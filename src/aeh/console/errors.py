"""The errors the console raises, and telling a schema fault from a busy database."""

from __future__ import annotations


#: What SQLite says when a query names something the store does not have. Matched on the
#: message because SQLite raises one exception type for "no such table" and for "database is
#: locked", and `FR-CONSOLE-37` treats those oppositely.
_SCHEMA_FAULTS: tuple[str, ...] = ("no such table", "no such column", "has no column named")


def _is_schema_fault(error: BaseException) -> bool:
    """Whether this `OperationalError` is the query's fault rather than the ledger's."""
    text = str(error).lower()
    return any(marker in text for marker in _SCHEMA_FAULTS)


class ConsoleReadError(RuntimeError):
    """A screen's read hit the SCHEMA and could not be answered (`FR-CONSOLE-37`).

    The distinction this type exists to make: a ledger that is missing, locked or corrupt is
    one ledger's bad luck and the page renders without it, counted. A table or column that is
    not there is the page asking the store for something the store has never had — and the old
    `except Exception: continue` turned that into an empty row list, which every caller
    downstream rendered as **zero**. A teacher reading "0 flagged" cannot tell it from "the
    query is wrong", and the second one is the case that shipped.

    Carries the query and the tier, because "the console could not read" is not actionable and
    "`SELECT ... FROM review_queue` against cohort `c-2026` names no such column" is."""

    def __init__(self, query: str, tier: str, cause: BaseException | None = None) -> None:
        self.query = str(query)
        self.tier = str(tier)
        super().__init__(
            f"this view could not be read: {self.query!r} against {self.tier} "
            f"failed on the schema ({cause})"
        )


class ConsoleBindRefused(Exception):
    """Starting the console was refused: the deployment profile forbids it, or the bind is
    not loopback (`FR-CONSOLE-05`). The refusal is in code because documentation would be
    read as a default — this is an unauthenticated student-record system, and the loopback
    bind is the only thing that makes the absence of accounts acceptable (R68, §3.19)."""


class _RefreshRequired(Exception):
    """Raised inside a real-store action when the owning module refused because the
    teacher's view is stale (`M-REVIEW`'s `StaleReviewItemError`, CT-REVIEW-15). `perform`
    turns it into `refused=True, refresh_required=True`: the §3.19 rule's refusal plus the
    refresh it owes, never a silent drop (`FR-CONSOLE-02`)."""


class ProvenanceRefused(Exception):
    """The export gate refused (`FR-CONSOLE-23` / R71): the package carries real student
    text, and the console will not emit it. Raised, not returned — an export that fails
    quietly is indistinguishable, from the teacher's side, from one that succeeded."""
