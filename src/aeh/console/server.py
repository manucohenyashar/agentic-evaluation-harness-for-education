"""The HTTP server: the declared routes, bounded request bodies, and loopback-only binding."""

from __future__ import annotations

import contextlib
import json
import os
import re
import socket
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit
from typing import Any

from aeh.conf import effective_config

from . import manuals_page
from .settings import CONSOLE_BIND
from .routes import CLOUD_HOSTED_PROFILE, LOOPBACK_ADDRESSES, SCREENS
from .vocabulary import CONTROL_SURFACE_ACTIONS
from .queries import _SELECT_CROP_REF_KNOWN
from .errors import ConsoleBindRefused
from .html import _row_get, _stylesheet_bytes
from .uploads import _record_upload_part, upload_scans
from .run_planning import build_console
from .api import SPA_BUNDLE_DIR, API_ROUTES, action_slug as _action_slug
from .api_handler import _READS, ApiRequestsMixin, outcome_json

#: Paths the API owns: everything under it is routed from `API_ROUTES` and nothing else.
_API_ROOT = "/api/"


#: slug -> action, for `POST /actions/<slug>`. Built from the declared set rather than written
#: out, so a sixteenth action cannot be reachable over HTTP without appearing in
#: `CONTROL_SURFACE_ACTIONS` first — the allow-list and the routing table are one object.
CONTROL_ACTION_SLUGS: dict[str, str] = {
    _action_slug(action): action for action in CONTROL_SURFACE_ACTIONS
}


if len(CONTROL_ACTION_SLUGS) != len(CONTROL_SURFACE_ACTIONS):  # pragma: no cover — import-time
    raise AssertionError(
        "two control actions share a URL slug, so one of them would be unreachable over HTTP: "
        f"{sorted(CONTROL_SURFACE_ACTIONS)}"
    )


class _BoundedReader:
    """Reads exactly `limit` bytes of `stream` and no more.

    An upload reads from a keep-alive connection, where the bytes after the body are the NEXT
    request. Reading to EOF would swallow it, so the body is bounded by its declared length and
    `consumed` lets the caller refuse a short one rather than store a truncated document."""

    def __init__(self, stream: Any, limit: int) -> None:
        self._stream = stream
        self._remaining = max(0, int(limit))
        self.consumed = 0

    def read(self, size: int = -1) -> bytes:
        if self._remaining <= 0:
            return b""
        take = self._remaining if size is None or size < 0 else min(size, self._remaining)
        chunk = self._stream.read(take)
        self._remaining -= len(chunk)
        self.consumed += len(chunk)
        return chunk


