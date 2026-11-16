"""The logger, the fixture directory, and the retry and endpoint knobs."""

from __future__ import annotations

import logging
import os

from aeh.conf import ConfigurationError


LOGGER_NAME = "aeh.prov"


_LOGGER = logging.getLogger(LOGGER_NAME)


#: Design §3.2 Configuration. Read once at construction, never per call (`CT-PROV-04`).
FIXTURE_DIR_ENV = "HARNESS_FIXTURE_DIR"


#: Seam 3. The fixture backend's declared `max_concurrency`: it is bounded by filesystem
#: parallelism, which differs by an order of magnitude between a laptop SSD and a shared CI
#: volume. The default is HLD §8.4's reference figure so the double declares what the local
#: server declares — a double advertising a *different* ceiling sends `M-ORCH` down a
#: different scheduling path than the backend it stands in for (RISK-37).
FIXTURE_MAX_CONCURRENCY_ENV = "HARNESS_FIXTURE_MAX_CONCURRENCY"


DEFAULT_FIXTURE_MAX_CONCURRENCY = 32


# --- the knobs (seam 3: production value is the default) ---------------------------------------

#: `HARNESS_RETRY_MAX` (default 3) — the retry budget `FR-PROV-06` names. Attempts, not
#: retries: a budget of 3 is one first attempt and two retries.
RETRY_MAX_ENV = "HARNESS_RETRY_MAX"


DEFAULT_RETRY_MAX = 3


#: `HARNESS_BACKOFF_BASE_MS` (default 250) — the exponential backoff's base, before jitter.
BACKOFF_BASE_MS_ENV = "HARNESS_BACKOFF_BASE_MS"


DEFAULT_BACKOFF_BASE_MS = 250


#: `HARNESS_RETRY_AFTER_CEILING_S` (default 120) — a `Retry-After` above the ceiling is
#: treated as malformed: a provider answering "come back in an hour" is unavailable for a
#: school-day run, and waiting would hold the run hostage to a figure the provider made up.
RETRY_AFTER_CEILING_S_ENV = "HARNESS_RETRY_AFTER_CEILING_S"


DEFAULT_RETRY_AFTER_CEILING_S = 120.0


#: `HARNESS_CONCURRENCY_FLOOR` (default 1) — where in-flight dispatches ratchet down to on
#: repeated 429s (`FR-PROV-07`: "toward the configured floor rather than the full batch").
CONCURRENCY_FLOOR_ENV = "HARNESS_CONCURRENCY_FLOOR"


DEFAULT_CONCURRENCY_FLOOR = 1


#: The two live providers' endpoints and credential (`CT-PROV-15`: this module is the only
#: place in the tree that names a model endpoint).
OPENROUTER_BASE_URL_ENV = "OPENROUTER_BASE_URL"


OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"


LOCAL_INFERENCE_BASE_URL_ENV = "LOCAL_INFERENCE_BASE_URL"


DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


DEFAULT_LOCAL_INFERENCE_BASE_URL = "http://127.0.0.1:8080/v1"


#: The hardware profile whose concurrency `LocalServerProvider.capabilities` declares
#: (FR-PROV-47, FR-CONF-06). The same key `M-CONF` resolves an `edge-local` run from; read once
#: at construction when the caller does not pass `hardware_profile=`.
HARDWARE_PROFILE_ENV = "HARNESS_HARDWARE_PROFILE"


#: Seam 3. Overrides the local server's declared `max_concurrency` outright, for a box whose
#: server cannot keep the profile's ceiling in flight (a slower test machine, a server started
#: with fewer parallel slots). Unset, the hardware profile's ceiling stands.
LOCAL_MAX_CONCURRENCY_ENV = "HARNESS_LOCAL_MAX_CONCURRENCY"


#: What a local server declares when no hardware profile is known: a provider built outside a
#: resolved `edge-local` run (a probe, a unit test). One request at a time is the value every
#: server can keep.
DEFAULT_LOCAL_MAX_CONCURRENCY = 1


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigurationError(f"{name}={raw!r} is not an integer") from error
    if value < 0:
        raise ConfigurationError(f"{name}={value} must not be negative")
    return value


#: FR-PROV-48: the retention probe before dispatch, on by default on every remote profile. Set
#: to `0` it turns the probe off for the recorded tier (`RecordedFixtureProvider`) only: replay
#: sends nothing anywhere, so a test box may skip it; a live provider is probed whatever the
#: knob says, because a knob that silenced the check on live traffic would read as a kept
#: privacy promise.
RETENTION_PRECHECK_ENV = "HARNESS_RETENTION_PRECHECK"


def retention_precheck_on() -> bool:
    """`HARNESS_RETENTION_PRECHECK`, read at call time: off only for an explicit `0`, `false`,
    `no` or `off`; anything else, unset included, leaves the probe on."""
    raw = (os.environ.get(RETENTION_PRECHECK_ENV) or "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ConfigurationError(f"{name}={raw!r} is not a number") from error
    if value < 0:
        raise ConfigurationError(f"{name}={value} must not be negative")
    return value
