"""`TC-EXTRACT-03` — a dependency carries the parent's spans and CANNOT carry a verdict.
Test plan §5.8 (full block form); `FR-EXTRACT-03`; RISK-02 (Critical) — a verdict
crossing a dependency edge is contamination.

Oracle: schema assertion (steps 2 and 3) plus a pattern scan over assembled requests
(step 4), exactly as the plan states.

Steps implemented:
1. `test_dependency_evidence_carries_the_parent_spans` — assemble the extraction request
   for c4 given a completed extraction for c2 (its spans, passed as the dependency
   evidence the orchestrator's topological order guarantees already exist, `CT-ORCH-05`)
   and assert `dependency_evidence` contains c2's spans.
2. `test_no_field_of_the_request_schema_can_carry_a_verdict` — enumerate the
   `ExtractionRequest` schema recursively and assert **no field** is capable of carrying
   a band, verdict, score, points or confidence at any nesting depth, including
   free-text fields named as such. `CT-EXTRACT-04`: "A consumer may assert the absence
   structurally, not by inspection."
3. `test_a_verdict_injected_into_dependency_evidence_fails_validation` — construct a
   request with a verdict injected into `dependency_evidence` and assert the
   construction FAILS VALIDATION rather than being dropped silently: no exception means
   a silent accept-or-strip, and either is the failure (a strip lets the caller believe
   the shape held; an accept ships the verdict).
4. `test_full_f_synth_run_requests_are_clean_of_verdict_shapes` — assemble the request
   for every judged (submission, criterion) of the `F-SYNTH` reference package through
   the module's own assembly seam and scan every string the request carries for
   band-shaped or score-shaped content. Shape-based, not word-based (the TC-JUDGE-08
   lesson: a scan that flags "score" inside legitimate teacher prose is a failing scan).
5. `test_chain_c2_c4_c7_carries_c4s_spans_and_nothing_from_c4s_verdict` — the plan's
   variant: c7's request carries c4's *spans* and nothing derived from c4's verdict,
   even though a completed verdict for c4 exists and c4's own request carried c2's
   spans.

**Written ahead of #68** (`M-EXTRACT`). Registered in `WRITTEN_AHEAD_BLOCKERS` under
`"#68 extraction suite (TS-26)"` (symbols conjunction; see
`tests/support/extract_vocabulary.py`).

**Interface this case assumes of #68**, listed so it is reconciled deliberately:

| Name | Status |
|---|---|
| `assemble_request(unit, dependency_evidence=...) -> ExtractionRequest` | **assumed here** — the pure assembly (§3.10 declares the analogous `assemble(unit) -> ScoringRequest` for `M-JUDGE`); the `dependency_evidence` keyword is how the caller passes the parent spans the worker already resolved, and the plan's step 1 needs it at rung 0 |
| `ExtractionRequest` | **design-named** (§3.8 Interfaces prose: "ExtractionRequest / ExtractionResult exactly as HLD §9.9 specifies") — schema-typed, so a verdict in `dependency_evidence` cannot be constructed |
| the §3.8 JSON field names (`work_id`, `criterion.criterion_id/text/evidence_type`, `question.prompt_text/reference_solution`, `dependency_evidence[].criterion_id/spans[].start/end/text`, `submission.submission_id/transcript`) | **design-pinned** |
| `WorkUnit` | **shipped** (`aeh.orch`, #57) — hand-built here at rung 0 with `submission_text` resolved, exactly as the lease surface (#58) resolves it |

**Disclosed stand-ins.** The units are hand-built values, not ledger rows: rung 0 has no
store, and the fields `assemble_request` reads are the ones #58's lease resolves anyway
(`student_name`/`submission_text` resolution is the lease's documented job). The parent
spans are the value a completed c2 extraction would have returned — the completed
*verdict* for c2 (and for c4, in the chain) is hand-built too, because its role in the
case is to EXIST and be absent from the request, not to be produced.

**Isolation: rung 0** — pure values and the socket guard; no store, no provider, no
model. A model call here would be a defect, and the autouse `network_guard` makes it
one.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

import pytest

from aeh.orch import STAGE_EXTRACT, WorkUnit
from tests.support.extract_vocabulary import (
    ASSEMBLE,
    EXTRACT_ISSUE,
    REQUEST_TYPE,
    WORKER,
)
from tests.support.impl import EXTRACT_MODULE, require

pytestmark = pytest.mark.writtenahead

ISSUE = EXTRACT_ISSUE

#: The prohibition's vocabulary. A field whose NAME carries one of these stems is
#: capable of carrying the thing, whatever its type — "including free-text fields typed
#: as such" (the plan's step 2).
_PROHIBITED_STEMS = ("band", "verdict", "score", "points", "confidence")

#: Verdict-shaped CONTENT, for the step-4 corpus scan. Shapes, not words: "12 kg" is
#: legitimate material, "3/4 points" and "band 2" are not.
_SHAPES = (
    re.compile(r"\b\d+\s*/\s*\d+\b"),                                   # 3/4
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:points?|marks?|pts)\b", re.I),     # 2 points
    re.compile(r"\bband\s*(?:ordinal\s*)?[:=]?\s*[0-4]\b", re.I),        # band 2
    re.compile(r"\b\d+\s+out of\s+\d+\b", re.I),                         # 2 out of 4
)

_C2_SPANS = [
    {"start": 0, "end": 27, "text": "The crate accelerates at 2 m/s^2."},
    {"start": 28, "end": 61, "text": "Friction opposes the motion up the slope."},
]
_C2_ENTRY = {"criterion_id": "c2", "spans": _C2_SPANS}

_TRANSCRIPT = "The crate accelerates at 2 m/s^2. Friction opposes the motion up the slope."


def _unit(criterion_id: str, *, submission_id: str = "s231") -> WorkUnit:
    """A leased, resolved extract unit as a pure value — the lease surface's documented
    job (resolving `submission_text` onto the unit) done by hand at rung 0."""
    return WorkUnit(
        work_id=f"sha256:{criterion_id}-{submission_id}",
        run_id="run-rung0",
        stage=STAGE_EXTRACT,
        student_ref="ref-s231",
        student_name=None,
        submission_id=submission_id,
        criterion_id=criterion_id,
        submission_text=_TRANSCRIPT,
        judge=None,
        attempt=0,
    )


def _assemble(*args: Any, **kwargs: Any) -> Any:
    AssembleRequest = require(EXTRACT_MODULE, ASSEMBLE, issue=ISSUE)
    return AssembleRequest(*args, **kwargs)


def _string_leaves(obj: Any, path: str = "") -> list[tuple[str, str]]:
    """Every (path, string) leaf in the object tree — dataclass, mapping or sequence —
    so the scans see field VALUES at any nesting depth."""
    if isinstance(obj, str):
        return [(path, obj)]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out: list[tuple[str, str]] = []
        for field in dataclasses.fields(obj):
            out.extend(
                _string_leaves(getattr(obj, field.name), f"{path}.{field.name}")
            )
        return out
    if isinstance(obj, dict):
        out = []
        for key, value in obj.items():
            out.extend(_string_leaves(value, f"{path}.{key}"))
        return out
    if isinstance(obj, (list, tuple)):
        out = []
        for index, value in enumerate(obj):
            out.extend(_string_leaves(value, f"{path}[{index}]"))
        return out
    return []


def _field_names(obj: Any, path: str = "") -> list[str]:
    """Every field NAME in the object tree at any nesting depth."""
    names: list[str] = []
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for field in dataclasses.fields(obj):
            names.append(field.name)
            names.extend(_field_names(getattr(obj, field.name), f"{path}.{field.name}"))
    elif isinstance(obj, dict):
        for key, value in obj.items():
            names.append(str(key))
            names.extend(_field_names(value, f"{path}.{key}"))
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            names.extend(_field_names(value, f"{path}[]"))
    return names


def _schema_names(request_type: Any, obj: Any) -> list[str]:
    """The schema's names: the TYPE's fields when the type declares them (a dataclass
    or TypedDict — including fields an instance left at its default), plus every name
    present on the instance."""
    names = list(_field_names(obj))
    if dataclasses.is_dataclass(request_type):
        names.extend(field.name for field in dataclasses.fields(request_type))
        for field in dataclasses.fields(request_type):
            names.extend(_field_names(getattr(obj, field.name, None)))
    annotations = getattr(request_type, "__annotations__", None)
    if annotations:
        names.extend(str(name) for name in annotations)
        for name, value in annotations.items():
            names.extend(_field_names(getattr(obj, name, None), name))
    return names


def _entry_facts(entry: Any) -> tuple[str, list[tuple[int, int, str]]]:
    """(criterion_id, [(start, end, text), ...]) for one dependency_evidence entry,
    however #68 shapes the spans (dicts or attributes)."""
    criterion_id = entry.get("criterion_id") if isinstance(entry, dict) else entry.criterion_id
    raw_spans = entry.get("spans") if isinstance(entry, dict) else entry.spans
    triples = []
    for span in raw_spans:
        if isinstance(span, dict):
            triples.append((span["start"], span["end"], span["text"]))
        else:
            triples.append((span.start, span.end, span.text))
    return str(criterion_id), triples


