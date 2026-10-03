"""Writing a checked package spec's rubric lines into a draft version (live-test blocker B5).

`aeh package build` (`aeh.pipeline.packages`) reads and checks the operator's spec; the rubric
lines it planned are written here, on the package side, because a rubric line's scoring model is
the package's declaration (`CT-SETUP-05`) and only the package side names it (`CT-AGG-09`).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

#: The scoring model a multiple-choice line is stored with: a key lookup is one atomic check.
MCQ_SCORING = "atomic"


def write_spec_criteria(catalog: Any, version: str, criteria: Iterable[Mapping[str, Any]]) -> None:
    """Add each planned rubric line to the draft `version` through `catalog`'s own writes.

    A multiple-choice line (`kind == "mcq"`) becomes a two-band criterion (incorrect, correct)
    with its options and answer key; a judged line keeps its bands, worst first, its declared
    scoring (`scoring`), dependencies and evidence type. Every rule `M-PKG` enforces still
    raises from the write that breaks it."""
    for c in criteria:
        if c["kind"] == "mcq":
            catalog.add_criterion(version, c["id"], question_id=c["question"], kind="mcq",
                                  max_points=c["max_points"], scoring_model=MCQ_SCORING,
                                  band_count=2)
            catalog.add_band(version, c["id"], 0, "incorrect", 0.0)
            catalog.add_band(version, c["id"], 1, "correct", c["max_points"])
            catalog.set_mcq_options(version, c["id"], c["options"])
            catalog.set_answer_key(version, c["id"], c["key"])
            continue
        catalog.add_criterion(
            version, c["id"], question_id=c["question"], kind="open",
            max_points=c["max_points"], scoring_model=c["scoring"],
            dependencies=c["depends_on"], band_count=len(c["bands"]),
            evidence_type=c["evidence_type"])
        for ordinal, name, points, descriptor in c["bands"]:
            catalog.add_band(version, c["id"], ordinal, name, points, descriptor)
