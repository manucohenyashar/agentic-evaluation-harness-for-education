"""Parsing a judge's reply and verifying that every cited span is really in the document."""

from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass
from typing import Any

from aeh.integ import answer_regions, clear_of_region_markup, relocate_span, verify_span
from aeh.prov import MalformedResponseError, PromptPayload, json_from_reply
from aeh.setup import SETUP_MAGNITUDE_PHRASES

from .errors import ProseAssessmentError
from .request import ScoringRequest, _sequence_of
from .prompt import CITED_SPAN_KEYS, REPLY_FIELDS
from .assembly import _canonical_document_bytes, _pseudonymize


# --- the reply's pinned field order (FR-JUDGE-09) ------------------------------------------------


@dataclass(frozen=True)
class _Verdict:
    """One parsed judge reply: the fields the result and the verdict row carry, after the reply's
    field order has been checked."""

    cited_spans: tuple
    evidence_assessment: str
    evidence_sufficient: bool
    band: str
    band_ordinal: int
    self_confidence: float


#: `FR-JUDGE-10`'s magnitude vocabulary, as configured: M-SETUP's own bar
#: (`SETUP_MAGNITUDE_PHRASES`, the `FR-SETUP-05` constant — the system keeps magnitude
#: language away from the model at every stage, and the reply's assessment is the one
#: place left it could come back). Matching is case-insensitive SUBSTRING, the
#: configured list's own documented semantics (a descriptor "matching any of these
#: (case-insensitive substring) is rejected" — the setup-time twin, mirrored, not
#: re-spelled). Deliberately NOT #79's numeral scan: that prohibition classifies
#: prompt surfaces (rubric vs content strictness) and has no reply-side counterpart —
#: the assessment is one free-prose field — while a numeral in a reply is ordinarily
#: DATA (a quoted offset, the student's "12 kg" quoted back), so this gate keys on the
#: magnitude PHRASES alone and leaves numerals to the span-reference test: prose that
#: names a span or a band condition is an inventory whatever digits it carries.
_MAGNITUDE_PHRASES: tuple[str, ...] = SETUP_MAGNITUDE_PHRASES


#: What counts as a span reference (`FR-JUDGE-10`'s "an inventory referencing spans or
#: band conditions"): the assessment names span-evidence vocabulary, or quotes the text
#: of one of the reply's cited spans, or quotes a declared band's descriptor (the band
#: condition). Disclosed boundary: the bar is deliberately "names the evidence channel",
#: not "identifies the byte range" — WHICH span a citation resolves to is M-INTEG's
#: verification (`spans_verified`), never the parser's; a reply that names no evidence
#: channel and instead grades ("excellent work throughout") is the prose-only case this
#: gate exists for. The shipped reply fixture's "the cited spans support the band" is an
#: inventory under this reading (it names the spans channel) — which is the point: the
#: gate fires on magnitude-only prose, not on terse citations.
_ASSESSMENT_SPAN_MARKS = re.compile(
    r"\bspans?\b|\boffsets?\b|\bcitations?\b|\bcited\b|\bexcerpt\b|\bpassage\b"
    r"|\bquot(?:e|ed|ing)\b",
    re.IGNORECASE,
)


def _references_evidence(
    assessment: str, cited: tuple, request: ScoringRequest
) -> bool:
    """Whether the assessment refers to the evidence: it names spans, quotes a cited span's text,
    or quotes a declared band's descriptor (FR-JUDGE-10)."""
    if _ASSESSMENT_SPAN_MARKS.search(assessment):
        return True
    for span in cited:
        text = span.get("text") if isinstance(span, dict) else None
        if isinstance(text, str) and text and text in assessment:
            return True
    for view in request.criterion.bands:
        if view.descriptor and view.descriptor in assessment:
            return True
    return False


def _prose_only(assessment: str, cited: tuple, request: ScoringRequest) -> bool:
    """Whether the assessment is free evaluative prose (FR-JUDGE-10): it uses a configured
    magnitude phrase and refers to no span or band condition. Both must hold. Prose that names
    evidence is fine even if it also says "good", and vague text with no magnitude word is not
    refused."""
    lowered = assessment.lower()
    return (
        not _references_evidence(assessment, cited, request)
        and any(phrase in lowered for phrase in _MAGNITUDE_PHRASES)
    )


