"""Worlds for Validity T18 (issue #903): the console's r2 reads and actions (TC-CONSOLE-117…122,
124, TC-REG-28).

Two worlds, both behind a real `serve_console()` on a loopback port (rung 3):

* **ENG7** (`tests/support/eng7_console.py`): four papers graded by the console's own
  `start run`, every judged cell `provisional`. It carries what the review queue's per-item
  arms need (roster names, grader verdicts, feedback narratives, the package's levels) and a
  boundary table (`pass = 6`, `"not yet" = 0`). `shape_queue` turns its four identical
  4-member groups into the plan's shape: ONE group (the C1a cells, which stay identical) and
  single items, with distinct rank scores, by writing the stored columns M-REVIEW reads.
* **The validity store** (`tests/support/validity_seed.py`): `seed_scored_run`'s synthetic
  class, which ENG7 cannot stand in for in three places: it holds deterministic (MCQ) lines,
  it can be as large as the whole-grade range needs (12+ papers), and its package declares no
  boundary table (the no-boundary twin). `served_validity` serves a console over it.

Everything written here is a stored row the shipped readers read; no reader is patched.
"""

from __future__ import annotations

import tomllib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from tests.support.eng7_console import Eng7Console
from tests.support.label_identity_world import ServedRun

REPO = Path(__file__).resolve().parents[2]
ENG7_SPEC = REPO / "docs" / "live-tests" / "config" / "eng7-read-01.package.toml"

#: The criterion whose cells stay one group (the stand-in judge marks every C1a "absent").
GROUP_CRITERION = "C1a"

#: Each submission's (spans_verified, ocr_overlap_risk) on C1b: four distinct signatures, so
#: the four C1b cells are four single items (CT-REVIEW-20's signature includes both).
_C1B_SIGNATURES = ((0, 0), (0, 1), (1, 0), (1, 1))


def eng7_boundaries() -> list[tuple[str, float]]:
    """The ENG7 spec's `[grades]` table, as (letter, lowest total), highest first."""
    spec = tomllib.loads(ENG7_SPEC.read_text(encoding="utf-8"))
    return sorted(((str(k), float(v)) for k, v in spec["grades"].items()),
                  key=lambda pair: -pair[1])


def eng7_levels() -> dict[str, list[str]]:
    """criterion -> its band names in declared order, from the shipped ENG7 spec."""
    spec = tomllib.loads(ENG7_SPEC.read_text(encoding="utf-8"))
    return {c["id"]: [b["name"] for b in c["bands"]] for c in spec["criterion"]
            if c.get("bands")}


def letter_for(score: float | None) -> str | None:
    """The grade a total earns under the ENG7 table, worked here (not through M-PKG)."""
    if score is None:
        return None
    for letter, lowest in eng7_boundaries():
        if float(score) >= lowest:
            return letter
    return None


def shape_queue(served: Eng7Console) -> dict[str, Any]:
    """Make ENG7's queue the plan's shape: the four C1a cells one group; every C1b, C2 and C3
    cell a single item (C1b by its integrity signature, C2 and C3 by a distinct proposed band
    each); every cell a distinct panel spread, so the rank scores differ and the service's
    order is not the submission order. Returns what was written."""
    levels = eng7_levels()
    submissions = sorted(served.names())
    spreads: dict[tuple[str, str], int] = {}
    position = 0
    for index, submission in enumerate(submissions):
        spans, ocr = _C1B_SIGNATURES[index]
        served.execute("UPDATE criterion_score SET spans_verified = ?, ocr_overlap_risk = ? "
                       "WHERE run_id = ? AND submission_id = ? AND criterion_id = 'C1b'",
                       spans, ocr, served.run_id, submission)
        for criterion in ("C2", "C3"):
            served.execute("UPDATE criterion_score SET band = ? WHERE run_id = ? AND "
                           "submission_id = ? AND criterion_id = ?",
                           levels[criterion][index], served.run_id, submission, criterion)
    # Distinct spreads, assigned against the submission order (the last paper the widest), so
    # the expected-value order and the submission-id order disagree.
    for criterion in ("C1a", "C1b", "C2", "C3"):
        for submission in reversed(submissions):
            position += 1
            spreads[(submission, criterion)] = position % 3 + (position // 7)
            served.execute("UPDATE criterion_score SET band_spread = ? WHERE run_id = ? AND "
                           "submission_id = ? AND criterion_id = ?",
                           spreads[(submission, criterion)], served.run_id, submission,
                           criterion)
    return {"spreads": spreads}


@contextmanager
def served_validity(world: Any, administration: Any, monkeypatch: Any,
                    network_guard: Any) -> Iterator[ServedRun]:
    """A console over a `ValidityStore`, as a `ServedRun` for `administration`."""
    from aeh.console import serve_console

    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    if network_guard is not None:
        network_guard.uninstall()
    server = None
    try:
        server = serve_console(store=world.store)
        yield ServedRun(world=administration, server=server,
                        port=server.socket.getsockname()[1], root=world.root)
    finally:
        try:
            if server is not None:
                server.terminate()
        finally:
            if network_guard is not None:
                network_guard.install()


def name_all(world: Any, administration: Any, offset: int = 0) -> dict[str, str]:
    """Roster names for the administration's students (`validity_browser.name_students`)."""
    from tests.support.validity_browser import name_students

    return name_students(world, administration, offset=offset)


__all__ = ["ENG7_SPEC", "GROUP_CRITERION", "eng7_boundaries", "eng7_levels", "letter_for",
           "name_all", "served_validity", "shape_queue"]
