"""`CT-STATS-02`, `-04`, `-13`, `-14` — what a figure carries, and what may never be merged.

Test plan §6.11.16, `TC-STATS-C02`, `-C04`, `-C13`, `-C14`. The four clauses are one idea in four
places: a statistic is a claim about *one* criterion, *one* population, *one* backend and *one*
panel build, and every mechanism here exists to make the wider claim unrepresentable rather than
merely discouraged.

§6.11.16 names the technique: *"type-level enforcement over convention — `CT-STATS-02` puts scope
inside the figure's own value"* — so `TC-STATS-C02` asserts the **construction refuses** rather
than inspecting a figure somebody remembered to fill in. A call-site sample passes for the next
caller who forgets; a type does not have a next caller.

The prohibitions in `-04` and `-14` are asserted **over the surface**, which is what the plan asks
for: *"asserted over the module's surface, not by observing outputs"*. A merged figure that no
function offers cannot be produced by a consumer who wants one.
"""

from __future__ import annotations

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab
from tests.support.impl import PKG_MODULE, STATS_MODULE, require

pytestmark = pytest.mark.contract


def _figure(stats, **overrides):
    """An `AgreementFigure` from a populated module, with the scope the caller asked for."""
    call = dict(vocab.EMPTY_DATA_CALL["agreement"])
    call.update(overrides)
    return stats.agreement(**call)


# --- CT-STATS-02 — the figure carries its own scope ------------------------------------------


@pytest.mark.writtenahead
def test_tc_stats_c02_the_figure_declares_exactly_the_fields_the_design_names():
    """Field-set **equality** against §3.16's dataclass, not containment.

    Containment would pass a figure that had grown a `percent_agreement` beside its κ — which is
    the one addition `CT-STATS-02`'s second half exists to govern, and which today has no surface
    to be governed on (see `test_ct_stats_vocabulary.py`, where that gap is asserted as a finding).
    """
    import dataclasses

    AgreementFigure = require(STATS_MODULE, "AgreementFigure", issue="#115")
    declared = tuple(field.name for field in dataclasses.fields(AgreementFigure))

    assert declared == vocab.AGREEMENT_FIGURE_FIELDS, (
        f"AgreementFigure declares {declared}; §3.16 declares "
        f"{vocab.AGREEMENT_FIGURE_FIELDS}"
    )


@pytest.mark.writtenahead
@pytest.mark.parametrize("omitted", vocab.REQUIRED_FIGURE_FIELDS)
def test_tc_stats_c02_a_figure_without_its_scope_or_its_n_cannot_be_constructed(omitted):
    """*"No figure is representable without them; the return type enforces it rather than the call
    sites"* — asserted by **construction refusal**, one row per required field.

    One row each because the plausible defect is a single field acquiring a default. A figure whose
    `panel_build_ref` defaults to `""` is constructible everywhere, renders everywhere, and is a
    claim about a panel nobody can identify — and a single test omitting all five at once would
    pass as soon as any one of them was still required.

    The three statistics are deliberately not swept: §3.16 declares `qwk` and `ordinal_alpha` as
    `| None`, so demanding them would fail a compliant figure carrying κ alone.
    """
    AgreementFigure = require(STATS_MODULE, "AgreementFigure", issue="#115")

    complete = {
        "kappa": 0.71,
        "qwk": None,
        "ordinal_alpha": None,
        "n": 142,
        "scoring_model": "atomic",
        "population_scope_id": "y9-2026-spring",
        "backend_profile": "edge-local-q4",
        "panel_build_ref": "9f2a1c",
    }
    assert AgreementFigure(**complete), "the complete construction failed, so the sweep below is vacuous"

    del complete[omitted]
    with pytest.raises(TypeError):
        AgreementFigure(**complete)


@pytest.mark.writtenahead
def test_tc_stats_c02_every_emitted_figure_is_chance_corrected():
    """*"Every figure is chance-corrected"* (`FR-STATS-02`), asserted on what the module emits.

    At least one of κ, QWK or ordinal α carries a value — a figure with all three `None` is a
    percent agreement wearing the dataclass, and it renders identically.
    """
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    stats = build_stats(labels=[broken.ADMISSIBLE_LABEL] * 40)

    figure = _figure(stats)
    corrected = [
        name
        for name in ("kappa", "qwk", "ordinal_alpha")
        if getattr(figure, name) is not None
    ]

    assert corrected, (
        "the figure carries no chance-corrected statistic at all — κ, QWK and ordinal α are all "
        "None, which is a raw percent agreement in the shape of an AgreementFigure (FR-STATS-02)"
    )


# --- CT-STATS-04 — keying, and the two prohibitions ------------------------------------------


