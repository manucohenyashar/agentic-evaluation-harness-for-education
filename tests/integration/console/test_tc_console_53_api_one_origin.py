"""`TS-147` (issue #628) — `TC-CONSOLE-53`: the console API and the SPA come from one origin,
every mutating API route is an enumerated control write, and no served byte names another
origin (`FR-CONSOLE-45`, `CT-CONSOLE-30`, RISK-108, RISK-115).

Operator-requirements test plan §5.6. **Rung 2**: a real `serve_console` on the loopback bind
over a real (fixture) store, real HTTP on a real socket, the network guard installed and
loosened for loopback only (`loopback_census`), so a fetch the *server* makes to anywhere else
is refused and recorded, which no byte sweep could see.

**Written ahead of #629.** The API, its route table and the bundle seam do not exist yet; the
names these cases hold are invented once, in `tests/support/console_api_vocabulary.py`, which
says what #629 is asked to provide. Every case fails with `NotImplementedYet` naming #629 until
it lands. One arm — the shipped bundle — waits on **#634** instead, which puts the built SPA at
the package-data path; until then there is no bundle to serve, and #629's own acceptance
criterion says so.

| Arm | What is asserted |
|---|---|
| (a) | `GET /` and every asset it loads (and every `/assets/…` file) answer 200 from this server with the suffix's `Content-Type`, the served bytes equal the bundle's, and no redirect leaves the origin |
| (a) shipped | the same over `SPA_BUNDLE_DIR` with no seam, plus the full sweep — keyed on #634 |
| (b) census | the table lists every mutating route beside the control action it writes; no orphans; the fifteen are all reachable; every API path is versioned |
| (b) door | each mutating route reaches `ConsoleApp.perform` with exactly its mapped action, exactly once — a label is not trusted, the dispatch is observed |
| (b) unlisted | a mutating verb on a path the table does not list is 404/405, calls no door, changes no stored byte |
| (b) reads | fetching every read route calls no door and changes no stored byte — a GET that writes is a second write path a method census cannot see |
| (c) | every byte served — page, assets, API reads, API mutation answers, a 404 — carries no absolute non-loopback URL; the server opened no non-loopback connection |
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

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
from aeh.store import open_store
from tests.support.console_api_vocabulary import (
    API_ISSUE,
    BUNDLE_ISSUE,
    CLEAN_BUNDLE,
    MUTATING_METHODS,
    NON_CONTROL_MUTATIONS,
    READ_METHODS,
    ROUTE_TABLE,
    SPA_BUNDLE_DIR,
    VERSIONED_API_PATH,
    concrete_path,
    content_type_matches,
    crawl_spa,
    external_references,
    fetch,
    matches_template,
    mutating_rows,
    on_loopback,
    orphan_mutations,
    route_rows,
    start_console,
    write_bundle,
)
from tests.support.impl import CONSOLE_MODULE, require

pytestmark = pytest.mark.integration

JSON_HEADERS = {"Content-Type": "application/json"}


@pytest.fixture
def store(tmp_data_dir, monkeypatch):
    """A real store on a fresh data directory, with the console's environment knobs cleared."""
    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    opened = open_store(tmp_data_dir)
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture
def bundle_dir(tmp_path):
    return write_bundle(tmp_path / "spa", CLEAN_BUNDLE)


def _api():
    """The server and its route table — `require`d in the test body, so a missing name is a
    `NotImplementedYet` failure naming #629, never a collection error."""
    serve, routes = require(CONSOLE_MODULE, "serve_console", ROUTE_TABLE, issue=API_ISSUE)
    return serve, list(routes)


def _fingerprint(root) -> dict[str, str]:
    """Every file under the data directory, by content hash — the write audit (TC-CONSOLE-43's)."""
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))


