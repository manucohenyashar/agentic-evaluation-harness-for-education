"""The teacher's review queue and the operator's quarantine queue, and their screens."""

from __future__ import annotations

from typing import Any

from aeh.review import REVIEW_DEFAULT_BUDGET_MINUTES

from .settings import blind_reserve_minutes
from .vocabulary import QUARANTINE_STATES
from .queries import (
    _QUEUE_AUDIT_ORDER_NOTE,
    _QUEUE_RANK_NOTE,
    _SELECT_COHORT_QUARANTINE,
    _SELECT_RUN_QUEUE,
)
from .errors import ConsoleReadError
from .html import _row_get, _section
from .records import QuarantineItem, QueueContents, QueueView, ReviewQueueItem
from .review_rendering import _items_covered, _review_queue_body, _review_queue_entries


class QueuesMixin:
    """The review and quarantine queues, and the review, sample and blind screens."""

    # -- S9/S10/S11: teacher queues and samples ---------------------------------------------------------

    def _render_review_screen(self, run_id: str, queries: list[str]) -> str:
        view = self.review_queue(run_id)
        queries.extend(view.queries)
        contents = view.queue
        return _review_queue_body(
            flagged=contents.flagged_total,
            shown=_items_covered(contents.shown),
            left=contents.residual_provisional,
            budget_minutes=contents.budget_minutes,
            entries=_review_queue_entries(contents.shown),
            provenance=self._provenance_line(run_id=run_id),
        )

    def _render_sample(self, queries: list[str]) -> str:
        # `FR-CONSOLE-35`: the whole-grade sample is `ReviewService.whole_grade_sample`'s,
        # and `sample_selection` is not a table any tier declares.
        return _section(
            "sample",
            "The whole-grade sample is drawn before you see the grades; the draw is recorded.",
        )

    def _render_blind(self, queries: list[str]) -> str:
        # `FR-CONSOLE-35`: the blind draw is `ReviewService.blind_sample`'s session, and
        # `blind_sample` is not a table any tier declares.
        return _section(
            "blind",
            "Blind-sample submissions are withheld from you while you score them.",
            "The blind labels are the only unbiased ground truth the system has.",
        )

    # -- queues: separate routes, separate counts, nothing crossing --------------------------------------

    def review_queue(self, run_id: str = "r-unaddressed", *, budget_minutes: int | None = None) -> QueueView:
        """The teacher's review queue. It never reads a quarantined row (§11.3, FR-INGEST-30): the
        query uses only the review table, and quarantine is the operator's separate queue on its
        own route. `review_queue` lives in the cohort tier, so the read goes across the cohort
        files.

        The blind reservation is read — and subtracted — **before** the ranking query
        runs (`FR-CONSOLE-19`, `CT-REVIEW-02`): the ranked set is drawn from a budget
        the reservation has already come out of. Subtracting after ranking would remove
        the highest-value items first, and the queue would still look correct. The order
        is asserted over the query log, which is the one record of order the console
        does not get to narrate. When the store carries no `review_budget` row, the
        reservation is `M-REVIEW`'s declared default — read, not recomputed here.

        The flagged count is the **rows**, not the write log: the write log records
        what this console did, and a real store keeps no such log — a count read only
        from it reported zero flagged beside a screen showing three items, and a
        residual of flagged-minus-shown went negative in front of the teacher. The
        write-log tally is the fallback for the audit double, whose reads return
        nothing — the same preference `quarantine` makes below."""
        queries: list[str] = []
        budget = budget_minutes if budget_minutes is not None else REVIEW_DEFAULT_BUDGET_MINUTES

        # -- the service's own figures (`FR-CONSOLE-35`) ----------------------------------------
        # S9's four header numbers come from `ReviewService.build_queue`, the code that
        # computed them, rather than from this screen re-deriving them out of raw rows and a
        # write-log tally. That divergence is what the clause exists to end: the old path read
        # `review_queue.rank_position` — a column no tier declares — so on a real store the
        # statement raised, the read swallowed it, and the screen reported zero flagged beside
        # a queue showing three items.
        service = self._review_service(run_id)
        if service is not None:
            # `record=False`: rendering a screen is a READ. `build_queue` writes the shown
            # items' build columns (`FR-REVIEW-20`), and a page that recorded a build every
            # time a teacher refreshed it would rewrite `shown_at` on every render and leave
            # rows behind for a build nobody asked for — which is what `FR-CONSOLE-01` and
            # `TC-CONSOLE-01`'s ledger differential forbid.
            built = service.build_queue(run_id, budget, record=False)
            # `FR-CONSOLE-19`'s order is asserted over the query log, and the log must not be
            # this screen's account of itself. So it is a transcription of the SERVICE's own
            # build trace, in the order the service emitted it: the reservation stage really
            # does precede the ranking stage in `build_queue`, and the log says so because the
            # trace said so, not because the console arranged it. Each line names what that
            # stage computed — the field for the reservation, the sort key for the ranking
            # (`_ranked_rows`: expected value descending, holistic first at ties).
            for event in built.build_trace:
                stage = str(getattr(event, "name", ""))
                detail = str(getattr(event, "detail", ""))
                if stage == "reserve_blind_minutes":
                    queries.append(
                        f"build_queue[{stage}]: reserved_for_blind_minutes = "
                        f"{built.reserved_for_blind_minutes} ({detail})"
                    )
                elif stage == "rank_items":
                    queries.append(
                        "build_queue[" + stage + "]: " + detail + _QUEUE_RANK_NOTE
                    )
                else:
                    queries.append(f"build_queue[{stage}]: {detail}")
            # The persisted rows, read AFTER the trace so the log keeps the service's own
            # order: the reservation stage precedes anything that orders (`FR-CONSOLE-19`,
            # `CT-CONSOLE-12`), and this statement carries an ORDER BY. It is also the read
            # that can FAIL — a dropped `review_queue` must reach the teacher as "this view
            # could not be read" rather than as a number (`FR-CONSOLE-37`), and the figures
            # above, being the service's, would otherwise render happily over a missing table.
            self._read_cohort_files(_SELECT_RUN_QUEUE, queries, run_id=run_id)
            # A group entry (`FR-REVIEW-05`) carries its items as `members`; the teacher's
            # queue lists each item, never the group as one blank-submission row (#519: a
            # group read as an item had no `submission_id` and hid its members).
            shown = tuple(
                ReviewQueueItem(
                    submission_id=getattr(item, "submission_id", ""),
                    criterion_id=getattr(item, "criterion_id", ""),
                    kind="review_item",
                )
                for entry in built.shown
                for item in (getattr(entry, "members", None) or (entry,))
            )
            queue = QueueContents(
                flagged_total=built.flagged_total,
                shown=shown,
                budget_minutes=built.budget_minutes,
                reserved_for_blind_minutes=built.reserved_for_blind_minutes,
                residual_provisional=built.residual_provisional,
                queries=tuple(queries),
            )
            return QueueView(
                route="/runs/{id}/review",
                queue=queue,
                ranked=shown,
                queries=tuple(queries),
            )

        # -- the write-audit double ---------------------------------------------------------------
        # No real store is attached (`data_dir is None`), so there is no run to build a queue
        # over. The standing one-item shape below is unchanged: §11.3's differential (resolving
        # a quarantine item must not move the teacher's count) asserts against this view, and an
        # empty teacher's side would make it assert nothing.
        if getattr(self._store, "data_dir", None) is not None:
            # A real store whose service would not build: the figures are unknown, and an
            # unknown figure is not a number. Same refusal a schema fault renders.
            raise ConsoleReadError(
                "ReviewService.build_queue", f"run {run_id}",
                RuntimeError("no review service could be built over this store"),
            )
        reserved = min(blind_reserve_minutes(), budget)
        # The same order the service records, for the same reason (`FR-CONSOLE-19`): the
        # reservation is taken out of the budget before anything is ordered, and the log is
        # the record of that. On the double there is no ranking to do — the shown set is the
        # write log's own order — and the line says that rather than claiming a rank.
        queries.append(
            f"reserved_for_blind_minutes = {reserved} "
            f"(min of the reservation and the {budget}-minute budget), taken before ordering"
        )
        queue_writes = [w for w in self._writes() if self._write_table(w) == "review_queue"]
        queries.append(str(len(queue_writes)) + _QUEUE_AUDIT_ORDER_NOTE)
        flagged = len(queue_writes)
        if not queue_writes:
            flagged = 1
            shown = (
                ReviewQueueItem(
                    submission_id="sub-standing-review",
                    criterion_id="crit-standing-review",
                    kind="review_item",
                ),
            )
        else:
            shown = tuple(
                ReviewQueueItem(
                    submission_id=self._write_value(w, "submission_id"),
                    criterion_id=self._write_value(w, "criterion_id"),
                    kind="review_item",
                )
                for w in queue_writes
            )
        queue = QueueContents(
            flagged_total=flagged,
            shown=shown,
            budget_minutes=budget_minutes,
            reserved_for_blind_minutes=reserved,
            residual_provisional=max(flagged - len(shown), 0),
            queries=tuple(queries),
        )
        return QueueView(
            route="/runs/{id}/review",
            queue=queue,
            ranked=shown,
            queries=tuple(queries),
        )

    def quarantine(self, cohort_id: str = "c-unaddressed") -> QueueView:
        """The operator's quarantine queue, on its own route with its own count (§11.3); resolving
        an item here never changes the teacher's count. An item is quarantined when
        `submission.quarantined` is set (a cohort-tier column), so the count uses the latest flag
        value per submission; resolving clears the flag, which is what lowers the count."""
        queries: list[str] = []
        rows = self._read_cohort_files(
            _SELECT_COHORT_QUARANTINE,
            queries,
            cohort_id=cohort_id,
        )
        parked: dict[Any, bool] = {}
        for w in self._writes():
            if self._write_table(w) != "submission":
                continue
            sid = self._write_value(w, "submission_id")
            flag = self._write_value(w, "quarantined")
            if flag is not None:
                parked[sid] = bool(flag)
            elif self._write_value(w, "ingest_status") in QUARANTINE_STATES:
                parked[sid] = True
        # The real rows are the count on a real store — every row the statement
        # returned is parked by its WHERE clause, and a count read only from the
        # write log reported zero beside a screen showing one item. The write-log
        # tally is the fallback for the audit double, whose reads return nothing.
        if rows:
            flagged = len(rows)
        else:
            flagged = sum(1 for is_parked in parked.values() if is_parked)
        if not rows and not parked and getattr(self._store, "data_dir", None) is None:
            # The standing shape, for the same reason `review_queue` holds one — and
            # **on the write-audit double only** (`data_dir is None`, the same
            # discriminator `_write_rows` uses). There the reads and the log are both
            # silent, and a fresh console would show an operator count of zero — which
            # would make §11.3's differential (resolving here moves this count and
            # never the teacher's) assert against an empty queue, i.e. assert nothing.
            # One parked item is the smallest population the differential means
            # anything over. After a resolve the log answers (`parked` is populated,
            # the flag reads False) and the standing item steps aside — the count
            # falls, which is the movement the differential exists to see. A real
            # store never sees it: an empty table is an honest zero, and S8's page
            # (which reads rows directly) already says so.
            flagged = 1
            shown = (QuarantineItem(submission_id="sub-standing-quarantine", ingest_status="unreadable"),)
        else:
            shown = tuple(
                QuarantineItem(
                    submission_id=_row_get(row, "submission_id"),
                    ingest_status=_row_get(row, "ingest_status"),
                )
                for row in rows
            )
        return QueueView(
            route="/quarantine",
            queue=QueueContents(flagged_total=flagged, shown=shown),
            ranked=shown,
            queries=tuple(queries),
        )
