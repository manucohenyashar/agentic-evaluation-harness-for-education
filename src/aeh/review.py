"""M-REVIEW — the minute-budgeted review queue (§3.15, issue #108).

The teacher states a minute budget; the queue spends it where a wrong score
costs the most per review second. Everything here is a pure function of the
stored signals (`NFR-REVIEW-02`): the ranking reads the four observable
error-probability inputs (`FR-REVIEW-03`), the two impact inputs, and the cost
estimate — and nothing else. `self_confidence` is deliberately unread (R22).

**The ranking score.** ``expected_value = (P(score wrong) × impact) / est_seconds``:

* ``P`` is an equal-weight sum of the four signals `FR-REVIEW-03` names — panel
  spread, adverse integrity signals (normalized by a cap), transcription
  overlap, and the criterion's historical override rate. §3.15 names the four
  inputs and no weights; equal weights are the uncommitted reading, and each
  carries a knob (`AEH_REVIEW_*`) so a Phase 2 calibration can replace them
  without a code change. `self_confidence` is not an input (R22).
* ``impact`` is ``criterion_weight × boundary proximity``, where proximity is
  ``1 / (1 + grade_boundary_delta / half_width)`` — a smooth 1→0 falloff that
  is 1 at the boundary and halves at the half width. The design says
  "proximity to a grade boundary" and names no shape; this one is monotone,
  bounded, and sensitive at the scale the fixtures use.
* The quotient — not an additive cost term — is the clause's own arithmetic
  (`TC-REVIEW-C03`'s ratio case), and `rank_queue_items` returns it as
  ``expected_value``, the same name the `#95 TS-36` unit suite already pins.

**Interpretations this module records** (each is a place the design is silent
and this implementation chose; all are reported on the PR):

* *The 5-minute budget under a 10-minute reserve.* `NFR-REVIEW-05` promises
  honest degradation at 5 minutes; `REVIEW_BLIND_RESERVE_MINUTES` is 10 and is
  subtracted first (`FR-REVIEW-02`), which would leave nothing to spend. The
  queue never returns an empty ``shown`` over a non-empty admitted population:
  when no entry fits, it shows the single top-ranked entry and states the
  truth in the residual. The floor of one keeps the degradation honest — fewer
  items, larger residual, same ranking rule — where an empty queue would make
  the same-rule assertion vacuous.
* *The blind reserve is capped at the budget*: ``min(REVIEW_BLIND_RESERVE_MINUTES,
  budget_minutes)``. A queue cannot reserve minutes the teacher did not offer.
* *The fill is greedy and never reorders.* Entries are taken in rank order
  (groups first, `FR-REVIEW-05`), each taken when it fits and passed over when
  it does not; the walk never reorders and never revisits, so the ranking rule
  is identical at every budget and the build never bills its own seconds to
  the teacher (`CT-REVIEW-16`). The residual counts items, not entries — a
  group covers its members (`vocab.items_shown`).
* *A flagged item is named by the teacher's routing, whatever its state.* The
  admitted population is ``routing`` in ``queued``/``provisional`` — the
  panel-routed work (`CT-AGG-06`) plus the provisional family, whose
  single-judge fallback and breaker refusal route identically and are told
  apart by state alone — in the judged mode (`FR-REVIEW-06`, enforced from the
  evaluation-mode column per `CT-DET-06`), outside the never-rendered origins
  (`FR-REVIEW-07`). The state column does not gate admission: `CT-AGG-07`
  binds consumers to surface ``ungradeable_by_panel`` rather than treat it as
  an ordinary provisional, and a state gate would hide exactly the row that
  clause names — the c07 consumer differential forces the read (both its rows
  route ``provisional``, one state apart, and the queue must present them
  differently). Panel work the panel routed to the teacher arrives ``final``
  (`CT-AGG-06` puts ``queued`` in the teacher's queue regardless). An acted-on
  row leaves the count through the service's acted-set (in memory) or through
  the store write #109's audit declares (rung 2, once #110 lands the label
  store), which is what makes ``flagged_total`` fall by exactly the reviewed
  item across sessions.
* *No-data override history reads as 0.5* (`AEH_REVIEW_OVERRIDE_RATE_NO_DATA`) —
  the same unmeasured-risk posture as `aeh.agg`'s escalation weight: a
  criterion nobody has reviewed is not a criterion nobody disagrees with
  (`CT-STATS-09`). The criteria-form ranker mirrors
  ``aeh.agg.rank_criteria_for_escalation`` exactly (no data first, then
  override rate descending, stable), which is what the `CT-STATS-09` consumer
  differential asserts of both consumers.
* *A group costs one decision.* ``ReviewGroup.est_seconds`` is its most
  expensive member's estimate: acting on the group is one band decision
  however many members it resolves, and that is what the budget accounting
  charges. The group's ranking value sums its members' value-per-decision.
* *Groups form only at two or more members* sharing criterion and signature —
  a one-member "group" would be a per-item entry wearing a costume, and
  `CT-REVIEW-20`'s sweep would count its lone member as grouped.
* *``est_seconds`` of zero or less is missing data*, not a free item: it takes
  the default estimate rather than dividing the score by zero or ranking the
  item first. ``REVIEW_DEFAULT_EST_SECONDS`` is the default (`FR-REVIEW-16`:
  the estimate is uncalibrated at Phase 1, and a missing one is not a zero).
* *Group labels record the honest per-member time*: ``review_seconds`` is
  divided across the members, because the group action genuinely took less per
  member — which is why ``GROUP_INDISTINGUISHABILITY_FIELDS`` excludes it.
* *The no-package-context points route reads the declared default band scale.*
  ``FR-REVIEW-10`` derives ``new_points`` from the band through `CT-PKG-05`'s
  pinned mapping — but the mapping needs a band table, and a score row carries
  none (the store rows carry no package linkage). With a ``catalog=`` attached
  the criterion's own pinned table is read
  (``PackageCatalog.points_for_band``); without one, the derivation reads the
  declared default scale below through the *same* mapping function, so the
  conversion logic still exists in exactly one place (`NFR-AGG-02`) — only the
  default band *data* is review's. A band absent from whichever table governs
  refuses (`PackageError`) rather than defaulting to a number — but a band
  whose *name* exists in both a stored package's table and the default scale
  is not detectable without a catalog, so the no-catalog route derives the
  default scale's points for it. Open the service with the run's
  ``catalog=`` when the labels' points must follow the package's own table;
  the no-catalog route is the in-memory flow's convenience, not a
  package-aware conversion.
* *A label is persisted when the service holds a store.* The store form's
  ``act`` writes the same label to Tier D's ``label`` table (the Durable 6
  columns this module's migration adds) that it writes in memory. `CT-STORE-03`
  scopes atomicity to one transaction body and cross-tier atomicity is
  deliberately not provided, so the two halves are sequential: a durable-write
  failure aborts the action with the in-memory record already written, and the
  caller sees the refusal. The same per-row scope makes a *group* action's
  durability partial by construction — members persist one row at a time, so
  a mid-loop failure leaves the earlier members durable and aborts the rest;
  a retry writes fresh label ids for every member, double-marking the already
  durable ones. Label ids are per-service sequential, so two
  services over one store collide on the row's primary key and refuse — one
  review session per run is the Phase 1 shape. A store-backed action with no
  run context (nothing built, and the service opened over zero or several
  cohorts) is refused rather than attributed to an invented run. The durable
  row's ``cohort_id`` scoping column — what `CT-STORE-10`'s promotion gate
  counts against — carries the *run's* id, not a per-row cohort: a run
  belongs to one cohort in this codebase (`aeh.orch`'s ``run`` table pairs
  each run id with a cohort id, and ``open_review`` names the cohort as the
  run), so in the declared store flow the two are the same string. A queue
  built under a fresh id over a multi-cohort ``build_review(store)`` service
  attributes its labels to that run id — `purge_cohort` keyed by a cohort id
  will not find those rows and refuses, fail-closed; keying the row to a
  cohort the in-memory rows do not carry is not Phase 1's shape.
* *Observability is per run, attributed from the service's own bookkeeping.*
  ``build_queue`` records the run it built for; actions after a build attribute
  their labels to that run. ``blind_completion_rate`` is measured from #111's
  blind flow: answered refs over drawn refs for the run — ``None`` for a run
  that never drew, which stays an unmeasured rate, never a silent zero.
* *The budget-exhaustion streak counts the administrations a criterion
  exhausted.* The service sees exhaustion events, not the administrations that
  went without one, so the streak is the recorded sequence for the criterion
  and the alert fires at two and stays — the pattern is retained across
  administrations, not reset per term.
* *The no-browser-storage rule is console-side, and this module is not the
  console.* `FR-REVIEW-12`'s clause binds the review views that display
  verbatim student work to write none of it to browser storage; the
  boundary reading is that this module — the headless core those views call —
  holds no browser surface at all: it writes labels to the store or memory,
  never to any client-side persistence, so the rule is unviolable from here.
  The obligation itself belongs to M-CONSOLE's view layer, where the student
  text is actually displayed; that layer's story carries the rule.
* *The skip-over fill is not a prefix fill at every budget.* The ranking rule
  is identical at every budget (same score, same order), but because an entry
  that does not fit is passed over rather than stopping the walk, a squeezed
  budget can show a different selection than a prefix of the generous budget's
  — a cheap tail item can ride along while an expensive head item is skipped.
  ``CT-REVIEW-C01``'s pinned assertion (the 5-minute floor-of-one showing the
  single top entry) is structurally a prefix at any fixture, so the case holds
  today; the divergence lives at intermediate budgets the plan does not pin.
  A prefix fill was rejected because it would strand the budget behind one
  expensive entry the design's "spend it where a wrong score costs the most"
  does not ask for.
* *Ranking is vacuous at rung 2 until the store carries the signals.*
  ``FR-REVIEW-03``'s seven inputs exist in no landed schema (``criterion_score``
  carries band/state/routing/confidence and the integrity booleans only), so
  ``open_review``'s admitted rows all score ``expected_value = 0.0`` (P falls
  to the 0.5 no-data default; impact falls to 0 with ``criterion_weight``
  absent) and the queue ranks by store row order. Admission, grouping, the
  budget and the residual all work; the expected-value ordering arrives with
  M-GRADE/M-STATS's columns, and no migration was added here (the issue
  forbids one).

**#109 — the prohibitions, the persistent residual, and the no-annotation
rule.** Extends the queue with the three `CT-REVIEW-05`/`-06`/`-14` surfaces
the clause suite resolves through `require_attr` (`FR-REVIEW-06/-07/-08/-17`):

* *The admission is a declared plan, not an observed absence.* ``admission_query()``
  returns the ``QueryPlan`` the queue actually runs — the routing values, the
  evaluation mode, the excluded origins. ``_admitted`` is the one predicate the
  in-memory filter and the store-form SQL both read, so the plan cannot drift
  from what runs, and `CT-REVIEW-05`'s reachability claim is asserted against
  the plan rather than against one fixture's outcome.
* *The write set is declared, and every write is audited.* ``write_fields()`` is
  the module-level declaration of every field a review action writes
  (`FR-REVIEW-17`'s intersection with the scoring prompt fields is asserted
  against it — and the intersection holds for prompts nobody has written yet,
  which is the strength the clause asks for), and ``act``/``act_on_group``
  append a ``WriteRecord`` per write to ``write_audit()``: ``criterion_score``
  for the reduction through the score row, ``label`` for the label itself.
  `CT-REVIEW-06` reads the indirection from the audit rather than from the
  resulting counts, because the counts are identical either way.
* *The residual persists across its two vanishing moments.* ``end_session`` and
  ``close_run`` are the sitting's end and the run's close — the two moments a
  residual could silently stop being one (`FR-REVIEW-08`). Neither clears, and
  neither finalizes: the acted set, the labels, and every residual row's
  ``provisional_unreviewed`` state survive both, and ``scores()`` keeps
  returning every still-flagged row. Each moment returns a ``ResidualReport``
  stating the residual as it left it, so the persistence is readable off the
  result rather than trusted.
* *No annotation surface.* The module writes no field any scoring prompt reads
  and exposes no per-student annotation surface (`FR-REVIEW-17`, R15) — the
  review-side half of the store and console annotation prohibitions
  (`FR-STORE-08`/`FR-CONSOLE-03`). Nothing a teacher records here reaches a
  re-run of the same unit, which is the route that would actually open.

Interpretations #109 records:

* *The two moments are audited reports, not state changes.* The honest
  implementation of "the residual persists" is that nothing happens to it:
  ``end_session``/``close_run`` mutate nothing, and their reports state the
  residual and the (empty) ``finalized``/``backfilled`` lists rather than a
  boolean trust flag — the fields are what a later change that starts
  finalizing would have to name its write in. The store-form write that
  updates an acted row's state, and the label store that carries a residual
  across processes, are #110's.
* *``routing_values`` reports both advisory routings.* The written-ahead c05
  reachability draft pinned ``("queued",)`` alone; the landed admission admits
  the provisional family with it — `CT-AGG-07`'s consumer differential makes
  that load-bearing (both its rows route ``provisional``, one state apart) —
  so the plan reports both and the draft's pin was reconciled at this unmark.
  ``triage``, the operator's queue, is reachable by neither, which is the half
  the original pin protected.
* *``skip`` writes nothing.* No label, no reduction, no audit record: the item
  stays flagged and stays residual, which is `CT-REVIEW-06`'s point — a skip
  that wrote a resolution would be the silent finalization `FR-REVIEW-08`
  forbids.

**The four seams.**

1. *Headless driver.* ``build_queue``/``act``/``act_on_group`` return structured
   results — the queue carries the residual triple plus a per-stage
   ``build_trace`` (one ``BuildEvent`` per stage, in order), and every action
   returns the label it wrote (or ``None`` for a skip). #109's reads and
   moments are the same shape: ``admission_query``, ``write_audit``, ``scores``,
   ``end_session``/``close_run`` all return structured results, no console.
2. *Deterministic transport.* There is no egress here. The rung-2 constructor
   ``open_review`` reads the cohort's own SQLite through ``aeh.store`` — the
   same deterministic store every other module reads — and never opens a
   network path. Ranking is a pure function of those rows.
3. *Env-gated knobs.* The four §3.15 configuration knobs are module constants
   injected at the call (``build_review(..., review_blind_n=..., config=...)``:
   keyword wins over a ``config=`` attribute, which wins over the constant).
   The calibration constants are read from the environment at call time
   through ``_env_float`` (`orch.py`'s shape): invalid values refuse rather
   than fall back, so a typo'd override cannot silently take the production
   number.
4. *Stage-level observability.* ``ReviewQueue.build_trace`` records what each
   build stage did, in order — `CT-REVIEW-02`'s event-order contract (reserve
   before rank) is asserted against exactly this trace — and the residual
   triple in the header is the run's own observability surface. #109 carries
   the rule to the actions: every write is audited with the table it landed
   on, and the residual's two vanishing moments each report what they left.

``ReviewService`` here is the concrete implementation of the §3.15 Protocol's
three #108 members (``build_queue``, ``act``, ``act_on_group``), #109's
read-and-audit surface (``admission_query``, ``write_audit``, ``scores``,
``labels_for``, ``end_session``/``close_run``; ``write_fields`` is module
level), #110's label store — ``record_label``/``labels_for`` at module level,
the collection surface for paths that hold no service handle, and ``label``,
``points_for_band``, ``edit_views``, ``act_from_view``, ``observability_counters``,
``counter_emissions``, ``exhaust_budget_on`` and ``alerts`` on the service —
and #111's two samples: ``blind_sample``/``submit_blind`` (the blind flow the
reserve protects), ``whole_grade_sample``, ``skip_blind_sample`` and
``render_blind_flow`` on the service, with ``blind_sample_skipped`` at module
level beside ``record_label``. Actions write in-memory labels and, on
a store-backed service, the same label to Tier D; a label's ``new_points`` is
derived from its band through `CT-PKG-05`'s pinned mapping
(``aeh.pkg.points_for_band``), which `NFR-AGG-02` keeps defined in exactly one
place in the source.

**#111 — the two samples, the skip, and the budget the reservation protects.**
Extends the service with `FR-REVIEW-12`/`-13`/`-14`'s three surfaces — the
blind sample the reserve protects, its submission, and the whole-grade sample —
plus the skip and its report (`CT-REVIEW-09`/`-10`/`-11`, `CT-REVIEW-15`'s
interrupted-session half, and the blind path of `CT-REVIEW-08`):

* *The reserve reconciliation is kept as landed.* #108's flagged finding asked
  this story to keep or revise the reserve reading; the reserve-cap +
  floor-of-one interpretation above is **kept** unchanged — the reserve is
  ``min(REVIEW_BLIND_RESERVE_MINUTES, budget_minutes)`` and the queue never
  returns an empty ``shown`` over a non-empty admitted population. The blind
  sample is drawn independently of the queue's fill (`CT-REVIEW-02`'s survival
  case is about the reserved minutes staying unspent on queue items), so the
  floor never costs the sample its draw — it costs the queue items, which is
  the honest degradation `NFR-REVIEW-05` states.
* *The draw is uniform over the eligible set, seeded per draw.* Each draw's
  RNG is derived from the service's seed and the draw's index, so the same
  seed reproduces the same *sequence* of draws while successive draws on one
  service differ — the per-run rate aggregates sittings, and a second sitting
  that re-drew the first's refs would double-write its labels; a declared seed
  of ``None`` stays entropy-per-draw, since an undeclared seed that silently
  pinned every administration to the same sample would be first-N's defect in
  disguise. ``blind_sample`` samples over the admitted judged rows. A blind
  label is evidence about the system, not a resolution of the row, so a drawn
  and answered ref stays eligible for the queue — the flow collects validation
  evidence, it does not review the row (`CT-REVIEW-06`'s indirection is the
  queue action's). A pool smaller than ``n`` floors the draw at the pool — the
  floor-of-one reading applied to a population: a small cohort gets a smaller
  sample, disclosed by the session's item count, rather than a refusal that
  would leave a small administration no validation evidence at all.
* *The system's output is structurally unreachable from the blind flow, not
  hidden.* `CT-REVIEW-09` words the clause as reachability, so the guarantee is
  a property of the type: a ``BlindItem`` carries ``submission_id``,
  ``criterion_id`` and ``evaluation_mode`` — the identity a judgement is about
  — and nothing else, exactly as `aeh.synth`'s ``L2Request`` carries no field a
  score could ride. ``BlindSession`` exposes ``readable_tables()``
  (``submission`` and ``criterion``, per §3.15's Data flow paragraph),
  ``available_data()`` and no field a score row could occupy; the rendered flow
  is built from the session alone, so the five outputs `FR-REVIEW-11` forbids
  are unreachable from the draw through to the render. The label's
  ``saw_system_output = 0`` is earned by that construction, not stored as a
  constant (`CT-REVIEW-09` step 4).
* *A submission records exactly the criteria answered.* ``submit_blind`` writes
  one ``blind`` label per answered ref — ``saw_system_output = 0``,
  ``system_band = None``, no ``review_queue_action`` (a blind label is not a
  queue action) — and refuses a ref the session never drew. An interrupted
  session is the same path with ``interrupted=True``: the labels written are
  the answered ones, which is `CT-REVIEW-15`'s clause in both directions (more
  would invent a judgement nobody made; fewer would discard the scarcest data
  the system collects). A session submits once; a second submission of the
  same session is refused rather than double-written.
* *The whole-grade sample is an offer, not a step.* ``whole_grade_sample``
  draws 10–15 complete final grades from the auto-accepted population — a
  submission qualifies only when **every** criterion row routed ``auto``:
  sampling reviewed grades would measure the review, not the system, and a
  submission holding a reviewed criterion is excluded with them, because a
  partial band set presented as the student's final grade understates it and a
  mixed one shows the teacher's corrections as system work. Each grade is one
  ``rendered_as_student_sees_it``. It writes no label — `FR-REVIEW-14` offers
  a display, and `FR-REVIEW-09` writes labels for decisions. The store form
  reads its population through the declared ``select_auto_grades`` statement,
  whose NOT IN guard carries the same restriction (the service's own fetch
  admits only the teacher's routings); the in-memory form filters its own rows
  to the same set.
* *Skipping has exactly one consequence.* ``skip_blind_sample`` records the
  skip; ``blind_sample_skipped`` reads it back as the reported absence. The
  report's ``current_figure`` is ``None`` — never a previous administration's
  figure, which is the silent carry-forward RISK-08 forbids — and the run's
  ``close_run`` report carries ``grades_delivered``/``grades_finalized`` as
  ``True`` by construction: the sample is the system's instrument, not the
  student's gate (`FR-REVIEW-13`). A run either draws its sample or skips it:
  a draw after a skip, and a skip beside a draw, are both refused, so the
  report's "no new validation evidence was collected" is guaranteed to agree
  with the evidence on record rather than asserted over it.
"""

