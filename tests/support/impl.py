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
STATS_MODULE = f"{IMPLEMENTATION_PACKAGE}.stats"
CONFORM_MODULE = f"{IMPLEMENTATION_PACKAGE}.conform"
REVIEW_MODULE = f"{IMPLEMENTATION_PACKAGE}.review"
AGG_MODULE = f"{IMPLEMENTATION_PACKAGE}.agg"

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
    # `M-CALIB` is Phase 3/4 and three stories away: #137 (triage) -> #138 (elicitation, lock,
    # history) -> #139 (the two gates). The `Calibration` protocol declares six members and #137
    # will very likely stub all six at once, so keying a later story on a protocol member fires at
    # #137.
    #
    # An earlier draft concluded the only alternative was an invented name that might never appear
    # — leaving a P0 case outside the gate forever, which is strictly worse — and keyed #138 and
    # #139 on the whole module. That dichotomy was false. Each story's tests already call several
    # **non-protocol** names that story must supply, and none appears in any Interfaces block, so
    # none can exist before an implementation does. They are invented, but the tests invent and use
    # them together, which is what makes them self-consistent — the same reasoning as `open_store`
    # and `compute_work_id` in TS-56, and `record_run_start` in #164.
    "#137": (
        "symbol",
        f"{CALIB_MODULE}:TriageCategoryRequired",
        ("tests/contract/calib/test_ct_calib_discovery_and_elicitation.py"
         "::test_tc_calib_c03_the_discovery_report_carries_no_accuracy_figure",
         "tests/contract/calib/test_ct_calib_discovery_and_elicitation.py"
         "::test_tc_calib_c04_a_disagreement_without_a_triage_category_is_refused",
         "tests/contract/calib/test_ct_calib_discovery_and_elicitation.py"
         "::test_tc_calib_c04_only_rubric_ambiguity_can_produce_a_proposed_edit"),
    ),
    "#138": (
        "symbol",
        f"{CALIB_MODULE}:PhaseDependencyError",
        ("tests/contract/calib/test_ct_calib_removability.py",
         "tests/contract/calib/test_ct_calib_discovery_and_elicitation.py",
         "tests/contract/calib/test_ct_calib_lock_and_gates.py"),
    ),
    "#139": (
        "symbol",
        f"{CALIB_MODULE}:ThresholdNotDeclared",
        ("tests/contract/calib/test_ct_calib_removability.py",
         "tests/contract/calib/test_ct_calib_lock_and_gates.py"),
    ),
    # `TC-CALIB-C09`'s rollup half is `M-GRADE`'s behaviour, not `M-CALIB`'s: R0- and R1-scored
    # results must not share an unannotated rollup. Keyed on the consumer that implements it.
    "#101": (
        "module",
        GRADE_MODULE,
        ("tests/contract/calib/test_ct_calib_lock_and_gates.py"
         "::test_tc_calib_c09_a_rollup_never_mixes_r0_and_r1_results_without_annotation",),
    ),
    # §6.11.17 names `M-STATS` as a second consumer for both `CT-CALIB-09` (it scopes its figures
    # across the revision boundary) and `CT-CALIB-16` (it presents the gate as non-inferiority).
    # Both were missing from the first draft, one of them under a docstring claiming otherwise.
    # Split from one `module` key into two `symbol` keys by TS-73. `find_spec("aeh.stats")`
    # resolves against the module's **first** commit, which is #115's -- so the entry fired three
    # stories early and named two tests that still could not run. Both tests say `issue="#118"`
    # themselves, and each drives a different invented name, so each gets the symbol it actually
    # resolves. The calib assertions are untouched.
    "#118 criterion_figures": (
        "symbol",
        f"{STATS_MODULE}:criterion_figures",
        ("tests/contract/calib/test_ct_calib_lock_and_gates.py"
         "::test_tc_calib_c09_m_stats_scopes_its_figures_across_the_revision_boundary",),
    ),
    "#118 describe_revision_gate": (
        "symbol",
        f"{STATS_MODULE}:describe_revision_gate",
        ("tests/contract/calib/test_ct_calib_lock_and_gates.py"
         "::test_tc_calib_c16_m_stats_presents_the_gate_as_non_inferiority_too",),
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
    # --- TS-75 (#136), the fourteen CT-CONFORM clause cases ---------------------------------
    #
    # `M-CONFORM` has two implementing stories and they land in order: #133 builds the frozen
    # corpus (size, span, media, consent, the adversarial tier) and #134 runs it (full pipeline
    # per backend, the divergence report, the gates, the records, the tiers). Keyed separately,
    # because seven of the cases become runnable at #133 and the rest need a run.
    #
    # **Keyed on symbols no Interfaces block declares.** Design §3.18 declares a two-member
    # Protocol -- `ConformanceSuite.run` and `.compare` -- plus the type names in their
    # signatures: `ConformanceReport`, `DivergenceReport`, `BackendResult`. A key on any of those,
    # or on either member, resolves against a Protocol-only `aeh.conform` with nothing behind it,
    # which is the measurement review made in TS-56: the narrowing is zero.
    #
    # `load_fixture_set` and `detect_build_substitution` are names these tests actually call and
    # neither appears anywhere in either design document (checked: zero occurrences), so neither
    # can exist before an implementation does. They are invented -- as most of this suite's
    # surface is, because fourteen clauses cannot be written against two names -- and the tests
    # invent and use them together, which is what makes them self-consistent.
    #
    # `detect_build_substitution` rather than a constructor for #134: `build_conformance_suite` is
    # the constructor **both** stories need -- `FR-CONFORM-02`'s refusal is #133's acceptance
    # criterion and needs a suite object -- so keying #134 on it would fire while #134 was still
    # unstarted. `detect_build_substitution` is `FR-CONFORM-08`, which is #134's alone.
    #
    # **`TC-CONFORM-C09`'s two run-halves are keyed on #134, and the issues disagree about that.**
    # #133's *acceptance criteria* name both of them verbatim ("each yields the same band... no
    # higher confidence than its benign twin", "quarantine at V0 and reach no model call"), which
    # argues for #133; its *Evaluation strategy* line says the story is covered by C01-C05, which
    # argues for #134. Both cannot be right, and the same contradiction runs the other way for
    # `TC-CONFORM-C05`. Keyed on the later of the two here, because the registry's own rule is that
    # an early unmark is the worse direction: a test told to rejoin TEST_CMD that then fails naming
    # an issue nobody is working on is how the gate stops being believed. Reported on the PR for
    # `/plan-to-issues` rather than resolved here -- the issue bodies are that skill's artifact.
    "#133": (
        "symbol",
        f"{CONFORM_MODULE}:load_fixture_set",
        (
            "tests/contract/conform/test_ct_conform_corpus.py::test_tc_conform_c01_the_corpus_"
            "spans_the_score_range_including_mid_range_partial_credit",
            "tests/contract/conform/test_ct_conform_corpus.py::test_tc_conform_c01_a_result_"
            "names_its_fixtures_and_one_changed_fixture_changes_the_identity",
            "tests/contract/conform/test_ct_conform_corpus.py::test_tc_conform_c02_the_corpus_"
            "carries_handwriting_spanning_the_legibility_range_and_mixed_format",
            "tests/contract/conform/test_ct_conform_corpus.py::test_tc_conform_c09_every_"
            "injection_submission_is_paired_with_a_benign_twin",
            "tests/contract/conform/test_ct_conform_corpus.py::test_tc_conform_c10_the_suite_"
            "refuses_to_run_against_a_cohort_not_so_flagged",
            "tests/contract/conform/test_ct_conform_corpus.py::test_tc_conform_c10_the_corpus_"
            "is_only_synthetic_or_consented_work",
            "tests/contract/conform/test_ct_conform_corpus.py::test_tc_conform_c10_the_suite_"
            "does_not_reimplement_the_consent_check",
        ),
    ),
    "#134": (
        "symbol",
        f"{CONFORM_MODULE}:detect_build_substitution",
        (
            "tests/contract/conform/test_ct_conform_corpus.py::test_tc_conform_c02_the_fixtures_"
            "traverse_the_vlm_path_rather_than_a_text_shortcut",
            "tests/contract/conform/test_ct_conform_corpus.py::test_tc_conform_c09_an_injection_"
            "never_beats_its_twin_on_band_citations_or_confidence",
            "tests/contract/conform/test_ct_conform_corpus.py::test_tc_conform_c09_a_malicious_"
            "pdf_quarantines_at_v0_and_reaches_no_model_call",
            "tests/contract/conform/test_ct_conform_pipeline_and_divergence.py",
            "tests/contract/conform/test_ct_conform_tiers_records_and_hole.py::test_tc_conform_"
            "c06_every_written_record_carries_its_backend_profile_and_panel_build_ref",
            "tests/contract/conform/test_ct_conform_tiers_records_and_hole.py::test_tc_conform_"
            "c06_a_write_merging_two_backends_into_one_record_is_refused",
            "tests/contract/conform/test_ct_conform_tiers_records_and_hole.py::test_tc_conform_"
            "c08_the_fast_tier_runs_to_completion_with_the_network_hard_blocked",
            "tests/contract/conform/test_ct_conform_tiers_records_and_hole.py::test_tc_conform_"
            "c11_a_run_completes_within_the_declared_budget_on_each_backend",
            "tests/contract/conform/test_ct_conform_tiers_records_and_hole.py::test_tc_conform_"
            "c12_the_only_writes_this_module_makes_are_records_and_its_own_report",
            "tests/contract/conform/test_ct_conform_tiers_records_and_hole.py::test_tc_conform_"
            "c12_the_pipelines_own_writes_stay_attributed_to_their_owning_modules",
        ),
    ),
    # `TC-CONFORM-C14`'s consumer sweep splits by consumer. #29 owns the population- and
    # backend-scoped validation records, so it is what makes the `M-PKG` half runnable; the
    # `M-CONSOLE` half is #122's and rides with the other console sweeps below.
    #
    # `record_validation` is invented and absent from both design documents. `PackageCatalog`
    # declares `validation_for` -- the **read** side -- and no write method at all, which is worth
    # noticing on its own: `M-CONFORM` is required to write "through `M-PKG`" via a surface the
    # design never names.
    "#29": (
        "symbol",
        f"{PKG_MODULE}:record_validation",
        ("tests/contract/conform/test_ct_conform_tiers_records_and_hole.py"
         "::test_tc_conform_c14_m_pkg_records_no_backend_equivalence_claim",),
    ),
    # --- TS-77 (#132), the twelve CT-CONSOLE rendering and honesty clause cases ---------------
    #
    # `M-CONSOLE` is six stories, and these twelve cases land across four of them: #122 builds the
    # process (control rows, uploads, the monitor, the knobs, observability, the audit surface),
    # #124 the review queue and blind flow (invariants 8-14), #125 amendment, export and the
    # touchpoint sweep (invariants 15-21), #127 `NFR-CONSOLE-07`. Keyed per story, because a
    # single key would hold two thirds of the suite outside the gate for three stories.
    #
    # **Every name is invented, and here that is not a shortcut.** Design §3.19 declares *no Python
    # Interfaces block at all* -- only prose, a route table and §11.8's control-surface table. So
    # unlike `M-CALIB` or `M-CONFORM`, there is not even a Protocol to key against, and the
    # question of whether a symbol key narrows the window does not arise: nothing the design
    # declares could exist first. The whole invented surface is settled in one place
    # (`tests/support/console_vocabulary.py`), so twelve cases cannot each guess a different shape.
    # Checked: none of the four symbols below appears in either design document or the HLD.
    "#122 console_app": (
        # `symbol`, not `module`. The `#122` entry below is a **module** key that three other
        # suites' consumer sweeps ride on, and it fires on the first `aeh/console.py` commit --
        # right for a sweep that only needs the module to exist, wrong for eleven cases that drive
        # a running console. A second entry rather than a changed one, so neither loses precision.
        "symbol",
        f"{CONSOLE_MODULE}:build_console",
        (
            "tests/contract/console/test_ct_console_runtime_and_config.py::test_tc_console_c18_"
            "the_upload_handler_dispatches_the_work_rather_than_awaiting_it",
            "tests/contract/console/test_ct_console_runtime_and_config.py::test_tc_console_c18_"
            "a_large_upload_streams_to_the_blob_store_rather_than_into_memory",
            "tests/contract/console/test_ct_console_runtime_and_config.py::test_tc_console_c19_"
            "the_run_monitor_polls_the_ledger_and_adds_no_write_load",
            "tests/contract/console/test_ct_console_runtime_and_config.py::test_tc_console_c20_"
            "the_three_knobs_carry_their_declared_defaults",
            "tests/contract/console/test_ct_console_runtime_and_config.py::test_tc_console_c20_"
            "a_routable_bind_does_not_defeat_the_cloud_hosted_refusal",
            "tests/contract/console/test_ct_console_runtime_and_config.py::test_tc_console_c21_"
            "the_console_renders_with_no_toolchain_and_no_network",
            "tests/contract/console/test_ct_console_runtime_and_config.py::test_tc_console_c21_"
            "the_coupling_surface_is_its_reads_plus_its_declared_writes",
            # Node IDs, not the file: `TC-CONSOLE-C24` lives in the same file and is #127's. A
            # file-level entry would have told whoever closed #122 to unmark C24 as well, and it
            # would then have failed inside TEST_CMD naming an issue nobody was working on — the
            # precise trap the entries above are written to avoid.
            "tests/contract/console/test_ct_console_observability_and_honesty.py::test_tc_console_"
            "c22_the_console_emits_all_four_declared_metrics",
            "tests/contract/console/test_ct_console_observability_and_honesty.py::test_tc_console_"
            "c22_skip_rates_are_emitted_per_setup_step_not_in_aggregate",
            "tests/contract/console/test_ct_console_observability_and_honesty.py::test_tc_console_"
            "c23_the_absence_of_auth_holds_only_within_the_loopback_bound",
            "tests/contract/console/test_ct_console_observability_and_honesty.py::test_tc_console_"
            "c23_no_audit_surface_presents_an_actor_string_as_an_identity",
            # TS-76 (#131). `TC-CONSOLE-C01`, `-C02` and `-C03` are all `build_console`'s: they
            # drive a console object rather than a served process, which is what separates them
            # from the three under the `serve_console` key above.
            "tests/contract/console/test_ct_console_statelessness_and_writes.py::test_tc_console_"
            "c01_the_console_makes_no_inference_and_effects_change_by_writing_a_row",
            "tests/contract/console/test_ct_console_statelessness_and_writes.py::test_tc_console_"
            "c01_two_tabs_and_a_closed_browser_leave_the_run_untouched",
            "tests/contract/console/test_ct_console_statelessness_and_writes.py::test_tc_console_"
            "c02_the_runtime_write_surface_equals_the_declared_control_actions",
            "tests/contract/console/test_ct_console_statelessness_and_writes.py::test_tc_console_"
            "c02_every_write_a_screen_makes_maps_to_a_declared_action",
            "tests/contract/console/test_ct_console_statelessness_and_writes.py::test_tc_console_"
            "c02_everything_else_the_console_does_is_a_read",
            "tests/contract/console/test_ct_console_statelessness_and_writes.py::test_tc_console_"
            "c03_every_control_action_is_idempotent_through_all_three_replay_routes",
            "tests/contract/console/test_ct_console_statelessness_and_writes.py::test_tc_console_"
            "c03_an_action_against_stale_state_is_refused_or_idempotent_never_partial",
        ),
    ),
    "#124": (
        "symbol",
        f"{CONSOLE_MODULE}:render_review_queue",
        (
            "tests/contract/console/test_ct_console_review_and_blind.py",
            # TS-76 (#131). `FR-CONSOLE-03` (no annotation surface, no path into a judgment) and
            # `-17`/`-18` (browser storage, external origins) are all #124's, so `TC-CONSOLE-C04`
            # and `-C06` land here rather than with #122's process work.
            "tests/contract/console/test_ct_console_isolation_and_binding.py::test_tc_console_c04_"
            "no_field_the_console_writes_after_the_lock_is_read_by_a_scoring_prompt",
            "tests/contract/console/test_ct_console_isolation_and_binding.py::test_tc_console_c04_"
            "no_per_student_annotation_surface_exists_on_any_route",
            "tests/contract/console/test_ct_console_isolation_and_binding.py::test_tc_console_c04_"
            "a_resumed_unit_reads_no_console_written_field",
            "tests/contract/console/test_ct_console_isolation_and_binding.py::test_tc_console_c06_"
            "no_page_reaches_browser_storage_with_student_text_in_the_data",
            "tests/contract/console/test_ct_console_isolation_and_binding.py::test_tc_console_c06_"
            "every_page_loads_from_its_own_origin_and_nothing_else",
        ),
    ),
    # #125 owns invariants 15-21, which is `FR-CONSOLE-21` (amendment), `-22` (review window),
    # `-23` (the export gate) and `-25` (the touchpoint sweep).
    #
    # `TC-CONSOLE-C19`'s measurement half rides here too, and that is a judgment call worth
    # stating: `NFR-CONSOLE-01` is traced to **#126**, which builds S1, S2, S6 and S8 -- none of
    # the two screens the NFR names. The case needs the review queue (#124) and the rollup (#125),
    # which are siblings with no dependency between them, so no single key is certainly last.
    # #125 is chosen because it completes the rollup surface. The mis-trace is a finding for
    # `/plan-to-issues`, reported on the PR rather than fixed here.
    "#125": (
        "symbol",
        f"{CONSOLE_MODULE}:amend_finalized_grade",
        (
            "tests/contract/console/test_ct_console_finalization_and_touchpoints.py",
            "tests/contract/console/test_ct_console_runtime_and_config.py::test_tc_console_c19_"
            "the_review_queue_and_rollup_render_inside_their_budgets_at_350_students",
            # TS-76 (#131). Three renderings whose FR is #125's rather than #123's:
            # `FR-CONSOLE-20` (invariant 16, every displayed band editable), `FR-CONSOLE-24`
            # (invariant 20, the absent agreement block) and `FR-CONSOLE-19` (invariant 15, the
            # blind reservation subtracted before ranking). Their sibling halves in the same files
            # are keyed on #123, which is why these are node IDs.
            "tests/contract/console/test_ct_console_screens_and_fields.py::test_tc_console_c08_"
            "every_route_that_shows_a_grade_shows_it_as_an_editable_band",
            "tests/contract/console/test_ct_console_provenance_and_queues.py::test_tc_console_"
            "c11b_with_no_blind_labels_the_block_says_so_and_carries_no_prior_figure",
            "tests/contract/console/test_ct_console_provenance_and_queues.py::test_tc_console_c12_"
            "the_blind_reservation_is_subtracted_before_ranking_not_after",
        ),
    ),
    "#127": (
        "symbol",
        f"{CONSOLE_MODULE}:render_submission_text",
        ("tests/contract/console/test_ct_console_observability_and_honesty.py"
         "::test_tc_console_c24_non_english_and_rtl_content_fails_or_degrades_visibly",),
    ),
    # --- TS-76 (#131), the twelve CT-CONSOLE security, isolation and prohibition cases ----------
    #
    # Keyed per **rendering**, not per case. `TC-CONSOLE-C11` carries three separate renderings
    # (§6.11.19: *"the clause carries three separate renderings and the case asserts each"*) and
    # they belong to three different stories -- (a) to #123, (b) to #125, (c) to #126, which is
    # `FR-CONSOLE-26`'s S1 Packages. `-C12` splits the same way. A single key would hold two
    # renderings outside the gate waiting on a story neither of them needs.
    #
    # So these entries are **node IDs throughout**, never a bare filename: every one of the four
    # files below mixes blockers. That is the trap TS-77 hit with `TC-CONSOLE-C24`, where a
    # file-level entry would have told whoever closed #122 to unmark another story's test.
    #
    # `serve_console` gets its own key rather than riding on `build_console`. The three tests under
    # it bind a real socket or spawn a process, and `require()` reports whichever blocker resolves
    # first -- so a test whose first call is `serve_console` must be registered against
    # `serve_console`, or the gate unmarks it while the thing it actually needs is still missing.
    "#122 serve_console": (
        "symbol",
        f"{CONSOLE_MODULE}:serve_console",
        (
            "tests/contract/console/test_ct_console_statelessness_and_writes.py::test_tc_console_"
            "c01_killing_the_console_process_leaves_the_run_and_its_queued_rows_intact",
            "tests/contract/console/test_ct_console_isolation_and_binding.py::test_tc_console_c05_"
            "the_console_binds_loopback_verified_against_the_actual_socket",
            "tests/contract/console/test_ct_console_isolation_and_binding.py::test_tc_console_c05_"
            "every_cloud_hosted_setting_combination_refuses_to_start",
        ),
    ),
    # #123 owns HLD §11.6's invariants 1-7, which is where `-C07` through `-C12`'s separation half
    # and `-C10`/`-C11`(a) live. `render_setup_step` is invented and absent from both design
    # documents and the HLD.
    #
    # One limitation, stated rather than discovered: no registry kind can express *"the story is
    # finished"*, only *"this symbol exists"* -- the sixth time this suite has hit it. So a symbol
    # landing on #123's first commit would tell a reader to unmark all eleven of these while the
    # rest of #123 is still being written. `render_setup_step` is chosen because invariant 1 is
    # #123's first acceptance criterion and nothing in #122 could provide it, which makes the
    # window as narrow as the mechanism allows.
    "#123": (
        "symbol",
        f"{CONSOLE_MODULE}:render_setup_step",
        (
            "tests/contract/console/test_ct_console_screens_and_fields.py::test_tc_console_c07_"
            "exactly_two_screens_block_and_they_are_s3_and_s4",
            "tests/contract/console/test_ct_console_screens_and_fields.py::test_tc_console_c07_"
            "every_skippable_prompt_renders_the_skip_and_its_cost_in_one_view",
            "tests/contract/console/test_ct_console_screens_and_fields.py::test_tc_console_c08_"
            "no_route_anywhere_offers_a_numeric_score_entry_field",
            "tests/contract/console/test_ct_console_screens_and_fields.py::test_tc_console_c09_"
            "no_route_or_payload_carries_a_per_student_progress_figure",
            "tests/contract/console/test_ct_console_screens_and_fields.py::test_tc_console_c09_"
            "progress_renders_at_the_three_dimensions_and_derives_nothing_more",
            "tests/contract/console/test_ct_console_provenance_and_queues.py::test_tc_console_c10_"
            "every_route_that_displays_a_grade_displays_its_provenance",
            "tests/contract/console/test_ct_console_provenance_and_queues.py::test_tc_console_"
            "c11a_any_agreement_statistic_renders_corrected_scoped_and_unmerged",
            "tests/contract/console/test_ct_console_provenance_and_queues.py::test_tc_console_c12_"
            "quarantine_and_the_review_queue_have_separate_routes_and_counts",
            "tests/contract/console/test_ct_console_provenance_and_queues.py::test_tc_console_c12_"
            "no_quarantine_item_is_reachable_from_the_review_queue",
            "tests/contract/console/test_ct_console_provenance_and_queues.py::test_tc_console_c12_"
            "no_deterministic_blind_or_random_arm_item_is_rendered_in_the_queue",
        ),
    ),
    # #126 builds S1 Packages, S2 Upload, S6 Preflight and S8 Quarantine, and it depends only on
    # #122 -- so it is a **sibling** of #123 and #125 rather than downstream of them. That is
    # exactly why `TC-CONSOLE-C11`(c) has its own key: `FR-CONSOLE-26` is S1's rule and no amount
    # of #123 or #125 landing makes it renderable.
    "#126": (
        "symbol",
        f"{CONSOLE_MODULE}:render_package_catalog",
        (
            "tests/contract/console/test_ct_console_provenance_and_queues.py::test_tc_console_"
            "c11c_a_package_never_administered_here_renders_no_borrowed_figure",
        ),
    ),
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
         "::test_tc_calib_c16_consumers_present_the_gate_as_non_inferiority_never_superiority",
         # TS-75's console half of `TC-CONFORM-C14`. The console is where a release decision is
         # actually read, so it is the surface on which a backend-equivalence claim does damage.
         # Its `M-PKG` twin is keyed on #29 above: the two land at different moments, and keying
         # both on the later would hold one of them outside the gate for nothing.
         "tests/contract/conform/test_ct_conform_tiers_records_and_hole.py"
         "::test_tc_conform_c14_m_console_renders_no_backend_equivalence_claim"),
    ),
    # --- TS-73 (#121), the twenty-one CT-STATS clause cases -----------------------------------
    #
    # `M-STATS` is four stories -- #115 (the admissible-label filter, the figure, the scoped
    # result), #116 (the MVVP), #117 (compression, surface proxies, routing policy, drift) and
    # #118 (the validation record, the weakest criterion, narrative metrics) -- and the twenty-one
    # cases land across all four plus nine consumer stories. Keyed per story: a single key would
    # hold four fifths of the suite outside the gate until the last of them shipped.
    #
    # **Every symbol below is one the story that owns it introduces, never a constructor.**
    # `build_stats` and `open_stats` are #115's, so a #117 case probing `build_stats` would resolve
    # the moment the filter landed -- and then run against a `compression_check` that did not exist
    # yet and fail with `AttributeError`, which is precisely the failure this registry exists to
    # prevent. So each case probes the member *its* story delivers first and constructs through
    # #115 afterwards; attribution is measured per test, and the thirteen groups below are what the
    # run reports rather than what the plan predicted.
    #
    # The consumer-side rows reuse the per-story console symbols the TS-77 entries above already
    # settled (`render_setup_step` for #123, `amend_finalized_grade` for #125) rather than
    # `render_agreement_block`, which #123 and #125 both touch: `FR-CONSOLE-10`'s scoped rendering
    # and `FR-CONSOLE-24`'s honest absence are two invariants on one renderer, and a shared target
    # would fire #125's rows at #123.
    "#115": (
        "symbol",
        f"{STATS_MODULE}:build_stats",
        (
            "tests/contract/stats/test_admissible_labels_only.py"
            "::test_tc_stats_c01_a_contaminated_population_in_a_real_store_is_excluded",
            "tests/contract/stats/test_admissible_labels_only.py"
            "::test_tc_stats_c01_each_contaminated_label_class_is_excluded[deterministic_mcq]",
            "tests/contract/stats/test_admissible_labels_only.py"
            "::test_tc_stats_c01_each_contaminated_label_class_is_excluded[operational]",
            "tests/contract/stats/test_admissible_labels_only.py"
            "::test_tc_stats_c01_each_contaminated_label_class_is_excluded[saw_system_output]",
            "tests/contract/stats/test_admissible_labels_only.py"
            "::test_tc_stats_c01_each_contaminated_label_class_is_excluded[whole_grade_sample]",
            "tests/contract/stats/test_admissible_labels_only.py"
            "::test_tc_stats_c01_no_function_in_the_module_computes_agreement_over_another_population",
            "tests/contract/stats/test_admissible_labels_only.py"
            "::test_tc_stats_c01_the_admissibility_filter_exists_once_in_the_source",
            "tests/contract/stats/test_admissible_labels_only.py"
            "::test_tc_stats_c01_the_predicate_is_a_conjunction_and_admits_only_the_blind_judged_label",
            "tests/contract/stats/test_ct_stats_checks_and_scope.py"
            "::test_tc_stats_c15_no_statement_in_the_source_writes_a_score_grade_or_package_row",
            "tests/contract/stats/test_ct_stats_checks_and_scope.py"
            "::test_tc_stats_c18_reads_only_tier_d_and_the_current_cohorts_labels",
            "tests/contract/stats/test_ct_stats_figures_and_keying.py"
            "::test_tc_stats_c02_a_figure_without_its_scope_or_its_n_cannot_be_constructed[backend_profile]",
            "tests/contract/stats/test_ct_stats_figures_and_keying.py"
            "::test_tc_stats_c02_a_figure_without_its_scope_or_its_n_cannot_be_constructed[n]",
            "tests/contract/stats/test_ct_stats_figures_and_keying.py"
            "::test_tc_stats_c02_a_figure_without_its_scope_or_its_n_cannot_be_constructed[panel_build_ref]",
            "tests/contract/stats/test_ct_stats_figures_and_keying.py"
            "::test_tc_stats_c02_a_figure_without_its_scope_or_its_n_cannot_be_constructed[population_scope_id]",
            "tests/contract/stats/test_ct_stats_figures_and_keying.py"
            "::test_tc_stats_c02_a_figure_without_its_scope_or_its_n_cannot_be_constructed[scoring_model]",
            "tests/contract/stats/test_ct_stats_figures_and_keying.py"
            "::test_tc_stats_c02_every_emitted_figure_is_chance_corrected",
            "tests/contract/stats/test_ct_stats_figures_and_keying.py"
            "::test_tc_stats_c02_the_figure_declares_exactly_the_fields_the_design_names",
            "tests/contract/stats/test_ct_stats_figures_and_keying.py"
            "::test_tc_stats_c04_atomic_and_holistic_are_reported_separately_and_no_function_merges_them",
            "tests/contract/stats/test_ct_stats_figures_and_keying.py"
            "::test_tc_stats_c04_every_emitted_statistic_echoes_the_scope_it_was_asked_for",
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c16_a_genuine_programming_error_still_raises",
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c16_no_entry_point_raises_because_there_is_too_little_data[agreement]",
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c17_statistics_over_accumulated_labels_compute_within_the_budget",
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c20_the_module_declares_no_pass_fail_threshold_over_a_quality_figure",
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c21_a_two_band_criterion_returns_its_number_and_discloses_the_degeneracy",
            "tests/contract/stats/test_no_validation_data_type.py"
            "::test_tc_stats_c03_agreement_reports_which_kind_of_absence_it_found[no_blind_labels]",
            "tests/contract/stats/test_no_validation_data_type.py"
            "::test_tc_stats_c03_agreement_reports_which_kind_of_absence_it_found[no_data_for_backend]",
            "tests/contract/stats/test_no_validation_data_type.py"
            "::test_tc_stats_c03_agreement_reports_which_kind_of_absence_it_found[no_data_for_population]",
            "tests/contract/stats/test_no_validation_data_type.py"
            "::test_tc_stats_c03_every_entry_point_returns_the_value_rather_than_a_substitute[agreement]",
            "tests/contract/stats/test_no_validation_data_type.py"
            "::test_tc_stats_c03_is_a_distinct_type_carrying_each_declared_reason[no_blind_labels]",
            "tests/contract/stats/test_no_validation_data_type.py"
            "::test_tc_stats_c03_is_a_distinct_type_carrying_each_declared_reason[no_data_for_backend]",
            "tests/contract/stats/test_no_validation_data_type.py"
            "::test_tc_stats_c03_is_a_distinct_type_carrying_each_declared_reason[no_data_for_population]",
            "tests/contract/stats/test_no_validation_data_type.py"
            "::test_tc_stats_c03_is_not_numerically_coercible_by_any_route",
            "tests/contract/stats/test_no_validation_data_type.py"
            "::test_tc_stats_c03_refuses_a_reason_outside_the_declared_literal",
        ),
    ),
    "#116": (
        "symbol",
        f"{STATS_MODULE}:run_mvvp",
        (
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c16_no_entry_point_raises_because_there_is_too_little_data[run_mvvp]",
            "tests/contract/stats/test_ct_stats_mvvp.py"
            "::test_tc_stats_c07_a_judge_above_the_stability_threshold_carries_its_position_bias_result",
            "tests/contract/stats/test_ct_stats_mvvp.py"
            "::test_tc_stats_c07_reports_the_six_steps_individually_and_offers_no_single_verdict",
            "tests/contract/stats/test_ct_stats_mvvp.py"
            "::test_tc_stats_c08_a_prior_result_is_not_reused_shown_or_merged_after_a_change",
            "tests/contract/stats/test_ct_stats_mvvp.py"
            "::test_tc_stats_c08_a_result_names_the_exact_configuration_it_measured",
            "tests/contract/stats/test_ct_stats_mvvp.py"
            "::test_tc_stats_c08_the_full_mvvp_reruns_when_each_dimension_changes[model_build]",
            "tests/contract/stats/test_ct_stats_mvvp.py"
            "::test_tc_stats_c08_the_full_mvvp_reruns_when_each_dimension_changes[panel_member]",
            "tests/contract/stats/test_ct_stats_mvvp.py"
            "::test_tc_stats_c08_the_full_mvvp_reruns_when_each_dimension_changes[prompt_template_version]",
            "tests/contract/stats/test_ct_stats_mvvp.py"
            "::test_tc_stats_c08_the_full_mvvp_reruns_when_each_dimension_changes[quantization]",
            "tests/contract/stats/test_no_validation_data_type.py"
            "::test_tc_stats_c03_every_entry_point_returns_the_value_rather_than_a_substitute[run_mvvp]",
        ),
    ),
    "#117": (
        "symbol",
        f"{STATS_MODULE}:compression_check",
        (
            "tests/contract/stats/test_ct_stats_checks_and_scope.py"
            "::test_tc_stats_c10_compares_panel_against_gold_bands_on_hand_computed_constants",
            "tests/contract/stats/test_ct_stats_checks_and_scope.py"
            "::test_tc_stats_c10_states_its_co_compression_blind_spot_inside_the_return_value",
            "tests/contract/stats/test_ct_stats_checks_and_scope.py"
            "::test_tc_stats_c11_compares_both_arms_using_blind_labels_only",
            "tests/contract/stats/test_ct_stats_checks_and_scope.py"
            "::test_tc_stats_c11_similar_error_rates_in_both_arms_are_reported_as_failing",
            "tests/contract/stats/test_ct_stats_checks_and_scope.py"
            "::test_tc_stats_c18_subgroup_analysis_is_off_by_default_and_refuses_when_disabled",
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c16_no_entry_point_raises_because_there_is_too_little_data[compression_check]",
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c16_no_entry_point_raises_because_there_is_too_little_data[drift_check]",
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c16_no_entry_point_raises_because_there_is_too_little_data[routing_policy_validity]",
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c16_no_entry_point_raises_because_there_is_too_little_data[surface_proxies]",
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c19_each_contract_alert_exists_and_fires[surface_proxy_flag]",
            "tests/contract/stats/test_ct_stats_records_and_absence.py"
            "::test_tc_stats_c12_a_sample_outside_the_declared_range_is_refused[19]",
            "tests/contract/stats/test_ct_stats_records_and_absence.py"
            "::test_tc_stats_c12_a_sample_outside_the_declared_range_is_refused[31]",
            "tests/contract/stats/test_ct_stats_records_and_absence.py"
            "::test_tc_stats_c12_the_drift_check_covers_judged_criteria_only",
            "tests/contract/stats/test_no_validation_data_type.py"
            "::test_tc_stats_c03_every_entry_point_returns_the_value_rather_than_a_substitute[compression_check]",
            "tests/contract/stats/test_no_validation_data_type.py"
            "::test_tc_stats_c03_every_entry_point_returns_the_value_rather_than_a_substitute[drift_check]",
            "tests/contract/stats/test_no_validation_data_type.py"
            "::test_tc_stats_c03_every_entry_point_returns_the_value_rather_than_a_substitute[routing_policy_validity]",
            "tests/contract/stats/test_no_validation_data_type.py"
            "::test_tc_stats_c03_every_entry_point_returns_the_value_rather_than_a_substitute[surface_proxies]",
        ),
    ),
    "#118 stats": (
        "symbol",
        f"{STATS_MODULE}:promote",
        (
            "tests/contract/stats/test_ct_stats_checks_and_scope.py"
            "::test_tc_stats_c15_the_validation_record_is_written_through_m_pkg",
            "tests/contract/stats/test_ct_stats_figures_and_keying.py"
            "::test_tc_stats_c04_an_aggregate_spanning_a_forbidden_dimension_is_refused[assignment_type]",
            "tests/contract/stats/test_ct_stats_figures_and_keying.py"
            "::test_tc_stats_c04_an_aggregate_spanning_a_forbidden_dimension_is_refused[backend]",
            "tests/contract/stats/test_ct_stats_figures_and_keying.py"
            "::test_tc_stats_c04_an_aggregate_spanning_a_forbidden_dimension_is_refused[population]",
            "tests/contract/stats/test_ct_stats_figures_and_keying.py"
            "::test_tc_stats_c13_an_aggregate_cannot_be_obtained_without_its_weakest_criterion",
            "tests/contract/stats/test_ct_stats_figures_and_keying.py"
            "::test_tc_stats_c14_narrative_quality_is_reported_separately_from_agreement",
            "tests/contract/stats/test_ct_stats_figures_and_keying.py"
            "::test_tc_stats_c14_no_function_offers_a_combined_quality_figure",
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c16_no_entry_point_raises_because_there_is_too_little_data[promote]",
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c17_the_analytical_export_is_read_only_and_does_not_touch_a_live_run",
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c19_each_contract_alert_exists_and_fires[blind_sample_skipped]",
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c19_emits_the_declared_counters",
            "tests/contract/stats/test_ct_stats_records_and_absence.py"
            "::test_tc_stats_c05_an_administration_with_no_blind_labels_does_not_advance_the_figures",
            "tests/contract/stats/test_ct_stats_records_and_absence.py"
            "::test_tc_stats_c06_an_operational_only_administration_leaves_kappa_unchanged",
            "tests/contract/stats/test_ct_stats_records_and_absence.py"
            "::test_tc_stats_c06_label_weighting_applies_to_operational_signals_and_not_to_the_figure",
            "tests/contract/stats/test_ct_stats_records_and_absence.py"
            "::test_tc_stats_c06_promote_increments_the_three_counters_separately",
            "tests/contract/stats/test_ct_stats_records_and_absence.py"
            "::test_tc_stats_c09_a_criterion_with_no_history_returns_no_data_rather_than_a_zero_rate",
        ),
    ),
    "#10 tier_d": (
        "symbol",
        f"{STORE_MODULE}:open_store",
        (
            "tests/contract/stats/test_ct_stats_checks_and_scope.py"
            "::test_tc_stats_c18_tier_d_holds_no_student_name_column_reachable_from_here",
        ),
    ),
    "#29 stats": (
        "symbol",
        f"{PKG_MODULE}:validation_for",
        (
            "tests/contract/stats/test_ct_stats_records_and_absence.py"
            "::test_tc_stats_c05_the_package_record_reports_the_message_rather_than_a_stale_figure",
        ),
    ),
    "#31 stats": (
        "symbol",
        f"{PKG_MODULE}:export_package",
        (
            "tests/contract/stats/test_ct_stats_figures_and_keying.py"
            "::test_tc_stats_c13_an_exported_package_carries_the_weakest_figure_beside_the_headline",
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c20_no_consumer_renders_or_exports_a_single_headline_figure[m_pkg_export]",
        ),
    ),
    "#91 stats": (
        "symbol",
        f"{AGG_MODULE}:describe_agreement",
        (
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c21_no_consumer_presents_binary_agreement_as_equivalent_to_multi_band[m_agg]",
        ),
    ),
    "#93 stats": (
        "symbol",
        f"{AGG_MODULE}:rank_criteria_for_escalation",
        (
            "tests/contract/stats/test_ct_stats_records_and_absence.py"
            "::test_tc_stats_c09_both_consumers_rank_no_data_differently_from_a_genuine_zero[m_agg]",
        ),
    ),
    "#108 stats": (
        "symbol",
        f"{REVIEW_MODULE}:rank_queue_items",
        (
            "tests/contract/stats/test_ct_stats_records_and_absence.py"
            "::test_tc_stats_c09_both_consumers_rank_no_data_differently_from_a_genuine_zero[m_review]",
        ),
    ),
    "#123 stats": (
        "symbol",
        f"{CONSOLE_MODULE}:render_setup_step",
        (
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c20_no_consumer_renders_or_exports_a_single_headline_figure[m_console]",
            "tests/contract/stats/test_ct_stats_limits_and_nonpromises.py"
            "::test_tc_stats_c21_no_consumer_presents_binary_agreement_as_equivalent_to_multi_band[m_console]",
        ),
    ),
    "#125 stats": (
        "symbol",
        f"{CONSOLE_MODULE}:amend_finalized_grade",
        (
            "tests/contract/stats/test_ct_stats_records_and_absence.py"
            "::test_tc_stats_c05_the_console_renders_the_message_not_the_previous_administrations_number",
            "tests/contract/stats/test_no_validation_data_type.py"
            "::test_tc_stats_c03_the_console_renders_the_absence_and_never_a_zero_or_a_blank",
        ),
    ),
    "#126 stats": (
        "symbol",
        f"{CONSOLE_MODULE}:render_preflight",
        (
            "tests/contract/stats/test_ct_stats_records_and_absence.py"
            "::test_tc_stats_c12_a_maximally_adverse_drift_result_does_not_block_a_run",
        ),
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
