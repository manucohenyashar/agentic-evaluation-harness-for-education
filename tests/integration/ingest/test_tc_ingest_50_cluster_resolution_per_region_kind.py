"""`TC-INGEST-50` and `TC-INGEST-51` — cluster resolution per region kind, and the selection
biconditional the database enforces (`FR-INGEST-36`, `FR-INGEST-37`, `CT-INGEST-21`).

**Why these live here, written by the fix.** GAP-16 is a *defect* with no shipped case (the
gap-fix test plan's own coverage row says "New regression + TC row (defect exception)"), and
CLAUDE.md's test-authorship rule carves exactly that out: the regression is written with the fix
and confirmed red against the unfixed code. The TC ids and their decision table are the gap-fix
test plan's (§5.11, `TC-INGEST-50`'s table; `TC-INGEST-51`); TS-92's own implementation of the
remaining rows (7, 8 and the M-DET consumption arm) stays that story's.

**The defect.** One statement, `update_region_content`, replaced the token's text and set
`selection_state='resolved'` for EVERY region kind, and never wrote `selection`. So an operator
resolving an ambiguous tick left `selection_state='resolved'` beside a NULL `selection` — the
exact state M-DET reads as *unanswered* (`det._read_from_regions`), and the student loses the
mark for a scanner ambiguity the operator had just fixed (RISK-50, RISK-03 through a new door).

**Confirmed red against the unfixed code.** With `resolve_cluster`'s per-kind rule reverted to
the single statement, `test_tc_ingest_50_row3…` fails on `selection is None` and
`…rows_4_to_6…` fails on `selection_state == 'resolved'`. With the triggers reverted,
`test_tc_ingest_51…` fails on the write succeeding. (The adversarial construction
`TC-INGEST-C21` names — restore the single statement — is exactly that revert.)

**The decision table** (`Q3` declares `A`–`D`), rows implemented here:

| Row | Region kind | Resolution | Expected |
|---|---|---|---|
| 1 | `transcribed_text` | `"2x + 3"` | content replaced; `selection_state` unchanged |
| 3 | `selection_mark` | `"C"` | `selection='C'` and `selection_state='resolved'`, together |
| 4 | `selection_mark` | `"E"` (undeclared) | stays `ambiguous`, NULL selection, content replaced, listed |
| 5 | `selection_mark` | `""` | as row 4 |
| 6 | `selection_mark` | `"c"` (case) | as row 4 — option ids match exactly |

Isolation: rung 2 — a real store, the real gateway, the real package tier for the declared
options. The provider and rasterizer are the suite's own doubles (seam 2).
"""

from __future__ import annotations

from typing import Any

import pytest

from aeh.prov import SamplingParams
from aeh.ingest import INGEST_STATEMENTS, IngestError, Ingestor
from aeh.pkg import PackageCatalog
from aeh.store import Statement
from tests.integration.ingest.test_ingest_gateway import (
    OnePageRasterizer,
    THROUGH_SANITIZER,
    _fixture,
    _model,
    _region_provider,
)
from tests.support.store_api import statement

pytestmark = pytest.mark.integration

ISSUE = "#355"
COHORT = "c-36"
QUESTION = "Q3"
OPTIONS = ("A", "B", "C", "D")
TOKEN = "illegible-tick"

#: One page carrying both kinds: a text region and a selection mark for `Q3`, each holding the
#: same unresolved token, so ONE cluster resolution reaches both and the per-kind rule is what
#: separates them (the decision table's row 7 shape, in miniature).
MARKED_PAGE = (
    f"<!-- region: kind=transcribed_text question_id=Q1 -->\n"
    f"the working shows <unresolved>{TOKEN}</unresolved> here\n<!-- /region -->\n"
    f"<!-- region: kind=selection_mark question_id={QUESTION} -->\n"
    f"<unresolved>{TOKEN}</unresolved>\n<!-- /region -->"
)


def _seed_options(store: Any) -> tuple[PackageCatalog, str]:
    """A real package version declaring `Q3`'s four options — the set the resolution is
    checked against."""
    handle = store.package("pkg-ingest-50")
    with handle.transaction() as tx:
        tx.execute(
            statement("INSERT INTO package (package_id, created_at) VALUES "
                      "('pkg-ingest-50', '2026-01-01T00:00:00Z')", issue=ISSUE))
    catalog = PackageCatalog(handle, package_id="pkg-ingest-50")
    version = catalog.create_version(parent=None)
    with handle.transaction() as tx:
        tx.execute(
            statement(
                "INSERT INTO question (package_version_id, question_id, ordinal, "
                "prompt_text, question_type, max_points, confirmed_at) VALUES (:v, :q, 0, "
                "'pick one', 'mcq', 1.0, '2026-01-01T00:00:00Z')", issue=ISSUE),
            v=version, q=QUESTION)
        for ordinal, option_id in enumerate(OPTIONS):
            tx.execute(
                statement(
                    "INSERT INTO question_option (package_version_id, question_id, "
                    "option_id, ordinal, label) VALUES (:v, :q, :o, :n, :l)", issue=ISSUE),
                v=version, q=QUESTION, o=option_id, n=ordinal, l=f"option {option_id}")
    return catalog, version


