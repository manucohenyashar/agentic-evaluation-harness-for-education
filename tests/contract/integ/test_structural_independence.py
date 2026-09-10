"""`CT-INTEG-05` — independence is structural, not procedural
(`TC-INTEG-C05`).

Case of test plan §6.11.9; TS-66 (issue #77). Written ahead of `#74` (the
M-INTEG module file) and `#68` (the M-EXTRACT module file).

The clause: M-INTEG "is not inside `M-EXTRACT` and shares no code path with
it, so a single extraction error cannot both produce the evidence and certify
it" (R19, ADR-12) — and a consumer relying on the R19 guarantee is relying on
THIS clause, so the case is release-gating and asserts the structure itself,
not a coding convention. Three structural facts, each checkable without
running either module:

1. **Not inside** — the certifier's file is not located within the producer's
   package tree (and vice versa): the ADR-12 boundary is physical, a module
   boundary, not a folder convention.
2. **No reach** — neither module's transitive first-party import closure
   contains any module of the other, directly or through a helper. The
   declared read-dependency on the extractor's span payload rides the
   injected `ExtractionView` (the #75 table), never an import — that
   inversion is what makes "shares no code path" satisfiable at all.
3. **No shared private code path** — the two closures, minus the declared
   public seams, are disjoint. A private helper both sides import is the
   self-certification scenario through the back door: the same buggy
   byte-slicer that produces the span also verifies it, and the verification
   reproduces the extraction's mistake.

**Disclosures register** (nothing new is minted beyond the #75 table):

| Name | Status |
|---|---|
| public seams | the aeh top-level modules that exist before this story and are neither of the pair (`conf`, `det`, `ingest`, `orch`, `pkg`, `prov`, `setup`, `store`) plus the package root — enumerated by name below so a NEW public module fails this case until it joins the list deliberately. Both sides reading the same canonical markdown through M-INGEST, or the same store through M-STORE, is the declared coordinate system, not a code path the pair shares |
| checker shape | static AST over the module files (a `state` clause: it holds for paths never exercised); import targets are followed only where they resolve to a first-party file on disk, so third-party and stdlib imports are out of scope and function-level `from X import name` never fabricates a module |
| synthetic teeth | the checker is proven against mini-packages under `tmp_path` (faithful pair, self-certification mutant, shared-private-helper mutant, physical-containment mutant) AND against the real landed tree below |
| `EXTRACT_MODULE:prompt_fields` | the representative symbol standing for "the M-EXTRACT module file exists" (the `#68 review` registry precedent), exactly as `INTEG_MODULE:verify_span` stands for M-INTEG |
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import aeh

from tests.support.impl import EXTRACT_MODULE, INTEG_MODULE, require

pytestmark = pytest.mark.contract

#: The aeh top-level modules that predate the pair — the declared public seams
#: both sides may read through. A new aeh module fails the real-tree assertion
#: until it is added here ON PURPOSE (that decision is the reconcile point).
REAL_SEAMS = frozenset({
    "aeh",
    "aeh.conf",
    "aeh.det",
    "aeh.ingest",
    "aeh.orch",
    "aeh.pkg",
    "aeh.prov",
    "aeh.setup",
    "aeh.store",
})


# --- the checker ----------------------------------------------------------------------------


def _resolves(name: str, src_root: Path) -> bool:
    """Whether dotted module `name` names a real first-party file under `src_root`."""
    rel = Path(*name.split("."))
    return (src_root / rel.with_suffix(".py")).is_file() or (
        (src_root / rel / "__init__.py").is_file())


def _imported_modules(source: str, module_name: str, is_package: bool,
                      src_root: Path) -> set[str]:
    """The first-party modules `source`'s imports execute, resolved against `src_root`.

    `import a.b` contributes `a.b`; `from a.b import f` contributes `a.b` plus
    `a.b.f` only if `a.b.f` is itself a module on disk; relative imports are
    resolved against the importing module's own dotted name.
    """
    targets: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            targets |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = module_name.split(".")
                if not is_package:
                    parts = parts[:-1]
                parts = parts[: max(len(parts) - (node.level - 1), 0)]
                full = ".".join(parts + ([node.module] if node.module else []))
            else:
                full = node.module or ""
            if full and _resolves(full, src_root):
                targets.add(full)
            for alias in node.names:
                if alias.name == "*":
                    continue
                candidate = f"{full}.{alias.name}" if full else alias.name
                if _resolves(candidate, src_root):
                    targets.add(candidate)
    return targets


def _modules_under(root: Path, src_root: Path) -> dict[str, Path]:
    """Dotted module name -> file, for a module file or package directory."""
    files = [root] if root.is_file() else sorted(root.rglob("*.py"))
    modules: dict[str, Path] = {}
    for path in files:
        parts = path.relative_to(src_root).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            modules[".".join(parts)] = path
    return modules


def _closure(entry: Path, src_root: Path) -> set[str]:
    """The transitive first-party import closure of one module (file or package)."""
    seen: set[str] = set()
    queue = _modules_under(entry, src_root)
    while queue:
        name, path = queue.popitem()
        if name in seen:
            continue
        seen.add(name)
        is_package = path.name == "__init__.py"
        for target in _imported_modules(path.read_text(encoding="utf-8"), name,
                                        is_package, src_root):
            if target in seen or not _resolves(target, src_root):
                continue
            rel = Path(*target.split("."))
            file = src_root / rel.with_suffix(".py")
            queue[target] = file if file.is_file() else src_root / rel / "__init__.py"
    return seen


def _resolve_module(src_root: Path, name: str) -> Path:
    """The file or package directory of a top-level module name."""
    for candidate in (src_root / f"{name}.py", src_root / name):
        if candidate.exists():
            return candidate
    raise AssertionError(f"{name} does not exist under {src_root}")


def _assert_structurally_independent(producer: Path, certifier: Path,
                                     src_root: Path, seams: frozenset[str]) -> None:
    """The clause's three structural facts, asserted in order of proximity."""
    # 1. not inside: the boundary is a module boundary, physical.
    for inside, outer, label in ((certifier, producer, "the certifier"),
                                 (producer, certifier, "the producer")):
        assert outer.resolve() not in inside.resolve().parents, (
            f"{label}'s code sits INSIDE the other module's package tree "
            f"({inside.name} under {outer.name}) — the ADR-12 boundary is not "
            "structural, and CT-INTEG-05's consumer guarantee is void"
        )
    producer_closure = _closure(producer, src_root)
    certifier_closure = _closure(certifier, src_root)

    # 2. no reach, either direction.
    producer_modules = set(_modules_under(producer, src_root))
    certifier_modules = set(_modules_under(certifier, src_root))
    reached = producer_modules & certifier_closure
    assert not reached, (
        f"the certifier's import closure reaches the producer's modules "
        f"{sorted(reached)} — the module that produced the evidence is in the code "
        "path that certifies it, the self-certification R19 forbids"
    )
    reached_back = certifier_modules & producer_closure
    assert not reached_back, (
        f"the producer's import closure reaches the certifier's modules "
        f"{sorted(reached_back)} — the producer pre-verifies its own output, the "
        "same single code path producing and certifying (R19, ADR-12)"
    )

    # 3. no shared private code path: the closures' intersection outside the
    # declared public seams must be empty.
    shared = (producer_closure & certifier_closure) - seams
    assert not shared, (
        f"the producer and the certifier share the private code path(s) "
        f"{sorted(shared)} — one bug there both produces the evidence and certifies "
        "it; shared seams must be public, declared modules only (CT-INTEG-05)"
    )


