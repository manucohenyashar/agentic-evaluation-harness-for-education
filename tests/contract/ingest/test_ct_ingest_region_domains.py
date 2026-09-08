"""`CT-INGEST-04` / `CT-INGEST-05` / `CT-INGEST-06` — the region's domains, the
selection biconditional, and the evaluative bar (`TC-INGEST-C04..C06`).

Cases of test plan §6.11.5; issue #49 (TS-62). Green by design — #38/#39 landed
the region protocol, #41 the gate around it.

Audit disclosure for **C04** (G2 in `_doubles`' docstring) — CLOSED by #221:
the parser used to read `conf=` permissively, so a region tagged without
`conf=` — and every outside-marker fragment, e.g. the `Student:` head every
submission transcript carries — stored `ocr_conf = NULL` and nothing noticed.
The shipped parser now refuses a non-numeric tag and derives a reading
confidence for every region that arrives without one (the page's minimum
tagged confidence; a page that tagged nothing records the floor itself), so
the sweep below asserts the clause at full strength: `ocr_conf` non-null on
EVERY stored row, the untagged `text` head included, and the tagged region's
own value still exactly the tagged float.

The consumer halves — `M-DET` reading `region_kind`/`content_state` domains and
`M-JUDGE` reading the crop as description material — are deferred with
disclosure (M-DET #86..#89, M-JUDGE #78..#84); the producer side is asserted at
full strength below.
"""

from __future__ import annotations

import pytest

from aeh.ingest import (
    EVALUATIVE_RETRIES_ENV,
    EVALUATIVE_TERMS,
    IngestError,
    REGION_KINDS,
)
from tests.contract.ingest._doubles import (
    ISSUE,
    Contract,
    SequencedProvider,
    answer_text,
    graphic_mark,
    selection_mark,
    student_answer,
)
from tests.support.store_api import statement

pytestmark = pytest.mark.contract


# -- TC-INGEST-C04: the stored domains, the crop retention, blank vs absent --------------------------


def test_tc_ingest_c04_every_stored_region_carries_a_domain_value(tmp_data_dir):
    """`TC-INGEST-C04` — one submission whose transcript exercises every region
    kind and every content state: every stored row's `region_kind` is in the
    module's declared domain, its `content_state` in present/blank/absent, its
    `ocr_conf` the tagged float, and the two DISTINCT states survive as two
    distinct rows — blank (a legitimate zero) is never collapsed into absent
    (a scanning failure). Both states arrive as model TAGS here (every declared
    question is answered, so the V2 declared-set read mints nothing — since
    #219 that read is live and is the second producer of `absent` rows)."""
    fx = Contract(tmp_data_dir, "c04-domains")
    fx.add_roster("bea")
    catalog, version = fx.catalog(
        ["open", "open", "open", "mcq", "open"],
        options={"Q4": ["A", "B", "C", "D"]})
    # Q1 present text, Q2 blank, Q3 described graphic (with crop), Q4
    # selection, Q5 tagged absent.
    source = fx.put(b"c04 pdf")
    fx.script(source, {1: student_answer(
        "bea",
        answer_text("Q1", "the population pyramid"),
        answer_text("Q2", "", state="blank"),
        graphic_mark("Q3", "a bar chart of rainfall by month"),
        selection_mark("Q4", state="resolved", option="B"),
        answer_text("Q5", "", state="absent"),
    )})
    report = fx.ingestor.ingest_submission(
        [source], cohort_id="c-ingest-ct", package_version=version,
        filenames={source: "a.pdf"}, package_catalog=catalog)
    assert report.ingest_status == "ok", (
        f"TC-INGEST-C04: the well-formed sweep did not ingest ok: "
        f"{report.ingest_status} / {report.gates}."
    )
    document_id = fx.documents()[0]["document_id"]
    regions = fx.regions(document_id)
    kinds = {row["region_kind"] for row in regions}
    states = {row["content_state"] for row in regions}
    assert kinds <= set(REGION_KINDS), (
        f"TC-INGEST-C04: a stored region_kind outside the declared domain: "
        f"{kinds - set(REGION_KINDS)}."
    )
    assert states <= {"present", "blank", "absent"}, (
        f"TC-INGEST-C04: a stored content_state outside the declared domain: "
        f"{states}."
    )
    assert "blank" in states and "absent" in states, (
        f"TC-INGEST-C04: the blank/absent distinction did not survive as two "
        f"rows (states found: {states}) — blank is a legitimate zero and absent "
        "is a scanning failure; they are never collapsed."
    )
    tagged = [row for row in regions if row["element_kind"] == "Q1"]
    assert tagged and tagged[0]["ocr_conf"] == pytest.approx(0.97), (
        f"TC-INGEST-C04: the tagged region's ocr_conf is "
        f"{tagged[0]['ocr_conf']!r}, not the tagged 0.97 — the per-region "
        "reading confidence did not survive the parse."
    )
    # The clause at full strength (#221): EVERY stored row — the untagged
    # `text` head included — carries a real confidence. The head's is the
    # page's minimum tagged reading (0.93, the selection mark), the
    # conservative direction for a fragment the prompt carries outside the
    # marker protocol.
    untagged = [row for row in regions if row["element_kind"] == "text"]
    assert untagged and untagged[0]["ocr_conf"] == pytest.approx(0.93), (
        f"TC-INGEST-C04: the untagged head's ocr_conf is "
        f"{untagged[0]['ocr_conf']!r}, not the page's minimum tagged reading "
        "0.93 — the derived confidence for an outside-marker fragment moved."
    )
    nulls = [row["element_kind"] for row in regions if row["ocr_conf"] is None]
    assert not nulls, (
        f"TC-INGEST-C04: regions stored a NULL ocr_conf: {nulls} — a NULL is "
        "a CT-INGEST-04 contract violation (the G2 hole is closed; a regression "
        "here reopens it)."
    )
    blank_rows = [row for row in regions if row["content_state"] == "blank"]
    absent_rows = [row for row in regions if row["content_state"] == "absent"]
    assert [row["element_kind"] for row in blank_rows] == ["Q2"] \
        and [row["element_kind"] for row in absent_rows] == ["Q5"], (
        "TC-INGEST-C04: the blank and absent rows are not the two distinct "
        "questions the transcript tagged."
    )
    assert all(row["content"] == "" for row in blank_rows + absent_rows), (
        "TC-INGEST-C04: a blank or absent row carries content."
    )
    fx.close()


