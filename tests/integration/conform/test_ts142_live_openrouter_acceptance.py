"""TS-142 (#617): the live OpenRouter acceptance makes real calls on every leg.

Cases: `TC-CONFORM-17`, `TC-CONFORM-18`, `TC-CONFORM-C17` (operator-requirements test plan §5.3;
design delta §3.3, `FR-CONFORM-17/18`, `CT-CONFORM-17`). The re-specified `TC-CONFORM-04` arm
lives beside the original case in `test_tc_conform_04_full_pipeline_differential.py`.

Rung 4, `live`, nightly, E2, synthetic corpus only (`FR-CONFORM-02`). **No fast-tier case stands
in for these** (plan §3 item 3): the whole point of the tier is that the model boundary is real,
so there is deliberately no offline arm here. `RecordedFixtureProvider` appears in this tier only
as the divergence oracle (FR-CONFORM-06's machinery), never as a leg's transport.

**#618 landed the surface** (`aeh.conform:run_live_acceptance`): the entry point, the report
type and the per-leg accounting the vocabulary names below are implemented in
`src/aeh/conform/live_acceptance.py`.

**Gate order, and why it differs from `TC-CONFORM-04`'s.** Each case checks
`OPENROUTER_API_KEY` *first* and skips naming it when unset; only then does it `require()` the
unbuilt surface (`NotImplementedYet` naming #618), and only after that does it resolve a config
or open a socket. So a box with no key cannot spend anything, and a box with a key but no #618
fails for the stated reason before any request leaves it.

**One run, three cases.** The plan reads 17, 18 and C17 off *"the same run"*; three runs would be
three times the spend and three different samples of a stochastic gate. The run is memoised
module-level and started inside the first test body that needs it (not in a fixture, so a
not-yet-built surface reports FAIL naming #618 rather than a setup ERROR).
"""

from __future__ import annotations

import dataclasses
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from tests.support.conform_vocabulary import (
    CT_CONFORM_17_KEYS,
    DECISION_ACCEPTED_RATE,
    DECISION_FALLBACK_RATE,
    DECISION_LEG_EXTRA_KEYS,
    EXTREME_KEY,
    EXTREME_NEVER_ACCEPTED,
    EXTREME_NEVER_FELL_BACK,
    GATE_CONFIDENCE_THRESHOLD,
    GATE_KEY,
    LEG_DECISION,
    LEG_JUDGE,
    LEG_MODEL_REFS,
    LEG_SYNTHESIS,
    LEG_VISION,
    LIVE_ACCEPTANCE_CONFIG_DEFAULT,
    LIVE_ACCEPTANCE_CONFIG_ENV,
    LIVE_ACCEPTANCE_ENTRY,
    LIVE_CALLS,
    LIVE_COST,
    LIVE_LEG_KEYS,
    LIVE_LEGS,
    RECORDED_FIXTURE_DISPATCH,
    REPORT_FAILED_LEGS,
    REPORT_INVALID_EXTREMES,
    REPORT_LEGS,
    REPORT_PER_CRITERION,
    REPORT_RUN_ID,
    REPORT_VALID,
    live_metric_name,
    require_openrouter_key,
)
from tests.support.impl import CONFORM_MODULE, require

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live,
    pytest.mark.slow,
]

ISSUE = "#618"

#: The synthetic cohort the run is consented under (FR-CONFORM-02; the `M-CONF` gate refuses
#: anything else on a remote profile).
COHORT_ID = "c-live-acceptance"

_RUN: dict[str, Any] = {}


@dataclasses.dataclass(frozen=True)
class _LiveRun:
    run_config: Any
    cohort: Any
    cfg: Any
    data_dir: Path
    report: Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _import_full_migration_chain() -> None:
    """CLAUDE.md: before the first store open in a process, import all eleven contributors."""
    import aeh.agg  # noqa: F401
    import aeh.det  # noqa: F401
    import aeh.extract  # noqa: F401
    import aeh.grade  # noqa: F401
    import aeh.ingest  # noqa: F401
    import aeh.integ  # noqa: F401
    import aeh.judge  # noqa: F401
    import aeh.orch  # noqa: F401
    import aeh.pkg  # noqa: F401
    import aeh.review  # noqa: F401
    import aeh.synth  # noqa: F401


