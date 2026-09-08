"""`CT-SETUP-10` — the default grade policy is applied and recorded as a default
(`TC-SETUP-C10`).

Case of test plan §6.11.6; issue #56 (TS-63). **Split disposition**, probed:

1. **The always-found half is green.** For a package whose setup declared NO
   grade policy, the stored-data answer is the exact default — unweighted sum
   of criteria (combination `weighted_sum` with NO weights), raw points (no
   scale, no rounding), no boundary table (zero `grade_boundary` rows), null
   review window. `PackageCatalog.grade_policy` answers this for a version with
   no stored row (src/aeh/pkg.py:2181-2190), so a policy question asked of the
   published package always FINDS a policy — the storage-layer guarantee
   `M-GRADE` will read. Probed on shipped code.
2. **The recorded-as-a-default half is written ahead of #53.** Recording that
   the default was used is M-SETUP's obligation, "discharged by storing the
   policy" (src/aeh/pkg.py:538) — and `SetupService.set_grade_policy` (the
   surface that discharges it, with FR-SETUP-12's semantics) is #53's. The test
   carries `writtenahead` and a `WRITTEN_AHEAD_BLOCKERS` entry ("#56 C10 grade
   policy") keyed on it — the same key #54's
   `tests/integration/setup/test_setup_policy_pending.py` waits on, with the
   same reasoning that rejects a pkg key: the storage shipped with #50, the
   recording step did not.

**Disclosed deferral** (rung 3, the consumer artifact): `M-GRADE` does not
exist yet (`src/aeh/` carries conf, ingest, pkg, prov, setup, store), so the
clause's consumer half — `M-GRADE` contains NO path that invents a policy —
has no module to scan. The green half below pins the storage-layer guarantee
it will read; the sweep lands with the module, reading its branch surface
against the stored row. A `M-GRADE` fallback would be a second policy source,
invisible and unversioned — the deferral is on record here, not forgotten.
"""
from __future__ import annotations

import sqlite3

import pytest

from aeh.pkg import GradePolicy, default_grade_policy
from aeh.setup import SetupService
from tests.contract.setup._doubles import db_file_for, ingest_document, stage_chain
from tests.support.impl import require_attr

pytestmark = pytest.mark.contract

ISSUE = "#53"


def _published_without_policy(tmp_data_dir, package_id: str):
    """A full Stage A publish with NO grade policy declared anywhere."""
    chain = stage_chain(tmp_data_dir, package_id=package_id)
    chain.doc = ingest_document(chain.store, kind="assessment")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)
    version = chain.service.ensure_version()
    chain.catalog.add_criterion(version, "CRIT-A", question_id="Q1",
                                kind="open", max_points=4.0,
                                evidence_type="textual_span")  # FR-SETUP-09
    chain.catalog.add_criterion(version, "CRIT-B", question_id="Q2",
                                kind="open", max_points=6.0,
                                evidence_type="textual_span")  # FR-SETUP-09
    chain.service.set_answer_keys({"CRIT-A": ["b0"], "CRIT-B": ["b0"]}
                                  | {"CRIT-Q4": ["A"], "CRIT-Q5": ["A"],
                                     "CRIT-Q6": ["A"]})
    published = chain.service.publish("teacher-1")
    return chain, published


def test_tc_setup_c10_the_default_policy_is_always_found(tmp_data_dir):
    """With no policy declared, the published package answers with the EXACT
    default — unweighted sum, raw points, no boundary table — and never with
    nothing: a policy question always finds a policy."""
    chain, published = _published_without_policy(tmp_data_dir, "pkg-c10")

    policy = chain.catalog.grade_policy(published)
    default = default_grade_policy()
    assert policy == default, (
        f"the undeclared policy came back {policy!r}, not the default "
        f"{default!r} — the applied default changed (CT-SETUP-C10)"
    )
    # The default's exact shape, field by field: sum of criteria (unweighted:
    # the weighted_sum rule with an empty weight table), raw points (no
    # transforms), no boundary table, null review window.
    assert policy.combination == "weighted_sum" and policy.weights == ()
    assert policy.scale is None and policy.rounding is None
    assert policy.gate is None and policy.k is None and policy.drop is None
    assert policy.review_window_hours is None

    # No boundary table: zero grade_boundary rows in the published file.
    conn = sqlite3.connect(
        f"file:{db_file_for(tmp_data_dir, 'pkg-c10')}?mode=ro", uri=True)
    try:
        boundaries = conn.execute(
            "SELECT COUNT(*) AS n FROM grade_boundary "
            "WHERE package_version_id = ?", (published,)).fetchone()[0]
    finally:
        conn.close()
    assert boundaries == 0, (
        f"the default policy carried {boundaries} boundary row(s) — the default "
        "resolves raw points, not a boundary table (CT-SETUP-C10)"
    )


def test_tc_setup_c10_the_default_is_recorded_as_a_default(tmp_data_dir):
    """#53 landed the recording: the setup flow RECORDS the default — the grade
    policy row EXISTS after a publish that declared nothing (discharged by
    storing — distinguishable from the read-side fallback, which answers
    without any row), the stored policy is the default exactly, and the
    recorded step's provenance says the default was TAKEN. The `writtenahead`
    marker and its `WRITTEN_AHEAD_BLOCKERS` entry ("#56 C10 grade policy") are
    gone."""
    require_attr(SetupService, "set_grade_policy", issue=ISSUE)

    chain, published = _published_without_policy(tmp_data_dir, "pkg-c10r")

    # The row exists: the recording obligation is discharged by storing the
    # policy, not by leaving the read-side fallback to answer silently.
    conn = sqlite3.connect(
        f"file:{db_file_for(tmp_data_dir, 'pkg-c10r')}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT policy FROM grade_policy "
            "WHERE package_version_id = ?", (published,)).fetchall()
    finally:
        conn.close()
    assert rows, (
        "no grade_policy row was stored for a package whose setup declared "
        "nothing — the default was applied silently, indistinguishable from a "
        "teacher's declared policy (CT-SETUP-C10)"
    )

    # The stored policy IS the default, exactly.
    policy = chain.catalog.grade_policy(published)
    assert policy == default_grade_policy(), (
        "the recorded policy is not the default (CT-SETUP-C10)"
    )

    # And the provenance: the grade_policy step reports DONE with the default
    # TAKEN — the recorded-provenance pattern every skippable default follows
    # (CT-SETUP-C01's assertion, at this step).
    progress = chain.service.steps()
    step = next(s for s in progress.steps if s.step_id == "grade_policy")
    assert step.done, "the grade_policy step did not report done (CT-SETUP-C10)"
    assert "staged by" not in step.note, (
        f"the grade_policy step still reports {step.note!r} — the default was "
        "taken but not recorded as taken (CT-SETUP-C10)"
    )
