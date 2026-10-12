"""The review walk and the ready gate (FR-AUTHOR-16/17, R-6) — story #696.

`run_review` walks the teacher through every unresolved item and placeholder a draft still
carries, in report order (== the draft's document order, the disclosure the test plan's
TC-AUTHOR-23/24 pin), one at a time, showing the current value and the reason the field is
missing. Each plain-language answer is checked against the deterministic rules the field
itself states (a key must be drawn from its question's declared options, FR-AUTHOR-10; a
band set must satisfy FR-PKG-06's even 2..6 count and non-decreasing points; grade floors
must be finite and distinct, FR-PKG-16), encoded into the spec vocabulary, and patched into
the draft in place: the quoted sentinel span becomes the encoded value and the
`# PLACEHOLDER(reason):` comment above it is removed. An answer that fails its checks is
rejected — named in the report, the sentinel survives, nothing invalid lands (Q-O9) — and
the checks run in two halves: the field's own rule first, then the whole-draft gate, where
the patched draft is re-validated and an answer that introduces a failure the draft did not
carry (a grade floor duplicating another grade's, a type whose question has no options) is
refused with its sentinel restored, the item left open and re-askable.

Two surfaces, one walk: `answers=None` reads the terminal (one answer line per item, EOF
stops the walk keeping what it applied, a blank line skips the item); `answers=[...]` is the
scripted form — the same call the console will make, one answer at a time (§3.1). A scripted
answer names its item by the sentinel's field id; where several occurrences share one id
(`key` stands once per unkeyed question) an answer is consumed by the first still-open
occurrence in document order.

The walk is local and deterministic: it makes **no model call** through any seam (the
reasoning happened at draft time; the walk mutates, validates and reports), so it writes
exactly the two artifacts it was given — the draft and its report, nothing else
(CT-AUTHOR-12, ADR-43). Every answer accepted is recorded in the report with a content
fingerprint: the hash over the item's id and the underlying content it was given against —
the owning question's id and text as the FINAL draft carries it, or the package id for the
package-level items — never over the answer itself, so the fingerprint follows the content
across flows (FR-AUTHOR-23). An item the draft-time carry-over marked provisional
(`carryover.py`'s `# CARRIED OVER` comment) is asked like any other: the recorded answer is
shown for confirmation, Enter accepts it through the same checks and gate, and until that
confirmation it satisfies nothing — the sentinel stands and the gate refuses ready.

Ready (FR-AUTHOR-17) is re-proved, never remembered: after the accepted answers are patched
in, the updated draft is re-parsed and `validate_draft` runs over it again; the walk reports
ready only when no sentinel of any kind survives (the `approved_by` sign-off included — it
is a placeholder like any other at review, FR-AUTHOR-09) and every structural check passes.
Otherwise it lists what remains — and never prints the build command, which is the ready
wording. A ready outcome also names, in stdout and the report, the report-only omissions
the design leaves optional (spec.py's `in_draft=False` gaps — `points Q2`): the draft
carries no placeholder for them, so they cannot block the gate, but ready never claims
every item resolved while the report still names one.
"""

# TC-AGG-03's scanner reads every string constant — docstrings included — as a SQL
# literal, so prose in this module keeps `verdict` and `points` in separate strings
# (the co-occurrence inside one literal is what the per-judge guard exists to refuse;
# comments are not string constants, hence this note lives as one).

from __future__ import annotations

import hashlib
import logging
import math
import re
import sys
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aeh.pipeline.spec_export import _toml_str

from .errors import AuthoringInputError
from .progress import check_cancel, commit_artifacts, emit, emit_completion
from .report import report_filename
from .types import AuthoringCancel, AuthoringObserver, AuthoringProgress, ReviewAnswer, \
    ReviewResult
from .validation import DraftIssue, validate_draft

LOGGER = logging.getLogger("aeh.author")

_PREFIX = "<<PLACEHOLDER: "
_SUFFIX = ">>"

#: The quoted sentinel token as the draft carries it — the span the review patches.
_TOKEN_RE = re.compile(r'"<<PLACEHOLDER: ([^<>\n]+?)>>"')
#: The bare sentinel as the report's Unresolved list names it.
_BARE_SENTINEL_RE = re.compile(r"<<PLACEHOLDER: ([^<>\n]+?)>>")
#: The `# PLACEHOLDER(<reason>): <supply>` comment above a sentinel line.
_COMMENT_RE = re.compile(r"#\s*PLACEHOLDER\((.+)\):\s*(.+?)\s*$")

#: The `# CARRIED OVER (provisional — confirm at review): <display>` comment the draft-time
#: carry-over (`carryover.py`) writes above a surviving sentinel, parsed back so the review
#: walk re-asks the carried item and offers the recorded answer. `CARRIED_COMMENT_PREFIX` is
#: the single spelling both sides share.
_CARRIED_LINE_RE = re.compile(r"#\s*CARRIED OVER \(provisional[^)]*\):\s*(.*?)\s*$")
CARRIED_COMMENT_PREFIX = "# CARRIED OVER (provisional — confirm at review): "

_CARRIED_REASON = "carried over from the prior report (provisional — confirm at review)"
_CARRIED_SUPPLY = "confirm the carried answer, or replace it"

#: The report's Items rows (`report._items`' rendering), parsed back for the rewrite.
_ITEM_ROW_RE = re.compile(r"^- \*\*(.+?)\*\* — ([a-z]+)(?: — (.*))?\.$")
#: The report's Answers-recorded rows, parsed back so a prior run's records merge — the
#: carried and dropped rows the draft-time carry-over writes (`carryover.py`) merge on the
#: same terms: a run that touches an item supersedes that item's prior row, whatever kind
#: it was.
_ANSWER_ROW_RE = re.compile(
    r"^- \*\*(.+?)\*\* — (?:answered|rejected|carried|dropped): ")
