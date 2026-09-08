"""`CT-SETUP-14` — the proposal prompt is a version-pinned template, recorded on
the package (`TC-SETUP-C14`).

Case of test plan §6.11.6; issue #56 (TS-63). **Green by design** — the pinned
template landed with #50 (`SETUP_PROMPT_TEMPLATE_V = "setup-inventory-v1"`) and
the probe confirmed the differential on shipped code.

The clause: `SETUP_PROMPT_TEMPLATE_V` is version-pinned and **recorded on the
package**. The consequential assertion: two packages created under different
template versions are **distinguishable from stored data alone** — because a
template change changes every package created afterwards, and a validation record
that cannot separate them is comparing two instruments (RISK-06).

Asserted here, probed:

1. **Pinned.** The module carries the constant, it is a version string (the
   `setup-inventory-vN` form — a pin, not a description), and it is what the
   proposal prompt is actually asked under: the scripted provider's recorded
   prompt fields are the same fields every package under this version is asked
   with (the template is an input, not a per-call improvisation).
2. **Recorded.** The stored proposal row carries `template_version`, and it is
   the constant's value — the record lives in the PACKAGE TIER (survives the
   process), read back here from the raw SQLite file without importing
   `aeh.setup` at all.
3. **The differential.** A second package is created under a DIFFERENT template
   version (the module constant is re-pinned — exactly what a template change
   is: a new version string, never an in-place edit). The two stored rows are
   distinguishable from stored data alone: the raw rows name different versions,
   so a validation record can separate the two instruments. The differential is
   asserted over the STORED BYTES (both packages' tier files read raw), not over
   the module's objects — the same reading a later validation pass would make.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

import aeh.setup as aeh_setup  # not `setup_module`: pytest reads that name as the xunit hook
from aeh.setup import SETUP_PROMPT_TEMPLATE_V
from tests.contract.setup._doubles import db_file_for, ingest_document, stage_chain

pytestmark = pytest.mark.contract


def _stored_proposals(data_dir: str, package_id: str) -> list[tuple[str, str]]:
    """The (version, template_version) proposal rows, read from the package tier
    file WITHOUT importing the module — the stored-data-alone reading."""
    conn = sqlite3.connect(f"file:{db_file_for(data_dir, package_id)}?mode=ro",
                           uri=True)
    try:
        return conn.execute(
            "SELECT package_version_id, template_version FROM setup_proposal"
        ).fetchall()
    finally:
        conn.close()


def test_tc_setup_c14_template_version_is_pinned_and_prompted(tmp_data_dir):
    """The constant is a version pin, and the prompt the model receives is the
    same template every call under this version asks with."""
    assert isinstance(SETUP_PROMPT_TEMPLATE_V, str)
    # The pin form: `setup-inventory-vN` — a version, not a description of the
    # template's content.
    assert SETUP_PROMPT_TEMPLATE_V.startswith("setup-inventory-v"), (
        f"{SETUP_PROMPT_TEMPLATE_V!r} is not a version pin (CT-SETUP-14)"
    )

    chain = stage_chain(tmp_data_dir / "pin", package_id="pkg-c14")
    chain.doc = ingest_document(chain.store, kind="assessment")
    proposal = chain.service.propose_inventory(chain.doc)
    assert proposal.template_version == SETUP_PROMPT_TEMPLATE_V

    # The prompt fields are the template's rendered shape — identical across two
    # proposals under the same version (the template is an input, not improvised
    # per call).
    first_fields = chain.provider.calls[0]
    chain2 = stage_chain(tmp_data_dir / "pin2", package_id="pkg-c14b")
    chain2.doc = ingest_document(chain2.store, kind="assessment")
    chain2.service.propose_inventory(chain2.doc)
    second_fields = chain2.provider.calls[0]
    assert first_fields.keys() == second_fields.keys()
    assert first_fields == second_fields, (
        "two proposals under the same template version received different "
        "prompt fields — the template is not pinned (CT-SETUP-14)"
    )


def test_tc_setup_c14_template_version_is_recorded_on_the_package(tmp_data_dir):
    """The proposal row stores `template_version` in the package tier — read
    back from the raw file, no module import, so the record survives the
    process and belongs to the package, not the session."""
    data_dir = tmp_data_dir / "recorded"
    chain = stage_chain(data_dir, package_id="pkg-c14rec")
    chain.doc = ingest_document(chain.store, kind="assessment")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)

    rows = _stored_proposals(data_dir, "pkg-c14rec")
    assert len(rows) == 1
    version_id, template_version = rows[0]
    assert version_id == proposal.package_version_id
    assert template_version == SETUP_PROMPT_TEMPLATE_V, (
        "the stored proposal row does not record the template version that "
        "produced it (CT-SETUP-14)"
    )


def test_tc_setup_c14_packages_under_different_versions_distinguishable(tmp_data_dir):
    """Two packages under different template versions are distinguishable from
    STORED DATA ALONE: the raw rows carry different versions, read without the
    module — a validation record can separate the two instruments (RISK-06)."""
    shared = tmp_data_dir / "differential"
    shared.mkdir()

    # Package 1 under the shipped pin.
    chain1 = stage_chain(shared, package_id="pkg-c14-v1")
    chain1.doc = ingest_document(chain1.store, kind="assessment")
    p1 = chain1.service.propose_inventory(chain1.doc)
    chain1.service.confirm_inventory(p1.proposal_id)
    # #53: the staged deterministic criteria need their keys before gate 2 opens.
    chain1.service.set_answer_keys({"CRIT-Q4": ["A"], "CRIT-Q5": ["A"],
                                    "CRIT-Q6": ["A"]})
    chain1.service.publish("teacher-1")

    # Package 2 under a NEW version string — what a template change is: a new
    # pin, never an in-place edit of the old one's meaning.
    original = aeh_setup.SETUP_PROMPT_TEMPLATE_V
    aeh_setup.SETUP_PROMPT_TEMPLATE_V = "setup-inventory-v2"
    try:
        chain2 = stage_chain(shared, package_id="pkg-c14-v2")
        chain2.doc = ingest_document(chain2.store, kind="assessment")
        p2 = chain2.service.propose_inventory(chain2.doc)
        assert p2.template_version == "setup-inventory-v2"
    finally:
        aeh_setup.SETUP_PROMPT_TEMPLATE_V = original

    # The differential, over STORED DATA ALONE: both tier files read raw.
    rows_v1 = _stored_proposals(shared, "pkg-c14-v1")
    rows_v2 = _stored_proposals(shared, "pkg-c14-v2")
    assert len(rows_v1) == 1 and len(rows_v2) == 1
    versions = {rows_v1[0][1], rows_v2[0][1]}
    assert versions == {original, "setup-inventory-v2"}, (
        "two packages created under different template versions are not "
        "distinguishable from stored data alone — a validation record cannot "
        "separate the two instruments (CT-SETUP-14, RISK-06)"
    )
    # The rows are stored per package version: the pairing version→template is
    # in the row itself, so the separation needs no session knowledge.
    assert rows_v1[0][0] != rows_v2[0][0]
    assert json.dumps(rows_v1) != json.dumps(rows_v2)
