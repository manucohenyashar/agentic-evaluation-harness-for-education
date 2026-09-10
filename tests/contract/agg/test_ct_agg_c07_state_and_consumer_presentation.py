"""`TC-AGG-C07` — the four score states, and the consumers that must not merge them (§6.11.12).

`CT-AGG-07`: "`criterion_score.state` ∈ {`final`, `provisional_unreviewed`,
`ungradeable_by_panel`, `unresolved_selection`}; `ungradeable_by_panel` is set for
criteria whose `M-ORCH` circuit breaker tripped, and consumers must surface it rather
than treating it as an ordinary provisional."

The state-per-cause mapping's four cells are the shipped sibling
`tests/unit/agg/test_score_states.py` (`TC-AGG-14`, #93). This case carries what that
sweep does not:

- **the closed-set direction**: no entry of the aggregation surface — panels, the
  uncited mark, every adverse cap, the fallback, the breaker, the holistic model, the
  deterministic pass-through — yields a state outside the four. A fifth state, or a
  cause that quietly reuses another's, is the enum eroding;
- **the consumer presentation differential** (the case's rung-3 limb, writtenahead on
  each unlanded consumer in turn — M-GRADE #101's `apply_policy` landed first, then
  M-REVIEW #108's queue, and the console module at the #122/#126 landing; all three
  params run unmarked now): the breaker path
  and the fallback path route **`provisional` identically** — `routing` carries no
  distinction; only `state` does. So the differential is exact: the same figures,
  written twice, differing in the state column alone, presented to a consumer whose
  two presentations must differ. A consumer whose presentation of the breaker-refused
  row equals its presentation of the ordinary provisional row has merged them — a
  panel that refused to grade renders as a panel awaiting review, which is exactly
  what `CT-ORCH-16` promised the breaker would not do.

The consumer call shapes are the declared assumptions, reconciled at each landing (the
`test_random_arm.py` precedent): `aeh.grade:apply_policy(scores, policy)` consumes the
score values with the package's default policy (§3.14); `aeh.review:build_review(store)`
holds the queue; `aeh.console:build_console(store)` renders a submission's scores.

Isolation: rung 0 for the state sweep; rung 2 (real SQLite, seeded cohort) for the
rows the consumer limb presents; the socket guard is autouse.
"""

from __future__ import annotations

from dataclasses import fields, replace

import pytest

from aeh.pkg import default_grade_policy
from aeh.store import open_store
from tests.support.agg_vocabulary import (
    band,
    criterion,
    panel,
    signals,
    verdict,
    agg_config,
)
from tests.support.impl import (
    AGG_MODULE,
    CONSOLE_MODULE,
    GRADE_MODULE,
    REVIEW_MODULE,
    require,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort

pytestmark = [pytest.mark.contract]

_FOUR_BAND = criterion([band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0),
                        band("B3", 3, 6.0)])
_HOLISTIC = criterion(_FOUR_BAND.bands, scoring_model="holistic")
_UNANIMOUS_TOP = panel(("B3", 3), ("B3", 3), ("B3", 3))
_TWO_LEFT = panel(("B1", 1), ("B3", 3))

#: The four states, verbatim from det v9 (CT-AGG-07's enumeration).
STATE_SET = ("final", "provisional_unreviewed", "ungradeable_by_panel",
             "unresolved_selection")

_COHORT = ORCH_COHORT_ID
_SUBMISSION = "SYN-C07"
_CRITERION = "C-STATE"

_INSERT = (
    "INSERT INTO criterion_score (submission_id, criterion_id, band, points, "
    "judge_count, agreement, state, routing) "
    "VALUES (:sid, :cid, :band, :points, :jc, :ag, :state, :routing)"
)


