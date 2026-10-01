"""The scoring request: the only fields a judge may see, the types that carry them, and the isolation check."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from .errors import IsolationViolation


# --- the whitelist request schema (FR-JUDGE-01, FR-JUDGE-02) -------------------------------------


@dataclass(frozen=True)
class BandView:
    """One declared band as the request carries it: its name, its position in the set, and the
    descriptor saying what it means. It has no score value (FR-JUDGE-03): a judge that can see what a
    band is worth is not judging."""

    band: str
    ordinal: int
    descriptor: str


@dataclass(frozen=True)
class ExemplarView:
    """One worked example from the package (FR-PKG-07): its id, the band it illustrates, and the
    example text. The text is content, so the numeral scan checks it leniently (a student's "12 kg"
    is fine); the band label is rubric."""

    exemplar_id: str
    band: str
    text: str


@dataclass(frozen=True)
class CriterionView:
    """The request's `criterion` object: the one criterion being judged (design §9.9).

    `text` is the wording being judged (the question's prompt text — the package's
    criterion rows carry identity, not prose), `bands` the declared set ordered by
    ordinal, and `exemplars` the criterion's worked examples in `FR-JUDGE-08`'s
    presentation order (fixed within a batch, salted across batches). All three are
    empty at the contract door, where an arm row carries identity only; a store-backed
    assembly fills them from the run's package version."""

    criterion_id: str
    text: str
    bands: tuple[BandView, ...] = ()
    exemplars: tuple[ExemplarView, ...] = ()


@dataclass(frozen=True)
class QuestionView:
    """The request's `question` object: the question's prompt and reference solution when the
    criterion belongs to a question, and empty (not missing) when it does not, so the request shape
    never changes (design §9.9)."""

    prompt_text: str
    reference_solution: str


@dataclass(frozen=True)
class SubmissionView:
    """The request's `submission` object: the submission id and the student's pseudonym
    (NFR-JUDGE-04). There is no field for the student's name."""

    submission_id: str
    student_ref: str


@dataclass(frozen=True)
class DependencyEvidence:
    """A parent criterion's already-extracted spans, as the request carries them (design §9.9).

    Spans only: the schema carries no verdict on a dependency — there is no field for
    one, so a parent's band is not merely unfilled but **unrepresentable**
    (`FR-JUDGE-14`). Spans travel VERBATIM, checked against the span schema and
    forwarded unchanged — never re-typed, so the child's request carries the parent's
    evidence exactly as the extractor resolved it.
    """

    criterion_id: str
    spans: tuple[Any, ...]


@dataclass(frozen=True)
class ScoringRequest:
    """The scoring request: the whitelist, exactly the seven declared keys (design §9.9).

    Construction is the validation: a kwarg outside the whitelist is a `TypeError`
    (the schema is closed — adding a field is a schema change, not a call-site
    change), and the nested views are coerced and re-checked here so a dict-shaped
    caller and an already-built request land in the same place. The views themselves
    are frozen: a request built clean stays clean.
    """

    work_id: str
    criterion: "CriterionView"
    question: QuestionView
    evidence: tuple[Any, ...]
    dependency_evidence: tuple[DependencyEvidence, ...]
    submission: SubmissionView
    submission_text: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "criterion", _criterion_of(self.criterion)
        )
        object.__setattr__(self, "question", _question_of(self.question))
        object.__setattr__(
            self, "submission", _submission_of(self.submission)
        )
        object.__setattr__(
            self,
            "evidence",
            tuple(
                _span_of(span, where=f"evidence[{index}]")
                for index, span in enumerate(_sequence_of(self.evidence, "evidence"))
            ),
        )
        object.__setattr__(
            self,
            "dependency_evidence",
            tuple(
                _dependency_entry_of(entry)
                for entry in _sequence_of(self.dependency_evidence, "dependency_evidence")
            ),
        )
        if not isinstance(self.work_id, str) or not self.work_id:
            raise TypeError(
                f"ScoringRequest carries work_id {self.work_id!r}; a non-empty "
                f"string is required — a judgment without its unit id is an "
                f"unattributable verdict"
            )
        if not isinstance(self.submission_text, str):
            raise ValueError(
                f"ScoringRequest submission_text must be a string, got "
                f"{type(self.submission_text).__name__}"
            )
        assert_isolated(self)


