"""The console API's surface, as `TC-CONSOLE-53` and `TC-CONSOLE-C30` read it (TS-147, #628).

Written ahead of #629 (`FR-CONSOLE-45`, `CT-CONSOLE-30`). The design says *what* the API is —
a versioned JSON surface under `/api/`, the SPA at `/` and `/assets/` from the same origin, every
mutation an enumerated control write — but names none of the objects a test needs to hold. So
the names are invented here, once, and nowhere else; #629 may rename any of them with a one-line
edit in this file.

What #629 is asked to provide (and nothing more):

* ``aeh.console.API_ROUTES`` — the server's route table, the object the census reads. A
  sequence of records, each with ``method`` (an HTTP verb), ``path`` (a template, ``{name}``
  for a path parameter) and ``control``: the member of ``CONTROL_SURFACE_ACTIONS`` the route
  writes, or ``None`` for a read. TC-CONSOLE-54 reads the same table, so it is public.
* ``aeh.console.SPA_BUNDLE_DIR`` — the package-data directory the SPA is served from:
  ``index.html`` at ``/``, ``assets/<file>`` at ``/assets/<file>``. #634 puts the bundle there.
* ``serve_console(..., spa_dir=<path>)`` — the same server over a different bundle directory.
  The deterministic seam (CLAUDE.md, seam 2) the cases need to serve a known bundle, and to
  plant an external origin in one, without touching package data.
* Every mutating API route reaches the control surface through ``ConsoleApp.perform`` — the
  door the existing ``POST /actions/<slug>`` already uses. The API adds a transport, not a
  second write path (FR-CONSOLE-45), and the census's behavioural half spies on that door.
  Two consequences, stated so they are not discovered: the handler looks ``perform`` up on
  ``server.app`` at request time (as ``POST /actions/<slug>`` does today), and it passes the
  request's parameters to the door rather than validating them first — refusing a malformed
  request is the door's job and it reports the refusal (the `FR-CONSOLE-34` posture), so a
  ``{}`` body still reaches ``perform`` exactly once.
* The server routes FROM ``API_ROUTES`` — the table is the router, the way
  ``CONTROL_ACTION_SLUGS`` is the router for ``/actions/`` today — so a route cannot exist that
  the table does not list. The unlisted-path probe checks this from outside; it cannot prove it.

The one named exception: the upload
-----------------------------------
`CT-CONSOLE-30` reads two ways about uploads. *"The API's mutations are exactly the enumerated
control writes"* — and the fifteen do not include an upload. *"No mutation exists in the API
that the server-rendered console did not have"* — and that console had ``POST /upload``
(`FR-CONSOLE-04`: uploads stream to the blob store). Loading papers is a lifecycle screen the
SPA must offer (FR-UI-03(c)), so the upload has to stay reachable. It is admitted here as ONE
named row, labelled ``"upload scans"`` and citing FR-CONSOLE-04, never by path pattern. Any
other mutation that is not one of the fifteen is an orphan. Reported on the PR as a plan
finding: FR-CONSOLE-42's cohort creation and M-HELP's ask endpoint will meet this census too.
"""

from __future__ import annotations

import http.client
import inspect
import re
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Iterator

from tests.support.console_security_vocabulary import external_origins
from tests.support.guards import loopback_census

# --- the invented names (the only place they are spelled) ----------------------------------

ROUTE_TABLE = "API_ROUTES"
SPA_BUNDLE_DIR = "SPA_BUNDLE_DIR"
SPA_DIR_KWARG = "spa_dir"

#: The issue every name above waits on.
API_ISSUE = "#629"
#: The issue that ships the real built bundle at `SPA_BUNDLE_DIR` (FR-UI-01).
BUNDLE_ISSUE = "#634"

#: `FR-CONSOLE-45`: "a versioned JSON API at same-origin paths under `/api/`".
VERSIONED_API_PATH = re.compile(r"^/api/v\d+/")

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
READ_METHODS = frozenset({"GET", "HEAD"})

#: The one mutation admitted beside the fifteen control actions, with the requirement that
#: makes it a pre-existing write rather than a new one (see the module docstring).
NON_CONTROL_MUTATIONS: dict[str, str] = {
    "upload scans": "FR-CONSOLE-04 — uploads stream to the content-addressed blob store",
}

#: Hosts that are this machine. A URL naming one of them is not an external origin.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})

