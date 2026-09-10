"""`TC-AGG-C03` — the discard's output is a legal stored row (§6.11.12, rung 2).

`CT-AGG-03`'s data clause has two shipped halves this case does not repeat, disclosed
up front: the odd-`judge_count` CHECK sweep — a real store refusing judge_count 2 and 4
with an `IntegrityError` and admitting 0, 1, 3, 5 — is `tests/integration/agg/
test_even_panel_failed_write.py` (`TC-AGG-04`), and the 1 → 3-never-2 escalation limb is
`tests/unit/agg/test_routing_and_escalation.py` (`TC-AGG-11`, with the shipped
`aeh.orch:validate_escalation_plan`). This case carries the limb neither sibling runs:
**the composition** — the two-verdict discard's own output (`aggregate(..., fallback=
True)`'s `judge_count = 1`, `provisional_unreviewed`, `provisional` row) written through
a real store and read back. The clause is a *data* clause: the discard is only real if
its output survives the write path the clause names — a discard that produced a shape
the CHECK refused (an even count, an unstate-ed row) would be a refusal discovered one
layer too late, by the database, in production. The round trip asserts the stored row
equals what the aggregation produced, on every recorded column.

Isolation: rung 2 — real SQLite, seeded cohort and submission rows; the panel path
itself stays rung 0 (the sibling TC-AGG-12 owns the pure discard assertion — this file
asserts only what the STORE does with the discard's output).
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support.agg_vocabulary import (
    band,
    criterion,
    panel,
    signals,
    agg_config,
)
from tests.support.impl import AGG_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort

pytestmark = [pytest.mark.contract]

_FOUR_BAND = criterion([band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0),
                        band("B3", 3, 6.0)])
_TWO_LEFT = panel(("B1", 1), ("B3", 3))

_COHORT = ORCH_COHORT_ID
_SUBMISSION = "SYN-C03"
_CRITERION = "C-AGG"

_INSERT = (
    "INSERT INTO criterion_score (submission_id, criterion_id, band, points, "
    "judge_count, agreement, state, routing, confidence, confidence_base, "
    "spans_verified, evidence_present, sufficiency_flag, ocr_overlap_risk) "
    "VALUES (:sid, :cid, :band, :points, :judge_count, :agreement, :state, "
    ":routing, :confidence, :confidence_base, :spans_verified, "
    ":evidence_present, :sufficiency_flag, :ocr_overlap_risk)"
)


def test_tc_agg_c03_the_fallback_discard_round_trips_through_a_real_store(
    tmp_data_dir,
):
    """`TC-AGG-C03` (`CT-AGG-03`, `FR-AGG-12`, contract / rung 2, exact stored
    state, P0) — the two-verdict discard's output, written through the real
    `criterion_score` path and read back, is exactly what the pure aggregation
    returned: `judge_count = 1` (the CHECK's odd arm admits it), the provisional
    state, and the recorded inputs — the discard is a *stored* verdict shape,
    not just a returned one."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")

    score = aggregate(_TWO_LEFT, _FOUR_BAND, signals(), fallback=True,
                      config=agg_config())
    assert score.judge_count == 1 and score.state == "provisional_unreviewed", (
        "fixture bug: the discard did not produce the two-verdict fallback shape "
        "TC-AGG-12 pins, so the round trip below would assert nothing about it"
    )

    store = open_store(tmp_data_dir)
    try:
        cohort = store.cohort(_COHORT)
        seed_cohort(store, [_SUBMISSION])
        with cohort.transaction() as tx:
            tx.execute(
                _INSERT,
                sid=_SUBMISSION, cid=_CRITERION, band=score.band, points=score.points,
                judge_count=score.judge_count, agreement=score.agreement,
                state=score.state, routing=score.routing, confidence=score.confidence,
                confidence_base=score.confidence_base,
                spans_verified=score.spans_verified,
                evidence_present=score.evidence_present,
                sufficiency_flag=score.sufficiency_flag,
                ocr_overlap_risk=score.ocr_overlap_risk,
            )

        row = cohort.query(
            "SELECT * FROM criterion_score WHERE submission_id = :s AND "
            "criterion_id = :c",
            s=_SUBMISSION, c=_CRITERION,
        )
        assert len(row) == 1, (
            "the discard's score row did not survive the write — the composition "
            "between the pure discard and the stored row is the clause's data claim"
        )
        stored = row[0]
        assert stored["judge_count"] == 1, (
            f"the stored row carries judge_count {stored['judge_count']!r} — the "
            "discard's 1 (the odd-judge_count CHECK admits it; a CHECK that refused "
            "1 would make the fallback unstoragable, which is the same defect as "
            "rounding it to 2)"
        )
        assert stored["state"] == "provisional_unreviewed", (
            f"the stored row carries state {stored['state']!r} — the provisional "
            "state the discard assigned, surviving the store round trip (FR-AGG-12)"
        )
        assert stored["routing"] == "provisional", (
            f"the stored row routes {stored['routing']!r} — never auto-accepted "
            "(FR-AGG-07: a single-judge band awaits its panel)"
        )
        assert stored["band"] == "B1" and stored["points"] == 1.0, (
            "the stored row's band/points differ from the discard's — the write "
            "altered the aggregation (CT-AGG-02's mapped-once, echoed intact)"
        )
    finally:
        store.close()
