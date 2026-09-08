"""`CT-SETUP-16` — the non-promise: Stage A runs once per package
(`TC-SETUP-C16`).

Case of test plan §6.11.6; issue #56 (TS-63). Green: the reflection held on
shipped code except for one disclosed finding (G1, the second-root mint route
below) — and #229 closes it, so the whole clause now holds on shipped code.

The clause: after `publish()` this module offers **no operation that alters a
published version**, asserted **by reflecting over the surface rather than by
calling**; and it has **no upstream consumers post-publish**, so a later "quick
edit through setup" has no route to exist. Together with `TC-PKG-C01` this
closes both ends of RISK-06: the catalog refuses the edit, and setup offers no
way to attempt it.

Asserted here, probed:

1. **The reflected surface names no alter operation.** Every public callable of
   `SetupService` is enumerated (reflection, not a hand list) and none names an
   edit/revise/alter/mutate operation; no public callable accepts a version id
   parameter at all — every operation acts on the package's DRAFT, discovered
   from the store, so there is no way to even NAME a published version through
   this surface.
2. **The surface's vocabulary is the draft's.** `aeh.setup`'s `__all__` and the
   public exception taxonomy carry no revision/edit/export surface: the
   sanctioned vehicle for changing a published instrument is `M-PKG`'s
   `create_version(parent=...)` (FR-PKG-02), and this module's surface does not
   re-export or wrap it.
3. **Every mutating entry point refuses on a finished package.** Driven (the
   reflection's complement): on a package whose setup has finished, ALL of
   setup's mutating operations refuse with `SetupOrderError` — the mint route
   (`ensure_version`), the inventory route (`propose_inventory`), the draft
   writers and `publish` — and the published version stays locked. The read
   surface reports the finished state with zero remaining steps and nothing
   available: the finished report and the refusing surface agree.
4. **No upstream consumers post-publish.** The module imports NOTHING downstream
   of publication: `aeh.setup`'s imports are the store boundary (`aeh.pkg`,
   `aeh.ingest`, `aeh.prov`) — no consumer module of setup's OUTPUT appears in
   the module's own graph, so no post-publish consumer can route through setup
   by construction.

**G1, closed (#229).** The finding #56 disclosed: on a package whose setup has
FINISHED, `propose_inventory` did not refuse — `ensure_version` (its first move)
saw `draft_version() is None`, never consulted `has_version()`, and minted a
**second root version** (`create_version(None)`, no parent link), opening a
fresh Stage A on the same package while the module's own `steps()` report for
the same state said the opposite ("setup has finished …; a new instrument is a
new package or a revision (FR-PKG-02)"). #229 makes the refusal-by-state the
mint route's behavior — `ensure_version` consults `has_version()` and raises
`SetupOrderError` naming the published version that blocked it, and the probe
below (formerly the G1 evidence probe) now asserts the CLOSED shape: the refusal
happens, the refusal names the published version, and no second version exists.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import aeh.setup as aeh_setup
from aeh.setup import SetupOrderError, SetupService
from tests.contract.setup._doubles import ingest_document, stage_chain

pytestmark = pytest.mark.contract

ALTER_VOCABULARY = ("edit", "revise", "alter", "amend", "mutate", "rewrite",
                    "update_version", "modify")


def _public_operations() -> list[str]:
    """The module's public operation surface, by reflection."""
    return [
        name for name, member in inspect.getmembers(SetupService, inspect.isfunction)
        if not name.startswith("_")
    ]


def test_tc_setup_c16_surface_names_no_alter_operation():
    """Reflection, not calls: no public operation names an alter of a version,
    and none accepts a version id parameter — there is no way to even NAME a
    published version through this surface."""
    operations = _public_operations()
    assert operations, "the reflection found no surface"
    for name in operations:
        lowered = name.lower()
        for word in ALTER_VOCABULARY:
            assert word not in lowered, (
                f"SetupService.{name} names an alter operation ({word!r}) — "
                "CT-SETUP-16: setup offers no operation that alters a published "
                "version"
            )
        signature = inspect.signature(getattr(SetupService, name))
        for parameter in signature.parameters:
            assert "version" not in parameter.lower(), (
                f"SetupService.{name} accepts a version parameter ({parameter!r}) "
                "— the surface must discover its draft from the store, never "
                "accept a version to operate on (CT-SETUP-16)"
            )
    # The module's declared export surface carries no revision/edit name either.
    exported = [name.lower() for name in aeh_setup.__all__]
    for word in ALTER_VOCABULARY:
        assert not any(word in name for name in exported), (
            f"aeh.setup's __all__ exports an alter surface ({word!r}) "
            "(CT-SETUP-16)"
        )


