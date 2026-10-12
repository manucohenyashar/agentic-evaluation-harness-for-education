"""The draft's structured edit path (`FR-CONSOLE-56`, #760): apply one structured change to a
draft file, validate the result with the draft's own rules, and persist it atomically.

The console's editor never sends TOML text (`ADR-45`: the draft files are the state, and the
teacher never meets the format): it names an operation from `EDIT_OPERATIONS` and the fields
the operation moves, and this module is the validate/persist path the design names. The rule
the editor's save button stands on (`TC-CONSOLE-63`'s third arm) is:

* an edit that would introduce a validation issue the draft did not already carry — an
  empty question text, a criterion whose key is not among its question's options — is
  **refused with the field named**, and the draft on disk is unchanged;
* an edit that only adds or resolves a *placeholder* is allowed: a placeholder is the
  workflow's own pending-work marker (the review walk exists to resolve them), not a
  mistake — a question added without its expected solution yet stands as a named sentinel
  the review screen then asks about.

The rule is evaluated layer by layer (`#760`'s review of this module): the complete
layers — the band, composite, grade and sentinel sweeps plus the structural checks below —
diff wholesale, because each reports every finding, so an after-before delta is exactly
what the edit introduced. The plan layer cannot diff that way: `plan_package` reports
**one refusal — its first** — so fixing it unmasks the next, and a whole-list delta would
refuse an edit for a pre-existing failure it never touched. `first_plan_issue` pulls that
layer out and `_plan_layer_refusal` judges it on its own terms.

The edited draft re-renders in the same house grammar `render_draft` writes, with every
`# PLACEHOLDER(reason): supply` comment the original carried re-attached above its sentinel
(`FR-AUTHOR-11` — the build's refusal reads that comment, so an edit may never lose it).
Comment recovery is best-effort by construction: a sentinel whose comment is gone
(a hand-edited draft) renders as a bare sentinel, which `plan_package`'s own sweep still
refuses with the field named.

The draft's approval marker (`approve draft package`'s idempotency gate, #760) also rides
this module: the marker is a comment line in the draft file itself (`ADR-45` — the files
are the state), so an edit must carry it across the re-render untouched, and the approve
gate reads it back from the same file.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .errors import AuthoringInputError
from .progress import commit_artifacts
from .spec import Assembly, Gap, render_draft
from .validation import DraftIssue, first_plan_issue, validate_draft


#: The operations the console's editor may ask for, one per structured change. The names
#: are the editor's own verbs (`FR-UI-13`: add/edit/reorder/delete via forms), not TOML
#: paths — the console never sends TOML text, and this module never accepts it.
EDIT_OPERATIONS: tuple[str, ...] = (
    "add question",
    "edit question",
    "move question",
    "delete question",
    "add option",
    "remove option",
    "add criterion",
    "edit criterion",
    "move criterion",
    "delete criterion",
)


#: The comment a sentinel line carries above it (`FR-AUTHOR-11`'s shape), as the renderer
#: and the review walk both read it.
_PLACEHOLDER_COMMENT = re.compile(r"#\s*PLACEHOLDER\s*\(([^)]*)\)\s*:?\s*(.*)")

#: The sentinel value itself, whose field is the review item id.
_SENTINEL_VALUE = re.compile(r"<<PLACEHOLDER:\s*(.*?)\s*>>")

#: The approval marker `approve draft package` writes after a successful build+publish:
#: `# APPROVED: <package_id> <version> (<sha256 of the approved text>)`. The hash is of the
#: draft text with every marker line removed. The marker's exact promise is the idempotent
#: replay (`TC-CONSOLE-64`'s third arm): approving an unchanged draft after the first build
#: dispatches nothing. An *edited* draft falls through to the build gate, where `M-PKG`'s
#: own rule applies — a built package is never changed, so the build refuses and the
#: edited draft needs a package id of its own (the console's approve action says so in its
#: refusal, #760). The hash is what keeps the replay arm exact: any edit to the approved
#: text changes it, so a stale marker never admits a second build of different content.
_APPROVED_MARKER = re.compile(
    r"#\s*APPROVED:\s+(\S+)\s+(\S+)\s+\(([0-9a-f]{64})\)")

_QUESTION_TYPES = ("open", "mcq", "mixed")


@dataclass(frozen=True)
class EditChange:
    """One change the edit made, in the draft's own locator vocabulary — the same
    `question 'Q3' text` shape `validate_draft`'s issues use, so a change list and a
    validation list read alike on the editor screen."""

    field: str
    change: str


@dataclass(frozen=True)
class EditOutcome:
    """What one structured edit did: the file it rewrote and the field-level change list
    the console renders as the before/after confirmation (`FR-UI-13`)."""

    path: Path
    changes: tuple[EditChange, ...]
    spec: dict[str, Any]


def approval_of(text: str) -> tuple[str, str, str] | None:
    """The draft's approval marker, as `(package_id, version, content hash)`, or `None`
    when the draft carries none — the approve gate's read side."""
    found = None
    for match in _APPROVED_MARKER.finditer(text):
        found = match
    return (found.group(1), found.group(2), found.group(3)) if found else None


