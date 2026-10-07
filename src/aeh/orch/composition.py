"""Cell phases and ready cells: what the composition layer (M-PIPE) reads and writes."""

from __future__ import annotations

from typing import Any

from .constants import STAGE_EXTRACT, STAGE_SCORE
from .errors import CellPhaseError
from .statements import ORCH_STATEMENTS
from .run_records import _panel_build_ref_of, _model_pin_records_of
from .executors import CELL_PHASES, CellKey, READY_HOOKS, RunHandle


class CompositionMixin:
    """Tracks each cell's progress through the pipeline stages and reports which cells are ready
    for the next stage."""

    def mark_cell_phase(
        self, tx: Any, run_id: str, submission_id: str, criterion_id: str,
        phase: str, units_consumed: int = 0,
    ) -> None:
        """Record that one cell reached one composition phase (`FR-ORCH-28`).

        Written through the CALLER's transaction, so a phase and whatever it stands for — the
        integrity verdict, the score row — commit together or not at all: a phase recorded
        beside work that rolled back would make a restart skip the work (`NFR-PIPE-01` is
        about exactly that). Marking the same phase twice updates the one row rather than
        adding a second, so redelivery is a no-op.

        `units_consumed` is how many terminal units the phase was computed over. It is what
        lets `ready_cells` distinguish "aggregated, and three more verdicts have landed since"
        from "aggregated, nothing since" — a count, not a flag, because the second aggregation
        is exactly what a re-scored cell needs.
        """
        if int(units_consumed) < 0:
            raise CellPhaseError(
                f"units_consumed must be >= 0, got {units_consumed!r} (FR-ORCH-28)")
        if phase not in CELL_PHASES:
            raise CellPhaseError(
                f"{phase!r} is not a composition phase; the declared vocabulary is "
                f"{CELL_PHASES} (FR-ORCH-28). The table's CHECK refuses it too — this "
                "refusal is the one that names the phases."
            )
        tx.execute(
            ORCH_STATEMENTS["upsert_cell_phase"],
            run_id=run_id, submission_id=submission_id, criterion_id=criterion_id,
            phase=phase, units_consumed=int(units_consumed), recorded_at=self._wall_now(),
        )

    def run_handle(self, run_id: str) -> RunHandle:
        """The run's cohort handle and ids, for the pipeline layer (FR-PIPE-04).

        `M-PIPE` needs a transaction to commit a score, its escalation and its cell phase
        together, and a transaction comes from the cohort handle. It is forbidden its own SQL
        (`CT-PIPE-05`), so it asks here rather than querying the run row — which is the same
        discipline every other cross-module read in this system follows: the owner answers.

        Raises `RunNotFoundError` for an unknown run, exactly as the lifecycle writers do.
        """
        cohort, row = self._find_run(run_id)
        return RunHandle(
            run_id=run_id,
            cohort_id=str(row["cohort_id"]),
            cohort=cohort,
            package_id=str(row["package_id"]),
            package_version_id=str(row["package_version_id"]),
            status=str(row["status"]),
            pause_reason=row["pause_reason"],
            backend_profile=str(row["backend_profile"] or ""),
            started_at=str(row["started_at"] or ""),
            panel_build_ref=_panel_build_ref_of(row),
            model_pins=_model_pin_records_of(row),
        )

    def cell_unit_counts(self, run_id: str, stage: str) -> dict["CellKey", tuple[int, int]]:
        """`(finished, total)` unit counts per cell for one stage; a cell's phase is computed from
        these.

        `mark_cell_phase(..., units_consumed=n)` wants the number of TERMINAL units the phase
        consumed, and `ready_cells` compares that number against the cell's terminal count to
        decide whether a widened panel needs re-aggregating. A composition layer therefore has
        to record the same number this module counts, and it cannot count for itself
        (`CT-PIPE-05`). Recording a verdict count instead would be a quiet bug: a quarantined
        unit produces no verdict, so the cell would read as ready on every later pass and
        aggregate forever.

        Same read `ready_cells` performs, exposed rather than duplicated.
        """
        cohort, _run_row = self._find_run(run_id)
        counts: dict[CellKey, tuple[int, int]] = {}
        for row in cohort.query(ORCH_STATEMENTS["select_cell_unit_counts"], run_id=run_id):
            if str(row["stage"]) != stage:
                continue
            counts[CellKey(str(row["submission_id"]), str(row["criterion_id"]))] = (
                int(row["terminal"] or 0), int(row["total"] or 0)
            )
        return counts

    def cell_quarantined_counts(self, run_id: str, stage: str) -> dict["CellKey", int]:
        """Each cell's number of quarantined units for one stage, from the ledger (#524).

        The composition layer needs it to tell a panel quarantine left even (FR-PIPE-18's
        replacement, FR-PIPE-05's fallback) from an even panel reached any other way, which is
        a defect and pauses. It cannot be inferred from verdicts: a `done` unit with no verdict
        is not a quarantine. Cells with none are omitted. Read-only."""
        cohort, _run_row = self._find_run(run_id)
        return {
            CellKey(str(row["submission_id"]), str(row["criterion_id"])): int(row["quarantined"])
            for row in cohort.query(ORCH_STATEMENTS["select_cell_unit_counts"], run_id=run_id)
            if str(row["stage"]) == stage and int(row["quarantined"] or 0)
        }

    def ready_cells(self, run_id: str, hook: str) -> tuple["CellKey", ...]:
        """The cells ready for one pipeline hook (FR-ORCH-29), in ledger order.

        * `integrity_pre` — every extract unit of the cell is terminal and the cell carries no
          `integrity_pre` phase yet. That is the moment the integrity gate can read a complete
          extraction and has not already.
        * `aggregate` — every score unit of the cell is terminal, and MORE of them are terminal
          than the `aggregated` phase consumed (or the cell has never aggregated). The count
          comparison is what makes a widened panel re-aggregate: three verdicts became five,
          so the cell is ready again.

        Terminal means `done` or `quarantined`: a quarantined unit will produce no further
        evidence, and a cell waiting for one would wait forever.
        """
        if hook not in READY_HOOKS:
            raise ValueError(
                f"{hook!r} is not a composition hook; the declared hooks are "
                f"{READY_HOOKS} (FR-ORCH-29)."
            )
        cohort, _run_row = self._find_run(run_id)
        return self._ready_cells_in(cohort, run_id, hook)

    def _ready_cells_in(self, cohort: Any, run_id: str, hook: str,
                        phase_rows: Any = None) -> tuple["CellKey", ...]:
        """`ready_cells` for a cohort handle the caller already has (used by the completion check).
        """
        counts: dict[tuple[str, str], dict[str, tuple[int, int]]] = {}
        for row in cohort.query(ORCH_STATEMENTS["select_cell_unit_counts"], run_id=run_id):
            key = (str(row["submission_id"]), str(row["criterion_id"]))
            counts.setdefault(key, {})[str(row["stage"])] = (
                int(row["terminal"] or 0), int(row["total"] or 0)
            )
        phases: dict[tuple[str, str], dict[str, int]] = {}
        if phase_rows is None:
            phase_rows = cohort.query(ORCH_STATEMENTS["select_cell_phases"], run_id=run_id)
        for row in phase_rows:
            key = (str(row["submission_id"]), str(row["criterion_id"]))
            phases.setdefault(key, {})[str(row["phase"])] = int(row["units_consumed"] or 0)
        stage = STAGE_EXTRACT if hook == "integrity_pre" else STAGE_SCORE
        ready: list[CellKey] = []
        for key in sorted(counts):
            terminal, total = counts[key].get(stage, (0, 0))
            if not total or terminal < total:
                continue
            marked = phases.get(key, {})
            if hook == "integrity_pre":
                if "integrity_pre" not in marked:
                    ready.append(CellKey(*key))
            elif "aggregated" not in marked or terminal > marked["aggregated"]:
                ready.append(CellKey(*key))
        return tuple(ready)

    def _awaiting_aggregation(self, cohort: Any, run_id: str) -> bool:
        """Whether any cell is still waiting for the pipeline layer to aggregate it (#524).

        A run driven through the composition hooks records cell phases (`mark_cell_phase`),
        and its aggregate hook decides, AFTER the last unit closes, whether a cell needs more
        units: an escalation (FR-ORCH-09) or a replacement arm (FR-ORCH-43). Completing the
        run first would strand those units — the claim pass skips a `complete` run and
        FR-ORCH-25 has no edge back to `running` — and a hook fault could no longer pause it.
        So while any cell is ready for `aggregate`, the run is not complete; the hook's
        sanctioned closer (`resume`) re-probes once it has run. A run with no phase recorded
        at all is not composition-driven and completes on its units alone, as before.
        """
        phases = cohort.query(ORCH_STATEMENTS["select_cell_phases"], run_id=run_id)
        if not phases:
            return False
        return bool(self._ready_cells_in(cohort, run_id, "aggregate", phases))

    def _cells_with_integrity_pre(self, cohort: Any, run_id: str) -> set[tuple[str, str]]:
        """The cells whose `integrity_pre` phase has been recorded. When an executor is bound, a
        cell must be in this set before its scoring sweep can start (FR-ORCH-30)."""
        return {
            (str(row["submission_id"]), str(row["criterion_id"]))
            for row in cohort.query(ORCH_STATEMENTS["select_cell_phases"], run_id=run_id)
            if str(row["phase"]) == "integrity_pre"
        }
