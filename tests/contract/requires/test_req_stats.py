"""`TS-81` (issue #154) — `Requires` pairwise integration into **`M-STATS`**: every consumer's
assumption about validation statistics, override history and the absence value, checked against
the real `aeh.stats` (rung 3).

| Case | Consumer | Assumption checked here |
|---|---|---|
| TC-REQ-41 | `M-AGG` | M-STATS' override history, fed to escalation, routes no data differently from a genuine zero |
| TC-REQ-57 | `M-REVIEW` | the same history ranks no data apart from a zero, and reaches the P(error) input of a stored queue row |
| TC-REQ-68 | `M-CALIB` | "no evidence" and "no disagreement" are different values, more labels narrow the interval, and the compression check returns its limitation |
| TC-REQ-73 | `M-CONFORM` | an agreement figure is scoped to one backend and never pools two |
| TC-REQ-79 | `M-CONSOLE` | a figure cannot reach the console without `n` and scope, and the console renders the absence type as absence |
| TC-REQ-83 | `M-PKG` | the record stores what `promote` computed, with no coercion, and blind counts stay apart from operational ones |

Labels are built in `M-REVIEW`'s label shape (`label_type`, `saw_system_output`,
`evaluation_mode`, both bands) so M-STATS' own admissibility filter applies to them.

Disclosed consumer gaps: `aeh.calib` and `aeh.conform` make no M-STATS call today, so TC-REQ-68 and
TC-REQ-73 check the provider's side of the assumption only, and CT-STATS-08 (a build change
invalidates an MVVP result) has no conformance path to exercise.

Markers: `contract` and `integration` (§4.7).
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.orch  # noqa: E401,F401
import aeh.pkg, aeh.review, aeh.synth  # noqa: E401,F401
import aeh.stats as stats
from aeh.stats import NoValidationData, ValidationStats

pytestmark = [pytest.mark.contract, pytest.mark.integration]


def label(criterion_id, system_band, teacher_band, *, backend="edge-local", origin="accept", i=0):
    return SimpleNamespace(
        label_id=f"L-{criterion_id}-{backend}-{i}", run_id="run-1", student_ref=f"ref-{i}",
        criterion_id=criterion_id, label_type="blind", saw_system_output=0,
        evaluation_mode="judged", system_band=system_band, teacher_band=teacher_band,
        band=teacher_band, backend_profile=backend, origin=origin,
    )


def _histories():
    """A criterion nobody reviewed, and a criterion reviewed four times with no override."""
    reviewed = [label("C-ZERO", "b1", "b1", i=i) for i in range(4)]
    s = ValidationStats(reviewed)
    return s.criterion_override_history("C-NEVER"), s.criterion_override_history("C-ZERO")


def test_tc_req_41_escalation_routes_no_override_data_differently_from_a_zero():
    """`TC-REQ-41` (`M-AGG` → `M-STATS`, CT-STATS-09): M-STATS returns `NoValidationData` for a
    never-reviewed criterion and a zero-rate history for one reviewed without overrides. The score
    is set up so the history decides: its interior band position alone contributes 1.0 of concern,
    and the threshold is set to 1.5, so only the no-data weight (0.5) can tip it. Handed each
    history, `should_escalate` must escalate on no data and not on the measured zero.

    Positive control: M-AGG's own no-data channel (`override_rate=None`) does flip the decision."""
    from aeh.agg import aggregate, should_escalate
    from tests.support.agg_vocabulary import agg_config, band, criterion, expected_distribution, panel, signals

    never, zero = _histories()
    assert isinstance(never, NoValidationData), f"fixture: {never!r}"
    assert getattr(zero, "override_rate", None) == 0.0, f"fixture: {zero!r}"
    crit = criterion([band("a", 0, 0.0), band("b", 1, 1.0), band("c", 2, 2.0), band("d", 3, 3.0)],
                     scoring_model="holistic", criterion_id="C1")
    config = agg_config()
    score = aggregate(panel(("b", 1), ("c", 2), ("c", 2)), crit, signals(), config=config)
    config.escalation_threshold = 1.5

    def escalates(history):
        return should_escalate(score=score, criterion=crit, history=history,
                               baseline=expected_distribution(), config=config).escalate

    assert escalates(zero) is False, "fixture: the measured zero must leave the score below threshold"
    assert escalates(SimpleNamespace(override_rate=None)) is True, (
        "control: M-AGG's own no-data channel does not tip the score, so the case cannot discriminate")
    assert escalates(never) is True, (
        "escalation routes M-STATS' no-data history exactly like a measured zero override rate. "
        "[When written: should_escalate reads _row_field(history, 'override_rate'); NoValidationData "
        "carries no such field, so the read returns the absent marker and the no-data weight, which "
        "applies only to override_rate=None, is skipped. rank_criteria_for_escalation handles the "
        "absence value; the per-score escalation decision does not.]")


