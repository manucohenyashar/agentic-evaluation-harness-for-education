"""The vocabulary `M-REVIEW`'s clause suite is written against, transcribed from the design.

TS-72 (issue #114) implements twenty `CT-REVIEW` clause cases against a module that does not
exist: `M-REVIEW` is four stories away (#108 → #109/#110/#111) and every one of those is
itself blocked. A suite that sits red across a phase drifts, and what drifts first is its
vocabulary — the nine label fields, the two sample ranges, the four knobs, the three
populations that are never rendered.

So the vocabulary lives here as **literals transcribed from design §3.15**, and
`tests/contract/review/test_ct_review_vocabulary.py` asserts every one of them against the
design document itself. Those assertions are green today and they are worth being precise
about: they test that *this fixture still matches the design*, not that `M-REVIEW` does
anything. Nobody should count them as coverage of a clause. What they buy is drift detection
— when §3.15 moves, the suite goes red at the transcription rather than quietly encoding a
contract nobody agreed to.

§3.15 **does** carry a Python Interfaces block, so `ReviewService`'s six members,
`ReviewQueue`'s five fields and `ReviewItem`'s wire shape are transcribed rather than
invented. The additions the clauses force but the block does not declare are listed here, in
one place, so an invented name is visibly invented:

**#108 — S-REVIEW-01, the queue itself**

    build_review(scores=..., **kw) -> ReviewService   the in-memory rung-0/1 constructor
    open_review(data_dir=..., run_id=...)             the rung-2 constructor
    .rank_queue_items(run_id=...)                     FR-REVIEW-03's ranking, separable;
                                                      entries carry .score_id, .expected_value
    .group_signature(row) -> Sequence[str]            CT-REVIEW-20's exact grouping rule
    .points_for_band(...)                             CT-PKG-05's mapping, reached from here
    .escalate(score_id)                               CT-REVIEW-15's induced race
    ReviewQueue.groups                                the group entries, separable from .shown
    ReviewQueue.build_seconds                         CT-REVIEW-16's budget accounting
    ReviewGroup.members                               so "one label per member" is countable
    ReviewItem.score_id / .criterion_id /
        .submission_id / .version                     identity, for differentials and staleness

**#109 — S-REVIEW-02, the prohibitions and the residual**

    .admission_query() -> QueryPlan                   CT-REVIEW-05's reachability; carries
                                                      .routing_values, .excluded_origins,
                                                      .evaluation_modes
    .write_audit()                                    CT-REVIEW-06's indirection; .table per write
    .write_fields() -> Sequence[str]                  CT-REVIEW-14's write set
    .scores(run_id=...)                               reading score rows back, for the residual
    .end_session(run_id=...) / .close_run(run_id=...) the two moments a residual can vanish

**#110 — S-REVIEW-03, the label store**

    .record_label(...)                                CT-REVIEW-07's collection path
    .labels_for(run_id=...) / .label(label_id)        reading the label store back
    .act_from_view(item, view=..., ...)               FR-REVIEW-15's outside-the-queue edit
    .edit_views()                                     CT-REVIEW-12's per-view sweep
    .observability_counters(run_id=...) / .alerts()   CT-REVIEW-18; alerts carry .name and
                                                      .consecutive_administrations
    .counter_emissions(run_id=...)                    CT-REVIEW-18's pairing; .at and .names
    .exhaust_budget_on(criterion_id=..., ...)         the alert's precondition
    Label.review_queue_action / .criterion_id         parity across edit paths

**#111 — S-REVIEW-04, the two samples**

    ReviewQueue.build_trace                           CT-REVIEW-02's event order; .name per
                                                      event. #111's, not #108's: S-REVIEW-04
                                                      owns the budget subtraction the trace
                                                      has to show happening first
    BlindSession.readable_tables()                    CT-REVIEW-09 — see the note below
    BlindSession.available_data() / .items            CT-REVIEW-09 step 2, and the refs to answer
    .render_blind_flow(session_id)                    the rendered half of step 2
    .submit_blind(..., interrupted=True)              CT-REVIEW-15's partial session
    .skip_blind_sample(run_id=...)                    CT-REVIEW-10's precondition
    .blind_sample_skipped(run_id=...)                 CT-REVIEW-10's reported absence; carries
                                                      .reported, .message, .current_figure
    SubmissionGrade.rendered_as_student_sees_it       FR-REVIEW-14's "as the student would"

Consumer-side names, in the same spirit — each keyed on the story that delivers it:

    aeh.console  render_review_queue (#124), blind_flow_requests (#124 — CT-REVIEW-09 step 3's
                 transport probe; requests carry .path and .body)
    aeh.stats    build_stats (#115) and the figure's .computed_over, .input_fields,
                 .excluded_count, .interval_low/.interval_high (#115)
    aeh.judge    prompt_fields, assemble_prompt(..., rerun=True) (#77)
    aeh.extract  prompt_fields (#68)

**`BlindSession.readable_tables()` is the one invented name that carries weight.** §3.15's
Compatibility paragraph mandates the assertion — *"the required negative test is that a blind
session's query plan **cannot** reach `criterion_score`, which is asserted against the query,
not the rendering"* — while the Interfaces block declares nothing that exposes a query. A
source-level scan is the tempting substitute and it is a **weaker claim**: it asserts that no
code in `aeh/review/` names the table, which a module reaching it through a store helper or a
view satisfies while violating the clause. So the runtime member is invented here and the
static scan is kept as an *additional* assertion rather than the primary one. Reported as a
finding on the PR.

Every constant below carries the clause or requirement it came from, so the transcription is
checkable by reading rather than by trusting.
"""

