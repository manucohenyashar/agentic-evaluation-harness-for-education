"""The smoke suite (TS-50, issue #143) — the console comes up where it is allowed to.

`TC-SMOKE-07` (`FR-CONSOLE-05`) — the console binds to loopback and serves its index; it
refuses to start on `cloud-hosted`. Fails if bound beyond loopback or started on the cloud
profile.

The bind half is asserted on the **bound socket**, not the setting — `getsockname()` is the
only witness the code under test cannot fake, the distinction §6.11.19 draws and the reason
`CT-CONSOLE-05` (issue #131) reads the same socket. "Serves its index" is the headless
render (`CT-CONSOLE-01`: nothing requires the browser) — the socket guard stands between
this test and any HTTP client, deliberately, so the index is read the way every other
consumer reads the console: through `render()`, which is the same page the child serves.
The refusal half keys on the deployment profile first (`CT-CONSOLE-20`'s order), and the
non-loopback bind refusal is the second wall the same case stands behind.

The one `serve_console` call that succeeds spawns the real child process; it is terminated
in a `finally`, exactly as the contract case does. Runtime is a fraction of a second — the
smoke budget carries it.

`Written ahead of implementation: yes` is stale — `M-CONSOLE` landed with #122-#126; the
case runs green by design.
"""

from __future__ import annotations

import pytest

from aeh.console import ConsoleBindRefused, serve_console
from tests.support.conf_builders import hosted_cfg
from tests.support.store_spy import StoreSpy


def test_tc_smoke_07_console_binds_loopback_serves_index_refuses_cloud_hosted():
    """`TC-SMOKE-07` — loopback bind witnessed on the socket, the index renders, and the
    cloud-hosted profile refuses before any bind happens.

    Oracle: **witness, content, refusal**. The bound socket's `getsockname()` names a
    loopback address — a console configured loopback that actually bound `0.0.0.0` reads
    correct from every configuration assertion and is RISK-20 (an unauthenticated
    student-record system on a school LAN), which is why the witness is the socket and not
    `bind_address`. The headless render of the root route returns real markup. And
    `serve_console` under a `cloud-hosted` cfg raises `ConsoleBindRefused` — the profile
    refusal fires **before** bind validation, so a routable `CONSOLE_BIND` under
    `cloud-hosted` cannot argue its way to a running server (`CT-CONSOLE-20`).
    """
    server = serve_console(StoreSpy())
    try:
        host, *_ = server.socket.getsockname()
        assert host in ("127.0.0.1", "::1"), (
            f"TC-SMOKE-07: the console is actually bound to {host!r}, not loopback. "
            "FR-CONSOLE-05: an unauthenticated student-record system runs on one machine, "
            "loopback only — RISK-20 is this exact bind."
        )
    finally:
        server.terminate()

    # The index serves real markup through the headless driver — the same render the
    # child process serves, read without an HTTP client because the socket guard is the
    # suite's network policy.
    from aeh.console import build_console

    page = build_console(StoreSpy()).render("/")
    assert page.html.strip(), (
        "TC-SMOKE-07: the console's index route rendered empty markup. A console that "
        "binds and serves nothing is the deployment that looks started and helps nobody."
    )

    # The cloud-hosted refusal — before any bind validation, whatever the settings say.
    with pytest.raises(ConsoleBindRefused):
        serve_console(StoreSpy(), cfg=hosted_cfg())
    # The bind wall is real too: a routable bind is refused on its own profile.
    with pytest.raises(ConsoleBindRefused):
        serve_console(StoreSpy(), cfg={"CONSOLE_BIND": "0.0.0.0"})