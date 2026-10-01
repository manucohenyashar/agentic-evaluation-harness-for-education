"""The inventory step: the model proposes the questions, the teacher corrects and confirms them."""

from __future__ import annotations

import json
import uuid
from typing import Any, Mapping, Sequence

from aeh.ingest import DocumentId
from aeh.pkg import PackageVersionId, QUESTION_TYPES
from aeh.prov import PromptPayload

from .settings import (
    _configured_proposal_attempts,
    LOGGER,
    _now,
    SETUP_MCQ_BAND_NAMES,
    SETUP_PROMPT_TEMPLATE_V,
)
from .errors import _ReplyError, SetupError, SetupOrderError
from .records import InventoryProposal, ProposedOption, ProposedQuestion, QuestionCorrection
from .prompts import _INVENTORY_INSTRUCTION


def _deterministic_criterion_id(question_id: str) -> str:
    """The criterion id for a confirmed question's multiple-choice part: `CRIT-<question id>`, the
    id answer keys use (FR-SETUP-03)."""
    return f"CRIT-{question_id}"


def _parse_reply(text: str) -> tuple[ProposedQuestion, ...]:
    """Parse the model's reply into proposed questions, raising `_ReplyError` for anything that is
    not a valid inventory, so the attempt loop asks again. The reply should be one JSON object;
    prose around it is tolerated, JSON that is not an inventory is not."""
    stripped = text.strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start < 0 or end <= start:
        raise _ReplyError("the reply contains no JSON object.")
    try:
        parsed = json.loads(stripped[start:end + 1])
    except ValueError as error:
        raise _ReplyError(f"the reply is not valid JSON: {error}") from error
    if not isinstance(parsed, dict) or not isinstance(parsed.get("questions"), list):
        raise _ReplyError("the reply's JSON does not carry a 'questions' list.")
    if not parsed["questions"]:
        raise _ReplyError(
            "the reply proposes zero questions — the document asks something; an "
            "empty inventory is not a proposal."
        )
    questions: list[ProposedQuestion] = []
    seen_ids: set[str] = set()
    seen_ordinals: set[int] = set()
    for index, raw in enumerate(parsed["questions"]):
        if not isinstance(raw, dict):
            raise _ReplyError(f"question #{index} is not an object.")
        question_id = raw.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            raise _ReplyError(f"question #{index}: question_id must be a non-empty string.")
        if question_id in seen_ids:
            raise _ReplyError(f"question #{index}: duplicate question_id {question_id!r}.")
        seen_ids.add(question_id)
        ordinal = raw.get("ordinal")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
            raise _ReplyError(
                f"question {question_id!r}: ordinal must be a non-negative integer, "
                f"got {ordinal!r}."
            )
        if ordinal in seen_ordinals:
            raise _ReplyError(
                f"question {question_id!r}: duplicate ordinal {ordinal} — two "
                "questions cannot share a position."
            )
        seen_ordinals.add(ordinal)
        prompt_text = raw.get("prompt_text")
        if not isinstance(prompt_text, str) or not prompt_text.strip():
            raise _ReplyError(f"question {question_id!r}: prompt_text must be non-empty.")
        question_type = raw.get("question_type")
        if question_type not in QUESTION_TYPES:
            raise _ReplyError(
                f"question {question_id!r}: question_type {question_type!r} is outside "
                f"the vocabulary {QUESTION_TYPES} (FR-SETUP-01)."
            )
        max_points = raw.get("max_points", 0.0)
        if isinstance(max_points, bool) or not isinstance(max_points, (int, float)):
            raise _ReplyError(
                f"question {question_id!r}: max_points must be a number, got "
                f"{max_points!r}."
            )
        raw_options = raw.get("options", [])
        if not isinstance(raw_options, list):
            raise _ReplyError(f"question {question_id!r}: options must be a list.")
        options: list[ProposedOption] = []
        option_ids: set[str] = set()
        option_ordinals: set[int] = set()
        for option_index, raw_option in enumerate(raw_options):
            if not isinstance(raw_option, dict):
                raise _ReplyError(
                    f"question {question_id!r} option #{option_index} is not an object."
                )
            option_id = raw_option.get("option_id")
            label = raw_option.get("label")
            if not isinstance(option_id, str) or not option_id.strip():
                raise _ReplyError(
                    f"question {question_id!r} option #{option_index}: option_id must "
                    "be a non-empty string."
                )
            if option_id in option_ids:
                raise _ReplyError(
                    f"question {question_id!r}: duplicate option_id {option_id!r}."
                )
            if not isinstance(label, str) or not label.strip():
                raise _ReplyError(
                    f"question {question_id!r} option {option_id!r}: label must be "
                    "non-empty."
                )
            option_ordinal = raw_option.get("ordinal", option_index)
            if (not isinstance(option_ordinal, int) or isinstance(option_ordinal, bool)
                    or option_ordinal < 0):
                raise _ReplyError(
                    f"question {question_id!r} option {option_id!r}: ordinal must be "
                    f"a non-negative integer, got {option_ordinal!r}."
                )
            if option_ordinal in option_ordinals:
                raise _ReplyError(
                    f"question {question_id!r}: duplicate option ordinal "
                    f"{option_ordinal} — two options cannot share a position."
                )
            option_ordinals.add(option_ordinal)
            option_ids.add(option_id)
            options.append(ProposedOption(option_id=option_id,
                                          ordinal=option_ordinal, label=label))
        if question_type in ("mcq", "mixed") and not options:
            raise _ReplyError(
                f"question {question_id!r} is {question_type} but proposes no options "
                "— the teacher would have nothing to mark (FR-SETUP-01)."
            )
        if question_type == "open" and options:
            raise _ReplyError(
                f"question {question_id!r} is open but carries {len(options)} "
                "option(s) — a typed mismatch is a proposal bug, not a content choice."
            )
        questions.append(ProposedQuestion(
            question_id=question_id, ordinal=ordinal, prompt_text=prompt_text,
            question_type=question_type, max_points=float(max_points),
            options=tuple(options),
        ))
    return tuple(questions)


