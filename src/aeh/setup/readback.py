"""The rubric read-back step: the stored rubric read back into criteria and band sets."""

from __future__ import annotations

import json
import math
from typing import Any, Mapping, Sequence

from aeh.ingest import DocumentId
from aeh.pkg import PackageError, PackageVersionId, default_evaluation_mode
from aeh.prov import PromptPayload

from .settings import (
    _configured_readback_attempts,
    FIVE_QUESTIONS,
    LOGGER,
    _now,
    _NUMERAL_IN_DESCRIPTOR,
    SCORING_MODELS,
    SETUP_DEFAULT_BAND_COUNT,
    SETUP_EVIDENCE_TYPE_DEFAULT,
    SETUP_MAGNITUDE_PHRASES,
    SETUP_MAX_CONFIRMATIONS,
    SETUP_READBACK_TEMPLATE_V,
)
from .errors import _ReplyError, SetupError, SetupOrderError
from .records import CriterionDraft, ProposedBand, RubricReadback
from .prompts import _READBACK_INSTRUCTION
from .decomposability import _classify_answers


# --- the rubric read-back (FR-SETUP-04/-05/-09, #51) --------------------------------------------
#
# The read back turns the rubric artifact into criterion drafts with band sets. Two
# rules carry the design's teeth:
#
#   * the magnitude bar (`FR-SETUP-05`): a band descriptor matching
#     `SETUP_MAGNITUDE_PHRASES` — or containing any digit — is a schema-validation
#     failure of the reply, re-requested within the attempt budget, never stored. The
#     rejection is the point: judges see descriptors, not a points scale in disguise.
#   * the band-order fix (`FR-PKG-06`'s order half): the model ranks bands best-first
#     (ordinal 1 = best, points descending); the STORED order is points-ascending with
#     ordinals contiguous from 0, because the band a judge can retreat to must be the
#     LOW one. §3.6's Requires table assigns that fix to this module: "band ordering is
#     fixed on read-back".
#
# A criterion whose construct carries no partial credit arrives with no bands at all
# (the common real case, §3.6's open question): the module derives the default two-band
# met / not-met set anchored on the criterion's own text.


def _descriptor_offense(text: str) -> str | None:
    """What the magnitude bar finds in one descriptor, or None: a configured phrase
    (case-insensitive substring) or any digit. The message names the match — it is the
    re-request's reason and the log line the operator reads."""

    lowered = text.lower()
    for phrase in SETUP_MAGNITUDE_PHRASES:
        if phrase.lower() in lowered:
            return f"the magnitude phrase {phrase!r}"
    numeral = _NUMERAL_IN_DESCRIPTOR.search(text)
    if numeral:
        return f"a bare numeral ({numeral.group(0)!r})"
    return None


def _derived_default_bands(construct: str, max_points: float) -> tuple[ProposedBand, ...]:
    """The two-band default (`FR-SETUP-04`): met / not met, anchored on the criterion's
    own text — the met band's descriptor IS the construct (the rubric's behavioural
    sentence, not a magnitude word), the not-met band states what falls outside it.
    Derived descriptors pass the same magnitude bar as proposed ones: if the construct
    itself carries a phrase or a numeral, the reply is rejected and re-requested — the
    model is asked for a cleaner statement of the construct."""

    met = construct.strip()
    not_met = f"the response does not do what the criterion describes ({met})"
    return (
        ProposedBand(band="not met", ordinal=0, points=0.0, descriptor=not_met),
        ProposedBand(band="met", ordinal=1, points=max_points, descriptor=met),
    )


