"""Validity T8 (issue #901), the rung-0 halves: TC-CONSOLE-109 (FR-CONSOLE-85, RSV-20) and
TC-REG-25 (SV-10).

- TC-CONSOLE-109: `STANDING_AGREEMENT_FIGURE` is absent from `src/` — no definition, no
  reference, no import, no string naming it (AST).
- TC-REG-25: no numeric literal 0.63 anywhere in `src/` (AST): the hard-coded kappa SV-10 found
  cannot come back as a constant.

Each census carries a positive control: the same walker, fed a source that reintroduces the
figure, flags it. The rung-3 halves (no served response or legacy page shows the figure; the
legacy rollup's absence sentence) are in
`tests/integration/console/test_tc_console_109_110_figures_and_record.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

SRC = Path(__file__).resolve().parents[3] / "src"
NAME = "STANDING_AGREEMENT_FIGURE"
FABRICATED_KAPPA = 0.63


def _name_sites(tree: ast.AST) -> list[int]:
    """Lines where the name is defined, referenced, imported or spelled as a string."""
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == NAME:
            lines.append(node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr == NAME:
            lines.append(node.lineno)
        elif isinstance(node, ast.alias) and NAME in (node.name, node.asname):
            lines.append(getattr(node, "lineno", 0))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and \
                NAME in node.value:
            lines.append(node.lineno)
    return lines


def _figure_sites(tree: ast.AST) -> list[int]:
    return [node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, float)
            and node.value == FABRICATED_KAPPA]


def _census(finder) -> list[str]:
    found = []
    files = sorted(SRC.rglob("*.py"))
    assert len(files) > 100, f"fixture: only {len(files)} source files under {SRC}"
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found += [f"{path.relative_to(SRC)}:{line}" for line in finder(tree)]
    return found


def test_tc_console_109_the_fabricated_figure_is_absent_from_src():
    """TC-CONSOLE-109 (rung 0): no `STANDING_AGREEMENT_FIGURE` anywhere in `src/`."""
    planted = ast.parse(f"{NAME} = {{'kappa': 0.63, 'n': 15}}\nx = vocabulary.{NAME}\n"
                        f"from aeh.console.vocabulary import {NAME}\n")
    assert len(_name_sites(planted)) == 3, "the census cannot see the name it looks for"
    found = _census(_name_sites)
    assert not found, f"{NAME} is back in production code (FR-CONSOLE-85): {found}"


def test_tc_reg_25_no_kappa_of_0_63_anywhere_in_src():
    """TC-REG-25 (SV-10): no float literal 0.63 in `src/`."""
    assert _figure_sites(ast.parse("FIGURE = {'kappa': 0.63}")) == [1], (
        "the census cannot see the literal it looks for")
    found = _census(_figure_sites)
    assert not found, f"a literal 0.63 is in production code (SV-10): {found}"
