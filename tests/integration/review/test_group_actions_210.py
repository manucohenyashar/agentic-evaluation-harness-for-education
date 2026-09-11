"""`TC-REVIEW-08` and `TC-REVIEW-22` — one group over 210, and 210 labels from one action.

Test plan §5.15, issue #112 (TS-40). Traces to `FR-REVIEW-05`.

`TC-REVIEW-08`: *"210 submissions sharing an identical band-plus-integrity-signature on one
criterion. One group item with an apply-to-group action, ranked above per-item entries; not 210
separate items."* — exact value, P1. `TC-REVIEW-22`: *"A group action over 210 items. Emits 210
labels, one per underlying item, each with the group action recorded — so a group action is not
one label standing for 210."* — exact row count, P0.

`CT-REVIEW-13` (`tests/contract/review/test_ct_review_labels_and_edits.py`) holds the clause
limbs at the 12-member scale: one label per member, indistinguishability against N individual
actions, and group-ranks-above with per-item entries carrying a *higher* expected value. This
file implements the two cases at their pinned 210 scale over the store path, which nothing
shipped carries: the count is the defect (`210 labels, not 1`), and a passing 12-member count
does not certify the 210-member one — a `batch()` misreading, a limit in a read path, or a
per-member write that degrades to a bulk write at scale are all invisible below the figure the
plan pinned.

**Disclosed at the load (the rung-2 EV vacuity, as in this suite's `TC-REVIEW-01` file):** the
store's `criterion_score` carries none of `FR-REVIEW-03`'s seven inputs, so every rung-2 row
scores expected value 0.0. The ranked-above limb here therefore exercises `FR-REVIEW-05`'s fill
rule — groups first in entry order, always — and not EV dominance over a higher-value per-item
entry; that differential is `CT-REVIEW-C13`'s rung-0 case. Everything else here is the plan's
own arithmetic: one signature collapses 210 rows, one decision covers them, and the label store
gains 210 rows.

**Isolation:** rung 2 — real store, real cohort ledger, no model.
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support import review_vocabulary as vocab
from tests.support.grade_vocabulary import write_criterion_scores
from tests.support.impl import REVIEW_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration]

#: §5.15's fixture figures: the group's 210 identical-signature submissions plus 10 rows whose
#: bands differ, so the queue holds one group and ten per-item entries over one criterion.
GROUP_MEMBERS = 210
PER_ITEM_ROWS = 10

#: The group's shared band. Every group member carries it, so the signature — band plus the
#: four integrity signals, `CT-REVIEW-20`'s exact Phase 1 rule — is one key over all 210.
GROUP_BAND = "B2"
#: The band the group action applies, deliberately *not* the proposed band: the action is an
#: edit, and the labels must say so (`act_on_group`'s action derivation).
APPLIED_BAND = "B4"

#: A budget whose spendable window (12 − 10 reserved = 2 minutes = 120s) fits the group (60s)
#: and exactly one more item, and a budget (30 minutes, 1200s) that fits everything. The pair
#: separates "the group is taken first" from "the budget happened to be big".
MID_BUDGET_MINUTES = 12
FULL_BUDGET_MINUTES = 30


def _seed_and_open(tmp_data_dir):
    """The 220-row cohort: 210 group members, 10 per-item entries, one criterion."""
    open_review = require(REVIEW_MODULE, "open_review", issue="#111")

    store = open_store(tmp_data_dir)
    try:
        _orchestrator, _run_id, _version = seed_run(
            store,
            submissions=tuple(f"S{i:03d}" for i in range(GROUP_MEMBERS + PER_ITEM_ROWS)),
            criteria=({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},),
        )
        cohort = store.cohort(ORCH_COHORT_ID)
        rows = [
            # The stand-in seeds `provisional` rather than `queued` — the disclosed mapping
            # (`ROUTING_TO_STATE`) derives `provisional_unreviewed` from it, and both are the
            # queue's admitted population. Identical bands give the 210 one signature.
            (f"S{i:03d}", "C1", GROUP_BAND, 6.0, "provisional")
            for i in range(GROUP_MEMBERS)
        ]
        rows.extend(
            (f"S{GROUP_MEMBERS + i:03d}", "C1", f"B{300 + i:03d}", 6.0, "provisional")
            for i in range(PER_ITEM_ROWS)
        )
        write_criterion_scores(cohort, rows)
        return open_review(tmp_data_dir, run_id=ORCH_COHORT_ID)
    finally:
        store.close()


def test_tc_review_08_210_identical_signatures_form_one_group_ranked_first(tmp_data_dir):
    """One group item — not 210 separate items — and it is shown before any per-item entry.

    The exact figures the plan pins: one group of 210 members among the shown entries, ten
    per-item entries behind it, and the header arithmetic reconciling with the group counted by
    its members — one decision covering 210 items is shown as one entry and *counted* as 210
    (`vocab.items_shown`), which is what keeps the residual honest.
    """
    service = _seed_and_open(tmp_data_dir)
    try:
        queue = service.build_queue(run_id=ORCH_COHORT_ID, budget_minutes=FULL_BUDGET_MINUTES)

        groups = [entry for entry in queue.shown if not hasattr(entry, "score_id")]
        assert len(groups) == 1, (
            f"210 identical-signature rows formed {len(groups)} groups. TC-REVIEW-08: one "
            "group item with an apply-to-group action — a queue that splits them back into "
            "per-item entries is the 210-item queue this case exists to prevent."
        )
        group = groups[0]
        assert len(group.members) == GROUP_MEMBERS, (
            f"the group holds {len(group.members)} members against the fixture's "
            f"{GROUP_MEMBERS} identical-signature rows"
        )
        assert len(queue.shown) == 1 + PER_ITEM_ROWS, (
            f"the queue showed {len(queue.shown)} entries; one group plus ten per-item entries "
            "is eleven — 220 separate items is TC-REVIEW-08's named failure"
        )

        assert queue.shown[0] is group, (
            "the group did not rank above the per-item entries. FR-REVIEW-05: a group ranks "
            "above per-item entries whenever one exists — one decision resolves 210 items, "
            "which no per-item expected value expresses."
        )

        assert queue.flagged_total == GROUP_MEMBERS + PER_ITEM_ROWS
        assert vocab.items_shown(queue) == GROUP_MEMBERS + PER_ITEM_ROWS, (
            "the shown count did not treat the group as its 210 members, so the header's "
            "figures count one decision as one item and the residual overstates what is left"
        )
        assert queue.residual_provisional == 0, (
            f"a budget that fits every entry left a residual of "
            f"{queue.residual_provisional} — the three figures do not reconcile"
        )

        mid = service.build_queue(run_id=ORCH_COHORT_ID, budget_minutes=MID_BUDGET_MINUTES)
        mid_groups = [entry for entry in mid.shown if not hasattr(entry, "score_id")]
        mid_items = [entry for entry in mid.shown if hasattr(entry, "score_id")]
        assert mid_groups and mid_groups[0].members[0].score_id in {
            member.score_id for member in group.members
        }, "the smaller budget dropped the group before its per-item entries"
        assert len(mid_items) == 1, (
            f"at {MID_BUDGET_MINUTES} minutes (120s spendable) the queue showed "
            f"{len(mid_items)} per-item entries after the group's 60s — the fill is not the "
            "greedy take-what-fits pass over the group-first order"
        )
        assert vocab.items_shown(mid) == GROUP_MEMBERS + 1 and mid.residual_provisional == (
            GROUP_MEMBERS + PER_ITEM_ROWS - (GROUP_MEMBERS + 1)
        ), (
            "the mid-budget header does not count the group by its members: one decision "
            "covers 210 items and the residual must state what actually remains"
        )
    finally:
        service.close()


def test_tc_review_22_a_group_action_over_210_emits_exactly_210_labels(tmp_data_dir):
    """One action, 210 labels — each naming its own member, each marked as a group action.

    *"So a group action is not one label standing for 210."* The exact row count is the oracle
    (`TC-REVIEW-22`'s declared oracle: *exact row count*), then the per-member identity — a
    bulk write that emitted 210 copies of one label would satisfy every count and still not say
    which 210 submissions the teacher judged. `review_seconds` is shared per member: 210 seconds
    over 210 members is 1.0 each, the honest per-member share.
    """
    service = _seed_and_open(tmp_data_dir)
    try:
        queue = service.build_queue(run_id=ORCH_COHORT_ID, budget_minutes=FULL_BUDGET_MINUTES)
        groups = [entry for entry in queue.shown if not hasattr(entry, "score_id")]
        assert groups, "no group formed at the pinned scale, so this case asserts nothing"
        group = groups[0]
        member_ids = {member.score_id for member in group.members}

        label_ids = service.act_on_group(group, band=APPLIED_BAND, review_seconds=GROUP_MEMBERS)
        assert len(label_ids) == GROUP_MEMBERS * vocab.GROUP_LABELS_PER_MEMBER, (
            f"a group action over {GROUP_MEMBERS} members wrote {len(label_ids)} labels. "
            "TC-REVIEW-22: 210, one per underlying item — a single label weights a bulk "
            "decision as one observation in every agreement figure the judgement feeds."
        )
        assert len(set(label_ids)) == len(label_ids), (
            "the group action returned duplicate label ids, so 210 labels does not mean 210 "
            "distinct records"
        )

        labels = [service.label(label_id) for label_id in label_ids]
        assert {label.score_id for label in labels} == member_ids, (
            "the labels do not identify the 210 scores the group decision was about — 210 "
            "identical rows are indistinguishable from one row written 210 times"
        )
        for label in labels:
            assert label.teacher_band == APPLIED_BAND, (
                f"a group label recorded teacher band {label.teacher_band!r} against the band "
                f"the action applied ({APPLIED_BAND!r})"
            )
            assert label.review_queue_action == "edit", (
                f"a group action applying a band other than the proposed one recorded action "
                f"{label.review_queue_action!r} — one band decision over the group is an edit "
                "everywhere the decision is read back"
            )
            assert label.via_group is True, (
                "a label from a group action does not record that it came from one. The "
                "group-action share of the session's actions is computed from this flag; a "
                "label missing it makes bulk review statistically invisible."
            )
            assert label.review_seconds == pytest.approx(1.0), (
                f"a group label carries review_seconds {label.review_seconds!r}; 210 seconds "
                "shared per member over 210 members is 1.0 each — the honest per-member share, "
                "not the group's total booked onto every row."
            )
    finally:
        service.close()