def _normalize_bands(raw_bands: Sequence[Mapping], construct: str,
                     max_points: float) -> tuple[ProposedBand, ...]:
    """Fix the band ordering on read-back (`FR-PKG-06`'s order half): sort by points
    ascending — the reply's own order breaking ties, so the model's ranking survives
    a flat band set — and re-base the ordinals to contiguous-from-0. The reply's
    descriptor content has already cleared the magnitude bar before this runs.

    The reply's bands are typed into `ProposedBand` FIRST and ordered through the
    attribute: this module orders and writes band points, it never reads a stored band
    row to map a band to a score — that mapping is `points_for_band`'s alone
    (`TC-PKG-C05`, RISK-05), and the typed shape is what keeps the two apart."""

    typed = tuple(
        ProposedBand(band=str(band["band"]), ordinal=int(band["ordinal"]),
                     points=float(band.get("points", 0.0)),
                     descriptor=str(band["descriptor"]))
        for band in raw_bands
    )
    ordered = sorted(enumerate(typed), key=lambda pair: (pair[1].points, pair[0]))
    return tuple(
        ProposedBand(band=band.band, ordinal=fixed_ordinal, points=band.points,
                     descriptor=band.descriptor)
        for fixed_ordinal, (_reply_ordinal, band) in enumerate(ordered)
    )


