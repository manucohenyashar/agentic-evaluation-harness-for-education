"""The request handling behind `/api/` and the same-origin SPA (FR-CONSOLE-45, CT-CONSOLE-30).

A mixin on the console's request handler, kept apart from `server.py` so the server-rendered
routes and the API's routes can each be read on their own. It owns no write: every API
mutation reaches the control surface through `ConsoleApp.perform`, looked up on the running
app at request time — the same door `POST /actions/<slug>` uses.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

from aeh.help import ScreenContext, parse_screen_context

from .help_read import (
    MANUAL_ID_PARAM,
    ask_payload,
    manual_payload,
    manuals_payload,
)

from .api import (
    API_ROUTES,
    ASK_CONTEXT_PARAM,
    ASK_QUERY_PARAM,
    UPLOAD_CONTROL,
    allowed_methods,
    ApiRoute,
    bundle_file,
    content_type_for,
    controls_payload,
    FileAnswer,
    match_route,
    READ_METHODS,
)
from .authoring_reads import authoring_draft_read, authoring_preview_read
from .class_actions import roster_preview_read
from .cohort_editor import roster_editor_payload
from .config_read import config_read
from .errors import ConsoleBindRefused
from .export_reads import readable_package_export_read, workbook_export_read
from .hub_state import hub_payload
from .parity import parity_inventory
from .results_reads import results_class_read, results_export_read, results_student_read
from .routes import SCREENS
from .run_start import run_start_preview_read
from .screen_reads import (
    blind_seats_read,
    class_roster_read,
    monitor_read,
    package_setup_read,
    papers_read,
    results_screen_read,
    review_queue_read,
    run_start_state_read,
    student_detail_read,
    system_status_read,
)
from .spa_reads import (
    context_read,
    impact_read,
    issues_read,
    job_read,
    jobs_read,
    logs_read,
    parked_read,
)
from .vocabulary import (
    AUTHORING_DRAFT_READ,
    AUTHORING_PREVIEW_READ,
    BLIND_SEATS_READ,
    CLASS_ROSTER_READ,
    CLI_HELP_READ,
    CONFIG_READ,
    CONTEXT_READ,
    IMPACT_READ,
    ISSUES_READ,
    JOB_READ,
    JOBS_READ,
    LOGS_READ,
    MONITOR_READ,
    PACKAGE_SETUP_READ,
    PAPERS_READ,
    PARKED_READ,
    READABLE_EXPORT_READ,
    RESULTS_CLASS_READ,
    RESULTS_EXPORT_READ,
    RESULTS_SCREEN_READ,
    RESULTS_STUDENT_READ,
    REVIEW_QUEUE_READ,
    ROSTER_PREVIEW_READ,
    RUN_START_PREVIEW_READ,
    RUN_START_STATE_READ,
    STUDENT_DETAIL_READ,
    SYSTEM_STATUS_READ,
    WORKBOOK_EXPORT_READ,
)

JSON_TYPE = "application/json; charset=utf-8"
ASSETS_PREFIX = "/assets/"
#: The largest refused body read off the socket before closing it; anything bigger is left
#: unread rather than spending a read on a request already refused.
REFUSED_BODY_DRAIN_BYTES = 64 * 1024


def outcome_json(action: str, outcome: Any) -> bytes:
    """A control outcome as the JSON both transports answer with. `next_action` is carried
    only when the action set one (a refusal's named next step, `CT-CONSOLE-33`, #761),
    `refresh_required` only when the outcome set it (§3.19's stale-screen refusal asks
    for the refresh, PR #794's finding 4), and `job_id` only when the outcome dispatched
    a job (`#760`'s authoring actions), so no outcome that predates any of the three
    fields changes shape."""
    answer = {
        "action": action,
        "dispatched": bool(getattr(outcome, "dispatched", False)),
        "refused": bool(getattr(outcome, "refused", False)),
        "detail": str(getattr(outcome, "detail", "")),
        "rows_written": len(getattr(outcome, "rows_written", ()) or ()),
    }
    next_action = getattr(outcome, "next_action", None)
    if next_action:
        answer["next_action"] = str(next_action)
    if getattr(outcome, "refresh_required", False):
        answer["refresh_required"] = True
    job_id = getattr(outcome, "job_id", None)
    if job_id:
        answer["job_id"] = str(job_id)
    return json.dumps(answer).encode("utf-8")


#: The reads the API answers, by the name a read route carries. Each takes the running
#: console, the console's app, the route's path parameters and the request's query string.
#: The first three are pure functions of the declared tables — no store is opened, so no
#: read can create or touch a stored byte. The hub read is a pure function of the console's
#: own held state (its config, its served run); the TS-148 reads (`run start preview`, the
#: results views, the export) reach the running app's store and M-ORCH/M-GRADE's doors; the
#: preview writes nothing (its cohort/package guards are read-only), and the export reads
#: the bytes `export_grade_artifacts` writes into a temporary directory. The manuals reads
#: are pure functions of the packaged manuals library. The ask read (`M-HELP`) is answered
#: by the mixin, not this table: its only write is the assistant's own Q&A log, written
#: after the model answered, so a refused or failed ask writes nothing (`CT-HELP-04`).
#: Each answers JSON, or a `FileAnswer` for the export's raw bytes.
_READS = {
    "controls": lambda _console, _app, _params, _query: controls_payload(),
    "screens": lambda _console, _app, _params, _query: {"screens": dict(SCREENS)},
    "roster editor": lambda _console, _app, _params, _query: roster_editor_payload(),
    "hub": lambda console, _app, _params, _query: hub_payload(console),
    RUN_START_PREVIEW_READ: lambda _console, app, _params, query: run_start_preview_read(app, query),
    RESULTS_CLASS_READ: lambda _console, app, _params, query: results_class_read(app, query),
    RESULTS_STUDENT_READ: lambda _console, app, _params, query: results_student_read(app, query),
    RESULTS_EXPORT_READ: lambda _console, app, _params, query: results_export_read(app, query),
    # #762 (FR-CONSOLE-58/59): the export reads — file answers beside the results export.
    WORKBOOK_EXPORT_READ: lambda _console, app, _params, query: workbook_export_read(app, query),
    READABLE_EXPORT_READ: lambda _console, app, _params, query: readable_package_export_read(
        app, query),
    "manuals": lambda _console, _app, _params, _query: manuals_payload(),
    "manual": lambda _console, _app, params, _query: manual_payload(params.get(MANUAL_ID_PARAM, "")),
    # #632: the parity inventory, generated from the live `aeh` parser — the read is pure
    # (it opens no store), so the help answers even before a cohort exists.
    CLI_HELP_READ: lambda _console, _app, _params, _query: parity_inventory(),
    # #635 (FR-UI-03): the lifecycle screens' reads. Each takes the console (for its bound
    # run), the app (the store and the modules' doors) and the query (a run or cohort named
    # per request), writes nothing, and answers a document the SPA renders as is.
    PACKAGE_SETUP_READ: lambda console, app, _params, query: package_setup_read(console, app, query),
    CLASS_ROSTER_READ: lambda _console, app, _params, query: class_roster_read(_console, app, query),
    PAPERS_READ: lambda console, app, _params, query: papers_read(console, app, query),
    RUN_START_STATE_READ: lambda console, app, _params, query: run_start_state_read(console, app, query),
    MONITOR_READ: lambda console, app, _params, query: monitor_read(console, app, query),
    REVIEW_QUEUE_READ: lambda console, app, _params, query: review_queue_read(console, app, query),
    BLIND_SEATS_READ: lambda console, app, _params, query: blind_seats_read(console, app, query),
    RESULTS_SCREEN_READ: lambda console, app, _params, query: results_screen_read(console, app, query),
    STUDENT_DETAIL_READ: lambda console, app, _params, query: student_detail_read(console, app, query),
    SYSTEM_STATUS_READ: lambda _console, app, _params, query: system_status_read(_console, app, query),
    # #755 (FR-CONSOLE-47…52, FR-CONSOLE-60): the redesign SPA's read surface. Each takes
    # the console, the app and the query like the reads above, and answers a document the
    # SPA renders as is. The authoring preview is the one POST read: its `query` argument
    # is the request's JSON body, because the uploaded documents cannot travel in a URL
    # (`CT-CONSOLE-34`), and it writes nothing anywhere.
    CONTEXT_READ: lambda console, app, _params, query: context_read(console, app, query),
    IMPACT_READ: lambda _console, app, _params, query: impact_read(_console, app, query),
    JOBS_READ: lambda _console, app, _params, query: jobs_read(_console, app, query),
    JOB_READ: lambda _console, app, params, query: job_read(_console, app, {**query, **params}),
    ISSUES_READ: lambda _console, app, _params, query: issues_read(_console, app, query),
    LOGS_READ: lambda _console, app, _params, query: logs_read(_console, app, query),
    PARKED_READ: lambda _console, app, _params, query: parked_read(_console, app, query),
    CONFIG_READ: lambda _console, app, _params, query: config_read(_console, app, query),
    AUTHORING_PREVIEW_READ: lambda _console, _app, _params, body: authoring_preview_read(
        _console, _app, body),
    AUTHORING_DRAFT_READ: lambda _console, app, _params, query: authoring_draft_read(
        _console, app, query),
    # FR-CONSOLE-63 (#761): the roster file import's preview — the second POST read. Like
    # the authoring preview, its `query` argument is the request's JSON body (the roster
    # file's text cannot travel in a URL, `CT-CONSOLE-34`), and it writes nothing anywhere.
    ROSTER_PREVIEW_READ: lambda _console, _app, _params, body: roster_preview_read(
        _console, _app, body),
}


class ApiRequestsMixin:
    """`/api/` routed from `API_ROUTES`, and the SPA bundle served from `spa_dir`."""

    # -- the SPA ----------------------------------------------------------------------------

    def _serve_spa_index(self) -> bool:
        """Serve the bundle's `index.html` at `/`, if the bundle is there."""
        index = bundle_file(self._console.spa_dir, "index.html")
        if index is None:
            return False
        self._respond(200, index.read_bytes(), content_type_for(index))
        return True

    def _serve_bundle_asset(self, route: str) -> bool:
        """Serve `/assets/<file>` from the bundle's `assets/` directory, if the file is there."""
        if not route.startswith(ASSETS_PREFIX):
            return False
        relative = "assets/" + route[len(ASSETS_PREFIX):]
        found = bundle_file(self._console.spa_dir, relative)
        if found is None:
            return False
        self._respond(200, found.read_bytes(), content_type_for(found))
        return True

    # -- the API ----------------------------------------------------------------------------

    def _serve_api(self, method: str, route: str, query: dict[str, str] | None = None) -> None:
        """Dispatch one `/api/` request through the route table, and nothing else."""
        matched, params, other_verb = match_route(method, route)
        if matched is None:
            # The connection is closed after the answer (see `_not_found`). A small declared
            # body is drained first: closing a Windows socket with unread bytes resets it, and
            # the client then never sees the 404/405 it was owed.
            self._drain_small_body()
            if other_verb:
                self._respond(405, b'{"error":"method not allowed"}', JSON_TYPE, close=True,
                              headers={"Allow": ", ".join(allowed_methods(route))})
            else:
                self._respond(404, b'{"error":"not found"}', JSON_TYPE, close=True)
            return
        if matched.read is not None:
            # A read dispatches on its read label, whatever verb it answers under: the
            # authoring preview (#755) is a POST read whose census label sits in
            # `control`, but it answers through the read path and writes nothing.
            self._api_read(matched, params, query or {})
            return
        if matched.control is None:
            self._api_read(matched, params, query or {})
            return
        try:
            self._console.recheck_environment()
        except ConsoleBindRefused as refusal:
            body = json.dumps({"error": str(refusal)}).encode("utf-8")
            self._drain_small_body()
            self._respond(403, body, JSON_TYPE, close=True)
            return
        if matched.control == UPLOAD_CONTROL:
            self._upload()
            return
        self._api_control(matched, params)

    def _api_read(self, route: ApiRoute, path_params: dict[str, str],
                  query: dict[str, str]) -> None:
        """One read: the reader's answer as JSON, or a `FileAnswer`'s bytes with their own
        media type. A refusal is a 400 — a read asked for something that is not there is
        the caller's mistake, and the body carries the named gap; anything else is a 500
        with the connection closed, so a failed read is answered, never a dropped socket.
        The ask read (`M-HELP`) is dispatched here rather than in `_READS`: its only write
        is the assistant's own Q&A log, written after the model answered. A POST read (the
        authoring preview) takes the request's JSON body as its `query` argument — the
        documents cannot travel in a URL (`CT-CONSOLE-34`) — and the body is read before
        any answer is written, the way every body-bearing route must."""
        if route.read == "help ask":
            self._help_ask(query)
            return
        if route.method not in READ_METHODS:
            if self.headers.get("Transfer-Encoding"):
                self._respond(411, b'{"error":"a JSON body requires Content-Length"}',
                              JSON_TYPE, close=True)
                return
            length = self._declared_length()
            if length is None:
                self._respond(400, b'{"error":"invalid Content-Length"}', JSON_TYPE, close=True)
                return
            body = self._read_json_object(length)
            if body is None:
                self._respond(400, b'{"error":"the body must be a JSON object"}', JSON_TYPE)
                return
            query = body  # type: ignore[assignment] — a POST read's query is its body
        reader = _READS[str(route.read)]
        try:
            answer = reader(self._console, self._console.app, path_params, query)
        except (ValueError, KeyError) as refusal:
            body = json.dumps({"error": str(refusal)}).encode("utf-8")
            self._respond(400, body, JSON_TYPE)
            return
        except Exception as error:  # noqa: BLE001 — a failed read is a 500, never a dropped socket
            body = json.dumps({"error": str(error)}).encode("utf-8")
            self._respond(500, body, JSON_TYPE, close=True)
            return
        if answer is None:
            body = json.dumps({"error": "not found"}).encode("utf-8")
            self._respond(404, body, JSON_TYPE, close=True)
            return
        if isinstance(answer, FileAnswer):
            self._respond(200, answer.body, answer.content_type)
            return
        self._respond(200, json.dumps(answer).encode("utf-8"), JSON_TYPE)

    def _help_ask(self, query: dict[str, str]) -> None:
        """The grounded Q&A ask (`M-HELP`, `CT-HELP-01`): one read-only GET whose only write
        is the assistant's own Q&A log row, written after the model answered.

        The optional `context` query parameter (FR-HELP-06) carries the JSON of
        ``{screen, refs}`` — the ids the asking screen already renders. It is parsed here, at
        the edge, so a malformed or smuggled shape is the caller's mistake and answers 400
        before anything reaches the model; the assistant joins what survives to the prompt as
        the identifiers it is (`CT-UI-07`)."""
        question = query.get(ASK_QUERY_PARAM, "").strip()
        if not question:
            body = json.dumps(
                {"error": "the ask read takes the question as ?q=<question>"}
            ).encode("utf-8")
            self._respond(400, body, JSON_TYPE)
            return
        raw_context = query.get(ASK_CONTEXT_PARAM, "").strip()
        context: ScreenContext | None = None
        if raw_context:
            try:
                context = parse_screen_context(json.loads(raw_context))
            except ValueError as refusal:  # JSONDecodeError is one, as is every shape refusal
                body = json.dumps(
                    {"error": f"the ask read could not take the context: {refusal}"}
                ).encode("utf-8")
                self._respond(400, body, JSON_TYPE)
                return
        try:
            payload = ask_payload(self._console.help_assistant(), question, context)
        except Exception as error:  # noqa: BLE001 — a failed ask is a 500, never a dropped socket
            body = json.dumps({"error": str(error)}).encode("utf-8")
            self._respond(500, body, JSON_TYPE, close=True)
            return
        self._respond(200, json.dumps(payload).encode("utf-8"), JSON_TYPE)

    def _api_control(self, route: ApiRoute, path_params: dict[str, str]) -> None:
        """Pass the request's parameters to the door unvalidated: refusing a malformed request
        is `perform`'s job, and it reports the refusal (FR-CONSOLE-34)."""
        if self.headers.get("Transfer-Encoding"):
            # A chunked body is not decoded here; left on the socket it would be parsed as the
            # next request, so the refusal closes the connection (the `_upload` precedent).
            self._respond(411, b'{"error":"a JSON body requires Content-Length"}', JSON_TYPE,
                          close=True)
            return
        length = self._declared_length()
        if length is None:
            self._respond(400, b'{"error":"invalid Content-Length"}', JSON_TYPE, close=True)
            return
        body = self._read_json_object(length)
        if body is None:
            self._respond(400, b'{"error":"the body must be a JSON object"}', JSON_TYPE)
            return
        action = str(route.control)
        try:
            outcome = self._console.app.perform(action, **{**body, **path_params})
        except (TypeError, ValueError, KeyError) as refusal:
            answer = json.dumps({"action": action, "error": str(refusal)}).encode("utf-8")
            self._respond(400, answer, JSON_TYPE)
            return
        except Exception as error:  # noqa: BLE001 — a failed action is a 500, never a dropped socket
            answer = json.dumps({"action": action, "error": str(error)}).encode("utf-8")
            self._respond(500, answer, JSON_TYPE, close=True)
            return
        self._respond(200, outcome_json(action, outcome), JSON_TYPE)

    def _declared_length(self) -> int | None:
        """The declared `Content-Length`: 0 when absent, `None` when it is not a
        non-negative integer (a negative one would read to EOF and hold the thread)."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        return length if length >= 0 else None

    def _drain_small_body(self) -> None:
        """Read and discard a refused request's body when it declares a length within
        `REFUSED_BODY_DRAIN_BYTES`; a larger or undeclared one is left unread."""
        length = self._declared_length()
        if length and length <= REFUSED_BODY_DRAIN_BYTES and not self.headers.get(
            "Transfer-Encoding"
        ):
            self.rfile.read(length)

    def _read_json_object(self, length: int) -> dict[str, Any] | None:
        """The request body as a JSON object; an empty body is `{}`, anything else `None`."""
        raw = self.rfile.read(length) if length else b""
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None


__all__ = ["API_ROUTES", "ApiRequestsMixin", "outcome_json"]
