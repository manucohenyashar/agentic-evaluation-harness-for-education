"""`TC-INTEG-03` — empty evidence on a citation-requiring criterion routes and can never
become a low band — and `TC-INTEG-10` — the module's import and write graph contains no
path to `band`, `points` or `confidence`.

Test plan §5.9 block forms (both P0, both `FR-INTEG-08`'s prohibition). Written ahead of
`#74` (test plan §8.2): every case fails only through `NotImplementedYet` naming `#74`.

**The prohibition half is static on purpose.** Steps 2 and 3 of TC-INTEG-03 and the
whole of TC-INTEG-10 are *artifact assertions*: an AST walk and an import scan over
`src/aeh/integ.py` itself, so they hold for code paths no test exercises — a dynamic
write-audit would only prove the paths the suite happened to drive, which is exactly
the hole a `band` write smuggled into an untested branch would hide in. The static half
cannot prove nothing writes a band anywhere in the process (the behavioral limb drives
`verify()` and asserts the routing outcome), and it is not asked to: FR-INTEG-08 is
about *this module's* write surface, and this module is one file.

**The write set is asserted by set equality** (CT-INTEG-04: "its entire output surface
is six booleans plus routing requests"), so a seventh column or an added output field
fails the case rather than sliding under it.

Interface assumed of `#74` (reconcile at landing): the module file at `src/aeh/integ.py`;
`IntegrityGate(handle, blobs, view, ocr_conf_floor=...)` with
`verify(run_id, submission_id, criterion_id)` (see `tests/support/integ_vocabulary.py`);
routing observed as `#74`'s contract implies — a citation-requiring criterion with no
verifiable evidence leaves a **re-extraction request in the work ledger** (a pending
`extract` unit for the same (submission, criterion), which FR-INTEG-02's retry loop
consumes), and no `criterion_score` row for it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from aeh.store import open_store
from tests.support.impl import INTEG_MODULE, require
from tests.support.integ_vocabulary import (
    Doc,
    ExtractionView,
    PanelFlags,
    Span,
    document_id_for,
    seed_document,
)



_RUN = "run-integ-2026-7B"
_COHORT = "c-2026-7B-integ"

#: The write set FR-INTEG-08 spells: exactly these six, nothing else, and no path to
#: band, points or confidence.
DECLARED_WRITE_SET = frozenset({
    "spans_verified",
    "evidence_present",
    "sufficiency_flag",
    "ocr_overlap_risk",
    "described_evidence",
    "extractor_disagreement",
})

FORBIDDEN_SCORE_COLUMNS = frozenset({"band", "points", "confidence"})

#: The non-signal columns the module's routing requests legitimately ride on — the
#: work-ledger and run-metrics plumbing, plus the review queue's (the plan's declared
#: destination for the empty-evidence route). Everything else the SQL writes must be one
#: of the six signals (the reverse half of the set-equality assertion).
INFRA_WRITE_COLUMNS = frozenset({
    "work_id", "submission_id", "criterion_id", "run_id",
    "stage", "status", "attempts", "origin",
    "metric", "name", "value",
    "queue_id", "reason",
})

_INSERT_COLUMNS = re.compile(r"INSERT\s+INTO\s+\w+\s*\(([^)]*)\)", re.IGNORECASE)
_UPDATE_SETS = re.compile(r"UPDATE\s+\w+\s+SET\s+(.*?)(?:\bWHERE\b|$)",
                          re.IGNORECASE | re.DOTALL)


def _sql_write_columns(source: str) -> set[str]:
    """Every column name in the module's INSERT column lists and UPDATE assignments.

    Scans string constants (including f-string parts) for INSERT/UPDATE statements and
    pulls the actual column names out, rather than only checking whether the names it
    already knows appear — that one-sidedness is what let a seventh persisted signal
    through (review finding). Limitation, disclosed: a column list assembled entirely
    from interpolated values is invisible here, which is why the behavioral limb and
    the TC-INTEG-07 routing cases exist alongside this scan.
    """

    def _constants(node: ast.AST) -> "list[str]":
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, ast.JoinedStr):
            return [s for value in node.values for s in _constants(value)]
        return []

    columns: set[str] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) and not isinstance(node, ast.JoinedStr):
            continue
        for text in _constants(node):
            for match in _INSERT_COLUMNS.finditer(text):
                columns.update(
                    col.strip().strip('"').strip("'")
                    for col in match.group(1).split(",")
                    if col.strip()
                )
            for match in _UPDATE_SETS.finditer(text):
                for assignment in match.group(1).split(","):
                    if "=" in assignment and ":=" not in assignment:
                        columns.add(assignment.split("=")[0].strip().strip('"'))
    return columns


def _module_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "src" / "aeh" / "integ.py"


# --- the static artifact assertions (TC-INTEG-03 steps 2-3, TC-INTEG-10) -------------------

def _stored_write_targets(source: str, tree: ast.AST) -> set[str]:
    """Every name the module's AST shows it assigning as an integrity signal or a score
    column: attribute stores (`row.band = ...`), dict-literal stores for row payloads,
    and the column names in INSERT/UPDATE SQL strings."""
    targets: set[str] = set()
    for node in ast.walk(tree):
        # attribute stores: anything.band / .points / .confidence = ... and the six
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            targets.add(node.attr)
        # dataclass field writes via setattr or dict keys for row payloads
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in DECLARED_WRITE_SET or node.value in FORBIDDEN_SCORE_COLUMNS:
                targets.add(node.value)
        # SQL: the column lists of INSERT INTO ... (...) and UPDATE ... SET ...
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value.upper()
            if "INSERT INTO" in text or "UPDATE " in text:
                for name in DECLARED_WRITE_SET | FORBIDDEN_SCORE_COLUMNS:
                    if name.upper() in text:
                        targets.add(name)
    return targets


def _imported_modules(tree: ast.AST) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_tc_integ_10_module_has_no_import_or_write_path_to_score_fields():
    """`TC-INTEG-10` (P0) — no import of, or write path to, `criterion_score.band`,
    `.points` or `.confidence`: an AST walk over the module's statements, so it holds
    for paths no test exercises."""
    require(INTEG_MODULE, issue="#74")  # the module file itself is the artifact under scan
    path = _module_path()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported = _imported_modules(tree)
    scoring_consumers = {"aeh.agg", "aeh.grade"}
    touched = imported & scoring_consumers
    assert not touched, (
        f"M-INTEG imports {sorted(touched)} — the module that certifies evidence must "
        "not even reach for the module that scores it (FR-INTEG-08, R19's separation)"
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            assert node.attr not in FORBIDDEN_SCORE_COLUMNS, (
                f"{path.name} assigns .{node.attr} at line {node.lineno} — a write path "
                "to a score field exists (FR-INTEG-08 forbids it outright)"
            )


def test_tc_integ_03_step_2_write_set_is_exactly_the_six_signals():
    """`TC-INTEG-03` step 2 — enumerate every write this module performs and assert the
    write set is exactly the six booleans: set equality, so a seventh signal or a
    smuggled score column fails rather than slides under."""
    require(INTEG_MODULE, issue="#74")
    path = _module_path()
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    attribute_targets = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store)
    }
    stored = _stored_write_targets(source, tree)
    score_writes = stored & FORBIDDEN_SCORE_COLUMNS
    assert not score_writes, (
        f"the module's write set reaches {sorted(score_writes)} — the prohibition is "
        "the whole point (CT-INTEG-07's clause, RISK-03)"
    )
    # The signal half of the write set must be covered by the six names and nothing
    # outside them that names a persisted column. Attribute stores on internal objects
    # are permitted (caches, parsed payloads); a *persisted* name is what the SQL and
    # dict-literal scan above catches. Assert the six are all present as a set.
    assert DECLARED_WRITE_SET <= (stored | attribute_targets), (
        f"the module never names {sorted(DECLARED_WRITE_SET - (stored | attribute_targets))} "
        "— a declared signal the write set cannot place is a signal computed nowhere"
    )
    # The REVERSE direction (review finding): every column the module's SQL actually
    # writes — INSERT column lists, UPDATE assignments — must be one of the six
    # signals or declared routing/ledger plumbing. Without it, a seventh persisted
    # signal (an INSERT INTO ... (criterion_id, hallucination_suspected)) is collected
    # by neither scan, because the known-name scan only looks for names it already
    # knows. The plumbing allowlist is the routing-request surface the write set
    # rides on (work-ledger and run-metrics rows), spelled out so a reviewer can
    # dispute it rather than discover it.
    written_columns = _sql_write_columns(source)
    unexpected = written_columns - INFRA_WRITE_COLUMNS - DECLARED_WRITE_SET
    assert not unexpected, (
        f"the module's SQL writes columns {sorted(unexpected)} outside the six signals "
        f"and the routing plumbing {sorted(INFRA_WRITE_COLUMNS)} — the write set is six "
        "booleans plus routing requests, exactly (CT-INTEG-04)"
    )


def test_tc_integ_03_step_3_no_lowest_band_path_from_empty_evidence():
    """`TC-INTEG-03` step 3 — search the module for any code path producing a
    lowest-band verdict from empty evidence: a static scan for the score-writing
    vocabulary, plus the import prohibition above. The module's source must not contain
    a band-mapping call at all; 'empty evidence with a low band' is then unreachable
    from this module by construction, not by coverage."""
    require(INTEG_MODULE, issue="#74")
    path = _module_path()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"band", "points_for_band", "apply_policy"}, (
                f"{path.name} calls .{node.func.attr}() at line {node.lineno} — a "
                "band-mapping path inside M-INTEG is the lowest-band verdict by "
                "another name (FR-INTEG-03)"
            )


# --- the behavioral limb (TC-INTEG-03 step 1, plus its variant) -----------------------------

_MARKDOWN = "The answer is forty-two.\nA second sentence for coverage.\n"


def _seeded_store(tmp_data_dir, submission_id: str) -> Doc:
    store = open_store(tmp_data_dir)
    doc = Doc(markdown=_MARKDOWN)
    seed_document(store.cohort(_COHORT), document_id_for(submission_id), submission_id,
                  doc.markdown, _COHORT)
    store.close()
    return doc


def _gate(tmp_data_dir, view):
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#74")
    store = open_store(tmp_data_dir)
    handle = store.cohort(_COHORT)
    return IntegrityGate(handle, store.blobs(), view, ocr_conf_floor=0.70), store


def _pending_extract_units(store, submission_id: str, criterion_id: str) -> list[dict]:
    return store.cohort(_COHORT).query(
        "SELECT work_id, status, attempts FROM work_unit WHERE submission_id = :s AND "
        "criterion_id = :c AND stage = 'extract' AND status IN ('pending', 'leased')",
        s=submission_id,
        c=criterion_id,
    )


def _fresh_retries(store, submission_id: str, criterion_id: str) -> list[dict]:
    """Re-extraction requests the GATE created — attempts grown past the original
    enumeration's zero, the same discriminator TC-INTEG-02 uses. Without it, a gate
    that writes nothing at all passes a 'pending row exists' check, because the
    orchestrator's original extract unit is itself pending (review finding)."""
    return [u for u in _pending_extract_units(store, submission_id, criterion_id)
            if u["attempts"] >= 1]


