"""`CT-SETUP-11` — every write passes through `M-PKG`; documents are read
through `M-INGEST` (`TC-SETUP-C11`).

Case of test plan §6.11.6; issue #56 (TS-63). **Green by design** for the halves
asserted here — the write path and the read path landed with #50, and the probe
confirmed the audit on shipped code.

The clause: under a Tier P write audit, **every** write from this module passes
through `M-PKG` and none goes direct — which is what makes the §6.2 lock apply
to setup output without a second check existing here. Documents are read through
`M-INGEST`.

The Tier P write audit here is a pass-through recording handle
(`tests.contract.setup._doubles.AuditHandle`) over the catalog's REAL tier
handle: unlike `tests/support/store_spy.StoreSpy` (a non-persisting fake for
"writes nothing at all" clauses), this lets the real writes through to the real
SQLite file and records them — the module's full Stage A runs for real while
every statement is logged.

Asserted here, probed:

1. **Every write lands on a package-tier table, through M-PKG's handle.** A full
   Stage A run (propose → confirm → publish) is audited; every recorded write
   statement's target table appears in the set of tables the package-tier schema
   owners declare — M-STORE (`src/aeh/store.py`) and M-PKG (`src/aeh/pkg.py`) —
   scanned LIVE from source, so a table either stops owning fails here too. And
   the audit wraps the CATALOG's tier handle, so every logged write is by
   construction an M-PKG statement; the observed set covers the version row, the
   proposal row (its confirmation stamp is an M-PKG statement), the question and
   option rows, and the publish lock — nothing else exists in the log.
2. **Setup owns no SQL.** The static half: `src/aeh/setup.py` contains no SQL
   write statement at all (no INSERT/UPDATE/DELETE/CREATE against any table).
   Combined with 1, the write path is constructively M-PKG's: every statement
   the audit saw is a catalog statement, and the module has no language to
   write with on its own. This is what makes the §6.2 lock apply without a
   second check existing in setup — there is no second write path to check.
3. **Documents are read through M-INGEST.** The transcript in the proposal
   prompt is the one M-INGEST's stored document returns (read through the real
   `Ingestor`, byte-identical into the prompt field), and the audit's read log
   — every SELECT the setup flow made against the package tier — never touches
   an ingest-owned table: setup reads no document table around the gateway.
4. *(Disclosed deferral)* **Calibration papers stored-NOT-used**: no surface
   accepts teacher-marked calibration papers yet (FR-SETUP-15 lands with #53's
   intake), so the no-read-path half has no storage to audit. Deferred with
   disclosure — the #54 TC-SETUP-18 precedent — not asserted here, and NOT
   shipped red: a bug in shipped code has no `writtenahead` target.
"""
from __future__ import annotations

import ast
import re

import pytest

from tests.contract.setup._doubles import (
    AuditHandle,
    ingest_document,
    stage_chain,
)

pytestmark = pytest.mark.contract

#: The write verbs. M-PKG's transaction bodies also run precheck SELECTs (the
#: §6.2 refusal checks execute inside the same transaction), so the audit's
#: write log is filtered to these before classifying — the reads stay in the
#: log (the third test uses them) but never count as writes.
_WRITE_RE = re.compile(
    r"^\s*(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+TABLE|"
    r"CREATE\s+TRIGGER|CREATE\s+INDEX)\b", re.IGNORECASE)


def _write_statements(sqls):
    """The statements in the audit's transaction log that actually write."""
    return [sql for sql in sqls if _WRITE_RE.match(sql)]


def _table_of(sql: str) -> str:
    """The table a write statement targets, from its verb's immediate object."""
    match = (re.match(r"INSERT\s+INTO\s+([A-Za-z_]+)", sql)
             or re.match(r"UPDATE\s+([A-Za-z_]+)", sql)
             or re.match(r"DELETE\s+FROM\s+([A-Za-z_]+)", sql)
             or re.match(r"CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?([A-Za-z_]+)", sql))
    assert match, f"unrecognized write statement: {sql!r}"
    return match.group(1) if match.lastindex == 1 or match.lastindex is None else match.group(2)


def _pkg_declared_tables(repo_root) -> set[str]:
    """The tables the package-tier schema owners declare — M-STORE's migrations
    (`src/aeh/store.py`) and M-PKG's (`src/aeh/pkg.py`) — scanned LIVE from
    source, so a table either module stops owning fails here too."""
    tables: set[str] = set()
    for module in ("store.py", "pkg.py"):
        source = (repo_root / "src" / "aeh" / module).read_text(encoding="utf-8")
        tables |= set(re.findall(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_]+)", source))
    return tables


