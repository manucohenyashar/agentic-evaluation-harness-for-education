"""`TS-90` (issue #384) — `TC-CONSOLE-46`: the console resolves its profile and bind from the
EFFECTIVE config, and refuses before it binds (`FR-CONSOLE-36`, `FR-CONF-14`, `CT-CONSOLE-20`,
`CT-CONSOLE-27`).

| Row | `HARNESS_PROFILE` | `CONSOLE_BIND` | `cfg` | Expected |
|---|---|---|---|---|
| 1 | unset | unset | `{}` | binds `127.0.0.1` |
| 2 | `cloud-hosted` | unset | `{}` | refuses; no socket |
| 3 | `cloud-hosted` | unset | `{"HARNESS_PROFILE": "edge-local"}` | **refuses**; `cfg` cannot argue the environment down |
| 4 | unset | `0.0.0.0` | `{}` | refuses — the loopback check on the *resolved* bind |
| 5 | unset | `0.0.0.0` | `{"CONSOLE_BIND": "127.0.0.1"}` | **refuses**: the environment wins over `cfg` |
| 6 | `edge-local` | `127.0.0.1` | `{"CONSOLE_PORT": 0}` | binds; the ephemeral port is reported |
| 7 | `cloud-hosted` | `0.0.0.0` | `{}` | refuses **naming the profile** — the profile check runs first |

**Rows 3 and 5 are the case.** Each is a configuration that would *look* safe if `cfg` were
read on its own, and each must still refuse because the environment is what the machine is
actually set to. A console that let a passed-in dict override `HARNESS_PROFILE` would start on
a cloud-hosted box for any caller who wrote `{"HARNESS_PROFILE": "edge-local"}` — which is the
one line an operator adds when the refusal is inconvenient. `FR-CONF-14` settles the
precedence; rows 1, 2, 4 and 6 all pass whichever way it is read.

**Row 7 is about refusal *order*, not refusal.** Both conditions hold, so any implementation
refuses; what it must not do is refuse for the bind. `CT-CONSOLE-20`: the profile is checked
first so a routable bind cannot argue with it, and the operator's message has to name the
condition that is not negotiable.

**"No socket" is asserted at the frame that raised, not inferred from the exception.** A
refusal that raised *after* binding would satisfy `pytest.raises` and leave a listening port on
a cloud-hosted host for as long as the socket stayed open — which is the whole failure. There
is no port to probe (the constructor returns nothing), so each refusing row asserts instead
that the exception came out of `_refuse_unless_servable`, which `ConsoleServer.__init__` runs
*before* it constructs `_ConsoleHTTPServer`. A refusal raised from any later frame fails here.

**Isolation: rung 2** — the real `ConsoleServer`, real `os.environ`, and a real socket on the
two rows that bind.
"""

from __future__ import annotations

import socket

import pytest

from aeh.console import ConsoleBindRefused, serve_console

pytestmark = pytest.mark.integration

PROFILE = "HARNESS_PROFILE"
BIND = "CONSOLE_BIND"