def _cited_span_of(raw: Any, *, where: str) -> dict:
    """Check one reply citation against the declared shape (`CITED_SPAN_FIELDS`, FR-JUDGE-42) and
    return it unchanged: a mapping whose keys are within `CITED_SPAN_KEYS`, with integer `start`
    and `end` and, when present, string `text`. `text` may be absent: offsets copied from an
    offered extracted span take that span's words at the citation gate (FR-JUDGE-41). A
    verdict-like key is refused, so no verdict can travel through the citation channel."""
    if not isinstance(raw, dict):
        raise TypeError(f"{where} must be a mapping of span fields, got {type(raw).__name__}")
    unknown = sorted(set(raw) - CITED_SPAN_KEYS)
    if unknown:
        raise ValueError(
            f"{where} carries key(s) {unknown} outside the declared citation shape "
            f"{sorted(CITED_SPAN_KEYS)}"
        )
    for key in ("start", "end"):
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{where} {key} must be an integer byte offset, got {value!r}")
    if "text" in raw and not isinstance(raw["text"], str):
        raise ValueError(f"{where} text must be a string, got {type(raw['text']).__name__}")
    return raw


def _verdict_of(text: str, request: ScoringRequest) -> _Verdict:
    """Parse one judge reply and check it against the pinned response contract.

    The five fields must arrive in `REPLY_FIELDS`' exact order — a re-ordered reply is
    not a format variation, it is a different contract (`FR-JUDGE-09`, `CT-JUDGE-05`) —
    the band must be in the criterion's declared set (`CT-JUDGE-04`), and the
    `evidence_assessment` must not be magnitude-only prose with no evidence reference
    (`FR-JUDGE-10`). Every refusal is a `MalformedResponseError` — the `FUZZ-04` oracle's
    named exception, a `ProviderError` the dispatch loop strikes within the budget —
    and a prose-only assessment is the `ProseAssessmentError` subtype, the re-request
    trigger. A contract violation is refused, never repaired and never answered with a
    fallback band (`CT-JUDGE-11`, `NFR-JUDGE-05`).
    """
    try:
        # A fenced or prefaced JSON reply reads as its JSON, key order kept (TC-REG-16).
        reply = json_from_reply(text)
    except json.JSONDecodeError as error:
        raise MalformedResponseError(
            f"judge reply is not valid JSON: {error}"
        ) from error
    if not isinstance(reply, dict):
        raise MalformedResponseError(
            f"judge reply is not a JSON object: {type(reply).__name__}"
        )
    if list(reply.keys()) != list(REPLY_FIELDS):
        raise MalformedResponseError(
            f"judge reply fields arrived {list(reply.keys())}, not the pinned order "
            f"{list(REPLY_FIELDS)} — reordering is not a format variation (FR-JUDGE-09)"
        )
    try:
        cited = tuple(
            _cited_span_of(span, where=f"reply cited_spans[{index}]")
            for index, span in enumerate(
                _sequence_of(reply["cited_spans"], "cited_spans")
            )
        )
    except (TypeError, ValueError) as error:
        # A malformed span inventory is a malformed response like any other: the
        # `FUZZ-04` oracle admits no other exception out of `_verdict_of`, and the
        # dispatch loop can only strike refusals it is shown (`NFR-JUDGE-05`).
        raise MalformedResponseError(
            f"judge reply cited_spans is not a valid span inventory: {error}"
        ) from error
    assessment = reply["evidence_assessment"]
    if not isinstance(assessment, str):
        raise MalformedResponseError(
            f"judge reply evidence_assessment must be a string, got "
            f"{type(assessment).__name__}"
        )
    if _prose_only(assessment, cited, request):
        raise ProseAssessmentError(
            f"judge reply evidence_assessment is free evaluative prose — it matches the "
            f"configured magnitude phrases and references no span and no band condition "
            f"(FR-JUDGE-10); the assessment must be an inventory citing spans or band "
            f"conditions"
        )
    sufficient = reply["evidence_sufficient"]
    if not isinstance(sufficient, bool):
        raise MalformedResponseError(
            f"judge reply evidence_sufficient must be a boolean, got "
            f"{type(sufficient).__name__}"
        )
    band = reply["band"]
    if not isinstance(band, str) or not band:
        raise MalformedResponseError(
            f"judge reply band must be a non-empty string, got {band!r}"
        )
    confidence = reply["self_confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise MalformedResponseError(
            f"judge reply self_confidence must be a number, got "
            f"{type(confidence).__name__}"
        )
    declared = {view.band: view.ordinal for view in request.criterion.bands}
    if band not in declared:
        raise MalformedResponseError(
            f"judge reply band {band!r} is outside the criterion's declared set "
            f"{sorted(declared)} — a contract violation is refused, never answered "
            f"with a fallback (CT-JUDGE-11, NFR-JUDGE-05)"
        )
    return _Verdict(
        cited_spans=cited,
        evidence_assessment=assessment,
        evidence_sufficient=sufficient,
        band=band,
        band_ordinal=declared[band],
        self_confidence=float(confidence),
    )


# --- the citation-grounding gate (FR-JUDGE-17's third defence; FR-INTEG-01 composed) --------------


