"""Triage categories, pipeline stages, the ambiguity alert knob, and the fixture ids."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping


LOGGER = logging.getLogger("aeh.calib")


# --- the triage vocabulary (FR-CALIB-02, CT-CALIB-04) ----------------------------------------------

#: The three categories, verbatim from `FR-CALIB-02`. A closed set: the
#: required field's membership is part of the required-field design, and a
#: fourth value would be a fourth path a disagreement could take past the
#: boundary the refusal guards.
RUBRIC_AMBIGUITY = "rubric_ambiguity"


MODEL_FAILURE = "model_failure"


TEACHER_INCONSISTENCY = "teacher_inconsistency"


TRIAGE_CATEGORIES: frozenset[str] = frozenset(
    {RUBRIC_AMBIGUITY, MODEL_FAILURE, TEACHER_INCONSISTENCY}
)


#: The one category eligible to produce a proposed edit (`FR-CALIB-02`). The
#: other two exist precisely because they must never produce one: fitting the
#: rubric to teacher inconsistency encodes one teacher's noise into the
#: instrument permanently, and editing it because the model failed changes the
#: assessment to accommodate a bug.
EDIT_ELIGIBLE_CATEGORY = RUBRIC_AMBIGUITY


#: The label `CT-CALIB-03` fixes: discovery output is *ambiguity discovery,
#: never a measurement of accuracy*. The label is part of the value, so a
#: consumer cannot render it as one without discarding the field that says
#: what it is.
KIND_AMBIGUITY_DISCOVERY = "ambiguity_discovery"


# --- the pipeline-finding vocabulary (FR-CALIB-04) -------------------------------------------------
#
# The three stages a model failure can live in, verbatim from `FR-CALIB-04`.
# A model failure is a finding about the pipeline that produced the score —
# never a reason to edit the rubric, which is what the eligibility rule above
# makes unreachable.

#: The pipeline stages a `model_failure` finding can name.
PIPELINE_STAGES: tuple[str, ...] = ("extraction", "decomposition", "panel_composition")


#: Where a scored-band disagreement is observed when the caller declares no
#: deeper stage: the panel's composition of the verdict. Disclosed as an
#: interpretation — it names where the disagreement was *seen*, never where it
#: was *caused* (see `docs/code-notes/calib.md`).
DEFAULT_PIPELINE_STAGE = "panel_composition"


# --- the side-by-side pair (FR-CALIB-03, NFR-CALIB-01) ---------------------------------------------

#: The two examples a `teacher_inconsistency` finding surfaces side by side.
#: Exactly two, enforced at construction: one example is an accusation, two
#: are a comparison the teacher can resolve.
EXAMPLES_PER_SIDE_BY_SIDE = 2


# --- the observability knob (CT-CALIB-14, seam 3) --------------------------------------------------
#
# "A rubric surfacing more than a handful of ambiguities alerts as *the rubric
# needs a conversation*, not as twenty questions to answer" (§3.17's
# Observability; `CT-CALIB-14` fixes the wording and the aggregate shape). A
# handful is a detector threshold, not a quality verdict — it decides when the
# report says the rubric needs a conversation, never whether the rubric is
# good. Read at call time under the same name (CLAUDE.md seam 3) so a slower
# or stricter installation adjusts without a code change; a mis-set or
# out-of-range value falls back to the default rather than raising, because a
# mis-set knob must not stop discovery, and the report discloses the value
# that actually applied.

CALIB_AMBIGUITY_ALERT_AFTER: int = 5


CALIB_AMBIGUITY_ALERT_AFTER_ENV: str = "HARNESS_CALIB_AMBIGUITY_ALERT_AFTER"


def _ambiguity_alert_after(environ: Mapping[str, str] | None = None) -> int:
    """The ambiguity alert threshold, read from its knob at call time. A value below 1 would alert
    on every discovery, so it falls back to the declared default like any other bad value."""
    source = os.environ if environ is None else environ
    raw = source.get(CALIB_AMBIGUITY_ALERT_AFTER_ENV)
    if raw is None or not raw.strip():
        return CALIB_AMBIGUITY_ALERT_AFTER
    try:
        value = int(raw)
    except ValueError:
        return CALIB_AMBIGUITY_ALERT_AFTER
    return value if value >= 1 else CALIB_AMBIGUITY_ALERT_AFTER


#: The alert text carried in ``DiscoveryReport.alerts`` — the wording
#: `CT-CALIB-14` fixes: the aggregate signal is that the rubric needs a
#: conversation, not a queue of twenty questions to answer.
AMBIGUITY_ALERT_TEXT = (
    "the rubric needs a conversation, not twenty questions to answer"
)


# --- the test seams (contract suite, §6.11.17) ------------------------------------------------------
#
# These live in the module — the same pattern `aeh.grade.cohort_with_mixed_revisions`
# established — because each one builds a REAL Tier P store through the package's own
# revision flow and then closes it, and a real store open needs the full migration chain
# (CLAUDE.md's store rule) before the first open. They are part of the module's surface,
# exported in `__all__`, so the contract cases drive exactly the surface a real caller
# would and no test-side double stands in for the package.

#: The package id every test store mints, and the criterion it carries.
_FIXTURE_PACKAGE_ID = "pkg-calib-test"


_FIXTURE_CRITERION_ID = "CRIT-1"