#: The rows that must refuse, as (id, env, cfg, what the message must name).
REFUSING_ROWS = (
    ("row2-cloud-hosted-env", {PROFILE: "cloud-hosted"}, {}, "profile"),
    (
        "row3-cfg-cannot-override-the-profile",
        {PROFILE: "cloud-hosted"},
        {PROFILE: "edge-local"},
        "profile",
    ),
    ("row4-routable-bind", {BIND: "0.0.0.0"}, {}, "bind"),
    (
        "row5-cfg-cannot-override-the-bind",
        {BIND: "0.0.0.0"},
        {BIND: "127.0.0.1"},
        "bind",
    ),
    (
        "row7-both-wrong-profile-first",
        {PROFILE: "cloud-hosted", BIND: "0.0.0.0"},
        {},
        "profile",
    ),
)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    """Neither variable set, whatever the developer's shell holds.

    `serve_console` reads `os.environ` through `effective_config`, so a stray `HARNESS_PROFILE`
    would make row 1 refuse and row 6 bind somewhere else — both for reasons about the machine
    rather than about the code.
    """
    for name in (PROFILE, BIND, "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)


def _listening(port: int) -> bool:
    """Whether anything answers on loopback at `port`."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(1.0)
    try:
        return probe.connect_ex(("127.0.0.1", port)) == 0
    finally:
        probe.close()


# --- TC-CONSOLE-46, the rows that bind ------------------------------------------------------


def test_tc_console_46_row_1_the_default_environment_binds_loopback(
    tmp_data_dir, network_guard, monkeypatch
):
    """Row 1 — nothing set, `cfg` empty: the console binds `127.0.0.1` and serves.

    The positive control for the whole matrix. Without it every refusal below would also pass
    against a console that refused unconditionally, which is a console nobody can run.
    """
    network_guard.uninstall()
    try:
        server = serve_console(cfg={})
    finally:
        network_guard.install()
    try:
        assert str(server.bind_address) == "127.0.0.1", (
            f"the console bound {server.bind_address!r}, not loopback"
        )
        host, port = server.socket.getsockname()[:2]
        assert host == "127.0.0.1"
        network_guard.uninstall()
        try:
            assert _listening(port), "the console reported a port nothing answers on"
        finally:
            network_guard.install()
    finally:
        server.terminate()


def test_tc_console_46_row_6_an_explicit_loopback_bind_reports_its_ephemeral_port(
    tmp_data_dir, network_guard, monkeypatch
):
    """Row 6 — `edge-local` + `127.0.0.1` + `CONSOLE_PORT: 0`: binds, and the port is reported.

    Port 0 asks the OS for an ephemeral port, so "the port is reported" is the assertion that
    the caller can find the server it just started. A console that returned the configured `0`
    would be telling the operator to connect to port zero.
    """
    monkeypatch.setenv(PROFILE, "edge-local")
    monkeypatch.setenv(BIND, "127.0.0.1")

    network_guard.uninstall()
    try:
        server = serve_console(cfg={"CONSOLE_PORT": 0})
    finally:
        network_guard.install()
    try:
        _host, port = server.socket.getsockname()[:2]
        assert port > 0, f"the console reported port {port}"
        network_guard.uninstall()
        try:
            assert _listening(port)
        finally:
            network_guard.install()
    finally:
        server.terminate()


# --- TC-CONSOLE-46, the rows that refuse ----------------------------------------------------


@pytest.mark.parametrize(
    "label,env,cfg,names", REFUSING_ROWS, ids=[row[0] for row in REFUSING_ROWS]
)
def test_tc_console_46_a_refusing_row_raises_before_it_binds(
    tmp_data_dir, network_guard, monkeypatch, label, env, cfg, names
):
    """Each refusing row raises `ConsoleBindRefused` **from the pre-bind check**.

    The five rows share one body because they share one contract: the refusal happens before
    the socket exists. A console that bound first and raised afterwards would pass a
    `pytest.raises`-only case while leaving a port open on a cloud-hosted host — so the frame
    the exception came from is asserted, which is the observable that distinguishes them.
    """
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    network_guard.uninstall()
    try:
        with pytest.raises(ConsoleBindRefused) as caught:
            serve_console(cfg=dict(cfg))
    finally:
        network_guard.install()

    message = str(caught.value).lower()
    assert names in message, (
        f"{label}: the refusal does not name the {names}: {caught.value!r}"
    )

    frames = [entry.name for entry in caught.traceback]
    assert "_refuse_unless_servable" in frames, (
        f"{label}: the refusal was raised from {frames}, not from the pre-bind check. "
        "`__init__` runs `_refuse_unless_servable` before `_ConsoleHTTPServer(...)`, and a "
        "refusal from any later frame means a socket already existed when it fired"
    )
    assert "_ConsoleHTTPServer" not in frames


def test_tc_console_46_row_7_refuses_for_the_profile_not_the_bind(
    tmp_data_dir, network_guard, monkeypatch
):
    """Row 7 — both conditions wrong: the message names the **profile**.

    Refusal order is the requirement here, and the parametrized case above cannot see it: any
    implementation refuses row 7, and one that checked the bind first would refuse it for the
    bind. `CT-CONSOLE-20` puts the profile first so a routable bind cannot argue with it, and
    an operator reading "bind 0.0.0.0 is not loopback" would try `127.0.0.1` and meet a second
    refusal they were not told about.
    """
    monkeypatch.setenv(PROFILE, "cloud-hosted")
    monkeypatch.setenv(BIND, "0.0.0.0")

    network_guard.uninstall()
    try:
        with pytest.raises(ConsoleBindRefused) as caught:
            serve_console(cfg={})
    finally:
        network_guard.install()

    message = str(caught.value).lower()
    assert "cloud-hosted" in message or "profile" in message, (
        f"the refusal does not name the profile: {caught.value!r}"
    )
    assert "0.0.0.0" not in message, (
        f"the refusal names the bind, so the bind was checked first: {caught.value!r}. The "
        "profile refusal is the one that is not negotiable, and an operator told about the "
        "bind will fix the bind and meet a second refusal nobody mentioned (CT-CONSOLE-20)"
    )


def test_tc_console_46_the_environment_is_re_read_rather_than_cached(
    tmp_data_dir, network_guard, monkeypatch
):
    """Two constructions in one process disagree when the environment changes between them.

    Not a plan row; it is what makes the matrix a matrix. If the effective config were resolved
    once per process, row 1 would pass and rows 2–7 would pass or fail depending on which ran
    first — and the whole table would be an artefact of test order.
    """
    network_guard.uninstall()
    try:
        server = serve_console(cfg={})
        server.terminate()

        monkeypatch.setenv(PROFILE, "cloud-hosted")
        with pytest.raises(ConsoleBindRefused):
            serve_console(cfg={})
    finally:
        network_guard.install()