from __future__ import annotations

import ast
import re
from typing import Iterable

# --- §3.15 Interfaces: what the design itself declares ------------------------------------

#: `ReviewService`'s members, transcribed from §3.15's Interfaces block in declaration order.
#: These are the names a story cannot rename without the design changing first.
SERVICE_MEMBERS: tuple[str, ...] = (
    "build_queue",
    "act",
    "act_on_group",
    "blind_sample",
    "submit_blind",
    "whole_grade_sample",
)

#: `ReviewQueue`'s five fields, transcribed from the same block. `CT-REVIEW-04` names three of
#: them as the residual triple; the other two are the budget and its blind reservation.
REVIEW_QUEUE_FIELDS: tuple[str, ...] = (
    "budget_minutes",
    "reserved_for_blind_minutes",
    "flagged_total",
    "shown",
    "residual_provisional",
)

#: `CT-REVIEW-04`'s subject: *"items flagged, items shown, items left provisional"*. All three
#: are rendered or the clause is broken — showing only what fits is the dishonesty it prevents.
RESIDUAL_TRIPLE: tuple[str, ...] = ("flagged_total", "shown", "residual_provisional")

#: `ReviewItem`'s wire shape, from §3.15's prose paragraph under the Interfaces block. Prose
#: rather than a dataclass, so this transcription is the only place the field list is written
#: down; the vocabulary test asserts each name appears in that paragraph.
REVIEW_ITEM_FIELDS: tuple[str, ...] = (
    "proposed_band",
    "band_options",
    "proposed_points",
    "max_points",
    "narrative",
    "evidence_spans",
    "reason",
    "est_seconds",
    "package_version_id",
    "grade_boundary_delta",
)

#: `proposed_points` and `max_points` are *"shown to the teacher, never to a judge"* (§3.15).
#: `CT-REVIEW-14`'s empty-intersection assertion is what enforces the second half.
TEACHER_ONLY_ITEM_FIELDS: tuple[str, ...] = ("proposed_points", "max_points")

#: `act`'s action domain, from the Interfaces block's `Literal`. Note `skip` is an action but
#: **not** a label type — a skipped item stays residual, which is `CT-REVIEW-06`'s subject.
ACTIONS: tuple[str, ...] = ("accept", "edit", "override", "skip")

#: `FR-REVIEW-09` / `CT-REVIEW-07`'s `label_type` domain. Four, and `blind` is the one that
#: does not come from the queue at all.
LABEL_TYPES: tuple[str, ...] = ("accept", "edit", "override", "blind")


# --- CT-REVIEW-07 / FR-REVIEW-09: what a label carries ------------------------------------

#: The fields `FR-REVIEW-09` names, in the order it names them.
#:
#: **The requirement names eight, and the test plan's `TC-REVIEW-C07` row says "all nine named
#: fields".** Counted from the requirement text — `label_type`, `saw_system_output`, `routing`,
#: `origin`, `evaluation_mode`, `review_seconds`, `system_band`, `teacher_band` — it is eight.
#: The transcription follows the design, the vocabulary test asserts the count against the
#: requirement's own text, and the discrepancy is reported as a finding rather than resolved by
#: inventing a ninth.
LABEL_FIELDS: tuple[str, ...] = (
    "label_type",
    "saw_system_output",
    "routing",
    "origin",
    "evaluation_mode",
    "review_seconds",
    "system_band",
    "teacher_band",
)

