"""`TS-82` (issue #155): the blast-radius CI rule, double conformance and the contract-coverage gate.

Test plan §6.12, cases `TC-BLAST-01..03`. These are **cross-cutting**: they trace to no `FR-*` and
no single clause, because their subject is the machinery that runs the other clause and pairwise
cases.

| Case | Asserts | Rung |
|---|---|---|
| TC-BLAST-01 | `python -m harness.blast_radius --changed <M-X>` emits §6.12's row for each of the 19 modules, read from design §4.7 | 2 |
| TC-BLAST-02 | every test double standing in for a contracted module runs in that module's §6.11 suite, or is exempt with its consequence stated | 2 |
| TC-BLAST-03 | `check_traceability.py --contracts-only` fails a build that loses a clause case, passes the real pair, and CI invokes it | 0 |

**Written ahead.** `harness.blast_radius` does not exist, and no story in the backlog builds it.
All three cases carry `writtenahead` and one `WRITTEN_AHEAD_BLOCKERS` entry keyed on that module.
TC-BLAST-03's red is also a defect in the existing gate script, not only the missing CI wiring
(see its docstring), so the module landing is the notice to re-check it, not proof it is fixed.

**Interfaces assumed, because the design declares none.**
- The harness prints the selection as text naming every resolved case ID (`TC-*`) and every
  consumer module re-verified (`M-*`).
- It accepts `--design <path>`, so the §4.7 table can be read from a fixture copy.
- Exemptions for doubles live at `harness.blast_radius:DOUBLE_EXEMPTIONS`, a mapping from the
  double's dotted class name to its stated consequence.
"""

from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.support.impl import NotImplementedYet, require

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]

BLAST_MODULE = "harness.blast_radius"
PLAN = "docs/design/test-plan.md"
DESIGN = "docs/design/detailed-design.md"
GATE = ".claude/skills/create-test-plan/scripts/check_traceability.py"
MODULE_RE = re.compile(r"M-[A-Z]+")


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    following = re.search(r"^#{2,3} ", text[start + len(heading):], re.M)
    return text[start: start + len(heading) + (following.start() if following else len(text))]


