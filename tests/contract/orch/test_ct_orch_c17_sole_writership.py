"""`TC-ORCH-C17` — sole writership of the run ledger, under a full dispatch (§6.11.7).

`CT-ORCH-17`'s state clause at rung 3: with the write audit installed and EVERY
worker running — the extraction worker's persist, the scoring workers' persists,
and the dispatch loop itself (the deterministic walk, the judged batch over the
transport seam, the pass-end metrics flush) — the write log is grouped by module
and read back:

- **`run` and `run_metrics` have exactly one writer: `aeh.orch`.** A second writer for
  a table that has exactly one is the *obvious convenience* RISK-38 names — a stats
  module incrementing a counter, a console flipping a status — each destroying the
  separation the design is built on. Write-ownership violations are silent by
  construction (a write from the wrong module is a legal row), so the negative half —
  the writer SET, not the rows — is the case.
- **`work_unit`'s writers are `aeh.orch` plus the two stage workers' reconciled
  boundary, and nothing else.** `aeh.extract` and `aeh.judge` execute exactly one
  ledger statement each — the shared `ORCH_STATEMENTS["mark_done"]` inside their own
  persist transactions (the completion a worker records for the unit it just
  finished). The case asserts the boundary positively (both workers' `mark_done`
  writes appear) and negatively (a non-orchestrator write to `work_unit` is that
  statement, byte-for-byte — no insert, no lease transition, no status a worker
  invented).
- **Reads are unrestricted**: the log records reads from the workers' own modules —
  sole-writership is a claim about who writes, and a read gate would break the
  console's statelessness (`CT-CONSOLE-01`'s headless poll reads everything).

Relationship to shipped cases, disclosed: `tests/contract/console/
test_ct_console_statelessness_and_writes.py` (M-CONSOLE, standing behind #122) holds
the console half of this clause — every progress view is a ledger read, and
`test_tc_console_c01_killing_the_console_process_leaves_the_run_and_its_queued_rows_intact`
is the kill-the-console differential the plan names. M-STATS's and M-DET's writes to
their own tables (`stats`, `criterion_score`) are their suites' ground; this case's
surface is the three ledger tables, and the drive proves a worker writing ITS table
wrote nothing of the ledger's.

Isolation: rung 3 — real store, real package, real documents, the real extraction
and scoring workers over the recorded fixture provider, and the dispatch loop's own
model calls through the transport seam the dispatch pass binds
(`Orchestrator(store, transport=...)`), so every worker that writes the ledger
writes it for real.
"""

from __future__ import annotations

import pytest

from aeh.extract import ExtractionWorker
from aeh.extract import assemble_request, prompt_fields
from aeh.judge import ScoringWorker
from aeh.judge import prompt_fields as judge_prompt_fields
from aeh.orch import ORCH_STATEMENTS, STAGE_EXTRACT, STAGE_SCORE, Orchestrator
from aeh.pkg import PackageCatalog
from aeh.prov import Completion
from aeh.store import open_store
from tests.contract.orch._doubles import install_audit
from tests.support.conf_builders import EDGE_JUDGE, EDGE_JUDGE_2, EDGE_JUDGE_3
from tests.support.extract_vocabulary import (
    extractor_ref,
    sampling_params,
    span_completion,
    verdict_completion,
)
from tests.support.orch_run import (
    ORCH_COHORT_ID,
    PLAIN_TRANSCRIPT,
    seed_document,
    seed_run,
)

pytestmark = [pytest.mark.contract]

_SUBMISSIONS = ("SYN-001", "SYN-002")

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic",
     "band_count": 2},
    {"criterion_id": "C2", "kind": "mcq"},
)

_WORKER = "w-c17"

_NEEDLE = "The evidence supports the conclusion"

_PANEL_REFS = (EDGE_JUDGE, EDGE_JUDGE_2, EDGE_JUDGE_3)


class _Seam:
    """The transport the dispatch pass binds: every model call recorded, one
    completion back — the shipped metrics case's seam shape."""

    def __init__(self) -> None:
        self.calls = 0

    def call(self, request: object) -> Completion:
        self.calls += 1
        return Completion(
            text="synthetic band: B",
            tokens_in=3,
            tokens_out=2,
            latency_ms=1,
            resolved_build="build-ct-c17-seam",
            cached_prefix_tokens=0,
            cost=None,
        )


