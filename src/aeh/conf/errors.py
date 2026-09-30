"""The errors M-CONF raises."""

from __future__ import annotations


# --- errors --------------------------------------------------------------------------------


class RunConfigError(Exception):
    """Base for every `M-CONF` failure.

    A **neutral** base with four siblings under it, never a chain: if
    `UnresolvedModelRefError` subclassed `ConfigurationError`, every "exact exception type"
    oracle in test-plan §5.1 would pass against the wrong failure.

    `retryable` is a class attribute rather than documentation because `TC-CONF-C08` asserts it:
    all four are raised **before** the `run` row is written, so there is nothing to retry and
    nothing to clean up (`CT-CONF-08`).
    """

    retryable = False


class ConfigurationError(RunConfigError):
    """A required key is absent, unrecognized, or of the wrong shape (`FR-CONF-01`, `-06`, `-07`).

    Raised rather than defaulting. `CT-CONF-11`: "No key has a silent default that selects a
    backend — absence raises."
    """


class UnresolvedModelRefError(RunConfigError):
    """A `ModelRef` is not a resolved build identity, or is the wrong form for the backend.

    `FR-CONF-03`: a friendly name such as `"Llama 3.3 70B"` fails validation.
    """


class BackendMismatchError(RunConfigError):
    """A resumed run's persisted backend disagrees with current configuration (`FR-CONF-04`).

    Declared here so the taxonomy `CT-CONF-08` names is complete and `TC-CONF-15`'s invariant
    ("one of the four declared exception types") can be written. Raised by `rehydrate_run_config`
    and `_refuse_on_mismatch`.
    """


class ConsentGateError(RunConfigError):
    """A remote provider was bound for a cohort that is neither synthetic nor consented
    (`FR-CONF-08`, RISK-10).

    Declared here for the same reason as `BackendMismatchError`. Raised by `_check_consent`, on
    resolution and — when a cohort is supplied — on resume.
    """
