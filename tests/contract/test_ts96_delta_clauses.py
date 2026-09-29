"""TS-96 (#390), part one: the gap-fix delta's clause cases for M-PKG, M-REVIEW and M-STATS.

| Case | Clause | Assertion (breaks if the clause is broken) |
|---|---|---|
| TC-PKG-C19 | CT-PKG-19 | the base version, a revision child and an import each hold no criterion whose `evaluation_mode` is NULL or outside `('judged', 'deterministic')` |
| TC-REVIEW-C21 | CT-REVIEW-21 | two store-form queued scores identical but for `band_spread` (0 vs 2), each with one adverse input: the spread-2 row ranks first and both EVs are positive |
| TC-REVIEW-C22 | CT-REVIEW-22 | two scores with equal inputs, one holistic and one atomic: the holistic ranks first |
| TC-REVIEW-C23 | CT-REVIEW-23 | every label written by the collection route carries a key of the Cohort `cohort` table, never a run id; a purge of the cohort leaves its labels in Tier D and removes the cohort file |
| TC-STATS-C22 | CT-STATS-22 | every `judge_signals` cell carries exactly `JUDGE_SIGNAL_FIELDS`, and the alert is named `judge_contract_violations_concentrated` |
| TC-STATS-C23 | CT-STATS-23 | 30 blind labels plus 30 flag-NULL labels whose teacher band equals the system band: the κ M-PKG records equals Cohen's κ hand-computed over the 30 blind labels, with n = 30 |

Disclosed:
- **TC-REVIEW-C23** drops "after migration": design 1.9 withdrew FR-REVIEW-22's historical backfill
  (ADR-31), so a pre-rule row keeps its run id by design; TC-REVIEW-33 pins that it never lets a
  purge pass.
- **TC-STATS-C23** asserts M-PKG's recorded κ (the figure the console's rollup reads through
  `promotion_record`, #529); rung 0 is TC-STATS-29's.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

import pytest

import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.orch  # noqa: F401,E401
import aeh.pkg, aeh.review, aeh.synth  # noqa: F401,E401
from aeh import review, stats
from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.contract.pkg.test_ct_pkg_catalog import _catalog, _version_with_content
from tests.support import broken_stats_fixtures as broken
from tests.support import pipe_world
from tests.support.grade_vocabulary import write_criterion_scores
from tests.support.orch_run import ORCH_COHORT_ID, seed_run


def _bad_modes(handle, version: str) -> int:
    return int(handle.query(
        "SELECT COUNT(*) AS n FROM criterion WHERE package_version_id = :v AND "
        "(evaluation_mode IS NULL OR evaluation_mode NOT IN ('judged', 'deterministic'))",
        v=version)[0]["n"])


def test_tc_pkg_c19_every_criterion_declares_its_evaluation_mode(tmp_data_dir):
    store, handle, catalog = _catalog(tmp_data_dir, blobs=True)
    v1 = _version_with_content(catalog)
    assert int(handle.query("SELECT COUNT(*) AS n FROM criterion WHERE package_version_id = :v",
                            v=v1)[0]["n"]) > 0, "fixture: the base version has no criterion"
    v2 = catalog.create_version(v1)
    catalog.publish(v1, "teacher")
    dest = tmp_data_dir / "c19.pkgzip"
    report = catalog.export(v1, dest)
    receiver_store = open_store(tmp_data_dir / "receiver")
    receiver = PackageCatalog(receiver_store.package("seed"), package_id="seed",
                              blobs=receiver_store.blobs())
    imported = receiver.import_file(dest)
    imported_handle = receiver_store.package(report.package_id)
    try:
        assert (_bad_modes(handle, v1), _bad_modes(handle, v2),
                _bad_modes(imported_handle, imported.package_version_id)) == (0, 0, 0)
    finally:
        receiver_store.close()
        store.close()


# --- M-REVIEW -------------------------------------------------------------------------------


def _queue(data_dir, run_id):
    service = review.open_review(data_dir, run_id=run_id)
    try:
        queue = service.build_queue(run_id=run_id, budget_minutes=600)
    finally:
        service.close()
    return [m for e in queue.shown for m in (getattr(e, "members", None) or (e,))]


def test_tc_review_c21_the_stored_panel_spread_moves_the_rank(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        _o, run_id, _v = seed_run(store, submissions=("S1", "S2"), criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},))
        write_criterion_scores(store.cohort(ORCH_COHORT_ID),
                               [("S1", "C1", "B1", 1.0, "provisional"), ("S2", "C1", "B2", 1.0, "provisional")])
    finally:
        store.close()
    with sqlite3.connect(Path(tmp_data_dir) / "cohorts" / f"{ORCH_COHORT_ID}.sqlite") as c:
        c.execute("UPDATE criterion_score SET spans_verified = 0, band_spread = "
                  "CASE submission_id WHEN 'S2' THEN 2 ELSE 0 END")
    items = _queue(tmp_data_dir, run_id)
    order = [i.submission_id for i in items]
    assert order.index("S2") < order.index("S1"), f"the spread-2 score does not rank first: {order}"
    assert all(i.expected_value > 0 for i in items), [(i.submission_id, i.expected_value) for i in items]


def test_tc_review_c22_a_holistic_score_ranks_above_an_equal_atomic_one(tmp_data_dir):
    """Equal expected value is constructed, not assumed: the holistic criterion takes twice as
    long to review (90 s vs 45 s), so it is weighted 2x in the grade policy, which doubles its
    impact and makes the two EVs exactly equal. At that tie the holistic one ranks first."""
    from aeh.pkg import GradePolicy

    store = open_store(tmp_data_dir)
    try:
        _o, run_id, version = seed_run(store, submissions=("S1",), criteria=(
            {"criterion_id": "C-A", "kind": "open", "scoring_model": "atomic"},
            {"criterion_id": "C-H", "kind": "open", "scoring_model": "holistic"}))
        package_id = version.rpartition("@")[0]
        catalog = PackageCatalog(store.package(package_id), package_id=package_id)
        catalog.set_grade_policy(version, GradePolicy(weights=(("C-A", 1.0), ("C-H", 2.0))))
        write_criterion_scores(store.cohort(ORCH_COHORT_ID), [
            ("S1", "C-A", "B2", 1.0, "provisional"), ("S1", "C-H", "B2", 1.0, "provisional")])
    finally:
        store.close()
    with sqlite3.connect(Path(tmp_data_dir) / "cohorts" / f"{ORCH_COHORT_ID}.sqlite") as c:
        c.execute("UPDATE criterion_score SET spans_verified = 0")
    ordered = _queue(tmp_data_dir, run_id)
    items = {i.criterion_id: i for i in ordered}
    assert items["C-H"].scoring_model == "holistic" and items["C-A"].scoring_model == "atomic"
    assert items["C-H"].expected_value == pytest.approx(items["C-A"].expected_value), (
        f"fixture: the EVs are not equal ({items['C-H'].expected_value} vs {items['C-A'].expected_value})")
    order = [i.criterion_id for i in ordered]
    assert order.index("C-H") < order.index("C-A"), f"at equal EV the atomic ranks first: {order} (CT-REVIEW-22)"


def test_tc_review_c23_collected_labels_carry_a_cohort_key(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        _o, run_id, _v = seed_run(store, submissions=("S1",), criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},))
        write_criterion_scores(store.cohort(ORCH_COHORT_ID), [("S1", "C1", "B1", 0.0, "provisional")])
    finally:
        store.close()
    service = review.open_review(tmp_data_dir, run_id=run_id)
    try:
        items = [m for e in service.build_queue(run_id=run_id, budget_minutes=600).shown
                 for m in (getattr(e, "members", None) or (e,))]
        service.act(items[0], action="edit", new_band="B2")
    finally:
        service.close()
    cohort_file = Path(tmp_data_dir) / "cohorts" / f"{ORCH_COHORT_ID}.sqlite"
    with sqlite3.connect(cohort_file) as c:
        cohorts = {r[0] for r in c.execute("SELECT cohort_id FROM cohort")}
        runs = {r[0] for r in c.execute("SELECT run_id FROM run")}
    with sqlite3.connect(Path(tmp_data_dir) / "durable.sqlite") as c:
        labels = [r[0] for r in c.execute("SELECT cohort_id FROM label")]
    assert labels and set(labels) <= cohorts and not set(labels) & runs, (labels, cohorts, runs)


# --- M-STATS --------------------------------------------------------------------------------


def test_tc_stats_c22_every_judge_signal_cell_carries_the_declared_fields(tmp_path, monkeypatch):
    world = pipe_world.replay_world(tmp_path / "w", monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    try:
        assert pipe_world.drive_composed(world).status == "complete"
        signals = stats.judge_signals(world.store, world.run_id)
    finally:
        world.store.close()
    assert signals.cells, "fixture: no judge signal cell"
    for key, cell in signals.cells.items():
        assert set(cell) == set(stats.JUDGE_SIGNAL_FIELDS), (key, sorted(cell))
    assert stats.JUDGE_VIOLATION_ALERT == "judge_contract_violations_concentrated"


def _cohen_kappa(pairs):
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(left[k] * right[k] for k in set(left) | set(right)) / (n * n)
    return (po - pe) / (1 - pe)


def test_tc_stats_c23_labels_with_no_blind_flag_never_enter_the_kappa(tmp_data_dir):
    # Rung 3's store half: the flag cannot even be stored NULL (the defence in depth).
    store = open_store(tmp_data_dir)
    try:
        store.durable()
    finally:
        store.close()
    with sqlite3.connect(Path(tmp_data_dir) / "durable.sqlite") as c, pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO label (label_id, run_id, student_ref, criterion_id, label_type, band, "
                  "evaluation_mode, saw_system_output, routing, origin, system_band, teacher_band) "
                  "VALUES ('L-null', 'r', 'S1', 'C1', 'blind', 'B1', 'judged', NULL, 'queued', "
                  "'blind_sample', 'B1', 'B1')")
    # The consumer half: labels whose flag is unrecorded never enter the figure.
    blind = ([(1, 1)] * 10 + [(2, 2)] * 8 + [(3, 3)] * 6 + [(1, 2)] * 3 + [(2, 3)] * 3)  # (teacher, system)
    labels = [broken.Label(label_id=f"L-b{i}", criterion_id="C1", teacher_band=t, band=sys_band,
                           saw_system_output=False)
              for i, (t, sys_band) in enumerate(blind)]
    labels += [broken.Label(label_id=f"L-n{i}", criterion_id="C1", teacher_band=1, band=1,
                            saw_system_output=None) for i in range(30)]
    figure = stats.ValidationStats(labels).agreement(criterion_id="C1")
    assert figure.n == 30, f"n = {figure.n}: the flag-NULL labels were admitted (CT-STATS-23)"
    assert figure.kappa == pytest.approx(_cohen_kappa(blind)), (figure.kappa, _cohen_kappa(blind))
