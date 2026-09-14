"""`TS-55` (issue #148) — the observability and alert-rule cases `OBS-01` to `OBS-11`: every
promised signal and alert is held by a case that asserts it.

Test plan §6.10. As with TS-53, most `OBS-*` rows were already implemented by the module stories'
observability cases, each written against the same row (`TC-INGEST-44`, `TC-STORE-24`,
`TC-ORCH-35`/`-36`, `TC-INTEG-14`, `TC-JUDGE-C16`, `TC-DET-14`/`-C08`, `TC-GRADE-24`, `TC-STATS-26`,
`TC-CONF-17`, `TC-REVIEW-23`/`-17`, `TC-CONSOLE-C22`). A second suite per signal would be two suites
for one requirement. This story adds:

- **`OBS-10`'s run-start case** (`tests/integration/obs/test_obs_10_run_start_line.py`).
  `TC-CONF-17` compares the two serializers with the test as the caller, so it cannot see that no
  run start emits the line.
- **This index**, one test per `OBS-*` ID, checking for each row:
  1. §6.10's Req cell is the one the holders were written against.
  2. Every holder file and test function exists, and the file cites the `OBS-*` ID or its own case ID.
  3. Where a row lists signals, the holder's *code* names them. The source is read with
     docstrings and comments stripped, so a renamed or dropped signal fails here rather than
     surviving in prose. Rows with no listed signals get the existence check only.
  4. A holder that is `writtenahead` is registered in `WRITTEN_AHEAD_BLOCKERS`
     (`tests/support/impl.py`). A red holder with no registered blocker is a case the gate never
     announces.
  5. A row part no case can hold yet is listed in `GAPS` with its reason, and the PR reports it. The
     index does not claim coverage for it.

Markers: none. The index reads source files and runs in the fast tier.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_PLAN = REPO_ROOT / "docs" / "design" / "test-plan.md"
IMPL = REPO_ROOT / "tests" / "support" / "impl.py"
COLUMNS = ("ID", "Req", "Promised signal", "Trigger", "Assertion")


@dataclass(frozen=True)
class Holder:
    path: str
    tests: tuple[str, ...]
    case: str
    signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class Row:
    obs_id: str
    req: str
    holders: tuple[Holder, ...]


ROWS: dict[str, Row] = {r.obs_id: r for r in (
    Row("OBS-01", "FR-INGEST-29", (
        Holder("tests/integration/ingest/test_ingest_telemetry_and_medium.py",
               ("test_tc_ingest_44_the_recorded_run_carries_exact_names_and_hand_computed_gate_counts",),
               "TC-INGEST-44", ("ocr_failure_rate", "unresolved_mark_rate", "text_layer_divergence")),
    )),
    Row("OBS-02", "FR-STORE-05", (
        Holder("tests/integration/store/test_observability.py",
               ("test_tc_store_24_every_named_signal_is_emitted_and_the_free_disk_alert_fires",),
               "TC-STORE-24", ("write_queue_depth", "free_disk")),
    )),
    Row("OBS-03", "FR-ORCH-23", (
        Holder("tests/integration/orch/test_run_metrics_signal_presence.py",
               ("test_tc_orch_35_run_metrics_carries_every_ct_orch_20_signal",),
               "TC-ORCH-35", ("cache_hit_rate", "('peak',)", "('swap',)")),
    )),
    Row("OBS-04", "FR-PROV-12, NFR-JUDGE-01", (
        Holder("tests/integration/orch/test_alert_rules.py",
               ("test_tc_orch_36_cache_hit_rate_collapse_fires_alone",), "TC-ORCH-36",
               ("cache_hit_rate",)),
        Holder("tests/artifact/test_scoring_isolation.py", (), "OBS-04"),
    )),
    Row("OBS-05", "FR-ORCH-14, FR-ORCH-15", (
        Holder("tests/integration/orch/test_alert_rules.py", (
            "test_tc_orch_36_escalation_rate_above_budget_fires_alone",
            "test_tc_orch_36_tripped_criterion_breaker_fires_alone",
            "test_tc_orch_36_cost_within_10pct_of_ceiling_fires_alone",
            "test_tc_orch_36_cache_hit_rate_collapse_fires_alone",
            "test_tc_orch_36_any_pause_fires_alone",
            "test_tc_orch_36_the_five_conditions_fire_distinct_alerts"), "TC-ORCH-36"),
    )),
    Row("OBS-06", "FR-INTEG-08", (
        Holder("tests/integration/integ/test_integ_observability.py", (
            "test_tc_integ_14_verification_failure_rate_matches_the_injected_rate",
            "test_tc_integ_14_all_six_rates_are_emitted_per_criterion",
            "test_tc_integ_14_alert_fires_above_threshold_and_not_below"), "TC-INTEG-14"),
    )),
    Row("OBS-07", "FR-JUDGE-11, FR-AGG-11", (
        Holder("tests/contract/judge/test_ct_judge_c16_signal_dimensionality.py",
               ("test_tc_judge_c16_the_six_signals_are_emitted_per_criterion_and_per_judge",),
               "TC-JUDGE-C16"),
    )),
    Row("OBS-08", "FR-DET-07", (
        Holder("tests/integration/det/test_det_queue_and_signals.py",
               ("test_tc_det_14_elevated_unresolved_count_alerts_as_a_scanning_problem",),
               "TC-DET-14", ("scanning",)),
        Holder("tests/contract/det/test_ct_det_item_stats.py",
               ("test_tc_det_c08_exact_counts_against_a_hand_built_fixture",), "TC-DET-C08"),
    )),
    Row("OBS-09", "FR-GRADE-04, FR-STATS-11", (
        Holder("tests/integration/grade/test_grade_observability.py",
               ("test_tc_grade_24_the_grading_stage_emits_every_signal_and_fires_the_alert",),
               "TC-GRADE-24", ("('boundary',)", "incomplete")),
        Holder("tests/integration/stats/test_administration_records.py",
               ("test_tc_stats_26_the_four_counters_are_emitted_over_the_real_store",
                "test_tc_stats_26_both_alerts_fire_with_their_exact_detail"), "TC-STATS-26"),
    )),
    Row("OBS-10", "FR-CONF-09, NFR-SYS-11", (
        Holder("tests/integration/obs/test_obs_10_run_start_line.py", (
            "test_obs_10_a_run_start_emits_one_credential_free_line_identical_to_the_audit_record",
            "test_obs_10_control_the_capture_sees_a_run_start_line_when_one_is_emitted"),
            "OBS-10", ("profile_summary",)),
        Holder("tests/integration/conf/test_audit_record.py",
               ("test_tc_conf_17_the_stored_profile_summary_matches_the_one_logged_at_run_start",),
               "TC-CONF-17", ("profile_summary",)),
    )),
    Row("OBS-11", "FR-REVIEW-16, FR-CONSOLE-06", (
        Holder("tests/contract/review/test_tc_review_observability_two_administrations.py",
               ("test_tc_review_23_all_eight_counters_carry_the_exact_figures_in_both_administrations",),
               "TC-REVIEW-23"),
        Holder("tests/contract/review/test_tc_review_17_review_seconds_accumulate.py",
               ("test_tc_review_17_est_seconds_is_recorded_per_item_and_is_what_the_budget_spends",),
               "TC-REVIEW-17"),
        Holder("tests/contract/console/test_ct_console_observability_and_honesty.py",
               ("test_tc_console_c22_skip_rates_are_emitted_per_setup_step_not_in_aggregate",),
               "CT-CONSOLE-22", ("SKIP_RATE_METRIC",)),
    )),
)}

#: Row parts no case holds yet, and why. Reported on the PR; never counted as coverage.
GAPS: dict[str, str] = {
    "OBS-03": "no case runs a model swap, and swap count/duration, peak concurrency, wall clock, "
              "retries, escalated units and both costs are checked for presence by name only; "
              "TC-ORCH-35 hand-counts total and quarantined units, tokens, rate-limited calls and "
              "the cache_hit_rate range",
    "OBS-04": "the collapse under deliberately broken prompt ordering is a live measurement (the "
              "rate only moves against a real prefix cache, E3, PERF-04/TC-PROV-22); the fast "
              "tier holds the ordering invariant and TC-ORCH-36 the alert on a collapse",
    "OBS-07": "the per-criterion half (band_spread distribution, ordinal alpha, escalation and "
              "auto-accept rates, hard-cap counts) and the 'caps firing at an unusual rate on one "
              "criterion' alert have no emitting surface named in the design and none in src/; "
              "only the per-(criterion, judge) half has a registered case (TC-JUDGE-C16), and "
              "that case checks the signals' keying and names only: no case injects contract "
              "violations on one judge or asserts the concentrated-violation alert",
    "OBS-10": "red when written: nothing in src/ calls aeh.conf.log_run_start, so a run start "
              "emits no line (a defect to file through /plan-to-issues)",
}


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def plan_rows() -> dict[str, dict[str, str]]:
    text = TEST_PLAN.read_text(encoding="utf-8")
    rows = {}
    for line in text.splitlines():
        if re.match(r"^\| OBS-\d\d \|", line):
            cells = _cells(line)
            if len(cells) == len(COLUMNS):
                rows[cells[0]] = dict(zip(COLUMNS, cells))
    return rows


def _code(source: str) -> str:
    """The module's code with docstrings and comments removed."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(getattr(body[0], "value", None), ast.Constant) \
                and isinstance(body[0].value.value, str):
            body[0] = ast.Pass()
    return ast.unparse(tree)