def _table_rows(section: str) -> list[list[str]]:
    return [[cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in section.splitlines()
            if line.startswith("| `M-") or line.startswith("| TC-")]


def _consumers(cell: str, module: str, all_modules: set[str]) -> set[str]:
    """A `Consumed by` cell as a module set. "every module except …" is the complement of what
    it lists (minus the module itself); a cell naming only people or CI is the empty set."""
    named = set(MODULE_RE.findall(cell))
    if cell.lower().startswith("every module except"):
        before_note = cell.split("(")[0]
        return all_modules - set(MODULE_RE.findall(before_note)) - {module}
    return named


def _design_register(design_text: str) -> dict[str, str]:
    section = _section(design_text, "### 4.7 Contract register and change classification")
    return {MODULE_RE.search(row[0]).group(0): row[-1] for row in _table_rows(section) if len(row) >= 6}


def _plan_blast_rows(plan_text: str) -> dict[str, list[str]]:
    section = _section(plan_text, "### 6.12 Blast-radius regression sets")
    return {MODULE_RE.search(row[0]).group(0): row for row in _table_rows(section)
            if len(row) == 5 and row[1].startswith("§6.11")}


def _requires_rows(plan_text: str) -> list[tuple[str, str, str]]:
    rows = []
    for line in plan_text.splitlines():
        match = re.match(r"\| (TC-REQ-\d+) \| `(M-[A-Z]+)` \| `(M-[A-Z]+)` \|", line)
        if match:
            rows.append(match.groups())
    return rows


MODULES = sorted(_design_register((Path(__file__).resolve().parents[3] / DESIGN).read_text(encoding="utf-8")))


def _child_env(repo_root: Path) -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": os.pathsep.join([str(repo_root / "src"), str(repo_root)])}


@pytest.mark.integration
@pytest.mark.parametrize("module", MODULES)
def test_tc_blast_01_the_selection_for_each_module_equals_its_section_6_12_row(module, repo_root, tmp_path):
    """`TC-BLAST-01`, one parametrized cell per module. The expected selection is
    §6.12's row:

    - the module's clause cases (every `TC-<MOD>-Cnn` in the plan, as many as the row's count);
    - the `M-*` consumers the row names;
    - the row's `TC-REQ-*` cases.

    Before the harness runs, the row is checked against its sources, so a stale oracle fails here
    and not as a harness bug:

    - its consumers equal design §4.7's `Consumed by`;
    - its `TC-REQ` list equals the §6.13 rows whose provider is this module;
    - its clause count equals the plan's clause cases.

    Then the harness's selection must equal that set exactly. Finally, the harness runs against a
    fixture copy of the design whose §4.7 row gains one consumer, and the selection must gain
    that consumer. That is the check that the harness reads §4.7 rather than a copy of it."""
    plan_text = (repo_root / PLAN).read_text(encoding="utf-8")
    design_text = (repo_root / DESIGN).read_text(encoding="utf-8")
    all_modules = set(MODULES)
    assert len(all_modules) == 19, f"design §4.7 names {len(all_modules)} modules"

    row = _plan_blast_rows(plan_text)[module]
    design_consumers = _consumers(_design_register(design_text)[module], module, all_modules)
    plan_consumers = _consumers(row[2], module, all_modules)
    assert plan_consumers == design_consumers, (
        f"§6.12's consumers for {module} {sorted(plan_consumers)} differ from design §4.7's "
        f"{sorted(design_consumers)}: the plan's table is stale (the design is right)")
    req_cases = set(re.findall(r"TC-REQ-\d+", row[3]))
    by_provider = {case for case, _consumer, provider in _requires_rows(plan_text) if provider == module}
    assert req_cases == by_provider, (
        f"§6.12's cases for {module} {sorted(req_cases)} differ from the §6.13 rows naming it as "
        f"provider {sorted(by_provider)}")
    short = module.removeprefix("M-")
    clause_cases = set(re.findall(rf"TC-{short}-C\d+", plan_text))
    declared = int(re.search(r"\((\d+)\)", row[1]).group(1))
    assert len(clause_cases) == declared, (
        f"{module}'s clause suite declares {declared} cases, the plan defines {len(clause_cases)}")
    expected = clause_cases | req_cases | plan_consumers

    require(BLAST_MODULE, issue="#155 (no implementing story yet)")

    def selection(*extra: str) -> set[str]:
        result = subprocess.run([sys.executable, "-m", BLAST_MODULE, "--changed", module, *extra],
                                cwd=repo_root, env=_child_env(repo_root), capture_output=True, text=True,
                                timeout=120)
        assert result.returncode == 0, f"blast_radius --changed {module} failed:\n{result.stderr[-1500:]}"
        return set(re.findall(r"TC-[A-Z]+-C?\d+|M-[A-Z]+", result.stdout)) - {module}

    emitted = selection()
    assert emitted == expected, (
        f"the selection for {module} differs from §6.12's row. Missing: {sorted(expected - emitted)}; "
        f"extra: {sorted(emitted - expected)}")

    widened_with = sorted(all_modules - design_consumers - {module})[0]
    fixture = tmp_path / "detailed-design.md"
    lines = design_text.splitlines(keepends=True)
    register = _section(design_text, "### 4.7 Contract register and change classification")
    target = next(line for line in register.splitlines() if line.startswith(f"| `{module}` |"))
    widened = target.rstrip().rstrip("|").rstrip() + f", `{widened_with}` |"
    fixture.write_text("".join(widened + "\n" if line.rstrip("\r\n") == target else line for line in lines),
                       encoding="utf-8")
    assert widened in fixture.read_text(encoding="utf-8"), "fixture: the widened row was not written"
    after = selection("--design", str(fixture))
    assert widened_with in after and after - {widened_with} >= emitted - {widened_with}, (
        f"widening {module}'s §4.7 row with {widened_with} did not widen the selection: {sorted(after)}")


_ENUMERATE_DOUBLES = textwrap.dedent('''
    import inspect, json, sys
    import pytest

    class Quiet:
        def pytest_collection_modifyitems(self, items):
            pass

    code = pytest.main(["--collect-only", "-q", "-p", "no:randomly", "-p", "no:cacheprovider", "tests"],
                       plugins=[Quiet()])
    import os
    tests_dir = os.path.abspath("tests") + os.sep
    classes = {}
    for name, module in list(sys.modules.items()):
        path = os.path.abspath(getattr(module, "__file__", None) or "") if module is not None else ""
        if not path.startswith(tests_dir):
            continue
        for attr, value in list(vars(module).items()):
            if inspect.isclass(value) and value.__module__ == name:
                members = sorted({m for klass in value.__mro__ if klass is not object
                                  for m, v in vars(klass).items()
                                  if not m.startswith("_") and (callable(v) or isinstance(v, property))})
                classes[f"{name}.{value.__qualname__}"] = members
    print("JSON:" + json.dumps({"collect_exit": int(code), "classes": classes}))
''')

_RECORD_SUITE_CONSTRUCTIONS = textwrap.dedent('''
    import importlib, json, sys
    import pytest

    doubles = json.load(open(sys.argv[1], encoding="utf-8"))
    suites = sys.argv[2:]
    current = {"suite": None}
    seen = {}

    def wrap(dotted):
        module_name, _, qualname = dotted.rpartition(".")
        while module_name:
            try:
                owner = importlib.import_module(module_name)
                break
            except ImportError:
                module_name, _, head = module_name.rpartition(".")
                qualname = head + "." + qualname
        else:
            return
        cls = owner
        for part in qualname.split("."):
            cls = getattr(cls, part, None)
            if cls is None:
                return
        original = cls.__init__

        def __init__(self, *args, __original=original, __name=dotted, **kwargs):
            if current["suite"] and type(self).__module__ + "." + type(self).__qualname__ == __name:
                seen.setdefault(current["suite"], set()).add(__name)
            __original(self, *args, **kwargs)

        try:
            cls.__init__ = __init__
        except (TypeError, AttributeError):
            pass

    class Tracker:
        def pytest_collection_finish(self, session):
            for dotted in doubles:
                wrap(dotted)

        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_protocol(self, item, nextitem):
            path = item.nodeid
            current["suite"] = path.split("/")[2] if path.startswith("tests/contract/") else None
            yield
            current["suite"] = None

    code = pytest.main([*[f"tests/contract/{s}" for s in suites], "-q", "-p", "no:randomly", "-p",
                        "no:cacheprovider", "-m", "not live and not slow and not writtenahead", "--no-header"],
                       plugins=[Tracker()])
    print("JSON:" + json.dumps({"exit": int(code), "seen": {k: sorted(v) for k, v in seen.items()}}))
''')


def _stand_in_rules():
    """Which contracted module a class stands in for, from the contracted modules' own declared
    surfaces. The member names are read from the Protocols and classes, not listed here.
    `aeh.prov.Transport`/`Clock` and `aeh.store.Clock` are seams inside a module (CLAUDE.md
    seam 2), not stand-ins for the module, and are left out."""
    import aeh.orch as orch
    import aeh.pkg as pkg
    import aeh.prov as prov
    import aeh.store as store

    def surface(cls):
        return {name for name, _ in inspect.getmembers(cls) if not name.startswith("_")}

    return [
        ("M-PROV", {"complete"} & surface(prov.InferenceProvider), 1),
        ("M-STORE", surface(store.Store), 2),
        ("M-STORE", surface(store.TierHandle), 2),
        ("M-STORE", surface(store.BlobStore), 3),
        ("M-PKG", (surface(pkg.PackageCatalog) | surface(orch.PackageCatalogProtocol)) - {"package_id"}, 3),
    ]


def _resolve(members, rules) -> str | None:
    for module, surface, needed in rules:
        if len(set(members) & surface) >= needed:
            return module
    return None


def _json_line(stdout: str) -> dict:
    line = next(l for l in reversed(stdout.splitlines()) if l.startswith("JSON:"))
    return json.loads(line[len("JSON:"):])


@pytest.mark.integration
def test_tc_blast_02_every_double_for_a_contracted_module_runs_its_clause_suite(repo_root, tmp_path):
    """`TC-BLAST-02` (§4.10). The doubles are found from the collected test session, not a
    registry or a naming pattern.

    1. A child process collects the whole `tests/` tree and lists every class defined in any
       module under `tests/` that the collection imported, whatever name it was imported under.
    2. Each class is resolved to the contracted module whose declared surface it implements, by
       its members and never by its name.
    3. A second child runs the §6.11 suites of the modules resolved to (fast-tier cells), with
       each double's constructor wrapped, and records which doubles are constructed while a test
       in each suite runs.

    A double is held when it is constructed inside its module's suite, or when it is on the
    harness's exemption list with a non-empty stated consequence. Every other double is a
    failure.

    Controls:
    - A class with a provider's `complete` and a neutral name resolves to M-PROV. A class with
      only a transport's `send` resolves to nothing.
    - The session walk finds `tests.contract.ingest._doubles.ScriptedProvider` and resolves it
      to M-PROV.
    - The recorder sees `aeh.prov.RecordedFixtureProvider` constructed inside the M-PROV suite,
      which §4.10 says is where it is held."""
    rules = _stand_in_rules()
    assert _resolve(["complete", "capabilities"], rules) == "M-PROV", "control: resolver misses a provider"
    assert _resolve(["send"], rules) is None, "control: resolver claims a transport seam"

    env = _child_env(repo_root)
    listed = subprocess.run([sys.executable, "-c", _ENUMERATE_DOUBLES], cwd=repo_root, env=env,
                            capture_output=True, text=True, timeout=900)
    classes = _json_line(listed.stdout)["classes"]
    doubles = {name: module for name, members in classes.items() if (module := _resolve(members, rules))}
    in_test_file = [n for n in doubles if ".test_" in n or n.startswith("test_")]
    assert in_test_file, f"control: no double defined inside a test file was found: {sorted(doubles)}"
    assert doubles.get("tests.contract.ingest._doubles.ScriptedProvider") == "M-PROV", (
        f"control: the session walk did not find a known provider double ({len(doubles)} doubles found)")
    doubles["aeh.prov.RecordedFixtureProvider"] = "M-PROV"  # §4.10's named double, shipped in src

    suites = sorted({module.removeprefix("M-").lower() for module in doubles.values()})
    listing = tmp_path / "doubles.json"
    listing.write_text(json.dumps(sorted(doubles)), encoding="utf-8")
    ran = subprocess.run([sys.executable, "-c", _RECORD_SUITE_CONSTRUCTIONS, str(listing), *suites], cwd=repo_root,
                         env=env, capture_output=True, text=True, timeout=1800)
    seen = _json_line(ran.stdout)["seen"]
    assert "aeh.prov.RecordedFixtureProvider" in seen.get("prov", ()), (
        f"control: the recorder did not see RecordedFixtureProvider constructed in the M-PROV suite: {seen.get('prov')}")

    try:
        exemptions = dict(require(BLAST_MODULE, "DOUBLE_EXEMPTIONS", issue="#155 (no implementing story yet)"))
        exemption_note = ""
    except NotImplementedYet as missing:
        exemptions, exemption_note = {}, f" (no exemption list exists: {missing})"
    unheld = sorted(
        f"{name} -> {module}" for name, module in doubles.items()
        if name not in seen.get(module.removeprefix("M-").lower(), ())
        and not str(exemptions.get(name, "")).strip())
    assert not unheld, (
        f"{len(unheld)} doubles stand in for a contracted module without running its clause suite "
        f"or carrying a stated exemption{exemption_note}:\n  " + "\n  ".join(unheld))


def _gate(repo_root: Path, plan: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(repo_root / GATE), "--design", str(repo_root / DESIGN),
                           "--plan", str(plan), "--contracts-only"], cwd=repo_root, capture_output=True,
                          text=True, timeout=120)


