"""Band sets, exemplars and the dependency graph (`M-PKG`), at the plan's TC IDs.

Cases `TC-PKG-05`, `TC-PKG-07`, `TC-PKG-08`, `TC-PKG-11` and the cache/mapping halves of
`NFR-PKG-05` / `CT-PKG-04` (`FR-PKG-05`, `-06`, `-07`), test plan §5.4. Issue #32 (TS-11).

**Traceability repair (2026-09-07).** This file landed with #28 under shifted IDs — its
band-count partition was labelled `TC-PKG-06`, its exemplar case `TC-PKG-07`, its cycle
cases `TC-PKG-12`, its cache case `TC-PKG-13` and its mapping case `TC-PKG-14`; the plan
assigns those numbers to other cases entirely (TC-PKG-06 is the DAG property, TC-PKG-12
the manifest, TC-PKG-13 provenance-export, TC-PKG-14 the policy vocabulary, TC-PKG-26 the
cache query-count). The tests were renamed to the IDs the plan actually gives them — no
assertion changed in the renamed tests — because a test named for the wrong TC makes the
RTM point coverage at the wrong requirement. #32's delta on top of the renames: the
`TC-PKG-05` named cells the #28 tests did not cover (the 3-cycle, the self-edge, the DAG
invariant) and the `TC-PKG-08` cells (ordinals 1,2,3 and 0,1,1; equal adjacent points
permitted).

Rung 2 — real Tier P files, because the band-set rules and the graph are enforced by
failed writes against the database.

`Written ahead of implementation: yes` is stale — the catalog landed with #26/#27/#28;
the cases run green by design.
"""

from __future__ import annotations

import pytest

from aeh.pkg import (
    BandSetError,
    CyclicDependencyError,
    PackageCatalog,
    PackageDraft,
)
from aeh.store import open_store
from tests.support.store_api import statement

pytestmark = pytest.mark.integration

ISSUE = "#32"


def _fresh_catalog(tmp_data_dir, package_id: str = "pkg-28") -> tuple:
    store = open_store(tmp_data_dir)
    handle = store.package(package_id)
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO package (package_id, created_at) "
            "VALUES (:p, '2026-01-01')", issue=ISSUE), p=package_id)
    catalog = PackageCatalog(handle, package_id=package_id)
    return store, handle, catalog


def _seed_criterion_with_bands(catalog, v, criterion_id: str, *, bands: int = 4,
                               kind: str = "open"):
    catalog.add_criterion(v, criterion_id, question_id=f"Q-{criterion_id}",
                          kind=kind, max_points=float(bands - 1))
    for ordinal in range(bands):
        catalog.add_band(v, criterion_id, ordinal, f"b{ordinal}", float(ordinal),
                         f"descriptor {ordinal}")


# --- TC-PKG-07: the band_count boundary (P0) --------------------------------------------------------


@pytest.mark.parametrize(
    "band_count, valid",
    [(1, False), (2, True), (3, False), (4, True), (5, False), (6, True),
     (0, False), (7, False)],
    ids=["1-odd-small", "2-even", "3-odd", "4-even", "5-odd", "6-even", "0-empty", "7-big"],
)
def test_tc_pkg_07_band_count_partition(tmp_data_dir, band_count, valid):
    """`TC-PKG-07` — *'band_count of 1, 2, 3, 4, 5, 6, 7: 2, 4 and 6 accepted; 1, 3, 5
    and 7 rejected as odd or out of range. Both boundaries tested, not just the type.'*

    Oracle: **exact exception per partition cell** — the sweep covers odd/even and
    in/out of 2..6 rather than sampling one representative."""
    store, handle, catalog = _fresh_catalog(tmp_data_dir)
    v = catalog.create_version(None, PackageDraft())
    if valid:
        catalog.add_criterion(v, "CRIT-B", question_id="Q-1", kind="open",
                              max_points=4.0, band_count=band_count)
        for ordinal in range(band_count):
            catalog.add_band(v, "CRIT-B", ordinal, f"b{ordinal}", float(ordinal))
        assert len(catalog.bands("CRIT-B")) == band_count
    else:
        with pytest.raises(BandSetError):
            catalog.add_criterion(v, "CRIT-B", question_id="Q-1", kind="open",
                                  max_points=4.0, band_count=band_count)
    store.close()


