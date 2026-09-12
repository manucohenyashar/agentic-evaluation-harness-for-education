"""`TC-CALIB-07` — the §6.2 lock's refusal is implemented exactly once, in `M-PKG`.

Test plan §5.17, `TC-CALIB-07` (FR-CALIB-07, Integration / rung 2, negative sweep —
oracle: *exact exception plus import-graph assertion*). The case's acceptance form names
both: each locked edit raises `SchemaLockViolation`, **through `M-PKG`**, so this module
implements no second check.

The **exact-exception half** is green in the contract suite (`TC-CALIB-C06`'s sweep: each
of the seven locked fields routed through the catalog raises `SchemaLockViolation` naming
the field, with the catalog's own violation counter proving the refusal never came from a
caller-side copy). What no green test carried before this file is the plan's **second
oracle — the import-graph assertion** that `M-CALIB` implements no second check, landed
here at the artifact rung where the repo's structural scans live (`test_import_graph.py`'s
reasoning: parsed, not grepped — an aliased or function-scoped spelling is invisible to a
line scan, and comments are not in the AST at all):

1. **One definition** — `SchemaLockViolation` is a class definition in `aeh.pkg` alone, and
   `aeh.calib` does not subclass it: a wrapper class with the same name and the same
   message is a second implementation of the lock wearing the first's clothes, and an
   `except SchemaLockViolation` in a caller would catch the copy while the real guard
   drifted. The runtime identity assertion closes the re-export loophole: the name
   `aeh.calib` publishes (its `__all__` carries it) **is** `M-PKG`'s class object.
2. **No raise site** — no statement in `aeh.calib` raises `SchemaLockViolation` (or a
   subclass of it). The module's refusals (`CalibrationError` and its family) are route
   and configuration errors; the lock's refusal belongs to the one implementation the
   every-edit-through-M-PKG routing guarantees (`TC-CALIB-C06`).
3. **The route exists** — `aeh.calib` imports `aeh.pkg` for real (module scope, not a
   `TYPE_CHECKING`-only edge): the dependency direction the clause names, the route every
   calibration edit takes to reach the one guard.
4. **The vocabularies reconcile** — `M-CALIB`'s sweep vocabulary (`LOCKED_FIELD_NAMES`,
   the HLD's seven words) is covered by `M-PKG`'s lock (`SCHEMA_LOCK_FIELDS`, the guard's
   SQL-shaped `(table, field)` strings, resolved through `_LOCKED_FIELD_HLD_NAMES`, the
   module's own declared bridge) — and nothing in the lock resolves outside the sweep's
   words. Neither direction of a drift is tolerable: a swept field the lock does not
   guard is a door that silently succeeds, and a locked field the sweep never drives
   through is a hole whose regression would refuse nothing.

The plan's seven, in its own words, are: weights (`max_points`), criterion count
(`criterion_count`), band sets and the band-to-points mapping (`criterion_band`), the
scoring-model classification (`scoring_model`), question type (`question_type`) and the
dependency graph (`criterion_dependency`) — plus `construct_tag`, which `FR-PKG-03`'s
verbatim lock list carries and the design's sweep vocabulary (`tests/support/
calib_vocabulary.py`) transcribes.

**Positive controls are part of the case**, for the same reason `TC-PROV-05`'s are not
decoration: an AST scan that matches nothing scores zero violations over a clean tree,
which is exactly what a correct scan scores. Each refusal shape the scan must catch is fed
to it as synthetic module source, in its own test, so a failure report distinguishes "the
tree grew a second lock" from "the detector broke".
"""

from __future__ import annotations

import ast
from pathlib import Path

from aeh.calib import LOCKED_FIELD_NAMES
from aeh.pkg import SCHEMA_LOCK_FIELDS, SchemaLockViolation, _LOCKED_FIELD_HLD_NAMES

_SRC = Path(__file__).resolve().parents[2] / "src" / "aeh"
_CALIB_SOURCE = (_SRC / "calib.py").read_text(encoding="utf-8")


