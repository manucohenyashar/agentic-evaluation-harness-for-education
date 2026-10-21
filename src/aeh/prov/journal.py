"""The AI-call journal: one `CallRecord` per model call attempt (FR-PROV-44/-45/-46, FR-CONSOLE-77).

Three pieces, all process-wide and all inert until a sink is installed:

* **Call context** (FR-PROV-45, ADR-52). `call_context(kind=..., cohort_id=..., ...)` sets a
  `contextvars.ContextVar` around a provider call. Nested contexts merge (an inner field
  overrides, an unset one is inherited) and the outer one is restored on exit. A context is
  per thread: a worker that runs on a pool thread sets its own, or is started inside
  `contextvars.copy_context().run(...)`. A call made with no kind records `unlabelled`.
* **The slot** (FR-CONSOLE-77). `install_call_journal(sink)` puts one sink in force for the
  whole process and returns the one it replaced; providers read the slot when an attempt
  ends, so no construction site needs the sink passed in. With no sink installed, providers
  build no record and make no extra clock read: the fast tier is unchanged.
* **The JSON-lines sink** (`JsonlCallJournal`, ADR-51). Each record is one line appended to
  `<data_dir>/logs/ai-calls/<folder>/<YYYY-MM-DD>.jsonl` under a thread lock and an OS file
  lock, written with one `write` call. A torn last line (a crash mid-write) is skipped by the
  reader, and the next append starts on a fresh line.

What is never journaled (FR-PROV-46, CT-PROV-31): an API key, any HTTP header, the provider's
raw HTTP envelope, and image bytes. The request is recorded from the caller's `PromptPayload`
(or the decision request's state and questions), never from the HTTP body, and an image field
is replaced by a descriptor: ``[page image: page 2 of 3, 812 KB, sha256 1a2b3c4d…]``.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import contextvars
import dataclasses
import hashlib
import json
import os
import re
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from .settings import _LOGGER
from .errors import (
    DecisionRequestRejectedError,
    MalformedResponseError,
    MissingConfidenceError,
)


# --- vocabulary (contract, CT-PROV-14) ----------------------------------------------------------

#: The kinds of call (FR-PROV-45), in the order the pipeline meets them.
CALL_KINDS: tuple[str, ...] = (
    "page_reading", "package_drafting", "rubric_setup", "answer_extraction", "ai_judge",
    "jev_decision", "feedback_writing", "help_question",
)

#: The kind recorded for a call made outside any `call_context`.
UNLABELLED_KIND = "unlabelled"

#: The outcome of one attempt. `retried` is any attempt the retry loop followed with another.
CALL_OUTCOMES: tuple[str, ...] = ("ok", "retried", "malformed", "rejected", "failed")

#: The context fields a record carries, besides `kind`.
CONTEXT_FIELDS: tuple[str, ...] = (
    "cohort_id", "run_id", "work_id", "submission_id", "criterion_id", "package_id",
)

#: The journal's home under the data folder (FR-CONSOLE-77). `M-STORE`'s purge deletes
#: `<data_dir>/logs/ai-calls/<cohort_id>/` by the same layout (CT-STORE-10).
JOURNAL_DIR_PARTS: tuple[str, ...] = ("logs", "ai-calls")

#: Folders for calls that belong to no class.
PACKAGES_FOLDER = "_packages"
HELP_FOLDER = "_help"
UNFILED_FOLDER = "_unfiled"

#: The payload field carried as an image (`live.IMAGE_FIELD`; repeated here so this module has
#: no import of the live providers).
_IMAGE_FIELD = "image_png_base64"

#: A run of base64 long enough to be binary data rather than text (CT-PROV-31's scan threshold).
_LONG_BASE64 = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")

#: Credential shapes scrubbed from any free text a record carries (an error message, an echo).
_CREDENTIAL_PATTERNS = (
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
)

_SAFE_FOLDER = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


# --- call context (FR-PROV-45) ------------------------------------------------------------------


@dataclass(frozen=True)
class CallContext:
    """What a call is about. Every field may be None; `kind` None records `unlabelled`.

    `page_no` and `page_count` are not record fields: they name the page an image field shows,
    for the image descriptor (FR-PROV-46)."""

    kind: str | None = None
    cohort_id: str | None = None
    run_id: str | None = None
    work_id: str | None = None
    submission_id: str | None = None
    criterion_id: str | None = None
    package_id: str | None = None
    page_no: int | None = None
    page_count: int | None = None


_CALL_CONTEXT: contextvars.ContextVar[CallContext] = contextvars.ContextVar(
    "aeh_prov_call_context", default=CallContext())


def current_call_context() -> CallContext:
    """The call context in force in this thread (or context copy)."""
    return _CALL_CONTEXT.get()


@contextlib.contextmanager
def call_context(**fields: Any) -> Iterator[CallContext]:
    """Label every provider call made inside the block (FR-PROV-45, ADR-52).

    Fields left out are inherited from the enclosing context, so an orchestrator can set the
    class, run and unit, and the stage worker inside it only the kind. A field passed as None
    is inherited too. On exit the enclosing context is restored, also on an exception."""
    unknown = set(fields) - {f.name for f in dataclasses.fields(CallContext)}
    if unknown:
        raise TypeError(f"call_context() got unknown field(s): {sorted(unknown)}")
    kind = fields.get("kind")
    if kind is not None and kind not in CALL_KINDS:
        raise ValueError(f"call_context(kind={kind!r}): the kinds are {list(CALL_KINDS)}")
    updates = {name: value for name, value in fields.items() if value is not None}
    merged = dataclasses.replace(_CALL_CONTEXT.get(), **updates)
    token = _CALL_CONTEXT.set(merged)
    try:
        yield merged
    finally:
        _CALL_CONTEXT.reset(token)


# --- the record (FR-PROV-44) --------------------------------------------------------------------


@dataclass(frozen=True)
class CallRecord:
    """One model call attempt. Field names and the `kind`/`outcome` vocabularies are contract
    (CT-PROV-14).

    `request` is the `PromptPayload` fields in order as `[name, value]` pairs (an image value
    replaced by its descriptor), or, for a decision, `{"state": ..., "questions": ...}`.
    `response` is `Completion.text` verbatim, or the decision's answers with their
    probabilities; None for an attempt that produced no accepted answer. `error` is
    `"<ErrorClass>: <message>"`, never a traceback. Token counts, `resolved_build` and `cost`
    are None where the attempt did not produce them; `cost` is a decimal string."""

    call_id: str
    attempt: int
    at: str
    kind: str
    cohort_id: str | None
    run_id: str | None
    work_id: str | None
    submission_id: str | None
    criterion_id: str | None
    package_id: str | None
    model: str
    resolved_build: str | None
    request: Any
    response: Any
    outcome: str
    error: str | None
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int | None
    cost: str | None

    def to_json_dict(self) -> dict[str, Any]:
        """The record as one JSON object, fields in declaration order."""
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}


@runtime_checkable
class CallJournal(Protocol):
    """Where records go. `append` is called once per attempt, from any thread."""

    def append(self, record: CallRecord) -> None: ...


# --- the process-wide slot (FR-CONSOLE-77) ------------------------------------------------------

_SLOT_LOCK = threading.Lock()
_INSTALLED: CallJournal | None = None


def install_call_journal(sink: CallJournal | None) -> CallJournal | None:
    """Put `sink` in force for every provider in this process, and return the sink it replaced.
    `None` uninstalls. An entry point that installs one restores the returned sink when it ends,
    so an in-process caller (a test, a second console) is left as it found the slot."""
    global _INSTALLED
    with _SLOT_LOCK:
        previous, _INSTALLED = _INSTALLED, sink
    return previous


def installed_call_journal() -> CallJournal | None:
    """The sink in force, or None."""
    return _INSTALLED


@contextlib.contextmanager
def journal_installed(sink: CallJournal | None) -> Iterator[CallJournal | None]:
    """Install `sink` for the block, then restore the previous one."""
    previous = install_call_journal(sink)
    try:
        yield sink
    finally:
        install_call_journal(previous)


# --- building records ---------------------------------------------------------------------------


def outcome_for(error: BaseException) -> str:
    """The final outcome an error ends a call with."""
    if isinstance(error, (MalformedResponseError, MissingConfidenceError)):
        return "malformed"
    if isinstance(error, DecisionRequestRejectedError):
        return "rejected"
    return "failed"


def _scrub(text: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    for pattern in _CREDENTIAL_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text


def _error_text(error: BaseException | None, secrets: tuple[str, ...]) -> str | None:
    if error is None:
        return None
    message = " ".join(str(error).split())
    return _scrub(f"{type(error).__name__}: {message}" if message else type(error).__name__,
                  secrets)


def _binary_descriptor(value: str, label: str) -> str:
    try:
        raw = base64.b64decode(value, validate=False)
    except (binascii.Error, ValueError):
        raw = value.encode("utf-8", "replace")
    kilobytes = max(1, round(len(raw) / 1024)) if raw else 0
    digest = hashlib.sha256(raw).hexdigest()[:8]
    return f"[{label}, {kilobytes} KB, sha256 {digest}…]"


def payload_request(fields: tuple[tuple[str, str], ...]) -> list[list[str]]:
    """A `PromptPayload`'s fields as the journal records them: in order, each image value
    replaced by its descriptor, and any other run of base64 over 200 characters replaced by a
    binary descriptor (FR-PROV-46)."""
    context = _CALL_CONTEXT.get()
    images = [index for index, (name, _value) in enumerate(fields) if name == _IMAGE_FIELD]
    recorded: list[list[str]] = []
    for index, (name, value) in enumerate(fields):
        if name == _IMAGE_FIELD:
            if len(images) == 1 and context.page_no is not None:
                page_no, page_count = context.page_no, context.page_count or context.page_no
            else:
                page_no, page_count = images.index(index) + 1, len(images)
            value = _binary_descriptor(value, f"page image: page {page_no} of {page_count}")
        else:
            value = _LONG_BASE64.sub(lambda m: _binary_descriptor(m.group(0), "binary data"),
                                     value)
        recorded.append([name, value])
    return recorded


def decision_request_document(state: str, questions: Mapping[str, Any]) -> dict[str, Any]:
    """A decision request as the journal records it: the state and the questions with their
    options, in the caller's order."""
    return {"state": state, "questions": dict(questions)}


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    return value


