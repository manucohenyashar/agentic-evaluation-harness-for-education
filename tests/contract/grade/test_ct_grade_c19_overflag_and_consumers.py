"""`TC-GRADE-C19` — the interval over-flags, and no consumer reads the flag as a likelihood (§6.11.14).

`CT-GRADE-19` (behaviour): "**Non-promise — the `score_low`/`score_high` interval
is conservative and over-flags.** Assert the promised behaviour rather than a
tighter one: construct a case where the full declared band range crosses a
boundary but any realistic outcome would not, and assert `boundary_at_risk` **is**
set. That over-flagging is the contract. Then the consumer sweep: assert
`M-REVIEW` and `M-CONSOLE` read it as **"could cross", not "likely to cross"** —
asserted over ranking behaviour and rendered language, since a consumer that
treats it as a likelihood would mis-rank the queue and mislead the teacher."

The limbs, in the row's order:

- **the over-flagging fixture** (rung 0, green): the row's exact case over the
  pure seam with the interval INJECTED (`TC-GRADE-06`'s injection contract): the
  full declared band range crosses the floor — so the flag MUST be set, the
  range's endpoints populated — while the realistic twin (the movement a marker
  would actually make, a hair either way) would NOT cross, and the contract does
  NOT promise a flag for it. The pair pins the non-promise: the flag tracks the
  declared range, never a likelihood estimate — a flag that tracked the realistic
  outcome would under-flag, and one that estimated likelihood would be a
  probability the design never promised.
- **the M-REVIEW ranking half** (rung 3, green): the landed queue ranks flagged
  items by boundary PROXIMITY — the delta between the grade and the floor — so the
  over-flagged item (whose flag came from the wide declared range while its total
  sits far from the floor) ranks BELOW the genuinely near-boundary one, at equal
  weight and equal error signals. A likelihood ranker would do the reverse (the
  wider the range, the "more likely" the crossing) and mis-rank the queue.
- **the M-CONSOLE language half** (`[m_console]`, writtenahead): the rendered
  language must read "could cross", never "likely to cross" — a teacher reading a
  likelihood where the design promises a possibility is misled. The landed
  console renders no boundary-risk language at all, so this waits on the
  disclosed `aeh.console:render_grade_coverage` (#107), the same render the
  C04/C05/C13 limbs key on.

Isolation: rung 0 for the pure seam; rung 3 for the review ranking (the queue's
stored-row shape, hand-built — the c16 consumer sweep's declared assumption) and
the console limb. The socket guard is autouse; `criterion_score` rows are the
vocabulary's disclosed `M-AGG` stand-in.
"""

from __future__ import annotations

import pytest

from aeh.grade import boundary_risk
from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.contract.grade._drive import current_grades, graded_run, set_boundaries
from tests.support.impl import CONSOLE_MODULE, GRADE_MODULE, REVIEW_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID

pytestmark = [pytest.mark.contract]

#: One floor is all the over-flag case needs: 63.0 sits inside the declared
#: range's reach and outside the realistic one.
_CUTS = (("B", 63.0), ("A", 85.0))


def test_tc_grade_c19_the_over_flagging_is_the_contract():
    """`TC-GRADE-C19` (`CT-GRADE-19`, rung 0) — the non-promise: the full declared
    band range crosses the floor, so `boundary_at_risk` IS set — while the
    realistic twin's movement would not cross, and the contract does not promise a
    flag for it. The flag consumes the declared range, not a probability of
    crossing."""
    require(GRADE_MODULE, "boundary_risk", issue="#101")

    # The row's case: the provisional criterion's declared band range is wide —
    # its current 3.5 points against a [0.0, 4.0] span lets the total fall to
    # 60.5 — so the range crosses the 63.0 floor. The flag IS set.
    declared_range = boundary_risk(64.0, [(-3.5, 0.5)], _CUTS)
    assert declared_range.at_risk, (
        "the declared-range crossing did not flag — the clause is explicit: the "
        "interval is CONSERVATIVE and OVER-FLAGS, and over-flagging is the "
        "contract, not a defect to tighten (CT-GRADE-19's non-promise)"
    )
    assert declared_range.score_low == 60.5 and declared_range.score_high == 64.5, (
        f"the flagged interval reads ({declared_range.score_low!r}, "
        f"{declared_range.score_high!r}) — the range is the declared band span's, "
        "populated exactly, not a probable range (CT-GRADE-19)"
    )

    # The realistic twin: the movement a marker would actually make — a hair
    # either way — would NOT cross. The contract does not promise a flag here,
    # and the shipped seam does not set one: the same total, the same floors,
    # only the interval's width differs. This is what makes the flag
    # conservative rather than a likelihood: it tracks the declared range's
    # reach, never the plausible outcome.
    realistic = boundary_risk(64.0, [(-0.1, 0.1)], _CUTS)
    assert not realistic.at_risk, (
        f"the realistic-movement twin flagged ({realistic!r}) — the flag is the "
        "declared range's reach, not a likelihood estimate; a flag that fired on "
        "every plausible outcome would be a probability the design never "
        "promised (CT-GRADE-19's non-promise)"
    )
    assert realistic.score_low is None and realistic.score_high is None, (
        "the unflagged twin carries a populated range — a range nobody acts on "
        "is withheld (CT-GRADE-19 with CT-GRADE-05)"
    )


