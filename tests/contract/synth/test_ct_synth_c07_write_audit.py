"""`TC-SYNTH-C07` — this module writes `narrative` and nothing else (§6.11.13).

`CT-SYNTH-07`'s state clause at rung 3, the half no shipped TC holds: with the write
audit installed after the fixture's disclosed seeding and the real two-level driver
running — five L1 compositions and the L2 one, each read assembled from score
units, verdicts, evidence and documents — every write the log records came from
`aeh.synth`, went to the `narrative` table, and is the module's own declared
`insert_narrative` statement, byte-for-byte. A write from the wrong module, or to
`criterion_score`/`submission_grade`, is the two write sets merging — the failure
`CT-AGG-11` observes from the other side and this clause from this one (§7.2 Rule
3, RISK-19); a write-ownership violation is silent by construction (a write from the
wrong module is a legal row), so the writer SET, not the rows, is the case.

The prohibition's static half — **no write path** to `criterion_score` or
`submission_grade`, asserted so it holds for unexercised paths — is
`tests/artifact/test_agg_synth_write_sets.py`'s (`TC-AGG-16`), which pins the
narrative writers ⊆ `{store.py, synth.py}` by AST over every `Statement` in the
tree. This case does not re-spell it: the reciprocal clauses and both cases stay
because each observes one direction of the merge, and the direction this case adds
is the live one — the audited drive proving the worker that ran wrote ITS table and
nothing else.

Reads are recorded and unrestricted: the drive's reads come from `aeh.synth`'s own
frames, and sole-writership is a claim about who writes.

Isolation: rung 3 — real store, real package, the real two-level driver over the
capture provider, and the write audit (`tests/contract/synth/_doubles.py`, the orch
suite's instrument re-exported) observing the cohort tier.
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.contract.synth._doubles import install_audit
from tests.support.orch_run import seed_run
from tests.support.synth_vocabulary import (
    COHORT_ID,
    FIVE_QUESTION_CRITERIA,
    WORKER,
    CaptureProvider,
    narrative_completion,
    seed_scored_submission,
    synth_ref,
)

pytestmark = [pytest.mark.contract]

_SUBMISSION = "SYN-001"
_QUESTIONS = tuple(f"Q{q}" for q in range(1, 6))


def _replies() -> list:
    replies = [
        narrative_completion(
            f"Question {q[1:]}: the response states the hypothesis and cites the "
            "worked steps for this question.",
            (f"{q}C1", f"{q}C2"),
        )
        for q in _QUESTIONS
    ]
    replies.append(narrative_completion("Overall: the submission works through each question in turn."))
    return replies


def test_tc_synth_c07_the_driver_writes_narrative_and_nothing_else(tmp_data_dir):
    """`TC-SYNTH-C07` (P0) — under the audited drive, every write is `aeh.synth`'s
    declared narrative insert: one writer, one table, one statement."""
    from tests.support.impl import SYNTH_MODULE, require

    Synth = require(SYNTH_MODULE, "SYNTH_STATEMENTS", WORKER, issue="#97")
    SynthStatements, Worker = Synth

    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = seed_run(
            store, submissions=(_SUBMISSION,), criteria=FIVE_QUESTION_CRITERIA
        )
        seed_scored_submission(store, run_id, _SUBMISSION, complete_questions=set(_QUESTIONS))

        # The audit installs AFTER the fixture's disclosed seeding and BEFORE the
        # first production statement — the log holds only what the drive wrote
        # (the TC-ORCH-C17 mechanics).
        cohort_audit, _durable_audit = install_audit(store, COHORT_ID)

        report = Worker(store, CaptureProvider(_replies()), synth_ref()).synthesize_submission(
            run_id, _SUBMISSION
        )
        assert report.narratives == 6 and report.failures == 0, (
            f"the audited drive stored {report.narratives} narratives with "
            f"{report.failures} failures — a partial drive would excuse whichever "
            "composition never ran, so the writership claim below would be asserted "
            "from nothing"
        )

        writes = cohort_audit.writes
        assert writes, (
            "the audit recorded no write at all — the drive stored six narratives, "
            "so an empty log means the audit never saw the worker"
        )
        modules = {write.module for write in writes}
        assert modules == {"aeh.synth"}, (
            f"the drive's writes came from {sorted(modules)} — CT-SYNTH-07: this "
            "module writes `narrative` and nothing else; a write from any other "
            "module during the drive is the write set merging, and it is silent by "
            "construction because a write from the wrong module is a legal row"
        )
        tables = {write.table for write in writes}
        assert tables == {"narrative"}, (
            f"the drive wrote {sorted(tables)} — `narrative` alone: no write path "
            "reaches `criterion_score` or `submission_grade` from the synthesis "
            "worker (RISK-19's second competing grade arrives through exactly such "
            "a write)"
        )
        assert len(writes) == 6, (
            f"{len(writes)} writes for six narratives — one insert per stored row, "
            "no retry duplicate, no shadow write"
        )

        # Every write is the module's own declared statement, byte-for-byte — not a
        # hand-assembled SQL twin a second code path could drift from.
        insert_sql = " ".join(SynthStatements["insert_narrative"].sql.split())
        for write in writes:
            assert write.sql == insert_sql, (
                f"aeh.synth wrote narrative with {write.sql[:80]!r} — the driver's "
                "ONLY write is the declared insert_narrative statement; any other "
                "statement (an update, a delete, a second insert shape) is an "
                "undeclared write path (CT-SYNTH-07, FR-STORE-08)"
            )

        # Reads are unrestricted and visible: the drive's reads come from the
        # worker's own frames.
        reader_modules = {module for module, _ in cohort_audit.reads}
        assert "aeh.synth" in reader_modules, (
            f"the read log holds only {reader_modules} — the drive's reads never "
            "appeared, so the audit would not catch a write sneaking in beside them"
        )
    finally:
        store.close()