def _entries_of(request: Any) -> list[Any]:
    return (
        list(request.dependency_evidence)
        if hasattr(request, "dependency_evidence")
        else list(request["dependency_evidence"])
    )


def test_tc_extract_03_step1_dependency_evidence_carries_the_parent_spans():
    """Step 1 — the request assembled for c4 carries c2's extracted spans in
    `dependency_evidence`: the topological order guarantees they exist (`CT-ORCH-05`),
    and this is the evidence the design intends the child to receive."""
    require(EXTRACT_MODULE, ASSEMBLE, REQUEST_TYPE, WORKER, issue=ISSUE)
    request = _assemble(_unit("c4"), dependency_evidence=[_C2_ENTRY])

    entries = _entries_of(request)
    assert [_entry_facts(entry) for entry in entries] == [
        ("c2", [(s["start"], s["end"], s["text"]) for s in _C2_SPANS])
    ], (
        f"dependency_evidence must carry c2's spans and nothing else, got {entries!r}"
    )


def test_tc_extract_03_step2_no_field_of_the_request_schema_can_carry_a_verdict():
    """Step 2 — the schema assertion: no field of `ExtractionRequest`, at any depth,
    is capable of carrying a band, verdict, score, points or confidence. The positive
    shape (the §3.8 JSON) is asserted too, so the prohibition cannot be satisfied by an
    empty schema."""
    request = _assemble(_unit("c4"), dependency_evidence=[_C2_ENTRY])
    ExtractionRequest = require(EXTRACT_MODULE, REQUEST_TYPE, issue=ISSUE)

    names = _schema_names(ExtractionRequest, request)
    offenders = sorted(
        {
            name
            for name in names
            for stem in _PROHIBITED_STEMS
            if stem in name.lower()
        }
    )
    assert not offenders, (
        f"ExtractionRequest carries verdict-capable field(s) {offenders} — CT-EXTRACT-04: "
        f"the schema must be UNABLE to carry a verdict, not trusted not to fill one in"
    )
    # The positive shape: the five §3.8 keys are present on the assembled request.
    for key in ("work_id", "criterion", "question", "dependency_evidence", "submission"):
        assert hasattr(request, key) or (isinstance(request, dict) and key in request), (
            f"assembled request is missing the §3.8 key {key!r}"
        )


