"""Classifying each criterion's decomposability, and the teacher's capped confirmations."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from aeh.pkg import PackageVersionId
from aeh.prov import PromptPayload

from .settings import (
    CLASSIFICATIONS,
    _configured_classify_attempts,
    FIVE_QUESTIONS,
    LOGGER,
    _now,
    SETUP_CLASSIFY_TEMPLATE_V,
    SETUP_MAX_CONFIRMATIONS,
)
from .errors import _ReplyError, SetupError
from .records import DecomposabilityVerdict
from .prompts import _CLASSIFY_INSTRUCTION


# -- #52: the decomposability decision table and its verdict (FR-SETUP-06/-07/-08) --------


def _classify_answers(
    answers: Mapping[str, Any],
) -> tuple[str, str | None]:
    """The five-question decision table that turns answers into a classification (FR-SETUP-06). The
    table is M-SETUP's; the model only answers the questions.

    The model answers the §5.3 questions; this table turns answers into a
    classification. Scanned in the HLD's order, the first `no` decides: `gates`
    failing names `atomic_with_gate` (the criterion is judged in isolation once its
    gate holds), any other question failing names `holistic` (the construct does not
    survive being cut apart). With no `no` anywhere, an `unclear` answer — or an
    answer the vocabulary does not name, which IS unclear — applies NFR-SETUP-02's
    asymmetric default: `holistic`, never `atomic` (RISK-27: a default of `atomic`
    would hand the criterion panel depth 1 and a higher auto-acceptance ceiling than
    it deserves, and nothing downstream would notice). All answers pass and none is
    unclear: `atomic` — the one classification the table grants, never the default.

    Returns `(classification, deciding_question)`; the deciding question is None
    exactly when nothing decided (the all-pass cell and the default cell)."""
    for question in FIVE_QUESTIONS:
        if str(answers.get(question, "")).strip().lower() == "no":
            if question == "gates":
                return "atomic_with_gate", question
            return "holistic", question
    for question in FIVE_QUESTIONS:
        if str(answers.get(question, "")).strip().lower() != "yes":
            return "holistic", None
    return "atomic", None


def _draft_criterion_identity(draft: Any) -> dict:
    """The classifier's view of one criterion draft, as a plain mapping.

    The draft arrives either as a `CriterionDraft` (the read back's own drafts) or as
    the plain dict a caller assembled (the payload shape the test suite bets on) — the
    classifier consumes the identity fields either way, and refuses a draft that names
    no criterion (`SetupError`: a classification of nothing is not a classification)."""
    if isinstance(draft, Mapping):
        get = draft.get
    else:
        get = lambda name, default=None: getattr(draft, name, default)  # noqa: E731
    criterion_id = get("criterion_id")
    if not isinstance(criterion_id, str) or not criterion_id.strip():
        raise SetupError(
            "classify_decomposability needs a draft that names its criterion — "
            f"got {draft!r} with no usable 'criterion_id'."
        )
    return {
        "criterion_id": criterion_id,
        "question_id": str(get("question_id", "") or ""),
        "kind": str(get("kind", "") or ""),
        "construct": str(get("construct", "") or ""),
        "max_points": get("max_points", 0.0),
        "band_count": get("band_count", 0),
    }


def _json_object(text: str) -> dict:
    """The one JSON object in a model reply, ignoring any prose around it. The reply parsers all
    start here."""
    stripped = text.strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start < 0 or end <= start:
        raise _ReplyError("the reply contains no JSON object.")
    try:
        parsed = json.loads(stripped[start:end + 1])
    except ValueError as error:
        raise _ReplyError(f"the reply is not valid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise _ReplyError("the reply's JSON is not an object.")
    return parsed


def _parse_classify_reply(text: str, criterion_id: str) -> tuple[dict, list[str], str]:
    """Parse the classifier's reply into `(answers, warning_signs, reasoning)`, raising
    `_ReplyError` for anything that is not a valid answer set, so the attempt loop asks again. The
    reply carries answers, never a classification (FR-SETUP-06). A reply about a different
    criterion than the draft is a schema failure."""
    parsed = _json_object(text)
    reply_id = parsed.get("criterion_id")
    if reply_id is not None and str(reply_id) != criterion_id:
        raise _ReplyError(
            f"the reply classifies {str(reply_id)!r} but the draft names "
            f"{criterion_id!r} — one classification per criterion, and this reply "
            "answers a different one."
        )
    raw_answers = parsed.get("answers")
    if not isinstance(raw_answers, dict):
        raise _ReplyError(
            "the reply's JSON does not carry an 'answers' object — the classifier "
            "answers the five §5.3 questions; it does not classify."
        )
    answers = {
        question: str(raw_answers.get(question, "unclear")).strip().lower()
        for question in FIVE_QUESTIONS
    }
    raw_warnings = parsed.get("warning_signs", [])
    if raw_warnings is None:
        raw_warnings = []
    if not isinstance(raw_warnings, list):
        raise _ReplyError(
            f"criterion {criterion_id!r}: warning_signs must be a list of strings."
        )
    warning_signs = [str(item) for item in raw_warnings if str(item).strip()]
    reasoning = parsed.get("reasoning", "")
    if reasoning is None:
        reasoning = ""
    if not isinstance(reasoning, str):
        raise _ReplyError(
            f"criterion {criterion_id!r}: reasoning must be a string."
        )
    return answers, warning_signs, reasoning.strip()


class DecomposabilityMixin:
    """Classifies criteria for decomposability and records the teacher's confirmations."""

    # -- Stage A: decomposability and dependencies (#52, skippable steps) ---------------------

    def classify_decomposability(self, criterion_draft: Any) -> DecomposabilityVerdict:
        """Classify one criterion against the five decomposability questions, applying M-SETUP's
        decision table to the model's answers (FR-SETUP-06, design §5.3).

        The model is asked for ANSWERS (one prompt per criterion, `NFR-SETUP-03`'s
        version-pinned template), never for a verdict; `_classify_answers` is the
        module's table, so a scripted or hallucinated classification cannot pass
        through the seam. An unclear answer — or an attempt budget spent — applies
        NFR-SETUP-02's asymmetric default: `holistic`, never `atomic` (RISK-27), and
        the default case SURFACES for the teacher, which is what makes it auditable
        rather than silent.

        The surfacing half of `FR-SETUP-07` lives here too: only borderline criteria
        (an unclear answer anywhere) and warning-sign criteria are surfaced, and the
        number of confirmations REQUESTED per draft version is capped at
        `SETUP_MAX_CONFIRMATIONS` — enforced by this module, headlessly (`CT-SETUP-13`),
        never by the console. A criterion beyond the cap keeps its classification but
        is not requested. Every verdict is recorded through `M-PKG` as the module's
        default (`source='default'`), so a skipped confirmation still leaves the
        teacher-vs-system distinction `M-CALIB` and `M-STATS` read (`R62`)."""
        # Every mutating entry point refuses on a finished package (`CT-SETUP-16`,
        # #229) — this one included: post-publish there is no draft to record the
        # verdict against, so the calls would run and the record would skip
        # silently. The never-started state stays open: the classification is the
        # module's table applied to a reply, and the rung-0 doubles exercise it
        # without a draft (the record skips by design there).
        if (self._catalog.draft_version() is None
                and self._catalog.has_version()):
            self._refuse_finished_package()
        identity = _draft_criterion_identity(criterion_draft)
        criterion_id = identity["criterion_id"]
        payload = PromptPayload(fields=(
            ("instruction", _CLASSIFY_INSTRUCTION),
            ("criterion", json.dumps(identity, sort_keys=True)),
        ))
        budget = _configured_classify_attempts()
        last_error = ""
        for attempt in range(1, budget + 1):
            try:
                completion = self._provider.complete(payload, self._model_ref,
                                                     self._params)
                answers, warning_signs, reply_reasoning = _parse_classify_reply(
                    completion.text, criterion_id)
            except _ReplyError as error:
                last_error = f"attempt {attempt}: {error}"
                LOGGER.warning("classify reply for %s failed to parse (%d/%d): %s",
                               criterion_id, attempt, budget, error)
                continue
            except Exception as error:  # contained: the transport's failure is a
                # failed attempt, and the degraded default — not a crash — is the
                # honest end of a budget spent (CT-SETUP-12's pattern).
                last_error = f"attempt {attempt}: {type(error).__name__}: {error}"
                LOGGER.warning("classify attempt %d/%d for %s failed: %s",
                               attempt, budget, criterion_id, error)
                continue
            verdict = self._verdict_from_answers(
                criterion_id, answers, warning_signs, reply_reasoning)
            LOGGER.info(
                "classified %s for version %s: %s (decided by %s, confirmation "
                "%s) in %d attempt(s), prompt %s — confirmations requested %d/%d",
                criterion_id, self._catalog.draft_version(), verdict.classification,
                verdict.deciding_question or "nothing",
                "requested" if verdict.needs_teacher_confirmation else "not requested",
                attempt, SETUP_CLASSIFY_TEMPLATE_V,
                self._confirmations_requested.get(self._catalog.draft_version(), 0),
                SETUP_MAX_CONFIRMATIONS,
            )
            return verdict

        # The budget is spent and no reply parsed: degraded but complete (`CT-SETUP-12`)
        # — the default applies, surfaced, and the reason is in the verdict's reasoning
        # so the audit trail says WHY the teacher is being asked. The cap is applied
        # through the same counter as the classified path (`_request_confirmation`):
        # a degraded package must not exceed SETUP_MAX_CONFIRMATIONS any more than a
        # classified one (NFR-SETUP-01); beyond-cap criteria keep the holistic default
        # but are not requested.
        degraded = DecomposabilityVerdict(
            classification="holistic", deciding_question=None,
            reasoning=(
                "the classifier could not read a §5.3 answer set "
                f"({last_error or 'no valid reply within the attempt budget'}); the "
                "default applies: holistic, never atomic (NFR-SETUP-02) — please "
                "enter the answers or confirm the criterion by hand."
            ),
            needs_teacher_confirmation=self._request_confirmation(
                self._catalog.draft_version()),
        )
        self._record_classification(self._catalog.draft_version(), criterion_id,
                                    degraded)
        LOGGER.warning(
            "classify for %s degraded to the holistic default after %d attempt(s): %s",
            criterion_id, budget, last_error,
        )
        return degraded

    def _request_confirmation(self, v: PackageVersionId | None) -> bool:
        """Count one teacher confirmation against the cap and say whether it was requested; this is
        the only place the cap is counted (FR-SETUP-07, NFR-SETUP-01). At most
        `SETUP_MAX_CONFIRMATIONS` are requested per draft version; a criterion beyond the cap keeps
        its classification but is not requested. The fallback path uses the same counter, so a
        failing provider cannot exceed the cap either."""
        requested = self._confirmations_requested.get(v, 0)
        if requested >= SETUP_MAX_CONFIRMATIONS:
            return False
        self._confirmations_requested[v] = requested + 1
        return True

    def _verdict_from_answers(
        self, criterion_id: str, answers: Mapping[str, str],
        warning_signs: Sequence[str], reply_reasoning: str,
    ) -> DecomposabilityVerdict:
        """Combine the decision table, the confirmation cap and the record into one verdict; shared
        by the normal and fallback paths. A criterion beyond `SETUP_MAX_CONFIRMATIONS` keeps its
        classification but is not requested (FR-SETUP-07)."""
        classification, deciding = _classify_answers(answers)
        unclear = any(
            str(answers.get(question, "")).strip().lower() not in ("yes", "no")
            for question in FIVE_QUESTIONS
        )
        # A warning sign with every answer passing still refuses the atomic grant:
        # the table's one automatic `atomic` is for criteria with nothing standing
        # against decomposition — a warning sign is the population FR-SETUP-07
        # surfaces, and it is judged holistic rather than granted depth 1
        # (RISK-27's asymmetry, applied to the warning case too).
        if deciding is None and classification == "atomic" and warning_signs:
            classification = "holistic"
        borderline = unclear or bool(warning_signs)
        needs = self._request_confirmation(
            self._catalog.draft_version()) if borderline else False
        if deciding is not None:
            reasoning = (
                f"the §5.3 table decided on {deciding!r} (its answer was 'no'): the "
                f"criterion classifies {classification!r}."
            )
        elif unclear:
            reasoning = (
                "the §5.3 answers were unclear: the default applies — holistic, "
                "never atomic (NFR-SETUP-02, RISK-27); surfaced for the teacher."
            )
        elif warning_signs:
            reasoning = (
                "the §5.3 answers pass, but the criterion carries warning signs "
                f"({'; '.join(warning_signs)}): judged holistic and surfaced for "
                "the teacher (FR-SETUP-07)."
            )
        else:
            reasoning = (
                "all five §5.3 answers pass and no warning sign stands: the "
                "criterion is judged in isolation (atomic)."
            )
        if reply_reasoning:
            reasoning = f"{reasoning} The criterion's reader said: {reply_reasoning}"
        verdict = DecomposabilityVerdict(
            classification=classification, deciding_question=deciding,
            reasoning=reasoning, needs_teacher_confirmation=needs,
        )
        self._record_classification(self._catalog.draft_version(), criterion_id,
                                    verdict)
        return verdict

    def _record_classification(
        self, v: PackageVersionId | None, criterion_id: str,
        verdict: DecomposabilityVerdict,
    ) -> None:
        """Save one verdict through M-PKG as M-SETUP's default (R62); `confirm_classifications`
        later updates it to `source='teacher'`. Skipped when there is no draft version or the
        catalog cannot record it; the verdict is still returned."""
        if v is None:
            return
        record = getattr(self._catalog, "record_classification", None)
        if record is None:
            return
        record(v, criterion_id=criterion_id, classification=verdict.classification,
               decomposition_basis=verdict.deciding_question, source="default",
               recorded_at=_now())

    def _record_decomposability_step(
        self, v: PackageVersionId, *, status: str, update: Mapping,
    ) -> None:
        """Merge `update` into the decomposability step's one provenance row (FR-SETUP-14). It
        merges rather than replaces, because the step has three parts (confirmations, proposals,
        approvals) and replacing the whole row would erase the others: an approval must still find
        the proposals it approves (CT-SETUP-03). Skipped when the catalog cannot record it."""
        step = getattr(self._catalog, "record_step", None)
        if step is None:
            return
        prior: dict = {}
        reader = getattr(self._catalog, "step_record", None)
        if reader is not None:
            row = reader(v, "decomposability")
            if row is not None:
                try:
                    loaded = json.loads(row["payload"])
                except (ValueError, TypeError):
                    loaded = None
                if isinstance(loaded, dict):
                    prior = loaded
        payload = {**prior, **dict(update)}
        step(v, step_id="decomposability", status=status,
             payload=json.dumps(payload, sort_keys=True), recorded_at=_now())

    def confirm_classifications(self, answers: Mapping[str, str]) -> None:
        """Record the teacher's confirmations of the surfaced classifications. The step may be
        skipped, and a skip is recorded too (FR-SETUP-14, R62).

        Each entry names a criterion and the classification the teacher confirms; the
        rows already stored as `source='default'` (the module's table, written at
        classify time) are upserted to `source='teacher'` — the recorded distinction
        between a teacher's judgment and the system default that `M-CALIB` and
        `M-STATS` read. A classification outside the vocabulary, or a criterion the
        version does not carry, is refused; skipping the call entirely records
        nothing here and leaves the default rows standing, which is the point."""
        v = self._require_draft_version()
        if not answers:
            LOGGER.info("confirm_classifications confirmed nothing for version %s", v)
            return
        misplaced = sorted(
            criterion_id for criterion_id, classification in answers.items()
            if classification not in CLASSIFICATIONS
        )
        if misplaced:
            raise SetupError(
                f"classification(s) for {', '.join(misplaced)} are outside the "
                f"vocabulary {CLASSIFICATIONS} (FR-SETUP-06) — a confirmed "
                "classification is one the decision table could have produced."
            )
        known = {row["criterion_id"] for row in self._catalog.criteria(v)}
        unknown = sorted(set(answers) - known)
        if unknown:
            raise SetupError(
                f"confirmation names criterion(s) {', '.join(unknown)} that version "
                f"{v!r} does not carry — the teacher confirms criteria that exist."
            )
        reader = getattr(self._catalog, "classification", None)
        record = getattr(self._catalog, "record_classification", None)
        confirmed: dict[str, str] = {}
        for criterion_id, classification in answers.items():
            basis = None
            if reader is not None:
                prior = reader(v, criterion_id)
                if prior is not None:
                    basis = prior.get("decomposition_basis")
            if record is not None:
                record(v, criterion_id=criterion_id, classification=classification,
                       decomposition_basis=basis, source="teacher",
                       recorded_at=_now())
            confirmed[criterion_id] = classification
        self._record_decomposability_step(
            v, status="classifications_confirmed",
            update={"confirmed": confirmed,
                    "teacher_confirmed_count": len(confirmed)})
        LOGGER.info(
            "teacher confirmed %d classification(s) for version %s — recorded as "
            "'teacher' beside the module's 'default' rows (R62)", len(confirmed), v,
        )
