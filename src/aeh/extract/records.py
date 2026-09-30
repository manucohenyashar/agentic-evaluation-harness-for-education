"""The extraction request, span and result types, and the checks on dependency evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aeh.ingest import REGION_KINDS


@dataclass(frozen=True)
class ExtractionSpan:
    """One span of the canonical document, as byte offsets into `document.markdown`.

    `start`/`end` are BYTE offsets into the canonical artifact's utf-8 bytes
    (`FR-EXTRACT-01`); `text` is the slice the bytes actually re-decode to — derived
    at parse, never trusted from the reply, so a span's text cannot disagree with its
    offsets. `region_kind` is the ingest region the span sits in (`FR-EXTRACT-09`): a
    described-graphic span stays marked all the way to the evidence payload.
    """

    start: int
    end: int
    text: str
    region_kind: str = "transcribed_text"


@dataclass(frozen=True)
class DependencyEvidence:
    """A parent criterion's already-extracted spans, as the request carries them (design §3.8).

    Spans only: the schema carries no verdict on a dependency — an implementation
    cannot record a parent's band here because there is no field for one
    (`TC-EXTRACT-03`'s schema assertion). The parent's spans travel VERBATIM: the
    caller's entries are checked against the spans-only schema and forwarded
    unchanged — never re-typed, so the child's request carries the parent's
    evidence exactly as the caller resolved it (`TC-EXTRACT-C04`).
    """

    criterion_id: str
    spans: tuple[Any, ...]


@dataclass(frozen=True)
class Criterion:
    """The request's `criterion` object (design §3.8). With a store, `text` and `evidence_type`
    come from the run's pinned package version (see docs/code-notes/extract.md)."""

    criterion_id: str
    text: str
    evidence_type: str


@dataclass(frozen=True)
class Question:
    """The request's `question` object: the question's prompt text and reference solution, when the
    run has them (design §3.8)."""

    prompt_text: str
    reference_solution: str


@dataclass(frozen=True)
class SubmissionRef:
    """The request's `submission` object: the submission id and the canonical transcript, unchanged
    (design §3.8)."""

    submission_id: str
    transcript: str


@dataclass(frozen=True)
class ExtractionRequest:
    """The extraction request: exactly five keys, the shape the isolation test walks (design §3.8).
    """

    work_id: str
    criterion: Criterion
    question: Question
    dependency_evidence: tuple[DependencyEvidence, ...]
    submission: SubmissionRef


@dataclass(frozen=True)
class ExtractionResult:
    """One processed unit: exactly the four declared result fields (design §9.9).

    `extractor` is the RESOLVED build identity of the model that actually answered
    (`FR-PROV-04`) — the evidence row's `resolved_build` column carries the same
    value, and echoing the requested identity is the substitution `TC-EXTRACT-05`
    forbids. `notes` is the stage-level observability channel (`CT-CONSOLE-08`'s
    "what each stage did, next to the status"): `None` on a clean extraction,
    otherwise one line saying what happened instead — the strike budget quarantined
    the unit, or the budget ran out with the unit still pending.
    """

    work_id: str
    spans: tuple[ExtractionSpan, ...]
    extractor: str | None
    notes: str | None = None


# --- request assembly ----------------------------------------------------------------------------

_DEPENDENCY_ENTRY_KEYS = frozenset({"criterion_id", "spans"})


_DEPENDENCY_SPAN_KEYS = frozenset({"start", "end", "text", "region_kind"})


_QUESTION_KEYS = frozenset({"prompt_text", "reference_solution"})


def _offset_of(raw: Any, *, where: str) -> int:
    """One span offset, which must be an integer. A bool, float or string is refused, not
    converted, because a converted offset would silently point somewhere else."""
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"{where} must be an integer byte offset, got {raw!r}")
    return raw


def _dependency_span(raw: Any, *, criterion_id: str, index: int) -> Any:
    """Check one dependency span against the span shape and return it unchanged. It may carry only
    the span keys; a verdict-like key such as `band` or `confidence` is refused, so no verdict can
    travel through the dependency channel (TC-EXTRACT-03)."""
    if isinstance(raw, ExtractionSpan):
        return raw
    if not isinstance(raw, dict):
        raise ValueError(
            f"dependency_evidence[{criterion_id!r}] span {index} must be a mapping "
            f"of span fields, got {type(raw).__name__}"
        )
    unknown = sorted(set(raw) - _DEPENDENCY_SPAN_KEYS)
    if unknown:
        raise ValueError(
            f"dependency_evidence[{criterion_id!r}] span {index} carries key(s) "
            f"{unknown} outside the span schema — a parent's verdict cannot travel "
            f"in the dependency evidence"
        )
    _offset_of(raw.get("start"), where=f"dependency span {index} start")
    _offset_of(raw.get("end"), where=f"dependency span {index} end")
    region_kind = raw.get("region_kind", "transcribed_text")
    if region_kind not in REGION_KINDS:
        raise ValueError(
            f"dependency_evidence[{criterion_id!r}] span {index} carries "
            f"region_kind {region_kind!r}, outside {REGION_KINDS}"
        )
    return raw


def _dependency_entry(raw: Any) -> DependencyEvidence:
    """One `dependency_evidence` entry: `{criterion_id, spans}` and nothing else."""
    if isinstance(raw, DependencyEvidence):
        return raw
    if not isinstance(raw, dict):
        raise ValueError(
            f"dependency_evidence entries must be mappings of "
            f"{sorted(_DEPENDENCY_ENTRY_KEYS)}, got {type(raw).__name__}"
        )
    unknown = sorted(set(raw) - _DEPENDENCY_ENTRY_KEYS)
    if unknown:
        raise ValueError(
            f"dependency_evidence entry carries key(s) {unknown} outside the "
            f"dependency schema — the schema carries parent SPANS only"
        )
    criterion_id = raw.get("criterion_id")
    if not isinstance(criterion_id, str) or not criterion_id:
        raise ValueError(
            f"dependency_evidence entry carries criterion_id {criterion_id!r}; a "
            f"non-empty string is required"
        )
    spans_raw = raw.get("spans", [])
    if not isinstance(spans_raw, (list, tuple)):
        raise ValueError(
            f"dependency_evidence[{criterion_id!r}] spans must be a sequence, got "
            f"{type(spans_raw).__name__}"
        )
    return DependencyEvidence(
        criterion_id=criterion_id,
        spans=tuple(
            _dependency_span(span, criterion_id=criterion_id, index=index)
            for index, span in enumerate(spans_raw)
        ),
    )


def _question_of(raw: Any) -> Question:
    """The request's `question` object. A missing question becomes an empty one, so the request has
    the same shape whether or not the run has a question."""
    if raw is None:
        return Question(prompt_text="", reference_solution="")
    if isinstance(raw, Question):
        return raw
    if isinstance(raw, dict):
        unknown = sorted(set(raw) - _QUESTION_KEYS)
        if unknown:
            raise ValueError(
                f"question carries key(s) {unknown} outside "
                f"{sorted(_QUESTION_KEYS)}"
            )
        return Question(
            prompt_text=str(raw.get("prompt_text", "")),
            reference_solution=str(raw.get("reference_solution", "")),
        )
    raise ValueError(
        f"question must be a mapping of {sorted(_QUESTION_KEYS)}, got "
        f"{type(raw).__name__}"
    )
