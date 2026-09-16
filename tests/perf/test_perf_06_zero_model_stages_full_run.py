"""`PERF-06` (issue #146, TS-53) — the zero-model stages inside a full `F-SYNTH` run.

Test plan §6.4: *"The zero-model stages, measured against a run with them disabled | Full run |
`F-SYNTH` | Added wall clock | Integrity < 1% of run wall clock; aggregation microseconds each; all
deterministic criteria for 350 students < 5 s | E1"* (`NFR-INTEG-01`, `NFR-AGG-03`, `NFR-DET-01`).

**What this adds over the module cases.** Each stage's threshold already has a module-scale case:
`TC-INTEG-11` (verification against a workload, with the `INTEG_SPAN_VERIFICATION_DISABLED`
differential), `TC-AGG-20` (5,250 aggregations at unit tier) and `TC-DET-11` (the 350-student
deterministic pass). `TC-INTEG-11` states that the *full-run* measurement "belongs to TS-53".
This is that measurement: the assembled overnight run over the 350-submission `F-SYNTH` cohort
(`tests/support/e2e_world.py`, `TC-E2E-02`'s drive in §4.2.2's order), with every call into the
three stages timed where the run makes it.

**How "measured against a run with them disabled" is expressed.** Each stage's added wall clock is
timed directly inside the run: every `IntegrityGate.verify`, every `aggregate`, and the
`DeterministicEvaluator.evaluate_cohort` pass, with `time.perf_counter` wrapped around the call. A
run with the stage switched off would be the same wall clock less exactly those calls. A literal
second run was not used, for two reasons that would make it measure something else:

- Only integrity has an off switch, so there is no "aggregation disabled" or "deterministic
  disabled" run to take the difference from.
- Switching integrity off changes the run, not just its cost. The gate's signals feed routing and
  the escalation ladder, so the disabled run leases, scores and aggregates a different set of units.
  Its wall clock differs by more than the gate's own cost.

On top of that, two overnight drives differ by far more than 1% in scheduler noise, so a raw
difference would not measure a 1% budget at all. Timing the calls in place gives the same added
wall clock as the ideal differential, without that confound.

**Scope of "run wall clock".** The overnight drive from `build_run` to `finalize`. World synthesis
(ingesting the 350 PDFs) is `PERF-02`'s load, not this run's, and is excluded. Excluding it makes
the integrity share *larger*, so it cannot help this case pass.

**The gate's own time, not the test world's.** `IntegrityGate.verify` reads its evidence through an
`ExtractionView`, and in the assembled world that view is `LedgerEvidenceView`, a test double in
`tests/support/e2e_world.py`. No shipped read model exists yet. The double's SQL is not
integrity's cost, so its methods get their own clock: the gate's time is verify's total less the
time spent inside the view. That is what the 1% is asserted on. The gross figure and the view's
share are reported beside it.

**Deviation to route to the plan's owner.** In-place timing leaves out the downstream cost the gate
causes: re-extraction from its retries and the review items it routes. §6.4 still reads "measured
against a run with them disabled". The reasons above say why this case does not do that literally,
and the PR asks `/create-test-plan` whether §6.4 should say so.

Markers: `e2e` and `slow`, like the journey it drives: a full-run case over the assembled world runs
in the E2E tier, never the fast tier. The environment is E1, and the result says so.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field

import pytest

import tests.support.e2e_world as e2e_world
from aeh.det import DeterministicEvaluator
from aeh.integ import IntegrityGate
from tests.support.e2e_world import SynthWorld

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

ENVIRONMENT = "E1"

#: `NFR-INTEG-01`: integrity adds under 1% of run wall clock.
INTEGRITY_SHARE_CEILING = 0.01
#: `NFR-AGG-03`: aggregation is microseconds per call. The ceiling is one millisecond, the same
#: reading `TC-AGG-20` pins (`_PER_CALL_CEILING_SECONDS`): anything at or above it is not
#: microseconds.
AGGREGATION_PER_CALL_CEILING_S = 0.001
#: `NFR-DET-01`: all deterministic criteria for 350 students in under 5 seconds.
DETERMINISTIC_PASS_CEILING_S = 5.0
#: `F-SYNTH`: 350 submissions (§4.4).
COHORT_SIZE = 350
#: The test double's read methods the gate calls through (`ExtractionView`).
VIEW_METHODS = ("spans", "second_family_spans", "regions", "panel_sufficiency",
                "criterion_requires_citation")


@dataclass
class StageClock:
    """Seconds spent inside one stage's calls, and how many calls there were."""

    durations: list[float] = field(default_factory=list)
    #: When set, only calls made while that clock is inside a call are counted.
    within: "StageClock | None" = None
    depth: int = 0

    def wrap(self, fn):
        def timed(*args, **kwargs):
            if self.within is not None and self.within.depth == 0:
                return fn(*args, **kwargs)
            started = time.perf_counter()
            self.depth += 1
            try:
                return fn(*args, **kwargs)
            finally:
                self.depth -= 1
                self.durations.append(time.perf_counter() - started)

        return timed

    @property
    def total(self) -> float:
        return sum(self.durations)


