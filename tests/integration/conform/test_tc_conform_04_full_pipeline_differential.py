"""`TC-CONFORM-04`, the behavioural half — the differential, live, with no stubs anywhere.

Case: test plan §5.18, `FR-CONFORM-04`, R28. Oracle: **differential across backends**.

    | TC-CONFORM-04 | Integration, live / 4 | The identical fixture set through the **full**
    | pipeline on two backends | No stubs anywhere, including ingestion — asserted by confirming
    | the fixture provider is not bound and that the real transcription stage ran. Per-criterion
    | score distributions, chance-corrected agreement with the fixture labels, confidence and
    | escalation rate, evidence-integrity failure rate and self-agreement over repeated runs are
    | all compared |

**Landed at #134** (unmarked there): `ConformanceSuite.run` drives the full pipeline per
backend and carries the divergence machinery the differential reads (`DivergenceReport`, the
per-backend figures). Marked `live` as well because the stub this case exists to forbid is
the model boundary itself: on the recorded transport the same assertions are `TC-CONFORM-C08`'s
fast-tier half, and they pass there by design.

**Env-gated, not skipped silently.** Rung 4 needs real backends, and this box may not have them.
`HARNESS_CONFORM_LIVE_BACKENDS` (seam 3) declares which profiles are provisioned; the case skips
naming that prerequisite when it is unset — the same arrangement gap `TC-PROV-19`'s E3 and
`TC-CONFORM-03`'s F-HAND sit behind — and runs **exactly** the declared profiles, so the knob
chooses the transport rather than decorating a fixed pair.

**How this differs from TS-75's `CT-CONFORM-03`/`-04`.** Those assert the report's *shape* at the
contract rung: the stage sweep, the five-dimension set equality, the no-headline prohibition.
This file drives the same report at rung 4 and asserts what the contract cases cannot: that the
stages really ran (the dispatch is the backend's own transcriber, not the recorded double), and
that each dimension's divergence has **operands** — a divergence value with no per-backend figure
behind it is a differential with the measurements missing. The overlap is reported on the PR.
"""

from __future__ import annotations

import pytest

from tests.support.conform_vocabulary import (
    DIVERGENCE_DIMENSIONS,
    OBSERVABILITY_FIELDS,
    PER_BACKEND_FIGURES_FIELD,
    PIPELINE_STAGES,
    RECORDED_FIXTURE_DISPATCH,
    SCORE_DISTRIBUTION_DIMENSION,
    TRANSCRIPTION_DISPATCH_FIELD,
    UNSTUBBABLE_STAGE,
    live_conformance_backends,
)
from tests.support.impl import CONFORM_MODULE, require

pytestmark = [pytest.mark.integration, pytest.mark.live]

ISSUE = "#134"
CASE = "TC-CONFORM-04"


def _synthetic_cohort():
    from aeh.conf import CohortRef

    return CohortRef(cohort_id="c-conform-fixtures", consent_class="synthetic")


def test_tc_conform_04_no_stub_runs_the_full_pipeline_through_the_real_transcriber():
    """*"No stubs anywhere, including ingestion"* — asserted the way the case says to assert it.

    Two observations carry it, and the case names both because either alone is defeat-able:

    **The fixture provider is not bound.** Asserted through the per-backend result's
    transcription dispatch: a run that dispatched through the recorded fixture double would
    compare the two backends on a transcript neither of them produced. The negative half alone
    (`!= recorded_fixture`) would admit any other stand-in, so the positive half pins the
    dispatch to the config's own transcriber — the resolved value, which is also what makes
    the two backends' dispatches **different**.

    **The real transcription stage ran.** The per-fixture, per-stage sweep, with ingestion
    asserted separately so a failure says *ingestion was stubbed* rather than *some stage was
    missing somewhere* — the same split `CT-CONFORM-03` makes, repeated at the rung where the
    stub would actually hide.
    """
    # #134 first, deliberately: `require()` reports whichever blocker it reaches first, and this
    # test is registered against #134 — a failure naming the wrong issue is how a gate stops
    # being believed.
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue=ISSUE)
    load_fixture_set = require(CONFORM_MODULE, "load_fixture_set", issue="#133")

    fixtures = load_fixture_set("v1")
    backends = live_conformance_backends()
    report = build_suite().run("v1", backends, cohort=_synthetic_cohort())

    assert len(report.per_backend) == len(backends), (
        f"the run measured {len(report.per_backend)} backend(s) against {len(backends)} "
        f"declared; a differential compares the declared backends"
    )

    hashes = {profile: r.input_set_hash for profile, r in report.per_backend.items()}
    assert len(set(hashes.values())) == 1, (
        f"the two backends consumed different input sets: {hashes}. The differential would then "
        f"be a statement about two different corpora."
    )
    assert set(hashes.values()) == {fixtures.content_hash}, (
        f"both backends agree with each other but not with the frozen set ({fixtures.content_hash}"
        f"): they consumed the same subset, which agrees on every dimension by construction."
    )

    for cfg in backends:
        profile = cfg["HARNESS_PROFILE"]
        result = report.per_backend[profile]
        dispatch = getattr(result, TRANSCRIPTION_DISPATCH_FIELD, None)
        assert dispatch is not None, (
            f"{profile}'s result does not say what its transcription stage dispatched through, "
            f"so 'the fixture provider is not bound' is unassertable (FR-CONFORM-04)"
        )
        assert dispatch != RECORDED_FIXTURE_DISPATCH, (
            f"{profile}'s transcription stage dispatched through the recorded fixture double. "
            f"The case compares the backends' own transcription, not a replay neither of them "
            f"produced."
        )
        assert dispatch == cfg["transcriber"].build_id, (
            f"{profile}'s transcription stage dispatched through {dispatch!r} but its config "
            f"declares {cfg['transcriber'].build_id!r}. A run measuring backend {profile} must "
            f"transcribe with that backend's own transcriber."
        )

        for submission_id, stages in result.stages_executed.items():
            missing = set(PIPELINE_STAGES) - set(stages)
            assert not missing, (
                f"{profile}/{submission_id} skipped {sorted(missing)}. FR-CONFORM-04 requires "
                f"the full pipeline, with no stubs anywhere."
            )
            assert UNSTUBBABLE_STAGE in stages, (
                f"{profile}/{submission_id} did not run {UNSTUBBABLE_STAGE!r}. A conformance run "
                f"that stubs ingestion compares the two backends on the one stage where they "
                f"differ most."
            )


