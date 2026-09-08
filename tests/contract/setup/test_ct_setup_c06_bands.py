"""`CT-SETUP-06` — every criterion carries an even `band_count` in 2..6, and band
descriptors carry no magnitude phrasing (`TC-SETUP-C06`).

Case of test plan §6.11.6; issue #56 (TS-63). **Split disposition**, probed:

1. **The band-count half is green.** M-PKG refuses a declared band_count that is
   odd or outside 2..6 at the declare itself (`add_criterion`, src/aeh/pkg.py:1807,
   `BandSetError`) and re-validates the whole set at the publish boundary — every
   declared count fully populated, even, in 2..6, BEFORE the lock flips. Swept
   1, 3, 5, 7 and 0 as rejections; the accepted evens 2, 4, 6 carry through to a
   published artifact whose every criterion satisfies the invariant. Rung 2: real
   store, real catalog, real publish.
2. **The descriptor half is written ahead of #51.** Band descriptors must state
   what a response *does* — a descriptor matching the configured magnitude-phrase
   list (`SETUP_MAGNITUDE_PHRASES`) is rejected and regenerated before
   publication, so `M-JUDGE` never has to filter one. The magnitude list, the
   default band count, and the read back that performs the regeneration
   (`read_back_rubric`) are #51's; the test below carries `writtenahead` and a
   `WRITTEN_AHEAD_BLOCKERS` entry ("#56 C06 bands") keyed on all three together —
   the same conjunction #54's `tests/integration/setup/test_setup_readback_pending.py`
   waits on. It fails ONLY via `NotImplementedYet` until #51 lands.

The clause's downstream point shapes the oracles: the sweep is a *rejection*
sweep (the bad counts must never exist, even as drafts), and the artifact
assertion is over the PUBLISHED package — a downstream filter would be a second
enforcement point and RISK-04's re-entry route.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

import aeh.setup as aeh_setup  # not `setup_module`: pytest reads that name as the xunit hook
from aeh.pkg import BandSetError
from aeh.setup import SetupService
from tests.contract.setup._doubles import db_file_for, ingest_document, stage_chain
from tests.support.impl import require_attr

pytestmark = pytest.mark.contract

#: The sweep: odd counts and the boundaries outside the range. 0 is the null
#: count an unset default would silently produce; 7 is the first odd past 6.
REJECTED_BAND_COUNTS = (0, 1, 3, 5, 7)
#: The even counts the range admits, swept as acceptances.
ACCEPTED_BAND_COUNTS = (2, 4, 6)


def _draft(chain):
    """A draft version with a confirmed inventory — the state criteria attach to."""
    chain.doc = ingest_document(chain.store, kind="assessment")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)
    return chain.service.ensure_version()


def test_tc_setup_c06_band_count_sweep_rejects_odd_and_out_of_range(tmp_data_dir):
    """Sweep 1, 3, 5, 7 and 0 as rejections at the declare: `BandSetError`, and
    the criterion never exists — a set that can never satisfy the even-count
    rule must not exist even as a draft."""
    chain = stage_chain(tmp_data_dir, package_id="pkg-c06")
    version = _draft(chain)

    for count in REJECTED_BAND_COUNTS:
        with pytest.raises(BandSetError) as excinfo:
            chain.catalog.add_criterion(version, f"CRIT-BAD-{count}",
                                        question_id="Q1", kind="open",
                                        max_points=4.0, band_count=count)
        assert "2..6" in str(excinfo.value) or "even" in str(excinfo.value), (
            f"band_count={count} was refused without naming the rule (CT-SETUP-06)"
        )
        created = {c["criterion_id"] for c in chain.catalog.criteria(version)}
        assert f"CRIT-BAD-{count}" not in created, (
            f"band_count={count} left a criterion behind — the refusal was not a "
            "no-op (CT-SETUP-06)"
        )


def test_tc_setup_c06_published_artifact_carries_even_band_counts_in_range(
        tmp_data_dir):
    """The artifact invariant, on the PUBLISHED package: every criterion that
    declares a band_count carries an even count in 2..6, fully populated — read
    from the published version through the catalog (the reading `M-JUDGE` makes),
    so no consumer ever needs a special case for a bad count."""
    chain = stage_chain(tmp_data_dir, package_id="pkg-c06p")
    version = _draft(chain)

    # Criteria at each accepted even count, bands populated to the declared
    # count (monotone points, ascending ordinals — the whole-set rules).
    descriptors = {
        2: ("the response states the definition unprompted",
            "the response omits or misstates the definition"),
        4: ("the derivation is complete and stated",
            "the derivation is carried partway with a slip",
            "the method is named but not carried through",
            "no method appears"),
        6: ("the result is exact and justified",
            "the result is correct with a minor gap in justification",
            "the result is reached with one reasoning slip",
            "partial method, no result",
            "method named only",
            "no attempt"),
    }
    for i, count in enumerate(ACCEPTED_BAND_COUNTS):
        criterion_id = f"CRIT-EVEN-{count}"
        chain.catalog.add_criterion(version, criterion_id,
                                    question_id=f"Q{i + 1}", kind="open",
                                    max_points=float(count), band_count=count)
        for ordinal, descriptor in enumerate(descriptors[count]):
            chain.catalog.add_band(version, criterion_id, ordinal,
                                   f"b{ordinal}", float(ordinal),
                                   descriptor=descriptor)

    # Gate 2 (the answer-keys blocking step) requires every criterion keyed:
    # the key names the criterion's acceptable band (the write-through surface
    # stores the ids; #53 stages FR-SETUP-03's full semantics).
    chain.service.set_answer_keys(
        {f"CRIT-EVEN-{count}": ["b0"] for count in ACCEPTED_BAND_COUNTS})

    # Publish through SETUP (the route the clause governs): the setup publish's
    # own gates run, then M-PKG's publish-boundary validation.
    chain.service.publish("teacher-1")

    criteria = chain.catalog.criteria(version)
    assert criteria, "the published package carries no criteria"
    for criterion in criteria:
        declared = criterion["band_count"]
        assert declared is None or (declared % 2 == 0 and 2 <= declared <= 6), (
            f"published criterion {criterion['criterion_id']!r} carries a "
            f"band_count of {declared} — odd or outside 2..6 (CT-SETUP-06)"
        )
        if declared is not None:
            bands = chain.catalog.bands(criterion["criterion_id"])
            assert len(bands) == declared, (
                f"published criterion {criterion['criterion_id']!r} declares "
                f"{declared} bands but carries {len(bands)} (CT-SETUP-06)"
            )
    # And the sweep's complement really is in the artifact: all three accepted
    # counts survive, so the invariant was not vacuously true on an empty set.
    counts = {c["band_count"] for c in criteria}
    assert set(ACCEPTED_BAND_COUNTS) <= counts, (
        f"the published artifact lost a swept count — invariant asserted over "
        f"{sorted(counts)} (CT-SETUP-06)"
    )


@pytest.mark.writtenahead
def test_tc_setup_c06_magnitude_descriptors_are_rejected_and_regenerated(
        tmp_data_dir):
    """WRITTEN AHEAD of #51. A band descriptor matching the configured
    magnitude-phrase list is rejected and regenerated BEFORE publication, and
    the published artifact is clean — `M-JUDGE` never filters a descriptor.

    Fails ONLY via `NotImplementedYet` (through `require_attr`) until #51 lands
    `read_back_rubric` with its two constants. The scripted reply uses the
    payload shape the oracle implies (criterion entries with bands and
    descriptors); when #51 lands, align the scripting to its schema — the
    assertions do not change."""
    require_attr(aeh_setup, "SETUP_MAGNITUDE_PHRASES", issue="#51")
    require_attr(aeh_setup, "SETUP_DEFAULT_BAND_COUNT", issue="#51")
    require_attr(SetupService, "read_back_rubric", issue="#51")

    chain = stage_chain(tmp_data_dir, package_id="pkg-c06m")
    chain.doc = ingest_document(chain.store, kind="assessment")
    rubric = ingest_document(chain.store, kind="rubric", name="rubric.pdf")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)

    # The adversarial input: descriptors that grade the GRADER's enthusiasm
    # ("very", "extremely") instead of stating what a response does — exactly
    # the magnitude phrasing the configured list exists to catch.
    chain.provider.replies = [json.dumps({"criteria": [{
        "criterion_id": "CRIT-MAG", "question_id": "Q1", "kind": "open",
        "scoring_model": "atomic", "max_points": 4.0,
        "construct": "the response defines impulse",
        "band_count": 2,
        "bands": [
            {"ordinal": 0, "band": "b0", "points": 4.0,
             "descriptor": "a very strong and extremely thorough answer"},
            {"ordinal": 1, "band": "b1", "points": 0.0,
             "descriptor": "a very poor answer"},
        ],
    }]})]
    readback = chain.service.read_back_rubric(rubric, chain.doc)

    # Regeneration, not passage: no returned descriptor matches a magnitude
    # phrase, and the offending descriptor CHANGED — the rejection is visible
    # as a different descriptor, not a silent keep.
    phrases = tuple(aeh_setup.SETUP_MAGNITUDE_PHRASES)
    for criterion in readback.criteria:
        for band in criterion.bands:
            lowered = band.descriptor.lower()
            assert not any(phrase in lowered for phrase in phrases), (
                f"band descriptor {band.descriptor!r} reached the package with "
                "magnitude phrasing — M-JUDGE would have to filter it "
                "(CT-SETUP-06, RISK-04's second enforcement point)"
            )
    offending = "a very strong and extremely thorough answer"
    returned = [band.descriptor for criterion in readback.criteria
                for band in criterion.bands]
    assert offending not in returned, (
        "the magnitude-carrying descriptor passed through unchanged — no "
        "regeneration happened (CT-SETUP-06)"
    )

    # The ARTIFACT half — the clause's oracle is a scan of the PUBLISHED
    # descriptors, not the return value: a read/write mismatch (clean return,
    # magnitude-phrased rows stored) must fail here. The read back WRITES the
    # criteria it classified (the bet TC-SETUP-C05 states); the stored bands
    # are what M-JUDGE reads, so those are what get scanned.
    chain.service.set_answer_keys({"CRIT-MAG": ["b0"]})
    published = chain.service.publish("teacher-1")
    assert chain.catalog.is_locked(published)
    stored_bands = chain.catalog.bands("CRIT-MAG")
    assert stored_bands, (
        "the read back's criterion carried no stored bands — the artifact scan "
        "has nothing to read (CT-SETUP-06)"
    )
    for band in stored_bands:
        lowered = band["descriptor"].lower()
        assert not any(phrase in lowered for phrase in phrases), (
            f"the PUBLISHED band descriptor {band['descriptor']!r} carries "
            "magnitude phrasing — M-JUDGE would have to filter it "
            "(CT-SETUP-06, the second enforcement point)"
        )
        assert band["descriptor"] != offending, (
            "the offending descriptor reached the PUBLISHED artifact although "
            "the read back returned a regenerated one — the write path ignored "
            "the regeneration (CT-SETUP-06)"
        )
