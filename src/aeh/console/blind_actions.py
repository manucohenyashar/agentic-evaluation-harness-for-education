"""The blind sample as the console serves it (FR-CONSOLE-81/82/83, #882): the sample offered
first, the seats read, the draft, Finish and Skip actions, and the administration promoted when
the draw closes.

M-REVIEW owns the draw (FR-REVIEW-26/27/30); M-PIPE owns promotion (FR-PIPE-21). This module
only composes them: every write here goes through `ReviewService` or `promote_administration`,
and the console computes no statistic.

**When the draw opens.** A run's draw opens the first time the teacher is shown that the run
finished (the Monitor's completion outcome) or opens the sample itself (the seats read), and
only for a `complete` run. Batch finalization never opens or closes it (FR-REVIEW-30), and the
headless pipeline leaves it `not_offered_yet` (FR-PIPE-20), so a run graded outside the console
draws when its teacher first comes to it. The Results reads never open a draw: they hold back
the drawn lines of a draw that is already open (`held_back`).
"""

from __future__ import annotations

import re
from typing import Any

from aeh.review import REVIEW_BLIND_N

from .settings import blind_reserve_minutes

#: The draw states, as M-REVIEW names them (FR-REVIEW-30).
DRAW_NOT_DRAWN = "not_drawn"
DRAW_OPEN = "open"
DRAW_CLOSED_BY_WINDOW = "closed_by_window"

#: FR-CONSOLE-81's reply to a Skip, verbatim.
SKIPPED_REPLY = (
    "Skipped. Every mark stays as it is; the only cost is no new evidence about how accurate "
    "the marking is."
)

#: The completion outcome's two choices (FR-CONSOLE-82): the blind sample first, the results as
#: the second, equally available choice.
BLIND_SAMPLE_NEXT = {"label": "Mark the sample", "route": "/review/blind"}
RESULTS_NEXT = {"label": "See the results", "route": "/results"}


def run_start_sample_sentence(n: int | None = None, minutes: int | None = None) -> str:
    """FR-CONSOLE-82's run-start sentence: `n` is the draw size (`REVIEW_BLIND_N`, the size
    M-REVIEW draws), `m` the time the review budget reserves for the sample
    (`reserved_for_blind_minutes`)."""
    count = REVIEW_BLIND_N if n is None else int(n)
    reserved = blind_reserve_minutes() if minutes is None else int(minutes)
    return (
        f"When marking finishes you'll be asked to mark about {count} answers yourself, "
        f"without seeing the system's marks (about {reserved} minutes). It's optional; your "
        "class is graded either way."
    )


def completion_next() -> list[dict[str, str]]:
    """The completion outcome's `next`: the blind sample, then the results."""
    return [dict(BLIND_SAMPLE_NEXT), dict(RESULTS_NEXT)]


# --- the draw -------------------------------------------------------------------------------


def _run_status(app: Any, run_id: str) -> str | None:
    row = app._run_row(run_id)
    return None if row is None else str(row["status"] or "")


def _promote(app: Any, run_id: str, trigger: str) -> Any:
    """FR-PIPE-21: promote the run's administration after its draw closed. Imported from the
    composition root's package, which the console already reaches (CT-CONSOLE-36)."""
    from aeh.pipeline import promote_administration

    return promote_administration(app._store, run_id, trigger)


def settle_draw(app: Any, run_id: str, service: Any = None, *, open_if_complete: bool = False
                ) -> tuple[Any, str]:
    """The run's review service and its draw state, settled.

    Reading the state settles a lapsed review window in M-REVIEW (the drafted seats become
    labels); a draw the window closed is then promoted here, `window_lapse`, once
    (`promote_administration` promotes an administration exactly once). With
    `open_if_complete`, a `complete` run that has not drawn draws now — the sample is offered
    first (ADR-58). Returns `(None, "not_drawn")` when M-REVIEW cannot open the run."""
    service = service if service is not None else app._review_service(run_id)
    if service is None:
        return None, DRAW_NOT_DRAWN
    state = service.draw_state(run_id)
    if state == DRAW_NOT_DRAWN and open_if_complete and _run_status(app, run_id) == "complete":
        try:
            service.blind_sample(run_id)
        except Exception:  # noqa: BLE001 — nothing to draw yet stays `not_drawn`
            pass
        state = service.draw_state(run_id)
    if state == DRAW_CLOSED_BY_WINDOW:
        try:
            _promote(app, run_id, "window_lapse")
        except Exception:  # noqa: BLE001 — `recover` promotes it at the next start
            pass
    return service, state


def blind_seats_payload(app: Any, run_id: str) -> dict[str, Any]:
    """`GET /api/v1/blind-seats` (FR-CONSOLE-83): M-REVIEW's seats, each with exactly
    `BLIND_SEAT_KEYS` (the seat's identity, the answer and its pages, the bands with their
    descriptors, the draft), the draw's state and `progress: {marked, total}`. Nothing derived
    from grading crosses: the seats are M-REVIEW's, which never read a score (CT-REVIEW-09)."""
    service, state = settle_draw(app, run_id, open_if_complete=True)
    if service is None:
        raise ValueError(f"M-REVIEW cannot open run {run_id!r}")
    seats = [dict(seat) for seat in service.blind_seats(run_id)]
    marked = sum(1 for seat in seats if seat.get("draft_band"))
    return {
        "run_id": run_id,
        "state": state,
        "seats": seats,
        "progress": {"marked": marked, "total": len(seats)},
    }


# --- the three actions ----------------------------------------------------------------------