#: What the test plan's row claims. Kept as a literal so the finding is asserted rather than
#: described — the day somebody adds a ninth field to `FR-REVIEW-09`, the vocabulary test that
#: reports this mismatch goes green and the finding retires itself.
LABEL_FIELD_COUNT_CLAIMED_BY_PLAN = 9

#: `NFR-REVIEW-03`: *"Every label shall be attributable to an actor and a timestamp"*. Separate
#: from `LABEL_FIELDS` because it comes from a different requirement — folding them together
#: would make the count assertion above untestable.
LABEL_ATTRIBUTION_FIELDS: tuple[str, ...] = ("actor", "timestamp")

#: What a label may **not** also carry. `CT-REVIEW-07` is asserted by set equality, and the
#: direction a presence check misses is the extra field: each of these is the system's own output
#: denormalized onto the record that is supposed to be an independent judgement of it. A label
#: carrying `confidence` beside `system_band` is one join short of an agreement statistic that
#: weights by the system's own certainty.
#:
#: `system_band` is deliberately absent — `FR-REVIEW-09` requires it, and the pair is the whole
#: point of the record. What is forbidden is everything *derived* from the score.
FORBIDDEN_LABEL_FIELDS: tuple[str, ...] = (
    "confidence",
    "self_confidence",
    "proposed_points",
    "system_points",
    "routing_reason",
    "narrative",
    "panel_spread",
)

#: `CT-REVIEW-07`: *"both `system_band` and `teacher_band`"* — a label with only one is useless
#: for agreement, which is the whole reason the label store exists.
AGREEMENT_BAND_PAIR: tuple[str, ...] = ("system_band", "teacher_band")

#: `CT-REVIEW-07`: *"Agreement is computed over bands, never points."* Any of these appearing as
#: the agreement input is the violation.
POINTS_FIELD_NAMES: tuple[str, ...] = (
    "points",
    "proposed_points",
    "new_points",
    "score",
    "scaled_score",
)


# --- CT-REVIEW-08: the field the validity argument rests on -------------------------------

#: The column `M-STATS` filters from. `FR-STATS-01` enforces admissibility *from this column*,
#: not from a naming convention or a table split — which is why the value has to be right on
#: every collection path rather than merely present.
ADMISSIBILITY_COLUMN = "saw_system_output"

#: The value each collection path must write, from `TC-REVIEW-C08` step 2. The sweep is the
#: point: the failure mode is **one path defaulting wrongly**, not the field being absent.
SAW_SYSTEM_OUTPUT_BY_PATH: dict[str, int] = {
    # a queue action — the teacher was looking at the system's band when they acted
    "queue_action": 1,
    # the blind flow — CT-REVIEW-09 makes the output unreachable, so this 0 is earned
    "blind_flow": 0,
    # FR-REVIEW-15's edit from any other view showing a band: still saw it
    "other_view_edit": 1,
    # a group action is N queue actions (CT-REVIEW-13), so it carries the queue value
    "group_action": 1,
}

#: `TC-REVIEW-C08`'s adversarial construction, transcribed so the test asserts the *stated*
#: one rather than an easier one: set `saw_system_output = 0` for queue actions where the
#: teacher **overrode** the system, reasoning that an override shows independent judgment.
#: κ rises, the validity claim strengthens, and the figure is built on labels anchored by the
#: very output they are supposed to validate.
ADVERSARIAL_OVERRIDE_LABEL_TYPE = "override"


# --- CT-REVIEW-09: unreachable, not hidden ------------------------------------------------

#: §3.15's Data flow paragraph: *"The blind session is a separate flow reading `submission` and
#: `criterion` only — it deliberately cannot join to `criterion_score`."*
BLIND_READABLE_TABLES: frozenset[str] = frozenset({"submission", "criterion"})

#: The table the blind session must not reach. Named separately because `CT-REVIEW-09`'s
#: assertion is about this one join, not about tables in general.
BLIND_FORBIDDEN_TABLE = "criterion_score"

#: `FR-REVIEW-11`'s five absences, swept individually. Five separate assertions rather than one
#: "no system output" check, because the plausible defect is one of the five surviving a
#: refactor — and a single combined assertion names none of them when it fails.
BLIND_FORBIDDEN_FIELDS: tuple[str, ...] = (
    "system_band",
    "points",
    "narrative",
    "confidence",
    "routing_reason",
)

#: `TC-REVIEW-C09`'s adversarial construction: prefetch the score row into the blind session
#: *"to make submission instant"*, rendering nothing. Nothing is displayed, the flow looks
#: identical, and the guarantee has degraded from **unreachable** to **hidden** — one template
#: change away from visible. The clause is worded as reachability to make this fail.
BLIND_PREFETCH_ATTRIBUTES: tuple[str, ...] = (
    "prefetched_score",
    "score_row",
    "criterion_score",
    "_scores",
    "cached_score",
)


