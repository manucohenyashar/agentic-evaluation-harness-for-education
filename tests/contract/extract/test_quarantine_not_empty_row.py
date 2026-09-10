"""`CT-EXTRACT-08` — a failed extraction quarantines and never writes an empty
`evidence` row (`TC-EXTRACT-C08`) — the safety property, in the file the plan's
"Automatable" line names.

Case of test plan §6.11.8; issue #72 (TS-65). Written ahead of #68 (`M-EXTRACT`) and
the rung-3 consumer surfaces (#78 `M-JUDGE`, #74 `M-INTEG`); registered in
`WRITTEN_AHEAD_BLOCKERS` under `"#68 extraction contract suite (TS-65)"` (the rung-2
tests) and, per node, `"#78 extraction contract suite (TS-65)"` and
`"#74 extraction contract sweep (TS-65)"` (the file mixes blockers, so the consumer
tests carry node IDs).

The clause: a unit failing three times **quarantines** rather than writing an empty
`evidence` row (FR-EXTRACT-08). Load-bearing (design §4.7, RISK-03): an empty row is
indistinguishable downstream from a student who wrote nothing — absence of evidence
and failure to extract must never arrive at `M-JUDGE` looking the same.

Halves:
1. **Three strikes, rung 2** — exactly three strikes (the shipped failure taxonomy's
   parse case), the unit `quarantined`, and the evidence count is ZERO — asserted by
   exact row ABSENCE, unit-scoped and global, because an empty row is the failure mode.
2. **The threshold is pinned, rung 2** — failing exactly twice retries rather than
   quarantines: the third attempt succeeds, the unit completes, and exactly ONE row is
   written. The case pins the boundary, not just the direction.
3. **The 2am construction, rung 2, adversarial** — the empty `evidence` row written on
   exhaustion "so the pipeline doesn't stall" goes through the REAL store silently: the
   write raises nothing, the ledger still shows the unit quarantined, and every
   row-reading oracle would still find "a row" and pass — only THIS case's absence
   oracle fires (row count != 0). That is RISK-03 made executable; the row is then
   deleted and absence re-asserted.
4. **Distinguishability at `M-JUDGE`'s input, rung 3** — two submissions, one where the
   student genuinely wrote nothing (extraction succeeds with an EMPTY span list → a row
   whose span list is empty) and one where extraction failed (no row at all, unit
   quarantined). With `M-JUDGE` real, the two assembled scoring inputs are
   distinguishable: the blank assembles from a row that exists, the failure has no
   evidence to assemble from — a refusal, or a different payload, but never the same
   bytes.
5. **Consumer sweep, rung 3** — `M-INTEG` reports `evidence_present = false` for the
   genuine blank and never sees the failed unit at all (no evidence row exists to
   verify); `M-ORCH` holds the failed unit `quarantined`, not complete, and the blank's
   unit complete.

Discriminator: an empty-row write on exhaustion turns half 3 red while the run
completes and no `FR-EXTRACT-*` case raises (they read rows; the mutant hands them
one); collapsing blank and failure into one shape at `M-JUDGE`'s input turns half 4
red; `M-INTEG` reporting the blank as evidence-present, or the failure reaching
`M-INTEG` as an empty row, turns half 5 red — while every `FR-EXTRACT-*` case, which
drives the happy path, stays green.

**Disclosed stand-ins** (suite register, `_doubles.py`): D1 (the blank is the recorded
empty-span reply — the reply format is the disclosed stand-in), D3 (document seeding),
D4-adjacent (the striking and sequenced provider stubs are the TS-26 failure file's
instrument, reused: the shipped `RecordedFixtureProvider` records successes only), D6
(`ScoringWorker`/`assemble` resolved under #78, `IntegrityGate` under #74 — no new
consumer symbol invented), D8 (the blank row's `spans` key). The 2am write in half 3
uses the store's own columns — the landed `evidence` DDL, plus the row-bet columns
(`payload`, `resolved_build`) once they exist; on the landed schema the mutant is the
empty row, after the row bet it is a row with an empty span payload — both are the
clause's named violations. **Isolation**: rung 2 (halves 1-3) / rung 3 (halves 4-5) —
real store, real ledger, real blob directory, the provider boundary the only fake.
"""

from __future__ import annotations

from typing import Any

import pytest

