"""`CT-SETUP-03` — setup is resumable; no in-memory session state is required
(`TC-SETUP-C03`).

Case of test plan §6.11.6; issue #56 (TS-63). **Green by design** — the resume
surface landed with #50 and the probe confirmed it across process boundaries.

The clause: a partially-completed package version persists as unpublished and can
be continued in a later session (NFR-SETUP-04); **no in-memory session state is
required** to finish it.

Asserted here, probed:

1. **Across a destroyed process.** A partially-completed version is persisted
   (proposal recorded, inventory unconfirmed), every in-process object is
   dropped, and a FRESH `SetupService` + `PackageCatalog` + `Ingestor` are
   constructed over the same data directory — the constructor of the next
   process. The resume completes: the same stored proposal comes back, the
   confirmation lands, and a SECOND boundary is crossed the same way before
   `publish()` succeeds. Setup finishes with nothing held in memory across
   either boundary.
2. **The negative assertion — the decisive one.** The fresh process reads only
   STORED data: nothing is passed from the old process but the directory path.
   The Python objects of the first process are dropped before the resume starts,
   so any session state the flow required would have to come from the caller —
   and none is supplied. If a step needs something the previous process held,
   the resume fails HERE, which is the assertion the clause names.
3. **The stored proposal is re-rendered, not re-proposed.** The resume path's
   `propose_inventory` returns the stored proposal unchanged (same
   `proposal_id`, same entries, same `attempts`), and the scripted provider's
   call log shows NO new model call — state is the database, and a resuming
   console re-renders what was stored.
4. **The honest remaining count survives the boundary.** `steps()` on the fresh
   service reports the draft, the unconfirmed blocking step, and the same
   remaining count the dying process would have reported — the console picks up
   mid-sequence from the file alone.
"""
from __future__ import annotations

import pytest

from tests.contract.setup._doubles import ingest_document, stage_chain

pytestmark = pytest.mark.contract


def test_tc_setup_c03_resume_across_process_boundaries(tmp_data_dir):
    """Persist a partial version, destroy the process entirely, resume in a
    fresh one — twice — and setup completes."""
    data_dir = tmp_data_dir / "resume"

    # Process 1: propose, do NOT confirm — the partial state that must survive.
    chain = stage_chain(data_dir, package_id="pkg-c03")
    chain.doc = ingest_document(chain.store, kind="assessment")
    proposal = chain.service.propose_inventory(chain.doc)
    stored_id = proposal.proposal_id
    stored_entries = proposal.questions
    stored_attempts = proposal.attempts
    assert proposal.status == "proposed"
    assert len(chain.provider.calls) == 1, "the probe precondition itself changed"

    # The process is destroyed ENTIRELY: every Python object is dropped. The
    # only thing carried across the boundary is the directory path.
    del chain, proposal

    # Process 2: a fresh service over the same directory — stored data only.
    fresh = stage_chain(data_dir, package_id="pkg-c03")
    progress = fresh.service.steps()
    assert progress.package_version_id is not None, (
        "the fresh service cannot see the draft version — the partial state did "
        "not persist (CT-SETUP-03)"
    )
    assert progress.remaining_steps == 1, (
        "the resuming console cannot tell what remains from stored data"
    )

    # The decisive negative: the stored proposal comes back unchanged and NO
    # model call is made — the reconstruction used stored data only. Even the
    # document id is read from the stored row, not carried over.
    stored_doc_id = fresh.service.current_proposal().assessment_doc_id
    resumed = fresh.service.propose_inventory(stored_doc_id)
    assert resumed.proposal_id == stored_id, "the resume re-proposed from scratch"
    assert resumed.questions == stored_entries
    assert resumed.attempts == stored_attempts
    assert len(fresh.provider.calls) == 0, (
        "the resume made a new model call — in-memory session state was required "
        "to get back the stored proposal (CT-SETUP-03)"
    )
    fresh.service.confirm_inventory(resumed.proposal_id)

    # Process 3: the same negative across the second boundary, through publish.
    # #53: the confirmation staged the deterministic criteria — the resuming
    # process keys them (the teacher's act, gate 2) before the publish.
    del fresh, resumed
    chain3 = stage_chain(data_dir, package_id="pkg-c03")
    chain3.service.set_answer_keys({"CRIT-Q4": ["A"], "CRIT-Q5": ["A"],
                                    "CRIT-Q6": ["A"]})
    version = chain3.service.publish("teacher-1")
    assert chain3.catalog.is_locked(version)
    assert chain3.service.steps().remaining_steps == 0


def test_tc_setup_c03_resume_needs_nothing_but_the_directory(tmp_data_dir):
    """The resume supplies NOTHING the previous process held: not the document
    id, not the proposal id, not the version id — the fresh service discovers
    all three from the store, and the document itself is still readable through
    M-INGEST (the ingest store persisted, not the Python object)."""
    data_dir = tmp_data_dir / "resume2"
    chain = stage_chain(data_dir, package_id="pkg-c03b")
    chain.doc = ingest_document(chain.store, kind="assessment")
    chain.service.propose_inventory(chain.doc)
    del chain

    # No doc id, no proposal id, no version id is handed over: the two reads a
    # resuming console makes FIRST work without any of them.
    fresh = stage_chain(data_dir, package_id="pkg-c03b")
    stored = fresh.service.current_proposal()
    assert stored is not None and stored.status == "proposed"
    assert stored.assessment_doc_id, "the stored proposal lost its source document"

    # The stored proposal's entries survive verbatim in the file: the payload is
    # the same questions the dying process saw.
    assert len(stored.questions) == 6, (
        "the stored proposal did not survive the boundary intact (CT-SETUP-03)"
    )

    # And the document is readable through M-INGEST in the fresh process — a
    # re-ingestion would mint a new document id; the STORED one answers.
    markdown = fresh.ingestor.read_document(stored.assessment_doc_id)
    assert "Q1." in markdown
    assert "Circle one" in markdown
