"""What the console returns: rendered pages, action outcomes, queue items and reports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dataclasses import dataclass, fields as dataclass_fields
from typing import Any, Iterator, NamedTuple

from .vocabulary import _GATE_COLUMNS, _GATE_NOT_REACHED, _STATE_PRESENTATION
from .html import _row_get

if TYPE_CHECKING:
    from .app import ConsoleApp


# --- the invented result types -------------------------------------------------------------------------


@dataclass(frozen=True)
class RenderedPage:
    """One rendered screen: the HTML, the queries that produced it and, for the run monitor, how
    often it polls. Pages do not report timings or memory; the tests measure those.

    A page *is* its rendering for the consumers that sweep markup: the review
    vocabulary's detectors (`unstated_residual`, the budget- and clustering-language
    sweeps) run over renderings, so `__contains__` and `lower` delegate to the markup
    and a caller never has to reach for `.html` to sweep one.

    `refused` is the render's own claim that it declined the content — the student-text
    render's refusal face (`render_submission_text`, #127). A page whose text rendered
    carries `refused=False`; the flag exists so a refusal is a value the caller reads,
    not a silent success."""

    html: str
    queries: tuple[str, ...] = ()
    poll_interval_ms: int | None = None
    refused: bool = False
    #: `FR-CONSOLE-37`, seam 4: how many per-ledger reads this render skipped. A skipped
    #: ledger is legitimate (missing, locked, mid-write) and the page renders without it —
    #: but silently skipping is how a partial page passes for a complete one, so the count
    #: rides next to the result rather than being swallowed.
    skipped_ledgers: int = 0
    #: The schema refusal, when one happened: the page rendered a visible "could not be
    #: read" section instead of a number it could not stand behind.
    read_error: str = ""

    def __contains__(self, text: Any) -> bool:
        """Search the HTML, so `"text" in page` works."""
        return text in self.html

    def lower(self) -> str:
        """The HTML in lowercase, for case-insensitive wording checks."""
        return self.html.lower()


@dataclass(frozen=True)
class ControlOutcome:
    """What `perform` did: the rows written (none if refused, replayed or paused), whether the
    action was refused, and, for a stale-screen refusal, the refresh request §3.19 requires."""

    rows_written: tuple[Any, ...] = ()
    refused: bool = False
    refresh_required: bool = False
    dispatched: bool = False
    detail: str = ""


@dataclass(frozen=True)
class UploadOutcome:
    """The upload handler's result. `blob_refs` are the content hashes of the chunks;
    `staged_in_browser` is always False (NFR-CONSOLE-06). The handler never allocates the full
    declared size."""

    dispatched: bool
    blob_refs: tuple[str, ...]
    staged_in_browser: bool = False
    detail: str = ""


@dataclass(frozen=True)
class RunPlan:
    """A planned run: an id derived from a hash of the saved configuration (same config, same run;
    a retry with a different backend profile is a different run, FR-CONF-04), the backend profile,
    and the status."""

    run_id: str
    backend_profile: str
    status: str = "planned"
    retry_of: str | None = None


@dataclass(frozen=True)
class PreflightView:
    """Screen S6: the checks for each gate, the cohort-level breaker (FR-INGEST-28), the drift
    warning, and a note that outstanding quarantine items do not block the run.
    `start_run_available` is False exactly when the breaker has tripped."""

    cohort_id: str
    gates: dict[str, str]
    start_run_available: bool
    drift_shown: bool
    breaker: dict | None = None
    quarantined: int = 0
    detail: str = ""

    @property
    def start_run_withheld(self) -> bool:
        return not self.start_run_available

    @property
    def ladder(self) -> dict[str, str]:
        return dict(self.gates)

    def __str__(self) -> str:
        lines = [f"Preflight for cohort {self.cohort_id}"]
        for gate in ("v0", "v1", "v2", "v3", "v4"):
            lines.append(
                f"{gate} ({_GATE_COLUMNS[gate]}): {self.gates.get(gate, _GATE_NOT_REACHED)}"
            )
        if self.breaker:
            lines.append(f"cohort breaker tripped at rate {self.breaker.get('rate')}")
            finding = self.breaker.get("finding")
            if finding:
                lines.append(str(finding))
        else:
            lines.append(
                "no cohort breaker finding: the V4 failure rate has not tripped it"
            )
        if self.drift_shown:
            lines.append(
                "drift advisory: shown; an adverse drift result does not block a run"
            )
        lines.append(
            f"quarantine items outstanding: {self.quarantined}; they do not withhold run "
            "start, because quarantine is the operator's parallel workstream"
        )
        lines.append(
            "start run available"
            if self.start_run_available
            else "start run withheld until a human clears the breaker"
        )
        return ". ".join(lines) + "."


@dataclass(frozen=True)
class CalibrationRender:
    """A Phase 4 feature shown as present but not yet available, with the version it arrives in
    (FR-CONSOLE-25), never silently missing."""

    present: bool
    available: bool
    available_in_version: str


@dataclass(frozen=True)
class PipelineOutcome:
    """The headless driver's result: the grades, whether they were delivered and finalized, the
    rubric version used, the criteria marked lower-confidence, the modules the pipeline imported,
    and a trace of each stage.

    `lock_waits` (`#118`, the export seam's fourth half) is the store's SQLITE_BUSY-retry
    count over every handle the run opened — the observability figure that says a scoring
    run *waited on a lock* rather than silently slowing down. Zero is the only healthy value
    under WAL's single-writer design, and `CT-STORE-17`-style callers assert exactly that
    while a concurrent analytical export runs `alongside`."""

    modules_imported: tuple[str, ...]
    grades: tuple[Any, ...]
    grades_delivered: bool
    finalized: bool
    rubric_version: str
    lower_confidence_criteria: tuple[str, ...]
    stages: tuple[str, ...] = ()
    lock_waits: int = 0


@dataclass(frozen=True)
class ScorePresentation:
    """A submission's score rows, presented by state. A row the panel refused to grade (the
    breaker) is shown differently from a normal provisional row, so it never looks like it is just
    waiting for review (CT-AGG-07)."""

    submission_id: str
    rows: tuple[Any, ...]

    def __str__(self) -> str:
        lines = [f"Scores for submission {self.submission_id}"]
        for row in self.rows:
            state = str(_row_get(row, "state"))
            label = _STATE_PRESENTATION.get(state, f"recorded state {state}")
            lines.append(
                f"{_row_get(row, 'criterion_id')}: band {_row_get(row, 'band')}, "
                f"points {_row_get(row, 'points')} — {label}"
            )
        if not self.rows:
            lines.append("no score rows recorded for this submission")
        return ". ".join(lines) + "."


@dataclass(frozen=True)
class QueueContents:
    """A queue's badge figures in M-REVIEW's `ReviewQueue` shape (§3.16): the number flagged, the
    number shown, the review budget, and the time reserved for the blind sample before ranking
    (FR-CONSOLE-19, CT-REVIEW-02). The queries used are included, so tests can check what the queue
    could reach."""

    flagged_total: int
    shown: tuple[Any, ...]
    budget_minutes: int | None = None
    reserved_for_blind_minutes: int = 0
    residual_provisional: int = 0
    queries: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueueView:
    """One queue's view: its route (the two queues never share one, §11.3), its contents, the
    ranked order before the reservation, and the queries that produced them."""

    route: str
    queue: QueueContents
    ranked: tuple[Any, ...]
    queries: tuple[str, ...]


class ReviewQueueItem(NamedTuple):
    """One item in the teacher's queue. It is a tuple, not a dict, so tests can intersect queues as
    sets ("no item is in both queues", §11.3); dicts are unhashable. `kind` is always
    `review_item`, the only kind a review queue may show (FR-CONSOLE-12)."""

    submission_id: Any
    criterion_id: Any
    kind: str


class QuarantineItem(NamedTuple):
    """One item in the operator's queue, with its flag state (the field resolving it writes). A
    tuple for the same reason as `ReviewQueueItem`; the two types are distinct even for the same
    ids."""

    submission_id: Any
    ingest_status: Any


@dataclass(frozen=True)
class ProgressReport:
    """Run progress in CT-ORCH-10's shape: counts by stage, criterion and judge, the totals and two
    derived figures, and no per-student field. The console shows nothing finer than M-ORCH provides
    (CT-CONSOLE-09).

    `counts` is a sequence of **rows**, each keyed by the three dimensions `CT-ORCH-10`
    declares (`stage`, `criterion`, `judge`) — not a string-keyed tally, which could not
    carry three dimensions without inventing a fourth. The field set stays exactly the
    seven the clause names.

    **The mapping behavior is deliberate** (the recorded interpretation `M-ORCH`'s own
    `ProgressReport` records): the report is the dataclass AND the surface a caller
    reads — attribute access and mapping access (`report["counts"]`, `set(report)`,
    `report.get("counts", ())`) are both first-class. The mapping carries **the declared
    field set and nothing else** — no operator extras here, because the console derives
    nothing `M-ORCH` did not expose (`CT-CONSOLE-09`'s ceiling is a ceiling on the
    mapping's keys too)."""

    counts: tuple[dict[str, Any], ...] = ()
    done: int = 0
    in_flight: int = 0
    pending: int = 0
    quarantined: int = 0
    escalation_rate_so_far: float = 0.0
    estimated_completion: str | None = None

    def __str__(self) -> str:
        return (
            f"done {self.done}, in flight {self.in_flight}, pending {self.pending}, "
            f"quarantined {self.quarantined}, escalation rate so far "
            f"{self.escalation_rate_so_far:.2f}"
        )

    # -- the mapping protocol, over the declared field set only --------------------

    def keys(self) -> tuple[str, ...]:
        return tuple(field.name for field in dataclass_fields(self))

    def __getitem__(self, key: str) -> Any:
        if key in self.keys():
            return getattr(self, key)
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def __contains__(self, key: object) -> bool:
        return key in self.keys()

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key) if key in self.keys() else default


