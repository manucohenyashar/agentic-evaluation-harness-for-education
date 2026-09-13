"""`TS-78` (issue #151) — `Requires` pairwise integration into **`M-STORE`**: every consumer's
assumption about the store, checked against a real SQLite store on a real data directory.

Test plan §6.13, grouped one suite per provider module (§4.10). Each case drives the consumer's own
write or read path where the row names one, then observes the store: the file, the schema, the
transaction boundary, the process death.

| Case | Consumer | Assumption checked here |
|---|---|---|
| TC-REQ-02 | `M-PKG` | constraints are enforced by the database, so the catalog validates by attempting the write |
| TC-REQ-03 | `M-PKG` | exemplar blobs are content-addressed: deduplicated in an export and resolved after import |
| TC-REQ-05 | `M-INGEST` | a document and its regions commit atomically under a process kill |
| TC-REQ-12 | `M-ORCH` | lease/complete transitions are transactional, backpressure is a signal, leases ignore a backwards wall clock |
| TC-REQ-22 | `M-EXTRACT` | evidence and its ledger transition commit in one transaction; no read-back outside it |
| TC-REQ-26 | `M-INTEG` | the integrity signals and the score row they qualify are one row, atomic under a kill |
| TC-REQ-32 | `M-JUDGE` | the verdict and its ledger transition commit in one transaction; no read-back outside it |
| TC-REQ-35 | `M-DET` | the deterministic audit trail reaching Tier D carries no student name |
| TC-REQ-42 | `M-AGG` | the odd-`judge_count` CHECK is enforced, so an even panel is a failed write |
| TC-REQ-48 | `M-SYNTH` | the `narrative` primary key is enforced, so a retry is a real conflict |
| TC-REQ-52 | `M-GRADE` | the partial unique index on `is_current` holds, and audit records outlive the cohort purge |
| TC-REQ-58 | `M-REVIEW` | the review queue reads by key only, never by text search |
| TC-REQ-64 | `M-STATS` | Tier D survives `purge_cohort`, so statistics remain computable |
| TC-REQ-76 | `M-CONSOLE` | a monitor poll does not slow the writer, and every multi-row view states its own order |

Markers: `contract` and `integration` (§4.7, `pytest -q -m "contract and integration"`).
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from aeh.store import Tx, open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[3]
_IMPORTS = ("import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge\n"
            "import aeh.orch, aeh.pkg, aeh.review, aeh.synth\n")
_OPEN = ({"criterion_id": "C01", "kind": "open", "scoring_model": "holistic"},)


def _child(script: str, *args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO_ROOT / "src"), str(REPO_ROOT)]))
    return subprocess.run([sys.executable, "-c", _IMPORTS + textwrap.dedent(script), *args],
                          capture_output=True, text=True, env=env, timeout=timeout)


class _TxLog:
    """Records which transaction each statement ran in, and every read outside one."""

    def __init__(self, monkeypatch):
        self.in_tx: list[tuple[int, str]] = []
        self.outside: list[tuple[str, dict]] = []
        original_execute = Tx.execute
        from aeh.store import SqliteTierHandle

        original_query = SqliteTierHandle.query
        log = self

        def execute(tx, statement, **params):
            log.in_tx.append((id(tx), str(statement)))
            return original_execute(tx, statement, **params)

        def query(handle, statement, **params):
            log.outside.append((str(statement), dict(params)))
            return original_query(handle, statement, **params)

        monkeypatch.setattr(Tx, "execute", execute)
        monkeypatch.setattr(SqliteTierHandle, "query", query)

    def tx_of(self, pattern: str) -> set[int]:
        return {tx for tx, sql in self.in_tx if re.search(pattern, sql, re.I)}


# -- TC-REQ-02 ----------------------------------------------------------------------------------


def test_tc_req_02_the_catalog_validates_by_attempting_the_write(tmp_data_dir):
    """`TC-REQ-02` (`M-PKG` → `M-STORE`, CT-STORE-01/03/12/13): the Tier P file is migrated at
    open to its complete schema. A catalog write that breaks a declared constraint fails in the
    database (`sqlite3.IntegrityError`, not a Python pre-check), and the rejected write leaves
    no row behind."""
    from aeh.pkg import PackageCatalog
    from aeh.store import COMPLETE_SCHEMA_VERSIONS, Tier

    store = open_store(tmp_data_dir)
    try:
        _orch, _run, version = seed_run(store, submissions=("S001",), criteria=_OPEN)
        handle = store.package("pkg-orch")
        applied = handle.query("SELECT MAX(version) AS v FROM schema_version")[0]["v"]
        assert applied == COMPLETE_SCHEMA_VERSIONS[Tier.PACKAGE], (
            f"the package file opened at schema {applied}, not the complete chain")
        catalog = PackageCatalog(handle, package_id="pkg-orch")
        before = handle.query("SELECT COUNT(*) AS n FROM criterion")[0]["n"]
        for label, write in (
            ("a duplicate criterion id", lambda: catalog.add_criterion(version, "C01",
                                                                       question_id="Q1")),
            ("an undeclared kind", lambda: catalog.add_criterion(version, "C99", question_id="Q9",
                                                                 kind="essayish")),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                write()
        after = handle.query("SELECT COUNT(*) AS n FROM criterion")[0]["n"]
    finally:
        store.close()
    assert after == before, f"a rejected write left rows behind: {before} -> {after}"


# -- TC-REQ-03 ----------------------------------------------------------------------------------


def test_tc_req_03_exemplar_blobs_are_deduplicated_in_export_and_resolve_after_import(
    tmp_data_dir, monkeypatch
):
    """`TC-REQ-03` (`M-PKG` → `M-STORE`, CT-STORE-07): two exemplars citing the same reference
    material share one content-addressed blob. The export carries it once, the import resolves it
    by hash, and a receiver already holding the blob does not store a second copy."""
    from aeh.pkg import PackageCatalog
    from tests.integration.pkg.test_export_import import SIGNING_KEY, _rich_package

    monkeypatch.setenv(SIGNING_KEY, "school-key")
    store, catalog, version, _parent, blob_hash = _rich_package(tmp_data_dir)
    try:
        assert store.blobs().put(b"reference material for the exemplar") == blob_hash
        unpublished = catalog.create_version(version)
        catalog.add_exemplar(unpublished, "EX-2", "CRIT-1", "b1", provenance="paraphrased",
                             blob_hash=blob_hash)
        catalog.publish(unpublished, "teacher")
        report = catalog.export(unpublished, tmp_data_dir / "dedup.pkgzip")
    finally:
        store.close()
    assert report.blobs_included == (blob_hash,), (
        f"two exemplars on one blob exported {report.blobs_included}, not one blob")

    receiver = open_store(tmp_data_dir / "receiver")
    try:
        receiver.blobs().put(b"reference material for the exemplar")  # already held
        blob_files = lambda: sorted(p for p in (tmp_data_dir / "receiver").rglob("*")  # noqa: E731
                                    if p.is_file() and blob_hash.split(":")[-1][:16] in p.name)
        held_before = blob_files()
        assert held_before, "control: the receiver's own copy of the blob was not found on disk"
        importer = PackageCatalog(receiver.package("receiving"), package_id="receiving",
                                  blobs=receiver.blobs())
        importer.import_file(tmp_data_dir / "dedup.pkgzip")
        held_after = blob_files()
        resolved = receiver.blobs().get(blob_hash)
    finally:
        receiver.close()
    assert resolved == b"reference material for the exemplar"
    assert held_after == held_before, f"the import stored a second copy: {held_after}"


# -- TC-REQ-12 ----------------------------------------------------------------------------------


def test_tc_req_12_ledger_transitions_are_transactional_and_backpressure_and_clock_are_safe(
    tmp_data_dir, monkeypatch
):
    """`TC-REQ-12` (`M-ORCH` → `M-STORE`, CT-STORE-02/03/05/06/14): the row §6.13 calls the
    single highest-value one.

    1. `lease` and `complete` move the ledger inside `transaction()`: the transition is visible
       the moment the call returns, with no queued write the orchestrator would have to read back.
    2. With the store signalling backpressure, `lease`, `complete` and `progress` carry on
       (a signal to reduce, not a fault).
    3. With the wall clock stepped back a day, a fresh lease is not treated as expired and the
       sweeper reclaims nothing. Lease expiry runs on the store's monotonic lease clock."""
    from aeh.orch import STAGE_EXTRACT
    
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _version = seed_run(store, submissions=("S001", "S002"),
                                                  criteria=_OPEN)
        orchestrator.enumerate_units(run_id)
        orchestrator.start(run_id)
        cohort = store.cohort(ORCH_COHORT_ID)
        status = lambda wid: cohort.query(  # noqa: E731
            "SELECT status FROM work_unit WHERE work_id = :w", w=wid)[0]["status"]

        leased = orchestrator.lease("w-req-12", STAGE_EXTRACT, 1)
        assert leased and status(leased[0].work_id) == "leased"
        log = _TxLog(monkeypatch)
        orchestrator.complete(leased[0].work_id)
        monkeypatch.undo()
        assert status(leased[0].work_id) == "done"
        assert log.in_tx and any("UPDATE work_unit" in sql for _tx, sql in log.in_tx), (
            "complete() moved the ledger outside a transaction")

        fresh = None
    finally:
        store.close()

    # 2. Backpressure is sensed only by the dispatch loop, so drive one with a model-call seam.
    import aeh.orch as orch_module
    from aeh.prov import Completion
    from tests.support.orch_run import seed_documents

    class _Seam:
        calls = 0

        def call(self, request):
            _Seam.calls += 1
            return Completion(text="band: B", tokens_in=10, tokens_out=5, latency_ms=1,
                              resolved_build="fixture-build", cached_prefix_tokens=0, cost=None)

    store = open_store(tmp_data_dir / "pressured")
    try:
        seam = _Seam()
        pressured_orch, pressured_run, _v = seed_run(store, submissions=("S001", "S002"),
                                                     criteria=_OPEN, transport=seam)
        seed_documents(store, ("S001", "S002"))
        pressured_orch.enumerate_units(pressured_run)
        pressured_orch.start(pressured_run)
        for stage in ("extract", "deterministic"):
            for unit in pressured_orch.lease("w-req-12", stage, 64):
                pressured_orch.complete(unit.work_id)
        signalled: list[bool] = []
        real_metrics = orch_module.store_metrics

        def pressured(store_arg):
            metrics = dict(real_metrics(store_arg))
            metrics["backpressure_active"] = True
            signalled.append(True)
            return metrics

        monkeypatch.setattr(orch_module, "store_metrics", pressured)
        report = pressured_orch.progress(pressured_run)
        monkeypatch.undo()
    finally:
        store.close()
    assert signalled, "control: the dispatch loop never read the backpressure signal"
    assert _Seam.calls > 0, "under backpressure the dispatch loop stopped instead of reducing"
    assert report.concurrency >= 1, f"backpressure clamped concurrency to {report.concurrency}"

    # 3. A backwards wall clock does not expire a fresh lease.
    store = open_store(tmp_data_dir)
    try:
        orchestrator = orch_module.Orchestrator(store)
        cohort = store.cohort(ORCH_COHORT_ID)
        status = lambda wid: cohort.query(  # noqa: E731
            "SELECT status FROM work_unit WHERE work_id = :w", w=wid)[0]["status"]
        fresh = orchestrator.lease("w-req-12", STAGE_EXTRACT, 1)
        real_time = time.time
        monkeypatch.setattr(time, "time", lambda: real_time() - 86_400)
        report = orchestrator.sweep_expired_leases()
        monkeypatch.undo()
        still = [status(unit.work_id) for unit in fresh]
    finally:
        store.close()
    assert still == ["leased"] * len(fresh), (
        f"a backwards wall clock expired a fresh lease: {still} ({report})")