class _DoorSpy:
    """Stands in for `ConsoleApp.perform` on one app instance: records every call and writes
    nothing, answering with a `ControlOutcome`-shaped refusal-free no-op."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, action: str, **params: Any) -> Any:
        self.calls.append((action, params))
        return SimpleNamespace(rows_written=(), refused=False, refresh_required=False,
                               dispatched=False, detail="door spy: nothing written")


def _non_vacuous_table(routes: list[Any]) -> None:
    assert routes, (
        f"{ROUTE_TABLE} is empty: a census over no routes has no orphans and proves nothing "
        "(FR-CONSOLE-45 requires the control surface exposed as an API)"
    )


# --- (a) the SPA from this origin ------------------------------------------------------------


def _assert_spa_served_from_this_origin(port: int, bundle: dict[str, bytes]) -> dict:
    served, leaving = crawl_spa(port)

    assert not leaving, f"a redirect left the console's origin: {leaving} (CT-CONSOLE-30)"
    status, headers, body = served["/"]
    assert status == 200, f"GET / answered {status}, not the SPA"
    assert content_type_matches("/", headers.get("content-type", "")), (
        f"GET / answered Content-Type {headers.get('content-type')!r}, not text/html"
    )
    assert body == bundle["index.html"], (
        "GET / did not serve the bundle's index.html byte for byte — the SPA is served from "
        "the package-data path, not rendered (FR-CONSOLE-45)"
    )
    loaded = [path for path in served if path != "/"]
    assert len(loaded) >= 3, (
        f"the page loaded only {loaded}: the crawl must see real assets before its silence "
        "about other origins means anything"
    )
    for path in loaded:
        status, headers, body = served[path]
        assert status == 200, f"the SPA's asset {path} answered {status}"
        assert content_type_matches(path, headers.get("content-type", "")), (
            f"{path} answered Content-Type {headers.get('content-type')!r}"
        )
        relative = path.lstrip("/")
        if relative in bundle:
            assert body == bundle[relative], f"{path} is not the bundle's file byte for byte"
    # Every asset the bundle ships, whether or not this page loads it.
    for relative, data in bundle.items():
        if not relative.startswith("assets/"):
            continue
        status, headers, body = fetch(port, "GET", "/" + relative)
        assert (status, body) == (200, data), f"GET /{relative} answered {status}, not the file"
        assert content_type_matches(relative, headers.get("content-type", "")), (
            f"/{relative} answered Content-Type {headers.get('content-type')!r}"
        )
    return served


def test_tc_console_53_a_the_spa_and_its_assets_come_from_this_origin_with_their_types(
    store, bundle_dir, network_guard
):
    """`GET /` and `/assets/…` serve the bundle the server was given, from its own port, with
    each file's media type and no redirect elsewhere."""
    serve, _routes = _api()
    server = start_console(serve, store, spa_dir=bundle_dir)

    with on_loopback(server, network_guard) as (port, _census):
        _assert_spa_served_from_this_origin(port, CLEAN_BUNDLE)

    network_guard.assert_no_network()


@pytest.mark.writtenahead
def test_tc_console_53_a_the_shipped_bundle_is_served_and_names_no_other_origin(
    store, network_guard
):
    """The real bundle at the package-data path, with no seam: served byte for byte, and every
    byte it and the API send swept (RISK-108). Waits on #634, which ships the bundle."""
    serve, routes = _api()
    bundle_root = require(CONSOLE_MODULE, SPA_BUNDLE_DIR, issue=API_ISSUE)
    from pathlib import Path

    root = Path(bundle_root)
    assert (root / "index.html").is_file(), (
        f"no built SPA at {root} (blocked on {BUNDLE_ISSUE}: the bundle ships as package data)"
    )
    bundle = {
        str(p.relative_to(root)).replace("\\", "/"): p.read_bytes()
        for p in root.rglob("*") if p.is_file()
    }
    server = start_console(serve, store)

    with on_loopback(server, network_guard) as (port, _census):
        served = _assert_spa_served_from_this_origin(port, bundle)
        for method, path, _control in route_rows(routes):
            if method == "GET":
                served[f"GET {path}"] = fetch(port, "GET", concrete_path(path))

    offenders = {
        path: refs for path, (_s, headers, body) in served.items()
        if (refs := external_references(body, headers.get("content-type", "")))
    }
    assert not offenders, f"served bytes name external origins: {offenders} (RISK-108)"
    network_guard.assert_no_network()


# --- (b) the route census ------------------------------------------------------------------