def decision_response_document(answers: Mapping[str, Any]) -> dict[str, Any]:
    """A decision's answers as the journal records them: per question key, the answer with its
    probabilities and confidence."""
    return {str(key): _jsonable(answer) for key, answer in answers.items()}


class AttemptJournal:
    """Journals the attempts of one provider call (FR-PROV-44).

    Built per call with `attempt_journal(...)`. Its `on_attempt` is handed to the retry loop,
    which calls it as each attempt ends; it is None when no sink is installed, so the loop
    does nothing extra. An attempt that ends `ok` is held until the provider calls
    `succeeded(...)` with the answer as returned (cost derived, latency measured); if the call
    raises after that, the held attempt is journaled as `failed` with the error."""

    def __init__(self, sink: CallJournal | None, *, model: str, request: Any,
                 secrets: tuple[str, ...]) -> None:
        self._sink = sink
        self._model = model
        self._request = request
        self._secrets = tuple(s for s in secrets if s)
        self._call_id = uuid.uuid4().hex
        self._context = _CALL_CONTEXT.get()
        self._held: tuple[int, int | None] | None = None
        self._attempts = 0
        self._finished = False
        self.on_attempt: Callable[..., None] | None = (
            self._on_attempt if sink is not None else None)

    @property
    def active(self) -> bool:
        return self._sink is not None

    def _on_attempt(self, attempt: int, outcome: str, error: BaseException | None = None,
                    latency_ms: int | None = None) -> None:
        self._attempts = max(self._attempts, attempt)
        if outcome == "ok":
            self._held = (attempt, latency_ms)
            return
        if outcome != "retried":
            self._finished = True
        self._emit(attempt=attempt, outcome=outcome, error=error, latency_ms=latency_ms)

    def succeeded(self, *, response: Any, resolved_build: str | None, tokens_in: int | None,
                  tokens_out: int | None, cost: Decimal | None,
                  latency_ms: int | None = None) -> None:
        """Journal the attempt that answered. A provider with no retry loop (the fixture)
        calls this without an `on_attempt`; it is then attempt 1."""
        if self._sink is None:
            return
        attempt, held_latency = self._held if self._held is not None else (self._attempts + 1,
                                                                          latency_ms)
        self._held = None
        self._finished = True
        self._emit(attempt=attempt, outcome="ok", error=None,
                   latency_ms=held_latency if held_latency is not None else latency_ms,
                   response=response, resolved_build=resolved_build, tokens_in=tokens_in,
                   tokens_out=tokens_out, cost=cost)

    def failed(self, error: BaseException) -> None:
        """Journal a call that raised before its final attempt was journaled."""
        if self._sink is None or self._finished:
            return
        if self._held is not None:
            attempt, latency = self._held
            self._held = None
        else:
            attempt, latency = self._attempts + 1, None
        self._finished = True
        self._emit(attempt=attempt, outcome=outcome_for(error), error=error, latency_ms=latency)

    def _emit(self, *, attempt: int, outcome: str, error: BaseException | None,
              latency_ms: int | None, response: Any = None, resolved_build: str | None = None,
              tokens_in: int | None = None, tokens_out: int | None = None,
              cost: Decimal | None = None) -> None:
        context = self._context
        if isinstance(response, str):
            response = _scrub(response, self._secrets) if self._secrets else response
        record = CallRecord(
            call_id=self._call_id, attempt=attempt,
            at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            kind=context.kind or UNLABELLED_KIND,
            cohort_id=context.cohort_id, run_id=context.run_id, work_id=context.work_id,
            submission_id=context.submission_id, criterion_id=context.criterion_id,
            package_id=context.package_id,
            model=self._model, resolved_build=resolved_build, request=self._request,
            response=response, outcome=outcome, error=_error_text(error, self._secrets),
            tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency_ms,
            cost=None if cost is None else str(cost),
        )
        hold = _HOLD.get()
        if hold is not None:
            hold.offer(record, self._sink)  # type: ignore[arg-type]
            return
        _append_safely(self._sink, record)  # type: ignore[arg-type]