# -- TC-REQ-22 / TC-REQ-32 ----------------------------------------------------------------------


def _judged_world(store, monkeypatch):
    from tests.contract.judge import _drive

    provider_dir = store.data_dir / "fixtures"
    from aeh.prov import RecordedFixtureProvider

    provider = RecordedFixtureProvider(fixture_dir=provider_dir)
    orchestrator, run_id, _version = _drive.seed_world(store)
    return _drive, orchestrator, run_id, provider


def _own_readbacks(log: _TxLog, table: str, work_ids: set[str]) -> list[str]:
    return [sql for sql, params in log.outside
            if re.search(rf"\b{table}\b", sql, re.I) and work_ids & {str(v) for v in params.values()}]


def test_tc_req_22_extraction_commits_evidence_with_its_transition_and_never_reads_it_back(
    tmp_data_dir, monkeypatch
):
    """`TC-REQ-22` (`M-EXTRACT` → `M-STORE`, CT-STORE-02/03): over a real run, the real worker's
    evidence insert and its unit's done transition execute in the same transaction. No read
    outside a transaction touches the evidence table for the unit it just wrote."""
    store = open_store(tmp_data_dir)
    try:
        drive, orchestrator, run_id, provider = _judged_world(store, monkeypatch)
        log = _TxLog(monkeypatch)
        drive.drive_extract(orchestrator, store, provider)
        monkeypatch.undo()
        evidence = store.cohort(ORCH_COHORT_ID).query("SELECT work_id FROM evidence")
    finally:
        store.close()
    work_ids = {row["work_id"] for row in evidence}
    assert work_ids, "fixture: extraction wrote no evidence"
    inserts, done = log.tx_of(r"INSERT\b.*\bevidence\b"), log.tx_of(r"SET status\s*=\s*'done'")
    assert inserts and inserts <= done, (
        "an evidence insert ran in a transaction that did not also move its unit to done")
    readbacks = _own_readbacks(log, "evidence", work_ids)
    assert not readbacks, f"the worker read its own evidence back outside a transaction: {readbacks[:2]}"