def test_tc_console_53_b_the_census_lists_every_mutating_route_beside_its_control_row():
    """The table, read as the census: each mutating route beside the control action it writes,
    no orphans, every API path versioned, every read route writing nothing, and all fifteen
    enumerated controls reachable — the API exposes the control surface, not part of it."""
    _serve, routes = _api()
    CONTROL_SURFACE_ACTIONS = require(CONSOLE_MODULE, "CONTROL_SURFACE_ACTIONS")
    _non_vacuous_table(routes)
    rows = route_rows(routes)
    census = "\n".join(f"  {m:6} {p:48} -> {c}" for m, p, c in rows)

    unknown_verbs = [row for row in rows if row[0] not in READ_METHODS | MUTATING_METHODS]
    assert not unknown_verbs, f"routes with no HTTP verb this census reads: {unknown_verbs}"
    reads_that_write = [row for row in rows if row[0] in READ_METHODS and row[2] is not None]
    assert not reads_that_write, (
        f"read routes labelled with a control write: {reads_that_write} — a GET is never a "
        "mutation (FR-CONSOLE-02's idempotence is per control row, not per page view)"
    )
    orphans = orphan_mutations(routes, CONTROL_SURFACE_ACTIONS)
    assert not orphans, (
        f"mutating routes no enumerated control row backs: {orphans}\ncensus:\n{census}\n"
        "Every API mutation is one of the fifteen (FR-CONSOLE-45, RISK-115); a new one is "
        "added to the enumeration first, never to the API alone."
    )
    unversioned = [
        row for row in rows
        if row[2] not in NON_CONTROL_MUTATIONS and not VERSIONED_API_PATH.match(row[1])
    ]
    assert not unversioned, (
        f"API routes outside a versioned /api/v<N>/ prefix: {unversioned} (FR-CONSOLE-45)"
    )
    reachable = {row[2] for row in mutating_rows(routes)}
    missing = sorted(set(CONTROL_SURFACE_ACTIONS) - reachable)
    assert not missing, (
        f"enumerated controls the API cannot reach: {missing}\ncensus:\n{census}\n"
        "FR-CONSOLE-45 exposes the control surface; a control only the retired HTML console "
        "offered is a lifecycle step the SPA cannot perform."
    )


def test_tc_console_53_b_every_mutating_route_reaches_exactly_its_control_row(
    store, bundle_dir, network_guard, monkeypatch
):
    """A label is not a dispatch. Each mutating route is posted to, and `ConsoleApp.perform`
    must be called once, with exactly the action the census names — a route labelled
    `start run` that writes something else, or writes beside the door, is the second write path
    RISK-115 names."""
    serve, routes = _api()
    _non_vacuous_table(routes)
    server = start_console(serve, store, spa_dir=bundle_dir)
    spy = _DoorSpy()
    monkeypatch.setattr(server.app, "perform", spy)
    wrong: list[str] = []

    with on_loopback(server, network_guard) as (port, _census):
        for method, path, control in mutating_rows(routes):
            if control in NON_CONTROL_MUTATIONS:
                continue  # the upload streams to blobs (FR-CONSOLE-04); it has no control row
            spy.calls.clear()
            status, _h, _b = fetch(port, method, concrete_path(path), b"{}", JSON_HEADERS)
            dispatched = [action for action, _params in spy.calls]
            if dispatched != [control]:
                wrong.append(f"{method} {path} (census: {control!r}) -> {status}, "
                             f"perform called with {dispatched}")

    assert not wrong, (
        "mutating routes whose dispatch is not the control row the census lists:\n  "
        + "\n  ".join(wrong)
    )
    network_guard.assert_no_network()


def test_tc_console_53_b_a_mutating_verb_on_an_unlisted_path_writes_nothing(
    store, tmp_data_dir, bundle_dir, network_guard, monkeypatch
):
    """Outside the table there is no mutation: an invented API path under every mutating verb,
    and every read route under every mutating verb it does not list, answer 404 or 405, reach
    no door, and change no stored byte."""
    serve, routes = _api()
    _non_vacuous_table(routes)
    rows = route_rows(routes)
    version = next(
        (m.group(0) for _m, p, _c in rows if (m := VERSIONED_API_PATH.match(p))), "/api/v1/"
    )
    def _routed(verb: str, concrete: str) -> bool:
        # A probe path a listed template of the same verb would legitimately route is not
        # unlisted: `/api/v1/packages/current` probed with PUT is `PUT /packages/{version}`.
        return any(m == verb and matches_template(p, concrete) for m, p, _c in rows)

    probes = [(verb, f"{version}drop-tables") for verb in sorted(MUTATING_METHODS)]
    probes += [
        (verb, path) for _m, path, _c in rows for verb in sorted(MUTATING_METHODS)
    ]
    probes = [(v, p) for v, p in probes if not _routed(v, concrete_path(p))]
    assert probes, "every probe is a listed route; the unlisted-path check would be vacuous"
    server = start_console(serve, store, spa_dir=bundle_dir)
    spy = _DoorSpy()
    monkeypatch.setattr(server.app, "perform", spy)
    before = _fingerprint(tmp_data_dir)
    answered: list[str] = []

    with on_loopback(server, network_guard) as (port, _census):
        for verb, path in dict.fromkeys(probes):
            status, _h, _b = fetch(port, verb, concrete_path(path), b"{}", JSON_HEADERS)
            if status not in (404, 405):
                answered.append(f"{verb} {path} -> {status}")

    assert not answered, f"unlisted mutating requests were accepted: {answered}"
    assert spy.calls == [], f"unlisted requests reached the control door: {spy.calls}"
    assert _changed(before, _fingerprint(tmp_data_dir)) == [], (
        "an unlisted mutating request changed the store (CT-CONSOLE-30: no mutation outside "
        "the enumerated control rows)"
    )
    network_guard.assert_no_network()


