"""Roster entries: a student's full name, required, and an optional ID (FR-INGEST-40, ADR-38).

Students are identified by the name written on their papers; a student ID is optional, a secondary
signal and a display convenience, never the only way a student is listed. So a roster entry
without a name is refused here, where every roster write (the command line's and the console's)
passes, and the refusal reads the same whichever surface sent it.

When an entry carries no ID, its `student_ref` is generated: opaque (digits only, so it can never
carry a fragment of the name into a model request — refs are what requests carry, NFR-PROV-04),
stable (stored once, never recomputed), and derived from the cohort, the entry's cohort-unique
ordinal and the name, so the same name in two cohorts gets two refs.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Mapping



class CohortSetupError(Exception):
    """A cohort could not be created or extended as asked. Nothing was written."""


#: Longest name accepted; a longer cell is a pasted paragraph, not a name.
MAX_NAME_LENGTH = 200

#: Longest student reference accepted.
MAX_REF_LENGTH = 128

#: Generated refs: this prefix, then this many decimal digits of a digest.
GENERATED_REF_PREFIX = "r-"
GENERATED_REF_DIGITS = 10

#: Unicode categories no name or reference may contain: control, format (zero-width), surrogate,
#: private-use and unassigned characters — text that would never match what a reader transcribes.
_INVISIBLE_CATEGORIES = ("Cc", "Cf", "Cs", "Co", "Cn")

#: What every name refusal says, so the CLI and the console refuse identically.
NAME_REQUIREMENT = (
    "every student needs a full name: students are identified by the name written on their "
    "papers, and a student ID may be given beside a name but never instead of one (FR-INGEST-40)")


@dataclass(frozen=True)
class RosterEntry:
    """One student as a roster lists them: the full name, and an optional student ID."""

    full_name: str | None
    student_ref: str | None = None


@dataclass(frozen=True)
class CheckedEntry:
    """An entry ready to store: its (supplied or generated) ref and its name."""

    student_ref: str
    full_name: str


def check_student_refs(student_refs: Iterable[Any]) -> tuple[str, ...]:
    """The references, stripped, or `CohortSetupError`. A reference is visible text: no spaces, no
    control or invisible formatting characters (a zero-width space would never match the
    `Student ID:` line a paper's reader transcribes), and no repeats."""
    refs = tuple(str(ref).strip() for ref in student_refs)
    bad = [ref for ref in refs if not ref or len(ref) > MAX_REF_LENGTH or any(
        ch.isspace() or unicodedata.category(ch) in _INVISIBLE_CATEGORIES for ch in ref)]
    if bad:
        raise CohortSetupError(
            f"{len(bad)} student reference(s) are empty, longer than {MAX_REF_LENGTH} "
            f"characters, or contain spaces or invisible characters; a reference must match "
            f"what is written on the paper exactly. Nothing was written.")
    seen: set[str] = set()
    repeated = sorted({ref for ref in refs if ref in seen or seen.add(ref)})
    if repeated:
        raise CohortSetupError(
            f"the roster lists {len(repeated)} reference(s) more than once: "
            f"{', '.join(repeated[:10])}. Nothing was written.")
    return refs


def check_roster(entries: Iterable[Any], cohort_id: str, *, first_ordinal: int = 1,
                 existing_refs: Iterable[str] = ()) -> tuple[CheckedEntry, ...]:
    """The entries ready to store, or `CohortSetupError`. A bare string is an ID with no name and
    is refused like any nameless entry. `first_ordinal` continues an existing roster's numbering
    and `existing_refs` are the refs already stored, which no new ref may repeat."""
    raw = [_as_entry(entry) for entry in entries]
    names = [_clean_name(entry.full_name) for entry in raw]
    nameless = [position for position, name in enumerate(names, start=1) if name is None]
    if raw and len(nameless) == len(raw):
        raise CohortSetupError(
            f"the roster lists student IDs only — {NAME_REQUIREMENT}. Nothing was written.")
    if nameless:
        shown = ", ".join(str(position) for position in nameless[:10])
        raise CohortSetupError(
            f"{len(nameless)} roster entr{'y has' if len(nameless) == 1 else 'ies have'} no "
            f"usable name (entry {shown}) — {NAME_REQUIREMENT}. A name is at most "
            f"{MAX_NAME_LENGTH} characters with no invisible characters. Nothing was written.")
    supplied = check_student_refs(entry.student_ref for entry in raw
                                  if entry.student_ref is not None)
    taken = set(existing_refs) | set(supplied)
    checked: list[CheckedEntry] = []
    for ordinal, (entry, name) in enumerate(zip(raw, names), start=first_ordinal):
        ref = entry.student_ref
        if ref is None:
            ref = _generate_ref(cohort_id, ordinal, name, taken)
            taken.add(ref)
        checked.append(CheckedEntry(student_ref=ref.strip(), full_name=name))
    return tuple(checked)


def _as_entry(entry: Any) -> RosterEntry:
    if isinstance(entry, RosterEntry):
        return entry
    if isinstance(entry, Mapping):
        ref = entry.get("student_ref")
        return RosterEntry(full_name=entry.get("full_name"),
                           student_ref=None if ref is None or not str(ref).strip() else str(ref))
    # A bare value is an ID: refused below as an entry with no name.
    return RosterEntry(full_name=None, student_ref=str(entry))


def _clean_name(name: Any) -> str | None:
    """The name stripped, or None when it is missing, blank, too long or holds invisible
    characters (combining accents, as in a decomposed `é`, are visible and allowed)."""
    if name is None:
        return None
    text = str(name).strip()
    if not text or len(text) > MAX_NAME_LENGTH or any(
            unicodedata.category(ch) in _INVISIBLE_CATEGORIES and ch not in "\t" for ch in text):
        return None
    return text


def _generate_ref(cohort_id: str, ordinal: int, name: str, taken: set[str]) -> str:
    """An opaque ref from the cohort, the ordinal and the name; a clash with a taken ref (vanishingly
    rare at ten digits) re-derives with a salt rather than guessing a suffix."""
    folded = " ".join(unicodedata.normalize("NFC", name).casefold().split())
    salt = 0
    while True:
        digest = hashlib.sha256(
            f"{cohort_id}\x1f{ordinal}\x1f{folded}\x1f{salt}".encode("utf-8")).hexdigest()
        number = int(digest, 16) % 10 ** GENERATED_REF_DIGITS
        ref = f"{GENERATED_REF_PREFIX}{number:0{GENERATED_REF_DIGITS}d}"
        if ref not in taken:
            return ref
        salt += 1
