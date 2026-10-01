# `aeh.orch`: design notes

These notes were the docstring of `src/aeh/orch.py` before it was split into the `aeh/orch/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

`M-ORCH` — the Run Orchestrator & Work Ledger (design §3.7).

The ledger is the system's only source of truth about what has run, what is running and
what is left, which is what makes the console stateless and resume bookkeeping-free. This
first slice (issue #57) is the ledger's foundation:

- **`WorkUnit`** — the unit type itself (design v1.5 note: this story owns the type, not
  just the ledger rows). Its field list is fixed by the design note and is deliberate;
  see the class docstring for why `student_name` is on it.
- **`compute_work_id`** — `FR-ORCH-01`'s content address. Changing any of the nine inputs
  that can affect the answer produces a different unit, so a stale result is structurally
  unreusable rather than manually cleaned up (R14, NFR-EXTRACT-02/03).
- **Enumeration** — `create_run` / `enumerate_units`: base units per the §3.7 data flow,
  inserted idempotently, so enumerating twice produces byte-identical `work_id` sets
  (NFR-ORCH-05) and re-running a completed run is a no-op (FR-ORCH-03).
- **`resume()`** — takes no arguments (`FR-ORCH-02`: an argument is a place for an
  operator to be wrong under time pressure), skips every `done` unit, and is safe to
  invoke when nothing is wrong.

**This slice (#58) adds the lease** (`FR-ORCH-04`): `lease(worker_id, stage, n)` claims
pending units exclusively with an owner and an expiry, `heartbeat(work_id)` extends a live
lease, `sweep_expired_leases()` returns abandoned leases to `pending` — and the failure
taxonomy (`FR-ORCH-18`): `complete(work_id, result)` marks a unit `done` and `fail(work_id,
error)` requeues a unit until `ORCH_MAX_ATTEMPTS`, then quarantines it with its last error
retained while the run continues ("fail the unit, never the run"). Expiry is derived from
`M-STORE`'s monotonic lease counter (`LeaseClock`, `FR-STORE-11`/`CT-STORE-14`) — never
from the wall clock, so a clock moved backwards across a restart still reads an expired
lease as expired. The wall-clock timestamp beside the ticks is for the operator reading
the row; the sweeper's comparison is the counter's alone.

**This slice (#59) adds the two-sweep execution plan** (`FR-ORCH-05/06/07/08/22`):
Sweep 1 (extraction) is enumerated over **admitted** submissions only —
`SWEEP1_ADMITTED_INGEST_STATUSES` is the admission rule — and dispatched in topological
order over the criterion dependency graph; Sweep 2 (scoring) for a criterion does not
begin until every extraction unit it depends on is `done`, and is then ordered judge →
question → criterion → parallel over submissions on every backend profile (`FR-ORCH-07`'s
fixed key — no dependency ordering in Sweep 2, per the design's technical note). A
`deterministic` criterion generates exactly one `stage='deterministic'` unit with a null
`judge_id` and no extraction and no scoring unit (`FR-ORCH-08`).

**This slice (#60) adds the escalation machinery** (`FR-ORCH-09/10/11/13/14/26`):
`enqueue_escalation(tx, criterion_score_key, judges)` — the design's `CT-ORCH-08`
form, the caller's transaction first — widens a pair's panel one judge to three,
never to two; an even plan raises `EvenEscalationPlanError` (`FR-ORCH-10`), and the
widened units carry `origin='escalation'` in the transaction the caller commits with
the verdict that triggered them (`FR-ORCH-09`). The **random arm** samples judged
pairs at `ORCH_RANDOM_ARM_RATE` during enumeration (`origin='random_arm'`,
independent of confidence, never suppressed by the budget or a breaker —
`CT-ORCH-15`); the seeded draw is `random_arm_selection`. The **criterion breaker**
(`FR-ORCH-13`) latches when a criterion escalates for more than half of the first
`ORCH_CRITERION_BREAKER_MIN_N` submissions processed — escalation halts for that
criterion, the remainder single-judge provisional. The **run-wide budget**
(`FR-ORCH-14`) rations dispatch: `enqueue_escalation` writes the plan the verdict
needs (the atomicity clause leaves it no choice), and the claim pass admits pending
escalation units through `admit_escalations` only while the observed rate is at or
under `ORCH_ESCALATION_BUDGET` — above it the remainder stays pending, marked
provisional in expected-value order, until growth returns headroom. Scrutiny is
never silently reduced. Every decision is pure policy (`escalation_plan`,
`validate_escalation_plan`, `admit_escalations`, `criterion_breaker_tripped`,
`random_arm_selection`) — evaluable with no model call (`NFR-ORCH-04`).

**This slice (#61) adds the control-row run lifecycle** (`FR-ORCH-15/16/17/25`,
`CT-ORCH-12/13`): `start(run_id)` flips `pending → running` and obtains + displays the
run's estimated cost from the injected provider seam **before** any dispatch;
`pause(run_id, cause=...)` records the request as a `run_control` row and applies it
through the control-read pass — immediately on a `running` run, queued on a `pending`
one (request ≠ effect: the effect lands at the next `start`), so a pause written while
the orchestrator was down is honoured at the next read rather than lost. The four
`CT-ORCH-12` pause conditions all land in the same place: `ProviderUnavailableError`
(`FR-ORCH-16`) and `BuildChangedError` (`FR-ORCH-17`) via `cause=`, the operator's own
request via `cause=None`, and the cost ceiling sensed in the claim pass itself — the
frozen ceiling (`FR-CONF-07`) is checked against the provider seam's **measured**
per-unit figures (`FR-PROV-12/04`, never an estimated optimism), spend accrues in the
claim transaction, a dispatch that would land **above** the ceiling is refused and the
run pauses naming its spend and remaining unit count. `resume(run_id)` is the
`paused → running` edge and re-binds to nothing: lifecycle writes touch status columns
only, so the frozen backend is the resumed backend by construction — there is no
substitution code path (`FR-ORCH-16`). The ledger is preserved across every pause: a
pause is a stop and a reason, never a purge.

**This slice (#62) adds the dispatch loop and the `ProgressReport`**
(`FR-ORCH-12/19/21/23/24`): `progress(run_id)` is the dispatch loop's beat — with a
transport injected it completes the extraction walk through the seam, completes the
deterministic walk directly (deterministic evaluation makes no model call), and claims ONE
score batch no larger than the pass's effective concurrency, running its model calls
concurrently against the injected transport seam (`Orchestrator(store, transport=...)`,
`call(request) -> Completion` or a raise of the real taxonomy error) — the seam receives
the **assembled** closed request (`FR-ORCH-20`: what is dispatched is "exactly one
submission per scoring or extraction request", so the dispatch assembles the stage's
shipped schema — `ScoringRequest` via `M-JUDGE`'s `ScoringWorker.assemble`, the
`ExtractionRequest` via `M-EXTRACT`'s `assemble_request` — and sends that, never the
ledger row); without a transport the call is the
report-only surface the console polls, which reads the ledger and dispatches nothing.
On `edge-local` the claim walk is **residency-batched**: one judge model stays resident
until the ledger holds none of its work, each model change is a recorded swap (count and
measured duration, `FR-ORCH-19`), and every handout batch is single-model. The
concurrency governor starts at the run's frozen ceiling, divides on rate-limit/OOM
signals and clamps further while M-STORE signals write backpressure — a signal to reduce
dispatch, never a fault (`CT-STORE-06`). The report counts by
`(stage, criterion, judge)` and totals done/in-flight/pending/quarantined — **no
per-student figure exists on the type** (`FR-ORCH-23`/`R63`) — with the completion
predicate read off the ledger (`FR-ORCH-12`: nothing pending and no in-flight scoring
judgment that could spawn an escalation) and the estimate adjusted by the observed
escalation rate (`estimated_completion_seconds`, `FR-ORCH-24`).

**The four seams** (CLAUDE.md): the orchestrator runs end-to-end from code and returns a
structured result with per-gate detail (`EnumerationReport`, `EscalationReport`,
`ProgressReport` — the `IngestReport.gates` precedent); its one external dependency to
transport — the model call — is injected (`transport=`), so a dispatch runs with no
network and the store arrives by injection the same way; every budget, threshold, rate
and window constant is env-gated and read at call time; and every report carries
stage-level detail rather than a bare status.

## Details moved out of the code

These notes were the longer parts of docstrings in `aeh.orch`. Each section is named after the file and the function or class it describes.

### dispatch.py: DispatchMixin._run_model_batch

Each unit's ASSEMBLED request is built on the calling thread BEFORE the pool
takes anything — the assembler is the owning stage's shipped door, it reads
the store (the words resolve here: "the lease resolves the identity, the
assembler the words"), and the store is not a thread-shared surface — so the
only thing that runs concurrently is the model call itself. Assembly
completes for the WHOLE batch before the first submit, and the submits are
then back-to-back: pipelining assembly into the submission loop would pace
the ramp at the assembly interval, and Little's law would cap the observed
in-flight peak at `call_duration / assembly_interval` — a figure set by the
assembler's speed, not by the governor. With the payloads pre-built, calls
run on a thread pool bounded by `min(len(batch), effective)` and the pool
width IS the observable in-flight concurrency the governor's ceiling governs
(`FR-ORCH-21`; the seam's spy counts the peak — the caller bounds a batch to
`effective` so the pre-assembly latency is bounded by the same figure). Every
outcome is classified, never absorbed silently:

- **Completion** — the real `Completion`: the unit closes (`complete`), and
  the answer's tokens, cost, cache prefix and resolved build accrue to the
  run's counters (`CT-PROV-11`'s shape — M-ORCH reads the provider's
  counters and persists them).
- **`RateLimitedError`** (`RES-11`) — expected, not an error: the counters
  increment (the parsed `Retry-After` accrues to the honoured wait), the
  unit requeues **without consuming an attempt and without a unit-level
  error** (a rate limit is the provider's condition, not the unit's — §9.11),
  and the governor reduces next pass.
- **`MemoryError`** (`RES-13`) — the box's condition: the unit requeues the
  same way (the box's condition is not the unit taxonomy's, §9.11), the cap
  reduces, and the OOM ladder's cumulative count may drop the judge from the
  panel.

Any other exception propagates — an unexpected transport failure is a defect,
and the units stay leased on the ledger where the sweeper reclaims them.
Returns the number of units the batch closed — the walk's headway check.

### dispatch.py: DispatchMixin.progress

**The two modes.** With a transport bound (`Orchestrator(store, transport=...)`)
the pass dispatches: the extraction walk sends its assembled `ExtractionRequest`
through the model-call seam, the deterministic walk completes its ledger
transition directly (no model call exists for it), one judged batch at the
governor's effective concurrency runs
through the model-call seam as assembled `ScoringRequest`s, and the run's
metrics flush to `run_metrics`
(`CT-ORCH-20`). With no transport the call is the **report-only surface** — the
(`CT-ORCH-20`). With no transport the call is the **report-only surface** — the
console's poll (`CT-CONSOLE-01`'s headless driver needs progress to work with no
console and no provider): the ledger is read and the report built, and nothing
is claimed, called or flushed.

**The pass drives the shared worker surface.** The walks and the judged batch
claim through `lease()` under `DISPATCH_OWNER` — the dispatch loop is a lease
holder like any worker, at-least-once and sweepable, so an interrupted pass's
in-flight units are the sweeper's ordinary reclaim, never a special case. The
claim pass walks the store's open runs (`#59`'s shape), so a poll nominally for
`run_id` serves whichever open run the walk reaches first; the single-run store
every dispatch case runs against makes the distinction invisible, and a
multi-run operator gets run-id-order service from the walk itself — recorded
interpretation, reconciled if a case ever pins multi-run dispatch.