@pytest.mark.writtenahead
def test_tc_stats_c04_every_emitted_statistic_echoes_the_scope_it_was_asked_for():
    """*"Every emitted statistic is keyed by population scope, backend profile, panel build ref,
    and scoring model."*

    The assertion is that the four fields carry the values **this test** asked for, not merely
    that they are non-empty. A module that stamps every figure with its own defaults satisfies a
    presence check and hands a consumer a figure describing a different population — and since
    `CT-PKG-17` says population scopes are free text per installation, nobody downstream can tell.
    """
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    stats = build_stats(labels=[broken.ADMISSIBLE_LABEL] * 40)

    asked = {
        "scope": "y10-2026-autumn",
        "backend_profile": "hosted-openrouter",
        "panel_build_ref": "aa11bb",
        "scoring_model": "holistic",
    }
    figure = _figure(stats, **asked)

    assert figure.population_scope_id == asked["scope"]
    assert figure.backend_profile == asked["backend_profile"]
    assert figure.panel_build_ref == asked["panel_build_ref"]
    assert figure.scoring_model == asked["scoring_model"], (
        "the figure reports a scope other than the one requested, so a consumer holding it is "
        "reading a claim about a different population, backend or panel (CT-STATS-04)"
    )


@pytest.mark.writtenahead
def test_tc_stats_c04_atomic_and_holistic_are_reported_separately_and_no_function_merges_them():
    """The first prohibition, *"asserted over the module's surface, not by observing outputs"*.

    Two halves. The behaviour: asking for `atomic` and asking for `holistic` over the same cohort
    produce two figures that are not the same object and not the same value by construction. The
    surface: no function offers the merge, so a consumer who wants one cannot get one — which is
    the durable half, since judge performance does not transfer across task types (HLD `R51`) and
    a merged figure is a claim nobody is entitled to make.
    """
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    stats = build_stats(
        labels=[broken.ADMISSIBLE_LABEL] * 20
        + [broken.Label(label_id=f"h-{i}", criterion_id="C-09", band=2) for i in range(20)],
        scoring_models={"C-01": "atomic", "C-09": "holistic"},
    )

    atomic = _figure(stats, criterion_id="C-01", scoring_model="atomic")
    holistic = _figure(stats, criterion_id="C-09", scoring_model="holistic")

    assert atomic.scoring_model == "atomic" and holistic.scoring_model == "holistic"
    assert {atomic.scoring_model, holistic.scoring_model} == {"atomic", "holistic"}, (
        "one call answered with the other's scoring model, so the two are not being kept apart"
    )

    merging = vocab.merging_surface([name for name in dir(stats) if not name.startswith("_")])
    assert merging == [], (
        f"{merging} offer a figure spanning something CT-STATS-04 keeps apart. The prohibition is "
        "on the function: a merge nobody can ask for is a claim nobody can make."
    )


@pytest.mark.writtenahead
@pytest.mark.parametrize("dimension", vocab.NON_AGGREGABLE_DIMENSIONS)
def test_tc_stats_c04_an_aggregate_spanning_a_forbidden_dimension_is_refused(dimension):
    """The second prohibition — *"Sweep an attempt to aggregate across each of the three and
    assert refusal."*

    One row per dimension, so a regression names which of the three stopped being refused.

    All three are keyed on **#118**, the story that delivers `aggregate`, even though the
    assignment-type dimension is `FR-STATS-17`'s (MVVP step 4, #116) and the other two are
    `FR-STATS-04`'s (#115). The refusal lives on `aggregate` in every case, and a row cannot run
    until the function it calls exists — keying the assignment-type row on #116 would report it
    runnable while `aggregate` was still absent, which is the same mistake in the other direction.

    A refusal, not an empty result. Returning `NoValidationData` would be wrong in a way that
    matters: absence of data and a request nobody is entitled to make are different answers, and a
    consumer that reads the first will try a different key and move on.

    `AttributeError` is excluded explicitly. A module with no `aggregate` at all raises one, and
    an oracle written as "it raises" would report that as a refusal — passing a module that
    refuses nothing because it offers nothing.
    """
    require(STATS_MODULE, "aggregate", issue="#118")  # the member this story delivers
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    stats = build_stats(labels=[broken.ADMISSIBLE_LABEL] * 40)

    assert stats.aggregate(), "the unspanned aggregate does not work, so the refusal below is vacuous"

    with pytest.raises(Exception) as raised:  # noqa: PT011 - the refusal type is the module's
        stats.aggregate(across=dimension)

    assert not isinstance(raised.value, AttributeError), (
        f"aggregate(across={dimension!r}) raised AttributeError, which is what a module with no "
        "aggregate at all raises — that is not a refusal, it is an absence"
    )


# --- CT-STATS-13 — the weakest criterion travels with the aggregate --------------------------


