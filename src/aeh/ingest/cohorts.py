"""Creating a cohort with its consent class and roster, and reading one back (live-test blocker B3).

Before this, nothing an operator could run created a cohort: the only writers of a `cohort` row
were reference builders and test drivers, and nothing in `src/` wrote a roster row at all. Yet
both decide what a run may do. The consent class is what the consent gate reads before any work
leaves the machine (`FR-CONF-08`, read back by `Orchestrator.cohort_ref`), and the roster is what
intake's identity gate (V3) matches each paper's `Student:` line against, exactly.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .errors import IngestError
from .schema import INGEST_STATEMENTS

#: The cohort table's own CHECK set (`store/migrations.py`). Named here so a refusal can list it
#: before the database does, in words an operator can act on.
CONSENT_CLASSES: tuple[str, ...] = ("synthetic", "consented", "real")


#: A cohort id becomes a file name (`cohorts/<id>.sqlite`) and the store does not check it, so
#: this is the one place that keeps `../x` or `a/b` from naming a file outside the cohort folder.
_COHORT_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


#: A student reference is matched exactly against the `Student:` line a paper carries, so it may
#: not hold whitespace a reader would never transcribe the same way twice.
_STUDENT_REF = re.compile(r"\A\S{1,128}\Z")


class CohortSetupError(IngestError):
    """A cohort could not be created or extended as asked. Nothing was written."""


@dataclass(frozen=True)
class CohortSummary:
    """A cohort as stored: its id, consent class, when it was created, and its roster size."""

    cohort_id: str
    consent_class: str
    created_at: str
    roster_size: int


def read_roster_file(path: str | Path) -> tuple[str, ...]:
    """The student references in a roster file, in file order.

    One reference per line, or a CSV. When the first row has a `student_ref` column, that column
    is read; otherwise the first column of every row. Blank lines and lines starting with `#` are
    skipped, and surrounding spaces are stripped. A UTF-8 byte-order mark (what Excel on Windows
    writes) is removed. Validation is `create_cohort`'s, so a file and a list are held to one rule.
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    rows = [row for row in csv.reader(io.StringIO(text))
            if row and row[0].strip() and not row[0].strip().startswith("#")]
    if not rows:
        return ()
    header = [cell.strip().lower() for cell in rows[0]]
    if "student_ref" in header:
        column = header.index("student_ref")
        return tuple(row[column].strip() for row in rows[1:]
                     if len(row) > column and row[column].strip())
    return tuple(row[0].strip() for row in rows)


def _checked_refs(student_refs: Iterable[str]) -> tuple[str, ...]:
    refs = tuple(str(ref).strip() for ref in student_refs)
    bad = [ref for ref in refs if not _STUDENT_REF.match(ref)]
    if bad:
        raise CohortSetupError(
            f"{len(bad)} student reference(s) are empty, longer than 128 characters or contain "
            f"spaces; a reference must match the 'Student:' line on the paper exactly. Nothing "
            f"was written.")
    seen: set[str] = set()
    repeated = sorted({ref for ref in refs if ref in seen or seen.add(ref)})
    if repeated:
        raise CohortSetupError(
            f"the roster lists {len(repeated)} reference(s) more than once: "
            f"{', '.join(repeated[:10])}. Nothing was written.")
    return refs


def _check_cohort_id(cohort_id: str) -> str:
    if not isinstance(cohort_id, str) or not _COHORT_ID.match(cohort_id) or cohort_id.endswith("."):
        raise CohortSetupError(
            f"cohort id {cohort_id!r} is not allowed: use 1 to 64 letters, digits, '.', '_' or "
            f"'-', starting with a letter or digit (it becomes a file name). Nothing was written.")
    return cohort_id


