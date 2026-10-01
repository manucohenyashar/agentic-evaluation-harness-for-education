"""Escalation policy: widening a panel, the random arm, the breaker, and budget admission."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, NamedTuple, Sequence

from .errors import EscalationPlanError, EvenEscalationPlanError
from .settings import (
    ORCH_CRITERION_BREAKER_MIN_N,
    ORCH_CRITERION_BREAKER_RATE,
    ORCH_ESCALATION_BUDGET,
    ORCH_RANDOM_ARM_RATE,
)


def _known_key(value: Any) -> tuple[int, Any]:
    """A sort key that puts missing values last without ever comparing them.

    Present values key ``(0, value)``; absent ones ``(1, None)`` — the first element
    decides before the second is ever compared, so `None` is never ordered against a real
    value and two absentees tie into the next key. The dispatch order uses it for a
    candidate whose criterion the version's maps do not name (a shape the immutable
    package cannot produce): the order stays total and deterministic either way.
    """
    return (0, value) if value is not None else (1, None)


def _dependency_closure(
    graph: Mapping[str, Sequence[str]],
) -> dict[str, frozenset[str]]:
    """The transitive closure of a dependency graph, per criterion.

    Input: criterion -> its direct dependencies (`PackageCatalog.dependency_graph`'s
    shape). Output: criterion -> every criterion it depends on, itself excluded (the
    graph cannot carry a self-edge — `FR-PKG-05` refuses one).

    **Kahn's sweep, honestly iterative**: an indegree pass, then a worklist drained
    from the sources inward — every criterion is closed only after all of its
    dependencies are, so the recursion depth is zero and a deep chain (a criterion per
    link, a thousand long) costs heap records, not call-stack frames. A criterion a
    dependency names but the graph does not (a dangling id, which `M-PKG`'s loader
    refuses but this helper does not trust) contributes itself and closes over
    nothing. The graph is a DAG (`FR-PKG-05` refuses cycles); a violated assumption
    leaves the cycle's members at their reserved empty closure — a bounded incomplete
    answer, not a crash or a hang — and the closure sets themselves are order-
    independent `frozenset`s, so the sweep's emission order cannot leak into results.
    """
    closure: dict[str, frozenset[str]] = {cid: frozenset() for cid in graph}
    indegree = {cid: 0 for cid in graph}
    dependents: dict[str, list[str]] = {cid: [] for cid in graph}
    for cid, deps in graph.items():
        for dep in deps:
            if dep in indegree:  # a dangling dep is not a graph edge to wait on
                indegree[cid] += 1
                dependents[dep].append(cid)
    ready = [cid for cid in graph if indegree[cid] == 0]
    while ready:
        cid = ready.pop()
        closure[cid] = frozenset().union(
            *(  # type: ignore[arg-type]
                {dep} | closure.get(dep, frozenset())
                for dep in graph.get(cid, ())
            )
        )
        for dependent in dependents[cid]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
    return closure


# --- the escalation policy, as pure functions (NFR-ORCH-04) -------------------------------------
#
# The *decision to escalate* is `M-AGG`'s (`FR-AGG-08`, `CT-AGG-08` — this module must not
# import that policy, and imports nothing from it). What IS this module's is the plan the
# decision becomes and the gates the plan passes through: the odd-panel ladder, the
# random-arm draw, the breaker arithmetic. All three are pure functions of observable
# signals and configuration — no model call, no store, no clock — which is what
# `TC-ORCH-32`'s purity assertion evaluates.


#: The namespace of derived escalation judges. A run's panel carries the ladder's first
#: arms (`panel_config_json`); when a widening outruns it — a `holistic` criterion's base
#: panel is already the whole panel — the ladder continues on derived judge identities
#: named by ladder position. The ledger does not resolve builds (`M-CONF`/`M-JUDGE` do,
#: downstream), and a deployment that owns real fifth judges passes them explicitly
#: (`enqueue_escalation`'s `judges`), which is the design's own `judges` parameter.
ESCALATION_ARM_PREFIX = "escalation-arm"


def _extension_arms(
    panel_arms: Sequence[str], prior_judges: Sequence[str], count: int = 2
) -> tuple[str, ...]:
    """The judges an escalation adds when the caller names none, in order.

    The run panel's arms the pair does not already carry come first — panel order is the
    escalation ladder's first arms (`panel_config_json`) — and past them the ladder
    continues on derived identities: ``escalation-arm-<k>`` numbered from the panel's end.
    A derived name a prior rung already put on the panel is skipped, so rung over rung
    (1 → 3 → 5 → …) never re-adds a judge. Deterministic: the same panel and prior produce
    the same additions, which is what makes a retried enqueue content-address the same units.
    """
    additions: list[str] = [arm for arm in panel_arms if arm not in prior_judges]
    position = len(tuple(panel_arms))
    while len(additions) < count:
        position += 1
        name = f"{ESCALATION_ARM_PREFIX}-{position}"
        if name not in prior_judges:
            additions.append(name)
    return tuple(additions[:count])


def _judge_id_of(judge: Any) -> str:
    """A judge's ledger id. A string is used as-is; anything else must be a model reference
    carrying a build id (FR-CONF-03: a judge is identified by its build, never by a friendly name).
    This is the same string `panel_config_json` records and `judge_id` hashes, so added judges have
    the same ids as the original panel's."""
    if isinstance(judge, str):
        return judge
    build_id = getattr(judge, "build_id", None)
    if isinstance(build_id, str) and build_id:
        return build_id
    raise EscalationPlanError(
        f"an escalation's judges are named by build id — a string, or a model ref "
        f"carrying one; got {judge!r}, which names no build identity (FR-CONF-03)."
    )