def _score_rows(store, submission_id: str, criterion_id: str) -> list[dict]:
    return store.cohort(_COHORT).query(
        "SELECT * FROM criterion_score WHERE submission_id = :s AND criterion_id = :c",
        s=submission_id,
        c=criterion_id,
    )


def test_tc_integ_03_empty_evidence_on_citation_requiring_criterion_routes(tmp_data_dir):
    """`TC-INTEG-03` step 1 — a citation-requiring criterion whose extraction carried
    zero spans: routed with `evidence_present = False`, a re-extraction request in the
    ledger, and no `criterion_score` row — never auto-scored."""
    doc = _seeded_store(tmp_data_dir, "SUB-001")
    view = ExtractionView(spans=(), panel=PanelFlags((True, True, True)),
                          evidence_type_requires_citation=True)
    gate, store = _gate(tmp_data_dir, view)
    signals = gate.verify(_RUN, "SUB-001", "C1")
    assert signals.evidence_present is False
    assert signals.spans_verified is False
    routed = _fresh_retries(store, "SUB-001", "C1")
    assert routed, (
        "empty evidence on a citation-requiring criterion produced no NEW re-extraction "
        "request — absence of evidence is a routing condition, not a score input "
        "(FR-INTEG-03, R13); a pre-existing pending row from enumeration is not a route"
    )
    assert not _score_rows(store, "SUB-001", "C1"), (
        "a criterion_score row exists for evidence the module just routed — the "
        "lowest-band path CT-INTEG-07 calls the single most consequential negative "
        "clause in this module"
    )
    store.close()


