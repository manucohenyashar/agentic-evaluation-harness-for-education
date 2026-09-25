"""`TS-90` (issue #384) — `SEC-17`: no slug outside `CONTROL_SURFACE_ACTIONS` can reach a
store (elevation of privilege, an undeclared write path).

| Input | Expected |
|---|---|
| every slug in `({route segments crawled from /} ∪ {50 generated slugs}) \\ CONTROL_SURFACE_ACTIONS` | 404 each, and zero store writes |

**What the threat is.** The console's control surface is an allow-list, and an allow-list is
only as good as the set of things it is asked about. `TC-CONSOLE-43` checks one hand-picked
undeclared slug; that catches an allow-list that was deleted, not one with a hole in it. This
case attacks the boundary from two directions at once:

* **Crawled slugs** — every path segment reachable from `/`. These are the names the console
  itself puts in front of an operator, so they are the names an attacker reads off the page
  and the ones most likely to have a half-wired handler behind them.
* **Generated slugs** — 50 plausible action names built from the verbs and nouns the real
  control surface uses. These probe for a handler that was added and never added to the
  allow-list, which is the ordinary way a hole appears.

**The oracle is the store, not the status code.** A 404 with a write behind it is worse than a
200: the client is told nothing happened and something did. So every request runs under a
fingerprint of the whole data directory, and the assertion is that not one byte moved.

**Isolation: rung 3** — a real socket, real HTTP, a real store on disk.
"""

from __future__ import annotations

import hashlib
import http.client
import re
from urllib.parse import urlsplit

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.console import CONTROL_ACTION_SLUGS, serve_console
from aeh.store import open_store

pytestmark = pytest.mark.integration

#: The verbs and nouns the real control surface is built from, recombined. A handler added
#: without an allow-list entry is overwhelmingly likely to be named out of this vocabulary.
_VERBS = ("start", "stop", "pause", "resume", "finalize", "export", "delete", "drop",
          "purge", "reset")
_NOUNS = ("run", "batch", "cohort", "package", "tables", "labels", "grades", "queue",
          "store", "database")


def _generated_slugs() -> list[str]:
    return [f"{verb}-{noun}" for verb in _VERBS for noun in _NOUNS][:50]


@pytest.fixture
def served(tmp_data_dir, network_guard, monkeypatch):
    """A real console over a real store, with a run seeded so the tiers exist on disk."""
    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    from tests.support.orch_run import seed_run

    store = open_store(tmp_data_dir)
    seed_run(
        store,
        submissions=("S001",),
        criteria=({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},),
    )
    network_guard.uninstall()
    try:
        server = serve_console(store=store)
    except BaseException:
        network_guard.install()
        store.close()
        raise
    _host, port = server.socket.getsockname()[:2]
    try:
        yield port, tmp_data_dir
    finally:
        try:
            server.terminate()
        finally:
            network_guard.install()
            store.close()


def _request(port: int, method: str, path: str, body: bytes | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(method, path, body=body)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _fingerprint(root) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _crawled_segments(port: int) -> set[str]:
    """Every path segment reachable from `/`, one hop deep.

    One hop is enough: the console's routes are flat, and the point is the names the page
    puts in front of an operator rather than an exhaustive site map.
    """
    _status, body = _request(port, "GET", "/")
    html = body.decode("utf-8", "replace")
    segments: set[str] = set()
    for href in re.findall(r'(?:href|action)="([^"]+)"', html):
        path = urlsplit(href).path
        for segment in path.strip("/").split("/"):
            if segment and re.fullmatch(r"[A-Za-z0-9._-]+", segment):
                segments.add(segment)
    return segments


# --- SEC-17 -----------------------------------------------------------------------------------


def test_sec_17_the_probe_set_is_non_empty_and_excludes_the_allow_list(served):
    """The set difference is real: crawled ∪ generated, minus the declared slugs.

    Asserted first because every assertion below is over this set. A crawl that found nothing
    and a generator that produced nothing would make the sweep pass without sending a request
    that could have done anything.
    """
    port, _data_dir = served
    probes = (_crawled_segments(port) | set(_generated_slugs())) - set(CONTROL_ACTION_SLUGS)

    assert len(probes) >= 50, (
        f"the probe set holds {len(probes)} slugs; the generated half alone is 50 and the "
        "crawl adds the page's own segments"
    )
    assert not probes & set(CONTROL_ACTION_SLUGS), (
        "the probe set includes declared control actions, which are supposed to work"
    )


def test_sec_17_no_undeclared_slug_is_routed_or_writes_anything(served):
    """Every undeclared slug answers 404, and the store is byte-identical afterwards.

    One fingerprint around the whole sweep rather than one per request: a write that happened
    and was undone would still be a write path, but a per-request comparison over ~60 requests
    costs a full directory hash each time and buys nothing the final comparison does not —
    any surviving change shows up here, and the status codes localize which slug did it.
    """
    port, data_dir = served
    probes = sorted(
        (_crawled_segments(port) | set(_generated_slugs())) - set(CONTROL_ACTION_SLUGS)
    )
    before = _fingerprint(data_dir)
    assert before, "the fixture wrote no store files, so the write audit is vacuous"

    routed = {}
    for slug in probes:
        status, _body = _request(port, "POST", f"/actions/{slug}", b"")
        if status != 404:
            routed[slug] = status

    assert routed == {}, (
        f"undeclared action slugs were routed: {routed}. The allow-list is the control "
        "surface; a slug outside it must not reach a handler at all (SEC-17)"
    )

    after = _fingerprint(data_dir)
    changed = sorted(
        name for name in set(before) | set(after) if before.get(name) != after.get(name)
    )
    assert changed == [], (
        f"{len(probes)} undeclared action slugs changed {changed}. A 404 with a write behind "
        "it is worse than a 200: the client is told nothing happened and something did"
    )


def test_sec_17_a_declared_slug_still_reaches_its_handler(served):
    """The positive control: the allow-list's own members are not 404.

    Without it the sweep passes against a console that 404s every POST — no control surface at
    all, which would be perfectly secure and useless.
    """
    port, _data_dir = served
    slug = sorted(CONTROL_ACTION_SLUGS)[0]

    status, _body = _request(port, "POST", f"/actions/{slug}", b"")

    assert status != 404, (
        f"the declared slug {slug!r} answered 404; the allow-list refuses its own members and "
        "the sweep above proves nothing"
    )


def test_sec_17_path_traversal_in_a_slug_is_refused(served):
    """A slug carrying `..` or an encoded separator is 404 and writes nothing.

    Not in the plan's generated set, and the shape most likely to reach something the
    allow-list never considered: the lookup is a dict `get` on the text after `/actions/`, so
    a separator inside it is only safe because nothing ever joins it to a path.
    """
    port, data_dir = served
    before = _fingerprint(data_dir)

    for slug in ("../../etc/passwd", "..%2f..%2fstore", "finalize-batch/../drop-tables", "."):
        status, _body = _request(port, "POST", f"/actions/{slug}", b"")
        assert status == 404, f"the traversal slug {slug!r} answered {status}"

    after = _fingerprint(data_dir)
    assert before == after, "a traversal slug changed the store"
