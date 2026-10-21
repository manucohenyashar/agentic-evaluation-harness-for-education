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

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from aeh.grade import GRADE_STATEMENTS, run_grade_records
from aeh.pkg import PKG_STATEMENTS, points_for_band
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
    try:
        roster = list(handle.query(
            "SELECT student_ref, full_name FROM roster ORDER BY student_ref"))
    except Exception:  # noqa: BLE001 — a cohort without a roster table answers its papers
        roster = []
    # A read paper keeps its student's listed name beside the ref, so the class screen
    # still says who the paper belongs to once it is in.
    names = {str(row["student_ref"]): str(row["full_name"] or "") or None for row in roster}
    for row in handle.query(
        "SELECT submission_id, student_ref, v3_identity FROM submission "
        "ORDER BY submission_id"
    ):
        ref = str(row["student_ref"])
        # One row per student: a paper parked as a second copy of a student's paper
        # (FR-INGEST-41) and a paper no student was matched to ('unknown', or a ref the list
        # does not hold) are the Parked screen's, never a second or phantom student here.
        if ref in seen or (names and ref not in names) or ref == "unknown" or str(
                row["v3_identity"] or "pass") not in ("pass",):
            continue
        seen.add(ref)
        students.append({"student_ref": ref, "submission_id": str(row["submission_id"]),
                         "full_name": names.get(ref)})
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
    cohorts = []
    for key in app._cohort_keys():
        if not _ledger_is_live(app, key):
            continue
        students = _students_of(app, key)
        cohorts.append({
            "cohort_id": key,
            "students": students,
            # FR-CONSOLE-69: the check a teacher makes against their own class list — how
            # many are listed, how many papers are in, and exactly who has none yet.
            "summary": _class_summary(students),
            **_class_standing(app, key),
        })
    return {"cohorts": cohorts}


def _graded_papers(handle: Any) -> set[str]:
    """The papers any grading run has touched (work, a score, a grade, feedback or a review
    row) — M-STORE's `discard_ungraded_paper` refuses exactly these."""
    graded: set[str] = set()
    for statement in _GRADED_PAPER_READS:
        try:
            graded |= {str(row["submission_id"]) for row in handle.query(statement)}
        except Exception:  # noqa: BLE001 — a ledger without the table has nothing there
            continue
    return graded


#: Every table a grading run writes a paper's rows into, one declared read each.
_GRADED_PAPER_READS: tuple[str, ...] = (
    "SELECT DISTINCT submission_id FROM work_unit",
    "SELECT DISTINCT submission_id FROM criterion_score",
    "SELECT DISTINCT submission_id FROM submission_grade",
    "SELECT DISTINCT submission_id FROM narrative",
    "SELECT DISTINCT submission_id FROM review_queue",
)


def _class_summary(students: list[dict[str, Any]]) -> dict[str, Any]:
    without = [s for s in students if s["submission_id"] is None]
    names = [str(s["full_name"] or "").casefold() for s in students if s["full_name"]]
    shared = {name for name in names if names.count(name) > 1}

    def label(student: dict[str, Any]) -> str:
        # FR-UI-22: the name first; the ref only to tell two students of one name apart.
        name = student["full_name"] or student["student_ref"]
        if student["full_name"] and str(student["full_name"]).casefold() in shared:
            return f"{name} ({student['student_ref']})"
        return str(name)

    return {
        "listed": len(students),
        "with_paper": len(students) - len(without),
        "without_paper": sorted((label(s) for s in without), key=str.casefold),
    }


def _class_standing(app: Any, key: str) -> dict[str, Any]:
    """What a class's corrections may still touch (FR-CONSOLE-64..68): its consent class, how
    many grading runs it has, how many of its papers a run has graded, and whether it can be
    deleted outright — a class that never held a paper or a run — so the screen says *before*
    the teacher asks what a delete would do."""
    handle = app._store.cohort(key)
    try:
        consent = handle.query("SELECT consent_class FROM cohort")
        consent_class = str(consent[0]["consent_class"]) if consent else None
    except Exception:  # noqa: BLE001 — an unreadable row is shown as unknown
        consent_class = None
    try:
        runs = int(handle.query("SELECT COUNT(*) AS n FROM run")[0]["n"])
        papers = int(handle.query("SELECT COUNT(*) AS n FROM submission")[0]["n"])
        graded = len(_graded_papers(handle))
    except Exception:  # noqa: BLE001 — a ledger without the grading tables has graded nothing
        runs, graded = 0, 0
        papers = 0
    return {
        "consent_class": consent_class,
        "runs": runs,
        "papers": papers,
        "graded_papers": graded,
        "deletable": runs == 0 and papers == 0,
    }


