"""Closed vocabularies for the `M-STORE` cases of TS-08 (issue #14).

Three lists that several cases share, kept here rather than duplicated per file so a term
added in one place is asserted everywhere it matters — the same reason `console_vocabulary`
and `stats_vocabulary` exist.

Search-surface names are **not** here: `tests.support.sql_scan.is_search_name` already owns
that vocabulary and `SEC-15` asserts against it. `TC-STORE-15` reuses it rather than growing a
second list that could drift from the first.

**The FR-STORE-12 name rule moved to `aeh.store` when #13 landed.** It is runtime behaviour
now — the Tier D write guard executes it on every insert — so the canonical rule, its token
sets and its rationale live in `src/aeh/store.py`, and this module re-exports them. A rule
asserted from one copy and enforced from another is two rules waiting to disagree; importing
the store's own rule here is what keeps the sweep (`TC-STORE-12`'s third limb) asserting the
same mapping the guard applies. `NON_STUDENT_NAME_COLUMNS` stays here: it is the negative
control set for `tests/unit/harness/test_store_vocabulary.py`, a test-side concern.
"""

from __future__ import annotations

import re
from pathlib import Path
import sqlite3

from aeh.store import (
    BARE_NAME_COLUMNS,
    NAME_TOKENS,
    PERSON_TOKENS,
    PSEUDONYM_TOKENS,
    STRONG_NAME_TOKENS,
    TIER_D_IDENTITY_COLUMN,
    WEAK_NAME_TOKENS,
    is_student_name_column,
)

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
        # Longitudinal per-student columns — the reason Tier D exists. Every one of these was
        # flagged by the person+name rule before `NAME_TOKENS` was split into strong and weak,
        # and none of the 33 entries above has this shape: they were all written against the
        # *previous* rule's failure mode, so 57 green controls said nothing about this one. A
        # control set that does not cover its rule's own risk surface is decoration.
        "student_first_seen", "student_last_seen_at", "learner_last_active",
        "candidate_last_attempt", "student_family_income", "student_family_size",
        "student_display_order", "pupil_last_updated", "student_middle_school",
        "learner_given_consent", "student_preferred_language", "candidate_first_language",
    }
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
