"""`CT-INGEST-23` — name-primary identity; the ref is the only identity output; names never leave
Tier C (`TC-INGEST-C23`, TS-143, issue #619; operator-requirements test plan §5.4, §6.11).

The clause: V3 matches by normalized name first; a student ID is a secondary signal only and its
absence is never an error. Identity resolution outputs a `student_ref`; the name extracted from a
paper never leaves the module except into Tier C rows and triage display. **Breaks if** a name
reaches a model request, a log, or any Tier D row.

Two halves:

1. **The clause suite** (written ahead of #620) — the TC-INGEST-56/57 matrix over F-NAMES
   (`tests/support/f_names.py`), asserted at clause strength per cell: the output is a roster
   `student_ref` (resolved) or `unknown` with the paper held (triaged) — never another value, and
   the expected one per the hand-computed table; no name in any request the model boundary
   received, in any log record, or in the bytes of any Tier D or Tier P file. A cell with no ID
   on the paper resolves exactly as it would with one where the name alone decides — the ID's
   absence is never an error.
2. **The static sweep** (green today, unmarked, so it guards #620 as #620 lands) — no Tier D or
   Tier P migration declares a name column, and no module that builds a model request outside
   the judge's redaction boundary reads the roster's `full_name`. Each sweep is shown to flag a
   planted mutant, so neither passes vacuously.

`aeh.judge` is outside the source sweep on purpose: its `assemble` *receives* the roster name in
order to replace it with the `student_ref` (SEC-19, TS-129), so reading a name is its legitimate
job; that boundary is pinned behaviourally by `tests/e2e/test_ts129_jev_open_arms.py`.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

import aeh.agg  # noqa: F401 — the full chain (CLAUDE.md: all eleven contributors)
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
from aeh.store import TIER_MIGRATIONS, Tier
from tests.support import f_names as fx

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "src" / "aeh"

#: The hand-computed clause table: (cell, written name, written ID, expected ref or None).
#: None means triage: `unknown`, held.
CLAUSE_CELLS = tuple((a.arm_id, a.written, None, a.intended_ref) for a in fx.ARMS) + (
    ("collision", fx.COLLISION_WRITTEN, None, None),
    ("collision-with-id", fx.COLLISION_WRITTEN, "S-0410", "S-0410"),
    ("unmatched", fx.UNMATCHED_WRITTEN, None, None),
    ("prefix", fx.PREFIX_WRITTEN, None, None),
)

#: Column names that would hold a student's name.
_NAME_COLUMN = re.compile(
    r"\b(full_name|student_name|first_name|last_name|given_name|family_name|surname)\b",
    re.IGNORECASE)

#: Where a model request is built, outside the judge's redaction boundary (see the docstring).
REQUEST_BUILDERS = ("prov", "extract", "synth", "setup", "ingest/markup.py")

_ROSTER_NAME = re.compile(r"\bfull_name\b")


# --- 1. the clause suite -----------------------------------------------------------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize("cell, written, student_id, expected", CLAUSE_CELLS,
                         ids=[c[0] for c in CLAUSE_CELLS])
def test_tc_ingest_c23_identity_outputs_a_ref_and_names_stay_in_tier_c(
        tmp_data_dir, caplog, cell, written, student_id, expected):
    caplog.set_level(logging.DEBUG)
    world = fx.NamesWorld(tmp_data_dir / f"c23-{cell}")
    try:
        report = world.ingest(f"c23-{cell}", written, student_id)
        row = world.submission(report.submission_id)
        if expected is None:
            assert (row["student_ref"], row["quarantined"]) == ("unknown", 1), (
                f"C23 {cell}: an unresolved identity must be triaged, never guessed — got "
                f"ref {row['student_ref']!r}, quarantined={row['quarantined']}")
            assert report.gates.get("v3") in ("ambiguous", "unmatched"), report.gates
        else:
            assert (row["student_ref"], report.gates.get("v3")) == (expected, "pass"), (
                f"C23 {cell}: expected {expected}, got {row['student_ref']!r} "
                f"(V3 {report.gates.get('v3')!r}: {fx.v3_findings(report)})")
        assert row["student_ref"] in set(fx.REFS) | {"unknown"}, (
            f"C23 {cell}: identity resolution output {row['student_ref']!r}, which is not a ref")
        for request in world.provider.requests:
            assert not fx.find_names(request), f"C23 {cell}: a name reached a model request"
    finally:
        world.close()
    assert not fx.find_names(caplog.text), (
        f"C23 {cell}: a name reached a log record: {fx.find_names(caplog.text)}")
    files = fx.non_cohort_files(world.root)
    assert any(p.name.startswith("durable.sqlite") for p in files), "fixture: no Tier D file"
    for path in files:
        assert not fx.scan_bytes_for_names(path), (
            f"C23 {cell}: a name reached {path.name} — Tier D/P gain nothing (FR-STORE-12)")


def test_tc_ingest_c23_the_tier_scan_flags_a_planted_name(tmp_path):
    """The byte scan is not vacuous: a name planted in a Tier D-shaped file, in NFC or NFD, is
    found."""
    import sqlite3
    import unicodedata

    for form in ("NFC", "NFD"):
        path = tmp_path / f"durable-{form}.sqlite"
        connection = sqlite3.connect(path)
        try:
            connection.execute("CREATE TABLE t (v TEXT)")
            connection.execute("INSERT INTO t VALUES (?)",
                               (unicodedata.normalize(form, "Chloé Lefèvre"),))
            connection.commit()
        finally:
            connection.close()
        assert fx.scan_bytes_for_names(path), f"the scan missed a planted {form} name"


# --- 2. the static sweep -----------------------------------------------------------------------


def _name_columns_in(statements) -> list[str]:
    return [str(s) for s in statements if _NAME_COLUMN.search(str(s))]


def test_tc_ingest_c23_no_tier_d_or_p_migration_declares_a_name_column():
    for tier in (Tier.DURABLE, Tier.PACKAGE):
        for migration in TIER_MIGRATIONS[tier]:
            found = _name_columns_in(migration.statements)
            assert not found, (
                f"C23: {tier.name} migration {migration.version} ({migration.name}) declares a "
                f"name column — names live in Tier C only (FR-STORE-12): {found[:1]}")


def test_tc_ingest_c23_the_column_sweep_flags_a_planted_name_column():
    assert _name_columns_in(["CREATE TABLE x (student_ref TEXT, full_name TEXT)"])
    assert not _name_columns_in(["CREATE TABLE x (student_ref TEXT, rubric_name TEXT)"])


def _request_builder_files() -> list[Path]:
    files: list[Path] = []
    for entry in REQUEST_BUILDERS:
        path = SRC / entry
        files.extend([path] if path.is_file() else sorted(path.rglob("*.py")))
    return files


def _roster_name_readers(texts: dict[str, str]) -> list[str]:
    return sorted(name for name, text in texts.items() if _ROSTER_NAME.search(text))


def test_tc_ingest_c23_no_request_builder_reads_the_roster_name():
    files = _request_builder_files()
    assert len(files) > 10, f"fixture: the sweep found only {len(files)} files"
    texts = {str(p.relative_to(SRC)): p.read_text(encoding="utf-8") for p in files}
    readers = _roster_name_readers(texts)
    assert not readers, (
        f"C23: {readers} read the roster's full_name — a model request is built there, and "
        f"names never enter one (NFR-PROV-04, CT-INGEST-23)")


def test_tc_ingest_c23_the_source_sweep_flags_a_planted_reader():
    mutant = {"ingest/markup.py": 'SELECT full_name FROM roster WHERE student_ref = :r',
              "prov/live.py": "student_ref only"}
    assert _roster_name_readers(mutant) == ["ingest/markup.py"]
