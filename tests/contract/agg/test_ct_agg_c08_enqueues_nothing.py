"""`TC-AGG-C08` — the decision is a returned value; the widening is `M-ORCH`'s write (§6.11.12).

`CT-AGG-08`'s first two limbs — the per-signal sensitivity sweep over the six
observables, and the R22 invariance (self-confidence is one weighted input and never
the sole trigger) — are the shipped sibling
`tests/unit/agg/test_routing_and_escalation.py` (`TC-AGG-09`, #93):
`test_tc_agg_09_every_observable_signal_alone_moves_the_escalation_decision` and
`test_tc_agg_09_self_confidence_alone_cannot_flip_the_escalation_decision`. This file
does not repeat them; it carries the clause's boundary limbs, which no sibling runs:

- **the write audit** (the case's third oracle): `should_escalate`'s decision is
  *returned* — `aeh.agg` computes a value and enqueues nothing itself. Under
  `install_audit` over a real driven run, evaluating the whole pure surface over the
  run's stored verdict rows logs zero writes attributed to `aeh.agg`;
- **the composition** — the decision, handed back to `M-ORCH`, inserts the widened
  units **in the caller's transaction** (`CT-ORCH-08`, `CT-STORE-03` read across the
  boundary): the triggering result's `criterion_score` row and the escalation's units
  land in one transaction, the writes attributed to `aeh.orch` — the positive control
  that proves the audit was watching while the negative held.

The escalation trigger here is the override history (a criterion whose reviewed scores
were mostly overridden — `AGG_ESCALATION_OVERRIDE_RATE`'s strict more-than-half), with
every integrity signal favourable, so the decision's cause is unambiguous and the
composition reads `3 → 5` off the shipped ladder (`FR-AGG-09`: the next odd at least
two above the panel, never 2).

Isolation: rung 3 — real store, real workers, the real escalation plan; the socket
guard is autouse.
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.contract.agg._drive import (
    criterion_bands,
    drive_scored_run,
    stored_verdicts,
)
from tests.contract.orch._doubles import install_audit
from tests.support.agg_vocabulary import (
    criterion,
    criterion_history,
    expected_distribution,
    signals,
    agg_config,
)
from tests.support.impl import AGG_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID

pytestmark = [pytest.mark.contract]

_COHORT = ORCH_COHORT_ID
_SUBMISSION = "SYN-C08"
_CRITERION = "C1"

_INSERT = (
    "INSERT INTO criterion_score (submission_id, criterion_id, band, points, "
    "judge_count, agreement, state, routing, confidence, confidence_base, "
    "spans_verified, evidence_present, sufficiency_flag, ocr_overlap_risk) "
    "VALUES (:sid, :cid, :band, :points, :judge_count, :agreement, :state, "
    ":routing, :confidence, :confidence_base, :spans_verified, "
    ":evidence_present, :sufficiency_flag, :ocr_overlap_risk)"
)

#: The driven criterion, declared `holistic`: the shipped enumeration's base
#: depth for it is 3 (`FR-SETUP-08`), so the drive judges a real three-judge
#: panel — the panel the ladder below widens 3 → 5.
_CRITERION_SPECS = [{
    "criterion_id": _CRITERION, "kind": "open",
    "scoring_model": "holistic", "band_count": 2,
}]


def _driven(store, provider):
    """The driven run's real verdict rows and declared criterion, as the pure
    surface consumes them."""
    _, run_id, _ = drive_scored_run(
        store, provider, submissions=(_SUBMISSION,),
        criterion_specs=_CRITERION_SPECS,
    )
    rows = stored_verdicts(store, run_id, _SUBMISSION, _CRITERION)
    assert len(rows) == 3, (
        "precondition: the drive did not judge a three-judge panel, so the "
        "3 → 5 target below would not be the ladder's reading"
    )
    crit = criterion(criterion_bands(store, _CRITERION),
                     criterion_id=_CRITERION, scoring_model="holistic")
    return rows, crit


def test_tc_agg_c08_the_pure_surface_enqueues_nothing_under_a_write_audit(
    tmp_data_dir, make_fixture_provider
):
    """`TC-AGG-C08` (`CT-AGG-08`, contract / rung 3, write-audit log, P0) — with
    the audit installed over the real ledger, the whole pure surface — aggregate
    over the run's stored verdict rows, `should_escalate` over the resulting score
    with an escalating override history — logs zero writes attributed to
    `aeh.agg`. The decision is a returned value; a module that persisted it, or
    inserted a unit of its own, would surface here as an `aeh.agg` write."""
    aggregate, should_escalate = require(
        AGG_MODULE, "aggregate", "should_escalate", issue="#93"
    )

    provider = make_fixture_provider()
    store = open_store(tmp_data_dir)
    try:
        rows, crit = _driven(store, provider)
        # Audit installed AFTER the drive (the drive's own writes are M-ORCH's and
        # M-JUDGE's, not this clause's surface), BEFORE the pure surface runs.
        cohort_audit, durable_audit = install_audit(store, _COHORT)

        score = aggregate(rows, crit, signals(), config=agg_config())
        decision = should_escalate(
            score=score,
            criterion=crit,
            history=criterion_history(override_rate=0.6),
            baseline=expected_distribution(),
            config=agg_config(),
        )
        assert decision.escalate, (
            "fixture bug: the override-history trigger did not fire, so the audit "
            "below guards a surface no escalation path walked"
        )

        writes = cohort_audit.writes + durable_audit.writes
        offenders = [w for w in writes if w.module == "aeh.agg"]
        assert offenders == [], (
            f"the pure surface wrote {offenders} — `should_escalate` returns its "
            "decision to M-ORCH and enqueues nothing itself (CT-AGG-08); an "
            "aggregation that inserted units of its own would surface here"
        )
        assert writes == [], (
            f"evaluating the policy surface logged writes {writes} — the policy is "
            "pure even at rung 3: no store traffic at all on the decision path"
        )
    finally:
        store.close()


def test_tc_agg_c08_the_returned_decision_widens_in_the_callers_transaction(
    tmp_data_dir, make_fixture_provider
):
    """`TC-AGG-C08` (`CT-AGG-08` × `CT-ORCH-08`, contract / rung 3, composition,
    P0) — the decision, handed to M-ORCH: `enqueue_escalation` inserts the widened
    units inside the CALLER's transaction, the same one that writes the triggering
    `criterion_score` row — both present or both absent after any commit
    (`CT-STORE-03` across the boundary). The writes are attributed to `aeh.orch`
    (the positive control that the audit was watching), never to `aeh.agg`."""
    aggregate, should_escalate = require(
        AGG_MODULE, "aggregate", "should_escalate", issue="#93"
    )

    provider = make_fixture_provider()
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _ = drive_scored_run(
            store, provider, submissions=(_SUBMISSION,),
            criterion_specs=_CRITERION_SPECS,
        )
        rows = stored_verdicts(store, run_id, _SUBMISSION, _CRITERION)
        crit = criterion(criterion_bands(store, _CRITERION),
                         criterion_id=_CRITERION, scoring_model="holistic")
        cohort_audit, durable_audit = install_audit(store, _COHORT)

        score = aggregate(rows, crit, signals(), config=agg_config())
        decision = should_escalate(
            score=score,
            criterion=crit,
            history=criterion_history(override_rate=0.6),
            baseline=expected_distribution(),
            config=agg_config(),
        )
        assert decision.escalate, (
            "fixture bug: the trigger did not fire — the composition below would "
            "enqueue nothing and assert nothing"
        )
        assert decision.target_judge_count == 5, (
            f"the decision targets {decision.target_judge_count!r} judges from a "
            "three-judge panel — the ladder's next odd at least two above (3 → 5, "
            "never 2, FR-AGG-09)"
        )

        cohort = store.cohort(_COHORT)
        with cohort_audit.transaction() as tx:
            # The triggering result's write and the widening it triggers: one
            # transaction, the caller's — never two commits.
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
            reports = orchestrator.enqueue_escalation(tx, (_SUBMISSION, _CRITERION))
        assert reports, (
            "the enqueue returned no report — the pair's run was not resolved "
            "from the ledger, so the widening below would be vacuous"
        )

        stored_row = cohort.query(
            "SELECT routing FROM criterion_score WHERE submission_id = :s "
            "AND criterion_id = :c",
            s=_SUBMISSION, c=_CRITERION,
        )
        assert len(stored_row) == 1, (
            "the triggering result's row did not survive the transaction — the "
            "composition's first half is missing"
        )
        widened = cohort.query(
            "SELECT COUNT(*) AS n FROM work_unit WHERE run_id = :r AND "
            "submission_id = :s AND criterion_id = :c AND origin = 'escalation'",
            r=run_id, s=_SUBMISSION, c=_CRITERION,
        )[0]["n"]
        assert widened == 2, (
            f"{widened} escalation units landed for the pair — the 3 → 5 widening "
            "adds exactly two arms, inserted in the caller's transaction "
            "(CT-ORCH-08's shape; FR-AGG-09's ladder)"
        )

        writes = cohort_audit.writes + durable_audit.writes
        assert writes, (
            "the audit logged no writes at all — it was not watching, and the "
            "negative assertion below would be vacuous"
        )
        assert any(w.module == "aeh.orch" for w in writes), (
            f"the enqueue's writes are attributed {sorted({w.module for w in writes})} "
            "— the widening is M-ORCH's write, and the audit must see it for the "
            "exclusion below to mean anything (CT-AGG-08's positive control)"
        )
        offenders = [w for w in writes if w.module == "aeh.agg"]
        assert offenders == [], (
            f"the escalation path logged writes from aeh.agg: {offenders} — the "
            "aggregation enqueues nothing itself; the widening is M-ORCH's "
            "(CT-AGG-08)"
        )
    finally:
        store.close()
