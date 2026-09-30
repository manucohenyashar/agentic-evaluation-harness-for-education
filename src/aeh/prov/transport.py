"""One HTTP attempt with no retry logic, the clock a retry loop needs, and the default transport."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from .errors import TransportError


# --- the interface -------------------------------------------------------------------------------


# --- the transport and clock seam (FR-PROV-15, design v1.5) ------------------------------------
#
# The seam this story owns. Design §3.2's v1.5 text: the real providers take `transport`,
# `clock`, `retention_answers` and `on_dispatch` as constructor arguments defaulting to the
# real ones, behaviour-neutrally. The point is not convenience — it is that the retry
# taxonomy below is *stated and assertable*: the only way to program a 429 without the seam
# was to stub the provider, which replaces the very code under test. A `Transport` is one
# HTTP attempt and nothing else; retry classification lives here, in this module, where
# `FR-PROV-06`'s rule can hold it.


@dataclass(frozen=True)
class HttpRequest:
    """One request as a `Transport` receives it. Plain data."""

    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class HttpResponse:
    """One response as a `Transport` returns it; `status` is the HTTP code. A connection failure
    never produces a response: it raises `TransportError`, which is what the retry loop relies on.
    """

    status: int
    headers: Mapping[str, str]
    body: bytes


class Transport(Protocol):
    """One HTTP attempt, with no retry logic (FR-PROV-15).

    Implementations raise `TransportError` for a connection failure or timeout, and return
    an `HttpResponse` otherwise — including for 429 and 5xx, whose *classification* is this
    module's job, not the transport's. A transport that retried internally would make
    `HARNESS_RETRY_MAX` a lie; the protocol's docstring is part of the contract for that
    reason.
    """

    def send(self, request: HttpRequest) -> HttpResponse: ...


class Clock(Protocol):
    """What a retry loop needs from time: a monotonic reading and a way to wait.

    Injected so `Retry-After: 2` honoured twenty times consumes no wall time in a test —
    test plan §4.6 makes `TC-ORCH-09` the suite's one sanctioned sleep, and a retry loop
    that slept for real would spend the whole budget on the first case that exercised it.
    """

    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    """The real clock, used by default; the only code in M-PROV that uses `time`."""

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def _wait(clock, seconds: float) -> None:
    """Wait `seconds` using whatever the injected clock provides.

    `SystemClock` sleeps for real. A test clock implements `advance` (the suite's
    `FrozenClock` does), and advancing is the honest equivalent: the wait consumes fake
    time, `rate_limit_wait_s` stays assertable, and §4.6's one-sanctioned-sleep rule is
    not spent by a retry loop. A clock with neither is treated as instantaneous."""
    sleeper = getattr(clock, "sleep", None)
    if callable(sleeper):
        sleeper(seconds)
        return
    advancer = getattr(clock, "advance", None)
    if callable(advancer):
        advancer(seconds)


class _DefaultTransport:
    """The real transport: one HTTP request through urllib, raising `TransportError` on any
    connection failure or timeout. This is the system's only egress point, the only code that opens
    a connection to a model endpoint (CT-PROV-15)."""

    def __init__(self, timeout_s: float = 120.0) -> None:
        self._timeout_s = timeout_s

    def send(self, request: HttpRequest) -> HttpResponse:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(
            request.url, data=request.body if request.body else None,
            headers=request.headers, method=request.method)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_s) as response:
                return HttpResponse(
                    status=response.status,
                    headers={k: v for k, v in response.headers.items()},
                    body=response.read(),
                )
        except urllib.error.HTTPError as error:
            return HttpResponse(
                status=error.code,
                headers={k: v for k, v in error.headers.items()},
                body=error.read(),
            )
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise TransportError(f"transport failure reaching {request.url}: {error}") from error