def _append_safely(sink: CallJournal, record: CallRecord) -> None:
    try:
        sink.append(record)
    except Exception as failure:  # noqa: BLE001 - the journal never fails a model call
        _LOGGER.warning("the AI-call journal could not record a call: %s",
                        type(failure).__name__)


class _HeldRecords:
    """Records held back until what they are about is known (see `held_call_records`)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: list[tuple[CallRecord, CallJournal]] = []
        self._updates: dict[str, Any] = {}
        self._released = False

    def offer(self, record: CallRecord, sink: CallJournal) -> None:
        with self._lock:
            if not self._released:
                self._held.append((record, sink))
                return
            updates = dict(self._updates)
        _append_safely(sink, dataclasses.replace(record, **updates))

    def release(self, **updates: Any) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
            self._updates = {name: value for name, value in updates.items()
                             if value is not None}
            held, self._held = self._held, []
        for record, sink in held:
            _append_safely(sink, dataclasses.replace(record, **self._updates))


_HOLD: contextvars.ContextVar[_HeldRecords | None] = contextvars.ContextVar(
    "aeh_prov_call_hold", default=None)


@contextlib.contextmanager
def held_call_records() -> Iterator[None]:
    """Hold the records of calls made in the block until `release_held_call_records(...)`
    names what they are about, then write them with those context fields set; calls after the
    release are written at once, with the same fields. For a job whose subject is named by one
    of its own calls: drafting a package learns the package id from the model's inventory
    answer, and every drafting call belongs under that package (FR-CONSOLE-77). Records still
    held when the block ends are written as they are."""
    hold = _HeldRecords()
    token = _HOLD.set(hold)
    try:
        yield
    finally:
        _HOLD.reset(token)
        hold.release()


def release_held_call_records(**context: Any) -> None:
    """Release the enclosing `held_call_records` block with these context fields (for example
    `package_id=...`). Outside such a block it does nothing."""
    unknown = set(context) - set(CONTEXT_FIELDS)
    if unknown:
        raise TypeError(f"release_held_call_records() got unknown field(s): {sorted(unknown)}")
    hold = _HOLD.get()
    if hold is not None:
        hold.release(**context)


@contextlib.contextmanager
def attempt_journal(*, model: str, request: Callable[[], Any],
                    secrets: tuple[str, ...] = ()) -> Iterator[AttemptJournal]:
    """Journal one provider call's attempts. `request` is a thunk, so a call made with no sink
    installed never builds the record's request (an image descriptor hashes the image)."""
    sink = installed_call_journal()
    journal = AttemptJournal(sink, model=model, request=request() if sink is not None else None,
                             secrets=secrets)
    try:
        yield journal
    except BaseException as error:
        journal.failed(error)
        raise


