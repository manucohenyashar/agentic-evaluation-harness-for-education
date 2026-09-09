"""`TC-EXTRACT-04` — the extraction prompt lint — and `TC-EXTRACT-13` — the extraction
prompt template version is pinned and part of the work ID.
Test plan §5.8; `FR-EXTRACT-04` and `NFR-EXTRACT-03`.

Oracles:
- **TC-EXTRACT-04 — template lint** (the design's named acceptance form): over sampled
  requests for several (submission, criterion) pairs, the rendered prompt's field-name
  sequence is IDENTICAL (fixed order); the student transcript appears ONLY in the last
  field's value — no earlier field carries it (submission last, after every invariant
  element); and that last value fences the transcript exactly once each between the
  shipped `M-INGEST` untrusted-content delimiters (`CT-EXTRACT-06` merges `FR-EXTRACT-04`
  and `FR-EXTRACT-10` into one lint). The invariant elements — the question's prompt
  text and reference solution — appear among the earlier fields and never in the last
  one.
- **TC-EXTRACT-13 — exact value plus cross-check**: the module pins the template
  version as a non-empty string constant; the assembled request echoes the unit's
  `work_id` (the orchestrator's version-bearing ID is the one that reaches the model
  call — a request that forks its own ID would desync the evidence row from the prompt);
  and the cross-check half — `compute_work_id` changes when `prompt_template_version`
  changes, and two whole enumerations differing ONLY in the pinned template version
  produce disjoint extract-unit work-id sets — is asserted UNMARKED against the shipped
  `M-ORCH` enumeration, because that mechanism is already real (it is `TC-ORCH-01`'s
  invalidation clause read from the extract side; disclosed as green-on-shipped).

**Written ahead of #68** (`M-EXTRACT`); the marker and its `WRITTEN_AHEAD_BLOCKERS`
entry (`"#68 extraction suite (TS-26)"`, built from
`tests/support/extract_vocabulary.py`) left when #68 landed `aeh.extract`.

**Interface this case assumes of #68**, listed so it is reconciled deliberately:

| Name | Status |
|---|---|
| `assemble_request(unit, dependency_evidence=..., question=...) -> ExtractionRequest` | **assumed here** — same seam the isolation file keys on, plus the two disclosed keyword inputs the §3.8 request shape needs that a shipped `WorkUnit` carries no source for (`extract_vocabulary`'s `ASSEMBLE` row); the lint's invariant-element assertions read back the `question=` this file supplies |
| `prompt_fields(request) -> PromptPayload` | **already assumed by the repo** — the `"#68 review"` registry entry resolves it; `CT-PROV-05` makes the ordered `fields` sequence contract |
| `EXTRACTION_PROMPT_TEMPLATE_VERSION` | **invented here** — `NFR-EXTRACT-03`'s pinned constant; its exact VALUE is #68's to fix, so only its existence and shape are asserted (disclosed) |
| `WorkUnit` / `compute_work_id` | **shipped** (`aeh.orch`, #57/#58) |

**Disclosed stand-ins.** Units are hand-built values with `submission_text` resolved —
the lease surface's documented job, done by hand at rung 0, exactly as in
`tests/artifact/test_extraction_isolation.py`. The enumerated runs in the cross-check
seed the ledger directly (`tests/support/orch_run.py`'s disclosed bypass). The untrusted
delimiters are `M-INGEST`'s shipped constants — the real fence the canonical document
carries.

**Isolation: rung 0** for the lint and the pin (pure values, socket-guarded); the
cross-check is rung 2 (real store, real enumeration — a store already has artifact-tier
precedent in `test_tc_store_15_no_search_surface.py`).
"""

from __future__ import annotations

from typing import Any

import pytest

from aeh.conf import CohortRef, resolve_run_config
from aeh.ingest import UNTRUSTED_CLOSE, UNTRUSTED_OPEN
from aeh.orch import STAGE_EXTRACT, Orchestrator, WorkUnit, compute_work_id
from aeh.store import open_store
from tests.support.conf_builders import edge_cfg, edge_panel
from tests.support.extract_vocabulary import (
    ASSEMBLE,
    EXTRACT_ISSUE,
    PROMPT_FIELDS,
    TEMPLATE_VERSION,
)
from tests.support.impl import EXTRACT_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_package

ISSUE = EXTRACT_ISSUE

