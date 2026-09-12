"""`TC-STATS-16` — the order swap on the live tier: a held-out fixture subset
re-scored under a permuted exemplar order, the band-change rate reported, and
the metamorphic relation asserted.

Test plan §5.16 (`TC-STATS-16`), issue #120 (TS-43). Traces to `FR-STATS-15`
(`run_mvvp` step 2). The plan's row: *"A held-out fixture subset re-scored
with exemplar order and reference-material order permuted. The per-judge
band-change rate under permutation is reported. A judge whose band changes
under a pure permutation is the finding."* Metamorphic relation, P0, live.

**The permutation surface is exemplar order, by design.** `FR-JUDGE-16`
settles the clause's "reference-material order" half: a request contains
exactly one criterion, so criterion order is not randomizable within it, and
the design "shall not reintroduce multi-criterion prompts to enable order
randomization" — what remains randomizable is exemplar order (`FR-JUDGE-08`).
The shipped mechanism is the `HARNESS_JUDGE_EXEMPLAR_SEED` salt: the same
rubric, byte-identical material, a different order under a different salt
(`TC-JUDGE-14` pins the order/set/reproducibility properties; the salt pair
here is its verified pairwise-distinct one). The reference-material
presentation order is fixed by the template's field order (`FR-JUDGE-06`/
`FR-JUDGE-07` — the invariant prefix `TC-JUDGE-21` measures), and permuting
*that* would be a template change, not a test input. So the case re-scores
under the shipped permutation exactly as the design defines it, and the
precondition below refuses to measure anything until the permutation is
proven to have engaged.

**The live leg.** The world is the real pipeline minus one boundary: a real
store, a real package version with exemplar blobs, a real extraction leg
(against `RecordedFixtureProvider`, `CT-PROV-10`'s deterministic transport),
real score units leased from the orchestrator — then the judge dispatches go
to the live local server, the one egress point a judgment has. The same
leased units are assembled twice (the salt is read at call time), and each
request is dispatched against the same judge and backend.

**The reporting and the relation.** The measured rate is computed from the
live replies (`changed / n`) and declared through ``measured_position_bias=``;
`run_mvvp` reports it verbatim in step 2 — never clamped, floored or omitted
(`TC-JUDGE-C17` limb 3). The metamorphic relation itself is then asserted: a
pure permutation must not move a band, so `rate == 0.0` — and when that
assertion fails, the report on the lines above already carries the finding,
which is the point of the case. A nondeterministic backend can also move a
band; that is a *different* claim about the same judge, measured separately
by `TC-STATS-17`'s >=3-run self-agreement (`FR-STATS-16`) and reported
beside this one, never merged (`FR-STATS-18`, `TC-STATS-20`).

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

#: Four exemplars for the one criterion — the permutation needs len >= 2 to engage
#: (`_ordered_exemplars` passes shorter lists through untouched, so fewer exemplars
#: would make every arm vacuous). The same shape `TC-JUDGE-14` verified its salts
#: under: one open criterion (`C1`), four seeded exemplar blobs.
EXEMPLARS = (
    ("C1", "secure"),
    ("C1", "emerging"),
    ("C1", "secure"),
    ("C1", "emerging"),
)
SEEDED_IDS = ("ex-00", "ex-01", "ex-02", "ex-03")

#: The held-out fixture subset — the stated n the rate is computed at. One submission
#: per judgment; each is re-scored once per exemplar order.
SUBMISSIONS = ("s-16a", "s-16b", "s-16c", "s-16d")
STATED_N = len(SUBMISSIONS)

#: The permutation salt. Verified empirically under this world's digest key (sha256
#: over `salt|question_id|criterion_id`, base order ex-00..ex-03): the shipped default
#: (`judge-prompt/2`) -> (01,02,03,00), "salt-a" -> (01,03,00,02) — pairwise distinct
#: (`TC-JUDGE-14`'s verified pair). If a template bump ever makes them coincide, the
#: precondition assertion below names it rather than measuring a vacuous rate.
PERMUTATION_SALT = "salt-a"

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
    units = list(world["orchestrator"].lease("w-tcstats-16", STAGE_SCORE, 64))
    assert len(units) == STATED_N, (
        f"precondition: one score unit per submission expected, got {len(units)}"
    )
    return store, units


def _exemplar_views(request):
    """The request's exemplar views as comparable tuples — id, band, and the blob's
    text bytes, so a material drift rides the same comparison as an order move."""
    return tuple(
        (view.exemplar_id, view.band, view.text)
        for view in request.criterion.exemplars
    )


def test_tc_stats_16_the_band_change_rate_under_permutation_is_reported(
    tmp_data_dir, make_fixture_provider, monkeypatch
):
    """TC-STATS-16 — the subset re-scored with the exemplar order permuted; the
    per-judge band-change rate reported verbatim in step 2; the metamorphic
    relation holds.

    Oracle: metamorphic relation. Three assertions, in the order a reader
    needs them:

    1. **the permutation engaged** — each unit's two assemblies carry the SAME
       exemplar set (ids, bands, bytes) in a DIFFERENT order. A same-order
       pair would measure nothing (two identical dispatches are a
       self-agreement probe, not a swap), and a different set would measure a
       rubric change, not an order change;
    2. **the rate is reported verbatim** — declared through the measured
       channel, step 2 carries `measured=True` and `band_change_rate == rate`,
       with no not-measured reason riding on a measured row;
    3. **the relation** — `rate == 0.0`. A judge whose band changes under a
       pure permutation is the finding: the exemplar order is not evidence
       about the submission, so a band that moves with it is order
       sensitivity, and step 2 exists to surface exactly this.
    """
    base_url = os.environ.get("LOCAL_INFERENCE_BASE_URL")
    if not base_url:
        pytest.fail(
            "TC-STATS-16 runs on E3 against a live local server; set "
            "LOCAL_INFERENCE_BASE_URL. Skipping would let a nightly tier report "
            "green without ever running the permutation the protocol exists for "
            "(test plan §4.6)."
        )

    ModelRef = require(CONF_MODULE, "ModelRef", issue=ISSUE)
    LocalServerProvider = require(PROVIDER_MODULE, "LocalServerProvider", issue=ISSUE)
    ScoringWorker = require(JUDGE_MODULE, "ScoringWorker", issue=JUDGE_ISSUE)
    run_mvvp = require(STATS_MODULE, "run_mvvp", issue="#116")
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

        # The same leased units assembled twice: the shipped default salt, then a
        # different one — the exemplar salt is read at assemble time (`FR-JUDGE-08`).
        monkeypatch.delenv(EXEMPLAR_SEED_KNOB, raising=False)
        default_requests = {
            unit.submission_id: worker.assemble(unit) for unit in units
        }
        monkeypatch.setenv(EXEMPLAR_SEED_KNOB, PERMUTATION_SALT)
        permuted_requests = {
            unit.submission_id: worker.assemble(unit) for unit in units
        }

        # Precondition 1: the permutation engaged, as a permutation.
        for submission_id in SUBMISSIONS:
            default_views = _exemplar_views(default_requests[submission_id])
            permuted_views = _exemplar_views(permuted_requests[submission_id])
            assert len(default_views) == len(SEEDED_IDS), (
                f"submission {submission_id} assembled {len(default_views)} "
                f"exemplars, expected {len(SEEDED_IDS)} — the rubric the swap "
                "re-scores must be the seeded one"
            )
            assert sorted(view[0] for view in default_views) == sorted(SEEDED_IDS), (
                f"submission {submission_id} assembled exemplars "
                f"{tuple(view[0] for view in default_views)} — not the seeded set "
                f"{SEEDED_IDS}"
            )
            assert sorted(default_views) == sorted(permuted_views), (
                f"submission {submission_id}: the two salts did not keep the same "
                "exemplar set (ids, bands and bytes) — a permutation must not lose "
                "or duplicate an exemplar, or the measured rate would be the rate "
                "of a rubric change, not an order change"
            )
            assert default_views != permuted_views, (
                f"submission {submission_id}: the shipped default salt and "
                f"{PERMUTATION_SALT!r} produced the SAME exemplar order — the pair "
                "was verified empirically to differ under this world's digest key "
                "(TC-JUDGE-14); if this fails after a template bump, re-verify the "
                "salt pair, because a re-score that never moved the order would "
                "report a vacuous rate"
            )

        # The live re-score: each unit's two orders dispatched against the same
        # judge and backend, temperature zero (pinned above).
        bands = {}
        for submission_id in SUBMISSIONS:
            default_result = worker.dispatch(default_requests[submission_id], live_ref)
            permuted_result = worker.dispatch(
                permuted_requests[submission_id], live_ref
            )
            bands[submission_id] = (default_result.band, permuted_result.band)

        changed = sum(
            1 for default_band, permuted_band in bands.values()
            if default_band != permuted_band
        )
        rate = changed / STATED_N

        # --- the protocol reports what the run measured (FR-STATS-15) ----------
        report = run_mvvp(
            assignment_type=ASSIGNMENT_TYPE,
            configuration={
                "panel_member": (judge_id,),
                "model_build": judge_id,
                "quantization": quantization,
                "prompt_template_version": JUDGE_PROMPT_TEMPLATE_V,
            },
            measured_position_bias={judge_id: rate},
        )

        step2 = report.steps[2].outcome[judge_id]
        assert step2.measured is True, (
            "the protocol reported step 2 as not-measured for a judge the run "
            "measured — the measured channel is the declaration, and a channel "
            "the caller declared must never arrive as the not-measured value "
            "(FR-STATS-15)"
        )
        assert step2.band_change_rate == rate, (
            f"step 2 reported band_change_rate={step2.band_change_rate!r} where "
            f"the run measured {rate!r} — the per-judge band-change rate under "
            "permutation is reported verbatim, never clamped, floored or omitted "
            "(FR-STATS-15, TC-JUDGE-C17 limb 3)"
        )
        assert step2.reason == "", (
            f"step 2's measured row carried reason {step2.reason!r}; a measured "
            "outcome reports the figure, and a not-measured reason on a measured "
            "row is the shape of a swap-in, not a report"
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
            "prompt the permutation ran under (FR-STATS-19, CT-STATS-08)"
        )

        # --- the metamorphic relation itself -----------------------------------
        moved = [
            f"{submission_id}: {default_band} -> {permuted_band}"
            for submission_id, (default_band, permuted_band) in bands.items()
            if default_band != permuted_band
        ]
        assert rate == 0.0, (
            f"the band changed under a pure exemplar permutation: {moved} "
            f"(band-change rate {rate} at the stated n={STATED_N}). A judge "
            "whose band changes under a pure permutation is the finding "
            "(FR-STATS-15) — the exemplar order is not evidence about the "
            "submission, so a band that moves with it is order sensitivity, "
            "and step 2 exists to surface exactly this. Whether the backend "
            "can hold a band across byte-identical re-runs at all is "
            "TC-STATS-17's separate claim, measured independently."
        )
    finally:
        store.close()