# --- the teeth: the checker on synthetic mini-packages, green now ---------------------------


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _synthetic_tree(tmp_path: Path, *, integ_imports: str, rows_imports: str,
                    nested_integ: bool = False) -> tuple[Path, Path, Path]:
    """A faithful mini-pipeline: producer package, certifier module, one public
    seam — with the two import lines parameterized so each mutant is one string."""
    src = tmp_path / "syn"
    _write(src / "store_like.py", "def read():\n    return ()\n")
    _write(src / "extract_like" / "__init__.py", "")
    _write(src / "extract_like" / "rows.py",
           f"{rows_imports}\n\ndef rows():\n    return ()\n")
    integ = (src / "extract_like" / "integ_like.py" if nested_integ
             else src / "integ_like.py")
    _write(integ, f"{integ_imports}\n\ndef verify():\n    return True\n")
    return src, src / "extract_like", integ


def test_tc_integ_c05_the_independence_checker_accepts_a_faithful_pair(tmp_path):
    """`TC-INTEG-C05`'s executable construction, faithful limb — two modules
    that read the same public seam and nothing else pass all three structural
    facts. Green: this asserts the checker's acceptance, not the implementation."""
    src, producer, certifier = _synthetic_tree(
        tmp_path,
        integ_imports="import store_like",
        rows_imports="import store_like",
    )
    _assert_structurally_independent(producer, certifier, src,
                                     frozenset({"store_like"}))