def test_tc_setup_c11_every_write_targets_a_pkg_table(tmp_data_dir, repo_root):
    """A full Stage A under the write audit: every write statement targets a
    table the package-tier schema owners declare, and every logged write is by
    construction an M-PKG statement (the audit wraps the catalog's handle) —
    nothing writes outside M-PKG."""
    chain = stage_chain(tmp_data_dir, package_id="pkg-c11")
    chain.doc = ingest_document(chain.store, kind="assessment")
    audit = AuditHandle(chain.catalog._handle)
    chain.catalog._handle = audit
    try:
        proposal = chain.service.propose_inventory(chain.doc)
        chain.service.confirm_inventory(proposal.proposal_id)
        # #53: the confirmation staged the deterministic criteria — keyed here
        # (M-PKG statements only, like every write in this audited window).
        chain.service.set_answer_keys({"CRIT-Q4": ["A"], "CRIT-Q5": ["A"],
                                       "CRIT-Q6": ["A"]})
        version = chain.service.publish("teacher-1")
    finally:
        chain.catalog._handle = audit._inner
    assert chain.catalog.is_locked(version)

    assert audit.writes, "the audit saw no writes — the run did not happen"
    declared = _pkg_declared_tables(repo_root)
    written = _write_statements(audit.writes)
    assert written, "the audit logged no write statement — the run did not happen"
    offenders = sorted({_table_of(sql) for sql in written} - declared)
    assert not offenders, (
        f"setup wrote to table(s) {offenders} that M-PKG does not declare — a "
        "write path exists outside M-PKG (CT-SETUP-11)"
    )

    # The audit saw the whole surface: the version mint, the proposal and its
    # confirmation stamp, the confirmed question rows and their options, and
    # the publish lock. (Exact counts would over-pin M-PKG's internals; the
    # TABLES are the contract's subject.)
    touched = {_table_of(sql) for sql in written}
    assert touched <= declared
    assert {"package", "package_version", "setup_proposal", "question"} <= touched, (
        f"the audited write set {sorted(touched)} is missing expected M-PKG "
        "targets — the flow under test changed"
    )


def test_tc_setup_c11_setup_owns_no_sql(repo_root):
    """The static half: `src/aeh/setup.py` contains no SQL write statement —
    the module has no language to write with, so every write necessarily goes
    through M-PKG's statements."""
    source = (repo_root / "src" / "aeh" / "setup.py").read_text(encoding="utf-8")
    # Strip comments first: the docstrings TEACH about SQL and must not count.
    source_no_comments = re.sub(r"#.*", "", source)
    offenders = []
    for verb in ("INSERT INTO", "UPDATE ", "DELETE FROM", "CREATE TABLE",
                 "CREATE TRIGGER", "CREATE INDEX"):
        if verb in source_no_comments.upper():
            offenders.append(verb.strip())
    assert not offenders, (
        f"aeh/setup.py contains SQL write vocabulary {offenders} — a direct "
        "write path exists outside M-PKG (CT-SETUP-11)"
    )
    # And no sqlite3 import either: the module cannot even open a connection.
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name != "sqlite3" for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "sqlite3"


def test_tc_setup_c11_documents_are_read_through_m_ingest(tmp_data_dir, repo_root):
    """The proposal prompt carries M-INGEST's stored transcript, and the setup
    flow never reads an ingest-owned table around the gateway."""
    chain = stage_chain(tmp_data_dir, package_id="pkg-c11r")
    doc_id = ingest_document(chain.store, kind="assessment")

    # What M-INGEST returns for the stored document — the canonical reading.
    through_gateway = chain.ingestor.read_document(doc_id)

    audit = AuditHandle(chain.catalog._handle)
    chain.catalog._handle = audit
    try:
        proposal = chain.service.propose_inventory(doc_id)
    finally:
        chain.catalog._handle = audit._inner

    # The transcript that reached the model IS the gateway's reading,
    # byte-identical, in the prompt field the inventory instruction consumes.
    prompt_fields = chain.provider.calls[0]
    assert prompt_fields["assessment_transcript"] == through_gateway, (
        "the proposal prompt's transcript is not the document M-INGEST returns "
        "— setup read the document around the gateway (CT-SETUP-11)"
    )
    assert proposal.assessment_doc_id == doc_id

    # And the flow's reads of the package tier never touch an ingest-owned
    # table: the only document reads are M-INGEST's own.
    ingest_source = (repo_root / "src" / "aeh" / "ingest.py").read_text(
        encoding="utf-8")
    ingest_tables = set(re.findall(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_]+)", ingest_source))
    offenders = sorted({re.search(r"(?:FROM|JOIN)\s+([A-Za-z_]+)", sql).group(1)
                        for sql in audit.reads
                        if re.search(r"(?:FROM|JOIN)\s+([A-Za-z_]+)", sql)}
                       & ingest_tables)
    assert not offenders, (
        f"the setup flow read ingest-owned table(s) {offenders} directly — a "
        "read path around M-INGEST exists (CT-SETUP-11)"
    )