# --- CT-REVIEW-01 / -03: budget, ranking, and what may not drive it -----------------------

#: `FR-REVIEW-01`: the queue is sized by a minute budget and **never** by these two.
FORBIDDEN_SIZING_RULES: tuple[str, ...] = ("fixed_percentage", "bare_confidence_threshold")

#: Names a percentage-sized queue would plausibly carry. `CT-REVIEW-01` is a surface clause, so
#: the presence of one of these on the queue is itself the violation.
PERCENTAGE_SIZING_NAMES: tuple[str, ...] = (
    "percent",
    "pct",
    "proportion",
    "fraction",
    "top_n",
    "quota",
)

#: `FR-REVIEW-03`'s P(error) inputs, all four. The case varies each **alone** and asserts the
#: order responds, so a ranking that reads three of them fails naming the fourth.
ERROR_PROBABILITY_SIGNALS: tuple[str, ...] = (
    "panel_spread",
    "adverse_integrity_signals",
    "transcription_overlap",
    "historical_override_rate",
)

#: `FR-REVIEW-03`'s impact term: *"the criterion's share of the final grade with proximity to a
#: grade boundary"*.
#:
#: Both are field names this suite invents for a term the requirement writes in prose, so each is
#: mapped to the phrase it came from — otherwise the transcription check has nothing to compare
#: against and would have to be dropped, which is how an invented name stops being visibly
#: invented. `grade_boundary_delta` is `ReviewItem`'s own field (§3.15's prose paragraph);
#: `criterion_weight` is `M-GRADE`'s, relied on through `CT-GRADE-19`.
IMPACT_SIGNALS: dict[str, str] = {
    "criterion_weight": "share of the final grade",
    "grade_boundary_delta": "proximity to a grade boundary",
}

#: The prohibition, from the same requirement: *"not self-reported confidence alone"*. Held
#: fixed on the observables and swept, the order must not move.
SELF_REPORTED_CONFIDENCE_FIELD = "self_confidence"

#: `FR-REVIEW-03`'s formula, as its three factors. Transcribed so `TC-REVIEW-C03` asserts the
#: shape — expected value **per second** — rather than merely that ranking is monotonic in
#: something.
EXPECTED_VALUE_FACTORS: tuple[str, ...] = ("p_error", "impact", "est_seconds")

#: `NFR-REVIEW-05` / `CT-REVIEW-01`'s honest-degradation budget. Five minutes is the plan's own
#: figure: *"at 5 minutes assert fewer items and a larger stated residual"*.
DEGRADED_BUDGET_MINUTES = 5


# --- CT-REVIEW-05: the three populations, and the deterministic criteria ------------------

#: `FR-REVIEW-07`'s three, plus `FR-REVIEW-06`'s fourth. Kept as one tuple because the clause
#: states them as one prohibition, and as named strings because the assertion is a reachability
#: sweep — each must be shown absent by name when it fails.
NEVER_RENDERED_POPULATIONS: tuple[str, ...] = (
    "quarantine",
    "blind_sample",
    "random_arm",
    "deterministic_criterion",
)

#: `CT-REVIEW-05`'s own gloss, asserted directly: the random arm *"spends compute, never teacher
#: minutes, and produces no review item"*. Exactly zero, not "few".
RANDOM_ARM_REVIEW_ITEMS = 0

#: `CT-AGG-15`/`CT-ORCH-15`'s column that keeps the random arm statistically separable. If
#: random-arm units entered the queue they would stop being an independent sample, taking
#: RISK-07's only unbiased comparison with them.
RANDOM_ARM_ORIGIN = "random_arm"

#: `CT-AGG-06`: the queue's population is `routing = 'queued'`; `triage` is the operator's.
QUEUE_ROUTING = "queued"
OPERATOR_ROUTING = "triage"

#: `CT-DET-06`: the column that makes the deterministic exclusion enforceable *from the data*
#: rather than by convention.
EVALUATION_MODE_FIELD = "evaluation_mode"
JUDGED_EVALUATION_MODE = "judged"
DETERMINISTIC_EVALUATION_MODE = "deterministic"


# --- CT-REVIEW-06: what review writes, and what it never writes ---------------------------

#: `CT-REVIEW-06`: review actions write these, and reduce `criteria_provisional` **through**
#: `criterion_score` — the indirection is the assertion, since this module never writes a grade.
PERMITTED_WRITE_TABLES: tuple[str, ...] = ("review_queue", "label", "audit_record")

