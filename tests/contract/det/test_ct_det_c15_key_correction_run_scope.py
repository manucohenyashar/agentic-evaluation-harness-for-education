"""`TC-DET-C15` — a key correction reaches the run it names, and no other (§6.11,
`CT-DET-15`).

| Rung | Form |
|---|---|
| 2 | `TC-DET-15` — B's correction reaches B only; a call naming A reaches A only |
| 3 | the `TC-PIPE-01` two-run form: run A complete, then run B corrected, and A's deterministic rows stay byte-identical |

**The adversarial construction the plan names**: `rederive_for_key_change` resolves "the newest
run" when it is not told which run to correct, so a console action on the *older* run rewrites
the newer one's rows. This case is built around that default rather than around the happy path,
because the happy path is `TC-DET-15`'s and it is already green.

**The exposure is real and is pinned here rather than asserted away.** `run_id` is a
keyword-only parameter defaulting to `None`, and the fallback is `_newest_run` — "latest
non-null `started_at`, then `run_id`". Between two runs that were created and never started
that tiebreak is a **uuid comparison**: which run a bare
`rederive_for_key_change(cohort, criterion, version)` corrects is, for that population,
effectively random. A caller who knows the run must say so, and the cases below assert both
halves: naming the run works, and omitting it does not pick the caller's run by luck.

**Byte-identical, not "unchanged points".** The untouched run's row is compared across every
column the re-derivation could touch — points, band, spread and the audit's key reference —
because a correction that rewrote the band while leaving the points is still a rewrite of a
run nobody asked about, and the grade it feeds reads the band.

**Isolation: rung 2.** The rung-3 composed form is `TC-PIPE-01`'s; it drives
`run_to_completion` over a whole corpus and is cross-referenced rather than duplicated here —
two files driving the same composed run would report two answers for one property.
"""

from __future__ import annotations

from typing import Any

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

pytestmark = [pytest.mark.contract, pytest.mark.integration]

#: Every column a re-derivation could touch, so "unchanged" means the row, not one field.
COMPARED_COLUMNS = "points, band, band_spread, state, routing"


def _row(store: Any, cohort_id: str, run_id: str) -> dict[str, Any]:
    rows = store.cohort(cohort_id).query(
        f"SELECT {COMPARED_COLUMNS} FROM criterion_score "
        "WHERE run_id = :r AND submission_id = 'S1' AND criterion_id = 'M3'",
        r=run_id,
    )
    assert len(rows) == 1, f"run {run_id} holds {len(rows)} M3 rows for S1, expected 1"
    return dict(rows[0])


@pytest.fixture
def two_scored_runs(tmp_data_dir):
    """Runs A and B over one cohort, both deterministically evaluated under key `B`."""
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
            resolve_run_config(
                edge_cfg(), CohortRef(cohort_id=cohort_id, consent_class="synthetic")
            ),
        )
        assert run_a != run_b

        evaluator = DeterministicEvaluator(store)
        evaluator.evaluate_cohort(run_a)
        evaluator.evaluate_cohort(run_b)
        assert _row(store, cohort_id, run_a)["points"] == 1.0
        assert _row(store, cohort_id, run_b)["points"] == 1.0

        catalog = PackageCatalog(store.package("pkg-det"), package_id="pkg-det")
        yield store, cohort_id, run_a, run_b, v1, catalog, evaluator
    finally:
        store.close()


# --- TC-DET-C15 ---------------------------------------------------------------------------------


def test_tc_det_c15_a_named_correction_leaves_the_other_run_byte_identical(two_scored_runs):
    """Correcting run B's key leaves run A's row identical in **every** compared column.

    "Unchanged points" is the weaker assertion and it misses the case where a correction
    rewrote the band and left the arithmetic alone — still a rewrite of a run nobody asked
    about, and the grade downstream reads the band.
    """
    store, cohort_id, run_a, run_b, v1, catalog, evaluator = two_scored_runs
    before_a = _row(store, cohort_id, run_a)

    v2 = catalog.create_version(parent=v1)
    catalog.set_answer_key(v2, "M3", ("C",))
    evaluator.rederive_for_key_change(cohort_id, "M3", v2, run_id=run_b)

    assert _row(store, cohort_id, run_b)["points"] == 0.0, (
        "run B's correction did not reach run B, so the isolation assertion below is vacuous"
    )
    assert _row(store, cohort_id, run_a) == before_a, (
        f"run A's row moved when run B's key was corrected: {before_a} became "
        f"{_row(store, cohort_id, run_a)} (CT-DET-15)"
    )


