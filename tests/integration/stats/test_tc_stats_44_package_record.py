"""Validity T6 (issue #899): the package record (TC-STATS-44, FR-STATS-35).

The record seed (test plan §2.4): three administrations of one package version, recorded in
order. Class A marks 12 of 12 drawn seats, class B skips (with one seat drafted), class C marks
20 of 20. That is n = 32 >= 30 on the one judged line drawn (C-11, holistic, four bands). In
the 29 variant, class C leaves 3 of its 20 seats unmarked. Only C-11 has judged cells, so the
per-criterion n is the administration total: `too_few` is decided per criterion.

Every label comes from a real draw and Finish, and every record from `promote_administration`.
The world is `tests/support/validity_seed.py`.
"""

from __future__ import annotations

import pytest

from tests.support.validity_seed import HOLISTIC, ValidityStore

pytestmark = pytest.mark.integration

TOLERANCE = 1e-9

# Class A: the validity seed's holistic line. Confusion [[1,0,0,0],[2,6,2,0],[0,0,1,0],0].
A_SYSTEM = ("B1",) + ("B2",) * 10 + ("B3",)
A_TEACHER = ("B1",) * 3 + ("B2",) * 6 + ("B3",) * 3
# Class B: 15 drawable cells, skipped.
B_SYSTEM = ("B2",) * 15
# Class C: system B2 x10 (teacher B2 x8, B3 x2), system B3 x10 (teacher B2 x1, B3 x9).
# Confusion [[0,0,0,0],[0,8,2,0],[0,1,9,0],[0,0,0,0]].
C_SYSTEM = ("B2",) * 10 + ("B3",) * 10
C_TEACHER = ("B2",) * 8 + ("B3",) * 2 + ("B2",) + ("B3",) * 9


def _administer(world, cohort_id, system, teacher, *, unmarked=0, skip=False):
    administration = world.administer(cohort_id, {HOLISTIC: system})
    seats = world.draw(administration, max(15, len(system)))
    assert len(seats) == len(system), f"fixture: {cohort_id} drew {len(seats)} seats"
    by_cell = {(administration.submission(i), HOLISTIC): band for i, band in enumerate(teacher)}
    if skip:
        world.mark(administration, seats[:1], {(seats[0][1], HOLISTIC): "B2"})
        world.skip(administration)
        world.promote(administration, "skip")
        return administration
    # The unmarked seats are the last `unmarked` cells (C's agreeing B3 ones), whatever seat
    # the draw put them in.
    keep = set(list(by_cell)[:len(by_cell) - unmarked])
    marked = world.mark(administration, seats, {cell: by_cell[cell] for cell in keep})
    assert marked == len(system) - unmarked
    world.finish(administration)
    outcome = world.promote(administration, "finish")
    assert outcome.promoted, outcome.reason
    return administration


def _record_seed(root, *, c_unmarked=0):
    world = ValidityStore(root)
    a = _administer(world, "class-a", A_SYSTEM, A_TEACHER)
    b = _administer(world, "class-b", B_SYSTEM, (), skip=True)
    c = _administer(world, "class-c", C_SYSTEM, C_TEACHER, unmarked=c_unmarked)
    return world, (a, b, c)


def test_tc_stats_44_a_record_seed_32_gives_the_pooled_per_criterion_figure(
        tmp_path, network_guard):
    """TC-STATS-44: n = 32 -> per-criterion agreement with n, pooled over the administrations.

    Pooled confusion (A + C; B collected nothing), rows = system, columns = teacher:
      [[1,0,0,0], [2,14,4,0], [0,1,10,0], [0,0,0,0]], N = 32, matched 25.
      p_o = 25/32; system marginals (1, 20, 11, 0), teacher marginals (3, 15, 14, 0);
      p_e = (3 + 300 + 154)/1024 = 457/1024;
      kappa = (800 - 457)/(1024 - 457) = 343/567 = 49/81 = 0.604938271604...
      QWK: sum w*O = 2*1 + 4*1 + 1*1 = 7;
           sum w*E = [1*(15 + 56) + 20*(3 + 14) + 11*(12 + 15)]/32 = 708/32;
           QWK = 1 - 7*32/708 = 121/177 = 0.683615819209...
    The latest administration alone (C) gives kappa 0.7 (p_o 17/20, p_e 1/2): a record that read
    only the newest figure fails on the kappa."""
    world, (a, b, c) = _record_seed(tmp_path / "w")
    try:
        from aeh.stats import package_record

        record = package_record(world.store, a.package_version_id)
        assert record.blind_labels == 32 and record.min_n_for_headline == 30
        (criterion,) = record.criteria
        assert (criterion.criterion_id, criterion.scoring_model) == (HOLISTIC, "holistic")
        assert (criterion.n, criterion.too_few, criterion.matched) == (32, False, 25), criterion
        assert criterion.kappa == pytest.approx(49 / 81, abs=TOLERANCE), criterion.kappa
        assert criterion.qwk == pytest.approx(121 / 177, abs=TOLERANCE), criterion.qwk
        assert criterion.administrations == 2, (
            f"{criterion.administrations} administrations pooled; A and C carry figures, "
            "B (skipped) carries none")

        handle = world.run_handle(a)
        assert (criterion.backend_profile, criterion.panel_build_ref) == (
            handle.backend_profile, handle.panel_build_ref)

        listed = [(item.cohort_id, item.blind_count, item.absence_reason, item.unmarked_count)
                  for item in record.administrations]
        assert listed == [("class-a", 12, None, 0), ("class-b", 0, "skipped", 0),
                          ("class-c", 20, None, 0)], listed
        for item in record.administrations:
            assert item.recorded_at, f"{item.cohort_id} is listed without a date"
            assert (item.backend_profile, item.panel_build_ref) == (
                handle.backend_profile, handle.panel_build_ref), item
        network_guard.assert_no_network()
    finally:
        world.close()


