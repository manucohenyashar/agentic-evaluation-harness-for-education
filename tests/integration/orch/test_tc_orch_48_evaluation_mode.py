"""`TS-85` (issue #379) — `TC-ORCH-48`: consumers route on `evaluation_mode`, never on `kind`
(`FR-ORCH-35`, `FR-PKG-22`, `CT-PKG-19`, RISK-57).

| Precondition | Oracle |
|---|---|
| `C1`: `kind='mcq'`, `evaluation_mode='judged'`; `C2`: `kind='open'`, `evaluation_mode='deterministic'` (with an answer key) | enumeration creates extract/score units for `C1` and a deterministic unit for `C2`; a source scan finds no `kind = 'mcq'` predicate in `orch.py`, `grade.py`, `stats.py` or `det.py` |

**The package is deliberately the wrong way round**, and that is the whole design of the case.
The retired equivalence was "`kind='mcq'` IS `evaluation_mode='deterministic'`". Both criteria
here contradict it, so any consumer still reading `kind` routes **both** of them wrongly — the
MCQ goes to the deterministic walk and the open criterion goes to a judge panel. A package
where the two agreed would pass against the old reading and the new one alike.

**What RISK-57 costs.** A revision child or imported package that loses `evaluation_mode`
defaults to `judged`, so MCQ items go to judges: extra cost on every run against that version,
and a judged score where a key exists. Rated High, and invisible — the run completes and the
grades look plausible.

**The static scan is a census, not an absence claim, and the divergence is reported.** The
plan's oracle says the scan "finds no `kind = 'mcq'` / `kind == "mcq"` predicate" in the four
modules. Two live ones remain, both the same documented shape:

* `orch.py:309` (`_row_evaluation_mode`) and `det.py:268` (`_declared_mode`) — read the column
  first and fall back to `kind` **only when the column is absent or empty**, for the in-memory
  catalogue doubles that predate it. A stored package at schema version ≥ 11 always carries
  the column, so neither fallback is reachable from a real package.

Pinning "zero occurrences" would redden the suite over a decision nobody has taken; asserting
nothing would let a new predicate land unnoticed. So the sites are pinned by
`module:line`-independent census — the two known functions, by name — and **any other**
occurrence in the four modules fails the case. That is the same shape as SEC-15's execute-site
census, and it is what makes a regression visible. #379 reports the question of whether the
fallbacks should go.

**The census covers both spellings, at both scopes, and that is not a refinement.** The plan's
oracle names `kind = 'mcq'` *first* — the SQL form — and that is the one that actually
regressed: `det.py`'s `select_mcq_criteria` carried `WHERE kind = 'mcq'` from #86 until #369
replaced it with `evaluation_mode = 'deterministic'`. It lived in a module-level `Statement`
dict, so a census matching only Python `==` inside function bodies would have been blind to the
exact regression `FR-ORCH-35` exists to prevent. `_mcq_mentions` therefore matches `Compare`
nodes *and* string constants carrying the SQL predicate, attributing each to its enclosing
function or to `MODULE_SCOPE`. Docstrings are excluded by node identity rather than by
heuristic, because `_row_evaluation_mode`'s own docstring contains the characters it forbids.

**Isolation: rung 3** for the enumeration arm, static for the scan.
"""

from __future__ import annotations

import ast
import pathlib
import re
from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.pkg import PackageCatalog
from aeh.store import Statement, open_store
from tests.support.orch_run import ORCH_COHORT_ID, orch_cfg, seed_cohort, seed_package

pytestmark = pytest.mark.integration

SUBMISSIONS = ("S01",)

#: The contradiction the case is built on: each criterion's `kind` points the opposite way from
#: its `evaluation_mode`.
CRITERIA = (
    {
        "criterion_id": "C1",
        "kind": "mcq",
        "scoring_model": "atomic",
        "evaluation_mode": "judged",
    },
    {
        "criterion_id": "C2",
        "kind": "open",
        "scoring_model": "atomic",
        "evaluation_mode": "deterministic",
    },
)

#: The four modules `FR-ORCH-35` binds, and the two functions licensed to mention `mcq` — each
#: a column-first read whose `kind` branch is unreachable for a stored package.
SCANNED_MODULES = ("orch.py", "grade.py", "stats.py", "det.py")
SANCTIONED_FALLBACKS = {
    ("orch.py", "_row_evaluation_mode"),
    ("det.py", "_declared_mode"),
}

_UNITS = Statement(
    "SELECT stage, criterion_id, COUNT(*) AS n FROM work_unit WHERE run_id = :run_id "
    "GROUP BY stage, criterion_id ORDER BY criterion_id, stage"
)


