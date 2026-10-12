"""The authoring knobs (seam 3), read and validated **per invocation** (CT-AUTHOR-14).

Authoring freezes nothing (ADR-43), so unlike the run path's `RetryPolicy` — read once and
fixed — these knobs are re-read at the start of every `draft()` call: a knob discovered
invalid before the first extraction never half-drives a run, and a long-lived
`AuthoringService` picks up an operator's correction without being rebuilt. An explicit
field beats nothing, the environment beats the default, and every refusal names the knob
and its legal range.

The console-redesign delta (§3.1.3) adds the fourth knob, `HARNESS_AUTHOR_DOC_MAX_BYTES`:
the per-file size ceiling intake enforces on teacher documents.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from aeh.conf import ConfigurationError

#: The repair budget: total model calls per item **per chain model** — the first attempt
#: plus repairs — so `HARNESS_AUTHOR_ATTEMPTS=1` means one call and no repair (TC-AUTHOR-07).
#: NFR-AUTHOR-02's ceiling (`ATTEMPTS × |chain|` calls per item) counts the same way.
ATTEMPTS_ENV = "HARNESS_AUTHOR_ATTEMPTS"
ATTEMPTS_MIN = 1
ATTEMPTS_MAX = 5
DEFAULT_ATTEMPTS = 2

#: The per-call timeout, in seconds, enforced around every `complete()` the module issues —
#: reasoning steps and transcriptions alike. The provider protocol carries no timeout slot
#: (`InferenceProvider.complete` takes payload, ref, params), so the service enforces it
#: itself and treats an expiry as a provider failure for that model: the next model in the
#: chain is tried, and the spent call is recorded among the item's failures.
TIMEOUT_ENV = "HARNESS_AUTHOR_TIMEOUT_S"
TIMEOUT_MIN_S = 30
DEFAULT_TIMEOUT_S = 240

#: Whether a page with no text layer may ride the profile's transcriber (FR-AUTHOR-02).
#: `auto` transcribes; `off` refuses — and with no text anywhere that refusal is the
#: fail-fast `AuthoringInputError` (FR-AUTHOR-13). Any other value is refused.
TRANSCRIBE_ENV = "HARNESS_AUTHOR_TRANSCRIBE"
TRANSCRIBE_AUTO = "auto"
TRANSCRIBE_OFF = "off"
DEFAULT_TRANSCRIBE = TRANSCRIBE_AUTO

#: The per-file size ceiling intake enforces on teacher documents (`FR-AUTHOR-28`'s
#: oversize row), in bytes — 10 MB by default. The bound is an *upload*-time refusal: the
#: console checks it at upload (`CT-CONSOLE-36`), and `normalize_document` enforces it
#: again before any content is parsed. Values above the ceiling (`DOC_MAX_BYTES_CEILING`)
#: or non-positive are refused with a message naming the knob, the value and the domain.
DOC_MAX_BYTES_ENV = "HARNESS_AUTHOR_DOC_MAX_BYTES"
DEFAULT_DOC_MAX_BYTES = 10 * 1024 * 1024
DOC_MAX_BYTES_CEILING = 100 * 1024 * 1024


@dataclass(frozen=True)
class AuthoringSettings:
    """The invocation's authoring settings, as the design's Configuration table declares them.

    A **zero-argument constructor is the normal form** (`AuthoringSettings()`): every field
    is `None`, and `effective()` — called once per `draft()` invocation — then reads the
    environment and falls back to the defaults. A field set explicitly (`attempts=1`) is the
    scripted form: it wins over the default, while a set environment variable still wins over
    it, because the knobs are per-invocation operator overrides by design (CT-AUTHOR-14).

    The reasoning chain is deliberately absent: it is the run configuration's panel and
    escalation judges (FR-AUTHOR-04, ADR-42), never a knob. A `HARNESS_AUTHOR_MODEL`-style
    override is not read by anything in this module, and the only environment variables
    that change authoring behaviour are this module's own knobs (CT-AUTHOR-14).
    """

    attempts: int | None = None
    timeout_s: int | None = None
    transcribe: str | None = None
    doc_max_bytes: int | None = None

    def effective(self) -> "AuthoringSettings":
        """Resolve the invocation's settings: environment first, then the explicit fields,
        then the defaults — validating every value it returns and refusing every value it
        cannot use, before anything is extracted or any model is called."""
        return AuthoringSettings(
            attempts=self._resolve_int(
                ATTEMPTS_ENV, self.attempts, DEFAULT_ATTEMPTS, ATTEMPTS_MIN, ATTEMPTS_MAX,
                f"the legal range is {ATTEMPTS_MIN} to {ATTEMPTS_MAX} (the repair budget of "
                f"FR-AUTHOR-05: total calls per item per chain model, first attempt included)",
            ),
            timeout_s=self._resolve_int(
                TIMEOUT_ENV, self.timeout_s, DEFAULT_TIMEOUT_S, TIMEOUT_MIN_S, None,
                f"the minimum is {TIMEOUT_MIN_S} seconds (a reasoning step on a hosted judge "
                f"is seconds, not minutes; NFR-AUTHOR-02's assumption)",
            ),
            transcribe=self._resolve_transcribe(),
            doc_max_bytes=resolve_doc_max_bytes(self.doc_max_bytes),
        )

    @property
    def transcribe_enabled(self) -> bool:
        """Whether no-text-layer pages ride the transcriber under these settings."""
        assert self.transcribe is not None  # guaranteed by effective()
        return self.transcribe == TRANSCRIBE_AUTO

    def _resolve_int(self, name: str, explicit: int | None, default: int,
                     minimum: int, maximum: int | None, range_text: str) -> int:
        raw = os.environ.get(name)
        if raw is None or not raw.strip():
            if explicit is None:
                return default
            value = explicit
        else:
            try:
                value = int(raw.strip())
            except ValueError:
                raise ConfigurationError(
                    f"{name}={raw!r} is not an integer. The knob is read at call time and "
                    f"validated before the first model call, so a malformed value never "
                    f"half-drives a run; {range_text}."
                ) from None
        if value < minimum or (maximum is not None and value > maximum):
            raise ConfigurationError(
                f"{name}={value} is outside its legal range: {range_text}."
            )
        return value

    def _resolve_transcribe(self) -> str:
        raw = os.environ.get(TRANSCRIBE_ENV)
        if raw is None or not raw.strip():
            return self.transcribe if self.transcribe is not None else DEFAULT_TRANSCRIBE
        value = raw.strip()
        if value not in (TRANSCRIBE_AUTO, TRANSCRIBE_OFF):
            raise ConfigurationError(
                f"{TRANSCRIBE_ENV}={raw!r} is not a legal value: use "
                f"'{TRANSCRIBE_AUTO}' (no-text-layer pages ride the profile transcriber) "
                f"or '{TRANSCRIBE_OFF}' (refuse them; FR-AUTHOR-02)."
            )
        return value


def resolve_doc_max_bytes(explicit: int | None = None) -> int:
    """The per-file size ceiling intake enforces (`FR-AUTHOR-28`'s oversize row): the
    environment's value when `HARNESS_AUTHOR_DOC_MAX_BYTES` is set, else the explicit
    value, else the 10 MB default — and a refusal, before any document is read, for a
    non-positive value or one above the 100 MB ceiling, naming the knob, the value and
    the domain (CT-CONF-04's rule, `CT-CONSOLE-36`)."""
    raw = os.environ.get(DOC_MAX_BYTES_ENV)
    if raw is None or not raw.strip():
        value = DEFAULT_DOC_MAX_BYTES if explicit is None else explicit
    else:
        try:
            value = int(raw.strip())
        except ValueError:
            raise ConfigurationError(
                f"{DOC_MAX_BYTES_ENV}={raw!r} is not an integer. The knob bounds the "
                "per-file size of teacher documents and is read at call time, so a "
                "malformed value never half-drives a run."
            ) from None
    if value <= 0 or value > DOC_MAX_BYTES_CEILING:
        raise ConfigurationError(
            f"{DOC_MAX_BYTES_ENV}={value} is outside its legal range: the ceiling is a "
            "positive number of bytes per teacher document, at most "
            f"{DOC_MAX_BYTES_CEILING} ({DOC_MAX_BYTES_CEILING // (1024 * 1024)} MB)."
        )
    return value