#: The leading scope id of a non-sentinel Unresolved row (`- criterion Q1 — the reasoning
#: did not converge: …`).
_ROW_SCOPE_RE = re.compile(r"^- (.+?) — ")

_NO_REASON = "a placeholder stands in the draft"
_NO_SUPPLY = "the field's value"


@dataclass(frozen=True)
class _Pending:
    """One sentinel occurrence the walk will ask about, reconciled 1:1 against the draft
    text: its item id (the sentinel's field), what kind of answer the field takes, the
    question whose content it sits in, the reason/supply pair the comment above it states,
    and the spans a patch would touch."""

    item_id: str
    kind: str  # string | type | options | key | bands | grades_boundary | grades_table
    owner_qid: str | None
    reason: str
    supply: str
    value_span: tuple[int, int]  # quoted token, or the whole line for the grades table
    comment_span: tuple[int, int] | None
    #: The recorded answer the draft-time carry-over annotated above this sentinel
    #: (`carryover.py`), or `None` when the item is a plain placeholder. A carried item is
    #: asked like any other — the value lands in the draft only when the teacher confirms
    #: it here (FR-AUTHOR-23: provisional until confirmed at review).
    carried: str | None = None


@dataclass(frozen=True)
class _Accepted:
    item_id: str
    display: str
    fingerprint: str


@dataclass(frozen=True)
class _Rejected:
    item_id: str
    reason: str


# --- the walk -------------------------------------------------------------------------------------


