"""`TC-STATS-17` — the replication floor on the live tier: each fixture judgment
run at least three times against the same judge and backend, the per-judge
self-agreement reported **together with** the backend's declared
``deterministic_at_temperature_zero`` capability — the two different claims
they are.

Test plan §5.16 (`TC-STATS-17`), issue #120 (TS-43). Traces to `FR-STATS-16`
(`run_mvvp` step 3). The plan's row: *"Each fixture judgment run at least three
times against the same judge and backend. Per-judge self-agreement reported
together with the backend's declared deterministic_at_temperature_zero
capability, since the two are different claims."* Statistical with stated n,
P0, live.

**The three runs are a replication, not a re-prompt.** One salt is held fixed
(the shipped default, the knob unset), so every run of a unit assembles the
byte-identical request (`TC-JUDGE-14_c`'s reproducibility is what makes this a
replication rather than a second sample), and the same request is dispatched
three times against the same judge and backend — the judge identity the
configuration echo carries (`model_build`, `quantization`), the same provider
instance every time. The order-swap claim is `TC-STATS-16`'s and stays out of
this file: no salt is moved here.

**Stated n.** `n = 4` units x `MVVP_REPLICATION_RUNS` (3) runs = 12 judged
replies; the per-judge self-agreement rate is the unanimous-band fraction over
the four units, computed from the live replies. The floor is the shipped
constant, not this file's arithmetic: the dispatch loop runs exactly
`MVVP_REPLICATION_RUNS` times, so a protocol floor raised to five would be
measured at five, not at a hardcoded three.

**Two claims, one row, never merged.** The measured rate is a statistical
claim at the stated n; ``deterministic_at_temperature_zero`` is the backend's
*declaration* (`CT-PROV-04` — statically declared by `LocalServerProvider`,
no network call). `run_mvvp` step 3 carries both on one row, source-tagged
``declared_by_caller``, and the case makes **no** `rate == 1.0` assertion: a
measured value below 1.0 is the finding the protocol exists to surface,
reported verbatim (`TC-JUDGE-C17` limb 3) — a backend that claims
determinism and measures below 1.0 is exactly the disagreement the row must
be able to carry. Clamping the rate to the claim, or overwriting the claim
with the rate, is the merge the row exists to prevent; the assertions pin
the row's shape, the verbatim figures on both sides of it, and the declared
runs floor.

Environment: E3, a live local model server (Ollama or vLLM-MLX). Marked
`live`, `slow` and `integration`, so the fast tier never selects it and
`pytest -q -m live` picks it up nightly.

**This case has never been executed.** E3 does not exist in this repository —
`CLAUDE.md` states that all work runs locally and no model server is
provisioned. It is written now, against the shipped interfaces, so whoever
stands E3 up inherits the assertion rather than inventing one; the PR says
so explicitly rather than letting a `live`-marked test imply it was ever run.

Not marked `writtenahead`
--------------------------
The marker means *"excluded from `TEST_CMD` until its implementing issue
closes"*, and `writtenahead` tests are registered so the gate can announce
when to unmark them. Neither fits here: `live` already excludes this from the
fast tier, and #120's landing did **not** make the test runnable — it needs
hardware, not code (the TC-JUDGE-21 precedent, verbatim).

Consequence worth stating: a bare `pytest -q` with no marker filter collects
and runs this file, so it appears in the full-suite failure count until E3
exists.
"""

from __future__ import annotations

import os

import pytest

from tests.support.extract_vocabulary import JUDGE_ISSUE
from tests.support.impl import JUDGE_MODULE, PROVIDER_MODULE, STATS_MODULE, require
from tests.support.judge_run import judge_world, warm_judged_modules
from tests.support.judge_vocabulary import EXEMPLAR_SEED_KNOB

pytestmark = [pytest.mark.live, pytest.mark.slow, pytest.mark.integration]

CONF_MODULE = "aeh.conf"
ISSUE = "#120"

#: Four exemplars for the one criterion — the same shape `TC-JUDGE-14` verified its
#: salts under. Here the salt never moves: a replication holds the prompt fixed.
EXEMPLARS = (
    ("C1", "secure"),
    ("C1", "emerging"),
    ("C1", "secure"),
    ("C1", "emerging"),
)

