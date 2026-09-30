"""Parsing an engine reply into a `Decision`, the confidence rules, and the request key."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from aeh.conf import ModelRef

from .errors import MalformedResponseError, MissingConfidenceError
from .request_key import _emit_framed, _encode_scalar, _frame, _FRAME_WIDTH, _MODEL_REF_FIELDS
from .decision_types import (
    ChoiceAnswer,
    ChoiceQuestion,
    Decision,
    DECISION_KEY_SCHEME,
    DecisionAnswer,
    DecisionRequest,
    NoulAnswer,
    NoulQuestion,
    PROBABILITY_SUM_TOLERANCE,
    ScoreAnswer,
    ScoreQuestion,
)


def derived_confidence(probabilities: Sequence[float]) -> float:
    """TypeSafe's published confidence statistic, `(n·peak - 1)/(n - 1)` (FR-PROV-19). For a yes/no
    question with probabilities `{p, 1 - p}` it is `|2p - 1|`."""
    values = list(probabilities)
    n = len(values)
    if n < 2:
        raise ValueError("a confidence needs at least two outcomes")
    return max(0.0, min(1.0, (n * max(values) - 1.0) / (n - 1)))


def _number(value: Any, where: str) -> float:
    """A JSON number between 0 and 1, or `MalformedResponseError`. Booleans do not count as
    numbers."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise MalformedResponseError(f"{where} is {value!r}, not a number")
    if not 0.0 <= float(value) <= 1.0:
        raise MalformedResponseError(f"{where} = {value!r} lies outside [0, 1]")
    return float(value)


def _distribution(values: Sequence[float], where: str) -> None:
    total = math.fsum(values)
    if abs(total - 1.0) > PROBABILITY_SUM_TOLERANCE:
        raise MalformedResponseError(
            f"{where} sums to {total!r}, not 1 ± {PROBABILITY_SUM_TOLERANCE}; the answer is "
            f"refused, never renormalised (FR-PROV-20)")


#: FR-PROV-19's two confidence rules (design 1.8). `jev`: Choice/Score confidence is the
#: engine's reported value and is required. `small`: `openjev-small` reports none, so the
#: provider derives Choice/Score confidence and ignores any value the shim emits. Under both,
#: a Noul's confidence is its `p`.
CONFIDENCE_RULES = ("jev", "small")


def confidence_rule(model_ref: Any) -> str:
    """Which confidence rule applies to a model reference (FR-PROV-19): `small` for
    `openjev-small`, `jev` for every other provider, including the fixture that stands in for them.
    """
    return "small" if getattr(model_ref, "provider", None) == "openjev-small" else "jev"


def _confidence(answer: Mapping[str, Any], values: Sequence[float], where: str,
                rule: str) -> tuple[float, str]:
    if rule == "small":
        return derived_confidence(values), "derived"
    reported = answer.get("confidence")
    if reported is None:
        raise MissingConfidenceError(
            f"{where}.confidence is absent: a Jev build reports its own confidence and the "
            f"harness never derives one (FR-PROV-19)")
    return _number(reported, f"{where}.confidence"), "reported"


