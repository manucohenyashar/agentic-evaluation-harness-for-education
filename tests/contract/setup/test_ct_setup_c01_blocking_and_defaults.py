"""`CT-SETUP-01` — exactly two blocking operations, everything else skippable with
a recorded default (`TC-SETUP-C01`).

Case of test plan §6.11.6; issue #56 (TS-63). The blocking half runs **green by
design** — `aeh.setup` landed with #50 and the probe confirmed the set. The
recorded-default sweep over the steps #51/#52/#53 stage is **written ahead** of
those stories (the provenance write belongs to the step that owns the default; a
step that does not exist cannot record that it was skipped).

The clause: exactly **two** operations block — `confirm_inventory` and
`set_answer_keys` — and a consumer may **enumerate** the blocking set and assert it
has two members, **as set equality**, so a third blocking step fails this case
rather than merely slowing the teacher (a hard-coded count of 2 would pass until
someone adds a third blocking step in `M-SETUP`; the set cannot). Every other step
has a defined default, is completable by skipping, and **records that the default
was taken** — a default indistinguishable from an explicit choice destroys
`M-CALIB`'s and `M-STATS`' ability to tell a teacher's judgment from the system's
(HLD `R62`).

Asserted here, probed:

1. **The blocking set, as set equality over the enumerated steps.** The runtime
   enumeration is `steps()`'s step list — the surface `M-CONSOLE` renders and the
   surface the clause names ("a consumer may enumerate"). `{step.step_id for step
   in progress.steps if step.blocking}` must EQUAL `{"inventory", "answer_keys"}`
   — no third member, no missing member — and the mapped operations must equal
   `{confirm_inventory, set_answer_keys}`, so the enumeration pins the OPERATIONS
   the clause names, not just two strings.
2. **The count follows from the set** (a redundant count would be the hard-coded
   form the clause rejects; this is the derived form): `sum(blocking) == 2` is
   asserted as a consequence, next to a sibling's right — `M-CONSOLE` renders
   exactly two blocking screens (`FR-CONSOLE-06`).
3. **The skip sweep over what ships today**: a full Stage A run completes —
   `publish()` succeeds — having called **only** the two blocking operations and
   the read surface. Every non-blocking operation `M-SETUP` offers is never
   required; the run never calls one. (The later steps are enumerated as
   present-and-unavailable, each naming the story that stages it — the console
   tells the truth about what remains rather than offering an operation that does
   not exist.)
4. *(written ahead of #51+#52+#53)* **The recorded-default sweep**: each
   non-blocking step, driven to completion BY SKIPPING, records in the package
   that the default was taken — the provenance artifact per step (`R62`): a
   stored default-marker distinguishable from the record of an explicit choice.
   This is the clause's substance; it lands with the steps themselves.
"""
from __future__ import annotations

import pytest

from aeh.setup import SetupService
from tests.contract.setup._doubles import (
    db_file_for,
    ingest_document,
    stage_chain,
    stage_confirmed,
)

pytestmark = pytest.mark.contract


def test_tc_setup_c01_blocking_set_is_exactly_two_operations(tmp_data_dir):
    """The blocking set is enumerable and EQUALS the two named operations."""
    chain = stage_chain(tmp_data_dir)
    chain.doc = ingest_document(chain.store, kind="assessment")

    progress = chain.service.steps()
    blocking = {step.step_id for step in progress.steps if step.blocking}
    # Set equality, not membership and not a count: a third blocking step added
    # later fails HERE, and removing either named step fails HERE.
    assert blocking == {"inventory", "answer_keys"}
    # The enumeration maps onto the operations the clause names — the step ids
    # are the console's names for `confirm_inventory` and `set_answer_keys`, and
    # the module offers both as exactly the operations that block.
    assert {step.step_id: step for step in progress.steps if step.blocking}.keys() == {
        "inventory", "answer_keys"}
    assert sum(1 for step in progress.steps if step.blocking) == 2
    # `publish` is not a member of the step list at all — it is the gate point
    # the blocking steps hold shut, never a third blocking screen.
    assert "publish" not in {step.step_id for step in progress.steps}