def run_review(draft_path: Path, answers: Iterable[ReviewAnswer] | None, *,
               observer: AuthoringObserver | None = None,
               cancel: AuthoringCancel | None = None) -> ReviewResult:
    """The review walk over one draft: answer what it can, re-validate, rewrite both
    artifacts, and report ready only when nothing stands (FR-AUTHOR-16/17).

    The console's progress seam (`FR-AUTHOR-30`): `observer`, when given, hears the
    'reviewing' stage once per answer processed and the 'writing draft' stage around the
    rewrite; `cancel` is checked at those same boundaries and stops the walk with
    `AuthoringCancelled` — the walk's patches live in memory until the single atomic
    commit, so a cancelled walk leaves the draft and the report byte-for-byte as it found
    them (`CT-AUTHOR-24`). Both default to `None`, so the terminal walk (and every
    existing caller) is unchanged."""
    check_cancel(cancel)
    path = Path(draft_path)
    if not path.is_file():
        raise AuthoringInputError(
            f"the draft file {path.name} does not exist: the review walk has nothing to "
            "read, and nothing was written (FR-AUTHOR-16).")
    text = path.read_text(encoding="utf-8")
    try:
        spec = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise AuthoringInputError(
            f"{path.name} is not valid TOML ({error}): the review walk reads the draft "
            "the `aeh author draft` step wrote, and nothing was written.") from error
    if not _is_authoring_draft(spec):
        raise AuthoringInputError(
            f"{path.name} is not an authoring draft: it names no package id and carries no "
            "question or criterion tables (the refusal is content-based, FR-AUTHOR-13's "
            "fail-fast; nothing was written).")
    package_id = str(spec["package"])

    pendings = _walk(spec, text)
    scripted = answers is not None
    answer_list = list(answers) if scripted else []

    accepted: list[_Accepted] = []
    rejected: list[_Rejected] = []
    committed: list[tuple[int, int, str]] = []
    applied: set[int] = set()
    consumed: set[int] = set()

    #: Locally accepted answers, in the order they were offered, awaiting the
    #: re-validation gate — the second, whole-draft half of Q-O9.
    tentative: list[tuple[int, _Pending, str, Any]] = []

    def consume(index: int, item: _Pending, raw: str) -> None:
        ok, value, reason = _evaluate(item, raw.strip(), spec)
        if not ok:
            rejected.append(_Rejected(item.item_id, reason))
            LOGGER.warning("review/%s: rejected — %s", item.item_id, reason)
            return
        display = " ".join(raw.strip().split())
        tentative.append((index, item, display, value))
        consumed.add(index)
        LOGGER.info("review/%s: accepted the local checks, awaiting re-validation",
                    item.item_id)

    # The 'reviewing' stage's boundary counters (`FR-AUTHOR-30`): one item per answer the
    # walk processes, the total the walk's own denominator — the answers it was given when
    # scripted, the items it will ask when terminal.
    review_done = 0
    review_total = 0

    if scripted:
        review_total = len(answer_list)
        for answer in answer_list:
            index = next((i for i, pending in enumerate(pendings)
                          if pending.item_id == answer.item_id and i not in consumed), None)
            if index is None:
                rejected.append(_Rejected(
                    str(answer.item_id),
                    "no open item in the draft carries this id — every item it names is "
                    "already answered, or the draft never had it"))
            else:
                consume(index, pendings[index], str(answer.value))
            review_done += 1
            emit(observer, cancel, AuthoringProgress(
                stage="reviewing", done=review_done, total=review_total,
                current=str(answer.item_id), attempt=1, attempts=1))
    else:
        review_total = len(pendings)
        for index, item in enumerate(pendings):
            _prompt(item)
            line = sys.stdin.readline()
            if line == "":
                print("(end of input — the walk stops here; what it applied is kept, "
                      "FR-AUTHOR-17)")
                break
            raw = line.strip()
            if not raw:
                if item.carried is not None:
                    # Enter accepts the carried answer: the same consume path as a typed
                    # one — the field's checks and the re-validation gate still apply, and
                    # the comment above the sentinel is removed with the patch (the
                    # provisional marker is spent by the confirmation).
                    print(f"(accepting the carried answer — {item.item_id} recorded)")
                    consume(index, item, item.carried)
                else:
                    print(f"(no answer — {item.item_id} stays open)")
                review_done += 1
                emit(observer, cancel, AuthoringProgress(
                    stage="reviewing", done=review_done, total=review_total,
                    current=item.item_id, attempt=1, attempts=1))
                continue
            consume(index, item, raw)
            review_done += 1
            emit(observer, cancel, AuthoringProgress(
                stage="reviewing", done=review_done, total=review_total,
                current=item.item_id, attempt=1, attempts=1))

    # The re-validation gate (Q-O9's second half): each locally accepted answer is applied
    # to the whole draft and `validate_draft` runs over the result — an answer that
    # introduces a validation failure the draft did not carry is refused, its sentinel
    # restored, the item left open and re-askable (the local per-field checks cannot see
    # cross-item rules: a grade floor that duplicates another grade's, a type whose
    # question carries no options). Patches are spans over the original text, so each
    # candidate is the original text plus every patch committed so far plus this one.
    def _issues_of(candidate_text: str) -> list[DraftIssue]:
        return validate_draft(tomllib.loads(candidate_text))

    def _answer_caused(issues: list[DraftIssue]) -> list[DraftIssue]:
        """The issues the gate diffs, excluding the placeholder-driven ones.

        A finding whose message quotes a sentinel exists only because some sentinel still
        stands somewhere in the draft — it is the placeholder sweep's worklist, not a
        failure an answer introduced. `plan_package` also refuses fast on the FIRST bad
        criterion, so its sentinel refusals move from criterion to criterion as earlier
        keys resolve (the baseline pairs C_Q3_key's sentinel refusal; the next candidate
        carries C_Q5_key's instead) — pair-diffing those would reject a correct answer
        for the sibling sentinel it did not touch. The final census and the report's
        Unresolved section still count every standing sentinel, and the build re-runs
        `plan_package` whole, so nothing here hides a gap; the duplicate-floors class the
        gate exists for carries no sentinel in its message and stays caught.
        """
        return [issue for issue in issues if _PREFIX not in issue.message]

    #: The issues the draft already carries, by field AND message: an answer may remove
    #: findings but must never add one, on any field — a field-level diff alone would miss
    #: a new failure hiding under a field the sentinel sweep already named.
    committed_issues = {(issue.field, issue.message)
                        for issue in _answer_caused(_issues_of(text))}
    for index, item, display, value in tentative:
        group: list[tuple[int, int, str]] = [
            (item.value_span[0], item.value_span[1], _encode(item, value))]
        if item.comment_span is not None:
            group.append((*item.comment_span, ""))
        candidate = _apply(text, _merge(committed + group))
        candidate_issues = _issues_of(candidate)
        new_issues = [issue for issue in _answer_caused(candidate_issues)
                      if (issue.field, issue.message) not in committed_issues]
        if new_issues:
            fields = ", ".join(sorted({issue.field for issue in new_issues}))
            reason = "; ".join(issue.message for issue in new_issues)
            rejected.append(_Rejected(
                item.item_id,
                f"re-validation refused the answer: the updated draft fails {fields} "
                f"({reason}) — the item stays open"))
            LOGGER.warning("review/%s: rejected at re-validation — %s", item.item_id, reason)
            # The item stays open and re-askable — in the NEXT run (`aeh author review`
            # again; the outcome's Next command names it). Within THIS run a same-id retry
            # cannot match: the scripted answers were matched to pendings up front, and
            # the gate runs after the whole answer list was read (disclosed residual —
            # the follow-up review's MAJOR 2 reconciliation; cross-run re-ask is probed).
            continue
        committed.extend(group)
        committed_issues |= {(issue.field, issue.message)
                             for issue in _answer_caused(candidate_issues)}
        applied.add(index)

    # The rewrite commits at the end, atomically (`FR-AUTHOR-30`): until here the walk's
    # patches live in memory, so a cancel at any boundary above leaves the draft and the
    # report byte-for-byte as the walk found them (`CT-AUTHOR-24`).
    new_text = _apply(text, _merge(committed)) if committed else text
    new_spec = tomllib.loads(new_text)
    issues = validate_draft(new_spec)

    # The fingerprints are computed against the FINAL draft (the content the answers were
    # actually given against), never the walk-start spec an earlier answer's patch may
    # have since changed (FR-AUTHOR-23: the fingerprint follows the content).
    accepted = [_Accepted(item.item_id, display, _fingerprint(item, new_spec, package_id))
                for _index, item, display, _value in tentative
                if _index in applied]

    standing = [pending for index, pending in enumerate(pendings)
                if index not in applied]
    ready = not _has_sentinel(new_spec) and not issues

    remaining: list[str] = []
    for pending in standing:
        if pending.item_id not in remaining:
            remaining.append(pending.item_id)
    for issue in issues:
        # A validator locator that already names a standing item ("question 'Q2'
        # model_answer" beside the model_answer sentinel) is the same open item twice —
        # the item id is what the teacher was asked, so it carries the listing. A locator
        # that names no item id — a plan refusal whose `_field_of` extraction yields a
        # message fragment (the residual the follow-up review's MINOR 7 named) — surfaces
        # raw below; the answerable item ids carry the listing first.
        if any(item_id in issue.field for item_id in remaining):
            continue
        if issue.field not in remaining:
            remaining.append(issue.field)
    result = ReviewResult(ready=ready, remaining=tuple(remaining))

    if ready:
        LOGGER.info("review: %s is ready (zero placeholders, every check passes)",
                    path.name)
    else:
        for item_id in remaining:
            LOGGER.warning("review: %s still stands in %s", item_id, path.name)

    report_path = path.parent / report_filename(package_id)
    report_text, report_only = _rebuilt_report(path, package_id, pendings, standing,
                                               accepted, rejected, issues, ready, new_spec)
    # The 'writing draft' stage (`FR-AUTHOR-30`): the boundary before the commit is the
    # last cancel checkpoint — the two artifacts are then committed atomically
    # (`progress.commit_artifacts`), and no cancel is checked after the final write, since
    # there is no next step left to stop.
    emit(observer, cancel, AuthoringProgress(
        stage="writing draft", done=0, total=2, current=path.name, attempt=1, attempts=1))
    pairs: list[tuple[Path, str]] = []
    if committed:
        pairs.append((path, new_text))
    pairs.append((report_path, report_text))
    commit_artifacts(path.parent, pairs)
    if committed:
        LOGGER.info("review rewrote the draft in place: %s", path.name)
    LOGGER.info("review rewrote the report: %s", report_path.name)
    emit_completion(observer, AuthoringProgress(
        stage="writing draft", done=2, total=2, current=report_path.name,
        attempt=1, attempts=1))
    _print_outcome(path, standing, issues, ready, report_only)
    return result


