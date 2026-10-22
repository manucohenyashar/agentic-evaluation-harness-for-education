"""The redesign SPA's read surface (FR-CONSOLE-47…52, #755): the context header's switcher
feed and the six secondary pages' documents, as pure store/service projections.

Every reader here is a read: it writes nothing, adds no persistence, and reaches only the
doors the store API and the modules already expose — the runs and work units the cohort
ledgers hold, the quarantine rows, the console's own progress report and job registry.
The console captures no new state for these: an issue or a log line the store does not
hold is not shown (`FR-CONSOLE-51`), and the jobs registry is console memory beside the
run threads (`ADR-47`), never pipeline state.

Key naming is deliberate (ADV-15): no payload here names a value `band`, `confidence` or
`scoring_engine` — a grading point's score levels travel as name lists, and the run's
per-criterion figure is never per-student (`CT-CONSOLE-09`): progress and logs render at
stage / grading-point granularity, the parked page being the one place a student is named,
because naming the matched student is `FR-CONSOLE-47`'s own requirement.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import queries as Q
from .vocabulary import QUARANTINE_STATES


# --- the declared enums (`CT-CONSOLE-38`: additive; the SPA maps unknown values to a
# --- neutral "needs attention" label rather than erroring) -------------------------------------------

#: The wizard stage-state badge values (§3.3.4's stepper legend, as data).
STAGE_STATES: tuple[str, ...] = (
    "done", "in_progress", "not_started", "needs_attention", "failed", "queued",
)


#: A class ledger's states (`ADR-48`): roster-only state is what makes a ledger a class.
CLASS_STATES: tuple[str, ...] = ("empty", "roster_only")


#: A grading cohort's states, derived from its population and its newest run.
COHORT_STATES: tuple[str, ...] = ("empty", "ready", "grading", "graded", "stalled")


#: A package's states, derived from its draft and its published version.
PACKAGE_STATES: tuple[str, ...] = ("drafting", "draft_ready", "published")


#: A run's states — the run row's own CHECK domain, mirrored verbatim so the SPA renders
#: what the ledger holds rather than a re-spelled copy of it.
RUN_STATES: tuple[str, ...] = ("pending", "running", "paused", "complete", "failed")


#: The stage of the workflow a run is at, as the context header renders it. Derived, not
#: stored: `pending` has not reached the papers yet; a running or paused run is grading; a
#: complete run is reviewing until every current grade is final, then exporting; a failed
#: run stopped while grading.
RUN_STAGES: tuple[str, ...] = ("papers", "grading", "reviewing", "exporting")


_RUN_STATE_TO_STAGE: dict[str, str] = {
    "pending": "papers",
    "running": "grading",
    "paused": "grading",
    "complete": "reviewing",
    "failed": "grading",
}


#: The work-unit stages, as the ledger spells them, in the teacher's words (§3.3.3). The
#: shipped writers produce these five (`M-EXTRACT`/`M-INTEG` write `extract` and `score`,
#: the review unit `review`, and M-DET's ledger derives `deterministic` or `judged` from
#: the criterion's mode); anything else is additive and passes through as it is stored,
#: for the SPA to map to its neutral label (`CT-CONSOLE-38`).
_STAGE_LABELS: dict[str, str] = {
    "extract": "Reading the papers",
    "score": "Grading",
    "deterministic": "Marking the answer sheets",
    "judged": "Grading the written answers",
    "review": "Reviewing flagged answers",
}


#: The work-unit statuses, as the ledger spells them, in the teacher's words.
_UNIT_STATE_LABELS: dict[str, str] = {
    "pending": "waiting",
    "leased": "in progress",
    "done": "done",
    "failed": "failed",
    "quarantined": "parked",
}


#: The park's diagnoses, as the schema spells them, in the teacher's words (§3.3.3). The
#: three parked states are `QUARANTINE_STATES`; the two flagged-but-available ones are here
#: so a count can say what they are without implying they parked anything.
_INGEST_STATUS_LABELS: dict[str, str] = {
    "ok": "Read cleanly",
    "low_confidence_ocr": "Read with some uncertainty",
    "unreadable": "Could not be read",
    "incomplete": "Missing pages or answers",
    "unmatched_assessment": "Doesn't match the class list",
}


_PARKED_RESOLUTIONS: dict[str, tuple[str, ...]] = {
    "unreadable": (
        "Scan the paper again, more clearly, and upload it in place of this one.",
        "Mark the paper unresolvable if no better scan exists.",
    ),
    "incomplete": (
        "Upload the complete paper — every page and every answer.",
        "Mark the paper unresolvable if the missing part cannot be recovered.",
    ),
    "unmatched_assessment": (
        "Check the class list names the student whose paper this is.",
        "Mark the paper unresolvable if it belongs to no one on the list.",
    ),
}


#: The ways out for a second paper of one student (FR-INGEST-41): keep one of the two.
_DUPLICATE_RESOLUTIONS: tuple[str, ...] = (
    "Keep the earlier paper: remove this scan.",
    "Use this scan instead: remove the earlier paper, then give this one to the student.",
)


# --- shared helpers ----------------------------------------------------------------------------------


def _data_dir(app: Any) -> Any:
    return getattr(app._store, "data_dir", None)


def _skipped_before(app: Any) -> int:
    return int(getattr(app, "_skipped_ledgers", 0))


def _projected(app: Any, before: int, **counts: Any) -> dict[str, Any]:
    """The per-read observability block every payload carries next to its status (seam 4):
    what the read projected, and how many cohort ledgers it had to skip because the
    pipeline was writing them (`FR-CONSOLE-37`'s counter, surfaced per read)."""
    counts["ledgers_skipped"] = int(getattr(app, "_skipped_ledgers", 0)) - before
    return counts


def _cost_of(raw: Any) -> float | None:
    """The ledger's cost accrual as a number, or `None` when it carries none. A stored zero
    is returned as zero — it is the ledger's own measured figure (`CT-PROV-03`)."""
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(str(raw))
    except ValueError:
        return None


def _run_rows(app: Any) -> list[dict[str, Any]]:
    """Every run row, across the cohort files, as dicts."""
    rows = app._read_cohort_files(Q._SELECT_RUNS_ALL, [])
    return [dict(row) for row in rows]


def _run_row_of(app: Any, run_id: str) -> dict[str, Any] | None:
    for row in _run_rows(app):
        if str(row["run_id"]) == run_id:
            return row
    return None


def _teacher_stage(stage: Any) -> str:
    return _STAGE_LABELS.get(str(stage), str(stage))


def _strip_exception_name(detail: Any) -> str | None:
    """The store-held detail of a failed step, with leading exception class names removed
    (`CT-CONSOLE-33`: a raw exception name never reaches a teacher-facing body). The
    message after the colon is the ledger's own record and is kept; a detail that names no
    exception passes through unchanged. The pipeline's composition-fault shape —
    `composition fault: <SomeError>: <message>` — loses its prefix and its exception name
    both, and a chain of exception names loses them all."""
    text = str(detail or "").strip()
    if not text:
        return None
    stripped = text
    while True:
        if stripped.startswith("composition fault:"):
            tail = stripped.partition(":")[2].strip()
            if not tail or tail == stripped:
                break
            stripped = tail
            continue
        head, sep, rest = stripped.partition(":")
        if not sep or not head.strip() or not head.strip().split(" ")[0].endswith(
            ("Error", "Exception", "Warning"),
        ):
            break
        candidate = rest.strip() or stripped
        if candidate == stripped:
            break
        stripped = candidate
    return stripped


def _requires_run(query: Any) -> str:
    run_id = str((query or {}).get("run_id") or "").strip()
    if not run_id:
        raise ValueError("this read takes the run it is about, as ?run_id=<the run's id>")
    return run_id


def _query_page(query: Any) -> int:
    """The 1-based page a paged read was asked for: page 1 when absent; a value outside the
    positive whole numbers is refused, never silently treated as page 1."""
    raw = str((query or {}).get("page") or "").strip()
    if not raw:
        return 1
    try:
        page = int(raw)
    except ValueError:
        page = 0
    if page < 1:
        raise ValueError("the page a read is asked for is a whole number from 1 up, as ?page=2")
    return page


# --- the context read (FR-CONSOLE-48, §3.3.5) ---------------------------------------------------------


def _ledger_population(app: Any, key: str) -> dict[str, int] | None:
    """One ledger's roster, paper and run counts; `None` when the ledger cannot be read
    (the pipeline is writing it — skipped and counted, never fatal to the whole read)."""
    try:
        rows = list(app._store.cohort(key).query(Q._SELECT_LEDGER_POPULATION))
    except Exception:  # noqa: BLE001 — one unreadable ledger is that ledger's bad luck
        app._skipped_ledgers += 1
        return None
    if not rows:
        return {"roster_n": 0, "papers_n": 0, "runs_n": 0}
    row = rows[0]

    def _n(name: str) -> int:
        try:
            return int(row[name])
        except (KeyError, TypeError, ValueError):
            return 0

    return {"roster_n": _n("roster_n"), "papers_n": _n("papers_n"), "runs_n": _n("runs_n")}


def _latest_run_status(runs: list[dict[str, Any]]) -> str | None:
    """The status of a ledger's newest run — latest `started_at`, then run id, the same
    newest-run rule the key-correction re-derivation uses; a run that never started
    (no `started_at`) still sorts, after any that did."""
    if not runs:
        return None
    newest = max(runs, key=lambda row: (str(row["started_at"] or ""), str(row["run_id"])))
    return str(newest["status"])


def _classify_ledger(population: dict[str, int], latest_status: str | None) -> tuple[str, str]:
    """A ledger's kind and state (`ADR-48`): a class is a cohort ledger in roster-only
    state — students listed, no papers, no runs. Until #761's creation actions distinguish
    the two at birth, the ledger's contents are the only honest signal: any paper or run
    makes it a cohort; anything else is a class, empty or listed. A cohort's state rides
    its newest run: none yet, ready; one under way, grading; finished, graded; stopped
    with a problem, stalled."""
    if population["papers_n"] or population["runs_n"]:
        return "cohorts", _cohort_state(population, latest_status)
    state = "roster_only" if population["roster_n"] else "empty"
    return "classes", state


def _cohort_state(population: dict[str, int], latest_status: str | None) -> str:
    if not population["roster_n"] and not population["papers_n"]:
        return "empty"
    if latest_status in ("pending", "running", "paused"):
        return "grading"
    if latest_status == "complete":
        return "graded"
    if latest_status == "failed":
        return "stalled"
    return "ready"


def _package_rows(app: Any, data_dir: Any) -> list[dict[str, Any]]:
    """The package entities: one per package file on disk, with its published version, its
    draft's missing-piece count and its wizard rows for the package stages (§3.3.4)."""
    from pathlib import Path

    from .authoring_reads import draft_placeholders, find_draft_for

    packages: list[dict[str, Any]] = []
    if data_dir is None:
        return packages
    for path in sorted(Path(data_dir, "packages").glob("*.pkg.sqlite")):
        package_id = path.name.removesuffix(".pkg.sqlite")
        versions: list[dict[str, Any]] = []
        try:
            versions = [dict(row) for row in
                        app._store.package(package_id).query(Q._SELECT_PACKAGE_VERSIONS)]
        except Exception:  # noqa: BLE001 — an unreadable catalog is that package's bad luck
            versions = []
        published = next(
            (str(row["package_version_id"]) for row in versions if row["locked"]),
            None,
        )
        draft_path = find_draft_for(data_dir, package_id)
        missing = draft_placeholders(draft_path) if draft_path is not None else None
        if published is not None:
            state = "published"
        elif missing is None:
            state = "drafting"
        elif missing:
            state = "drafting"
        else:
            state = "draft_ready"
        detail = {
            "create package": (
                "done", "A draft or a published version exists."
                if (draft_path is not None or versions) else "No draft yet.",
            ),
            "review draft": (
                "done" if (missing == 0 or published is not None) else (
                    "needs_attention" if missing else "not_started"),
                "" if missing is None else (
                    f"The draft has {missing} missing pieces." if missing
                    else "No missing pieces."),
            ),
            "approve package": (
                "done" if published is not None else "not_started",
                f"Published as {published}." if published is not None else "",
            ),
        }
        packages.append({
            "package_id": package_id,
            "state": state,
            "published_version": published,
            # FR-CONSOLE-74 (#808): the id the SPA sends back; `published_version` reads as
            # the teacher label once the boundary has named it.
            "published_version_id": published,
            "version_count": len(versions),
            "draft_missing_pieces": missing,
            "wizard": [
                {"stage": stage, "state": row[0],
                 "detail": row[1] if row[0] in ("needs_attention", "failed") else ""}
                for stage, row in detail.items()
            ],
        })
    return packages


def context_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The context header's feed (FR-CONSOLE-48): every class, cohort, package and run,
    each with its state from a declared enum, the packages with their wizard rows, and the
    runs with the stage each is at. A console with no store answers empty collections —
    the switcher renders empties, never an error."""
    del console, query  # the context is the whole store's, not one run's
    before = _skipped_before(app)
    data_dir = _data_dir(app)
    classes: list[dict[str, Any]] = []
    cohorts: list[dict[str, Any]] = []
    run_rows = _run_rows(app) if data_dir is not None else []
    runs_by_cohort: dict[str, list[dict[str, Any]]] = {}
    for row in run_rows:
        runs_by_cohort.setdefault(str(row["cohort_id"]), []).append(row)
    ledger_keys = app._cohort_keys() if data_dir is not None else ()
    from .screen_reads import _ledger_is_live

    for key in ledger_keys:
        if not _ledger_is_live(app, key):
            continue  # a deleted (purged) class: its emptied file is not a class
        population = _ledger_population(app, key)
        if population is None:
            continue
        kind, state = _classify_ledger(population, _latest_run_status(
            runs_by_cohort.get(key, ())))
        students = population["roster_n"] or population["papers_n"]
        entry: dict[str, Any] = {
            "cohort_id": key,
            "label": key,
            "students": students,
            "state": state,
            "runs": len(runs_by_cohort.get(key, ())),
        }
        if kind == "classes":
            classes.append(entry)
        else:
            cohorts.append(entry)
    packages = _package_rows(app, data_dir)
    unfinalized: dict[str, int] = {}
    runs: list[dict[str, Any]] = []
    for row in run_rows:
        run_id = str(row["run_id"])
        stage = _RUN_STATE_TO_STAGE.get(str(row["status"]), "grading")
        if str(row["status"]) == "complete":
            key = str(row["cohort_id"])
            if key not in unfinalized:
                try:
                    handle = app._store.cohort(key)
                    rows_ = list(handle.query(Q._SELECT_RUN_UNFINALIZED, run_id=run_id))
                    unfinalized[key] = int(rows_[0]["n"]) if rows_ else 0
                except Exception:  # noqa: BLE001 — an unreadable count keeps reviewing
                    unfinalized[key] = 1
            if unfinalized[key] == 0:
                stage = "exporting"
        runs.append({
            "run_id": run_id,
            "cohort_id": str(row["cohort_id"]),
            "package_id": str(row["package_id"]),
            "package_version_id": str(row["package_version_id"]),
            "state": str(row["status"]),
            "stage": stage,
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
        })
    return {
        "classes": classes,
        "cohorts": cohorts,
        "packages": packages,
        "runs": runs,
        "enums": {
            "stage_states": list(STAGE_STATES),
            "class_states": list(CLASS_STATES),
            "cohort_states": list(COHORT_STATES),
            "package_states": list(PACKAGE_STATES),
            "run_states": list(RUN_STATES),
            "run_stages": list(RUN_STAGES),
        },
        "projected": _projected(
            app, before, classes=len(classes), cohorts=len(cohorts),
            packages=len(packages), runs=len(runs),
        ),
    }


# --- the impact read (FR-CONSOLE-49) -------------------------------------------------------------------


def impact_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """What editing a package version would touch (FR-CONSOLE-49): the runs that used it
    and the students already graded under it. A version nothing used answers zeros — that
    is a measured zero, not a refusal; a version no package declares is refused, because
    the teacher asked about something that does not exist."""
    del console
    version = str((query or {}).get("package_version") or "").strip()
    if not version:
        raise ValueError("this read takes the package version it is about, "
                         "as ?package_version=<the version's id>")
    before = _skipped_before(app)
    known = app._package_of(version)
    if not known:
        raise ValueError(
            "There is no test package version with that reference. "
            "Choose one from the list on the package page."
        )
    run_rows = [row for row in _run_rows(app)
                if str(row["package_version_id"]) == version]
    students = 0
    for key in app._cohort_keys():
        try:
            rows = list(app._store.cohort(key).query(
                Q._SELECT_VERSION_REACHED_STUDENTS, package_version_id=version))
            students += int(rows[0]["n"]) if rows else 0
        except Exception:  # noqa: BLE001 — one unreadable ledger is that ledger's bad luck
            app._skipped_ledgers += 1
            continue
    return {
        "package_version": version,
        "package_version_id": version,  # the id; `package_version` is the label (#808)
        "runs": len(run_rows),
        "students": students,
        "run_records": [
            {"run_id": str(row["run_id"]), "cohort_id": str(row["cohort_id"]),
             "state": str(row["status"])}
            for row in run_rows
        ],
        "regrading": {
            "triggered": students > 0,
            "detail": (
                f"Editing the grading guide means {students} already-graded papers "
                f"need re-grading." if students > 0
                else "Nothing downstream yet — no paper has been graded under it."
            ),
        },
        "projected": _projected(app, before, runs=len(run_rows), students=students),
    }


# --- the jobs reads (FR-CONSOLE-52, ADR-47) -------------------------------------------------------------

_RUN_JOB_ERROR_NEXT = (
    "Open the run's monitor to see why it stopped, then resume it or start a new run."
)


def _run_job_records(app: Any) -> list[dict[str, Any]]:
    """The run jobs, mirrored from the run rows (`ADR-47`): each carries `CT-CONSOLE-37`'s
    field set, its progress from the console's own grouped report — stage and grading-point
    granularity, never a per-student figure (`CT-CONSOLE-09`)."""
    from .jobs import RUN_STATE_TO_JOB_STATE, job_record

    records: list[dict[str, Any]] = []
    for row in _run_rows(app):
        run_id = str(row["run_id"])
        try:
            report = app.progress(run_id)
            done = int(report.done)
            total = done + int(report.in_flight) + int(report.pending) + int(report.quarantined)
        except Exception:  # noqa: BLE001 — a run whose progress cannot be read still lists
            done, total = None, None
        state = RUN_STATE_TO_JOB_STATE.get(str(row["status"]), "queued")
        error_detail = None
        error_next = None
        if state == "failed":
            error_detail = _strip_exception_name(row["pause_reason"]) or (
                "The run stopped with a problem.")
            error_next = _RUN_JOB_ERROR_NEXT
        records.append(job_record(
            job_id=run_id,
            kind="run",
            state=state,
            done=done,
            total=total,
            current=None,
            started_at=row["started_at"],
            finished_at=row["completed_at"],
            cost_usd=_cost_of(row["cost_spend"]),
            error_detail=error_detail,
            error_next_action=error_next,
        ))
    return records


def jobs_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """Every job the console knows of (FR-CONSOLE-52): the registry's own records (from
    #760's authoring jobs; empty until then) plus one record per run, mirrored from the run
    row. Writes nothing; a console restart drops the finished history by design."""
    del console, query
    before = _skipped_before(app)
    registry_jobs = app._jobs.all()
    run_jobs = _run_job_records(app)
    return {
        "jobs": registry_jobs + run_jobs,
        "projected": _projected(
            app, before, registry_jobs=len(registry_jobs), run_jobs=len(run_jobs),
        ),
    }


def job_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """One job (FR-CONSOLE-52): its `CT-CONSOLE-37` record plus the per-job statistics —
    duration where both stamps exist, and, for a run, how many papers have a current
    grade. An unknown id is refused in the teacher's words: a console restart drops the
    finished history, so yesterday's job may genuinely be gone."""
    del console
    job_id = str((query or {}).get("job_id") or "").strip()
    if not job_id:
        raise ValueError("this read takes the job it is about, as ?job_id=<the job's id>")
    before = _skipped_before(app)
    from .jobs import job_record

    record = app._jobs.get(job_id)
    kind = str(record["kind"]) if record else "run"
    started_at = record["started_at"] if record else None
    finished_at = record["finished_at"] if record else None
    if record is None:
        row = _run_row_of(app, job_id)
        if row is None:
            raise ValueError(
                "There is no job with that reference. It may have finished before the "
                "console last restarted — finished jobs are kept only while the console "
                "runs."
            )
        mirrors = [candidate for candidate in _run_job_records(app)
                   if candidate["job_id"] == job_id]
        record = mirrors[0] if mirrors else job_record(
            job_id=job_id, kind="run", state="queued")
        started_at, finished_at = row["started_at"], row["completed_at"]
    duration_seconds = _duration(started_at, finished_at)
    payload = dict(record)
    payload["statistics"] = {"duration_seconds": duration_seconds, "items_graded": None}
    if kind == "run":
        payload["statistics"]["items_graded"] = _graded_students(app, job_id)
    payload["projected"] = _projected(app, before)
    return payload


def _duration(started_at: Any, finished_at: Any) -> float | None:
    """The wall-clock seconds between the two stamps, or `None` when either is missing —
    never a guess from one stamp."""
    try:
        start = datetime.fromisoformat(str(started_at))
        end = datetime.fromisoformat(str(finished_at))
    except (TypeError, ValueError):
        return None
    return max(0.0, (end - start).total_seconds())


def _graded_students(app: Any, run_id: str) -> int | None:
    """How many of the run's papers hold a current grade, read from the ledger that holds
    the run; `None` when no ledger answers (never a fabricated zero)."""
    key = app._cohort_for_run(run_id)
    if key is None:
        return None
    try:
        rows = list(app._store.cohort(key).query(
            Q._SELECT_RUN_GRADED_STUDENTS, run_id=run_id,
        ))
    except Exception:  # noqa: BLE001 — an unreadable ledger leaves the figure unknown
        return None
    return int(rows[0]["n"]) if rows else 0


# --- the issues read (FR-CONSOLE-51) ---------------------------------------------------------------------

_QUARANTINE_ISSUES: dict[str, tuple[str, str, str]] = {
    # status: (what happened, what it affects, the next step)
    "unreadable": (
        "A paper could not be read.",
        "That paper is parked; its marks are not graded.",
        "Upload a clearer scan of the paper from the parked page, or mark it unresolvable.",
    ),
    "incomplete": (
        "A paper is missing pages or answers.",
        "That paper is parked; its marks are not graded.",
        "Upload the complete paper again, or mark it unresolvable.",
    ),
    "unmatched_assessment": (
        "A paper's answer sheet does not match anyone on the class list.",
        "That paper is parked; its marks are not graded.",
        "Check the class list, then re-match the paper, or mark it unresolvable.",
    ),
}


def _cohort_query(app: Any, key: str, statement: str, **params: Any) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in app._store.cohort(key).query(statement, **params)]
    except Exception:  # noqa: BLE001 — one unreadable ledger is that ledger's bad luck
        app._skipped_ledgers += 1
        return []


