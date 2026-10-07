"""`TC-STORE-26`: what `pyproject.toml` declares about packaging (`FR-STORE-15` amended,
`FR-STORE-20`, ADR-36). First written by TS-84 (issue #378); **flipped** by #613 per the
operator-requirements test plan §5.0.

| Case | Input | Expected |
|---|---|---|
| `TC-STORE-26` (flipped) | `tomllib.load(pyproject.toml)` | `[project].dependencies` contains exactly `pypdf>=6.0`, `pypdfium2>=4.0`, `Pillow>=10.0`, `typesafe-sdk==0.7.2`, each a declared string; `optional-dependencies` is absent; `[build-system].requires` contains `setuptools>=69`; `[project.scripts].aeh == "aeh.pipeline:main"`; package data includes `aeh/console_assets/*` and covers the SPA bundle directory |

**Why it flipped.** ADR-36 supersedes ADR-11's packaging clause: the operator's one install
command, `pip install .`, must leave the system complete (user directive R-1). The PDF readers,
the page-picture decoder and the TypeSafe SDK move from the `live-ingest` / `jev-cloud` extras
into the core dependency list, and the extras are retired. The *import* boundary does not move:
the four stay lazy-imported, which is `TC-PIPE-12`'s and `TC-INGEST-01`'s business, not this file's.

**Which arms were red, and why.** Written ahead of #614 (the packaging story) and of #634 (the
bundle): the dependency-set and no-extras arms waited on #614 — the core list was `[]` and both
extras existed — and the SPA-bundle coverage arm waited on #634, which #614 could not make true.
Both stories have landed, the markers are off and their `WRITTEN_AHEAD_BLOCKERS` entries are out;
the build-system, entry-point and `console_assets/*` arms were unchanged throughout and stayed
green.

**The `>=` clauses are asserted as declared strings**, not parsed as version ranges: the plan
pins `pypdf>=6.0`, and a test that parsed and compared would pass for `pypdf>=6.1` — a different
declaration from the one the plan pins. Equality is on the *list* (as a multiset of strings, not
an order), so an added fifth dependency, a dropped one, an unpinned `Pillow`, or a loosened
`typesafe-sdk>=0.7.2` each fail it.
"""

from __future__ import annotations

import fnmatch
import tomllib
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = REPO_ROOT / "pyproject.toml"
CONSOLE_ASSETS = REPO_ROOT / "src" / "aeh" / "console_assets"

EXPECTED_BUILD_REQUIRE = "setuptools>=69"
EXPECTED_ENTRY_POINT = "aeh.pipeline:main"
#: FR-STORE-20, transcribed — never read back from the file under test.
EXPECTED_DEPENDENCIES = ("pypdf>=6.0", "pypdfium2>=4.0", "Pillow>=10.0", "typesafe-sdk==0.7.2")
EXPECTED_PACKAGE_DATA = "console_assets/*"
#: The SPA's entry document. FR-UI-01 ships the built bundle as package data under
#: `console_assets/`; its exact sub-directory is #634's call, so the arm finds it by its entry
#: file rather than pinning a path the design never fixed.
SPA_ENTRY = "index.html"


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_tc_store_26_the_build_system_requires_setuptools_69() -> None:
    """Unchanged arm (green)."""
    requires = _pyproject()["build-system"]["requires"]
    assert EXPECTED_BUILD_REQUIRE in requires, (
        f"[build-system].requires is {requires}; FR-STORE-15 pins "
        f"{EXPECTED_BUILD_REQUIRE!r} — the backend `pip install .` builds with"
    )


def test_tc_store_26_the_console_script_points_at_m_pipes_main() -> None:
    """Unchanged arm (green). `aeh` on the PATH is `aeh.pipeline:main`; `TC-PIPE-12` invokes it
    as `aeh --help` in a clean venv, which is later and dearer than here."""
    scripts = _pyproject()["project"].get("scripts", {})
    assert scripts.get("aeh") == EXPECTED_ENTRY_POINT, (
        f"[project.scripts].aeh is {scripts.get('aeh')!r}, not {EXPECTED_ENTRY_POINT!r}"
    )


def test_tc_store_26_the_core_declares_exactly_the_four_standard_dependencies() -> None:
    """FR-STORE-20 (flipped from `dependencies == []`): exactly the four declared strings.

    Compared as a multiset of the literal strings: order is not a packaging fact, but a
    duplicate, an extra entry, a missing one, or any respelling of a specifier is.
    """
    dependencies = _pyproject()["project"].get("dependencies")
    assert isinstance(dependencies, list), f"[project].dependencies is {dependencies!r}"
    assert Counter(dependencies) == Counter(EXPECTED_DEPENDENCIES), (
        f"[project].dependencies is {dependencies}; FR-STORE-20 declares exactly "
        f"{list(EXPECTED_DEPENDENCIES)} — an unpinned, re-specified, missing or added "
        "dependency is a different install from the one the operator documents promise"
    )


