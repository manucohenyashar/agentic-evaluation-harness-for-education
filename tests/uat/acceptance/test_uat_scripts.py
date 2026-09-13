"""`TS-52` (issue #145) — the user-acceptance scripts exist as written procedures, each with its
data, its role and its sign-off criterion, ready to execute at release.

Test plan §6.3 (`UAT-01`, `UAT-04`, `UAT-05`, `UAT-06`, `UAT-07`, `UAT-08`) and §8.2's note on
the two **authoring-only** stories: the deliverable is the written procedure, which *executes at
release rather than in CI*. The scripts are `docs/uat/UAT-*.md`, one per case.

**What these tests can and cannot check.** A UAT's oracle is human judgement (§4.3): a teacher
decides whether the shown items were worth reviewing. No test here pretends to run that. What
*can* go wrong in CI is the script itself, and each test below fails when it does:

- **Differential against §6.3.** The script's header carries the plan row's seven cells, word for
  word, parsed out of `test-plan.md` itself. A script that drifts from the plan (a changed
  criterion, a renamed role, different data) fails, and so does a plan row edited without its script.
- **Executable as written.** The required sections are present. The procedure is numbered and walks
  the scenario's own **Given**, **When**, **Then** in that order. The data section names the row's
  data. The sign-off section restates the criterion and carries a blank record to fill in.
- **Pilot evidence is recorded either way.** A criterion that cites an HLD §11.9 question has a row
  for its answer in the record, so a pass/fail box cannot swallow what the pilot is for.
- **Coverage stays honest.** The *Automated coverage* list names only cases the plan defines, and
  includes every non-UAT case §7.1's matrix traces to the row's requirements. The script cannot quietly
  omit the automated half its judgement rests on.
- **A blank template.** The record is empty. A filled record belongs in the release's records, and
  one committed here would read as a sign-off nobody gave.

`test_the_script_checks_catch_drift` is the positive control: the same checks, run on in-memory
mutations of a real script, must report each mutation.

**Markers.** None: these read committed Markdown, touch no store and no socket, and pass once the
scripts exist. They run in the fast tier. `writtenahead` is reserved for tests an unresolved
`aeh.*` symbol blocks (`WRITTEN_AHEAD_BLOCKERS`), and no symbol blocks a written procedure. The
issue's generic "a red suite is the expected outcome" is overridden by its own authoring-only note
("red-by-construction **or as documentation**"), and this story lands as documentation.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_PLAN = REPO_ROOT / "docs" / "design" / "test-plan.md"
DETAILED_DESIGN = REPO_ROOT / "docs" / "design" / "detailed-design.md"
UAT_DIR = REPO_ROOT / "docs" / "uat"

#: §6.3's column headers, in order, as `plan_rows()` keys them. The header block of every script
#: carries the same fields, with the scenario column's "(Given / When / Then)" dropped.
PLAN_COLUMNS = ("UAT ID", "Req", "Business goal", "Role", "Scenario", "Data", "Sign-off criterion")
_PLAN_HEADER = PLAN_COLUMNS[:4] + ("Scenario (Given / When / Then)",) + PLAN_COLUMNS[5:]

#: The sections a runnable script needs, in the order they appear.
REQUIRED_SECTIONS = (
    "Who takes part",
    "Data",
    "Preconditions",
    "Procedure",
    "Observations to record",
    "Sign-off",
    "Automated coverage",
)

#: The sign-off record's rows every script carries, besides the role's own-words row.
RECORD_ROWS = ("Executed by", "Observer", "Date", "Build", "Profile", "Verdict")

#: Sections whose body a runnable script cannot leave empty.
NON_EMPTY_SECTIONS = ("Who takes part", "Data", "Preconditions", "Procedure",
                      "Observations to record")

#: The scripts that run on consented real student work. Their Data section must name the corpus:
#: substituting a synthetic cohort shows the pipeline works, not that a teacher accepts it.
REAL_WORK_CORPUS = "F-HAND"
REAL_WORK_SCRIPTS = ("UAT-01", "UAT-04", "UAT-05", "UAT-06", "UAT-07")

_CASE_ID = re.compile(r"\b(?:TC-[A-Z0-9]+-[A-Z]?\d+|OBS-\d+|E2E-\d+|SEC-\d+|RES-\d+|PERF-\d+)\b")
_REQ_ID = re.compile(r"\b(?:FR|NFR)-[A-Z]+-\d+\b")


def _norm(text: str) -> str:
    return " ".join(text.split())


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _section(text: str, heading: str, level: int = 2) -> str:
    """The body under a `##`/`###` heading, up to the next heading of that level or higher."""
    marks = "#" * level
    match = re.search(rf"^{marks} {re.escape(heading)}[^\n]*\n", text, re.M)
    if match is None:
        return ""
    end = re.search(rf"^#{{1,{level}}} ", text[match.end():], re.M)
    return text[match.end(): match.end() + end.start()] if end else text[match.end():]


def plan_rows() -> dict[str, dict[str, str]]:
    """§6.3's table, keyed by UAT ID, parsed from the plan itself."""
    body = _section(TEST_PLAN.read_text(encoding="utf-8"), "6.3 User acceptance tests", level=3)
    lines = [line for line in body.splitlines() if line.startswith("|")]
    header = tuple(_cells(lines[0])) if lines else ()
    assert header == _PLAN_HEADER, f"§6.3's columns changed: {header!r}"
    rows = {}
    for line in lines[2:]:
        cells = _cells(line)
        assert len(cells) == len(PLAN_COLUMNS), f"§6.3 row does not split into 7 cells: {line!r}"
        rows[cells[0]] = dict(zip(PLAN_COLUMNS, cells))
    return rows


