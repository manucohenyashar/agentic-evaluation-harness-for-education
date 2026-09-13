"""`TS-54` (issue #147) — the `NFR-SYS-05` acceptance-gate runbook, the air-gapped run, and the
restart measurement: `PERF-10`, `RES-17`, `RES-18`.

Test plan §8.2 marks TS-54 **authoring only**. Its deliverable is the written procedure, which
*executes at release rather than in CI*. `PERF-10` needs the E4 reference machine and consented
real student work, and `RES-17` needs a host with its network interfaces removed. Neither can run
here, so each lands as a runbook under `docs/perf/`. `RES-18` is the exception: §6.8 says it is
*"measured on E1 and confirmed once on E4 during PERF-10"*. The E1 half is a real test,
`tests/resilience/test_res_18_restart_rpo_rto.py`, and the E4 half is a row in `PERF-10`'s record.

What these tests check is what can go wrong between the plan and the procedures in CI:

- **`PERF-10`.** The runbook's header equals §6.4's row word for word. Its gate table has exactly
  ten rows, in the order of the ten sub-criteria in the row's Metric cell, each carrying that
  sub-criterion's wording. "All ten sub-criteria met" cannot quietly become nine. The sign-off
  record has RES-18's RTO and RPO rows. Every measurement cell is blank.
- **`RES-17`.** The runbook's header equals §6.8's row. The procedure runs §4.7's air-gapped command
  and requires networking off at the host, not a firewall rule. The record is blank.
- **`RES-18`.** The E1 test exists, cites the ID, is not `live`, and pins `NFR-SYS-02`'s 5 s and
  60 s thresholds where they are defined and where they are compared.

`test_the_release_gate_checks_catch_drift` is the positive control. Markers: none, because these
read files and run in the fast tier. The issue's generic "a red suite is the expected outcome" is
overridden by its authoring-only note ("red-by-construction **or as documentation**").
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_PLAN = REPO_ROOT / "docs" / "design" / "test-plan.md"
PERF_DOCS = REPO_ROOT / "docs" / "perf"
RES_18_TEST = "tests/resilience/test_res_18_restart_rpo_rto.py"
ORCH_SOURCE = REPO_ROOT / "src" / "aeh" / "orch.py"


def run_metric_names() -> set[str]:
    """The metric names `M-ORCH` actually writes to `run_metrics` (`_flush_run_metrics`)."""
    source = ORCH_SOURCE.read_text(encoding="utf-8")
    start = source.index("    def _flush_run_metrics(")
    body = source[start: source.index("\n    def ", start + 1)]
    return set(re.findall(r'^\s+"([a-z_]+)": ', body, re.M)) | set(
        re.findall(r'metrics\["([a-z_]+)"\]', body))

PERF_COLUMNS = ("Perf ID", "NFR", "Load profile", "Duration", "Dataset", "Metric", "Threshold", "Env")
RES_COLUMNS = ("ID", "Req", "Injected failure", "Where", "Promised behavior (design ref)", "Assertion")


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _norm(text: str) -> str:
    return " ".join(text.split())


def _plan_row(heading: str, columns: tuple[str, ...], row_id: str) -> dict[str, str]:
    text = TEST_PLAN.read_text(encoding="utf-8")
    start = text.index(heading)
    body = text[start: text.index("\n### ", start + 1)]
    lines = [line for line in body.splitlines() if line.startswith("|")]
    assert tuple(_cells(lines[0])) == columns, f"{heading}'s columns changed: {_cells(lines[0])!r}"
    for line in lines[2:]:
        cells = _cells(line)
        if cells[0] == row_id:
            assert len(cells) == len(columns), f"{row_id} does not split into {len(columns)} cells"
            return dict(zip(columns, cells))
    raise AssertionError(f"{heading} has no {row_id} row")


def _tables(text: str) -> list[list[list[str]]]:
    """Every Markdown table in `text`, as rows of cells, header and rule dropped."""
    tables, current = [], []
    for line in text.splitlines() + [""]:
        if line.startswith("|"):
            current.append(_cells(line))
        elif current:
            tables.append([r for r in current[2:]])
            current = []
    return tables


def _header_problems(text: str, row: dict[str, str], columns: tuple[str, ...]) -> list[str]:
    header = {r[0]: (r[1] if len(r) > 1 else "") for r in _tables(text)[0]} if _tables(text) else {}
    problems = []
    if tuple(header) != columns:
        problems.append(f"the runbook's header fields are {tuple(header)!r}, not {columns!r}")
    for column in columns:
        if _norm(header.get(column, "")) != _norm(row[column]):
            problems.append(f"the runbook's {column!r} drifted from the plan")
    return problems


def _blank_record(text: str, heading: str, required: tuple[str, ...]) -> list[str]:
    section = text.split(f"## {heading}", 1)
    if len(section) != 2:
        return [f"the runbook has no '{heading}' section"]
    rows = _tables(section[1].split("\n## ")[0])
    rows = rows[0] if rows else []
    names = [r[0] for r in rows]
    problems = [f"the '{heading}' record has no {name!r} row" for name in required if name not in names]
    filled = [r[0] for r in rows if len(r) > 1 and r[1]]
    if filled:
        problems.append(f"the committed runbook carries entries {filled!r}; fill in a copy")
    return problems


def perf_10_problems(text: str, row: dict[str, str]) -> list[str]:
    problems = _header_problems(text, row, PERF_COLUMNS)
    metric = row["Metric"].split(":", 1)[-1]
    sub_criteria = [_norm(part).rstrip(".") for part in metric.split(";") if part.strip()]
    if len(sub_criteria) != 10 or "ten" not in row["Threshold"]:
        problems.append(f"§6.4's Metric no longer lists ten sub-criteria: {sub_criteria!r}")
    section = text.split("## The gate table", 1)
    gates = _tables(section[1].split("\n## ")[0])[0] if len(section) == 2 else []
    if [g[0] for g in gates] != [str(n) for n in range(1, len(sub_criteria) + 1)]:
        problems.append(f"the gate table's rows are {[g[0] for g in gates]!r}, not 1..{len(sub_criteria)}")
    for number, (gate, criterion) in enumerate(zip(gates, sub_criteria), start=1):
        if len(gate) < 6 or _norm(gate[1]).lower() != criterion.lower():
            problems.append(f"gate row {number} reads {gate[1:2]!r}, not §6.4's {criterion!r}")
        elif not gate[2] or not gate[3]:
            problems.append(f"gate row {number} has no pass rule or no measurement source")
        elif gate[4] or gate[5]:
            problems.append(f"gate row {number} carries a committed measurement")
    if gates and len(gates) >= 9 and len(gates[8]) > 2 and not (
            "RTO ≤ 1 minute" in gates[8][2] and "RPO ≤ 5 s" in gates[8][2]):
        problems.append("gate row 9 no longer states NFR-SYS-02's RTO ≤ 1 minute and RPO ≤ 5 s")
    procedure = _norm(text.split("## Procedure", 1)[-1].split("\n## ")[0])
    if "1 minute or less" not in procedure or "more than 5 seconds before the kill" not in procedure:
        problems.append("step 5 no longer measures RTO against 1 minute and RPO against 5 seconds")
    known = run_metric_names()
    for gate in gates:
        for name in re.findall(r"run_metrics\.([a-z_]+)", gate[3] if len(gate) > 3 else ""):
            if name not in known:
                problems.append(f"gate row {gate[0]} sources run_metrics.{name}, which M-ORCH "
                                f"does not write")
    problems += _blank_record(text, "Sign-off", ("Executed by", "Build", "Machine", "Verdict",
                                                 "RTO (RES-18 on E4)", "RPO (RES-18 on E4)"))
    if "all ten rows pass" not in _norm(text):
        problems.append("the verdict rule does not require all ten rows")
    return problems


def res_17_problems(text: str, row: dict[str, str]) -> list[str]:
    problems = _header_problems(text, row, RES_COLUMNS)
    procedure = text.split("## Procedure", 1)[-1].split("\n## ")[0]
    if "`pytest -q -m e2e`" not in procedure:
        problems.append("the procedure does not run §4.7's air-gapped command, `pytest -q -m e2e`")
    if "at the host" not in _norm(text) or "firewall rule is not enough" not in _norm(text):
        problems.append("the runbook does not require networking off at the host")
    if "the E2E tier passed in full" not in _norm(text):
        problems.append("the RES-17 verdict no longer requires the E2E tier to pass in full")
    problems += _blank_record(text, "Record", ("Executed by", "Build", "Interfaces up during the run",
                                               "Verdict"))
    return problems


def res_18_problems(source: str, row: dict[str, str]) -> list[str]:
    problems = []
    if "RES-18" not in source:
        problems.append(f"{RES_18_TEST} does not cite RES-18")
    tree = ast.parse(source)
    if not any(isinstance(n, ast.FunctionDef) and n.name.startswith("test_res_18_") for n in tree.body):
        problems.append(f"{RES_18_TEST} has no test_res_18_ test")
    if re.search(r"pytest\.mark\.live", source):
        problems.append(f"{RES_18_TEST} is marked live, but RES-18 is measured on E1")
    for pin in (r"^RPO_S = 5\.0$", r"^RTO_S = 60\.0$", r"if rto is None or rto > RTO_S:",
                r"if oldest_lost > RPO_S:", r"^KILL_AFTER_S = 3 \* RPO_S$",
                r"assert span > RPO_S and len\(reported\) < enumerated,"):
        if not re.search(pin, source, re.M):
            problems.append(f"{RES_18_TEST} no longer pins {pin!r}")
    if "E1" not in row["Assertion"] or "PERF-10" not in row["Assertion"]:
        problems.append(f"§6.8's RES-18 assertion changed: {row['Assertion']!r}")
    return problems


def _perf_10():
    return (PERF_DOCS / "PERF-10-release-gate.md").read_text(encoding="utf-8"), \
        _plan_row("### 6.4 Performance scenarios", PERF_COLUMNS, "PERF-10")


def _res(row_id):
    return _plan_row("### 6.8 Resilience and failure injection", RES_COLUMNS, row_id)


def test_perf_10_release_gate_runbook_carries_the_full_ten_row_gate_table():
    text, row = _perf_10()
    problems = perf_10_problems(text, row)
    assert not problems, "PERF-10:\n- " + "\n- ".join(problems)


def test_res_17_air_gapped_runbook_matches_the_plan_and_removes_the_interface():
    text = (PERF_DOCS / "RES-17-air-gapped-run.md").read_text(encoding="utf-8")
    problems = res_17_problems(text, _res("RES-17"))
    assert not problems, "RES-17:\n- " + "\n- ".join(problems)


def test_res_18_restart_is_measured_on_e1_and_confirmed_in_perf_10():
    source = (REPO_ROOT / RES_18_TEST).read_text(encoding="utf-8")
    problems = res_18_problems(source, _res("RES-18"))
    readme = (PERF_DOCS / "README.md").read_text(encoding="utf-8")
    for doc in ("PERF-10-release-gate.md", "RES-17-air-gapped-run.md"):
        if f"({doc})" not in readme:
            problems.append(f"docs/perf/README.md does not link {doc}")
    assert not problems, "RES-18:\n- " + "\n- ".join(problems)


def test_the_release_gate_checks_catch_drift():
    """Positive control: each mutation of a real input must be reported."""
    text, row = _perf_10()
    res17 = (PERF_DOCS / "RES-17-air-gapped-run.md").read_text(encoding="utf-8")
    res18 = (REPO_ROOT / RES_18_TEST).read_text(encoding="utf-8")
    assert perf_10_problems(text, row) == []
    assert res_17_problems(res17, _res("RES-17")) == []
    assert res_18_problems(res18, _res("RES-18")) == []

    gate_10 = next(line for line in text.splitlines() if line.startswith("| 10 |"))
    mutations = {
        "a dropped gate row": perf_10_problems(text.replace(gate_10 + "\n", ""), row),
        "a reworded gate": perf_10_problems(
            text.replace("| No sustained thermal throttling |", "| Thermals acceptable |"), row),
        "a filled gate": perf_10_problems(text.replace(gate_10, gate_10[:-6] + " 12 GB | pass |"), row),
        "a lost RTO row": perf_10_problems(text.replace("| RTO (RES-18 on E4) |  |\n", ""), row),
        "a plan with nine sub-criteria": perf_10_problems(
            text, dict(row, Metric=row["Metric"].replace("; disk growth within free space", ""))),
        "a firewall instead of no interface": res_17_problems(
            res17.replace("A firewall rule is not enough", "A firewall rule is enough"), _res("RES-17")),
        "a different command": res_17_problems(
            res17.replace("`pytest -q -m e2e`", "`pytest -q -m integration`"), _res("RES-17")),
        "a loosened E4 RPO": perf_10_problems(text.replace("RPO ≤ 5 s of completed", "RPO ≤ 50 s of completed"), row),
        "a loosened step-5 RTO": perf_10_problems(text.replace("1 minute or less", "10 minutes or less"), row),
        "an invented metric": perf_10_problems(
            text.replace("`run_metrics.cache_hit_rate`", "`run_metrics.nonexistent`"), row),
        "a weakened RES-17 verdict": res_17_problems(
            res17.replace("the E2E tier passed in full", "the E2E tier mostly passed"), _res("RES-17")),
        "a count-based kill": res_18_problems(
            res18.replace("KILL_AFTER_S = 3 * RPO_S", "KILL_AFTER_S = 0.1"), _res("RES-18")),
        "a loosened RTO": res_18_problems(res18.replace("RTO_S = 60.0", "RTO_S = 600.0"), _res("RES-18")),
        "a weakened RPO comparison": res_18_problems(
            res18.replace("if oldest_lost > RPO_S:", "if oldest_lost > 10 * RPO_S:"), _res("RES-18")),
    }
    missed = [name for name, problems in mutations.items() if not problems]
    assert not missed, f"the checks missed: {missed}"