from __future__ import annotations

import itertools
import os
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable, Mapping, Sequence

# The label store's own schema: this module owns Tier D's last migration (the
# durable ``label`` columns the fully-typed label needs), so the schema imports
# are module-level — importing ``aeh.review`` is what completes a durable chain
# to the pin (CLAUDE.md's contributor rule).
from aeh.store import Migration, Statement, Tier, TIER_MIGRATIONS

__all__ = [
    "REVIEW_BLIND_RESERVE_MINUTES",
    "REVIEW_BLIND_N",
    "REVIEW_WHOLE_GRADE_N",
    "REVIEW_DEFAULT_BUDGET_MINUTES",
    "REVIEW_DEFAULT_BANDS",
    "REVIEW_STATEMENTS",
    "REVIEW_BUDGET_EXHAUSTION_ALERT",
    "BLIND_SAMPLE_RANGE",
    "WHOLE_GRADE_SAMPLE_RANGE",
    "ReviewError",
    "StaleReviewItemError",
    "ReviewItem",
    "ReviewGroup",
    "ReviewQueue",
    "BuildEvent",
    "LabelRecord",
    "BlindItem",
    "BlindSession",
    "SubmissionGrade",
    "BlindSampleSkipReport",
    "QueryPlan",
    "WriteRecord",
    "ResidualReport",
    "CriterionOverrideRank",
    "SupersededScore",
    "CounterEmission",
    "ReviewAlert",
    "ReviewService",
    "build_review",
    "open_review",
    "rank_queue_items",
    "record_label",
    "labels_for",
    "blind_sample_skipped",
    "write_fields",
]


# --- the four §3.15 configuration knobs (CT-REVIEW-17) ----------------------------------------------
#
# §3.15's Configuration line, transcribed with their declared Assumption values.
# CT-REVIEW-17 makes all four M-STATS's inputs as much as this module's settings,
# so the names are part of the contract — a story cannot rename them without the
# design changing first.

#: Minutes always reserved for the blind sample, subtracted BEFORE any ranking
#: (`FR-REVIEW-02`) — the event order is the contract (`CT-REVIEW-02`).
REVIEW_BLIND_RESERVE_MINUTES = 10
#: Submissions the blind sample draws by default (`FR-REVIEW-12`); the draw
#: itself is #111's ``blind_sample``, range-checked against BLIND_SAMPLE_RANGE.
REVIEW_BLIND_N = 15
#: Complete final grades the whole-grade sample draws by default (`FR-REVIEW-14`;
#: #111's ``whole_grade_sample``, range-checked against WHOLE_GRADE_SAMPLE_RANGE).
REVIEW_WHOLE_GRADE_N = 12
#: The budget `build_queue` assumes when a caller states none. §3.15's
#: Interfaces block declares ``budget_minutes`` required, so nothing reads this
#: today — it is declared because CT-REVIEW-17 asserts its value.
REVIEW_DEFAULT_BUDGET_MINUTES = 30

#: The blind sample's draw range, inclusive at both ends (`FR-REVIEW-12`): a
#: draw outside it is refused, not clamped — a κ over three labels is a number
#: with no business being reported, and a 40-item draw is not what the teacher
#: asked for either. `CT-REVIEW-11` refuses both ends by name.
BLIND_SAMPLE_RANGE = (15, 25)
#: The whole-grade sample's range, inclusive at both ends (`FR-REVIEW-14`),
#: refused the same way.
WHOLE_GRADE_SAMPLE_RANGE = (10, 15)


# --- the calibration constants (Phase 1; FR-REVIEW-16's calibration is Phase 2) ---------------------
#
# §3.15 names the formula's factors and no numbers. These are the Phase 1
# reading, each env-gated at call time (seam 3) so a differently-shaped corpus
# can adjust without a code change, and each injectable through ``config=``
# under its own name.

#: Weight of one unit of panel spread in P(score wrong). Equal weights: the
#: design names four inputs and no weighting.
REVIEW_PANEL_SPREAD_WEIGHT: float = 1.0
#: Weight of one adverse integrity signal, after the cap below.
REVIEW_INTEGRITY_SIGNAL_WEIGHT: float = 1.0
#: Weight of transcription overlap in P(score wrong).
REVIEW_TRANSCRIPTION_OVERLAP_WEIGHT: float = 1.0
#: Weight of the criterion's historical override rate in P(score wrong).
REVIEW_OVERRIDE_RATE_WEIGHT: float = 1.0
#: The count of adverse integrity signals read as "the panel is shouting";
#: the signal is normalized by this cap, not by trust.
REVIEW_INTEGRITY_SIGNAL_CAP: int = 3
#: Boundary proximity ``1/(1 + delta/half_width)`` halves here: a criterion
#: whose band sits this far from a grade boundary is half as boundary-urgent.
REVIEW_BOUNDARY_HALF_WIDTH: float = 10.0
#: P contribution of an override history nobody has measured (`CT-STATS-09`:
#: no data is not a zero; the unmeasured criterion is the risky one).
REVIEW_OVERRIDE_RATE_NO_DATA: float = 0.5
#: The estimate used when a row carries no usable ``est_seconds``.
REVIEW_DEFAULT_EST_SECONDS: float = 60.0

_WEIGHT_LOW, _WEIGHT_HIGH = 0.0, 10.0

# --- errors -----------------------------------------------------------------------------------------


class ReviewError(Exception):
    """Base class for the review module's refusals, so callers can catch the
    module's own failures without catching the package's too."""


class StaleReviewItemError(ReviewError):
    """An action arrived for a score row the queue no longer reflects
    (`CT-REVIEW-15`): the row was superseded by an escalation after this queue
    was built, and acting on the stale copy would overwrite a judgment somebody
    else already made. The message says to refresh the queue."""


# --- the label store's durable schema (FR-REVIEW-09, #110) ------------------------------------------
#
# The durable `label` table predates this module (M-STORE's base DDL carries
# label_id/run_id/student_ref/criterion_id/label_type/band, and #87's
# `det_audit_separation_columns` added `evaluation_mode` — deliberately not
# re-added here, its CHECK would fail the ALTER). What it could not carry was a
# *fully-typed* label: `FR-REVIEW-09`'s eight fields, `NFR-REVIEW-03`'s
# attribution pair, the queue action `FR-REVIEW-15`'s parity clause compares,
# and the `cohort_id` scoping column the Tier D promotion gate reads
# (`_PURGE_PROMOTED_ROWS`). This migration is what makes the store able to hold
# one, so an acted review session outlives the process that acted it.

_DURABLE_006 = Migration(
    version=6,
    name="review_label_store_columns",
    statements=(
        # CT-REVIEW-08's admissibility column: 1 = the teacher saw the system's
        # output (an operational signal, excluded from agreement at the
        # consumer per FR-STATS-01), 0 = the blind flow's earned 0 (#111). The
        # default of 1 discloses the honest worst case for pre-existing rows —
        # they count as operational, not as validity evidence they never were.
        Statement("ALTER TABLE label ADD COLUMN saw_system_output INTEGER "
                  "NOT NULL DEFAULT 1"),
        # The routing/origin/mode triple the queue admitted on, recorded so a
        # label can be traced back to the population rule that surfaced it.
        Statement("ALTER TABLE label ADD COLUMN routing TEXT "
                  "NOT NULL DEFAULT 'queued'"),
        Statement("ALTER TABLE label ADD COLUMN origin TEXT "
                  "NOT NULL DEFAULT 'escalation'"),
        # CT-REVIEW-19's Phase 2 calibration input: the seconds the decision
        # actually took, against est_seconds stored on the score row.
        Statement("ALTER TABLE label ADD COLUMN review_seconds REAL "
                  "NOT NULL DEFAULT 0"),
        # The agreement pair itself. `band` above stays NOT NULL — it is the
        # effective band the label stands for; the pair records both sides.
        # system_band is nullable: a blind label carries none (#111).
        Statement("ALTER TABLE label ADD COLUMN system_band TEXT"),
        Statement("ALTER TABLE label ADD COLUMN teacher_band TEXT"),
        # NFR-REVIEW-03's attribution pair. actor carries '' on pre-existing
        # rows (unattributed — a DEFAULT of a name would be the attribution
        # lie CT-REVIEW-07 refuses) rather than pretending an owner.
        Statement("ALTER TABLE label ADD COLUMN actor TEXT NOT NULL DEFAULT ''"),
        Statement("ALTER TABLE label ADD COLUMN timestamp TEXT"),
        # Identity: the score the label is about, the queue action
        # FR-REVIEW-15's parity clause compares, and the derived points.
        Statement("ALTER TABLE label ADD COLUMN score_id TEXT"),
        Statement("ALTER TABLE label ADD COLUMN review_queue_action TEXT"),
        Statement("ALTER TABLE label ADD COLUMN new_points REAL"),
        # The promotion scoping column: `_purge_precondition_failures` refuses a
        # cohort purge while this table lacks it, and a promotion keys labels to
        # the administration they belong to.
        Statement("ALTER TABLE label ADD COLUMN cohort_id TEXT"),
    ),
)

