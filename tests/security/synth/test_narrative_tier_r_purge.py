"""`TC-SYNTH-11` — narratives are Tier R: purged with the cohort, never promoted
verbatim (`M-SYNTH`, TS-37, P0, security, rung 2).

NFR-SYNTH-04: narratives are student PII; they live in Tier R and are purged with it,
with only cited spans promoted to the audit record. The oracle is **post-purge
absence**: a full synthesis run's narrative rows must be gone after `purge_cohort`,
which both proves they lived in Tier R (the purge deletes Tiers C and R and nothing
else) and proves the store does not quietly retain a copy a later reader could reach.
The promotion half is the negative: the audit record that survives in Tier D must not
carry the narrative's text — a survival-of-prose in the permanent tier is a PII leak
that outlives every deletion mechanism built to remove it (CT-STORE-09's rule, applied
to the one artifact this module writes).

Isolation: rung 2 — real SQLite, the capture provider at the model boundary. The Tier D
promotion gates are given through the same independent-connection mechanics
`test_tc_store_11` uses (an `audit_record` row cohort-scoped, the shipped
`purge_cohort` precondition), because the promotion write is `M-STORE`'s and this
case's subject is where the narrative lives — not re-testing the gates.

Interface assumed of `#97` (disclosed in `tests/support/synth_vocabulary.py`, reconcile
at landing): `SynthesisWorker(store, provider, model_ref)` with
`.synthesize_submission(...)`; narrative rows in the cohort database carrying `text`.
"""

from __future__ import annotations

import sqlite3

import pytest

from aeh.store import open_store
from tests.support.impl import SYNTH_MODULE, require
from tests.support.orch_run import seed_run
from tests.support.synth_vocabulary import (
    COHORT_ID,
    FIVE_QUESTION_CRITERIA,
    SYNTH_ISSUE,
    WORKER,
    CaptureProvider,
    narrative_completion,
    seed_scored_submission,
    synth_ref,
)

pytestmark = [pytest.mark.integration]

_SUBMISSION = "SYN-001"
_QUESTIONS = tuple(f"Q{q}" for q in range(1, 6))
#: The distinctive prose the run stores — what must NOT survive in Tier D.
_NARRATIVE_TEXTS = tuple(
    [f"Question {q[1:]}: the response states the hypothesis and cites the worked "
     f"steps for this question." for q in _QUESTIONS]
    + ["Overall: the submission works through each question in turn."]
)

PROMOTE_DDL = (
    "ALTER TABLE audit_record ADD COLUMN cohort_id TEXT",
    "ALTER TABLE label ADD COLUMN cohort_id TEXT",
    "ALTER TABLE criterion_stats ADD COLUMN cohort_id TEXT",
)


def _promote(store, cohort_id: str) -> None:
    """Give Tier D the three promotion gates, through an independent connection —
    the `test_tc_store_11` mechanics, verbatim in shape."""
    store.durable()
    with sqlite3.connect(store.durable_path()) as raw:
        for ddl in PROMOTE_DDL:
            try:
                raw.execute(ddl)
            except sqlite3.OperationalError as error:
                if "duplicate column" not in str(error).lower():
                    raise
        raw.execute(
            "INSERT INTO audit_record (audit_record_id, run_id, recorded_at, "
            "profile_summary, cohort_id) VALUES (?, ?, 't', 'p', ?)",
            (f"a-{cohort_id}", "run-1", cohort_id),
        )
        raw.execute(
            "INSERT INTO label (label_id, run_id, student_ref, criterion_id, "
            "label_type, band, cohort_id) VALUES (?, 'run-1', 'ref-1', 'CRIT-1', "
            "'human', 'b1', ?)",
            (f"l-{cohort_id}", cohort_id),
        )
        raw.execute(
            "INSERT INTO criterion_stats (package_version_id, criterion_id, "
            "backend_profile, panel_build_ref, n, cohort_id) VALUES (?, 'c', 'bp', ?, 5, ?)",
            (f"pv-{cohort_id}", f"pb-{cohort_id}", cohort_id),
        )


def test_tc_synth_11_narratives_live_in_tier_r_and_purge_removes_them(tmp_data_dir):
    """`TC-SYNTH-11` (P0, security) — the run's narratives exist, the audit record is
    promoted, the cohort is purged: the narratives are gone, the audit record is not,
    and the audit record carries none of the narrative's prose."""
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)

    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = seed_run(store, submissions=(_SUBMISSION,), criteria=FIVE_QUESTION_CRITERIA)
        seed_scored_submission(store, run_id, _SUBMISSION, complete_questions=set(_QUESTIONS))
        replies = [
            narrative_completion(text, (f"{q}C1", f"{q}C2"))
            for q, text in zip(_QUESTIONS, _NARRATIVE_TEXTS[:5], strict=True)
        ] + [narrative_completion(_NARRATIVE_TEXTS[5])]
        Worker(store, CaptureProvider(replies), synth_ref()).synthesize_submission(
            run_id, _SUBMISSION
        )

        before = store.cohort(COHORT_ID).query(
            "SELECT COUNT(*) AS n FROM narrative WHERE run_id = :r", r=run_id
        )
        assert before[0]["n"] == 6, (
            f"{before[0]['n']} narrative rows before the purge — the fixture must "
            "store the run's prose before asserting on its absence"
        )

        _promote(store, COHORT_ID)
        store.purge_cohort(COHORT_ID)
    finally:
        store.close()

    # Post-purge absence, read from a store reopened over the same data directory —
    # the purge evicts and empties the cohort file, so the read must be a fresh one.
    store = open_store(tmp_data_dir)
    try:
        after = store.cohort(COHORT_ID).query(
            "SELECT COUNT(*) AS n FROM narrative WHERE run_id = :r", r=run_id
        )
        assert after[0]["n"] == 0, (
            f"{after[0]['n']} narrative rows survive the cohort purge — NFR-SYNTH-04: "
            "narratives are student PII living in Tier R and are purged with it; a "
            "surviving narrative is PII that outlived every deletion mechanism built "
            "to remove it"
        )

        # Only cited spans are promoted: the surviving audit record must not carry
        # the narrative's prose. Any column value holding a stored narrative's own
        # words is the permanent-tier copy the purge can never reach.
        audit_rows = store.durable().query(
            "SELECT * FROM audit_record WHERE cohort_id = :c", c=COHORT_ID
        )
        assert audit_rows, (
            "no audit record survived the purge — promotion to Tier D is the "
            "precondition the purge demands, and it must survive what Tier R does not"
        )
        for row in audit_rows:
            for value in tuple(row):
                text = value.decode("utf-8", "ignore") if isinstance(value, bytes) else str(value)
                for narrative in _NARRATIVE_TEXTS:
                    assert narrative not in text, (
                        f"the surviving audit record carries narrative prose "
                        f"({narrative[:40]!r}...) — NFR-SYNTH-04 promotes only cited "
                        "spans to the audit record; a verbatim copy in Tier D is the "
                        "second, undeletable store of student work CT-STORE-09 forbids"
                    )
    finally:
        store.close()