def test_tc_req_32_scoring_commits_the_verdict_with_its_transition_and_never_reads_it_back(
    tmp_data_dir, monkeypatch
):
    """`TC-REQ-32` (`M-JUDGE` → `M-STORE`, CT-STORE-02/03): the real scoring worker's `persist`
    inserts the verdict and marks its unit done in one transaction. No read outside a
    transaction touches the verdict table for the unit just persisted."""
    store = open_store(tmp_data_dir)
    try:
        drive, orchestrator, run_id, provider = _judged_world(store, monkeypatch)
        drive.drive_extract(orchestrator, store, provider)
        log = _TxLog(monkeypatch)
        judged = drive.drive_score(orchestrator, store, provider)
        monkeypatch.undo()
        verdicts = store.cohort(ORCH_COHORT_ID).query("SELECT work_id FROM verdict")
    finally:
        store.close()
    work_ids = {row["work_id"] for row in verdicts}
    assert judged and len(work_ids) == judged, f"fixture: {judged} judged, {len(work_ids)} verdicts"
    inserts, done = log.tx_of(r"INSERT\b.*\bverdict\b"), log.tx_of(r"SET status\s*=\s*'done'")
    assert inserts and inserts <= done, (
        "a verdict insert ran in a transaction that did not also move its unit to done")
    readbacks = _own_readbacks(log, "verdict", work_ids)
    assert not readbacks, f"persist read its own verdict back outside a transaction: {readbacks[:2]}"