def _prompt(item: _Pending) -> None:
    """The walk's one prompt: the item, its current value, why it is missing and what to
    supply — the current value IS the sentinel (the field holds nothing else yet). For a
    carried item the recorded answer is the current value, shown for confirmation."""
    print(f"[aeh author review] {item.item_id}")
    if item.carried is not None:
        print(f"  carried answer (provisional — confirm at review): {item.carried}")
        print("  your answer (press Enter to accept the carried answer, end of input to "
              "stop): ", end="")
    else:
        print(f"  current value: <<PLACEHOLDER: {item.item_id}>>")
        print(f"  missing because: {item.reason}")
        print(f"  what to supply: {item.supply}")
        print("  your answer (blank to skip this item, end of input to stop): ", end="")
    sys.stdout.flush()


def _print_outcome(path: Path, standing: list[_Pending], issues: list[DraftIssue],
                   ready: bool, report_only: list[str] = ()) -> None:
    """The walk's stdout outcome. Ready prints the build command — the ready wording,
    which must appear only when the gate passed (FR-AUTHOR-17: zero placeholders in the
    draft, every structural check passes) — and names the report-only omissions the walk
    never asked about, so ready never reads as "every item resolved" while the report
    still names one. Otherwise the items that remain are listed and the build command is
    never printed."""
    if ready:
        print("The draft is ready: zero placeholders remain in the draft, every "
              "structural check passes (FR-AUTHOR-17).")
        if report_only:
            print("The report still names omission(s) the draft carries no placeholder "
                  f"for — {', '.join(report_only)} — the walk cannot ask for them (the "
                  "design leaves them optional); the build does not require them.")
        print(f"Next: `aeh package build --spec {path.name}`")
        return
    print(f"{len(standing)} item(s) still open in {path.name}:")
    for pending in standing:
        print(f"  - <<PLACEHOLDER: {pending.item_id}>> — {pending.reason}. What to supply: "
              f"{pending.supply}.")
    for issue in issues:
        print(f"  - {issue.field} — {issue.message}")
    if not standing and issues:
        print("No placeholder is left; the items above are what the deterministic checks "
              "still refuse (FR-AUTHOR-17).")
    print(f"To continue: `aeh author review --draft {path.name}`")


# --- the pending-item walk: the spec's sentinels, reconciled against the draft text ---------------


def _walk(spec: Mapping[str, Any], text: str) -> list[_Pending]:
    """Every sentinel occurrence in document order — the report's walk order (disclosed:
    report order == the draft's document order). The spec is walked in the renderer's own
    order (top-level scalars, then the question tables, then the criterion tables, then the
    `[grades]` table last, exactly `render_draft` writes them), each sentinel's kind read
    off the field key it stands at, and each occurrence claimed against the draft text's
    quoted sentinel tokens 1:1 — a draft whose text and parsed spec disagree is refused."""
    tokens: list[tuple[str, tuple[int, int]]] = [
        (match.group(1), (match.start(), match.end())) for match in _TOKEN_RE.finditer(text)]
    claimed = [False] * len(tokens)
    pendings: list[_Pending] = []

    def claim(item_id: str) -> tuple[int, int]:
        for index, (token_id, span) in enumerate(tokens):
            if token_id == item_id and not claimed[index]:
                claimed[index] = True
                return span
        raise AuthoringInputError(
            f"the draft carries no placeholder token for {item_id!r} that its parsed spec "
            "does not also carry — the file and its TOML disagree; nothing was written.")

    def visit(value: Any, section: str, key: str, owner_qid: str | None) -> None:
        if isinstance(value, Mapping):
            for inner_key, inner in value.items():
                visit(inner, section, str(inner_key), owner_qid)
        elif isinstance(value, list):
            for entry in value:
                visit(entry, section, key, owner_qid)
        elif isinstance(value, str) and value.startswith(_PREFIX) and value.endswith(_SUFFIX):
            item_id = value[len(_PREFIX):-len(_SUFFIX)]
            span = claim(item_id)
            kind = _kind_of(section, key)
            reason, supply, comment_span, carried = _comment_above(text, span)
            whole_line = (section, key) == ("top", "grades")
            value_span = _line_span(text, span) if whole_line else span
            pendings.append(_Pending(item_id=item_id, kind=kind, owner_qid=owner_qid,
                                     reason=reason, supply=supply, value_span=value_span,
                                     comment_span=comment_span, carried=carried))

    for key, value in spec.items():
        if key in ("question", "criterion"):
            continue
        if key == "grades" and isinstance(value, Mapping):
            continue  # a real table renders — and is walked — last, as the [grades] table
        visit(value, "top", str(key), None)
    for block in _blocks(spec, "question"):
        qid = block.get("id")
        for key, value in block.items():
            visit(value, "question", str(key), str(qid) if qid is not None else None)
    for block in _blocks(spec, "criterion"):
        qid = block.get("question")
        for key, value in block.items():
            visit(value, "criterion", str(key), str(qid) if qid is not None else None)
    grades = spec.get("grades")
    if isinstance(grades, Mapping):
        for key, value in grades.items():
            visit(value, "grades", str(key), None)
    if not all(claimed):
        raise AuthoringInputError(
            "the draft text carries a placeholder token its parsed spec does not name — "
            "the file and its TOML disagree; nothing was written.")
    return pendings


