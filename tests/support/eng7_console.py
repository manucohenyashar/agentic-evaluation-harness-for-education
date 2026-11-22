"""The ENG7 class graded through the console, for Validity T8 (issue #901): TC-CONSOLE-104…108,
114 and 116.

The four-paper ENG7 class (`tests/support/eng7_sample.py`) is built, enrolled and read in with
the operator commands, then graded by the console's own `start run` action over HTTP, under
the shipped dev-ci config with the stand-in OpenRouter transport. The run completes on the
console's worker thread. Every cell is routed `provisional` (the stand-in judge answers at
confidence 0.1), so M-REVIEW draws 15 of the 16 judged cells; which 15 is random per run, so
callers read the draw (`drawn_cells`) rather than assume it.

The world is served by a real `serve_console()` on a loopback port (rung 3). The run-start
outcome is kept on the world (`start_outcome`) for TC-CONSOLE-106.
"""

from __future__ import annotations

import io
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from tests.support.eng7_sample import DEV_CI_CONFIG, forget_sample_modules, ingest_eng7, run_rows
from tests.support.label_identity_world import ServedRun

#: How long the console's run worker may take on a slow box (seconds). Env-gated (seam 3).
RUN_JOIN_TIMEOUT_ENV = "AEH_TEST_ENG7_RUN_TIMEOUT_S"


@dataclass
class _RunIds:
    cohort_id: str
    run_id: str = ""


@dataclass
class Eng7Console(ServedRun):
    """The ENG7 run behind a live console, with what the start action answered."""

    package_version: str = ""
    start_outcome: dict = field(default_factory=dict)

    def raw_get(self, path: str) -> tuple[int, bytes]:
        """A GET whose body is returned as bytes (the file exports)."""
        import http.client

        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def service(self) -> Any:
        """The console's own review service for the run (reads the draw; never writes here)."""
        return self.server.app._review_service(self.run_id)

    def drawn_cells(self) -> set[tuple[str, str]]:
        """The (submission, criterion) cells of the run's draw, read from M-REVIEW."""
        return {(str(item.submission_id), str(item.criterion_id))
                for item in self.service().blind_draw_items(self.run_id)}

    def judged_cells(self) -> dict[tuple[str, str], dict]:
        """Every scored cell of the run, keyed (submission, criterion)."""
        return {(row["submission_id"], row["criterion_id"]): row for row in self.rows(
            "SELECT * FROM criterion_score WHERE run_id = ?", self.run_id)}

    def names(self) -> dict[str, str]:
        """submission id -> the student's full name on the roster."""
        return {row["submission_id"]: row["full_name"] for row in self.rows(
            "SELECT s.submission_id, r.full_name FROM submission s "
            "JOIN roster r ON r.student_ref = s.student_ref")}

    def open_draw(self) -> dict:
        """Open the draw the way the teacher does: read the blind seats."""
        status, read = self.get("/api/v1/blind-seats", run_id=self.run_id)
        assert status == 200 and read.get("state") == "open", (status, read)
        return read

    def seat_cells(self, read: dict) -> dict[str, tuple[str, str]]:
        """seat id -> (submission, criterion), from the draw's items in seat order."""
        items = list(self.service().blind_draw_items(self.run_id))
        return {seat["seat_id"]: (str(item.submission_id), str(item.criterion_id))
                for seat, item in zip(read["seats"], items, strict=True)}


@contextmanager
def eng7_console(root: Path, work: Path, monkeypatch: Any,
                 network_guard: Any) -> Iterator[Eng7Console]:
    """Ingest ENG7 into `root`, serve a console over it, start the run with the console's
    `start run` action and wait for it to complete."""
    import os

    from aeh.conf import parse_config_document
    from aeh.console import serve_console
    from aeh.store import open_store

    for key in ("HARNESS_PROFILE", "HARNESS_FIXTURE_DIR", "CONSOLE_BIND"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HARNESS_DECISION_ENGINE", "off")
    monkeypatch.setenv("CONSOLE_PORT", "0")
    root.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    store = None
    server = None
    try:
        world = ingest_eng7(root, work, monkeypatch, DEV_CI_CONFIG)
        cfg = parse_config_document(DEV_CI_CONFIG.read_text(encoding="utf-8"), "toml")
        store = open_store(root)
        network_guard.uninstall()
        with redirect_stdout(io.StringIO()):
            server = serve_console(store=store, cfg=cfg, config_path=str(DEV_CI_CONFIG))
        ids = _RunIds(cohort_id=world.cohort_id)
        served = Eng7Console(world=ids, server=server, port=server.socket.getsockname()[1],
                             root=root, package_version=world.package_version)
        status, outcome = served.action("start run", cohort_id=world.cohort_id,
                                        package_version=world.package_version)
        assert status == 200 and outcome.get("dispatched"), (status, outcome)
        served.start_outcome = outcome
        (row,) = run_rows(root)
        ids.run_id = row["run_id"]
        thread = server.app._run_threads[ids.run_id]
        thread.join(float(os.environ.get(RUN_JOIN_TIMEOUT_ENV, "180")))
        assert not thread.is_alive(), "fixture: the console's ENG7 run did not finish"
        (row,) = run_rows(root)
        assert row["status"] == "complete", f"fixture: the ENG7 run ended {row['status']!r}"
        yield served
    finally:
        try:
            if server is not None:
                server.terminate()
        finally:
            network_guard.install()
            forget_sample_modules()
            if store is not None:
                try:
                    store.close()
                except Exception as error:  # noqa: BLE001 — teardown after the assertions
                    if "can only be used in that same thread" not in str(error):
                        raise


__all__ = ["Eng7Console", "RUN_JOIN_TIMEOUT_ENV", "eng7_console"]