def _resolve_live_config():
    """The reference live config, resolved through the production path with the real env.

    `TC-CONFORM-17`: *"the OpenRouter profile with the default engine, no recorded fixture
    bound (asserted)"*. Both halves are asserted here, at run start, before anything dispatches.
    """
    from aeh.conf import CohortRef, effective_config, parse_config_document, resolve_run_config

    path = Path(os.environ.get(LIVE_ACCEPTANCE_CONFIG_ENV) or LIVE_ACCEPTANCE_CONFIG_DEFAULT)
    if not path.is_absolute():
        path = _repo_root() / path
    document = parse_config_document(path.read_text(encoding="utf-8"), "toml")
    cfg = effective_config(document, os.environ)

    # No recorded fixture bound: `HARNESS_FIXTURE_DIR` is what binds the replay on dev-ci.
    assert not cfg.get("HARNESS_FIXTURE_DIR") and not os.environ.get("HARNESS_FIXTURE_DIR"), (
        "TC-CONFORM-17: HARNESS_FIXTURE_DIR is set, so the run would replay recordings. The live "
        "acceptance binds no recorded fixture on any leg (FR-CONFORM-17)."
    )
    # The *default* engine: the key is not set anywhere, so the profile's default decides.
    assert "HARNESS_DECISION_ENGINE" not in cfg, (
        f"TC-CONFORM-17: {path.name} (or the environment) sets HARNESS_DECISION_ENGINE="
        f"{cfg.get('HARNESS_DECISION_ENGINE')!r}. The acceptance runs the profile's *default* "
        f"engine (FR-CONF-29: jev on the OpenRouter profiles); a pinned value — 'off' above all — "
        f"is the configuration this test exists to retire (design delta §3.3)."
    )
    cohort = CohortRef(cohort_id=COHORT_ID, consent_class="synthetic")
    run_config = resolve_run_config(cfg, cohort)
    assert run_config.backend_profile in {"dev-ci", "cloud-hosted"}, (
        f"TC-CONFORM-17 runs on the OpenRouter profile; the config resolved "
        f"{run_config.backend_profile!r}"
    )
    assert run_config.decision_engine is not None, (
        f"TC-CONFORM-17: {run_config.backend_profile} resolved the decision engine off with "
        f"HARNESS_DECISION_ENGINE unset. FR-CONF-29's default on the OpenRouter profiles is jev, "
        f"and the acceptance must exercise the Jev leg (R-3)."
    )
    return run_config, cohort, cfg


def _live_run(tmp_path_factory) -> _LiveRun:
    """The one live run all three cases read. Key first, then the blocker, then the network."""
    require_openrouter_key()
    run_live_acceptance = require(CONFORM_MODULE, LIVE_ACCEPTANCE_ENTRY, issue=ISSUE)
    # A failed run is cached too, so the other two cases re-raise it instead of paying for the
    # whole live pipeline again.
    if "error" in _RUN:
        raise _RUN["error"]
    if "run" not in _RUN:
        try:
            _import_full_migration_chain()
            run_config, cohort, cfg = _resolve_live_config()
            data_dir = tmp_path_factory.mktemp("live-acceptance")
            report = run_live_acceptance(run_config, cohort=cohort, data_dir=data_dir,
                                         config=cfg)
        except Exception as error:
            _RUN["error"] = error
            raise
        _RUN["run"] = _LiveRun(run_config, cohort, cfg, data_dir, report)
    return _RUN["run"]


def _field(report: Any, name: str) -> Any:
    value = getattr(report, name, None)
    assert value is not None, (
        f"the live acceptance report has no {name!r}; see tests/support/conform_vocabulary.py "
        f"(TS-142) for the surface this case reads"
    )
    return value


def _as_set(value: Any) -> set[str]:
    return {value} if isinstance(value, str) else set(value)


def _open_store(data_dir: Path) -> Any:
    from aeh.store import open_store

    return open_store(data_dir)


# --- TC-CONFORM-17 ----------------------------------------------------------------------------


