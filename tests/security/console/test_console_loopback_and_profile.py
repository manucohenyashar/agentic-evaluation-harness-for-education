"""`TS-49` (issue #130) — the console refuses a routable bind and the cloud profile, and a LAN
host cannot connect.

Test plan §5.19 `TC-CONSOLE-05` (`FR-CONSOLE-05`, `NFR-SYS-12`) and §6.5 `SEC-10`, Security /
rung 2, negative: a real store, a real served console, the bound socket as witness.

**What these add over `CT-CONSOLE-C05`/`-C20` and `TC-SMOKE-07`.** Those cases drive the refusal
through the `cfg` dict handed to `serve_console`, over `StoreSpy`, and sweep every setting
combination of it. What none of them does:

* **The deployment profile where a deployment sets it.** `aeh.conf.environment_snapshot` is how a
  running installation's `HARNESS_PROFILE` enters the system — from the process environment. A
  console started on a `cloud-hosted` machine with no hand-built `cfg` is the case `NFR-SYS-12`
  exists for: *the refusal is in code, not documentation*, so it cannot depend on the caller
  remembering to pass the profile along.
* **`CONSOLE_BIND = 0.0.0.0` set the way an operator sets it** — in the environment — witnessed on
  the socket: the console binds loopback or refuses, never the routable address.
* **The LAN connection refused at the socket** (`SEC-10`'s third probe): a connection attempted to
  the running console's port on each of this machine's non-loopback addresses — the address
  another LAN host would use — must be refused, while loopback accepts.

**Written ahead of implementation.** The issue says `yes`; stale — `M-CONSOLE` landed (#122).
"""

from __future__ import annotations

import errno
import socket

import pytest

from aeh.console import ConsoleBindRefused, serve_console, start_console
from aeh.store import open_store
from tests.support.conf_builders import hosted_cfg
from tests.support.console_world import seed_scored_run

pytestmark = [pytest.mark.integration]

_LOOPBACK = ("127.0.0.1", "::1")


def _fail_with(problems: list[str]) -> None:
    assert not problems, "\n\n".join(problems)


def _local_non_loopback_ipv4() -> list[str]:
    return sorted({
        info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        if not info[4][0].startswith("127.")
    })


# --- TC-CONSOLE-05 — loopback only, and no start on the cloud profile, however it is set ----------


def test_tc_console_05_the_console_binds_loopback_and_refuses_the_cloud_profile(
    tmp_data_dir, monkeypatch
):
    """`TC-CONSOLE-05` — exact refusal plus socket binding assertion, over a real store.

    Collected clauses:

    1. `CONSOLE_BIND=0.0.0.0` in the environment: the console either refuses or its bound socket
       is loopback — never the routable address (whether the knob is read at all is the separate
       case below);
    2. `CONSOLE_BIND=0.0.0.0` in the configuration: refused (`ConsoleBindRefused`) before binding;
    3. `backend_profile = 'cloud-hosted'` in the configuration: refused — in code, whatever else the
       configuration says (`NFR-SYS-12`).
    """
    store = open_store(tmp_data_dir)
    try:
        world = seed_scored_run(store, submissions=1)
        problems: list[str] = []

        monkeypatch.setenv("CONSOLE_BIND", "0.0.0.0")
        try:
            server = serve_console(store=store, run_id=world.run_id)
        except ConsoleBindRefused:
            pass
        else:
            try:
                host = server.socket.getsockname()[0]
                if host not in _LOOPBACK:
                    problems.append(f"with CONSOLE_BIND=0.0.0.0 in the environment the console "
                                    f"bound {host!r}")
            finally:
                server.terminate()
        monkeypatch.delenv("CONSOLE_BIND")

        try:
            leaked = serve_console(store=store, cfg={"CONSOLE_BIND": "0.0.0.0"})
        except ConsoleBindRefused:
            pass
        else:
            leaked.terminate()
            problems.append("a configured CONSOLE_BIND=0.0.0.0 started a console")

        for cfg in (hosted_cfg(), hosted_cfg(CONSOLE_BIND="127.0.0.1")):
            try:
                leaked = start_console(cfg, store=store)
            except ConsoleBindRefused:
                continue
            leaked.terminate()
            problems.append(f"a cloud-hosted configuration started a console: {sorted(cfg)}")
        _fail_with(problems)
    finally:
        store.close()


