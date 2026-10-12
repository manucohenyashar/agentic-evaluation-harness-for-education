"""Draft assembly: the in-memory spec the steps' accepted proposals become, and the draft
TOML it renders to — two artifacts, nothing else (FR-AUTHOR-14, ADR-43).

The assembly is deterministic by construction: questions in paper order, criteria in
question order with derived ids, every gap either a sentinel in the draft (a required field
the build would refuse the draft without, `FR-AUTHOR-11`) or an omission the report names
(an optional field the review may add). The renderer follows the spec export's house style
(`FR-PKG-27`'s vocabulary) — the same `aeh package build --spec` grammar, top-level keys
above the first table, `[grades]` last — so a completed draft needs no reformatting to build.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The spec-export rendering helpers, imported for their behaviour, not their ownership:
# the draft renders in the same house grammar `aeh package build` reads (`FR-PKG-27`), so
# duplicating the three private helpers would let the two renderers drift. This does load
# `M-PIPE` with `M-AUTHOR` at import time — the design's downstream-only note describes the
# call direction, not an import-free boundary (disclosed at the #690 review; the one line
# that would change is the comment in `validation._plan_issues`).
from aeh.pipeline.spec_export import _assign, _toml_key, _toml_str

from .rubric import aspect_present_points

#: The sentinel the draft carries for a field it could not determine (`FR-AUTHOR-11`):
#: `<<PLACEHOLDER: <field>>>`, with the `# PLACEHOLDER(<reason>):` comment above it. The
#: field name is the review item id (`PLACEHOLDER_FIELDS_AS_ITEM_IDS`'s disclosure): the
#: scripted review answers name exactly this string.
def sentinel(item_id: str) -> str:
    return f"<<PLACEHOLDER: {item_id}>>"


@dataclass(frozen=True)
class Gap:
    """One field the documents did not determine: its review item id, why it is missing and
    what the teacher must supply — and whether it stands in the draft (a required field's
    sentinel) or is named only in the report (an optional field, omitted)."""

    item_id: str          # the sentinel's field — the review answer's item id
    reason: str           # why the field is missing
    supply: str           # what the teacher must supply
    in_draft: bool        # True: the sentinel stands in the draft; False: omitted, report-only


@dataclass
class Assembly:
    """The draft's assembled state: the spec dict, its gaps, and per-question bookkeeping."""

    package_id: str
    spec: dict[str, Any]
    gaps: list[Gap] = field(default_factory=list)
    #: question id → final item status ("resolved" | "derived" | "placeholder" | "unresolved")
    statuses: dict[str, str] = field(default_factory=dict)
    #: question id → the criterion/gap details the report's Items section needs
    details: dict[str, str] = field(default_factory=dict)
    #: question id → the in-draft sentinel gaps standing in that question's own content (its
    #: block and its criterion lines). Shared field-level ids ("key", "model_answer") do not
    #: carry the question id, so attribution is recorded here as the gap is appended; the
    #: per-question status reads it instead of matching suffixes, and the renderer resolves
    #: each occurrence's reason comment through it.
    question_gaps: dict[str, list[Gap]] = field(default_factory=dict)

    @property
    def placeholder_count(self) -> int:
        """The named gaps — the sentinel gaps in the draft plus the report-only omissions.
        `approved_by` is the sign-off slot, never counted (`AF-01` expects zero)."""
        return sum(1 for gap in self.gaps if gap.item_id != "approved_by")


