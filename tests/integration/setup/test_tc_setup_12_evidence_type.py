"""`TC-SETUP-12` (FR-SETUP-09, P1) — publication refuses a judged criterion without
its `evidence_type` (#232).

Deferred, not written ahead: #54 (TS-20) held the case out because its oracle turned
on "an `evidence_type` column that does not exist and no interface member carries"
(disclosed on the #54 PR; see `WRITTEN_AHEAD_BLOCKERS`' TS-20 note). Migration 8
added the column and #51 (PR #216) shipped the write half — the read back attaches
`SETUP_EVIDENCE_TYPE_DEFAULT` when the model proposes none and stores whatever
non-empty declaration it does propose. This file is the refusal half the oracle
names: publication refuses while any judged criterion lacks the declaration, and
proceeds when every judged criterion carries one.

The state the refusal catches is reachable through shipped surfaces only: the
degraded read back routes the teacher to M-PKG hand-entry ("the teacher enters the
criteria through M-PKG", `needs_manual_entry`), and `PackageCatalog.add_criterion`
writes a judged criterion (kind `open`) whose `evidence_type` stays NULL. A package
cannot lock with an undeclared criterion in it — M-INTEG routes on the declaration
(FR-INTEG-03) — and the refusal names EVERY offender, not just the first.

The deterministic criteria #53 stages (kind `mcq`, `evidence_type` NULL) are keyed,
not judged, and are exempt: the gate reads judged-ness, not the whole criterion set.
"""

from __future__ import annotations

import pytest

from aeh.setup import SETUP_EVIDENCE_TYPE_DEFAULT, SetupOrderError
from tests.support.setup_harness import (
    ingest_document,
    stage_chain,
)

ISSUE = "#232"


def _confirmed_chain(tmp_data_dir):
    """The chain through the confirmed inventory: the state publish's gates read."""
    chain = stage_chain(tmp_data_dir)
    assessment = ingest_document(chain.store)
    proposal = chain.service.propose_inventory(assessment)
    chain.service.confirm_inventory(proposal.proposal_id)
    return chain, assessment, chain.catalog.draft_version()


def _key_staged_criteria(chain) -> None:
    """Key the deterministic criteria #53 staged from the confirmed inventory, so
    blocking gate 2 is out of the way and the case's assertions land on the
    `FR-SETUP-09` structural check."""
    chain.service.set_answer_keys(
        {"CRIT-Q4": ["A"], "CRIT-Q5": ["A"], "CRIT-Q6": ["A"]})


def _hand_entered_criterion(chain, version, criterion_id: str,
                            question_id: str) -> None:
    """One judged criterion entered through M-PKG's surface — the path the degraded
    read back routes the teacher to. Kind `open` (judged), `holistic` (the unclear
    default a hand entry carries; an `atomic` classification would put the criterion
    in blocking gate 2's unkeyed set instead), and no `evidence_type` —
    `add_criterion` has no parameter for one, which is exactly the hole the gate
    closes."""
    chain.catalog.add_criterion(
        version, criterion_id, question_id=question_id, scoring_model="holistic",
        max_points=4.0, band_count=2)
    chain.catalog.add_band(version, criterion_id, 0, "not met", 0.0)
    chain.catalog.add_band(version, criterion_id, 1, "met", 4.0)


# --- TC-SETUP-12, limb 1: the refusal -------------------------------------------------------


@pytest.mark.integration
def test_tc_setup_12_publish_refuses_a_judged_criterion_without_evidence_type(
    tmp_data_dir,
):
    """`TC-SETUP-12` limb 1 — a draft holding a judged criterion without an
    `evidence_type` is refused at `publish()`, the refusal names the criterion, and
    the version stays an unlocked draft. A second offender is refused in the SAME
    message: the refusal names every offending criterion, not just the first."""
    chain, assessment, version = _confirmed_chain(tmp_data_dir)
    _key_staged_criteria(chain)
    _hand_entered_criterion(chain, version, "CRIT-HAND", "Q1")

    with pytest.raises(SetupOrderError) as refused:
        chain.service.publish("teacher-1")
    message = str(refused.value)
    assert "CRIT-HAND" in message, (
        "TC-SETUP-12: the refusal does not name the judged criterion that lacks its "
        f"evidence_type — got: {message}"
    )
    assert "FR-SETUP-09" in message, (
        "TC-SETUP-12: the refusal does not trace to FR-SETUP-09 — got: "
        f"{message}"
    )
    # Refused, not half-done: the version is still an unlocked draft — the same
    # writes-nothing promise the blocking gates' refusals keep (CT-SETUP-02's shape).
    assert not chain.catalog.is_locked(version), (
        "TC-SETUP-12: the refused publish locked the version anyway"
    )
    assert chain.catalog.draft_version() == version, (
        "TC-SETUP-12: the refused publish consumed the draft"
    )

    # A second undeclared criterion, and the SAME refusal names both.
    _hand_entered_criterion(chain, version, "CRIT-FLAW", "Q2")
    with pytest.raises(SetupOrderError) as refused_both:
        chain.service.publish("teacher-1")
    both = str(refused_both.value)
    assert "CRIT-HAND" in both and "CRIT-FLAW" in both, (
        "TC-SETUP-12: the refusal names only some of the offending criteria — "
        f"CRIT-HAND and CRIT-FLAW are both untyped; got: {both}"
    )