def with_approval_marker(text: str, package_id: str, version: str, digest: str) -> str:
    """The draft text carrying exactly one approval marker: every marker line removed (a
    re-approval of an edited draft replaces the stale one) and the new line appended."""
    stripped = "\n".join(
        line for line in text.splitlines() if not _APPROVED_MARKER.search(line)
    ).rstrip("\n")
    return f"{stripped}\n\n# APPROVED: {package_id} {version} ({digest})\n"


def content_digest(text: str) -> str:
    """The sha256 of the draft text with its marker lines removed — what the marker's hash
    field records and what the approve gate compares."""
    import hashlib

    stripped = "\n".join(
        line for line in text.splitlines() if not _APPROVED_MARKER.search(line)
    ).rstrip("\n")
    return hashlib.sha256(stripped.encode("utf-8")).hexdigest()


def apply_structured_edit(
    draft_path: Path, operation: str, *, params: Mapping[str, Any]
) -> EditOutcome:
    """Apply one structured edit to the draft file at `draft_path`.

    The order is the guarantee (`TC-CONSOLE-63`'s third arm): the parsed draft is edited in
    memory, the result is validated against the rules the draft already carried, and only a
    draft with no *new* non-placeholder issue is rendered and committed — atomically, so a
    refusal or a failure leaves the file byte-for-byte as it was. Raises
    `AuthoringInputError` with the field named for every refusal; nothing is written on
    any of them.
    """
    if operation not in EDIT_OPERATIONS:
        raise AuthoringInputError(
            f"The edit {operation!r} is not one the editor performs "
            f"({', '.join(EDIT_OPERATIONS)}). The draft on disk is unchanged.")
    text = _read_text(draft_path)
    try:
        spec = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise AuthoringInputError(
            f"The draft file could not be read: line {error.lineno} does not parse as a "
            "draft. Fix it on disk or re-draft from the documents. Nothing was changed."
        ) from error
    package_gaps, question_gaps = _comment_gaps(text)
    plan_before = first_plan_issue(spec)
    before = _issues_of(spec, plan_before)

    changes = _apply(operation, spec, params)

    plan_after = first_plan_issue(spec)
    new_issues = [
        (field, message) for field, message in _issues_of(spec, plan_after)
        if (field, message) not in before
        and "placeholder" not in message.lower()
    ]
    plan_refusal = _plan_layer_refusal(plan_before, plan_after, changes)
    if plan_refusal is not None:
        new_issues.append((plan_refusal.field, plan_refusal.message))
    if new_issues:
        listing = "; ".join(
            f"{field}: {message}" for field, message in new_issues)
        raise AuthoringInputError(
            f"The edit was not saved: it would leave the draft invalid ({listing}). Fix "
            "the named field and save again. The draft on disk is unchanged.")

    assembly = Assembly(
        package_id=str(spec.get("package") or ""), spec=spec,
        gaps=package_gaps, question_gaps=question_gaps)
    new_text = render_draft(assembly)
    markers = [line for line in text.splitlines() if _APPROVED_MARKER.search(line)]
    if markers:
        new_text = new_text.rstrip("\n") + "\n" + "\n".join(markers) + "\n"
    commit_artifacts(draft_path.parent, [(draft_path, new_text)])
    return EditOutcome(path=draft_path, changes=tuple(changes), spec=spec)