#: Exact strings, never prefixes: XML namespace identifiers an SVG or MathML document must
#: carry. They are names, never fetched. `http://www.w3.org/2000/svg/x.js` is not on the list.
NAMESPACE_IDENTIFIERS = frozenset({
    "http://www.w3.org/2000/svg",
    "http://www.w3.org/1999/xlink",
    "http://www.w3.org/1999/xhtml",
    "http://www.w3.org/1998/Math/MathML",
    "http://www.w3.org/XML/1998/namespace",
})

#: Content-Type families by file suffix (`TC-CONSOLE-53(a)`: "`Content-Type` correct").
EXPECTED_CONTENT_TYPES: dict[str, tuple[str, ...]] = {
    ".html": ("text/html",),
    ".js": ("text/javascript", "application/javascript"),
    ".mjs": ("text/javascript", "application/javascript"),
    ".css": ("text/css",),
    ".svg": ("image/svg+xml",),
    ".woff2": ("font/woff2",),
    ".woff": ("font/woff",),
    ".png": ("image/png",),
    ".json": ("application/json",),
    ".ico": ("image/x-icon", "image/vnd.microsoft.icon"),
}


# --- the route table -----------------------------------------------------------------------


def route_rows(routes: Iterable[Any]) -> list[tuple[str, str, Any]]:
    """The census: each route as ``(METHOD, path, control)``, in table order."""
    return [
        (str(getattr(r, "method")).upper(), str(getattr(r, "path")), getattr(r, "control"))
        for r in routes
    ]


def mutating_rows(routes: Iterable[Any]) -> list[tuple[str, str, Any]]:
    return [row for row in route_rows(routes) if row[0] not in READ_METHODS]


def orphan_mutations(
    routes: Iterable[Any], enumerated: Iterable[str]
) -> list[tuple[str, str, Any]]:
    """Every mutating route whose control is neither an enumerated action nor the one named
    exception. `CT-CONSOLE-30` breaks the moment this is non-empty."""
    enumerated = set(enumerated)
    orphans: list[tuple[str, str, Any]] = []
    excepted: set[Any] = set()
    for row in mutating_rows(routes):
        if row[2] in enumerated:
            continue
        # The named exception admits ONE route, by POST, per label — a second row carrying the
        # label, or a DELETE wearing it, is a new mutation hiding behind an old name.
        if row[2] in NON_CONTROL_MUTATIONS and row[0] == "POST" and row[2] not in excepted:
            excepted.add(row[2])
            continue
        orphans.append(row)
    return orphans


def matches_template(template: str, path: str) -> bool:
    """Whether a concrete request path is one the route template would route."""
    return re.fullmatch(re.sub(r"\\\{(\w+)\\\}", r"[^/]+", re.escape(template)), path) is not None


def concrete_path(template: str) -> str:
    """A route template with every ``{name}`` filled by a probe value."""
    return re.sub(r"\{(\w+)\}", lambda m: f"probe-{m.group(1)}", template)


# --- HTTP ----------------------------------------------------------------------------------