# --- request assembly ----------------------------------------------------------------------------

_CRITERION_KEYS = frozenset({"criterion_id", "text", "bands", "exemplars"})


_BAND_KEYS = frozenset({"band", "ordinal", "descriptor"})


_EXEMPLAR_KEYS = frozenset({"exemplar_id", "band", "text"})


_QUESTION_KEYS = frozenset({"prompt_text", "reference_solution"})


_SUBMISSION_KEYS = frozenset({"submission_id", "student_ref"})


_SPAN_KEYS = frozenset({"start", "end", "text", "region_kind"})


_DEPENDENCY_ENTRY_KEYS = frozenset({"criterion_id", "spans"})


def _sequence_of(raw: Any, where: str) -> tuple:
    """A sequence, or an empty tuple for None. A single value is refused."""
    if raw is None:
        return ()
    if isinstance(raw, (list, tuple)):
        return tuple(raw)
    raise TypeError(f"{where} must be a sequence, got {type(raw).__name__}")


def _band_of(raw: Any) -> BandView:
    """One declared band as the whitelist carries it: name, ordinal and descriptor, never a score value
    (FR-JUDGE-03)."""
    if isinstance(raw, BandView):
        return raw
    if not isinstance(raw, dict):
        raise TypeError(
            f"criterion bands must be mappings of {sorted(_BAND_KEYS)}, got "
            f"{type(raw).__name__}"
        )
    unknown = sorted(set(raw) - _BAND_KEYS)
    if unknown:
        raise ValueError(
            f"band entry carries key(s) {unknown} outside "
            f"{sorted(_BAND_KEYS)} — a band's points are the package tier's, "
            f"never the request's (FR-JUDGE-03)"
        )
    return BandView(
        band=str(raw["band"]),
        ordinal=int(raw["ordinal"]),
        descriptor=str(raw.get("descriptor", "")),
    )


def _exemplar_of(raw: Any) -> ExemplarView:
    """One worked example as the whitelist carries it: id, band and text. There is no slot for
    anything verdict-like."""
    if isinstance(raw, ExemplarView):
        return raw
    if not isinstance(raw, dict):
        raise TypeError(
            f"criterion exemplars must be mappings of {sorted(_EXEMPLAR_KEYS)}, got "
            f"{type(raw).__name__}"
        )
    unknown = sorted(set(raw) - _EXEMPLAR_KEYS)
    if unknown:
        raise ValueError(
            f"exemplar entry carries key(s) {unknown} outside "
            f"{sorted(_EXEMPLAR_KEYS)} — the exemplar channel carries worked "
            f"examples, nothing verdict-shaped"
        )
    return ExemplarView(
        exemplar_id=str(raw.get("exemplar_id", "")),
        band=str(raw.get("band", "")),
        text=str(raw.get("text", "")),
    )