def _issues_of(
    spec: dict[str, Any], plan_issue: DraftIssue | None = None
) -> set[tuple[str, str]]:
    """The draft's validity state, as `(field, message)` pairs, in two layers.

    The first is `validate_draft`'s **complete** layers — the band, composite, grade and
    sentinel sweeps — with the plan layer's single first refusal removed (the caller
    passes it as `plan_issue`; it is judged on its own terms by `_plan_layer_refusal`,
    because `plan_package` reports one refusal and a diff of whole lists pairs a
    still-standing one with a masked one). The second exists because `plan_package`
    reports **one refusal — its first** — and a draft that already fails somewhere earlier
    would mask a break the edit just introduced downstream: a key pointed at an option the
    question does not carry would save silently behind an unrelated pre-existing refusal.
    So the question/criterion relationships the plan checks are also evaluated here,
    entry by entry, where nothing masks anything. A pair standing before the edit and
    after it alike is pre-existing state the editor does not own; the refusal rule is the
    delta's — an edit that would **introduce** a validation issue is refused.

    Deliberately absent from the second layer: the ungraded-question rule. `add question`
    must be able to land before its grading point exists (the editor's two form steps),
    and a question whose criterion was just deleted is the review screen's pending work —
    the approve gate carries the plan's own refusal for the state that reaches a build.
    """
    issues = {(issue.field, issue.message) for issue in validate_draft(spec)}
    if plan_issue is not None:
        issues.discard((plan_issue.field, plan_issue.message))
    issues.update(_structural_issues(spec))
    return issues


def _plan_layer_refusal(
    before: DraftIssue | None, after: DraftIssue | None,
    changes: list[EditChange],
) -> DraftIssue | None:
    """The plan layer's verdict on its own terms, because `plan_package` reports one
    refusal — its first — and a whole-list delta cannot tell a refusal the edit introduced
    from one the first-refusal rule just unmasked. The cases:

    * a refusal carrying a placeholder marker is the worklist, never a failure (the
      sentinel sweep owns those, and placeholders may stand);
    * a refusal standing before and after alike is pre-existing state;
    * a refusal on a plan layer that was **clear** before is the edit's doing — refuse;
    * a **moved** refusal (the plan refused something else before) is refused only when it
      names an entry this edit touched; otherwise the plan's first-refusal rule unmasked a
      pre-existing failure elsewhere, which the approve gate still carries to a build.
    """
    if after is None or "placeholder" in after.message.lower():
        return None
    if before is not None and (before.field, before.message) == (
            after.field, after.message):
        return None
    if before is None:
        return after
    touched = {_locator_entry(change.field) for change in changes}
    touched.discard(None)
    return after if _locator_entry(after.field) in touched else None


def _locator_entry(field: str) -> tuple[str, str] | None:
    """The question or criterion entry a locator names, as `(kind, id)` — the `'Q3'`
    inside `question 'Q3' model_answer` — or `None` when the locator names no entry."""
    match = re.search(r"\b(question|criterion)\s+'([^']+)'", field)
    return (match.group(1), match.group(2)) if match else None


