"""`M-SETUP` Stage A's rubric read-back — **#51** (issue #54).

Cases `TC-SETUP-05/06/07` (test plan §5.6, all P0). Written ahead of the implementation
they carried `writtenahead` and sat outside `TEST_CMD`; #51 landed `read_back_rubric` —
the §3.6 Interface member every one of them drives — together with its two Configuration
constants, `SETUP_DEFAULT_BAND_COUNT` and `SETUP_MAGNITUDE_PHRASES`, so the marker is
gone (never the test) and the entry in `tests/support/impl.py` under "#51 readback" is
dropped. The scripted replies below matched the payload shape #51 parses
(`{"criteria": [...]}` with criterion entries carrying bands and a `justification`), so
no scripting alignment was needed.

One note kept from the written-ahead state:

- **TC-SETUP-06's rung.** The plan says unit / 0. It is implemented here at rung 2 beside
  its siblings: the rejection rule is only observable through the regeneration the read
  back performs, and doubling a write path whose shape is #51's to decide would put the
  mock where the behaviour is. The assertions are identical at either rung; a rung-0
  variant can move to a scripted catalog now that #51's write calls are known.
"""

from __future__ import annotations

import json

import pytest

from tests.support.impl import SETUP_MODULE, require, require_attr
from tests.support.setup_harness import (
    INVENTORY_REPLY,
    ingest_document,
    stage_chain,
)

ISSUE = "#51"


def _chain_ready(tmp_data_dir):
    """The chain through S2: propose, confirm — the state `read_back_rubric` follows."""
    chain = stage_chain(tmp_data_dir)
    assessment = ingest_document(chain.store)
    rubric = ingest_document(chain.store, kind="rubric", name="rubric.pdf")
    proposal = chain.service.propose_inventory(assessment)
    chain.service.confirm_inventory(proposal.proposal_id)
    return chain, rubric, assessment, chain.catalog.draft_version()


def _readback_reply(criteria: list[dict]) -> str:
    """One scripted read-back reply in the payload shape this file's oracles imply."""
    return json.dumps({"criteria": criteria})


#: The rubric the plan's precondition names: a criterion admitting partial credit, and one
#: that does not. `CRIT-MET` carries no bands at all — the common real case §3.6's open
#: question describes, whose default is the derived two-band met/not-met set.
PARTIAL_RUBRIC_REPLY = _readback_reply([
    {
        "criterion_id": "CRIT-MET", "question_id": "Q1", "kind": "open",
        "scoring_model": "holistic", "max_points": 4.0,
        "construct": "the response defines impulse as force acting over contact time",
    },
    {
        "criterion_id": "CRIT-STEPS", "question_id": "Q3", "kind": "open",
        "scoring_model": "atomic", "max_points": 6.0,
        "construct": "the response carries the derivation through to a stated result",
        "band_count": 4,
        "bands": [
            {"band": "full", "ordinal": 1, "points": 6.0,
             "descriptor": "the response derives the relation, states each step, and "
                           "arrives at the stated result"},
            {"band": "partial", "ordinal": 2, "points": 4.0,
             "descriptor": "the response sets up the derivation correctly and completes "
                           "at least one intermediate step"},
            {"band": "partial", "ordinal": 3, "points": 2.0,
             "descriptor": "the response identifies the governing relation but stops "
                           "before an intermediate step"},
            {"band": "none", "ordinal": 4, "points": 0.0,
             "descriptor": "the response states no relation and shows no derivation"},
        ],
        "justification": "partial credit: the derivation earns points for each correct "
                         "step even when the final result is wrong",
    },
])

CLEAN_DESCRIPTOR_REPLY = _readback_reply([
    {
        "criterion_id": "CRIT-MET", "question_id": "Q1", "kind": "open",
        "scoring_model": "holistic", "max_points": 4.0,
        "construct": "the response defines impulse as force acting over contact time",
        "bands": [
            {"band": "met", "ordinal": 1, "points": 4.0,
             "descriptor": "the response names the net force and the contact time and "
                           "multiplies them, stating the unit of the result"},
            {"band": "not met", "ordinal": 2, "points": 0.0,
             "descriptor": "the response omits either the force or the contact time, or "
                           "asserts a definition without connecting the two"},
        ],
    },
])


