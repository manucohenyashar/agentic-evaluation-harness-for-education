"""Writing a checked package spec's rubric lines into a draft version (live-test blocker B5).

`aeh package build` (`aeh.pipeline.packages`) reads and checks the operator's spec — which since
`FR-PKG-27` is a system-emitted export, never a teacher-authored file — and the rubric lines are
written here, on the package side, because a rubric line's scoring model and method are the
package's declarations (`CT-SETUP-05`, `CT-AGG-09`). Every rule `M-PKG` enforces still raises
from the write that breaks it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

#: The scoring model a multiple-choice line is stored with (a key lookup is one atomic check),
#: and the one a judged line gets when its spec does not declare one.
MCQ_SCORING = "atomic"
JUDGED_SCORING = "holistic"

#: A keyed line declares a two-band set (incorrect / correct), as an aspect criterion does.
ASPECT_BAND_COUNT = 2


def write_spec_criteria(catalog: Any, version: str, criteria: Iterable[Mapping[str, Any]],
                        approved_by: str) -> None:
    """Write each planned rubric line to the draft `version` through `catalog`'s own API.

    A multiple-choice line (`kind == "mcq"`) becomes a two-band criterion (incorrect /
    correct) with its options and answer key. An `evidence_sum` criterion is a composite: a
    grouping record with no bands and no key, its aspects written as their own two-band
    criteria naming it in `component_of` (`FR-PKG-24`). A `general` criterion is written as
    the bands criterion it stores as, and its spec-carried derivation description is recorded
    and confirmed (`FR-PKG-26`) — the confirmation that makes it publishable."""
    for c in criteria:
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
                max_points=c["max_points"], scoring_model=c["scoring"],
                dependencies=c["depends_on"], band_count=None,
                score_method=method)
            continue
        catalog.add_criterion(
            version, c["id"], question_id=c["question"], kind="open",
            max_points=c["max_points"], scoring_model=c["scoring"],
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