def _roster_names(handle: Any) -> dict[str, str | None]:
    """A class's listed names by student ref; an unreadable roster answers none."""
    try:
        return {str(row["student_ref"]): (str(row["full_name"] or "") or None)
                for row in handle.query("SELECT student_ref, full_name FROM roster")}
    except Exception:  # noqa: BLE001 — names are a convenience beside the refs
        return {}


def _ledger_is_live(app: Any, key: str) -> bool:
    """Whether a cohort file still holds its cohort: a purge empties every table but leaves
    the compacted file, so a deleted class must not be listed again under its old name. An
    unreadable file is listed (its own read reports the trouble)."""
    try:
        return bool(app._store.cohort(key).query("SELECT COUNT(*) AS n FROM cohort")[0]["n"])
    except Exception:  # noqa: BLE001 — listed, and its own read names the problem
        return True


def papers_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The papers screen's document (FR-UI-03c): the cohort's students and the scan parts
    already uploaded, in assembled order — the preflight state the server-rendered upload
    screen shows, through M-PIPE's `uploaded_parts`."""
    # Through `aeh.pipeline`'s re-export, the spelling the server-rendered screens already
    # use — `aeh.pipeline.background` at symbol level would add an undeclared edge to the
    # frozen set (`TC-CONSOLE-36`) for the same door.
    from aeh.pipeline import cohort_has_test_paper, uploaded_parts

    run_row = _run_row_of(console, app, query)
    cohort_id = str(query.get("cohort_id") or "")
    if not cohort_id and run_row is not None:
        cohort_id = str(run_row["cohort_id"])
    if not cohort_id:
        keys = app._cohort_keys()
        cohort_id = keys[0] if keys else ""
    if not cohort_id:
        raise ValueError("no class exists yet: set up a class first, then load its papers")
    students = _students_of(app, cohort_id)
    standing = _class_standing(app, cohort_id)
    return {
        "cohort_id": cohort_id,
        "students": students,
        "summary": _class_summary(students),
        # FR-CONSOLE-68: the test paper can be replaced while no paper here is graded.
        "graded_papers": standing["graded_papers"],
        "parts": list(uploaded_parts(app._store, cohort_id)),
        # B4: what the papers screen needs to read papers here — whether the class holds
        # its test paper yet (the sheets are checked against it), and every sheet read so
        # far with what the paper check said.
        "test_paper_read": bool(cohort_has_test_paper(app._store, cohort_id)),
        "sheets": _sheets_of(app, cohort_id),
    }


def _sheets_of(app: Any, cohort_id: str) -> list[dict[str, Any]]:
    """The answer sheets read into one cohort, oldest first: each with the student it was
    matched to, its paper-check status and whether it is parked (`FR-INGEST-30`'s flag)."""
    from .vocabulary import QUARANTINE_STATES

    sheets: list[dict[str, Any]] = []
    handle = app._store.cohort(cohort_id)
    try:
        rows = list(handle.query(
            "SELECT submission_id, student_ref, ingest_status, quarantined, v3_identity "
            "FROM submission ORDER BY rowid"))
    except Exception:  # noqa: BLE001 — an unreadable ledger lists no sheets, not a 500
        return sheets
    try:
        names = {str(row["student_ref"]): row["full_name"] for row in handle.query(
            "SELECT student_ref, full_name FROM roster")}
    except Exception:  # noqa: BLE001 — a ledger without names lists refs
        names = {}
    # A paper is part of a run's record once any run touched it — the rule M-STORE's
    # `discard_ungraded_paper` refuses on, so the screen never offers a removal it refuses.
    graded = _graded_papers(handle)
    for row in rows:
        status = str(row["ingest_status"] or "")
        ref = None if row["student_ref"] is None else str(row["student_ref"])
        matched = str(row["v3_identity"] or "pass") == "pass"
        sheets.append({
            "submission_id": str(row["submission_id"]),
            "student_ref": ref,
            # FR-CONSOLE-66/67: the name the paper is filed under (when a student was
            # matched), whether a run has graded it (a graded paper can be moved, never
            # removed), and whether it is a matched paper the teacher may move.
            "full_name": (names.get(ref) if ref is not None else None) or None,
            "matched": matched and ref not in (None, "unknown"),
            "graded": str(row["submission_id"]) in graded,
            "status": status or "reading",
            "parked": bool(row["quarantined"]) or status in QUARANTINE_STATES,
        })
    return sheets


