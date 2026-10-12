"""`TC-CONSOLE-69` (issue #771, FR-CONSOLE-47) — the parked read and the resolve action
that backs it.

| Arm | Expected |
|---|---|
| (a) two parked papers, one matched, one unmatched | the read mirrors the quarantine rows exactly — count, reasons, the student each paper matched (or why it could not), the resolutions each status offers — counted as the ledger holds them |
| (b) resolve a paper as unresolvable | the outcome is the existing quarantine resolution's sentence, the parked read loses the paper, and the store row carries the terminal state (`incomplete`, unflagged) |
| (c) resolve a paper by match | the release is the operator's decision recorded, the parked read empties, and the store row reads `ok` |

The park is written the way `M-INGEST` writes it (the `ingest_status` / `quarantined`
columns); the mirror assertion reads those rows directly, the oracle side.

**Isolation: rung 3 (E1)** — a real store, a real console on a real loopback socket; the
read and the actions taken over the console's own HTTP surface.
"""

from __future__ import annotations

import pytest

import aeh.agg  # noqa: F401 — the full migration chain before the first store open (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from tests.support.console_redesign_world import (
    _action,
    _get_json,
    served_console,
)
from tests.support.console_world import seed_scored_run

pytestmark = pytest.mark.integration

COHORT = "c-pk"
RUN = "r-pk"
PACKAGE = "pkg-pk"
MATCHED = "sub-c-pk-01"
UNMATCHED = "sub-c-pk-02"

UNREADABLE_RESOLUTIONS = (
    "Scan the paper again, more clearly, and upload it in place of this one.",
    "Mark the paper unresolvable if no better scan exists.",
)
UNMATCHED_RESOLUTIONS = (
    "Check the class list names the student whose paper this is.",
    "Mark the paper unresolvable if it belongs to no one on the list.",
)


def _seed_park(store) -> None:
    """One scored run, two of whose papers are parked the way `M-INGEST` parks them: one
    unreadable but matched to its student, one unmatched with the identity evidence kept."""
    seed_scored_run(store, cohort_id=COHORT, run_id=RUN, package_id=PACKAGE,
                    submissions=2, finalize=True)
    with store.cohort(COHORT).transaction() as tx:
        tx.execute(
            "UPDATE submission SET quarantined = 1, ingest_status = 'unreadable', "
            "v3_identity = 'pass' WHERE submission_id = :s",
            s=MATCHED,
        )
        # The V4-mismatch shape: the student matched (v3 passed), the answer sheet did
        # not — the student_ref stands, the assessment diagnosis is what parked it.
        tx.execute(
            "UPDATE submission SET quarantined = 1, ingest_status = "
            "'unmatched_assessment', v3_identity = 'pass' WHERE submission_id = :s",
            s=UNMATCHED,
        )


def _parked_by_id(port: int) -> dict[str, dict]:
    return {row["submission_id"]: row for row in
            _get_json(port, "/api/v1/parked")["parked"]}


def test_tc_console_69a_the_parked_read_mirrors_the_quarantine_rows(served_console):
    """Every parked entry is the quarantine row's mirror — count, reason, reason label,
    the match or its absence, and the resolutions the status offers."""
    _server, port, store, _data_dir = served_console
    _seed_park(store)
    ledger_rows = [dict(row) for row in store.cohort(COHORT).query(
        "SELECT submission_id, ingest_status FROM submission WHERE quarantined = 1 "
        "ORDER BY submission_id")]
    assert len(ledger_rows) == 2, f"the seed parked {len(ledger_rows)} paper(s)"

    payload = _get_json(port, "/api/v1/parked")

    assert payload["counts"] == {
        "total": 2, "by_reason": {"unreadable": 1, "unmatched_assessment": 1},
    }, f"the read counted {payload['counts']}"
    assert [(row["submission_id"], row["reason"]) for row in payload["parked"]] == [
        (row["submission_id"], row["ingest_status"]) for row in ledger_rows], (
        "the read's rows do not mirror the ledger's quarantine rows")

    parked = _parked_by_id(port)
    matched = parked[MATCHED]
    assert matched["cohort_id"] == COHORT
    assert matched["reason_label"] == "Could not be read"
    assert matched["matched_student"] == f"ref-{MATCHED}"
    assert matched["match_note"] == f"The paper matched ref-{MATCHED}."
    assert matched["resolutions"] == list(UNREADABLE_RESOLUTIONS)
    assert matched["resolvable"] is True

    unmatched = parked[UNMATCHED]
    assert unmatched["reason_label"] == "Doesn't match the class list"
    assert unmatched["matched_student"] == f"ref-{UNMATCHED}", (
        "the V4-mismatch paper matched its student; the assessment is what failed")
    assert unmatched["match_note"] == f"The paper matched ref-{UNMATCHED}."
    assert unmatched["resolutions"] == list(UNMATCHED_RESOLUTIONS)
    assert unmatched["resolvable"] is True


def test_tc_console_69b_closing_a_paper_as_unresolvable_runs_the_existing_resolution(
        served_console):
    """The unresolvable close: the shipped sentence, the paper gone from the parked read,
    and the terminal state in the store row."""
    _server, port, store, _data_dir = served_console
    _seed_park(store)

    answer = _action(port, "resolve quarantine item", {
        "submission_id": UNMATCHED, "resolution": "unresolvable",
    })

    assert answer["dispatched"] is True, answer["detail"]
    assert answer["refused"] is False
    assert answer["detail"] == (
        f"submission {UNMATCHED} closed as unresolvable: criteria MISSING, grade "
        "INCOMPLETE — never zero (M-GRADE computes the missing-criteria rule over "
        "criteria that were never scored)"), answer["detail"]

    parked = _parked_by_id(port)
    assert UNMATCHED not in parked, "the closed paper still reads as parked"
    assert set(parked) == {MATCHED}
    row = [dict(r) for r in store.cohort(COHORT).query(
        "SELECT ingest_status, quarantined FROM submission "
        "WHERE submission_id = :s", s=UNMATCHED)][0]
    assert row == {"ingest_status": "incomplete", "quarantined": 0}, (
        f"the store row after the close is {row}; the close writes the terminal "
        "state and clears the flag")


def test_tc_console_69c_releasing_a_matched_paper_records_the_operators_decision(
        served_console):
    """The matched release: the operator's decision recorded — never an automatic one —
    and the store row reads `ok`."""
    _server, port, store, _data_dir = served_console
    _seed_park(store)

    answer = _action(port, "resolve quarantine item", {
        "submission_id": MATCHED, "resolution": "matched",
    })

    assert answer["dispatched"] is True, answer["detail"]
    assert answer["detail"] == (
        f"submission {MATCHED} released by the operator's match; the console wrote "
        "the operator's decision, never an automatic one"), answer["detail"]

    parked = _parked_by_id(port)
    assert MATCHED not in parked, "the released paper still reads as parked"
    assert set(parked) == {UNMATCHED}, (
        f"the read's remaining rows are {sorted(parked)}; only the released paper "
        "may have left the park")
    payload = _get_json(port, "/api/v1/parked")
    assert payload["counts"]["total"] == 1
    row = [dict(r) for r in store.cohort(COHORT).query(
        "SELECT ingest_status, quarantined FROM submission "
        "WHERE submission_id = :s", s=MATCHED)][0]
    assert row == {"ingest_status": "ok", "quarantined": 0}
