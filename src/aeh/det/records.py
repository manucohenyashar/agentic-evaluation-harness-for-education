"""The rows and reports M-DET returns to its callers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# --- the stored result and the pass report ----------------------------------------------------------


@dataclass(frozen=True)
class SelectionRead:
    """What M-INGEST recorded about one question's answer, as the scoring rule's input. `selection`
    is a tuple of option ids, or None when nothing was read."""

    content_state: str
    selection_state: str | None
    selection: tuple[str, ...] | None


@dataclass(frozen=True)
class CriterionScore:
    """The score row M-DET wrote, returned field by field rather than as a bare status."""

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
    """One question's item summary (FR-DET-07): n, correct rate, and blank and unresolved counts
    kept separate (CT-DET-08). `most_chosen_distractor` is the most-chosen wrong option, ties
    broken alphabetically. An `unresolved_rate` above the threshold is a scanning alert, never item
    difficulty."""

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
    """What one cohort pass did: counts, per-question summaries and scanning alerts, so an empty
    result can never look like a success."""

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
    #: to carry (see `docs/code-notes/det.md`'s interpretations).
    audit_records_written: int
    summaries: tuple[CriterionSummary, ...]
    alerts: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ItemOptionCount:
    """How many students chose one option of one question, with a flag for whether it is in the key
    (FR-DET-07, CT-DET-08)."""

    criterion_id: str
    option: str
    chosen: int
    is_key: bool


@dataclass(frozen=True)
class ItemStatsEntry:
    """One question's statistics as read back: the summary figures and the per-option counts behind
    them, with blank and unresolved counts kept separate (FR-DET-07, CT-DET-08)."""

    criterion_id: str
    n: int
    correct_rate: float
    blank_count: int
    unresolved_count: int
    options: tuple[ItemOptionCount, ...]


@dataclass(frozen=True)
class ItemStatsReport:
    """What `item_stats` returns for one cohort (FR-DET-07, CT-DET-08). `package_version_id` is
    None exactly when the cohort has no runs."""

    cohort_id: str
    package_version_id: str | None
    items: tuple[ItemStatsEntry, ...]


@dataclass(frozen=True)
class RederiveChange:
    """How one submission's score changed under the corrected key (FR-DET-08). `old_band` is None
    when there was no score row before. Unresolved rows never change, because they never depended
    on the key."""

    submission_id: str
    old_band: str | None
    new_band: str
    old_points: float | None
    new_points: float | None


@dataclass(frozen=True)
class RederiveReport:
    """What one key-correction re-derivation did: the versions involved, the changes, and explicit
    zero counts, such as zero panel units enqueued, so the absence of panel work is visible in the
    result (FR-DET-08, CT-DET-07)."""

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
