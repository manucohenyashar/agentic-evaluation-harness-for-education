"""Ingesting one document: sanitize, rasterize and transcribe every page, then store it."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from typing import Any, Sequence

from aeh.prov import PromptPayload, SamplingParams

from .settings import (
    _configured_dpi,
    _configured_max_tokens,
    DEFAULT_DIVERGENCE_HALT,
    DEFAULT_DUPLICATE_THRESHOLD,
    DEFAULT_RETAIN_PAGE_RASTERS,
    DIVERGENCE_HALT_ENV,
    DOCUMENT_KINDS,
    DocumentId,
    DocumentKind,
    DUPLICATE_ENV,
    LOGGER,
    RETAIN_PAGE_RASTERS_ENV,
    TRANSCRIPTION_PROMPT_VERSION,
)
from .descriptions import (
    description_disagreement,
    _jaccard_similarity,
    SECOND_DESCRIPTION_PROMPT,
    SECOND_DESCRIPTION_PROMPT_VERSION,
)
from .errors import IngestDuplicateError, IngestError, IngestGapError, IngestOrderError
from .rasterizer import PageImage
from .schema import INGEST_STATEMENTS
from .assembly import _natural_key, _parse_fiducial, _parse_page_number
from .regions import _evaluative_offences, _mark_untrusted_content, _parse_regions


class DocumentIngestionMixin:
    """Ingests one logical document and stores its canonical Markdown."""

    # -- the gateway -----------------------------------------------------------------------------

    def ingest_document(
        self, blobs: Sequence[str], kind: DocumentKind,
        order_hint: Sequence[str] | None = None,
        package_version: str | None = None,
        submission_id: str | None = None,
        filenames: dict[str, str] | None = None,
        report_detail: dict | None = None,
        high_risk_question_ids: Sequence[str] | None = None,
    ) -> DocumentId:
        """Ingest one logical document: rasterize every page of every source PDF, run
        exactly ONE VLM transcription call per page, and emit exactly ONE immutable
        Markdown `document` row (`FR-INGEST-02`, `FR-INGEST-04`).

        `blobs` are content hashes in the blob store. The assembly order comes from
        the declared preference ladder (FR-INGEST-06): an operator-stated
        `order_hint` (blob hashes in order) > printed page numbers parsed from the
        transcripts > fiducial markers > `filenames` (blob hash -> source filename,
        natural-sorted). With no tier available the call refuses — the module never
        guesses (FR-INGEST-31). `kind` is one of the four artifact kinds — there is
        no per-kind alternative path: the pipeline below is the only one. Returns the
        new `DocumentId`."""
        if kind not in DOCUMENT_KINDS:
            raise IngestError(
                f"document kind {kind!r} is not one of {DOCUMENT_KINDS}. There are "
                "exactly four artifact kinds and one pipeline."
            )
        if not blobs:
            raise IngestError("ingest_document needs at least one source blob.")
        document_id = f"doc-{uuid.uuid4().hex[:12]}"
        transcriber_ref: str | None = None
        # The per-page transcription strike log (#220): strikes and recoveries
        # land in the report's stage detail when a report_detail dict is given.
        attempt_log: list[dict] = (
            [] if report_detail is None
            else report_detail.setdefault("transcription_attempts", []))
        page_images: list[PageImage] = []
        page_records: list[dict] = []
        dpi = _configured_dpi()
        if self._residency is not None:
            self._residency.acquire("transcriber")
        try:
            pages_used = 0
            # The sanitized copy of each source blob, kept so EVERY decode of the
            # document — page rasters, text layers, retained crops — reads the
            # sanitized bytes and nothing else ever re-reads the original (#42,
            # review B1: the crop path was rendering the unsanitized original).
            sanitized_of: dict[str, bytes] = {}
            for blob_hash in blobs:
                deadline = self._file_deadline(blob_hash)
                pdf_bytes = self._blobs.get(blob_hash)
                # FR-INGEST-33/34: neutralize and bound BEFORE any page is
                # rasterized, and rasterize only the sanitized copy. A refusal
                # raises — quarantine in the submission path, the teacher in the
                # setup-artifact path (FR-INGEST-32).
                sanitized = self._sanitize_source(blob_hash, pdf_bytes,
                                                  pages_used=pages_used,
                                                  deadline=deadline)
                sanitized_of[blob_hash] = sanitized.pdf_bytes
                if sanitized.neutralized:
                    LOGGER.info(
                        "neutralized %s in source blob %s before rasterization",
                        ", ".join(sanitized.neutralized), blob_hash[:12])
                self._refuse_past_deadline(blob_hash, deadline,
                                           "before rasterization")
                pages = self._rasterizer.rasterize(sanitized.pdf_bytes, dpi)
                self._check_rasters(blob_hash, pages)
                self._refuse_past_deadline(blob_hash, deadline,
                                           "during rasterization")
                if not pages:
                    raise IngestError(
                        f"source blob {blob_hash} rasterized to zero pages — a PDF "
                        "with no pages is a V0 finding once the ladder lands; the "
                        "gateway refuses it now."
                    )
                pages_used += len(pages)
                page_images.extend(pages)
                for page in pages:
                    completion = self._transcribe_page(page, blob_hash,
                                                       attempt_log)
                    if (transcriber_ref is not None
                            and completion.resolved_build != transcriber_ref):
                        raise IngestError(
                            f"the transcriber build changed mid-document: "
                            f"{transcriber_ref!r} answered earlier pages, "
                            f"{completion.resolved_build!r} answered page "
                            f"{page.page_no}. One document, one transcriber build — "
                            "re-run the ingestion on one build."
                        )
                    transcriber_ref = completion.resolved_build
                    layer = self._rasterizer.text_layer(sanitized_of[blob_hash],
                                                        page.page_no)
                    page_records.append({
                        "blob_hash": blob_hash,
                        "page_no": page.page_no,
                        "transcript": completion.text,
                        "layer": layer,
                        "image": page,
                        # FR-STORE-06 / issue #226: the full-page raster persists
                        # alongside the crops — or records its honest skip.
                        "raster_hash": self._persist_raster(page),
                    })
        finally:
            if self._residency is not None:
                self._residency.release("transcriber")

        # Duplicates first (FR-INGEST-08): two near-identical pages are surfaced for
        # confirmation, NEVER concatenated — the check runs before any ordering, so a
        # duplicated page cannot slip through because ordering happened to separate it.
        duplicate_threshold = self._configured_float(
            DUPLICATE_ENV, DEFAULT_DUPLICATE_THRESHOLD)
        duplicate_pairs = [
            (left, right)
            for left in range(len(page_records))
            for right in range(left + 1, len(page_records))
            if _jaccard_similarity(page_records[left]["transcript"],
                                   page_records[right]["transcript"])
            > duplicate_threshold
        ]
        if duplicate_pairs:
            named = [
                (f"blob {page_records[l]['blob_hash'][:12]} page "
                 f"{page_records[l]['page_no']}",
                 f"blob {page_records[r]['blob_hash'][:12]} page "
                 f"{page_records[r]['page_no']}")
                for l, r in duplicate_pairs
            ]
            raise IngestDuplicateError(
                f"pages similar above {duplicate_threshold}: {named}. Surface for "
                "confirmation — never concatenate (FR-INGEST-08)."
            )

        # The text layer (FR-INGEST-03): extracted IN ADDITION to transcription, the
        # divergence measured per page with a layer, the document carrying the count
        # and the MAX divergence. A reference artifact over the halt threshold is a
        # corrupted answer key: ingestion HALTS, nothing is written.
        pages_with_layer = sum(1 for record in page_records if record["layer"])
        divergence = max(
            (
                1.0 - _jaccard_similarity(record["layer"], record["transcript"])
                for record in page_records if record["layer"]
            ),
            default=None,
        )
        if kind == "reference" and divergence is not None:
            halt = self._configured_float(DIVERGENCE_HALT_ENV,
                                          DEFAULT_DIVERGENCE_HALT)
            if divergence > halt:
                raise IngestError(
                    f"reference artifact text-layer divergence {divergence:.3f} "
                    f"exceeds the halt threshold {halt:.3f} — a corrupted answer "
                    "key, not a warning (FR-INGEST-03). Nothing was ingested."
                )

        # The order ladder (FR-INGEST-06), strict: operator > page number > marker >
        # filename > refuse. Directory order is never read.
        ordered: list[dict]
        if order_hint is not None:
            hint = list(order_hint)
            if sorted(hint) != sorted(blobs) or len(hint) != len(blobs):
                raise IngestError(
                    "the operator-stated order does not name every source blob "
                    "exactly once."
                )
            ordered = sorted(page_records,
                             key=lambda record: hint.index(record["blob_hash"]))
            order_source = "operator"
        else:
            numbers = [_parse_page_number(record["transcript"])
                       for record in page_records]
            if all(number is not None for number in numbers):
                declared_totals = {total for _, total in numbers}
                if len(declared_totals) != 1:
                    raise IngestGapError(
                        f"the pages disagree about the document's page count "
                        f"({sorted(declared_totals)}): a torn or mixed stack "
                        "(FR-INGEST-09)."
                    )
                total = declared_totals.pop()
                found = [number for number, _ in numbers]
                missing = sorted(set(range(1, total + 1)) - set(found))
                if missing:
                    raise IngestGapError(
                        f"the printed page sequence is missing positions {missing} "
                        f"(found {sorted(found)} of {total}): rescan the missing "
                        "pages or state the order explicitly (FR-INGEST-09)."
                    )
                repeats = sorted({number for number in found
                                  if found.count(number) > 1})
                if repeats:
                    raise IngestGapError(
                        f"the printed page sequence repeats positions {repeats} "
                        "(FR-INGEST-09)."
                    )
                ordered = [record for _, record in
                           sorted(zip(found, page_records),
                                  key=lambda pair: pair[0])]
                order_source = "page_number"
            else:
                markers = [_parse_fiducial(record["transcript"])
                           for record in page_records]
                if all(marker is not None for marker in markers):
                    repeats = sorted({marker for marker in markers
                                      if markers.count(marker) > 1})
                    if repeats:
                        raise IngestGapError(
                            f"the fiducial markers repeat positions {repeats} — "
                            "a misprint or a duplicated sheet (FR-INGEST-09)."
                        )
                    # Natural sort: [fiducial:page-10] sorts after [fiducial:page-2],
                    # exactly as the filename tier treats page-10.md.
                    ordered = [record for _, record in
                               sorted(zip(markers, page_records),
                                      key=lambda pair: _natural_key(pair[0]))]
                    order_source = "marker"
                elif filenames and all(filenames.get(blob) for blob in blobs):
                    name_of = {record["blob_hash"]: filenames[record["blob_hash"]]
                               for record in page_records}
                    # The ambiguity line (FR-INGEST-31, #227): the design names
                    # "ambiguous filenames" a refusal but draws no line between
                    # ambiguous and resolvable-by-tier, so it is pinned here from
                    # the ladder's own ordering rule — the filename tier resolves
                    # iff its natural keys form a strict total order. A key
                    # collision (identical names, or distinct names whose
                    # digit-variant spellings reduce to the same key — page-1 vs
                    # page-01) leaves the tier nothing to order by; distinct keys
                    # always order (scan-2.md vs scan-10.md is natural-sorted,
                    # never ambiguous). The tier orders BLOBS — every page of one
                    # blob shares that blob's name and sorts adjacent to it — so
                    # the collision check runs over the blobs, not the pages. The
                    # ladder's precedence is untouched: an operator hint or
                    # resolvable page numbers resolves above this tier and the
                    # ambiguity never matters.
                    keys = [tuple(_natural_key(filenames[blob]))
                            for blob in blobs]
                    colliding = sorted({
                        filenames[blob]
                        for blob, key in zip(blobs, keys)
                        if keys.count(key) > 1
                    })
                    if colliding:
                        raise IngestOrderError(
                            f"ambiguous filenames cannot be ordered: "
                            f"{', '.join(repr(name) for name in colliding)} "
                            "resolve to the same position, so the filename tier "
                            "cannot order them. The module never guesses "
                            "(FR-INGEST-31) — state the order and re-ingest."
                        )
                    ordered = sorted(
                        page_records,
                        key=lambda record: _natural_key(
                            name_of[record["blob_hash"]]))
                    order_source = "filename"
                else:
                    raise IngestOrderError(
                        "assembly order cannot be determined: no operator-stated "
                        "order, no printed page numbers, no fiducial markers, and "
                        "no unambiguous filenames. The module never guesses "
                        "(FR-INGEST-31) — state the order and re-ingest."
                    )
        # The regions (FR-INGEST-13/10/11/12) come BEFORE the document row is
        # assembled: a re-request replaces the page's transcript, and the stored
        # Markdown must be the FINAL one — the rejected judgement must not survive in
        # document.markdown (review B3).
        retries = self._configured_retries()
        all_regions: list[dict] = []
        position_cursor = 0
        re_requests = 0
        for record in ordered:
            # FR-INGEST-35: the emission rule runs over the FINAL transcript,
            # after the ordering ladder and the divergence measure — both read
            # the raw transcription; the stored Markdown and the region rows
            # then both carry the untrusted marker. (This is the demarcation
            # gate — a post-transcription emission gate on the one pipeline,
            # not a per-kind path; TC-INGEST-02's guard exempts it structurally,
            # keyed on the transform call in the branch body.)
            if kind == "submission":
                record["transcript"] = _mark_untrusted_content(record["transcript"])
            regions = _parse_regions(record["transcript"], record["blob_hash"],
                                     record["page_no"], position_cursor, kind)
            offenders = [region for region in regions
                         if region["description"]
                         and _evaluative_offences(region["description"])]
            attempt = 0
            while offenders and attempt < retries:
                # Reject and RE-REQUEST (FR-INGEST-11): the same page again, one more
                # VLM call per attempt.
                re_requests += 1
                completion = self._transcribe_page(record["image"],
                                                   record["blob_hash"],
                                                   attempt_log)
                record["transcript"] = completion.text
                if kind == "submission":  # the FR-INGEST-35 demarcation gate, not a path
                    record["transcript"] = _mark_untrusted_content(
                        record["transcript"])
                regions = _parse_regions(record["transcript"], record["blob_hash"],
                                         record["page_no"], position_cursor, kind)
                offenders = [region for region in regions
                             if region["description"]
                             and _evaluative_offences(region["description"])]
                attempt += 1
            if offenders:
                raise IngestError(
                    f"{len(offenders)} description(s) still contain evaluative "
                    f"vocabulary after {retries} re-request(s): the descriptions "
                    "would hand the panel a pre-made judgement (FR-INGEST-11). "
                    "Surface for the operator."
                )
            all_regions.extend(regions)
            position_cursor += len(regions)
        # B1: the crops are IMAGE crops (FR-INGEST-13) — the region's box carved from
        # the page raster through the rasterizer seam, or the whole page raster when
        # the model emitted no box. Never the description text. The crop reads the
        # SANITIZED source bytes (#42: a retained crop must no more re-render the
        # unsanitized original than the page raster does).
        for region in all_regions:
            if region["region_kind"] == "described_graphic":
                # The region's OWN page record — matching the page index, not
                # the blob's first page: a boxless described_graphic crops the
                # whole page IT sits on, and on a multi-page source the pages
                # differ in size (review, #226 — the scripted doubles' box-
                # blind crop masked this until the live rasterizer landed).
                record = next(r for r in ordered
                              if r["blob_hash"] == region["source_hash"]
                              and r["page_no"] == region["page_index"])
                box = region.get("crop_box")
                crop_png = self._rasterizer.crop(
                    sanitized_of[region["source_hash"]], region["page_index"],
                    box if box is not None else (0, 0, record["image"].width_px,
                                                 record["image"].height_px),
                    _configured_dpi())
                region["crop_ref"] = self._blobs.put(crop_png)
                region["crop_png"] = crop_png
        # FR-INGEST-14: the second description of each high-risk crop, before the rows
        # are written so `description_secondary` lands with its region.
        second_pass = self._second_describe(
            all_regions,
            self._high_risk if high_risk_question_ids is None
            else tuple(high_risk_question_ids),
            transcriber_ref=transcriber_ref)
        if report_detail is not None and second_pass is not None:
            report_detail["second_descriptions"] = second_pass["regions"]
            report_detail["second_description_pass"] = {
                key: value for key, value in second_pass.items() if key != "regions"}
        # The Markdown is assembled from the FINAL transcripts (B3).
        markdown = self._assemble([record["transcript"] for record in ordered])
        content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        provenance = {
            # FR-INGEST-14: the pass's summary and each region's outcome, frozen at
            # ingest (the verdict included), so M-INTEG reads what ingest decided.
            **({"second_description_pass": {
                **{key: value for key, value in second_pass.items() if key != "regions"},
                "regions": [
                    {key: entry.get(key) for key in (
                        "region_id", "question_id", "status", "error", "second_model",
                        "resolved_build", "disagreement")}
                    for entry in second_pass["regions"]],
            }} if second_pass is not None else {}),
            "order_source": order_source,
            "pages": [
                {"blob_hash": record["blob_hash"], "page_no": record["page_no"],
                 "position": position + 1,
                 "raster_hash": record.get("raster_hash")}
                for position, record in enumerate(ordered)
            ],
        }
        with self._handle.transaction() as tx:
            # The parent row first: document_region's FK points at it.
            tx.execute(INGEST_STATEMENTS["insert_document"],
                       document_id=document_id, submission_id=submission_id,
                       content_hash=content_hash, markdown=markdown,
                       transcriber_ref=transcriber_ref,
                       prompt_template_version=TRANSCRIPTION_PROMPT_VERSION,
                       kind=kind, parent_doc_id=None,
                       source_blobs=json.dumps(provenance, sort_keys=True),
                       pages_with_text_layer=pages_with_layer,
                       text_layer_divergence=divergence,
                       created_at=self._now())
            for region in all_regions:
                tx.execute(INGEST_STATEMENTS["insert_region"],
                           region_id=region["region_id"],
                           document_id=document_id,
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
                           is_untrusted_content=region["is_untrusted_content"],
                           description_secondary=region.get("description_secondary"),
                           question_id=region.get("question_id"))
                for token in re.findall(r"<unresolved>(.*?)</unresolved>",
                                        region["content"] or ""):
                    if token.strip():
                        tx.execute(INGEST_STATEMENTS["insert_unresolved_token"],
                                   token=token.strip().lower(),
                                   region_id=region["region_id"],
                                   document_id=document_id)
        LOGGER.info(
            "ingested document %s kind=%s pages=%d order=%s content_hash=%s "
            "transcriber=%s divergence=%s regions=%d re_requests=%d "
            "rasters=%d persisted, %d skipped",
            document_id, kind, len(page_images), order_source, content_hash[:12],
            transcriber_ref,
            None if divergence is None else round(divergence, 3),
            len(all_regions), re_requests,
            sum(1 for record in page_records if record.get("raster_hash")),
            sum(1 for record in page_records
                if not record.get("raster_hash")),
        )
        if report_detail is not None:
            # Seam 4: the new storage surface reports what it did next to the
            # status — a bare success must not sit on top of an unrecorded one.
            rasters_persisted = sum(1 for record in page_records
                                    if record.get("raster_hash"))
            report_detail["rasters"] = {
                "persisted": rasters_persisted,
                "skipped": len(page_records) - rasters_persisted,
            }
        return document_id

    def _enforce_evaluative_bar(self, regions: list[dict]) -> list[dict]:
        """The FR-INGEST-11 gate over parsed regions: re-request up to the budget,
        then refuse. Factored so ingest and revise enforce the SAME bar."""
        offenders = [region for region in regions
                     if region["description"]
                     and _evaluative_offences(region["description"])]
        if offenders:
            raise IngestError(
                f"{len(offenders)} description(s) contain evaluative vocabulary: "
                "the descriptions would hand the panel a pre-made judgement "
                "(FR-INGEST-11). Surface for the operator."
            )
        return regions

    def _persist_raster(self, page: PageImage) -> str | None:
        """`FR-STORE-06`'s storage form for the full-page raster (issue #226):
        the blob goes into the same content-addressed store as the source PDFs
        and the crops — keyed by SHA-256, deduplicated on write — and only the
        hash is recorded, in `document.source_blobs`' per-page provenance.
        Retention follows the crop precedent: kept until the cohort's Tier C
        purge (`NFR-INGEST-04`, student PII). `HARNESS_INGEST_RETAIN_PAGE_RASTERS`
        is the environment-sensitive bound, read at call time (seam 3): off,
        the skip is what the provenance honestly records (a null
        `raster_hash`) and `FR-INGEST-13`'s crops still flow."""
        if not self._configured_bool(RETAIN_PAGE_RASTERS_ENV,
                                     DEFAULT_RETAIN_PAGE_RASTERS):
            return None
        return self._blobs.put(page.png)

    def _second_describe(self, regions: list[dict],
                         high_risk_questions: Sequence[str], *,
                         transcriber_ref: str | None = None) -> dict | None:
        """FR-INGEST-14: describe each high-risk described graphic's crop a second
        time with the different-family model. Returns the pass record — `None` only
        when no high-risk register was injected — so "register given, nothing
        matched" is never silent: the record names the declared questions, how many
        graphics the document holds, how many matched, and each region's outcome.

        **Which question a graphic belongs to.** The pinned transcription prompt tags
        a graphic by `element_kind`, not by question, so a graphic belongs to the
        question in force where it appears (an explicit `question_id` on the graphic's
        own marker wins). Since `#373` that is `question_id`, carried forward by
        `_parse_regions` and stored on the row, so this pass reads the fact rather than
        recomputing it. A graphic before any question region belongs to none and is
        counted as unassigned.

        Every other region gets exactly one description. A failed second call — an
        exception, an empty or evaluative reply, or an answer resolved to the
        transcriber's own build — leaves `description_secondary` NULL and is recorded
        as `failed`, never read as agreement. The second call holds the residency
        slot under its own role, like the transcription it follows."""
        if not self._high_risk or self._second_model_ref is None:
            return None
        wanted = set(high_risk_questions)
        entries: list[dict] = []
        graphics = unassigned = 0
        params = SamplingParams(temperature=0.0, max_tokens=_configured_max_tokens())
        second_ref = self._second_model_ref
        candidates = []
        for region in regions:
            if region["region_kind"] != "described_graphic":
                continue
            graphics += 1
            # `#373`: one read of the parsed column, where a walk carrying the question
            # forward across the non-graphic regions used to stand. `_parse_regions` now
            # does that carry-forward itself, so this is the same answer from the single
            # place that owns it — and the second copy of the rule, which could drift
            # from the stored one, is gone.
            question = region.get("question_id")
            if question is None:
                unassigned += 1
                continue
            if question in wanted and region.get("crop_png") is not None:
                candidates.append((region, question))
        if candidates and self._residency is not None:
            self._residency.acquire("second_describer")
        try:
            for region, question in candidates:
                payload = PromptPayload(fields=(
                    ("instruction", SECOND_DESCRIPTION_PROMPT),
                    ("prompt_template_version", SECOND_DESCRIPTION_PROMPT_VERSION),
                    ("crop_ref", str(region["crop_ref"])),
                    ("image_png_base64",
                     base64.b64encode(region["crop_png"]).decode("ascii")),
                ))
                entry: dict[str, Any] = {
                    "region_id": region["region_id"],
                    "question_id": question,
                    "crop_ref": region["crop_ref"],
                    "description": region["description"],
                    "second_model": {"provider": second_ref.provider,
                                     "build_id": second_ref.build_id},
                }
                try:
                    completion = self._provider.complete(payload, second_ref, params)
                    text = (completion.text or "").strip()
                    resolved = getattr(completion, "resolved_build", None)
                    entry["resolved_build"] = resolved
                    if transcriber_ref is not None and resolved == transcriber_ref:
                        raise IngestError(
                            f"the second description resolved to the transcriber's own "
                            f"build {resolved!r}: not a second family (FR-INGEST-14)")
                    if not text:
                        raise IngestError("the second model returned an empty description")
                    if _evaluative_offences(text):
                        raise IngestError(
                            "the second description contains evaluative vocabulary "
                            "(FR-INGEST-11)")
                except Exception as error:  # noqa: BLE001 -- recorded, never agreement
                    entry.update(status="failed", error=str(error),
                                 description_secondary=None, disagreement=None)
                    LOGGER.warning("second description failed for region %s: %s",
                                   region["region_id"], error)
                else:
                    region["description_secondary"] = text
                    entry.update(
                        status="described", error=None, description_secondary=text,
                        disagreement=description_disagreement(region["description"], text))
                entries.append(entry)
        finally:
            if candidates and self._residency is not None:
                self._residency.release("second_describer")
        return {
            "status": "ran",
            "declared_criteria": list(self._high_risk),
            "high_risk_questions": sorted(wanted),
            "graphics": graphics,
            "unassigned_graphics": unassigned,
            "matched": len(candidates),
            "described": sum(1 for e in entries if e["status"] == "described"),
            "failed": sum(1 for e in entries if e["status"] == "failed"),
            "disagreements": sum(1 for e in entries
                                 if e.get("disagreement") and e["disagreement"]["disagrees"]),
            "regions": entries,
        }

    def _retain_crops(self, regions: list[dict],
                      sanitized_of: dict[str, bytes],
                      page: PageImage) -> list[dict]:
        """FR-INGEST-13: a described_graphic's crop is an IMAGE crop carved from the
        page raster through the rasterizer seam, retained in the blob store. The
        crop reads the SANITIZED source bytes (#42, review B1) — never the
        original blob. A region with no box crops the WHOLE page raster — the
        rect of the page these regions were parsed from (`page`, the same image
        the model saw), matching the ingest path's default; a zero rect would
        be refused by the live crop rather than silently clamped, and the
        scripted doubles masked that disagreement for years (review, #226)."""
        for region in regions:
            if region["region_kind"] != "described_graphic":
                continue
            box = region.get("crop_box")
            crop_png = self._rasterizer.crop(sanitized_of[region["source_hash"]],
                                             region["page_index"],
                                             box if box is not None
                                             else (0, 0, page.width_px,
                                                   page.height_px),
                                             _configured_dpi())
            region["crop_ref"] = self._blobs.put(crop_png)
        return regions