from aeh.orch import STAGE_EXTRACT, Orchestrator
from aeh.prov import MalformedResponseError
from aeh.store import open_store
from tests.support.conf_builders import edge_panel
from tests.support.extract_vocabulary import (
    WORKER,
    extractor_ref,
    sampling_params,
    span_completion,
)
from tests.support.impl import EXTRACT_MODULE, INTEG_MODULE, JUDGE_MODULE, require
from tests.support.integ_vocabulary import ExtractionView
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_package
from tests.contract.extract._doubles import (
    World,
    build_markdown,
    evidence_rows,
    make_world,
    payload_bytes,
    require_extract_surface,
    resolved_config,
    seed_document,
)

pytestmark = [pytest.mark.contract]

_MARKDOWN = build_markdown(
    "The buffer overflowed because the index was never bounds-checked.\n"
)
#: The genuine blank: a submission whose untrusted block is empty — the student wrote
#: nothing. The blankness the consumer sees is carried by the recorded EMPTY span list
#: (D1), which is the designed representation of "wrote nothing".
_BLANK_MARKDOWN = build_markdown("")
_CRITERIA = [{"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"}]
_SPANS = [
    {
        "start": 41,
        "end": 96,
        "text": "The buffer overflowed because the index was never bounds-checked.",
        "region_kind": "transcribed_text",
    }
]


class _StrikingProvider:
    """Every call raises the shipped parse-failure error — the failure M-PROV's
    Requires row names, which is what makes the three-strike quarantine well-defined.
    Counts the strikes (the TS-26 failure file's instrument, D4-adjacent)."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        self.calls += 1
        raise MalformedResponseError(
            "extraction reply is not parseable span output (fixture: strike)"
        )


class _SequencedProvider:
    """Fails exactly `failures` times, then delegates to a real
    `RecordedFixtureProvider` — the instrument the boundary test (exactly two
    failures, then success) needs."""

    def __init__(self, inner: Any, failures: int) -> None:
        self._inner = inner
        self._failures = failures
        self.calls = 0

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        self.calls += 1
        if self.calls <= self._failures:
            raise MalformedResponseError(
                "extraction reply is not parseable span output (fixture: strike)"
            )
        return self._inner.complete(prompt, model_ref, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _unit_status(store: Any, work_id: str) -> str:
    rows = store.cohort(ORCH_COHORT_ID).query(
        "SELECT status FROM work_unit WHERE work_id = :w", w=work_id
    )
    assert rows, f"work_unit {work_id} vanished from the ledger"
    return rows[0]["status"]


def _evidence_count(store: Any, work_id: str | None = None) -> int:
    sql = "SELECT COUNT(*) AS n FROM evidence"
    params: dict[str, Any] = {}
    if work_id is not None:
        sql += " WHERE work_id = :w"
        params["w"] = work_id
    return store.cohort(ORCH_COHORT_ID).query(sql, **params)[0]["n"]


def _two_submission_world(tmp_data_dir: Any, make_fixture_provider: Any) -> World:
    """One cohort, two submissions: `SYN-001` the genuine blank, `SYN-002` a written
    answer whose extraction will fail. `make_world` seeds one submission, so this
    composes the same shipped seeders by hand."""
    store = open_store(tmp_data_dir)
    seed_cohort(store, ("SYN-001", "SYN-002"))
    version = seed_package(store, _CRITERIA, package_id="pkg-ct-c08-two")
    seed_document(store, "SYN-001", _BLANK_MARKDOWN, "doc-ct-c08-blank")
    seed_document(store, "SYN-002", _MARKDOWN, "doc-ct-c08-failed")
    return World(
        store=store,
        provider=make_fixture_provider(),
        version=version,
        doc_id="doc-ct-c08-blank",
        markdown=_BLANK_MARKDOWN,
    )


def test_tc_extract_c08_three_failures_quarantine_and_never_write_an_evidence_row(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C08` half 1 — three strikes: the unit quarantines and the evidence
    count is ZERO, unit-scoped and global (an empty row is the failure mode)."""
    require(EXTRACT_MODULE, issue="#68")
    require_extract_surface()
    world = make_world(tmp_data_dir, make_fixture_provider, markdown=_MARKDOWN,
                       criteria=_CRITERIA)
    try:
        orchestrator = Orchestrator(world.store)
        run_id = orchestrator.create_run(
            ORCH_COHORT_ID, world.version, resolved_config(edge_panel(1))
        )
        (unit,) = orchestrator.lease("w-extract", STAGE_EXTRACT, 1)
        Worker = require(EXTRACT_MODULE, WORKER, issue="#68")
        provider = _StrikingProvider()
        Worker(world.store, provider, extractor_ref()).process(unit)

        assert provider.calls == 3, (
            f"TC-EXTRACT-C08: precondition — the unit must strike exactly three "
            f"times, saw {provider.calls} calls"
        )
        assert _unit_status(world.store, unit.work_id) == "quarantined", (
            "TC-EXTRACT-C08: a thrice-failing unit must quarantine"
        )
        assert _evidence_count(world.store, unit.work_id) == 0, (
            "TC-EXTRACT-C08: an evidence row was written for a quarantined unit — an "
            "empty row is indistinguishable downstream from a student who wrote "
            "nothing, which is exactly the violation"
        )
        assert _evidence_count(world.store) == 0, (
            "TC-EXTRACT-C08: the failed extraction left evidence rows behind"
        )
    finally:
        world.close()


