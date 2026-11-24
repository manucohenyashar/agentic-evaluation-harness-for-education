"""The blind sample (bands given without seeing the system's) and the whole-grade sample.

The blind draw has a state (FR-REVIEW-30): `not_drawn`, `open`, `finished`, `skipped` or
`closed_by_window`. A draw opens once per run and, over a store, is stored with its seats and
each seat's routing at draw time (cohort migration 37, `review_blind_draw`), so every console
request reads the same seats. The teacher's band per seat is a draft, changeable until the
draw closes (FR-REVIEW-26); the draw closes only by Finish, Skip or the lapse of the review
window, which is noticed lazily at the next read or action on the run, the way grade
settlement is. Batch finalization and run completion never touch it.
"""

from __future__ import annotations

import json
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Mapping

from .settings import (
    BLIND_SAMPLE_RANGE,
    REVIEW_DEFAULT_BANDS,
    WHOLE_GRADE_DECISIONS,
    WHOLE_GRADE_SAMPLE_RANGE,
)
from .errors import LabelProvenanceError, ReviewError
from .schema import BLIND_DRAW_STATEMENTS, REVIEW_STATEMENTS
from .records import (
    BlindCloseReport,
    BlindItem,
    BlindSampleSkipReport,
    BlindSession,
    DRAW_CLOSED_BY_WINDOW,
    DRAW_FINISHED,
    DRAW_NOT_DRAWN,
    DRAW_OPEN,
    DRAW_SKIPPED,
    DRAW_TRANSITIONS,
    DrawRecord,
    LabelRecord,
    SubmissionGrade,
    WriteRecord,
)
from .stored_rows import _newest_run_id, _row_mapping


@dataclass
class _Draw:
    """One run's blind draw as the service holds it while acting on it: the stored row, its
    seats in seat order, and the teacher's drafts by (submission, criterion). Draw-time routing
    is read separately, only when labels are written."""

    run_id: str
    state: str
    opened_at: str | None = None
    window_hours: float | None = None
    seats: tuple[BlindItem, ...] = ()
    drafts: dict[tuple[str, str], str] = field(default_factory=dict)
    routing: dict[tuple[str, str], str] = field(default_factory=dict)
    session_id: str | None = None
    closed_at: str | None = None
    labels_written: int = 0
    unmarked_count: int = 0
    absence_reason: str | None = None


class _CloseLost(ReviewError):
    """Another request closed the stored draw first; this close wrote nothing."""


def _instant(raw: Any) -> datetime | None:
    """An ISO-8601 instant as an aware datetime (naive read as UTC), or None when unreadable."""
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _cell(ref: BlindItem) -> tuple[str, str]:
    return (ref.submission_id, ref.criterion_id)


