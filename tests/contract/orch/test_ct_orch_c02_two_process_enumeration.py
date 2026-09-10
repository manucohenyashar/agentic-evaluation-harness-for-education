"""`TC-ORCH-C02` — the two-process whole-run enumeration (§6.11.7): the same store,
the same run, two dispatcher processes — the full `work_id` set is byte-identical
(`CT-ORCH-02`, `NFR-ORCH-05`).

Relationship to the shipped unit case, disclosed: `tests/unit/orch/test_work_id.py`'s
step 3 recomputes a SINGLE id in fresh interpreters, and its step 4 enumerates a whole
run twice — but in ONE process, against an untouched store. The limb C02 exists for is
the process boundary itself: a whole run enumerated by one process (store opened,
enumeration committed, store closed), then re-enumerated by a completely separate
interpreter that builds its own hash tables, dict orders and `PYTHONHASHSEED` draws from
nothing, opens the store files cold and walks the same cohort roster and package catalog.
That is the resume/dedup geometry of a real dispatch fleet — two worker processes racing
the same run — and it is where per-process nondeterminism (a set-walk feeding the hash,
a clock, a counter) would actually surface.

The child is `tests/contract/orch/_enumeration_worker.py`: shipped modules only, the full
eight-module migration chain imported before its open, no test imports at all. Two child
runs under deliberately different `PYTHONHASHSEED` values bracket the in-process
enumeration; all three id sets must be byte-identical, and the store must end with
exactly one ledger row per id — three enumerations, no duplicates (`INSERT OR IGNORE`'s
contract, `FR-ORCH-03`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from aeh.orch import Orchestrator
from aeh.store import open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.contract]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKER = REPO_ROOT / "tests" / "contract" / "orch" / "_enumeration_worker.py"

_RUN_ID = "run-c02-two-process"
_SUBMISSIONS = ("SYN-001", "SYN-002")
_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},
    {"criterion_id": "C2", "kind": "mcq"},
    {"criterion_id": "C3", "kind": "open", "scoring_model": "atomic"},
)


def _run_worker(data_dir: Path, pythonhashseed: str) -> dict:
    """One child process: cold open, enumerate the pinned run, report as JSON.

    `PYTHONHASHSEED` is pinned per child so the two children draw different hash-table
    orders; `HARNESS_ORCH_RANDOM_ARM_RATE=0` is re-set explicitly (the suite's autouse
    pin propagates through `os.environ`, and this makes the child's env honest about
    what it relies on — the run id is pinned precisely so the arm's run-seeded draw
    would ALSO be deterministic if a later case raises it).
    """
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = pythonhashseed
    env["HARNESS_ORCH_RANDOM_ARM_RATE"] = "0"
    env["PYTHONPATH"] = (
        str(REPO_ROOT / "src")
        + os.pathsep
        + str(REPO_ROOT)
        + os.pathsep
        + env.get("PYTHONPATH", "")
    )
    completed = subprocess.run(
        [sys.executable, str(WORKER), str(data_dir), _RUN_ID],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=120,
    )
    assert completed.returncode == 0, (
        f"the child process failed to enumerate run {_RUN_ID} "
        f"(PYTHONHASHSEED={pythonhashseed!r}): {completed.stderr}"
    )
    return json.loads(completed.stdout)


def test_tc_orch_c02_two_processes_enumerate_the_same_run_byte_identically(
    tmp_data_dir,
):
    """Three enumerations — this process, and two cold child processes under different
    hash seeds — over one pinned run id. Every comparison is a sorted byte-list; the
    final ledger holds exactly one row per id."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _ = seed_run(
            store,
            submissions=_SUBMISSIONS,
            criteria=_CRITERIA,
            run_id=_RUN_ID,
        )
        assert run_id == _RUN_ID, "seed_run must honour the pinned run id"
        in_process = sorted(orchestrator.enumerate_units(run_id).work_ids)
    finally:
        store.close()
    assert in_process, "the run enumerated nothing — nothing to compare across processes"

    child_a = _run_worker(tmp_data_dir, "0")
    child_b = _run_worker(tmp_data_dir, "20260908")

    for label, child in (("PYTHONHASHSEED=0", child_a), ("seed 20260908", child_b)):
        assert child["work_ids"] == in_process, (
            f"the child process ({label}) enumerated a different work_id set for run "
            f"{_RUN_ID} than this process did — the enumeration reaches something "
            "process-local (hash order, a clock, a counter) and NFR-ORCH-05's "
            "cross-process byte-identity does not hold at whole-run scale"
        )
        assert child["units_inserted"] == 0, (
            f"the child ({label}) inserted {child['units_inserted']} rows re-enumerating "
            "a fully-enumerated run — the pass must compute, ignore, and report no-op "
            "(INSERT OR IGNORE keyed on work_id, FR-ORCH-03)"
        )
        assert child["units_already_present"] == len(in_process)

    # The ledger's side of the contract: three enumerations, one row per identity.
    store = open_store(tmp_data_dir)
    try:
        rows = store.cohort(ORCH_COHORT_ID).query(
            "SELECT work_id FROM work_unit WHERE run_id = :r", r=_RUN_ID
        )
    finally:
        store.close()
    assert sorted(r["work_id"] for r in rows) == in_process, (
        "the ledger's row identities diverge from the enumerated set — a duplicate row "
        "from the two-process overlap would let the same unit's result land twice"
    )