_KINDS = {
    ("top", "grades"): "grades_table",
    ("question", "type"): "type",
    ("question", "options"): "options",
    ("criterion", "key"): "key",
    ("criterion", "bands"): "bands",
}


def _kind_of(section: str, key: str) -> str:
    """What kind of answer the field takes, from the table it stands in and the field key
    the sentinel is the value of; every other field is free text the teacher supplies."""
    if section == "grades":
        return "grades_boundary"
    return _KINDS.get((section, key), "string")


def _comment_above(text: str, span: tuple[int, int]) -> \
        tuple[str, str, tuple[int, int] | None, str | None]:
    """The comment on the line above the sentinel line, with the comment line's full span
    (trailing newline included) for the patch to remove. A `# PLACEHOLDER(reason): supply`
    comment gives the reason/supply pair; a `# CARRIED OVER (provisional — ...)` comment
    (the draft-time carry-over's annotation) gives the recorded answer as the fourth
    element, the reason/supply pair describing the provisional carry. Neither — the
    defaults."""
    line_start = text.rfind("\n", 0, span[0]) + 1
    if line_start == 0:
        return _NO_REASON, _NO_SUPPLY, None, None
    previous_end = line_start - 1  # the newline separating it from the sentinel's line
    previous_start = text.rfind("\n", 0, previous_end) + 1
    previous = text[previous_start:previous_end]
    remove_end = previous_end + 1 if previous_end < len(text) else previous_end
    carried = _CARRIED_LINE_RE.match(previous)
    if carried is not None:
        return (_CARRIED_REASON, _CARRIED_SUPPLY, (previous_start, remove_end),
                carried.group(1))
    match = _COMMENT_RE.match(previous)
    if match is None:
        return _NO_REASON, _NO_SUPPLY, None, None
    return match.group(1).strip(), match.group(2).strip(), (previous_start, remove_end), None


def _line_span(text: str, span: tuple[int, int]) -> tuple[int, int]:
    """The whole line a token sits on, without its trailing newline — the span the grades
    table's replacement covers."""
    start = text.rfind("\n", 0, span[0]) + 1
    end = text.find("\n", span[1])
    return (start, len(text) if end == -1 else end)


def _blocks(spec: Mapping[str, Any], name: str) -> list[Mapping[str, Any]]:
    raw = spec.get(name, [])
    if not isinstance(raw, list):
        return []
    return [block for block in raw if isinstance(block, Mapping)]


def _is_authoring_draft(spec: Mapping[str, Any]) -> bool:
    """The content-based draft check: a package id naming a package, and at least one of the
    two tables an authoring draft always carries. A valid TOML file with none of it — a
    gradebook, a notes table — is not a draft under any reading, so the refusal comes from
    the content, never the file's name (the disclosure TC-AUTHOR-24 pins)."""
    package = spec.get("package")
    return (isinstance(package, str) and bool(package.strip())
            and (isinstance(spec.get("question"), list)
                 or isinstance(spec.get("criterion"), list)))


# --- the answers: local, deterministic checks per field kind ---------------------------------------


def _evaluate(item: _Pending, raw: str, spec: Mapping[str, Any]) -> tuple[bool, Any, str]:
    """`(accepted, value, rejection-reason)` for one answer, by field kind. The checks are
    the field's own deterministic rules — the same ones `validate_draft` and the build run —
    applied before anything lands, so a rejected answer never reaches the draft (Q-O9)."""
    if not raw:
        return False, None, "the answer is empty; the item stays open"
    if item.kind == "bands":
        return _eval_bands(raw)
    if item.kind == "grades_table":
        return _eval_grade_pairs(raw.splitlines() if "\n" in raw else re.split(r";", raw),
                                 "the grade boundaries, as grade name and minimum mark or "
                                 "percentage, e.g. `Pass: 50`")
    if item.kind == "grades_boundary":
        number, reason = _number(raw)
        if reason:
            return False, None, reason
        return True, number, ""
    if item.kind == "key":
        return _eval_key(raw, spec, item.owner_qid)
    if item.kind == "type":
        value = raw.strip().strip('"').lower()
        if value not in ("mcq", "open", "mixed"):
            return False, None, ("a question's type is \"mcq\" (multiple choice), \"open\" "
                                 "(free text) or \"mixed\"")
        return True, value, ""
    if item.kind == "options":
        return _eval_options(raw)
    return True, raw, ""  # string: free text — the field's value is what the teacher says


def _eval_key(raw: str, spec: Mapping[str, Any], owner_qid: str | None) -> tuple[bool, Any, str]:
    """The key must be drawn from the owning question's declared options (FR-AUTHOR-10) —
    the one check that can truly reject, and the reason Q-O9's rejection oracle rides the
    key placeholder. Several correct letters are accepted, comma- or space-separated."""
    letters = [token for token in re.split(r"[^A-Za-z]+", raw) if token]
    if not letters or any(len(token) != 1 for token in letters):
        return False, None, ("the key is the question's correct option letter (or letters, "
                             "separated by commas) — e.g. `C` or `A, C`")
    options = _owner_options(spec, owner_qid)
    if options is None:
        return False, None, ("the question's options are not determined yet, so the key "
                             "cannot be checked against them (FR-AUTHOR-10); supply the "
                             "options first — the walk asks for them before the key")
    resolved: list[str] = []
    for letter in letters:
        match = next((option for option in options if option.upper() == letter.upper()), None)
        if match is None:
            return False, None, (f"{letter!r} is not one of the question's declared options "
                                 f"{options} (FR-AUTHOR-10: the key must be drawn from them)")
        if match not in resolved:
            resolved.append(match)
    return True, (resolved[0] if len(resolved) == 1 else resolved), ""


