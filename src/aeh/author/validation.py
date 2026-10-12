"""Draft validation: the structural rules of `M-PIPE` plus the build-time rules of `M-PKG`,
wrapped as a report of `DraftIssue`s instead of exceptions (FR-AUTHOR-10).

`plan_package` is the authority on what a package spec may say — it is the same gate the
build path runs a draft through — and `M-PKG` adds the rules the build enforces later, at
store/publish time, which `plan_package` does not carry: the band-set rules (`FR-PKG-06`:
even count 2..6, ordinals contiguous, points non-decreasing), the composite-shape rule
(`CT-PKG-21`/`FR-JUDGE-38`: an `evidence_sum` composite needs at least one aspect naming
it) and the grade-boundary rules (`FR-PKG-16`: a named label for every boundary, finite
floors, no two grades sharing one cut).
`validate_draft` runs both layers over a draft **before** review, so a teacher is told
every structural problem at once, in the report, rather than meeting them one `PackageSpecError`
at a time. It never raises for a bad spec: it returns issues, and an empty list means the
draft is structurally sound. Sentinel detection is folded in here too — a `<<PLACEHOLDER: …>>`
left in a field is the one issue a structurally perfect draft can still carry.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The sentinel prefix the draft vocabulary writes (`<<PLACEHOLDER: <reason>>>`).
PLACEHOLDER_PREFIX = "<<PLACEHOLDER:"

#: `plan_package` requires a `packages_dir` to collision-check the id against. Validation
#: must be pure — reading nothing, writing nothing — so it passes a directory that cannot
#: exist; `check_package_id` then performs only the shape check (its scan is guarded by
#: the directory's existence).
_NO_SUCH_PACKAGES_DIR = Path("Z:") / "__aeh_validate_draft_nonexistent__"


@dataclass(frozen=True)
class DraftIssue:
    """One problem with a draft: the field that carries it, and what is wrong.

    `field` is a human-readable locator (e.g. ``question 'Q3' model_answer``,
    ``criterion 'Q4' bands``, ``grades``) — the same vocabulary the report and the
    review answers use, so a teacher can find the spot without parsing TOML paths.
    """

    field: str
    message: str


def validate_draft(spec: Mapping[str, Any]) -> list[DraftIssue]:
    """Every structural problem with a draft spec, as issues; an empty list is a sound draft.

    The two layers, in the design's order:

    1. `plan_package`'s full structural check (`FR-AUTHOR-10`), caught and converted — one
       issue per refusal, never an exception, because a teacher reads issues one by one;
    2. `M-PKG`'s build-time rules, which `plan_package` does not carry: the band-set rules
       (`FR-PKG-06` — an even count of 2..6 bands and points that never decrease down the
       worst-first list), the composite-shape rule (`CT-PKG-21` — an `evidence_sum`
       composite needs at least one aspect naming it) and the grade-boundary rules
       (`FR-PKG-16` — a named label per boundary, finite floors, no two grades sharing
       one cut);
    3. the sentinel sweep: any `<<PLACEHOLDER: …>>` still standing, field by field —
       except `approved_by`, whose sentinel is the sign-off slot by design (the teacher
       approves the draft there; it is never counted as an unresolved placeholder).
    """
    if not isinstance(spec, Mapping):
        return [DraftIssue("spec", "the draft must be a table of fields, not "
                           f"{type(spec).__name__}.")]
    issues: list[DraftIssue] = []
    issues.extend(_plan_issues(spec))
    issues.extend(_band_issues(spec))
    issues.extend(_composite_issues(spec))
    issues.extend(_grades_issues(spec))
    issues.extend(_placeholder_issues(spec))
    return issues


def _plan_issues(spec: Mapping[str, Any]) -> list[DraftIssue]:
    """`plan_package`'s refusals, converted. The import is lazy as a guard, not as
    isolation — `spec.py` already pulls `aeh.pipeline.spec_export`'s rendering helpers at
    module import, so `M-PIPE` loads with `M-AUTHOR` (the design's downstream-only note
    describes the call direction — M-PIPE registers and calls this module — not an
    import-free boundary: the draft renders in the spec-export grammar the build reads).
    The lazy `plan_package` keeps the heavier build-path import off module load until a
    draft is actually validated."""
    from aeh.pipeline.packages import PackageSpecError, plan_package
    try:
        plan_package(spec, _NO_SUCH_PACKAGES_DIR)
    except PackageSpecError as error:
        message = str(error)
        return [DraftIssue(_field_of(message), message)]
    return []


def _field_of(message: str) -> str:
    """The field a `PackageSpecError` message names, when its shape lets us find one —
    messages lead with a locator such as ``question 'Q3':`` or ``criterion 'C2':``."""
    for marker in ("question ", "criterion ", "'grades'", "package"):
        index = message.find(marker)
        if index == 0 or (index > 0 and message[index - 1] in " ("):
            head = message[index:].split(":", 1)[0].strip(" .")
            return head or "spec"
    return "spec"


def _band_issues(spec: Mapping[str, Any]) -> list[DraftIssue]:
    """`FR-PKG-06`'s two band rules, over every criterion that declares bands — the checks
    `M-PKG` runs at store time, run here so the draft never reaches a build that refuses it.
    Ordinals are the list order (worst first), so contiguity is structural; what can be
    wrong is the count and the points ladder."""
    issues: list[DraftIssue] = []
    for table in _tables(spec, "criterion"):
        cid = table.get("id")
        where = f"criterion {cid!r} bands" if cid else "criterion bands"
        bands = table.get("bands")
        if bands is None:
            continue
        if not isinstance(bands, list) or not all(isinstance(b, Mapping) for b in bands):
            continue  # a type failure plan_package already reported
        count = len(bands)
        if count < 2 or count > 6 or count % 2 != 0:
            issues.append(DraftIssue(
                where, f"a band set of {count} bands is outside 2..6 or odd (FR-PKG-06). "
                       "The even count removes the safe middle band a hesitant judge "
                       "retreats to."))
            continue
        points: list[float] = []
        malformed = False
        for index, band in enumerate(bands):
            value = band.get("points")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                issues.append(DraftIssue(
                    f"{where} [{index}]", f"band {index} has no numeric 'points'; every "
                    "band declares the points it awards (a best-first list would "
                    "otherwise score backwards)."))
                malformed = True
                continue
            points.append(float(value))
        if malformed:
            continue
        if any(later < earlier for earlier, later in zip(points, points[1:])):
            issues.append(DraftIssue(
                where, f"the band points {points} are not non-decreasing down the "
                       "worst-first list (FR-PKG-06): M-AGG and M-GRADE assume the "
                       "monotone band-to-points mapping."))
    return issues


def _composite_issues(spec: Mapping[str, Any]) -> list[DraftIssue]:
    """The composite-shape rule the build enforces at publish time (`_composite_problems`,
    `CT-PKG-21`/`FR-JUDGE-38`): an `evidence_sum` criterion is a grouping record — it needs
    at least one aspect criterion whose `component_of` names it. `plan_package` checks the
    aspects' side (exactly two bands naming an `evidence_sum` line) but nothing demands the
    composite be named, so the check lives here. Excluded from the scan: the composite's own
    table (a `component_of` on a composite never counts as an aspect) and every other
    `evidence_sum` table — the build stores `component_of` only on judged lines, so a
    composite naming another composite leaves both unnamed."""
    issues: list[DraftIssue] = []
    criteria = _tables(spec, "criterion")
    for table in criteria:
        if table.get("score_method") != "evidence_sum":
            continue
        cid = table.get("id")
        where = f"criterion {cid!r}" if cid else "criterion"
        if not any(other is not table and other.get("score_method") != "evidence_sum"
                   and other.get("component_of") == cid for other in criteria):
            issues.append(DraftIssue(
                where, f"{where} has no aspect criteria; it needs at least one 2-band "
                       "aspect whose component_of names it (FR-JUDGE-38). A composite "
                       "carries no bands — its aspects do."))
    return issues


def _grades_issues(spec: Mapping[str, Any]) -> list[DraftIssue]:
    """The grade-boundary rules the build enforces when it sets the table (`set_boundaries`,
    `FR-PKG-16`): every boundary names its grade, floors are finite, and no two grades share
    one cut. `plan_package` only checks each value is a number, so these are wrapped here.
    Non-numeric values are not this sweep's — `plan_package` refuses them — and a sentinel
    is the placeholder sweep's finding."""
    issues: list[DraftIssue] = []
    grades = spec.get("grades")
    if not isinstance(grades, Mapping):
        return []  # a non-table (or a whole-table sentinel) `plan_package` already reported
    floors: list[float] = []
    for name, value in grades.items():
        if not name:
            issues.append(DraftIssue(
                "grades", "a boundary table names each grade (FR-PKG-16) — an empty label "
                          "resolves to nothing."))
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            floor = float(value)
            if not math.isfinite(floor):
                issues.append(DraftIssue(
                    f"grades {name!r}", "boundary floors are finite scaled scores "
                                        "(FR-PKG-16)."))
                continue
            floors.append(floor)
    if len(set(floors)) != len(floors):
        issues.append(DraftIssue(
            "grades", f"duplicate scaled floors {floors} — two grades sharing one cut is "
                      "an ambiguous resolution (FR-PKG-16)."))
    return issues