def test_tc_conform_17_every_leg_made_real_calls_with_recorded_models_and_metrics(tmp_path_factory):
    """`TC-CONFORM-17` (P0): per leg, `live_calls`, `live_tokens_in`, `live_tokens_out`,
    `live_cost` each > 0; each leg's model ref recorded; the figures land in `run_metrics`.

    *A green run with no real calls is a failure, not a pass.* Positivity of all four on every
    leg is the oracle, and `live_cost > 0` doubles as the no-fixture proof: the recorded double
    reports a null cost (CT-PROV-03), so a leg that replayed cannot carry a positive one.
    """
    run = _live_run(tmp_path_factory)
    legs = _field(run.report, REPORT_LEGS)

    missing = [leg for leg in LIVE_LEGS if leg not in legs]
    assert not missing, (
        f"TC-CONFORM-17: the report has no figures for {missing}. FR-CONFORM-17 requires real "
        f"calls on every leg the profile uses: vision, judge panel, synthesis, Jev decision."
    )
    for leg in LIVE_LEGS:
        figures = legs[leg]
        for key in LIVE_LEG_KEYS:
            value = figures.get(key)
            assert value is not None and Decimal(str(value)) > 0, (
                f"TC-CONFORM-17: leg {leg!r} reports {key}={value!r}. Every leg must make real "
                f"calls with real token usage and a real cost; a zero here is a leg that did "
                f"not run live, and it fails the report (CT-CONFORM-17)."
            )

    # Q-O1: the model ref is *recorded* — and it is the configured one, not merely non-empty.
    cfg = run.run_config
    expected_refs = {
        LEG_VISION: {cfg.transcriber.build_id},
        LEG_DECISION: {cfg.decision_engine.model.build_id},
    }
    # The judge leg is the panel plus whatever real judges an escalation (the config's
    # `escalation_judge` list) or the off-panel check seated: every panel build must appear, and
    # nothing outside the configured judges may.
    panel_refs = {ref.build_id for ref in cfg.panel}
    allowed_judges = panel_refs | {
        str(entry.get("build_id")) for entry in (run.cfg.get("escalation_judge") or ())
    }
    if cfg.off_panel_checker is not None:
        allowed_judges.add(cfg.off_panel_checker.build_id)
    for leg in LIVE_LEGS:
        refs = _as_set(legs[leg].get(LEG_MODEL_REFS) or ())
        assert refs, f"TC-CONFORM-17: leg {leg!r} records no model ref (Q-O1)."
        assert RECORDED_FIXTURE_DISPATCH not in refs, (
            f"TC-CONFORM-17: leg {leg!r} was answered by the recorded fixture double."
        )
        if leg == LEG_JUDGE:
            assert panel_refs <= refs <= allowed_judges, (
                f"TC-CONFORM-17: the judge leg called {sorted(refs)}; it must include every panel "
                f"build {sorted(panel_refs)} and nothing beyond the configured judges "
                f"{sorted(allowed_judges)}."
            )
        if leg in expected_refs:
            assert refs == expected_refs[leg], (
                f"TC-CONFORM-17: leg {leg!r} called {sorted(refs)}; the resolved config names "
                f"{sorted(expected_refs[leg])}."
            )
    assert not tuple(_field(run.report, REPORT_FAILED_LEGS) or ()), (
        f"TC-CONFORM-17: the report lists zero-call legs {run.report.failed_legs}."
    )

    # The figures land in the run's metrics (FR-CONFORM-17's last sentence).
    store = _open_store(run.data_dir)
    try:
        rows = store.durable().query(
            "SELECT metric, value FROM run_metrics WHERE run_id = :r",
            r=_field(run.report, REPORT_RUN_ID),
        )
    finally:
        store.close()
    stored: dict[str, list[float]] = {}
    for row in rows:
        stored.setdefault(row["metric"], []).append(float(row["value"]))
    for leg in LIVE_LEGS:
        for key in LIVE_LEG_KEYS:
            name = live_metric_name(leg, key)
            assert name in stored, (
                f"TC-CONFORM-17: run_metrics has no {name!r} row for run "
                f"{run.report.run_id}. The report's figures must be recorded in the run's metrics."
            )
            assert sum(stored[name]) == pytest.approx(float(legs[leg][key])), (
                f"TC-CONFORM-17: run_metrics {name!r} = {stored[name]} but the report says "
                f"{legs[leg][key]}. The durable figure and the report disagree."
            )