def issues_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The run's errors and warnings as teacher-language records (FR-CONSOLE-51): each
    saying what happened, what it affects, and the next step. Sourced entirely from rows
    the store already holds — the console adds no persistence and invents no issue: a run
    with nothing wrong answers an empty list."""
    del console
    run_id = _requires_run(query)
    before = _skipped_before(app)
    row = _run_row_of(app, run_id)
    if row is None:
        raise ValueError(
            "There is no grading run with that reference. Choose one from the switcher."
        )
    cohort_key = app._cohort_for_run(run_id)
    issues: list[dict[str, Any]] = []
    sources: dict[str, int] = {}
    if cohort_key is not None:
        for unit in _cohort_query(app, cohort_key, Q._SELECT_RUN_WORK_UNITS, run_id=run_id):
            if str(unit["status"]) != "failed":
                continue
            sources["grading step"] = sources.get("grading step", 0) + 1
            attempts = int(unit["attempts"] or 0)
            issues.append({
                "issue_id": f"work-unit:{unit['work_id']}",
                "source": "grading step",
                "what": (
                    f"A grading step gave up after {attempts} tries."
                    if attempts > 1 else "A grading step gave up."
                ),
                "affects": "The paper it was grading may be missing a score.",
                "next_step": "Use the console's recover action to pick the work back up.",
            })
        for parked in _cohort_query(app, cohort_key, Q._SELECT_COHORT_QUARANTINE,
                                    cohort_id=str(row["cohort_id"])):
            status = str(parked["ingest_status"])
            what, affects, next_step = _QUARANTINE_ISSUES.get(
                status, ("A paper was parked while its pages were read.",
                         "That paper is parked; its marks are not graded.",
                         "Open the parked page to see its reason and its options."))
            sources["parked paper"] = sources.get("parked paper", 0) + 1
            issues.append({
                "issue_id": f"parked:{parked['submission_id']}",
                "source": "parked paper",
                "what": what,
                "affects": affects,
                "next_step": next_step,
            })
        for request in _cohort_query(app, cohort_key, Q._SELECT_RUN_ESCALATIONS, run_id=run_id):
            sources["second opinion"] = sources.get("second opinion", 0) + 1
            admitted = bool(request["admitted"])
            issues.append({
                "issue_id": f"escalation:{request['request_id']}",
                "source": "second opinion",
                "what": ("A grading point needed a second opinion." if admitted else
                         "A grading point is waiting for a second opinion slot."),
                "affects": ("That score took longer to settle; the result is unchanged."
                            if admitted else "That score is not settled yet."),
                "next_step": ("Nothing to do — the second opinion is part of the check."
                              if admitted else
                              "Wait: the run admits it when the budget allows."),
            })
        for breaker in _cohort_query(app, cohort_key, Q._SELECT_RUN_BREAKERS, run_id=run_id):
            sources["grading point"] = sources.get("grading point", 0) + 1
            issues.append({
                "issue_id": f"breaker:{breaker['breaker_id']}",
                "source": "grading point",
                "what": ("One grading point needed too many second opinions, so second "
                         "opinions for it were stopped."),
                "affects": "Scores on that grading point may need review before exporting.",
                "next_step": "Review that grading point's scores before exporting.",
            })
    return {
        "run_id": run_id,
        "issues": issues,
        "projected": _projected(app, before, issues=len(issues), sources=sources),
    }


# --- the logs read (FR-CONSOLE-51) ------------------------------------------------------------------------


def logs_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The run's stage-by-stage records, as the store holds them (FR-CONSOLE-51): the run
    row's own milestones, one summary per stage the ledger carries work for, and one
    record per group of failed steps — stage and grading-point granularity, never a
    per-student figure (`CT-CONSOLE-09`). A stage with no records shows nothing: the
    console captures no stderr and invents no line."""
    del console
    run_id = _requires_run(query)
    before = _skipped_before(app)
    from .settings import logs_page_size

    row = _run_row_of(app, run_id)
    if row is None:
        raise ValueError(
            "There is no grading run with that reference. Choose one from the switcher."
        )
    records: list[dict[str, Any]] = []
    sources: dict[str, int] = {}
    if row["started_at"]:
        sources["run"] = sources.get("run", 0) + 1
        records.append({
            "record_id": f"run:{run_id}:started",
            "kind": "milestone",
            "stage": "The run",
            "at": row["started_at"],
            "text": "The grading run started.",
            "detail": None,
        })
    cohort_key = app._cohort_for_run(run_id)
    stage_lines: dict[str, dict[str, int]] = {}
    problems: dict[tuple[str, str, str, str], int] = {}
    if cohort_key is not None:
        for unit in _cohort_query(app, cohort_key, Q._SELECT_RUN_WORK_UNITS, run_id=run_id):
            stage = _teacher_stage(unit["stage"])
            state = _UNIT_STATE_LABELS.get(str(unit["status"]), str(unit["status"]))
            stage_lines.setdefault(stage, {}).setdefault(state, 0)
            stage_lines[stage][state] += 1
            if str(unit["status"]) == "failed":
                key = (
                    stage,
                    str(unit["criterion_id"] or ""),
                    str(unit["judge_id"] or ""),
                    _strip_exception_name(unit["last_error"]) or "",
                )
                problems[key] = problems.get(key, 0) + 1
    for stage, counts in stage_lines.items():
        sources["stage"] = sources.get("stage", 0) + 1
        parts = [f"{n} {label}" for label, n in sorted(counts.items())]
        records.append({
            "record_id": f"run:{run_id}:stage:{stage}",
            "kind": "summary",
            "stage": stage,
            "at": None,
            "text": f"{stage} — " + ", ".join(parts) + ".",
            "detail": None,
        })
    for (stage, criterion, judge, detail), n in sorted(problems.items()):
        sources["problem"] = sources.get("problem", 0) + 1
        point = f" at grading point {criterion}" if criterion else ""
        records.append({
            "record_id": f"run:{run_id}:problem:{stage}:{criterion}:{judge}",
            "kind": "problem",
            "stage": stage,
            "at": None,
            "text": f"{n} step{'s' if n != 1 else ''} gave up{point}.",
            "detail": detail or None,
        })
    if row["completed_at"]:
        status = str(row["status"])
        text = {
            "complete": "The grading run finished.",
            "failed": "The grading run stopped with a problem.",
            "paused": "The grading run was paused.",
        }.get(status, f"The grading run is {status}.")
        sources["run"] = sources.get("run", 0) + 1
        records.append({
            "record_id": f"run:{run_id}:{status}",
            "kind": "milestone",
            "stage": "The run",
            "at": row["completed_at"],
            "text": text,
            "detail": _strip_exception_name(row["pause_reason"]) if status == "failed" else None,
        })
    page_size = logs_page_size()
    start = (_query_page(query) - 1) * page_size
    shown = records[start:start + page_size]
    return {
        "run_id": run_id,
        "records": shown,
        "page": {
            "size": page_size,
            "shown": len(shown),
            "more_available": len(records) > start + page_size,
        },
        "projected": _projected(app, before, records=len(records), sources=sources),
    }


