"""`InferenceProvider`: the one interface every completion provider implements."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from aeh.conf import ModelRef

from .records import (
    CallPlan,
    Capabilities,
    Completion,
    CostEstimate,
    PromptPayload,
    RetentionReport,
    SamplingParams,
)


@runtime_checkable
class InferenceProvider(Protocol):
    """The one interface. Design §3.2, `CT-PROV-01`.

    All four operations are **synchronous and blocking**, and exactly one of them —
    `complete` — makes a model call. One `complete` is one model call: no batching, no
    coalescing, no speculative second sample.

    This module starts no thread and owns no queue. Concurrency belongs to `M-ORCH`, and an
    internal worker pool here would take it away silently — along with `M-JUDGE`'s isolation
    between scoring contexts, which rests on the caller deciding what runs beside what.
    """

    def complete(
        self, prompt: PromptPayload, model_ref: ModelRef, params: SamplingParams
    ) -> Completion: ...

    def capabilities(self, model_ref: ModelRef) -> Capabilities: ...

    def estimate_cost(self, plan: CallPlan) -> CostEstimate: ...

    def verify_retention(self, model_refs: Sequence[ModelRef]) -> RetentionReport: ...
