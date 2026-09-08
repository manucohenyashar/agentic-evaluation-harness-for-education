"""`CT-SETUP-08` — dependencies default to zero; a proposed dependency is written
only on explicit teacher approval (`TC-SETUP-C08`).

Case of test plan §6.11.6; issue #56 (TS-63). **Split disposition**, probed:

1. **The zero-default half is green.** A full Stage A publish carries criteria
   but NO dependency edges — the stored `criterion_dependency` rows for the
   published version are exactly the empty set (raw SQLite, stored data alone),
   which every consumer treats as the base case. Stage A itself proposes no
   dependency (the proposal step is #52's — src/aeh/setup.py:690 stages it), so
   the graph starts empty and stays empty unless a teacher approves otherwise.
2. **The approval half is green since #52.** A dependency must be
   *proposed*, rendered in plain language, and written ONLY on explicit teacher
   approval — an auto-approved dependency changes extraction and dispatch order
   for every later run silently. The proposal surface (`propose_dependencies`)
   landed with #52 and the criteria it attaches to come out of #51's read back
   (landed via PR #216); the test went green when the conjunction did, and the
   `writtenahead` marker and the `WRITTEN_AHEAD_BLOCKERS` entry ("#56 C08
   dependencies") are gone.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from aeh.setup import SetupService
from tests.contract.setup._doubles import db_file_for, ingest_document, stage_chain
from tests.support.impl import require_attr

pytestmark = pytest.mark.contract


def _stored_dependency_edges(data_dir, package_id: str,
                             version: str) -> list[sqlite3.Row]:
    """The version's stored dependency edges, read from the package tier file
    WITHOUT the catalog — the stored-data-alone reading a consumer makes."""
    conn = sqlite3.connect(f"file:{db_file_for(data_dir, package_id)}?mode=ro",
                           uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT criterion_id, depends_on FROM criterion_dependency "
            "WHERE package_version_id = ?", (version,)).fetchall()
    finally:
        conn.close()


def test_tc_setup_c08_dependencies_default_to_zero(tmp_data_dir):
    """Publish WITHOUT any approval: the dependency graph is exactly empty —
    non-vacuously, over a package that carries criteria."""
    chain = stage_chain(tmp_data_dir, package_id="pkg-c08")
    chain.doc = ingest_document(chain.store, kind="assessment")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)
    version = chain.service.ensure_version()

    # Criteria exist (added here because #51's read back stages them): the
    # empty-graph assertion below is about EDGES, not an empty package.
    for i, criterion_id in enumerate(("CRIT-A", "CRIT-B")):
        chain.catalog.add_criterion(version, criterion_id,
                                    question_id=f"Q{i + 1}", kind="open",
                                    max_points=4.0,
                                    evidence_type="textual_span")  # FR-SETUP-09
    chain.service.set_answer_keys(
        {"CRIT-A": ["b0"], "CRIT-B": ["b0"]}
        | {"CRIT-Q4": ["A"], "CRIT-Q5": ["A"], "CRIT-Q6": ["A"]})

    published = chain.service.publish("teacher-1")
    assert chain.catalog.is_locked(published)

    # No approval was ever given, so no edge may exist: exactly the empty set.
    edges = _stored_dependency_edges(tmp_data_dir, "pkg-c08", published)
    assert edges == [], (
        f"the published package carries {len(edges)} dependency edge(s) no "
        "teacher approved — dependencies do not default to zero (CT-SETUP-08)"
    )
    # Non-vacuous: the criteria the edges would attach to are real.
    ids = {c["criterion_id"] for c in chain.catalog.criteria(published)}
    assert {"CRIT-A", "CRIT-B"} <= ids


def test_tc_setup_c08_proposal_writes_nothing_without_explicit_approval(
        tmp_data_dir):
    """Green since #51+#52 landed. A dependency is PROPOSED, rendered in plain
    language, and nothing is written by the proposal itself — the graph stays
    empty until a teacher acts.

    What this body pins: the proposal writes NOTHING (the stored graph is empty
    after it), and no proposal arrives pre-approved. The refusal assertion
    PROPER — attempting the unapproved write against #52's vehicle and
    asserting it refuses — is `confirm_dependencies` refusing un-proposed
    pairs and the empty-graph assertion below, since approval is the only
    writer; the green companion test pins the end-to-end half (a publish with
    no approvals carries exactly zero edges)."""
    require_attr(SetupService, "read_back_rubric", issue="#51")
    require_attr(SetupService, "propose_dependencies", issue="#52")

    chain = stage_chain(tmp_data_dir, package_id="pkg-c08d")
    chain.doc = ingest_document(chain.store, kind="assessment")
    rubric = ingest_document(chain.store, kind="rubric", name="rubric.pdf")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)

    # The read back produces the criteria; the dependency proposal attaches to
    # them. The reply shape is this suite's bet (see #54's pending file) — the
    # assertions below do not change when #51's schema lands.
    chain.provider.replies = [json.dumps({"criteria": [
        {"criterion_id": "CRIT-DEF", "question_id": "Q1", "kind": "open",
         "scoring_model": "atomic", "max_points": 4.0,
         "construct": "the response defines impulse"},
        {"criterion_id": "CRIT-USE", "question_id": "Q3", "kind": "open",
         "scoring_model": "atomic", "max_points": 6.0,
         "construct": "the definition is applied to the collision"},
    ]}), json.dumps({"dependencies": [
        {"criterion_id": "CRIT-USE", "depends_on": "CRIT-DEF",
         "reason": "error carried forward: grading the application sees the "
                   "definition credited under the earlier part"},
    ]})]
    chain.service.read_back_rubric(rubric, chain.doc)

    proposals = chain.service.propose_dependencies()
    assert proposals, "no dependency was proposed for a decomposable pair"
    # Plain language: the proposal names both criteria and WHY, in words a
    # teacher reads — not an opaque edge tuple.
    rendered = json.dumps(proposals, default=str)
    for fragment in ("CRIT-DEF", "CRIT-USE"):
        assert fragment in rendered, (
            f"the dependency proposal does not name {fragment} (CT-SETUP-08)"
        )
        # ... and states the dependency's reason, not just its endpoints.
    assert any(getattr(p, "reason", "") or getattr(p, "justification", "")
               for p in proposals), (
        "the dependency proposal carries no stated reason — not plain language "
        "(CT-SETUP-08)"
    )

    # Nothing is written by the proposal: the draft graph is empty after it —
    # the write happens only when the teacher approves (the vehicle #52 pins).
    edges_after_proposal = _stored_dependency_edges(
        tmp_data_dir, "pkg-c08d", proposal.package_version_id)
    assert edges_after_proposal == []

    # And no proposal arrives pre-approved: approval is the teacher's act, so
    # the proposal objects cannot carry it as a default.
    assert all(not getattr(p, "approved", False) for p in proposals), (
        "a dependency proposal arrived pre-approved (CT-SETUP-08)"
    )
