"""`TC-ORCH-21` — a criterion holding two completed verdicts whose scoring unit keeps
failing: the retry comes first, no adjudication between two ever occurs, and the run
continues. Runs **green** against the shipped #58 surface — the failure taxonomy's
ladder is the retry mechanism the plan names.

The shipped unit model makes the scenario exact: one `stage = 'score'` unit per
(submission, criterion) — the panel is that unit's business, and its verdicts attach to
the unit's `work_id` one row per `judge_id`. A unit failing after two of its three panel
verdicts landed leaves a criterion holding two completed verdicts with the third still
to come — the state `FR-ORCH-26` legislates.

**The shipped sweep-2 gate is part of the scenario** (`FR-ORCH-06`, #59's two-sweep
plan): a score unit is ready only once its criterion's extraction is `done`. So the
criterion's extraction completes before its panel scoring is dispatched, and the run's
second criterion is left undispatched — which is what makes "the run continues" a
ledger fact rather than a status read: after the quarantine, the sibling criterion's
scoring unit is exactly what the run claims next.

`FR-ORCH-26`'s oracle is "exact value plus API assertion", and this file holds both
halves that live at the M-ORCH surface:

- **retry-first**: the failing scoring unit is requeued with its attempt count carried —
  a unit claimable again IS the third verdict being retried first, because while it sits
  queued no fallback has happened and none can: the claimable retry is the proof the
  orchestrator went back for the third verdict rather than settling;
- **no adjudication between two, at the API surface**: after the retry exhausts, the
  Orchestrator exposes **no** name containing "adjudic" — there is no entry point a
  caller could invoke to adjudicate a two-verdict criterion (R48: a tie broken by rule
  is a coin flip presented as a judgement), and the ledger confirms it: `criterion_score`
  holds no row, while both completed verdicts stand.

**Disclosed: the fallback's write half is not this file's.** "On failure the second
verdict is discarded and the base single-judge band is recorded as provisional" is
M-AGG's conditional write at aggregation time — the band writers are `M-JUDGE`/`M-AGG`,
and the discard-and-record belongs to `TC-AGG-12`'s case, not re-asserted here. What the
M-ORCH surface owes — the retry ladder, the preserved verdicts, the empty adjudication
target, the continuing run — is asserted exactly below.

**Disclosed: rung uplift 1 → 2.** The plan seats this case at rung 1; every other orch
integration case (the taxonomy, leasing, the pause matrix) runs against the real store,
and §4.2 forbids an in-memory stand-in for the store contract outright — a requeue an
in-memory fake "performs" proves nothing about the ledger's attempt arithmetic, which is
the ladder's load-bearing column. The case runs at rung 2, the stronger rung.

**Disclosed fixture bypass** (`orch_run.py`'s precedent): the two verdicts are INSERTed
directly — `verdict` is a shipped table and `M-JUDGE` does not exist yet, and the
scenario *requires* a criterion holding two completed verdicts. They attach to the
failing unit's `work_id` the way an in-flight execution's partial verdicts would; the
`judge_id`s are opaque strings (the shipped ledger records no ModelRef-to-id mapping to
read), and their distinctness is what carries "two of the panel's three".

Isolation: rung 2 — real store, real Tier P package, real cohort ledger, no doubles.
"""

from __future__ import annotations

import pytest

from aeh.orch import Orchestrator as OrchestratorClass
from aeh.orch import WorkError
from aeh.store import open_store
from tests.support.conf_builders import EDGE_PANEL_3
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

_SUBMISSIONS = ("SYN-001",)
_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
)


def _score_units(cohort, run_id: str) -> list[dict]:
    return cohort.query(
        "SELECT work_id, criterion_id, judge_id, status, attempts, last_error "
        "FROM work_unit WHERE run_id = :r AND stage = 'score' ORDER BY work_id",
        r=run_id,
    )