def _question_to_dict(question: ProposedQuestion) -> dict:
    """A question in the plain-mapping shape `write_confirmed_inventory` stores; M-PKG does not
    import M-SETUP's types."""
    return {
        "question_id": question.question_id,
        "ordinal": question.ordinal,
        "prompt_text": question.prompt_text,
        "question_type": question.question_type,
        "max_points": question.max_points,
        "options": [
            {"option_id": option.option_id, "ordinal": option.ordinal,
             "label": option.label}
            for option in question.options
        ],
    }


def _assert_confirmed_shape(questions: Sequence[ProposedQuestion]) -> None:
    """Check the inventory again after the teacher's corrections, which can create duplicate ids or
    colliding ordinals the proposal did not have. M-PKG checks again when writing
    (`InventoryError`); this earlier check reports the failure as a setup error naming the
    correction."""
    if not questions:
        raise SetupError(
            "a confirmed inventory carries at least one question — the corrections "
            "removed every proposed question. Add one (the manual-entry path) or "
            "confirm the proposal unmodified."
        )
    seen_ids: set[str] = set()
    seen_ordinals: set[int] = set()
    for question in questions:
        if question.question_id in seen_ids:
            raise SetupError(
                f"correction produced a duplicate question_id {question.question_id!r}."
            )
        seen_ids.add(question.question_id)
        if question.ordinal in seen_ordinals:
            raise SetupError(
                f"correction produced a duplicate ordinal {question.ordinal} "
                f"(question {question.question_id!r}) — two questions cannot share a "
                "position."
            )
        seen_ordinals.add(question.ordinal)
        if question.question_type not in QUESTION_TYPES:
            raise SetupError(
                f"correction set question {question.question_id!r} to question_type "
                f"{question.question_type!r}, outside the vocabulary {QUESTION_TYPES}."
            )
        if question.question_type in ("mcq", "mixed") and not question.options:
            raise SetupError(
                f"correction left {question.question_type} question "
                f"{question.question_id!r} without options — the teacher would have "
                "nothing to mark."
            )
        if question.question_type == "open" and question.options:
            raise SetupError(
                f"correction left open question {question.question_id!r} with an "
                "option set — a typed mismatch is a correction bug, not a content "
                "choice."
            )