def test_tc_extract_03_step3_a_verdict_injected_into_dependency_evidence_fails_validation():
    """Step 3 — injection into `dependency_evidence` FAILS VALIDATION. A silent strip
    and a silent accept are both failures: the first lets the caller believe the shape
    held, the second ships the verdict."""
    ExtractionRequest = require(EXTRACT_MODULE, REQUEST_TYPE, issue=ISSUE)
    AssembleRequest = require(EXTRACT_MODULE, ASSEMBLE, issue=ISSUE)

    # The §3.8-shaped kwargs of a clean request, to which the injection is added.
    clean = _assemble(_unit("c4"), dependency_evidence=[])
    kwargs = {
        name: getattr(clean, name, None)
        for name in ("work_id", "criterion", "question", "dependency_evidence",
                     "submission")
    }
    if isinstance(clean, dict):
        kwargs = {name: clean.get(name) for name in kwargs}
    assert all(value is not None for value in kwargs.values()), (
        f"fixture bug: could not read the assembled request's own shape: {kwargs!r}"
    )

    injected_entry = {
        "criterion_id": "c2",
        "spans": _C2_SPANS,
        # The verdict, injected at the entry level...
        "band": "secure",
        "band_ordinal": 3,
        "points": 3.0,
        "confidence": 0.91,
    }
    injected_span = {
        "start": 0,
        "end": 27,
        "text": "The crate accelerates at 2 m/s^2.",
        # ...and at the span level, where a "confident span" would be the tempting shape.
        "confidence": 0.97,
    }
    for label, evidence in (
        ("entry-level verdict", [injected_entry]),
        ("span-level verdict", [{"criterion_id": "c2", "spans": [injected_span]}]),
    ):
        attempt = dict(kwargs)
        attempt["dependency_evidence"] = evidence
        with pytest.raises(Exception):  # noqa: B017,PT011 — ANY refusal counts
            if isinstance(ExtractionRequest, type) and not isinstance(
                clean, ExtractionRequest
            ):
                ExtractionRequest(**attempt)
            else:
                # The assembly seam re-validates when the type itself cannot express
                # the refusal (a dict-shaped schema validates at assembly).
                AssembleRequest(_unit("c4"), dependency_evidence=evidence)


