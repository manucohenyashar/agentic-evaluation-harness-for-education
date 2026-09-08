"""`M-SETUP` Stage A's dependency proposals — **#52**'s integration case (issue #54).

Case `TC-SETUP-13` (FR-SETUP-10, P0), rung 2. It waited on a *pair*, and that was stated
in its registry entry rather than papered over: the criteria a dependency attaches to come
out of the read back (#51's `read_back_rubric`, landed via PR #216), and the proposal
itself is #52's `propose_dependencies`. The entry keyed "#52 dependencies" in
`tests/support/impl.py` was a `symbols` conjunction over both — the marker and the entry
are gone now that both halves are green.

The case's own oracle decides what is asserted here: *"asserted by declining and
confirming no edge exists"*. So the file asserts the three quarters that need no approval
API — every criterion defaults to zero dependencies, a proposal is rendered in plain
language naming both criteria, and declining leaves the graph empty. The fourth quarter —
the *positive* write on explicit approval — is `confirm_dependencies`' to expose, and the
second test below pins it (the reviewer finding this PR closes: the sole edge-write path
was otherwise unasserted end to end; the data layer's `set_dependencies`, cycle-refusing
inside its transaction, already landed with #31 and is covered by its own cases).

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


def _dependency_edges(data_dir, package_id: str, version: str, issue: str) -> list:
    """The version's stored dependency edges as raw (criterion_id, depends_on) rows."""
    # A raw tier handle is needed for the row read: the criteria read does not
    # carry the graph, and `set_dependencies` *replaces* rather than reads it.
    # The version is the caller's (`chain.catalog.draft_version()`) — a fresh
    # `PackageCatalog` has no `transaction()` to borrow, and re-opening the tier
    # for its draft would race the chain's own view of "latest unpublished".
    handle = open_store(data_dir).package(package_id)
    with handle.transaction() as tx:
        return tx.execute(statement(
            "SELECT criterion_id, depends_on FROM criterion_dependency "
            "WHERE package_version_id = :v ORDER BY criterion_id, depends_on",
            issue=issue), v=version)


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
    # #53 stages CRIT-Q4/Q5/Q6 from the confirmed inventory, alongside the read-back's two.
    criteria = {row["criterion_id"] for row in chain.catalog.criteria(version)}
    assert criteria == {"CRIT-IMP", "CRIT-STEPS", "CRIT-Q4", "CRIT-Q5", "CRIT-Q6"}
    assert len(_dependency_edges(tmp_data_dir, chain.package_id, version, ISSUE)) == 0, (
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
    assert len(_dependency_edges(tmp_data_dir, chain.package_id, version, ISSUE)) == 0, (
        "TC-SETUP-13: an edge exists after the teacher declined — FR-SETUP-10 writes a "
        "dependency only on explicit teacher approval"
    )
    assert not chain.catalog.is_locked(version)  # nothing was published on the way


@pytest.mark.integration
def test_tc_setup_13_approval_writes_exactly_the_proposed_edge_and_survives_a_confirmation(
    tmp_data_dir,
):
    """`TC-SETUP-13`'s positive half (`FR-SETUP-10`) — the write on EXPLICIT approval:
    approving a recorded proposal writes exactly that edge, in the contamination
    direction the proposal names (the later criterion sees the earlier work), and the
    approval SURVIVES the natural console ordering — §4.2.1 S5 presents classification
    confirmations and dependency proposals under one step, so the teacher confirms a
    classification between proposing and approving, and the approval must still find
    the proposals it approves. The step's provenance row is MERGED, never replaced:
    a whole-payload upsert would erase the proposals at confirmation time and the
    approval would then refuse the teacher's own act."""
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

    # The natural console order: the teacher confirms a classification FIRST.
    chain.service.confirm_classifications({"CRIT-STEPS": "holistic"})
    proposals = chain.service.propose_dependencies()
    assert proposals, (
        "TC-SETUP-13: a classification confirmation erased the dependency proposals "
        "— the step's provenance row is merged, never replaced (FR-SETUP-10)"
    )

    # Explicit approval: exactly the proposed edge, contamination flowing the way
    # the proposal names — the derivation (CRIT-STEPS) sees the credited definition
    # (CRIT-IMP), not the reverse.
    chain.service.confirm_dependencies(proposals)
    edges = _dependency_edges(tmp_data_dir, chain.package_id, version, ISSUE)
    assert len(edges) == 1, (
        f"TC-SETUP-13: approving one proposal wrote {len(edges)} edge(s) — approval "
        "writes exactly what was approved (FR-SETUP-10)"
    )
    assert (edges[0]["criterion_id"], edges[0]["depends_on"]) == (
        "CRIT-STEPS", "CRIT-IMP"), (
        f"TC-SETUP-13: the edge runs ({edges[0]['depends_on']!r} -> "
        f"{edges[0]['criterion_id']!r}), not (CRIT-IMP -> CRIT-STEPS) — contamination "
        "must flow from the earlier criterion's credited work INTO the later one "
        "(§7.2 Rule 2: a dependency the wrong way round hides evidence)"
    )

    # And the approved edge survives the publish lock: the graph the run reads is
    # the one the teacher approved, not a re-derivation. #53: the staged deterministic
    # criteria need their keys before gate 2 opens.
    chain.service.set_answer_keys({"CRIT-Q4": ["A"], "CRIT-Q5": ["A"], "CRIT-Q6": ["A"]})
    published = chain.service.publish("teacher-1")
    assert chain.catalog.is_locked(published)
    assert len(_dependency_edges(
        tmp_data_dir, chain.package_id, published, ISSUE)) == 1, (
        "TC-SETUP-13: the approved edge did not survive the publish lock — the "
        "published graph is the teacher's approval, stored (FR-SETUP-10)"
    )
