"""`TC-CALIB-04` — a model failure routes to the pipeline, and the rubric edit stays shut.

Test plan §5.17, `TC-CALIB-04` (FR-CALIB-04, Integration / rung 2).

The contract suite carries the category-level half (`TC-CALIB-C04`: a `model_failure` verdict
produces *a* pipeline finding and no edit). What no green test carried before this file is the
routing itself:

* the finding names the stage the caller declared — all three declared stages asserted, one
  row each, because a router that forwards `extraction` failures to the panel-composition
  surface would still pass a truthiness check;
* the default is the stage the disagreement was **observed** on — `panel_composition`, the
  surface a scored-band disagreement arrives on — never a guess at where it was *caused*;
* an out-of-set stage does not exist: the finding's constructor refuses it (a plain
  `ValueError` — a caller defect), so a typo cannot route a failure to a stage nobody owns;
* the no-edit prohibition holds through the finding's shape, not beside it — the verdict
  carries the finding, carries no edit, and refuses one.

The stages are `aeh.calib.PIPELINE_STAGES` — the module's own declaration — swept generically
rather than hand-listed, so a stage added to the module without landing in this sweep is
visible rather than silent.
"""

from __future__ import annotations

import dataclasses

import pytest

from tests.support.impl import CALIB_MODULE, require


def _triaged_model_failure(calib, pipeline_stage=None):
    """A `model_failure` verdict from a real `triage()` call, at an optional stage."""
    disagreement = calib.Disagreement(
        criterion_id="c1",
        category="model_failure",
        sample_id="s1",
        teacher_band="3",
        model_band="2",
        **({"pipeline_stage": pipeline_stage} if pipeline_stage else {}),
    )
    return calib.triage(disagreement)


# --- the routing, one row per declared stage ------------------------------------------------------


@pytest.mark.parametrize("stage", ["extraction", "decomposition", "panel_composition"])
def test_tc_calib_04_the_finding_names_the_stage_the_caller_declared(stage):
    """`CT-CALIB-04`/`FR-CALIB-04` — the pipeline finding routes the failure to the stage the
    evidence names, swept over all three declared stages.

    Parametrized rather than sampled because the routing is the case: a `PipelineFinding`
    whose `stage` is whatever the caller passed is the contract — and each of the three stages
    has a different owner downstream, so a wrong routing is a wrong *destination*, not just a
    wrong string. The detail text is asserted to name the criterion, so the finding is
    actionable at the stage it lands on rather than a bare label.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "triage", "PipelineFinding", issue="#140")

    verdict = _triaged_model_failure(calib, pipeline_stage=stage)
    finding = verdict.pipeline_finding

    assert finding is not None, (
        f"{stage}: the model_failure verdict produced no pipeline finding (FR-CALIB-04)"
    )
    assert finding.stage == stage, (
        f"the finding routed a declared-{stage} failure to {finding.stage!r} — the finding "
        "names the stage the failure lives in, not the surface it was observed from "
        "(FR-CALIB-04)"
    )
    assert finding.criterion_id == "c1"
    assert "c1" in (finding.detail or ""), (
        f"the finding's detail does not name the criterion it routes ({finding.detail!r}); a "
        "stage that receives a finding it cannot attribute is a dead letter"
    )


def test_tc_calib_04_without_evidence_the_finding_names_where_it_was_seen():
    """No declared stage → `panel_composition`, the observation surface — never a guess at
    causation.

    A scored-band disagreement is *seen* on the panel's composition of the verdict; where the
    failure was *caused* is evidence the caller may or may not have. Defaulting to a deeper
    stage would be the module inventing a diagnosis, and `M-PIPE` would receive a routing the
    run's own evidence cannot support.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "triage", "DEFAULT_PIPELINE_STAGE", issue="#140")

    verdict = _triaged_model_failure(calib, pipeline_stage=None)
    assert verdict.pipeline_finding is not None
    assert verdict.pipeline_finding.stage == calib.DEFAULT_PIPELINE_STAGE, (
        f"without declared evidence the finding named "
        f"{verdict.pipeline_finding.stage!r}, not the declared default "
        f"{calib.DEFAULT_PIPELINE_STAGE!r} — where the disagreement was *seen* is what the "
        "run knows; where it was *caused* is a guess the module must not make (FR-CALIB-04)"
    )


# --- the closed set, and the prohibition ----------------------------------------------------------


def test_tc_calib_04_a_stage_outside_the_declared_three_does_not_exist():
    """An out-of-set stage is refused — the finding's constructor raises a plain `ValueError`.

    The set of stages a model failure can live in is closed (`PIPELINE_STAGES`), and the
    refusal is a caller defect, not a calibration-domain failure: a typo'd stage name must not
    silently route a failure to the default surface, where the owner that should have received
    it never hears of it.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "PipelineFinding", "PIPELINE_STAGES", issue="#140")

    with pytest.raises(ValueError) as exc:
        calib.PipelineFinding(criterion_id="c1", stage="prompt_writing")
    assert not isinstance(exc.value, calib.CalibrationError), (
        "an out-of-set pipeline stage raised into the calibration hierarchy; this is a "
        "programming error (ValueError), the same distinction TC-CALIB-02 draws for the "
        "triage categories"
    )

    # The sweep's closure: the module's declared set is exactly the three this file's routing
    # sweep covers, so a stage added to the module without a routing row is visible here.
    assert calib.PIPELINE_STAGES == ("extraction", "decomposition", "panel_composition"), (
        f"PIPELINE_STAGES is {calib.PIPELINE_STAGES}; the routing sweep above covers the "
        "three declared stages — a fourth means the sweep and the module have drifted apart"
    )


def test_tc_calib_04_the_finding_rides_a_verdict_that_still_refuses_an_edit():
    """The finding routes the failure; the rubric edit stays structurally unreachable.

    `triage()` on a `model_failure` disagreement returns a verdict that carries the finding
    and no edit — and the constructor still refuses an edit on the category, so the routing
    and the prohibition are one value, not two behaviours that could drift apart. Editing the
    rubric because the extractor failed changes the assessment to accommodate a bug.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "triage", "TriageVerdict", "EditNotEligible", issue="#140")

    verdict = _triaged_model_failure(calib, pipeline_stage="extraction")
    assert verdict.pipeline_finding is not None
    assert verdict.pipeline_finding.stage == "extraction"
    assert verdict.proposed_edit is None, (
        "a model_failure verdict carrying the pipeline finding also carried a rubric edit — "
        "the finding exists precisely because the rubric is not the problem (FR-CALIB-04)"
    )
    assert verdict.edit_eligible is False
    assert verdict.fitted is False

    with pytest.raises(calib.EditNotEligible):
        calib.TriageVerdict(
            criterion_id="c1",
            category="model_failure",
            pipeline_finding=verdict.pipeline_finding,
            proposed_edit="descriptor: 'clear' -> 'well structured'",
        )

    # The value is frozen: the finding cannot be swapped out after triage recorded it.
    assert dataclasses.is_dataclass(verdict) and verdict.__dataclass_params__.frozen, (
        "the triage verdict is not frozen; a mutable verdict lets a later stage attach the "
        "edit the constructor refused"
    )