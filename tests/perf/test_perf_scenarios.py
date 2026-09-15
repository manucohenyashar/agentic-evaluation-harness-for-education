"""`TS-53` (issue #146) — the performance scenarios `PERF-01` to `PERF-09`: every scenario is held,
at the threshold §6.4 declares, in the environment §6.4 declares.

Test plan §6.4 defines one scenario per quantified NFR, and adds one rule: *"Every result names its
environment: a number from E1 or E3 is **not** evidence about E4."*

**Why this file is an index and not nine timing loops.** When this story was picked up, most
scenarios were already measured by the module stories' own performance cases, each written against
the same §6.4 row. A second timing loop per scenario would be two suites for one requirement, which
CLAUDE.md rules out. This story adds the pieces no module case had:

- `tests/perf/test_perf_04_prefix_cache_band.py`: ten minutes of batches against the historical band
  (E3, `live`).
- `tests/perf/test_perf_05_sustained_writes.py`: the 60-second paced run `TC-STORE-17` hands to
  `PERF-05`.
- `tests/perf/test_perf_06_zero_model_stages_full_run.py`: the full-run measurement `TC-INTEG-11`
  says belongs here (`e2e`).
- `docs/perf/PERF-01-*.md` and `docs/perf/PERF-02-*.md`: runbooks for the two E4-only scenarios,
  which no CI box can measure.

What *this* file checks, per scenario, is what can silently go wrong between a plan row and the
cases that claim it:

1. **The plan row is still the one the holders were written against.** The NFR and Env cells equal
   the registry's, and every threshold figure the holders pin still appears in the Threshold cell.
2. **Every holder exists and claims the scenario.** The file and the named test function are there,
   and the file cites the Perf ID.
3. **The threshold in code is the plan's.** Each holder's pinned figure is matched against its
   source: a budget constant edited from 5 ms to 50 ms fails here even though the timing case
   itself would go greener.
4. **The environment is honoured by the tier.** An E1 holder is not `live`. An E3 holder is `live`,
   so the fast and integration tiers never report a local-server number. An E4 scenario has its
   runbook, whose header equals the §6.4 row, with a blank measurement record.

`test_the_scenario_checks_catch_drift` is the positive control. `test_perf_04_historical_band_...`
exercises the band reader over a real store, since the live case that uses it cannot run here.

Markers: none. The index reads source files and runs in the fast tier. The issue's generic "a red
suite is the expected outcome" does not apply: the implementations the scenarios measure have
landed, and their cases run green.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_PLAN = REPO_ROOT / "docs" / "design" / "test-plan.md"
PERF_DOCS = REPO_ROOT / "docs" / "perf"

COLUMNS = ("Perf ID", "NFR", "Load profile", "Duration", "Dataset", "Metric", "Threshold", "Env")


@dataclass(frozen=True)
class Holder:
    """One test that holds (part of) a scenario, and the figures its source must pin."""

    path: str
    test: str
    pins: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scenario:
    perf_id: str
    nfr: str
    env: str
    #: Figures that must still appear in §6.4's Threshold cell (whitespace-normalised).
    threshold_figures: tuple[str, ...]
    holders: tuple[Holder, ...] = ()
    runbook: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


SCENARIOS: dict[str, Scenario] = {s.perf_id: s for s in (
    Scenario(
        "PERF-01", "NFR-ORCH-01, R10", "E4", ("~1.7 h", "recorded not asserted"),
        runbook="PERF-01-overnight-run.md",
    ),
    Scenario(
        "PERF-02", "NFR-INGEST-01", "E4", ("Same order of magnitude", "measured, not estimated"),
        holders=(
            Holder("tests/integration/ingest/test_ingest_telemetry_and_medium.py",
                   "test_tc_ingest_47_ingestion_wall_clock_over_the_full_cohort_shape_is_measured",
                   (r"refs = \[f\"s-\{index:04d\}\" for index in range\(350\)\]",)),
        ),
        runbook="PERF-02-cohort-ingestion.md",
    ),
    Scenario(
        "PERF-03", "NFR-ORCH-01", "E1", ("< 5 ms",),
        holders=(
            Holder("tests/integration/orch/test_perf_scheduling_overhead.py",
                   "test_tc_orch_30_scheduling_overhead_under_5ms_per_unit_at_23k",
                   (r"^BUDGET_MS_PER_UNIT = 5\.0$", r"<= BUDGET_MS_PER_UNIT|< BUDGET_MS_PER_UNIT")),
        ),
    ),
    Scenario(
        "PERF-04", "NFR-JUDGE-01, NFR-PROV-02", "E3", ("historical band", "build failure"),
        holders=(
            Holder("tests/integration/prov/test_prefix_cache_stability.py",
                   "test_tc_prov_22_the_invariant_prefix_is_not_reallocated_across_a_concurrent_batch",
                   (r'^CONCURRENCY = int\(os\.environ\.get\("HARNESS_PERF_CONCURRENCY", "32"\)\)$',)),
            Holder("tests/security/judge/test_tc_judge_21_prefix_efficiency.py",
                   "test_tc_judge_21_the_judge_batch_shares_its_prefix_across_concurrent_calls",
                   (r'^CONCURRENCY = int\(os\.environ\.get\("HARNESS_PERF_CONCURRENCY", "32"\)\)$',)),
            Holder("tests/perf/test_perf_04_prefix_cache_band.py",
                   "test_perf_04_prefix_cache_is_high_stable_and_inside_its_historical_band_for_ten_minutes",
                   (r'^DURATION_S = int\(os\.environ\.get\("HARNESS_PERF_04_SECONDS", "600"\)\)$',
                    r'^CONCURRENCY = int\(os\.environ\.get\("HARNESS_PERF_CONCURRENCY", "32"\)\)$',
                    r"^SUBMISSIONS = 350$")),
        ),
    ),
    Scenario(
        "PERF-05", "NFR-STORE-01", "E1", ("≥ 200/s", "no queue growth"),
        holders=(
            Holder("tests/integration/store/test_capacity.py",
                   "test_tc_store_17_two_hundred_write_units_per_second_sustained",
                   (r"^RATE_FLOOR = 200\b", r"assert rate >= RATE_FLOOR,")),
            Holder("tests/perf/test_perf_05_sustained_writes.py",
                   "test_perf_05_two_hundred_write_units_per_second_for_a_minute_with_no_queue_growth",
                   (r"^RATE_FLOOR = 200$", r"^OFFERED_RATE = RATE_FLOOR$",
                    r"if committed_in_window < sent - COMMIT_BATCH:",
                    r"if late > early \+ COMMIT_BATCH:",
                    r'^DURATION_S = int\(os\.environ\.get\("HARNESS_PERF_05_SECONDS", "60"\)\)$')),
        ),
    ),
    Scenario(
        "PERF-06", "NFR-INTEG-01, NFR-AGG-03, NFR-DET-01", "E1",
        ("< 1% of run wall clock", "microseconds each", "< 5 s"),
        holders=(
            Holder("tests/perf/test_perf_06_zero_model_stages_full_run.py",
                   "test_perf_06_zero_model_stages_stay_inside_their_budgets_in_a_full_run",
                   (r"^INTEGRITY_SHARE_CEILING = 0\.01$",
                    r"^AGGREGATION_PER_CALL_CEILING_S = 0\.001$",
                    r"^DETERMINISTIC_PASS_CEILING_S = 5\.0$",
                    r"^COHORT_SIZE = 350$",
                    r"if gate_seconds >= INTEGRITY_SHARE_CEILING \* run_seconds:",
                    r"if per_call >= AGGREGATION_PER_CALL_CEILING_S:",
                    r"if deterministic\.total >= DETERMINISTIC_PASS_CEILING_S:")),
            Holder("tests/integration/integ/test_integ_perf.py",
                   "test_tc_integ_11_verification_adds_under_one_percent_to_wall_clock",
                   (r"^_DIFFERENTIAL_BUDGET = 1\.01\b",
                    r"assert enabled <= disabled \* _DIFFERENTIAL_BUDGET,")),
            Holder("tests/unit/agg/test_aggregation_perf.py",
                   "test_tc_agg_20_five_thousand_two_hundred_fifty_aggregations_add_negligible_wall_clock",
                   (r"^_PER_CALL_CEILING_SECONDS = 0\.001\b", r"assert per_call < _PER_CALL_CEILING_SECONDS,")),
            Holder("tests/integration/det/test_det_key_change.py",
                   "test_tc_det_11_all_deterministic_criteria_350_students_one_pass_under_budget",
                   (r"^_COHORT_SIZE = 350$", r"assert elapsed < 5\.0,")),
        ),
    ),
    Scenario(
        "PERF-07", "NFR-GRADE-03", "E1", ("< 30 s", "zero model calls"),
        holders=(
            Holder("tests/integration/grade/test_perf_grade_scale.py",
                   "test_tc_grade_20_grading_and_rollup_for_350_submissions_under_30s",
                   (r"^BUDGET_S = 30\.0$", r"< BUDGET_S\b", r'^_SUBMISSIONS = tuple\(f"S\{i:03d\}" for i in range\(1, 351\)\)$')),
        ),
    ),
    Scenario(
        "PERF-08", "NFR-REVIEW-01, NFR-CONSOLE-01", "E1", ("Queue < 2 s", "rollup < 3 s"),
        holders=(
            Holder("tests/contract/review/test_tc_review_18_build_and_render.py",
                   "test_tc_review_18_the_queue_builds_and_renders_within_two_seconds_at_the_stated_load",
                   (r"assert elapsed < vocab\.QUEUE_BUILD_SECONDS,",
                    r"flagged_population\(vocab\.PERF_FLAGGED_ITEMS")),
            Holder("tests/support/review_vocabulary.py", "",
                   (r"^QUEUE_BUILD_SECONDS = 2\.0$", r"^PERF_STUDENTS = 350$",
                    r"^PERF_FLAGGED_ITEMS = 800$")),
            Holder("tests/integration/console/test_console_render_budget_350.py",
                   "test_tc_console_33_queue_and_rollup_render_within_budget_for_a_350_student_run",
                   (r"^FLAGGED_ITEMS = 800$",
                    r"if queue_seconds >= REVIEW_QUEUE_BUDGET_SECONDS:",
                    r"if rollup_seconds >= ROLLUP_BUDGET_SECONDS:")),
            Holder("tests/support/console_vocabulary.py", "",
                   (r"^REVIEW_QUEUE_BUDGET_SECONDS = 2\.0$", r"^ROLLUP_BUDGET_SECONDS = 3\.0$",
                    r"^REFERENCE_COHORT_SIZE = 350$")),
        ),
    ),
    Scenario(
        "PERF-09", "NFR-ORCH-06, NFR-STORE-06", "E1", ("40,000", "< 500 MB"),
        holders=(
            Holder("tests/integration/orch/test_ledger_capacity.py",
                   "test_tc_orch_33_lease_and_complete_at_23k_and_40k_without_degradation",
                   (r"assert _SIZES\[0\]\[1\] >= 23000 and _SIZES\[1\]\[1\] >= 40000",
                    r"assert footprint_mb < 500,")),
        ),
    ),
)}


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _norm(text: str) -> str:
    return " ".join(text.split())


def plan_rows() -> dict[str, dict[str, str]]:
    """§6.4's table, keyed by Perf ID, parsed from the plan."""
    text = TEST_PLAN.read_text(encoding="utf-8")
    start = text.index("### 6.4 Performance scenarios")
    body = text[start: text.index("\n### ", start + 1)]
    lines = [line for line in body.splitlines() if line.startswith("|")]
    assert tuple(_cells(lines[0])) == COLUMNS, f"§6.4's columns changed: {_cells(lines[0])!r}"
    rows = {}
    for line in lines[2:]:
        cells = _cells(line)
        assert len(cells) == len(COLUMNS), f"§6.4 row does not split into 8 cells: {line[:80]!r}"
        rows[cells[0]] = dict(zip(COLUMNS, cells))
    return rows