# --- the parked read (FR-CONSOLE-47) ------------------------------------------------------------------------


def _parked_class_facts(app: Any, cohort_id: str) -> dict[str, Any]:
    """What the parked page needs of one class to resolve its papers (B8): the students on its
    list who have no paper yet — the only students a paper may be assigned to — and the
    operator decisions already recorded. An unreadable class answers empty lists."""
    from aeh.pipeline import parked_decisions

    try:
        handle = app._store.cohort(cohort_id)
        with_paper = {str(row["student_ref"]) for row in handle.query(
            "SELECT student_ref FROM submission "
            "WHERE NOT (ingest_status = 'incomplete' AND quarantined = 0) "
            # A parked second copy is not the student's paper (FR-INGEST-41): once the
            # earlier one is removed, the student is offered for this copy.
            "AND COALESCE(v3_identity, '') != 'already_has_paper'")}
        roster = [
            {"student_ref": str(row["student_ref"]),
             "full_name": str(row["full_name"] or "") or None}
            for row in handle.query(
                "SELECT student_ref, full_name FROM roster ORDER BY full_name, student_ref")
            if str(row["student_ref"]) not in with_paper
        ]
        names = {str(row["student_ref"]): (str(row["full_name"] or "") or None)
                 for row in handle.query("SELECT student_ref, full_name FROM roster")}
        decisions = [
            {**{key: decision[key] for key in (
                "submission_id", "resolution", "actor", "student_ref", "note", "decided_at")},
             "full_name": names.get(str(decision["student_ref"] or ""))}
            for decision in parked_decisions(handle)
        ]
    except Exception:  # noqa: BLE001 — a class the page cannot read offers no assignment
        return {"students_without_paper": [], "decisions": []}
    return {"students_without_paper": roster, "decisions": decisions}


