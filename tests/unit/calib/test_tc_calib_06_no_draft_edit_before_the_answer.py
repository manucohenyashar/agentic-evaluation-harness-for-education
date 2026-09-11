"""`TC-CALIB-06` — no draft edit exists before the teacher answers.

Test plan §5.17, `TC-CALIB-06` (FR-CALIB-06, artifact assertion / rung 0).

The contract suite carries the case's **API half** (`TC-CALIB-C05`'s first case: every
question arrives with options and no `proposed_edit` field at all, two examples side by
side). What no green test carried before this file is the case's **state half** — the
artifact assertion over a real store: between the question being asked and the teacher
answering it, **nothing exists to approve**. The teacher's answer generates the edit; the
model's job never rises above proposing the question.

Asserted on **state**, not on the returned value, because the two halves fail differently:
a question carrying a populated `proposed_edit` field fails the API half, but a surface
that writes a draft edit row (or mints a version) while *asking* passes the API half —
there is no edit on the question, there is one in the store, awaiting approval. So the
assertions here are over the store's state, through the module's own test catalog
(`catalog_for_test`, the real Tier P store whose writes the facade records):

* after `elicit`, the catalog has recorded **no write at all** — no version minted, no
  band touched, no elicitation row appended;
* the published version is unchanged — same latest version, same descriptor on the band
  the ambiguity lives in;
* and, for contrast, the teacher's **answer** is what generates the edit: after
  `apply_answers`, a version exists that did not exist before, carrying the clarified
  descriptor. The two phases are the case's causal claim in both directions.
"""

from __future__ import annotations

from tests.support.impl import CALIB_MODULE, require


def _finding_on_the_published_criterion(calib, *, band_ordinal: int = 1):
    """A known ambiguity on the one criterion the test package carries (`CRIT-1`).

    Built on the rubric's real criterion id — not `findings_fixture`'s `CRIT-00x` ids —
    so the session the questions define is the one `apply_answers` resolves against the
    version being edited."""
    return calib.Finding(
        criterion_id="CRIT-1",
        category="rubric_ambiguity",
        submissions_affected=17,
        examples=(
            "student response A for criterion CRIT-1",
            "student response B for criterion CRIT-1",
        ),
        band_ordinal=band_ordinal,
    )


def test_tc_calib_06_elicitation_writes_nothing_anywhere():
    """`TC-CALIB-06`'s state half — asking leaves the store exactly as it found it.

    Three surfaces, because a draft edit could arrive through any of them: the catalog's
    write record (every mutating call the facade forwards is named there), the version
    chain (a minted draft version *is* a draft edit), and the band descriptor the question
    is about (a pre-authored clarification sitting on the copy is the edit under another
    name). The assertion is state, not API: a question that *carried* no edit is
    `TC-CALIB-C05`'s green assertion; this one fails when a question *causes* one.
    """
    calib = require(CALIB_MODULE, issue="#138")
    elicit = require(CALIB_MODULE, "elicit", issue="#138")

    catalog = calib.catalog_for_test()
    base = catalog.latest_version()
    descriptor_before = dict(
        (row["ordinal"], row["descriptor"]) for row in catalog.bands("CRIT-1")
    )
    assert base is not None, "the fixture package published no version to calibrate against"

    questions = elicit([_finding_on_the_published_criterion(calib)])

    assert questions, "the elicitation produced no question, so the state check is vacuous"
    assert catalog.writes == [], (
        f"asking the questions wrote to the store: {catalog.writes}. TC-CALIB-06: the "
        "teacher's answer generates the edit, so no draft edit exists before the answer — "
        "and a draft that exists before the answer is a pre-authored edit awaiting approval, "
        "the approval interface the clause forbids."
    )
    assert catalog.latest_version() == base, (
        "elicitation minted a package version — a draft edit exists in the store before the "
        "teacher answered anything"
    )
    descriptor_after = dict(
        (row["ordinal"], row["descriptor"]) for row in catalog.bands("CRIT-1")
    )
    assert descriptor_after == descriptor_before, (
        "the band descriptor changed while the questions were being asked — the edit exists "
        "before the answer that is supposed to generate it"
    )


def test_tc_calib_06_the_answer_is_what_brings_the_edit_into_existence():
    """The contrast that makes "before" meaningful: the answer generates the edit.

    Asserted in both directions over one store, because "no draft edit before the answer"
    is only meaningful if an edit appears *when* the answer is given — a module that never
    writes anything would satisfy the first assertion vacuously while calibration does
    nothing at all. After the teacher answers, a version exists that did not exist before,
    its descriptor is the clarification the answer generated, and the conversation is on
    the record — the same writes, observed as state rather than as an audit.
    """
    calib = require(CALIB_MODULE, issue="#138")
    elicit = require(CALIB_MODULE, "elicit", issue="#138")
    apply_answers = require(CALIB_MODULE, "apply_answers", issue="#138")

    catalog = calib.catalog_for_test()
    base = catalog.latest_version()
    elicit([_finding_on_the_published_criterion(calib)])
    assert catalog.writes == [], "the elicitation itself wrote; the fixture is broken"

    revised = apply_answers({"q1": "broaden"}, catalog=catalog)

    assert revised is not None and revised != base, (
        "the teacher's answer produced no edit — the edit exists only once the answer "
        "generates it, and here nothing came into existence"
    )
    assert catalog.latest_version() == revised, (
        "the version the edit landed on is not the store's latest version"
    )
    clarified = next(
        row["descriptor"] for row in catalog.bands("CRIT-1") if row["ordinal"] == 1
    )
    assert "broadened" in clarified, (
        f"the clarified descriptor reads {clarified!r}; the edit the answer generated does "
        "not carry the broadening the teacher chose"
    )
    # The edit path's own record: one new version, the descriptor edit on it, and the
    # conversation appended — in that order, on the new version's copy, never on the base.
    assert catalog.writes[:3] == ["create_version", "update_band_field",
                                  "append_elicitation"], (
        f"the edit path wrote {catalog.writes}; the answer generates the edit as a new "
        "version (FR-PKG-04's revision flow), edits the copy, and records the conversation"
    )