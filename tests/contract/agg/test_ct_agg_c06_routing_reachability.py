"""`TC-AGG-C06` — routing is the closed five-value set, reached as declared (§6.11.12).

`CT-AGG-06`: "`routing` is one of `auto` / `queued` / `reviewed` / `provisional` /
`triage`; an unresolved or ingestion-failed result routes `triage`, never `queued`; a
deterministic result never routes `queued`; assert both as reachability properties at
rung 3." The shipped siblings pin the threshold arithmetic that decides `auto` vs
`queued` (`tests/unit/agg/test_routing_and_escalation.py`, `TC-AGG-11`, #93) and the
provisional routing of the discard and the breaker (TC-AGG-12/13 there). Neither runs:

- **the closed set over the whole swept surface** — every entry of `aggregate`'s
  reachability (panel, uncited, each adverse cap, fallback, breaker, holistic,
  deterministic final, deterministic unresolved) yields one of the five values, and
  the sixth, `reviewed`, is emitted by **none**: a teacher's override is M-GRADE's
  act (§3.14), and an aggregation that ever self-assigned `reviewed` would be
  forging the human's mark;
- **the two prohibitions as reachability**, at rung 0 and again at rung 2 through a
  real store: the deterministic path's outputs (`final`→`auto`, the unresolved
  selection→`triage`, `aeh.det:BAND_UNRESOLVED`'s marker band as M-DET writes it)
  land exactly there and never `queued` — the module det.py's own comment records
  the boundary ("nothing in this module's vocabulary admits `queued`") — and the
  store's v9 CHECK admits exactly the five declared values and refuses a sixth, so
  the closed set holds at the boundary the consumers read, not only in the function.

Isolation: rung 0 for the sweep; rung 2 (real SQLite, seeded cohort) for the store
boundary; the socket guard is autouse.
"""

from __future__ import annotations

import re

import pytest

from aeh.store import open_store
from tests.support.agg_vocabulary import (
    band,
    criterion,
    panel,
    signals,
    verdict,
    agg_config,
)
from tests.support.impl import AGG_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort

pytestmark = [pytest.mark.contract]

_FOUR_BAND = criterion([band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0),
                        band("B3", 3, 6.0)])
_HOLISTIC = criterion(_FOUR_BAND.bands, scoring_model="holistic")
_UNANIMOUS_TOP = panel(("B3", 3), ("B3", 3), ("B3", 3))
_SPLIT = panel(("B0", 0), ("B1", 1), ("B1", 1), ("B1", 1), ("B2", 2))

#: The closed routing set, verbatim from det v9 (CT-AGG-06's enumeration).
ROUTING_SET = ("auto", "queued", "reviewed", "provisional", "triage")
#: The four states the same migration declares (the sweep asserts these too).
STATE_SET = ("final", "provisional_unreviewed", "ungradeable_by_panel",
             "unresolved_selection")

_COHORT = ORCH_COHORT_ID
_SUBMISSION = "SYN-C06"

#: The deterministic final row as M-DET writes it (judge_count 0, agreement NULL).
_DET_FINAL = {
    "submission_id": _SUBMISSION, "criterion_id": "C-DET",
    "band": "correct", "points": 1.0, "judge_count": 0, "agreement": None,
    "state": "final", "routing": "auto",
}
#: The unresolved selection as M-DET writes it — the marker band, no points, the
#: operator queue (`FR-INGEST-30`'s boundary). `aeh.det` writes `triage` at the
#: source; the aggregation's duty is to land it there and never re-route it.
_DET_UNRESOLVED = {
    "submission_id": _SUBMISSION, "criterion_id": "C-DET",
    "band": "unresolved", "points": None, "judge_count": 0, "agreement": None,
    "state": "unresolved_selection", "routing": "triage",
}

_INSERT = (
    "INSERT INTO criterion_score (submission_id, criterion_id, band, points, "
    "judge_count, agreement, state, routing) "
    "VALUES (:sid, :cid, :band, :points, :judge_count, :agreement, :state, :routing)"
)


