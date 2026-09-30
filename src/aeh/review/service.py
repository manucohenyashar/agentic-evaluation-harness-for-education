"""`ReviewService`: builds the budgeted queue, and closes sessions and runs."""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

from .settings import _calibration_knobs, REVIEW_DEFAULT_BANDS, REVIEW_DEFAULT_BUDGET_MINUTES
from .errors import ReviewError, StaleReviewItemError
from .schema import _queue_id_for, REVIEW_QUEUE_STATEMENTS
from .records import (
    BlindSession,
    BuildEvent,
    CounterEmission,
    LabelRecord,
    QueryPlan,
    ResidualReport,
    ReviewGroup,
    ReviewItem,
    ReviewQueue,
    WriteRecord,
)
from .ranking import (
    _admitted,
    _ADVISORY_ROUTINGS,
    _EXCLUDED_ORIGINS,
    _expected_value,
    _fill_to_budget,
    _group_identical,
    _itemize,
    _items_shown_count,
    _JUDGED_MODE,
    _ranked_rows,
    _RESIDUAL_STATE,
    _score_id_of,
    _signature_of,
)
from .actions import ActionsMixin
from .blind import BlindSamplingMixin
from .observability import ObservabilityMixin


# --- the service ------------------------------------------------------------------------------------


class ReviewService(ActionsMixin, BlindSamplingMixin, ObservabilityMixin):
    """The review service: builds the queue, ranks it, writes labels.

    Constructed by ``build_review`` (rung 0/1, over score rows in memory) or
    ``open_review`` (rung 2, over a stored run). The three §3.15 members #108
    owns are here with #110's label store (``label``, ``points_for_band``,
    ``edit_views``, ``act_from_view`` and the observability surface), plus
    #109's admission plan, write audit and residual reads (``admission_query``,
    ``write_audit``, ``scores``, ``labels_for``, ``end_session``/``close_run``)
    and #111's two samples (``blind_sample``/``submit_blind``,
    ``whole_grade_sample``) with the skip (``skip_blind_sample``) and the
    rendered blind flow (``render_blind_flow``).
    """

    def __init__(
        self,
        rows: Sequence[Any],
        *,
        actor: str = "teacher",
        clock: Callable[[], str] | None = None,
        catalog: Any = None,
        config: Any = None,
        blind_reserve_minutes: int | None = None,
        blind_n: int | None = None,
        whole_grade_n: int | None = None,
        default_budget_minutes: int | None = None,
        seed: int | None = None,
        administration_id: str | None = None,
        previous_administration: Any = None,
        store: Any = None,
    ) -> None:
        self._rows = tuple(rows)
        self._rows_by_id = {_score_id_of(row): row for row in self._rows}
        self._actor_name = actor
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        # The points route (`FR-REVIEW-10`): a catalog attached at construction
        # is read per criterion; without one the declared default scale below
        # is read through the same mapping function (see the interpretations).
        self._catalog = catalog
        self._blind_reserve = blind_reserve_minutes
        self._blind_n = blind_n
        self._whole_grade_n = whole_grade_n
        self._default_budget = default_budget_minutes
        # #111's sampling: one seed per service, both samples draw from it; the
        # administration identity rides along for attribution and for the skip
        # report's context. `previous_administration` is held, never read: the
        # carry-forward RISK-08 forbids is a *value* a skip report could
        # present, and holding the earlier administration's result without
        # reading it is what makes `current_figure=None` an honest None.
        self._seed = seed
        self._administration_id = administration_id
        self._previous_administration = previous_administration
        self._store = store
        self._cohort_ids: tuple[str, ...] = ()
        self._labels: list[LabelRecord] = []
        self._labels_by_id: dict[str, LabelRecord] = {}
        self._audit: list[WriteRecord] = []
        # -- observability bookkeeping (CT-REVIEW-18) -----------------------------------------------
        self._current_run_id: str | None = None
        self._run_labels: dict[str, list[LabelRecord]] = {}
        self._builds: dict[str, dict[str, Any]] = {}
        self._emissions: dict[str, list[CounterEmission]] = {}
        self._exhaustions: dict[str, list[str]] = {}
        self._acted: set[str] = set()
        self._versions: dict[str, int] = {}
        # -- #111's blind-flow bookkeeping ------------------------------------------------------------
        self._blind_sessions: dict[str, BlindSession] = {}
        self._blind_submitted: set[str] = set()
        self._blind_drawn: dict[str, int] = {}
        self._blind_answered: dict[str, int] = {}
        self._skipped_runs: set[str] = set()
        self._whole_grade_draws = 0

    # -- the queue -----------------------------------------------------------------------------------

    def build_queue(
        self, run_id: str, budget_minutes: int, *, record: bool = True
    ) -> ReviewQueue:
        """Build the minute-budgeted queue (`FR-REVIEW-01`).

        `record=False` builds the same queue and writes nothing. `FR-REVIEW-20` makes a build
        a writer — the shown items' `rank_score`, `est_seconds` and `shown_at` land on their
        queue rows — and `FR-CONSOLE-35` puts this call on a console screen, which is a READ
        (`FR-CONSOLE-01`: a console open during a run leaves the run identical). Rendering S9
        must therefore be able to ask for the figures without recording a build that never
        happened, and that is what this flag is for. Nothing else about the queue differs.

        Stage order is the contract, not an implementation detail
        (`CT-REVIEW-02`): the blind reserve is subtracted **before** anything is
        ranked, and the trace says so. The queue fills in rank order, takes what
        fits, and states what is left over — and never bills its own build
        seconds to the teacher (`CT-REVIEW-16`).
        """
        started = perf_counter()
        trace: list[BuildEvent] = []
        knobs = _calibration_knobs()

        admitted = self._admitted_rows()
        flagged_total = len(admitted)
        trace.append(BuildEvent("count_flagged", f"{flagged_total} queued judged rows"))

        reserve = min(self._blind_reserve, budget_minutes)
        available_seconds = max(budget_minutes - reserve, 0) * 60
        trace.append(
            BuildEvent(
                "reserve_blind_minutes",
                f"{reserve} of {budget_minutes} minutes reserved; "
                f"{available_seconds}s spendable",
            )
        )

        ranked = _ranked_rows(admitted, knobs)
        trace.append(BuildEvent("rank_items", f"{len(ranked)} items ranked"))

        groups, leftovers = _group_identical(ranked, knobs)
        trace.append(
            BuildEvent(
                "group_identical_signatures",
                f"{len(groups)} groups over "
                f"{sum(len(group.members) for group in groups)} items",
            )
        )

        shown = _fill_to_budget([*groups, *leftovers], available_seconds)
        trace.append(
            BuildEvent(
                "truncate_to_budget", f"{len(shown)} entries shown within {available_seconds}s"
            )
        )

        residual = flagged_total - _items_shown_count(shown)
        trace.append(
            BuildEvent(
                "compute_residual", f"{residual} of {flagged_total} remain provisional"
            )
        )

        # CT-REVIEW-18's bookkeeping: this build is the run's queue as it now
        # stands, and its honesty pair is emitted together or not at all —
        # which is the shape the pairing assertion reads.
        self._current_run_id = run_id
        self._builds[run_id] = {
            "shown_items": _items_shown_count(shown),
            "flagged": flagged_total,
            "est_seconds": tuple(entry.est_seconds for entry in shown),
        }
        self._record_emission(
            run_id,
            ("review_items_shown", "review_items_flagged"),
            {
                "review_items_shown": _items_shown_count(shown),
                "review_items_flagged": flagged_total,
            },
        )
        if record:
            self._record_shown_rows(run_id, shown, knobs)

        return ReviewQueue(
            run_id=run_id,
            budget_minutes=budget_minutes,
            reserved_for_blind_minutes=reserve,
            flagged_total=flagged_total,
            shown=tuple(shown),
            residual_provisional=residual,
            groups=tuple(groups),
            build_seconds=perf_counter() - started,
            build_trace=tuple(trace),
        )

    def queue(
        self, run_id: str = "run-1", budget_minutes: int | None = None
    ) -> tuple["ReviewItem | ReviewGroup", ...]:
        """The built queue as its consumer reads it (`§3.15`): the shown
        entries — signature groups collapsed, singletons per-item — in
        presentation order.

        ``build_review(store).queue()`` is the store form's declared read
        (the c05/c07/c09 consumer limbs' shape): no run id and no budget
        arrive, so the module's default budget governs. The residual header
        and the per-stage trace stay on ``build_queue`` — this is the queue's
        face, not its bookkeeping."""
        budget = (
            int(budget_minutes)
            if budget_minutes is not None
            else int(self._default_budget or REVIEW_DEFAULT_BUDGET_MINUTES)
        )
        return self.build_queue(run_id, budget).shown

    def rank_queue_items(self, run_id: str) -> tuple[ReviewItem, ...]:
        """The ranking, separable from the queue (`FR-REVIEW-03`): every admitted
        item, best-first, each carrying its ``expected_value`` — the ranking's
        full output, without the budget's truncation."""
        knobs = _calibration_knobs()
        admitted = self._admitted_rows()
        ranked = _ranked_rows(admitted, knobs)
        return tuple(_itemize(row, knobs) for row in ranked)

    def group_signature(self, row: Any) -> dict[str, Any]:
        """The exact Phase 1 grouping signature (`CT-REVIEW-20`): the five
        declared components and nothing else — a rule with fewer components
        groups items the clause says are different; one with more never groups
        anything."""
        return _signature_of(row)

    def admission_query(self, run_id: str = "run-1") -> QueryPlan:
        """The admission query as a plan, not an observation (`CT-REVIEW-05`'s
        reachability clause): the routing values the queue's queries read over,
        the evaluation mode they gate on, and the origins they can never reach.

        ``_admitted`` is the single predicate the plan restates — the in-memory
        filter executes it, and the store form runs it on every fetched row
        beneath its WHERE clause — so the plan cannot drift from what the
        service runs. The store's routing narrow is a declared SQL literal
        (SEC-15 permits no runtime assembly), matching this tuple by
        transcription rather than by construction; the mode and origin halves
        ride the predicate. The routings are both of the teacher's (`CT-AGG-06`'s
        ``queued``, plus the provisional family whose rows `CT-AGG-07` binds
        this module to surface); ``triage``, the operator's queue, is reachable
        by neither. The mode is gated on the evaluation-mode column
        (`FR-REVIEW-06`, `CT-DET-06`), not by convention.

        ``run_id`` is bookkeeping: the plan is the same over every run the
        service carries, and is stated for the run the caller names."""
        return QueryPlan(
            routing_values=tuple(_ADVISORY_ROUTINGS),
            evaluation_modes=(_JUDGED_MODE,),
            excluded_origins=tuple(sorted(_EXCLUDED_ORIGINS)),
        )

    # -- actions -------------------------------------------------------------------------------------

    def _record_shown_rows(self, run_id: str, shown: Sequence[Any], knobs: Any) -> None:
        """Write `FR-REVIEW-20`'s build columns for the items this build showed.

        Best-effort against the store, and only there: the in-memory service has no
        `review_queue` to write to, and a queue build is a READ as far as the teacher is
        concerned — a store that refuses the write must not take the screen down with it."""
        if self._store is None:
            return
        cohort_id = self._writable_cohort()
        if cohort_id is None:
            return
        shown_at = self._clock()
        try:
            handle = self._store.cohort(cohort_id)
            with handle.transaction() as tx:
                for entry in shown:
                    for member in getattr(entry, "members", None) or (entry,):
                        submission_id = str(getattr(member, "submission_id", ""))
                        criterion_id = str(getattr(member, "criterion_id", ""))
                        if not submission_id:
                            continue
                        queue_id = _queue_id_for(run_id, submission_id, criterion_id)
                        tx.execute(
                            REVIEW_QUEUE_STATEMENTS["ensure_queue_row"],
                            queue_id=queue_id, run_id=run_id,
                            submission_id=submission_id, criterion_id=criterion_id,
                            reason="queued for review",
                        )
                        tx.execute(
                            REVIEW_QUEUE_STATEMENTS["record_shown"],
                            queue_id=queue_id, run_id=run_id,
                            rank_score=float(_expected_value(member, knobs)),
                            est_seconds=float(getattr(member, "est_seconds", 0.0) or 0.0),
                            shown_at=shown_at,
                        )
        except Exception:  # noqa: BLE001 — the queue still renders; the row is bookkeeping
            return

    def _record_queue_action(self, item: Any, action: str, label: Any) -> None:
        """Write `FR-REVIEW-20`'s action columns for one acted item."""
        if self._store is None:
            return
        cohort_id = self._writable_cohort()
        run_id = self._current_run_id or ""
        if cohort_id is None or not run_id:
            return
        submission_id = str(getattr(item, "submission_id", ""))
        criterion_id = str(getattr(item, "criterion_id", ""))
        if not submission_id:
            return
        try:
            handle = self._store.cohort(cohort_id)
            with handle.transaction() as tx:
                tx.execute(
                    REVIEW_QUEUE_STATEMENTS["record_action"],
                    queue_id=_queue_id_for(run_id, submission_id, criterion_id),
                    action=action,
                    new_band=getattr(label, "teacher_band", None),
                    new_points=getattr(label, "new_points", None),
                    acted_at=self._clock(),
                )
        except Exception:  # noqa: BLE001 — the label is the record of the decision either way
            return

    def _points_for_band(
        self,
        package_version_id: str | None = None,
        criterion_id: str | None = None,
        band: str | None = None,
    ) -> float:
        """Band → points, through the one pinned mapping (`FR-REVIEW-10`). With
        a ``catalog=`` attached the criterion's own pinned table is read
        (``PackageCatalog.points_for_band``); without one, the declared default
        scale (`REVIEW_DEFAULT_BANDS`) is read through the same function —
        never a second table (`NFR-AGG-02`). A band absent from whichever
        table governs refuses (`PackageError`) rather than defaulting to a
        number — but a band whose name exists in both tables is not
        distinguishable without a catalog, so the no-catalog route derives the
        default scale's points for it (the collision hazard is disclosed in
        the module interpretations). ``package_version_id`` is accepted for
        interface parity with the queue item and ignored: the mapping is
        criterion-scoped.
        """
        if band is None:
            raise ReviewError(
                "a score edit is a band selection; there is no band here to map"
            )
        if self._catalog is not None:
            return self._catalog.points_for_band(criterion_id, band)
        from aeh import pkg as _pkg  # lazy: pkg's import graph must not pull review in

        return float(_pkg.points_for_band(REVIEW_DEFAULT_BANDS, band))

    # The public face, aliased to the body above. Deliberately an alias and not
    # a second definition: NFR-AGG-02 keeps the mapping *defined* in exactly
    # one module (aeh.pkg — CT-PKG-05's pinned mapping), and the artifact sweep
    # enforcing it reads the source.
    points_for_band = _points_for_band

    def close(self) -> None:
        """Release the rung-2 store handle, if this service was opened over one."""
        if self._store is not None:
            self._store.close()
            self._store = None

    def _with_store(
        self,
        store: Any,
        cohort_ids: Sequence[str] = (),
        owning_cohorts: Sequence[str] = (),
    ) -> "ReviewService":
        """Attach the rung-2 store handle (``open_review``'s plumbing). The
        cohort ids ride along so a label written before any queue build can
        still attribute itself — to the sole cohort, when there is exactly
        one; never to an invented run (`NFR-REVIEW-04`)."""
        self._store = store
        self._cohort_ids = tuple(cohort_ids)
        #: The cohorts whose rows this service actually loaded — a subset of `cohort_ids`
        #: once a run scope is given, and what `FR-REVIEW-20`'s writes are addressed to.
        self._owning_cohorts = tuple(owning_cohorts)
        return self

    #: The run's declared criteria and their scoring models, attached when the service is
    #: built over a store. The PACKAGE is the authority on which criteria exist
    #: (`CT-SETUP-05`); the queue only knows which of them need a teacher.
    _declared_models: "Mapping[str, str]" = {}

    def scoring_model_for(self, criterion_id: str) -> str:
        """`FR-REVIEW-19`: the criterion's stored scoring model for this service's run.

        Raises for a criterion the run does not score, rather than answering `"atomic"`.
        The guess is the failure mode this replaces: a holistic criterion silently read
        as atomic is budgeted at half the minutes a teacher needs, and the queue that
        results overruns without ever reporting that it did."""
        declared = self._declared_models
        if criterion_id in declared:
            model = declared[criterion_id]
            if model:
                return str(model)
            raise ReviewError(
                f"criterion {criterion_id!r} is declared by this run's package version, "
                "but the version declares no model for it (FR-REVIEW-19). The "
                "model is the package's to declare; the review will not assume one."
            )
        for row in self._rows:
            if getattr(row, "criterion_id", None) != criterion_id:
                continue
            carried = getattr(row, "scoring_model", None)
            if carried:
                return str(carried)
            break
        raise ReviewError(
            f"criterion {criterion_id!r} is not declared by this run (FR-REVIEW-19)"
        )

    def _writable_cohort(self) -> "str | None":
        """The cohort `FR-REVIEW-20`'s columns are written to.

        The cohort whose rows this service actually loaded, when exactly one did — not
        `_attribution_run`, which answers "which run does a label belong to". Asking the store
        for a cohort keyed by a run id would create that cohort's file."""
        owning = getattr(self, "_owning_cohorts", ())
        if len(owning) == 1:
            return owning[0]
        if len(self._cohort_ids) == 1:
            return self._cohort_ids[0]
        return None

    # -- the write audit, and the residual's read path (#109) -----------------------------------------

    def write_audit(self) -> tuple[WriteRecord, ...]:
        """Every write this service's actions have made, in write order
        (`CT-REVIEW-06` reads the indirection from the write side, not from the
        resulting counts, because the counts are identical either way).

        In the in-memory service the writes land on the service's own state —
        the label list and the acted set — and each ``WriteRecord`` names the
        store table that state stands in for: ``criterion_score`` for the
        reduction through the score row (the acted row leaves the flagged count
        *through* ``criterion_score``, never through a grade table — this
        module never writes a grade) and ``label`` for the label itself. #110's
        store writes keep the same tables, so the audit reads the same after."""
        return tuple(self._audit)

    def scores(self, run_id: str = "run-1") -> tuple[Any, ...]:
        """The run's still-flagged score rows, read back for the residual
        (`FR-REVIEW-08`'s read path): the admitted population minus what this
        service has acted on — the population ``build_queue`` counts into
        ``flagged_total``, so ``len(scores())`` is the flagged figure at the
        same moment.

        States ride through exactly as stored. Review writes no state it did
        not decide: the residual's ``provisional_unreviewed`` mark is the
        producer's (``aeh.agg`` writes it when it routes the row), and the
        three prohibitions keep it that way — ``end_session`` and ``close_run``
        persist the residual by leaving it exactly where it stands. The acted
        rows' state updates are #110's store write; until then an acted row is
        visible through ``labels_for`` and has left the count through the
        acted set."""
        return tuple(self._admitted_rows())

    def labels_for(self, run_id: str = "run-1") -> tuple[LabelRecord, ...]:
        """The labels this service has written, in write order — the in-memory
        read the residual's no-backfill assertion reads (`FR-REVIEW-08`: a
        residual item gains no label nobody entered) and the refusal case of
        `CT-REVIEW-15` checks. The label store's own persistence surface is
        #110's; until then the labels live here, and ``run_id`` is
        bookkeeping."""
        return tuple(self._labels)

    def end_session(self, run_id: str = "run-1") -> ResidualReport:
        """Close the sitting (`FR-REVIEW-08`'s first vanishing moment): the
        residual persists. The acted set, the labels and every residual row's
        ``provisional_unreviewed`` state survive it untouched — clearing per
        sitting would silently convert "not reviewed" into "reviewed and
        accepted" — so the next sitting's queue still owes exactly what this
        one did not finish. Nothing is mutated; the report is the moment."""
        return self._residual_report(run_id, moment="end_session")

    def close_run(self, run_id: str = "run-1") -> ResidualReport:
        """Close the run (`FR-REVIEW-08`'s second vanishing moment): the run's
        close is where finalization pressure lands, and neither prohibition is
        met. No residual row is finalized, none gains a label nobody entered,
        and ``scores()`` keeps returning every one of them — the residual does
        not answer to the run's lifecycle. Nothing is mutated; the report is
        the moment."""
        return self._residual_report(run_id, moment="close_run")

    def _residual_report(self, run_id: str, *, moment: str) -> ResidualReport:
        """The residual as the moment leaves it: every still-flagged row, in
        the state `FR-REVIEW-08` marks it with. ``finalized``/``backfilled``
        are what the moment wrote — nothing, by construction, since the service
        writes no state and no label at a session or run boundary; the lists
        exist so a later change that does write one has a field to carry it
        in.

        ``state`` reports the ordinary residual mark. A residual can also hold
        an unacted ``ungradeable_by_panel`` row (it routes ``provisional``,
        so it is admitted and still unreviewed); consumers keep that state
        distinct per `CT-AGG-07`, and #110's store form carries the per-state
        counts when the report gains them."""
        residual = self._admitted_rows()
        return ResidualReport(
            run_id=run_id,
            moment=moment,
            residual_provisional=len(residual),
            state=_RESIDUAL_STATE,
            finalized=(),
            backfilled=(),
        )

    # -- internals -----------------------------------------------------------------------------------

    def _admitted_rows(self) -> list[Any]:
        """The still-flagged rows this run admits (`_admitted`), minus the ones
        this service has already acted on."""
        return [
            row for row in _admitted(self._rows) if _score_id_of(row) not in self._acted
        ]

    def _as_item(self, item: Any) -> ReviewItem:
        """The queue entry an action arrives on. A ``ReviewGroup`` is not an
        action target — ``act_on_group`` is the group's path."""
        if getattr(item, "members", None) is not None:
            raise ReviewError(
                "act() takes a single review item; a group is acted on through "
                "act_on_group, which writes one label per member"
            )
        if getattr(item, "score_id", None) is None:
            raise ReviewError("act() takes a queue item carrying score_id")
        return item

    def _check_not_stale(self, item: ReviewItem) -> None:
        current = self._versions.get(item.score_id)
        if current is None and self._store is not None:
            # A store-backed service (one per console request, #398) compares against the
            # stored row it loaded: that row is the current version of the score.
            stored = [row for row in self._rows if _score_id_of(row) == item.score_id]
            if stored:
                current = int(getattr(stored[0], "version", 1) or 1)
        if current is not None and current != item.version:
            raise StaleReviewItemError(
                f"score {item.score_id!r} is stale: it was superseded by an escalation "
                f"(the store now carries version {current}, the queue built version "
                f"{item.version}); refresh the queue before acting"
            )
