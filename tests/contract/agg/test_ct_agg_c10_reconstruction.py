"""`TC-AGG-C10` — the recorded inputs are load-bearing; the row alone suffices (§6.11.12).

`CT-AGG-10`: "The integrity inputs (`spans_verified`, `evidence_present`,
`sufficiency_flag`, `ocr_overlap_risk`) are recorded **on the score row**, so a
confidence figure is reconstructible from stored data alone, years later, without
replaying the run."

The shipped sibling `tests/integration/agg/test_confidence_reconstructible.py`
(`TC-AGG-15`, #95/#92) executes the round trip — aggregate, store, reopen, recompute
equals stored — with one signal set. This file carries the two limbs no sibling runs:

- **the reconstruction differential** (the case's named oracle shape): two rows
  identical on every recorded field but ONE integrity signal recompute to DIFFERENT
  figures, each reproducing its own stored value. A recording that did not move the
  replay would be decoration; the differential proves the recorded dimension is what
  the decision's answerability rides on. The store in this limb holds no verdicts at
  all — asserted — so the recomputation cannot be a replay by construction;
- **the purge limb** (rung 3): a real driven run's verdicts and evidence are DELETED
  from the ledger after the score row is written — the "years later" reading taken
  literally, the replay material gone rather than merely unconsulted — and the
  recomputation from the row alone still reproduces the stored figure.

Isolation: rung 2 for the differential (real SQLite, no run at all); rung 3 for the
purge; the socket guard is autouse.
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.contract.agg._drive import (
    criterion_bands,
    drive_scored_run,
    stored_verdicts,
)
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
_UNANIMOUS_TOP = panel(("B3", 3), ("B3", 3), ("B3", 3))

_COHORT = ORCH_COHORT_ID
_SUBMISSION = "SYN-C10"
_CRITERION = "C1"

_INSERT = (
    "INSERT INTO criterion_score (submission_id, criterion_id, band, points, "
    "judge_count, agreement, state, routing, confidence, confidence_base, "
    "spans_verified, evidence_present, sufficiency_flag, ocr_overlap_risk) "
    "VALUES (:sid, :cid, :band, :points, :judge_count, :agreement, :state, "
    ":routing, :confidence, :confidence_base, :spans_verified, "
    ":evidence_present, :sufficiency_flag, :ocr_overlap_risk)"
)


def _stored_row(cohort, cid, score):
    with cohort.transaction() as tx:
        tx.execute(
            _INSERT,
            sid=_SUBMISSION, cid=cid, band=score.band, points=score.points,
            judge_count=score.judge_count, agreement=score.agreement,
            state=score.state, routing=score.routing, confidence=score.confidence,
            confidence_base=score.confidence_base,
            spans_verified=score.spans_verified,
            evidence_present=score.evidence_present,
            sufficiency_flag=score.sufficiency_flag,
            ocr_overlap_risk=score.ocr_overlap_risk,
        )
    return cohort.query(
        "SELECT * FROM criterion_score WHERE submission_id = :s AND criterion_id = :c",
        s=_SUBMISSION, c=cid,
    )[0]


def test_tc_agg_c10_the_recorded_signal_dimension_moves_the_replay(tmp_data_dir):
    """`TC-AGG-C10` (`CT-AGG-10`, `FR-AGG-13`, `NFR-AGG-04`, contract / rung 2,
    reconstruction differential, P0) — two rows identical on every recorded field
    but one signal recompute to different figures, each reproducing its own stored
    value, in a store that holds no verdicts at all. The recording is what the
    answerability rides on; a replay that ignored it would answer two different
    disputes with one number."""
    aggregate, recompute_confidence = require(
        AGG_MODULE, "aggregate", "recompute_confidence", issue="#92"
    )

    store = open_store(tmp_data_dir)
    try:
        cohort = store.cohort(_COHORT)
        seed_cohort(store, [_SUBMISSION])

        # A store that never held a run: the replay below cannot consult verdicts,
        # because there are none to consult.
        assert cohort.query("SELECT COUNT(*) AS n FROM verdict")[0]["n"] == 0, (
            "fixture bug: the store holds verdict rows — the recomputation below "
            "would not be a from-the-row-alone answer"
        )

        measured = aggregate(_UNANIMOUS_TOP, _FOUR_BAND, signals(),
                             config=agg_config())
        unmeasured = aggregate(_UNANIMOUS_TOP, _FOUR_BAND,
                               signals(spans_verified=None), config=agg_config())
        row_measured = _stored_row(cohort, "C-MEASURED", measured)
        row_unmeasured = _stored_row(cohort, "C-UNMEASURED", unmeasured)

        # The one recorded difference, round-tripped: the measured row carries the
        # favourable reading; the unmeasured row carries `None` — recorded, not
        # defaulted to favourable (the fail-closed half rides the row too). Booleans
        # read back as 0/1 on the raw handles (no `detect_types`).
        assert row_measured["spans_verified"] in (1, True), (
            "the measured row's favourable signal did not survive the write"
        )
        assert row_unmeasured["spans_verified"] is None, (
            "the unmeasured row's None did not survive the write — recorded, not "
            "defaulted to favourable; the differential below would compare two "
            "identical rows"
        )

        replay_measured = recompute_confidence(row_measured, _FOUR_BAND)
        replay_unmeasured = recompute_confidence(row_unmeasured, _FOUR_BAND)
        assert replay_measured == pytest.approx(measured.confidence), (
            f"the measured row replays {replay_measured!r} against its stored "
            f"{measured.confidence!r} — the reconstruction must reproduce the "
            "recorded figure from the row alone (NFR-AGG-04)"
        )
        assert replay_unmeasured == pytest.approx(unmeasured.confidence), (
            f"the unmeasured row replays {replay_unmeasured!r} against its stored "
            f"{unmeasured.confidence!r} — the None signal must replay as the "
            "fail-closed cap, never as favourable (CT-AGG-05's recorded arm)"
        )
        assert replay_measured != pytest.approx(replay_unmeasured), (
            "rows differing only in one recorded signal replay the same figure — "
            "the recording is decorative, and the disputed routing decision's "
            "cause is NOT answerable from the row (CT-AGG-10's differential)"
        )
    finally:
        store.close()


def test_tc_agg_c10_after_the_run_is_purged_the_row_still_answers(tmp_data_dir,
                                                                  make_fixture_provider):
    """`TC-AGG-C10` (`CT-AGG-10`, contract / rung 3, the purge limb, P0) — the
    run's verdicts and evidence deleted after the score row is written: the
    recomputation from the row alone still reproduces the stored figure. A disputed
    routing decision outlives the run that produced it — that is the clause's
    point, and here the replay material is demonstrably gone."""
    aggregate, recompute_confidence = require(
        AGG_MODULE, "aggregate", "recompute_confidence", issue="#92"
    )

    provider = make_fixture_provider()
    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = drive_scored_run(store, provider, submissions=(_SUBMISSION,))
        rows = stored_verdicts(store, run_id, _SUBMISSION, _CRITERION)
        crit = criterion(criterion_bands(store, _CRITERION), criterion_id=_CRITERION)
        score = aggregate(rows, crit, signals(), config=agg_config())

        cohort = store.cohort(_COHORT)
        stored = _stored_row(cohort, _CRITERION, score)

        # The purge: every verdict and every evidence row the run produced —
        # the material a replay would need. `work_unit` survives (the run's own
        # ledger); what the confidence could have been replayed FROM does not.
        with cohort.transaction() as tx:
            tx.execute(
                "DELETE FROM evidence WHERE work_id IN "
                "(SELECT work_id FROM work_unit WHERE run_id = :r)", r=run_id,
            )
            tx.execute(
                "DELETE FROM verdict WHERE work_id IN "
                "(SELECT work_id FROM work_unit WHERE run_id = :r)", r=run_id,
            )
        assert cohort.query(
            "SELECT COUNT(*) AS n FROM verdict v JOIN work_unit w "
            "ON w.work_id = v.work_id WHERE w.run_id = :r", r=run_id,
        )[0]["n"] == 0, (
            "fixture bug: verdicts survived the purge — the recomputation below "
            "would not be the years-later reading the clause names"
        )

        # A fresh handle: nothing from the write half's memory survives.
        reopened = open_store(tmp_data_dir).cohort(_COHORT)
        row = reopened.query(
            "SELECT * FROM criterion_score WHERE submission_id = :s AND "
            "criterion_id = :c", s=_SUBMISSION, c=_CRITERION,
        )[0]
        replayed = recompute_confidence(row, crit)
        assert replayed == pytest.approx(stored["confidence"]), (
            f"after the purge the row replays {replayed!r} against the stored "
            f"{stored['confidence']!r} — the confidence must be reconstructible "
            "from the row alone, years later, without replaying the run "
            "(NFR-AGG-04, RISK-12)"
        )
    finally:
        store.close()
