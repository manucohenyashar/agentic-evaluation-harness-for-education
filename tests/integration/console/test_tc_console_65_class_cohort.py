"""`TC-CONSOLE-65` (issue #771, FR-CONSOLE-53/54/63) — the class and cohort actions, and
the roster preview that fronts the import.

| Arm | Expected |
|---|---|
| (a) `create class` from a pasted 3-student list | the outcome names the class, its consent class and its size, and the class ledger's roster rows exist — the store digest moved, and the ledger reads as the rows `aeh cohort create` writes |
| (b) `create cohort from class`, twice | each copy carries the class's roster and consent class; the class is only read — unchanged after both copies, and the second copy is allowed (a class may seed many cohorts, `ADR-48`) |
| (c) the roster preview, then the import | the preview lists every malformed row with its line number and reason and writes nothing (digest unchanged); the import of the same content refuses naming the same rows; a clean file imports |

**Isolation: rung 3 (E1)** — a real store, a real console on a real loopback socket; the
actions run over the console's own control surface, the ledger rows are read back through
the store's own cohort handle.
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
    _post_json,
    served_console,
)
from tests.support.spa import store_digest

pytestmark = pytest.mark.integration

#: The pasted 3-student list arm (a) creates the class from: first, last and student ID,
#: tab-separated — the roster editor's paste shape.
PASTE = "Amara\tOkafor\tS-01\nBen\tIto\tS-02\nCleo\tNdiaye\tS-03"

#: The roster file arm (c) previews and imports: a valid row, a nameless row and a
#: duplicated student ID — the two problem classes the parser collects in one pass.
MALFORMED_ROSTER = (
    "full_name,student_ref\n"
    "Amara Okafor,S-01\n"
    ",S-02\n"
    "Ben Ito,S-01\n"
)

CLEAN_ROSTER = (
    "full_name,student_ref\n"
    "Amara Okafor,S-01\n"
    "Ben Ito,S-02\n"
)


def _roster_rows(store, cohort_id: str) -> list[tuple[str, str]]:
    """A ledger's roster rows, in insertion order, as `(student_ref, full_name)` pairs —
    read through the store's own cohort handle."""
    rows = store.cohort(cohort_id).query(
        "SELECT student_ref, full_name FROM roster ORDER BY rowid")
    return [(str(row["student_ref"]), str(row["full_name"])) for row in rows]


def _consent_class(store, cohort_id: str) -> str:
    """A ledger's consent class, read from its cohort row — the copy's consent is
    asserted from the store, not from the outcome's echo of the request."""
    rows = store.cohort(cohort_id).query(
        "SELECT consent_class FROM cohort WHERE cohort_id = :c", c=cohort_id)
    assert len(rows) == 1, f"cohort {cohort_id} has {len(rows)} cohort row(s)"
    return str(rows[0]["consent_class"])


def test_tc_console_65a_creating_a_class_from_a_paste_writes_the_roster_rows(
        served_console):
    """`create class` from a pasted list: the outcome names the class, its consent class
    and its size, and the class ledger's roster rows exist — the digest moved."""
    _server, port, store, data_dir = served_console
    before = store_digest(data_dir)

    answer = _action(port, "create class", {
        "class_id": "cl-a", "consent_class": "synthetic", "paste": PASTE,
    })

    assert answer["refused"] is False, answer["detail"]
    assert answer["dispatched"] is True
    assert answer["detail"] == (
        "class cl-a created (synthetic) with 3 student(s) through M-ORCH's "
        "create_cohort — the rows `aeh cohort create` writes. Next: make a grading "
        "cohort out of it, or add more students to it.")
    assert _roster_rows(store, "cl-a") == [
        ("S-01", "Amara Okafor"), ("S-02", "Ben Ito"), ("S-03", "Cleo Ndiaye"),
    ]
    assert store_digest(data_dir) != before, (
        "the class's ledger rows are what the store digest exists to see; a class "
        "created without a store row would leave the digest standing")

    context = _get_json(port, "/api/v1/context")
    classes = [row for row in context["classes"] if row["cohort_id"] == "cl-a"]
    assert len(classes) == 1 and classes[0]["state"] == "roster_only", (
        f"the created class reads as {classes!r}; a roster-only ledger is a class "
        "(ADR-48)")