def _criterion_of(raw: Any) -> "CriterionView":
    """The request's `criterion` object: identity, wording, the declared bands and the worked
    examples. It is the whole rubric, and nothing verdict-like."""
    if isinstance(raw, CriterionView):
        bands = tuple(_band_of(band) for band in raw.bands)
        exemplars = tuple(_exemplar_of(exemplar) for exemplar in raw.exemplars)
        if bands == tuple(raw.bands) and exemplars == tuple(raw.exemplars):
            return raw
        return CriterionView(
            criterion_id=raw.criterion_id, text=raw.text, bands=bands,
            exemplars=exemplars,
        )
    if isinstance(raw, dict):
        unknown = sorted(set(raw) - _CRITERION_KEYS)
        if unknown:
            raise ValueError(
                f"criterion carries key(s) {unknown} outside {sorted(_CRITERION_KEYS)}"
            )
        return CriterionView(
            criterion_id=str(raw.get("criterion_id", "")),
            text=str(raw.get("text", "")),
            bands=tuple(
                _band_of(band) for band in (raw.get("bands") or ())
            ),
            exemplars=tuple(
                _exemplar_of(exemplar) for exemplar in (raw.get("exemplars") or ())
            ),
        )
    raise TypeError(
        f"criterion must be a CriterionView or a mapping of "
        f"{sorted(_CRITERION_KEYS)}, got {type(raw).__name__}"
    )


def _question_of(raw: Any) -> QuestionView:
    """The request's `question` object. A missing question becomes an empty one, so the request has
    the same shape whether or not the run has a question."""
    if raw is None:
        return QuestionView(prompt_text="", reference_solution="")
    if isinstance(raw, QuestionView):
        return raw
    if isinstance(raw, dict):
        unknown = sorted(set(raw) - _QUESTION_KEYS)
        if unknown:
            raise ValueError(
                f"question carries key(s) {unknown} outside {sorted(_QUESTION_KEYS)}"
            )
        return QuestionView(
            prompt_text=str(raw.get("prompt_text", "")),
            reference_solution=str(raw.get("reference_solution", "")),
        )
    raise ValueError(
        f"question must be a QuestionView or a mapping of {sorted(_QUESTION_KEYS)}, "
        f"got {type(raw).__name__}"
    )


def _submission_of(raw: Any) -> SubmissionView:
    """The request's `submission` object: only the submission id and the student's pseudonym. A
    `student_name` cannot be passed at all (NFR-JUDGE-04)."""
    if isinstance(raw, SubmissionView):
        return raw
    if isinstance(raw, dict):
        unknown = sorted(set(raw) - _SUBMISSION_KEYS)
        if unknown:
            raise ValueError(
                f"submission carries key(s) {unknown} outside "
                f"{sorted(_SUBMISSION_KEYS)} — a payload carries student_ref only "
                f"(NFR-JUDGE-04)"
            )
        return SubmissionView(
            submission_id=str(raw.get("submission_id", "")),
            student_ref=str(raw.get("student_ref", "")),
        )
    raise ValueError(
        f"submission must be a SubmissionView or a mapping of "
        f"{sorted(_SUBMISSION_KEYS)}, got {type(raw).__name__}"
    )


def _span_of(raw: Any, *, where: str) -> Any:
    """Check one evidence span against the span shape and return it unchanged. A verdict-like key
    such as `band` or `confidence` is refused, so no verdict can travel through an evidence channel
    (FR-JUDGE-14)."""
    if not isinstance(raw, dict):
        if dataclasses.is_dataclass(raw) and not isinstance(raw, type):
            return raw  # a span object travels verbatim, as the extractor typed it
        raise TypeError(
            f"{where} must be a mapping of span fields, got {type(raw).__name__}"
        )
    unknown = sorted(set(raw) - _SPAN_KEYS)
    if unknown:
        raise ValueError(
            f"{where} carries key(s) {unknown} outside the span schema — a verdict "
            f"cannot travel inside evidence spans"
        )
    return raw