def _spans() -> list[dict[str, object]]:
    start = PLAIN_TRANSCRIPT.find(_NEEDLE)
    assert start >= 0, "fixture bug: the span needle is not in the transcript"
    return [{"start": start, "end": start + len(_NEEDLE), "text": _NEEDLE}]


def _banded_package(store, version, criterion_id):
    """The criterion's REAL band set, through the shipped catalog API — the judged
    parse below needs a legal band to land in (two bands, A and B, points
    non-decreasing in ordinal per FR-PKG-06)."""
    catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
    catalog.add_band(version, criterion_id, 0, "A", 2.0, "adequate")
    catalog.add_band(version, criterion_id, 1, "B", 4.0, "excellent")


def _drive_extract(orchestrator, store, provider, run_id):
    """Lease and process every extract unit of the run through the real worker."""
    worker_ref = extractor_ref()
    worker = ExtractionWorker(store, provider, worker_ref)
    while True:
        batch = orchestrator.lease(_WORKER, STAGE_EXTRACT, 8)
        if not batch:
            break
        for unit in batch:
            request = assemble_request(unit, store=store)
            provider.record(
                prompt_fields(request),
                worker_ref,
                sampling_params(),
                span_completion(_spans(), build_id="build-ct-c17"),
            )
            worker.process(unit)


def _score_all(orchestrator, store, provider, run_id):
    """Drive every base score unit through the real scoring workers.

    Each verdict's persist marks its unit done, so the edge-local residency gate
    never stalls on a judge's unfinished batch across the loop's lease calls; the
    escalation's widened units do not exist yet (the enqueue follows this drive)
    and ride the dispatch loop's own judged batch instead.
    """
    refs_by_build = {ref.build_id: ref for ref in _PANEL_REFS}
    for _ in range(32):
        batch = orchestrator.lease(_WORKER, STAGE_SCORE, 8)
        if not batch:
            break
        for unit in batch:
            judge_ref = refs_by_build[unit.judge]
            judge_worker = ScoringWorker(store, provider, judge_ref)
            request = judge_worker.assemble(unit)
            provider.record(
                judge_prompt_fields(request),
                judge_ref,
                sampling_params(),
                verdict_completion("B", 0.9, build_id="build-ct-c17"),
            )
            result = judge_worker.dispatch(request, judge_ref)
            assert result.band == "B", (
                "precondition: the judge's reply was not the verdict the fixture "
                "recorded"
            )
            judge_worker.persist(unit, result)