def _owner_options(spec: Mapping[str, Any], owner_qid: str | None) -> list[str] | None:
    """The owning question's declared option letters, or `None` when the question cannot be
    found or its options are still a placeholder."""
    if owner_qid is None:
        return None
    block = next((question for question in _blocks(spec, "question")
                  if question.get("id") == owner_qid), None)
    if block is None:
        return None
    options = block.get("options")
    if not isinstance(options, Mapping) or not options:
        return None
    return [str(letter) for letter in options]


def _eval_options(raw: str) -> tuple[bool, Any, str]:
    """Options as `letter: label` pairs — the shape the report's supply line names."""
    entries = [entry for entry in re.split(r"[;\n]", raw) if entry.strip()]
    pairs: dict[str, str] = {}
    for entry in entries:
        match = re.match(r"\s*(?P<letter>[A-Za-z])\s*[):.=-]\s*(?P<label>.+?)\s*$", entry, re.S)
        if match is None:
            return False, None, ("options are option letter and label pairs, e.g. "
                                 "`A: a complete loop; B: a broken loop`")
        letter = match.group("letter").upper()
        if letter in pairs:
            return False, None, f"option {letter} was given twice"
        pairs[letter] = match.group("label")
    if len(pairs) < 2:
        return False, None, "a multiple-choice question needs at least two options"
    return True, pairs, ""


def _eval_bands(raw: str) -> tuple[bool, Any, str]:
    """Bands as plain-language entries, worst first: `name: descriptor (N points)`. The
    band-set rules the build enforces (FR-PKG-06) are applied here, before anything lands —
    an even count of 2..6 and points that never decrease down the worst-first list."""
    entries = [entry for entry in re.split(r"[;\n]", raw) if entry.strip()]
    if len(entries) < 2:
        return False, None, ("bands are at least two entries, worst first, each as "
                             "`name: what that level of work looks like (N points)` — "
                             "e.g. `absent: no evidence (0 points); present: the evidence "
                             "is there (2 points)`")
    bands: list[dict[str, Any]] = []
    for entry in entries:
        match = re.match(
            r"\s*(?P<name>.+?)\s*:\s*(?P<descriptor>.+?)\s*\((?P<points>[0-9.]+)\s*points?\)"
            r"\s*$", entry, re.S)
        if match is None:
            return False, None, ("each band is `name: descriptor (N points)` — the points "
                                 "say what the band awards, and the build requires them")
        points, reason = _number(match.group("points"))
        if reason:
            return False, None, f"band {match.group('name').strip()!r}: {reason}"
        name = match.group("name").strip()
        descriptor = " ".join(match.group("descriptor").split())
        if not name or not descriptor:
            return False, None, "every band needs a name and a descriptor"
        bands.append({"name": name, "points": points, "descriptor": descriptor})
    count = len(bands)
    if count < 2 or count > 6 or count % 2 != 0:
        return False, None, (f"a band set of {count} bands is outside 2..6 or odd "
                             "(FR-PKG-06); the even count removes the safe middle band")
    points = [band["points"] for band in bands]
    if any(later < earlier for earlier, later in zip(points, points[1:])):
        return False, None, ("the band points must never decrease down the worst-first "
                             "list (FR-PKG-06)")
    return True, bands, ""


def _eval_grade_pairs(entries: list[str], hint: str) -> tuple[bool, Any, str]:
    """Grade boundaries as `name: floor` pairs (the `[grades]` table's shape)."""
    pairs: list[tuple[str, Any]] = []
    for entry in entries:
        if not entry.strip():
            continue
        match = re.match(r"\s*(?P<name>.+?)\s*[=:]\s*(?P<floor>-?[0-9.]+)\s*%?\s*$",
                         entry.strip())
        if match is None:
            return False, None, f"{hint} — one pair per grade"
        floor, reason = _number(match.group("floor"))
        if reason:
            return False, None, f"grade {match.group('name').strip()!r}: {reason}"
        name = match.group("name").strip()
        if not name:
            return False, None, "every grade boundary needs the grade's name (FR-PKG-16)"
        pairs.append((name, floor))
    if not pairs:
        return False, None, hint
    floors = [floor for _name, floor in pairs]
    if len(set(floors)) != len(floors):
        return False, None, ("two grades sharing one boundary cut is an ambiguous "
                             "resolution (FR-PKG-16)")
    return True, pairs, ""


def _number(raw: str) -> tuple[float | int, str]:
    """A finite number, `%` tolerated; whole numbers are kept whole."""
    text = raw.strip().rstrip("%").strip()
    try:
        value = float(text)
    except ValueError:
        return 0, f"{raw!r} is not a number"
    if not math.isfinite(value):
        return 0, f"{raw!r} is not a finite number"
    return (int(value) if value.is_integer() else value), ""


# --- the patches -----------------------------------------------------------------------------------


def _encode(item: _Pending, value: Any) -> str:
    """The accepted value, encoded into the spec-export house grammar at the exact span the
    sentinel occupied — a completed draft needs no reformatting to build (FR-PKG-27)."""
    if item.kind == "grades_table":
        return "[grades]\n" + "\n".join(
            f"{_toml_str(name)} = {_number_text(floor)}" for name, floor in value)
    if item.kind == "grades_boundary":
        return _number_text(value)
    if item.kind == "options":
        return "{ " + ", ".join(
            f"{_toml_str(letter)} = {_toml_str(label)}" for letter, label in value.items()) \
            + " }"
    if item.kind == "key":
        if isinstance(value, list):
            return "[" + ", ".join(_toml_str(letter) for letter in value) + "]"
        return _toml_str(value)
    if item.kind == "bands":
        return "[" + ", ".join(
            "{ " + ", ".join((
                f"name = {_toml_str(band['name'])}",
                f"points = {_number_text(band['points'])}",
                f"descriptor = {_toml_str(band['descriptor'])}",
            )) + " }" for band in value) + "]"
    return _toml_str(value)


