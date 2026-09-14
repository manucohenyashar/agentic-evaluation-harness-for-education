"""`TC-ORCH-37` — a work unit is traceable to its source document (#223, `FR-INGEST-01`).

Regression case for finding A6 (the G5 probe, #49/PR #212): the `work_unit` row carries no
`document_id`, and nothing followed the join from a unit to the text it came from. Design
§3.7's `WorkUnit` field list is closed, so the join is a lookup over the submission row:
`Orchestrator.provenance(work_id)` follows work_unit -> submission -> document.

Written with the fix under `/fix-issue`'s defect exception, and added to the test plan in
the same change. The world is `tests/support/orch_run.py`'s seeded ledger (cohort,
submission and document rows written disclosedly), not a live ingestion.
"""

from __future__ import annotations

import dataclasses

import pytest

from aeh.store import open_store
from tests.support.orch_run import seed_document, seed_run

pytestmark = [pytest.mark.integration]

_CRITERIA = ({"criterion_id": "C01", "kind": "open", "scoring_model": "holistic"},)


def _units(orchestrator, run_id):
    orchestrator.enumerate_units(run_id)
    return orchestrator.lease("w-prov", "extract", 10)


def test_tc_orch_37_a_leased_unit_resolves_to_its_current_document(tmp_data_dir):
    """The leased unit joins to the document its submission was transcribed into, and a
    superseding re-transcription moves the head — the row extraction reads."""
    from aeh.orch import UnitProvenance

    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _v = seed_run(store, submissions=("S001", "S002"), criteria=_CRITERIA)
        seed_document(store, "S001", "first answer text")
        seed_document(store, "S002", "second answer text")
        units = _units(orchestrator, run_id)
        assert units, "fixture: the lease handed over no extract units"
        for unit in units:
            record = orchestrator.provenance(unit.work_id)
            assert isinstance(record, UnitProvenance)
            assert (record.work_id, record.run_id, record.submission_id) == (
                unit.work_id, run_id, unit.submission_id)
            assert record.document_id == f"doc-{unit.submission_id}", (
                f"TC-ORCH-37: unit {unit.work_id[:12]} of {unit.submission_id} joined to "
                f"{record.document_id!r}, not the submission's document.")
            assert record.hops == (
                f"work_unit:{unit.work_id}", f"submission:{unit.submission_id}",
                f"document:doc-{unit.submission_id}"), record.hops

        # Different submissions resolve to different documents: a join that ignored the
        # submission key would hand every unit the same row.
        assert len({orchestrator.provenance(u.work_id).document_id for u in units}) == 2

        target = next(u for u in units if u.submission_id == "S001")
        handle, _row = orchestrator._find_unit(target.work_id)
        with handle.transaction() as tx:
            tx.execute(
                "INSERT INTO document (document_id, submission_id, content_hash) "
                "VALUES ('doc-S001-zz-retranscribed', 'S001', :h)",
                h=store.blobs().put(b"re-transcribed answer"))
        moved = orchestrator.provenance(target.work_id)
        assert moved.document_ids == ("doc-S001", "doc-S001-zz-retranscribed")
        assert moved.document_id == "doc-S001-zz-retranscribed", (
            "TC-ORCH-37: the head must follow M-INGEST's document ordering")
    finally:
        store.close()


@pytest.mark.parametrize("hop", ["no-document", "null-submission"])
def test_tc_orch_37_a_broken_lineage_is_refused_not_joined_to_null(tmp_data_dir, hop):
    """A unit whose lineage stops short raises `BrokenLineageError` naming the hop."""
    from aeh.orch import BrokenLineageError

    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _v = seed_run(store, submissions=("S001",), criteria=_CRITERIA)
        seed_document(store, "S001")
        unit = _units(orchestrator, run_id)[0]
        # Positive control: the intact lineage resolves before it is broken.
        assert orchestrator.provenance(unit.work_id).document_id == "doc-S001"
        cohort, _row = orchestrator._find_unit(unit.work_id)
        with cohort.transaction() as tx:
            if hop == "no-document":
                tx.execute("DELETE FROM document WHERE submission_id = 'S001'")
            else:
                tx.execute("UPDATE work_unit SET submission_id = NULL WHERE work_id = :w",
                           w=unit.work_id)
        with pytest.raises(BrokenLineageError) as refused:
            orchestrator.provenance(unit.work_id)
        expected = "document hop" if hop == "no-document" else "no submission_id"
        assert expected in str(refused.value), str(refused.value)
    finally:
        store.close()


def test_tc_orch_37_the_provenance_record_widens_nothing_the_ledger_exposes():
    """The pseudonymization boundary stays at assembly (§3.7 v1.5 note): the record
    carries identifiers only, never identity or text."""
    from aeh.orch import UnitProvenance

    fields = {field.name for field in dataclasses.fields(UnitProvenance)}
    leaked = fields & {"student_ref", "student_name", "submission_text", "text", "markdown"}
    assert not leaked, f"TC-ORCH-37: UnitProvenance exposes {sorted(leaked)}"
