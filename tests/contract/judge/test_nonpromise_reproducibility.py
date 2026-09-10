"""`TC-JUDGE-C17` — verdicts are not reproducible, and no consumer may assume they are
(§6.11.10).

`CT-JUDGE-17` (behaviour, **non-promise**): *"`**Not promised:** verdicts are not
reproducible. The same request may yield a different band on a re-run at any
temperature, on any backend. `M-STATS` FR-STATS-16 **measures** self-agreement
precisely because it is not guaranteed; a consumer must not treat two identical
requests as owing identical answers."* (detailed design, verbatim). The plan's
technique is the case's shape: *"Do not assert verdicts vary. **Make them vary** —
the same request yielding a different band on a re-run, at temperature 0, on the same
backend — and assert every consumer still behaves correctly."*

Five limbs carry the sweep the plan names (`M-AGG`, `M-STATS`, `M-CONFORM`):

1. **the provider double varies, the boundary accepts both** (rung 2) — a
   transport double programmed with two *different but valid* completions serves
   byte-identical repeated requests: the SAME request dispatched twice makes TWO
   boundary calls and both replies are accepted. The non-promise is made real, not
   asserted;
2. **`M-AGG` reuses by `work_id` and merges nothing on request equality** (rung 3)
   — two full runs of the same world on ONE store: the units' `work_id` sets are
   disjoint (the id is the reuse key, computed over `run_id` among its nine
   inputs) while their rendered prompts are byte-identical (the render is a pure
   function of the world, no run identity rides it), each run's verdict rows carry
   its own band and nothing merges, and each run's aggregation reads its OWN
   verdicts — run A aggregates "emerging", run B "secure", on identical requests.
   The artifact half: `aeh.agg`'s AST carries no caching decorator — the shape a
   "same request, same answer" memo takes;
3. **`M-STATS` measures self-agreement as a finding** (rung 2, written ahead of
   `#116`) — `FR-STATS-16` measures self-agreement because it is not guaranteed;
   a measured 0.71 is REPORTED verbatim as the finding it is — no exception, no
   omitted judge, no single pass/fail flip (`CT-STATS-07`'s six-steps shape);
4. **`M-CONFORM` measures repetition and requires no reproducibility** (rung 2,
   written ahead of `#134`) — the comparison's divergence dimensions carry
   `self_agreement_over_repeated_runs` as a MEASURED rate (the same no-unmeasured
   bet `TC-CONFORM-C04` makes) and never as a boolean "reproduced" gate;
5. **no golden file pins a verdict as an exact-match expectation in the live
   tier** (rung 0) — the live-tier judge suites' directory carries no data
   artifact at all, and no live-tier source compares a verdict or band to a
   string literal with `==`: the two shapes a golden pin takes. Positive controls
   prove both scans fire.

`M-PROV`'s side of the same bargain (`CT-PROV-16`: *no verdict is ever re-sampled*)
is the transport double's contract and lives in `TC-PROV`'s suite; this file is the
consumer side. Cross-references, not duplicates: the producer-side knob that invites
the assumption is `TC-JUDGE-C15`'s (temperature zero is a sampling parameter); the
isolation guarantee that keeps verdicts per-unit is `TC-JUDGE-C14`; the MVVP
step-reporting shape this file's stats limb reuses is `TC-STATS-C07`
(`test_ct_stats_mvvp.py`); the five-dimension divergence shape the conform limb
rides is `TC-CONFORM-C04` (`test_ct_conform_pipeline_and_divergence.py`). The live
tier's own suites (`TC-JUDGE-21/22/23`, `tests/security/judge/`) run the real
backend; limb 5 is the artifact assertion that none of them pins its output.

Isolation: rung 2 — real store, real workers, a transport double at the model
boundary; rung 3 for the `M-AGG` consumer differential (two full runs, real
ledgers); rung 0 for the artifact limbs; the socket guard is autouse.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from aeh.conf import CohortRef
from aeh.orch import Orchestrator
from aeh.store import open_store
from tests.contract.agg._drive import criterion_bands, stored_verdicts
from tests.contract.judge._drive import (
    BANDS,
    PANEL_REFS,
    RecordingTransport,
    add_bands,
    drive_extract,
    lease_score_units,
    seed_world,
    spans,
)
from tests.support import stats_vocabulary as vocab
from tests.support.agg_vocabulary import agg_config, criterion, signals
from tests.support.conf_builders import EDGE_PANEL_3, HOSTED_PANEL_3, edge_cfg, hosted_cfg
from tests.support.conform_vocabulary import SELF_AGREEMENT_DIMENSION
from tests.support.extract_vocabulary import verdict_completion
from tests.support.impl import (
    AGG_MODULE,
    CONFORM_MODULE,
    JUDGE_MODULE,
    STATS_MODULE,
    require,
)
from tests.support.orch_run import (
    ORCH_COHORT_ID,
    orch_cfg,
    seed_cohort,
    seed_documents,
    seed_package,
)

pytestmark = [pytest.mark.contract]

#: The story that owns the clause (`M-JUDGE` is complete — #78/#79/#80/#81).
ISSUE = "#78"

_SUBMISSIONS = ("SYN-001", "SYN-002")

_JUDGE_BUILD = "build-judge-contract"

_C1_SPEC = {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic",
            "band_count": len(BANDS)}

_RUN_A = "run-c17-a"
_RUN_B = "run-c17-b"


def test_tc_judge_c17_the_same_request_is_sampled_again_and_both_replies_are_accepted(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C17` limb 1 (the provider double varies, rung 2, P0) — the SAME
    request dispatched twice makes TWO boundary calls and lands two DIFFERENT valid
    bands, both accepted: the non-promise is made real at the boundary, at the
    default temperature, on the same backend."""
    provider = make_fixture_provider()
    store = open_store(tmp_data_dir)
    try:
        orchestrator, _run_id, _version = seed_world(store)
        drive_extract(orchestrator, store, provider)
        units = lease_score_units(orchestrator)
        assert units, "fixture bug: no score unit leased for the variation drive"
        unit = units[0]
        refs_by_build = {ref.build_id: ref for ref in PANEL_REFS}
        judge_ref = refs_by_build[unit.judge]
        request = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, None, judge_ref
        ).assemble(unit)

        # The double's program: a different but valid band per call — the two
        # completions differ in band AND confidence, and both bands are inside the
        # criterion's declared set.
        program = [
            verdict_completion("emerging", 0.8, build_id=_JUDGE_BUILD,
                               cited_spans=spans()),
            verdict_completion("secure", 0.9, build_id=_JUDGE_BUILD,
                               cited_spans=spans()),
        ]
        transport = RecordingTransport(program)
        worker = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, transport, judge_ref
        )

        first = worker.dispatch(request, judge_ref)
        second = worker.dispatch(request, judge_ref)

        # Two dispatches of the byte-identical request, two boundary calls — the
        # boundary re-SAMPLES, it does not replay a verdict (`CT-PROV-16`'s flip
        # side: the fixture provider replays RECORDINGS; a live dispatch samples).
        assert len(transport.calls) == 2, (
            f"the second dispatch of the identical request made "
            f"{len(transport.calls)} boundary call(s) — a re-run is SAMPLED, not "
            "short-cut on request equality (CT-JUDGE-17, CT-JUDGE-15)"
        )
        assert transport.payloads()[0] == transport.payloads()[1], (
            "the two dispatches did not send byte-identical payloads — the render "
            "is a pure function of the request, and a boundary that stamped a "
            "per-call value into it would break the fixture contract (`CT-PROV-05`)"
        )
        assert (first.band, second.band) == ("emerging", "secure"), (
            f"the identical request landed {(first.band, second.band)!r} — the "
            "double's different-but-valid replies must BOTH be accepted: a "
            "different band on a re-run is the promised behaviour, not an error "
            "(CT-JUDGE-17)"
        )
    finally:
        store.close()