def _number_text(value: Any) -> str:
    return str(value)


def _merge(patches: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Sorted, overlap-checked, duplicate-free patches. Two sentinel lines may share one
    comment (an inline band entry carrying two sentinels), so identical removals are
    collapsed; anything that still overlaps is a walk bug and refuses rather than corrupts."""
    unique: dict[tuple[int, int], str] = {}
    for start, end, replacement in patches:
        if (start, end) in unique and unique[(start, end)] != replacement:
            raise AuthoringInputError(
                "the review walk produced two different patches for the same span of the "
                "draft — refusing rather than corrupting it; nothing was written.")
        unique[(start, end)] = replacement
    ordered = sorted(unique.items())
    for index in range(len(ordered) - 1):
        (start, end), _replacement = ordered[index]
        (next_start, _next_end), _next_replacement = ordered[index + 1]
        if start > end or end > next_start:
            raise AuthoringInputError(
                "the review walk produced overlapping patches for the draft — refusing "
                "rather than corrupting it; nothing was written.")
    return [(start, end, replacement) for (start, end), replacement in ordered]


def _apply(text: str, patches: list[tuple[int, int, str]]) -> str:
    out: list[str] = []
    cursor = 0
    for start, end, replacement in patches:
        out.append(text[cursor:start])
        out.append(replacement)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


# --- the fingerprints (FR-AUTHOR-23) ----------------------------------------------------------------


def _fingerprint(item: _Pending, spec: Mapping[str, Any], package_id: str) -> str:
    """The hash over the item's id and the underlying content it was given against — the
    owning question's id and text, or the package id for the package-level items. Never the
    answer: the fingerprint follows the content, so two flows answering differently print
    the same fingerprint (FR-AUTHOR-23, CT-AUTHOR-19).

    The id component is casefolded before hashing: a package's identity is
    case-insensitive (M-PKG's `check_package_id` collision rule), and the carry-over's
    match reads fingerprints across re-drafts whose inventory may spell the same package
    id with a different case (AF-01's `HIST7-ROME-01` vs AF-13's `hist7-rome-01`)."""
    owner_id, owner_text = _owner(item, spec, package_id)
    seed = f"{item.item_id}|{owner_id.casefold()}|{owner_text}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _owner(item: _Pending, spec: Mapping[str, Any], package_id: str) -> tuple[str, str]:
    if item.owner_qid is None:
        return package_id, ""
    block = next((question for question in _blocks(spec, "question")
                  if question.get("id") == item.owner_qid), None)
    if block is None:
        return item.owner_qid, ""
    return str(block.get("id")), str(block.get("text", ""))


# --- the report rewrite -----------------------------------------------------------------------------


def _rebuilt_report(path: Path, package_id: str, pendings: list[_Pending],
                    standing: list[_Pending], accepted: list[_Accepted],
                    rejected: list[_Rejected], issues: list[DraftIssue], ready: bool,
                    new_spec: Mapping[str, Any]) -> tuple[str, list[str]]:
    """The report, rebuilt (FR-AUTHOR-16): the Documents and Steps head kept, the Items
    section's question rows updated (a question whose sentinels all fell reads resolved —
    unless the report still names a report-only omission in its scope), an
    Answers-recorded section rebuilt from this run's rows **merged with the prior report's
    carryable rows** (FR-AUTHOR-12's "every item the teacher answered at review" spans
    runs, and FR-AUTHOR-23's carry-over reads this section — a second review must never
    erase the first one's records), the Unresolved list rebuilt from what still stands,
    and the Next command stating the gate's outcome. Rebuilt even when every answer was
    refused — the outcome is recorded either way (Q-O9) — and returned as text: the walk
    commits it together with the draft, atomically (`FR-AUTHOR-30`).

    Returns `(report text, item ids the rebuilt Unresolved section still names that the
    walk never asked about)` — spec.py's `in_draft=False` omissions (`points Q2`): they
    stand in no draft span, so the ready wording names them rather than implying
    everything resolved.
    """
    report_path = path.parent / report_filename(package_id)
    old = report_path.read_text(encoding="utf-8") if report_path.is_file() else \
        f"# Authoring report — {package_id}\n"
    lines = old.split("\n")
    try:
        items_at = next(index for index, line in enumerate(lines) if line.startswith("## Items"))
    except StopIteration:
        items_at = len(lines)
    head = lines[:items_at]

    answered_ids = {record.item_id for record in accepted}
    standing_ids = {pending.item_id for pending in standing}

    prior: list[str] = []
    answers_at = next((index for index, line in enumerate(lines)
                       if line.startswith("### Answers recorded at review")), None)
    if answers_at is not None:
        touched = answered_ids | {record.item_id for record in rejected}
        for line in lines[answers_at + 1:]:
            if line.startswith("#"):
                break
            if not line.strip():
                continue
            match = _ANSWER_ROW_RE.match(line)
            if match is not None and match.group(1) in touched:
                continue  # this run's row supersedes the prior one for the same item id
            prior.append(line)

    unresolved = _rebuilt_unresolved(lines, pendings, answered_ids, standing_ids, issues)
    pending_ids = {pending.item_id for pending in pendings}
    report_only = sorted({named for line in unresolved
                          for named in _BARE_SENTINEL_RE.findall(line)
                          if named not in pending_ids})

    out = [*head, "## Items", ""]
    out.extend(_updated_item_rows(lines, items_at, new_spec, report_only))
    if accepted or rejected or prior:
        out.extend(["", "### Answers recorded at review", ""])
        for record in accepted:
            out.append(f"- **{record.item_id}** — answered: {record.display} "
                       f"(content fingerprint {record.fingerprint}).")
        for record in rejected:
            out.append(f"- **{record.item_id}** — rejected: {record.reason} "
                       "The item stays open.")
        out.extend(prior)

    out.extend(["", "## Unresolved", ""])
    out.extend(unresolved or [
        "Nothing: every item resolved. The draft is ready to build."])

    out.extend(["", "## Next command", ""])
    if ready:
        out.extend([f"`aeh package build --spec {path.name}`", ""])
    else:
        out.extend([f"`aeh author review --draft {path.name}`", "",
                    "The review walk asks for every item above, one at a time, and for the "
                    "approval (`approved_by`) — then, when nothing is left:", "",
                    f"`aeh package build --spec {path.name}`", ""])
    return "\n".join(out), report_only


def _scope_of(item_id: str, spec: Mapping[str, Any]) -> str | None:
    """The question an item id belongs to, the report's own longest-suffix attribution
    (report.py's `priority`): ids are built as `<field> <qid>`, but a question id may
    itself carry spaces, so the last rsplit word is not the id."""
    qids = [str(question.get("id")) for question in _blocks(spec, "question")
            if question.get("id") is not None]
    return max((qid for qid in qids if item_id.endswith(" " + qid)), key=len, default=None)


def _updated_item_rows(lines: list[str], items_at: int, new_spec: Mapping[str, Any],
                       report_only: list[str]) -> list[str]:
    """The Items section's rows, parsed back and updated: a question row whose every
    in-scope sentinel the review removed now reads resolved — unless the report still
    names a report-only omission in that question's scope (`points Q2`): the row then
    stays as it was, so Items never claims every item answered while Unresolved names one
    (the self-contradiction the #696 review found on AF-08). Rows that still stand, and
    rows that are not rows, are kept as they were."""
    gap_scopes = {_scope_of(item_id, new_spec) for item_id in report_only}
    rows: list[str] = []
    for line in lines[items_at + 1:]:
        if line.startswith("#"):
            break
        rows.append(line)
    updated: list[str] = []
    for line in rows:
        match = _ITEM_ROW_RE.match(line)
        if match is None:
            updated.append(line)
            continue
        qid, status, _detail = match.group(1), match.group(2), match.group(3) or ""
        if (status in ("placeholder", "unresolved")
                and not _scope_has_sentinel(new_spec, qid)
                and qid not in gap_scopes):
            updated.append(f"- **{qid}** — resolved — every item answered at review.")
        else:
            updated.append(line)
    return updated


def _scope_has_sentinel(spec: Mapping[str, Any], qid: str) -> bool:
    """Whether any sentinel still stands in question `qid`'s own content: its block and the
    criterion lines that name it."""
    for question in _blocks(spec, "question"):
        if question.get("id") == qid and _contains_sentinel(question):
            return True
    for criterion in _blocks(spec, "criterion"):
        if criterion.get("question") == qid and _contains_sentinel(criterion):
            return True
    return False


def _contains_sentinel(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_sentinel(entry) for entry in value.values())
    if isinstance(value, list):
        return any(_contains_sentinel(entry) for entry in value)
    return isinstance(value, str) and value.startswith(_PREFIX) and value.endswith(_SUFFIX)


def _rebuilt_unresolved(lines: list[str], pendings: list[_Pending], answered_ids: set[str],
                        standing_ids: set[str], issues: list[DraftIssue]) -> list[str]:
    """The Unresolved list, rebuilt from the current truth: a gap row whose every sentinel
    it names was answered this run is dropped; a non-convergence row whose scope the walk
    answered in full is dropped too (the human answer superseded the reasoning's failure —
    a stale row must not survive a ready verdict, the #696 review's AF-09 finding); the
    template "Nothing" line is dropped (the rebuilt list states the verdict itself). The
    still-open items are appended in walk order with their reason and supply from the
    draft's own comments; the deterministic checks' findings last, never doubling an item
    id the list already carries."""
    try:
        unresolved_at = next(index for index, line in enumerate(lines)
                             if line.startswith("## Unresolved"))
    except StopIteration:
        unresolved_at = None
    pending_ids = {pending.item_id for pending in pendings}
    kept: list[str] = []
    covered: set[str] = set()
    if unresolved_at is not None:
        for line in lines[unresolved_at + 1:]:
            if line.startswith("#"):
                break
            if not line.strip():
                continue
            if line.startswith("- Nothing:"):
                continue
            named = _BARE_SENTINEL_RE.findall(line)
            if not named:
                match = _ROW_SCOPE_RE.match(line)
                scope = match.group(1) if match else None
                if (scope is not None and scope in pending_ids
                        and scope in answered_ids and scope not in standing_ids):
                    continue  # the reasoning failure the walk's answers superseded
                kept.append(line)
                continue
            if all(item_id in answered_ids and item_id not in standing_ids
                   for item_id in named):
                continue
            kept.append(line)
            covered.update(named)
    rebuilt = list(kept)
    for pending in pendings:
        if pending.item_id in covered:
            continue
        if pending.item_id in answered_ids and pending.item_id not in standing_ids:
            continue
        rebuilt.append(f"- <<PLACEHOLDER: {pending.item_id}>> — {pending.reason}. "
                       f"What to supply: {pending.supply}.")
        covered.add(pending.item_id)
    for issue in issues:
        if any(item_id in issue.field for item_id in covered):
            continue
        rebuilt.append(f"- {issue.field} — {issue.message}")
        covered.add(issue.field)
    return rebuilt


def _has_sentinel(value: Any) -> bool:
    """Whole-value sentinel detection over the parsed spec, `approved_by` included: at the
    ready gate the sign-off is a placeholder like any other (FR-AUTHOR-09, FR-AUTHOR-17)."""
    if isinstance(value, Mapping):
        return any(_has_sentinel(entry) for entry in value.values())
    if isinstance(value, list):
        return any(_has_sentinel(entry) for entry in value)
    return isinstance(value, str) and value.startswith(_PREFIX) and value.endswith(_SUFFIX)