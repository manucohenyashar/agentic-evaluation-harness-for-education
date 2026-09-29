"""TS-137 (#548): design 1.9's clause suites — M-STATS, M-REVIEW, M-PKG, M-INGEST, M-STORE.

| Case | Clause | Assertion (breaks if the clause is broken) |
|---|---|---|
| TC-STATS-C09 (amended) | CT-STATS-09 | both figures return no-data, never 0.0, at n = 0 and n = 4 |
| TC-STATS-C25 | CT-STATS-25 | the FR-STATS-28 surface exists as stated; 4 labels → `below_min_n` from M-STATS itself |
| TC-STATS-C26 | CT-STATS-26 | one `NoValidationData` class; every absence value from the five readers is an instance carrying `reason` and `n` |
| TC-REVIEW-C24 | CT-REVIEW-24 | a data dir holding only `durable.sqlite` still holds only that after `open_review` on an unknown run |
| TC-REVIEW-C25 | CT-REVIEW-25 | labels from `record_label` and from `act` both carry a backend (the label's; the run's) |
| TC-PKG-C20 | CT-PKG-20 | the verdict domain holds, and `record_noninferiority`'s statements are the only writes of the column |
| TC-INGEST-C22 | CT-INGEST-22 | candidates are a JSON array sorted by (−semantic, id), every element numeric, over generated stores |
| TC-STORE-C19 | CT-STORE-19 | one SQL text per name whatever the import order, and a conflicting registration refused with the registry unchanged |

Implementations are merged (#511, #512, #514, #515, #433, #454, #376), so these land green.
Disclosed: TC-INGEST-C22 runs three generated stores of three matching papers each (seeded),
not fifty affinity sets — each store is a full ingest, and three orderings already exercise the
sort key's both parts.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import os
import random
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.orch  # noqa: F401,E401
import aeh.pkg, aeh.review, aeh.synth  # noqa: F401,E401
from aeh import pkg, review, stats
from aeh.conf import ModelRef
from aeh.store import open_store
from tests.support import broken_stats_fixtures as broken
from tests.support.grade_vocabulary import write_criterion_scores
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

REPO = Path(__file__).resolve().parents[2]


def _label(i, criterion, *, teacher=2, origin="blind_sample"):
    return broken.Label(label_id=f"L{criterion}{i}", criterion_id=criterion, band=2,
                        teacher_band=teacher, origin=origin)


# --- M-STATS --------------------------------------------------------------------------------


@pytest.mark.parametrize("n", [0, 4])
def test_tc_stats_c09_both_figures_are_no_data_below_the_minimum(n, monkeypatch):
    monkeypatch.delenv("HARNESS_REVIEW_OVERRIDE_MIN_N", raising=False)
    s = stats.ValidationStats([_label(i, "C1") for i in range(n)])
    for figure in (s.criterion_override_history("C1"), s.criterion_disagreement_rate("C1")):
        assert isinstance(figure, pkg.NoValidationData), f"n={n}: {figure!r} is a figure, not no-data"
        assert getattr(figure, "override_rate", None) != 0.0 and getattr(figure, "rate", None) != 0.0


def test_tc_stats_c25_the_disagreement_surface_and_its_minimum(monkeypatch):
    monkeypatch.delenv("HARNESS_REVIEW_OVERRIDE_MIN_N", raising=False)
    assert list(inspect.signature(stats.ValidationStats.criterion_disagreement_rate).parameters) == [
        "self", "criterion_id"]
    assert list(inspect.signature(stats.stored_disagreement_rates).parameters) == [
        "store", "package_version_id"]
    four = stats.ValidationStats([_label(i, "C1") for i in range(4)]).criterion_disagreement_rate("C1")
    assert isinstance(four, pkg.NoValidationData) and four.reason == "below_min_n", four
    assert "below_min_n" not in inspect.getsource(review), (
        "the minimum moved into aeh.review (CT-STATS-25: M-STATS owns it)")


def test_tc_stats_c26_one_absence_class_everywhere(tmp_data_dir, monkeypatch):
    monkeypatch.delenv("HARNESS_REVIEW_OVERRIDE_MIN_N", raising=False)
    assert stats.NoValidationData is pkg.NoValidationData
    store = open_store(tmp_data_dir)
    try:
        _o, _r, version = seed_run(store, submissions=("S1",), criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},))
        package_id = version.rpartition("@")[0]
        catalog = pkg.PackageCatalog(store.package(package_id), package_id=package_id)
        empty = stats.ValidationStats([])
        absences = {
            "baseline_for": catalog.baseline_for(version, "C1", "", "edge-local", "pbr"),
            "validation_for": catalog.validation_for(version, "C1", "", "edge-local", "pbr"),
            "criterion_override_history": empty.criterion_override_history("C1"),
            "criterion_disagreement_rate": empty.criterion_disagreement_rate("C1"),
            "agreement": empty.agreement(criterion_id="C1"),
        }
    finally:
        store.close()
    for reader, value in absences.items():
        assert isinstance(value, pkg.NoValidationData), f"{reader} returned {value!r}"
        assert hasattr(value, "reason") and hasattr(value, "n"), f"{reader}'s absence lacks reason/n"


# --- M-REVIEW -------------------------------------------------------------------------------


def test_tc_review_c24_an_unknown_run_leaves_a_bare_data_dir_bare(tmp_data_dir):
    data = Path(tmp_data_dir) / "bare"  # the fixture's own dir already holds a store skeleton
    data.mkdir(parents=True, exist_ok=True)
    (data / "durable.sqlite").write_bytes(b"")
    with pytest.raises(review.UnknownRunError):
        review.open_review(data, run_id="run-nope")
    assert sorted(p.name for p in data.iterdir()) == ["durable.sqlite"]


def _cloud_cfg():
    from aeh.conf import CohortRef, resolve_run_config
    from tests.support.conf_builders import hosted_cfg

    panel = tuple(ModelRef(role="judge", provider="openrouter",
                           build_id=f"openrouter/judge-{i}@2026-01-01", quantization=None)
                  for i in range(3))
    return resolve_run_config(hosted_cfg("cloud-hosted", panel=panel),
                              CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"))


def test_tc_review_c25_both_write_paths_record_a_backend(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        _o, run_id, _v = seed_run(store, submissions=("S1",), criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},), cfg=_cloud_cfg())
        write_criterion_scores(store.cohort(ORCH_COHORT_ID), [("S1", "C1", "B1", 0.0, "provisional")])
    finally:
        store.close()
    review.record_label(data_dir=tmp_data_dir, label=dataclasses.replace(
        _label(1, "C1"), backend_profile="edge-local"))  # not the run's profile
    service = review.open_review(tmp_data_dir, run_id=run_id)
    try:
        queue = service.build_queue(run_id=run_id, budget_minutes=600)
        items = [m for e in queue.shown for m in (getattr(e, "members", None) or (e,))]
        acted = service.act(items[0], action="edit", new_band="B2")
    finally:
        service.close()
    with sqlite3.connect(Path(tmp_data_dir) / "durable.sqlite") as c:
        backends = dict(c.execute("SELECT label_id, backend_profile FROM label").fetchall())
    assert backends["LC11"] == "edge-local", backends
    assert backends[acted] == "cloud-hosted", (
        f"the act path wrote {backends[acted]!r}, not the run's frozen cloud-hosted")


# --- M-PKG ----------------------------------------------------------------------------------


def test_tc_pkg_c20_the_verdict_column_has_one_writer(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        _o, _r, version = seed_run(store, submissions=("S1",), criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},))
    finally:
        store.close()
    for verdict in ("true", "false", "insufficient_data"):
        assert pkg.record_noninferiority(tmp_data_dir, package_version_id=version,
                                         criterion_id="C1", verdict=verdict).recorded
    with pytest.raises(sqlite3.IntegrityError):
        pkg.record_noninferiority(tmp_data_dir, package_version_id=version, criterion_id="C1",
                                  verdict="maybe")
    # Every declared statement of every module, by its assembled text (a multi-literal INSERT
    # is one Statement here, whatever its source spelling).
    import importlib
    import pkgutil

    import aeh
    from aeh.store import Statement

    writers, seen = set(), set()
    for info in pkgutil.iter_modules(aeh.__path__):
        module = importlib.import_module(f"aeh.{info.name}")
        for attr, registry in vars(module).items():
            if not attr.endswith("STATEMENTS") or not isinstance(registry, dict) or id(registry) in seen:
                continue
            seen.add(id(registry))
            for name, statement in registry.items():
                sql = " ".join(str(statement).split()).upper()
                if isinstance(statement, Statement) and sql.startswith(("INSERT", "UPDATE", "REPLACE"))                         and "DECISION_ENGINE_NONINFERIOR" in sql:
                    writers.add((name, sql))
    names = {name for name, _sql in writers}
    assert names == {"insert_validation_noninferiority", "update_validation_noninferiority"}, (
        f"statements writing decision_engine_noninferior: {sorted(names)} (CT-PKG-20: one writer)")
    assert len(writers) == 2, "a writer name carries two SQL texts"
    assert names <= set(pkg.PKG_STATEMENTS), "the writer statements are not M-PKG's own"


# --- M-INGEST -------------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("seed", [7, 11, 23])
def test_tc_ingest_c22_candidates_are_sorted_with_numeric_semantics(tmp_data_dir, seed):
    from tests.integration.ingest.test_ts136_multi_lineage import _Papers

    rng = random.Random(seed)
    vocabulary = [f"w{i}" for i in range(40)]
    answer = rng.sample(vocabulary, 12)
    fx = _Papers(tmp_data_dir, f"ts137-c22-{seed}")
    try:
        fx.put_paper("Assessment Alpha", ("Q1", "Q2"))
        for k in range(3):
            shared = rng.sample(answer, rng.randint(0, 6))
            other = rng.sample([w for w in vocabulary if w not in answer], 6)
            fx.put_paper(f"Assessment P{k}", ("Q7", "Q8"),
                         text={"Q7": " ".join(shared or ["none"]), "Q8": " ".join(other)})
        source = fx.put_submission("History Final", {"Q7": " ".join(answer[:6]),
                                                     "Q8": " ".join(answer[6:])}, tag=f"c22-{seed}")
        report = fx.submit(source)
        assert report.gates["v4"] == "mismatch"
        raw = fx.proposals()[0]["candidates"]
        candidates = json.loads(raw)
        assert isinstance(candidates, list) and len(candidates) == 3
        assert all(isinstance(c["semantic"], (int, float)) for c in candidates)
        keys = [(-c["semantic"], c["assessment_document_id"]) for c in candidates]
        assert keys == sorted(keys), f"candidates are not ordered by (-semantic, id): {keys}"
    finally:
        fx.close()


# --- M-STORE --------------------------------------------------------------------------------


_C19 = r"""
import importlib, json, pkgutil, sys
import aeh
from aeh.store import Statement, STATEMENTS, StatementConflictError
mods = sorted(m.name for m in pkgutil.iter_modules(aeh.__path__))
if sys.argv[1] == "reverse":
    mods = mods[::-1]
