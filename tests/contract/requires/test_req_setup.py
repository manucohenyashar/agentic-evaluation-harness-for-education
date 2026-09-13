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

import inspect
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
        monkeypatch.undo()
        version = chain.service.steps().package_version_id
        record = chain.catalog.step_record(version, "calibration_papers")
        retrievable = [chain.ingestor.read_document(p) for p in papers]
    finally:
        chain.store.close()
    assert record is not None, "the calibration papers left no record on the package version"
    payload = json.loads(record["payload"]) if isinstance(record, dict) else json.loads(record[3])
    assert sorted(payload["document_ids"]) == sorted(papers) and payload["used"] is False, payload
    assert not (set(reads) & set(papers)), f"setup read calibration papers while storing them: {reads}"
    assert all(retrievable), "a stored calibration paper is not retrievable for M-CALIB"


def test_tc_req_88_the_blocking_set_is_setups_and_setup_holds_its_own_state(tmp_data_dir):
    """`TC-REQ-88` (`M-CONSOLE` → `M-SETUP`, CT-SETUP-01/03/13, CT-CONSOLE-07):

    1. **Enumerable at runtime, two members.** `SetupService.steps()` reports exactly two
       blocking steps.
    2. **The console's count comes from setup.** CT-CONSOLE-07's blocking count must be derived
       from that enumeration. A console that hard-codes it passes until a third blocking step is
       added to M-SETUP. M-CONSOLE's source must therefore consult setup's steps.
    3. **Skipped steps record their default.** After a skip-only publish, each skipped step has a
       stored record on the version, so the console can render the cost of skipping from stored
       data.
    4. **Setup survives a console kill.** A fresh `SetupService` over the reopened store, with no
       in-memory session, reports the same step state.
    5. **The confirmation cap is setup's.** M-SETUP enforces `SETUP_MAX_CONFIRMATIONS` in a
       process that never imports the console."""
    import aeh.console as console
    from tests.contract.setup._doubles import stage_chain as fresh_chain

    chain = stage_chain(tmp_data_dir)
    try:
        chain.doc = ingest_document(chain.store, kind="assessment")
        blocking = [s.step_id for s in chain.service.steps().steps if s.blocking]
        chain.store.close()
    except Exception:
        chain.store.close()
        raise

    publish_dir = tmp_data_dir / "published"
    chain = stage_chain(publish_dir)
    try:
        version = _skip_only_publish(chain)
        stored = {step: chain.catalog.step_record(version, step)
                  for step in ("rubric_readback", "decomposability", "grade_policy")}
        state_before = [(s.step_id, s.done) for s in chain.service.steps().steps]
    finally:
        chain.store.close()
    reopened = fresh_chain(publish_dir)
    try:
        state_after = [(s.step_id, s.done) for s in reopened.service.steps().steps]
    finally:
        reopened.store.close()

    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO_ROOT / "src"), str(REPO_ROOT)]))
    probe = subprocess.run([sys.executable, "-c",
                            "import sys, aeh.setup as s; "
                            "print(s.SETUP_MAX_CONFIRMATIONS, 'aeh.console' in sys.modules)"],
                           capture_output=True, text=True, env=env, timeout=60)

    import ast

    tree = ast.parse(inspect.getsource(console))
    derives = any(
        (isinstance(node, ast.ImportFrom) and (node.module or "").startswith("aeh.setup"))
        or (isinstance(node, ast.Import) and any(a.name.startswith("aeh.setup") for a in node.names))
        for node in ast.walk(tree))

    problems = []
    if sorted(blocking) != ["answer_keys", "inventory"]:
        problems.append(f"setup's blocking set is {blocking}, not the two named steps")
    missing = [step for step, record in stored.items() if record is None]
    if missing:
        problems.append(f"skipped steps left no stored default: {missing}")
    if state_after != state_before:
        problems.append("a fresh SetupService over the reopened store reports a different state")
    if probe.returncode != 0 or probe.stdout.split() != [str(int(probe.stdout.split()[0])), "False"]:
        problems.append(f"the confirmation cap is not setup's alone: {probe.stdout!r} {probe.stderr[-300:]!r}")
    if not derives:
        problems.append(
            f"M-CONSOLE's blocking count is not derived from M-SETUP's enumeration: blocking_screens() "
            f"returns {console.build_console().blocking_screens()} from a constant, so a third "
            f"blocking step added to setup would not reach it (CT-CONSOLE-07). [When written: "
            f"console.py defines BLOCKING_SCREENS = frozenset({{'S3', 'S4'}}) and never imports "
            f"aeh.setup.]")
    assert not problems, "\n".join(problems)
