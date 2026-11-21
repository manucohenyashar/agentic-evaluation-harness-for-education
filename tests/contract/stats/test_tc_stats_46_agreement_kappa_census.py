"""TC-STATS-46 (CT-STATS-29), rung 0: no consumer reads `agreement_kappa` as the figure.

`package_validation.agreement_kappa` is NULL on every multi-criterion record (FR-STATS-32), so
a screen that showed it would show "no figure" exactly where there is one. The figure a reader
shows is per criterion (`criterion_stats`, `administration_figure_views`). The census:

- `aeh.console`: no read of the column in any form (attribute, subscript, `.get`, `getattr`),
  and the name appears nowhere, SQL text included;
- `aeh.pkg`: no read in any of those forms. The name may appear only where the record is
  written or declared: the DDL, the promotion-record SELECT, and `record_promotion`'s INSERT
  and parameter. Each allowed site is pinned below with its reason;
- `ui/src`: the name appears in no `.ts`/`.tsx` file. Python has no TypeScript parser, so this
  leg is a token scan, not an AST census (disclosed in the PR).

The rung-3 half (the validity read shows per-criterion figures on the multi-criterion seed,
and goes red when made to read `agreement_kappa`) is
`tests/integration/stats/test_tc_stats_46_validity_read.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "aeh"
COLUMN = "agreement_kappa"

#: `aeh.pkg`'s sites allowed to NAME the column: (file, enclosing definition) -> why.
PKG_ALLOWED_MENTIONS: dict[tuple[str, str], str] = {
    ("schema.py", "<module>"): "the package_validation DDL and its comment",
    ("statements.py", "<module>"): "_SELECT_PROMOTION_RECORD, the record's read-back statement",
    ("validation.py", "record_promotion"): "the writer: its parameter, INSERT and binding",
}


def _enclosing(tree: ast.AST) -> dict[ast.AST, str]:
    """Each node mapped to the name of the outermost function or class around it."""
    owner: dict[ast.AST, str] = {}
    for top in ast.iter_child_nodes(tree):
        name = (top.name if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef,
                                             ast.ClassDef)) else "<module>")
        for node in ast.walk(top):
            owner[node] = name
    return owner


def column_reads(source: str) -> list[int]:
    """Line numbers where `source` READS the column: `x.agreement_kappa`,
    `x["agreement_kappa"]`, `x.get("agreement_kappa")` or `getattr(x, "agreement_kappa")`."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr == COLUMN and isinstance(
                node.ctx, ast.Load):
            lines.append(node.lineno)
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load) and isinstance(
                node.slice, ast.Constant) and node.slice.value == COLUMN:
            lines.append(node.lineno)
        elif isinstance(node, ast.Call) and any(
                isinstance(arg, ast.Constant) and arg.value == COLUMN for arg in node.args):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in {"get", "getattr", "pop", "setdefault"}:
                lines.append(node.lineno)
    return sorted(lines)


def column_mentions(source: str) -> set[str]:
    """The enclosing definitions in which the column is NAMED at all: a string containing it, a
    name, an argument, a keyword or an attribute."""
    tree = ast.parse(source)
    owner = _enclosing(tree)
    found = set()
    for node in ast.walk(tree):
        named = (
            (isinstance(node, ast.Constant) and isinstance(node.value, str)
             and COLUMN in node.value)
            or (isinstance(node, ast.Name) and node.id == COLUMN)
            or (isinstance(node, ast.arg) and node.arg == COLUMN)
            or (isinstance(node, ast.keyword) and node.arg == COLUMN)
            or (isinstance(node, ast.Attribute) and node.attr == COLUMN)
        )
        if named:
            found.add(owner.get(node, "<module>"))
    return found


def _python_files(package: str) -> list[Path]:
    files = sorted((SRC / package).rglob("*.py"))
    assert files, f"fixture: no Python files under {SRC / package}"
    return files


def test_tc_stats_46_the_census_detects_each_read_form():
    """Positive control: each read form the census claims to catch is caught, and a write
    (keyword argument, dict key in a binding) is not counted as a read."""
    reads = (
        "record.agreement_kappa\n"
        "row['agreement_kappa']\n"
        "row.get('agreement_kappa')\n"
        "getattr(record, 'agreement_kappa', None)\n"
    )
    assert column_reads(reads) == [1, 2, 3, 4]
    writes = "write(agreement_kappa=None)\nparams = {'agreement_kappa': value}\n"
    assert column_reads(writes) == []
    assert column_mentions(writes) == {"<module>"}


@pytest.mark.parametrize("package", ["console", "pkg"])
def test_tc_stats_46_no_module_reads_agreement_kappa(package):
    """TC-STATS-46: no file of `aeh.console` or `aeh.pkg` reads `agreement_kappa`."""
    offenders = {
        str(path.relative_to(SRC)): lines
        for path in _python_files(package)
        if (lines := column_reads(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}, (
        f"aeh.{package} reads agreement_kappa at {offenders}; it is NULL on a multi-criterion "
        "record, so a display of it shows 'no figure' where there is one (CT-STATS-29). Read "
        "the per-criterion figures (`administration_figure_views`) instead")


def test_tc_stats_46_the_console_never_names_agreement_kappa():
    """TC-STATS-46: the console does not name the column at all, SQL text included."""
    offenders = {
        str(path.relative_to(SRC)): sorted(found)
        for path in _python_files("console")
        if (found := column_mentions(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}, f"aeh.console names agreement_kappa in {offenders}"


def test_tc_stats_46_the_package_tier_names_it_only_where_it_is_written():
    """TC-STATS-46: `aeh.pkg` names the column only at the pinned write and declaration sites.
    The set must also be non-empty there: a census that cannot see the writer sees nothing."""
    found = {
        (path.name, definition)
        for path in _python_files("pkg")
        for definition in column_mentions(path.read_text(encoding="utf-8"))
    }
    unexpected = found - set(PKG_ALLOWED_MENTIONS)
    assert unexpected == set(), (
        f"aeh.pkg names agreement_kappa at unpinned sites {sorted(unexpected)}; allowed are "
        f"{PKG_ALLOWED_MENTIONS}")
    assert ("validation.py", "record_promotion") in found, (
        "the census did not see the writer: the scan is not reading aeh.pkg")


def test_tc_stats_46_the_spa_never_names_agreement_kappa():
    """TC-STATS-46: no TypeScript source under `ui/src` names the column (a token scan)."""
    sources = sorted(p for p in (ROOT / "ui" / "src").rglob("*")
                     if p.suffix in {".ts", ".tsx"} and "node_modules" not in p.parts)
    assert len(sources) > 10, f"fixture: only {len(sources)} SPA sources found under ui/src"
    offenders = [str(path.relative_to(ROOT)) for path in sources
                 if COLUMN in path.read_text(encoding="utf-8")]
    assert offenders == [], f"the SPA names agreement_kappa in {offenders}"
