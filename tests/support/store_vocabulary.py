"""Closed vocabularies for the `M-STORE` cases of TS-08 (issue #14).

Three lists that several cases share, kept here rather than duplicated per file so a term
added in one place is asserted everywhere it matters — the same reason `console_vocabulary`
and `stats_vocabulary` exist.

Search-surface names are **not** here: `tests.support.sql_scan.is_search_name` already owns
that vocabulary and `SEC-15` asserts against it. `TC-STORE-15` reuses it rather than growing a
second list that could drift from the first.
"""

from __future__ import annotations

import re
from pathlib import Path
import sqlite3

# --- FR-STORE-12: what a "column mapped as a student-name field" looks like -----------------
#
# `FR-STORE-12` says Tier D "shall reject any insert containing a column mapped as a
# student-name field", and design §3.3 puts the identity mapping in Tier C alone. The
# requirement names the *concept*, not the spellings, so the case needs a list — and a list is
# only as good as its worst omission, since a name-bearing column that no pattern matches is
# precisely the leak `CT-STORE-09` promises callers cannot happen.
#
# Matched as whole `_`-separated words against the column name, so `student_name` and
# `name_of_student` match while `nametag` and `renamed_at` do not.
STUDENT_NAME_COLUMN_STEMS: frozenset[str] = frozenset(
    {
        "name", "names", "fullname", "firstname", "lastname", "surname",
        "forename", "givenname", "familyname", "pupil", "learner",
    }
)

#: The pseudonymous key Tier D is allowed to carry instead (`FR-STORE-12`).
TIER_D_IDENTITY_COLUMN = "student_ref"

#: Columns that contain the word "name" but are not a *student* name, so a blanket "no column
#: containing `name`" rule would red the build on the first ordinary Tier D table. Each is a
#: name the design's own §3.3 Tier D table list implies — a criterion, a package, a run.
NON_STUDENT_NAME_COLUMNS: frozenset[str] = frozenset(
    {
        "criterion_name", "package_name", "run_name", "cohort_name", "school_name",
        "model_name", "policy_name", "table_name", "column_name", "file_name",
        "label_name", "band_name", "rubric_name", "question_name", "metric_name",
    }
)


def is_student_name_column(column: str) -> bool:
    """Does this column name a student's name?

    Whole-word stem matching over the `_`-separated parts, with `NON_STUDENT_NAME_COLUMNS`
    taking precedence — the false-positive half matters as much as the true-positive half.
    A rule that flags `criterion_name` is one the first `M-STORE` commit switches off, and a
    switched-off rule catches nothing at all.
    """
    lowered = column.lower().strip()
    if lowered in NON_STUDENT_NAME_COLUMNS:
        return False
    words = set(re.split(r"[_\s-]+", lowered))
    if words & STUDENT_NAME_COLUMN_STEMS:
        return True
    # `studentname`, `student_full_name`, `pupilName` after normalization.
    return bool(re.search(r"(student|pupil|learner|candidate)\w*(name|forename|surname)", lowered))


# --- design §3.3 Observability / CT-STORE-17: the five signals ------------------------------
#
# Design §3.3 names the signals in prose — *"Write-queue depth, batch commit latency, database
# file sizes, free disk space, and `VACUUM` duration"* — and `CT-STORE-17` makes them contract:
# *"Emits ... under those names"*. Prose does not fix a spelling, so `TC-STORE-24` pins one
# here and the PR reports the gap: a clause that says "under those names" without naming them
# is not assertable, and an unassertable clause is the one a consumer discovers is broken.
#
# Each entry maps the design's prose to the key the case requires, so a rename is a diff a
# reader can argue with rather than a silent redefinition.
STORE_SIGNALS: dict[str, str] = {
    "write_queue_depth": "Write-queue depth",
    "batch_commit_latency_ms": "batch commit latency",
    "database_file_bytes": "database file sizes (per tier)",
    "free_disk_bytes": "free disk space",
    "vacuum_duration_ms": "`VACUUM` duration",
}

#: `CT-STORE-17`: *"Free-disk and queue-depth are alert inputs and their semantics are
#: contract."* The two alerts design §3.3 names under **Alerts**.
STORE_ALERTS: frozenset[str] = frozenset({"free_disk_below_projection", "queue_depth_sustained"})


# --- shared schema helpers -------------------------------------------------------------------


def table_names(db_path: Path) -> set[str]:
    """Every table in a SQLite file, read through an independent connection.

    Independent on purpose: a case that asks the module under test what its own schema contains
    is asking the defect to report itself.
    """
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {row[0] for row in rows}


def column_names(db_path: Path, table: str) -> list[str]:
    """The columns of one table, in declaration order."""
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return [row[1] for row in rows]


def virtual_table_definitions(db_path: Path) -> dict[str, str]:
    """Every `CREATE VIRTUAL TABLE` in a file, by name.

    `TC-STORE-15`'s schema half. An FTS index is the one way to add full-text search to SQLite
    without adding a method anybody would call `search`, so the surface sweep alone cannot see
    it — which is why the plan names the schema separately from the API.
    """
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL"
        ).fetchall()
    return {
        name: sql for name, sql in rows
        if re.search(r"\bcreate\s+virtual\s+table\b", sql, re.IGNORECASE)
    }


def journal_mode(db_path: Path) -> str:
    """`PRAGMA journal_mode` as the file itself reports it.

    WAL is persisted in the database header, so an independent read-only connection is a real
    oracle for `FR-STORE-01` rather than a re-ask of the module.
    """
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        return str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