def escalation_plan(
    prior_judges: Sequence[str],
    *,
    add_judges: Sequence[str] | None = None,
    panel_arms: Sequence[str] = (),
) -> tuple[str, ...]:
    """Build one escalation step: the widened panel, or a refusal with a named error (FR-ORCH-10).

    More detail: `docs/code-notes/orch.md`, section `escalation_policy.py: escalation_plan`.
    """
    prior = tuple(prior_judges)
    if len(prior) == 0:
        raise EscalationPlanError(
            "no judges to escalate from: a criterion with judge_count 0 has no panel "
            "to widen. Enumeration gives every judged criterion its base panel; an "
            "escalation before that is a caller error."
        )
    if len(prior) % 2 == 0:
        raise EvenEscalationPlanError(
            f"the criterion's current panel {prior!r} carries an even judge_count "
            f"({len(prior)}); an even panel is the state the odd-panel rule exists to "
            "prevent (CT-AGG-03) and no escalation plan may be built on top of it — "
            "the panel is corrupt, and widening it would launder the corruption."
        )
    additions = (
        _extension_arms(panel_arms, prior)
        if add_judges is None
        else tuple(add_judges)
    )
    if not additions:
        raise EscalationPlanError(
            "the escalation plan adds no judges: a plan that does not widen the panel "
            "is not an escalation (FR-ORCH-10), and enqueuing it would look like work "
            "while adding nothing."
        )
    if len(set(additions)) != len(additions):
        raise EscalationPlanError(
            f"the escalation plan names the same judge more than once among its "
            f"additions: {additions!r}. One judge, one seat — a doubled seat would let "
            "one verdict outweigh another in the widened panel's aggregation, and an "
            "odd length built on a repeated name hides an even panel of distinct "
            "judges behind it."
        )
    overlap = [judge for judge in additions if judge in prior]
    if overlap:
        raise EscalationPlanError(
            f"the escalation plan re-adds judge(s) already on the panel: {overlap!r}. "
            "One judge, one seat — a doubled seat would let one verdict outweigh "
            "another in the widened panel's aggregation."
        )
    total = len(prior) + len(additions)
    if total % 2 == 0:
        raise EvenEscalationPlanError(
            f"the escalation plan produces an even judge_count ({total}: {len(prior)} "
            f"prior + {len(additions)} added). Escalation goes one judge to three, "
            "never to two (FR-ORCH-10, R48) — an even panel is a tie broken by rule, "
            "which is a coin flip presented as a judgement."
        )
    if total <= len(prior):
        raise EscalationPlanError(
            f"the escalation plan produces a judge_count of {total}, not wider than "
            f"the panel it starts from ({len(prior)})."
        )
    return prior + additions


def _random_arm_key_bytes(key: Any) -> bytes:
    """The bytes hashed for one candidate in the random-arm draw: a string as-is, or a tuple such
    as `(submission_id, criterion_id)` joined with `\x1f`. Deterministic and collision-free for the
    keys this module uses."""
    if isinstance(key, str):
        return key.encode("utf-8")
    if isinstance(key, (tuple, list)):
        return b"\x1f".join(str(part).encode("utf-8") for part in key)
    return repr(key).encode("utf-8")


def random_arm_selection(key: Any, seed: int, rate: float | None = None) -> bool:
    """Whether one candidate is drawn into the random arm (FR-ORCH-11, TC-ORCH-12).

    Pure and **seeded**: the draw is sha256 over the candidate's key and the caller's
    seed read as a uniform integer against the rate, so the same (key, seed) draws the
    same way on every enumeration — `CT-ORCH-02`'s byte-identical enumeration and
    `NFR-ORCH-05`'s determinism survive the arm being in the pass — while across keys
    the draws are uniform, which is what makes the arm's share converge on the rate
    (the 10,000-draw sweep of `TC-ORCH-12`). ``rate`` defaults to the module constant
    `ORCH_RANDOM_ARM_RATE` — the pure function never reads the environment; the
    production path reads the knob at call time and passes the rate explicitly (the
    env seam, `§4.6`). No confidence input, no store, no clock: the arm is independent
    of confidence **by construction** (`R22` — that independence is the point of the
    arm, `FR-STATS-08`), and a rate of 0 disables it honestly.
    """
    if rate is None:
        rate = ORCH_RANDOM_ARM_RATE
    if rate <= 0:
        return False
    digest = hashlib.sha256(
        b"aeh.orch\x1frandom_arm\x1f"
        + _random_arm_key_bytes(key)
        + b"\x1f"
        + str(int(seed)).encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64) < rate


