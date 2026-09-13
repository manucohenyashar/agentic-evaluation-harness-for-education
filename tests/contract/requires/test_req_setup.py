"""`TS-79` (issue #152) — `Requires` pairwise integration into **`M-SETUP`**: the consumers'
assumptions about setup's step enumeration, its recorded defaults and its calibration-paper
intake, checked against the real `SetupService` over a real store (rung 3).

Test plan §6.13, grouped one suite per provider module (§4.10).

| Case | Consumer | Assumption checked here |
|---|---|---|
| TC-REQ-69 | `M-CALIB` | calibration papers are stored with the package, and setup never reads them |
| TC-REQ-88 | `M-CONSOLE` | the blocking set is setup's runtime enumeration, skipped defaults are stored, setup survives a console kill, and the confirmation cap lives in setup |

Markers: `contract` and `integration` (§4.7).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from aeh.store import open_store
from tests.contract.setup._doubles import ingest_document, stage_chain

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _skip_only_publish(chain):
    """The two blocking gates, then publish, with no non-blocking step ever called."""
    chain.doc = ingest_document(chain.store, kind="assessment")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)
    chain.service.set_answer_keys({"CRIT-Q4": ["A"], "CRIT-Q5": ["A"], "CRIT-Q6": ["A"]})
    return chain.service.publish("teacher-1")


def test_tc_req_69_calibration_papers_are_stored_with_the_package_and_unread_by_setup(
    tmp_data_dir, monkeypatch
):
    """`TC-REQ-69` (`M-CALIB` → `M-SETUP`, CT-SETUP-11/15): the teacher's marked calibration
    papers are handed to setup. They are recorded against the package version with `used: False`
    and every document ID named, and the documents stay retrievable for M-CALIB. Setup reads
    none of them while storing them: no read of any paper's Markdown or bytes."""
    import json

    from aeh.ingest import Ingestor

    chain = stage_chain(tmp_data_dir)
    try:
        chain.doc = ingest_document(chain.store, kind="assessment")
        proposal = chain.service.propose_inventory(chain.doc)
        chain.service.confirm_inventory(proposal.proposal_id)
        papers = [ingest_document(chain.store, kind="submission", name=f"paper-{i}.pdf")
                  for i in range(3)]
        reads: list[str] = []
        real_read = Ingestor.read_document

        def spy(self, document_id):
            reads.append(document_id)
            return real_read(self, document_id)

        monkeypatch.setattr(Ingestor, "read_document", spy)
        chain.service.store_calibration_papers(papers)
        stored_reads = list(reads)
        chain.ingestor.read_document(chain.doc)  # control: the spy records a read
        monkeypatch.undo()
        version = chain.service.steps().package_version_id
        record = chain.catalog.step_record(version, "calibration_papers")
        retrievable = [chain.ingestor.read_document(p) for p in papers]
    finally:
        chain.store.close()
    assert record is not None, "the calibration papers left no record on the package version"
    payload = json.loads(record["payload"]) if isinstance(record, dict) else json.loads(record[3])
    assert sorted(payload["document_ids"]) == sorted(papers) and payload["used"] is False, payload
    assert reads[-1] == chain.doc, "control: the read spy did not record a read"
    assert not (set(stored_reads) & set(papers)), (
        f"setup read calibration papers while storing them: {stored_reads}")
    assert all(retrievable), "a stored calibration paper is not retrievable for M-CALIB"