def rtm_cases(requirement: str) -> set[str]:
    """The non-UAT cases §7.1's matrix traces to one requirement."""
    body = _section(TEST_PLAN.read_text(encoding="utf-8"), "7.1 Requirements traceability matrix",
                    level=3)
    for line in body.splitlines():
        if line.startswith(f"| {requirement} |"):
            return set(_CASE_ID.findall(_cells(line)[1]))
    raise AssertionError(f"§7.1 has no row for {requirement}")


def _plan_defines(case_id: str, plan_text: str) -> bool:
    return bool(re.search(rf"^(?:\| {re.escape(case_id)} \||#+ {re.escape(case_id)} )", plan_text,
                          re.M))


def _table(body: str) -> dict[str, str]:
    """A two-column Markdown table, first column to second, skipping the header and rule."""
    rows = [_cells(line) for line in body.splitlines() if line.startswith("|")]
    return {cells[0]: (cells[1] if len(cells) > 1 else "") for cells in rows[2:]}


def script_path(uat_id: str) -> Path | None:
    found = sorted(UAT_DIR.glob(f"{uat_id}-*.md"))
    return found[0] if len(found) == 1 else None


def problems_with(uat_id: str, text: str, row: dict[str, str]) -> list[str]:
    """Everything that stops `text` being §6.3's `uat_id` procedure, ready to run at release."""
    problems: list[str] = []
    plan_text = TEST_PLAN.read_text(encoding="utf-8")
    design_text = DETAILED_DESIGN.read_text(encoding="utf-8")

    title = re.search(r"^# (.+)$", text, re.M)
    if title is None or _norm(title.group(1)) != f"{uat_id} — {row['Business goal']}":
        problems.append(f"the title must read '# {uat_id} — {row['Business goal']}'")

    header_body = text[: text.find("\n## ")] if "\n## " in text else text
    header = _table(header_body)
    if tuple(header) != PLAN_COLUMNS:
        problems.append(f"the header fields are {tuple(header)!r}, not §6.3's {PLAN_COLUMNS!r}")
    for column in PLAN_COLUMNS:
        if _norm(header.get(column, "")) != _norm(row[column]):
            problems.append(f"header {column!r} drifted from §6.3:\n  script: "
                            f"{header.get(column)!r}\n  plan:   {row[column]!r}")

    for requirement in _REQ_ID.findall(row["Req"]):
        if not re.search(rf"^\| {re.escape(requirement)} \|", design_text, re.M):
            problems.append(f"{requirement} is not a requirement in detailed-design.md")

    headings = re.findall(r"^## (.+?)\s*$", text, re.M)
    if [h for h in headings if h in REQUIRED_SECTIONS] != list(REQUIRED_SECTIONS):
        problems.append(f"sections are {headings!r}; a runnable script needs {REQUIRED_SECTIONS!r} "
                        f"in that order")

    for heading in NON_EMPTY_SECTIONS:
        if not _section(text, heading).strip():
            problems.append(f"the {heading!r} section is empty")
    signer = re.search(rf"^- \*\*{re.escape(row['Role'])}\.\*\* .*?(?=^- |\Z)",
                       _section(text, "Who takes part"), re.M | re.S)
    if signer is None or "sign off" not in _norm(signer.group(0)):
        problems.append(f"'Who takes part' does not name the {row['Role']} as the one who signs off")

    data = _section(text, "Data")
    if uat_id in REAL_WORK_SCRIPTS and f"`{REAL_WORK_CORPUS}`" not in data:
        problems.append(f"the Data section does not name `{REAL_WORK_CORPUS}`, the consented real "
                        f"corpus this script runs on")
    if _norm(row["Data"]).lower() not in _norm(data).lower():
        problems.append(f"the Data section does not name §6.3's data, {row['Data']!r}")

    procedure = _section(text, "Procedure")
    steps = re.findall(r"^\d+\. ", procedure, re.M)
    if len(steps) < 3:
        problems.append(f"the procedure has {len(steps)} numbered steps")
    # §6.3 writes "**Given** ..., **when** ..., **then** ...": the keywords match in any case.
    marks = []
    for keyword in ("Given", "When", "Then"):
        if not re.search(rf"\*\*{keyword}\*\* ", row["Scenario"], re.I):
            problems.append(f"§6.3's scenario has no **{keyword}** clause to walk")
        found = re.search(rf"\*\*{keyword}\*\* ", procedure, re.I)
        if found is None:
            problems.append(f"the procedure never walks the scenario's **{keyword}**")
        marks.append(found.start() if found else -1)
    if -1 not in marks and marks != sorted(marks):
        problems.append("the procedure walks Given/When/Then out of order")

    signoff = _section(text, "Sign-off")
    if _norm(row["Sign-off criterion"]) not in _norm(signoff.replace("*", "")):
        problems.append("the Sign-off section does not restate §6.3's criterion word for word")
    record = _table(signoff)
    for name in RECORD_ROWS:
        if name not in record:
            problems.append(f"the sign-off record has no {name!r} row")
    if f"{row['Role']}'s own words" not in record:
        problems.append(f"the sign-off record has no row for the {row['Role']}'s own words")
    for question in re.findall(r"HLD §11\.9 question (\d)", row["Sign-off criterion"]):
        if f"HLD §11.9 question {question} answer" not in record:
            problems.append(f"the criterion asks HLD §11.9 question {question}, and the record "
                            f"has no row for its answer")
    filled = {name: value for name, value in record.items() if value}
    if filled:
        problems.append(f"the committed template carries a filled sign-off record {filled!r}; "
                        f"fill in a copy in the release's records")

    coverage = set(_CASE_ID.findall(_section(text, "Automated coverage")))
    if not coverage:
        problems.append("the Automated coverage section names no case")
    for case_id in sorted(coverage):
        if not _plan_defines(case_id, plan_text):
            problems.append(f"Automated coverage names {case_id}, which the test plan does not "
                            f"define")
    for requirement in _REQ_ID.findall(row["Req"]):
        missing = rtm_cases(requirement) - coverage
        if missing:
            problems.append(f"§7.1 traces {sorted(missing)} to {requirement}, and Automated "
                            f"coverage omits them")

    readme = (UAT_DIR / "README.md").read_text(encoding="utf-8")
    if f"]({uat_id}-" not in readme:
        problems.append(f"docs/uat/README.md does not link {uat_id}")
    return problems


