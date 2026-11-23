"""The browser tier's ENG7 world for Validity T12 (issue #909): the four-paper ENG7 class
graded by the console's own `start run` (`tests/support/eng7_console.py`, rung 3), opened in
the SPA.

One cell, (first student, `C3`), is routed `auto` before anything opens the draw — T8's
`_keep_one_cell` — so M-REVIEW draws exactly the other fifteen and every case has the same
undrawn positive control on every run. `Q3` holds only `C3`, so that student's Q3 is the
undrawn single-line question.

What the world knows, read from the store (never from the SPA): the drawn cells, each
cell's stored band and points, each criterion's question, the roster names and each
criterion's scale with its descriptors (from the shipped ENG7 spec).
"""

from __future__ import annotations

import tomllib
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from tests.support import spa
from tests.support.eng7_console import Eng7Console, eng7_console

VIEWPORT = {"width": 1280, "height": 720}
HELD_BACK = "Hidden until you mark your sample or skip it"
REPO = Path(__file__).resolve().parents[2]
SPEC = REPO / "docs" / "live-tests" / "config" / "eng7-read-01.package.toml"
KEPT_CRITERION = "C3"


def scales() -> dict[str, list[tuple[str, str]]]:
    """criterion -> [(band, descriptor)] worst first, from the shipped ENG7 spec."""
    spec = tomllib.loads(SPEC.read_text(encoding="utf-8"))
    return {c["id"]: [(b["name"], b["descriptor"]) for b in c["bands"]]
            for c in spec["criterion"] if c.get("bands")}


@dataclass
class Eng7Browser:
    served: Eng7Console
    kept: tuple[str, str]
    origin: str = ""
    questions: dict[str, str] = field(default_factory=dict)

    @property
    def run_id(self) -> str:
        return self.served.run_id

    def route(self, route: str) -> str:
        joiner = "&" if "?" in route else "?"
        return (f"{self.origin}/#{route}{joiner}class={self.served.cohort_id}"
                f"&run={self.run_id}")

    def open(self, page: Any, route: str) -> str:
        page.goto(self.route(route))
        return spa.wait_for_screen(page)

    def names(self) -> dict[str, str]:
        return self.served.names()

    def cells(self) -> dict[tuple[str, str], dict]:
        return self.served.judged_cells()

    def drawn(self) -> set[tuple[str, str]]:
        return self.served.drawn_cells()


@contextmanager
def eng7_browser(tmp_path: Path, monkeypatch: Any) -> Iterator[Eng7Browser]:
    """The graded ENG7 class behind a console; the draw is NOT opened here (the first
    Monitor read, `open_draw`, or a seats read opens it)."""
    with eng7_console(tmp_path / "w", tmp_path / "work", monkeypatch, None) as served:
        first = sorted(served.names())[0]
        served.execute("UPDATE criterion_score SET routing = 'auto' WHERE run_id = ? AND "
                       "submission_id = ? AND criterion_id = ?", served.run_id, first,
                       KEPT_CRITERION)
        status, screen = served.get("/api/v1/results/screen", run_id=served.run_id)
        assert status == 200, screen
        questions = {line["criterion_id"]: line["question_id"]
                     for student in screen["students"] for line in student["criteria"]}
        yield Eng7Browser(served=served, kept=(first, KEPT_CRITERION),
                          origin=f"http://127.0.0.1:{served.port}", questions=questions)


def open_draw(world: Eng7Browser) -> dict:
    """Open the draw the way the teacher does and check the fixture's shape."""
    read = world.served.open_draw()
    drawn = world.drawn()
    assert world.kept not in drawn and len(drawn) == len(world.cells()) - 1 == 15, (
        f"fixture: the draw holds {len(drawn)} cells, kept {world.kept}")
    return read


def assert_clean(page: Any, log: Any) -> None:
    assert log.foreign_requests() == [], f"requests left the origin: {log.foreign_requests()}"
    assert log.page_errors == [], f"page errors: {log.page_errors}"
    assert spa.rejections(page) == [], f"unhandled rejections: {spa.rejections(page)}"


def dialog(page: Any) -> Any:
    return page.get_by_role("dialog").first


__all__ = ["Eng7Browser", "HELD_BACK", "VIEWPORT", "assert_clean", "dialog", "eng7_browser",
           "open_draw", "scales"]
