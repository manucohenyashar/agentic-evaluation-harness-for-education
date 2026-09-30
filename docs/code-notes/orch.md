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
