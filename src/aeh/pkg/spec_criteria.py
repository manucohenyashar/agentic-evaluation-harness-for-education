"""Writing a checked package spec's rubric lines into a draft version (live-test blocker B5).

`aeh package build` (`aeh.pipeline.packages`) reads and checks the operator's spec — which since
`FR-PKG-27` is a system-emitted export, never a teacher-authored file — and the rubric lines are
written here, on the package side, because a rubric line's scoring model and method are the
package's declarations (`CT-SETUP-05`, `CT-AGG-09`). Every rule `M-PKG` enforces still raises
from the write that breaks it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

#: The scoring model a multiple-choice line is stored with (a key lookup is one atomic check).
MCQ_SCORING = "atomic"
#: FR-PKG-29's two outcomes for a judged line that declares no model: a presence check by
#: construction (an `evidence_sum` aspect, or any two-band line) is atomic; every other judged
#: line is an overall judgement.
ATOMIC_SCORING = "atomic"
JUDGED_SCORING = "holistic"

#: A keyed line declares a two-band set (incorrect / correct), as an aspect criterion does.
ASPECT_BAND_COUNT = 2

#: The `setup_step_record` row naming the lines that took FR-PKG-29's default rather than a
#: declared model (FR-SETUP-14: a default taken is never indistinguishable from a choice).
#: Written for every spec-built version with a judged line; `declared` when no line defaulted.
SCORING_DEFAULT_STEP = "scoring_model"
SCORING_DEFAULT_STATUS = "default_taken"
SCORING_DECLARED_STATUS = "declared"


def default_scoring_model(*, score_method: str | None, band_count: int | None,
                          component_of: str | None) -> str:
    """The scoring model a judged line takes when it declares none (FR-PKG-29, ADR-55).

    `atomic` for an aspect of an `evidence_sum` composite and for any line whose band set has
    exactly two bands; `holistic` for every other `bands` or `general` line. The composite
    itself (no bands, graded through its aspects) is outside the rule and keeps `holistic`, the
    value it always stored."""
    if score_method == "evidence_sum":
        return JUDGED_SCORING
    if component_of is not None or band_count == ASPECT_BAND_COUNT:
        return ATOMIC_SCORING
    return JUDGED_SCORING


def draft_line_scoring(line: Mapping[str, Any]) -> dict[str, Any] | None:
    """A draft rubric line's model as publication will set it (FR-UI-37): `{"scoring": model,
    "chosen_automatically": bool}` — the declared `scoring` when the line names one, else
    FR-PKG-29's structural default, decided by the same rule `_scoring_for` applies at the
    write, so the review screen cannot show a model the publish then contradicts.

    None for a line that is not marked by judgement: an answer-key line (`key`), and an
    `evidence_sum` composite, which carries no band set and is marked through its aspects —
    each aspect is a line of its own and carries its own model."""
    if "key" in line:
        return None
    method = line.get("score_method") or "bands"
    if method == "evidence_sum":
        return None
    declared = line.get("scoring")
    if isinstance(declared, str) and declared:
        return {"scoring": declared, "chosen_automatically": False}
    bands = line.get("bands")
    model = default_scoring_model(
        score_method=method,
        band_count=len(bands) if isinstance(bands, list) else None,
        component_of=line.get("component_of") or None)
    return {"scoring": model, "chosen_automatically": True}


def defaulted_scoring(step_record: Mapping[str, Any] | None) -> dict[str, str]:
    """The criteria (id -> model) that took FR-PKG-29's default, read from the version's
    `SCORING_DEFAULT_STEP` row; empty when every line declared its model or there is no row
    (a version that predates the default, or one not built from a spec)."""
    if not step_record:
        return {}
    return dict(json.loads(step_record["payload"]).get("defaulted", {}))


def write_spec_criteria(catalog: Any, version: str, criteria: Iterable[Mapping[str, Any]],
                        approved_by: str) -> None:
    """Write each planned rubric line to the draft `version` through `catalog`'s own API.

    A multiple-choice line (`kind == "mcq"`) becomes a two-band criterion (incorrect /
    correct) with its options and answer key. An `evidence_sum` criterion is a composite: a
    grouping record with no bands and no key, its aspects written as their own two-band
    criteria naming it in `component_of` (`FR-PKG-24`). A `general` criterion is written as
    the bands criterion it stores as, and its spec-carried derivation description is recorded
    and confirmed (`FR-PKG-26`) — the confirmation that makes it publishable.

    A judged line with no declared `scoring` takes FR-PKG-29's structural default here — the
    one write both build paths (`aeh package build` and the console's authoring build) pass
    through, so the same spec yields the same model on either (CT-PKG-24) — and the lines that
    took it (possibly none) are recorded in a `SCORING_DEFAULT_STEP` setup-step row
    (FR-SETUP-14)."""
    defaulted: dict[str, str] = {}
    judged = False
    for c in criteria:
        judged = judged or c["kind"] != "mcq"
        if c["kind"] == "mcq":
            catalog.add_criterion(version, c["id"], question_id=c["question"], kind="mcq",
                                  max_points=c["max_points"], scoring_model=MCQ_SCORING,
                                  band_count=ASPECT_BAND_COUNT)
            catalog.add_band(version, c["id"], 0, "incorrect", 0.0)
            catalog.add_band(version, c["id"], 1, "correct", c["max_points"])
            catalog.set_mcq_options(version, c["id"], c["options"])
            catalog.set_answer_key(version, c["id"], c["key"])
            continue
        method = c.get("score_method") or "bands"
        if method == "evidence_sum":
            catalog.add_criterion(
                version, c["id"], question_id=c["question"], kind="open",
                max_points=c["max_points"], scoring_model=_scoring_for(c, defaulted),
                dependencies=c["depends_on"], band_count=None,
                score_method=method)
            continue
        catalog.add_criterion(
            version, c["id"], question_id=c["question"], kind="open",
            max_points=c["max_points"], scoring_model=_scoring_for(c, defaulted),
            dependencies=c["depends_on"], band_count=len(c["bands"]),
            evidence_type=c["evidence_type"], component_of=c["component_of"],
            score_method=None if method == "bands" else method,
            evaluation_mode=c["evaluation_mode"], construct_tag=c["construct_tag"])
        for ordinal, name, points, descriptor in c["bands"]:
            catalog.add_band(version, c["id"], ordinal, name, points, descriptor)
        if c["band_justification"]:
            catalog.update_criterion_field(version, c["id"], "band_justification",
                                           c["band_justification"])
        if method == "general":
            _record_confirmed_derivation(catalog, version, c["id"],
                                         c["derivation_description"], approved_by)
    if judged:
        _record_scoring_default(catalog, version, defaulted)


def _scoring_for(c: Mapping[str, Any], defaulted: dict[str, str]) -> str:
    """The judged line's declared model, or FR-PKG-29's default — noted in `defaulted` when
    taken."""
    declared = c.get("scoring")
    if declared:
        return declared
    method = c.get("score_method") or "bands"
    model = default_scoring_model(
        score_method=method,
        band_count=None if method == "evidence_sum" else len(c["bands"]),
        component_of=c.get("component_of"))
    defaulted[c["id"]] = model
    return model


def _record_scoring_default(catalog: Any, version: str, defaulted: Mapping[str, str]) -> None:
    """Record which judged lines took FR-PKG-29's default (FR-SETUP-14). The row is written
    even when none did, so its presence tells a version built under the rule — every line not
    listed declared its model — from one that predates it."""
    catalog.record_step(
        version, step_id=SCORING_DEFAULT_STEP,
        status=SCORING_DEFAULT_STATUS if defaulted else SCORING_DECLARED_STATUS,
        payload=json.dumps({"defaulted": dict(defaulted)}, sort_keys=True),
        recorded_at=datetime.now(timezone.utc).isoformat())


def _record_confirmed_derivation(catalog: Any, version: str, criterion_id: str,
                                 description: str, approved_by: str) -> None:
    """The spec export carries a `general` criterion's derivation provenance; the rebuild
    records it against the bands the criterion carries and confirms it under the approver,
    exactly as the setup flow's teacher confirmation did (`FR-PKG-26`)."""
    bands = [dict(band) for band in catalog.bands(criterion_id)]
    now = datetime.now(timezone.utc).isoformat()
    catalog.record_derivation(
        version, criterion_id, description=description,
        derived_bands=[{"ordinal": b["ordinal"], "band": b["band"], "points": b["points"],
                        "descriptor": b.get("descriptor") or ""} for b in bands],
        recorded_at=now)
    catalog.confirm_derivation(version, criterion_id, confirmed_by=approved_by,
                               confirmed_at=now)
