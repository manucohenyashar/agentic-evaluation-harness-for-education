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
EXTRACT_MODULE = f"{IMPLEMENTATION_PACKAGE}.extract"
INGEST_MODULE = f"{IMPLEMENTATION_PACKAGE}.ingest"

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
#   "symbols" "mod:a,mod:b" (comma-separated)   -- a test with more than one blocker; resolved
#                                                  only when every one of them is
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
    # The `"#10"` and `"#10 tier_d"` entries that stood here are gone because #10 landed:
    # `aeh.store` exists, `SEC-15`'s reflective probe and `TC-STATS-C18`'s Tier D column sweep
    # both run in the gate, and a resolved blocker left in this dict fails the gate test by
    # design.
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
    # **Re-keyed off `open_store` by #10.** Both entries stood on `open_store` because, when they
    # were written, `M-STORE` was one unbuilt module and any name in it was as good as any other.
    # #10 has now landed `open_store` while the blob store and the write queue are still #12's and
    # #11's -- so the old keys fired the gate telling a reader to unmark two tests that then fail
    # on `NotImplementedError`, which is the precise trap this registry exists to avoid. The
    # discriminating question is unchanged: *which single blocker, resolved, makes this test
    # runnable*.
    #
    # Both new targets are **implementation** names, not the Protocols design §3.3 declares:
    # `BlobStore` and `TierHandle.transaction` both exist today (as a Protocol and as a method
    # that raises), so either would resolve immediately -- the same Protocol trap TS-56 measured.
    # Checked: neither `ContentAddressedBlobStore` nor `WriteQueue` appears anywhere in
    # `detailed-design.md`, `test-plan.md` or `src/`.
    # The `"#12"` entry that stood here -- `symbol`, `aeh.store:ContentAddressedBlobStore` --
    # is gone because #12 landed it, and `FUZZ-07`'s blob property is unmarked and in the gate.
    # The `"#11"` entry that stood here -- `symbol`, `aeh.store:WriteQueue` -- is gone because
    # #11 landed it. Its case is unmarked and inside `TEST_CMD`, and a resolved blocker left in
    # this dict fails the gate test by design.
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
    # --- TS-08 (#14), the nine M-STORE integration cases -------------------------------------
    #
    # Four keys because TS-08's nine cases are implemented by four different stories — #10 opens
    # the tiers, #11 builds the write queue, #12 the blob store, #13 the no-search and Tier D
    # guarantees — and a single key would hold six cases outside the gate until the last of the
    # four landed.
    #
    # **Keyed on names that appear in no Interfaces block**, for the reason TS-74 records at
    # length above: design §3.3 declares `Store`, `TierHandle`, `BlobStore` and every one of
    # their members in one block that #10 creates, so a key on any of them — or on any member —
    # resolves against a Protocol-only module and fires the gate up to three stories early.
    # `open_store`, `store_metrics`, `blob_store_stats` and `StudentNameInTierDError` are the
    # constructors and accessors these tests actually call (see `tests/support/store_api.py`,
    # which is also where the design gaps they represent are written down), and none can exist
    # before an implementation of the story that owns it does.
    #
    # File paths, not `::nodeid`s: `test_every_registered_blocker_names_a_file_that_exists`
    # checks only `path.split("::")[0]`, so a typo'd nodeid names nothing and nothing says so.
    # Each file here has exactly one blocker, so the file path loses no precision.
    # **The `"#10 open_store"` entry that stood here was mis-keyed, and #10 landing proved it.**
    # It keyed `test_tier_handles.py` and `test_tc_store_15_no_search_surface.py` on
    # `aeh.store:open_store`, on the reasoning that a *constructible* store is what makes them
    # runnable. #10 landed `open_store` (PR #175), the gate fired on schedule -- and all four
    # cases it told a reader to unmark fail, because `open_store` is not what they need:
    #
    #   `TC-STORE-01`, `-02`, `-16` (`test_tier_handles.py`) call `TierHandle.transaction`,
    #     which #10 ships as `raise NotImplementedError("... is issue #11 (FR-STORE-04)")`.
    #   `TC-STORE-15` (`test_tc_store_15_no_search_surface.py`) calls `Store.blobs()`, which
    #     #10 ships as `raise NotImplementedError("... is issue #12 (FR-STORE-06)")`.
    #
    # So both files move to the entries for the stories that actually unblock them. The right
    # question was never "does a store exist" but "does every symbol this file calls exist",
    # and a constructor is the weakest available proxy for that when the constructor's own
    # story deliberately stubs its siblings. Measured, not argued: those four failures are what
    # `pytest tests/integration/store/test_tier_handles.py
    # tests/artifact/test_tc_store_15_no_search_surface.py` prints against `main` @ `576157b`.
    #
    # The collision that entry existed to report is gone -- #10's PR re-keyed TS-56's `"#11"`
    # and `"#12"` off `open_store` onto `WriteQueue` and `ContentAddressedBlobStore` -- which is
    # why this was the only entry that fired.
    #
    # A residual weakness this move does not close, recorded rather than papered over: `symbol`
    # cannot tell a name that is absent from one that is present and raises. `transaction` and
    # `blobs` both *exist* today; only their bodies are #11's and #12's. The keys below are
    # therefore proxies -- names that stand in for "the story landed" -- and neither is called by
    # the file it now guards. That cuts both ways, and the second direction is the worse one:
    #
    #   late  -- if #11 spells its metrics accessor something other than `store_metrics`,
    #            `test_tier_handles.py` sits outside the gate silently, forever.
    #   early -- if #11 lands `store_metrics` while `transaction` is still a stub, the gate fires,
    #            a reader unmarks, and three cases fail *inside* `TEST_CMD`. That is the failure
    #            this commit is repairing, one story further on.
    #
    # A fourth kind -- `"implemented"`: resolves *and* does not raise `NotImplementedError` --
    # narrows it but does not close it for these two targets, because `TierHandle.transaction`
    # and `Store.blobs` cannot be called without a constructed store over a real data directory,
    # and `blocker_is_resolved` is handed only `repo_root`. Sizing that probe is a change to the
    # harness rather than to TS-08, so it is a finding in the PR, not a change here.
    #
    # `TC-STORE-15` has **two** blockers, which is why it gets its own entry rather than riding
    # along with the blob store. Limb 1 sweeps every tier and `Store.blobs()` is one of them
    # (#12); limb 2 reads the declared statement registry `aeh.store:STATEMENTS`, which is a
    # fifth invented name and, unlike the other four, **belongs to no story at all** --
    # `tests/support/store_api.py` attributed it to #10, and #10 closed without it. One entry
    # takes one target, so the key must be whichever lands *last*, or the gate fires early and
    # a reader unmarks a test that then reds inside `TEST_CMD`.
    #
    # An earlier draft of this commit keyed it on `STATEMENTS` alone, reasoning that #13 lands
    # after #12 "either way". Checked against the graph rather than the issue numbers, that is
    # false: **#12 and #13 both carry `Depends on: #10` and nothing else**, so nothing orders
    # them and both are in the ready set today. Picking either symbol is a coin flip between the
    # two failure directions, which is how this whole branch started. Hence the `symbols` kind:
    # the entry names both and resolves only when both do.
    #
    # `STATEMENTS` is attributed to **#13** because `FR-STORE-08` ("no search") is #13's
    # requirement and a declared-statement registry is how a store keeps that promise checkable.
    # That is a presumption, not a resolution -- no issue's acceptance criteria mention
    # `STATEMENTS`, and `store_api.py` guessed #10 before #10 closed without it. If #13 closes
    # without it too, the conjunction never resolves and this P0 case sits outside the gate with
    # nothing saying so. Reported in the PR for whoever owns the design and the issue graph; it
    # cannot be fixed from a test file.
    # The `"#11 store_metrics"` entry that stood here is gone for the same reason: #11 landed
    # `store_metrics`, so `TC-STORE-01`, `-02`, `-03`, `-07`, `-16` and `-24` lost the marker and
    # now run. Not in `TEST_CMD`, and the distinction is worth keeping straight: they carry
    # `pytest.mark.integration`, which `scripts/test.sh` deselects on its own account (test plan
    # §4.7). Losing `writtenahead` puts a test back in `pytest -q`, which is the honest full
    # picture and what a PR reports; the fast tier is a separate filter. Of the six only
    # `FUZZ-07`'s property rejoined the gate, which is why it moved 758 -> 759 rather than by six.
    # …and `"#12 blob_store_stats"` with it: `TC-STORE-09` is unmarked and runs. It carries
    # `pytest.mark.integration`, so it rejoined `pytest -q` rather than the fast tier -- the
    # distinction the `"#11 store_metrics"` note above spells out.
    #
    # …and the `"#12 and #13"` conjunction with them: both halves have landed --
    # `blob_store_stats` with the blob store (#12), and `STATEMENTS` with #13, whose guard and
    # purge statements joined the registry #12's own write had already opened -- so
    # `TC-STORE-15` is unmarked and back in the gate. The `symbols` kind was added for this one
    # case; it held the marker on through #11, which either single-symbol key would not have.
    #
    # The `"#13 StudentNameInTierDError"` entry that stood here is gone too: #13 landed the
    # error, the Tier D write guard (`FR-STORE-12`) and the `STATEMENTS` registry
    # (`FR-STORE-08`), so `TC-STORE-12` lost the marker and runs in the integration tier again
    # -- out of `TEST_CMD` on its own `integration` marker, back in `pytest -q`, the honest
    # full picture. Two fixture adaptations came with it (the #177 situation: the landing
    # disproved the fixture, not the assertions) -- limb 2 now inserts into the landed `label`
    # table rather than creating an `audit_record` that collided with migration 001, and
    # `schema_version` is excluded from the sweep as bookkeeping. See the case's docstring.
    # --- TS-01 (#2), the six §6.9 baselines --------------------------------------------------
    #
    # The `#2` entry that stood here -- `path`, `fixtures/F-FROZEN/manifest.json` -- is gone
    # because #2 landed: the corpora exist, `tests/artifact/test_heldout_disjoint.py` runs in
    # the gate, and a resolved blocker left in this dict fails the gate test by design.
    #
    # The six entries below replace it, and they are keyed on **producers, not on corpora**.
    # That is the whole shape of TS-01: the corpora are inputs and they are here now, but every
    # `TC-REG-*` case compares an artifact against a frozen baseline, and an artifact is the
    # output of a module. So each case waits on the story that emits it, and each key names a
    # symbol that story must supply rather than the module -- `aeh.ingest` existing says
    # nothing about whether it can assemble a document yet.
    #
    # None of the six golden files exist either, and that is deliberate rather than an omission:
    # `tests/support/baselines.py` explains why a baseline committed before its producer freezes
    # a guess. `golden_bytes()` raises `NotImplementedYet` naming the same issue as the key here,
    # so the two cannot drift.
    "#37": (
        # `assemble_canonical_markdown`, not `Ingestor.ingest_submission`: design §3.7 declares
        # the `Ingestor` Protocol, so a key on any of its members resolves against a
        # Protocol-only `aeh.ingest` with nothing behind it. Checked: this name appears nowhere
        # in either design document. #36 creates the module and the canonical artifact; #37 adds
        # `FR-INGEST-06`'s assembly order, and `TC-REG-01` traces to both -- so #37 is the later
        # of the two and the one whose landing makes the case runnable.
        "symbol",
        f"{INGEST_MODULE}:assemble_canonical_markdown",
        ("tests/regression/test_reg_01_canonical_markdown.py",),
    ),
    "#31 baselines": (
        # The same symbol `#31 stats` keys on, under its own key so neither entry's message
        # loses track of which suite it is unmarking.
        "symbol",
        f"{PKG_MODULE}:export_package",
        ("tests/regression/test_reg_02_package_archive.py",),
    ),
    "#104": (
        # `GradingService.export` is declared in design §3.14, so it is Protocol surface and
        # cannot be the key. `export_grade_artifacts` is this suite's -- it returns the CSV and
        # the per-student PDF set together, which is what `FR-GRADE-17` promises and what the
        # baseline covers. Checked: absent from both design documents.
        "symbol",
        f"{GRADE_MODULE}:export_grade_artifacts",
        ("tests/regression/test_reg_03_grade_exports.py",),
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
        (
            "tests/property/test_fuzz_06_graphs_and_work_ids.py"
            "::test_fuzz_06_distinct_input_tuples_always_yield_distinct_work_ids",
            # TS-01 (#2). `TC-REG-06`'s baseline is the `work_id` reference values, computed by
            # the same function over the ten committed input tuples. Same blocker, same symbol —
            # a second key would only split one unmarking instruction into two.
            "tests/regression/test_reg_06_work_id_reference.py",
        ),
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
            # TS-01 (#2). `TC-REG-05`'s baseline is the per-criterion score distribution of
            # `F-FROZEN` on each backend, and the assertion that carries the requirement is
            # `FR-CONFORM-08`: a shift under an unchanged package is build substitution to be
            # *detected*, not a baseline to update. `detect_build_substitution` is therefore the
            # symbol the case actually drives, so it is already the right key.
            "tests/regression/test_reg_05_score_distributions.py",
        ),
    ),
    # --- TS-02 (#3), the behavioural half of `TC-CONFORM-09` ---------------------------------
    #
    # Its own key rather than riding on `#134` above, and the reason is the one the `#122
    # serve_console` note states: `require()` reports whichever blocker it resolves **first**, so a
    # test whose first call is `run_adversarial_tier` must be registered against
    # `run_adversarial_tier`. Registering it under the existing `#134` entry (keyed on
    # `detect_build_substitution`) would unmark it when `FR-CONFORM-08` landed, while the thing it
    # actually drives was still absent.
    #
    # **Keyed on a symbol no Interfaces block declares.** Design §3.18 declares `ConformanceSuite`
    # with two members, `run` and `compare`, plus the type names in their signatures -- so a key on
    # any of those resolves against a Protocol-only `aeh.conform` with nothing behind it, which is
    # the measurement TS-56 made and TS-75 repeated. `run_adversarial_tier` is `FR-CONFORM-09`'s
    # own phrase (*"an adversarial-input tier"*) turned into a name, appears nowhere in either
    # design document (checked: zero occurrences), and is invented and used together by the one
    # suite that drives it.
    #
    # #134 rather than #133, for the same reason TS-75 keys `TC-CONFORM-C09`'s two run-halves
    # there: #133 builds the corpus and #134 runs it, and this half is a run. The corpus half of
    # the same case is in `tests/artifact/` and carries no marker -- it is green, because the
    # corpora are TS-02's deliverable rather than something it waits on.
    "#134 adversarial": (
        "symbol",
        f"{CONFORM_MODULE}:run_adversarial_tier",
        ("tests/integration/conform/test_tc_conform_09_adversarial_tier.py",),
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
            # TS-01 (#2). `TC-REG-04`'s baseline is the rendered HTML of *three* surfaces -- the
            # review queue, the rollup and the student view. Keyed on #125 for the same reason
            # `TC-CONSOLE-C19`'s measurement half above is: the queue is #124's and the rollup is
            # #125's, they are siblings, and #125 is the one that completes the surface. Keying on
            # #124 would unmark a test that then fails on a rollup nobody has built.
            "tests/regression/test_reg_04_console_html.py",
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
            "::test_tc_stats_c12_the_check_stays_inside_the_declared_sample_range[19]",
            "tests/contract/stats/test_ct_stats_records_and_absence.py"
            "::test_tc_stats_c12_the_check_stays_inside_the_declared_sample_range[31]",
            "tests/contract/stats/test_ct_stats_records_and_absence.py"
            "::test_tc_stats_c12_the_drift_check_covers_judged_criteria_only",
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
    # --- TS-72 (#114), the twenty CT-REVIEW clause cases -----------------------------------
    #
    # `M-REVIEW` is four stories: #108 builds the queue, #109 the admission prohibitions and the
    # residual, #110 the label store, #111 the two samples. Attribution below was **measured**,
    # not read off the stories' `Evaluation strategy` lines: a plugin recorded which `require()`
    # fired per test, and the first pass reported #108 for 68 of the 81 -- because every case has
    # to construct a service before it can probe anything.
    #
    # That is exactly the shape of the `#118` defect this registry already carries a fix for. A
    # key on `build_review` resolves the day #108 lands and drops #109/#110/#111's cases out of
    # the gate while they are still failing, now with an `AttributeError` instead of a stated
    # reason. So each case gained a `require_attr` for the member **its own story delivers**, and
    # the key below is the *last* blocker rather than the first.
    #
    # Every target is a name that appears in **no** Interfaces block. §3.15 declares
    # `ReviewService`'s six members, so a key on `blind_sample` or `submit_blind` resolves
    # against a Protocol-only module -- and a key on a *member of the concrete class* never
    # resolves at all if the implementation puts it somewhere else, which leaves a P0 case
    # outside the gate permanently. `build_review`, `write_fields`, `record_label` and
    # `blind_sample_skipped` are this suite's own inventions (declared in
    # `tests/support/review_vocabulary.py`'s docstring) and cannot exist before an implementation
    # does.
    #
    # Four keys are the reviewer's corrections rather than the plugin's: three cases reach the
    # blind flow (#111) or the label store (#110) through a *call* rather than a `require`, which
    # a scan of `require(issue=...)` arguments cannot see. `CT-REVIEW-14` was one test needing two
    # independent stories -- #78 and #68, either of which could land first -- so it is
    # parametrized per consumer and each half carries its own key. And `CT-REVIEW-09`'s
    # transport-layer step reaches a different console symbol from the other three console cases,
    # so it gets its own entry rather than riding on `render_review_queue`.
    "#108 review": (
        "symbol",
        f"{REVIEW_MODULE}:build_review",
        (
            "tests/contract/review/test_ct_review_admission_and_residual.py"
            "::test_tc_review_c04_the_queue_states_all_three_figures_and_they_are_arithmetically_consistent",
            "tests/contract/review/test_ct_review_budget_and_ranking.py"
            "::test_tc_review_c01_a_five_minute_budget_shows_fewer_items_with_the_same_ranking_rule",
            "tests/contract/review/test_ct_review_budget_and_ranking.py"
            "::test_tc_review_c01_queue_size_tracks_the_minute_budget_and_not_a_proportion",
            "tests/contract/review/test_ct_review_budget_and_ranking.py"
            "::test_tc_review_c03_ranking_responds_to_each_error_probability_signal_alone",
            "tests/contract/review/test_ct_review_budget_and_ranking.py"
            "::test_tc_review_c03_rebuilding_with_unchanged_data_yields_an_identical_order",
            "tests/contract/review/test_ct_review_budget_and_ranking.py"
            "::test_tc_review_c03_the_order_does_not_move_when_only_self_confidence_changes",
            "tests/contract/review/test_ct_review_budget_and_ranking.py"
            "::test_tc_review_c03_the_ranking_score_is_expected_value_per_estimated_second",
            "tests/contract/review/test_ct_review_budget_and_ranking.py"
            "::test_tc_review_c16_build_time_is_excluded_from_the_teachers_minute_budget",
            "tests/contract/review/test_ct_review_budget_and_ranking.py"
            "::test_tc_review_c16_the_queue_builds_within_two_seconds_at_the_stated_load",
            "tests/contract/review/test_ct_review_budget_and_ranking.py"
            "::test_tc_review_c19_the_queue_still_degrades_honestly_when_est_seconds_is_badly_wrong",
            "tests/contract/review/test_ct_review_labels_and_edits.py"
            "::test_tc_review_c13_a_group_action_emits_one_label_per_member",
            "tests/contract/review/test_ct_review_labels_and_edits.py"
            "::test_tc_review_c13_group_items_rank_above_per_item_entries",
            "tests/contract/review/test_ct_review_limits_and_config.py"
            "::test_tc_review_c17_each_knob_declares_its_documented_default",
            "tests/contract/review/test_ct_review_limits_and_config.py"
            "::test_tc_review_c20_the_group_signature_is_exactly_the_declared_components",
            "tests/contract/review/test_ct_review_limits_and_config.py"
            "::test_tc_review_c20_two_items_differing_in_any_signature_component_are_not_grouped",
        ),
    ),
    "#109 review": (
        "symbol",
        f"{REVIEW_MODULE}:write_fields",
        (
            "tests/contract/review/test_ct_review_admission_and_residual.py"
            "::test_tc_review_c05_no_excluded_population_appears_in_a_built_queue",
            "tests/contract/review/test_ct_review_admission_and_residual.py"
            "::test_tc_review_c05_the_queues_admission_query_cannot_reach_the_excluded_populations",
            "tests/contract/review/test_ct_review_admission_and_residual.py"
            "::test_tc_review_c05_the_random_arm_spends_compute_and_produces_no_review_item",
            "tests/contract/review/test_ct_review_admission_and_residual.py"
            "::test_tc_review_c06_a_residual_item_is_never_silently_finalized_or_backfilled",
            "tests/contract/review/test_ct_review_admission_and_residual.py"
            "::test_tc_review_c06_a_review_action_writes_through_criterion_score_and_never_a_grade",
            "tests/contract/review/test_ct_review_admission_and_residual.py"
            "::test_tc_review_c06_residual_items_are_marked_provisional_unreviewed",
            "tests/contract/review/test_ct_review_admission_and_residual.py"
            "::test_tc_review_c06_the_residual_persists_across_review_sessions",
            "tests/contract/review/test_ct_review_limits_and_config.py"
            "::test_tc_review_c14_the_module_exposes_no_per_student_annotation_surface",
            "tests/contract/review/test_ct_review_sampling_and_staleness.py"
            "::test_tc_review_c15_an_action_on_a_stale_item_is_rejected_with_a_refresh",
        ),
    ),
    "#110 review": (
        "symbol",
        f"{REVIEW_MODULE}:record_label",
        (
            "tests/contract/review/test_ct_review_budget_and_ranking.py"
            "::test_tc_review_c19_both_calibration_inputs_are_stored_so_phase_2_has_a_path",
            "tests/contract/review/test_ct_review_labels_and_edits.py"
            "::test_tc_review_c12_an_edit_from_any_view_writes_the_same_action_and_the_same_label_type",
            "tests/contract/review/test_ct_review_labels_and_edits.py"
            "::test_tc_review_c12_new_points_is_derived_from_new_band_through_the_pinned_mapping",
            "tests/contract/review/test_ct_review_labels_and_edits.py"
            "::test_tc_review_c12_no_interface_in_the_module_accepts_a_numeric_score",
            "tests/contract/review/test_ct_review_labels_and_edits.py"
            "::test_tc_review_c13_group_labels_are_indistinguishable_from_individual_ones",
            "tests/contract/review/test_ct_review_limits_and_config.py"
            "::test_tc_review_c18_every_named_counter_is_emitted",
            "tests/contract/review/test_ct_review_limits_and_config.py"
            "::test_tc_review_c18_shown_and_flagged_are_emitted_as_a_pair",
            "tests/contract/review/test_ct_review_limits_and_config.py"
            "::test_tc_review_c18_the_budget_exhaustion_signal_is_retained_across_administrations",
            "tests/contract/review/test_saw_system_output.py"
            "::test_tc_review_c08_an_override_from_the_queue_still_records_that_the_system_was_visible",
            "tests/contract/review/test_saw_system_output.py"
            "::test_tc_review_c08_saw_system_output_is_populated_on_every_label_with_no_null",
        ),
    ),
    "#111 review": (
        "symbol",
        f"{REVIEW_MODULE}:blind_sample_skipped",
        (
            "tests/contract/review/test_blind_unreachability.py"
            "::test_tc_review_c09_blind_labels_carry_saw_system_output_zero_legitimately",
            "tests/contract/review/test_blind_unreachability.py"
            "::test_tc_review_c09_no_blind_session_object_caches_a_score_row",
            "tests/contract/review/test_blind_unreachability.py"
            "::test_tc_review_c09_no_system_output_is_available_before_submission",
            "tests/contract/review/test_blind_unreachability.py"
            "::test_tc_review_c09_the_blind_session_cannot_reach_criterion_score_at_the_query_level",
            "tests/contract/review/test_ct_review_budget_and_ranking.py"
            "::test_tc_review_c02_blind_minutes_are_subtracted_before_any_ranking_occurs",
            "tests/contract/review/test_ct_review_budget_and_ranking.py"
            "::test_tc_review_c02_the_blind_sample_survives_a_run_with_far_more_items_than_budget",
            "tests/contract/review/test_ct_review_labels_and_edits.py"
            "::test_tc_review_c07_every_label_names_an_actor_and_a_timestamp",
            "tests/contract/review/test_ct_review_labels_and_edits.py"
            "::test_tc_review_c07_every_label_type_carries_the_named_fields_by_set_equality",
            "tests/contract/review/test_ct_review_limits_and_config.py"
            "::test_tc_review_c17_moving_a_knob_changes_how_much_validation_evidence_is_produced",
            "tests/contract/review/test_ct_review_sampling_and_staleness.py"
            "::test_tc_review_c10_skipping_the_blind_sample_leaves_grades_delivered_and_finalized",
            "tests/contract/review/test_ct_review_sampling_and_staleness.py"
            "::test_tc_review_c11_the_blind_sample_draws_inside_its_range_over_judged_criteria_only",
            "tests/contract/review/test_ct_review_sampling_and_staleness.py"
            "::test_tc_review_c11_the_blind_sample_refuses_a_draw_outside_its_stated_range",
            "tests/contract/review/test_ct_review_sampling_and_staleness.py"
            "::test_tc_review_c11_the_draw_is_uniform_over_the_eligible_set_rather_than_first_n",
            "tests/contract/review/test_ct_review_sampling_and_staleness.py"
            "::test_tc_review_c11_the_whole_grade_sample_draws_from_the_auto_accepted_population_only",
            "tests/contract/review/test_ct_review_sampling_and_staleness.py"
            "::test_tc_review_c15_an_interrupted_blind_session_keeps_the_criteria_actually_answered",
            "tests/contract/review/test_saw_system_output.py"
            "::test_tc_review_c08_every_collection_path_writes_the_correct_saw_system_output_value",
        ),
    ),
    "#115 review": (
        "symbol",
        f"{STATS_MODULE}:build_stats",
        (
            "tests/contract/review/test_ct_review_labels_and_edits.py"
            "::test_tc_review_c07_both_bands_are_present_and_agreement_is_computed_over_them_not_points",
            "tests/contract/review/test_ct_review_limits_and_config.py"
            "::test_tc_review_c17_m_stats_achievable_precision_moves_with_the_knobs",
            "tests/contract/review/test_ct_review_sampling_and_staleness.py"
            "::test_tc_review_c10_the_absence_is_reported_rather_than_papered_over",
            "tests/contract/review/test_saw_system_output.py"
            "::test_tc_review_c08_m_stats_excludes_an_operational_label_from_agreement_and_says_how_many",
        ),
    ),
    # CT-REVIEW-04's rendering half and CT-REVIEW-19/-20's consumer-language sweeps are
    # `M-CONSOLE` surfaces. The clauses are M-REVIEW's and the assertions are not, which is
    # reported as a finding on the PR.
    "#124 review": (
        "symbol",
        f"{CONSOLE_MODULE}:render_review_queue",
        (
            "tests/contract/review/test_ct_review_admission_and_residual.py"
            "::test_tc_review_c04_the_console_renders_all_three_figures",
            "tests/contract/review/test_ct_review_budget_and_ranking.py"
            "::test_tc_review_c19_the_console_does_not_present_the_budget_as_a_guarantee_of_elapsed_time",
            "tests/contract/review/test_ct_review_limits_and_config.py"
            "::test_tc_review_c20_the_console_does_not_describe_a_group_as_semantically_clustered",
        ),
    ),
    # CT-REVIEW-09 step 3, the transport-layer probe. A P0 safety-property step that lands
    # outside the module its clause belongs to: `M-REVIEW` is a service with six methods and
    # no requests. Keyed on its own symbol because `render_review_queue` -- which three other
    # cases here need -- is the likelier of the two to land first.
    "#124 transport review": (
        "symbol",
        f"{CONSOLE_MODULE}:blind_flow_requests",
        (
            "tests/contract/review/test_blind_unreachability.py"
            "::test_tc_review_c09_no_blind_flow_request_returns_system_output_even_unrendered",
        ),
    ),
    # CT-REVIEW-14 intersects M-REVIEW's write set with what each scoring consumer assembles
    # into a prompt. #78 (M-JUDGE) and #68 (M-EXTRACT) are independent, so the case is
    # parametrized and each half is keyed on the story it actually needs -- rather than one
    # test keyed on whichever of the two somebody guessed would land last.
    "#78 review": (
        "symbol",
        f"{JUDGE_MODULE}:prompt_fields",
        (
            "tests/contract/review/test_ct_review_limits_and_config.py"
            "::test_tc_review_c14_the_write_set_and_the_scoring_prompt_fields_do_not_intersect[judge]",
        ),
    ),
    "#78 rerun review": (
        "symbol",
        f"{JUDGE_MODULE}:assemble_prompt",
        (
            "tests/contract/review/test_ct_review_limits_and_config.py"
            "::test_tc_review_c14_nothing_a_teacher_records_reaches_a_rerun_of_the_same_unit",
        ),
    ),
    "#68 review": (
        "symbol",
        f"{EXTRACT_MODULE}:prompt_fields",
        (
            "tests/contract/review/test_ct_review_limits_and_config.py"
            "::test_tc_review_c14_the_write_set_and_the_scoring_prompt_fields_do_not_intersect[extract]",
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
    if kind == "symbols":
        # Conjunction: resolved only when **every** listed symbol is. A comma-separated list of
        # `module:dotted.attr`, since a target already contains `:`.
        #
        # `symbol` assumes one test file has one blocker, which is true of nearly every entry
        # above and false for `TC-STORE-15`: limb 1 sweeps `Store.blobs()` (#12) and limb 2
        # reads `aeh.store:STATEMENTS` (#13). Neither issue depends on the other -- both carry
        # `Depends on: #10` and nothing else -- so the graph does not say which lands first, and
        # a single-symbol key is a coin flip between the two failure directions this registry
        # exists to prevent. Keying on the earlier one fires the gate while the later blocker is
        # still a stub, and a reader who does as instructed puts a red P0 case inside `TEST_CMD`.
        #
        # Conjunction is the honest encoding: the case becomes runnable when its *last* blocker
        # lands, whichever that turns out to be. It is deliberately not disjunction -- an "any"
        # kind would fire early by construction.
        return all(
            blocker_is_resolved("symbol", one.strip(), repo_root)
            for one in target.split(",")
            if one.strip()
        )
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
