"""The package vocabulary: question types, evaluation modes and provenance words."""

from __future__ import annotations

import logging
from typing import Any

from .errors import PackageError


#: A package version's id: an opaque string the catalog mints.
PackageVersionId = str


#: Module observability (`CT-PKG-16`): every export/import logged with version,
#: provenance and destination; every `SchemaLockViolation` at WARN.
LOGGER = logging.getLogger("aeh.pkg")


#: The question-type vocabulary the `question` table's CHECK enforces (`FR-SETUP-01`,
#: HLD §9.5). `open` — a ruled response area with nothing to circle; `mcq` — an
#: enumerated option set; `mixed` — both parts on one question. The list lives here, at
#: the data layer whose CHECK enforces it; `M-SETUP` reads it from this module rather
#: than carrying a second copy that could drift from the schema.
QUESTION_TYPES: tuple[str, ...] = ("open", "mcq", "mixed")


#: The two modes a criterion may declare (`FR-PKG-22`). `judged` runs the panel;
#: `deterministic` is scored by rule (§7.8).
EVALUATION_MODES: tuple[str, ...] = ("judged", "deterministic")


def default_evaluation_mode(kind: str | None) -> str:
    """The evaluation mode a criterion gets when its author does not choose one (FR-PKG-22).

    This is the ONE place the old `kind='mcq'` equivalence still lives, and it lives here
    deliberately: choosing a default from the shape is a WRITER's convenience, and every
    reader must consult the column instead (`FR-ORCH-35` — no consumer may test
    `kind = 'mcq'`, because a package is entitled to declare a judged multiple-choice
    criterion and a reader that infers the mode makes that package unrepresentable).

    The default is not symmetric in cost. A criterion wrongly marked `judged` spends judge
    calls on something a rule could have scored; one wrongly marked `deterministic` skips
    the panel silently and reports a score nobody weighed. So everything that is not the
    declared deterministic shape defaults to doing the work.
    """
    return "deterministic" if kind == "mcq" else "judged"


def _criterion_field(criterion: Any, name: str) -> Any:
    """One field of a criterion payload, whatever mapping-like shape it arrives in."""
    try:
        return criterion[name]
    except (KeyError, IndexError, TypeError):
        return None


def _declared_evaluation_mode(criterion: Any) -> str:
    """The evaluation mode a criterion payload declares, or its default. A value outside the
    allowed list is refused here, rather than left for the database to reject with an error that
    names no requirement."""
    declared = _criterion_field(criterion, "evaluation_mode")
    if declared is None:
        return default_evaluation_mode(_criterion_field(criterion, "kind"))
    if declared not in EVALUATION_MODES:
        raise PackageError(
            f"criterion evaluation_mode {declared!r} is not one of {EVALUATION_MODES} "
            "(FR-PKG-22). The mode is a declared vocabulary member, not free text."
        )
    return str(declared)


#: The exemplar provenance vocabulary (ADR-4). `real_verbatim` is the canonical value
#: for a real student response used verbatim — the export gate's one test.
PROVENANCE_VOCABULARY: tuple[str, ...] = ("synthetic", "paraphrased", "real_verbatim")


#: The closed rubric-method vocabulary (`FR-PKG-24`, ADR-39), in the order the design
#: states it. The column's CHECK (Package migration 15) is the database backstop; this
#: tuple is what refusals name. Checklist and single-point rubrics are NOT members:
#: they are `evidence_sum` and `bands` respectively, and the set stays closed.
SCORE_METHODS: tuple[str, ...] = ("bands", "evidence_sum", "general")

#: Who chose a criterion's scoring model (`FR-PKG-30`, migration P3): the spec named it
#: (`declared`), FR-PKG-29's structural rule took it (`default`), or the teacher confirmed or
#: changed it on the review screen (`teacher`, the one source with a confirmation time). The
#: column's CHECK is the database backstop; this tuple is what refusals name.
SCORING_MODEL_SOURCES: tuple[str, ...] = ("declared", "default", "teacher")
DECLARED_SOURCE = "declared"
DEFAULT_SOURCE = "default"
TEACHER_SOURCE = "teacher"


def declared_scoring_model_source(source: str, confirmed_at: str | None,
                                  criterion_id: str) -> str:
    """The source a criterion write records, refused by name when outside the closed set or
    when its confirmation time disagrees with it: a `teacher` source carries the time the
    teacher confirmed it, and no other source has one (FR-PKG-30)."""
    if source not in SCORING_MODEL_SOURCES:
        raise PackageError(
            f"criterion {criterion_id!r} records scoring_model_source {source!r}, which is "
            f"not one of the closed set {{{', '.join(SCORING_MODEL_SOURCES)}}} (FR-PKG-30)."
        )
    if (source == TEACHER_SOURCE) != bool(confirmed_at):
        raise PackageError(
            f"criterion {criterion_id!r}: scoring_model_confirmed_at is recorded exactly when "
            "the teacher confirmed the model (scoring_model_source 'teacher') (FR-PKG-30)."
        )
    return source


#: A criterion that declares no method is a `bands` criterion — the column default, and
#: the only method every package before migration 15 could express.
DEFAULT_SCORE_METHOD = "bands"


def declared_score_method(score_method: str | None, criterion_id: str) -> str:
    """The method a criterion write declares, or the default. Membership is exact — no case
    folding, no trimming — so `BANDS` or `""` is refused here, by name, rather than by the
    column's CHECK with a bare IntegrityError that names no requirement."""
    if score_method is None:
        return DEFAULT_SCORE_METHOD
    if score_method not in SCORE_METHODS:
        raise PackageError(
            f"criterion {criterion_id!r} declares score_method {score_method!r}, which is "
            f"not one of the closed set {{{', '.join(SCORE_METHODS)}}} (FR-PKG-24). A "
            "checklist is evidence_sum and a single-point rubric is bands; no other "
            "method exists."
        )
    return score_method