def test_tc_extract_03_step4_full_f_synth_run_requests_are_clean_of_verdict_shapes():
    """Step 4 — the corpus assertion: every request the module's own assembly seam
    produces for the `F-SYNTH` reference package is free of band-shaped or
    score-shaped content, in every string the request carries."""
    from tests.support.corpora import reference_package

    require(EXTRACT_MODULE, ASSEMBLE, REQUEST_TYPE, issue=ISSUE)
    package = reference_package()
    judged = [
        criterion
        for criterion in package["criteria"]
        if criterion.get("kind", "open") == "open"
    ]
    assert judged, "fixture bug: the reference package has no judged criteria"

    submissions = ("SYN-001", "SYN-002")
    scanned = 0
    for submission_id in submissions:
        for criterion in judged:
            unit = _unit(str(criterion["criterion_id"]), submission_id=submission_id)
            request = _assemble(unit)
            for path, text in _string_leaves(request):
                for shape in _SHAPES:
                    assert shape.search(text) is None, (
                        f"{path} in the request for ({submission_id}, "
                        f"{criterion['criterion_id']}) carries verdict-shaped content "
                        f"{shape.pattern!r}: {text!r}"
                    )
                scanned += 1
    assert scanned > len(judged), "the scan must have covered the whole corpus"


def test_tc_extract_03_variant_chain_c2_c4_c7_carries_c4s_spans_and_nothing_from_c4s_verdict():
    """Variant — the chain c2 → c4 → c7: c7's request carries C4's spans (its immediate
    parent's extracted evidence) and NOTHING derived from c4's verdict, although a
    completed verdict for c4 exists and is in scope."""
    require(EXTRACT_MODULE, ASSEMBLE, REQUEST_TYPE, issue=ISSUE)

    c4_spans = [{"start": 0, "end": 42, "text": "The net force points down the slope."}]
    c4_verdict = {
        "band": "secure",
        "band_ordinal": 3,
        "points": 3.0,
        "confidence": 0.88,
        "judge_id": "judge-1",
    }
    request = _assemble(
        _unit("c7"),
        dependency_evidence=[{"criterion_id": "c4", "spans": c4_spans}],
    )

    # c4's spans are present, keyed to c4.
    entries = _entries_of(request)
    assert [_entry_facts(entry) for entry in entries] == [
        ("c4", [(s["start"], s["end"], s["text"]) for s in c4_spans])
    ]

    # The verdict exists upstream — and appears NOWHERE in the request, in value or in
    # field name. Serialized-value scan: every string leaf, plus the verdict's own
    # scalars searched for verbatim.
    leaves = " | ".join(text for _path, text in _string_leaves(request))
    for value in (
        c4_verdict["band"],
        str(c4_verdict["band_ordinal"]),
        str(c4_verdict["points"]),
        str(c4_verdict["confidence"]),
        c4_verdict["judge_id"],
    ):
        assert value not in leaves, (
            f"c7's request carries material derived from c4's verdict ({value!r})"
        )
    names = [name.lower() for name in _field_names(request)]
    offenders = sorted(
        {name for name in names for stem in _PROHIBITED_STEMS if stem in name}
    )
    assert not offenders, f"verdict-capable fields on the chain request: {offenders}"


