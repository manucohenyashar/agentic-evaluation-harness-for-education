"""`TS-81` (issue #154) — `Requires` pairwise integration into **`M-STATS`**: every consumer's
assumption about validation statistics, override history and the absence value, checked against
the real `aeh.stats` (rung 3).

| Case | Consumer | Assumption checked here |
|---|---|---|
| TC-REQ-41 | `M-AGG` | M-STATS' override history, fed to escalation, routes no data differently from a genuine zero |
| TC-REQ-57 | `M-REVIEW` | the same history, fed to ranking, ranks no data differently from a genuine zero |
| TC-REQ-68 | `M-CALIB` | "no evidence" and "no disagreement" are different values, and the compression check states its limitation |
| TC-REQ-73 | `M-CONFORM` | an agreement figure is scoped to one backend and never pools two |
| TC-REQ-79 | `M-CONSOLE` | a figure cannot exist without `n` and scope, and the console renders the absence type as absence |
| TC-REQ-83 | `M-PKG` | the catalog stores what `promote` computed, with no coercion, and blind counts stay apart from operational ones |

Labels are built in `M-REVIEW`'s label shape (`label_type`, `saw_system_output`,
`evaluation_mode`, both bands) so M-STATS' own admissibility filter applies to them.

Markers: `contract` and `integration` (§4.7).
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

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


def test_tc_req_41_escalation_routes_no_override_data_differently_from_a_zero(tmp_path):
    """`TC-REQ-41` (`M-AGG` → `M-STATS`, CT-STATS-09): M-STATS returns `NoValidationData` for a
    never-reviewed criterion and a zero-rate history for one reviewed without overrides. Handed to
    M-AGG's escalation decision as the history for the same score, the two must not decide
    identically. A criterion nobody has looked at carries unmeasured risk, and reading it as a
    zero makes it the safest."""
    from aeh.agg import aggregate, should_escalate
    from tests.support.agg_vocabulary import (
        agg_config,
        band,
        criterion,
        expected_distribution,
        panel,
        signals,
    )

    never, zero = _histories()
    assert isinstance(never, NoValidationData), f"fixture: {never!r}"
    assert getattr(zero, "override_rate", None) == 0.0, f"fixture: {zero!r}"
    crit = criterion([band("a", 0, 0.0), band("b", 1, 1.0), band("c", 2, 2.0), band("d", 3, 3.0)],
                     scoring_model="holistic", criterion_id="C1")
    score = aggregate(panel(("b", 1), ("c", 2), ("c", 2)), crit, signals(), config=agg_config())

    def decide(history):
        decision = should_escalate(score=score, criterion=crit, history=history,
                                   baseline=expected_distribution(), config=agg_config())
        return (decision.escalate, tuple(getattr(decision, "reasons", ()) or ()))

    control = decide(SimpleNamespace(override_rate=None))
    assert control != decide(zero), (
        f"control: M-AGG's own no-data channel (override_rate=None) decides like a zero: {control}")
    assert decide(never) != decide(zero), (
        f"escalation reads M-STATS' no-data history exactly like a zero override rate: {decide(never)}. "
        f"[When written: NoValidationData carries no override_rate, so M-AGG's history read finds the "
        f"field absent and skips it; the no-data weight applies only to override_rate=None, and no src "
        f"code maps M-STATS' absence value into that channel.]")


def test_tc_req_57_review_ranking_distinguishes_no_override_data_from_a_zero():
    """`TC-REQ-57` (`M-REVIEW` → `M-STATS`, CT-STATS-09): the same two histories feed M-REVIEW's
    `historical_override_rate` for two otherwise identical queue rows. The rows' expected values
    must differ, and building the queue must not fail on the absence value M-STATS hands over."""
    from aeh.review import build_review
    from tests.support import broken_review_fixtures as broken

    never, zero = _histories()
    base = broken.flagged_population(1, criteria=1)[0]
    rows = [dataclasses.replace(base, score_id="score-never", criterion_id="C-NEVER",
                                historical_override_rate=never),
            dataclasses.replace(base, score_id="score-zero", criterion_id="C-ZERO",
                                historical_override_rate=zero.override_rate)]
    control_rows = [dataclasses.replace(rows[0], historical_override_rate=None), rows[1]]
    control = build_review(scores=control_rows).build_queue(run_id="run-1", budget_minutes=600)
    control_values = {item.score_id: item.expected_value for item in control.shown}
    assert control_values["score-never"] != control_values["score-zero"], (
        f"control: M-REVIEW's own no-data channel (None) ranks like a zero: {control_values}")
    problems = []
    try:
        queue = build_review(scores=rows).build_queue(run_id="run-1", budget_minutes=600)
        values = {item.score_id: item.expected_value for item in queue.shown}
        if values.get("score-never") == values.get("score-zero"):
            problems.append(f"ranking reads no data as a zero: {values}")
    except Exception as error:
        problems.append(
            f"M-REVIEW cannot rank on M-STATS' absence value: {type(error).__name__}: {error}. [When "
            f"written: review.py reads historical_override_rate as a float or None; no src code maps "
            f"NoValidationData into None, so the value M-STATS returns for a never-reviewed "
            f"criterion does not reach the ranking's no-data default.]")
    assert not problems, "\n".join(problems)


def test_tc_req_68_no_evidence_and_no_disagreement_are_different_values():
    """`TC-REQ-68` (`M-CALIB` → `M-STATS`, CT-STATS-01/03/10): over no blind labels, `agreement`
    returns `NoValidationData`. Over perfectly agreeing blind labels, it returns an `AgreementFigure`
    with its `n`. The two are different types, so a consumer cannot read absence as agreement by
    comparing numbers. The compression check carries a statement of its own limitation.

    Disclosed gap: no code in `aeh.calib` reads M-STATS today, so M-CALIB's side of this row
    ("never reads absence as agreement") holds only because there is no read to get wrong."""
    agreeing = ValidationStats([label("C1", "b1", "b1", i=i) for i in range(6)]
                               + [label("C1", "b2", "b2", i=10 + i) for i in range(6)])
    empty = ValidationStats([])
    none = empty.agreement(criterion_id="C1")
    full = agreeing.agreement(criterion_id="C1")
    assert isinstance(none, NoValidationData), f"no labels gave {none!r}"
    assert isinstance(full, stats.AgreementFigure) and full.n == 12, f"agreeing labels gave {full!r}"
    import inspect

    compression_doc = inspect.getdoc(stats.compression_check) or ""
    assert "limit" in compression_doc.lower(), "the compression check states no limitation"


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


def test_tc_req_79_a_figure_cannot_exist_without_its_scope_and_the_console_renders_absence(tmp_data_dir):
    """`TC-REQ-79` (`M-CONSOLE` → `M-STATS`, CT-STATS-02/03/20, CT-CONSOLE-11): `AgreementFigure`
    refuses construction without `n` and its scope fields, so a scopeless figure cannot reach the
    console. The console renders its S1 absence sentence for a package with no validation record,
    and never a number in that position."""
    from aeh.console import NO_VALIDATION_FOR_POPULATION, SCREENS, build_console
    from aeh.store import open_store
    from tests.support.orch_run import seed_run

    with pytest.raises(TypeError):
        stats.AgreementFigure(kappa=0.8, qwk=0.8, ordinal_alpha=0.8)  # no n, no scope
    required = {f.name for f in dataclasses.fields(stats.AgreementFigure)
                if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING}
    assert {"n", "population_scope_id", "backend_profile", "panel_build_ref"} <= required, required

    store = open_store(tmp_data_dir)
    try:
        seed_run(store, submissions=("S001",), criteria=(
            {"criterion_id": "C01", "kind": "open", "scoring_model": "holistic"},))
        page = build_console(store=store).render(SCREENS["S1"]).html
    finally:
        store.close()
    assert NO_VALIDATION_FOR_POPULATION in page, "S1 does not render the absence sentence"
    assert "κ" not in page and "kappa" not in page.lower(), "S1 renders a figure where there is none"


def test_tc_req_83_the_catalog_stores_what_promote_computed_without_coercion(tmp_data_dir):
    """`TC-REQ-83` (`M-PKG` → `M-STATS`, CT-STATS-02/03/06, CT-PKG-07): M-REVIEW records three blind
    labels and one operational label for one criterion, and M-STATS' `promote` records the
    administration. The counters stay separate (3 blind, 1 operational), the figure's `n` is the
    blind count and not 4, and the durable record row written through `aeh.pkg.record_promotion`
    holds exactly the values `promote` returned. For a key with no record, M-PKG's catalog returns
    `NoValidationData`, a type distinct from any figure, never a zero."""
    import sqlite3

    import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.orch  # noqa: E401,F401
    import aeh.pkg, aeh.review, aeh.synth  # noqa: E401,F401
    from aeh.pkg import PackageCatalog
    from aeh.review import record_label
    from aeh.store import open_store
    from tests.support import broken_stats_fixtures as broken

    blind = [broken.Label(label_id=f"b{i}", criterion_id="C-01", band=s, teacher_band=t)
             for i, (s, t) in enumerate([(1, 1), (2, 2), (1, 2)])]
    operational = broken.Label(label_id="op-1", label_type="accept", origin="accept", criterion_id="C-01",
                               saw_system_output=True, band=1, teacher_band=4)
    for item in blind + [operational]:
        record_label(data_dir=tmp_data_dir, label=item)
    update = stats.open_stats(data_dir=tmp_data_dir).promote(cohort_id="coh-83")
    assert (update.blind_count, update.operational_count, update.n) == (3, 1, 3), (
        f"promote mixed operational labels into the blind figure: {update}")

    with sqlite3.connect(tmp_data_dir / "durable.sqlite") as raw:
        raw.row_factory = sqlite3.Row
        records = [dict(r) for r in raw.execute("SELECT * FROM package_validation WHERE cohort_id = 'coh-83'")]
    assert len(records) == 1, f"expected one record row for the administration, got {records}"
    record = records[0]
    for field in ("blind_count", "operational_count", "cohorts_used", "n", "agreement_kappa"):
        assert record[field] == getattr(update, field), (
            f"the stored record's {field} is {record[field]!r}, not the {getattr(update, field)!r} "
            f"promote computed: the write path coerced a figure")

    store = open_store(tmp_data_dir)
    try:
        from tests.support.orch_run import seed_package

        version = seed_package(store, ({"criterion_id": "C-01", "kind": "open", "scoring_model": "holistic"},))
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        missing = catalog.validation_for(version, "pop-never", "edge-local", "pbr:none")
    finally:
        store.close()
    assert isinstance(missing, NoValidationData), (
        f"the catalog answered an unrecorded key with {type(missing).__module__}.{type(missing).__name__}, "
        f"not M-STATS' absence type: M-PKG invents its own absence value instead of carrying M-STATS'. "
        f"[When written: aeh.pkg defines a second NoValidationData class, the TC-REQ-61 finding on #341; "
        f"a consumer's isinstance check against aeh.stats.NoValidationData misses the catalog's.]")
    assert not isinstance(missing, (int, float, dict)), "the absence arrived as a value a figure could be"
