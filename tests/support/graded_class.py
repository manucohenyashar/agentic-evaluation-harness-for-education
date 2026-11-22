"""A graded class at each point of its blind sample, for the purge cases (Validity T7, #900):
TC-STORE-31, TC-REVIEW-108's purge arm, and TC-REG-27.

Built on `tests/support/validity_seed.py`'s `ValidityStore`: the run, package and scored cells
are the shipped modules plus that file's disclosed M-AGG stand-in; the draw, drafts, Finish and
Skip go through M-REVIEW's store-backed service; promotion is M-PIPE's `promote_administration`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from tests.support.validity_seed import ATOMIC, Administration, ValidityStore, teacher_bands

#: Fifteen papers on the atomic line, the smallest whole draw (FR-REVIEW-12's 15-25 range);
#: the teacher disagrees on one.
PAPERS = 15
SYSTEM = {ATOMIC: ("fail", "pass") * 7 + ("pass",)}
TEACHER = {ATOMIC: ("fail", "pass") * 7 + ("fail",)}

#: The class's cohort tables the purge must empty, the draw's three among them.
SWEPT = ("blind_draft", "blind_draw_seat", "blind_draw", "criterion_score", "run",
         "submission", "cohort")


def graded_class(root: Path, cohort_id: str, *,
                 drafted: int = PAPERS) -> tuple[ValidityStore, Administration]:
    """A scored class whose blind draw is open with `drafted` of its fifteen seats drafted."""
    world = ValidityStore(root)
    administration = world.administer(cohort_id, SYSTEM)
    seats = world.draw(administration, PAPERS)
    assert len(seats) == PAPERS, f"fixture: drew {len(seats)} seats, not {PAPERS}"
    marked = world.mark(administration, seats[:drafted], teacher_bands(administration, TEACHER))
    assert marked == drafted, f"fixture: drafted {marked} of {drafted}"
    return world, administration


def cohort_file(world: ValidityStore, cohort_id: str) -> Path:
    return world.root / "cohorts" / f"{cohort_id}.sqlite"


def cohort_counts(world: ValidityStore, cohort_id: str) -> dict[str, int]:
    """Row count per swept table, read from the file as it stands."""
    with sqlite3.connect(cohort_file(world, cohort_id)) as connection:
        return {table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in SWEPT}


def run_status(world: ValidityStore, administration: Administration) -> str:
    with sqlite3.connect(cohort_file(world, administration.cohort_id)) as connection:
        return str(connection.execute("SELECT status FROM run WHERE run_id = ?",
                                      (administration.run_id,)).fetchone()[0])


def durable_count(world: ValidityStore, table: str, cohort_id: str) -> int:
    return int(world.durable_rows(f"SELECT COUNT(*) AS n FROM {table} WHERE cohort_id = ?",
                                  cohort_id)[0]["n"])


def purge(world: ValidityStore, cohort_id: str) -> Any:
    return world.store.purge_cohort(cohort_id)


__all__ = [
    "PAPERS",
    "SWEPT",
    "SYSTEM",
    "TEACHER",
    "cohort_counts",
    "cohort_file",
    "durable_count",
    "graded_class",
    "purge",
    "run_status",
]