#: This module's declared statements (`FR-STORE-08`): the one write the label
#: store makes to the durable tier, keyword-parameterized. Registered in the
#: module's own registry, the shape every other contributing module uses.
REVIEW_STATEMENTS: dict[str, Statement] = {
    "insert_label": Statement(
        "INSERT INTO label (label_id, run_id, student_ref, criterion_id, "
        "label_type, band, evaluation_mode, saw_system_output, routing, origin, "
        "review_seconds, system_band, teacher_band, actor, timestamp, score_id, "
        "review_queue_action, new_points, cohort_id) "
        "VALUES (:label_id, :run_id, :student_ref, :criterion_id, :label_type, "
        ":band, :evaluation_mode, :saw_system_output, :routing, :origin, "
        ":review_seconds, :system_band, :teacher_band, :actor, :timestamp, "
        ":score_id, :review_queue_action, :new_points, :cohort_id)"
    ),
    # #111's whole-grade read: the auto-accepted population the sample draws
    # from. The service's own fetch admits only the teacher's routings
    # (`queued`/`provisional`), so the sample reads its population through this
    # declared literal — a `.query`, never a runtime assembly (SEC-15), and
    # never a join to anything the blind flow can reach. In-memory services
    # filter their own rows instead.
    "select_auto_grades": Statement(
        "SELECT submission_id, criterion_id, band FROM criterion_score "
        "WHERE routing = 'auto' "
        "AND submission_id NOT IN "
        "(SELECT submission_id FROM criterion_score WHERE routing <> 'auto')"
    ),
}

TIER_MIGRATIONS[Tier.DURABLE] = TIER_MIGRATIONS[Tier.DURABLE] + (_DURABLE_006,)

#: The views that display a band and can therefore carry a review action
#: (`FR-REVIEW-15`; the teacher routes of the design's console table): the
#: queue itself (S9), the run rollup, the student view (S13 — the case
#: `TC-REVIEW-15` names), and the submission detail. The blind flow and the
#: whole-grade sample are deliberately absent: the blind flow must not display
#: the system's band at all (`FR-REVIEW-11`), and the sample displays grades,
#: not band decisions. `edit_views()` is a method over this constant so a view
#: added later joins `CT-REVIEW-12`'s sweep on the day it appears.
_EDIT_VIEWS: tuple[str, ...] = (
    "review_queue",
    "rollup",
    "student",
    "submission_detail",
)

#: The default band scale the no-package-context points route reads. The
#: *mapping* is `aeh.pkg.points_for_band`'s alone (`NFR-AGG-02`); this constant
#: is only the band *data* the derivation needs when a score row carries no
#: package linkage (none of the store rows do — #108's ranking interpretation
#: records the same absence). The scale is the plan's 0–100 spread over five
#: bands; a criterion's real table supersedes it the moment a catalog is
#: attached.
REVIEW_DEFAULT_BANDS: tuple[dict[str, Any], ...] = (
    {"band": "B1", "points": 0.0},
    {"band": "B2", "points": 25.0},
    {"band": "B3", "points": 50.0},
    {"band": "B4", "points": 75.0},
    {"band": "B5", "points": 100.0},
)

#: The counter names `CT-REVIEW-18`'s surface names. Every one is a key of
#: ``observability_counters``'s result for any run — an unmeasured value is
#: ``None``, never absent, so a missing name is a defect and not a quiet gap.
_OBSERVABILITY_COUNTERS: tuple[str, ...] = (
    "review_minutes_used",
    "review_items_shown",
    "review_items_flagged",
    "override_rate_by_criterion",
    "group_action_usage_share",
    "blind_completion_rate",
    "mean_review_seconds",
    "mean_est_seconds",
)

#: The budget-exhaustion alert and the streak length that fires it
#: (`CT-REVIEW-18`): a criterion that exhausted its budget on two
#: administrations in a row is a pattern, not a coincidence.
REVIEW_BUDGET_EXHAUSTION_ALERT = "criterion_exhausts_budget_across_administrations"
_ALERT_MIN_CONSECUTIVE_ADMINISTRATIONS = 2


# --- the queue's wire shapes ------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewItem:
    """One flagged criterion as the queue presents it — §3.15's wire shape plus
    the identity fields a differential reads and the ranking surface (`FR-REVIEW-03`,
    `FR-AGG-06`'s tie-break input). ``state`` rides through because `CT-AGG-07`
    binds consumers to surface ``ungradeable_by_panel`` rather than merge it
    into the provisional presentation."""

    score_id: str
    criterion_id: str
    submission_id: str
    version: int
    state: str | None
    proposed_band: str | None
    band_options: tuple[str, ...]
    proposed_points: float | None
    max_points: float | None
    narrative: str | None
    evidence_spans: tuple[Any, ...]
    reason: str
    est_seconds: float
    package_version_id: str | None
    grade_boundary_delta: float
    expected_value: float
    scoring_model: str | None


@dataclass(frozen=True)
class ReviewGroup:
    """One signature-identical group presented as a single entry (`FR-REVIEW-05`).

    ``members`` carries the full per-item rows, so "one label per member" is
    countable (`CT-REVIEW-13`) and the group's per-item view survives the
    collapse. ``est_seconds`` is the most expensive member's estimate — one
    band decision is charged once, at the slowest member's pace."""

    members: tuple[ReviewItem, ...]
    signature: Mapping[str, Any]
    criterion_id: str
    proposed_band: str
    est_seconds: float
    expected_value: float
    reason: str


@dataclass(frozen=True)
class BuildEvent:
    """One stage of a queue build (`NFR-REVIEW-01`'s trace seam). ``name`` is the
    stable identifier the event-order contract reads (`CT-REVIEW-02`)."""

    name: str
    detail: str = ""


@dataclass(frozen=True)
class ReviewQueue:
    """The built queue — §3.15's five declared fields plus the group list, the
    build's own timing, and the per-stage trace."""

    run_id: str
    budget_minutes: int
    reserved_for_blind_minutes: int
    flagged_total: int
    shown: tuple["ReviewItem | ReviewGroup", ...]
    residual_provisional: int
    groups: tuple[ReviewGroup, ...]
    build_seconds: float
    build_trace: tuple[BuildEvent, ...]


@dataclass(frozen=True)
class LabelRecord:
    """The label an action writes — `FR-REVIEW-09`'s eight fields, `NFR-REVIEW-03`'s
    attribution, and the identity fields a differential reads, with ``new_points``
    derived through `CT-PKG-05`'s pinned mapping from the band the label records
    (`None` only where no band was recorded). Deliberately carries none of the
    fields `CT-REVIEW-07` forbids — no confidence, no narrative, no system-side
    points."""

    label_id: str
    label_type: str
    saw_system_output: int
    routing: str
    origin: str
    evaluation_mode: str
    review_seconds: float
    system_band: str | None
    teacher_band: str | None
    actor: str
    timestamp: str
    #: ``None`` on a blind label (#111): the flow that produced it cannot reach
    #: a score row — that is the guarantee — so there is no score id to name.
    score_id: str | None
    criterion_id: str
    #: ``None`` on a blind label: it is not a queue action, and `CT-REVIEW-08`'s
    #: parity clause compares queue paths with queue paths.
    review_queue_action: str | None
    new_points: float | None
    #: Whether this label was one member of a group action (`CT-REVIEW-13`'s
    #: per-member count): service bookkeeping, deliberately not one of the
    #: seven indistinguishability fields the differential reads, and not one
    #: of the durable columns — the share it feeds is a session figure.
    via_group: bool = False


@dataclass(frozen=True)
class CriterionOverrideRank:
    """One criterion's row in the criteria-form ranking — the mirror of
    ``aeh.agg.CriterionEscalationRank`` (`CT-STATS-09`'s consumer differential):
    ``override_rate`` is None exactly when there was no figure to give; a
    genuine zero keeps its zero and its ``no_data=False``."""

    criterion_id: str
    override_rate: float | None
    no_data: bool


@dataclass(frozen=True)
class SupersededScore:
    """What ``escalate`` returns (`CT-REVIEW-15`'s induced race): the score id and
    the version every queue built before the escalation now carries stale."""

    score_id: str
    version: int


@dataclass(frozen=True)
class CounterEmission:
    """One observability emission (`CT-REVIEW-18`'s seam 4 surface): when it
    fired, which counters it carried, and their values. The shown/flagged pair
    travels in ONE emission by construction — the build emits them together, or
    not at all — which is what the pairing assertion reads."""

    at: str
    names: tuple[str, ...]
    values: Mapping[str, Any]


@dataclass(frozen=True)
class ReviewAlert:
    """One fired alert (`CT-REVIEW-18`'s Alert). ``name`` is the stable
    identifier the contract reads; the criterion and its administration
    sequence say what the pattern is in."""

    name: str
    criterion_id: str
    consecutive_administrations: int
    administrations: tuple[str, ...]


@dataclass(frozen=True)
class QueryPlan:
    """The admission query, as a plan (`CT-REVIEW-05`'s reachability surface):
    the routing values the queue's queries read over, the evaluation mode they
    gate on, and the origins they can never reach. This is the plan the queue
    runs — ``_admitted`` is the one predicate the in-memory filter executes
    and the store form runs on every fetched row — not a description of one
    fixture's outcome."""

    routing_values: tuple[str, ...]
    evaluation_modes: tuple[str, ...]
    excluded_origins: tuple[str, ...]


@dataclass(frozen=True)
class WriteRecord:
    """One write a review action made, as ``write_audit`` reports it
    (`CT-REVIEW-06` reads the indirection from the write side rather than from
    the resulting counts). ``table`` names the store table the write lands on —
    ``criterion_score`` for the reduction through the score row, ``label`` for
    the label itself; nothing this module writes is ever named on a grade
    table. In the in-memory service the writes land on the service's own state
    and each record names the table that state stands in for; #110's store
    writes keep the same tables."""

    table: str
    score_id: str
    detail: str = ""


@dataclass(frozen=True)
class BlindItem:
    """One blind-flow draw unit (#111): the identity a judgement is about, and
    nothing else. `CT-REVIEW-09` words its clause as *reachability* — the
    system's output must be structurally absent from what the teacher answers
    on, not merely unrendered — so the item carries the three fields the flow
    needs to pose the question and no field a score row could occupy, the same
    boundary-as-the-type reading `aeh.synth`'s ``L2Request`` takes. Frozen and
    hashable: the refs are the keys of a submission's ``bands`` mapping."""

    submission_id: str
    criterion_id: str
    evaluation_mode: str


@dataclass(frozen=True)
class BlindSession:
    """One blind sample sitting (#111): the drawn refs, and the two reads
    `CT-REVIEW-09` asserts against. ``readable_tables()`` is the query-level
    guarantee — ``submission`` and ``criterion`` only, per §3.15's Data flow
    paragraph, and never ``criterion_score``; ``available_data()`` is what the
    session holds, over which the value-level sweep runs. The session carries
    no attribute a prefetched score row could hide behind (`FR-REVIEW-11`):
    unreachability is a property of the type, not of the template."""

    session_id: str
    run_id: str
    items: tuple[BlindItem, ...]

    def readable_tables(self) -> frozenset[str]:
        """The tables this session's queries read: the two §3.15's Data flow
        paragraph permits, and nothing else — asserted by set equality and by
        the named absence of ``criterion_score``."""
        return frozenset({"submission", "criterion"})

    def available_data(self) -> dict[str, Any]:
        """Everything the session can reach before submission, as plain data:
        the identity fields of the drawn refs. No band, no points, no
        narrative — the value-level probe walks this structure recursively, so
        it is complete by construction."""
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "submissions": tuple(sorted({item.submission_id for item in self.items})),
            "criteria": tuple(sorted({item.criterion_id for item in self.items})),
            "evaluation_modes": tuple(sorted({item.evaluation_mode for item in self.items})),
            "items": self.items,
        }


@dataclass(frozen=True)
class SubmissionGrade:
    """One complete final grade as the student would receive it
    (`FR-REVIEW-14`'s whole-grade sample): the submission's auto-accepted bands
    per criterion and the points those bands map to. ``rendered_as_student_sees_it``
    is the clause's own marker — the sample shows the grade, not the system's
    internal view of it."""

    submission_id: str
    criterion_bands: Mapping[str, str]
    points: float
    rendered_as_student_sees_it: bool = True


@dataclass(frozen=True)
class BlindSampleSkipReport:
    """What a skipped blind sample reports (`FR-REVIEW-13`): the absence, and
    nothing in its place. ``reported`` is the honesty half — a blank where a
    figure belongs is the finding, not a gap to fill — and ``current_figure``
    is ``None`` by construction: a previous administration's figure presented
    as current is RISK-08 arriving through the back door."""

    reported: bool
    message: str
    current_figure: float | None = None


@dataclass(frozen=True)
class ResidualReport:
    """What ``end_session``/``close_run`` return (`FR-REVIEW-08`'s two
    vanishing moments): the residual as the moment leaves it. ``state`` is the
    mark the residual persists in; ``finalized`` and ``backfilled`` name rows
    the moment wrote into a resolved state or invented a label for — empty by
    construction, because the moment writes nothing, and the fields exist so a
    later change that does write one has to name it there rather than in the
    silence the clause forbids. ``grades_delivered``/``grades_finalized`` are
    #111's (`FR-REVIEW-13`): skipping the blind sample has exactly one
    consequence — no new validation evidence — and these two are the assertion
    that the student's marks did not hear about it; ``True`` by construction,
    because nothing here delivers, blocks or finalizes a grade."""

    run_id: str
    moment: str
    residual_provisional: int
    state: str
    finalized: tuple[str, ...] = ()
    backfilled: tuple[str, ...] = ()
    grades_delivered: bool = True
    grades_finalized: bool = True


# --- the write set (CT-REVIEW-14) --------------------------------------------------------------------


def write_fields() -> tuple[str, ...]:
    """Every field this module writes (`CT-REVIEW-14`'s write set): the label's
    own fields — `FR-REVIEW-09`'s eight plus `NFR-REVIEW-03`'s attribution and
    the identity fields a differential reads — the action that produced it, and
    the field the reduction writes on the score row, the review state
    `FR-REVIEW-08` disciplines.

    The declaration is the module's write surface, not a survey of today's
    writes: a field added to a label or to the reduction must appear here, and
    must never appear in a scoring prompt's assembly — `CT-REVIEW-14` asserts
    the intersection with every prompt field empty, which holds for prompts
    nobody has written yet."""
    return (
        "label_id",
        "label_type",
        "saw_system_output",
        "routing",
        "origin",
        "evaluation_mode",
        "review_seconds",
        "system_band",
        "teacher_band",
        "actor",
        "timestamp",
        "score_id",
        "criterion_id",
        "review_queue_action",
        "new_points",
        "state",
    )


# --- the admitted population and the ranking --------------------------------------------------------

#: The teacher's population, by routing (`CT-AGG-06`): ``queued`` — the
#: panel-routed work — and ``provisional`` — the single-judge fallback and the
#: breaker refusal, which route identically and are told apart by state alone
#: (`CT-AGG-07`'s consumer differential). ``auto`` never arrives here
#: (deterministic work grades itself), and ``triage`` is the operator's queue,
#: not the teacher's.
_ADVISORY_ROUTINGS = ("queued", "provisional")
#: `FR-REVIEW-06` (`CT-DET-06`): the exclusion is enforced from this column.
_JUDGED_MODE = "judged"
#: `FR-REVIEW-07`'s never-rendered origins: quarantine, the blind sample, and
#: the random arm — the arm is the only unbiased comparison RISK-07 has, and it
#: spends compute, never teacher minutes (`CT-REVIEW-05`).
_EXCLUDED_ORIGINS = frozenset({"quarantine", "blind_sample", "random_arm"})
#: `FR-REVIEW-08`'s residual mark: an item nobody looked at is provisional and
#: unreviewed, and it says so. ``aeh.agg`` writes the mark when it routes the
#: row; this module only ever leaves it alone — ``end_session``/``close_run``
#: persist the residual by never touching it.
_RESIDUAL_STATE = "provisional_unreviewed"

