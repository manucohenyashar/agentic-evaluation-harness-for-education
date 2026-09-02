"""`SEC-14` — the supply-chain boundary. Test plan §6.5, TS-57 (issue #150).

Test plan §6.5: *"Dependency vulnerability scan on every push. No unresolved High or Critical
advisory in a shipped dependency. **Cross-cutting** — this traces to no single requirement."*

**What this file asserts, and what it deliberately does not.**

The stated oracle has two halves and only one of them is expressible in this repository today.

*The half that is here.* `pyproject.toml` declares `dependencies = []` — a design decision, not an
accident: ADR-11 fixes Python 3.11+ with stdlib `sqlite3`, and `NFR-SYS-06` (test plan §4.5 E1)
requires the fast tier to run with nothing installed. **The shipped dependency set is empty**, so
"no High or Critical advisory in a shipped dependency" is trivially true — and the thing that makes
it stop being true is somebody adding a dependency. That is what these cases assert, as set
equality against a literal transcribed here, the same shape as `TC-CONF-C02`'s field set and
`TC-CONF-C11`'s six-key set. Adding `requests` to `requirements-dev.txt` fails this file.

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

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract


#: `pyproject.toml`'s runtime dependency list, transcribed. Empty, per ADR-11 and `NFR-SYS-06`.
#:
#: A literal rather than a read of the same file the assertion is about — reading it and comparing
#: it to itself is the tautology `TC-CONF-C02` avoids by transcribing the design's field list. The
#: value of this constant is that changing `pyproject.toml` requires changing this line too, in a
#: diff a reviewer sees.
DECLARED_RUNTIME_DEPENDENCIES: frozenset[str] = frozenset()

#: Every distribution `requirements-dev.txt` is allowed to install, with the story that added it.
#: A dev dependency is not shipped, so it carries no `SEC-14` advisory obligation of its own — but
#: it does run in CI against the repository, and an unreviewed addition is exactly the A08 vector
#: this boundary exists for.
REVIEWED_DEV_DEPENDENCIES: dict[str, str] = {
    "pytest": "TS-00 (#1) — the framework itself",
    "pytest-randomly": "TS-00 (#1) — §4.6 runs the unit suite shuffled",
    "hypothesis": "TS-03 (#7) — the first story carrying Property-level cases",
}

REPO_ROOT = Path(__file__).resolve().parents[2]

#: `name>=1.2`, `name==1.2`, `name[extra]>=1.2`, or a bare `name`. Extras and environment markers
#: are stripped, because the assertion is about *which distribution* is installed.
_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*(?:[<>=!~;].*)?$")


def _declared_dev_requirements() -> dict[str, str]:
    """Every non-comment line of `requirements-dev.txt`, as `distribution -> the raw line`."""
    text = (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        match = _REQUIREMENT.match(line)
        assert match, f"unparseable requirement line: {line!r}"
        found[match.group(1).lower()] = line
    return found


def test_sec_14_the_shipped_dependency_set_is_empty():
    """`SEC-14` — no shipped dependency, so no advisory can apply to one.

    Set equality against the transcribed literal, not `assert not deps`: the two differ the day
    someone declares a dependency *and* the day someone rewrites this file's expectation, and only
    the first should be silent.

    This is the assertion the whole case rests on. Every other supply-chain claim in this
    repository — the air-gapped tier (§4.5 E1), `NFR-SYS-06`'s "nothing required to run", the
    absence of a lockfile — is downstream of the runtime dependency set being empty, and none of
    them is checked anywhere else.
    """
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = {
        _REQUIREMENT.match(entry).group(1).lower()
        for entry in pyproject["project"].get("dependencies", [])
    }

    assert declared == DECLARED_RUNTIME_DEPENDENCIES, (
        "SEC-14: the shipped dependency set changed.\n"
        f"  newly declared: {sorted(declared - DECLARED_RUNTIME_DEPENDENCIES)}\n"
        f"  removed:        {sorted(DECLARED_RUNTIME_DEPENDENCIES - declared)}\n"
        "Every addition ships to a school node and carries an advisory obligation this "
        "repository cannot currently scan for (see this file's docstring). ADR-11 and "
        "NFR-SYS-06 say the runtime set is empty; if that is changing, it is a design "
        "decision, not a dependency bump."
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
    unbounded = [
        line for line in _declared_dev_requirements().values()
        if not re.search(r"[<>=~!]", line)
    ]

    assert not unbounded, (
        "SEC-14: these dev requirements have no version constraint, so the installed version "
        f"is whatever the index served: {unbounded}"
    )


def test_sec_14_no_lockfile_claims_a_dependency_set_that_does_not_exist():
    """A stale lockfile is a supply-chain claim nobody is maintaining.

    This repository has no lockfile and, with an empty runtime dependency set, needs none. The
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
