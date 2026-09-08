"""`M-SETUP` Stage A's grade policy — written ahead of **#53** (issue #54).

Case `TC-SETUP-15` (FR-SETUP-12, P0), rung 2. It carries `writtenahead` and sits outside
`TEST_CMD` until #53 lands `SetupService.set_grade_policy` — the §3.6 Interface member
the case drives. The entry keyed "#53 policy" in `tests/support/impl.py` is deliberately
keyed on the **SetupService** member and not on `aeh.pkg:set_grade_policy`: M-PKG's half
(policy object, closed vocabulary, default, storage) already shipped with #50, so a pkg
key would resolve today while the setup step that *records the default as taken* — the
clause the case exists for — is still #53's.

The distinction the case turns on is a row's existence, not a value: `grade_policy(v)`
returns the default policy for both a never-set version and a recorded-default version,
so "the package records that the default was used" (FR-SETUP-12) is asserted by counting
`grade_policy` rows — one after the skip, zero on a control package nobody touched. A
skipped step is thereby distinguishable from an explicit identical choice, which is
FR-SETUP-14's whole point and the reason CT-SETUP-10 calls the recording load-bearing.
"""

from __future__ import annotations

import pytest

from aeh.pkg import GradePolicy, default_grade_policy

from tests.support.impl import SETUP_MODULE, require, require_attr
from tests.support.setup_harness import (
    INVENTORY_REPLY,
    ingest_document,
    stage_chain,
)
from tests.support.store_api import statement

pytestmark = pytest.mark.writtenahead

ISSUE = "#53"

#: A declared policy from the closed vocabulary, distinct from the default.
DECLARED_POLICY = GradePolicy(combination="best_k_of_n", k=2)


def _chain_confirmed(data_dir, package_id: str):
    """A chain through S2 (propose, confirm) — the earliest state the policy step follows."""
    chain = stage_chain(data_dir, package_id=package_id)
    assessment = ingest_document(chain.store)
    chain.provider.replies = [INVENTORY_REPLY]
    proposal = chain.service.propose_inventory(assessment)
    chain.service.confirm_inventory(proposal.proposal_id)
    return chain, chain.catalog.draft_version()


def _policy_rows(data_dir, package_id: str, version, issue: str) -> int:
    """How many `grade_policy` rows the version carries — the recorded-vs-never-set test."""
    from aeh.pkg import PackageCatalog

    from aeh.store import open_store

    handle = PackageCatalog(open_store(data_dir).package(package_id),
                            package_id=package_id)
    with handle.transaction() as tx:
        rows = tx.execute(statement(
            "SELECT policy FROM grade_policy WHERE package_version_id = :v",
            issue=issue), v=version).fetchall()
    return len(rows)


@pytest.mark.integration
def test_tc_setup_15_declared_policy_captured_and_undeclared_default_recorded_as_default(
    tmp_data_dir,
):
    """`TC-SETUP-15` (FR-SETUP-12, P0) — a teacher-declared policy is captured from the
    closed vocabulary and stored as declared; with none declared, the default policy
    applies **and the package records that the default was used** — a row, so the skipped
    step is distinguishable from an explicit identical choice and from a package nobody
    reached the step on at all."""
    setup = require(SETUP_MODULE, "SetupService", issue=ISSUE)
    require_attr(setup, "set_grade_policy", issue=ISSUE)

    # A teacher-declared policy: captured verbatim from the closed vocabulary.
    declared_chain, declared_version = _chain_confirmed(tmp_data_dir, "pkg-policy-declared")
    applied = declared_chain.service.set_grade_policy(DECLARED_POLICY)
    assert applied == DECLARED_POLICY
    assert declared_chain.catalog.grade_policy(declared_version) == DECLARED_POLICY

    # No declared policy: the skip. The default applies — and is recorded as a default.
    skip_chain, skip_version = _chain_confirmed(tmp_data_dir, "pkg-policy-skip")
    applied = skip_chain.service.set_grade_policy(None)
    assert applied == default_grade_policy(), (
        "TC-SETUP-15: skipping the policy step must apply the default policy (sum of "
        "criteria into sum of questions, raw points, no boundary table), not refuse — "
        "the step is skippable (FR-SETUP-14, CT-SETUP-10)"
    )
    assert skip_chain.catalog.grade_policy(skip_version) == default_grade_policy()
    assert _policy_rows(tmp_data_dir, "pkg-policy-skip", skip_version, ISSUE) == 1, (
        "TC-SETUP-15: the default was applied but not recorded — FR-SETUP-12 requires "
        "the package to record that the default was used, because M-STATS answers "
        "whether skips are taken from exactly this record (CT-SETUP-10 is load-bearing)"
    )

    # The control: a package nobody offered the policy to carries NO row. A recorded
    # default and a never-set version must be distinguishable from stored data, or
    # "recorded that the default was used" is indistinguishable from silence.
    control_chain, control_version = _chain_confirmed(tmp_data_dir, "pkg-policy-never")
    assert control_chain.catalog.grade_policy(control_version) == default_grade_policy()
    assert _policy_rows(tmp_data_dir, "pkg-policy-never", control_version, ISSUE) == 0
