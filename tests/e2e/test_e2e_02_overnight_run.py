"""TC-E2E-02 — The overnight run: 350 submissions in, 341 finalized grades out, zero
teacher action at any point.

The second of the three end-to-end journeys (TS-51, issue #144; design §4.2.2, test plan
§6.2). Rung 4 — the ASSEMBLED system, on the shared world module
(`tests.support.e2e_world`, whose disclosures are this journey's disclosures): real
store across the full migration chain, real gateway ingesting 350 four-page PDFs
through the real sanitizer and rasterizer, real M-PKG catalog and publication, real
orchestrator, real deterministic evaluator, real extraction workers (second family
included), real integrity gate over real ledger rows, real aggregation walk, real
scoring workers, real synthesis worker, real grade pass. No doubles at any module
boundary; the only double anywhere is the model boundary — the shipped
`RecordedFixtureProvider` in its regeneration-then-replay shape (journey-1 precedent):
a first sight of a request is answered by the journey's own computation and recorded
through the shipped `record()`/request-key machinery, and every later identical request
replays from the recording — `CT-PROV-10`'s only egress, exercised as `F-RECORDED`'s
own lifecycle.

**Happy path** (§4.2.2, in order): 350 submissions ingest (9 quarantine); the run
starts with the backend fixed; units enumerate and a cost estimate is shown before any
dispatch; Sweep 1 runs in topological order; the integrity gate runs; deterministic
criteria are scored by lookup; Sweep 2 runs judge-first; verdicts aggregate to median
bands with points mapped once; escalations enqueue in-transaction; synthesis runs L1
then L2; the run completes and every grade finalizes with no teacher action at any
point. **Oracle**: 341 grades exist, coverage is recorded per grade, provisional grades
are labelled, and the whole journey is compared against a committed baseline result set.

**The baseline** (fixtures/baselines/TC-E2E-02/result-set.json) freezes the full
350-submission result set the assembled system produced — per submission: the ingest
status with its per-gate record, the grade with its five coverage counters, every
criterion score row, and the narrative set. §6.9's discipline applies even though the
six-entry registry does not name a `TC-E2E-*` row (the registry's table is §6.9's own
and pinned by its drift test): the producing tier is the journey's own
`RecordedFixtureProvider` — request-keyed, regeneration-then-replay — so no live
backend's wording can move it, and the governance is inline here. Reviewer: the
overnight run's owner. Grounds for accepting a diff: a package-corpus bump or a
declared world-shape change — **never** "the model changed its mind"; a diff in a
band, a points figure, a routing or a coverage counter is a defect, not a baseline
update. There is deliberately no regenerate helper here: the first capture was run,
inspected and committed in the PR that carried it. Nondeterministic identifiers are
normalized out on purpose (submission and version ids are minted per build), so the
baseline freezes what the system PRODUCED, and the identifier shapes are asserted
separately; timestamps are excluded and narrative prose carries digests, because the
baseline's business is what was produced, not the scripted wording.

**Variants** (each a separate execution at reduced scale, compared against an in-test
control run at the same scale):

(a) **SIGKILL at a seeded random point + `resume()`** (RES-04..07): the drive is cut
    mid-leg with units still LEASED — the exact injury a SIGKILLed worker leaves — the
    world reattaches on the same directories (a fresh store, a fresh provider over the
    same fixture store, a fresh orchestrator), the lease sweeper requeues the abandoned
    leases, and the drive continues to the sanctioned closer. The resumed result set
    equals the uninterrupted control's: a restart replays, it never recomputes.
(b) **Provider unavailable mid-run → pause on the same backend → resume**
    (`FR-ORCH-16`, `CT-ORCH-12`): the driver surfaces `ProviderUnavailableError`
    before any unit is struck, the operator pauses with the sensed cause, the run row
    reads paused with its reason and with `provider_config`/`panel_config` untouched,
    the backend recovers, `resume()` un-pauses, the sweeper requeues the batch the
    window caught, and the result set equals the control's.
(c) **A criterion trips the escalation breaker** (`FR-ORCH-13`, `CT-ORCH-16`): the
    walk hands the breaker its knobs at call time; a criterion escalating for more
    than the rate's share of its first window trips it, escalation halts for that
    criterion (`halted_by_breaker`, zero units), the refused cells are re-aggregated
    with `breaker_tripped=True` in the caller's transaction — routed provisional,
    state `ungradeable_by_panel`, the panel's own figure standing — the mark surfaces
    in the rollup findings with the affected-student count, and the run still
    completes with every admitted grade finalized.

Disclosed shape: the world's base panel is three judges, so a breaker-marked cell
keeps a three-judge figure standing — the design's "remainder single-judge provisional"
phrasing is that mark on a one-judge base panel; here the halt refuses the widening,
not the judgement already made, and the precedence (breaker over panel size) is what
the variant pins.
"""