@pytest.fixture
def mode_world(tmp_data_dir):
    """A run over the contradictory package, enumerated."""
    store = open_store(tmp_data_dir)
    try:
        from aeh.orch import Orchestrator

        seed_cohort(store, SUBMISSIONS)
        version = seed_package(store, CRITERIA)
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        # `C2` is deterministic, so it needs the key the deterministic walk grades against.
        catalog.set_answer_key(version, "C2", ("opt-a",))

        orchestrator = Orchestrator(store)
        run_id = orchestrator.create_run(ORCH_COHORT_ID, version, orch_cfg())
        orchestrator.enumerate_units(run_id)
        yield store, run_id
    finally:
        store.close()


def _units(store: Any, run_id: str) -> dict[tuple[str, str], int]:
    return {
        (str(row["criterion_id"]), str(row["stage"])): int(row["n"])
        for row in store.cohort(ORCH_COHORT_ID).query(_UNITS, run_id=run_id)
    }


#: The SQL spelling of the same predicate, matched inside string constants. `kind = 'mcq'` is
#: the FIRST form the plan's oracle names, and it is the one that actually regressed:
#: `det.py`'s `select_mcq_criteria` carried `WHERE kind = 'mcq'` from #86 until #369 replaced
#: it with `evaluation_mode = 'deterministic'`. A census that saw only Python `==` would have
#: been blind to the very regression `FR-ORCH-35` exists to prevent.
_SQL_PREDICATE = re.compile(r"kind\s*(?:=|==|!=|<>|\bIN\b)\s*\(?\s*['\"]mcq['\"]", re.IGNORECASE)

#: Where a match was found when it is not inside any function — module-level `Statement` dicts
#: like `ORCH_STATEMENTS` and `DET_STATEMENTS` are exactly that, and they are where the SQL
#: lives.
MODULE_SCOPE = "<module>"


def _mcq_mentions(module_name: str) -> list[tuple[str, int]]:
    """Every site in `module_name` that routes on the literal `'mcq'`, in two spellings.

    Parsed rather than grepped: a comment or a docstring saying "the `kind='mcq'` reading is
    retired" is documentation, and a regex over raw source would report all four modules as
    offenders on the strength of their own explanations. So the AST is walked, and only two
    shapes count:

    * a `Compare` node against the constant `'mcq'` — the Python predicate;
    * a **string constant** carrying the SQL predicate — a declared `Statement`'s text.

    Both are attributed to their enclosing function, or to `MODULE_SCOPE` when there is none.
    A docstring is skipped explicitly: `_row_evaluation_mode`'s own docstring contains the
    characters `kind = 'mcq'` while describing why the test is forbidden, and reporting that
    as an offence would make the census unusable.
    """
    source = pathlib.Path(aeh.orch.__file__).parent / module_name
    tree = ast.parse(source.read_text(encoding="utf-8"))

    #: node id -> enclosing function name, so a match anywhere reports where it lives.
    scope: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(node):
                scope.setdefault(id(inner), node.name)

    # Only the four node types that can carry a docstring. A blanket `getattr(node, "body")`
    # also picks up `IfExp.body` and `Lambda.body`, which are single expressions rather than
    # statement lists.
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }

    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        where = scope.get(id(node), MODULE_SCOPE)
        if isinstance(node, ast.Compare) and any(
            isinstance(operand, ast.Constant) and operand.value == "mcq"
            for operand in [node.left, *node.comparators]
        ):
            found.append((where, node.lineno))
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
            and _SQL_PREDICATE.search(node.value)
        ):
            found.append((where, node.lineno))
    return found


# --- TC-ORCH-48, the enumeration arm --------------------------------------------------------


def test_tc_orch_48_a_judged_mcq_criterion_enumerates_extract_and_score_units(mode_world):
    """`C1` is `kind='mcq'` and `evaluation_mode='judged'`: it gets a panel, not a key walk.

    A judged multiple-choice criterion is a package the design allows, and the retired
    equivalence made it unrepresentable. A consumer still reading `kind` sends this one to the
    deterministic walk, where it is scored against an answer key it does not have.
    """
    store, run_id = mode_world
    units = _units(store, run_id)

    assert units.get(("C1", "extract"), 0) > 0, (
        f"C1 got no extract unit: {units}. It declares evaluation_mode='judged', so it is "
        "extracted and scored like any judged criterion (FR-ORCH-35)"
    )
    assert units.get(("C1", "score"), 0) > 0, (
        f"C1 got no score unit: {units}. Its kind is 'mcq' and a consumer reading `kind` would "
        "route it to the deterministic walk — the retired equivalence (RISK-57)"
    )
    assert units.get(("C1", "deterministic"), 0) == 0, (
        f"C1 got a deterministic unit: {units}"
    )


