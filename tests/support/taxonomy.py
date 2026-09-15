"""Fixture F-TAXONOMY (gap-fix test plan §4.2): a scripted stub provider raising the provider
error taxonomy, call by call.

    call *n* raises `RateLimitedError(retry_after=0)`, `ProviderUnavailableError`,
    `BuildChangedError` or `ProviderError("500")`, or returns unparseable JSON, per a list

**Why a stub provider and not `RecordedFixtureProvider`.** The cases that use it (TC-EXTRACT-16,
TC-JUDGE-26, TC-JUDGE-28, TC-EXTRACT-18, TC-ORCH-43, RES-20) are about what a *worker* does when
the boundary raises — the recorded provider records successes, and a stub is the only way to
program a failure at a chosen call. The shipped error classes carry no `retry_after` attribute
(they are plain `Exception` subclasses), so `RateLimitedError` is raised with a message; the
retry wait is `M-PROV`'s concern and is exercised by `TC-PROV-18`, not here.

Each script step is one of:

* an exception **class** or **instance** — raised (a class is instantiated with a message naming
  the step);
* `UNPARSEABLE` — a `Completion` whose text is not JSON (a strike through the parser's
  `ValueError`, the contrast arm);
* a `Completion` — returned;
* a callable `(payload, model_ref, params) -> step` — resolved at call time, for steps that need
  the request (a recorded success, or a clock advance).

Every call is recorded with the `work_unit.attempts` value the ledger held at that moment when an
`attempts_probe` is supplied, so "attempts unchanged" and "attempts = 1 after one call" are read
from the ledger between calls, not inferred from the call count.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from aeh.prov import (
    BuildChangedError,
    Completion,
    ProviderError,
    ProviderUnavailableError,
    RateLimitedError,
)

UNPARSEABLE = object()

#: The three errors FR-EXTRACT-11 / FR-JUDGE-19 make **not strikes**.
TAXONOMY_THREE: tuple[type[ProviderError], ...] = (
    RateLimitedError,
    ProviderUnavailableError,
    BuildChangedError,
)


def server_error() -> ProviderError:
    """`ProviderError("500")` — a generic provider failure that stays a strike."""
    return ProviderError("500")


def completion(text: str, *, build_id: str, latency_ms: int = 0) -> Completion:
    return Completion(
        text=text,
        tokens_in=0,
        tokens_out=0,
        latency_ms=latency_ms,
        resolved_build=build_id,
        cached_prefix_tokens=0,
        cost=None,
    )


@dataclass
class TaxonomyProvider:
    """The scripted boundary. `script` is consumed one step per call; a call past its end
    fails the test loudly rather than inventing a reply."""

    script: Sequence[Any]
    attempts_probe: Callable[[], int] | None = None
    build_id: str = "taxonomy-build"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete(self, payload: Any, model_ref: Any, params: Any) -> Any:
        index = len(self.calls)
        record: dict[str, Any] = {
            "index": index,
            "model": getattr(model_ref, "build_id", None),
            "attempts_before": self.attempts_probe() if self.attempts_probe else None,
        }
        self.calls.append(record)
        if index >= len(self.script):
            raise AssertionError(
                f"F-TAXONOMY: call {index + 1} is past the {len(self.script)}-step script — "
                f"the worker made a call the case did not program"
            )
        step = self.script[index]
        if callable(step) and not isinstance(step, type):
            step = step(payload, model_ref, params)
        record["step"] = step if isinstance(step, type) else type(step).__name__
        if isinstance(step, type) and issubclass(step, BaseException):
            raise step(f"F-TAXONOMY call {index + 1}: {step.__name__}")
        if isinstance(step, BaseException):
            raise step
        if step is UNPARSEABLE:
            return completion("this is not JSON {", build_id=self.build_id)
        return step


@dataclass
class PerJudgeScript:
    """A boundary scripted per judge build: each judge consumes its own list, so a panel's
    judges can fail differently in one run (TC-JUDGE-28)."""

    scripts: dict[str, list[Any]]
    calls: list[str] = field(default_factory=list)

    def complete(self, payload: Any, model_ref: Any, params: Any) -> Any:
        build_id = getattr(model_ref, "build_id", None)
        self.calls.append(build_id)
        queue = self.scripts.get(build_id)
        if not queue:
            raise AssertionError(f"F-TAXONOMY: no scripted reply left for judge {build_id!r}")
        step = queue.pop(0)
        if callable(step):
            step = step(payload, model_ref, params)
        if isinstance(step, BaseException):
            raise step
        return step


__all__ = [
    "PerJudgeScript",
    "TAXONOMY_THREE",
    "TaxonomyProvider",
    "UNPARSEABLE",
    "completion",
    "server_error",
]