class BlindSamplingMixin:
    """Draws and collects the blind sample and the whole-grade sample."""

    #: The configured review window in hours, when the caller sets one. None reads the run's
    #: package grade policy (`review_window_hours`, FR-GRADE-10) at draw time; a window of
    #: None or 0 never lapses.
    _review_window_hours: float | None = None

    # -- the two samples, and the skip (#111) ---------------------------------------------------------

    def _rng(self, draw_index: int) -> random.Random:
        """The random generator for one draw, derived from the service's seed and the draw number:
        the same seed repeats the same sequence of draws, while successive draws on one service
        differ (CT-REVIEW-11). A seed of None gives fresh randomness per draw, so an undeclared
        seed never fixes every administration to the same sample."""
        if self._seed is None:
            return random.Random()
        # A str seed, not a tuple: Random() accepts only None/int/float/str/
        # bytes/bytearray, and str's version-2 seeding is a sha512 digest, so
        # the derived seed is deterministic across processes, not hash-ordered.
        return random.Random(f"{self._seed}:{draw_index}")

    def blind_sample(self, run_id: str = "run-1", n: int | None = None) -> BlindSession:
        """Draw the blind sample (FR-REVIEW-12): 15 to 25 judged references, chosen uniformly at
        random from the eligible judged population, reproducible from the service's seed, never
        simply the first N (CT-REVIEW-11). A smaller pool gives a smaller draw; a size outside
        `BLIND_SAMPLE_RANGE` is refused, naming the range.

        The first draw opens the run's draw (FR-REVIEW-30). Over a store the draw is stored, and
        every later call, from this service or a fresh one, returns the same seats in the same
        order: the draw is made once, so the seat the teacher saw is the seat they mark. A
        storeless service re-draws while no seat is drafted (#111's repeated sittings).

        A run whose draw is closed refuses: a skipped run draws nothing, since a draw after a skip
        would make the skip's report false (FR-REVIEW-13), and after Finish or the window's lapse
        no route leads back into the draw (FR-REVIEW-26).

        The refs the session returns carry identity only — that is
        `CT-REVIEW-09`'s whole guarantee, so it is a property of the type
        rather than of the rendering."""
        count = self._blind_n if n is None else int(n)
        low, high = BLIND_SAMPLE_RANGE
        if count < low or count > high:
            raise ValueError(
                f"blind_sample draws {low}-{high} judged refs (FR-REVIEW-12), got n={count}: "
                "the range is the contract, and a draw outside it is refused rather than sized "
                "to whatever the caller asked for"
            )
        key = self._draw_key(run_id)
        draw = self._settled_draw(key, counter_run=run_id)
        state = draw.state if draw is not None else DRAW_NOT_DRAWN
        if state == DRAW_SKIPPED or run_id in self._skipped_runs:
            raise ReviewError(
                f"run {run_id!r} skipped its blind sample, so it does not draw one: "
                "a run either draws its sample or skips it. Drawing after a skip would make "
                "the skip's report — no new validation evidence — false, and the report is "
                "the clause's whole content (FR-REVIEW-13)"
            )
        if state in (DRAW_FINISHED, DRAW_CLOSED_BY_WINDOW):
            raise ReviewError(
                f"run {run_id!r}'s blind sample is closed ({state}): after Finish or the end "
                "of the review window no route leads back into the draw, and no mark can be "
                "changed (FR-REVIEW-26)"
            )
        if draw is not None and (self._store is not None or draw.drafts):
            self._blind_drawn.setdefault(run_id, len(draw.seats))
            return self._session_for(run_id, draw)
        pool: list[BlindItem] = []
        seen: set[tuple[str, str]] = set()
        for row in self._admitted_rows():
            ref = BlindItem(
                submission_id=str(getattr(row, "submission_id", "") or ""),
                criterion_id=str(getattr(row, "criterion_id", "") or ""),
                evaluation_mode=str(getattr(row, "evaluation_mode", "") or ""),
            )
            if _cell(ref) in seen:
                continue
            seen.add(_cell(ref))
            pool.append(ref)
        drawn = tuple(
            self._rng(len(self._blind_sessions)).sample(pool, min(count, len(pool)))
        )
        if not drawn and self._store is not None:
            # Nothing to mark yet (no judged cell is flagged): no draw is stored, so a later
            # call can still draw once there is something to draw from.
            return BlindSession(session_id=f"blind-{key}", run_id=run_id, items=())
        fresh = _Draw(
            run_id=key,
            state=DRAW_OPEN,
            opened_at=self._clock(),
            window_hours=self._window_hours_for(key),
            seats=drawn,
            # The routing each drawn cell had at draw time (FR-REVIEW-29), stored beside the
            # draw rather than in the session, so the session still carries identity only.
            routing={_cell(ref): self._routing_now(ref) for ref in drawn},
        )
        stored = self._store_new_draw(fresh)
        if stored is not fresh:
            # Another request opened the draw first: its seats are the draw.
            self._blind_drawn.setdefault(run_id, len(stored.seats))
            return self._session_for(run_id, stored)
        self._blind_drawn[run_id] = self._blind_drawn.get(run_id, 0) + len(drawn)
        return self._session_for(run_id, fresh)

    def draw_state(self, run_id: str = "run-1") -> str:
        """The run's draw state (FR-REVIEW-30): `not_drawn`, `open`, `finished`, `skipped` or
        `closed_by_window`. Reading it settles a lapsed review window first, so the answer is
        never an `open` that has already run out."""
        draw = self._settled_draw(self._draw_key(run_id), counter_run=run_id)
        if draw is None:
            return DRAW_SKIPPED if run_id in self._skipped_runs else DRAW_NOT_DRAWN
        return draw.state

    def draw_record(self, run_id: str = "run-1") -> DrawRecord:
        """The run's draw as stored (FR-REVIEW-30): its state and, once closed, what the close
        recorded. Reading it settles a lapsed review window first, exactly as `draw_state` does,
        so a lapsed draw reads `closed_by_window` with its labels written."""
        draw = self._settled_draw(self._draw_key(run_id), counter_run=run_id)
        if draw is None:
            if run_id in self._skipped_runs:
                return DrawRecord(run_id=run_id, state=DRAW_SKIPPED, absence_reason="skipped")
            return DrawRecord(run_id=run_id, state=DRAW_NOT_DRAWN)
        return DrawRecord(
            run_id=draw.run_id, state=draw.state, labels_written=draw.labels_written,
            unmarked_count=draw.unmarked_count, absence_reason=draw.absence_reason,
            closed_at=draw.closed_at,
        )

    def blind_draw_items(self, run_id: str = "run-1") -> tuple[BlindItem, ...]:
        """The run's drawn references in seat order, identity only, WITHOUT drawing: empty for
        a run with no draw (or a skip without one). A closed draw still answers its seats, so a
        screen can show what was marked."""
        draw = self._settled_draw(self._draw_key(run_id), counter_run=run_id)
        return draw.seats if draw is not None else ()

    def blind_seats(self, run_id: str = "run-1") -> tuple[dict[str, Any], ...]:
        """The run's blind seats in seat order (FR-REVIEW-27), each a mapping with exactly the
        keys of `BLIND_SEAT_KEYS`: `seat_id`, `student_name`, `question`, `criterion_id`,
        `answer_text` (the student's answer, the transcribed text of the question's region in
        the canonical document), `page_refs` (the scanned pages it is on), `bands` (the
        criterion's bands as `{name, descriptor}` in the package's order) and `draft_band`.

        Nothing derived from grading is read or carried: no band, points, confidence, routing,
        reason, narrative, flag, cited quote or extracted span. The reads touch the submission,
        the criterion and its band set, the canonical artifact and the draw's own tables, never
        `criterion_score`, `verdict` or `extraction` (CT-REVIEW-09). A run with no draw has no
        seats."""
        draw = self._settled_draw(self._draw_key(run_id), counter_run=run_id)
        if draw is None or not draw.seats:
            return ()
        context = self._seat_context(draw.run_id)
        return tuple(
            self._seat(number, ref, draw, context)
            for number, ref in enumerate(draw.seats, start=1)
        )

    def draft_blind(self, run_id: str, seat_id: Any, band: str) -> str:
        """Store the teacher's band for one seat as a draft (FR-REVIEW-26). A draft can be
        changed any number of times and survives leaving and returning; it becomes a blind label
        only when the draw closes. Refused, with nothing stored, when the draw is not open, when
        the seat is not in the draw, or when the band is not one the criterion declares.
        Returns the band stored."""
        key = self._draw_key(run_id)
        draw = self._settled_draw(key, counter_run=run_id)
        self._require_open(run_id, draw, "a draft")
        ref = self._seat_ref(draw, seat_id)
        chosen = str(band or "")
        self._check_band(ref, chosen)
        self._store_draft(draw, ref, chosen)
        return chosen

    def finish_blind(self, run_id: str = "run-1") -> BlindCloseReport:
        """Finish the blind sample (FR-REVIEW-26): one blind label per drafted seat, the draw
        closed as `finished`, and the unmarked seats counted. Finishing with no seat marked
        writes no label and records `absence_reason = 'none_marked'`. A draw that is not open
        refuses, so a second Finish writes nothing. The console calls promotion after this
        returns (FR-PIPE-21); M-REVIEW never calls M-STATS."""
        key = self._draw_key(run_id)
        draw = self._settled_draw(key, counter_run=run_id)
        if draw is not None and draw.state in (DRAW_FINISHED, DRAW_CLOSED_BY_WINDOW):
            # A system-band join the close could not finish is repaired here before the
            # second Finish is refused (#518's resubmit repair; idempotent).
            self._join_blind_system_bands(SimpleNamespace(run_id=draw.run_id))
        self._require_open(run_id, draw, "Finish")
        self._check_transition(draw.state, DRAW_FINISHED, run_id)
        return self._close_with_labels(draw, DRAW_FINISHED, counter_run=run_id)

    def submit_blind(
        self,
        session_id: str,
        bands: Mapping[BlindItem, str],
        *,
        interrupted: bool = False,
        review_seconds: float = 0,
    ) -> list[str]:
        """Record a whole blind sitting at once (FR-REVIEW-12, CT-REVIEW-15): the answered
        references are drafted and the draw is finished, so one `blind` label is written per
        answered reference, with `saw_system_output = 0` (the session could not reach the
        system's output), `system_band = None` at write time and no queue action. Nothing is
        written for unanswered references, and a reference the session never drew is refused.

        ``interrupted`` records that the sitting ended early; the labels
        written are the answered ones either way, which is the clause in both
        directions. The session submits once — a second submission is refused
        rather than double-written. Returns the label ids in the draw's seat
        order."""
        session = self._blind_sessions.get(session_id)
        if session is None:
            raise ReviewError(
                f"no blind session {session_id!r} in this service; the ids "
                "blind_sample() returned are the submission's ids"
            )
        if session_id in self._blind_submitted:
            # The sitting has ended; a join a first submit could not finish is repaired
            # here before the resubmit is refused (#518 review; idempotent).
            self._join_blind_system_bands(session)
            raise ReviewError(
                f"blind session {session_id!r} was already submitted: a sitting answers once, "
                "and a second submission would double-write the labels an agreement figure "
                "counts"
            )
        drawn = set(session.items)
        unknown = [ref for ref in bands if ref not in drawn]
        if unknown:
            raise ReviewError(
                f"the bands name a ref this session never drew ({unknown[0]!r}): "
                "submit_blind records the criteria the flow posed, and a ref outside the "
                "session is a judgement nobody was asked for"
            )
        key = self._draw_key(session.run_id)
        draw = self._settled_draw(key, counter_run=session.run_id)
        self._require_open(session.run_id, draw, "a blind submission")
        if tuple(session.items) != tuple(draw.seats):
            raise ReviewError(
                f"blind session {session_id!r} was replaced by a later draw for run "
                f"{session.run_id!r}; submit the current draw's session, so no answer is "
                "silently dropped"
            )
        answered = [
            (ref, str(band)) for ref in session.items if (band := bands.get(ref)) is not None
        ]
        # Every band is checked before the first draft lands, so a bad band stores nothing.
        for ref, band in answered:
            self._check_band(ref, band)
        for ref, band in answered:
            self._store_draft(draw, ref, band)
        report = self._close_with_labels(
            draw, DRAW_FINISHED, counter_run=session.run_id,
            interrupted=interrupted, review_seconds=review_seconds,
        )
        self._blind_submitted.add(session_id)
        return list(report.label_ids)

    def whole_grade_sample(
        self, run_id: str = "run-1", n: int | None = None
    ) -> tuple[SubmissionGrade, ...]:
        """Draw the whole-grade sample (FR-REVIEW-14): 10 to 15 complete final grades, each as the
        student would receive it, from submissions where every criterion was auto-accepted.
        Sampling reviewed grades would measure the review rather than the system, so any submission
        with a reviewed criterion is left out (CT-REVIEW-11). Bands map to points through the one
        pinned mapping. The sample writes no label; a size outside `WHOLE_GRADE_SAMPLE_RANGE` is
        refused."""
        count = self._whole_grade_n if n is None else int(n)
        low, high = WHOLE_GRADE_SAMPLE_RANGE
        if count < low or count > high:
            raise ValueError(
                f"whole_grade_sample draws {low}-{high} complete grades (FR-REVIEW-14), got "
                f"n={count}: the range is the contract, refused rather than clamped"
            )
        by_submission: dict[str, list[tuple[str, str]]] = {}
        for submission_id, criterion_id, band in self._auto_grade_population():
            by_submission.setdefault(submission_id, []).append((criterion_id, band))
        candidates = list(by_submission)
        picked = self._rng(self._whole_grade_draws).sample(
            candidates, min(count, len(candidates))
        )
        self._whole_grade_draws += 1
        return tuple(
            SubmissionGrade(
                submission_id=submission_id,
                criterion_bands=dict(by_submission[submission_id]),
                points=float(sum(
                    self._points_for_band(criterion_id=criterion_id, band=band)
                    for criterion_id, band in by_submission[submission_id]
                )),
            )
            for submission_id in picked
        )

    def record_whole_grade_check(
        self, run_id: str, decision: str, submission_ids: tuple[str, ...] = ()
    ) -> str:
        """Record the teacher's answer to the whole-grade sample (FR-CONSOLE-93): `confirmed`
        (*these look like grades I would have given*) or `skipped`, as exactly one append-only
        `audit_record` row naming the run, the decision and the drawn submissions. No label is
        written: the sample checks the system end to end and is never validation evidence
        (FR-REVIEW-14). Returns the audit record id. Refused for any other decision, and on a
        storeless service (there is nowhere to record it)."""
        if decision not in WHOLE_GRADE_DECISIONS:
            raise ReviewError(
                f"the whole-grade sample is answered {' or '.join(WHOLE_GRADE_DECISIONS)}, "
                f"not {decision!r}")
        if self._store is None:
            raise ReviewError("a storeless review service cannot record the whole-grade answer")
        audit_record_id = uuid.uuid4().hex
        with self._store.durable().transaction() as tx:
            tx.execute(
                REVIEW_STATEMENTS["insert_whole_grade_audit_record"],
                audit_record_id=audit_record_id,
                run_id=run_id,
                recorded_at=self._clock(),
                profile_summary=json.dumps({
                    "event": "whole_grade_check",
                    "run_id": run_id,
                    "decision": decision,
                    "submissions": sorted(str(s) for s in submission_ids),
                }, sort_keys=True),
                decided_by=self._actor_name,
                evaluation_mode="judged",
            )
        return audit_record_id

    def skip_blind_sample(self, run_id: str = "run-1") -> BlindSampleSkipReport:
        """Record that this administration skips the blind sample (FR-REVIEW-13). The only
        consequence is that it adds no new validation evidence, and the report says so; grades are
        delivered and finalized as normal, and `current_figure` is None, never an earlier
        administration's figure. Skipping twice counts once.

        A skip closes the draw (FR-REVIEW-30): from `not_drawn`, or from `open`, whose drafts
        are discarded, because a skip records no evidence. A finished or window-closed draw
        refuses the skip: its labels are evidence, and a skip beside them would report "no new
        validation evidence" about a run that holds some."""
        key = self._draw_key(run_id)
        draw = self._settled_draw(key, counter_run=run_id)
        state = draw.state if draw is not None else DRAW_NOT_DRAWN
        if state != DRAW_SKIPPED and run_id not in self._skipped_runs:
            self._check_transition(state, DRAW_SKIPPED, run_id)
            closed_at = self._clock()
            if draw is None:
                draw = _Draw(run_id=key, state=DRAW_SKIPPED, closed_at=closed_at,
                             absence_reason="skipped")
                self._store_skip_without_draw(draw)
            elif not self._store_close(draw, DRAW_SKIPPED, closed_at=closed_at,
                                       labels_written=0, unmarked_count=0,
                                       absence_reason="skipped", discard_drafts=True):
                raise ReviewError(
                    f"run {run_id!r}'s blind sample was closed by another action while the "
                    "skip was being recorded; nothing was skipped"
                )
        self._skipped_runs.add(run_id)
        return self.skip_report(run_id)

    def skip_report(self, run_id: str = "run-1") -> BlindSampleSkipReport:
        """Whether the run's blind sample was skipped, the consequence in words, and
        `current_figure = None` whatever earlier administrations produced (FR-REVIEW-13)."""
        skipped = run_id in self._skipped_runs or self.draw_state(run_id) == DRAW_SKIPPED
        if skipped:
            message = (
                "the blind sample was skipped for this administration: no new "
                "validation evidence was collected, so this administration has "
                "no agreement figure of its own — grades deliver and finalize "
                "normally, and no earlier figure is presented in its place"
            )
        else:
            message = (
                "the blind sample was not skipped for this administration, so "
                "there is no absence to report; the run's own evidence speaks "
                "when it exists"
            )
        return BlindSampleSkipReport(reported=skipped, message=message, current_figure=None)

    # -- the draw's state, stored or held (#875) ------------------------------------------------------

    def _draw_key(self, run_id: str) -> str:
        """The run a draw is stored under: over a store, the run the service writes labels for
        (a caller that passes its cohort's id still reaches its run's draw, as the labels do);
        in memory, the run id given."""
        if self._store is not None:
            return str(self._attribution_run() or run_id)
        return run_id

    def _draw_cohort(self) -> Any:
        """The cohort file the draw is stored in: the one this service's run lives in."""
        cohort_id = self._writable_cohort()
        if cohort_id is None:
            raise ReviewError(
                "this service holds a store but no single cohort for its run, so the blind "
                "draw has nowhere to be kept: open the service for one run"
            )
        return self._store.cohort(cohort_id)

    def _load_draw(self, key: str) -> _Draw | None:
        """The run's draw as stored (or held, in memory), or None for `not_drawn`."""
        if self._store is None:
            return self._draws.get(key)
        handle = self._draw_cohort()
        rows = handle.query(BLIND_DRAW_STATEMENTS["select_draw"], run_id=key)
        if not rows:
            return None
        row = _row_mapping(rows[0])
        seats = tuple(
            BlindItem(
                submission_id=str(seat["submission_id"]),
                criterion_id=str(seat["criterion_id"]),
                evaluation_mode=str(seat["evaluation_mode"] or ""),
            )
            for seat in (
                _row_mapping(found)
                for found in handle.query(BLIND_DRAW_STATEMENTS["select_seats"], run_id=key)
            )
        )
        drafts = {
            (str(mapping["submission_id"]), str(mapping["criterion_id"])): str(mapping["band"])
            for mapping in (
                _row_mapping(found)
                for found in handle.query(BLIND_DRAW_STATEMENTS["select_drafts"], run_id=key)
            )
        }
        return _Draw(
            run_id=key,
            state=str(row["state"]),
            opened_at=row.get("opened_at"),
            window_hours=row.get("window_hours"),
            seats=seats,
            drafts=drafts,
            closed_at=row.get("closed_at"),
            labels_written=int(row.get("labels_written") or 0),
            unmarked_count=int(row.get("unmarked_count") or 0),
            absence_reason=row.get("absence_reason"),
        )

    def _draw_routing(self, draw: _Draw) -> dict[tuple[str, str], str]:
        """Each seat's routing at draw time (FR-REVIEW-29), read only to write the labels."""
        if self._store is None:
            return dict(draw.routing)
        return {
            (str(mapping["submission_id"]), str(mapping["criterion_id"])):
                str(mapping["draw_routing"])
            for mapping in (
                _row_mapping(found)
                for found in self._draw_cohort().query(
                    BLIND_DRAW_STATEMENTS["select_seat_routing"], run_id=draw.run_id)
            )
        }

    def _store_new_draw(self, draw: _Draw) -> _Draw:
        """Store a newly opened draw and its seats in one transaction. When another request
        opened the run's draw first, its draw is returned instead and nothing is written."""
        if self._store is None:
            self._draws[draw.run_id] = draw
            return draw
        handle = self._draw_cohort()
        try:
            with handle.transaction() as tx:
                tx.execute(
                    BLIND_DRAW_STATEMENTS["insert_draw"], run_id=draw.run_id, state=DRAW_OPEN,
                    opened_at=draw.opened_at, window_hours=draw.window_hours, closed_at=None,
                    absence_reason=None,
                )
                for number, ref in enumerate(draw.seats, start=1):
                    tx.execute(
                        BLIND_DRAW_STATEMENTS["insert_seat"], run_id=draw.run_id,
                        seat_no=number, submission_id=ref.submission_id,
                        criterion_id=ref.criterion_id, evaluation_mode=ref.evaluation_mode,
                        draw_routing=draw.routing.get(_cell(ref)) or "queued",
                    )
        except Exception:
            existing = self._load_draw(draw.run_id)
            if existing is None:
                raise
            return existing
        return draw

    def _store_skip_without_draw(self, draw: _Draw) -> None:
        """`not_drawn → skipped`: the skip's own row, with no seats."""
        if self._store is None:
            self._draws[draw.run_id] = draw
            return
        with self._draw_cohort().transaction() as tx:
            tx.execute(
                BLIND_DRAW_STATEMENTS["insert_draw"], run_id=draw.run_id, state=DRAW_SKIPPED,
                opened_at=None, window_hours=None, closed_at=draw.closed_at,
                absence_reason="skipped",
            )

    def _store_draft(self, draw: _Draw, ref: BlindItem, band: str) -> None:
        """Upsert one seat's draft band."""
        draw.drafts[_cell(ref)] = band
        if self._store is None:
            return
        with self._draw_cohort().transaction() as tx:
            tx.execute(
                BLIND_DRAW_STATEMENTS["upsert_draft"], run_id=draw.run_id,
                submission_id=ref.submission_id, criterion_id=ref.criterion_id, band=band,
                updated_at=self._clock(),
            )

    def _store_close(
        self,
        draw: _Draw,
        state: str,
        *,
        closed_at: str,
        labels_written: int,
        unmarked_count: int,
        absence_reason: str | None,
        discard_drafts: bool = False,
    ) -> bool:
        """Close an open draw into `state`, recording what the close does. False, with nothing
        changed, when another request closed the stored draw first."""
        if self._store is not None:
            with self._draw_cohort().transaction() as tx:
                won = tx.execute(
                    BLIND_DRAW_STATEMENTS["close_draw"], run_id=draw.run_id, state=state,
                    closed_at=closed_at, labels_written=labels_written,
                    unmarked_count=unmarked_count, absence_reason=absence_reason,
                )
                if won and discard_drafts:
                    tx.execute(BLIND_DRAW_STATEMENTS["delete_drafts"], run_id=draw.run_id)
            if not won:
                return False
        draw.state = state
        draw.closed_at = closed_at
        draw.labels_written = labels_written
        draw.unmarked_count = unmarked_count
        draw.absence_reason = absence_reason
        if discard_drafts:
            draw.drafts.clear()
        return True

    def _reopen(self, draw: _Draw, state: str, closed_at: str) -> None:
        """Undo a close whose labels failed to land, so the close can be repeated."""
        draw.state = DRAW_OPEN
        draw.closed_at = None
        draw.labels_written = draw.unmarked_count = 0
        draw.absence_reason = None
        if self._store is None:
            return
        with self._draw_cohort().transaction() as tx:
            tx.execute(BLIND_DRAW_STATEMENTS["reopen_draw"], run_id=draw.run_id, state=state,
                       closed_at=closed_at)

    def _settled_draw(self, key: str, *, counter_run: str) -> _Draw | None:
        """The run's draw after settling a lapsed review window (FR-REVIEW-30, OQ-3): an open
        draw whose window has run out (`opened_at + window <= now`, as grade settlement
        measures it) is closed as `closed_by_window`, its drafted seats written as blind labels
        (they were formed blind) and the unmarked seats counted. A window of None or 0 never
        lapses."""
        draw = self._load_draw(key)
        if draw is None or draw.state != DRAW_OPEN or not draw.window_hours:
            return draw
        opened = _instant(draw.opened_at)
        now = _instant(self._clock())
        if opened is None or now is None:
            return draw
        if opened + timedelta(hours=float(draw.window_hours)) <= now:
            try:
                self._close_with_labels(draw, DRAW_CLOSED_BY_WINDOW, counter_run=counter_run)
            except LabelProvenanceError:
                # A drafted seat whose provenance cannot be derived refuses the close with
                # nothing written; the draw stays open rather than wedging every route on the
                # run, so the teacher can still Skip (FR-REVIEW-25).
                return draw
            except _CloseLost:
                return self._load_draw(key)
        return draw

    def _close_with_labels(
        self,
        draw: _Draw,
        state: str,
        *,
        counter_run: str,
        interrupted: bool = False,
        review_seconds: float = 0,
    ) -> BlindCloseReport:
        """Close the draw into `state`, then write one blind label per drafted seat.

        Every drafted seat's provenance is settled before anything changes: one underivable
        cell refuses the close with nothing written and the draw still open (FR-REVIEW-25).
        The close is CLAIMED first (a guarded update): of two requests closing the same draw
        at once (two reads after the window's lapse, say), only the one that wins writes
        labels, and the other raises `_CloseLost`. If writing the labels then fails, the close
        is undone so it can be repeated; a seat the label store already holds a blind label
        for is not written again (FR-CONSOLE-02). The labels carry the routing each seat had
        at draw time (FR-REVIEW-29)."""
        drafted = [(ref, draw.drafts[_cell(ref)]) for ref in draw.seats if _cell(ref) in draw.drafts]
        recorded = self._recorded_blind_labels(draw.run_id)
        to_write = [(ref, band) for ref, band in drafted if self._blind_score_id(ref) not in recorded]
        origins = {
            ref: self._cell_origin(ref.submission_id, ref.criterion_id, self._row_for_ref(ref))
            for ref, _band in to_write
        }
        routing = self._draw_routing(draw)
        unmarked = len(draw.seats) - len(drafted)
        absence = None if drafted else "none_marked"
        closed_at = self._clock()
        if not self._store_close(
            draw, state, closed_at=closed_at, labels_written=len(drafted),
            unmarked_count=unmarked, absence_reason=absence,
        ):
            raise _CloseLost(
                f"run {draw.run_id!r}'s blind sample was closed by another action at the same "
                "moment; this close wrote nothing"
            )
        try:
            labels = [
                self._write_blind_label(
                    ref,
                    band,
                    interrupted=interrupted,
                    review_seconds=review_seconds,
                    origin=origins[ref],
                    routing=routing.get(_cell(ref)) or self._routing_now(ref),
                )
                for ref, band in to_write
            ]
        except BaseException:
            self._reopen(draw, state, closed_at)
            raise
        self._join_blind_system_bands(SimpleNamespace(run_id=draw.run_id))
        self._blind_drawn.setdefault(counter_run, len(draw.seats))
        self._blind_answered[counter_run] = (
            self._blind_answered.get(counter_run, 0) + len(labels))
        self._record_action_emission(labels)
        self._record_emission(
            counter_run, ("blind_completion_rate",),
            {"blind_completion_rate": self._blind_rate(counter_run)},
        )
        return BlindCloseReport(
            run_id=draw.run_id,
            state=state,
            label_ids=tuple(label.label_id for label in labels),
            unmarked_count=unmarked,
            absence_reason=absence,
        )

    def _require_open(self, run_id: str, draw: _Draw | None, what: str) -> None:
        """Refuse `what` unless the run's draw is open (FR-REVIEW-26/30)."""
        if draw is None:
            raise ReviewError(
                f"run {run_id!r} has no blind sample drawn, so there is nothing to take "
                f"{what} for: draw the sample first"
            )
        if draw.state != DRAW_OPEN:
            raise ReviewError(
                f"run {run_id!r}'s blind sample is {draw.state}, so {what} is refused and "
                "nothing was written: once the sample is finished, skipped or closed by the "
                "review window, no mark can be changed (FR-REVIEW-26)"
            )

    @staticmethod
    def _check_transition(state: str, target: str, run_id: str) -> None:
        """Refuse a transition FR-REVIEW-30 does not allow, leaving the state unchanged."""
        if target not in DRAW_TRANSITIONS.get(state, frozenset()):
            raise ReviewError(
                f"run {run_id!r}'s blind sample cannot go from {state} to {target}: a draw "
                "closes only by Finish, Skip or the end of the review window, and nothing "
                "leads back out of a closed draw (FR-REVIEW-30)"
            )

    def _seat_ref(self, draw: _Draw, seat_id: Any) -> BlindItem:
        """The drawn reference a seat id names: `seat-<n>`, the number itself, or the
        reference. A seat outside the draw is refused."""
        if isinstance(seat_id, BlindItem):
            if seat_id in draw.seats:
                return seat_id
        else:
            text = str(seat_id).strip()
            number = text[len("seat-"):] if text.startswith("seat-") else text
            if number.isdigit() and 1 <= int(number) <= len(draw.seats):
                return draw.seats[int(number) - 1]
        raise ReviewError(
            f"{seat_id!r} is not a seat of run {draw.run_id!r}'s blind sample "
            f"({len(draw.seats)} seats): a mark for an answer the sample never posed is a "
            "judgement nobody was asked for"
        )

    def _check_band(self, ref: BlindItem, band: str) -> None:
        """Refuse a band the criterion does not declare, through the one pinned mapping."""
        if not band:
            raise ReviewError("a blind mark names a band; this one names none")
        try:
            self._points_for_band(criterion_id=ref.criterion_id, band=band)
        except Exception as exc:  # noqa: BLE001 — refused with the reason, nothing stored
            raise ReviewError(
                f"{band!r} is not a level of criterion {ref.criterion_id!r}: {exc}"
            ) from exc

    def _window_hours_for(self, key: str) -> float | None:
        """The review window a draw opened now is held to (FR-GRADE-10): the configured value,
        else the run's package grade policy; None when neither declares one."""
        if self._review_window_hours is not None:
            return float(self._review_window_hours) or None
        if self._store is None:
            return None
        try:
            rows = self._draw_cohort().query(REVIEW_STATEMENTS["select_run_package"], run_id=key)
            if not rows:
                return None
            from aeh.pkg import PackageCatalog

            package_id = str(rows[0]["package_id"])
            hours = PackageCatalog(
                self._store.package(package_id), package_id=package_id
            ).grade_policy(str(rows[0]["package_version_id"])).review_window_hours
        except Exception:  # noqa: BLE001 — an unreadable policy declares no window
            return None
        return float(hours) if hours else None

    def _session_for(self, run_id: str, draw: _Draw) -> BlindSession:
        """The session over a draw's seats. Over a store its id is the run's, so a fresh
        service names the same session."""
        if draw.session_id is None:
            draw.session_id = (
                f"blind-{draw.run_id}" if self._store is not None
                else f"blind-{len(self._blind_sessions) + 1:04d}"
            )
        session = BlindSession(session_id=draw.session_id, run_id=run_id, items=draw.seats)
        self._blind_sessions[session.session_id] = session
        return session

    def _seat_context(self, key: str) -> dict[str, Any]:
        """What every seat of a run's draw reads alike: the cohort file and the run's package
        file and version. Empty in memory, or when the run's package cannot be read."""
        if self._store is None:
            return {}
        handle = self._draw_cohort()
        context: dict[str, Any] = {"cohort": handle}
        rows = handle.query(REVIEW_STATEMENTS["select_run_package"], run_id=key)
        if rows:
            try:
                context["package"] = self._store.package(str(rows[0]["package_id"]))
                context["package_version_id"] = str(rows[0]["package_version_id"])
            except Exception:  # noqa: BLE001 — the seat falls back to the default scale
                pass
        return context

    def _seat(
        self, number: int, ref: BlindItem, draw: _Draw, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        """One seat (FR-REVIEW-27), with exactly `BLIND_SEAT_KEYS`."""
        question = ref.criterion_id
        bands: list[dict[str, Any]] = []
        package = context.get("package")
        version = context.get("package_version_id")
        if package is not None and version:
            found = package.query(
                BLIND_DRAW_STATEMENTS["select_criterion_question"],
                package_version_id=version, criterion_id=ref.criterion_id)
            if found and _row_mapping(found[0]).get("question_id"):
                question = str(_row_mapping(found[0])["question_id"])
            bands = [
                {"name": str(mapping["band"]), "descriptor": mapping.get("descriptor")}
                for mapping in (
                    _row_mapping(row) for row in package.query(
                        BLIND_DRAW_STATEMENTS["select_criterion_bands"],
                        package_version_id=version, criterion_id=ref.criterion_id)
                )
            ]
        if not bands:
            bands = self._fallback_bands(ref.criterion_id)
        student_name, answer_text, page_refs = None, None, []
        cohort = context.get("cohort")
        if cohort is not None:
            student_name = self._seat_student_name(cohort, ref.submission_id)
            answer_text, page_refs = self._seat_answer(cohort, ref.submission_id, question)
        return {
            "seat_id": f"seat-{number}",
            "student_name": student_name,
            "question": question,
            "criterion_id": ref.criterion_id,
            "answer_text": answer_text,
            "page_refs": page_refs,
            "bands": bands,
            "draft_band": draw.drafts.get(_cell(ref)),
        }

    def _fallback_bands(self, criterion_id: str) -> list[dict[str, Any]]:
        """The criterion's bands from the attached catalog, else the default scale, each with
        the descriptor the source carries (None when it carries none)."""
        entries: Any = ()
        if self._catalog is not None:
            try:
                entries = self._catalog.bands(criterion_id)
            except Exception:  # noqa: BLE001 — the default scale below
                entries = ()
        if not entries:
            entries = REVIEW_DEFAULT_BANDS
        result = []
        for entry in entries:
            mapping = entry if isinstance(entry, Mapping) else _row_mapping(entry)
            result.append({"name": str(mapping["band"]), "descriptor": mapping.get("descriptor")})
        return result

    @staticmethod
    def _seat_student_name(cohort: Any, submission_id: str) -> str | None:
        """The student's name as the class list gives it, else their roster ref."""
        rows = cohort.query(
            BLIND_DRAW_STATEMENTS["select_submission_student"], submission_id=submission_id)
        if not rows:
            return None
        mapping = _row_mapping(rows[0])
        return str(mapping.get("full_name") or "") or (
            str(mapping["student_ref"]) if mapping.get("student_ref") else None)

    @staticmethod
    def _seat_answer(cohort: Any, submission_id: str, question_id: str) -> tuple[str | None, list[int]]:
        """The student's answer to the question, from the canonical document: the text of the
        question's region(s) in document order, and the scanned pages they are on. The text is
        the canonical Markdown's region bodies (the region the judge is scoped to, ADR-63);
        a document whose Markdown carries no tagged region falls back to the stored region
        rows' text. None when there is no document."""
        from aeh.integ import answer_regions

        documents = cohort.query(
            BLIND_DRAW_STATEMENTS["select_canonical_document"], submission_id=submission_id)
        if not documents:
            return None, []
        document = _row_mapping(documents[0])
        regions = [
            _row_mapping(row) for row in cohort.query(
                BLIND_DRAW_STATEMENTS["select_question_regions"],
                document_id=document["document_id"], question_id=question_id)
        ]
        pages = sorted({int(region["page_no"]) for region in regions if region.get("page_no")})
        spans = answer_regions(str(document.get("markdown") or ""), question_id)
        if spans:
            text = "\n".join(span.text.strip() for span in spans)
        else:
            text = "\n".join(
                str(region.get("content") or "").strip() for region in regions
                if region.get("content"))
        return text, pages

    def render_blind_flow(self, session_id: str) -> str:
        """The blind flow as the teacher sees it (CT-REVIEW-09): the drawn references and the fixed
        band scale, built from the session alone. Nothing the system decided can appear, because
        the session holds nothing the system decided."""
        session = self._blind_sessions.get(session_id)
        if session is None:
            raise ReviewError(
                f"no blind session {session_id!r} in this service; the ids "
                "blind_sample() returned are the render's ids"
            )
        lines = [
            f"Blind validation session {session.session_id} (run {session.run_id})",
            (
                f"{len(session.items)} criteria drawn at random. The system's own "
                "bands are not available in this flow."
            ),
            "",
        ]
        lines.extend(
            f"- submission {ref.submission_id} / criterion {ref.criterion_id}"
            for ref in session.items
        )
        lines.append("")
        lines.append(
            "For each criterion, record the band you judge: "
            + ", ".join(str(band["band"]) for band in REVIEW_DEFAULT_BANDS)
        )
        lines.append("Submit what you answered; an interrupted sitting keeps the answered criteria.")
        return "\n".join(lines)

    def _blind_rate(self, run_id: str) -> float | None:
        """The run's blind completion rate: answered references over drawn ones (CT-REVIEW-18).
        None for a run that never drew: an unmeasured rate, never zero."""
        drawn = self._blind_drawn.get(run_id)
        if not drawn:
            return None
        return self._blind_answered.get(run_id, 0) / drawn

    def _routing_now(self, ref: BlindItem) -> str:
        """The drawn cell's routing as the service's rows hold it now. Called at draw time, so the
        blind label records the routing the cell had when it was drawn (FR-REVIEW-29)."""
        row = self._row_for_ref(ref)
        routing = getattr(row, "routing", None) if row is not None else None
        return str(routing or "queued")

    def _blind_score_id(self, ref: BlindItem) -> str:
        """The score id of the cell a blind reference names (FR-REVIEW-25): the service's row's
        own id, or the store's `<submission>:<criterion>` convention when no row is loaded."""
        row = self._row_for_ref(ref)
        score_id = getattr(row, "score_id", None) if row is not None else None
        return str(score_id or f"{ref.submission_id}:{ref.criterion_id}")

    def _row_for_ref(self, ref: BlindItem) -> Any:
        """The score row a blind reference came from, looked up by the service for the label's
        routing and origin. The session itself never sees it."""
        for row in self._rows:
            if (
                str(getattr(row, "submission_id", "") or "") == ref.submission_id
                and str(getattr(row, "criterion_id", "") or "") == ref.criterion_id
            ):
                return row
        return None

    def _auto_grade_population(self) -> list[tuple[str, str, str]]:
        """The whole-grade sample's population (FR-REVIEW-14): submissions where every criterion
        was auto-accepted, as `(submission_id, criterion_id, band)` triples. A submission with any
        other routing is left out, because the grade shown must be complete and wholly the
        system's. With a store, this uses the declared `select_auto_grades` statement; in memory,
        the rows are filtered the same way.

        A service built for one run (`review_service_over(..., run_id=...)`, the console's) reads
        that run's population only, in whichever cohort holds it (#869): without the scope every
        cohort's newest run was pooled, so the console's sample for one class mixed in another
        class's papers, and an older run's sample was the newest run's."""
        if self._store is not None:
            triples: list[tuple[str, str, str]] = []
            scope = getattr(self, "_scope_run_id", None)
            for cohort_id in self._cohort_ids:
                run_id = scope if scope is not None else _newest_run_id(self._store, cohort_id)
                if run_id is None:
                    continue
                for row in self._store.cohort(cohort_id).query(
                    REVIEW_STATEMENTS["select_auto_grades"], run_id=run_id
                ):
                    mapping = _row_mapping(row)
                    submission_id = str(mapping.get("submission_id") or "")
                    criterion_id = str(mapping.get("criterion_id") or "")
                    band = str(mapping.get("band") or "")
                    if submission_id and criterion_id and band:
                        triples.append((submission_id, criterion_id, band))
            return triples
        non_auto: set[str] = set()
        auto_bands: dict[str, list[tuple[str, str]]] = {}
        for row in self._rows:
            submission_id = str(getattr(row, "submission_id", "") or "")
            if not submission_id:
                continue
            if getattr(row, "routing", None) != "auto":
                non_auto.add(submission_id)
                continue
            criterion_id = str(getattr(row, "criterion_id", "") or "")
            band = str(getattr(row, "proposed_band", "") or "")
            if criterion_id and band:
                auto_bands.setdefault(submission_id, []).append((criterion_id, band))
        return [
            (submission_id, criterion_id, band)
            for submission_id, bands in auto_bands.items()
            if submission_id not in non_auto
            for criterion_id, band in bands
        ]

    def _write_blind_label(
        self,
        ref: BlindItem,
        band: str,
        *,
        interrupted: bool,
        review_seconds: float,
        origin: str,
        routing: str,
    ) -> LabelRecord:
        """Write one blind label, collected by a flow that could not see the system's output.
        `review_queue_action` and `system_band` are None and `saw_system_output` is 0
        (CT-REVIEW-09); the band is the teacher's alone, and its points come from the pinned
        mapping (NFR-AGG-02). The score row stays flagged: a blind label is evidence about the
        system, not a decision on the row.

        `score_id` names the cell the label is about (FR-REVIEW-25), resolved by the service, not
        the session; `origin` is the one derived from the cell's work units and `routing` the
        cell's routing at draw time (FR-REVIEW-29), both settled by the caller."""
        label = LabelRecord(
            label_id=self._mint_label_id(),
            label_type="blind",
            saw_system_output=0,
            routing=routing,
            origin=origin,
            evaluation_mode=ref.evaluation_mode,
            review_seconds=review_seconds,
            system_band=None,
            teacher_band=band,
            actor=self._actor_name,
            timestamp=self._clock(),
            score_id=self._blind_score_id(ref),
            criterion_id=ref.criterion_id,
            review_queue_action=None,
            # The label's points derive from the band through the one pinned
            # mapping (`FR-REVIEW-10`), exactly as a queue label's do — the
            # derivation is the teacher's band's, never the system's.
            new_points=self._points_for_band(criterion_id=ref.criterion_id, band=band),
        )
        self._labels.append(label)
        self._labels_by_id[label.label_id] = label
        run_id = self._attribution_run()
        if run_id is not None:
            self._run_labels.setdefault(run_id, []).append(label)
        if self._store is not None:
            if run_id is None:
                raise ReviewError(
                    "this service holds a store but no run context: build a queue "
                    "for the run (or open the service over exactly one cohort) "
                    "before submitting the blind flow — a label is not attributed "
                    "to an invented run"
                )
            # `ref` itself: `_persist_label` reads the item's `submission_id`,
            # and a BlindItem carries exactly that identity — no ReviewItem is
            # needed, and handing one over would smuggle the score row back
            # into the flow that cannot see it.
            self._persist_label(label, run_id, ref)
        self._audit.append(
            WriteRecord(
                table="label",
                score_id=ref.submission_id,
                detail=(
                    f"blind label {label.label_id}"
                    + (" (interrupted session, answered criteria only)" if interrupted else "")
                ),
            )
        )
        return label

    def _join_blind_system_bands(self, session: Any) -> None:
        """Fill in the system's band on stored blind labels, so every stored label carries both
        bands (CT-REVIEW-07).

        A blind label is written with `system_band = NULL`, because the sitting must not reach
        the score row while the teacher answers (CT-REVIEW-09). Once the sitting is submitted,
        each label records the band of the score it judged, read from the rows this service
        loaded, with `agreed`, `band_distance` and `system_points` recomputed the same way
        `_label_judgement_columns` computes them at write time. The in-memory records the
        sitting produced keep `system_band = None`. A storeless service has no stored rows.

        The join reads the run's blind labels that still lack the band from the store, not
        just this call's labels, so a join that failed after the labels landed is repaired by
        the next submit or resubmit (the UPDATE is guarded, so this is idempotent)."""
        if self._store is None:
            return
        attributed = self._attribution_run() or session.run_id
        pending = self._store.durable().query(
            REVIEW_STATEMENTS["select_unbanded_blind_labels"], run_id=attributed)
        updates = []
        for stored in pending:
            # Keyed on the label's score id (FR-REVIEW-25); a label written before #867 has
            # none, and its `student_ref` held the submission id, which rebuilds the old key.
            row = self._rows_by_id.get(
                stored["score_id"] or f"{stored['student_ref']}:{stored['criterion_id']}")
            band = getattr(row, "proposed_band", None) if row is not None else None
            if band is None:
                continue
            probe = SimpleNamespace(system_band=band, teacher_band=stored["teacher_band"],
                                    criterion_id=stored["criterion_id"], timestamp=None)
            columns = self._label_judgement_columns(probe, attributed)
            updates.append(dict(label_id=stored["label_id"], system_band=band,
                                agreed=columns["agreed"], band_distance=columns["band_distance"],
                                system_points=columns["system_points"]))
        if not updates:
            return
        with self._store.durable().transaction() as tx:
            for update in updates:
                tx.execute(REVIEW_STATEMENTS["set_blind_system_band"], **update)

    def _recorded_blind_labels(self, run_id: str) -> set[str]:
        """The score ids of the cells that already have a stored blind label. A label written
        before #867 carries no score id; its `student_ref` held the submission id, so the old
        `<submission>:<criterion>` key is rebuilt from it."""
        if self._store is None:
            return set()
        attributed = self._attribution_run() or run_id
        rows = self._store.durable().query(
            REVIEW_STATEMENTS["select_blind_labels_for_run"], run_id=attributed)
        return {
            str(row["score_id"] or f"{row['student_ref']}:{row['criterion_id']}") for row in rows
        }
