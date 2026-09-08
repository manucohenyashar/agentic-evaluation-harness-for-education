"""`TC-ORCH-34` — enumeration is deterministic and total, over **generated**
(cohort, package, config) triples. Test plan §5.7; `FR-ORCH-01`, `FR-ORCH-08`,
`NFR-ORCH-05`. Property / rung 0.

Two invariants, per the plan's oracle:

1. **Determinism** — the same input always yields the same `work_id` set. Asserted two
   ways per example: a re-enumeration is byte-identical (the set is a function of the
   inputs, not of what the pass finds), and **every unit's id equals a recomputation of
   `compute_work_id` over its nine inputs** read back from the ledger and the catalog —
   the id is pinned to the pure function, unit by unit, so no enumeration-internal state
   can reach it. Cross-process determinism under a varying `PYTHONHASHSEED` is
   `TC-ORCH-01` step 3's oracle and is not repeated here.
2. **Totality** — every (submission, criterion) pair that should have a unit has exactly
   one: one `deterministic` unit for an `mcq` criterion; one `extract` unit plus
   `min(base depth, panel size)` `score` units for a judged one, over the panel's first
   arms in order (`FR-SETUP-08`; an unknown scoring model is the conservative base of 1).

The dependency edges ride along in the generated packages (`FR-PKG-05` guarantees
acyclicity at the write) because totality is a claim about *real-shaped* packages, not
about independent criteria only. Sweep ordering itself is #59's and is deliberately not
asserted here. `FUZZ-06`'s work-ID half (distinct input tuples → distinct ids) is the
*sensitivity* property over generated pairs; this case is the *enumeration* property over
generated triples — different consequences of the same nine-input address space.

**Fixture shape, disclosed.** Panels are drawn from the legal sizes only — `CT-CONF-02`
refuses an even panel at resolution, so sizes 2 and 4 are caller errors, not enumeration
inputs. Examples share one scratch store (the `in_memory_catalog` pattern — per-example
store files cost a migration pass apiece) with counter-suffixed package and cohort ids, so
no example ever sees another's state, and nothing but the nine inputs can decide an id.
"""

from __future__ import annotations

import atexit
import itertools
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aeh.conf import CohortRef, resolve_run_config
from aeh.orch import (
    EXTRACTOR_VERSION,
    SCORING_MODEL_BASE_DEPTH,
    Orchestrator,
    compute_work_id,
)
from aeh.store import open_store
from tests.support.conf_builders import (
    EDGE_JUDGE,
    EDGE_JUDGE_2,
    EDGE_JUDGE_3,
    edge_cfg,
)

pytestmark = pytest.mark.property

#: The plan's row states no example count for this case (`FUZZ-06`'s "500 in CI" is that
#: row's own column). Thirty examples sweep every panel size, every scoring model, both
#: criterion kinds and edge shapes many times over; `deadline=None` because each example
#: stands up real Tier C and Tier P files, and no database round trip owes the default
#: 200 ms per-example budget.
EXAMPLES = 30

_JUDGES = (EDGE_JUDGE, EDGE_JUDGE_2, EDGE_JUDGE_3)
_SCORING_MODELS = ("atomic", "atomic_with_gate", "holistic", "model-not-in-the-map")

_EXAMPLE = itertools.count()
_SCRATCH = tempfile.TemporaryDirectory(prefix="aeh-orch-34-")


def _scratch_store():
    """The example store, created once and closed at process exit."""
    global _STORE
    try:
        return _STORE
    except NameError:
        _STORE = open_store(Path(_SCRATCH.name))
        atexit.register(lambda: _STORE.close())
        return _STORE


def _expected_score_depth(scoring_model: str, panel_size: int) -> int:
    return min(SCORING_MODEL_BASE_DEPTH.get(scoring_model, 1), panel_size)


@st.composite
def orch_triples(draw: st.DrawFn) -> dict:
    """A (cohort, package, config) triple: 1-6 criteria with acyclic-by-construction
    edges, 1-5 submissions, a legal panel size, and one of two prompt versions."""
    criteria: list[dict] = []
    for index in range(draw(st.integers(min_value=1, max_value=6))):
        criterion_id = f"C{index}"
        if draw(st.booleans()):
            spec: dict = {"criterion_id": criterion_id, "kind": "mcq"}
        else:
            spec = {
                "criterion_id": criterion_id,
                "kind": "open",
                "scoring_model": draw(st.sampled_from(_SCORING_MODELS)),
                # Edges only ever point at lower-indexed criteria, so every generated
                # graph is acyclic by construction — the property under test is
                # enumeration totality, not cycle rejection (`FR-PKG-05` owns that).
                "dependencies": tuple(
                    f"C{d}"
                    for d in draw(
                        st.lists(
                            st.integers(min_value=0, max_value=max(index - 1, 0)),
                            max_size=min(2, index),
                            unique=True,
                        )
                    )
                ),
            }
        criteria.append(spec)
    return {
        "criteria": criteria,
        "submissions": tuple(
            f"SYN-{i:03d}" for i in range(draw(st.integers(min_value=1, max_value=5)))
        ),
        # CT-CONF-02: [1, 3, 5] are the legal sizes — 5 would need a fifth judge ref,
        # and the depth clamp at min(depth, panel) is fully exercised by 1 and 3.
        "panel_size": draw(st.sampled_from([1, 3])),
        "prompt": draw(st.sampled_from(["conf-v1.0.0", "judge/4"])),
    }