def _dependency_entry_of(raw: Any) -> DependencyEvidence:
    """One `dependency_evidence` entry: `{criterion_id, spans}` and nothing else. A verdict-like
    key at this level is refused too."""
    if isinstance(raw, DependencyEvidence):
        return raw
    if isinstance(raw, dict):
        unknown = sorted(set(raw) - _DEPENDENCY_ENTRY_KEYS)
        if unknown:
            raise ValueError(
                f"dependency_evidence entry carries key(s) {unknown} outside the "
                f"dependency schema — the schema carries parent SPANS only, so a "
                f"verdict is unrepresentable, not merely unfilled"
            )
        criterion_id = raw.get("criterion_id")
        if not isinstance(criterion_id, str) or not criterion_id:
            raise ValueError(
                f"dependency_evidence entry carries criterion_id {criterion_id!r}; "
                f"a non-empty string is required"
            )
        spans_raw = raw.get("spans", [])
        if not isinstance(spans_raw, (list, tuple)):
            raise TypeError(
                f"dependency_evidence[{criterion_id!r}] spans must be a sequence, "
                f"got {type(spans_raw).__name__}"
            )
        return DependencyEvidence(
            criterion_id=criterion_id,
            spans=tuple(
                _span_of(span, where=f"dependency_evidence[{criterion_id!r}] span {index}")
                for index, span in enumerate(spans_raw)
            ),
        )
    if hasattr(raw, "criterion_id") and hasattr(raw, "spans"):
        return raw  # an already-built entry passes through unchanged
    raise ValueError(
        f"dependency_evidence entries must be mappings of "
        f"{sorted(_DEPENDENCY_ENTRY_KEYS)}, got {type(raw).__name__}"
    )


# --- the isolation check (§7.2 Rule 1's machine-checkable form, FR-JUDGE-01) ---------------------

#: The contaminating-field vocabulary, from FR-JUDGE-01's own list (another judge's
#: verdict; this judge's verdict on another criterion; another submission; prior
#: cohorts; student identity or history; any running score) plus FR-JUDGE-03's points
#: prohibition. A field whose NAME carries one of these stems is capable of carrying
#: the thing, whatever its type. No exemptions: a legitimate field that trips a stem
#: is a finding about the field — renamed, never exempted from the scan.
_PROHIBITED_STEMS: tuple[str, ...] = (
    "verdict",
    "score",
    "points",
    "history",
    "summary",
    "prior",
    "cohort",
    "running_total",
    "name",
    "other",
)


#: FR-JUDGE-15's second scan: a mixed question's judged request carries neither the
#: deterministic criterion's selection nor its correctness — no field name capable of
#: carrying them may exist.
_DETERMINISTIC_STEMS: tuple[str, ...] = (
    "selection",
    "correct",
    "deterministic",
    "option",
    "answer_key",
    "mcq",
)


def _request_names(value: Any, _depth: int = 0) -> Any:
    """Every field name anywhere in the request, from dataclass fields, mapping keys and list
    items. The whitelist is checked over the whole assembled object, not over a list of fields
    someone remembered."""
    if _depth > 12:
        return
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            yield field.name
            yield from _request_names(getattr(value, field.name), _depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _request_names(item, _depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _request_names(item, _depth + 1)


def assert_isolated(request: Any) -> None:
    """Check that an assembled request holds nothing outside the whitelist (design §3.10, §7.2 Rule
    1).

    Every field name the request carries, at any depth, against the contaminating
    stems (`_PROHIBITED_STEMS`) and the deterministic-criterion stems
    (`_DETERMINISTIC_STEMS`): a name capable of carrying another judge's verdict, a
    prior cohort, a student identity, a running score or a deterministic criterion's
    selection is a `IsolationViolation` — the schema has no field for the thing, and a
    name is the shape a smuggled one must take. Raises nothing for a request built
    clean; the construction door refuses anything the whitelist has no field for
    before this is ever reached.
    """
    names = list(_request_names(request))
    offenders = sorted(
        {name for name in names for stem in _PROHIBITED_STEMS if stem in name.lower()}
        | {name for name in names for stem in _DETERMINISTIC_STEMS if stem in name.lower()}
    )
    if offenders:
        raise IsolationViolation(
            f"the scoring request carries contaminating-capable field(s) {offenders} — "
            f"FR-JUDGE-01/03/15: the whitelist has no field for another judge's "
            f"verdict, a prior cohort, student identity, a running score, or a "
            f"deterministic criterion's selection or correctness"
        )