def test_tc_store_26_no_optional_dependency_table_survives() -> None:
    """FR-STORE-20: the `live-ingest` and `jev-cloud` extras are removed — and so is the table.

    Absence of the whole `optional-dependencies` key, not of the two names: a re-added extra
    under a new name is still a second install command an operator can get wrong.
    """
    project = _pyproject()["project"]
    assert "optional-dependencies" not in project, (
        f"[project.optional-dependencies] is {project.get('optional-dependencies')!r}; "
        "ADR-36 retires every extra, so `pip install .` is the only install command"
    )


def test_tc_store_26_the_console_assets_ship_with_the_package() -> None:
    """Unchanged arm (green). `console_assets/*` is declared as package data, and the file it
    stands for exists: a declaration over an empty directory ships nothing, and a stylesheet
    only in the source tree is missing from every installed copy (`TC-PIPE-12` checks the venv).
    """
    package_data = _pyproject()["tool"]["setuptools"]["package-data"]
    assert EXPECTED_PACKAGE_DATA in package_data.get("aeh", []), (
        f"tool.setuptools.package-data['aeh'] is {package_data.get('aeh')}; it must include "
        f"{EXPECTED_PACKAGE_DATA!r} or the console's stylesheet ships only in the source tree"
    )
    stylesheet = CONSOLE_ASSETS / "console.css"
    assert stylesheet.is_file(), (
        f"{stylesheet} does not exist, so the package-data glob above matches nothing and the "
        "declaration is a promise about an empty directory"
    )


def _covered(relative: str, globs: list[str]) -> bool:
    """Whether setuptools' package-data globs for `aeh` match the package-relative `relative`.

    setuptools matches each glob against the path relative to the package directory; a `*`
    does not cross a `/` and `**` (setuptools >= 62.3, below our `setuptools>=69` floor) does.
    `fnmatch` lets `*` cross `/`, so the segment-wise comparison below is what keeps
    `console_assets/*` from appearing to cover `console_assets/spa/index.html` when it does not.
    setuptools expands the globs with `glob`, which skips dot-files and dot-directories unless the
    pattern segment itself starts with `.`; `fnmatch` does not, so `_segment` re-applies that rule
    (a bundle's `.vite/manifest.json` is NOT shipped by `console_assets/**/*`).
    """
    def _segment(part: str, glob_part: str) -> bool:
        if part.startswith(".") and not glob_part.startswith("."):
            return False
        return fnmatch.fnmatchcase(part, glob_part)

    parts = relative.split("/")
    for glob in globs:
        pattern = glob.split("/")
        if "**" in pattern:
            head = pattern[: pattern.index("**")]
            tail = pattern[pattern.index("**") + 1:]
            spanned = parts[len(head):len(parts) - len(tail)]
            if (len(parts) >= len(head) + len(tail)
                    and all(_segment(p, g) for p, g in zip(parts, head))
                    and not any(p.startswith(".") for p in spanned)
                    and all(_segment(p, g)
                            for p, g in zip(parts[len(parts) - len(tail):], tail))):
                return True
        elif len(pattern) == len(parts) and all(
                _segment(p, g) for p, g in zip(parts, pattern)):
            return True
    return False


def test_tc_store_26_the_package_data_covers_the_spa_bundle_directory() -> None:
    """New arm (operator plan §5.0): `console_assets/*` covers the SPA bundle directory too.

    Two halves, both needed. The bundle must be *there* (an entry `index.html` under
    `console_assets/`, FR-UI-01), and every file of the `console_assets/` tree must be matched by
    a declared package-data glob — a bundle in a sub-directory that `console_assets/*` does not
    reach is a console that renders on a checkout and serves 404s from every installed copy.
    """
    globs = list(_pyproject()["tool"]["setuptools"]["package-data"].get("aeh", []))
    entries = sorted(CONSOLE_ASSETS.rglob(SPA_ENTRY))
    assert entries, (
        f"no SPA bundle under {CONSOLE_ASSETS}: no {SPA_ENTRY} anywhere in the tree "
        "(FR-UI-01 ships the built bundle as package data; #634 commits it)"
    )
    files = [p.relative_to(REPO_ROOT / "src" / "aeh").as_posix()
             for p in CONSOLE_ASSETS.rglob("*") if p.is_file()]
    uncovered = sorted(f for f in files if not _covered(f, globs))
    assert uncovered == [], (
        f"tool.setuptools.package-data['aeh'] is {globs}; these console_assets files match no "
        f"glob and would be missing from an installed package: {uncovered}"
    )