from __future__ import annotations

import json
import random
from decimal import Decimal
from pathlib import Path

import pytest

from aeh.grade import rollup_findings
from aeh.prov import ProviderUnavailableError
from tests.support.e2e_world import (
    GRADE_BOUNDARIES,
    SynthWorld,
)

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

ISSUE = "#144"

#: The variants' reduced scale: enough submissions for the escalation ladder and the
#: breaker's window to be real (the breaker variant pins the window minimum at 4),
#: small enough that a variant plus its control is minutes.
VARIANT_SCALE = 24

#: The SIGKILL variant's seeded draw range: (leg, units struck before the kill). The
#: seed makes the random point reproducible; both judged legs are in the draw.
KILL_POINTS = (
    ("extract", 9),
    ("extract", 40),
    ("score", 25),
    ("score", 121),
)

#: The variant-(c) breaker knobs, handed to the walk at call time. Rate 0.50 is the
#: shipped production value; the window minimum is pinned below the shipped 20 so the
#: reduced scale's own first four completions are the window.
BREAKER_RATE = "0.50"
BREAKER_MIN_N = "4"


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
    """Units the drive currently holds leases on - the SIGKILL variant's injury."""
    return _count(world, "SELECT work_id FROM work_unit WHERE run_id = :r "
                         "AND status = 'leased'", r=world.run_id)


def _drive_overnight(world: SynthWorld, monkeypatch) -> None:
    """The uninterrupted overnight drive in §4.2.2's order — the variants' control."""
    world.build_run()
    world.start_run()
    world.drive_deterministic()
    world.integrity_pass()
    world.drive_extract()
    world.drive_score()
    world.integrity_pass(capture=True)
    world.aggregate_walk(monkeypatch=monkeypatch)
    world.drive_score(include_escalations=True)
    world.aggregate_walk(monkeypatch=monkeypatch)
    world.drive_synthesis()
    world.finalize()