def test_tc_judge_c17_m_agg_reuses_by_work_id_and_merges_nothing_on_request_equality(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C17` limb 2 (`M-AGG` at rung 3, P0) — two full runs of the same
    world on ONE store: disjoint `work_id` sets over byte-identical renders, each
    run's verdicts its own, each run's aggregation reading its OWN band — and no
    caching decorator anywhere in `aeh.agg`."""
    provider = make_fixture_provider()
    store = open_store(tmp_data_dir)
    try:
        # The shared world, seeded ONCE: cohort, package, bands, documents. The two
        # runs differ in nothing but their run id — the address input.
        cohort_id = seed_cohort(store, _SUBMISSIONS)
        version = seed_package(store, [_C1_SPEC])
        add_bands(store, version, "C1", BANDS)
        seed_documents(store, _SUBMISSIONS)
        cfg = orch_cfg()
        orchestrator = Orchestrator(store)

        runs: dict[str, list[Any]] = {}
        for run_id, verdict_band in ((_RUN_A, "emerging"), (_RUN_B, "secure")):
            created = orchestrator.create_run(cohort_id, version, cfg, run_id=run_id)
            assert created == run_id, "fixture bug: the pinned run id was not used"
            orchestrator.enumerate_units(run_id)
            assert orchestrator.start(run_id) == "running", (
                f"fixture bug: {run_id} did not start"
            )
            drive_extract(orchestrator, store, provider)
            units = lease_score_units(orchestrator)
            assert units, (
                f"no score units leased for {run_id} — the run's units either "
                "never enumerated or were addressed as another run's work: a "
                "work_id not keyed on run_id collapses two runs of one world "
                "into a single address space (CT-JUDGE-17, FR-ORCH-01)"
            )
            refs_by_build = {ref.build_id: ref for ref in PANEL_REFS}
            transport = RecordingTransport(verdict_completion(
                verdict_band, 0.9, build_id=_JUDGE_BUILD, cited_spans=spans(),
            ))
            for unit in units:
                judge_ref = refs_by_build[unit.judge]
                worker = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
                    store, transport, judge_ref
                )
                request = worker.assemble(unit)
                result = worker.dispatch(request, judge_ref)
                worker.persist(unit, result)
            runs[run_id] = units
            assert len(transport.calls) == len(units), (
                f"fixture bug: {run_id} judged {len(units)} unit(s) in "
                f"{len(transport.calls)} call(s)"
            )

        # work_id is the reuse key: the two runs' score units are disjoint by id —
        # run_id is one of the id's nine inputs, so a second run of the same world
        # is NEW work, never a cache hit on the old.
        handle = store.cohort(ORCH_COHORT_ID)
        ids_by_run: dict[str, set[str]] = {}
        for run_id in (_RUN_A, _RUN_B):
            rows = handle.query(
                "SELECT work_id FROM work_unit WHERE run_id = :r AND stage = 'score'",
                r=run_id,
            )
            ids_by_run[run_id] = {row["work_id"] for row in rows}
        assert ids_by_run[_RUN_A] and ids_by_run[_RUN_B], (
            "fixture bug: a run carried no score units"
        )
        assert ids_by_run[_RUN_A].isdisjoint(ids_by_run[_RUN_B]), (
            "the two runs share a work_id — compute_work_id is not keyed on "
            "run_id, so a re-run would be addressed as the same work and a "
            "request-hash cache would serve the first run's verdicts forever "
            "(CT-JUDGE-17, FR-ORCH-01)"
        )

        # The renders are byte-identical while the ids differ: the prompt is a pure
        # function of the world — no run identity rides it — so request equality
        # holds across runs and CANNOT be the reuse key.
        fields_of_run: dict[str, list[tuple[str, str]]] = {}
        for run_id in (_RUN_A, _RUN_B):
            refs_by_build = {ref.build_id: ref for ref in PANEL_REFS}
            by_submission = {u.submission_id: u for u in runs[run_id]}
            unit = by_submission[_SUBMISSIONS[0]]
            judge_ref = refs_by_build[unit.judge]
            request = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
                store, None, judge_ref
            ).assemble(unit)
            payload = require(JUDGE_MODULE, "prompt_fields", issue=ISSUE)(request)
            fields_of_run[run_id] = list(payload.fields)
        assert fields_of_run[_RUN_A] == fields_of_run[_RUN_B], (
            "the two runs' renders differ — the render is not a pure function of "
            "the world, so the byte-identity this file's reuse argument rests on "
            "does not hold (CT-JUDGE-17, CT-JUDGE-08)"
        )

        # Nothing merged: each run's verdict rows carry its own band.
        for run_id, verdict_band in ((_RUN_A, "emerging"), (_RUN_B, "secure")):
            for submission_id in _SUBMISSIONS:
                rows = handle.query(
                    "SELECT v.band FROM verdict v JOIN work_unit w "
                    "ON w.work_id = v.work_id "
                    "WHERE w.run_id = :r AND w.submission_id = :s AND "
                    "w.criterion_id = 'C1'",
                    r=run_id, s=submission_id,
                )
                assert {row["band"] for row in rows} == {verdict_band}, (
                    f"{run_id}/{submission_id} carries "
                    f"{sorted({row['band'] for row in rows})} — a verdict crossed "
                    "runs: work was reused on request equality, the exact cache "
                    "the clause forbids (CT-JUDGE-17)"
                )

        # And the consumer reads its OWN run's verdicts: run A aggregates
        # "emerging", run B "secure", over identical requests.
        crit = criterion(criterion_bands(store, "C1"), criterion_id="C1")
        aggregate = require(AGG_MODULE, "aggregate", issue="#92")
        for run_id, verdict_band in ((_RUN_A, "emerging"), (_RUN_B, "secure")):
            score = aggregate(
                stored_verdicts(store, run_id, _SUBMISSIONS[0], "C1"),
                crit, signals(), config=agg_config(),
            )
            assert score.band == verdict_band, (
                f"{run_id}'s aggregate carries {score.band!r} on verdicts that "
                f"all read {verdict_band!r} — aggregation did not read its own "
                "run's verdicts, which is a merge across runs on request "
                "equality (CT-JUDGE-17)"
            )
            assert score.judge_count == 1 and score.state == "provisional_unreviewed", (
                f"{run_id}'s single-judge score reads judge_count="
                f"{score.judge_count}, state={score.state!r} — the consumer must "
                "stay honest about what it measured (CT-JUDGE-17, FR-AGG-07)"
            )

        # The artifact limb: nothing in `aeh.agg` carries a caching decorator —
        # the one shape a "same request, same answer" assumption takes in code.
        import aeh.agg

        parsed = ast.parse(
            Path(aeh.agg.__file__).read_text(encoding="utf-8")
        )

        def _decorator_name(decorator: Any) -> str | None:
            # The bare form (`@lru_cache`) is a Name; the parameterised form
            # (`@lru_cache(maxsize=None)`) is a Call around one — both count.
            if isinstance(decorator, ast.Call):
                decorator = decorator.func
            if isinstance(decorator, ast.Name):
                return decorator.id
            if isinstance(decorator, ast.Attribute):
                return decorator.attr
            return None

        _CACHE_DECORATORS = {"lru_cache", "cache", "cached_property"}
        decorated = []
        for node in ast.walk(parsed):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for decorator in node.decorator_list:
                    name = _decorator_name(decorator)
                    if name in _CACHE_DECORATORS:
                        decorated.append(f"{getattr(node, 'name', '?')}@{name}")
        assert decorated == [], (
            f"aeh.agg decorates {decorated} — a cached aggregate serves a stale "
            "figure on the assumption that an identical request owed an identical "
            "answer, and the verdicts it was computed from have already changed "
            "(CT-JUDGE-17)"
        )
        # Positive control: the scan flags the parameterised call form it must
        # catch (the shape a real memo ships with), not only the bare name.
        control = ast.parse(
            "from functools import lru_cache\n"
            "@lru_cache(maxsize=None)\n"
            "def cached_figure(x):\n"
            "    return x\n"
        )
        control_decorators = [
            _decorator_name(d) for node in ast.walk(control)
            if isinstance(node, ast.FunctionDef) for d in node.decorator_list
        ]
        assert control_decorators == ["lru_cache"], (
            "fixture bug: the agg decorator scan no longer detects the "
            "parameterised call form — the prohibition above would be vacuous"
        )
    finally:
        store.close()


@pytest.mark.writtenahead
def test_tc_judge_c17_m_stats_measures_self_agreement_as_a_finding_not_a_failure():
    """`TC-JUDGE-C17` limb 3 (`M-STATS`, `FR-STATS-16`, written ahead of `#116`) —
    self-agreement is MEASURED, and a measured value below 1.0 is a finding, not a
    failure: `run_mvvp` reports 0.71 and 0.62 verbatim inside its six steps, raises
    nothing, omits no judge, and offers no single pass/fail to absorb the finding."""
    run_mvvp = require(STATS_MODULE, "run_mvvp", issue="#116")

    # The call must NOT raise: a measured self-agreement below 1.0 is the finding
    # the protocol exists to surface, not an error (CT-JUDGE-17, FR-STATS-16).
    report = run_mvvp(
        assignment_type="extended_response",
        measured_self_agreement={"judge-a": 0.71, "judge-b": 0.62},
    )

    # The finding is REPORTED verbatim — the measured figure, not a clamped,
    # floor-ed or omitted value.
    for judge_id, measured in (("judge-a", 0.71), ("judge-b", 0.62)):
        paired = report.steps[5].paired_results[judge_id]
        assert paired.self_agreement == pytest.approx(measured), (
            f"{judge_id}'s measured self-agreement was reported as "
            f"{paired.self_agreement!r}, not the measured {measured!r} — a "
            "figure that was never measured anywhere (CT-JUDGE-17, FR-STATS-16)"
        )

    # And the report still offers six individually-reported steps with no single
    # verdict to flip the finding into a failure (the `CT-STATS-07` shape).
    assert set(report.steps) == set(vocab.MVVP_STEPS), (
        f"the report covers steps {sorted(report.steps)}; the six are "
        f"{sorted(vocab.MVVP_STEPS)}"
    )
    collapsed = [
        name
        for name in ("passed", "ok", "success", "verdict", "overall", "is_valid")
        if hasattr(report, name)
    ]
    assert collapsed == [], (
        f"the MVVP report offers {collapsed} — a single verdict is where a "
        "below-1.0 self-agreement would be silently absorbed as a pass/fail "
        "flip instead of the finding it is (CT-JUDGE-17)"
    )


@pytest.mark.writtenahead
def test_tc_judge_c17_m_conform_measures_repetition_and_requires_no_reproducibility():
    """`TC-JUDGE-C17` limb 4 (`M-CONFORM`, written ahead of `#134`) — the comparison
    method does not require verdict reproducibility: its divergence dimensions carry
    `self_agreement_over_repeated_runs` as a MEASURED rate, not as a boolean
    'reproduced' gate. A boolean would be the reproducibility requirement the clause
    forbids, wearing a metric's name."""
    # The discriminator first: `require()` reports whichever blocker it resolves
    # first, so this limb's registry entry (the `#134` one, keyed
    # `detect_build_substitution`) names the symbol the limb's FIRST door resolves —
    # `FR-CONFORM-08`, #134's alone. The constructor below resolves against #302's
    # build-only module; the `run()` the limb drives is #134's divergence machinery,
    # still a stub.
    require(CONFORM_MODULE, "detect_build_substitution", issue="#134")
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")
    report = build_suite().run(
        "v1",
        [edge_cfg(panel=EDGE_PANEL_3), hosted_cfg(panel=HOSTED_PANEL_3)],
        cohort=CohortRef(cohort_id="c-conform-fixtures", consent_class="synthetic"),
    )
    divergence = report.divergence

    # The repetition measure EXISTS — the comparison measures agreement over
    # repeated runs rather than demanding the repeats agree.
    value = divergence.dimensions[SELF_AGREEMENT_DIMENSION]
    assert value is not None, (
        f"{SELF_AGREEMENT_DIMENSION!r} is declared but unmeasured — a comparison "
        "that leaves repetition unmeasured has required nothing and measured "
        "nothing (CT-JUDGE-17; the no-unmeasured bet is `TC-CONFORM-C04`'s)"
    )
    # Its shape is a measurement, never a gate: True/False is 'reproduced?', which
    # is the determinism requirement CT-JUDGE-17 forbids.
    assert not isinstance(value, bool), (
        f"{SELF_AGREEMENT_DIMENSION} is {value!r} — a boolean is a 'reproduced' "
        "gate, and a gate on verdict reproducibility is the exact requirement "
        "CT-JUDGE-17 refuses to make (the rate may be low; the comparison still "
        "runs)"
    )


def test_tc_judge_c17_no_live_tier_artifact_pins_a_verdict_as_an_exact_match():
    """`TC-JUDGE-C17` limb 5 (plan step 5, rung 0, P0) — no golden file pins a
    verdict as an exact-match expectation in the live tier: the live-tier judge
    suites carry no data artifact, and no live-tier source asserts a verdict or band
    against a string literal with `==` (the exact-match shape). Positive controls
    prove both scans fire."""
    live_dir = Path(__file__).resolve().parents[2] / "security" / "judge"
    assert live_dir.is_dir(), "fixture bug: the live-tier judge directory moved"

    # Scan 1 — no golden-verdict data artifact in the live tier's own directory.
    data_files = sorted(
        p.relative_to(live_dir).as_posix()
        for p in live_dir.rglob("*")
        if p.is_file() and p.suffix in {".json", ".golden", ".expected"}
    )
    assert data_files == [], (
        f"the live-tier judge suites carry data file(s) {data_files} — a golden "
        "file there pins a live verdict as an exact-match expectation, and "
        "verdicts are not reproducible (`CT-JUDGE-17`): the suite would fail on "
        "the backend's legitimate variation and get edited until it lied"
    )

    # Scan 2 — no exact-match equality over a verdict or band in the live-tier
    # sources: `assert x.band == "secure"` is the pin, whatever the band.
    offenders: list[str] = []
    for source in sorted(live_dir.glob("test_*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for compare in ast.walk(tree):
            if not (isinstance(compare, ast.Compare)
                    and any(isinstance(op, ast.Eq) for op in compare.ops)):
                continue
            operands = [compare.left, *compare.comparators]
            for index, operand in enumerate(operands):
                if not (isinstance(operand, ast.Constant)
                        and isinstance(operand.value, str)):
                    continue
                others = [o for j, o in enumerate(operands) if j != index]
                if any(
                    "band" in ast.unparse(o).lower()
                    or "verdict" in ast.unparse(o).lower()
                    for o in others
                ):
                    offenders.append(f"{source.name}:{compare.lineno}")
    assert offenders == [], (
        f"the live tier pins a verdict with an exact-match equality at "
        f"{offenders} — a live verdict is not reproducible (`CT-JUDGE-17`); "
        "assert the invariant the suite actually owns (refusal, budget, prefix "
        "shape), never the band the backend happened to return"
    )

    # Positive controls: each scan flags its defect on synthetic fixtures.
    golden = live_dir / "_probe_ctrl.golden"
    try:
        golden.write_text('{"expected_band": "secure"}', encoding="utf-8")
        control_files = [
            p for p in live_dir.rglob("*")
            if p.is_file() and p.suffix in {".json", ".golden", ".expected"}
        ]
        assert control_files, (
            "fixture bug: the data-file scan no longer detects a golden file in "
            "the live tier — the prohibition above would be vacuous"
        )
    finally:
        golden.unlink(missing_ok=True)
    control = ast.parse(
        "assert result.band == 'secure'\n"
        "assert 'emerging' == verdict.band\n"
        "assert verdict.band != 'excellent'\n"  # not a pin: refusal-shaped, != stays legal
    )
    flagged = 0
    for compare in ast.walk(control):
        if not (isinstance(compare, ast.Compare)
                and any(isinstance(op, ast.Eq) for op in compare.ops)):
            continue
        operands = [compare.left, *compare.comparators]
        for index, operand in enumerate(operands):
            if isinstance(operand, ast.Constant) and isinstance(operand.value, str):
                others = [o for j, o in enumerate(operands) if j != index]
                if any("band" in ast.unparse(o).lower() for o in others):
                    flagged += 1
    assert flagged == 2, (
        f"fixture bug: the exact-match scan flagged {flagged} of its 2 controls — "
        "the prohibition above would be vacuous"
    )
