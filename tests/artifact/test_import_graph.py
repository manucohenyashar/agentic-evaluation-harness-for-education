"""`M-PROV` is the sole egress point, asserted over the import graph.

Case: `TC-PROV-05` (`FR-PROV-03`, `NFR-PROV-05`, **P0**, RISK-29, and the precondition for
every conformance claim). Level: artifact assertion over the import graph. Isolation: rung 0 —
no code under test is executed. Test plan §5.2, issue #24 (TS-07).

`FR-PROV-03` names its own acceptance form, verbatim: *"an automated import-graph assertion
over the source tree is the acceptance form of this requirement."* The walker is
`tests/support/import_graph.py`; this file is the assertion.

**Not written ahead.** Unlike the rest of TS-07, this case asserts about the *shape of the
source tree* rather than about behaviour, so it is meaningful from the first commit and it runs
in `TEST_CMD` today. It is also the case with the longest useful life: it fails on the change
that introduces a second egress point, whenever that is attempted, and RISK-32 rates that
change **Critical** with detectability **No** — the run succeeds and looks normal.

Why the positive controls below are not decoration
--------------------------------------------------
A walker that matches nothing scores zero violations over a clean tree, which is exactly what a
correct walker scores. The two are indistinguishable from `test_tc_prov_05_*` alone, and the
plan's expected result — *"a violation names the importing module and the symbol"* — is a claim
about what happens when there **is** one. So the controls feed the walker synthetic module
sources covering every spelling of the edge, including the one `TC-PROV-05`'s **Variants** line
names by hand: `importlib.import_module("litellm")`.

They are separate tests with their own names, so a failure report distinguishes "the tree grew
a violation" from "the detector broke" — those are different incidents with different fixes.
"""

from __future__ import annotations

import pytest

from tests.support.import_graph import (
    BACKEND_CONSTANT_EXEMPT,
    FORBIDDEN_ROOTS,
    PROVIDER_MODULES,
    SOURCE_ROOTS,
    Violation,
    egress_holders_outside_m_prov,
    is_within,
    scan_module,
    scan_tree,
    skipped_files,
    source_files,
)

#: The one file in the repository whose stem is not a Python identifier, and which is therefore
#: invisible to all three steps. Bounded by a test below rather than left as a category.
KNOWN_UNIMPORTABLE = {"harness/reference/metamorphic.skeleton.py"}


# --- the case ---------------------------------------------------------------------------------


def test_tc_prov_05_no_module_outside_m_prov_reaches_a_model_endpoint(repo_root):
    """TC-PROV-05 — zero violating edges over the whole source tree.

    Steps 1–3 in one assertion, because they share an oracle and a failure in any of them is
    the same incident: an egress-capable reference outside `M-PROV`.

    1. The import graph of every module under `src/` and `harness/` is built.
    2. Every edge into a forbidden symbol originates inside `M-PROV` — enforced by the walker
       skipping `M-PROV` and reporting everything else.
    3. No module outside `M-PROV` and `M-CONF` references `ollama`, `vllm-mlx` or `openrouter`
       as a string constant.

    `harness/` is in scope deliberately. RISK-32's named adversarial construction is *"a direct
    SDK import to `M-CONFORM` to compare raw latencies"*, and `M-CONFORM`'s entry point is a
    `harness.*` module (§4.7) — a scan restricted to `src/` would stay green through exactly
    the change the case exists to catch.

    Oracle: artifact assertion. Expected result: zero violating edges; the message names the
    importing module and the symbol.
    """
    violations = scan_tree(repo_root)

    assert not violations, (
        "M-PROV is the sole egress point (FR-PROV-03, CT-PROV-15), but these modules reference "
        "a provider SDK, an HTTP client or a backend-specific constant:\n  "
        + "\n  ".join(str(v) for v in sorted(violations, key=str))
    )