def _parse_readback_reply(
    text: str, confirmed_ids: Mapping[str, Mapping],
) -> tuple[CriterionDraft, ...]:
    """Parse the model's read-back reply into criterion drafts, raising `_ReplyError`
    on anything that is not a valid read-back — the failure the attempt loop
    re-requests. Validity here is the whole bar: schema fields, the band rules
    (`FR-PKG-06`'s count half), the justification rule (`FR-SETUP-04`), and the
    magnitude scan (`FR-SETUP-05`) over every proposed AND derived descriptor — the
    stored set must be clean whatever produced it."""

    stripped = text.strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start < 0 or end <= start:
        raise _ReplyError("the reply contains no JSON object.")
    try:
        parsed = json.loads(stripped[start:end + 1])
    except ValueError as error:
        raise _ReplyError(f"the reply is not valid JSON: {error}") from error
    if not isinstance(parsed, dict) or not isinstance(parsed.get("criteria"), list):
        raise _ReplyError("the reply's JSON does not carry a 'criteria' list.")
    if not parsed["criteria"]:
        raise _ReplyError(
            "the reply proposes zero criteria — a rubric read back that reads nothing "
            "is not a read back."
        )
    drafts: list[CriterionDraft] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(parsed["criteria"]):
        if not isinstance(raw, dict):
            raise _ReplyError(f"criterion #{index} is not an object.")
        criterion_id = raw.get("criterion_id")
        if not isinstance(criterion_id, str) or not criterion_id.strip():
            raise _ReplyError(
                f"criterion #{index}: criterion_id must be a non-empty string."
            )
        if criterion_id in seen_ids:
            raise _ReplyError(
                f"criterion #{index}: duplicate criterion_id {criterion_id!r}."
            )
        seen_ids.add(criterion_id)
        question_id = raw.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            raise _ReplyError(
                f"criterion {criterion_id!r}: question_id must be a non-empty string."
            )
        if question_id not in confirmed_ids:
            raise _ReplyError(
                f"criterion {criterion_id!r}: question_id {question_id!r} is not in "
                "the CONFIRMED inventory — criteria anchor to confirmed questions "
                "(FR-SETUP-02), and an invented anchor is a proposal bug."
            )
        kind = raw.get("kind")
        if kind not in ("open", "mcq"):
            raise _ReplyError(
                f"criterion {criterion_id!r}: kind {kind!r} is outside the vocabulary "
                "('open', 'mcq')."
            )
        scoring_model = raw.get("scoring_model")
        decomposition_basis = ""
        needs_confirmation = False
        # `FR-SETUP-17`: decided from the shape here and re-decided explicitly in the
        # classifier branches below, so every path out of this loop has bound it — the
        # arm that takes the reply's own `scoring_model` reaches neither branch.
        evaluation_mode = default_evaluation_mode(kind)
        if scoring_model is None:
            # #52 (`FR-SETUP-06`/`-08`): the reply carried the §5.3 ANSWERS (or none at
            # all) and no scoring model — the classification is the module's table, not
            # the reply's word. An `mcq` criterion is FR-SETUP-13's: never submitted to
            # the §5.3 test, `atomic` outright. Anything else is the table over whatever
            # answers the reply carried — an absent answer set is the unclear case, and
            # the default is `holistic`, never `atomic` (NFR-SETUP-02, RISK-27).
            if kind == "mcq":
                scoring_model = "atomic"
                # `FR-SETUP-17`: FR-SETUP-13's criteria are the deterministic ones, and
                # the mode is bound here rather than left for M-PKG's column default —
                # the service DECLARES how each criterion is evaluated (`FR-PKG-22`).
                evaluation_mode = "deterministic"
            else:
                evaluation_mode = "judged"
                raw_answers = raw.get("answers")
                raw_answers = raw_answers if isinstance(raw_answers, dict) else {}
                scoring_model, decided = _classify_answers(raw_answers)
                decomposition_basis = decided or ""
                # The same refusal the classifier applies (`_verdict_from_answers`):
                # a warning sign with every answer passing refuses the atomic grant,
                # and a borderline verdict — unclear answers OR warning signs — is
                # surfaced for the teacher and counted against the cap by the
                # service (`_request_confirmation`). A read-back reply must not be
                # a second classification surface that quietly escapes FR-SETUP-07.
                raw_warnings = raw.get("warning_signs", [])
                warning_signs = ([str(item) for item in raw_warnings
                                  if str(item).strip()]
                                 if isinstance(raw_warnings, list) else [])
                if decided is None and scoring_model == "atomic" and warning_signs:
                    scoring_model = "holistic"
                    decomposition_basis = ""
                needs_confirmation = (
                    decided is None
                    and any(str(raw_answers.get(question, "")).strip().lower()
                            not in ("yes", "no") for question in FIVE_QUESTIONS)
                ) or bool(warning_signs)
        elif scoring_model not in SCORING_MODELS:
            raise _ReplyError(
                f"criterion {criterion_id!r}: scoring_model {scoring_model!r} is "
                f"outside the vocabulary {SCORING_MODELS} (FR-SETUP-13, FR-AGG-06)."
            )
        max_points = raw.get("max_points", 0.0)
        if isinstance(max_points, bool) or not isinstance(max_points, (int, float)):
            raise _ReplyError(
                f"criterion {criterion_id!r}: max_points must be a number, got "
                f"{max_points!r}."
            )
        if max_points < 0:
            raise _ReplyError(
                f"criterion {criterion_id!r}: max_points {max_points} is negative."
            )
        if not math.isfinite(max_points):
            raise _ReplyError(
                f"criterion {criterion_id!r}: max_points {max_points} is not a finite "
                "number — NaN would fail the band write outright and an infinity would "
                "make every band unreachable."
            )
        construct = raw.get("construct")
        if not isinstance(construct, str) or not construct.strip():
            raise _ReplyError(
                f"criterion {criterion_id!r}: construct must be non-empty — the "
                "criterion's own behavioural text is what the default band set "
                "anchors on."
            )
        raw_bands = raw.get("bands", [])
        if not isinstance(raw_bands, list):
            raise _ReplyError(f"criterion {criterion_id!r}: bands must be a list.")
        band_count = raw.get("band_count", len(raw_bands) or SETUP_DEFAULT_BAND_COUNT)
        # The band set's shape (even, 2..6: FR-SETUP-04 / FR-PKG-06) is the catalog's rule and
        # is refused by the catalog's own write (CT-PKG-04, #535); a second copy here would
        # drift from it. The reply only has to say which count it asks for.
        if not isinstance(band_count, int) or isinstance(band_count, bool):
            raise _ReplyError(
                f"criterion {criterion_id!r}: band_count {band_count!r} is not a whole number."
            )
        justification = raw.get("justification", "")
        if justification is None:
            justification = ""
        if not isinstance(justification, str):
            raise _ReplyError(
                f"criterion {criterion_id!r}: justification must be a string."
            )
        if band_count > SETUP_DEFAULT_BAND_COUNT and not justification.strip():
            raise _ReplyError(
                f"criterion {criterion_id!r}: band_count {band_count} exceeds the "
                "two-band default without a justification (FR-SETUP-04) — partial "
                "credit that is genuinely part of the construct is recorded, not "
                "silent."
            )
        evidence_type = raw.get("evidence_type")
        if evidence_type is None:
            evidence_type = SETUP_EVIDENCE_TYPE_DEFAULT
        if not isinstance(evidence_type, str) or not evidence_type.strip():
            raise _ReplyError(
                f"criterion {criterion_id!r}: evidence_type, when given, must be a "
                "non-empty string (FR-SETUP-09) — a declaration of nothing satisfies "
                "no criterion."
            )
        if raw_bands:
            if len(raw_bands) != band_count:
                raise _ReplyError(
                    f"criterion {criterion_id!r}: {len(raw_bands)} band(s) proposed "
                    f"against a declared band_count of {band_count}."
                )
            for band_index, raw_band in enumerate(raw_bands):
                if not isinstance(raw_band, dict):
                    raise _ReplyError(
                        f"criterion {criterion_id!r} band #{band_index} is not an "
                        "object."
                    )
                label = raw_band.get("band")
                if not isinstance(label, str) or not label.strip():
                    raise _ReplyError(
                        f"criterion {criterion_id!r} band #{band_index}: band label "
                        "must be non-empty."
                    )
                points = raw_band.get("points", 0.0)
                if isinstance(points, bool) or not isinstance(points, (int, float)):
                    raise _ReplyError(
                        f"criterion {criterion_id!r} band {label!r}: points must be "
                        f"a number, got {points!r}."
                    )
                if points < 0:
                    raise _ReplyError(
                        f"criterion {criterion_id!r} band {label!r}: points "
                        f"{points} is negative."
                    )
                if not math.isfinite(points):
                    raise _ReplyError(
                        f"criterion {criterion_id!r} band {label!r}: points {points} "
                        "is not a finite number — the JSON decoder accepts NaN and "
                        "Infinity, and neither is a points value a band can carry."
                    )
                descriptor = raw_band.get("descriptor")
                if not isinstance(descriptor, str) or not descriptor.strip():
                    raise _ReplyError(
                        f"criterion {criterion_id!r} band {label!r}: descriptor must "
                        "state what a response in that band DOES — an empty "
                        "descriptor states nothing."
                    )
                offense = _descriptor_offense(descriptor)
                if offense:
                    raise _ReplyError(
                        f"criterion {criterion_id!r} band {label!r}: its descriptor "
                        f"carries {offense} (FR-SETUP-05) — judges see what a "
                        "response does, never a quality word or a points scale."
                    )
            bands = _normalize_bands(raw_bands, construct, float(max_points))
            bands_source = "proposed"
        else:
            if band_count != SETUP_DEFAULT_BAND_COUNT:
                raise _ReplyError(
                    f"criterion {criterion_id!r}: no bands proposed but band_count "
                    f"{band_count} is not the default — propose the bands or omit "
                    "the count."
                )
            bands = _derived_default_bands(construct, float(max_points))
            bands_source = "derived_default"
            for band in bands:
                offense = _descriptor_offense(band.descriptor)
                if offense:
                    raise _ReplyError(
                        f"criterion {criterion_id!r}: its construct carries {offense}, "
                        "which would leak into the derived band descriptors "
                        "(FR-SETUP-05) — restate the construct behaviourally."
                    )
        drafts.append(CriterionDraft(
            criterion_id=criterion_id, question_id=question_id, kind=kind,
            evaluation_mode=evaluation_mode,
            scoring_model=scoring_model, max_points=float(max_points),
            construct=construct, band_count=band_count, bands=bands,
            justification=justification.strip(), evidence_type=evidence_type.strip(),
            bands_source=bands_source, decomposition_basis=decomposition_basis,
            needs_confirmation=needs_confirmation,
        ))
    return tuple(drafts)


