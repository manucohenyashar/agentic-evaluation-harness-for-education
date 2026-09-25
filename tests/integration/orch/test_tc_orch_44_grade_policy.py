"""`TS-85` (issue #379) — `TC-ORCH-44`: `create_run` refuses a package version whose grade
policy names criteria the version does not declare (`FR-ORCH-31`, `CT-ORCH-25`, RISK-53).

| Arm | Policy references | Expected |
|---|---|---|
| a | a per-question rule's criterion | **not expressible** — see below |
| b | the gate's criterion | `PackageIntegrityError` naming the missing id; zero run rows |
| c | a best-k member | **not expressible** — see below |
| d | a weight key | `PackageIntegrityError` naming the missing id; zero run rows |
| e | four missing ids at once (`C7`, `C8`, `C9`, `C10`) | the message contains **all four** |
| f | a valid policy | the run is created |

**The failure this prevents costs a night.** RISK-53: a policy references a deleted criterion,
the run spends the night, and it fails at grading — where the operator meets it as a missing
input on a run that has already spent the money. The check runs before the run row exists, so
a refusal leaves nothing behind, and that is what the row-count assertions pin.

**Arms (a) and (c) are not expressible against the shipped `GradePolicy`, and this is
reported, not approximated.** `validate_grade_policy`'s own docstring states it: "`FR-ORCH-31`
also names per-question rules and best-k members; neither has a field in the landed policy
object (`best_k_of_n` carries `k`, a count, and no member list), so there is nothing to read
for them today." The dataclass confirms it — `combination`, `weights`, `k`, `drop`, `gate`,
`scale`, `rounding`, `decimals`, `review_window_hours`, and only `weights` and `gate` name a
criterion. Writing arms (a) and (c) would mean inventing fields and testing a policy object
that does not exist. #379 reports the gap rather than faking coverage; a policy that grows
either field must extend `_policy_criterion_ids` **and** add its arm here in the same change.

**Arm (e) still gets its four ids**, through the two kinds that *are* expressible: three
missing weight keys and one missing gate criterion. The oracle — "the message contains all
four" — is what the arm is for, because an operator fixing a package needs the list, and a
refusal naming one id per attempt turns one edit into four.

**Isolation: rung 2** — real store, real Tier P package and a real `GradePolicy` written
through `PackageCatalog.set_grade_policy`.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

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
from aeh.orch import Orchestrator
from aeh.pkg import GateRule, GradePolicy, PackageCatalog, PackageIntegrityError
from aeh.store import Statement, open_store
from tests.support.orch_run import ORCH_COHORT_ID, orch_cfg, seed_cohort, seed_package

pytestmark = pytest.mark.integration

SUBMISSIONS = ("S01",)

#: The version declares C1 and C2 and nothing else; every missing id below is outside this set.
DECLARED = ("C1", "C2")
CRITERIA = tuple(
    {"criterion_id": name, "kind": "open", "scoring_model": "atomic"} for name in DECLARED
)

_COUNT_RUNS = Statement("SELECT COUNT(*) AS n FROM run")


def _policy_world(tmp_data_dir, policy: GradePolicy | None):
    """A cohort, a package version declaring `DECLARED`, and `policy` written onto it."""
    store = open_store(tmp_data_dir)
    seed_cohort(store, SUBMISSIONS)
    version = seed_package(store, CRITERIA)
    if policy is not None:
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        catalog.set_grade_policy(version, policy)
    return store, Orchestrator(store), version


def _run_count(store: Any) -> int:
    return int(store.cohort(ORCH_COHORT_ID).query(_COUNT_RUNS)[0]["n"])


def _refuses(store: Any, orchestrator: Any, version: str, missing: Sequence[str]) -> str:
    """Assert `create_run` refuses, names every id in `missing`, and writes no row."""
    before = _run_count(store)

    with pytest.raises(PackageIntegrityError) as caught:
        orchestrator.create_run(ORCH_COHORT_ID, version, orch_cfg())

    message = str(caught.value)
    for name in missing:
        assert name in message, (
            f"the refusal does not name the missing criterion {name!r}: {message!r}. An "
            "operator fixing the package needs every offending id, not the first"
        )
    assert _run_count(store) == before, (
        f"a refused create_run changed the run count from {before} to {_run_count(store)}; "
        "FR-ORCH-31's check runs BEFORE the run row exists so a refusal leaves nothing behind"
    )
    return message


# --- TC-ORCH-44 -----------------------------------------------------------------------------


def test_tc_orch_44_arm_b_a_gate_naming_an_undeclared_criterion_refuses_the_run(
    tmp_data_dir,
):
    """Arm (b) — the gate's criterion is not declared by the version."""
    store, orchestrator, version = _policy_world(
        tmp_data_dir,
        GradePolicy(
            combination="weighted_sum",
            weights=(("C1", 1.0),),
            gate=GateRule(criterion_id="C9", minimum=0.5),
        ),
    )
    try:
        _refuses(store, orchestrator, version, ("C9",))
    finally:
        store.close()


