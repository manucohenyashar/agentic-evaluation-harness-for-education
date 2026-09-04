"""The socket guard.

Test plan §8.1: *"Without the socket guard, half the P0 assertions in this plan ('and no
model call is made') are unenforceable."*

The guard does two things, and both matter:

1. **Raises** on any outbound connection attempt, so a test that accidentally reaches the
   network fails instead of quietly passing (or quietly costing money).
2. **Records** every attempt, so a test can assert *zero* attempts positively. Raising alone
   is not enough: `TC-PROV-13`'s oracle is "exact exception **plus socket guard**", and a
   guard that only raises cannot distinguish "no call was made" from "the call was made and
   swallowed by an `except Exception`" — which is exactly the bug the case exists to catch.

Deliberately strict: loopback is blocked too. A test that genuinely needs a real socket
(the `live` tier, or the three E6 browser cases) marks itself and the guard stands down.
"""

from __future__ import annotations

import builtins
import io
import os
import pathlib
import socket
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from tests.support.impl import IMPLEMENTATION_PACKAGE as _IMPLEMENTATION_PACKAGE

_LOCAL_HOSTS = {None, "", "localhost", "localhost.localdomain", "127.0.0.1", "::1"}


def _is_local(host: Any) -> bool:
    return isinstance(host, (str, type(None))) and host in _LOCAL_HOSTS


class NetworkAccessError(AssertionError):
    """Raised when a guarded test attempts an outbound connection.

    Subclasses `AssertionError` so pytest reports it as a *failure* rather than an error:
    reaching the network from the fast tier is a broken assertion about the system, not an
    infrastructure problem.
    """


@dataclass
class ConnectionAttempt:
    """One recorded attempt, kept whether or not the caller swallowed the exception."""

    api: str          # "socket.connect", "socket.connect_ex", "socket.create_connection"
    address: Any      # whatever the caller passed; not normalized, so the record is honest


@dataclass
class SocketGuard:
    """Blocks and records outbound connections while installed."""

    attempts: list[ConnectionAttempt] = field(default_factory=list)
    _originals: dict[str, Any] = field(default_factory=dict, repr=False)
    _installed: bool = field(default=False, repr=False)

    # -- lifecycle ---------------------------------------------------------------------
    def install(self) -> None:
        if self._installed:
            return
        self._originals = {
            "connect": socket.socket.connect,
            "connect_ex": socket.socket.connect_ex,
            "create_connection": socket.create_connection,
            "getaddrinfo": socket.getaddrinfo,
            "sendto": socket.socket.sendto,
        }

        guard = self

        def _connect(self_sock, address, *args, **kwargs):  # noqa: ANN001
            guard._record_and_raise("socket.connect", address)

        def _connect_ex(self_sock, address, *args, **kwargs):  # noqa: ANN001
            guard._record_and_raise("socket.connect_ex", address)

        def _create_connection(address, *args, **kwargs):  # noqa: ANN001
            guard._record_and_raise("socket.create_connection", address)

        def _sendto(self_sock, data, *args, **kwargs):  # noqa: ANN001
            # UDP needs no connect(), so sendto is its own egress path.
            address = args[-1] if args else kwargs.get("address")
            guard._record_and_raise("socket.sendto", address)

        def _getaddrinfo(host, port, *args, **kwargs):  # noqa: ANN001
            # A hostname lookup is already egress: it leaves the machine, and on the
            # air-gapped tier (§4.5 E5) it is exactly what must not happen. Resolutions
            # that never leave the host are still allowed through.
            if _is_local(host):
                return guard._originals["getaddrinfo"](host, port, *args, **kwargs)
            guard._record_and_raise("socket.getaddrinfo", (host, port))

        socket.socket.connect = _connect          # type: ignore[method-assign]
        socket.socket.connect_ex = _connect_ex    # type: ignore[method-assign]
        socket.socket.sendto = _sendto            # type: ignore[method-assign]
        socket.create_connection = _create_connection  # type: ignore[assignment]
        socket.getaddrinfo = _getaddrinfo         # type: ignore[assignment]
        self._installed = True

    def uninstall(self) -> None:
        if not self._installed:
            return
        socket.socket.connect = self._originals["connect"]              # type: ignore[method-assign]
        socket.socket.connect_ex = self._originals["connect_ex"]        # type: ignore[method-assign]
        socket.socket.sendto = self._originals["sendto"]                # type: ignore[method-assign]
        socket.create_connection = self._originals["create_connection"]  # type: ignore[assignment]
        socket.getaddrinfo = self._originals["getaddrinfo"]             # type: ignore[assignment]
        self._originals.clear()
        self._installed = False

    # -- assertions --------------------------------------------------------------------
    @property
    def installed(self) -> bool:
        return self._installed

    def assert_no_network(self) -> None:
        """Assert nothing tried to connect.

        The positive half of the oracle. Call this even when the code under test is expected
        to raise, because an attempt that was made and then swallowed still fails the claim
        "no model call is made".
        """
        if self.attempts:
            made = ", ".join(f"{a.api}{a.address!r}" for a in self.attempts)
            raise AssertionError(
                f"expected no network activity, but {len(self.attempts)} connection "
                f"attempt(s) were made: {made}"
            )

    # -- internals ---------------------------------------------------------------------
    def _record_and_raise(self, api: str, address: Any) -> None:
        self.attempts.append(ConnectionAttempt(api=api, address=address))
        raise NetworkAccessError(
            f"blocked {api}({address!r}). The fast tier runs with no network "
            f"(test plan §4.5 E1); model calls go through RecordedFixtureProvider. "
            f"Mark the test `live` if it genuinely needs a socket."
        )


