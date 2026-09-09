"""`CT-EXTRACT-04` — a dependent criterion's request carries spans, never a verdict
(`TC-EXTRACT-C04`).

Case of test plan §6.11.8; issue #72 (TS-65). Written ahead of #68 (`M-EXTRACT`);
registered in `WRITTEN_AHEAD_BLOCKERS` under `"#68 extraction contract suite (TS-65)"`.

The clause: where a criterion declares a dependency, the request carries the parent
criterion's **extracted spans** and never a verdict, band, or score;
`ExtractionRequest` is schema-typed so it cannot carry one (FR-EXTRACT-03). A consumer
may assert the absence **structurally**, not by inspection — the clause grants the
structural form explicitly, because that is the difference between a check ("none
happened to be present this time") and a guarantee ("there is nowhere for one to
live").

Halves:
1. **The dependency payload** — for a criterion whose package dependency declares a
   parent, the assembled request carries the parent's extracted spans under
   `dependency_evidence`, keyed by the parent's criterion id.
2. **The structural rejection** — the request type's field set equals the declared
   schema (`REQUEST_FIELDS`, HLD §9.9 verbatim, submission last), and constructing one
   with a verdict-shaped field raises: the type refuses a verdict rather than the code
   path happening not to set one.

Discriminator: widening `ExtractionRequest` with an optional verdict/band/score field
turns this red while every `FR-EXTRACT-*` case stays green — a request assembled
without the field passes every behavioural case, which is exactly the gap the
structural form closes.

**Disclosed stand-ins** (suite register, `_doubles.py`): D2 (the
`dependency_evidence=` assembly kwarg) and D8 (the declared schema). **Isolation:
rung 0** — pure assembly and type construction, no store, no provider.
"""

from __future__ import annotations

import dataclasses

import pytest

from aeh.orch import STAGE_EXTRACT, WorkUnit
from tests.support.extract_vocabulary import REQUEST_FIELDS, REQUEST_TYPE
from tests.support.impl import EXTRACT_MODULE, require
from tests.contract.extract._doubles import judgment_fields, require_extract_surface

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]

_PARENT_SPANS = [
    {"start": 41, "end": 91, "text": "The parent's cited material.", "region_kind":
     "transcribed_text"},
]


def _dependent_unit() -> WorkUnit:
    """A leased-shaped extract unit for criterion C1, which declares C0 as a parent."""
    return WorkUnit(
        work_id="w-dep",
        run_id="r-ct-c04",
        stage=STAGE_EXTRACT,
        student_ref="S-0001",
        student_name=None,
        submission_id="SYN-001",
        criterion_id="C1",
        submission_text=None,
        judge=None,
    )


def _entry_fields(entry: object) -> list[str]:
    if isinstance(entry, dict):
        return list(entry.keys())
    if dataclasses.is_dataclass(entry) and not isinstance(entry, type):
        return [f.name for f in dataclasses.fields(entry)]
    if hasattr(entry, "__dict__"):
        return sorted(vars(entry))
    return [a for a in dir(entry) if not a.startswith("_")]


def test_tc_extract_c04_the_request_carries_the_parents_extracted_spans():
    """`TC-EXTRACT-C04` — `dependency_evidence` on the assembled request is the parent
    criterion's extracted spans, keyed by the parent's criterion id."""
    AssembleRequest = require(EXTRACT_MODULE, "assemble_request", issue="#68")
    require_extract_surface()
    request = AssembleRequest(
        _dependent_unit(),
        dependency_evidence=[{"criterion_id": "C0", "spans": _PARENT_SPANS}],
        question={"prompt_text": "Explain the mechanism.", "reference_solution": "—"},
    )
    dependency = getattr(request, "dependency_evidence", None) or (
        request["dependency_evidence"] if isinstance(request, dict) else None
    )
    assert dependency is not None, (
        "TC-EXTRACT-C04: the assembled request carries no dependency_evidence — the "
        "parent's spans never reach the extractor"
    )
    (entry,) = list(dependency)
    entry_id = entry.get("criterion_id") if isinstance(entry, dict) else entry.criterion_id
    entry_spans = entry.get("spans") if isinstance(entry, dict) else entry.spans
    assert entry_id == "C0", (
        f"TC-EXTRACT-C04: dependency keyed by {entry_id!r}, not the parent criterion"
    )
    assert list(entry_spans) == _PARENT_SPANS, (
        f"TC-EXTRACT-C04: dependency spans {entry_spans!r} != the parent's extracted "
        f"spans — something other than spans was forwarded"
    )
    assert judgment_fields(_entry_fields(entry)) == [], (
        "TC-EXTRACT-C04: judgment vocabulary inside the dependency payload"
    )


def test_tc_extract_c04_the_request_type_rejects_a_verdict_structurally():
    """`TC-EXTRACT-C04` — the structural half: `ExtractionRequest`'s field set equals
    the declared schema and the type REFUSES a verdict rather than carrying one."""
    ExtractionRequest = require(EXTRACT_MODULE, REQUEST_TYPE, issue="#68")
    require_extract_surface()
    names = [f.name for f in dataclasses.fields(ExtractionRequest)]
    assert set(names) == set(REQUEST_FIELDS), (
        f"TC-EXTRACT-C04: ExtractionRequest fields {sorted(names)} != the declared "
        f"schema {sorted(REQUEST_FIELDS)}"
    )
    assert names[-1] == "submission", (
        f"TC-EXTRACT-C04: 'submission' must be declared LAST (§8.4), got {names}"
    )
    # The structural rejection: the schema-typed type cannot represent a verdict.
    for smuggled in ("verdict", "band", "score", "self_confidence"):
        try:
            ExtractionRequest(**{
                "work_id": "w",
                "criterion": {"criterion_id": "C1", "text": "t",
                              "evidence_type": "textual_span"},
                "question": {"prompt_text": "p", "reference_solution": "r"},
                "dependency_evidence": [],
                "submission": {"submission_id": "s", "transcript": "m"},
                smuggled: "secure",
            })
        except TypeError:
            continue
        raise AssertionError(
            f"TC-EXTRACT-C04: ExtractionRequest accepted {smuggled!r}=... — the type "
            f"can carry a verdict, so the clause's guarantee is a check, not a "
            f"guarantee"
        )
