"""The extraction request, span and result types, and the checks on dependency evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aeh.ingest import REGION_KINDS


@dataclass(frozen=True)
class ExtractionSpan:
    """One byte-offset span into `document.markdown`.

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
    """A parent criterion's already-extracted spans, as §3.8's request carries them.

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
    """§3.8's `criterion` object. `text`/`evidence_type` come from the run's pinned package
    version when the assembler has a store (#516); see the module docstring."""

    criterion_id: str
    text: str
    evidence_type: str


@dataclass(frozen=True)
class Question:
    """§3.8's `question` object — the assignment's prompt text and reference
    solution, when the run carries one."""

    prompt_text: str
    reference_solution: str


@dataclass(frozen=True)
class SubmissionRef:
    """§3.8's `submission` object: the unit's submission id and the canonical
    transcript, verbatim."""

    submission_id: str
    transcript: str


@dataclass(frozen=True)
class ExtractionRequest:
    """§3.8's request, exactly five keys — the schema the isolation case walks."""

    work_id: str
    criterion: Criterion
    question: Question
    dependency_evidence: tuple[DependencyEvidence, ...]
    submission: SubmissionRef


@dataclass(frozen=True)
class ExtractionResult:
    """One processed unit — §9.9's result, exactly the declared four fields.

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
    """One span offset, strictly an integer — a bool, a float or a string is a
    refusal, not a coercion (a coerced offset is a silently rewritten address)."""
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"{where} must be an integer byte offset, got {raw!r}")
    return raw


def _dependency_span(raw: Any, *, criterion_id: str, index: int) -> Any:
    """One dependency span, checked against the §3.8 shape and returned VERBATIM:
    exactly the span keys, no more — a verdict-shaped key (`band`, `confidence`,
    ...) is a refusal, which is what makes a verdict impossible to smuggle through
    the dependency channel (`TC-EXTRACT-03`, step 3). Nothing is re-typed: the
    caller's span is the span the child's request carries."""
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
    """The request's `question` object: absent means empty, not missing — the request
    shape is stable across runs that carry a question and runs that do not."""
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