@pytest.mark.writtenahead
def test_tc_stats_c13_an_aggregate_cannot_be_obtained_without_its_weakest_criterion():
    """*"Asserted structurally so an aggregate cannot be obtained without it, rather than by
    checking that callers ask for it."*

    Two assertions and the second is the structural one:

    * the aggregate value carries the weakest criterion **per population**, keyed by population
      rather than as a single overall weakest — a package administered to two populations has two
      weakest criteria and one of them is invisible in a single figure;
    * no function on the surface returns a bare aggregate. A caller who can get the headline alone
      will, and `CT-PKG-18` says the catalog offers no ranking query to recover the weakest one
      afterwards.
    """
    require(STATS_MODULE, "aggregate", issue="#118")  # the member this story delivers
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    stats = build_stats(
        labels=[broken.ADMISSIBLE_LABEL] * 40,
        population_scopes=["y9-2026-spring", "y10-2026-autumn"],
    )

    aggregate = stats.aggregate()

    assert aggregate.weakest_per_population, (
        "the aggregate carries no weakest criterion. FR-STATS-13: a package advertising only its "
        "overall number repeats the §2.1 error in portable form (R23)."
    )
    assert set(aggregate.weakest_per_population) == {"y9-2026-spring", "y10-2026-autumn"}, (
        "the weakest criterion is reported once rather than per population, so one population's "
        "weakest criterion is not represented anywhere in the value"
    )

    bare = [
        name
        for name in dir(stats)
        if not name.startswith("_") and name in {"headline", "overall", "headline_agreement"}
    ]
    assert bare == [], f"{bare} return an aggregate with no weakest criterion attached"


@pytest.mark.writtenahead
def test_tc_stats_c13_an_exported_package_carries_the_weakest_figure_beside_the_headline():
    """The portability half, at **rung 3**: *"assert an **exported** package carries the weakest
    figure alongside the headline"*.

    `M-PKG`'s export, so keyed on **#31** — the story that owns single-file export — rather than on
    #118. The clause's point is that the §2.1 error becomes portable here: a package that travels
    to another school advertising one number is the failure `R23` names, and the receiving school
    has no way to recover what it did not send.
    """
    export_package = require(PKG_MODULE, "export_package", issue="#31")
    exported = export_package(package_version="pkg-v1")
    validation = exported["validation"] if isinstance(exported, dict) else exported.validation

    assert validation.get("weakest_per_population"), (
        "the exported package advertises an aggregate with no weakest criterion beside it "
        "(CT-STATS-13, R23) — the §2.1 error, in the form that travels"
    )


# --- CT-STATS-14 — narrative quality is a separate report ------------------------------------


@pytest.mark.writtenahead
def test_tc_stats_c14_narrative_quality_is_reported_separately_from_agreement():
    """The three metrics, on a sample, in their own report.

    *"A system with κ = 0.8 and ungrounded feedback is failing at its most valuable job"* — so the
    assertion is that the narrative report exists, carries all three metrics, and is **not** a
    field of the agreement figure. Folding citation validity into the figure would make it a
    component of a number a consumer reads as agreement.
    """
    require(STATS_MODULE, "narrative_quality", issue="#118")  # the member this story delivers
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    stats = build_stats(labels=[broken.ADMISSIBLE_LABEL] * 40)

    report = stats.narrative_quality(cohort_id="coh-1")
    for metric in vocab.NARRATIVE_QUALITY_METRICS:
        assert hasattr(report, metric), (
            f"the narrative-quality report has no {metric} (FR-STATS-12)"
        )

    figure = _figure(stats)
    leaked = [m for m in vocab.NARRATIVE_QUALITY_METRICS if hasattr(figure, m)]
    assert leaked == [], (
        f"{leaked} appear on the agreement figure. CT-STATS-14 reports narrative quality "
        "separately from criterion-score agreement, and a metric inside the figure is a component "
        "of a number consumers read as agreement."
    )


@pytest.mark.writtenahead
def test_tc_stats_c14_no_function_offers_a_combined_quality_figure():
    """*"Assert the absence of a combining function over the surface."*

    The clause's reason is what makes the surface assertion the right one: a blended headline is
    exactly what hides κ = 0.8 with ungrounded feedback, and nobody blends deliberately — somebody
    adds `combined_quality_score` because a screen needed one number.
    """
    require(STATS_MODULE, "narrative_quality", issue="#118")  # the member this story delivers
    stats = require(STATS_MODULE, issue="#115")
    exposed = [name for name in dir(stats) if not name.startswith("_")]

    combining = vocab.merging_surface(exposed)
    assert combining == [], (
        f"{combining} offer a combined figure. A system with κ = 0.8 and ungrounded feedback is "
        "failing at its most valuable job, and a blended headline hides exactly that."
    )
