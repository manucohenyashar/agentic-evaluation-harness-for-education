"""`TC-REVIEW-36`: label ids are unique across store-backed review services.

A regression case for a defect #398 exposed (CLAUDE.md's defect-fix exception; added to
`docs/design/closeout_test_plan.md` in the same change). `ReviewService` minted label ids
from a per-instance counter (`label-0001`, `label-0002`, …). The console builds a fresh
service for every request, so the second request's first label reused `label-0001` and
the durable insert failed on `label.label_id`'s primary key: the teacher's second action
of the day was refused.

The oracle is the durable table. Two services over the same store, opened one after the
other, each record a label, and both rows land with different ids.
"""

from __future__ import annotations

import pytest

from aeh.review import review_service_over
from aeh.store import open_store
from tests.support.console_world import OPEN_CRITERIA, rows, seed_scored_run
from tests.support.grade_vocabulary import write_criterion_scores

pytestmark = pytest.mark.integration


def _queued_world(store):
    world = seed_scored_run(store, choices=[("A", "B", "C"), ("A", "D", "C")], submissions=2,
                            with_open_criteria=True)
    cohort = store.cohort(world.cohort_id)
    write_criterion_scores(cohort, [(s, c, "B2", 2.0, "auto") for s in world.submissions
                                    for c, _ in OPEN_CRITERIA])
    with cohort.transaction() as tx:
        tx.execute("UPDATE criterion_score SET routing = 'queued', "
                   "state = 'provisional_unreviewed', judge_count = 3")
    return world


def test_tc_review_36_two_services_over_one_store_mint_distinct_label_ids(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        world = _queued_world(store)
        criterion = OPEN_CRITERIA[0][0]
        written = []
        for submission in world.submissions:
            # A fresh service per action, the way every console request builds one.
            service = review_service_over(store, cohort_ids=[world.cohort_id],
                                          run_id=world.run_id)
            item = next(i for i in service.rank_queue_items(world.run_id)
                        if i.submission_id == submission and i.criterion_id == criterion)
            written.append(service.act(item, "edit", new_band="B3"))
        stored = [r["label_id"] for r in rows(store.durable(), "SELECT label_id FROM label")]
        assert len(set(written)) == 2, (
            f"two services minted {written}: a per-instance counter reuses the first id, and "
            "the second service's label collides with the first one's durable row"
        )
        assert sorted(stored) == sorted(written), (
            f"the label table holds {stored}, expected both labels {written}"
        )
    finally:
        store.close()