def test_tc_conform_04_all_five_dimensions_are_compared_with_both_operands_present():
    """The five dimensions are compared, and each comparison has its two measurements behind it.

    *"Per-criterion score distributions, chance-corrected agreement with the fixture labels,
    confidence and escalation rate, evidence-integrity failure rate and self-agreement over
    repeated runs are all compared."* A divergence value with no per-backend figure behind it is
    the differential with the operands missing — the shape that passes a shape check on a report
    that measured nothing (`CLAUDE.md`'s first silent-failure trap). So the operands are asserted
    present per backend, per dimension, before the divergence values are asserted at all.

    **Per-criterion, not pooled.** The score-distribution figure is a mapping keyed by criterion:
    one aggregate distribution would let a divergence on one criterion hide inside averages over
    the rest, which is exactly what "per-criterion" exists to prevent.

    **Anchored to the fixture labels.** The agreement dimension is chance-corrected agreement
    *with the fixture labels* — computed against the frozen set's reference scores, not between
    the two backends. The labels' provenance is the fixture set version the report emits; a run
    whose agreement figure names no fixture set has computed agreement with something, and the
    reader cannot tell what.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue=ISSUE)
    load_fixture_set = require(CONFORM_MODULE, "load_fixture_set", issue="#133")

    fixtures = load_fixture_set("v1")
    report = build_suite().run("v1", live_conformance_backends(), cohort=_synthetic_cohort())

    divergence = report.divergence
    assert set(divergence.dimensions) == DIVERGENCE_DIMENSIONS, (
        f"the divergence report covers {sorted(divergence.dimensions)}; FR-CONFORM-04 declares "
        f"{sorted(DIVERGENCE_DIMENSIONS)}"
    )
    unmeasured = [d for d in DIVERGENCE_DIMENSIONS if divergence.dimensions[d] is None]
    assert not unmeasured, (
        f"these dimensions are declared and unmeasured: {unmeasured}. The right shape with no "
        f"values is the failure that looks like success."
    )

    for profile, result in report.per_backend.items():
        figures = getattr(result, PER_BACKEND_FIGURES_FIELD, None)
        assert figures is not None, (
            f"{profile}'s result carries no {PER_BACKEND_FIGURES_FIELD!r} mapping, so the "
            f"divergence values have no per-backend measurements behind them — a differential "
            f"with the operands missing"
        )
        missing = set(DIVERGENCE_DIMENSIONS) - set(figures)
        assert not missing, (
            f"{profile} measured {sorted(set(figures))}; the differential needs its own figure "
            f"for every dimension, including {sorted(set(DIVERGENCE_DIMENSIONS) - set(figures))}"
        )
        blank = [d for d, value in figures.items() if value is None]
        assert not blank, (
            f"{profile}'s figures for {blank} are present and empty — the measurement that "
            f"looks recorded and is not"
        )

        distribution = figures[SCORE_DISTRIBUTION_DIMENSION]
        assert isinstance(distribution, dict) and distribution, (
            f"{profile}'s score distribution is {type(distribution).__name__}, not a per-criterion "
            f"mapping. One pooled distribution is exactly the aggregate 'per-criterion' forbids."
        )

    # The labels the agreement was computed against are the frozen set's — the report names the
    # fixture set it ran, so the agreement figure's anchor is checkable against the set itself.
    assert OBSERVABILITY_FIELDS <= set(report.observability), (
        f"the report emits {sorted(report.observability)}; the run's provenance (§3.18's "
        f"observability line) is what anchors the agreement figures to a named fixture set"
    )
    assert report.observability["fixture_set_version"] == fixtures.version, (
        f"the run reports fixture set {report.observability['fixture_set_version']!r}; the frozen "
        f"set it was given is {fixtures.version!r}. Agreement 'with the fixture labels' is "
        f"agreement with whatever set this names."
    )


#: The profiles whose arm is the OpenRouter arm (FR-CONF-29 resolves `jev` by default on both).
_OPENROUTER_PROFILES = frozenset({"cloud-hosted", "dev-ci"})


@pytest.mark.writtenahead
def test_tc_conform_04_openrouter_arm_runs_the_default_engine_and_reports_per_leg_live_keys():
    """`TC-CONFORM-04`, re-specified by the operator-requirements plan (§5.0; TS-142, #617).

    *"The OpenRouter arm runs with the resolved default engine (`jev` on that profile), so the
    differential includes the decision leg; the report carries the CT-CONFORM-17 per-leg keys
    alongside the existing figures."*

    **The resolved default, not a pinned value.** `conf_builders.hosted_cfg` pins
    `HARNESS_DECISION_ENGINE="off"` so every older case stays engine-off; this arm deletes the
    key so the profile's default decides. The decision leg's `live_calls > 0` is then the proof
    that the default resolved to an engine that actually ran.

    Written ahead of #618 (keyed on `aeh.conform:run_live_acceptance`, the story's entry point,
    since #618 lands this arm's per-leg figures with it). The key is checked first so a box
    without one skips before anything is resolved or dispatched.
    """
    from tests.support.conform_vocabulary import (
        BACKEND_LIVE_LEGS_FIELD,
        CT_CONFORM_17_KEYS,
        LEG_DECISION,
        LIVE_ACCEPTANCE_ENTRY,
        LIVE_CALLS,
        LIVE_LEG_KEYS,
        LIVE_LEGS,
        require_openrouter_key,
    )

    require_openrouter_key()
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue=ISSUE)
    require(CONFORM_MODULE, LIVE_ACCEPTANCE_ENTRY, issue="#618")

    backends = live_conformance_backends()
    openrouter = [cfg for cfg in backends if cfg["HARNESS_PROFILE"] in _OPENROUTER_PROFILES]
    if not openrouter:
        pytest.skip(
            "HARNESS_CONFORM_LIVE_BACKENDS declares no OpenRouter profile (cloud-hosted or "
            "dev-ci); the re-specified arm has nothing to run against."
        )
    for cfg in openrouter:
        cfg.pop("HARNESS_DECISION_ENGINE", None)

    report = build_suite().run("v1", backends, cohort=_synthetic_cohort())

    for cfg in openrouter:
        profile = cfg["HARNESS_PROFILE"]
        result = report.per_backend[profile]
        figures = getattr(result, PER_BACKEND_FIGURES_FIELD, None)
        assert figures and set(DIVERGENCE_DIMENSIONS) <= set(figures), (
            f"{profile}: the existing per-backend figures must stay alongside the new keys"
        )
        legs = getattr(result, BACKEND_LIVE_LEGS_FIELD, None)
        assert legs is not None, (
            f"{profile}'s result carries no {BACKEND_LIVE_LEGS_FIELD!r}; the re-specified arm "
            f"reports the CT-CONFORM-17 per-leg keys beside the existing figures."
        )
        assert set(legs) == set(LIVE_LEGS), (
            f"{profile} reports legs {sorted(legs)}; the full-pipeline arm has {sorted(LIVE_LEGS)}"
        )
        for leg in LIVE_LEGS:
            missing = set(LIVE_LEG_KEYS) - set(legs[leg])
            assert not missing, f"{profile} leg {leg!r} lacks {sorted(missing)}"
            assert float(legs[leg][LIVE_CALLS]) > 0, (
                f"{profile} leg {leg!r} made no live calls; a zero-call leg fails the report "
                f"(CT-CONFORM-17)."
            )
        missing = CT_CONFORM_17_KEYS - set(legs[LEG_DECISION])
        assert not missing, (
            f"{profile}'s decision leg lacks {sorted(missing)}. With the engine resolved by "
            f"default the differential includes the decision leg (FR-CONFORM-17)."
        )