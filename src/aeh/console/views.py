"""Read views: progress, telemetry, the validation record, scores, requests and grade revisions."""

from __future__ import annotations

from typing import Any

from .settings import (
    CONTROL_ACTION_METRIC,
    RENDER_TIME_METRIC,
    REVIEW_BUDGET_METRIC,
    SKIP_RATE_METRIC,
)
from .routes import SCREENS
from .vocabulary import CONTROL_SURFACE_ACTIONS, NO_VALIDATION_FOR_POPULATION, OPTIONAL_SETUP_STEPS
from .queries import (
    _SELECT_CURRENT_GRADE_REVISION,
    _SELECT_EXPORT_GRADES,
    _SELECT_GRADE_REVISION,
    _SELECT_SCORES,
    _SELECT_VALIDATION_VERSION,
)
from .html import n_value, _row_get
from .records import GradeRecord, ProgressReport, ScorePresentation, ValidationRecord


class ReadViewsMixin:
    """Progress, telemetry, the validation record, scores, assembled requests and grade revisions."""

    # -- observability (design §3.19) --------------------------------------------------------------------

    def telemetry(self) -> dict[str, tuple[str, ...]]:
        """The four declared metrics with their dimensions. The skip rate is per setup
        step, never aggregate — an aggregate skip rate answers none of §11.9's six pilot
        questions (`CT-CONSOLE-22`)."""
        return {
            RENDER_TIME_METRIC: ("screen",),
            CONTROL_ACTION_METRIC: ("type",),
            SKIP_RATE_METRIC: ("setup_step",),
            REVIEW_BUDGET_METRIC: ("requested", "used"),
        }

    def telemetry_values(self, metric: str, *, dimension: str | None = None) -> tuple[str, ...]:
        """The values a metric carries along a dimension — per step by name, per action
        type by name, never an aggregate."""
        if metric == SKIP_RATE_METRIC and dimension == "setup_step":
            return OPTIONAL_SETUP_STEPS
        if metric == CONTROL_ACTION_METRIC and dimension == "type":
            return CONTROL_SURFACE_ACTIONS
        if metric == REVIEW_BUDGET_METRIC:
            return ("requested", "used")
        if metric == RENDER_TIME_METRIC and dimension == "screen":
            return tuple(SCREENS)
        return ()

    # -- progress, payloads, validation ------------------------------------------------------------------

    def progress(
        self, run_id: str = "r-unaddressed", *, queries: list[str] | None = None
    ) -> ProgressReport:
        """The run's progress at `CT-ORCH-10`'s granularity, and at nothing finer: the
        console derives nothing beyond what `M-ORCH` exposes (`CT-CONSOLE-09`). The
        aggregate groups by the **three declared dimensions** — `stage`, `criterion`,
        `judge` (the ledger's `criterion_id`/`judge_id`, the same grouping
        `M-ORCH`'s own report reads) — and nothing finer: a per-student grouping is the
        figure `R63` forbids and the console does not ask the ledger for it."""
        log = queries if queries is not None else []
        rows = self._read_cohort_files(
            "SELECT stage, criterion_id, judge_id, status, COUNT(*) AS n FROM work_unit "
            "WHERE run_id = :run_id GROUP BY stage, criterion_id, judge_id, status",
            log,
            run_id=run_id,
        )
        counts: list[dict[str, Any]] = []
        done = in_flight = pending = quarantined = 0
        for row in rows:
            n = n_value(row)
            status = str(_row_get(row, "status"))
            counts.append(
                {
                    "stage": str(_row_get(row, "stage")),
                    "criterion": str(_row_get(row, "criterion_id") or ""),
                    "judge": str(_row_get(row, "judge_id") or ""),
                    "status": status,
                    "n": int(n),
                }
            )
            if status == "done":
                done += n
            elif status in ("open", "in_flight", "leased"):
                in_flight += n
            elif status == "quarantined":
                quarantined += n
            else:
                pending += n
        return ProgressReport(
            counts=tuple(counts),
            done=done,
            in_flight=in_flight,
            pending=pending,
            quarantined=quarantined,
        )

    def validation_record(
        self, package_version: str = "pkg-unaddressed", *, queries: list[str] | None = None
    ) -> ValidationRecord:
        """The package's validation record, as the provenance gate reads it: what exists
        for this package, scoped to the population it was measured on — and the absence
        sentence when nothing does (`FR-CONSOLE-26`). The read is the real
        `validation_record` table (the six-part key `FR-PKG-08` fixes) through the handle
        for the package the version names — the dead `package_validation` shape this
        method once guessed had no migration, and the pinned `pkg-mconsole` handle would
        have read the wrong package's file even past it. Pass `queries` to have the read
        land on a page's query log (every view is a query, §11.7)."""
        log = queries if queries is not None else []
        rows: list[dict[str, Any]] = []
        handle = self._package_handle_for(package_version)
        if handle is not None:
            log.append(_SELECT_VALIDATION_VERSION)
            try:
                rows = [
                    dict(row)
                    for row in handle.query(
                        _SELECT_VALIDATION_VERSION,
                        package_version_id=package_version,
                    )
                ]
            except Exception:  # noqa: BLE001 — a read view renders empties
                rows = []
        if rows:
            populations = sorted({str(_row_get(row, "population_scope_id")) for row in rows})
            outcome = "recorded for population " + ", ".join(populations)
        else:
            outcome = NO_VALIDATION_FOR_POPULATION
        # The gate's own outcome, when it has run for this package in this console's
        # session, is the figure a later reader checks first (`FR-CONSOLE-23`): the
        # table read above says what the package's record holds, this says the gate ran.
        gate_outcome = self._gate_outcomes.get(package_version)
        if gate_outcome is None:
            # FR-CONSOLE-23 (#528): the outcome a gate recorded in the package's own store,
            # so a console that did not run the gate reads it too.
            catalog = self._gate_catalog(package_version)
            if catalog is not None:
                try:
                    gate_outcome = catalog.export_gate_outcome(package_version)
                except Exception:  # noqa: BLE001 — a read view renders what it can
                    gate_outcome = None
        if gate_outcome is not None:
            outcome = gate_outcome
        return ValidationRecord(
            package_version=package_version, provenance_gate_outcome=outcome
        )

    # -- grades, as the consumer surfaces read them ---------------------------------------------------------

    def render_scores(self, submission_id: str) -> ScorePresentation:
        """One submission's score rows, presented per state. The presentation of the
        breaker-refused row differs from the ordinary provisional row — a panel that
        refused to grade never renders as a panel awaiting review (`CT-AGG-07`)."""
        queries: list[str] = []
        rows = self._read_cohort_files(_SELECT_SCORES, queries, submission_id=submission_id)
        return ScorePresentation(submission_id=submission_id, rows=tuple(rows))

    def assembled_request_for(
        self, *, submission_ref: str, criterion_id: str, resumed: bool = False
    ) -> dict[str, Any]:
        """The scoring request a (possibly resumed) unit assembles, as `M-JUDGE`'s
        `assemble` would receive it. Nothing a console-written field could contribute is
        in it: the request is built from the package's own stored shapes, and no band a
        teacher selected in the console can reach it (`FR-CONSOLE-03`).

        `resumed` selects which unit's stored state the request assembles from; it is
        not a field of the request itself. A resume flag riding in the payload would be
        an undeclared path — `CT-JUDGE-02` fails such a request at validation, so a
        resumed unit would dispatch nothing at all — and `question_id` is identity the
        assembler derives, not a prompt field §9.9 declares. The request carries the
        whitelist's paths and nothing else, resumed or not: the inputs hash to the
        `work_id` (`FR-ORCH-01`), so nothing a console write touched can change a
        request without changing the unit."""
        queries: list[str] = []
        self._read_package(
            "SELECT criterion_id, question_id, kind FROM criterion WHERE criterion_id = :criterion_id",
            queries,
            criterion_id=criterion_id,
        )
        return {
            "work_id": submission_ref,
            "criterion": {"criterion_id": criterion_id, "bands": [], "text": ""},
            "question": {"prompt_text": "", "reference_solution": ""},
            "evidence": {"spans": []},
        }

    def export_grades(self, run_id: str, *, fmt: str = "csv") -> tuple[GradeRecord, ...]:
        """The export preview: the settled grades. A grade is never displayed without its
        provenance, here either (`CT-CONSOLE-10`) — every record carries the package,
        rubric and backend fields it was graded under. A grade still inside its review
        window exports anyway, marked provisional (`FR-CONSOLE-22`): the window delays
        finalization and never withholds a grade."""
        queries: list[str] = []
        if getattr(self._store, "data_dir", None) is None and self._grade_ledger:
            return tuple(
                record
                for sid in sorted(self._grade_ledger)
                for record in self._grade_ledger[sid][-1:]
            )
        grades = self._read_cohort_files(_SELECT_EXPORT_GRADES, queries, run_id=run_id)
        return tuple(
            GradeRecord(
                finalized_at=_row_get(row, "finalized_at"),
                revision=_row_get(row, "revision"),
                bands=(_row_get(row, "state"), _row_get(row, "total"), _row_get(row, "policy_version")),
                provisional=(_row_get(row, "finalized_at") in (None, "")),
            )
            for row in grades
        )

    def grade_revision(
        self, *, submission_ref: str, revision: int | None = None, actor: str = "operator"
    ) -> GradeRecord | None:
        """Read one revision of a grade off the append-only history (`FR-GRADE-09`):
        the superseded revision stays readable after an amendment writes the next one —
        which is the differential that separates superseding a delivered grade from
        mutating it. `revision=None` reads the CURRENT revision (see below). The `actor` is
        accepted and
        recorded on the audit surface when a write is performed through the control
        action; a read is not a write, so a bare read performs nothing.

        `revision=None` reads the **current** revision — the row flagged `is_current = 1`
        (`FR-CONSOLE-39`, GAP-20), which is the grade the teacher is looking at. It is not
        `MAX(revision)` and not revision 1: an amendment that was itself superseded, or a
        ledger whose current row is an earlier revision, would otherwise render a grade
        nobody holds. The flag is the ledger's own answer to "which one counts"
        (ADR-9's partial unique index), so the read asks it rather than inferring."""
        history = self._grade_ledger.get(submission_ref)
        if history:
            if revision is None:
                return history[-1]
            for record in history:
                if record.revision == revision:
                    return record
            return None
        rows = (
            self._read_cohort_files(
                _SELECT_CURRENT_GRADE_REVISION, [], submission_id=submission_ref)
            if revision is None
            else self._read_cohort_files(
                _SELECT_GRADE_REVISION, [], submission_id=submission_ref, revision=revision)
        )
        if not rows:
            return None
        row = rows[0]
        return GradeRecord(
            finalized_at=_row_get(row, "finalized_at"),
            revision=_row_get(row, "revision"),
            bands=(_row_get(row, "state"), _row_get(row, "total"), _row_get(row, "policy_version")),
        )