def test_tc_ingest_c04_a_described_graphics_crop_is_retained_and_resolvable(
        tmp_data_dir):
    """`TC-INGEST-C04` (crop half) — a `described_graphic` region's crop_ref is
    a blob-store reference the store can resolve to bytes, carved from the
    SANITIZED source through the rasterizer seam (asserted on the rasterizer's
    recorded events: the crop reads the same bytes rasterization read)."""
    fx = Contract(tmp_data_dir, "c04-crop")
    fx.add_roster("bea")
    source = fx.put(b"c04 crop pdf")
    fx.script(source, {1: student_answer(
        "bea", graphic_mark("Q1", "a scatter of points with a trend"),
    )})
    document_id = fx.ingestor.ingest_document([source], kind="submission",
                                              filenames={source: "a.pdf"})
    regions = fx.regions(document_id)
    graphics = [row for row in regions if row["region_kind"] == "described_graphic"]
    assert len(graphics) == 1, (
        f"TC-INGEST-C04: the graphic region did not survive as exactly one row "
        f"({len(graphics)})."
    )
    crop_ref = graphics[0]["crop_ref"]
    assert crop_ref, (
        "TC-INGEST-C04: the described_graphic stored no crop_ref — the crop was "
        "not retained."
    )
    resolved = fx.blobs.get(crop_ref)
    assert resolved, (
        f"TC-INGEST-C04: crop_ref {crop_ref!r} does not resolve in the blob "
        "store — the retained crop is unresolvable."
    )
    crop_events = [event for event in fx.rasterizer.events
                   if event[0] == "crop"]
    assert crop_events == [("crop", b"c04 crop pdf", 1)], (
        f"TC-INGEST-C04: the crop was not carved from the sanitized source "
        f"through the rasterizer seam exactly once (events: "
        f"{fx.rasterizer.events})."
    )
    fx.close()


# -- TC-INGEST-C05: selection iff resolved ------------------------------------------------------------


