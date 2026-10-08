"""TS-131 (#542): the engine non-inferiority verdict, stored.

| Case | Requirement | Oracle |
|---|---|---|
| TC-PKG-33 | FR-PKG-23 | the three verdicts round-trip; `'maybe'` and `None` raise the column CHECK's `IntegrityError` and change nothing; an unwritten row reads `None`, distinct from `'insufficient_data'`; the Package pin and CLAUDE.md name the migration |
| TC-STATS-38 | FR-STATS-29 | `promote` of an engine-on administration stores `'true'` at α 0.70 vs 0.74 over 60 labels each and `'insufficient_data'` at 59; an engine-off administration stores nothing (NULL) |

Disclosed adaptations:
- **Migration number.** The plan says Package migration 13 / pin 13. #528's
  `pkg_export_gate_outcome` took 13, so #454 landed `pkg_decision_engine_noninferior` as 14.
- **Reader.** The plan reads the verdict through `validation_for`, which lists only rows carrying
  an agreement figure; a promote records the verdict on its own, so the case reads through
  `PackageCatalog.noninferiority_for`, #454's reader for exactly this.
- **TC-STATS-38's rung.** The partitioning of F-STATS-JEV's labels into engines is TC-STATS-33/35's
  (TS-119). This case pins FR-STATS-29's wiring on a real store: `promote` persists the verdict
  `decision_engine_noninferior` computes, with `agreement_by_engine` answering the plan's
  figures, and writes nothing for an engine-off administration. The 59-vs-60 minimum lives in
  `agreement_by_engine`, stubbed here; it is pinned by TS-119 (`test_ts119_engine_measurement`).
  Arm (c)'s "every other column byte-identical" is a twin comparison: the same administration
  promoted with the verdict step removed leaves every package-tier row the same.
- **TC-PKG-33's migration arm.** The case opens a fresh store at pin 14; it does not migrate a
  store opened at 13, so "a pre-migration row reads `None`" is asserted over an unwritten row.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.orch  # noqa: F401,E401
import aeh.review, aeh.synth  # noqa: F401,E401
from aeh import stats
from aeh.pkg import PackageCatalog, record_noninferiority
from aeh.store import COMPLETE_SCHEMA_VERSIONS, Tier, open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]


def _draft(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        _o, run_id, version = seed_run(store, submissions=("S1",), criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},))
        store.durable()
    finally:
        store.close()
    return run_id, version


def test_tc_pkg_33_the_verdict_column_round_trips_and_refuses_outside_its_domain(tmp_data_dir):
    _run_id, version = _draft(tmp_data_dir)
    package_id = version.rpartition("@")[0]
    store = open_store(tmp_data_dir)
    try:
        catalog = PackageCatalog(store.package(package_id), package_id=package_id)
        assert catalog.noninferiority_for(version, criterion_id="C1") is None, (
            "an unwritten row must read None (not measured), not 'insufficient_data'")
        for verdict in ("true", "false", "insufficient_data"):
            written = record_noninferiority(tmp_data_dir, package_version_id=version,
                                            criterion_id="C1", verdict=verdict)
            assert written.recorded, written
            assert catalog.noninferiority_for(version, criterion_id="C1") == verdict
        for bad in ("maybe", None):
            with pytest.raises(sqlite3.IntegrityError):
                record_noninferiority(tmp_data_dir, package_version_id=version,
                                      criterion_id="C1", verdict=bad)
            assert catalog.noninferiority_for(version, criterion_id="C1") == "insufficient_data", (
                f"a refused {bad!r} changed the stored verdict")
    finally:
        store.close()
    assert COMPLETE_SCHEMA_VERSIONS[Tier.PACKAGE] == 16
    assert "pkg_decision_engine_noninferior" in (REPO / "CLAUDE.md").read_text(encoding="utf-8")


def _administration(tmp_data_dir, run_id: str, engine_on: bool) -> None:
    """Six blind labels of `run_id` (unclaimed) and the run's audit row, engine on or off."""
    summary = {"backend_profile": "cloud-hosted" if engine_on else "edge-local"}
    if engine_on:
        summary["decision_engine"] = {"provider": "openrouter-jev", "build_id": "b"}
    with sqlite3.connect(Path(tmp_data_dir) / "durable.sqlite") as c:
        c.execute("INSERT INTO audit_record (audit_record_id, run_id, recorded_at, profile_summary) "
                  "VALUES (?, ?, '2026-09-01T00:00:00+00:00', ?)",
                  (f"a-{run_id}-{engine_on}", run_id, json.dumps(summary, sort_keys=True)))
        for i in range(6):
            c.execute("INSERT INTO label (label_id, run_id, student_ref, criterion_id, label_type, band, "
                      "evaluation_mode, saw_system_output, routing, origin, system_band, teacher_band) "
                      "VALUES (?, ?, 'S1', 'C1', 'blind', 'B1', 'judged', 0, 'queued', "
                      "'blind_sample', 'B1', 'B1')", (f"L-{run_id}-{i}", run_id))