def fetch(
    port: int, method: str, path: str, body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """One request on a fresh loopback connection. Redirects are NOT followed — a redirect is
    one of the things `TC-CONSOLE-53(a)` inspects."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, payload
    finally:
        connection.close()


def same_origin_location(location: str, port: int) -> bool:
    """Whether a redirect's ``Location`` stays on this server."""
    location = location.strip()
    if location.startswith("//"):
        return False
    if location.startswith("/") or not re.match(r"^[a-z][a-z0-9+.-]*:", location, re.I):
        return True
    match = re.match(r"^https?://([^/]+)", location, re.I)
    return bool(match) and match.group(1).lower() in {
        f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"
    }


# --- the served-bytes sweep (RISK-108) ------------------------------------------------------

_SCHEME_URL = re.compile(r"""(?i)\b(?:https?|wss?):(?://|\\/\\/)([^\s"'`<>()\\/?#]+)[^\s"'`<>()\\]*""")
_CSS_PROTOCOL_RELATIVE = re.compile(
    r"""(?i)(?:url\(\s*['"]?|@import\s+['"])(//[^\s"')]+)"""
)


def _host_of(authority: str) -> str:
    host = authority.rsplit("@", 1)[-1].lower()
    if host.startswith("["):
        return host.split("]", 1)[0] + "]"
    return host.split(":", 1)[0]


def external_references(body: bytes, content_type: str = "") -> list[str]:
    """Every absolute non-loopback URL in one served body.

    Scheme-anchored (`http://`, `https://`, and their JSON-escaped `https:\\/\\/` form) over
    every text body, because a bundle reaches the network from JS and CSS, not only from
    markup. Protocol-relative ``//host`` is matched only where it is a fetch — CSS ``url()``
    and ``@import``, and HTML attributes through `external_origins` — since a bare ``//`` in
    JS is a comment far more often than a URL. Binary bodies (fonts, images) are swept too,
    decoded leniently: a font file carries no URL, and if one does it is reported.
    """
    text = body.decode("utf-8", errors="replace")
    found: list[str] = []
    for match in _SCHEME_URL.finditer(text):
        url = match.group(0).replace("\\/", "/")
        if url in NAMESPACE_IDENTIFIERS:
            continue
        if _host_of(match.group(1)) in LOOPBACK_HOSTS:
            continue
        found.append(url)
    found.extend(_CSS_PROTOCOL_RELATIVE.findall(text))
    if "html" in content_type.lower() or text.lstrip().lower().startswith("<!doctype html"):
        found.extend(
            u for u in external_origins(text)
            if u not in NAMESPACE_IDENTIFIERS and not _is_loopback_url(u)
        )
    return list(dict.fromkeys(found))


def _is_loopback_url(url: str) -> bool:
    match = re.match(r"^(?:[a-z][a-z0-9+.-]*:)?//([^/]+)", url, re.I)
    return bool(match) and _host_of(match.group(1)) in LOOPBACK_HOSTS


# --- the bundle ----------------------------------------------------------------------------


class _References(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Any]]) -> None:
        for name, value in attrs:
            if name in ("src", "href") and value:
                self.urls.append(str(value))

    handle_startendtag = handle_starttag


