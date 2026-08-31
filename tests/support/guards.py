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

import socket
from dataclasses import dataclass, field
from typing import Any


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
        }

        guard = self

        def _connect(self_sock, address, *args, **kwargs):  # noqa: ANN001
            guard._record_and_raise("socket.connect", address)

        def _connect_ex(self_sock, address, *args, **kwargs):  # noqa: ANN001
            guard._record_and_raise("socket.connect_ex", address)

        def _create_connection(address, *args, **kwargs):  # noqa: ANN001
            guard._record_and_raise("socket.create_connection", address)

        socket.socket.connect = _connect          # type: ignore[method-assign]
        socket.socket.connect_ex = _connect_ex    # type: ignore[method-assign]
        socket.create_connection = _create_connection  # type: ignore[assignment]
        self._installed = True

    def uninstall(self) -> None:
        if not self._installed:
            return
        socket.socket.connect = self._originals["connect"]              # type: ignore[method-assign]
        socket.socket.connect_ex = self._originals["connect_ex"]        # type: ignore[method-assign]
        socket.create_connection = self._originals["create_connection"]  # type: ignore[assignment]
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