def parse_decision(document: Any, request: DecisionRequest, *, fallback_build: str,
                   latency_ms: int = 0, cost: Decimal | None = None, rule: str = "jev") -> Decision:
    """Turn an engine response document (design §1.2) into a checked `Decision`, or raise
    `MalformedResponseError`.

    The only place a decision response is interpreted, shared by every implementation so the
    fixture double refuses exactly what a live provider refuses (CT-PROV-18, CT-PROV-23)."""
    if not isinstance(document, dict):
        raise MalformedResponseError("the decision response is not a JSON object")
    answers = document.get("answers")
    if not isinstance(answers, dict):
        raise MalformedResponseError("the decision response carries no 'answers' object")
    expected = [question.key for question in request.questions]
    if set(answers) != set(expected):
        raise MalformedResponseError(
            f"answer keys {sorted(answers)} do not equal question keys {sorted(expected)}")
    parsed: dict[str, DecisionAnswer] = {}
    for question in request.questions:
        where = f"answers.{question.key}"
        raw = answers[question.key]
        if not isinstance(raw, dict):
            raise MalformedResponseError(f"{where} is not an object")
        kind = {ChoiceQuestion: "choice", ScoreQuestion: "score", NoulQuestion: "noul"}[type(question)]
        if raw.get("type") != kind:
            raise MalformedResponseError(f"{where}.type is {raw.get('type')!r}, the question is {kind!r}")
        if isinstance(question, NoulQuestion):
            p = _number(raw.get("noul"), f"{where}.noul")
            parsed[question.key] = NoulAnswer(p_true=p, confidence=p,
                                              confidence_source="derived" if rule == "small" else "reported")
        elif isinstance(question, ChoiceQuestion):
            probabilities = raw.get("probabilities")
            if not isinstance(probabilities, dict) or set(probabilities) != set(question.labels):
                raise MalformedResponseError(f"{where}.probabilities keys do not equal the options")
            values = {label: _number(probabilities[label], f"{where}.probabilities.{label}")
                      for label in question.labels}
            _distribution(list(values.values()), f"{where}.probabilities")
            choice = raw.get("choice")
            if choice not in values:
                raise MalformedResponseError(f"{where}.choice {choice!r} is not one of the options")
            confidence, source = _confidence(raw, list(values.values()), where, rule)
            parsed[question.key] = ChoiceAnswer(choice, values, confidence, source)
        else:
            count = len(question.levels)
            indices = [str(i) for i in range(count)]
            probabilities = raw.get("probabilities")
            if not isinstance(probabilities, dict) or set(probabilities) != set(indices):
                raise MalformedResponseError(f"{where}.probabilities must cover exactly indices 0…{count - 1}")
            legend = raw.get("legend")
            # Required, not optional: the legend is the only evidence that index i means
            # levels[i], and an off-by-one there is a plausible wrong band (RISK-62).
            if not isinstance(legend, dict) or set(legend) != set(indices) or any(
                    legend[str(i)] != question.levels[i] for i in range(count)):
                raise MalformedResponseError(f"{where}.legend is missing or does not name the requested levels in order")
            values = tuple(_number(probabilities[i], f"{where}.probabilities.{i}") for i in indices)
            _distribution(values, f"{where}.probabilities")
            score = raw.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
                raise MalformedResponseError(f"{where}.score is {score!r}, not a number")
            confidence, source = _confidence(raw, values, where, rule)
            parsed[question.key] = ScoreAnswer(float(score), values, confidence, source)
    usage = document.get("usage") or {}
    if not isinstance(usage, dict):
        raise MalformedResponseError("the decision response 'usage' is not an object")
    tokens = {}
    for name in ("input_tokens", "output_tokens"):
        value = usage.get(name, 0) or 0
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise MalformedResponseError(f"usage.{name} is {value!r}, not a non-negative integer")
        tokens[name] = value
    served = document.get("model") or document.get("provider")
    return Decision(
        answers=MappingProxyType(parsed),
        tokens_in=tokens["input_tokens"],
        tokens_out=tokens["output_tokens"],
        latency_ms=int(latency_ms),
        resolved_build=served if isinstance(served, str) and served else fallback_build,
        cost=cost,
    )


def decision_questions_document(request: DecisionRequest) -> dict[str, Any]:
    """The `questions` object of an engine request (design §1.2), in the caller's order. Every live
    provider builds its request body from this, so every backend receives the same questions."""
    out: dict[str, Any] = {}
    for q in request.questions:
        if isinstance(q, ChoiceQuestion):
            out[q.key] = {"type": "choice", "instructions": q.instructions,
                          "criteria": {label: desc for label, desc in q.options}}
        elif isinstance(q, ScoreQuestion):
            out[q.key] = {"type": "score", "instructions": q.instructions, "criteria": list(q.levels)}
        else:
            entry: dict[str, Any] = {"type": "noul", "instructions": q.instructions}
            if q.when_true is not None or q.when_false is not None:
                entry["criteria"] = {"true": q.when_true, "false": q.when_false}
            out[q.key] = entry
    return out


def decision_request_key(request: DecisionRequest, model_ref: ModelRef) -> str:
    """SHA-256 over the whole `DecisionRequest` and `ModelRef` (FR-PROV-25), framed like
    `request_key`. It uses its own scheme tag, so a completion recording can never answer a
    decision."""
    digest = hashlib.sha256()
    digest.update(_frame(DECISION_KEY_SCHEME))
    digest.update(_frame(b"state"))
    _emit_framed(digest.update, request.state.encode("utf-8"))
    digest.update(_frame(b"questions"))
    digest.update(len(request.questions).to_bytes(_FRAME_WIDTH, "big"))
    for q in request.questions:
        if isinstance(q, ChoiceQuestion):
            parts: tuple[Any, ...] = ("choice", q.key, q.instructions,
                                      tuple(item for pair in q.options for item in pair))
        elif isinstance(q, ScoreQuestion):
            parts = ("score", q.key, q.instructions, q.levels)
        else:
            parts = ("noul", q.key, q.instructions, q.when_true, q.when_false)
        for part in parts:
            digest.update(_encode_scalar(part))
    digest.update(_frame(b"model_ref"))
    for name in _MODEL_REF_FIELDS:
        digest.update(_frame(name.encode("utf-8")))
        digest.update(_encode_scalar(getattr(model_ref, name)))
    return "sha256:" + digest.hexdigest()