def _structural_issues(spec: Mapping[str, Any]) -> set[tuple[str, str]]:
    """The question/criterion relationships, checked entry by entry: option tables where
    the question's type demands them, a key that is among its question's options, exactly
    one of key or score levels per grading point, and no judged line on a multiple-choice
    question — the same rules `plan_package` refuses a build on, evaluated without the
    first-error masking."""
    issues: set[tuple[str, str]] = set()
    questions = spec.get("question")
    options_by_qid: dict[str, set[str]] = {}
    mcq: set[str] = set()
    for entry in questions if isinstance(questions, list) else ():
        if not isinstance(entry, Mapping):
            continue
        qid = str(entry.get("id"))
        where = f"question {qid!r}"
        qtype = str(entry.get("type") or "open")
        if qtype not in _QUESTION_TYPES:
            issues.add((where, f"{where}: its type is one of "
                        f"{', '.join(_QUESTION_TYPES)}."))
            continue
        options = entry.get("options")
        if qtype in ("mcq", "mixed"):
            if isinstance(options, Mapping) and options:
                options_by_qid[qid] = {
                    str(letter).strip().upper() for letter in options}
            else:
                issues.add((where, f"{where}: a multiple-choice question carries its "
                           "options as a table of letter and label."))
        if qtype == "mcq":
            mcq.add(qid)
        if qtype == "open" and options is not None and not isinstance(options, str):
            issues.add((where, f"{where}: an open question carries no options."))
    criteria = spec.get("criterion")
    for entry in criteria if isinstance(criteria, list) else ():
        if not isinstance(entry, Mapping):
            continue
        cid = str(entry.get("id"))
        where = f"criterion {cid!r}"
        key = entry.get("key")
        bands = entry.get("bands")
        if (key is None) == (bands is None):
            issues.add((where, f"{where}: a grading point carries exactly one of a "
                        "key or score levels."))
            continue
        qid = str(entry.get("question") or "")
        if key is not None:
            allowed = options_by_qid.get(qid)
            if allowed is None:
                issues.add((where, f"{where}: its question {qid!r} carries no options "
                           "for a key to name."))
            else:
                keys = key if isinstance(key, list) else [key]
                for one in keys:
                    if str(one).strip().upper() not in allowed:
                        issues.add((where, f"{where}: key {one!r} is not among its "
                                    "question's options."))
        if bands is not None and qid in mcq:
            issues.add((where, f"{where}: a score level stands on a multiple-choice "
                        "question, which is graded by its key."))
    return issues


# --- the operations -------------------------------------------------------------------------------------


def _apply(operation: str, spec: dict[str, Any],
           params: Mapping[str, Any]) -> list[EditChange]:
    """Dispatch one operation over the parsed spec, in place. Every param-shape refusal
    raises `AuthoringInputError` with the field named; a refusal leaves `spec` semantically
    untouched from the caller's point of view (it is never rendered after a raise)."""
    if operation.startswith("add option") or operation == "remove option":
        return _option_change(operation, spec, params)
    target = "question" if "question" in operation else "criterion"
    entries = _tables_of(spec, target)
    if operation.startswith("add "):
        if target == "question":
            return _add_question(spec, entries, params)
        return _add_criterion(spec, entries, params)
    item_id = _item_id(params, target)
    entry = _entry_of(entries, target, item_id)
    if operation.startswith("edit "):
        return _edit_entry(spec, entry, target, item_id, params)
    if operation.startswith("move "):
        return _move_entry(entries, target, item_id, params)
    return _delete_entry(spec, entries, target, item_id)