def _check(uat_id: str) -> None:
    row = plan_rows().get(uat_id)
    assert row is not None, f"§6.3 has no {uat_id} row"
    path = script_path(uat_id)
    assert path is not None, f"expected exactly one docs/uat/{uat_id}-*.md script"
    problems = problems_with(uat_id, path.read_text(encoding="utf-8"), row)
    assert not problems, f"{path.relative_to(REPO_ROOT)}:\n- " + "\n- ".join(problems)


def test_uat_01_overnight_grades_script_matches_the_plan_and_is_runnable():
    """`UAT-01` — the overnight zero-action run, signed off by the teacher."""
    _check("UAT-01")


def test_uat_04_review_budget_script_matches_the_plan_and_is_runnable():
    """`UAT-04` — the 30-minute queue and its residual message (HLD §11.9 question 4)."""
    _check("UAT-04")


def test_uat_05_band_only_editing_script_matches_the_plan_and_is_runnable():
    """`UAT-05` — band-only corrections (HLD §11.9 question 3)."""
    _check("UAT-05")


def test_uat_06_operator_quarantine_script_matches_the_plan_and_is_runnable():
    """`UAT-06` — the operator clears quarantine with no marking judgement."""
    _check("UAT-06")


def test_uat_07_provisional_grades_script_matches_the_plan_and_is_runnable():
    """`UAT-07` — the teacher decides whether to issue provisional grades."""
    _check("UAT-07")