# -- TC-REQ-42 / TC-REQ-48 ----------------------------------------------------------------------


def test_tc_req_42_an_even_panel_score_is_a_failed_write_at_the_database(tmp_data_dir):
    """`TC-REQ-42` (`M-AGG` → `M-STORE`, CT-STORE-03/13, CT-AGG-03): the score row M-AGG's walk
    writes carries `judge_count`. An even count is refused by the database's CHECK, inside the
    transaction, and nothing lands. An odd count on the same row writes."""
    upsert = ("INSERT OR REPLACE INTO criterion_score (submission_id, criterion_id, band, points, "
              "judge_count, routing, state) VALUES (:s, 'C01', 'met', 1.0, :n, 'auto', 'final')")
    store = open_store(tmp_data_dir)
    try:
        seed_run(store, submissions=("S001",), criteria=_OPEN)
        cohort = store.cohort(ORCH_COHORT_ID)
        with pytest.raises(sqlite3.IntegrityError, match="judge_count"):
            with cohort.transaction() as tx:
                tx.execute(upsert, s="S001", n=2)
        assert cohort.query("SELECT COUNT(*) AS n FROM criterion_score")[0]["n"] == 0
        with cohort.transaction() as tx:
            tx.execute(upsert, s="S001", n=3)
        assert cohort.query("SELECT judge_count FROM criterion_score")[0]["judge_count"] == 3
    finally:
        store.close()


def test_tc_req_48_a_duplicate_narrative_is_a_real_conflict_at_the_database(tmp_data_dir):
    """`TC-REQ-48` (`M-SYNTH` → `M-STORE`, CT-STORE-03/13, CT-SYNTH-06): M-SYNTH's own insert
    statement, executed twice for the same key, fails the second time at the database. The
    statement is a plain `INSERT`, so the conflict reaches the worker rather than being absorbed
    by `OR IGNORE` or `OR REPLACE`."""
    from aeh.synth import SYNTH_STATEMENTS

    statement = SYNTH_STATEMENTS["insert_narrative"]
    assert re.match(r"\s*INSERT\s+INTO\b", str(statement), re.I), (
        f"M-SYNTH's narrative insert absorbs conflicts: {str(statement)[:60]}")
    params = set(re.findall(r":(\w+)", str(statement)))
    values = {name: f"v-{name}" for name in params}
    values.update(run_id="r-48", submission_id="S001", level="l1_question", question_id="Q1",
                  score_claim_flag=0)
    values = {k: v for k, v in values.items() if k in params}
    store = open_store(tmp_data_dir)
    try:
        seed_run(store, submissions=("S001",), criteria=_OPEN)
        cohort = store.cohort(ORCH_COHORT_ID)
        with cohort.transaction() as tx:
            tx.execute(statement, **values)
        with pytest.raises(sqlite3.IntegrityError):
            with cohort.transaction() as tx:
                tx.execute(statement, **values)
        assert cohort.query("SELECT COUNT(*) AS n FROM narrative")[0]["n"] == 1
    finally:
        store.close()


# -- TC-REQ-05 ----------------------------------------------------------------------------------

