"""The review queue's group action (FR-CONSOLE-92, CT-REVIEW-13/15; #868).

`review group action` (`run_id`, `group_signature`, `band` or `decision`) applies one level
to a group the queue showed. M-REVIEW's `act_on_group` writes one label per member, each
`accept` or `edit` by that member's own proposed level (CT-REVIEW-13). The group is the one the
teacher saw: `group_signature` records each member as shown with its revision, so a member
whose score changed since (an escalation re-scored it, CT-REVIEW-15) or that has left the group
is refused by name — M-REVIEW's stale check decides, never the console — and the rest are
marked. `decision = 'skip'` writes nothing: the answers stay provisional and in the queue
(FR-REVIEW-08).
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from aeh.review import REVIEW_DEFAULT_BUDGET_MINUTES

from .review_reads import decode_group_signature, same_signature, student_name


def _names(app: Any, run_id: str, submission_ids: list[str]) -> str:
    named = [student_name(app, run_id, submission_id) for submission_id in submission_ids]
    if len(named) == 1:
        return named[0]
    return ", ".join(named[:-1]) + " and " + named[-1]


def _current_members(service: Any, run_id: str, built: Any, wanted: dict[str, Any]
                     ) -> dict[str, Any]:
    """Each answer of the shown group as it now stands, by submission. Read from the group when
    it still exists, else from every item the queue still admits (a two-member group whose
    other member changed is no group any more, and the unchanged one is still the teacher's
    to mark). An answer that left the queue, was drawn since, or now carries another proposed
    level is not here: it has changed."""
    group = next((g for g in built.groups if same_signature(g, wanted)), None)
    if group is not None:
        candidates = list(group.members)
    else:
        held_out = service.held_out_cells(run_id)
        candidates = [item for item in service.rank_queue_items(run_id)
                      if (str(item.submission_id), str(item.criterion_id)) not in held_out]
    proposed = str(wanted["signature"].get("proposed_band"))
    return {str(item.submission_id): item for item in candidates
            if str(item.criterion_id) == wanted["criterion_id"]
            and str(item.proposed_band) == proposed}


def review_group_effect(app: Any, params: dict[str, Any]) -> tuple[str, bool]:
    """Apply one decision to a shown group. Returns the outcome sentence and whether anything
    was marked (a refusal marks nothing)."""
    run_id = str(params.get("run_id") or "")
    token = str(params.get("group_signature") or "")
    decision = str(params.get("decision") or "").strip().lower()
    band = params.get("band", params.get("new_band"))
    if not run_id or not token:
        return ("The group action names no run or no group, so nothing was marked.", False)
    try:
        wanted = decode_group_signature(token)
    except ValueError as exc:
        return (f"{exc}, so nothing was marked; refresh the review queue.", False)
    shown = wanted["members"]
    if decision == "skip":
        return (f"Skipped for now: these {len(shown)} answers stay provisional and in your "
                "review queue.", True)
    if decision in ("", "accept") and band in (None, ""):
        band = wanted["signature"].get("proposed_band")
    if band in (None, ""):
        return ("The group action names no level, so nothing was marked.", False)
    band = str(band)
    service = app._review_service(run_id)
    if service is None:
        return ("The review queue for this run could not be opened, so nothing was marked.",
                False)
    built = service.build_queue(run_id, int(REVIEW_DEFAULT_BUDGET_MINUTES), record=False)
    current = _current_members(service, run_id, built, wanted)
    fresh, refused = [], []
    for submission_id, revision in shown:
        member = current.get(submission_id)
        as_shown = replace(member, version=revision) if member is not None else None
        if as_shown is None or service.is_stale(as_shown):
            refused.append(submission_id)
        else:
            fresh.append(as_shown)
    refused_sentence = ""
    if refused:
        one = len(refused) == 1
        refused_sentence = (
            f" {_names(app, run_id, refused)} {'has' if one else 'have'} changed since you "
            f"opened the queue, so {'that answer was' if one else 'those answers were'} not "
            f"marked; refresh the queue to see {'it' if one else 'them'} again.")
    if not fresh:
        return ("Nothing was marked." + refused_sentence, False)
    try:
        label_ids = service.act_on_group(SimpleNamespace(members=tuple(fresh)), band)
    except Exception:  # noqa: BLE001 — a refusal is the honest outcome
        # `act_on_group` writes member by member, so a failure part-way may follow labels
        # already recorded: the sentence does not claim that nothing was.
        return (f"The group could not be marked {band}; some of these answers may already be "
                "recorded. Refresh the review queue to see which are still waiting.", False)
    count = len(label_ids)
    return (f"{count} {'answer' if count == 1 else 'answers'} marked {band} as one decision; "
            "each is recorded on its own." + refused_sentence, True)
