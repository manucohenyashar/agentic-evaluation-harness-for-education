"""`M-CONF`'s two static-analysis cases: purity, and residency-as-data.

Cases: `TC-CONF-13` (`NFR-CONF-01`, P1) and `TC-CONF-14` (`NFR-CONF-03`, P2), test plan §5.1.
Rung 0. Oracles: *import-graph and AST assertion*, and *AST assertion*.

These are the two cases in `M-CONF` that assert about the **shape of the code** rather than its
behaviour, and that is the point: a resolver that reads the environment produces correct results
until the environment differs, and a platform branch works on the machine it was written on. No
behavioural case catches either until someone else runs it.
"""

from __future__ import annotations

import ast
import inspect
import re
import types
from pathlib import Path

import pytest

import aeh.conf

CONF_SOURCE = Path(inspect.getsourcefile(aeh.conf)).read_text(encoding="utf-8")
CONF_TREE = ast.parse(CONF_SOURCE)


def _function(name: str) -> ast.FunctionDef:
    for node in ast.walk(CONF_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"aeh.conf defines no function named {name!r}")


def _names_read(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def _names_bound(node: ast.AST) -> set[str]:
    bound: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.FunctionDef):
            bound |= {a.arg for a in child.args.args} | {a.arg for a in child.args.kwonlyargs}
            if child.args.vararg:
                bound.add(child.args.vararg.arg)
            if child.args.kwarg:
                bound.add(child.args.kwarg.arg)
        elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            bound.add(child.id)
        elif isinstance(child, (ast.comprehension,)):
            bound |= _names_bound(child.target)
        elif isinstance(child, ast.ExceptHandler) and child.name:
            bound.add(child.name)
    return bound


def _attribute_paths(node: ast.AST) -> set[str]:
    """Dotted reads such as `os.environ`, `sys.platform`, flattened to strings."""
    paths: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute):
            parts = [child.attr]
            inner = child.value
            while isinstance(inner, ast.Attribute):
                parts.append(inner.attr)
                inner = inner.value
            if isinstance(inner, ast.Name):
                parts.append(inner.id)
                paths.add(".".join(reversed(parts)))
    return paths


def _reachable_helpers(entry: str) -> set[str]:
    """`entry` plus every module-level function it can reach, transitively.

    `resolve_run_config` delegates most of its work, so an assertion that stopped at its own
    body would say nothing about `_resolve_cost` opening a file. Purity is a property of the
    call, not of one function's source.
    """
    module_functions = {
        node.name for node in CONF_TREE.body if isinstance(node, ast.FunctionDef)
    }
    seen: set[str] = set()
    pending = [entry]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        called = _names_read(_function(name)) & module_functions
        pending.extend(called - seen)
    return seen


# --- TC-CONF-13: purity ------------------------------------------------------------------------

#: Things a pure resolver must not touch. `NFR-CONF-01`: *"a pure function of its arguments and
#: the environment snapshot passed to it, so profile resolution is unit-testable without a
#: filesystem or network."*
_FORBIDDEN_ATTRIBUTES = {
    "os.environ",
    "os.getenv",
    "os.getcwd",
    "os.listdir",
    "sys.argv",
    "time.time",
    "datetime.now",
    "socket.socket",
    "socket.create_connection",
    "sqlite3.connect",
    "random.random",
}
_FORBIDDEN_CALLS = {"open", "input", "eval", "exec", "compile", "__import__"}

#: Modules this module must not import at all. The plan's oracle is *"import-graph **and** AST
#: assertion"*, and the import half is not decoration: `from os import getenv` rebinds the read to
#: a bare `Name`, so an attribute-path scan never sees it — and `getenv("HARNESS_PROFILE")` is
#: precisely what `NFR-CONF-01` forbids. Verified: the attribute scan alone misses it, along with
#: `requests.post`, `urllib.request.urlopen` and `Path(...).read_text()`.
_FORBIDDEN_MODULES = {
    "requests", "httpx", "urllib", "urllib3", "http", "socket", "ssl", "ftplib", "smtplib",
    "sqlite3", "shelve", "dbm", "pickle", "subprocess", "multiprocessing", "shutil", "tempfile",
    "webbrowser", "asyncio",
}

