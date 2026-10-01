"""The cohort's run-level ingestion signals."""

from __future__ import annotations

from .descriptions import description_disagreement
from .schema import INGEST_STATEMENTS
from .records import GATE_COLUMNS_BY_GATE, GATE_FAIL_VALUES, GATE_PASS_VALUES, RunAggregates


class RunAggregatesMixin:
    """Computes the cohort's run-level ingestion signals."""

    def run_aggregates(self, cohort_id: str) -> RunAggregates:
        """The cohort's run-level ingestion signals (CT-INGEST-19, OBS-01), computed in this one
        place. Every figure comes from the stored rows a consumer could read, never from memory.
        Counting gate passes over raw rows is accurate because a gate that was never reached
        records `not_reached`.

        More detail: `docs/code-notes/ingest.md`, section `aggregates.py: RunAggregatesMixin.run_aggregates`.
        """
        gate_rows = self._handle.query(
            INGEST_STATEMENTS["select_cohort_gate_rows"], cohort_id=cohort_id)
        documents = self._handle.query(
            INGEST_STATEMENTS["select_cohort_documents"], cohort_id=cohort_id)
        marks = self._handle.query(
            INGEST_STATEMENTS["select_cohort_mark_regions"],
            cohort_id=cohort_id)
        second_pass = self._handle.query(
            INGEST_STATEMENTS["select_cohort_second_pass_regions"],
            cohort_id=cohort_id)

        submissions = len(gate_rows)
        ocr_failed = sum(
            1 for row in gate_rows
            if row["v0_integrity"] in GATE_FAIL_VALUES["v0"]
            or row["v1_pages"] in GATE_FAIL_VALUES["v1"])
        unresolved_marks = sum(
            1 for row in marks if row["selection_state"] != "resolved")
        divergences = [row["text_layer_divergence"] for row in documents
                       if row["text_layer_divergence"] is not None]
        pass_counts = {
            gate: sum(1 for row in gate_rows
                      if row[column] in GATE_PASS_VALUES[gate])
            for gate, column in GATE_COLUMNS_BY_GATE.items()}
        fail_counts = {
            gate: sum(1 for row in gate_rows
                      if row[column] in GATE_FAIL_VALUES[gate])
            for gate, column in GATE_COLUMNS_BY_GATE.items()}
        quarantine_by_gate: dict[str, int] = {}
        for row in gate_rows:
            if not row["quarantined"]:
                continue
            failed = next((gate for gate, column in GATE_COLUMNS_BY_GATE.items()
                           if row[column] in GATE_FAIL_VALUES[gate]), None)
            quarantine_by_gate[failed if failed is not None else "unattributed"] = (
                quarantine_by_gate.get(
                    failed if failed is not None else "unattributed", 0) + 1)
        disagreed = sum(
            1 for row in second_pass
            if description_disagreement(row["description"],
                                        row["description_secondary"])["disagrees"])

        return RunAggregates(
            submissions=submissions,
            ocr_failure_rate=(ocr_failed / submissions
                              if submissions else None),
            unresolved_mark_rate=(unresolved_marks / len(marks)
                                  if marks else None),
            pages_with_text_layer=sum(
                row["pages_with_text_layer"] or 0 for row in documents),
            mean_text_layer_divergence=(sum(divergences) / len(divergences)
                                        if divergences else None),
            max_text_layer_divergence=(max(divergences)
                                       if divergences else None),
            gate_pass_counts=pass_counts,
            gate_fail_counts=fail_counts,
            quarantine_counts_by_gate=quarantine_by_gate,
            second_pass_disagreement_rate=(disagreed / len(second_pass)
                                           if second_pass else None),
            basis={
                "ocr_failure_rate":
                    f"submissions with a failed v0 or v1 gate over "
                    f"{submissions} submission(s); None over an empty cohort",
                "unresolved_mark_rate":
                    f"selection-mark regions not 'resolved' over "
                    f"{len(marks)} selection-mark region(s); None when the "
                    "cohort carries no marks",
                "pages_with_text_layer":
                    f"sum over {len(documents)} submission document(s); "
                    "documents without a count contribute 0",
                "mean_text_layer_divergence":
                    f"mean of {len(divergences)} recorded per-document "
                    "maximum(a); None when none measured",
                "max_text_layer_divergence":
                    f"max of {len(divergences)} recorded per-document "
                    "maximum(a); None when none measured",
                "gate_pass_counts":
                    "per gate over the raw submission rows under "
                    "GATE_PASS_VALUES; not_reached/not_run count in neither "
                    "side (the F4 discriminator)",
                "gate_fail_counts":
                    "per gate over the raw submission rows under "
                    "GATE_FAIL_VALUES",
                "quarantine_counts_by_gate":
                    "quarantined rows attributed to the first failing gate "
                    "in ladder order; 'unattributed' only when a quarantined "
                    "row names none",
                "second_pass_disagreement_rate":
                    f"second-passed regions whose secondary description "
                    f"differs from the primary over {len(second_pass)} "
                    "second-passed region(s); None while no second pass has "
                    "run (the pass is not implemented — never simulated)",
            },
        )
