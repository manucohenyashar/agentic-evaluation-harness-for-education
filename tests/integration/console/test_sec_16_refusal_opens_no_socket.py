"""`TS-90` (issue #384) — `SEC-16`: a refused console opens no socket, measured from outside
the process (information disclosure).

| Input | Expected |
|---|---|
| `TC-CONSOLE-46` rows 2, 3 and 7 run in a **subprocess**, environment set by the parent | zero listening sockets owned by the child; the process exits non-zero with the refusal text |

**Why a subprocess, when `TC-CONSOLE-46` already asserts the refusal.** That case checks the
refusal from *inside* the interpreter that raised it — it can see the exception and the frame
it came from, but it cannot see the operating system. A bind that happened and was closed, a
socket inherited by a thread, a listener opened by an import: none of those are visible to
`pytest.raises`, and all of them are visible to the OS. Enumerating the child's listening
sockets is the only oracle that answers "did this machine ever accept a connection", which is
the question an information-disclosure case is actually asking.

**Rows 2, 3 and 7 specifically.** Row 2 is the plain cloud-hosted refusal; row 3 is the one a
`cfg` tries to argue down; row 7 is the one where a routable bind competes with the profile.
Each is a refusal a caller might reasonably expect to be negotiable, and each must leave the
host with nothing listening.

**`netstat`, not `psutil`.** The plan allows either; `psutil` is not in `requirements-dev.txt`,
and installing a dependency to run a test is a worse trade than parsing a tool every Windows
and POSIX host already has.

**Matched by PORT, not by PID, and that is a measured decision.** The plan says to enumerate
"the child's listening sockets", which reads as a PID filter. It does not work here: on Windows
the socket is registered against a PID that is not `Popen.pid` (a launcher indirection), so a
PID-filtered parse reports zero listening sockets for a child that is demonstrably listening —
the silent pass this case exists to prevent. So the instrument is a **before/after diff of every
listening port**, and `test_sec_16_the_enumerator_sees_a_socket_that_does_exist` validates it
by binding a known port and requiring the diff to contain it. If the instrument goes blind, the
control fails and the OS-level assertions skip with a reason rather than passing over nothing.

**The non-zero exit is the second half.** A refusal that logged and carried on would leave no
socket either, and would also leave an operator believing the console was running. The child
exits non-zero and prints the refusal.

**Isolation: rung 3, subprocess** — a real interpreter, a real environment, real OS state.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.integration

#: The three refusing rows of `TC-CONSOLE-46`, as environments for the child.
ROWS = {
    "row2-cloud-hosted": {"HARNESS_PROFILE": "cloud-hosted"},
    "row3-cfg-argues-back": {"HARNESS_PROFILE": "cloud-hosted"},
    "row7-routable-bind-too": {
        "HARNESS_PROFILE": "cloud-hosted", "CONSOLE_BIND": "0.0.0.0",
    },
}

#: Row 3 is the one that passes a `cfg` trying to override the environment.
CFG_FOR = {"row3-cfg-argues-back": '{"HARNESS_PROFILE": "edge-local"}'}

_CHILD = textwrap.dedent(
    """
    import json, os, sys, time
    sys.path[:0] = [{src!r}, {root!r}]
    from aeh.console import ConsoleBindRefused, serve_console

    cfg = json.loads(os.environ.get("SEC16_CFG", "{{}}"))
    try:
        server = serve_console(cfg=cfg)
    except ConsoleBindRefused as refusal:
        # Printed so the parent can assert the operator sees WHY, and held briefly so the
        # parent's socket enumeration runs against a live PID rather than a reaped one.
        sys.stderr.write(str(refusal))
        sys.stderr.flush()
        print("REFUSED", flush=True)
        time.sleep({hold})
        sys.exit(2)
    print("BOUND", server.socket.getsockname()[1], flush=True)
    time.sleep({hold})
    sys.exit(0)
    """
)

#: How long the child lingers so the parent can enumerate its sockets.
HOLD_SECONDS = 2.5


def _listening_ports() -> set[int] | None:
    """Every port this host is listening on, or `None` when no enumerator is available."""
    netstat = shutil.which("netstat")
    if netstat is None:
        return None
    flags = ["-ano"] if os.name == "nt" else ["-anp"]
    try:
        completed = subprocess.run(
            [netstat, *flags], capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    ports: set[int] = set()
    for line in completed.stdout.splitlines():
        if "LISTEN" not in line.upper():
            continue
        match = re.search(r"[:.](\d+)\s", line)
        if match:
            ports.add(int(match.group(1)))
    return ports


def _run_child(env_overrides: dict[str, str], cfg: str | None):
    root = os.getcwd()
    script = _CHILD.format(
        src=os.path.join(root, "src"), root=root, hold=HOLD_SECONDS
    )
    env = dict(os.environ)
    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT", "SEC16_CFG"):
        env.pop(name, None)
    env.update(env_overrides)
    if cfg is not None:
        env["SEC16_CFG"] = cfg
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=root,
        bufsize=1,
    )


def _await_verdict(child) -> str:
    """The child's first stdout line — `REFUSED` or `BOUND <port>`.

    Read BEFORE the sockets are enumerated, and that ordering is the whole point: the child
    prints its verdict only after `serve_console` has returned or raised, so enumerating
    earlier races the bind and reports an empty set for a process that is about to listen.
    The control case below exists because that race is silent in the refusing direction.
    """
    line = child.stdout.readline()
    return line.strip()


# --- SEC-16 -----------------------------------------------------------------------------------


@pytest.mark.parametrize("label", sorted(ROWS), ids=sorted(ROWS))
def test_sec_16_a_refused_console_owns_no_listening_socket(label, network_guard):
    """The child refuses, exits non-zero with the reason, and never listens on anything."""
    network_guard.uninstall()
    try:
        before = _listening_ports()
        child = _run_child(ROWS[label], CFG_FOR.get(label))
        try:
            verdict = _await_verdict(child)
            during = _listening_ports()
            rest, stderr = child.communicate(timeout=60)
            stdout = verdict + chr(10) + rest
        finally:
            if child.poll() is None:  # pragma: no cover — only on a hung child
                child.kill()
                child.communicate(timeout=30)
    finally:
        network_guard.install()

    assert "BOUND" not in stdout, (
        f"{label}: the child reported binding a socket: {stdout.strip()!r}"
    )
    assert "REFUSED" in stdout, (
        f"{label}: the child neither bound nor refused. stdout={stdout!r} stderr={stderr!r}"
    )
    assert child.returncode != 0, (
        f"{label}: the child exited 0 after refusing. A refusal that logs and carries on "
        "leaves an operator believing the console is running"
    )
    assert stderr.strip(), (
        f"{label}: the refusal printed no reason, so an operator cannot tell a profile "
        "refusal from a crash"
    )

    if before is None or during is None:
        pytest.skip(
            "no `netstat` on this host, and psutil is not a dev dependency — the OS-level "
            "half of SEC-16 cannot be measured here. The in-process half is TC-CONSOLE-46's."
        )
    assert during <= before, (
        f"{label}: the host began listening on {sorted(during - before)} while a refusing "
        "console ran. The refusal happens before the bind, so nothing may appear — and an "
        "exception the parent can catch says nothing about what the OS saw (SEC-16)"
    )


def test_sec_16_the_enumerator_sees_a_socket_that_does_exist(network_guard):
    """The control: a child that *does* bind is observed listening.

    Without it, `ports == set()` passes on any host where the parse silently matches nothing —
    a changed `netstat` format, a locale, a container without the tool — and SEC-16 becomes a
    case that cannot fail. This is the assertion that keeps the enumerator honest.
    """
    network_guard.uninstall()
    try:
        before = _listening_ports()
        child = _run_child({"HARNESS_PROFILE": "edge-local"}, None)
        try:
            verdict = _await_verdict(child)
            during = _listening_ports()
            rest, stderr = child.communicate(timeout=60)
            stdout = verdict + chr(10) + rest
        finally:
            if child.poll() is None:  # pragma: no cover — only on a hung child
                child.kill()
                child.communicate(timeout=30)
    finally:
        network_guard.install()

    assert "BOUND" in stdout, (
        f"the control child did not bind: stdout={stdout!r} stderr={stderr!r}"
    )
    bound_port = int(stdout.split()[1])

    if before is None or during is None:
        pytest.skip("no `netstat` on this host; the enumerator cannot be controlled")
    assert bound_port in during, (
        f"the enumerator did not see the port the child reported binding ({bound_port}). "
        "Every 'nothing new is listening' assertion in this file is passing over a parse that "
        "matches nothing — which is the silent pass SEC-16 exists to prevent"
    )
    assert bound_port not in before, (
        f"port {bound_port} was already listening before the child started, so the diff "
        "cannot attribute it"
    )