def _exception_name(node: ast.expr | None) -> str | None:
    """The trailing name of a raise's exception expression, through calls and attributes.

    `raise SchemaLockViolation(...)`, `raise pkg.SchemaLockViolation(...)` — every
    non-aliased spelling reduces here to its final name segment, which is what "raises the
    lock" means for a scan that must not depend on how the name is spelled at the site.
    An alias (`Lock` bound by an import-as or an assignment) resolves one step further, in
    `_raises_of`.
    """
    if isinstance(node, ast.Call):
        return _exception_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _alias_map(tree: ast.Module) -> dict[str, str]:
    """Module-level bindings of a name to another name: import-aliases and assignments.

    `from aeh.pkg import SchemaLockViolation as Lock` and `Lock = SchemaLockViolation` both
    bind `Lock` to the lock's class, and a raise spelled through either is the same
    refusal — the exact spelling a second check would adopt to hide from a bare-name scan.
    Only module level is scanned: that is where a module wires its refusal type, and a
    function-local rebinding of an exception class is not how this codebase names refusals.
    """
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            aliases.update(
                (alias.asname, alias.name) for alias in node.names if alias.asname
            )
        elif isinstance(node, ast.Import):
            aliases.update(
                (alias.asname, alias.name) for alias in node.names if alias.asname
            )
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Name)
        ):
            aliases[node.targets[0].id] = node.value.id
    return aliases


def _raises_of(source: str, exception: str) -> list[str]:
    """Every raise in `source` whose exception resolves to a name ending in `exception`."""
    tree = ast.parse(source)
    aliases = _alias_map(tree)
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and node.exc is not None:
            name = _exception_name(node.exc)
            if name is None:
                continue
            name = aliases.get(name, name)
            if name.endswith(exception):
                names.append(name)
    return names


def _class_definitions_named(source: str, name: str) -> list[str]:
    """Every `class <name>` in the source, plus every class whose bases name it."""
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            base_names = [
                base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                for base in node.bases
            ]
            if node.name == name or name in base_names:
                found.append(node.name)
    return found


def _imports_of(source: str, module: str) -> list[str]:
    """The spellings by which `source` imports `module` at module scope.

    Only top-level statements count: an import deferred under `if TYPE_CHECKING:` (or
    any guard) is documentation, not a route — the module's calls never resolve through
    it at import time, so it cannot carry an edit to the guard. `ast.walk` would descend
    into the guard's body and score a deferred edge as a route; `tree.body` does not.
    """
    tree = ast.parse(source)
    edges = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == module:
            edges.append(", ".join(alias.name for alias in node.names))
        if isinstance(node, ast.Import):
            edges.extend(
                alias.name
                for alias in node.names
                if alias.name == module or alias.name.startswith(module + ".")
            )
    return edges


# --- the case ------------------------------------------------------------------------------------


def test_tc_calib_07_the_lock_is_defined_exactly_once_and_calib_does_not_copy_it():
    """One class definition, in `M-PKG`; no subclass in `M-CALIB`; the re-export is the
    same object."""
    carrying = [
        path.name
        for path in sorted(_SRC.glob("*.py"))
        if _class_definitions_named(
            path.read_text(encoding="utf-8"), SchemaLockViolation.__name__
        )
    ]
    assert carrying == ["pkg.py"], (
        f"SchemaLockViolation is defined or subclassed in {carrying}; FR-PKG-03's lock has "
        "one implementation and TC-CALIB-07's oracle is that M-CALIB implements no second "
        "check — a copy or a subclass here is a second lock that drifts (RISK-06)"
    )
    import aeh.calib
    import aeh.pkg

    assert aeh.calib.SchemaLockViolation is aeh.pkg.SchemaLockViolation, (
        "aeh.calib's SchemaLockViolation is not M-PKG's class object — a subclass or a "
        "redefinition would satisfy a caller's except clause while refusing nothing"
    )