_INGEST_KILLED = """
import os, sys
from aeh.store import Tx, open_store
from tests.support.setup_harness import build_ingestor, ASSESSMENT_MD
store = open_store(sys.argv[1])
with store.cohort("c-setup").transaction() as tx:
    tx.execute("INSERT INTO cohort (cohort_id, consent_class, created_at) "
               "VALUES ('c-setup', 'synthetic', '2026-01-01')")
original = Tx.execute
def dying(tx, statement, **params):
    result = original(tx, statement, **params)
    if "INSERT" in str(statement).upper() and "DOCUMENT_REGION" in str(statement).upper():
        os._exit(3)  # an uncontrolled death with the region write mid-transaction
    return result
Tx.execute = dying
source = store.blobs().put(b"assessment bytes")
build_ingestor(store, ASSESSMENT_MD).ingest_document([source], kind="assessment",
                                                     filenames={source: "a.pdf"})
os._exit(0)
"""


def test_tc_req_05_a_document_and_its_regions_commit_atomically_under_a_kill(tmp_data_dir):
    """`TC-REQ-05` (`M-INGEST` → `M-STORE`, CT-STORE-03/07/16): a child process ingests one
    document through the real `Ingestor` and dies uncontrolled (`os._exit`) right after its first
    region insert executes. On reopen, a document row is present only with its regions: no
    document without regions. An undisturbed ingest's source blob resolves by its content hash,
    and on POSIX the blob file is owner-only (`0o600`). Windows has no POSIX mode bits, so that
    half is not asserted there."""
    killed = _child(_INGEST_KILLED, str(tmp_data_dir))
    assert killed.returncode == 3, f"fixture: the child did not die mid-write: {killed.stderr[-600:]}"
    store = open_store(tmp_data_dir)
    try:
        cohort = store.cohort("c-setup")
        documents = cohort.query("SELECT COUNT(*) AS n FROM document")[0]["n"]
        regions = cohort.query("SELECT COUNT(*) AS n FROM document_region")[0]["n"]
        orphans = cohort.query(
            "SELECT COUNT(*) AS n FROM document d WHERE NOT EXISTS "
            "(SELECT 1 FROM document_region r WHERE r.document_id = d.document_id)")[0]["n"]
    finally:
        store.close()
    assert orphans == 0, (
        f"the kill left {documents} document row(s) and {regions} region row(s), with {orphans} "
        f"document(s) holding no region: the document and its regions did not commit together")

    clean = open_store(tmp_data_dir / "clean")
    try:
        source = clean.blobs().put(b"assessment bytes for the clean ingest")
        again = clean.blobs().put(b"assessment bytes for the clean ingest")
        resolved = clean.blobs().get(source)
        mode = clean.blobs().path(source).stat().st_mode & 0o777
    finally:
        clean.close()
    assert source == again, "the same bytes stored twice were given two addresses"
    assert resolved == b"assessment bytes for the clean ingest"
    if os.name == "posix":
        assert mode == 0o600, f"the blob file is not owner-only: {oct(mode)}"


# -- TC-REQ-26 ----------------------------------------------------------------------------------

_SCORE_KILLED = """
import os, sys
from aeh.store import open_store
from tests.support.e2e_world import _SCORE_UPSERT
store = open_store(sys.argv[1])
with store.cohort("c-2026-7B-orch").transaction() as tx:
    tx.execute(_SCORE_UPSERT, sid="S001", cid="C01", band="met", points=1.0, judge_count=3,
               agreement=1.0, state="final", routing="auto", confidence=0.9,
               confidence_base=0.9, spans_verified=1, evidence_present=1,
               sufficiency_flag=0, ocr_overlap_risk=0)
    os._exit(4)  # killed after the score-with-signals write, before the commit
"""


def test_tc_req_26_integrity_signals_and_their_score_row_are_one_atomic_write(tmp_data_dir):
    """`TC-REQ-26` (`M-INTEG` → `M-STORE`, CT-STORE-03): the gate's signals reach the ledger as
    columns of the `criterion_score` row they qualify (`spans_verified`, `evidence_present`,
    `sufficiency_flag`, `ocr_overlap_risk`), written in one statement by the aggregation walk. A
    process killed inside that transaction leaves neither the score nor its signals.

    Disclosed shape: `IntegrityGate` itself persists routing rows (units, review items, rates),
    not the signals. The signals commit through the score write, which is the statement the walk
    in `tests/support/e2e_world.py` issues."""
    store = open_store(tmp_data_dir)
    try:
        seed_run(store, submissions=("S001",), criteria=_OPEN)
        columns = {row["name"] for row in store.cohort(ORCH_COHORT_ID).query(
            "SELECT name FROM pragma_table_info('criterion_score')")}
    finally:
        store.close()
    signals = {"spans_verified", "evidence_present", "sufficiency_flag", "ocr_overlap_risk"}
    assert signals <= columns, f"criterion_score does not carry the signals: {signals - columns}"

    killed = _child(_SCORE_KILLED, str(tmp_data_dir))
    assert killed.returncode == 4, f"fixture: the child did not die mid-transaction: {killed.stderr[-600:]}"
    store = open_store(tmp_data_dir)
    try:
        left = store.cohort(ORCH_COHORT_ID).query("SELECT COUNT(*) AS n FROM criterion_score")[0]["n"]
    finally:
        store.close()
    assert left == 0, "a killed score-with-signals write left a row behind"


