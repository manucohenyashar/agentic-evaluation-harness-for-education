"""What the review queue shows and writes: items, groups, labels, reports, and the write set."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


# --- the queue's wire shapes ------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewItem:
    """One flagged criterion as the queue shows it (design §3.15), with the fields the ranking uses
    (FR-REVIEW-03, FR-AGG-06). `state` is kept so `ungradeable_by_panel` can be shown distinctly
    (CT-AGG-07)."""

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
    """A group of items with identical signatures, shown as one entry (FR-REVIEW-05).

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
    """One stage of a queue build (NFR-REVIEW-01). `name` is the stable identifier the event-order
    check reads (CT-REVIEW-02)."""

    name: str
    detail: str = ""


@dataclass(frozen=True)
class ReviewQueue:
    """The built queue: the five declared fields (design §3.15) plus the groups, the build's timing
    and the per-stage trace."""

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
    """The label an action writes: the eight declared fields (FR-REVIEW-09), who made it
    (NFR-REVIEW-03), and identity fields. `new_points` comes from the pinned band mapping
    (CT-PKG-05), and is None only when no band was recorded. It has none of the fields CT-REVIEW-07
    forbids: no confidence, no narrative, no system-side points."""

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
    #: The cell the label is about, on every label (FR-REVIEW-25, #867). A blind
    #: label's is resolved by the service, never by the session, which still
    #: cannot reach a score row (CT-REVIEW-09).
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
    """One criterion's row in the criteria ranking, matching `aeh.agg.CriterionEscalationRank`
    (CT-STATS-09). `override_rate` is None exactly when there was no figure; a real zero stays zero
    with `no_data=False`."""

    criterion_id: str
    override_rate: float | None
    no_data: bool


@dataclass(frozen=True)
class SupersededScore:
    """What `escalate` returns: the score id, and the version that every earlier-built queue now
    holds out of date (CT-REVIEW-15)."""

    score_id: str
    version: int


@dataclass(frozen=True)
class CounterEmission:
    """One counter emission (CT-REVIEW-18): when it fired, which counters it carried, and their
    values. The shown and flagged counts always travel together in one emission."""

    at: str
    names: tuple[str, ...]
    values: Mapping[str, Any]


@dataclass(frozen=True)
class ReviewAlert:
    """One fired alert (CT-REVIEW-18). `name` is the stable identifier; the criterion and its
    administration history say what the alert is about."""

    name: str
    criterion_id: str
    consecutive_administrations: int
    administrations: tuple[str, ...]


@dataclass(frozen=True)
class QueryPlan:
    """The admission query as a plan (CT-REVIEW-05): the routing values it reads, the evaluation
    mode it requires, and the origins it can never reach. `_admitted` is the one filter both the
    in-memory and the store versions actually run."""

    routing_values: tuple[str, ...]
    evaluation_modes: tuple[str, ...]
    excluded_origins: tuple[str, ...]


@dataclass(frozen=True)
class WriteRecord:
    """One write a review action made, as `write_audit` reports it (CT-REVIEW-06). `table` is
    `criterion_score` for settling the score row and `label` for the label; nothing M-REVIEW writes
    lands on a grade table."""

    table: str
    score_id: str
    detail: str = ""


@dataclass(frozen=True)
class BlindItem:
    """One reference in a blind draw: the identity a judgment is about, and nothing else
    (CT-REVIEW-09). It has only the three fields the flow needs to ask the question and no field a
    score could occupy. Frozen and hashable, because the references key a submission's `bands`
    mapping."""

    submission_id: str
    criterion_id: str
    evaluation_mode: str


#: Every table a blind draw and its seat reads touch (CT-REVIEW-09, amended by FR-REVIEW-27,
#: #875): the submission and its roster name; the criterion and the package's band set; the
#: canonical artifact (the transcribed document and its regions); the run's package link and,
#: when a draw opens, the review window its grade policy declares; and the draw's own three
#: tables. Nothing here holds a band, points, verdict or span the system produced.
BLIND_READABLE_TABLES: frozenset[str] = frozenset({
    "submission", "roster",
    "criterion", "band",
    "document", "document_region",
    "run", "grade_policy",
    "blind_draw", "blind_draw_seat", "blind_draft",
})

#: FR-REVIEW-30's draw states. `not_drawn` is the absence of a draw; the other four are stored.
DRAW_NOT_DRAWN = "not_drawn"
DRAW_OPEN = "open"
DRAW_FINISHED = "finished"
DRAW_SKIPPED = "skipped"
DRAW_CLOSED_BY_WINDOW = "closed_by_window"
DRAW_STATES: tuple[str, ...] = (
    DRAW_NOT_DRAWN, DRAW_OPEN, DRAW_FINISHED, DRAW_SKIPPED, DRAW_CLOSED_BY_WINDOW,
)