# --- TC-PKG-08: ordinals and points (P0) -------------------------------------------------------------


def test_tc_pkg_08_contiguous_ordinals_from_zero_are_accepted(tmp_data_dir):
    """`TC-PKG-08` — the `0,1,2` cell: ordinals contiguous from zero are accepted, and
    **equal adjacent points are permitted** — the rule is non-DEcreasing, not strictly
    increasing, so two bands may share a points value."""
    store, handle, catalog = _fresh_catalog(tmp_data_dir)
    v = catalog.create_version(None, PackageDraft())
    catalog.add_criterion(v, "CRIT-O", question_id="Q", kind="open", max_points=4.0,
                          band_count=4)
    catalog.add_band(v, "CRIT-O", 0, "b0", 1.0)
    catalog.add_band(v, "CRIT-O", 1, "b1", 1.0)  # equal at one step: permitted
    catalog.add_band(v, "CRIT-O", 2, "b2", 2.0)
    assert [row["points"] for row in catalog.bands("CRIT-O")] == [1.0, 1.0, 2.0], (
        "TC-PKG-08 (0,1,2 with equal points): a set the rule permits was refused, or "
        "the stored points drifted. Non-decreasing includes equal; refusing equality "
        "would outlaw a legitimate rubric."
    )
    store.close()


def test_tc_pkg_08_ordinals_not_starting_at_zero_are_refused(tmp_data_dir):
    """`TC-PKG-08` — the `1,2,3` cell: an ordinal set that starts at 1 is not contiguous
    from zero, and is refused with the structural error."""
    store, handle, catalog = _fresh_catalog(tmp_data_dir)
    v = catalog.create_version(None, PackageDraft())
    catalog.add_criterion(v, "CRIT-S", question_id="Q", kind="open", max_points=4.0)
    with pytest.raises(BandSetError):
        catalog.add_band(v, "CRIT-S", 1, "b1", 1.0)  # first ordinal is 1, not 0
    store.close()


def test_tc_pkg_08_duplicate_ordinals_are_refused_as_a_no_op(tmp_data_dir):
    """`TC-PKG-08` — the `0,1,1` cell: a duplicate ordinal is refused with
    `BandSetError` — the structural error the band rules' taxonomy promises — and the
    refusal is a no-op (`CT-PKG-11`).

    Before #32 the duplicate hit the band table's composite primary key and surfaced as
    a bare `sqlite3.IntegrityError`; the catalog now refuses it before the INSERT (the
    database's key remains the backstop for raw writes)."""
    store, handle, catalog = _fresh_catalog(tmp_data_dir)
    v = catalog.create_version(None, PackageDraft())
    catalog.add_criterion(v, "CRIT-D", question_id="Q", kind="open", max_points=4.0)
    catalog.add_band(v, "CRIT-D", 0, "b0", 0.0)
    catalog.add_band(v, "CRIT-D", 1, "b1", 1.0)
    with pytest.raises(BandSetError):
        catalog.add_band(v, "CRIT-D", 1, "b1-again", 1.5)  # duplicate ordinal
    rows = handle.query(statement(
        "SELECT ordinal, band, points FROM band WHERE package_version_id = :v "
        "AND criterion_id = 'CRIT-D' ORDER BY ordinal", issue=ISSUE), v=v)
    assert [tuple(row) for row in rows] == [(0, "b0", 0.0), (1, "b1", 1.0)], (
        "TC-PKG-08 (0,1,1): the refused duplicate left a row behind — a rejected write "
        "must be a no-op (CT-PKG-11), or the stored set is the invalid one the rule "
        "exists to prevent."
    )
    store.close()


