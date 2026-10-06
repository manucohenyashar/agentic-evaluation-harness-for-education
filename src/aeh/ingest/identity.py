"""V3 identity by name (FR-INGEST-39, CT-INGEST-23, ADR-38) and Cohort migration 33.

The roster carries each student's `full_name` beside an internal `student_ref`. V3 reads the name
the paper's reader copied after `Student:` and matches it against the roster's names under
normalization — case folding (full `casefold`, so `ß` meets `ss`), whitespace collapse, diacritic
folding and token-order tolerance (surname first or last). It never guesses:

* exactly one row's normalized name equals the paper's → that row's ref;
* two or more rows normalize equally → the `Student ID:` line on the paper may choose AMONG THOSE
  rows (an ID never resolves a paper on its own, and another student's ID resolves nothing);
  otherwise `ambiguous`, with the rows as triage candidates;
* no row's name → `unmatched`. The one exception is the pre-migration channel: a roster row with
  no name (created before migration 33) still resolves when the `Student:` line carries its ref
  exactly, so old cohorts keep working.

The name stays here and in Tier C rows: the result carries refs only, and `redact_identity_head`
strips the written name from a transcript before any model request is assembled from it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable

from aeh.store import TIER_MIGRATIONS, Migration, Statement, Tier

#: V3's three outcomes, as recorded in `submission.v3_identity`.
V3_PASS = "pass"
V3_AMBIGUOUS = "ambiguous"
V3_UNMATCHED = "unmatched"

#: What the `Student:` head is replaced with before a transcript reaches a model.
REDACTED_IDENTITY = "[student]"

_STUDENT_LINE = re.compile(r"^Student:[ \t]*(.*)$", re.MULTILINE)
_STUDENT_ID_LINE = re.compile(r"^Student ID:[ \t]*(.+)$", re.MULTILINE)


# --- Tier C, migration 33 (#620, ADR-38): the roster carries names -----------------------------
#
# Nullable in the schema: the migration cannot invent names for rows created before it. A name is
# required at cohort creation instead (`aeh.orch.cohorts`), which is where a roster is written.
_INGEST_ROSTER_NAMES = Migration(
    version=33,
    name="ingest_roster_names",
    statements=(Statement("ALTER TABLE roster ADD COLUMN full_name TEXT"),),
)

TIER_MIGRATIONS[Tier.COHORT] = TIER_MIGRATIONS[Tier.COHORT] + (_INGEST_ROSTER_NAMES,)


def normalize_name(text: str) -> str:
    """The match key of a name: case-folded, diacritics removed (precomposed or decomposed),
    whitespace collapsed, tokens sorted so surname-first and given-name-first agree."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(sorted(stripped.split()))


@dataclass(frozen=True)
class IdentityMatch:
    """V3's verdict: the outcome, the resolved ref (None unless `pass`), and the triage
    candidates (roster refs, never names)."""

    outcome: str
    student_ref: str | None = None
    candidates: tuple[str, ...] = field(default_factory=tuple)


def written_identity(markdown: str) -> tuple[str | None, str | None]:
    """The name on the paper's `Student:` line and the ID on its `Student ID:` line (each None
    when absent or blank)."""
    name = _first_value(_STUDENT_LINE, markdown)
    student_id = _first_value(_STUDENT_ID_LINE, markdown)
    return name, student_id


def _first_value(pattern: re.Pattern[str], markdown: str) -> str | None:
    match = pattern.search(markdown)
    value = match.group(1).strip() if match else ""
    return value or None


def resolve_identity(written_name: str | None, written_id: str | None,
                     roster: Iterable[Any]) -> IdentityMatch:
    """Match the paper's written identity against roster rows (`student_ref`, `full_name`)."""
    rows = [(str(row["student_ref"]), row["full_name"]) for row in roster]
    if written_name is None:
        return IdentityMatch(V3_UNMATCHED)
    key = normalize_name(written_name)
    candidates = sorted(ref for ref, name in rows
                        if name is not None and key and normalize_name(str(name)) == key)
    if len(candidates) == 1:
        return IdentityMatch(V3_PASS, candidates[0])
    if len(candidates) > 1:
        if written_id is not None and written_id in candidates:
            return IdentityMatch(V3_PASS, written_id)
        return IdentityMatch(V3_AMBIGUOUS, candidates=tuple(candidates))
    return _resolve_by_legacy_ref(written_name, [ref for ref, name in rows if name is None])


def _resolve_by_legacy_ref(written: str, nameless_refs: list[str]) -> IdentityMatch:
    """The pre-migration channel (FR-INGEST-24 as it stood before ADR-38): only a NAMELESS row
    resolves from its ref written on the `Student:` line, exactly — a named row's ID is a
    secondary signal and never resolves a paper alone. A non-exact reading offers the nameless
    refs containing it as candidates, as it always did."""
    if written in nameless_refs:
        return IdentityMatch(V3_PASS, written)
    candidates = tuple(sorted(ref for ref in nameless_refs if written.lower() in ref.lower()))
    outcome = V3_AMBIGUOUS if len(candidates) > 1 else V3_UNMATCHED
    return IdentityMatch(outcome, candidates=candidates)


def triage_finding(match: IdentityMatch, name_present: bool) -> str:
    """The V3 finding for a held paper. It names candidates by ref and never carries the
    written name (CT-INGEST-23: names leave the module only into Tier C rows and triage
    display, which reads the stored transcript)."""
    if not name_present:
        return "no student identity found in the submission"
    if match.outcome == V3_AMBIGUOUS:
        return (f"the identity on the paper does not match the roster uniquely — it matches "
                f"{len(match.candidates)} students (candidates: {list(match.candidates)})")
    return (f"the identity on the paper does not match the roster "
            f"(candidates: {list(match.candidates)})")


def redact_identity_head(markdown: str) -> str:
    """The transcript with every `Student:` line's value replaced, so the child's written name
    never reaches a model request (NFR-PROV-04). The `Student ID:` line is left: it is an ID."""
    return _STUDENT_LINE.sub(f"Student: {REDACTED_IDENTITY}", markdown)
