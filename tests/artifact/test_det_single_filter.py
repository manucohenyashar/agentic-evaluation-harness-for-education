"""`TC-DET-09` — the statistical-separation filter of `FR-DET-09`/`NFR-DET-03` exists in
exactly one place and is reused by every statistics consumer. Test plan §5.11; issue
#88.

Oracle: **import-graph (artifact) assertion** over the source tree — parsed, not grepped
(the same reasoning `tests/support/import_graph.py` records: an aliased or
function-scoped re-spelling is invisible to a line scan, and comments are not in the AST
at all).

What the case pins:

1. **One definition** — the exclusion predicate
   `label.evaluation_mode <> 'deterministic'` appears ONLY in `aeh.det`, bound to the
   module constant `DETERMINISTIC_EXCLUSION`; the canonical statement's literal copy is
   tied to that constant by det's import-time assert (re-asserted here), so the two
   occurrences are one definition and its one bound composition — not two filters.
2. **No second filter** — no other `aeh` module carries any SQL against the `label`
   table's mode column, so no consumer can re-spell the exclusion at a call site.
3. **Reuse is reachable** — the composed statement is registered in the store's
   statement registry under its own name, which is the path every statistics consumer
   (`M-STATS`'s κ / α / grader-quality figures included) is required to take.
"""

from __future__ import annotations

import ast
from pathlib import Path

from aeh.det import DETERMINISTIC_EXCLUSION, DET_STATEMENTS
from aeh.store import STATEMENTS

ISSUE = "#88"

#: The exact exclusion predicate `FR-DET-09` requires. A drift in either direction — a
#: re-spelled predicate or a weakened one — changes this string and fails the case.
EXCLUSION_PREDICATE = "label.evaluation_mode <> 'deterministic'"

_SRC = Path(__file__).resolve().parents[2] / "src" / "aeh"


def _modules_with(predicate):
    """Every `aeh` module whose AST holds a string constant matching the predicate.

    Triple-quoted f-strings, joined constants and aliased definitions all reduce to
    `ast.Constant` string nodes, so this catches every form a re-spelling can take
    short of runtime concatenation — which `SEC-15`'s assembled-SQL rule already
    refuses at the store boundary.
    """
    hits = []
    for path in sorted(_SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if predicate(node.value):
                    hits.append(path.name)
                    break
    return hits


def test_tc_det_09_the_exclusion_filter_is_defined_exactly_once():
    """The predicate exists in exactly one module, bound to the constant — and the
    statement's copy is the constant, tied by det's import-time assert."""
    carrying = _modules_with(
        lambda text: "evaluation_mode <>" in text and "'deterministic'" in text
    )
    assert carrying == ["det.py"], (
        f"the deterministic-exclusion predicate appears in {carrying} — NFR-DET-03 "
        "requires ONE definition that every statistics consumer reuses, and a second "
        "site is a filter that can drift from the first"
    )
    assert DETERMINISTIC_EXCLUSION == EXCLUSION_PREDICATE

    # The canonical statement's literal copy IS the constant (the same tie det asserts
    # at import; re-asserted here so the case fails on its own if the composition
    # loosens).
    canonical = str(DET_STATEMENTS["select_agreement_labels"])
    assert EXCLUSION_PREDICATE in canonical
    assert "label_type = 'blind'" in canonical, (
        "the canonical agreement query lost the blind-label half of the conjunction "
        "(NFR-STATS-04) — the filter is a pair, and half a pair is a leak"
    )


def test_tc_det_09_no_other_module_touches_the_label_mode():
    """No other `aeh` module holds SQL against the label table's mode column — the
    exclusion cannot be bypassed by a consumer re-spelling it at a call site."""
    touching = _modules_with(
        lambda text: "label" in text and "evaluation_mode" in text
    )
    assert touching == ["det.py"], (
        f"{touching} reference the label table's mode column outside det.py — a "
        "statistics consumer is spelling its own exclusion instead of importing the "
        "one filter (NFR-DET-03)"
    )


def test_tc_det_09_the_composed_filter_is_registered_for_consumers():
    """Reuse is reachable: the canonical composed query is registered in the store's
    statement registry under its own name — the path every statistics consumer takes
    (`M-STATS`'s κ / α / grader-quality figures included) — and the constant is
    importable for composition, never re-spelling."""
    assert str(STATEMENTS["select_agreement_labels"]) == str(
        DET_STATEMENTS["select_agreement_labels"]
    )
    assert EXCLUSION_PREDICATE in str(STATEMENTS["select_agreement_labels"])
