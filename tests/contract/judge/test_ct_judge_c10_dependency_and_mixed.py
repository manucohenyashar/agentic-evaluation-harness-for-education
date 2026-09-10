"""`TC-JUDGE-C10` — dependency evidence is spans-only, and the mixed question leaks
neither the selection nor the correctness (§6.11.10).

`CT-JUDGE-10` (data): *"For a dependent criterion, assert the request carries the
parent's **extraction evidence** and **no parent verdict** — asserted structurally,
since `dependency_evidence` is schema-typed to spans only and cannot represent a
verdict. Then the `mixed`-question case, which is the one most easily missed: a judged
criterion's request carries **neither** the deterministic criterion's selection **nor**
its correctness. Assert both absences over the assembled value. A leaked correctness
signal makes the panel's judgment a function of the answer key."* (plan §6.11.10,
verbatim)

Two limbs, over REAL assemblies:

1. **the dependent criterion** — a parent/child pair driven through a real run
   (`C1` declares `dependencies=("C0",)`): the child's assembled request carries
   the parent's extraction evidence, VERBATIM (the entry's spans equal the
   parent's own assembled evidence — forwarded, never re-typed), and **no parent
   verdict** twice over: structurally, `DependencyEvidence` declares exactly
   `(criterion_id, spans)` — a schema with no field for a verdict, so one is not
   merely unfilled but unrepresentable (the closed-schema TypeError is the
   machine check) — and dynamically, after the parent's verdict EXISTS in the
   ledger (persisted with a distinctive self-confidence sentinel), the child's
   request carries that sentinel nowhere;
2. **the mixed question** — one question anchored by a judged criterion `J1` and
   a deterministic criterion `M1` beside it: the deterministic pass runs for real
   (the answer key is looked up, the selections scored, the `criterion_score`
   row written), the judged drive runs beside it, and every assembled request for
   the judged criterion carries NEITHER the selection (the sentinel option id)
   NOR the correctness (the deterministic band constants) — with both sources
   proven LIVE in the store first, so the absences mean something.

Cross-references, not duplicates: `TC-DET-C12` (`tests/contract/det/
test_ct_det_key_material.py`, #90) owns the key-unreachable clause and DISCLOSES
that its sentinel scan runs over the work ledger because the judge-request surface
had not landed when it shipped — the mixed limb below is exactly the assembled-value
form that disclosure named, over the request `dispatch` sends. `TC-ORCH-C07` owns
the enumeration shape (an mcq criterion generates no judge-bound unit at all).
`TC-JUDGE-05`/`TC-JUDGE-06` are the shipped whitelist cases this file's
type-level rejections extend to the dependency entry. `CT-EXTRACT-04` is the
extract-side sibling (`tests/contract/extract/test_ct_extract_c04_dependency_request.py`).

Isolation: rung 2 — real store, real package, real workers, the real deterministic
evaluator; the socket guard is autouse and the completions come from the recorded
fixture provider.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from aeh.det import DeterministicEvaluator
from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.contract.judge._drive import (
    BANDS,
    PANEL_REFS,
    add_bands,
    drive_extract,
    judge_units,
    lease_score_units,
    seed_world,
)
from tests.support.impl import JUDGE_MODULE, require
from tests.support.judge_vocabulary import string_leaves
from tests.support.det_vocabulary import seed_answer_region
from tests.support.orch_run import ORCH_COHORT_ID, seed_documents, seed_run

pytestmark = [pytest.mark.contract]

#: The story that owns the request schema (`M-JUDGE` is complete — #78/#79/#80/#81).
ISSUE = "#78"

#: The parent's verdict is persisted under this distinctive self-confidence —
#: the sentinel the child request must not carry. Distinctive enough that no
#: declared band, ordinal or descriptor carries it by accident.
_VERDICT_SENTINEL = 0.91337

#: The selection's sentinel — the key option's id, `TC-DET-C12`'s own sentinel,
#: reused so the two files' scans read as one boundary at two surfaces.
_SELECTION_SENTINEL = "ZQ7"

#: The deterministic outcome's band constants (`aeh.det` writes these verbatim into
#: `criterion_score`): the correctness markers the judged request must not carry.
_DETERMINISTIC_BANDS = ("correct", "incorrect")

_MIXED_CRITERIA = [
    {"criterion_id": "J1", "kind": "open", "scoring_model": "atomic",
     "question_id": "Q1", "band_count": 2},
    {"criterion_id": "M1", "kind": "mcq", "question_id": "Q1"},
]

#: The deterministic criterion's declared bands carry the labels `aeh.det` writes
#: (its `BAND_CORRECT`/`BAND_INCORRECT` constants resolve through the package's
#: declared band labels — the same shape the shipped `TC-DET-C12` fixture uses).
#: The judged criterion's bands stay the default set, so the correctness markers
#: below are absent from its request by every LEGITIMATE route.
_MIXED_MCQ_BANDS = (
    ("incorrect", 0.0, "the key was missed"),
    ("correct", 1.0, "the key was matched"),
)

_DEPENDENT_CRITERIA = [
    {"criterion_id": "C0", "kind": "open", "scoring_model": "atomic",
     "band_count": 2},
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic",
     "dependencies": ("C0",), "band_count": 2},
]


def _leaves(request: Any) -> str:
    return "\n".join(text for _path, text in string_leaves(request))


def _criterion_unit(units: Any, criterion_id: str) -> Any:
    return next(unit for unit in units if unit.criterion_id == criterion_id)


def test_tc_judge_c10_the_child_request_carries_parent_evidence_and_no_parent_verdict(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C10` limb 1 (`CT-JUDGE-10`, the dependent criterion, rung 2, P0) —
    the child's assembled request carries the parent's extraction evidence VERBATIM
    and no parent verdict: the schema cannot represent one (the fields are exactly
    `(criterion_id, spans)` and the construction door refuses more), and the parent's
    persisted verdict rides nowhere in the child's bytes."""
    store = open_store(tmp_data_dir)
    try:
        provider = make_fixture_provider()
        orchestrator, run_id, version = seed_world(
            store, criterion_specs=_DEPENDENT_CRITERIA
        )
        drive_extract(orchestrator, store, provider)
        units = lease_score_units(orchestrator)
        assert len(units) == 2, (
            f"fixture bug: the drive leased {len(units)} score units — the limb "
            "is a parent and a dependent child, one judged pair each"
        )
        # The parent's verdict is made REAL first: judged, persisted, and read back.
        parent_unit = _criterion_unit(units, "C0")
        child_unit = _criterion_unit(units, "C1")
        judged = judge_units(
            store, make_fixture_provider(), [parent_unit],
            self_confidence=_VERDICT_SENTINEL,
        )
        assert judged == 1, "fixture bug: the parent's verdict was not persisted"
        parent_verdicts = store.cohort(ORCH_COHORT_ID).query(
            "SELECT v.self_confidence FROM verdict v JOIN work_unit w "
            "ON w.work_id = v.work_id WHERE w.run_id = :r AND w.criterion_id = 'C0'",
            r=run_id,
        )
        assert parent_verdicts and any(
            row["self_confidence"] is not None
            and abs(row["self_confidence"] - _VERDICT_SENTINEL) < 1e-9
            for row in parent_verdicts
        ), (
            "fixture bug: the parent's verdict row does not carry the sentinel — "
            "the child-request absence below would be vacuous"
        )

        # The child's request, assembled AFTER the parent's verdict exists.
        refs_by_build = {ref.build_id: ref for ref in PANEL_REFS}
        payload_fn = require(JUDGE_MODULE, "prompt_fields", issue=ISSUE)
        child_request = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, None, refs_by_build[child_unit.judge]
        ).assemble(child_unit)
        parent_request = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, None, refs_by_build[parent_unit.judge]
        ).assemble(parent_unit)

        # The parent's extraction evidence rides VERBATIM: one entry, the parent's
        # id, its spans exactly as the parent's own request carried them.
        DependencyEvidence = require(JUDGE_MODULE, "DependencyEvidence", issue=ISSUE)
        entries = child_request.dependency_evidence
        assert len(entries) == 1 and entries[0].criterion_id == "C0", (
            f"the child's request carries {len(entries)} dependency entr(y/ies) — "
            "the parent's extracted evidence is what the dependency channel moves "
            "(CT-JUDGE-10, FR-JUDGE-14)"
        )
        assert entries[0].spans == parent_request.evidence, (
            "the child's dependency spans differ from the parent's own extracted "
            "evidence — spans travel VERBATIM, never re-typed (CT-JUDGE-10)"
        )

        # Structurally: no verdict is REPRESENTABLE in the dependency channel —
        # the schema carries exactly (criterion_id, spans), and the construction
        # door refuses a verdict-shaped kwarg.
        field_names = [field.name for field in dataclasses.fields(DependencyEvidence)]
        assert field_names == ["criterion_id", "spans"], (
            f"DependencyEvidence declares {field_names} — the schema is spans-only "
            "by construction, so a parent's band is not merely unfilled but "
            "unrepresentable (CT-JUDGE-10, FR-JUDGE-14)"
        )
        with pytest.raises(TypeError) as raised:
            DependencyEvidence(
                criterion_id="C0", spans=(), verdict_band="secure"
            )
        assert "verdict_band" in str(raised.value), (
            f"the dependency construction refused a verdict field but its message "
            f"names nothing: {raised.value!r} — the closed-schema rejection must "
            "name what it refused (CT-JUDGE-10)"
        )

        # And dynamically: the parent's persisted verdict appears nowhere in the
        # child's request — every verdict then existing, still nothing leaked.
        child_bytes = _leaves(child_request)
        assert "0.91337" not in child_bytes, (
            "the child's request carries the parent's persisted self-confidence — "
            "a parent verdict reached the dependency channel, which is spans-only "
            "(CT-JUDGE-10, FR-JUDGE-14)"
        )
    finally:
        store.close()


