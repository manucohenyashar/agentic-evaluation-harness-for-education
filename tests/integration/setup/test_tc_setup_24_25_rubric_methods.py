"""`TC-SETUP-24` (FR-SETUP-18, RISK-112, Q-O4, P0) and `TC-SETUP-25` (FR-SETUP-19, P1) — the
rubric-method setup flows (TS-145, #623).

Written ahead of #624: every case here is red until `SetupService` grows the derivation
read-back and the evidence-sum builder, and carries `writtenahead` keyed to #624 in
`WRITTEN_AHEAD_BLOCKERS`. The surface those flows will have is not named by the design; the
assumed names live in `tests/support/setup_rubric_methods.py` only.

Rung 2: a real store, real `Ingestor`, real `PackageCatalog`; the setup model is the only
double. The plan's browser arm ("browser where the card renders", E6) is NOT implemented here:
the card's rendering belongs to M-UI, which #624 does not build. Disclosed on the #623 PR.
"""

from __future__ import annotations

import pytest

from tests.support import setup_rubric_methods as rm

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]


# --- TC-SETUP-24 (a): the derivation output passes the numeral scan ----------------------------


def test_tc_setup_24_a_a_model_derivation_carrying_numerals_never_reaches_the_card_or_the_store(
    tmp_data_dir,
):
    """RISK-112: the model writes "3 details = top band" into the derived descriptors. The scan
    runs on the DERIVATION OUTPUT, not only on teacher input, so that reply is never shown as
    the card and never staged. Two outcomes are correct — re-requested (the second, clean reply
    becomes the card) or refused with a `SetupError` — and both are held to the same oracle:
    nothing that fails FR-JUDGE-03's scan is shown or stored. The two-outcome oracle is sound
    only because (c) and TC-SETUP-C17's confirmed arm force the success path on a clean reply,
    so a module that refuses every derivation cannot pass the suite."""
    from aeh.setup import SetupError

    chain = rm.confirmed_chain(tmp_data_dir)
    # The fixture is what it claims: the leaking reply fails the scan, the clean one passes.
    assert rm.numeral_offenses(rm.NUMERAL_BANDS)
    assert not rm.numeral_offenses(rm.DERIVED_BANDS)

    replies = [rm.derivation_reply(rm.GENERAL, rm.NUMERAL_BANDS),
               rm.derivation_reply(rm.GENERAL, rm.DERIVED_BANDS)]
    calls_before = len(chain.provider.calls)  # the inventory proposal already made one
    try:
        shown = rm.derive(chain, rm.GENERAL, replies=replies)
    except SetupError:
        shown = None

    if shown is not None:
        offenses = rm.numeral_offenses(rm.field(shown, "bands"))
        assert not offenses, (
            "TC-SETUP-24(a): the derivation card shows a band set that fails FR-JUDGE-03's "
            f"numeral scan — the scan did not run on the derivation output: {offenses}")
        assert rm.comparable(rm.field(shown, "bands")) == rm.comparable(rm.DERIVED_BANDS), (
            "TC-SETUP-24(a): the card is neither the refused reply nor the clean re-request — "
            f"got {rm.band_tuples(rm.field(shown, 'bands'))}")
        assert len(chain.provider.calls) - calls_before >= 2, (
            "TC-SETUP-24(a): a clean card after one derivation call — the numeral reply was "
            "not the one rejected")

    # Both branches: the card a resuming console renders (the read-back record, where §3.6
    # stores the derivation) carries nothing that fails the scan.
    resumed = rm.stored_card(chain, rm.GENERAL)
    if resumed is not None:
        offenses = rm.numeral_offenses(rm.field(resumed, "bands"))
        assert not offenses, (
            f"TC-SETUP-24(a): the stored derivation card fails the numeral scan: {offenses}")

    stored = rm.stored_bands(chain).get(rm.GENERAL, [])
    offenses = rm.numeral_offenses(stored)
    assert not offenses, (
        f"TC-SETUP-24(a): the draft stores derived bands that fail the numeral scan: {offenses}")


# --- TC-SETUP-24 (b): confirmation withheld, publish refused ------------------------------------


