"""Validity T5 (issue #898): drafts until the draw closes, the draw state machine, and the
review window's lapse under an injected clock (FR-REVIEW-26, FR-REVIEW-30, CT-REVIEW-27).

| Case | What it pins | Rung |
|---|---|---|
| TC-REVIEW-103 | 15 seats: a draft changed L1 -> L2 -> L3 reads L3 after the console restarts; 12 drafted, Finish -> 12 blind labels, `unmarked_count = 3`; draft, draw and a second Finish after Finish refused; Finish with 0 marked -> 0 labels, `none_marked` | 3, HTTP |
| TC-REVIEW-104 (a, b) | the legal and illegal transitions, `draw_state(run_id)` after each step | 3 |
| TC-REVIEW-105 | a 24 h window, 5 seats drafted: at +23 h 59 m still `open`; at +24 h 1 s the next read finds `closed_by_window`, 5 labels, `unmarked_count = n - 5`, and promote called exactly once (TC-PIPE-40's window-lapse row) | 3, injected clock |

TC-REVIEW-104's non-transitions (finalization, "Approve all grades", run completion) run over a
completed composed run in `tests/integration/pipe/test_tc_pipe_40_41_review_104_promotion_owner.py`.

**The world.** The F-DEV-PIPE world draws only three seats, so these cases seed a scored run
with 16 judged cells (8 submissions x 2 open criteria, routed `queued`) through the shipped
modules (`console_world.seed_scored_run`), and the draw is 15 of them. The review window, when
a case needs one, is the package version's `review_window_hours` (the console's "set review
window", FR-PKG-19), set before the draw opens: the window a draw is held to is fixed when it
opens.

**Disclosed departures (in the PR as well).**

1. *"Restart the console process"* is a console server terminated, the store closed, and a
   fresh store and fresh console opened over the same data directory, in-process. The draft is
   then read back over HTTP. No state survives except what is on disk.
2. *The draw is opened by M-REVIEW's `blind_sample`*, not the console's completion read: the
   console opens a draw only for a `complete` run, and the seeded run is scored without the
   orchestrator's dispatch loop. Every draft and Finish after that is an HTTP request.
3. *TC-REVIEW-105's "next read"* is the console's settle path (`blind_actions.settle_draw`,
   the function every blind read and action calls) handed a review service on the injected
   clock. The console builds its services on the wall clock, so the clock is injected at the
   one seam `settle_draw` exposes. Promotion then runs through the console's own call to
   `promote_administration`.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest

from tests.support.console_world import OPEN_CRITERIA, seed_scored_run
from tests.support.grade_vocabulary import write_scored_cells
from tests.support.label_identity_world import ServedRun

pytestmark = pytest.mark.integration

T0 = datetime(2030, 3, 4, 9, 0, 0, tzinfo=timezone.utc)
#: The open criteria's declared band scale, and three distinct levels of it.
BANDS = ("B1", "B2", "B3", "B4", "B5")
L1, L2, L3 = BANDS[:3]


class Clock:
    """An injected ISO-8601 clock (M-REVIEW's seam)."""

    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> str:
        return self.now.isoformat()

    def at(self, delta: timedelta) -> "Clock":
        self.now = T0 + delta
        return self


class SeededWorld:
    """A scored run with 16 queued judged cells over a real store."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = None
        self.world = None

    def open(self) -> Any:
        from aeh.store import open_store

        self.store = open_store(self.root)
        return self.store

    def seed(self, *, window_hours: int | None = None) -> None:
        from aeh.pkg import PackageCatalog

        store = self.open()
        self.world = seed_scored_run(store, submissions=8, with_open_criteria=True)
        cohort = store.cohort(self.world.cohort_id)
        open_ids = [criterion for criterion, _question in OPEN_CRITERIA]
        write_scored_cells(cohort, [(s, c, "B2", 2.0, "auto")
                                    for s in self.world.submissions for c in open_ids])
        with cohort.transaction() as tx:
            tx.execute("UPDATE criterion_score SET routing = 'queued', "
                       "state = 'provisional_unreviewed', judge_count = 3 "
                       "WHERE criterion_id IN ('C-10', 'C-11')")
        catalog = PackageCatalog(store.package(self.world.package_id),
                                 package_id=self.world.package_id)
        # The open criteria's band scale, declared in the package, so the console's catalog
        # and M-REVIEW's seats agree on the levels a draft may name.
        for criterion in open_ids:
            for ordinal, band in enumerate(BANDS):
                catalog.add_band(self.world.package_version_id, criterion, ordinal, band,
                                 float(ordinal))
        if window_hours is not None:
            catalog.set_review_window(self.world.package_version_id, window_hours)

    @property
    def run_id(self) -> str:
        return self.world.run_id

    @property
    def cohort_id(self) -> str:
        return self.world.cohort_id

    def service(self, clock: Any = None) -> Any:
        from aeh.review import review_service_over

        return review_service_over(self.store, cohort_ids=[self.cohort_id], run_id=self.run_id,
                                   actor="teacher", clock=clock)

    def draw(self, clock: Any = None, n: int = 15) -> Any:
        session = self.service(clock).blind_sample(self.run_id, n)
        assert len(session.items) == n, f"fixture: drew {len(session.items)} seats, not {n}"
        return session

    def blind_labels(self) -> list[dict]:
        return [dict(row) for row in self.store.durable().query(
            "SELECT * FROM label WHERE label_type = 'blind' AND run_id = :r", r=self.run_id)]

    def close(self) -> None:
        if self.store is not None:
            self.store.close()
            self.store = None


@contextmanager
def seeded(root: Path, **kwargs: Any) -> Iterator[SeededWorld]:
    world = SeededWorld(root)
    try:
        world.seed(**kwargs)
        yield world
    finally:
        world.close()


@contextmanager
def served(world: SeededWorld, monkeypatch: Any, network_guard: Any) -> Iterator[ServedRun]:
    """A real console over the seeded world's store."""
    from aeh.console import serve_console

    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    network_guard.uninstall()
    server = None
    try:
        server = serve_console(store=world.store)
        _host, port = server.socket.getsockname()[:2]
        yield ServedRun(world=world, server=server, port=port, root=world.root)
    finally:
        try:
            if server is not None:
                server.terminate()
        finally:
            network_guard.install()


def _seats(console: ServedRun) -> list[dict]:
    status, read = console.get("/api/v1/blind-seats", run_id=console.run_id)
    assert status == 200, f"the blind-seats read answered {status}: {read!r}"
    return read["seats"]


def _draft(console: ServedRun, seat_id: str, band: str) -> None:
    console.dispatched("blind-sample draft", run_id=console.run_id, seat_id=seat_id, band=band)


# --- TC-REVIEW-103: drafts until Finish ---------------------------------------------------------


def test_tc_review_103_a_drafts_survive_a_restart_and_become_labels_only_at_finish(
        tmp_path, monkeypatch, network_guard):
    """TC-REVIEW-103 (FR-REVIEW-26, CT-REVIEW-27). 15 seats. Seat 1 is drafted L1, L2, L3; the
    console restarts and the seat reads L3. 12 seats are drafted in all and Finish writes 12
    blind labels with `unmarked_count = 3` (on the draw record, the Finish reply, and the
    administration's promotion). After Finish a draft is refused, the draw route is refused,
    and a second Finish writes no label."""
    with seeded(tmp_path / "w") as world:
        world.draw()
        with served(world, monkeypatch, network_guard) as console:
            seats = _seats(console)
            assert len(seats) == 15
            first = seats[0]["seat_id"]
            for band in (L1, L2, L3):
                _draft(console, first, band)
        # The restart: nothing in memory survives, only the data directory.
        world.close()
        world.open()
        with served(world, monkeypatch, network_guard) as console:
            seats = _seats(console)
            drafts = {seat["seat_id"]: seat["draft_band"] for seat in seats}
            assert drafts[first] == L3, (
                f"after the restart seat 1 reads {drafts[first]!r}, not the last draft")
            assert world.blind_labels() == [], "a draft was written as a blind label"
            for seat in seats[1:12]:
                _draft(console, seat["seat_id"], L2)
            assert world.blind_labels() == [], "drafts were written as labels before Finish"
            outcome = console.dispatched("blind-sample finish", run_id=console.run_id)
            labels = world.blind_labels()
            assert len(labels) == 12, f"Finish wrote {len(labels)} blind labels, expected 12"
            assert outcome["rows_written"] == 12, outcome
            record = world.service().draw_record(world.run_id)
            assert (record.state, record.labels_written, record.unmarked_count,
                    record.absence_reason) == ("finished", 12, 3, None), record
            stored = console.rows("SELECT unmarked_count FROM package_validation "
                                  "WHERE cohort_id = ?", world.cohort_id, tier="durable")
            assert [row["unmarked_count"] for row in stored] == [3], stored

            status, refused = console.action("blind-sample draft", run_id=console.run_id,
                                             seat_id=seats[13]["seat_id"], band=L1)
            assert not refused.get("dispatched"), f"a draft after Finish was saved: {refused!r}"
            from aeh.review import ReviewError

            with pytest.raises(ReviewError):
                world.service().draft_blind(world.run_id, seats[13]["seat_id"], L1)
            with pytest.raises(ReviewError):
                world.service().blind_sample(world.run_id, 15)
            status, second = console.action("blind-sample finish", run_id=console.run_id)
            assert not second.get("dispatched"), f"a second Finish was dispatched: {second!r}"
            assert len(world.blind_labels()) == 12, "a second Finish wrote labels"
            status, read = console.get("/api/v1/blind-seats", run_id=console.run_id)
            assert status == 200 and read["state"] == "finished", (
                f"the console's draw route after Finish answered {status} {read!r}")
            assert world.service().draw_state(world.run_id) == "finished"


def test_tc_review_103_b_finish_with_nothing_marked_writes_no_label(
        tmp_path, monkeypatch, network_guard):
    """TC-REVIEW-103 boundary: Finish with 0 seats marked writes 0 blind labels and records
    `absence_reason = 'none_marked'`, with all 15 seats unmarked."""
    with seeded(tmp_path / "w") as world:
        world.draw()
        with served(world, monkeypatch, network_guard) as console:
            console.dispatched("blind-sample finish", run_id=console.run_id)
        assert world.blind_labels() == []
        record = world.service().draw_record(world.run_id)
        assert (record.state, record.labels_written, record.unmarked_count,
                record.absence_reason) == ("finished", 0, 15, "none_marked"), record


# --- TC-REVIEW-104: the draw state machine -------------------------------------------------------


def _expect_refused(world: SeededWorld, action: Any, state: str) -> None:
    from aeh.review import ReviewError

    with pytest.raises(ReviewError):
        action()
    assert world.service().draw_state(world.run_id) == state, (
        f"a refused transition moved the draw out of {state!r}")


def test_tc_review_104_a_legal_transitions(tmp_path):
    """TC-REVIEW-104 (FR-REVIEW-30, CT-REVIEW-27; RSV-08): not_drawn -> open (draw), open ->
    finished, open -> skipped, open -> closed_by_window, not_drawn -> skipped, each read back
    with `draw_state(run_id)`."""
    with seeded(tmp_path / "finish") as world:
        assert world.service().draw_state(world.run_id) == "not_drawn"
        world.draw()
        assert world.service().draw_state(world.run_id) == "open"
        world.service().finish_blind(world.run_id)
        assert world.service().draw_state(world.run_id) == "finished"
    with seeded(tmp_path / "skip-open") as world:
        world.draw()
        world.service().skip_blind_sample(world.run_id)
        assert world.service().draw_state(world.run_id) == "skipped"
    with seeded(tmp_path / "window", window_hours=24) as world:
        clock = Clock()
        world.draw(clock)
        assert world.service(clock.at(timedelta(hours=24, seconds=1))).draw_state(
            world.run_id) == "closed_by_window"
    with seeded(tmp_path / "skip-undrawn") as world:
        world.service().skip_blind_sample(world.run_id)
        assert world.service().draw_state(world.run_id) == "skipped"


def test_tc_review_104_b_illegal_transitions_are_refused_with_the_state_unchanged(tmp_path):
    """TC-REVIEW-104: finished -> open, skipped -> open, finished -> skipped and
    closed_by_window -> finished are each refused, and `draw_state(run_id)` is unchanged."""
    with seeded(tmp_path / "finished") as world:
        world.draw()
        world.service().finish_blind(world.run_id)
        _expect_refused(world, lambda: world.service().blind_sample(world.run_id, 15),
                        "finished")
        _expect_refused(world, lambda: world.service().skip_blind_sample(world.run_id),
                        "finished")
    with seeded(tmp_path / "skipped") as world:
        world.draw()
        world.service().skip_blind_sample(world.run_id)
        _expect_refused(world, lambda: world.service().blind_sample(world.run_id, 15),
                        "skipped")
    with seeded(tmp_path / "window", window_hours=24) as world:
        clock = Clock()
        world.draw(clock)
        late = clock.at(timedelta(hours=25))
        assert world.service(late).draw_state(world.run_id) == "closed_by_window"
        _expect_refused(world, lambda: world.service(late).finish_blind(world.run_id),
                        "closed_by_window")


# --- TC-REVIEW-105: the window's lapse, injected clock -------------------------------------------


def test_tc_review_105_the_window_lapse_closes_at_the_next_read_and_promotes_once(
        tmp_path, monkeypatch, network_guard):
    """TC-REVIEW-105 (FR-REVIEW-30; RSV-23, OQ-3) and TC-PIPE-40's window-lapse row. A 24 h
    window, 15 seats, 5 drafted. At +23 h 59 m the console's read finds the draw `open`, no
    label and no promote. At +24 h 1 s the next read finds `closed_by_window`, 5 blind labels,
    `unmarked_count = 10`, and `ValidationStats.promote` called exactly once; a further read
    promotes nothing more.

    The lapse is settled lazily at the next read (the OQ-3 assumption), so nothing happens
    between the two reads but the clock."""
    from aeh.console.blind_actions import settle_draw
    from aeh.stats.service import ValidationStats

    calls: list[dict] = []
    real = ValidationStats.promote

    def counting(stats, *args, **kwargs):
        calls.append(kwargs)
        return real(stats, *args, **kwargs)

    monkeypatch.setattr(ValidationStats, "promote", counting)
    clock = Clock()
    with seeded(tmp_path / "w", window_hours=24) as world:
        session = world.draw(clock)
        drafting = world.service(clock.at(timedelta(hours=1)))
        for seat in drafting.blind_seats(world.run_id)[:5]:
            drafting.draft_blind(world.run_id, seat["seat_id"], L2)
        n = len(session.items)
        with served(world, monkeypatch, network_guard) as console:
            app = console.server.app

            _service, state = settle_draw(
                app, world.run_id, world.service(clock.at(timedelta(hours=23, minutes=59))))
            assert state == "open", f"at +23 h 59 m the draw reads {state!r}"
            assert world.blind_labels() == [] and calls == []

            _service, state = settle_draw(
                app, world.run_id,
                world.service(clock.at(timedelta(hours=24, seconds=1))))
            assert state == "closed_by_window", f"at +24 h 1 s the draw reads {state!r}"
            assert len(world.blind_labels()) == 5, world.blind_labels()
            record = world.service(clock).draw_record(world.run_id)
            assert (record.labels_written, record.unmarked_count) == (5, n - 5), record
            assert len(calls) == 1, f"the lapse called promote {len(calls)} time(s), expected 1"
            assert calls[0].get("unmarked_count") == n - 5, calls[0]
            stored = console.rows("SELECT unmarked_count FROM package_validation "
                                  "WHERE cohort_id = ?", world.cohort_id, tier="durable")
            assert [row["unmarked_count"] for row in stored] == [n - 5], stored

            settle_draw(app, world.run_id, world.service(clock.at(timedelta(hours=30))))
            assert len(calls) == 1, f"a later read promoted again ({len(calls)} calls)"
            assert len(world.blind_labels()) == 5