def test_tc_grade_c19_the_review_queue_ranks_proximity_not_likelihood():
    """`TC-GRADE-C19`'s M-REVIEW half (`CT-GRADE-19`, rung 3) — the queue ranks
    flagged items by boundary PROXIMITY, so the over-flagged item (flag from the
    wide declared range, total far from the floor) ranks BELOW the genuinely
    near-boundary one at equal weight and equal error signals. A likelihood
    ranker would promote the over-flagged item — its range is wider, its crossing
    "more likely" — and mis-rank the queue the clause forbids."""
    rank_queue_items = require(REVIEW_MODULE, "rank_queue_items", issue="#108")

    def _flagged(submission_id, delta):
        """One stored score row's shape, flagged-pending, equal in every ranked
        input but the boundary delta (the c16 consumer sweep's row shape)."""
        return {
            "submission_id": submission_id,
            "criterion_id": "C1",
            "band": "B2",
            "state": "provisional",
            "criterion_weight": 1.0,
            "grade_boundary_delta": delta,
        }

    # S-NEAR sits half a point from the floor; S-WIDE's flag came from the
    # declared span's full reach while its total sits a full two points away —
    # the over-flagged shape, realistically safe.
    ranked = rank_queue_items([
        _flagged("S-WIDE", 2.0),
        _flagged("S-CLOSE", 0.5),
    ])
    order = [item.submission_id for item in ranked]
    assert order == ["S-CLOSE", "S-WIDE"], (
        f"the queue ranked {order!r} — the boundary term is PROXIMITY (how close "
        "the grade could come to the floor), so the genuinely near item outranks "
        "the over-flagged one; a consumer reading the flag as a LIKELIHOOD would "
        "rank the wider range first and mis-rank the queue (CT-GRADE-19's "
        "consumer sweep, M-REVIEW)"
    )
    assert ranked[0].expected_value > ranked[1].expected_value, (
        "the ranking did not separate the two flagged items by proximity — the "
        "differential below would be vacuous (CT-GRADE-19)"
    )
    # The flag's presence is not the rank: both items carry the same weight, the
    # same error signals and the same cost — only the delta differs — so the
    # ordering IS the proximity reading, distance not likelihood.
    assert ranked[0].grade_boundary_delta == 0.5 and ranked[1].grade_boundary_delta == 2.0, (
        "fixture bug: the ranked items lost their boundary deltas"
    )


def test_tc_grade_c19_the_console_reads_it_as_could_cross_not_likely(tmp_data_dir):
    """`TC-GRADE-C19`'s M-CONSOLE limb (`CT-GRADE-19`, `[m_console]`, rung 3) — the
    rendered language reads the flagged grade as "could cross", never "likely to
    cross": the flag is a possibility the declared range carries, not a likelihood
    the design promises, and a console that said "likely" would mislead the
    teacher the clause protects.

    Writtenahead on the disclosed `aeh.console:render_grade_coverage` (#107) — the
    same render the C04/C05/C13 limbs key on: the landed console renders no
    boundary-risk language at all, so the consumer obligation waits on that
    landing."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    render_grade_coverage = require(
        CONSOLE_MODULE, "render_grade_coverage", issue="#107"
    )
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=("S-RISK",),
            criteria=(
                {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
                {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
            ),
            rows=[
                ("S-RISK", "C1", "B2", 60.0, "auto"),
                ("S-RISK", "C2", "B1", 3.5, "provisional"),
            ],
            compute=False,  # the declarations must exist before the one pass
        )
        set_boundaries(store, world.version, _CUTS)
        # C05's declared-band-span manufacture: S-RISK's provisional C2 carries
        # the declared span [0.0, 4.0], so its total 63.5's plausible range can
        # reach across the 63.0 floor — the flag the render must speak of.
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        for ordinal, points in enumerate((0.0, 4.0)):
            catalog.add_band(world.version, "C2", ordinal, f"SP{ordinal}", points)
        world.service.compute_all(world.run_id)
        # Fixture gate: the limb presumes a FLAGGED grade on S-RISK — without the
        # declared span the pass emits boundary_at_risk=0 and the render would be
        # asserted against a fixture bug, not the contract.
        (delivered,) = current_grades(store.cohort(ORCH_COHORT_ID), world.run_id)
        assert delivered["submission_id"] == "S-RISK" and delivered[
            "boundary_at_risk"
        ] == 1, (
            f"fixture must produce the flagged grade first: S-RISK delivered "
            f"boundary_at_risk={delivered['boundary_at_risk']!r}"
        )
        rendered = render_grade_coverage(world.run_id, "S-RISK", store=store)
        text = rendered if isinstance(rendered, str) else str(rendered)
        assert "could cross" in text.lower(), (
            f"the console's flagged grade reads {text[:120]!r}... — the language "
            "must present the flag as a possibility (\"could cross\"), the "
            "reading the non-promise pins (CT-GRADE-19's consumer sweep, "
            "M-CONSOLE)"
        )
        assert "likely to cross" not in text.lower(), (
            "the console renders the flagged grade as LIKELY to cross — a "
            "likelihood the design never promised, and the mislead the clause "
            "names (CT-GRADE-19, M-CONSOLE)"
        )
    finally:
        store.close()