for m in mods:
    importlib.import_module("aeh." + m)
texts, seen = {}, set()
for m in mods:
    for attr, val in vars(sys.modules["aeh." + m]).items():
        if attr.endswith("STATEMENTS") and isinstance(val, dict) and id(val) not in seen:
            seen.add(id(val))
            for name, st in val.items():
                if isinstance(st, Statement):
                    texts.setdefault(name, set()).add(str(st))
before = dict(STATEMENTS)
try:
    STATEMENTS["select_document_head"] = Statement("SELECT 2 AS other")
    refused = False
except StatementConflictError:
    refused = True
print(json.dumps({"conflicts": sorted(n for n, v in texts.items() if len(v) > 1),
                  "resolved": {n: sorted(v)[0] for n, v in texts.items()},
                  "refused": refused, "unchanged": dict(STATEMENTS) == before}))
"""


@pytest.mark.integration
def test_tc_store_c19_statement_names_are_import_order_independent_and_guarded():
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO / "src"), str(REPO)])}
    out = {}
    for order in ("alphabetical", "reverse"):
        done = subprocess.run([sys.executable, "-c", _C19, order], capture_output=True, text=True,
                              env=env, cwd=str(REPO), timeout=300)
        assert done.returncode == 0, done.stderr[-2000:]
        out[order] = json.loads(done.stdout.strip().splitlines()[-1])
    for order, result in out.items():
        assert result["conflicts"] == [], (order, result["conflicts"])
        assert result["refused"] and result["unchanged"], (order, result)
    assert out["alphabetical"]["resolved"] == out["reverse"]["resolved"]