def test_tc_calib_07_no_raise_site_in_calib_implements_the_lock():
    """No statement in `aeh.calib` raises the lock's exception — the refusal is the
    catalog's, reached by routing, never performed here.

    A second check does not need a second class to be a second check: a guard that raises
    the imported type is the same drift with one less symbol. The behavioral provenance
    half of this claim (the violation counter moves only when the catalog refuses) is the
    contract sweep's green assertion; this is its structural twin.
    """
    raises = _raises_of(_CALIB_SOURCE, SchemaLockViolation.__name__)

    assert not raises, (
        f"aeh.calib raises SchemaLockViolation itself ({raises}). FR-CALIB-07: every "
        "calibration edit is subject to M-PKG's §6.2 lock, and the module implements no "
        "second check — a refusal raised before the catalog's guard is a lock that drifts "
        "from the one implementation (RISK-06)."
    )


def test_tc_calib_07_the_route_to_the_one_guard_exists_in_the_import_graph():
    """`aeh.calib` imports `aeh.pkg` for real: the dependency direction the clause names.

    A calibration edit reaches the lock only by calling through M-PKG, so the import edge
    is the clause's acceptance form — an import-graph assertion over the source. A missing
    edge would mean edits are checked by something else (a second implementation); a
    `TYPE_CHECKING`-only edge would mean the surface is documentation, not a route.
    """
    edges = _imports_of(_CALIB_SOURCE, "aeh.pkg")

    assert edges, (
        "aeh.calib does not import aeh.pkg — there is no route from a calibration edit to "
        "M-PKG's §6.2 guard, so whatever refuses locked edits is not the one implementation "
        "(FR-CALIB-07, TC-CALIB-07's import-graph oracle)"
    )


def test_tc_calib_07_the_sweep_vocabulary_and_the_lock_cover_the_same_seven_fields():
    """Every field `M-CALIB`'s sweep names is one `M-PKG` guards, and conversely.

    The two modules state the lock in different vocabularies on purpose: `M-PKG` guards
    SQL-shaped `(table, field)` strings (`SCHEMA_LOCK_FIELDS`, thirteen of them — the
    one place the list lives, `NFR-PKG-03`), and `M-CALIB` sweeps the HLD's seven words
    (`LOCKED_FIELD_NAMES`). They reconcile through `M-PKG`'s own declared bridge
    (`_LOCKED_FIELD_HLD_NAMES`), resolved exactly the way the guard's refusal message
    resolves a field: the bridge first, then the guard string's own spelling when it
    already is the HLD's word (`max_points`, `question_type`, `scoring_model`,
    `construct_tag`), then the table the edit acts on (`criterion_dependency.add` is an
    edit of the dependency graph — the table name is the HLD's word there).

    The equality is asserted in both directions because the failure modes differ: a
    swept field with no guard tuple is a route the lock does not protect (a door that
    silently succeeds), and a guard entry that resolves outside the sweep's words is a
    refusal the sweep never drives through (its regression would be silent).
    """
    hld_vocabulary = set(LOCKED_FIELD_NAMES)

    def hld_name(table: str, field: str) -> str:
        """`M-PKG`'s own derivation, mirrored: bridge, then native, then the table."""
        guard = f"{table}.{field}"
        if guard in _LOCKED_FIELD_HLD_NAMES:
            return _LOCKED_FIELD_HLD_NAMES[guard]
        if field in hld_vocabulary:
            return field
        return table

    covered = {hld_name(table, field) for table, field in SCHEMA_LOCK_FIELDS}

    assert covered == hld_vocabulary, (
        f"M-CALIB's sweep vocabulary {sorted(hld_vocabulary)} and the fields M-PKG's lock "
        f"resolves to {sorted(covered)} disagree. A swept field the lock does not guard "
        "succeeds silently; a guarded field the sweep never drives through refuses nothing "
        "when its guard regresses (RISK-06, TC-CALIB-07)."
    )
    assert len(hld_vocabulary) == 7, (
        f"the HLD's §6.2 vocabulary carries {len(hld_vocabulary)} fields; the design names "
        "seven — weights, criterion count, band sets and their band-to-points mapping, "
        "scoring-model classification, question type, construct tags and the dependency graph"
    )