def _assert_matches_baseline(repo_root: Path, result_set: dict) -> None:
    """Compare the journey's result set against its committed baseline, with §6.9's
    governance in the failure message — journey-1's manifest shape."""
    baseline_path = repo_root / "fixtures" / "baselines" / "TC-E2E-02" / "result-set.json"
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
    341-final / 9-quarantine oracle, coverage per grade, provisional labels, and the
    whole journey against the committed baseline."""
    world = SynthWorld(tmp_data_dir, tmp_path / "fixtures", n_submissions=350,
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

    # Sweep 1 in topological order (FR-ORCH-08): the deterministic leg completes its
    # whole stage before the judged legs strike a unit.
    world.drive_deterministic()
    assert _count(world, "SELECT work_id FROM work_unit WHERE run_id = :r AND "
                         "stage = 'deterministic' AND status != 'done'",
                  r=world.run_id) == 0, (
        "TC-E2E-02: the deterministic leg left units un-done - Sweep 1's order is "
        "topological, det first"
    )
    assert _count(world, "SELECT work_id FROM work_unit WHERE run_id = :r AND "
                         "stage IN ('extract', 'score') AND status = 'done'",
                  r=world.run_id) == 0, (
        "TC-E2E-02: judged units completed while the deterministic stage ran - Sweep "
        "1's stages are topological (FR-ORCH-08), not concurrent"
    )
    world.integrity_pass()
    world.drive_extract()
    world.drive_score()
    world.integrity_pass(capture=True)
    # The walk: median bands, points mapped once, escalations in the caller's tx.
    enqueued = world.aggregate_walk(monkeypatch=monkeypatch)
    assert enqueued > 0, (
        "TC-E2E-02: the first walk enqueued no widening - the interior-band limb is "
        "this cohort's honest escalation share"
    )
    world.drive_score(include_escalations=True)
    world.aggregate_walk(monkeypatch=monkeypatch)
    world.drive_synthesis()
    world.finalize()

    assert _run_row(world)["status"] == "complete", (
        "TC-E2E-02: the run did not complete - the sanctioned closer fires only with "
        "zero open units underneath it"
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


# --- TC-E2E-02 variant (a): SIGKILL at a seeded random point, then resume -------------------

def test_tc_e2e_02_sigkill_and_resume_reproduces_the_control(
    tmp_data_dir, tmp_path, monkeypatch, repo_root,
):
    """`TC-E2E-02` variant (a) (RES-04..07): a seeded random-point kill mid-leg, the
    world reattached on the same directories, the sweeper requeueing the abandoned
    leases, `resume()` closing - and the resumed result set equals the uninterrupted
    control's at the same scale."""
    control = SynthWorld(tmp_data_dir / "control", tmp_path / "fixtures",
                         n_submissions=VARIANT_SCALE, monkeypatch=monkeypatch)
    _drive_overnight(control, monkeypatch=monkeypatch)
    expected = control.result_set()
    assert any(s["quarantined"] for s in expected["submissions"]), (
        "precondition: the variant's scale holds a quarantine, as the overnight does"
    )

    world = SynthWorld(tmp_data_dir, tmp_path / "fixtures" / "kill",
                       n_submissions=VARIANT_SCALE, monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    world.drive_deterministic()
    world.integrity_pass()
    leg, cut = random.Random(14402).choice(KILL_POINTS)
    if leg == "extract":
        struck = world.drive_extract(limit=cut)
        assert struck == cut
        assert _leased(world) > 0, (
            "TC-E2E-02 (a): the cut drive left no leased unit - the kill exercised no "
            "injury to recover from"
        )
        world.reattach()
        world.sweep()
        world.drive_extract()
        world.drive_score()
    else:
        world.drive_extract()
        struck = world.drive_score(limit=cut)
        assert struck == cut
        assert _leased(world) > 0
        world.reattach()
        world.sweep()
        world.drive_score()
    world.integrity_pass(capture=True)
    world.aggregate_walk(monkeypatch=monkeypatch)
    world.drive_score(include_escalations=True)
    world.aggregate_walk(monkeypatch=monkeypatch)
    world.drive_synthesis()
    world.finalize()
    assert world.result_set() == expected, (
        "TC-E2E-02 (a): the resumed run's result set differs from the uninterrupted "
        "control's - a restart must replay the recordings, never recompute a "
        "judgement (RES-04..07)"
    )


# --- TC-E2E-02 variant (b): provider unavailable mid-run ------------------------------------

def test_tc_e2e_02_provider_unavailable_pauses_on_the_same_backend_then_resumes(
    tmp_data_dir, tmp_path, monkeypatch, repo_root,
):
    """`TC-E2E-02` variant (b): the provider drops mid-run, the operator pauses with
    the sensed cause, the frozen backend never moves, and the resume re-drives to a
    result set identical to the control's."""
    control = SynthWorld(tmp_data_dir / "control", tmp_path / "fixtures",
                         n_submissions=VARIANT_SCALE, monkeypatch=monkeypatch)
    _drive_overnight(control, monkeypatch=monkeypatch)
    expected = control.result_set()

    world = SynthWorld(tmp_data_dir, tmp_path / "fixtures" / "unavailable",
                       n_submissions=VARIANT_SCALE, monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    world.drive_deterministic()
    world.integrity_pass()
    backend_before = _run_row(world)
    world.provider.set_unavailable(True)
    with pytest.raises(ProviderUnavailableError):
        world.drive_extract()
    assert _leased(world) > 0, (
        "TC-E2E-02 (b): the aborted drive left no leased unit - the window must catch "
        "the driver holding the batch it was striking"
    )
    cause = ProviderUnavailableError("the journey's provider is unavailable (injected)")
    assert world.orchestrator.pause(world.run_id, cause=cause) == "paused"
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
    world.provider.set_unavailable(False)
    world.orchestrator.resume(world.run_id)
    assert _run_row(world)["status"] == "running", (
        "TC-E2E-02 (b): the resume did not effect the paused -> running edge"
    )
    # The operator restarts the worker process after the outage: a fresh
    # orchestrator (fresh LeaseClock) reads every lease ever issued as expired, so
    # the sweep reclaims the units the aborted drive held mid-batch. On the SAME
    # orchestrator the clock is mid-life - the in-flight leases are not yet expired,
    # the sweep reclaims nothing, and the units the outage stranded are invisible to
    # every later drive (leased != pending) - their cells never reach the walk.
    world.reattach()
    world.sweep()
    world.drive_extract()
    world.drive_score()
    world.integrity_pass(capture=True)
    world.aggregate_walk(monkeypatch=monkeypatch)
    world.drive_score(include_escalations=True)
    world.aggregate_walk(monkeypatch=monkeypatch)
    world.drive_synthesis()
    world.finalize()
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
    caller's transaction, the mark surfaces in the rollup findings with the affected
    student count, and the run still completes with every admitted grade finalized."""
    world = SynthWorld(tmp_data_dir, tmp_path / "fixtures", n_submissions=VARIANT_SCALE,
                       monkeypatch=monkeypatch)
    breaker = {"breaker_rate": BREAKER_RATE, "breaker_min_n": BREAKER_MIN_N}
    world.build_run()
    world.start_run()
    world.drive_deterministic()
    world.integrity_pass()
    world.drive_extract()
    world.drive_score()
    world.integrity_pass(capture=True)
    world.aggregate_walk(monkeypatch=monkeypatch, **breaker)
    world.drive_score(include_escalations=True)
    world.aggregate_walk(monkeypatch=monkeypatch, **breaker)
    world.drive_synthesis()
    world.finalize()

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
    marked = world.breaker_marked
    assert marked, (
        "TC-E2E-02 (c): the trip left no re-aggregated cell - the mark on the result "
        "is M-AGG's artifact, written in the caller's transaction (FR-ORCH-13)"
    )
    for sid, cid in marked:
        row = world.handle.query(
            "SELECT judge_count, routing, state FROM criterion_score "
            "WHERE submission_id = :s AND criterion_id = :c", s=sid, c=cid)[0]
        assert row["state"] == "ungradeable_by_panel" and row["routing"] == "provisional", (
            f"TC-E2E-02 (c): the breaker-marked cell ({sid[:12]}, {cid}) reads "
            f"{row['state']!r}/{row['routing']!r} - the breaker's precedence routes "
            "the refused widening provisional and ungradeable_by_panel (FR-AGG-11)"
        )
        assert row["judge_count"] == 3, (
            "TC-E2E-02 (c): a breaker-marked cell must keep the panel's own figure - "
            "the halt refuses the widening, not the judgement already made"
        )
    findings = {finding.criterion_id: finding
                for finding in rollup_findings(world.run_id, world.store)}
    marked_cids = {cid for _, cid in marked}
    assert marked_cids <= set(findings), (
        "TC-E2E-02 (c): the breaker mark does not surface in the rollup findings - "
        "CT-ORCH-16's degradation must be visible to the operator"
    )
    for criterion_id in marked_cids:
        touched = {sid for sid, cid in marked if cid == criterion_id}
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
