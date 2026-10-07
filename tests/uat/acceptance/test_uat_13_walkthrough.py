"""`UAT-13` — the deployment-tutorial walkthrough (NFR-SYS-17) exists as a written
procedure, ready to execute at release.

`TS-152`'s UAT row lives in the operator-requirements test plan delta (§5.6), not in the
base plan's §6.3, so `tests/uat/acceptance/test_uat_scripts.py` — which parses §6.3 — does
not reach it. This file gives the delta's UAT row the same treatment, against the delta's
own column shape:

- **Differential against §5.6.** The script's header carries the delta row's seven cells,
  word for word, parsed out of `operator_requirements_test_plan.md` itself. A script that
  drifts from the plan fails, and so does a plan row edited without its script.
- **Executable as written.** The required sections are present and non-empty, the
  procedure walks the criterion's own verbs — install, configure, set-up, run, monitor,
  review, export, help — in that order, the terminal is closed after `pip install .` and
  before the first console step, and the RISK-110 roster-against-roster review appears
  before export.
- **The record is a blank template.** One filled row here would read as a sign-off nobody
  gave; fill in a copy in the release's records.
- **Coverage stays honest.** Automated coverage names `TC-E2E-06` — the same journey's
  automated half — and names only cases the delta plan defines.

**Markers.** None: these read committed Markdown, touch no store and no socket, and pass
once the script exists. They run in the fast tier. `writtenahead` is reserved for tests an
unresolved `aeh.*` symbol blocks, and no symbol blocks a written procedure — the same
authoring-only doctrine `test_uat_scripts.py` states for its six scripts.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DELTA_PLAN = REPO_ROOT / "docs" / "design" / "operator_requirements_test_plan.md"
DELTA_DESIGN = REPO_ROOT / "docs" / "design" / "operator_requirements_design_delta.md"
UAT_DIR = REPO_ROOT / "docs" / "uat"

UAT_ID = "UAT-13"

#: §5.6's column headers, in order, as the delta plan writes them.
DELTA_COLUMNS = ("ID", "Req", "Preconditions / input", "Rung", "Expected", "Oracle", "P")

#: The sections a runnable script needs, in the order they appear — the same list
#: `test_uat_scripts.py` enforces on its six scripts.
REQUIRED_SECTIONS = (
    "Who takes part",
    "Data",
    "Preconditions",
    "Procedure",
    "Observations to record",
    "Sign-off",
    "Automated coverage",
)

NON_EMPTY_SECTIONS = ("Who takes part", "Data", "Preconditions", "Procedure",
                      "Observations to record")

#: The sign-off record's rows every script carries, besides the operator's own-words row.
RECORD_ROWS = ("Executed by", "Observer", "Date", "Build", "Profile", "Verdict")

#: The criterion's verbs, in the order the Expected cell names them.
CRITERION_VERBS = ("install", "configure", "set-up", "run", "monitor", "review",
                   "export", "help")

#: The automated half the walkthrough's judgement rests on (the issue's own pairing).
AUTOMATED_COVERAGE = ("TC-E2E-06",)

#: RISK-110's compensation, carried as a procedure step before export.
ROSTER_STEP = "roster-against-roster"


def _norm(text: str) -> str:
    return " ".join(text.split())


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _section(text: str, heading: str, level: int = 2) -> str:
    """The body under a `##` heading, up to the next heading of that level or higher."""
    marks = "#" * level
    match = re.search(rf"^{marks} {re.escape(heading)}[^\n]*\n", text, re.M)
    if match is None:
        return ""
    end = re.search(rf"^#{{1,{level}}} ", text[match.end():], re.M)
    return text[match.end(): match.end() + end.start()] if end else text[match.end():]


def _table(body: str) -> dict[str, str]:
    """A two-column Markdown table, first column to second, skipping header and rule."""
    rows = [_cells(line) for line in body.splitlines() if line.startswith("|")]
    return {cells[0]: (cells[1] if len(cells) > 1 else "") for cells in rows[2:]}


def delta_row() -> dict[str, str]:
    """§5.6's UAT-13 row, keyed by the delta plan's own column names."""
    body = _section(DELTA_PLAN.read_text(encoding="utf-8"),
                    "5.6 M-CONSOLE / M-UI / M-HELP", level=3)
    lines = [line for line in body.splitlines() if line.startswith("|")]
    header = tuple(_cells(lines[0])) if lines else ()
    assert header == DELTA_COLUMNS, f"§5.6's columns changed: {header!r}"
    for line in lines[2:]:
        cells = _cells(line)
        if cells and cells[0] == UAT_ID:
            return dict(zip(DELTA_COLUMNS, cells))
    raise AssertionError(f"§5.6 has no {UAT_ID} row")


def script_path() -> Path:
    found = sorted(UAT_DIR.glob(f"{UAT_ID}-*.md"))
    assert len(found) == 1, f"expected exactly one docs/uat/{UAT_ID}-*.md script, got {found!r}"
    return found[0]


def problems_with(text: str, row: dict[str, str]) -> list[str]:
    """Everything that stops `text` being §5.6's UAT-13 procedure, ready to run."""
    problems: list[str] = []
    delta_design = DELTA_DESIGN.read_text(encoding="utf-8")

    title = re.search(r"^# (.+)$", text, re.M)
    if title is None or _norm(title.group(1)) != f"{UAT_ID} — The whole workflow without a terminal":
        problems.append(
            f"the title must read '# {UAT_ID} — The whole workflow without a terminal'")

    header_body = text[: text.find("\n## ")] if "\n## " in text else text
    header = _table(header_body)
    if tuple(header) != DELTA_COLUMNS:
        problems.append(f"the header fields are {tuple(header)!r}, not §5.6's {DELTA_COLUMNS!r}")
    for column in DELTA_COLUMNS:
        if _norm(header.get(column, "")) != _norm(row[column]):
            problems.append(f"header {column!r} drifted from §5.6:\n  script: "
                            f"{header.get(column)!r}\n  plan:   {row[column]!r}")

    if not re.search(rf"^\| {re.escape(row['Req'])} \|", delta_design, re.M):
        problems.append(f"{row['Req']} is not a requirement in the design delta")

    headings = re.findall(r"^## (.+?)\s*$", text, re.M)
    if [h for h in headings if h in REQUIRED_SECTIONS] != list(REQUIRED_SECTIONS):
        problems.append(f"sections are {headings!r}; a runnable script needs "
                        f"{REQUIRED_SECTIONS!r} in that order")
    for heading in NON_EMPTY_SECTIONS:
        if not _section(text, heading).strip():
            problems.append(f"the {heading!r} section is empty")

    signer = re.search(r"^- \*\*Operator\.\*\* .*?(?=^- |\Z)",
                       _section(text, "Who takes part"), re.M | re.S)
    if signer is None or "sign off" not in _norm(signer.group(0)):
        problems.append("'Who takes part' does not name the operator as the one who signs off")

    data = _section(text, "Data")
    for needle in ("deployment-tutorial", "reference machine", "sample-materials"):
        if needle not in _norm(data).lower():
            problems.append(f"the Data section does not name the {needle!r} the walkthrough runs on")

    procedure = _section(text, "Procedure")
    steps = re.findall(r"^\d+\. ", procedure, re.M)
    if len(steps) < len(CRITERION_VERBS):
        problems.append(f"the procedure has {len(steps)} numbered steps")
    positions = []
    flat = _norm(procedure).lower()
    for verb in CRITERION_VERBS:
        found = re.search(verb.replace("-", "[- ]"), flat)
        positions.append(found.start() if found else -1)
        if not found:
            problems.append(f"the procedure never walks the criterion's {verb!r} step")
    if -1 not in positions and positions != sorted(positions):
        problems.append("the procedure walks the criterion's verbs out of order")

    installed = procedure.lower().find("pip install .")
    closed = procedure.lower().find("closes the terminal")
    if installed < 0 or closed < 0 or closed < installed:
        problems.append("the procedure does not close the terminal after `pip install .` — "
                        "the walkthrough's one terminal step is the install itself")

    roster = flat.find(ROSTER_STEP)
    exported = flat.find("**export")
    if roster < 0:
        problems.append(f"the procedure carries no {ROSTER_STEP!r} review step (RISK-110)")
    elif exported >= 0 and roster > exported:
        problems.append("the roster-against-roster review comes after the export step; "
                        "RISK-110's compensation is reviewed BEFORE anything leaves the machine")

    signoff = _section(text, "Sign-off")
    expected = _norm(row["Expected"])
    if expected not in _norm(signoff.replace("*", "")):
        problems.append("the Sign-off section does not restate §5.6's Expected cell word for word")
    record = _table(signoff)
    for name in RECORD_ROWS:
        if name not in record:
            problems.append(f"the sign-off record has no {name!r} row")
    if f"Operator's own words" not in record:
        problems.append("the sign-off record has no row for the operator's own words")
    filled = {name: value for name, value in record.items() if value}
    if filled:
        problems.append(f"the committed template carries a filled sign-off record {filled!r}; "
                        f"fill in a copy in the release's records")

    coverage = set(re.findall(r"\bTC-[A-Z0-9]+-\w+\b", _section(text, "Automated coverage")))
    if not coverage:
        problems.append("the Automated coverage section names no case")
    plan_text = DELTA_PLAN.read_text(encoding="utf-8")
    for case_id in sorted(coverage):
        if not re.search(rf"^(?:\| {re.escape(case_id)} \||#+ {re.escape(case_id)} )",
                         plan_text, re.M):
            problems.append(f"Automated coverage names {case_id}, which the delta plan does not "
                            f"define")
    missing = set(AUTOMATED_COVERAGE) - coverage
    if missing:
        problems.append(f"Automated coverage omits {sorted(missing)} — the automated half the "
                        f"walkthrough's judgement rests on")

    readme = (UAT_DIR / "README.md").read_text(encoding="utf-8")
    if f"]({UAT_ID}-" not in readme:
        problems.append(f"docs/uat/README.md does not link {UAT_ID}")
    return problems


