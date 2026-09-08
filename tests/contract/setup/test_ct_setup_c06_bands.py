"""`CT-SETUP-06` — every criterion carries an even `band_count` in 2..6, and band
descriptors carry no magnitude phrasing (`TC-SETUP-C06`).

Case of test plan §6.11.6; issue #56 (TS-63). **Green by design**, probed:

1. **The band-count half.** M-PKG refuses a declared band_count that is
   odd or outside 2..6 at the declare itself (`add_criterion`, src/aeh/pkg.py:1807,
   `BandSetError`) and re-validates the whole set at the publish boundary — every
   declared count fully populated, even, in 2..6, BEFORE the lock flips. Swept
   1, 3, 5, 7 and 0 as rejections; the accepted evens 2, 4, 6 carry through to a
   published artifact whose every criterion satisfies the invariant. Rung 2: real
   store, real catalog, real publish.
2. **The descriptor half.** Band descriptors must state what a response *does* —
   a descriptor matching the configured magnitude-phrase list
   (`SETUP_MAGNITUDE_PHRASES`) or carrying a bare numeral is rejected and
   regenerated before publication, so `M-JUDGE` never has to filter one. The
   bar lives in the rubric read back (`read_back_rubric`, landed with #51 via
   PR #216 — the rebase check that flipped this file's last writtenahead case
   to green): a reply that offends is re-requested within the
   `HARNESS_SETUP_READBACK_ATTEMPTS` budget, and after the budget the read
   back degrades to `needs_manual_entry` with nothing stored.

The clause's downstream point shapes the oracles: the sweep is a *rejection*
sweep (the bad counts must never exist, even as drafts), and the artifact
assertion is over the PUBLISHED package — a downstream filter would be a second
enforcement point and RISK-04's re-entry route.
"""
from __future__ import annotations

import json

import pytest

import aeh.setup as aeh_setup  # not `setup_module`: pytest reads that name as the xunit hook
from aeh.pkg import BandSetError
from tests.contract.setup._doubles import ingest_document, stage_chain

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


def test_tc_setup_c06_magnitude_descriptors_are_rejected_and_regenerated(
        tmp_data_dir, monkeypatch):
    """A band descriptor carrying magnitude language is rejected and
    REGENERATED by the rubric read back (`FR-SETUP-05`), never stored — on the
    shipped surface (`read_back_rubric`, #51).

    Both arms of the configured bar are swept: the phrase arm
    (`SETUP_MAGNITUDE_PHRASES`, case-insensitive substring) and the bare-numeral
    arm (any digit — a points scale in disguise). The attempt budget is pinned
    through its env knob (`HARNESS_SETUP_READBACK_ATTEMPTS`, read at call time)
    so the re-request is deterministic: attempt 1 offends on both arms and is
    refused, attempt 2 is clean and is what gets proposed — `attempts == 2` is
    the rejection visible in the attempt record. The clause's oracle is the
    PUBLISHED artifact: the stored descriptors are what `M-JUDGE` reads, so
    they get the same scan the return value got."""
    monkeypatch.setenv("HARNESS_SETUP_READBACK_ATTEMPTS", "2")
    chain = stage_chain(tmp_data_dir, package_id="pkg-c06m")
    chain.doc = ingest_document(chain.store, kind="assessment")
    rubric = ingest_document(chain.store, kind="rubric", name="rubric.pdf")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)

    phrase_offender = "an excellent and thoroughly strong answer"
    numeral_offender = "the response earns 4 of the 5 available points"
    clean = {
        "CRIT-MAG": {
            "criterion_id": "CRIT-MAG", "question_id": "Q1", "kind": "open",
            "scoring_model": "atomic", "max_points": 4.0,
            "construct": "the response defines impulse", "band_count": 2,
            "bands": [
                {"band": "b0", "ordinal": 0, "points": 4.0,
                 "descriptor": "the response states the definition with the "
                               "force acting over the contact time"},
                {"band": "b1", "ordinal": 1, "points": 0.0,
                 "descriptor": "the response omits the definition"},
            ],
        },
        "CRIT-NUM": {
            "criterion_id": "CRIT-NUM", "question_id": "Q2", "kind": "open",
            "scoring_model": "holistic", "max_points": 5.0,
            "construct": "the response carries the derivation through",
            "band_count": 2,
            "bands": [
                {"band": "b0", "ordinal": 0, "points": 5.0,
                 "descriptor": "the derivation reaches a stated result"},
                {"band": "b1", "ordinal": 1, "points": 0.0,
                 "descriptor": "no derivation appears"},
            ],
        },
    }
    offending = json.dumps({"criteria": [
        # Attempt 1: one criterion offends on the phrase arm, one on the
        # numeral arm — both refused before anything is written.
        {**clean["CRIT-MAG"],
         "bands": [{**clean["CRIT-MAG"]["bands"][0],
                    "descriptor": phrase_offender},
                   clean["CRIT-MAG"]["bands"][1]]},
        {**clean["CRIT-NUM"],
         "bands": [{**clean["CRIT-NUM"]["bands"][0],
                    "descriptor": numeral_offender},
                   clean["CRIT-NUM"]["bands"][1]]},
    ]})
    chain.provider.replies = [offending, json.dumps({"criteria": list(
        clean.values())})]
    readback = chain.service.read_back_rubric(rubric, chain.doc)

    # The rejection consumed an attempt; the regeneration is what came back.
    assert readback.status == "proposed", (
        f"the read back degraded ({readback.status!r}) instead of regenerating "
        "a clean reply (CT-SETUP-06)"
    )
    assert readback.attempts == 2, (
        f"the read back spent {readback.attempts} attempt(s) — a "
        "first-attempt acceptance means the magnitude bar never fired "
        "(CT-SETUP-06)"
    )

    phrases = tuple(aeh_setup.SETUP_MAGNITUDE_PHRASES)
    returned = [band.descriptor for criterion in readback.criteria
                for band in criterion.bands]
    assert returned, "the read back returned no descriptors to scan"
    for descriptor in returned:
        lowered = descriptor.lower()
        assert not any(phrase in lowered for phrase in phrases), (
            f"band descriptor {descriptor!r} carries a magnitude phrase — "
            "M-JUDGE would have to filter it (CT-SETUP-06, RISK-04's second "
            "enforcement point)"
        )
        assert not any(ch.isdigit() for ch in descriptor), (
            f"band descriptor {descriptor!r} carries a bare numeral — a "
            "points scale in disguise (CT-SETUP-06)"
        )
    assert phrase_offender not in returned and numeral_offender not in returned, (
        "an offending descriptor passed through unchanged — no regeneration "
        "happened (CT-SETUP-06)"
    )

    # The ARTIFACT half — the same scan over the PUBLISHED descriptors: a
    # read/write mismatch (clean return, phrased rows stored) fails here.
    chain.service.set_answer_keys(
        {"CRIT-MAG": ["b0"], "CRIT-NUM": ["b0"]})
    published = chain.service.publish("teacher-1")
    assert chain.catalog.is_locked(published)
    for criterion_id in ("CRIT-MAG", "CRIT-NUM"):
        stored_bands = chain.catalog.bands(criterion_id)
        assert stored_bands, (
            f"the read back's criterion {criterion_id!r} carried no stored "
            "bands — the artifact scan has nothing to read (CT-SETUP-06)"
        )
        for band in stored_bands:
            lowered = band["descriptor"].lower()
            assert not any(phrase in lowered for phrase in phrases), (
                f"the PUBLISHED band descriptor {band['descriptor']!r} carries "
                "magnitude phrasing — M-JUDGE would have to filter it "
                "(CT-SETUP-06, the second enforcement point)"
            )
            assert not any(ch.isdigit() for ch in band["descriptor"]), (
                f"the PUBLISHED band descriptor {band['descriptor']!r} carries "
                "a bare numeral (CT-SETUP-06)"
            )
            assert band["descriptor"] not in (phrase_offender, numeral_offender), (
                "the offending descriptor reached the PUBLISHED artifact "
                "although the read back returned a regenerated one — the write "
                "path ignored the rejection (CT-SETUP-06)"
            )


