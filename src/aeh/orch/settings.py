"""Leases, attempts, budgets, breakers, dispatch batching and the other knobs, read at call time."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from .errors import WorkLedgerError


#: FR-ORCH-37: the input-token budget one decision pre-screen is estimated at when the run-start
#: cost estimate adds the decision calls. Production default 1,500 (the judge prompt's shared
#: prefix, NFR-JUDGE-01); `HARNESS_ORCH_DECISION_TOKENS_PER_SEAT` adjusts it at call time.
DECISION_TOKENS_PER_SEAT_ENV = "HARNESS_ORCH_DECISION_TOKENS_PER_SEAT"


DECISION_TOKENS_PER_SEAT_DEFAULT = 1500


#: The decision-engine render version (Jev design delta FR-ORCH-36). Owned by `M-JUDGE`'s render;
#: declared here because `panel_config` hashes it and `aeh.judge` already imports this module.
#: Changing the Jev request render changes this string, and so every decision-engine work id.
JUDGE_DECISION_TEMPLATE_V = "judge-decision/1"


# --- environment-gated knobs (CLAUDE.md seam 3) -------------------------------------------------

#: The number of ledger inserts per committed transaction during enumeration. Production
#: default; `HARNESS_ORCH_ENUM_COMMIT_BATCH` adjusts it for a slower test box without a
#: code change. Read at **call** time, so a test can set the variable and call — a value
#: captured at construction would make the knob a lie.
ENUM_COMMIT_BATCH_ENV = "HARNESS_ORCH_ENUM_COMMIT_BATCH"


ENUM_COMMIT_BATCH_DEFAULT = 500


#: The lease TTL in seconds (design §3.7 Configuration: `ORCH_LEASE_SECONDS`, 300).
#: Production default; `HARNESS_ORCH_LEASE_SECONDS` adjusts it at **call** time — the
#: seam a slower test box (or a real-elapsed expiry case) sets instead of sleeping five
#: minutes. A lease this short would be a production incident, which is why the knob
#: refuses to be set implicitly: it only ever comes from the environment or this default.
ORCH_LEASE_SECONDS = 300


LEASE_SECONDS_ENV = "HARNESS_ORCH_LEASE_SECONDS"


#: The attempts a unit may fail before it quarantines (design §3.7 Configuration:
#: `ORCH_MAX_ATTEMPTS`, 3 — the state model's "attempts = 3"). Production default;
#: `HARNESS_ORCH_MAX_ATTEMPTS` adjusts it at call time. The taxonomy is honest at any
#: value: fewer attempts quarantine sooner and more visibly, never silently.
ORCH_MAX_ATTEMPTS = 3


MAX_ATTEMPTS_ENV = "HARNESS_ORCH_MAX_ATTEMPTS"


#: The random-arm sample rate (`FR-ORCH-11`, design §3.7 Configuration: `ORCH_RANDOM_ARM_RATE`,
#: 0.07 — the HLD's 5–10% band's stated Assumption). The arm measures the routing policy
#: itself (`FR-STATS-08`), so it draws independently of confidence and is **never**
#: suppressed by the escalation budget or a breaker (`CT-ORCH-15`) — its knob tunes the
#: sample size, nothing gates it. Production default; `HARNESS_ORCH_RANDOM_ARM_RATE`
#: adjusts it at **call** time. A rate of 0 disables the arm honestly (a test or a
#: deployment that does not want the compute spends none); a rate above 1 is refused.
ORCH_RANDOM_ARM_RATE = 0.07


RANDOM_ARM_RATE_ENV = "HARNESS_ORCH_RANDOM_ARM_RATE"


#: The run-wide escalation budget (`FR-ORCH-14`, design §3.7 Configuration:
#: `ORCH_ESCALATION_BUDGET`, 0.30): the share of processed results that may escalate
#: before further requests are admitted only in expected-value order, the remainder
#: queued and marked provisional. Production default; `HARNESS_ORCH_ESCALATION_BUDGET`
#: adjusts it at **call** time. The rate is never silently reduced by this knob: over
#: budget means rationed in the open (`CT-ORCH-16`), never refused quietly.
ORCH_ESCALATION_BUDGET = 0.30


# --- #370 (`FR-ORCH-32`): the five run alerts ---------------------------------------------
#
# §3.7 names five conditions an operator must hear about. They were design text with no
# surface carrying them, so `TC-ORCH-36` was written ahead against an invented name. This
# is that surface: ONE pure function over already-gathered state, which is what lets each
# condition be breached independently in a test and what keeps the rules out of the
# dispatch loop, where they would only be reachable by running a whole pass.

#: The fraction of the ceiling at which spend becomes an alert, BEFORE the pause at the
#: ceiling itself (`FR-ORCH-15`'s early form — "within 10% of ceiling"). A knob because
#: a ceiling's useful warning distance depends on how fast the run burns it.
COST_WARNING_FRACTION_DEFAULT = 0.9


COST_WARNING_FRACTION_ENV = "HARNESS_ORCH_COST_WARNING_FRACTION"


#: Cache collapse is RISK-23's ONLY detection path: nothing errors, throughput just dies.
#: Three guards, because a bare "below average" would cry wolf on every ordinary dip:
#:   * `_SIGMA` — how many standard deviations below the run history counts as a break
#:     rather than noise;
#:   * `_FLOOR` — an absolute floor the rate must ALSO be under, so a perfectly steady
#:     history (zero variance) does not make a 1% dip a three-sigma event;
#:   * `_MIN_HISTORY` — the fewest prior runs that make a mean meaningful at all. Below
#:     it there is no alert, because two runs are not a baseline (`CT-STATS-09`'s reading
#:     of "no data is not a zero", applied to a threshold instead of a rate).
CACHE_COLLAPSE_SIGMA_DEFAULT = 3.0


CACHE_COLLAPSE_SIGMA_ENV = "HARNESS_ORCH_CACHE_COLLAPSE_SIGMA"


CACHE_COLLAPSE_FLOOR_DEFAULT = 0.5


CACHE_COLLAPSE_FLOOR_ENV = "HARNESS_ORCH_CACHE_COLLAPSE_FLOOR"


CACHE_COLLAPSE_MIN_HISTORY_DEFAULT = 3


CACHE_COLLAPSE_MIN_HISTORY_ENV = "HARNESS_ORCH_CACHE_COLLAPSE_MIN_HISTORY"


ESCALATION_BUDGET_ENV = "HARNESS_ORCH_ESCALATION_BUDGET"


#: The criterion circuit breaker's rate (`FR-ORCH-13`, design §3.7 Configuration:
#: `ORCH_CRITERION_BREAKER_RATE`, 0.50): a criterion escalating for **more than** this
#: share of the first `ORCH_CRITERION_BREAKER_MIN_N` submissions processed trips the
#: breaker — escalation halts for it, it is marked un-gradeable by panel, and the
#: remainder scores single-judge provisional. Production default;
#: `HARNESS_ORCH_CRITERION_BREAKER_RATE` adjusts it at **call** time.
ORCH_CRITERION_BREAKER_RATE = 0.50


CRITERION_BREAKER_RATE_ENV = "HARNESS_ORCH_CRITERION_BREAKER_RATE"


#: The criterion breaker's window (`FR-ORCH-13`, design §3.7 Configuration:
#: `ORCH_CRITERION_BREAKER_MIN_N`, 20 — the HLD's "first 20–30" band's floor, the stated
#: Assumption): the breaker evaluates only once at least this many submissions have been
#: processed for the criterion. Production default;
#: `HARNESS_ORCH_CRITERION_BREAKER_MIN_N` adjusts it at **call** time.
ORCH_CRITERION_BREAKER_MIN_N = 20


CRITERION_BREAKER_MIN_N_ENV = "HARNESS_ORCH_CRITERION_BREAKER_MIN_N"


#: The extract/deterministic rows one dispatch pass completes directly (`#62`): their
#: handling is the ledger transition — the extraction payload is `M-EXTRACT`'s — and
#: scoring gates on the transition, so the pass completes them to unlock the judged
#: batch. Bounded, not open-ended: a 40,000-unit walk in one pass is exactly the
#: unbounded dispatch the concurrency story exists to prevent. Production default;
#: `HARNESS_ORCH_DISPATCH_WALK_BATCH` adjusts it for a slower test box at call time.
DISPATCH_WALK_BATCH_ENV = "HARNESS_ORCH_DISPATCH_WALK_BATCH"


DISPATCH_WALK_BATCH_DEFAULT = 4096


#: The divisor the backpressure clamp applies to the governor's cap while M-STORE's
#: `backpressure_active` level is ON (`FR-ORCH-21`, `CT-STORE-06`): the pass runs at
#: `max(cap // divisor, 1)`. The clamp is sensed per pass and never persists — a
#: reduction that never recovers is one slow store throttling a run forever. Production
#: default 4; `HARNESS_ORCH_BACKPRESSURE_DIVISOR` adjusts it at call time.
BACKPRESSURE_DIVISOR_ENV = "HARNESS_ORCH_BACKPRESSURE_DIVISOR"


BACKPRESSURE_DIVISOR_DEFAULT = 4


#: The divisor the governor applies to the cap after a pass in which any model call came
#: back rate-limited or OOM (`FR-ORCH-21`'s reduce; §9.13's back-off). Floor 1 — the
#: dispatch never stops on the signal alone, it narrows. Production default 2 (halve);
#: `HARNESS_ORCH_CONCURRENCY_REDUCTION` adjusts it at call time.
CONCURRENCY_REDUCTION_ENV = "HARNESS_ORCH_CONCURRENCY_REDUCTION"


CONCURRENCY_REDUCTION_DEFAULT = 2


#: The cumulative OOM count a judge reaches before the governor drops it from the
#: panel (§9.11's "drop to a smaller panel", RES-13): the reduced panel is written to
#: the run row's `panel_config` as a strict subset, never below one judge. Production
#: default 2; `HARNESS_ORCH_OOM_DROP_THRESHOLD` adjusts it at call time.
OOM_DROP_THRESHOLD_ENV = "HARNESS_ORCH_OOM_DROP_THRESHOLD"


OOM_DROP_THRESHOLD_DEFAULT = 2


#: The `backend_profile` value that carries model residency (`FR-ORCH-19`): weights
#: loaded one model at a time, so the dispatcher keeps one judge resident per run. A
#: hosted backend holds no weights and batches across judges freely.
BACKEND_EDGE_LOCAL = "edge-local"


#: The worker identity the dispatch loop leases under (`#62`): the dispatch pass is a
#: lease holder like any worker — at-least-once, sweepable — so its in-flight batch is
#: visible on the ledger as exactly what it is, and an interrupted pass's leases are
#: the sweeper's ordinary reclaim, never a special case.
DISPATCH_OWNER = "orchestrator-dispatch"


def _env_int(name: str, default: int) -> int:
    """One integer setting from the environment, read each call.

    Invalid and negative values refuse rather than fall back to the default: a typo in an
    operator's override silently taking the production value is the phantom-bug shape the
    seam exists to prevent.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise WorkLedgerError(f"{name}={raw!r} is not an integer") from exc
    if value <= 0:
        raise WorkLedgerError(f"{name}={value} must be positive")
    return value


