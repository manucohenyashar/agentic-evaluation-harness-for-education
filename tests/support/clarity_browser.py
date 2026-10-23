"""The served ENG7 clarity world, shared by the browser tiers that drive it
(the TC-UI-24..27 censuses, the TC-UI-31..34 results/clock/ai-calls tests).

`serve_eng7_world` is the census's own `_serve_world`, extracted so the suites that
drive the same world share one shape: the ENG7 Jev-final seed (published test, graded
run, roster) and the recorded AF-09 draft (a review screen whose gaps include the
whole-number passing-score question) on one store behind one loopback console.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tests.support import clarity_world, console_redesign_world as crw


def ensure_draft_ledger(store: Any, package_id: str) -> None:
    """The package row a draft-only world lacks: the draft job writes only the draft
    TOML, and the context read needs the row (the screens suite's `_ensure_ledger`)."""
    from tests.support.clarity_world import STAMP

    with store.package(package_id).transaction() as tx:
        tx.execute("INSERT OR IGNORE INTO package (package_id, created_at) VALUES (:p, :t)",
                   p=package_id, t=STAMP)


@contextmanager
def serve_eng7_world(root: Path, network_guard: Any, monkeypatch: Any,
                     *, draft_job: bool = True, compute: bool = False,
                     ) -> Iterator[dict[str, Any]]:
    """One served world: the ENG7 Jev-final seed (published test, graded run, roster)
    and — when `draft_job` — the recorded AF-09 draft (a review screen whose gaps
    include the whole-number passing-score question), on one store behind one loopback
    console. The draft job runs against the live console over the recorded corpus; the
    environment is set the way `served_authoring` sets it and undone on the way out.
    `compute` runs M-GRADE's own pass over the seeded cells after the seed (the
    TC-CONSOLE-97 seed's rule: no `submission_grade` row, no student in the read)."""
    from aeh.console import serve_console
    from aeh.store import open_store

    store = open_store(root / "data")
    world = clarity_world.seed_jev_final_world(store)
    if compute:
        from aeh.grade import open_grade

        open_grade(store).compute_all(world.synthetic.run_id)
        open_grade(store).compute_all(world.real.run_id)
    if monkeypatch is not None:
        for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("HARNESS_PROFILE", "dev-ci")
        monkeypatch.setenv("HARNESS_FIXTURE_DIR", str(crw.RECORDINGS))
    else:
        from tests.support.env_hygiene import set_world_env

        set_world_env("HARNESS_PROFILE", "dev-ci")
        set_world_env("HARNESS_FIXTURE_DIR", str(crw.RECORDINGS))
    if network_guard is not None:
        network_guard.uninstall()
    try:
        server = serve_console(store=store, run_id=world.synthetic.run_id,
                               cfg=crw.recorded_authoring_config())
    except BaseException:
        if network_guard is not None:
            network_guard.install()
        store.close()
        raise
    host, port = server.socket.getsockname()[:2]
    origin = f"http://{host}:{port}"
    draft: dict[str, Any] | None = None
    if draft_job:
        # The AF-09 draft: a real draft through the console's own authoring job,
        # replaying the recorded model calls (zero egress — the request log asserts it
        # per case).
        _answer, record = crw.run_draft_job(port, "AF-09")
        assert record["state"] == "succeeded", \
            f"the AF-09 draft job ended {record['state']}"
        draft = crw.draft_read(port)["draft"]
        assert draft is not None and draft["missing_pieces"] > 0, (
            "fixture: the AF-09 draft carries no missing pieces to ask about")
        ensure_draft_ledger(store, draft["package_id"])
    try:
        yield {"origin": origin, "port": port, "store": store, "world": world,
               "draft": draft}
    finally:
        from tests.support.env_hygiene import restore_world_env

        server.terminate()
        restore_world_env()
        if network_guard is not None:
            network_guard.install()
        from tests.support.console_redesign_world import _close_console_store

        _close_console_store(store)
