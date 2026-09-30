# `aeh.review`: design notes

These notes were the docstring of `src/aeh/review.py` before it was split into the `aeh/review/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

M-REVIEW — the minute-budgeted review queue (§3.15, issue #108).

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

## Details moved out of the code

These notes were the longer parts of docstrings in `aeh.review`. Each section is named after the file and the function or class it describes.

### labels.py: record_label

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

Two routes, one signature (`#115`'s collection route completes the shape
this docstring anticipated at #110):

* **The in-memory route** — ``run_id=``, ``score_id=``, ``label_type=``
  (the original #110 surface). The label lives in the process-level store
  and dies with the process; this is the vocabulary the C07/C08 contract
  reads.
* **The durable collection route** — ``label=`` with ``data_dir=`` (and an
  optional ``cohort_id=``): the label object is written straight to Tier
  D's ``label`` table through ``upsert_label``, the store being cached per
  data directory so a collection loop pays the open once. The statistics
  cases (`TC-STATS-C01` rung 2, `TC-STATS-C17`, `TC-STATS-C18`) collect
  through this route, and `M-STATS` reads the same rows back.

The two are mutually exclusive by signature — a call carrying both is
refused rather than guessed at, and a call carrying neither route's
required arguments is a programming error, not a silent default.