def test_tc_orch_21_a_two_verdict_criterion_retries_first_and_never_adjudicates(
    tmp_data_dir,
):
    """`TC-ORCH-21` (`FR-ORCH-26`, integration / rung 2, resilience, P0) — the scoring
    unit holds two of its panel's three verdicts and fails three times: requeued twice
    with its attempts carried, quarantined on the third with its last error; the two
    verdicts stand, no adjudication exists at the API surface or in the ledger, and the
    run continues."""
    store = open_store(tmp_data_dir)
    try:
        orch, run_id, _ = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA, panel=EDGE_PANEL_3
        )
        orch.enumerate_units(run_id)
        cohort = store.cohort(ORCH_COHORT_ID)

        units = _score_units(cohort, run_id)
        assert len(units) == 2 and {u["criterion_id"] for u in units} == {"C1", "C2"}, (
            f"the panel enumerated {len(units)} score units for two criteria — the "
            "shipped model is one unit per (submission, criterion) with the panel "
            "behind it, and a different shape voids the scenario's premise"
        )

        # Sweep 2 is gated on extraction (`FR-ORCH-06`): the panel scoring of a criterion
        # runs only once its extraction is done. Both criteria extract, both extractions
        # complete — and the gate is a premise, so it is verified, not assumed: had a
        # completion silently no-oped, the score claim below would starve and the ladder
        # would never start.
        extracts = orch.lease("worker-a", "extract", 10)
        assert len(extracts) == 2, (
            f"extraction leased {len(extracts)} of the run's 2 extract units — the "
            "scenario's scoring unit waits behind its criterion's extraction, and a "
            "short lease is a missing premise"
        )
        for extract_unit in extracts:
            orch.complete(extract_unit.work_id)
        done = cohort.query(
            "SELECT COUNT(*) AS n FROM work_unit WHERE run_id = :r "
            "AND stage = 'extract' AND status = 'done'",
            r=run_id,
        )[0]["n"]
        assert done == 2, (
            f"{done} of 2 extractions are done — the sweep-2 gate admits a score unit "
            "only over a done extraction, so an incomplete extraction would starve the "
            "ladder this case exists to walk"
        )

        # The panel scoring runs: the claim hands out the sweep order's head — one score
        # unit, its sibling still queued. Its in-flight execution lands two of the
        # panel's three verdicts before the malformed third response arrives.
        leased = orch.lease("worker-a", "score", 1)
        assert len(leased) == 1, (
            f"the score claim handed out {len(leased)} units — the sweep order's head "
            "is one unit, and a different shape voids the retry-first oracle below"
        )
        victim = leased[0]
        work_id = victim.work_id
        criterion_id = victim.criterion_id
        sibling = [u for u in units if u["criterion_id"] != criterion_id][0]

        with cohort.transaction() as tx:
            for judge_id, verdict_id, band in (
                ("judge-base", "v-base", "A"),
                ("judge-second", "v-second", "B"),
            ):
                tx.execute(
                    "INSERT INTO verdict (verdict_id, work_id, judge_id, band) "
                    "VALUES (:v, :w, :j, :b)",
                    v=verdict_id,
                    w=work_id,
                    j=judge_id,
                    b=band,
                )

        error = WorkError(message="malformed model output: no band in response")

        # Retry-first: the failing unit is requeued with its attempt count carried, and
        # it is the scoring work the run claims again — the third verdict is retried
        # before anything else happens to the criterion, ahead of even the sibling
        # criterion's ready scoring unit.
        for expected_attempts in (1, 2):
            orch.fail(work_id, error)
            row = cohort.query(
                "SELECT status, attempts FROM work_unit WHERE work_id = :w", w=work_id
            )[0]
            assert row["status"] == "pending", (
                f"after failure {expected_attempts} the unit is '{row['status']}', not "
                "'pending' — below the ceiling the third verdict is retried, not "
                "abandoned (FR-ORCH-26)"
            )
            assert row["attempts"] == expected_attempts, (
                f"attempt count is {row['attempts']}, expected {expected_attempts} — "
                "the attempt history is what makes the ladder exact"
            )
            reclaimed = orch.lease("worker-a", "score", 1)
            assert [u.work_id for u in reclaimed] == [work_id], (
                f"after failure {expected_attempts} the run claimed "
                f"{[u.work_id for u in reclaimed]!r} — the retry comes FIRST: the "
                "requeued third verdict is the claim's head, ahead of the sibling "
                "criterion's ready scoring unit, or the orchestrator went around the "
                "criterion instead of back to it"
            )

        # The retry fails a third time: quarantined, last error retained, attempts exact.
        orch.fail(work_id, error)
        row = cohort.query(
            "SELECT status, attempts, last_error FROM work_unit WHERE work_id = :w",
            w=work_id,
        )[0]
        assert row["status"] == "quarantined", (
            f"a unit at the attempt ceiling is '{row['status']}', not 'quarantined' — "
            "the ladder's third rung is quarantine, not another requeue"
        )
        assert row["attempts"] == 3
        assert row["last_error"], (
            "the quarantined unit retained no last_error — the operator surface can "
            "say WHAT happened, not just that something did"
        )

        # Exact final state: the unit quarantined with BOTH its completed verdicts
        # still standing (the discard is M-AGG's conditional act at aggregation time —
        # TC-AGG-12's case — and the orchestrator's ladder left them untouched).
        verdicts = cohort.query(
            "SELECT verdict_id, judge_id, band FROM verdict WHERE work_id = :w "
            "ORDER BY verdict_id",
            w=work_id,
        )
        assert [v["band"] for v in verdicts] == ["A", "B"] and len(verdicts) == 2, (
            f"the criterion holds {len(verdicts)} verdicts after the quarantine — both "
            "completed verdicts stand until aggregation discards one (the fallback's "
            "write half is TC-AGG-12's, and the ledger here must be exactly as the "
            "ladder left it)"
        )

        # No adjudication between two ever occurs — asserted at the API surface: the
        # Orchestrator offers no entry point whose name admits adjudicating.
        offenders = [
            name for name in dir(OrchestratorClass)
            if "adjudic" in name.lower() and not name.startswith("__")
        ]
        assert not offenders, (
            f"the Orchestrator surface exposes {offenders!r} — 'no adjudication "
            "between two ever occurs' is asserted at the API surface, and a callable "
            "named for it is that path"
        )
        # ...and in the ledger: no criterion of this run has an adjudicated row.
        assert not cohort.query("SELECT 1 FROM criterion_score LIMIT 1"), (
            "criterion_score holds a row for a run whose only scored criterion "
            "quarantined with two verdicts standing — an adjudication between two is a "
            "coin flip presented as a judgement (R48)"
        )

        # The run continues: the sibling criterion's scoring unit is exactly what the
        # run claims next — the failure was the unit's, never the run's.
        still_open = orch.lease("worker-a", "score", 10)
        assert [u.work_id for u in still_open] == [sibling["work_id"]], (
            f"after the quarantine the run claimed "
            f"{[u.work_id for u in still_open]!r}, expected the sibling criterion's "
            "scoring unit — a scoring failure parks its own unit, never the run "
            "(FR-ORCH-26: the run continues)"
        )
    finally:
        store.close()
