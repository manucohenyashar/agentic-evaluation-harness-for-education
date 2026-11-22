"""Validity T8 (issue #901): TC-CONSOLE-105's alert arm (FR-CONSOLE-81, CT-STATS-19).

FR-CONSOLE-81: *"The repeated-skip alert (`BLIND_SAMPLE_SKIPPED_ALERT`) is reachable through
it"* (the console's `blind-sample skip`). After the configured number of consecutive skipped
administrations the alert is raised; one administration earlier it is not.

**Written ahead: yes — a defect, not a missing story.** The alert exists only in M-STATS'
in-memory `ValidationStats.alerts()`, fed by `build_stats(administrations=...)`. Nothing in
`src/` calls `.alerts()` over stored records, `open_stats` takes no administrations, and no
console read names the alert. So N console skips, each recorded by `promote_administration`
with `absence_reason = 'skipped'`, raise nothing a teacher or operator can read. This case
drives the skips through the console and looks for the alert on the reads the console serves
for the test and the run (the validity read, the package record, System status). It is red
until the console carries the alert. Registry: `WRITTEN_AHEAD_BLOCKERS` key
`"#901 defect — FR-CONSOLE-81 repeated-skip alert unreachable"`, a `command` probe that
resolves once `src/aeh/console` names `BLIND_SAMPLE_SKIPPED_ALERT`. When it fires, remove the
marker, keep the test, drop the entry. The rest of TC-CONSOLE-105 runs green in
`test_tc_console_105_107_114_blind_flow.py`.

The threshold is set to 3 (`STATS_BLIND_SKIP_ALERT_AFTER`, default 2), so "one run earlier"
is two skips, not one.

World: the validity seed's store (`tests/support/validity_seed.py`): three administrations of
one version, each skipped by the console's own action over HTTP (rung 3).
"""

from __future__ import annotations

import json

import pytest

from tests.support.label_identity_world import ServedRun
from tests.support.validity_seed import HOLISTIC, ValidityStore

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

THRESHOLD = 3
#: CT-STATS-19's alert name and the detail's words, either of which a read may carry.
ALERT_SIGNS = ("blind_sample_skipped_consecutive_administrations",
               "consecutive administrations without a blind sample")


def _alert_shown(console: ServedRun, run_id: str, version: str) -> list[str]:
    reads = {
        "validity": console.get("/api/v1/results/validity", run_id=run_id),
        "record": console.get("/api/v1/packages/record", package_version_id=version),
        "system status": console.get("/api/v1/system-status", run_id=run_id),
    }
    for name, (status, _body) in reads.items():
        assert status == 200, (name, reads[name])
    return [name for name, (_status, body) in reads.items()
            if any(sign in json.dumps(body) for sign in ALERT_SIGNS)]


def test_tc_console_105_b_the_repeated_skip_alert_after_the_configured_skips(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-105 (alert arm): two console skips raise nothing; the third raises
    `BLIND_SAMPLE_SKIPPED_ALERT` on a console read."""
    from aeh.console import serve_console

    monkeypatch.setenv("STATS_BLIND_SKIP_ALERT_AFTER", str(THRESHOLD))
    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    world = ValidityStore(tmp_path / "w")
    administrations = [world.administer(f"class-{k}", {HOLISTIC: ("B2",) * 15})
                       for k in range(THRESHOLD)]
    network_guard.uninstall()
    server = serve_console(store=world.store)
    try:
        console = ServedRun(world=administrations[0], server=server,
                            port=server.socket.getsockname()[1], root=world.root)
        version = administrations[0].package_version_id
        for count, administration in enumerate(administrations, 1):
            status, outcome = console.action("blind-sample skip", run_id=administration.run_id)
            assert status == 200 and outcome.get("dispatched"), (status, outcome)
            shown = _alert_shown(console, administration.run_id, version)
            if count < THRESHOLD:
                assert not shown, f"the alert is raised after {count} skips: {shown}"
        assert shown, (
            f"{THRESHOLD} consecutive console skips raise BLIND_SAMPLE_SKIPPED_ALERT on no "
            "console read (validity, package record, System status): FR-CONSOLE-81 says it is "
            "reachable through the skip action")
    finally:
        try:
            server.terminate()
        finally:
            network_guard.install()
            world.close()