def test_tc_setup_c16_no_downstream_import_in_the_module_graph(repo_root):
    """No upstream consumers post-publish, by the module's own import graph:
    `aeh.setup` imports only the store boundary (`aeh.pkg`, `aeh.ingest`,
    `aeh.prov`), stdlib, and typing — no consumer of setup's OUTPUT appears in
    its own graph, so no post-publish consumer can route through setup by
    construction."""
    source = (repo_root / "src" / "aeh" / "setup.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module)
    aeh_imports = {name for name in imported if name == "aeh" or name.startswith("aeh.")}
    # The store boundary and NOTHING downstream of publication.
    boundary = {"aeh.ingest", "aeh.pkg", "aeh.prov"}
    assert aeh_imports == boundary, (
        f"aeh.setup imports outside the store boundary: "
        f"{sorted(aeh_imports - boundary)} — a post-publish consumer or a "
        "second enforcement point has entered the module graph (CT-SETUP-16)"
    )


def test_tc_setup_c16_write_operations_refuse_on_a_finished_package(tmp_data_dir):
    """Driven (the reflection's complement): on a finished package EVERY mutating
    entry point refuses with the order error — the mint route (`ensure_version`,
    #229), the inventory route (`propose_inventory`, its caller), the draft
    writers and `publish` — and the published version stays locked."""
    chain = stage_chain(tmp_data_dir, package_id="pkg-c16")
    chain.doc = ingest_document(chain.store, kind="assessment")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)
    # #53: the staged deterministic criteria need their keys before gate 2 opens.
    chain.service.set_answer_keys({"CRIT-Q4": ["A"], "CRIT-Q5": ["A"],
                                   "CRIT-Q6": ["A"]})
    version = chain.service.publish("teacher-1")
    assert chain.catalog.is_locked(version)

    stored = chain.catalog.proposal(version)
    criterion_draft = {"criterion_id": "CRIT-Q4"}
    for name, call in (
        # The mint route itself, and its inventory caller (#229's closure).
        ("ensure_version", chain.service.ensure_version),
        ("propose_inventory", lambda: chain.service.propose_inventory(chain.doc)),
        ("confirm_inventory", lambda: chain.service.confirm_inventory(
            stored["proposal_id"])),
        ("read_back_rubric", lambda: chain.service.read_back_rubric(
            chain.doc, chain.doc)),
        ("set_answer_keys", lambda: chain.service.set_answer_keys({"MCQ-1": ["A"]})),
        ("set_grade_policy", lambda: chain.service.set_grade_policy(None)),
        ("check_prefix_budget", chain.service.check_prefix_budget),
        ("store_calibration_papers",
         lambda: chain.service.store_calibration_papers((chain.doc,))),
        ("classify_decomposability",
         lambda: chain.service.classify_decomposability(criterion_draft)),
        ("confirm_classifications",
         lambda: chain.service.confirm_classifications({})),
        ("propose_dependencies", chain.service.propose_dependencies),
        ("confirm_dependencies", lambda: chain.service.confirm_dependencies(())),
        ("publish", lambda: chain.service.publish("teacher-1")),
    ):
        with pytest.raises(SetupOrderError):
            call()
        assert chain.catalog.is_locked(version), (
            f"{name}() on a finished package disturbed the published version "
            "(CT-SETUP-16)"
        )

    # The read surface reports the finished state honestly: nothing available,
    # nothing remaining — the console has no post-publish affordance to render.
    progress = chain.service.steps()
    assert progress.remaining_steps == 0
    assert progress.ready_to_publish is False
    assert all(not step.available for step in progress.steps)


def test_tc_setup_c16_no_route_mints_a_version_after_finish(tmp_data_dir):
    """The G1 probe, flipped by #229: the second-root mint route is CLOSED.
    Where the probe once pinned the disclosed leak (a post-finish
    `propose_inventory` minting a fresh root version and opening a second Stage
    A), it now asserts the closed shape — the refusal happens, the refusal NAMES
    the published version that blocked it (the observability half of #229), and
    no second version exists afterward: the store still holds exactly the
    published root, the finished report still says nothing remains, and the
    published version stays locked."""
    chain = stage_chain(tmp_data_dir, package_id="pkg-c16-g1")
    chain.doc = ingest_document(chain.store, kind="assessment")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)
    # #53: the staged deterministic criteria need their keys before gate 2 opens.
    chain.service.set_answer_keys({"CRIT-Q4": ["A"], "CRIT-Q5": ["A"],
                                   "CRIT-Q6": ["A"]})
    published = chain.service.publish("teacher-1")

    fresh_doc = ingest_document(chain.store, kind="assessment")
    with pytest.raises(SetupOrderError) as refused:
        chain.service.propose_inventory(fresh_doc)
    assert published in str(refused.value), (
        f"the refusal {str(refused.value)!r} does not name the published "
        "version that blocked it — the observability half of #229"
    )
    # The mint route itself refuses the same way, naming the same version.
    with pytest.raises(SetupOrderError) as mint_refused:
        chain.service.ensure_version()
    assert published in str(mint_refused.value), (
        "ensure_version's refusal does not name the published version "
        "(#229's observability half)"
    )
    # No second version exists: the store holds exactly the published root —
    # no draft, no new latest, the lineage is still the single published root.
    assert chain.catalog.draft_version() is None, (
        "a draft exists after the refusals — a version was minted post-publish "
        "(CT-SETUP-16, RISK-06: G1 reopened)"
    )
    assert chain.catalog.latest_version() == published, (
        "the package's latest version is not the published one — a second "
        "version was minted post-publish (CT-SETUP-16, RISK-06: G1 reopened)"
    )
    assert chain.catalog.lineage(published) == (published,), (
        "the published root's lineage grew — a child or a second root appeared "
        "(CT-SETUP-16, RISK-06)"
    )
    assert chain.catalog.is_locked(published)
    # The finished report and the refused surface agree: the report still says
    # nothing remains, and it said so before the refusals too — the surface's
    # new refusals change no step's story.
    progress = chain.service.steps()
    assert progress.remaining_steps == 0
    assert all(not step.available for step in progress.steps)
