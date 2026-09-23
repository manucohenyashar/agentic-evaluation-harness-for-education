"""`TS-84` (issue #378) — `TC-PIPE-10`: the production extraction view answers exactly what the
tests' view answers (`FR-PIPE-10`, `FR-INTEG-09`, gap-fix test plan §5 / §6).

| Case | Input | Expected |
|---|---|---|
| `TC-PIPE-10` | one store after extraction and panel | for every cell, `spans`, `second_family_spans`, `regions`, `panel_sufficiency` and `criterion_requires_citation` from `StoreExtractionView(handle, catalog, pv)` **equal** those from `LedgerEvidenceView` |

**What this case is really for.** `V-2` records that no production view exists and that the
integrity gate is driven in tests by `tests/support/e2e_world.py:423` `LedgerEvidenceView`. Every
gate assertion in this repo is therefore currently made against a **double**. `FR-INTEG-09`
publishes the real one, and `CT-INTEG-17` says the double must match it. Until something compares
the two, "the gate works" means "the gate works against the stand-in" — which is exactly the
class of claim a harness exists to stop anyone making.

So the oracle is a **differential**, not a property: whatever the double answers, the real view
answers, cell by cell and document by document. A test that checked the real view was
"reasonable" on its own would re-learn the double's bugs.

**Two things the plan does not settle, disclosed rather than guessed:**

1. *The constructor.* `FR-PIPE-10` (line 92) writes `StoreExtractionView(handle, catalog)`;
   `FR-INTEG-09` (line 303) writes `StoreExtractionView(handle, catalog, package_version_id)`
   and says the view was "moved here from FR-PIPE-10's consumer need". The three-argument form
   is taken as authoritative — it is the later statement, it belongs to the module that owns the
   view, and the test plan's own row spells it `(handle, catalog, pv)`. The inconsistency is a
   finding for the design, reported in #378's PR rather than silently resolved.
2. *The return shapes differ, and the gate tolerates that on purpose.* The double returns
   `SimpleNamespace`; the production view returns plain `dict`s and, for `panel_sufficiency`, a
   bare tuple. `IntegrityGate` reads both through its own adapters — `_span_items`,
   `_region_items`, and a `getattr(panel, "evidence_sufficient", None)` that falls back to a
   tuple/list (`integ.py:483`, `:500`, `:985`). So raw equality of the returned objects is the
   WRONG oracle: it fails on a difference the gate is explicitly written to absorb, and the
   plan's "equal" can only sensibly mean *equal in what the gate derives*. Both sides are
   therefore compared through the gate's own adapters. That is a stronger oracle than a shape
   match, not a weaker one — it asks the question the gate asks.

**`regions` is asked in the gate's own spelling.** The gate passes `doc-<submission_id>`, and the
double resolves that through the document table's submission foreign key
(`e2e_world.py:487`). The differential asks both views the same question the gate asks, rather
than a question only one of them understands.

**The world drives itself.** Unlike TS-83's cases, nothing here needs `run_to_completion`: the
store is brought to "after extraction and panel" by `SynthWorld`'s own drive loop, which is what
that world is built for. Verified: at `n_submissions=3` the build is ~1s and the full drive
~4s, so this case is cheap despite being rung 2 over a real store.

**Written ahead of implementation: NO.** `StoreExtractionView` already exists in `aeh.integ`
with the five declared reads and the signature `(handle, catalog, package_version_id,
run_id='')` — #363 is parked on the *rest* of its scope (idempotent verify, document cache,
indexes), not on the view. So these cases carry no marker and no `WRITTEN_AHEAD_BLOCKERS`
entry: they run for real, today, and the differential `V-2` asks for is answerable now rather
than whenever #363 is unparked. The registry's resolved-blocker gate is what caught this —
registering the symbol made it fire immediately.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.support.e2e_world import LedgerEvidenceView, SynthWorld
from tests.support.impl import INTEG_MODULE, require

pytestmark = pytest.mark.integration

ISSUE = "#363"

SUBMISSIONS = 3

#: The five reads `CT-INTEG-17` says the view implements exactly.
CELL_READS = ("spans", "second_family_spans", "panel_sufficiency")


def _gate_spans(value: Any) -> Any:
    """A span sequence as the gate sees it — `integ._span_items`, the gate's own adapter."""
    from aeh.integ import _span_items

    return _span_items(value)


def _gate_regions(value: Any) -> Any:
    """Regions as the gate sees them — `(region_kind, start, end, ocr_conf, crop_ref)` tuples."""
    from aeh.integ import _region_items

    return _region_items(value)


def _gate_panel_flags(panel: Any) -> Any:
    """The sufficiency flags as the gate extracts them (`integ.py:985`).

    `getattr(..., "evidence_sufficient")` first, then a bare tuple/list — the two shapes the
    gate accepts. Reproduced here rather than imported because the extraction is inline in the
    gate's method, not a named helper.
    """
    flags = getattr(panel, "evidence_sufficient", None)
    if flags is None and isinstance(panel, (tuple, list)):
        flags = panel
    return list(flags) if flags is not None else None


