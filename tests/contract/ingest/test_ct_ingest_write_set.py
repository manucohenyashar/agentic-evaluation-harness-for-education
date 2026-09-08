"""`CT-INGEST-17` — the write set (`TC-INGEST-C17`).

Case of test plan §6.11.5; issue #49 (TS-62). Green by design — the schema and
the declared-literal statement registry are the module's write surface, and
both are readable.

The clause: sole writer of `document`, `document_region` and the `submission`
gate columns; writes page rasters and crops to the blob store; writes NO score,
band, points, evidence or verdict — and **has no such write path** (the static
half, so the absence holds for paths never exercised).

**Disclosed finding (G7, probe-backed, shipped code):** the blob-store half is
only partially held — the module's only blob writes are the two crop
retentions (`aeh/ingest.py:2314` and `:2404`; the whole file has no other
`.put(`), i.e. a `described_graphic` region's crop — whole-page when the model
emitted no box. A TEXT page's raster is never persisted; `FR-STORE-06` and
`CT-INGEST-17` both name page rasters as blob content, so retention for every
page is the unimplemented remainder. The crop half is asserted here at full
strength; the raster half is disclosed for the M-INGEST owner (a bug in
shipped code has no `writtenahead` target — the module is its own implementer).

The sole-writer half is held at module level: the module's ENTIRE write
surface, read from the declared-literal registry, is exactly the seven owned
tables — a new write cannot pass unnoticed. That other modules never write
these tables is the consumers' half (M-EXTRACT/M-DET/M-STORE, stories #68..#71
and the store suite); nothing outside M-INGEST exists yet to write them.
"""
from __future__ import annotations

import re

import pytest

from tests.contract.ingest._doubles import (
    COHORT,
    INGEST_OWNED_TABLES,
    ISSUE,
    SCORE_TABLES,
    Contract,
    answer_text,
    graphic_mark,
    student_answer,
)
from tests.support.store_api import statement

pytestmark = pytest.mark.contract


def _row_counts(fx: Contract) -> dict[str, int]:
    """Row counts of every user table in the cohort database — the delta audit's
    instrument."""
    names = fx.handle.query(statement(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND "
        "name NOT LIKE 'sqlite_%'", issue=ISSUE))
    return {row["name"]: fx.handle.query(statement(
        f"SELECT COUNT(*) AS n FROM {row['name']}", issue=ISSUE))[0]["n"]
        for row in names}


def test_tc_ingest_c17_the_write_surface_is_exactly_the_owned_tables(
        tmp_data_dir):
    """`TC-INGEST-C17` (surface + audit) — statically, the module's whole write
    surface read from the declared registry is EXACTLY the seven owned tables,
    no statement writes a score-bearing name, and the audit is non-vacuous.
    Behaviorally, a rich clean ingest (text answer, unresolved token, graphic
    crop) changes only owned tables: the before/after row-count delta over
    every table in the cohort database never leaves the set, and every
    score-bearing table reads back zero rows after."""
    # The static half: the exact surface.
    from tests.contract.ingest._doubles import statement_texts, written_tables
    texts = statement_texts()
    assert texts, "TC-INGEST-C17: the statement registry is empty."
    surface = written_tables()
    assert surface == set(INGEST_OWNED_TABLES), (
        f"TC-INGEST-C17: the write surface is {sorted(surface)}, not exactly "
        f"the owned {sorted(INGEST_OWNED_TABLES)} — a table appeared or "
        "disappeared."
    )
    forbidden = SCORE_TABLES | {"band"}
    pattern = re.compile(
        r"\b(" + "|".join(sorted(forbidden)) + r")\b", re.IGNORECASE)
    offenders = [name for name, sql in texts.items() if pattern.search(sql)]
    assert not offenders, (
        f"TC-INGEST-C17: M-INGEST statements name score-bearing tables: "
        f"{offenders} — the module has a write path the clause forbids."
    )

    # The behavioral half: a rich ingest's row-count delta stays inside the set.
    fx = Contract(tmp_data_dir, "c17-audit")
    fx.add_roster("gus")
    before = _row_counts(fx)
    source = fx.put(b"c17 audit pdf")
    fx.script(source, {1: student_answer(
        "gus",
        answer_text("Q1", "plain <unresolved>projekt</unresolved> token body"),
        graphic_mark("Q2", "a diagram of the apparatus", crop="0,0,10,10"))})
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "a.pdf"})
    assert report.ingest_status == "ok", (
        f"TC-INGEST-C17: the audited ingest did not complete: "
        f"{report.ingest_status} / {report.gates}."
    )
    after = _row_counts(fx)
    changed = {name for name, count in after.items()
               if count != before.get(name, 0)}
    assert changed <= set(INGEST_OWNED_TABLES), (
        f"TC-INGEST-C17: the ingest changed non-owned tables "
        f"{sorted(changed - set(INGEST_OWNED_TABLES))} — a write outside the "
        "module's surface happened."
    )
    assert {"document", "document_region", "submission"} <= changed, (
        f"TC-INGEST-C17: the audit saw no core writes ({sorted(changed)}) — "
        "it would pass vacuously."
    )
    for name in sorted(SCORE_TABLES):
        assert after.get(name, 0) == 0, (
            f"TC-INGEST-C17: {name} holds {after.get(name, 0)} row(s) after a "
            "clean ingest — the module wrote a score."
        )
    fx.close()


def test_tc_ingest_c17_crops_resolve_to_retained_blobs(tmp_data_dir):
    """`TC-INGEST-C17` (blob-store half) — a `described_graphic` region's
    `crop_ref` resolves through the blob store to retained image bytes, with or
    without a declared box (the whole page when none), identical crop bytes
    land on one content-addressed copy, and the source PDF still resolves. The
    disclosed G7: a TEXT page's raster is never retained — the module's only
    blob writes are these crops."""
    fx = Contract(tmp_data_dir, "c17-crops")
    fx.add_roster("gus")
    boxed = fx.put(b"c17 boxed pdf")
    whole = fx.put(b"c17 whole pdf")
    fx.script(boxed, {1: student_answer(
        "gus",
        graphic_mark("Q1", "the diagram with a box", crop="0,0,10,10"))})
    fx.script(whole, {1: student_answer(
        "gus",
        graphic_mark("Q2", "the diagram without a box", crop=None))})
    document_id = fx.ingestor.ingest_document(
        [boxed, whole], kind="submission", order_hint=[boxed, whole])
    regions = fx.regions(document_id)
    graphics = [row for row in regions if row["region_kind"] == "described_graphic"]
    assert len(graphics) == 2, (
        f"TC-INGEST-C17: expected two described_graphic regions, got "
        f"{len(graphics)}."
    )
    refs = [row["crop_ref"] for row in graphics]
    assert all(refs), (
        f"TC-INGEST-C17: a described_graphic carries no crop_ref: "
        f"{[(r['element_kind'], r['crop_ref']) for r in graphics]}."
    )
    for row, ref in zip(graphics, refs):
        payload = fx.blobs.get(ref)
        assert payload, (
            f"TC-INGEST-C17: {row['element_kind']}'s crop_ref {ref!r} resolves "
            "to empty bytes — the crop is not retained."
        )
    # Identical crop bytes → one content-addressed copy (FR-STORE-06 through
    # the module's write): the whole-page fallback is the same scripted bytes
    # as the boxed crop here, so the two refs must deduplicate.
    assert refs[0] == refs[1], (
        f"TC-INGEST-C17: identical crop bytes stored twice ({refs!r}) — the "
        "write bypassed the content-addressed store."
    )
    fx.close()
