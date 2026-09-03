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
ORCH_MODULE = f"{IMPLEMENTATION_PACKAGE}.orch"
CONSOLE_MODULE = f"{IMPLEMENTATION_PACKAGE}.console"
JUDGE_MODULE = f"{IMPLEMENTATION_PACKAGE}.judge"
PKG_MODULE = f"{IMPLEMENTATION_PACKAGE}.pkg"
CALIB_MODULE = f"{IMPLEMENTATION_PACKAGE}.calib"
GRADE_MODULE = f"{IMPLEMENTATION_PACKAGE}.grade"

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
    #
    # `SEC-15`'s stated probe is behavioural — call into a real `Store` and assert the search
    # method is not there — so it needs `M-STORE`. Keyed on **#10** although `FR-STORE-08` is
    # #13's: the discriminating question is *which single blocker, resolved, makes this test
    # runnable and non-vacuous*, and that is #10, which creates `aeh.store` and the
    # `Store`/`TierHandle` protocols. An absence assertion over a class is real the moment the
    # class exists; keying on #13 (which depends on #10) would hold it outside the gate for two
    # further stories. `symbol` rather than `module` for the same precision — `aeh.store` could
    # exist as an empty module.
    "#10": (
        "symbol",
        f"{STORE_MODULE}:Store",
        ("tests/artifact/test_store_query_surface.py"
         "::test_sec_15_no_tier_exposes_a_free_text_or_similarity_query",),
    ),
    # --- TS-56 (#149), the two cross-module fuzz cases -------------------------------------
    #
    # Each of the four is keyed on the story that makes *it* runnable, rather than all four on the
    # last one: `FUZZ-06`'s halves target M-PKG and M-ORCH, `FUZZ-07`'s target the blob store and
    # the write queue, and the four land at four different moments.
    #
    # **Keyed on symbols no Interfaces block declares.** `symbol` checks that a name exists, and
    # design §3.3 declares `Store`, `TierHandle` and `BlobStore` in one block that #10 creates
    # (§3.6 does the same for `PackageCatalog` at #26) -- so a key on any of those classes, *or on
    # any of their members*, resolves against a Protocol-only module with no implementation behind
    # it. An earlier draft keyed on `BlobStore.put` and `TierHandle.transaction` believing that
    # narrowed the window; review measured all four candidates firing at once and the narrowing was
    # zero.
    #
    # `in_memory_catalog`, `open_store` and `compute_work_id` are the constructors these tests
    # actually call and appear in no Interfaces block, so none can exist before an implementation
    # does. That closes the window without needing a fourth registry kind.
    "#28": (
        "symbol",
        f"{PKG_MODULE}:in_memory_catalog",
        ("tests/property/test_fuzz_06_graphs_and_work_ids.py"
         "::test_fuzz_06_a_cyclic_dependency_write_is_always_rejected",
         "tests/property/test_fuzz_06_graphs_and_work_ids.py"
         "::test_fuzz_06_topological_order_always_satisfies_every_edge"),
    ),
    "#12": (
        "symbol",
        f"{STORE_MODULE}:open_store",
        ("tests/property/test_fuzz_07_blobs_and_write_queue.py"
         "::test_fuzz_07_a_blob_round_trips_and_its_path_stays_inside_the_data_directory",),
    ),
    "#11": (
        "symbol",
        f"{STORE_MODULE}:open_store",
        ("tests/property/test_fuzz_07_blobs_and_write_queue.py"
         "::test_fuzz_07_a_result_and_its_status_are_both_present_or_both_absent",),
    ),
    # --- TS-74 (#142), the sixteen CT-CALIB clause cases ------------------------------------
    #
    # **This is the instance where the registry's limits actually cost something, so it is stated
    # plainly.** `M-CALIB` is Phase 3/4 and three stories away: #137 (triage) -> #138 (elicitation,
    # lock, history) -> #139 (the two gates). The `Calibration` protocol declares six members, and
    # #137 will almost certainly stub all six at once -- so keying #138's or #139's cases on a
    # protocol member fires at #137, and keying them on an *invented* story-specific name that
    # never appears leaves a P0 case outside the gate **forever**. The second failure is strictly
    # worse than the first.
    #
    # So: #137 keys on a vocabulary constant its own tests need, and #138 and #139 key on the
    # module. Those two fire when #137 lands, and the marker comes off in two later passes. That
    # is a known, accepted false alarm rather than an unnoticed one -- and it is the fifth
    # instance of a limitation a fourth registry kind would close (see PR #164).
    "#137": (
        "symbol",
        f"{CALIB_MODULE}:TRIAGE_CATEGORIES",
        ("tests/contract/calib/test_ct_calib_discovery_and_elicitation.py"
         "::test_tc_calib_c03_the_discovery_report_carries_no_accuracy_figure",
         "tests/contract/calib/test_ct_calib_discovery_and_elicitation.py"
         "::test_tc_calib_c04_a_disagreement_without_a_triage_category_is_refused",
         "tests/contract/calib/test_ct_calib_discovery_and_elicitation.py"
         "::test_tc_calib_c04_only_rubric_ambiguity_can_produce_a_proposed_edit"),
    ),
    "#138": (
        "module",
        CALIB_MODULE,
        ("tests/contract/calib/test_ct_calib_removability.py",
         "tests/contract/calib/test_ct_calib_discovery_and_elicitation.py",
         "tests/contract/calib/test_ct_calib_lock_and_gates.py"),
    ),
    "#139": (
        "module",
        CALIB_MODULE,
        ("tests/contract/calib/test_ct_calib_removability.py",
         "tests/contract/calib/test_ct_calib_lock_and_gates.py"),
    ),
    # `TC-CALIB-C09`'s rollup half is `M-GRADE`'s behaviour, not `M-CALIB`'s: R₀- and R₁-scored
    # results must not share an unannotated rollup. Keyed on the consumer that implements it.
    "#101": (
        "module",
        GRADE_MODULE,
        ("tests/contract/calib/test_ct_calib_lock_and_gates.py"
         "::test_tc_calib_c09_a_rollup_never_mixes_r0_and_r1_results_without_annotation",),
    ),
    "#2": (
        "path",
        "fixtures/F-FROZEN/manifest.json",
        ("tests/artifact/test_heldout_disjoint.py",),
    ),
    # `TC-PROV-18`'s six counters (`FR-PROV-12`). Keyed on **#20** rather than #19, although
    # both must have landed: `transport_retries` cannot be implemented before there is a retry
    # to count, so #19 lands first by construction and keying on it would fire while the
    # counters were still absent. The `symbol` target is the accessor rather than the module --
    # `aeh.prov` arrives with #18, months before `FR-PROV-12`.
    "#20": (
        "symbol",
        # `LocalServerProvider.counters`, because that is the object the test drives -- the
        # registry's question is which blocker *resolved* makes the test runnable, and
        # `RecordedFixtureProvider.counters` resolving would fire the gate for a test that
        # then fails on a provider it never mentions. Same trap the #122 note describes.
        f"{PROVIDER_MODULE}:LocalServerProvider.counters",
        ("tests/unit/prov/test_run_counters.py",),
    ),
    # `SEC-03` -- `cloud-hosted` retention (`FR-PROV-14`). `OpenRouterProvider` is named
    # verbatim in design 3.2's Interfaces block, so this blocker is forced rather than guessed,
    # and retention is meaningless without the implementation that talks to the cloud.
    "#21": (
        "symbol",
        f"{PROVIDER_MODULE}:OpenRouterProvider.verify_retention",
        ("tests/unit/prov/test_retention_gate.py",),
    ),
    # `TC-PROV-21` and `SEC-04` scan assembled payloads for student names. Keyed on `M-JUDGE`
    # and **not** on `M-ORCH`, although both cases read as though they need a full run: design
    # 3.10 declares `assemble(unit) -> ScoringRequest` pure ("# pure, testable"), so a test
    # drives it 350 times with no scheduler, no store and no model call. #78 is the M-JUDGE
    # story that owns assembly, so it landing is exactly what makes these two runnable.
    #
    # Only the two case tests carry the marker; the file's scanner controls run in the gate
    # today, which is what keeps the cases from going green-by-blindness when #78 lands.
    "#78": (
        # The symbol the tests actually resolve, not the module: `aeh.judge` could land with
        # #79's numeral prohibition while `assemble` is still #78's.
        "symbol",
        f"{JUDGE_MODULE}:ScoringWorker",
        (
            "tests/artifact/test_payload_pseudonymization.py"
            "::test_tc_prov_21_no_assembled_payload_carries_a_student_name",
            "tests/artifact/test_payload_pseudonymization.py"
            "::test_sec_04_a_full_run_discloses_no_name_to_the_provider",
        ),
    ),
    # `TC-CONF-17` is the one case in TS-04 whose rung is not achievable: rung 2 means a
    # *finished run's* audit record. Keyed on `M-ORCH` rather than `M-STORE`, deliberately --
    # the case is a **differential** between what the orchestrator stores and what the run start
    # logged, so it needs the *producer*, not the storage. Unmarking it when `M-STORE` alone
    # landed would report a P1 case as covered while the test still wrote the row itself and
    # compared a value to itself.
    "#57": (
        # `symbol`, not `module`. `find_spec("aeh.orch")` resolves against an **empty file**, so a
        # module key fires on the first `M-ORCH` commit -- while `record_run_start` is still
        # absent and the test still cannot run. Whoever acted on that would unmark a P1 case and
        # get a failure nobody expects, which is how a gate stops being believed.
        #
        # `record_run_start` is the symbol the test actually calls, and its own docstring marks it
        # "**invented here** -- the orchestrator's write of the audit record". It appears in no
        # Interfaces block in either design document, so unlike a Protocol member it cannot exist
        # before an implementation does. (Checked: zero occurrences in detailed-design.md and
        # test-plan.md.)
        #
        # The case needs `M-STORE` too -- it calls `open_store` -- and keying on #57 alone is
        # still right: #57 depends on #11, which depends on #10, so `M-ORCH` landing means the
        # store already has.
        "symbol",
        f"{ORCH_MODULE}:record_run_start",
        ("tests/integration/conf/test_audit_record.py",),
    ),
    # The same issue, a different target. `TC-CONF-17` above needs the whole orchestrator, so a
    # module key is right for it; `FUZZ-06`'s work-ID half needs one function, and `aeh.orch` as an
    # empty file would fire the module key while `compute_work_id` was still absent. The dict key
    # carries the symbol so the two entries can coexist and the gate message names which is which.
    "#57 compute_work_id": (
        "symbol",
        f"{ORCH_MODULE}:compute_work_id",
        ("tests/property/test_fuzz_06_graphs_and_work_ids.py"
         "::test_fuzz_06_distinct_input_tuples_always_yield_distinct_work_ids",),
    ),
    # `TC-CONF-C14` step 3 is a **consumer sweep at rung 3**: with `M-ORCH` *and* `M-CONSOLE`
    # real, assert neither exposes a path that reaches a rebinding. Steps 1 and 2 are rung 0 and
    # run in the gate today; only the sweep is blocked.
    #
    # Keyed on `M-CONSOLE` although it needs both, because the gate fires when **any** registered
    # blocker resolves. Registering it against `M-ORCH` too would fire the moment #57 lands with
    # `M-CONSOLE` still months away -- and whoever acted on that would unmark a test that then
    # fails for a reason nobody expects, which is how a gate stops being believed. The
    # discriminating question is *which single blocker, resolved, means this test can run*:
    # #122 depends on #10 and #61, so `M-CONSOLE` lands strictly after `M-ORCH` and resolving it
    # means both halves are present.
    "#122": (
        "module",
        CONSOLE_MODULE,
        ("tests/contract/conf/test_no_rebinding.py::test_tc_conf_c14_step_3_no_consumer_"
         "exposes_a_path_that_rebinds_a_run",
         # TS-74's consumer-side cases. `TC-CALIB-C01` is the unusual one: §6.11.17 says it is
         # "really an assertion about M-CONSOLE, M-GRADE and M-ORCH, not of this module" -- it runs
         # the pipeline with M-CALIB *absent*, so its blocker is the pipeline rather than any
         # calibration story.
         "tests/contract/calib/test_ct_calib_removability.py"
         "::test_tc_calib_c01_grades_deliver_with_calibration_absent_and_with_it_disabled",
         "tests/contract/calib/test_ct_calib_removability.py"
         "::test_tc_calib_c15_the_console_renders_phase_4_surfaces_as_present_and_unavailable",
         "tests/contract/calib/test_ct_calib_discovery_and_elicitation.py"
         "::test_tc_calib_c03_the_console_renders_no_accuracy_language",
         "tests/contract/calib/test_ct_calib_lock_and_gates.py"
         "::test_tc_calib_c16_consumers_present_the_gate_as_non_inferiority_never_superiority"),
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
