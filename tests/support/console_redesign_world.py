"""The rung-3 world the console-redesign suite (#771, `TC-CONSOLE-59..73`) drives: a real
store, a real console over a real loopback socket, the recorded provider as the only
transport, and the seeded ledgers the reads answer from.

Two served fixtures, one store discipline:

* `served_console` — the plain console over an empty (or test-seeded) store, for the reads
  and actions that need no authoring corpus.
* `served_authoring` — the same, with the authoring corpus wired in: `HARNESS_PROFILE` set
  to `dev-ci`, `HARNESS_FIXTURE_DIR` pointed at the F-AUTHOR recordings, and a
  configuration whose dev-ci panel/transcriber name the builds the corpus was recorded
  against.

**The recorded chain is declared here, and that is a disclosed reconcile.** The F-AUTHOR
recordings are keyed on the assembled request, build id included (`author_vocabulary`'s
corpus coupling). The repo's `live-test.dev-ci.toml` has since been re-pinned to a
different head (`gpt-6-luna`, commit `aea6eeb`), so a draft run through the repo file's
own chain misses every recording and ends in the fallback — the ~35 author-recording reds
the fast-tier baseline already carries. This suite's cases must see the recorded world
the corpus documents, so the configuration the console is served with names the recorded
builds directly — the same reconciliation `chain_from_config()` performs for the rung-1
suite, one level up: if the corpus is re-recorded through another chain, the two refs
below are the fix, here and nowhere else.

Everything else is the shipped code: the store is `open_store`'s (never a spy), the
control surface is reached over real HTTP (`_request`), and the network guard is
uninstalled only for the served window, then reinstalled — the `TC-CONSOLE-43` precedent,
which is where this fixture shape comes from.
"""

from __future__ import annotations

import base64
import http.client
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain before the first store open (CLAUDE.md)
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
from aeh.console import serve_console
from aeh.store import open_store

from tests.support.author_vocabulary import RECORDINGS, af

#: The transcriber build the F-AUTHOR corpus was recorded against (the recordings' own
#: `model_ref.build_id`s; see the module docstring's reconcile).
RECORDED_TRANSCRIBER = "openrouter/qwen/qwen3-vl-8b-instruct@2026-06-01"

#: The reasoning-chain head the F-AUTHOR corpus was recorded against — the recorded
#: dev-ci profile's single judge (`[[panel]]`, no `[[escalation_judge]]` section).
RECORDED_JUDGE = "openrouter/qwen/qwen3-30b-a3b@2026-06-01"


def recorded_authoring_config() -> dict[str, Any]:
    """The configuration the console is served with for the recorded authoring world: a
    dev-ci profile whose transcriber and panel are the corpus's recorded builds. Raw
    model tables are accepted (`authoring_service` converts), so the plain dict form is
    the config file's own shape."""
    return {
        "profiles": {
            "dev-ci": {
                "transcriber": {
                    "role": "transcriber", "provider": "openrouter",
                    "build_id": RECORDED_TRANSCRIBER,
                },
                "panel": [
                    {"role": "judge", "provider": "openrouter",
                     "build_id": RECORDED_JUDGE},
                ],
            },
        },
    }


def _request(port: int, method: str, path: str, body: dict[str, Any] | None = None):
    """One HTTP request to the served console; `(status, headers, body-bytes)`."""
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        return response.status, dict(response.getheaders()), raw
    finally:
        connection.close()


def _get_json(port: int, path: str) -> Any:
    """One GET read's JSON answer; the caller asserts the status it asked for."""
    status, _headers, raw = _request(port, "GET", path)
    assert status == 200, f"GET {path} answered {status}: {raw!r}"
    return json.loads(raw)