def _placeholder_issues(spec: Mapping[str, Any]) -> list[DraftIssue]:
    """Every standing sentinel, field by field — the review queue's worklist."""
    issues: list[DraftIssue] = []
    for key, value in spec.items():
        if key == "approved_by":
            continue  # the sign-off slot: a sentinel there is by design, not a gap
        if _is_placeholder(value):
            issues.append(DraftIssue(str(key), f"{key} still holds a placeholder "
                                              f"sentinel: {value}"))
        elif key == "grades":
            issues.extend(_grades_placeholders(value))
    for group, label in (("question", "question"), ("criterion", "criterion")):
        for table in _tables(spec, group):
            issues.extend(_table_placeholders(table, label))
    return issues


def _grades_placeholders(grades: Any) -> list[DraftIssue]:
    """Placeholder grades: either the whole-table sentinel (a top-level string, which
    `plan_package` refuses as a non-table) or per-question sentinels inside the table."""
    if _is_placeholder(grades):
        return [DraftIssue("grades", f"the grades table is still a placeholder: {grades}")]
    if not isinstance(grades, Mapping):
        return []  # a type failure plan_package already reported
    issues: list[DraftIssue] = []
    for qid, value in grades.items():
        if _is_placeholder(value):
            issues.append(DraftIssue(f"grades {qid!r}", f"the grade for question {qid!r} "
                                                       f"is still a placeholder: {value}"))
    return issues


