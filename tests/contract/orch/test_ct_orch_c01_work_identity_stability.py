"""`TC-ORCH-C01` — the contract half of `CT-ORCH-01` (§6.11.7): a `work_id` is a pure
function of its nine declared inputs, and the enumeration that mints them is pure too —
**no unrelated ledger state reaches the id**.

What the shipped unit case already covers (`tests/unit/orch/test_work_id.py`, §5.7's
block form) and what this file therefore does NOT re-assert: the committed-reference
golden, the nine-input perturbation sweep, the panel-order and null-judge variants, the
cross-process/`PYTHONHASHSEED` recompute, and a clean double enumeration. Step 4's second
enumeration runs against an **untouched** store — the limb it leaves open is the one a
real dispatcher exercises: re-enumerating a live run whose store has, since the first
enumeration, grown unrelated cohorts, unrelated packages, unrelated runs, new documents
and progress mutations on the run's own rows.

`CT-ORCH-01`'s wording is the oracle: "the work_id is a pure function of the run id,
stage, submission id, criterion id, judge id, package version id, panel config, prompt
template version and extractor version — and of nothing else." Of nothing else is what
this file makes falsifiable: every perturbation below touches ledger state that is NOT
one of the nine inputs, and the run's identities must survive all of them byte-identically.
A counterexample — an enumeration that reads the cohort's `ingest_status`, the package
tier's row counts, the documents, or another run's presence — would mint different ids
for the same declared inputs and strand every result recorded before the change.
"""

from __future__ import annotations

import pytest

from aeh.orch import Orchestrator
from aeh.store import open_store
from tests.support.orch_run import ORCH_COHORT_ID, orch_cfg, seed_cohort, seed_document, seed_package, seed_run

pytestmark = [pytest.mark.contract]

_SUBMISSIONS = ("SYN-001", "SYN-002", "SYN-003")
_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},
    {"criterion_id": "C2", "kind": "mcq"},
)
_PLAIN_TEXT = (
    "The evidence supports the conclusion, with the caveats noted in section "
    "two of the cited report."
)


def _sorted_ids(report: object) -> list[str]:
    ids = sorted(report.work_ids)  # type: ignore[attr-defined]
    assert len(set(ids)) == len(ids), (
        "the enumeration produced duplicate work_ids — the uniqueness invariant "
        "CT-ORCH-01's purity rests on is already broken"
    )
    return ids


def test_tc_orch_c01_enumeration_identity_survives_unrelated_state(tmp_data_dir):
    """The C01 limb the unit case leaves open: enumerate a run, grow the store with
    state none of the nine inputs carries, re-enumerate — the id set is byte-identical
    and the ledger gained no duplicate rows."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, version = seed_run(
            store,
            submissions=_SUBMISSIONS,
            criteria=_CRITERIA,
        )
        first = _sorted_ids(orchestrator.enumerate_units(run_id))

        # --- the perturbations, each unrelated to the nine declared inputs ---------
        # 1. An unrelated cohort, with its own submissions and a document.
        seed_cohort(store, ("OTHER-001",), cohort_id="c-2026-7B-other")
        seed_document(
            store, "OTHER-001", "unrelated cohort prose", cohort_id="c-2026-7B-other"
        )
        # 2. An unrelated package version in its own package tier.
        other_version = seed_package(
            store,
            ({"criterion_id": "X1", "kind": "open", "scoring_model": "holistic"},),
            package_id="pkg-unrelated",
        )
        # 3. An unrelated run over that cohort and package, enumerated against the
        #    same ledger. Built from the run-row surface directly (the same call
        #    `seed_run` makes), because `seed_run` seeds the default cohort by
        #    construction — this run must live on the UNRELATED one.
        other_orchestrator = Orchestrator(store)
        other_run_id = other_orchestrator.create_run(
            "c-2026-7B-other", other_version, orch_cfg("edge-local")
        )
        other_orchestrator.enumerate_units(other_run_id)
        # 4. Documents added under the run's own cohort AFTER the first enumeration —
        #    content the assembler resolves later, never an id input.
        for submission_id in _SUBMISSIONS:
            seed_document(store, submission_id, _PLAIN_TEXT)
        # 5. The run's own progress mutated: one unit leased and one driven done —
        #    ledger rows whose status is explicitly not an id input.
        handle = store.cohort(ORCH_COHORT_ID)
        units = handle.query(
            "SELECT work_id FROM work_unit WHERE run_id = :r ORDER BY work_id LIMIT 2",
            r=run_id,
        )
        assert len(units) == 2, "the run enumerated too few units to perturb"
        with handle.transaction() as tx:
            tx.execute(
                "UPDATE work_unit SET status = 'leased' WHERE work_id = :w",
                w=units[0]["work_id"],
            )
            tx.execute(
                "UPDATE work_unit SET status = 'done' WHERE work_id = :w",
                w=units[1]["work_id"],
            )

        second = _sorted_ids(Orchestrator(store).enumerate_units(run_id))

        assert second == first, (
            "re-enumeration after unrelated state grew a different id set — some "
            "unrelated ledger surface (another cohort, another package, another run, "
            "document rows, or this run's own progress) is leaking into the identity "
            "hash, and NFR-ORCH-05's purity is a property the shipped module does not "
            "hold. The run's declared nine inputs are unchanged; so must be its ids."
        )
    finally:
        store.close()


def test_tc_orch_c01_enumeration_is_insert_or_ignore_over_progress(tmp_data_dir):
    """The ledger side of the same clause: re-enumeration after progress is a no-op on
    existing rows (`INSERT OR IGNORE` keyed on `work_id`) — `done` stays `done` and the
    ledger grows by nothing, which is what makes resume's skip rather than re-address."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, version = seed_run(
            store,
            submissions=_SUBMISSIONS,
            criteria=_CRITERIA,
        )
        orchestrator.enumerate_units(run_id)
        handle = store.cohort(ORCH_COHORT_ID)
        before = {
            row["work_id"]: row["status"]
            for row in handle.query(
                "SELECT work_id, status FROM work_unit WHERE run_id = :r", r=run_id
            )
        }
        assert before, "the fixture enumerated no units — nothing to re-enumerate over"
        target = sorted(before)[0]
        with handle.transaction() as tx:
            tx.execute(
                "UPDATE work_unit SET status = 'done' WHERE work_id = :w", w=target
            )

        orchestrator.enumerate_units(run_id)

        after = {
            row["work_id"]: row["status"]
            for row in handle.query(
                "SELECT work_id, status FROM work_unit WHERE run_id = :r", r=run_id
            )
        }
        assert set(after) == set(before), (
            "re-enumeration minted NEW ledger rows for identities it already holds — "
            "the idempotence CT-ORCH-01 requires (INSERT OR IGNORE keyed on work_id) "
            "is not what the module ships"
        )
        assert after[target] == "done", (
            f"re-enumeration reset the driven unit {target[:12]}… from 'done' — an "
            "enumeration that touches existing rows is a cleanup pass, not an idempotent "
            "insert, and would erase every completed unit on resume"
        )
    finally:
        store.close()
