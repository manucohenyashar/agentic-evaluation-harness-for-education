"""`CT-INTEG-04` — the module writes only integrity signals, and there is no
write path to `band`, `points` or `confidence` (`TC-INTEG-C04`).

Case of test plan §6.11.9; TS-66 (issue #77). Written ahead of `#74`.

The clause: writes **only** integrity signals; there is **no write path** from
this module to `band`, `points`, or `confidence`, and none will be added
(FR-INTEG-08); the entire output surface is **six booleans plus routing
requests**, by set equality. Three limbs, because the clause's risk lives in
the gap between them:

1. **Static** — an AST walk over `src/aeh/integ.py`'s statements: no SQL write
   names a forbidden score column, no attribute store assigns one, and the
   module does not even import the modules that score. This is the limb that
   "holds for paths never exercised" — the reason the clause is a `state`
   clause at all (RISK-38: a write from the wrong module is a legal row).
2. **Dynamic write audit (rung 3)** — `verify()` runs against real SQLite and
   every table's contents are diffed before/after: the delta must sit inside
   the declared routing/metrics surface, and the score-bearing tables
   (`criterion_score`, `verdict`) must not gain a row.
3. **Output surface** — the returned value is the six fields and nothing else;
   the persisted surface is the declared allowlist and nothing else. Set
   equality on both sides, so a seventh signal or an added output field fails.

**Disclosures register**:

| Name | Status |
|---|---|
| `IntegrityGate` / `IntegritySignals` | the #74 keys, reused |
| write-audit surface | real-SQLite table diff (the databases are never doubled, §4.2); the declared touched-tables allowlist is `{work_unit, run_metrics, review_queue}` — the routing requests (ledger and review queue, the plan's declared route destination for empty evidence) and the per-criterion rate rows #75's interface table records. Disclosed: the allowlist is the reconciliation point if `#74` persists signals elsewhere |
| static scanners | local to this file (no test-to-test imports in this suite); they overlap the artifact file `tests/artifact/test_integ_write_set.py` (TC-INTEG-03/10's scanners) deliberately and independently — the clause case is release-gating on CT-INTEG-04 and must not break when that file is reorganized. Scope: the SQL regexes read column-listed `INSERT`/`UPDATE` statements and the AST scan reads attribute stores; a column-list-less `INSERT ... VALUES` or a subscript store is NOT caught statically — the exhaustive half is the dynamic write audit below, which diffs every user table over the exercised paths |
| INFRA allowlist | `#75`'s `INFRA_WRITE_COLUMNS` vocabulary, restated here so the clause case owns its own allowlist and can be disputed line by line |
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from aeh.store import open_store
from tests.contract.integ._doubles import CONTRACT_COHORT, make_gate, byte_span
from tests.support.impl import INTEG_MODULE, require
from tests.support.integ_vocabulary import (
    ExtractionView,
    PanelFlags,
    seed_document,
    document_id_for,
)

pytestmark = pytest.mark.contract

_RUN = "run-integ-c04"
_SUBMISSION = "SUB-C04"
_MARKDOWN = "The answer develops two reasons in plain prose.\n"

#: The write set FR-INTEG-08 spells, and the score columns it forbids.
DECLARED_SIGNALS = frozenset({
    "spans_verified", "evidence_present", "sufficiency_flag",
    "ocr_overlap_risk", "described_evidence", "extractor_disagreement",
})
FORBIDDEN_SCORE_COLUMNS = frozenset({"band", "points", "confidence"})

#: The non-signal columns routing requests legitimately ride on (the #75
#: vocabulary, restated so this case owns its own allowlist): the work ledger's
#: columns, the durable metrics', and the review queue's — the plan's declared
#: destination for the empty-evidence route (TC-INTEG-C07 step 2).
INFRA_WRITE_COLUMNS = frozenset({
    "work_id", "submission_id", "criterion_id", "run_id",
    "stage", "status", "attempts", "origin",
    "metric", "name", "value",
    "queue_id", "reason",
})

#: The tables the write audit may see touched: the work ledger (routing
#: requests), the durable metrics, and the review queue (the routing
#: destination). Everything else — the score-bearing tables first — must be
#: byte-identical across a verify().
TOUCHABLE_TABLES = frozenset({"work_unit", "run_metrics", "review_queue"})
UNTOUCHABLE_TABLES = frozenset({"criterion_score", "verdict", "document", "submission"})

_INSERT_COLUMNS = re.compile(r"INSERT\s+INTO\s+\w+\s*\(([^)]*)\)", re.IGNORECASE)
_UPDATE_SETS = re.compile(r"UPDATE\s+\w+\s+SET\s+(.*?)(?:\bWHERE\b|$)",
                          re.IGNORECASE | re.DOTALL)


def _module_path() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "src" / "aeh" / "integ.py"


def _sql_write_columns(source: str) -> set[str]:
    """Every column name in the module's INSERT column lists and UPDATE sets."""
    def _constants(node: ast.AST) -> "list[str]":
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, ast.JoinedStr):
            return [s for value in node.values for s in _constants(value)]
        return []

    columns: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        for text in _constants(node):
            for match in _INSERT_COLUMNS.finditer(text):
                columns.update(col.strip().strip('"').strip("'")
                               for col in match.group(1).split(",") if col.strip())
            for match in _UPDATE_SETS.finditer(text):
                for assignment in match.group(1).split(","):
                    if "=" in assignment and ":=" not in assignment:
                        columns.add(assignment.split("=")[0].strip().strip('"'))
    return columns


