"""Tier D carries `student_ref` and refuses a student name.

Case `TC-STORE-12` (`FR-STORE-12`, P0, negative), test plan §5.3. Issue #14 (TS-08);
implemented by issue **#13**.

Rung 2 — the real Tier D file, because the second half of the case is a claim about the
*schema*, and a schema assertion against a double asserts the double.

This case guards **RISK-21** ("a student name lands in Tier D") at Critical/High. Tier D is
permanent and is the one tier `purge_cohort` does not touch: design §3.3's tier table marks it
"permanent / pseudonymized" while C+R are "per administration / heavy PII" and purgeable. A
name that reaches Tier D is therefore not a privacy bug that a later purge cleans up — it is
one that outlives every retention control the system has.

**Written ahead of implementation** (test plan §8.2). Registered under
`#13 StudentNameInTierDError`.
"""

from __future__ import annotations

import sqlite3

import pytest

from tests.support.store_api import open_store, statement, student_name_error
from tests.support.store_vocabulary import (
    TIER_D_IDENTITY_COLUMN,
    column_names,
    is_student_name_column,
    table_names,
)

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = "#13"

DURABLE_FILE = "durable.sqlite"

#: A Tier D table shaped the way `FR-STORE-12` requires: pseudonymous key, no name.
_AUDIT_DDL = (
    "CREATE TABLE audit_record ("
    "  id INTEGER PRIMARY KEY,"
    "  student_ref TEXT NOT NULL,"
    "  criterion_id TEXT NOT NULL,"
    "  decision TEXT NOT NULL"
    ")"
)
_AUDIT_INSERT = (
    "INSERT INTO audit_record (student_ref, criterion_id, decision) "
    "VALUES (:student_ref, :criterion_id, :decision)"
)
_AUDIT_READ = "SELECT student_ref FROM audit_record ORDER BY id"

#: The table limb 1 inserts into. Created **through an independent `sqlite3` connection**, not
#: through the store, and carrying every forbidden spelling as a real column.
#:
#: That indirection is the whole point. `FR-STORE-12` requires the *insert* to be rejected, so
#: the insert must be valid SQL — otherwise SQLite raises `OperationalError: table audit_record
#: has no column named student_name` and the case is broken in both directions at once. A
#: correct guard that runs after SQLite prepares the statement would red, because the schema
#: error arrives first; and a store with **no** name guard at all would pass, because SQLite's
#: own message contains the spelling the assertion looks for. Against a well-formed insert into
#: a table that really has the column, an unguarded store *succeeds* — which is the failure the
#: case needs to be able to see.
_POISONED_TABLE = "audit_with_names"
_POISONED_DDL = (
    f"CREATE TABLE {_POISONED_TABLE} ("
    "  id INTEGER PRIMARY KEY,"
    "  student_ref TEXT NOT NULL,"
    "  criterion_id TEXT NOT NULL,"
    "  decision TEXT NOT NULL,"
    "  student_name TEXT,"
    "  full_name TEXT,"
    "  surname TEXT,"
    "  pupil_forename TEXT"
    ")"
)

#: One literal per spelling, so a failure names the spelling that got through rather than
#: reporting that "an insert succeeded".
_NAME_BEARING_INSERTS = {
    spelling: (
        f"INSERT INTO {_POISONED_TABLE} (student_ref, criterion_id, decision, {spelling}) "
        f"VALUES (:student_ref, :criterion_id, :decision, :{spelling})"
    )
    for spelling in ("student_name", "full_name", "surname", "pupil_forename")
}

#: The control that tells a *guard* apart from a blanket wrapper. A store that simply re-raises
#: every Tier D `OperationalError` as `StudentNameInTierDError` passes limb 1 without inspecting
#: a single column name; this insert names a column that does not exist and is not a name, so it
#: must fail as something else.
_UNKNOWN_COLUMN_INSERT = (
    f"INSERT INTO {_POISONED_TABLE} (student_ref, criterion_label) "
    "VALUES (:student_ref, :criterion_label)"
)

#: The values each forbidden insert would carry. A real name, because the guard must key on the
#: *column*, not on anything about the value — `FR-STORE-12` says "a column mapped as a
#: student-name field".
_NAME_VALUES = {
    "student_name": "Amara Okonkwo",
    "full_name": "Amara Okonkwo",
    "surname": "Okonkwo",
    "pupil_forename": "Amara",
}


