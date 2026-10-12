"""TC-E2E-02 — The overnight run: 350 submissions in, 341 finalized grades out, zero
teacher action at any point.

The second of the three end-to-end journeys (TS-51, issue #144; design §4.2.2, test plan
§6.2). Rung 4 — the ASSEMBLED system, on the shared world module
(`tests.support.e2e_world`, whose disclosures are this journey's disclosures), driven
through the composed pipeline (`tests.support.composed_synth`, whose disclosures are the
re-base's): real store across the full migration chain, real gateway ingesting 350
four-page PDFs through the real sanitizer and rasterizer, real M-PKG catalog and
publication, real orchestrator, real deterministic evaluator, real extraction workers
(second family included), real integrity gate over real ledger rows, real aggregation
and escalation through the composed hook, real scoring workers, real synthesis worker,
real grade pass. No doubles at any module boundary; the only double anywhere is the model
boundary — the shipped `RecordedFixtureProvider` in its capture shape (`CaptureProvider`,
the F-DEV-PIPE precedent): the boundary answers a first sight of a request by composing it
from the corpus's own declarations and records it through the shipped
`record()`/request-key machinery, and every later identical request replays from the
recording — `CT-PROV-10`'s only egress.

**The drive is `run_to_completion`** (TS-98's re-base, issue #392; §5.0's reconciliation
row): the overnight run is the composed drive over F-SYNTH, and `recover` is its restart.
The hand-written aggregation walk is gone from this journey — not kept as a fallback —
and with it the stand-in escalation inputs: the composed hook reads its baseline from the
run's package (`FR-PIPE-15`), so the world records the design's Assumption distribution
onto the published version through the shipped `record_validation_baseline` route
(`composed_synth`'s disclosure), and reads no aggregation configuration at all
(`CT-AGG-01`: the policy takes its configuration from its caller, and the composed hook
passes none — the journey's figures are stated against the shipped policy).

**Happy path** (§4.2.2, in order): 350 submissions ingest (9 quarantine); the run starts
with the backend fixed; units enumerate and a cost estimate is shown before any dispatch;
the composed drive runs the deterministic evaluation first, then dispatch passes with the
integrity gate and the aggregation/escalation hook firing in-transaction, escalations
widening panels through the real ladder; synthesis runs L1 then L2; the run completes and
every grade finalizes with no teacher action at any point. **Oracle**: 341 grades exist,
coverage is recorded per grade, provisional grades are labelled, CT-PIPE-02's invariant
holds (no `done` unit without its payload row), and the whole journey is compared against
a committed baseline result set.

**The baseline** (fixtures/baselines/TC-E2E-02/result-set.json) freezes the full
350-submission result set the assembled system produced — per submission: the ingest
status with its per-gate record, the grade with its five coverage counters, every
criterion score row, and the narrative set. §6.9's discipline applies even though the
six-entry registry does not name a `TC-E2E-*` row (the registry's table is §6.9's own
and pinned by its drift test): the producing tier is the journey's own
`RecordedFixtureProvider` — request-keyed, compose-then-record — so no live backend's
wording can move it, and the governance is inline here. Reviewer: the overnight run's
owner. Grounds for accepting a diff: a package-corpus bump or a declared world-shape
change — **never** "the model changed its mind"; a diff in a band, a points figure, a
routing or a coverage counter is a defect, not a baseline update. There is deliberately
no regenerate helper here: the first capture was run, inspected and committed in the PR
that carried it. Nondeterministic identifiers are normalized out on purpose (submission
and version ids are minted per build), so the baseline freezes what the system PRODUCED,
and the identifier shapes are asserted separately; timestamps are excluded and narrative
prose carries digests, because the baseline's business is what was produced, not the
scripted wording.

**Variants** (each a separate execution at reduced scale, compared against an in-test
control run at the same scale — the control is the composed drive, and `recover` is the
restart in both):

(a) **The kill at a seeded random point + `recover`** (RES-04..07): the composed drive
    is cut after one dispatch pass (the run mid-ledger), and then — the exact injury a
    SIGKILLed worker leaves — `cut` units on the drawn leg are LEASED by a worker that
    dies before completing them (the hand drive's cut used to leave the same state as the
    side effect of its batch window; the composed drive has no leg to stop mid-flight, so
    the injury is made directly through the real lease API). The world reattaches on the
    same directories, `recover` reclaims the abandoned leases and resumes the run
    (`FR-PIPE-07`), and the composed drive continues to the sanctioned closer. The
    resumed result set equals the uninterrupted control's: a restart replays, it never
    recomputes.
(b) **Provider unavailable mid-run → pause on the same backend → resume**
    (`FR-ORCH-16`, `CT-ORCH-12`): the boundary raises `ProviderUnavailableError` from its
    first call, the composed pipeline absorbs it and pauses the run with the sensed cause
    (`FR-ORCH-30` — the structured `RunResult`, `FR-PIPE-01`), the run row reads paused
    with its reason and with `provider_config`/`panel_config` untouched, the backend
    recovers, the explicit `resume()` un-pauses, `recover` reclaims anything the window
    caught, and the result set equals the control's. (The hand drive surfaced the error
    by raising out of its own leg; the composed drive surfaces it as the stored status —
    the same sensed cause, the sanctioned route.)
(c) **A criterion trips the escalation breaker** (`FR-ORCH-13`, `CT-ORCH-16`): the
    breaker's knobs ride the world's env seam (`composed_synth`'s disclosure — the
    composed hook reads the knob at call time), at journey-2's variant values; a
    criterion escalating for more than the rate's share of its first window trips it,
    escalation halts for that criterion (`halted_by_breaker`), the refused cells are
    re-aggregated with `breaker_tripped=True` inside the hook's own transaction — routed
    provisional, state `ungradeable_by_panel`, the panel's own figure standing (three
    judges where the halt refused the widening, five where a widening had already landed)
    — the mark surfaces in the rollup findings with the affected-student count, and the
    run still completes with every admitted grade finalized.

Disclosed shape: the world's base panel is three judges, so a breaker-marked cell keeps
a three-judge figure standing where the halt refused its first widening — the design's
"remainder single-judge provisional" phrasing is that mark on a one-judge base panel;
here the halt refuses the widening, not the judgement already made, and the precedence
(breaker over panel size) is what the variant pins.
"""

