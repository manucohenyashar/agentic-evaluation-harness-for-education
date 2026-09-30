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
