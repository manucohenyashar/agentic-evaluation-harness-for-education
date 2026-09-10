"""`TC-AGG-C15` — the per-criterion figures, and per-cap counts that stay separate (§6.11.12).

`CT-AGG-15`: "Emits, per criterion: band histogram, `band_spread` distribution,
ordinal α, escalation rate, auto-accept rate, and **the count of each hard cap
fired**. The last is the load-bearing one: caps firing at an unusual rate on one
criterion is an extraction problem wearing a confidence costume."

The case's oracle is an **artifact assertion on names and per-cap dimensionality**
(rung 2, P0), and that is what this file executes:

- **the names** (rung 0): the score the module emits per criterion carries every
  observable the clause lists — the histogram, the spread, the α — as named
  fields, not a bag;
- **the per-cap dimensionality differential** (rung 2, the load-bearing one):
  from stored `criterion_score` rows ALONE, the caps' fired-counts derive PER CAP
  — two rows whose adverse signals differ count under DIFFERENT keys, and the
  counts stay separate where a total-only counter would merge them into one
  number that can no longer tell an extraction problem from a panel problem. The
  derivation reads exactly the four recorded integrity fields (`FR-AGG-13`): the
  two unrecorded signals (`described_evidence`, `extractor_disagreement`) are the
  design's own disclosed residual — a confidence they capped is not fully
  re-derivable from the row, and their fired-counts are not derivable either;
- **the rate figures** (rung 3): the auto-accept rate derives from the stored
  `routing` column per criterion, and the escalation rate from the
  escalation-origin units `M-ORCH` inserts (`TC-AGG-C08`'s composition proved
  they land unconditionally in the caller's transaction) — both keyed per
  criterion, never in total.

Isolation: rung 0 for the names; rung 2 (real SQLite, seeded cohort) for the
per-cap differential; rung 3 (real driven run) for the rates; the socket guard is
autouse.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields

import pytest

from aeh.agg import CriterionScore
from aeh.store import open_store
from tests.contract.agg._drive import (
    criterion_bands,
    drive_scored_run,
    stored_verdicts,
)
from tests.support.agg_vocabulary import (
    DESIGN_CAPS,
    FAVOURABLE,
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

#: The four integrity fields FR-AGG-13 records on the row — exactly the
#: dimensions the per-cap derivation below may read.
RECORDED_SIGNALS = ("spans_verified", "evidence_present", "sufficiency_flag",
                    "ocr_overlap_risk")

_COHORT = ORCH_COHORT_ID
_SUBMISSION = "SYN-C15"
_CRITERION = "C-CAPS"

_INSERT = (
    "INSERT INTO criterion_score (submission_id, criterion_id, band, points, "
    "judge_count, agreement, state, routing, confidence, confidence_base, "
    "spans_verified, evidence_present, sufficiency_flag, ocr_overlap_risk) "
    "VALUES (:sid, :cid, :band, :points, :jc, :agreement, :state, :routing, "
    ":confidence, :confidence_base, :spans, :evidence, :sufficiency, :ocr)"
)


def test_tc_agg_c15_the_emitted_score_carries_every_declared_observable():
    """`TC-AGG-C15` (`CT-AGG-15`, observe / rung 0, artifact assertion on names,
    P0) — the score emitted per criterion carries the clause's observables as
    named fields: the band histogram (in the criterion's own band order), the
    spread, ordinal α (`agreement`), and the routing the auto-accept rate reads.
    A figure that exists only inside a log line is not emission."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#91")

    names = {field.name for field in dataclass_fields(CriterionScore)}
    for observable in ("histogram", "band_spread", "agreement", "routing",
                       "confidence"):
        assert observable in names, (
            f"the emitted score carries no {observable!r} field — the clause's "
            "per-criterion figures must be named fields on the emission "
            "(CT-AGG-15), not values a consumer re-derives from prose"
        )

    split = aggregate(
        [verdict for verdict in panel(("B3", 3), ("B3", 3), ("B0", 0))],
        _FOUR_BAND, signals(), config=agg_config(),
    )
    order = [entry[0] for entry in split.histogram]
    declared = [row.band for row in _FOUR_BAND.bands]
    assert order == [name for name in declared if name in order], (
        f"the histogram ran {order!r} against declared bands {declared!r} — the "
        "histogram must emit in the criterion's own band order (CT-AGG-15)"
    )
    assert split.band_spread == 3 and split.agreement is not None, (
        "the split panel's spread and α did not emit — the per-criterion "
        "figures the clause lists must ride the score (CT-AGG-15)"
    )


def _adverse(value, field):
    """The stored signal's adverse reading (0/1 on the raw handles; `None` =
    not measured = adverse, the fail-closed reading)."""
    if value is None:
        return True
    return bool(value) != FAVOURABLE[field]


