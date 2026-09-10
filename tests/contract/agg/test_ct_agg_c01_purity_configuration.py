"""`TC-AGG-C01` — the policy reads no configuration beyond the values passed in (§6.11.12).

`CT-AGG-01`'s fourth prohibition — the one the case table says *erodes*: "no store access,
no model call, no clock, **and no configuration read beyond the values passed in** —
reading a threshold from the environment inside the function would make the policy
untestable as a value." Run first, as the case demands: every case below depends on the
policy being evaluable as a value.

Relationship to the shipped sibling, disclosed: `tests/unit/agg/test_policy_purity.py`
(`TC-AGG-18`) is the poison-guard half — store spy, socket guard, clock/entropy/`os.getenv`
poisoned — and it documents the ONE surface it deliberately cannot poison: `os.environ`
itself, which the harness process reads mid-run. That blind spot is exactly this case's
ground. A module can read a threshold through `os.environ[...]` or `os.environ.get`
while every `os.getenv` poison stays silent. So the assertion here is a **differential**,
the behavioural closure the poison cannot be: the same call evaluated with the
environment holding adversarial configuration-shaped values and with them cleared must
return the *same* result — both on the production defaults (`config=None`, the reading an
environment look-over would subvert) and on an explicitly injected config (the
environment must not override the caller's values either).

The names set below are the plausible spellings a regression would reach for — the
module's own constants' names under the harness's `HARNESS_` knob convention, plus a
generic `AGG_*` spelling. The salt is what makes this an oracle rather than a name
list: each value is chosen to MOVE a figure on one of the cells below, the moved
figure is recorded at each entry, and the calibration is empirical — patching the
constant a name shadows to the salted value must move the compared tuple. The
atomic-threshold entries record why the calibration matters: a salt in the dead zone
(0.40, 0.80] — where every atomic cell's routing is the same at both readings — lets
a read through silently, which is exactly the failure a figure list without figures
would ship.

Isolation: rung 0 — pure functions and doubles; the socket guard is autouse, so a
model call fails mid-connect; the store-shaped parameter space is asserted empty at
the signature level (the sibling's refusing spy, made structural).
"""

from __future__ import annotations

import inspect
import os

import pytest

from tests.support.agg_vocabulary import (
    band,
    criterion,
    panel,
    signals,
    verdict,
    agg_config,
    escalation_score,
    criterion_history,
    expected_distribution,
)
from tests.support.impl import AGG_MODULE, require

pytestmark = [pytest.mark.contract]

_FOUR_BAND = criterion([band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0),
                        band("B3", 3, 6.0)])
_UNANIMOUS_TOP = panel(("B3", 3), ("B3", 3), ("B3", 3))
_SPLIT = panel(("B0", 0), ("B1", 1), ("B1", 1), ("B1", 1), ("B2", 2))  # α = 0.52