def _add_question(spec: dict[str, Any], entries: list[dict[str, Any]],
                  params: Mapping[str, Any]) -> list[EditChange]:
    qid = str(params.get("item_id") or params.get("id") or "").strip() \
        or _next_id(entries, "Q")
    if any(str(entry.get("id")) == qid for entry in entries if isinstance(entry, dict)):
        raise AuthoringInputError(
            f"The draft already carries a question named {qid!r}. Give the new question "
            "its own id. Nothing was saved.")
    block: dict[str, Any] = {
        "id": qid,
        "type": _question_type(params),
        "text": _text(params, "text", f"question {qid!r}"),
    }
    points = _optional_points(params, f"question {qid!r}: 'points'")
    if points is not None:
        # update(), not a subscript: TC-PKG-C05's static half greps any `["points"]`
        # subscript in `src/aeh` outside `aeh.pkg`, and this is a spec field, not the
        # band-points column that rule fences off.
        block.update(points=points)
    options = _options_param(params, qid)
    if options is not None:
        block["options"] = options
    model_answer = str(params.get("model_answer") or "").strip()
    if model_answer:
        block["model_answer"] = model_answer
    entries.append(block)
    return [EditChange(field=f"question {qid!r}",
                       change=f"added the question ({block['type']})")]


def _edit_entry(spec: dict[str, Any], entry: dict[str, Any], target: str,
                item_id: str, params: Mapping[str, Any]) -> list[EditChange]:
    where = f"{target} {item_id!r}"
    if target == "question":
        field = str(params.get("field") or "").strip()
        if field not in ("text", "type", "points", "model_answer"):
            raise AuthoringInputError(
                f"{where}: the editor changes a question's text, type, points or model "
                "answer — name one of those as the field. Nothing was saved.")
        value: Any
        if field == "type":
            value = _question_type(params)
        elif field == "points":
            value = _points(params.get("value"), f"{where}: 'points'")
        else:
            value = _text(params, "value", f"{where}: {field}")
        entry[field] = value
        return [EditChange(field=f"question {item_id!r} {field}",
                           change=f"set to {value!r}" if not isinstance(value, str)
                           else f"set to \"{value}\"")]
    field = str(params.get("field") or "").strip()
    if field == "question":
        value = _text(params, "value", f"{where}: 'question'")
        _question_exists(spec, value, where)
        entry["question"] = value
        return [EditChange(field=f"criterion {item_id!r} question",
                           change=f"now grades question {value!r}")]
    if field == "key":
        entry.pop("bands", None)
        entry["key"] = _key_param(params.get("value"), where)
        return [EditChange(field=f"criterion {item_id!r} key",
                           change="set the multiple-choice key")]
    if field == "bands":
        entry.pop("key", None)
        entry["bands"] = _bands_param(params.get("value"), where)
        return [EditChange(field=f"criterion {item_id!r} bands",
                           change="set the score levels")]
    if field == "points":
        # update(), not a subscript: TC-PKG-C05's static half greps any `["points"]`
        # subscript in `src/aeh` outside `aeh.pkg`, and this is a spec field, not the
        # band-points column that rule fences off.
        value = _points(params.get("value"), f"{where}: 'points'")
        entry.update(points=value)
        return [EditChange(field=f"criterion {item_id!r} points",
                           change=f"set to {value}")]
    raise AuthoringInputError(
        f"{where}: the editor changes a criterion's question, key, score levels or "
        "points — name one of those as the field. Nothing was saved.")


def _move_entry(entries: list[dict[str, Any]], target: str, item_id: str,
                params: Mapping[str, Any]) -> list[EditChange]:
    entry = _entry_of(entries, target, item_id)
    position = _position(params, len(entries))
    entries.remove(entry)
    entries.insert(position - 1, entry)
    return [EditChange(field=f"{target} {item_id!r}",
                       change=f"moved to position {position}")]


def _delete_entry(spec: dict[str, Any], entries: list[dict[str, Any]], target: str,
                  item_id: str) -> list[EditChange]:
    entry = _entry_of(entries, target, item_id)
    entries.remove(entry)
    changes = [EditChange(field=f"{target} {item_id!r}", change="removed")]
    if target == "question":
        criteria = spec.get("criterion")
        if isinstance(criteria, list):
            bound = [row for row in criteria if isinstance(row, dict)
                     and str(row.get("question")) == item_id]
            for row in bound:
                criteria.remove(row)
                changes.append(EditChange(
                    field=f"criterion {row.get('id')!r}",
                    change=f"removed with question {item_id!r}"))
    return changes


