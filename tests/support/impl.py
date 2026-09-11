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

from tests.support.extract_vocabulary import (
    ASSEMBLE as _EXTRACT_ASSEMBLE,
    PROMPT_FIELDS as _EXTRACT_PROMPT_FIELDS,
    TS26_EXTRACT_SYMBOLS,
    TS65_EXTRACT_SYMBOLS,
)

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
SETUP_MODULE = f"{IMPLEMENTATION_PACKAGE}.setup"
SYNTH_MODULE = f"{IMPLEMENTATION_PACKAGE}.synth"
INTEG_MODULE = f"{IMPLEMENTATION_PACKAGE}.integ"

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
    # `"#28"` is gone because #31 landed: `aeh.pkg:in_memory_catalog()` exists — a catalog
    # lifetime over one shared scratch Tier P store, delegating to the real
    # `PackageCatalog` (whose `create_version` now writes the draft's criteria and whose
    # `set_dependencies` is the real dependency write, cycle-refusing inside the
    # transaction so the refusal is a no-op, `CT-PKG-11`). Both FUZZ-06 graph-half cases
    # run unmarked; the work-ID half stays keyed on #57 below.
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
    # `M-CALIB` is Phase 3/4 and both of its stories have landed: #138 (elicitation, lock,
    # history) then #139 (the two gates); #137 (triage) landed `discover` and
    # `triage` and deliberately nothing else. The `Calibration` protocol declares
    # six members and a story may stub several at once, so keying a later story
    # on a protocol member fires at the first story that touches the module —
    # #137's forecast ("will very likely stub all six") resolved to two, which
    # is why #138 and #139 were keyed on the non-protocol names below instead.
    #
    # An earlier draft concluded the only alternative was an invented name that might never appear
    # — leaving a P0 case outside the gate forever, which is strictly worse — and keyed #138 and
    # #139 on the whole module. That dichotomy was false. Each story's tests already call several
    # **non-protocol** names that story must supply, and none appears in any Interfaces block, so
    # none can exist before an implementation does. They are invented, but the tests invent and use
    # them together, which is what makes them self-consistent — the same reasoning as `open_store`
    # and `compute_work_id` in TS-56, and `record_run_start` in #164.
    # The `"#137"` entry that stood here — `symbol`, `aeh.calib:TriageCategoryRequired` — is gone
    # because #137 landed it: `TriageCategoryRequired` is the module's own refusal type, and the
    # three cases it keyed (C03's type half and both C04 halves) are unmarked and inside TEST_CMD.
    # The `"#138"` entry that stood here — `symbol`, `aeh.calib:PhaseDependencyError` — is gone
    # because #138 landed it: `PhaseDependencyError` is the module's own refusal type for the
    # pre-lock vintage (`CT-CALIB-15`), and the fifteen cases it keyed (C05's two, C06's two
    # clauses, C10, C11's two, C12's teacher-time clause, C15's refusal) are unmarked and inside
    # TEST_CMD.
    # `#139`'s tuple included the discovery file even though most of that file landed with
    # #137/#138: its last writtenahead case, C12's dual-scoring cost disclosure, was #139's.
    # The `"#139"` entry that stood here — `symbol`, `aeh.calib:ThresholdNotDeclared` — is gone
    # because #139 landed it: `ThresholdNotDeclared` is the module's own refusal for the
    # undeclared non-inferiority threshold (`CT-CALIB-13`), and the eleven cases it keyed (C02's
    # sweep, C07's three, C08's two, C09's pin, C12's cost disclosure, C13's two, C14's two,
    # C16) are unmarked and inside TEST_CMD.
    # `TC-CALIB-C09`'s rollup half is `M-GRADE`'s behaviour, not `M-CALIB`'s: R0- and R1-scored
    # results must not share an unannotated rollup. Keyed on the consumer that implements it.
    # (`#101` landed: `aeh.grade` ships `class_rollup` and `cohort_with_mixed_revisions`,
    # so the entry is gone and the case runs unmarked.)
    # §6.11.17 names `M-STATS` as a second consumer for both `CT-CALIB-09` (it scopes its figures
    # across the revision boundary) and `CT-CALIB-16` (it presents the gate as non-inferiority).
    # Both were missing from the first draft, one of them under a docstring claiming otherwise.
    # Split from one `module` key into two `symbol` keys by TS-73. `find_spec("aeh.stats")`
    # resolves against the module's **first** commit, which is #115's -- so the entry fired three
    # stories early and named two tests that still could not run. Both tests say `issue="#118"`
    # themselves, and each drives a different invented name, so each gets the symbol it actually
    # resolves. The calib assertions are untouched. (`#118` landed: `aeh.stats` ships
    # both symbols, so both entries are gone and the two consumer cases run unmarked.)
    # --- TS-35 (#94), the M-AGG median-band aggregation cases ---------------------------------
    #
    # `"#91"` is gone because #91 landed: `aeh.agg` ships the median-band aggregate,
    # the ordinal α and `EvenPanelError` under exactly the vocabulary's declared
    # names (`tests/support/agg_vocabulary.py`'s table — no rename was needed, and
    # the module-level-function reading of §3.12's Protocol is the one that landed).
    # Every TS-35 file runs unmarked. The TS-36 files keep their markers: their
    # conjunctions name #92's/#93's members and did not resolve here.

    # FUZZ-05 carries a second, independent blocker: its policy half pins the #101
    # applicator — the design **does** declare it (`apply_policy(scores, policy) ->
    # GradeComputation`, detailed-design.md §3.14, CT-GRADE-02), so the entry keyed on the
    # declared name; only `GradeComputation`'s field set is unpinned and assumed (`.total`,
    # declared in the test's docstring). Split from the `#101` module entry above, which
    # resolves against `aeh.grade`'s **first** commit and so names a test the module's
    # existence does not make runnable — the `#118` split precedent. The fuzz file's
    # marker is per-test with node-ID paths (the `#118`/`#138`/`#139` form): a
    # module-level marker on a two-blocker file would let an early unmark move the
    # still-red half inside `TEST_CMD`.
    # (`#101 apply_policy` landed: `aeh.grade` ships `apply_policy` with `.total`, so the
    # entry is gone and the policy half runs unmarked.)
    # --- TS-36 (#95), the M-AGG confidence-inversion, routing and escalation cases -----------
    #
    # Thirteen cases across seven files, written ahead of THREE stories — #91 lands the
    # `aggregate` core, #92 the caps and the stored integrity inputs, #93 the routing,
    # the escalation policy and the score states — so the entries key per BLOCKER SET
    # rather than per story, and every conjunction is what the file's `require()` calls
    # actually resolve. `TC-AGG-16` is deliberately absent: its write-set guard is
    # structural and green today (the `TC-AGG-03` precedent), so it carries no marker.
    #
    # **Keyed on the same proxy #76 chose, for the same recorded reason.** No
    # §3.12-declared name isolates "the cap table landed" — the caps are
    # Assumption-numbered, not named — so the confidence entries rode on
    # `AGG_AUTO_THRESHOLD_ATOMIC` (unmarked at #92's landing: the inversion, the
    # recorded inputs and the recompute seam all landed there).
    #
    # **The three entries the #93 landing dropped** (unmarked 2026-09, that story):
    # "routing, escalation and thresholds" (`should_escalate` conjunction),
    # "score states" (`should_escalate` re-keyed at #91's landing as the states' gate)
    # and "policy purity" (the three-member conjunction) — all resolved when #93
    # shipped `should_escalate` beside the routing/state assignment. The round-trip