@pytest.mark.writtenahead
def test_tc_console_05_the_bind_and_profile_set_in_the_environment_are_honoured(
    tmp_data_dir, monkeypatch
):
    """`TC-CONSOLE-05`, the environment half — two findings the configuration-dict cases cannot see.

    1. **`CONSOLE_BIND` is an env-gated knob that is never read.** `aeh/console.py`'s four-seams
       section declares `CONSOLE_BIND`/`CONSOLE_PORT` knobs "read at call time"; the discriminating
       probe is a *legal* loopback value other than the default — `CONSOLE_BIND=::1` must produce an
       `::1` socket. A knob the console ignores cannot be told apart from one it refuses, which is why
       clause 1 of the case above cannot carry this.
    2. **`HARNESS_PROFILE=cloud-hosted` in the process environment, no configuration passed.**
       Contested interpretation, stated as such: `aeh.conf.environment_snapshot` is how a deployment's
       profile enters the system, and it is the caller's to merge (`conf.py`), so the gap may belong
       to "which layer applies the snapshot at console start-up" rather than to `serve_console`. It is
       asserted because FR-CONSOLE-05 says the console *refuses to start* on the cloud profile and no
       layer in the repository today makes a console started on such a machine refuse.
    """
    store = open_store(tmp_data_dir)
    try:
        problems: list[str] = []
        if socket.has_ipv6:
            monkeypatch.setenv("CONSOLE_BIND", "::1")
            server = None
            try:
                server = serve_console(store=store)
                host = server.socket.getsockname()[0]
                if host != "::1":
                    problems.append(
                        f"with CONSOLE_BIND=::1 in the environment the console bound {host!r}: the "
                        f"declared env-gated knob is never read (ConsoleServer takes the bind from "
                        f"its cfg or the module default only)"
                    )
            except ConsoleBindRefused as refusal:
                problems.append(f"a loopback CONSOLE_BIND=::1 was refused: {refusal}")
            finally:
                if server is not None:
                    server.terminate()
            monkeypatch.delenv("CONSOLE_BIND")

        monkeypatch.setenv("HARNESS_PROFILE", "cloud-hosted")
        for label, start in (("start_console()", lambda: start_console(store=store)),
                             ("serve_console()", lambda: serve_console(store=store))):
            try:
                leaked = start()
            except ConsoleBindRefused:
                continue
            host = leaked.socket.getsockname()[0]
            leaked.terminate()
            problems.append(
                f"{label} started a console bound to {host!r} on a machine whose deployment "
                f"profile is HARNESS_PROFILE=cloud-hosted: the refusal keys only on a `cfg` dict "
                f"the caller passes, and nothing applies the deployment's own profile at start-up "
                f"(FR-CONSOLE-05, NFR-SYS-12)"
            )
        _fail_with(problems)
    finally:
        store.close()


# --- SEC-10 — the three probes, the third being a LAN host's connection --------------------------


def test_sec_10_a_lan_host_cannot_reach_the_console_and_neither_probe_starts_it(
    tmp_data_dir, network_guard
):
    """`SEC-10` / `FR-CONSOLE-05` — Spoofing / A01, no authN by design.

    Probes 1 and 2 (`CONSOLE_BIND = 0.0.0.0`, `cloud-hosted`) are refused before any socket exists
    — asserted here in their configured form; the environment forms are `TC-CONSOLE-05`'s. Probe 3:
    a console served over a real store, then a TCP connection to its port from each of this
    machine's non-loopback IPv4 addresses, which is what another LAN host would reach. Expected:
    refused at the socket, while the same port accepts on loopback (so the refusal is the bind,
    not a dead port), and a throwaway listener bound to every interface IS reachable on the same
    addresses (so the refusal is not a firewall or an unroutable address). Only a refused connection
    counts as refused; a timeout or other error is inconclusive. The autouse socket guard is stood
    down only around these connects; addresses are resolved first. A host with no non-loopback
    interface, or none that answers conclusively, skips with that reason.
    """
    store = open_store(tmp_data_dir)
    server = None
    try:
        world = seed_scored_run(store, submissions=1)
        for probe in ({"CONSOLE_BIND": "0.0.0.0"}, hosted_cfg(CONSOLE_BIND="0.0.0.0")):
            with pytest.raises(ConsoleBindRefused):
                serve_console(store=store, cfg=probe)

        network_guard.uninstall()
        try:
            lan_addresses = _local_non_loopback_ipv4()
        finally:
            network_guard.install()
        if not lan_addresses:
            pytest.skip("no non-loopback IPv4 interface to stand in for another LAN host")

        server = serve_console(store=store, run_id=world.run_id)
        host, port = server.socket.getsockname()[:2]
        assert host in _LOOPBACK, f"the served console is bound to {host!r}"
        refused_codes = {errno.ECONNREFUSED, getattr(errno, "WSAECONNREFUSED", errno.ECONNREFUSED)}
        network_guard.uninstall()
        reached, inconclusive = [], []
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5):
                pass  # positive control 1: the console's port is live on loopback
            # Positive control 2: a throwaway listener bound to every interface IS reachable on
            # these addresses — so a refusal below is the console's bind, not a firewall or an
            # unroutable address.
            witness = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            witness.bind(("0.0.0.0", 0))
            witness.listen(1)
            witness_port = witness.getsockname()[1]
            try:
                for address in lan_addresses:
                    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    probe.settimeout(10)
                    try:
                        if probe.connect_ex((address, witness_port)) != 0:
                            inconclusive.append(address)
                    finally:
                        probe.close()
            finally:
                witness.close()
            for address in [a for a in lan_addresses if a not in inconclusive]:
                probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                probe.settimeout(10)
                try:
                    code = probe.connect_ex((address, port))
                finally:
                    probe.close()
                if code == 0:
                    reached.append(address)
                elif code not in refused_codes:
                    inconclusive.append(f"{address} (errno {code})")
        finally:
            network_guard.install()
        if inconclusive and len(inconclusive) >= len(lan_addresses):
            pytest.skip(f"no LAN address gave a conclusive answer: {inconclusive}")
        assert not reached, (
            f"another LAN host reaches the console at {reached}:{port} — SEC-10: the LAN "
            f"connection is refused at the socket"
        )
    finally:
        if server is not None:
            server.terminate()
        store.close()
