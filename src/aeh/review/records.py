"""What the review queue shows and writes: items, groups, labels, reports, and the write set."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


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
