"""`TS-49` (issue #130) — the console starts and renders on a clean machine: no npm toolchain, no
build step, no network at render time.

Test plan §5.19 `TC-CONSOLE-34` (`NFR-CONSOLE-02`), Smoke / rung 2, oracle *exact success*.

**What this adds over `CT-CONSOLE-C21` and `TC-SMOKE-07`.** Both read the console through the
headless `render()` — the smoke case says so, and says the render is "the same page the child
serves". A clean machine is where that claim is tested: the console is started as its own
process, with every Node/npm directory stripped from `PATH` (asserted, not assumed), over a real
store, and its index is fetched **over the loopback socket** the way the teacher's browser would.
"Starts and renders" means the served response is the console's rendered S1 page — HTML carrying
the screen's title — and the stylesheet every page references is served from the same origin
(assets are vendored locally, HLD §11.7; there is no build step to produce them).

The render-time half stays in-process: every screen rendered over the same store under the suite's
socket guard, with `assert_no_network()` as the positive proof that no request left the process.

The socket guard is stood down only around the loopback fetches, and reinstalled.

**Written ahead of implementation.** The issue says `yes`; stale — `M-CONSOLE` landed (#122).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from aeh.console import build_console
from aeh.store import open_store
from tests.support.console_world import seed_scored_run

pytestmark = [pytest.mark.integration]

_REPO_ROOT = Path(__file__).resolve().parents[3]

_CHILD = textwrap.dedent(
    """
    import shutil, sys, time
    assert shutil.which("node") is None and shutil.which("npm") is None, "toolchain on PATH"
    import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge
    import aeh.orch, aeh.pkg, aeh.review, aeh.synth
    from aeh.console import start_console
    from aeh.store import open_store
    store = open_store(sys.argv[1])
    server = start_console({"HARNESS_PROFILE": "edge-local"}, store=store)
    print(server.socket.getsockname()[1], flush=True)
    sys.stdin.read()
    server.terminate()
    store.close()
    """
)


def _clean_path() -> str:
    """`PATH` with every directory holding a Node/npm executable removed."""
    kept = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        if any(shutil.which(tool, path=entry) for tool in ("node", "npm", "npx")):
            continue
        kept.append(entry)
    return os.pathsep.join(kept)


def _http_get(port: int, path: str, timeout: float = 5.0) -> tuple[int | None, str, str]:
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.getheader("Content-Type") or "", response.read().decode(
            "utf-8", "replace")
    except OSError as error:
        return None, "", f"{type(error).__name__}: {error}"
    finally:
        connection.close()


@pytest.mark.writtenahead
def test_tc_console_34_the_console_starts_and_serves_its_pages_with_no_toolchain_or_network(
    tmp_data_dir, network_guard
):
    """`TC-CONSOLE-34` — exact success, collected:

    1. with no Node/npm on `PATH`, the console process starts over a real store and reports its
       port;
    2. `GET /` on that port answers 200 `text/html` with the rendered S1 page (`<title>Packages`);
    3. `GET /assets/console.css` — the stylesheet every page links — answers 200 from the same
       origin;
    4. every screen renders in-process over the same store with zero network attempts;
    5. the repository carries no client build manifest (`package.json`) or toolchain output.
    """
    store = open_store(tmp_data_dir)
    world = seed_scored_run(store, submissions=1)
    problems: list[str] = []

    app = build_console(store=store)
    for screen, route in app.screens().items():
        html = app.render(route, id=world.run_id, ref=world.submissions[0],
                          version=world.package_version_id).html
        if not html.startswith("<!doctype html>"):
            problems.append(f"{screen} did not render a page in-process")
    network_guard.assert_no_network()
    store.close()

    for manifest in ("package.json", "package-lock.json", "node_modules", "webpack.config.js"):
        if (_REPO_ROOT / manifest).exists():
            problems.append(f"the repository carries {manifest}: a build step exists")

    env = dict(os.environ, PATH=_clean_path(),
               PYTHONPATH=os.pathsep.join([str(_REPO_ROOT / "src"), str(_REPO_ROOT)]))
    child = subprocess.Popen(
        [sys.executable, "-c", _CHILD, str(tmp_data_dir)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        text=True,
    )
    try:
        # A child that hangs before reporting its port must fail the case, not hang it.
        import threading

        first_line: list[str] = []
        reader = threading.Thread(target=lambda: first_line.append(child.stdout.readline()),
                                  daemon=True)
        reader.start()
        reader.join(60)
        line = first_line[0].strip() if first_line else "<no output within 60s>"
        if not line.isdigit():
            child.kill()
            problems.append(f"the console process did not start on a clean PATH: "
                            f"{line!r} {child.stderr.read()[-800:]!r}")
            pytest.fail("\n\n".join(problems))
        port = int(line)
        network_guard.uninstall()
        try:
            index = _http_get(port, "/")
            stylesheet = _http_get(port, "/assets/console.css")
        finally:
            network_guard.install()
        status, content_type, body = index
        if status != 200 or "text/html" not in content_type or "<title>Packages</title>" not in body:
            problems.append(
                f"GET / on the started console's port {port} answered status={status}, "
                f"content-type={content_type!r}, body={body[:120]!r}. NFR-CONSOLE-02: the console "
                f"starts *and renders*. [When written: serve_console's configured socket listens "
                f"and never accepts, and its child answers every route with plain-text "
                f"'console page'.]"
            )
        status, content_type, body = stylesheet
        if status != 200:
            problems.append(
                f"GET /assets/console.css answered status={status} ({body[:80]!r}); every page "
                f"links this stylesheet. [A separate defect from the index: no such asset exists "
                f"anywhere in the repository to serve.]"
            )
    finally:
        if child.poll() is None:
            try:
                child.communicate(input="", timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
    assert not problems, "\n\n".join(problems)
