"""`TS-86` (issue #380) — `TC-INTEG-15`: `StoreExtractionView` raises on a faulted read, and
the gate treats the raise as adverse (`FR-INTEG-09`, `CT-INTEG-01`, `NFR-INTEG-03`).

| Case | Input | Expected |
|---|---|---|
| `TC-INTEG-15` | the underlying read of `evidence` failing (`sqlite3.OperationalError` injected); a missing criterion | each read **raises**, never returns `()`, `None` or `False`. `IntegrityGate.verify` then takes `CT-INTEG-01`'s fail-closed route, never a pass |

**The one lie the gate cannot detect.** `StoreExtractionView`'s own docstring states the
contract: "a view that returned `[]` for a faulted evidence read would tell it 'measured, and
there is nothing', which is the one lie the gate cannot detect". An empty span list and a
broken database are the same value to every consumer downstream — the first is a student who
cited nothing, the second is a disk that stopped answering, and only one of them should
quarantine a cell. That is why the assertion here is on the **raise** and not on the value.

**The missing-criterion arm returns `True`, and that is the fail-closed answer, not a
violation.** `criterion_requires_citation` reads the catalog and ends `return True  #
fail-closed: an undeclared criterion is read as requiring citation`. The plan's "never returns
`False`" is what matters for that read, and it is asserted directly — a criterion the package
does not declare must not be released as needing no evidence.

**Both halves are needed.** The view raising is worth nothing if the gate swallows it into a
pass, so the second half drives a real `IntegrityGate` over a faulting view and asserts the
route. `CT-INTEG-01` allows either a review item or a retry; what it forbids is a clean pass,
so that is the shape of the assertion.

**Isolation: rung 2** — real store, real cohort ledger, real `StoreExtractionView`; the fault
is injected at the handle, which is the layer below the view and the one that actually breaks.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.integ import IntegrityGate, StoreExtractionView
from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.support.integ_vocabulary import document_id_for, seed_document
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

SUBMISSION = "SUB-101"
CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)
MARKDOWN = "The thesis is stated plainly, and the argument follows from it."

#: The five reads that ARE `M-INTEG`'s declared *Requires* surface (`CT-INTEG-17`). The first
#: four go to the cohort handle; `criterion_requires_citation` goes to the catalog.
HANDLE_BACKED_READS = (
    ("spans", (SUBMISSION, CRITERION)),
    ("second_family_spans", (SUBMISSION, CRITERION)),
    ("regions", (document_id_for(SUBMISSION),)),
    ("panel_sufficiency", (SUBMISSION, CRITERION)),
)


class FaultingHandle:
    """A cohort handle whose every query raises, as a broken file does.

    Wrapping the real handle rather than substituting a stub: `transaction()` and everything
    else still work, so the fault is exactly "the read failed" and not "the object is not a
    handle". `sqlite3.OperationalError` is the error the store actually surfaces.
    """

    def __init__(self, real: Any) -> None:
        self._real = real
        self.attempts = 0

    def query(self, *args: Any, **kwargs: Any) -> Any:
        self.attempts += 1
        raise sqlite3.OperationalError("disk I/O error")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


@pytest.fixture
def view_world(tmp_data_dir):
    """A real run with a document, and the real `StoreExtractionView` over its cohort."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        handle = store.cohort(ORCH_COHORT_ID)
        seed_document(
            handle, document_id_for(SUBMISSION), SUBMISSION, MARKDOWN, ORCH_COHORT_ID
        )
        orchestrator.enumerate_units(run_id)
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        yield store, handle, catalog, version, run_id
    finally:
        store.close()


# --- TC-INTEG-15, the view --------------------------------------------------------------


@pytest.mark.parametrize("method_name,args", HANDLE_BACKED_READS)
def test_tc_integ_15_a_faulted_read_raises_rather_than_returning_empty(
    view_world, method_name, args
):
    """Each handle-backed read raises `sqlite3.OperationalError`; none returns `()` or `None`.

    Parametrized over all four because the contract is about the *surface*, not about
    whichever read someone remembered to guard. A view with a `try/except` on one method and
    not the others reports "no evidence" for the unguarded cell and quarantines nothing.
    """
    store, handle, catalog, version, _run_id = view_world
    faulting = FaultingHandle(handle)
    view = StoreExtractionView(faulting, catalog, version)

    with pytest.raises(sqlite3.OperationalError):
        result = getattr(view, method_name)(*args)
        pytest.fail(
            f"{method_name} returned {result!r} on a faulted read instead of raising. An "
            "empty result tells the gate 'measured, and there is nothing' — which is the one "
            "lie it cannot detect (FR-INTEG-09, NFR-INTEG-03)"
        )

    assert faulting.attempts > 0, (
        f"{method_name} never reached the store, so the fault was not the thing it met"
    )