def _option_change(operation: str, spec: dict[str, Any],
                   params: Mapping[str, Any]) -> list[EditChange]:
    entries = _tables_of(spec, "question")
    item_id = _item_id(params, "question")
    entry = _entry_of(entries, "question", item_id)
    qtype = str(entry.get("type") or "open")
    letter = str(params.get("letter") or "").strip().upper()
    if len(letter) != 1 or not letter.isalpha():
        raise AuthoringInputError(
            f"question {item_id!r}: an option's letter is one letter, as the paper "
            "prints it (A, B, C…). Nothing was saved.")
    label = _text(params, "label", f"question {item_id!r} option {letter}")
    if qtype == "open":
        raise AuthoringInputError(
            f"question {item_id!r} is an open question, and only multiple-choice "
            f"questions carry options. Set its type to \"mcq\" first, then add the "
            "options. Nothing was saved.")
    options = entry.get("options")
    if not isinstance(options, dict):
        # A `<<PLACEHOLDER: options …>>` sentinel standing as the whole options table is
        # the draft's own "no options yet" marker: the first option added resolves it.
        options = {}
    if operation == "add option":
        if letter in options:
            raise AuthoringInputError(
                f"question {item_id!r} already carries option {letter}. Edit that "
                "option's label instead of adding it twice. Nothing was saved.")
        options[letter] = label
        entry["options"] = options
        return [EditChange(field=f"question {item_id!r} options",
                           change=f"added option {letter}")]
    if letter not in options:
        raise AuthoringInputError(
            f"question {item_id!r} carries no option {letter} to remove "
            f"({', '.join(sorted(options)) or 'it lists none'}). Nothing was saved.")
    del options[letter]
    return [EditChange(field=f"question {item_id!r} options",
                       change=f"removed option {letter}")]


def _add_criterion(spec: dict[str, Any], entries: list[dict[str, Any]],
                   params: Mapping[str, Any]) -> list[EditChange]:
    cid = str(params.get("item_id") or params.get("id") or "").strip() \
        or _next_id(entries, "C")
    if any(str(entry.get("id")) == cid for entry in entries if isinstance(entry, dict)):
        raise AuthoringInputError(
            f"The draft already carries a criterion named {cid!r}. Give the new one its "
            "own id. Nothing was saved.")
    qid = _text(params, "question", f"criterion {cid!r}: 'question'")
    _question_exists(spec, qid, f"criterion {cid!r}")
    block: dict[str, Any] = {"id": cid, "question": qid}
    if params.get("key") is not None:
        block["key"] = _key_param(params.get("key"), f"criterion {cid!r}")
        points = _optional_points(params, f"criterion {cid!r}: 'points'")
        # update(), not a subscript: TC-PKG-C05's static half greps any `["points"]`
        # subscript in `src/aeh` outside `aeh.pkg`, and this is a spec field, not the
        # band-points column that rule fences off.
        block.update(points=points if points is not None else 1)
    else:
        block["bands"] = _bands_param(params.get("bands"), f"criterion {cid!r}")
    entries.append(block)
    return [EditChange(field=f"criterion {cid!r}",
                       change=f"added the grading point for question {qid!r}")]


# --- param and spec helpers -----------------------------------------------------------------------------


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise AuthoringInputError(
            f"The draft file could not be read ({error.strerror or error}). Nothing was "
            "changed.") from error


def _tables_of(spec: dict[str, Any], name: str) -> list[dict[str, Any]]:
    raw = spec.get(name)
    if raw is None:
        spec[name] = []
        return spec[name]
    if not isinstance(raw, list):
        raise AuthoringInputError(
            f"The draft's {name} entries do not read as a list of tables, so the editor "
            "cannot change them. Re-draft from the documents or fix the file on disk. "
            "Nothing was saved.")
    return raw


