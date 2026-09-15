"""`TS-48` (issue #129) — the console holds no state, and its control actions survive being
made twice: over a real run, with a second console standing in for the second tab.

Test plan §5.19, `TC-CONSOLE-01`, `-02`, `-38`, `-39`, Integration / rung 3.

**What these add over `CT-CONSOLE-C01`/`-C03`.** The clause cases assert idempotency through
the console's own replay seam (`perform(..., replay="back_navigation")`) on `StoreSpy`, where
the answer comes from the console's in-memory record of what it already applied. A browser
does not send that flag: a double-click is the same request twice, and back-navigation re-posts
the form to a server that — by `FR-CONSOLE-01` — remembers nothing. So here the second and
third requests are *plain* identical requests, the third through a freshly built console, and
the oracle is the store: the rows each action's effect lives in, snapshotted after the first
request and compared after every repeat.

**Diagnostics.** Red-by-defect cases collect every violated clause before failing.

**Written ahead of implementation.** The issue says `yes`; stale — `M-CONSOLE` landed (#122).
"""

from __future__ import annotations

import socket
import sqlite3
from pathlib import Path

import pytest

from aeh.console import (
    SCREENS,
    build_console,
    run_pipeline_for_test,
    serve_console,
)
from aeh.grade import GradingService
from aeh.orch import Orchestrator
from aeh.store import open_store
from tests.support.console_vocabulary import CONTROL_SURFACE_ACTIONS
from tests.support.console_world import OPEN_CRITERIA, IngestWorld, rows, seed_scored_run
from tests.support.grade_vocabulary import write_criterion_scores

pytestmark = [pytest.mark.integration]


def _fail_with(problems: list[str]) -> None:
    assert not problems, "\n\n".join(problems)


def _data_dir(root: Path, name: str) -> Path:
    data_dir = root / name
    for sub in ("packages", "cohorts", "blobs"):
        (data_dir / sub).mkdir(parents=True)
    return data_dir


#: The wall-clock and minted columns: `audit_record`'s id and timestamp (uuid, wall clock, written
#: by M-DET) and each tier's `schema_version.applied_at` (the migration's wall clock). Every other
#: column, and every other table, is a pure function of the driver's pinned inputs.
_UNPINNED_COLUMNS = {
    "audit_record": {"audit_record_id", "recorded_at"},
    "schema_version": {"applied_at"},
}