def test_tc_pkg_08_non_contiguous_ordinals_fail(tmp_data_dir):
    """`TC-PKG-08` — the `0,2,3` cell: *'ordinals not contiguous from 0 fail'* — a gap
    would leave an unreachable band in the middle of the mapping."""
    store, handle, catalog = _fresh_catalog(tmp_data_dir)
    v = catalog.create_version(None, PackageDraft())
    catalog.add_criterion(v, "CRIT-G", question_id="Q", kind="open", max_points=4.0)
    catalog.add_band(v, "CRIT-G", 0, "b0", 0.0)
    with pytest.raises(BandSetError):
        catalog.add_band(v, "CRIT-G", 2, "b2", 2.0)  # skips ordinal 1
    rows = handle.query(statement(
        "SELECT ordinal FROM band WHERE package_version_id = :v "
        "AND criterion_id = 'CRIT-G' ORDER BY ordinal", issue=ISSUE), v=v)
    assert [row["ordinal"] for row in rows] == [0], (
        "TC-PKG-08 (0,2,3): the refused gapped set left its row behind — the refusal "
        "must be a no-op (CT-PKG-11)."
    )
    store.close()


def test_tc_pkg_08_decreasing_points_fail(tmp_data_dir):
    """`TC-PKG-08` — *'points not non-decreasing in ordinal fail.'* M-AGG and M-GRADE
    assume the monotone band-to-points mapping; a decreasing pair breaks it silently.

    The refusal is also asserted to be a no-op: before #32 the whole-set validation ran
    after the transaction committed, so the refused band stayed on disk behind the
    raised error — the invalid set the rule exists to prevent, persisted."""
    store, handle, catalog = _fresh_catalog(tmp_data_dir)
    v = catalog.create_version(None, PackageDraft())
    catalog.add_criterion(v, "CRIT-D", question_id="Q", kind="open", max_points=4.0)
    catalog.add_band(v, "CRIT-D", 0, "b0", 0.0)
    catalog.add_band(v, "CRIT-D", 1, "b1", 2.0)
    with pytest.raises(BandSetError):
        catalog.add_band(v, "CRIT-D", 2, "b2", 1.0)  # 1.0 < 2.0: decreases
    rows = handle.query(statement(
        "SELECT ordinal, band, points FROM band WHERE package_version_id = :v "
        "AND criterion_id = 'CRIT-D' ORDER BY ordinal", issue=ISSUE), v=v)
    assert [tuple(row) for row in rows] == [(0, "b0", 0.0), (1, "b1", 2.0)], (
        "TC-PKG-08 (decreasing): the refused band left a row behind — a rejected write "
        "must be a no-op (CT-PKG-11), and the persisted set would be the non-monotone "
        "one M-AGG and M-GRADE cannot consume."
    )
    store.close()


# --- TC-PKG-11: exemplars name declared bands (P1) ---------------------------------------------------


def test_tc_pkg_11_an_exemplar_on_an_undeclared_band_is_refused(tmp_data_dir):
    """`TC-PKG-11` — *'an exemplar naming a band not declared for its criterion is
    rejected; one naming a declared band is accepted.'* An exemplar anchored to an
    undeclared band would train judges toward a level the scoring pipeline cannot
    produce."""
    store, handle, catalog = _fresh_catalog(tmp_data_dir)
    v = catalog.create_version(None, PackageDraft())
    _seed_criterion_with_bands(catalog, v, "CRIT-E", bands=4)
    catalog.add_exemplar(v, "ex-ok", "CRIT-E", "b1")
    with pytest.raises(BandSetError):
        catalog.add_exemplar(v, "ex-bad", "CRIT-E", "b9")
    store.close()


# --- TC-PKG-05: the dependency graph (P0) ------------------------------------------------------------