def _env_float(name: str, default: float, *, low: float, high: float) -> float:
    """One decimal setting from the environment, read each call and checked against its range.

    The same refusal posture as `_env_int`: a typo'd override silently taking the
    production value is the phantom-bug shape the seam exists to prevent, so an
    unparseable value raises. Rates are bounded — a share outside ``[low, high]`` is
    not a stricter policy, it is a misconfiguration, and it refuses rather than clamps
    (a clamped 7% becomes a silent 100% escalation rate; the clamp would BE the bug).
    Zero is a legal low bound: the random arm may honestly be disabled by rate 0.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise WorkLedgerError(f"{name}={raw!r} is not a number") from exc
    if not low <= value <= high:
        raise WorkLedgerError(
            f"{name}={value} is outside its allowed range [{low}, {high}]"
        )
    return value


def _now() -> str:
    """The current time in UTC ISO-8601; the only clock read the ledger writes."""
    return datetime.now(timezone.utc).isoformat()


def _elapsed_seconds_since(timestamp: str | None) -> float:
    """Seconds since a stored timestamp, or 0.0 if it cannot be read.

    The report-only path's elapsed anchor (`#62`): a poll with no dispatch state has
    no monotonic start of its own, so the run's own `started_at` is the throughput
    window the estimate extrapolates from. A missing or unparseable timestamp is no
    observed window — 0.0, never an infinity extrapolated from nothing (the same
    posture `estimated_completion_seconds` takes).
    """
    if not timestamp:
        return 0.0
    try:
        started = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return 0.0
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return max((datetime.now(timezone.utc) - started).total_seconds(), 0.0)