def _criterion_to_dict(draft: CriterionDraft) -> dict:
    """The payload shape for one read-back criterion — plain mappings, because the
    data layer does not import this module's types. `bands_source` is
    `proposed` or `derived_default` (`FR-SETUP-14`: a default taken is recorded)."""
    return {
        "criterion_id": draft.criterion_id,
        "question_id": draft.question_id,
        "kind": draft.kind,
        "scoring_model": draft.scoring_model,
        "max_points": draft.max_points,
        "construct": draft.construct,
        "band_count": draft.band_count,
        "evidence_type": draft.evidence_type,
        "evaluation_mode": draft.evaluation_mode,
        "justification": draft.justification,
        "bands_source": draft.bands_source,
        "decomposition_basis": draft.decomposition_basis,
        "bands": [
            {"band": band.band, "ordinal": band.ordinal, "points": band.points,
             "descriptor": band.descriptor}
            for band in draft.bands
        ],
    }


def _criterion_record(draft: CriterionDraft) -> dict:
    """The write shape `PackageCatalog.write_readback` validates and stores — the
    payload dict's sibling under M-PKG's names (`construct_tag`, `band_justification`)."""
    return {
        "criterion_id": draft.criterion_id,
        "question_id": draft.question_id,
        "kind": draft.kind,
        "max_points": draft.max_points,
        "scoring_model": draft.scoring_model,
        "construct_tag": draft.construct,
        "band_count": draft.band_count,
        "evidence_type": draft.evidence_type,
        "band_justification": draft.justification or None,
        "evaluation_mode": draft.evaluation_mode,
        "bands": [
            {"band": band.band, "ordinal": band.ordinal, "points": band.points,
             "descriptor": band.descriptor}
            for band in draft.bands
        ],
    }