# -- TC-REQ-35 ----------------------------------------------------------------------------------


def test_tc_req_35_the_deterministic_audit_trail_reaches_tier_d_without_a_student_name(
    tmp_data_dir
):
    """`TC-REQ-35` (`M-DET` → `M-STORE`, CT-STORE-03/09): the head document carries a sentinel
    student name in its transcript. After M-DET's real cohort pass writes its audit records and
    item statistics to Tier D, no cell of any Tier D table holds the sentinel. The store also
    refuses a Tier D insert naming a student-name column (`StudentNameInTierDError`), the
    backstop M-DET relies on."""
    from aeh.det import DeterministicEvaluator
    from aeh.store import StudentNameInTierDError
    from tests.support.det_vocabulary import (
        open_det_store,
        seed_answer_region,
        seed_det_world,
        seed_head_document,
    )

    sentinel = "Zebulon Quartermaine-Oyelaran"
    store = open_det_store(tmp_data_dir)
    try:
        run_id, _version, cohort_id = seed_det_world(
            store, submissions=("S001", "S002"),
            criteria=[{"criterion_id": "M1", "question_id": "Q1", "key": ("B",)}])
        for submission in ("S001", "S002"):
            document_id = seed_head_document(store, cohort_id, submission)
            seed_answer_region(store, cohort_id, document_id, "Q1", selection="B")
        with store.cohort(cohort_id).transaction() as tx:
            tx.execute("UPDATE document SET markdown = :m", m=f"Student: {sentinel}\nQ1 (B)")
        DeterministicEvaluator(store).evaluate_cohort(run_id)
        durable = store.durable()
        audit = durable.query("SELECT COUNT(*) AS n FROM audit_record")[0]["n"]
        leaked = []
        for table in [row["name"] for row in durable.query(
                "SELECT name FROM sqlite_master WHERE type = 'table'")]:
            for row in durable.query(f'SELECT * FROM "{table}"'):
                if any(sentinel in str(value) for value in dict(row).values()):
                    leaked.append(table)
        with pytest.raises(StudentNameInTierDError):
            with durable.transaction() as tx:
                tx.execute("INSERT INTO audit_record (audit_record_id, run_id, recorded_at, "
                           "profile_summary, student_name) VALUES ('a', 'r', 't', 'p', 'x')")
    finally:
        store.close()
    assert audit > 0, "fixture: the cohort pass wrote no audit record to Tier D"
    assert not leaked, f"the student name reached Tier D in {sorted(set(leaked))}"


# -- TC-REQ-52 ----------------------------------------------------------------------------------


def test_tc_req_52_one_current_revision_is_enforced_and_audit_records_outlive_the_purge(
    tmp_data_dir
):
    """`TC-REQ-52` (`M-GRADE` → `M-STORE`, CT-STORE-03/09/13): the partial unique index on
    `submission_grade (run_id, submission_id) WHERE is_current = 1` refuses a second current
    revision at the database, while a superseded revision coexists. M-GRADE's amendment audit
    record, written to Tier D through its own statement, is still there after `purge_cohort`
    has emptied the cohort file."""
    from aeh.grade import GRADE_STATEMENTS
    from tests.integration.store.test_purge import _promote

    revision = ("INSERT INTO submission_grade (submission_id, revision, run_id, is_current, state) "
                "VALUES ('S001', :rev, 'r-52', :cur, 'provisional')")
    store = open_store(tmp_data_dir)
    try:
        seed_run(store, submissions=("S001",), criteria=_OPEN)
        cohort = store.cohort(ORCH_COHORT_ID)
        with cohort.transaction() as tx:
            tx.execute(revision, rev=0, cur=0)
            tx.execute(revision, rev=1, cur=1)
        with pytest.raises(sqlite3.IntegrityError):
            with cohort.transaction() as tx:
                tx.execute(revision, rev=2, cur=1)
        current = cohort.query(
            "SELECT COUNT(*) AS n FROM submission_grade WHERE is_current = 1")[0]["n"]

        statement = GRADE_STATEMENTS["insert_amendment_audit_record"]
        names = set(re.findall(r":(\w+)", str(statement)))
        params = {name: f"v-{name}" for name in names}
        params.update({k: v for k, v in (("audit_record_id", "aud-52"), ("run_id", "r-52"),
                                         ("cohort_id", ORCH_COHORT_ID),
                                         ("evaluation_mode", "judged")) if k in names})
        _promote(store, ORCH_COHORT_ID)
        with store.durable().transaction() as tx:
            tx.execute(statement, **params)
        store.purge_cohort(ORCH_COHORT_ID)
        grades_after = store.cohort(ORCH_COHORT_ID).query(
            "SELECT COUNT(*) AS n FROM submission_grade")[0]["n"]
        audit_after = store.durable().query(
            "SELECT COUNT(*) AS n FROM audit_record WHERE audit_record_id = 'aud-52'")[0]["n"]
    finally:
        store.close()
    assert current == 1
    assert grades_after == 0, "fixture: the purge did not empty the cohort file"
    assert audit_after == 1, "M-GRADE's audit record did not survive the cohort purge"