def test_tc_integ_c05_a_self_certifying_import_is_rejected(tmp_path):
    """`TC-INTEG-C05`'s teeth, mutant A — the certifier importing the producer
    (the lazy shortcut: call the extractor's own rows function to verify its
    spans) goes red on the reach limb."""
    src, producer, certifier = _synthetic_tree(
        tmp_path,
        integ_imports="import store_like\nfrom extract_like.rows import rows",
        rows_imports="import store_like",
    )
    with pytest.raises(AssertionError, match="reaches the producer's modules"):
        _assert_structurally_independent(producer, certifier, src,
                                         frozenset({"store_like"}))


def test_tc_integ_c05_a_shared_private_helper_is_rejected(tmp_path):
    """`TC-INTEG-C05`'s teeth, mutant B — a private `_span_utils` both sides
    import (the same slicer producing and verifying the span) goes red on the
    shared-code-path limb even though neither module imports the other."""
    src, producer, certifier = _synthetic_tree(
        tmp_path,
        integ_imports="import store_like\nimport _span_utils",
        rows_imports="import store_like\nimport _span_utils",
    )
    _write(src / "_span_utils.py", "def slice_bytes():\n    return b''\n")
    with pytest.raises(AssertionError, match="share the private code path"):
        _assert_structurally_independent(producer, certifier, src,
                                         frozenset({"store_like"}))


def test_tc_integ_c05_a_certifier_inside_the_producer_package_is_rejected(tmp_path):
    """`TC-INTEG-C05`'s teeth, mutant C — the certifier's file dropped inside
    the producer's package (independence by folder naming, not by boundary)
    goes red on the physical limb before any import is even parsed."""
    src, producer, certifier = _synthetic_tree(
        tmp_path,
        integ_imports="import store_like",
        rows_imports="import store_like",
        nested_integ=True,
    )
    with pytest.raises(AssertionError, match="INSIDE"):
        _assert_structurally_independent(producer, certifier, src,
                                         frozenset({"store_like"}))


# --- the real tree ---------------------------------------------------------------------------


def test_tc_integ_c05_the_landed_pair_is_structurally_independent():
    """`TC-INTEG-C05` — the clause against the real tree: the landed M-INTEG
    and M-EXTRACT are separate module trees, neither's import closure reaches
    the other's code, and their closures intersect only at the declared public
    seams. A consumer relying on R19's separation relies on this assertion
    holding for every path neither module's own FR cases exercise."""
    require(INTEG_MODULE, "verify_span", issue="#74")
    require(EXTRACT_MODULE, "prompt_fields", issue="#68")
    src_root = Path(aeh.__file__).resolve().parent
    _assert_structurally_independent(
        _resolve_module(src_root, "extract"),
        _resolve_module(src_root, "integ"),
        src_root,
        REAL_SEAMS,
    )
