"""`TC-PIPE-42` (ADR-57, CT-CALIB-01, CT-PIPE-01 amended; issue #898, Validity T5): the dependency
census behind "M-PIPE owns promotion".

- `aeh.review` imports nothing from `aeh.stats` beyond the stored disagreement-rate read, imports
  nothing from `aeh.pipeline`, and calls no `promote` (M-REVIEW never promotes).
- `aeh.pipeline` imports nothing from `aeh.calib`; the edge `aeh.calib -> aeh.pipeline` is
  allowed (M-CALIB grades its examples through the same driver, TC-PIPE-43).
- `aeh.console` calls no agreement function: a spy on M-STATS's agreement functions, over the
  console's blind flow (seats, drafts, Finish, which promotes) and its results screen, records
  no call whose immediate caller is a console module.
- `promote_administration` is on M-PIPE's composition surface, and promoting uses only M-ORCH
  doors on TC-REQ-90's `COMPOSITION_SURFACE`.

The walker resolves relative imports (`from ..stats import x` inside `aeh.review` is an edge to
`aeh.stats`) and dynamic `importlib.import_module` calls, and covers function-scoped imports,
since `ast.walk` visits every node. It is checked against synthetic modules first, so a walker
that never matches cannot pass the census vacuously.

**Disclosed departures (in the PR as well).**

1. *TC-REQ-90's `COMPOSITION_SURFACE` does not list `promote_administration`, and should not.*
   That set is M-ORCH's surface: the `Orchestrator` methods M-PIPE may call. The plan asks for
   `promote_administration` in it, but `promote_administration` is M-PIPE's own door, not an
   M-ORCH method. This case therefore pins two things instead. `promote_administration` is
   exported at `aeh.pipeline`'s root and defined in `aeh.pipeline.validity` (the package has
   no `__all__`). And the M-ORCH doors M-PIPE calls
   while promoting (Finish's promotion and the recovery sweep) are a subset of
   `COMPOSITION_SURFACE`, the property the plan's line protects.
2. *"`aeh.review` imports nothing from `aeh.stats`" conflicts with the design delta.* The delta's
   §2 lists `M-REVIEW -> M-STATS` among the existing edges. `aeh.review.stored_rows` reads
   `aeh.stats.stored_disagreement_rates` for the queue's eighth input (FR-REVIEW-18 amended,
   FR-STATS-28, #433). The delta governs, so the census allows that one read edge by name. It
   forbids every other `aeh.stats` import, any `aeh.pipeline` import, and any `promote` call.
   ADR-57's actual rule is "M-REVIEW never calls M-STATS's promotion".
3. *The console spy runs over the console's blind flow, not TC-E2E-16.* TC-E2E-16 is not in
   this issue. The spy covers every console path that reaches promotion.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Iterable

import pytest

from tests.support.import_graph import is_within, source_files

REPO = Path(__file__).resolve().parents[3]


def _resolve(module: str, is_package: bool, node: ast.ImportFrom) -> str | None:
    """The absolute module an `ImportFrom` names, relative levels resolved against `module`."""
    if node.level == 0:
        return node.module
    parts = module.split(".")
    base = parts if is_package else parts[:-1]
    if node.level - 1 > len(base):
        return None
    base = base[: len(base) - (node.level - 1)]
    return ".".join(base + ([node.module] if node.module else []))


def imported_modules(module: str, source: str, *, is_package: bool = False) -> set[str]:
    """Every module `source` imports, statically (any scope, any spelling) or through
    `importlib.import_module("...")` / `__import__("...")` with a literal name. For
    `from pkg import name`, both `pkg` and `pkg.name` are recorded, since `name` may be a
    submodule."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            target = _resolve(module, is_package, node)
            if target:
                found.add(target)
                found.update(f"{target}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call):
            func = node.func
            name = (func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name) else "")
            if name in ("import_module", "__import__") and node.args and isinstance(
                    node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                found.add(node.args[0].value)
    return found


def forbidden_edges(importer_root: str, imported_root: str,
                    modules: Iterable[tuple[str, str, bool]]) -> list[str]:
    """Each `module -> target` edge from inside `importer_root` into `imported_root`."""
    edges: list[str] = []
    for module, source, is_package in modules:
        if not is_within(module, [importer_root]):
            continue
        for target in sorted(imported_modules(module, source, is_package=is_package)):
            if is_within(target, [imported_root]):
                edges.append(f"{module} -> {target}")
    return edges


def _tree() -> list[tuple[str, str, bool]]:
    return [(module, path.read_text(encoding="utf-8"), path.name == "__init__.py")
            for module, path in source_files(REPO, ("src",))]


# --- the walker, against synthetic modules --------------------------------------------------------


def test_tc_pipe_42_walker_sees_every_spelling_and_the_rule_is_directional():
    """Non-vacuity: the walker finds absolute, relative, function-scoped and dynamic edges, and
    the census rule flags `aeh.pipeline -> aeh.calib` while allowing `aeh.calib -> aeh.pipeline`."""
    synthetic = [
        ("aeh.review.x", "from ..stats import agreement\n", False),
        ("aeh.review.y", "def f():\n    import aeh.stats.promotion\n", False),
        ("aeh.review", "from .blind import z\nfrom ..stats.service import V\n", True),
        ("aeh.review.w", "import importlib\nimportlib.import_module('aeh.stats')\n", False),
        ("aeh.pipeline.v", "from aeh.calib import driver\n", False),
        ("aeh.calib.u", "from aeh.pipeline import run_to_completion\n", False),
        ("aeh.review.ok", "from aeh.store import open_store\nfrom .records import R\n", False),
    ]
    review_edges = forbidden_edges("aeh.review", "aeh.stats", synthetic)
    assert {edge.split(" -> ")[0] for edge in review_edges} == {
        "aeh.review.x", "aeh.review.y", "aeh.review", "aeh.review.w"}, review_edges
    assert forbidden_edges("aeh.pipeline", "aeh.calib", synthetic) == [
        "aeh.pipeline.v -> aeh.calib", "aeh.pipeline.v -> aeh.calib.driver"]
    assert forbidden_edges("aeh.calib", "aeh.pipeline", synthetic), (
        "the walker missed the allowed calib -> pipeline edge it must be able to see")


# --- the census over src/ ------------------------------------------------------------------------


#: The one M-REVIEW -> M-STATS edge the design keeps (delta §2, "existing edges ... `M-REVIEW ->
#: M-STATS`"): the queue's eighth input reads M-STATS' stored disagreement rates (FR-REVIEW-18
#: amended, FR-STATS-28, #433). A read of stored figures, never a promotion.
REVIEW_STATS_READER = "aeh.review.stored_rows"
REVIEW_STATS_READ_EDGE = frozenset({
    "aeh.stats", "aeh.stats.CriterionDisagreement", "aeh.stats.stored_disagreement_rates",
})


def _calls_promote(source: str) -> list[int]:
    """Lines of `source` that call anything named `promote` / `promote_administration`."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            name = (func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name) else "")
            if name in ("promote", "promote_administration"):
                lines.append(node.lineno)
    return lines


def test_tc_pipe_42_a_review_reaches_stats_only_through_the_stored_rate_read():
    """`aeh.review` imports nothing from `aeh.stats` beyond the stored disagreement-rate read
    the design keeps, never M-PIPE, and calls no `promote` (ADR-57: M-REVIEW never promotes;
    M-STATS depends on M-REVIEW, so a promoting edge would be a cycle)."""
    tree = _tree()
    assert any(is_within(module, ["aeh.review"]) for module, _s, _p in tree), "fixture: no aeh.review"
    edges = [edge for edge in forbidden_edges("aeh.review", "aeh.stats", tree)
             if not (edge.split(" -> ")[0] == REVIEW_STATS_READER
                     and edge.split(" -> ")[1] in REVIEW_STATS_READ_EDGE)]
    # The reader takes the two names by `from aeh.stats import ...`; a bare `import aeh.stats`
    # would reach every M-STATS function through attribute access, so it is not the read edge.
    bare = [f"{module}:{node.lineno}" for module, source, _p in tree
            if is_within(module, ["aeh.review"])
            for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Import)
            for alias in node.names if is_within(alias.name, ["aeh.stats"])]
    edges += [f"{site} -> import aeh.stats" for site in bare]
    assert not edges, ("M-REVIEW imports M-STATS beyond the stored-rate read (ADR-57: the "
                       "composition root promotes, M-REVIEW never calls M-STATS):\n  "
                       + "\n  ".join(edges))
    to_pipe = forbidden_edges("aeh.review", "aeh.pipeline", tree)
    assert not to_pipe, "M-REVIEW imports M-PIPE:\n  " + "\n  ".join(to_pipe)
    promoting = [f"{module}:{line}" for module, source, _p in tree
                 if is_within(module, ["aeh.review"]) for line in _calls_promote(source)]
    assert not promoting, f"M-REVIEW calls promote: {promoting}"


def test_tc_pipe_42_b_pipeline_imports_nothing_from_calib_and_calib_may_import_pipeline():
    tree = _tree()
    edges = forbidden_edges("aeh.pipeline", "aeh.calib", tree)
    assert not edges, ("M-PIPE imports M-CALIB (CT-CALIB-01: M-CALIB sits above the driver):"
                       "\n  " + "\n  ".join(edges))


@pytest.mark.integration
def test_tc_pipe_42_c_promote_administration_is_m_pipes_door_on_orch_composition_surface(
        tmp_path, monkeypatch, network_guard):
    """`promote_administration` is exported by `aeh.pipeline`, and the M-ORCH doors M-PIPE
    calls while promoting (on Finish, and in the recovery sweep) are all on TC-REQ-90's
    `COMPOSITION_SURFACE`."""
    import aeh.pipeline as pipeline
    from aeh.orch import Orchestrator
    from tests.contract.requires.test_ts97_requires_delta import COMPOSITION_SURFACE
    from tests.support.label_identity_world import served_run
    from tests.support.source_tree import class_members, top_module

    # M-PIPE's own door, exported at the package root and defined in M-PIPE (not re-exported
    # from another module).
    assert pipeline.promote_administration.__module__ == "aeh.pipeline.validity"

    used: set[str] = set()
    promoting: list[bool] = [False]
    for name, member in class_members(Orchestrator):
        if name.startswith("_") and name != "__init__" or not callable(member):
            continue

        def spy(self, *args, _name=name, _real=member, **kwargs):
            if promoting[0] and top_module(
                    sys._getframe(1).f_globals.get("__name__", "")) == "aeh.pipeline":
                used.add(_name)
            return _real(self, *args, **kwargs)

        monkeypatch.setattr(Orchestrator, name, spy)
    with served_run(tmp_path / "w", monkeypatch, network_guard) as served:
        status, read = served.get("/api/v1/blind-seats", run_id=served.run_id)
        assert status == 200 and read["seats"], read
        promoting[0] = True
        outcome = pipeline.promote_administration(served.world.store, served.run_id, "finish")
        assert not outcome.promoted
        served.dispatched("blind-sample finish", run_id=served.run_id)
        pipeline.recover(served.world.store)
        promoting[0] = False
        assert pipeline.validity_stage(served.world.store, served.run_id).metrics["state"] in (
            "recorded",), "fixture: Finish did not promote"
    assert used, "fixture: promoting called no M-ORCH door, so the subset check is vacuous"
    assert used <= COMPOSITION_SURFACE, (
        f"promoting used M-ORCH doors outside TC-REQ-90's COMPOSITION_SURFACE: "
        f"{sorted(used - COMPOSITION_SURFACE)}")


@pytest.mark.integration
def test_tc_pipe_42_d_the_console_calls_no_agreement_function(
        tmp_path, monkeypatch, network_guard):
    """`aeh.console` calls no agreement function (ADR-57). Each of M-STATS's agreement entry
    points is wrapped; over the console's blind flow (seats, two drafts, Finish, which
    promotes) and its results screen, no call's immediate caller is a console module. The
    calls M-STATS makes inside `promote` are expected and allowed (their caller is M-STATS);
    the spy records them so the case is not vacuous."""
    import aeh.stats as stats_pkg
    from aeh.stats.service import ValidationStats
    from harness.corpora import dev_pipe
    from tests.support.label_identity_world import served_run

    calls: list[tuple[str, str]] = []

    def wrap(owner, name):
        real = getattr(owner, name)

        def spy(*args, **kwargs):
            calls.append((name, sys._getframe(1).f_globals.get("__name__", "")))
            return real(*args, **kwargs)

        monkeypatch.setattr(owner, name, spy)

    for name in ("agreement", "routing_policy_validity", "aggregate"):
        wrap(ValidationStats, name)
    for name in ("agreement", "agreement_by_engine"):
        if hasattr(stats_pkg, name):
            wrap(stats_pkg, name)
    wrap(sys.modules["aeh.stats.agreement"], "agreement")

    with served_run(tmp_path / "w", monkeypatch, network_guard) as served:
        status, read = served.get("/api/v1/blind-seats", run_id=served.run_id)
        assert status == 200, read
        for seat, ordinal in zip(read["seats"][:2], (1, 4)):
            served.dispatched("blind-sample draft", run_id=served.run_id,
                              seat_id=seat["seat_id"], band=dev_pipe.band_at("C2", ordinal))
        served.dispatched("blind-sample finish", run_id=served.run_id)
        served.get("/api/v1/blind-seats", run_id=served.run_id)
        served.server.app._render_rollup_screen(served.run_id, [])
    from_console = [(name, caller) for name, caller in calls
                    if is_within(caller, ["aeh.console"])]
    assert not from_console, f"the console called agreement functions: {from_console}"
    assert calls, ("fixture: no agreement function ran at all, not even inside promote, so "
                   "the spies are not live")


#: M-STATS's agreement functions, by name.
AGREEMENT_FUNCTIONS = frozenset({"agreement", "agreement_by_engine", "routing_policy_validity"})


def _agreement_sites(module: str, source: str, is_package: bool) -> list[str]:
    """Each import of an agreement function from `aeh.stats`, and each call of a function or
    method by one of those names, in `source`."""
    sites: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            target = _resolve(module, is_package, node) or ""
            if is_within(target, ["aeh.stats"]):
                sites += [f"{module}:{node.lineno} imports {alias.name}" for alias in node.names
                          if alias.name in AGREEMENT_FUNCTIONS
                          or target.endswith(".agreement")]
        elif isinstance(node, ast.Call):
            func = node.func
            name = (func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name) else "")
            if name in AGREEMENT_FUNCTIONS:
                sites.append(f"{module}:{node.lineno} calls {name}()")
    return sites


def test_tc_pipe_42_e_the_console_names_no_agreement_function_statically():
    """The static half of 42 (d), independent of import order: no `aeh.console` module imports
    an agreement function from `aeh.stats` or calls one by name. The runtime spy in (d) can
    miss a module-level `from aeh.stats import agreement` bound before the spy wraps the
    package attribute; this cannot. Checked against a synthetic module first."""
    planted = _agreement_sites(
        "aeh.console.x",
        "from aeh.stats import agreement\nfrom ..stats.agreement import AgreementFigure\n"
        "def f(s):\n    return s.routing_policy_validity()\n", False)
    assert len(planted) == 3, planted
    sites = [site for module, source, is_package in _tree()
             if is_within(module, ["aeh.console"])
             for site in _agreement_sites(module, source, is_package)]
    assert not sites, "the console reaches an agreement function:\n  " + "\n  ".join(sites)