def test_tc_prov_05_step_3_the_set_of_egress_capable_modules_has_cardinality_at_most_one(
    repo_root,
):
    """TC-PROV-05 step 3's audit claim, which the zero-violations assertion cannot make.

    The clause promises a reviewer something specific: *"A reviewer may therefore audit egress
    by reading one module"* (`CT-PROV-15`). That is a statement about the **cardinality** of
    the set of modules holding an egress-capable import — and a tree containing no provider
    module at all satisfies "zero violations outside `M-PROV`" vacuously while satisfying
    nothing a reviewer could rely on.

    Stated as "nothing outside `M-PROV`" rather than "exactly one module", because `M-PROV`
    is expected to become a *package* — three implementations, design §3.2 — and a count over
    modules would then report three and be right to. The clause is about the audit boundary,
    and `aeh.prov.openrouter_backend` is inside it.
    """
    holders = egress_holders_outside_m_prov(repo_root)

    assert not holders, (
        "egress-capable imports must live in M-PROV alone, so a reviewer can audit egress by "
        "reading one module (CT-PROV-15). Found them in: " + ", ".join(sorted(holders))
    )


def test_tc_prov_05_scans_a_tree_that_actually_contains_modules(repo_root):
    """The precondition the two assertions above share: *"the full source tree"*.

    A path bug — a renamed package, a changed layout, a `rglob` that matches nothing — makes
    both of them pass over an empty file list. That is the one way this case can report
    "clean" while asserting about nothing at all, and it is not hypothetical: `src/aeh/` moved
    once already, in #4.
    """
    modules = [module for module, _ in source_files(repo_root)]

    assert "aeh.conf" in modules, (
        "the import-graph scan found no aeh.conf, so it is scanning the wrong tree and its "
        f"clean result means nothing. Modules found: {sorted(modules)}"
    )
    # Both roots, asserted separately. `harness/` is in scope because RISK-32's named
    # construction lands there, and it contributes zero modules today — so a `SOURCE_ROOTS`
    # that quietly lost it would change nothing visible and take M-CONFORM out of the scan.
    assert set(SOURCE_ROOTS) == {"src", "harness"}


def test_nothing_but_the_known_skeleton_is_invisible_to_the_scan(repo_root):
    """A file the walk skips is reported by no step of `TC-PROV-05`, so the set must be bounded.

    The skip rule exists for one file — a `/harness-bootstrap` reference skeleton whose stem
    (`metamorphic.skeleton`) is not an identifier, and which holds a live `urllib.request`
    call. It is not runnable and nothing can import it.

    Without this assertion the skip is an open category: a leak parked in `adhoc.probe.py`
    would be silently dropped, and a green `TC-PROV-05` would be reporting on a tree it had
    not fully read.
    """
    assert set(skipped_files(repo_root)) == KNOWN_UNIMPORTABLE


def test_a_directory_name_never_removes_a_file_from_the_scan(tmp_path):
    """The narrow half of the skip rule, and a regression.

    An earlier draft required **every** path segment to be an identifier, so a directory named
    `quick-tools/` dropped its whole subtree — a working second egress point, invisible, which
    is the single outcome this case exists to prevent. Only the file's own stem decides.
    """
    probe = tmp_path / "harness" / "quick-tools" / "latency_probe.py"
    probe.parent.mkdir(parents=True)
    probe.write_text("import httpx\n", encoding="utf-8")

    assert skipped_files(tmp_path, roots=("harness",)) == []
    assert [v.symbol for v in scan_tree(tmp_path, roots=("harness",))] == ["httpx"]


# --- positive controls for the walker ----------------------------------------------------------
#
# Each source below is a module that *should* be reported. They are parametrized rather than
# written as one test so a failure names the spelling that stopped being detected.