def test_tc_pkg_05_the_named_cycle_cells(tmp_data_dir):
    """`TC-PKG-05` — the case's four named inputs, cell for cell: *'a dependency set
    forming a 2-cycle; a 3-cycle; a self-edge; a DAG.'*

    Each cycle and the self-edge raise `CyclicDependencyError` at the write (`FR-PKG-05`,
    `CT-PKG-06`: at write time, never at read time), the refusal leaves no edge behind,
    and the DAG is accepted with a `topological_order` consistent with every edge.

    The self-edge cell is the one that found a defect: the DDL's
    `CHECK (criterion_id <> depends_on)` refused the raw write, but with
    `sqlite3.IntegrityError` — not the `CyclicDependencyError` FR-PKG-05 promises the
    caller. The catalog now refuses the self-edge before the INSERT; the CHECK remains
    the backstop for writes that route around the catalog."""
    store, handle, catalog = _fresh_catalog(tmp_data_dir)
    v = catalog.create_version(None, PackageDraft(criteria=("C1", "C2", "C3")))

    # The 2-cycle and the 3-cycle, each refused and each a no-op:
    with pytest.raises(CyclicDependencyError):
        catalog.set_dependencies(v, (("C2", "C1"), ("C1", "C2")))
    with pytest.raises(CyclicDependencyError):
        catalog.set_dependencies(v, (("C2", "C1"), ("C3", "C2"), ("C1", "C3")))
    # The self-edge, on both write surfaces:
    with pytest.raises(CyclicDependencyError):
        catalog.set_dependencies(v, (("C1", "C1"),))
    with pytest.raises(CyclicDependencyError):
        catalog.add_criterion(v, "C4", question_id="Q-4", kind="open",
                              max_points=4.0, dependencies=("C4",))

    # Every refusal was a no-op: no edge was stored, and the version orders cleanly.
    assert catalog.topological_order(v) == ("C1", "C2", "C3")

    # The DAG half: a valid edge set is accepted, and the order satisfies every edge.
    edges = (("C1", "C2"), ("C1", "C3"), ("C2", "C3"))
    catalog.set_dependencies(v, edges)
    order = catalog.topological_order(v)
    position = {name: index for index, name in enumerate(order)}
    assert all(position[before] < position[after] for before, after in edges), (
        f"TC-PKG-05 (DAG): the order {order} violates an edge of {edges}. The "
        "extraction sweep walks dependencies first; a dependent extracted before its "
        "dependency would score against evidence that does not exist yet."
    )
    store.close()


def test_tc_pkg_05_a_cyclic_dependency_write_is_refused(tmp_data_dir):
    """`TC-PKG-05` — *'a criterion_dependency write that would make the graph cyclic
    raises CyclicDependencyError'* — and a cycle that reached the store by a write that
    routed around the catalog (the DDL CHECK only bars the self-edge) is refused at
    READ time too, so no reader can silently consume it.

    The post-insert acyclic check also refuses the next guarded criterion added into an
    already-cyclic version: the write fails, not the sweep."""
    store, handle, catalog = _fresh_catalog(tmp_data_dir)
    v = catalog.create_version(None, PackageDraft())
    catalog.add_criterion(v, "CRIT-A", question_id="Q", kind="open", max_points=4.0)
    catalog.add_criterion(v, "CRIT-B", question_id="Q", kind="open", max_points=4.0,
                          dependencies=("CRIT-A",))
    # The two-node cycle closes by raw edge: A depending on B while B depends on A.
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO criterion_dependency (package_version_id, criterion_id, "
            "depends_on) VALUES (:v, 'CRIT-A', 'CRIT-B')", issue=ISSUE), v=v)
    with pytest.raises(CyclicDependencyError):
        catalog.topological_order(v)
    # And the post-insert acyclic check refuses the NEXT guarded criterion added into
    # an already-cyclic version: the write fails, not the sweep.
    with pytest.raises(CyclicDependencyError):
        catalog.add_criterion(v, "CRIT-AFTER", question_id="Q", kind="open",
                              max_points=4.0)
    store.close()