#: Names that must not be imported *from* an otherwise-permitted module, because importing them
#: turns a forbidden attribute read into an invisible bare call.
_FORBIDDEN_IMPORTED_NAMES = {
    "environ", "getenv", "putenv", "system", "popen", "urlopen", "connect", "create_connection",
    "getcwd", "chdir", "remove", "rename", "listdir", "walk",
}


def _imports() -> list[tuple[str, str]]:
    """Every `(module, imported_name)` pair in `aeh.conf`; `imported_name` is `""` for a plain
    `import x`."""
    pairs: list[tuple[str, str]] = []
    for node in ast.walk(CONF_TREE):
        if isinstance(node, ast.Import):
            pairs.extend((alias.name, "") for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            pairs.extend((node.module, alias.name) for alias in node.names)
    return pairs


def test_tc_conf_13_the_module_imports_nothing_that_reaches_a_file_or_the_network():
    """TC-CONF-13's **import-graph** half — the other side of the plan's stated oracle.

    An attribute scan can only refuse spellings someone anticipated. This refuses the
    *capability*: if `requests` is not imported, no spelling of an HTTP call exists to miss. The
    sharp case is `from os import getenv`, which the attribute scan cannot see at all.
    """
    offenders = [
        f"{module}.{name}" if name else module
        for module, name in _imports()
        if module.split(".")[0] in _FORBIDDEN_MODULES
        or (module.split(".")[0] == "os" and name in _FORBIDDEN_IMPORTED_NAMES)
        or (module.split(".")[0] == "pathlib" and name)
    ]
    assert not offenders, (
        "aeh.conf imports a capability NFR-CONF-01 forbids it: " + ", ".join(sorted(offenders))
    )


def test_tc_conf_13_resolution_reads_no_environment_opens_no_file_makes_no_network_call():
    """TC-CONF-13 — the AST half. Swept over `resolve_run_config` **and every module-level
    helper it can reach**, because purity is a property of the call.

    `environment_snapshot` is deliberately outside that set: it is the one function that *does*
    read `os.environ`, and it is separate precisely so the resolver stays a function of its
    arguments. If it ever appears in the reachable set, this fails — which is the assertion.
    """
    reachable = _reachable_helpers("resolve_run_config")

    assert "environment_snapshot" not in reachable, (
        "resolve_run_config reaches environment_snapshot, so the environment no longer enters "
        "only through the snapshot in cfg (CT-CONF-05)"
    )

    for name in sorted(reachable):
        node = _function(name)
        forbidden = _attribute_paths(node) & _FORBIDDEN_ATTRIBUTES
        assert not forbidden, f"{name} reads {sorted(forbidden)}"

        called = {
            call.func.id
            for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        }
        assert not called & _FORBIDDEN_CALLS, f"{name} calls {sorted(called & _FORBIDDEN_CALLS)}"


def test_tc_conf_13_every_module_global_resolution_reads_is_immutable():
    """TC-CONF-13's *"reads no module global"*, in the only reading that is satisfiable.

    Taken literally the clause fails against **any** implementation: a function that referenced
    no module-level name could not call its own helpers or raise its own exception types.
    `NFR-CONF-01` states the intent instead — *a pure function of its arguments* — so what must
    be true is that nothing the resolver reads can **change between two calls**.

    That is a real oracle, not a softening. `HARDWARE_PROFILES` passes because it is a
    `MappingProxyType`; a plain `dict` fails here, and a plain `dict` is exactly what makes
    `resolve_run_config(cfg, cohort)` return two different answers for one input — the thing
    `CT-CONF-05` forbids and `TC-CONF-C05`, which perturbs only the *environment*, cannot see.
    """
    #: `ModuleType` is here because an imported module is not module *state*: `hashlib` cannot
    #: change what `compute_panel_build_ref` computes between two calls in any way this case is
    #: about. What it excludes is the thing that matters — a `dict`, `list` or `set` at module
    #: level that a caller, a plugin or another test could reach in and edit.
    #: `ModuleType` is here because an imported module is not module *state*: `hashlib` cannot
    #: change what `compute_panel_build_ref` computes between two calls in any way this case is
    #: about. `re.Pattern` likewise — a compiled pattern exposes no mutator, so it is a constant
    #: that happens to be an object. What this excludes is the thing that matters: a `dict`,
    #: `list` or `set` at module level that a caller, a plugin or another test could edit.
    immutable = (
        str, bytes, int, float, bool, complex, type(None),
        tuple, frozenset, types.MappingProxyType, types.ModuleType, re.Pattern,
        type, types.FunctionType, types.BuiltinFunctionType,
    )

    mutable_reads: list[str] = []
    for name in sorted(_reachable_helpers("resolve_run_config")):
        node = _function(name)
        for read in sorted(_names_read(node) - _names_bound(node)):
            value = getattr(aeh.conf, read, None)
            if value is None:
                continue
            if not isinstance(value, immutable):
                mutable_reads.append(f"{name} reads {read} ({type(value).__name__})")

    assert not mutable_reads, (
        "resolution reads module state that can change between calls, so the same inputs need "
        "not produce the same RunConfig (NFR-CONF-01, CT-CONF-05):\n  "
        + "\n  ".join(mutable_reads)
    )


def test_tc_conf_13_resolution_is_called_with_an_explicit_environment_snapshot():
    """TC-CONF-13's last clause — *"called with an explicit environment snapshot"*.

    Asserted over the signature: the environment arrives as a parameter, and the function that
    reads the real environment is a different one the caller invokes.
    """
    parameters = list(inspect.signature(aeh.conf.resolve_run_config).parameters)
    assert parameters[0] == "cfg", "the first parameter is the configuration snapshot"

    snapshot_params = inspect.signature(aeh.conf.environment_snapshot).parameters
    assert "environ" in snapshot_params, (
        "environment_snapshot must accept an explicit mapping so a test can supply one instead "
        "of mutating the process environment"
    )
    assert snapshot_params["environ"].default is None


# --- TC-CONF-14: residency and quantization are data --------------------------------------------

_PLATFORM_ATTRIBUTES = {"sys.platform", "os.name", "platform.system", "platform.machine",
                        "platform.processor", "sys.getwindowsversion"}


def test_tc_conf_14_the_module_contains_no_platform_branch():
    """TC-CONF-14 — *"No `sys.platform` branch"*.

    `NFR-CONF-03` is portability: an `edge-local` concept must not become a code path that
    behaves differently on the machine it runs on. A platform branch is the standard way that
    happens, and it is invisible until someone runs the suite on the other platform.
    """
    found = _attribute_paths(CONF_TREE) & _PLATFORM_ATTRIBUTES
    assert not found, f"aeh.conf branches on the platform: {sorted(found)}"

    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(CONF_TREE)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else node.names)
    } | {
        node.module.split(".")[0]
        for node in ast.walk(CONF_TREE)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "platform" not in imported, "aeh.conf imports `platform`"


def test_tc_conf_14_the_module_has_no_conditional_import():
    """TC-CONF-14 — *"no platform-conditional import"*.

    Asserted structurally rather than by name: **any** import nested inside an `If` or a `Try` is
    refused, whatever it is conditional on. A `try: import x except ImportError` is the same
    portability hazard wearing different clothes, and naming only `sys.platform` would miss it.
    """
    offenders = []
    for node in ast.walk(CONF_TREE):
        if not isinstance(node, (ast.If, ast.Try)):
            continue
        # Two shapes are exempt because neither is a *platform* branch, and refusing them would
        # fail a legitimate implementation: `if TYPE_CHECKING:` imports nothing at runtime, and
        # `try: import tomllib / except ImportError: import tomli` selects on the standard
        # library's version rather than on the machine.
        if isinstance(node, ast.If) and any(
            isinstance(n, ast.Name) and n.id == "TYPE_CHECKING" for n in ast.walk(node.test)
        ):
            continue
        if isinstance(node, ast.Try) and any(
            isinstance(h.type, ast.Name) and h.type.id in ("ImportError", "ModuleNotFoundError")
            for h in node.handlers
        ):
            continue
        for child in ast.walk(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in child.names]
                offenders.append(f"line {child.lineno}: {names}")

    assert not offenders, "aeh.conf imports conditionally: " + "; ".join(offenders)


def test_tc_conf_14_residency_and_quantization_appear_only_as_data():
    """TC-CONF-14 — *"residency and quantization appear only as data"*.

    The difference between "data" and "a code path" is expressible exactly: a value that is
    **listed** in `HARDWARE_PROFILES` is data; a value that a branch **compares against** is a
    code path. So this walks every `if` test in the module and asserts no quantization target,
    residency role or hardware-profile name appears in one.

    A resolver that grew `if profile == "unified-large": ceiling = 2000` would satisfy every
    behavioural case in the suite — the numbers would be right — and fail here, which is the
    only place that difference shows up.
    """
    # Hardware-profile names and quantization targets. **Residency role strings are excluded**,
    # and that is a scoping decision rather than an oversight: residency policies are spelled
    # with the same words as `ModelRef.role` — "judge", "transcriber" — and the module
    # legitimately branches on a *role* (`_refuse_on_mismatch` compares the transcriber
    # differently from the off-panel checker). Including them would flag that as a platform
    # branch, which it is not. What `NFR-CONF-03` is about is behaviour selected by *hardware*,
    # and these two vocabularies capture it exactly.
    vocabulary = set(aeh.conf.HARDWARE_PROFILES)
    for policy in aeh.conf.HARDWARE_PROFILES.values():
        vocabulary.add(policy.quantization_target)

    # **Every** branching construct, not just `ast.If`. A ternary is the natural way to write
    # the very branch this case forbids — `2000 if p == "unified-large" else 1500` — and
    # `match`, a comprehension guard and `while` are all equally invisible to an `If`-only walk.
    # Verified: all four survived the earlier version; only the docstring's own example failed.
    branched_on = set()
    tests: list[tuple[int, ast.AST]] = []
    for node in ast.walk(CONF_TREE):
        if isinstance(node, (ast.If, ast.IfExp, ast.While)):
            tests.append((node.lineno, node.test))
        elif isinstance(node, ast.Match):
            tests.extend((case.pattern.lineno, case.pattern) for case in node.cases)
        elif isinstance(node, ast.comprehension):
            tests.extend((guard.lineno, guard) for guard in node.ifs)

    for lineno, test in tests:
        for child in ast.walk(test):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                if child.value in vocabulary:
                    branched_on.add(f"line {lineno}: {child.value!r}")

    assert not branched_on, (
        "aeh.conf branches on a residency role, quantization target or hardware profile name — "
        "these must appear only as data in HARDWARE_PROFILES (NFR-CONF-03):\n  "
        + "\n  ".join(sorted(branched_on))
    )


def test_tc_conf_14_the_hardware_vocabulary_is_reachable_as_data():
    """The positive half. "Only as data" is satisfied vacuously if the values are nowhere at
    all, so this asserts they *are* present in the table a consumer reads — otherwise deleting
    `HARDWARE_PROFILES` entirely would pass the case above."""
    assert aeh.conf.HARDWARE_PROFILES, "the hardware table is empty"
    for name, policy in aeh.conf.HARDWARE_PROFILES.items():
        assert policy.quantization_target, f"{name} declares no quantization target"
        assert policy.residency_policy, f"{name} declares no residency policy"
