"""TS-130 (#541): the two override figures, the backend column, run-scoped review, the purge rule.

| Case | Requirement | Oracle |
|---|---|---|
| TC-STATS-36 | FR-STATS-24 (amended) | 4 labels → `below_min_n`; 5 with 1 override → 0.2; none → `no_blind_labels`; operational labels excluded; the minimum read at call time |
| TC-STATS-37 | FR-STATS-28 | every two-band label counts, one-band labels do not; 1/3 over 6; 4 → `below_min_n`; the stored reader equals the in-memory figure; no `system_band !=` in `aeh.review` |
| TC-REVIEW-32 | FR-REVIEW-18 (amended) | the stored rate reaches `historical_override_rate` (0.6 / 0.0 / no data), C-HI outranks C-LO, and without the input the two tie |
| TC-REVIEW-33 | FR-REVIEW-22 (amended) | a pre-rule label (`cohort_id = run id`) never lets a purge pass; nothing rewrites it |
| TC-REVIEW-34 | FR-REVIEW-23 | labels carry their run's backend; a pre-migration NULL is `backend_not_recorded`; Durable pin 12 |
| TC-REVIEW-35 | FR-REVIEW-24 | one service per run in a shared cohort; an unknown run raises `UnknownRunError` and creates no file |
| TC-REVIEW-37 | FR-STATS-24 (defect #525 item 3) | a collected label names its package; five labels naming pkg-alpha give pkg-alpha's `C1` a 5/0.2 history and pkg-beta's `C1` `no_blind_labels` |

Implemented by #433, #514, #515 and #434's decision (all merged), so these land green.
TC-REVIEW-37 is the exception: it is a defect fix's regression case (#525 item 3, no TC
existed), written RED first against the collection route that hard-coded the package NULL.

Disclosed:
- **TC-REVIEW-37.** The reader keeps its documented "or no version" accommodation (a label
  that names no version pools into every lineage, because no honest reading can attribute
  it); what this case pins is the WRITE side — a label that names its package records it, so
  the reviews of one package stop counting for another that shares a criterion name.
- **TC-REVIEW-33.** The plan's refusal "naming the unattributable label" is not what M-STORE
  says: it names the unmet gate ("no label rows for cohort …"), never the row. The case asserts
  the labels gate is the ONLY unmet one (the cohort's audit and stats rows are seeded). Its NULL
  arm goes through the collection route (`record_label(data_dir=, label=)` with no cohort).
- **TC-REVIEW-34 and TC-PKG-33 (TS-131).** Both open a fresh store at the current chain and
  write the NULL row by hand; neither migrates a store opened at the previous pin, so "a
  pre-migration row survives as NULL" is asserted over the NULL's reading, not the migration.
TC-STATS-31 arms 2 and 4 were re-keyed by #433 itself (both markers removed when it landed).
"""

from __future__ import annotations

import dataclasses
import inspect
import sqlite3
from pathlib import Path

import pytest

import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.orch  # noqa: F401,E401
import aeh.pkg, aeh.review, aeh.synth  # noqa: F401,E401
from aeh import review, stats
from aeh.pkg import NoValidationData
from aeh.store import COMPLETE_SCHEMA_VERSIONS, PurgePreconditionError, Tier, open_store
from tests.support import broken_stats_fixtures as broken
from tests.support.grade_vocabulary import write_criterion_scores
from tests.support.orch_run import ORCH_COHORT_ID, orch_cfg, seed_package, seed_run
from tests.support.source_tree import package_source

pytestmark = pytest.mark.integration


def _label(i: int, criterion: str, *, system: int = 2, teacher: int | None = 2,
           origin: str = "blind_sample", label_type: str = "blind") -> broken.Label:
    return broken.Label(label_id=f"L-{criterion}-{i}", criterion_id=criterion, band=system,
                        teacher_band=teacher, origin=origin, label_type=label_type)


# --- TC-STATS-36 ----------------------------------------------------------------------------


def test_tc_stats_36_override_history_min_n_population_and_call_time_knob(monkeypatch):
    monkeypatch.delenv("HARNESS_REVIEW_OVERRIDE_MIN_N", raising=False)
    labels = [
        *(_label(i, "C1", origin="override" if i == 0 else "blind_sample") for i in range(4)),
        *(_label(i, "C2", origin="override" if i == 0 else "blind_sample") for i in range(5)),
        *(_label(i, "C4") for i in range(5)),
        *(_label(100 + i, "C4", origin="override", label_type="accept") for i in range(10)),
    ]
    s = stats.ValidationStats(labels)
    c1 = s.criterion_override_history("C1")
    assert isinstance(c1, NoValidationData) and c1.reason == "below_min_n" and c1.n == 4, c1
    c2 = s.criterion_override_history("C2")
    assert (c2.n, c2.override_rate) == (5, 0.2), c2
    c3 = s.criterion_override_history("C3")
    assert isinstance(c3, NoValidationData) and c3.reason == "no_blind_labels" and c3.n == 0, c3
    c4 = s.criterion_override_history("C4")
    assert (c4.n, c4.override_rate) == (5, 0.0), (
        f"{c4}: the ten operational override labels must be excluded (admissible blind only)")
    monkeypatch.setenv("HARNESS_REVIEW_OVERRIDE_MIN_N", "4")
    assert s.criterion_override_history("C1").override_rate == 0.25, (
        "the minimum n is read at call time (seam 3)")