_EVASIONS = {
    "plain_import": "import litellm\n",
    "from_import": "from openai import OpenAI\n",
    "aliased_import": "import litellm as _l\n",
    "submodule_import": "import openai.types.chat\n",
    "from_submodule": "from litellm.utils import token_counter\n",
    "function_scoped": (
        "def call():\n"
        "    import litellm\n"
        "    return litellm\n"
    ),
    "try_guarded": (
        "try:\n"
        "    import ollama\n"
        "except ImportError:\n"
        "    ollama = None\n"
    ),
    # Named by TC-PROV-05's Variants line, in as many words.
    "dynamic_import_module": (
        "import importlib\n"
        "client = importlib.import_module('litellm')\n"
    ),
    "dynamic_bare_import_module": (
        "from importlib import import_module\n"
        "client = import_module('openai')\n"
    ),
    "dynamic_dunder_import": "client = __import__('litellm')\n",
    # The same door with the argument passed by name.
    "dynamic_keyword_argument": (
        "import importlib\n"
        "client = importlib.import_module(name='litellm')\n"
    ),
    # ...and with the callee renamed, which defeats a walker matching on the literal name.
    "dynamic_aliased_callee": (
        "from importlib import import_module as _load\n"
        "client = _load('litellm')\n"
    ),
    "dynamic_aliased_module": (
        "import importlib as _il\n"
        "client = _il.import_module('openai')\n"
    ),
    "http_client": "import httpx\n",
    "http_client_stdlib": "from urllib.request import urlopen\n",
    "mlx": "import mlx_lm\n",
}


@pytest.mark.parametrize("spelling", sorted(_EVASIONS), ids=sorted(_EVASIONS))
def test_the_walker_catches_every_spelling_of_a_forbidden_import(spelling):
    """Each of these is a working import of a provider SDK or an HTTP client.

    An aliased import, a function-scoped one and a `try`-guarded one are invisible to a line
    scan for `^import litellm$` while importing `litellm` perfectly well; `import_module` is
    invisible to any import-statement walker that does not inspect call arguments. Every one of
    them must be a violation, or `TC-PROV-05` is green against a tree that has already leaked.
    """
    violations = scan_module("aeh.leaky", _EVASIONS[spelling], "src/aeh/leaky.py")

    assert violations, f"the walker missed a forbidden import spelled {spelling!r}"
    assert all(isinstance(v, Violation) for v in violations)

    # The expected result requires the report to name the importing module *and the symbol*, so
    # a reader can act on the failure without opening the walker. Asserting the symbol is
    # merely truthy would pass for a walker that reported every violation as "something".
    reported = str(violations[0])
    assert "aeh.leaky" in reported
    expected_symbol = next(
        name
        for name in ("litellm", "openai", "ollama", "mlx_lm", "httpx", "urllib.request")
        if name in _EVASIONS[spelling]
    )
    assert any(v.symbol.startswith(expected_symbol) for v in violations), (
        f"the report names {[v.symbol for v in violations]}, not {expected_symbol!r}"
    )


def test_the_walker_catches_a_backend_constant_outside_the_exempt_modules():
    """Step 3, on a module that is neither `M-PROV` nor `M-CONF`.

    The failure this catches is subtler than an import: a module that never imports an SDK but
    branches on `if backend == "ollama"` has taken a backend-specific behaviour outside the
    seam, which is what `NFR-PROV-05` ("adding a fourth backend shall require no change outside
    this module and `M-CONF`") forbids.
    """
    source = 'BACKEND = "ollama"\n\n\ndef pick(name):\n    return name == "vllm-mlx"\n'

    violations = scan_module("aeh.orch", source, "src/aeh/orch.py")

    assert {v.symbol for v in violations} == {"ollama", "vllm-mlx"}
    assert all(v.kind == "backend-constant" for v in violations)


def test_the_walker_does_not_report_ordinary_code():
    """The negative control. A detector that reports everything is as useless as one that
    reports nothing, and it is the failure mode that gets a gate switched off."""
    source = (
        "import json\n"
        "import urllib.parse\n"
        "from http.server import HTTPServer\n"
        "from dataclasses import dataclass\n"
        "\n"
        "import openai_helpers_of_ours\n"  # boundary match, not a prefix match
        "\n"
        "PROVIDER_LABEL = 'the configured backend'\n"
    )

    assert scan_module("aeh.console", source, "src/aeh/console.py") == []


