"""`TC-CONSOLE-73` (issue #771, CT-CONSOLE-36, FR-PIPE-11) — the env knobs' refusals and
the `aeh console` startup.

| Arm | Expected |
|---|---|
| (a) a knob outside its domain | the read refuses with a message naming the knob, the offending value and the domain — `0` and a 200 MB ceiling both |
| (b) `aeh console` startup | the banner prints the clickable full URL (`http://127.0.0.1:<port>/`) and the one-line next step, and exits cleanly on the interrupt |
| (c) `HARNESS_CONSOLE_AUTO_OPEN` | `0` suppresses the browser-open; the interactive default opens it once with the URL; an unrecognized value warns on stderr naming the knob, the value and `0, false or off` |
| (d) `serve_console()` itself | never opens a browser — the auto-open lives on the CLI path only (`CT-CONSOLE-01`'s headless rule) |

The knob refusals ride the served console's read routes; the startup arms drive
`cli.main` in-process, with the sleep loop interrupted the way Ctrl-C would.

**Isolation: rung 3 (E1)** — real store, real console over real HTTP for (a); the CLI's
own startup path, in-process, for (b)–(d).
"""

from __future__ import annotations

import base64
import re

import pytest

import aeh.agg  # noqa: F401 — the full migration chain before the first store open (CLAUDE.md)
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
from aeh.console import serve_console
from aeh.grade.pdf import text_pdf_bytes
from aeh.pipeline import cli as console_cli
from aeh.store import open_store
from tests.support.console_redesign_world import (
    _post_json,
    served_console,
)

pytestmark = pytest.mark.integration


def _tiny_pdf() -> str:
    """One one-line text PDF, base64 — small enough for any ceiling, valid enough to
    reach the knob check."""
    return base64.b64encode(
        text_pdf_bytes(["Assessment: knob probe", "hello"])).decode("ascii")


def test_tc_console_73a_an_out_of_domain_knob_is_refused_naming_knob_value_and_domain(
        served_console, monkeypatch):
    """`HARNESS_AUTHOR_DOC_MAX_BYTES=0` and a 200 MB value are both refused with the
    declared-knob message: the knob's name, the offending value, the domain."""
    _server, port, _store, _data_dir = served_console

    monkeypatch.setenv("HARNESS_AUTHOR_DOC_MAX_BYTES", "0")
    status, body = _post_json(port, "/api/v1/authoring/preview", {
        "documents": [{"name": "probe.pdf", "content_base64": _tiny_pdf()}],
    })
    assert status == 400, body
    error = body["error"]
    assert "HARNESS_AUTHOR_DOC_MAX_BYTES=0" in error, error
    assert "from 1 to 104857600" in error, (
        f"the refusal does not name the domain: {error!r}")

    monkeypatch.setenv("HARNESS_AUTHOR_DOC_MAX_BYTES", str(200 * 1024 * 1024))
    status, body = _post_json(port, "/api/v1/authoring/preview", {
        "documents": [{"name": "probe.pdf", "content_base64": _tiny_pdf()}],
    })
    assert status == 400, body
    assert f"HARNESS_AUTHOR_DOC_MAX_BYTES={200 * 1024 * 1024}" in body["error"], (
        body["error"])

    # The roster ceiling's knob carries the same discipline, on its own read.
    monkeypatch.setenv("HARNESS_ROSTER_IMPORT_MAX_BYTES", "0")
    status, body = _post_json(port, "/api/v1/roster/preview",
                              {"content": "full_name\nAmara Okafor\n",
                               "name": "roster.csv"})
    assert status == 400, body
    assert "HARNESS_ROSTER_IMPORT_MAX_BYTES=0" in body["error"], body["error"]
    assert "from 1 to 104857600" in body["error"], body["error"]


