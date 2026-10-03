"""What M-ORCH returns: progress, enumeration and sweep reports, escalation reports and state."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, fields as dataclass_fields
from typing import Any, Mapping


# --- the worker-facing report types -------------------------------------------------------------


@dataclass(frozen=True)
class WorkError:
    """What a worker reports when a unit fails (input to FR-ORCH-18).

    One field, deliberately: the ledger retains the **message** — `last_error` is what
    the operator surface reads when it asks what happened to a quarantined unit, and a
    message is the only part of a failure that stays true after the process that hit it
    is gone. A worker may also pass a bare string; the orchestrator stores what it is
    given rather than wrapping it in this type's repr.
    """

    message: str


@dataclass(frozen=True)
class WorkResult:
    """What a worker reports when a unit completes.

    Deliberately minimal in this slice: the **payload** each stage persists is that
    stage's to own (extraction spans, verdicts — #68 and onward land beside `M-EXTRACT`
    and `M-JUDGE`), and Tier C holds none of it by design. The ledger's `complete` half
    records the transition — `done` is the state resume skips (`FR-ORCH-02`) — and the
    stages that own payloads write them through their own surfaces.
    """

    summary: str = ""


# --- the enumeration report ---------------------------------------------------------------------


@dataclass(frozen=True)
class EnumerationReport:
    """What one enumeration pass did (seam 4).

    The `gates` dict is deliberately per-gate rather than one boolean — the
    `IngestReport.gates` precedent (`CT-INGEST-08`): a bare `status=enumerated` on top of
    an empty report is the top silent-failure trap, so each stage of the pass says what it
    saw. `work_ids` is the sorted set the pass computed, which is what NFR-ORCH-05's
    byte-identical comparison is over (a set-of-bytes comparison, never a count).

    `status` is `"enumerated"` when the pass inserted at least one new ledger row and
    `"no-op"` when every unit the pass computed was already present — the shape a
    completed run's re-run must have (FR-ORCH-03). Either way the report is complete:
    a no-op still names its counts, its gates and its `work_ids`.
    """

    run_id: str
    status: str
    work_ids: tuple[str, ...]
    units_enumerated: int
    units_inserted: int
    units_already_present: int
    by_stage: Mapping[str, int] = field(default_factory=dict)
    by_status: Mapping[str, int] = field(default_factory=dict)
    gates: dict[str, str] = field(default_factory=dict)


# --- the sweeper's report ------------------------------------------------------------------------


@dataclass(frozen=True)
class SweepPlan:
    """The ordering data for both sweeps of one package version, computed once (FR-ORCH-05/07).

    Everything the dispatch order needs, read off the immutable package and cached:
    `extract_positions` is the criterion's position in `M-PKG`'s topological order
    (`FR-PKG-05` — dependencies before dependents, Kahn's with sorted emission, so the
    order is reproducible); `question_of` maps a criterion to its question, `FR-ORCH-07`'s
    second key; `dependency_closure` maps a criterion to the transitive set of criteria it
    depends on — the extraction units whose completion gates its scoring (`FR-ORCH-06`).

    The closure is computed here, not in `M-PKG`: the topology is `M-PKG`'s data (this
    module consumes it rather than re-deriving the graph), and what the *gate* needs —
    transitive closure over that topology — is scheduling policy, this module's own.
    """

    extract_positions: Mapping[str, int]
    question_of: Mapping[str, str]
    dependency_closure: Mapping[str, frozenset[str]]


@dataclass(frozen=True)
class SweeperReport:
    """What one lease-expiry sweep did (seam 4).

    A bare count would be the silent-failure shape — a sweep that examined nothing and
    requeued nothing is indistinguishable from one that never ran — so the report names
    all three outcomes: `examined`, `requeued`, `still_held`, plus the `gates` detail
    (the `EnumerationReport`/`IngestReport.gates` precedent).

    `still_held` is derived (`examined - requeued`), and a unit that completes or
    moves during the sweep counts as still held: the report is a reading taken at
    sweep time, the ledger row is the truth. Report-level approximation, stated
    rather than hidden.
    """

    examined: int
    requeued: int
    still_held: int
    gates: dict[str, str] = field(default_factory=dict)


# --- the progress report and the dispatch loop's report surface (#62) ----------------------------


#: The operator extras `ProgressReport` serves beside the designed field set. They are
#: deliberately NOT dataclass fields — the field set is §3.7's, asserted by set equality
#: (TC-ORCH-26), and these ride outside it through the mapping protocol.
PROGRESS_EXTRA_FIELDS = ("complete", "concurrency", "by_unit", "alerts")


#: The per-student figure FR-ORCH-23 forbids, named once so the prohibition is
#: checkable: neither the type's fields nor the mapping's keys may carry it.
_PROGRESS_FORBIDDEN_TOKENS = ("student", "submission", "learner")


def estimated_completion_seconds(
    *,
    completed: int,
    remaining: int,
    elapsed_seconds: float,
    escalation_rate_so_far: float,
) -> float:
    """The run's estimated time to finish, from the throughput so far adjusted for the escalation
    rate so far (FR-ORCH-24). A pure function (NFR-ORCH-04).

    The naive figure is `remaining / observed_throughput`, with the throughput the
    run has actually sustained (`completed` units over `elapsed_seconds`) — not the
    plan's optimism. Each escalation widens a pair's panel from one judge to three
    (`FR-ORCH-10`: one to three, never to two), so a widened unit becomes three: the
    observed rate grows the remaining work by `(1 + 2 * rate)` — one added unit per
    pair plus the pair's own re-judgment. At a 0% rate the adjustment is a no-op and
    the estimate IS the naive one; at 15% of 200 remaining it adds 60s; the growth
    the escalations commit the run to is exactly what a naive estimate hides
    (TC-ORCH-27).

    No completed work or no elapsed time is no observed throughput — 0.0, not an
    infinity extrapolated from nothing.
    """
    if completed <= 0 or elapsed_seconds <= 0:
        return 0.0
    naive = remaining * elapsed_seconds / completed
    return naive * (1.0 + 2.0 * escalation_rate_so_far)


@dataclass(frozen=True)
class ProgressReport:
    """The progress report `progress(run_id)` returns (§3.7, FR-ORCH-23).

    The field set is the design's, exactly and deliberately: the position fields
    (which stage, which criterion, which judge the open work sits at), the four
    status totals, the observed escalation rate and the adjusted estimate. It
    carries **no per-student figure** — `FR-ORCH-23`'s prohibition, paired with
    `R63`: the console renders what the type holds, so the data must not exist to
    render (`FR-CONSOLE-08`).

    **The mapping behavior is deliberate** (recorded interpretation): the report is
    the §3.7 dataclass AND the query surface the console reads — field access
    (`report.complete`) and mapping access (`report["done"]`, `report.keys()`) are
    both first-class, with the three operator extras (the completion predicate, the
    dispatch's current concurrency, the per-unit counts) riding OUTSIDE the field
    set. `dataclasses.fields(ProgressReport)` stays exactly the designed eleven;
    an added per-student field would fail that set equality, and the mapping's
    keys are checked by the same prohibition.
    """

    stage: str
    criterion_index: int
    criterion_total: int
    judge_index: int
    judge_total: int
    done: int
    in_flight: int
    pending: int
    quarantined: int
    escalation_rate_so_far: float
    estimated_completion: float

    def __post_init__(self) -> None:
        # The extras ride outside the field set: attached per instance, not declared,
        # so the field enumeration the prohibition is asserted over stays the
        # design's. A report built without dispatch state reports what the ledger
        # says: not complete, no measured concurrency yet.
        object.__setattr__(
            self,
            "_extras",
            {
                "complete": self.pending == 0 and self.in_flight == 0,
                "concurrency": 0,
                "by_unit": {},
                # `FR-ORCH-32`: an extra, not a field. The designed field set is exactly
                # eleven and `FR-ORCH-23`'s per-student prohibition is asserted over that
                # enumeration, so alerts ride beside the other operator extras. A report
                # built without run state has no alerts — not "no problems", simply
                # nothing evaluated; `progress()` attaches the evaluated tuple.
                "alerts": (),
            },
        )
        for key in (*PROGRESS_EXTRA_FIELDS, *(f.name for f in dataclass_fields(self))):
            text = str(key).lower()
            offending = [t for t in _PROGRESS_FORBIDDEN_TOKENS if t in text]
            if offending:
                raise ValueError(
                    f"ProgressReport key {key!r} carries a per-student token "
                    f"({offending[0]!r}) — FR-ORCH-23: no per-student completion "
                    "figure exists on the type, so the console cannot render one (R63)."
                )

    # -- the operator extras, and the mapping protocol over fields + extras ------

    def _map(self) -> dict[str, Any]:
        mapped = {f.name: getattr(self, f.name) for f in dataclass_fields(self)}
        mapped.update(self.__dict__.get("_extras", {}))
        return mapped

    def __getattr__(self, name: str) -> Any:
        # Only reached for names that are not dataclass fields (normal lookup
        # already failed): the extras, and nothing else.
        extras = self.__dict__.get("_extras")
        if extras is not None and name in extras:
            return extras[name]
        raise AttributeError(
            f"{type(self).__name__} has no field or extra named {name!r} — the "
            f"designed fields are {tuple(f.name for f in dataclass_fields(self))} "
            f"and the operator extras are {PROGRESS_EXTRA_FIELDS}."
        )

    def __getitem__(self, key: str) -> Any:
        try:
            return self._map()[key]
        except KeyError:
            raise KeyError(key) from None

    def __contains__(self, key: object) -> bool:
        return key in self._map()

    def __iter__(self) -> Any:
        return iter(self._map())

    def __len__(self) -> int:
        return len(self._map())

    def keys(self) -> Any:
        return self._map().keys()

    def values(self) -> Any:
        return self._map().values()

    def items(self) -> Any:
        return self._map().items()

    def get(self, key: str, default: Any = None) -> Any:
        return self._map().get(key, default)


# --- the escalation reports (CLAUDE.md seam 4) ---------------------------------------------------


#: What `enqueue_escalation` decided. Both outcomes are named, never absorbed: the
#: breaker's halt is the visible degradation `CT-ORCH-16` demands — a caller that
#: receives `halted_by_breaker` knows scrutiny was reduced and why (the mark on the
#: result is M-AGG's to write). The budget does not decide here: the enqueue writes
#: the plan the verdict's transaction needs (`CT-ORCH-08`/`FR-ORCH-09`), and the
#: budget rations DISPATCH — the claim pass defers pending escalation units through
#: `admit_escalations`, the remainder provisional (`FR-ORCH-14`).
DECISION_ADMITTED = "admitted"


DECISION_HALTED_BY_BREAKER = "halted_by_breaker"


#: The widening would need a judge seat the caller has no real model for (`seats=`): nothing
#: is written, and the caller's score stands for review. Only reached when units WOULD be
#: inserted — a pair already widened is `admitted` as the no-op it is, whatever `seats` says.
DECISION_NO_REAL_SEAT = "no_real_seat"


#: The content-address space of escalation bookkeeping: request and breaker rows are
#: keyed on a sha256 over what they are ABOUT — never on the wall clock or a uuid — so a
#: retried enqueue or a second trip evaluation addresses the SAME row (`INSERT OR
#: IGNORE` then makes the retry a no-op, `FR-ORCH-03`'s idempotence carried into the
#: escalation path). `kind` namespaces the two id spaces; the module name prefixes the
#: digest so these cannot collide with anything else keyed by bare sha256.
_CONTENT_ID_KIND_REQUEST = "escalation_request"


_CONTENT_ID_KIND_BREAKER = "criterion_breaker"


_CONTENT_ID_KIND_REPLACEMENT = "replacement_arm"


def _content_id(kind: str, *parts: str) -> str:
    """A content-based id for escalation records: a sha256 of the kind and the row's identifying
    parts, joined with `\x1f`. The same inputs always give the same id."""
    digest = hashlib.sha256()
    digest.update(b"aeh.orch\x1f")
    digest.update(kind.encode())
    for part in parts:
        digest.update(b"\x1f")
        digest.update(part.encode())
    return digest.hexdigest()


#: FR-ORCH-43's decisions: one arm inserted, a request already made for this quarantine
#: (nothing inserted), or refused (budget or breaker).
REPLACEMENT_INSERTED = "inserted"


REPLACEMENT_ALREADY_REQUESTED = "already_requested"


REPLACEMENT_REFUSED = "refused"


#: The pair has no quarantined score unit: an even panel this path did not cause, which the
#: caller treats as the defect it is (FR-PIPE-18: EvenPanelError still pauses).
REPLACEMENT_NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class ReplacementArmReport:
    """What one `enqueue_replacement_arm` call did (FR-ORCH-43, CT-ORCH-33, seam 4)."""

    run_id: str
    submission_id: str
    criterion_id: str
    decision: str
    arm: str | None
    reason: str
    quarantined: int
    gates: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EscalationReport:
    """What one escalation call did (FR-ORCH-09/10/13/14, seam 4).

    `decision` is the enqueue's outcome — `admitted` (units inserted), `queued` (over
    budget, held in the persisted queue in expected-value order; the caller marks its
    result provisional), or `halted_by_breaker` (the criterion breaker has tripped;
    escalation halts for the criterion). The numbers beside the decision — the rate, the
    budget, the queue depth, the judge counts — are what make the decision auditable:
    a bare `status=refused` on top of an empty report is the silent-failure shape the
    `IngestReport.gates` precedent exists to prevent.
    """

    run_id: str
    submission_id: str
    criterion_id: str
    decision: str
    prior_judges: tuple[str, ...]
    added_judges: tuple[str, ...]
    judge_count: int
    units_inserted: int
    expected_value: float | None
    escalation_rate: float
    escalation_budget: float
    queue_depth: int
    breaker_tripped: bool
    gates: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BreakerTrip:
    """One tripped criterion breaker, as the operator sees it (FR-ORCH-13).

    The alert the design names ("any criterion tripping the circuit breaker") reads
    these rows: which criterion, when, and the window arithmetic that tripped it —
    `detail` carries the numbers so the alert answers "why", not just "what".
    """

    run_id: str
    criterion_id: str
    kind: str
    tripped_at: str
    detail: str


@dataclass(frozen=True)
class EscalationBudgetState:
    """The run-wide escalation budget's state, as the operator sees it (FR-ORCH-14).

    The rate-above-budget alert's source (`CT-ORCH-16`: both breakers degrade visibly):
    the processed/escalated pair the rate is computed from, the budget it is compared
    against, the queued remainder, and the criteria whose breakers have tripped. Read
    from the ledger every time — no side-file counters (`FR-ORCH-02`).
    """

    run_id: str
    processed_results: int
    escalated_results: int
    escalation_rate: float
    budget: float
    over_budget: bool
    queued_requests: int
    tripped_criteria: tuple[str, ...]
    provisional_pairs: tuple[str, ...] = ()
    gates: dict[str, str] = field(default_factory=dict)
