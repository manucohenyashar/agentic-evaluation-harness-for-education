"""`TS-100` (issue #394) — `TC-STATS-28`, the MVVP measurement drivers.

Gap-fix test plan §5 (`TC-STATS-28`, `FR-STATS-21`, Phase 2, P2), rung 3 with recorded fixtures:

    6 fixture judgments; recorded responses for the original order and 2 permutations
    (seeds 1, 2), where judge J2 changes band on 2 of 6 under permutation;
    `measure_self_agreement(runs=3)` with J1 identical all 3 times; `runs=2`.
    Expected: `position_bias[J2] = 2/6`, `[J1] = 0`; self-agreement J1 = 1.0;
    `run_mvvp(measured_position_bias=…)` accepts the output unchanged; `runs=2` raises (Q-17).
    Oracle: hand-computed.

**The world** is TS-31's judged run (`tests/support/judge_run.py`) through the real boundary: a
real store, a banded package with four `C1` exemplars (the permutation needs ≥ 2 to engage), the
real extraction leg, and a three-judge panel (`edge_panel(3)`; panels are odd, `CT-CONF-02`)
whose score units are assembled, dispatched and persisted against `RecordedFixtureProvider` —
the six fixture judgments per judge. The plan's J1/J2 are the panel's first two; J3 behaves as J1.

**The controlled condition** is the recordings. Every unit's request is assembled under the
shipped default exemplar order and under `HARNESS_JUDGE_EXEMPLAR_SEED` = `"1"` and `"2"` (the
plan's two permutations), and a reply is recorded under each exact request key:

* J1 and J3 answer the control band under every order — order-insensitive, rate 0;
* J2 answers the control band under the default order, and the other declared band under both
  permutations for exactly two of the six submissions — rate 2/6.

A precondition refuses to measure until each salt is proven to have moved the order (same
exemplar set, different sequence), since a salt that coincided with the default would make J2's
"changed" recordings unreachable and the rate vacuous.

**Written ahead of implementation: it was** — keyed on `aeh.stats:measure_position_bias`
(#374). #374 landed both drivers, so the `writtenahead` markers and the
`WRITTEN_AHEAD_BLOCKERS` entry are gone and these two cases run in the gate.

**Interface assumed** (design delta §3.9, FR-STATS-21), stated so #374 reconciles it
deliberately — and #374 implemented it unchanged, signature for signature, so the table below
is now the shipped interface rather than an assumption about it:

| Name | Assumption |
|---|---|
| `measure_position_bias(store, provider, panel, fixture_submissions, *, seed)` | `panel` is the judges' `ModelRef`s, `fixture_submissions` the submission ids; `seed` selects one permutation and is the exemplar salt's value (`seed=1` → salt `"1"`). Each seed is measured in its own call, and both must report J2 = 2/6, which holds under either reading of how the seed engages because J2 moves on the same two submissions under both |
| return | `Mapping[judge build_id, rate]`, each rate a float `run_mvvp` accepts verbatim (`PositionBiasRate`) |
| `measure_self_agreement(store, provider, panel, fixture_submissions, *, runs=3)` | same leading arguments; every judgment dispatched through `provider` ≥ `runs` times (witnessed by a counting wrapper); `runs < 3` raises (Q-17 leaves the type open, so none is asserted) |
| `fixture_submissions` | bare submission ids: the driver must rebuild each unit exactly as the lease resolved it, or the recorded-request lookup misses — a missing-recording refusal here means that, not a wrong rate |

**Known blind spot, deliberate.** J2 moves on the same two submissions under both salts, so a driver
that ignores `seed` still reports 2/6; the plan's row fixes no seed-specific behaviour, and this
keeps the case green under either reading of how `seed` engages. A driver that never permutes is
still caught — the default order answers the control band, so J2 would read 0.
"""

from __future__ import annotations

import pytest

from tests.support.conf_builders import edge_panel
from tests.support.extract_vocabulary import verdict_completion
from tests.support.impl import STATS_MODULE, require
from collections import Counter

from tests.support.judge_run import (
    _CountingProvider,
    CONTROL_BAND,
    CONTROL_CONFIDENCE,
    DECLARED_NAMES,
    judge_world,
    warm_judged_modules,
)
from tests.support.judge_vocabulary import EXEMPLAR_SEED_KNOB

pytestmark = pytest.mark.integration

ISSUE = "#374"

EXEMPLARS = (("C1", "secure"), ("C1", "emerging"), ("C1", "secure"), ("C1", "emerging"))
SUBMISSIONS = ("s-28a", "s-28b", "s-28c", "s-28d", "s-28e", "s-28f")
#: The two submissions J2 moves band on under permutation — the hand-computed 2/6.
J2_MOVES_ON = ("s-28b", "s-28e")
SEEDS = (1, 2)
OTHER_BAND = next(name for name in DECLARED_NAMES if name != CONTROL_BAND)

ASSIGNMENT_TYPE = "extended_response"


def _reply(band, spans, build_id):
    return verdict_completion(band, CONTROL_CONFIDENCE, build_id=build_id, cited_spans=spans)


def _order(request):
    return tuple(view.exemplar_id for view in request.criterion.exemplars)


