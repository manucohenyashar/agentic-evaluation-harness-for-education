"""A module that assembles SQL every way `sql_scan` is meant to catch. Never imported.

The positive control for `SEC-15`'s source-level half, and it is not decoration. `src/` contains
`aeh.conf` and `aeh.prov` today and neither issues a single SQL statement, so "zero assembled-SQL
sites in the source tree" is true of the tree, true of a scanner that returns `[]` unconditionally,
and true of a scanner with a typo in every pattern. The three claims are indistinguishable without
a file that *should* be flagged.

Lives in `tests/support/` rather than `src/` deliberately — `sql_scan.scan_tree` walks `src/` and
`harness/` (`import_graph.SOURCE_ROOTS`), so a control placed there would fail the very assertion
it exists to support. The control test points the scanner at this file directly.

`# noqa` throughout: every line here is a defect on purpose.
"""

from __future__ import annotations

import sqlite3


def by_name(connection: sqlite3.Connection, name: str):
    """f-string interpolation — the commonest form, and the one a line scan can still see."""
    return connection.execute(f"SELECT * FROM roster WHERE display_name = '{name}'")  # noqa


def by_cohort(connection: sqlite3.Connection, cohort_id: str):
    """Concatenation — invisible to a scan that only looks for f-strings."""
    return connection.execute("SELECT * FROM submission WHERE cohort_id = '" + cohort_id + "'")  # noqa


def by_status(connection: sqlite3.Connection, status: str):
    """Percent formatting, the oldest form and still what a copied snippet uses."""
    return connection.execute("SELECT id FROM work_unit WHERE status = '%s'" % status)  # noqa


def ordered_by(connection: sqlite3.Connection, column: str):
    """`.format()` — and an ORDER BY, which cannot be parameterized at all in SQLite, so it is
    the clause where an author most often gives up and interpolates."""
    return connection.execute("SELECT id FROM verdict ORDER BY {} LIMIT 10".format(column))  # noqa


def migrate(connection: sqlite3.Connection, schema: str):
    """`executescript` accepts no parameters, so every value in it is interpolated by
    construction — flagged whether or not the text is a literal."""
    return connection.executescript(schema)  # noqa


def split_across_lines(connection: sqlite3.Connection, table: str):
    """Assembled in a chain, so no single line reads as SQL. This is the one a grep misses and
    the reason `sql_scan` parses."""
    head = "SELECT * "
    body = "FROM " + table + " "
    tail = "WHERE 1 = 1"
    return connection.execute(head + body + tail)  # noqa
