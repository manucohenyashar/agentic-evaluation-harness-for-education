"""Parsing a judge's reply and verifying that every cited span is really in the document."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from aeh.integ import verify_span
from aeh.prov import MalformedResponseError, PromptPayload
from aeh.setup import SETUP_MAGNITUDE_PHRASES

from .errors import ProseAssessmentError
from .request import ScoringRequest, _sequence_of, _span_of
from .prompt import REPLY_FIELDS
from .assembly import _canonical_document_bytes, _pseudonymize


# --- the reply's pinned field order (FR-JUDGE-09) ------------------------------------------------


@dataclass(frozen=True)
class _Verdict:
    """One parsed judge reply. Internal: the fields the result and the verdict row
    carry, after the reply's own field order has been checked."""

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
    """Whether the assessment references spans or band conditions (`FR-JUDGE-10`'s
    inventory reading): span vocabulary named, a cited span's text quoted, or a
    declared band's descriptor quoted."""
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
    """`FR-JUDGE-10`'s free-evaluative-prose test: the assessment matches the configured
    magnitude-phrase list AND references no span and no band condition. BOTH arms must
    hold — prose that names evidence is an inventory even when it also says "good", and
    an assessment with no magnitude word in it is not evaluative-only prose however
    vague it is (the gate's rejection is the magnitude vocabulary's, not a general
    prose ban)."""
    lowered = assessment.lower()
    return (
        not _references_evidence(assessment, cited, request)
        and any(phrase in lowered for phrase in _MAGNITUDE_PHRASES)
    )


def _verdict_of(text: str, request: ScoringRequest) -> _Verdict:
    """Parse and VALIDATE one judge reply against the pinned response contract.

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
        reply = json.loads(text)
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
            _span_of(span, where=f"reply cited_spans[{index}]")
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
    """A cited span whose text is the document's own bytes with the unit's roster name replaced
    by its `student_ref` (#593). Assembly rewrites a span's text and keeps its offsets, so a
    judge or the engine cites the pseudonymized text at the stored offsets.

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


def _refuse_unverified_citations(
    cited: tuple, request: ScoringRequest, store: Any, roster_name: Any = None
) -> None:
    """Verify every cited span byte-exactly against the canonical document, and refuse
    the reply when one fails (`FR-JUDGE-17` acceptance (iv): a forged citation fails
    span verification; `FR-INTEG-01`'s invariant composed at the judge boundary, per
    §3.10's consumers — M-JUDGE consumes M-INTEG's pure verifier, it does not re-spell
    it: `aeh.integ.verify_span` is the one implementation of the shared invariant).

    A reply that cites NOTHING passes vacuously — an uncited verdict is `FR-JUDGE-12`'s
    marked downgrade, not a verification failure. A reply that cites anything cannot
    become a verdict until each citation's bytes are the document's own: `verify_span`
    demands `0 <= start <= end <= len(raw)` AND `raw[start:end] == text` — text the
    document never carried, or offsets it does not hold, verify False. An unresolvable
    document (no store bound, no document row, a missing blob) makes every citation
    unverifiable and refuses the reply — fail-closed in both directions, because an
    unverifiable citation is indistinguishable from a forged one. Every refusal here is
    a `MalformedResponseError`, the same strike the dispatch loop already knows: the
    obeying reply is ROUTED out (refused, re-requested, quarantined at budget
    exhaustion — never persisted, so no verdict row and no confidence exists for
    M-AGG's auto-accept threshold to see).
    """
    if not cited:
        return
    raw = _canonical_document_bytes(store, request.submission.submission_id)
    if raw is None:
        raise MalformedResponseError(
            f"judge reply cites {len(cited)} span(s) but the canonical document for "
            f"submission {request.submission.submission_id!r} cannot be resolved to "
            f"bytes — an unverifiable citation is refused, not accepted as evidence "
            f"(FR-INTEG-01 fail-closed, FR-JUDGE-17)"
        )
    ref = request.submission.student_ref
    for index, span in enumerate(cited):
        if not verify_span(raw, span) and not _verifies_as_pseudonymized(
                raw, span, roster_name, ref):
            raise MalformedResponseError(
                f"judge reply cites span {index} {span!r} which fails byte-exact "
                f"verification against the canonical document — the cited text is not "
                f"the document's own bytes at those offsets (FR-INTEG-01, FR-JUDGE-17: "
                f"a forged citation fails span verification and the reply is refused, "
                f"never accepted)"
            )


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
    " response contract. Reply again with all five fields in their pinned order."
)


def _amended_payload(payload: PromptPayload) -> PromptPayload:
    """The amended render the `FR-JUDGE-10` re-request goes out with: the same pinned
    field order with the assessment ground-rules correction inserted immediately BEFORE
    the final field (the submission — `prompt_fields` guarantees it last, and the
    insertion keeps it last). The amendment is a different fully-assembled request —
    a different fixture key (`CT-PROV-05`) and a different call in `FR-PROV-06`'s
    sense, which is what makes the re-request legal where a verbatim replay would be a
    re-sampled verdict. Because the amendment text is static, the amended render's
    invariant prefix stays prefix-invariant across the batch (`FR-JUDGE-06`): every
    judge re-requesting on the same batch inserts the same bytes in the same place."""
    fields = list(payload.fields)
    fields.insert(len(fields) - 1, (_ASSESSMENT_AMENDMENT_FIELD, _AMENDMENT_TEXT))
    return PromptPayload(fields=tuple(fields))
