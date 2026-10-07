"""Creating a cohort with its consent class and roster, and reading one back (live-test blocker B3).

Before this, nothing an operator could run created a cohort: the only writers of a `cohort` row
were reference builders and test drivers, and nothing in `src/` wrote a roster row at all. Yet both
decide what a run may do. The consent class is what the consent gate reads before any work leaves
the machine (`FR-CONF-08`, read back by `Orchestrator.cohort_ref`, which this module sits beside),
and the roster is what intake's identity gate (V3, `FR-INGEST-39`) matches each paper's `Student:`
line against: each student's full name (required, `FR-INGEST-40`) and an optional ID
(`aeh.orch.roster_entries`).

Why here and not in `M-INGEST`: the `cohort` and `roster` tables are the store's base Tier C
schema, outside intake's declared write surface (`CT-INGEST-17`), and intake's entry points take no
path (`CT-INGEST-01`). The orchestrator already owns reading the cohort row for the consent gate.
Reading a roster FILE is the command line's job (`aeh.pipeline.rosters`); this module takes
`RosterEntry`s.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .roster_entries import (
    CheckedEntry,
    CohortSetupError,
    RosterEntry,
    check_roster,
    check_student_refs,
)
from .statements import ORCH_STATEMENTS

__all__ = ["CONSENT_CLASSES", "CohortSetupError", "CohortSummary", "RosterEntry",
           "add_to_roster", "check_cohort_id", "check_student_refs", "cohort_summary",
           "create_cohort"]

#: The cohort table's own CHECK set (`store/migrations.py`), named here so a refusal can list it.
CONSENT_CLASSES: tuple[str, ...] = ("synthetic", "consented", "real")


#: A cohort id becomes a file name (`cohorts/<id>.sqlite`) and the store does not check it. Lower
#: case only: on a case-insensitive file system (Windows, macOS) `Class-9A` and `class-9a` name
#: ONE file, so two cohorts, with different consent classes, would share a database.
_COHORT_ID = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,63}\Z")


#: Windows device names, which name a device rather than a file even with an extension.
_WINDOWS_RESERVED = re.compile(r"\A(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?\Z")


@dataclass(frozen=True)
class CohortSummary:
    """A cohort as stored: its id, consent class, when it was created, and its roster size."""

    cohort_id: str
    consent_class: str
    created_at: str
    roster_size: int


def check_cohort_id(cohort_id: Any) -> str:
    """The id, or `CohortSetupError` when it is not a safe, unambiguous file name."""
    if (not isinstance(cohort_id, str) or not _COHORT_ID.match(cohort_id)
            or cohort_id.endswith(".") or _WINDOWS_RESERVED.match(cohort_id)):
        raise CohortSetupError(
            f"cohort id {cohort_id!r} is not allowed: use 1 to 64 lower-case letters, digits, "
            f"'.', '_' or '-', starting with a letter or digit, not ending in '.', and not a "
            f"Windows device name such as 'con' or 'nul' (it becomes a file name). Nothing was "
            f"written.")
    return cohort_id


def cohort_summary(store: Any, cohort_id: str) -> CohortSummary | None:
    """The stored cohort, or None when none exists by that id. Opens no file that is not already
    there, so asking about a mistyped id creates nothing.

    A file that exists but holds a different cohort is refused: only a case-insensitive file
    system, or a hand-made file, gets there, and two cohorts in one file would share their
    students' data and be purged together."""
    check_cohort_id(cohort_id)
    if not Path(store.cohort_path(cohort_id)).exists():
        return None
    handle = store.cohort(cohort_id)
    held = [row["cohort_id"] for row in handle.query(ORCH_STATEMENTS["select_cohort_ids"])]
    if held and held != [cohort_id]:
        raise CohortSetupError(
            f"the file for cohort {cohort_id!r} holds cohort(s) {held}; refusing to share it. "
            f"Nothing was written.")
    rows = handle.query(ORCH_STATEMENTS["select_cohort_created"], cohort_id=cohort_id)
    if not rows:
        return None
    refs = handle.query(ORCH_STATEMENTS["select_roster_refs"], cohort_id=cohort_id)
    return CohortSummary(cohort_id=cohort_id, consent_class=str(rows[0]["consent_class"]),
                         created_at=str(rows[0]["created_at"]), roster_size=len(refs))