def _caps_fired_from_row(row, cap_table):
    """The hard caps one stored row fired, derived from the row alone: a cap
    fired iff its signal is recorded adverse AND the pre-cap base sat above the
    cap (so the `min` bit) AND the stored figure sits at or under the cap."""
    fired = []
    base = row["confidence_base"]
    for field in RECORDED_SIGNALS:
        cap = cap_table[field]
        if not _adverse(row[field], field):
            continue
        if base is not None and base > cap and row["confidence"] <= cap:
            fired.append(field)
    return fired


def test_tc_agg_c15_the_caps_count_per_cap_and_the_keys_stay_separate(tmp_data_dir):
    """`TC-AGG-C15` (`CT-AGG-15`, observe / rung 2, per-cap dimensionality
    differential, P0) — from stored rows alone, each hard cap's fired-count keys
    under its OWN name: a row capped by `spans_verified` counts there and
    nowhere else, a row capped by `ocr_overlap_risk` likewise, and a row both
    signals capped counts under both. A total-only counter would read 3 where
    the per-cap truth is {spans_verified: 2, ocr_overlap_risk: 2, rest: 0} — and
    "caps firing at an unusual rate on one criterion is an extraction problem
    wearing a confidence costume" is exactly the reading a total cannot support
    (RISK-01's second-best detector, retired silently by a merged counter)."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#91")

    store = open_store(tmp_data_dir)
    try:
        cohort = store.cohort(_COHORT)
        # One submission row per cell: the criterion_score row keys on the pair,
        # so the three cells of the ONE criterion are three submissions.
        seed_cohort(store, [f"{_SUBMISSION}-{key}" for key in ("A", "B", "C")])

        # Three rows for ONE criterion: spans-adverse, ocr-adverse, both —
        # identical panels otherwise, so the per-cap counts diverge only through
        # which signal was adverse.
        cells = {
            "A": aggregate(_UNANIMOUS_TOP, _FOUR_BAND,
                           signals(spans_verified=False), config=agg_config()),
            "B": aggregate(_UNANIMOUS_TOP, _FOUR_BAND,
                           signals(ocr_overlap_risk=True), config=agg_config()),
            "C": aggregate(_UNANIMOUS_TOP, _FOUR_BAND,
                           signals(spans_verified=False, ocr_overlap_risk=True),
                           config=agg_config()),
        }
        with cohort.transaction() as tx:
            for key, score in cells.items():
                tx.execute(
                    _INSERT,
                    sid=f"{_SUBMISSION}-{key}", cid=_CRITERION, band=score.band,
                    points=score.points, jc=score.judge_count,
                    agreement=score.agreement, state=score.state,
                    routing=score.routing, confidence=score.confidence,
                    confidence_base=score.confidence_base,
                    spans=score.spans_verified, evidence=score.evidence_present,
                    sufficiency=score.sufficiency_flag,
                    ocr=score.ocr_overlap_risk,
                )
        # The rows read back from the store — the derivation below may consult
        # NOTHING but these rows and the declared cap table.
        rows = cohort.query(
            "SELECT * FROM criterion_score WHERE criterion_id = :c ORDER BY "
            "submission_id", c=_CRITERION,
        )
        assert len(rows) == 3, "fixture bug: the per-cap cells did not store"

        fired_counts: dict[str, int] = {field: 0 for field in DESIGN_CAPS}
        for row in rows:
            for field in _caps_fired_from_row(row, dict(DESIGN_CAPS)):
                fired_counts[field] += 1

        assert fired_counts["spans_verified"] == 2, (
            f"the spans_verified cap's fired-count read "
            f"{fired_counts['spans_verified']} — rows A and C carry the adverse "
            "spans signal over a base the cap cut, and each must count under "
            "the spans key alone (CT-AGG-15's per-cap dimensionality)"
        )
        assert fired_counts["ocr_overlap_risk"] == 2, (
            f"the ocr_overlap_risk cap's fired-count read "
            f"{fired_counts['ocr_overlap_risk']} — rows B and C must count "
            "under the ocr key alone (CT-AGG-15's per-cap dimensionality)"
        )
        untouched = {field: count for field, count in fired_counts.items()
                     if field not in ("spans_verified", "ocr_overlap_risk")}
        assert untouched == {field: 0 for field in untouched}, (
            f"caps fired that no row's recorded signals were adverse on: "
            f"{untouched} — a cap whose count moves without its signal is not "
            "counting the row (CT-AGG-15)"
        )
        # The dimensionality the clause calls load-bearing: the four RECORDABLE
        # caps count separately. The two signals FR-AGG-13 does not record on
        # the row (`described_evidence`, `extractor_disagreement`) are the
        # design's disclosed residual — their fired-counts are NOT derivable
        # from the row, and this derivation claims only what the row carries.
        # (The derivation iterates RECORDED_SIGNALS by construction, so no
        # invented-key assertion here would be falsifiable.)
    finally:
        store.close()


def test_tc_agg_c15_the_rates_derive_per_criterion_from_the_ledger(
    tmp_data_dir, make_fixture_provider
):
    """`TC-AGG-C15` (`CT-AGG-15`, observe / rung 3, per-criterion rate figures,
    P0) — the auto-accept rate derives from the stored `routing` column per
    criterion, and the escalation rate from the escalation-origin units `M-ORCH`
    inserts — both keyed PER CRITERION, never in total: two criteria in one run,
    one escalated and one not, must read as two keys, because a criterion's
    extraction problem may not be its neighbour's."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#91")

    provider = make_fixture_provider()
    store = open_store(tmp_data_dir)
    try:
        # `holistic` criteria: the shipped enumeration's base depth for them is
        # 3 (`FR-SETUP-08`), so the drive judges a real three-judge panel per
        # criterion. The holistic threshold moves 0.90 → 0.80 — the shipped knob
        # TC-AGG-C14's second cell moves — because the holistic ceiling (1.0 ×
        # the 0.85 multiplier = 0.85) sits UNDER the 0.90 default and a favourable
        # panel would queue at the defaults; the differential below needs one
        # auto cell, and the knob is the declared instrument that places it.
        config = agg_config(auto_threshold_holistic=0.80)
        orchestrator, run_id, _ = drive_scored_run(
            store, provider,
            submissions=(_SUBMISSION,),
            criterion_specs=[
                {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic",
                 "band_count": 2},
                {"criterion_id": "C2", "kind": "open", "scoring_model": "holistic",
                 "band_count": 2},
            ],
        )
        crit1 = criterion(criterion_bands(store, "C1"), criterion_id="C1",
                          scoring_model="holistic")
        crit2 = criterion(criterion_bands(store, "C2"), criterion_id="C2",
                          scoring_model="holistic")
        # C1 aggregated UNFAVOURABLE (adverse spans signal caps it → queued);
        # C2 favourable (unanimous, auto): the two criteria's rates must
        # differ, and the difference must read per criterion.
        score1 = aggregate(stored_verdicts(store, run_id, _SUBMISSION, "C1"),
                           crit1, signals(spans_verified=False), config=config)
        score2 = aggregate(stored_verdicts(store, run_id, _SUBMISSION, "C2"),
                           crit2, signals(), config=config)
        assert score1.routing == "queued" and score2.routing == "auto", (
            f"fixture bug: the two cells routed {score1.routing!r}/{score2.routing!r} "
            "— the differential below would assert nothing"
        )

        cohort = store.cohort(_COHORT)
        with cohort.transaction() as tx:
            # C1 stored UNFAVOURABLE (queued — the adverse spans signal); C2
            # favourable (auto): the two criteria's auto-accept rates must
            # differ, per criterion.
            for cid, score in (("C1", score1), ("C2", score2)):
                tx.execute(
                    _INSERT, sid=_SUBMISSION, cid=cid, band=score.band,
                    points=score.points, jc=score.judge_count,
                    agreement=score.agreement, state=score.state,
                    routing=score.routing, confidence=score.confidence,
                    confidence_base=score.confidence_base,
                    spans=score.spans_verified, evidence=score.evidence_present,
                    sufficiency=score.sufficiency_flag, ocr=score.ocr_overlap_risk,
                )
            reports = orchestrator.enqueue_escalation(tx, (_SUBMISSION, "C1"))
        assert reports, (
            "fixture bug: the escalation for C1 did not enqueue, so the "
            "escalation rate below would have nothing to count"
        )

        # The rate figures, derived from the ledger alone, grouped per criterion.
        routing_rows = cohort.query(
            "SELECT criterion_id, routing FROM criterion_score"
        )
        by_criterion: dict[str, list[str]] = {}
        for row in routing_rows:
            by_criterion.setdefault(row["criterion_id"], []).append(row["routing"])
        auto_accept_rate = {
            cid: sum(1 for r in routings if r == "auto") / len(routings)
            for cid, routings in by_criterion.items()
        }
        assert auto_accept_rate == {"C1": 0.0, "C2": 1.0}, (
            f"the auto-accept rates read {auto_accept_rate!r} — the rate figure "
            "must derive from the stored routing column PER CRITERION "
            "(CT-AGG-15), not as one cohort-wide number"
        )

        escalations = cohort.query(
            "SELECT criterion_id, COUNT(*) AS n FROM work_unit WHERE run_id = :r "
            "AND origin = 'escalation' GROUP BY criterion_id",
            r=run_id,
        )
        escalation_counts = {row["criterion_id"]: row["n"] for row in escalations}
        assert escalation_counts == {"C1": 2}, (
            f"the escalation rate's basis read {escalation_counts!r} — the "
            "escalated criterion's units must count under C1 alone "
            "(CT-AGG-15's per-criterion dimensionality; TC-AGG-C08 proved the "
            "units land unconditionally)"
        )
    finally:
        store.close()