#: The fixture the replication runs over — the stated n's unit count (the runs
#: count is `MVVP_REPLICATION_RUNS`, read from the shipped constant below).
SUBMISSIONS = ("s-17a", "s-17b", "s-17c", "s-17d")
STATED_N = len(SUBMISSIONS)

ASSIGNMENT_TYPE = "extended_response"

TEMPERATURE_KNOB = "HARNESS_JUDGE_TEMPERATURE"


def _world(tmp_data_dir, make_fixture_provider):
    """The store door: a judged package carrying four exemplars, a real extraction
    leg (the fixture transport — extraction is infrastructure, the live condition is
    the judge leg), and the score units leased. Nothing is dispatched here; the
    caller owns the judge boundary."""
    from aeh.orch import STAGE_SCORE
    from aeh.store import open_store

    warm_judged_modules()
    store = open_store(tmp_data_dir)
    provider = make_fixture_provider()
    world = judge_world(
        store,
        provider,
        submissions=SUBMISSIONS,
        panel=1,
        exemplars=EXEMPLARS,
        judge_leg=False,
    )
    units = list(world["orchestrator"].lease("w-tcstats-17", STAGE_SCORE, 64))
    assert len(units) == STATED_N, (
        f"precondition: one score unit per submission expected, got {len(units)}"
    )
    return store, units