#: The table the reduction goes through. Named separately: a write straight to the grade row
#: would satisfy "the provisional count went down" and violate the clause.
PROVISIONAL_INDIRECTION_TABLE = "criterion_score"

#: What this module never writes. `M-GRADE` owns these; a review action that touched one would
#: make review a grading surface, which is the boundary `CT-REVIEW-06` draws.
FORBIDDEN_WRITE_TABLES: tuple[str, ...] = (
    "submission_grade",
    "class_rollup",
    "grade_boundary",
    "criterion",
    "package_version",
)

#: `FR-REVIEW-08`'s residual state, and its three properties as separate assertions.
RESIDUAL_STATE = "provisional_unreviewed"

#: The two ways a residual silently stops being one. Both are `FR-REVIEW-08` prohibitions and
#: both are plausible: the per-sitting clear is the likelier, and it would erase the residual
#: the system promised to report.
RESIDUAL_VIOLATIONS: tuple[str, ...] = ("cleared_per_session", "silently_finalized")


# --- CT-REVIEW-11: the two samples --------------------------------------------------------

#: `FR-REVIEW-12`: 15–25 submissions at random, judged criteria only. Inclusive at both ends.
BLIND_SAMPLE_RANGE: tuple[int, int] = (15, 25)

#: `FR-REVIEW-14`: 10–15 complete final grades, from the auto-accepted population.
WHOLE_GRADE_SAMPLE_RANGE: tuple[int, int] = (10, 15)

#: The population the whole-grade sample draws from, and the one it must not. *"Sampling
#: reviewed grades would measure the review, not the system"* — so this is the clause's point,
#: not an aside, and it gets its own assertion.
WHOLE_GRADE_POPULATION = "auto_accepted"
WHOLE_GRADE_FORBIDDEN_POPULATION = "reviewed"

#: `TC-REVIEW-C11`: *"Assert randomness is genuine (seeded, uniform over the eligible set)
#: rather than first-N."* The number of draws the distribution check makes.
RANDOMNESS_TRIALS = 200


# --- CT-REVIEW-10: skipping the sample has exactly one consequence ------------------------

#: The one consequence, transcribed from `FR-REVIEW-13`.
SKIP_CONSEQUENCE = "no new validation evidence for this administration"

#: The same consequence as the words a report has to contain, because §3.15 fixes the
#: *consequence* and fixes no wording for reporting it. Pinning the sentence would fail a
#: compliant console over a synonym; requiring these four words fails a report that says
#: something else. Review caught the string-equality gate.
SKIP_CONSEQUENCE_TERMS: tuple[str, ...] = ("no", "validation evidence", "administration")

#: What must be **unaffected** — the "exactly one" half. Asserted as everything-else-normal
#: rather than as the absence alone.
UNAFFECTED_BY_SKIP: tuple[str, ...] = ("grades_delivered", "grades_finalized")

#: The discriminating negative: an administration that skips while a *previous* administration's
#: figure exists. The earlier figure must not be presented as current — that silent carry-forward
#: is RISK-08 arriving through the back door.
CARRY_FORWARD_FORBIDDEN = True


# --- CT-REVIEW-12: edits are bands -------------------------------------------------------

#: `FR-REVIEW-10`: the module exposes **no** interface accepting a numeric score. Parameter names
#: a numeric-entry surface would plausibly carry.
NUMERIC_ENTRY_PARAMETER_NAMES: tuple[str, ...] = (
    "new_points",
    "points",
    "score",
    "new_score",
    "mark",
    "marks",
    "percentage",
)

#: The one derived field, and what it derives from. `CT-PKG-05`'s pinned mapping is the single
#: place the conversion happens.
DERIVED_POINTS_FIELD = "new_points"
BAND_SELECTION_FIELD = "new_band"

#: `FR-REVIEW-15`: review actions are available *"from any view that displays a band"*, and an
#: edit made outside the queue writes the **same** `review_queue` action and the **same** label
#: type. The sweep is per view; an edit path that skips label creation silently removes data
#: from the validity argument.
EDIT_VIEW_PARITY_FIELDS: tuple[str, ...] = ("review_queue_action", "label_type")


# --- CT-REVIEW-13: a group action is N individual actions ---------------------------------

#: `FR-REVIEW-05` / `CT-REVIEW-13`: one label **per member**, so a group action is statistically
#: indistinguishable from N individual actions in the label store. A single group label would
#: silently under-weight bulk decisions in every agreement figure.
GROUP_LABELS_PER_MEMBER = 1