def test_tc_req_88_the_blocking_set_is_setups_and_setup_holds_its_own_state(
    tmp_data_dir, monkeypatch
):
    """`TC-REQ-88` (`M-CONSOLE` → `M-SETUP`, CT-SETUP-01/03/13, CT-CONSOLE-07):

    1. **Enumerable at runtime, two members.** `SetupService.steps()` reports exactly two
       blocking steps.
    2. **The console's count is asserted against setup.** The console's blocking screens equal
       setup's blocking steps in number. With M-SETUP's enumeration made to report a third
       blocking step, the console's count must follow. A console that hard-codes two passes the
       first comparison and fails this one.
    3. **Skipped steps record their default.** After a skip-only publish, each skipped step has a
       stored record on the version, so the console can render the cost of skipping from stored
       data.
    4. **Setup survives a console kill.** Mid-setup (inventory confirmed, keys not yet set), a
       fresh `SetupService` over the reopened store, with no in-memory session, reports the same
       step state.
    5. **The confirmation cap is setup's.** M-SETUP owns `SETUP_MAX_CONFIRMATIONS` and loads it in
       a process that never imports the console. That the cap is applied is `TC-SETUP-10`'s case."""
    import dataclasses

    import aeh.setup as setup
    from aeh.console import build_console
    from tests.contract.setup._doubles import stage_chain as fresh_chain

    problems = []

    chain = stage_chain(tmp_data_dir / "live")
    try:
        chain.doc = ingest_document(chain.store, kind="assessment")
        progress = chain.service.steps()
        blocking = [s.step_id for s in progress.steps if s.blocking]
        console_count = len(build_console(store=chain.store).blocking_screens())
        if console_count != len(blocking):
            problems.append(f"console blocks on {console_count} screens, setup on {len(blocking)} steps")

        real_steps = setup.SetupService.steps

        def with_third_blocking(self):
            report = real_steps(self)
            extra = dataclasses.replace(report.steps[0], step_id="third_blocking_step",
                                        name="a third blocking step", blocking=True)
            return dataclasses.replace(report, steps=tuple(report.steps) + (extra,))

        monkeypatch.setattr(setup.SetupService, "steps", with_third_blocking)
        now_blocking = sum(1 for s in chain.service.steps().steps if s.blocking)
        console_after = len(build_console(store=chain.store).blocking_screens())
        monkeypatch.undo()
        if now_blocking != 3:
            problems.append(f"fixture: the patched enumeration reports {now_blocking} blocking steps")
        if console_after != now_blocking:
            problems.append(
                f"with setup reporting {now_blocking} blocking steps the console still blocks on "
                f"{console_after}: its count is hard-coded, not derived from M-SETUP (CT-CONSOLE-07). "
                f"[When written: console.py's BLOCKING_SCREENS = frozenset({{'S3', 'S4'}}), with no "
                f"reference to setup's enumeration.]")

        proposal = chain.service.propose_inventory(chain.doc)
        chain.service.confirm_inventory(proposal.proposal_id)
        mid_setup = [(s.step_id, s.done, s.available) for s in chain.service.steps().steps]
    finally:
        chain.store.close()
    reopened = fresh_chain(tmp_data_dir / "live")
    try:
        after_kill = [(s.step_id, s.done, s.available) for s in reopened.service.steps().steps]
    finally:
        reopened.store.close()
    if sorted(blocking) != ["answer_keys", "inventory"]:
        problems.append(f"setup's blocking set is {blocking}, not the two named steps")
    if not any(done for _id, done, _a in mid_setup) or after_kill != mid_setup:
        problems.append(f"a fresh SetupService mid-setup reports {after_kill}, not {mid_setup}")

    publish_dir = tmp_data_dir / "published"
    chain = stage_chain(publish_dir)
    try:
        version = _skip_only_publish(chain)
        stored = {step: chain.catalog.step_record(version, step)
                  for step in ("rubric_readback", "decomposability", "grade_policy")}
    finally:
        chain.store.close()
    missing = [step for step, record in stored.items() if record is None]
    if missing:
        problems.append(f"skipped steps left no stored default: {missing}")

    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO_ROOT / "src"), str(REPO_ROOT)]))
    probe = subprocess.run([sys.executable, "-c",
                            "import sys, aeh.setup as s; "
                            "print(int(s.SETUP_MAX_CONFIRMATIONS), 'aeh.console' in sys.modules)"],
                           capture_output=True, text=True, env=env, timeout=60)
    words = probe.stdout.split()
    if probe.returncode != 0 or len(words) != 2 or not words[0].isdigit() or words[1] != "False":
        problems.append(f"the confirmation cap is not setup's alone: {probe.stdout!r} {probe.stderr[-300:]!r}")
    assert not problems, "\n".join(problems)
