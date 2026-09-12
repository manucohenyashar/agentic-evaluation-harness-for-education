"""`TS-47` (issue #128) — the HLD §11.6 interface invariants as **artifact assertions**.

Test plan §5.19's artifact-assertion cases against the landed console. The contract suite
(`tests/contract/console/`, TS-76/TS-77) asserts the §6.11.19 clause cases at runtime; this
file carries the three cases whose *named oracle* is a statement about the module's own shape
rather than about a rendered page or a return value — the oracles the clause cases cannot
supply because they are true of the file, not of an app instance:

* `TC-CONSOLE-03` (`FR-CONSOLE-03`, invariant 14, P0) — the console writes no field any
  scoring prompt reads, and exposes no per-student annotation surface. Oracle: an
  **import-graph assertion**. The runtime halves are already asserted by
  `test_ct_console_isolation_and_binding.py` (`CT-CONSOLE-C04`: the post-lock write set
  against `SCORING_PROMPT_FIELDS`, the annotation-field sweep, the resumed-request
  whitelist). What no runtime sweep can see is the *door*: the scoring prompt is assembled
  by `aeh.judge` (`assemble`/`assemble_prompt`) and the transport request by `aeh.extract`
  (`assemble_request`) — if the console imported that surface, it could construct a
  prompt-shaped payload and write it into the ledger through a service the write-set sweep
  never sees as a console field. The assertion is that no such edge exists: the console
  names `aeh.judge` and `aeh.extract` only as **bare migration-chain imports** (the
  completeness duty before any store open, `#234`), never at symbol level and never
  dynamically.

* `TC-CONSOLE-08` (`FR-CONSOLE-08`, invariant 3, P0) — the run monitor, **during a live
  run**, over real ledger rows: progress renders at (stage, criterion, judge) granularity
  and no per-student figure exists on the page. `CT-CONSOLE-C09` sweeps the API payloads
  and the `ProgressReport` object; the poll contract renders the monitor's standing shape
  over an empty ledger. Neither reads the renderer against *populated* ledger state —
  which is the case's own precondition ("the run monitor during a live run") and the one
  place a per-student grouping could render from data the console actually holds: the
  `work_unit` rows it reads carry `submission_id`, so a renderer that derived per-student
  figures would put those identifiers on the page. Asserted both ways: every ledger group
  renders as its line, and no submission identifier the ledger carries appears anywhere in
  the HTML.

* `TC-CONSOLE-36` (`NFR-CONSOLE-05`, P1) — the console's dependency edges: *"it only reads
  stores and writes the enumerated control rows, so it is replaceable without touching the
  harness"*. Oracle: an **import-graph assertion**. `CT-CONSOLE-C21` asserts the runtime
  coupling surface (`actual_couplings` ⊆ reads ∪ writes); a module-level import is a
  coupling no runtime attribute records, and it is the kind a replacement console would
  have to reproduce without the design ever mentioning it. The assertion freezes the file's
  import edges — set equality, in both directions, at two granularities — and asserts the
  module holds no egress-capable import of its own (`import_graph.scan_module` with the
  `TC-PROV-05` forbidden roots; the tree-wide scan in `test_import_graph.py` covers every
  module, this one re-asserts it for the module whose replaceability is the clause).

`TC-CONSOLE-32`'s full block names an import-graph assertion for its step 4 ("no write path
writes a field any scoring prompt reads"); that oracle is the `TC-CONSOLE-03` test below and
is not duplicated. No case here carries `writtenahead`: `M-CONSOLE` is complete, so all three
assert green against the landed module — the story's remaining console-keyed blockers
(`#107`'s `render_grade_coverage` limbs, `#119`'s `TOO_FEW_QUALIFIER`) name surfaces this
story does not touch.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from html import escape

from aeh.store import open_store
from tests.support.console_vocabulary import elements
from tests.support.import_graph import FORBIDDEN_ROOTS, scan_module
from tests.support.impl import CONSOLE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run


# --- the import-edge reader both static cases stand on -------------------------------------------


@dataclass(frozen=True)
class ImportEdges:
    """Every import edge out of one module's source, sorted by the shape of the edge.

    The distinction between the first two fields is load-bearing for `TC-CONSOLE-03`: a bare
    `import aeh.judge` is the migration-chain completeness duty the store's open requires
    (#234) — the case's declared exception. It still binds the module object, so
    `aeh.judge.assemble_prompt(...` remains a runtime call this static oracle cannot see;
    what guards that door is C04's write-set sweep, which is why the case pairs the two
    oracles. The symbol-level field is the half the invariant-14 import ban constrains: a
    walker that recorded only module names would have to ban the chain import too, fail the
    shipped console, and prove nothing about symbol-pulling. The edge shape, not the module
    name, is what the invariant constrains.
    """

    #: `import aeh.judge` — the module edge only, no symbol pulled.
    bare_modules: tuple[str, ...]
    #: `from aeh.judge import assemble_prompt` — the symbol-carrying edges, by module.
    symbol_modules: tuple[str, ...]
    #: `importlib.import_module("aeh.judge")` / `__import__("aeh.judge")` — the dynamic door.
    dynamic_targets: tuple[str, ...]
    #: Every import root (the first dotted segment), across all three shapes.
    all_roots: tuple[str, ...]
    #: Relative imports (`from . import x`), which cannot leave the package — recorded so a
    #: caller that expects none can assert that rather than silently not see them.
    relative_modules: tuple[str, ...]


def _dynamic_import_aliases(tree: ast.AST) -> set[str]:
    """The callee names that reach a dynamic import, `import_module` under any alias.

    `from importlib import import_module as im` makes `im("aeh.judge")` a working dynamic
    import that a check on the callee's literal name would miss — the same lesson
    `tests/support/import_graph.py` encodes for the provider SDKs, reused here rather than
    imported, so this oracle's teeth do not move when the walker's internals do.
    """
    aliases = {"import_module", "__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "importlib" and node.level == 0:
            for alias in node.names:
                if alias.name == "import_module" and alias.asname:
                    aliases.add(alias.asname)
    return aliases


def _import_edges(source: str) -> ImportEdges:
    """Parse the source and return its import edges.

    Walks the **whole** AST, not just module level: a function-scoped
    `from aeh.judge import assemble_prompt` is a working import and a perfectly working way
    to reach the assembly surface, so a module-level-only scan would be the loophole-shaped
    version of this oracle. Dynamic imports are caught at both spellings, in either argument
    position, and under aliases.
    """
    tree = ast.parse(source, filename="<console.py>")
    aliases = _dynamic_import_aliases(tree)

    bare: list[str] = []
    symbols: list[str] = []
    dynamic: list[str] = []
    relative: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bare.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                relative.append(node.module or "")
            elif node.module == "aeh":
                # `from aeh import judge` binds the module object exactly as
                # `from aeh.judge import assemble_prompt` binds a symbol — recorded at the
                # imported name, not the parent, or the assembly surface reachable through
                # this spelling is invisible to the invariant-14 oracle. A re-exported
                # non-module name records the same way and is an undeclared symbol edge
                # either way; failing on it is the conservative direction for this oracle.
                symbols.extend(f"aeh.{alias.name}" for alias in node.names)
            elif node.module:
                symbols.append(node.module)
        elif isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if called in aliases:
                for argument in (
                    *node.args,
                    *(keyword.value for keyword in node.keywords),
                ):
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        dynamic.append(argument.value)

    roots = [name.split(".")[0] for name in (*bare, *symbols, *dynamic)]
    return ImportEdges(
        bare_modules=tuple(bare),
        symbol_modules=tuple(symbols),
        dynamic_targets=tuple(dynamic),
        all_roots=tuple(roots),
        relative_modules=tuple(relative),
    )


def _is_within(module: str, roots: tuple[str, ...]) -> bool:
    """Whether `module` is one of `roots` or a submodule of one (`aeh.judge.sub` ⊂ `aeh.judge`)."""
    return any(module == root or module.startswith(f"{root}.") for root in roots)


#: The modules that own the prompt/request assembly surface — the two the invariant-14
#: import edge must not reach. Pinned here with their assembly entry points so the guard
#: follows the code that actually builds prompts: if the surface moved to another module,
#: the precondition anchors below go red loudly instead of this test silently guarding a
#: file that no longer assembles anything.
_PROMPT_ASSEMBLY_MODULES: tuple[str, ...] = ("aeh.judge", "aeh.extract")

#: The console's shipped migration-chain imports, name-only. The store refuses to open on a
#: truncated chain (`IncompleteMigrationChainError`, `#234`), so the console — which opens
#: stores — carries these imports as its completeness duty. `TC-CONSOLE-03`'s exception for
#: them is anchored on this set, and `TC-CONSOLE-36` freezes it.
_CONSOLE_BARE_MIGRATION_IMPORTS: frozenset[str] = frozenset(
    {
        "aeh.agg",
        "aeh.det",
        "aeh.extract",
        "aeh.grade",
        "aeh.ingest",
        "aeh.integ",
        "aeh.judge",
        "aeh.orch",
        "aeh.pkg",
        "aeh.synth",
    }
)

#: The modules the console pulls **symbols** from, and why each is a declared edge of the
#: seam `NFR-CONSOLE-05` names. Everything else is a coupling a replacement console would
#: have to reproduce without the design mentioning it.
#:
#: - `aeh.store` — the seam itself: reads and control-row writes go through the tier handles.
#: - `aeh.conf` — config types (`CohortRef`, `ModelRef`, `resolve_run_config`).
#: - `aeh.review` — the review constants the queue renders (`REVIEW_DEFAULT_BANDS`, the
#:   blind-reserve minutes): read-only vocabulary, `M-REVIEW`'s declared shape.
#: - `aeh.grade`, `aeh.orch`, `aeh.pkg`, `aeh.det` — the domain owners §11.8's control
#:   actions delegate to (`GradingService.finalize_batch`, the orchestrator's control-row
#:   application, the package catalog S1 reads, `DeterministicEvaluator` for S12's key
#:   correction re-derivation).
_CONSOLE_SYMBOL_IMPORT_MODULES: frozenset[str] = frozenset(
    {"aeh.conf", "aeh.det", "aeh.grade", "aeh.orch", "aeh.pkg", "aeh.review", "aeh.store"}
)


# --- TC-CONSOLE-03 — no import edge reaches the prompt-assembly surface ---------------------------


def test_tc_console_03_console_imports_no_surface_that_assembles_a_scoring_prompt(repo_root):
    """`TC-CONSOLE-03` / `FR-CONSOLE-03` (invariant 14) — the import-graph oracle.

    *"Writes no field any scoring prompt reads; exposes no per-student annotation surface."*
    The write-set half is asserted at runtime by `CT-CONSOLE-C04` (the post-lock write set
    against `SCORING_PROMPT_FIELDS`, the annotation-field sweep) — and a runtime sweep is
    exactly what cannot see the static door. The scoring prompt is assembled in `aeh.judge`
    and the transport request in `aeh.extract`; an import of that surface would let the
    console construct a prompt-shaped payload and land it in the ledger by calling a
    borrowed service — a write path that is not in the enumerated fifteen because it is not
    a control action at all. The clause's named oracle is the import graph, so the assertion
    is about the edges: the console names the two assembly modules only as bare
    migration-chain imports, never at symbol level, never dynamically, at any scope.

    Two controls keep the oracle from being vacuous. First, the guarded modules are
    anchored as the real assembly owners — if the surface moved, this test fails naming the
    move rather than passing over a file it no longer understands. Second, the scanner is
    proven able to fire on the exact violation it forbids, over a synthetic snippet — a
    walker that never matched anything would score zero violations over a clean tree and be
    indistinguishable from a correct one (the `test_import_graph.py` lesson).
    """
    console_source = (repo_root / "src" / "aeh" / "console.py").read_text(encoding="utf-8")
    edges = _import_edges(console_source)

    # **Precondition anchors.** The scanner sees this file's imports (it is not scanning
    # nothing), the chain imports it exempts really are here, and the modules it guards
    # really are the assembly owners.
    bare_aeh = [name for name in edges.bare_modules if _is_within(name, ("aeh",))]
    assert len(bare_aeh) >= 10, (
        f"the edge reader found {len(bare_aeh)} bare aeh.* import(s) in console.py — fewer "
        f"than the migration chain requires, so either the file changed or the scanner is "
        f"not seeing the imports this assertion is built on"
    )
    assert {"aeh.judge", "aeh.extract"} <= set(bare_aeh), (
        "the fixture premise moved: aeh.judge/aeh.extract are no longer among console.py's "
        "bare imports, so the exemption this assertion rests on is no longer exercised and "
        "its positive anchor below proves nothing"
    )
    judge_source = (repo_root / "src" / "aeh" / "judge.py").read_text(encoding="utf-8")
    extract_source = (repo_root / "src" / "aeh" / "extract.py").read_text(encoding="utf-8")
    assert "def assemble_prompt" in judge_source and "def assemble(" in judge_source, (
        "aeh.judge no longer defines the assembly surface this guard is anchored on — move "
        "_PROMPT_ASSEMBLY_MODULES to the module that now owns it, or the invariant-14 edge "
        "ban is guarding the wrong file while the real assembly path goes unguarded"
    )
    assert "def assemble_request" in extract_source, (
        "aeh.extract no longer assembles the transport request; re-point "
        "_PROMPT_ASSEMBLY_MODULES before trusting the silence below"
    )

    # **The invariant.** No symbol-level import and no dynamic import reaches the assembly
    # surface, at any nesting depth — the console cannot construct a scoring prompt, so it
    # cannot write one regardless of what its declared write set says.
    reaching = [
        module
        for module in (*edges.symbol_modules, *edges.dynamic_targets)
        if _is_within(module, _PROMPT_ASSEMBLY_MODULES)
    ]
    assert not reaching, (
        f"console.py imports the prompt-assembly surface: {sorted(set(reaching))}. "
        f"TC-CONSOLE-03's oracle is the import graph because the runtime write-set sweep "
        f"cannot see a payload written through a borrowed service — the console must have no "
        f"path to prompt construction at all (invariant 14). The bare `import aeh.judge` the "
        f"migration chain requires is the case's declared exception; what its runtime abuse "
        f"would write is C04's write-set sweep to catch, not this oracle."
    )
    assert not edges.relative_modules, (
        f"console.py carries relative imports ({edges.relative_modules}); every edge this "
        f"case freezes is asserted absolute, so a relative import is an edge the scan would "
        f"not see"
    )

    # **The scanner can fire.** The exact violation this test exists to condemn, on a
    # synthetic module: if the edge reader ever stops matching symbol imports, this control
    # fails instead of the real assertion passing silently.
    control = _import_edges("from aeh.judge import assemble_prompt\n")
    assert _is_within("aeh.judge", _PROMPT_ASSEMBLY_MODULES) and "aeh.judge" in (
        control.symbol_modules
    ), (
        "the import-edge reader no longer detects a symbol-level import of aeh.judge — this "
        "case's real assertion is passing on a scanner that cannot see the violation"
    )
    parent_control = _import_edges("from aeh import judge\n")
    assert "aeh.judge" in parent_control.symbol_modules, (
        "the import-edge reader records `from aeh import judge` at the parent package — the "
        "module object is reachable through that spelling too, so the real assertion above "
        "would pass with that door open"
    )


# --- TC-CONSOLE-36 — the dependency edges are frozen, and there is no egress ----------------------


def test_tc_console_36_console_dependency_edges_are_frozen_and_egress_free(repo_root):
    """`TC-CONSOLE-36` / `NFR-CONSOLE-05` — the import-graph oracle for replaceability.

    *"The console shall be replaceable without touching the harness; the seam is that it
    only reads stores and writes the enumerated control rows."* `CT-CONSOLE-C21` asserts
    the runtime half — `actual_couplings` against reads ∪ writes — but an import is a
    coupling no runtime attribute records: a replacement console written against the
    declared surface would still have to reproduce whatever modules this file imports,
    and a `harness.*` import would make "without touching the harness" false at the
    module boundary, where the clause lives.

    So the edges are **frozen, in both directions, at two granularities** — the same
    both-ways discipline TC-CONSOLE-32's set equality uses. A bare-import set that drifts
    (an eleventh contributor, or a dropped one) fails; a symbol-import set that gains a
    module fails. An import of anything outside the standard library and the declared
    `aeh.*` set — `harness.*`, a third-party client, a future internal package — fails.
    And the module holds no egress-capable import of its own: the tree-wide `TC-PROV-05`
    scan already covers every module, but the clause's oracle is about *this* module's
    edges, so the walker is re-run over it here rather than trusted by implication.

    Both scanners carry positive controls over synthetic snippets, so a future refactor of
    the edge reader that silently stops matching is the failure this test reports, not a
    passing oracle nobody can trust.
    """
    console_source = (repo_root / "src" / "aeh" / "console.py").read_text(encoding="utf-8")
    edges = _import_edges(console_source)

    bare_aeh = {name for name in edges.bare_modules if _is_within(name, ("aeh",))}
    symbol_aeh = {name for name in edges.symbol_modules if _is_within(name, ("aeh",))}

    # **Set equality, both directions, both granularities.** A missing edge and an extra
    # edge fail differently and both matter: the missing one is a chain-completeness duty
    # gone (the store will refuse the open), the extra one is an undeclared coupling.
    assert bare_aeh == set(_CONSOLE_BARE_MIGRATION_IMPORTS), (
        f"console.py's bare aeh.* imports drifted: undeclared {sorted(bare_aeh - set(_CONSOLE_BARE_MIGRATION_IMPORTS))}, "
        f"missing {sorted(set(_CONSOLE_BARE_MIGRATION_IMPORTS) - bare_aeh)}. The bare imports "
        f"are the migration-chain completeness duty (#234); a new bare name in this set is an "
        f"edge no design line declares, and NFR-CONSOLE-05's replaceability claim is frozen "
        f"to the declared set."
    )
    assert symbol_aeh == set(_CONSOLE_SYMBOL_IMPORT_MODULES), (
        f"console.py's symbol-level aeh.* imports drifted: undeclared "
        f"{sorted(symbol_aeh - set(_CONSOLE_SYMBOL_IMPORT_MODULES))}, missing "
        f"{sorted(set(_CONSOLE_SYMBOL_IMPORT_MODULES) - symbol_aeh)}. Each entry in the "
        f"declared set is a seam the design names; a new module here is a coupling a "
        f"replacement console would have to reproduce without the design ever mentioning it."
    )

    # **Nothing outside the standard library and the declared aeh edges.** This is the half
    # that catches `harness.*` — the "without touching the harness" wording, statically.
    foreign_roots = [
        root
        for root in edges.all_roots
        if root not in sys.stdlib_module_names and root != "aeh"
    ]
    assert not foreign_roots, (
        f"console.py imports outside the standard library and the declared aeh set: "
        f"{sorted(set(foreign_roots))}. NFR-CONSOLE-05's seam is 'reads stores, writes "
        f"control rows' — an import of the harness (or of any non-aeh package) is a "
        f"dependency the replacement console cannot reconstruct from the declared surface."
    )

    # **No egress-capable edge of its own.** `TC-PROV-05`'s tree scan covers every module;
    # this re-asserts it for the one module the replaceability clause is about, so the
    # console's own file is auditable in one line rather than by implication. Backend
    # constants are skipped here — the profile refusal names deployment profiles, not
    # backends, and the tree-wide scan already owns that check.
    violations = scan_module(
        "aeh.console",
        console_source,
        "src/aeh/console.py",
        forbidden=FORBIDDEN_ROOTS,
        check_backend_constants=False,
    )
    assert not violations, (
        f"console.py carries an egress-capable import: {violations}. The console performs no "
        f"inference and adds no egress point; a provider SDK or HTTP client in this module is "
        f"a second egress seam NFR-CONSOLE-05's replaceability does not admit."
    )

    # **Both scanners can fire.** Synthetic positives for the exact violations this case
    # condemns: an undeclared root, and an egress-capable import.
    drifting = _import_edges("import aeh.unlisted_module\n")
    assert "aeh" in drifting.all_roots and any(
        name.startswith("aeh.") and name not in _CONSOLE_BARE_MIGRATION_IMPORTS
        and name not in _CONSOLE_SYMBOL_IMPORT_MODULES
        for name in (*drifting.bare_modules, *drifting.symbol_modules)
    ), "the edge reader cannot see a bare import — the root freeze above would pass vacuously"
    egress_control = scan_module(
        "aeh.console",
        "import litellm\n",
        "<synthetic>",
        forbidden=FORBIDDEN_ROOTS,
        check_backend_constants=False,
    )
    assert egress_control, (
        "the egress scan no longer flags a provider SDK import — the no-egress assertion "
        "above would pass on a scanner that matches nothing"
    )


# --- TC-CONSOLE-08 — the live monitor renders the ledger's three dimensions, and nothing finer ----


def _expected_progress_line(row) -> str:
    """The rendered form of one ledger group, as the monitor's own formatter writes it.

    Mirrors `_render_monitor`'s line shape — including `escape()`, the renderer's declared
    HTML transformation — so the oracle compares the ledger against what the page shows,
    with the same transformation applied to both sides.
    """
    return "stage {} · criterion {} · judge {} · status {}: {} units".format(
        escape(str(row["stage"])),
        escape(str(row["criterion_id"] or "")),
        escape(str(row["judge_id"] or "")),
        escape(str(row["status"])),
        row["n"],
    )


def test_tc_console_08_monitor_renders_ledger_groups_and_no_per_student_figure(tmp_data_dir):
    """`TC-CONSOLE-08` / `FR-CONSOLE-08` (invariant 3) — the monitor over a **live run**.

    The case's precondition is "the run monitor during a live run", and that is not a
    decoration: over an empty ledger every monitor renders the same honest empties, and the
    standing shape is all the contract's poll test reads. With real units on the ledger,
    two things become assertable that nothing else asserts:

    - **Granularity** — progress renders at (stage, criterion, judge), and the rendered
      lines are the *ledger's* groups: built here from a direct GROUP BY over the store the
      console was handed, not from the console's own report. A renderer that dropped a
      group, miscounted a group, or rendered a fourth dimension fails against lines the
      ledger says exist.
    - **No per-student figure** — the work_unit rows the monitor reads carry
      `submission_id`; a grouping that derived per-student progress would put those
      identifiers on the page. So the assertion is that none of them appear — anchored by
      reading the same rows back and showing the ledger really names the students the page
      does not.

    Rung 2 (real SQLite, real enumerated ledger, shipped writers throughout): the run is
    created, enumerated and started through `Orchestrator` — no direct SQL anywhere — so
    the ledger state the renderer is read against is the state a live run actually holds.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    submissions = ("SYN-M01", "SYN-M02")
    criteria = (
        {"criterion_id": "C0", "kind": "mcq", "scoring_model": "deterministic"},
        {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},
    )
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _version = seed_run(
            store, submissions=submissions, criteria=criteria, run_id="r-mon"
        )
        orchestrator.enumerate_units(run_id)
        orchestrator.start(run_id)  # pending → running: the live-run precondition

        app = build_console(store=store)
        page = app.render("/runs/{id}/monitor", id=run_id)

        # The ledger's own groups, read directly — not `app.progress()`. The renderer
        # formats its report; the oracle compares the page against the store, so a report
        # and a renderer that drifted together would still be caught here.
        ledger = store.cohort(ORCH_COHORT_ID).query(
            "SELECT stage, criterion_id, judge_id, status, COUNT(*) AS n FROM work_unit "
            "WHERE run_id = :run_id GROUP BY stage, criterion_id, judge_id, status",
            run_id=run_id,
        )
        stages = {str(row["stage"]) for row in ledger}
        judges = {str(row["judge_id"]) for row in ledger if row["judge_id"] is not None}
        assert len(ledger) >= 3 and len(stages) >= 2 and len(judges) >= 2, (
            f"the fixture enumerated {len(ledger)} group(s) over {len(stages)} stage(s) and "
            f"{len(judges)} judge(s) — the three-dimension granularity assertion needs a run "
            f"whose ledger actually varies along all three axes"
        )

        assert elements(page.html, "progress"), (
            "the monitor rendered no progress section, so the granularity assertion below "
            "has nothing to read"
        )
        for row in ledger:
            line = _expected_progress_line(row)
            assert line in page.html, (
                f"the ledger group {line!r} does not render on the run monitor. TC-CONSOLE-08: "
                f"progress renders at (stage, criterion, judge) granularity — exactly the rows "
                f"the ledger counts, and the count is the ledger's, not the renderer's."
            )

        # **The prohibition half, two-sided.** The rows the renderer read really do name the
        # students — so if the page showed a per-student figure, the identifiers would be
        # its signature.
        named = store.cohort(ORCH_COHORT_ID).query(
            "SELECT DISTINCT submission_id FROM work_unit WHERE run_id = :run_id",
            run_id=run_id,
        )
        assert {str(row["submission_id"]) for row in named} >= set(submissions), (
            "the enumerated ledger does not carry the seeded submissions, so the absence "
            "assertion below would pass over a monitor that reads nothing"
        )
        for submission_id in submissions:
            assert submission_id not in page.html and f"ref-{submission_id}" not in page.html, (
                f"the run monitor names submission {submission_id!r} (or its student ref). "
                f"FR-CONSOLE-08: there is no per-student progress figure — a unit's state "
                f"says nothing about when a student's grade will exist, and the identifier "
                f"on the page is the signature of a per-student grouping."
            )
    finally:
        store.close()