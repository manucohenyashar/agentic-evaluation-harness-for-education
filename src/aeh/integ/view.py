"""`StoreExtractionView`: reads a cell's extraction results from the store for the gate."""

from __future__ import annotations

import json
from typing import Any

from .schema import INTEG_STATEMENTS


class StoreExtractionView:
    """The extraction view the gate reads in production (`FR-INTEG-09`).

    `M-INTEG` publishes it because the five reads ARE this module's declared *Requires*
    surface (`CT-INTEG-17`): `spans`, `second_family_spans`, `regions`, `panel_sufficiency` and
    `criterion_requires_citation`. A test double that implements the same five is a double of
    THIS, which is what keeps the doubles honest.

    Constructed as `StoreExtractionView(handle, catalog, package_version_id)`: the cohort
    handle the evidence and regions live on, the package catalog the criterion's citation
    requirement is declared in, and the version that declaration belongs to.

    **Every read raises on a fault** — it never substitutes an empty result. That is the whole
    contract: the gate's fail-closed routing reads an exception as "adverse and unknown", and a
    view that returned `[]` for a faulted evidence read would tell it "measured, and there is
    nothing", which is the one lie the gate cannot detect (`NFR-INTEG-03`).
    """

    def __init__(self, handle: Any, catalog: Any, package_version_id: str,
                 run_id: str = "") -> None:
        self._handle = handle
        self._catalog = catalog
        self._package_version_id = package_version_id
        self._run_id = run_id

    def _cell_query(self, key: str, submission_id: str, criterion_id: str) -> list:
        """One cell read, scoped to this view's run when it has one."""
        if self._run_id:
            return list(self._handle.query(
                INTEG_STATEMENTS[f"{key}_in_run"], run_id=self._run_id,
                submission_id=submission_id, criterion_id=criterion_id,
            ))
        return list(self._handle.query(
            INTEG_STATEMENTS[key],
            submission_id=submission_id, criterion_id=criterion_id,
        ))

    def _payloads(self, submission_id: str, criterion_id: str) -> list:
        """Every extraction payload the cell carries, in `work_id` order.

        A cell that was re-extracted has more than one, and the last is the current
        one — reading only the first would hand the gate the rejected extraction
        forever, which quarantines a cell whose re-extraction actually succeeded.
        """
        payloads = []
        for row in self._cell_query("read_cell_evidence", submission_id, criterion_id):
            payload = row["payload"]
            if payload is None:
                continue
            if isinstance(payload, (bytes, bytearray)):
                payload = bytes(payload).decode("utf-8")
            payloads.append(json.loads(payload))
        return payloads

    def _payload(self, submission_id: str, criterion_id: str) -> dict:
        """The cell's CURRENT extraction payload — the last one written."""
        payloads = self._payloads(submission_id, criterion_id)
        return payloads[-1] if payloads else {}

    def spans(self, submission_id: str, criterion_id: str) -> list:
        """The cell's extracted spans, as `M-EXTRACT` wrote them.

        Every payload's spans, not just the current one's: a span the gate has already
        verified stays verified, and a re-extraction that dropped it should not make the
        cell read as though the evidence had never been found."""
        spans: list = []
        for payload in self._payloads(submission_id, criterion_id):
            spans.extend(payload.get("spans") or ())
        return spans

    def second_family_spans(self, submission_id: str, criterion_id: str) -> "list | None":
        """The second family's spans, or `None` where no second family ran — `None` is
        "not measured" and the gate reads it as such, never as agreement."""
        second = self._payload(submission_id, criterion_id).get("second_family")
        if not isinstance(second, dict) or "spans" not in second:
            return None
        return list(second.get("spans") or ())

    def regions(self, document_id: str) -> list:
        """The document's stored regions, in position order, each carrying its extent.

        The gate asks by its own `doc-<submission_id>` spelling; the store's document ids
        are minted (`doc-<uuid12>`), so the request resolves through the submission foreign
        key. `document_region` stores no byte extents, so each region's is located by
        finding its stored content in the canonical Markdown — in BYTES, the units
        `verify_span` compares in — with a cursor advancing in row order, so a document
        that repeats a region's content addresses successive occurrences rather than
        collapsing them onto the first.

        A region whose content the canonical text no longer carries takes a zero-length
        extent at the cursor: present and measured, overlapping nothing. It is not dropped,
        because a dropped region is indistinguishable from a document that never had one.
        """
        submission_id = (
            document_id[len("doc-"):] if document_id.startswith("doc-") else document_id
        )
        docs = self._handle.query(
            INTEG_STATEMENTS["read_document_for_regions"], submission_id=submission_id
        )
        if not docs:
            return []
        markdown = docs[0]["markdown"] or ""
        raw = markdown.encode("utf-8") if isinstance(markdown, str) else bytes(markdown)
        items: list = []
        cursor = 0
        for row in self._handle.query(
            INTEG_STATEMENTS["read_document_regions"], document_id=docs[0]["document_id"]
        ):
            region = dict(row)
            content = region.get("content") or ""
            needle = content.encode("utf-8") if isinstance(content, str) else bytes(content)
            start = raw.find(needle, cursor) if needle else cursor
            if start < 0:
                start = cursor
                needle = b""
            region["start"] = start
            region["end"] = start + len(needle)
            cursor = max(cursor, start)
            items.append(region)
        return items

    def panel_sufficiency(self, submission_id: str, criterion_id: str) -> tuple:
        """Each landed verdict's `evidence_sufficient` answer for the cell, in `work_id`
        order — the panel's own flags, never a computed substitute."""
        return tuple(
            None if row["evidence_sufficient"] is None else bool(row["evidence_sufficient"])
            for row in self._cell_query(
                "read_panel_sufficiency", submission_id, criterion_id
            )
        )

    def criterion_requires_citation(self, criterion_id: str) -> bool:
        """Whether the criterion's declaration requires cited evidence (`M-PKG`'s own
        reading, read through the catalog rather than re-derived here)."""
        for row in self._catalog.criteria(self._package_version_id):
            row_id = row["criterion_id"] if isinstance(row, dict) else row.get("criterion_id")
            if str(row_id) == str(criterion_id):
                value = (row.get("evidence_type") if isinstance(row, dict)
                         else getattr(row, "evidence_type", None))
                # Fail closed on NULL as well as on absence. `evidence_type` is nullable
                # TEXT with no CHECK and one writer (`M-PKG`'s read-back), so NULL means
                # "not declared", not "declared as needing nothing" — and reading it as the
                # latter releases a zero-span cell as verified, which is the outcome
                # `FR-INTEG-03` exists to prevent.
                return value is None or str(value) != "none"
        return True  # fail-closed: an undeclared criterion is read as requiring citation
