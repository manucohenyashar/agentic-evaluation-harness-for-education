"""Validity T6 (issue #899): what promotion computes, one record per administration, and the
anomaly baseline (TC-STATS-41, TC-STATS-42, TC-STATS-43).

| Case | What it pins | Rung |
|---|---|---|
| TC-STATS-41 | the validity seed promoted: atomic kappa = 0.5, holistic kappa and QWK equal to hand-computed literals, no QWK on the two-band line, one stored row per criterion with its own scoring model, no deterministic figure, `agreement_kappa IS NULL`, weakest = the lower kappa, the flags column stored, engine figures and non-inferiority `insufficient_data` | 3 |
| TC-STATS-42 | `promote` twice: one row, no label claimed twice; Skip -> `blind_count = 0`, `skipped`; Finish with none marked -> `none_marked`; 3 of 15 unmarked -> `unmarked_count = 3`; the in-memory promote gives the durable promote's figures | 3 |
| TC-STATS-43 | the baseline per judged criterion equals the run's final scores' statistics; a second administration's cell more than 3 sd out gets `should_escalate`'s anomaly reason, and the same cell before any baseline does not | 3 |

The world is `tests/support/validity_seed.py` (its docstring lists what is seeded). Every
blind label comes from a real draw, real drafts and a real Finish or Skip on M-REVIEW's
store-backed service, and every record from M-PIPE's `promote_administration`.

**Disclosed departures (in the PR as well).**

1. *Routing and origin spread.* M-REVIEW draws only `queued` and `provisional` cells and never a
   `random_arm` one, so the seed spreads its labels over `queued`/`provisional` and
   `base`/`escalation`. `auto`, `reviewed`, `triage` and `random_arm` cells cannot carry a blind
   label.
2. *The deterministic line.* The draw never offers a deterministic cell, so "the deterministic
   line absent" would be vacuous. The case inserts one blind, unseen label on the MCQ line
   `C-01` under the run's id, in the column shape the flow writes, before promotion. The
   admissibility filter must keep it out.
3. *Surface-proxy flags.* `promote_administration` opens the stats with `open_stats`, which
   carries no measured-correlations channel, so the production record stores the empty array.
   The case pins that the column is stored as a JSON array (`[]`), not NULL. The planted-channel
   leg is TC-STATS-11 (`test_tc_stats_11_promote_flags.py`).
4. *Gate bins.* No decision engine ran in the seed, so every calibration bin has n = 0. "Bins
   below 20 are `insufficient_data`" holds, but trivially; the per-engine figure is the
   discriminating leg (`llm_engine_off`, n = 12 < 60).
5. *TC-STATS-43's M-ORCH pairing.* The baseline is read the way the aggregate hook reads it
   (`PackageCatalog.baselines_for` under the run's frozen backend and panel build) and passed to
   M-AGG's `should_escalate`, with the score row built from the second administration's stored
   cell. The private hook (`pipeline.hooks._escalation_inputs`) is not called.
"""

from __future__ import annotations

import json
import math

import pytest

from tests.support.validity_seed import (
    ATOMIC,
    DETERMINISTIC,
    HOLISTIC,
    HOLISTIC_BANDS,
    VALIDITY_SYSTEM,
    VALIDITY_TEACHER,
    ValidityStore,
    teacher_bands,
    validity_seed,
)

pytestmark = pytest.mark.integration

TOLERANCE = 1e-9


def _promoted_seed(tmp_path):
    world, administration = validity_seed(tmp_path / "w")
    outcome = world.promote(administration, "finish")
    assert outcome.promoted, f"fixture: the seed was not promoted: {outcome.reason!r}"
    return world, administration, outcome.update


# --- TC-STATS-41: what promotion computes ------------------------------------------------------


