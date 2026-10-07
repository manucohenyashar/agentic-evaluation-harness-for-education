"""The console's JSON API and the SPA bundle it serves from the same origin (FR-CONSOLE-45).

`API_ROUTES` is both the census `CT-CONSOLE-30` is checked against and the router the server
dispatches `/api/` from: a route the table does not list does not exist. Every mutating row is
built from `CONTROL_SURFACE_ACTIONS`, so the API cannot carry a mutation the enumeration does
not — the API adds a transport, not a second write path. The one mutation beside the enumerated actions
is the scan upload (`FR-CONSOLE-04`), which the server-rendered console already had.

The SPA itself (M-UI) ships as package data at `SPA_BUNDLE_DIR` (#634); this module only says
where it lives and how a request path maps onto a file inside it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, NamedTuple

from .vocabulary import (
    CONTROL_SURFACE_ACTIONS,
    RESULTS_CLASS_READ,
    RESULTS_EXPORT_READ,
    RESULTS_STUDENT_READ,
    RUN_START_PREVIEW_READ,
)

#: The API's version prefix. A breaking change to the API moves to `/api/v2/` beside it.
API_PREFIX = "/api/v1"

#: The built SPA bundle: `index.html` served at `/`, `assets/<file>` at `/assets/<file>`.
#: Resolved from this file rather than the working directory, so an installed wheel serves the
#: same bundle a checkout does (the `_stylesheet_bytes` precedent).
SPA_BUNDLE_DIR: Path = Path(__file__).resolve().parent.parent / "console_assets" / "spa"

#: The label of the one non-control mutation the API carries (`FR-CONSOLE-04`).
UPLOAD_CONTROL = "upload scans"

#: The query parameter the ask read takes the question from (`M-HELP`).
ASK_QUERY_PARAM = "q"

#: Media types by suffix. Explicit rather than `mimetypes`, which on Windows reads the
#: registry and can answer `text/plain` for `.js` — a module script the browser then refuses.
CONTENT_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".txt": "text/plain; charset=utf-8",
}
DEFAULT_CONTENT_TYPE = "application/octet-stream"

READ_METHODS = frozenset({"GET"})


class ApiRoute(NamedTuple):
    """One API route: its HTTP verb, its path template (`{name}` for a path parameter), the
    control action it writes (`None` for a read), and the read it answers with (`None` for a
    mutation)."""

    method: str
    path: str
    control: str | None
    read: str | None = None


class FileAnswer(NamedTuple):
    """A read that answers a stored file's bytes (the results export, FR-CONSOLE-44) rather
    than a JSON document: the raw bytes and the media type they carry."""

    body: bytes
    content_type: str


def action_slug(action: str) -> str:
    """A control action's URL form: lowercase, with spaces and slashes turned into hyphens.

    `CONTROL_SURFACE_ACTIONS` holds the actions verbatim, as prose — "start run",
    "pause/resume" — because `FR-CONSOLE-32` pins that set to those words. None of them is a
    legal path segment, so the URL carries a slug and the server maps it back
    (`TC-CONSOLE-43`'s `finalize-batch`, `TC-CONF-21`'s `start-run`)."""
    return action.lower().replace("/", "-").replace(" ", "-")


def _build_routes() -> tuple[ApiRoute, ...]:
    reads = (
        ApiRoute("GET", f"{API_PREFIX}/controls", None, "controls"),
        ApiRoute("GET", f"{API_PREFIX}/screens", None, "screens"),
        # FR-CONSOLE-42: the roster editor's columns, its "ID is optional" statement and the
        # consent classes — the copy the SPA renders, so it restates no rule of its own.
        ApiRoute("GET", f"{API_PREFIX}/roster-editor", None, "roster editor"),
        # FR-UI-02: the home hub's live state — the package version, the served run's status
        # and the engine in use — which the hub reads on load and polls.
        ApiRoute("GET", f"{API_PREFIX}/hub", None, "hub"),
        # #631: the run-start screen's data behind its one confirmation (FR-CONSOLE-43) and
        # the results views, byte-identical with the CLI's (FR-CONSOLE-44, TC-CONSOLE-56/57).
        # Reads, not controls: the preview writes nothing, and the confirmation's write is
        # the enumerated "start run" control, not a second one.
        ApiRoute("GET", f"{API_PREFIX}/run-start-preview", None, RUN_START_PREVIEW_READ),
        ApiRoute("GET", f"{API_PREFIX}/results/class", None, RESULTS_CLASS_READ),
        ApiRoute("GET", f"{API_PREFIX}/results/student", None, RESULTS_STUDENT_READ),
        ApiRoute("GET", f"{API_PREFIX}/results/export", None, RESULTS_EXPORT_READ),
        # M-HELP (FR-HELP-01): the manuals page's reads, and the grounded Q&A ask. The ask is a
        # GET, not a POST: its only write is the assistant's own Q&A log (`CT-HELP-04`), so it
        # is not a control action and the route carries no control row.
        ApiRoute("GET", f"{API_PREFIX}/manuals", None, "manuals"),
        ApiRoute("GET", f"{API_PREFIX}/manuals/{{manual_id}}", None, "manual"),
        ApiRoute("GET", f"{API_PREFIX}/help/ask", None, "help ask"),
    )
    controls = tuple(
        ApiRoute("POST", f"{API_PREFIX}/actions/{action_slug(action)}", action)
        for action in CONTROL_SURFACE_ACTIONS
    )
    upload = (ApiRoute("POST", f"{API_PREFIX}/uploads", UPLOAD_CONTROL),)
    return reads + controls + upload


#: The route table and the router (`FR-CONSOLE-45`, `CT-CONSOLE-30`).
API_ROUTES: tuple[ApiRoute, ...] = _build_routes()


if len({(r.method, r.path) for r in API_ROUTES}) != len(API_ROUTES):  # pragma: no cover
    raise AssertionError("two API routes share a method and path; one would be unreachable")


def _template_pattern(template: str) -> re.Pattern[str]:
    return re.compile(re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[^/]+)", re.escape(template)))


_PATTERNS: tuple[tuple[ApiRoute, re.Pattern[str]], ...] = tuple(
    (route, _template_pattern(route.path)) for route in API_ROUTES
)


def match_route(method: str, path: str) -> tuple[ApiRoute | None, dict[str, str], bool]:
    """The route `method path` names, its path parameters, and whether the path is routed
    under some other verb (so the answer is 405 rather than 404)."""
    other_verb = False
    for route, pattern in _PATTERNS:
        match = pattern.fullmatch(path)
        if match is None:
            continue
        if route.method == method:
            return route, match.groupdict(), False
        other_verb = True
    return None, {}, other_verb


def allowed_methods(path: str) -> tuple[str, ...]:
    """The verbs the table routes `path` under, for a 405's `Allow` header."""
    return tuple(sorted({r.method for r, pattern in _PATTERNS if pattern.fullmatch(path)}))


def controls_payload() -> dict[str, Any]:
    """The enumerated control surface as the API exposes it: each action and its route."""
    return {
        "version": API_PREFIX.rsplit("/", 1)[-1],
        "controls": [
            {"action": r.control, "method": r.method, "path": r.path}
            for r in API_ROUTES if r.method not in READ_METHODS
        ],
    }


def content_type_for(path: Path) -> str:
    return CONTENT_TYPES.get(path.suffix.lower(), DEFAULT_CONTENT_TYPE)


def bundle_file(spa_dir: Path, relative: str) -> Path | None:
    """The file `relative` names inside `spa_dir`, or `None` if it is not one.

    Confined: the resolved path must stay inside the bundle directory. A request path is
    attacker-shaped — `..`, a drive letter or a backslash would otherwise reach any file the
    process can read."""
    if not relative or "\\" in relative or ":" in relative or "\x00" in relative:
        return None
    try:
        root = Path(spa_dir).resolve()
        candidate = (root / relative).resolve()
    except (OSError, ValueError):
        return None
    if root not in candidate.parents or not candidate.is_file():
        return None
    return candidate
