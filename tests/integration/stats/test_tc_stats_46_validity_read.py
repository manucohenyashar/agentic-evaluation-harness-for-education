"""TC-STATS-46 (CT-STATS-29), rung 3: the validity read shows per-criterion figures on the
multi-criterion seed, where `agreement_kappa` is NULL.

The read is `GET /api/v1/results/validity` on a real console over the validity seed
(`tests/support/validity_seed.py`), promoted through `promote_administration`. The record's
`agreement_kappa` is NULL (two criteria), so a read that showed it would show no figure. The
mutation "make the validity read use `agreement_kappa`" (in `administration_figure_views`)
turns every criterion's kappa to None and this case red. The census half is
`tests/contract/stats/test_tc_stats_46_agreement_kappa_census.py`.
"""

from __future__ import annotations

import pytest

from tests.support.label_identity_world import ServedRun
from tests.support.validity_seed import ATOMIC, HOLISTIC, validity_seed

pytestmark = pytest.mark.integration


def test_tc_stats_46_the_validity_read_shows_per_criterion_figures(
        tmp_path, monkeypatch, network_guard):
    """TC-STATS-46: on the two-criterion seed the read's `criteria` carries each judged
    criterion's own stored kappa (C-10 0.5, C-11 5/13), the QWK only on the four-band line, and
    the record it reads holds `agreement_kappa = NULL`."""
    from aeh.console import serve_console

    world, administration = validity_seed(tmp_path / "w")
    try:
        world.promote(administration, "finish")
        (record,) = world.package_validation(administration)
        assert record["agreement_kappa"] is None, "fixture: the seed is not multi-criterion"

        for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
            monkeypatch.delenv(name, raising=False)
        network_guard.uninstall()
        server = serve_console(store=world.store)
        try:
            console = ServedRun(world=administration, server=server,
                                port=server.socket.getsockname()[1], root=world.root)
            status, read = console.get("/api/v1/results/validity", run_id=administration.run_id)
        finally:
            try:
                server.terminate()
            finally:
                network_guard.install()
        assert status == 200, read
        assert read["state"] == "recorded", read
        figures = {item["criterion_id"]: item for item in read["criteria"]}
        assert set(figures) == {ATOMIC, HOLISTIC}, read["criteria"]
        assert figures[ATOMIC]["kappa"] == pytest.approx(0.5, abs=1e-9), figures[ATOMIC]
        assert figures[HOLISTIC]["kappa"] == pytest.approx(5 / 13, abs=1e-9), figures[HOLISTIC]
        assert figures[HOLISTIC]["qwk"] == pytest.approx(0.5, abs=1e-9)
        assert "qwk" not in figures[ATOMIC], figures[ATOMIC]
        assert (figures[ATOMIC]["scoring_model"], figures[HOLISTIC]["scoring_model"]) == (
            "atomic", "holistic")
        assert (figures[ATOMIC]["n"], figures[ATOMIC]["matched"]) == (12, 9)
    finally:
        world.close()