def _verifies_as_pseudonymized(raw: bytes, span: Any, name: Any, ref: Any) -> bool:
    """Whether a cited span's text equals the document's bytes at its offsets with the student's
    roster name replaced by their pseudonym (#593). Assembly rewrites span text but keeps offsets,
    so judges cite the pseudonymized text at the stored offsets.

    Exact: the stored slice at those offsets, with THIS unit's name replaced by the ref, must
    equal the cited text byte for byte. With no name known (a request this worker did not
    assemble) nothing is accepted here, and the citation is `verify_span`'s alone."""
    if not (isinstance(name, str) and name and isinstance(ref, str) and ref):
        return False
    if isinstance(span, dict):
        start, end, text = span.get("start"), span.get("end"), span.get("text")
    else:
        start, end, text = (getattr(span, k, None) for k in ("start", "end", "text"))
    if not (isinstance(start, int) and isinstance(end, int) and isinstance(text, str)):
        return False
    if not 0 <= start <= end <= len(raw):
        return False
    try:
        stored = raw[start:end].decode("utf-8")
    except UnicodeDecodeError:
        return False
    return name in stored and _pseudonymize(stored, name, ref) == text


def _span_field(span: Any, key: str) -> Any:
    """One field of a span given as a mapping or as an object; None when it has none."""
    return span.get(key) if isinstance(span, dict) else getattr(span, key, None)


def _with_fields(span: Any, **fields: Any) -> Any:
    """A copy of the span with the given fields replaced, in the span's own form. Every other key
    (`region_kind` among them) is kept as it was."""
    if isinstance(span, dict):
        return {**span, **fields}
    if dataclasses.is_dataclass(span) and not isinstance(span, type):
        return dataclasses.replace(span, **fields)
    return {"start": _span_field(span, "start"), "end": _span_field(span, "end"),
            "text": _span_field(span, "text"), **fields}


def _offered_spans(request: Any) -> tuple:
    """Every extracted span this unit's request offered the judge: its own evidence and its
    dependency parents' (FR-JUDGE-41's "offered in that unit's request")."""
    offered = list(getattr(request, "evidence", ()) or ())
    for entry in getattr(request, "dependency_evidence", ()) or ():
        offered.extend(getattr(entry, "spans", ()) or ())
    return tuple(offered)


def _with_offered_text(span: Any, request: Any) -> Any:
    """FR-JUDGE-41: a citation with no `text` whose `(start, end)` equals an offered extracted
    span's offsets takes that span's text (as offered, so pseudonymized when assembly rewrote
    it). A text-less citation matching no offered span is returned as it is, and fails
    verification. A citation that carries text is returned as it is."""
    if isinstance(_span_field(span, "text"), str):
        return span
    start, end = _span_field(span, "start"), _span_field(span, "end")
    for offered in _offered_spans(request):
        text = _span_field(offered, "text")
        if (_span_field(offered, "start") == start and _span_field(offered, "end") == end
                and isinstance(text, str)):
            return _with_fields(span, text=text)
    return span


def _relocated(raw: bytes, span: Any, region: Any, name: Any, ref: Any) -> Any:
    """The citation re-anchored to the unique occurrence of its quoted words in the unit's region
    (FR-JUDGE-40 composing `relocate_span`, FR-INTEG-13), or None.

    The quote is tried as the document's own bytes first. A quote of pseudonymized evidence
    carries the ref where the document holds the roster name (#593), so with this unit's name
    known it is tried again with the name restored, and accepted only if the found bytes,
    pseudonymized, are exactly the quote."""
    found = relocate_span(raw, span, region)
    if found is not None:
        return _with_fields(span, start=found.start, end=found.end)
    text = _span_field(span, "text")
    if not (isinstance(name, str) and name and isinstance(ref, str) and ref
            and isinstance(text, str) and ref in text):
        return None
    found = relocate_span(raw, {"text": text.replace(ref, name)}, region)
    if found is None or _pseudonymize(found.text, name, ref) != text:
        return None
    return _with_fields(span, start=found.start, end=found.end)


#: `question_id` default for a caller that names no unit question: relocation searches the whole
#: document (FR-INTEG-13's `region=None`). The worker always names it.
_NO_QUESTION_GIVEN = None