# --- the filesystem write audit ------------------------------------------------------------


class DiskWriteError(AssertionError):
    """Raised when an audited block writes to disk.

    `AssertionError` for the same reason as `NetworkAccessError`: a module that promised to
    write nothing and then wrote is a broken claim about the system, not an infrastructure
    problem.
    """


@dataclass
class WriteAttempt:
    """One recorded write, kept whether or not the caller swallowed the exception."""

    api: str      # "open", "Path.write_text", "sqlite3.connect", ...
    target: Any   # whatever the caller passed; not normalized, so the record is honest

    #: The implementation module that **performed** the write — the innermost `aeh.*` frame on
    #: the stack, as its design label (`M-PKG`, `M-GRADE`, ...). `None` when no implementation
    #: frame is involved, which is what a test's own scaffolding writes look like.
    attributed_to: str | None = None

    #: The implementation module that **started** the call chain — the outermost `aeh.*` frame.
    #: Different from `attributed_to` exactly when one module wrote through another, which is
    #: the distinction `CT-CONFORM-12` is about: `M-CONFORM` runs whole pipelines and owns none
    #: of their output, so a validation record shows `attributed_to="M-PKG"` with
    #: `initiated_by="M-CONFORM"` — written *through* `M-PKG`, exactly as the clause requires.
    initiated_by: str | None = None


_WRITE_MODES = frozenset("wax+")

#: `aeh.<name>` -> the design's module label. Used for write attribution; a module absent here
#: is reported by its dotted path rather than dropped, so a new module shows up as unattributed
#: noise instead of silently reading as "not this module's write".
_MODULE_LABELS: dict[str, str] = {
    "conf": "M-CONF",
    "prov": "M-PROV",
    "store": "M-STORE",
    "pkg": "M-PKG",
    "setup": "M-SETUP",
    "ingest": "M-INGEST",
    "orch": "M-ORCH",
    "extract": "M-EXTRACT",
    "integ": "M-INTEG",
    "judge": "M-JUDGE",
    "det": "M-DET",
    "agg": "M-AGG",
    "synth": "M-SYNTH",
    "grade": "M-GRADE",
    "review": "M-REVIEW",
    "stats": "M-STATS",
    "conform": "M-CONFORM",
    "console": "M-CONSOLE",
    "calib": "M-CALIB",
}


def _implementation_frames() -> list[str]:
    """The `aeh.*` module labels on the current stack, innermost first.

    §6.11.18's oracle for `TC-CONFORM-12` is a *"write-audit log with per-stack attribution"*, and
    the stack is the only thing that can supply it: the write APIs are patched globally, so the
    record itself carries no idea of who called it. Without this, every attempt looks identical
    and `CT-CONFORM-12` — whose whole claim is *which* module a write belongs to — has no oracle
    at all.

    Walked with `sys._getframe` rather than `inspect.stack()`, which builds a `FrameInfo` with
    source context per frame and turns a run with thousands of writes into a minute of I/O.
    """
    labels: list[str] = []
    depth = 1
    while True:
        try:
            frame = sys._getframe(depth)
        except ValueError:
            break
        depth += 1
        name = frame.f_globals.get("__name__", "")
        if not name.startswith(f"{_IMPLEMENTATION_PACKAGE}."):
            continue
        submodule = name.split(".", 2)[1]
        label = _MODULE_LABELS.get(submodule, name)
        if not labels or labels[-1] != label:
            labels.append(label)
    return labels