def test_tc_ingest_c05_selection_rows_carry_an_option_iff_resolved(tmp_data_dir):
    """`TC-INGEST-C05` — the biconditional over the stored rows: a selection is
    populated ONLY when the mark resolved, and a resolved mark always names its
    option. Asserted over a transcript carrying all three declared mark states
    (resolved, ambiguous, multiple_marks) AND the two malformed shapes (#219):
    a mark tagged with no state and no option, and a mark claiming `resolved`
    while naming no option. The sweep reads the STORED rows, so a parser that
    mapped an unresolved mark onto an option — or stored a malformed mark as
    `resolved` with a NULL `selection`, the hole this same case disclosed
    before #219 closed it — turns this red.

    Residual, disclosed in the #219 PR rather than fixed there: the
    biconditional is closed at PARSE (this sweep) and at the V2 gate, but the
    operator's cluster resolution (`update_region_content`, reached from
    `resolve_cluster`) stamps `selection_state='resolved'` onto EVERY region
    carrying a resolved token without setting `selection` — so a selection_mark
    stored `ambiguous` with an `<unresolved>` token in its body can be flipped
    to `resolved` with a NULL `selection` by an operator action (which can also
    stamp `resolved` onto non-mark rows). The clause's letter binds the
    transcript-stored rows this sweep reads; the operator-path residual belongs
    to the FR-INGEST-20 flow."""
    fx = Contract(tmp_data_dir, "c05-biconditional")
    fx.add_roster("cal")
    source = fx.put(b"c05 pdf")
    fx.script(source, {1: student_answer(
        "cal",
        selection_mark("Q1", state="resolved", option="C"),
        selection_mark("Q2", state="ambiguous"),
        selection_mark("Q3", state="multiple_marks"),
        # The malformed shapes, raw (the `_doubles` helper always tags a
        # state): no state at all, and `resolved` without its option.
        "<!-- region: kind=selection_mark question_id=Q4 conf=0.90 -->\n"
        "the mark as seen\n<!-- /region -->",
        selection_mark("Q5", state="resolved", option=None),
    )})
    document_id = fx.ingestor.ingest_document([source], kind="submission",
                                              filenames={source: "a.pdf"})
    rows = {row["element_kind"]: row for row in fx.regions(document_id)
            if row["region_kind"] == "selection_mark"}
    assert set(rows) == {"Q1", "Q2", "Q3", "Q4", "Q5"}, (
        f"TC-INGEST-C05: the mark states did not survive as rows: {set(rows)}."
    )
    resolved = rows["Q1"]
    assert resolved["selection_state"] == "resolved" \
        and resolved["selection"] == "C", (
        f"TC-INGEST-C05: the resolved mark stored state="
        f"{resolved['selection_state']!r} option={resolved['selection']!r}."
    )
    for question in ("Q2", "Q3"):
        row = rows[question]
        assert row["selection"] is None, (
            f"TC-INGEST-C05: the {row['selection_state']} mark on {question} was "
            f"mapped onto option {row['selection']!r} — an unresolved mark is "
            "never mapped to an option."
        )
    # The malformed shapes (#219): a mark the transcript cannot resolve — no
    # state tagged, or `resolved` claimed without naming an option — stores as
    # `ambiguous` with no selection. It is NEVER `resolved` with a NULL
    # selection, the disclosed pre-#219 form.
    for question in ("Q4", "Q5"):
        row = rows[question]
        assert row["selection_state"] == "ambiguous" \
            and row["selection"] is None, (
            f"TC-INGEST-C05: the malformed mark on {question} stored "
            f"state={row['selection_state']!r} "
            f"option={row['selection']!r} — an unresolvable mark stores "
            "`ambiguous` with no selection, never `resolved` with a NULL one "
            "(FR-INGEST-17)."
        )
    # The biconditional, over the whole stored set.
    violating = [row for row in rows.values()
                 if (row["selection_state"] == "resolved")
                 != (row["selection"] is not None)]
    assert not violating, (
        f"TC-INGEST-C05: rows violating selection-iff-resolved: "
        f"{[(r['element_kind'], r['selection_state'], r['selection']) for r in violating]}."
    )
    fx.close()


# -- TC-INGEST-C06: no evaluative vocabulary in any stored description --------------------------------


