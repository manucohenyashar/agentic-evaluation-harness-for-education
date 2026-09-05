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
# **Not a `*_name` rule.** The obvious version — flag any column whose name contains `name` —
# was measured against this module and flagged `criterion_name`, `stat_name`, `scope_name`,
# `run_name`, `metric_name`, `display_name` and nine more. Tier D holds `criterion_stats`,
# `mcq_item_stats` and `run_metrics` (design §3.3), so those are not hypothetical columns: that
# rule reds the build against a *correct* store, and a rule that does that is one the first
# `M-STORE` commit switches off. A switched-off rule catches nothing at all, which is strictly
# worse than the leak it was guarding.
#
# So the rule is **person + name**, not name alone: a column is a student-name column when it
# names a *person* and names their *name*. Two token sets, and the intersection is the finding.

#: Who the column is about. Absent these, `*_name` is a criterion, a run or a metric.
PERSON_TOKENS: frozenset[str] = frozenset({"student", "pupil", "learner", "candidate", "child"})

#: What about them. `first`/`last`/`middle`/`preferred` are here without `name` because
#: `student_first` is exactly as identifying as `student_first_name`.
NAME_TOKENS: frozenset[str] = frozenset(
    {
        "name", "names", "fullname", "firstname", "lastname", "surname", "forename",
        "givenname", "familyname", "initials", "first", "last", "given", "family",
        "middle", "preferred", "display",
    }
)

#: The pseudonymous shape `FR-STORE-12` *requires*. A person token with one of these is the
#: sanctioned Tier D column, not a violation — `student_ref` is the whole point of the clause,
#: and a rule that flagged it would flag the correct implementation.
PSEUDONYM_TOKENS: frozenset[str] = frozenset(
    {"ref", "id", "key", "uuid", "hash", "token", "code", "pseudonym", "anon"}
)

#: Spellings that identify a person with no person token attached, so the person+name rule
#: cannot see them. A bare `name` column in a Tier D table is a finding on its own.
BARE_NAME_COLUMNS: frozenset[str] = frozenset(
    {
        "name", "names", "full_name", "fullname", "first_name", "firstname", "last_name",
        "lastname", "surname", "forename", "given_name", "givenname", "family_name",
        "familyname", "middle_name", "preferred_name", "legal_name", "maiden_name",
    }
)

#: The pseudonymous key Tier D is allowed to carry instead (`FR-STORE-12`).
TIER_D_IDENTITY_COLUMN = "student_ref"

#: Legitimate columns that a careless rule flags. Not used by `is_student_name_column` — it is
#: the **negative control set** for `tests/unit/harness/test_store_vocabulary.py`, which is what
#: keeps the false-positive half of this rule honest. Every entry was produced by measuring an
#: earlier draft of the rule against plausible Tier D columns.
NON_STUDENT_NAME_COLUMNS: frozenset[str] = frozenset(
    {
        "criterion_name", "package_name", "run_name", "cohort_name", "school_name",
        "model_name", "policy_name", "table_name", "column_name", "file_name",
        "label_name", "band_name", "rubric_name", "question_name", "metric_name",
        "stat_name", "scope_name", "stage_name", "backend_name", "signal_name",
        "event_name", "constraint_name", "field_name", "dataset_name", "population_name",
        "display_name", "name_hash", "renamed_at", "nametag",
        # The pseudonymous shapes the clause *requires*, which an over-eager rule flags.
        "student_ref", "pupil_id", "learner_ref", "candidate_code", "student_uuid",
    }
)


def is_student_name_column(column: str) -> bool:
    """Does this column name a student's name?

    `person token AND name token`, with a pseudonym token vetoing the match. See the block
    comment above for why this is not a `*_name` rule.

    Known limit, stated rather than hidden: an unsegmented abbreviation like `sname` or `fname`
    matches nothing here. Catching those needs guessing at abbreviations, and every guess is a
    false positive against some legitimate column. `TC-STORE-12`'s third limb is a sweep over a
    real schema, so the residual risk is a column somebody deliberately obfuscated — which is a
    different threat from the one `FR-STORE-12` describes.
    """
    lowered = column.lower().strip()
    words = set(re.split(r"[_\s-]+", lowered))

    if lowered in BARE_NAME_COLUMNS:
        return True

    if words & PERSON_TOKENS:
        # `student_ref`, `pupil_id`, `learner_uuid` — the shape the clause requires.
        if words & PSEUDONYM_TOKENS:
            return False
        if words & NAME_TOKENS:
            return True

    # `studentname`, `pupilForename` — a person and a name glued into one token.
    return bool(
        re.search(r"(student|pupil|learner|candidate|child)\w*(name|forename|surname)", lowered)
    )


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
