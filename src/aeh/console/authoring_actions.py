"""The console's authoring control actions (#760, `FR-CONSOLE-55/56/57/61/62`): the five
enumerated actions the design delta's §3.2.2 adds, dispatched from `perform` before the
row machinery — because four of the five write no store row the control surface owns, and
the fifth (`cancel job`) may delegate to one that does.

The shape follows the landed write actions (`#755`'s reads, `#761`'s class actions):

* **draft package from documents** (`FR-CONSOLE-61`) stages the uploaded documents in the
  blob store — the only place document bytes may land (`CT-CONSOLE-34`) — then starts the
  `AuthoringService.draft` workflow on a server-owned worker thread (the `start_run_in_
  background` pattern) and returns the job id at once. Progress rides the jobs registry
  (`ADR-47`): the worker maps `AuthoringProgress` onto the job record at every step
  boundary (`FR-AUTHOR-30`'s observer seam), and the cancel event is checked at those same
  boundaries. One active authoring job per draft directory (`ADR-45`): a second draft
  against the same directory is refused by name, not queued behind a silent interleaving.
* **answer authoring review** (`FR-CONSOLE-55`) runs the review walk synchronously over
  the named draft — the same `run_review` door the workflow's own review stage uses
  (`FR-AUTHOR-16/17`), called directly because a review makes no model call and needs no
  constructed service. A draft under an action is single-writer (`ADR-45`): a second
  review, edit or approval of the same file while one runs is refused by name, and a
  draft job cannot start behind a running action. A refused answer is reported as
  refused: the walk restores the item's sentinel, and the outcome says the item still
  stands rather than that the answer was recorded.
* **edit draft package** (`FR-CONSOLE-56`) applies one structured operation through
  `aeh.author`'s validate-and-persist path (`edit.apply_structured_edit`): the console
  never sends TOML text (`ADR-45`), an edit that would leave the draft invalid is refused
  with the field named, and the field-level change list comes back as the outcome detail.
* **approve draft package** (`FR-CONSOLE-62`) is the one authoring action that touches the
  package tier, and it does so only through M-PKG's own door — `build_package`, which
  plans, creates the version and publishes it in one idempotent gate. The approval record
  is a marker line in the draft file itself (`ADR-45`: the draft files are the state), so
  approving an unchanged draft a second time is a no-op that names the published version.
  Approving an *edited* draft is a different case, and the design does not promise it
  builds again: `M-PKG`'s own rule answers at the build gate — a built package is never
  changed, so the edited draft cannot be approved under the same package id, and the
  refusal says so and names the way back (a new draft from the documents under a new id).
  The draft's remaining placeholders are refused exactly where M-PKG refuses them
  (`FR-PKG-28`'s sentence), with the review screen named as the way out.
* **cancel job** (`FR-CONSOLE-57`) is cooperative for authoring jobs — it sets the event
  the worker checks at its next step boundary, and nothing else — and for a run job it
  delegates to the same `pause/resume` control row the run monitor writes, so there is one
  mechanism per kind of work, never two.

Every refusal is a returned outcome with a teacher-shaped detail (`CT-CONSOLE-33`: no
HTTP codes, no exception names, no tracebacks) and, where one exists, the next action the
screen should offer. Nothing here writes a store row outside M-PKG's own door, and no
document byte ever reaches a detail message, a log line or a URL (`CT-CONSOLE-34`).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import tempfile
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Mapping

from aeh.author import (
    EDIT_OPERATIONS,
    AuthoringCancelled,
    AuthoringInputError,
    AuthoringProgress,
    OverwriteRefusedError,
    ReviewAnswer,
    apply_structured_edit,
    approval_of,
    authoring_service,
    commit_artifacts,
    content_digest,
    run_review,
    with_approval_marker,
)
from aeh.author import slugify_package_id
from aeh.author import check_gap_answer, missing_points
from aeh.author.report import draft_filename
from aeh.pipeline.packages import (
    PLACEHOLDER_SENTINEL,
    PackageSpecError,
    build_package,
    read_package_spec,
)
from aeh.pipeline.runtime import _open_store, _provider_for

from .html import _now
from .authoring_reads import _load_draft, _walk_placeholders, find_draft_for
from .authoring_reads import owner_qid
from .records import ControlOutcome
from .version_labels import (
    PackageVersionLabel,
    UnknownPackageVersion,
    read_version_label,
)
from .settings import author_doc_max_bytes
from .spa_reads import _strip_exception_name
from .write_rows import _rows_for


#: The five actions this module owns — the control-surface entries whose effect is not a
#: store row the console writes itself. `perform` dispatches here before the row
#: machinery; the enumeration (`CT-CONSOLE-02`) already declared them in the vocabulary.
AUTHORING_CONTROL_ACTIONS: frozenset[str] = frozenset(
    {
        "draft package from documents",
        "draft package from scratch",
        "answer authoring review",
        "edit draft package",
        "approve draft package",
        "cancel job",
    }
)


def apply_authoring_action(
    app: Any, action: str, params: Mapping[str, Any]
) -> ControlOutcome:
    """The dispatch `perform` calls for the six authoring actions. Every teacher-facing
    refusal returns an outcome (never a raise), so the sweep that performs each action
    bare sees a refusal, not an exception."""
    if action == "draft package from documents":
        return _draft_package_from_documents(app, params)
    if action == "draft package from scratch":
        return _draft_package_from_scratch(app, params)
    if action == "answer authoring review":
        return _answer_authoring_review(app, params)
    if action == "edit draft package":
        return _edit_draft_package(app, params)
    if action == "approve draft package":
        return _approve_draft_package(app, params)
    if action == "cancel job":
        return _cancel_job(app, params)
    raise KeyError(f"{action!r} is not an authoring control action")


def _refused(detail: str, next_action: str | None = None) -> ControlOutcome:
    return ControlOutcome(rows_written=(), refused=True, dispatched=False,
                          detail=detail, next_action=next_action)


def _data_dir(app: Any) -> str | None:
    data_dir = getattr(app._store, "data_dir", None)
    return str(data_dir) if data_dir is not None else None


# --- the draft job (FR-CONSOLE-61) ----------------------------------------------------------------------


def _draft_package_from_documents(
    app: Any, params: Mapping[str, Any]
) -> ControlOutcome:
    documents = params.get("documents")
    if not isinstance(documents, list) or not documents:
        return _refused(
            "the action names no documents: select the scanned documents on the "
            "authoring screen and start the draft again.")
    ceiling = author_doc_max_bytes()
    staged: list[tuple[str, str]] = []
    for index, document in enumerate(documents):
        if not isinstance(document, Mapping) or not str(document.get("name") or "").strip():
            return _refused(
                f"document {index + 1}: a document is a file name and its content; "
                "give both and start the draft again.")
        name = str(document["name"])
        raw = document.get("content_base64")
        if not isinstance(raw, str) or not raw.strip():
            return _refused(
                f"the document {name!r} arrived with no content: upload it again.")
        try:
            data = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            return _refused(
                f"the document {name!r} could not be read: its content is not the "
                "encoded file the upload sent. Upload it again.")
        if not data:
            return _refused(f"the document {name!r} is empty; upload it again.")
        if len(data) > ceiling:
            return _refused(
                f"the document {name!r} is larger than the ceiling of "
                f"{ceiling // (1024 * 1024)} MB per document. Split it or compress it, "
                "then start the draft again.")
        staged.append((name, data))

    data_dir = _data_dir(app)
    if data_dir is None:
        return _refused("no store is attached; the documents cannot be staged.")
    config = app.run_config if isinstance(app.run_config, dict) else {}
    profile = str(config.get("HARNESS_PROFILE") or "")
    if not profile:
        return _refused(
            "no backend profile is configured for authoring, and a draft cannot run "
            "without one. Set the profile in the configuration, then start again.",
            next_action="open the configuration screen and set the profile.")

    # Stage the documents in the blob store — the one place document bytes may land
    # (`CT-CONSOLE-34`). The worker reads them back from there; nothing keeps the bytes
    # in console memory, and no detail message ever carries document content.
    store = app._store
    refs: list[tuple[str, str]] = []
    for name, data in staged:
        try:
            refs.append((name, store.blobs().put(data)))
        except Exception as error:  # noqa: BLE001 - a staging failure is a refusal
            return _refused(
                f"the document {name!r} could not be staged "
                f"({_strip_exception_name(error)}); nothing was started.")
    del staged

    digest = hashlib.sha256(
        "\n".join(f"{name}\x00{ref}" for name, ref in sorted(refs)).encode("utf-8")
    ).hexdigest()[:12]
    base_id = f"authoring-{digest}"
    existing = app._jobs.get(base_id)
    if existing is not None and existing["state"] in ("queued", "running"):
        return ControlOutcome(
            rows_written=(), refused=False, dispatched=False,
            detail=(
                f"the draft job for these documents is already {existing['state']} "
                f"(job {base_id}); its progress is on the jobs page."))
    if existing is not None and existing["state"] == "succeeded" and not params.get("replace"):
        return ControlOutcome(
            rows_written=(), refused=False, dispatched=False,
            next_action="open the draft on the authoring screen.",
            detail=(
                f"the draft for these documents already stands (job {base_id} "
                f"succeeded); re-drafting would replace it. Pass replace to draft "
                "again from the documents as they are now."))

    # One active authoring job per draft directory (`ADR-45`): the directory lock is held
    # for the job's whole life, so a review or an edit of a draft in that directory waits
    # rather than interleaving with the writer. The attempt number and the lock are taken
    # together under the guard, and the lock's token is the job id this attempt will
    # register — the same id the register-failure path and the worker's `finally` release
    # with, so a refused or failed attempt never strands the directory lock.
    dir_key = f"authoring-dir:{data_dir}"
    with app._authoring_lock_guard:
        attempts = int(app._authoring_attempts.get(base_id, 0)) + 1
        app._authoring_attempts[base_id] = attempts
        job_id = base_id if attempts == 1 else f"{base_id}-r{attempts}"
        holder = app._authoring_locks.get(dir_key)
        if holder is not None and holder != job_id:
            holder = str(holder)
        else:
            app._authoring_locks[dir_key] = job_id
            holder = None
    if holder is not None:
        # The attempt counter is not rolled back: it exists to keep tokens unique, and a
        # consumed number costs nothing. The holder is either a draft job's id or a
        # synchronous action's token; each refusal names what actually holds the
        # directory.
        if holder.startswith("authoring-"):
            return _refused(
                f"another authoring job (job {holder}) is already writing this draft "
                "directory. Wait for it to finish or cancel it, then start again.")
        return _refused(
            "another review, edit or approval of a draft in this directory is "
            "running; try again in a moment.")

    event = threading.Event()
    app._authoring_cancels[job_id] = event
    try:
        app._jobs.register(job_id=job_id, kind="authoring_draft",
                           current=f"{len(refs)} document(s) staged", started_at=_now())
    except ValueError:
        _release_lock(app, dir_key, job_id)
        app._authoring_cancels.pop(job_id, None)
        return _refused(
            f"a job named {job_id} is already registered; the jobs page shows its "
            "progress.")
    thread = threading.Thread(
        target=_draft_worker,
        name=f"authoring-draft-{job_id}",
        daemon=True,
        args=(app, job_id, base_id, dir_key, refs, data_dir, profile, dict(config),
              bool(params.get("replace")), event),
    )
    app._authoring_threads[job_id] = thread
    thread.start()
    return ControlOutcome(
        rows_written=(), refused=False, dispatched=True, job_id=job_id,
        next_action="watch the job on the jobs page; the draft opens on the "
                    "authoring screen when it finishes.",
        detail=(
            f"{len(refs)} document(s) staged; the draft job {job_id} is running. The "
            "draft and its report are written under the authoring folder when it "
            "finishes."))


def _draft_worker(
    app: Any, job_id: str, base_id: str, dir_key: str,
    refs: list[tuple[str, str]], data_dir: str, profile: str, config: dict[str, Any],
    replace: bool, cancel_event: threading.Event,
) -> None:
    """The draft job's body: open this thread's own store (a SQLite connection belongs to
    its thread), read the staged documents back out of the blob store, and run the
    authoring workflow with the observer/cancel seam the console drives (`FR-AUTHOR-30`)."""
    registry = app._jobs

    def observe(progress: AuthoringProgress) -> None:
        registry.update(
            job_id, state="running", done=progress.done, total=progress.total,
            current=progress.current, stage=progress.stage,
            attempt=progress.attempt, attempts=progress.attempts)

    worker_store = None
    try:
        registry.update(job_id, state="running", current="starting")
        provider = _provider_for({"backend_profile": profile})
        service = authoring_service(config, profile, provider=provider)
        worker_store = _open_store(data_dir)
        with tempfile.TemporaryDirectory(prefix="aeh-authoring-") as folder:
            # Two uploaded documents can carry the same file name; they are materialized
            # under distinct names so one never silently overwrites the other.
            paths = []
            used: set[str] = set()
            for name, ref in refs:
                base = Path(name).name or f"document-{len(paths) + 1}"
                stem, suffix = Path(base).stem, Path(base).suffix
                final_name, n = base, 2
                while final_name in used:
                    final_name = f"{stem}-{n}{suffix}"
                    n += 1
                used.add(final_name)
                path = Path(folder, final_name)
                path.write_bytes(worker_store.blobs().get(ref))
                paths.append(path)
            result = service.draft(
                paths, Path(data_dir, "authoring"), force=replace,
                observer=observe, cancel=cancel_event.is_set)
        registry.update(
            job_id, current=(
                f"the draft stands at {result.draft_path.name} "
                f"({result.placeholders} review item(s) to answer)"))
        registry.finish(job_id, state="succeeded", finished_at=_now())
    except AuthoringCancelled as stopped:
        registry.finish(
            job_id, state="cancelled", finished_at=_now(), error_detail=str(stopped),
            error_next_action="start the draft again from the documents.")
    except OverwriteRefusedError as refused:
        registry.finish(
            job_id, state="failed", finished_at=_now(), error_detail=str(refused),
            error_next_action=(
                "the draft already stands: open it on the authoring screen, or start "
                "the job again with replace confirmed."))
    except Exception as error:  # noqa: BLE001 - recorded on the job, never swallowed
        registry.finish(
            job_id, state="failed", finished_at=_now(),
            error_detail=_strip_exception_name(error)
            or "the draft job failed for a reason the console could not name.",
            error_next_action=(
                "read the authoring report and the server log; correct the documents "
                "or the profile and start the draft again."))
    finally:
        app._authoring_threads.pop(job_id, None)
        app._authoring_cancels.pop(job_id, None)
        _release_lock(app, dir_key, job_id)
        if worker_store is not None:
            try:
                worker_store.close()
            except Exception:  # noqa: BLE001 - a close failure must not mask the outcome
                pass


# --- the synchronous draft actions ----------------------------------------------------------------------


def _draft_package_from_scratch(app: Any, params: Mapping[str, Any]) -> ControlOutcome:
    """The from-scratch start (`FR-UI-13`, the editor's second entry): the service's
    deterministic skeleton (`FR-AUTHOR-29`) written under the package id the title
    slugifies to, synchronously — it makes no model call and reads no documents, so it
    is a fast action beside the review and edit rows, not a job. The same single-writer
    rule holds (`ADR-45`): the directory lock is held for the write, and the would-be
    draft file is the file lock's key, so a from-scratch start never lands behind a draft
    job or a running review of the draft it would replace."""
    title = str(params.get("title") or "").strip()
    if not title:
        return _refused(
            "a package started from scratch needs a name: the name becomes the package "
            "id the empty draft is written under. Give the package a name and start "
            "again.")
    data_dir = _data_dir(app)
    if data_dir is None:
        return _refused("no store is attached; the empty draft cannot be written.")
    config = app.run_config if isinstance(app.run_config, dict) else {}
    profile = str(config.get("HARNESS_PROFILE") or "")
    if not profile:
        return _refused(
            "no backend profile is configured for authoring, and a package cannot be "
            "started without one. Set the profile in the configuration, then start again.",
            next_action="open the configuration screen and set the profile.")
    package_id = slugify_package_id(title)
    path = Path(data_dir, "authoring", draft_filename(package_id))

    def run() -> ControlOutcome:
        try:
            provider = _provider_for({"backend_profile": profile})
            service = authoring_service(config, profile, provider=provider)
            result = service.draft_from_scratch(Path(data_dir, "authoring"), title)
        except AuthoringInputError as refused:
            return _refused(str(refused))
        except OverwriteRefusedError as refused:
            # The library's refusal names the output directory by its server path; the
            # teacher surface never carries one (`CT-CONSOLE-31`), so the folder is
            # projected out and the file names stay.
            message = str(refused).replace(
                str(Path(data_dir, "authoring")), "the authoring folder")
            return _refused(
                message,
                next_action=(
                    "open the standing draft on the editor screen, or give the new "
                    "package its own name and start again."))
        except Exception as error:  # noqa: BLE001 - a failed start is a refusal
            return _refused(
                f"the empty draft could not be written ({_strip_exception_name(error)}); "
                "nothing stands changed.")
        return ControlOutcome(
            rows_written=(), refused=False, dispatched=True,
            next_action="open the editor: add the questions, then the grading points.",
            detail=(
                f"the empty draft for package {package_id!r} stands "
                f"({result.draft_path.name}); it has no questions and no grading points "
                "yet — the editor is where both are added."))

    return _with_draft_lock(app, path, data_dir, "scratch", run)


def _draft_path_for(app: Any, params: Mapping[str, Any]) -> Path | None:
    """The draft file the action names, through the confined lookup the reads use — a
    package id arrives from a request body, so it is attacker-shaped and refused by
    absence, never by probing paths."""
    data_dir = _data_dir(app)
    if data_dir is None:
        return None
    return find_draft_for(data_dir, str(params.get("package_id") or ""))


def _with_draft_lock(
    app: Any, path: Path, data_dir: str, action: str,
    run: Callable[[], ControlOutcome],
) -> ControlOutcome:
    """Run one synchronous draft action under the single-writer rule (`ADR-45`), holding
    both locks for the action's whole body: the directory lock (so a draft job cannot
    start mid-action and write behind it) and the draft-file lock (so two actions on one
    draft — two reviews, a review against an edit — cannot interleave). The token is
    unique to this invocation, so a second action while one runs is a genuine conflict,
    never a same-token re-entry; both locks release in `finally`, so a failure never
    strands one."""
    dir_key = f"authoring-dir:{data_dir}"
    token = f"{action}-{uuid.uuid4().hex[:8]}"
    with app._authoring_lock_guard:
        holder = app._authoring_locks.get(dir_key)
        if holder is not None:
            holder = str(holder)
        else:
            app._authoring_locks[dir_key] = token
    if holder is not None:
        if holder.startswith("authoring-"):
            return _refused(
                f"another authoring job (job {holder}) is writing in this draft's "
                "directory. Wait for it to finish or cancel it, then try again.")
        return _refused(
            "another review, edit or approval of a draft in this directory is "
            "running; try again in a moment.")
    file_key = f"authoring-draft:{path}"
    holder = _acquire_lock(app, file_key, token)
    if holder is not None:
        _release_lock(app, dir_key, token)
        return _refused(
            "this draft already has an action in progress; finish it before "
            "starting another.")
    try:
        return run()
    finally:
        _release_lock(app, file_key, token)
        _release_lock(app, dir_key, token)


def _answer_authoring_review(app: Any, params: Mapping[str, Any]) -> ControlOutcome:
    data_dir = _data_dir(app)
    if data_dir is None:
        return _refused("no store is attached; there is no draft to review.")
    path = _draft_path_for(app, params)
    if path is None:
        return _refused(
            f"no draft stands for the package {params.get('package_id')!r}. Draft the "
            "package from its documents first.",
            next_action="start the draft on the authoring screen.")
    answers: list[ReviewAnswer] = []
    supplied = params.get("answers")
    if isinstance(supplied, list):
        for entry in supplied:
            if not isinstance(entry, Mapping) or not str(entry.get("item_id") or "").strip():
                return _refused(
                    "an answer names the review item it answers (its item id) and the "
                    "answer itself; one of the answers carries neither.")
            answers.append(ReviewAnswer(
                item_id=str(entry["item_id"]), value=str(entry.get("value") or "")))
    else:
        item_id = str(params.get("item_id") or "").strip()
        if not item_id:
            return _refused(
                "the action names no review item: answer from the review screen, which "
                "lists the items the draft still asks about.")
        answers.append(ReviewAnswer(item_id=item_id, value=str(params.get("value") or "")))

    spec = _load_draft(path)
    if spec is None:
        return _refused(
            "the draft file could not be read; re-draft the package from its documents.")
    owners: dict[str, str | None] = {}
    for item_id, where in _walk_placeholders(spec, ""):
        owners.setdefault(item_id, owner_qid(spec, where))
    # A question's missing points stand in no sentinel, yet are asked (FR-AUTHOR-32): the
    # answer lands through the structured edit, not the review walk.
    points_items = set(missing_points(spec))
    open_items = set(owners) | points_items
    for answer in answers:
        if answer.item_id not in open_items:
            listing = ", ".join(sorted(open_items)) or "none"
            return _refused(
                f"the review item {answer.item_id!r} is not one this draft still asks "
                f"about (open items: {listing}). Answer from the review screen, which "
                "lists the items that still stand.")
    # The server re-applies the field's check (CT-AUTHOR-27): an answer outside its kind or
    # range is refused with the gap's own hint, before anything is written.
    for answer in answers:
        refusal = check_gap_answer(answer.item_id, answer.value, spec,
                                   owners.get(answer.item_id))
        if refusal is not None:
            return _refused(refusal)
    points_answers = [answer for answer in answers if answer.item_id in points_items]
    answers = [answer for answer in answers if answer.item_id not in points_items]
    if points_answers and answers:
        # Two writers in one request could half-land: the points edit saved while a review
        # answer is turned down. The points come first, on their own.
        return _refused(
            "Answer how many points each question is worth first, on its own. Then "
            "answer the other questions.")

    def run() -> ControlOutcome:
        for answer in points_answers:
            try:
                apply_structured_edit(path, "edit question", params={
                    "item_id": answer.item_id.partition(" ")[2], "field": "points",
                    "value": int(answer.value.strip())})
            except AuthoringInputError as refused:
                return _refused(str(refused))
        if not answers:
            return ControlOutcome(
                rows_written=(), refused=False, dispatched=True,
                next_action="answer the remaining questions on the review screen.",
                detail="the answer was recorded.")
        # The review walk directly, not through a constructed service: a review makes no
        # model call, so `AuthoringService.review` would only re-seat the same `run_review`
        # door (`FR-AUTHOR-16/17`); the console drives the one implementation both surfaces
        # share (`FR-AUTHOR-30`'s parity rule).
        try:
            result = run_review(path, answers)
        except AuthoringInputError as refused:
            return _refused(str(refused))
        if result.ready:
            return ControlOutcome(
                rows_written=(), refused=False, dispatched=True,
                next_action="approve the draft package.",
                detail=(
                    "the answer was recorded; the draft is ready to approve — every "
                    "review item stands answered and the draft re-validated."))
        remaining = ", ".join(result.remaining)
        # `run_review` does not raise on a rejected answer: it restores the item's
        # sentinel and leaves it open, so an item the request answered and that still
        # stands was refused by the walk. Saying "recorded" for it would lie to the
        # teacher; the honest split is which answers were accepted and which were not.
        answered = {answer.item_id for answer in answers}
        rejected = sorted(answered & set(result.remaining))
        if rejected:
            names = ", ".join(rejected)
            return ControlOutcome(
                rows_written=(), refused=False, dispatched=True,
                next_action="open the review screen; it shows what each standing item "
                            "needs.",
                detail=(
                    f"the answer for {names} was not accepted: the review item(s) still "
                    f"stand. {len(result.remaining)} review item(s) stand in all "
                    f"({remaining})."))
        return ControlOutcome(
            rows_written=(), refused=False, dispatched=True,
            next_action="answer the remaining review items on the review screen.",
            detail=(
                f"the answer was recorded; {len(result.remaining)} review item(s) still "
                f"stand ({remaining}). The draft was re-validated and rewritten in place."))

    return _with_draft_lock(app, path, data_dir, "review", run)


def _edit_draft_package(app: Any, params: Mapping[str, Any]) -> ControlOutcome:
    data_dir = _data_dir(app)
    if data_dir is None:
        return _refused("no store is attached; there is no draft to edit.")
    path = _draft_path_for(app, params)
    if path is None:
        return _refused(
            f"no draft stands for the package {params.get('package_id')!r}. Draft the "
            "package from its documents first.",
            next_action="start the draft on the authoring screen.")
    operation = str(params.get("operation") or "").strip()
    if not operation:
        return _refused(
            "the action names no edit operation: the editor performs "
            f"{' , '.join(EDIT_OPERATIONS)}.")

    def run() -> ControlOutcome:
        try:
            outcome = apply_structured_edit(path, operation, params=params)
        except AuthoringInputError as refused:
            return _refused(str(refused))
        except (KeyError, TypeError, ValueError) as refused:
            return _refused(_strip_exception_name(refused) or str(refused))
        summary = "; ".join(
            f"{change.field} — {change.change}" for change in outcome.changes)
        return ControlOutcome(
            rows_written=(), refused=False, dispatched=True,
            detail=(
                f"the draft was edited ({summary}). The edited draft was re-validated "
                "before it was saved, and the placeholders the draft already carried "
                "stand untouched."))

    return _with_draft_lock(app, path, data_dir, "edit", run)


def _approve_draft_package(app: Any, params: Mapping[str, Any]) -> ControlOutcome:
    data_dir = _data_dir(app)
    if data_dir is None:
        return _refused("no store is attached; a package cannot be built.")
    package_id = str(params.get("package_id") or "").strip()
    if not package_id:
        return _refused(
            "the action names no package: approve from the draft's review screen.")
    path = _draft_path_for(app, params)
    if path is None:
        return _refused(
            f"no draft stands for the package {package_id!r}. Draft the package from "
            "its documents first.",
            next_action="start the draft on the authoring screen.")

    def run() -> ControlOutcome:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            return _refused(
                "the draft file could not be read; re-draft the package from its "
                "documents.")
        marker = approval_of(text)
        if marker is not None and marker[2] == content_digest(text):
            # FR-CONSOLE-73: a second press is not a refusal — the same success outcome,
            # prefixed, and nothing is built again.
            return _published_outcome(
                _version_label_from(data_dir, marker[1]), marker[0], already=True)
        store = None
        label: PackageVersionLabel | None = None
        try:
            store = _open_store(data_dir)
            spec = read_package_spec(path)
            built = build_package(store, spec)
            # The new version's teacher label, read while the store is open
            # (FR-CONSOLE-74): its number and the approval record's date.
            try:
                label = read_version_label(store, built.package_version)
            except UnknownPackageVersion:
                label = None
        except PackageSpecError as incomplete:
            # M-PKG's own refusal (`FR-PKG-28`) names the field, its line and the draft
            # file — engineering detail. The teacher is told in their words instead
            # (FR-UI-25, the console clarity delta): what was not published, why, and the
            # way back. A refusal that is not about unanswered pieces keeps M-PKG's
            # sentence as its why, with the server path projected out (`CT-CONSOLE-31`).
            message = str(incomplete).replace(str(path), path.name)
            if "already exists" in message:
                # An edited draft of a published package: `M-PKG` refuses the build, and
                # the console cannot rename a package for the teacher. The honest way
                # back, not a promised new version.
                what = f"{package_id} was not published again."
                why = ("A published test is never changed, and this draft was edited "
                       "after it was published.")
                return ControlOutcome(
                    rows_written=(), refused=True, dispatched=False,
                    detail=f"{what} {why}", what=what, why=why,
                    next_action=(
                        "Keep the published version, and start a new draft from the "
                        "documents under a new test name."))
            open_pieces = text.count(PLACEHOLDER_SENTINEL)
            what = f"{package_id} was not published."
            why = (f"The draft still has {open_pieces} unanswered "
                   f"{'piece' if open_pieces == 1 else 'pieces'}, and a test is "
                   "published only when every piece is answered."
                   if open_pieces else message)
            return ControlOutcome(
                rows_written=(), refused=True, dispatched=False,
                detail=f"{what} {why}", what=what, why=why,
                next_action=(
                    "Answer the remaining questions on the review screen, then press "
                    "Approve again."))
        except Exception as error:  # noqa: BLE001 - a failed build is a refusal, not a 500
            return _refused(
                f"the package could not be built ({_strip_exception_name(error)}); the "
                "draft stands unchanged.")
        finally:
            # `build_package` closes the store it is given on a failure's cleanup path;
            # this store handle is the console's, so it is closed here either way.
            if store is not None:
                try:
                    store.close()
                except Exception:  # noqa: BLE001
                    pass
        approved = with_approval_marker(
            text, built.package_id, built.package_version, content_digest(text))
        commit_artifacts(path.parent, [(path, approved)])
        return _published_outcome(label, built.package_id, approved_by=built.approved_by)

    return _with_draft_lock(app, path, data_dir, "approve", run)


#: Where the teacher goes after a test is published (FR-CONSOLE-73, FR-UI-27).
LOAD_PAPERS_NEXT = {"label": "Load papers", "route": "/papers"}
_LOAD_PAPERS_SENTENCE = "Next: load the students' papers."


def published_state(store: Any, text: str) -> dict[str, Any] | None:
    """The draft read's served approved state (FR-UI-27): when `text` stands approved and
    unchanged — its marker's hash still matches the content, the same rule the approve
    gate applies — the FR-CONSOLE-73 sentence with the Load papers link, so a reload
    keeps the banner. `None` when the draft carries no live marker. The plain sentence
    (no "Already published —" prefix: that prefix is a *press's* answer, not the state)."""
    marker = approval_of(text)
    if marker is None or marker[2] != content_digest(text):
        return None
    label: PackageVersionLabel | None
    try:
        label = read_version_label(store, marker[1])
    except Exception:  # noqa: BLE001 — a label is a courtesy; the state still stands
        label = None
    outcome = _published_outcome(label, marker[0], already=False)
    return {"detail": outcome.detail, "next": dict(LOAD_PAPERS_NEXT)}


def _version_label_from(data_dir: str, version_id: str) -> PackageVersionLabel | None:
    """The label of an already-published version, read through a store opened and closed
    here; `None` when the store cannot name it (the outcome then names the package only)."""
    store = None
    try:
        store = _open_store(data_dir)
        return read_version_label(store, version_id)
    except Exception:  # noqa: BLE001 — a label is a courtesy; the outcome still stands
        return None
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:  # noqa: BLE001
                pass


def _published_outcome(label: PackageVersionLabel | None, package_id: str, *,
                       approved_by: str | None = None,
                       already: bool = False) -> ControlOutcome:
    """FR-CONSOLE-73's approve outcome, in teacher words: *"Published ENG7-READ-01,
    version 1. Approved by <name> on 20 Oct 2026. Next: load the students' papers."* — or,
    for a press on the unchanged, already-published draft, *"Already published —"* and
    the same outcome. Never the version hash; always the link to Load papers. The replay
    dispatches nothing (nothing was built)."""
    named = f"{package_id}, {label.version}" if label is not None else package_id
    approver = (label.approved_by if label is not None and label.approved_by
                else approved_by)
    approved = ""
    if approver and label is not None and label.approved_on:
        approved = f" Approved by {approver} on {label.approved_on}."
    elif approver:
        approved = f" Approved by {approver}."
    outcome = f"{named}.{approved} {_LOAD_PAPERS_SENTENCE}"
    detail = f"Already published — {outcome}" if already else f"Published {outcome}"
    return ControlOutcome(
        rows_written=(), refused=False, dispatched=not already,
        detail=detail, next_action="Load the students' papers.",
        next=dict(LOAD_PAPERS_NEXT))


# --- cancel (FR-CONSOLE-57) ------------------------------------------------------------------------


def _cancel_job(app: Any, params: Mapping[str, Any]) -> ControlOutcome:
    job_id = str(params.get("job_id") or "").strip()
    if not job_id:
        return _refused(
            "the action names no job: cancel from the jobs page, which lists the "
            "console's jobs.")
    record = app._jobs.get(job_id)
    if record is not None and record["state"] in ("queued", "running"):
        if str(record["kind"]).startswith("authoring"):
            event = app._authoring_cancels.get(job_id)
            if event is None:
                return _refused(
                    f"the job {job_id} cannot be cancelled from this console process "
                    "(its worker is gone); the jobs page shows its last state.")
            event.set()
            return ControlOutcome(
                rows_written=(), refused=False, dispatched=True,
                detail=(
                    f"cancel requested for job {job_id}; it stops at its next step "
                    "boundary, and the files it has written stay exactly as the last "
                    "completed step left them."))
        return _cancel_run(app, job_id)
    if record is not None:
        return _refused(
            f"the job {job_id} is already {record['state']}; there is nothing to "
            "cancel.",
            next_action=(
                "open the job on the jobs page; its outcome and the files it wrote "
                "are listed there."))
    # Not in the registry: a console restart drops finished history (`ADR-47`), but a run
    # the registry no longer mirrors is still a run this console could pause — so the
    # same door the run monitor uses decides, and its answer stands.
    return _cancel_run(app, job_id)


def _cancel_run(app: Any, job_id: str) -> ControlOutcome:
    rows = _rows_for("pause/resume", {"run_id": job_id, "state": "paused"})
    result = app._write_rows("pause/resume", rows, {"run_id": job_id, "state": "paused"})
    # Indexed unpacking on purpose: `#761` widens this return with a fourth element, the
    # PR #794 follow-up with a fifth (`refused`), and the first three keep their meaning
    # across both.
    written, detail, dispatched = result[0], result[1], result[2]
    if not dispatched:
        return _refused(
            f"no job named {job_id} is running; the jobs page lists this console's "
            "jobs, and the runs screen lists its runs.")
    return ControlOutcome(
        rows_written=written, refused=False, dispatched=True,
        detail=(
            f"cancel requested for run {job_id}: {detail} The run stops at its next "
            "control-read boundary."))


# --- the lock table -------------------------------------------------------------------------------------


def _acquire_lock(app: Any, key: str, token: str) -> str | None:
    """Take the named lock for `token`, or answer the holder's id. The table lives on the
    app beside the jobs registry (`ADR-47`): console memory, guarded, never store state."""
    with app._authoring_lock_guard:
        holder = app._authoring_locks.get(key)
        if holder is not None and holder != token:
            return str(holder)
        app._authoring_locks[key] = token
        return None


def _release_lock(app: Any, key: str, token: str) -> None:
    with app._authoring_lock_guard:
        if app._authoring_locks.get(key) == token:
            del app._authoring_locks[key]