# --- the JSON-lines sink (FR-CONSOLE-77, ADR-51) ------------------------------------------------


def journal_root(data_dir: str | os.PathLike[str]) -> Path:
    """`<data_dir>/logs/ai-calls`."""
    return Path(data_dir).joinpath(*JOURNAL_DIR_PARTS)


def journal_folder(record: CallRecord) -> tuple[str, ...]:
    """The folder a record is filed under, relative to the journal root: the class, else the
    package (`_packages/<id>`), `_help` for a help question, and `_unfiled` for a call with
    none of these. An id that is not a safe file name component is filed as `_unfiled`."""
    if record.kind == "help_question":
        return (HELP_FOLDER,)
    if record.cohort_id:
        return (record.cohort_id,) if _SAFE_FOLDER.match(record.cohort_id) else (UNFILED_FOLDER,)
    if record.package_id:
        if _SAFE_FOLDER.match(record.package_id):
            return (PACKAGES_FOLDER, record.package_id)
    return (UNFILED_FOLDER,)


#: An offset far past any journal line, locked as the cross-process append lock on Windows.
#: A region past the data keeps a concurrent reader from ever touching the locked bytes.
_LOCK_OFFSET = 0x7FFF0000


class _FileLock:
    """An exclusive OS lock on an open journal file, for appends from several processes."""

    def __init__(self, fd: int) -> None:
        self._fd = fd

    def __enter__(self) -> "_FileLock":
        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + 60.0
            while True:
                os.lseek(self._fd, _LOCK_OFFSET, os.SEEK_SET)
                try:
                    msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
                    return self
                except OSError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.005)
        import fcntl

        fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_exc: Any) -> None:
        if os.name == "nt":
            import msvcrt

            os.lseek(self._fd, _LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(self._fd, fcntl.LOCK_UN)


class JsonlCallJournal:
    """Appends each record as one JSON line to
    `<data_dir>/logs/ai-calls/<folder>/<YYYY-MM-DD>.jsonl` (FR-CONSOLE-77), the date being the
    record's UTC date. One `write` per line, under a process lock and an OS file lock, so lines
    from threads and processes never interleave; a torn last line is followed by a newline
    before the next record, so it never corrupts the record after it."""

    def __init__(self, data_dir: str | os.PathLike[str]) -> None:
        self._root = journal_root(data_dir)
        self._lock = threading.Lock()

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, record: CallRecord) -> Path:
        return self._root.joinpath(*journal_folder(record), f"{record.at[:10]}.jsonl")

    def append(self, record: CallRecord) -> None:
        line = json.dumps(record.to_json_dict(), ensure_ascii=False, default=str) + "\n"
        data = line.encode("utf-8")
        path = self.path_for(record)
        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, flags, 0o600)
            try:
                with _FileLock(fd):
                    size = os.fstat(fd).st_size
                    if size:
                        os.lseek(fd, size - 1, os.SEEK_SET)
                        if os.read(fd, 1) != b"\n":
                            data = b"\n" + data
                    written = os.write(fd, data)
                    while written < len(data):
                        written += os.write(fd, data[written:])
            finally:
                os.close(fd)


class ListCallJournal:
    """A sink that keeps records in memory, for a caller that wants them as objects."""

    def __init__(self) -> None:
        self.records: list[CallRecord] = []
        self._lock = threading.Lock()

    def append(self, record: CallRecord) -> None:
        with self._lock:
            self.records.append(record)


# --- reading ------------------------------------------------------------------------------------


def read_journal_file(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """The records in one journal file, in file order. A line that does not parse as a JSON
    object (a torn last line after a crash) is skipped."""
    records: list[dict[str, Any]] = []
    with open(path, "rb") as handle:
        for raw in handle:
            try:
                document = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(document, dict):
                records.append(document)
    return records


def journal_files(data_dir: str | os.PathLike[str], *folder: str) -> list[Path]:
    """Every journal file under the root (or under one folder of it), sorted by path."""
    base = journal_root(data_dir).joinpath(*folder)
    if not base.is_dir():
        return []
    return sorted(base.rglob("*.jsonl"))


def iter_call_records(data_dir: str | os.PathLike[str], *folder: str) -> Iterator[dict[str, Any]]:
    """Every readable record under the root (or one folder of it), file by file."""
    for path in journal_files(data_dir, *folder):
        yield from read_journal_file(path)