#: The fields that must match between a group-produced label and an individually-produced one
#: for "indistinguishable" to mean anything. `review_seconds` is excluded deliberately: a group
#: action genuinely took less time per member and the label records that honestly.
GROUP_INDISTINGUISHABILITY_FIELDS: tuple[str, ...] = (
    "label_type",
    "saw_system_output",
    "routing",
    "origin",
    "evaluation_mode",
    "system_band",
    "teacher_band",
)

#: `FR-REVIEW-05`: group items rank **above** per-item entries whenever a group exists.
GROUP_RANKS_ABOVE_ITEMS = True


# --- CT-REVIEW-20: what grouping actually is at Phase 1 -----------------------------------

#: §3.15's open question resolved for Phase 1: *"exact band-plus-integrity-signature grouping,
#: which is weaker but needs no model"*. The signature's components — two items differing in
#: **any** of these are not grouped, even when semantically identical.
GROUP_SIGNATURE_COMPONENTS: tuple[str, ...] = (
    "proposed_band",
    "spans_verified",
    "evidence_present",
    "sufficiency_flag",
    "ocr_overlap_risk",
)

#: `CT-REVIEW-20`'s consumer obligation: `M-CONSOLE` must not describe a group as semantically
#: clustered. The risk is a teacher applying one band to a group they believe is homogeneous
#: when it is only signature-identical — a bulk action taken on a false premise.
SEMANTIC_CLUSTERING_PHRASES: tuple[str, ...] = (
    "similar",
    "semantically",
    "same pattern",
    "alike",
    "cluster",
    "clustered",
    "equivalent",
    "comparable",
)


# --- CT-REVIEW-14: nothing a teacher records reaches a later judgment ----------------------

#: `FR-REVIEW-17`: the module writes no field that any scoring prompt reads, and exposes no
#: per-student annotation surface. The intersection with the prompt-field set must be empty —
#: which is stronger than sampling prompts, because it holds for prompts nobody wrote yet.
ANNOTATION_SURFACE_NAMES: tuple[str, ...] = (
    "annotate",
    "annotation",
    "note",
    "notes",
    "comment",
    "remark",
    "tag_student",
)

#: The two modules whose prompt assembly the write set is intersected against.
SCORING_PROMPT_MODULES: tuple[str, ...] = ("judge", "extract")


# --- CT-REVIEW-16 / -17 / -18: perf, knobs, counters --------------------------------------

#: `NFR-REVIEW-01`'s threshold and its stated load.
QUEUE_BUILD_SECONDS = 2.0
PERF_STUDENTS = 350
PERF_FLAGGED_ITEMS = 800

#: §3.15's Configuration line, all four with their declared Assumption values.
CONFIG_DEFAULTS: dict[str, int] = {
    "REVIEW_BLIND_RESERVE_MINUTES": 10,
    "REVIEW_BLIND_N": 15,
    "REVIEW_WHOLE_GRADE_N": 12,
    "REVIEW_DEFAULT_BUDGET_MINUTES": 30,
}

#: `CT-REVIEW-17`'s framing, which is the assertion that matters: all four *"change how much
#: validation evidence an administration produces, so they are `M-STATS`'s inputs as much as
#: this module's settings"*. Measured as label counts, never as a settings read.
KNOBS_MEASURED_AS = "label_count"

#: §3.15's Observability line. `review_items_shown` and `review_items_flagged` are a **pair** —
#: the R12 honesty check — and either alone is uninformative, so they are asserted together.
OBSERVABILITY_COUNTERS: tuple[str, ...] = (
    "review_minutes_used",
    "review_items_shown",
    "review_items_flagged",
    "override_rate_by_criterion",
    "group_action_usage_share",
    "blind_completion_rate",
    "mean_review_seconds",
    "mean_est_seconds",
)

#: The pair that must travel together.
HONESTY_CHECK_PAIR: tuple[str, ...] = ("review_items_shown", "review_items_flagged")

#: §3.15's Alert: a criterion exhausting the budget across **consecutive** administrations,
#: surfaced as a *pattern* rather than absorbed each term. So the signal is retained across
#: administrations rather than reset — which is what "absorbed each term" describes.
BUDGET_EXHAUSTION_ALERT = "criterion_exhausts_budget_across_administrations"
ALERT_MIN_CONSECUTIVE_ADMINISTRATIONS = 2


# --- CT-REVIEW-19: the non-promise about est_seconds --------------------------------------

#: `FR-REVIEW-16` is **Phase 2**. At Phase 1 `est_seconds` is uncalibrated, and the consumer
#: obligation is that the budget is not presented as a guarantee of elapsed time.
EST_SECONDS_CALIBRATION_PHASE = 2