def _world(tmp_data_dir):
    store, blobs, _rasterizer, _provider, _slot, _ = _fixture(tmp_data_dir)
    handle = store.cohort(COHORT)
    ingestor = Ingestor(
        handle, blobs, _region_provider([MARKED_PAGE]), _model(),
        SamplingParams(temperature=0.0), OnePageRasterizer(), sanitizer=THROUGH_SANITIZER,
    )
    document_id = ingestor.ingest_document(
        [blobs.put(b"one submission")], kind="submission",
        filenames={blobs.put(b"one submission"): "scan.md"},
    )
    catalog, version = _seed_options(store)
    return store, handle, ingestor, document_id, catalog, version


def _regions(handle: Any, document_id: str) -> dict[str, dict[str, Any]]:
    rows = handle.query(
        statement(
            "SELECT region_id, region_kind, element_kind, selection, selection_state, content "
            "FROM document_region WHERE document_id = :d ORDER BY position", issue=ISSUE),
        d=document_id)
    return {str(row["region_kind"]): dict(row) for row in rows}


def _cluster_id(ingestor: Any) -> str:
    (cluster,) = [c for c in ingestor.clusters(COHORT) if c.token == TOKEN]
    return cluster.cluster_id


# --- TC-INGEST-50 rows 1 and 3 ------------------------------------------------------------------


def test_tc_ingest_50_row3_a_declared_option_sets_selection_and_state_together(tmp_data_dir):
    """Row 3 — `C` is declared for `Q3`: `selection='C'` AND `selection_state='resolved'`.
    Row 1 rides along: the text region's content is replaced and its selection state is
    untouched, which is the per-kind split's whole point."""
    store, handle, ingestor, document_id, catalog, version = _world(tmp_data_dir)
    try:
        before = _regions(handle, document_id)
        assert before["selection_mark"]["selection_state"] != "resolved", (
            "fixture: the mark starts unresolved, or the assertions below prove nothing"
        )

        report = ingestor.resolve_cluster(
            _cluster_id(ingestor), "C", package_catalog=catalog, package_version=version,
        )

        after = _regions(handle, document_id)
        mark = after["selection_mark"]
        assert mark["selection"] == "C", (
            f"the resolved mark carries selection {mark['selection']!r} — a resolved "
            "selection mark with no selection is what M-DET reads as unanswered (RISK-50)"
        )
        assert mark["selection_state"] == "resolved", (
            f"the mark's state is {mark['selection_state']!r}; a matched option resolves it"
        )
        assert report.selection_unresolved == (), (
            f"a declared option was listed as unresolved: {report.selection_unresolved}"
        )
        assert set(report) == {document_id}

        # Row 1: the text region's content changed and nothing else did.
        text = after["transcribed_text"]
        assert "<unresolved>" not in str(text["content"]) and "C" in str(text["content"])
        assert text["selection_state"] == before["transcribed_text"]["selection_state"], (
            f"the text region's selection_state moved to {text['selection_state']!r} — "
            "reading a word is not selecting an option (FR-INGEST-36)"
        )
    finally:
        store.close()


# --- TC-INGEST-50 rows 4, 5 and 6 ---------------------------------------------------------------


@pytest.mark.parametrize(
    "resolution, why",
    [("E", "undeclared option"), ("", "empty resolution"), ("c", "case differs from 'C'")],
    ids=["row4-undeclared", "row5-empty", "row6-case"],
)
def test_tc_ingest_50_rows_4_to_6_an_unmatched_resolution_leaves_the_mark_ambiguous(
    tmp_data_dir, resolution, why
):
    """Rows 4-6 — the mark stays `ambiguous` with a NULL selection, its content is still
    replaced, and the region is listed under `selection_unresolved`."""
    store, handle, ingestor, document_id, catalog, version = _world(tmp_data_dir)
    try:
        report = ingestor.resolve_cluster(
            _cluster_id(ingestor), resolution,
            package_catalog=catalog, package_version=version,
        )

        mark = _regions(handle, document_id)["selection_mark"]
        assert mark["selection"] is None, (
            f"{why}: the mark carries selection {mark['selection']!r} — only a declared "
            f"option id may be stored ({OPTIONS})"
        )
        assert mark["selection_state"] == "ambiguous", (
            f"{why}: the mark is {mark['selection_state']!r}; an unmatched resolution leaves "
            "it AMBIGUOUS — `resolved` with a NULL selection is the state M-DET reads as "
            "unanswered (CT-INGEST-05, RISK-50), and any other state invents a reading"
        )
        assert "<unresolved>" not in str(mark["content"]), (
            f"{why}: the content was not replaced; the operator's reading is still recorded"
        )
        assert report.selection_unresolved == (mark["region_id"],), (
            f"{why}: the report lists {report.selection_unresolved} — an operator whose "
            "resolution matched no option learns it from the report, not from a lost mark"
        )
    finally:
        store.close()