#: Configuration-shaped environment, every value chosen to MOVE a figure on one of the
#: cells the differential evaluates — the moved figure is recorded at each entry,
#: against the shipped readings (shipped: thresholds 0.80/0.90, multipliers 0.80/0.85,
#: caps 0.25, escalation threshold 1.0, weights 1.0/0.5/0.25, sigma 2.0, override 0.5).
_ADVERSARIAL_ENV = {
    # The split panel's confidence (0.40) clears this but not the shipped 0.80 —
    # its routing flips queued → auto. (A salt in (0.40, 0.80] — 0.50, 0.45 — moves
    # nothing: every atomic cell reads the same at both thresholds.)
    "HARNESS_AGG_AUTO_THRESHOLD_ATOMIC": "0.35",
    # The uncited panel's confidence (0.80) meets the shipped threshold exactly
    # (auto) and misses this one — its routing flips auto → queued.
    "AGG_AUTO_THRESHOLD_ATOMIC": "0.85",
    # The holistic ceiling's unanimous figure (0.85) clears this, not the shipped 0.90.
    "HARNESS_AGG_AUTO_THRESHOLD_HOLISTIC": "0.70",
    # The uncited unanimous panel's shipped 0.80 confidence becomes 0.60 (and queues).
    "HARNESS_AGG_UNCITED_MULTIPLIER": "0.60",
    # The holistic panel's shipped 0.85 confidence becomes 0.60.
    "HARNESS_AGG_HOLISTIC_MULTIPLIER": "0.60",
    # The spans-capped unanimous panel's shipped 0.25 becomes 0.99 — routing flips.
    "HARNESS_AGG_CAP_SPANS_VERIFIED": "0.99",
    # The evidence-capped panel's shipped 0.25 becomes 0.99 — routing flips.
    "HARNESS_AGG_CAP_EVIDENCE_PRESENT": "0.99",
    # The mild cell's only concern is the self-confidence input (0.25 × 0.5 = 0.125,
    # under the shipped 1.0); at this threshold it escalates.
    "AGG_ESCALATION_THRESHOLD": "0.10",
    # The same mild cell's concern becomes 2.5 under this weight — it escalates.
    "AGG_ESCALATION_SELF_CONFIDENCE_WEIGHT": "5.0",
    # The interior cell's two fired limbs (shipped concern 2.0) fall under the
    # threshold — its decision flips escalate → hold.
    "AGG_ESCALATION_SIGNAL_WEIGHT": "0.25",
    # The no-data history cell's shipped concern (the 0.5 weight alone) crosses the
    # threshold — its decision flips hold → escalate.
    "AGG_ESCALATION_NO_DATA_WEIGHT": "2.0",
    # The calm cell's anomaly (z = 2.0, exactly the shipped sigma) stops counting —
    # its decision flips escalate → hold.
    "AGG_ESCALATION_ANOMALY_SIGMA": "3.0",
    # The override-history cell's rate (0.40) clears this, not the shipped 0.50 —
    # its decision flips hold → escalate.
    "AGG_ESCALATION_OVERRIDE_RATE": "0.30",
}

_SCORE_FIELDS = ("confidence", "routing", "state")


class _RefusingStoreSpy:
    """A store spy that fails on any access — the sibling TC-AGG-18's oracle."""

    def __getattr__(self, name: str):
        raise AssertionError(
            f"the policy function touched the store during evaluation ({name!r}) — "
            "CT-AGG-01: no store access"
        )


def _spy_kwargs(function) -> dict:
    """A refusing spy for every store-shaped parameter the signature declares."""
    spy_names = {"store", "store_handle", "session", "conn", "connection"}
    return {
        name: _RefusingStoreSpy()
        for name in inspect.signature(function).parameters
        if name.lower() in spy_names
    }


def _decide(aggregate, should_escalate, ordinal_alpha, config):
    """One evaluation of the whole policy surface the case sweeps — the values the
    differential compares. Every cell is one a salted environment read would move
    (the moved figure recorded on the salt above): the spans-capped and
    evidence-capped unanimous panels (0.25 shipped against the salted 0.99 caps),
    the uncited unanimous panel (0.80 shipped vs the salted 0.60 multiplier), the
    holistic panel (0.85, between the salted and shipped holistic threshold and
    multiplier), the split panel (confidence 0.40, between the salted and shipped
    atomic thresholds), and four escalation cells — the calm anomaly cell (z = 2.0,
    exactly the shipped sigma), the interior cell (two fired limbs, concern 2.0),
    a mild self-doubting cell (concern 0.125, under the threshold), a no-data
    history cell (the 0.5 weight alone), and a contested-history cell under the
    shipped override-rate threshold — so each escalation knob's read flips its own
    cell's decision. `config` rides through so both the production-default reading
    (None) and the caller-specified reading are covered."""
    spy = _spy_kwargs(aggregate)

    capped = aggregate(_UNANIMOUS_TOP, _FOUR_BAND, signals(spans_verified=False),
                       config=config, **spy)
    uncited = aggregate(
        [verdict("B3", 3), verdict("B3", 3), verdict("B3", 3, cited=False)],
        _FOUR_BAND, signals(), config=config, **spy,
    )
    holistic = criterion(_FOUR_BAND.bands, scoring_model="holistic")
    holistic_score = aggregate(_UNANIMOUS_TOP, holistic, signals(), config=config, **spy)
    split = aggregate(_SPLIT, _FOUR_BAND, signals(), config=config, **spy)
    evidence_capped = aggregate(_UNANIMOUS_TOP, _FOUR_BAND,
                                signals(evidence_present=False), config=config, **spy)

    def _escalation(score, history, baseline):
        return should_escalate(
            score=score, criterion=_FOUR_BAND, history=history, baseline=baseline,
            config=config, **_spy_kwargs(should_escalate),
        )

    calm = _escalation(
        escalation_score(ordinal=3, band_count=4, self_confidence=1.0),
        criterion_history(), expected_distribution(),
    )
    interior = _escalation(
        escalation_score(ordinal=2, band_count=4, spans_verified=None),
        criterion_history(), expected_distribution(),
    )
    mild = _escalation(
        escalation_score(ordinal=3, band_count=4, self_confidence=0.5),
        criterion_history(), expected_distribution(mean=3.0),
    )
    nodata = _escalation(
        escalation_score(ordinal=3, band_count=4, self_confidence=1.0),
        criterion_history(override_rate=None), expected_distribution(mean=3.0),
    )
    override = _escalation(
        escalation_score(ordinal=3, band_count=4, self_confidence=1.0),
        criterion_history(override_rate=0.4), expected_distribution(mean=3.0),
    )
    return (
        capped.confidence, capped.routing,
        uncited.confidence, uncited.routing,
        holistic_score.confidence, holistic_score.routing,
        split.confidence, split.routing,
        evidence_capped.confidence, evidence_capped.routing,
        calm.escalate, calm.target_judge_count,
        interior.escalate, interior.target_judge_count,
        mild.escalate, mild.target_judge_count,
        nodata.escalate, nodata.target_judge_count,
        override.escalate, override.target_judge_count,
        ordinal_alpha(_SPLIT),
        ordinal_alpha([]),
    )