def test_tc_stats_44_b_the_29_variant_reads_too_few_with_n(tmp_path, network_guard):
    """TC-STATS-44: 12 + 17 = 29 -> `too_few` with n = 29, the figures withheld, and class C
    listed with `unmarked_count = 3`."""
    world, (a, _b, _c) = _record_seed(tmp_path / "w", c_unmarked=3)
    try:
        from aeh.stats import package_record

        record = package_record(world.store, a.package_version_id)
        (criterion,) = record.criteria
        assert (criterion.n, criterion.too_few) == (29, True), criterion
        assert (criterion.kappa, criterion.qwk, criterion.matched) == (None, None, None)
        assert record.blind_labels == 29
        assert [(item.cohort_id, item.blind_count, item.unmarked_count)
                for item in record.administrations][-1] == ("class-c", 17, 3)
        network_guard.assert_no_network()
    finally:
        world.close()


def test_tc_stats_44_b2_thirty_is_the_first_headline_n(tmp_path, network_guard):
    """TC-STATS-44, the boundary's other side: 12 + 18 = 30 = the minimum -> `too_few` false
    and the pooled figure shown (pins `n < 30`, not `n <= 30`)."""
    world, (a, _b, _c) = _record_seed(tmp_path / "w", c_unmarked=2)
    try:
        from aeh.stats import package_record

        (criterion,) = package_record(world.store, a.package_version_id).criteria
        assert (criterion.n, criterion.too_few) == (30, False), criterion
        assert criterion.kappa is not None and criterion.matched is not None, criterion
        network_guard.assert_no_network()
    finally:
        world.close()


def test_tc_stats_44_c_a_new_package_version_has_an_empty_record(tmp_path, network_guard):
    """TC-STATS-44: a revision of the version (a new package version) starts its own record:
    no administrations, no criteria, no labels. The old version's record is untouched."""
    world, (a, _b, _c) = _record_seed(tmp_path / "w")
    try:
        from aeh.stats import package_record

        revision = world.catalog().create_version(a.package_version_id)
        assert revision != a.package_version_id
        fresh = package_record(world.store, revision)
        assert (fresh.blind_labels, fresh.criteria, fresh.administrations) == (0, (), ())
        assert package_record(world.store, a.package_version_id).blind_labels == 32
        network_guard.assert_no_network()
    finally:
        world.close()


def test_tc_stats_44_d_the_console_serves_the_record(tmp_path, monkeypatch, network_guard):
    """TC-STATS-44 through `GET /api/v1/packages/record` (FR-CONSOLE-84's read of FR-STATS-35):
    the skipped administration shows its absence reason and no `blind_count`; the others show
    `blind_count`; the pooled figure carries n = 32."""
    from aeh.console import serve_console

    world, (a, _b, _c) = _record_seed(tmp_path / "w")
    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    network_guard.uninstall()
    server = serve_console(store=world.store)
    try:
        from tests.support.label_identity_world import ServedRun

        console = ServedRun(world=a, server=server, port=server.socket.getsockname()[1],
                            root=world.root)
        status, read = console.get("/api/v1/packages/record",
                                   package_version_id=a.package_version_id)
        assert status == 200, read
        assert read["blind_labels"] == 32 and read["too_few"] is False
        (criterion,) = read["criteria"]
        assert criterion["n"] == 32 and criterion["kappa"] == pytest.approx(49 / 81)
        administrations = read["administrations"]
        assert [entry["class_name"] for entry in administrations] == [
            "class-a", "class-b", "class-c"]
        assert administrations[1]["absence_reason"] == "skipped"
        assert "blind_count" not in administrations[1], administrations[1]
        assert [administrations[i].get("blind_count") for i in (0, 2)] == [12, 20]
        assert all(entry["date"] and entry["backend"] and entry["panel_build_ref"]
                   for entry in administrations), administrations
    finally:
        try:
            server.terminate()
        finally:
            network_guard.install()
            world.close()