def test_tc_ingest_c06_an_evaluative_description_is_rerequested_then_refused(
        tmp_data_dir, monkeypatch):
    """`TC-INGEST-C06` — a description carrying evaluative vocabulary is
    RE-REQUESTED once (the configured budget), and a description that is still
    evaluative after the budget REFUSES the ingest: nothing is stored, because
    the descriptions would hand the panel a pre-made judgement."""
    monkeypatch.setenv(EVALUATIVE_RETRIES_ENV, "1")
    dirty = student_answer("dee", graphic_mark(
        "Q1", "the correct answer is circled in red"))
    fx = Contract(tmp_data_dir, "c06-refuse", provider=SequencedProvider())
    source = fx.put(b"c06 pdf")
    fx.provider.sequences[(source, 1)] = [dirty]
    with pytest.raises(IngestError, match="evaluative vocabulary"):
        fx.ingestor.ingest_document([source], kind="submission",
                                    filenames={source: "a.pdf"})
    # One original call + one re-request within the budget, then the refusal.
    assert len(fx.provider.calls) == 2, (
        f"TC-INGEST-C06: expected the re-request loop (1 + 1 calls), got "
        f"{len(fx.provider.calls)}."
    )
    assert fx.documents() == [], (
        "TC-INGEST-C06: a refused description left a document row behind."
    )
    fx.close()


def test_tc_ingest_c06_stored_descriptions_are_clean_and_clean_retries_accept(
        tmp_data_dir, monkeypatch):
    """`TC-INGEST-C06` (accept half) — a clean re-request is accepted: the
    stored description carries none of the module's evaluative terms (the sweep
    reads the STORED rows over every description column), and the student's own
    answer content is not subject to the bar — the gate discriminates
    descriptions from content."""
    monkeypatch.setenv(EVALUATIVE_RETRIES_ENV, "1")
    first = student_answer("dee", graphic_mark(
        "Q1", "the properly drawn diagram should be here"))
    second = student_answer("dee", graphic_mark(
        "Q1", "a force diagram with three labelled arrows"))
    fx = Contract(tmp_data_dir, "c06-accept", provider=SequencedProvider())
    source = fx.put(b"c06b pdf")
    fx.provider.sequences[(source, 1)] = [first, second]
    document_id = fx.ingestor.ingest_document([source], kind="submission",
                                              filenames={source: "a.pdf"})
    assert len(fx.provider.calls) == 2, (
        f"TC-INGEST-C06: the re-request did not happen (calls: "
        f"{len(fx.provider.calls)}) — the rejected answer was accepted as-is."
    )
    regions = fx.regions(document_id)
    descriptions = [row["description"] for row in regions
                    if row["description"]] \
        + [row["description_secondary"] for row in regions
           if row["description_secondary"]]
    assert descriptions, "TC-INGEST-C06: no description was stored to sweep."
    for description in descriptions:
        lowered = description.lower()
        offenders = [term for term in EVALUATIVE_TERMS if term in lowered]
        assert not offenders, (
            f"TC-INGEST-C06: the stored description {description!r} carries "
            f"evaluative vocabulary {offenders} — a pre-made judgement reached "
            "the panel."
        )
    # The bar discriminates: student answer CONTENT with the same words stores.
    content_rows = [row for row in regions if row["region_kind"]
                    == "transcribed_text"]
    assert content_rows, "TC-INGEST-C06: the answer content did not store."
    fx.close()


def test_tc_ingest_c06_student_content_is_not_subject_to_the_bar(tmp_data_dir):
    """`TC-INGEST-C06` (demarcation half) — the evaluative bar reads
    DESCRIPTIONS, never student content: an answer whose text says 'I think the
    correct answer is X' ingests fine — the student's words are data, the
    model's descriptions are the panel's inputs."""
    fx = Contract(tmp_data_dir, "c06-content")
    fx.add_roster("eli")
    source = fx.put(b"c06c pdf")
    fx.script(source, {1: student_answer(
        "eli", answer_text("Q1", "I believe the correct answer is B"),)})
    document_id = fx.ingestor.ingest_document([source], kind="submission",
                                              filenames={source: "a.pdf"})
    rows = [row for row in fx.regions(document_id)
            if row["region_kind"] == "transcribed_text"]
    assert any("correct" in (row["content"] or "") for row in rows), (
        "TC-INGEST-C06: the student's own evaluative wording did not store — "
        "the bar reached past the descriptions into content."
    )
    assert all(not row["description"] for row in rows), (
        "TC-INGEST-C06: a text region grew a description."
    )
    fx.close()