# --- TC-CONFORM-18 ----------------------------------------------------------------------------


def _rate(value: Any) -> float:
    """A rate; `None` (no prescreens on the criterion) reads as 0 — the engine never acted."""
    return 0.0 if value is None else float(value)


def test_tc_conform_18_accepted_and_fallback_both_nonzero_per_criterion_else_invalid(tmp_path_factory):
    """`TC-CONFORM-18` (P0): per criterion, `decision_accepted_rate` > 0 **and**
    `decision_fallback_rate` > 0; either extreme marks the run invalid, naming the extreme and
    the gate values. Band agreement is recorded per criterion.

    Two steps, in order. First the report must *apply the rule correctly* — its verdict and its
    named extremes are recomputed here from its own rates, which are themselves cross-checked
    against the CT-JUDGE-28 figures in the store. Then the run must *be* valid: a misconfigured
    gate that silently graded LLM-only (RISK-116) turns the nightly red.
    """
    run = _live_run(tmp_path_factory)
    from aeh.judge.metrics import decision_engine_metrics

    conform = require(CONFORM_MODULE)
    run_id = _field(run.report, REPORT_RUN_ID)
    per_criterion = _field(run.report, REPORT_PER_CRITERION)

    store = _open_store(run.data_dir)
    try:
        metrics = decision_engine_metrics(store.cohort(run.cohort.cohort_id), run_id)
    finally:
        store.close()

    # Same submissions, same cells: the report's criteria are the ones the engine prescreened.
    assert set(per_criterion) == set(metrics.per_criterion), (
        f"TC-CONFORM-18: the report covers criteria {sorted(per_criterion)} but the decision "
        f"engine prescreened {sorted(metrics.per_criterion)}. FR-CONFORM-18 runs the engine on "
        f"the same submissions as the panel, and reports every criterion."
    )
    assert per_criterion, "TC-CONFORM-18: no criterion was decided at all."

    threshold = Decimal(str(run.run_config.decision_engine.confidence_threshold))
    expected_extremes: dict[str, set[str]] = {}
    for criterion, figures in per_criterion.items():
        stored = metrics.per_criterion[criterion]
        for key in (DECISION_ACCEPTED_RATE, DECISION_FALLBACK_RATE):
            assert figures.get(key) == pytest.approx(getattr(stored, key)), (
                f"TC-CONFORM-18: {criterion} {key} is {figures.get(key)!r} in the report and "
                f"{getattr(stored, key)!r} in decision_engine_metrics (CT-JUDGE-28)."
            )
        # Band agreement, the live form of FR-CONFORM-10/11, under the CT-CONFORM-15 names.
        for key in conform.DECISION_REPORT_KEYS:
            assert key in figures, (
                f"TC-CONFORM-18: {criterion} records no {key!r}; Jev-vs-LLM-median band "
                f"agreement is recorded per criterion."
            )
        for key in ("decision_band_exact_agreement", "decision_band_adjacent_agreement"):
            value = figures[key]
            assert (isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
                    and 0 <= value <= 1), (
                f"TC-CONFORM-18: {criterion} {key}={value!r} is not a measured agreement."
            )
        extremes = set()
        if _rate(figures.get(DECISION_ACCEPTED_RATE)) == 0:
            extremes.add(EXTREME_NEVER_ACCEPTED)
        if _rate(figures.get(DECISION_FALLBACK_RATE)) == 0:
            extremes.add(EXTREME_NEVER_FELL_BACK)
        if extremes:
            expected_extremes[criterion] = extremes

    named = dict(getattr(run.report, REPORT_INVALID_EXTREMES, None) or {})
    assert set(named) == set(expected_extremes), (
        f"TC-CONFORM-18: the report names extremes on {sorted(named)}; the rates put "
        f"{sorted(expected_extremes)} at an extreme."
    )
    for criterion, entry in named.items():
        assert _as_set(entry[EXTREME_KEY]) == expected_extremes[criterion], (
            f"TC-CONFORM-18: {criterion} is named {entry[EXTREME_KEY]!r}; its rates say "
            f"{sorted(expected_extremes[criterion])}."
        )
        gate = entry[GATE_KEY]
        assert Decimal(str(gate[GATE_CONFIDENCE_THRESHOLD])) == threshold, (
            f"TC-CONFORM-18: {criterion}'s invalidity names gate {gate!r}; the run's frozen "
            f"threshold is {threshold}. The report must name the gate values that produced it."
        )

    failed_legs = tuple(getattr(run.report, REPORT_FAILED_LEGS, None) or ())
    expected_valid = not expected_extremes and not failed_legs
    assert getattr(run.report, REPORT_VALID) is expected_valid, (
        f"TC-CONFORM-18: the report says valid={run.report.valid!r}; the rule gives "
        f"{expected_valid} (extremes {expected_extremes}, zero-call legs {failed_legs})."
    )
    assert expected_valid, (
        f"TC-CONFORM-18: the live acceptance is INVALID — {expected_extremes or failed_legs}. "
        f"Never accepting means the gate silently graded LLM-only; never falling back means the "
        f"gate accepts everything. Either is a misconfigured gate (threshold {threshold}), not a "
        f"passing test (FR-CONFORM-18, RISK-116)."
    )


