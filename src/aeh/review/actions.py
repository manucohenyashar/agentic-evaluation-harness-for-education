"""Teacher decisions: acting on one item or a group, and writing and settling the label."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from .settings import _EDIT_VIEWS
from .errors import ReviewError
from .schema import REVIEW_STATEMENTS
from .records import BlindItem, LabelRecord, ReviewItem, SupersededScore, WriteRecord
from .ranking import _ACTIONS


class ActionsMixin:
    """Records a teacher's decision as a label and settles the score it is about."""

    def act(
        self,
        item: Any,
        action: str,
        new_band: str | None = None,
        review_seconds: float = 0,
    ) -> str | None:
        """Record one teacher decision on one queue item (design §3.15).

        ``accept`` keeps the proposed band; ``edit``/``override`` name a new one
        — an edit without a band is refused, because there is nowhere to put a
        number (`FR-REVIEW-10`); ``skip`` writes no label and leaves the item
        residual (`CT-REVIEW-06`). Acting on a superseded score is refused with
        a refresh message (`CT-REVIEW-15`). Returns the label id, or None.

        Every write the action makes is audited (`CT-REVIEW-06`): a
        ``criterion_score`` record for the reduction through the score row and
        a ``label`` record for the label itself — a ``skip`` writes nothing at
        all."""
        if action not in _ACTIONS:
            raise ValueError(f"{action!r} is not a review action; one of {_ACTIONS}")
        if action == "skip":
            return None
        if action in ("edit", "override") and new_band is None:
            raise ValueError("an edit names a band")
        item = self._as_item(item)
        self._check_not_stale(item)
        teacher_band = item.proposed_band if action == "accept" else new_band
        recorded = self._recorded_decision(item, action, teacher_band)
        if recorded is not None:
            # The same decision on the same score is already in the label store: a
            # repeated post (double-click, second tab) writes no second label
            # (FR-CONSOLE-02). The settle is re-applied, and it is idempotent: a first post
            # whose label landed but whose settle failed is repaired by the retry (#517).
            self._settle_band(item, teacher_band)
            self._acted.add(item.score_id)
            return recorded
        label = self._write_label(
            item,
            label_type=action,
            teacher_band=item.proposed_band if action == "accept" else new_band,
            review_seconds=review_seconds,
            review_queue_action=action,
        )
        self._record_writes(item, action, label)
        self._settle_score(item, label)
        self._acted.add(item.score_id)
        self._record_queue_action(item, action, label)
        self._record_action_emission([label])
        return label.label_id

    def act_on_group(self, group: Any, band: str, review_seconds: float = 0) -> list[str]:
        """Apply one band decision to a whole group (design §3.15). It writes one label per member
        (CT-REVIEW-13), each with the member's identity and its share of the time; a single label
        for the group would under-count bulk decisions in every agreement figure."""
        members = tuple(getattr(group, "members"))
        if not members:
            return []
        per_member = review_seconds / len(members)
        label_ids: list[str] = []
        labels: list[LabelRecord] = []
        for member in members:
            self._check_not_stale(member)
            action = "accept" if band == member.proposed_band else "edit"
            label = self._write_label(
                member,
                label_type=action,
                teacher_band=band,
                review_seconds=per_member,
                review_queue_action=action,
                via_group=True,
            )
            self._record_writes(member, action, label)
            self._settle_score(member, label)
            self._acted.add(member.score_id)
            self._record_queue_action(member, action, label)
            labels.append(label)
            label_ids.append(label.label_id)
        self._record_action_emission(labels)
        return label_ids

    # -- the label store (FR-REVIEW-09 / FR-REVIEW-15, #110) ------------------------------------------

    def label(self, label_id: str) -> LabelRecord:
        """One label this service wrote, by id (CT-REVIEW-07)."""
        label = self._labels_by_id.get(label_id)
        if label is None:
            raise ReviewError(
                f"no label {label_id!r} in this service's label store; the ids "
                "act()/act_on_group()/act_from_view() returned are the store's ids"
            )
        return label

    def edit_views(self) -> tuple[str, ...]:
        """The views that show a band and so can carry a review action (FR-REVIEW-15). Listed
        explicitly so the parity test (CT-REVIEW-12) also covers views added later."""
        return _EDIT_VIEWS

    def act_from_view(
        self,
        item: Any,
        *,
        view: str,
        action: str,
        new_band: str | None = None,
        review_seconds: float = 0,
    ) -> str | None:
        """Record a teacher decision made outside the budgeted queue, from any view that shows a
        band (FR-REVIEW-15). After checking the view, it calls `act`, so an edit made anywhere
        writes the same queue action and the same label type."""
        if view not in self.edit_views():
            raise ReviewError(
                f"{view!r} is not a view that displays a band; review actions "
                f"are available from {self.edit_views()}"
            )
        return self.act(item, action, new_band=new_band, review_seconds=review_seconds)

    def escalate(self, score_id: str) -> SupersededScore:
        """Mark one score as superseded (CT-REVIEW-15). Every queue built before this call now
        holds an old version, and an action on it is refused with a message to refresh."""
        current = self._versions.get(score_id)
        if current is None:
            row = self._rows_by_id.get(score_id)
            current = int(getattr(row, "version", 1) or 1) if row is not None else 1
        bumped = current + 1
        self._versions[score_id] = bumped
        return SupersededScore(score_id=score_id, version=bumped)

    def _record_writes(self, item: ReviewItem, action: str, label: LabelRecord) -> None:
        """Record one action's writes in the audit list (CT-REVIEW-06): first the settlement of the
        score row, then the label."""
        self._audit.append(
            WriteRecord(
                table="criterion_score",
                score_id=item.score_id,
                detail=f"{action} leaves the flagged count through the score row",
            )
        )
        self._audit.append(
            WriteRecord(
                table="label",
                score_id=item.score_id,
                detail=f"{action} label {label.label_id}",
            )
        )

    def _write_label(
        self,
        item: ReviewItem,
        *,
        label_type: str,
        teacher_band: str | None,
        review_seconds: float,
        review_queue_action: str,
        via_group: bool = False,
    ) -> LabelRecord:
        row = self._rows_by_id.get(item.score_id)
        self._versions.setdefault(item.score_id, item.version)
        # ``new_points`` is derived from the band the label records through
        # `CT-PKG-05`'s pinned mapping (`FR-REVIEW-10`) — the same call the
        # derivation contract names (`points_for_band`), not a second table
        # (`NFR-AGG-02`). An accept records the system's proposed band; an
        # edit or override records the teacher's.
        effective_band = item.proposed_band if label_type == "accept" else teacher_band
        new_points = (
            self._points_for_band(
                package_version_id=getattr(item, "package_version_id", None),
                criterion_id=item.criterion_id,
                band=effective_band,
            )
            if effective_band is not None
            else None
        )
        label = LabelRecord(
            label_id=self._mint_label_id(),
            label_type=label_type,
            # A queue action happens with the system's band on the screen
            # (`CT-REVIEW-08`'s per-path values; the blind flow's earned 0 is #111's).
            saw_system_output=1,
            routing=str(getattr(row, "routing", "queued") or "queued"),
            origin=str(getattr(row, "origin", "escalation") or "escalation"),
            evaluation_mode=str(getattr(row, "evaluation_mode", "judged") or "judged"),
            review_seconds=review_seconds,
            system_band=item.proposed_band,
            teacher_band=teacher_band,
            actor=self._actor_name,
            timestamp=self._clock(),
            score_id=item.score_id,
            criterion_id=item.criterion_id,
            review_queue_action=review_queue_action,
            new_points=new_points,
            via_group=via_group,
        )
        # In-memory first, then the durable half (`CT-STORE-03`): a failure in
        # the durable write aborts the action with the in-memory record already
        # written, which is what the interpretations disclose.
        self._labels.append(label)
        self._labels_by_id[label.label_id] = label
        # Attribution is per-run (`NFR-REVIEW-04`): the label joins the run the
        # service last built a queue for, or the sole cohort the service was
        # opened over — never an invented run.
        run_id = self._attribution_run()
        if run_id is not None:
            self._run_labels.setdefault(run_id, []).append(label)
        if self._store is not None:
            if run_id is None:
                raise ReviewError(
                    "this service holds a store but no run context: build a queue "
                    "for the run (or open the service over exactly one cohort) "
                    "before acting — a label is not attributed to an invented run"
                )
            self._persist_label(label, run_id, item)
        return label

    def _mint_label_id(self) -> str:
        """A new label id. A store-backed service makes a globally unique id, because every console
        request builds a fresh service and a per-instance counter would repeat ids already stored.
        The storeless service keeps its deterministic counter for tests."""
        if self._store is not None:
            return f"label-{uuid.uuid4().hex}"
        return f"label-{len(self._labels) + 1:04d}"

    def _settle_score(self, item: Any, label: LabelRecord) -> None:
        """Settle the score row with the teacher's band through M-AGG's `record_review`, so
        M-GRADE's next pass counts the criterion as reviewed (CT-REVIEW-06). M-REVIEW writes no
        grade. A storeless service has no score row to settle."""
        self._settle_band(item, label.teacher_band)

    def _settle_band(self, item: Any, band: Any) -> None:
        """Settle one score row on `band`. The points are the package's points for that band (never
        the default display scale, which M-GRADE would then add up): an unchanged band keeps the
        row's points, a new band takes the package's points, or NULL if the package figure cannot
        be read. Safe to repeat."""
        if self._store is None or band is None:
            return
        row = self._rows_by_id.get(item.score_id)
        run_id = getattr(row, "run_id", None)
        cohort_id = self._writable_cohort()
        if run_id is None or cohort_id is None:
            return
        points = None
        if str(band) != str(getattr(row, "proposed_band", None)):
            probe = SimpleNamespace(system_band=None, teacher_band=band,
                                    criterion_id=item.criterion_id, timestamp=None)
            points = self._label_judgement_columns(probe, str(run_id))["teacher_points"]
        from aeh.agg import record_review

        with self._store.cohort(cohort_id).transaction() as tx:
            record_review(tx, str(run_id), item.submission_id, item.criterion_id,
                          str(band), points)

    def _recorded_decision(self, item: Any, action: str, teacher_band: Any) -> str | None:
        """The id of the score's latest stored label if it records this same decision, else None.
        Only a store-backed service has stored labels to check."""
        run_id = self._attribution_run()
        if self._store is None or run_id is None or teacher_band is None:
            return None
        rows = self._store.durable().query(
            REVIEW_STATEMENTS["select_latest_label_for_score"], run_id=run_id,
            score_id=item.score_id)
        # Only the LATEST decision on the score counts as "already recorded": edit B3, then
        # B1, then B3 again is three decisions, and the third must land.
        if rows and rows[0]["review_queue_action"] == action                 and rows[0]["teacher_band"] == teacher_band:
            return str(rows[0]["label_id"])
        return None

    def _attribution_run(self) -> str | None:
        """The run a label written now belongs to (NFR-REVIEW-04): the queue this service last
        built, or, before any build, the only cohort the service was opened over. None when neither
        applies. The stored row's `cohort_id` holds the same id, because the store flow uses the
        cohort id as the run id."""
        if self._current_run_id is not None:
            return self._current_run_id
        if len(self._cohort_ids) == 1:
            return self._cohort_ids[0]
        return None

    def _persist_label(
        self, label: LabelRecord, run_id: str, item: ReviewItem | BlindItem
    ) -> None:
        """Write the label to Tier D's `label` table in one statement, for a store-backed action
        (FR-REVIEW-09). The store has no cross-tier transactions (CT-STORE-03), so this runs after
        the in-memory record: a failure here aborts the action with the in-memory record already
        written. `item` supplies the student reference: the queue item acted on, or the blind
        reference drawn."""
        if label.teacher_band is None:
            raise ReviewError(
                f"label {label.label_id!r} records no band; Tier D's label table "
                "carries a band for every label, so an action without one is refused"
            )
        handle = self._store.durable()
        with handle.transaction() as tx:
            tx.execute(
                REVIEW_STATEMENTS["insert_label"],
                label_id=label.label_id,
                run_id=run_id,
                # The store rows carry no student identity (#108's mapping
                # records the same absence): the submission under review is
                # what the row can honestly reference in Phase 1.
                student_ref=item.submission_id,
                criterion_id=label.criterion_id,
                label_type=label.label_type,
                band=label.teacher_band,
                evaluation_mode=label.evaluation_mode,
                saw_system_output=label.saw_system_output,
                routing=label.routing,
                origin=label.origin,
                review_seconds=label.review_seconds,
                system_band=label.system_band,
                teacher_band=label.teacher_band,
                actor=label.actor,
                timestamp=label.timestamp,
                score_id=label.score_id,
                review_queue_action=label.review_queue_action,
                new_points=label.new_points,
                # `FR-REVIEW-22`: the COHORT, resolved from the rows this service
                # actually loaded — never the run id. The two are different values, and
                # M-STORE reads this column as a purge PRECONDITION ("Tier D holds a
                # promoted row for this cohort", `store.py:56`): a run id here means the
                # gate looks for a cohort that has no rows, so the purge it guards can
                # never pass. `None` where the cohort cannot be resolved, which fails the
                # same gate CLOSED — the safe direction, and honest about not knowing.
                cohort_id=self._writable_cohort(),
                **self._label_judgement_columns(label, run_id),
            )

    def _label_judgement_columns(
        self, label: LabelRecord, run_id: str
    ) -> dict[str, Any]:
        """The label's eight judgement columns: what the label agreed with, recorded when it is
        written (FR-REVIEW-21).

        Everything here is resolved best-effort and defaults to `None`, never to a
        flattering value: a `band_distance` the band scale cannot supply is unknown, and
        a zero would read as "the teacher agreed". `agreed` is the one figure that does
        not need the scale — two band ids are equal or they are not — so it is recorded
        even where the distance is not, which is what keeps `FR-STATS-24`'s override
        count computable on a store with no package behind it.
        """
        system_band = label.system_band
        teacher_band = label.teacher_band
        agreed: int | None = None
        if system_band is not None and teacher_band is not None:
            agreed = 1 if str(system_band) == str(teacher_band) else 0

        facts: dict[str, Any] = {
            "package_version_id": None,
            "assignment_type": None,
            "band_distance": None,
            "system_points": None,
            "teacher_points": None,
            "agreed": agreed,
            "panel_config": None,
            "recorded_at": label.timestamp or self._clock(),
            # FR-REVIEW-23 / CT-REVIEW-25 (#514): the run's frozen backend profile. NULL
            # when the run row cannot be read, which M-STATS excludes from every
            # backend-scoped figure as `backend_not_recorded` rather than guessing.
            "backend_profile": None,
        }

        cohort_id = self._writable_cohort()
        if cohort_id is None:
            return facts
        try:
            rows = self._store.cohort(cohort_id).query(
                REVIEW_STATEMENTS["select_run_package"], run_id=run_id
            )
        except Exception:
            return facts
        if not rows:
            return facts
        facts["package_version_id"] = rows[0]["package_version_id"]
        facts["panel_config"] = rows[0]["panel_config"]
        facts["backend_profile"] = rows[0]["backend_profile"] or None
        package_id = rows[0]["package_id"]

        try:
            from aeh.pkg import PackageCatalog

            catalog = PackageCatalog(
                self._store.package(package_id), package_id=package_id
            )
            version_id = facts["package_version_id"]
            # Primes the per-version cache BEFORE the two version-free readers below.
            declared = catalog.criteria(version_id)
            ordinals = {
                band["band"]: band["ordinal"]
                for band in catalog.bands(label.criterion_id)
            }
            if system_band in ordinals and teacher_band in ordinals:
                facts["band_distance"] = abs(
                    int(ordinals[system_band]) - int(ordinals[teacher_band])
                )
            if system_band is not None:
                facts["system_points"] = catalog.points_for_band(
                    label.criterion_id, system_band
                )
            if teacher_band is not None:
                facts["teacher_points"] = catalog.points_for_band(
                    label.criterion_id, teacher_band
                )
            for entry in declared:
                if entry["criterion_id"] != label.criterion_id:
                    continue
                # ONLY a declared population scope. `construct_tag` is a different
                # dimension and is deliberately NOT substituted: M-STATS reads a missing
                # `assignment_type` as "not recorded" and refuses to partition, which is
                # the honest answer — a construct tag here would produce a confident
                # figure partitioned on the wrong axis.
                if "assignment_type" in entry.keys():
                    facts["assignment_type"] = entry["assignment_type"]
                break
        except Exception:
            pass
        return facts
