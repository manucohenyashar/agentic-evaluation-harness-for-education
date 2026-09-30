"""The decision engine's request, question and answer types."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .errors import DecisionRequestError


# --- the decision surface (Jev design delta §3.1, FR-PROV-16…20/25…27/29) -----------------------
#
# A second provider surface beside `InferenceProvider`: typed questions in, typed probabilistic
# answers out. It exists for the decision engine (Jev) that `M-JUDGE` pre-screens the decision
# seat with. Three rules from the design shape everything below:
#
# - **Refuse, never repair** (FR-PROV-20). A response whose distribution does not sum to one, or
#   whose Score legend names a different level, is a `MalformedResponseError` — retryable per
#   CT-PROV-06 like any structural parse failure. Renormalising it would hide an engine or wire
#   defect behind a plausible-looking band.
# - **One statistic for confidence** (FR-PROV-19). A reported confidence is used when present;
#   otherwise, and always for a Noul, it is `(n·peak − 1)/(n − 1)` over the answer's own
#   distribution. Consumers never see a missing confidence.
# - **No substitution** (CT-PROV-21). A failing `decide` raises; choosing to ask an LLM instead is
#   `M-JUDGE`'s decision on a *confidence* outcome, never this module's on a *failure*.
#
# **Deviation, recorded:** design FR-PROV-16 names the per-implementation limits method
# `capabilities`. `RecordedFixtureProvider` serves both surfaces, and its `capabilities` already
# returns the `InferenceProvider`'s `Capabilities` (CT-PROV-04), so the decision surface's method
# is `decision_capabilities`. The decision-only live providers also answer to `capabilities`.

#: A question key: lowercase letters and underscores, no digits — so a key can never carry a
#: numeral into the request's rubric surface (FR-JUDGE-03, FR-PROV-17).
_DECISION_KEY = re.compile(r"\A[a-z][a-z_]{0,31}\Z")


#: Universal limits from the published object model (design §1.2). Per-implementation limits
#: are tighter and live on `DecisionCapabilities` (`DecisionRequest.validate_for`).
CHOICE_MAX_OPTIONS = 255


SCORE_MIN_LEVELS = 2


SCORE_MAX_LEVELS = 10


#: Every shipped implementation declares 64 (FR-PROV-27/32), so the cap is universal and
#: checked at construction (TC-PROV-23 j); `validate_for` still applies a tighter declared one.
DECISION_MAX_QUESTIONS = 64


#: FR-PROV-20: a distribution sums to 1 within this tolerance or the response is malformed.
PROBABILITY_SUM_TOLERANCE = 1e-3


DECISION_KEY_SCHEME = b"aeh.prov/decision-key/1"


DECISION_FIXTURE_SCHEMA = "aeh.prov/decision-fixture/1"


def _check_key(key: Any) -> None:
    if not isinstance(key, str) or not _DECISION_KEY.match(key):
        raise DecisionRequestError(
            f"question key {key!r} must match {_DECISION_KEY.pattern} — lowercase letters and "
            f"underscores, no digits (FR-PROV-17)."
        )


def _check_text(value: Any, what: str, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if not isinstance(value, str) or not value.strip():
        raise DecisionRequestError(f"{what} must be a non-empty string, got {value!r}.")


@dataclass(frozen=True)
class ChoiceQuestion:
    """Pick one of 2…255 unordered options. `options` is `((label, description | None), …)`."""

    key: str
    instructions: str
    options: tuple[tuple[str, str | None], ...]

    def __post_init__(self) -> None:
        _check_key(self.key)
        _check_text(self.instructions, f"{self.key}.instructions")
        if not isinstance(self.options, tuple):
            raise DecisionRequestError(f"{self.key}.options must be a tuple of (label, description) pairs.")
        if not 2 <= len(self.options) <= CHOICE_MAX_OPTIONS:
            raise DecisionRequestError(
                f"Choice {self.key!r} has {len(self.options)} options; 2…{CHOICE_MAX_OPTIONS} are allowed.")
        labels = []
        for pair in self.options:
            if not (isinstance(pair, tuple) and len(pair) == 2):
                raise DecisionRequestError(f"{self.key}.options entries must be (label, description) pairs.")
            _check_text(pair[0], f"{self.key} option label")
            _check_text(pair[1], f"{self.key} option description", optional=True)
            labels.append(pair[0])
        if len(set(labels)) != len(labels):
            raise DecisionRequestError(f"Choice {self.key!r} repeats an option label.")

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(label for label, _ in self.options)


@dataclass(frozen=True)
class ScoreQuestion:
    """Place the state on an ordered scale of 2…10 level descriptions, lowest first."""

    key: str
    instructions: str
    levels: tuple[str, ...]

    def __post_init__(self) -> None:
        _check_key(self.key)
        _check_text(self.instructions, f"{self.key}.instructions")
        if not isinstance(self.levels, tuple):
            raise DecisionRequestError(f"{self.key}.levels must be a tuple of level descriptions.")
        if not SCORE_MIN_LEVELS <= len(self.levels) <= SCORE_MAX_LEVELS:
            raise DecisionRequestError(
                f"Score {self.key!r} has {len(self.levels)} levels; "
                f"{SCORE_MIN_LEVELS}…{SCORE_MAX_LEVELS} are allowed.")
        for level in self.levels:
            _check_text(level, f"{self.key} level")


@dataclass(frozen=True)
class NoulQuestion:
    """A yes/no statement; the answer is the probability it is true."""

    key: str
    instructions: str
    when_true: str | None = None
    when_false: str | None = None

    def __post_init__(self) -> None:
        _check_key(self.key)
        _check_text(self.instructions, f"{self.key}.instructions")
        _check_text(self.when_true, f"{self.key}.when_true", optional=True)
        _check_text(self.when_false, f"{self.key}.when_false", optional=True)


DecisionQuestion = ChoiceQuestion | ScoreQuestion | NoulQuestion


@dataclass(frozen=True)
class DecisionCapabilities:
    """What a decision implementation declares about itself (FR-PROV-27, the CT-PROV-04
    posture): declared, never discovered, stable for the run."""

    max_context_tokens: int
    max_choice_options: int
    max_questions: int
    cost_per_input_token: Decimal | None
    deterministic: bool


@dataclass(frozen=True)
class DecisionRequest:
    """The closed, frozen request (FR-PROV-17): a state and an ordered tuple of questions."""

    state: str
    questions: tuple[DecisionQuestion, ...]

    def __post_init__(self) -> None:
        _check_text(self.state, "DecisionRequest.state")
        if not isinstance(self.questions, tuple) or not self.questions:
            raise DecisionRequestError("DecisionRequest.questions must be a non-empty tuple.")
        if len(self.questions) > DECISION_MAX_QUESTIONS:
            raise DecisionRequestError(
                f"{len(self.questions)} questions exceed the {DECISION_MAX_QUESTIONS}-question cap.")
        keys = []
        for question in self.questions:
            if not isinstance(question, (ChoiceQuestion, ScoreQuestion, NoulQuestion)):
                raise DecisionRequestError(
                    f"DecisionRequest.questions holds a {type(question).__name__}; only "
                    f"ChoiceQuestion, ScoreQuestion and NoulQuestion exist (FR-PROV-17).")
            keys.append(question.key)
        if len(set(keys)) != len(keys):
            raise DecisionRequestError(f"DecisionRequest repeats a question key: {keys}.")

    def validate_for(self, capabilities: DecisionCapabilities) -> None:
        """The per-implementation half of FR-PROV-17: question count and Choice width against
        the implementation's declared limits. Called by every `decide` before anything is sent."""
        if len(self.questions) > capabilities.max_questions:
            raise DecisionRequestError(
                f"{len(self.questions)} questions exceed this implementation's "
                f"max_questions={capabilities.max_questions}.")
        for question in self.questions:
            if isinstance(question, ChoiceQuestion) and len(question.options) > capabilities.max_choice_options:
                raise DecisionRequestError(
                    f"Choice {question.key!r} has {len(question.options)} options; this "
                    f"implementation allows {capabilities.max_choice_options}.")


