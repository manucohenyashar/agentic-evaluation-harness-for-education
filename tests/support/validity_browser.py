"""The browser tier's view of the validity seed (Validity T12, issue #909): a `ValidityStore`
(`tests/support/validity_seed.py`) behind a real loopback `serve_console()`, plus the two
things the SPA cases need that the API-tier seed leaves out.

* **Roster names.** The seed's students carry no roster row, so every read names them by
  their ref. FR-UI-38's differences sentence names students by name, so `name_students`
  writes one roster row per submission with a real-length synthetic name from
  `tests/support/roster.py` (no real student data).
* **One served console** over the store, with the browser's own checks: no foreign
  request, no page error, no unhandled rejection (`assert_clean`).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from tests.support import spa
from tests.support.roster import build_roster

VIEWPORT = {"width": 1280, "height": 720}


def name_students(world: Any, administration: Any, offset: int = 0) -> dict[str, str]:
    """Give each of the administration's students a roster name; submission -> name."""
    roster = build_roster(size=offset + len(administration.run.submissions) + 1)
    names: dict[str, str] = {}
    cohort = world.store.cohort(administration.cohort_id)
    rows = cohort.query("SELECT submission_id, student_ref FROM submission")
    refs = {str(row["submission_id"]): str(row["student_ref"]) for row in rows}
    with cohort.transaction() as tx:
        for index, submission in enumerate(administration.run.submissions):
            name = roster[offset + index].full_name
            tx.execute("INSERT OR REPLACE INTO roster (cohort_id, student_ref, full_name) "
                       "VALUES (:c, :r, :n)", c=administration.cohort_id,
                       r=refs[submission], n=name)
            names[submission] = name
    return names


@contextmanager
def served(world: Any, monkeypatch: Any) -> Iterator[str]:
    """A console over the validity store; yields its origin."""
    from aeh.console import serve_console

    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    server = serve_console(store=world.store)
    try:
        yield f"http://127.0.0.1:{server.socket.getsockname()[1]}"
    finally:
        server.terminate()


def open_screen(page: Any, origin: str, route: str, administration: Any) -> str:
    """Load one SPA route with the administration's class and run selected."""
    joiner = "&" if "?" in route else "?"
    page.goto(f"{origin}/#{route}{joiner}class={administration.cohort_id}"
              f"&run={administration.run_id}")
    return spa.wait_for_screen(page)


def assert_clean(page: Any, log: Any) -> None:
    """The browser's own oracle for every case: nothing left the origin, nothing threw."""
    assert log.foreign_requests() == [], f"requests left the origin: {log.foreign_requests()}"
    assert log.page_errors == [], f"page errors: {log.page_errors}"
    assert spa.rejections(page) == [], f"unhandled rejections: {spa.rejections(page)}"


__all__ = ["VIEWPORT", "assert_clean", "name_students", "open_screen", "served"]
