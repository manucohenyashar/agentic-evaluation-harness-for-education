#!/usr/bin/env python3
"""Print every student's mark per rubric line after a run, and check the evidence-sum lines.

    python docs/live-tests/sample-materials/show_criterion_marks.py --data-dir <folder> --cohort <id> --run <run id>

`aeh results show` prints each student's total and grade; this prints the line-by-line view
behind them, the one the grade is computed from (FR-GRADE-22):

* a `bands`, `general` or multiple-choice line shows the band awarded and its points;
* an evidence checklist (`evidence_sum`, the English test's C1) shows ONE line, the sum of its
  items' points, with each item (C1a, C1b) and the band awarded to it beneath. While any item
  is still unscored the sum is shown as `unscored`: the system never presents a partial sum.

It then checks what the live-test guide says can be checked to the mark: every checklist line
equals the sum of its items' points. It exits 1 if one does not, 0 otherwise.

It only reads. It sends nothing anywhere and changes nothing in the data folder. Run it with
the console stopped, from the project folder, with the Python environment active.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

import aeh.agg  # noqa: F401,E402  — all eleven modules that own a migration, before the first open
import aeh.det  # noqa: F401,E402
import aeh.extract  # noqa: F401,E402
import aeh.grade  # noqa: F401,E402
import aeh.ingest  # noqa: F401,E402
import aeh.integ  # noqa: F401,E402
import aeh.judge  # noqa: F401,E402
import aeh.orch  # noqa: F401,E402
import aeh.pkg  # noqa: F401,E402
import aeh.review  # noqa: F401,E402
import aeh.synth  # noqa: F401,E402

from aeh.grade import GRADE_STATEMENTS, open_grade  # noqa: E402
from aeh.grade.results import run_grade_records  # noqa: E402
from aeh.store import open_store  # noqa: E402

#: A score row in triage counts toward no grade (the same rule the grade computation applies).
TRIAGE = "triage"


def _points(value: float | None) -> str:
    return "unscored" if value is None else f"{value:g}"


def student_lines(store, cohort: str, run_id: str, submission_id: str) -> tuple[list[str], list[str]]:
    """The printed lines for one student, and any checklist line that is not its items' sum."""
    service = open_grade(store)
    scores = {row["criterion_id"]: dict(row) for row in store.cohort(cohort).query(
        GRADE_STATEMENTS["select_submission_scores"], run_id=run_id, submission_id=submission_id)}

    def awarded(criterion_id: str) -> float | None:
        row = scores.get(criterion_id)
        if row is None or row["points"] is None or row["routing"] == TRIAGE:
            return None
        return float(row["points"])

    def band(criterion_id: str) -> str:
        row = scores.get(criterion_id)
        return f"{row['band']} ({row['state']})" if row and row["band"] else "no score"

    printed, problems = [], []
    for line in service.criterion_lines(run_id, submission_id):
        out_of = _points(line.max_points)
        if not line.aspects:
            printed.append(f"    {line.criterion_id:<10} {_points(line.awarded):>8} / {out_of:<4} "
                           f"{band(line.criterion_id)}")
            continue
        printed.append(f"    {line.criterion_id:<10} {_points(line.awarded):>8} / {out_of:<4} "
                       f"evidence sum of {' + '.join(line.aspects)}")
        items = [awarded(aspect) for aspect in line.aspects]
        for aspect, points in zip(line.aspects, items):
            printed.append(f"      {aspect:<10} {_points(points):>6}        {band(aspect)}")
        expected = math.fsum(items) if all(p is not None for p in items) else None
        if line.awarded != expected:
            problems.append(f"{submission_id} {line.criterion_id}: shown "
                            f"{_points(line.awarded)}, its items add up to {_points(expected)}")
    return printed, problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--cohort", required=True)
    parser.add_argument("--run", required=True)
    args = parser.parse_args(argv)
    if not args.data_dir.expanduser().is_dir():
        print(f"no data folder at {args.data_dir}")
        return 2

    store = open_store(args.data_dir.expanduser())
    problems: list[str] = []
    try:
        students = {row["submission_id"]: row["student_ref"] for row in store.cohort(
            args.cohort).query("SELECT submission_id, student_ref FROM submission")}
        records = run_grade_records(store, args.run)
        if not records:
            print(f"run {args.run} has no grades yet: let it finish (aeh run), then try again.")
            return 2
        for record in records:
            sid = record["submission_id"]
            print(f"{students.get(sid, '?')}  ({sid})   total {_points(record['total'])}   "
                  f"grade {record['grade'] or '-'}   state {record['state']}")
            printed, found = student_lines(store, args.cohort, args.run, sid)
            print("\n".join(printed))
            problems += found
    finally:
        store.close()

    print()
    if problems:
        print("MISMATCH: an evidence-sum line is not the sum of its items:")
        for problem in problems:
            print("  -", problem)
        return 1
    print("OK: every evidence-sum line equals the sum of its items' points (or waits, unscored, "
          "for an item still to be scored).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
