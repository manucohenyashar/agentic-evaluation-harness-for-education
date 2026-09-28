"""`TS-90` (issue #384) — `TC-CONSOLE-43`: the console serves real HTTP, and the control
surface is an allow-list checked before anything else (`FR-CONSOLE-33`).

| Request | Expected |
|---|---|
| `GET /` | 200, `text/html; charset=utf-8` |
| `GET /assets/console.css` | 200, `text/css` |
| `GET /nope` | 404 |
| every response | `Cache-Control: no-store` |
| `POST /actions/<declared slug>` vs `POST /actions/drop-tables` | the undeclared slug → 404 **with no store write** |
| `POST /upload` with a 12 MiB body | the blob's sha256 equals the body's, with no single read over 1 MiB |
| `terminate()` | the port refuses connections and the thread has joined |
| static | `_CHILD_SCRIPT` is absent from `console.py` |

**`no-store` on every response, not just the pages.** The console renders student records. A
cached page is a student record sitting in a browser cache on a shared machine after the
teacher has closed the tab, and the one response most likely to be treated as harmless — a
stylesheet, a 404 — is the one whose headers get written by a different code path. So the
header is asserted across all three kinds.

**The undeclared slug is checked before the body is read.** `CONTROL_ACTION_SLUGS` is derived
from `CONTROL_SURFACE_ACTIONS` at import time, and `do_POST` looks the slug up *before* reading
the form and before calling any door. An undeclared slug must not be able to reach a store at
all — so it is a 404 with no write, rather than a refusal the ledger records. A refusal that
got as far as writing an audit row would already have opened the door it was refusing.

**The read ceiling is about memory, not speed.** A 12 MiB upload read in one call is 12 MiB
resident on a teacher's laptop, and the ceiling is what makes the handler's footprint
independent of what a client sends. The spy records every read size and the assertion is on the
**maximum**, because an average would hide one large read among many small ones.

**A divergence, reported: the shipped default is 4 MiB, not the plan's 1 MiB.**
`_UPLOAD_CHUNK_DEFAULT = 4 * 1024 * 1024` (`console.py:277`), so a 12 MiB body is read in three
4 MiB chunks and a literal reading of the plan's "no single read over 1 MiB" is red on the
default configuration. What the requirement is actually about — that the footprint is bounded
and does not follow the body's size — is a property of the knob, and
`HARNESS_CONSOLE_UPLOAD_CHUNK_BYTES` is exactly the env-gated seam CLAUDE.md's rule 3 asks for.
So the case sets the knob to 1 MiB and asserts the handler honours it, which tests the
mechanism rather than the constant, and #384 reports the default for a human to settle: 4 MiB
resident per concurrent upload may well be the intended trade, but it is not what the plan
says.

**`terminate()` joining the thread is the half that leaks.** A closed port with a live serving
thread is a process that will not exit, which on a teacher's machine is a console that
"disappeared" and still holds the store open.

**Isolation: rung 3** — a real socket, real HTTP, a real store.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import socket
from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.console import (
    CONTROL_ACTION_SLUGS,
    _ConsoleRequestHandler,
    serve_console,
)
from aeh.store import open_store

pytestmark = pytest.mark.integration

#: The plan's undeclared slug. Chosen to look plausible and to be the worst thing it could
#: reach if the allow-list were consulted after the door.
UNDECLARED_SLUG = "drop-tables"

#: One MiB — the largest single read the upload handler may make, whatever the body's size.
ONE_MIB = 1024 * 1024
UPLOAD_BYTES = 12 * ONE_MIB


@pytest.fixture
def upload_chunk_1mib(monkeypatch):
    """The upload walk bounded at 1 MiB, through its declared knob.

    Ordered before `served` so the server is built with the knob already set — the chunk size
    is read at call time, but binding first and setting after would leave the ordering to
    fixture luck.
    """
    monkeypatch.setenv("HARNESS_CONSOLE_UPLOAD_CHUNK_BYTES", str(ONE_MIB))


@pytest.fixture
def served(tmp_data_dir, network_guard, monkeypatch):
    """A real console on a real loopback port, over a real store."""
    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    store = open_store(tmp_data_dir)
    network_guard.uninstall()
    try:
        server = serve_console(store=store)
    except BaseException:
        network_guard.install()
        store.close()
        raise
    _host, port = server.socket.getsockname()[:2]
    try:
        yield server, port, store, tmp_data_dir
    finally:
        try:
            server.terminate()
        finally:
            network_guard.install()
            store.close()


def _request(port: int, method: str, path: str, body: bytes | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(method, path, body=body)
        response = connection.getresponse()
        payload = response.read()
        return response.status, dict(response.getheaders()), payload
    finally:
        connection.close()


def _fingerprint(root) -> dict[str, str]:
    """Every file under the data directory, by content hash — the write audit."""
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# --- TC-CONSOLE-43, the GET surface ---------------------------------------------------------


@pytest.mark.parametrize(
    "path,status,content_type",
    (
        ("/", 200, "text/html"),
        ("/assets/console.css", 200, "text/css"),
        ("/nope", 404, ""),
    ),
)
def test_tc_console_43_the_three_get_routes_answer_as_declared(
    served, path, status, content_type
):
    """`/` renders HTML, the stylesheet is CSS, an unknown route is 404."""
    _server, port, _store, _dir = served

    got_status, headers, _body = _request(port, "GET", path)

    assert got_status == status, f"GET {path} answered {got_status}, not {status}"
    if content_type:
        assert headers.get("Content-Type", "").startswith(content_type), (
            f"GET {path} answered Content-Type {headers.get('Content-Type')!r}, not "
            f"{content_type!r}"
        )


@pytest.mark.parametrize("path", ("/", "/assets/console.css", "/nope"))
def test_tc_console_43_every_response_forbids_caching(served, path):
    """`Cache-Control: no-store` on the page, the stylesheet **and** the 404.

    All three, because they leave through different code paths and the two that look harmless
    are the ones a header gets forgotten on. The console renders student records; a cached page
    is a student record left in a browser cache on a shared machine.
    """
    _server, port, _store, _dir = served

    _status, headers, _body = _request(port, "GET", path)

    assert headers.get("Cache-Control") == "no-store", (
        f"GET {path} answered Cache-Control {headers.get('Cache-Control')!r}"
    )


# --- TC-CONSOLE-43, the control surface -----------------------------------------------------


def test_tc_console_43_an_undeclared_action_slug_is_404_and_writes_nothing(served):
    """`POST /actions/drop-tables` → 404, and not one byte of the store changes.

    The write audit is the half that matters. A 404 returned *after* the handler had reached a
    door would look identical to the client and would already have done the thing it refused.
    """
    _server, port, _store, data_dir = served
    assert UNDECLARED_SLUG not in CONTROL_ACTION_SLUGS, (
        f"{UNDECLARED_SLUG!r} is now a declared control action; the case needs a slug that "
        f"is not one. Declared: {sorted(CONTROL_ACTION_SLUGS)}"
    )
    before = _fingerprint(data_dir)

    status, _headers, _body = _request(port, "POST", f"/actions/{UNDECLARED_SLUG}", b"")

    assert status == 404, f"the undeclared slug answered {status}, not 404"
    after = _fingerprint(data_dir)
    changed = sorted(
        name for name in set(before) | set(after) if before.get(name) != after.get(name)
    )
    assert changed == [], (
        f"an undeclared action slug changed {changed}. The allow-list is checked before the "
        "body is read and before any door is called, so an undeclared slug reaches no store "
        "at all (FR-CONSOLE-33)"
    )


def test_tc_console_43_a_declared_action_slug_is_routed(served):
    """The positive control: a slug that *is* declared is not a 404.

    Without it, "the undeclared slug is 404" would pass against a console that 404'd every
    POST — a console with no control surface at all.
    """
    _server, port, _store, _dir = served
    slug = sorted(CONTROL_ACTION_SLUGS)[0]

    status, _headers, _body = _request(port, "POST", f"/actions/{slug}", b"")

    assert status != 404, (
        f"the declared slug {slug!r} answered 404; the allow-list is refusing its own members"
    )


# --- TC-CONSOLE-43, the upload ---------------------------------------------------------------


def test_tc_console_43_a_twelve_mebibyte_upload_is_read_in_bounded_chunks(
    upload_chunk_1mib, served, monkeypatch
):
    """The upload's bytes arrive intact, and no single read exceeds 1 MiB.

    Both halves together: a handler that read the whole body at once would get the hash right
    and hold 12 MiB resident, and one that capped its reads but dropped a chunk would stay
    small and corrupt the scan. The maximum read is the oracle rather than the average, because
    an average hides one large read among many small ones.
    """
    _server, port, store, _dir = served
    # `%PDF-`-headed: `upload_scans` carries FR-CONSOLE-13's magic check, and a body without
    # it is rejected before the stream is drained — which shows up as a 400 about a truncated
    # upload rather than as a format refusal.
    header = b"%PDF-1.7\n"
    body = header + bytes(
        bytearray((index * 7 + 11) % 256 for index in range(UPLOAD_BYTES - len(header)))
    )
    assert len(body) == UPLOAD_BYTES

    # The spy wraps the handler's `rfile` at `setup()` rather than patching a read method:
    # `io.BufferedReader` is an immutable C type, and wrapping the stream the handler actually
    # reads from observes the real HTTP reads without touching the stdlib.
    reads: list[int] = []
    original_setup = _ConsoleRequestHandler.setup

    class _CountingReader:
        def __init__(self, wrapped: Any) -> None:
            self._wrapped = wrapped

        def read(self, size: int = -1) -> bytes:
            chunk = self._wrapped.read(size)
            if chunk:
                reads.append(len(chunk))
            return chunk

        def __getattr__(self, name: str) -> Any:
            return getattr(self._wrapped, name)

    def _spying_setup(self) -> None:  # noqa: ANN001 — stdlib signature
        original_setup(self)
        self.rfile = _CountingReader(self.rfile)

    monkeypatch.setattr(_ConsoleRequestHandler, "setup", _spying_setup)

    status, _headers, payload = _request(port, "POST", "/upload", body)

    assert status == 200, f"the upload answered {status}: {payload[:300]!r}"
    assert reads, "no read was observed, so the ceiling assertion is vacuous"
    assert max(reads) <= ONE_MIB, (
        f"the handler's largest single read was {max(reads)} bytes with "
        f"HARNESS_CONSOLE_UPLOAD_CHUNK_BYTES set to {ONE_MIB}. The knob is not being honoured, "
        "so the handler's footprint follows the body's size rather than the configured bound "
        "— a 12 MiB body read in one call is 12 MiB resident on a teacher's laptop"
    )
    assert len(reads) > 1, (
        f"the whole body arrived in {len(reads)} read(s); a bounded walk over "
        f"{UPLOAD_BYTES} bytes at {ONE_MIB} per chunk takes several"
    )
    assert sum(reads) >= UPLOAD_BYTES, (
        f"the handler read {sum(reads)} of {UPLOAD_BYTES} bytes; a bounded read that dropped "
        "a chunk stays small and stages a truncated scan"
    )

    # The bytes that landed are the bytes that were sent: the staged blobs, concatenated in
    # the order the response reports them, hash to the body's digest.
    staged = json.loads(payload.decode("utf-8"))
    refs = staged["blob_refs"]
    assert refs, f"the upload staged no blobs: {staged}"
    digest = hashlib.sha256()
    for ref in refs:
        # The refs are `sha256:<hex>`; `BlobStore.get` takes the bare digest and refuses a
        # prefixed one by name (`CT-STORE-07`, SEC-09).
        digest.update(store.blobs().get(str(ref).split(":", 1)[-1]))
    assert digest.hexdigest() == hashlib.sha256(body).hexdigest(), (
        "the staged blobs do not reconstruct the uploaded body — the chunked walk kept its "
        "memory ceiling and lost content"
    )


# --- TC-CONSOLE-43, shutdown and the static clause -------------------------------------------


def test_tc_console_43_terminate_closes_the_port_and_joins_the_thread(
    tmp_data_dir, network_guard, monkeypatch
):
    """After `terminate()` the port refuses connections and the serving thread has joined.

    A closed port with a live thread is a process that will not exit — a console the teacher
    thinks they closed, still holding the store open.
    """
    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    store = open_store(tmp_data_dir)
    network_guard.uninstall()
    try:
        server = serve_console(store=store)
        _host, port = server.socket.getsockname()[:2]
        with socket.create_connection(("127.0.0.1", port), timeout=5):
            pass  # the positive control: the port is live before terminate()

        server.terminate()

        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(2)
        try:
            refused = probe.connect_ex(("127.0.0.1", port)) != 0
        finally:
            probe.close()
        assert refused, f"port {port} still accepts connections after terminate()"

        thread = getattr(server, "_thread", None)
        assert thread is not None and not thread.is_alive(), (
            "the serving thread is still alive after terminate(); the port is closed but the "
            "process will not exit"
        )
    finally:
        network_guard.install()
        store.close()


def test_tc_console_43_console_py_spawns_no_child_script():
    """`_CHILD_SCRIPT` is absent from `console.py` — the static clause.

    A regression pin on a name that is already gone: the console serves in-process, and a child
    script is how a "just run it in a subprocess" shortcut re-enters. It would take the profile
    and bind refusals with it, because those are resolved in `__init__` of the object that no
    longer does the serving.
    """
    import inspect

    import aeh.console as console_module

    assert "_CHILD_SCRIPT" not in inspect.getsource(console_module), (
        "`_CHILD_SCRIPT` is back in console.py. The console serves in-process; a child script "
        "would bypass the profile and bind refusals that FR-CONSOLE-36 resolves at construction"
    )