# entry (TC-AGG-15) went at #92's. The review-queue rank limb (TC-AGG-07) was
    # the last: its blocker was M-REVIEW's, not M-AGG's, and it unmarked at #108's
    # landing (`aeh.review:rank_queue_items`, whose `items` form orders
    # holistic-first at equal expected value and expected-value dominant
    # otherwise — FR-AGG-06's tie-break, taken as given).
    # --- TS-69 (#96), the M-AGG contract suite -------------------------------------------------
    #
    # Nine rows, keyed per owning story because the consumers land at different
    # moments (#101 M-GRADE, #108 M-REVIEW, #123 M-CONSOLE) and a single #96 key
    # would hold every writtenahead limb outside the gate until the last of them
    # shipped. Each names the symbol the OWNING story introduces — the same rule
    # the TS-73 entries below record — never a constructor: `build_review` and
    # `rank_queue_items` are #108's, `apply_policy` #101's, and the two console
    # renderers #123's. The executable core of every case (rungs 0-3, unmarked)
    # is in the same files; only the limbs whose consumer does not exist yet sit
    # behind these rows.
    #
    # **Three of the four M-REVIEW rows the #108 landing dropped** (unmarked
    # 2026-09, that story): the c05 rung-4 consequence, and the c07 and c16
    # M-REVIEW presentation limbs — keyed on `REVIEW_MODULE:build_review` /
    # `rank_queue_items`, which #108 shipped; each runs unmarked inside the
    # gate against the landed queue. The c05 unmark reconciled the
    # written-ahead draft's missing bridge (the limb asked the store-form queue
    # for a row it never persisted; it now performs the insert its own file's
    # rung-3 limb declares, per the queue's §3.15 data flow). The c09 ranking
    # limb STAYS marked — the queue cannot rank holistic-first at equal value
    # through the store, because `scoring_model` lives only in the Tier P
    # `criterion` table and cohort rows carry no package linkage — and its row
    # below is re-keyed on the landed queue surface plus the declared planned
    # owner of the scoring-model read; the gap is a finding on #108's PR.
    # (The two M-GRADE rows went at #101's landing: `aeh.grade` ships `apply_policy`,
    # so the c07 and c16 `[m_grade]` params run unmarked.)
    "#96 c09 holistic ranks higher at rung 3 (M-REVIEW)": (
        "symbols",
        (f"{REVIEW_MODULE}:ReviewService.queue,"
         f"{REVIEW_MODULE}:ReviewService.scoring_model_for"),
        (
            "tests/contract/agg/test_ct_agg_c09_no_runtime_special_casing.py"
            "::test_tc_agg_c09_a_holistic_criterion_ranks_higher_in_the_review_queue",
        ),
    ),
    # The `"#96 c07 M-CONSOLE presents ungradeable_by_panel"` entry that stood here is
    # gone because #126 landed: `aeh.console:build_console` exists, the c07
    # `[m_console]` param runs unmarked inside the gate (its `require` now resolves),
    # and the entry would only re-mark a running case.
    "#96 c14 the knobs' honesty text (M-CONSOLE)": (
        "symbol",
        f"{CONSOLE_MODULE}:render_setup_step",
        (
            "tests/contract/agg/test_ct_agg_c14_declared_knobs.py"
            "::test_tc_agg_c14_no_consumer_presents_the_knobs_as_empirically_justified",
        ),
    ),
    # The `"#96 c16 M-CONSOLE renders no probability"` entry that stood here is gone
    # because #124 landed `aeh.console:render_review_queue`, which the registry had
    # keyed on: the c16 `[m_console]` param ran against an invented
    # `render_review_queue(store).render_scores(...)` shape, and its reconciliation at
    # the unmark rekeyed the param to the landed `build_console` (#122) whose
    # `render_scores` actually presents the queued row. The entry would only re-mark
    # a running case.
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
    # `"#37"` is gone because #37 landed: `aeh.ingest:assemble_canonical_markdown`
    # exists — the pure assembly seam over the declared preference ladder (operator >
    # printed page number > fiducial > filename > refuse, never directory order) — and
    # both TC-REG-01 baselines were recorded in #37's PR.
    # `"#31 baselines"` is gone because #31 landed: `aeh.pkg:export_package` exists (the
    # module-level seam the written-ahead suites anticipated), `TC-REG-02` runs in the gate
    # and its baseline `TC-REG-02/PKG-REF.archive.json` was recorded in #31's PR.
    # `"#104"` is gone because #104 landed: `aeh.grade:export_grade_artifacts` exists — the
    # school-facing export whose shape the doctrine anticipated (the CSV of marks and the
    # per-student PDF set returned together, `FR-GRADE-17`) — `TC-REG-03` runs in the gate
    # and both its baselines were recorded in #104's PR.
    # `TC-PROV-18`'s six counters (`FR-PROV-12`). Keyed on **#20** rather than #19, although
    # both must have landed: `transport_retries` cannot be implemented before there is a retry
    # to count, so #19 lands first by construction and keying on it would fire while the
    # counters were still absent. The `symbol` target is the accessor rather than the module --
    # `aeh.prov` arrives with #18, months before `FR-PROV-12`.
    # The `"#20"` and `"#21"` entries that stood here are gone: #19 (the retry loop and the
    # Transport/Clock seam), #20 (the counters and BuildWatch) and #21 (the two live
    # providers and the fail-closed retention gate) landed together, so both TS-07 unit
    # files lost the marker and rejoined the fast tier. The anticipated seam held: the
    # tests' `retention_answers` dict keyed by build_id, the `transport=`/`clock=`
    # constructor arguments and the `counters` accessor all resolved against the shipped
    # surface without a test edit. #22 (TS-05) owns the fuller retry-taxonomy cases and the
    # live-API retention shapes.
    # The `"#78"` entry stood here: #78 landed `aeh.judge` (`ScoringWorker` and the
    # whitelist `ScoringRequest`), so the two `TC-PROV-21`/`SEC-04` case tests lost
    # their markers and rejoined the fast tier — the scanner controls in that file
    # never carried one. The rung-0 bet held: `worker_cls()` constructed with no
    # arguments, and both scans ran over the assembled requests unchanged.
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
    # because seven of the cases became runnable at #133 -- released when its fixture surface
    # (`load_fixture_set`, `build_conformance_suite`, `ConsentRefused`) landed -- and the rest
    # still need a run.
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
            # `M-JUDGE`'s `TC-JUDGE-C17` limb 4 (TS-67, #85) rides here, joined when
            # #302 landed the module: the limb needs a divergence REPORT, and `run()`'s
            # divergence machinery is #134's (the module's own stub says so) — the
            # constructor alone resolves against #302's build-only module, so a key on
            # it would unmark the limb while what it drives was still a stub. The
            # limb's FIRST `require()` is this entry's `detect_build_substitution`, so
            # `require()` reports THIS entry's blocker and the nodeid unmarks with the
            # rest of #134's surface.
            "tests/contract/judge/test_nonpromise_reproducibility.py"
            "::test_tc_judge_c17_m_conform_measures_repetition_and_requires_no_reproducibility",
            # TS-46 (#135), §5.18's seven behavioural cases, joined here. All seven drive the
            # same surface this entry proxies: `run()`'s report, the divergence machinery, the
            # substitution seam, and — for `TC-CONFORM-13` — the alert reader over all of it,
            # so there is one story's landing between each of them and green, exactly as for
            # the C-suite files above. The three `live`-marked files (TC-CONFORM-04, -08, and
            # the budget-threshold test in TC-CONFORM-11's file) are additionally env-gated on
            # `HARNESS_CONFORM_LIVE_BACKENDS` (the shared gate lives in `conform_vocabulary.py`),
            # so on a box without declared backends they skip naming that prerequisite; the
            # marker still keys them here, because the blocker is #134's machinery and only
            # looks like hardware. TC-CONFORM-06's plan-level
            # gap half and TC-CONFORM-07's CI half are green in `tests/artifact/` and carry
            # no marker — not listed here. The invented surfaces these files call beyond
            # `detect_build_substitution` (`evaluate_conformance_alerts`, the per-backend
            # figure and dispatch fields) are centralised in `conform_vocabulary.py`'s TS-46
            # section with the same adopt-or-rename rule.
            "tests/integration/conform/test_tc_conform_04_full_pipeline_differential.py",
            "tests/integration/conform/test_tc_conform_05_backend_scoped_records.py",
            "tests/integration/conform/test_tc_conform_06_divergence_gate_and_gap.py",
            "tests/integration/conform/test_tc_conform_08_build_substitution.py",
            "tests/integration/conform/test_tc_conform_11_run_budget.py",
            "tests/integration/conform/test_tc_conform_12_self_agreement.py",
            "tests/integration/conform/test_tc_conform_13_observability_alerts.py",
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
    # --- #148's OBS-07, the judge signals' emitter (`#85`'s `TC-JUDGE-C16`) -------------------
    #
    # `CT-JUDGE-16`'s six observability signals are not emitted by anything yet, and
    # no Interfaces block names the emitting operation — `judge_signals` is the
    # disclosure (`TC-JUDGE-C16`'s docstring records the same
    # invented-and-used-together reasoning the `#134 adversarial` entry does, with the
    # six field names centralised in `tests/support/judge_vocabulary.py` so a future
    # emitter cannot guess a different spelling). Keyed `symbol` on the emitter so the
    # marker comes off exactly when the name lands, whichever story carries it.
    #
    # Keyed `#148`, not `#85`: the Requires tables (design's `CT-JUDGE-16` row, the
    # plan's `TS-67` row) name `M-STATS` as the emitter's owner, and the
    # per-(criterion, judge) signals plus the concentrated-violation alert are
    # `OBS-07`'s acceptance — TS-55, issue #148. #85 is a TEST issue that closes with
    # its own PR; keying the marker on it would strand a red test naming a closed
    # issue — the registry's own rule, the one the `#134 adversarial` note records.
    # The stats module is
    # the Requires tables' own word; a symbol key releases on the name's landing
    # regardless of which story carries it.
    "#148 judge_signals": (
        "symbol",
        f"{STATS_MODULE}:judge_signals",
        ("tests/contract/judge/test_ct_judge_c16_signal_dimensionality.py",),
    ),
    # `"#29"` is gone because #31 landed: `aeh.pkg:record_validation` now exists as the
    # write side the design never named (catalog-backed for the in-memory catalog,
    # registry-backed for the export summary), so the `M-PKG` half of `TC-CONFORM-C14`'s
    # consumer sweep runs unmarked. The `M-CONSOLE` half is #122's and stays with the
    # console sweeps below.
    # --- TS-77 (#132), the twelve CT-CONSOLE rendering and honesty clause cases ---------------
    #
    # `M-CONSOLE` is six stories, and these twelve cases were keyed across four of them: #122 builds the
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
    # The `"#122 console_app"` entry that stood here is gone because #122 landed:
    # `aeh.console:build_console` exists and drives all eighteen of its cases -- the
    # `build_console`-keyed eleven (knobs, uploads, monitor, coupling, observability, the
    # audit surface) and TS-76's `TC-CONSOLE-C01`/`-C02`/`-C03` seven. The `"#124"` entry
    # is gone the same way: `aeh.console:render_review_queue` and `aeh.console:blind_flow`
    # exist and drive TS-77's CT-CONSOLE-13/-14 file plus TS-76's `TC-CONSOLE-C04`/`-C06`
    # five. `#125` and `#127` stay: their symbols (`amend_finalized_grade`,
    # `render_submission_text`) are still deliberately absent from the module, and the
    # node-ID discipline above is what kept them out of #122's sweep.
    # #125 owns invariants 15-21, which is `FR-CONSOLE-21` (amendment), `-22` (review window),
    # `-23` (the export gate) and `-25` (the touchpoint sweep).
    #
    # The `"#125"` entry that stood here is gone because #125 landed (merged with #124's
    # registry rewrite): `aeh.console` now ships `amend_finalized_grade`,
    # `export_package`, `ProvenanceRefused`, `touchpoint_surface` and
    # `render_agreement_block`, so the finalization/touchpoints file, `-C08`'s
    # editable-band sweep, `-C11`(b)'s honest absence, `-C12`'s reservation-ordering
    # half, the stats `-C05` console message and `TC-REG-04` -- the golden whose
    # producer surfaces are #125's, recorded at this landing -- all run in the gate.
    # `TC-CONSOLE-C19`'s measurement half had been keyed here too, and that was a
    # judgment call worth stating: `NFR-CONSOLE-01` is traced to **#126**, which builds
    # S1, S2, S6 and S8 -- none of the two screens the NFR names. The case needed the
    # review queue (#124) and the rollup (#125), siblings with no dependency between
    # them, so no single key was certainly last. The mis-trace was a finding for
    # `/plan-to-issues`, reported rather than fixed here. Reconciled at #124's landing:
    # the registry's premise -- "the rollup is #125's" -- was outdated, because
    # `render_rollup` had already landed with the console process, so the case's last
    # unmet `require` was the queue and it unmarked with #124. The node ID that stood
    # here is gone.
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
    # The `"#122 serve_console"` entry that stood here is gone because #122 landed:
    # `aeh.console:serve_console` exists, so the kill test and both `-C05` binding cases run
    # in the gate.
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
    # Both `"#126"` and the `"#122"` **module** entry that stood here are gone because #122 and
    # #126 landed: `aeh.console` exists with `render_package_catalog` and `render_preflight`, so
    # `TC-CONSOLE-C11`(c) runs in the gate, and the eight module-keyed consumer rows -- the
    # conf step-3 rebinding check, the four TS-74 calibration consumer cases, TS-75's conform
    # C14 console half -- all run too. `render_setup_step`, `amend_finalized_grade` and
    # `render_submission_text` stay absent: #123, #125 and #127 are still open, and those
    # are the keys their rows ride on. (`render_review_queue` was #124's and landed, so
    # the row that keyed on it -- the c16 `[m_console]` sweep -- runs too.)
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
    # The `"#115"` entry that stood here is gone because #115 landed: `aeh.stats` ships
    # `build_stats` -- with `agreement`, `AgreementFigure`, `NoValidationData` and the single
    # admissibility filter (NFR-STATS-04) -- so its registered cases run in the gate unmarked.
    # The `"#116"` entry is gone too: `aeh.stats` ships `run_mvvp` (the MVVP as six
    # separately-reported steps, CT-STATS-07/-08), so its ten registered cases -- the five
    # CT-STATS-07/-08 cases, the c16 sweep's [run_mvvp] row and the C17 M-STATS limb --
    # run in the gate unmarked. The `"#117"` entry is gone too: `aeh.stats` ships the four
    # comparisons -- `compression_check`, `surface_proxies`, `routing_policy_validity` and
    # `drift_check` -- plus the `alerts` surface and the subgroup knob, so its thirteen
    # registered cases run in the gate unmarked. The `"#118"` entry is gone too: `aeh.stats`
    # ships `promote` -- the validation record's writer, with the three separate counters,
    # the weakest criterion per population and the first-class absence message -- plus the
    # figure surface it delivers (`aggregate`, `criterion_override_history`,
    # `narrative_quality`, `operational_signal`, `observability_counters`, and the calib
    # consumers' `criterion_figures`/`describe_revision_gate`), so all sixteen of its
    # registered rows -- the c15 promotion write, the c04 aggregate refusals, the c13
    # weakest, the c14 pair, the c16 sweep's promote row, the c17 export, the c19 counters
    # and blind-sample alert, the c05/c06/c09 records cases -- and the synth c10 promotion
    # consumer run in the gate unmarked. The `open_stats` rung-2
    # cases needed `record_label`'s durable collection route (`data_dir=, label=,
    # cohort_id=`), which landed with #115 in `aeh.review`. The `"#29 stats"`
    # entry is gone too: `aeh.pkg` ships the module-level `validation_for` #29's
    # clause declared (`FR-PKG-09`) and #118's record read needed -- with the
    # administration-keyed `record_validation` shape the consumer calls -- so its
    # one registered case runs in the gate unmarked.
    # `"#31 stats"` is gone because #31 landed: `export_package` answers the validation
    # payload (`weakest_per_population` beside the per-population headline, never an
    # aggregate), and the `m_pkg_export` param of the CT-STATS-20 sweep runs unmarked. The
    # `m_console` param keeps its marker — #123 has not landed.
    #
    # `"#91 stats"` is gone because #91 landed: `aeh.agg:describe_agreement` is the
    # module's own disclosure of the figure it produces (CT-STATS-21's M-AGG limb),
    # and the sweep's `m_agg` param runs unmarked while `m_console` stays #123's.
    #
    # `"#93 stats"` is gone because #93 landed: `aeh.agg:rank_criteria_for_escalation`
    # ranks no-data first and a measured zero by its rate (CT-STATS-09's consumer
    # differential, c09), and the sweep's `m_agg` param runs unmarked.
    #
    # `"#108 stats"` is gone because #108 landed: `aeh.review:rank_queue_items`
    # carries the same `criteria=` form (`CriterionOverrideRank`, no data first,
    # then override rate descending — the mirror of `aeh.agg`), so the sweep's
    # `m_review` param runs unmarked too and both consumers answer c09 the same
    # way.
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
    # The `"#125 stats"` entry that stood here split when #125 landed, and the `-C03`
    # half that rode the conjunction of `render_agreement_block` and `NoValidationData`
    # is gone too because #115 landed the second symbol: the absence-rendering case
    # runs in the gate unmarked.
    # The `"#126 stats"` entry that stood here is gone because #126 landed: `aeh.console`
    # ships `render_preflight`, so `TC-STATS-C12`'s drift consumer runs in the gate reading
    # the real S6 ladder rather than a stand-in.
    # --- TS-70 (#100), the fourteen CT-SYNTH contract cases --------------------------------
    #
    # Four consumer sweeps are written ahead of their consumers, keyed on the symbols
    # those tests actually call -- with the same two keying rules the registry's earlier
    # entries settled:
    #
    # * a *member* of an unlanded story's class is gated through the story's **last**
    #   module-level symbol, because `require()` reports the first blocker it resolves
    #   and a key on the first would unmark a test whose member is still missing (the
    #   `#118` defect, fixed in the TS-72 shape). So C13's stats half rides
    #   `{STATS_MODULE}:promote` (#118's alone) exactly as the shipped `"#118 stats"`
    #   entry does, and C14's conform half rides
    #   `{CONFORM_MODULE}:detect_build_substitution` (#134's alone) exactly as the
    #   shipped `"#134"` entry does -- `build_conformance_suite` is the constructor
    #   *both* conform stories need, so keying on it would fire while #134 was
    #   unstarted.
    # * where one test needs two stories, the kind is `symbols` -- the conjunction: all
    #   of them must resolve before the test may rejoin TEST_CMD (C03 needs a console
    #   AND a grade service; C13 a console AND the narrative-quality story; C14 the
    #   rung-2 stats constructor AND the conform run).
    # (The grade-only rows went at #101's landing: `aeh.grade` ships `open_grade`, so
    # the C05/C08/C09 consumer legs run unmarked; C03 and C13 still wait on the
    # console conjunction.)
    # The `"#100 suppression consumers (C03)"` entry that stood here is gone because
    # #126 landed: `aeh.console:build_console` exists alongside `aeh.grade:open_grade`,
    # so C03's suppression consumer sweep runs in the gate. The `"#100 language consumers
    # (C13)"` and `"#100 promotion consumer (C10)"` entries are gone too because #118
    # landed: `aeh.stats:promote` now resolves, so both halves of C13's conjunction and
    # C10's promotion consumer run in the gate unmarked.
    "#100 comparison consumers (C14)": (
        "symbols",
        f"{STATS_MODULE}:open_stats,{CONFORM_MODULE}:detect_build_substitution",
        (
            "tests/contract/synth/test_ct_synth_c14_non_reproducible_prose.py"
            "::test_tc_synth_c14_the_comparison_consumers_do_not_diff_narratives",
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
    #
    # `"#108 review"` is gone because #108 landed (unmarked 2026-09, that story):
    # `aeh.review:build_review` constructs the service and its queue carries the
    # residual triple, the build trace, the groups and the greedy rank-order fill —
    # so the entry's fifteen cases unmark, and with them two orphans whose
    # substance landed with the same story: the CT-REVIEW-02 event-order case
    # (`build_trace` is #108's to provide; its marker came off and its line left
    # the "#111" list below) and the CT-REVIEW-14 rerun case (its binding blocker
    # was `build_review`). Every case below that reaches the samples (#111), the
    # label store (#110) or the write surface (#109) through a `require_attr` that
    # is still absent stays red for its own story, exactly as the keying above
    # intended.
    # `"#109 review"` stood here (`aeh.review:write_fields`, for the eleven cases it gated).
    # #109 landed: `write_fields` is the module-level write set, `admission_query` the
    # reachability plan, `write_audit` the per-write records, and `scores`/`end_session`/
    # `close_run` the residual's read path and its two audited moments — with `labels_for` as
    # the in-memory read the backfill and refusal assertions check. Unmarked 2026-09, that
    # story; the `[judge]`/`[extract]` write-set params unmarked with it (the marker was
    # function-level and shared). One reconciliation at the unmark: the c05 reachability
    # draft's single-routing pin became the landed two-routing admission — the provisional
    # family routes `provisional` and `CT-AGG-07`'s consumer differential makes admitting it
    # load-bearing — recorded in the test's docstring and in `review_vocabulary`.
    # The `#110 review` entry also stood here (`aeh.review:record_label`, ten cases);
    # #110 landed the module-level `record_label`/`labels_for` pair and the service's
    # label store, so its ten cases unmarked and rejoined the gate with this story.
    # The CT-REVIEW-02 event-order case (`c02_blind_minutes_are_subtracted...`)
    # unmarked at #108's landing: `build_trace` is #108's and the reservation step
    # sits in its trace, so the case's binding blocker resolved there. Only the
    # survival case below still waits on #111's sample surface. The `#110 review`
    # entry was removed at #110's landing: `record_label`/`labels_for` and the
    # service's label store are in, and its ten cases rejoined the gate.
    # `"#111 review"` is gone because #111 landed (unmarked 2026-09, that story):
    # `aeh.review:blind_sample_skipped` reports the skip, and with it the whole
    # blind surface is in — `blind_sample`/`submit_blind` (the 15-25 draw over
    # judged criteria), `whole_grade_sample` (the 10-15 auto-accepted grades),
    # `skip_blind_sample` with its one-consequence report, and the `BlindSession`
    # whose `readable_tables()`/`available_data()` are CT-REVIEW-09's probe
    # surface. Its fifteen cases unmarked and rejoined the gate. One
    # reconciliation at the unmark: the CT-REVIEW-08 sweep's fixture was
    # `flagged_population(12)`, which groups nothing by construction — `groups[0]`
    # was an IndexError for any implementation — so the fixture now appends a
    # two-row identical-signature population and the per-item paths select the
    # entries that carry no `members` attribute (a group ranks above items).
    # Recorded in the sweep's docstring. The CT-REVIEW-10 absence case stays red
    # for #115, as the keying above intended; the CT-REVIEW-09 transport step was
    # #124's and unmarked with it.
    # The `"#115 review"` entry that stood here is gone because #115 landed: the four
    # review cases that read M-STATS' figures (c07's bands-not-points, c17's achievable
    # precision, c10's absence reporting, c08's exclusion-with-a-count) run in the gate
    # unmarked.
    # The `"#124 review"` and `"#124 transport review"` entries stood here (`aeh.console:
    # render_review_queue` and `aeh.console:blind_flow_requests` for CT-REVIEW-04's rendering
    # half, CT-REVIEW-19/-20's consumer-language sweeps and CT-REVIEW-09 step 3). #124 landed
    # both symbols, so the five cases unmarked with it -- their clauses are M-REVIEW's but the
    # surfaces are the console's, which is a finding reported on #124's PR.
    # CT-REVIEW-14 intersects M-REVIEW's write set with what each scoring consumer assembles
    # into a prompt. #78 (M-JUDGE) and #68 (M-EXTRACT) are independent, so the case is
    # parametrized and each half was keyed on the story it actually needs -- rather than one
    # test keyed on whichever of the two somebody guessed would land last.
    #
    # The `"#78 review"` entry stood here (`aeh.judge:prompt_fields` for the `[judge]`
    # param). #78 landed it, but the param's BINDING blocker is #109's `write_fields`
    # -- the test resolves it before it reads either consumer -- and the writtenahead
    # marker is function-level, shared with the `[extract]` param. So the `[judge]`
    # half stayed marked with the file and unmarked with #109, below; keying this entry
    # on a symbol that is no longer what blocks it would have fired the gate and sent
    # someone to unmark a test that then fails on `write_fields`.
    #
    # The `"#78 rerun review"` entry stood here too (`aeh.judge:assemble_prompt` for
    # the c14 rerun case): #79 landed the id-keyed door, but the test's BINDING
    # blocker was always #108's `build_review` -- its first require resolves it before
    # `assemble_prompt` is read. #108 landed, and the c14 rerun case unmarked with
    # that story (verified green against the landed queue); the `[judge]` write-set
    # param below stayed marked for #109's `write_fields` and unmarked with it.
    # The "#68 review" entry stood here: `aeh.extract:prompt_fields` landed with #68,
    # so its blocker no longer holds. The `[extract]` param it named stayed marked for
    # #109's `write_fields` (its first require resolves it before it reads either
    # consumer), and the marker was function-level, shared with the `[judge]` param —
    # so both unmarked with the `#109 review` entry, which landed with that story.
    # --- TS-26 (#70), the M-EXTRACT suite ---------------------------------------------------
    #
    # The fourteen TC-EXTRACT cases. Design §3.8 pins the ExtractionRequest /
    # ExtractionResult SHAPES but **no Python names at all** — no Interfaces block, no
    # Protocol — so every name the suite resolves is an invented-and-used-together name
    # declared once in `tests/support/extract_vocabulary.py` (the record_run_start
    # precedent), and the conjunction below is BUILT from that file's
    # `TS26_EXTRACT_SYMBOLS`, so the registry cannot name a symbol the tests stopped
    # using (or vice versa). Keying on any single symbol would resolve early — the
    # Protocol-only trap TS-56/TS-74 documented does not apply here (no Protocol
    # declares these), but the full conjunction is still the honest blocker set: the
    # suite's files use most of the names together.
    #
    # `TC-EXTRACT-06` (deterministic criteria) and TC-EXTRACT-11's enumeration half,
    # TC-EXTRACT-13's cross-check half run GREEN against shipped M-ORCH and carry no
    # marker; they sit inside the marked files whose other cases wait on #68. The
    # second-family case was keyed separately below: #69 owns `FR-EXTRACT-07`'s
    # mechanism (Phase 2) and landed independently of #68.
    # The "#68 extraction suite (TS-26)" entry stood here: its conjunction over
    # `TS26_EXTRACT_SYMBOLS` (built from `tests/support/extract_vocabulary.py`)
    # resolved when #68 landed `aeh.extract`, and the seven suite files it named lost
    # their markers in the same change. What remains keyed of this suite is the one
    # case whose blocker #68 did NOT land — TC-EXTRACT-14 below — and the #69
    # second-family entry left with #69.
    # TC-EXTRACT-14 (`test_extract_pii_purge.py`) is keyed SEPARATELY from the TS-26
    # suite: #68 made its extraction half runnable (the payload provably carries the
    # student's verbatim work before the purge), but the purge half calls
    # `store.purge_cohort`, whose Tier D promotion precondition — `audit_record`,
    # `label` and `criterion_stats` scoped by `cohort_id`, and `promote` itself — is
    # M-STATS/M-REVIEW's to land (the shipped gate names them). Keyed on the promote
    # surface (the vocabulary bet: the store's own error names the operation); the
    # implementer who lands promotion unmarks the file and reconciles the case's
    # seeding with the promote API.
    "#68 TC-EXTRACT-14 purge (waits on M-STATS/M-REVIEW promotion)": (
        "symbol",
        f"{STATS_MODULE}:promote_cohort",
        ("tests/security/extract/test_extract_pii_purge.py",),
    ),
    # The "#69 second family (TS-26)" entry stood here: its conjunction over the
    # driver plus `second_family_model` resolved when #69 landed the different-family
    # model and the `ExtractionWorker` seam, and the file runs in TEST_CMD again.
    # --- TS-27 (#71), the M-EXTRACT injection-resistance cases ------------------------------
    #
    # Both entries stood here for TS-27. The injection-differential entry
    # (TC-EXTRACT-10, `test_extract_injection_resistance.py`) left with #68: its
    # conjunction over `TS27_EXTRACT_SYMBOLS` resolved when the extract module landed,
    # and the file runs in TEST_CMD again. The band-forcing entry left when #78 landed
    # `aeh.judge`: the conjunction over the judge symbols (`ScoringWorker`,
    # `prompt_fields`) and the extract symbols resolved, `test_judge_band_forcing.py`
    # lost its marker and rejoins the integration tier. Its latent `b.band` band read
    # (the catalog's bands are dict rows) was reconciled in the same change.
    # --- TS-65 (#72), the M-EXTRACT contract cases, C01-C15 ---------------------------------
    #
    # Written ahead of #68 like the TS-26 suite above, but keyed per BLOCKER rather than
    # per story: the contract cases are rung-split, and the rung-3 halves wait on their
    # consumers (#73 verification, #74 signals, #78 assembly, #97 rendering), not on #68.
    # A file that mixes blockers lists its rung-2 nodes under the #68 entry and its
    # rung-3 nodes under the consumer entry (node IDs, the calibration precedent), so
    # every entry names exactly the symbols the tests it covers resolve. Each contract
    # case resolves the full surface first (`require_extract_surface` = the
    # `TS26_EXTRACT_SYMBOLS` conjunction), so every conjunction below is that base plus
    # the consumer symbols — built from the vocabulary and the module constants, like
    # the entries above, so the registry cannot name a symbol the tests stopped using.
    # The "#68 extraction contract suite (TS-65)" entry left when #68 landed
    # `aeh.extract`: the rung-2 contract cases (C01-C09, C11-C13, C08) resolved only
    # the `TS26_EXTRACT_SYMBOLS` conjunction, so their markers came off and they
    # rejoin TEST_CMD. The three consumer-keyed entries below left at the #73/#74
    # landing (`aeh.integ`): their markers came off in the same change, and nothing
    # rung-3 remains keyed in this section.
    "#68 extraction contract metrics (TS-65)": (
        # C14, the whole file: the suite's names plus #68's own `extraction_metrics`
        # emitter — the one case that reads the metrics, hence its own conjunction, so
        # the suite entry above never names a symbol its tests do not use.
        "symbols",
        ",".join(f"{EXTRACT_MODULE}:{name}" for name in TS65_EXTRACT_SYMBOLS),
        ("tests/contract/extract/test_ct_extract_c14_extraction_metrics.py",),
    ),
    # The "#69 extraction contract second family (TS-65)" entry stood here: its
    # conjunction resolved with the same landing, and C10 lost its marker in the
    # same change.
    # The "#73 extraction contract sweep (TS-65)", "#74 extraction contract sweep
    # (TS-65)" and "#73+#74+#78+#97 extraction contract sweep (TS-65)" entries stood
    # here: #73 landed `aeh.integ:verify_span` and #74 the gate (`IntegrityGate`,
    # `IntegritySignals`), completing every conjunction the rung-3 nodes resolved —
    # C07's re-derivation, C09's marker routing, C08's blank routing and the whole
    # C15 sweep — so their markers came off and they rejoin TEST_CMD in the same
    # change.
    # --- TS-20 (#54), the M-SETUP Stage A cases that wait on #51/#52/#53 --------------------
    #
    # `aeh.setup` itself landed with #50 (propose, confirm, the two gates, publish), so
    # nothing here is keyed on the module — the files below run against shipped code
    # up to the member each case actually drives. (The #51 readback entry left with
    # #51: the read back, its two constants and the marker went together.) Every entry
    # is keyed on the §3.6
    # Interface members (`read_back_rubric`, `classify_decomposability`,
    # `propose_dependencies`, `set_grade_policy`) and §3.6 Configuration constants
    # (`SETUP_DEFAULT_BAND_COUNT`, `SETUP_MAGNITUDE_PHRASES`, `SETUP_MAX_CONFIRMATIONS`).
    #
    # **Each entry is a `symbols` conjunction covering its file's FULL blocker set**, so no
    # entry can fire while a sibling symbol the same file needs is still missing — the
    # TC-STORE-15 lesson (a conjunction, never a coin flip), applied at file granularity.
    # Per-test granularity was considered and rejected: each file's cases share one story
    # and one blocker set, so a file-level conjunction is both exact and readable.
    #
    # TC-SETUP-09 and -21 are not this issue's cases (a repetition invariant and a UAT
    # measurement). TC-SETUP-11, -12, -14, -16, -17 and -18 are **deferred, not written
    # ahead**: their oracles turn on storage or surfaces the design does not pin — the
    # panel-depth/auto-acceptance columns (11), an `evidence_type` column that does not
    # exist and no interface member carries (12), the prefix token-counting seam (14), an
    # `evaluation_mode` column that does not exist (16), the cross-story skip sweep whose
    # recorded-default storage is unpinned (17), and calibration-paper intake no surface
    # accepts (18). That is the TC-INGEST-38 precedent; disclosed on the #54 PR.
    # The TC-SETUP-12 deferral left with #232: migration 8 added the column, #51 (PR
    # #216) shipped the write half, and #232 the publish refusal — the case runs in
    # `tests/integration/setup/test_tc_setup_12_evidence_type.py`. It was never a
    # `WRITTEN_AHEAD_BLOCKERS` entry (deferred, not written ahead), so nothing was
    # unmarked; the case is listed here only because this note is where the deferral
    # was recorded.
    # "#52 decomposition" and "#52 dependencies" left with #52: the classifier, the cap
    # constant and the proposal surface landed, and #51's read back (PR #216) supplies
    # the criteria half of the dependencies conjunction — both pending files run green,
    # so their markers and these entries are gone.
    # "#53 policy", "#55 setup time budget", and the #56 C01/C07/C09/C10 entries left
    # with #53 (this issue): set_grade_policy/check_prefix_budget and the staging of the
    # deterministic criteria landed — the policy-pending, UAT and contract files run
    # green, so their markers and these entries are gone.
    # "#56 C04 classification" and "#56 C05 panel depth" left with #52: the
    # classifier landed and the file runs green against it (C05's read-back half
    # was already green with #51) — markers and entries gone.
    # "#56 C06 bands" left with #51 (PR #216): the read back and its two constants
    # landed, and the file's descriptor half runs green against them — the rebase
    # check the suite's issue names.
    # "#56 C08 dependencies" left with #52: the proposal surface landed and #51's read
    # back supplies the criteria it attaches to — the file runs green, marker and
    # entry gone.
    # "#56 C13 confirmation cap" left with #52: the classifier and the cap constant
    # landed and the file runs green against them — marker and entry gone.
    # "#56 C15 consumer sweep" left with #137: the last of its conjunction landed (aeh.calib
    # completed `read_back_rubric` + the three consumer modules), and the sweep runs green
    # against all of them — marker and entry gone. Note the entry also exposed a gate defect,
    # fixed here: a bare module path as a `symbols` limb (no `:`) never resolved, because
    # `"".split(".")` is `[""]` and `getattr(module, "")` is None — the conjunction could
    # not have fired its own gate even once every limb landed.
    # --- TS-22 (issue #63), the M-ORCH cases written ahead of their stories ---------------
    #
    # #57 shipped the ledger slice (work units, `compute_work_id`, enumeration), so these
    # are keyed on the *symbols* the later stories owe, not on the module.
    # The #59 entries (TC-ORCH-25, TC-ORCH-06/07/08) were dropped when #59 landed:
    # `SWEEP1_ADMITTED_INGEST_STATUSES` and the two-sweep dispatch order are in.
    # The three #62 entries (TC-ORCH-22, TC-ORCH-23/RES-11/13, TC-ORCH-31) were
    # dropped when #62 landed: `Orchestrator.progress` and `record_run_metrics`
    # shipped as declared.
    # --- TS-24 (issue #65), the resume/lease-expiry/taxonomy cases written ahead -------
    #
    # #57 (argument-free resume) and #58 (lease, sweeper, fail/complete taxonomy) shipped,
    # so the GREEN cases (TC-ORCH-04/18, RES-04/05/12/15) run unmarked. These four entries
    # key the cases the later stories owe, on the §3.7 Protocol members those stories must
    # add to the concrete class.
    # `#97 TS-24 synthesis boundary (RES-07)` — DROPPED at #97's landing: the invented
    # `aeh.synth:synthesize` entry point landed as `synthesize(store, provider,
    # model_ref, run_id, *, submission_id)` and the case is unmarked (the reconciliation
    # is disclosed in the test module's docstring).
    # --- TS-28 (#75), the M-INTEG span-verification and integrity-signal cases ------------
    #
    # M-INTEG is two implementation stories: #73 (`verify_span`, fail-closed) and #74
    # (signals, routing, the restricted write set), and the cases split on that seam.
    #
    # All four entries this section once carried left at the #73/#74 landing:
    # `verify_span` shipped as the invented module-level function (the `#65`
    # `aeh.synth:synthesize` precedent — the rung-0 cases need no construction),
    # `IntegrityGate` landed with the retry ladder, `IntegritySignals` with the
    # routing and the write set, and `ALERT_SPAN_VERIFICATION_FAILURES` as declared —
    # so every TS-28 file is unmarked and nothing is keyed here.
    # --- TS-66 (#77), the fifteen CT-INTEG clause cases ------------------------------------
    #
    # One entry per blocker shape, not per case: the clause cases share the #75-reconciled
    # M-INTEG seam (`verify_span`, `IntegrityGate`, `IntegritySignals`, the alert and rate
    # constants) and the #76-reconciled M-AGG surface (`aggregate`, `AGG_AUTO_THRESHOLD_
    # ATOMIC`), so the conjunctions group by what makes a file runnable. No new M-INTEG
    # name is minted for TS-66 — the two knobs CT-INTEG-13 names (INTEG_OCR_CONF_FLOOR,
    # INTEG_DESCRIBED_EVIDENCE_ROUTES) ride env like the #75 disable switch, and the
    # disclosure tables in the files carry the details. The #73/#74-only entries
    # (C01, C04, C05, C06, C10-C14) left when M-INTEG landed; the entries that remain
    # are exactly the ones whose conjunctions still name the M-AGG surface (#92).
    # The "#92 IntegritySignals+aggregate+threshold (TS-66 C02 None-is-not-False)",
    # "#92 IntegrityGate+IntegritySignals+aggregate (TS-66 C03 fail-closed)", "#74
    # ... (TS-66 C04 write surface)", "#74+#68 both module files (TS-66 C05
    # structural independence)", "#74 IntegrityGate (TS-66 C06 byte-exact
    # rejection, nothing scores)", "#92 gate+signals+aggregate+threshold (TS-66 C07
    # empty evidence routes)", "(TS-66 C08 sufficiency is an extraction problem)"
    # and "(TS-66 C09 OCR intersection and cap)" entries stood here: M-INTEG landed
    # the gate and the signals, #92's landing (merged alongside) supplied
    # `aeh.agg:aggregate` and `AGG_AUTO_THRESHOLD_ATOMIC`, so C02-C09's conjunctions
    # resolved and their files rejoined TEST_CMD in the same change.
    # --- TS-23 (issue #64), the escalation / breaker / random-arm / cost-ceiling cases -----
    #
    # #60's six entries (the breaker, the budget, the plan, the sampler, the enqueue's
    # atomicity and the arm's enumeration mechanism) resolved at that landing — the
    # declared interface names shipped as declared. The estimator is #62's, the policy
    # function itself is M-AGG's (#95), and the cost-ceiling pause is #61's. Every
    # remaining invented name is declared in its test module's docstring with its
    # reconciling story — the `record_run_metrics` precedent: the design pins the
    # semantics and the constants but no function names, so the tests invent and use
    # them together. The #62 entry (TC-ORCH-27) was dropped when #62 landed:
    # `estimated_completion_seconds` shipped as declared. The policy-purity entry
    # (TC-ORCH-32, keyed on `aeh.agg:should_escalate` — the member, not the module)
    # was dropped when #93 landed the function.
    # --- TS-29 (#76), the M-INTEG adversarial forgery cases --------------------------------
    #
    # The "#76 forged evidence (TC-INTEG-13, ADV-01, ADV-03)" entry stood here: a
    # `symbols` conjunction over the file's full blocker set — `verify_span`,
    # `IntegrityGate`, `IntegritySignals` (all M-INTEG's), plus M-AGG's `aggregate`
    # and `AGG_AUTO_THRESHOLD_ATOMIC` (#92). M-INTEG landed the first three, #92's
    # landing (merged alongside) supplied the last two, the conjunction resolved, and
    # the file rejoined TEST_CMD in the same change — its consumer doubles reconciled
    # to the landed M-AGG shape (a verdict carries `.ordinal`, a criterion carries
    # band rows, and the score rows read from the cohort tier where
    # `criterion_score` ships).
    # --- TS-25 (issue #66), dispatch isolation, progress granularity, run metrics ---
    #
    # Two of the eight cases run GREEN against shipped code and carry no marker:
    # TC-ORCH-30 (tests/integration/orch/test_perf_scheduling_overhead.py — the
    # scheduling path #59 shipped holds the budget) and TC-ORCH-33's lease/
    # complete half (tests/integration/orch/test_ledger_capacity.py). Five
    # entries have dropped as their surfaces landed: TC-ORCH-26/24/35 and
    # TC-ORCH-33's progress half at #62 (`Orchestrator.progress`,
    # `ProgressReport` and `record_run_metrics` shipped as declared), and
    # TC-ORCH-19/ADV-04 below. `record_run_metrics` is #65's
    # invented-and-reserved name, claimed by TS-25's own file; the #65 entry
    # above keeps its conjunction for ITS file untouched.
    #
    # The "#66 TS-25 one-submission isolation (TC-ORCH-19, ADV-04)" entry stood
    # here: its conjunction over `Orchestrator.progress` + the M-JUDGE
    # assembler/validator resolved when #62 landed the dispatch's
    # assembled-request seam (`FR-ORCH-20` — what crosses the call seam is the
    # stage's closed request, never the ledger row, so the corpus half captures
    # `ScoringRequest`/`ExtractionRequest`) and #80/#81 landed
    # `ScoringWorker.assemble` and `assert_isolated`;
    # `test_one_submission_per_request.py` lost its marker and rejoined the
    # integration tier.
    "#66 TS-25 alert rules (TC-ORCH-36)": (
        # The five OBS-05 conditions are design text with no pinned surface;
        # `evaluate_alerts` is invented-and-disclosed (the `aeh.synth:-
        # synthesize` / `ALERT_SPAN_VERIFICATION_FAILURES` precedent) — if the
        # observability story ships another name, the rename here and in the
        # test module is one line.
        "symbol",
        f"{ORCH_MODULE}:evaluate_alerts",
        ("tests/integration/orch/test_alert_rules.py",),
    ),
    # --- TS-30 (#82), the M-JUDGE judgment-isolation suite -----------------------------------
    #
    # Two files, one per owning story of the surface they resolve. The isolation
    # file is pure rung 0 and waited on #78's worker/request pair; the numeral file
    # renders through #78's worker AND #79's version-pinned template, so its key is
    # a conjunction over both stories' symbols (the "#71" precedent: the render
    # alone does not make the case runnable). The symbol tuples live in
    # `tests/support/judge_vocabulary.py` — the single bet the two suites share;
    # that module imports nothing from here, so the key import is acyclic.
    #
    # The "#78 scoring isolation (TS-30)" entry stood here: its conjunction over
    # `TS30_JUDGE_SYMBOLS` resolved when #78 landed `aeh.judge`, and
    # `test_scoring_isolation.py` lost its marker and rejoined the fast tier. The
    # vocabulary's `TS30_JUDGE_SYMBOLS` tuple stays in `judge_vocabulary.py` — the
    # "#79" entry's conjunction below was built from the sibling tuple, and the
    # shared bet is the two suites'.
    #
    # The "#79 judge prompt (TS-30)" entry stood here: its conjunction over
    # `TS30_PROMPT_SYMBOLS` (plus the extract leg the numeral file's world runs)
    # resolved when #79 landed `JUDGE_PROMPT_TEMPLATE_V` and the template it pins,
    # and `test_no_numerals_in_judge_prompt.py` lost its marker and rejoined the
    # fast tier. The vocabulary's `TS30_PROMPT_SYMBOLS` tuple stays in
    # `judge_vocabulary.py` — the settled bet is the suites' record of what they
    # resolve, even with no registry entry left to build from it.
    # --- TS-37 (issue #99), the M-SYNTH two-level synthesis and score-claim cases -----
    #
    # The design declares no M-SYNTH Protocol (grep of detailed-design.md for an
    # Interfaces block returns nothing), so every key was an
    # invented-and-disclosed name — settled in `tests/support/synth_vocabulary.py`
    # (the extract_vocabulary precedent), one rename there per reconciled symbol.
    # Ownership followed the stories' acceptance criteria: #97 shipped the two-level
    # boundary, the request types, the completeness gate, the narrative schema and
    # the report; #98 shipped the score-claim prohibition (the check and the
    # configured pattern list) and the evidence anchoring. The "#97" entries were
    # DROPPED at #97's landing; the "#98 score-claim check (TC-SYNTH-04)",
    # "#97+#98 stored narratives (TC-SYNTH-05/06)" and "#98 ADV-11 attack (ADV-11)"
    # entries stood here until #98 landed `has_score_claim` and
    # `SYNTH_SCORE_CLAIM_PATTERNS` — their three files unmarked and rejoined the
    # gate green on the landed surface (the TC-SYNTH-11 purge case never carried a
    # marker: its worker-half resolved at #97).
    # --- TS-39 (#106), the M-GRADE revisions/amendment/rollup/export suite -------------------
    #
    # Five files, five entries (the observability pair below is one conjunction entry, not
    # two, for the reason its comment gives). Every key is an **invented-and-disclosed**
    # name — the `aeh.orch:evaluate_alerts` / `export_grade_artifacts` precedent: a name
    # neither design document declares (checked: zero occurrences in both), that the test
    # calls and the landing reconciles; a different name at the landing is one rename here
    # and in the test module.
    #
    # Why not the obvious names: `ClassRollup`, `rollup`, `criterion_stats` and
    # `GradingService.export` are §3.14-declared Protocol surface, and `class_rollup` /
    # `export` already SHIPPED with #101 — keying on a landed name fires this gate
    # immediately (the resolved-`"#2"`/`"#37"` doctrine), and keying on a Protocol name
    # resolves the gate against exactly the un-separated, findings-less, figures-less
    # shapes the cases exist to refuse. Why not `criterion_figures`: #118/M-STATS already
    # reserves that name for its analytical read (its entry above); M-GRADE's producer is
    # a different surface from M-STATS's analytical export (`CT-GRADE-13` names the
    # consumer obligation the other way), so `criterion_band_figures` is the producer's
    # own bet. The #101 carry-forwards this suite owns are keyed nowhere on purpose —
    # amendment-replay idempotence is GREEN against shipped code
    # (`tests/integration/grade/test_recompute_idempotence.py`), and scaled-interval
    # composition is disclosed in the PR, not a case in the table.
    # The three `"#104 ..."` entries that stood here (TC-GRADE-14/15/16) are gone:
    # #104 landed `criterion_band_figures`, `separated_rollup` and `rollup_findings`
    # in the same PR that unmarked their cases. #103's two entries (TC-GRADE-23,
    # TC-GRADE-24) are gone the same way: #103 landed `enforce_ledger_append_only`
    # and the `record_grade_signals`/`evaluate_grade_alerts` conjunction, and both
    # files unmarked and rejoined the gate green.
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
        # A bare module path (no `:`) is a legal limb inside a `symbols` conjunction —
        # the #56 C15 sweep conjoined three consumer MODULES with #51's read-back
        # symbol. An empty `dotted` must read as "the module landed": `"".split(".")`
        # is `[""]`, and `getattr(module, "")` is None, which made such a limb read
        # unresolved forever — the silent direction this registry exists to prevent.
        for attribute in (dotted.split(".") if dotted else ()):
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