def test_tc_setup_c06_the_magnitude_refusal_is_the_recorded_reason(
        tmp_data_dir, monkeypatch):
    """When EVERY attempt offends, the read back degrades to
    `needs_manual_entry` with the bar's own wording as the reason — and nothing
    is stored: the rejected descriptors never reach the package, at budget end
    just as mid-budget (`FR-SETUP-05`'s never-stored, `CT-SETUP-12`'s
    degraded-but-complete)."""
    monkeypatch.setenv("HARNESS_SETUP_READBACK_ATTEMPTS", "1")
    chain = stage_chain(tmp_data_dir, package_id="pkg-c06x")
    chain.doc = ingest_document(chain.store, kind="assessment")
    rubric = ingest_document(chain.store, kind="rubric", name="rubric.pdf")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)

    numeral_offender = "the response earns 4 of the 5 available points"
    chain.provider.replies = [json.dumps({"criteria": [{
        "criterion_id": "CRIT-NUM", "question_id": "Q1", "kind": "open",
        "scoring_model": "atomic", "max_points": 4.0,
        "construct": "the response defines impulse", "band_count": 2,
        "bands": [
            {"band": "b0", "ordinal": 0, "points": 4.0,
             "descriptor": numeral_offender},
            {"band": "b1", "ordinal": 1, "points": 0.0,
             "descriptor": "the response omits the definition"},
        ],
    }]})]
    readback = chain.service.read_back_rubric(rubric, chain.doc)

    assert readback.status == "needs_manual_entry", (
        f"an all-offending budget produced {readback.status!r} — the degraded "
        "path is the honest end of a spent budget (CT-SETUP-06)"
    )
    assert not readback.criteria, (
        "the degraded read back carried criteria (CT-SETUP-06)"
    )
    assert "bare numeral" in readback.reason, (
        f"the recorded reason {readback.reason!r} does not name the magnitude "
        "bar — the operator cannot see why the read back degraded "
        "(CT-SETUP-06)"
    )
    version = proposal.package_version_id
    assert not chain.catalog.criteria(version), (
        "a magnitude-refused read back left criterion rows behind — the "
        "rejected descriptors reached the package (CT-SETUP-06)"
    )
