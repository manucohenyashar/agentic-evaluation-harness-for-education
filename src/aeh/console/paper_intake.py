"""Reading uploaded papers from the console (live-test blocker B4, design delta §3.2.3).

The papers upload is "the existing PDF scan staging path, multi-file, with the paper check
naming rejections in plain language and parking what fails". Before this module the upload
route staged the scan's chunks and recorded its file name, and nothing ever read it: reading
the papers took `aeh ingest` in a terminal. This module is the missing half, and it adds no
write path of its own — the upload stays the one non-control mutation the API carries
(`FR-CONSOLE-04`), and the read is `aeh ingest`'s own door (`aeh.pipeline.read_uploaded_paper`
over `ingest_files`), so the console and the command line read a paper identically.

The shape follows the authoring draft job (`authoring_actions`):

* **Checked before a byte is staged.** An upload that asks to be read names its class, the
  published test version it is read against and whether it is the test paper or an answer
  sheet; an unknown class or version, or a class whose consent forbids this profile's
  page reader (`FR-CONF-08`), is refused before the body is read.
* **No long work in the request handler** (`FR-CONSOLE-04`): the handler queues the staged
  file and returns. One worker thread per class drains that class's queue in arrival order —
  so the test paper the screen sends first is read before the sheets that need it — opening
  its own store (a SQLite connection belongs to its thread).
* **Progress is a job** (`ADR-47`): one `paper_intake` job per worker, its `done`/`total`
  counting files and its `current` line naming the last file and what the check said. Files
  queued while the worker runs join its job; the next upload after it finishes starts a new
  one. The jobs registry is console memory; the papers' state is the submission rows.

Nothing here reaches the provider directly or writes SQL; no document byte reaches a detail
message, a log line or a URL (`CT-CONSOLE-34`) — the file name is the teacher's own label.
"""

from __future__ import annotations

import collections
import threading
from typing import Any, Mapping

from .html import _now
from .spa_reads import _strip_exception_name

#: The job kind the registry and the jobs page carry for a papers read.
INTAKE_JOB_KIND = "paper_intake"

#: What an uploaded paper may be: the class's test paper, or one student's answer sheet.
PAPER_KINDS: tuple[str, ...] = ("assessment", "sheet")

#: The upload query flag that asks for the read, in the forms a query string spells "yes".
_TRUE_WORDS = frozenset({"1", "true", "yes", "on"})

#: The intake statuses that leave a paper readable by the grading run (`FR-INGEST-29`):
#: everything else is parked for the operator.
_ADMITTED_STATUSES = frozenset({"ok", "low_confidence_ocr"})


def wants_read(query: Mapping[str, Any]) -> bool:
    """Whether an upload asked to be read as it lands (`read=1`)."""
    return str(query.get("read") or "").strip().lower() in _TRUE_WORDS


def check_paper_upload(app: Any, query: Mapping[str, Any]) -> str | None:
    """The refusal an upload that asks to be read earns before any byte is staged, or `None`.

    Every check is a look, never a write: the class and the version are matched against what
    the store already holds (an unknown id's open would CREATE its tier file), and the consent
    gate resolves the configuration exactly as `aeh ingest` does."""
    from aeh.pipeline import resolve_intake_config

    store = getattr(app, "_store", None)
    if store is None or getattr(store, "data_dir", None) is None:
        return "no data folder is attached to the console, so a paper cannot be read."
    kind = str(query.get("kind") or "")
    if kind not in PAPER_KINDS:
        return ("say whether the file is the test paper or an answer sheet, then upload it "
                "again. Nothing was stored.")
    filename = str(query.get("filename") or "").strip()
    if not filename:
        return "the upload carries no file name. Choose the file again. Nothing was stored."
    cohort_id = str(query.get("cohort_id") or "")
    if cohort_id not in app._cohort_keys():
        return (f"no class named {cohort_id!r} exists. Make the class first, then upload "
                "the papers. Nothing was stored.")
    package_version = str(query.get("package_version") or "")
    if not package_version or app._package_of(package_version) == "":
        return ("choose the published test these papers answer, then upload them again. "
                "Nothing was stored.")
    try:
        resolve_intake_config(store, _intake_config(app), cohort_id)
    except Exception as refusal:  # noqa: BLE001 - the consent gate's own wording
        return (f"these papers cannot be read under this console's settings: "
                f"{_strip_exception_name(refusal)} Nothing was stored.")
    return None