def _refuse_unverified_citations(
    cited: tuple, request: ScoringRequest, store: Any, roster_name: Any = None, *,
    question_id: "str | None" = _NO_QUESTION_GIVEN,
) -> "tuple[tuple, bool]":
    """Accept every cited span against the canonical document, or refuse the reply (FR-JUDGE-17,
    FR-JUDGE-40). Returns the spans to store and whether any was relocated (`reanchored`).

    Per span, in order:

    1. A span with no `text` whose offsets equal an offered extracted span's takes that
       span's text (FR-JUDGE-41).
    2. It is accepted as cited when its text is the document's own bytes at its offsets
       (M-INTEG's `verify_span`, the one implementation of that check, FR-INTEG-01) or the
       pseudonymized form of them (#593), and it includes no region-marker byte
       (`clear_of_region_markup`, FR-INTEG-14).
    3. Otherwise it is re-anchored to the unique occurrence of its quoted words within the
       unit's answer region (`relocate_span`, FR-INTEG-13, ADR-54/63) and stored at those
       offsets: the offsets never win over the words.
    4. Otherwise the reply is refused, exactly as before this change.

    The region: with `question_id` naming the unit's question, the answer text of the
    document's regions tagged with it (`answer_regions`; a quote found only in another
    question's answer is not evidence for this criterion, D7). An empty `question_id` (a
    criterion that grades the submission directly) or none given searches the whole document.

    A reply that cites NOTHING passes vacuously: an uncited verdict is `FR-JUDGE-12`'s marked
    downgrade, not a verification failure. An unresolvable document (no store bound, no
    document row, a missing blob) refuses every citing reply, fail-closed, because an
    unverifiable citation is indistinguishable from a forged one. Every refusal is a
    `MalformedResponseError`, the strike the dispatch loop already knows: the reply is routed
    out (refused, re-requested, quarantined at budget exhaustion), never persisted.
    """
    if not cited:
        return (), False
    raw = _canonical_document_bytes(store, request.submission.submission_id)
    if raw is None:
        raise MalformedResponseError(
            f"judge reply cites {len(cited)} span(s) but the canonical document for "
            f"submission {request.submission.submission_id!r} cannot be resolved to "
            f"bytes — an unverifiable citation is refused, not accepted as evidence "
            f"(FR-INTEG-01 fail-closed, FR-JUDGE-17)"
        )
    ref = request.submission.student_ref
    region = answer_regions(raw, question_id) if question_id else None
    accepted: list[Any] = []
    reanchored = False
    for index, span in enumerate(cited):
        span = _with_offered_text(span, request)
        if ((verify_span(raw, span) or _verifies_as_pseudonymized(raw, span, roster_name, ref))
                and clear_of_region_markup(raw, span)):
            accepted.append(span)
            continue
        relocated = _relocated(raw, span, region, roster_name, ref)
        if relocated is not None:
            accepted.append(relocated)
            reanchored = True
            continue
        raise MalformedResponseError(
            f"judge reply cites span {index} {span!r} which fails byte-exact "
            f"verification against the canonical document, and its quoted text has no "
            f"unique occurrence in the unit's answer region to re-anchor to (FR-INTEG-01, "
            f"FR-INTEG-13, FR-JUDGE-17: a forged citation fails span verification and the "
            f"reply is refused, never accepted)"
        )
    return tuple(accepted), reanchored


# --- the assessment re-request (FR-JUDGE-10's one amendment) -------------------------------------

#: The amendment's field name. It carries STATIC ground-rules text — no per-submission
#: byte — so it joins the invariant prefix, and it is inserted BEFORE the final
#: submission field, which keeps `FR-JUDGE-07`'s submission-LAST invariant intact on the
#: amended render too. The name carries no prohibited stem, so the escalation-variant's
#: stem scan over a render stays clean.
_ASSESSMENT_AMENDMENT_FIELD = "evidence_rules_amendment"


#: The amendment's text — a static correction to the evidence ground rules, saying what
#: the contract requires of `evidence_assessment` and nothing about the particular unit.
_AMENDMENT_TEXT = (
    "Correction to the ground rules, because the previous reply was refused: the"
    " evidence_assessment field must be an inventory that references evidence — cite"
    " the spans that support the band you chose (by their text or their byte offsets)"
    " or state the band condition that holds. An assessment that only grades the work"
    " in overall terms, naming no span and no band condition, is refused under the"
    " response contract. Reply again with JSON only, all five keys in this order: "
    + ", ".join(REPLY_FIELDS) + "."
)


def _amended_payload(payload: PromptPayload) -> PromptPayload:
    """The prompt for the re-request after a prose-only assessment (FR-JUDGE-10): the same fields
    in the same order, with the assessment rules restated just before the final field (the
    submission, which stays last).

    The amended prompt is a different request with a different fixture key (CT-PROV-05), which is
    what makes the re-request legal where replaying the same prompt would re-sample a verdict
    (FR-PROV-06). The added text is fixed, so every judge re-requesting in a batch inserts the same
    bytes in the same place and the shared prefix is kept (FR-JUDGE-06)."""
    fields = list(payload.fields)
    fields.insert(len(fields) - 1, (_ASSESSMENT_AMENDMENT_FIELD, _AMENDMENT_TEXT))
    return PromptPayload(fields=tuple(fields))