def _attribution() -> tuple[str | None, str | None]:
    """`(performed_by, initiated_by)` for the write happening right now."""
    labels = _implementation_frames()
    if not labels:
        return None, None
    return labels[0], labels[-1]


@contextmanager
def write_audit() -> Iterator[list[WriteAttempt]]:
    """Fail the block if anything in it writes to disk. Yields the attempt log.

    This exists because `StoreSpy` cannot answer the question. The spy is a *passive recorder*
    shaped like design §3.3's `Store` — it only sees writes routed through a handle a caller
    was given. `M-CONF` is a leaf that takes no store at all (`CT-CONF-09`: "Writes nothing. No
    database, no file, no blob"), so `StoreSpy().assert_no_writes()` after a resolution is
    vacuous: it passes for every possible implementation, including one that caches its result
    to a file on every call.

    `TC-CONF-C09` states the shape this needs — *"the data directory, the blob directory and the
    database under a write-audit hook; assert zero writes of any kind"* — which is a filesystem
    audit, not a store double. That case belongs to TS-58 (issue #9); this is the hook it will
    use, and it is here now because `TC-CONF-02`'s substituted oracle leans on it.

    Deliberately narrow: reads are untouched, so a test that opens a fixture inside the block
    still works. Only the write-capable modes and the mutating `Path`/`os` calls are blocked.
    """
    attempts: list[WriteAttempt] = []

    real_open = builtins.open
    real_path_open = pathlib.Path.open
    real_write_text = pathlib.Path.write_text
    real_write_bytes = pathlib.Path.write_bytes
    real_mkdir = pathlib.Path.mkdir
    real_unlink = pathlib.Path.unlink
    real_remove = os.remove
    real_rename = os.rename
    real_connect = sqlite3.connect

    def _fail(api: str, target: Any) -> None:
        attempts.append(WriteAttempt(api=api, target=target))
        raise DiskWriteError(
            f"blocked {api}({target!r}): this block must write nothing to disk "
            f"(CT-CONF-09). If a write is legitimate here, audit it explicitly rather than "
            f"widening the guard."
        )

    def _is_write_mode(mode: Any) -> bool:
        return isinstance(mode, str) and bool(_WRITE_MODES & set(mode))

    def _open(file, mode="r", *args, **kwargs):  # noqa: ANN001
        if _is_write_mode(mode):
            _fail("open", file)
        return real_open(file, mode, *args, **kwargs)

    def _path_open(self, mode="r", *args, **kwargs):  # noqa: ANN001
        if _is_write_mode(mode):
            _fail("Path.open", self)
        return real_path_open(self, mode, *args, **kwargs)

    builtins.open = _open                                        # type: ignore[assignment]
    pathlib.Path.open = _path_open                               # type: ignore[method-assign]
    pathlib.Path.write_text = lambda self, *a, **k: _fail("Path.write_text", self)  # type: ignore[method-assign]
    pathlib.Path.write_bytes = lambda self, *a, **k: _fail("Path.write_bytes", self)  # type: ignore[method-assign]
    pathlib.Path.mkdir = lambda self, *a, **k: _fail("Path.mkdir", self)  # type: ignore[method-assign]
    pathlib.Path.unlink = lambda self, *a, **k: _fail("Path.unlink", self)  # type: ignore[method-assign]
    os.remove = lambda path, *a, **k: _fail("os.remove", path)   # type: ignore[assignment]
    os.rename = lambda src, dst, *a, **k: _fail("os.rename", (src, dst))  # type: ignore[assignment]
    sqlite3.connect = lambda *a, **k: _fail("sqlite3.connect", a[0] if a else None)  # type: ignore[assignment]

    try:
        yield attempts
    finally:
        builtins.open = real_open                                # type: ignore[assignment]
        pathlib.Path.open = real_path_open                       # type: ignore[method-assign]
        pathlib.Path.write_text = real_write_text                # type: ignore[method-assign]
        pathlib.Path.write_bytes = real_write_bytes              # type: ignore[method-assign]
        pathlib.Path.mkdir = real_mkdir                          # type: ignore[method-assign]
        pathlib.Path.unlink = real_unlink                        # type: ignore[method-assign]
        os.remove = real_remove                                  # type: ignore[assignment]
        os.rename = real_rename                                  # type: ignore[assignment]
        sqlite3.connect = real_connect                           # type: ignore[assignment]