def _markers(source: str) -> set[str]:
    names = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            for attr in ast.walk(node.value):
                if isinstance(attr, ast.Attribute) and isinstance(attr.value, ast.Attribute) \
                        and attr.value.attr == "mark":
                    names.add(attr.attr)
    return names


def problems_with(row: Row, plan: dict[str, str] | None, sources: dict[str, str],
                  impl_text: str) -> list[str]:
    problems = []
    if plan is None:
        return [f"§6.10 has no {row.obs_id} row"]
    if " ".join(plan["Req"].split()) != row.req:
        problems.append(f"§6.10's Req is {plan['Req']!r}; the holders were written for {row.req!r}")
    for holder in row.holders:
        source = sources.get(holder.path)
        if source is None:
            problems.append(f"{holder.path} does not exist")
            continue
        functions = {n.name for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
        for test in holder.tests:
            if test not in functions:
                problems.append(f"{holder.path} has no test {test}")
        if holder.case not in source:
            problems.append(f"{holder.path} does not cite {holder.case}")
        code = _code(source) if holder.signals else ""
        for signal in holder.signals:
            if signal not in code:
                problems.append(f"{holder.path} no longer names the promised signal {signal!r}")
        if "writtenahead" in _markers(source) and holder.path not in impl_text:
            problems.append(f"{holder.path} is writtenahead but not registered in "
                            f"WRITTEN_AHEAD_BLOCKERS")
    return problems


def _check(obs_id: str) -> None:
    row = ROWS[obs_id]
    sources = {h.path: (REPO_ROOT / h.path).read_text(encoding="utf-8")
               for h in row.holders if (REPO_ROOT / h.path).exists()}
    problems = problems_with(row, plan_rows().get(obs_id), sources,
                             IMPL.read_text(encoding="utf-8"))
    if obs_id in GAPS:
        print(f"{obs_id} gap (not counted as coverage): {GAPS[obs_id]}")
    assert not problems, f"{obs_id}:\n- " + "\n- ".join(problems)


def test_obs_01_ingest_signals_are_held():
    _check("OBS-01")


def test_obs_02_store_signals_and_free_disk_alert_are_held():
    _check("OBS-02")


def test_obs_03_run_metrics_are_held():
    _check("OBS-03")


def test_obs_04_cache_hit_rate_collapse_alert_is_held():
    _check("OBS-04")


def test_obs_05_the_five_orchestrator_alerts_are_held():
    _check("OBS-05")


def test_obs_06_integrity_rates_and_alert_are_held():
    _check("OBS-06")


def test_obs_07_judge_signals_are_held_and_the_criterion_half_is_a_declared_gap():
    _check("OBS-07")


def test_obs_08_deterministic_item_signals_and_scanning_alert_are_held():
    _check("OBS-08")


def test_obs_09_grade_and_validation_alerts_are_held():
    _check("OBS-09")


def test_obs_10_run_start_line_is_held():
    _check("OBS-10")


def test_obs_11_review_and_setup_telemetry_is_held():
    _check("OBS-11")


def test_every_obs_row_is_indexed():
    assert set(plan_rows()) == set(ROWS), set(plan_rows()) ^ set(ROWS)


def test_the_obs_checks_catch_drift():
    """Positive control: each mutation of real inputs must be reported."""
    impl = IMPL.read_text(encoding="utf-8")

    def run(obs_id, *, edit=None, plan_edit=None, impl_text=impl):
        row = ROWS[obs_id]
        sources = {h.path: (REPO_ROOT / h.path).read_text(encoding="utf-8") for h in row.holders}
        if edit:
            path, old, new = edit
            assert old in sources[path], f"control fixture: {old!r} not in {path}"
            sources[path] = sources[path].replace(old, new)
        plan = dict(plan_rows()[obs_id], **(plan_edit or {}))
        return problems_with(row, plan, sources, impl_text)

    assert run("OBS-01") == [] and run("OBS-05") == []
    alert_rules = "tests/integration/orch/test_alert_rules.py"
    mutations = {
        "a renamed signal": run("OBS-01", edit=(
            "tests/integration/ingest/test_ingest_telemetry_and_medium.py",
            "unresolved_mark_rate", "unresolved_rate")),
        "a deleted alert case": run("OBS-05", edit=(
            alert_rules, "def test_tc_orch_36_any_pause_fires_alone", "def _dropped")),
        "an unregistered writtenahead holder": run(
            "OBS-05", impl_text=impl.replace(alert_rules, "tests/elsewhere.py")),
        "a changed plan row": run("OBS-09", plan_edit={"Req": "FR-GRADE-04"}),
        "a second renamed signal": run("OBS-01", edit=(
            "tests/integration/ingest/test_ingest_telemetry_and_medium.py",
            "text_layer_divergence", "tld_renamed")),
    }
    missed = [name for name, problems in mutations.items() if not problems]
    assert not missed, f"the checks missed: {missed}"
