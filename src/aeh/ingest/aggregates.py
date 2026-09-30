"""The cohort's run-level ingestion signals."""

from __future__ import annotations

from .descriptions import description_disagreement
from .schema import INGEST_STATEMENTS
from .records import GATE_COLUMNS_BY_GATE, GATE_FAIL_VALUES, GATE_PASS_VALUES, RunAggregates


class RunAggregatesMixin:
    """Computes the cohort's run-level ingestion signals."""

    def run_aggregates(self, cohort_id: str) -> RunAggregates:
        """The cohort's run-level aggregates (`CT-INGEST-19`, OBS-01) — #222's
        F3/G4 emitter, the single path that produces every signal the report
        surface names. Each is computed from the STORED rows (the same rows a
        consumer could read), never from in-memory state: the per-gate pass
        counts over raw rows are honest exactly because the F4 fix made an
        unreached gate record `not_reached` — counting over raw rows equals
        counting over construction-known reachability.

        Signal definitions (each also stated in `basis`, with its denominator):

        - `ocr_failure_rate`: submissions whose V0 or V1 gate failed, over all
          submissions — the file/OCR pipeline failed to deliver a usable
          transcript (remedy: re-scan/re-ingest). V2–V4's remedies differ,
          which is the clause's reason the rates are separate signals.
        - `unresolved_mark_rate`: selection-mark regions whose
          `selection_state` is not `resolved`, over all selection-mark regions
          (remedy: operator reading — CT-INGEST-05).
        - `pages_with_text_layer`: the count over the cohort's submission
          documents; 0 with no documents is the honest zero (a count, not a
          rate).
        - `mean`/`max_text_layer_divergence`: over the documents that carry a
          measurement (each recorded value is that document's per-page
          maximum, F6); None when none measured.
        - `gate_pass_counts`/`gate_fail_counts`: per gate over the five
          columns under `GATE_PASS_VALUES`/`GATE_FAIL_VALUES`;
          `not_reached`/`not_run` count in neither.
        - `quarantine_counts_by_gate`: each quarantined row attributed to the
          FIRST failing gate in ladder order (the C19 derivation: a
          quarantined row names exactly one failing gate). A quarantined row
          that names none counts under `unattributed` — surfaced, never
          folded away.
        - `second_pass_disagreement_rate`: second-described regions whose two
          descriptions disagree on a load-bearing fact or fall under the content
          floor (`description_disagreement`, FR-INGEST-14), over second-described
          regions; None when no region carries a second description, so a zero
          would lie. Failed second calls carry no second description and are not
          in this rate — they are in each document's `second_description_pass`."""
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