def test_tc_req_57_review_ranking_and_p_error_input_distinguish_no_data_from_a_zero(tmp_data_dir):
    """`TC-REQ-57` (`M-REVIEW` → `M-STATS`, CT-STATS-09). Two halves over the same two histories:

    - **The criteria ranking** (`rank_queue_items(criteria=)`) takes M-STATS' values as given,
      ranks the never-reviewed criterion first, and marks it `no_data`.
    - **The P(error) input.** Over a real store, C-ZERO has four admissible blind labels and no
      override; C-NEVER has none. The store-backed review service's rows must carry
      `historical_override_rate` 0.0 for C-ZERO and no data for C-NEVER. A measured zero that
      reaches ranking as "no data" makes the reviewed criterion look unmeasured."""
    from aeh.review import open_review, rank_queue_items, record_label
    from aeh.store import open_store
    from tests.support import broken_stats_fixtures as broken
    from tests.support.grade_vocabulary import write_criterion_scores
    from tests.support.orch_run import ORCH_COHORT_ID, seed_run

    never, zero = _histories()
    ranked = rank_queue_items(criteria={"C-ZERO": zero, "C-NEVER": never})
    assert [(r.criterion_id, r.no_data) for r in ranked] == [("C-NEVER", True), ("C-ZERO", False)], ranked

    store = open_store(tmp_data_dir)
    try:
        seed_run(store, submissions=("S1",), criteria=(
            {"criterion_id": "C-NEVER", "kind": "open", "scoring_model": "atomic"},
            {"criterion_id": "C-ZERO", "kind": "open", "scoring_model": "atomic"}))
        write_criterion_scores(store.cohort(ORCH_COHORT_ID), [("S1", "C-NEVER", "B2", 25.0, "provisional"),
                                                              ("S1", "C-ZERO", "B3", 50.0, "provisional")])
    finally:
        store.close()
    for i in range(4):
        record_label(data_dir=tmp_data_dir, label=broken.Label(label_id=f"z{i}", criterion_id="C-ZERO",
                                                              band=2, teacher_band=2, origin="blind_sample"))
    measured = stats.open_stats(data_dir=tmp_data_dir).criterion_override_history("C-ZERO")
    assert getattr(measured, "override_rate", None) == 0.0, f"fixture: M-STATS over the store reads {measured!r}"

    service = open_review(tmp_data_dir, run_id=ORCH_COHORT_ID)
    try:
        rates = {row.criterion_id: row.historical_override_rate for row in service.scores(ORCH_COHORT_ID)}
    finally:
        service.close()
    assert rates.get("C-ZERO") == 0.0 and rates.get("C-NEVER") is None, (
        f"the stored queue rows' P(error) input reads {rates}: M-STATS measured C-ZERO's override rate as "
        f"0.0, but the row carries no data, so a reviewed criterion ranks as an unmeasured one. [When "
        f"written: the store-backed review row reads historical_override_rate from the criterion_score "
        f"mapping, which has no such column, and no src code fills it from "
        f"M-STATS' criterion_override_history.]")


