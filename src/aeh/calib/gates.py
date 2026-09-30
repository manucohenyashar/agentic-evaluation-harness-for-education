"""The two gates a revised rubric must pass (non-inferiority, back-translation), and pinning it."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .errors import (
    CalibrationError,
    InsufficientPopulation,
    OffPanelConfigurationError,
    OffPanelUnavailable,
    ThresholdNotDeclared,
)
from .off_panel import (
    _BACK_TRANSLATION_ANGLES,
    CALIB_OFF_PANEL_MODEL_ENV,
    _ConstructionAttempt,
    _off_panel_model_declared,
    _off_panel_model_ref_from_declared,
    _OFF_PANEL_PROVIDERS,
    _OFF_PANEL_SESSIONS,
    OffPanelModelRef,
    _PANEL_BUILDS,
    _RecordedSessionProvider,
)
from .rosters import (
    CALIB_CLASS_SIZE_CAP_ENV,
    _CLASS_ROSTERS,
    _class_size_cap,
    _next_timestamp,
    _roster_from_store,
)


# --- the two guardrail gates (#139, FR-CALIB-08/-11, §6.5–§6.7) -------------------------------------
#
# Between a proposed revision and a live one sit two gates, and every failure mode ends at
# R₀ (CT-CALIB-02): a revision is the rubric's construct changing shape, and the construct
# is what every accumulated validation record describes (RISK-06) — so the gates are
# evidence gates about construct stability, never quality gates, and no outcome ships a
# revision carrying a warning.

#: The cohort id that names the calibration set itself. The gate refuses it
#: (`NFR-CALIB-02`: the calibration set *"lacks the sample size to mean anything"* — a gate
#: run on twenty papers returns a number, and a number that means nothing is worse than no
#: number, because it is a passed gate somebody will cite).
CALIBRATION_SET = "calibration-set"


#: The threshold §6.5 states as an **example** ("reject if more than 10% of the class
#: shifts by a full rubric level"). It is deliberately *not* the gate's default
#: (`CT-CALIB-13`): the design is explicit that it is "an example value from the HLD, not a
#: validated one" and "must be declared per institution before use" — so the constant
#: exists to be read and documented, and the gate refuses to run until somebody declares
#: their own (an argument, `declare_institutional_threshold`, or the deployment's env
#: channel below).
CALIB_NONINFERIORITY_THRESHOLD: float = 0.10


CALIB_NONINFERIORITY_THRESHOLD_ENV: str = "HARNESS_CALIB_NONINFERIORITY_THRESHOLD"


def _noninferiority_threshold_from_env(
    environ: Mapping[str, str] | None = None,
) -> float | None:
    """The env fallback for the threshold (seam 3), or None when unset or mis-set.

    A value outside [0, 1] is treated as unset rather than raising: the mis-set value
    then falls through to the refusal that names the real problem — no threshold
    declared — instead of a ValueError about string parsing."""
    source = os.environ if environ is None else environ
    raw = source.get(CALIB_NONINFERIORITY_THRESHOLD_ENV)
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if 0.0 <= value <= 1.0 else None


#: The standing institutional threshold declaration, and the moment it was fixed. One-shot:
#: the gate run that uses it consumes it (see the module docstring's interpretation).
_INSTITUTIONAL_THRESHOLD: float | None = None


_INSTITUTIONAL_THRESHOLD_DECLARED_AT: datetime | None = None


def declare_institutional_threshold(value: float) -> datetime:
    """Declare the institution's non-inferiority threshold and return when it was fixed
    (`FR-CALIB-08`, `CT-CALIB-13`).

    The declaration is the owned decision the gate consumes: it must exist **before**
    the comparison, which the returned timestamp is the record of. The declaration is
    one-shot — the next gate run that uses it consumes it, so a fresh comparison needs a
    fresh declaration (the strictest honest reading of "declared before the comparison";
    see the module docstring). The value is a fraction of a class, so anything outside
    [0, 1] is refused here, at the declaration."""
    global _INSTITUTIONAL_THRESHOLD, _INSTITUTIONAL_THRESHOLD_DECLARED_AT
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise CalibrationError(
            f"the non-inferiority threshold is a fraction of the class, got {value!r}: "
            "declare a value in [0, 1] — 0.10 is the HLD's example, not a validated one "
            "(CT-CALIB-13)"
        )
    declared_at = _next_timestamp()
    _INSTITUTIONAL_THRESHOLD = value
    _INSTITUTIONAL_THRESHOLD_DECLARED_AT = declared_at
    return declared_at


def _clear_institutional_threshold() -> None:
    """Clear any standing threshold declaration. The declaration is one-shot, so this is
    hygiene for the knob sweep: an observation must read the value it injected, not a
    leftover declaration that outranks the env."""
    global _INSTITUTIONAL_THRESHOLD, _INSTITUTIONAL_THRESHOLD_DECLARED_AT
    _INSTITUTIONAL_THRESHOLD = None
    _INSTITUTIONAL_THRESHOLD_DECLARED_AT = None


@dataclass(frozen=True)
class GateResult:
    """One gate's outcome, with what the gate did next to it (seam 4) — never a bare
    pass/fail.

    ``threshold_used`` is the value the comparison applied and ``threshold_source`` is
    where it came from — "argument" when the caller passed one, "configuration" when it
    came from a standing one-shot declaration, "environment" when it fell back to the
    deployment's env channel. The distinction matters: a declaration is an owned
    decision, a machine default is not, and one reader of the result can tell them
    apart. The timestamps are the
    event-order oracle: ``threshold_declared_at`` is when the threshold was fixed (the
    declaration's moment for a standing declaration; for an argument or an env fallback,
    the call at which the gate fixed it), and it precedes ``first_result_at`` — the first
    comparison's timestamp — on every path, so a threshold chosen to fit the outcome
    shows up as one.

    ``revert_to`` is the revert record (`CT-CALIB-02`): the rubric the run ends on when
    this gate refuses — R₀ — or None when the gate passed. ``advisory_only`` is
    structurally False: no outcome on this surface attaches a note to a revision that
    ships, so the forbidden "warned revision" shape is assertable rather than merely
    avoided."""

    gate: str
    outcome: str
    r0: str
    r1: str
    cohort_id: str | None = None
    threshold_used: float | None = None
    threshold_source: str | None = None
    threshold_declared_at: datetime | None = None
    first_result_at: datetime | None = None
    shifted_papers: int | None = None
    class_size: int | None = None
    shifted_fraction: float | None = None
    divergent_response_found: bool | None = None
    constructed_response: str | None = None
    advisory_only: bool = False
    revert_to: str | None = None
    attempts: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def non_inferiority(
    r0: str,
    r1: str,
    cohort_id: str,
    threshold: float | None,
    *,
    environ: Mapping[str, str] | None = None,
) -> GateResult:
    """The dual-scoring non-inferiority gate (`FR-CALIB-08`, `CT-CALIB-07`/`-13`).

    Compares the full class's dual scores — the R₀ and R₁ bands the registered roster
    carries, the recorded-transport form — and rejects the revision when **more than**
    ``threshold`` of the class shifted by a full band. "More than" is strict: a class
    shifted by exactly the threshold passes, which is the row an implementation using
    ``>=`` gets wrong (`FR-CALIB-08` says "more than").

    The threshold is resolved, never defaulted (`CT-CALIB-13`): an explicit argument
    wins (source "argument"); then a standing institutional declaration — consumed by
    this run (source "configuration"); then the deployment's
    ``HARNESS_CALIB_NONINFERIORITY_THRESHOLD``; with none of the three, the gate refuses
    with `ThresholdNotDeclared`. ``CALIB_NONINFERIORITY_THRESHOLD`` — the design's 0.10 —
    is never applied by the gate: it is the HLD's example, not a validated value.

    The gate refuses the calibration set itself and any roster flagged as it
    (`InsufficientPopulation`, `NFR-CALIB-02`), and refuses a class over the
    deployment's class-size cap rather than silently scoring a subset. Passing is
    **non-inferiority and nothing more** (`CT-CALIB-16`): the gate cannot see whether
    the revision was better, and says nothing about it.
    """
    # The one-shot declaration is consumed here, so the globals are assigned in this scope.
    global _INSTITUTIONAL_THRESHOLD, _INSTITUTIONAL_THRESHOLD_DECLARED_AT

    if cohort_id == CALIBRATION_SET:
        raise InsufficientPopulation(
            f"cohort {CALIBRATION_SET!r} is the calibration set, which lacks the sample "
            "size to mean anything (NFR-CALIB-02): the gate refuses it rather than "
            "returning a number somebody will cite (CT-CALIB-07)"
        )
    roster = _CLASS_ROSTERS.get(cohort_id)
    if roster is not None and not roster.answers(r0, r1):
        # The cache holds a DIFFERENT comparison's roster for this cohort. Fall through to the
        # table, which is keyed by the comparison — and never fall back to the cached one, or
        # this gate answers a question nobody asked.
        roster = None
    if roster is None:
        # `FR-CALIB-15`: the registered roster is persisted, and the module dict is a cache
        # populated from it on first use. The process that runs the gate is often not the one
        # that registered the class (`CT-CALIB-17`), and a roster that only ever lived in this
        # dict would make every such gate run answer "unknown cohort".
        roster = _roster_from_store(cohort_id, r0=r0, r1=r1)
    if roster is None:
        raise CalibrationError(
            f"unknown cohort {cohort_id!r}: the gate scores a registered class — the "
            "recorded-transport form the caller registers (CT-PROV-10)"
        )
    if roster.is_calibration_set:
        raise InsufficientPopulation(
            f"cohort {cohort_id!r} is flagged as the calibration set, which lacks the "
            "sample size to mean anything (NFR-CALIB-02): the gate refuses it"
        )
    cap = _class_size_cap(environ)
    if cap is not None and roster.class_size > cap:
        raise CalibrationError(
            f"cohort {cohort_id!r} carries {roster.class_size} submissions and the "
            f"deployment's {CALIB_CLASS_SIZE_CAP_ENV} is {cap}: the gate scores the FULL "
            "class (NFR-CALIB-02) or refuses, never a subset"
        )

    if threshold is not None:
        threshold_used = float(threshold)
        if not 0.0 <= threshold_used <= 1.0:
            raise CalibrationError(
                f"the threshold is a fraction of the class, got {threshold_used!r}: "
                "pass a value in [0, 1] or None to use the declared one"
            )
        threshold_source = "argument"
        threshold_declared_at = _next_timestamp()
    elif _INSTITUTIONAL_THRESHOLD is not None:
        threshold_used = _INSTITUTIONAL_THRESHOLD
        threshold_source = "configuration"
        threshold_declared_at = _INSTITUTIONAL_THRESHOLD_DECLARED_AT
        _INSTITUTIONAL_THRESHOLD = None  # one-shot: consumed by the run it was declared for
        _INSTITUTIONAL_THRESHOLD_DECLARED_AT = None
    else:
        env_threshold = _noninferiority_threshold_from_env(environ)
        if env_threshold is None:
            raise ThresholdNotDeclared(
                "no threshold was declared for this comparison (CT-CALIB-13): pass one, "
                f"call declare_institutional_threshold first, or set "
                f"{CALIB_NONINFERIORITY_THRESHOLD_ENV}. {CALIB_NONINFERIORITY_THRESHOLD} is "
                "the HLD's example, not a validated value, and the gate does not default it"
            )
        threshold_used = env_threshold
        threshold_source = "environment"
        threshold_declared_at = _next_timestamp()

    shifted = roster.shifted_papers
    shifted_fraction = shifted / roster.class_size
    first_result_at = _next_timestamp()
    outcome = "reject" if shifted_fraction > threshold_used else "pass"
    notes = (
        f"{shifted} of {roster.class_size} submissions shifted a full band "
        f"({shifted_fraction:.2f}) against a threshold of {threshold_used} "
        f"({threshold_source}): "
        + (
            "the revision is rejected and the class is graded against R₀ (FR-CALIB-08)"
            if outcome == "reject"
            else "the shift is within the threshold: non-inferior, and no evidence the "
            "revision improved the rubric (CT-CALIB-16 is a non-promise)"
        ),
    )
    return GateResult(
        gate="non_inferiority",
        outcome=outcome,
        r0=r0,
        r1=r1,
        cohort_id=cohort_id,
        threshold_used=threshold_used,
        threshold_source=threshold_source,
        threshold_declared_at=threshold_declared_at,
        first_result_at=first_result_at,
        shifted_papers=shifted,
        class_size=roster.class_size,
        shifted_fraction=shifted_fraction,
        advisory_only=False,
        revert_to=r0 if outcome == "reject" else None,
        notes=notes,
    )


def back_translate(r0: str, r1: str, off_panel: OffPanelModelRef | None = None) -> GateResult:
    """The adversarial back-translation gate (`FR-CALIB-09`, `CT-CALIB-08`, §6.6).

    A model **not in the scoring panel** is asked to construct a student response on
    which R₀ and R₁ would assign different scores. A successful construction is evidence
    the construct changed, and the outcome is a **rejection** — not an advisory note
    attached to a revision that ships anyway, which would be `CT-CALIB-02`'s warned
    revision renamed. When every attempt fails to construct a divergence the gate passes,
    with the note that absence of evidence is not evidence of preservation: several
    angles were probed and none found the seam, which §6.6 reads as evidence of
    preservation only in the weak sense.

    With no explicit checker the gate reads the deployment's declared one —
    `CALIB_OFF_PANEL_MODEL`, or its env channel `HARNESS_CALIB_OFF_PANEL_MODEL`, at call
    time. Nothing declared is the enumerated unavailable mode: the gate never invents an
    adversary.

    The off-panel build is refused when it shares a served build with the panel
    (`OffPanelConfigurationError`) — at the gate as well as at configuration time,
    because a registry the caller filled by hand deserves the same teeth
    (`NFR-CALIB-04`). A build with no bound construction transport is unavailable
    (`OffPanelUnavailable`), the enumerated failure mode that ends at R₀ like every
    other.
    """
    if not r0 or not r1:
        raise CalibrationError("back_translate needs both rubric versions to ask about")
    if off_panel is None:
        declared = _off_panel_model_declared()
        if declared is None:
            raise OffPanelUnavailable(
                "no off-panel checker is declared: set CALIB_OFF_PANEL_MODEL (or "
                f"{CALIB_OFF_PANEL_MODEL_ENV}) — the gate never invents an adversary "
                "(CT-CALIB-02's off_panel_model_unavailable mode)"
            )
        off_panel = _off_panel_model_ref_from_declared(declared)
    if off_panel.build_key in _PANEL_BUILDS:
        raise OffPanelConfigurationError(
            f"the off-panel model {off_panel.provider}/{off_panel.build_id} is in the "
            "scoring panel: a shared build would let the panel's own blind spots define "
            "the adversarial search, so the gate would pass by construction "
            "(CT-CALIB-08, NFR-CALIB-04)"
        )
    provider = _OFF_PANEL_PROVIDERS.get(off_panel.build_key)
    angles = _BACK_TRANSLATION_ANGLES
    if provider is None:
        session = _OFF_PANEL_SESSIONS.get(off_panel.build_key)
        if session is not None:
            provider = _RecordedSessionProvider(session)
            angles = provider.angles
    if provider is None:
        raise OffPanelUnavailable(
            f"no construction transport is bound for the off-panel build "
            f"{off_panel.provider}/{off_panel.build_id}: the gate never invents one "
            "(CT-CALIB-02's off_panel_model_unavailable mode)"
        )
    constructions = _construct_through_provider(provider, off_panel, r0, r1, angles)
    attempts = tuple(
        f"{attempt.angle}: "
        + ("constructed a divergent response" if attempt.response is not None else "no construction")
        for attempt in constructions
    )
    constructed = next((a for a in constructions if a.response is not None), None)
    if constructed is None:
        return GateResult(
            gate="back_translation",
            outcome="pass",
            r0=r0,
            r1=r1,
            divergent_response_found=False,
            advisory_only=False,
            attempts=attempts,
            notes=(
                "no attempt constructed a response on which R0 and R1 would differ; the "
                "gate passes on the attempts' failure, which is evidence of preservation "
                "only in §6.6's weak sense — absence of evidence is not evidence the "
                "construct did not change",
            ),
        )
    divergence_note = constructed.divergence_note or (
        "the attempt did not name the divergence"
    )
    return GateResult(
        gate="back_translation",
        outcome="reject",
        r0=r0,
        r1=r1,
        divergent_response_found=True,
        constructed_response=constructed.response,
        advisory_only=False,
        revert_to=r0,
        attempts=attempts,
        notes=(
            f"an off-panel model constructed a response on which R0 and R1 would assign "
            f"different scores ({divergence_note}): a successful construction "
            "is evidence the construct changed (FR-CALIB-09), so the revision is rejected "
            "rather than shipping with a note (CT-CALIB-02, CT-CALIB-08)",
        ),
    )


def _construct_through_provider(provider: Any, off_panel: "OffPanelModelRef", r0: str, r1: str,
                                angles: Sequence[str]) -> tuple["_ConstructionAttempt", ...]:
    """Ask the off-panel checker, through `InferenceProvider.complete()`, once per angle, for a
    student response on which R0 and R1 would assign different scores (#536, CT-PROV-08).
    An unavailable provider surfaces as `OffPanelUnavailable`, and nothing falls back to
    another model: the gate ends at R0 like every other enumerated failure."""
    from aeh.conf import ModelRef
    from aeh.prov import PromptPayload, ProviderError, SamplingParams

    ref = ModelRef(role="off_panel", provider=off_panel.provider, build_id=off_panel.build_id,
                   quantization=None)
    out: list[_ConstructionAttempt] = []
    for angle in angles:
        payload = PromptPayload(fields=(
            ("task", "construct a student response on which the two rubric versions would "
                     "assign different scores; answer JSON {response, divergence_note}, with "
                     "response null when no such response exists"),
            ("r0", r0), ("r1", r1), ("angle", angle),
        ))
        try:
            completion = provider.complete(payload, ref, SamplingParams(temperature=0.0))
        except ProviderError as error:
            raise OffPanelUnavailable(
                f"the off-panel checker {off_panel.provider}/{off_panel.build_id} is "
                f"unavailable ({type(error).__name__}): the gate does not fall back to another "
                "model (CT-PROV-08, CT-CALIB-02)") from error
        text = str(getattr(completion, "text", "") or "").strip()
        if text.startswith("```"):
            # A fenced block (```json ... ```) is the usual shape of a model's JSON answer.
            text = text.strip("`").strip()
            if text[:4].lower() == "json":
                text = text[4:].strip()
        try:
            answer = json.loads(text)
        except ValueError:
            answer = None
        if not isinstance(answer, dict):
            # An answer the gate cannot read is not "no construction": reading it that way
            # would pass the revision on the checker's silence. It ends at R0 like every
            # other unavailable checker (#536 review, CT-CALIB-02).
            raise OffPanelUnavailable(
                f"the off-panel checker {off_panel.provider}/{off_panel.build_id} answered "
                f"the {angle!r} angle with something that is not the requested JSON object")
        response = answer.get("response")
        note = answer.get("divergence_note")
        out.append(_ConstructionAttempt(
            angle=angle, response=response if isinstance(response, str) and response else None,
            divergence_note=note if isinstance(note, str) else None))
    return tuple(out)


# --- the version pin (FR-CALIB-11, §6.7, CT-CALIB-09) ------------------------------------------------


@dataclass(frozen=True)
class PinnedRevision:
    """The version pin a revision carries once approved (`FR-CALIB-11`, `CT-CALIB-09`):
    the package version, the approver, and the moment of the approval.

    The approver is the field that matters — a revision pinned with a version and a time
    but no approver is a rubric change nobody owns. The durable record rides the
    caller's `M-PKG` publish (this module has no store authority of its own,
    `CT-CALIB-06`); consumers keep R₀-scored and R₁-scored results out of one
    unannotated rollup, and the pin is what they annotate with."""

    package_version: str
    approved_by: str
    approved_at: datetime


def pin_revision(r1: str, *, approved_by: str) -> PinnedRevision:
    """Pin the approved revision as R₁: version, approver, timestamp (`CT-CALIB-09`).

    The approver is required at the boundary — a pin with a version and a time but no
    approver is a rubric change nobody owns. The pin value is returned for the caller to
    record durably through `M-PKG` (see `PinnedRevision`); nothing is written here,
    because this module holds no store authority of its own (`CT-CALIB-06`)."""
    if not r1 or not r1.strip():
        raise CalibrationError("pin_revision needs the revision's package version")
    if not approved_by or not approved_by.strip():
        raise CalibrationError(
            "a pinned revision names its approver: a pin with a version and a timestamp "
            "but no approver is a rubric change nobody owns (FR-CALIB-11, CT-CALIB-09)"
        )
    return PinnedRevision(
        package_version=r1,
        approved_by=approved_by,
        approved_at=_next_timestamp(),
    )