# --- TC-SETUP-05 ---------------------------------------------------------------------------


@pytest.mark.integration
def test_tc_setup_05_band_sets_are_even_two_to_six_default_two_bands_justification_recorded(
    tmp_data_dir,
):
    """`TC-SETUP-05` (FR-SETUP-04, P0) — the read back produces criterion rows whose band
    sets are even and within 2..6; a criterion whose construct carries no partial credit
    gets the configured default (two bands, `met` / `not met` — no bands to derive from in
    the rubric, the open question §3.6 records); and the partial-credit criterion's
    justification is recorded, so the wider band set is auditable rather than arbitrary."""
    setup = require(SETUP_MODULE, "SetupService", issue=ISSUE)
    require_attr(setup, "read_back_rubric", issue=ISSUE)
    default_bands = require(SETUP_MODULE, "SETUP_DEFAULT_BAND_COUNT", issue=ISSUE)
    assert default_bands == 2, (
        "TC-SETUP-05: SETUP_DEFAULT_BAND_COUNT is the Configuration block's declared "
        "default (two bands, met / not met); a different value changes every criterion "
        "the default path mints"
    )

    chain, rubric, assessment, version = _chain_ready(tmp_data_dir)
    # The propose/confirm rounds above consumed the provider's default; the read back
    # gets exactly this reply — without it the call would see the inventory payload and
    # the criteria below could never come into existence.
    chain.provider.replies = [PARTIAL_RUBRIC_REPLY]
    readback = chain.service.read_back_rubric(rubric, assessment)

    criteria = {row["criterion_id"]: row for row in chain.catalog.criteria(version)}
    # #53 stages CRIT-Q4/Q5/Q6 from the confirmed inventory's mcq/mixed questions, so the
    # stored set is the read-back's two criteria plus the staged deterministic ones.
    assert set(criteria) == {"CRIT-MET", "CRIT-STEPS",
                             "CRIT-Q4", "CRIT-Q5", "CRIT-Q6"}
    for criterion_id, row in criteria.items():
        count = row["band_count"]
        assert count % 2 == 0 and 2 <= count <= 6, (
            f"TC-SETUP-05: {criterion_id} carries band_count {count!r} — FR-SETUP-04 "
            "requires an even count in 2..6"
        )
        assert len(chain.catalog.bands(criterion_id)) == count

    # The default, met and not met: CRIT-MET declared no bands, so the module derived the
    # two-band set the design's open question describes.
    assert criteria["CRIT-MET"]["band_count"] == default_bands
    assert {row["band"] for row in chain.catalog.bands("CRIT-MET")} == {"met", "not met"}

    # The partial-credit justification is recorded with the criterion it belongs to.
    entry = _readback_entry(readback, "CRIT-STEPS")
    justification = getattr(entry, "justification", None)
    assert justification, (
        "TC-SETUP-05: the partial-credit criterion's justification is not recorded — "
        "FR-SETUP-04 makes the wider band set auditable by recording why it exists "
        "(the name read here, `justification`, is FR-SETUP-04's own word; if #51 names "
        "the field differently, this is the line to align)"
    )
    assert "partial" in str(justification).lower()
    # The stored half (FR-SETUP-04): the justification lives on the criterion row the
    # package carries, not only on the read-back's return object — #51's
    # `band_justification` column is where the wider band set stays auditable.
    stored_justification = criteria["CRIT-STEPS"]["band_justification"]
    assert "partial" in str(stored_justification).lower(), (
        "TC-SETUP-05: the stored criterion row does not carry the band-set "
        "justification — FR-SETUP-04 records it in the package, where the audit "
        "actually happens"
    )