def test_tc_integ_03_criterion_not_requiring_citation_is_not_routed_for_citation(tmp_data_dir):
    """`TC-INTEG-03`'s control — a criterion whose `evidence_type` does not require a
    citation and whose extraction carried no spans: `evidence_present` is still False
    (it is a measurement, not a verdict), but the citation route is not the mechanism
    that fires; the case pins the distinction so the flag cannot silently become the
    route for every criterion."""
    doc = _seeded_store(tmp_data_dir, "SUB-002")
    view = ExtractionView(spans=(), panel=PanelFlags((True, True, True)),
                          evidence_type_requires_citation=False)
    gate, store = _gate(tmp_data_dir, view)
    signals = gate.verify(_RUN, "SUB-002", "C1")
    assert signals.evidence_present is False
    assert not _fresh_retries(store, "SUB-002", "C1"), (
        "a criterion whose evidence_type does not require a citation was routed for "
        "re-extraction — the flag cannot silently become the route for every criterion, "
        "or the control distinguishes nothing (review finding; if #74 routes this case "
        "by another mechanism, that is a reconcile-at-landing conversation)"
    )
    assert not _score_rows(store, "SUB-002", "C1"), (
        "no criterion_score row may exist while signals are unset or adverse — the "
        "module never writes one (FR-INTEG-08); scoring happens downstream or not at all"
    )
    store.close()


def test_tc_integ_03_evidence_present_but_every_span_failing_routes_not_scores(tmp_data_dir):
    """`TC-INTEG-03`'s variant — spans extracted but every one failing verification:
    must route, not score. `evidence_present` is False (no span SURVIVED verification —
    evidence is what the check certified, not what the extractor claimed; reconciled at
    #74's landing) while `spans_verified` is False; the unit goes back for re-extraction
    and no score row appears."""
    doc = _seeded_store(tmp_data_dir, "SUB-003")
    hallucinated = (Span(0, 5, "nope!"),)  # bytes that are not in the document
    view = ExtractionView(spans=hallucinated, panel=PanelFlags((True, True, True)),
                          evidence_type_requires_citation=True)
    gate, store = _gate(tmp_data_dir, view)
    signals = gate.verify(_RUN, "SUB-003", "C1")
    assert signals.evidence_present is False
    assert signals.spans_verified is False
    routed = _fresh_retries(store, "SUB-003", "C1")
    assert routed, (
        "evidence whose every span failed verification did not route — verified-or-not "
        "is the gate that matters (FR-INTEG-02), and present-but-unverified is exactly "
        "the hallucination case RISK-01 names"
    )
    assert not _score_rows(store, "SUB-003", "C1")
    store.close()