#: §3.15's ``act`` action domain. ``skip`` is an action but not a label type —
#: a skipped item stays residual (`CT-REVIEW-06`).
_ACTIONS = ("accept", "edit", "override", "skip")

#: `CT-REVIEW-20`'s exact Phase 1 grouping signature: two items differing in any
#: of these five components are not grouped, even when semantically identical.
SIGNATURE_COMPONENTS: tuple[str, ...] = (
    "proposed_band",
    "spans_verified",
    "evidence_present",
    "sufficiency_flag",
    "ocr_overlap_risk",
)


def _signature_of(row: Any) -> dict[str, Any]:
    """The five-component signature of one row (`CT-REVIEW-20`), as a mapping
    keyed by the declared component names."""
    return {component: getattr(row, component) for component in SIGNATURE_COMPONENTS}


def _group_key(row: Any) -> tuple:
    """Two rows group only when they share a criterion *and* the signature."""
    signature = _signature_of(row)
    return (str(getattr(row, "criterion_id", "")),) + tuple(
        signature[component] for component in SIGNATURE_COMPONENTS
    )


def _admitted(rows: Iterable[Any]) -> list[Any]:
    """The rows the queue may render: the teacher's population by routing and
    mode (`CT-AGG-06`, `FR-REVIEW-06/-07`), minus the never-rendered origins
    (`FR-REVIEW-07`), and only work still awaiting it (`CT-REVIEW-05`).

    The state column rides through to the presentation rather than gating
    admission: `CT-AGG-07` binds consumers to surface ``ungradeable_by_panel``
    rather than treat it as an ordinary provisional, and a state gate would
    hide exactly the row that clause names — both of the c07 differential's
    rows route ``provisional``, one state apart, and the queue must present
    them differently."""
    return [
        row
        for row in rows
        if getattr(row, "routing", None) in _ADVISORY_ROUTINGS
        and getattr(row, "evaluation_mode", None) == _JUDGED_MODE
        and getattr(row, "origin", None) not in _EXCLUDED_ORIGINS
    ]


def _score_id_of(row: Any) -> str:
    return str(getattr(row, "score_id"))


def _est_seconds_of(row: Any, default: float) -> float:
    """The row's cost estimate, or the default when it carries none (`FR-REVIEW-16`;
    a missing or non-positive estimate is missing data, not a free item)."""
    raw = getattr(row, "est_seconds", None)
    if raw is None:
        return default
    value = float(raw)
    return default if value <= 0 else value


def _override_rate_of(row: Any, knobs: Mapping[str, float]) -> float:
    """The criterion's measured override rate — or the no-data default
    (`CT-STATS-09`: a criterion nobody has reviewed is not a criterion nobody
    disagrees with, so no data is not read as a zero)."""
    rate = getattr(row, "historical_override_rate", None)
    if rate is None:
        return knobs["override_rate_no_data"]
    return float(rate)


def _p_error(row: Any, knobs: Mapping[str, float]) -> float:
    """P(score wrong) from the four observable signals (`FR-REVIEW-03`), equal
    weights, integrity normalized by its cap. ``self_confidence`` is unread (R22)."""
    integrity = min(
        float(getattr(row, "adverse_integrity_signals", 0) or 0),
        knobs["integrity_signal_cap"],
    )
    return (
        knobs["panel_spread_weight"] * float(getattr(row, "panel_spread", 0.0) or 0.0)
        + knobs["integrity_signal_weight"] * (integrity / knobs["integrity_signal_cap"])
        + knobs["transcription_overlap_weight"]
        * float(getattr(row, "transcription_overlap", 0.0) or 0.0)
        + knobs["override_rate_weight"] * _override_rate_of(row, knobs)
    )


def _impact_of(row: Any, knobs: Mapping[str, float]) -> float:
    """The criterion's share of the final grade, weighted by boundary proximity."""
    weight = float(getattr(row, "criterion_weight", 0.0) or 0.0)
    delta = float(getattr(row, "grade_boundary_delta", 0.0) or 0.0)
    proximity = 1.0 / (1.0 + abs(delta) / knobs["boundary_half_width"])
    return weight * proximity


def _expected_value(row: Any, knobs: Mapping[str, float]) -> float:
    """`FR-REVIEW-03`'s score: ``(P(score wrong) × impact) / est_seconds``."""
    est = _est_seconds_of(row, knobs["default_est_seconds"])
    return (_p_error(row, knobs) * _impact_of(row, knobs)) / est


def _calibration_knobs() -> dict[str, float]:
    """The calibration knobs for one build, env-gated at call time (seam 3).
    Invalid overrides refuse rather than fall back, so a typo cannot silently
    take the production number."""
    return {
        "panel_spread_weight": _env_float(
            "AEH_REVIEW_PANEL_SPREAD_WEIGHT", REVIEW_PANEL_SPREAD_WEIGHT,
            low=_WEIGHT_LOW, high=_WEIGHT_HIGH,
        ),
        "integrity_signal_weight": _env_float(
            "AEH_REVIEW_INTEGRITY_SIGNAL_WEIGHT", REVIEW_INTEGRITY_SIGNAL_WEIGHT,
            low=_WEIGHT_LOW, high=_WEIGHT_HIGH,
        ),
        "transcription_overlap_weight": _env_float(
            "AEH_REVIEW_TRANSCRIPTION_OVERLAP_WEIGHT", REVIEW_TRANSCRIPTION_OVERLAP_WEIGHT,
            low=_WEIGHT_LOW, high=_WEIGHT_HIGH,
        ),
        "override_rate_weight": _env_float(
            "AEH_REVIEW_OVERRIDE_RATE_WEIGHT", REVIEW_OVERRIDE_RATE_WEIGHT,
            low=_WEIGHT_LOW, high=_WEIGHT_HIGH,
        ),
        "integrity_signal_cap": _env_float(
            "AEH_REVIEW_INTEGRITY_SIGNAL_CAP", float(REVIEW_INTEGRITY_SIGNAL_CAP),
            low=1.0, high=100.0,
        ),
        "boundary_half_width": _env_float(
            "AEH_REVIEW_BOUNDARY_HALF_WIDTH", REVIEW_BOUNDARY_HALF_WIDTH,
            low=1e-06, high=1e06,
        ),
        "override_rate_no_data": _env_float(
            "AEH_REVIEW_OVERRIDE_RATE_NO_DATA", REVIEW_OVERRIDE_RATE_NO_DATA,
            low=0.0, high=1.0,
        ),
        "default_est_seconds": _env_float(
            "AEH_REVIEW_DEFAULT_EST_SECONDS", REVIEW_DEFAULT_EST_SECONDS,
            low=1.0, high=3600.0,
        ),
    }