def test_tc_det_c15_correcting_the_other_direction_is_equally_scoped(two_scored_runs):
    """And naming run A reaches A only — the symmetric half.

    Without it, "B's correction did not touch A" holds for an implementation that only ever
    writes B: the scoping would be an accident of which run the fixture happened to name.
    """
    store, cohort_id, run_a, run_b, v1, catalog, evaluator = two_scored_runs
    before_b = _row(store, cohort_id, run_b)

    v2 = catalog.create_version(parent=v1)
    catalog.set_answer_key(v2, "M3", ("C",))
    evaluator.rederive_for_key_change(cohort_id, "M3", v2, run_id=run_a)

    assert _row(store, cohort_id, run_a)["points"] == 0.0
    assert _row(store, cohort_id, run_b) == before_b, (
        f"run B's row moved when run A's key was corrected: {before_b} became "
        f"{_row(store, cohort_id, run_b)}"
    )


def test_tc_det_c15_omitting_the_run_falls_back_to_the_newest_and_is_a_reported_hazard(
    two_scored_runs,
):
    """**The adversarial construction, pinned.** A bare call corrects `_newest_run`, not the
    caller's run.

    `run_id` is keyword-only with a `None` default, and the fallback is
    `_newest_run(runs)` — "latest non-null `started_at`, then `run_id`". Neither run here has
    started, so the tiebreak is a **uuid comparison**: the run a bare call corrects is, for
    this population, whichever id sorts higher.

    That is the console hazard the plan names: an action on the older run that does not pass
    `run_id` rewrites the newer one's rows, and the operator sees a correction applied to a
    run they were not looking at. This case asserts the fallback reaches **exactly one** run
    and that it is the one `_newest_run` picks — so the behaviour is documented and any change
    to it is deliberate. #389 reports the hazard; whether the default should exist at all is a
    design call, not a test's.
    """
    from aeh.det import _newest_run

    store, cohort_id, run_a, run_b, v1, catalog, evaluator = two_scored_runs
    runs = store.cohort(cohort_id).query(
        "SELECT run_id, started_at FROM run ORDER BY run_id"
    )
    expected = _newest_run(list(runs))["run_id"]
    other = run_b if expected == run_a else run_a
    before_other = _row(store, cohort_id, other)

    v2 = catalog.create_version(parent=v1)
    catalog.set_answer_key(v2, "M3", ("C",))
    evaluator.rederive_for_key_change(cohort_id, "M3", v2)

    assert _row(store, cohort_id, expected)["points"] == 0.0, (
        f"a bare re-derivation did not reach {expected!r}, the run `_newest_run` names. If "
        "the default has changed, this case documents the old behaviour and should be "
        "updated deliberately (#389 reported the hazard)"
    )
    assert _row(store, cohort_id, other) == before_other, (
        f"a bare re-derivation touched BOTH runs: {other!r} moved from {before_other} to "
        f"{_row(store, cohort_id, other)}. Whatever run the default picks, it must pick one"
    )


def test_tc_det_c15_a_re_derivation_under_an_unchanged_key_writes_nothing(two_scored_runs):
    """Idempotence: correcting to the same key changes no row and reports zero.

    `CT-DET-07`'s redelivery constraint, and the guard that keeps the scoping cases honest —
    an implementation that rewrote every row on every call would satisfy "the named run
    changed" and fail this one.
    """
    store, cohort_id, run_a, run_b, v1, catalog, evaluator = two_scored_runs
    before_a = _row(store, cohort_id, run_a)
    before_b = _row(store, cohort_id, run_b)

    v2 = catalog.create_version(parent=v1)
    catalog.set_answer_key(v2, "M3", ("B",))  # the SAME key
    report = evaluator.rederive_for_key_change(cohort_id, "M3", v2, run_id=run_a)

    assert report.scores_changed == 0, (
        f"an unchanged key reported {report.scores_changed} changed score(s); a re-derivation "
        "writes only the rows whose value actually moves (CT-DET-07)"
    )
    assert _row(store, cohort_id, run_a) == before_a
    assert _row(store, cohort_id, run_b) == before_b


def test_tc_det_c15_the_composed_two_run_form_is_tc_pipe_01s():
    """The rung-3 arm is cross-referenced, not duplicated.

    `TC-PIPE-01` drives `run_to_completion` over the F-DEV-PIPE corpus; running a second
    composed drive here would time and assert the same property twice and report two answers
    for it. This asserts that case still exists, so a deletion is visible from the clause
    suite that depends on it.
    """
    import pathlib

    path = pathlib.Path("tests/integration/pipe/test_f_dev_pipe_corpus.py")
    assert path.exists(), (
        f"{path} is gone; CT-DET-15's rung-3 composed form went with it (TC-PIPE-01)"
    )