_QUESTION = {
    "prompt_text": "Explain why the crate accelerates up the slope.",
    "reference_solution": "Net force along the slope divided by the mass.",
}

#: Transcripts carry a marker token the question does not — so "the marker appears only
#: in the last field" is a content test, not a word-overlap accident.
_TRANSCRIPTS = {
    "s401": " zxq-crate-401 slides. ",
    "s402": " zxq-crate-402 topples. ",
}

_C2_SPANS = [{"start": 0, "end": 27, "text": "The crate accelerates at 2 m/s^2."}]


def _unit(submission_id: str, criterion_id: str) -> WorkUnit:
    """A leased, resolved extract unit as a pure value — the lease's documented
    `submission_text` resolution done by hand at rung 0."""
    return WorkUnit(
        work_id=f"sha256:tmpl-{submission_id}-{criterion_id}",
        run_id="run-tmpl",
        stage=STAGE_EXTRACT,
        student_ref=f"ref-{submission_id}",
        student_name=None,
        submission_id=submission_id,
        criterion_id=criterion_id,
        submission_text=_TRANSCRIPTS[submission_id],
        judge=None,
        attempt=0,
    )


def _fields_of(request: Any) -> list[tuple[str, str]]:
    """The rendered prompt's ordered (name, value) pairs, however #68 shapes the
    payload (attribute or mapping)."""
    PromptFields = require(EXTRACT_MODULE, PROMPT_FIELDS, issue=ISSUE)
    payload = PromptFields(request)
    fields = getattr(payload, "fields", None)
    if fields is None and isinstance(payload, dict):
        fields = payload.get("fields")
    assert fields is not None, (
        f"prompt_fields returned {payload!r} — no ordered `fields` sequence "
        f"(CT-PROV-05 makes the order contract)"
    )
    return [(str(name), str(value)) for name, value in fields]


def test_tc_extract_04_template_lint_submission_last_fixed_order_fenced():
    """`TC-EXTRACT-04` — the lint: fixed field order across sampled requests; the
    transcript only in the last field, fenced exactly once between the shipped
    untrusted-content delimiters; invariant elements never in the last field."""
    AssembleRequest = require(EXTRACT_MODULE, ASSEMBLE, issue=ISSUE)

    sampled = []
    for submission_id in ("s401", "s402"):
        for criterion_id, dependency in (
            ("C1", []),                       # no dependency
            ("C4", [{"criterion_id": "C2", "spans": _C2_SPANS}]),  # carries parent spans
        ):
            request = AssembleRequest(
                _unit(submission_id, criterion_id),
                dependency_evidence=dependency,
                # The §3.8 request carries a `question` object; a shipped WorkUnit has
                # no source for it, so the lint supplies it through the disclosed
                # assembly input (extract_vocabulary's ASSEMBLE row) and reads it back.
                question=_QUESTION,
            )
            sampled.append((submission_id, criterion_id, request))

    # Fixed field order: one field-name sequence for every sampled request.
    orders = [tuple(name for name, _value in _fields_of(request))
              for _s, _c, request in sampled]
    assert orders and all(order == orders[0] for order in orders), (
        f"field order is not fixed across sampled requests: {orders}"
    )
    assert len(orders[0]) >= 2, "the prompt must carry more than one field to be orderable"

    for submission_id, _criterion_id, request in sampled:
        pairs = _fields_of(request)
        names = [name for name, _value in pairs]
        transcript = _TRANSCRIPTS[submission_id].strip()
        marker = transcript.split()[0]  # the distinctive zxq-crate-NNN token

        last_name, last_value = pairs[-1]
        # The transcript is inside the LAST field, whole.
        assert transcript in last_value, (
            f"last prompt field {last_name!r} does not carry the submission: "
            f"{last_value!r}"
        )
        # ...and NOWHERE earlier: no earlier field carries the marker token.
        for name, value in pairs[:-1]:
            assert marker not in value, (
                f"field {name!r} carries submission material ({marker!r}) — the "
                f"submission must be placed LAST, after every invariant element"
            )
        # The fence: exactly one open and one close delimiter, transcript between them.
        assert last_value.count(UNTRUSTED_OPEN) == 1, (
            f"last field {last_name!r} does not open the untrusted block exactly once"
        )
        assert last_value.count(UNTRUSTED_CLOSE) == 1, (
            f"last field {last_name!r} does not close the untrusted block exactly once"
        )
        assert (
            last_value.index(UNTRUSTED_OPEN)
            < last_value.index(transcript)
            < last_value.index(UNTRUSTED_CLOSE)
        ), (
            f"the submission is not fenced between {UNTRUSTED_OPEN!r} and "
            f"{UNTRUSTED_CLOSE!r} in field {last_name!r} (CT-EXTRACT-06)"
        )
        # The invariant elements sit among the EARLIER fields and never in the last one.
        earlier = "\n".join(value for _name, value in pairs[:-1])
        assert _QUESTION["prompt_text"] in earlier, (
            "the question's prompt text is missing from the invariant prefix"
        )
        assert _QUESTION["reference_solution"] in earlier, (
            "the reference solution is missing from the invariant prefix"
        )
        assert _QUESTION["prompt_text"] not in last_value, (
            f"the last field {last_name!r} carries the question — invariant elements "
            f"must precede the submission"
        )