def _markers(source: str) -> set[str]:
    """The module-level `pytestmark` marker names of a test file."""
    names: set[str] = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
        ):
            for attr in ast.walk(node.value):
                if isinstance(attr, ast.Attribute) and isinstance(attr.value, ast.Attribute) \
                        and attr.value.attr == "mark":
                    names.add(attr.attr)
    return names


def _functions(source: str) -> set[str]:
    return {node.name for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}


def _function_markers(source: str, name: str) -> set[str]:
    """The `@pytest.mark.<name>` decorators on one test function."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            found = set()
            for decorator in node.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Attribute) \
                        and target.value.attr == "mark":
                    found.add(target.attr)
            return found
    return set()


def problems_with(scenario: Scenario, row: dict[str, str],
                  sources: dict[str, str], runbook_text: str | None) -> list[str]:
    """Everything that stops `scenario` being held as §6.4 declares it."""
    problems: list[str] = []
    if _norm(row["NFR"]) != _norm(scenario.nfr):
        problems.append(f"§6.4's NFR cell is {row['NFR']!r}; the holders were written for "
                        f"{scenario.nfr!r}")
    env = re.match(r"\**(E\d)", row["Env"])
    if env is None or env.group(1) != scenario.env:
        problems.append(f"§6.4's Env cell is {row['Env']!r}; the holders run on {scenario.env}")
    for figure in scenario.threshold_figures:
        if _norm(figure) not in _norm(row["Threshold"]).replace("**", ""):
            problems.append(f"§6.4's Threshold no longer states {figure!r}: {row['Threshold']!r}")

    for holder in scenario.holders:
        source = sources.get(holder.path)
        if source is None:
            problems.append(f"{holder.path} does not exist")
            continue
        if holder.test:
            if holder.test not in _functions(source):
                problems.append(f"{holder.path} has no test {holder.test}")
            if scenario.perf_id not in source:
                problems.append(f"{holder.path} does not cite {scenario.perf_id}")
            markers = _markers(source) | _function_markers(source, holder.test)
            if scenario.env == "E3" and "live" not in markers:
                problems.append(f"{holder.path} holds an E3 scenario but is not marked live, so a "
                                f"non-E3 tier would report its number")
            if scenario.env != "E3" and "live" in markers:
                problems.append(f"{holder.path} holds an {scenario.env} scenario but is marked live")
        for pin in holder.pins:
            if not re.search(pin, source, re.M):
                problems.append(f"{holder.path} no longer pins {pin!r}: the threshold in code has "
                                f"moved away from §6.4's")

    if scenario.env == "E4":
        if runbook_text is None:
            problems.append(f"{scenario.perf_id} is E4-only and has no runbook in docs/perf/")
        else:
            header = {}
            for line in runbook_text.split("\n## ")[0].splitlines()[2:]:
                if line.startswith("|") and not line.startswith("|---"):
                    cells = _cells(line)
                    header[cells[0]] = cells[1] if len(cells) > 1 else ""
            header.pop("Field", None)
            if tuple(header) != COLUMNS:
                problems.append(f"the runbook's header fields are {tuple(header)!r}")
            for column in COLUMNS:
                if _norm(header.get(column, "")) != _norm(row[column]):
                    problems.append(f"the runbook's {column!r} drifted from §6.4")
            record = runbook_text.split("## Measurement record", 1)
            rows = [_cells(line) for line in record[-1].split("\n## ")[0].splitlines()
                    if line.startswith("|")][2:] if len(record) == 2 else []
            if not any(r[0] == "Verdict" for r in rows):
                problems.append("the runbook has no measurement record with a Verdict row")
            filled = [r[0] for r in rows if len(r) > 1 and r[1]]
            if filled:
                problems.append(f"the committed runbook carries measurements {filled!r}; record "
                                f"them in a copy")
    elif runbook_text is not None:
        problems.append(f"{scenario.perf_id} runs on {scenario.env} but has an E4 runbook")
    return problems


def _check(perf_id: str) -> None:
    scenario = SCENARIOS[perf_id]
    row = plan_rows().get(perf_id)
    assert row is not None, f"§6.4 has no {perf_id} row"
    sources = {h.path: (REPO_ROOT / h.path).read_text(encoding="utf-8")
               for h in scenario.holders if (REPO_ROOT / h.path).exists()}
    runbooks = sorted(PERF_DOCS.glob(f"{perf_id}-*.md"))
    runbook_text = runbooks[0].read_text(encoding="utf-8") if runbooks else None
    problems = problems_with(scenario, row, sources, runbook_text)
    assert not problems, f"{perf_id}:\n- " + "\n- ".join(problems)


def test_perf_01_full_uniform_depth_run_is_held_by_its_e4_runbook():
    _check("PERF-01")


def test_perf_02_cohort_ingestion_is_held_by_its_e4_runbook_and_the_e1_shape_case():
    _check("PERF-02")


def test_perf_03_scheduling_overhead_is_held_at_five_ms_per_unit():
    _check("PERF-03")


def test_perf_04_prefix_cache_is_held_on_e3_by_live_cases_only():
    _check("PERF-04")


def test_perf_05_sustained_writes_are_held_at_two_hundred_per_second():
    _check("PERF-05")


def test_perf_06_zero_model_stages_are_held_in_a_full_run_and_per_stage():
    _check("PERF-06")


def test_perf_07_grading_and_rollup_are_held_at_thirty_seconds():
    _check("PERF-07")


def test_perf_08_queue_and_rollup_render_are_held_at_two_and_three_seconds():
    _check("PERF-08")


def test_perf_09_ledger_volume_and_footprint_are_held_at_forty_thousand_and_500_mb():
    _check("PERF-09")


def test_every_performance_scenario_in_the_plan_is_registered():
    """§6.4's PERF-01..09 are all registered here; PERF-10 is TS-54's (#147), not this story's."""
    assert set(plan_rows()) - {"PERF-10"} == set(SCENARIOS)
    readme = (PERF_DOCS / "README.md").read_text(encoding="utf-8")
    missing = [perf_id for perf_id in SCENARIOS if f"| {perf_id} " not in readme]
    assert not missing, f"docs/perf/README.md does not index {missing}"


def test_the_scenario_checks_catch_drift():
    """Positive control: each mutation of real inputs must be reported."""
    rows = plan_rows()

    def run(perf_id, *, row=None, source_edit=None, runbook_edit=None):
        scenario = SCENARIOS[perf_id]
        sources = {h.path: (REPO_ROOT / h.path).read_text(encoding="utf-8")
                   for h in scenario.holders}
        if source_edit:
            path, old, new = source_edit
            assert old in sources[path], f"control fixture: {old!r} not in {path}"
            sources[path] = sources[path].replace(old, new)
        runbooks = sorted(PERF_DOCS.glob(f"{perf_id}-*.md"))
        text = runbooks[0].read_text(encoding="utf-8") if runbooks else None
        if runbook_edit:
            assert runbook_edit[0] in text, f"control fixture: {runbook_edit[0]!r} not in runbook"
            text = text.replace(*runbook_edit)
        return problems_with(scenario, row or rows[perf_id], sources, text)

    assert run("PERF-03") == [] and run("PERF-01") == [] and run("PERF-04") == []
    mutations = {
        "a loosened budget": run("PERF-03", source_edit=(
            "tests/integration/orch/test_perf_scheduling_overhead.py",
            "BUDGET_MS_PER_UNIT = 5.0", "BUDGET_MS_PER_UNIT = 50.0")),
        "an E3 case dropped from live": run("PERF-04", source_edit=(
            "tests/perf/test_perf_04_prefix_cache_band.py",
            "pytestmark = [pytest.mark.live, pytest.mark.slow, pytest.mark.integration]",
            "pytestmark = [pytest.mark.slow, pytest.mark.integration]")),
        "a weakened comparison": run("PERF-06", source_edit=(
            "tests/perf/test_perf_06_zero_model_stages_full_run.py",
            "if gate_seconds >= INTEGRITY_SHARE_CEILING * run_seconds:",
            "if gate_seconds >= 0.5 * run_seconds:")),
        "a loosened call site": run("PERF-08", source_edit=(
            "tests/integration/console/test_console_render_budget_350.py",
            "if queue_seconds >= REVIEW_QUEUE_BUDGET_SECONDS:",
            "if queue_seconds >= 20.0:")),
        "an E1 case marked live on the function": run("PERF-03", source_edit=(
            "tests/integration/orch/test_perf_scheduling_overhead.py",
            "def test_tc_orch_30_", "@pytest.mark.live\ndef test_tc_orch_30_")),
        "a renamed holder test": run("PERF-07", source_edit=(
            "tests/integration/grade/test_perf_grade_scale.py",
            "def test_tc_grade_20_", "def test_tc_grade_21_")),
        "a plan row moved to E3": run("PERF-05", row=dict(rows["PERF-05"], Env="E3")),
        "a plan threshold changed": run("PERF-08", row=dict(
            rows["PERF-08"], Threshold="Queue < 5 s, rollup < 3 s")),
        "a runbook header drifted": run("PERF-01", runbook_edit=(
            "| Env | E4 |", "| Env | E3 |")),
        "a filled runbook record": run("PERF-02", runbook_edit=(
            "| Verdict |  |", "| Verdict | pass |")),
    }
    missed = [name for name, problems in mutations.items() if not problems]
    assert not missed, f"the checks missed: {missed}"


def test_perf_04_historical_band_is_read_from_run_metrics(tmp_data_dir):
    """The band reader the live `PERF-04` case uses, over a real store: only the scenario's own
    history counts (a real run's `cache_hit_rate` does not), three earlier runs give a floor of
    mean − 3σ, fewer than three give no band, and the floor never drops below the absolute one."""
    import statistics

    import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ  # noqa: E401,F401
    import aeh.judge, aeh.pkg, aeh.review, aeh.synth  # noqa: E401,F401
    from aeh.orch import Orchestrator
    from aeh.store import open_store
    from tests.perf.test_perf_04_prefix_cache_band import (
        HISTORY_METRIC,
        MIN_CACHE_HIT_RATE,
        historical_band,
        record_history,
    )

    assert historical_band(None) == (None, [])
    store = open_store(tmp_data_dir)
    try:
        orchestrator = Orchestrator(store)
        orchestrator.record_run_metrics("r-1", {HISTORY_METRIC: 0.82, "cache_hit_rate": 0.1})
        orchestrator.record_run_metrics("r-2", {HISTORY_METRIC: 0.84})
        orchestrator.record_run_metrics("real-run", {"cache_hit_rate": 0.2})
    finally:
        store.close()
    assert historical_band(str(tmp_data_dir)) == (None, [0.82, 0.84])

    store = open_store(tmp_data_dir)
    try:
        Orchestrator(store).record_run_metrics("r-3", {HISTORY_METRIC: 0.80})
    finally:
        store.close()
    floor, history = historical_band(str(tmp_data_dir))
    assert sorted(history) == [0.80, 0.82, 0.84]
    assert floor == pytest.approx(statistics.mean(history) - 3 * statistics.pstdev(history))

    # A noisy history cannot produce a band that never fires, and a run records itself.
    record_history(str(tmp_data_dir), 0.1)
    floor, history = historical_band(str(tmp_data_dir))
    assert len(history) == 4 and floor == MIN_CACHE_HIT_RATE
