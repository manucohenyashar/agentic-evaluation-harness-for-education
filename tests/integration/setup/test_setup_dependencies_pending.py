"""`M-SETUP` Stage A's dependency proposals — written ahead of **#52**, needing **#51**
too (issue #54).

Case `TC-SETUP-13` (FR-SETUP-10, P0), rung 2. It waits on a *pair*, and that is stated in
its registry entry rather than papered over: the criteria a dependency attaches to come
out of the read back (#51's `read_back_rubric`), and the proposal itself is #52's
`propose_dependencies`. The entry keyed "#52 dependencies" in `tests/support/impl.py` is
a `symbols` conjunction over both, so the gate cannot fire while either is missing.

The case's own oracle decides what is asserted here: *"asserted by declining and
confirming no edge exists"*. So the file asserts the three quarters that need no approval
API — every criterion defaults to zero dependencies, a proposal is rendered in plain
language naming both criteria, and declining leaves the graph empty — and discloses the
fourth: the *positive* write on explicit approval is #52's to expose (the data layer's
`set_dependencies`, cycle-refusing inside its transaction, already landed with #31 and is
covered by its own cases).

The scripted dependency reply is this file's bet, as in the sibling pending files: the
reply carries the **facts** (a criterion pair and an error-carried-forward reason); the
plain-language rendering is the module's to do (FR-SETUP-10's own example sentence is the
standard). No rendered sentence is scripted.
"""

from __future__ import annotations

import json

import pytest

from aeh.pkg import PackageCatalog
from aeh.store import open_store

from tests.support.impl import SETUP_MODULE, require, require_attr
from tests.support.setup_harness import (
    INVENTORY_REPLY,
    ingest_document,
    stage_chain,
)
from tests.support.store_api import statement

pytestmark = pytest.mark.writtenahead

ISSUE = "#52"

#: The read back: two criteria in a subject where error-carried-forward is likely — the
#: derivation (Q3) uses the impulse definition (Q1).
ECF_RUBRIC_REPLY = json.dumps({"criteria": [
    {
        "criterion_id": "CRIT-IMP", "question_id": "Q1", "kind": "open",
        "scoring_model": "holistic", "max_points": 4.0,
        "construct": "the response defines impulse as force acting over contact time",
        "bands": [
            {"band": "met", "ordinal": 1, "points": 4.0,
             "descriptor": "the response names the net force and the contact time and "
                           "multiplies them"},
            {"band": "not met", "ordinal": 2, "points": 0.0,
             "descriptor": "the response omits either the force or the contact time"},
        ],
    },
    {
        "criterion_id": "CRIT-STEPS", "question_id": "Q3", "kind": "open",
        "scoring_model": "holistic", "max_points": 6.0,
        "construct": "the response carries the derivation through to a stated result, "
                     "using the impulse definition from the earlier part",
        "bands": [
            {"band": "met", "ordinal": 1, "points": 6.0,
             "descriptor": "the response derives the relation step by step and arrives "
                           "at the stated result"},
            {"band": "not met", "ordinal": 2, "points": 0.0,
             "descriptor": "the response stops before the derivation is carried through"},
        ],
    },
]})

#: The dependency the subject makes likely: grading the derivation sees the credited
#: definition. The reply carries facts; the plain-language sentence is rendered by #52.
ECF_DEPENDENCY_REPLY = json.dumps({"dependencies": [
    {
        "criterion_id": "CRIT-STEPS",
        "depends_on": "CRIT-IMP",
        "reason": "error carried forward: the derivation is graded on work that "
                  "presupposes the impulse definition",
    },
]})


def _dependency_edges(data_dir, package_id: str, issue: str) -> int:
    """How many dependency edges the version's stored graph carries."""
    # A raw handle is needed for the row count: the criteria read does not carry the
    # graph, and `set_dependencies` *replaces* rather than reads it.
    handle = PackageCatalog(open_store(data_dir).package(package_id),
                            package_id=package_id)
    with handle.transaction() as tx:
        version = handle.draft_version()
        rows = tx.execute(statement(
            "SELECT criterion_id, depends_on FROM criterion_dependency "
            "WHERE package_version_id = :v", issue=issue), v=version).fetchall()
    return len(rows)


@pytest.mark.integration
def test_tc_setup_13_dependencies_default_zero_proposal_plain_language_edge_only_on_approval(
    tmp_data_dir,
):
    """`TC-SETUP-13` (FR-SETUP-10, P0) — in a subject where error-carried-forward is
    likely: every criterion defaults to zero dependencies; a proposal is rendered in plain
    language naming both criteria (not a payload dump); and the edge is written **only**
    on explicit approval — asserted by declining, then confirming no edge exists."""
    setup = require(SETUP_MODULE, "SetupService", issue=ISSUE)
    require_attr(setup, "read_back_rubric", issue="#51")
    require_attr(setup, "propose_dependencies", issue=ISSUE)

    chain = stage_chain(tmp_data_dir)
    assessment = ingest_document(chain.store)
    rubric = ingest_document(chain.store, kind="rubric", name="rubric.pdf")
    chain.provider.replies = [
        INVENTORY_REPLY, ECF_RUBRIC_REPLY, ECF_DEPENDENCY_REPLY,
    ]
    proposal = chain.service.propose_inventory(assessment)
    chain.service.confirm_inventory(proposal.proposal_id)
    chain.service.read_back_rubric(rubric, assessment)
    version = chain.catalog.draft_version()

    # The default, before anything is proposed: zero dependencies everywhere.
    criteria = {row["criterion_id"] for row in chain.catalog.criteria(version)}
    assert criteria == {"CRIT-IMP", "CRIT-STEPS"}
    assert _dependency_edges(tmp_data_dir, chain.package_id, ISSUE) == 0, (
        "TC-SETUP-13: a criterion carried a dependency before anyone approved one — "
        "FR-SETUP-10 defaults every criterion to zero dependencies"
    )

    # The proposal: rendered in plain language, naming both criteria.
    proposals = chain.service.propose_dependencies()
    assert proposals, (
        "TC-SETUP-13: no dependency proposal was made in a subject where "
        "error-carried-forward is likely — the propose path produced nothing"
    )
    for item in proposals:
        rendered = str(item)
        assert "CRIT-IMP" in rendered and "CRIT-STEPS" in rendered, (
            f"TC-SETUP-13: the proposal does not name both criteria: {rendered!r} — "
            "FR-SETUP-10 renders each proposal in plain language naming both criteria"
        )
        assert "{" not in rendered and "}" not in rendered and "=" not in rendered, (
            f"TC-SETUP-13: the proposal reads as a payload dump, not plain language: "
            f"{rendered!r} — a dict dump carries braces and a dataclass repr carries "
            "'=' between field and value; neither is a sentence"
        )
        # The rendering must bind to the facts the reply carried — a default repr of an
        # unrendered object names the ids without ever surfacing the reason, so this
        # assertion is what makes "plain language" mean *this* proposal's language.
        assert "presupposes" in rendered.lower(), (
            "TC-SETUP-13: the rendered proposal does not carry the reply's own reason "
            "(error carried forward: the derivation is graded on work that presupposes "
            f"the impulse definition) — what rendered was {rendered!r}, which is not "
            "this proposal's plain language"
        )

    # Declined. No edge exists.
    assert _dependency_edges(tmp_data_dir, chain.package_id, ISSUE) == 0, (
        "TC-SETUP-13: an edge exists after the teacher declined — FR-SETUP-10 writes a "
        "dependency only on explicit teacher approval"
    )
    assert not chain.catalog.is_locked(version)  # nothing was published on the way