# --- TC-STATS-37 ----------------------------------------------------------------------------


def _stats37_labels() -> list[broken.Label]:
    return [
        _label(0, "C1", system=2, teacher=3),
        _label(1, "C1"),
        _label(2, "C1"),
        _label(3, "C1", system=2, teacher=1, label_type="edit"),
        _label(4, "C1", label_type="accept"),
        _label(5, "C1", label_type="accept"),
        _label(6, "C1", teacher=None),
        _label(7, "C1", teacher=None, label_type="accept"),
        *(_label(i, "C2") for i in range(4)),
    ]


def test_tc_stats_37_disagreement_rate_counts_every_two_band_label(tmp_data_dir, monkeypatch):
    monkeypatch.delenv("HARNESS_REVIEW_OVERRIDE_MIN_N", raising=False)
    s = stats.ValidationStats(_stats37_labels())
    c1 = s.criterion_disagreement_rate("C1")
    assert (c1.n, c1.disagreements) == (6, 2) and c1.rate == pytest.approx(1 / 3), c1
    c2 = s.criterion_disagreement_rate("C2")
    assert isinstance(c2, NoValidationData) and c2.reason == "below_min_n", c2

    store = open_store(tmp_data_dir)
    try:
        _o, _run, version = seed_run(store, submissions=("S1",), criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
            {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"}))
    finally:
        store.close()
    # The collection route refuses a label with no teacher band (Tier D stores a band for
    # every label), so the stored half holds the six two-band labels and the four for C2.
    for label in _stats37_labels():
        if label.teacher_band is not None:
            review.record_label(data_dir=tmp_data_dir, label=label)
    store = open_store(tmp_data_dir)
    try:
        stored = stats.stored_disagreement_rates(store, version)
    finally:
        store.close()
    assert set(stored) == {"C1", "C2"}, stored
    assert (stored["C1"].n, stored["C1"].disagreements) == (6, 2), stored["C1"]
    assert stored["C1"].rate == pytest.approx(1 / 3), stored["C1"]
    assert isinstance(stored["C2"], NoValidationData) and stored["C2"].reason == "below_min_n", stored["C2"]
    assert "system_band !=" not in package_source(review), (
        "aeh.review derives a disagreement of its own (FR-REVIEW-18 amended: M-STATS alone)")


# --- TC-REVIEW-32 ---------------------------------------------------------------------------


def _ranked_rows(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        _o, run_id, _v = seed_run(store, submissions=("S1",), criteria=(
            {"criterion_id": "C-HI", "kind": "open", "scoring_model": "atomic"},
            {"criterion_id": "C-LO", "kind": "open", "scoring_model": "atomic"},
            {"criterion_id": "C-NONE", "kind": "open", "scoring_model": "atomic"}))
        write_criterion_scores(store.cohort(ORCH_COHORT_ID), [
            ("S1", "C-HI", "B2", 1.0, "provisional"), ("S1", "C-LO", "B2", 1.0, "provisional"),
            ("S1", "C-NONE", "B2", 1.0, "provisional")])
    finally:
        store.close()
    return run_id


def _seed_rate_labels(tmp_data_dir):
    for i in range(10):
        review.record_label(data_dir=tmp_data_dir, label=_label(i, "C-HI", teacher=3 if i < 6 else 2))
        review.record_label(data_dir=tmp_data_dir, label=_label(i, "C-LO"))
    for i in range(2):
        review.record_label(data_dir=tmp_data_dir, label=_label(i, "C-NONE", teacher=3))


def _rows_by_criterion(tmp_data_dir, run_id):
    service = review.open_review(tmp_data_dir, run_id=run_id)
    try:
        return {str(row.criterion_id): row for row in service._rows}
    finally:
        service.close()


def test_tc_review_32_the_stored_disagreement_rate_moves_the_rank(tmp_data_dir, monkeypatch):
    monkeypatch.delenv("HARNESS_REVIEW_OVERRIDE_MIN_N", raising=False)
    run_id = _ranked_rows(tmp_data_dir)
    _seed_rate_labels(tmp_data_dir)
    rows = _rows_by_criterion(tmp_data_dir, run_id)
    assert rows["C-HI"].historical_override_rate == pytest.approx(0.6)
    assert rows["C-LO"].historical_override_rate == 0.0
    assert rows["C-NONE"].historical_override_rate is None, "two labels are no data, not 0.0"
    knobs = review._calibration_knobs()
    hi, lo = (review._expected_value(rows[c], knobs) for c in ("C-HI", "C-LO"))
    assert hi > lo, f"C-HI ({hi}) does not outrank C-LO ({lo}) on the stored rate alone"

    # Mutation: the input removed, the two criteria are identical and must tie.
    monkeypatch.setattr(stats, "stored_disagreement_rates", lambda store, version: {})
    muted = _rows_by_criterion(tmp_data_dir, run_id)
    assert review._expected_value(muted["C-HI"], knobs) == review._expected_value(muted["C-LO"], knobs)


# --- TC-REVIEW-33 ---------------------------------------------------------------------------


def test_tc_review_33_a_pre_rule_label_never_lets_a_purge_pass(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        _o, run_id, _v = seed_run(store, submissions=("S1",), criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},))
        store.durable()
    finally:
        store.close()
    durable = Path(tmp_data_dir) / "durable.sqlite"
    with sqlite3.connect(durable) as c:
        c.execute("INSERT INTO label (label_id, run_id, student_ref, criterion_id, label_type, band, "
                  "evaluation_mode, saw_system_output, routing, origin, cohort_id) VALUES "
                  "('pre-rule', ?, 'S1', 'C1', 'blind', 'B1', 'judged', 0, 'queued', 'direct', ?)",
                  (run_id, run_id))
        # The cohort's other promotion rows, so the pre-rule label is the ONLY thing between
        # this cohort and a purge (without them the audit and stats gates refuse on their own).
        c.execute("INSERT INTO audit_record (audit_record_id, run_id, recorded_at, profile_summary, "
                  "cohort_id) VALUES ('a-1', ?, '2026-09-01T00:00:00Z', 'edge-local', ?)",
                  (run_id, ORCH_COHORT_ID))
        c.execute("INSERT INTO criterion_stats (package_version_id, criterion_id, backend_profile, "
                  "panel_build_ref, n, cohort_id) VALUES (?, 'C1', 'edge-local', '', 5, ?)",
                  (_v, ORCH_COHORT_ID))
    store = open_store(tmp_data_dir)
    try:
        with pytest.raises(PurgePreconditionError) as refused:
            store.purge_cohort(ORCH_COHORT_ID)
    finally:
        store.close()
    unmet = str(refused.value).split("Unmet gates:", 1)[1].split(". Promotion", 1)[0]
    assert unmet.strip().startswith("labels") and "audit" not in unmet and "statistics" not in unmet, (
        f"the purge must be refused on the labels gate alone: {unmet}")
    with sqlite3.connect(durable) as c:
        assert c.execute("SELECT cohort_id FROM label WHERE label_id = 'pre-rule'").fetchone() == (run_id,), (
            "a code path rewrote the pre-rule row (FR-REVIEW-22 amended: no backfill)")
        assert Path(tmp_data_dir, "cohorts", f"{ORCH_COHORT_ID}.sqlite").exists(), "the refused purge deleted"
    # A fresh label whose cohort cannot be resolved stores NULL, never a run id.
    review.record_label(data_dir=tmp_data_dir, label=_label(1, "C1"))
    with sqlite3.connect(durable) as c:
        assert c.execute("SELECT cohort_id FROM label WHERE label_id = 'L-C1-1'").fetchone() == (None,)


# --- TC-REVIEW-34 ---------------------------------------------------------------------------


def test_tc_review_34_labels_record_their_runs_backend(tmp_data_dir, monkeypatch):
    monkeypatch.delenv("HARNESS_REVIEW_OVERRIDE_MIN_N", raising=False)
    assert COMPLETE_SCHEMA_VERSIONS[Tier.DURABLE] == 12
    store = open_store(tmp_data_dir)
    try:
        store.durable()
    finally:
        store.close()
    with sqlite3.connect(Path(tmp_data_dir) / "durable.sqlite") as c:
        cols = [row[1] for row in c.execute("PRAGMA table_info(label)")]
        assert "backend_profile" in cols
        c.execute("INSERT INTO label (label_id, run_id, student_ref, criterion_id, label_type, band, "
                  "evaluation_mode, saw_system_output, routing, origin, system_band, teacher_band) "
                  "VALUES ('pre-mig', '', 'S0', 'C1', 'blind', 'B1', 'judged', 0, 'queued', "
                  "'direct', 'B1', 'B1')")
    review.record_label(data_dir=tmp_data_dir, label=dataclasses.replace(
        _label(1, "C1"), backend_profile="edge-local"))
    review.record_label(data_dir=tmp_data_dir, label=dataclasses.replace(
        _label(2, "C1"), backend_profile="cloud-hosted"))
    with sqlite3.connect(Path(tmp_data_dir) / "durable.sqlite") as c:
        backends = dict(c.execute("SELECT label_id, backend_profile FROM label").fetchall())
    assert backends["L-C1-1"] == "edge-local" and backends["L-C1-2"] == "cloud-hosted", backends
    assert backends["pre-mig"] is None
    reasons = stats.open_stats(data_dir=tmp_data_dir).exclusion_reasons(
        backend_profile="edge-local", criterion_id="C1")
    assert reasons.get("backend_not_recorded") == 1, reasons


# --- TC-REVIEW-35 ---------------------------------------------------------------------------


def test_tc_review_35_open_review_serves_exactly_its_run(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        orch, r1, version = seed_run(store, submissions=("S1", "S2"), criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},))
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            tx.execute("INSERT INTO criterion_score (run_id, submission_id, criterion_id, band, "
                       "points, routing, state) VALUES (:r, 'S1', 'C1', 'B1', 1.0, 'provisional', "
                       "'provisional_unreviewed')", r=r1)
        r2 = orch.create_run(ORCH_COHORT_ID, version, orch_cfg())
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            tx.execute("INSERT INTO criterion_score (run_id, submission_id, criterion_id, band, "
                       "points, routing, state) VALUES (:r, 'S2', 'C1', 'B1', 1.0, 'provisional', "
                       "'provisional_unreviewed')", r=r2)
    finally:
        store.close()
    for run_id, submission in ((r1, "S1"), (r2, "S2")):
        service = review.open_review(tmp_data_dir, run_id=run_id)
        try:
            assert {str(row.submission_id) for row in service._rows} == {submission}, run_id
        finally:
            service.close()
    before = sorted(p.relative_to(tmp_data_dir).as_posix() for p in Path(tmp_data_dir).rglob("*"))
    with pytest.raises(review.UnknownRunError, match="run-nope"):
        review.open_review(tmp_data_dir, run_id="run-nope")
    after = sorted(p.relative_to(tmp_data_dir).as_posix() for p in Path(tmp_data_dir).rglob("*"))
    assert before == after, "an unknown run created a file"


# --- TC-REVIEW-37 (defect #525 item 3) -------------------------------------------------------


@dataclasses.dataclass
class _PackagedLabel:
    """A collected label that also names its package version.

    `broken.Label` carries only the columns `CT-STATS-01` filters on — by design it has no
    `package_version_id`, which is exactly the column #525's item 3 is about: the collection
    route (`record_label(data_dir=, label=)`) must read the label's own package linkage and
    store it, not hard-code NULL. This fixture adds that one field so the test can say which
    package a label belongs to; the route is `getattr`-based, so nothing else changes shape.
    """

    label_id: str
    criterion_id: str
    band: int
    teacher_band: int
    label_type: str = "blind"
    evaluation_mode: str = "judged"
    saw_system_output: int = 0
    origin: str = "blind_sample"
    package_version_id: str | None = None


def test_tc_review_37_a_collected_label_counts_for_the_package_it_names(tmp_data_dir, monkeypatch):
    monkeypatch.delenv("HARNESS_REVIEW_OVERRIDE_MIN_N", raising=False)
    store = open_store(tmp_data_dir)
    try:
        alpha = seed_package(store, (
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},),
            package_id="pkg-alpha")
        beta = seed_package(store, (
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},),
            package_id="pkg-beta")
    finally:
        store.close()
    labels = [
        _PackagedLabel(
            label_id=f"L-{i}", criterion_id="C1", band=2, teacher_band=2,
            origin="override" if i == 0 else "blind_sample", package_version_id=alpha)
        for i in range(5)
    ]
    for label in labels:
        review.record_label(data_dir=tmp_data_dir, label=label)
    with sqlite3.connect(Path(tmp_data_dir) / "durable.sqlite") as c:
        versions = dict(c.execute("SELECT label_id, package_version_id FROM label").fetchall())
    assert set(versions.values()) == {alpha}, (
        f"FR-STATS-24 (defect #525 item 3): every collected label carries the package it "
        f"names, not NULL: {versions}")
    store = open_store(tmp_data_dir)
    try:
        alpha_histories = stats.stored_override_histories(store, alpha)
        beta_histories = stats.stored_override_histories(store, beta)
    finally:
        store.close()
    alpha_c1 = alpha_histories["C1"]
    assert (alpha_c1.n, alpha_c1.override_count, alpha_c1.override_rate) == (5, 1, 0.2), alpha_c1
    beta_c1 = beta_histories["C1"]
    assert isinstance(beta_c1, NoValidationData) and beta_c1.reason == "no_blind_labels" \
        and beta_c1.n == 0, (
        f"{beta_c1}: five labels naming pkg-alpha must not count for pkg-beta's C1 — "
        "the packages share only the criterion name (defect #525 item 3)")