def _post_json(port: int, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """One POST's JSON answer with its status, for the cases that assert the status."""
    status, _headers, raw = _request(port, "POST", path, body)
    return status, json.loads(raw)


def _action(port: int, action: str, params: dict[str, Any]) -> dict[str, Any]:
    """One control action over HTTP: the 200 outcome the console answers with.

    `action` is the control surface's own spelling; the URL slug is the server's
    lowercase/hyphen rule, spelled here rather than imported so a case reads as its
    request."""
    status, answer = _post_json(
        port, f"/api/v1/actions/{action.lower().replace(' ', '-').replace('/', '-')}",
        params)
    assert status == 200, f"{action} answered {status}: {answer!r}"
    return answer


def wait_for_job(port: int, job_id: str, *, timeout: float = 60.0) -> dict[str, Any]:
    """Poll the jobs read until the named job reaches a terminal state, and return its
    final record. The poll rides the console's own read (`GET /api/v1/jobs/<id>`), never
    the registry's internals."""
    deadline = time.monotonic() + timeout
    terminal = {"succeeded", "failed", "cancelled"}
    while True:
        record = _get_json(port, f"/api/v1/jobs/{job_id}")
        if record["state"] in terminal:
            return record
        if time.monotonic() > deadline:
            raise AssertionError(
                f"job {job_id} did not finish within {timeout}s; last record: {record!r}")
        time.sleep(0.05)


class PacedRecordedProvider:
    """The recorded provider with one paced `complete()`: the first call announces
    itself on `gate` and blocks on `release` before replaying the recording.

    The transport stays the recorded one — every reply is the recording's own — and only
    the timing is scripted, the way the ingest suite's scripted rasterizer stands in for
    the PDF engine. A cancel test needs a draft that is provably *mid-flight* when the
    cancel lands; an unpaced recorded draft finishes between two polls, and a test that
    then asserted "cancelled" would be asserting a race."""

    def __init__(self, inner: Any, gate: threading.Event, release: threading.Event) -> None:
        self._inner = inner
        self._gate = gate
        self._release = release
        self.calls = 0

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        self.calls += 1
        self._gate.set()
        if not self._release.wait(timeout=120):
            raise AssertionError("the cancel test never released the paced model call")
        return self._inner.complete(prompt, model_ref, params)

    def capabilities(self, model_ref: Any) -> Any:
        return self._inner.capabilities(model_ref)

    def estimate_cost(self, plan: Any) -> Any:
        return self._inner.estimate_cost(plan)

    def verify_retention(self, model_refs: Any) -> Any:
        return self._inner.verify_retention(model_refs)


def _close_console_store(store) -> None:
    """Close the fixture's store, tolerating the cross-thread close the console's own
    design invites. When a package exists, a context read's setup step
    (`app._setup_blocking_steps`) touches the caller's store from a server thread, and
    that thread constructs the tier handle — whose own connection can then only be
    closed from that thread. The shipped close already tolerates the cross-thread case
    for the per-thread readers it tracks (`tier_handle._read_connection`'s docstring:
    "`close()` runs on a *different* thread"); the handle's own connection is the one
    strictness that remains. A test fixture that handed the console its store hits it at
    teardown, after every assertion has run — the handle dies with the process, which is
    what the shipped tolerance is for."""
    try:
        store.close()
    except Exception as error:  # noqa: BLE001 — teardown after the assertions, either way
        if "can only be used in that same thread" not in str(error):
            raise


@pytest.fixture
def served_console(tmp_data_dir, network_guard, monkeypatch):
    """A real console on a real loopback port over a real store, with no profile set.

    Yields `(server, port, store, data_dir)`; the network guard is uninstalled for the
    served window and reinstalled on the way out, whichever way the body ends."""
    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    store = open_store(tmp_data_dir)
    network_guard.uninstall()
    try:
        server = serve_console(store=store)
    except BaseException:
        network_guard.install()
        _close_console_store(store)
        raise
    _host, port = server.socket.getsockname()[:2]
    try:
        yield server, port, store, tmp_data_dir
    finally:
        try:
            server.terminate()
        finally:
            network_guard.install()
            _close_console_store(store)


@pytest.fixture
def served_authoring(tmp_data_dir, network_guard, monkeypatch):
    """The served console with the recorded authoring corpus wired in.

    `HARNESS_PROFILE=dev-ci` (the profile the draft job resolves its provider and chain
    from), `HARNESS_FIXTURE_DIR` at the F-AUTHOR recordings, and the configuration
    carrying the recorded builds. Yields `(server, port, store, data_dir)`."""
    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HARNESS_PROFILE", "dev-ci")
    monkeypatch.setenv("HARNESS_FIXTURE_DIR", str(RECORDINGS))
    store = open_store(tmp_data_dir)
    network_guard.uninstall()
    try:
        server = serve_console(store=store, cfg=recorded_authoring_config())
    except BaseException:
        network_guard.install()
        _close_console_store(store)
        raise
    _host, port = server.socket.getsockname()[:2]
    try:
        yield server, port, store, tmp_data_dir
    finally:
        try:
            server.terminate()
        finally:
            network_guard.install()
            _close_console_store(store)


# --- the recorded authoring journeys the cases share ----------------------------------------------------


def af_documents(fixture: str) -> list[dict[str, str]]:
    """A fixture's document set as the draft action's JSON carries it: the files' names
    and their base64 bodies, read from the corpus directory itself."""
    documents: list[dict[str, str]] = []
    for path in sorted(af(fixture).glob("*.pdf")):
        documents.append({
            "name": path.name,
            "content_base64": base64.b64encode(path.read_bytes()).decode(),
        })
    return documents


def start_draft(port: int, fixture: str = "AF-02", *, replace: bool = False) -> dict[str, Any]:
    """One `draft package from documents` action over a recorded fixture's documents."""
    params: dict[str, Any] = {"documents": af_documents(fixture)}
    if replace:
        params["replace"] = True
    return _action(port, "draft package from documents", params)


def draft_path_in(data_dir: Path, package_id: str) -> Path:
    """The draft file a finished job wrote for the named package, under the authoring
    folder the draft action names in its detail. A test that reads the draft file reads
    the same bytes the console's own reads answer from."""
    return Path(data_dir, "authoring", f"{package_id}.package.draft.toml")


def draft_read(port: int) -> dict[str, Any]:
    """The authoring draft read's document (`GET /api/v1/authoring/draft`)."""
    return _get_json(port, "/api/v1/authoring/draft")


def run_draft_job(port: int, fixture: str = "AF-02", *, replace: bool = False,
                  timeout: float = 90.0) -> tuple[dict[str, Any], dict[str, Any]]:
    """Start a recorded draft job and wait it out: `(the action's outcome, the job's
    terminal record)`."""
    answer = start_draft(port, fixture, replace=replace)
    assert answer["dispatched"], f"the draft action did not dispatch: {answer!r}"
    record = wait_for_job(port, answer["job_id"], timeout=timeout)
    return answer, record


__all__ = [
    "PacedRecordedProvider",
    "RECORDED_JUDGE",
    "RECORDED_TRANSCRIBER",
    "af_documents",
    "draft_path_in",
    "draft_read",
    "recorded_authoring_config",
    "run_draft_job",
    "served_authoring",
    "served_console",
    "start_draft",
    "wait_for_job",
]
