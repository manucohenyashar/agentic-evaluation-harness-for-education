"""`CT-DET-07` — the key-correction surface (`TC-DET-C07`).

Case of test plan §6.11.11; issue #90 (TS-68). Green by design — `M-DET`
shipped via #246/#249.

The clause: `rederive_for_key_change` recomputes every affected score **by
lookup** and enqueues **no** panel work; the audit record names which key
version produced which grade, so a correction is answerable years later; and
it is **idempotent** — re-deriving against an unchanged key produces no change.

The clause discriminator: the FR-level case (TS-33's) walks the 350-student
correction and its counts; this case asserts the two properties a count-sweep
does not pin —
- **Idempotency as a differential**: a re-derivation naming the UNCORRECTED
  version itself changes nothing (zero on every counter, no rows written, no
  audit appended), and a SECOND re-derivation under the corrected version is
  likewise a full no-change — redelivery of the same correction is harmless,
  which is the M-ORCH at-least-once constraint the surface exists to satisfy;
- **Audit resolution (RISK-12)**: each audit row's `answer_key_ref` is
  resolved through the package's version lineage back to the key bytes that
  produced the grade — the pre-correction grades still resolve to the OLD
  key after the correction, and the re-derived grades resolve to the new.
  A ref that stopped resolving, or resolved to whatever the version's key is
  NOW, would make the correction unanswerable.
"""

from __future__ import annotations

import json

import pytest

from aeh.det import DeterministicEvaluator
from aeh.pkg import PackageCatalog
from tests.support.det_vocabulary import (
    open_det_store,
    seed_det_world,
    seed_selection_answers,
)

pytestmark = pytest.mark.contract

from tests.contract.det._doubles import ISSUE  # noqa: F401 — register citation


def _seed(store):
    """A small world with both key-dependent outcomes: two B-answerers and two
    C-answerers on `M1` (key B), plus a control criterion `M2` the correction
    does not touch."""
    run_id, version, cohort_id = seed_det_world(
        store,
        submissions=("S1", "S2", "S3", "S4"),
        criteria=[
            {"criterion_id": "M1", "question_id": "Q1", "key": ("B",)},
            {"criterion_id": "M2", "question_id": "Q2", "key": ("B",)},
        ],
    )
    seed_selection_answers(
        store, cohort_id,
        [{"submission_id": s, "selection": "B"} for s in ("S1", "S2")]
        + [{"submission_id": s, "selection": "C"} for s in ("S3", "S4")],
    )
    # M2's regions too (the batch helper writes Q1 only).
    from tests.support.det_vocabulary import seed_answer_region

    for s in ("S1", "S2", "S3", "S4"):
        seed_answer_region(store, cohort_id, f"doc-{s}", "Q2", selection="B")
    return run_id, version, cohort_id


def _units(store, cohort_id):
    return store.cohort(cohort_id).query(
        "SELECT COUNT(*) AS n FROM work_unit"
    )[0]["n"]


def _resolve_ref(store, ref: str) -> tuple[str, tuple[str, ...]]:
    """`answer_key_ref` → `(version, key bytes)`, read back through the
    package's version lineage — the resolution the clause promises stays
    possible years later."""
    package_handle = store.package("pkg-det")
    version, raw = ref.split(":", 1)
    rows = package_handle.query(
        "SELECT answer_key FROM criterion WHERE package_version_id = :v "
        "AND criterion_id = 'M1'",
        v=version,
    )
    assert rows, f"TC-DET-C07: ref version {version!r} does not resolve."
    return version, tuple(json.loads(raw)), tuple(json.loads(rows[0]["answer_key"]))


