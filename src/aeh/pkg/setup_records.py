"""What M-SETUP records through the catalog: proposals, inventory, read-back, steps."""

from __future__ import annotations

import json
import uuid
from typing import Any, Mapping, Sequence

from .vocabulary import _declared_evaluation_mode, LOGGER, PackageVersionId
from .errors import PackageError, SchemaLockViolation
from .lock import SCHEMA_LOCK_VIOLATIONS
from .statements import PKG_STATEMENTS


class SetupRecordsMixin:
    """Records what M-SETUP produces: proposals, the confirmed inventory, the read-back, step provenance."""

    def append_elicitation(
        self, v: PackageVersionId, question: str, options_offered: Sequence[str],
        answer_given: str, resulting_edit: str = "",
    ) -> str:
        """Append one calibration-history row (FR-PKG-20, FR-CALIB-14): the question, the options
        offered, the teacher's answer and the resulting edit. Appending is allowed on published
        versions, because the history records discussions about the rubric as it stands. The table
        is append-only in fact: triggers refuse every update and delete, and there is no method for
        either."""
        elicitation_id = uuid.uuid4().hex
        with self._handle.transaction() as tx:
            tx.execute(PKG_STATEMENTS["insert_elicitation"], id=elicitation_id, v=v,
                       question=question,
                       options_offered=json.dumps(list(options_offered)),
                       answer_given=answer_given, resulting_edit=resulting_edit)
        return elicitation_id

    def record_proposal(
        self, v: PackageVersionId, *, proposal_id: str, assessment_doc_id: str,
        payload: str, template_version: str, model_ref: str, attempts: int,
    ) -> None:
        """Store the version's unconfirmed inventory proposal, or replace it when the model is
        asked again (CT-SETUP-12). Refused once a proposal is confirmed, because the inventory is
        then locked (FR-SETUP-02, CT-SETUP-16)."""
        self._refuse_unknown_version(v)
        self._refuse_mutation(v)
        row = self._handle.query(PKG_STATEMENTS["select_proposal"], v=v)
        if row and row[0]["confirmed_at"] is not None:
            raise PackageError(
                f"the inventory for version {v!r} was confirmed at "
                f"{row[0]['confirmed_at']}; the question rows are locked (FR-SETUP-02) "
                "and proposing again is out of order (CT-SETUP-16). A new instrument "
                "is a new version (FR-PKG-02)."
            )
        with self._handle.transaction() as tx:
            if row:
                tx.execute(PKG_STATEMENTS["update_proposal_payload"], v=v,
                           payload=payload, attempts=attempts)
            else:
                tx.execute(PKG_STATEMENTS["insert_proposal"], v=v,
                           proposal_id=proposal_id,
                           assessment_doc_id=assessment_doc_id, payload=payload,
                           template_version=template_version, model_ref=model_ref,
                           attempts=attempts)
        LOGGER.info("recorded inventory proposal %s for version %s (attempt %d)",
                    proposal_id, v, attempts)

    def proposal(self, v: PackageVersionId) -> dict | None:
        """The version's proposal row, or None. Resuming setup reads this instead of proposing
        again."""
        rows = self._handle.query(PKG_STATEMENTS["select_proposal"], v=v)
        return dict(rows[0]) if rows else None

    def write_confirmed_inventory(
        self, v: PackageVersionId, *, proposal_id: str,
        questions: Sequence[Mapping], confirmed_at: str,
    ) -> None:
        """Write the confirmed inventory in one transaction (FR-SETUP-02): the questions, their
        options and the proposal's confirmation stamp, all or nothing. A half-written inventory
        that the publish gate could misread is worse than a refused confirmation.

        Each question record is a mapping with `question_id`, `ordinal`,
        `prompt_text`, `question_type`, `max_points` and `options` (a sequence of
        mappings with `option_id`, `ordinal`, `label`). The structural validation here
        is M-PKG's own (CT-PKG-12) — it does not trust the caller's check. Refused when
        the proposal is unknown, already confirmed, or a different proposal id; refused
        on a published version. `reference_solution` is NOT written here: confirmation
        locks everything except it, and the rubric read-back (#51) fills it."""
        self._refuse_unknown_version(v)
        self._refuse_mutation(v)
        row = self._handle.query(PKG_STATEMENTS["select_proposal"], v=v)
        if not row:
            raise PackageError(
                f"no inventory proposal is recorded for version {v!r}: confirm_inventory "
                "confirms a proposal, and propose_inventory has not run."
            )
        if row[0]["confirmed_at"] is not None:
            raise PackageError(
                f"the inventory for version {v!r} is already confirmed "
                f"(at {row[0]['confirmed_at']}); it is locked (FR-SETUP-02) and cannot "
                "be confirmed again."
            )
        if row[0]["proposal_id"] != proposal_id:
            raise PackageError(
                f"confirmation names proposal {proposal_id!r} but version {v!r} holds "
                f"{row[0]['proposal_id']!r} — a stale or foreign confirmation is "
                "refused; the teacher confirms what was proposed."
            )
        validated = self._validated_inventory(questions)
        with self._handle.transaction() as tx:
            for question in validated:
                tx.execute(PKG_STATEMENTS["insert_question"], v=v,
                           question_id=question["question_id"],
                           ordinal=question["ordinal"],
                           prompt_text=question["prompt_text"],
                           question_type=question["question_type"],
                           max_points=question["max_points"],
                           reference_solution=None, confirmed_at=confirmed_at)
                for option in question["options"]:
                    tx.execute(PKG_STATEMENTS["insert_question_option"], v=v,
                               question_id=question["question_id"],
                               option_id=option["option_id"],
                               ordinal=option["ordinal"], label=option["label"])
            tx.execute(PKG_STATEMENTS["confirm_proposal"], v=v,
                       confirmed_at=confirmed_at)
        LOGGER.info("confirmed inventory for version %s: %d question(s), proposal %s",
                    v, len(validated), proposal_id)

    def questions(self, v: PackageVersionId) -> tuple[dict, ...]:
        """The version's confirmed questions, in confirmed order."""
        return tuple(
            dict(row) for row in
            self._handle.query(PKG_STATEMENTS["select_questions"], v=v)
        )

    def question_options(
        self, v: PackageVersionId, question_id: str
    ) -> tuple[dict, ...]:
        """One confirmed question's options, in declared order."""
        return tuple(
            dict(row) for row in
            self._handle.query(PKG_STATEMENTS["select_options_by_question"],
                               v=v, question_id=question_id)
        )

    def update_question_field(
        self, v: PackageVersionId, question_id: str, field: str, value: Any
    ) -> None:
        """Change one field of a confirmed question, subject to the confirmation lock.

        A CONFIRMED question row refuses every field except `reference_solution`
        (`FR-SETUP-02`: the lock engages at confirmation, earlier than publication —
        the confirmation IS the teacher's assertion about content, and HLD §7.8 names
        the open/mcq conversion a redefinition). A published version refuses everything
        (`PublishedVersionImmutableError`), and the triggers backstop the same rule for
        writes that route around the catalog."""
        writable = ("prompt_text", "ordinal", "max_points", "question_type",
                    "reference_solution")
        if field not in writable:
            raise PackageError(
                f"question field {field!r} is not writable here; writable fields: "
                f"{', '.join(writable)}."
            )
        self._refuse_unknown_version(v)
        self._refuse_mutation(v)
        rows = self._handle.query(PKG_STATEMENTS["select_question"], v=v,
                                  question_id=question_id)
        if not rows:
            raise PackageError(
                f"question {question_id!r} does not exist in version {v!r}."
            )
        if rows[0]["confirmed_at"] is not None and field != "reference_solution":
            SCHEMA_LOCK_VIOLATIONS.increment()
            LOGGER.warning(
                "schema lock violation: the question.%r edit on question %r in version "
                "%r is refused (FR-SETUP-02) — the inventory was confirmed and the "
                "edit would redefine what was asked", field, question_id, v,
            )
            raise SchemaLockViolation(
                f"the question.{field} edit on question {question_id!r} in version "
                f"{v!r} is refused: the inventory was confirmed at "
                f"{rows[0]['confirmed_at']} and its content is locked (FR-SETUP-02). "
                "Corrections happen before confirmation; a published version's "
                f"sanctioned vehicle is a new version (create_version(parent={v!r}))."
            )
        with self._handle.transaction() as tx:
            tx.execute(PKG_STATEMENTS[f"update_question_{field}"], v=v,
                       question_id=question_id, value=value)

    def readback(self, v: PackageVersionId) -> dict | None:
        """The version's rubric read-back row, or None. Resuming setup reads this instead of
        reading the rubric again (CT-SETUP-03); the row exists only after a read-back finished or
        fell back."""
        rows = self._handle.query(PKG_STATEMENTS["select_readback"], v=v)
        return dict(rows[0]) if rows else None

    # -- #52: the decomposability verdicts and the setup steps' provenance ---------------

    def record_classification(
        self, v: PackageVersionId, *, criterion_id: str, classification: str,
        decomposition_basis: str | None, source: str, recorded_at: str,
    ) -> None:
        """Store one decomposability classification (FR-SETUP-06, R62).

        `source` is `'default'` (the module's §5.3 table decided, the teacher has not
        spoken) or `'teacher'` (`confirm_classifications` upserts over the default row
        — the teacher's judgment replaces it as the stored record, which is exactly
        the distinction M-CALIB and M-STATS read). Refused on a published version
        (the published-immunity triggers)."""
        if source not in ("default", "teacher"):
            raise PackageError(
                f"classification source {source!r} is outside the vocabulary "
                "('default', 'teacher') — a row that cannot say who spoke cannot "
                "distinguish a teacher's judgment from a system default (R62)."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion.add")
            tx.execute(PKG_STATEMENTS["insert_classification"], v=v,
                       criterion_id=criterion_id, classification=classification,
                       decomposition_basis=decomposition_basis, source=source,
                       recorded_at=recorded_at)
        self._invalidate()

    def classifications(self, v: PackageVersionId) -> tuple[dict, ...]:
        """The version's stored classifications, ordered by criterion id; M-CALIB and M-STATS read
        these to tell teacher choices from defaults."""
        return tuple(
            dict(row) for row in
            self._handle.query(PKG_STATEMENTS["select_classifications"], v=v)
        )

    def classification(self, v: PackageVersionId,
                       criterion_id: str) -> dict | None:
        """One criterion's stored classification, or None."""
        rows = self._handle.query(PKG_STATEMENTS["select_classification"], v=v,
                                  criterion_id=criterion_id)
        return dict(rows[0]) if rows else None

    def record_step(
        self, v: PackageVersionId, *, step_id: str, status: str, payload: str,
        recorded_at: str,
    ) -> None:
        """Insert or update one setup step's provenance row (FR-SETUP-14).

        The write half of "a default taken is recorded": each optional setup step
        names itself here when it completes — by the teacher's action or, at
        publish, as a recorded default. `payload` is the step's own JSON summary."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion.add")
            tx.execute(PKG_STATEMENTS["insert_step_record"], v=v, step_id=step_id,
                       status=status, payload=payload, recorded_at=recorded_at)
        self._invalidate()

    def record_default_step(
        self, v: PackageVersionId, *, step_id: str, status: str, payload: str,
        recorded_at: str,
    ) -> bool:
        """Record that a step's default was taken, only if the step has no row of its own
        (FR-SETUP-14). Returns whether a row was written; a step that was already recorded is never
        overwritten."""
        if self.step_record(v, step_id) is not None:
            return False
        # The guard runs BEFORE the transaction, not inside it — the shape the
        # catalog's own publish() uses. This write sits on the publish path's
        # happy tail, and CT-SETUP-02 audits that path to exactly ONE
        # lock-carrying statement: an in-transaction guard would put a second
        # package_version statement (the guard's SELECT) in the audited window.
        self._refuse_mutation(v)
        with self._handle.transaction() as tx:
            tx.execute(PKG_STATEMENTS["insert_step_record"], v=v, step_id=step_id,
                       status=status, payload=payload, recorded_at=recorded_at)
        self._invalidate()
        return True

    def step_record(self, v: PackageVersionId, step_id: str) -> dict | None:
        """One setup step's provenance row, or None. The console reads this to show which steps are
        done."""
        rows = self._handle.query(PKG_STATEMENTS["select_step_record"], v=v,
                                  step_id=step_id)
        return dict(rows[0]) if rows else None

    def step_records(self, v: PackageVersionId) -> tuple[dict, ...]:
        """All of the version's setup-step rows, ordered by step id."""
        return tuple(
            dict(row) for row in
            self._handle.query(PKG_STATEMENTS["select_step_records"], v=v)
        )

    def write_readback(
        self, v: PackageVersionId, *, rubric_doc_id: str, assessment_doc_id: str,
        criteria: Sequence[Mapping], payload: str, template_version: str,
        model_ref: str, attempts: int, created_at: str,
    ) -> None:
        """Write the rubric read-back in one transaction (FR-SETUP-04, FR-SETUP-05, FR-SETUP-09):
        every criterion with its bands, `evidence_type` and `band_justification`, plus the
        read-back's provenance row. All or nothing (CT-PKG-11), so a failed read-back leaves
        nothing behind.

        Each criterion record is a mapping with `criterion_id`, `question_id`, `kind`,
        `max_points`, `scoring_model`, `band_count`, `evidence_type`,
        `band_justification`, an optional `evaluation_mode` (`FR-PKG-22`: `judged` or
        `deterministic`, defaulting from `kind` when the record does not declare one, and
        REFUSED if it is anything else) and `bands` (a sequence of mappings with `band`,
        `ordinal`, `points`, `descriptor`). The structural validation here is M-PKG's own
        (`CT-PKG-12`) — the band rules are the same ones `add_criterion`/`add_band`
        enforce (`FR-PKG-06`), plus the read-back's own rule: a `band_count` above two
        carries a recorded justification (`FR-SETUP-04`). Descriptor CONTENT is not
        checked here — the magnitude-phrase bar is M-SETUP's Configuration
        (`FR-SETUP-05`), and this module does not import it. Refused when a read-back
        row already exists for the version (one read back per version, `CT-SETUP-16`),
        on a published version, or for a criterion id the version already carries."""
        self._refuse_unknown_version(v)
        self._refuse_mutation(v)
        if self._handle.query(PKG_STATEMENTS["select_readback"], v=v):
            raise PackageError(
                f"version {v!r} already holds a rubric read-back (CT-SETUP-16: one "
                "read back per version) — the stored row is provenance and is not "
                "replaced; the rubric read-back resumes from it."
            )
        validated = self._validated_readback(criteria)
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion.add")
            for criterion in validated:
                existing = [row["criterion_id"] for row in tx.execute(
                    PKG_STATEMENTS["select_criteria"], v=v)]
                if criterion["criterion_id"] in existing:
                    raise PackageError(
                        f"criterion {criterion['criterion_id']!r} already exists in "
                        f"version {v!r} — the read back writes criteria onto a clean "
                        "draft, not over rows another path added."
                    )
                if not tx.execute(PKG_STATEMENTS["select_question"], v=v,
                                  question_id=criterion["question_id"]):
                    raise PackageError(
                        f"criterion {criterion['criterion_id']!r} names question "
                        f"{criterion['question_id']!r}, which the version's CONFIRMED "
                        "inventory does not carry — criteria anchor to confirmed "
                        "questions (FR-SETUP-02)."
                    )
                tx.execute(PKG_STATEMENTS["insert_readback_criterion"], v=v,
                           criterion_id=criterion["criterion_id"],
                           question_id=criterion["question_id"],
                           kind=criterion["kind"],
                           max_points=criterion["max_points"],
                           scoring_model=criterion["scoring_model"],
                           construct_tag=criterion["construct_tag"],
                           band_count=criterion["band_count"],
                           evidence_type=criterion["evidence_type"],
                           band_justification=criterion["band_justification"],
                           # `FR-SETUP-17`: the readback carries the mode when the
                           # proposal declared one, and otherwise takes the shape
                           # default — bound explicitly at the insert either way, never
                           # left to the column's DDL default.
                           evaluation_mode=_declared_evaluation_mode(criterion))
                for band in criterion["bands"]:
                    tx.execute(PKG_STATEMENTS["insert_band"], v=v,
                               criterion_id=criterion["criterion_id"],
                               ordinal=band["ordinal"], band=band["band"],
                               points=band["points"], descriptor=band["descriptor"])
                rows = [row for row in tx.execute(
                    PKG_STATEMENTS["select_bands"], v=v)
                    if row["criterion_id"] == criterion["criterion_id"]]
                self._validate_band_order(rows)
            tx.execute(PKG_STATEMENTS["insert_readback"], v=v,
                       rubric_doc_id=rubric_doc_id,
                       assessment_doc_id=assessment_doc_id, payload=payload,
                       template_version=template_version, model_ref=model_ref,
                       attempts=attempts, created_at=created_at)
        self._invalidate()
        LOGGER.info(
            "wrote rubric read-back for version %s: %d criterion(s), prompt %s, "
            "attempt %d", v, len(validated), template_version, attempts,
        )
