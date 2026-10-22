"""TC-REG-18 (#825): T2b, a second press on Approve neither refuses nor shows "@".

Console-clarity test plan §3.12 (→ TC-CONSOLE-91, FR-CONSOLE-73). The live teacher test's
symptom: pressing Approve again on a published ENG7 draft answered with a refusal naming the
version hash (`ENG7-READ-01@<12 hex>`). Pinned here over the served console: the second press
is not refused, dispatches nothing, and no teacher field of the answer carries "@".

The draft is the shipped assembler's AF-23-shaped ENG7 draft (`clarity_world.write_eng7_draft`;
AF-23's drafting replies are not recorded yet).

Markers. `integration` (rung 3: a real store, the real console over HTTP, M-PKG's build).
"""

from __future__ import annotations

import pytest

from tests.support.clarity_world import write_eng7_draft
from tests.support.console_redesign_world import _action, served_console

pytestmark = pytest.mark.integration

__all__ = ["served_console"]  # the fixture, imported for pytest


def test_tc_reg_18_a_second_approve_neither_refuses_nor_shows_the_hash(served_console) -> None:
    _server, port, _store, data_dir = served_console
    write_eng7_draft(data_dir / "authoring", {"pass": None, "not yet": None})
    answered = _action(port, "answer authoring review", {
        "package_id": "ENG7-READ-01",
        "answers": [{"item_id": "approved_by", "value": "Dana Teacher"},
                    {"item_id": "grades pass", "value": "6"}]})
    assert answered["refused"] is False, answered
    first = _action(port, "approve draft package", {"package_id": "ENG7-READ-01"})
    assert first["refused"] is False, first

    second = _action(port, "approve draft package", {"package_id": "ENG7-READ-01"})

    assert second["refused"] is False, f"the second press was refused: {second!r}"
    assert second["dispatched"] is False, "the second press built again"
    for field in ("detail", "what", "why", "next_action"):
        assert "@" not in str(second.get(field) or ""), (
            f"the second press shows '@' in {field}: {second.get(field)!r}")