def cohort_id_of(row: Any) -> str:
    return str(row["cohort_id"])


def _name_of(app: Any, cohort_id: str, student_ref: str) -> str:
    """The student's listed name, the way the teacher knows them; the ref only when the list
    holds no name for it."""
    try:
        rows = app._store.cohort(cohort_id).query(
            "SELECT full_name FROM roster WHERE student_ref = :ref", ref=student_ref)
    except Exception:  # noqa: BLE001 — the ref stands in for an unreadable name
        rows = []
    return (str(rows[0]["full_name"] or "") if rows else "") or student_ref


def _earlier_paper(app: Any, cohort_id: str, student_ref: str,
                   submission_id: str) -> dict[str, Any]:
    """The student a second-copy paper matched, and their paper already in the class: its id
    and whether a run has graded it (a graded paper stays; the copy is then removed)."""
    facts: dict[str, Any] = {"student_ref": student_ref, "full_name": None,
                             "submission_id": None, "graded": False}
    try:
        handle = app._store.cohort(cohort_id)
        names = handle.query("SELECT full_name FROM roster WHERE student_ref = :ref",
                             ref=student_ref)
        if names:
            facts["full_name"] = str(names[0]["full_name"] or "") or None
        earlier = handle.query(
            "SELECT submission_id FROM submission WHERE student_ref = :ref "
            "AND submission_id != :sid AND NOT (ingest_status = 'incomplete' "
            "AND quarantined = 0) ORDER BY rowid", ref=student_ref, sid=submission_id)
        if earlier:
            facts["submission_id"] = str(earlier[0]["submission_id"])
            facts["graded"] = bool(handle.query(
                "SELECT 1 FROM work_unit WHERE submission_id = :sid LIMIT 1",
                sid=facts["submission_id"]))
    except Exception:  # noqa: BLE001 — what could be read is named; the rest stays empty
        pass
    return facts