# --- limb 1: the static prohibition ---------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_integ_c04_no_statement_of_the_module_writes_a_score_column():
    """`TC-INTEG-C04` — the prohibition as a static assertion over the module's
    statements, so it holds for paths never exercised: no INSERT column list or
    UPDATE assignment names `band`, `points` or `confidence`; no attribute
    store assigns them; and the module does not import the modules that score
    — reaching for the scorer is the write path one refactor away."""
    require(INTEG_MODULE, issue="#74")  # the module file is the artifact under scan
    path = _module_path()
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    written = _sql_write_columns(source)
    assert not (written & FORBIDDEN_SCORE_COLUMNS), (
        f"the module's SQL writes {sorted(written & FORBIDDEN_SCORE_COLUMNS)} — a "
        "write path to a score field exists in a statement no test exercised "
        "(FR-INTEG-08 forbids it outright; RISK-38: a write from the wrong module "
        "is a legal row)"
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            assert node.attr not in FORBIDDEN_SCORE_COLUMNS, (
                f"{path.name} assigns .{node.attr} at line {node.lineno} — the "
                "prohibition is the whole point of CT-INTEG-04"
            )
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {node.module for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module}
    touched = imported & {"aeh.agg", "aeh.grade"}
    assert not touched, (
        f"M-INTEG imports {sorted(touched)} — the module that certifies evidence must "
        "not even reach for the modules that score it (R19's separation)"
    )


@pytest.mark.writtenahead
def test_tc_integ_c04_the_persisted_write_set_is_exactly_signals_plus_routing():
    """`TC-INTEG-C04` — the write set by set equality: every column the
    module's SQL writes is one of the six signals or the declared routing
    plumbing — an eighth column, a seventh signal, or a score column each fail
    rather than slide under the allowlist."""
    require(INTEG_MODULE, issue="#74")
    written = _sql_write_columns(_module_path().read_text(encoding="utf-8"))
    unexpected = written - INFRA_WRITE_COLUMNS - DECLARED_SIGNALS
    assert not unexpected, (
        f"the module's SQL writes columns {sorted(unexpected)} outside the six "
        f"signals and the routing plumbing {sorted(INFRA_WRITE_COLUMNS)} — the "
        "output surface is six booleans plus routing requests, exactly (CT-INTEG-04)"
    )
    assert written, (
        "the module's source names no SQL write at all — either the routing requests "
        "ride a seam this case does not know, or the scan is vacuous; both need a "
        "reconcile-at-landing conversation rather than a green light"
    )


def test_tc_integ_c04_the_write_scan_has_teeth():
    """`TC-INTEG-C04`'s executable construction — the static scanner is proven
    against a synthetic violating module NOW, so the #74 landing cannot satisfy
    the case with a scan that sees nothing. Runs green: it asserts the scanner's
    teeth, not the implementation."""
    violator = (
        "def score():\n"
        "    handle.query(\"INSERT INTO criterion_score (criterion_id, band, points, "
        "confidence) VALUES (?, ?, ?, ?)\")\n"
        "    handle.query(\"UPDATE work_unit SET status = :s WHERE work_id = :w\")\n"
    )
    written = _sql_write_columns(violator)
    assert {"band", "points", "confidence", "status"} <= written, (
        f"the scanner missed columns of a known violator: {sorted(written)} — the "
        "static limb's oracle is blind and the whole case is vacuous"
    )
    assert written & FORBIDDEN_SCORE_COLUMNS, (
        "the scanner failed to see the forbidden score columns the mutant writes"
    )


# --- limb 2: the dynamic write audit (rung 3) -----------------------------------------------


def _table_dump(handle) -> dict[str, set]:
    """Every user table's full contents, as comparable row-frozensets."""
    dump: dict[str, set] = {}
    tables = [row["name"] for row in handle.query(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%'")]
    for table in tables:
        rows = handle.query(f"SELECT * FROM {table}")  # noqa: S608 - fixed names
        dump[table] = {repr(sorted((key, row[key]) for key in row.keys()))
                       for row in rows}
    return dump


def _assert_write_audit_covers_only_declared_surface(tmp_data_dir, view) -> None:
    """One verify() under a full-database write audit: the delta sits inside
    the declared surface, and the score-bearing tables gain nothing."""
    store = open_store(tmp_data_dir)
    handle = store.cohort(CONTRACT_COHORT)
    seed_document(handle, document_id_for(_SUBMISSION), _SUBMISSION, _MARKDOWN,
                  CONTRACT_COHORT)
    before = _table_dump(handle)
    gate, store2 = make_gate(tmp_data_dir, view)
    gate.verify(_RUN, _SUBMISSION, "C1")
    after = _table_dump(handle)
    store.close()
    store2.close()

    touched = {table for table in after if after[table] != before.get(table, set())}
    unexpected = touched - TOUCHABLE_TABLES
    assert not unexpected, (
        f"verify() wrote to {sorted(unexpected)} — the module's write surface is six "
        "booleans plus routing requests (CT-INTEG-04); the audit diffs every user "
        "table, so a write to any other table fails here"
    )
    violated = [table for table in UNTOUCHABLE_TABLES
                if after.get(table, set()) - before.get(table, set())]
    assert not violated, (
        f"score-bearing or upstream tables gained rows under verify(): {sorted(violated)} "
        "— the write audit's whole reason to exist"
    )
    assert touched, (
        "verify() wrote nothing anywhere — the routing requests the clause grants the "
        "module are part of its declared surface, and a scan that sees none cannot "
        "distinguish restraint from a broken seam; reconcile at #74's landing"
    )


@pytest.mark.writtenahead
def test_tc_integ_c04_a_healthy_verify_writes_only_within_the_declared_surface(
        tmp_data_dir):
    """`TC-INTEG-C04` limb 2, healthy run — the write audit over real SQLite:
    only the ledger and the metrics table move, the score-bearing tables gain
    nothing."""
    span = byte_span(_MARKDOWN, "reasons")
    view = ExtractionView(
        spans=(span,),
        regions=(),
        panel=PanelFlags((True, True, True)),
    )
    _assert_write_audit_covers_only_declared_surface(tmp_data_dir, view)


@pytest.mark.writtenahead
def test_tc_integ_c04_a_routing_verify_never_touches_the_score_tables(tmp_data_dir):
    """`TC-INTEG-C04` limb 2, routing run — empty evidence on a
    citation-requiring criterion: the routing request is the write, and the
    audit still sees nothing in `criterion_score` or `verdict` — the
    prohibition carried by the clause, observed rather than assumed."""
    view = ExtractionView(
        spans=(),
        regions=(),
        panel=PanelFlags((True, True, True)),
        evidence_type_requires_citation=True,
    )
    _assert_write_audit_covers_only_declared_surface(tmp_data_dir, view)


# --- limb 3: the returned output surface ----------------------------------------------------


@pytest.mark.writtenahead
def test_tc_integ_c04_the_returned_output_surface_is_the_six_fields(tmp_data_dir):
    """`TC-INTEG-C04` limb 3 — what `verify()` RETURNS is the six booleans and
    nothing else: set equality over the instance's public attributes, so an
    added output field (a suggested band, a confidence hint, a message) fails
    rather than rides along."""
    IntegritySignals = require(INTEG_MODULE, "IntegritySignals", issue="#74")
    span = byte_span(_MARKDOWN, "reasons")
    view = ExtractionView(spans=(span,), regions=(),
                          panel=PanelFlags((True, True, True)))
    gate, store = make_gate(tmp_data_dir, view)
    signals = gate.verify(_RUN, _SUBMISSION, "C1")
    store.close()
    public = {name for name in dir(signals)
              if not name.startswith("_") and not callable(getattr(signals, name, None))}
    assert public == set(DECLARED_SIGNALS), (
        f"verify() returned the surface {sorted(public)}; the clause fixes six "
        "booleans plus routing requests — and routing requests ride the ledger, not "
        "the return value (an added output field fails here by set equality)"
    )
    assert isinstance(signals, IntegritySignals)