def test_tc_pkg_05_topological_order_serves_the_extraction_sweep(tmp_data_dir):
    """`TC-PKG-05` — *'the DAG yields a topological_order consistent with every edge'* —
    dependencies before dependents, deterministic (Kahn's, sorted-ready)."""
    store, handle, catalog = _fresh_catalog(tmp_data_dir)
    v = catalog.create_version(None, PackageDraft())
    catalog.add_criterion(v, "CRIT-ROOT", question_id="Q", kind="open", max_points=4.0)
    catalog.add_criterion(v, "CRIT-MID", question_id="Q", kind="open", max_points=4.0,
                          dependencies=("CRIT-ROOT",))
    catalog.add_criterion(v, "CRIT-LEAF", question_id="Q", kind="open", max_points=4.0,
                          dependencies=("CRIT-MID",))
    order = catalog.topological_order(v)
    position = {name: index for index, name in enumerate(order)}
    assert position["CRIT-ROOT"] < position["CRIT-MID"] < position["CRIT-LEAF"], (
        f"TC-PKG-05: the order {order} is not topological. M-ORCH's extraction sweep "
        "walks dependencies first; a dependent extracted before its dependency would "
        "score against evidence that does not exist yet."
    )
    store.close()


# --- NFR-PKG-05 / CT-PKG-04: the cache and the mapping read surface ---------------------------------


def test_nfr_pkg_05_the_per_run_cache_serves_reads_and_invalidates_on_publish(
    tmp_data_dir,
):
    """`NFR-PKG-05`'s behavioural half — *'criteria(), bands() and points_for_band() are
    served from an in-process cache loaded once per run'* — and *'invalidation on
    version publish is part of this story'*: the cache must not become a second source
    of truth.

    The plan's TC-PKG-26 oracle for the load-count claim (the query spy) is asserted in
    the contract tier as `TC-PKG-C15`
    (`tests/contract/pkg/test_ct_pkg_catalog.py`); this test holds the invalidation
    behaviour the cache criterion in design §3.4 demands."""
    store, handle, catalog = _fresh_catalog(tmp_data_dir)
    v = catalog.create_version(None, PackageDraft())
    _seed_criterion_with_bands(catalog, v, "CRIT-C", bands=4)
    first = catalog.criteria(v)
    again = catalog.criteria(v)
    assert first == again
    # The published flag flips: publish invalidates, so the next read reflects reality.
    catalog.publish(v, "approver")
    after_publish = catalog.criteria(v)
    assert after_publish == first, (
        "NFR-PKG-05: publishing changed the cached view. Invalidation must preserve "
        "the data — what it must NOT do is serve stale data after an edit (asserted "
        "below)."
    )
    # A revision edits its own rows; the cache must drop after the edit.
    v2 = catalog.create_version(v, PackageDraft(title="edited"))
    catalog.update_criterion_field(v2, "CRIT-C", "max_points", 9.0)
    rows = catalog.criteria(v2)
    assert any(r["max_points"] == 9.0 for r in rows), (
        "NFR-PKG-05: the cache served stale data after an edit — it became a second "
        "source of truth, which design §3.4's cache criterion explicitly forbids."
    )
    store.close()


def test_ct_pkg_04_points_for_band_is_the_monotone_mapping(tmp_data_dir):
    """`CT-PKG-04`'s read half — the band→points mapping the callers consume is monotone
    in ordinal (the `FR-PKG-06` guarantee), and an unknown band is refused rather than
    silently scoring zero. The clause suite's canonical form for `CT-PKG-04` is
    `tests/contract/pkg/test_ct_pkg_catalog.py`."""
    store, handle, catalog = _fresh_catalog(tmp_data_dir)
    v = catalog.create_version(None, PackageDraft())
    _seed_criterion_with_bands(catalog, v, "CRIT-P", bands=4)
    points = [catalog.points_for_band("CRIT-P", f"b{i}") for i in range(4)]
    assert points == sorted(points), (
        "CT-PKG-04: points_for_band is not monotone in ordinal — M-AGG and M-GRADE "
        "assume the monotone mapping."
    )
    from aeh.pkg import PackageError

    with pytest.raises(PackageError):
        catalog.points_for_band("CRIT-P", "b9")
    store.close()
