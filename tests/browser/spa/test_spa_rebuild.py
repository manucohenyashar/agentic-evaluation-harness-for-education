"""Issue #639 — `TC-UI-01 (c)` / `TC-UI-C06`: the committed bundle is what the committed source
builds to, with the pinned toolchain (FR-UI-01, CT-UI-06, RISK-117).

**Why this is E6, not the fast tier.** The delta's rule (operator test plan §4 rule 2): *"no Node
anywhere in the installed system or the test tiers below E6."* The rebuild needs Node, so it runs
where the browser does — `browser` + `integration` — and skips, naming the missing piece, on a
machine without `node`/`npm` on PATH. The rung-0 halves (present, swept, shipped) are in
`tests/artifact/test_spa_bundle_gate.py` and need no toolchain.

**Never in place.** The source is copied to a temporary directory and built there into a second
temporary directory: rebuilding over `src/aeh/console_assets/spa` would dirty the tree and race
every case that reads the bundle. The comparator is `spa.bundle_diff`, whose stale-bundle control
runs green in the fast tier.

**Written ahead of #634** (`writtenahead`, keyed in `WRITTEN_AHEAD_BLOCKERS` on the bundle's
`index.html`). `npm ci` reads the registry or the local npm cache; on an air-gapped box with a cold
cache it fails, and the failure says so rather than reading as a stale bundle.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from tests.support import spa
from tests.support.impl import require_path

pytestmark = [pytest.mark.browser, pytest.mark.integration]

#: The rebuild's budget, env-gated (seam 3): `npm ci` plus a production build on the reference box.
REBUILD_TIMEOUT_S = int(os.environ.get("HARNESS_UI_REBUILD_TIMEOUT_S", "600"))


@pytest.mark.writtenahead
def test_tc_ui_01_c_tc_ui_c06_a_rebuild_from_committed_source_is_byte_identical(tmp_path):
    """`TC-UI-01 (c)` / `TC-UI-C06` (P0) — install the locked toolchain (`npm ci` against the
    committed lockfile) and build the committed source into a fresh directory; the result equals
    the committed bundle byte for byte, file set included. A stale bundle — source edited, bundle
    not rebuilt — fails here, which is what makes the committed bundle trustworthy as the release."""
    require_path(spa.BUNDLE_INDEX, "the committed SPA bundle (FR-UI-01)", issue="#634")
    require_path(spa.SPA_LOCKFILE, "the SPA toolchain lockfile (Q-O3's pin)", issue="#634")
    npm = shutil.which("npm")
    if npm is None or shutil.which("node") is None:
        pytest.skip("E6 rebuild unavailable: node/npm are not on PATH (the pinned dev toolchain)")

    source = tmp_path / "ui"
    shutil.copytree(spa.SPA_SOURCE_DIR, source,
                    ignore=shutil.ignore_patterns("node_modules", "dist", ".vite"))
    out = tmp_path / "rebuilt"

    def run(argv: tuple[str, ...], what: str) -> None:
        completed = subprocess.run([npm, *argv[1:]], cwd=source, capture_output=True, text=True,
                                   timeout=REBUILD_TIMEOUT_S)
        assert completed.returncode == 0, (
            f"{what} failed (exit {completed.returncode}) — the committed source does not build "
            f"with the pinned toolchain:\n{completed.stdout[-2000:]}\n{completed.stderr[-2000:]}")

    run(spa.INSTALL_COMMAND, "npm ci (the locked toolchain)")
    run(tuple(part.replace("{out}", str(out)) for part in spa.BUILD_COMMAND), "the bundle build")
    assert spa.bundle_files(out), f"the build wrote nothing to {out}"
    differences = spa.bundle_diff(spa.BUNDLE_DIR, out)
    assert not differences, (
        "the committed bundle is stale — it is not what the committed source builds to "
        "(CT-UI-06). Rebuild and commit it:\n  " + "\n  ".join(differences[:40]))