def test_tc_integ_15_an_undeclared_criterion_reads_as_requiring_citation(view_world):
    """The missing-criterion arm: `criterion_requires_citation` returns **True**, never False.

    A criterion the package version does not declare is unknown, and unknown is adverse. The
    opposite reading releases a zero-span cell as verified, which is what `FR-INTEG-03` exists
    to prevent.
    """
    store, handle, catalog, version, _run_id = view_world
    view = StoreExtractionView(handle, catalog, version)

    assert view.criterion_requires_citation("C-never-declared") is True, (
        "an undeclared criterion was read as needing no citation; the read fails closed "
        "(FR-INTEG-09)"
    )


def test_tc_integ_15_a_declared_criterion_is_still_read_from_the_catalog(view_world):
    """The positive control for the arm above.

    `True` is also what a read that ignored the catalog entirely would return, so without a
    criterion whose declaration produces a different answer, the fail-closed assertion proves
    nothing about the read.
    """
    store, handle, catalog, version, _run_id = view_world
    catalog.add_criterion(version, "C-none", kind="open", evidence_type="none")
    view = StoreExtractionView(handle, catalog, version)

    assert view.criterion_requires_citation("C-none") is False, (
        "a criterion declaring evidence_type='none' was still read as requiring citation, so "
        "criterion_requires_citation is not reading the declaration at all and the "
        "fail-closed case above is vacuous"
    )


# --- TC-INTEG-15, the gate's route --------------------------------------------------------


def test_tc_integ_15_the_gate_never_passes_a_cell_whose_evidence_read_faulted(view_world):
    """`IntegrityGate.verify` over a faulting view takes the fail-closed route, never a pass.

    The half that makes the raises matter. `CT-INTEG-01` allows a review item or a retry; what
    it forbids is a clean pass, so the assertion is that the cell did not come back verified
    and that the gate did something about it.
    """
    store, handle, catalog, version, run_id = view_world

    class FaultingView:
        """The real view's five-method surface, every read faulting — a double of
        `StoreExtractionView`, which is what `CT-INTEG-17` says a double must be."""

        def spans(self, submission_id: str, criterion_id: str) -> list:
            raise sqlite3.OperationalError("disk I/O error")

        def second_family_spans(self, submission_id: str, criterion_id: str) -> Any:
            raise sqlite3.OperationalError("disk I/O error")

        def regions(self, document_id: str) -> list:
            raise sqlite3.OperationalError("disk I/O error")

        def panel_sufficiency(self, submission_id: str, criterion_id: str) -> tuple:
            raise sqlite3.OperationalError("disk I/O error")

        def criterion_requires_citation(self, criterion_id: str) -> bool:
            raise sqlite3.OperationalError("disk I/O error")

    gate = IntegrityGate(handle, store.blobs(), FaultingView(), ocr_conf_floor=0.70)

    signals = gate.verify(run_id, SUBMISSION, CRITERION)

    assert signals.spans_verified is not True, (
        f"the gate reported spans_verified={signals.spans_verified!r} for a cell whose "
        "evidence read faulted. A fault is adverse and unknown, never a pass (CT-INTEG-01)"
    )
    assert signals.evidence_present is not True, (
        f"the gate reported evidence_present={signals.evidence_present!r} although it could "
        "not read any evidence"
    )

    routed = handle.query(
        "SELECT COUNT(*) AS n FROM review_queue WHERE submission_id = :s", s=SUBMISSION
    )[0]["n"]
    retried = handle.query(
        "SELECT MAX(attempts) AS a FROM work_unit WHERE run_id = :r AND submission_id = :s "
        "AND criterion_id = :c AND stage = 'extract'",
        r=run_id, s=SUBMISSION, c=CRITERION,
    )[0]["a"]
    assert int(routed or 0) > 0 or int(retried or 0) > 0, (
        "the gate neither queued a review item nor charged a retry for a cell it could not "
        "read at all — the cell passes through silently, which is the fail-OPEN outcome "
        "CT-INTEG-01 forbids"
    )
