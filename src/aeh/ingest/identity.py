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

#: The `student_ref` an unresolved submission carries.
UNRESOLVED_REF = "unknown"

#: What the `Student:` head is replaced with before a transcript reaches a model, when no
#: resolved ref is there to stand in for it.
REDACTED_IDENTITY = "[student]"

#: The identity head: a `Student:` label, tolerating Markdown emphasis around it (`**Student:**`),
#: then the value on the same line. `Student ID:` is not this label (no colon after `Student`).
_STUDENT_HEAD = re.compile(r"^[ \t]*[*_]*Student[*_]*:[*_]*[ \t]*(?P<value>[^\n]*?)[ \t]*$",
                           re.MULTILINE)

#: A line that cannot be the value of a bare `Student:` label: another header or region markup.
_NOT_A_VALUE = re.compile(r"^[ \t]*(<!--|[*_]*(Student ID|Assessment)[*_]*:)")

#: The line after a position, stripped of its surrounding blanks.
_NEXT_LINE = re.compile(r"\n[ \t]*(?P<line>[^\n]*?)[ \t]*(?=\n|$)")

_STUDENT_ID_LINE = re.compile(r"^[ \t]*[*_]*Student ID[*_]*:[*_]*[ \t]*(.+)$", re.MULTILINE)


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
    whitespace collapsed, tokens sorted so surname-first and given-name-first agree. A comma
    separates like whitespace, so `Okafor, Amara` is `Amara Okafor`."""
    decomposed = unicodedata.normalize("NFKD", text.casefold().replace(",", " "))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(sorted(stripped.split()))


@dataclass(frozen=True)
class IdentityMatch:
    """V3's verdict: the outcome, the resolved ref (None unless `pass`), and the triage
    candidates (roster refs, never names)."""

    outcome: str
    student_ref: str | None = None
    candidates: tuple[str, ...] = field(default_factory=tuple)


def _identity_head_values(markdown: str) -> list[tuple[int, int]]:
    """Where each `Student:` head's value sits in `markdown`, as (start, end) offsets. A bare
    label takes the next non-empty line as its value, unless that line is another header or
    markup. The ONE parse both the matcher and the redaction read, so they cannot drift: a name
    the matcher could read is a name the redaction replaces."""
    spans: list[tuple[int, int]] = []
    for head in _STUDENT_HEAD.finditer(markdown):
        if head.group("value").strip():
            spans.append(head.span("value"))
            continue
        position = head.end()
        while (line := _NEXT_LINE.match(markdown, position)) is not None:
            position = line.end()
            if not line.group("line"):
                continue
            if not _NOT_A_VALUE.match(line.group("line")):
                spans.append(line.span("line"))
            break
    return spans


def written_identity(markdown: str) -> tuple[str | None, str | None]:
    """The name on the paper's first `Student:` head and the ID on its `Student ID:` line (each
    None when absent or blank)."""
    heads = _identity_head_values(markdown)
    name = markdown[heads[0][0]:heads[0][1]].strip() if heads else ""
    match = _STUDENT_ID_LINE.search(markdown)
    student_id = match.group(1).strip() if match else ""
    return name or None, student_id or None


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


def pseudonymize_name(text: str, name: Any, ref: Any) -> str:
    """The text with every occurrence of the student's roster display name replaced by the
    student's pseudonymous `student_ref` (NFR-PROV-08: a model request carries the ref, never
    the name). The boundary helper both assemblers share — `M-JUDGE` for the scoring request
    and `M-EXTRACT` for the extraction request — because a name a student writes anywhere on
    the paper (a signature, a turn of phrase) travels in the stored transcript, and every
    request built from that transcript must carry the ref in its place. `aeh.ingest` owns the
    identity rules, so both `aeh.extract` and `aeh.judge` import it here without a cycle
    (`aeh.judge` already imports `aeh.extract`, so the helper cannot live there).

    A call with no name (a ref-only or nameless roster row, the pre-#620 shape — every unit
    `M-ORCH` leases before the roster names a student) passes the text through unchanged, so
    today's bytes assemble byte-identically. The comparison is exact, not normalized: a
    roster's display name is the operator's own spelling, and the transcription that put the
    name in the transcript read it from the same paper the roster was typed from. Name
    variants the roster does not hold are out of scope by design (`judge.py` §3.2 rejects
    free-text redaction); the `Student:` head, the one place the spelling is unreliable, is
    `redact_identity_head`'s job.
    """
    if isinstance(text, str) and isinstance(name, str) and name and ref and name in text:
        return text.replace(name, str(ref))
    return text


def redact_identity_head(markdown: str, student_ref: str | None = None) -> str:
    """The transcript with every `Student:` head's value replaced, so the child's written name
    never reaches a model request (NFR-PROV-04, CT-INGEST-23). The value becomes the
    submission's resolved `student_ref` when one is given — what the line held before names
    (so a request whose head already carried the ref is byte-identical) — and a fixed
    placeholder otherwise. The `Student ID:` line is left: it is an ID. Stored text is never
    changed; callers apply this to the copy they send."""
    replacement = (student_ref if student_ref and student_ref != UNRESOLVED_REF
                   else REDACTED_IDENTITY)
    out = markdown
    for start, end in reversed(_identity_head_values(markdown)):
        out = out[:start] + replacement + out[end:]
    return out
