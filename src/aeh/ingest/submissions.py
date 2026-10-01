"""Ingesting one submission through the validation ladder."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Sequence

from .settings import (
    BLANK_TOLERANCE_ENV,
    _configured_dpi,
    DEFAULT_BLANK_TOLERANCE,
    DocumentId,
    GATE_NOT_REACHED,
    LOGGER,
    _ocr_conf_floor,
)
from .errors import (
    IngestCohortBreakerTripped,
    IngestDuplicateError,
    IngestError,
    IngestGapError,
    IngestTranscriptionError,
)
from .schema import INGEST_STATEMENTS
from .records import IngestReport


class SubmissionIngestionMixin:
    """Ingests one submission through the validation ladder."""

    # -- the absent-region read (FR-INGEST-16/18) -----------------------------------------

    def _absent_regions(self, package_version: str, document_id: DocumentId,
                        declared_regions: Sequence[tuple[str, str]],
                        package_catalog: Any) -> list[tuple[str, str]]:
        """The package's declared questions that the document has no region for. Each becomes its
        own `absent` row. Absent (a scanning failure, sent to triage) and blank (a legitimate zero)
        are separate rows and never merged (FR-INGEST-16). The V2 gate uses this."""
        recorded = {question for question, _ in declared_regions}
        absent: list[tuple[str, str]] = []
        rows = package_catalog.criteria(package_version)
        with self._handle.transaction() as tx:
            for row in rows:
                question_id = row["question_id"]
                if question_id in recorded:
                    continue
                absent.append((question_id, "absent"))
                tx.execute(INGEST_STATEMENTS["insert_region"],
                           region_id=f"reg-{uuid.uuid4().hex[:12]}",
                           document_id=document_id,
                           page_no=1,
                           element_kind=question_id,
                           region_kind="transcribed_text",
                           description=None,
                           retraction=None,
                           # CT-INGEST-04's non-null clause (#221): a minted
                           # absent row records 0.0 — NO OCR was performed on a
                           # question the declared-set diff found unrecorded, so
                           # zero is the honest "no reading evidence", not a
                           # claim the text was read badly. These rows only ever
                           # exist beside the V2 quarantine that minted them, so
                           # the 0.0 can never flag `low_confidence_ocr` (that
                           # outcome fires only on a clean ladder).
                           ocr_conf=0.0,
                           content_state="absent",
                           selection_state=None,
                           selection=None,
                           crop_ref=None,
                           source_hash=None,
                           page_index=None,
                           position=None,
                           is_untrusted_content=0,
                           description_secondary=None,
                           content=None,
                           # `#373`: a minted absent row exists BECAUSE this declared
                           # question had none, so its owner is known exactly — not
                           # inferred from a neighbour, which is why it is recorded
                           # rather than left NULL like a pre-migration row.
                           question_id=question_id)
        return absent

    @staticmethod
    def _declared_options(
        package_catalog: Any | None, package_version: str | None, question_id: str
    ) -> frozenset[str]:
        """The option ids declared for one question, or an empty set when no package was given. Ids
        match exactly: `c` is not `C` (TC-INGEST-50)."""
        if package_catalog is None or package_version is None or not question_id:
            return frozenset()
        reader = getattr(package_catalog, "question_options", None)
        if callable(reader):
            rows = reader(package_version, question_id)
        else:
            handle = getattr(package_catalog, "handle", None) or package_catalog
            rows = handle.query(
                INGEST_STATEMENTS["select_question_options"],
                v=package_version, question_id=question_id,
            )
        ids: set[str] = set()
        for row in rows or ():
            if isinstance(row, str):
                ids.add(row)
            elif isinstance(row, dict):
                ids.add(str(row.get("option_id")))
            else:
                try:
                    ids.add(str(row["option_id"]))
                except (TypeError, KeyError, IndexError):
                    ids.add(str(getattr(row, "option_id", "")))
        return frozenset(name for name in ids if name)

    def ingest_submission(
        self, blobs: Sequence[str], cohort_id: str,
        package_version: str, order_hint: Sequence[str] | None = None,
        filenames: dict[str, str] | None = None,
        package_catalog: Any | None = None,
    ) -> IngestReport:
        """Ingest one submission through the validation ladder (FR-INGEST-21..24): V0 file
        integrity, V1 page completeness, V2 structural completeness (question structure read from
        the package, FR-INGEST-18, FR-INGEST-19), and V3 identity against the roster. Each gate
        records its own outcome in its own column (FR-INGEST-29). A failure quarantines the
        submission, and a quarantined submission never reaches the teacher's review queue
        (FR-INGEST-30).

        Fail the unit, never the run (`NFR-INGEST-02`): a page that fails
        transcription the configured number of times quarantines THIS submission;
        the cohort's remaining submissions continue.

        V4 assessment match (`FR-INGEST-25..28`, #41): a three-valued outcome
        (`match` / `uncertain` / `mismatch`) computed from the four signal families
        and recorded per signal in `submission.v4_signals`; BOTH `uncertain` and
        `mismatch` halt scoring for the submission (`unmatched_assessment`); a
        mismatch records a ranked PROPOSAL and never reassigns (`FR-INGEST-26`).
        When the cohort's breaker is tripped, this call refuses outright — the one
        gate outcome that raises, because it halts the cohort, not the unit."""
        if (tripped := self.cohort_breaker(cohort_id)) is not None:
            raise IngestCohortBreakerTripped(tripped["finding"])
        submission_id = f"sub-{uuid.uuid4().hex[:12]}"
        # Every gate starts NOT REACHED (#222, the F4 fix): the final write
        # records every column, so a `'pass'` init would ride to the row on
        # gates the ladder never reached. Each gate flips to its own outcome
        # only at the point the ladder actually runs it.
        gates: dict[str, str] = {"v0": GATE_NOT_REACHED, "v1": GATE_NOT_REACHED,
                                 "v2": GATE_NOT_REACHED,
                                 "v3": GATE_NOT_REACHED, "v4": "not_run"}
        findings: list[dict] = []
        ingest_status = "ok"
        quarantined = False
        student_ref = "unknown"

        def quarantine(gate: str, status: str, finding: dict) -> None:
            nonlocal ingest_status, quarantined
            gates[gate] = "fail"
            ingest_status = status
            quarantined = True
            findings.append(finding)

        # V0 file integrity (FR-INGEST-21) plus the adversarial-input stage
        # (#42, FR-INGEST-33/34): every source is neutralized and bounded BEFORE
        # any page is rasterized, and only the sanitized copy is rasterized. Zero
        # pages, a blank ratio past tolerance, unremovable active content, a
        # crossed ceiling, or ANY failure inside the sanitize-and-bound stage
        # quarantines as `unreadable` — NFR-INGEST-08's fail-closed rule is that
        # every one of these resolves to quarantine, never to processing, so the
        # catch is deliberately broad.
        v0_failed = False
        neutralized: dict[str, list[str]] = {}
        pages_used = 0
        for blob_hash in blobs:
            pdf_bytes = self._blobs.get(blob_hash)
            try:
                deadline = self._file_deadline(blob_hash)
                sanitized = self._sanitize_source(blob_hash, pdf_bytes,
                                                  pages_used=pages_used,
                                                  deadline=deadline)
                if sanitized.neutralized:
                    neutralized[blob_hash[:12]] = list(sanitized.neutralized)
                    LOGGER.info(
                        "neutralized %s in source blob %s before rasterization",
                        ", ".join(sanitized.neutralized), blob_hash[:12])
                pages = self._rasterizer.rasterize(sanitized.pdf_bytes,
                                                   _configured_dpi())
                self._check_rasters(blob_hash, pages)
            except Exception as error:  # noqa: BLE001 -- NFR-INGEST-08: refuse, never process
                quarantine("v0", "unreadable", {
                    "gate": "v0", "blob_hash": blob_hash[:12],
                    "finding": f"the source was refused by the V0 integrity "
                               f"gate: {error}"})
                v0_failed = True
                continue
            pages_used += len(pages)
            if not pages:
                quarantine("v0", "unreadable", {
                    "gate": "v0", "blob_hash": blob_hash[:12],
                    "finding": "the source has zero pages"})
                v0_failed = True
                continue
            blank = sum(1 for page in pages if not page.png.strip())
            if blank / len(pages) > self._configured_float(
                    BLANK_TOLERANCE_ENV, DEFAULT_BLANK_TOLERANCE):
                quarantine("v0", "unreadable", {
                    "gate": "v0", "blob_hash": blob_hash[:12],
                    "finding": f"{blank}/{len(pages)} blank pages exceed tolerance"})
                v0_failed = True
        if not v0_failed:
            # V0 completed every source without quarantining — its verdict.
            gates["v0"] = "pass"

        # The submission row exists before anything references it: the document's
        # FK points here, and the gate columns write to it after the ladder runs.
        with self._handle.transaction() as tx:
            tx.execute(INGEST_STATEMENTS["insert_submission"],
                       submission_id=submission_id, cohort_id=cohort_id,
                       student_ref=student_ref)
        document_id: DocumentId | None = None
        v2_failures: list[dict] = []
        # Whether V2's declared-set check found questions the package declares
        # with no region in the transcript (#219). Drives the V4 override guard
        # below; False whenever the gate never ran.
        declared_gap = False
        raster_detail: dict = {}
        if not v0_failed:
            try:
                high_risk_questions = None
                if self._high_risk and package_catalog is not None:
                    listed = set(self._high_risk)
                    high_risk_questions = tuple(sorted({
                        row["question_id"]
                        for row in package_catalog.criteria(package_version)
                        if row["criterion_id"] in listed and row["question_id"]}))
                document_id = self.ingest_document(
                    blobs, kind="submission", order_hint=order_hint,
                    package_version=package_version, filenames=filenames,
                    submission_id=submission_id, report_detail=raster_detail,
                    high_risk_question_ids=high_risk_questions,
                )
                gates["v1"] = "pass"
            except IngestTranscriptionError as error:
                # The strike limit exhausted (#220, `NFR-INGEST-02`): the page
                # has NO transcript, so THIS submission quarantines and the
                # cohort's remaining submissions continue — the exception never
                # escapes raw and the row is never a NULL-gates zombie. The
                # columns say what is true: the file passed V0, the page stage
                # failed, the ladder never reached V2+; `unreadable` is the
                # operator's diagnosis — the page could not be read.
                quarantine("v1", "unreadable", {
                    "gate": "v1", "finding": str(error),
                    "attempts": error.attempts})
            except (IngestGapError, IngestDuplicateError) as error:
                # V1 page completeness (FR-INGEST-22): #37's gap and duplicate
                # findings become gate outcomes here — quarantined, naming the
                # specific pages.
                quarantine("v1", "incomplete", {"gate": "v1",
                                                "finding": str(error)})
            except IngestError as error:
                quarantine("v0", "unreadable", {"gate": "v0",
                                                "finding": str(error)})

        # The transcript and its regions, read once for V2, V3 and V4 alike.
        regions: Sequence[Any] = ()
        stored_markdown = ""
        if document_id is not None:
            regions = self._handle.query(INGEST_STATEMENTS["select_regions"],
                                         document_id=document_id)
            stored_markdown = self._handle.query(
                INGEST_STATEMENTS["select_document"],
                document_id=document_id)[0]["markdown"]

        if document_id is not None and not quarantined:
            # V2 structural completeness (FR-INGEST-23), reading the question
            # structure FROM the package (FR-INGEST-18): a region whose shape
            # contradicts the package is a V2 failure naming the question.
            if package_catalog is not None:
                declared = {
                    row["question_id"]: row["kind"]
                    for row in package_catalog.criteria(package_version)
                }
                for region in regions:
                    question_id = region["element_kind"]
                    if question_id in ("text", "graphic"):
                        # The parser's sentinel kinds for text OUTSIDE the region
                        # protocol — page headers, instructions, student labels. An
                        # untagged region carries no question identity, so it can
                        # neither contradict nor satisfy the declared inventory
                        # (#41: without this, every headered transcript — the
                        # prompt's own 'Assessment:'/'Student:' carry-over — was a
                        # V2 failure).
                        continue
                    if region["region_kind"] == "selection_mark":
                        if declared.get(question_id) == "open":
                            v2_failures.append({
                                "gate": "v2", "question_id": question_id,
                                "finding": "selection where the package declares "
                                           "open"})
                        elif (declared.get(question_id) == "mcq"
                                and region["selection_state"] != "resolved"):
                            # FR-INGEST-23: an mcq region must carry a RESOLVABLE
                            # selection — an ambiguous or multiple mark under a
                            # declared mcq routes to the operator (the ladder's
                            # disclosed F2: this used to pass V2 and V4 then
                            # matched the submission).
                            v2_failures.append({
                                "gate": "v2", "question_id": question_id,
                                "finding": "an unresolved selection where the "
                                           "package declares mcq"})
                    elif declared.get(question_id) == "mcq":
                        v2_failures.append({
                            "gate": "v2", "question_id": question_id,
                            "finding": "prose where the package declares mcq"})
                    elif question_id not in declared:
                        v2_failures.append({
                            "gate": "v2", "question_id": question_id,
                            "finding": "the package declares no such question"})
                # FR-INGEST-23's declared-set half: the ladder reads the DECLARED
                # set, not only the regions that exist. A question the package
                # declares with no region in the transcript is a V2 failure naming
                # the question, recorded as its own `absent` row — never a blank
                # answer (FR-INGEST-16). This is `_absent_regions`' call site:
                # until #219 it had none (the ladder's disclosed F1) and a missing
                # question passed V2 silently. The check needs a transcript that
                # ENGAGED the question protocol: one that tagged no question at
                # all has no tagged inventory to diff — every question would read
                # "missing" against output that named nothing — and routes through
                # V3/V4 instead (V4's structural signal reports the empty
                # inventory and halts scoring; TC-INGEST-44's untagged row pins
                # that route).
                tagged = {region["element_kind"] for region in regions
                          if region["element_kind"] not in ("text", "graphic")}
                if tagged:
                    absent = self._absent_regions(
                        package_version, document_id,
                        [(region["element_kind"], region["content_state"])
                         for region in regions], package_catalog)
                    declared_gap = bool(absent)
                    for question_id, _ in absent:
                        v2_failures.append({
                            "gate": "v2", "question_id": question_id,
                            "finding": "no region for a question the "
                                       "assessment declares"})
                if v2_failures:
                    quarantine("v2", "incomplete", {
                        "gate": "v2", "failures": v2_failures})
                else:
                    gates["v2"] = "pass"
            # V3 identity (FR-INGEST-24): the transcript's declared identity,
            # matched against the roster — ambiguous or unmatched routes to triage
            # and is NEVER guessed.
            named = self._extract_identity(stored_markdown)
            roster = {row["student_ref"] for row in self._handle.query(
                INGEST_STATEMENTS["select_roster"], cohort_id=cohort_id)}
            if named is None:
                gates["v3"] = "unmatched"
                ingest_status = "incomplete"
                quarantined = True
                identity_matched = False
                findings.append({"gate": "v3", "finding":
                                 "no student identity found in the submission"})
            elif named not in roster:
                candidates = sorted(ref for ref in roster
                                    if named.lower() in ref.lower())
                gates["v3"] = "ambiguous" if len(candidates) > 1 else "unmatched"
                ingest_status = "incomplete"
                quarantined = True
                identity_matched = False
                findings.append({"gate": "v3", "finding":
                                 f"identity {named!r} does not match the roster "
                                 f"(candidates: {candidates})"})
            else:
                gates["v3"] = "pass"
                student_ref = named
                identity_matched = True

        # V4 assessment match (#41, FR-INGEST-25..28): runs whenever a transcript
        # exists — INCLUDING after a V2/V3 quarantine, because the plan's decision
        # table (test plan §5.5) expects the wrong-paper case to reach V4 and be
        # named `mismatch`, not misread as `incomplete`. Every signal that fired is
        # recorded (`FR-INGEST-27`); both non-match outcomes halt scoring; a
        # mismatch records a proposal and never reassigns (`FR-INGEST-26`).
        proposal: dict | None = None
        v4_signals: dict = {}
        if document_id is None:
            v4_signals["skipped"] = ("no transcript — V0/V1 quarantined the "
                                     "submission before V4")
        elif package_catalog is None:
            v4_signals["skipped"] = ("no package bound to this ingestion — V4 has "
                                     "nothing to match against")
        else:
            outcome, v4_signals = self._v4_evaluate(
                stored_markdown, regions, package_version, package_catalog,
                identity_matched)
            gates["v4"] = outcome
            if outcome in ("uncertain", "mismatch"):
                # Both outcomes halt scoring (FR-INGEST-25): quarantined, with the
                # status naming the specific diagnosis — the ASSESSMENT did not
                # match, whatever else the ladder found. V4's verdict takes the
                # status because it is the more specific one; the earlier gates'
                # findings stay recorded above and in their own columns — EXCEPT
                # where V2 named a declared-set gap (#219): the structural dissent
                # behind an `uncertain` is then the very gap V2 already named, so
                # the derivative verdict does not rename the V2 diagnosis
                # (`incomplete` stands). A `mismatch` is independent dissent
                # (identifier AND semantic both disagreed) and still renames —
                # the plan's decision table pins it (TC-INGEST-25 cell (b), which
                # is itself a missing-question shape).
                quarantined = True
                if outcome == "mismatch" or not declared_gap:
                    ingest_status = "unmatched_assessment"
                findings.append({
                    "gate": "v4", "finding":
                        f"assessment match: {outcome} — scoring halted for this "
                        "submission"})
                if outcome == "mismatch":
                    proposal = self._v4_build_proposal(
                        regions, stored_markdown)
            if proposal is not None:
                v4_signals["proposal_id"] = proposal["proposal_id"]

        # FR-INGEST-29's `low_confidence_ocr` outcome (#221): a transcription
        # whose reading confidence dipped below the floor is AVAILABLE, flagged
        # for impact routing (the state model's second arm) — never quarantined,
        # because CT-INGEST-11 admits it to scoring exactly like `ok`. It fires
        # only when every gate left the submission clean: a quarantined status
        # is the more specific diagnosis and stands. The comparison is strictly
        # below the floor (the divergence halt's declared boundary rule);
        # exactly-at is not low. The flag is per-region over the STORED rows —
        # a document-level mean would be the exact collapse FR-INGEST-15 forbids.
        if not quarantined and ingest_status == "ok":
            floor = _ocr_conf_floor()
            low_regions = [region["region_id"] for region in regions
                           if region["ocr_conf"] is not None
                           and region["ocr_conf"] < floor]
            if low_regions:
                ingest_status = "low_confidence_ocr"
                findings.append({
                    "gate": "ocr",
                    "finding": f"{len(low_regions)} region(s) recorded "
                               f"ocr_conf below the {floor} confidence floor — "
                               "the submission stays available, flagged for "
                               "impact routing (low_confidence_ocr).",
                    "region_ids": low_regions,
                })
                LOGGER.info(
                    "submission %s flagged low_confidence_ocr: %d region(s) "
                    "below the floor", submission_id, len(low_regions),
                )

        with self._handle.transaction() as tx:
            tx.execute(INGEST_STATEMENTS["update_submission_gates"],
                       submission_id=submission_id,
                       v0=gates["v0"], v1=gates["v1"], v2=gates["v2"],
                       v3=gates["v3"], v4=gates["v4"],
                       v4_signals=json.dumps(v4_signals, default=str),
                       status=ingest_status,
                       quarantined=1 if quarantined else 0,
                       student_ref=student_ref)
            if proposal is not None:
                # FR-INGEST-26: the proposal row, written in the same transaction
                # as the gates it belongs to. The resolution columns are the
                # human's; the ladder never writes them.
                tx.execute(INGEST_STATEMENTS["insert_match_proposal"],
                           proposal_id=proposal["proposal_id"],
                           submission_id=submission_id,
                           v4_match=gates["v4"],
                           candidates=json.dumps(proposal["candidates"]),
                           signals=json.dumps(v4_signals, default=str),
                           proposed_at=self._now())
            # The cohort breaker (FR-INGEST-28), evaluated on the post-write state
            # inside the same transaction: at or above the configured rate AND the
            # configured minimum, it records the ONE cohort-level finding.
            breaker = self._v4_evaluate_breaker(tx, cohort_id)
        if breaker is not None:
            findings.append({"gate": "v4", "cohort": cohort_id,
                             "finding": breaker["finding"]})
        LOGGER.info(
            "ingested submission %s status=%s gates=%s findings=%d",
            submission_id, ingest_status, gates, len(findings),
        )
        detail = {"findings": findings, "v2_failures": v2_failures,
                  "neutralized": neutralized, "rasters": raster_detail.get(
                      "rasters"),
                  # #220: the per-page strike log — which pages struck, on
                  # which attempt, and whether a later attempt recovered.
                  "transcription_attempts": raster_detail.get(
                      "transcription_attempts", []),
                  # FR-INGEST-14: both descriptions and their comparison, per region.
                  "second_descriptions": raster_detail.get("second_descriptions", []),
                  "second_description_pass": raster_detail.get("second_description_pass")}
        if self._residency is not None:
            # The F11 seam (#222): a slot on a result is never bare — the
            # report carries the slot's stage detail (holder, waiter count)
            # next to the gates it gated.
            detail["residency"] = self._residency.snapshot()
        return IngestReport(
            submission_id=submission_id, document_id=document_id or "",
            gates=gates, ingest_status=ingest_status,
            detail=detail,
            v4_signals=v4_signals,
        )

    @staticmethod
    def _extract_identity(markdown: str) -> str | None:
        """The student named on the paper: a leading `Student: <name>` line that the prompt asks
        the model to copy exactly (FR-INGEST-24). None when there is none; V3 handles the absence
        and never guesses."""
        match = re.search(r"^Student:\s*(.+)$", markdown, re.MULTILINE)
        return match.group(1).strip() if match else None

    # -- V4: assessment match, recorded signals, the cohort breaker (FR-INGEST-25..28) ---------------
    #
    # ADR-7: deterministic first. The identifier and structural signals are computed
    # from stored rows; the base semantic correspondence is a deterministic lexical
    # measure; the model-assisted path fires only in the `uncertain` band and its
    # verdict is RECORDED, not applied — the plan's decision table (§5.5, TC-INGEST-25)
    # pins exact outcomes per signal cell, which only the deterministic signals can
    # decide, and the escalation's rate is a monitored metric, which only a recorded
    # verdict makes measurable.
    #
    # The decision rule (declared here because the plan demands the design fix case (e),
    # "not left to the implementation"):
    #   all three decisive signals agree "match" (the identifier may be absent) → match
    #   identifier=mismatch AND structural=mismatch AND semantic=mismatch        → mismatch
    #   otherwise — any single dissent, no unanimity against                     → uncertain
    # Case (e) of the table (no identifier, structural match, semantic match) is
    # therefore `match`. `roster_context` is computed and recorded but never decisive:
    # the student who handed in the wrong paper is still on the roster, so roster
    # agreement corroborates and disagreement is already V3's finding — the plan's
    # table gives it no column, and inventing one would change pinned cells.

    @staticmethod
    def _extract_assessment_identifier(markdown: str) -> str | None:
        """The assessment named on the paper: a leading `Assessment: <name>` line copied exactly
        (FR-INGEST-25). None when the paper names none; the signal then reads `absent`. The same
        reading is used on candidate assessment documents when a mismatch proposes alternatives."""
        match = re.search(r"^Assessment:\s*(.+)$", markdown, re.MULTILINE)
        return match.group(1).strip() if match else None