@settings(max_examples=EXAMPLES, deadline=None)
@given(triple=orch_triples())
def test_tc_orch_34_enumeration_is_deterministic_and_total(triple: dict):
    """`TC-ORCH-34` — the same triple always yields the same `work_id` set, and every
    (submission, criterion) pair that should have a unit has exactly one."""
    panel = _JUDGES[: triple["panel_size"]]
    store = _scratch_store()
    n = next(_EXAMPLE)
    cohort_id = f"c-orch34-{n}"
    cfg = resolve_run_config(
        edge_cfg(HARNESS_PROFILE="edge-local", panel=panel,
                 prompt_template_v=triple["prompt"]),
        CohortRef(cohort_id=cohort_id, consent_class="synthetic"),
    )

    from tests.support.orch_run import seed_cohort, seed_package

    seed_cohort(store, triple["submissions"], cohort_id=cohort_id)
    version = seed_package(store, triple["criteria"], package_id=f"pkg-orch34-{n}")
    orchestrator = Orchestrator(store)
    run_id = orchestrator.create_run(cohort_id, version, cfg, run_id=f"run-{n}")

    first = orchestrator.enumerate_units(run_id)
    second = orchestrator.enumerate_units(run_id)

    # Determinism, form 1: re-enumeration is byte-identical.
    assert first.work_ids == second.work_ids, (
        "re-enumerating the same run produced a different work_id set — the set is a "
        "function of what the pass finds, not of the inputs (NFR-ORCH-05)"
    )
    assert len(set(first.work_ids)) == len(first.work_ids), (
        "the enumerated set carries duplicate work_ids"
    )

    # Determinism, form 2: every unit's id equals compute_work_id over the nine inputs,
    # read back from the ledger and the catalog — the address is pinned to the pure
    # function, unit by unit.
    run_row = store.cohort(cohort_id).query(
        "SELECT panel_config, prompt_template_v, package_version_id FROM run "
        "WHERE run_id = :r",
        r=run_id,
    )[0]
    cohort = store.cohort(cohort_id)
    rows = cohort.query(
        "SELECT work_id, stage, submission_id, criterion_id, judge_id FROM work_unit "
        "WHERE run_id = :r",
        r=run_id,
    )
    assert len(rows) == len(first.work_ids)
    for row in rows:
        expected = compute_work_id(
            run_id=run_id,
            stage=row["stage"],
            submission_id=row["submission_id"],
            criterion_id=row["criterion_id"],
            judge_id=row["judge_id"],
            package_version_id=run_row["package_version_id"],
            panel_config=run_row["panel_config"],
            prompt_template_version=run_row["prompt_template_v"],
            extractor_version=EXTRACTOR_VERSION,
        )
        assert row["work_id"] == expected, (
            f"unit for ({row['submission_id']}, {row['criterion_id']}, "
            f"{row['stage']}) carries id {row['work_id'][:12]}… but the nine inputs "
            f"recompute to {expected[:12]}… — enumeration and the pure function "
            "disagree about an address"
        )

    _assert_total(first, cohort, run_id, triple, panel)


def _assert_total(report, cohort, run_id: str, triple: dict, panel: tuple) -> None:
    """Totality: exactly the expected units exist for every (submission, criterion) pair,
    with the expected stages and judges — counted from the ledger, not from the report."""
    rows = cohort.query(
        "SELECT submission_id, criterion_id, stage, judge_id, COUNT(*) AS n "
        "FROM work_unit WHERE run_id = :r "
        "GROUP BY submission_id, criterion_id, stage, judge_id",
        r=run_id,
    )
    judged = {
        spec["criterion_id"]: spec["scoring_model"]
        for spec in triple["criteria"]
        if spec["kind"] == "open"
    }
    mcq = {spec["criterion_id"] for spec in triple["criteria"] if spec["kind"] == "mcq"}

    seen: dict[tuple, int] = {}
    for row in rows:
        key = (
            row["submission_id"],
            row["criterion_id"],
            row["stage"],
            row["judge_id"],
        )
        seen[key] = seen.get(key, 0) + row["n"]

    expected: dict[tuple, int] = {}
    for submission_id in triple["submissions"]:
        for criterion_id in mcq:
            expected[(submission_id, criterion_id, "deterministic", None)] = 1
        for criterion_id, scoring_model in judged.items():
            expected[(submission_id, criterion_id, "extract", None)] = 1
            depth = _expected_score_depth(scoring_model, len(panel))
            for arm in panel[:depth]:
                expected[(submission_id, criterion_id, "score", arm.build_id)] = 1

    assert seen == expected, (
        "enumeration is not total over the generated triple: "
        f"missing={ {k: v for k, v in expected.items() if seen.get(k) != v} } "
        f"unexpected={ {k: v for k, v in seen.items() if expected.get(k) != v} }"
    )
    assert report.units_enumerated == sum(expected.values()), (
        "the report's own count disagrees with the ledger's grouped counts — the report "
        "would be summarizing an enumeration that did not happen"
    )