def test_tc_stats_41_promotion_figures_equal_the_hand_references(tmp_path, network_guard):
    """TC-STATS-41 (FR-STATS-32, CT-STATS-29; RSV-11). The validity seed, promoted on Finish.

    Hand references (rows = system band, columns = teacher band):

    Atomic C-10, two bands, confusion [[5, 1], [2, 4]], N = 12.
      p_o = 9/12 = 0.75; system marginals (6, 6), teacher marginals (7, 5);
      p_e = (6*7 + 6*5)/144 = 72/144 = 0.5; kappa = (0.75 - 0.5)/(1 - 0.5) = 0.5.
      Two bands: no QWK.

    Holistic C-11, four declared bands, confusion
      [[1,0,0,0], [2,6,2,0], [0,0,1,0], [0,0,0,0]], N = 12.
      p_o = 8/12; system marginals (1, 10, 1, 0), teacher marginals (3, 6, 3, 0);
      p_e = (1*3 + 10*6 + 1*3)/144 = 66/144;
      kappa = (96 - 66)/(144 - 66) = 30/78 = 5/13 = 0.384615384615...
      QWK, weights (i - j)^2 (the 1/(K-1)^2 scale cancels):
        observed sum w*O = 2*1 (B2->B1) + 2*1 (B2->B3) = 4;
        expected sum w*E = sum r_i c_j (i-j)^2 / 12
          = [1*(6*1 + 3*4) + 10*(3*1 + 3*1) + 1*(3*4 + 6*1)] / 12 = 96/12 = 8;
        QWK = 1 - 4/8 = 0.5.

    The weakest criterion is C-11 (5/13 < 1/2), the second in sort order, so "the first
    criterion" and "the weakest" cannot agree by accident."""
    world, administration, update = _promoted_seed(tmp_path)
    try:
        # Preconditions: the labels carry the spread the seed claims, and the deterministic
        # contaminant is not yet there.
        labels = world.labels(administration)
        assert len(labels) == 24
        assert {row["routing"] for row in labels} == {"queued", "provisional"}, labels
        assert {row["origin"] for row in labels} == {"base", "escalation"}, labels

        figures = update.criterion_figures
        assert set(figures) == {ATOMIC, HOLISTIC}, (
            f"figures for {sorted(figures)}; only the two judged lines have a figure")

        atomic, holistic = figures[ATOMIC], figures[HOLISTIC]
        assert atomic["confusion"] == [[5, 1], [2, 4]], atomic["confusion"]
        assert atomic["kappa"] == pytest.approx(0.5, abs=TOLERANCE)
        assert atomic["qwk"] is None, f"a two-band line carried a QWK: {atomic['qwk']!r}"
        assert holistic["confusion"] == [[1, 0, 0, 0], [2, 6, 2, 0], [0, 0, 1, 0], [0, 0, 0, 0]]
        assert holistic["kappa"] == pytest.approx(5 / 13, abs=TOLERANCE)
        assert holistic["qwk"] == pytest.approx(0.5, abs=TOLERANCE)
        assert (atomic["matched"], atomic["n"]) == (9, 12)
        assert (holistic["matched"], holistic["n"]) == (8, 12)

        # Atomic and holistic are stored apart, each with its own model.
        stored = world.criterion_stats(administration)
        assert set(stored) == {ATOMIC, HOLISTIC}, f"criterion_stats rows: {sorted(stored)}"
        assert stored[ATOMIC]["scoring_model"] == "atomic"
        assert stored[HOLISTIC]["scoring_model"] == "holistic"
        assert stored[ATOMIC]["kappa"] == pytest.approx(0.5, abs=TOLERANCE)
        assert stored[ATOMIC]["qwk"] is None
        assert stored[HOLISTIC]["kappa"] == pytest.approx(5 / 13, abs=TOLERANCE)
        assert stored[HOLISTIC]["qwk"] == pytest.approx(0.5, abs=TOLERANCE)

        (record,) = world.package_validation(administration)
        assert record["agreement_kappa"] is None, (
            f"agreement_kappa = {record['agreement_kappa']!r} on a two-criterion record; it "
            "is NULL whenever more than one criterion has a figure (CT-STATS-29)")
        weakest = json.loads(record["weakest_per_population"])
        assert weakest == {administration.cohort_id: {
            "criterion_id": HOLISTIC, "kappa": pytest.approx(5 / 13, abs=TOLERANCE)}}, weakest
        assert record["surface_proxy_flags"] is not None
        assert json.loads(record["surface_proxy_flags"]) == [], record["surface_proxy_flags"]

        for criterion, figure in figures.items():
            engine_off = figure["per_engine"]["llm_engine_off"]
            assert engine_off == {"n": 12, "ordinal_alpha": None,
                                  "status": "insufficient_data"}, (criterion, engine_off)
            assert all(item["status"] == "insufficient_data"
                       for item in figure["per_engine"].values()), figure["per_engine"]
            assert figure["gate_bins"], f"{criterion}: no gate bins at all"
            assert all(item["status"] == "insufficient_data" and item["n"] < 20
                       for item in figure["gate_bins"]), figure["gate_bins"]
            assert figure["noninferiority"] == "insufficient_data", figure["noninferiority"]
        network_guard.assert_no_network()
    finally:
        world.close()