#: The factor `TC-REVIEW-C19` distorts estimates by. Large enough that a queue silently relying
#: on the estimate being roughly right would visibly break.
EST_SECONDS_DISTORTION_FACTOR = 20

#: Language a console must not use about the budget. `CT-REVIEW-19`: *"a consumer must not
#: present the budget as a guarantee of elapsed time"*.
BUDGET_GUARANTEE_PHRASES: tuple[str, ...] = (
    "will take",
    "takes exactly",
    "guaranteed",
    "guarantee",
    "exactly 30 minutes",
    "you will finish",
    "no longer than",
)

#: The two fields `CT-REVIEW-18` records that make Phase 2 calibration possible from stored data.
#: Asserted so the non-promise names its own way out rather than just its limitation.
CALIBRATION_INPUTS: tuple[str, ...] = ("review_seconds", "est_seconds")


# --- detection rules, each controlled in both directions ----------------------------------
#
# Every rule below is exercised twice in `test_ct_review_vocabulary.py`: once on copy a correct
# implementation would plausibly render or declare, and once on copy the clause forbids. A rule
# that fails correct copy is a rule the first person to hit it switches off.


def _function_nodes(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every function and method in one parse, so `id()` comparisons stay within one AST."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    """The `id()` of every docstring constant, so prose is excluded from source rules.

    A module docstring that *describes* the prohibition — which every module in this repo has —
    would otherwise trip every rule that scans for a forbidden name.
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            ids.add(id(body[0].value))
    return ids


def numeric_entry_parameters(source: str) -> list[str]:
    """`CT-REVIEW-12` — every public parameter that would accept a numeric score.

    Returns `"function:parameter"` for each hit. Parses rather than greps: a numeric parameter
    added to a keyword-only tail, or one carrying a type annotation that spans lines, is
    invisible to a line scan and is exactly the shape a later edit takes.

    `new_points` is flagged **as a parameter** and permitted **as a return or attribute** —
    `FR-REVIEW-10` derives it from `new_band` rather than accepting it, so the direction is the
    whole distinction.
    """
    tree = ast.parse(source)
    hits: list[str] = []
    for func in _function_nodes(tree):
        if func.name.startswith("_"):
            continue
        args = func.args
        every = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        if args.vararg is not None:
            every.append(args.vararg)
        if args.kwarg is not None:
            every.append(args.kwarg)
        for arg in every:
            if arg.arg in NUMERIC_ENTRY_PARAMETER_NAMES:
                hits.append(f"{func.name}:{arg.arg}")
    return sorted(hits)


def annotation_surface_members(names: Iterable[str]) -> list[str]:
    """`CT-REVIEW-14` — public names that would be a per-student annotation surface.

    Substring rather than exact match, because the surface arrives named for its screen
    (`annotate_submission`, `student_note`) rather than for the prohibition.
    """
    hits = []
    for name in names:
        if name.startswith("_"):
            continue
        lowered = name.lower()
        if any(term in lowered for term in ANNOTATION_SURFACE_NAMES):
            hits.append(name)
    return sorted(hits)


def percentage_sizing_surface(names: Iterable[str]) -> list[str]:
    """`CT-REVIEW-01` — names suggesting the queue is sized by a proportion rather than minutes.

    `top_n` is in the list and `n` is not: `blind_sample(n=15)` is the design's own signature,
    and a rule that flagged a bare `n` would fail correct copy on its first run.
    """
    hits = []
    for name in names:
        if name.startswith("_"):
            continue
        lowered = name.lower()
        if any(term in lowered for term in PERCENTAGE_SIZING_NAMES):
            hits.append(name)
    return sorted(hits)


_WORD = re.compile(r"[a-z][a-z_]*")


def semantic_clustering_language(rendering: str) -> list[str]:
    """`CT-REVIEW-20` — phrases describing a group as semantically clustered.

    Two-part, because a single substring scan is wrong in both directions here. `"similar"`
    matches inside `"dissimilar"`, and `"same pattern"` is a phrase rather than a word — so
    words are matched whole and multi-word phrases are matched as substrings.

    A rendering that says *"grouped by identical band and integrity signature"* is the correct
    copy and must pass; one that says *"210 similar responses"* is the violation.
    """
    lowered = rendering.lower()
    words = set(_WORD.findall(lowered))
    hits = []
    for phrase in SEMANTIC_CLUSTERING_PHRASES:
        if " " in phrase:
            if phrase in lowered:
                hits.append(phrase)
        elif phrase in words:
            hits.append(phrase)
    return sorted(hits)


def budget_guarantee_language(rendering: str) -> list[str]:
    """`CT-REVIEW-19` — language presenting the minute budget as a guarantee of elapsed time.

    Substring throughout: every phrase here is multi-word or unambiguous, and the correct copy
    the rule must pass — *"a 30-minute budget, estimated"* — contains none of them.
    """
    lowered = rendering.lower()
    return sorted(phrase for phrase in BUDGET_GUARANTEE_PHRASES if phrase in lowered)


def unstated_residual(rendering: str, queue: object) -> list[str]:
    """`CT-REVIEW-04` — which of the residual triple the rendering fails to state.

    Numbers, not field names: a console that prints the label `residual_provisional` and no
    figure has rendered nothing, and a console that prints `12` for a queue whose residual is
    `12` has rendered it whatever it called the row.
    """
    missing = []
    for field in RESIDUAL_TRIPLE:
        value = getattr(queue, field, None)
        if field == "shown" and value is not None:
            value = len(value)
        if value is None or str(value) not in rendering:
            missing.append(field)
    return missing


_FIELD_WORDS = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def label_fields_in(text: str) -> list[str]:
    """Which `LABEL_FIELDS` appear in `text` as whole identifiers.

    `origin` is a substring of `original`, and a re-run prompt saying *"the original submission"*
    is compliant — a substring scan fails it. Tokenising first is what keeps the rule usable, and
    review found the substring version.
    """
    words = set(_FIELD_WORDS.findall(text))
    return sorted(field for field in LABEL_FIELDS if field in words)


def reachable_values(data: object, sentinel: object, path: str = "") -> list[str]:
    """Every place `sentinel` is reachable inside `data`, as dotted paths.

    `CT-REVIEW-09` step 2 asks whether the system's answer is *available* to the blind session,
    and an earlier draft asked `"system_band" not in session.available_data()` — top-level key
    membership on a mapping, which passes a session returning
    `{"items": [ref_with_a_system_band, ...]}` for all five fields. The question is about the
    value and about the whole structure, so the walk is recursive.
    """
    found: list[str] = []
    if data == sentinel:
        return [path or "<root>"]
    if isinstance(data, dict):
        for key, value in data.items():
            found += reachable_values(value, sentinel, f"{path}.{key}" if path else str(key))
    elif isinstance(data, (list, tuple, set, frozenset)):
        for index, value in enumerate(data):
            found += reachable_values(value, sentinel, f"{path}[{index}]")
    elif hasattr(data, "__dict__"):
        for key, value in vars(data).items():
            found += reachable_values(value, sentinel, f"{path}.{key}" if path else str(key))
    return found


def module_sources(module: object) -> list[tuple[str, str]]:
    """`(name, source)` for a module, or for every source file in it if it is a package.

    `inspect.getsource(package)` returns `__init__.py` alone. `M-REVIEW` is four stories — a
    queue, a label store and two samples — so shipping as a package is likely, and a surface scan
    that saw only the `__init__` would miss a numeric-entry parameter in `aeh/review/queue.py`
    while its docstring promised the whole surface. Review caught that.
    """
    import inspect
    import pathlib as _pathlib

    paths = getattr(module, "__path__", None)
    if paths is None:
        return [(module.__name__, inspect.getsource(module))]
    sources = []
    for root in paths:
        for file in sorted(_pathlib.Path(root).rglob("*.py")):
            sources.append((file.name, file.read_text(encoding="utf-8")))
    return sources


def items_shown(queue: object) -> int:
    """How many review **items** a queue is showing, counting a group as its members.

    `len(queue.shown)` counts *entries*, and §3.15 types `shown` as
    `Sequence[ReviewItem | ReviewGroup]` — so a queue presenting 200 items as 16 groups shows 16
    entries and covers 200 items, and `CT-REVIEW-04`'s residual arithmetic is about the second
    number. Review found `flagged_total - len(shown)` demanding a residual of 184 from a correct
    queue with nothing left over.
    """
    total = 0
    for entry in getattr(queue, "shown", ()):
        members = getattr(entry, "members", None)
        total += len(members) if members is not None else 1
    return total


def blind_prefetch_attributes(session: object) -> list[str]:
    """`CT-REVIEW-09`'s adversarial construction — a score row cached on the session.

    Attribute presence, not rendering: the whole point of the construction is that nothing is
    rendered. A session carrying any of these has degraded the guarantee from *unreachable* to
    *hidden*, which is one template change from visible.
    """
    return sorted(
        name for name in BLIND_PREFETCH_ATTRIBUTES if getattr(session, name, None) is not None
    )