def run_random_arm_seed(run_id: str) -> int:
    """The run's random-arm seed, derived from the run id.

    A run's arm membership must be a property of the RUN (the same cohort re-enumerated
    into a new run re-draws — new run, new sample), and it must be deterministic within
    the run (`CT-ORCH-02`). The run id is the seed's whole input: sha256 under the
    module prefix, read as an integer in the statistical cases' own draw range
    (``rng.randrange(2**31)``).
    """
    digest = hashlib.sha256(b"aeh.orch\x1frun_arm_seed\x1f" + run_id.encode("utf-8"))
    return int.from_bytes(digest.digest()[:8], "big") % (2**31)


def criterion_breaker_tripped(
    escalated: int,
    processed: int,
    *,
    rate: float | None = None,
    min_n: int | None = None,
) -> bool:
    """Whether a criterion's escalation breaker trips (FR-ORCH-13, TC-ORCH-13).

    Pure, the design's own sentence twice over: the breaker evaluates only **at or
    after the window minimum** (`processed >= min_n` — a criterion that escalates 11 of
    its first 10 processed has not met the window yet, and the minimum gates before the
    rate does), and it trips when the criterion escalated for **more than** ``rate`` of
    what it has processed — half of twenty is ten, and ten of twenty does not trip;
    eleven does. Defaults are the module constants; the production path reads the env
    knobs at call time and passes them explicitly (the env seam, `§4.6`).

    The caller chooses what window `escalated`/`processed` count over — the enqueue
    path feeds the criterion's first `min_n` submissions by completion tick, so the
    comparison is "more than half of the first twenty", exactly the design's window.
    """
    if rate is None:
        rate = ORCH_CRITERION_BREAKER_RATE
    if min_n is None:
        min_n = ORCH_CRITERION_BREAKER_MIN_N
    if processed < min_n:
        return False
    return escalated / processed > rate


def validate_escalation_plan(judge_count: int) -> int:
    """Check and normalize one escalation's target panel size (FR-ORCH-10, TC-ORCH-20).

    The declared pure surface of the odd-panel rule: an odd depth is legal and stands
    (3 judges stay 3, 5 stay 5), a **one-judge criterion escalates to three — never to
    two**, and any even count raises `EvenEscalationPlanError` (a two-way tie broken by
    rule is a coin flip presented as a judgement, R48). `escalation_plan` composes this
    rule with the widening arithmetic; this function is the rule alone.
    """
    if judge_count % 2 == 0:
        raise EvenEscalationPlanError(
            f"an escalation plan for judge_count {judge_count} produces an even "
            "panel — an even panel is a tie broken by rule, a coin flip presented "
            "as a judgement (FR-ORCH-10, R48). One judge escalates to three, never "
            "to two."
        )
    return 3 if judge_count == 1 else judge_count


class AdmissionPlan(NamedTuple):
    """Which escalations in one batch are admitted (FR-ORCH-14, TC-ORCH-14).

    `admitted` and `provisional` are tuples of the candidates' keys; the provisional
    half is ordered by expected value, highest first — the order admission resumes in
    when the rate allows — so the remainder is **marked, not dropped**: scrutiny is
    degraded visibly, never silently reduced (R26, `CT-ORCH-16`).
    """

    admitted: tuple
    provisional: tuple


def admit_escalations(
    candidates: Sequence[tuple[Any, float]],
    *,
    escalated: int,
    processed: int,
    budget: float | None = None,
) -> AdmissionPlan:
    """Decide which escalations in one batch fit within the run-wide escalation budget
    (FR-ORCH-14).

    Pure: the caller reads the ledger's observed counts (the escalations and the
    processed results it names) and hands the batch's ``(key, expected_value)``
    candidates; this says which are admitted and which are marked provisional. The
    declared reading, strict like the breaker's "more than half": the budget is
    exceeded when ``escalated / processed`` is **strictly above** it — at-budget
    behaves like below-budget (rationing must not start early; that is the "silently
    reducing scrutiny" failure R26 names) — and above it **nothing further is
    admitted**: every further escalation past a rate already above the budget deepens
    the overrun FR-ORCH-14 forbids. The deferred remainder is the full pending set in
    expected-value order, so admission resumes with the highest-value criteria when
    the rate allows. Full accounting is the invariant: no candidate is dropped, none
    duplicated, none appears on both sides. A window with nothing processed yet has no
    observed rate to exceed — the batch is admitted.
    """
    if budget is None:
        budget = ORCH_ESCALATION_BUDGET
    ordered = tuple(
        key
        for key, _ in sorted(
            candidates,
            key=lambda pair: (-float(pair[1]), str(pair[0])),
        )
    )
    if processed > 0 and escalated / processed > budget:
        return AdmissionPlan((), ordered)
    return AdmissionPlan(ordered, ())