def _surface(aggregate):
    """Every routing-relevant entry of the aggregation surface, as (cell, output)
    pairs — the sweep the closed-set and prohibition assertions run over."""
    config = agg_config()
    cells: list[tuple[str, object]] = []
    cells.append(("unanimous panel",
                  aggregate(_UNANIMOUS_TOP, _FOUR_BAND, signals(), config=config)))
    cells.append(("split panel",
                  aggregate(_SPLIT, _FOUR_BAND, signals(), config=config)))
    cells.append(("uncited unanimous",
                  aggregate([verdict("B3", 3), verdict("B3", 3),
                             verdict("B3", 3, cited=False)],
                            _FOUR_BAND, signals(), config=config)))
    for name in ("spans_verified", "evidence_present", "sufficiency_flag",
                 "ocr_overlap_risk", "described_evidence", "extractor_disagreement"):
        cells.append((f"{name} adverse",
                      aggregate(_UNANIMOUS_TOP, _FOUR_BAND, signals(**{name: None}),
                                config=config)))
    cells.append(("fallback discard",
                  aggregate(panel(("B1", 1), ("B3", 3)), _FOUR_BAND, signals(),
                            fallback=True, config=config)))
    cells.append(("breaker tripped",
                  aggregate(_UNANIMOUS_TOP, _FOUR_BAND, signals(),
                            breaker_tripped=True, config=config)))
    cells.append(("holistic panel",
                  aggregate(_UNANIMOUS_TOP, _HOLISTIC, signals(), config=config)))
    cells.append(("deterministic final",
                  aggregate([], _FOUR_BAND, signals(),
                            deterministic_score=dict(_DET_FINAL), config=config)))
    cells.append(("unresolved selection",
                  aggregate([], _FOUR_BAND, signals(),
                            deterministic_score=dict(_DET_UNRESOLVED), config=config)))
    return cells


def test_tc_agg_c06_every_reached_routing_is_in_the_closed_set_and_reviewed_is_not_reached():
    """`TC-AGG-C06` (`CT-AGG-06`, `FR-AGG-07`, unit / rung 0, closed set + non-
    reachability, P0) — over the whole swept surface, `routing` is always one of
    the five declared values; and `reviewed` is reached by NONE of them — the
    teacher's override mark is M-GRADE's (§3.14), never the aggregator's."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")

    cells = _surface(aggregate)

    for cell, score in cells:
        assert score.routing in ROUTING_SET, (
            f"cell {cell!r} routed {score.routing!r} — outside the closed five-value "
            "set (CT-AGG-06)"
        )
        assert score.state in STATE_SET, (
            f"cell {cell!r} recorded state {score.state!r} — outside the closed "
            "state set (CT-AGG-06's store vocabulary)"
        )
    reviewers = [cell for cell, score in cells if score.routing == "reviewed"]
    assert reviewers == [], (
        f"cells {reviewers} routed themselves 'reviewed' — a teacher's override "
        "mark is assigned by M-GRADE on review, and an aggregation that reaches it "
        "forges the human's action (CT-AGG-06's non-reachability)"
    )


def test_tc_agg_c06_the_deterministic_path_never_reaches_queued_and_the_unresolved_lands_triage():
    """`TC-AGG-C06` (`CT-AGG-06`, unit / rung 0, the two named prohibitions, P0) —
    the deterministic entries are the clause's two reachability prohibitions: a
    scored det row routes `auto`, an unresolved selection routes `triage`, and
    NEITHER ever routes `queued` — the teacher's queue is for panel disagreement,
    and a deterministic row has none to disagree about."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")

    final_score = aggregate([], _FOUR_BAND, signals(),
                            deterministic_score=dict(_DET_FINAL), config=agg_config())
    unresolved_score = aggregate([], _FOUR_BAND, signals(),
                                 deterministic_score=dict(_DET_UNRESOLVED),
                                 config=agg_config())

    assert final_score.routing == "auto", (
        f"the scored det row routed {final_score.routing!r} — a deterministic row "
        "arrives complete (FR-DET-03) and rides the auto path, never queued"
    )
    assert unresolved_score.routing == "triage", (
        f"the unresolved selection routed {unresolved_score.routing!r} — the "
        "operator queue (`FR-INGEST-30`'s boundary), never the teacher's"
    )
    assert unresolved_score.state == "unresolved_selection", (
        f"the unresolved selection recorded state {unresolved_score.state!r} — "
        "M-DET's three-way distinction survives the pass-through"
    )
    assert "queued" not in (final_score.routing, unresolved_score.routing), (
        "a deterministic path reached the teacher's queue — the clause's "
        "never-queued prohibition (CT-AGG-06)"
    )


def _check_segment(stored_sql: str, column: str) -> str:
    """The CHECK's parenthesised value list for `column`, out of the shipped table
    DDL — asserted directly so a refusal by some *other* constraint cannot
    masquerade as this case passing (the sibling TC-AGG-04's pattern)."""
    match = re.search(rf"CHECK \({column} IN \(([^)]*)\)\)", stored_sql)
    assert match is not None, (
        f"the criterion_score table carries no {column} CHECK — the closed set "
        "cannot be the store's law if the store never wrote it (det v9)"
    )
    return match.group(1)


