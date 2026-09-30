"""The consent gate: remote providers are refused for real student work unless consent is recorded."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .vocabulary import BACKEND_PROFILES
from .errors import ConfigurationError, ConsentGateError
from .frozen import _typeerror_on_mutation
from .checks import _echo
from .run_config import CohortRef
from .sources import parse_allow_remote_real_work


# --- consent (FR-CONF-08, RISK-10) -----------------------------------------------------------

#: The consent classes that may be graded by a remote provider without an override (ADR-5).
#: `real` is absent deliberately, and an undeclared cohort defaults to `real` on `CohortRef`.
CONSENTED_CLASSES: frozenset[str] = frozenset({"synthetic", "consented"})


#: The backends that dispatch student work off the machine. `edge-local` is not one of them, so
#: the gate does not apply there at all — there is nothing to consent to.
REMOTE_PROFILES: frozenset[str] = frozenset({"cloud-hosted", "dev-ci"})


@_typeerror_on_mutation
@dataclass(frozen=True)
class ConsentOverride:
    """The record `FR-CONF-08` requires when real work is sent to a remote provider anyway.

    *"the override and its supplier are written to the audit record"* — but `CT-CONF-09` says
    this module writes **nothing**, and `CT-CONF-C02` leaves no free field on `RunConfig`. So
    `M-CONF` **produces** this value and `M-ORCH` persists it. Producing it and writing it are
    different jobs, and only one of them is this module's.
    """

    cohort_id: str
    consent_class: str
    backend_profile: str
    supplied_by: str


def consent_override_for(cfg: Mapping[str, Any], cohort: CohortRef) -> ConsentOverride | None:
    """The audit record for this resolution's consent override, or `None` if none was needed.

    `M-ORCH` calls this and writes the result. It shares `_check_consent`'s logic, so a run that
    resolved under an override and the record of that override cannot disagree — two
    implementations of the same rule is how a run ends up dispatched with nothing in the audit
    trail saying who authorised it.

    The profile is validated here for the same reason. Reading `HARNESS_PROFILE` raw made a
    near-miss — `'Cloud-Hosted'`, `'cloud-hosted '` — fall outside `REMOTE_PROFILES` and return
    `None`, which reads as *"no override was needed"* for a configuration that
    `resolve_run_config` refuses outright. The two must refuse together or the claim that they
    are one rule is false where it matters.
    """
    backend_profile = cfg.get("HARNESS_PROFILE") if isinstance(cfg, Mapping) else None
    if not isinstance(backend_profile, str) or backend_profile not in BACKEND_PROFILES:
        raise ConfigurationError(
            f"HARNESS_PROFILE must be one of {BACKEND_PROFILES} before a consent override can "
            f"be recorded, got {_echo('HARNESS_PROFILE', backend_profile)}."
        )
    return _check_consent(cfg, cohort, backend_profile)


def _check_consent(
    cfg: Mapping[str, Any], cohort: CohortRef, backend_profile: Any
) -> ConsentOverride | None:
    """Refuse a remote binding for work that is neither synthetic nor consented.

    RISK-10 is student work leaving the machine without consent, and this is the pre-dispatch
    check ADR-5 added the `consent_class` column for. Fails **closed** twice over: an undeclared
    cohort is `real` by `CohortRef`'s default, and an override is refused unless it names who
    supplied it.
    """
    if backend_profile not in REMOTE_PROFILES:
        return None  # nothing leaves the machine, so there is nothing to gate
    if cohort.consent_class in CONSENTED_CLASSES:
        return None

    supplied_by = cfg.get("allow_remote_real_work_supplied_by")
    if not parse_allow_remote_real_work(cfg.get("HARNESS_ALLOW_REMOTE_REAL_WORK")):
        raise ConsentGateError(
            f"cohort {cohort.cohort_id!r} has consent_class {cohort.consent_class!r}, which is "
            f"neither 'synthetic' nor 'consented', so its work may not be sent to a "
            f"{backend_profile!r} provider (FR-CONF-08, R31). Supply "
            f"HARNESS_ALLOW_REMOTE_REAL_WORK together with "
            f"allow_remote_real_work_supplied_by to override this deliberately."
        )

    # `TC-CONF-08`'s oracle: "a record naming the override but not its supplier fails." An
    # override nobody is accountable for is the configuration flag ADR-5 set out to avoid --
    # "explicit and logged rather than a flag someone sets once and forgets" -- so it is refused
    # rather than recorded as anonymous.
    if not isinstance(supplied_by, str) or not supplied_by.strip():
        # `ConsentGateError`, not `ConfigurationError`: the outcome is a refused remote binding
        # for non-consented work, which is this exception's documented job. `CT-CONF-08` makes
        # the four types a closed taxonomy consumers branch on, and `M-ORCH` branching on
        # `ConsentGateError` to raise consent-required UX would miss this path entirely.
        raise ConsentGateError(
            "allow_remote_real_work_supplied_by must name who authorised sending real student "
            "work to a remote provider. The override is not usable without attribution, so the "
            "gate still refuses (FR-CONF-08)."
        )

    return ConsentOverride(
        cohort_id=cohort.cohort_id,
        consent_class=cohort.consent_class,
        backend_profile=backend_profile,
        supplied_by=supplied_by.strip(),
    )
