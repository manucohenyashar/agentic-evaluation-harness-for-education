"""`TC-CONSOLE-63` (issue #771, FR-CONSOLE-56) — `edit draft package`: the editor's
operations through the console, each change reported so a failure names the case.

| Arm | Expected |
|---|---|
| (a) add an option to a multiple-choice question | the outcome's change list **names the question** (`question '<id>' options — added option <letter>`), and the option is in the draft file the console rewrote |
| (b) reorder the criteria (`move criterion` to position 1) | the change names the move, and the draft read's criteria list reflects the new order |
| (c) an invalid edit (a question with no text) | refused with the editor's field-level message naming the question, and the draft file on disk unchanged |

The base draft is the recorded AF-02 draft (`geo8-climate-01`): three open questions,
three band criteria, numeric grade floors. **Two shipped defects shape arm (a)'s setup,
both flagged for follow-up in the PR — neither is papered over here:**

1. `render_draft`'s `[grades]` loop writes a non-`None` floor raw (`_toml_key(name) =
   {floor}`), so a grades placeholder sentinel — a quoted string in the file, parsed back
   as a string — renders **unquoted** and the draft file stops parsing. Every recorded
   draft that carries an mcq question (AF-09, AF-11) also carries a grades sentinel, so
   any edit round-trip on them corrupts the file (observed: the edit after an
   add-question answers "The draft file could not be read: line 31 does not parse as a
   draft").
2. `authoring_draft_read` projects `spec.get("questions")`, but the draft grammar's
   table key is `question` (singular, as `render_draft`, `validate_draft` and
   `_structural_issues` all read it) — the read's `items` list is empty for every real
   draft, so arm (a)'s read-back rides the draft file itself (`tomllib` over the same
   bytes the console rewrote), not the broken projection.

Arm (a) therefore seeds the editor's own two-form-steps end state into the recorded draft
file — the mcq question **and** the key criterion that grades it, which is what the
plan's ungraded-question rule demands before the plan layer stays clear — and then
exercises the arm the TC names: `add option` on that question.

**Isolation: rung 3 (E1)** — real store, real console over real HTTP, the recorded
provider (the support module's declared reconcile).
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path

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
    draft_path_in,
    draft_read,
    run_draft_job,
    served_authoring,
)

pytestmark = pytest.mark.integration

#: The mcq question and its grading point the option arm needs, in the draft grammar the
#: renderer itself writes — the editor's two form steps (question, then the grading point
#: that keys it), landed in the file before the option arm runs.
SEEDED_QUESTION = """
[[question]]
id = "Q9"
type = "mcq"
points = 1
text = "Which rock type forms when magma cools and solidifies?"
options = { "A" = "Igneous", "B" = "Sedimentary" }

[[criterion]]
id = "C_Q9"
question = "Q9"
key = "A"
"""


def _file_digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _af02_draft(served_authoring):
    """Run the recorded AF-02 draft job; `(port, data_dir, draft path, package id)`."""
    _server, port, _store, data_dir = served_authoring
    _answer, record = run_draft_job(port, "AF-02")
    assert record["state"] == "succeeded", f"the draft job ended {record['state']}"
    package_id = draft_read(port)["draft"]["package_id"]
    return port, data_dir, draft_path_in(data_dir, package_id), package_id


def test_tc_console_63a_adding_an_option_names_the_question_in_the_change_list(
        served_authoring):
    """Add an option to a multiple-choice question: the change list names the question
    the option belongs to, and the option is in the draft file the console rewrote."""
    port, _data_dir, path, package_id = _af02_draft(served_authoring)
    path.write_text(path.read_text(encoding="utf-8") + SEEDED_QUESTION,
                    encoding="utf-8")

    option = _action(port, "edit draft package", {
        "package_id": package_id,
        "operation": "add option",
        "item_id": "Q9",
        "letter": "C",
        "label": "Metamorphic",
    })

    assert option["refused"] is False, option["detail"]
    assert option["dispatched"] is True
    assert "question 'Q9' options — added option C" in option["detail"], (
        f"the change list does not name the question the option was added to: "
        f"{option['detail']!r}")
    assert option["detail"].startswith("the draft was edited (")

    # The option stands in the file the edit committed — read through the same grammar
    # the editor itself parses (`authoring_draft_read`'s items projection is the broken
    # `questions` key, flagged above).
    spec = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    questions = [q for q in spec["question"] if str(q.get("id")) == "Q9"]
    assert len(questions) == 1, (
        f"the rewritten draft carries {len(questions)} question(s) named 'Q9'")
    assert questions[0]["options"].get("C") == "Metamorphic", (
        f"the added option is missing from the rewritten draft: {questions[0]!r}")
    assert questions[0]["options"].get("A") == "Igneous", (
        "the rewrite lost an option the question already carried")


def test_tc_console_63b_reordering_the_criteria_is_reflected_in_the_draft_read(
        served_authoring):
    """Move a criterion to position 1: the change names the move, and the draft read's
    criteria list starts with it."""
    port, _data_dir, _path, package_id = _af02_draft(served_authoring)
    document = draft_read(port)["draft"]
    order_before = [criterion["id"] for criterion in document["criteria"]]
    assert len(order_before) >= 2, (
        f"the AF-02 draft carries {len(order_before)} criteria; the reorder arm needs "
        "at least two")
    moved = order_before[-1]

    answer = _action(port, "edit draft package", {
        "package_id": package_id,
        "operation": "move criterion",
        "item_id": moved,
        "position": 1,
    })

    assert answer["refused"] is False, answer["detail"]
    assert f"criterion '{moved}' — moved to position 1" in answer["detail"], (
        f"the move outcome does not name the criterion and its new position: "
        f"{answer['detail']!r}")
    order_after = [criterion["id"]
                   for criterion in draft_read(port)["draft"]["criteria"]]
    assert order_after[0] == moved, (
        f"the criteria list after the move starts with {order_after[0]!r}; the read "
        "must reflect the new order")
    assert sorted(order_after) == sorted(order_before), (
        "the move lost or duplicated a criterion")


def test_tc_console_63c_an_invalid_edit_is_refused_in_teacher_language_and_the_draft_stands(
        served_authoring):
    """A question added with no text is refused with the editor's field-level message —
    naming the question and that nothing was saved — and the draft file on disk is
    unchanged."""
    port, _data_dir, path, package_id = _af02_draft(served_authoring)
    before = _file_digest(path)

    answer = _action(port, "edit draft package", {
        "package_id": package_id,
        "operation": "add question",
        "question_type": "open",
        "text": "   ",
    })

    assert answer["refused"] is True, (
        f"the textless edit was answered {answer!r}; the editor must refuse it")
    assert answer["dispatched"] is False
    assert "the edit carries no text" in answer["detail"], (
        f"the refusal does not name the missing field: {answer['detail']!r}")
    assert "Nothing was saved." in answer["detail"]
    assert re.search(r"question '\w+'", answer["detail"]), (
        "the refusal does not name the question it was about")
    assert _file_digest(path) == before, (
        "a refused edit changed the draft file on disk")