def _known_route(route: str) -> bool:
    """Whether `route` is one of the declared screens.

    `ConsoleApp._resolve` falls back to S1 for anything it does not recognise — the right
    behaviour for a render, and the wrong one for a server, which owes an unknown path a 404
    rather than somebody else's page (`FR-CONSOLE-33`). So the server asks this first, over the
    same `SCREENS` table `_resolve` walks."""
    for template in SCREENS.values():
        if route == template:
            return True
        if re.fullmatch(re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", template), route):
            return True
    return route == "/"


class _ConsoleRequestHandler(ApiRequestsMixin, BaseHTTPRequestHandler):
    """Serves the routes FR-CONSOLE-33 declares, and nothing else.

    Every response carries `Cache-Control: no-store`: the console renders student records, and
    a cached page is a record sitting in a browser's disk cache after the run it belongs to is
    over. That header is set in one place (`_respond`) so a route cannot forget it.
    """

    server_version = "aeh-console"
    protocol_version = "HTTP/1.1"
    # Answer immediately: the API's responses are small and written header-write then
    # body-write, so with Nagle (the socketserver default) the second segment waits on a
    # delayed ACK — a screen read that answers in 5ms once warm costs 50-100ms on a fresh
    # connection. `TCP_NODELAY` on every accepted socket is what keeps reads uniform.
    disable_nagle_algorithm = True

    @property
    def _console(self) -> "ConsoleServer":
        return self.server.console  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        """Silent by default: the console's record is its pages and the database, and an access log
        on stderr would mix with test output."""

    def _respond(
        self, status: int, body: bytes, content_type: str, *, close: bool = False,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if close:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        if close:
            self.close_connection = True

    def _not_found(self) -> None:
        """Send 404 and end the connection.

        Every refusal path answers WITHOUT reading the request body, and this is HTTP/1.1, so
        leaving the connection open would have the unread body parsed as the next request:
        a refused control action followed by a smuggled `GET /students/<ref>` on the same
        socket, which is the disclosure the refusal exists to prevent. Closing is the one fix
        that does not require trusting a body the server has already declined to accept."""
        self._respond(404, b"not found\n", "text/plain; charset=utf-8", close=True)

    def _serve_crop(self, crop_ref: str) -> None:
        """Serve screen S8's crop image (FR-CONSOLE-29, #530), only when a stored region's
        `crop_ref` names it, so this route can never read any other stored file."""
        app = self._console.app
        known = False
        try:
            known = any(int(_row_get(row, "n") or 0) for row in app._read_cohort_files(
                _SELECT_CROP_REF_KNOWN, [], crop_ref=crop_ref))
            data = app._store.blobs().get(crop_ref) if known else None
        except Exception:  # noqa: BLE001 — an unreadable crop is a 404, never a 500 with detail
            data = None
        if not known or not data:
            self._not_found()
            return
        self._respond(200, bytes(data), "image/png")

    def do_GET(self) -> None:  # noqa: N802 — the stdlib's dispatch name
        parsed = urlsplit(self.path)
        route = parsed.path
        if route.startswith(_API_ROOT):
            # FR-CONSOLE-43/44: the API's reads take query parameters (the run-start
            # preview's cohort, package version and per-request profile; the results
            # views' run and revision) — the screens path re-derives theirs per render,
            # the API reads receive them.
            api_query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
            self._serve_api("GET", route, api_query)
            return
        # FR-CONSOLE-45: the SPA bundle, once it ships, answers `/` and `/assets/…`; until it
        # does (#634), the server-rendered catalog and stylesheet answer as before.
        if route == "/" and self._serve_spa_index():
            return
        if self._serve_bundle_asset(route):
            return
        if route == "/assets/console.css":
            try:
                body = _stylesheet_bytes()
            except OSError:
                self._not_found()
                return
            self._respond(200, body, "text/css; charset=utf-8")
            return
        # The manuals pages (M-HELP, FR-HELP-01): the targets the Q&A panel's citations
        # point at. Served directly, like the stylesheet above — the HLD's thirteen screens
        # are not the only text the console serves, and the SPA never calls the manuals
        # reads, so the panel's traffic stays exactly the ask endpoint (TC-REQ-129).
        if route == "/manuals":
            self._respond(200, manuals_page.manuals_library_html().encode("utf-8"),
                          "text/html; charset=utf-8")
            return
        if route.startswith("/manuals/"):
            page = manuals_page.manual_page_html(unquote(route[len("/manuals/"):]))
            if page is None:
                self._not_found()
                return
            self._respond(200, page.encode("utf-8"), "text/html; charset=utf-8")
            return
        if route.startswith("/blobs/"):
            self._serve_crop(route[len("/blobs/"):])
            return
        if not _known_route(route):
            self._not_found()
            return
        # `render(route, **query)` takes `route` positionally, so a query string carrying its
        # own `route=` (or `self=`) raised `TypeError` out of the handler and the client saw a
        # closed connection rather than a status. A URL cannot name the handler's own
        # parameters.
        query = {
            key: values[-1]
            for key, values in parse_qs(parsed.query).items()
            if key not in ("route", "self")
        }
        try:
            page = self._console.app.render(route, **query)
        except Exception as error:  # noqa: BLE001 — a page is a read; a failed read is a 500
            body = f"the console could not render {route}: {error}\n".encode("utf-8")
            self._respond(500, body, "text/plain; charset=utf-8", close=True)
            return
        self._respond(200, str(page.html).encode("utf-8"), "text/html; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802 — the stdlib's dispatch name
        route = urlsplit(self.path).path
        if route.startswith(_API_ROOT):
            self._serve_api("POST", route)
            return
        if route == "/upload":
            self._upload()
            return
        if not route.startswith("/actions/"):
            self._not_found()
            return
        # The slug allow-list is the declared control surface, checked BEFORE the body is read
        # and before any door is called: an undeclared slug must not be able to reach a store
        # at all, so it is a 404 with no write rather than a refusal the ledger records.
        action = CONTROL_ACTION_SLUGS.get(route[len("/actions/"):])
        if action is None:
            self._not_found()
            return
        # `FR-CONSOLE-36`: the effective config is resolved again here, not just at start, so a
        # profile or bind changed in the environment after the server came up is refused on the
        # action rather than honoured.
        try:
            self._console.recheck_environment()
        except ConsoleBindRefused as refusal:
            self._respond(
                403, f"{refusal}\n".encode("utf-8"), "text/plain; charset=utf-8", close=True
            )
            return
        form = self._read_form()
        outcome = self._console.app.perform(action, **form)
        self._respond(200, outcome_json(action, outcome), "application/json; charset=utf-8")

    def _other_verb(self, method: str) -> None:
        """PUT, PATCH and DELETE: routed only where `API_ROUTES` lists them (it lists none
        today), so anything else is a 404/405 rather than the stdlib's 501."""
        route = urlsplit(self.path).path
        if route.startswith(_API_ROOT):
            self._serve_api(method, route)
            return
        self._not_found()

    def do_PUT(self) -> None:  # noqa: N802 — the stdlib's dispatch name
        self._other_verb("PUT")

    def do_PATCH(self) -> None:  # noqa: N802 — the stdlib's dispatch name
        self._other_verb("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802 — the stdlib's dispatch name
        self._other_verb("DELETE")

    def _read_form(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        return {key: values[-1] for key, values in parse_qs(raw).items()}

    def _upload(self) -> None:
        """Pass the request body to `upload_scans`.

        Not a second implementation: `upload_scans` is where `FR-CONSOLE-04`'s chunked walk
        and `FR-CONSOLE-13`'s `%PDF-` magic check live, and a route that staged bytes itself
        would be an upload path with no format check and no `UploadOutcome` — an orphan blob
        no intake ever consumes.

        The body is read through a bounded reader rather than to EOF, because on a keep-alive
        connection the bytes after it are the next request."""
        length_header = self.headers.get("Content-Length")
        if length_header is None:
            # No declared length means a chunked body, which this route does not decode. Saying
            # so is the honest answer; the alternative was storing the hash of nothing and
            # answering 200.
            self._respond(
                411, b"upload requires Content-Length\n", "text/plain; charset=utf-8",
                close=True,
            )
            return
        length = int(length_header)
        query = {k: v[-1] for k, v in parse_qs(urlsplit(self.path).query).items()}
        reader = _BoundedReader(self.rfile, length)
        outcome = upload_scans(
            self._console.app,
            cohort_id=str(query.get("cohort_id", "c-unaddressed")),
            size_bytes=length,
            stream=reader,
            filename=str(query.get("filename", "")),
            record=False,
        )
        if reader.consumed != length:
            # A client that disconnected mid-body: the staged chunks are a truncated document,
            # and answering 200 would hand back an address for it.
            self._respond(
                400,
                f"upload ended after {reader.consumed} of {length} bytes\n".encode("utf-8"),
                "text/plain; charset=utf-8", close=True,
            )
            return
        if outcome.dispatched and outcome.blob_refs and query.get("filename"):
            # The whole body arrived: only now is the part recorded (#531 review).
            _record_upload_part(self._console.app, str(query.get("cohort_id", "")),
                                str(query.get("filename")), str(outcome.blob_refs[0]))
        body = json.dumps({
            "dispatched": bool(outcome.dispatched),
            "blob_refs": [str(ref) for ref in outcome.blob_refs],
            "detail": str(outcome.detail),
        }).encode("utf-8")
        self._respond(200 if outcome.dispatched else 400, body, "application/json; charset=utf-8")


class _ConsoleHTTPServer(ThreadingHTTPServer):
    """A `ThreadingHTTPServer` that knows which `ConsoleServer` it serves."""

    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address: tuple, handler: type, console: "ConsoleServer") -> None:
        self.console = console
        # Every accepted connection, until its own handler closes it. `ThreadingHTTPServer`
        # serves each on its own daemon thread, so a plain `shutdown()` stops only the accept
        # loop: connections already accepted keep answering (a browser's kept-alive socket
        # would read 200s from a console that is supposed to be gone). Tracking them here is
        # what lets `ConsoleServer.terminate()` end those too.
        self._accepted: set[socket.socket] = set()
        self._accepted_lock = threading.Lock()
        # The family follows the address rather than defaulting to IPv4: `CONSOLE_BIND=::1` is
        # a legal loopback bind (`TC-CONSOLE-05` uses it as the discriminating probe that the
        # knob is read at all), and binding it on an `AF_INET` socket raises `gaierror`.
        if ":" in str(address[0]):
            self.address_family = socket.AF_INET6
        super().__init__(address, handler)

    def process_request(self, request: socket.socket, client_address: Any) -> None:
        with self._accepted_lock:
            self._accepted.add(request)
        super().process_request(request, client_address)

    def close_request(self, request: socket.socket) -> None:
        super().close_request(request)
        with self._accepted_lock:
            self._accepted.discard(request)

    def stop_accepted_connections(self) -> None:
        """Shut down and close every connection this server has accepted and not yet closed.

        Forcing `SHUT_RDWR` (rather than the half-close a finished handler does) unblocks a
        handler thread sitting in a keep-alive read, so the browser's next request over the
        socket fails instead of being answered by a console that has stopped."""
        with self._accepted_lock:
            sockets = list(self._accepted)
            self._accepted.clear()
        for live in sockets:
            with contextlib.suppress(Exception):
                live.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(Exception):
                live.close()


class ConsoleServer:
    """A running console: one in-process `ThreadingHTTPServer` on the configured loopback address
    (ADR-17).

    There is no child process. Runs execute in-process and the ledger makes them resumable,
    so killing the server stops them and `recover` picks them up (`NFR-CONSOLE-03`,
    `NFR-CONSOLE-08`) — which is why the child-process design this replaced bought nothing.
    `terminate()` shuts the server down, closes the port and joins the serving thread, so
    "the console is gone" is a state a caller can actually observe.
    """

    def __init__(
        self,
        store: Any = None,
        *,
        run_id: str | None = None,
        cfg: dict[str, Any] | None = None,
        bind: str | None = None,
        port: int | None = None,
        environ: Any = None,
        spa_dir: Any = None,
        help_assistant: Any = None,
    ) -> None:
        self._cfg = dict(cfg or {})
        #: Where `/` and `/assets/` are served from (FR-CONSOLE-45): the packaged bundle unless a
        #: caller names another — the seam that serves a known bundle without touching package data.
        self.spa_dir = Path(spa_dir) if spa_dir is not None else SPA_BUNDLE_DIR
        self._environ = environ
        self._bind = bind
        config = self._effective()
        self._refuse_unless_servable(config, bind)
        self.bind_address = self._resolved_bind(config, bind)
        host = "::1" if str(self.bind_address) == "::1" else "127.0.0.1"
        resolved_port = port if port is not None else (config.get("CONSOLE_PORT") or 0)
        self._store = store
        self._run_id = run_id
        #: A caller-supplied QA assistant, the way `spa_dir` names a bundle: the seam a
        #: recorded-provider tier configures the ask with (operator plan §4 rule 7), in place
        #: of the lazily built one below. `None` keeps the production rule unchanged.
        self._help_assistant: Any = help_assistant
        self.app = build_console(store=store, bind_address=str(self.bind_address))
        # "start run" resolves the run configuration the server was started with.
        self.app.run_config = self._effective()
        # And a run NAMED per request (`run_start.py`) re-selects its profile section from
        # the configuration file itself — `run_config` is already profile-flattened, its
        # `profiles` table gone, so the raw file is what a section selection needs.
        self.app.file_config = dict(self._cfg)
        self._httpd = _ConsoleHTTPServer(
            (host, int(resolved_port)), _ConsoleRequestHandler, self
        )
        self.socket = self._httpd.socket
        self.returncode: int | None = None
        self._closed = False
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="aeh-console", daemon=True
        )
        self._thread.start()
        self._warm_reads()

    def _warm_reads(self) -> None:
        """One throwaway in-process call per parameterless read route's reader, before use.

        A fresh server's first handling of an endpoint carries one-time cost — lazy imports,
        the first open of a package's tier file — that a screen read is otherwise asked to
        absorb inside a browser's check window (CT-UI-04, PERF-19): a read that answers in a
        millisecond warm answered in fifty cold. The warm-up calls the readers directly
        through the dispatch table the handler uses, so the cost is paid once, at start, on
        the same code path the request will take — without the HTTP hop, which would make
        the console an egress-capable module outside M-PROV (TC-PROV-05). Every failure is
        swallowed: a read the store cannot answer yet is still a route whose imports and
        doors are warm."""
        for route in API_ROUTES:
            if route.method != "GET" or "{" in route.path:
                continue
            reader = _READS.get(str(route.read))
            if reader is None:
                continue
            with contextlib.suppress(Exception):
                reader(self, self.app, {}, {})

    # -- configuration (`FR-CONSOLE-36`) -----------------------------------------------------

    def _effective(self) -> dict:
        """The effective configuration: environment variables over `cfg`, recomputed each time.

        Asked again on every control action rather than cached, so `HARNESS_PROFILE` or
        `CONSOLE_BIND` changed after start is honoured — the whole point of resolving through
        `conf.effective_config` rather than reading `cfg`."""
        return effective_config(self._cfg, self._environ)

    @staticmethod
    def _resolved_bind(config: dict, bind: str | None) -> str:
        return bind or config.get("CONSOLE_BIND") or CONSOLE_BIND

    @classmethod
    def _refuse_unless_servable(cls, config: dict, bind: str | None) -> None:
        """Run the two start-up refusals, in the order that makes them real refusals.

        The profile first (`CT-CONSOLE-20`): a routable bind must not be able to argue with
        it, so no bind validation happens before this line."""
        if config.get("HARNESS_PROFILE") == CLOUD_HOSTED_PROFILE:
            raise ConsoleBindRefused(
                "the console refuses to start under the cloud-hosted profile: authN/authZ is "
                "none by design, and the refusal keys on the deployment profile, not on any "
                "setting (FR-CONSOLE-05, CT-CONSOLE-05)."
            )
        address = cls._resolved_bind(config, bind)
        if str(address) not in LOOPBACK_ADDRESSES:
            raise ConsoleBindRefused(
                f"the console refuses a non-loopback bind ({address!r}): an "
                "unauthenticated student-record system runs on one machine, loopback only "
                "(FR-CONSOLE-05, R68)."
            )

    def recheck_environment(self) -> None:
        """Re-read the configuration and re-run the refusals before a control action
        (FR-CONSOLE-36)."""
        self._refuse_unless_servable(self._effective(), self._bind)

    # -- lifecycle ---------------------------------------------------------------------------

    @property
    def store(self) -> Any:
        return self._store

    @property
    def run_id(self) -> str | None:
        """The run the console serves, as `serve_console` was given it (`None` when none)."""
        return self._run_id

    @property
    def port(self) -> int:
        return int(self.socket.getsockname()[1])

    def help_assistant(self) -> Any:
        """The manuals Q&A assistant (M-HELP), built on the first ask and held for this
        server's life.

        Built here, not at start, so a console whose configuration names no QA model starts
        and serves the manuals and refuses at the ask instead (`help_read.resolve_help_model`);
        held thereafter because the manuals are package data — the index cannot go stale
        within a process, and rebuilding it per ask would spend the retrieval budget
        (`NFR-HELP-01`) on nothing.
        """
        if self._help_assistant is None:
            from .help_read import build_help_assistant

            self._help_assistant = build_help_assistant(self._store, self._effective())
        return self._help_assistant

    @property
    def pid(self) -> int:
        """This process's id. The console runs in-process (ADR-17), so there is no other process;
        the property remains because callers use it in messages."""
        return os.getpid()

    def terminate(self) -> None:
        """Stop serving: shut down the loop, close the port, end the accepted connections and
        join the thread.

        Ending the accepted connections is what makes "the console is gone" hold for a
        connected client too (FR-UI-07's degradation arms on it): without it, a browser's
        kept-alive socket would keep being answered after the port refuses new connections.
        `returncode` is set to 0 once the thread is joined — the observable "it is really
        stopped" the child-process design used an exit status for."""
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(Exception):
            self._httpd.shutdown()
        self._httpd.stop_accepted_connections()
        with contextlib.suppress(Exception):
            self._httpd.server_close()
        self._thread.join(timeout=10)
        self.returncode = 0 if not self._thread.is_alive() else None
        with contextlib.suppress(Exception):
            self.socket.close()


def serve_console(
    store: Any = None,
    *,
    run_id: str | None = None,
    cfg: dict[str, Any] | None = None,
    environ: Any = None,
    spa_dir: Any = None,
    help_assistant: Any = None,
) -> ConsoleServer:
    """Serve the console. Before binding it refuses, in this order: the `cloud-hosted` deployment
    profile (never allowed, whatever the settings), then any non-loopback address. Both are read
    from the effective configuration, with environment variables taking priority over `cfg`
    (FR-CONSOLE-36). `spa_dir` names the SPA bundle to serve at `/` and `/assets/`; the
    packaged one (`SPA_BUNDLE_DIR`) when omitted (FR-CONSOLE-45). `help_assistant` names a
    prebuilt QA assistant the ask is answered with (the recorded-provider seam, operator plan
    §4 rule 7); when omitted the assistant is built lazily at the first ask from the effective
    configuration (`FR-CONF-30`)."""
    return ConsoleServer(store, run_id=run_id, cfg=cfg, environ=environ, spa_dir=spa_dir,
                         help_assistant=help_assistant)


def start_console(
    cfg: dict[str, Any] | None = None,
    *,
    store: Any = None,
    run_id: str | None = None,
    environ: Any = None,
    spa_dir: Any = None,
    help_assistant: Any = None,
) -> ConsoleServer:
    """Start the console with `cfg`. The same refusals apply in the same order: the profile first,
    then the address, so the refusal cannot be turned off like a default (CT-CONSOLE-20). Both use
    the effective configuration, with environment variables taking priority over `cfg`
    (FR-CONSOLE-36). `spa_dir` and `help_assistant` are as `serve_console` takes them."""
    return ConsoleServer(store, run_id=run_id, cfg=cfg, environ=environ, spa_dir=spa_dir,
                         help_assistant=help_assistant)
