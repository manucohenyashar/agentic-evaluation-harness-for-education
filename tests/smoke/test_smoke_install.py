"""The smoke suite (TS-50, issue #143): a system that is broken in the ways that matter
fails here in minutes.

`TC-SMOKE-01` (`NFR-STORE-03`) — *"A clean virtualenv install completes with no npm
toolchain, no build step, no server process."* Fails if any additional install step is
required.

The oracle has two halves, because "no additional install step" is a claim about **what the
repository declares** and **what the source tree actually does**:

1.  **Declared** — `pyproject.toml` ships exactly the four standard dependencies of
    `FR-STORE-20` (ADR-36, #614, which superseded ADR-11's empty `dependencies = []`), so one
    pip step resolves everything from the package index, and no extras exist; and the tracked
    tree carries no npm manifest, no lockfile, no container image, no server-composition file.
    Anything a fresh machine needs beyond `python -m venv` and that one pip step is an
    additional install step by definition.
2.  **Demonstrated** — the `TC-STORE-19` pattern (issue #16): a subprocess whose environment
    carries nothing but the OS minimum and `HARNESS_DATA_DIR` imports the whole assembled
    system (the eleven migration-chain contributors) from the source tree, opens a store,
    writes and reads a row, and exits 0. Nothing is built, nothing is compiled, nothing
    listens: the system runs from source with no configuration beyond a data directory path.

Why the actual `pip install` is not re-run here: the socket guard (TS-00) is active for every
non-live test and pip needs the network, and a real venv bootstrap does not fit the smoke
budget (~60-90 s total, §6.1). The clean-environment case the plan owns is `TC-STORE-19`
(issue #16, `tests/integration/store/test_capacity.py`) — the store-side half; this case is
the whole-system version, which is why its child imports all eleven contributors rather than
`aeh.store` alone.

One residual masking vector the demonstration cannot see: its child runs on the dev venv's
interpreter, so an undeclared **eager** runtime import of a package that the dev venv
happens to carry would ride in with the interpreter and pass. The declared half (the exact
four-package set above) and the shipped lazy-import convention hold that line —
`pypdfium2`/`pypdf`/`PIL`/`typesafe_sdk` are imported inside the implementations that need
them, not at module top — which is why the demonstration is the second wall, not the only one.

`Written ahead of implementation: yes` is stale — every module the smoke suite drives is
landed (#42-#302); the suite runs green by design, exactly as §8.2's unmarking rule predicts.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_SRC = REPO_ROOT / "src"

#: File names whose presence anywhere in the tracked tree means an install step beyond pip
#: has entered the repository. Scanned on basename, with no path carve-out: the tracked
#: fixture `fixtures/package/reference-package.json` is Tier P package *data* (a reference
#: import) and its basename is not an npm manifest, so no fixtures/ exemption is needed —
#: and must not exist, or a future manifest placed under fixtures/ would escape the scan.
NPM_MANIFESTS = {"package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"}

#: Server-shaped install steps: anything the operator would have to start before the first
#: run. The console's loopback server is opt-in at runtime, not an install requirement.
SERVER_ARTIFACTS = {"Dockerfile", "docker-compose.yml", "docker-compose.yaml", "Vagrantfile"}

#: FR-STORE-20 (ADR-36, #614), transcribed rather than read back from the file under test: the
#: complete runtime set `pip install .` carries. Pip resolves these in the one install step, so
#: they are not an additional step — an entry outside this set is.
STANDARD_DEPENDENCIES = ("pypdf>=6.0", "pypdfium2>=4.0", "Pillow>=10.0", "typesafe-sdk==0.7.2")


def test_tc_smoke_01_clean_install_needs_nothing_beyond_a_venv_and_a_data_dir(
    tmp_data_dir, tmp_path
):
    """`TC-SMOKE-01` — a clean virtualenv install completes with no npm toolchain, no build
    step, no server process.

    Oracle: **declared-property plus exact success**. The declaration half reads the
    repository's own install contract; the demonstration half is the clean-environment
    subprocess — environment carrying only the OS minimum and `HARNESS_DATA_DIR`, source tree
    on `PYTHONPATH`, no build artifact anywhere — importing the assembled system, opening a
    store, writing a row through a transaction, reading it back, and exiting 0. A repository
    that has grown an npm toolchain, a compiled build step, or a required server makes one of
    the assertions below name it.
    """
    # -- the declared half -------------------------------------------------------------------
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]
    assert Counter(dependencies) == Counter(STANDARD_DEPENDENCIES), (
        f"TC-SMOKE-01: pyproject.toml declares runtime dependencies {dependencies}, not "
        f"FR-STORE-20's {list(STANDARD_DEPENDENCIES)}. NFR-STORE-03: no separate installation "
        "step — `pip install .` must carry exactly the declared set (ADR-36), so a changed "
        "set is an install the smoke suite was written to catch."
    )
    assert "optional-dependencies" not in pyproject["project"], (
        "TC-SMOKE-01: an extra is a second install command, and ADR-36 retired them all: "
        f"{pyproject['project']['optional-dependencies']}"
    )

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    # The npm-manifest rule guards the INSTALL story, not the whole tree: since #634 (M-UI),
    # the SPA's source tree `ui/` deliberately commits its manifests — Q-O3 pins the
    # toolchain through the lockfile so the bundle is reproducibly rebuildable — and the
    # committed bundle (`src/aeh/console_assets/spa/`) is pre-built, so the install never
    # runs npm. An npm manifest anywhere ELSE means a second toolchain the install story
    # does not declare.
    npm = [f for f in tracked
           if Path(f).name in NPM_MANIFESTS and not Path(f).parts[:1] == ("ui",)]
    assert npm == [], (
        f"TC-SMOKE-01: npm-shaped manifests in the tracked tree outside ui/: {npm}. The "
        "install story is venv + requirements-dev.txt; a package.json outside the SPA's "
        "source tree (where Q-O3 pins the toolchain through the lockfile) means a second "
        "toolchain."
    )
    servers = [f for f in tracked if Path(f).name in SERVER_ARTIFACTS]
    assert servers == [], (
        f"TC-SMOKE-01: server-shaped install artifacts in the tracked tree: {servers}. "
        "NFR-STORE-03: no server process. SQLite is the store; nothing is started."
    )

    # -- the demonstrated half ----------------------------------------------------------------
    env = {
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "TEMP": os.environ.get("TEMP", str(tmp_path)),
        "TMP": os.environ.get("TMP", str(tmp_path)),
        "HARNESS_DATA_DIR": str(tmp_data_dir / "clean"),
        "PYTHONPATH": str(REPO_SRC),
    }
    child = (
        "from aeh.store import Statement, open_store\n"
        "# The chains concatenate at import time, so the full-world convention holds here\n"
        "# too: every contributing module before the first open (#234).\n"
        "import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, "
        "aeh.judge, aeh.orch, aeh.pkg, aeh.review, aeh.synth  # noqa: E401\n"
        "store = open_store()  # no argument: HARNESS_DATA_DIR or refusal\n"
        "handle = store.durable()\n"
        "with handle.transaction() as tx:\n"
        "    tx.execute(Statement('INSERT INTO run_metrics (run_id, metric, value) "
        "VALUES (:r, :m, :v)'), r='smoke', m='boot', v=1.0)\n"
        "rows = handle.query(Statement('SELECT value FROM run_metrics "
        "WHERE metric = \\'boot\\''))\n"
        "assert len(rows) == 1 and rows[0][0] == 1.0\n"
        "store.close()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", child], env=env, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, (
        "TC-SMOKE-01: the assembled system did not come up in a clean environment — "
        "an additional install step, build artifact, server process or configuration "
        "beyond the data directory has entered the runtime.\n"
        f"stderr: {result.stderr[-800:]}\n"
        "NFR-STORE-03 is the clause this smoke case exists to defend."
    )
    assert (tmp_data_dir / "clean" / "durable.sqlite").exists(), (
        "TC-SMOKE-01: the child exited 0 but left no durable.sqlite — a success that "
        "wrote nothing is the silent-failure shape the smoke suite exists to catch."
    )