def cohort_summary(store: Any, cohort_id: str) -> CohortSummary | None:
    """The stored cohort, or None when no cohort by that id exists. Opens no file that is not
    already there, so asking about a mistyped id creates nothing."""
    _check_cohort_id(cohort_id)
    if not Path(store.cohort_path(cohort_id)).exists():
        return None
    handle = store.cohort(cohort_id)
    rows = handle.query(INGEST_STATEMENTS["select_cohort"], cohort_id=cohort_id)
    if not rows:
        return None
    count = handle.query(INGEST_STATEMENTS["count_roster"], cohort_id=cohort_id)[0]["n"]
    return CohortSummary(cohort_id=cohort_id, consent_class=str(rows[0]["consent_class"]),
                         created_at=str(rows[0]["created_at"]), roster_size=int(count))


def create_cohort(store: Any, cohort_id: str, consent_class: str,
                  student_refs: Iterable[str], created_at: str | None = None) -> CohortSummary:
    """Create a cohort with its consent class and roster, in one transaction.

    `consent_class` has no default: it decides whether the cohort's work may be sent to a remote
    model (`FR-CONF-08`), and a default would decide that for the operator. An existing cohort is
    refused rather than overwritten, so its consent class can never be changed by re-running a
    command; `add_to_roster` adds students later. Every refusal writes nothing.
    """
    _check_cohort_id(cohort_id)
    if consent_class not in CONSENT_CLASSES:
        raise CohortSetupError(
            f"consent class {consent_class!r} is not one of {', '.join(CONSENT_CLASSES)}. It is "
            f"required, with no default: 'synthetic' is made-up practice work, 'consented' "
            f"means the students or guardians agreed, 'real' is everything else. Nothing was "
            f"written.")
    refs = _checked_refs(student_refs)
    if not refs:
        raise CohortSetupError(
            "the roster is empty: intake's identity check (V3) would park every paper. Nothing "
            "was written.")
    if cohort_summary(store, cohort_id) is not None:
        raise CohortSetupError(
            f"cohort {cohort_id!r} already exists; it is never overwritten, so its consent class "
            f"stays as created. Use add-students to extend its roster. Nothing was written.")
    stamp = created_at or datetime.now(timezone.utc).isoformat()
    with store.cohort(cohort_id).transaction() as tx:
        tx.execute(INGEST_STATEMENTS["insert_cohort"], cohort_id=cohort_id,
                   consent_class=consent_class, created_at=stamp)
        for ref in refs:
            tx.execute(INGEST_STATEMENTS["insert_roster_entry"], cohort_id=cohort_id,
                       student_ref=ref)
    return CohortSummary(cohort_id=cohort_id, consent_class=consent_class, created_at=stamp,
                         roster_size=len(refs))


def add_to_roster(store: Any, cohort_id: str, student_refs: Iterable[str]) -> CohortSummary:
    """Add students to an existing cohort's roster, in one transaction. A reference already on the
    roster is refused, naming it, so a typo'd re-run cannot pass silently. The consent class is
    untouched."""
    current = cohort_summary(store, cohort_id)
    if current is None:
        raise CohortSetupError(
            f"no cohort {cohort_id!r} exists; create it first. Nothing was written.")
    refs = _checked_refs(student_refs)
    if not refs:
        raise CohortSetupError("no student references were given. Nothing was written.")
    handle = store.cohort(cohort_id)
    present = {row["student_ref"] for row in handle.query(
        INGEST_STATEMENTS["select_roster"], cohort_id=cohort_id)}
    clash = sorted(set(refs) & present)
    if clash:
        raise CohortSetupError(
            f"{len(clash)} reference(s) are already on the roster: {', '.join(clash[:10])}. "
            f"Nothing was written.")
    with handle.transaction() as tx:
        for ref in refs:
            tx.execute(INGEST_STATEMENTS["insert_roster_entry"], cohort_id=cohort_id,
                       student_ref=ref)
    return CohortSummary(cohort_id=cohort_id, consent_class=current.consent_class,
                         created_at=current.created_at, roster_size=current.roster_size + len(refs))