def _uncovered_clauses(output: str) -> set[str]:
    match = re.search(r"contract clause\(s\) with no test case[^\n]*\n((?:\s+CT-[A-Z]+-\d+[^\n]*\n)+)", output)
    return set(re.findall(r"CT-[A-Z]+-\d+", match.group(1))) if match else set()


def test_tc_blast_03_the_contracts_only_gate_fails_a_lost_clause_case_and_ci_runs_it(repo_root, tmp_path):
    """`TC-BLAST-03` (RISK-40). Three halves, each checked on its own, then reported together.

    1. **A lost case fails the build, naming the clause.** The fixture plan removes the
       `TC-CONF-C01` case row. The gate must exit non-zero *and* list `CT-CONF-01` under
       "contract clause(s) with no test case". The exit code alone proves nothing: the unmutated
       run also exits non-zero today, for an unrelated reason.
    2. **The real pair passes.** `--contracts-only` against the real design and plan exits 0.
    3. **CI invokes it.** The workflows are `.disabled` (CLAUDE.md), so the CI wiring lives in
       plan §4.7's suite table and `scripts/test.sh`, the reading `TC-CONFORM-07` settled. One of
       them must run `check_traceability.py --contracts-only`.

    Control: a fixture plan with *every* mention of `TC-CONF-C01` removed does make the gate
    name `CT-CONF-01`. That proves half 1's check can fire."""
    plan_text = (repo_root / PLAN).read_text(encoding="utf-8")
    row = next(line for line in plan_text.splitlines() if line.startswith("| TC-CONF-C01 | CT-CONF-01 |"))

    erased = tmp_path / "erased.md"
    erased.write_text("\n".join(l for l in plan_text.splitlines() if "TC-CONF-C01" not in l), encoding="utf-8")
    assert "CT-CONF-01" in _uncovered_clauses(_gate(repo_root, erased).stdout), (
        "control: the gate does not name a clause even when every mention of its case is gone")

    problems = []
    mutated = tmp_path / "test-plan.md"
    mutated.write_text("\n".join(l for l in plan_text.splitlines() if l != row), encoding="utf-8")
    lost = _gate(repo_root, mutated)
    if lost.returncode == 0 or "CT-CONF-01" not in _uncovered_clauses(lost.stdout):
        problems.append(
            f"removing TC-CONF-C01's case row leaves the gate reporting CT-CONF-01 as traced (exit "
            f"{lost.returncode}, uncovered={sorted(_uncovered_clauses(lost.stdout))}). [When written: the "
            f"script counts a clause as covered wherever its ID shares a table row with any TC-* "
            f"reference, and the §7.6 contract traceability matrix row '| CT-CONF-01 | … | TC-CONF-C01 |' still names the "
            f"deleted case. A clause stays green after losing its case, which is the RISK-40 accretion "
            f"the gate exists to stop.]")

    real = _gate(repo_root, repo_root / PLAN)
    if real.returncode != 0:
        orphan_line = next((l for l in real.stdout.splitlines() if l.startswith("FAIL")), "")
        problems.append(
            f"--contracts-only exits {real.returncode} against the real pair: {orphan_line!r}. [When "
            f"written: --contracts-only drops the requirement pattern from the scan, so every case "
            f"tracing only to an FR-*/NFR-* ID becomes an orphan and fails the run. The full "
            f"invocation exits 0.]")

    wiring = [(PLAN, _section(plan_text, "### 4.7 Tooling and execution")),
              ("scripts/test.sh", (repo_root / "scripts/test.sh").read_text(encoding="utf-8"))]
    if not any(re.search(r"check_traceability\.py[^\n|]*--contracts-only", text) for _, text in wiring):
        problems.append(
            "neither plan §4.7's suite table nor scripts/test.sh runs `check_traceability.py "
            "--contracts-only`: the gate §4.8 exit criterion 10 says is 'wired as a build gate' "
            "is invoked nowhere.")
    assert not problems, "\n".join(problems)
