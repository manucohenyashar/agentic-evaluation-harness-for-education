"""TC-REG-27 (Validity T7, issue #900): SV-13 pinned. A graded class that has been promoted can be
purged.

Traces: FR-STORE-22 (-> TC-STORE-31). Source: `docs/design/statistical_validity_test_plan.md`
§3.17; the gap is SV-13 in `statistical_validity_design_delta.md`.

**SV-13.** Before #880, `purge_cohort` gated only on CT-STORE-10's three Tier D tables, each
scoped by `cohort_id`. A real promotion never satisfies them: `audit_record` rows are never
stamped with a cohort. So the gate could never pass, and a graded class could never be deleted.
The one case that reached the purge (TC-EXTRACT-14) sat behind a written-ahead blocker keyed on
`aeh.stats:promote_cohort`, a surface that never existed.

The case runs the teacher's whole path through shipped modules:

1. a class is graded;
2. the blind sample is drafted and finished (M-REVIEW);
3. the administration is promoted (`aeh.pipeline.promote_administration`);
4. the class is purged.

The pin is that step 4 passes, on the administration route. On the regressed code it refuses
with CT-STORE-10's unmet gates.

**Isolation: rung 3.** A real store; `network_guard` holds the run offline.
"""

from __future__ import annotations

import pytest

from aeh.store.purge import ADMINISTRATIONS_RECORDED
from tests.support.graded_class import SWEPT, cohort_counts, graded_class, purge

pytestmark = pytest.mark.integration


def test_tc_reg_27_sv13_a_promoted_class_purges(tmp_path, network_guard):
    world, administration = graded_class(tmp_path / "w", "c-sv13")
    try:
        world.finish(administration)
        assert world.promote(administration, "finish").promoted

        report = purge(world, administration.cohort_id)

        assert report.preconditions_verified == (ADMINISTRATIONS_RECORDED,), (
            f"SV-13 is back: a promoted class passed {report.preconditions_verified}")
        assert cohort_counts(world, administration.cohort_id) == {t: 0 for t in SWEPT}
        network_guard.assert_no_network()
    finally:
        world.close()