#: The legal transitions (FR-REVIEW-30, CT-REVIEW-27). A draw closes only by Finish, Skip or
#: the window's lapse, and nothing leads back out of a closed state.
DRAW_TRANSITIONS: Mapping[str, frozenset[str]] = {
    DRAW_NOT_DRAWN: frozenset({DRAW_OPEN, DRAW_SKIPPED}),
    DRAW_OPEN: frozenset({DRAW_FINISHED, DRAW_SKIPPED, DRAW_CLOSED_BY_WINDOW}),
    DRAW_FINISHED: frozenset(),
    DRAW_SKIPPED: frozenset(),
    DRAW_CLOSED_BY_WINDOW: frozenset(),
}

#: The exact keys of a blind seat (FR-REVIEW-27, TC-REVIEW-106): its identity, the student's
#: answer and the page(s) it is on, the criterion's bands with their descriptors, and the
#: teacher's draft. Nothing derived from grading.
BLIND_SEAT_KEYS: tuple[str, ...] = (
    "seat_id", "student_name", "question", "criterion_id",
    "answer_text", "page_refs", "bands", "draft_band",
)


@dataclass(frozen=True)
class BlindCloseReport:
    """What closing a draw did (FR-REVIEW-26/30): the state it closed into, the blind labels it
    wrote (one per drafted seat), the seats left unmarked, and `absence_reason` (`none_marked`
    for a close with no mark, `skipped` for a skip, else None). The administration's record
    reads `unmarked_count` and `absence_reason` from here (FR-STATS-33)."""

    run_id: str
    state: str
    label_ids: tuple[str, ...]
    unmarked_count: int
    absence_reason: str | None = None


@dataclass(frozen=True)
class DrawRecord:
    """A run's draw as stored, read without acting on it (FR-REVIEW-30, #879): its state, and for
    a closed draw what the close recorded — the blind labels it wrote, the seats left unmarked
    and the absence reason. The composition root reads it to promote the administration when the
    draw closes (FR-PIPE-21): a window lapse returns no `BlindCloseReport` to anyone."""

    run_id: str
    state: str
    labels_written: int = 0
    unmarked_count: int = 0
    absence_reason: str | None = None
    closed_at: str | None = None


@dataclass(frozen=True)
class BlindSession:
    """One blind sitting: the drawn references, and the two checks CT-REVIEW-09 makes.
    `readable_tables()` is the query-level guarantee (only `submission` and `criterion`, never
    `criterion_score`); `available_data()` is everything the session holds. The session has no
    attribute where a score row could hide (FR-REVIEW-11)."""

    session_id: str
    run_id: str
    items: tuple[BlindItem, ...]

    def readable_tables(self) -> frozenset[str]:
        """The tables the blind flow's queries read (CT-REVIEW-09 as amended by FR-REVIEW-27):
        the submission and whose it is, the criterion and the package's band set with its
        descriptors, the canonical artifact's region, and the draw's own bookkeeping, and never
        `criterion_score`, `verdict` or `extraction`."""
        return BLIND_READABLE_TABLES

    def available_data(self) -> dict[str, Any]:
        """Everything the session can reach before submission, as plain data: the identity fields
        of the drawn references. No band, no points, no narrative."""
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
    """One complete final grade as the student would receive it (FR-REVIEW-14): the auto-accepted
    band for each criterion and the points they map to."""

    submission_id: str
    criterion_bands: Mapping[str, str]
    points: float
    rendered_as_student_sees_it: bool = True


@dataclass(frozen=True)
class BlindSampleSkipReport:
    """What a skipped blind sample reports (FR-REVIEW-13): that there is no figure, and nothing in
    its place. `current_figure` is always None, because showing an earlier administration's figure
    as current would be misleading (RISK-08)."""

    reported: bool
    message: str
    current_figure: float | None = None


@dataclass(frozen=True)
class ResidualReport:
    """What `end_session` and `close_run` return (FR-REVIEW-08): the unreviewed residual as it
    stands. `finalized` and `backfilled` are always empty because these moments write nothing; the
    fields exist so any future change that does write must say so. `grades_delivered` and
    `grades_finalized` are always True: skipping the blind sample does not hold back grades
    (FR-REVIEW-13)."""

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
    """Every field M-REVIEW writes (CT-REVIEW-14): the label's fields, the action that produced it,
    and the review-state field it sets on the score row.

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
