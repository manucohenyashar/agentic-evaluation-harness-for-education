"""The `work_id` reference values, which nobody may accept a diff to casually.

Case: `TC-REG-06` (test plan §6.9), `FR-ORCH-01`, golden file.

    baseline  The `work_id` reference values
    reviewer  Nobody may accept a diff casually
    grounds   A changed `work_id` means every stored result for that shape is now unreachable.
              Requires an explicit migration note

`FR-ORCH-01` defines it exactly — `sha256` over nine named inputs — and `CT-ORCH-01` states
what the definition buys: *"changing any of them produces a different unit, so stale results
are structurally unreusable rather than manually cleaned up."* That is a promise with two
halves, and a baseline of stable digests only tests one of them. A `compute_work_id` that
ignored `prompt_template_version` entirely would produce perfectly stable digests forever and
silently reuse every result computed under a different prompt.

So the baseline population is ten tuples: a base, and one variant per input differing in
exactly that one field (`fixtures/baselines/TC-REG-06/work-id-reference.inputs.json`). The
case asserts both halves — the digests match the frozen values, **and** all ten are distinct.

**The digests are not committed yet, and that is deliberate.** The inputs are `FR-ORCH-01`'s
nine fields and are knowable today; the digest depends on how a tuple is canonically encoded
into bytes, which `M-ORCH` has not chosen. A guessed encoding frozen into a baseline would
dictate the implementation from the test side — the one thing a regression baseline must never
do. `tests/support/baselines.py` refuses to invent it.

**Written ahead of implementation** (§8.2). `compute_work_id` is #57's. Remove the marker —
never the test — when #57 closes, and record the baseline in that PR with the migration note
the grounds above require.
"""

from __future__ import annotations

import json

import pytest

from tests.support.baselines import (
    assert_matches_golden,
    entry_for,
    work_id_reference_inputs,
)
from tests.support.impl import ORCH_MODULE, require

pytestmark = pytest.mark.writtenahead

ISSUE = "#57"
CASE = "TC-REG-06"
GOLDEN = "TC-REG-06/work-id-reference.json"


def test_tc_reg_06_the_work_id_reference_values_are_unchanged_and_still_discriminating():
    """TC-REG-06 — the `work_id` reference values.

    Oracle: golden file over the reference input tuples, plus pairwise distinctness.
    """
    compute_work_id = require(ORCH_MODULE, "compute_work_id", issue=ISSUE)
    entry = entry_for(CASE)

    reference = work_id_reference_inputs()
    fields = tuple(reference["inputs_in_requirement_order"])
    assert len(fields) == 9, (
        f"FR-ORCH-01 names nine inputs; the reference population declares {len(fields)}: "
        f"{fields}. A missing field is a field nothing would notice being ignored."
    )

    computed = {
        tuple_spec["label"]: compute_work_id(**tuple_spec["inputs"])
        for tuple_spec in reference["tuples"]
    }

    # `CT-ORCH-01`'s half that a stable-digest baseline cannot see: each variant differs from the
    # base in exactly one of the nine inputs, so an implementation that ignores any one of them
    # produces a collision here. Asserted *before* the golden comparison, because a `work_id`
    # that collides is wrong whatever it is frozen to.
    collisions = {
        label: work_id
        for label, work_id in computed.items()
        if list(computed.values()).count(work_id) > 1
    }
    assert not collisions, (
        f"{len(collisions)} reference tuples share a work_id: {collisions}. Each differs from "
        f"the base in exactly one FR-ORCH-01 input, so a collision means that input does not "
        f"reach the hash — and a stale result computed under a different value of it would be "
        f"reused as current."
    )

    produced = (
        json.dumps(
            {"inputs_in_requirement_order": list(fields), "work_ids": computed},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")

    assert_matches_golden(CASE, GOLDEN, produced)
    assert entry.grounds, "the registry entry carries no grounds"