def _ledger_dump(data_dir: Path) -> dict[str, list[tuple]]:
    """Every row of every table of every tier file, sorted — the whole state a run leaves."""
    dump: dict[str, list[tuple]] = {}
    for path in sorted(data_dir.rglob("*.sqlite")):
        connection = sqlite3.connect(path)
        try:
            tables = [name for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
            for table in tables:
                cursor = connection.execute(f'SELECT * FROM "{table}"')
                columns = [column[0] for column in cursor.description]
                keep = [i for i, c in enumerate(columns)
                        if c not in _UNPINNED_COLUMNS.get(table, set())]
                dump[f"{path.relative_to(data_dir).as_posix()}:{table}"] = sorted(
                    repr(tuple(row[i] for i in keep)) for row in cursor.fetchall()
                )
        finally:
            connection.close()
    return dump


# --- TC-CONSOLE-01 — no pipeline state, no inference, and a closed browser changes nothing -------


def test_tc_console_01_a_console_open_during_the_run_and_then_closed_leaves_the_run_identical(
    tmp_path, monkeypatch
):
    """`TC-CONSOLE-01` / `FR-CONSOLE-01` — state assertion plus run completion, as a differential.

    The same pinned run is driven twice by the console's own headless driver
    (`run_pipeline_for_test`: real `M-PKG`, `M-ORCH`, `M-DET`, `M-GRADE`). In the second, a
    console is opened on its own store connection from the driver's `alongside` seam — a thread
    started just before the deterministic pass and joined before the store closes, so it runs
    concurrently with scoring (the overlap is the seam's, not guaranteed per render) — renders
    every run-scoped screen over and over, and is then closed: the browser going away mid-run.

    Oracles:

    * **run completion** — both runs finalize and deliver the same grades;
    * **no pipeline state** — every row of every tier the two runs leave is identical, so the
      console contributed nothing to the ledger and took nothing away from it;
    * **no inference** — zero calls at the provider seam, counted both on the provider handed to
      the console and on every shipped provider class (the fixture tier answers from disk, so the
      socket guard alone cannot see a dispatched request).
    """
    cohort_id, run_id = "c-ts48-01", "r-ts48-01"
    baseline_dir = _data_dir(tmp_path, "baseline")
    watched_dir = _data_dir(tmp_path, "watched")
    baseline = run_pipeline_for_test(data_dir=baseline_dir, cohort_id=cohort_id, run_id=run_id)

    class _CountingProvider:
        calls: list[object] = []

        def complete(self, *args, **kwargs):  # noqa: ANN002, ANN003
            self.calls.append(args)
            raise AssertionError("the console dispatched an inference request")

    provider = _CountingProvider()
    # The provider handed to the console is only half the seam: a console that built its own
    # provider would never touch it. So every shipped provider class's `complete` counts too (the
    # driver's pass is deterministic and dispatches nothing, so any call is the console's).
    import aeh.prov as prov

    for name in dir(prov):
        candidate = getattr(prov, name)
        if (
            isinstance(candidate, type)
            and callable(getattr(candidate, "complete", None))
            and candidate.__module__ == prov.__name__
        ):
            monkeypatch.setattr(candidate, "complete", provider.complete, raising=False)
    renders: list[str] = []

    def _browser_open_during_the_run() -> None:
        store = open_store(watched_dir)
        try:
            app = build_console(store=store, provider=provider)
            for _ in range(5):
                for route, params in (
                    (SCREENS["S7"], {"id": run_id}),
                    (SCREENS["S9"], {"id": run_id}),
                    (SCREENS["S12"], {"id": run_id}),
                    (SCREENS["S8"], {}),
                    (SCREENS["S6"], {"id": cohort_id}),
                ):
                    renders.append(app.render(route, **params).html)
        finally:
            store.close()  # the tab closes; nothing the console held survives it

    watched = run_pipeline_for_test(data_dir=watched_dir, cohort_id=cohort_id, run_id=run_id,
                                    alongside=_browser_open_during_the_run)

    assert len(renders) == 25, "the console did not render while the run was scoring"
    assert baseline.finalized and watched.finalized, (
        f"a run did not complete: baseline {baseline.stages}, watched {watched.stages}"
    )
    assert watched.grades == baseline.grades and watched.grades, (
        "the run a console watched delivered different grades from the unwatched run"
    )
    assert provider.calls == [], (
        f"the console dispatched {len(provider.calls)} inference request(s); FR-CONSOLE-01: it "
        f"performs no inference"
    )
    base_dump, watched_dump = _ledger_dump(baseline_dir), _ledger_dump(watched_dir)
    assert set(base_dump) == set(watched_dump), (
        f"the watched run's store has different tables: "
        f"{sorted(set(base_dump) ^ set(watched_dump))}"
    )
    differing = sorted(key for key in base_dump if base_dump[key] != watched_dump[key])
    assert not differing, (
        f"a console open during the run changed the ledger in {differing}. FR-CONSOLE-01: the "
        f"console holds no pipeline state and every view is a read."
    )


# --- TC-CONSOLE-02 — every control action, posted twice and re-posted: the ledger moves once -----


#: The parameters a form posts, as the union every one of §11.8's fifteen actions reads from.
def _form(world, parked: str) -> dict:
    return {
        "run_id": world.run_id,
        "cohort_id": world.cohort_id,
        "package_version": world.package_version_id,
        "submission_id": parked,
        "submission_ref": world.submissions[0],
        "criterion_id": "C-02",
        "answer_key": "D",
        "state": "paused",
        "resolution": "unresolvable",
        "review_window_hours": 48,
        "band": "incorrect",
        "actor": "teacher-a",
    }


#: The actions whose first post must really change the store — the ones the console wires to a
#: row or a landed owner on a real store. Every other action is swept too: it must not write on a
#: repeat either, which is what catches a write path added later without an idempotency guard.
_EFFECTFUL = {"pause/resume", "finalize batch", "correct an answer key after a run",
              "resolve quarantine item"}
# (`purge cohort` is wired to M-STORE but correctly refused here — the cohort was never promoted
# to Tier D, `CT-STORE-10` — so it is swept for "no write on repeat" like the unwired actions.)


def _apply_control(store, world) -> None:
    """The orchestrator's own control-read pass over the run (`CT-ORCH-13`: the console queues,
    the orchestrator applies on its schedule). Called after every post so the oracle is the
    *effect*, not the request log: M-ORCH records every pause request as a row by design, and marks
    a pause of an already-paused run applied without flipping anything."""
    orchestrator = Orchestrator(store)
    orchestrator._apply_control_rows(store.cohort(world.cohort_id), world.run_id)


def _without_request_log(dump: dict) -> dict:
    return {key: value for key, value in dump.items() if not key.endswith(":run_control")}


@pytest.mark.parametrize("action", sorted(CONTROL_SURFACE_ACTIONS))
def test_tc_console_02_an_action_posted_twice_and_re_posted_changes_the_ledger_once(
    tmp_data_dir, action
):
    """`TC-CONSOLE-02` / `FR-CONSOLE-02` — per action, the ledger invariant.

    One store carries a started run (so a pause has something to pause) and a parked submission
    ingested for real (so a quarantine close has something to close). The action is posted once,
    then again identically on the same console (a double-click), then re-posted through a fresh
    console (back-navigation: the browser replays the form to a server that holds nothing). The
    oracle is the **whole store**: every row of every tier (`_ledger_dump`, minted ids and wall
    clocks excluded), snapshotted after the first post and compared after each repeat.

    The console's own `replay="back_navigation"` route is not a leg here: it answers from the
    instance's memory before touching the store, so it cannot fail; `CT-CONSOLE-C03` covers it.

    `run_control` is a request log, not an effect — `M-ORCH`'s own `pause()` writes a row per call
    and applies a repeat as a no-op — so it is excluded from the dump, and pause/resume's effect is
    asserted directly: after the orchestrator's control pass the run is paused, stays paused, and no
    unapplied request is left that could flip it later.
    """
    store = open_store(tmp_data_dir)
    try:
        world = seed_scored_run(store, choices=[("A", "B", "C"), ("A", "D", "C")], submissions=2)
        Orchestrator(store).start(world.run_id)
        ingest = IngestWorld(store, "c-ts48-02q", "pkg-ts48-02q")
        parked = ingest.submit_mismatch("parked").submission_id
        params = _form(world, parked)
        if action == "purge cohort":
            params["cohort_id"] = ingest.cohort_id

        first = build_console(store=store)
        outcome = first.perform(action, **params)
        if action in _EFFECTFUL:
            assert outcome.dispatched, (
                f"fixture: the first post of {action!r} changed nothing: {outcome.detail}"
            )
        _apply_control(store, world)
        settled = _without_request_log(_ledger_dump(tmp_data_dir))

        problems: list[str] = []
        for label, post in (
            ("a second identical post (double-click)", lambda: first.perform(action, **params)),
            ("a re-post through a fresh console (back-navigation)",
             lambda: build_console(store=store).perform(action, **params)),
        ):
            post()
            _apply_control(store, world)
            now = _without_request_log(_ledger_dump(tmp_data_dir))
            changed = sorted(
                f"{key} ({len(settled.get(key, []))} -> {len(now.get(key, []))} rows)"
                for key in set(settled) | set(now) if settled.get(key) != now.get(key)
            )
            if changed:
                problems.append(
                    f"{label} of {action!r} changed {changed}. FR-CONSOLE-02: every action is "
                    f"idempotent — a browser repeats a request without any replay flag, so "
                    f"idempotency the server does not enforce against the store is idempotency a "
                    f"double-click defeats."
                )
                settled = now

        if action == "pause/resume":
            cohort = store.cohort(world.cohort_id)
            status = rows(cohort, "SELECT status FROM run WHERE run_id = :r", r=world.run_id)
            unapplied = rows(cohort, "SELECT action FROM run_control WHERE run_id = :r "
                                     "AND applied_at IS NULL", r=world.run_id)
            if status != [{"status": "paused"}] or unapplied:
                problems.append(
                    f"after pausing three times the run reads {status!r} with unapplied requests "
                    f"{unapplied!r}; expected one paused run and nothing left queued"
                )
        _fail_with(problems)
    finally:
        store.close()


# --- TC-CONSOLE-38 — two tabs show one truth; a LAN device cannot connect --------------------------


def _local_non_loopback_ipv4() -> list[str]:
    addresses = set()
    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        address = info[4][0]
        if not address.startswith("127."):
            addresses.add(address)
    return sorted(addresses)


def test_tc_console_38_two_tabs_show_the_same_truth_and_the_lan_cannot_connect(
    tmp_data_dir, network_guard
):
    """`TC-CONSOLE-38` / `FR-CONSOLE-01` — differential plus connection refusal.

    **Two tabs**: two consoles over one store render every run-scoped screen identically; tab A
    then corrects an answer key and tab B — which did nothing — renders the rollup exactly as a
    third, freshly opened console does, and differently from before. A tab that cached the run
    would pass the first comparison and fail the second.

    **A LAN device**: the console is served for real (`serve_console`) and a connection is
    attempted to its port on each of this machine's non-loopback IPv4 addresses — the address a
    second device on the LAN would use. Every attempt must be refused, while the same port on
    loopback accepts (so the refusal is about the bind, not a dead port). The autouse socket guard
    blocks even loopback by design; it is stood down only around these connects and reinstalled.
    """
    store = open_store(tmp_data_dir)
    server = None
    try:
        world = seed_scored_run(store, choices=[("A", "B", "C"), ("A", "D", "C")], submissions=2)
        tab_a, tab_b = build_console(store=store), build_console(store=store)
        screens = ((SCREENS["S7"], {"id": world.run_id}), (SCREENS["S9"], {"id": world.run_id}),
                   (SCREENS["S12"], {"id": world.run_id}), (SCREENS["S8"], {}),
                   (SCREENS["S6"], {"id": world.cohort_id}))
        for route, params in screens:
            assert tab_a.render(route, **params).html == tab_b.render(route, **params).html, (
                f"two consoles over one store render {route} differently"
            )
        before = tab_b.render(SCREENS["S12"], id=world.run_id).html
        outcome = tab_a.perform("correct an answer key after a run", run_id=world.run_id,
                                criterion_id="C-02", answer_key="D")
        assert outcome.dispatched, outcome.detail
        after_b = tab_b.render(SCREENS["S12"], id=world.run_id).html
        fresh = build_console(store=store).render(SCREENS["S12"], id=world.run_id).html
        assert after_b != before and after_b == fresh, (
            "tab B's rollup after tab A's correction does not match a freshly opened console's — "
            "a tab is holding state (FR-CONSOLE-01: both tabs show the same truth because neither "
            "holds any)"
        )

        # Resolved before the guard stands down, so name resolution cannot emit traffic unguarded.
        network_guard.uninstall()
        try:
            lan_addresses = _local_non_loopback_ipv4()
        finally:
            network_guard.install()
        if not lan_addresses:
            pytest.skip("no non-loopback IPv4 interface on this machine: the LAN half of "
                        "TC-CONSOLE-38 needs one to stand in for a second device")
        server = serve_console(store=store, run_id=world.run_id)
        _host, port = server.socket.getsockname()[:2]
        network_guard.uninstall()
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5):
                pass  # the positive control: the port is live on loopback
            reached = []
            for address in lan_addresses:
                probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                probe.settimeout(3)
                try:
                    if probe.connect_ex((address, port)) == 0:
                        reached.append(address)
                finally:
                    probe.close()
        finally:
            network_guard.install()
        assert not reached, (
            f"a device on the LAN reached the console at {reached} port {port}. FR-CONSOLE-05 / "
            f"RISK-20: an unauthenticated student-record system is loopback-only."
        )
    finally:
        if server is not None:
            server.terminate()
        store.close()