def test_tc_console_65b_a_class_seeds_two_cohorts_and_stays_intact(served_console):
    """`create cohort from class` twice: each new cohort carries the class's roster and
    consent class; the class is unchanged after both, and the second copy is allowed."""
    _server, port, store, _data_dir = served_console
    _action(port, "create class", {
        "class_id": "cl-a", "consent_class": "synthetic", "paste": PASTE,
    })
    class_roster = _roster_rows(store, "cl-a")

    first = _action(port, "create cohort from class",
                    {"class_id": "cl-a", "cohort_id": "co-a"})

    assert first["refused"] is False, first["detail"]
    assert first["detail"] == (
        "class cl-a's roster copied into cohort co-a (synthetic) with 3 student(s) "
        "through M-ORCH's create_cohort; the class is unchanged and can seed more "
        "cohorts")
    assert _roster_rows(store, "co-a") == class_roster
    assert _consent_class(store, "co-a") == "synthetic", (
        "the copy's consent class is copied from the class, not just echoed in the "
        "outcome's message")

    second = _action(port, "create cohort from class",
                     {"class_id": "cl-a", "cohort_id": "co-b"})

    assert second["refused"] is False, second["detail"]
    assert "cohort co-b (synthetic) with 3 student(s)" in second["detail"], (
        f"the second copy's outcome does not name the new cohort: "
        f"{second['detail']!r}")
    assert _roster_rows(store, "co-b") == class_roster
    assert _consent_class(store, "co-b") == "synthetic"
    assert _consent_class(store, "cl-a") == "synthetic", (
        "the class's own consent class is unchanged by the copies")
    assert _roster_rows(store, "cl-a") == class_roster, (
        "the class is only read; copying a cohort out of it must not change its roster")


def test_tc_console_65c_the_preview_lists_every_malformed_row_and_the_import_refuses_them(
        served_console):
    """The roster preview parses the file and lists every malformed row with its line
    number and reason, writes nothing (digest unchanged); the import of the same content
    refuses naming the same rows; a clean file imports."""
    _server, port, store, data_dir = served_console
    before = store_digest(data_dir)

    status, preview = _post_json(port, "/api/v1/roster/preview",
                                 {"content": MALFORMED_ROSTER, "name": "roster.csv"})
    assert status == 200
    assert preview["name"] == "roster.csv"
    assert preview["format"] == "csv"
    assert preview["format_label"] == "a table with a header row"
    assert preview["rows"] == [
        {"line": 2, "full_name": "Amara Okafor", "student_ref": "S-01"}]
    problems = preview["problems"]
    assert [problem["line"] for problem in problems] == [3, 4], (
        f"the preview listed {problems!r}; every malformed row is listed, not the "
        "first one")
    assert "Row 3 has no name" in problems[0]["reason"]
    assert "Row 4's student ID 'S-01' is already on row 2" in problems[1]["reason"], (
        f"the duplicated reference is not named with both rows: "
        f"{problems[1]['reason']!r}")
    assert preview["counts"] == {"students": 1, "problems": 2}
    assert preview["ready"] is False
    assert store_digest(data_dir) == before, (
        "the preview writes nothing anywhere — no blob, no store row")

    imported = _action(port, "import roster file", {
        "class_id": "cl-imp", "consent_class": "synthetic",
        "content": MALFORMED_ROSTER, "name": "roster.csv",
    })
    # A class-vocabulary refusal is a refusal: `refused=True` with the refused detail and
    # its next action, consistent with the authoring actions' outcomes (PR #794's
    # finding 3 — the shipped shape kept the flag False and signalled only through
    # `dispatched=False` plus the "… refused: …" detail prefix; fixed in the follow-up).
    assert imported["refused"] is True, imported["detail"]
    assert imported["dispatched"] is False, imported["detail"]
    assert imported["detail"].startswith("import roster file refused:")
    assert "the roster file still has 2 problem row(s)" in imported["detail"], (
        f"the import accepted what the preview refused: {imported['detail']!r}")
    assert "Nothing was written." in imported["detail"]
    assert store_digest(data_dir) == before, "a refused import wrote to the store"

    committed = _action(port, "import roster file", {
        "class_id": "cl-imp", "consent_class": "synthetic",
        "content": CLEAN_ROSTER, "name": "roster.csv",
    })
    assert committed["refused"] is False, committed["detail"]
    assert committed["detail"] == (
        "class cl-imp created (roster.csv, synthetic) with 2 student(s) through "
        "M-ORCH's create_cohort — the rows `aeh cohort create` writes. Next: make a "
        "grading cohort out of it.")
    assert _roster_rows(store, "cl-imp") == [("S-01", "Amara Okafor"),
                                             ("S-02", "Ben Ito")]
    assert store_digest(data_dir) != before