def _record_world(tmp_data_dir, make_fixture_provider, monkeypatch):
    """Build the judged world and record every reply the drivers can ask for."""
    from aeh.store import open_store

    warm = warm_judged_modules()
    ScoringWorker, JudgePromptFields = warm["judge"], warm["judge_prompt_fields"]
    from tests.support.extract_vocabulary import sampling_params

    monkeypatch.delenv(EXEMPLAR_SEED_KNOB, raising=False)
    store = open_store(tmp_data_dir)
    provider = make_fixture_provider()
    panel = edge_panel(3)
    j1, j2, j3 = (ref.build_id for ref in panel)
    world = judge_world(
        store,
        provider,
        submissions=SUBMISSIONS,
        panel=3,
        exemplars=EXEMPLARS,
        reply_for=lambda submission, judge: _reply(
            CONTROL_BAND, None, "judge-build-ts100"
        ),
    )
    assert not world["failures"], f"precondition: the base judgments failed {world['failures']}"
    assert len(world["results"]) == len(SUBMISSIONS) * 3, (
        "precondition: six fixture judgments per judge"
    )

    refs = {ref.build_id: ref for ref in panel}
    for seed in SEEDS:
        monkeypatch.setenv(EXEMPLAR_SEED_KNOB, str(seed))
        for (submission, judge), unit in world["score_units"].items():
            ref = refs[judge]
            permuted = ScoringWorker(store, provider, ref).assemble(unit)
            base = world["requests"][(submission, judge)]
            assert sorted(_order(permuted)) == sorted(_order(base)) and len(_order(base)) == 4, (
                f"precondition: seed {seed} changed the exemplar SET for {submission}"
            )
            assert _order(permuted) != _order(base), (
                f"precondition: seed {seed} left the exemplar order of {submission} unmoved — "
                f"J2's permuted recordings would be unreachable and the rate vacuous"
            )
            band = OTHER_BAND if judge == j2 and submission in J2_MOVES_ON else CONTROL_BAND
            provider.record(
                JudgePromptFields(permuted), ref, sampling_params(),
                _reply(band, None, "judge-build-ts100"),
            )
    monkeypatch.delenv(EXEMPLAR_SEED_KNOB, raising=False)
    return store, provider, panel, j1, j2, j3


def test_tc_stats_28_position_bias_is_the_per_judge_band_change_rate(
    tmp_data_dir, make_fixture_provider, monkeypatch
):
    """`TC-STATS-28` — J2 moves band on 2 of 6 under each permutation, J1 on none: the rates are
    exactly 2/6 and 0, and `run_mvvp` reports them verbatim."""
    store, provider, panel, j1, j2, j3 = _record_world(
        tmp_data_dir, make_fixture_provider, monkeypatch
    )
    try:
        measure_position_bias, run_mvvp = require(
            STATS_MODULE, "measure_position_bias", "run_mvvp", issue=ISSUE
        )
        for seed in SEEDS:
            rates = measure_position_bias(store, provider, panel, SUBMISSIONS, seed=seed)
            assert set(rates) == {j1, j2, j3}, f"seed {seed}: rates for {sorted(rates)}"
            assert rates[j2] == 2 / 6, (
                f"seed {seed}: position_bias[J2]={rates[j2]!r}, hand-computed 2/6"
            )
            assert rates[j1] == 0, f"seed {seed}: position_bias[J1]={rates[j1]!r}, expected 0"
            assert rates[j3] == 0, f"seed {seed}: position_bias[J3]={rates[j3]!r}, expected 0"

            report = run_mvvp(
                assignment_type=ASSIGNMENT_TYPE,
                configuration={"panel_member": (j1, j2, j3)},
                measured_position_bias=rates,
            )
            step2 = report.steps[2].outcome
            for judge in (j1, j2, j3):
                assert step2[judge].measured is True
                assert step2[judge].band_change_rate == rates[judge], (
                    f"run_mvvp did not accept {judge}'s rate unchanged"
                )
    finally:
        store.close()


def test_tc_stats_28_self_agreement_replicates_at_least_three_times(
    tmp_data_dir, make_fixture_provider, monkeypatch
):
    """`TC-STATS-28` — three byte-identical replications of J1 agree every time: self-agreement
    1.0, consumed unchanged by `run_mvvp`; `runs=2` is below the ≥ 3 floor and raises."""
    store, provider, panel, j1, j2, j3 = _record_world(
        tmp_data_dir, make_fixture_provider, monkeypatch
    )
    try:
        measure_self_agreement, run_mvvp = require(
            STATS_MODULE, "measure_self_agreement", "run_mvvp", issue=ISSUE
        )
        # A counting transport, so "replicate each judgment >= 3 times" is witnessed rather
        # than inferred from a 1.0 a driver could return without dispatching anything.
        counting = _CountingProvider(provider)
        agreement = measure_self_agreement(store, counting, panel, SUBMISSIONS, runs=3)
        assert set(agreement) == {j1, j2, j3}, f"self-agreement for {sorted(agreement)}"
        assert agreement[j1] == 1.0, f"self-agreement J1={agreement[j1]!r}, expected 1.0"
        per_judge = Counter(counting.calls)
        for judge in (j1, j2, j3):
            assert per_judge[judge] >= 3 * len(SUBMISSIONS), (
                f"judge {judge} was dispatched {per_judge[judge]} times; six judgments each "
                f"replicated >= 3 times is at least {3 * len(SUBMISSIONS)} (FR-STATS-21)"
            )

        report = run_mvvp(
            assignment_type=ASSIGNMENT_TYPE,
            configuration={"panel_member": (j1, j2, j3)},
            measured_self_agreement=agreement,
        )
        step3 = report.steps[3].outcome
        assert step3[j1].measured is True
        assert step3[j1].self_agreement == agreement[j1]

        with pytest.raises(Exception) as refusal:  # noqa: PT011 — Q-17 leaves the type open
            measure_self_agreement(store, provider, panel, SUBMISSIONS, runs=2)
        assert not isinstance(refusal.value, AssertionError)
    finally:
        store.close()