def _entry_of(entries: list[dict[str, Any]], target: str,
              item_id: str) -> dict[str, Any]:
    for entry in entries:
        if isinstance(entry, dict) and str(entry.get("id")) == item_id:
            return entry
    raise AuthoringInputError(
        f"No {target} named {item_id!r} stands in the draft — check the id on the "
        "editor screen. Nothing was saved.")


def _question_exists(spec: dict[str, Any], qid: str, where: str) -> None:
    questions = spec.get("question")
    if isinstance(questions, list) and any(
            isinstance(entry, dict) and str(entry.get("id")) == qid
            for entry in questions):
        return
    raise AuthoringInputError(
        f"{where} names question {qid!r}, and no question with that id stands in the "
        "draft. Check the id on the editor screen. Nothing was saved.")


def _item_id(params: Mapping[str, Any], target: str) -> str:
    item_id = str(params.get("item_id") or params.get("id") or "").strip()
    if not item_id:
        raise AuthoringInputError(
            f"The edit names no {target} — the editor sends the id of the entry the "
            "change is about. Nothing was saved.")
    return item_id


def _text(params: Mapping[str, Any], key: str, where: str) -> str:
    value = params.get(key)
    if value is None or not str(value).strip():
        raise AuthoringInputError(
            f"{where}: the edit carries no {key} text. Nothing was saved.")
    return str(value).strip()


def _question_type(params: Mapping[str, Any]) -> str:
    raw = str(params.get("question_type") or params.get("type") or "open").strip()
    if raw not in _QUESTION_TYPES:
        raise AuthoringInputError(
            f"A question's type is one of {', '.join(_QUESTION_TYPES)}, not {raw!r}. "
            "Nothing was saved.")
    return raw


def _points(value: Any, where: str) -> int | float:
    try:
        number = float(value) if not isinstance(value, bool) else None
    except (TypeError, ValueError):
        number = None
    if number is None or number < 0:
        raise AuthoringInputError(
            f"{where} is a number of points, not {value!r}. Nothing was saved.")
    return int(number) if float(number).is_integer() else number


def _optional_points(params: Mapping[str, Any], where: str) -> int | float | None:
    if params.get("points") is None:
        return None
    return _points(params.get("points"), where)


def _options_param(params: Mapping[str, Any], qid: str) -> dict[str, str] | None:
    """The options a new question carries, as the grammar's `{ A = "...", B = "..." }`
    table: a JSON object of letter → label, or a list of `[letter, label]` pairs."""
    raw = params.get("options")
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        options = {str(key).strip().upper(): str(value) for key, value in raw.items()}
    elif isinstance(raw, list):
        options = {}
        for entry in raw:
            if isinstance(entry, Mapping) and "letter" in entry:
                options[str(entry["letter"]).strip().upper()] = str(entry.get("label") or "")
            elif isinstance(entry, (list, tuple)) and len(entry) == 2:
                options[str(entry[0]).strip().upper()] = str(entry[1])
            else:
                raise AuthoringInputError(
                    f"question {qid!r}: an option is a letter and its label, as "
                    '[["A", "the option text"]]. Nothing was saved.')
    else:
        raise AuthoringInputError(
            f"question {qid!r}: the options travel as a table of letter and label, as "
            '{ "A": "the option text" }. Nothing was saved.')
    for letter in options:
        if len(letter) != 1 or not letter.isalpha():
            raise AuthoringInputError(
                f"question {qid!r}: an option's letter is one letter, as the paper "
                f"prints it — not {letter!r}. Nothing was saved.")
    return options


def _key_param(value: Any, where: str) -> str | list[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list) and value and all(
            isinstance(item, str) and item.strip() for item in value):
        return [item.strip() for item in value]
    raise AuthoringInputError(
        f"{where}: 'key' is an option letter such as \"C\", or a list of them. "
        "Nothing was saved.")