def test_tc_orch_c17_sole_writership_of_the_run_ledger_under_a_full_dispatch(
    tmp_data_dir, make_fixture_provider, monkeypatch
):
    """The write audit over a real dispatch with every worker running: the writer set
    of `run`/`run_metrics` is exactly `aeh.orch`, while `work_unit`'s extra writers
    are the two stages' shared `mark_done` and nothing else — reads flow
    unrestricted."""
    # The run-wide escalation budget is TC-ORCH-C16's subject; here the 0.30
    # default would defer the escalated pair's widened judges mid-drain and hold
    # the run open for budget reasons the writership clause does not name.
    monkeypatch.setenv("HARNESS_ORCH_ESCALATION_BUDGET", "1.0")
    seam = _Seam()
    provider = make_fixture_provider()
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, version = seed_run(
            store, submissions=_SUBMISSIONS,
            criteria=_CRITERIA, transport=seam,
        )
        _banded_package(store, version, "C1")
        for submission_id in _SUBMISSIONS:
            seed_document(store, submission_id)

        # The audit installs AFTER the fixture's disclosed seeding and BEFORE the
        # first production statement — the log holds only what the run wrote.
        cohort_audit, durable_audit = install_audit(store, ORCH_COHORT_ID)

        orchestrator.enumerate_units(run_id)
        assert orchestrator.start(run_id) == "running"

        # Every worker runs, on the ledger the audit watches: the extraction
        # worker processes the extract stage, the scoring workers process the
        # base panels, and the escalation's widened batch rides the dispatch
        # loop itself — transport-bound `progress()` passes whose judged batch
        # claims the widened units through the seam, whose deterministic walk
        # completes the mcq units, and whose pass-end flush writes run_metrics.
        _drive_extract(orchestrator, store, provider, run_id)
        _score_all(orchestrator, store, provider, run_id)
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            orchestrator.enqueue_escalation(tx, ("SYN-001", "C1"))
        report = orchestrator.progress(run_id)
        for _ in range(64):
            if report.complete:
                break
            report = orchestrator.progress(run_id)
        assert report.complete, (
            "the audited dispatch never exhausted the run — a writership audit over "
            "a partial drive would excuse whichever worker never ran"
        )
        assert seam.calls >= 1, (
            "precondition: the dispatch pass's own judged batch made no model call "
            "— the escalation's widened units never rode the transport, so the "
            "audit would not cover the dispatch loop's writes"
        )

        def _writers_for(audit, table):
            return {
                w.module for w in audit.writes if w.table == table
            }

        # The run row: born in the fixture, transitioned ONLY by the orchestrator.
        run_writers = _writers_for(cohort_audit, "run")
        assert run_writers == {"aeh.orch"}, (
            f"the run row was written by {sorted(run_writers)} — `run` has exactly "
            "one writer (CT-ORCH-17); a status flip from any other module is the "
            "second-writer defect RISK-38 names, and it is silent by construction"
        )
        metrics_writers = _writers_for(durable_audit, "run_metrics")
        assert metrics_writers == {"aeh.orch"}, (
            f"run_metrics was written by {sorted(metrics_writers)} — M-ORCH is the "
            "table's sole writer (CT-STORE-03): the dispatch loop's flush is the "
            "only hand that touches it"
        )
        assert any(w.table == "run" for w in cohort_audit.writes), (
            "the audit recorded no run write at all — the drive never transitioned "
            "the run, so the sole-writer claim below would be vacuous"
        )
        assert any(w.table == "run_metrics" for w in durable_audit.writes), (
            "the drive flushed no run_metrics row — the sole-writer claim needs the "
            "metrics path actually exercised (the pass-end flush, CT-ORCH-20)"
        )

        # work_unit: the orchestrator's transitions, plus the two stages' shared
        # mark_done — and NOTHING else, from ANYONE.
        work_writers = _writers_for(cohort_audit, "work_unit")
        assert work_writers, (
            "no work_unit write was recorded — the drive touched no unit"
        )
        assert work_writers <= {"aeh.orch", "aeh.extract", "aeh.judge"}, (
            f"work_unit was written by {sorted(work_writers)} — a module outside the "
            "orchestrator and the two stage workers transitioned a unit (CT-ORCH-17: "
            "no other module transitions a unit's status or writes the ledger)"
        )
        mark_done_sql = " ".join(ORCH_STATEMENTS["mark_done"].sql.split())
        for writer in ("aeh.extract", "aeh.judge"):
            worker_writes = [
                w for w in cohort_audit.writes
                if w.module == writer and w.table == "work_unit"
            ]
            assert worker_writes, (
                f"{writer} recorded no work_unit write — the reconciled boundary "
                "(the stage's persist marks its own unit done) was not exercised, so "
                "the boundary's shape below would be asserted from nothing"
            )
            for w in worker_writes:
                assert w.sql == mark_done_sql, (
                    f"{writer} wrote work_unit with {w.sql[:80]!r} — the stage's ONLY "
                    "ledger statement is the shared mark_done it executes inside its "
                    "own persist transaction; any other unit write (an insert, a "
                    "lease, a status it does not own) is a second writer on the "
                    "ledger (CT-ORCH-17)"
                )

        # Reads are unrestricted: the workers read the ledger from their own frames,
        # and sole-writership never became sole-readership.
        reader_modules = {module for module, _ in cohort_audit.reads}
        assert reader_modules - {"aeh.orch"}, (
            f"the read log holds only {reader_modules} — no non-orchestrator module "
            "read the ledger, so the unrestricted-reads half of the clause was never "
            "exercised (the workers' own reads should appear here)"
        )
    finally:
        store.close()