def assemble(package_id: str, questions: list[dict[str, Any]],
             rubric_values: dict[str, dict[str, Any] | None],
             rubric_unresolved: dict[str, tuple[str, ...]],
             derived_keys: dict[str, list[str]],
             grades: dict[str, float | None]) -> Assembly:
    """The steps' outputs, assembled into the draft's spec dict and its gap list.

    `questions` are the inventory's normalized proposals (paper order); `rubric_values` maps
    question id → the accepted rubric proposal (or `None`, a clean gap); `rubric_unresolved`
    maps question id → the failure reasons of a rubric the chain could not make pass;
    `derived_keys` maps mcq question id → the key the ANSWERS pre-pass derived; `grades` is
    the grades step's boundary table (or `None`, the never-invent gap).
    """
    assembly = Assembly(package_id=package_id, spec={})
    spec: dict[str, Any] = {"package": package_id}
    spec["approved_by"] = sentinel("approved_by")
    assembly.gaps.append(Gap(
        item_id="approved_by",
        reason="the teacher who approves the questions and rubric names themselves at review",
        supply="your name, as the approving teacher",
        in_draft=True))

    criteria: list[dict[str, Any]] = []
    for question in questions:
        rubric = rubric_values.get(question["id"])
        _question_block(assembly, spec, question, rubric)
        _criterion_blocks(assembly, criteria, question, rubric,
                          rubric_unresolved.get(question["id"], ()),
                          derived_keys.get(question["id"]))
        _status(assembly, question, rubric,
                rubric_unresolved.get(question["id"], ()),
                derived_keys.get(question["id"]))
    spec["criterion"] = criteria
    if grades:
        # A partial table renders its stated boundaries and a per-grade sentinel where the
        # document names a grade but states no boundary — stated derived, missing named
        # (TC-AUTHOR-11's partial case).
        spec["grades"] = dict(grades)
        for name, floor in grades.items():
            if floor is None:
                assembly.gaps.append(Gap(
                    item_id=f"grades {name}",
                    reason="the document names the grade but states no boundary for it, and "
                           "a boundary is never invented (FR-AUTHOR-08)",
                    supply=f"the minimum mark or percentage for grade {name}",
                    in_draft=True))
    else:
        # The whole-table placeholder: a top-level sentinel string, which `plan_package`
        # refuses as a non-table — exactly right, the draft is not complete (FR-AUTHOR-08).
        spec["grades"] = sentinel("grades")
        assembly.gaps.append(Gap(
            item_id="grades",
            reason="the documents state no grade boundaries, and a boundary is never "
                   "invented (FR-AUTHOR-08)",
            supply="the grade boundaries, as grade name and minimum mark or percentage",
            in_draft=True))
    assembly.spec = spec
    return assembly


def _attribute(assembly: Assembly, qid: str, gap: Gap) -> None:
    """Record that an in-draft sentinel gap stands in question `qid`'s own content."""
    assembly.question_gaps.setdefault(qid, []).append(gap)


def _question_block(assembly: Assembly, spec: dict[str, Any], question: dict[str, Any],
                    rubric: dict[str, Any] | None) -> None:
    """One `[[question]]`, with its required gaps as sentinels and its optional gaps as
    named omissions."""
    qid = question["id"]
    block: dict[str, Any] = {"id": qid}
    block["type"] = question["type"] if question.get("type") else sentinel(f"type {qid}")
    if question.get("type") is None:
        gap = Gap(
            item_id=f"type {qid}", reason="the documents do not show whether the question "
                                          "is multiple choice",
            supply=f"the question {qid}'s type: \"mcq\" with its options, or \"open\"",
            in_draft=True)
        assembly.gaps.append(gap)
        _attribute(assembly, qid, gap)
    if question.get("points") is not None:
        block["points"] = question["points"]
    else:
        assembly.gaps.append(Gap(
            item_id=f"points {qid}", reason="the paper states no marks for the question",
            supply=f"the marks question {qid} is worth",
            in_draft=False))
    if question.get("text"):
        block["text"] = question["text"]
    else:
        block["text"] = sentinel(f"text {qid}")
        gap = Gap(
            item_id=f"text {qid}", reason="no readable question text was extracted for it",
            supply=f"question {qid}'s text, as the paper states it",
            in_draft=True)
        assembly.gaps.append(gap)
        _attribute(assembly, qid, gap)
    if question.get("options"):
        block["options"] = dict(question["options"])
    elif question.get("type") == "mcq":
        block["options"] = sentinel(f"options {qid}")
        gap = Gap(
            item_id=f"options {qid}", reason="no lettered options were extracted for the "
                                             "multiple-choice question",
            supply=f"question {qid}'s options, as option letter and label",
            in_draft=True)
        assembly.gaps.append(gap)
        _attribute(assembly, qid, gap)
    if question.get("model_answer"):
        block["model_answer"] = question["model_answer"]
    elif question.get("type") != "mcq" and not _rubric_describes_answer(rubric):
        # An unstated model answer is a named placeholder, its sentinel standing as the
        # field's value (`FR-AUTHOR-11`: the sentinel is the field's value) — except where
        # the rubric's own provenance already describes what a good answer is: a
        # `general` criterion carries the teacher's grading words verbatim, and an
        # `evidence_sum` composite's aspect descriptors carry the evidence conditions
        # (`AF-04`/`AF-05` resolve without the gap; `AF-07`'s plain bands leave it standing).
        block["model_answer"] = sentinel("model_answer")
        gap = Gap(
            item_id="model_answer",
            reason="the documents state no expected solution for the question",
            supply=f"question {qid}'s expected solution, for the judge's reference",
            in_draft=True)
        assembly.gaps.append(gap)
        _attribute(assembly, qid, gap)
    spec.setdefault("question", []).append(block)


