"""The run screens: upload, the run monitor and the quarantine view."""

from __future__ import annotations

import sqlite3
from html import escape
from typing import Any

from .settings import CONSOLE_POLL_INTERVAL_MS
from .queries import _SELECT_QUARANTINE, _SELECT_SUBMISSION_CROPS
from .errors import ConsoleReadError, _is_schema_fault
from .html import _label_line, _prompt_section, _row_get, _section


class RunScreensMixin:
    """The upload, run-monitor and quarantine screens."""

    # -- S2: upload — page order before transcription, calibration stored, no promises ---------------

    def _render_upload(self, queries: list[str], params: dict[str, Any]) -> str:
        # `FR-CONSOLE-35`: `package_file` is not a table in any tier, so the read it
        # replaced returned nothing on every store and the fallback below was always what
        # rendered. The uploaded set comes from the caller (the ingestion report's own
        # listing) or from the standing names.
        files = params.get("files")
        cohort_id = params.get("cohort_id")
        unread = False
        if (not files and cohort_id and getattr(self._store, "data_dir", None) is not None
                and str(cohort_id) not in self._cohort_keys()):
            # An id naming no existing cohort file: nothing was uploaded to it, and reading it
            # must not create one (#531 review).
            files = ()
        elif not files and cohort_id and getattr(self._store, "data_dir", None) is not None:
            # FR-CONSOLE-27 (#531): on a real store, the parts the upload recorded, in the
            # assembled (filename-tier) order; nothing at all when nothing was uploaded.
            from aeh.pipeline import uploaded_parts

            try:
                files = uploaded_parts(self._store, str(cohort_id))
            except sqlite3.OperationalError as error:
                # CT-CONSOLE-28 (#600): never an absence over a table that could not be read.
                if _is_schema_fault(error):
                    raise ConsoleReadError(
                        "uploaded_parts", f"cohort {cohort_id}", error) from error
                self._skipped_ledgers += 1
                files, unread = (), True
            except Exception:  # noqa: BLE001 — one unreadable ledger, counted and said
                self._skipped_ledgers += 1
                files, unread = (), True
        elif not files and getattr(self._store, "data_dir", None) is None:
            files = (
                "scan-001.pdf",
                "scan-002.pdf",
                "scan-003.pdf",
            )
        order = "".join(
            f"<li>Page {index + 1}: {escape(str(name))}</li>"
            for index, name in enumerate(files or ())
        ) or ("<li>The uploaded parts could not be read just now; nothing is shown rather "
              "than a list that may be wrong.</li>" if unread
              else "<li>No parts have been uploaded for this cohort yet.</li>")
        return (
            _section(
                "upload-format",
                "Accepted format: PDF only. A logical document may arrive as several files.",
                "The upload streams to the content-addressed blob store; nothing buffers in "
                "the browser and nothing buffers here.",
            )
            + '<section data-role="page-order"><h2>Assembled page order</h2>'
            f"<ol>{order}</ol>"
            "<p>This is the order the pages are assembled in, shown before transcription "
            "starts. Correct it here if the scan order is wrong.</p></section>"
            + '<section data-role="transcription"><h2>Transcription</h2>'
            "<p>Transcription starts after the assembled order is accepted.</p></section>"
            + _prompt_section(
                "Mark 10 to 15 calibration papers",
                "The calibration papers you upload are stored with the package for a later "
                "version; they are not scored in this administration.",
                "if you skip, this administration runs without a fixed reference and the "
                "papers stay stored with the package for a later version.",
            )
        )

    def _render_monitor(self, run_id: str, queries: list[str]) -> str:
        # The `run` table lives in the cohort tier (orch migration 7) — a durable-tier
        # read saw no rows at all, and a running run rendered as `pending`.
        rows = self._read_cohort_files(
            "SELECT status, pause_reason FROM run WHERE run_id = :run_id", queries, run_id=run_id
        )
        stored = str(_row_get(rows[-1], "status")) if rows else None
        shown = self._run_status_from_ledger() or stored or "pending"
        # CT-PIPE-04 (#602): a paused run says why. The reason is the stored row's, and it is
        # shown only while the run the operator sees is paused.
        reason = _row_get(rows[-1], "pause_reason") if rows else None
        why = (_label_line("Pause reason", reason)
               if shown == "paused" and reason else "")
        # Invariant 3 (`FR-CONSOLE-08`): progress renders at (stage, criterion, judge)
        # — the monitor draws exactly the rows the report carries, and derives no
        # per-student figure from them (`CT-CONSOLE-09`).
        report = self.progress(run_id, queries=queries)
        progress_lines = [
            "stage {} · criterion {} · judge {} · status {}: {} units".format(
                escape(row["stage"]), escape(row["criterion"]), escape(row["judge"]),
                escape(row["status"]), row["n"],
            )
            for row in report.counts
        ]
        return (
            _section("run-state", f"Run {run_id} status: {shown}.")
            + why
            + _label_line("Poll interval", f"{CONSOLE_POLL_INTERVAL_MS} ms")
            + _section(
                "progress",
                "Work by stage, criterion and judge — the three dimensions the run "
                "ledger counts. There is no per-student progress figure: a unit's "
                "state says nothing about when a student's grade will exist.",
                *(
                    progress_lines
                    or ["No units are on the ledger for this run yet."]
                ),
            )
            + self._render_audit_lines()
        )

    # -- S8: quarantine — the crop, and what is never automatic -----------------------------------------

    def _render_quarantine(self, queries: list[str]) -> str:
        # `submission` lives in the cohort tier — the park list is read across the
        # cohort files, the same walk the grade and deterministic modules use.
        rows = self._read_cohort_files(_SELECT_QUARANTINE, queries)
        items = []
        for row in rows:
            submission = _row_get(row, "submission_id")
            # FR-CONSOLE-29 (#530): the item's OWN stored crops, by content hash, never a
            # static placeholder. An item with no stored crop (a V4 mismatch has no mark)
            # shows no image and says so.
            crops = self._read_cohort_files(
                _SELECT_SUBMISSION_CROPS, queries, submission_id=submission)
            figures = "".join(
                f'<figure data-role="mark"><img src="/blobs/{escape(str(_row_get(crop, "crop_ref")))}" '
                f'alt="stored crop of the {escape(str(_row_get(crop, "region_kind")))} region">'
                f"<figcaption>The stored crop of the "
                f"{escape(str(_row_get(crop, 'region_kind')))} region.</figcaption></figure>"
                for crop in crops
            ) or ("<p>No stored crop for this item. M-INGEST keeps crops for described "
                  "regions; an item with no stored crop shows none rather than a stand-in.</p>")
            items.append(
                f'<div class="quarantine-item"><p>{escape(str(submission))} — parked for '
                "operator triage.</p>" + figures + "</div>"
            )
        body = (
            '<section data-role="quarantine">' + "".join(items) + "</section>"
            if items
            else _section("quarantine-empty", "No quarantine items are parked for this cohort.")
        )
        return body + _section(
            "quarantine-rules",
            "Nothing here is reassigned automatically: a mismatched submission is parked, "
            "and a human resolves it.",
            "Closing an item as unresolvable marks its criteria MISSING and its grade "
            "INCOMPLETE — never zero, and never a borrowed figure.",
            "The image crop shows the mark that could not be read, for the operator's own eyes.",
        )
