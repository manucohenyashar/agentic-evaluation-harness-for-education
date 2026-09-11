"""`TC-STATS-24` — the figure invariants hold over generated label sets.

Test plan §5.16 (row form: Property / rung 0), issue #119 (TS-42). Traces to
`FR-STATS-02`. Where `TC-STATS-04` pins the exact hand-computed references on
chosen tables, this property generalizes the *shape* invariants over every
generated contingency table (0–30 blind judged pairs on 4 bands, declared band
count 2 or 4):

- **every returned value is structured, never a bare float**: `agreement`
  returns an `AgreementFigure` or the `NoValidationData` absence value;
  `operational_signal` returns an `OperationalSignal`; `aggregate` returns a
  `ValidationAggregate`. A consumer can never be handed a number wearing no
  scope.
- **every figure carries n and full scope**: the figure's `n` is a
  non-negative count and its `population_scope_id` / `backend_profile` /
  `panel_build_ref` are exactly the call's — a figure is a claim about a
  declared population, and it says which.
- **κ and α stay in the domain or refuse**: each is in `[-1, 1]` or `None`
  (unanimity's 0/0), and a population too small to measure is the absence
  value with a declared reason — never a plausible-looking number.

Isolation: rung 0 (`build_stats`, pure). Interface: the landed
`build_stats`/`agreement`/`operational_signal`/`aggregate` surface (#115) and
`stats_vocabulary`'s declared groups.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab
from tests.support.impl import STATS_MODULE, require

pytestmark = pytest.mark.property

_PAIRS = st.tuples(st.integers(1, 4), st.integers(1, 4))
_TABLES = st.lists(_PAIRS, min_size=0, max_size=30)
_DECLARED_BAND_COUNTS = st.sampled_from([2, 4])


def _stats(table, declared_band_count):
    """A rung-0 instance over the generated table, blind judged pairs on C-01."""
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    labels = [
        broken.Label(
            label_id=f"p-{index}",
            label_type="blind",
            origin="blind_sample",
            criterion_id="C-01",
            band=system,
            teacher_band=teacher,
        )
        for index, (system, teacher) in enumerate(table)
    ]
    return build_stats(
        labels,
        scoring_models={"C-01": "atomic"},
        band_counts={"C-01": declared_band_count},
    )


@given(table=_TABLES, declared=_DECLARED_BAND_COUNTS)
def test_tc_stats_24_every_returned_value_is_structured_and_carries_n_and_scope(
    table, declared
):
    """`TC-STATS-24` (`FR-STATS-02`, property / rung 0, P0) — no call returns a
    bare float, the figure carries n and the call's full scope, and the other
    members return structured values too."""
    agreement_cls = require(STATS_MODULE, "AgreementFigure", issue="#115")
    no_validation = require(STATS_MODULE, "NoValidationData", issue="#115")
    aggregate_cls = require(STATS_MODULE, "ValidationAggregate", issue="#115")
    stats = _stats(table, declared)

    figure = stats.agreement(**vocab.EMPTY_DATA_CALL["agreement"])
    assert isinstance(figure, (agreement_cls, no_validation)), (
        f"agreement over a {len(table)}-label table returned {figure!r} "
        f"({type(figure).__name__}); a figure is a structured value, never a "
        "bare float (FR-STATS-02)"
    )

    if isinstance(figure, agreement_cls):
        call = vocab.EMPTY_DATA_CALL["agreement"]
        assert isinstance(figure.n, int) and figure.n >= 0, (
            f"figure.n = {figure.n!r} over a {len(table)}-label table; every "
            "figure carries the count it was computed over"
        )
        assert figure.population_scope_id == call["scope"], (
            "the figure's population scope is the call's, not dropped or "
            "rewritten (a figure is a claim about a declared population)"
        )
        assert figure.backend_profile == call["backend_profile"], (
            "the figure carries the call's backend profile in full scope"
        )
        assert figure.panel_build_ref == call["panel_build_ref"], (
            "the figure carries the call's panel build ref in full scope"
        )

    signal = stats.operational_signal()
    assert not isinstance(signal, float), (
        f"operational_signal returned a bare {signal!r}; the signal is a "
        "structured value carrying n, weights and the weighted flag (FR-STATS-14)"
    )
    assert isinstance(signal.n, int) and signal.n >= 0, (
        f"signal.n = {signal.n!r} over a {len(table)}-label table"
    )
    assert signal.signal is None or 0.0 <= signal.signal <= 1.0, (
        f"signal.signal = {signal.signal!r} over a {len(table)}-label table; "
        "a weighted mean of agreement indicators stays in [0, 1]"
    )

    agg = stats.aggregate()
    assert isinstance(agg, aggregate_cls), (
        f"aggregate returned {type(agg).__name__}; the per-population value is "
        "structured, never a bare float (FR-STATS-02)"
    )


@given(table=_TABLES, declared=_DECLARED_BAND_COUNTS)
def test_tc_stats_24_kappa_and_alpha_stay_in_the_domain_or_refuse(table, declared):
    """`TC-STATS-24` (`FR-STATS-02`, property / rung 0, P0) — over every
    generated table, κ and α are in `[-1, 1]` or `None` (unanimity's 0/0), and
    a population too small to measure is the absence value with a declared
    reason, never a number."""
    no_validation = require(STATS_MODULE, "NoValidationData", issue="#115")
    agreement_cls = require(STATS_MODULE, "AgreementFigure", issue="#115")
    stats = _stats(table, declared)

    figure = stats.agreement(**vocab.EMPTY_DATA_CALL["agreement"])
    if isinstance(figure, no_validation):
        assert figure.reason in vocab.NO_VALIDATION_DATA_REASONS, (
            f"the absence carries reason {figure.reason!r}; it is one of the "
            "declared literals, not a message (FR-STATS-04)"
        )
        return

    assert isinstance(figure, agreement_cls)
    assert figure.kappa is None or -1.0 <= figure.kappa <= 1.0, (
        f"table={table} declared={declared}: kappa = {figure.kappa!r} — a "
        "chance-corrected coefficient stays in [-1, 1] or is None (FR-STATS-02)"
    )
    assert figure.qwk is None or -1.0 <= figure.qwk <= 1.0, (
        f"table={table} declared={declared}: qwk = {figure.qwk!r} — a weighted "
        "coefficient stays in [-1, 1] or is None (FR-STATS-02)"
    )
    assert figure.ordinal_alpha is None or -1.0 <= figure.ordinal_alpha <= 1.0, (
        f"table={table} declared={declared}: ordinal_alpha = "
        f"{figure.ordinal_alpha!r} — a distance coefficient stays in [-1, 1] or "
        "is None (FR-STATS-02)"
    )
