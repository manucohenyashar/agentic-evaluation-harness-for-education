"""`Tx`: the handle a transaction body writes through."""

from __future__ import annotations

import sqlite3
from typing import Any, Callable, Sequence

from .interfaces import Row, Statement
from .connection import _run


class Tx:
    """The handle a `transaction()` body writes through (CT-STORE-03).

    Section 3.3's Interfaces block types `transaction()` as `ContextManager[Tx]` and never
    defines `Tx`, so its one method is this module's. `execute(statement, **params)` mirrors
    `query` deliberately: same declared-`Statement` argument, same keyword parameters, so a
    caller moving a read into a transaction changes the method name and nothing else.

    **No `commit` and no `rollback`.** The context manager owns both -- commit on a clean exit,
    rollback on any exception -- because `CT-STORE-03`'s promise is "atomic and synchronous over
    its whole body", and a body that could commit halfway through would make "both present or
    both absent" a convention rather than a guarantee. `FUZZ-07` is the case that notices:
    review proved its atomicity property vacuous against a `transaction()` that was a bare
    `yield`, and a `Tx` exposing `commit()` is the same hole one level up.
    """

    __slots__ = ("_connection", "_guard", "_retries")

    def __init__(self, connection: sqlite3.Connection, retries: int,
                 guard: Callable[[Statement], None] | None = None) -> None:
        self._connection = connection
        self._retries = retries
        # The tier write guard, if this handle has one (`_reject_tier_d_student_name_insert`
        # on Tier D, `None` elsewhere). Set before the first `execute`, because a guard that
        # only applied from the second statement on would let the first one through.
        self._guard = guard

    def execute(self, statement: Statement, **params: Any) -> Sequence[Row]:
        """Run one declared statement inside the open transaction.

        Reads are allowed as well as writes -- `_refuse_write` guards `query`, not this --
        because a transaction that could not read cannot do the read-modify-write every ledger
        transition is. The rows come back for the same reason `query` returns them.

        The tier write guard runs **before** the statement reaches SQLite: `FR-STORE-12`'s
        rejection is of the insert itself, so a name-bearing statement must fail before it
        writes, not after — and a guard that ran after a successful execute would have
        already landed the row it is refusing.
        """
        declared = statement if isinstance(statement, Statement) else Statement(statement)
        if self._guard is not None:
            self._guard(declared)
        return _run(self._connection, declared, params, retries=self._retries).fetchall()