def _stored_readback_status(row: Mapping[str, Any] | None) -> str:
    """The stored read-back row's status — a field of the PAYLOAD, not a column.

    `steps()` reads this to report done / degraded honestly (`NFR-SETUP-04`): the
    row's own columns are provenance (documents, prompt, build, attempts), and the
    status word the module wrote lives inside the payload it mirrors. A row whose
    payload cannot be parsed reads as not-done rather than crashing the console's
    enumeration — the row is provenance, and provenance is not silently replaced."""
    if not row:
        return ""
    try:
        return str(json.loads(row["payload"]).get("status") or "")
    except (KeyError, TypeError, ValueError):
        return ""


def _readback_from_row(v: PackageVersionId, row: Mapping[str, Any]) -> RubricReadback:
    """Rebuild the stored read back — the resume path's read (`CT-SETUP-03`: state is
    the database). A malformed stored payload raises `SetupError` naming the corruption
    rather than silently re-reading the rubric over it."""

    try:
        payload = json.loads(row["payload"])
        status = payload["status"]
        entries = payload.get("criteria", [])
        reason = payload.get("reason", "")
    except (ValueError, KeyError, TypeError) as error:
        raise SetupError(
            f"the stored read-back for version {v!r} is malformed ({error}) — the "
            "payload is provenance and is not silently replaced; delete the version "
            "and run setup again."
        ) from error
    criteria = tuple(
        CriterionDraft(
            criterion_id=str(entry["criterion_id"]),
            question_id=str(entry["question_id"]),
            kind=str(entry["kind"]),
            scoring_model=str(entry["scoring_model"]),
            max_points=float(entry.get("max_points", 0.0)),
            construct=str(entry.get("construct", "")),
            band_count=int(entry["band_count"]),
            bands=tuple(
                ProposedBand(band=str(band["band"]), ordinal=int(band["ordinal"]),
                             points=float(band.get("points", 0.0)),
                             descriptor=str(band["descriptor"]))
                for band in entry.get("bands", ())
            ),
            justification=str(entry.get("justification", "")),
            evidence_type=str(entry.get("evidence_type",
                                        SETUP_EVIDENCE_TYPE_DEFAULT)),
            # A payload written before `evaluation_mode` existed carries none; the shape
            # default reproduces exactly what that payload meant when it was written.
            evaluation_mode=str(entry.get("evaluation_mode")
                                or default_evaluation_mode(str(entry["kind"]))),
            bands_source=str(entry.get("bands_source", "proposed")),
            decomposition_basis=str(entry.get("decomposition_basis", "")),
        )
        for entry in entries
    )
    return RubricReadback(
        rubric_doc_id=str(row["rubric_doc_id"]),
        assessment_doc_id=str(row["assessment_doc_id"]),
        package_version_id=v,
        template_version=str(row["template_version"]),
        model_ref=str(row["model_ref"]),
        attempts=int(row["attempts"]),
        criteria=criteria,
        status=status,
        reason=str(reason),
    )


