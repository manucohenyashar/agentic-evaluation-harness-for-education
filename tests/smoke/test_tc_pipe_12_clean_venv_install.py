"""`TC-PIPE-12` (flipped): a clean virtualenv, `pip install .` and nothing else, yields the whole
operator system (`FR-STORE-20`, ADR-36; operator-requirements test plan §5.0; issue #613).

| Case | Input | Expected | Oracle |
|---|---|---|---|
| `TC-PIPE-12` (flipped) | A fresh venv; `pip install <repo>` with no dev requirements, no extras, no further argument | the install exits 0; `aeh --help` exits 0; `import pypdf`, `pypdfium2`, `PIL`, `typesafe_sdk` each SUCCEED; `aeh` imports from the venv, not the checkout; `console.css` and the SPA bundle exist in the installed package; importing the harness loads none of the four (the lazy import stays the seam) | Exact import outcomes + exit codes + file presence |

**What flipped.** The gap-fix plan's version of this case asserted `import pypdf` FAILS in a
core-only venv (ADR-11's empty core). ADR-36 inverts it: the operator's one command must leave PDF
reading, page-picture decoding and the OpenRouter Jev provider importable. What did *not* flip is
the import boundary — none of the four is imported by `import aeh.*`; they load inside the code
paths that need them. The plan joins this case with `TC-INGEST-01`'s sweep for that half ("the fast
tier still executes none of their code paths"); that sweep is unchanged and is not repeated here.
The arm below that imports the assembled harness in the *installed* venv, where all four are now
present, is the clean-machine view of the same boundary: an eager top-level import that a missing
library used to expose would now pass silently everywhere else.

**Rung 4, `slow`, nightly** — as the gap-fix plan placed it (§5, TS-84): a real venv and a real
`pip install` from the package index, so this case needs network and minutes, which is why it is
outside `TEST_CMD` by its `slow` marker and not only by `writtenahead`. It installs a *copy* of the
package sources (`pyproject.toml` and `src/`), not the checkout itself, so setuptools' build
directories never land in the working tree.

**Written ahead.** The install-and-import case is red until **#614** (today `import pypdf` and the
other three fail in the clean venv — the reason this case exists). The SPA-bundle case is red until
**#634** commits the bundle; #614 cannot make it green, so it is its own test and its own blocker.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The four standard dependencies' import names (FR-STORE-20): `Pillow` imports as `PIL`.
STANDARD_IMPORTS = ("pypdf", "pypdfium2", "PIL", "typesafe_sdk")

#: The assembled harness: the eleven migration-chain contributors plus the composer, the provider
#: package and the console. None of them may load any of `STANDARD_IMPORTS` at import time.
HARNESS_MODULES = ("aeh.agg", "aeh.det", "aeh.extract", "aeh.grade", "aeh.ingest", "aeh.integ",
                   "aeh.judge", "aeh.orch", "aeh.pkg", "aeh.review", "aeh.synth", "aeh.prov",
                   "aeh.pipeline", "aeh.console")

INSTALL_TIMEOUT_S = 1800


def _clean_env() -> dict[str, str]:
    """The caller's environment minus everything that would let the venv see the checkout or the
    dev venv: no `PYTHONPATH`, no `PYTHONHOME`, no active `VIRTUAL_ENV`."""
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONSTARTUP"}}
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _source_files(under: str) -> list[str]:
    """Repo-relative paths of every tracked or untracked-but-not-ignored file under `under`."""
    listed = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "--", under],
                            cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    return [line for line in listed.stdout.splitlines() if (REPO_ROOT / line).is_file()]


class _Venv:
    def __init__(self, root: Path, install: subprocess.CompletedProcess) -> None:
        self.root = root
        self.install = install
        scripts = root / ("Scripts" if os.name == "nt" else "bin")
        self.python = scripts / ("python.exe" if os.name == "nt" else "python")
        self.aeh = scripts / ("aeh.exe" if os.name == "nt" else "aeh")
        self.cwd = root.parent  # outside the checkout, so `import aeh` cannot find src/

    def run(self, *argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(list(argv), cwd=self.cwd, env=_clean_env(), capture_output=True,
                              text=True, timeout=300)

    def python_c(self, code: str) -> subprocess.CompletedProcess:
        return self.run(str(self.python), "-I", "-c", code)


@pytest.fixture(scope="module")
def clean_venv(tmp_path_factory) -> _Venv:
    """A fresh venv with `pip install <copy of the package>` and no other argument."""
    base = tmp_path_factory.mktemp("tc_pipe_12")
    source = base / "source"
    for relative in ["pyproject.toml", *_source_files("src")]:
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    root = base / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(root)], check=True, env=_clean_env(),
                   capture_output=True, timeout=300)
    venv = _Venv(root, subprocess.CompletedProcess([], 0))
    venv.install = subprocess.run(
        [str(venv.python), "-m", "pip", "install", "--disable-pip-version-check", str(source)],
        cwd=base, env=_clean_env(), capture_output=True, text=True, timeout=INSTALL_TIMEOUT_S)
    return venv


def _installed_package_dir(venv: _Venv) -> Path:
    located = venv.python_c("import aeh, pathlib; print(pathlib.Path(aeh.__file__).resolve().parent)")
    assert located.returncode == 0, f"`import aeh` failed in the clean venv:\n{located.stderr[-1500:]}"
    package = Path(located.stdout.strip().splitlines()[-1])
    assert venv.root.resolve() in package.parents, (
        f"`aeh` imported from {package}, not from the venv at {venv.root} — the case would be "
        "testing the checkout, not the install")
    return package


@pytest.mark.writtenahead
def test_tc_pipe_12_pip_install_dot_alone_yields_the_command_and_all_four_libraries(clean_venv) -> None:
    """The install exits 0, `aeh --help` exits 0, each of the four standard dependencies imports,
    `console.css` is in the installed package, and the assembled harness imports none of the four."""
    assert clean_venv.install.returncode == 0, (
        f"`pip install .` failed in a clean venv (RISK-113: the operator's first step is the "
        f"failure):\n{clean_venv.install.stdout[-1500:]}\n{clean_venv.install.stderr[-2500:]}")

    help_run = clean_venv.run(str(clean_venv.aeh), "--help")
    assert help_run.returncode == 0, f"`aeh --help` exited {help_run.returncode}:\n{help_run.stderr[-1500:]}"
    assert "usage: aeh" in help_run.stdout, help_run.stdout[-800:]

    outcomes = {name: clean_venv.python_c(f"import {name}").returncode for name in STANDARD_IMPORTS}
    assert outcomes == {name: 0 for name in STANDARD_IMPORTS}, (
        f"import exit codes in the clean venv: {outcomes}; FR-STORE-20 — `pip install .` alone "
        "must provide PDF reading, page-picture decoding and the OpenRouter Jev provider")

    package = _installed_package_dir(clean_venv)
    assert (package / "console_assets" / "console.css").is_file(), (
        f"console.css is not in the installed package at {package / 'console_assets'}")

    probe = clean_venv.python_c(
        "import importlib, json, sys\n"
        f"for m in {HARNESS_MODULES!r}: importlib.import_module(m)\n"
        f"print(json.dumps(sorted(m for m in {STANDARD_IMPORTS!r} if m in sys.modules)))\n")
    assert probe.returncode == 0, f"the assembled harness did not import:\n{probe.stderr[-1500:]}"
    loaded = json.loads(probe.stdout.strip().splitlines()[-1])
    assert loaded == [], (
        f"importing the harness loaded {loaded}: the four stay lazy-imported inside the code paths "
        "that need them (the import boundary did not move with the install boundary)")


@pytest.mark.writtenahead
def test_tc_pipe_12_the_installed_package_carries_the_spa_bundle(clean_venv) -> None:
    """Every file of the source `console_assets/` tree — the stylesheet and the SPA bundle
    (FR-UI-01) — exists at the same path in the installed package, and the bundle's entry document
    is among them."""
    assert clean_venv.install.returncode == 0, clean_venv.install.stderr[-2500:]
    prefix = "src/aeh/"
    sources = [f[len(prefix):] for f in _source_files("src/aeh/console_assets")]
    assert any(Path(f).name == "index.html" for f in sources), (
        "no SPA bundle (no index.html) under src/aeh/console_assets — #634 commits it")
    package = _installed_package_dir(clean_venv)
    missing = sorted(f for f in sources if not (package / f).is_file())
    assert missing == [], f"console_assets files missing from the installed package: {missing}"