def test_tc_console_53_b_no_read_route_writes(
    store, tmp_data_dir, bundle_dir, network_guard, monkeypatch
):
    """Every read route fetched: no door called, no stored byte changed. A GET that writes is a
    mutation the method census cannot see, and the one the SPA's polling would repeat."""
    serve, routes = _api()
    _non_vacuous_table(routes)
    reads = [(m, p) for m, p, _c in route_rows(routes) if m in READ_METHODS]
    assert reads, f"{ROUTE_TABLE} lists no read route: the SPA has nothing to render from"
    server = start_console(serve, store, spa_dir=bundle_dir)
    spy = _DoorSpy()
    monkeypatch.setattr(server.app, "perform", spy)
    before = _fingerprint(tmp_data_dir)

    with on_loopback(server, network_guard) as (port, _census):
        statuses = {p: fetch(port, m, concrete_path(p))[0] for m, p in reads}

    assert spy.calls == [], f"read routes reached the control door: {spy.calls}"
    assert _changed(before, _fingerprint(tmp_data_dir)) == [], (
        f"fetching the read routes changed the store; statuses: {statuses}"
    )
    network_guard.assert_no_network()


# --- (c) the served-bytes sweep (RISK-108) --------------------------------------------------


def test_tc_console_53_c_no_served_byte_names_an_external_origin(
    store, bundle_dir, network_guard, monkeypatch
):
    """Everything the server sends — the page, its assets, every API read, every API mutation's
    answer, a 404 — swept for absolute non-loopback URLs. Zero (RISK-108). Headers are swept
    too: a `Location` or a `Link` preload is a fetch the body never names."""
    serve, routes = _api()
    _non_vacuous_table(routes)
    server = start_console(serve, store, spa_dir=bundle_dir)
    monkeypatch.setattr(server.app, "perform", _DoorSpy())
    responses: dict[str, tuple[int, dict[str, str], bytes]] = {}

    with on_loopback(server, network_guard) as (port, census):
        spa, _leaving = crawl_spa(port)
        responses.update({f"GET {p}": r for p, r in spa.items()})
        for method, path, control in route_rows(routes):
            if control in NON_CONTROL_MUTATIONS:
                continue
            body = None if method in READ_METHODS else b"{}"
            responses[f"{method} {path}"] = fetch(
                port, method, concrete_path(path), body, JSON_HEADERS if body else None
            )
        responses["GET /api/v1/no-such-route"] = fetch(port, "GET", "/api/v1/no-such-route")

    api_json = [
        key for key, (status, headers, body) in responses.items()
        if " /api/" in key and status == 200 and "json" in headers.get("content-type", "")
        and json.loads(body or b"null") is not None
    ]
    assert api_json, (
        "no API route answered 200 with a JSON body, so the sweep saw no API bytes: "
        f"{ {k: r[0] for k, r in responses.items()} }"
    )
    assert len(spa) >= 4, f"the crawl saw only {list(spa)}; the sweep needs the page and its assets"
    offenders = {}
    for key, (_status, headers, body) in responses.items():
        refs = external_references(body, headers.get("content-type", ""))
        refs += external_references(
            "\n".join(f"{k}: {v}" for k, v in headers.items()).encode("utf-8")
        )
        if refs:
            offenders[key] = refs
    assert not offenders, (
        f"served bytes name an origin other than the console's own: {offenders} (CT-CONSOLE-30, "
        "FR-CONSOLE-18 — at a school with no internet that request renders the console blank)"
    )
    assert census, "the sweep made no loopback connection: nothing was fetched"
    network_guard.assert_no_network()
