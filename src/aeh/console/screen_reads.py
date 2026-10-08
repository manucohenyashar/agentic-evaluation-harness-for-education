"""The lifecycle screens' reads (M-UI, #635): the JSON documents the SPA's screens render,
read live from the store through the modules that own each table.

Every reader here is a read: it opens only tier files that exist (the never-create rule),
writes nothing, and answers a document the SPA can render as is. The readers reach the same
doors the server-rendered console and the CLI call — `SetupService.steps()` for the package
screen's gates, `progress` for the monitor, `review_queue` for the review screen,
`run_grade_records` for the results — so the two transports are one implementation, not two
suites of rules.

Key naming is deliberate: the SPA's blind-sample arm (ADV-15) scans every API body the
browser received for system-output keys, so no payload here names a value `band`,
`confidence` or `scoring_engine` — a results row's per-criterion band is `criterion_band`,
and the rubric's band scale is answered as a list of names, never as objects carrying a
`band` key.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from aeh.grade import GRADE_STATEMENTS, run_grade_records
from aeh.setup import setup_service_for_store


def _data_dir(app: Any) -> Path:
    data_dir = getattr(app._store, "data_dir", None)
    if data_dir is None:
        raise ValueError("no store is attached; there is nothing to read")
    return Path(data_dir)


def _bound_run_id(console: Any) -> str:
    """The run the console serves — `serve_console` was started with it; empty when it was
    not (a console without a run has no run-bound screen to answer)."""
    return str(getattr(console, "run_id", None) or "")


def _run_row_of(console: Any, app: Any, query: Any) -> Any:
    """The run row the read is about: the query's `run_id`, else the console's bound run.
    `None` answers an unknown or absent run — the screen renders its no-run state, and no
    tier file is created by the look."""
    run_id = str(query.get("run_id") or "") or _bound_run_id(console)
    if not run_id:
        return None
    try:
        return app._run_row(run_id)
    except Exception:  # noqa: BLE001 — an unreadable ledger is a no-run state, not a 500
        return None


def _draft_package(app: Any, data_dir: Path) -> tuple[str, Any] | None:
    """The stored package whose setup still holds a draft, as `(package_id, service)`.

    The first sorted package file is the one `blocking_screens` reads, so the SPA and the
    server-rendered screens cannot disagree about which draft setup works on. A package
    whose setup has finished (no draft left) is skipped: its screen shows the published
    version instead, not a finished gate. The import is module-level, not lazy: a lazy one
    puts a whole-module import on the screen's first read, where a browser check expects the
    answer within tens of milliseconds (CT-UI-04's recovery arms on that)."""
    for path in sorted(Path(data_dir, "packages").glob("*.pkg.sqlite")):
        package_id = path.name.removesuffix(".pkg.sqlite")
        try:
            service = setup_service_for_store(app._store, package_id)
            if service.current_proposal() is not None:
                return package_id, service
        except Exception:  # noqa: BLE001 — an unreadable setup is not the draft
            continue
    return None


# --- the package screen -----------------------------------------------------------------------


def package_setup_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The package screen's document (FR-UI-03a): the M-SETUP draft — its id, its draft
    version, its steps verbatim from `SetupService.steps()` with the blocking gates named —
    and the package version the console's run grades, which is the hub's own fact. A store
    with no draft answers `draft: None`; the screen shows the published state, never an
    invented gate."""
    payload: dict[str, Any] = {"draft": None, "current_version_id": None}
    run_row = _run_row_of(console, app, query)
    if run_row is not None:
        payload["current_version_id"] = run_row["package_version_id"]
    try:
        draft = _draft_package(app, _data_dir(app))
    except ValueError:
        draft = None
    if draft is None:
        return payload
    package_id, service = draft
    steps = service.steps()
    payload["draft"] = {
        "package_id": package_id,
        "version_id": str(steps.package_version_id),
        "ready_to_publish": bool(steps.ready_to_publish),
        "steps": [
            {
                "step_id": str(step.step_id),
                "name": str(step.name),
                "blocking": bool(step.blocking),
                "available": bool(step.available),
                "done": bool(step.done),
                "note": str(step.note),
            }
            for step in steps.steps
        ],
    }
    return payload


# --- the class and papers screens ---------------------------------------------------------------


def _students_of(app: Any, cohort_id: str) -> list[dict[str, Any]]:
    """One cohort's students in ledger order: every submission's identity (the ref is the
    student identity the screens display — `FR-CONSOLE-44`'s safe form), then roster names
    for a listed student who has no paper yet. Reads both tables in the cohort's own ledger;
    an unreadable roster answers submissions alone."""
    handle = app._store.cohort(cohort_id)
    students: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in handle.query(
        "SELECT submission_id, student_ref FROM submission ORDER BY submission_id"
    ):
        ref = str(row["student_ref"])
        seen.add(ref)
        students.append({"student_ref": ref, "submission_id": str(row["submission_id"]),
                         "full_name": None})
    try:
        roster = handle.query(
            "SELECT student_ref, full_name FROM roster ORDER BY student_ref")
    except Exception:  # noqa: BLE001 — a cohort without a roster table answers its papers
        roster = ()
    for row in roster:
        ref = str(row["student_ref"])
        if ref in seen:
            continue
        seen.add(ref)
        students.append({"student_ref": ref, "submission_id": None,
                         "full_name": str(row["full_name"] or "") or None})
    return students


def class_roster_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The class screen's document (FR-UI-03b): every stored cohort with its students — the
    roster editor's data, read live, so a submission written out of band is on the screen
    after the next reload without the SPA holding any state."""
    cohorts = [
        {"cohort_id": key, "students": _students_of(app, key)}
        for key in app._cohort_keys()
    ]
    return {"cohorts": cohorts}


def papers_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The papers screen's document (FR-UI-03c): the cohort's students and the scan parts
    already uploaded, in assembled order — the preflight state the server-rendered upload
    screen shows, through M-PIPE's `uploaded_parts`."""
    # Through `aeh.pipeline`'s re-export, the spelling the server-rendered screens already
    # use — `aeh.pipeline.background` at symbol level would add an undeclared edge to the
    # frozen set (`TC-CONSOLE-36`) for the same door.
    from aeh.pipeline import uploaded_parts

    run_row = _run_row_of(console, app, query)
    cohort_id = str(query.get("cohort_id") or "")
    if not cohort_id and run_row is not None:
        cohort_id = str(run_row["cohort_id"])
    if not cohort_id:
        keys = app._cohort_keys()
        cohort_id = keys[0] if keys else ""
    if not cohort_id:
        raise ValueError("papers names no stored cohort")
    return {
        "cohort_id": cohort_id,
        "students": _students_of(app, cohort_id),
        "parts": list(uploaded_parts(app._store, cohort_id)),
    }


# --- the run-bound screens ------------------------------------------------------------------------


def run_start_state_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The run-start screen's context (FR-UI-03d): the run the console serves — cohort,
    package version, status — beside the preview read (`run start preview`), which names the
    profile and refuses on its own. The context answers even when the preview cannot be
    composed: the teacher still sees what would start."""
    run_row = _run_row_of(console, app, query)
    if run_row is None:
        return {"run_id": None, "cohort_id": None, "package_version_id": None,
                "status": None}
    return {
        "run_id": str(run_row["run_id"]),
        "cohort_id": str(run_row["cohort_id"]),
        "package_version_id": str(run_row["package_version_id"]),
        "status": str(run_row["status"]),
    }


def monitor_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The monitor's document (FR-UI-03e): the run's status and pause reason beside
    M-ORCH's own `progress` report — the counts the server-rendered monitor shows."""
    run_row = _run_row_of(console, app, query)
    if run_row is None:
        return {"run_id": None, "status": None, "pause_reason": None, "progress": None}
    run_id = str(run_row["run_id"])
    try:
        report = app.progress(run_id)
        progress_payload = asdict(report) if not isinstance(report, dict) else dict(report)
    except Exception:  # noqa: BLE001 — a run with no ledger yet shows its status alone
        progress_payload = None
    return {
        "run_id": run_id,
        "status": str(run_row["status"]),
        "pause_reason": str(run_row.get("pause_reason") or "") or None,
        "progress": progress_payload,
    }


def _queue_payload(view: Any) -> dict[str, Any]:
    queue = view.queue
    return {
        "route": str(view.route),
        "flagged_total": int(queue.flagged_total),
        "shown": [
            {"submission_id": str(item.submission_id), "criterion_id": str(item.criterion_id),
             "kind": str(item.kind)}
            for item in queue.shown
        ],
        "budget_minutes": (
            None if queue.budget_minutes is None else int(queue.budget_minutes)
        ),
        "reserved_for_blind_minutes": int(queue.reserved_for_blind_minutes),
        "residual_provisional": int(queue.residual_provisional),
        "queries": [str(q) for q in queue.queries],
    }


def review_queue_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The review screen's document (FR-UI-03f): the teacher's queue, read through
    `ConsoleApp.review_queue` with `record=False` semantics — a screen render is a read,
    and answers nothing the S9 page would not."""
    run_id = str(query.get("run_id") or "") or _bound_run_id(console)
    if not run_id:
        raise ValueError("review names no run")
    view = app.review_queue(run_id)
    payload = _queue_payload(view)
    payload["run_id"] = run_id
    return payload


def blind_seats_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The blind screen's document: M-REVIEW's draw for the run, each seat's identity alone —
    submission, criterion, evaluation mode — beside the rubric's band scale as names. No
    system output crosses: the draw's items are exactly what M-REVIEW's `BlindSession`
    carries (`CT-REVIEW-09`), and the payload adds nothing the flow's transport face
    (`blind_flow`) does not already name."""
    from aeh.review import REVIEW_DEFAULT_BANDS

    run_id = str(query.get("run_id") or "") or _bound_run_id(console)
    if not run_id:
        raise ValueError("the blind sample names no run")
    service = app._review_service(run_id)
    if service is None:
        raise ValueError(f"M-REVIEW cannot open run {run_id!r}")
    session = service.blind_sample(run_id)
    cohort_id = None
    run_row = _run_row_of(console, app, query)
    if run_row is not None:
        cohort_id = str(run_row["cohort_id"])
    refs: dict[str, str] = {}
    if cohort_id:
        try:
            refs = {
                str(row["submission_id"]): str(row["student_ref"])
                for row in app._store.cohort(cohort_id).query(
                    "SELECT submission_id, student_ref FROM submission")
            }
        except Exception:  # noqa: BLE001 — a seat renders its submission id alone
            refs = {}
    return {
        "run_id": run_id,
        "band_scale": [str(band["band"]) for band in REVIEW_DEFAULT_BANDS],
        "seats": [
            {
                "submission_id": str(item.submission_id),
                "student_ref": refs.get(str(item.submission_id)),
                "criterion_id": str(item.criterion_id),
                "evaluation_mode": str(getattr(item, "evaluation_mode", "") or ""),
            }
            for item in session.items
        ],
    }


# --- the results screens ---------------------------------------------------------------------------


def results_screen_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The results screen's document (FR-UI-03g): every student's grade record (M-GRADE's
    own, the ledger's) beside the run's per-criterion bands, so a band shown is the stored
    band and the row a teacher sees is the row the ledger holds."""
    run_row = _run_row_of(console, app, query)
    if run_row is None:
        return {"run_id": None, "cohort_id": None, "students": []}
    run_id = str(run_row["run_id"])
    cohort_id = str(run_row["cohort_id"])
    records = run_grade_records(app._store, run_id)
    by_submission: dict[str, dict[str, Any]] = {}
    for record in records:
        by_submission[str(record["submission_id"])] = {
            "submission_id": str(record["submission_id"]),
            "student_ref": None,
            "total": record["total"],
            "state": str(record["state"] or ""),
            "criteria": [],
        }
    try:
        bands = app._store.cohort(cohort_id).query(
            GRADE_STATEMENTS["select_run_criterion_bands"],
            run_id=run_id, cohort_id=cohort_id,
        )
    except Exception:  # noqa: BLE001 — a cohort ledger without the rows answers grades alone
        bands = ()
    for row in bands:
        student = by_submission.get(str(row["submission_id"]))
        if student is not None:
            student["criteria"].append({
                "criterion_id": str(row["criterion_id"]),
                "criterion_band": str(row["band"]),
            })
    try:
        refs = {
            str(row["submission_id"]): str(row["student_ref"])
            for row in app._store.cohort(cohort_id).query(
                "SELECT submission_id, student_ref FROM submission")
        }
    except Exception:  # noqa: BLE001 — the ref column's absence is not the grades'
        refs = {}
    for submission_id, ref in refs.items():
        if submission_id in by_submission:
            by_submission[submission_id]["student_ref"] = ref
    return {"run_id": run_id, "cohort_id": cohort_id, "students": list(by_submission.values())}


def student_detail_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """One student's detail: their grade record and their narrative — the text M-SYNTH
    wrote, which is the student's own document a teacher reads on the student screen.
    Refuses a read that names no submission (the caller's mistake, a 400)."""
    submission_id = str(query.get("submission_id") or "")
    run_row = _run_row_of(console, app, query)
    if run_row is None:
        raise ValueError("student detail names no run")
    if not submission_id:
        raise ValueError("student detail names no submission")
    cohort_id = str(run_row["cohort_id"])
    record = next(
        (r for r in run_grade_records(app._store, str(run_row["run_id"]))
         if str(r["submission_id"]) == submission_id),
        None,
    )
    student_ref = None
    narrative: list[dict[str, Any]] = []
    try:
        handle = app._store.cohort(cohort_id)
        rows = handle.query(
            "SELECT student_ref FROM submission WHERE submission_id = :s", s=submission_id)
        if rows:
            student_ref = str(rows[0]["student_ref"])
        narrative = [
            {"level": str(row["level"]), "question_id": str(row["question_id"]),
             "text": str(row["text"])}
            for row in handle.query(
                "SELECT level, question_id, text FROM narrative "
                "WHERE run_id = :r AND submission_id = :s ORDER BY narrative_id",
                r=str(run_row["run_id"]), s=submission_id,
            )
        ]
    except Exception:  # noqa: BLE001 — a ledger without the tables answers the grade alone
        pass
    return {
        "run_id": str(run_row["run_id"]),
        "submission_id": submission_id,
        "student_ref": student_ref,
        "total": None if record is None else record["total"],
        "state": None if record is None else str(record["state"] or ""),
        "narrative": narrative,
    }


# --- the status and help screens --------------------------------------------------------------------


def system_status_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The system status screen's document: the hub's three facts beside the store's own
    shape — how many cohort ledgers and package files this console serves."""
    from .hub_state import engine_in_use

    run_row = _run_row_of(console, app, query)
    data_dir = getattr(app._store, "data_dir", None)
    packages = len(list(Path(data_dir, "packages").glob("*.pkg.sqlite"))) if data_dir else 0
    return {
        "run_id": None if run_row is None else str(run_row["run_id"]),
        "run_status": None if run_row is None else str(run_row["status"]),
        "package_version_id": (
            None if run_row is None else str(run_row["package_version_id"])
        ),
        "engine": engine_in_use(getattr(app, "run_config", None)),
        "cohorts": len(app._cohort_keys()),
        "packages": packages,
    }


def help_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The help screen's document — the manuals this console ships, until M-HELP's index
    lands (#638). The degradation contract (FR-UI-07) applies to this screen too, so the
    read exists now and the screen's recovery is real."""
    return {
        "manuals": [
            "Teacher guide",
            "Deployment tutorial",
            "Live-test documents",
            "Console help",
        ],
        "ask": (
            "The assistant answers questions about operating the system; it does not "
            "operate it."
        ),
    }