def _intake_config(app: Any) -> dict[str, Any]:
    """The configuration a paper is read under: the console's own effective one, composed
    the way a run started here is composed — never a console-private spelling."""
    from .run_start import compose_run_start_config

    return compose_run_start_config(app, {})


def queue_paper_intake(
    app: Any, *, cohort_id: str, package_version: str, kind: str, filename: str,
    chunk_refs: tuple[str, ...],
) -> str:
    """Queue one fully-received upload for reading and answer the job id that will read it.

    A worker already draining the class's queue takes the file into its own job (its total
    grows by one); otherwise a new job is registered and its worker started. Taken under the
    one guard the worker's last look at the queue is taken under, so a file queued as the
    worker finishes is never stranded."""
    item = {
        "package_version": package_version,
        "kind": kind,
        "filename": filename,
        "chunk_refs": tuple(chunk_refs),
    }
    # Composed before anything is registered: a composition that raises must not leave the
    # class with a job no worker drains (every later upload would join it).
    config = _intake_config(app)
    with app._intake_guard:
        queue = app._intake_queues.setdefault(cohort_id, collections.deque())
        queue.append(item)
        live = app._intake_jobs.get(cohort_id)
        if live is not None:
            record = app._jobs.get(live)
            total = int((record or {}).get("progress", {}).get("total") or 0)
            app._jobs.update(live, total=total + 1)
            return live
        attempts = int(app._intake_attempts.get(cohort_id, 0)) + 1
        app._intake_attempts[cohort_id] = attempts
        job_id = f"papers-{cohort_id}-{attempts}"
        app._jobs.register(job_id=job_id, kind=INTAKE_JOB_KIND, total=1,
                           current=f"{filename} is waiting to be read",
                           started_at=_now())
        app._intake_jobs[cohort_id] = job_id
    thread = threading.Thread(
        target=_intake_worker, name=f"aeh-papers-{job_id}", daemon=True,
        args=(app, cohort_id, job_id, config),
    )
    try:
        thread.start()
    except Exception as error:  # noqa: BLE001 - a worker that never ran owns nothing
        with app._intake_guard:
            app._intake_jobs.pop(cohort_id, None)
            app._intake_queues.pop(cohort_id, None)
        app._jobs.finish(job_id, state="failed", finished_at=_now(),
                         error_detail=_strip_exception_name(error)
                         or "the papers reader could not start.",
                         error_next_action="upload the papers again.")
    return job_id


def _reassembled(store: Any, chunk_refs: tuple[str, ...]) -> bytes:
    """The uploaded file, put back together from the chunks the upload staged in order.
    The route names each chunk `sha256:<hex>`; the blob store keys it by the bare digest."""
    blobs = store.blobs()
    return b"".join(blobs.get(ref.split(":", 1)[-1]) for ref in chunk_refs)


#: The tallies one file adds to its job's summary, in the summary's order.
_TALLIES = ("ready", "parked", "skipped", "failed")


def _sheet_line(filename: str, result: Any) -> tuple[str, str | None]:
    """One file's progress line, and the tally it adds to the job's summary (`None` for the
    test paper, which is no student's paper)."""
    sheets = tuple(getattr(result, "sheets", ()) or ())
    if not sheets:
        return f"{filename}: the test paper is {result.assessment}", None
    sheet = sheets[0]
    status = str(sheet.status)
    if status in _ADMITTED_STATUSES:
        return f"{filename}: read", "ready"
    if status == "skipped":
        return f"{filename}: already read for this class", "skipped"
    if sheet.submission_id:
        return f"{filename}: parked ({status.replace('_', ' ')})", "parked"
    detail = str(sheet.detail or status)
    return f"{filename}: not read — {detail}", "failed"


def _tallies(app: Any, job_id: str) -> dict[str, Any]:
    """The job's running file tallies, kept on the app so a Resume continues them."""
    store = getattr(app, "_intake_tallies", None)
    if store is None:
        store = {}
        try:
            app._intake_tallies = store
        except AttributeError:  # pragma: no cover - an app that refuses attributes
            pass
    return store.setdefault(job_id, {**dict.fromkeys(_TALLIES, 0), "last_error": None})


def _money(value: Any) -> str:
    """A cost as a teacher reads it: the decimal as recorded, with no trailing exponent."""
    from decimal import Decimal

    return format(Decimal(str(value)).normalize(), "f")