def test_tc_judge_c10_a_judged_request_carries_no_deterministic_signal(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C10` limb 2 (`CT-JUDGE-10`, the mixed-question case, rung 2, P0) —
    a judged criterion anchored to the SAME question as a deterministic one: the
    deterministic pass runs for real (key looked up, selections scored, rows
    written), the judged drive runs beside it, and every assembled request for the
    judged criterion carries neither the selection nor the correctness — with both
    sources proven live first, so the absences are over real signals."""
    store = open_store(tmp_data_dir)
    try:
        provider = make_fixture_provider()
        submissions = ("SYN-001", "SYN-002")
        # The mixed world, banded selectively (`seed_world`'s `bands` parameter
        # would put the mcq labels on the judged criterion too): J1 carries the
        # default set, M1 the deterministic labels det's constants resolve to.
        orchestrator, run_id, version = seed_run(
            store, submissions=submissions, criteria=_MIXED_CRITERIA
        )
        add_bands(store, version, "J1", BANDS)
        add_bands(store, version, "M1", _MIXED_MCQ_BANDS)
        seed_documents(store, submissions)
        orchestrator.enumerate_units(run_id)
        assert orchestrator.start(run_id) == "running", (
            "fixture bug: the mixed run did not start"
        )
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        catalog.set_mcq_options(version, "M1", [
            (_SELECTION_SENTINEL, "the sentinel option"),
            ("OPT-B", "Option B"),
            ("OPT-C", "Option C"),
        ])
        catalog.set_answer_key(version, "M1", (_SELECTION_SENTINEL,))
        for submission_id in submissions:
            seed_answer_region(
                store, ORCH_COHORT_ID, f"doc-{submission_id}", "Q1",
                selection=_SELECTION_SENTINEL,
            )

        # The deterministic pass, for real: the key is looked up and every
        # selection scored against it.
        report = DeterministicEvaluator(store).evaluate_cohort(run_id)
        assert report.evaluations == len(submissions), (
            f"fixture bug: the deterministic pass evaluated {report.evaluations} "
            f"selection(s) — both submissions' marks must be scored for the "
            "correctness signal below to be live"
        )

        # The judged drive beside it, then the assembled requests — AFTER verdicts
        # exist, the state where a carry-over would tempt.
        drive_extract(orchestrator, store, provider)
        units = lease_score_units(orchestrator)
        assert len(units) == len(submissions), (
            f"fixture bug: the drive leased {len(units)} score unit(s) — the mcq "
            "criterion enumerates no judge-bound unit, so the judged criterion's "
            "units are the sweep"
        )
        judge_units(store, provider, units)
        refs_by_build = {ref.build_id: ref for ref in PANEL_REFS}
        payload_fn = require(JUDGE_MODULE, "prompt_fields", issue=ISSUE)
        for unit in units:
            request = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
                store, None, refs_by_build[unit.judge]
            ).assemble(unit)
            leaves = _leaves(request)
            assert _SELECTION_SENTINEL not in leaves, (
                f"{unit.work_id[:12]}: the judged request carries the deterministic "
                "criterion's selection — a judged prompt that names the mcq "
                "selection grades beside the key (CT-JUDGE-10)"
            )
            for marker in _DETERMINISTIC_BANDS:
                assert marker not in leaves, (
                    f"{unit.work_id[:12]}: the judged request carries the "
                    f"deterministic outcome {marker!r} — a leaked correctness "
                    "signal makes the panel's judgment a function of the answer "
                    "key (CT-JUDGE-10)"
                )

        # The sources were live: the selection read and the correctness row both
        # exist in the store the requests were assembled from.
        handle = store.cohort(ORCH_COHORT_ID)
        regions = handle.query(
            "SELECT selection FROM document_region WHERE element_kind = 'Q1' "
            "AND selection IS NOT NULL"
        )
        assert [row["selection"] for row in regions] == \
            [_SELECTION_SENTINEL] * len(submissions), (
            f"fixture bug: the answer regions carry "
            f"{[row['selection'] for row in regions]} — the selection sentinel "
            "must be live for the request-level absence to mean anything"
        )
        scores = handle.query(
            "SELECT band FROM criterion_score WHERE criterion_id = 'M1'"
        )
        assert len(scores) == len(submissions) and all(
            row["band"] == "correct" for row in scores
        ), (
            f"fixture bug: the deterministic pass wrote {len(scores)} row(s) "
            f"{[row['band'] for row in scores]} — the correctness markers must be "
            "live in the ledger the judged requests were assembled beside"
        )

        # And structurally: the request schema itself cannot represent either
        # signal — no field admits a selection, a correctness or a key.
        ScoringRequest = require(JUDGE_MODULE, "ScoringRequest", issue=ISSUE)
        schema_fields = [field.name for field in dataclasses.fields(ScoringRequest)]
        assert schema_fields == ["work_id", "criterion", "question", "evidence",
                                 "dependency_evidence", "submission",
                                 "submission_text"], (
            f"the request schema declares {schema_fields} — the whitelist is the "
            "structural half: there is no field for a deterministic criterion's "
            "selection or correctness, so a leak is not merely filtered but "
            "unrepresentable (CT-JUDGE-10)"
        )
        assert not any(
            token in name for name in schema_fields
            for token in ("selection", "correct", "answer_key", "verdict")
        ), (
            f"a request-schema field name admits a deterministic signal: "
            f"{[n for n in schema_fields if any(t in n for t in ('selection', 'correct', 'answer_key', 'verdict'))]} "
            "— the mixed-question leak the clause refuses would have a home "
            "(CT-JUDGE-10)"
        )

        # The scanner's teeth: the same leaf scan catches the correctness marker
        # planted in a request's leaves, so the absences above are over a scan
        # that can fire.
        from tests.contract.judge._drive import offline_request

        poisoned = offline_request(
            criterion_text="the deterministic outcome is correct",
        )
        assert "correct" in _leaves(poisoned), (
            "fixture bug: the leaf scan cannot see a planted correctness marker — "
            "the absences above would be vacuous"
        )
    finally:
        store.close()