progress() never raises for an expected provider condition: a rate limit or an
OOM is absorbed into the governor and the report (`RES-11`, `RES-13` —
"expected, not an error"). A failure that is not one of the taxonomy's two
transport conditions propagates: an unexpected exception mid-dispatch is a
defect, and absorbing it would be the silent-failure shape.

### enumeration.py: EnumerationMixin.enumerate_units

The pass is a pure function of the ledger's run row, the package catalog and the
cohort roster, walked in sorted order — so the same (cohort, package version,
config) enumerates byte-identical `work_id` sets (NFR-ORCH-05). Each unit is
inserted `INSERT OR IGNORE` keyed on `work_id`: a row already present is left
exactly as the ledger holds it — `done` stays done, `quarantined` stays
quarantined — which is what makes re-running a completed run a no-op that
produces no duplicate rows (FR-ORCH-03) and what resume's skip is made of
(FR-ORCH-02). The work-ID scheme is the invalidation: a changed input computes a
new `work_id` and the prior result is simply unreachable from the new unit
(NFR-EXTRACT-02/03) — there is no cleanup step to forget.

**Base shapes** (§3.7's data flow): a judged criterion (the catalog's
`kind='open'`) gets one `stage='extract'` unit with a null judge — extraction is
judge-independent by §7.2 Rule 2 — plus one `stage='score'` unit per panel arm up
to the criterion's base depth (`FR-SETUP-08`: 1 for `atomic`/`atomic_with_gate`,
3 for `holistic`). A criterion the package declares
`evaluation_mode='deterministic'` gets exactly one `stage='deterministic'` unit
with a null judge and no extraction and no scoring unit.
**Reconciliation closed (#369, retiring #59's note):** that note recorded the
design's `evaluation_mode` column as existing in no shipped schema, and stood the
equivalence `kind='mcq'` IS `evaluation_mode='deterministic'` in its place.
`FR-PKG-22` ships the column, so the equivalence is retired here and everywhere
that read it (`FR-ORCH-35`): shape and evaluation are separate claims, and a
package may declare a multiple-choice criterion whose options a panel weighs.
The migration's backfill makes the switch lossless — `deterministic` exactly where
`kind='mcq'` held — so no existing package changes behaviour. Extract and score
units are enumerated for **admitted** submissions only (`FR-ORCH-22`); the
deterministic unit is enumerated for every submission.

**The random arm** (`FR-ORCH-11`, this story): after a judged pair's base score
units, the pair draws at `HARNESS_ORCH_RANDOM_ARM_RATE` (default 0.07) — the
seeded draw `random_arm_selection` runs over the pair's key with the run's own
seed (`run_random_arm_seed`, derived from the run id), so the byte-identical
enumeration guarantee (NFR-ORCH-05) survives: the same inputs draw the same
pairs every pass, and `INSERT OR IGNORE` keeps a drawn pair's units from
duplicating. A drawn pair gets the widened panel an escalation would build
(1→3, 3→5), marked `origin='random_arm'` — the origin is why the work exists,
deliberately NOT a `work_id` input, so a base panel and a random-arm panel for
the same (submission, criterion, judge) share rows rather than
double-scoring. The draw consults neither confidence, nor the escalation
budget, nor a breaker (`CT-ORCH-15`: suppression would make the routing
policy unfalsifiable). Explicit escalations stay with `enqueue_escalation`
below — enumeration does not create them.

Commit batches of `HARNESS_ORCH_ENUM_COMMIT_BATCH` inserts keep one pass from
holding a write lock across 23,000 inserts; the knob exists so a slower box can
shrink it without a code change (NFR-ORCH-01 keeps per-unit cost trivial; the
benchmark is S-ORCH-03's, not this module's).

### escalation.py: EscalationMixin.enqueue_escalation

Arguments: the caller's transaction; the criterion score key, which is the `(run_id,
submission_id, criterion_id)` triple that names a `criterion_score` row (#359, FR-ORCH-34);
and the judges to add.

The new units are written inside the caller's transaction, because a criterion's score and
the escalation that widens its panel must both exist or both be missing after a crash
(CT-STORE-03). This method never commits, rolls back or opens a transaction. A caller
without one wraps the call in `cohort.transaction()`.

**The key names its run** (`FR-ORCH-34`, `CT-ORCH-26`): the escalation widens
that run's panel only, and the one-element tuple returned is that run's report.
The two-element ``(submission_id, criterion_id)`` form is **deprecated**: it
resolves the run from the ledger only when exactly one open run holds the
pair's score units, and raises `WorkLedgerError` — before anything is written
— when none or two or more do. A run whose base units all completed has
auto-completed (`_maybe_complete_run`), so a caller escalating it names the
run with the three-element key. A key no run holds a panel for raises
`EscalationPlanError` before anything is written.

**The decision, in order** (each stage reported in `gates` — seam 4):

1. *Plan.* The pair's prior judges are the score units the ledger enumerates
   for it — any origin, any status: the panel IS the enumerated units, not the
   verdicts landed so far. `escalation_plan` widens 1→3, 3→5 (never to two,
   `FR-ORCH-10`; `validate_escalation_plan` is the rule's pure surface) —
   with caller-named judges exactly, or the ladder's next two arms when
   `judges` is None. A plan that is not a widening, produces an even
   `judge_count`, or names a judge twice raises before anything is written
   (`EvenEscalationPlanError` is the subclass `TC-ORCH-20` asserts).
2. *Idempotence.* A pair already carrying escalation-origin units is a no-op
   (`admitted`, zero units): the widened panel exists, whatever path built it
   — including a random-arm draw, whose units are the SAME rows this path
   would insert (origin is not a `work_id` input, `CT-ORCH-15`), so a retried
   enqueue inserts nothing and reports honestly.
3. *Criterion breaker* (`FR-ORCH-13`). A latched breaker for the criterion
   halts immediately (`halted_by_breaker`); otherwise the first
   `ORCH_CRITERION_BREAKER_MIN_N` submissions processed for the criterion —
   by completion tick, the ledger's honest ordering — are checked with
   `criterion_breaker_tripped`, and a trip latches a content-addressed
   breaker row (INSERT OR IGNORE: one trip, one event) whose detail names the
   mark the design requires — `un-gradeable_by_panel`, remainder single-judge
   provisional. The mark on the criterion's RESULT is `M-AGG`'s artifact to
   write; the ledger's breaker row and this report's decision are what tell
   it to. Random-arm units are never counted here (origin='escalation'
   only) — the breaker gates the routing policy, not its control sample.
4. *The units.* The escalation's units are inserted **unconditionally** — the
   budget rations dispatch, not the plan write. The atomicity clause leaves
   no choice: a budget that refused the insert would put the escalation
   OUTSIDE the verdict's transaction, and a crash between the two would leave
   exactly the partial write `CT-STORE-03` forbids — a verdict recorded, its
   panel never widened. The caller's `expected_value` is recorded on the
   request row (content-addressed, INSERT OR IGNORE) as the ranking key the
   dispatch-time admission consumes.
5. *The budget, at dispatch* (`FR-ORCH-14`). The claim pass admits pending
   escalation units through `admit_escalations` only while the run's observed
   escalation rate is at or under `ORCH_ESCALATION_BUDGET`; above it the
   units stay pending — the remainder `FR-ORCH-14` marks provisional — and
   dispatch resumes in expected-value order when growth returns headroom.
   `escalation_budget_state` is the operator surface that shows the split;
   nothing here reads the budget, because the decision is dispatch's, not the
   plan write's.

The inserted units invalidate this run's dispatch-order cache (the claim pass
must see them). Pure policy — `escalation_plan`, `validate_escalation_plan`,
`criterion_breaker_tripped`, `admit_escalations` — does every decision here;
the method only reads the ledger and writes rows, and never contacts a judge
(`NFR-ORCH-04`: the escalation policy is evaluable with no model call).

### escalation_policy.py: escalation_plan

Pure — `TC-ORCH-20` and `TC-ORCH-32` evaluate it with no store and no model. The
result is the FULL widened panel in order: the criterion's prior judges followed by
the additions, so the plan's ``judge_count`` is ``len(result)`` and the odd-panel rule
reads directly off the return value.

**The rules, each from the design's own sentence:**

- The criterion escalates **from one judge to three, never to two** — the canonical
  rung widens by two. With no caller-named judges the plan widens by exactly two,
  taken from the run panel's unused arms first, then derived extension arms
  (`_extension_arms`). An odd panel widened by an even addition stays odd, so the
  default ladder never leaves the odd numbers: 1 → 3 → 5 → …
- **A plan producing an even ``judge_count`` is rejected** — `EvenEscalationPlanError`,
  the exact exception `TC-ORCH-20` asserts for counts 2 and 4. A two-way tie broken by
  rule is a coin flip presented as a judgement; the ledger's CHECK (`CT-AGG-03`) is
  the backstop, this refusal is the front.
- A plan that does not widen (equal or smaller than the panel it starts from) is
  refused with `EscalationPlanError`: an escalation that adds nothing looks like work
  while being the silent no-op shape.
- A criterion with **no judges yet** (prior count 0) has no band to widen — refusing
  rather than treating first enumeration as escalation keeps "escalate" meaning
  *widen a panel that exists*.
- A caller-named judge already on the panel is refused (`EscalationPlanError`), and so
  is a plan naming the **same judge twice among the additions** (`EscalationPlanError`):
  one judge, one seat — a doubled seat would let one verdict outweigh another, and a
  doubled seat can also hide an even distinct-judge panel behind an odd `len`.

An even PRIOR panel is refused with `EvenEscalationPlanError` as well: the ledger
should never hold one (the CHECK refuses the write), and a plan built on top of a
corrupted panel would launder it rather than surface it.

### leasing.py: LeasingMixin._claim_pass

Each claim transitions the unit `pending → leased` with the worker as `lease_owner`
and an expiry `ORCH_LEASE_SECONDS` (env: `HARNESS_ORCH_LEASE_SECONDS`) out, derived
from `M-STORE`'s **monotonic counter** — the store's `LeaseClock.issue()` persists
the expiry before the claim commits, so a lease that survives an uncontrolled kill
still compares honestly after a restart whose wall clock moved backwards
(`FR-STORE-11`, `CT-STORE-14`).

**The walk and its order (#59's two-sweep plan).** Cohorts are walked sorted, and
within a cohort each open run individually — the dispatch order is a function of
the run's own package (its dependency topology and criteria), so candidates are
gathered, ordered and claimed per run, in `run_id` order. A paused run schedules
nothing (`CT-ORCH-12`): its units are never candidates. The stage's order is
`_dispatch_order`'s: Sweep 1 in topological dependency order (`FR-ORCH-05`),
Sweep 2 gated on done extraction and then keyed judge → question → criterion
(`FR-ORCH-06/07`); every other stage keeps `work_id` order. The claim applies the
order front to back, so the units a claim hands out are the sweep's head.

**Exclusivity is the guard on the write**, not the read: candidates are read
`status = 'pending'`, the expiry is issued, and the claim is an
`UPDATE ... WHERE status = 'pending'` whose `changes()` — read in the same
transaction — decides whether *this* claim won. A claim that loses the guard
writes nothing and returns nothing; the unit's new holder is whoever won. The
lost-guard race leaves the persisted high-water raised by one unused expiry —
the store's own stated conservatism (a restart expires every outstanding lease,
`CT-STORE-14`), arrived at from the harmless side: a raised counter can only make
the sweeper *more* willing to reclaim, never less.

**The order cache** (`NFR-ORCH-01`). The sweep key is not expressible in SQL —
it reads the run's package topology and panel — so the ordered candidates are
derived in Python, and deriving them per poll made a one-at-a-time drain
quadratic (re-reading and re-sorting the whole pending set per claim: measured
5.3 ms/unit at 750 pending, over budget, and growing). The ordered ready list
is therefore cached per `(run_id, stage)` and drained front to back across
passes; the guard on the write stays the only correctness check. The cache's
invalidation set is exactly the events that can falsify it:

- **Exhaustion** — the remaining candidates were claimed; new units (a later
  enumeration) are discoverable only from the ledger, so the entry is dropped
  and the next pass re-reads.
- **A lost guard** — another writer won a unit this cache held pending, so
  the view of pending is stale; the entry is dropped wholesale.
- **A requeue** — a failure below the ceiling (`fail`) or a sweeper reclaim
  returns a unit this cache has already popped to `pending`; the run's entries
  are dropped so the next pass re-reads — a requeue the cached order cannot
  see is a unit lost to the run (`TC-ORCH-18`).
- **A budget deferral** (`FR-ORCH-14`) — an escalation unit the dispatch gate
  deferred was skipped mid-pass; the entry is dropped so the next pass
  re-derives with the current observed rate. Unlike the Sweep 2 gate, this
  gate's answer can move both ways (completions raise the rate, growth lowers
  it), so a deferral the cached order could not revisit would be a deferral
  that never lifts — the provisional remainder must stay recoverable.
- **Re-enumeration** — `enumerate_units` drops the run's entries, because it
  may add rows this cache has never seen.

An empty order is never cached: readiness only grows, but it grows outside
the cache's view, so a stage whose candidates are all gated out re-derives
per pass — caching the empty list would starve the newly ready. What the
cache deliberately does **not** re-check per pass is the Sweep 2 gate: the
gate was evaluated at derivation, and a unit ready then stays ready (an
extraction's `done` is terminal within a run), so serving the cached order
can never dispatch a judge over absent evidence; only the not-yet-ready set
can change, and those units are not in the cache at all.

### leasing.py: LeasingMixin._dispatch_order

`Sweep 1` (`extract`) is **topological order over the criterion dependency
graph** (`FR-ORCH-05`) — a priority order over pending units, not a completion
gate: the design dispatches extraction in dependency order, and nothing in it
says a criterion's extraction waits for another's to finish. `Sweep 2`
(`score`) first **gates** (`FR-ORCH-06`) — a score unit is ready only when its
own criterion's extraction and every extraction in its dependency closure, for
its submission, are `done` — and then **orders by the fixed key and nothing
else** (`FR-ORCH-07`): judge model outermost, then question, then criterion, the
submissions parallel beneath. No criterion-graph term appears in the key; the
graph was Sweep 1's, and re-ordering scoring by it would cost cache locality for
nothing. Every other stage (the deterministic units, and the stages later stories
add) keeps `work_id` order.

The gate reads `done` on the extraction units of the run — one indexed query per
pass (`select_not_done_extracts`); a quarantined extraction is not `done`, so the
scoring it feeds stays gated until an operator re-queues it: the gate never
scores over nothing. Deterministic criteria carry no extraction unit, so a
dependency on one is satisfied vacuously — there is nothing to wait for.

**Interpretations recorded (#59):** the gate is per (criterion, submission) — a
score unit reads that submission's evidence — and it includes the criterion's own
extraction plus the transitive closure of its dependencies; the requirement's
"every extraction unit that criterion depends on" leaves direct-vs-transitive and
own-extraction open (`TC-ORCH-07` discloses the same), and this reading is the
one under which no judge ever reads absent evidence. Within a `(judge, question,
criterion)` group the submission order is `work_id`'s — `CT-ORCH-21` explicitly
does not promise submission order inside a batch. The key's judge term is the
judge's position in the run's panel order (the dispatch order, not the build
id's lexical order), and its criterion term is the criterion id ascending;
`FR-ORCH-07` fixes the levels, not the within-level measure, and these are the
stable choices.

### leasing.py: LeasingMixin.fail

The unit's `attempts` increments; below `ORCH_MAX_ATTEMPTS`
(env: `HARNESS_ORCH_MAX_ATTEMPTS`) it returns to `pending` and is claimable
again; at the ceiling it becomes `quarantined` with `last_error` retained —
the operator surface can say *what* happened, not just that something did. Both
arms clear the lease columns; the run continues either way — "fail the unit,
never the run" (`NFR-ORCH-03`) is the whole point of the taxonomy, so **no arm
of this method raises into the caller's loop over a unit's own failure**: the
only raise is for a work id that resolves to no unit at all. A won report also
drops this run's dispatch-order cache entries — the requeued unit must be
visible to the very next claim pass (`TC-ORCH-18`).

**A failure report wins over a live lease.** The design fixes this signature at
`(work_id, error)` — no owner identity — so the report cannot name its holder,
and the ledger treats it as authoritative about the attempt: the unit requeues
(or quarantines) and its lease columns clear even if another worker currently
shows as holding them. At-least-once leasing makes the holder tolerate losing
the claim; its own next heartbeat is a named refusal (the guard catches it), so
the stale holder cannot keep working silently.

Races are absorbed by the ledger's state at write time, not raised: a failure
for a unit that completed (a completion beat this report — under
`CT-ORCH-04`'s at-least-once that is an expected outcome, and the real result
exists), one already quarantined (the record stands; a duplicate report from a
double-run worker must not double-count it), or one whose state moved between
the read and the guarded write — all no-ops. The count and the ceiling
comparison are computed **inside the statement** from the row as the write sees
it, so two concurrent reports cannot both read the same count and lose an
attempt; quarantine lands on the report that actually reaches the ceiling.

### leasing.py: LeasingMixin.lease

The claim mechanics — the `pending → leased` transition, the expiry derived from
`M-STORE`'s monotonic counter, the guarded write that makes one claim win — are
`_claim_pass`'s, stated once there. This surface adds two things over the raw
pass:

**Self-healing enumeration.** A first pass that claims nothing triggers the
base enumeration `resume()` uses — idempotent by construction — but only for
runs whose ledger holds no units at all **and** whose cohort holds an
admissible submission (`_runs_missing_units`: a cohort that is all-refused
enumerates to the empty set legitimately, and a drained poll must not pay
for re-deriving that), and claims again, so a caller that created a run and
leased receives units without a separate enumerate step while a drained poll
late in a large run pays one claim query and one existence probe, never a
full pass. An empty return after that is a true empty (the stage's units are
done, in flight, or the run is not dispatching), not a bookkeeping gap.

**The unit handed over.** The returned units carry `student_ref`;
`student_name` and `submission_text` stay `None` — the ledger holds neither
(Tier C carries pseudonymous refs, the text lives in the documents), and
resolving them is the assembler's act at dispatch, `M-EXTRACT`'s territory.
#57's WorkUnit docstring expected #58 to resolve them; that expectation is
hereby reconciled to the schema — the lease resolves the identity, the
assembler the words.

Leasing is **at-least-once with an expiry** (`CT-ORCH-04`): an abandoned lease
returns to `pending` via `sweep_expired_leases()` and the unit is claimed again.
Workers must therefore be safe to run twice on the same unit — a precondition on
the worker, not a guarantee from the orchestrator.

### orchestrator.py: Orchestrator

Main operations:

- `create_run`, `enumerate_units`, `lease`, `complete`, `fail`: the work ledger.
- `start(run_id)`: moves a run from `pending` to `running` and shows its estimated cost
  before anything is dispatched (FR-ORCH-15).
- `pause(run_id, cause=...)`: writes a control row that the claim loop applies. A run
  pauses when the provider is unavailable (FR-ORCH-16), its model build changed
  (FR-ORCH-17), the operator asks, or its frozen cost ceiling would be crossed
  (CT-ORCH-12). Nothing is ever substituted.
- `resume()`: takes no arguments and continues every open run on its original frozen
  backend. Pausing only touches lifecycle columns, so there is no way to switch backends
  on resume.
- `enqueue_escalation`: adds judges to a panel, subject to the random arm, the criterion
  breakers and the run-wide escalation budget.
- `progress(run_id)`: one dispatch pass, then a progress report.

Control rows written while nothing is dispatching wait in `run_control` and are applied on the
next read (CT-ORCH-13).

**Recorded interpretations (#62) — dispatch, residency, concurrency, progress.**
The dispatch loop's model-call seam takes the stage's ASSEMBLED closed request —
`ScoringRequest` via `M-JUDGE`'s `ScoringWorker.assemble`, `ExtractionRequest`
via `M-EXTRACT`'s `assemble_request` (`FR-ORCH-20`'s own wording: "exactly one
submission per scoring or extraction request" — what is dispatched is the
request, and its exactly-one form is assertable only over the closed type,
`CT-JUDGE-02`). The loop's classification, batching and residency are untouched
by the payload's shape; deterministic units cross nothing (their evaluation
makes no model call), so the deterministic walk completes directly. Residency
batches **judge models only**:
`residency_policy` lists the roles permitted resident, and the units this loop
dispatches are score units whose `judge_id` names a model — the transcriber's
residency is the transcription stage's, not yet this module's. A judge's
**batch** is its dispatchable work: the units the ready order hands out for it,
plus the ones in flight; a gated or budget-deferred pending unit is not
dispatchable (it may never become ready without an operator) and cannot hold a
model resident — a residency held over undispatchable work starves every judge
behind it — and when gated work becomes ready the model reloads to serve it. A
residency swap's
duration is the wall time of the first model call after the swap — the load rides
that call; a swap whose first call is still to come records the count and adds the
duration when the load is actually paid. The dispatch loop's extract walk sends
the assembled `ExtractionRequest` (extraction IS a model call — `FR-ORCH-20`
covers extraction requests); the deterministic walk is the ledger transition
itself, completed with no transport (a deterministic criterion's evaluation makes
no model call): completing the transition is what unlocks the judged batch, and
the walks are bounded per pass by `HARNESS_ORCH_DISPATCH_WALK_BATCH`. The
concurrency governor's cap is per run, starts at the run's frozen
`concurrency_ceiling` (never the environment's — `FR-CONF-07`'s freeze), divides
once per pass on any rate-limited/OOM call (floor 1) and is clamped per pass while
M-STORE signals write backpressure (`CT-STORE-06`: a signal to reduce, never a
fault — the clamp is sensed at the pass's start and does not persist). The report's
`concurrency` is the cap the NEXT pass will run at (post-clamp, post-reduction) —
the operator reads the reduction that takes effect. The OOM remedy requeues the
judge's in-flight units without consuming attempts (the box's condition is not the
unit taxonomy's, §9.11), halves the cap, and at the drop threshold removes the
judge from the run's `panel_config` as a strict subset (never below one judge) —
its un-run units stay in the ledger for an operator to re-queue under a smaller
panel, never silently discarded. The completion predicate on the report is
**ledger-derived, not run-status-derived** (`FR-ORCH-12`): nothing pending and no
in-flight scoring judgment — a score unit in flight can still disagree with its
panel and spawn an escalation. The report's estimate feeds
`estimated_completion_seconds` with the ledger's own totals. `progress()` with no
transport dispatches nothing: it is the report-only surface (the console's poll).

**Recorded interpretations (#61).** The ceiling comparison is strict `>` per
dispatch (a dispatch landing exactly at the ceiling proceeds; the run pauses once
spend sits at the ceiling) — the breaker's and budget's reading of an "at or above"
boundary; the at-ceiling sense fires only when the claim actually moved spend (a
not-billed figure adds nothing and consumes no ceiling, so replayed work drains
past an at-ceiling pause without re-pausing it). The estimate displayed at start is
the sum of the units' seam figures. Every pause and resume — operator, sensed, or
explicit `resume(run_id)` — is written as a `run_control` row and effected through
the control-read pass (request ≠ effect, `CT-ORCH-13`); a resume supersedes the
pauses queued before it (latest control intent wins, bounded by request time), and
a queued pause on a `pending` run is honoured at `start` (the machine's declared
edges have no `pending → paused` from mid-flight); a queued pause on a `running`
run applies at the next claim pass; an operator's pause stays sticky across a
no-argument `resume` (a stop outranks a scheduler's restart). Run-level `complete`
is probed after every won lifecycle write and fires only for a `running` run with
at least one unit and none open (quarantined units are not open — their record
stands).

The store is injected (`CLAUDE.md` seam 2). Nothing here opens a network connection
or contacts a judge: enumeration is a pure function of the ledger, the package
catalog and the roster, over an injected store, and every escalation decision is
pure policy over ledger state (`NFR-ORCH-04`). The provider seam is injected the
same way and consulted only for cost figures — no dispatch, retry or pause decision
ever asks the provider what to do.

### run_lifecycle.py: RunLifecycleMixin.create_run

`run_id` is minted as ``run-<uuid4 hex>`` — two runs of the same (cohort, package
version, config) are *different runs* and must not share work ids, which is why
`run_id` is a hash input. Keyword override for a caller (or test) that names its
own. The row is born `status='pending'`; `FR-ORCH-25`'s status transitions are
control-row territory (#61) and #57 flips none of them.

`provider_config` is the run's frozen backend snapshot, serialized canonically —
the HLD's "provider, per-judge model ref, retention setting in force, concurrency
cap, cost ceiling", every field the audit may one day ask the run to account for.

The run start is logged here too: exactly one `run_start` line through
`aeh.conf.log_run_start`, whose returned summary is the one the audit record stores.

The audit record is written here, on the durable tier, by `record_run_start` —
the run's configuration is frozen the moment the row exists, and the audit trail
should not depend on a later story landing. The two writes are two transactions
on two tiers (a cross-tier transaction is refused by design, `CT-STORE-06`): the
run row commits first, so a crash between them leaves a run whose audit record
is absent — visible in the durable tier, and repairable without touching the
ledger: read the run's id back from the run table and call
`record_run_start(store, cfg, run_id=<that id>)` to write the missing record.
Creating the run "again" would mint a second `run_id` and a second audit
record, which is not a retry. Never a half-written ledger.

### run_lifecycle.py: RunLifecycleMixin.pause

The two-step is the point, not overhead: the control row is the durable request
(`CT-ORCH-13` — request ≠ effect, the orchestrator reads control rows on its own
schedule), and applying through the same pass the claim loop reads means a pause
lands identically whether it was requested a second ago or written while the
orchestrator was down. On a `running` run the read pass runs immediately and the
effect is immediate; on a `pending` run the row stays queued and the effect lands
at the next `start` — a run that has not begun dispatching is not torn down for a
stop it can simply honour first. An already-`paused` run records the request as
satisfied (applied at once): the state the request asks for already holds.
Terminal states (`complete`, `failed`) refuse with `RunStateError` — a stop is
not a result.

`cause` is one of `CT-ORCH-12`'s four pause conditions: a `ProviderUnavailableError`
(`FR-ORCH-16`), a `BuildChangedError` (`FR-ORCH-17`), the cost ceiling (the claim
pass pauses on its own — it writes a sensed pause naming spend and remaining, never
calling this), or `None` for an operator request. The rendered reason lands on the
run row (`pause_reason`) so the operator surface can say *why* the run stopped,
never just that it did.

The pause touches lifecycle columns only — never `provider_config`/`panel_config`
(`FR-ORCH-16`'s resume-same-backend: the backend the run was frozen with is the
backend it resumes with, because nothing here can change it). Returns the status
the run row carries after the call.

### run_lifecycle.py: RunLifecycleMixin.resume

With no argument, the open runs are discovered from the ledger itself: every run
whose status is `pending`, `running` or `paused`, across every cohort file the
store holds. No side file, no cursor, no operator input — `resume` requires no
bookkeeping beyond the ledger (`FR-ORCH-02`), and an argument would be a place
for an operator to be wrong under time pressure.

Resuming re-enumerates, and re-enumeration is where "skip every unit with
`status='done'`" is realized: a done unit's `work_id` is already in the ledger,
`INSERT OR IGNORE` leaves it untouched, and no result is recomputed or duplicated.
A completed run resumed — by discovery's omission or by explicit id — enumerates
to a no-op. Invoked when nothing is wrong, it inserts nothing and changes
nothing: the safe no-op the acceptance criterion asks for.

**Control rows are both the input and the effect here** (`CT-ORCH-13`): the
no-argument form reads each open run's unapplied control rows first — a resume
written while the orchestrator was down flips its paused run back to `running`
through the same guarded transition an explicit resume uses. **An explicit
`run_id` is itself written as a control row** — request ≠ effect applies to
every resume, no-argument or named: the row is the durable request, the read
pass the effect. On a paused run the pass effects the `paused → running` edge
(`FR-ORCH-25`) and supersedes the pauses queued before it; on a pending or
running one the request is vacuous and is marked applied. Either way the resume
re-binds to nothing and consults no current configuration — the run's frozen
`provider_config`/`panel_config` are the backend (`FR-ORCH-16`'s
resume-same-backend is structural: the lifecycle transitions write status
columns only, so *no code path exists* by which a resume could substitute a
backend). An operator's pause stays sticky across a restart:
the no-argument form applies control rows and enumerates but does not auto-unpause
a run nobody asked to resume — a stop an operator requested outranks a scheduler's
restart.

The dispatch half of resume — leasing the pending units to workers — is #58's
`lease` landing on this same ledger; the ledger half (nothing done is re-run,
nothing lost, nothing duplicated) is complete here.
