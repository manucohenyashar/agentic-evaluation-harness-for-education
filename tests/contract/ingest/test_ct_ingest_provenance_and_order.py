"""`CT-INGEST-07` — provenance and the order ladder (`TC-INGEST-C07`).

Case of test plan §6.11.5; issue #49 (TS-62). Green by design — #36/#37 landed
assembly with the ladder; the sweep holds the §4.7 clause.

The clause has three halves:

1. **The provenance triple**: every stored region carries `page_no`,
   `source_hash` and `page_index`, and the document's `source_blobs` records
   per-page provenance — the crop a graphic's `crop_ref` names is resolved
   against the SAME source (`CT-INGEST-04`'s crop half pins resolvability; here
   it is the triple's consistency that is asserted).
2. **The order ladder is a strict preference**: operator > printed page number >
   fiducial marker > filename > refuse. A decision table — the higher tier wins
   exactly when it is complete, each decided outcome is RECORDED on the
   document's provenance as `order_source`, and incompleteness at a tier falls
   through rather than half-fires.
3. **Directory order is never read**: no `os.listdir` / `iterdir` / `scandir` /
   `glob` call exists in the module (the AST half), and the behavioural
   differential — the same blobs with the caller's filename map permuted —
   produces the permuted page order, never an insertion-order artifact.

Discriminator: the ladder's refusals and the recorded `order_source` go red if
the clause breaks (a directory read sneaks in, a tier half-fires, the operator
tier is ignored) while the FR cases — which pin one tier each at the call level
— stay green.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from aeh.ingest import (
    IngestError,
    IngestGapError,
    IngestOrderError,
)
from tests.contract.ingest._doubles import (
    ISSUE,
    Contract,
    answer_text,
    student_answer,
)
from tests.support.store_api import statement

pytestmark = pytest.mark.contract

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _page_with_number(number: int, total: int, body: str) -> str:
    return f"Page {number} of {total}\n{body}"


def _page_with_marker(marker: str, body: str) -> str:
    return f"[fiducial:{marker}]\n{body}"


# -- the provenance triple ---------------------------------------------------------------------------


def test_tc_ingest_c07_every_region_carries_the_provenance_triple(tmp_data_dir):
    """`TC-INGEST-C07` step 1 — every stored region carries `page_no`,
    `source_hash` and `page_index`, the hashes resolve into the document's
    recorded per-page provenance, and the provenance's positions are the
    assembly order (1..N over every page the document holds)."""
    fx = Contract(tmp_data_dir, "c07-provenance")
    fx.add_roster("gus")
    first = fx.put(b"c07 first pdf")
    second = fx.put(b"c07 second pdf")
    fx.script(first, {1: student_answer("gus", answer_text("Q1", "part one"))})
    fx.script(second, {1: student_answer(None, answer_text("Q2", "part two"))})
    document_id = fx.ingestor.ingest_document(
        [first, second], kind="submission", order_hint=[first, second])
    document = fx.documents("document_id = :d", d=document_id)[0]
    regions = fx.regions(document_id)
    assert len(regions) >= 2, (
        f"TC-INGEST-C07: expected regions from both pages, got {len(regions)}."
    )
    for row in regions:
        assert row["page_no"] is not None and row["page_no"] >= 1, (
            f"TC-INGEST-C07: a region carries page_no {row['page_no']!r}."
        )
        assert row["source_hash"], (
            "TC-INGEST-C07: a region carries no source_hash — its provenance "
            "triple is incomplete."
        )
        assert row["page_index"] == row["page_no"], (
            f"TC-INGEST-C07: page_index {row['page_index']!r} disagrees with "
            f"page_no {row['page_no']!r} for a same-numbered page."
        )
    provenance = json.loads(document["source_blobs"])
    recorded_hashes = {entry["blob_hash"] for entry in provenance["pages"]}
    assert {row["source_hash"] for row in regions} <= recorded_hashes, (
        "TC-INGEST-C07: a region's source_hash is not covered by the "
        "document's recorded provenance."
    )
    positions = sorted(entry["position"] for entry in provenance["pages"])
    assert positions == list(range(1, len(positions) + 1)), (
        f"TC-INGEST-C07: provenance positions are not 1..N over the document: "
        f"{positions}."
    )
    fx.close()


# -- the order ladder: a strict preference, decided and recorded -------------------------------------


def test_tc_ingest_c07_the_operator_tier_wins_and_is_recorded(tmp_data_dir):
    """`TC-INGEST-C07` step 2, row 1 — an operator-stated order wins over every
    other signal (the pages carry BOTH printed numbers and filenames that say
    the opposite), and the decision is recorded as `order_source: operator`."""
    fx = Contract(tmp_data_dir, "c07-operator")
    fx.add_roster("gus")
    first = fx.put(b"c07 op first")
    second = fx.put(b"c07 op second")
    fx.script(first, {1: _page_with_number(2, 2, "second page body")})
    fx.script(second, {1: _page_with_number(1, 2, "first page body")})
    document_id = fx.ingestor.ingest_document(
        [first, second], kind="submission", order_hint=[second, first],
        filenames={first: "zz.pdf", second: "aa.pdf"})
    markdown = fx.documents("document_id = :d", d=document_id)[0]["markdown"]
    assert markdown.index("first page body") < markdown.index(
        "second page body"), (
        "TC-INGEST-C07: the operator-stated order was not followed — the "
        "ladder's first tier lost."
    )
    provenance = json.loads(fx.documents(
        "document_id = :d", d=document_id)[0]["source_blobs"])
    assert provenance["order_source"] == "operator", (
        f"TC-INGEST-C07: order_source recorded as "
        f"{provenance['order_source']!r}, not 'operator'."
    )
    fx.close()


def test_tc_ingest_c07_the_page_number_tier_sorts_numerically_and_records(
        tmp_data_dir):
    """`TC-INGEST-C07` step 2, row 2 — with no operator tier, printed page
    numbers decide: page 2 before page 10 (numeric, not lexicographic), and the
    decision is recorded as `order_source: page_number`."""
    fx = Contract(tmp_data_dir, "c07-pageno")
    fx.add_roster("gus")
    # Ten pages of a declared ten: the gap gate requires the complete sequence,
    # and 2-vs-10 is the pair where lexicographic and numeric order disagree.
    blobs = {number: fx.put(f"c07 page {number}".encode())
             for number in range(1, 11)}
    for number, source in blobs.items():
        fx.script(source, {1: _page_with_number(number, 10, f"body {number}")})
    document_id = fx.ingestor.ingest_document(
        [blobs[10], blobs[1], blobs[2]] + [blobs[n] for n in range(3, 11)
                                           if n not in (10,)],
        kind="submission")
    markdown = fx.documents("document_id = :d", d=document_id)[0]["markdown"]
    assert markdown.index("body 2") < markdown.index("body 10"), (
        "TC-INGEST-C07: page 10 sorted before page 2 — the tier is "
        "lexicographic where the clause demands numeric."
    )
    provenance = json.loads(fx.documents(
        "document_id = :d", d=document_id)[0]["source_blobs"])
    assert provenance["order_source"] == "page_number", (
        f"TC-INGEST-C07: order_source recorded as "
        f"{provenance['order_source']!r}, not 'page_number'."
    )
    fx.close()


def test_tc_ingest_c07_the_marker_tier_sorts_naturally_and_records(tmp_data_dir):
    """`TC-INGEST-C07` step 2, row 3 — fiducial markers decide when no higher
    tier is complete: `[fiducial:page-10]` after `[fiducial:page-2]`, recorded
    as `order_source: marker`."""
    fx = Contract(tmp_data_dir, "c07-marker")
    fx.add_roster("gus")
    blobs = {marker: fx.put(f"c07 marker {marker}".encode())
             for marker in ("page-2", "page-10", "page-1")}
    for marker, source in blobs.items():
        fx.script(source, {1: _page_with_marker(marker, f"body {marker}")})
    document_id = fx.ingestor.ingest_document(
        [blobs["page-10"], blobs["page-1"], blobs["page-2"]],
        kind="submission")
    markdown = fx.documents("document_id = :d", d=document_id)[0]["markdown"]
    assert markdown.index("body page-2") < markdown.index("body page-10"), (
        "TC-INGEST-C07: the marker tier sorted lexicographically."
    )
    provenance = json.loads(fx.documents(
        "document_id = :d", d=document_id)[0]["source_blobs"])
    assert provenance["order_source"] == "marker", (
        f"TC-INGEST-C07: order_source recorded as "
        f"{provenance['order_source']!r}, not 'marker'."
    )
    fx.close()


def test_tc_ingest_c07_the_filename_tier_is_the_last_complete_tier(tmp_data_dir):
    """`TC-INGEST-C07` step 2, row 4 — filenames decide when nothing higher is
    complete (natural sort), recorded as `order_source: filename`; and the
    DIFFERENTIAL: permuting the caller's filename map permutes the page order —
    the order is a function of the declared inputs only."""
    fx = Contract(tmp_data_dir, "c07-filenames")
    fx.add_roster("gus")
    one = fx.put(b"c07 file one")
    two = fx.put(b"c07 file two")
    fx.script(one, {1: student_answer("gus", answer_text("Q1", "one"))})
    fx.script(two, {1: student_answer(None, answer_text("Q2", "two"))})

    def ingest(names: dict) -> str:
        return fx.ingestor.ingest_document([one, two], kind="submission",
                                           filenames=names)

    document_a = ingest({one: "1-page.pdf", two: "2-page.pdf"})
    document_b = ingest({one: "9-page.pdf", two: "0-page.pdf"})
    markdown_a = fx.documents("document_id = :d", d=document_a)[0]["markdown"]
    markdown_b = fx.documents("document_id = :d", d=document_b)[0]["markdown"]
    assert markdown_a.index("one") < markdown_a.index("two"), (
        "TC-INGEST-C07: the filename tier mis-ordered the first ingest."
    )
    assert markdown_b.index("two") < markdown_b.index("one"), (
        "TC-INGEST-C07: permuting the filename map did not permute the page "
        "order — an insertion-order artifact decided the assembly."
    )
    for document_id in (document_a, document_b):
        provenance = json.loads(fx.documents(
            "document_id = :d", d=document_id)[0]["source_blobs"])
        assert provenance["order_source"] == "filename", (
            f"TC-INGEST-C07: order_source recorded as "
            f"{provenance['order_source']!r}, not 'filename'."
        )
    fx.close()


def test_tc_ingest_c07_an_incomplete_tier_falls_through_and_neither_half_fires(
        tmp_data_dir):
    """`TC-INGEST-C07` step 2, row 5 — a PARTIAL page-number tier (one page
    carries a number, the other does not) falls through to the filename tier
    instead of half-firing, and the recorded decision says so."""
    fx = Contract(tmp_data_dir, "c07-partial")
    fx.add_roster("gus")
    numbered = fx.put(b"c07 partial numbered")
    unnumbered = fx.put(b"c07 partial unnumbered")
    fx.script(numbered, {1: _page_with_number(1, 2, "numbered body")})
    fx.script(unnumbered, {1: "unnumbered body"})
    document_id = fx.ingestor.ingest_document(
        [unnumbered, numbered], kind="submission",
        filenames={numbered: "2-page.pdf", unnumbered: "1-page.pdf"})
    markdown = fx.documents("document_id = :d", d=document_id)[0]["markdown"]
    assert markdown.index("unnumbered body") < markdown.index("numbered body"), (
        "TC-INGEST-C07: the partial page-number tier half-fired and decided "
        "the order."
    )
    provenance = json.loads(fx.documents(
        "document_id = :d", d=document_id)[0]["source_blobs"])
    assert provenance["order_source"] == "filename", (
        f"TC-INGEST-C07: the fall-through recorded as "
        f"{provenance['order_source']!r}, not 'filename'."
    )
    fx.close()


def test_tc_ingest_c07_no_tier_no_order_refuses(tmp_data_dir):
    """`TC-INGEST-C07` step 2, refusal row — no operator order, no printed
    numbers, no markers, no filenames: the call refuses (`IngestOrderError`),
    and through the submission gateway the refusal quarantines the unit without
    touching the run. Nothing is ever assembled in directory order."""
    fx = Contract(tmp_data_dir, "c07-refuse")
    fx.add_roster("gus")
    one = fx.put(b"c07 refuse one")
    two = fx.put(b"c07 refuse two")
    fx.script(one, {1: student_answer("gus", answer_text("Q1", "one"))})
    fx.script(two, {1: "two"})
    with pytest.raises(IngestOrderError, match="cannot be determined"):
        fx.ingestor.ingest_document([one, two], kind="submission")
    fx.close()


def test_tc_ingest_c07_a_page_count_disagreement_is_a_gap_refusal(tmp_data_dir):
    """`TC-INGEST-C07` step 2, gap row — pages that disagree about the
    document's declared total refuse (`IngestGapError`): a torn or mixed stack
    is never silently concatenated."""
    fx = Contract(tmp_data_dir, "c07-gap")
    one = fx.put(b"c07 gap one")
    two = fx.put(b"c07 gap two")
    fx.script(one, {1: _page_with_number(1, 2, "one")})
    fx.script(two, {1: _page_with_number(2, 3, "two")})
    with pytest.raises(IngestGapError, match="disagree about"):
        fx.ingestor.ingest_document([one, two], kind="submission")
    fx.close()


# -- directory order is never read -------------------------------------------------------------------


def test_tc_ingest_c07_no_directory_read_exists_in_the_module():
    """`TC-INGEST-C07` step 3 (static half) — the module never enumerates a
    directory: no `os.listdir` / `Path.iterdir` / `scandir` / `glob` call in
    `aeh.ingest`'s body. The behavioural differential above is the twin
    assertion; this one holds even where no fixture can reach."""
    tree = ast.parse((_REPO_ROOT / "src" / "aeh" / "ingest.py").read_text(
        encoding="utf-8"))
    directory_calls: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in (
                "listdir", "iterdir", "scandir", "glob", "walk", "rglob"):
            directory_calls.append(f"line {node.lineno}: .{func.attr}()")
    assert not directory_calls, (
        f"TC-INGEST-C07: aeh.ingest enumerates a directory: {directory_calls}. "
        "Directory order is never read (CT-INGEST-07) — the caller declares "
        "every input and its name."
    )
