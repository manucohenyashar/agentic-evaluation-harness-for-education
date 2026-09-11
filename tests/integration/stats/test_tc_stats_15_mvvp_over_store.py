"""`TC-STATS-15` — `run_mvvp` over a real store: six protocols, individually.

Test plan §5.16 (`TC-STATS-15`, with `TC-STATS-21`'s rung-2 re-run and
`TC-STATS-18`'s store leg), issue #120 (TS-43). Traces to `FR-STATS-05` and
`FR-STATS-19`/`FR-STATS-17`.

The plan's `TC-STATS-15` row: *"`run_mvvp` over a fixture assignment type.
Six separately-testable protocols reported **individually**, not as one
pass/fail."* `CT-STATS-C07` pins the shape at rung 0; the rung-2 leg runs the
protocol over a real store's label rows — the population step 1 and step 6
figure comes from `open_stats`' read of the `label` table, not an in-memory
fixture — and asserts each step's own artifact from that read:

- **step 1** figures the store's blind judged population per criterion —
  the 20-label table `TC-STATS-01` and `TC-STATS-25` share their hand
  arithmetic with (κ = 173/273), so the store's own read lands on the same
  reference;
- **steps 2, 3 and 5** report what the protocol *can* say headlessly: the
  declared not-measured value with its reason — never a plausible number
  (`CT-STATS-03`);
- **step 4** is `TC-STATS-18`'s store leg: the store's `label` table
  predates the assignment-type column, so its rows carry no type and the
  step is the disclosed refusal (`assignment_type_not_recorded`), never a
  figure over a population nobody split;
- **step 6** compresses the store's paired population — panel n = 20, and
  the panel's three-category distribution against the gold's four (one tail
  label at band 4) hand-computes to `panel_narrower` True.

`TC-STATS-21` (P0) is the re-run: *"A prior MVVP result, then a change to a
panel member; then to a model build; then to quantization; then to the
prompt template version. The MVVP is re-run and the prior result is **not**
carried across any of the four changes."* `CT-STATS-C08` sweeps the four at
rung 0; this leg re-runs the sweep over a store-backed instance, where the
steps' figures come from the store's population each time — a result that
served the prior configuration would be the store's read carried across the
change.

Isolation: rung 2 — real store, real label rows through `record_label`,
real `open_stats` read; no provider is reachable (`network_guard` is
autouse and each case asserts it). Hand references shared with
`TC-STATS-01`/`TC-STATS-25` (κ = 173/273) and `TC-STATS-C10` (the
compression comparison's shape; its arithmetic is pinned there).
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab
from tests.support.impl import REVIEW_MODULE, STATS_MODULE, require

pytestmark = pytest.mark.integration

#: The configuration the sweep mutates, one dimension at a time — the same
#: four dimensions `FR-STATS-19` triggers on (`CT-STATS-C08`'s table, this
#: suite's values).
BASE_CONFIGURATION: dict[str, object] = {
    "panel_member": ("judge-a", "judge-b", "judge-c"),
    "model_build": "qwen2.5-14b-instruct@3f9c",
    "quantization": "q4_K_M",
    "prompt_template_version": "judge-v7",
}

#: The 20 blind judged labels, as a contingency table over (system band,
#: teacher band) — the hand reference's cells, shared with `TC-STATS-01`'s
#: artifact case and `TC-STATS-25`'s operational-side case (κ = 173/273,
#: QWK = 123/148, α = 17/20).
T1_TABLE: dict[tuple[int, int], int] = {
    (1, 1): 6, (1, 2): 2, (2, 2): 5, (2, 3): 2, (3, 3): 4, (3, 4): 1,
}
T1_N = 20
T1_KAPPA = Fraction(173, 273)

CRITERION = "C-01"
ASSIGNMENT_TYPE = "extended_response"


def _seed_store(tmp_data_dir) -> None:
    """The store's blind judged population: the plan's 20-label table."""
    record_label = require(REVIEW_MODULE, "record_label", issue="#110")
    labels = []
    for index, ((system, teacher), count) in enumerate(sorted(T1_TABLE.items())):
        for j in range(count):
            labels.append(
                broken.Label(
                    label_id=f"mvvp-{index}-{j}",
                    criterion_id=CRITERION,
                    band=system,
                    teacher_band=teacher,
                )
            )
    for label in labels:
        record_label(data_dir=tmp_data_dir, label=label)


def _open(tmp_data_dir):
    open_stats = require(STATS_MODULE, "open_stats", issue="#115")
    return open_stats(data_dir=tmp_data_dir)


def _report(tmp_data_dir, assignment_type=ASSIGNMENT_TYPE, **kwargs):
    return _open(tmp_data_dir).run_mvvp(assignment_type=assignment_type, **kwargs)


# --- TC-STATS-15: six protocols over the store's read ------------------------------------------


def test_tc_stats_15_the_mvvp_over_the_store_reports_six_steps_individually(
    tmp_data_dir, network_guard
):
    """The report shape over the store's population, and no collapsed verdict.

    The six steps carry their own requirement (`FR-STATS-05`'s mapping) and
    their own outcome; the report offers no single pass/fail — the same
    prohibition `CT-STATS-C07` pins on the return type, re-asserted on the
    rung-2 artifact, because a store-shaped convenience verdict is exactly
    what a dashboard would ask for."""
    _seed_store(tmp_data_dir)
    report = _report(tmp_data_dir)

    assert set(report.steps) == set(vocab.MVVP_STEPS), (
        f"the store-backed run covers steps {sorted(report.steps)}; the "
        "protocol is six, per FR-STATS-05"
    )
    for step, requirement in vocab.MVVP_STEPS.items():
        assert report.steps[step].requirement == requirement
        assert report.steps[step].outcome is not None, (
            f"step {step} has no outcome of its own over the store's "
            "population — the six protocols are not separately reported"
        )
    collapsed = [
        name
        for name in ("passed", "ok", "success", "verdict", "overall", "is_valid")
        if hasattr(report, name)
    ]
    assert collapsed == [], (
        f"the rung-2 MVVP report offers {collapsed}; six separately-testable "
        "protocols, never one pass/fail (FR-STATS-05, TC-STATS-15)"
    )
    network_guard.assert_no_network()


def test_tc_stats_15_step1_figures_the_stores_blind_population_per_criterion(
    tmp_data_dir, network_guard
):
    """Step 1's figures are the store's own read, on the shared hand
    reference: n = 20 and κ = 173/273 — the arithmetic `TC-STATS-01` and
    `TC-STATS-25` compute; the store's rows land on the same figure."""
    _seed_store(tmp_data_dir)
    report = _report(tmp_data_dir)

    figures = report.steps[1].outcome
    assert set(figures) == {CRITERION}, (
        f"step 1 figured {sorted(figures)}; the store carries the one "
        "criterion's labels and the surface figures per criterion"
    )
    figure = figures[CRITERION]
    assert figure.n == T1_N
    assert figure.kappa == pytest.approx(float(T1_KAPPA)), (
        f"the store-backed figure's κ was {figure.kappa!r}; the plan's "
        f"20-label matrix hand-computes to {float(T1_KAPPA):.6f} (173/273) — "
        "the same reference TC-STATS-01 and TC-STATS-25 pin"
    )
    network_guard.assert_no_network()


def test_tc_stats_15_the_headless_steps_report_the_declared_not_measured_value(
    tmp_data_dir, network_guard
):
    """Steps 2, 3 and 5 over the store, no measured channel: the explicit
    not-measured value with its declared reason.

    Nothing was measured here — no provider is reachable, and the measured
    channel was not supplied. The honest step is the not-measured value with
    its reason (`CT-STATS-03`), never a plausible number; and the backend's
    capability claim is the not-declared disclosure (`CT-PROV-04`'s claim is
    the backend's to declare, not the protocol's to guess). The live tier
    (`TC-STATS-16`/`TC-STATS-17`) supplies the channel; this pins that its
    absence is the reason value, not a fabricated rate."""
    _seed_store(tmp_data_dir)
    report = _report(tmp_data_dir)

    for judge, result in report.steps[2].outcome.items():
        assert result.measured is False and result.band_change_rate is None, (
            f"judge {judge} carried a band-change rate nobody measured"
        )
        assert result.reason == "no_position_bias_measurement_supplied"
    for judge, result in report.steps[3].outcome.items():
        assert result.measured is False and result.self_agreement is None
        assert result.reason == "no_replication_measurement_supplied"
        assert result.backend_claims_deterministic_at_temperature_zero is None
        assert result.backend_claim_source == "not_declared"
    for judge, pairing in report.steps[5].paired_results.items():
        assert pairing.self_agreement_measured is False
        assert pairing.pairing_required is False, (
            f"judge {judge} was pairing-required with no measured rate; the "
            "pairing requirement is a claim about a measured rate, and a "
            "not-measured judge cannot be high-stability"
        )
    network_guard.assert_no_network()


def test_tc_stats_15_step4_over_the_store_is_the_recorded_absence(tmp_data_dir, network_guard):
    """`TC-STATS-18`'s store leg — the exact refusal over real rows.

    The store's `label` table predates the assignment-type column, so every
    row `open_stats` read carries no type and the step is the disclosed
    refusal (`assignment_type_not_recorded`, `figures` empty) — the store
    cannot manufacture the dimension, and the outcome says so rather than
    computing over a population nobody split (the same branch the rung-0
    file pins, asserted here against the real rows)."""
    _seed_store(tmp_data_dir)
    report = _report(tmp_data_dir)

    outcome = report.steps[4].outcome
    assert outcome.assignment_type == ASSIGNMENT_TYPE
    assert outcome.assignment_type_recorded is False
    assert outcome.figures == {}
    assert outcome.reason == "assignment_type_not_recorded", (
        f"step 4 over the store returned reason {outcome.reason!r}; the "
        "label table carries no assignment type, so the step discloses "
        "that — a figure over a population nobody split is the spanning "
        "figure FR-STATS-17 refuses"
    )
    assert outcome.spanning_refused is True
    network_guard.assert_no_network()


def test_tc_stats_15_step6_compares_the_store_panel_against_its_gold(tmp_data_dir, network_guard):
    """Step 6 over the store's paired population: n = 20, and the panel's
    shape is the narrower one — hand-computed.

    Panel bands over the plan's table: 6, 7, 7 across three bands →
    H = 1.581 bits. Gold: 6, 7, 6, 1 across four → H = 1.788. The panel
    compressed toward the middle of a shape the gold never had: narrower,
    and the comparison says so against the blind gold's own distribution —
    with the stated limitation in the value (`CT-STATS-10`), always."""
    _seed_store(tmp_data_dir)
    report = _report(tmp_data_dir)

    outcome = report.steps[6].outcome
    assert outcome.n == T1_N
    assert outcome.stated_limitation == vocab.CO_COMPRESSION_LIMITATION, (
        "the store-backed compression outcome dropped the stated limitation; "
        "the CO blind spot travels in the value, at every rung"
    )
    assert outcome.panel_narrower is True, (
        "the panel's three-category distribution (H ≈ 1.58) is narrower than "
        "the gold's four-band shape (H ≈ 1.79) — a gold side carrying a band "
        "the panel never used is the compression direction the check exists "
        "to name"
    )
    assert outcome.gold_band_entropy is not None
    network_guard.assert_no_network()


# --- TC-STATS-21: the re-run, over the store's population --------------------------------------


@pytest.mark.parametrize("dimension", vocab.MVVP_RERUN_TRIGGERS)
def test_tc_stats_21_the_store_backed_mvvp_reruns_when_each_dimension_changes(
    tmp_data_dir, dimension
):
    """`TC-STATS-21`'s rung-2 sweep: one change per dimension, the protocol
    re-measured over the store's population.

    The four-change sweep is `CT-STATS-C08`'s (rung 0, full re-run asserted
    per step); the rung-2 leg pins that the *store-backed* run is re-measured
    per change — the prior result is not carried across any of the four —
    and that the current result names the changed configuration."""
    _seed_store(tmp_data_dir)
    base_configuration = dict(BASE_CONFIGURATION)
    run_mvvp = require(STATS_MODULE, "run_mvvp", issue="#116")

    before = run_mvvp(_open(tmp_data_dir), assignment_type=ASSIGNMENT_TYPE,
                      configuration=base_configuration)
    changed = dict(base_configuration)
    changed[dimension] = _changed_to(dimension)
    after = run_mvvp(_open(tmp_data_dir), assignment_type=ASSIGNMENT_TYPE,
                     configuration=changed)

    assert after.result_id != before.result_id, (
        f"changing {dimension} returned the same store-backed MVVP result; "
        "the protocol re-runs the full sweep on any of the four (FR-STATS-19)"
    )
    assert after.measured_configuration[dimension] == _changed_to(dimension)
    assert before.result_id not in after.contributing_results, (
        f"the prior result contributed to the re-run; FR-STATS-19: not "
        "carried across any of the four changes"
    )


def _changed_to(dimension: str):
    """One value per dimension, distinct from the base's — a failure names
    the dimension that stopped re-running."""
    return {
        "panel_member": ("judge-a", "judge-b", "judge-d"),
        "model_build": "qwen2.5-14b-instruct@7a02",
        "quantization": "q8_0",
        "prompt_template_version": "judge-v8",
    }[dimension]