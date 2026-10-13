"""`SEC-14` — the supply-chain boundary. Test plan §6.5, TS-57 (issue #150).

Test plan §6.5: *"Dependency vulnerability scan on every push. No unresolved High or Critical
advisory in a shipped dependency. **Cross-cutting** — this traces to no single requirement."*

**What this file asserts, and what it deliberately does not.**

The stated oracle has two halves and only one of them is expressible in this repository today.

*The half that is here.* `pyproject.toml` declares exactly seven runtime dependencies — `pypdf`,
`pypdfium2`, `Pillow`, `typesafe-sdk`, and, since the console-redesign intake tier (ADR-49, #754),
`mammoth` and `charset-normalizer`, and, since the console's workbook export (ADR-49, #762),
`openpyxl` (`FR-STORE-20`). That is a design decision, not an accident:
ADR-11 once declared the set empty, and ADR-36 (#614) superseded its packaging clause so that the
operator's one `pip install .` leaves the system complete. ADR-36's stated mitigation is this file:
**the shipped set is enumerated, entry by entry, with the reason each one ships**, and every entry is
exact-pinned or floor-bounded. The thing that widens the advisory surface is somebody adding a
dependency, so these cases assert the set as equality against a literal transcribed here, the same
shape as `TC-CONF-C02`'s field set and `TC-CONF-C11`'s six-key set. Adding `requests` to
`pyproject.toml` or to `requirements-dev.txt` fails this file. (The import boundary did not move with
the install boundary: the fast tier still imports none of the seven — `NFR-SYS-06`, `TC-INGEST-01`.)

*The half that is not.* Running an actual advisory scan needs an advisory database, which needs
network. Two independent obstructions, both reported in the PR rather than engineered around:

1. §4.7's tier table has **no egress-permitted non-model tier**. `live` means "makes real model
   calls; nightly only, E2/E3" — reusing it for a dependency scan makes the marker's own
   definition false, and the tier table belongs to `/create-test-plan`.
2. "on every push" is a CI statement, and `.github/workflows/` is `.disabled` deliberately
   (`CLAUDE.md`: the workflows are off on purpose, `/work-backlog` is the dispatcher).

A scanner tested against a vendored advisory snapshot was considered and rejected: it would prove
the scanner works while saying nothing about the dependency set, and a snapshot goes stale into a
lie that reads as truth. A test that skips when offline is not a test.

So `SEC-14` is **partially implemented, and that is stated** rather than hidden behind a green
tick — the honest reporting the `/write-tests` skill asks for when an oracle cannot be expressed.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.contract


#: `pyproject.toml`'s runtime dependency list, transcribed, with the reason each one ships
#: (FR-STORE-20, ADR-36 — the supply-chain inventory the ADR names as its mitigation). Keys are
#: lowercased distribution names, as `_REQUIREMENT` parses them.
#:
#: A literal rather than a read of the same file the assertion is about — reading it and comparing
#: it to itself is the tautology `TC-CONF-C02` avoids by transcribing the design's field list. The
#: value of this constant is that changing `pyproject.toml` requires changing this mapping too, in
#: a diff a reviewer sees.
DECLARED_RUNTIME_DEPENDENCIES: dict[str, str] = {
    "pypdf": "M-INGEST, TS-18 (#42) — the live PypdfSanitizer, the gateway's neutralize-and-bound "
             "stage (FR-INGEST-33/34). Pure Python. Lazy-imported, so the fast tier never loads it",
    "pypdfium2": "M-INGEST, #226 (F10) — the live PdfiumRasterizer's engine: rasterize, text_layer "
                 "and the live crop (FR-INGEST-13). Ships the PDFium binary as a platform wheel. "
                 "Lazy-imported",
    "pillow": "M-INGEST / M-STORE, #226 — PdfBitmap.to_pil() needs it: the persisted page rasters "
              "and image crops decode their PNG bytes through it (FR-STORE-06). Before ADR-36 it "
              "was a manual install step. Lazy-imported",
    "typesafe-sdk": "M-PROV, TS-124 (#500), design 1.8 ADR-28 — the TypeSafe SDK behind "
                    "JevOpenRouterProvider, exact-pinned (NFR-PROV-10). Imported solely inside "
                    "aeh.prov, lazily, at provider construction (CT-PROV-29). Pulls httpx2, "
                    "pydantic, pydantic-core, tenacity and typing-extensions",
    "mammoth": "M-AUTHOR, #754 (ADR-49) — .docx intake's converter to semantic HTML "
               "(FR-AUTHOR-25); its messages list is the warnings stream. Pure Python. "
               "Lazy-imported inside aeh.author.intake, so the fast tier never loads it",
    "charset-normalizer": "M-AUTHOR, #754 (ADR-49) — .txt intake's encoding detection "
                          "(FR-AUTHOR-26). Pure Python. Lazy-imported inside "
                          "aeh.author.intake, so the fast tier never loads it",
    "openpyxl": "M-CONSOLE, #762 (ADR-49) — the results workbook export's writer "
                "(FR-CONSOLE-58): the only maintained pure-Python xlsx writer. Upper-bounded "
                "at <4 because openpyxl's minor releases have rewritten workbook internals "
                "under the same 3.x line. Imported solely inside aeh.grade.workbook, lazily, "
                "inside the export call, so the fast tier never loads it (NFR-SYS-06)",
}

#: The exact specifier strings FR-STORE-20 pins, so a loosened pin is caught here as well as in
#: `TC-STORE-26`: an advisory obligation is only answerable if the shipped version is known.
DECLARED_RUNTIME_SPECIFIERS: frozenset[str] = frozenset(
    {"pypdf>=6.0", "pypdfium2>=4.0", "Pillow>=10.0", "typesafe-sdk==0.7.2",
     "mammoth>=1.6,<2", "charset-normalizer>=3.0,<4", "openpyxl>=3.1,<4"}
)

#: Every distribution `requirements-dev.txt` is allowed to install, with the story that added it.
#: A dev dependency is not shipped, so it carries no `SEC-14` advisory obligation of its own — but
#: it does run in CI against the repository, and an unreviewed addition is exactly the A08 vector
#: this boundary exists for.
REVIEWED_DEV_DEPENDENCIES: dict[str, str] = {
    "pytest": "TS-00 (#1) — the framework itself",
    "pytest-randomly": "TS-00 (#1) — §4.6 runs the unit suite shuffled",
    "hypothesis": "TS-03 (#7) — the first story carrying Property-level cases",
    "playwright": "TS-49 (#130) — test plan §4.5's E6 headless browser for the browser-level "
                  "console facts (TC-CONSOLE-40/41, SEC-12). Test-only: imported solely by "
                  "tests/support/console_browser.py, launching an installed Edge/Chrome by "
                  "channel, so no browser binary is downloaded",
}

REPO_ROOT = Path(__file__).resolve().parents[2]

#: `name>=1.2`, `name==1.2`, `name[extra]>=1.2`, or a bare `name`. Extras and environment markers
#: are stripped, because the assertion is about *which distribution* is installed.
_REQUIREMENT = re.compile(
    r"^\s*([A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*([<>=!~][^;#]*)?\s*(?:;[^#]*)?(?:#.*)?$"
)


def _dev_requirement_lines() -> tuple[dict[str, str], list[str]]:
    """`({distribution: specifier}, [option lines])` from `requirements-dev.txt`.

    Option lines are **returned, not skipped**. The first draft dropped anything starting with
    `-`, which silently ignored `-r other.txt`, `--index-url` and `--extra-index-url` — and an
    index override is a textbook A08 vector: it redirects every install to a host nobody
    reviewed, without changing a single package name.
    """
    text = (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    found: dict[str, str] = {}
    options: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-"):
            options.append(line)
            continue
        match = _REQUIREMENT.match(line)
        assert match, f"unparseable requirement line: {line!r}"
        found[match.group(1).lower()] = match.group(2) or ""
    return found, options


def _declared_dev_requirements() -> dict[str, str]:
    """`{distribution: specifier}` — the specifier alone, never the raw line.

    The version-floor check used to `re.search(r"[<>=~!]", line)` over the raw text, so
    `pytest  # >= pin this someday` and `pytest; python_version >= "3.11"` both counted as
    bounded while the distribution was unpinned. `_REQUIREMENT` already isolates the specifier;
    this is where that isolation is applied.
    """
    return _dev_requirement_lines()[0]


def _declared_runtime_entries() -> list[str]:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return list(pyproject["project"].get("dependencies", []))


def test_sec_14_the_shipped_dependency_set_is_the_enumerated_inventory():
    """`SEC-14` — every shipped dependency is on the inventory, with its reason, and nothing else.

    Set equality against the transcribed literal, both directions: the two differ the day someone
    declares a dependency *and* the day someone drops one while its reason stays here, and only a
    reviewed diff to this mapping should make them agree again.

    This is the assertion the whole case rests on. ADR-36 traded ADR-11's empty runtime set for
    the operator's one-command install, and named this enumeration as the mitigation: the advisory
    surface of a school node is exactly these seven distributions and their transitive sets.
    """
    entries = _declared_runtime_entries()
    declared = {_REQUIREMENT.match(entry).group(1).lower() for entry in entries}
    inventory = set(DECLARED_RUNTIME_DEPENDENCIES)

    assert declared == inventory, (
        "SEC-14: the shipped dependency set changed.\n"
        f"  newly declared: {sorted(declared - inventory)}\n"
        f"  removed:        {sorted(inventory - declared)}\n"
        "Every addition ships to a school node and carries an advisory obligation this "
        "repository cannot currently scan for (see this file's docstring). FR-STORE-20 / ADR-36 "
        "enumerate the runtime set; if that is changing, it is a design decision recorded in "
        "DECLARED_RUNTIME_DEPENDENCIES with its reason, not a dependency bump."
    )
    unexplained = sorted(name for name, reason in DECLARED_RUNTIME_DEPENDENCIES.items()
                         if not reason.strip())
    assert not unexplained, f"SEC-14: inventory entries with no reason: {unexplained}"


def test_sec_14_every_shipped_dependency_carries_its_declared_pin():
    """The specifiers, not only the names: `Pillow` unbounded or `typesafe-sdk>=0.7.2` is a
    different install from the one whose advisories anyone could answer for (NFR-PROV-10)."""
    entries = _declared_runtime_entries()

    assert sorted(entries) == sorted(DECLARED_RUNTIME_SPECIFIERS), (
        f"SEC-14: pyproject.toml declares {entries}; FR-STORE-20 pins "
        f"{sorted(DECLARED_RUNTIME_SPECIFIERS)}, each exact-pinned or floor-bounded"
    )


def test_sec_14_every_dev_dependency_has_been_reviewed():
    """Each entry in `requirements-dev.txt` is on the reviewed list, and nothing else is.

    Both directions. A one-way check ("every reviewed name is present") passes while an
    unreviewed package sits alongside them, and that package is the A08 vector: dev tooling runs
    with full filesystem access against the repository on every push.

    The reviewed list carries *why* each entry is there, because the useful question when this
    fails is not "is this package safe" but "who decided we needed it".
    """
    declared = _declared_dev_requirements()
    reviewed = {name.lower() for name in REVIEWED_DEV_DEPENDENCIES}

    unreviewed = sorted(set(declared) - reviewed)
    assert not unreviewed, (
        "SEC-14: requirements-dev.txt declares packages that are not on the reviewed list: "
        f"{unreviewed}. Add them to REVIEWED_DEV_DEPENDENCIES with the story that needed them, "
        "so the addition is a diff somebody approved rather than a line that appeared."
    )

    missing = sorted(reviewed - set(declared))
    assert not missing, (
        f"SEC-14: these are on the reviewed list but no longer declared: {missing}. Drop them "
        "from REVIEWED_DEV_DEPENDENCIES — a reviewed list that outlives its entries stops being "
        "read."
    )


def test_sec_14_every_dev_dependency_declares_a_version_floor():
    """A bare, unbounded requirement resolves to whatever the index served that day.

    `A06 vulnerable components` is not only "a known-bad version is pinned"; it is also "nobody
    can say which version ran". A floor does not stop a bad release, but it makes the installed
    set reproducible enough to answer the question after the fact — which is the minimum this
    repository can offer while the advisory scan itself is out of reach.
    """
    declared = _declared_dev_requirements()
    unbounded = sorted(name for name, specifier in declared.items() if not specifier.strip())

    assert not unbounded, (
        "SEC-14: these dev requirements have no version constraint, so the installed version "
        f"is whatever the index served: {unbounded}"
    )


def test_sec_14_no_option_line_redirects_the_install():
    """`requirements-dev.txt` carries requirements, not install options.

    `--index-url` and `--extra-index-url` redirect every install to a host nobody reviewed, and
    `-r other.txt` moves the dependency set somewhere this file does not look — both A08, both
    invisible to a check that reads package names. Review found the first draft skipping every
    `-`-prefixed line outright, which made the "and nothing else" claim in the case above false.

    Asserted as absence rather than parsed: this repository has no reason to carry one, and if
    that changes it should be a decision recorded here rather than a line that appeared.
    """
    options = _dev_requirement_lines()[1]

    assert not options, (
        f"SEC-14: requirements-dev.txt carries install options: {options}. An index override "
        "or an -r include changes what gets installed without changing a package name."
    )


def test_sec_14_no_lockfile_claims_a_dependency_set_that_does_not_exist():
    """A stale lockfile is a supply-chain claim nobody is maintaining.

    This repository has no lockfile: its seven runtime dependencies are pinned in `pyproject.toml`
    and enumerated above, so the declaration itself is the maintained claim. The
    case exists so that adding one is a decision: a `poetry.lock` or `requirements.txt` that
    nobody regenerates describes an install that never happens, and it is the artifact a reader
    trusts when asking "what shipped".
    """
    lockfiles = [
        name for name in ("poetry.lock", "Pipfile.lock", "pdm.lock", "uv.lock", "requirements.txt")
        if (REPO_ROOT / name).exists()
    ]

    assert not lockfiles, (
        f"SEC-14: {lockfiles} appeared. A lockfile is a claim about the shipped set — if it is "
        "deliberate, this case is the place to record who maintains it and how it is "
        "regenerated."
    )


# --- the SPA's build-time dependency inventory (ADR-49, #767) ---------------------------------------

#: `ui/package.json`'s `dependencies` — the libraries the SPA build **bundles into the committed
#: asset** — transcribed with the reason each one is there (the same shape as
#: `DECLARED_RUNTIME_DEPENDENCIES`, for the other half of ADR-49's policy).
#:
#: These never ship as runtime dependencies of the wheel and are never fetched at runtime
#: (`CT-CONSOLE-06` — the committed bundle is the product; `TC-UI-01 (b)`'s origin sweep is the
#: never-runtime-fetched half, and the E6 rebuild gate is the bundled-in half). What an
#: unreviewed addition here widens is the build machine's surface and the committed asset's
#: bytes, so the admission is the same literal-transcription move: the set changes only in a
#: diff a reviewer sees.
#:
#: **The one design-named dependency that is not here, stated:** ADR-49 names
#: `@base-ui-components/react` 1.x beside `lucide-react` as the delta's two build-time
#: libraries, and issue #767's acceptance criteria carry both. The shipped shell does not
#: declare or import it — the switchers are native `<select>` controls and the dialog, help
#: panel and state badges are hand-rolled accessible components (recorded on #781's PR:
#: "only lucide-react was added; the switchers are native controls, so Base UI is not needed
#: by this story"). Declaring an unused dependency to satisfy the checklist would widen the
#: very surface this inventory bounds, so the inventory enumerates what ships; if a component
#: ever adopts a Base UI primitive, it enters this mapping in the same change, per the rule
#: this file exists to enforce.
DECLARED_SPA_DEPENDENCIES: dict[str, str] = {
    "react": "#634 — the SPA's runtime: the hub, the lifecycle screens and the wizard shell "
             "render through it. Bundled into the committed asset by the pinned Vite build",
    "react-dom": "#634 — the SPA's renderer, mounted once from `ui/src/main.tsx`. Bundled "
                 "beside react by the same build",
    "lucide-react": "#763 (ADR-49) — the icon set behind every state badge and screen glyph "
                    "(FR-UI-04's icon + label + colour pairings and CT-UI-10's never-colour-"
                    "alone rule are what it is for). Tree-shaken by the build: only the "
                    "imported glyphs' paths reach the committed asset, which is why the "
                    "bundle's bytes, not the package, are the shipped surface",
}

#: `ui/package.json`'s `devDependencies` — the pinned build toolchain (`TC-UI-C06`'s Q-O3
#: half: the lockfile is the pin). None of it reaches the bundle; it is inventoried because
#: it runs on the build machine against the repository, the same A08 reasoning as
#: `REVIEWED_DEV_DEPENDENCIES`, and because an unbounded toolchain pin is how a rebuild stops
#: being reproducible (the byte-identity gate's whole premise).
DECLARED_SPA_DEV_DEPENDENCIES: dict[str, str] = {
    "@types/react": "#634 — react's type declarations, typecheck-only",
    "@types/react-dom": "#634 — react-dom's type declarations, typecheck-only",
    "@vitejs/plugin-react": "#634 — the Vite plugin that compiles the JSX/TSX source",
    "typescript": "#634 — the compiler `npm run typecheck` runs over the SPA source",
    "vite": "#634 — the bundler that produces the committed asset (`npm run build`)",
}


def _spa_package_json() -> dict[str, Any]:
    return json.loads((REPO_ROOT / "ui" / "package.json").read_text(encoding="utf-8"))


def _spa_lockfile() -> dict[str, Any]:
    return json.loads((REPO_ROOT / "ui" / "package-lock.json").read_text(encoding="utf-8"))


def _spa_lockfile_roots() -> dict[str, Any]:
    return _spa_lockfile().get("packages", {}).get("", {})


def _is_upper_bounded(specifier: str) -> bool:
    """True when the specifier names a bounded install: an exact pin (`1.2.3`, bare or
    `v`-prefixed, or written `==1.2.3`), an explicit upper bound (`<2`), or a caret/tilde
    range — `^0.577.0` means `>=0.577.0 <0.578.0`, which is an upper bound even though no
    `<` appears in the string (npm's semver semantics, and the reason the check parses
    intent rather than grepping for a character). A leading digit covers the bare exact
    pin and a major-pinned range (`1.x`); `>=3.1` with no `<` still reads as unbounded."""
    text = specifier.strip()
    if not text:
        return False
    if text.startswith(("^", "~", "v")) or "==" in text:
        return True
    if text[0].isdigit():
        return True
    return "<" in text


def test_sec_14_the_spa_dependency_set_is_the_enumerated_inventory():
    """`SEC-14`, the build-time half (ADR-49, #767) — every library `ui/package.json` declares
    under `dependencies` is on the inventory with its reason, and nothing else is, both
    directions. The bundle is what ships to the school's browser, so a library reaching it is
    a shipped dependency in the sense that matters, even though the wheel never installs it."""
    declared = {name.lower(): spec for name, spec in _spa_package_json()["dependencies"].items()}
    inventory = {name.lower() for name in DECLARED_SPA_DEPENDENCIES}

    assert set(declared) == inventory, (
        "SEC-14: the SPA's declared dependency set changed.\n"
        f"  newly declared: {sorted(set(declared) - inventory)}\n"
        f"  removed:        {sorted(inventory - set(declared))}\n"
        "Everything under `dependencies` is bundled into the committed asset (ADR-49): an "
        "addition is a design decision recorded in DECLARED_SPA_DEPENDENCIES with its reason, "
        "admitted in the same change that adds it — never a dependency bump."
    )
    unexplained = sorted(name for name, reason in DECLARED_SPA_DEPENDENCIES.items()
                         if not reason.strip())
    assert not unexplained, f"SEC-14: SPA inventory entries with no reason: {unexplained}"


def test_sec_14_every_spa_dependency_declares_an_upper_bound():
    """`SEC-14`, the build-time half — an unbounded SPA dependency resolves to whatever the
    index served the day the bundle was built, which is exactly the non-reproducibility the
    byte-identity rebuild gate (TC-UI-01 (c)) cannot then vouch for. The dev toolchain is
    held to the same bound: the lockfile pins today's build, but the declared range is what
    the next `npm update` resolves under."""
    package = _spa_package_json()
    unbounded = sorted(
        f"{name} {specifier or '(no specifier)'}"
        for section in ("dependencies", "devDependencies")
        for name, specifier in package.get(section, {}).items()
        if not _is_upper_bounded(specifier)
    )
    assert not unbounded, (
        f"SEC-14: these SPA dependencies are unbounded: {unbounded}. ADR-49 pins every new "
        "dependency with an upper bound; a caret or tilde range is a bound, a bare name is not"
    )


def test_sec_14_the_spa_lockfile_declares_the_same_set_as_the_manifest():
    """The lockfile is the toolchain pin the rebuild gate installs with (`npm ci`); if its
    root entries drift from `package.json`, the gate audits one set while `npm ci` installs
    another. The lockfile lock-version record is checked too: a lockfile written by a
    different npm generation is a toolchain change, which is its own reviewed diff."""
    package = _spa_package_json()
    roots = _spa_lockfile_roots()
    problems = []
    for section in ("dependencies", "devDependencies"):
        manifest = {name.lower(): spec for name, spec in package.get(section, {}).items()}
        locked = {name.lower(): spec for name, spec in (roots.get(section) or {}).items()}
        if manifest != locked:
            problems.append(f"{section}: manifest {manifest} != lockfile {locked}")
    lock_version = _spa_lockfile().get("lockfileVersion")
    if lock_version != 3:
        problems.append(f"lockfileVersion is {lock_version!r}, not the declared 3")
    assert not problems, (
        "SEC-14: the SPA lockfile's claim and the manifest's disagree — `npm ci` would install "
        f"what the rebuild gate does not audit:\n  " + "\n  ".join(problems))


def test_sec_14_control_the_spa_bound_check_rejects_an_unbounded_pin():
    """The negative control for `_is_upper_bounded`: the four specifier shapes that must pass
    do, and the bare name — the actual A06 vector — does not. A parser that passed everything
    would make the case above a tautology, which is the failure TS-57's rule names."""
    assert _is_upper_bounded("^0.577.0")
    assert _is_upper_bounded("~5.9.0")
    assert _is_upper_bounded(">=3.1,<4")
    assert _is_upper_bounded("==0.7.2")
    assert _is_upper_bounded("1.2.3")
    assert _is_upper_bounded("v1.2.3")
    assert not _is_upper_bounded("lucide-react")
    assert not _is_upper_bounded("")
    assert not _is_upper_bounded(">=3.1")

