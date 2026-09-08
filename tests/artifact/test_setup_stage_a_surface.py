"""`M-SETUP` Stage A's API surface, rung 0 (issue #54): `TC-SETUP-03` and `TC-SETUP-22`.

The plan puts both cases at **artifact assertion / rung 0** — no tiers at all — so the
catalog is a pure in-memory double mirroring exactly the `PackageCatalog` members
`SetupService` touches at this stage, and the ingest boundary is just `read_document`.
The scripted transport (`tests/support/setup_harness.py`) is the same one the rung-2
files use; only the persistence is doubled, because what these two cases assert is the
*shape of the API*, not what the store did with it.

Two disclosures the plan's wording forces:

- `TC-SETUP-03`'s input names "the console route table"; no console module ships yet.
  The shipped `SetupStep` docstring pins what the console renders from: "one setup step
  as the console renders it (`NFR-SETUP-04`, `FR-CONSOLE-25`)" — the enumerated list this
  file asserts against, which is also exactly what the plan's oracle says ("asserted
  against the enumerated step list rather than by reading the UI"). When the console
  lands, its route table must render this list; a route table that grew a third blocking
  route would fail the assertion below first.
- `TC-SETUP-03`'s "every other step exposes a skip": the shipped surface carries no
  separate skip flag — a step *is* its skip when it is enumerated but `blocking=False`
  (the docstring's present-and-unavailable wording), so that is what is asserted. A
  future step object that adds an explicit skip affordance should keep this green by
  construction; one that starts blocking a third step goes red here.
"""

from __future__ import annotations

import re

import aeh.setup
import pytest

from tests.support.setup_harness import (
    ASSESSMENT_MD,
    ScriptedCatalog,
    ScriptedIngestor,
    ScriptedSetupProvider,
    make_setup_service,
)

pytestmark = [pytest.mark.contract]


# --- TC-SETUP-03 ---------------------------------------------------------------------------


def test_tc_setup_03_exactly_two_steps_block_and_every_other_step_exposes_a_skip():
    """`TC-SETUP-03` (FR-SETUP-02, FR-SETUP-16, P0) — against the enumerated step list the
    console renders from: exactly two steps block (the question inventory and the answer
    keys), and every other step is present in the enumeration without blocking — the
    shipped form of "exposes a skip" (see the module docstring). `publish` is not a step:
    it is the gate point the blocking steps hold shut, so it appears in no list."""
    service = make_setup_service(ScriptedCatalog(), ScriptedIngestor(),
                                 ScriptedSetupProvider())

    progress = service.steps()

    assert [step.step_id for step in progress.steps] == [
        "inventory", "answer_keys", "rubric_readback", "decomposability", "grade_policy",
    ]
    blocking = [step.step_id for step in progress.steps if step.blocking]
    assert blocking == ["inventory", "answer_keys"], (
        "TC-SETUP-03: the blocking set drifted — exactly the question inventory and the "
        "answer keys may block (FR-SETUP-02); a third blocking step is a skipped default "
        "turned into a demand the teacher cannot defer"
    )
    skipped = [step for step in progress.steps if not step.blocking]
    assert [step.step_id for step in skipped] == [
        "rubric_readback", "decomposability", "grade_policy",
    ]
    for step in skipped:
        # Present-and-unavailable with a note that says why: what a teacher defers must
        # be rendered as deferrable, not as a missing feature (NFR-SETUP-04).
        assert step.note, (
            f"{step.step_id} is enumerated without a note — the console would render an "
            "unexplained blank"
        )
    assert "publish" not in [step.step_id for step in progress.steps]
    assert progress.remaining_steps == 1  # only the blocking inventory step counts


# --- TC-SETUP-22 ---------------------------------------------------------------------------


def test_tc_setup_22_template_version_pinned_recorded_on_every_package_and_tracks_changes(
    monkeypatch,
):
    """`TC-SETUP-22` (NFR-SETUP-03, P1) — the proposal prompt template is version-pinned
    (`setup-inventory-v1`, a name a regex can pin, not a bare number); the version is
    recorded verbatim on every package's proposal row; and changing the template changes
    the recorded version — asserted by bumping the pin to `setup-inventory-v2` and
    proposing into a fresh package, so a version that stopped being recorded, or a record
    that hardcoded the old literal, both go red here."""
    version = aeh.setup.SETUP_PROMPT_TEMPLATE_V
    assert re.fullmatch(r"[a-z0-9-]+-v\d+", version), (
        f"the prompt template pin {version!r} is not a versioned name — NFR-SETUP-03 "
        "records a version so a change is visible in every package's provenance"
    )

    provider = ScriptedSetupProvider()
    catalog = ScriptedCatalog(package_id="pkg-a")
    proposal = make_setup_service(catalog, ScriptedIngestor(), provider).propose_inventory(
        "doc-a"
    )
    assert catalog.recorded, "the proposal was never recorded — nothing to pin a version on"
    assert catalog.recorded[0]["template_version"] == version
    assert proposal.template_version == version
    # The template rendered the assessment into the prompt it sent.
    assert any(ASSESSMENT_MD in str(field) for field in provider.calls[0].values())

    # Recorded on every package: a second package's row carries the same pin...
    catalog_b = ScriptedCatalog(package_id="pkg-b")
    make_setup_service(catalog_b, ScriptedIngestor(), provider).propose_inventory("doc-b")
    assert catalog_b.recorded[0]["template_version"] == version

    # ...and changing the template changes the version that gets recorded.
    with monkeypatch.context() as patch:
        patch.setattr(aeh.setup, "SETUP_PROMPT_TEMPLATE_V", "setup-inventory-v2")
        catalog_c = ScriptedCatalog(package_id="pkg-c")
        changed = make_setup_service(catalog_c, ScriptedIngestor(), provider).propose_inventory(
            "doc-c"
        )
        assert changed.template_version == "setup-inventory-v2"
        assert catalog_c.recorded[0]["template_version"] == "setup-inventory-v2"