# --- TC-INGEST-51 — the biconditional the database enforces --------------------------------------


def test_tc_ingest_51_a_resolved_selection_mark_with_no_selection_is_refused(tmp_data_dir):
    """`TC-INGEST-51` (`FR-INGEST-37`, `CT-INGEST-21`) — a direct UPDATE and a direct INSERT of
    a resolved `selection_mark` with a NULL selection both abort; the same writes for a
    `transcribed_text` region succeed, so the trigger is the biconditional and not a blanket
    refusal."""
    store, handle, ingestor, document_id, _catalog, _version = _world(tmp_data_dir)
    try:
        regions = _regions(handle, document_id)
        mark_id = regions["selection_mark"]["region_id"]

        with pytest.raises(Exception) as update_refused:
            with handle.transaction() as tx:
                tx.execute(
                    statement("UPDATE document_region SET selection_state = 'resolved', "
                              "selection = NULL WHERE region_id = :r", issue=ISSUE), r=mark_id)
        assert "selection" in str(update_refused.value).lower()

        with pytest.raises(Exception) as insert_refused:
            with handle.transaction() as tx:
                tx.execute(
                    statement(
                        "INSERT INTO document_region (region_id, document_id, page_no, "
                        "element_kind, region_kind, selection_state, selection) VALUES "
                        "('reg-born-wrong', :d, 1, :q, 'selection_mark', 'resolved', NULL)",
                        issue=ISSUE), d=document_id, q=QUESTION)
        # The trigger's own message, not merely "some integrity error": every column this
        # INSERT omits is nullable, so a future NOT NULL column would otherwise make this arm
        # pass for a reason that has nothing to do with the biconditional.
        assert "selection" in str(insert_refused.value).lower(), (
            f"the INSERT was refused by something other than the biconditional: "
            f"{insert_refused.value!r}"
        )

        # The stored row never reached the forbidden state, by either door.
        after = _regions(handle, document_id)["selection_mark"]
        assert not (after["selection_state"] == "resolved" and after["selection"] is None)
        assert handle.query(
            statement("SELECT region_id FROM document_region WHERE region_id = "
                      "'reg-born-wrong'", issue=ISSUE)) == []

        # The same shape on a text region is none of the trigger's business.
        with handle.transaction() as tx:
            tx.execute(
                statement("UPDATE document_region SET selection_state = 'resolved', "
                          "selection = NULL WHERE region_id = :r", issue=ISSUE),
                r=regions["transcribed_text"]["region_id"])

    finally:
        store.close()


def test_tc_ingest_c21_the_trigger_turns_the_restored_defect_into_an_ingest_error(
    tmp_data_dir, monkeypatch
):
    """`TC-INGEST-C21`'s adversarial construction, run: restore the single
    `update_region_content` shape — the statement that set `selection_state='resolved'` without
    a selection — and the DATABASE refuses the write, which the module surfaces as
    `IngestError`. This is the defence-in-depth arm: with FR-INGEST-36's writer reverted, the
    student is still not silently marked unanswered."""
    store, handle, ingestor, document_id, catalog, version = _world(tmp_data_dir)
    try:
        monkeypatch.setitem(
            INGEST_STATEMENTS, "resolve_selection_region",
            Statement(
                "UPDATE document_region SET content = REPLACE(content, "
                "'<unresolved>' || :token || '</unresolved>', :resolution), "
                "selection_state = 'resolved' WHERE region_id = :region_id "
                "AND :selection IS NOT NULL"),
        )
        with pytest.raises(IngestError) as refused:
            ingestor.resolve_cluster(
                _cluster_id(ingestor), "C",
                package_catalog=catalog, package_version=version,
            )
        assert "selection" in str(refused.value).lower(), (
            f"the boundary error does not name the biconditional: {refused.value!r}"
        )
        mark = _regions(handle, document_id)["selection_mark"]
        assert not (mark["selection_state"] == "resolved" and mark["selection"] is None), (
            "the reverted writer stored the forbidden state — the trigger did not hold"
        )
    finally:
        store.close()