def _paused_reason(session: Any, done: int, waiting: int) -> str:
    """The sentence a paused reading job carries on Jobs and on Papers (FR-CONSOLE-97)."""
    currency = session.currency
    return (f"Reading paused at the reading cost limit of {_money(session.ceiling())} "
            f"{currency}: the {done} file(s) read so far cost {_money(session.spent)} "
            f"{currency}. {waiting} file(s) wait unread. Press Resume to read up to "
            f"{_money(session.ceiling())} {currency} more; papers already read are kept and "
            f"are not read again.")


def _intake_worker(app: Any, cohort_id: str, job_id: str, config: dict[str, Any], *,
                   done: int = 0, spent: Any = 0) -> None:
    """Drain one class's queue under one job: reassemble each file from the blob store and
    read it through `aeh ingest`'s door, reporting each file as it is done.

    FR-CONSOLE-97 / FR-PROV-48: the files are read through one `ReadingSession`, built before
    the first file — it verifies the page reader's retention on a remote profile, and meters
    what each file cost. Before each next file the job's spend since it started (or resumed)
    is checked against the reading cost limit; at the limit the job pauses with the files still
    queued, and **Resume** (`resume_reading`) continues from the next unread file. `done` and
    `spent` are what the job had already done when it is resumed."""
    from aeh.pipeline import ReadingSession
    from aeh.pipeline.runtime import _open_store

    registry = app._jobs
    tally = _tallies(app, job_id)
    worker_store = None
    session = None
    paused_waiting: int | None = None
    try:
        registry.update(job_id, state="running")
        worker_store = _open_store(str(app._store.data_dir))
        session = ReadingSession(worker_store, config, cohort_id, spent=spent)
        while True:
            with app._intake_guard:
                queue = app._intake_queues.get(cohort_id)
                if not queue:
                    app._intake_jobs.pop(cohort_id, None)
                    break
                if session.ceiling_reached():
                    # Paused, not finished: the queue and the class's job stay, so a later
                    # upload joins this job and waits with the rest for Resume.
                    paused_waiting = len(queue)
                    break
                item = queue.popleft()
            filename = str(item["filename"])
            registry.update(job_id, current=f"reading {filename}")
            try:
                result = session.read(
                    str(item["package_version"]), kind=str(item["kind"]), filename=filename,
                    data=_reassembled(worker_store, item["chunk_refs"]))
                line, counted = _sheet_line(filename, result)
            except Exception as error:  # noqa: BLE001 - one file's failure, never the queue's
                tally["last_error"] = _strip_exception_name(error) or "the read failed."
                line, counted = f"{filename}: not read — {tally['last_error']}", "failed"
            done += 1
            if counted is not None:
                tally[counted] += 1
            registry.update(job_id, done=done, current=line, cost_usd=float(session.spent))
        if paused_waiting is not None:
            registry.update(job_id, state="paused", cost_usd=float(session.spent),
                            current=_paused_reason(session, done, paused_waiting))
            return
        summary = (f"{done} file(s) done: {tally['ready']} paper(s) ready to grade, "
                   f"{tally['parked']} parked, {tally['skipped']} already read, "
                   f"{tally['failed']} not read")
        spend = float(session.spent)
        if done and tally["failed"] == done:
            registry.update(job_id, current=summary)
            registry.finish(
                job_id, state="failed", finished_at=_now(), cost_usd=spend,
                error_detail=tally["last_error"] or "no file could be read.",
                error_next_action=(
                    "check the page reader's key, credit and model name in the settings, "
                    "then upload the papers again — papers already read are skipped."))
        else:
            registry.update(job_id, current=summary)
            registry.finish(job_id, state="succeeded", finished_at=_now(), cost_usd=spend)
    except Exception as error:  # noqa: BLE001 - recorded on the job, never swallowed
        with app._intake_guard:
            app._intake_jobs.pop(cohort_id, None)
            app._intake_queues.pop(cohort_id, None)
        registry.finish(
            job_id, state="failed", finished_at=_now(),
            cost_usd=float(session.spent) if session is not None else None,
            error_detail=_strip_exception_name(error) or "the papers could not be read.",
            error_next_action="upload the papers again; papers already read are skipped.")
    finally:
        if paused_waiting is None:
            getattr(app, "_intake_tallies", {}).pop(job_id, None)
        if worker_store is not None:
            try:
                worker_store.close()
            except Exception:  # noqa: BLE001 - a close failure must not mask the outcome
                pass


