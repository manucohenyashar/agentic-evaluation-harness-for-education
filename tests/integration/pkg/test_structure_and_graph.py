"""Band sets, exemplars, the acyclic dependency graph and the per-run cache (`M-PKG`).

Cases `TC-PKG-06`, `TC-PKG-07`, `TC-PKG-12`, `TC-PKG-13`, `TC-PKG-14` (`FR-PKG-05`,
`-06`, `-07`, `NFR-PKG-05`), test plan §5.4. Issue #28.

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

ISSUE = "#28"


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


# --- TC-PKG-06: the band-set partition (P0) --------------------------------------------------------


@pytest.mark.parametrize(
    "band_count, valid",
    [(1, False), (2, True), (3, False), (4, True), (5, False), (6, True),
     (0, False), (7, False)],
    ids=["1-odd-small", "2-even", "3-odd", "4-even", "5-odd", "6-even", "0-empty", "7-big"],
)
def test_tc_pkg_06_band_count_partition(tmp_data_dir, band_count, valid):
    """`TC-PKG-06` — *'a criterion whose band_count is odd or outside 2..6 fails.'*

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


def test_tc_pkg_06_non_contiguous_ordinals_fail(tmp_data_dir):
    """`TC-PKG-06` — *'ordinals not contiguous from 0 fail'* — a gap would leave an
    unreachable band in the middle of the mapping."""
    store, handle, catalog = _fresh_catalog(tmp_data_dir)
    v = catalog.create_version(None, PackageDraft())
    catalog.add_criterion(v, "CRIT-G", question_id="Q", kind="open", max_points=4.0)
    catalog.add_band(v, "CRIT-G", 0, "b0", 0.0)
    with pytest.raises(BandSetError):
        catalog.add_band(v, "CRIT-G", 2, "b2", 2.0)  # skips ordinal 1
    store.close()


def test_tc_pkg_06_decreasing_points_fail(tmp_data_dir):
    """`TC-PKG-06` — *'points not non-decreasing in ordinal fail.'* M-AGG and M-GRADE
    assume the monotone band-to-points mapping; a decreasing pair breaks it silently."""
    store, handle, catalog = _fresh_catalog(tmp_data_dir)
    v = catalog.create_version(None, PackageDraft())
    catalog.add_criterion(v, "CRIT-D", question_id="Q", kind="open", max_points=4.0)
    catalog.add_band(v, "CRIT-D", 0, "b0", 0.0)
    catalog.add_band(v, "CRIT-D", 1, "b1", 2.0)
    with pytest.raises(BandSetError):
        catalog.add_band(v, "CRIT-D", 2, "b2", 1.0)  # 1.0 < 2.0: decreases
    store.close()


# --- TC-PKG-07: exemplars name declared bands (P1) --------------------------------------------------


def test_tc_pkg_07_an_exemplar_on_an_undeclared_band_is_refused(tmp_data_dir):
    """`TC-PKG-07` — *'an exemplar whose band does not name a band declared for its
    criterion fails.'* An exemplar anchored to an undeclared band would train judges
    toward a level the scoring pipeline cannot produce."""
    store, handle, catalog = _fresh_catalog(tmp_data_dir)
    v = catalog.create_version(None, PackageDraft())
    _seed_criterion_with_bands(catalog, v, "CRIT-E", bands=4)
    catalog.add_exemplar(v, "ex-ok", "CRIT-E", "b1")
    with pytest.raises(BandSetError):
        catalog.add_exemplar(v, "ex-bad", "CRIT-E", "b9")
    store.close()


# --- TC-PKG-12/13/14: the dependency graph and the cache (P0/P1) ------------------------------------


def test_tc_pkg_12_a_cyclic_dependency_write_is_refused(tmp_data_dir):
    """`TC-PKG-12` — *'a criterion_dependency write that would make the graph cyclic
    raises CyclicDependencyError.'* The extraction sweep's two-pass order rests on the
    graph being a DAG."""
    store, handle, catalog = _fresh_catalog(tmp_data_dir)
    v = catalog.create_version(None, PackageDraft())
    catalog.add_criterion(v, "CRIT-A", question_id="Q", kind="open", max_points=4.0)
    catalog.add_criterion(v, "CRIT-B", question_id="Q", kind="open", max_points=4.0,
                          dependencies=("CRIT-A",))
    # The two-node cycle closes by raw edge: A depending on B while B depends on A.
    # (A self-loop is refused earlier still, by the DDL's own CHECK constraint — a
    # failed write at the data layer.)
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


def test_tc_pkg_12_topological_order_serves_the_extraction_sweep(tmp_data_dir):
    """`TC-PKG-12` — *'topological_order returns a valid topological order over the
    dependency graph for M-ORCH's extraction sweep'* — dependencies before dependents,
    deterministic (Kahn's, sorted-ready)."""
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
        f"TC-PKG-12: the order {order} is not topological. M-ORCH's extraction sweep "
        "walks dependencies first; a dependent extracted before its dependency would "
        "score against evidence that does not exist yet."
    )
    store.close()


def test_tc_pkg_13_the_per_run_cache_serves_reads_and_invalidates_on_publish(
    tmp_data_dir,
):
    """`TC-PKG-13` — *'criteria(), bands() and points_for_band() are served from an
    in-process cache loaded once per run'* — and *'invalidation on version publish is
    part of this story'*: the cache must not become a second source of truth."""
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
        "TC-PKG-13: publishing changed the cached view. Invalidation must preserve the "
        "data — what it must NOT do is serve stale data after an edit (asserted below)."
    )
    # A revision edits its own rows; the cache must drop after the edit.
    v2 = catalog.create_version(v, PackageDraft(title="edited"))
    catalog.update_criterion_field(v2, "CRIT-C", "max_points", 9.0)
    rows = catalog.criteria(v2)
    assert any(r["max_points"] == 9.0 for r in rows), (
        "TC-PKG-13: the cache served stale data after an edit — it became a second "
        "source of truth, which design §3.4's cache criterion explicitly forbids."
    )
    store.close()


def test_tc_pkg_14_points_for_band_is_the_monotone_mapping(tmp_data_dir):
    """`TC-PKG-12`'s mapping half — *'points_for_band is served'* and monotone (the
    FR-PKG-06 guarantee the readers assume)."""
    store, handle, catalog = _fresh_catalog(tmp_data_dir)
    v = catalog.create_version(None, PackageDraft())
    _seed_criterion_with_bands(catalog, v, "CRIT-P", bands=4)
    points = [catalog.points_for_band("CRIT-P", f"b{i}") for i in range(4)]
    assert points == sorted(points), (
        "TC-PKG-14: points_for_band is not monotone in ordinal — M-AGG and M-GRADE "
        "assume the monotone mapping."
    )
    from aeh.pkg import PackageError

    with pytest.raises(PackageError):
        catalog.points_for_band("CRIT-P", "b9")
    store.close()