@dataclass(frozen=True)
class ChoiceAnswer:
    choice: str
    probabilities: Mapping[str, float]
    confidence: float
    confidence_source: str


@dataclass(frozen=True)
class ScoreAnswer:
    """`probabilities[i]` is the probability of `levels[i]`. `score` is the probability-weighted
    position; a consumer takes the band from the argmax, never from `score` (ADR-22)."""

    score: float
    probabilities: tuple[float, ...]
    confidence: float
    confidence_source: str


@dataclass(frozen=True)
class NoulAnswer:
    """A Noul's confidence is its `p_true`, Jev's calibrated P(yes) (design 1.8, FR-PROV-19):
    `confidence == p_true` on every returned answer. `confidence_source` is `"reported"` for a
    Jev build and `"derived"` for `openjev-small`; it has no default."""

    p_true: float
    confidence: float
    confidence_source: str


DecisionAnswer = ChoiceAnswer | ScoreAnswer | NoulAnswer


@dataclass(frozen=True)
class Decision:
    """One answered request (FR-PROV-18): exactly one answer per question key, typed as its
    question. `cost` is null on edge-local and fixture (the CT-PROV-03 posture)."""

    answers: Mapping[str, DecisionAnswer]
    tokens_in: int
    tokens_out: int
    latency_ms: int
    resolved_build: str
    cost: Decimal | None