# --- TC-CONFORM-C17 ---------------------------------------------------------------------------


def test_tc_conform_c17_report_key_set_carries_the_ct_conform_17_names(tmp_path_factory):
    """`TC-CONFORM-C17` (P1): the report's key set ⊇ the CT-CONFORM-17 names, with the
    CT-JUDGE-28 names on the decision leg. **Breaks if** a key is renamed.

    ⊇ rather than equality on the keys (the plan's Expected column), because a leg also carries
    its model refs; set *equality* is asserted where the clause enumerates — the leg set. Plus
    the clause's failure half: a leg with zero calls fails the report.
    """
    run = _live_run(tmp_path_factory)
    from aeh.judge.metrics import DecisionEngineMetrics

    judge_names = {f.name for f in dataclasses.fields(DecisionEngineMetrics)}
    assert set(DECISION_LEG_EXTRA_KEYS) <= judge_names, (
        f"TC-CONFORM-C17: {sorted(set(DECISION_LEG_EXTRA_KEYS) - judge_names)} are not "
        f"CT-JUDGE-28 names any more; the live report must carry the CT-JUDGE-28 names."
    )

    legs = _field(run.report, REPORT_LEGS)
    assert set(legs) == set(LIVE_LEGS), (
        f"TC-CONFORM-C17: the report's legs are {sorted(legs)}; CT-CONFORM-17 names "
        f"{sorted(LIVE_LEGS)}. A leg missing from the report is a leg nobody checked."
    )
    for leg in LIVE_LEGS:
        missing = set(LIVE_LEG_KEYS) - set(legs[leg])
        assert not missing, f"TC-CONFORM-C17: leg {leg!r} lacks {sorted(missing)}."
    missing = CT_CONFORM_17_KEYS - set(legs[LEG_DECISION])
    assert not missing, f"TC-CONFORM-C17: the decision leg lacks {sorted(missing)}."

    zero_call = {leg for leg in LIVE_LEGS if float(legs[leg][LIVE_CALLS]) == 0}
    failed = set(getattr(run.report, REPORT_FAILED_LEGS, None) or ())
    assert failed == zero_call, (
        f"TC-CONFORM-C17: zero-call legs are {sorted(zero_call)} but the report fails "
        f"{sorted(failed)}. CT-CONFORM-17: a leg with zero calls fails the report."
    )
    if zero_call:
        assert getattr(run.report, REPORT_VALID) is False, (
            f"TC-CONFORM-C17: {sorted(zero_call)} made no calls and the report is still valid."
        )
    # The synthesis leg is the one with no RunConfig field behind it, so its ref is the easiest
    # to leave unrecorded; C17 names it explicitly.
    assert legs[LEG_SYNTHESIS].get(LEG_MODEL_REFS), "TC-CONFORM-C17: synthesis records no model ref."