# -- TC-REQ-58 ----------------------------------------------------------------------------------


def test_tc_req_58_the_review_queue_reads_by_key_and_never_by_text_search():
    """`TC-REQ-58` (`M-REVIEW` → `M-STORE`, CT-STORE-03/08/09), the consuming half of
    CT-STORE-08: no SQL in M-REVIEW uses a text-search operator (`LIKE`, `GLOB`, `MATCH`,
    `REGEXP`, `instr`, full-text tables), and every read of the queue's population
    (`criterion_score`, `review_queue`, `label`) filters by key or state columns with `=`, `<>` or `IN`. The store handles expose no search method to reach for."""
    import ast
    import inspect

    import aeh.review as review
    from aeh.store import SqliteStore, SqliteTierHandle

    # ast merges implicitly concatenated literals, so each SQL string is read whole.
    sql = [" ".join(node.value.split()) for node in ast.walk(ast.parse(inspect.getsource(review)))
           if isinstance(node, ast.Constant) and isinstance(node.value, str)
           and re.match(r"\s*(SELECT|INSERT|UPDATE|DELETE|WITH)\b", node.value, re.I)]
    search = [q for q in sql if re.search(r"\b(LIKE|GLOB|MATCH|REGEXP|fts\d)\b|instr\s*\(", q, re.I)]
    reads = [q for q in sql if re.match(r"(SELECT|WITH)\b", q, re.I)
             and re.search(r"\bFROM\s+(criterion_score|review_queue|label)\b", q, re.I)]
    unkeyed = [q for q in reads if not re.search(r"\bWHERE\b.*(=|<>|\bIN\b)", q, re.I)]
    surface = [name for cls in (SqliteStore, SqliteTierHandle) for name in dir(cls)
               if re.search(r"search|find|fulltext", name, re.I)]
    assert reads, "control: no queue-population read was found in M-REVIEW's source"
    assert not search, f"M-REVIEW issues text search: {search[:2]}"
    assert not unkeyed, f"a queue-population read is not keyed: {unkeyed[:2]}"
    assert not surface, f"the store exposes a search surface: {surface}"


# -- TC-REQ-64 ----------------------------------------------------------------------------------


def test_tc_req_64_statistics_remain_computable_after_the_cohort_purge(tmp_data_dir):
    """`TC-REQ-64` (`M-STATS` → `M-STORE`, CT-STORE-09): with a cohort's labels promoted to Tier
    D, `open_stats` reads the same label population and gives the same agreement answer after
    `purge_cohort` has emptied the cohort file as before it."""
    from aeh.stats import open_stats
    from tests.integration.store.test_purge import _promote, _seed_cohort

    cohort_id = "c-req-64"
    store = open_store(tmp_data_dir)
    try:
        _seed_cohort(store, cohort_id, with_sentinel=False)
        _promote(store, cohort_id)
    finally:
        store.close()

    def figures():
        stats = open_stats(tmp_data_dir, cohort_id=cohort_id)
        return (len(stats._labels), repr(stats.admissible_labels()),
                repr(stats.agreement(criterion_id="CRIT-1")))

    before = figures()
    store = open_store(tmp_data_dir)
    try:
        store.purge_cohort(cohort_id)
        emptied = store.cohort(cohort_id).query("SELECT COUNT(*) AS n FROM submission")[0]["n"]
    finally:
        store.close()
    after = figures()
    assert before[0] > 0, "fixture: open_stats read no label before the purge"
    assert emptied == 0, "fixture: the purge did not empty the cohort file"
    assert after == before, f"statistics changed across the purge: {before} -> {after}"