#: How each read is compared: the gate's own view of the answer, per read.
COMPARATORS = {
    "spans": _gate_spans,
    "second_family_spans": _gate_spans,
    "panel_sufficiency": _gate_panel_flags,
}


@pytest.fixture(scope="module")
def driven_world(tmp_path_factory):
    """A store after extraction and panel — the precondition the plan names.

    Module-scoped: the drive is the expensive part and every case in this file asks the same
    world the same kind of question, so building it once is the difference between ~4s and ~4s
    per case. Nothing here mutates it.
    """
    base = tmp_path_factory.mktemp("pipe10")
    data_dir = base / "data"
    for sub in ("packages", "cohorts", "blobs"):
        (data_dir / sub).mkdir(parents=True)
    world = SynthWorld(data_dir, base / "fixtures", n_submissions=SUBMISSIONS)
    try:
        world.build_run()
        world.start_run()
        world.drive_deterministic()
        world.integrity_pass()
        world.drive_extract()
        world.drive_score()
        yield world
    finally:
        world.store.close()


def _production_view(world: Any) -> Any:
    """The real view, built the way `FR-INTEG-09` spells it."""
    StoreExtractionView = require(INTEG_MODULE, "StoreExtractionView", issue=ISSUE)
    return StoreExtractionView(world.handle, world.catalog, world.version)


# --- TC-PIPE-10 ----------------------------------------------------------------------------


@pytest.mark.parametrize("read", CELL_READS)
def test_tc_pipe_10_the_production_view_matches_the_double_per_cell(read, driven_world):
    """`spans`, `second_family_spans` and `panel_sufficiency`, for every judged cell.

    Parametrised per read so a failure names which of the five diverged, rather than reporting
    that "the view disagrees" and leaving the reader to find where.
    """
    production = _production_view(driven_world)
    double = LedgerEvidenceView(driven_world)

    divergent = []
    for submission_id in driven_world.admitted_ids():
        for criterion_id in driven_world.open_ids:
            compare = COMPARATORS[read]
            expected = compare(getattr(double, read)(submission_id, criterion_id))
            actual = compare(getattr(production, read)(submission_id, criterion_id))
            if actual != expected:
                divergent.append((submission_id, criterion_id, expected, actual))

    assert divergent == [], (
        f"StoreExtractionView.{read} disagrees with LedgerEvidenceView on "
        f"{len(divergent)} cell(s). Every gate assertion in this repo is currently made against "
        f"the double (V-2), so a divergence here means the gate has been verified against a "
        f"stand-in that does not match the real thing (CT-INTEG-17). First: {divergent[:2]}"
    )
    assert driven_world.admitted_ids() and driven_world.open_ids, (
        "the differential compared no cells, so it asserted nothing"
    )


def test_tc_pipe_10_the_production_view_matches_the_double_on_regions(driven_world):
    """`regions`, asked in the gate's own `doc-<submission_id>` spelling.

    The gate never passes a minted document id — it passes its own spelling and lets the view
    resolve it (`e2e_world.py:487`). Asking the production view a question only it would
    understand would be testing a different interface from the one the gate uses.
    """
    production = _production_view(driven_world)
    double = LedgerEvidenceView(driven_world)

    divergent = []
    for submission_id in driven_world.admitted_ids():
        document_id = f"doc-{submission_id}"
        expected = _gate_regions(double.regions(document_id))
        actual = _gate_regions(production.regions(document_id))
        if actual != expected:
            divergent.append((document_id, expected, actual))

    assert divergent == [], (
        f"StoreExtractionView.regions disagrees with LedgerEvidenceView on {len(divergent)} "
        f"document(s). The gate's region extents drive its citation checks, so a divergence "
        f"here changes what the gate routes. First: {divergent[:1]}"
    )


def test_tc_pipe_10_the_production_view_matches_the_double_on_citation_requirement(
    driven_world
):
    """`criterion_requires_citation`, per criterion.

    Kept separate from the per-cell reads because it is keyed on the criterion alone: folding it
    into the cell sweep would ask the same question once per submission and hide which axis a
    disagreement is on.
    """
    production = _production_view(driven_world)
    double = LedgerEvidenceView(driven_world)

    divergent = [
        (criterion_id,
         double.criterion_requires_citation(criterion_id),
         production.criterion_requires_citation(criterion_id))
        for criterion_id in driven_world.open_ids
        if production.criterion_requires_citation(criterion_id)
        != double.criterion_requires_citation(criterion_id)
    ]
    assert divergent == [], (
        f"StoreExtractionView.criterion_requires_citation disagrees with LedgerEvidenceView on "
        f"{divergent}. This flag decides whether an uncited verdict is a fault, so the two "
        "views disagreeing means the gate's routing depends on which view it was handed"
    )
