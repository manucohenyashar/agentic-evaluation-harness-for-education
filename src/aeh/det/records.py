"""The rows and reports M-DET returns to its callers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# --- the stored result and the pass report ----------------------------------------------------------


@dataclass(frozen=True)
class SelectionRead:
    """What M-INGEST recorded about one question's answer, as the kernel's
    inputs. `selection` is a tuple of option ids (one per resolved option;
    today's ingest delivers at most one) or None when nothing was read."""

    content_state: str
    selection_state: str | None
    selection: tuple[str, ...] | None


@dataclass(frozen=True)
class CriterionScore:
    """The score row this module wrote, returned to the caller — per-field,
    never a bare status (`CLAUDE.md` seam 4)."""

    run_id: str
    submission_id: str
    criterion_id: str
    question_id: str
    band: str
    state: str
    routing: str
    points: float | None
    judge_count: int
    agreement: float | None
    credit: float
    reason: str
    selection_read: tuple[str, ...] | None


@dataclass(frozen=True)
class CriterionSummary:
    """One question's item summary (`FR-DET-07`): n, correct rate, and — the
    separation that is contract (`CT-DET-08`) — blank count and unresolved
    count as separate figures. `most_chosen_distractor` is the highest-count
    non-key option (ties broken lexicographically, so the report is
    deterministic). `unresolved_rate` above the threshold alerts as a
    SCANNING problem; it is never item difficulty."""

    criterion_id: str
    question_id: str
    n: int
    correct: int
    correct_rate: float
    blank_count: int
    unresolved_count: int
    unresolved_rate: float
    most_chosen_distractor: str | None


@dataclass(frozen=True)
class DeterministicReport:
    """What one cohort pass did (`CLAUDE.md` seam 4): counts, per-question
    summaries, and the scanning alerts — a bare success on an empty detail is
    the silent-failure trap this exists to refuse."""

    run_id: str
    cohort_id: str
    package_version_id: str
    submissions: int
    criteria: int
    evaluations: int
    correct: int
    incorrect: int
    blank: int
    unresolved: int
    unresolved_alert_rate: float
    #: Audit records appended for this pass's scored rows (`FR-DET-10`). Unresolved
    #: rows write none — no grade, no points, nothing for `final_points NOT NULL`
    #: to carry (see the module docstring's interpretations).
    audit_records_written: int
    summaries: tuple[CriterionSummary, ...]
    alerts: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ItemOptionCount:
    """One option's chosen count within one question's stats (`FR-DET-07`):
    the count, and the denormalized key flag (`CT-DET-08`'s rollup needs no
    join)."""

    criterion_id: str
    option: str
    chosen: int
    is_key: bool


@dataclass(frozen=True)
class ItemStatsEntry:
    """One question's read-back statistics (`FR-DET-07`): the summary figures
    and the per-option counts they were built from. blank_count and
    unresolved_count stay separate figures here for the same reason they are
    separate columns (`CT-DET-08`)."""

    criterion_id: str
    n: int
    correct_rate: float
    blank_count: int
    unresolved_count: int
    options: tuple[ItemOptionCount, ...]


@dataclass(frozen=True)
class ItemStatsReport:
    """What `item_stats` returns for one cohort (`FR-DET-07`, `CT-DET-08`).
    `package_version_id` is None exactly when the cohort has no run rows — an
    empty report on an evaluated cohort is impossible, because the cohort pass
    writes the stats it summarizes."""

    cohort_id: str
    package_version_id: str | None
    items: tuple[ItemStatsEntry, ...]


@dataclass(frozen=True)
class RederiveChange:
    """One submission's score difference under the corrected key (`FR-DET-08`).
    `old_band` is None when no score row existed — the re-derivation created
    one. Unresolved rows appear here only as no-changes: they never depended on
    the key."""

    submission_id: str
    old_band: str | None
    new_band: str
    old_points: float | None
    new_points: float | None


@dataclass(frozen=True)
class RederiveReport:
    """What one key-correction re-derivation did (`FR-DET-08`, `CT-DET-07`):
    the versions involved, the diff, and the declared zeros — zero panel work
    enqueued is a FIELD, not an absence, so the refusal to enqueue is visible
    in the result (`CLAUDE.md` seam 4, `TC-DET-C07`'s exact zero)."""

    cohort_id: str
    criterion_id: str
    question_id: str | None
    new_version: str
    from_versions: tuple[str, ...]
    submissions_examined: int
    scores_changed: int
    scores_unchanged: int
    audit_records_written: int
    panel_units_enqueued: int
    changes: tuple[RederiveChange, ...]
