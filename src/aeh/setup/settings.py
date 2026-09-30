"""Prompt versions, attempt budgets, the confirmation cap and the other setup knobs."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from .errors import SetupError


#: Module observability: every proposal attempt, confirmation, gate refusal and
#: publication is logged with its identifiers (the four seams' stage-level trace).
LOGGER = logging.getLogger("aeh.setup")


#: The version-pinned inventory prompt (`CT-SETUP-14`, `TC-SETUP-22`): changing the
#: wording changes what the model was asked, so the text carries a version and the
#: proposal row records which one produced it. A prompt change is a NEW version string
#: and a new proposal — never an in-place edit of this constant's meaning.
SETUP_PROMPT_TEMPLATE_V = "setup-inventory-v1"


#: The degraded-path attempt budget (`CT-SETUP-12`): a model proposal that fails to
#: parse or validate is re-requested up to this many times, then the proposal is
#: recorded as `needs_manual_entry` — degraded but complete: the teacher enters the
#: questions as corrections and confirms. Env-gated so a slow test box can shrink it.
PROPOSAL_ATTEMPTS_ENV = "HARNESS_SETUP_PROPOSAL_ATTEMPTS"


PROPOSAL_ATTEMPTS_DEFAULT = 3


def _configured_proposal_attempts() -> int:
    """The attempt budget, read at call time — never at import (`M-PKG`'s knob
    doctrine: a test or deployment sets it per operation, not per process load)."""
    raw = os.environ.get(PROPOSAL_ATTEMPTS_ENV)
    if not raw:
        return PROPOSAL_ATTEMPTS_DEFAULT
    try:
        value = int(raw)
    except ValueError as error:
        raise SetupError(
            f"{PROPOSAL_ATTEMPTS_ENV}={raw!r} is not an integer."
        ) from error
    if value < 1:
        raise SetupError(
            f"{PROPOSAL_ATTEMPTS_ENV}={value} is below 1: at least one proposal "
            "attempt is required."
        )
    return value


#: The version-pinned read-back prompt (`NFR-SETUP-03`, `CT-SETUP-14`'s rule carried to
#: the read back): changing the wording changes what the model was asked, which changes
#: every criterion the read back produces from then on — so the text carries a version
#: and the read-back row records which one produced it. A prompt change is a NEW version
#: string, never an in-place edit of this constant's meaning.
SETUP_READBACK_TEMPLATE_V = "setup-readback-v1"


#: The decomposability-classification prompt's pinned version (`#52`, NFR-SETUP-03's
#: rule at the classifier): a change to it changes every classification made afterwards,
#: so it is recorded with the verdicts it produced (`CT-SETUP-14`'s rule, applied to
#: this prompt too).
SETUP_CLASSIFY_TEMPLATE_V = "setup-classify-v1"


#: The dependency-proposal prompt's pinned version (`#52`): the same record-where-used
#: rule — the proposals' plain-language renderings are traceable to the prompt that
#: elicited them.
SETUP_DEPENDENCIES_TEMPLATE_V = "setup-dependencies-v1"


#: The default band-set size (`FR-SETUP-04`): a criterion whose construct carries no
#: partial credit gets two bands — met / not met — derived from the criterion's own
#: text. Configuration §3.6: `SETUP_DEFAULT_BAND_COUNT` (2).
SETUP_DEFAULT_BAND_COUNT = 2


#: The two bands every staged deterministic criterion carries (`FR-SETUP-03`, #53):
#: an mcq question's criterion is atomic with EXACTLY `correct`/`incorrect` — the key
#: decides, so there is no partial credit to model and nothing for the §5.3 table to
#: ask (`CT-SETUP-07`).
SETUP_MCQ_BAND_NAMES: tuple[str, ...] = ("correct", "incorrect")


#: The prefix-budget ceiling's fallback (`FR-SETUP-11`, `FR-CONF-10`, #53): the
#: budget check compares the assembled per-(question, criterion) prefix against
#: `RunConfig.prefix_token_ceiling` — the per-profile value M-CONF derives (2000 on
#: `unified-large`, 1500 otherwise; the `hosted_prefix_token_ceiling` cfg key moves
#: the hosted one, per conf.py's recorded decision that NO separate env key exists
#: for this ceiling, since one would permit `unified-large` with a ceiling of 500).
#: This constant is only the fallback for a service constructed without a resolved
#: run config. The counting seam itself — a real tokenizer behind the same report —
#: is `TC-SETUP-14`'s deferred story; the estimate `_estimate_tokens` makes is
#: documented at that function.
SETUP_PREFIX_TOKEN_CEILING_DEFAULT = 1500


def _prefix_ceiling(run_config: Any) -> int:
    """The ceiling THIS check compares against (`FR-SETUP-11`): the resolved run
    config's per-profile value (`FR-CONF-06`/`-10` derive it from the profile)
    when the service carries one, the fallback default otherwise.

    The config arrives duck-typed — whatever the caller resolved carries
    `prefix_token_ceiling` (aeh.conf's `RunConfig` is the intended shape) — read
    through `Any` deliberately: this module's import graph is the store boundary
    (`aeh.pkg`, `aeh.ingest`, `aeh.prov`) and nothing else (`CT-SETUP-16`'s
    module-graph probe), so M-CONF's type is consumed, never imported."""
    if run_config is not None:
        return int(run_config.prefix_token_ceiling)
    return SETUP_PREFIX_TOKEN_CEILING_DEFAULT


def _estimate_tokens(text: str) -> int:
    """The token estimate behind `check_prefix_budget` (`FR-SETUP-11`, #53).

    Characters divided by four, rounded up — the coarse constant the industry uses
    for English prose, and deliberately NOT a tokenizer call: the exact counting
    seam is `TC-SETUP-14`'s deferred story, and this module's obligation is the
    EVENT (an over-budget prefix is reported before publication, and the
    remediation never touches the reference solution or the criterion text), not
    the exact count. A real tokenizer lands behind the same report; until then the
    estimate's bias is stated here rather than hidden: it under-counts code and
    heavily symbol-dense text and over-counts long runs of short words."""
    if not text:
        return 0
    return -(-len(text) // 4)


#: The magnitude-phrase bar (`FR-SETUP-05`, Configuration §3.6: `SETUP_MAGNITUDE_PHRASES`):
#: a generated band descriptor matching any of these (case-insensitive substring) is
#: REJECTED and RE-GENERATED — the setup-time twin of FR-JUDGE-03 (no numeral in the
#: scoring prompt) and FR-SYNTH-03 (no score claim in narrative): the system keeps
#: magnitude language away from the model at every stage. The bar's other arm, a BARE
#: NUMERAL, is a pattern rather than a phrase and lives in `_NUMERAL_IN_DESCRIPTOR`
#: below; `M-JUDGE` never has to filter a descriptor (`CT-SETUP-06`).
SETUP_MAGNITUDE_PHRASES: tuple[str, ...] = (
    "good", "excellent", "weak", "adequate", "out of",
)


#: The bare-numeral arm of the magnitude bar (`FR-SETUP-05`): any digit in a descriptor
#: is a points scale leaking back into the language the judge sees.
_NUMERAL_IN_DESCRIPTOR = re.compile(r"\d")


#: The evidence-type default (`FR-SETUP-09`): what kind of textual evidence satisfies a
#: criterion the read back produces. The design pins no closed vocabulary — M-EXTRACT's
#: interface example names `textual_span`, the common case of evidence located in the
#: response's own text — so the read back attaches this when the model proposes none,
#: and stores whatever non-empty declaration it does propose.
SETUP_EVIDENCE_TYPE_DEFAULT = "textual_span"


#: The read-back's scoring-model vocabulary. The criterion DDL leaves scoring_model open
#: (its writers are trusted), but the design names exactly two models — `atomic` and
#: `holistic` (FR-SETUP-13, FR-AGG-06) — so the read back proposes within those and a
#: third name in a model reply is a schema-validation failure, re-requested.
SCORING_MODELS: tuple[str, ...] = ("atomic", "atomic_with_gate", "holistic")


# -- #52: the decomposability classification (FR-SETUP-06/-07/-08, §5.3) ------------------

#: The five HLD §5.3 questions, in the order the HLD names them. The classifier asks
#: the model for an ANSWER to each — never for a verdict — and this module's decision
#: table turns the answers into the classification (FR-SETUP-06: the table is the
#: module's, so a scripted verdict cannot pass through the model seam).
FIVE_QUESTIONS: tuple[str, ...] = (
    "completeness", "non_interference", "independence", "additivity", "gates",
)


#: The classification vocabulary (`CT-SETUP-04`): `atomic` (judged in isolation),
#: `atomic_with_gate` (judged in isolation once its gate holds), `holistic` (judged as
#: a whole). The criterion's stored `scoring_model` IS the classification (`FR-SETUP-08`
#: — panel depth and the auto-acceptance ceiling are functions of stored data, so
#: M-ORCH and M-AGG read a number, never a run-time branch).
CLASSIFICATIONS: tuple[str, ...] = ("atomic", "atomic_with_gate", "holistic")


#: The teacher-time cap (`FR-SETUP-07`, NFR-SETUP-01, Configuration §3.6):
#: `SETUP_MAX_CONFIRMATIONS` (6, Assumption (6), R9's budget) — at most this many
#: decomposability confirmations are REQUESTED per package, plus the two blocking
#: screens, and the cap is enforced by THIS module (`CT-SETUP-13`: headlessly, not by
#: the console). Env-gated so a slower pilot box can widen it without a code change;
#: read at import — the tests and the console read the module attribute, so the env
#: must be set before the process starts.
CONFIRMATIONS_ENV = "HARNESS_SETUP_MAX_CONFIRMATIONS"


CONFIRMATIONS_DEFAULT = 6


def _configured_max_confirmations() -> int:
    """The confirmation cap: the design's 6 unless the env widens or narrows it."""
    raw = os.environ.get(CONFIRMATIONS_ENV)
    if not raw:
        return CONFIRMATIONS_DEFAULT
    try:
        value = int(raw)
    except ValueError as error:
        raise SetupError(
            f"{CONFIRMATIONS_ENV}={raw!r} is not an integer."
        ) from error
    if value < 1:
        raise SetupError(
            f"{CONFIRMATIONS_ENV}={value} is below 1: a cap below one confirmation "
            "cannot surface even the first borderline criterion."
        )
    return value


SETUP_MAX_CONFIRMATIONS: int = _configured_max_confirmations()


#: The classify attempt budget (`CT-SETUP-12`'s rule at the classifier): a reply that
#: fails to parse or validate is re-requested up to this many times, then the verdict
#: degrades to the recorded default (`holistic`, surfaced) — degraded but complete.
#: Env-gated, read at CALL time (the knob doctrine).
CLASSIFY_ATTEMPTS_ENV = "HARNESS_SETUP_CLASSIFY_ATTEMPTS"


CLASSIFY_ATTEMPTS_DEFAULT = 3


def _configured_classify_attempts() -> int:
    """The classify attempt budget, read at call time — never at import."""
    raw = os.environ.get(CLASSIFY_ATTEMPTS_ENV)
    if not raw:
        return CLASSIFY_ATTEMPTS_DEFAULT
    try:
        value = int(raw)
    except ValueError as error:
        raise SetupError(
            f"{CLASSIFY_ATTEMPTS_ENV}={raw!r} is not an integer."
        ) from error
    if value < 1:
        raise SetupError(
            f"{CLASSIFY_ATTEMPTS_ENV}={value} is below 1: at least one classify "
            "attempt is required."
        )
    return value


#: The read-back attempt budget (`CT-SETUP-12`'s rule at the read back): a model reply
#: that fails to parse, to validate, or to clear the magnitude bar is re-requested up to
#: this many times, then the read back is recorded as `needs_manual_entry` — degraded
#: but complete. Env-gated, read at CALL time (the knob doctrine: per operation, not
#: per process load).
READBACK_ATTEMPTS_ENV = "HARNESS_SETUP_READBACK_ATTEMPTS"


READBACK_ATTEMPTS_DEFAULT = 3


def _configured_readback_attempts() -> int:
    """The read-back attempt budget, read at call time — never at import."""
    raw = os.environ.get(READBACK_ATTEMPTS_ENV)
    if not raw:
        return READBACK_ATTEMPTS_DEFAULT
    try:
        value = int(raw)
    except ValueError as error:
        raise SetupError(
            f"{READBACK_ATTEMPTS_ENV}={raw!r} is not an integer."
        ) from error
    if value < 1:
        raise SetupError(
            f"{READBACK_ATTEMPTS_ENV}={value} is below 1: at least one read-back "
            "attempt is required."
        )
    return value


def _now() -> str:
    """The confirmation stamp. UTC ISO — the same shape the store's
    `datetime('now')` stamps carry (which are UTC), so one column sorts cleanly."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
