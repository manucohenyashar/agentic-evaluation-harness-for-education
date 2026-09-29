"""TS-135 (#546): every grade view names the run that produced the grade.

| Case | Oracle |
|---|---|
| TC-CONSOLE-50 | Run A (`edge-local`, package A, engine off) and run B (`cloud-hosted`, package B, the `openrouter-jev` decision engine). S9, S12, S13 and S14 for each show that run's package version and `backend profile`, B adds `decision engine openrouter-jev <build>`, A carries no engine line, B never shows `edge-local-q4`, and no page carries a confidence figure; the storeless double still renders `GRADE_PROVENANCE` |
| SEC-24 | With `OPENROUTER_API_KEY=sk-or-SENTINEL…` and a non-default `HARNESS_JEV_OPENROUTER_URL` in the environment, no page byte carries the sentinel, `sk-or-` or the URL |

Implemented by #533 (merged), so these land green.

Disclosed: the plan names package "v1"/"v2"; the fixture uses two packages (`pkg-ts135a`,
`pkg-ts135b`), whose version ids are what each run froze — the oracle (each page shows ITS run's
version) is unchanged.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.pkg  # noqa: F401,E401
import aeh.review, aeh.synth  # noqa: F401,E401
from aeh.console import GRADE_PROVENANCE, SCREENS, build_console
from aeh.orch import Orchestrator
from aeh.store import open_store
from tests.support.grade_vocabulary import write_criterion_scores
from tests.support.orch_run import orch_cfg, seed_cohort, seed_package

pytestmark = pytest.mark.integration

JEV_BUILD = "openrouter/typesafe/jev-1.13@2026-09-17"
SENTINEL = "sk-or-SENTINEL-ts135-0000"
JEV_URL = "https://jev.example.invalid/api/v1/systemone"
CRITERIA = [{"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"}]


class _Seam:
    def verify_retention(self, refs):
        from aeh.prov import RetentionReport
        return RetentionReport(confirmed=tuple(refs), unconfirmed=())

    def estimate_cost(self, unit):
        return Decimal("0.01")


def _cloud_engine_config():
    from aeh.conf import CohortRef, ModelRef, resolve_run_config
    from tests.support.conf_builders import hosted_cfg

    panel = tuple(ModelRef(role="judge", provider="openrouter",
                           build_id=f"openrouter/judge-{i}@2026-01-01", quantization=None)
                  for i in range(3))
    return resolve_run_config(
        hosted_cfg("cloud-hosted", panel=panel, HARNESS_COST_CEILING="12.50",
                   HARNESS_DECISION_ENGINE="jev", HARNESS_JEV_BUILD=JEV_BUILD),
        CohortRef(cohort_id="c-2026-7B-orch", consent_class="synthetic"))


def _pages(app, run_id: str, ref: str, version: str) -> dict[str, str]:
    return {
        "S9": app.render(SCREENS["S9"], id=run_id).html,
        "S12": app.render(SCREENS["S12"], id=run_id).html,
        "S13": app.render(SCREENS["S13"], ref=ref).html,
        "S14": app.render(SCREENS["S14"], version=version).html,
    }


@pytest.fixture
def two_runs(tmp_data_dir, monkeypatch):
    from aeh.prov import JevOpenRouterProvider

    monkeypatch.setenv("OPENROUTER_API_KEY", SENTINEL)
    monkeypatch.setenv("HARNESS_JEV_OPENROUTER_URL", JEV_URL)
    store = open_store(tmp_data_dir)
    seed_cohort(store, ["SA1"], cohort_id="c-ts135-a")
    version_a = seed_package(store, CRITERIA, package_id="pkg-ts135a")
    run_a = Orchestrator(store).create_run("c-ts135-a", version_a, orch_cfg("edge-local"))
    seed_cohort(store, ["SB1"], cohort_id="c-ts135-b")
    version_b = seed_package(store, CRITERIA, package_id="pkg-ts135b")
    decider = JevOpenRouterProvider(api_key=SENTINEL, retention_answers=lambda b: "zero-retention")
    run_b = Orchestrator(store, provider=_Seam(), decision_provider=decider).create_run(
        "c-ts135-b", version_b, _cloud_engine_config())
    write_criterion_scores(store.cohort("c-ts135-a"), [("SA1", "C1", "B1", 1.0, "provisional")])
    write_criterion_scores(store.cohort("c-ts135-b"), [("SB1", "C1", "B1", 1.0, "provisional")])
    try:
        yield store, (run_a, "SA1", version_a), (run_b, "SB1", version_b)
    finally:
        store.close()


def test_tc_console_50_every_grade_view_names_its_own_run(two_runs):
    store, (run_a, ref_a, version_a), (run_b, ref_b, version_b) = two_runs
    app = build_console(store=store)
    pages_a = _pages(app, run_a, ref_a, version_a)
    pages_b = _pages(app, run_b, ref_b, version_b)
    for screen, html in pages_a.items():
        assert f"package version {version_a}" in html, f"A's {screen} does not name {version_a}"
        assert "backend profile edge-local" in html, f"A's {screen} does not name edge-local"
        assert "decision engine" not in html, f"A's {screen} carries an engine line (engine off)"
    for screen, html in pages_b.items():
        assert f"package version {version_b}" in html, f"B's {screen} does not name {version_b}"
        assert "backend profile cloud-hosted" in html, f"B's {screen} does not name cloud-hosted"
        assert f"decision engine openrouter-jev {JEV_BUILD}" in html, (
            f"B's {screen} does not carry the engine and build: FR-CONSOLE-40")
        assert "edge-local-q4" not in html, f"B's {screen} shows the GRADE_PROVENANCE constant"
    for screen, html in {**pages_a, **pages_b}.items():
        lowered = html.lower()
        assert "confidence" not in lowered and "probability" not in lowered, (
            f"{screen} renders a confidence or probability figure (UAT-12's negative half)")
    storeless = build_console().render(SCREENS["S12"], id="r-unaddressed").html
    assert GRADE_PROVENANCE["backend_profile"] in storeless, (
        "the storeless double no longer renders GRADE_PROVENANCE")


def test_sec_24_no_grade_view_carries_the_credential_or_the_endpoint(two_runs):
    store, (run_a, ref_a, version_a), (run_b, ref_b, version_b) = two_runs
    app = build_console(store=store)
    for run in ((run_a, ref_a, version_a), (run_b, ref_b, version_b)):
        for screen, html in _pages(app, *run).items():
            for forbidden in (SENTINEL, "sk-or-", JEV_URL, "jev.example.invalid"):
                assert forbidden not in html, f"{screen} of {run[0]} carries {forbidden!r}"