from __future__ import annotations

import json
import os
import random
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from aeh.grade import rollup_findings
from aeh.orch import LEASE_SECONDS_ENV
from aeh.pipeline import recover
from aeh.prov import ProviderUnavailableError
from tests.support.composed_synth import ComposedSynthWorld
from tests.support.e2e_world import SynthWorld

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

ISSUE = "#144"

#: The variants' reduced scale: enough submissions for the escalation ladder and the
#: breaker's window to be real (the breaker variant pins the window minimum at 4),
#: small enough that a variant plus its control is minutes.
VARIANT_SCALE = 24

#: The kill variant's seeded draw range: (leg, units the dead worker holds). The seed
#: makes the random point reproducible; the draw is over the legs the cut's ledger can
#: actually claim on (`_draw_kill_point` — a drained leg claims nothing, a score leg
#: whose pairs' extractions are still not done is gated out of the claim, and a kill
#: where nothing can be leased would be no injury); both judged legs are in the pool.
KILL_POINTS = (
    ("extract", 9),
    ("extract", 40),
    ("score", 25),
    ("score", 121),
)

#: The variant-(c) breaker knobs, riding the world's env seam (the composed hook reads
#: them at call time). Rate 0.50 is the shipped production value; the window minimum is
#: pinned below the shipped 20 so the reduced scale's own first four completions are the
#: window.
BREAKER_RATE = "0.50"
BREAKER_MIN_N = "4"


class _BreakerWorld(ComposedSynthWorld):
    """Variant (c)'s world: the breaker's knobs through the env seam."""

    breaker_rate = BREAKER_RATE
    breaker_min_n = BREAKER_MIN_N