def test_tc_det_c07_idempotent_under_unchanged_and_corrected_keys(tmp_data_dir):
    """`TC-DET-C07` (idempotency differential) — three re-derivations:
    against the UNCORRECTED version (no change at all), against the corrected
    version (the change, once), and the SAME correction again (nothing — the
    redelivery). The audit trail appends only on the one pass that moved
    rows; the work ledger never grows."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, v1, cohort_id = _seed(store)
        evaluator = DeterministicEvaluator(store)
        first = evaluator.evaluate_cohort(run_id)
        assert (first.correct, first.incorrect) == (2 + 4, 2)  # M1: 2/2; M2: 4/0

        units_before = _units(store, cohort_id)
        audits_before = store.durable().query(
            "SELECT COUNT(*) AS n FROM audit_record")[0]["n"]

        # 1. Re-deriving against the UNCHANGED key: a full no-change.
        same = evaluator.rederive_for_key_change(cohort_id, "M1", v1)
        assert same.panel_units_enqueued == 0
        assert same.scores_changed == 0 and same.scores_unchanged == 4
        assert same.changes == () and same.audit_records_written == 0
        assert _units(store, cohort_id) == units_before
        assert store.durable().query(
            "SELECT COUNT(*) AS n FROM audit_record")[0]["n"] == audits_before

        # 2. The correction, once: the four scored M1 rows move.
        package_handle = store.package("pkg-det")
        catalog = PackageCatalog(package_handle, package_id="pkg-det")
        v2 = catalog.create_version(parent=v1)
        catalog.set_answer_key(v2, "M1", ("C",))
        changed = evaluator.rederive_for_key_change(cohort_id, "M1", v2)
        assert changed.panel_units_enqueued == 0, (
            "TC-DET-C07: the correction enqueued panel work."
        )
        assert changed.scores_changed == 4 and changed.scores_unchanged == 0
        assert changed.audit_records_written == 4
        assert _units(store, cohort_id) == units_before, (
            "TC-DET-C07: the work_unit ledger grew during a key correction."
        )
        audits_mid = store.durable().query(
            "SELECT COUNT(*) AS n FROM audit_record")[0]["n"]
        assert audits_mid == audits_before + 4

        # 3. The SAME correction redelivered: a full no-change again — no
        # rows move, no audit appends. At-least-once delivery is harmless.
        again = evaluator.rederive_for_key_change(cohort_id, "M1", v2)
        assert again.panel_units_enqueued == 0
        assert again.scores_changed == 0 and again.scores_unchanged == 4
        assert again.changes == () and again.audit_records_written == 0
        assert _units(store, cohort_id) == units_before
        assert store.durable().query(
            "SELECT COUNT(*) AS n FROM audit_record")[0]["n"] == audits_mid
    finally:
        store.close()


def test_tc_det_c07_audit_resolves_each_grade_to_its_own_key(tmp_data_dir):
    """`TC-DET-C07` (audit resolution, RISK-12) — every audit row's
    `answer_key_ref` resolves, through the package's version lineage, to the
    exact key that produced the grade: the two B-answerers' ORIGINAL grades
    still resolve to v1's key (`["B"]`) after the correction, and the
    re-derived grades carry v2 and its `["C"]`. The old grade is answerable
    to the old key — the property that makes a correction a correction
    rather than a rewrite."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, v1, cohort_id = _seed(store)
        evaluator = DeterministicEvaluator(store)
        evaluator.evaluate_cohort(run_id)

        package_handle = store.package("pkg-det")
        catalog = PackageCatalog(package_handle, package_id="pkg-det")
        v2 = catalog.create_version(parent=v1)
        catalog.set_answer_key(v2, "M1", ("C",))
        evaluator.rederive_for_key_change(cohort_id, "M1", v2)

        audits = store.durable().query(
            "SELECT submission_id, criterion_id, package_version_id, "
            "answer_key_ref, final_points FROM audit_record WHERE "
            "criterion_id = 'M1' ORDER BY package_version_id, submission_id"
        )
        # Two grades per submission exist in the trail: the original (v1) and
        # the re-derivation (v2) — the append-only trail, not an overwrite.
        versions = {row["package_version_id"] for row in audits}
        assert versions == {v1, v2}, (
            f"TC-DET-C07: audit trail carries {sorted(versions)} — the old "
            "grades' records must survive the correction."
        )
        for row in audits:
            ref_version, ref_key, resolved_key = _resolve_ref(
                store, row["answer_key_ref"]
            )
            assert ref_version == row["package_version_id"], (
                "TC-DET-C07: the ref names a version the row does not."
            )
            assert ref_key == resolved_key, (
                f"TC-DET-C07: {row['answer_key_ref']!r} resolves to "
                f"{resolved_key!r}, not the key bytes it was written with — "
                "the grade is no longer answerable to the key that produced "
                "it."
            )
        # Spot-check the RISK-12 property directly: an S1 (answered B) grade
        # under v1 resolves to ["B"] — still, after the correction.
        old = [r for r in audits if r["package_version_id"] == v1
               and r["submission_id"] == "S1"]
        assert old and old[0]["answer_key_ref"].endswith('["B"]')
    finally:
        store.close()
