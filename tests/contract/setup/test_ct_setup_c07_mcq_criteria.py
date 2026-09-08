"""`CT-SETUP-07` — mcq questions yield deterministic criteria; no deterministic
criterion publishes without an answer key (`TC-SETUP-C07`).

Case of test plan §6.11.6; issue #56 (TS-63). **Split disposition**, probed:

1. **The no-escape half is green.** A `deterministic` criterion cannot publish
   without an answer key — no default, no skip. The setup publish's gate 2
   enumerates every atomic criterion lacking a key and refuses BY NAME with
   "blocking gate 2 of 2" (src/aeh/setup.py:1041-1048); the refusal is pre-lock,
   and keying unblocks the same version. Probed on shipped code.
2. **The mcq-production half landed with #53.** For every `mcq`
   question, the PRODUCED criterion is deterministic — the shipped gate's own
   definition (scoring_model `atomic`, the column the acceptance rule reads) —
   carries EXACTLY two bands named `correct`/`incorrect`, and is NOT submitted
   to the §5.3 test. #53 stages it at the confirmation itself; the
   `writtenahead` marker and its `WRITTEN_AHEAD_BLOCKERS` entry ("#56 C07 mcq
   criteria") are gone. One oracle alignment was forced by the landing: the
   bands' ORDER in ordinal is `incorrect` (0.0) then `correct` (max_points),
   because FR-PKG-06 requires the band points non-decreasing in ordinal —
   the names-SET assertion below is the invariant; a tuple-in-ordinal-order
   assertion could not hold alongside the points rule.

**Disclosed bet** (stated, not hidden): the clause's `evaluation_mode =
'deterministic'` vocabulary has NO storage anywhere — no such column exists in
M-PKG's schema (the same absence #54's deferred TC-SETUP-16 note records). The
shipped deterministic test is `scoring_model == "atomic"` (setup.py:1041), and
the acceptance rule consumers run is keyed on that column. This case asserts
the stored carrier; when #53 lands an `evaluation_mode` column, the assertion
widens to it — never weakens.
"""
from __future__ import annotations

import json

import pytest

from aeh.setup import SetupOrderError, SetupService
from tests.contract.setup._doubles import ingest_document, stage_chain
from tests.support.impl import require_attr

pytestmark = pytest.mark.contract

ISSUE = "#53"


def _chain_with_atomic_criterion(tmp_data_dir, package_id):
    """A draft with a confirmed inventory and ONE unkeyed atomic criterion."""
    chain = stage_chain(tmp_data_dir, package_id=package_id)
    chain.doc = ingest_document(chain.store, kind="assessment")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)
    version = chain.service.ensure_version()
    chain.catalog.add_criterion(version, "CRIT-DET", question_id="Q1",
                                kind="open", max_points=4.0,
                                scoring_model="atomic")
    return chain, version


def test_tc_setup_c07_no_deterministic_criterion_publishes_without_a_key(
        tmp_data_dir):
    """The no-escape sweep: with an unkeyed atomic criterion present, publish
    refuses BY NAME — no default key, no skip — the version stays unlocked, and
    keying the criterion (the teacher's act) is what unblocks the same publish."""
    chain, version = _chain_with_atomic_criterion(tmp_data_dir, "pkg-c07")

    with pytest.raises(SetupOrderError) as excinfo:
        chain.service.publish("teacher-1")
    message = str(excinfo.value)
    assert "CRIT-DET" in message, (
        "the refusal did not name the unkeyed criterion — a teacher could not "
        "act on it (CT-SETUP-C07)"
    )
    assert "gate 2 of 2" in message, (
        "the refusal did not name its gate — exactly two screens block, and "
        "the console renders the refusal verbatim (CT-SETUP-C07)"
    )
    # Pre-lock: the refusal left nothing published — no default key was invented.
    assert not chain.catalog.is_locked(version), (
        "publish without a key still locked the version — the escape happened "
        "(CT-SETUP-C07)"
    )
    assert not chain.catalog.criteria(version)[0].get("answer_key"), (
        "a default answer key was invented by the refused publish (CT-SETUP-C07)"
    )

    # The key is the teacher's act, and it unblocks the SAME version — every
    # deterministic criterion keyed: the hand-added CRIT-DET plus the ones #53
    # staged from the confirmed inventory (CRIT-Q4/Q5/Q6).
    chain.service.set_answer_keys({"CRIT-DET": ["b0"]}
                                  | {"CRIT-Q4": ["A"], "CRIT-Q5": ["A"],
                                     "CRIT-Q6": ["A"]})
    published = chain.service.publish("teacher-1")
    assert chain.catalog.is_locked(published)