# --- positive controls: the scan catches every shape of a second lock -----------------------------


def test_the_scan_catches_a_second_definition_of_the_lock():
    """A second `class SchemaLockViolation` (or a subclass of it) is the exact thing this
    case exists to refuse; the scan must report it, not score a clean tree."""
    second = (
        "from aeh.pkg import SchemaLockViolation as _Base\n"
        "class SchemaLockViolation(_Base):\n"
        "    pass\n"
        "def check(field):\n"
        "    raise SchemaLockViolation(field)\n"
    )
    assert _class_definitions_named(second, "SchemaLockViolation") == [
        "SchemaLockViolation"
    ]
    assert _raises_of(second, "SchemaLockViolation") == ["SchemaLockViolation"]


def test_the_scan_catches_a_raise_through_an_alias():
    """A raise through an aliased binding is the same second check.

    `from aeh.pkg import SchemaLockViolation as Lock` followed by `raise Lock(...)`, and
    the assignment alias `Lock = SchemaLockViolation` — both spellings are invisible to a
    line scan for the bare name, and both are the refusal implemented outside `M-PKG`.
    The scan resolves module-level aliases one step, so neither spelling slips through.
    """
    imported_alias = (
        "from aeh.pkg import SchemaLockViolation as Lock\n\n\n"
        "def check(field):\n"
        "    raise Lock(field)\n"
    )
    assigned_alias = (
        "from aeh.pkg import SchemaLockViolation\n\n"
        "Lock = SchemaLockViolation\n\n\n"
        "def check(field):\n"
        "    raise Lock(field)\n"
    )
    assert _raises_of(imported_alias, "SchemaLockViolation") == ["SchemaLockViolation"], (
        "the import-aliased raise was not resolved to the lock — the one spelling a "
        "bare-name scan misses, and exactly the shape a second check would take"
    )
    assert _raises_of(assigned_alias, "SchemaLockViolation") == ["SchemaLockViolation"], (
        "the assignment-aliased raise was not resolved to the lock"
    )


def test_the_scan_catches_an_attribute_scoped_raise():
    """`raise pkg.SchemaLockViolation(...)` — the refusal performed through the module
    attribute rather than the imported name. Same second check, same catch."""
    scoped = "import aeh.pkg as pkg\n\n\ndef check(field):\n    raise pkg.SchemaLockViolation(field)\n"
    assert _raises_of(scoped, "SchemaLockViolation") == ["SchemaLockViolation"], (
        "the attribute-scoped raise was not caught"
    )


def test_the_route_scan_refuses_a_deferred_edge():
    """A `TYPE_CHECKING`-deferred import is documentation, not a route — the scan must
    not score it as the guard's edge, or a module could claim the dependency while
    resolving none of its calls through it at import time."""
    deferred = (
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n"
        "    from aeh.pkg import SchemaLockViolation\n\n\n"
        "def check(field):\n"
        "    raise SchemaLockViolation(field)\n"
    )
    assert _imports_of(deferred, "aeh.pkg") == [], (
        "a TYPE_CHECKING-deferred edge scored as a route — the module resolves nothing "
        "through it at import time, so it cannot carry an edit to the guard"
    )


def test_the_scan_does_not_report_ordinary_refusals():
    """The negative control. `M-CALIB` raises its own refusal family all over —
    `CalibrationError`, `TriageCategoryRequired`, `PhaseDependencyError` — and a scan that
    reports those is a nuisance that gets switched off, which is how a real second check
    would land unnoticed."""
    ordinary = (
        "def check():\n"
        "    raise CalibrationError('refused')\n"
        "    raise TriageCategoryRequired('category')\n"
        "    raise PhaseDependencyError('pre-lock vintage')\n"
    )
    assert _raises_of(ordinary, "SchemaLockViolation") == [], (
        "the scan reported M-CALIB's own refusal family — a nuisance scan gets switched "
        "off, and then a real second check lands unnoticed"
    )
    assert _class_definitions_named(ordinary, "SchemaLockViolation") == []