def _rubric_describes_answer(rubric: dict[str, Any] | None) -> bool:
    """Whether the rubric's own provenance already describes what a good answer looks like."""
    return bool(rubric and (rubric.get("derivation_description") or rubric.get("aspects")))


def _criterion_blocks(assembly: Assembly, criteria: list[dict[str, Any]],
                      question: dict[str, Any], rubric: dict[str, Any] | None,
                      failures: tuple[str, ...], derived_key: list[str] | None) -> None:
    """The question's rubric line(s): an mcq key line, a judged line, or an evidence_sum
    composite with its aspects — or the placeholder sentinel when no usable proposal
    stands (`FR-AUTHOR-11`)."""
    qid = question["id"]
    qtype = question.get("type")
    options = question.get("options") or {}
    wants_key = qtype in ("mcq", "mixed")
    key = derived_key or (rubric or {}).get("key")

    if wants_key:
        if key:
            letters = list(key)
            # FR-AUTHOR-07 reads singular ("a `key` drawn from that question's declared
            # options", "key ∈ options"), and the build vocabulary accepts the letter or a
            # list of them (plan_package): a one-letter key renders as the option letter
            # itself, a list only when the documents state several correct letters.
            key_value = letters[0] if len(letters) == 1 else letters
            line: dict[str, Any] = {"id": f"C_{qid}_key", "question": qid, "key": key_value}
            if question.get("points") is not None:
                line["points"] = question["points"]
            criteria.append(line)
        else:
            criteria.append({"id": f"C_{qid}_key", "question": qid,
                             "key": sentinel("key")})
            gap = Gap(
                item_id="key",
                reason="the answer key is not stated in the documents, and a key is never "
                       "guessed",
                supply=f"question {qid}'s correct option letter(s)",
                in_draft=True)
            assembly.gaps.append(gap)
            _attribute(assembly, qid, gap)
        if qtype == "mcq":
            return  # a pure mcq question carries no judged line

    bands = (rubric or {}).get("bands")
    aspects = (rubric or {}).get("aspects")
    derivation = (rubric or {}).get("derivation_description")
    if bands:
        line = {"id": f"C_{qid}", "question": qid,
                "bands": [dict(band) for band in bands]}
        if derivation:
            line["score_method"] = "general"
            line["derivation_description"] = derivation
        criteria.append(line)
        return
    if aspects:
        points = question.get("points")
        composite = float(points) if isinstance(points, (int, float)) else 2.0
        present = aspect_present_points(aspects, composite)
        criteria.append({"id": f"C_{qid}", "question": qid, "score_method": "evidence_sum",
                         "points": composite})
        for index, aspect in enumerate(aspects, start=1):
            criteria.append({
                "id": f"C_{qid}_aspect{index}", "question": qid, "component_of": f"C_{qid}",
                "bands": [{"name": "absent", "points": 0},
                          {"name": "present", "points": present[index - 1],
                           "descriptor": aspect["description"]}]})
        return
    if failures:
        reason = ("no model in the chain produced a rubric that passed the structural "
                  "checks: " + "; ".join(failures))
    else:
        reason = "the documents state no grading description for the question"
    criteria.append({"id": f"C_{qid}", "question": qid, "bands": sentinel(f"criterion {qid}")})
    gap = Gap(
        item_id=f"criterion {qid}", reason=reason,
        supply=f"the grading description for question {qid}, as bands or an evidence "
               "checklist the module can map",
        in_draft=True)
    assembly.gaps.append(gap)
    _attribute(assembly, qid, gap)


def _status(assembly: Assembly, question: dict[str, Any], rubric: dict[str, Any] | None,
            failures: tuple[str, ...], derived_key: list[str] | None) -> None:
    """The question's final item status: `unresolved` when the chain could not make a rubric
    pass (flagged first in the report), `derived` when the deterministic ANSWERS pre-pass
    supplied the key and nothing else is missing, `placeholder` when a named gap stands,
    `resolved` otherwise."""
    qid = question["id"]
    if failures:
        assembly.statuses[qid] = "unresolved"
        assembly.details[qid] = "no rubric proposal passed the structural checks"
        return
    # The question's own in-draft sentinels were attributed as they were appended (shared
    # field-level ids do not carry the question id); report-only omissions still carry it.
    gaps = assembly.question_gaps.get(qid, [])
    optional = [gap.item_id for gap in assembly.gaps
                if not gap.in_draft and gap.item_id.endswith(f" {qid}")]
    if derived_key and not gaps and not optional:
        assembly.statuses[qid] = "derived"
        assembly.details[qid] = "the answer key was derived from the documents' stated answers"
        return
    if gaps or optional:
        assembly.statuses[qid] = "placeholder"
        assembly.details[qid] = "; ".join(
            (*(gap.item_id for gap in gaps), *optional))
        return
    assembly.statuses[qid] = "resolved"
    assembly.details[qid] = "every field determined from the documents"