def _run_console_command(monkeypatch, tmp_path, capsys, opener):
    """`aeh console` in-process: the sleep loop interrupted like Ctrl-C, the browser
    seam patched to `opener`. `(return code, stdout, stderr)`."""
    def interrupted_sleep(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(console_cli.time, "sleep", interrupted_sleep)
    monkeypatch.setattr(console_cli, "_open_console_browser", opener)
    code = console_cli.main(["console", "--data-dir", str(tmp_path)])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_tc_console_73b_the_banner_prints_the_clickable_url_and_the_next_step(
        tmp_path, monkeypatch, capsys):
    """The startup banner: the listening line, the full `http://127.0.0.1:<port>/` URL
    and the one-line next step — and, headless, no browser opened."""
    opened: list[str] = []
    code, out, err = _run_console_command(monkeypatch, tmp_path, capsys,
                                          lambda url: opened.append(url) or True)

    assert code == 0, (out, err)
    listening = re.search(r"console listening on port (\d+)", out)
    assert listening is not None, f"the banner's listening line is missing:\n{out}"
    assert f"  Grading console:  http://127.0.0.1:{listening.group(1)}/" in out, out
    assert ("  Next step:        create a class, then a test package — "
            "the home page walks you through it.") in out, out
    assert opened == [], (
        "the headless default opened a browser; auto-open is on for an interactive "
        "terminal only (CT-CONSOLE-01)")
    assert "not a recognized value" not in err


def test_tc_console_73c_auto_open_zero_suppresses_the_browser(tmp_path, monkeypatch,
                                                              capsys):
    """`HARNESS_CONSOLE_AUTO_OPEN=0`: no browser is opened, and no warning is printed —
    an explicit off is not a mistake."""
    monkeypatch.setenv("HARNESS_CONSOLE_AUTO_OPEN", "0")
    opened: list[str] = []
    code, _out, err = _run_console_command(monkeypatch, tmp_path, capsys,
                                           lambda url: opened.append(url) or True)

    assert code == 0
    assert opened == []
    assert "not a recognized value" not in err


def test_tc_console_73d_the_interactive_default_opens_the_banner_url_once(
        tmp_path, monkeypatch, capsys):
    """With no `HARNESS_CONSOLE_AUTO_OPEN` set and a tty behind both streams, the
    default opens the browser — once, with the banner's own URL."""
    monkeypatch.setattr(console_cli.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(console_cli.sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.delenv("HARNESS_CONSOLE_AUTO_OPEN", raising=False)
    opened: list[str] = []
    code, out, _err = _run_console_command(monkeypatch, tmp_path, capsys,
                                           lambda url: opened.append(url) or True)

    assert code == 0
    url = re.search(r"Grading console:\s+(\S+)", out).group(1)
    assert opened == [url], (
        f"the browser was opened with {opened!r}, not the banner's URL {url!r}, or "
        "not exactly once")


def test_tc_console_73e_an_unrecognized_auto_open_value_warns_and_stands_down(
        tmp_path, monkeypatch, capsys):
    """`HARNESS_CONSOLE_AUTO_OPEN=maybe`: the warning names the knob, the value and the
    accepted spellings, and the default (off, headless) stands in."""
    monkeypatch.setenv("HARNESS_CONSOLE_AUTO_OPEN", "maybe")
    opened: list[str] = []
    code, _out, err = _run_console_command(monkeypatch, tmp_path, capsys,
                                           lambda url: opened.append(url) or True)

    assert code == 0
    assert opened == []
    assert "HARNESS_CONSOLE_AUTO_OPEN='maybe'" in err, err
    assert "0, false or off" in err, err


def test_tc_console_73f_serve_console_never_opens_a_browser(
        tmp_path, network_guard, monkeypatch):
    """`serve_console()` binds and serves, and no browser is opened from it — the
    auto-open lives on the CLI path only, so tests and in-process drivers are unaffected
    (`CT-CONSOLE-01`)."""
    opened: list[str] = []

    import webbrowser
    monkeypatch.setattr(webbrowser, "open",
                        lambda url: opened.append(url) or True)

    store = open_store(tmp_path)
    network_guard.uninstall()
    try:
        server = serve_console(store=store)
    except BaseException:
        network_guard.install()
        store.close()
        raise
    try:
        assert opened == [], (
            "serve_console opened a browser; the headless rule forbids it")
    finally:
        server.terminate()
        network_guard.install()
        store.close()