def test_tc_setup_c07_every_mcq_question_yields_a_keyed_shape_criterion(
        tmp_data_dir):
    """#53 landed the staging: for EVERY mcq question the produced criterion is
    deterministic (the shipped gate's carrier: scoring_model `atomic`), carries
    EXACTLY two bands named `correct`/`incorrect`, and was NOT submitted to the
    §5.3 test — the classifier never sees an mcq question. The staging happens
    at the confirmation itself (#53), so the produced criteria exist before any
    #53 call is made."""
    require_attr(SetupService, "set_grade_policy", issue="#53")
    require_attr(SetupService, "check_prefix_budget", issue="#53")

    chain = stage_chain(tmp_data_dir, package_id="pkg-c07m")
    chain.doc = ingest_document(chain.store, kind="assessment")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)
    version = proposal.package_version_id

    # The confirmed inventory's mcq questions (Q4 and Q5 in the scripted reply).
    mcq_ids = [q["question_id"] for q in chain.catalog.questions(version)
               if q["question_type"] == "mcq"]
    assert mcq_ids, "the fixture inventory carries no mcq question"

    # #53 produces the criteria for them; after it lands, every mcq question
    # has its produced criterion.
    produced = {}
    for question_id in mcq_ids:
        rows = chain.catalog.criteria(version, question_id=question_id)
        assert rows, (
            f"mcq question {question_id!r} produced no criterion — the "
            "deterministic shape is #53's to land (CT-SETUP-C07)"
        )
        produced[question_id] = rows[0]

    for question_id, criterion in produced.items():
        # The deterministic carrier the shipped gate and the acceptance rule
        # both read (the evaluation_mode vocabulary is disclosed above).
        assert criterion["scoring_model"] == "atomic", (
            f"the criterion produced for mcq {question_id!r} is not "
            f"deterministic (scoring_model={criterion['scoring_model']!r}) "
            "(CT-SETUP-C07)"
        )
        # Exactly two bands, named correct/incorrect — not the derived
        # met/not-met set, not the criterion's declared count. The ORDER is
        # disclosed: FR-PKG-06 requires the band POINTS to be non-decreasing in
        # ordinal, so the zero-point `incorrect` band sits at ordinal 0 and
        # `correct` (max_points) at ordinal 1 — the shape #53 stages. The set is
        # the invariant; a tuple assertion in ordinal order would contradict the
        # points rule the same schema enforces.
        bands = chain.catalog.bands(criterion["criterion_id"])
        names = tuple(band["band"] for band in bands)
        assert set(names) == {"correct", "incorrect"} and len(names) == 2, (
            f"mcq {question_id!r}'s criterion carries bands {names} — exactly "
            "correct/incorrect is the produced shape (CT-SETUP-C07)"
        )
    # NOT submitted to the §5.3 test: the scripted provider's call log carries
    # no decomposability request for the produced criteria — a §5.3 request
    # names the five questions it asks about, which the inventory prompt never
    # does.
    classifier_signature = ("completeness", "non_interference", "independence",
                            "additivity", "gates")
    classify_calls = [call for call in chain.provider.calls
                      if any(word in json.dumps(call)
                             for word in classifier_signature)]
    assert not classify_calls, (
        "an mcq question was submitted to the §5.3 test — its criterion shape "
        "is fixed, not classified (CT-SETUP-C07)"
    )