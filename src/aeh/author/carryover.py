"""The answer carry-over (FR-AUTHOR-23, CT-AUTHOR-19/20) — story #697's delta.

A re-draft over the same package id reads the prior run's report — the carry-over's source
of truth (`docs/design/package_authoring_design_delta.md` §3.1) — and re-applies each
recorded review answer whose item still stands and whose content fingerprint still matches,
**provisionally**: the recorded answer is written as a `# CARRIED OVER (provisional —
confirm at review): <display>` comment above the surviving sentinel, and the sentinel
itself stays, so the review walk re-asks the item and the ready gate refuses until the
teacher confirms it there (a carried answer never satisfies the human gate by itself). A
record whose item is gone, or whose fingerprint no longer matches, is dropped — and named
in the new report with the reason and the recorded value, never silent.

Nothing here is state: the prior report is read from the output directory at draft time,
the same place the two artifacts live (ADR-43), so a fresh process re-derives everything
(FR-AUTHOR-21). The walk, the fingerprint and the patch machinery are #696's (`review.py`)
reused as-is, so the carry-over reads exactly the pendings the review will ask and hashes
exactly the content the review records against.

The annotation is comment-only: the parsed spec, the placeholder count and every counted
field are untouched, so a re-draft with nothing to carry stays byte-identical to a draft
with no prior report at all (`TC-AUTHOR-18`, C19's no-records limb).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from .report import draft_filename, report_filename
from .review import CARRIED_COMMENT_PREFIX, _apply, _fingerprint, _merge, _walk
from .types import CarriedAnswer, DroppedAnswer

#: The answer records the review walk writes (`- **<id>** — answered: <display> (content
#: fingerprint <hex>).`) and the carried rows this module's own report section renders —
#: both are carry-over sources, so a carried answer survives a further re-draft.
_ANSWER_RECORD_RE = re.compile(
    r"^- \*\*(.+?)\*\* — (?:answered|carried): (?P<display>.*?) "
    r"\(content fingerprint (?P<fingerprint>[0-9a-fA-F]{8,64})\)\.", re.M)


def prior_artifacts(output: Path, package_id: str) -> tuple[Path | None, Path | None]:
    """The existing draft and report artifacts for `package_id` in `output`, matched by
    file name **ignoring case**.

    A package's identity is case-insensitive (M-PKG's `check_package_id` collision rule),
    so AF-13's regenerated `hist7-rome-01` is the same package as AF-01's `HIST7-ROME-01`:
    the overwrite refusal and the carry-over lookup must see one file on every platform
    (on Windows and macOS the filesystem already folds case; this is the Linux half of the
    same rule). An exact-name match wins over a case-variant one, and within each tier the
    lexicographically first name decides — deterministic either way.
    """
    if not output.is_dir():
        return None, None
    want_draft = draft_filename(package_id)
    want_report = report_filename(package_id)
    exact_draft = exact_report = None
    variant_draft: list[Path] = []
    variant_report: list[Path] = []
    for entry in sorted(output.iterdir()):
        if not entry.is_file():
            continue
        if entry.name == want_draft:
            if exact_draft is None:
                exact_draft = entry
        elif entry.name == want_report:
            if exact_report is None:
                exact_report = entry
        elif entry.name.casefold() == want_draft.casefold():
            variant_draft.append(entry)
        elif entry.name.casefold() == want_report.casefold():
            variant_report.append(entry)
    draft = exact_draft if exact_draft is not None else \
        (variant_draft[0] if variant_draft else None)
    report = exact_report if exact_report is not None else \
        (variant_report[0] if variant_report else None)
    return draft, report


def apply_carry_over(draft_text: str, package_id: str,
                     prior_report_text: str) -> tuple[str, tuple[CarriedAnswer, ...],
                                                      tuple[DroppedAnswer, ...]]:
    """Re-apply the prior report's recorded answers to a freshly rendered draft.

    Returns the (possibly annotated) draft text plus the carried and dropped accounts for
    the new report. A record is carried only when an open placeholder in the regenerated
    draft carries the record's item id AND its content fingerprint matches the recorded
    one (the hash over the item id and the owning content, casefolded on the id —
    `review._fingerprint`); everything else is dropped with a named reason. The prior
    report is never modified, and a report with no answer records changes nothing.
    """
    records = _records(prior_report_text)
    if not records:
        return draft_text, (), ()
    spec = tomllib.loads(draft_text)
    pendings = _walk(spec, draft_text)

    patches: list[tuple[int, int, str]] = []
    carried: list[CarriedAnswer] = []
    dropped: list[DroppedAnswer] = []
    used: set[int] = set()
    claimed: dict[tuple[int, int], str] = {}  # comment span -> the item that claimed it

    for record in records:
        candidates = [i for i, pending in enumerate(pendings)
                      if pending.item_id == record.item_id and i not in used]
        index = next((i for i in candidates
                      if _fingerprint(pendings[i], spec, package_id)
                      == record.fingerprint), None)
        if index is not None:
            pending = pendings[index]
            if pending.comment_span is None:
                # A rendered draft always writes a comment above every sentinel, so this
                # is a defensive branch, not a reachable one — dropped rather than
                # annotated, on the never-silent rule.
                dropped.append(DroppedAnswer(
                    item_id=record.item_id, display=record.display,
                    reason="the draft carries no placeholder comment above the item's "
                           "sentinel to annotate the suggestion on"))
                continue
            if pending.comment_span in claimed:
                # Two sentinels may share one comment line (an inline band entry); only
                # one suggestion fits, so the second is accounted, not silently skipped.
                dropped.append(DroppedAnswer(
                    item_id=record.item_id, display=record.display,
                    reason="its placeholder shares the comment line above it with "
                           f"another carried answer ({claimed[pending.comment_span]}), "
                           "so its suggestion cannot be annotated separately"))
                continue
            claimed[pending.comment_span] = record.item_id
            used.add(index)
            start, end = pending.comment_span
            if end > start and draft_text[end - 1] == "\n":
                end -= 1  # leave the newline separating the comment from the sentinel line
            patches.append((start, end, CARRIED_COMMENT_PREFIX + record.display))
            carried.append(CarriedAnswer(item_id=record.item_id, display=record.display,
                                         fingerprint=record.fingerprint))
        elif candidates:
            dropped.append(DroppedAnswer(
                item_id=record.item_id, display=record.display,
                reason="the content the answer was given against has changed (the "
                       "recorded content fingerprint no longer matches the regenerated "
                       "draft)"))
        else:
            dropped.append(DroppedAnswer(
                item_id=record.item_id, display=record.display,
                reason="the item no longer stands in the regenerated draft (it is "
                       "answered there now, or it no longer exists)"))
    new_text = _apply(draft_text, _merge(patches)) if patches else draft_text
    return new_text, tuple(carried), tuple(dropped)


def _records(prior_report_text: str) -> list[CarriedAnswer]:
    """The prior report's answer records, in report order: the `answered` rows the review
    walk writes and the `carried` rows a previous carry-over wrote (a carried answer stays
    carried across a further re-draft). `rejected` and `dropped` rows are not answers."""
    found: list[CarriedAnswer] = []
    for match in _ANSWER_RECORD_RE.finditer(prior_report_text):
        found.append(CarriedAnswer(
            item_id=match.group(1).strip(),
            display=match.group("display").strip(),
            fingerprint=match.group("fingerprint").lower()))
    return found