def test_tc_agg_c06_the_closed_set_holds_at_the_real_store_boundary(tmp_data_dir):
    """`TC-AGG-C06` (`CT-AGG-06`, contract / rung 2, P0) — the reachability
    properties through a real store: the deterministic pair and a queued panel
    score each round-trip with their routing intact; and the v9 CHECKs name
    exactly the declared sets — the routing CHECK admits each of the five values
    and refuses a sixth with an `IntegrityError`, the state CHECK the four — so
    the closed set is the store's law, not just the function's convention."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")

    split_score = aggregate(_SPLIT, _FOUR_BAND, signals(), config=agg_config())
    final_score = aggregate([], _FOUR_BAND, signals(),
                            deterministic_score=dict(_DET_FINAL), config=agg_config())
    unresolved_score = aggregate([], _FOUR_BAND, signals(),
                                 deterministic_score=dict(_DET_UNRESOLVED),
                                 config=agg_config())

    store = open_store(tmp_data_dir)
    try:
        cohort = store.cohort(_COHORT)
        seed_cohort(store, [_SUBMISSION])

        # The constraints exist, on the shipped table, in the form the design
        # declares — asserted directly (the TC-AGG-04 pattern).
        stored_sql = cohort.query(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='criterion_score'"
        )[0]["sql"]
        routing_list = _check_segment(stored_sql, "routing")
        others = [
            token for token in re.findall(r"'([^']*)'", routing_list)
            if token not in ROUTING_SET
        ]
        assert others == [] and all(
            f"'{value}'" in routing_list for value in ROUTING_SET
        ), (
            f"the routing CHECK is not exactly the closed five (found extras "
            f"{others}) — a value the design never declared, or one it did that "
            "the store lost (det v9, CT-AGG-06)"
        )
        state_list = _check_segment(stored_sql, "state")
        others = [
            token for token in re.findall(r"'([^']*)'", state_list)
            if token not in STATE_SET
        ]
        assert others == [] and all(
            f"'{value}'" in state_list for value in STATE_SET
        ), (
            f"the state CHECK is not exactly the four declared states (found "
            f"extras {others}) — CT-AGG-06's store vocabulary"
        )

        with cohort.transaction() as tx:
            for cid, score in (("C-DET", final_score), ("C-DEU", unresolved_score),
                               ("C-PANEL", split_score)):
                tx.execute(
                    "INSERT INTO criterion_score (submission_id, criterion_id, band, "
                    "points, judge_count, agreement, state, routing) "
                    "VALUES (:sid, :cid, :band, :points, :jc, :ag, :state, :routing)",
                    sid=_SUBMISSION, cid=cid, band=score.band, points=score.points,
                    jc=score.judge_count, ag=score.agreement, state=score.state,
                    routing=score.routing,
                )
            # The closed set, both directions: every declared value is admitted;
            # a value outside the set is refused by the CHECK itself.
            for index, routing in enumerate(ROUTING_SET):
                tx.execute(
                    "INSERT INTO criterion_score (submission_id, criterion_id, band, "
                    "points, judge_count, agreement, state, routing) VALUES "
                    "(:sid, :cid, 'correct', 1.0, 0, NULL, 'final', :routing)",
                    sid=_SUBMISSION, cid=f"C-SET-{index}", routing=routing,
                )
            for index, state in enumerate(STATE_SET):
                tx.execute(
                    "INSERT INTO criterion_score (submission_id, criterion_id, band, "
                    "points, judge_count, agreement, state, routing) VALUES "
                    "(:sid, :cid, 'correct', 1.0, 0, NULL, :state, 'auto')",
                    sid=_SUBMISSION, cid=f"C-STATE-{index}", state=state,
                )
            for column in ("routing", "state"):
                with pytest.raises(Exception) as refused:
                    tx.execute(
                        "INSERT INTO criterion_score (submission_id, criterion_id, "
                        "band, points, judge_count, agreement, state, routing) "
                        "VALUES (:sid, :cid, 'correct', 1.0, 0, NULL, "
                        ":state, :routing)",
                        sid=_SUBMISSION, cid=f"C-BOGUS-{column}",
                        state="bogus" if column == "state" else "final",
                        routing="bogus" if column == "routing" else "auto",
                    )
                assert type(refused.value).__name__ == "IntegrityError", (
                    f"a {column} outside the closed set was refused by "
                    f"{type(refused.value).__name__!r} — the refusal must be the "
                    "v9 CHECK, not some other constraint (CT-AGG-06)"
                )

        rows = cohort.query(
            "SELECT criterion_id, routing, state FROM criterion_score "
            "WHERE submission_id = :s", s=_SUBMISSION,
        )
        stored = {row["criterion_id"]: row for row in rows}
        assert stored["C-DET"]["routing"] == "auto", (
            "the scored det row's auto routing did not survive the write — the "
            "reachability property fails at the boundary the consumers read"
        )
        assert stored["C-DEU"]["routing"] == "triage", (
            "the unresolved selection's triage routing did not survive the write — "
            "the operator queue would lose the row (CT-AGG-06)"
        )
        assert stored["C-PANEL"]["routing"] == "queued", (
            "the split panel's queued routing did not survive the write"
        )
        for cid in ("C-DET", "C-DEU"):
            assert stored[cid]["routing"] != "queued", (
                f"the deterministic cell {cid} reached the teacher's queue through "
                "the real store — the never-queued prohibition (CT-AGG-06)"
            )
    finally:
        store.close()
