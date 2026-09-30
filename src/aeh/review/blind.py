"""The blind sample (bands given without seeing the system's) and the whole-grade sample."""

from __future__ import annotations

import random
from types import SimpleNamespace
from typing import Any, Mapping

from .settings import BLIND_SAMPLE_RANGE, REVIEW_DEFAULT_BANDS, WHOLE_GRADE_SAMPLE_RANGE
from .errors import ReviewError
from .schema import REVIEW_STATEMENTS
from .records import (
    BlindItem,
    BlindSampleSkipReport,
    BlindSession,
    LabelRecord,
    SubmissionGrade,
    WriteRecord,
)
from .stored_rows import _newest_run_id, _row_mapping


class BlindSamplingMixin:
    """Draws and collects the blind sample and the whole-grade sample."""

    # -- the two samples, and the skip (#111) ---------------------------------------------------------

    def _rng(self, draw_index: int) -> random.Random:
        """One draw's RNG: derived from the service's seed and the draw's
        index, so the same seed reproduces the same *sequence* of draws while
        successive draws on one service differ — a second sitting draws fresh
        refs instead of re-drawing the first's (`CT-REVIEW-11`'s uniformity is
        per draw, and a per-run rate aggregates sittings). A declared seed of
        ``None`` stays entropy-per-draw: an undeclared seed must not silently
        pin every administration to the same sample, which is first-N's defect
        in disguise."""
        if self._seed is None:
            return random.Random()
        # A str seed, not a tuple: Random() accepts only None/int/float/str/
        # bytes/bytearray, and str's version-2 seeding is a sha512 digest, so
        # the derived seed is deterministic across processes, not hash-ordered.
        return random.Random(f"{self._seed}:{draw_index}")

    def blind_sample(self, run_id: str = "run-1", n: int | None = None) -> BlindSession:
        """Draw the blind sample (`FR-REVIEW-12`): 15–25 judged refs at random
        over judged criteria, as one ``BlindSession``. The draw is
        ``self._rng``-seeded ``sample`` over the admitted judged population —
        uniform over the eligible set, reproducible from the service's seed,
        and never first-N (`CT-REVIEW-11`'s distribution case). A pool smaller
        than ``n`` floors the draw at the pool (the interpretations); a request
        outside ``BLIND_SAMPLE_RANGE`` is refused, naming the range.

        A run that recorded its skip refuses to draw: the skip's one
        consequence is the missing evidence, and a draw after a skip would
        make the skip's report false (see ``skip_blind_sample``).

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
        if run_id in self._skipped_runs:
            raise ReviewError(
                f"run {run_id!r} skipped its blind sample, so it does not draw one: "
                "a run either draws its sample or skips it. Drawing after a skip would make "
                "the skip's report — no new validation evidence — false, and the report is "
                "the clause's whole content (FR-REVIEW-13)"
            )
        pool: list[BlindItem] = []
        seen: set[tuple[str, str]] = set()
        for row in self._admitted_rows():
            ref = BlindItem(
                submission_id=str(getattr(row, "submission_id", "") or ""),
                criterion_id=str(getattr(row, "criterion_id", "") or ""),
                evaluation_mode=str(getattr(row, "evaluation_mode", "") or ""),
            )
            key = (ref.submission_id, ref.criterion_id)
            if key in seen:
                continue
            seen.add(key)
            pool.append(ref)
        drawn = tuple(
            self._rng(len(self._blind_sessions)).sample(pool, min(count, len(pool)))
        )
        self._blind_drawn[run_id] = self._blind_drawn.get(run_id, 0) + len(drawn)
        session = BlindSession(
            session_id=f"blind-{len(self._blind_sessions) + 1:04d}",
            run_id=run_id,
            items=drawn,
        )
        self._blind_sessions[session.session_id] = session
        return session

    def submit_blind(
        self,
        session_id: str,
        bands: Mapping[BlindItem, str],
        *,
        interrupted: bool = False,
        review_seconds: float = 0,
    ) -> list[str]:
        """Submit a blind sitting's answers (`FR-REVIEW-12`'s collection path,
        `CT-REVIEW-15`'s interrupted half): one ``blind`` label per answered
        ref — ``saw_system_output = 0`` (earned: the session could not reach
        the output, `CT-REVIEW-09` step 4), ``system_band = None``, no
        ``review_queue_action`` — and nothing for a ref the teacher never
        answered. A ref the session never drew is refused: a band for a
        criterion the flow never posed is a judgement nobody made.

        ``interrupted`` records that the sitting ended early; the labels
        written are the answered ones either way, which is the clause in both
        directions. The session submits once — a second submission is refused
        rather than double-written. Returns the label ids in the session's
        draw order."""
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
        # A ref the label store already holds a blind label for is not written again
        # (FR-CONSOLE-02, #398): a repeated submission from a fresh console holds no
        # memory of the first, and a second blind label would be counted twice.
        recorded = self._recorded_blind_labels(session.run_id)
        written = [
            (ref, self._write_blind_label(
                ref,
                band,
                interrupted=interrupted,
                review_seconds=review_seconds,
            ))
            for ref in session.items
            if (band := bands.get(ref)) is not None
            and (ref.submission_id, ref.criterion_id) not in recorded
        ]
        labels = [label for _ref, label in written]
        self._blind_submitted.add(session_id)
        self._join_blind_system_bands(session)
        run_id = session.run_id
        self._blind_answered[run_id] = self._blind_answered.get(run_id, 0) + len(labels)
        self._record_action_emission(labels)
        rate = self._blind_rate(run_id)
        self._record_emission(
            run_id, ("blind_completion_rate",), {"blind_completion_rate": rate}
        )
        return [label.label_id for label in labels]

    def whole_grade_sample(
        self, run_id: str = "run-1", n: int | None = None
    ) -> tuple[SubmissionGrade, ...]:
        """Draw the whole-grade sample (`FR-REVIEW-14`): 10–15 complete final
        grades from the auto-accepted population, each as the student would
        receive it. The population is the submissions whose **every** criterion
        row routed ``auto`` — sampling reviewed grades would measure the review,
        not the system, so the restriction is the clause's point
        (`CT-REVIEW-11`'s membership assertion), and a submission holding a
        reviewed criterion is excluded with them: its grade mixes the teacher's
        corrections into what is presented as the system's work, and a partial
        band set presented as a final grade understates it. One grade per
        submission, bands mapped to points through the one pinned mapping (the
        default-policy sum — a package grade policy supersedes it the moment
        one is attached); the offer writes no label. A request outside
        ``WHOLE_GRADE_SAMPLE_RANGE`` is refused, naming the range."""
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

    def skip_blind_sample(self, run_id: str = "run-1") -> BlindSampleSkipReport:
        """Record that this administration skips the blind sample
        (`FR-REVIEW-13`): exactly one consequence — no new validation evidence
        for this administration — and the report states the absence rather
        than filling it. Grades deliver and finalize normally
        (``ResidualReport.grades_delivered``/``grades_finalized``); the
        report's ``current_figure`` is ``None``, never a previous
        administration's figure. Idempotent: skipping twice skips once.

        A run that already drew refuses the skip: the draw *is* validation
        evidence, and recording a skip beside it would make the report say
        "no new validation evidence was collected" about a run whose counter
        says otherwise. A run either draws its sample or skips it; the two
        refusals (this one, and ``blind_sample``'s against a skipped run) are
        what keep the report and the evidence in agreement."""
        if self._blind_drawn.get(run_id):
            raise ReviewError(
                f"run {run_id!r} already drew a blind sample "
                f"({self._blind_drawn[run_id]} refs on record): there is no skip to record. "
                "A run either draws its sample or skips it — recording a skip beside a draw "
                "would report 'no new validation evidence' about a run that holds it"
            )
        self._skipped_runs.add(run_id)
        return self.skip_report(run_id)

    def skip_report(self, run_id: str = "run-1") -> BlindSampleSkipReport:
        """A run's skip, read back as the report (`FR-REVIEW-13`): whether the
        sample was skipped, the consequence said in words, and
        ``current_figure = None`` — the honest None, whatever an earlier
        administration produced."""
        skipped = run_id in self._skipped_runs
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

    def render_blind_flow(self, session_id: str) -> str:
        """The blind flow as the teacher sees it (`CT-REVIEW-09` step 2's
        rendered probe): the drawn refs and the fixed band scale, built from
        the session alone. Nothing the system decided can appear here, because
        the session carries nothing the system decided — the render is a
        projection of identity fields, not a template filtering a richer
        object."""
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
        """The run's blind completion rate (`CT-REVIEW-18`): answered refs over
        drawn refs, from the service's own bookkeeping. ``None`` for a run
        that never drew — an unmeasured rate, never a silent zero."""
        drawn = self._blind_drawn.get(run_id)
        if not drawn:
            return None
        return self._blind_answered.get(run_id, 0) / drawn

    def _row_for_ref(self, ref: BlindItem) -> Any:
        """The score row a blind ref came from — the *service's* lookup, for
        the label's routing/origin metadata. The session never sees it: the
        guarantee is a property of what the session carries, not of what the
        service's internals hold."""
        for row in self._rows:
            if (
                str(getattr(row, "submission_id", "") or "") == ref.submission_id
                and str(getattr(row, "criterion_id", "") or "") == ref.criterion_id
            ):
                return row
        return None

    def _auto_grade_population(self) -> list[tuple[str, str, str]]:
        """The whole-grade sample's population (`FR-REVIEW-14`): the
        completely auto-accepted submissions, as ``(submission_id,
        criterion_id, band)`` triples — a submission holding any row with
        another routing is excluded with the reviewed ones, because the grade
        presented must be complete and wholly the system's (a partial band set
        shown as the student's final grade understates it; a mixed one shows
        the teacher's corrections as system work). The store form reads them
        through the declared ``select_auto_grades`` statement, whose NOT IN
        guard carries the same restriction — the service's own fetch admits
        only the teacher's routings, so the sample needs its own declared read
        (a ``.query``, never a runtime assembly, SEC-15); the in-memory form
        filters its own rows to the same set."""
        if self._store is not None:
            triples: list[tuple[str, str, str]] = []
            for cohort_id in self._cohort_ids:
                run_id = _newest_run_id(self._store, cohort_id)
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
    ) -> LabelRecord:
        """One blind label (#111): the same record an action writes, collected
        by the flow that could not see the output. ``score_id`` is ``None`` —
        the flow cannot reach a score row, so there is no score id to name and
        the honest label says so; ``review_queue_action`` is ``None`` — this is
        not a queue action; ``system_band`` is ``None`` and
        ``saw_system_output`` is 0, earned by the session's construction
        (`CT-REVIEW-09` step 4). The band is the teacher's alone; its points
        ride the one pinned mapping (`NFR-AGG-02`). Writes no reduction: the
        row stays flagged — a blind label is evidence about the system, not a
        resolution of it (`CT-REVIEW-06`'s indirection is the queue's)."""
        row = self._row_for_ref(ref)
        label = LabelRecord(
            label_id=self._mint_label_id(),
            label_type="blind",
            saw_system_output=0,
            routing=str(getattr(row, "routing", "queued") or "queued")
            if row is not None
            else "queued",
            origin=str(getattr(row, "origin", "escalation") or "escalation")
            if row is not None
            else "escalation",
            evaluation_mode=ref.evaluation_mode,
            review_seconds=review_seconds,
            system_band=None,
            teacher_band=band,
            actor=self._actor_name,
            timestamp=self._clock(),
            score_id=None,
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
        """CT-REVIEW-07 for blind labels (#518): every stored label carries both bands.

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
            row = self._rows_by_id.get(f"{stored['student_ref']}:{stored['criterion_id']}")
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

    def _recorded_blind_labels(self, run_id: str) -> set[tuple[str, str]]:
        """`(submission, criterion)` refs that already carry a durable blind label."""
        if self._store is None:
            return set()
        attributed = self._attribution_run() or run_id
        rows = self._store.durable().query(
            REVIEW_STATEMENTS["select_blind_labels_for_run"], run_id=attributed)
        return {(str(row["student_ref"]), str(row["criterion_id"])) for row in rows}
