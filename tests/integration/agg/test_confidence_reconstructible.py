"""`TC-AGG-15` — the confidence is recomputable from the stored row alone.

Test plan §5.12 (row form: Integration / rung 2), issue #95 (TS-36). Traces to
`FR-AGG-13`, `NFR-AGG-04`; the accountability half of RISK-01. Written ahead of #92
(the `confidence` column and the four FR-AGG-13 integrity columns land with #92's
migration; the `aggregate` core is #91's — the `#76 forged evidence` key precedent).

**The round trip.** Aggregate a real panel, write the score it returns into a real
`criterion_score` row (the four integrity inputs ON the row, per FR-AGG-13), then —
from a freshly opened store handle, with nothing else in memory ("years later") —
read the row back and recompute the confidence from the row alone. The oracle is
equality with what was stored: a disputed routing decision must be answerable from
the stored data, without replaying the run (NFR-AGG-04).

**Assumed of #92** (declared so it is reconciled deliberately):

| Name | Status |
|---|---|
| `aeh.agg:recompute_confidence(row, criterion)` | **invented** — NFR-AGG-04 needs the confidence derivable from the stored row; §3.12 names no function. `row` is the read-back `criterion_score` mapping; `criterion` is the package's static band definition (configuration, not run state). |
| criterion_score columns `confidence`, `spans_verified`, `evidence_present`, `sufficiency_flag`, `ocr_overlap_risk` | the migration v9 columns exist today (det.py); these five land with #92's migration. The INSERT names them, so a conforming landing satisfies this file's SQL unchanged. |
| score `.confidence` + the four integrity fields | the returned score's fields, as in `test_confidence_inversion.py`. |

Isolation: rung 2 — real SQLite, real migrations, real store handles; the only
stand-ins are the aggregation value objects (`tests/support/agg_vocabulary.py`) and
the aggregate call itself, which is the case's designed blocker. The submission row
the FK needs is INSERTed directly (the `orch_run.py` disclosed-bypass precedent).
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
import aeh.det  # noqa: F401 — registers the score-state migration carrying criterion_score

from tests.support.agg_vocabulary import (
    band,
    criterion,
    panel,
    signals,
    agg_config,
)
from tests.support.impl import AGG_MODULE, require

_COHORT = "c-agg-15"
_SUBMISSION = "s-agg-15"
_CRITERION_ID = "C-AGG-15"

_FOUR_BAND = criterion(
    [band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0), band("B3", 3, 6.0)],
    criterion_id=_CRITERION_ID,
)

#: The panel whose score makes the round trip: enough disagreement to make the
#: confidence non-trivial, one adverse signal to make the cap part of the stored
#: figure — a row that actually needed its integrity inputs.
_PANEL = panel(("B2", 2), ("B2", 2), ("B3", 3))
_SIGNALS = signals(spans_verified=False)


def _seed_submission(cohort) -> None:
    with cohort.transaction() as tx:
        tx.execute(
            "INSERT INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES (:c, 'synthetic', '2026-01-01T00:00:00Z')",
            c=_COHORT,
        )
        tx.execute(
            "INSERT INTO submission (submission_id, cohort_id, student_ref) "
            "VALUES (:s, :c, 'r-1')",
            s=_SUBMISSION, c=_COHORT,
        )


def test_tc_agg_15_the_confidence_is_recomputable_from_the_stored_row_alone(tmp_data_dir):
    """`TC-AGG-15` (`FR-AGG-13`, `NFR-AGG-04`, integration / rung 2, round-trip
    recomputation, P0) — aggregate, store, reopen, recompute: the recomputed figure
    equals the stored one, and the four integrity inputs are on the row."""
    # `require` returns one symbol per probed name — three names, three bindings.
    aggregate, recompute_confidence, _auto_threshold = require(
        AGG_MODULE, "aggregate", "recompute_confidence",
        "AGG_AUTO_THRESHOLD_ATOMIC", issue="#92",
    )

    # Write half: aggregate the panel and store the score WITH its integrity inputs.
    store = open_store(tmp_data_dir)
    cohort = store.cohort(_COHORT)
    _seed_submission(cohort)

    score = aggregate(_PANEL, _FOUR_BAND, _SIGNALS, config=agg_config())
    with cohort.transaction() as tx:
        tx.execute(
            "INSERT INTO criterion_score (submission_id, criterion_id, band, points, "
            "judge_count, agreement, state, routing, confidence, confidence_base, "
            "spans_verified, evidence_present, sufficiency_flag, ocr_overlap_risk) "
            "VALUES (:sid, :cid, :band, :points, :judge_count, :agreement, :state, "
            ":routing, :confidence, :confidence_base, :spans_verified, "
            ":evidence_present, :sufficiency_flag, :ocr_overlap_risk)",
            sid=_SUBMISSION, cid=_CRITERION_ID, band=score.band, points=score.points,
            judge_count=score.judge_count, agreement=score.agreement,
            state=score.state, routing=score.routing, confidence=score.confidence,
            confidence_base=score.confidence_base,
            spans_verified=score.spans_verified,
            evidence_present=score.evidence_present,
            sufficiency_flag=score.sufficiency_flag,
            ocr_overlap_risk=score.ocr_overlap_risk,
        )

    # Read half: a FRESH handle — nothing from the write half's memory survives. This
    # is the "years later" limb: the recomputation consumes the row and the static
    # criterion definition and nothing else.
    reopened = open_store(tmp_data_dir).cohort(_COHORT)
    row = reopened.query(
        "SELECT * FROM criterion_score WHERE submission_id = :s AND criterion_id = :c",
        s=_SUBMISSION, c=_CRITERION_ID,
    )[0]

    # The store returns raw sqlite3 rows (no detect_types), so boolean columns read
    # back as 0/1 whatever the migration declares — the assertion accepts either
    # representation (the boolean-column precedent of the saw-system-output contract).
    assert row["spans_verified"] in (0, False), (
        f"spans_verified read back {row['spans_verified']!r} — it must be the False "
        "the aggregation recorded: FR-AGG-13's recorded inputs are what make the "
        "confidence answerable years later"
    )
    assert row["evidence_present"] in (1, True), (
        f"evidence_present read back {row['evidence_present']!r} — it must be the "
        "True the aggregation recorded (FR-AGG-13)"
    )
    assert row["sufficiency_flag"] in (0, False), (
        f"sufficiency_flag read back {row['sufficiency_flag']!r} — it must be the "
        "False the aggregation recorded (FR-AGG-13)"
    )
    assert row["ocr_overlap_risk"] in (0, False), (
        f"ocr_overlap_risk read back {row['ocr_overlap_risk']!r} — it must be the "
        "False the aggregation recorded (FR-AGG-13)"
    )

    recomputed = recompute_confidence(row, _FOUR_BAND)
    assert recomputed == pytest.approx(row["confidence"]), (
        f"the recomputed confidence {recomputed!r} does not reproduce the stored "
        f"{row['confidence']!r} — NFR-AGG-04: the confidence is reconstructible from "
        "the stored row alone, so a disputed routing decision is answerable years "
        "later without replaying the run"
    )
    assert recomputed == pytest.approx(score.confidence), (
        f"the stored confidence {row['confidence']!r} does not reproduce the "
        f"aggregation-time figure {score.confidence!r} — the write half must store "
        "what the computation produced, unrounded (FR-AGG-13's chain)"
    )
