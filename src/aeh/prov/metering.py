"""A provider wrapper that adds up what its completions cost (FR-CONSOLE-97)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from aeh.conf import ModelRef

from .records import Completion, PromptPayload, SamplingParams


class MeteredProvider:
    """Wraps a completion provider and sums the cost each completion reports.

    The console's reading job reads its files through one of these so it can stop at its cost
    limit and record its spend: `spent` is everything metered (starting from `spent=`, the
    spend a resumed job already had), `spent_here` what this wrapper metered itself. A
    completion that reports no cost adds nothing; nothing is estimated here. Every other
    attribute is the wrapped provider's own, so the caller sees the real provider."""

    def __init__(self, provider: Any, *, spent: Any = 0) -> None:
        self._metered = provider
        self.spent = Decimal(str(spent or 0))
        self.spent_here = Decimal(0)

    def complete(self, prompt: PromptPayload, model_ref: ModelRef,
                 params: SamplingParams) -> Completion:
        completion = self._metered.complete(prompt, model_ref, params)
        cost = getattr(completion, "cost", None)
        if cost is not None:
            figure = Decimal(str(cost))
            self.spent += figure
            self.spent_here += figure
        return completion

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") or name == "_metered":
            raise AttributeError(name)
        return getattr(self._metered, name)
