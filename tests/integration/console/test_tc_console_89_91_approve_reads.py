"""`TC-CONSOLE-89..91` (issue #825, FR-CONSOLE-72, FR-CONSOLE-73, FR-CONSOLE-74) — the
version label, the package summary on the draft read, and the approve outcomes, over an
ENG7 draft on a served console.

Console clarity test plan §3.4, story T9. TC-REG-18 (the second-press regression) is
`tests/regression/test_reg_18_second_approve.py`.

| Case | Expected |
|---|---|
| 89 | revisions 0, 1, 5 read "version 1", "version 2", "version 6"; the approval date reads "20 Oct 2026"; M-PKG's own first version (revision 1) is "version 1"; an unknown version id is refused without echoing the id |
| 90 | ENG7 draft, approver and `grades pass` answered: test name; approver with `source = "your answer"`; Q1/Q2/Q3 points 2/3/3, total 8; grades pass 6 / not yet 0, max 8; rubric lines under their questions. Approver unanswered: "Not answered yet" |
| 91 | (a) first approve: "Published ENG7-READ-01, version 1. Approved by Dana Teacher on <date>. Next: load the students' papers.", `next` → Load papers; (b) repeat: not refused, detail starts "Already published —"; (c) a gap open: refused with what / why / next and no ID |

**The draft** is the shipped assembler's ENG7 draft with the AF-23 grade table (pass named, no
boundary), written into the console's authoring folder (`clarity_world.write_eng7_draft`):
AF-23's drafting replies are not recorded yet, so the draft job cannot replay them.

**Plan deviation, disclosed (91a's date).** The plan's literal "on 20 Oct 2026" cannot be
pinned: the approval date is `package_version.published_at`, which M-PKG writes with SQLite's
`datetime('now')` — there is no clock seam on the publish path. 91a compares the date against
the stored `published_at`, formatted here independently of the console ("D Mon YYYY", fixed
English months), and checks it is today's UTC date; the "20 Oct 2026" formatting itself is
pinned in 89 against a stored approval record.

**Isolation: rung 3** — a real store, the real console over real HTTP, M-PKG's own build.
**Written ahead of implementation: no** (#808, #809 landed).

Markers. `integration`.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

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
from tests.support.clarity_world import build_eng7_package, write_eng7_draft
from tests.support.console_redesign_world import _action, draft_read, served_console

pytestmark = pytest.mark.integration

PACKAGE = "ENG7-READ-01"
APPROVER = "Dana Teacher"
AF23_GRADES: dict[str, float | None] = {"pass": None, "not yet": None}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
#: FR-UI-23's ID shapes a teacher string must not carry.
_ID = re.compile(r"\b(FR|NFR|CT|TC|ADR|RS)-[A-Z0-9]+|@[0-9a-f]{12}\b|\bpkg-|\.toml\b|"
                 r"\.sqlite\b")

__all__ = ["served_console"]  # the fixture, imported for pytest


def _teacher_date(value: str) -> str:
    day = datetime.fromisoformat(value.replace(" ", "T")).date()
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def _eng7_draft(data_dir):
    return write_eng7_draft(data_dir / "authoring", AF23_GRADES)


def _answer(port: int, answers: dict[str, str]) -> dict:
    outcome = _action(port, "answer authoring review", {
        "package_id": PACKAGE,
        "answers": [{"item_id": k, "value": v} for k, v in answers.items()]})
    assert outcome["refused"] is False, outcome
    return outcome


# --- TC-CONSOLE-89 --------------------------------------------------------------------------


def test_tc_console_89_version_label_numbers_date_and_unknown_refusal(served_console) -> None:
    from aeh.console.version_labels import UnknownPackageVersion, read_version_label, \
        version_label_for

    _server, _port, store, _data_dir = served_console
    package = "VLBL-01"
    ids = {rev: f"{package}@{rev:012x}" for rev in (0, 1, 5)}
    with store.package(package).transaction() as tx:
        tx.execute("INSERT INTO package (package_id, created_at) VALUES (:p, :t)",
                   p=package, t="2026-10-01T00:00:00+00:00")
        for rev, vid in ids.items():
            tx.execute("INSERT INTO package_version (package_version_id, package_id, "
                       "revision, locked) VALUES (:v, :p, :r, 0)", v=vid, p=package, r=rev)
        tx.execute("UPDATE package_version SET published_by = :b, "
                   "published_at = '2026-10-20 09:00:00' WHERE package_version_id = :v",
                   b=APPROVER, v=ids[0])

    for rev, expected in ((0, "version 1"), (1, "version 2"), (5, "version 6")):
        assert read_version_label(store, ids[rev]).version == expected, f"revision {rev}"
    first = read_version_label(store, ids[0])
    assert first.approved_on == "20 Oct 2026"
    assert first.approved_by == APPROVER
    assert first.text(with_date=True) == "VLBL-01 version 1 (approved 20 Oct 2026)"

    # M-PKG mints a package's first version at revision 1: that is still "version 1".
    _pid, built = build_eng7_package(store)
    assert read_version_label(store, built).text() == f"{PACKAGE} version 1"
    assert version_label_for(store)(built) == "version 1"

    for unknown in (f"{PACKAGE}@ffffffffffff", "NO-SUCH-PKG@0123456789ab", "not-an-id"):
        with pytest.raises(UnknownPackageVersion) as refused:
            read_version_label(store, unknown)
        message = str(refused.value)
        assert unknown not in message and "@" not in message, (
            f"the refusal echoes the id: {message!r}")
        assert message.strip(), "the refusal says nothing"
        assert version_label_for(store)(unknown) is None


# --- TC-CONSOLE-90 --------------------------------------------------------------------------


def test_tc_console_90_package_summary_of_the_answered_eng7_draft(served_console) -> None:
    _server, port, _store, data_dir = served_console
    _eng7_draft(data_dir)

    unanswered = draft_read(port)["draft"]["summary"]
    assert unanswered["approver"]["value"] == "Not answered yet"
    assert unanswered["approver"]["answered"] is False

    _answer(port, {"approved_by": APPROVER, "grades pass": "6"})
    summary = draft_read(port)["draft"]["summary"]

    assert summary["test"]["value"] == PACKAGE
    assert summary["approver"] == {"value": APPROVER, "answered": True,
                                   "source": "your answer"}
    questions = summary["questions"]
    assert [(q["number"], q["points"]["value"]) for q in questions] == [
        ("Q1", 2), ("Q2", 3), ("Q3", 3)]
    assert summary["total_points"] == 8
    grades = summary["grades"]
    assert grades["max"] == 8
    assert [(row["grade"], row["lowest_total"]) for row in grades["rows"]] == [
        ("pass", 6), ("not yet", 0)]
    assert next(r for r in grades["rows"] if r["grade"] == "pass")["source"] == "your answer"
    # Rubric lines sit under their own question: Q1 the checklist (composite + 2 aspects),
    # Q2 and Q3 one banded line each, with their score levels.
    assert [len(q["rubric"]) for q in questions] == [3, 1, 1]
    q2_levels = questions[1]["rubric"][0]["levels"]["value"]
    assert [(lvl["name"], lvl["points"]) for lvl in q2_levels] == [
        ("none", 0), ("limited", 1), ("adequate", 2), ("full", 3)]
    q3_levels = questions[2]["rubric"][0]["levels"]["value"]
    assert [lvl["name"] for lvl in q3_levels] == ["none", "retell", "change", "evidenced"]
    assert summary["unanswered"] == 0


# --- TC-CONSOLE-91 --------------------------------------------------------------------------


def test_tc_console_91a_first_approve_names_version_approver_date_and_next(
        served_console) -> None:
    _server, port, store, data_dir = served_console
    _eng7_draft(data_dir)
    _answer(port, {"approved_by": APPROVER, "grades pass": "6"})

    before = datetime.now(timezone.utc).date()
    approved = _action(port, "approve draft package", {"package_id": PACKAGE})
    after = datetime.now(timezone.utc).date()

    assert approved["refused"] is False, approved
    rows = store.package(PACKAGE).query(
        "SELECT published_at FROM package_version WHERE published_at IS NOT NULL")
    assert len(rows) == 1
    stored = str(rows[0]["published_at"])
    on = _teacher_date(stored)
    assert on in {_teacher_date(before.isoformat()), _teacher_date(after.isoformat())}
    assert approved["detail"] == (
        f"Published {PACKAGE}, version 1. Approved by {APPROVER} on {on}. "
        "Next: load the students' papers.")
    assert approved["next"] == {"label": "Load papers", "route": "/papers"}


def test_tc_console_91b_second_approve_is_already_published_not_a_refusal(
        served_console) -> None:
    _server, port, _store, data_dir = served_console
    _eng7_draft(data_dir)
    _answer(port, {"approved_by": APPROVER, "grades pass": "6"})
    first = _action(port, "approve draft package", {"package_id": PACKAGE})
    assert first["refused"] is False

    again = _action(port, "approve draft package", {"package_id": PACKAGE})

    assert again["refused"] is False, again
    assert again["detail"].startswith("Already published —"), again["detail"]
    assert again["detail"] == "Already published — " + first["detail"].removeprefix(
        "Published "), "the repeat is the same outcome, prefixed"
    assert again["next"] == {"label": "Load papers", "route": "/papers"}


def test_tc_console_91c_approve_with_a_gap_open_is_a_three_part_refusal_without_ids(
        served_console) -> None:
    _server, port, _store, data_dir = served_console
    _eng7_draft(data_dir)
    _answer(port, {"grades pass": "6"})  # the approver still stands open

    refused = _action(port, "approve draft package", {"package_id": PACKAGE})

    assert refused["refused"] is True
    assert refused["dispatched"] is False
    for part in ("what", "why", "next_action"):
        text = refused.get(part) or ""
        assert text.strip(), f"the refusal has no {part}"
        assert not _ID.search(text), f"{part} carries an ID: {text!r}"
        assert str(data_dir) not in text
    assert not _ID.search(refused["detail"]), refused["detail"]
    assert refused["why"] == ("The draft still has 1 unanswered piece, and a test is "
                              "published only when every piece is answered.")
