"""Applying a correction: re-transcribing replaced pages into a new document revision."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Sequence

from .settings import _configured_dpi, DocumentId, LOGGER, TRANSCRIPTION_PROMPT_VERSION
from .descriptions import _jaccard_similarity
from .errors import IngestError
from .rasterizer import PageImage
from .schema import INGEST_STATEMENTS
from .records import PageReplacement
from .regions import _mark_untrusted_content, _parse_regions


class RevisionMixin:
    """Applies a correction as a new revision of a stored document."""

    def revise_document(
        self, document_id: DocumentId, replacement_pages: Sequence[PageReplacement],
    ) -> DocumentId:
        """Apply a correction (FR-INGEST-05): re-transcribe the replaced pages and write a new
        document row with `parent_doc_id` set and a new `content_hash`. The original row is never
        changed, so the id returned always differs from the one passed in."""
        rows = self._handle.query(INGEST_STATEMENTS["select_document"],
                                  document_id=document_id)
        if not rows:
            raise IngestError(f"document {document_id!r} does not exist.")
        row = rows[0]
        provenance = json.loads(row["source_blobs"] or "{}")
        if isinstance(provenance, dict) and "pages" in provenance:
            # The structured form (#37): the recorded provenance IS the page sequence —
            # iterate positions 1..N and take (blob, page_no) from each entry. The
            # page_number/marker tiers INTERLEAVE pages across files, so a running
            # per-blob counter would silently replace the wrong page and lose another.
            page_sequence = [
                (entry["blob_hash"], entry["page_no"])
                for entry in sorted(provenance["pages"],
                                    key=lambda e: e["position"])
            ]
        else:
            # The legacy list form (pre-#37 rows): raster order within each blob.
            page_sequence = None
            source_blobs = list(provenance) if isinstance(provenance, list) else []
        replacements = {replacement.page_no: replacement.blob_hash
                        for replacement in replacement_pages}
        if not replacements:
            raise IngestError("revise_document needs at least one replacement page.")

        markdown_parts: list[str] = []
        # The divergence measure reads the RAW transcripts (FR-INGEST-03): the
        # untrusted-marker protocol (#42) is scaffolding the harness adds after
        # the measure, so the recorded divergence stays comparable across prompt
        # versions.
        raw_parts: list[str] = []
        transcriber_ref: str | None = None
        new_provenance_pages: list[dict] = []
        layers: list[str] = []
        revision_regions_all: list[dict] = []
        dpi = _configured_dpi()
        if self._residency is not None:
            self._residency.acquire("transcriber")
        try:
            raster_cache: dict[str, list[PageImage]] = {}
            # The sanitized copy per source blob (review B1): text layers and
            # retained crops read it too — nothing re-reads the original.
            sanitized_cache: dict[str, bytes] = {}

            def pages_of(blob_hash: str) -> list[PageImage]:
                if blob_hash not in raster_cache:
                    # A revision re-reads source blobs: the same sanitize-and-
                    # bound stage applies, per blob (a revised document's total
                    # page count was already bounded when it was first ingested;
                    # the rescans are one-page sources).
                    deadline = self._file_deadline(blob_hash)
                    sanitized = self._sanitize_source(
                        blob_hash, self._blobs.get(blob_hash), pages_used=0,
                        deadline=deadline)
                    if sanitized.neutralized:
                        LOGGER.info(
                            "neutralized %s in source blob %s before "
                            "re-rasterization",
                            ", ".join(sanitized.neutralized), blob_hash[:12])
                    sanitized_cache[blob_hash] = sanitized.pdf_bytes
                    self._refuse_past_deadline(blob_hash, deadline,
                                               "before re-rasterization")
                    raster_cache[blob_hash] = self._rasterizer.rasterize(
                        sanitized.pdf_bytes, dpi)
                    self._check_rasters(blob_hash, raster_cache[blob_hash])
                    self._refuse_past_deadline(blob_hash, deadline,
                                               "during re-rasterization")
                return raster_cache[blob_hash]

            if page_sequence is not None:
                # One transcription call per recorded position, in assembled order.
                for position, (blob_hash, page_no) in enumerate(page_sequence,
                                                                start=1):
                    pages = pages_of(blob_hash)
                    page = pages[page_no - 1]
                    replacement = replacements.pop(position, None)
                    replaced_from: str | None = None
                    if replacement is not None:
                        # A rescan is a one-page PDF holding the replacement page.
                        rescan = pages_of(replacement)
                        if len(rescan) != 1:
                            raise IngestError(
                                f"the replacement for position {position} rasterized "
                                f"to {len(rescan)} pages; a replacement page is one "
                                "page."
                            )
                        replaced_from = page_no
                        page = PageImage(page_no=1, png=rescan[0].png,
                                         width_px=rescan[0].width_px,
                                         height_px=rescan[0].height_px)
                        blob_hash, page_no = replacement, 1
                    completion = self._transcribe_page(page, blob_hash)
                    if (transcriber_ref is not None
                            and completion.resolved_build != transcriber_ref):
                        raise IngestError(
                            f"the transcriber build changed mid-revision: "
                            f"{transcriber_ref!r} answered earlier pages, "
                            f"{completion.resolved_build!r} answered this one. One "
                            "document, one transcriber build — re-run the revision "
                            "on one build."
                        )
                    transcriber_ref = completion.resolved_build
                    raw_parts.append(completion.text)
                    # FR-INGEST-35 holds on corrections: a revised SUBMISSION page
                    # is re-emitted marked like the original (the region rows
                    # already key their column off the document's kind).
                    text = (completion.text if row["kind"] != "submission"
                            else _mark_untrusted_content(completion.text))
                    markdown_parts.append(text)
                    layers.append(self._rasterizer.text_layer(
                        sanitized_cache[blob_hash], page_no)
                        if replaced_from is None else "")
                    # M5: the revision's pages are regionized too — a head later
                    # stages read carries regions whether it came from ingest or
                    # from a correction, and the evaluative gate holds on both.
                    revision_regions = _parse_regions(
                        text, blob_hash, page_no, len(markdown_parts) - 1,
                        "revision")
                    revision_regions = self._enforce_evaluative_bar(revision_regions)
                    revision_regions = self._retain_crops(
                        revision_regions, sanitized_cache, page)
                    revision_regions_all.extend(revision_regions)
                    new_provenance_pages.append({
                        "blob_hash": blob_hash, "page_no": page_no,
                        "position": position, **({"replaced": replaced_from}
                                                 if replaced_from else {}),
                        # FR-STORE-06 / issue #226: the revision's pages persist
                        # their rasters like the original ingest's.
                        "raster_hash": self._persist_raster(page),
                    })
            else:
                position = 0
                for blob_hash in source_blobs:
                    pdf_bytes = self._blobs.get(blob_hash)
                    deadline = self._file_deadline(blob_hash)
                    # The legacy-provenance branch rasterizes whole sources the
                    # same way: sanitized copy only (FR-INGEST-33).
                    sanitized = self._sanitize_source(blob_hash, pdf_bytes,
                                                      pages_used=0,
                                                      deadline=deadline)
                    if sanitized.neutralized:
                        LOGGER.info(
                            "neutralized %s in source blob %s before "
                            "re-rasterization",
                            ", ".join(sanitized.neutralized), blob_hash[:12])
                    sanitized_cache[blob_hash] = sanitized.pdf_bytes
                    self._refuse_past_deadline(blob_hash, deadline,
                                               "before re-rasterization")
                    legacy_pages = self._rasterizer.rasterize(sanitized.pdf_bytes,
                                                              dpi)
                    self._check_rasters(blob_hash, legacy_pages)
                    self._refuse_past_deadline(blob_hash, deadline,
                                               "during re-rasterization")
                    for page in legacy_pages:
                        position += 1
                        replacement = replacements.pop(page.page_no, None)
                        if replacement is not None:
                            rescan = pages_of(replacement)
                            if len(rescan) != 1:
                                raise IngestError(
                                    f"the replacement for page {page.page_no} "
                                    f"rasterized to {len(rescan)} pages; a "
                                    "replacement page is one page."
                                )
                            page = PageImage(page_no=page.page_no,
                                             png=rescan[0].png,
                                             width_px=rescan[0].width_px,
                                             height_px=rescan[0].height_px)
                        completion = self._transcribe_page(page, blob_hash)
                        if (transcriber_ref is not None
                                and completion.resolved_build != transcriber_ref):
                            raise IngestError(
                                "the transcriber build changed mid-revision: "
                                f"{transcriber_ref!r} answered earlier pages, "
                                f"{completion.resolved_build!r} answered this one."
                            )
                        transcriber_ref = completion.resolved_build
                        raw_parts.append(completion.text)
                        text = (completion.text if row["kind"] != "submission"
                                else _mark_untrusted_content(completion.text))
                        markdown_parts.append(text)
                        layers.append("")
                        revision_regions = _parse_regions(
                            text, blob_hash, page.page_no,
                            len(markdown_parts) - 1, "revision")
                        revision_regions = self._enforce_evaluative_bar(
                            revision_regions)
                        revision_regions = self._retain_crops(
                            revision_regions, sanitized_cache, page)
                        revision_regions_all.extend(revision_regions)
                        new_provenance_pages.append({
                            "blob_hash": blob_hash, "page_no": page.page_no,
                            "position": position,
                            # FR-STORE-06 / issue #226, as above.
                            "raster_hash": self._persist_raster(page),
                        })
            if replacements:
                raise IngestError(
                    f"replacement positions {sorted(replacements)} do not exist in "
                    f"document {document_id!r} "
                    f"({len(page_sequence or source_blobs)} page(s))."
                )
        finally:
            if self._residency is not None:
                self._residency.release("transcriber")
        new_id = f"doc-{uuid.uuid4().hex[:12]}"
        markdown = self._assemble(markdown_parts)
        content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        # The revision's own provenance (FR-INGEST-07): the replaced positions point
        # at the RESCAN blob they actually came from — copying the parent's record
        # verbatim would claim a citation's page is the pre-correction scan.
        order_source = (provenance.get("order_source", "operator")
                        if isinstance(provenance, dict) else "operator")
        pages_with_layer = sum(1 for layer in layers if layer)
        divergence = max(
            (1.0 - _jaccard_similarity(layer, text)
             for layer, text in zip(layers, raw_parts) if layer),
            default=None,
        )
        with self._handle.transaction() as tx:
            tx.execute(INGEST_STATEMENTS["insert_document"],
                       document_id=new_id, submission_id=row["submission_id"],
                       content_hash=content_hash, markdown=markdown,
                       transcriber_ref=transcriber_ref,
                       prompt_template_version=TRANSCRIPTION_PROMPT_VERSION,
                       kind=row["kind"], parent_doc_id=document_id,
                       source_blobs=json.dumps(
                           {"order_source": order_source,
                            "pages": new_provenance_pages,
                            # FR-INGEST-14: a revision does not re-run the second
                            # description; with a register injected that is stated,
                            # so the revised head never reads as "not high-risk".
                            **({"second_description_pass": {
                                "status": "not_run",
                                "reason": "revise_document does not run the "
                                          "FR-INGEST-14 pass; re-ingest the "
                                          "submission to describe its graphics again",
                                "declared_criteria": list(self._high_risk)}}
                               if self._high_risk else {})}, sort_keys=True),
                       pages_with_text_layer=pages_with_layer or None,
                       text_layer_divergence=divergence,
                       created_at=self._now())
            for region in revision_regions_all:
                tx.execute(INGEST_STATEMENTS["insert_region"],
                           region_id=region["region_id"],
                           document_id=new_id,
                           page_no=region["page_no"],
                           element_kind=region["element_kind"],
                           region_kind=region["region_kind"],
                           description=region["description"],
                           retraction=region["retraction"],
                           ocr_conf=region.get("ocr_conf"),
                           content_state=region["content_state"],
                           selection_state=region["selection_state"],
                           selection=region["selection"],
                           crop_ref=region.get("crop_ref"),
                           content=region["content"],
                           source_hash=region["source_hash"],
                           page_index=region["page_index"],
                           position=region["position"],
                           is_untrusted_content=1 if row["kind"] == "submission" else 0,
                           description_secondary=None,
                           # `#373`: the revision's regions are freshly parsed, so the
                           # question in force came with them — carry it to the column
                           # rather than letting the new document's rows read NULL and
                           # send their consumers back to positional inference.
                           question_id=region.get("question_id"))
                for token in re.findall(r"<unresolved>(.*?)</unresolved>",
                                        region["content"] or ""):
                    if token.strip():
                        tx.execute(INGEST_STATEMENTS["insert_unresolved_token"],
                                   token=token.strip().lower(),
                                   region_id=region["region_id"],
                                   document_id=new_id)
        LOGGER.info(
            "revised document %s into %s pages_replaced=%d content_hash=%s "
            "regions=%d",
            document_id, new_id, len(replacement_pages), content_hash[:12],
            len(revision_regions_all),
        )
        return new_id