def same_origin_references(html: str) -> list[str]:
    """The root-relative or relative ``src``/``href`` targets of a page: what it loads from
    its own origin."""
    parser = _References()
    parser.feed(html)
    return [
        u for u in dict.fromkeys(parser.urls)
        if not re.match(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", u, re.I)
    ]


def css_references(css: str) -> list[str]:
    return [
        u for u in dict.fromkeys(re.findall(r"""url\(\s*['"]?([^'")]+)""", css))
        if not re.match(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", u.strip(), re.I)
    ]


def root_path(reference: str) -> str:
    """A reference from ``/`` as a request path."""
    reference = reference.split("#", 1)[0].split("?", 1)[0]
    return reference if reference.startswith("/") else "/" + reference.lstrip("./")


#: A minimal SPA bundle in the shape #634 ships: `index.html` and `assets/`. Its SVG carries
#: the SVG namespace on purpose — the one absolute `http://` an honest bundle cannot avoid —
#: so the sweep's namespace allowance is exercised rather than assumed.
CLEAN_BUNDLE: dict[str, bytes] = {
    "index.html": (
        b'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        b"<title>aeh console</title>"
        b'<link rel="stylesheet" href="/assets/app.css">'
        b'<link rel="icon" href="/assets/logo.svg">'
        b'</head><body><div id="root"></div>'
        b'<script type="module" src="/assets/app.js"></script></body></html>'
    ),
    "assets/app.js": (
        b'const API="/api/v1/";'
        b'fetch(API+"packages").then(r=>r.json()).then(d=>{'
        b'document.getElementById("root").textContent=JSON.stringify(d)});'
        b"// a comment with // slashes is not a URL\n"
    ),
    "assets/app.css": (
        b'@font-face{font-family:"Inter";src:url("/assets/inter.woff2") format("woff2")}'
        b'body{font-family:"Inter",sans-serif;background:url(logo.svg) no-repeat}'
    ),
    "assets/inter.woff2": b"wOF2\x00\x01\x00\x00" + bytes(range(256)) * 4,
    "assets/logo.svg": (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8">'
        b'<rect width="8" height="8"/></svg>'
    ),
}

#: The same bundle with an external origin planted in each place RISK-108 names: a CDN script
#: in the markup, a web font in the CSS (by scheme and protocol-relative), a telemetry call
#: in the JS. The negative control: a sweep that finds none of these proves nothing.
PLANTED_ORIGINS: dict[str, str] = {
    "index.html": "https://cdn.example.net/react.production.min.js",
    "assets/app.css": "https://fonts.googleapis.com/css2?family=Inter",
    "assets/app.css#protocol-relative": "//fonts.gstatic.com/s/inter/v12/inter.woff2",
    "assets/app.js": "https://telemetry.example.com/collect",
    "assets/app.js#websocket": "wss://telemetry.example.com/stream",
}


def planted_bundle() -> dict[str, bytes]:
    bundle = dict(CLEAN_BUNDLE)
    bundle["index.html"] = bundle["index.html"].replace(
        b"</head>",
        f'<script src="{PLANTED_ORIGINS["index.html"]}"></script></head>'.encode(),
    )
    bundle["assets/app.css"] = (
        f'@import url("{PLANTED_ORIGINS["assets/app.css"]}");'.encode()
        + bundle["assets/app.css"]
        + f'@font-face{{font-family:"X";src:url({PLANTED_ORIGINS["assets/app.css#protocol-relative"]})}}'.encode()
    )
    bundle["assets/app.js"] = (
        bundle["assets/app.js"]
        + f'fetch("{PLANTED_ORIGINS["assets/app.js"]}",{{method:"POST"}});'.encode()
        + f'new WebSocket("{PLANTED_ORIGINS["assets/app.js#websocket"]}");'.encode()
    )
    return bundle


def write_bundle(root: Path, bundle: dict[str, bytes]) -> Path:
    for relative, data in bundle.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


# --- serving and crawling ------------------------------------------------------------------


def start_console(serve: Any, store: Any, *, spa_dir: Path | None = None) -> Any:
    """`serve_console` over `store`, optionally over a fixture bundle.

    A server that does not take the bundle seam yet fails as `NotImplementedYet` naming #629,
    never as a `TypeError` — a test that fails on a signature proves nothing about the API."""
    from tests.support.impl import NotImplementedYet

    if spa_dir is None:
        return serve(store=store)
    if SPA_DIR_KWARG not in inspect.signature(serve).parameters:
        raise NotImplementedYet(
            f"serve_console does not take {SPA_DIR_KWARG!r} yet (blocked on {API_ISSUE}): the "
            "seam that serves a known SPA bundle from the same origin (FR-CONSOLE-45)."
        )
    return serve(store=store, **{SPA_DIR_KWARG: spa_dir})


@contextmanager
def on_loopback(server: Any, guard: Any) -> Iterator[tuple[int, list[Any]]]:
    """Requests to `server` inside the guard's loopback census; terminated on exit."""
    try:
        with loopback_census(guard) as census:
            yield int(server.port), census
    finally:
        server.terminate()


def crawl_spa(port: int) -> tuple[dict[str, tuple[int, dict[str, str], bytes]], list[str]]:
    """Load the SPA the way a browser would, from ``/``: the page, every same-origin ``src`` /
    ``href`` it names, and every ``url()`` its stylesheets name. Redirects are followed only
    while they stay on this origin; one that leaves is reported in the second list and not
    followed. Returns every response by request path, in load order."""
    served: dict[str, tuple[int, dict[str, str], bytes]] = {}
    leaving: list[str] = []
    pending = ["/"]
    while pending:
        path = pending.pop(0)
        if path in served:
            continue
        status, headers, body = fetch(port, "GET", path)
        hops = 0
        while 300 <= status < 400 and hops < 3:
            location = headers.get("location", "")
            if not same_origin_location(location, port):
                leaving.append(f"GET {path} -> {status} {location}")
                break
            hops += 1
            local = re.sub(r"^https?://[^/]+", "", location, flags=re.I) or "/"
            status, headers, body = fetch(port, "GET", root_path(local))
        served[path] = (status, headers, body)
        if status != 200:
            continue
        content_type = headers.get("content-type", "")
        text = body.decode("utf-8", errors="replace")
        if "html" in content_type:
            pending.extend(root_path(ref) for ref in same_origin_references(text))
        elif "css" in content_type:
            base = path.rsplit("/", 1)[0] + "/"
            pending.extend(
                root_path(ref) if ref.startswith("/") else root_path(base + ref)
                for ref in css_references(text)
            )
    return served, leaving


def content_type_matches(path: str, content_type: str) -> bool:
    """Whether a response's media type is the one its path's suffix calls for (``/`` is HTML)."""
    suffix = Path(path.split("?", 1)[0]).suffix.lower() or ".html"
    expected = EXPECTED_CONTENT_TYPES.get(suffix)
    return expected is not None and content_type.lower().split(";")[0].strip() in expected
