"""TC-STATS-47 (NFR-STATS-07): the validity read and the package record never recompute.

A package version with 1,000 blind labels across 10 administrations, every one promoted. Then
`GET /api/v1/results/validity` and `GET /api/v1/packages/record` are each read 20 times on a
real console, with a spy on every agreement computation M-STATS has. Expected: the spy
records 0 calls during the reads, and the p95 of each read is at most 500 ms on the dev box.

**The wall-clock bound is an env-gated knob** (CLAUDE.md seam 3):
`AEH_TEST_STATS_READ_P95_MS`, default 500 (the plan's dev-box figure). A slower test box raises
it without a code change. The measured p95s are printed and carried in the assertion message.
The case is marked `slow` (no `perf` marker is registered), so the fast tier never gates on a
wall-clock threshold.

**The world, disclosed.** A draw holds at most 25 seats (FR-REVIEW-12), so 1,000 labels over 10
administrations cannot all come through draws. One administration is the validity seed: 24
labels from a real draw and Finish, promoted by `promote_administration`. Its run is the one
the validity read reads. The other nine are 976 labels inserted in the blind flow's column
shape, each administration promoted by `ValidationStats.promote` (the call
`promote_administration` makes). The spy's positive control is a promote after the reads,
which must register calls. Without it, "0 during reads" could mean the spy saw nothing.

One warm-up read of each route runs before the 20 timed ones and is not counted (first-request
import and connection costs).
"""

from __future__ import annotations

import math
import os
import time
from typing import Any

import pytest

from tests.support.label_identity_world import ServedRun
from tests.support.validity_seed import ATOMIC, HOLISTIC, validity_seed

pytestmark = [pytest.mark.integration, pytest.mark.slow]

READS = 20
TOTAL_LABELS = 1000
ADMINISTRATIONS = 10

#: The agreement computations, by name, in every module that defines or imports them: the
#: low-level coefficients, the per-criterion and pooled figures, the engine figures and the
#: `ValidationStats` figure methods. `from x import f` binds f in the importer, so each
#: module's own binding is wrapped.
SPIED_MODULES = ("aeh.stats.agreement", "aeh.stats.administration", "aeh.stats.promotion",
                 "aeh.stats.package_record", "aeh.stats.engines", "aeh.stats.comparisons",
                 "aeh.stats")
SPIED_NAMES = ("_observed_and_expected", "_chance_corrected_coefficient",
               "_weighted_coefficient", "_distance_coefficient", "_corrected_statistics",
               "_band_ordinals", "_per_criterion_kappas", "criterion_figures",
               "cumulative_figures", "agreement_by_engine", "decision_engine_noninferior",
               "decision_gate_calibration")
SPIED_METHODS = ("agreement", "promote", "aggregate", "surface_proxies")


def _p95_bound_ms() -> float:
    return float(os.environ.get("AEH_TEST_STATS_READ_P95_MS", "500"))