def test_tc_stats_41_the_deterministic_line_never_has_a_figure(tmp_path, network_guard):
    """TC-STATS-41: a blind, unseen label on the deterministic MCQ line, inside the run's
    population, is not evidence (R53). The record has no figure for it, and the stored
    figures are the judged lines' alone."""
    world, administration = validity_seed(tmp_path / "w")
    try:
        source = world.labels(administration)[0]
        world.insert_label_like(
            source, label_id="label-deterministic-contaminant", criterion_id=DETERMINISTIC,
            evaluation_mode="deterministic", band="correct", teacher_band="correct",
            system_band="incorrect", saw_system_output=0, label_type="blind")
        assert len(world.labels(administration)) == 25, "fixture: the contaminant is not stored"
        update = world.promote(administration, "finish").update
        assert DETERMINISTIC not in update.criterion_figures, update.criterion_figures
        assert DETERMINISTIC not in world.criterion_stats(administration)
        assert set(update.criterion_figures) == {ATOMIC, HOLISTIC}
        assert update.blind_count == 24, (
            f"blind_count {update.blind_count}: the deterministic label was counted as evidence")
        network_guard.assert_no_network()
    finally:
        world.close()


# --- TC-STATS-42: one record per administration ------------------------------------------------


def test_tc_stats_42_a_promote_twice_writes_one_record_and_claims_no_label_twice(
        tmp_path, network_guard):
    """TC-STATS-42 (FR-STATS-33, CT-STATS-28). After the administration is recorded, a second
    `ValidationStats.promote` for the same (version, cohort) writes nothing, claims nothing and
    returns the stored record. A fresh unclaimed label of the same run, inserted between the two
    calls, stays unclaimed: a second claim would stamp it.

    `promote_administration` returns early on a recorded administration and never reaches
    `promote`, so the second call here is `promote` itself."""
    from aeh.stats import open_stats

    world, administration, first = _promoted_seed(tmp_path)
    try:
        labels = world.labels(administration)
        assert {row["cohort_id"] for row in labels} == {administration.cohort_id}, (
            "the first promote did not claim every label of the administration")
        world.insert_label_like(labels[0], label_id="label-late-unclaimed", cohort_id=None)

        stats = open_stats(world.store.data_dir, cohort_id=administration.cohort_id)
        second = stats.promote(administration.cohort_id,
                               package_version=administration.package_version_id,
                               run_id=administration.run_id)
        assert second.already_recorded is True
        assert second.blind_count == first.blind_count == 24
        late = world.durable_rows("SELECT cohort_id FROM label WHERE label_id = ?",
                                  "label-late-unclaimed")
        assert late == [{"cohort_id": None}], f"the second promote claimed a label: {late}"
        assert len(world.package_validation(administration)) == 1
        stored = world.durable_rows(
            "SELECT criterion_id, COUNT(*) AS n FROM criterion_stats WHERE cohort_id = ? "
            "GROUP BY criterion_id", administration.cohort_id)
        assert {row["criterion_id"]: row["n"] for row in stored} == {ATOMIC: 1, HOLISTIC: 1}
        assert second.criterion_figures[ATOMIC]["kappa"] == pytest.approx(0.5, abs=TOLERANCE)

        again = world.promote(administration, "finish")
        assert not again.promoted and again.reason == "this administration is already recorded"
        assert len(world.package_validation(administration)) == 1
        network_guard.assert_no_network()
    finally:
        world.close()


def _fresh_administration(tmp_path):
    world = ValidityStore(tmp_path / "w")
    return world, world.administer("c-absence", VALIDITY_SYSTEM)


def test_tc_stats_42_b_skip_records_no_evidence_and_the_reason(tmp_path, network_guard):
    """TC-STATS-42: Skip, with one seat drafted, records `blind_count = 0` and
    `absence_reason = 'skipped'`."""
    world, administration = _fresh_administration(tmp_path)
    try:
        seats = world.draw(administration, 15)
        world.mark(administration, seats[:1],
                   teacher_bands(administration, VALIDITY_TEACHER))
        world.skip(administration)
        outcome = world.promote(administration, "skip")
        assert outcome.promoted, outcome.reason
        (record,) = world.package_validation(administration)
        assert (record["blind_count"], record["absence_reason"]) == (0, "skipped"), record
        assert outcome.update.criterion_figures == {}, outcome.update.criterion_figures
        network_guard.assert_no_network()
    finally:
        world.close()


