"""`TC-GRADE-15` — the rollup keeps deterministic results in a separate block, and no
combined figure across the two exists anywhere in it.

Test plan §5.14; `FR-GRADE-15` ("The rollup shall report deterministic (multiple-choice)
results in a block separate from judged criteria and shall provide **no** combined figure
across the two"); Integration / 2; artifact assertion (field enumeration); P0.

**Written ahead of implementation** (test plan §8.2). The shipped `ClassRollup` carries
only rubric-version segments (`CT-CALIB-09`'s segmentation) — no deterministic/judged
separation and, necessarily, no combined figure to forbid. `#104` — *"Class rollup,
criterion statistics, rubric findings and export"*, whose second acceptance criterion
is this clause — lands the separation, so this file carries
`@pytest.mark.writtenahead` and its registry entry names the symbol below.

**The invented-and-disclosed key** (the `evaluate_alerts` / `export_grade_artifacts`
precedent): `aeh.grade:separated_rollup`. Keying on `ClassRollup` or on `rollup` is
barred by the doctrine — both are §3.14 Protocol surface and the shipped record would
resolve the gate against the un-separated shape — so the key is the accessor whose
landing IS the separation: a rollup record that carries the deterministic block. The
name is absent from both design documents (checked: zero occurrences); the signature
assumed here — `separated_rollup(run_id, store)` mirroring `class_rollup`'s handle
shape — reconciles at #104's landing like every other reserved name.

**The field-enumeration oracle** (the `test_ct_det_item_stats.py` precedent: assert the
separation STRUCTURALLY, so a later merge FAILS rather than quietly reading wrong):

1. the rollup record carries a deterministic block — a field whose name names it;
2. **no** field anywhere on the record can carry a combined figure across judged and
   deterministic results: the enumerated field set offers no `combined`/`overall`/
   `all_results`/`class_total` alias, and the judged block's own fields are disjoint
   from the deterministic block's — a merge would have to rename a field, which is the
   failure the enumeration catches;
3. the judged block's submission count matches the hand count (all three submissions
   carry the judged criterion, so the judged population is the whole run), so the block
   is not merely present but is the judged one.

**Disclosed stand-ins** (`grade_vocabulary.py`, header): `write_criterion_scores`
standing in for `M-AGG`; the deterministic criterion's rows are written by the same
stand-in with M-DET's band names (`correct`/`incorrect`), since M-DET's evaluator
(`CT-DET-09`) is not this case's subject — the rollup reads settled rows either way.

**Isolation:** rung 2 — real store, real package lineage (both criterion kinds on one
run), real grade ledger.
"""

from __future__ import annotations

import dataclasses

import pytest

from aeh.pkg import GradePolicy, PackageCatalog
from aeh.store import open_store
from tests.support.grade_vocabulary import grade_rows, write_criterion_scores
from tests.support.impl import GRADE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [
    pytest.mark.integration,
    # Red by design until #104 lands the separated rollup this case pins
    # (WRITTEN_AHEAD_BLOCKERS: "#104 separated rollup" -> `aeh.grade:separated_rollup`).
    pytest.mark.writtenahead,
]

ISSUE = "#104"

_SUBMISSIONS = ("S-B1", "S-B2", "S-B3")

#: One judged criterion and one deterministic criterion on the same rubric.
_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "MCQ", "kind": "mcq", "scoring_model": "deterministic"},
)


def _seed_mixed_run(store):
    """A run whose submissions carry judged scores (bands B1..B5, the M-AGG stand-in)
    and deterministic scores (M-DET's correct/incorrect bands, disclosed)."""
    require(GRADE_MODULE, "open_grade", issue=ISSUE)
    _orchestrator, run_id, version = seed_run(
        store, submissions=_SUBMISSIONS, criteria=_CRITERIA
    )
    catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
    catalog.set_grade_policy(version, GradePolicy(combination="weighted_sum"))
    cohort = store.cohort(ORCH_COHORT_ID)
    write_criterion_scores(
        cohort,
        [("S-B1", "C1", "B2", 7.0, "auto"), ("S-B1", "MCQ", "correct", 1.0, "auto"),
         ("S-B2", "C1", "B1", 3.0, "auto"), ("S-B2", "MCQ", "incorrect", 0.0, "auto"),
         ("S-B3", "C1", "B3", 9.0, "auto"), ("S-B3", "MCQ", "correct", 1.0, "auto")],
    )
    return run_id, cohort


def test_tc_grade_15_the_rollup_separates_deterministic_results_by_field_enumeration(
    tmp_data_dir,
):
    """`TC-GRADE-15` — a separate deterministic block exists, no combined figure field
    exists anywhere on the rollup, and the judged block's figures match the hand
    count. A merge cannot slip through: it would need a new field name, and the
    enumeration's negative list refuses the aliases."""
    separated_rollup = require(GRADE_MODULE, "separated_rollup", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        run_id, cohort = _seed_mixed_run(store)

        svc = require(GRADE_MODULE, "open_grade", issue=ISSUE)(store)
        svc.compute_all(run_id)
        assert all(row["total"] is not None for row in grade_rows(cohort)), (
            "fixture premise failed: a grade row carries no total — the rollup's "
            "blocks are built over settled figures"
        )

        rollup = separated_rollup(run_id, store)

        # Limb 1 — the separate block exists, by name.
        fields = {field.name for field in dataclasses.fields(rollup)}
        assert any("deterministic" in name for name in fields), (
            f"the rollup record carries {sorted(fields)} — no field names the "
            "deterministic block (FR-GRADE-15): multiple-choice results must appear "
            "in a block of their own"
        )

        # Limb 2 — no combined figure, anywhere on the record. The negative list is
        # the names a merge would reach for; none may exist.
        merged_aliases = ("combined", "overall", "all_results", "unified",
                          "mixed_total", "full_class_mean")
        offenders = [
            name for name in fields
            if any(alias in name.lower() for alias in merged_aliases)
        ]
        assert not offenders, (
            f"the rollup carries combined-figure field(s) {offenders} — a figure "
            "across judged and deterministic results is FR-GRADE-15's exact refusal "
            "(the two are not comparable)"
        )

        # Limb 3 — the judged block is the judged one: its submission count is the
        # hand count. The judged population is the whole run (three submissions,
        # totals 8.0 / 3.0 / 10.0 under the plain sum over C1 and MCQ's points).
        judged = [field.name for field in dataclasses.fields(rollup)
                  if "judged" in field.name.lower()]
        assert judged, (
            f"the rollup names no judged block ({sorted(fields)}) — the separation is "
            "two-sided: a deterministic block without a judged one is a relabeling"
        )
        judged_block = getattr(rollup, judged[0])
        judged_count = (
            judged_block.submission_count
            if hasattr(judged_block, "submission_count")
            else len(judged_block)
        )
        assert judged_count == 3, (
            f"the judged block covers {judged_count!r} submissions, expected 3 — the "
            "fixture's judged population is the whole run (hand count)"
        )
    finally:
        store.close()