def test_tc_store_12_tier_d_rejects_a_student_name_column_and_accepts_student_ref(
    tmp_data_dir,
):
    """`TC-STORE-12` — *"The name-bearing insert is rejected; the `student_ref` insert succeeds;
    Tier D's schema contains no name-mapped column."*

    Oracle: **exact rejection plus schema assertion**.

    Three limbs, and the middle one is the one a naive implementation fails.

    **Rejected**, on an **insert**, with an exact exception. The requirement is precise about
    the operation — "shall reject any *insert* containing a column mapped as a student-name
    field" — so the case attempts inserts, not `CREATE TABLE`s. A schema guard is a different
    (and weaker) promise, and an implementation that did exactly what `FR-STORE-12` says while
    permitting the DDL would fail a case written the other way round.

    The exception is exact. `FR-STORE-12` requires the refusal but names no error, so this case
    pins one (`StudentNameInTierDError`) rather than accepting "something raised" — a
    `sqlite3.OperationalError` from a typo'd column would satisfy a bare `pytest.raises(
    Exception)` and tell us nothing about whether the guard exists at all. The design gap is
    reported in the PR.

    **Accepted.** A store that rejects *every* Tier D insert also rejects every name-bearing
    one. Without this limb the case is passed by a broken store, which is the standard failure
    of a negative-only test. `student_ref` is the pseudonymous key `CT-STORE-09` promises
    consumers ("a caller may rely on Tier D being pseudonymized"), so the accepted insert is
    also read back to prove it actually landed.

    **The schema itself.** Rejecting inserts is a runtime guard; a name-mapped *column* in the
    Tier D schema means some path already created one, and a guard on one write path is not a
    guarantee. Swept over every table and every column in the real file.

    The sweep is over four spellings because the requirement names a *concept* — "a column
    mapped as a student-name field" — and a guard matched against the single literal
    `student_name` is one `full_name` away from useless.
    """
    store = open_store(tmp_data_dir, issue=ISSUE)
    durable = store.durable()
    StudentNameInTierD = student_name_error(issue=ISSUE)

    with durable.transaction() as tx:
        tx.execute(statement(_AUDIT_DDL, issue=ISSUE))

    # --- limb 1: every name-bearing *insert* is refused, by the exact error ------------------
    #
    # The table is created outside the store so that no DDL guard can pre-empt the case: the
    # question is what happens to the *insert*.
    durable_path = tmp_data_dir / DURABLE_FILE
    with sqlite3.connect(durable_path) as raw:
        raw.execute(_POISONED_DDL)

    for spelling, sql in sorted(_NAME_BEARING_INSERTS.items()):
        params = {
            "student_ref": "ref-00417",
            "criterion_id": "CRIT-1",
            "decision": "agree",
            spelling: _NAME_VALUES[spelling],
        }
        with pytest.raises(StudentNameInTierD) as raised:
            with durable.transaction() as tx:
                tx.execute(statement(sql, issue=ISSUE), **params)
        assert spelling in str(raised.value), (
            f"TC-STORE-12: Tier D refused the {spelling!r} column but the error does not name "
            f"it: {raised.value!r}. An operator who cannot see which column was rejected cannot "
            "fix the caller."
        )

    # The control: an unknown, innocuous column must fail as something *other* than the name
    # guard. Without it, a store that wraps every Tier D error in StudentNameInTierDError passes
    # every assertion above while inspecting no column names at all.
    with pytest.raises(Exception) as unrelated:
        with durable.transaction() as tx:
            tx.execute(
                statement(_UNKNOWN_COLUMN_INSERT, issue=ISSUE),
                student_ref="ref-00418",
                criterion_label="legible",
            )
    assert not isinstance(unrelated.value, StudentNameInTierD), (
        "TC-STORE-12: an insert naming `criterion_label` — a column that does not exist and is "
        f"not a name — was rejected as a student-name violation: {unrelated.value!r}. That is a "
        "blanket wrapper around Tier D errors, not the FR-STORE-12 guard, and it would report "
        "every schema typo as a privacy incident while catching no actual name."
    )

    # --- limb 2: the pseudonymous shape is accepted, and actually lands ---------------------
    with durable.transaction() as tx:
        tx.execute(
            statement(_AUDIT_INSERT, issue=ISSUE),
            student_ref="ref-00417",
            criterion_id="CRIT-3",
            decision="agree",
        )

    rows = [row[0] for row in durable.query(statement(_AUDIT_READ, issue=ISSUE))]
    assert rows == ["ref-00417"], (
        "TC-STORE-12: the student_ref insert did not land. FR-STORE-12 requires Tier D rows to "
        "*carry* student_ref, not merely to reject names — a store that refuses every insert "
        f"passes the negative limb and is useless. Got {rows!r}."
    )

    # --- limb 3: the schema, swept ------------------------------------------------------------
    #
    # `_POISONED_TABLE` is excluded by name: this case created it itself, behind the store's
    # back, precisely so limb 1 had a valid insert to make. Sweeping it would be asserting on
    # the test's own fixture. Everything the *store* created is in scope.
    offenders: list[str] = []
    inspected = 0
    for table in sorted(table_names(durable_path)):
        if table.startswith("sqlite_") or table == _POISONED_TABLE:
            continue
        for column in column_names(durable_path, table):
            inspected += 1
            if is_student_name_column(column):
                offenders.append(f"{table}.{column}")

    assert inspected, (
        "TC-STORE-12: the sweep inspected no columns at all, so it would pass against an empty "
        "Tier D. The audit_record table created above must be present for this limb to mean "
        "anything."
    )
    assert not offenders, (
        f"TC-STORE-12: Tier D's schema declares a student-name column ({', '.join(offenders)}). "
        "Design §3.3 puts the identity mapping in Tier C alone, and Tier D is the tier "
        "purge_cohort does not touch — a name here outlives every retention control in the "
        "system (RISK-21)."
    )

    columns_of_audit = column_names(durable_path, "audit_record")
    assert TIER_D_IDENTITY_COLUMN in columns_of_audit, (
        f"TC-STORE-12: audit_record has no {TIER_D_IDENTITY_COLUMN!r} column. The clause has "
        "two halves — reject the name *and* carry the pseudonymous key — and a Tier D that "
        f"carries neither is not pseudonymized, it is anonymous. Columns: {columns_of_audit}"
    )
