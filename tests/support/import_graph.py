"""The import-graph walker behind `TC-PROV-05`.

`FR-PROV-03` names its own acceptance form, verbatim: *"an automated import-graph assertion
over the source tree is the acceptance form of this requirement."* `CT-PROV-15` restates it as
a safety property — `M-PROV` is the **sole egress point**, and the audit claim the clause makes
on a reviewer's behalf is that the set of modules containing an egress-capable import has
cardinality one.

This module is that walker. It is here rather than in `harness/` because §4.7 reserves
`harness.*` for the `blast_radius` / `conform` / `mvvp` entry points, and because nothing
outside the suite consumes it.

Why static analysis rather than a runtime check
-----------------------------------------------
RISK-32 is rated **Critical** and its detectability is **No**: a module that imports an SDK
directly — for a "quick" streaming feature or a health check — produces a run that succeeds and
looks entirely normal. Every consent gate, cost ceiling and air-gap guarantee in the system is
enforced at the seam that import bypasses. Nothing behavioural notices, so the assertion has to
be about the shape of the code.

The walker parses rather than greps, deliberately. `TC-PROV-05`'s **Variants** line requires a
dynamic `importlib.import_module("litellm")` to be caught as well, and an aliased or
function-scoped import is invisible to a naive line scan while being a perfectly working
import. Comments are not in the AST at all, which is the right answer: a comment cannot import
anything.

What the declared lists are, and what they are not
--------------------------------------------------
`TC-PROV-05`'s preconditions call for *"a declared list of forbidden symbols — `litellm`,
`openai`, `ollama`, `mlx_lm`, the OpenRouter SDK namespace, and any HTTP client whose target is
a model endpoint."* The first five are named; the sixth cannot be decided statically, because
whether a client targets a model endpoint depends on a URL that is not in the source. So
`HTTP_CLIENT_ROOTS` forbids the clients themselves outside `M-PROV` — which is the stronger
reading and the one `CT-PROV-15` states ("no other module imports ... an HTTP client targeting
a model endpoint"), since a module that holds no HTTP client cannot point one anywhere.

Bare `socket` is deliberately **not** on that list. `M-CONSOLE` binds a loopback listener
(`FR-CONSOLE-05`) and a static ban would fire on it, which is not egress and would make this
case a nuisance rather than a gate. Socket-level egress is covered at runtime instead, by
`TC-PROV-C15` step 2 (issue #25) with a process-wide guard that records the stack that opened
each connection.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

#: Provider SDKs and model-serving clients. The first four are named in `TC-PROV-05`'s
#: preconditions; the rest are the same category, listed so that reaching for a different
#: vendor's client is caught by the case rather than by a reviewer noticing.
PROVIDER_SDK_ROOTS: frozenset[str] = frozenset(
    {
        "litellm",
        "openai",
        "ollama",
        "mlx_lm",
        "openrouter",  # the OpenRouter SDK namespace, per the preconditions
        "anthropic",
        "cohere",
        "mistralai",
        "google",  # google.generativeai
        "vllm",
        "llama_cpp",
        "transformers",
        "huggingface_hub",
        "sentence_transformers",
        "torch",
    }
)

#: HTTP clients. `http.server` and `socketserver` are absent on purpose — serving a loopback
#: console is not egress. See the module docstring.
HTTP_CLIENT_ROOTS: frozenset[str] = frozenset(
    {
        "requests",
        "httpx",
        "aiohttp",
        "urllib3",
        "websockets",
        "websocket",
        "urllib.request",
        "http.client",
    }
)

FORBIDDEN_ROOTS: frozenset[str] = PROVIDER_SDK_ROOTS | HTTP_CLIENT_ROOTS

#: Step 3's backend-specific string constants, verbatim from `TC-PROV-05`.
BACKEND_CONSTANTS: tuple[str, ...] = ("ollama", "vllm-mlx", "openrouter")

#: `M-PROV`. The one module allowed an egress-capable import — that is the whole clause.
#:
#: Matched on module **boundaries**, so `aeh.prov.openrouter_backend` is covered when `M-PROV`
#: grows from a module into a package — which is the likely layout for three implementations.
#: An exact-string test was the first draft and it turned a *correct* `M-PROV` red; the damage
#: is not the red but the reflex fix, which is to add the new module to this set. That is
#: precisely how one seam becomes two.
PROVIDER_MODULES: frozenset[str] = frozenset({"aeh.prov"})

#: `M-CONF` resolves `provider` on a `ModelRef` and so names the backends; `TC-PROV-05` step 3
#: exempts it by name. It gets **no** exemption from step 2: `M-CONF` selects the provider, it
#: does not call one (design §3.1, "it owns the *fixing* of the backend; it does not own the
#: calling of it").
BACKEND_CONSTANT_EXEMPT: frozenset[str] = PROVIDER_MODULES | {"aeh.conf"}


def is_within(module: str, roots: Iterable[str]) -> bool:
    """Whether `module` is one of `roots` or a submodule of one.

    `aeh.prov` covers `aeh.prov.openrouter_backend`; `aeh.provisioning` is a different module
    and is covered by neither.
    """
    segments = module.split(".")
    for root in roots:
        root_segments = root.split(".")
        if segments[: len(root_segments)] == root_segments:
            return True
    return False

#: Package roots the walk covers. `harness/` is included because RISK-32's named scenario is
#: "a direct SDK import to `M-CONFORM` to compare raw latencies", and `M-CONFORM`'s entry point
#: is a `harness.*` module (§4.7). `tests/` is excluded — step 3 says "outside a test fixture",
#: and this suite necessarily names the backends in order to assert about them.
SOURCE_ROOTS: tuple[str, ...] = ("src", "harness")


@dataclass(frozen=True)
class Violation:
    """One forbidden edge, named the way `TC-PROV-05`'s expected result requires.

    *"Zero violating edges; a violation names the importing module and the symbol."* So the
    failure message must be actionable on its own — `module`, `symbol` and a file:line a reader
    can open.
    """

    module: str  # dotted module path, e.g. "aeh.orch"
    path: str  # repo-relative, POSIX separators
    line: int
    kind: str  # "import" | "dynamic-import" | "backend-constant"
    symbol: str

    def __str__(self) -> str:
        return f"{self.module} ({self.path}:{self.line}) {self.kind} -> {self.symbol!r}"


def _matches_forbidden(dotted: str, forbidden: Iterable[str]) -> str | None:
    """The forbidden entry `dotted` falls under, or `None`.

    Matches on module *boundaries* rather than on prefixes, so `openai_helpers` is not read as
    `openai` and a module named `requests_of_teachers` is not a finding.
    """
    segments = dotted.split(".")
    for entry in forbidden:
        entry_segments = entry.split(".")
        if segments[: len(entry_segments)] == entry_segments:
            return entry
    return None


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """`id()` of every node that is a docstring, so step 3 can skip prose.

    A docstring is a string constant in the AST but is not a value the code branches on, and
    `M-PROV`'s own design tables — and this walker's own documentation — necessarily spell the
    backend names out. Skipping them keeps step 3 an assertion about *code* referencing a
    backend, which is what it is for. A comment needs no such handling: comments never reach
    the AST.
    """
    marked: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                marked.add(id(first.value))
    return marked


def _dynamic_import_aliases(tree: ast.AST) -> set[str]:
    """Local names bound to `importlib.import_module`, so an alias is still caught.

    `from importlib import import_module as im` makes `im("litellm")` a working dynamic import
    that no walker matching on the callee's literal name would see.
    """
    aliases = {"import_module", "__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module" and alias.asname:
                    aliases.add(alias.asname)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib" and alias.asname:
                    aliases.add(f"{alias.asname}.import_module")
    return aliases


def _dynamic_import_targets(node: ast.Call, aliases: set[str]) -> Iterator[str]:
    """The module names a dynamic-import call asks for, when they are string literals.

    `TC-PROV-05`'s **Variants** line: *"a dynamic `importlib.import_module('litellm')` must
    also be caught, so the walker inspects string arguments to `import_module` as well as
    `import` statements."* `__import__` is here too — it is the same door with an older name,
    and a walker that watched only one of them would be trivially avoidable.

    A non-literal argument (`import_module(name)`) is invisible to any static walker. That is
    the residual this case cannot close, and `TC-PROV-C15` step 2's runtime egress guard is
    what closes it.
    """
    func = node.func
    called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if called not in aliases:
        return
    # Positional *and* keyword: `import_module(name="litellm")` is the same door, and the
    # Variants line is the one spelling the plan calls out by hand.
    arguments = list(node.args) + [keyword.value for keyword in node.keywords]
    for argument in arguments:
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            yield argument.value


def module_name_for(path: Path, root: Path) -> str | None:
    """The dotted module path a file would be imported as, or `None` if it is not importable.

    `TC-PROV-05` step 1 is *"build the import graph of every module in the package"*, and a
    file whose **name** is not a Python identifier has no node in that graph: nothing can
    import `harness/reference/metamorphic.skeleton.py`, because `metamorphic.skeleton` does not
    name a module. The repository holds exactly one such file today — a reference skeleton
    copied in from `/harness-bootstrap` and marked *"a REFERENCE to copy + fill in, not a
    runnable suite"*, carrying a `urllib.request` call against a placeholder
    `http://localhost:PORT`.

    Skipping it is not an exemption. Give that file an importable name and it becomes a node,
    and this case reports it — which is the correct outcome, because a copy of that skeleton
    wired to a real endpoint is precisely the second egress point `CT-PROV-15` forbids.

    The rule is deliberately narrow: **the stem, never a parent directory**. Requiring every
    segment to be an identifier would drop `harness/quick-tools/latency_probe.py` — a perfectly
    working egress point — out of the scan entirely, and `skipped_files()` exists so nothing
    lands in this category without a test noticing.
    """
    relative = path.relative_to(root)
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][: -len(".py")]
    # The **stem** only. An earlier draft required every path segment to be an identifier,
    # which meant a directory named `quick-tools/` silently dropped its entire subtree from all
    # three steps — a working second egress point, invisible, which is the one outcome this
    # case exists to prevent. A hyphenated directory does not make the file unreadable, and the
    # walk is a static read rather than an import.
    if parts and not parts[-1].isidentifier():
        return None
    return ".".join(parts)


def source_files(repo_root: Path, roots: Iterable[str] = SOURCE_ROOTS) -> list[tuple[str, Path]]:
    """Every `.py` file under the scanned roots, with the module name it would import as.

    `src/` holds the implementation package, so a module there is `aeh.something`; `harness/`
    is itself the package root, so a module there is `harness.something`.
    """
    found: list[tuple[str, Path]] = []
    for root_name in roots:
        root = repo_root / root_name
        if not root.is_dir():
            continue
        # `src` is a path entry (pyproject's `pythonpath`), not a package; `harness` is a
        # package whose parent is the repository root.
        package_root = root if root_name == "src" else repo_root
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            module = module_name_for(path, package_root)
            if module is None:
                continue
            found.append((module, path))
    return found


def skipped_files(repo_root: Path, roots: Iterable[str] = SOURCE_ROOTS) -> list[str]:
    """Every `.py` file the walk does not scan, because its stem is not importable.

    Exposed so a test can bound the set. Whatever is in here is invisible to all three steps of
    `TC-PROV-05`, so it must stay a list somebody has looked at rather than a growing category
    — a leak parked in a file named `adhoc.probe.py` would otherwise be reported by nothing.
    """
    skipped: list[str] = []
    for root_name in roots:
        root = repo_root / root_name
        if not root.is_dir():
            continue
        package_root = root if root_name == "src" else repo_root
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            if module_name_for(path, package_root) is None:
                skipped.append(path.relative_to(repo_root).as_posix())
    return skipped


def scan_module(
    module: str,
    source: str,
    path: str,
    *,
    forbidden: Iterable[str] = FORBIDDEN_ROOTS,
    backend_constants: Iterable[str] = BACKEND_CONSTANTS,
    check_backend_constants: bool = True,
) -> list[Violation]:
    """Every forbidden edge out of one module's source. Steps 1–3 of `TC-PROV-05`.

    Takes source text rather than a path so the walker itself can be tested against synthetic
    modules — a walker that never matches anything scores zero violations over a clean tree and
    is indistinguishable from a correct one. See `tests/artifact/test_import_graph.py`.
    """
    tree = ast.parse(source, filename=path)
    forbidden = tuple(forbidden)
    aliases = _dynamic_import_aliases(tree)
    violations: list[Violation] = []

    for node in ast.walk(tree):
        # Step 1 and 2: static imports, in both spellings and under any alias. The alias is
        # irrelevant to the graph — `import litellm as _l` is the same edge.
        if isinstance(node, ast.Import):
            for alias in node.names:
                hit = _matches_forbidden(alias.name, forbidden)
                if hit is not None:
                    violations.append(
                        Violation(module, path, node.lineno, "import", alias.name)
                    )
        elif isinstance(node, ast.ImportFrom):
            # `node.level > 0` is a relative import, which cannot leave the package.
            if node.level == 0 and node.module:
                hit = _matches_forbidden(node.module, forbidden)
                if hit is not None:
                    violations.append(
                        Violation(module, path, node.lineno, "import", node.module)
                    )
        elif isinstance(node, ast.Call):
            for target in _dynamic_import_targets(node, aliases):
                hit = _matches_forbidden(target, forbidden)
                if hit is not None:
                    violations.append(
                        Violation(module, path, node.lineno, "dynamic-import", target)
                    )

    if check_backend_constants:
        docstrings = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in docstrings:
                continue
            lowered = node.value.lower()
            for token in backend_constants:
                if token in lowered:
                    violations.append(
                        Violation(module, path, node.lineno, "backend-constant", token)
                    )

    return violations


def scan_tree(repo_root: Path, roots: Iterable[str] = SOURCE_ROOTS) -> list[Violation]:
    """Steps 1–3 over the whole source tree, with `TC-PROV-05`'s two exemptions applied.

    `M-PROV` may import anything on the forbidden list — that is what being the sole egress
    point means. `M-CONF` is additionally exempt from step 3 only.
    """
    violations: list[Violation] = []
    for module, path in source_files(repo_root, roots):
        relative = path.relative_to(repo_root).as_posix()
        if is_within(module, PROVIDER_MODULES):
            continue
        violations.extend(
            scan_module(
                module,
                path.read_text(encoding="utf-8"),
                relative,
                check_backend_constants=not is_within(module, BACKEND_CONSTANT_EXEMPT),
            )
        )
    return violations


def egress_capable_modules(repo_root: Path, roots: Iterable[str] = SOURCE_ROOTS) -> set[str]:
    """Every module holding an egress-capable import, `M-PROV` included.

    `TC-PROV-05` step 3's audit claim — restated by `CT-PROV-15` as *"a reviewer may therefore
    audit egress by reading one module"* — is a statement about the **cardinality** of this
    set, which is a different assertion from "zero violations outside `M-PROV`": a tree with no
    provider module at all satisfies the second vacuously and fails the first.
    """
    holders: set[str] = set()
    for module, path in source_files(repo_root, roots):
        relative = path.relative_to(repo_root).as_posix()
        found = scan_module(
            module,
            path.read_text(encoding="utf-8"),
            relative,
            check_backend_constants=False,
        )
        if found:
            holders.add(module)
    return holders


def egress_holders_outside_m_prov(repo_root: Path, roots: Iterable[str] = SOURCE_ROOTS) -> set[str]:
    """`egress_capable_modules`, minus everything inside `M-PROV`."""
    return {
        module
        for module in egress_capable_modules(repo_root, roots)
        if not is_within(module, PROVIDER_MODULES)
    }