def test_uat_08_no_validation_data_script_matches_the_plan_and_is_runnable():
    """`UAT-08` — an imported package's absent population evidence, described correctly."""
    _check("UAT-08")


def test_the_script_checks_catch_drift():
    """Positive control: each mutation of a real script must be reported, so a green run above
    means the scripts are right, not that the checks read nothing."""
    rows = plan_rows()
    assert set(rows) >= {"UAT-01", "UAT-04", "UAT-05", "UAT-06", "UAT-07", "UAT-08"}
    text = script_path("UAT-04").read_text(encoding="utf-8")
    row = rows["UAT-04"]
    assert problems_with("UAT-04", text, row) == []

    criterion = row["Sign-off criterion"]
    mutations = {
        "a drifted criterion": text.replace(criterion, criterion.replace("informative", "useful")),
        "a changed role": text.replace("| Role | Teacher |", "| Role | Operator |"),
        "a lost section": text.replace("## Observations to record", "## Notes"),
        "a dropped When": text.replace("**When**", "When"),
        "a filled record": text.replace("| Verdict |  |", "| Verdict | pass |"),
        "a lost pilot row": text.replace("| HLD §11.9 question 4 answer |  |\n", ""),
        "an omitted traced case": text.replace("`TC-REVIEW-23`", "the observability case"),
        "an invented case": text.replace("`TC-REVIEW-02`", "`TC-REVIEW-99`"),
        "renamed data": text.replace("**A completed run.**", "**A finished run.**"),
        "an empty section": re.sub(r"(## Preconditions\n).*?(?=\n## )", r"\1", text, flags=re.S),
        "a different signer": text.replace("- **Teacher.**", "- **Parent.**"),
        "the wrong own words": text.replace("| Teacher's own words |", "| Observer's own words |"),
        "a substituted corpus": text.replace("`F-HAND`", "some scans"),
    }
    for name, mutated in mutations.items():
        assert mutated != text, f"control fixture: the mutation {name!r} changed nothing"
        assert problems_with("UAT-04", mutated, row), f"the checks missed {name}"
    drifted_plan = dict(row, Data="A run in progress")
    assert problems_with("UAT-04", text, drifted_plan), "the checks missed a plan-side edit"