def _env_float(name: str, default: float, *, low: float, high: float) -> float:
    """One float environment knob, read at call time (``orch._env_float``'s shape).

    Absent or blank takes the default; an unparseable value or one outside
    ``[low, high]`` raises rather than falling back — a typo'd override silently
    taking the production value is the phantom-bug shape the seam exists to
    prevent, and a clamped misconfiguration would BE the bug.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ReviewError(f"{name}={raw!r} is not a number") from exc
    if value < low or value > high:
        raise ReviewError(f"{name}={raw!r} is outside [{low}, {high}]")
    return value


def _resolve_knob(explicit: Any, config: Any, name: str, default: Any) -> Any:
    """One §3.15 knob: keyword-injected value, then ``config`` attribute, then
    the module constant (``aeh.agg._escalation_knob``'s reading: the policy
    reads no configuration beyond what the call passes)."""
    if explicit is not None:
        return explicit
    if config is not None:
        attr = getattr(config, name, None)
        if attr is not None:
            return attr
    return default


# --- items and groups -------------------------------------------------------------------------------


def _itemize(row: Any, knobs: Mapping[str, float]) -> ReviewItem:
    """One score row as the queue presents it (§3.15's wire shape). The fields
    the row does not carry stay None/empty: the teacher's view is filled by
    whoever has the package context, and the queue does not invent one."""
    return ReviewItem(
        score_id=_score_id_of(row),
        criterion_id=str(getattr(row, "criterion_id", "") or ""),
        submission_id=str(getattr(row, "submission_id", "") or ""),
        version=int(getattr(row, "version", 1) or 1),
        state=getattr(row, "state", None),
        proposed_band=getattr(row, "proposed_band", None),
        band_options=tuple(getattr(row, "band_options", ()) or ()),
        proposed_points=_opt_float(getattr(row, "proposed_points", None)),
        max_points=_opt_float(getattr(row, "max_points", None)),
        narrative=getattr(row, "narrative", None),
        evidence_spans=tuple(getattr(row, "evidence_spans", ()) or ()),
        reason=str(getattr(row, "reason", None) or "flagged for review"),
        est_seconds=_est_seconds_of(row, knobs["default_est_seconds"]),
        package_version_id=getattr(row, "package_version_id", None),
        grade_boundary_delta=float(getattr(row, "grade_boundary_delta", 0.0) or 0.0),
        expected_value=_expected_value(row, knobs),
        scoring_model=getattr(row, "scoring_model", None),
    )


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _ranked_rows(rows: Sequence[Any], knobs: Mapping[str, float]) -> list[Any]:
    """The rows ranked best-first: expected value per review second, holistic
    first at ties (`FR-AGG-06`), stable otherwise (`NFR-REVIEW-02`)."""
    return sorted(
        rows,
        key=lambda row: (
            -_expected_value(row, knobs),
            0 if getattr(row, "scoring_model", None) == "holistic" else 1,
        ),
    )


def _group_identical(
    ranked_rows: Sequence[Any], knobs: Mapping[str, float]
) -> tuple[list[ReviewGroup], list[ReviewItem]]:
    """Collapse signature-identical rows into group entries (`CT-REVIEW-20`'s
    exact Phase 1 rule): same criterion, same band, same four integrity
    signals. Groups form at two or more members; singletons stay per-item
    entries. Groups rank above per-item entries (`FR-REVIEW-05`) and are
    ordered among themselves by expected value."""
    items = [(_itemize(row, knobs), row) for row in ranked_rows]
    buckets: dict[tuple, list[ReviewItem]] = {}
    signatures: dict[tuple, dict[str, Any]] = {}
    for item, row in items:
        key = _group_key(row)
        buckets.setdefault(key, []).append(item)
        signatures.setdefault(key, _signature_of(row))

    groups: list[ReviewGroup] = []
    used: set[str] = set()
    for key, members in buckets.items():
        if len(members) < 2:
            continue
        first = members[0]
        est = max(member.est_seconds for member in members)
        # Σ p×impact = Σ expected_value × est_seconds, per member.
        numerator = sum(member.expected_value * member.est_seconds for member in members)
        groups.append(
            ReviewGroup(
                members=tuple(members),
                signature=signatures[key],
                criterion_id=first.criterion_id,
                proposed_band=str(first.proposed_band or ""),
                est_seconds=est,
                expected_value=numerator / est,
                reason=first.reason,
            )
        )
        used.update(member.score_id for member in members)

    groups.sort(key=lambda group: -group.expected_value)
    leftovers = [item for item, _ in items if item.score_id not in used]
    return groups, leftovers


def _fill_to_budget(entries: Sequence[Any], available_seconds: float) -> list[Any]:
    """Greedy fill in entry order: take every entry that fits, pass over one
    that does not, never reorder (`NFR-REVIEW-02`/`-05`). Over a non-empty
    entry list the queue never shows nothing: when no entry fits, the single
    top-ranked entry is shown and the residual states the truth (the recorded
    5-minute interpretation)."""
    shown: list[Any] = []
    spent = 0.0
    for entry in entries:
        if spent + entry.est_seconds <= available_seconds:
            shown.append(entry)
            spent += entry.est_seconds
    if not shown and entries:
        shown.append(entries[0])
    return shown


def _items_shown_count(shown: Iterable[Any]) -> int:
    """How many review *items* a shown list covers — a group counts its members
    (`CT-REVIEW-04`'s arithmetic is about items, not entries)."""
    total = 0
    for entry in shown:
        members = getattr(entry, "members", None)
        total += len(members) if members is not None else 1
    return total


# --- the ranking, at both of its declared shapes ----------------------------------------------------


def rank_queue_items(items: Sequence[Any] | None = None, *, criteria: Any = None) -> Any:
    """The ranking, at both of its declared shapes.

    ``items`` (the ``#95 TS-36`` limb): review-queue items carrying
    ``expected_value`` and ``scoring_model`` — ordered best-first, expected
    value dominant, holistic ranking above atomic at equal value, stable
    otherwise. The caller's ``expected_value`` is taken as given: this is the
    queue's ordering rule over items whose value some producer has stated.
    Stored score rows (mappings, as ``SELECT *`` hands them back) are
    normalized to items first, honest defaults for the columns the store does
    not carry — the c16 consumer sweep's declared assumption, that the ranker
    takes the stored rows and returns the ranked queue.

    ``criteria`` (the ``CT-STATS-09`` consumer limb): a mapping of criterion ids
    to override-history payloads — mirrors
    ``aeh.agg.rank_criteria_for_escalation`` exactly, so both consumers rank no
    data first and a measured zero by its rate. Returns
    ``CriterionOverrideRank`` rows.
    """
    if criteria is not None:
        return _rank_criteria(criteria)
    if items is None:
        raise ReviewError(
            "rank_queue_items takes the items to rank, or criteria= for the criteria form"
        )
    knobs = _calibration_knobs()
    normalized: list[Any] = []
    for item in items:
        if hasattr(item, "expected_value"):
            normalized.append(item)
            continue
        if not hasattr(item, "keys"):
            raise ReviewError(
                "rank_queue_items takes review items carrying expected_value, or "
                "stored score rows as mappings; "
                f"{type(item).__name__} carries neither"
            )
        normalized.append(
            _itemize(
                _StoredScoreRow(_row_mapping(item), knobs["default_est_seconds"]),
                knobs,
            )
        )
    return sorted(
        normalized,
        key=lambda ranked: (
            -float(ranked.expected_value),
            0 if getattr(ranked, "scoring_model", None) == "holistic" else 1,
        ),
    )


def _rank_criteria(criteria: Any) -> tuple[CriterionOverrideRank, ...]:
    """The criteria form — ``aeh.agg.rank_criteria_for_escalation``'s semantics,
    mirrored so both consumers answer `CT-STATS-09` the same way: no data
    first, then override rate descending, ties keeping the caller's order."""
    ranks: list[tuple[tuple[int, float], CriterionOverrideRank]] = []
    for criterion_id, payload in dict(criteria).items():
        if isinstance(payload, dict):
            override_rate = payload.get("override_rate")
            reviewed = payload.get("reviewed")
        else:
            override_rate = getattr(payload, "override_rate", None)
            reviewed = getattr(payload, "reviewed", None)
        no_data = override_rate is None or reviewed is False
        key = (0, 0.0) if no_data else (1, -float(override_rate))
        ranks.append(
            (
                key,
                CriterionOverrideRank(
                    criterion_id=str(criterion_id),
                    override_rate=None if override_rate is None else float(override_rate),
                    no_data=no_data,
                ),
            )
        )
    ranks.sort(key=lambda entry: entry[0])
    return tuple(rank for _, rank in ranks)


# --- the service ------------------------------------------------------------------------------------


class ReviewService:
    """The review service: builds the queue, ranks it, writes labels.

    Constructed by ``build_review`` (rung 0/1, over score rows in memory) or
    ``open_review`` (rung 2, over a stored run). The three §3.15 members #108
    owns are here with #110's label store (``label``, ``points_for_band``,
    ``edit_views``, ``act_from_view`` and the observability surface), plus
    #109's admission plan, write audit and residual reads (``admission_query``,
    ``write_audit``, ``scores``, ``labels_for``, ``end_session``/``close_run``)
    and #111's two samples (``blind_sample``/``submit_blind``,
    ``whole_grade_sample``) with the skip (``skip_blind_sample``) and the
    rendered blind flow (``render_blind_flow``).
    """

    def __init__(
        self,
        rows: Sequence[Any],
        *,
        actor: str = "teacher",
        clock: Callable[[], str] | None = None,
        catalog: Any = None,
        config: Any = None,
        blind_reserve_minutes: int | None = None,
        blind_n: int | None = None,
        whole_grade_n: int | None = None,
        default_budget_minutes: int | None = None,
        seed: int | None = None,
        administration_id: str | None = None,
        previous_administration: Any = None,
        store: Any = None,
    ) -> None:
        self._rows = tuple(rows)
        self._rows_by_id = {_score_id_of(row): row for row in self._rows}
        self._actor_name = actor
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        # The points route (`FR-REVIEW-10`): a catalog attached at construction
        # is read per criterion; without one the declared default scale below
        # is read through the same mapping function (see the interpretations).
        self._catalog = catalog
        self._blind_reserve = blind_reserve_minutes
        self._blind_n = blind_n
        self._whole_grade_n = whole_grade_n
        self._default_budget = default_budget_minutes
        # #111's sampling: one seed per service, both samples draw from it; the
        # administration identity rides along for attribution and for the skip
        # report's context. `previous_administration` is held, never read: the
        # carry-forward RISK-08 forbids is a *value* a skip report could
        # present, and holding the earlier administration's result without
        # reading it is what makes `current_figure=None` an honest None.
        self._seed = seed
        self._administration_id = administration_id
        self._previous_administration = previous_administration
        self._store = store
        self._cohort_ids: tuple[str, ...] = ()
        self._labels: list[LabelRecord] = []
        self._labels_by_id: dict[str, LabelRecord] = {}
        self._audit: list[WriteRecord] = []
        # -- observability bookkeeping (CT-REVIEW-18) -----------------------------------------------
        self._current_run_id: str | None = None
        self._run_labels: dict[str, list[LabelRecord]] = {}
        self._builds: dict[str, dict[str, Any]] = {}
        self._emissions: dict[str, list[CounterEmission]] = {}
        self._exhaustions: dict[str, list[str]] = {}
        self._acted: set[str] = set()
        self._versions: dict[str, int] = {}
        # -- #111's blind-flow bookkeeping ------------------------------------------------------------
        self._blind_sessions: dict[str, BlindSession] = {}
        self._blind_submitted: set[str] = set()
        self._blind_drawn: dict[str, int] = {}
        self._blind_answered: dict[str, int] = {}
        self._skipped_runs: set[str] = set()
        self._whole_grade_draws = 0

    # -- the queue -----------------------------------------------------------------------------------

    def build_queue(self, run_id: str, budget_minutes: int) -> ReviewQueue:
        """Build the minute-budgeted queue (`FR-REVIEW-01`).

        Stage order is the contract, not an implementation detail
        (`CT-REVIEW-02`): the blind reserve is subtracted **before** anything is
        ranked, and the trace says so. The queue fills in rank order, takes what
        fits, and states what is left over — and never bills its own build
        seconds to the teacher (`CT-REVIEW-16`).
        """
        started = perf_counter()
        trace: list[BuildEvent] = []
        knobs = _calibration_knobs()

        admitted = self._admitted_rows()
        flagged_total = len(admitted)
        trace.append(BuildEvent("count_flagged", f"{flagged_total} queued judged rows"))

        reserve = min(self._blind_reserve, budget_minutes)
        available_seconds = max(budget_minutes - reserve, 0) * 60
        trace.append(
            BuildEvent(
                "reserve_blind_minutes",
                f"{reserve} of {budget_minutes} minutes reserved; "
                f"{available_seconds}s spendable",
            )
        )

        ranked = _ranked_rows(admitted, knobs)
        trace.append(BuildEvent("rank_items", f"{len(ranked)} items ranked"))

        groups, leftovers = _group_identical(ranked, knobs)
        trace.append(
            BuildEvent(
                "group_identical_signatures",
                f"{len(groups)} groups over "
                f"{sum(len(group.members) for group in groups)} items",
            )
        )

        shown = _fill_to_budget([*groups, *leftovers], available_seconds)
        trace.append(
            BuildEvent(
                "truncate_to_budget", f"{len(shown)} entries shown within {available_seconds}s"
            )
        )

        residual = flagged_total - _items_shown_count(shown)
        trace.append(
            BuildEvent(
                "compute_residual", f"{residual} of {flagged_total} remain provisional"
            )
        )

        # CT-REVIEW-18's bookkeeping: this build is the run's queue as it now
        # stands, and its honesty pair is emitted together or not at all —
        # which is the shape the pairing assertion reads.
        self._current_run_id = run_id
        self._builds[run_id] = {
            "shown_items": _items_shown_count(shown),
            "flagged": flagged_total,
            "est_seconds": tuple(entry.est_seconds for entry in shown),
        }
        self._record_emission(
            run_id,
            ("review_items_shown", "review_items_flagged"),
            {
                "review_items_shown": _items_shown_count(shown),
                "review_items_flagged": flagged_total,
            },
        )

        return ReviewQueue(
            run_id=run_id,
            budget_minutes=budget_minutes,
            reserved_for_blind_minutes=reserve,
            flagged_total=flagged_total,
            shown=tuple(shown),
            residual_provisional=residual,
            groups=tuple(groups),
            build_seconds=perf_counter() - started,
            build_trace=tuple(trace),
        )

    def queue(
        self, run_id: str = "run-1", budget_minutes: int | None = None
    ) -> tuple["ReviewItem | ReviewGroup", ...]:
        """The built queue as its consumer reads it (`§3.15`): the shown
        entries — signature groups collapsed, singletons per-item — in
        presentation order.

        ``build_review(store).queue()`` is the store form's declared read
        (the c05/c07/c09 consumer limbs' shape): no run id and no budget
        arrive, so the module's default budget governs. The residual header
        and the per-stage trace stay on ``build_queue`` — this is the queue's
        face, not its bookkeeping."""
        budget = (
            int(budget_minutes)
            if budget_minutes is not None
            else int(self._default_budget or REVIEW_DEFAULT_BUDGET_MINUTES)
        )
        return self.build_queue(run_id, budget).shown

    def rank_queue_items(self, run_id: str) -> tuple[ReviewItem, ...]:
        """The ranking, separable from the queue (`FR-REVIEW-03`): every admitted
        item, best-first, each carrying its ``expected_value`` — the ranking's
        full output, without the budget's truncation."""
        knobs = _calibration_knobs()
        admitted = self._admitted_rows()
        ranked = _ranked_rows(admitted, knobs)
        return tuple(_itemize(row, knobs) for row in ranked)

    def group_signature(self, row: Any) -> dict[str, Any]:
        """The exact Phase 1 grouping signature (`CT-REVIEW-20`): the five
        declared components and nothing else — a rule with fewer components
        groups items the clause says are different; one with more never groups
        anything."""
        return _signature_of(row)

    def admission_query(self, run_id: str = "run-1") -> QueryPlan:
        """The admission query as a plan, not an observation (`CT-REVIEW-05`'s
        reachability clause): the routing values the queue's queries read over,
        the evaluation mode they gate on, and the origins they can never reach.

        ``_admitted`` is the single predicate the plan restates — the in-memory
        filter executes it, and the store form runs it on every fetched row
        beneath its WHERE clause — so the plan cannot drift from what the
        service runs. The store's routing narrow is a declared SQL literal
        (SEC-15 permits no runtime assembly), matching this tuple by
        transcription rather than by construction; the mode and origin halves
        ride the predicate. The routings are both of the teacher's (`CT-AGG-06`'s
        ``queued``, plus the provisional family whose rows `CT-AGG-07` binds
        this module to surface); ``triage``, the operator's queue, is reachable
        by neither. The mode is gated on the evaluation-mode column
        (`FR-REVIEW-06`, `CT-DET-06`), not by convention.

        ``run_id`` is bookkeeping: the plan is the same over every run the
        service carries, and is stated for the run the caller names."""
        return QueryPlan(
            routing_values=tuple(_ADVISORY_ROUTINGS),
            evaluation_modes=(_JUDGED_MODE,),
            excluded_origins=tuple(sorted(_EXCLUDED_ORIGINS)),
        )

    # -- actions -------------------------------------------------------------------------------------

    def act(
        self,
        item: Any,
        action: str,
        new_band: str | None = None,
        review_seconds: float = 0,
    ) -> str | None:
        """One teacher decision on one queue item (§3.15's Protocol member).

        ``accept`` keeps the proposed band; ``edit``/``override`` name a new one
        — an edit without a band is refused, because there is nowhere to put a
        number (`FR-REVIEW-10`); ``skip`` writes no label and leaves the item
        residual (`CT-REVIEW-06`). Acting on a superseded score is refused with
        a refresh message (`CT-REVIEW-15`). Returns the label id, or None.

        Every write the action makes is audited (`CT-REVIEW-06`): a
        ``criterion_score`` record for the reduction through the score row and
        a ``label`` record for the label itself — a ``skip`` writes nothing at
        all."""
        if action not in _ACTIONS:
            raise ValueError(f"{action!r} is not a review action; one of {_ACTIONS}")
        if action == "skip":
            return None
        if action in ("edit", "override") and new_band is None:
            raise ValueError("an edit names a band")
        item = self._as_item(item)
        self._check_not_stale(item)
        label = self._write_label(
            item,
            label_type=action,
            teacher_band=item.proposed_band if action == "accept" else new_band,
            review_seconds=review_seconds,
            review_queue_action=action,
        )
        self._record_writes(item, action, label)
        self._acted.add(item.score_id)
        self._record_action_emission([label])
        return label.label_id

    def act_on_group(self, group: Any, band: str, review_seconds: float = 0) -> list[str]:
        """One band decision over a whole group (§3.15's Protocol member): one
        label per member (`CT-REVIEW-13`) — a single group label would
        under-weight bulk decisions in every agreement figure — each carrying
        the member's own identity and the per-member share of the time."""
        members = tuple(getattr(group, "members"))
        if not members:
            return []
        per_member = review_seconds / len(members)
        label_ids: list[str] = []
        labels: list[LabelRecord] = []
        for member in members:
            self._check_not_stale(member)
            action = "accept" if band == member.proposed_band else "edit"
            label = self._write_label(
                member,
                label_type=action,
                teacher_band=band,
                review_seconds=per_member,
                review_queue_action=action,
                via_group=True,
            )
            self._record_writes(member, action, label)
            self._acted.add(member.score_id)
            labels.append(label)
            label_ids.append(label.label_id)
        self._record_action_emission(labels)
        return label_ids

    # -- the label store (FR-REVIEW-09 / FR-REVIEW-15, #110) ------------------------------------------

    def label(self, label_id: str) -> LabelRecord:
        """One label this service wrote, by id (`CT-REVIEW-07`'s read back)."""
        label = self._labels_by_id.get(label_id)
        if label is None:
            raise ReviewError(
                f"no label {label_id!r} in this service's label store; the ids "
                "act()/act_on_group()/act_from_view() returned are the store's ids"
            )
        return label

    def _points_for_band(
        self,
        package_version_id: str | None = None,
        criterion_id: str | None = None,
        band: str | None = None,
    ) -> float:
        """Band → points, through the one pinned mapping (`FR-REVIEW-10`). With
        a ``catalog=`` attached the criterion's own pinned table is read
        (``PackageCatalog.points_for_band``); without one, the declared default
        scale (`REVIEW_DEFAULT_BANDS`) is read through the same function —
        never a second table (`NFR-AGG-02`). A band absent from whichever
        table governs refuses (`PackageError`) rather than defaulting to a
        number — but a band whose name exists in both tables is not
        distinguishable without a catalog, so the no-catalog route derives the
        default scale's points for it (the collision hazard is disclosed in
        the module interpretations). ``package_version_id`` is accepted for
        interface parity with the queue item and ignored: the mapping is
        criterion-scoped.
        """
        if band is None:
            raise ReviewError(
                "a score edit is a band selection; there is no band here to map"
            )
        if self._catalog is not None:
            return self._catalog.points_for_band(criterion_id, band)
        from aeh import pkg as _pkg  # lazy: pkg's import graph must not pull review in

        return float(_pkg.points_for_band(REVIEW_DEFAULT_BANDS, band))

    # The public face, aliased to the body above. Deliberately an alias and not
    # a second definition: NFR-AGG-02 keeps the mapping *defined* in exactly
    # one module (aeh.pkg — CT-PKG-05's pinned mapping), and the artifact sweep
    # enforcing it reads the source.
    points_for_band = _points_for_band

    def edit_views(self) -> tuple[str, ...]:
        """The views that display a band and can therefore carry a review
        action (`FR-REVIEW-15`) — enumerable precisely so `CT-REVIEW-12`'s
        parity sweep covers a view added later."""
        return _EDIT_VIEWS

    def act_from_view(
        self,
        item: Any,
        *,
        view: str,
        action: str,
        new_band: str | None = None,
        review_seconds: float = 0,
    ) -> str | None:
        """One teacher decision made outside the budgeted queue (`FR-REVIEW-15`):
        the same action from any view that displays a band. The validation is
        the view's membership — and then the record is `act`'s, by *delegation*,
        not by imitation: an edit made outside the queue runs the same code path
        and so writes the same `review_queue` action and the same label type by
        construction, which is the clause's whole point."""
        if view not in self.edit_views():
            raise ReviewError(
                f"{view!r} is not a view that displays a band; review actions "
                f"are available from {self.edit_views()}"
            )
        return self.act(item, action, new_band=new_band, review_seconds=review_seconds)

    # -- the two samples, and the skip (#111) ---------------------------------------------------------

    def _rng(self, draw_index: int) -> random.Random:
        """One draw's RNG: derived from the service's seed and the draw's
        index, so the same seed reproduces the same *sequence* of draws while
        successive draws on one service differ — a second sitting draws fresh
        refs instead of re-drawing the first's (`CT-REVIEW-11`'s uniformity is
        per draw, and a per-run rate aggregates sittings). A declared seed of
        ``None`` stays entropy-per-draw: an undeclared seed must not silently
        pin every administration to the same sample, which is first-N's defect
        in disguise."""
        if self._seed is None:
            return random.Random()
        # A str seed, not a tuple: Random() accepts only None/int/float/str/
        # bytes/bytearray, and str's version-2 seeding is a sha512 digest, so
        # the derived seed is deterministic across processes, not hash-ordered.
        return random.Random(f"{self._seed}:{draw_index}")

    def blind_sample(self, run_id: str = "run-1", n: int | None = None) -> BlindSession:
        """Draw the blind sample (`FR-REVIEW-12`): 15–25 judged refs at random
        over judged criteria, as one ``BlindSession``. The draw is
        ``self._rng``-seeded ``sample`` over the admitted judged population —
        uniform over the eligible set, reproducible from the service's seed,
        and never first-N (`CT-REVIEW-11`'s distribution case). A pool smaller
        than ``n`` floors the draw at the pool (the interpretations); a request
        outside ``BLIND_SAMPLE_RANGE`` is refused, naming the range.

        A run that recorded its skip refuses to draw: the skip's one
        consequence is the missing evidence, and a draw after a skip would
        make the skip's report false (see ``skip_blind_sample``).

        The refs the session returns carry identity only — that is
        `CT-REVIEW-09`'s whole guarantee, so it is a property of the type
        rather than of the rendering."""
        count = self._blind_n if n is None else int(n)
        low, high = BLIND_SAMPLE_RANGE
        if count < low or count > high:
            raise ValueError(
                f"blind_sample draws {low}-{high} judged refs (FR-REVIEW-12), got n={count}: "
                "the range is the contract, and a draw outside it is refused rather than sized "
                "to whatever the caller asked for"
            )
        if run_id in self._skipped_runs:
            raise ReviewError(
                f"run {run_id!r} skipped its blind sample, so it does not draw one: "
                "a run either draws its sample or skips it. Drawing after a skip would make "
                "the skip's report — no new validation evidence — false, and the report is "
                "the clause's whole content (FR-REVIEW-13)"
            )
        pool: list[BlindItem] = []
        seen: set[tuple[str, str]] = set()
        for row in self._admitted_rows():
            ref = BlindItem(
                submission_id=str(getattr(row, "submission_id", "") or ""),
                criterion_id=str(getattr(row, "criterion_id", "") or ""),
                evaluation_mode=str(getattr(row, "evaluation_mode", "") or ""),
            )
            key = (ref.submission_id, ref.criterion_id)
            if key in seen:
                continue
            seen.add(key)
            pool.append(ref)
        drawn = tuple(
            self._rng(len(self._blind_sessions)).sample(pool, min(count, len(pool)))
        )
        self._blind_drawn[run_id] = self._blind_drawn.get(run_id, 0) + len(drawn)
        session = BlindSession(
            session_id=f"blind-{len(self._blind_sessions) + 1:04d}",
            run_id=run_id,
            items=drawn,
        )
        self._blind_sessions[session.session_id] = session
        return session

    def submit_blind(
        self,
        session_id: str,
        bands: Mapping[BlindItem, str],
        *,
        interrupted: bool = False,
        review_seconds: float = 0,
    ) -> list[str]:
        """Submit a blind sitting's answers (`FR-REVIEW-12`'s collection path,
        `CT-REVIEW-15`'s interrupted half): one ``blind`` label per answered
        ref — ``saw_system_output = 0`` (earned: the session could not reach
        the output, `CT-REVIEW-09` step 4), ``system_band = None``, no
        ``review_queue_action`` — and nothing for a ref the teacher never
        answered. A ref the session never drew is refused: a band for a
        criterion the flow never posed is a judgement nobody made.

        ``interrupted`` records that the sitting ended early; the labels
        written are the answered ones either way, which is the clause in both
        directions. The session submits once — a second submission is refused
        rather than double-written. Returns the label ids in the session's
        draw order."""
        session = self._blind_sessions.get(session_id)
        if session is None:
            raise ReviewError(
                f"no blind session {session_id!r} in this service; the ids "
                "blind_sample() returned are the submission's ids"
            )
        if session_id in self._blind_submitted:
            raise ReviewError(
                f"blind session {session_id!r} was already submitted: a sitting answers once, "
                "and a second submission would double-write the labels an agreement figure "
                "counts"
            )
        drawn = set(session.items)
        unknown = [ref for ref in bands if ref not in drawn]
        if unknown:
            raise ReviewError(
                f"the bands name a ref this session never drew ({unknown[0]!r}): "
                "submit_blind records the criteria the flow posed, and a ref outside the "
                "session is a judgement nobody was asked for"
            )
        labels = [
            self._write_blind_label(
                ref,
                band,
                interrupted=interrupted,
                review_seconds=review_seconds,
            )
            for ref in session.items
            if (band := bands.get(ref)) is not None
        ]
        self._blind_submitted.add(session_id)
        run_id = session.run_id
        self._blind_answered[run_id] = self._blind_answered.get(run_id, 0) + len(labels)
        self._record_action_emission(labels)
        rate = self._blind_rate(run_id)
        self._record_emission(
            run_id, ("blind_completion_rate",), {"blind_completion_rate": rate}
        )
        return [label.label_id for label in labels]

    def whole_grade_sample(
        self, run_id: str = "run-1", n: int | None = None
    ) -> tuple[SubmissionGrade, ...]:
        """Draw the whole-grade sample (`FR-REVIEW-14`): 10–15 complete final
        grades from the auto-accepted population, each as the student would
        receive it. The population is the submissions whose **every** criterion
        row routed ``auto`` — sampling reviewed grades would measure the review,
        not the system, so the restriction is the clause's point
        (`CT-REVIEW-11`'s membership assertion), and a submission holding a
        reviewed criterion is excluded with them: its grade mixes the teacher's
        corrections into what is presented as the system's work, and a partial
        band set presented as a final grade understates it. One grade per
        submission, bands mapped to points through the one pinned mapping (the
        default-policy sum — a package grade policy supersedes it the moment
        one is attached); the offer writes no label. A request outside
        ``WHOLE_GRADE_SAMPLE_RANGE`` is refused, naming the range."""
        count = self._whole_grade_n if n is None else int(n)
        low, high = WHOLE_GRADE_SAMPLE_RANGE
        if count < low or count > high:
            raise ValueError(
                f"whole_grade_sample draws {low}-{high} complete grades (FR-REVIEW-14), got "
                f"n={count}: the range is the contract, refused rather than clamped"
            )
        by_submission: dict[str, list[tuple[str, str]]] = {}
        for submission_id, criterion_id, band in self._auto_grade_population():
            by_submission.setdefault(submission_id, []).append((criterion_id, band))
        candidates = list(by_submission)
        picked = self._rng(self._whole_grade_draws).sample(
            candidates, min(count, len(candidates))
        )
        self._whole_grade_draws += 1
        return tuple(
            SubmissionGrade(
                submission_id=submission_id,
                criterion_bands=dict(by_submission[submission_id]),
                points=float(sum(
                    self._points_for_band(criterion_id=criterion_id, band=band)
                    for criterion_id, band in by_submission[submission_id]
                )),
            )
            for submission_id in picked
        )

    def skip_blind_sample(self, run_id: str = "run-1") -> BlindSampleSkipReport:
        """Record that this administration skips the blind sample
        (`FR-REVIEW-13`): exactly one consequence — no new validation evidence
        for this administration — and the report states the absence rather
        than filling it. Grades deliver and finalize normally
        (``ResidualReport.grades_delivered``/``grades_finalized``); the
        report's ``current_figure`` is ``None``, never a previous
        administration's figure. Idempotent: skipping twice skips once.

        A run that already drew refuses the skip: the draw *is* validation
        evidence, and recording a skip beside it would make the report say
        "no new validation evidence was collected" about a run whose counter
        says otherwise. A run either draws its sample or skips it; the two
        refusals (this one, and ``blind_sample``'s against a skipped run) are
        what keep the report and the evidence in agreement."""
        if self._blind_drawn.get(run_id):
            raise ReviewError(
                f"run {run_id!r} already drew a blind sample "
                f"({self._blind_drawn[run_id]} refs on record): there is no skip to record. "
                "A run either draws its sample or skips it — recording a skip beside a draw "
                "would report 'no new validation evidence' about a run that holds it"
            )
        self._skipped_runs.add(run_id)
        return self.skip_report(run_id)

    def skip_report(self, run_id: str = "run-1") -> BlindSampleSkipReport:
        """A run's skip, read back as the report (`FR-REVIEW-13`): whether the
        sample was skipped, the consequence said in words, and
        ``current_figure = None`` — the honest None, whatever an earlier
        administration produced."""
        skipped = run_id in self._skipped_runs
        if skipped:
            message = (
                "the blind sample was skipped for this administration: no new "
                "validation evidence was collected, so this administration has "
                "no agreement figure of its own — grades deliver and finalize "
                "normally, and no earlier figure is presented in its place"
            )
        else:
            message = (
                "the blind sample was not skipped for this administration, so "
                "there is no absence to report; the run's own evidence speaks "
                "when it exists"
            )
        return BlindSampleSkipReport(reported=skipped, message=message, current_figure=None)

    def render_blind_flow(self, session_id: str) -> str:
        """The blind flow as the teacher sees it (`CT-REVIEW-09` step 2's
        rendered probe): the drawn refs and the fixed band scale, built from
        the session alone. Nothing the system decided can appear here, because
        the session carries nothing the system decided — the render is a
        projection of identity fields, not a template filtering a richer
        object."""
        session = self._blind_sessions.get(session_id)
        if session is None:
            raise ReviewError(
                f"no blind session {session_id!r} in this service; the ids "
                "blind_sample() returned are the render's ids"
            )
        lines = [
            f"Blind validation session {session.session_id} (run {session.run_id})",
            (
                f"{len(session.items)} criteria drawn at random. The system's own "
                "bands are not available in this flow."
            ),
            "",
        ]
        lines.extend(
            f"- submission {ref.submission_id} / criterion {ref.criterion_id}"
            for ref in session.items
        )
        lines.append("")
        lines.append(
            "For each criterion, record the band you judge: "
            + ", ".join(str(band["band"]) for band in REVIEW_DEFAULT_BANDS)
        )
        lines.append("Submit what you answered; an interrupted sitting keeps the answered criteria.")
        return "\n".join(lines)

    def _blind_rate(self, run_id: str) -> float | None:
        """The run's blind completion rate (`CT-REVIEW-18`): answered refs over
        drawn refs, from the service's own bookkeeping. ``None`` for a run
        that never drew — an unmeasured rate, never a silent zero."""
        drawn = self._blind_drawn.get(run_id)
        if not drawn:
            return None
        return self._blind_answered.get(run_id, 0) / drawn

    def _row_for_ref(self, ref: BlindItem) -> Any:
        """The score row a blind ref came from — the *service's* lookup, for
        the label's routing/origin metadata. The session never sees it: the
        guarantee is a property of what the session carries, not of what the
        service's internals hold."""
        for row in self._rows:
            if (
                str(getattr(row, "submission_id", "") or "") == ref.submission_id
                and str(getattr(row, "criterion_id", "") or "") == ref.criterion_id
            ):
                return row
        return None

    def _auto_grade_population(self) -> list[tuple[str, str, str]]:
        """The whole-grade sample's population (`FR-REVIEW-14`): the
        completely auto-accepted submissions, as ``(submission_id,
        criterion_id, band)`` triples — a submission holding any row with
        another routing is excluded with the reviewed ones, because the grade
        presented must be complete and wholly the system's (a partial band set
        shown as the student's final grade understates it; a mixed one shows
        the teacher's corrections as system work). The store form reads them
        through the declared ``select_auto_grades`` statement, whose NOT IN
        guard carries the same restriction — the service's own fetch admits
        only the teacher's routings, so the sample needs its own declared read
        (a ``.query``, never a runtime assembly, SEC-15); the in-memory form
        filters its own rows to the same set."""
        if self._store is not None:
            triples: list[tuple[str, str, str]] = []
            for cohort_id in self._cohort_ids:
                for row in self._store.cohort(cohort_id).query(
                    REVIEW_STATEMENTS["select_auto_grades"]
                ):
                    mapping = _row_mapping(row)
                    submission_id = str(mapping.get("submission_id") or "")
                    criterion_id = str(mapping.get("criterion_id") or "")
                    band = str(mapping.get("band") or "")
                    if submission_id and criterion_id and band:
                        triples.append((submission_id, criterion_id, band))
            return triples
        non_auto: set[str] = set()
        auto_bands: dict[str, list[tuple[str, str]]] = {}
        for row in self._rows:
            submission_id = str(getattr(row, "submission_id", "") or "")
            if not submission_id:
                continue
            if getattr(row, "routing", None) != "auto":
                non_auto.add(submission_id)
                continue
            criterion_id = str(getattr(row, "criterion_id", "") or "")
            band = str(getattr(row, "proposed_band", "") or "")
            if criterion_id and band:
                auto_bands.setdefault(submission_id, []).append((criterion_id, band))
        return [
            (submission_id, criterion_id, band)
            for submission_id, bands in auto_bands.items()
            if submission_id not in non_auto
            for criterion_id, band in bands
        ]

    def _write_blind_label(
        self,
        ref: BlindItem,
        band: str,
        *,
        interrupted: bool,
        review_seconds: float,
    ) -> LabelRecord:
        """One blind label (#111): the same record an action writes, collected
        by the flow that could not see the output. ``score_id`` is ``None`` —
        the flow cannot reach a score row, so there is no score id to name and
        the honest label says so; ``review_queue_action`` is ``None`` — this is
        not a queue action; ``system_band`` is ``None`` and
        ``saw_system_output`` is 0, earned by the session's construction
        (`CT-REVIEW-09` step 4). The band is the teacher's alone; its points
        ride the one pinned mapping (`NFR-AGG-02`). Writes no reduction: the
        row stays flagged — a blind label is evidence about the system, not a
        resolution of it (`CT-REVIEW-06`'s indirection is the queue's)."""
        row = self._row_for_ref(ref)
        label = LabelRecord(
            label_id=f"label-{len(self._labels) + 1:04d}",
            label_type="blind",
            saw_system_output=0,
            routing=str(getattr(row, "routing", "queued") or "queued")
            if row is not None
            else "queued",
            origin=str(getattr(row, "origin", "escalation") or "escalation")
            if row is not None
            else "escalation",
            evaluation_mode=ref.evaluation_mode,
            review_seconds=review_seconds,
            system_band=None,
            teacher_band=band,
            actor=self._actor_name,
            timestamp=self._clock(),
            score_id=None,
            criterion_id=ref.criterion_id,
            review_queue_action=None,
            # The label's points derive from the band through the one pinned
            # mapping (`FR-REVIEW-10`), exactly as a queue label's do — the
            # derivation is the teacher's band's, never the system's.
            new_points=self._points_for_band(criterion_id=ref.criterion_id, band=band),
        )
        self._labels.append(label)
        self._labels_by_id[label.label_id] = label
        run_id = self._attribution_run()
        if run_id is not None:
            self._run_labels.setdefault(run_id, []).append(label)
        if self._store is not None:
            if run_id is None:
                raise ReviewError(
                    "this service holds a store but no run context: build a queue "
                    "for the run (or open the service over exactly one cohort) "
                    "before submitting the blind flow — a label is not attributed "
                    "to an invented run"
                )
            # `ref` itself: `_persist_label` reads the item's `submission_id`,
            # and a BlindItem carries exactly that identity — no ReviewItem is
            # needed, and handing one over would smuggle the score row back
            # into the flow that cannot see it.
            self._persist_label(label, run_id, ref)
        self._audit.append(
            WriteRecord(
                table="label",
                score_id=ref.submission_id,
                detail=(
                    f"blind label {label.label_id}"
                    + (" (interrupted session, answered criteria only)" if interrupted else "")
                ),
            )
        )
        return label

    def observability_counters(self, run_id: str) -> dict[str, Any]:
        """The run's counter surface (`CT-REVIEW-18`): every name in
        ``OBSERVABILITY_COUNTERS`` as a key, with the value the service's own
        bookkeeping supports. ``blind_completion_rate`` is measured from #111's
        blind flow — answered refs over drawn refs for this run — and is
        ``None`` for a run that never drew, which stays an unmeasured rate,
        never a silent zero.
        ``override_rate_by_criterion`` is a per-criterion *count* of
        edit/override labels for now — the denominator a rate divides by (the
        judgments the criterion received) is #115's read over the stored
        labels, and a count is the honest numerator the service itself
        observed; the name is the contract's (`CT-REVIEW-18`'s plan), the
        shape is decided there."""
        builds = self._builds.get(run_id)
        labels = self._run_labels.get(run_id, [])
        drawn = self._blind_drawn.get(run_id)
        if builds is None and not labels and not drawn:
            return {name: None for name in _OBSERVABILITY_COUNTERS}
        est = builds["est_seconds"] if builds else ()
        used = sum(label.review_seconds for label in labels)
        judged = [label for label in labels if label.label_type in ("edit", "override")]
        by_criterion: dict[str, float] = {}
        for label in judged:
            by_criterion[label.criterion_id] = by_criterion.get(label.criterion_id, 0) + 1
        total = len(labels)
        return {
            "review_minutes_used": used / 60,
            "review_items_shown": builds["shown_items"] if builds else 0,
            "review_items_flagged": builds["flagged"] if builds else 0,
            "override_rate_by_criterion": dict(by_criterion),
            "group_action_usage_share": (
                (sum(1 for label in labels if label.via_group) / total) if total else None
            ),
            # #111's blind flow, measured: answered refs over drawn refs for
            # this run; None when the run never drew — an unmeasured rate,
            # never a silent zero.
            "blind_completion_rate": self._blind_rate(run_id),
            "mean_review_seconds": (
                sum(label.review_seconds for label in labels) / total if total else None
            ),
            "mean_est_seconds": (
                sum(est) / len(est) if est else None
            ),
        }

    def counter_emissions(self, run_id: str) -> tuple[CounterEmission, ...]:
        """The ordered emissions the run produced (`CT-REVIEW-18`'s read back)."""
        return tuple(self._emissions.get(run_id, ()))

    def exhaust_budget_on(self, criterion_id: str, administration_id: str) -> None:
        """Record that a criterion exhausted its budget on one administration
        (`CT-REVIEW-18`'s exhaustion signal). A repeat for an administration
        already recorded does not extend the streak: the signal is that the
        criterion exhausted, once per administration."""
        streak = self._exhaustions.setdefault(criterion_id, [])
        if administration_id not in streak:
            streak.append(administration_id)

    def alerts(self) -> tuple[ReviewAlert, ...]:
        """The standing alerts: one per criterion whose exhaustion streak has
        reached `ALERT_MIN_CONSECUTIVE_ADMINISTRATIONS`, recomputed from the
        retained sequence — never reset between terms (`CT-REVIEW-18`)."""
        return tuple(
            ReviewAlert(
                name=REVIEW_BUDGET_EXHAUSTION_ALERT,
                criterion_id=criterion_id,
                consecutive_administrations=len(streak),
                administrations=tuple(streak),
            )
            for criterion_id, streak in self._exhaustions.items()
            if len(streak) >= _ALERT_MIN_CONSECUTIVE_ADMINISTRATIONS
        )

    def escalate(self, score_id: str) -> SupersededScore:
        """Mark one score superseded (`CT-REVIEW-15`'s induced race): every queue
        built before this call carries the old version, and an action on it is
        refused with a refresh message."""
        current = self._versions.get(score_id)
        if current is None:
            row = self._rows_by_id.get(score_id)
            current = int(getattr(row, "version", 1) or 1) if row is not None else 1
        bumped = current + 1
        self._versions[score_id] = bumped
        return SupersededScore(score_id=score_id, version=bumped)

    def close(self) -> None:
        """Release the rung-2 store handle, if this service was opened over one."""
        if self._store is not None:
            self._store.close()
            self._store = None

    def _with_store(
        self, store: Any, cohort_ids: Sequence[str] = ()
    ) -> "ReviewService":
        """Attach the rung-2 store handle (``open_review``'s plumbing). The
        cohort ids ride along so a label written before any queue build can
        still attribute itself — to the sole cohort, when there is exactly
        one; never to an invented run (`NFR-REVIEW-04`)."""
        self._store = store
        self._cohort_ids = tuple(cohort_ids)
        return self

    # -- the write audit, and the residual's read path (#109) -----------------------------------------

    def write_audit(self) -> tuple[WriteRecord, ...]:
        """Every write this service's actions have made, in write order
        (`CT-REVIEW-06` reads the indirection from the write side, not from the
        resulting counts, because the counts are identical either way).

        In the in-memory service the writes land on the service's own state —
        the label list and the acted set — and each ``WriteRecord`` names the
        store table that state stands in for: ``criterion_score`` for the
        reduction through the score row (the acted row leaves the flagged count
        *through* ``criterion_score``, never through a grade table — this
        module never writes a grade) and ``label`` for the label itself. #110's
        store writes keep the same tables, so the audit reads the same after."""
        return tuple(self._audit)

    def scores(self, run_id: str = "run-1") -> tuple[Any, ...]:
        """The run's still-flagged score rows, read back for the residual
        (`FR-REVIEW-08`'s read path): the admitted population minus what this
        service has acted on — the population ``build_queue`` counts into
        ``flagged_total``, so ``len(scores())`` is the flagged figure at the
        same moment.

        States ride through exactly as stored. Review writes no state it did
        not decide: the residual's ``provisional_unreviewed`` mark is the
        producer's (``aeh.agg`` writes it when it routes the row), and the
        three prohibitions keep it that way — ``end_session`` and ``close_run``
        persist the residual by leaving it exactly where it stands. The acted
        rows' state updates are #110's store write; until then an acted row is
        visible through ``labels_for`` and has left the count through the
        acted set."""
        return tuple(self._admitted_rows())

    def labels_for(self, run_id: str = "run-1") -> tuple[LabelRecord, ...]:
        """The labels this service has written, in write order — the in-memory
        read the residual's no-backfill assertion reads (`FR-REVIEW-08`: a
        residual item gains no label nobody entered) and the refusal case of
        `CT-REVIEW-15` checks. The label store's own persistence surface is
        #110's; until then the labels live here, and ``run_id`` is
        bookkeeping."""
        return tuple(self._labels)

    def end_session(self, run_id: str = "run-1") -> ResidualReport:
        """Close the sitting (`FR-REVIEW-08`'s first vanishing moment): the
        residual persists. The acted set, the labels and every residual row's
        ``provisional_unreviewed`` state survive it untouched — clearing per
        sitting would silently convert "not reviewed" into "reviewed and
        accepted" — so the next sitting's queue still owes exactly what this
        one did not finish. Nothing is mutated; the report is the moment."""
        return self._residual_report(run_id, moment="end_session")

    def close_run(self, run_id: str = "run-1") -> ResidualReport:
        """Close the run (`FR-REVIEW-08`'s second vanishing moment): the run's
        close is where finalization pressure lands, and neither prohibition is
        met. No residual row is finalized, none gains a label nobody entered,
        and ``scores()`` keeps returning every one of them — the residual does
        not answer to the run's lifecycle. Nothing is mutated; the report is
        the moment."""
        return self._residual_report(run_id, moment="close_run")

    def _residual_report(self, run_id: str, *, moment: str) -> ResidualReport:
        """The residual as the moment leaves it: every still-flagged row, in
        the state `FR-REVIEW-08` marks it with. ``finalized``/``backfilled``
        are what the moment wrote — nothing, by construction, since the service
        writes no state and no label at a session or run boundary; the lists
        exist so a later change that does write one has a field to carry it
        in.

        ``state`` reports the ordinary residual mark. A residual can also hold
        an unacted ``ungradeable_by_panel`` row (it routes ``provisional``,
        so it is admitted and still unreviewed); consumers keep that state
        distinct per `CT-AGG-07`, and #110's store form carries the per-state
        counts when the report gains them."""
        residual = self._admitted_rows()
        return ResidualReport(
            run_id=run_id,
            moment=moment,
            residual_provisional=len(residual),
            state=_RESIDUAL_STATE,
            finalized=(),
            backfilled=(),
        )

    def _record_writes(self, item: ReviewItem, action: str, label: LabelRecord) -> None:
        """Audit one action's writes (`CT-REVIEW-06`). The reduction through
        the score row is recorded first — it is the write the clause asserts —
        and the label second."""
        self._audit.append(
            WriteRecord(
                table="criterion_score",
                score_id=item.score_id,
                detail=f"{action} leaves the flagged count through the score row",
            )
        )
        self._audit.append(
            WriteRecord(
                table="label",
                score_id=item.score_id,
                detail=f"{action} label {label.label_id}",
            )
        )

    # -- internals -----------------------------------------------------------------------------------

    def _admitted_rows(self) -> list[Any]:
        """The still-flagged rows this run admits (`_admitted`), minus the ones
        this service has already acted on."""
        return [
            row for row in _admitted(self._rows) if _score_id_of(row) not in self._acted
        ]

    def _as_item(self, item: Any) -> ReviewItem:
        """The queue entry an action arrives on. A ``ReviewGroup`` is not an
        action target — ``act_on_group`` is the group's path."""
        if getattr(item, "members", None) is not None:
            raise ReviewError(
                "act() takes a single review item; a group is acted on through "
                "act_on_group, which writes one label per member"
            )
        if getattr(item, "score_id", None) is None:
            raise ReviewError("act() takes a queue item carrying score_id")
        return item

    def _check_not_stale(self, item: ReviewItem) -> None:
        current = self._versions.get(item.score_id)
        if current is not None and current != item.version:
            raise StaleReviewItemError(
                f"score {item.score_id!r} is stale: it was superseded by an escalation "
                f"(the store now carries version {current}, the queue built version "
                f"{item.version}); refresh the queue before acting"
            )

    def _write_label(
        self,
        item: ReviewItem,
        *,
        label_type: str,
        teacher_band: str | None,
        review_seconds: float,
        review_queue_action: str,
        via_group: bool = False,
    ) -> LabelRecord:
        row = self._rows_by_id.get(item.score_id)
        self._versions.setdefault(item.score_id, item.version)
        # ``new_points`` is derived from the band the label records through
        # `CT-PKG-05`'s pinned mapping (`FR-REVIEW-10`) — the same call the
        # derivation contract names (`points_for_band`), not a second table
        # (`NFR-AGG-02`). An accept records the system's proposed band; an
        # edit or override records the teacher's.
        effective_band = item.proposed_band if label_type == "accept" else teacher_band
        new_points = (
            self._points_for_band(
                package_version_id=getattr(item, "package_version_id", None),
                criterion_id=item.criterion_id,
                band=effective_band,
            )
            if effective_band is not None
            else None
        )
        label = LabelRecord(
            label_id=f"label-{len(self._labels) + 1:04d}",
            label_type=label_type,
            # A queue action happens with the system's band on the screen
            # (`CT-REVIEW-08`'s per-path values; the blind flow's earned 0 is #111's).
            saw_system_output=1,
            routing=str(getattr(row, "routing", "queued") or "queued"),
            origin=str(getattr(row, "origin", "escalation") or "escalation"),
            evaluation_mode=str(getattr(row, "evaluation_mode", "judged") or "judged"),
            review_seconds=review_seconds,
            system_band=item.proposed_band,
            teacher_band=teacher_band,
            actor=self._actor_name,
            timestamp=self._clock(),
            score_id=item.score_id,
            criterion_id=item.criterion_id,
            review_queue_action=review_queue_action,
            new_points=new_points,
            via_group=via_group,
        )
        # In-memory first, then the durable half (`CT-STORE-03`): a failure in
        # the durable write aborts the action with the in-memory record already
        # written, which is what the interpretations disclose.
        self._labels.append(label)
        self._labels_by_id[label.label_id] = label
        # Attribution is per-run (`NFR-REVIEW-04`): the label joins the run the
        # service last built a queue for, or the sole cohort the service was
        # opened over — never an invented run.
        run_id = self._attribution_run()
        if run_id is not None:
            self._run_labels.setdefault(run_id, []).append(label)
        if self._store is not None:
            if run_id is None:
                raise ReviewError(
                    "this service holds a store but no run context: build a queue "
                    "for the run (or open the service over exactly one cohort) "
                    "before acting — a label is not attributed to an invented run"
                )
            self._persist_label(label, run_id, item)
        return label

    def _attribution_run(self) -> str | None:
        """The run a label written now attributes to (`NFR-REVIEW-04`): the
        queue this service last built, or — before any build — the sole cohort
        the service was opened over. ``None`` when neither holds. The durable
        row's ``cohort_id`` scoping column carries this same id — the run's id
        is the administration's id in the store flow (`open_review` names the
        cohort as the run), and the rule's full shape is disclosed in the
        module interpretations."""
        if self._current_run_id is not None:
            return self._current_run_id
        if len(self._cohort_ids) == 1:
            return self._cohort_ids[0]
        return None

    def _persist_label(
        self, label: LabelRecord, run_id: str, item: ReviewItem | BlindItem
    ) -> None:
        """The durable half of a store-backed action (`FR-REVIEW-09`): the same
        label this service holds in memory, written to Tier D's ``label`` table
        in one statement. ``CT-STORE-03`` scopes atomicity to one transaction
        body and cross-tier atomicity is deliberately not provided, so this
        runs after the in-memory write: a failure here aborts the action with
        the in-memory record already written. ``item`` is the identity the
        label's student-reference column carries — the queue item an action
        acted on, or the blind ref the flow drew (#111; a ``BlindItem`` carries
        ``submission_id`` and nothing else, which is all the durable row
        reads)."""
        if label.teacher_band is None:
            raise ReviewError(
                f"label {label.label_id!r} records no band; Tier D's label table "
                "carries a band for every label, so an action without one is refused"
            )
        handle = self._store.durable()
        with handle.transaction() as tx:
            tx.execute(
                REVIEW_STATEMENTS["insert_label"],
                label_id=label.label_id,
                run_id=run_id,
                # The store rows carry no student identity (#108's mapping
                # records the same absence): the submission under review is
                # what the row can honestly reference in Phase 1.
                student_ref=item.submission_id,
                criterion_id=label.criterion_id,
                label_type=label.label_type,
                band=label.teacher_band,
                evaluation_mode=label.evaluation_mode,
                saw_system_output=label.saw_system_output,
                routing=label.routing,
                origin=label.origin,
                review_seconds=label.review_seconds,
                system_band=label.system_band,
                teacher_band=label.teacher_band,
                actor=label.actor,
                timestamp=label.timestamp,
                score_id=label.score_id,
                review_queue_action=label.review_queue_action,
                new_points=label.new_points,
                # The promotion gate's scoping column carries the run's id, not
                # a per-row cohort: a run belongs to one cohort in this
                # codebase, so in the declared store flow the two coincide —
                # the rule and its purge consequence are disclosed in the
                # module interpretations.
                cohort_id=run_id,
            )

    def _record_emission(
        self,
        run_id: str,
        names: tuple[str, ...],
        values: Mapping[str, Any],
    ) -> None:
        """One observability emission, stamped at the service's clock and
        attributed to the run (`CT-REVIEW-18`'s seam 4)."""
        self._emissions.setdefault(run_id, []).append(
            CounterEmission(at=self._clock(), names=names, values=dict(values))
        )

    def _record_action_emission(self, labels: Sequence[LabelRecord]) -> None:
        """The per-action emission (`CT-REVIEW-18`): minutes used and the
        running mean, emitted together at the instant the labels were written —
        one emission per action, not per label (a group action is one decision)."""
        if not labels:
            return
        run_id = self._attribution_run()
        if run_id is None:
            return
        run_labels = self._run_labels.get(run_id, ())
        total = sum(label.review_seconds for label in run_labels)
        self._record_emission(
            run_id,
            ("review_minutes_used", "mean_review_seconds"),
            {
                "review_minutes_used": total / 60,
                "mean_review_seconds": total / len(run_labels) if run_labels else None,
            },
        )


# --- the constructors -------------------------------------------------------------------------------


def build_review(
    scores: Any = None,
    *,
    actor: str = "teacher",
    clock: Callable[[], str] | None = None,
    catalog: Any = None,
    config: Any = None,
    review_blind_reserve_minutes: int | None = None,
    review_blind_n: int | None = None,
    review_whole_grade_n: int | None = None,
    review_default_budget_minutes: int | None = None,
    seed: int | None = None,
    administration_id: str | None = None,
    previous_administration: Any = None,
) -> ReviewService:
    """The rung-0/1 constructor: a review service over score rows — or, in the
    store form, over a whole store.

    The four §3.15 knobs arrive as keywords (``review_blind_n=20``), as
    ``config=`` attributes named after the constants, or not at all — the
    module constants are the declared defaults (`CT-REVIEW-17`). The store
    form (`build_review(store)`, the c05/c07/c09 consumer limbs' declared
    shape) reads every cohort the store carries and admits the same
    population `open_review` does; the queue is then the service's read path
    (``.queue()``).

    #111's sampling keywords ride both forms: ``seed=`` reproduces both
    samples' draws, ``administration_id=`` names the administration the skip
    report speaks for, and ``previous_administration=`` is held — never read —
    so the skip report's ``current_figure=None`` is an honest None rather than
    an uninformed one (`FR-REVIEW-13`'s no-carry-forward clause)."""
    if scores is not None and hasattr(scores, "cohort"):
        return _service_from_store(
            scores,
            actor=actor,
            clock=clock,
            catalog=catalog,
            config=config,
            review_blind_reserve_minutes=review_blind_reserve_minutes,
            review_blind_n=review_blind_n,
            review_whole_grade_n=review_whole_grade_n,
            review_default_budget_minutes=review_default_budget_minutes,
            seed=seed,
            administration_id=administration_id,
            previous_administration=previous_administration,
        )
    return ReviewService(
        scores or (),
        actor=actor,
        clock=clock,
        catalog=catalog,
        config=config,
        blind_reserve_minutes=_resolve_knob(
            review_blind_reserve_minutes, config, "REVIEW_BLIND_RESERVE_MINUTES",
            REVIEW_BLIND_RESERVE_MINUTES,
        ),
        blind_n=_resolve_knob(
            review_blind_n, config, "REVIEW_BLIND_N", REVIEW_BLIND_N
        ),
        whole_grade_n=_resolve_knob(
            review_whole_grade_n, config, "REVIEW_WHOLE_GRADE_N", REVIEW_WHOLE_GRADE_N
        ),
        default_budget_minutes=_resolve_knob(
            review_default_budget_minutes, config, "REVIEW_DEFAULT_BUDGET_MINUTES",
            REVIEW_DEFAULT_BUDGET_MINUTES,
        ),
        seed=seed,
        administration_id=administration_id,
        previous_administration=previous_administration,
    )


def _store_cohort_ids(store: Any) -> list[str]:
    """The cohort ids a store carries, in stable id order — the same discovery
    the store's own surfaces use (`cohorts/<cohort_id>.sqlite`, one file per
    administration; `aeh.det` and `aeh.orch` walk the identical layout)."""
    return sorted(
        path.stem for path in Path(store.data_dir, "cohorts").glob("*.sqlite")
    )


def _service_from_store(
    store: Any,
    *,
    cohort_ids: Sequence[str] | None = None,
    actor: str = "teacher",
    clock: Callable[[], str] | None = None,
    catalog: Any = None,
    config: Any = None,
    review_blind_reserve_minutes: int | None = None,
    review_blind_n: int | None = None,
    review_whole_grade_n: int | None = None,
    review_default_budget_minutes: int | None = None,
    seed: int | None = None,
    administration_id: str | None = None,
    previous_administration: Any = None,
) -> ReviewService:
    """The rung-2 constructor's body, shared by ``open_review`` (one named
    cohort) and ``build_review`` (a whole store — every cohort it carries).

    Reads the cohort's stored ``criterion_score`` rows through ``aeh.store`` —
    the deterministic store, no egress — and maps them onto the score-row
    vocabulary with honest defaults for the columns the store does not carry.
    The query takes both of the teacher's routings (`CT-AGG-06`: ``queued``;
    the provisional family whose fallback and breaker rows `CT-AGG-07` binds
    this module to surface); the state column rides through to the item, and
    the admission predicate — the same one the in-memory service runs — does
    the excluding."""
    # The store's tier migration chains are concatenated at import time by the
    # modules that own the schema they add (CLAUDE.md): the cohort handle this
    # opens must not be the first open in a process that skipped the imports.
    # These ten plus *this module* — which owns Durable's last migration, the
    # #110 label-store columns — make the complete chain; importing aeh.review
    # from inside aeh.review is a no-op, so the ten it does not own are here.
    import aeh.agg  # noqa: F401
    import aeh.det  # noqa: F401
    import aeh.extract  # noqa: F401
    import aeh.grade  # noqa: F401
    import aeh.ingest  # noqa: F401
    import aeh.integ  # noqa: F401
    import aeh.judge  # noqa: F401
    import aeh.orch  # noqa: F401
    import aeh.pkg  # noqa: F401
    import aeh.synth  # noqa: F401

    from aeh.store import Statement

    if cohort_ids is None:
        cohort_ids = _store_cohort_ids(store)
    rows: list[Any] = []
    # The routing narrow is a declared literal, not an assembly: SEC-15's
    # walker (`FR-STORE-08`) forbids building SQL at runtime, so this statement
    # matches ``_ADVISORY_ROUTINGS`` by transcription and the admission_query
    # plan reports the same values. Drift between the two is caught by review
    # of the pair, as the plan's docstring says. The mode and origin halves of
    # the admission ride the predicate on the fetched rows.
    for cohort_id in cohort_ids:
        rows.extend(
            _row_mapping(row)
            for row in store.cohort(cohort_id).query(
                Statement(
                    "SELECT * FROM criterion_score "
                    "WHERE routing IN ('queued', 'provisional')"
                )
            )
        )
    knobs = _calibration_knobs()
    mapped = [
        _StoredScoreRow(mapping, knobs["default_est_seconds"]) for mapping in rows
    ]
    return build_review(
        mapped,
        actor=actor,
        clock=clock,
        catalog=catalog,
        config=config,
        review_blind_reserve_minutes=review_blind_reserve_minutes,
        review_blind_n=review_blind_n,
        review_whole_grade_n=review_whole_grade_n,
        review_default_budget_minutes=review_default_budget_minutes,
        seed=seed,
        administration_id=administration_id,
        previous_administration=previous_administration,
    )._with_store(store, cohort_ids=cohort_ids)


class _StoredScoreRow:
    """One stored ``criterion_score`` row as the ranking reads it: the store's
    column names mapped onto the score-row vocabulary, with the row's own
    values wherever the store carries them and honest defaults where it does
    not (the review inputs the store does not carry yet arrive with their
    stories — an override history the store has none of reads as no data)."""

    def __init__(self, mapping: Mapping[str, Any], default_est_seconds: float) -> None:
        submission_id = mapping.get("submission_id")
        criterion_id = mapping.get("criterion_id")
        self.score_id = f"{submission_id}:{criterion_id}"
        self.criterion_id = criterion_id
        self.submission_id = submission_id
        self.routing = mapping.get("routing")
        self.origin = mapping.get("origin", "escalation")
        self.evaluation_mode = mapping.get("evaluation_mode", "judged")
        self.state = mapping.get("state")
        self.proposed_band = mapping.get("band")
        self.panel_spread = mapping.get("panel_spread")
        self.adverse_integrity_signals = mapping.get("adverse_integrity_signals") or 0
        self.transcription_overlap = mapping.get("transcription_overlap")
        self.historical_override_rate = mapping.get("historical_override_rate")
        self.criterion_weight = mapping.get("criterion_weight")
        self.grade_boundary_delta = mapping.get("grade_boundary_delta")
        est = mapping.get("est_seconds")
        self.est_seconds = default_est_seconds if not est else est
        self.self_confidence = mapping.get("confidence")
        self.spans_verified = mapping.get("spans_verified")
        self.evidence_present = mapping.get("evidence_present")
        self.sufficiency_flag = mapping.get("sufficiency_flag")
        self.ocr_overlap_risk = mapping.get("ocr_overlap_risk")
        self.version = 1
        self.scoring_model = "atomic"


def _row_mapping(row: Any) -> dict[str, Any]:
    """One store row as a plain mapping, whatever ``Row`` shape the tier hands
    back."""
    try:
        return {key: row[key] for key in row.keys()}
    except AttributeError:
        return dict(row)


def open_review(
    data_dir: Path | str,
    *,
    run_id: str,
    actor: str = "teacher",
    clock: Callable[[], str] | None = None,
    catalog: Any = None,
    config: Any = None,
    review_blind_reserve_minutes: int | None = None,
    review_blind_n: int | None = None,
    review_whole_grade_n: int | None = None,
    review_default_budget_minutes: int | None = None,
    seed: int | None = None,
    administration_id: str | None = None,
    previous_administration: Any = None,
) -> ReviewService:
    """The rung-2 constructor: a review service over a stored run's flagged rows.

    Reads the cohort's own ``criterion_score`` rows through ``aeh.store`` — the
    deterministic store, no egress — and admits the same population the
    in-memory service does. Actions write the label store (`FR-REVIEW-09`):
    every label is held in memory and persisted to Tier D's ``label`` table
    (this module's Durable 6 migration adds the columns), attributed to the
    ``run_id`` named here.
    """
    from aeh.store import open_store as _open_store

    store = _open_store(Path(data_dir))
    try:
        return _service_from_store(
            store,
            cohort_ids=[run_id],
            actor=actor,
            clock=clock,
            catalog=catalog,
            config=config,
            review_blind_reserve_minutes=review_blind_reserve_minutes,
            review_blind_n=review_blind_n,
            review_whole_grade_n=review_whole_grade_n,
            review_default_budget_minutes=review_default_budget_minutes,
            seed=seed,
            administration_id=administration_id,
            previous_administration=previous_administration,
        )
    except Exception:
        store.close()
        raise


# --- the module-level label store (FR-REVIEW-09, #110) ------------------------------------------------
#
# A process-level store for labels written *outside* a service session — the
# route the C07/C08 vocabulary exercises (`record_label`/`labels_for`). It is
# deliberately separate from `ReviewService`'s own bookkeeping: a service's
# labels are per-session (its ids, its runs, its optional durable rows), and a
# shared store would leak labels between tests and sessions. The durable
# persistence is the service's, over a real store (`CT-STORE-01`: the spy
# stores expose no transactional execute).

_LABEL_TYPES: tuple[str, ...] = ("accept", "edit", "override", "blind")

_LABEL_STORE: dict[str, list[LabelRecord]] = {}
_LABEL_STORE_COUNTER = itertools.count(1)


def record_label(
    *,
    run_id: str,
    score_id: str,
    label_type: str,
    teacher_band: str | None = None,
    system_band: str | None = None,
    saw_system_output: int | None = None,
    routing: str = "queued",
    origin: str = "escalation",
    evaluation_mode: str = "judged",
    review_seconds: float = 0,
    criterion_id: str = "",
    actor: str = "teacher",
    timestamp: str | None = None,
    review_queue_action: str | None = None,
) -> str:
    """Write one label into the process-level store and return its id
    (`FR-REVIEW-09`): the direct route for a label that does not ride an
    action — and the vocabulary the C07/C08 contract reads.

    ``saw_system_output`` records whether the teacher saw the system's output
    before deciding (`FR-REVIEW-09`'s visibility column): 1 means the system
    output was visible, 0 means the label was written blind. It defaults from
    the label type — a ``blind`` label is by definition blind, every other type
    is by default an operational one — and an explicit value wins, so a caller
    that knows better can record it. The label is fully typed: band, routing,
    origin, attribution, the visibility flag — no field is left implicit. There
    is deliberately no ``new_points`` parameter: a score edit is a band
    choice (`FR-REVIEW-10`), and points enter only as the *derived* value a
    service label carries — the mapping is never handed a caller's number.

    This is the in-memory surface, deliberate at #110: the durable
    per-label write outside a service session is #115's collection route,
    and the stats cases written ahead of both stories call a planned
    ``record_label(data_dir=..., label=...)`` shape against it — at #115's
    landing those calls reconcile to whichever surface that story ships
    (this one, or its durable extension); the `require(..., issue="#115")`
    blocker ahead of every such call keeps them outside the gate until then.
    """
    if label_type not in _LABEL_TYPES:
        raise ValueError(f"{label_type!r} is not a label type; one of {_LABEL_TYPES}")
    if saw_system_output is None:
        saw_system_output = 0 if label_type == "blind" else 1
    elif saw_system_output not in (0, 1):
        raise ValueError(
            f"saw_system_output is a visibility flag, not a number: it is 1 (the "
            f"system output was visible) or 0 (the label was written blind), got "
            f"{saw_system_output!r} — any other value is indistinguishable from a "
            "real one at query time"
        )
    label = LabelRecord(
        label_id=f"stored-{next(_LABEL_STORE_COUNTER):04d}",
        label_type=label_type,
        saw_system_output=int(saw_system_output),
        routing=routing,
        origin=origin,
        evaluation_mode=evaluation_mode,
        review_seconds=review_seconds,
        system_band=system_band,
        teacher_band=teacher_band,
        actor=actor,
        timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
        score_id=score_id,
        criterion_id=criterion_id,
        review_queue_action=review_queue_action,
        new_points=None,
    )
    _LABEL_STORE.setdefault(run_id, []).append(label)
    return label.label_id


def labels_for(*, run_id: str) -> tuple[LabelRecord, ...]:
    """Every label recorded into the process-level store for one run
    (`CT-REVIEW-07`'s read back), in write order. A tuple, so a caller cannot
    reorder the store's history in place."""
    return tuple(_LABEL_STORE.get(run_id, ()))


def blind_sample_skipped(service: Any, run_id: str = "run-1") -> BlindSampleSkipReport:
    """The skip, read back from a service (`FR-REVIEW-13`'s reporting surface,
    `CT-REVIEW-10`'s read side): whether this run's blind sample was skipped,
    the consequence in words, and ``current_figure = None`` — always, whatever
    a previous administration produced. The module-level form mirrors
    ``record_label``/``labels_for``: the report is read *about* a service, so a
    caller holding one asks here rather than reaching into its state."""
    return service.skip_report(run_id)
