"""`TS-84` (issue #378) — `TC-STORE-26`: what `pyproject.toml` declares about packaging
(`FR-STORE-15`, gap-fix test plan §5 / §6).

| Case | Input | Expected |
|---|---|---|
| `TC-STORE-26` | `tomllib.load(pyproject.toml)` | `[build-system].requires` contains `setuptools>=69`; `[project.scripts].aeh == "aeh.pipeline:main"`; `[project].dependencies == []`; `optional-dependencies.live-ingest` contains `pypdf>=6.0` and `pypdfium2>=4.0`; package data includes `aeh/console_assets/*` |

**Rung 0, and green today.** This case reads one committed file and asserts what it declares.
It needs no store, no run and no `aeh.pipeline` — so unlike the rest of TS-84 it carries **no**
`writtenahead` marker and no `WRITTEN_AHEAD_BLOCKERS` entry: every clause the plan names is
already true of `pyproject.toml`, so the case joins the fast tier immediately and guards the
declaration from here on. A written-ahead marker on a case that passes would put it outside
`TEST_CMD` for no reason and trip the registry's own resolved-blocker gate.

**What it is actually guarding.** Each clause is a packaging promise something else depends on,
and each fails silently if it drifts:

* `dependencies == []` is `NFR-PIPE-03`/`ADR-11`: the runtime is stdlib-only, so
  `pip install .` needs no wheel-building toolchain and no network beyond the index. A stray
  runtime dependency here is what `TC-PIPE-12`'s clean-venv case would later discover the
  expensive way — and `TC-SMOKE-01` already asserts the same emptiness from the other side.
* `scripts.aeh` is the console-script entry point `TC-PIPE-12` invokes as `aeh --help`. It
  names `aeh.pipeline:main`, the module `M-PIPE` has yet to build (#365/#358) — the declaration
  can be right before the module exists, which is why this case is green while TS-84's others
  are not.
* `live-ingest` holds the two PDF libraries *out* of the core. `TC-PIPE-12` asserts
  `import pypdf` FAILS in a core-only venv; this is the declaration that makes that true.
* `package-data` carrying `console_assets/*` is what puts `console.css` in the installed
  package rather than only in the source tree.

**The `>=` clauses are asserted as declared strings**, not parsed as version ranges: the plan
says "contains `setuptools>=69`", and a test that parsed and compared would pass for
`setuptools>=70` — a different declaration from the one the plan pins.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = REPO_ROOT / "pyproject.toml"

EXPECTED_BUILD_REQUIRE = "setuptools>=69"
EXPECTED_ENTRY_POINT = "aeh.pipeline:main"
EXPECTED_LIVE_INGEST = ("pypdf>=6.0", "pypdfium2>=4.0")
EXPECTED_PACKAGE_DATA = "console_assets/*"


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_tc_store_26_the_build_system_requires_setuptools_69() -> None:
    requires = _pyproject()["build-system"]["requires"]
    assert EXPECTED_BUILD_REQUIRE in requires, (
        f"[build-system].requires is {requires}; FR-STORE-15 pins "
        f"{EXPECTED_BUILD_REQUIRE!r} — the backend `pip install .` builds with"
    )


def test_tc_store_26_the_console_script_points_at_m_pipes_main() -> None:
    """`aeh` on the PATH is `aeh.pipeline:main`. `TC-PIPE-12` invokes it as `aeh --help`, so a
    drifted target is discovered in a clean venv rather than here — which is later and dearer."""
    scripts = _pyproject()["project"].get("scripts", {})
    assert scripts.get("aeh") == EXPECTED_ENTRY_POINT, (
        f"[project.scripts].aeh is {scripts.get('aeh')!r}, not {EXPECTED_ENTRY_POINT!r}"
    )


def test_tc_store_26_the_core_declares_no_runtime_dependencies() -> None:
    """`NFR-PIPE-03` / `ADR-11`: the runtime is stdlib-only.

    Asserted as exact emptiness rather than "no pdf libraries": the claim is that the core needs
    *nothing*, and a test naming specific forbidden packages passes for the next one added.
    """
    dependencies = _pyproject()["project"]["dependencies"]
    assert dependencies == [], (
        f"[project].dependencies is {dependencies}; the runtime is stdlib-only (ADR-11), so "
        "anything here is an install step a clean venv would have to satisfy"
    )


def test_tc_store_26_the_pdf_libraries_are_optional_not_core() -> None:
    """Both live-ingest libraries sit in an extra. `TC-PIPE-12` asserts `import pypdf` FAILS in a
    core-only venv; this declaration is what makes that true."""
    optional = _pyproject()["project"].get("optional-dependencies", {})
    live_ingest = optional.get("live-ingest", [])
    missing = [name for name in EXPECTED_LIVE_INGEST if name not in live_ingest]
    assert missing == [], (
        f"optional-dependencies.live-ingest is {live_ingest}; it must contain {missing} "
        "(FR-STORE-15). A PDF library that left this extra would land in the core install"
    )


def test_tc_store_26_the_console_assets_ship_with_the_package() -> None:
    """`console_assets/*` is declared as package data, and the file it stands for exists.

    Both halves: a declaration naming a directory that is empty ships nothing, and a stylesheet
    that exists only in the source tree is missing from every installed copy — which is what
    `TC-PIPE-12` checks in the venv.
    """
    package_data = _pyproject()["tool"]["setuptools"]["package-data"]
    assert EXPECTED_PACKAGE_DATA in package_data.get("aeh", []), (
        f"tool.setuptools.package-data['aeh'] is {package_data.get('aeh')}; it must include "
        f"{EXPECTED_PACKAGE_DATA!r} or the console's stylesheet ships only in the source tree"
    )
    stylesheet = REPO_ROOT / "src" / "aeh" / "console_assets" / "console.css"
    assert stylesheet.is_file(), (
        f"{stylesheet} does not exist, so the package-data glob above matches nothing and the "
        "declaration is a promise about an empty directory"
    )
