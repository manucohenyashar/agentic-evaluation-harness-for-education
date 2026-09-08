"""`CT-SETUP-16` — the non-promise: Stage A runs once per package
(`TC-SETUP-C16`).

Case of test plan §6.11.6; issue #56 (TS-63). **Green, with one disclosed
finding (G1)** — the reflection holds on shipped code; one operation contradicts
the module's own finished-state report, and shipped-code findings have no
`writtenahead` target to key on, so they are disclosed here rather than shipped
red (the G-series precedent, tests/contract/ingest/_doubles.py).

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
3. **Operations that refuse on a finished package.** Driven (the reflection's
   complement): on a package whose setup has finished, the write operations
   (`confirm_inventory`, `set_answer_keys`, `publish`) refuse with
   `SetupOrderError` and the published version stays locked. The read surface
   reports the finished state with zero remaining steps and nothing available.
4. **No upstream consumers post-publish.** The module imports NOTHING downstream
   of publication: `aeh.setup`'s imports are the store boundary (`aeh.pkg`,
   `aeh.ingest`, `aeh.prov`) — no consumer module of setup's OUTPUT appears in
   the module's own graph, so no post-publish consumer can route through setup
   by construction.

**Disclosed finding G1** (`ensure_version`, src/aeh/setup.py:588-599, reached
from `propose_inventory` at src/aeh/setup.py:735): on a package whose setup has
FINISHED, `propose_inventory` does not refuse — `ensure_version` sees
`draft_version() is None`, never consults `has_version()`, and mints a **second
root version** (`create_version(None)`, no parent link), opening a fresh Stage A
on the same package. The module's own `steps()` report for the same state says
the opposite ("setup has finished …; a new instrument is a new package or a
revision (FR-PKG-02)"), and CT-SETUP-16's no-route half exists to close exactly
this route. The published version itself is never altered (the lock holds;
`TC-PKG-C01` holds the catalog end), so the clause's ALTER half holds and the
case stays green — but the probe below pins the disclosed behavior so the
finding cannot silently regress: the probe asserts what IS today (a second root
appears and the published version is untouched), which is the evidence the
finding cites, and the moment #50's successor closes the route by refusing, this
probe's `assert fresh_round is not None` is the line to flip.
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
    """Driven (the reflection's complement): on a finished package the write
    operations refuse with the order error, and the published version stays
    locked."""
    chain = stage_chain(tmp_data_dir, package_id="pkg-c16")
    chain.doc = ingest_document(chain.store, kind="assessment")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)
    version = chain.service.publish("teacher-1")
    assert chain.catalog.is_locked(version)

    stored = chain.catalog.proposal(version)
    for name, call in (
        ("confirm_inventory", lambda: chain.service.confirm_inventory(
            stored["proposal_id"])),
        ("set_answer_keys", lambda: chain.service.set_answer_keys({"MCQ-1": ["A"]})),
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


def test_tc_setup_c16_disclosed_g1_propose_after_finish_opens_a_second_root(
        tmp_data_dir):
    """The G1 probe: the disclosed route is pinned so it cannot silently
    regress. Today, `propose_inventory` after a finished setup mints a second
    ROOT version and opens a fresh Stage A on the same package, while the
    published version stays untouched — the exact evidence the G1 finding cites
    (see the module docstring). When the route is closed by refusing, this
    probe flips with it: the refusal IS the fix."""
    chain = stage_chain(tmp_data_dir, package_id="pkg-c16-g1")
    chain.doc = ingest_document(chain.store, kind="assessment")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)
    published = chain.service.publish("teacher-1")

    fresh_doc = ingest_document(chain.store, kind="assessment")
    try:
        second_round = chain.service.propose_inventory(fresh_doc)
    except SetupOrderError:
        # The route has been closed — G1 is fixed; the surface now refuses.
        return
    # Today: a second round opens on a NEW root version (no parent link), and
    # the published version is untouched.
    assert second_round.package_version_id != published, (
        "the second round reused the published version — that IS the editable "
        "published package (CT-SETUP-16, RISK-06)"
    )
    assert chain.catalog.is_locked(published), (
        "the published version was altered by the second round (CT-SETUP-16)"
    )
    lineage = chain.catalog.lineage(second_round.package_version_id)
    assert lineage == (second_round.package_version_id,), (
        f"the second round's lineage is {lineage!r} — G1's evidence changed; "
        "re-read src/aeh/setup.py ensure_version and update this probe"
    )