# --- the draft TOML ------------------------------------------------------------------------------


_DRAFT_HEADER = (
    "# Package spec — DRAFT, generated by `aeh author draft` (M-AUTHOR, ADR-43).",
    "# Not a published package: complete it with `aeh author review`, then build it with",
    "# `aeh package build --spec <this file>`.",
)


def render_draft(assembly: Assembly) -> str:
    """The draft TOML: the spec export's grammar and house style, with a
    `# PLACEHOLDER(<reason>): <supply>` comment above every sentinel line (`FR-AUTHOR-11`) —
    the reason the build's refusal reads when the teacher builds too early (`FR-PKG-28`)."""
    spec = assembly.spec

    def comment(qid: str | None, value: Any) -> list[str]:
        gap = _gap_for(assembly, qid, value)
        if gap is None:
            return []
        return [f"# PLACEHOLDER({gap.reason}): {gap.supply}"]

    lines: list[str] = [*_DRAFT_HEADER, ""]
    for key, value in spec.items():
        if key in ("question", "criterion"):
            continue
        if key == "grades" and isinstance(value, dict):
            continue  # a real boundary table renders as its [grades] table, after the tables
        lines.extend(comment(None, value))
        lines.append(_assign(key, value))
    for block in spec.get("question", []):
        lines.append("")
        lines.append("[[question]]")
        for key, value in block.items():
            lines.extend(comment(block.get("id"), value))
            lines.append(_assign(key, value) if not isinstance(value, dict)
                         else _options_line(value))
    for block in spec.get("criterion", []):
        lines.append("")
        lines.append("[[criterion]]")
        for key, value in block.items():
            if key == "bands" and isinstance(value, list):
                lines.append("bands = [" + ", ".join(_band_entry(band) for band in value)
                             + "]")
            else:
                lines.extend(comment(block.get("question"), value))
                lines.append(_assign(key, value))
    grades = spec.get("grades")
    if isinstance(grades, dict):
        lines.append("")
        lines.append("[grades]")
        for name, floor in grades.items():
            if floor is None:
                item_id = f"grades {name}"
                lines.extend(comment(None, sentinel(item_id)))
                lines.append(f"{_toml_key(name)} = {_toml_str(sentinel(item_id))}")
            else:
                lines.append(f"{_toml_key(name)} = {floor}")
    lines.append("")
    return "\n".join(lines)


def _is_sentinel(value: Any) -> bool:
    """Whether a field's value is a sentinel standing for an undetermined field."""
    return (isinstance(value, str) and value.startswith("<<PLACEHOLDER:")
            and value.endswith(">>"))


def _gap_for(assembly: Assembly, qid: str | None, value: Any) -> Gap | None:
    """The gap a sentinel value stands for — `None` when the value carries no sentinel.

    Shared field-level ids ("key", "model_answer") repeat per question, so a line inside a
    question's content resolves through that question's attributed gaps: each occurrence's
    comment names its own question. A package-level line (`approved_by`, `grades`) resolves
    by the item id the sentinel names."""
    if not _is_sentinel(value):
        return None
    item_id = value[len("<<PLACEHOLDER: "):-len(">>")]
    if qid is not None:
        for gap in assembly.question_gaps.get(qid, ()):
            if gap.item_id == item_id:
                return gap
        return None
    for gap in assembly.gaps:
        if gap.item_id == item_id:
            return gap
    return None


def _options_line(options: dict[str, str]) -> str:
    return ("options = { "
            + ", ".join(f"{_toml_str(k)} = {_toml_str(v)}" for k, v in options.items())
            + " }")


def _band_entry(band: dict[str, Any]) -> str:
    fields = [f"name = {_toml_str(band['name'])}", f"points = {band['points']}"]
    if band.get("descriptor"):
        fields.append(f"descriptor = {_toml_str(band['descriptor'])}")
    return "{ " + ", ".join(fields) + " }"