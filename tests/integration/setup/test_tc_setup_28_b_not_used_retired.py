"""Validity T9 (issue #902): `TC-SETUP-28`'s retirement arm — *"The old 'not used' behaviour is
gone"* (CT-SETUP-11 amended, breaking: "Withdraws 'not used'").

**Written ahead, as a finding.** S15 (#885) added the marked-examples step but kept the legacy
`SetupService.store_calibration_papers`, which still records a `calibration_papers` step with
status `stored_not_used` and `"used": false` — the withdrawn CT-SETUP-11 behaviour. It was kept
on purpose: TC-REQ-69 (`tests/contract/requires/test_req_setup.py`) and TC-E2E-01
(`tests/e2e/test_e2e_01_package_setup.py`) call it. Retiring it is implementation work (src and
those two cases), so this arm waits on it: `WRITTEN_AHEAD_BLOCKERS` key
"#902 defect — TC-SETUP-28 legacy store_calibration_papers 'not used'". The probe resolves when
no module under `src/aeh/setup` still writes `stored_not_used`.

The oracle: whatever the setup surface offers for teacher-marked papers, nothing records them as
stored and not used.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]


def test_tc_setup_28_b_no_calibration_paper_is_recorded_as_stored_and_not_used(tmp_data_dir):
    from tests.support.setup_harness import ingest_document, stage_chain

    chain = stage_chain(tmp_data_dir, package_id="pkg-t28b")
    try:
        assessment = ingest_document(chain.store)
        proposal = chain.service.propose_inventory(assessment)
        chain.service.confirm_inventory(proposal.proposal_id)
        paper = ingest_document(chain.store, kind="submission", name="marked.pdf")
        legacy = getattr(chain.service, "store_calibration_papers", None)
        if legacy is not None:
            legacy([paper])
    finally:
        chain.store.close()
    path = next(Path(tmp_data_dir).rglob("pkg-t28b*.sqlite"))
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT step_id, status, payload FROM setup_step_record").fetchall()
    not_used = [(step, status) for step, status, payload in rows
                if status == "stored_not_used"
                or json.loads(payload or "{}").get("used") is False]
    assert not not_used, (
        f"the withdrawn 'stored, not used' behaviour is still recorded: {not_used} "
        "(CT-SETUP-11 amended: calibration papers are stored with bands and graded)")