def test_perf_06_zero_model_stages_stay_inside_their_budgets_in_a_full_run(
    tmp_data_dir, tmp_path, monkeypatch
):
    """`PERF-06`: over one full 350-submission overnight drive on E1, integrity is under 1% of the
    run's wall clock, each aggregation is microseconds, and the deterministic pass for all 350
    students is under 5 s. The measured load is checked first, so a run that skipped a stage
    cannot pass on an empty numerator."""
    world = SynthWorld(tmp_data_dir, tmp_path / "fixtures", n_submissions=COHORT_SIZE,
                       monkeypatch=monkeypatch)
    integrity, aggregation, deterministic = StageClock(), StageClock(), StageClock()
    # Only the view reads the gate makes from inside verify are subtracted from it.
    view = StageClock(within=integrity)
    monkeypatch.setattr(IntegrityGate, "verify", integrity.wrap(IntegrityGate.verify))
    for name in VIEW_METHODS:
        monkeypatch.setattr(e2e_world.LedgerEvidenceView, name,
                            view.wrap(getattr(e2e_world.LedgerEvidenceView, name)))
    # The world's walk calls `aggregate` through its own module namespace.
    monkeypatch.setattr(e2e_world, "aggregate", aggregation.wrap(e2e_world.aggregate))
    monkeypatch.setattr(DeterministicEvaluator, "evaluate_cohort",
                        deterministic.wrap(DeterministicEvaluator.evaluate_cohort))

    started = time.perf_counter()
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
    run_seconds = time.perf_counter() - started

    cells = len(world.admitted_ids()) * len(world.open_ids)
    gate_seconds = integrity.total - view.total
    report = (
        f"PERF-06 on {ENVIRONMENT} (not evidence about E4): run {run_seconds:.2f}s; "
        f"integrity gate {gate_seconds:.3f}s ({gate_seconds / run_seconds:.4%} of the run) = "
        f"verify {integrity.total:.3f}s over {len(integrity.durations)} calls less "
        f"{view.total:.3f}s inside the test double's evidence view; aggregation "
        f"{len(aggregation.durations)} calls, mean "
        f"{statistics.mean(aggregation.durations or [0.0]) * 1e6:.0f}us, max "
        f"{max(aggregation.durations or [0.0]) * 1e6:.0f}us; deterministic pass "
        f"{deterministic.total:.3f}s over {len(deterministic.durations)} call(s)"
    )
    print(report)

    # The load has to be present before any ratio means anything.
    assert len(world.cohort) == COHORT_SIZE, f"fixture: {len(world.cohort)} submissions. {report}"
    assert len(deterministic.durations) == 1, (
        f"the deterministic stage ran {len(deterministic.durations)} cohort passes; PERF-06 times "
        f"ONE pass over all 350 students. {report}"
    )
    assert len(integrity.durations) == 2 * cells, (
        f"integrity verified {len(integrity.durations)} cells, not the two passes over "
        f"{cells} admitted cells the drive makes. {report}"
    )
    assert len(aggregation.durations) >= 2 * cells, (
        f"aggregation ran {len(aggregation.durations)} times, fewer than the two walks over "
        f"{cells} cells. {report}"
    )

    problems = []
    if gate_seconds >= INTEGRITY_SHARE_CEILING * run_seconds:
        problems.append(
            f"the integrity gate's own time was {gate_seconds / run_seconds:.3%} of the run's wall "
            f"clock, at or over NFR-INTEG-01's 1% ({gate_seconds / len(integrity.durations) * 1e3:.1f}"
            f" ms per verify, excluding the test double's evidence reads). [When written (E1, "
            f"2026-09-13): the gate's own 123.5 s was 2.30% of a 5370.6 s run, 15.1 ms per verify "
            f"over 8184 calls, with 392.5 s more inside the test double's view; profiles at 40 and "
            f"120 submissions showed the per-call cost growing with the cohort. Query plans read when "
            f"written, on an empty schema: the gate's count_verdicts scans verdict (no index on "
            f"verdict.work_id); count_units uses idx_wu_pairs on run_id only; the document read "
            f"scans document (no index on submission_id).]")
    # The mean, not the maximum: one call caught by a garbage-collection pause is the machine,
    # not the aggregation, and a max-gated case would flake on it (§4.6's flake policy).
    per_call = statistics.mean(aggregation.durations)
    if per_call >= AGGREGATION_PER_CALL_CEILING_S:
        problems.append(f"aggregation averaged {per_call * 1e3:.3f} ms per call over "
                        f"{len(aggregation.durations)} calls; NFR-AGG-03 says microseconds each")
    if deterministic.total >= DETERMINISTIC_PASS_CEILING_S:
        problems.append(f"the deterministic pass for 350 students took {deterministic.total:.2f}s, "
                        f"at or over NFR-DET-01's 5 s")
    assert not problems, "\n".join(problems) + f"\n{report}"