def _stored_verdicts(tmp_data_dir, version: str) -> list:
    package_id = version.rpartition("@")[0]
    path = Path(tmp_data_dir) / "packages" / f"{package_id}.pkg.sqlite"
    with sqlite3.connect(path) as c:
        return [row[0] for row in c.execute(
            "SELECT decision_engine_noninferior FROM validation_record WHERE criterion_id = 'C1'")]


@pytest.mark.parametrize("decision_n, expected", [(60, "true"), (59, "insufficient_data")],
                         ids=["a-60-labels-not-inferior", "b-59-labels-insufficient"])
def test_tc_stats_38_promote_stores_the_verdict_for_an_engine_on_administration(
        tmp_data_dir, monkeypatch, decision_n, expected):
    run_id, version = _draft(tmp_data_dir)
    _administration(tmp_data_dir, run_id, engine_on=True)
    monkeypatch.setattr(stats, "agreement_by_engine", lambda labels, partition_of, **k: {
        "decision": stats.EngineAgreement("decision", decision_n,
                                          None if decision_n < 60 else 0.70, decision_n < 60),
        "llm_engine_off": stats.EngineAgreement("llm_engine_off", 60, 0.74, False),
    })
    update = stats.open_stats(data_dir=tmp_data_dir).promote(ORCH_COHORT_ID, package_version=version)
    stored = _stored_verdicts(tmp_data_dir, version)
    assert {v for v in stored if v is not None} == {expected}, stored
    assert update.noninferiority_outcomes.get("C1") == f"recorded {expected if expected != 'true' else True}", (
        update.noninferiority_outcomes)


def _package_rows(data_dir, version: str) -> dict[str, list[tuple]]:
    """Every row of every table in the package's file, minus minted ids, version-derived
    columns and timestamps (the twin's ids differ by construction)."""
    package_id = version.rpartition("@")[0]
    out: dict[str, list[tuple]] = {}
    with sqlite3.connect(Path(data_dir) / "packages" / f"{package_id}.pkg.sqlite") as c:
        c.row_factory = sqlite3.Row
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        for table in sorted(tables):
            rows = c.execute(f"SELECT * FROM {table}").fetchall()
            out[table] = sorted(
                tuple((k, row[k]) for k in row.keys()
                      if not k.endswith(("_id", "_at", "_hash", "_ref")) and k not in ("version",))
                for row in rows)
    return out


def test_tc_stats_38_c_an_engine_off_administration_stores_nothing(tmp_data_dir, tmp_path, monkeypatch):
    # The twin: the same engine-off administration promoted with the verdict step removed.
    # Every column of every row must come out the same, the verdict column included (NULL).
    twin = tmp_path / "twin"
    for sub in ("packages", "cohorts", "blobs"):
        (twin / sub).mkdir(parents=True, exist_ok=True)
    twin_run, twin_version = _draft(twin)
    _administration(twin, twin_run, engine_on=False)
    with monkeypatch.context() as m:
        m.setattr(stats, "_record_noninferiority_verdicts", lambda *a, **k: {})
        stats.open_stats(data_dir=twin).promote(ORCH_COHORT_ID, package_version=twin_version)

    run_id, version = _draft(tmp_data_dir)
    _administration(tmp_data_dir, run_id, engine_on=False)
    called = []
    monkeypatch.setattr(stats, "agreement_by_engine",
                        lambda *a, **k: called.append(1) or {})
    update = stats.open_stats(data_dir=tmp_data_dir).promote(ORCH_COHORT_ID, package_version=version)
    mine, theirs = _package_rows(tmp_data_dir, version), _package_rows(twin, twin_version)
    assert mine == theirs, (
        "an engine-off promote changed a package-tier row the verdict step does not own: "
        f"{sorted(t for t in mine if mine[t] != theirs.get(t))}")
    assert not called, "an engine-off promote measured engine agreement"
    assert all(value is None for value in _stored_verdicts(tmp_data_dir, version)), (
        "an engine-off administration wrote a verdict (NFR-SYS-14: the column stays NULL)")
    assert update.noninferiority_outcomes == {}