def test_uat_13_walkthrough_script_matches_the_delta_plan_and_is_runnable():
    """`UAT-13` — the terminal-closed walkthrough, signed off by the operator."""
    row = delta_row()
    path = script_path()
    problems = problems_with(path.read_text(encoding="utf-8"), row)
    assert not problems, f"{path.relative_to(REPO_ROOT)}:\n- " + "\n- ".join(problems)


def test_the_uat_13_checks_catch_drift():
    """Positive control: each mutation of the real script must be reported, so a green run
    above means the script is right, not that the checks read nothing."""
    row = delta_row()
    text = script_path().read_text(encoding="utf-8")
    assert problems_with(text, row) == []

    drifted = text.replace("| Rung | 4 |", "| Rung | 2 |")
    assert any("drifted" in p for p in problems_with(drifted, row)), "rung drift not reported"

    dropped = re.sub(r"^## Observations to record\n.*?(?=^## )", "", text, flags=re.M | re.S)
    assert problems_with(dropped, row), "a dropped section is not reported"

    installed_over = text.replace("`pip install .`", "`install the package`")
    assert any("pip install" in p for p in problems_with(installed_over, row)), \
        "a procedure without the `pip install .` step is not reported"

    filled = text.replace("| Verdict |  |", "| Verdict | pass |")
    assert any("filled sign-off record" in p for p in problems_with(filled, row)), \
        "a filled record is not reported"