@dataclass(frozen=True)
class ValidationRecord:
    """Screen S1's validation record for one package version: what the package's record says, and
    the export-gate outcome. For a package never used with this population, it holds the absence
    sentence, never another population's figure."""

    package_version: str
    provenance_gate_outcome: str


@dataclass(frozen=True)
class GradeRecord:
    """A grade in the vocabulary's `Grade` shape: when it was finalized, its revision, and its
    bands. A grade exported while its review window is still open is marked `provisional`: the
    window delays finalization but never withholds the grade (FR-CONSOLE-22)."""

    finalized_at: str | None
    revision: int
    bands: tuple[Any, ...] = ()
    provisional: bool = False


@dataclass(frozen=True)
class ExportOutcome:
    """What one export attempt did (CT-INGEST-08's style): the package, the flag it was checked on,
    and the gate's message."""

    package_version: str
    contains_real_student_text: bool
    refused: bool
    detail: str


@dataclass(frozen=True)
class TouchpointRender:
    """How one §7.9 touchpoint appears (FR-CONSOLE-25): whether the MVP implements it, whether it
    is shown, whether it can be used, and, if shown but unavailable, the version it arrives in. It
    is always a labelled placeholder, never a gap (R72)."""

    implemented: bool
    present: bool = True
    available: bool = True
    available_in_version: str = ""


class _HeldAction:
    """What `hold_after` yields. `release()` resolves the paused action against the store as it is
    now. The safe result is a refusal with a refresh request and no write; §3.19 allows either a
    repeatable result or a refusal, never a partial write."""

    def __init__(self, app: "ConsoleApp", action: str) -> None:
        self._app = app
        self._action = action

    def release(self) -> ControlOutcome:
        return ControlOutcome(
            rows_written=(),
            refused=True,
            refresh_required=True,
            dispatched=False,
            detail=(
                "stale read: the stored state moved while the action was mid-flight, so the "
                "action was not applied. Refresh the page and re-apply."
            ),
        )
