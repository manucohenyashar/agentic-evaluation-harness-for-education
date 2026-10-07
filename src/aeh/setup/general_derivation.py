"""The `general` rubric method: teacher prose → system-derived bands → blocking confirmation.

`FR-SETUP-18`, `CT-SETUP-17`, `FR-PKG-26`. The teacher describes in their own words how they
score a criterion; the setup model derives a band set from that description; the card shows
the description back beside the derived bands, descriptors and points; and nothing publishes
until the teacher confirms the set as shown or edits it. Only then is the criterion written:
a `general` criterion whose band set is the confirmed one, with M-PKG's derivation provenance
recorded and confirmed (`_general_problems` in `aeh.pkg.rubric_methods` re-checks that the
stored bands ARE the confirmed set at publish).

`RISK-112`: the numeral scan runs on the derivation OUTPUT — a reply whose labels or
descriptors carry a numeral ("3 details = top band") is re-requested within the attempt
budget and never shown or stored; past the budget the derivation is refused.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from aeh.pkg import PackageVersionId
from aeh.prov import PromptPayload

from .settings import (
    _configured_derivation_attempts,
    LOGGER,
    _now,
    SETUP_DERIVATION_TEMPLATE_V,
    SETUP_EVIDENCE_TYPE_DEFAULT,
)
from .errors import _ReplyError, SetupError, SetupOrderError
from .records import DerivationCard, ProposedBand
from .prompts import _DERIVATION_INSTRUCTION
from .method_drafts import (
    band_set_problems,
    bands_from_json,
    bands_to_json,
    CONFIRMED,
    EVIDENCE_SUM_STEP_PREFIX,
    GENERAL_STEP_PREFIX,
    PENDING,
    typed_bands,
)

GENERAL_METHOD = "general"
#: A `general` criterion is not classified by the §5.3 table; NFR-SETUP-02's asymmetric
#: default applies — holistic, never atomic.
GENERAL_SCORING_MODEL = "holistic"


def _parse_derivation_reply(text: str, criterion_id: str,
                            max_points: float) -> tuple[ProposedBand, ...]:
    """The reply's band set in stored order, or `_ReplyError` naming every reason it cannot be
    shown — the attempt loop re-requests on that."""
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
    named = parsed.get("criterion_id")
    if named is not None and str(named) != criterion_id:
        raise _ReplyError(f"the reply derives {named!r}, not {criterion_id!r}.")
    try:
        bands = typed_bands(parsed.get("bands"))
    except ValueError as error:
        raise _ReplyError(str(error)) from error
    problems = band_set_problems(bands, max_points)
    if problems:
        raise _ReplyError("; ".join(problems))
    return bands


class GeneralDerivationMixin:
    """`derive_general_bands`, `derivation_card`, `confirm_general_derivation`."""

    def derive_general_bands(self, criterion_id: str, *, question_id: str,
                             description: str) -> DerivationCard:
        """Derive a band set from the teacher's description and return the read-back card,
        unconfirmed (`FR-SETUP-18`). The card is stored pending — publish refuses, naming the
        criterion, until `confirm_general_derivation` (`CT-SETUP-17`).

        Showing the card spends one of NFR-SYS-07's optional confirmations (Q-O4), once per
        criterion: re-deriving a pending card does not spend another. Re-deriving replaces
        the pending card; a criterion already confirmed refuses. A pending evidence-sum draft
        for the same id is superseded — the teacher chose another method."""
        v = self._require_draft_version()
        if not isinstance(description, str) or not description.strip():
            raise SetupError(f"general criterion {criterion_id!r}: the derivation needs the "
                             "teacher's own description of how it is scored (FR-SETUP-18).")
        question = self._method_question(v, question_id)
        self._require_unused_ids(v, [criterion_id])
        step_id = GENERAL_STEP_PREFIX + criterion_id
        earlier = self._method_record(v, step_id)
        if earlier is not None and earlier["status"] == CONFIRMED:
            raise SetupOrderError(f"general criterion {criterion_id!r} is already confirmed; "
                                  "its band set is the package's now.")
        max_points = float(question.get("max_points") or 0.0)
        bands, attempts, model_ref = self._derive_bands(criterion_id, question, description,
                                                        max_points)
        recorded_at = _now()
        self._supersede(v, EVIDENCE_SUM_STEP_PREFIX + criterion_id, recorded_at)
        payload = {
            "criterion_id": criterion_id, "question_id": question_id,
            "description": description, "derived_bands": bands_to_json(bands),
            "bands": bands_to_json(bands), "attempts": attempts,
            "template_version": SETUP_DERIVATION_TEMPLATE_V, "model_ref": model_ref,
            "confirmed_by": None,
        }
        self._write_method_record(v, step_id, PENDING, payload, recorded_at)
        if earlier is None:
            self._request_confirmation(v)
        LOGGER.info("derived %d band(s) for general criterion %s of version %s in %d "
                    "attempt(s); the read-back card awaits the teacher (CT-SETUP-17)",
                    len(bands), criterion_id, v, attempts)
        return _card_from_payload(payload, confirmed=False)

    def derivation_card(self, criterion_id: str) -> DerivationCard:
        """The stored card, for a resuming console: pending or confirmed. No model call."""
        v = self._require_draft_version()
        record = self._method_record(v, GENERAL_STEP_PREFIX + criterion_id)
        if record is None or record["status"] not in (PENDING, CONFIRMED):
            raise SetupError(f"no general derivation is staged for criterion "
                             f"{criterion_id!r} in version {v!r}.")
        return _card_from_payload(record["payload"],
                                  confirmed=record["status"] == CONFIRMED)

    def confirm_general_derivation(
        self, criterion_id: str, *, confirmed_by: str,
        bands: Sequence[Mapping[str, Any]] | None = None,
    ) -> DerivationCard:
        """The teacher's confirmation of the card (`FR-SETUP-18`): `bands=None` confirms the
        derived set as shown; otherwise `bands` is the teacher's edit of it, held to the same
        rules as the derivation (the numeral scan included). Writes the `general` criterion,
        its bands and M-PKG's confirmed derivation provenance; publish's gate then opens."""
        v = self._require_draft_version()
        if not isinstance(confirmed_by, str) or not confirmed_by.strip():
            raise SetupError(f"general criterion {criterion_id!r}: a confirmation names who "
                             "confirmed it (FR-PKG-26).")
        step_id = GENERAL_STEP_PREFIX + criterion_id
        record = self._method_record(v, step_id)
        if record is None or record["status"] != PENDING:
            raise SetupOrderError(f"general criterion {criterion_id!r} has no derivation "
                                  "awaiting confirmation: derive_general_bands first.")
        payload = dict(record["payload"])
        question = self._method_question(v, payload["question_id"])
        confirmed = (bands_from_json(payload["bands"]) if bands is None
                     else self._teacher_bands(criterion_id, bands, question))
        self._require_unused_ids(v, [criterion_id])
        recorded_at = _now()
        self._write_general_criterion(v, criterion_id, payload, confirmed, confirmed_by,
                                      recorded_at)
        payload.update(bands=bands_to_json(confirmed), confirmed_by=confirmed_by)
        self._write_method_record(v, step_id, CONFIRMED, payload, recorded_at)
        LOGGER.info("general criterion %s of version %s confirmed by %r (%s)", criterion_id,
                    v, confirmed_by, "as derived" if bands is None else "edited")
        return _card_from_payload(payload, confirmed=True)

    # -- internals -------------------------------------------------------------------------

    def _derive_bands(self, criterion_id: str, question: Mapping[str, Any], description: str,
                      max_points: float) -> tuple[tuple[ProposedBand, ...], int, str]:
        """One model call per attempt, within `HARNESS_SETUP_DERIVATION_ATTEMPTS`. A reply that
        fails `_parse_derivation_reply` is re-requested; past the budget, `SetupError`."""
        payload = PromptPayload(fields=(
            ("instruction", _DERIVATION_INSTRUCTION),
            ("criterion_id", criterion_id),
            ("question_text", str(question.get("prompt_text") or "")),
            ("question_max_points", f"{max_points:g}"),
            ("teacher_description", description),
        ))
        budget = _configured_derivation_attempts()
        last_error = ""
        for attempt in range(1, budget + 1):
            try:
                completion = self._provider.complete(payload, self._model_ref, self._params)
                bands = _parse_derivation_reply(completion.text, criterion_id, max_points)
            except _ReplyError as error:
                last_error = f"attempt {attempt}: {error}"
                LOGGER.warning("general derivation reply for %s refused (%d/%d): %s",
                               criterion_id, attempt, budget, error)
                continue
            return bands, attempt, str(completion.resolved_build)
        raise SetupError(
            f"general criterion {criterion_id!r}: no derivation the teacher could be shown "
            f"after {budget} attempt(s) — {last_error}. Nothing was staged; describe the "
            "scoring again, or choose per-band descriptions (FR-SETUP-18, RISK-112).")

    def _teacher_bands(self, criterion_id: str, bands: Sequence[Mapping[str, Any]],
                       question: Mapping[str, Any]) -> tuple[ProposedBand, ...]:
        try:
            typed = typed_bands(list(bands))
        except ValueError as error:
            raise SetupError(f"general criterion {criterion_id!r}: the edited band set is "
                             f"malformed — {error}.") from error
        problems = band_set_problems(typed, float(question.get("max_points") or 0.0))
        if problems:
            raise SetupError(f"general criterion {criterion_id!r}: the edited band set "
                             f"cannot publish — {'; '.join(problems)}.")
        return typed

    def _write_general_criterion(self, v: PackageVersionId, criterion_id: str,
                                 payload: Mapping[str, Any],
                                 bands: Sequence[ProposedBand], confirmed_by: str,
                                 recorded_at: str) -> None:
        """The criterion, its bands, and the confirmed derivation — the stored form FR-PKG-26
        names: a banded criterion whose provenance is the description and the confirmed set."""
        self._catalog.add_criterion(
            v, criterion_id, question_id=payload["question_id"], kind="open",
            max_points=bands[-1].points, scoring_model=GENERAL_SCORING_MODEL,
            band_count=len(bands), evidence_type=SETUP_EVIDENCE_TYPE_DEFAULT,
            score_method=GENERAL_METHOD)
        for band in bands:
            self._catalog.add_band(v, criterion_id, band.ordinal, band.band, band.points,
                                   band.descriptor)
        self._catalog.record_derivation(v, criterion_id, description=payload["description"],
                                        derived_bands=bands_to_json(bands),
                                        recorded_at=recorded_at)
        self._catalog.confirm_derivation(v, criterion_id, confirmed_by=confirmed_by,
                                         confirmed_at=recorded_at)
        self._record_method_classification(v, criterion_id, GENERAL_SCORING_MODEL,
                                           recorded_at)


def _card_from_payload(payload: Mapping[str, Any], *, confirmed: bool) -> DerivationCard:
    return DerivationCard(
        criterion_id=str(payload["criterion_id"]),
        question_id=str(payload["question_id"]),
        description=str(payload["description"]),
        bands=bands_from_json(payload["bands"]),
        derived_bands=bands_from_json(payload["derived_bands"]),
        confirmed=bool(confirmed),
        confirmed_by=payload.get("confirmed_by"),
        attempts=int(payload["attempts"]),
        template_version=str(payload["template_version"]),
        model_ref=str(payload["model_ref"]),
    )