# --- the filesystem read audit ---------------------------------------------------------------


@dataclass
class ReadAttempt:
    """One recorded read. Records rather than raises — see `open_audit`."""

    api: str      # "open", "Path.read_text", "sqlite3.connect", ...
    target: Any   # whatever the caller passed; not normalized, so the record is honest


@contextmanager
def open_audit() -> Iterator[list[ReadAttempt]]:
    """Record every file a block opens for reading. Yields the log; asserts nothing itself.

    `write_audit()` cannot answer `CT-CONF-01`. That clause is *"reads no file the caller did
    not name"* — a **read** assertion — and `write_audit` deliberately leaves reads untouched so
    a test can open a fixture inside its block. `TC-CONF-C01`'s oracle is "no unnamed file",
    which is a comparison between two *sets*: what was opened, and what the caller named.

    **Records rather than raises**, unlike its write-side sibling, and the difference is the
    point. Raising stops at the first read, so the failure message names one file when the
    interesting fact is the whole set — and an implementation that reads a profile table from
    disk would report only the first of six. A record-only audit also lets the read succeed, so
    the code under test proceeds normally and the case still gets to assert on its *result*.

    `sqlite3.connect` is recorded here too: `CT-CONF-12`'s "no database read" is the same
    question asked of a different API, and a module that opened a connection but only issued
    `SELECT`s would slip past `write_audit` entirely.

    **The low-level bindings are patched too**, and that was a review finding rather than
    foresight: `os.open` + `os.read` is a complete file read that touches none of the high-level
    APIs, and `io.open` is a *separate binding* to the same function, so rebinding
    `builtins.open` leaves it working. A resolver reading a profile table through either left the
    entire repository green.

    Caller-named paths are subtracted by the test, not here — the audit does not know which
    paths a given case considers named.
    """
    attempts: list[ReadAttempt] = []

    real_open = builtins.open
    real_io_open = io.open
    real_os_open = os.open
    real_path_open = pathlib.Path.open
    real_read_text = pathlib.Path.read_text
    real_read_bytes = pathlib.Path.read_bytes
    real_connect = sqlite3.connect

    def _record(api: str, target: Any) -> None:
        attempts.append(ReadAttempt(api=api, target=target))

    def _open(file, mode="r", *args, **kwargs):  # noqa: ANN001
        _record("open", file)
        return real_open(file, mode, *args, **kwargs)

    def _path_open(self, mode="r", *args, **kwargs):  # noqa: ANN001
        _record("Path.open", self)
        return real_path_open(self, mode, *args, **kwargs)

    def _read_text(self, *args, **kwargs):  # noqa: ANN001
        _record("Path.read_text", self)
        return real_read_text(self, *args, **kwargs)

    def _read_bytes(self, *args, **kwargs):  # noqa: ANN001
        _record("Path.read_bytes", self)
        return real_read_bytes(self, *args, **kwargs)

    def _connect(*args, **kwargs):  # noqa: ANN001
        _record("sqlite3.connect", args[0] if args else None)
        return real_connect(*args, **kwargs)

    def _os_open(path, flags, *args, **kwargs):  # noqa: ANN001
        _record("os.open", path)
        return real_os_open(path, flags, *args, **kwargs)

    builtins.open = _open                          # type: ignore[assignment]
    # A separate binding, not an alias of the one above: rebinding `builtins.open` leaves
    # `io.open` pointing at the original, and `io.open(path)` is a working read the audit would
    # never see. Found by review — a resolver reading a file through `os.open`/`os.read` left the
    # whole repository green.
    io.open = _open                                # type: ignore[assignment]
    os.open = _os_open                             # type: ignore[assignment]
    pathlib.Path.open = _path_open                 # type: ignore[method-assign]
    pathlib.Path.read_text = _read_text            # type: ignore[method-assign]
    pathlib.Path.read_bytes = _read_bytes          # type: ignore[method-assign]
    sqlite3.connect = _connect                     # type: ignore[assignment]

    try:
        yield attempts
    finally:
        builtins.open = real_open                  # type: ignore[assignment]
        io.open = real_io_open                     # type: ignore[assignment]
        os.open = real_os_open                     # type: ignore[assignment]
        pathlib.Path.open = real_path_open         # type: ignore[method-assign]
        pathlib.Path.read_text = real_read_text    # type: ignore[method-assign]
        pathlib.Path.read_bytes = real_read_bytes  # type: ignore[method-assign]
        sqlite3.connect = real_connect             # type: ignore[assignment]