class AgreementSpy:
    """Counts every call to the agreement computations, delegating to the real ones."""

    def __init__(self, monkeypatch: Any) -> None:
        import importlib

        from aeh.stats.service import ValidationStats

        self.calls: list[str] = []
        wrapped = 0
        for module_name in SPIED_MODULES:
            module = importlib.import_module(module_name)
            for name in SPIED_NAMES:
                real = getattr(module, name, None)
                if callable(real):
                    monkeypatch.setattr(module, name, self._counting(f"{module_name}.{name}",
                                                                     real))
                    wrapped += 1
        for name in SPIED_METHODS:
            monkeypatch.setattr(ValidationStats, name,
                                self._counting(f"ValidationStats.{name}",
                                               getattr(ValidationStats, name)))
        assert wrapped >= len(SPIED_NAMES), f"fixture: only {wrapped} functions spied"

    def _counting(self, label: str, real: Any) -> Any:
        def counting(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(label)
            return real(*args, **kwargs)

        return counting


def _seed(root):
    """The validity seed (24 real labels, promoted), then nine bulk administrations."""
    from aeh.stats import open_stats

    world, real = validity_seed(root)
    outcome = world.promote(real, "finish")
    assert outcome.promoted, outcome.reason
    source = world.labels(real)[0]
    remaining = TOTAL_LABELS - 24
    sizes = [remaining // 9 + (1 if k < remaining % 9 else 0) for k in range(9)]
    for k, size in enumerate(sizes):
        cohort = f"bulk-{k}"
        rows = []
        for i in range(size):
            criterion = ATOMIC if i % 2 else HOLISTIC
            bands = ("fail", "pass") if criterion == ATOMIC else ("B1", "B2", "B3", "B4")
            system = bands[i % len(bands)]
            teacher = system if i % 5 else bands[(i + 1) % len(bands)]
            rows.append({"label_id": f"label-{cohort}-{i:04d}", "run_id": f"run-{cohort}",
                         "student_ref": f"ref-{cohort}-{i:04d}", "criterion_id": criterion,
                         "system_band": system, "teacher_band": teacher, "band": teacher,
                         "agreed": int(system == teacher), "cohort_id": None})
        world.insert_labels_like(source, rows)
        update = open_stats(world.store.data_dir, cohort_id=cohort).promote(
            cohort, package_version=real.package_version_id)
        assert update.blind_count == size, (cohort, update.blind_count)
    claimed = world.durable_rows("SELECT COUNT(*) AS n, COUNT(DISTINCT cohort_id) AS c "
                                 "FROM label WHERE label_type = 'blind'")
    assert claimed == [{"n": TOTAL_LABELS, "c": ADMINISTRATIONS}], claimed
    return world, real


def _p95(samples: list[float]) -> float:
    """Nearest-rank p95."""
    ordered = sorted(samples)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _timed(console: ServedRun, path: str, **query: Any) -> tuple[list[float], Any]:
    status, body = console.get(path, **query)  # warm-up, not counted
    assert status == 200, body
    samples = []
    for _ in range(READS):
        started = time.perf_counter()
        status, body = console.get(path, **query)
        samples.append((time.perf_counter() - started) * 1000)
        assert status == 200, body
    return samples, body


def test_tc_stats_47_reads_never_recompute_and_answer_within_the_bound(
        tmp_path, monkeypatch, network_guard):
    """TC-STATS-47: 1,000 labels, 10 administrations. The validity read and the package record,
    20 reads each: 0 agreement computations during the reads, p95 <= the bound (500 ms by
    default). A promote after the reads, under the same spy, registers calls (positive
    control)."""
    from aeh.console import serve_console
    from aeh.stats import open_stats

    world, real = _seed(tmp_path / "w")
    try:
        for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
            monkeypatch.delenv(name, raising=False)
        network_guard.uninstall()
        server = serve_console(store=world.store)
        try:
            console = ServedRun(world=real, server=server, port=server.socket.getsockname()[1],
                                root=world.root)
            spy = AgreementSpy(monkeypatch)
            validity_ms, validity = _timed(console, "/api/v1/results/validity",
                                           run_id=real.run_id)
            record_ms, record = _timed(console, "/api/v1/packages/record",
                                       package_version_id=real.package_version_id)
            during_reads = list(spy.calls)
        finally:
            try:
                server.terminate()
            finally:
                network_guard.install()

        # The reads answered what was stored, so the zero below is about real reads.
        assert validity["state"] == "recorded" and len(validity["criteria"]) == 2, validity
        assert record["blind_labels"] == TOTAL_LABELS, record["blind_labels"]
        assert len(record["administrations"]) == ADMINISTRATIONS

        assert during_reads == [], (
            f"{len(during_reads)} agreement computation(s) during the reads, e.g. "
            f"{sorted(set(during_reads))[:5]}: a read must serve stored figures (NFR-STATS-07)")

        # Positive control: the same spy sees a promote's computations.
        source = world.labels(real)[0]
        world.insert_labels_like(source, [
            {"label_id": f"label-control-{i}", "run_id": "run-control", "cohort_id": None,
             "criterion_id": HOLISTIC, "system_band": "B2", "teacher_band": band, "band": band}
            for i, band in enumerate(("B2", "B3", "B2"))])
        open_stats(world.store.data_dir, cohort_id="control").promote(
            "control", package_version=real.package_version_id)
        assert len(spy.calls) > 0, "the spy saw no computation in a promote: it spies nothing"

        bound = _p95_bound_ms()
        measured = {"validity read": _p95(validity_ms), "package record": _p95(record_ms)}
        print(f"\nTC-STATS-47 p95 over {READS} reads (dev box): "
              + ", ".join(f"{name} {value:.1f} ms" for name, value in measured.items())
              + f"; bound {bound:.0f} ms (AEH_TEST_STATS_READ_P95_MS)")
        assert all(value <= bound for value in measured.values()), (
            f"p95 above {bound:.0f} ms: {measured} (raise AEH_TEST_STATS_READ_P95_MS on a "
            "slower box)")
    finally:
        world.close()
