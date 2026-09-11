"""`TC-GRADE-C11` — `compute_all` is idempotent, and every revision records its versions (§6.11.14).

`CT-GRADE-11` (behaviour): "Assert `compute_all` is **idempotent**: recomputation
with unchanged inputs produces **no new revision** — asserted as a revision count,
since a no-op that still writes a revision would fill the audit trail with noise
and make real amendments unfindable. Then assert a key correction or policy
version change **recomputes affected grades** and **records which policy and key
version produced each revision**, verified by resolving an older revision to its
older versions."

The limbs, in the row's order:

- **the revision count** (rung 3, green): two unchanged passes, one grade row —
  the ledger records content changes, not pass executions; a no-op that minted a
  revision would fill the audit trail with noise (NFR-GRADE-05).
- **the amended-replay half** (rung 3, green): after an amendment, a recompute
  pass replays the recorded map before comparing content — an unchanged re-run of
  an amended submission reproduces the AMENDED content and writes nothing, rather
  than minting a revert (FR-GRADE-13's exactness reaches amended revisions).
- **the version resolution per revision** (rung 3, green): a policy change
  recomputes the affected grades as revision n+1, and each revision resolves to
  the policy and key version that produced it — revision 1 still resolves to the
  OLD policy version, revision 2 to the new one.

Isolation: rung 3 — real store, real package, real service. The socket guard is
autouse; `criterion_score` rows are the vocabulary's disclosed `M-AGG` stand-in.
"""

from __future__ import annotations

import pytest

from aeh.pkg import GradePolicy
from aeh.store import open_store
from tests.contract.grade._drive import (
    complete_run,
    current_grades,
    grade_revision,
    graded_run,
    set_policy,
)
from tests.support.impl import GRADE_MODULE, require

pytestmark = [pytest.mark.contract]

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
)

_ROWS = (
    ("S-ONE", "C1", "B2", 7.0, "auto"),
    ("S-ONE", "C2", "B2", 5.0, "auto"),
)


def test_tc_grade_c11_recomputation_with_unchanged_inputs_writes_no_revision(
    tmp_data_dir,
):
    """`TC-GRADE-C11` (`CT-GRADE-11`, rung 3) — `compute_all` is idempotent: a
    second pass over unchanged inputs writes no new revision, asserted as a
    revision count. The settlement path changes no revision either: the completed
    run settles the grade's STATE in place, never minting a row."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=("S-ONE",), criteria=_CRITERIA, rows=_ROWS
        )
        first_count = len(world.cohort.query(
            "SELECT * FROM submission_grade WHERE run_id = :r AND submission_id = :s",
            r=world.run_id, s="S-ONE",
        ))
        assert first_count == 1, "fixture bug: the first pass mints one grade row"

        # A second pass over unchanged inputs: no new revision.
        world.service.compute_all(world.run_id)
        assert len(world.cohort.query(
            "SELECT * FROM submission_grade WHERE run_id = :r AND submission_id = :s",
            r=world.run_id, s="S-ONE",
        )) == first_count, (
            "a recomputation with unchanged inputs wrote a new revision — a no-op "
            "revision fills the audit trail with noise and makes real amendments "
            "unfindable (CT-GRADE-11, NFR-GRADE-05)"
        )
        # And the run completing changes the state in place — settlement, not a
        # new computation.
        complete_run(world.cohort, world.run_id)
        world.service.compute_all(world.run_id)
        (settled,) = current_grades(world.cohort, world.run_id)
        assert settled["state"] == "final" and settled["revision"] == 1, (
            f"run completion minted a revision ({settled['revision']!r}) — the "
            "completion path settles the current revision in place (FR-GRADE-10: "
            "finalization is not a recomputation)"
        )
    finally:
        store.close()


def test_tc_grade_c11_amended_content_survives_a_recompute(tmp_data_dir):
    """`CT-GRADE-11`'s amendment leg (`CT-GRADE-13`'s replay clause, rung 3) — a
    recomputation replays the recorded overrides before comparing content: an
    unchanged re-run of an amended submission reproduces the AMENDED content and
    writes nothing, instead of minting a revert."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=("S-ONE",), criteria=_CRITERIA, rows=_ROWS,
            compute=False,
        )
        world.service.compute_all(world.run_id)
        revision_two = world.service.amend(
            world.run_id, "S-ONE", {"C1": 10.0}, actor="teacher-1", reason="band move",
        )
        assert revision_two.revision == 2, "fixture bug: the amendment mints revision 2"

        # The unchanged re-run: the recorded override replays, no new revision.
        world.service.compute_all(world.run_id)
        rows = world.cohort.query(
            "SELECT revision, total FROM submission_grade "
            "WHERE run_id = :r AND submission_id = :s",
            r=world.run_id, s="S-ONE",
        )
        assert [(r["revision"], float(r["total"])) for r in rows] == [(1, 12.0), (2, 15.0)], (
            f"the recompute did not reproduce the amended grade ({rows!r}) — the "
            "recorded override replay keeps an amended grade from being reverted "
            "(CT-GRADE-11's recompute clause with FR-GRADE-13)"
        )
    finally:
        store.close()