def test_the_walker_skips_docstrings_but_not_code_constants():
    """Step 3 is about code that references a backend, not prose that mentions one.

    `M-CONF`'s docstrings spell every backend name out because that is what documenting a
    build-identity format requires, and `M-PROV`'s will too. Reporting those would make step 3
    a nuisance that gets exempted module by module until it means nothing — while a constant
    the code actually branches on stays a violation.
    """
    documented = '"""Resolves ollama and openrouter builds."""\n\n\ndef f():\n    """Uses vllm-mlx."""\n    return 1\n'
    assert scan_module("aeh.orch", documented, "src/aeh/orch.py") == []

    assigned = '"""Prose."""\n\nDEFAULT = "ollama"\n'
    assert [v.symbol for v in scan_module("aeh.orch", assigned, "src/aeh/orch.py")] == ["ollama"]


def test_m_prov_and_m_conf_are_exempt_exactly_where_the_case_says():
    """The two exemptions, asserted rather than assumed — and asserted *narrowly*.

    `M-PROV` is exempt from everything: being the sole egress point is what the clause grants
    it. `M-CONF` is exempt from **step 3 only** — it names the backends because it resolves
    `ModelRef.provider`, but design §3.1 is explicit that it "owns the *fixing* of the backend;
    it does not own the calling of it", so an SDK import there is a violation like anywhere
    else. An exemption widened by accident is how a seam quietly gains a second hole.
    """
    assert PROVIDER_MODULES == {"aeh.prov"}
    assert BACKEND_CONSTANT_EXEMPT == {"aeh.prov", "aeh.conf"}

    # The narrow half: M-CONF importing litellm is still a violation.
    violations = scan_module(
        "aeh.conf", "import litellm\n", "src/aeh/conf.py", check_backend_constants=False
    )
    assert [v.symbol for v in violations] == ["litellm"]


def test_the_exemptions_follow_m_prov_when_it_becomes_a_package(tmp_path):
    """A submodule of `M-PROV` is inside the seam. A module merely *named* like one is not.

    `M-PROV` ships three implementations (design §3.2), so `aeh/prov/` as a package is the
    likely layout. An exact-string exemption turns a **correct** `M-PROV` red — and the damage
    is not the red, it is the reflex fix, which is to add the new module to the exempt set.
    That is how one auditable seam quietly becomes two.
    """
    assert is_within("aeh.prov.openrouter_backend", PROVIDER_MODULES)
    assert is_within("aeh.prov", PROVIDER_MODULES)
    assert not is_within("aeh.provisioning", PROVIDER_MODULES)
    assert not is_within("aeh.orch", PROVIDER_MODULES)

    # End to end: a package-shaped M-PROV importing an SDK is clean, and its lookalike is not.
    package = tmp_path / "src" / "aeh" / "prov"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "openrouter_backend.py").write_text("import litellm\n", encoding="utf-8")

    assert scan_tree(tmp_path, roots=("src",)) == []
    assert egress_holders_outside_m_prov(tmp_path, roots=("src",)) == set()

    lookalike = tmp_path / "src" / "aeh" / "provisioning.py"
    lookalike.write_text("import litellm\n", encoding="utf-8")

    assert [v.module for v in scan_tree(tmp_path, roots=("src",))] == ["aeh.provisioning"]


def test_m_conf_keeps_its_step_3_exemption_as_a_package(tmp_path):
    """The same boundary rule on the other exemption. `M-CONF` is the module that *must* name
    the backends, and a submodule of it must not lose that."""
    assert is_within("aeh.conf.profiles", BACKEND_CONSTANT_EXEMPT)
    assert not is_within("aeh.configurator", BACKEND_CONSTANT_EXEMPT)


def test_the_declared_forbidden_list_covers_the_symbols_the_case_names():
    """`TC-PROV-05`'s preconditions name the list by hand; this is that list, checked.

    A silently shortened list is the other way this case goes green while the tree has leaked,
    and unlike a broken walker it leaves every control above passing.
    """
    named_by_the_plan = {"litellm", "openai", "ollama", "mlx_lm", "openrouter"}

    assert named_by_the_plan <= FORBIDDEN_ROOTS, (
        "TC-PROV-05's preconditions name these forbidden symbols explicitly; missing: "
        f"{sorted(named_by_the_plan - FORBIDDEN_ROOTS)}"
    )