def parked_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The park, under its teacher name (FR-CONSOLE-47): every parked paper with its
    reason, the student it matched (or why it could not), and the resolutions available —
    mirrored exactly from the quarantine rows the ledgers hold, counted as they hold them."""
    del console, query
    before = _skipped_before(app)
    rows = app._read_cohort_files(Q._SELECT_PARKED_PAPERS, [])
    parked: list[dict[str, Any]] = []
    by_reason: dict[str, int] = {}
    classes: dict[str, dict[str, Any]] = {}
    for row in rows:
        status = str(row["ingest_status"])
        by_reason[status] = by_reason.get(status, 0) + 1
        identity = str(row["v3_identity"] or "").strip()
        # A paper the identity check did not pass carries a placeholder ref ('unknown'), not
        # a student: it matched nobody, whatever the column holds.
        student_ref = (str(row["student_ref"] or "").strip() or None) \
            if identity == "pass" else None
        duplicate_of = None
        if identity == "already_has_paper":
            # FR-INGEST-41: a second paper for a student who already has one. Named with
            # the student it matched and the earlier paper, so the teacher keeps one.
            duplicate_of = _earlier_paper(app, str(row["cohort_id"]),
                                          str(row["student_ref"] or ""),
                                          str(row["submission_id"]))
            student_ref = duplicate_of["student_ref"]
            match_note = (
                f"This paper matched {duplicate_of['full_name'] or student_ref}, who already "
                "has a paper in this class. Keep one of the two: remove this scan, or use it "
                "instead of the earlier one.")
        elif student_ref:
            match_note = f"The paper matched {_name_of(app, cohort_id_of(row), student_ref)}."
        else:
            match_note = (
                "No student could be matched to this paper"
                + (f" (recorded as {identity!r})." if identity else ".")
            )
        cohort_id = str(row["cohort_id"])
        if cohort_id not in classes:
            classes[cohort_id] = _parked_class_facts(app, cohort_id)
        facts = classes[cohort_id]
        submission_id = str(row["submission_id"])
        parked.append({
            "submission_id": submission_id,
            "cohort_id": cohort_id,
            "reason": "already_has_paper" if duplicate_of is not None else status,
            "reason_label": ("A second paper for a student who already has one"
                             if duplicate_of is not None
                             else _INGEST_STATUS_LABELS.get(status, status)),
            "matched_student": student_ref,
            "matched_name": (_name_of(app, cohort_id, student_ref) if student_ref else None),
            "match_note": match_note,
            "resolutions": list(_DUPLICATE_RESOLUTIONS if duplicate_of is not None
                                else _PARKED_RESOLUTIONS.get(
                                    status, ("Open the parked page to resolve this paper.",))),
            "resolvable": status in QUARANTINE_STATES or duplicate_of is not None,
            # B8: a paper whose student was not matched (but whose pages were read) can be
            # given to the student it belongs to — one of the class's students with no paper.
            # A second copy becomes assignable once the student's earlier paper is gone.
            "assignable": (status in QUARANTINE_STATES or duplicate_of is not None)
            and identity not in (
                "pass", "not_reached") and not (
                duplicate_of is not None and duplicate_of["submission_id"] is not None),
            # A second copy can only be removed or used instead of the first; closing it
            # would grade it INCOMPLETE beside the student's real paper.
            "duplicate_of": duplicate_of,
            "students_without_paper": facts["students_without_paper"],
            "decisions": [d for d in facts["decisions"] if d["submission_id"] == submission_id],
        })
    return {
        "parked": parked,
        "counts": {"total": len(parked), "by_reason": by_reason},
        "projected": _projected(app, before, parked=len(parked)),
    }
