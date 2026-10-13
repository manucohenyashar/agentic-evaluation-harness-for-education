"""`TC-CONSOLE-63` (issue #771, FR-CONSOLE-56) — `edit draft package`: the editor's
operations through the console, each change reported so a failure names the case.

| Arm | Expected |
|---|---|
| (a) add an option to a multiple-choice question | the outcome's change list **names the question** (`question '<id>' options — added option <letter>`), and the option is in the draft file the console rewrote |
| (b) reorder the criteria (`move criterion` to position 1) | the change names the move, and the draft read's criteria list reflects the new order |
| (c) an invalid edit (a question with no text) | refused with the editor's field-level message naming the question, and the draft file on disk unchanged |

The base draft is the recorded AF-02 draft (`geo8-climate-01`): three open questions,
three band criteria, numeric grade floors. Arm (a) seeds the editor's own two-form-steps
end state into the recorded draft file — the mcq question **and** the key criterion that
grades it, which is what the plan's ungraded-question rule demands before the plan layer
stays clear — and then exercises the arm the TC names: `add option` on that question.

Two round-trip facts this file pins came out of the merge PR #794's shipped-defect
findings, fixed in the follow-up and planned as TC-CONSOLE-75/76 in the console redesign
plan (the `question` key itself was already corrected in #793):

1. `render_draft`'s `[grades]` loop renders a sentinel floor **quoted**, with its
   `# PLACEHOLDER(...)` reason comment above it (`FR-AUTHOR-11`), so a draft whose grades
   boundary is still a placeholder survives an edit's round-trip — the shipped loop wrote
   it raw and the rewritten draft stopped parsing
   (`test_an_edit_round_trip_keeps_a_draft_with_a_grades_placeholder_parseable`).
2. `authoring_draft_read` projects the grammar's singular `question` key, so the read's
   `items` mirror the draft file's tables
   (`test_the_draft_read_projects_the_questions_table_the_grammar_names`).

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
    # the editor itself parses; the projection has its own pin further down this file.
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
    # PR #794's finding 5: the message doubled the word (`… no text text. Nothing was
    # saved.`) because it interpolated the field name after the noun. The sentence reads
    # once, as a teacher meets it.
    assert "the edit carries no text. Nothing was saved." in answer["detail"], (
        f"the refusal's sentence is not the single-word form: {answer['detail']!r}")
    assert "Nothing was saved." in answer["detail"]
    assert re.search(r"question '\w+'", answer["detail"]), (
        "the refusal does not name the question it was about")
    assert _file_digest(path) == before, (
        "a refused edit changed the draft file on disk")


def test_the_draft_read_projects_the_questions_table_the_grammar_names(served_authoring):
    """PR #794's finding 2: `authoring_draft_read` projected `spec.get("questions")`, but
    the draft grammar's table is `question` (singular, as `render_draft`, `validate_draft`
    and `_structural_issues` all read it) — the read's `items` list was empty for every
    real draft, so the SPA's per-question views starved. (The key itself was corrected in
    #793; this pins the projection against the draft file's own grammar.)"""
    port, _data_dir, path, _package_id = _af02_draft(served_authoring)
    file_ids = [str(q["id"]) for q in tomllib.loads(
        path.read_text(encoding="utf-8"))["question"]]

    answer = draft_read(port)
    document = answer["draft"]

    assert [item["id"] for item in document["items"]] == file_ids, (
        f"the draft read's items {[item['id'] for item in document['items']]} do not "
        f"project the draft's questions {file_ids} — the read read a plural key the "
        "grammar never writes")
    assert answer["projected"]["items"] == len(file_ids), (
        f"the read's projected count is {answer['projected']['items']}, not the "
        f"{len(file_ids)} questions the draft carries")


def test_an_edit_round_trip_keeps_a_draft_with_a_grades_placeholder_parseable(
        served_authoring):
    """PR #794's finding 1: `render_draft`'s `[grades]` loop wrote a floor that was a
    sentinel string raw (`f"{_toml_key(name)} = {floor}"`), so a grades placeholder that
    round-tripped through a parse — a quoted string in the file, a string in the spec —
    re-rendered unquoted and the rewritten draft no longer parsed (observed: the next
    edit answers "The draft file could not be read: line N does not parse as a draft").
    The re-render keeps the sentinel quoted, with its reason comment above it
    (`FR-AUTHOR-11`), so the file survives the round-trip and the next one too."""
    port, _data_dir, path, package_id = _af02_draft(served_authoring)
    text = path.read_text(encoding="utf-8")
    # AF-10's partial-table shape, dropped into the recorded AF-02 draft: one grade's
    # boundary a per-grade sentinel with its reason comment above it — the state a draft
    # carrying a grades placeholder parses back to (`[grades]` is the draft's last table).
    grades_block = (
        "[grades]\n"
        "\n"
        "# PLACEHOLDER(the document names the grade but states no boundary for it): "
        "the minimum mark or percentage for grade A\n"
        'A = "<<PLACEHOLDER: grades A>>"\n'
    )
    path.write_text(re.sub(r"\[grades\]\n.*\Z", grades_block, text, flags=re.DOTALL),
                    encoding="utf-8")
    spec = tomllib.loads(path.read_text(encoding="utf-8"))
    qid = next(str(q["id"]) for q in spec["question"])

    answer = _action(port, "edit draft package", {
        "package_id": package_id, "operation": "edit question",
        "item_id": qid, "field": "text", "value": "Reworded: what does the data show?",
    })

    assert answer["refused"] is False, (
        f"the edit of a placeholder-carrying draft was refused: {answer['detail']!r}")
    rewritten = path.read_text(encoding="utf-8")
    parsed = tomllib.loads(rewritten)  # raises: unquoted sentinel text is not TOML
    assert parsed["grades"] == {"A": "<<PLACEHOLDER: grades A>>"}, (
        f"the re-render changed the grades table: {parsed['grades']!r}")
    lines = rewritten.splitlines()
    sentinel_at = next(index for index, line in enumerate(lines)
                       if "<<PLACEHOLDER: grades A>>" in line)
    assert lines[sentinel_at - 1].startswith("# PLACEHOLDER("), (
        f"the re-rendered sentinel carries no reason comment above it "
        f"(FR-AUTHOR-11): {lines[max(sentinel_at - 1, 0)]!r}")