def test_tc_agg_c07_the_state_vocabulary_is_closed_and_each_state_is_reached():
    """`TC-AGG-C07` (`CT-AGG-07`, `FR-AGG-11`, unit / rung 0, domain sweep, P0) —
    each of the four states is reached by its declared cause, and no entry of the
    swept surface — including the cells a regression would most plausibly reroute
    through an existing state — yields a fifth value. The cause→state cells
    themselves are TC-AGG-14's; the closed set over the wider surface is this
    case's."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")

    by_cause = {
        "a judged panel": aggregate(_UNANIMOUS_TOP, _FOUR_BAND, signals(),
                                    config=agg_config()),
        "the two-verdict discard": aggregate(_TWO_LEFT, _FOUR_BAND, signals(),
                                             fallback=True, config=agg_config()),
        "the tripped breaker": aggregate(_UNANIMOUS_TOP, _FOUR_BAND, signals(),
                                         breaker_tripped=True, config=agg_config()),
        "the unresolved selection": aggregate(
            [], _FOUR_BAND, signals(),
            deterministic_score={"submission_id": _SUBMISSION,
                                 "criterion_id": _CRITERION,
                                 "band": "unresolved", "points": None,
                                 "judge_count": 0, "agreement": None,
                                 "state": "unresolved_selection",
                                 "routing": "triage"},
            config=agg_config(),
        ),
    }
    expected = {
        "a judged panel": "final",
        "the two-verdict discard": "provisional_unreviewed",
        "the tripped breaker": "ungradeable_by_panel",
        "the unresolved selection": "unresolved_selection",
    }
    for cause, score in by_cause.items():
        assert score.state == expected[cause], (
            f"{cause} recorded state {score.state!r}, expected "
            f"{expected[cause]!r} — the state-per-cause mapping (FR-AGG-11)"
        )

    # The closed set over the wider surface: every routing-relevant entry of the
    # module lands in the four, and no fifth state is reachable.
    surface = [
        by_cause["a judged panel"],
        aggregate([verdict("B3", 3), verdict("B3", 3), verdict("B3", 3, cited=False)],
                  _FOUR_BAND, signals(), config=agg_config()),
        aggregate(_UNANIMOUS_TOP, _FOUR_BAND, signals(spans_verified=False),
                  config=agg_config()),
        by_cause["the two-verdict discard"],
        by_cause["the tripped breaker"],
        aggregate(_UNANIMOUS_TOP, _HOLISTIC, signals(), config=agg_config()),
        by_cause["the unresolved selection"],
    ]
    for score in surface:
        assert score.state in STATE_SET, (
            f"an aggregation entry recorded state {score.state!r} — outside the "
            "closed four-value set (CT-AGG-07, det v9's CHECK vocabulary)"
        )


def _paired_scores(aggregate):
    """The differential's two rows: the SAME panel figures, written by the fallback
    path and by the breaker path — identical on every field but `state` (both route
    `provisional`; `routing` carries no distinction). The fixture sanity gate makes
    the differential honest: if the two rows differed in anything else, a consumer's
    differing presentations would prove nothing."""
    provisional = aggregate(_TWO_LEFT, _FOUR_BAND, signals(), fallback=True,
                            config=agg_config())
    ungradeable = replace(provisional, state="ungradeable_by_panel")
    assert provisional.state == "provisional_unreviewed", (
        "fixture bug: the fallback discard is not the ordinary provisional row"
    )
    differing = [
        field.name for field in fields(provisional)
        if getattr(provisional, field.name) != getattr(ungradeable, field.name)
    ]
    assert differing == ["state"], (
        f"fixture bug: the paired rows differ on {differing} — the differential "
        "must hold every figure constant and vary the state column alone"
    )
    return provisional, ungradeable


def _stored(store, score):
    """One real criterion_score row written and read back — the shape a consumer's
    presentation reads."""
    cohort = store.cohort(_COHORT)
    with cohort.transaction() as tx:
        tx.execute(
            _INSERT, sid=_SUBMISSION, cid=_CRITERION, band=score.band,
            points=score.points, jc=score.judge_count, ag=score.agreement,
            state=score.state, routing=score.routing,
        )
    return cohort.query(
        "SELECT * FROM criterion_score WHERE submission_id = :s AND criterion_id = :c",
        s=_SUBMISSION, c=_CRITERION,
    )[0]


@pytest.mark.parametrize(
    "consumer, module, entry, issue",
    [
        # Per-param keying, the sweep's own per-row convention: all three consumer
        # params run unmarked — #101 landed `apply_policy`, #108 landed the queue,
        # and the #122/#126 landing shipped the console module.
        pytest.param("M-GRADE", GRADE_MODULE, "apply_policy", "#101"),
        pytest.param("M-REVIEW", REVIEW_MODULE, "build_review", "#108"),
        pytest.param("M-CONSOLE", CONSOLE_MODULE, "build_console", "#123"),
    ],
    ids=["m_grade", "m_review", "m_console"],
)
def test_tc_agg_c07_consumers_present_ungradeable_by_panel_distinctly(
    consumer, module, entry, issue, tmp_data_dir
):
    """`TC-AGG-C07` (`CT-AGG-07`, contract / rung 2-3, consumer presentation
    differential, P0) — the same figures, one state apart: each consumer's
    presentation of the breaker-refused row must DIFFER from its presentation of
    the ordinary provisional row. A merged presentation degrades the refusal
    quietly — the panel that refused to grade reads as a panel awaiting review,
    and the teacher's queue cannot tell them apart."""
    surface = require(module, entry, issue=issue)
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")
    provisional, ungradeable = _paired_scores(aggregate)

    def presented(score, label):
        """The consumer's presentation of one row, in a store of its own — both
        stores carry the same submission and criterion ids, so the two
        presentations can differ only through the state distinction."""
        if consumer == "M-GRADE":
            # §3.14: the policy consumes the score values with the package policy.
            return surface([score], default_grade_policy())
        store_dir = tmp_data_dir / label
        store_dir.mkdir()
        store = open_store(store_dir)
        try:
            seed_cohort(store, [_SUBMISSION])
            _stored(store, score)
            if consumer == "M-REVIEW":
                return surface(store).queue()
            return surface(store).render_scores(_SUBMISSION)
        finally:
            store.close()

    assert str(presented(ungradeable, "ungradeable")) != str(
        presented(provisional, "provisional")
    ), (
        f"{consumer} presents the breaker-refused row exactly as the ordinary "
        "provisional one — `ungradeable_by_panel` merged into the provisional "
        "presentation hides a panel that refused to grade from the human whose "
        "queue it belongs in (CT-AGG-07's consumer obligation; CT-ORCH-16's "
        "promise degraded quietly)"
    )