#: An action's outcome: the rows it wrote (the label ids for Finish), the teacher's sentence,
#: whether it ran, and whether it was refused.
BlindOutcome = tuple[tuple[Any, ...], str, bool, bool]


def _refused(why: str) -> BlindOutcome:
    return (), why, False, True


#: What M-REVIEW's refusals carry that is not teacher text: a requirement id in parentheses,
#: the run's id, and the code-voice tail after a colon (FR-UI-23).
_REQUIREMENT_ID = re.compile(r"\s*\((?:FR|NFR|CT)-[A-Z]+-\d+[^)]*\)")
_RUN_NAMED = re.compile(r"run '[^']*'('s)?")
_CRITERION_NAMED = re.compile(r"(?:of )?criterion '[^']*'")


def _teacher_reason(exc: Exception) -> str:
    """M-REVIEW's refusal in teacher words: the requirement ids dropped, the run named as
    "this test run", and only its first clause kept."""
    text = _REQUIREMENT_ID.sub("", str(exc))
    text = _RUN_NAMED.sub(lambda m: "this test run" + ("'s" if m.group(1) else ""), text)
    text = _CRITERION_NAMED.sub("for this question", text)
    first = text.split(": ", 1)[0].strip().rstrip(".")
    return (first[:1].upper() + first[1:] + ".") if first else "It was refused."


def _service_for(app: Any, params: dict[str, Any]) -> tuple[str, Any]:
    run_id = str(params.get("run_id") or "")
    if not run_id:
        return run_id, None
    service, _state = settle_draw(app, run_id)
    return run_id, service


def draft_effect(app: Any, params: dict[str, Any]) -> BlindOutcome:
    """`blind-sample draft` (seat, band): store the teacher's band for one seat as a draft
    (FR-REVIEW-26). No label is written until the sample is finished."""
    seat_id = str(params.get("seat_id") or "")
    band = str(params.get("band") or "")
    if not params.get("run_id") or not seat_id or not band:
        return _refused("The mark names no test run, answer or level, so nothing was saved.")
    run_id, service = _service_for(app, params)
    if service is None:
        return _refused("This test run could not be opened, so nothing was saved.")
    try:
        service.draft_blind(run_id, seat_id, band)
    except Exception as exc:  # noqa: BLE001 — M-REVIEW's refusal is the honest outcome
        return _refused(f"The mark was not saved. {_teacher_reason(exc)}")
    return (), f"Saved your mark ({band}). It counts when you finish the sample.", True, False


def finish_effect(app: Any, params: dict[str, Any]) -> BlindOutcome:
    """`blind-sample finish` (run): one blind label per drafted seat, the draw closed
    (FR-REVIEW-26), then the administration promoted (`finish`, FR-PIPE-21). The rows written
    are the labels, so the outcome's count is the labels' (FR-CONSOLE-89, SV-15)."""
    run_id, service = _service_for(app, params)
    if not run_id:
        return _refused("Finish names no test run, so nothing was recorded.")
    if service is None:
        return _refused("This test run could not be opened, so nothing was recorded.")
    try:
        report = service.finish_blind(run_id)
    except Exception as exc:  # noqa: BLE001 — M-REVIEW's refusal is the honest outcome
        return _refused(f"The sample was not finished. {_teacher_reason(exc)}")
    promoted = _promote_after_close(app, run_id, "finish")
    labels = tuple(report.label_ids)
    unmarked = int(report.unmarked_count or 0)
    detail = (f"Finished. {len(labels)} of your marks "
              f"{'was' if len(labels) == 1 else 'were'} recorded")
    if unmarked:
        detail += (f"; {unmarked} {'answer was' if unmarked == 1 else 'answers were'} "
                   "left unmarked.")
    else:
        detail += "."
    if promoted:
        detail += f" {promoted}"
    return labels, detail, True, False


def skip_effect(app: Any, params: dict[str, Any]) -> BlindOutcome:
    """`blind-sample skip` (run): M-REVIEW's `skip_blind_sample` (from not drawn or open; the
    drafts are discarded), then the administration promoted (`skip`), which is what records the
    skipped administration the repeated-skip alert counts (FR-CONSOLE-81)."""
    run_id, service = _service_for(app, params)
    if not run_id:
        return _refused("Skip names no test run, so nothing was recorded.")
    if service is None:
        return _refused("This test run could not be opened, so nothing was recorded.")
    try:
        service.skip_blind_sample(run_id)
    except Exception as exc:  # noqa: BLE001 — M-REVIEW's refusal is the honest outcome
        return _refused(f"The sample was not skipped. {_teacher_reason(exc)}")
    promoted = _promote_after_close(app, run_id, "skip")
    return (), SKIPPED_REPLY if not promoted else f"{SKIPPED_REPLY} {promoted}", True, False


def _promote_after_close(app: Any, run_id: str, trigger: str) -> str:
    """Promote after M-REVIEW closed the draw. The close stands whatever promotion says, so a
    failed promotion is reported (and `recover` promotes it at the next start), never raised:
    returns "" when promotion ran or had nothing to do, else the sentence to add."""
    try:
        _promote(app, run_id, trigger)
    except Exception:  # noqa: BLE001 — the close is recorded; recovery promotes later
        return ("The comparison with the system's marks could not be worked out yet; it is "
                "worked out the next time the system starts.")
    return ""


#: The blind actions, by name (FR-CONSOLE-81/83).
BLIND_ACTION_EFFECTS = {
    "blind-sample draft": draft_effect,
    "blind-sample finish": finish_effect,
    "blind-sample skip": skip_effect,
}
