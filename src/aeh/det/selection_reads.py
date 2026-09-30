"""Reading each question's recorded selection from the submission's ingested document."""

from __future__ import annotations

from typing import Any

from .schema import DET_STATEMENTS
from .records import SelectionRead


class SelectionReadingMixin:
    """Reads each question's recorded selection from the head document of a submission."""

    def _selection_read(
        self, cohort_handle: Any, submission_id: str, question_id: str
    ) -> SelectionRead:
        """One question's answer regions in the head document, resolved to the
        kernel's inputs under R47's retraction discipline. The cohort pass uses
        `_selection_reads` (one query per submission) and looks the question up;
        this method is the single-criterion path."""
        return self._selection_reads(cohort_handle, submission_id).get(
            question_id,
            SelectionRead("absent", None, None),
        )

    def _selection_reads(
        self, cohort_handle: Any, submission_id: str
    ) -> dict[str, SelectionRead]:
        """Every question's answer in the head document, from one head query
        and one regions query — the shape the cohort pass needs to stay a
        single pass (`NFR-DET-01`)."""
        documents = cohort_handle.query(
            DET_STATEMENTS["select_det_document_head"], submission_id=submission_id
        )
        if not documents:
            return {}
        head = documents[-1]
        regions = cohort_handle.query(
            DET_STATEMENTS["select_det_regions"], document_id=head["document_id"]
        )
        mine: dict[str, list[Any]] = {}
        for row in regions:
            # Grouped by `element_kind`, DELIBERATELY, although `#373` added
            # `document_region.question_id` and it is the better name for ownership.
            #
            # `_read_from_regions` below reads one question's regions on the premise its
            # own docstring states — "today's ingest writes one region per question,
            # making the mixed case defensive". Grouping by `element_kind` is what makes
            # that true here: a graphic lands under its own kind ("free_body_diagram"),
            # never under the question, so a question's group holds the one region that
            # answers it.
            #
            # Regrouping by `question_id` would put a question's text region AND every
            # region that follows it — its graphic, its continuation — in one group, and
            # `len(candidates) > 1` would read them as `multiple_marks`. Measured: a
            # BLANK answer with a graphic after it goes from `SelectionRead("blank", ...)`
            # — a legitimate zero under R47 — to an unresolved `multiple_marks`. That is a
            # scoring change, and it belongs to whatever issue teaches the kernel to read
            # a mixed group, not to the one that added the column.
            mine.setdefault(row["element_kind"], []).append(row)
        reads: dict[str, SelectionRead] = {}
        for question_id, rows in mine.items():
            reads[question_id] = self._read_from_regions(rows)
        return reads

    def _read_from_regions(self, mine: list[Any]) -> SelectionRead:
        """R47's retraction discipline applied to one question's regions (see
        module docstring). Live selection-mark regions take precedence: if any
        exist they are the candidates, and several of them are multiple marks
        — unresolved, never "darkest". A question with no live selection mark
        but other live regions still gets read — a letter written in the
        margin is a valid selection captured as a description (§7.8) — one
        such region is read, several are multiple marks. (So a single live
        selection_mark wins over coexisting non-mark regions; today's ingest
        writes one region per question, making the mixed case defensive.)"""
        live = [row for row in mine if row["retraction"] is None]
        if not live:
            # Every region for the question was struck through: the student
            # retracted their answer and left nothing — an empty answer, a
            # legitimate zero (R47's remaining-mark rule taken to its end).
            return SelectionRead("blank", None, None)
        marks = [row for row in live if row["region_kind"] == "selection_mark"]
        candidates = marks if marks else live
        if len(candidates) > 1:
            return SelectionRead("present", "multiple_marks", None)
        region = candidates[0]
        selection: tuple[str, ...] | None = None
        selection_state = region["selection_state"]
        if selection_state == "resolved" and region["selection"]:
            # FR-INGEST-17: selection is populated only when resolved, and
            # today's ingest writes at most one option id; the kernel is
            # list-valued so the situation table stays enumerable either way.
            selection = (region["selection"],)
        return SelectionRead(
            region["content_state"], selection_state, selection
        )