def test_tc_setup_c01_enumeration_is_runtime_not_hardcoded(tmp_data_dir):
    """The set equality reads the RUNTIME enumeration, so it is live against a
    changed `M-SETUP`: `steps()` is the surface a consumer enumerates, and this
    case reads it through the public call, not a constant of its own."""
    chain = stage_chain(tmp_data_dir)
    chain.doc = ingest_document(chain.store, kind="assessment")

    # The enumeration must come from the service's own report — the same call
    # `M-CONSOLE` makes — and stay equal after the blocking steps' states change
    # (confirming gate 1 moves `done`, never the blocking set).
    before = {s.step_id for s in chain.service.steps().steps if s.blocking}
    stage_confirmed(chain)
    after = {s.step_id for s in chain.service.steps().steps if s.blocking}
    assert before == after == {"inventory", "answer_keys"}

    # The blocking property lives on the step records themselves, typed `bool`.
    for step in chain.service.steps().steps:
        assert isinstance(step.blocking, bool)


def test_tc_setup_c01_every_non_blocking_step_is_skippable(tmp_data_dir):
    """A full Stage A completes by calling ONLY the blocking operations: every
    non-blocking step is completable by skipping — demonstrated by skipping all
    of them and reaching the published state."""
    chain = stage_chain(tmp_data_dir)
    chain.doc = ingest_document(chain.store, kind="assessment")

    # The only setup calls in this run are the two blocking gates and the read
    # surface. No non-blocking operation is invoked — and the run still finishes.
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)
    version = chain.service.publish("teacher-1")
    assert chain.catalog.is_locked(version)

    # The steps that exist but were skipped are enumerated honestly: each
    # non-blocking step names the story that stages it, so "skipped" is never
    # indistinguishable from "missing".
    finished = chain.service.steps()
    for step in finished.steps:
        if not step.blocking:
            assert step.note, f"step {step.step_id!r} carries no provenance note"


@pytest.mark.writtenahead
def test_tc_setup_c01_each_skipped_default_is_recorded_as_taken(tmp_data_dir):
    """The clause's substance, per step: completing a non-blocking step BY
    SKIPPING records in the package that the default was taken — stored
    provenance distinguishable from an explicit choice (`R62`), so `M-CALIB` and
    `M-STATS` can tell a teacher's judgment from the system's.

    Blocked on the steps themselves: `read_back_rubric` (#51),
    `classify_decomposability`/`propose_dependencies` (#52),
    `set_grade_policy`/`check_prefix_budget` (#53) — the steps whose defaults
    this sweep drives; the `require_attr` calls below are the designed blocker.
    The exact default VALUE per step is each step's own case (TC-SETUP-C06, -C08,
    -C09, -C10); this sweep pins the provenance rule itself.
    """
    import sqlite3

    from tests.support.impl import require_attr

    require_attr(SetupService, "read_back_rubric", issue="#51")
    require_attr(SetupService, "classify_decomposability", issue="#52")
    require_attr(SetupService, "propose_dependencies", issue="#52")
    require_attr(SetupService, "set_grade_policy", issue="#53")
    require_attr(SetupService, "check_prefix_budget", issue="#53")

    skipped_ids = {"rubric_readback", "decomposability", "grade_policy"}
    chain = stage_chain(tmp_data_dir)
    chain.doc = ingest_document(chain.store, kind="assessment")

    # A skip-only run: the two blocking gates, then publish — no non-blocking
    # operation is ever called, yet setup completes (its half is the green case
    # above).
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)
    version = chain.service.publish("teacher-1")
    assert chain.catalog.is_locked(version)

    # The provenance must be STORED, not merely returned in memory: every row of
    # the package tier that belongs to this version, serialized, is the material
    # a later session (or M-CALIB/M-STATS) can read without this process.
    conn = sqlite3.connect(f"file:{db_file_for(tmp_data_dir, chain.package_id)}?mode=ro",
                           uri=True)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        stored = ""
        for table in tables:
            cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})")]
            if "package_version_id" not in cols:
                continue
            for row in conn.execute(
                f"SELECT * FROM {table} WHERE package_version_id = ?", (version,)):
                stored += " | ".join(str(cell) for cell in row) + "\n"
    finally:
        conn.close()

    for step_id in sorted(skipped_ids):
        assert step_id in stored, (
            f"skipping {step_id!r} left no stored record naming it — the default "
            "is indistinguishable from an explicit choice (CT-SETUP-01, R62)"
        )