def test_tc_req_68_no_evidence_and_no_disagreement_are_different_values():
    """`TC-REQ-68` (`M-CALIB` → `M-STATS`, CT-STATS-01/03/10):

    - Over no blind labels, `agreement` returns `NoValidationData`. Over perfectly agreeing blind
      labels, it returns an `AgreementFigure` carrying `n`. The two are different types.
    - Accumulating labels makes the figure safer to act on: the achievable-precision interval
      over 80 labels agreeing three times in four is strictly narrower than over 8.
    - The compression check returns its limitation as a non-empty `stated_limitation` on the
      result, for an empty and a measured population alike.

    Disclosed gap: no code in `aeh.calib` reads M-STATS today, so M-CALIB's half of this row
    ("never reads absence as agreement") holds only because there is no read to get wrong."""

    def agreeing(n):
        """Perfect agreement, and a population agreeing on three pairs in four (so its interval has width)."""
        return ValidationStats([label("C1", b, b, i=i) for i, b in enumerate(["b1", "b2"] * (n // 2))])

    def mostly(n):
        pairs = [("b1", "b1"), ("b2", "b2"), ("b1", "b1"), ("b1", "b2")] * (n // 4)
        return ValidationStats([label("C1", s_, t, i=i) for i, (s_, t) in enumerate(pairs)])

    none = ValidationStats([]).agreement(criterion_id="C1")
    small, large = mostly(8).agreement(criterion_id="C1"), mostly(80).agreement(criterion_id="C1")
    perfect = agreeing(6).agreement(criterion_id="C1")
    assert isinstance(perfect, stats.AgreementFigure) and perfect.n == 6, f"agreeing labels gave {perfect!r}"
    assert isinstance(none, NoValidationData), f"no labels gave {none!r}"
    assert not isinstance(none, stats.AgreementFigure)
    assert isinstance(small, stats.AgreementFigure) and small.n == 8, small
    assert isinstance(large, stats.AgreementFigure) and large.n == 80, large
    assert (large.interval_high - large.interval_low) < (small.interval_high - small.interval_low), (
        f"80 labels are no safer than 8: ({small.interval_low}, {small.interval_high}) vs "
        f"({large.interval_low}, {large.interval_high})")
    for population in (ValidationStats([]), agreeing(6)):
        limitation = population.compression_check().stated_limitation
        assert isinstance(limitation, str) and limitation.strip(), "the compression check returns no limitation"


def test_tc_req_73_an_agreement_figure_never_pools_two_backends():
    """`TC-REQ-73` (`M-CONFORM` → `M-STATS`, CT-STATS-02/04/08): blind labels from two backends
    disagree with the teacher differently: `edge-local` always agrees, `dev-ci` never does. The
    figure asked for `edge-local` must be computed over that backend's labels only, so its `n`
    is that backend's count. A pooled figure would make a conformance comparison meaningless."""
    edge = [label("C1", b, b, backend="edge-local", i=i) for i, b in enumerate(["b1", "b2"] * 4)]
    hosted = [label("C1", b, "b2" if b == "b1" else "b1", backend="dev-ci", i=100 + i)
              for i, b in enumerate(["b1", "b2"] * 4)]
    s = ValidationStats(edge + hosted, backend_profiles=["edge-local", "dev-ci"])
    figure = s.agreement(criterion_id="C1", backend_profile="edge-local")
    assert isinstance(figure, stats.AgreementFigure), f"fixture: {figure!r}"
    assert figure.backend_profile == "edge-local"
    assert figure.n == len(edge), (
        f"the edge-local figure was computed over {figure.n} labels, not the {len(edge)} edge-local "
        f"ones: two backends were pooled into one figure stamped with one backend (CT-STATS-04). "
        f"[When written: agreement() checks the backend is declared, then computes over every "
        f"admissible label and never reads the label's backend; the durable label table has no "
        f"backend_profile column, so stored labels could not be split by backend either.]")


def test_tc_req_79_a_scopeless_figure_cannot_reach_the_console_as_a_scoped_one():
    """`TC-REQ-79` (`M-CONSOLE` → `M-STATS`, CT-STATS-02/03/20, CT-CONSOLE-11):

    - `AgreementFigure` refuses construction without `n` and its scope fields.
    - The absence value M-STATS returns renders as the console's absence sentence, never a number.
    - A figure whose scope fields are all `None` is scopeless. The console's agreement block must
      not render it as a population- and backend-scoped figure; either the type or the renderer
      has to stop it.

    Positive control: the fully scoped figure M-STATS computes renders its kappa and `n`."""
    from aeh.console import NO_NEW_VALIDATION_EVIDENCE, render_agreement_block

    with pytest.raises(TypeError):
        stats.AgreementFigure(kappa=0.8, qwk=0.8, ordinal_alpha=0.8)  # no n, no scope

    absent = ValidationStats([]).agreement(criterion_id="C1")
    absence_text = render_agreement_block(figure=absent)
    assert NO_NEW_VALIDATION_EVIDENCE in absence_text and "kappa" not in absence_text.lower(), absence_text

    scoped_stats = ValidationStats([label("C1", b, b, i=i) for i, b in enumerate(["b1", "b2"] * 3)],
                                   population_scopes=["pop-7B"], backend_profiles=["edge-local"])
    scoped = scoped_stats.agreement(criterion_id="C1", scope="pop-7B", backend_profile="edge-local",
                                    panel_build_ref="pbr:1", scoring_model="holistic")
    scoped_text = render_agreement_block(figure=scoped)
    assert "kappa" in scoped_text.lower() and "n = 6" in scoped_text, f"control: {scoped_text}"

    scopeless = stats.AgreementFigure(kappa=0.8, qwk=0.8, ordinal_alpha=0.8, n=5, scoring_model=None,
                                      population_scope_id=None, backend_profile=None, panel_build_ref=None,
                                      degenerate_band_shape=False)
    text = render_agreement_block(figure=scopeless)
    assert "scoped to" not in text.lower() and "0.8" not in text, (
        f"the console rendered a figure with no population, backend or panel build as a scoped figure: "
        f"{text!r}. [When written: AgreementFigure declares the scope fields without defaults but "
        f"accepts None for each, and render_agreement_block renders any figure with a kappa using "
        f"fixed 'scoped to this population and backend' wording, whatever the figure carries.]")


def test_tc_req_83_the_record_stores_what_promote_computed_without_coercion(tmp_data_dir):
    """`TC-REQ-83` (`M-PKG` → `M-STATS`, CT-STATS-02/03/06, CT-PKG-07, RISK-08):

    - **Counts stay separate.** M-REVIEW records three blind labels and one operational label for
      one criterion, and `promote` reports 3 blind, 1 operational and a figure over `n` = 3.
    - **No coercion on the record.** The durable record row written through
      `aeh.pkg.record_promotion` holds exactly the values `promote` returned.
    - **Absence is not a zero.** A second administration with only operational labels records
      its `agreement_kappa` as NULL, not 0.
    - **The catalog's absence is M-STATS' absence.** For a key with no record, M-PKG's catalog
      returns a value that is neither a number nor a mapping, and is M-STATS' own
      `NoValidationData` type, so a consumer's single type check covers both."""
    from aeh.pkg import PackageCatalog
    from aeh.review import record_label
    from aeh.store import open_store
    from tests.support import broken_stats_fixtures as broken
    from tests.support.orch_run import seed_package

    blind = [broken.Label(label_id=f"b{i}", criterion_id="C-01", band=s, teacher_band=t)
             for i, (s, t) in enumerate([(1, 1), (2, 2), (1, 2)])]
    operational = broken.Label(label_id="op-1", label_type="accept", origin="accept", criterion_id="C-01",
                               saw_system_output=True, band=1, teacher_band=4)
    for item in blind + [operational]:
        record_label(data_dir=tmp_data_dir, label=item)
    update = stats.open_stats(data_dir=tmp_data_dir).promote(cohort_id="coh-83")
    assert (update.blind_count, update.operational_count, update.n) == (3, 1, 3), (
        f"promote mixed operational labels into the blind figure: {update}")

    record_label(data_dir=tmp_data_dir, label=broken.Label(
        label_id="op-2", label_type="accept", origin="accept", criterion_id="C-01", saw_system_output=True))
    empty_update = stats.open_stats(data_dir=tmp_data_dir).promote(cohort_id="coh-83b")

    with sqlite3.connect(tmp_data_dir / "durable.sqlite") as raw:
        raw.row_factory = sqlite3.Row
        records = {r["cohort_id"]: dict(r) for r in raw.execute("SELECT * FROM package_validation")}
    assert set(records) >= {"coh-83", "coh-83b"}, f"record rows: {records}"
    for field in ("blind_count", "operational_count", "cohorts_used", "n", "agreement_kappa"):
        assert records["coh-83"][field] == getattr(update, field), (
            f"the stored record's {field} is {records['coh-83'][field]!r}, not the "
            f"{getattr(update, field)!r} promote computed: the write path coerced a figure")
    assert empty_update.agreement_kappa is None and records["coh-83b"]["agreement_kappa"] is None, (
        f"an administration with no blind labels recorded agreement as "
        f"{records['coh-83b']['agreement_kappa']!r}: an absence was coerced into a figure")

    store = open_store(tmp_data_dir)
    try:
        version = seed_package(store, ({"criterion_id": "C-01", "kind": "open", "scoring_model": "holistic"},))
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        missing = catalog.validation_for(version, "pop-never", "edge-local", "pbr:none")
    finally:
        store.close()
    assert not isinstance(missing, (int, float, dict)) and missing is not None, (
        f"the catalog answered an unrecorded key with a value a figure could be: {missing!r}")
    assert isinstance(missing, NoValidationData), (
        f"the catalog answered an unrecorded key with {type(missing).__module__}.{type(missing).__name__}, "
        f"not M-STATS' absence type, so the catalog invents its own absence value rather than carrying "
        f"M-STATS'. CT-PKG-07 asks only for 'a NoValidationData of a distinct type'; this case's wording "
        f"('without the catalog inventing either') and TC-REQ-61 read it as the same type. This needs a "
        f"design ruling. [When written: aeh.pkg defines a second NoValidationData class (pkg.py ~656), "
        f"the TC-REQ-61 finding on #341.]")
