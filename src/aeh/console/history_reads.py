"""Past tests (FR-CONSOLE-70): every grading run the store holds, findable long after the day.

A teacher is asked about a test weeks later — "what did Dana get on the March quiz, and why?" —
and before this read the console offered a run switcher labelled *Grading run 1, 2, 3* with no
class, test or date, so the answer meant guessing runs one by one. This read lists every run,
newest first, with its class, the test version it graded against, when it started and finished,
its state, and each graded student's name, total and state; the screen filters it by class, test
or student name and opens a run's results or a student's detail from it.

A read, never a write (`ADR-45`): it reads each class's run rows and M-GRADE's own per-student
records (`run_grade_records`, the door the results screen and the exports read) beside the
class list's names. A run whose grades cannot be read is listed without its students and counted, not a 500.
"""

from __future__ import annotations

from typing import Any

from aeh.grade import run_grade_records

from . import queries as Q


def _names(app: Any, cohort_id: str) -> dict[str, str | None]:
    try:
        return {str(row["student_ref"]): (str(row["full_name"] or "") or None)
                for row in app._store.cohort(cohort_id).query(
                    "SELECT student_ref, full_name FROM roster")}
    except Exception:  # noqa: BLE001 — names are a convenience beside the refs
        return {}


def _refs(app: Any, cohort_id: str) -> dict[str, str]:
    try:
        return {str(row["submission_id"]): str(row["student_ref"])
                for row in app._store.cohort(cohort_id).query(
                    "SELECT submission_id, student_ref FROM submission")}
    except Exception:  # noqa: BLE001 — a ledger without papers lists no students
        return {}


def past_tests_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """Every grading run, newest first, each with its class, test version, dates, state and
    graded students (name, ref, total, state). `cohort_id` narrows to one class."""
    del console
    if getattr(app._store, "data_dir", None) is None:
        return {"runs": [], "unreadable_runs": 0}
    wanted = str(query.get("cohort_id") or "")
    rows = [dict(row) for row in app._read_cohort_files(Q._SELECT_RUNS_ALL, [])]
    runs: list[dict[str, Any]] = []
    names_by_class: dict[str, dict[str, str | None]] = {}
    refs_by_class: dict[str, dict[str, str]] = {}
    skipped = 0
    for row in rows:
        cohort_id = str(row["cohort_id"])
        if wanted and cohort_id != wanted:
            continue
        run_id = str(row["run_id"])
        if cohort_id not in names_by_class:
            names_by_class[cohort_id] = _names(app, cohort_id)
            refs_by_class[cohort_id] = _refs(app, cohort_id)
        names, refs = names_by_class[cohort_id], refs_by_class[cohort_id]
        try:
            records = run_grade_records(app._store, run_id)
        except Exception:  # noqa: BLE001 — the run is listed; its grades could not be read
            records = []
            skipped += 1
        students = []
        for record in records:
            ref = refs.get(str(record["submission_id"]))
            students.append({
                "submission_id": str(record["submission_id"]),
                "student_ref": ref,
                "full_name": names.get(ref) if ref is not None else None,
                "total": record["total"],
                "state": str(record["state"] or ""),
            })
        students.sort(key=lambda s: ((s["full_name"] or s["student_ref"] or "").casefold()))
        runs.append({
            "run_id": run_id,
            "cohort_id": cohort_id,
            "package_id": str(row["package_id"]),
            "package_version_id": str(row["package_version_id"]),
            "status": str(row["status"]),
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "students": students,
        })
    runs.sort(key=lambda r: (str(r["started_at"] or ""), r["run_id"]), reverse=True)
    return {"runs": runs, "unreadable_runs": skipped}


__all__ = ["past_tests_read"]