#: The control action that continues a reading job paused at its cost limit (FR-CONSOLE-97).
RESUME_READING_ACTION = "resume reading"


def resume_reading(app: Any, params: Mapping[str, Any]) -> Any:
    """**Resume** (FR-CONSOLE-97): continue the class's reading job that paused at the reading
    cost limit, from the next unread file, under the same job — its count of files done and its
    spend carry on, and nothing already read is read again (the files left are exactly the
    queue the pause kept). Each Resume allows up to one more limit's worth of reading.

    Refuses, in the teacher's words, a class with no paused reading job, or a job that is not
    the class's paused reading job. Writes no store row: the queue and the job are console
    memory (`ADR-47`); the papers' real state is the submission rows the read writes."""
    from .records import ControlOutcome

    def refused(detail: str, next_action: str) -> ControlOutcome:
        return ControlOutcome(rows_written=(), refused=True, dispatched=False,
                              detail=detail, next_action=next_action)

    cohort_id = str(params.get("cohort_id") or "")
    try:
        config = _intake_config(app)
    except Exception as error:  # noqa: BLE001 - the composition's own wording
        return refused(f"the reading could not resume: {_strip_exception_name(error)}",
                       "check the console's settings, then press Resume again.")
    # The check and the flip out of `paused` happen under the one guard, so two Resume presses
    # at once (a double click, a second tab) start one worker, never two on the same job.
    with app._intake_guard:
        live = app._intake_jobs.get(cohort_id)
        job_id = str(params.get("job_id") or live or "")
        record = app._jobs.get(job_id) if job_id else None
        resumable = (record is not None and record.get("kind") == INTAKE_JOB_KIND
                     and live == job_id and record.get("state") == "paused")
        if resumable:
            app._jobs.update(job_id, state="queued",
                             current="reading resumes with the next unread file")
    if not resumable:
        return refused(
            "there is no paused reading of papers for this class to resume.",
            "open Load papers for the class; a reading that paused at its cost limit shows a "
            "Resume button there.")
    done = int((record.get("progress") or {}).get("done") or 0)
    spent = record.get("cost_usd") or 0
    thread = threading.Thread(
        target=_intake_worker, name=f"aeh-papers-{job_id}-resumed", daemon=True,
        args=(app, cohort_id, job_id, config), kwargs={"done": done, "spent": spent},
    )
    try:
        thread.start()
    except Exception as error:  # noqa: BLE001 - a worker that never ran owns nothing
        with app._intake_guard:
            app._intake_jobs.pop(cohort_id, None)
            app._intake_queues.pop(cohort_id, None)
        getattr(app, "_intake_tallies", {}).pop(job_id, None)
        app._jobs.finish(job_id, state="failed", finished_at=_now(),
                         error_detail=_strip_exception_name(error)
                         or "the papers reader could not start.",
                         error_next_action="upload the papers again; papers already read "
                                           "are skipped.")
        return refused("the reading could not resume: the papers reader could not start.",
                       "upload the papers again; papers already read are skipped.")
    return ControlOutcome(rows_written=(), refused=False, dispatched=True, job_id=job_id,
                          detail="reading resumed with the next unread file; papers already "
                                 "read are kept.")


def reading_state(app: Any, cohort_id: str) -> dict[str, Any] | None:
    """The class's live reading job for the Papers screen (FR-CONSOLE-97): its state, files
    done and waiting, its spend and — when it paused at the cost limit — the reason, in the
    teacher's words. `None` when no reading job is live for the class."""
    if getattr(app, "_intake_guard", None) is None or getattr(app, "_jobs", None) is None:
        return None
    with app._intake_guard:
        job_id = app._intake_jobs.get(cohort_id)
        waiting = len(app._intake_queues.get(cohort_id) or ())
    record = app._jobs.get(job_id) if job_id else None
    if record is None:
        return None
    paused = record.get("state") == "paused"
    return {
        "job_id": job_id,
        "state": record.get("state"),
        "paused": paused,
        "done": (record.get("progress") or {}).get("done"),
        "waiting": waiting,
        "spend": record.get("cost_usd"),
        "reason": (record.get("progress") or {}).get("current") if paused else None,
    }


__all__ = [
    "INTAKE_JOB_KIND",
    "PAPER_KINDS",
    "RESUME_READING_ACTION",
    "check_paper_upload",
    "queue_paper_intake",
    "reading_state",
    "resume_reading",
    "wants_read",
]