def _readback_entry(readback, criterion_id: str):
    """One criterion's entry from a `RubricReadback`, without assuming its container type.

    §3.6 pins the return-type *name*, not its shape; this reads the container under the
    names a proposal-shaped result is likely to carry and fails naming what it searched,
    so an alignment at #51 is one line, not a mystery.
    """
    searched = [name for name in ("criteria", "entries", "drafts", "readback")
                if hasattr(readback, name)]
    for container in searched:
        for entry in getattr(readback, container):
            if getattr(entry, "criterion_id", None) == criterion_id:
                return entry
    raise AssertionError(
        f"TC-SETUP-05: no entry for {criterion_id!r} in the read back — searched "
        f"{searched or 'a RubricReadback with no enumerable container'}"
    )


# --- TC-SETUP-06 ---------------------------------------------------------------------------


@pytest.mark.integration
def test_tc_setup_06_magnitude_descriptors_rejected_and_regenerated_behavioural_accepted(
    tmp_data_dir,
):
    """`TC-SETUP-06` (FR-SETUP-05, P0) — generated descriptors containing each configured
    magnitude phrase, and a bare numeral, are rejected and regenerated; the clean
    behavioural descriptor is accepted and reaches the stored bands; and nothing the
    module stored after regeneration carries any configured phrase. The rejection is
    observed through the model boundary: the first read-back round is refused, a second
    round is requested, and the stored rows are the second round's."""
    setup = require(SETUP_MODULE, "SetupService", issue=ISSUE)
    require_attr(setup, "read_back_rubric", issue=ISSUE)
    phrases = require(SETUP_MODULE, "SETUP_MAGNITUDE_PHRASES", issue=ISSUE)
    assert phrases, (
        "TC-SETUP-06: SETUP_MAGNITUDE_PHRASES is empty — the rejection rule would scan "
        "nothing, and the case would assert nothing"
    )

    chain = stage_chain(tmp_data_dir)
    assessment = ingest_document(chain.store)
    rubric = ingest_document(chain.store, kind="rubric", name="rubric.pdf")
    # One offending descriptor per configured phrase, plus the bare numeral the FR names.
    offenders = [f"the response is {phrase}" for phrase in phrases]
    offenders.append("the response scores 5")
    clean = ("the response names the net force and the contact time and multiplies them, "
             "stating the unit of the result")
    chain.provider.replies = [
        INVENTORY_REPLY,
        _readback_reply([_offending_criterion(offenders)]),
        _readback_reply([_clean_criterion(clean)]),
    ]
    proposal = chain.service.propose_inventory(assessment)
    chain.service.confirm_inventory(proposal.proposal_id)

    chain.service.read_back_rubric(rubric, assessment)

    # Rejected and regenerated: the read back made another model round rather than
    # storing the offending descriptors.
    assert len(chain.provider.calls) >= 3, (
        "TC-SETUP-06: no regeneration round was requested after the offending "
        "descriptors — the magnitude rejection either did not fire or stored them"
    )
    _assert_no_stored_magnitude(chain, phrases)
    # The behavioural descriptor was accepted: it is what reached the stored bands.
    stored = _stored_descriptor_text(chain)
    assert clean in stored, (
        "TC-SETUP-06: the clean behavioural descriptor never reached the stored bands — "
        "the regeneration either failed or stored a substitute the test cannot see"
    )


def _offending_criterion(descriptors: list[str]) -> dict:
    """The read-back entry whose band descriptors carry every offending phrase."""
    return {
        "criterion_id": "CRIT-FLAW", "question_id": "Q2", "kind": "open",
        "scoring_model": "holistic", "max_points": 5.0,
        "construct": "the response derives the range equation",
        "bands": [
            {"band": f"b{index}", "ordinal": index + 1, "points": 5.0 / (index + 1),
             "descriptor": descriptor}
            for index, descriptor in enumerate(descriptors)
        ],
    }