def test_tc_stats_42_c_finish_with_none_marked_records_none_marked(tmp_path, network_guard):
    """TC-STATS-42: Finish with no seat drafted records `absence_reason = 'none_marked'` and
    no evidence."""
    world, administration = _fresh_administration(tmp_path)
    try:
        world.draw(administration, 15)
        world.finish(administration)
        world.promote(administration, "finish")
        (record,) = world.package_validation(administration)
        assert (record["blind_count"], record["absence_reason"]) == (0, "none_marked"), record
        assert record["unmarked_count"] == 15, record
        network_guard.assert_no_network()
    finally:
        world.close()


def test_tc_stats_42_d_three_of_fifteen_unmarked_is_recorded(tmp_path, network_guard):
    """TC-STATS-42: 15 seats, 12 drafted, Finish -> `unmarked_count = 3`, `blind_count = 12`,
    no absence reason."""
    world, administration = _fresh_administration(tmp_path)
    try:
        seats = world.draw(administration, 15)
        assert len(seats) == 15
        marked = world.mark(administration, seats[:12],
                            teacher_bands(administration, VALIDITY_TEACHER))
        assert marked == 12
        world.finish(administration)
        world.promote(administration, "finish")
        (record,) = world.package_validation(administration)
        assert (record["unmarked_count"], record["blind_count"], record["absence_reason"]) == (
            3, 12, None), record
        network_guard.assert_no_network()
    finally:
        world.close()


#: The headline keys both promote paths compute. The engine figures, `bands` and `cumulative`
#: legitimately differ: the in-memory path has no store, so no engine context, no package scale
#: and no earlier record.
HEADLINE_KEYS = ("scoring_model", "n", "paired", "matched", "kappa", "qwk", "reason",
                 "confusion", "band_count")


def test_tc_stats_42_e_the_in_memory_promote_equals_the_durable_one(tmp_path, network_guard):
    """TC-STATS-42: `_record_in_memory` (a `build_stats` instance, no data directory) over the
    same stored labels, scoring models and declared band counts gives the durable promote's
    per-criterion figures, counters and weakest entry, and the same for a skip."""
    from aeh.stats import build_stats
    from aeh.stats.admissibility import _StoredLabel

    world, administration, durable = _promoted_seed(tmp_path)
    try:
        stored = [_StoredLabel(row) for row in world.labels(administration)]

        def in_memory(**kwargs):
            stats = build_stats(stored, scoring_models={ATOMIC: "atomic", HOLISTIC: "holistic"},
                                band_counts={ATOMIC: 2, HOLISTIC: 4})
            assert stats._data_dir is None, "fixture: build_stats must take the in-memory path"
            return stats.promote(administration.cohort_id,
                                 package_version=administration.package_version_id,
                                 run_id=administration.run_id, **kwargs)

        memory = in_memory()
        assert set(memory.criterion_figures) == set(durable.criterion_figures)
        for criterion, figure in durable.criterion_figures.items():
            assert {key: memory.criterion_figures[criterion][key] for key in HEADLINE_KEYS} == {
                key: figure[key] for key in HEADLINE_KEYS}, criterion
        assert (memory.blind_count, memory.agreement_kappa, memory.weakest_per_population) == (
            durable.blind_count, durable.agreement_kappa, durable.weakest_per_population)

        skipped = in_memory(absence_reason="skipped")
        assert (skipped.blind_count, skipped.absence_reason, skipped.criterion_figures) == (
            0, "skipped", {})
        network_guard.assert_no_network()
    finally:
        world.close()


# --- TC-STATS-43: the baseline is written and used ---------------------------------------------


def _validation_records(world, package_version_id):
    """The baseline rows of `validation_record` for the version, from the package's file."""
    import sqlite3

    (path,) = sorted((world.root / "packages").glob("*.pkg.sqlite"))
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(
            "SELECT criterion_id, backend_profile, panel_build_ref, expected_mean, expected_sd, "
            "expected_histogram FROM validation_record WHERE package_version_id = ? "
            "AND expected_mean IS NOT NULL", (package_version_id,))]


def _population_mean_sd(ordinals):
    mean = sum(ordinals) / len(ordinals)
    return mean, math.sqrt(sum((value - mean) ** 2 for value in ordinals) / len(ordinals))