def test_tc_setup_24_b_publish_with_the_derivation_unconfirmed_is_refused_naming_the_criterion(
    tmp_data_dir,
):
    """The read-back is BLOCKING: with every other gate met, an unconfirmed `general`
    derivation refuses publish, the refusal names the criterion, the version stays an unlocked
    draft, and the step report does not call the draft ready."""
    chain = rm.confirmed_chain(tmp_data_dir)
    rm.derive(chain, rm.GENERAL)
    assert chain.service.steps().ready_to_publish is False, (
        "TC-SETUP-24(b): the step report calls the draft ready to publish while a `general` "
        "derivation is unconfirmed")

    refusal = rm.publish_refusal(chain)
    rm.assert_derivation_gate(chain, refusal)
    assert rm.GENERAL in str(refusal), (
        f"TC-SETUP-24(b): the refusal does not name the pending criterion — got: {refusal}")
    assert not rm.locked(chain), "TC-SETUP-24(b): the refused publish locked the version"
    assert chain.catalog.draft_version() == chain.version, (
        "TC-SETUP-24(b): the refused publish consumed the draft")


# --- TC-SETUP-24 (c): edited, confirmed, published with the edited structure --------------------


def test_tc_setup_24_c_the_teachers_edited_bands_are_what_publishes(tmp_data_dir):
    """The teacher edits the derived bands (one label, two descriptors) and confirms: the
    published criterion carries the EDITED set — equal to the edit, different from the
    derivation — and is stored as a `general` criterion (#621's reading, CT-PKG-21)."""
    chain = rm.confirmed_chain(tmp_data_dir)
    rm.derive(chain, rm.GENERAL)
    assert rm.comparable(rm.EDITED_BANDS) != rm.comparable(rm.DERIVED_BANDS)
    assert not rm.numeral_offenses(rm.EDITED_BANDS)

    rm.confirm_general(chain, rm.GENERAL, bands=rm.EDITED_BANDS)
    assert chain.service.publish(rm.TEACHER) == chain.version
    assert rm.locked(chain)

    stored = rm.stored_bands(chain)[rm.GENERAL]
    assert rm.comparable(stored) == rm.comparable(rm.EDITED_BANDS), (
        "TC-SETUP-24(c): the published band set is not the teacher's edit — got "
        f"{rm.band_tuples(stored)}")
    assert rm.comparable(stored) != rm.comparable(rm.DERIVED_BANDS)
    assert [b["ordinal"] for b in stored] == list(range(len(rm.EDITED_BANDS)))
    row = rm.criteria_rows(chain)[rm.GENERAL]
    assert row.get("score_method") == "general", (
        f"TC-SETUP-24(c): the published criterion's score_method is {row.get('score_method')!r}")
    assert row["question_id"] == rm.QUESTION


# --- TC-SETUP-24 (d): the card is one of NFR-SYS-07's six optional confirmations (Q-O4) ---------


def test_tc_setup_24_d_the_derivation_card_counts_as_one_of_the_six_optional_confirmations(
    tmp_data_dir,
):
    """Q-O4: the derivation card spends one of NFR-SYS-07's six optional confirmations. With
    one card requested, fifteen borderline criteria can surface only FIVE decomposability
    confirmations — six in all. A module that does not count the card surfaces six and the
    total drifts to seven, which this case makes visible."""
    import aeh.setup as aeh_setup

    budget = aeh_setup.SETUP_MAX_CONFIRMATIONS  # six in production (NFR-SYS-07, CT-SETUP-13)
    chain = rm.confirmed_chain(tmp_data_dir)
    shown = rm.derive(chain, rm.GENERAL)
    assert rm.field(shown, "confirmed") is False

    ids = [f"CRIT-B{i}" for i in range(15)]
    chain.provider.replies = [rm.borderline_reply(cid) for cid in ids]
    verdicts = [chain.service.classify_decomposability(
        {"criterion_id": cid, "question_id": "Q1", "kind": "open",
         "construct": f"the response does the thing {cid} names"}) for cid in ids]
    decomposability = sum(1 for v in verdicts if v.needs_teacher_confirmation)
    assert decomposability == budget - 1, (
        f"TC-SETUP-24(d): {decomposability} decomposability confirmations after the derivation "
        f"card — expected {budget - 1}: the card is one of the {budget} optional confirmations "
        f"(Q-O4), so the teacher's total is {decomposability + 1}, not {budget}")


# --- TC-SETUP-25: the evidence-sum builder -------------------------------------------------------