# --- TC-SETUP-12, limb 2: the biconditional -------------------------------------------------


@pytest.mark.integration
def test_tc_setup_12_every_judged_criterion_typed_publishes_and_deterministic_exempt(
    tmp_data_dir,
):
    """`TC-SETUP-12` limbs 2 and 3 — the biconditional. A draft whose judged
    criteria each carry an `evidence_type` publishes (a blanket refusal would break
    the shipped #51 path), each judged row's stored value is exact — the default
    where the model proposed none, the proposal where it did — and the deterministic
    criteria, which carry NO `evidence_type` in storage, are exempt: publication
    proceeds with them untyped, because the gate reads judged-ness."""
    chain = stage_chain(tmp_data_dir)
    assessment = ingest_document(chain.store)
    rubric = ingest_document(chain.store, kind="rubric", name="rubric.pdf")
    proposal = chain.service.propose_inventory(assessment)
    chain.service.confirm_inventory(proposal.proposal_id)

    # Two judged criteria: one that proposes its own evidence_type, one that proposes
    # none and so takes the default the read back attaches. The design pins no closed
    # vocabulary (the read back stores whatever non-empty declaration is proposed),
    # so the explicit value here is an arbitrary non-empty declaration.
    chain.provider.replies = [  # the read-back round
        _readback_reply([
            {"criterion_id": "CRIT-MET", "question_id": "Q1", "kind": "open",
             "scoring_model": "holistic", "max_points": 4.0,
             "construct": "the response defines impulse as force acting over "
                          "contact time"},
            {"criterion_id": "CRIT-TYPED", "question_id": "Q2", "kind": "open",
             "scoring_model": "holistic", "max_points": 5.0,
             "construct": "the response derives the range equation",
             "evidence_type": "worked_formula"},
        ])
    ]
    chain.service.read_back_rubric(rubric, assessment)
    _key_staged_criteria(chain)

    version = chain.service.publish("teacher-1")
    assert chain.catalog.is_locked(version)

    rows = {row["criterion_id"]: row for row in chain.catalog.criteria(version)}
    judged = {cid: row for cid, row in rows.items() if row["kind"] == "open"}
    deterministic = {cid: row for cid, row in rows.items() if row["kind"] == "mcq"}

    assert set(judged) == {"CRIT-MET", "CRIT-TYPED"}, (
        "TC-SETUP-12: the published package's judged set is not the read back's — "
        f"got {sorted(judged)}"
    )
    for criterion_id, row in judged.items():
        expected = ("worked_formula" if criterion_id == "CRIT-TYPED"
                    else SETUP_EVIDENCE_TYPE_DEFAULT)
        assert row["evidence_type"] == expected, (
            f"TC-SETUP-12: judged criterion {criterion_id} stored evidence_type "
            f"{row['evidence_type']!r}, expected {expected!r} — the oracle is the "
            "exact value (test plan §5.6)"
        )

    # Limb 3, visible in the same published artifact: the deterministic criteria
    # carry NO evidence_type, and the package locked anyway.
    assert set(deterministic) == {"CRIT-Q4", "CRIT-Q5", "CRIT-Q6"}, (
        "TC-SETUP-12: the staged deterministic criteria are not the confirmed "
        f"inventory's mcq/mixed set — got {sorted(deterministic)}"
    )
    untyped = [cid for cid, row in deterministic.items()
               if str(row["evidence_type"] or "").strip()]
    assert not untyped, (
        f"TC-SETUP-12: deterministic criteria {untyped} unexpectedly carry an "
        "evidence_type — the exemption is no longer exercised by this case"
    )


def _readback_reply(criteria: list[dict]) -> str:
    """One scripted read-back reply in the payload shape the read back parses."""
    import json

    return json.dumps({"criteria": criteria})
