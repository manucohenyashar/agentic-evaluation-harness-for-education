"""`TC-CONSOLE-64` (issue #771, FR-CONSOLE-62, FR-PKG-28) — `approve draft package`: the
gate between a draft and a published package version, driven over the recorded AF-09
fixture (`eng8-essay-01`, whose draft carries four sentinel placeholders).

| Arm | Expected |
|---|---|
| (a) approve a draft that still carries sentinels | refused with `FR-PKG-28`'s own sentence — the first unfinished field, its line, the reason, and `(N more placeholder line(s) remain)` — with the server-side draft path projected out of the message and the way back in `next_action` |
| (b) every review item answered, then approve | dispatched; the built package version appears in the catalog (`published_version` on the package page's context row, `state == 'published'`) |
| (c) approve the same draft again | idempotent: the already-approved sentence, nothing dispatched, and no second version in the catalog |

The plan's arm (a) says "a draft with 2 placeholders"; the AF-09 draft carries four, which
exercises the `(N more ...)` clause the sentence ends with — the same oracle, at the
larger boundary. The recorded chain is the support module's declared reconcile.

**Isolation: rung 3 (E1)** — real store, real console over real HTTP, the recorded
provider; the approval goes through M-PKG's own build door.
"""

from __future__ import annotations

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
from tests.support.console_redesign_world import (
    _action,
    _get_json,
    draft_read,
    run_draft_job,
    served_authoring,
)

pytestmark = pytest.mark.integration

#: The AF-09 draft's review items and the answers the review walk accepts — the same
#: answer grammar the authoring suite's journey fixture carries.
AF09_ANSWERS = (
    ("approved_by", "Prof. Dana Whitfield"),
    ("model_answer", "3/4, because 2/8 + 4/8 = 6/8 = 3/4."),
    ("criterion Q1",
     "none: the essay states no thesis at all (0 points); "
     "clear: a clear thesis supported by evidence from the text (4 points)"),
    ("grades A", "8"),
)


def _af09_draft(served_authoring):
    """Run the recorded AF-09 draft job; `(port, data_dir, package id, placeholders)`."""
    _server, port, _store, data_dir = served_authoring
    _answer, record = run_draft_job(port, "AF-09")
    assert record["state"] == "succeeded", f"the draft job ended {record['state']}"
    document = draft_read(port)["draft"]
    items = [item["item_id"] for item in document["placeholders"]]
    assert set(items) == {item_id for item_id, _ in AF09_ANSWERS}, (
        f"the AF-09 draft's open items are {items}, not the ones this case answers")
    return port, data_dir, document["package_id"], items


def test_tc_console_64a_approving_a_draft_with_sentinels_is_refused_with_the_locations(
        served_authoring):
    """The gate refuses an unfinished draft with FR-PKG-28's own sentence: the first
    unfinished field, its line, the sentinel it still carries, how many more remain, and
    the way back — with the server-side path projected out of the message."""
    port, data_dir, package_id, _items = _af09_draft(served_authoring)

    answer = _action(port, "approve draft package", {"package_id": package_id})

    assert answer["refused"] is True
    assert answer["dispatched"] is False
    detail = answer["detail"]
    # The console clarity delta (#808, FR-UI-25) replaced FR-PKG-28's engineering sentence
    # (field, line, sentinel) with the teacher's three parts; the count stands.
    assert answer["what"] == f"{package_id} was not published."
    assert answer["why"] == (
        f"The draft still has {len(_items)} unanswered pieces, and a test is published "
        "only when every piece is answered.")
    assert detail == f"{answer['what']} {answer['why']}"
    assert str(data_dir) not in detail, (
        "the refusal carries a server-side path; CT-CONSOLE-31 projects the draft's "
        "server path to its file name")
    assert answer["next_action"] == (
        "Answer the remaining questions on the review screen, then press Approve again.")


def test_tc_console_64b_the_resolved_draft_approves_to_a_published_version(served_authoring):
    """Answer every review item, then approve: the build goes through, the outcome names
    the version and the next step, and the package page's context row shows the version
    published."""
    port, _data_dir, package_id, _items = _af09_draft(served_authoring)

    answered = _action(port, "answer authoring review", {
        "package_id": package_id,
        "answers": [{"item_id": item_id, "value": value}
                    for item_id, value in AF09_ANSWERS],
    })
    assert answered["refused"] is False, answered["detail"]
    assert answered["next_action"] == "approve the draft package."
    assert draft_read(port)["draft"]["placeholders"] == []

    approved = _action(port, "approve draft package", {"package_id": package_id})

    assert approved["refused"] is False, approved["detail"]
    assert approved["dispatched"] is True
    detail = approved["detail"]
    # FR-CONSOLE-73 (#808): the outcome names the version in teacher words, never by id.
    assert detail.startswith(f"Published {package_id}, version 1."), detail
    assert "Approved by Prof. Dana Whitfield on " in detail
    assert detail.endswith("Next: load the students' papers.")
    assert "@" not in detail
    assert approved["next"] == {"label": "Load papers", "route": "/papers"}

    context = _get_json(port, "/api/v1/context")
    rows = [row for row in context["packages"] if row["package_id"] == package_id]
    assert len(rows) == 1, f"the package page lists {len(rows)} row(s) for {package_id}"
    assert rows[0]["published_version"], "the catalog names no published version"
    assert rows[0]["state"] == "published"
    assert rows[0]["version_count"] >= 1


def test_tc_console_64c_replaying_the_approval_is_idempotent_and_builds_no_second_version(
        served_authoring):
    """Approving the unchanged draft again answers the already-approved sentence,
    dispatches nothing, and the catalog carries no second version."""
    port, _data_dir, package_id, _items = _af09_draft(served_authoring)
    _action(port, "answer authoring review", {
        "package_id": package_id,
        "answers": [{"item_id": item_id, "value": value}
                    for item_id, value in AF09_ANSWERS],
    })
    approved = _action(port, "approve draft package", {"package_id": package_id})
    assert approved["refused"] is False
    context = _get_json(port, "/api/v1/context")
    version = next(row["published_version_id"] for row in context["packages"]
                   if row["package_id"] == package_id)

    replay = _action(port, "approve draft package", {"package_id": package_id})

    assert replay["refused"] is False
    assert replay["dispatched"] is False, (
        f"the replay dispatched ({replay!r}); approving an unchanged draft must "
        "change nothing")
    # FR-CONSOLE-73 (#808): a repeat press is the success outcome, prefixed — no hash.
    assert replay["detail"].startswith(
        f"Already published — {package_id}, version 1."), replay["detail"]
    assert "@" not in replay["detail"]
    assert "job_id" not in replay

    context = _get_json(port, "/api/v1/context")
    rows = [row for row in context["packages"] if row["package_id"] == package_id]
    assert rows[0]["published_version_id"] == version
    assert rows[0]["version_count"] == 1, (
        f"the catalog now lists {rows[0]['version_count']} version(s); the idempotent "
        "replay must not have built a second one")