class ReadbackStepMixin:
    """Reads the stored rubric back into criteria and band sets."""

    def read_back_rubric(self, rubric_doc: DocumentId,
                         assessment_doc: DocumentId) -> RubricReadback:
        """Read the stored rubric back into criteria and band sets (`§3.6`'s Interface,
        `FR-SETUP-04`/`-05`/`-09`).

        Gate 1 (the confirmed inventory) must be met first — criteria anchor to
        confirmed questions (`SetupOrderError` otherwise). The rubric and assessment are
        read through `M-INGEST` (`CT-SETUP-11`); each attempt is one model call through
        the provider seam within the `HARNESS_SETUP_READBACK_ATTEMPTS` budget. A reply
        that fails to parse, anchors to an unconfirmed question, or carries a band
        descriptor matching `SETUP_MAGNITUDE_PHRASES` (or a bare numeral) is
        re-requested (`FR-SETUP-05`); after the budget the read back degrades to
        `needs_manual_entry` — recorded, so the teacher enters the criteria through
        `M-PKG` and the console says what happened rather than retrying forever.

        The stored row comes back unchanged (the resume path — no new model call,
        `CT-SETUP-03`), and a read back is ONCE per version (`CT-SETUP-16`): the row is
        provenance, written all-or-nothing through `M-PKG` (`CT-PKG-11`)."""
        v = self._require_draft_version()
        stored = self._catalog.readback(v)
        if stored is not None:
            readback = _readback_from_row(v, stored)
            LOGGER.info("resuming with the stored rubric read-back for version %s "
                        "(status %s, %d attempt(s))", v, readback.status,
                        readback.attempts)
            return readback
        proposal = self._catalog.proposal(v)
        if proposal is None or not proposal["confirmed_at"]:
            raise SetupOrderError(
                f"the inventory for version {v!r} is not confirmed yet — the rubric "
                "read-back anchors criteria to confirmed questions, so gate 1 "
                "(§4.2.1) must be met before it runs (FR-SETUP-02)."
            )
        criteria_rows = self._catalog.criteria(v)
        staged_ids = self._staged_criterion_ids(v)
        foreign = [
            row["criterion_id"] for row in criteria_rows
            if row["criterion_id"] not in staged_ids
            or row.get("kind") != "mcq" or row.get("scoring_model") != "atomic"
        ]
        if foreign:
            # Reachable through M-PKG's public add_criterion — the same manual path
            # the degraded note directs a teacher to. The read back writes criteria
            # onto a clean draft (CT-PKG-11: a rejected write is a no-op, so the next
            # attempt re-proposes onto that clean draft); merging its output with
            # hand-authored criteria is a decision a model call cannot make, so
            # refuse BEFORE spending the attempt budget rather than letting M-PKG's
            # refusal escape mid-write. The staged criteria are NOT foreign — #53
            # created them from this very inventory, in exactly the produced shape,
            # and the read back anchors around them.
            raise SetupOrderError(
                f"version {v!r} already carries hand-authored criterion rows "
                f"({', '.join(foreign[:4])}"
                f"{', …' if len(foreign) > 4 else ''}) — the rubric read-back writes "
                "criteria onto a clean draft and would collide with them. A version "
                "is either hand-authored or read back, not both; a fresh read-back is "
                "a new version (FR-PKG-02)."
            )
        rubric_markdown = self._ingestor.read_document(rubric_doc)
        assessment_markdown = self._ingestor.read_document(assessment_doc)
        confirmed_ids = frozenset(
            row["question_id"] for row in self._catalog.questions(v)
        )
        payload = PromptPayload(fields=(
            ("instruction", _READBACK_INSTRUCTION),
            ("rubric_transcript", rubric_markdown),
            ("assessment_transcript", assessment_markdown),
        ))
        budget = _configured_readback_attempts()
        last_error = ""
        for attempt in range(1, budget + 1):
            try:
                completion = self._provider.complete(payload, self._model_ref,
                                                     self._params)
                criteria = _parse_readback_reply(completion.text, confirmed_ids)
            except _ReplyError as error:
                last_error = f"attempt {attempt}: {error}"
                LOGGER.warning("rubric read-back reply failed to parse (%d/%d): %s",
                               attempt, budget, error)
                continue
            except Exception as error:  # contained: the transport's failure is a
                # failed attempt, and the degraded path — not a crash — is the
                # honest end of a budget spent (CT-SETUP-12's pattern).
                last_error = f"attempt {attempt}: {type(error).__name__}: {error}"
                LOGGER.warning("rubric read-back attempt %d/%d failed: %s",
                               attempt, budget, error)
                continue
            body = {
                "status": "proposed",
                "criteria": [_criterion_to_dict(criterion) for criterion in criteria],
            }
            # The catalog's own write first (#535): it enforces the band set's shape
            # (CT-PKG-04), atomically. A refusal there is a failed attempt, exactly like a
            # malformed reply, so the budget retries and then degrades; and nothing else is
            # written for a reply the catalog refused (no classification row, no
            # confirmation charged).
            try:
                self._catalog.write_readback(
                    v, rubric_doc_id=rubric_doc, assessment_doc_id=assessment_doc,
                    criteria=[_criterion_record(criterion) for criterion in criteria],
                    payload=json.dumps(body, sort_keys=True),
                    template_version=SETUP_READBACK_TEMPLATE_V,
                    model_ref=completion.resolved_build, attempts=attempt,
                    created_at=_now(),
                )
            except PackageError as error:
                last_error = f"attempt {attempt}: the catalog refused the read back: {error}"
                LOGGER.warning("rubric read-back attempt %d/%d refused by the catalog: %s",
                               attempt, budget, error)
                continue
            # The read back is a classification surface too (#52): every criterion
            # whose scoring model the §5.3 table (or the reply's declared model)
            # produced gets its `source='default'` row NOW, so the R62 audit table
            # is complete before the teacher speaks, and every borderline verdict —
            # an unclear answer or a warning sign — counts against the confirmation
            # cap through the SAME counter the classifier uses (`_request_confirmation`
            # is the cap's one accounting point).
            recorder = getattr(self._catalog, "record_classification", None)
            borderline: list[str] = []
            for criterion in criteria:
                if recorder is not None:
                    recorder(
                        v, criterion_id=criterion.criterion_id,
                        classification=criterion.scoring_model,
                        decomposition_basis=criterion.decomposition_basis or None,
                        source="default", recorded_at=_now(),
                    )
                if criterion.needs_confirmation and self._request_confirmation(v):
                    borderline.append(criterion.criterion_id)
            if borderline:
                LOGGER.warning(
                    "read back produced %d borderline classification(s) for version "
                    "%s (%s) — surfaced for the teacher within the %d-confirmation "
                    "cap (FR-SETUP-07, NFR-SETUP-01)", len(borderline), v,
                    ", ".join(borderline), SETUP_MAX_CONFIRMATIONS,
                )
            LOGGER.info(
                "read the rubric back for version %s from documents %s/%s: %d "
                "criterion(s) in %d attempt(s), prompt %s",
                v, rubric_doc, assessment_doc, len(criteria), attempt,
                SETUP_READBACK_TEMPLATE_V,
            )
            return RubricReadback(
                rubric_doc_id=rubric_doc, assessment_doc_id=assessment_doc,
                package_version_id=v, template_version=SETUP_READBACK_TEMPLATE_V,
                model_ref=completion.resolved_build, attempts=attempt,
                criteria=criteria, status="proposed",
            )

        body = {
            "status": "needs_manual_entry",
            "criteria": [],
            "reason": last_error,
        }
        self._catalog.write_readback(
            v, rubric_doc_id=rubric_doc, assessment_doc_id=assessment_doc,
            criteria=[], payload=json.dumps(body, sort_keys=True),
            template_version=SETUP_READBACK_TEMPLATE_V,
            model_ref=self._model_ref.build_id, attempts=budget,
            created_at=_now(),
        )
        LOGGER.warning(
            "rubric read-back for version %s degraded to needs_manual_entry after "
            "%d attempt(s): %s — the teacher enters the criteria through M-PKG "
            "(CT-SETUP-12's pattern)", v, budget, last_error,
        )
        return RubricReadback(
            rubric_doc_id=rubric_doc, assessment_doc_id=assessment_doc,
            package_version_id=v, template_version=SETUP_READBACK_TEMPLATE_V,
            model_ref=self._model_ref.build_id, attempts=budget, criteria=(),
            status="needs_manual_entry", reason=last_error,
        )