def test_tc_stats_43_baseline_from_final_scores_and_the_anomaly_it_raises(
        tmp_path, monkeypatch, network_guard):
    """TC-STATS-43 (FR-STATS-34; pair M-ORCH).

    The run's final judged scores (every judged cell is final in the seed):
      C-10: fail x6, pass x6 -> ordinals 0 x6, 1 x6: mean 0.5, population sd 0.5,
            histogram {"0": 6, "1": 6}.
      C-11: the seed's B3 cell (submission 11) is re-scored B4 and left NOT final
            (`provisional_unreviewed`), so the final cells are B1 x1, B2 x10 -> ordinals 0,
            1 x10: mean 10/11, variance (1*(10/11)^2 + 10*(1/11)^2)/11 = 10/121,
            sd = sqrt(10)/11 = 0.287480..., histogram {"0": 1, "1": 10}. A baseline that
            counted the non-final cell would carry {"3": 1} and another mean.

    A second administration of the same version holds a C-11 cell at B4 (ordinal 3):
    z = (3 - 10/11)/(sqrt(10)/11) = 23/sqrt(10) = 7.273 >= 3. With the baseline, `should_escalate` names the
    distributional anomaly; with no baseline (before the first administration is promoted)
    the same score row gets no anomaly reason."""
    from aeh.agg import should_escalate

    monkeypatch.setattr("aeh.pipeline.hooks._ESCALATION_INPUTS", {})
    world, first = validity_seed(tmp_path / "w")
    try:
        with world.store.cohort(first.cohort_id).transaction() as tx:
            tx.execute("UPDATE criterion_score SET band = 'B4', state = 'provisional_unreviewed' "
                       "WHERE run_id = :r AND submission_id = :s AND criterion_id = :c",
                       r=first.run_id, s=first.submission(11), c=HOLISTIC)
        second = world.administer("c-second", {HOLISTIC: ("B4",) + ("B2",) * 11})
        handle_first, handle_second = world.run_handle(first), world.run_handle(second)
        assert (handle_second.backend_profile, handle_second.panel_build_ref) == (
            handle_first.backend_profile, handle_first.panel_build_ref), (
            "fixture: the two administrations must share the baseline's scope")

        def baselines():
            return world.catalog().baselines_for(
                second.package_version_id, backend_profile=handle_second.backend_profile,
                panel_build_ref=handle_second.panel_build_ref)

        cell = world.store.cohort(second.cohort_id).query(
            "SELECT band FROM criterion_score WHERE run_id = :r AND submission_id = :s "
            "AND criterion_id = :c", r=second.run_id, s=second.submission(0), c=HOLISTIC)
        score = {"ordinal": HOLISTIC_BANDS.index(cell[0]["band"]),
                 "band_count": len(HOLISTIC_BANDS)}
        assert score["ordinal"] == 3

        def anomaly_reasons(baseline):
            decision = should_escalate(score, None, None, baseline)
            return [reason for reason in decision.reasons
                    if reason.startswith("distributional anomaly")]

        before = baselines()
        assert anomaly_reasons(before[HOLISTIC]) == [], (
            f"an anomaly fired with no baseline recorded: {before[HOLISTIC]!r}")

        world.promote(first, "finish")
        after = baselines()
        mean, sd = _population_mean_sd([0] * 6 + [1] * 6)
        assert after[ATOMIC] == {"mean": pytest.approx(mean, abs=TOLERANCE),
                                 "std": pytest.approx(sd, abs=TOLERANCE),
                                 "histogram": {"0": 6, "1": 6}}, after[ATOMIC]
        mean, sd = _population_mean_sd([0] + [1] * 10)
        assert (mean, sd) == (pytest.approx(10 / 11), pytest.approx(math.sqrt(10) / 11))
        assert after[HOLISTIC] == {"mean": pytest.approx(mean, abs=TOLERANCE),
                                   "std": pytest.approx(sd, abs=TOLERANCE),
                                   "histogram": {"0": 1, "1": 10}}, after[HOLISTIC]
        # The `validation_record` rows themselves, in the package's file.
        rows = _validation_records(world, second.package_version_id)
        assert {row["criterion_id"] for row in rows} == {ATOMIC, HOLISTIC}, rows
        holistic_row = next(row for row in rows if row["criterion_id"] == HOLISTIC)
        assert holistic_row["expected_mean"] == pytest.approx(10 / 11, abs=TOLERANCE)
        assert holistic_row["expected_sd"] == pytest.approx(math.sqrt(10) / 11, abs=TOLERANCE)
        assert json.loads(holistic_row["expected_histogram"]) == {"0": 1, "1": 10}
        assert (holistic_row["backend_profile"], holistic_row["panel_build_ref"]) == (
            handle_first.backend_profile, handle_first.panel_build_ref)
        z = (3 - mean) / sd
        assert z >= 3
        assert anomaly_reasons(after[HOLISTIC]) == [
            f"distributional anomaly vs package baseline (z={z:.2f})"], after[HOLISTIC]
        network_guard.assert_no_network()
    finally:
        world.close()