def _table_placeholders(table: Mapping[str, Any], label: str) -> list[DraftIssue]:
    """Sentinels inside one question or criterion table, at any depth — including inside
    band entries, where a placeholder description is exactly what a partial rubric carries."""
    issues: list[DraftIssue] = []
    name = table.get("id")
    where = f"{label} {name!r}" if name else label

    def walk(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                walk(item, f"{path} {key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path} [{index}]")
        elif _is_placeholder(value):
            issues.append(DraftIssue(path, f"{path} still holds a placeholder sentinel: "
                                           f"{value}"))

    for key, value in table.items():
        walk(value, f"{where} {key}")
    return issues


def _is_placeholder(value: Any) -> bool:
    """Whole-value sentinel detection. Disclosed residual (#693's landing audit): the
    build's `FR-PKG-28` refusal is a substring-level scan of the spec *file*, so a sentinel
    embedded mid-string inside a longer legal value would be refused by the build but pass
    this whole-value sweep — a shape the shipped proposal path never emits, since every
    sentinel it writes is the field's whole value."""
    return isinstance(value, str) and value.startswith(PLACEHOLDER_PREFIX)


def _tables(spec: Mapping[str, Any], name: str) -> list[Mapping[str, Any]]:
    """The `[[name]]` arrays of tables, tolerating a malformed entry (`plan_package`
    reports the type failure; the band and placeholder sweeps must not crash on it)."""
    raw = spec.get(name, [])
    if not isinstance(raw, list):
        return []
    return [table for table in raw if isinstance(table, Mapping)]