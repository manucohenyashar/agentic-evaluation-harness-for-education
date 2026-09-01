"""The seam between a written-ahead test and an implementation that does not exist yet.

Test-plan §8.2: this repository has no implementation at all, so every test story is written
**ahead** of the code it tests and `/write-tests` should expect a red suite. But there is a
right way and a wrong way to be red. A module-level `from aeh.prov import ...` produces a
*collection* error: pytest reports "1 error", the test never runs, and nothing about the
requirement was asserted. That failure looks identical whether the implementation is missing,
the import path is wrong, or the test file has a syntax error — and it is the kind of thing a
later reader "fixes" by deleting the import.

So the import happens **inside the test body**, through `require()`, and a missing
implementation raises `NotImplementedYet` — an `AssertionError` naming the module and the
issue that will provide it. The test runs, fails for a stated reason, and turns green the
moment the implementation lands, with no edit to the test.

One constant below is the only place the implementation package is named.
"""

from __future__ import annotations

import importlib
import importlib.util
from typing import Any

# --- the implementation under test -------------------------------------------------------
# The design and the test plan fix the *test* layout (`tests/unit/...`) and the tooling
# package (`harness.*`, §4.7) but never name the source package. Chosen here, isolated to
# these three constants: issue #18 (S-PROV-01) owns the implementation and may rename it with
# a one-line change.
IMPLEMENTATION_PACKAGE = "aeh"
PROVIDER_MODULE = f"{IMPLEMENTATION_PACKAGE}.prov"
CONF_MODULE = f"{IMPLEMENTATION_PACKAGE}.conf"
STORE_MODULE = f"{IMPLEMENTATION_PACKAGE}.store"

# §4.2: "RecordedFixtureProvider (FR-PROV-10) is a *shipped implementation*, not a test fake."
# The fast tier binds this class by name; the harness self-test asserts the binding.
FIXTURE_PROVIDER_CLASS = "RecordedFixtureProvider"


# --- what the written-ahead tests are waiting on -----------------------------------------
# Every test carrying `@pytest.mark.writtenahead` is excluded from TEST_CMD (see
# scripts/test.sh), which is what lets the Stop-hook gate be green while those tests are
# correctly red. The risk in that scheme is silence: when the blocking issue closes, nothing
# says so, and a P0 case can sit outside the gate indefinitely.
#
# This registry closes it. `tests/unit/harness/test_harness.py` asserts every blocker is
# still unresolved, so the moment one lands the gate fails and names the tests to unmark.
# Three kinds of target, because a blocker is not always a whole module:
#   "module"  importable module path            -- the module does not exist yet
#   "path"    repo-relative file or directory   -- a data artifact does not exist yet
#   "symbol"  "module:dotted.attr"              -- the module exists; this name in it does not
#
# `symbol` is what a module split across several stories needs. `aeh.conf` landed with #4, so
# `find_spec` has said "resolved" since then — but `RunConfig.profile_summary` arrives with #5
# and `rehydrate_run_config` with #6, and until they do their cases are correctly red.
WRITTEN_AHEAD_BLOCKERS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    # issue: (kind, target, tests to unmark)
    "#18": (
        "module",
        PROVIDER_MODULE,
        ("tests/unit/prov/test_recorded_fixture_provider.py",),
    ),
    "#2": (
        "path",
        "fixtures/F-FROZEN/manifest.json",
        ("tests/artifact/test_heldout_disjoint.py",),
    ),
    # `TC-CONF-17` is the one case in TS-04 whose rung is not achievable: rung 2 means a
    # *finished run's* audit record, which needs `M-STORE` to write it. Keyed on the module
    # rather than a symbol because none of it exists yet.
    "#10": (
        "module",
        STORE_MODULE,
        ("tests/integration/conf/test_audit_record.py",),
    ),
}


def blocker_is_resolved(kind: str, target: str, repo_root: Any) -> bool:
    """Has the thing a written-ahead test waits on landed?

    Lives here rather than in the gate test so the registry and the rule that reads it stay in
    one file — a new `kind` added above without a branch here would otherwise fail silently as
    "not resolved", which is the direction that keeps a P0 case outside the gate forever.
    """
    if kind == "module":
        try:
            # find_spec raises rather than returning None when the *parent* package is absent.
            return importlib.util.find_spec(target) is not None
        except ModuleNotFoundError:
            return False
    if kind == "symbol":
        module_path, _, dotted = target.partition(":")
        try:
            obj: Any = importlib.import_module(module_path)
        except ModuleNotFoundError:
            return False
        for attribute in dotted.split("."):
            obj = getattr(obj, attribute, None)
            if obj is None:
                return False
        return True
    if kind == "path":
        return (repo_root / target).exists()
    raise ValueError(
        f"unknown written-ahead blocker kind {kind!r}. Add a branch here when adding a kind, "
        f"or the gate reads it as unresolved and never fires."
    )


class NotImplementedYet(AssertionError):
    """The thing under test has not been built yet.

    `AssertionError` so pytest reports a failure rather than an error, and so the message
    lands in the failure summary where a reader will actually see which issue is blocking.
    """


def require(module_path: str, *names: str, issue: str | None = None) -> Any:
    """Import `module_path` and return the named symbols, or fail with a stated reason.

    Call this inside a test body, never at module scope::

        Provider, FixtureMissingError = require(
            PROVIDER_MODULE, "RecordedFixtureProvider", "FixtureMissingError", issue="#18"
        )

    Returns a single symbol when one name is given, a tuple otherwise; the module itself when
    no names are given.
    """
    blocked_by = f" (blocked on {issue})" if issue else ""
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        # Only swallow the absence of the target itself. A ModuleNotFoundError raised from
        # *inside* a module that does exist is a real defect and must not be reported as
        # "not implemented yet".
        if exc.name is not None and (
            exc.name == module_path or module_path.startswith(exc.name + ".")
        ):
            raise NotImplementedYet(
                f"{module_path} does not exist yet{blocked_by}. This test is written ahead "
                f"of its implementation (test plan §8.2) and is expected to fail until it "
                f"lands."
            ) from None
        raise

    if not names:
        return module

    missing = [n for n in names if not hasattr(module, n)]
    if missing:
        raise NotImplementedYet(
            f"{module_path} exists but does not define "
            f"{', '.join(repr(n) for n in missing)}{blocked_by}."
        )

    resolved = tuple(getattr(module, n) for n in names)
    return resolved[0] if len(resolved) == 1 else resolved


def require_attr(owner: Any, name: str, issue: str | None = None) -> Any:
    """The same idea for a method arriving later on a class that already exists.

    `require()` cannot express this: `aeh.conf` is importable and `RunConfig` is defined, so a
    module-level check says "resolved" while `profile_summary` is still months away.
    """
    attr = getattr(owner, name, None)
    if attr is None:
        blocked_by = f" (blocked on {issue})" if issue else ""
        raise NotImplementedYet(
            f"{getattr(owner, '__name__', owner)!s} exists but has no {name!r} yet{blocked_by}. "
            f"This test is written ahead of its implementation (test plan §8.2)."
        )
    return attr


def require_path(path: Any, what: str, issue: str | None = None) -> Any:
    """The same idea for a data artifact — a corpus, a manifest, a fixture set."""
    if not path.exists():
        blocked_by = f" (blocked on {issue})" if issue else ""
        raise NotImplementedYet(
            f"{what} not found at {path}{blocked_by}. This test is written ahead of the "
            f"artifact it asserts on (test plan §8.2)."
        )
    return path