def test_tc_grade_c11_a_policy_change_recomputes_and_records_versions(tmp_data_dir):
    """`CT-GRADE-11`'s versioning limbs (rung 3): a policy change recomputes the
    affected grades as revision n+1, and each revision resolves to the policy and
    key versions that produced it — the older revision still resolves to the OLDER
    versions."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=("S-ONE", "S-TWO"), criteria=_CRITERIA, rows=(
                ("S-ONE", "C1", "B2", 7.0, "auto"),
                ("S-ONE", "C2", "B2", 5.0, "auto"),
                ("S-TWO", "C1", "B2", 7.0, "auto"),
                ("S-TWO", "C2", "B2", 5.0, "auto"),
            ),
            compute=False,
        )
        original = GradePolicy()
        set_policy(store, world.version, original)
        world.service.compute_all(world.run_id)
        first = {
            row["submission_id"]: row for row in current_grades(world.cohort, world.run_id)
        }
        assert first["S-ONE"]["policy_version"] and first["S-TWO"]["policy_version"], (
            "fixture bug: the grade rows carry no policy version"
        )
        assert (
            first["S-ONE"]["answer_key_ref"] and first["S-TWO"]["answer_key_ref"]
        ), (
            "fixture bug: the grade rows carry no answer-key ref — the clause "
            "records which policy AND KEY version produced each revision"
        )

        # The policy changes: the affected grades recompute as revision 2, each
        # recording the policy version that produced it.
        changed = GradePolicy(weights=(("C1", 2.0),))
        set_policy(store, world.version, changed)
        world.service.compute_all(world.run_id)
        revised = {
            row["submission_id"]: row
            for row in current_grades(world.cohort, world.run_id)
        }
        for sid in ("S-ONE", "S-TWO"):
            assert revised[sid]["revision"] == 2, (
                f"{sid}: the policy change did not produce revision 2 "
                f"({revised[sid]['revision']!r}) — affected grades recompute "
                "(CT-GRADE-11: recomputes affected grades)"
            )
        # Resolve each revision to ITS versions: revision 1 to the older policy
        # version, revision 2 to the new one — both addressable through the key.
        for sid in ("S-ONE", "S-TWO"):
            old = grade_revision(world.cohort, world.run_id, sid, 1)
            fresh = grade_revision(world.cohort, world.run_id, sid, 2)
            assert old["policy_version"] == first[sid]["policy_version"], (
                f"{sid} revision 1 does not resolve to its older policy version — "
                "each revision records which policy produced it (CT-GRADE-11)"
            )
            # The key version resolves per revision too: only the policy changed
            # here, so revision 1 must still resolve to the SAME key version it
            # recorded — a per-run (not per-revision) overwrite would still show
            # a stale key under a recomputed policy.
            assert old["answer_key_ref"] == fresh["answer_key_ref"], (
                f"{sid}'s revisions do not resolve to the same answer-key ref — "
                "each revision records which key version produced it "
                "(CT-GRADE-11: policy AND key version per revision)"
            )
            assert revised[sid]["policy_version"] != old["policy_version"], (
                "the new revision does not record the changed policy version "
                "(CT-GRADE-11: records which policy version produced each revision)"
            )
    finally:
        store.close()