def _proposal_from_row(v: PackageVersionId, row: Mapping[str, Any]) -> InventoryProposal:
    """Rebuild the stored proposal, for resuming setup (CT-SETUP-03). A malformed stored payload
    raises `SetupError` naming the problem, instead of silently proposing again."""
    try:
        payload = json.loads(row["payload"])
        entries = payload["entries"]
        status = payload["status"]
    except (ValueError, KeyError, TypeError) as error:
        raise SetupError(
            f"the stored proposal for version {v!r} is malformed ({error}) — the "
            "payload is provenance and is not silently replaced; delete the version "
            "and run setup again."
        ) from error
    questions = tuple(
        ProposedQuestion(
            question_id=str(entry["question_id"]),
            ordinal=int(entry["ordinal"]),
            prompt_text=str(entry["prompt_text"]),
            question_type=str(entry["question_type"]),
            max_points=float(entry.get("max_points", 0.0)),
            options=tuple(
                ProposedOption(option_id=str(option["option_id"]),
                               ordinal=int(option["ordinal"]),
                               label=str(option["label"]))
                for option in entry.get("options", ())
            ),
        )
        for entry in entries
    )
    return InventoryProposal(
        proposal_id=str(row["proposal_id"]),
        assessment_doc_id=str(row["assessment_doc_id"]),
        package_version_id=v,
        template_version=str(row["template_version"]),
        model_ref=str(row["model_ref"]),
        attempts=int(row["attempts"]),
        questions=questions,
        status=status,
        confirmed_at=row["confirmed_at"],
    )