def test_tc_setup_25_a_three_aspects_become_three_editable_two_band_criteria(tmp_data_dir):
    """Three named aspects with points: setup generates three 2-band aspect criteria whose
    descriptors derive from the aspect name, pass the numeral scan (the aspect's points must not
    leak into them), and are editable before confirmation. Published: the composite is
    `evidence_sum` with no band, each aspect points (0, p) with `component_of` the composite,
    and the edited descriptor is the stored one."""
    chain = rm.confirmed_chain(tmp_data_dir)
    draft = rm.build_sum(chain, rm.COMPOSITE, rm.ASPECTS)
    aspects = list(rm.field(draft, "aspects"))
    assert not list(rm.field(draft, "promotions")), (
        "TC-SETUP-25(a): two-level aspects were proposed for promotion")
    assert sorted(str(rm.field(a, "name")) for a in aspects) == sorted(
        a["name"] for a in rm.ASPECTS), "TC-SETUP-25(a): the aspects are not the three named"

    by_name = {}
    for aspect in aspects:
        name = str(rm.field(aspect, "name"))
        bands = list(rm.field(aspect, "bands"))
        assert len(bands) == 2, f"TC-SETUP-25(a): aspect {name!r} has {len(bands)} band(s)"
        offenses = rm.numeral_offenses(bands)
        assert not offenses, f"TC-SETUP-25(a): aspect {name!r}'s generated bands: {offenses}"
        assert any(name.lower() in str(rm.field(b, "descriptor")).lower() for b in bands), (
            f"TC-SETUP-25(a): no generated descriptor of {name!r} derives from its name — got "
            f"{rm.band_tuples(bands)}")
        by_name[name] = aspect

    edited_aspect = str(rm.field(by_name["clear structure"], "criterion_id"))
    edited_text = "Orders the argument from the setup through to the result."
    rm.edit_aspect(chain, rm.COMPOSITE, edited_aspect, ordinal=1, descriptor=edited_text)
    rm.confirm_sum(chain, rm.COMPOSITE)
    assert chain.service.publish(rm.TEACHER) == chain.version

    rows = rm.criteria_rows(chain)
    bands = rm.stored_bands(chain)
    assert rows[rm.COMPOSITE].get("score_method") == "evidence_sum"
    assert rows[rm.COMPOSITE].get("component_of") is None
    assert rm.COMPOSITE not in bands, "TC-SETUP-25(a): the composite carries a band set"
    for spec in rm.ASPECTS:
        cid = str(rm.field(by_name[spec["name"]], "criterion_id"))
        assert rows[cid].get("component_of") == rm.COMPOSITE, (
            f"TC-SETUP-25(a): aspect {cid} component_of {rows[cid].get('component_of')!r}")
        assert [b["points"] for b in bands[cid]] == [0.0, spec["points"]], (
            f"TC-SETUP-25(a): aspect {cid}'s band points {[b['points'] for b in bands[cid]]}")
    assert bands[edited_aspect][1]["descriptor"] == edited_text, (
        "TC-SETUP-25(a): the teacher's edit before confirmation did not reach the store — got "
        f"{bands[edited_aspect][1]['descriptor']!r}")


def test_tc_setup_25_b_an_aspect_needing_levels_is_proposed_for_promotion_never_a_three_band_aspect(
    tmp_data_dir,
):
    """An aspect the teacher describes with levels ("partially correct structure") fails the
    decomposability test in reverse: setup proposes promoting it to a standalone `bands`
    criterion and creates no aspect with more than two bands — in the draft it returns or in
    the store. (The accepted promotion is not driven to publish: three levels are an odd band
    count FR-PKG-06 refuses on any criterion, which would say nothing about this rule.)"""
    chain = rm.confirmed_chain(tmp_data_dir)
    draft = rm.build_sum(chain, rm.COMPOSITE, [rm.ASPECTS[0], rm.LEVELLED_ASPECT,
                                               rm.ASPECTS[2]])
    promotions = list(rm.field(draft, "promotions"))
    assert [str(rm.field(p, "aspect")) for p in promotions] == [rm.LEVELLED_ASPECT["name"]], (
        "TC-SETUP-25(b): the promotion proposals do not name exactly the levelled aspect — got "
        f"{promotions}")
    assert rm.field(promotions[0], "score_method") == "bands"

    for aspect in rm.field(draft, "aspects"):
        assert len(list(rm.field(aspect, "bands"))) == 2, (
            f"TC-SETUP-25(b): aspect {rm.field(aspect, 'name')!r} carries more than two bands")
        assert str(rm.field(aspect, "name")) != rm.LEVELLED_ASPECT["name"], (
            "TC-SETUP-25(b): the levelled aspect was created as an aspect anyway")

    rows = rm.criteria_rows(chain)
    bands = rm.stored_bands(chain)
    wide = [cid for cid, row in rows.items()
            if row.get("component_of") is not None and len(bands.get(cid, [])) > 2]
    assert not wide, f"TC-SETUP-25(b): the draft stores aspects with more than two bands: {wide}"