@pytest.mark.parametrize("with_config", [False, True], ids=["defaults", "explicit_config"])
def test_tc_agg_c01_the_policy_reads_no_configuration_beyond_the_values_passed_in(
    monkeypatch, with_config
):
    """`TC-AGG-C01` (`CT-AGG-01`, `NFR-AGG-01`, unit / rung 0, environment
    differential, P0) — the whole policy surface evaluated with the environment
    holding adversarial configuration-shaped values and with them cleared returns
    the SAME result, on the production defaults and on a caller-specified config
    alike. An environment read inside the call would move at least one figure —
    the erosion this case exists to catch."""
    aggregate, should_escalate, ordinal_alpha = require(
        AGG_MODULE, "aggregate", "should_escalate", "ordinal_alpha", issue="#91"
    )
    config = agg_config() if with_config else None

    for name, value in _ADVERSARIAL_ENV.items():
        monkeypatch.setenv(name, value)
    with_env = _decide(aggregate, should_escalate, ordinal_alpha, config)

    for name in _ADVERSARIAL_ENV:
        monkeypatch.delenv(name, raising=False)
    # The rest of the harness environment stays as it is — the differential is over
    # the configuration-shaped names above, not a wholesale wipe (the sibling's
    # recorded reason: pytest itself reads the environment mid-run).
    without_env = _decide(aggregate, should_escalate, ordinal_alpha, config)
    assert os.environ.get("AGG_AUTO_THRESHOLD_ATOMIC") is None, (
        "fixture bug: the cleared-environment run did not actually clear the salted "
        "names, so the differential compared the environment against itself"
    )

    assert with_env == without_env, (
        f"the policy moved when the environment changed: with env {with_env} vs "
        f"without {without_env} — a configuration read beyond the values passed in "
        "makes the policy untestable as a value (CT-AGG-01's fourth prohibition; "
        "the differential closes the os.environ blind spot TC-AGG-18 documents)"
    )


def test_tc_agg_c01_the_policy_surface_declares_no_store_or_session_parameter():
    """`TC-AGG-C01` (`CT-AGG-01`, surface assertion, P0) — none of the three
    policy members declares a store-shaped parameter at all: the purity is in the
    signature, not only in the behaviour, so a future parameter cannot arrive
    without this case naming it."""
    aggregate, should_escalate, ordinal_alpha = require(
        AGG_MODULE, "aggregate", "should_escalate", "ordinal_alpha", issue="#91"
    )
    spy_names = {"store", "store_handle", "session", "conn", "connection"}
    for function in (aggregate, should_escalate, ordinal_alpha):
        offenders = [
            name for name in inspect.signature(function).parameters
            if name.lower() in spy_names
        ]
        assert offenders == [], (
            f"{function.__name__} declares store-shaped parameter(s) {offenders} — "
            "CT-AGG-01: no store access; the policy is a pure function of its values"
        )
