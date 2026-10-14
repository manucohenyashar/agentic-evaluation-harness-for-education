"""TC-REQ-138 — the forbidden-term constant and the design's vocabulary map cannot drift.

Test plan §3.7 (issue #774): *"The forbidden-term test constant and the design's
vocabulary-map left column are parsed from the design delta itself and asserted equal — the
map cannot drift from the scan silently."*

TC-CONSOLE-74's census scans against `FORBIDDEN_TERMS` (`tests/support/redesign_vocabulary.py`),
a transcription of design delta §3.3.3's left column. A transcription nobody re-checks is a
second copy waiting to rot: the design could gain a row, rename one, or drop one, and the
census would keep scanning the stale list — green, and blind to exactly the leak the map was
extended to name. This case parses the design delta's §3.3.3 table itself and asserts
equality **in both directions** — containment alone would stay green when a row is dropped
from the *constant*, which is the direction that silently narrows the census.

The design is also the map's *right* column's source: the census deliberately does not scan
the left column's bare words (the map's own right column uses them — "Test package",
"Approve final grades / Final", "Not final yet" — so a word-level scan would condemn the
copy the design itself mandates). The scannable rows are the six families
(`redesign_vocabulary.SCAN_FAMILIES`); this case keeps the *list* honest so the families
stay anchored to the design.

Isolation rung 0 (contract): the repository's own documents against the test-support
constant — no store, no console, no browser.
"""

from __future__ import annotations

import pytest

from tests.support import redesign_vocabulary
from tests.support.doc_tables import markdown_rows, read_repo_text

pytestmark = pytest.mark.contract

DELTA = "docs/design/console_redesign_design_delta.md"
HEADING = "#### 3.3.3 The vocabulary map (R0)"
HEADER_CELL = "Internal term (forbidden on teacher surfaces)"


def test_tc_req_138_the_forbidden_term_constant_equals_the_vocabulary_maps_left_column(
        repo_root):
    """`FORBIDDEN_TERMS` is §3.3.3's left column, verbatim and in the document's order."""
    delta = read_repo_text(repo_root, DELTA)

    # The heading is asserted first, with the reason: a moved or renamed section must fail
    # here as a finding, not silently empty the slice below — an empty parse would read as
    # "the map shrank to nothing", not as "the fixture lost its anchor".
    assert HEADING in delta, (
        "the design delta's §3.3.3 vocabulary-map heading is gone. The census imports its "
        "term list from that table, so if the section moved, update `HEADING`; if the map "
        "was removed, that is the defect this case exists to catch."
    )
    section = delta[delta.index(HEADING):]
    section = section[:section.index("\n#### ", 1)]

    rows = markdown_rows(section)
    # Two cells per row (internal term | teacher label); the header row is dropped by its
    # own cell text so it can never masquerade as a term.
    declared = [row[0] for row in rows if len(row) == 2 and row[0] != HEADER_CELL]
    assert declared, "§3.3.3's vocabulary-map table parsed to zero rows"

    constant = list(redesign_vocabulary.FORBIDDEN_TERMS)
    missing_from_constant = [term for term in declared if term not in constant]
    absent_from_design = [term for term in constant if term not in declared]
    assert not missing_from_constant and not absent_from_design, (
        "the design's forbidden-term list and the census's constant disagree — "
        f"only in the design: {missing_from_constant}; "
        f"only in the constant: {absent_from_design}. The census scans the constant, so "
        "either side moving alone silently narrows or silently invents coverage. Update "
        "both together: the design first, then the transcription."
    )
    assert declared == constant, (
        "the two sides agree as sets but differ in order or carry a duplicate. The "
        "constant is transcribed in the document's order deliberately (a reviewer diffing "
        "it against §3.3.3 reads both top to bottom): design declares "
        f"{declared}; the constant carries {constant}."
    )