# --- the run-bound screens ------------------------------------------------------------------------


def run_start_state_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The run-start screen's context (FR-UI-03d): the run the console serves — cohort,
    package version, status — beside the preview read (`run start preview`), which names the
    profile and refuses on its own. The context answers even when the preview cannot be
    composed: the teacher still sees what would start."""
    run_row = _run_row_of(console, app, query)
    # The profile a run started here runs under: the console's own, which the screen names
    # when it asks for a new run's priced preview (FR-CONSOLE-43 names the profile per
    # request; the console's is the one a teacher can start under).
    config = app.run_config if isinstance(getattr(app, "run_config", None), dict) else {}
    profile = str(config.get("HARNESS_PROFILE") or "") or None
    if run_row is None:
        return {"run_id": None, "cohort_id": None, "package_version_id": None,
                "status": None, "profile": profile}
    return {
        "run_id": str(run_row["run_id"]),
        "cohort_id": str(run_row["cohort_id"]),
        "package_version_id": str(run_row["package_version_id"]),
        "status": str(run_row["status"]),
        "profile": profile,
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
    # FR-UI-22: each flagged answer names its student the way the teacher knows them, and
    # its grading point by the question's own label.
    run_row = _run_row_of(console, app, {"run_id": run_id})
    if run_row is not None:
        handle = app._store.cohort(str(run_row["cohort_id"]))
        names = _roster_names(handle)
        try:
            refs = {str(row["submission_id"]): str(row["student_ref"]) for row in handle.query(
                "SELECT submission_id, student_ref FROM submission")}
        except Exception:  # noqa: BLE001 — a row then names its paper alone
            refs = {}
        labels = _grading_point_labels(app, run_row)
        for item in payload["shown"]:
            ref = refs.get(item["submission_id"])
            item["student_ref"] = ref
            item["full_name"] = names.get(ref) if ref is not None else None
            item["label"] = labels.get(item["criterion_id"], item["criterion_id"])
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
    names = _roster_names(app._store.cohort(cohort_id)) if cohort_id else {}
    # Each seat's own scale: the package's declared levels for that grading point, the names
    # M-REVIEW maps a submitted label through — the rubric, not system output, so the blind
    # stays blind. A generic label the criterion does not declare is refused by the review
    # service, so offering only `REVIEW_DEFAULT_BANDS` blocked every custom-band package;
    # the generic scale remains the fallback for a seat whose package cannot be read.
    scales = _declared_scales(app, run_row) if run_row is not None else {}
    labels = _grading_point_labels(app, run_row) if run_row is not None else {}
    return {
        "run_id": run_id,
        "band_scale": [str(band["band"]) for band in REVIEW_DEFAULT_BANDS],
        "seats": [
            {
                "submission_id": str(item.submission_id),
                "student_ref": refs.get(str(item.submission_id)),
                # The teacher knows the student by name (the blind hides the system's
                # verdict, never whose paper it is).
                "full_name": names.get(refs.get(str(item.submission_id), "")),
                "criterion_id": str(item.criterion_id),
                "label": labels.get(str(item.criterion_id), str(item.criterion_id)),
                "band_scale": [name for name, _points in
                               scales.get(str(item.criterion_id), ())] or None,
                "evaluation_mode": str(getattr(item, "evaluation_mode", "") or ""),
            }
            for item in session.items
        ],
    }


# --- the results screens ---------------------------------------------------------------------------

#: The results reads' cell query: the criterion-score rows a run holds, with the routing
#: and state the aggregation wrote beside the band. One parameterized select over the same
#: table `GRADE_STATEMENTS["select_run_criterion_bands"]` reads — a wider column list, not a
#: second rule about which rows exist. (`TC-STORE-15`'s banned shape is a search, never a
#: keyed select.)
_CELL_ROWS_SQL = (
    "SELECT cs.criterion_id, cs.submission_id, cs.band, cs.routing, cs.state, cs.state_reason "
    "FROM criterion_score cs "
    "JOIN submission s ON cs.submission_id = s.submission_id "
    "WHERE cs.run_id = :run_id AND s.cohort_id = :cohort_id "
    "ORDER BY cs.criterion_id, cs.submission_id"
)

#: The run's escalation panels, per cell: the widenings M-ORCH wrote (`stage='score'`,
#: `origin='escalation'`), read as (submission, criterion) pairs — the second-opinion
#: markers the results overview flags. Keyed, not searched (`TC-STORE-15`).
_ESCALATED_CELLS_SQL = (
    "SELECT DISTINCT submission_id, criterion_id FROM work_unit "
    "WHERE run_id = :run_id AND stage = 'score' AND origin = 'escalation'"
)

#: One cell's grader verdicts (FR-JUDGE-18, CT-JUDGE-20) — the same row shape and `work_id`
#: order M-JUDGE's own statement answers. Inlined because the console's `aeh.*` import set
#: is frozen (`CT-CONSOLE-36`): the read borrows the ledger's schema, not M-JUDGE's module.
_CELL_VERDICTS_SQL = (
    "SELECT v.work_id, v.judge_id, v.band, v.cited_spans FROM verdict v "
    "JOIN work_unit w ON w.work_id = v.work_id "
    "WHERE w.run_id = :run_id AND w.submission_id = :submission_id "
    "AND w.criterion_id = :criterion_id ORDER BY v.work_id"
)


def _declared_scales(app: Any, run_row: Any) -> dict[str, list[tuple[str, Any]]]:
    """The run's package version's declared score levels, per grading point, in the
    package's own ordinal order — each entry `(name, points)`. This is the x-axis the
    distribution renders and the scale the override's selection offers (FR-UI-15, FR-UI-17):
    the declaration, never a client-side sort. An unreadable package answers `{}` and the
    screens degrade to the rows they hold, never to an invented scale."""
    try:
        package = app._store.package(str(run_row["package_id"]))
        rows = package.query(
            PKG_STATEMENTS["select_bands"], v=str(run_row["package_version_id"]))
    except Exception:  # noqa: BLE001 — an unreadable catalog is not the grades'
        return {}
    by_criterion: dict[str, list[Any]] = {}
    for row in rows:
        by_criterion.setdefault(str(row["criterion_id"]), []).append(dict(row))
    # Each level's points through M-PKG's one band-to-points reader (CT-PKG-05), never the
    # column itself: the console maps an amended figure back to its level with them.
    return {
        criterion: [(str(row["band"]), points_for_band(entries, str(row["band"])))
                    for row in sorted(entries, key=lambda row: int(row["ordinal"]))]
        for criterion, entries in by_criterion.items()
    }


def _answer_keys(app: Any, run_row: Any, labels: dict[str, str]) -> list[dict[str, Any]]:
    """The run's multiple-choice grading points with their options and current key — what
    the results screen's key correction offers (FR-CONSOLE-30: a key found wrong after a run
    is corrected and the marks re-derived). Read through M-PKG's own catalog; an unreadable
    package offers no correction rather than an invented one."""
    from aeh.pkg import PackageCatalog

    package_id = str(run_row["package_id"])
    version = str(run_row["package_version_id"])
    try:
        catalog = PackageCatalog(app._store.package(package_id), package_id=package_id)
        keys = []
        for criterion in catalog.criteria(version):
            criterion_id = str(criterion["criterion_id"])
            options = catalog.mcq_options(version, criterion_id)
            if not options:
                continue
            keys.append({
                "criterion_id": criterion_id,
                "label": labels.get(criterion_id, criterion_id),
                "options": [{"option_id": str(option_id), "label": str(label or "")}
                            for option_id, label in options],
                # The run's OWN version's key — what the correction compares against — not
                # the newest in the lineage (another class's correction moves that one).
                "key": _key_ids(criterion["answer_key"]),
            })
        return keys
    except Exception:  # noqa: BLE001 — no correction offered over an unreadable catalog
        return []


def _key_ids(raw: Any) -> list[str]:
    """A stored answer key (`criterion.answer_key`, a JSON list of option ids) as a list."""
    if raw is None:
        return []
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []
    return [str(option) for option in value] if isinstance(value, (list, tuple)) else [str(value)]


def _grading_point_labels(app: Any, run_row: Any) -> dict[str, str]:
    """Each grading point's teacher label (`CT-CONSOLE-31` — an internal criterion id is
    never the only name a screen shows): the question the grading point grades, as the
    package's stored `question_id` spells it, falling back to the id the read carries. An
    unreadable catalog answers empty and the screens fall back to the id alone."""
    try:
        package = app._store.package(str(run_row["package_id"]))
        rows = package.query(
            "SELECT criterion_id, question_id FROM criterion "
            "WHERE package_version_id = :v ORDER BY criterion_id",
            v=str(run_row["package_version_id"]),
        )
    except Exception:  # noqa: BLE001 — an unreadable catalog is not the grades'
        return {}
    return {
        str(row["criterion_id"]): str(row["question_id"] or "") or str(row["criterion_id"])
        for row in rows
    }


def _level_of(scale: list[tuple[str, Any]], points: Any) -> str | None:
    """The declared score level whose points a recorded figure is, or `None` when no
    declared level carries it (an amendment recorded off-scale points is shown as the
    stored level, never as a number the scale does not name)."""
    for name, band_points in scale:
        try:
            if band_points is not None and float(band_points) == float(points):
                return name
        except (TypeError, ValueError):
            continue
    return None


def _amendments_of_run(cohort_handle: Any, run_id: str) -> dict[str, list[dict[str, Any]]]:
    """Each submission's current grade revision's amendment entries (M-GRADE's own
    `select_current_grades_for_run` rows), keyed by submission — who, when, and why, as
    the ledger records them. An unreadable column answers empty, never an error."""
    try:
        rows = cohort_handle.query(
            GRADE_STATEMENTS["select_current_grades_for_run"], run_id=run_id)
    except Exception:  # noqa: BLE001 — a ledger without the column answers empty
        return {}
    history: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        raw = row["amendments"]
        if not raw:
            continue
        try:
            entries = json.loads(str(raw))
        except (TypeError, ValueError):
            continue
        if not isinstance(entries, list):
            continue
        history[str(row["submission_id"])] = [
            entry for entry in entries if isinstance(entry, dict)
        ]
    return history


def _grader_labels() -> dict[str, str]:
    """The label registry a detail read hands its judges through (`CT-CONSOLE-31`): the
    internal judge id is never rendered — its ordinal is. The ordinal is the judge's place
    in the read's own first-seen order (criteria in criterion order, verdicts in `work_id`
    order), never digits scraped out of the id: a build-id fragment is not a number a
    teacher can read, and two ids can share a digit set."""
    return {}


def _grader_label(registry: dict[str, str], judge_id: str) -> str:
    label = registry.get(judge_id)
    if label is None:
        label = f"Grader {len(registry) + 1}"
        registry[judge_id] = label
    return label


def _state_reason_text(raw: str) -> str:
    """The aggregate's stored state reason in the teacher's words (`CT-CONSOLE-31`): the
    reasons the store carries are codes, and a snake_case code is not plain language.
    An unknown code passes through unchanged — an unmapped code names its value rather
    than inventing a story for it."""
    reasons = {
        "even_panel_after_quarantine":
            "the graders were split on this grading point, so the panel's verdict was "
            "held for the teacher's review",
    }
    return reasons.get(raw, raw)


def _cell_flag(routing: str, state: str, escalated: bool) -> str | None:
    """The one flag a cell raises for the overview's flagged list (FR-UI-15), strongest
    first: a second opinion (M-ORCH widened the panel), then a low-confidence verdict (the
    aggregation queued it for the teacher), then a not-final grade. `None` means the cell
    raises nothing."""
    if escalated:
        return "second_opinion"
    if routing == "queued":
        return "low_confidence"
    if state == "provisional_unreviewed":
        return "not_final"
    return None


#: FR-CONSOLE-75: the timed stages in run order, each with the name the teacher reads. The
#: stage is the suffix of M-PIPE's `run_metrics` row `stage_seconds.<stage>`.
STAGE_TIMING_LABELS: tuple[tuple[str, str], ...] = (
    ("extract", "Reading answers"),
    ("judge", "AI grading"),
    ("aggregate", "Combining grades"),
    ("synth", "Writing feedback"),
)

_STAGE_SECONDS_SQL = (
    "SELECT metric, value FROM run_metrics WHERE run_id = :run_id "
    "AND metric LIKE 'stage_seconds.%' "
    "AND submission_id = '' AND criterion_id = '' AND judge_id = ''"
)


def _stage_timings(app: Any, run_id: str) -> list[dict[str, Any]]:
    """The run's `stage_timings` (FR-CONSOLE-75): `{stage, label, seconds}` in run order,
    for the stages M-PIPE timed. A stage with no row did not run and is not listed — never
    shown as 0. An unreadable metrics table answers no timings, not a failed screen."""
    try:
        rows = app._store.durable().query(_STAGE_SECONDS_SQL, run_id=run_id)
    except Exception:  # noqa: BLE001 — timings are a footnote to the grades, never a 500
        return []
    seconds = {
        str(row["metric"]).removeprefix("stage_seconds."): float(row["value"])
        for row in rows if str(row["metric"]).startswith("stage_seconds.")
    }
    return [
        {"stage": stage, "label": label, "seconds": seconds[stage]}
        for stage, label in STAGE_TIMING_LABELS if stage in seconds
    ]


def results_screen_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The results screen's document (FR-UI-03g, extended by FR-UI-15): every student's
    grade record (M-GRADE's own, the ledger's) beside the run's per-criterion score levels,
    each carrying its routing, its state and its flag; the package's declared score levels
    order the distribution and name the overrides' selections.

    A level shown is the effective one: a grade the teacher amended shows the amended
    level, with the aggregation's own level beside it as `stored_band` — the ledger keeps
    both, and the overview must not show a grade the ledger superseded. No count or share
    is derived here: the SPA aggregates the rows this document serves (`CT-UI-08`)."""
    run_row = _run_row_of(console, app, query)
    if run_row is None:
        return {"run_id": None, "cohort_id": None, "score_levels": [], "scales": [],
                "students": [], "stage_timings": []}
    run_id = str(run_row["run_id"])
    cohort_id = str(run_row["cohort_id"])
    records = run_grade_records(app._store, run_id)
    by_submission: dict[str, dict[str, Any]] = {}
    for record in records:
        by_submission[str(record["submission_id"])] = {
            "submission_id": str(record["submission_id"]),
            "student_ref": None,
            "full_name": None,
            "total": record["total"],
            "state": str(record["state"] or ""),
            "criteria": [],
        }
    handle = app._store.cohort(cohort_id)
    scales = _declared_scales(app, run_row)
    labels = _grading_point_labels(app, run_row)
    amendments = _amendments_of_run(handle, run_id)
    escalated: set[tuple[str, str]] = set()
    try:
        escalated = {
            (str(row["submission_id"]), str(row["criterion_id"]))
            for row in handle.query(_ESCALATED_CELLS_SQL, run_id=run_id)
        }
    except Exception:  # noqa: BLE001 — a ledger without the work units flags nothing
        escalated = set()
    try:
        cells = handle.query(_CELL_ROWS_SQL, run_id=run_id, cohort_id=cohort_id)
    except Exception:  # noqa: BLE001 — a cohort ledger without the rows answers grades alone
        cells = ()
    for row in cells:
        student = by_submission.get(str(row["submission_id"]))
        if student is None:
            continue
        criterion_id = str(row["criterion_id"])
        scale = scales.get(criterion_id, [])
        stored_band = str(row["band"])
        criterion_band = stored_band
        for points in [entry.get("points") for entry in amendments.get(
                str(row["submission_id"]), []) if entry.get("criterion_id") == criterion_id]:
            amended_level = _level_of(scale, points)
            if amended_level is not None:
                criterion_band = amended_level
        student["criteria"].append({
            "criterion_id": criterion_id,
            "label": labels.get(criterion_id, criterion_id),
            "criterion_band": criterion_band,
            "stored_band": stored_band,
            "routing": str(row["routing"] or ""),
            "state": str(row["state"] or ""),
            "state_reason": _state_reason_text(str(row["state_reason"] or "")),
            "flag": _cell_flag(str(row["routing"] or ""), str(row["state"] or ""),
                               (str(row["submission_id"]), criterion_id) in escalated),
        })
    try:
        refs = {
            str(row["submission_id"]): str(row["student_ref"])
            for row in handle.query(
                "SELECT submission_id, student_ref FROM submission")
        }
    except Exception:  # noqa: BLE001 — the ref column's absence is not the grades'
        refs = {}
    names = _roster_names(handle)
    for submission_id, ref in refs.items():
        if submission_id in by_submission:
            by_submission[submission_id]["student_ref"] = ref
            # FR-CONSOLE-70: the teacher finds a student by the name on their list.
            by_submission[submission_id]["full_name"] = names.get(ref)
    # The distribution's x-axis: the declared levels in the package's own order, merged
    # across the run's grading points (a level two criteria both declare appears once).
    seen_levels: dict[str, tuple[int, str]] = {}
    for criterion, entries in scales.items():
        for position, (name, _points) in enumerate(entries):
            rank = (position, name)
            if name not in seen_levels or rank < seen_levels[name]:
                seen_levels[name] = rank
    score_levels = [name for name, _rank in sorted(seen_levels.items(), key=lambda item: item[1])]
    return {
        "run_id": run_id,
        "cohort_id": cohort_id,
        # The test version the run graded against: the screen's download of the test
        # itself (FR-CONSOLE-59's readable export) names it.
        "package_version_id": str(run_row["package_version_id"]),
        "answer_keys": _answer_keys(app, run_row, labels),
        "score_levels": score_levels,
        "scales": [
            {"criterion_id": criterion, "label": labels.get(criterion, criterion),
             "levels": [name for name, _points in entries]}
            for criterion, entries in sorted(scales.items())
        ],
        "students": list(by_submission.values()),
        # FR-CONSOLE-75: how long each long step of this run took, in run order.
        "stage_timings": _stage_timings(app, run_id),
    }


