"""`TS-88` (issue #382) — `TC-DET-15`: a deterministic evaluation of run B never modifies run A's
rows (`FR-DET-11`, `CT-DET-15`).

Gap-fix test plan §5 (P0, rung 2, two-run oracle):

    Run A evaluates MCQ `Q3` for S1 with key `B`, answer `B` (full points). Run B, same cohort, has
    key corrected to `C`; `rederive_for_key_change` is called for run B. Expected: run B's row 0
    points; run A's row **unchanged** (full points), and `band_spread = 0` on both. A call naming
    run A re-derives only A.

**The world** is the M-DET suite's (`tests/support/det_vocabulary.py`): a real cohort, a real
package version with MCQ criterion `M3` over question `Q3`, S1's head document with a resolved
selection `B`, and two real runs over the same version (`create_run`). Both runs are evaluated
under key `B` first, so both hold a full-points row before the correction — which is what makes
"run A unchanged" a claim about isolation rather than about a row that was never written.

**"A call naming run A re-derives only A."** After B's correction, a further correction back to key
`B` is re-derived naming run A. A is already correct under `B`, so it must stay at full points —
and run B, at 0 under `C`, must **stay** at 0. A re-derivation that ignored the run would lift B
back to full points, which is exactly the leak this arm reads.

**Interface assumed** (design delta §3.6), for #359 to reconcile deliberately:
`DeterministicEvaluator.rederive_for_key_change(cohort_id, criterion_id, new_version, run_id=...)`
— the shipped positional signature plus the run the design says it re-derives ("shall re-derive
only rows of the named run"), passed by keyword.

**Written ahead of implementation: yes** — keyed on #359's `agg_run_scoped_score` migration; the
run-scoped reads here need its `run_id` column.
"""

from __future__ import annotations

import pytest

from aeh.conf import CohortRef, resolve_run_config
from aeh.det import DeterministicEvaluator
from aeh.orch import Orchestrator
from aeh.pkg import PackageCatalog
from tests.support.conf_builders import edge_cfg
from tests.support.det_vocabulary import (
    open_det_store,
    seed_answer_region,
    seed_det_world,
    seed_head_document,
)
from tests.support.impl import NotImplementedYet
from tests.support.run_scoped import run_scoped_migration

pytestmark = pytest.mark.integration

ISSUE = "#359"


def _row(store, cohort_id, run_id):
    rows = store.cohort(cohort_id).query(
        "SELECT points, band, band_spread FROM criterion_score "
        "WHERE run_id = :r AND submission_id = 'S1' AND criterion_id = 'M3'", r=run_id)
    assert len(rows) == 1, f"run {run_id} holds {len(rows)} M3 rows for S1, expected 1"
    return dict(rows[0])


def test_tc_det_15_rederiving_run_b_never_modifies_run_a(tmp_data_dir):
    """`TC-DET-15` — B's correction reaches B only; a call naming A reaches A only."""
    store = open_det_store(tmp_data_dir)
    try:
        run_a, v1, cohort_id = seed_det_world(
            store, submissions=("S1",),
            criteria=[{"criterion_id": "M3", "question_id": "Q3", "key": ("B",)}],
        )
        document_id = seed_head_document(store, cohort_id, "S1")
        seed_answer_region(store, cohort_id, document_id, "Q3", selection="B")
        run_b = Orchestrator(store).create_run(
            cohort_id, v1,
            resolve_run_config(edge_cfg(), CohortRef(cohort_id=cohort_id,
                                                     consent_class="synthetic")),
        )
        assert run_a != run_b

        if run_scoped_migration() is None:
            raise NotImplementedYet(
                f"criterion_score is not run-scoped yet — no agg_run_scoped_score migration "
                f"(blocked on {ISSUE})"
            )
        evaluator = DeterministicEvaluator(store)
        evaluator.evaluate_cohort(run_a)
        evaluator.evaluate_cohort(run_b)
        assert _row(store, cohort_id, run_a)["points"] == 1.0, "precondition: A full points"
        assert _row(store, cohort_id, run_b)["points"] == 1.0, "precondition: B full points"

        catalog = PackageCatalog(store.package("pkg-det"), package_id="pkg-det")
        v2 = catalog.create_version(parent=v1)
        catalog.set_answer_key(v2, "M3", ("C",))
        evaluator.rederive_for_key_change(cohort_id, "M3", v2, run_id=run_b)

        row_a, row_b = _row(store, cohort_id, run_a), _row(store, cohort_id, run_b)
        assert row_b["points"] == 0.0, f"run B under key C: {row_b['points']!r}, expected 0"
        assert row_a["points"] == 1.0, (
            f"run A's row moved to {row_a['points']!r} when run B's key was corrected (CT-DET-15)"
        )
        assert row_a["band_spread"] == 0 and row_b["band_spread"] == 0

        v3 = catalog.create_version(parent=v2)
        catalog.set_answer_key(v3, "M3", ("B",))
        evaluator.rederive_for_key_change(cohort_id, "M3", v3, run_id=run_a)
        assert _row(store, cohort_id, run_a)["points"] == 1.0
        assert _row(store, cohort_id, run_b)["points"] == 0.0, (
            "a re-derivation naming run A lifted run B back to full points"
        )
    finally:
        store.close()