class InventoryStepMixin:
    """Proposes the question inventory and records the teacher's confirmation (gate 1)."""

    # -- Stage A: propose, confirm (BLOCKING), publish ---------------------------------------

    def propose_inventory(self, assessment_doc: DocumentId) -> InventoryProposal:
        """Propose the question inventory from the assessment document, once per version
        (CT-SETUP-16).

        The document is read through `M-INGEST` (`CT-SETUP-11`); one model call goes
        out through the provider seam per attempt (`CT-SETUP-12`'s budget, env-gated).
        A reply that fails to parse or validate is re-requested; after the budget the
        proposal is recorded as `needs_manual_entry` — degraded but complete, the
        teacher enters the questions as `add` corrections and confirms.

        Already-stored proposals come back unchanged (the resume path — no new model
        call); a CONFIRMED inventory refuses to be proposed again (`SetupOrderError`):
        it is locked (`FR-SETUP-02`), and a new instrument is a new version."""
        v = self.ensure_version()
        stored = self._catalog.proposal(v)
        if stored is not None:
            proposal = _proposal_from_row(v, stored)
            if proposal.confirmed:
                raise SetupOrderError(
                    f"the inventory for version {v!r} was already confirmed at "
                    f"{proposal.confirmed_at}; the question rows are locked "
                    "(FR-SETUP-02) and proposing again is out of order (CT-SETUP-16). "
                    "A new instrument is a new version (FR-PKG-02)."
                )
            LOGGER.info("resuming with the stored proposal %s for version %s",
                        proposal.proposal_id, v)
            return proposal

        markdown = self._ingestor.read_document(assessment_doc)
        payload = PromptPayload(fields=(
            ("instruction", _INVENTORY_INSTRUCTION),
            ("assessment_transcript", markdown),
        ))
        proposal_id = uuid.uuid4().hex[:12]
        budget = _configured_proposal_attempts()
        last_error = ""
        for attempt in range(1, budget + 1):
            try:
                completion = self._provider.complete(payload, self._model_ref,
                                                     self._params)
                questions = _parse_reply(completion.text)
            except _ReplyError as error:
                last_error = f"attempt {attempt}: {error}"
                LOGGER.warning("inventory proposal reply failed to parse (%d/%d): %s",
                               attempt, budget, error)
                continue
            except Exception as error:  # contained: the transport's failure is a
                # failed attempt, and the degraded path — not a crash — is the
                # honest end of a budget spent (CT-SETUP-12).
                last_error = f"attempt {attempt}: {type(error).__name__}: {error}"
                LOGGER.warning("inventory proposal attempt %d/%d failed: %s",
                               attempt, budget, error)
                continue
            body = {
                "status": "proposed",
                "entries": [_question_to_dict(question) for question in questions],
            }
            self._catalog.record_proposal(
                v, proposal_id=proposal_id, assessment_doc_id=assessment_doc,
                payload=json.dumps(body, sort_keys=True),
                template_version=SETUP_PROMPT_TEMPLATE_V,
                model_ref=completion.resolved_build, attempts=attempt,
            )
            proposal = InventoryProposal(
                proposal_id=proposal_id, assessment_doc_id=assessment_doc,
                package_version_id=v, template_version=SETUP_PROMPT_TEMPLATE_V,
                model_ref=completion.resolved_build, attempts=attempt,
                questions=questions, status="proposed",
            )
            LOGGER.info(
                "proposed inventory %s for version %s from document %s: %d "
                "question(s) in %d attempt(s), prompt %s",
                proposal_id, v, assessment_doc, len(questions), attempt,
                SETUP_PROMPT_TEMPLATE_V,
            )
            return proposal

        body = {
            "status": "needs_manual_entry",
            "entries": [],
            "reason": last_error,
        }
        self._catalog.record_proposal(
            v, proposal_id=proposal_id, assessment_doc_id=assessment_doc,
            payload=json.dumps(body, sort_keys=True),
            template_version=SETUP_PROMPT_TEMPLATE_V,
            model_ref=self._model_ref.build_id, attempts=budget,
        )
        LOGGER.warning(
            "inventory proposal for version %s degraded to needs_manual_entry after "
            "%d attempt(s): %s — the teacher enters the questions as corrections "
            "(CT-SETUP-12)", v, budget, last_error,
        )
        return InventoryProposal(
            proposal_id=proposal_id, assessment_doc_id=assessment_doc,
            package_version_id=v, template_version=SETUP_PROMPT_TEMPLATE_V,
            model_ref=self._model_ref.build_id, attempts=budget, questions=(),
            status="needs_manual_entry",
        )

    def confirm_inventory(
        self, proposal_id: str, corrections: Sequence[QuestionCorrection] = (),
    ) -> None:
        """Record the teacher's confirmation of the inventory: blocking gate 1. Applies the
        corrections to the stored proposal and writes the confirmed inventory through M-PKG in one
        transaction; the schema lock takes effect at this write (FR-SETUP-02). The `proposal_id`
        must be the version's stored proposal, so the teacher confirms exactly what was proposed.

        Returns None by design (`§3.6`'s protocol): the confirmation's observable
        result is the locked inventory, read back through `current_proposal` /
        `steps` / the catalog's question surfaces."""
        v = self._require_draft_version()
        stored = self._catalog.proposal(v)
        if stored is None:
            raise SetupOrderError(
                f"no inventory proposal is recorded for version {v!r} — "
                "propose_inventory first; confirmation confirms a proposal, not an "
                "idea."
            )
        if stored["confirmed_at"] is not None:
            raise SetupOrderError(
                f"the inventory for version {v!r} is already confirmed (at "
                f"{stored['confirmed_at']}) — it is locked (FR-SETUP-02) and cannot "
                "be confirmed again."
            )
        if stored["proposal_id"] != proposal_id:
            raise SetupOrderError(
                f"confirmation names proposal {proposal_id!r} but version {v!r} "
                f"holds {stored['proposal_id']!r} — the teacher confirms what was "
                "proposed, and a stale or foreign id is refused."
            )
        proposal = _proposal_from_row(v, stored)
        entries: dict[str, ProposedQuestion] = {
            question.question_id: question for question in proposal.questions
        }
        for correction in corrections:
            if correction.action not in ("add", "set", "remove"):
                raise SetupError(
                    f"correction for {correction.question_id!r} has unknown action "
                    f"{correction.action!r} — 'add', 'set' or 'remove'."
                )
            if correction.action == "add":
                if correction.question_id in entries:
                    raise SetupError(
                        f"add correction names {correction.question_id!r}, which the "
                        "proposal already carries — a 'set' correction edits it."
                    )
                missing = [
                    field for field in ("question_type", "prompt_text")
                    if getattr(correction, field) is None
                ]
                if missing:
                    raise SetupError(
                        f"add correction for {correction.question_id!r} is missing "
                        f"{', '.join(missing)} — the manual-entry path must carry "
                        "them (CT-SETUP-12)."
                    )
                if correction.question_type not in QUESTION_TYPES:
                    raise SetupError(
                        f"add correction for {correction.question_id!r} carries "
                        f"question_type {correction.question_type!r}, outside the "
                        f"vocabulary {QUESTION_TYPES}."
                    )
                options = correction.options or ()
                if correction.question_type in ("mcq", "mixed") and not options:
                    raise SetupError(
                        f"add correction for {correction.question_id!r} is "
                        f"{correction.question_type} without options — the teacher "
                        "would have nothing to mark."
                    )
                if correction.question_type == "open" and options:
                    raise SetupError(
                        f"add correction for {correction.question_id!r} is open but "
                        "carries options — a typed mismatch is a correction bug."
                    )
                ordinal = correction.ordinal
                if ordinal is None:
                    ordinal = max((q.ordinal for q in entries.values()), default=-1) + 1
                entries[correction.question_id] = ProposedQuestion(
                    question_id=correction.question_id, ordinal=ordinal,
                    prompt_text=correction.prompt_text or "",
                    question_type=correction.question_type,
                    max_points=float(correction.max_points or 0.0),
                    options=tuple(options),
                )
            elif correction.action == "set":
                if correction.question_id not in entries:
                    raise SetupError(
                        f"set correction names {correction.question_id!r}, which the "
                        "proposal does not carry — 'add' contributes a new question."
                    )
                base = entries[correction.question_id]
                if (correction.options is not None
                        and correction.question_type is None
                        and base.question_type == "open" and correction.options):
                    raise SetupError(
                        f"set correction adds options to open question "
                        f"{correction.question_id!r} without retyping it — set "
                        "question_type to 'mcq' or 'mixed' in the same correction."
                    )
                entries[correction.question_id] = ProposedQuestion(
                    question_id=base.question_id,
                    ordinal=base.ordinal if correction.ordinal is None
                    else correction.ordinal,
                    prompt_text=base.prompt_text if correction.prompt_text is None
                    else correction.prompt_text,
                    question_type=base.question_type
                    if correction.question_type is None
                    else correction.question_type,
                    max_points=base.max_points if correction.max_points is None
                    else float(correction.max_points),
                    options=base.options if correction.options is None
                    else tuple(correction.options),
                )
            else:  # remove
                if correction.question_id not in entries:
                    raise SetupError(
                        f"remove correction names {correction.question_id!r}, which "
                        "the proposal does not carry."
                    )
                del entries[correction.question_id]
        questions = tuple(entries.values())
        _assert_confirmed_shape(questions)
        self._catalog.write_confirmed_inventory(
            v, proposal_id=proposal_id,
            questions=[_question_to_dict(question) for question in questions],
            confirmed_at=_now(),
        )
        LOGGER.info(
            "inventory confirmed for version %s (%d question(s), %d correction(s)) — "
            "the question rows are locked (FR-SETUP-02)", v, len(questions),
            len(corrections),
        )
        # S4's criteria exist the moment the inventory they come from is confirmed
        # (#53, FR-SETUP-03): the deterministic questions' criteria are staged here,
        # so the teacher keys what already has its shape rather than authoring
        # criteria by hand on the side. Idempotent; the ids staged are recorded.
        self._stage_deterministic_criteria(v)

    # -- internals ----------------------------------------------------------------------------

    def _staged_criterion_ids(self, v: PackageVersionId) -> set[str]:
        """The ids of the criteria staged for the confirmed inventory's multiple-choice questions.
        The read-back step expects these and does not treat them as collisions."""
        return {
            _deterministic_criterion_id(row["question_id"])
            for row in self._catalog.questions(v)
            if row["question_type"] in ("mcq", "mixed")
        }

    def _stage_deterministic_criteria(self, v: PackageVersionId) -> list[str]:
        """Create the multiple-choice criteria the confirmed inventory implies (FR-SETUP-03,
        CT-SETUP-07): one per `mcq` or `mixed` question, with id `CRIT-<question id>`, kind `mcq`,
        scoring model `atomic`, `evaluation_mode='deterministic'` (FR-SETUP-17), exactly two bands
        (incorrect at 0 points on the lower ordinal, then correct), and the question's option set.
        These are never classified for decomposability: the answer key fixes their shape.

        Idempotent: an id already present is left exactly as the teacher left it
        (keyed, perhaps). Returns the ids staged BY THIS CALL. A catalog without
        the M-PKG write surface (a rung-0 double) stages nothing."""
        add_criterion = getattr(self._catalog, "add_criterion", None)
        if add_criterion is None:
            return []
        staged: list[str] = []
        existing = {row["criterion_id"] for row in self._catalog.criteria(v)}
        for question in self._catalog.questions(v):
            if question["question_type"] not in ("mcq", "mixed"):
                continue
            criterion_id = _deterministic_criterion_id(question["question_id"])
            if criterion_id in existing:
                continue
            max_points = float(question["max_points"] or 0.0)
            add_criterion(
                v, criterion_id, question_id=question["question_id"], kind="mcq",
                scoring_model="atomic", max_points=max_points, band_count=2,
                # `FR-SETUP-17`: these ARE FR-SETUP-13's criteria, so the service states
                # the mode rather than letting `add_criterion` infer it from `kind`. The
                # stored value is the same either way; what differs is whether M-SETUP
                # declared it, and the requirement is about the declaration.
                evaluation_mode="deterministic",
            )
            # The bands are the two names with FR-PKG-06's monotone mapping — points
            # non-decreasing in ordinal, so the zero-point `incorrect` band sits at
            # the lower ordinal and `correct` carries the question's points above it.
            self._catalog.add_band(
                v, criterion_id, 0, SETUP_MCQ_BAND_NAMES[1], 0.0,
                descriptor="the response marks only options the answer key does "
                           "not accept")
            self._catalog.add_band(
                v, criterion_id, 1, SETUP_MCQ_BAND_NAMES[0], max_points,
                descriptor="the response marks an option the answer key accepts")
            self._catalog.set_mcq_options(
                v, criterion_id,
                [(row["option_id"], row["label"])
                 for row in self._catalog.question_options(
                     v, question["question_id"])])
            staged.append(criterion_id)
        if staged:
            self._catalog.record_step(
                v, step_id="answer_keys", status="criteria_staged",
                payload=json.dumps({
                    "staged_criterion_ids": staged,
                    "reason": "the confirmed inventory carries deterministic "
                              "questions; their criteria are staged for the "
                              "teacher's keys (FR-SETUP-03)",
                }, sort_keys=True),
                recorded_at=_now(),
            )
            LOGGER.info(
                "staged %d deterministic criterion(s) for version %s (%s) — the "
                "confirmed inventory's mcq/mixed questions, awaiting the teacher's "
                "keys (FR-SETUP-03)", len(staged), v, ", ".join(staged),
            )
        return staged