class _OutageBoundary:
    """The variant-(b) boundary: `complete` raises while the outage window is open;
    everything else forwards to the world's real boundary."""

    def __init__(self, inner: Any, world: "_OutageWorld") -> None:
        self._inner = inner
        self._world = world

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        if self._world._outage_open:
            raise ProviderUnavailableError(
                "the journey's provider is unavailable (injected)")
        return self._inner.complete(prompt, model_ref, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _OutageWorld(ComposedSynthWorld):
    """Variant (b)'s world: an injected unavailability window on the model boundary."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._outage_open = False

    def set_unavailable(self, flag: bool = True) -> None:
        """Open or close the injected unavailability window."""
        self._outage_open = bool(flag)

    def drive(self, **overrides: Any) -> Any:
        inner = self.provider
        self.provider = _OutageBoundary(inner, self)
        try:
            return super().drive(**overrides)
        finally:
            self.provider = inner


# --- the drive ------------------------------------------------------------------------------

def _run_row(world: SynthWorld) -> dict:
    """The run row's operator surface: lifecycle, estimate, spend, pause reason, and
    the two frozen backend snapshots."""
    rows = world.handle.query(
        "SELECT status, cost_estimate, cost_spend, pause_reason, provider_config, "
        "panel_config FROM run WHERE run_id = :r", r=world.run_id,
    )
    assert rows, f"fixture bug: run {world.run_id} has no run row"
    return rows[0]


def _count(world: SynthWorld, sql: str, **params) -> int:
    return int(world.handle.query(f"SELECT COUNT(*) AS n FROM ({sql})", **params)[0]["n"])


def _leased(world: SynthWorld) -> int:
    """Units the drive currently holds leases on - the kill variant's injury."""
    return _count(world, "SELECT work_id FROM work_unit WHERE run_id = :r "
                         "AND status = 'leased'", r=world.run_id)


def _draw_kill_point(world: SynthWorld, rng: random.Random) -> tuple[str, int]:
    """The kill variant's seeded draw: one of the seeded points whose leg can actually
    claim at the cut. Two ways a leg with pending rows can still claim nothing:
    a leg the first pass has already drained has nothing left to lease, and a score
    unit whose pair's extraction is not done is gated out of the claim even though
    its row reads pending (`select_not_done_extracts` — the Sweep 2 gate,
    `src/aeh/orch/statements.py`: a score unit is claimable only when neither its own
    criterion's extraction nor a dependency's is pending, leased or quarantined).
    An empty claim against a run with rows is a true empty (`leasing.py`), so the
    draw runs over the points that can leave the dead worker's batch behind at all —
    the guard on `_leased` after the injury stays the arbiter."""
    gated = {(row["submission_id"], row["criterion_id"]) for row in world.handle.query(
        "SELECT submission_id, criterion_id FROM work_unit WHERE run_id = :r "
        "AND stage = 'extract' AND status != 'done'", r=world.run_id)}
    claimable = {row["stage"]: int(row["n"]) for row in world.handle.query(
        "SELECT stage, COUNT(*) AS n FROM work_unit w WHERE run_id = :r "
        "AND status = 'pending' AND (stage != 'score' OR NOT EXISTS "
        "(SELECT 1 FROM work_unit e WHERE e.run_id = w.run_id AND e.stage = 'extract' "
        "AND e.status != 'done' AND e.submission_id = w.submission_id "
        "AND e.criterion_id = w.criterion_id)) GROUP BY stage", r=world.run_id)}
    pending = {row["stage"]: int(row["n"]) for row in world.handle.query(
        "SELECT stage, COUNT(*) AS n FROM work_unit WHERE run_id = :r "
        "AND status = 'pending' GROUP BY stage", r=world.run_id)}
    candidates = [(leg, cut) for leg, cut in KILL_POINTS if claimable.get(leg, 0) > 0]
    assert candidates, (
        f"TC-E2E-02 (a): no seeded kill leg can claim at the cut (claimable by stage: "
        f"{claimable}; pending by stage: {pending}; gated pairs: {len(gated)}) - the "
        f"one-pass cut left no leaseable work to injure"
    )
    return rng.choice(candidates)


def _orphan_counts(world: SynthWorld) -> dict[str, int]:
    """`CT-PIPE-02`'s three invariant queries: done units with no payload row, per
    stage (the composition tests' own queries, read over this journey's run)."""
    queries = {
        "extract": ("SELECT work_id FROM work_unit WHERE run_id = :r AND stage = 'extract' "
                    "AND status = 'done' AND NOT EXISTS (SELECT 1 FROM evidence e WHERE "
                    "e.work_id = work_unit.work_id)"),
        "score": ("SELECT work_id FROM work_unit WHERE run_id = :r AND stage = 'score' "
                  "AND status = 'done' AND NOT EXISTS (SELECT 1 FROM verdict v WHERE "
                  "v.work_id = work_unit.work_id)"),
        "deterministic": ("SELECT work_id FROM work_unit WHERE run_id = :r AND stage = "
                          "'deterministic' AND status = 'done' AND NOT EXISTS (SELECT 1 "
                          "FROM criterion_score s WHERE s.run_id = work_unit.run_id AND "
                          "s.submission_id = work_unit.submission_id AND "
                          "s.criterion_id = work_unit.criterion_id)"),
    }
    return {stage: _count(world, sql, r=world.run_id) for stage, sql in queries.items()}


def _assert_matches_baseline(repo_root: Path, result_set: dict) -> None:
    """Compare the journey's result set against its committed baseline, with §6.9's
    governance in the failure message — journey-1's manifest shape."""
    baseline_path = repo_root / "fixtures" / "baselines" / "TC-E2E-02" / "result-set.json"
    if os.environ.get("AEH_E2E_CAPTURE_BASELINE"):
        # The deliberate-freeze act itself, env-guarded so an ordinary run can
        # never rewrite the baseline as a side effect: the capture run's output
        # is inspected and committed with the reviewer before it becomes the
        # journey's oracle, and the env var is unset in every other context.
        dest = baseline_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            json.dumps(result_set, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"\nTC-E2E-02 BASELINE CAPTURED -> {dest}")
        return
    assert baseline_path.exists(), (
        "TC-E2E-02: no committed baseline at fixtures/baselines/TC-E2E-02/result-set.json. "
        "The 350-submission result set is the journey's whole output; freezing it is a "
        "deliberate act (run the journey, inspect what it emitted, commit it with the "
        f"reviewer — {ISSUE}'s owner) - never a regenerate-until-green keypress."
    )
    golden = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert result_set == golden, (
        "TC-E2E-02: the assembled system's result set no longer matches its committed "
        "baseline.\n\nbaseline: fixtures/baselines/TC-E2E-02/result-set.json\n"
        "  reviewer: the overnight run's owner\n"
        "  grounds for accepting a diff: a package-corpus bump or a declared "
        "world-shape change; never 'the model changed its mind' — a diff in a band, a "
        "points figure, a routing or a coverage counter is a defect, not a baseline "
        "update (test plan §6.9's discipline)"
    )


# --- TC-E2E-02: the happy path --------------------------------------------------------------

def test_tc_e2e_02_overnight_run_full_cohort_finalizes_without_teacher_action(
    tmp_data_dir, tmp_path, monkeypatch, repo_root,
):
    """`TC-E2E-02` happy path at the full scale: the whole §4.2.2 block in order, the
    341-final / 9-quarantine oracle, coverage per grade, provisional labels, CT-PIPE-02's
    invariant, and the whole journey against the committed baseline."""
    world = ComposedSynthWorld(tmp_data_dir, tmp_path / "fixtures", n_submissions=350,
                               monkeypatch=monkeypatch)
    assert len(world.cohort) == 350
    assert len(world.quarantined_ids()) == 9, (
        "TC-E2E-02: the quarantine population is not the oracle's nine identity-gate "
        "refusals"
    )
    assert len(world.admitted_ids()) == 341

    # The run starts with the backend fixed: the run row freezes the resolved config.
    world.build_run()
    world.start_run()
    row = _run_row(world)
    assert row["status"] == "running"
    # Units enumerate and a cost estimate is shown BEFORE any dispatch (FR-ORCH-15).
    enumerated = _count(world, "SELECT work_id FROM work_unit WHERE run_id = :r",
                        r=world.run_id)
    assert row["cost_estimate"] is not None, (
        "TC-E2E-02: the run row carries no estimate after start - FR-ORCH-15 displays "
        "the figure before a single unit is leased, and a fabricated zero would read "
        "as a measured price"
    )
    assert Decimal(row["cost_estimate"]) == Decimal("0.001") * enumerated, (
        "TC-E2E-02: the estimate is not the provider seam's per-unit figure summed "
        "over the enumerated units"
    )

    # The composed drive: the deterministic evaluation first (Sweep 1's topological
    # order is the driver's own structure - its trace is the run's first), then the
    # dispatch passes with the integrity gate and the aggregation hook firing
    # in-transaction, escalations widening panels, synthesis, grading.
    result = world.drive()
    traces = [trace.stage for trace in result.stages]
    assert traces and traces[0] == "deterministic", (
        f"TC-E2E-02: the drive's stage traces run {traces[:4]} - Sweep 1's order is "
        "topological, the deterministic leg first (FR-ORCH-08)"
    )
    assert _count(world, "SELECT work_id FROM work_unit WHERE run_id = :r AND "
                         "stage = 'deterministic' AND status != 'done'",
                  r=world.run_id) == 0, (
        "TC-E2E-02: the deterministic leg left units un-done - the composed driver "
        "evaluates the cohort before a single judged unit is struck"
    )
    # The escalation ladder widened panels: the composed hook's escalations are the
    # durable judge_count on the widened cells (the walk's enqueue count was its own
    # bookkeeping; the composition's is the ledger's).
    widened = _count(world, "SELECT submission_id FROM criterion_score WHERE "
                            "run_id = :r AND judge_count > 3", r=world.run_id)
    assert widened > 0, (
        "TC-E2E-02: no cell's panel was widened - the interior-band limb is this "
        "cohort's honest escalation share, and the composed hook enqueues the widening "
        "in-transaction"
    )

    assert _run_row(world)["status"] == "complete", (
        "TC-E2E-02: the run did not complete - the sanctioned closer fires only with "
        "zero open units underneath it"
    )
    assert _orphan_counts(world) == {"extract": 0, "score": 0, "deterministic": 0}, (
        f"TC-E2E-02: a done unit lost its payload row ({_orphan_counts(world)}) - "
        "CT-PIPE-02's invariant holds over the whole run, fault or no fault"
    )

    # Oracle: 341 grades exist, every one final, with coverage recorded and the
    # provisional criteria labelled; the nine refusals ledger as incomplete.
    result_set = world.result_set()
    submissions = result_set["submissions"]
    assert len(submissions) == 350
    finals = [s for s in submissions if s["grade"] and s["grade"]["state"] == "final"]
    incomplete = [s for s in submissions if s["grade"] and s["grade"]["state"] != "final"]
    assert len(finals) == 341, (
        f"TC-E2E-02: {len(finals)} finalized grades; the overnight oracle is 341 - "
        "every admitted submission finalizes with no teacher action at any point"
    )
    assert len(incomplete) == 9 and all(s["quarantined"] for s in incomplete), (
        "TC-E2E-02: the non-final grades are not exactly the quarantines"
    )
    for row in incomplete:
        assert row["grade"]["criteria_missing"] == len(world.open_ids), (
            "TC-E2E-02: a quarantined submission's grade must ledger its twelve open "
            "criteria as missing - absence awaiting re-ingestion, never a zero"
        )
        assert row["grade"]["criteria_auto"] == len(world.mcq_ids), (
            "TC-E2E-02: a quarantined submission keeps its deterministic rows - M-DET "
            "scores every submission's mcq criteria, quarantine included"
        )
        assert row["narratives"] == [], (
            "TC-E2E-02: a quarantined submission produced narratives - synthesis reads "
            "the admitted population only"
        )
    assert labelled_provisional_count(finals) > 0, (
        "TC-E2E-02: no grade labels provisional criteria - the escalated panels' "
        "figures must be labelled on the grade that carries them (coverage is "
        "recorded per grade), never folded silently into the acceptance"
    )
    for row in finals:
        counters = row["grade"]
        assert counters["criteria_total"] == 15, (
            "TC-E2E-02: a final grade's coverage does not span the package's fifteen "
            "criteria - the five-counter record is FR-GRADE-04's per-grade record"
        )
        assert (counters["criteria_auto"] + counters["criteria_reviewed"]
                + counters["criteria_provisional"] + counters["criteria_missing"]) == 15
    # Deterministic criteria scored by lookup: judge_count 0 on every mcq row, and a
    # quarantined submission holds exactly those three rows.
    for row in submissions:
        mcq = [score for score in row["scores"] if score[0] in world.mcq_ids]
        assert all(score[3] == 0 for score in mcq), (
            "TC-E2E-02: an mcq row carries a judge count - deterministic criteria are "
            "scored by lookup, never by a panel"
        )
    _assert_matches_baseline(repo_root, result_set)


def labelled_provisional_count(submissions: list[dict]) -> int:
    return sum(1 for s in submissions
               if s["grade"] and s["grade"]["criteria_provisional"] > 0)


# --- TC-E2E-02 variant (a): the kill at a seeded random point, then recover -----------------

def test_tc_e2e_02_sigkill_and_recover_reproduces_the_control(
    tmp_data_dir, tmp_path, monkeypatch, repo_root,
):
    """`TC-E2E-02` variant (a) (RES-04..07): a seeded random-point kill mid-run, the
    world reattached on the same directories, `recover` reclaiming the abandoned leases
    and resuming the run, the composed drive closing - and the resumed result set equals
    the uninterrupted control's at the same scale."""
    control = ComposedSynthWorld(tmp_data_dir / "control", tmp_path / "fixtures",
                                 n_submissions=VARIANT_SCALE, monkeypatch=monkeypatch)
    control.build_run()
    control.start_run()
    assert control.drive().status == "complete"
    expected = control.result_set()
    assert any(s["quarantined"] for s in expected["submissions"]), (
        "precondition: the variant's scale holds a quarantine, as the overnight does"
    )

    world = ComposedSynthWorld(tmp_data_dir, tmp_path / "fixtures" / "kill",
                               n_submissions=VARIANT_SCALE, monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    # One dispatch pass, so the run is mid-ledger at the kill - the drive is cut
    # running, not before it started.
    assert world.drive(max_passes=1).status == "running"
    leg, cut = _draw_kill_point(world, random.Random(14402))
    # The injury: units leased by a worker that dies before completing them - the
    # exact ledger state a SIGKILLed worker leaves (the hand drive's cut left the same
    # state as the side effect of its batch window; the composed drive has no leg to
    # stop mid-flight, so the injury is made through the real lease API). The lease
    # expiry lives on the store's monotonic lease clock (`FR-STORE-11`), so the knob
    # shortens the TTL to a second and the dead worker's batch is already expired when
    # recover's sweep arrives - TC-PIPE-11's pattern. The knob rides only the injury:
    # the composed drive's own leases keep the production TTL on both sides of it.
    monkeypatch.setenv(LEASE_SECONDS_ENV, "1")
    world.orchestrator.lease("w-overnight-kill", leg, cut)
    time.sleep(1.2)
    assert _leased(world) > 0, (
        "TC-E2E-02 (a): the kill left no leased unit - the kill exercised no injury "
        "to recover from"
    )
    world.reattach()
    report = recover(world.store)
    assert report.leases_reclaimed > 0, (
        "TC-E2E-02 (a): recover reclaimed no lease - the sweep did not see the dead "
        "worker's abandoned batch"
    )
    assert report.runs_resumed == (world.run_id,), (
        f"TC-E2E-02 (a): recover resumed {report.runs_resumed} - the killed run is the "
        "running run recovery exists for (FR-PIPE-07)"
    )
    assert _leased(world) == 0, (
        "TC-E2E-02 (a): the sweep left the dead worker's leases held - the abandoned "
        "batch would never finish, and its cells never reach the aggregation hook"
    )
    assert world.drive().status == "complete"
    assert world.result_set() == expected, (
        "TC-E2E-02 (a): the recovered run's result set differs from the uninterrupted "
        "control's - a restart must replay the recordings, never recompute a "
        "judgement (RES-04..07)"
    )


# --- TC-E2E-02 variant (b): provider unavailable mid-run ------------------------------------

def test_tc_e2e_02_provider_unavailable_pauses_on_the_same_backend_then_resumes(
    tmp_data_dir, tmp_path, monkeypatch, repo_root,
):
    """`TC-E2E-02` variant (b): the boundary drops mid-run, the composed pipeline
    pauses the run with the sensed cause, the frozen backend never moves, and the
    resume re-drives to a result set identical to the control's."""
    control = ComposedSynthWorld(tmp_data_dir / "control", tmp_path / "fixtures",
                                 n_submissions=VARIANT_SCALE, monkeypatch=monkeypatch)
    control.build_run()
    control.start_run()
    assert control.drive().status == "complete"
    expected = control.result_set()

    world = _OutageWorld(tmp_data_dir, tmp_path / "fixtures" / "unavailable",
                         n_submissions=VARIANT_SCALE, monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    backend_before = _run_row(world)
    world.set_unavailable(True)
    result = world.drive()
    assert result.status == "paused", (
        f"TC-E2E-02 (b): the drive read {result.status!r} - the unavailable boundary "
        "pauses the run (FR-ORCH-30 absorbs the error per future), it does not fail it"
    )
    assert result.pause_reason and "ProviderUnavailableError" in str(result.pause_reason), (
        f"TC-E2E-02 (b): the pause reason is {result.pause_reason!r} - the sensed "
        "cause, not a bare status (CT-ORCH-12)"
    )
    paused = _run_row(world)
    assert paused["status"] == "paused" and paused["pause_reason"], (
        "TC-E2E-02 (b): the run row does not read paused with a rendered reason - the "
        "operator surface must say why the run stopped (CT-ORCH-12)"
    )
    assert paused["provider_config"] == backend_before["provider_config"], (
        "TC-E2E-02 (b): the pause moved the run's frozen provider snapshot - "
        "FR-ORCH-16's resume-same-backend is structural: no code path exists by which "
        "a pause could substitute a backend"
    )
    assert paused["panel_config"] == backend_before["panel_config"]
    world.set_unavailable(False)
    world.orchestrator.resume(world.run_id)
    assert _run_row(world)["status"] == "running", (
        "TC-E2E-02 (b): the resume did not effect the paused -> running edge"
    )
    # The operator restarts the worker process after the outage: a fresh orchestrator
    # (fresh LeaseClock) reads every lease ever issued as expired, so `recover`'s sweep
    # reclaims whatever the window caught. On the SAME orchestrator the clock is
    # mid-life - the in-flight leases are not yet expired, the sweep reclaims nothing,
    # and units stranded mid-batch stay invisible to every later drive.
    world.reattach()
    recover(world.store)
    assert world.drive().status == "complete"
    assert world.result_set() == expected, (
        "TC-E2E-02 (b): the resumed run's result set differs from the control's - the "
        "pause is a stop, never a rewrite of what the run produced"
    )


# --- TC-E2E-02 variant (c): the escalation breaker ------------------------------------------

def test_tc_e2e_02_criterion_breaker_halts_escalation_and_the_run_still_completes(
    tmp_data_dir, tmp_path, monkeypatch, repo_root,
):
    """`TC-E2E-02` variant (c): a criterion trips the escalation breaker - escalation
    halts for it, the refused cells are re-aggregated `ungradeable_by_panel` in the
    hook's own transaction, the mark surfaces in the rollup findings with the affected
    student count, and the run still completes with every admitted grade finalized."""
    world = _BreakerWorld(tmp_data_dir, tmp_path / "fixtures",
                          n_submissions=VARIANT_SCALE, monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    result = world.drive()
    assert result.status == "complete", result.pause_reason

    latched = world.handle.query(
        "SELECT criterion_id, detail FROM circuit_breaker WHERE run_id = :r",
        r=world.run_id)
    assert latched, (
        "TC-E2E-02 (c): no criterion breaker latched at rate 0.50 over a four-wide "
        "window on this cohort - the variant exercised nothing"
    )
    assert all("un-gradeable_by_panel" in row["detail"] for row in latched), (
        "TC-E2E-02 (c): the latched breaker row's detail does not carry the design's "
        "mark - the operator surface names the degradation (FR-ORCH-13)"
    )
    # The mark on the RESULT is M-AGG's artifact, written in the hook's transaction
    # (FR-ORCH-13): the cells whose widening the halt refused read routed provisional,
    # state ungradeable_by_panel, with the panel's own figure standing - three judges
    # where the halt refused the first widening, five where a widening had already
    # landed (FR-AGG-11's precedence; the halt refuses the widening, never the
    # judgement already made).
    marked = world.handle.query(
        "SELECT submission_id, criterion_id, judge_count, routing, state "
        "FROM criterion_score WHERE run_id = :r AND state = 'ungradeable_by_panel'",
        r=world.run_id)
    assert marked, (
        "TC-E2E-02 (c): the trip left no re-aggregated cell - the mark on the result "
        "is the aggregation's artifact (FR-ORCH-13)"
    )
    for row in marked:
        assert row["state"] == "ungradeable_by_panel" and row["routing"] == "provisional", (
            f"TC-E2E-02 (c): the breaker-marked cell ({row['submission_id'][:12]}, "
            f"{row['criterion_id']}) reads {row['state']!r}/{row['routing']!r} - the "
            "breaker's precedence routes the refused widening provisional and "
            "ungradeable_by_panel (FR-AGG-11)"
        )
        assert row["judge_count"] in (3, 5), (
            f"TC-E2E-02 (c): a breaker-marked cell reads judge_count "
            f"{row['judge_count']} - the mark keeps the panel's own figure standing "
            "(the halt refuses the widening, not the judgement already made)"
        )
    findings = {finding.criterion_id: finding
                for finding in rollup_findings(world.run_id, world.store)}
    marked_cids = {row["criterion_id"] for row in marked}
    assert marked_cids <= set(findings), (
        "TC-E2E-02 (c): the breaker mark does not surface in the rollup findings - "
        "CT-ORCH-16's degradation must be visible to the operator"
    )
    for criterion_id in marked_cids:
        touched = {row["submission_id"] for row in marked
                   if row["criterion_id"] == criterion_id}
        assert findings[criterion_id].student_count >= len(touched), (
            f"TC-E2E-02 (c): the finding for {criterion_id} undercounts its affected "
            "students"
        )
    assert _run_row(world)["status"] == "complete", (
        "TC-E2E-02 (c): the breaker halted escalation but must not stop the run - it "
        "degrades scrutiny visibly, it does not fail the journey"
    )
    finalized = world.handle.query(
        "SELECT COUNT(*) AS n FROM submission_grade WHERE run_id = :r "
        "AND is_current = 1 AND state = 'final'", r=world.run_id)
    assert int(finalized[0]["n"]) == 23, (
        "TC-E2E-02 (c): the breaker must not cost the admitted population its "
        "finalized grades"
    )