def test_tc_orch_44_arm_d_a_weight_naming_an_undeclared_criterion_refuses_the_run(
    tmp_data_dir,
):
    """Arm (d) — a weight key is not declared by the version."""
    store, orchestrator, version = _policy_world(
        tmp_data_dir,
        GradePolicy(combination="weighted_sum", weights=(("C1", 1.0), ("C8", 2.0))),
    )
    try:
        _refuses(store, orchestrator, version, ("C8",))
    finally:
        store.close()


def test_tc_orch_44_arm_e_every_missing_id_is_named_in_one_message(tmp_data_dir):
    """Arm (e) — four undeclared ids, and the refusal names all four.

    The arm that separates "refuses" from "refuses usefully". A check that raised on the first
    offender would pass arms (b) and (d) and fail here, and an operator would fix the package
    four times over four failed runs.
    """
    store, orchestrator, version = _policy_world(
        tmp_data_dir,
        GradePolicy(
            combination="weighted_sum",
            weights=(("C1", 1.0), ("C7", 1.0), ("C8", 1.0), ("C9", 1.0)),
            gate=GateRule(criterion_id="C10", minimum=0.5),
        ),
    )
    try:
        message = _refuses(store, orchestrator, version, ("C7", "C8", "C9", "C10"))
        # Compared as a set of quoted ids, not by substring: 'C1' is a substring of 'C10', so a
        # substring test would report the declared C1 as an offender.
        offenders = set(re.findall(r"'([^']+)'", message.split("The run refuses")[0]))
        assert offenders >= {"C7", "C8", "C9", "C10"}, (
            f"the offender clause names {sorted(offenders)}; all four missing ids belong there"
        )
        assert not offenders & set(DECLARED), (
            f"the refusal lists declared criteria {sorted(offenders & set(DECLARED))} among "
            f"the offenders: {message!r}"
        )
    finally:
        store.close()


def test_tc_orch_44_arm_f_a_valid_policy_creates_the_run(tmp_data_dir):
    """Arm (f) — the positive control. Without it every arm above passes against a
    `create_run` that refused every package it was ever handed."""
    store, orchestrator, version = _policy_world(
        tmp_data_dir,
        GradePolicy(
            combination="weighted_sum",
            weights=(("C1", 1.0), ("C2", 2.0)),
            gate=GateRule(criterion_id="C2", minimum=0.5),
        ),
    )
    try:
        run_id = orchestrator.create_run(ORCH_COHORT_ID, version, orch_cfg())

        assert run_id, "a policy naming only declared criteria must create the run"
        assert _run_count(store) == 1
    finally:
        store.close()


def test_tc_orch_44_a_version_with_no_declared_policy_creates_the_run(tmp_data_dir):
    """The other legal shape: no policy at all is not an error.

    `validate_grade_policy` returns early for a version that declares none — the default
    policy references nothing. Pinned because a check that treated "absent" as "empty and
    therefore invalid" would refuse every package in the repository's own fixtures.
    """
    store, orchestrator, version = _policy_world(tmp_data_dir, None)
    try:
        assert orchestrator.create_run(ORCH_COHORT_ID, version, orch_cfg())
        assert _run_count(store) == 1
    finally:
        store.close()


def test_tc_orch_44_the_refusal_is_a_package_error(tmp_data_dir):
    """`CT-ORCH-C25`'s type clause: `PackageIntegrityError` `isinstance` `PackageError`.

    A caller catching the package family must catch this one — the package is what needs
    fixing, and an error outside that family would be handled as an orchestrator fault.
    """
    from aeh.pkg import PackageError

    store, orchestrator, version = _policy_world(
        tmp_data_dir,
        GradePolicy(combination="weighted_sum", weights=(("C9", 1.0),)),
    )
    try:
        with pytest.raises(PackageIntegrityError) as caught:
            orchestrator.create_run(ORCH_COHORT_ID, version, orch_cfg())
        assert isinstance(caught.value, PackageError)
        assert getattr(caught.value, "retryable", None) is False, (
            "the refusal advertises itself as retryable; the package is the mistake and "
            "retrying the run reproduces it exactly"
        )
    finally:
        store.close()