# -- TC-REQ-76 ----------------------------------------------------------------------------------

_POLLER = """
import sys, time
from aeh.console import build_console, SCREENS
from aeh.store import open_store
store = open_store(sys.argv[1], read_only=True)
app = build_console(store=store)
print("polling", flush=True)
deadline = time.time() + float(sys.argv[3])
while time.time() < deadline:
    app.render(SCREENS["S7"], id=sys.argv[2])
"""


def _writer_seconds(data_dir: Path, units: int) -> float:
    from aeh.orch import STAGE_EXTRACT, Orchestrator

    store = open_store(data_dir)
    try:
        orchestrator = Orchestrator(store)
        started = time.perf_counter()
        done = 0
        while done < units:
            batch = orchestrator.lease("w-req-76", STAGE_EXTRACT, 16)
            if not batch:
                break
            for unit in batch:
                orchestrator.complete(unit.work_id)
                done += 1
        return time.perf_counter() - started
    finally:
        store.close()


def test_tc_req_76_a_monitor_poll_does_not_slow_the_writer_and_views_state_their_order(
    tmp_data_dir
):
    """`TC-REQ-76` (`M-CONSOLE` → `M-STORE`, CT-STORE-01/04/18).

    1. **Reads never block the writer.** The same lease-and-complete workload is timed alone and
       then with a separate console process polling the run monitor (S7) as fast as it renders.
       Taking the best of three per side, the polled run stays within `POLL_SLOWDOWN` of the
       unpolled one. The console runs as its own process, the way HLD §11.7 deploys it.
    2. **No view depends on incidental order.** The same submissions go into two stores in
       opposite physical orders, and the quarantine screen (S8), which lists them, must render
       byte-identical HTML from both."""
    POLL_SLOWDOWN = 1.5
    submissions = tuple(f"S{i:03d}" for i in range(1, 41))
    criteria = tuple({"criterion_id": f"C{i:02d}", "kind": "open", "scoring_model": "holistic"}
                     for i in range(1, 6))
    timings: dict[str, list[float]] = {"alone": [], "polled": []}
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO_ROOT / "src"), str(REPO_ROOT)]))
    for attempt in range(3):
        for mode in ("alone", "polled"):
            data_dir = tmp_data_dir / f"{mode}-{attempt}"
            store = open_store(data_dir)
            try:
                orchestrator, run_id, _v = seed_run(store, submissions=submissions,
                                                    criteria=criteria)
                orchestrator.enumerate_units(run_id)
                orchestrator.start(run_id)
            finally:
                store.close()
            poller = None
            if mode == "polled":
                poller = subprocess.Popen(
                    [sys.executable, "-c", _IMPORTS + textwrap.dedent(_POLLER), str(data_dir),
                     run_id, "60"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                    env=env)
                assert poller.stdout.readline().strip() == "polling", "fixture: the poller did not start"
            try:
                timings[mode].append(_writer_seconds(data_dir, 200))
            finally:
                if poller is not None:
                    poller.kill()
                    poller.wait()
    alone, polled = min(timings["alone"]), min(timings["polled"])

    from aeh.console import SCREENS, build_console
    from tests.support.orch_run import seed_cohort

    pages = []
    for name, order in (("forward", submissions[:8]), ("reverse", tuple(reversed(submissions[:8])))):
        store = open_store(tmp_data_dir / f"order-{name}")
        try:
            seed_cohort(store, order)
            with store.cohort(ORCH_COHORT_ID).transaction() as tx:
                tx.execute("UPDATE submission SET quarantined = 1, ingest_status = 'unreadable' "
                           "WHERE submission_id IN ('S002', 'S005')")
            pages.append(build_console(store=store).render(SCREENS["S8"]).html)
        finally:
            store.close()

    assert "S002" in pages[0] and "S005" in pages[0], (
        "control: the quarantine screen lists no submission, so its order cannot be compared")
    problems = []
    if polled > alone * POLL_SLOWDOWN:
        problems.append(f"a console poll slowed the writer: {polled:.3f}s polled vs {alone:.3f}s "
                        f"alone (best of three), over {POLL_SLOWDOWN}x")
    if pages[0] != pages[1]:
        problems.append("the quarantine screen renders differently when the same submissions are "
                        "stored in a different physical order, so the view depends on incidental "
                        "order (CT-STORE-18). [When written: console.py's _SELECT_COHORT_QUARANTINE carries no "
                        "ORDER BY.]")
    assert not problems, "\n".join(problems) + f"\ntimings: {timings}"
