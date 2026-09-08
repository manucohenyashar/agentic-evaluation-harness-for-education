"""`TC-ORCH-01` — `work_id` changes when any of its nine inputs changes, so stale results
cannot be reused. Test plan §5.7 block form; `FR-ORCH-01`, `NFR-ORCH-05`; RISK-09 (Critical).

Oracle, per the plan: **exact value against a committed reference** for step 1;
**pairwise-distinctness invariant** for step 2; **determinism invariants** for steps 3 and 4.

Relationship to `TC-REG-06`, disclosed rather than duplicated: the committed reference this
case's step 1 checks against **is** `TC-REG-06`'s golden
(`fixtures/baselines/TC-REG-06/work-id-reference.json`, recorded by #217's PR with the
migration note that golden demands). This file does not keep a second copy of the reference
values — a second golden would be a second place to move when the encoding changes
consciously, and the whole point of the golden is that it moves as a block. Step 2 is
re-stated here over this file's own baseline because the plan's block form asks for the
sweep at the case's own home; `TC-REG-06` carries the same invariant over its ten-tuple
population, so a diff that passes one and breaks the other is itself a finding.

Step 4 enumerates through a real store and a real Tier P package
(`tests/support/orch_run.py`): the property under test is *the whole run's* `work_id` set,
and an enumeration-shaped double would assert it against itself.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from aeh.orch import WORK_ID_INPUTS, compute_work_id
from aeh.store import open_store
from tests.support.baselines import golden_bytes, work_id_reference_inputs
from tests.support.orch_run import seed_run

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The baseline tuple §5.7's block form names — the same nine inputs the committed
#: reference population's `base` tuple carries, spelled out here so the sweep below reads
#: against the case's own fixture rather than against an import.
BASELINE_INPUTS: dict[str, str | None] = {
    "run_id": "RUN-0001",
    "stage": "score",
    "submission_id": "SYN-001",
    "criterion_id": "C-01",
    "judge_id": "judge-a",
    "package_version_id": "PKG-REF@1",
    "panel_config": "depth=3;arms=a,b,c",
    "prompt_template_version": "judge/4",
    "extractor_version": "extract/2",
}

#: One perturbed value per input. `judge_id` and `criterion_id` perturb between strings;
#: the null judge's own stability and distinctness are the variants test below.
_PERTURBED_VALUES: dict[str, str | None] = {
    "run_id": "RUN-0001-perturbed",
    "stage": "extract",
    "submission_id": "SYN-001-perturbed",
    "criterion_id": "C2",
    "judge_id": "judge-z",
    "package_version_id": "pkg-orch@v2",
    "panel_config": '{"arms": ["judge-a", "judge-b", "judge-c", "judge-d"]}',
    "prompt_template_version": "conf-v2.0.0",
    "extractor_version": "extract/3",
}


def test_tc_orch_01_step1_baseline_matches_the_committed_reference():
    """Step 1 — compute the baseline `work_id` and compare it against the committed
    reference value (`TC-REG-06`'s golden; see module docstring)."""
    reference = work_id_reference_inputs()
    base_tuple = next(t for t in reference["tuples"] if t["label"] == "base")
    golden = json.loads(
        golden_bytes("TC-REG-06", "TC-REG-06/work-id-reference.json").decode("utf-8")
    )
    committed = golden["work_ids"]["base"]

    computed = compute_work_id(**BASELINE_INPUTS)
    reference_computed = compute_work_id(**base_tuple["inputs"])

    assert BASELINE_INPUTS == base_tuple["inputs"], (
        "this file's baseline drifted from the reference population's base tuple; the "
        "two are the same fixture by construction and must be reconciled before either "
        "assertion below means anything"
    )
    assert computed == committed, (
        f"the baseline work_id {computed!r} does not match the committed reference "
        f"{committed!r}. A diff here means the work-ID encoding moved — which is "
        "permitted only as a conscious act with the migration note TC-REG-06's grounds "
        "require, never as a silent recomputation."
    )
    assert reference_computed == committed


def test_tc_orch_01_step2_each_input_perturbed_alone_is_distinct():
    """Step 2 — perturb each of the nine inputs in turn; every resulting id differs from
    the baseline and from every other perturbation. The `prompt_template_version` row is
    the one that matters most: it is what makes a prompt change invalidate dependent work
    automatically rather than by manual cleanup (NFR-EXTRACT-02/03)."""
    baseline = compute_work_id(**BASELINE_INPUTS)  # type: ignore[arg-type]
    perturbed: dict[str, str] = {}
    for name in WORK_ID_INPUTS:
        kwargs = dict(BASELINE_INPUTS)
        kwargs[name] = _PERTURBED_VALUES[name]
        perturbed[name] = compute_work_id(**kwargs)  # type: ignore[arg-type]

    assert set(perturbed) == set(WORK_ID_INPUTS), (
        "the sweep must cover every one of FR-ORCH-01's nine inputs — a missing row is a "
        "field nothing would notice being ignored"
    )
    for name, work_id in perturbed.items():
        assert work_id != baseline, (
            f"perturbing {name!r} alone left the work_id unchanged — a stale result "
            f"computed under a different {name} would be reused as current (RISK-09)"
        )
    distinct = sorted(set(perturbed.values()))
    assert len(distinct) == len(perturbed), (
        "two different single-input perturbations collided on one work_id; the sweep's "
        "oracle is pairwise distinctness, not merely differ-from-baseline"
    )


def test_tc_orch_01_variants_panel_order_and_null_judge():
    """The plan's variants: `panel_config` differing **only** in judge order, and a null
    `judge_id` for a deterministic unit — which must still be stable and distinct."""
    baseline = compute_work_id(**BASELINE_INPUTS)  # type: ignore[arg-type]

    # panel order is semantic (dispatch order, the escalation ladder's first arm), so two
    # panels with the same members in a different order are different panels — different
    # units — even though the judge *set* is unchanged.
    reordered = dict(BASELINE_INPUTS)
    reordered["panel_config"] = '{"arms": ["judge-c", "judge-a", "judge-b"]}'
    assert compute_work_id(**reordered) != baseline  # type: ignore[arg-type]

    # the deterministic unit: null judge. Stable under recomputation (same inputs, same
    # id — there is no clock or counter in the hash), and distinct from every string-judge
    # id, which is what the `N` type tag in the canonical encoding buys.
    deterministic = dict(BASELINE_INPUTS)
    deterministic["judge_id"] = None
    first = compute_work_id(**deterministic)  # type: ignore[arg-type]
    second = compute_work_id(**deterministic)  # type: ignore[arg-type]
    assert first == second, "a null-judge unit recomputed to a different id"
    assert first != baseline, "the null judge collided with a string-judge unit"


def _run_in_fresh_process(pythonhashseed: str) -> str:
    """Recompute the baseline id in a fresh interpreter under the given `PYTHONHASHSEED`."""
    payload = json.dumps(BASELINE_INPUTS)
    command = (
        "import json, sys; from aeh.orch import compute_work_id; "
        "print(compute_work_id(**json.load(sys.stdin)))"
    )
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = pythonhashseed
    env["PYTHONPATH"] = (
        str(REPO_ROOT / "src") + os.pathsep + str(REPO_ROOT) + os.pathsep
        + env.get("PYTHONPATH", "")
    )
    completed = subprocess.run(
        [sys.executable, "-c", command],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=120,
    )
    assert completed.returncode == 0, (
        f"the fresh-process recompute failed under PYTHONHASHSEED={pythonhashseed!r}: "
        f"{completed.stderr}"
    )
    return completed.stdout.strip()


def test_tc_orch_01_step3_stable_across_processes_and_hash_seeds():
    """Step 3 — recompute the baseline in a fresh process with a different
    `PYTHONHASHSEED` and assert equality (`NFR-ORCH-05`: the id is a pure function of the
    nine inputs; no environment or interpreter state reaches it)."""
    in_process = compute_work_id(**BASELINE_INPUTS)  # type: ignore[arg-type]
    seed_a = _run_in_fresh_process("0")
    seed_b = _run_in_fresh_process("20260908")
    assert seed_a == in_process, (
        f"the fresh-process id {seed_a!r} differs from the in-process id {in_process!r} "
        "under PYTHONHASHSEED=0 — some input is reaching the hash through an "
        "unordered structure, which is exactly the nondeterminism NFR-ORCH-05 forbids"
    )
    assert seed_b == in_process, (
        f"the fresh-process id {seed_b!r} differs from the in-process id {in_process!r} "
        "under a second hash seed; one seed agreeing can be coincidence, two cannot"
    )


def test_tc_orch_01_step4_whole_run_enumerated_twice_is_byte_identical(tmp_data_dir):
    """Step 4 — enumerate a whole run twice from the same (cohort, package version,
    config) and assert the two `work_id` sets are byte-identical. Compared as the sorted
    tuple the report carries — a set-of-bytes comparison, never a count."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _ = seed_run(
            store,
            submissions=("SYN-001", "SYN-002"),
            criteria=(
                {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
                {"criterion_id": "C2", "kind": "mcq"},
                {"criterion_id": "C3", "kind": "open", "scoring_model": "holistic"},
            ),
        )
        first = orchestrator.enumerate_units(run_id)
        second = orchestrator.enumerate_units(run_id)
    finally:
        store.close()
    assert first.work_ids == second.work_ids, (
        "two enumerations of the same (cohort, package version, config) produced "
        "different work_id sets — the enumeration is not a pure function of its inputs "
        "(NFR-ORCH-05)"
    )
    assert first.units_enumerated == second.units_enumerated
    # byte-identical, not merely equal-as-sets: the report's own tuple is the artifact.
    assert list(first.work_ids) == list(second.work_ids)
    assert len(set(first.work_ids)) == len(first.work_ids), (
        "the enumerated work_id set contains duplicates — a unit addressed twice is a "
        "unit whose result could be recorded under two ledger rows"
    )