def _clean_criterion(descriptor: str) -> dict:
    return {
        "criterion_id": "CRIT-FLAW", "question_id": "Q2", "kind": "open",
        "scoring_model": "holistic", "max_points": 5.0,
        "construct": "the response derives the range equation",
        "bands": [
            {"band": "met", "ordinal": 1, "points": 5.0, "descriptor": descriptor},
            {"band": "not met", "ordinal": 2, "points": 0.0,
             "descriptor": "the response omits the governing relation or asserts it "
                           "without deriving it"},
        ],
    }


def _stored_descriptor_text(chain) -> str:
    version = chain.catalog.draft_version()
    # Descriptors only: the FR-SETUP-05 bar governs descriptor text, and rows carry
    # non-descriptor fields (criterion ids like CRIT-Q5 — #53's staged criteria) whose
    # digits are not a points scale leaking into a judge prompt.
    return " ".join(
        str(band_row["descriptor"])
        for row in chain.catalog.criteria(version)
        for band_row in chain.catalog.bands(row["criterion_id"])
    ).lower()


def _assert_no_stored_magnitude(chain, phrases) -> None:
    stored = _stored_descriptor_text(chain)
    hits = [phrase for phrase in phrases if str(phrase).lower() in stored]
    assert not hits, (
        f"TC-SETUP-06: the stored band descriptors carry magnitude phrasing {hits} — "
        "FR-SETUP-05 requires rejection and regeneration, because M-JUDGE never filters "
        "a descriptor"
    )
    assert "5" not in stored.replace("5.0", ""), (
        "TC-SETUP-06: the bare-numeral descriptor survived into the stored bands"
    )


# --- TC-SETUP-07 ---------------------------------------------------------------------------


@pytest.mark.integration
def test_tc_setup_07_no_band_descriptor_in_the_published_package_carries_magnitude(
    tmp_data_dir,
):
    """`TC-SETUP-07` (FR-SETUP-05, P0) — the stored-artifact half of `TC-SETUP-06`: every
    band descriptor in a **published** package is scanned against
    `SETUP_MAGNITUDE_PHRASES` and matches zero of them. The scan runs over the published
    version's stored rows, read through a catalog opened after publication, so what is
    scanned is the artifact `M-JUDGE` will consume, not an in-memory object."""
    setup = require(SETUP_MODULE, "SetupService", issue=ISSUE)
    require_attr(setup, "read_back_rubric", issue=ISSUE)
    phrases = require(SETUP_MODULE, "SETUP_MAGNITUDE_PHRASES", issue=ISSUE)
    assert phrases, "TC-SETUP-07: SETUP_MAGNITUDE_PHRASES is empty — the scan sees nothing"

    chain, rubric, assessment, _ = _chain_ready(tmp_data_dir)
    # The propose/confirm rounds above consumed the provider's default; this case is
    # about the stored artifact, not about regeneration, so the read back gets exactly
    # one clean round — no malformed first round it would have to re-request past.
    chain.provider.replies = [CLEAN_DESCRIPTOR_REPLY]
    chain.service.read_back_rubric(rubric, assessment)

    # #53: the staged deterministic criteria need their keys before gate 2 opens.
    chain.service.set_answer_keys({"CRIT-Q4": ["A"], "CRIT-Q5": ["A"], "CRIT-Q6": ["A"]})
    version = chain.service.publish("teacher-1")
    assert chain.catalog.is_locked(version)

    # A fresh catalog over the published version: the stored rows, not a live cache.
    from aeh.pkg import PackageCatalog

    published_catalog = PackageCatalog(chain.store.package(chain.package_id),
                                       package_id=chain.package_id)
    offenders = []
    for row in published_catalog.criteria(version):
        for band_row in published_catalog.bands(row["criterion_id"]):
            text = " ".join(str(value) for value in band_row.values()).lower()
            for phrase in phrases:
                if str(phrase).lower() in text:
                    offenders.append(
                        f"{row['criterion_id']} band {band_row.get('band')!r} carries "
                        f"{phrase!r}"
                    )
    assert not offenders, (
        "TC-SETUP-07: a published package's band descriptors carry magnitude phrasing — "
        "CT-SETUP-06 promises M-JUDGE never has to filter one:\n  " + "\n  ".join(offenders)
    )