def test_tc_stats_17_self_agreement_is_reported_beside_the_backend_declaration(
    tmp_data_dir, make_fixture_provider, monkeypatch
):
    """TC-STATS-17 — three dispatches per unit against the same judge and backend;
    the unanimous-band self-agreement reported verbatim beside the backend's
    declared `deterministic_at_temperature_zero`, on step 3's row, never merged.

    Oracle: statistical with stated n. The rate's value is deliberately NOT
    asserted — a measured value below 1.0 is the finding the protocol exists
    to surface (`TC-JUDGE-C17` limb 3), so the row must carry it whatever it
    is. What is asserted is that the two claims arrive as two claims:

    1. the replication ran at the protocol's floor — `MVVP_REPLICATION_RUNS`
       dispatches per unit, and step 3's `runs_required` says the same number;
    2. the measured rate is verbatim — `measured=True`, `self_agreement ==
       rate`, no not-measured reason on a measured row, no clamp toward the
       backend's declaration;
    3. the declaration rides beside it, source-tagged `declared_by_caller`
       and carrying the value `capabilities()` declared — the two fields are
       the two claims, and neither replaces the other.
    """
    base_url = os.environ.get("LOCAL_INFERENCE_BASE_URL")
    if not base_url:
        pytest.fail(
            "TC-STATS-17 runs on E3 against a live local server; set "
            "LOCAL_INFERENCE_BASE_URL. Skipping would let a nightly tier report "
            "green without ever measuring self-agreement against the backend's "
            "own determinism claim (test plan §4.6)."
        )

    ModelRef = require(CONF_MODULE, "ModelRef", issue=ISSUE)
    LocalServerProvider = require(PROVIDER_MODULE, "LocalServerProvider", issue=ISSUE)
    ScoringWorker = require(JUDGE_MODULE, "ScoringWorker", issue=JUDGE_ISSUE)
    run_mvvp = require(STATS_MODULE, "run_mvvp", issue="#116")
    runs_required = require(STATS_MODULE, "MVVP_REPLICATION_RUNS", issue="#116")
    from aeh.judge import JUDGE_PROMPT_TEMPLATE_V

    # The claim under test is a temperature-zero claim: pin the shipped default
    # rather than inherit whatever the ambient environment set the knob to.
    monkeypatch.delenv(TEMPERATURE_KNOB, raising=False)

    store, units = _world(tmp_data_dir, make_fixture_provider)
    try:
        judge_id = os.environ.get("HARNESS_LIVE_BUILD_ID", "local-model")
        quantization = os.environ.get("HARNESS_LIVE_QUANTIZATION", "q4")
        live_ref = ModelRef(
            role="judge",
            provider="ollama",
            build_id=judge_id,
            quantization=quantization,
        )
        live_provider = LocalServerProvider(base_url=base_url)
        worker = ScoringWorker(store, live_provider, live_ref)

        # One salt, held fixed for the whole case — the byte-identical request is
        # what makes three dispatches a replication (the salt knob stays unset,
        # the shipped default `judge-prompt/2`).
        monkeypatch.delenv(EXEMPLAR_SEED_KNOB, raising=False)
        requests = {unit.submission_id: worker.assemble(unit) for unit in units}

        # The >=3-run floor, at the protocol's own constant: the dispatch loop runs
        # exactly `MVVP_REPLICATION_RUNS` times, so the case measures the floor the
        # protocol actually declares, not a hardcoded three.
        assert runs_required >= 3, (
            f"the protocol floor read {runs_required}; the case measures at least "
            "three runs per the plan row, and a floor below three would be a "
            "replication nobody declared"
        )
        bands = {}
        for submission_id in SUBMISSIONS:
            bands[submission_id] = tuple(
                worker.dispatch(requests[submission_id], live_ref).band
                for _ in range(runs_required)
            )

        unanimous = sum(1 for band_runs in bands.values() if len(set(band_runs)) == 1)
        rate = unanimous / STATED_N

        # The backend's declaration, consumed as the API declares it — statically
        # (`CT-PROV-04`), no network call. A claim is carried beside the measured
        # rate, never computed from it.
        capabilities = live_provider.capabilities(live_ref)
        backend_claim = capabilities.deterministic_at_temperature_zero
        assert isinstance(backend_claim, bool), (
            f"capabilities() declared {backend_claim!r}; the backend's "
            "deterministic_at_temperature_zero declaration is a bool, and "
            "run_mvvp refuses anything else as a programming error"
        )

        # --- the protocol reports both claims on one row (FR-STATS-16) ---------
        report = run_mvvp(
            assignment_type=ASSIGNMENT_TYPE,
            configuration={
                "panel_member": (judge_id,),
                "model_build": judge_id,
                "quantization": quantization,
                "prompt_template_version": JUDGE_PROMPT_TEMPLATE_V,
            },
            measured_self_agreement={judge_id: rate},
            backend_claims_deterministic_at_temperature_zero=backend_claim,
        )

        step3 = report.steps[3].outcome[judge_id]
        assert step3.measured is True, (
            "the protocol reported step 3 as not-measured for a judge the run "
            "measured — the measured channel is the declaration, and a channel "
            "the caller declared must never arrive as the not-measured value "
            "(FR-STATS-16)"
        )
        assert step3.self_agreement == rate, (
            f"step 3 reported self_agreement={step3.self_agreement!r} where the "
            f"run measured {rate!r} — the per-judge self-agreement is reported "
            "verbatim, never clamped, floored or pushed toward the backend's "
            "declaration (FR-STATS-16, TC-JUDGE-C17 limb 3)"
        )
        assert step3.reason == "", (
            f"step 3's measured row carried reason {step3.reason!r}; a measured "
            "outcome reports the figure, and a not-measured reason on a measured "
            "row is the shape of a swap-in, not a report"
        )
        assert step3.runs_required == runs_required, (
            f"step 3 declared runs_required={step3.runs_required} where the "
            f"protocol floor the run measured is {runs_required} — the "
            "replication's stated n is the row's own figure (FR-STATS-16)"
        )
        assert step3.backend_claim_source == "declared_by_caller", (
            f"step 3 tagged the claim {step3.backend_claim_source!r}; the "
            "declaration arrived through the caller's channel, and the row must "
            "say where the claim came from — the two claims are different claims "
            "(FR-STATS-16)"
        )
        assert (
            step3.backend_claims_deterministic_at_temperature_zero == backend_claim
        ), (
            f"step 3 carried the declaration as "
            f"{step3.backend_claims_deterministic_at_temperature_zero!r} where the "
            f"backend declared {backend_claim!r} — the claim is carried verbatim, "
            "never recomputed or merged into the measured rate (CT-PROV-04)"
        )
        assert report.judges_in_scope == (judge_id,), (
            f"the report scoped {report.judges_in_scope!r}; the measured judge is "
            "the one the run dispatched against, and the panel names it"
        )
        assert report.measured_configuration == {
            "panel_member": (judge_id,),
            "model_build": judge_id,
            "quantization": quantization,
            "prompt_template_version": JUDGE_PROMPT_TEMPLATE_V,
        }, (
            f"the configuration echo was {report.measured_configuration!r}; a "
            "consumer must be able to verify which judge, build, quantization and "
            "prompt the three runs ran under — 'the same judge and backend' is "
            "the row's own clause (FR-STATS-16, FR-STATS-19)"
        )
    finally:
        store.close()