@contextmanager
def recording_write_audit() -> Iterator[list[WriteAttempt]]:
    """Record every write a block makes, without blocking any of them. Yields the log.

    The sibling `write_audit()` **raises** on the first write, which makes it the wrong tool for a
    case that must distinguish a *permitted* write from a forbidden one. `TC-CALIB-C06` is exactly
    that case: every rubric edit must reach Tier P **through `M-PKG`**, so the catalog's own write
    is required and any other write is the violation. Under the blocking guard the two are
    indistinguishable — the first write raises, whichever it was, and the assertion that the
    catalog *did* write becomes unreachable.

    §6.11.17's Oracle for that case is a "**Write-audit log**", which is this shape rather than a
    guard. Review found the blocking version making C06's two assertions jointly unsatisfiable
    against a real on-disk catalog, and its carefully worded failure message unreachable.

    Same APIs as `write_audit`, same narrowness — reads are untouched, only write-capable modes and
    the mutating `Path`/`os`/`sqlite3` calls are seen.
    """
    attempts: list[WriteAttempt] = []

    real_open = builtins.open
    real_path_open = pathlib.Path.open
    real_write_text = pathlib.Path.write_text
    real_write_bytes = pathlib.Path.write_bytes
    real_mkdir = pathlib.Path.mkdir
    real_unlink = pathlib.Path.unlink
    real_remove = os.remove
    real_rename = os.rename
    real_connect = sqlite3.connect

    def _record(api: str, target: Any) -> None:
        performed_by, initiated_by = _attribution()
        attempts.append(
            WriteAttempt(
                api=api, target=target, attributed_to=performed_by, initiated_by=initiated_by
            )
        )

    def _is_write_mode(mode: Any) -> bool:
        return isinstance(mode, str) and bool(_WRITE_MODES & set(mode))

    def _open(file, mode="r", *args, **kwargs):  # noqa: ANN001
        if _is_write_mode(mode):
            _record("open", file)
        return real_open(file, mode, *args, **kwargs)

    def _path_open(self, mode="r", *args, **kwargs):  # noqa: ANN001
        if _is_write_mode(mode):
            _record("Path.open", self)
        return real_path_open(self, mode, *args, **kwargs)

    def _write_text(self, *a, **k):  # noqa: ANN001
        _record("Path.write_text", self)
        return real_write_text(self, *a, **k)

    def _write_bytes(self, *a, **k):  # noqa: ANN001
        _record("Path.write_bytes", self)
        return real_write_bytes(self, *a, **k)

    def _mkdir(self, *a, **k):  # noqa: ANN001
        _record("Path.mkdir", self)
        return real_mkdir(self, *a, **k)

    def _unlink(self, *a, **k):  # noqa: ANN001
        _record("Path.unlink", self)
        return real_unlink(self, *a, **k)

    def _connect(*a, **k):  # noqa: ANN001
        _record("sqlite3.connect", a[0] if a else None)
        return real_connect(*a, **k)

    builtins.open = _open                                        # type: ignore[assignment]
    pathlib.Path.open = _path_open                               # type: ignore[method-assign]
    pathlib.Path.write_text = _write_text                        # type: ignore[method-assign]
    pathlib.Path.write_bytes = _write_bytes                      # type: ignore[method-assign]
    pathlib.Path.mkdir = _mkdir                                  # type: ignore[method-assign]
    pathlib.Path.unlink = _unlink                                # type: ignore[method-assign]
    os.remove = lambda path, *a, **k: (_record("os.remove", path), real_remove(path, *a, **k))[1]
    os.rename = lambda s, d, *a, **k: (_record("os.rename", (s, d)), real_rename(s, d, *a, **k))[1]
    sqlite3.connect = _connect                                   # type: ignore[assignment]

    try:
        yield attempts
    finally:
        builtins.open = real_open                                # type: ignore[assignment]
        pathlib.Path.open = real_path_open                       # type: ignore[method-assign]
        pathlib.Path.write_text = real_write_text                # type: ignore[method-assign]
        pathlib.Path.write_bytes = real_write_bytes              # type: ignore[method-assign]
        pathlib.Path.mkdir = real_mkdir                          # type: ignore[method-assign]
        pathlib.Path.unlink = real_unlink                        # type: ignore[method-assign]
        os.remove = real_remove                                  # type: ignore[assignment]
        os.rename = real_rename                                  # type: ignore[assignment]
        sqlite3.connect = real_connect                           # type: ignore[assignment]