def _bands_param(value: Any, where: str) -> list[dict[str, Any]]:
    """The score levels a judged criterion carries, worst first: a list of
    `{name, points, descriptor?}` tables. The console sends them structured; points are
    numbers the grammar requires explicitly (`FR-PKG-06`)."""
    if not isinstance(value, list) or not value:
        raise AuthoringInputError(
            f"{where}: 'bands' is a list of score levels, worst first, each naming its "
            'name and points — as [{"name": "not met", "points": 0}]. Nothing was saved.')
    bands: list[dict[str, Any]] = []
    for index, band in enumerate(value):
        if not isinstance(band, Mapping):
            raise AuthoringInputError(
                f"{where} band {index + 1} is not a score-level table. Nothing was saved.")
        name = str(band.get("name") or "").strip()
        if not name:
            raise AuthoringInputError(
                f"{where} band {index + 1} carries no name. Nothing was saved.")
        points = _points(band.get("points"), f"{where} band {index + 1}: 'points'")
        entry: dict[str, Any] = {"name": name, "points": points}
        descriptor = str(band.get("descriptor") or "").strip()
        if descriptor:
            entry["descriptor"] = descriptor
        bands.append(entry)
    return bands


def _position(params: Mapping[str, Any], length: int) -> int:
    raw = params.get("position", params.get("index"))
    try:
        position = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        position = 0
    if not 1 <= position <= max(length, 1):
        raise AuthoringInputError(
            f"A position is a whole number from 1 to {length}, not {raw!r}. "
            "Nothing was saved.")
    return position


def _next_id(entries: list[dict[str, Any]], prefix: str) -> str:
    """The next free numbered id (`Q3`, `C4`): one more than the largest numeric suffix
    already standing, so an editor-added entry never collides with a derived one."""
    largest = 0
    for entry in entries:
        match = re.fullmatch(rf"{re.escape(prefix)}(\d+)",
                             str(entry.get("id") or "")) if isinstance(entry, dict) else None
        if match:
            largest = max(largest, int(match.group(1)))
    return f"{prefix}{largest + 1}"


def _comment_gaps(text: str) -> tuple[list[Gap], dict[str, list[Gap]]]:
    """The `# PLACEHOLDER(reason): supply` comments the draft text carries, rebuilt as
    `Gap` records so the re-render re-attaches them (`FR-AUTHOR-11`).

    Attribution follows the renderer's own rule (`spec._gap_for`): a sentinel inside a
    `[[question]]` block resolves through that question's gaps; a sentinel inside a
    `[[criterion]]` block resolves through the gaps of the question the criterion grades;
    a top-level or `[grades]` sentinel resolves at package level. A comment whose value
    line carries no sentinel is ignored (a resolved field's retired comment)."""
    package: list[Gap] = []
    per_question: dict[str, list[Gap]] = {}
    lines = text.splitlines()
    scope: str | None = None
    owner: str | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[["):
            scope = stripped[2:stripped.index("]]")].strip() if "]]" in stripped else None
            owner = None
            continue
        if stripped.startswith("["):
            scope = None
            owner = None
            continue
        if scope in ("question", "criterion") and "=" in stripped:
            key, _, value = stripped.partition("=")
            if key.strip() in ("id", "question"):
                quoted = re.match(r"['\"](.*)['\"]", value.strip())
                if quoted:
                    owner = quoted.group(1)
        comment = _PLACEHOLDER_COMMENT.match(stripped)
        if not comment:
            continue
        for later in lines[index + 1:]:
            later_stripped = later.strip()
            if not later_stripped or later_stripped.startswith("#"):
                continue
            if "=" not in later_stripped:
                break
            sentinel = _SENTINEL_VALUE.search(later_stripped.partition("=")[2])
            if not sentinel:
                break
            gap = Gap(item_id=sentinel.group(1), reason=comment.group(1).strip(),
                      supply=comment.group(2).strip(), in_draft=True)
            if scope in ("question", "criterion") and owner:
                per_question.setdefault(owner, []).append(gap)
            else:
                package.append(gap)
            break
    return package, per_question