def create_cohort(store: Any, cohort_id: str, consent_class: str,
                  roster: Iterable[Any], created_at: str | None = None) -> CohortSummary:
    """Create a cohort with its consent class and roster, in one transaction.

    `roster` holds `RosterEntry`s (or mappings with `full_name` and an optional `student_ref`):
    every entry needs a name, and an IDs-only roster is refused (`FR-INGEST-40`); an entry with
    no ID gets a generated ref.

    `consent_class` has no default: it decides whether the cohort's work may be sent to a remote
    model (`FR-CONF-08`), and a default would decide that for the operator. An existing cohort is
    refused rather than overwritten, so its consent class can never be changed by re-running a
    command; `add_to_roster` adds students later. Every refusal writes nothing.
    """
    check_cohort_id(cohort_id)
    if consent_class not in CONSENT_CLASSES:
        raise CohortSetupError(
            f"consent class {consent_class!r} is not one of {', '.join(CONSENT_CLASSES)}. It is "
            f"required, with no default: 'synthetic' is made-up practice work, 'consented' "
            f"means the students or guardians agreed, 'real' is everything else. Nothing was "
            f"written.")
    entries = list(roster)
    if not entries:
        raise CohortSetupError(
            "the roster is empty: intake's identity check (V3) would park every paper. Nothing "
            "was written.")
    checked = check_roster(entries, cohort_id)
    if cohort_summary(store, cohort_id) is not None:
        raise CohortSetupError(_exists(cohort_id))
    stamp = created_at or datetime.now(timezone.utc).isoformat()
    try:
        with store.cohort(cohort_id).transaction() as tx:
            tx.execute(ORCH_STATEMENTS["insert_cohort"], cohort_id=cohort_id,
                       consent_class=consent_class, created_at=stamp)
            _insert_entries(tx, cohort_id, checked)
    except (sqlite3.IntegrityError, sqlite3.OperationalError) as error:
        # Two creates for one id at once: the loser fails on the cohort key, or inside the
        # store's first open of the new file. Either way the winner's cohort stands.
        raise CohortSetupError(
            f"{_exists(cohort_id)} (it was created at the same moment by another command: "
            f"{type(error).__name__})") from error
    return CohortSummary(cohort_id=cohort_id, consent_class=consent_class, created_at=stamp,
                         roster_size=len(checked))


def _insert_entries(tx: Any, cohort_id: str, entries: Iterable[CheckedEntry]) -> None:
    for entry in entries:
        tx.execute(ORCH_STATEMENTS["insert_roster_entry"], cohort_id=cohort_id,
                   student_ref=entry.student_ref, full_name=entry.full_name)


def _exists(cohort_id: str) -> str:
    return (f"cohort {cohort_id!r} already exists; it is never overwritten, so its consent class "
            f"stays as created. Use add-students to extend its roster. Nothing was written.")


def add_to_roster(store: Any, cohort_id: str, roster: Iterable[Any]) -> CohortSummary:
    """Add students to an existing cohort's roster, in one transaction. Every entry needs a name,
    as at creation. A supplied reference already on the roster is refused, naming it, so a re-run
    cannot pass silently. The consent class is untouched."""
    current = cohort_summary(store, cohort_id)
    if current is None:
        raise CohortSetupError(
            f"no cohort {cohort_id!r} exists; create it first. Nothing was written.")
    entries = list(roster)
    if not entries:
        raise CohortSetupError("no students were given. Nothing was written.")
    handle = store.cohort(cohort_id)
    present = {row["student_ref"] for row in handle.query(
        ORCH_STATEMENTS["select_roster_refs"], cohort_id=cohort_id)}
    checked = check_roster(entries, cohort_id, first_ordinal=current.roster_size + 1,
                           existing_refs=present)
    clash = sorted({entry.student_ref for entry in checked} & present)
    if clash:
        raise CohortSetupError(
            f"{len(clash)} reference(s) are already on the roster: {', '.join(clash[:10])}. "
            f"Nothing was written.")
    try:
        with handle.transaction() as tx:
            _insert_entries(tx, cohort_id, checked)
    except sqlite3.IntegrityError as error:
        raise CohortSetupError(
            "another command added some of these students at the same moment. Nothing was "
            "written; run 'show' and try again.") from error
    return CohortSummary(cohort_id=cohort_id, consent_class=current.consent_class,
                         created_at=current.created_at,
                         roster_size=current.roster_size + len(checked))
