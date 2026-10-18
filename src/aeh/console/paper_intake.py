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


def _intake_worker(app: Any, cohort_id: str, job_id: str, config: dict[str, Any]) -> None:
    """Drain one class's queue under one job: reassemble each file from the blob store and
    read it through `aeh ingest`'s door, reporting each file as it is done."""
    from aeh.pipeline import read_uploaded_paper
    from aeh.pipeline.runtime import _open_store

    registry = app._jobs
    done = 0
    tally = dict.fromkeys(_TALLIES, 0)
    last_error: str | None = None
    worker_store = None
    try:
        registry.update(job_id, state="running")
        worker_store = _open_store(str(app._store.data_dir))
        while True:
            with app._intake_guard:
                queue = app._intake_queues.get(cohort_id)
                if not queue:
                    app._intake_jobs.pop(cohort_id, None)
                    break
                item = queue.popleft()
            filename = str(item["filename"])
            registry.update(job_id, current=f"reading {filename}")
            try:
                result = read_uploaded_paper(
                    worker_store, config, cohort_id, str(item["package_version"]),
                    kind=str(item["kind"]), filename=filename,
                    data=_reassembled(worker_store, item["chunk_refs"]))
                line, counted = _sheet_line(filename, result)
            except Exception as error:  # noqa: BLE001 - one file's failure, never the queue's
                last_error = _strip_exception_name(error) or "the read failed."
                line, counted = f"{filename}: not read — {last_error}", "failed"
            done += 1
            if counted is not None:
                tally[counted] += 1
            registry.update(job_id, done=done, current=line)
        summary = (f"{done} file(s) done: {tally['ready']} paper(s) ready to grade, "
                   f"{tally['parked']} parked, {tally['skipped']} already read, "
                   f"{tally['failed']} not read")
        if done and tally["failed"] == done:
            registry.update(job_id, current=summary)
            registry.finish(
                job_id, state="failed", finished_at=_now(),
                error_detail=last_error or "no file could be read.",
                error_next_action=(
                    "check the page reader's key, credit and model name in the settings, "
                    "then upload the papers again — papers already read are skipped."))
        else:
            registry.update(job_id, current=summary)
            registry.finish(job_id, state="succeeded", finished_at=_now())
    except Exception as error:  # noqa: BLE001 - recorded on the job, never swallowed
        with app._intake_guard:
            app._intake_jobs.pop(cohort_id, None)
            app._intake_queues.pop(cohort_id, None)
        registry.finish(
            job_id, state="failed", finished_at=_now(),
            error_detail=_strip_exception_name(error) or "the papers could not be read.",
            error_next_action="upload the papers again; papers already read are skipped.")
    finally:
        if worker_store is not None:
            try:
                worker_store.close()
            except Exception:  # noqa: BLE001 - a close failure must not mask the outcome
                pass


__all__ = [
    "INTAKE_JOB_KIND",
    "PAPER_KINDS",
    "check_paper_upload",
    "queue_paper_intake",
    "wants_read",
]