def test_tc_extract_13_template_version_is_pinned_and_echoed_in_the_request():
    """`TC-EXTRACT-13` — the module pins the template version as a non-empty string
    constant, and the assembled request echoes the unit's `work_id`: the orchestrator's
    version-bearing ID is the one the prompt and evidence row address."""
    pinned = require(EXTRACT_MODULE, TEMPLATE_VERSION, issue=ISSUE)
    AssembleRequest = require(EXTRACT_MODULE, ASSEMBLE, issue=ISSUE)

    assert isinstance(pinned, str) and pinned, (
        "the extraction prompt template version must be pinned as a non-empty string "
        "(NFR-EXTRACT-03); its exact value is #68's to fix"
    )

    unit = _unit("s401", "C1")
    request = AssembleRequest(unit)
    echoed = getattr(request, "work_id", None)
    if echoed is None and isinstance(request, dict):
        echoed = request.get("work_id")
    assert echoed == unit.work_id, (
        f"the assembled request carries work_id {echoed!r}, not the unit's "
        f"{unit.work_id!r} — a request that forks its own ID desyncs the evidence row "
        f"from the prompt (CT-EXTRACT-03's addressing clause)"
    )


def test_tc_extract_13_cross_check_template_change_invalidates_extract_units(
    tmp_data_dir,
):
    """`TC-EXTRACT-13` cross-check with `TC-ORCH-01` (unmarked, green-on-shipped):
    `compute_work_id` changes when `prompt_template_version` changes, and two whole
    enumerations over the same cohort and package that differ ONLY in the pinned
    template version produce disjoint extract-unit work-id sets — a template change
    invalidates dependent work automatically, no cleanup job."""
    # Pure half: the hash is sensitive to the template version.
    common = dict(
        run_id="run-x",
        stage=STAGE_EXTRACT,
        submission_id="SYN-001",
        criterion_id="C1",
        judge_id=None,
        package_version_id="pkg-v1",
        panel_config="[]",
        extractor_version="extract/1",
    )
    assert compute_work_id(**common, prompt_template_version="v1") != compute_work_id(
        **common, prompt_template_version="v2"
    ), "compute_work_id ignores prompt_template_version — the pin could not bind"

    # Enumerated half: same store, same package, same submission — only the pinned
    # template version differs.
    store = open_store(tmp_data_dir)
    try:
        seed_cohort(store, ("SYN-001",))
        version = seed_package(
            store, ({"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},)
        )

        def extract_ids(prompt_template_v: str) -> set[str]:
            resolved = resolve_run_config(
                edge_cfg(panel=edge_panel(3), prompt_template_v=prompt_template_v),
                CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
            )
            orchestrator = Orchestrator(store)
            run_id = orchestrator.create_run(ORCH_COHORT_ID, version, resolved)
            orchestrator.enumerate_units(run_id)
            rows = store.cohort(ORCH_COHORT_ID).query(
                "SELECT work_id FROM work_unit WHERE run_id = :r AND stage = :st",
                r=run_id, st=STAGE_EXTRACT,
            )
            return {row["work_id"] for row in rows}

        ids_v1 = extract_ids("conf-v1.0.0")
        ids_v2 = extract_ids("conf-v9.9.9")
        assert ids_v1 and ids_v2, (
            f"precondition: enumeration produced no extract units ({ids_v1!r}, "
            f"{ids_v2!r})"
        )
        assert not (ids_v1 & ids_v2), (
            "the same (submission, criterion) under two template versions shares a "
            "work_id — a template change would NOT invalidate dependent work"
        )
    finally:
        store.close()