def student_detail_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """One student's detail (FR-UI-03g, extended by FR-UI-16/17): their grade record, their
    narrative — the text M-SYNTH wrote — and, per grading point, the justification the
    engineering trail grounds: the aggregate's own state reason, and each grader's verdict
    with the evidence spans it cited, read from the verdict ledger in M-JUDGE's `work_id`
    order (`FR-JUDGE-18`). The teacher-facing amendment history rides the grade's own
    ledger entries — who, when, and why, with the level each amendment moved the grade
    from and to. Refuses a read that names no submission (the caller's mistake, a 400)."""
    submission_id = str(query.get("submission_id") or "")
    run_row = _run_row_of(console, app, query)
    if run_row is None:
        raise ValueError("student detail names no run")
    if not submission_id:
        raise ValueError("student detail names no submission")
    run_id = str(run_row["run_id"])
    cohort_id = str(run_row["cohort_id"])
    record = next(
        (r for r in run_grade_records(app._store, run_id)
         if str(r["submission_id"]) == submission_id),
        None,
    )
    student_ref = None
    narrative: list[dict[str, Any]] = []
    criteria: list[dict[str, Any]] = []
    amendment_history: list[dict[str, Any]] = []
    handle = app._store.cohort(cohort_id)
    try:
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
                r=run_id, s=submission_id,
            )
        ]
    except Exception:  # noqa: BLE001 — a ledger without the tables answers the grade alone
        pass
    scales = _declared_scales(app, run_row)
    labels = _grading_point_labels(app, run_row)
    amendment_entries = _amendments_of_run(handle, run_id).get(submission_id, [])
    escalation_pairs: set[tuple[str, str]] = set()
    try:
        escalation_pairs = {
            (str(row["submission_id"]), str(row["criterion_id"]))
            for row in handle.query(_ESCALATED_CELLS_SQL, run_id=run_id)
            if str(row["submission_id"]) == submission_id
        }
    except Exception:  # noqa: BLE001 — a ledger without the work units flags nothing
        escalation_pairs = set()
    try:
        cells = handle.query(
            "SELECT criterion_id, band, routing, state, state_reason FROM criterion_score "
            "WHERE run_id = :run_id AND submission_id = :submission_id "
            "ORDER BY criterion_id",
            run_id=run_id, submission_id=submission_id,
        )
    except Exception:  # noqa: BLE001 — a ledger without the scores answers the grade alone
        cells = ()
    grader_registry = _grader_labels()
    for row in cells:
        criterion_id = str(row["criterion_id"])
        scale = scales.get(criterion_id, [])
        stored_band = str(row["band"])
        criterion_band = stored_band
        for entry in amendment_entries:
            if str(entry.get("criterion_id") or "") == criterion_id:
                amended_level = _level_of(scale, entry.get("points"))
                if amended_level is not None:
                    criterion_band = amended_level
        graders: list[dict[str, Any]] = []
        try:
            verdict_rows = handle.query(
                _CELL_VERDICTS_SQL, run_id=run_id,
                submission_id=submission_id, criterion_id=criterion_id)
        except Exception:  # noqa: BLE001 — a cell without verdicts shows the aggregate alone
            verdict_rows = ()
        for vrow in verdict_rows:
            cited: list[str] = []
            raw_spans = vrow["cited_spans"]
            if raw_spans:
                try:
                    parsed = json.loads(str(raw_spans))
                except ValueError:
                    parsed = []
                if isinstance(parsed, list):
                    cited = [str(span.get("text") or "") for span in parsed
                             if isinstance(span, dict) and span.get("text")]
            graders.append({
                "grader": _grader_label(grader_registry, str(vrow["judge_id"])),
                "score_level": str(vrow["band"]),
                "cited": cited,
            })
        criteria.append({
            "criterion_id": criterion_id,
            "label": labels.get(criterion_id, criterion_id),
            "criterion_band": criterion_band,
            "stored_band": stored_band,
            "routing": str(row["routing"] or ""),
            "state": str(row["state"] or ""),
            "state_reason": _state_reason_text(str(row["state_reason"] or "")),
            "flag": _cell_flag(str(row["routing"] or ""), str(row["state"] or ""),
                               (submission_id, criterion_id) in escalation_pairs),
            "levels": [name for name, _points in scale],
            "graders": graders,
        })
    # The current revision's amendment entries, rendered with the level each moved the
    # grade from (the aggregation's stored level — M-GRADE never writes criterion scores)
    # and to (the declared level the amended points name). The pair is what the teacher
    # sentence renders back ("Final grade changed from 'X' to 'Y' — reason recorded").
    for entry in amendment_entries:
        criterion_id = str(entry.get("criterion_id") or "")
        scale = scales.get(criterion_id, [])
        stored = next((c["stored_band"] for c in criteria
                       if c["criterion_id"] == criterion_id), "")
        amendment_history.append({
            "criterion_id": criterion_id,
            "from_band": stored,
            "to_band": _level_of(scale, entry.get("points")) or "",
            "actor": str(entry.get("actor") or ""),
            "reason": str(entry.get("reason") or ""),
            "at": str(entry.get("at") or ""),
        })
    return {
        "run_id": run_id,
        "submission_id": submission_id,
        "student_ref": student_ref,
        "full_name": _roster_names(handle).get(student_ref) if student_ref else None,
        "total": None if record is None else record["total"],
        "state": None if record is None else str(record["state"] or ""),
        "narrative": narrative,
        "criteria": criteria,
        "amendments": amendment_history,
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