# --- TC-CONSOLE-39 — stale state: idempotent or refused with a refresh, never partial --------------


def test_tc_console_39_stale_actions_are_idempotent_or_refused_and_never_partially_applied(
    tmp_data_dir,
):
    """`TC-CONSOLE-39` / `FR-CONSOLE-02`, negative — the two stale states the case names.

    1. **Finalizing an already-finalized run.** `M-GRADE` finalized the batch; the console is
       asked to finalize it again. Every grade row — revision, state, total, `finalized_at` — must
       be exactly as delivered (idempotent), or the action refused.
    2. **Reviewing a superseded item.** A judged C-10 item is queued for review and rendered; the
       escalation then re-scores that very item (a wider panel, a different band) before the
       teacher's review of the old view is posted.
       A review action posted against the superseded view must either be refused with
       `refresh_required`, or apply idempotently to the current state — and in either case the
       ledger must not be partially changed: no label, no score, no grade row moves unless the
       whole review lands.
    """
    store = open_store(tmp_data_dir)
    try:
        world = seed_scored_run(store, choices=[("A", "B", "C"), ("A", "D", "C")], submissions=2,
                                with_open_criteria=True)
        cohort = store.cohort(world.cohort_id)
        # The judged criteria settle as panel outputs (the disclosed M-AGG stand-in), so every
        # grade is complete and M-GRADE's finalize really delivers the batch.
        write_criterion_scores(cohort, [(s, c, "B2", 2.0, "auto") for s in world.submissions
                                        for c, _ in OPEN_CRITERIA])
        GradingService(store).compute_all(world.run_id)
        GradingService(store).finalize_batch(world.run_id, "teacher-a")
        grades = "SELECT * FROM submission_grade ORDER BY submission_id, revision"
        delivered = rows(cohort, grades)
        assert delivered and all(r["finalized_at"] for r in delivered if r["is_current"]), (
            f"fixture: M-GRADE must deliver the batch before it can be re-finalized: {delivered!r}"
        )

        problems: list[str] = []
        again = build_console(store=store).perform("finalize batch", run_id=world.run_id,
                                                    actor="teacher-b")
        if rows(cohort, grades) != delivered and not again.refused:
            problems.append(
                "finalizing an already-finalized run changed the delivered grade rows without "
                "being refused — FR-CONSOLE-02: idempotent or refused, never a second delivery"
            )

        target = world.submissions[0]
        with cohort.transaction() as tx:
            tx.execute(
                "INSERT OR REPLACE INTO criterion_score (run_id, submission_id, criterion_id, band, points, "
                "judge_count, routing, state) VALUES (COALESCE((SELECT run_id FROM run ORDER BY COALESCE(started_at, '') DESC, run_id DESC LIMIT 1), 'run-fixture'), :s, 'C-10', 'B2', 2.0, 3, 'queued', "
                "'provisional_unreviewed')", s=target)
        stale_view = build_console(store=store)
        stale_view.render(SCREENS["S9"], id=world.run_id)
        # The item the teacher is looking at is superseded under them: the escalation's widened
        # panel re-scores C-10 (judge_count 3 -> 5, band B2 -> B3) — the score-version change
        # M-REVIEW's StaleReviewItemError keys on. (Disclosed M-AGG stand-in, as above.)
        with cohort.transaction() as tx:
            tx.execute(
                "UPDATE criterion_score SET band = 'B3', points = 3.0, judge_count = 5 "
                "WHERE submission_id = :s AND criterion_id = 'C-10'", s=target)
        before_review = {
            "grades": rows(cohort, grades),
            "scores": rows(cohort, "SELECT * FROM criterion_score ORDER BY 1, 2"),
            "labels": rows(store.durable(), "SELECT * FROM label ORDER BY 1"),
        }
        review = stale_view.perform("review action", run_id=world.run_id, submission_id=target,
                                    criterion_id="C-10", band="B3", revision=1)
        after_review = {
            "grades": rows(cohort, grades),
            "scores": rows(cohort, "SELECT * FROM criterion_score ORDER BY 1, 2"),
            "labels": rows(store.durable(), "SELECT * FROM label ORDER BY 1"),
        }
        moved = sorted(key for key in before_review if before_review[key] != after_review[key])
        applied = bool(review.dispatched)
        if moved and not applied:
            problems.append(f"the stale review moved {moved} while reporting it was not applied — "
                            f"a partial application")
        if not review.refresh_required and not applied:
            problems.append(
                f"a review action against a superseded item was neither refused with a refresh "
                f"nor applied: {review!r}. On a real store the console's review action reaches no "
                f"module at all (dispatched=False, 'the owning module performs this write when "
                f"its story lands') — M-REVIEW's StaleReviewItemError, the shipped stale-item "
                f"refusal, is never consulted, so the teacher's review is silently dropped. "
                f"FR-CONSOLE-02: idempotent or refused with a refresh."
            )
        _fail_with(problems)
    finally:
        store.close()