def test_tc_orch_48_a_deterministic_open_criterion_enumerates_a_deterministic_unit(
    mode_world,
):
    """`C2` is `kind='open'` and `evaluation_mode='deterministic'`: a key walk, not a panel.

    The other half of the contradiction, and the expensive one: routing this to a panel spends
    model calls on a criterion whose answer key already settles it.
    """
    store, run_id = mode_world
    units = _units(store, run_id)

    assert units.get(("C2", "deterministic"), 0) > 0, (
        f"C2 got no deterministic unit: {units}. It declares "
        "evaluation_mode='deterministic', and the column is what routes it (FR-PKG-22)"
    )
    assert units.get(("C2", "score"), 0) == 0, (
        f"C2 got a score unit: {units}. A deterministic criterion is never sent to a judge — "
        "that is model spend on a question the key answers (RISK-57)"
    )
    assert units.get(("C2", "extract"), 0) == 0, (
        f"C2 got an extract unit: {units}"
    )


# --- TC-ORCH-48, the static scan ------------------------------------------------------------


@pytest.mark.parametrize("module_name", SCANNED_MODULES)
def test_tc_orch_48_no_unsanctioned_module_routes_on_kind_mcq(module_name):
    """The census: only the two documented column-first fallbacks may compare to `'mcq'`.

    A new predicate anywhere in these four modules fails here, named by its function. That is
    the regression this scan exists for — `FR-ORCH-35`'s rule is a rule about every consumer,
    and a behavioural case can only ever cover the consumers it happens to drive.
    """
    offenders = [
        (function, line)
        for function, line in _mcq_mentions(module_name)
        if (module_name, function) not in SANCTIONED_FALLBACKS
    ]

    assert offenders == [], (
        f"{module_name} compares to the literal 'mcq' outside the sanctioned column-first "
        f"fallbacks: {offenders}. `kind` is not a test any consumer may make — the "
        "equivalence it stood for was retired when `evaluation_mode` shipped (FR-ORCH-35). "
        f"Sanctioned: {sorted(SANCTIONED_FALLBACKS)}"
    )


def test_tc_orch_48_the_sanctioned_fallbacks_are_still_there():
    """The census's own positive control: every sanctioned entry still names a real site.

    Without this, the parametrized case above passes trivially once someone deletes a fallback
    and forgets the entry — and the next predicate to appear in that function would be
    excused by a stale exemption.
    """
    for module_name, function in sorted(SANCTIONED_FALLBACKS):
        names = {name for name, _line in _mcq_mentions(module_name)}
        assert function in names, (
            f"{module_name}:{function} is sanctioned to compare to 'mcq' but no longer does. "
            "Drop the entry from SANCTIONED_FALLBACKS — a stale exemption would excuse the "
            "next predicate written in that function"
        )


@pytest.mark.parametrize(
    "label,body,expected_scope",
    (
        (
            "the Python predicate",
            "def router(row):\n"
            "    if row['kind'] == 'mcq':\n"
            "        return 'deterministic'\n"
            "    return 'judged'\n",
            "router",
        ),
        (
            "the SQL predicate in a module-level statement dict",
            "STATEMENTS = {\n"
            "    'select_mcq_criteria': Statement(\n"
            "        \"SELECT criterion_id FROM criterion WHERE kind = 'mcq'\"\n"
            "    ),\n"
            "}\n",
            MODULE_SCOPE,
        ),
        (
            "the SQL predicate inside a function",
            "def load(handle):\n"
            "    return handle.query(\"SELECT * FROM criterion WHERE kind='mcq'\")\n",
            "load",
        ),
    ),
)
def test_tc_orch_48_the_scan_sees_each_shape_it_claims_to_see(
    tmp_path, label, body, expected_scope, monkeypatch
):
    """The census's own oracle, run through `_mcq_mentions` itself.

    Three shapes, because the census was blind to two of them when it was first written and
    the blindness coincided on a real site: `det.py`'s `select_mcq_criteria` carried
    `WHERE kind = 'mcq'` — SQL, at module scope, inside a `Statement` — until #369 replaced
    it. A scan that matched only Python `Compare` nodes inside functions would have watched
    that exact regression walk back in.

    The matching rule is exercised through `_mcq_mentions`, not re-implemented here: a control
    that reimplements the thing it controls stays green when the real function breaks.
    """
    module = tmp_path / "probe_module.py"
    module.write_text(body, encoding="utf-8")
    monkeypatch.setattr(
        pathlib.Path, "read_text", lambda self, **kw: body, raising=True
    )

    found = _mcq_mentions("probe_module.py")

    assert [scope for scope, _line in found] == [expected_scope], (
        f"{label}: the census reported {found}, not one match in {expected_scope!r}. Every "
        "scan above is passing over a pattern it cannot see"
    )