def test_tc_extract_c08_exactly_two_failures_retry_rather_than_quarantine(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C08` half 2 — the threshold is pinned: exactly two failures and the
    unit RETRIES, the third attempt succeeds, the unit completes, and exactly ONE row
    is written."""
    require(EXTRACT_MODULE, issue="#68")
    require_extract_surface()
    world = make_world(tmp_data_dir, make_fixture_provider, markdown=_MARKDOWN,
                       criteria=_CRITERIA)
    try:
        orchestrator = Orchestrator(world.store)
        run_id = orchestrator.create_run(
            ORCH_COHORT_ID, world.version, resolved_config(edge_panel(1))
        )
        (unit,) = orchestrator.lease("w-extract", STAGE_EXTRACT, 1)
        AssembleRequest = require(EXTRACT_MODULE, "assemble_request", issue="#68")
        PromptFields = require(EXTRACT_MODULE, "prompt_fields", issue="#68")
        Worker = require(EXTRACT_MODULE, WORKER, issue="#68")
        model_ref = extractor_ref()
        request = AssembleRequest(unit, store=world.store)
        world.provider.record(
            PromptFields(request), model_ref, sampling_params(),
            span_completion(_SPANS, build_id="ct-c08-build"),
        )
        sequenced = _SequencedProvider(world.provider, failures=2)
        Worker(world.store, sequenced, model_ref).process(unit)

        assert sequenced.calls == 3, (
            f"TC-EXTRACT-C08: precondition — two failures then one success is three "
            f"calls, saw {sequenced.calls}"
        )
        assert _unit_status(world.store, unit.work_id) != "quarantined", (
            "TC-EXTRACT-C08: two failures quarantined the unit — the threshold is "
            "pinned at three, and this boundary is the case's own second oracle"
        )
        rows = evidence_rows(world.store, run_id)
        assert len(rows) == 1, (
            f"TC-EXTRACT-C08: the retried unit wrote {len(rows)} evidence rows — "
            f"exactly one is the contract"
        )
    finally:
        world.close()


def test_tc_extract_c08_the_2am_empty_row_write_is_silent_but_turns_this_case_red(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C08` half 3, adversarial — the empty-row write a developer reaches
    for at 2am ("so the pipeline doesn't stall and the criterion still gets a verdict")
    goes through the real store SILENTLY: nothing raises, the ledger keeps the unit
    quarantined, and every row-reading oracle would still pass — only this case's
    absence oracle fires. RISK-03, made executable."""
    require(EXTRACT_MODULE, issue="#68")
    require_extract_surface()
    world = make_world(tmp_data_dir, make_fixture_provider, markdown=_MARKDOWN,
                       criteria=_CRITERIA)
    try:
        orchestrator = Orchestrator(world.store)
        orchestrator.create_run(
            ORCH_COHORT_ID, world.version, resolved_config(edge_panel(1))
        )
        (unit,) = orchestrator.lease("w-extract", STAGE_EXTRACT, 1)
        Worker = require(EXTRACT_MODULE, WORKER, issue="#68")
        Worker(world.store, _StrikingProvider(), extractor_ref()).process(unit)
        assert _unit_status(world.store, unit.work_id) == "quarantined", (
            "TC-EXTRACT-C08: precondition — the unit must be quarantined"
        )
        assert _evidence_count(world.store, unit.work_id) == 0, (
            "TC-EXTRACT-C08: precondition — the worker wrote no row"
        )

        # The 2am write, through the REAL store, in the schema's own columns: the
        # landed `evidence` DDL takes the bare empty row; once the row bet lands
        # (`payload`, `resolved_build`) the same write carries an empty span payload.
        # Both are the clause's named violations.
        handle = world.store.cohort(ORCH_COHORT_ID)
        columns = {r["name"] for r in handle.query("PRAGMA table_info(evidence)")}
        with handle.transaction() as tx:
            if {"payload", "resolved_build"} <= columns:
                tx.execute(
                    "INSERT INTO evidence (evidence_id, work_id, payload, "
                    "resolved_build) VALUES (:e, :w, :p, :b)",
                    e="ev-ct-c08-2am", w=unit.work_id, p="[]", b="sha256:2am",
                )
            else:
                tx.execute(
                    "INSERT INTO evidence (evidence_id, work_id) VALUES (:e, :w)",
                    e="ev-ct-c08-2am", w=unit.work_id,
                )
        # The write raised nothing, the run did not stall, the unit still shows
        # quarantined — and every FR case that reads a row now finds one.
        assert _unit_status(world.store, unit.work_id) == "quarantined", (
            "TC-EXTRACT-C08: the mutant write un-quarantined the unit"
        )
        assert _evidence_count(world.store, unit.work_id) != 0, (
            "TC-EXTRACT-C08: the absence oracle did NOT fire on the mutant row — "
            "this case cannot catch the 2am write, which is the safety property "
            "failing silently (RISK-03)"
        )
        # Cleanup: the designed state is restored, and absence is re-asserted.
        with handle.transaction() as tx:
            tx.execute("DELETE FROM evidence WHERE evidence_id = :e", e="ev-ct-c08-2am")
        assert _evidence_count(world.store, unit.work_id) == 0, (
            "TC-EXTRACT-C08: cleanup failed — the mutant row survived"
        )
    finally:
        world.close()


def test_tc_extract_c08_the_blank_and_the_failure_are_distinguishable_at_m_judge(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C08` half 4, rung 3 — the clause's stated reason for existing: a
    genuine blank (a row whose span list is empty) and an extraction failure (NO row,
    unit quarantined) arrive at `M-JUDGE`'s input distinguishable, under every
    admissible `assemble` behaviour."""
    require(JUDGE_MODULE, "ScoringWorker", "assemble", issue="#78")
    require_extract_surface()
    world = _two_submission_world(tmp_data_dir, make_fixture_provider)
    try:
        orchestrator = Orchestrator(world.store)
        run_id = orchestrator.create_run(
            ORCH_COHORT_ID, world.version, resolved_config(edge_panel(1))
        )
        units = orchestrator.lease("w-extract", STAGE_EXTRACT, 2)
        blank_unit = next(u for u in units if u.submission_id == "SYN-001")
        failed_unit = next(u for u in units if u.submission_id == "SYN-002")
        AssembleRequest = require(EXTRACT_MODULE, "assemble_request", issue="#68")
        PromptFields = require(EXTRACT_MODULE, "prompt_fields", issue="#68")
        Worker = require(EXTRACT_MODULE, WORKER, issue="#68")
        model_ref = extractor_ref()
        # The genuine blank: extraction SUCCEEDS with an empty span list.
        world.provider.record(
            PromptFields(AssembleRequest(blank_unit, store=world.store)),
            model_ref, sampling_params(),
            span_completion([], build_id="ct-c08-build"),
        )
        Worker(world.store, world.provider, model_ref).process(blank_unit)
        # The failure: every call strikes.
        Worker(world.store, _StrikingProvider(), model_ref).process(failed_unit)

        blank_rows = evidence_rows(world.store, run_id, submission_id="SYN-001")
        failed_rows = evidence_rows(world.store, run_id, submission_id="SYN-002")
        assert len(blank_rows) == 1, (
            f"TC-EXTRACT-C08: precondition — the blank wrote {len(blank_rows)} rows"
        )
        assert len(failed_rows) == 0, (
            "TC-EXTRACT-C08: the failure wrote a row — the violation is already "
            "present in the store"
        )
        import json as _json

        stored = _json.loads(payload_bytes(blank_rows[0]["payload"]).decode("utf-8"))
        assert "spans" in stored and stored["spans"] == [], (
            f"TC-EXTRACT-C08: the blank's row carries {stored!r} — the designed "
            f"representation of wrote-nothing is a row with an EMPTY span list (D8)"
        )
        assert _unit_status(world.store, failed_unit.work_id) == "quarantined", (
            "TC-EXTRACT-C08: precondition — the failed unit is quarantined"
        )

        # Distinguishability at M-JUDGE's input: the blank's score arm assembles from
        # a row that exists; the failure has no evidence to assemble from. A refusal
        # is distinguishable; so is a different payload. The SAME bytes are not.
        Assemble = require(JUDGE_MODULE, "assemble", issue="#78")
        arms = world.store.cohort(ORCH_COHORT_ID).query(
            "SELECT submission_id, work_id, judge_id FROM work_unit "
            "WHERE run_id = :r AND stage = 'score' AND criterion_id = :c "
            "ORDER BY submission_id, judge_id",
            r=run_id, c="C1",
        )
        blank_arm = next(a for a in arms if a["submission_id"] == "SYN-001")
        failed_arm = next(a for a in arms if a["submission_id"] == "SYN-002")
        blank_payload = payload_bytes(Assemble(blank_arm))
        try:
            failed_payload = payload_bytes(Assemble(failed_arm))
        except Exception:
            failed_payload = None  # a refusal is the clearest distinction there is
        assert failed_payload is None or failed_payload != blank_payload, (
            "TC-EXTRACT-C08: the genuine blank and the extraction failure arrive at "
            "M-JUDGE's input INDISTINGUISHABLE — absence of evidence and failure to "
            "extract look the same, which is the violation the clause exists for"
        )
    finally:
        world.close()


def test_tc_extract_c08_m_integ_sees_the_blank_never_the_failure_m_orch_holds_it(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C08` half 5, rung 3 — the consumer sweep: `M-INTEG` reports
    `evidence_present = false` for the genuine blank and never sees the failed unit at
    all (no evidence row exists to verify); `M-ORCH` holds the failed unit
    `quarantined`, not complete, and the blank's unit complete."""
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#74")
    require_extract_surface()
    world = _two_submission_world(tmp_data_dir, make_fixture_provider)
    try:
        orchestrator = Orchestrator(world.store)
        run_id = orchestrator.create_run(
            ORCH_COHORT_ID, world.version, resolved_config(edge_panel(1))
        )
        units = orchestrator.lease("w-extract", STAGE_EXTRACT, 2)
        blank_unit = next(u for u in units if u.submission_id == "SYN-001")
        failed_unit = next(u for u in units if u.submission_id == "SYN-002")
        AssembleRequest = require(EXTRACT_MODULE, "assemble_request", issue="#68")
        PromptFields = require(EXTRACT_MODULE, "prompt_fields", issue="#68")
        Worker = require(EXTRACT_MODULE, WORKER, issue="#68")
        model_ref = extractor_ref()
        world.provider.record(
            PromptFields(AssembleRequest(blank_unit, store=world.store)),
            model_ref, sampling_params(),
            span_completion([], build_id="ct-c08-build"),
        )
        Worker(world.store, world.provider, model_ref).process(blank_unit)
        Worker(world.store, _StrikingProvider(), model_ref).process(failed_unit)

        # M-INTEG's verdict for the genuine blank: no evidence present — never True.
        gate = IntegrityGate(
            world.store.cohort(ORCH_COHORT_ID),
            world.store.blobs(),
            ExtractionView(spans=()),
        )
        signals = gate.verify(run_id, "SYN-001", "C1")
        assert signals.evidence_present is False, (
            "TC-EXTRACT-C08: M-INTEG reported evidence_present="
            f"{signals.evidence_present!r} for a submission whose span list is empty "
            "— a genuine blank must never read as evidence-present"
        )
        # The failed unit never reaches M-INTEG: there is no evidence row to verify.
        assert evidence_rows(world.store, run_id, submission_id="SYN-002") == [], (
            "TC-EXTRACT-C08: the failed unit left evidence for M-INTEG to see — the "
            "failure reached the consumer as an empty row"
        )
        # ...and M-ORCH holds it quarantined, not complete; the blank's unit completed.
        assert _unit_status(world.store, failed_unit.work_id) == "quarantined", (
            "TC-EXTRACT-C08: M-ORCH does not hold the failed unit quarantined — "
            "a failure that completes is indistinguishable from a blank"
        )
        assert _unit_status(world.store, blank_unit.work_id) != "quarantined", (
            "TC-EXTRACT-C08: the blank's unit quarantined — wrote-nothing is not a "
            "failure"
        )
    finally:
        world.close()
