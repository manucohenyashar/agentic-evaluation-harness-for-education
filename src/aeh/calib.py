"""M-CALIB — Rubric Calibration (§3.17): discovery and triage (#137), the
capped elicitation, the lock write-path and the history (#138), and the two
guardrail gates (#139).

Three stories have landed. The first (#137) is the half the design builds as a
guardrail before the feature it guards (`§3.17`'s phasing note): discovery of
where a rubric is ambiguous, and the triage that categorizes every disagreement
before anything is revised. The second (#138) is the half a teacher actually
meets: the elicitation that turns edit-eligible findings into at most
`CALIB_MAX_QUESTIONS` questions — ranked by how many submissions the ambiguity
affects — each carrying options and two examples, never a pre-authored edit;
the application of the teacher's answers as rubric clarifications written
**through `M-PKG`'s §6.2 lock**; the history that records every question,
option set, answer and resulting edit; and the skip path, which grades the
class against R₀ unchanged and is never on the critical path. The third
(#139) is the pair of guardrail gates between a proposed revision and a live
one (`§6.5`–`§6.7`): dual-scoring non-inferiority over the **full class**
against a threshold **declared before the comparison** — never a default —
and adversarial back-translation, in which a model *not in the scoring panel*
is asked to construct a student response on which R₀ and R₁ would assign
different scores, and a successful construction is evidence the construct
changed. Any gate failure reverts to R₀ rather than shipping with a warning:
`CalibrationRunOutcome.shipped_with_warning` and `GateResult.advisory_only`
are structurally False — the checkable statement of `CT-CALIB-02`, in the
same shape as `TriageVerdict`'s `fitted` — so the forbidden "warned revision"
is unconstructible on this surface rather than merely avoided.

**Ambiguity discovery, never a measurement of accuracy (`FR-CALIB-01`,
`CT-CALIB-03`).** `discover()` scores teacher-graded calibration samples under
R₀ — the rubric version the caller names, which is the package's current
delivered version before any edit — and reports where the teacher's band and
the panel's band differ, per criterion. The output is typed as ambiguity
discovery (`DiscoveryReport.kind`) and carries no field an accuracy figure
falls out of: no matched/total pair, no rate, no correctness count. The
teacher's labels are a second opinion, not a gold standard, and the
calibration set is far too small for an accuracy claim — the figures that
exist are `M-STATS`'s, computed over admissible blind labels (`CT-STATS-01`).

**The required triage category (`FR-CALIB-02`, `CT-CALIB-04`).** Every
disagreement carries a triage category — `rubric_ambiguity`,
`model_failure`, or `teacher_inconsistency` — as a *required* output field.
The requirement is enforced at the triage boundary, where it has teeth: a
`Disagreement` discovered with no category yet is exactly what discovery
emits (categorizing is the triage step's judgement, not discovery's guess),
and `triage()` refuses it with `TriageCategoryRequired`. An optional category
would default into *some* path, and the editable path is the dangerous
default — the refusal is what makes that unreachable. Past the boundary the
`TriageVerdict` always carries one, and a verdict without one is
unconstructible.

**Eligibility is structural, not policy (`FR-CALIB-02`).** Only
`rubric_ambiguity` is eligible to produce a proposed edit. That is not a
flag the module promises to respect — `edit_eligible` is derived from the
category inside the value, and `TriageVerdict.__post_init__` refuses the
construction of a non-`rubric_ambiguity` verdict carrying a `proposed_edit`,
so no caller, on any path, can attach one. Even a `rubric_ambiguity` verdict
carries `proposed_edit=None` at triage: the edit is generated from the
teacher's *answer* during elicitation (#138, `CT-CALIB-05`), never proposed
by the model.

**Teacher inconsistency is surfaced, never fitted to (`FR-CALIB-03`).** A
`teacher_inconsistency` verdict carries both examples side by side — the
teacher's own differing labels, as a two-slot pair. The constructor refuses a
one-example verdict, because one example is an accusation and two are a
comparison the teacher can resolve. Nothing on this surface generates an edit
from one: with the eligibility rule above, a `teacher_inconsistency` verdict
cannot carry a `proposed_edit` at all.

**A model failure routes to the pipeline, not the rubric (`FR-CALIB-04`).**
A `model_failure` verdict carries a `PipelineFinding` naming where the
model's failure lives — extraction, decomposition, or panel composition —
and no rubric edit (structurally, as above). The stage is the disagreement's
declared `pipeline_stage` when the caller carries that evidence; otherwise
the default is `panel_composition`, the surface a scored band disagreement
is observed on, disclosed as an interpretation on the PR.

**The four seams.** Headless: module-level `discover`/`triage`/`elicit`/
`apply_answers`/`run_for_assignment`/`non_inferiority`/`back_translate` return
structured values, no console on any path. Deterministic transport: the
scoring side of discovery arrives through injected channels — `model_bands`
(the recorded-transport form, pre-scored under R₀) or the `scorer` callable
(the injected scoring seam a test binds to `RecordedFixtureProvider`-backed
code and production binds to the panel) — so a calibration run needs no
network and no real upstream (`CT-PROV-10`), and the provider stays the only
egress point (`CT-PROV-15`). The gates ride the same seam: the full class's
dual-scored bands arrive as a registered roster (pre-scored under R₀ and R₁,
the same recorded-transport form), and the off-panel model's construction
attempts arrive as a bound session — a build with neither is *unavailable*,
never invented. Env-gated knobs, all read at call time: the aggregate
more-than-a-handful-of-ambiguities alert threshold
(`HARNESS_CALIB_AMBIGUITY_ALERT_AFTER`), the elicitation cap
(`HARNESS_CALIB_MAX_QUESTIONS`, `FR-CALIB-05` — the cap is the knob, because
teacher time is environment-shaped too), the standing threshold declaration's
env fallback (`HARNESS_CALIB_NONINFERIORITY_THRESHOLD`), the class-size
cap (`HARNESS_CALIB_CLASS_SIZE_CAP` — production default is **no cap**: the
gate scores the full class, `NFR-CALIB-02`, and a set cap refuses an
oversized class rather than silently scoring a subset), and the off-panel
checker this deployment names (`HARNESS_CALIB_OFF_PANEL_MODEL` — the gate
reads it when the caller passes no explicit checker; nothing declared is
the unavailable mode, never an invented adversary). Observability: the
report, the run outcome and each gate result carry what each stage did —
papers scored, criteria excluded as deterministic, unscored papers, per-stage
notes, the aggregate alert, the run's fairness note and revision trace, the
threshold's source and declared-at timestamp, the per-gate outcome and the
class shift distribution — never a bare status.

**The two gates (`FR-CALIB-08`/`-09`, `§6.5`/`§6.6`).** `non_inferiority`
compares the R₀ and R₁ dual scores the *full class* already carries and
rejects the revision when **more than** the threshold of the class shifted by
a full band — strictly more: exactly-at-threshold passes, because the
requirement says "more than". The threshold is never defaulted
(`CT-CALIB-13`: 0.10 is the HLD's *example*, not a validated value): an
explicit argument wins, then a standing institutional declaration made
through `declare_institutional_threshold` (or its env fallback), and with
neither the gate refuses with `ThresholdNotDeclared` — an unowned threshold
governing whether a rubric changes is the decision nobody made. The gate
refuses the calibration set itself (`InsufficientPopulation`: it "lacks the
sample size to mean anything", `NFR-CALIB-02`) and reports *where its
threshold came from* (`threshold_source`) and *when it was fixed relative to
the first result* (`threshold_declared_at` < `first_result_at`), so a
threshold chosen after the outcome shows up as one. `back_translate` asks a
model **off the panel** to construct a response on which R₀ and R₁ would
differ; a construction that succeeds rejects the revision outright — an
advisory note would be the warned revision renamed (`CT-CALIB-08`). The
off-panel build is refused at configuration time in `M-CONF` when it shares a
served build with the panel (`RunConfig.__post_init__`, `NFR-CALIB-04`), and
`back_translate` refuses it again at the gate, because two entries naming the
same build are the same model however they are labelled. Every failure mode
ends at R₀ (`CT-CALIB-02`): the gate outcomes and the run outcome carry the
revert as data, and `simulate_failure` drives each of the eight enumerated
modes through the module's real paths to the same terminal state.

**Version pinning (`FR-CALIB-10`/`-11`, `§6.7`, `CT-CALIB-09`).** A revision
that passed both gates is pinned with `pin_revision` — the package version,
the approver, and a timestamp — before anything consumes it, and consumers
keep R₀-scored and R₁-scored results out of one unannotated rollup (`M-GRADE`
and `M-STATS` carry their halves; this module mints the pin). The cost is
budgeted, not incurred (`NFR-CALIB-03`, `CT-CALIB-12`): `plan_dual_scoring`
discloses the call count — one additional full-class pass — *before*
authorization, `authorize` records the operator's approval, and
`run_dual_scoring` makes exactly the disclosed number of calls through the
injected provider.

**The store surface is `M-PKG`'s, exclusively.** Nothing here opens a store
on its own authority or carries a schema of its own: every question, answer
and resulting edit is recorded through `PackageCatalog.append_elicitation`
(`FR-CALIB-13`), and every rubric clarification lands through the same
catalog's revision flow — a new version created by `create_version`, edited
while unlocked, behind the §6.2 lock the catalog's `_guard` already enforces
(`FR-CALIB-07`; a second implementation of that lock is what would drift,
`CT-CALIB-06`). The append-only elicitation history's schema arrived with
`M-PKG`'s migration 5 (`FR-PKG-20`, `NFR-PKG-01`), so this story needs no
migration of its own and adds nothing to the store's census.

Interpretations this module records (each a place the design is silent and
this implementation chose; all reported on the PR):

* *Discovery emits uncategorized disagreements.* `FR-CALIB-02` says every
  disagreement *carries* a required category; §3.17's interface has `triage`
  as a separate step from `discover`. Read together: discovery identifies,
  triage categorizes, and the required-field refusal sits between them. A
  discovered disagreement that already carried a model-assigned category
  would be the module triaging its own failures — the fitting the clause
  exists to prevent, one step early.
* *The side-by-side pair is a structural two-slot surface.* `triage()`
  normalizes the teacher's repeat labels to exactly two example slots — the
  pair the teacher resolves (NFR-CALIB-01's "two student examples shown side
  by side"). A disagreement carrying more than two repeat labels displays
  its first two as the pair; one carrying none arrives as a pair with both
  slots unfilled (visible as None) rather than the surface pretending to be
  complete — the pair's length is structural, so a verdict constructed
  directly with anything but two slots is refused (`SideBySideRequired`), and
  the one-example shape is unconstructible by hand.
* *The default pipeline stage is where the failure is observed.* A scored
  band the teacher disagrees with is observed on the panel's composition of
  the verdict; extraction and decomposition failures are only visible when
  the caller declares them (`Disagreement.pipeline_stage`). The default
  names where the disagreement was *seen*, never guesses where it was
  *caused*.
* *The teacher's repeat-label spread is surfaced in the notes, not as a
  disagreement.* Where the teacher's own labels for one criterion differ
  across samples but the panel matched both, no teacher-vs-model disagreement
  exists to categorize — and inventing one to carry the finding would be a
  disagreement with no sides. The spread is disclosed per criterion in the
  report's notes as material for the triage conversation (`FR-CALIB-03`),
  never fitted to.
* *Answer-to-edit resolution is the teacher's words, not a vocabulary.*
  `apply_answers` reads the answer's first word as an intent — *broaden*,
  *narrow*, *keep as is* — and composes the clarified descriptor from the band's
  CURRENT text, never a replacement of it: broaden and narrow append the
  directional clause the answer chose to the descriptor as it stands (a revision
  that erased what the band means would be the edit destroying the thing it
  claims to clarify), the teacher's own words are appended as the clarification
  itself, and *keep as is* generates no edit at all — nothing lands, no version is
  minted, and the confirmation lives in the history row alone. There is no closed
  answer schema to reject against, because the question's options are a
  prompt to a person, not an API contract: a teacher who types a sentence
  is giving the clarification, and refusing it would send them back to the
  interface for no safety gain (the edit itself still goes through the
  catalog's guard).
* *A question's criterion is matched to the version being edited, with a
  positional fallback.* The session a question was asked under and the
  version an answer is applied against are different reads of the same
  package; when the question's `criterion_id` exists in the target
  version's criteria it is used, otherwise the question's position picks
  the criterion from the version's own ordering. The fallback exists because
  discovery and elicitation can run against different revisions of the same
  rubric without the ambiguity having moved; the ordering is the version's,
  not the session's — and the history row records the generic wording naming
  the criterion actually edited, so a stale session (elicited against a
  different package) can never leave a row whose question names a criterion
  the edit did not touch.
* *A pre-§6.2-lock vintage is declared, not inferred.* Whether a package
  version predates the schema lock is a property of when it was created —
  the lock's columns arrived in `M-PKG`'s migration 3 — and no inference
  from content could recover it. `package_version_predating_schema_lock()`
  is the declaration seam a caller (or a test) uses to name such a version;
  `apply_answers` refuses it with `PhaseDependencyError` rather than
  attempting an edit the vintage cannot carry (`CT-CALIB-15`).
* *A standing threshold declaration is consumed by the gate run it was
  declared for.* `declare_institutional_threshold` records a threshold with
  the moment it was fixed, and the next gate run that uses it consumes it —
  a fresh declaration per comparison is the strictest honest reading of
  "declared before the comparison" (`FR-CALIB-08`): a threshold that stood
  forever would let a comparison run months later under a number chosen for
  a different one, with nothing distinguishing that from a fresh decision.
  An explicit `threshold` argument is never consumed — it is the caller's
  declaration at the call itself.
* *A "shift" is any full-band difference, in either direction.*
  Non-inferiority asks whether the *instrument* moved, and a student whose
  band moved a full level under R₁ has been regraded in a teacher-recognizable
  sense whether the move was up or down; the clause reads "shifts", not
  "drops" (`FR-CALIB-08`). A paper shifts when any criterion's band differs
  between its R₀ and R₁ scores.
* *The gate consumes pre-scored rosters; the budgeted pass buys the R₁ half.*
  `non_inferiority` reads the class's dual-scored bands from the registered
  roster — the recorded-transport form, the same shape discovery's
  `model_bands` takes (`CT-PROV-10`) — so the gate is a comparison, not a
  scoring run. `run_dual_scoring` is the one additional full-class pass
  (`NFR-CALIB-03`) that drives the injected provider, and the R₁ scores it
  buys come back on the plan; joining them with R₀'s accumulated bands and
  registering the roster is the caller's act, and in this build the
  registration route is the test seam. #139 is the last module in build
  order, so there is no later story to land a production registration route
  in — the gap is recorded on the module's `type:test` issue.
* *A plan for an unregistered cohort is built on disclosed defaults.*
  `plan_dual_scoring` against a cohort the module has no roster for cannot
  know the class's shape, so it plans against the declared example class
  (`PLAN_DEFAULT_CLASS_SIZE`, `PLAN_DEFAULT_CRITERIA_COUNT`) and says so in
  the plan's notes — never silently: an estimated cost built on an unstated
  assumption is a budget that lies.
* *The structurally-False flags are the clause made checkable.*
  `CalibrationRunOutcome.shipped_with_warning` and
  `GateResult.advisory_only` are always False, exactly as
  `TriageVerdict.fitted` reads the one shape the constructor already refuses:
  `CT-CALIB-02` forbids the warned revision and `CT-CALIB-08` forbids the
  advisory outcome, so the fields exist to be asserted, and a code path that
  could set them cannot be written without making the assertion fail.
* *`simulate_failure` is the caller-side terminal-state policy, not an
  eighth failure path.* Each of `CT-CALIB-02`'s eight enumerated modes is
  driven through the module's real refusal paths — the gate's refusals, the
  triage boundary, the unbound off-panel transport — and the sweep asserts
  the *outcome shape* every failure resolves to: R₀ unchanged, the ambiguous
  criteria lower-confidence, no revision shipped, nothing shipped with a
  warning (`FR-CALIB-10`). The seam exists because the terminal state is a
  property of how callers resolve these failures, and the contract pins it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aeh.det import EVALUATION_MODE_DETERMINISTIC
from aeh.pkg import PackageCatalog, SchemaLockViolation

__all__: tuple[str, ...] = (
    "CALIB_AMBIGUITY_ALERT_AFTER",
    "CALIB_AMBIGUITY_ALERT_AFTER_ENV",
    "CALIB_CLASS_SIZE_CAP",
    "CALIB_CLASS_SIZE_CAP_ENV",
    "CALIB_MAX_QUESTIONS",
    "CALIB_MAX_QUESTIONS_ENV",
    "CALIB_NONINFERIORITY_THRESHOLD",
    "CALIB_NONINFERIORITY_THRESHOLD_ENV",
    "CALIB_OFF_PANEL_MODEL",
    "CALIB_OFF_PANEL_MODEL_ENV",
    "CALIBRATION_SET",
    "CalibrationAlert",
    "CalibrationError",
    "CalibrationMetric",
    "CalibrationRunOutcome",
    "Assignment",
    "DEFAULT_PIPELINE_STAGE",
    "Disagreement",
    "DiscoveryReport",
    "DualScoringPlan",
    "EditNotEligible",
    "ElicitationQuestion",
    "EXAMPLES_PER_SIDE_BY_SIDE",
    "Finding",
    "GateResult",
    "InsufficientPopulation",
    "KIND_AMBIGUITY_DISCOVERY",
    "KNOBS",
    "LockedFieldEdit",
    "MODEL_FAILURE",
    "OffPanelConfigurationError",
    "OffPanelModelRef",
    "OffPanelUnavailable",
    "PIPELINE_STAGES",
    "PinnedRevision",
    "PhaseDependencyError",
    "QUESTION_OPTIONS",
    "RUBRIC_AMBIGUITY",
    "SchemaLockViolation",
    "SideBySideRequired",
    "TEACHER_INCONSISTENCY",
    "ThresholdNotDeclared",
    "TriageCategoryRequired",
    "TriageVerdict",
    "TRIAGE_CATEGORIES",
    "alerts_for_test",
    "apply_answers",
    "assignment",
    "authorize",
    "back_translate",
    "catalog_for_test",
    "cohort_with_band_shift",
    "contrasting_values_for",
    "counting_provider_for_test",
    "declare_institutional_threshold",
    "discover",
    "edit_touching",
    "elicit",
    "elicitation_history_for_test",
    "field_names_of",
    "findings_fixture",
    "metrics_for_test",
    "model_ref_in_panel",
    "model_ref_off_panel",
    "non_inferiority",
    "observable_behaviour_with",
    "package_version_predating_schema_lock",
    "pin_revision",
    "plan_dual_scoring",
    "run_dual_scoring",
    "run_for_assignment",
    "simulate_failure",
    "tier_p_path_for_test",
    "triage",
    "worse_but_low_shift_revision",
)

LOGGER = logging.getLogger(__name__)

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
#: was *caused* (see the module docstring).
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
    """The alert threshold, read at call time (seam 3). A value below 1 would
    alert on any discovery at all — outside the knob's meaning — so it falls
    back to the declared default like any other mis-set value."""
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


# --- errors ----------------------------------------------------------------------------------------


class CalibrationError(Exception):
    """Base for every `M-CALIB` refusal. Nothing here is transient; no caller
    should retry, so there is deliberately no retry taxonomy."""


class TriageCategoryRequired(CalibrationError):
    """A disagreement arrived at the triage boundary without its required
    category (`FR-CALIB-02`, `CT-CALIB-04`).

    This is the required-field design's enforcement point: an uncategorized
    disagreement would default into *some* path, and the editable path is the
    dangerous default — the module would fit the rubric to a disagreement
    nobody classified. The refusal is the field's "required", not a
    convention that a category is usually present."""


class SideBySideRequired(CalibrationError):
    """A `teacher_inconsistency` verdict was constructed without exactly two
    examples (`FR-CALIB-03`).

    Both examples side by side is the finding's whole shape: one example
    accuses the teacher, two let the teacher compare their own judgments and
    resolve the inconsistency themselves. A one-example verdict is the
    accusation wearing the finding's name, so it is unconstructible rather
    than discouraged."""


class EditNotEligible(CalibrationError):
    """An edit was attached to a verdict whose category cannot carry one
    (`FR-CALIB-02`, `CT-CALIB-04`).

    Only `rubric_ambiguity` is eligible to produce a proposed edit, and the
    rule is structural: the constructor refuses the violating shape, so no
    caller — and no future code path in this module — can attach an edit to a
    `model_failure` or `teacher_inconsistency` verdict. A policy check beside
    the constructor would be a second implementation of one rule, and two
    implementations of one rule drift."""


# --- the value types -------------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineFinding:
    """Where a model's failure lives (`FR-CALIB-04`): the finding a
    `model_failure` verdict produces, naming the pipeline stage the failure
    belongs to. Editing the rubric because the extractor failed changes the
    assessment to accommodate a bug — the finding routes the failure to the
    stage that owns it, and the rubric edit is structurally unreachable
    (``EditNotEligible``)."""

    criterion_id: str
    stage: str
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.stage not in PIPELINE_STAGES:
            raise ValueError(
                f"pipeline finding stage {self.stage!r} is outside the declared "
                f"stages {PIPELINE_STAGES} (FR-CALIB-04 names the three a model "
                "failure can live in)"
            )


@dataclass(frozen=True)
class Disagreement:
    """One criterion of one calibration sample where the teacher's band and
    the panel's band under R₀ differ — the unit `triage()` categorizes.

    ``category`` is the *required* triage category (`FR-CALIB-02`): discovery
    emits disagreements without one (categorizing is the triage step's
    judgement), and the triage boundary refuses one that arrives still
    uncategorized. A category outside the three declared values is refused at
    the triage boundary as well — the set is closed.

    ``teacher_band`` rides beside ``model_band`` as the second opinion the
    disagreement is about; neither is an accuracy claim, and nothing on this
    value computes one. ``examples`` carries the teacher's repeat labels for
    the criterion — ``((paper, band), ...)`` pairs — which is the material a
    `teacher_inconsistency` triage surfaces side by side (`FR-CALIB-03`).
    ``pipeline_stage`` declares where a known model failure lives, when the
    caller has that evidence; ``triage()`` defaults the finding to the stage
    the disagreement was observed on otherwise.
    """

    criterion_id: str
    category: str | None = None
    sample_id: str | None = None
    teacher_band: Any = None
    model_band: Any = None
    examples: tuple[Any, ...] = ()
    pipeline_stage: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class TriageVerdict:
    """The recorded outcome of triaging one disagreement (`FR-CALIB-02`..`-04`).

    The category is a **required** field, enforced twice: `triage()` refuses a
    disagreement that arrives without one, and this constructor refuses a
    verdict that would exist without one — a `TriageVerdict` without a
    category is unconstructible, which is what stops an uncategorized
    disagreement from defaulting into the editable path.

    The eligibility rule is structural, not policy: ``edit_eligible`` is
    derived from the category, and a non-`rubric_ambiguity` verdict carrying a
    ``proposed_edit`` is refused at construction (`EditNotEligible`). A
    `teacher_inconsistency` verdict carries both examples side by side —
    exactly two slots, enforced — and is never fitted to: ``fitted`` reads the
    one shape that would be a fit, and the constructor has already refused to
    produce it. A `model_failure` verdict carries a `PipelineFinding` and no
    rubric edit (`FR-CALIB-04`).
    """

    criterion_id: str
    category: str
    examples: tuple[Any, ...] = ()
    pipeline_finding: PipelineFinding | None = None
    proposed_edit: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.category, str) or not self.category.strip():
            raise TriageCategoryRequired(
                "a triage verdict cannot exist without its required category "
                "(FR-CALIB-02): an uncategorized disagreement would default into "
                "some path, and the editable path is the dangerous default"
            )
        if self.category not in TRIAGE_CATEGORIES:
            raise ValueError(
                f"triage category {self.category!r} is outside the closed set "
                f"{sorted(TRIAGE_CATEGORIES)} (FR-CALIB-02 names the three)"
            )
        if self.category != EDIT_ELIGIBLE_CATEGORY and self.proposed_edit is not None:
            raise EditNotEligible(
                f"a {self.category!r} verdict cannot carry a proposed edit: only "
                f"{EDIT_ELIGIBLE_CATEGORY!r} is eligible (FR-CALIB-02, CT-CALIB-04), "
                "and the rule is structural rather than a flag a caller could set"
            )
        if self.category == TEACHER_INCONSISTENCY and (
            len(self.examples) != EXAMPLES_PER_SIDE_BY_SIDE
        ):
            raise SideBySideRequired(
                f"a teacher_inconsistency verdict surfaces {EXAMPLES_PER_SIDE_BY_SIDE} "
                "examples side by side (FR-CALIB-03) — one example is an accusation, "
                "two are a comparison the teacher can resolve"
            )

    @property
    def edit_eligible(self) -> bool:
        """Whether this verdict may produce a proposed edit — derived from the
        category inside the value, never set by a caller. Only
        `rubric_ambiguity` is eligible (`FR-CALIB-02`); the derived form is
        what makes the rule structural rather than a flag."""
        return self.category == EDIT_ELIGIBLE_CATEGORY

    @property
    def fitted(self) -> bool:
        """Whether this finding was fitted to — true only where an edit was
        attached to the one category that must never be fitted to
        (`FR-CALIB-03`). Reads as a tautology because it is one: the
        constructor refuses `teacher_inconsistency` verdicts carrying edits, so
        the property is the checkable statement of that refusal, and a future
        edit that relaxed the constructor would turn this false-flag into the
        failing assertion."""
        return self.category == TEACHER_INCONSISTENCY and (
            self.proposed_edit is not None
        )


@dataclass(frozen=True)
class DiscoveryReport:
    """What discovery found, typed and labelled (`FR-CALIB-01`, `CT-CALIB-03`).

    ``kind`` says what the value is — ambiguity discovery — so a consumer must
    discard the field that names it to mistake it for a measurement of
    accuracy. The field set is the other half of that clause: no rate, no
    matched/total pair, no correctness count — a report that carried
    ``matched: 41, total: 50`` invites the division whether or not anyone
    performs it, and the calibration set is far too small for the result to
    mean anything.

    The stage-level fields are the observability seam: what each stage did,
    next to the status. ``papers_scored`` is the count of papers a comparison
    actually ran on, ``deterministic_excluded`` names the criteria kept out as
    deterministic subjects (#89's separation — a deterministic criterion has
    an answer key, and scoring it with a panel would be theatre),
    ``unscored_papers`` names the papers no comparison ran on — the teacher's
    row missing, or present but with every graded criterion unscored under R0 —
    so ``papers_scored`` and ``len(unscored_papers)`` account for every
    calibration paper, ``alerts``
    carries the aggregate more-than-a-handful alert (`CT-CALIB-14`'s wording,
    fired once on the aggregate rather than per finding), and ``notes``
    carries what each stage did in words — including the honest empty case,
    where nothing was scored and the report says why rather than succeeding
    quietly."""

    kind: str = KIND_AMBIGUITY_DISCOVERY
    package_version: str = ""
    calibration_papers: tuple[str, ...] = ()
    disagreements: tuple[Disagreement, ...] = ()
    papers_scored: int = 0
    deterministic_excluded: tuple[str, ...] = ()
    unscored_papers: tuple[str, ...] = ()
    alerts: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


# --- discovery (FR-CALIB-01) -----------------------------------------------------------------------


def field_names_of(value: Any) -> tuple[str, ...]:
    """The inspectable field names of a structured value, whatever it is.

    Exists because `CT-CALIB-03`'s assertion is over the *shape* of discovery
    output — that no field an accuracy figure falls out of can exist — and a
    sweep that only knows one construction would pass silently over any other.
    A dataclass is read through its fields, a mapping through its keys, a plain
    object through its ``__dict__``; anything else exposes nothing, and the
    caller decides whether an empty sweep is vacuous (the contract case does:
    it refuses to pass over an empty field set).
    """
    fields = getattr(value, "__dataclass_fields__", None)
    if fields is not None:
        return tuple(fields)
    if isinstance(value, Mapping):
        return tuple(value.keys())
    state = getattr(value, "__dict__", None)
    if state:
        return tuple(state)
    return ()


def discover(
    package_version: str,
    calibration_papers: Sequence[str],
    *,
    teacher_bands: Mapping[str, Mapping[str, Any]] | None = None,
    model_bands: Mapping[str, Mapping[str, Any]] | None = None,
    scorer: Callable[[str, str], Any] | None = None,
    evaluation_modes: Mapping[str, str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> DiscoveryReport:
    """Score teacher-graded calibration samples under R₀ and identify
    per-criterion disagreements (`FR-CALIB-01`).

    The samples arrive as ``calibration_papers`` — the refs stored-not-used at
    setup (`FR-SETUP-15`) — and the teacher's grades for them as
    ``teacher_bands`` (paper → criterion → band): the teacher's grades are the
    *second opinion* the disagreement is measured against, never a gold
    standard, and nothing here turns the comparison into one.

    The panel's side is R₀-scoring, through one of two injected transports:

    * ``model_bands`` — the panel's bands under R₀, already scored (paper →
      criterion → band). The recorded-transport form: a run that already
      scored the samples under the same rubric version hands its results over,
      and discovery compares without another model call.
    * ``scorer`` — the scoring seam as a callable, ``(paper, criterion_id)``
      → band. A test binds a deterministic stub or `RecordedFixtureProvider`-
      backed code (the provider stays the only egress point, `CT-PROV-15`);
      production binds the panel. The calibration papers the teacher graded
      are the criteria the teacher graded — discovery scores those, so an
      unscored criterion is one the teacher never graded.

    Both bound at once? The recorded bands win and the scorer stays
    unexercised — one transport per run, and the run's notes name the ignored
    one rather than dropping it silently.

    The rubric version the caller names **is R₀** — the package's current
    delivered version before any edit — and the report carries it as
    ``package_version``, so every disagreement names the instrument both sides
    read. Reading a published version is what discovery does; revising one is
    what only elicitation (#138) through `M-PKG`'s lock may do.

    Deterministic criteria are not calibration subjects (#89's separation, the
    same exclusion `FR-REVIEW-12` draws for the blind sample): a criterion
    declared ``deterministic`` in ``evaluation_modes`` is kept out by name and
    reported in ``deterministic_excluded`` — scoring an answer-key lookup
    with a panel would be theatre, and disagreeing with an answer key is a
    key error, not a rubric ambiguity.

    The report is ambiguity discovery, never a measurement of accuracy
    (`CT-CALIB-03`): it carries the disagreements, what each stage did, and
    nothing an accuracy figure falls out of. Where nothing could be scored the
    report says why in ``notes`` — a bare success over an empty result is the
    silent-failure shape the four seams exist to prevent.

    Raises on programming errors only: a non-string or empty
    ``package_version``, or an empty ``calibration_papers``, is a caller
    defect and raises; a paper with no teacher bands is a finding's absence,
    disclosed in the notes, never an exception.
    """
    if not isinstance(package_version, str) or not package_version.strip():
        raise TypeError(
            f"discover() got package_version={package_version!r}; the rubric "
            "version discovery scores under is R₀ and must be named"
        )
    papers = [str(paper) for paper in calibration_papers]
    if not papers:
        raise ValueError(
            "discover() got no calibration papers — scoring an empty set would "
            "report an empty discovery as a finding (name the samples stored at "
            "setup, FR-SETUP-15)"
        )

    teacher_bands = dict(teacher_bands or {})
    modes = dict(evaluation_modes or {})
    notes: list[str] = [
        f"scored under R0 {package_version}: the package's current delivered "
        "rubric version, before any edit (FR-CALIB-01)"
    ]

    # -- the transport: recorded bands first, then the injected scoring seam ---
    live = model_bands is None and scorer is not None
    if live:
        notes.append(
            "model side scored live through the injected scorer seam; the "
            "provider stays the only egress point (CT-PROV-15)"
        )
    elif model_bands is not None:
        notes.append(
            "model side taken from pre-scored bands recorded under the same "
            "rubric version (the recorded-transport path, CT-PROV-10)"
        )
        if scorer is not None:
            notes.append(
                "a scorer seam is bound beside recorded bands: the recorded "
                "bands win and the callable stays unexercised — one transport "
                "per run, and the ignored one is named rather than silent"
            )
    else:
        notes.append(
            "no scoring transport bound: no paper was scored, and the report "
            "says so rather than reporting an empty discovery as a finding"
        )

    # -- per paper, per criterion: the teacher's band against the panel's -----
    # Comparisons are collected raw and the Disagreement values built after the
    # pass, so the teacher's repeat-label spread (computed over the whole run)
    # is known before the values it appears on are constructed — a frozen
    # value is built once, with its examples already attached.
    raw_disagreements: list[tuple[str, str, Any, Any]] = []
    deterministic_excluded: set[str] = set()
    unscored_papers: list[str] = []
    papers_scored = 0
    # The teacher's repeat labels per criterion, across papers: the material a
    # teacher_inconsistency triage surfaces side by side (FR-CALIB-03), and the
    # per-criterion spread disclosed in the notes.
    teacher_label_pairs: dict[str, list[tuple[str, Any]]] = {}

    for paper in papers:
        teacher_row = teacher_bands.get(paper) or {}
        if not teacher_row:
            unscored_papers.append(paper)
            notes.append(
                f"{paper}: no teacher bands — a calibration sample is a "
                "teacher-graded sample (FR-CALIB-01), and without the teacher's "
                "second opinion there is no disagreement to find"
            )
            continue

        compared_any = False
        for criterion_id, teacher_band in teacher_row.items():
            if modes.get(criterion_id) == EVALUATION_MODE_DETERMINISTIC:
                deterministic_excluded.add(criterion_id)
                continue
            if model_bands is not None:
                model_band = (model_bands.get(paper) or {}).get(criterion_id)
            elif scorer is not None:
                model_band = scorer(paper, criterion_id)
            else:
                model_band = None
            if model_band is None:
                notes.append(
                    f"{paper}/{criterion_id}: no model band under R0, so the "
                    "criterion is unscored rather than agreeing — absence is "
                    "disclosed, never read as agreement (the TC-REQ-68 rule)"
                )
                continue
            compared_any = True
            teacher_label_pairs.setdefault(criterion_id, []).append(
                (paper, teacher_band)
            )
            if model_band != teacher_band:
                raw_disagreements.append(
                    (criterion_id, paper, teacher_band, model_band)
                )

        if compared_any:
            papers_scored += 1
        else:
            # The teacher graded this paper, yet no comparison ran on any of
            # its criteria — every graded criterion was either deterministic
            # (kept out by name) or missing a model band under R0, including
            # the no-transport case where nothing at all was scored. The paper
            # belongs in `unscored_papers` as much as one the teacher never
            # graded: the aggregate field must carry what the notes already
            # disclose, or a consumer reading fields alone misses it.
            unscored_papers.append(paper)
            notes.append(
                f"{paper}: no comparison ran — the teacher graded it, but every "
                "graded criterion was either deterministic-excluded or unscored "
                "under R0; absence is disclosed, never read as agreement"
            )

    # -- the teacher's own repeat labels: side-by-side material, never a fit --
    #: Per criterion, the first two of the teacher's differing repeat labels —
    #: the pair the triage conversation shows side by side (FR-CALIB-03).
    side_by_side: dict[str, tuple[tuple[str, Any], ...]] = {}
    for criterion_id, pairs in teacher_label_pairs.items():
        bands = {str(band) for _paper, band in pairs}
        if len(bands) > 1:
            side_by_side[criterion_id] = tuple(pairs[:2])
            notes.append(
                f"{criterion_id}: the teacher's own labels differ across samples "
                f"({', '.join(sorted(bands))}) — surfaced to the teacher with both "
                "examples side by side at triage, and never fitted to (FR-CALIB-03)"
            )

    disagreements = [
        Disagreement(
            criterion_id=criterion_id,
            sample_id=paper,
            teacher_band=teacher_band,
            model_band=model_band,
            category=None,  # categorizing is triage's judgement, not discovery's
            examples=side_by_side.get(criterion_id, ()),
        )
        for criterion_id, paper, teacher_band, model_band in raw_disagreements
    ]

    # -- the aggregate alert, fired once on the aggregate (CT-CALIB-14) -------
    alerts: list[str] = []
    if len(disagreements) > _ambiguity_alert_after(environ):
        alerts.append(AMBIGUITY_ALERT_TEXT)
        notes.append(
            f"{len(disagreements)} disagreements is more than a handful: the "
            "alert fires once, on the aggregate, as 'the rubric needs a "
            "conversation' — not as one alert per finding (CT-CALIB-14)"
        )

    notes.append(
        f"discovery identified {len(disagreements)} disagreement(s) across "
        f"{papers_scored} scored paper(s); the output is ambiguity discovery, "
        "never a measurement of accuracy (CT-CALIB-03)"
    )
    if deterministic_excluded:
        notes.append(
            "deterministic criteria kept out of calibration: "
            + ", ".join(sorted(deterministic_excluded))
            + " (#89's separation — an answer key is not a calibration subject)"
        )

    report = DiscoveryReport(
        package_version=package_version,
        calibration_papers=tuple(papers),
        disagreements=tuple(disagreements),
        papers_scored=papers_scored,
        deterministic_excluded=tuple(sorted(deterministic_excluded)),
        unscored_papers=tuple(unscored_papers),
        alerts=tuple(alerts),
        notes=tuple(notes),
    )
    LOGGER.info(
        "calibration discovery for %s: %d paper(s), %d scored, %d "
        "disagreement(s), %d deterministic criterion(ies) excluded",
        package_version,
        len(papers),
        papers_scored,
        len(disagreements),
        len(deterministic_excluded),
    )
    return report


# --- triage (FR-CALIB-02..04, CT-CALIB-04) ---------------------------------------------------------


def triage(disagreement: Disagreement) -> TriageVerdict:
    """Categorize one disagreement and return the verdict that records it
    (`FR-CALIB-02`).

    The category is the disagreement's *required* field: one that arrives
    without one is refused with `TriageCategoryRequired`, because an
    uncategorized disagreement would default into some path and the editable
    path is the dangerous default. A category outside the closed set of three
    is a caller defect and raises.

    What each category produces is the eligibility rule, structurally:

    * ``rubric_ambiguity`` — the only edit-eligible verdict
      (`verdict.edit_eligible`). The edit itself does not exist yet: it is
      generated from the teacher's answer during elicitation (#138,
      `CT-CALIB-05`), so ``proposed_edit`` is None at triage even here.
    * ``teacher_inconsistency`` — surfaced with both examples side by side
      (`FR-CALIB-03`): the teacher's repeat labels, normalized to the
      two-slot pair. Never fitted to — ``fitted`` reads False structurally,
      because the verdict constructor refuses an edit on this category.
    * ``model_failure`` — produces a `PipelineFinding` naming the pipeline
      stage the failure lives in (`FR-CALIB-04`), and no rubric edit: the
      category is not edit-eligible, structurally.

    The disagreement's ``pipeline_stage`` declares where a known model failure
    lives when the caller has that evidence; without it the finding names
    ``panel_composition``, the surface a scored-band disagreement is observed
    on — where it was *seen*, never a guess at where it was *caused*.
    """
    if not isinstance(disagreement, Disagreement):
        raise TypeError(
            f"triage() categorizes a Disagreement, got {type(disagreement).__name__}"
        )
    category = disagreement.category
    if not isinstance(category, str) or not category.strip():
        raise TriageCategoryRequired(
            f"criterion {disagreement.criterion_id!r} arrived without its required "
            "triage category (FR-CALIB-02): an uncategorized disagreement would "
            "default into some path, and the editable path is the dangerous default"
        )
    if category not in TRIAGE_CATEGORIES:
        raise ValueError(
            f"triage category {category!r} is outside the closed set "
            f"{sorted(TRIAGE_CATEGORIES)} (FR-CALIB-02 names the three)"
        )

    examples: tuple[Any, ...] = tuple(disagreement.examples)
    pipeline_finding: PipelineFinding | None = None
    if category == TEACHER_INCONSISTENCY:
        # The side-by-side pair: exactly two slots, from the teacher's repeat
        # labels. More than two displays its first two as the pair; fewer pads
        # to the pair's shape so the verdict can exist while the examples the
        # teacher needs to compare are still being collected — the surface is
        # structural, and the unfilled slot is visible as None rather than the
        # pair pretending to be complete.
        examples = (examples + (None,) * EXAMPLES_PER_SIDE_BY_SIDE)[
            :EXAMPLES_PER_SIDE_BY_SIDE
        ]
    if category == MODEL_FAILURE:
        stage = disagreement.pipeline_stage or DEFAULT_PIPELINE_STAGE
        pipeline_finding = PipelineFinding(
            criterion_id=disagreement.criterion_id,
            stage=stage,
            detail=(
                f"model failure on criterion {disagreement.criterion_id}: the "
                "pipeline finding routes the failure to the pipeline; the rubric "
                "is not the problem and is not edited (FR-CALIB-04)"
            ),
        )

    verdict = TriageVerdict(
        criterion_id=disagreement.criterion_id,
        category=category,
        examples=examples,
        pipeline_finding=pipeline_finding,
        # No proposed edit on any path at triage: rubric_ambiguity is *eligible*
        # for one, and the edit is generated from the teacher's answer during
        # elicitation (#138, CT-CALIB-05) — the model's job never rises above
        # proposing the question.
        proposed_edit=None,
    )
    LOGGER.info(
        "triaged %s/%s as %s (edit_eligible=%s, pipeline_finding=%s)",
        disagreement.sample_id or "-",
        disagreement.criterion_id,
        category,
        verdict.edit_eligible,
        pipeline_finding.stage if pipeline_finding else "-",
    )
    return verdict


# --- the elicitation cap (FR-CALIB-05, seam 3) ------------------------------------------------------
#
# "The teacher answers no more than CALIB_MAX_QUESTIONS questions" — NFR-CALIB-01's
# teacher-time budget expressed as an exact number, not a guideline. The cap is the
# knob (seam 3): teacher time is environment-shaped too, so the value is read at call
# time under `HARNESS_CALIB_MAX_QUESTIONS`, production value as the default, a mis-set
# or out-of-range value falling back rather than raising — a mis-set knob must not stop
# a calibration, and the run outcome discloses what actually applied.

CALIB_MAX_QUESTIONS: int = 6
CALIB_MAX_QUESTIONS_ENV: str = "HARNESS_CALIB_MAX_QUESTIONS"


def _max_questions(environ: Mapping[str, str] | None = None) -> int:
    """The elicitation cap, read at call time (seam 3). A value below 1 would ask the
    teacher nothing and call it calibration — outside the knob's meaning — so it falls
    back to the declared default like any other mis-set value."""
    source = os.environ if environ is None else environ
    raw = source.get(CALIB_MAX_QUESTIONS_ENV)
    if raw is None or not raw.strip():
        return CALIB_MAX_QUESTIONS
    try:
        value = int(raw)
    except ValueError:
        return CALIB_MAX_QUESTIONS
    return value if value >= 1 else CALIB_MAX_QUESTIONS


# --- phasing: the §6.2 lock is a dependency, declared not inferred (CT-CALIB-15) --------------------
#
# "Triage, dual-scoring non-inferiority and back-translation are Phase 3; elicitation is
# Phase 4; the §6.2 lock they depend on is Phase 1 and belongs to M-PKG." The lock is what
# makes CT-CALIB-06 structural: every calibration edit routes through M-PKG, so the lock
# applies to calibration output without this module implementing a check of its own. An
# edit attempted against a package version created BEFORE the lock existed would bypass
# that guarantee — so the vintage is a declared fact, not an inferred one (see the module
# docstring), and `apply_answers` refuses it.


class PhaseDependencyError(CalibrationError):
    """An edit was attempted against a package version whose schema predates the §6.2
    lock the edit's route depends on (`CT-CALIB-15`).

    The lock is a Phase 1 fact about the schema a version was born under, and a version
    born before it cannot carry the guarantee that makes calibration's write route
    structural: the catalog would apply the edit, but the lock that every accumulated
    validation record leans on was not yet in the file. The refusal names the version
    and the dependency; the fix is a version created under the current schema."""


#: The declaration seam: version id -> the Tier P migration version the version was
#: created under. Deliberately declared, never inferred — nothing in a version's
#: content can recover when it was born, and an inference would silently claim the
#: lock's guarantee for versions created before the lock existed. Unregistered
#: versions read as created under the current schema.
_VERSION_SCHEMA_VINTAGES: dict[str, int] = {}

#: The migration that installed the lock's columns on package_version (aeh.pkg's third
#: migration). A version born under an earlier migration predates the lock.
_LOCK_ARRIVAL_MIGRATION = 3

#: A vintage from before the first content-bearing migration, used for the pre-lock
#: declaration below — the earliest schema a real package file could have been built on.
_PRE_LOCK_VINTAGE = 1

_FIXTURE_PRE_LOCK_VERSION = "pkg-v1-pre-lock"


def package_version_predating_schema_lock() -> str:
    """Declare (and return) a package version born before the §6.2 lock existed.

    This is the seam a caller or test uses to name such a version — the registry above
    is deliberately not a thing the module populates from the store, because vintage is
    a fact about a file's history that no content can recover. `apply_answers` refuses
    a declared pre-lock version with `PhaseDependencyError` (`CT-CALIB-15`)."""
    _VERSION_SCHEMA_VINTAGES[_FIXTURE_PRE_LOCK_VERSION] = _PRE_LOCK_VINTAGE
    LOGGER.info("declared pre-lock vintage %d for package version %r",
                _PRE_LOCK_VINTAGE, _FIXTURE_PRE_LOCK_VERSION)
    return _FIXTURE_PRE_LOCK_VERSION


def _refuse_pre_lock_vintage(version_id: str) -> None:
    """Refuse an edit against a version created before the §6.2 lock existed."""
    vintage = _VERSION_SCHEMA_VINTAGES.get(version_id, _LOCK_ARRIVAL_MIGRATION)
    if vintage < _LOCK_ARRIVAL_MIGRATION:
        raise PhaseDependencyError(
            f"package version {version_id!r} was created under Tier P schema migration "
            f"{vintage}, which predates the §6.2 schema lock (installed by migration "
            f"{_LOCK_ARRIVAL_MIGRATION}): the guarantee that every edit routes through "
            "M-PKG's guard does not hold for it, so no calibration edit is applied "
            "against it (CT-CALIB-15). The version needs re-importing under the current "
            "schema before it can be clarified."
        )


# --- elicitation: a question with options, never a pre-authored edit (CT-CALIB-05) ------------------
#
# "Elicitation presents OPTIONS, never a pre-authored rubric edit — the teacher's ANSWER
# generates the edit." The two halves of that sentence are both structural here: the
# question value carries options and carries no edit field at all (not an edit field
# that happens to be None — the attribute does not exist), and the edit is generated
# from the answer at application time, deterministically, through M-PKG.

#: The options an elicitation question offers. A prompt to a person, not an API
#: contract: the teacher may also answer in their own words, and `apply_answers`
#: composes the edit from the band's current descriptor and the answer — with
#: *keep as is* generating no edit at all (see the module docstring).
QUESTION_OPTIONS: tuple[str, ...] = ("broaden", "narrow", "keep as is")


@dataclass(frozen=True)
class Finding:
    """One ambiguity a calibration run would elicit on: the criterion it lives in, the
    triage category it was given (`CT-CALIB-04`'s required field — a finding without
    one is not elicitable), how many submissions the ambiguity affects (`FR-CALIB-05`'s
    ranking input), the two examples the question shows side by side, and the band
    ordinal whose descriptor the ambiguity lives in — a criterion's bands each say
    something, and an edit that clarifies one must not silently touch another."""

    criterion_id: str
    category: str
    submissions_affected: int
    examples: tuple[str | None, ...] = ()
    band_ordinal: int = 0


@dataclass(frozen=True)
class ElicitationQuestion:
    """One question the teacher is asked. Options are present, examples are exactly the
    two NFR-CALIB-01 budgets, and — the load-bearing shape — there is NO edit field on
    this value at all: `proposed_edit` is not merely unset (`CT-CALIB-05`). An edit
    arrives into the world only when the teacher's answer is applied."""

    question_id: str
    criterion_id: str
    question: str
    options: tuple[str, ...]
    examples: tuple[str | None, ...]
    submissions_affected: int
    band_ordinal: int = 0


#: The session of questions the most recent `elicit` call asked, so `apply_answers`
#: can resolve an answer's question id back to its criterion and its wording. A module
#: global because elicitation and application are two calls a teacher makes minutes
#: apart, not two arguments of one call; the resolution rule is stated on
#: `_resolve_criterion`.
_ACTIVE_QUESTIONS: list[ElicitationQuestion] = []


def elicit(
    findings: Sequence[Finding], *, environ: Mapping[str, str] | None = None
) -> tuple[ElicitationQuestion, ...]:
    """Turn edit-eligible findings into at most `CALIB_MAX_QUESTIONS` questions.

    Ranked by how many submissions the ambiguity affects (`FR-CALIB-05`), ties broken
    by criterion id for determinism, and capped at the env-read knob — together the cap
    and the ranking decide which ambiguities the teacher never sees, which is why the
    cap is asserted exactly in the contract suite (`CT-CALIB-05`).

    Each question carries `QUESTION_OPTIONS` and exactly two examples (NFR-CALIB-01's
    side-by-side pair) — and no edit, on any path (`CT-CALIB-05`). The questions asked
    become the session `apply_answers` resolves answers against.
    """
    eligible = [f for f in findings if f.category == EDIT_ELIGIBLE_CATEGORY]
    ranked = sorted(eligible, key=lambda f: (-f.submissions_affected, f.criterion_id))
    cap = _max_questions(environ)
    questions = []
    for position, finding in enumerate(ranked[:cap], start=1):
        examples = tuple(finding.examples)[:EXAMPLES_PER_SIDE_BY_SIDE]
        examples = examples + (None,) * (EXAMPLES_PER_SIDE_BY_SIDE - len(examples))
        questions.append(
            ElicitationQuestion(
                question_id=f"q{position}",
                criterion_id=finding.criterion_id,
                question=(
                    f"criterion {finding.criterion_id} reads ambiguously to "
                    f"{finding.submissions_affected} submissions: should its descriptor "
                    "be broadened, narrowed, or kept as is?"
                ),
                options=QUESTION_OPTIONS,
                examples=examples,
                submissions_affected=finding.submissions_affected,
                band_ordinal=finding.band_ordinal,
            )
        )
    global _ACTIVE_QUESTIONS
    _ACTIVE_QUESTIONS = questions
    LOGGER.info(
        "elicitation asked %d of %d eligible findings (cap=%d, env=%s)",
        len(questions), len(eligible), cap,
        os.environ.get(CALIB_MAX_QUESTIONS_ENV, "<unset>") if environ is None
        else environ.get(CALIB_MAX_QUESTIONS_ENV, "<unset>"),
    )
    return tuple(questions)


# --- the lock write-path: every edit through M-PKG, no second check (FR-CALIB-07) -------------------
#
# CT-CALIB-06 makes the lock structural by ROUTING: this module has no copy of the
# forbidden-field list and no guard of its own — a second implementation of one rule is
# what drifts (RISK-06). The refused-edit door below exists so the sweep can drive each
# locked field through the catalog and watch the catalog's own guard raise.

#: The §6.2 field names an edit can touch, in the HLD's vocabulary — the same names the
#: contract sweep parametrizes over. These are message/route names, never a gate: the
#: gate is the catalog's `_guard` (`NFR-PKG-03`), reached through the routing map below.
LOCKED_FIELD_NAMES: tuple[str, ...] = (
    "max_points",
    "criterion_count",
    "question_type",
    "scoring_model",
    "construct_tag",
    "criterion_band",
    "criterion_dependency",
)


@dataclass(frozen=True)
class LockedFieldEdit:
    """An edit touching one §6.2-locked field — the input of the forced-edit door.

    The door exists to demonstrate refusal, not to permit: every field in the
    vocabulary is locked, so every door call raises `SchemaLockViolation` raised by the
    catalog's guard (`raised_by == "catalog"`, `CT-CALIB-06`)."""

    locked_field: str
    criterion_id: str
    description: str


def edit_touching(locked_field: str) -> LockedFieldEdit:
    """Build the edit that would touch one locked field, for the refusal sweep.

    `criterion_count` is the one door whose target is not an existing criterion —
    adding one needs an id nothing is using yet; the rest address the criterion the
    test package carries (`_FIXTURE_CRITERION_ID`)."""
    if locked_field not in LOCKED_FIELD_NAMES:
        raise CalibrationError(
            f"unknown locked field {locked_field!r}; the §6.2 vocabulary is "
            f"{LOCKED_FIELD_NAMES}."
        )
    criterion_id = (
        "CRIT-CALIB-NEW" if locked_field == "criterion_count" else _FIXTURE_CRITERION_ID
    )
    return LockedFieldEdit(
        locked_field=locked_field,
        criterion_id=criterion_id,
        description=f"an edit altering the {locked_field} of the published rubric",
    )


def _route_forced_edit(catalog: Any, base: str, edit: LockedFieldEdit) -> None:
    """Send a forced edit through the catalog door whose guard covers its field.

    One route per vocabulary name, all on the PUBLISHED base — so the catalog's own
    `_guard` raises, which is the entire point: this module performs no lock check of
    its own (`CT-CALIB-06`), it merely offers the edit to the one implementation."""
    field = edit.locked_field
    criterion = edit.criterion_id
    if field == "max_points":
        catalog.update_criterion_field(base, criterion, "max_points", 5.0)
    elif field == "criterion_count":
        catalog.add_criterion(base, criterion)
    elif field == "question_type":
        catalog.update_criterion_field(base, criterion, "question_type", "mcq")
    elif field == "scoring_model":
        catalog.update_criterion_field(base, criterion, "scoring_model", "atomic")
    elif field == "construct_tag":
        catalog.update_criterion_field(base, criterion, "construct_tag", "clarity")
    elif field == "criterion_band":
        catalog.update_band_field(base, criterion, 0, "label", "Clarified")
    elif field == "criterion_dependency":
        catalog.update_criterion_dependency(base)
    else:  # unreachable: `edit_touching` validates against the same tuple
        raise CalibrationError(f"no catalog door routes a {field!r} edit.")


def _clarified_descriptor(
    current_descriptor: str, answer: str
) -> str | None:
    """The descriptor the teacher's answer generates, or `None` when it generates none
    (`CT-CALIB-05`: the answer, never the model, produces the edit).

    Composition, not replacement: the band's descriptor as it stands is the base of
    every result, because a revision that erased what the band means would be the
    edit destroying the very thing it claims to clarify — and the NEXT calibration
    would chain on the erased text. The answer's first word reads as an intent and
    the directional clause is appended to the current text; anything else is the
    teacher's own clarification, appended verbatim; *keep as is* (or an empty
    answer) is `None` — no edit exists to generate, and the confirmation belongs
    in the history row, which the caller writes either way. There is no closed
    answer schema to reject against — the question's options are a prompt to a
    person, and refusing a teacher's own words would send them back to the interface
    for no safety gain: the edit still goes through the catalog's guard."""
    base = current_descriptor.strip() or "the band's descriptor"
    stripped = answer.strip()
    first = stripped.lower().split(" ", 1)[0] if stripped else ""
    if first == "keep" or not stripped:
        return None
    if first == "broaden":
        return (f"{base}; broadened to also cover responses that only partially "
                "meet the criterion")
    if first == "narrow":
        return f"{base}; narrowed to responses that fully meet the criterion"
    return f"{base}; {stripped}"


#: The session question ids are `q1..qn`; the number picks the criterion positionally
#: when the session and the version disagree (see the module docstring).
_QUESTION_ID_PATTERN = re.compile(r"q(\d+)")


def _resolve_criterion(
    question_id: str, criterion_ids: Sequence[str], base: str
) -> tuple[str, str, int]:
    """Resolve one answer's question id to a criterion of the version being edited,
    with the question text the history row will record and the band ordinal to clarify.

    The session's own mapping wins only when its criterion still exists in the version
    being edited — discovery and elicitation can run against different revisions of the
    same rubric without the ambiguity having moved. Otherwise the question id's position
    picks the criterion from the version's own ordering (the order the catalog reports
    the version's criteria in), and the recorded question is the generic form naming
    THAT criterion — never a session wording that names a criterion the edit does not
    touch, which is the row that would lie about what happened. The fallback band is
    ordinal 0: a positional resolution carries no band information of its own."""
    session = {question.question_id: question for question in _ACTIVE_QUESTIONS}
    asked = session.get(question_id)
    if asked is not None and asked.criterion_id in criterion_ids:
        return asked.criterion_id, asked.question, asked.band_ordinal
    match = _QUESTION_ID_PATTERN.fullmatch(question_id)
    if match is not None:
        position = int(match.group(1))
        if 1 <= position <= len(criterion_ids):
            criterion_id = criterion_ids[position - 1]
            question_text = (
                f"should the descriptor of criterion {criterion_id} be broadened, "
                "narrowed, or kept as is?"
            )
            return criterion_id, question_text, 0
    raise CalibrationError(
        f"the answer {question_id!r} matches no criterion of package version {base!r} "
        f"(its criteria are {list(criterion_ids)}). Answers are keyed by the elicitation "
        "session's question ids (q1..qn), resolved against the version being edited."
    )


def apply_answers(
    answers: Mapping[str, str],
    *,
    catalog: Any | None = None,
    package_version: str | None = None,
    forced_edit: LockedFieldEdit | None = None,
) -> str | None:
    """Apply the teacher's answers as rubric clarifications, written through `M-PKG`.

    Every edit follows the catalog's own revision flow (`FR-PKG-04`): a new version is
    created as a copy of the one being clarified, the descriptor edit lands on the
    unlocked copy, and the conversation that produced it is appended to the elicitation
    history on the published base (`FR-CALIB-13`/`-14`). Nothing here writes a locked
    field, and nothing here writes anywhere but through the catalog — `M-CALIB` has no
    second check of its own (`FR-CALIB-07`, `CT-CALIB-06`).

    Three doors:

    * the ordinary one — `answers` keyed by elicitation question id, applied against
      `package_version` or the catalog's latest version; one new version per EDIT (a
      *keep as is* answer generates no edit: no version is minted and its history row
      records an empty `resulting_edit`), each copy parented on the previous, so the
      history's `resulting_edit` names the version its answer produced. Returns the
      last version an edit landed on, or `None` when every answer kept the rubric
      as is — no edit exists to return;
    * the forced-edit door — `forced_edit` routes one locked-field edit through the
      catalog on the published base, which refuses it with `SchemaLockViolation` (the
      sweep's vehicle; nothing lands, nothing is appended, `None` returns);
    * the refusal that precedes both — an edit against a declared pre-lock vintage
      raises `PhaseDependencyError` (`CT-CALIB-15`).
    """
    if not isinstance(answers, Mapping) or not answers:
        raise CalibrationError(
            "apply_answers requires at least one answer keyed by an elicitation "
            f"question id; got {type(answers).__name__}."
        )
    if package_version is not None:
        _refuse_pre_lock_vintage(package_version)
    if forced_edit is not None:
        if catalog is None:
            raise CalibrationError(
                "a forced edit needs the catalog it is routed through: pass the same "
                "catalog the real edit would take (CT-CALIB-06)."
            )
        base = package_version if package_version is not None else catalog.latest_version()
        if base is None:
            raise CalibrationError("the package carries no version for the edit to touch.")
        _refuse_pre_lock_vintage(base)
        _route_forced_edit(catalog, base, forced_edit)
        return None
    if package_version is None:
        if catalog is None:
            raise CalibrationError(
                "apply_answers needs the catalog the edit is written through "
                "(FR-CALIB-07), or an explicit package_version to clarify."
            )
        base = catalog.latest_version()
    else:
        base = package_version
    if base is None:
        raise CalibrationError("the package carries no version to calibrate against.")
    _refuse_pre_lock_vintage(base)
    rows = catalog.criteria(base)
    # The version's OWN ordering, not an alphabetical rewrite of it: the positional
    # fallback resolves qN against the order the catalog reports, so the docstring's
    # claim and the resolution agree.
    criterion_ids = list(dict.fromkeys(row["criterion_id"] for row in rows))
    if not criterion_ids:
        raise CalibrationError(
            f"package version {base!r} carries no criteria to clarify."
        )
    current = base
    for question_id, answer in sorted(answers.items()):
        criterion_id, question_text, band_ordinal = _resolve_criterion(
            question_id, criterion_ids, base
        )
        # Probe the answer's intent BEFORE minting anything: the keep/empty rule
        # lives in `_clarified_descriptor` alone, and a probe against a placeholder
        # base answers "does this answer generate an edit at all" without one.
        if _clarified_descriptor("", answer) is None:
            # *Keep as is*: no edit exists to generate. Nothing lands on the rubric,
            # no version is minted, and the confirmation lives in the history row.
            catalog.append_elicitation(
                base, question_text, list(QUESTION_OPTIONS), answer, resulting_edit="",
            )
            LOGGER.info(
                "calibration answer kept the rubric as is: criterion %s (question %s), "
                "no edit",
                criterion_id, question_id,
            )
            continue
        current = catalog.create_version(current)
        # Read the descriptor being clarified off the freshly minted copy: the copy
        # carries the base's bands verbatim (the revision flow's verbatim copy) and is
        # now the file's latest version, which is the one `bands()` reads — so the
        # composition composes against the text being edited, whatever version that is.
        bands = catalog.bands(criterion_id)
        band_row = next(
            (row for row in bands if row.get("ordinal") == band_ordinal), None
        )
        if band_row is None and 0 <= band_ordinal < len(bands):
            band_row = bands[band_ordinal]
        current_descriptor = (band_row or {}).get("descriptor", "") or ""
        clarified = _clarified_descriptor(current_descriptor, answer)
        if clarified is None:  # unreachable: the probe above proved the answer edits
            raise CalibrationError(
                f"the answer for {question_id!r} generated no edit on the second "
                "resolution — an internal inconsistency in answer handling."
            )
        catalog.update_band_field(current, criterion_id, band_ordinal, "descriptor",
                                  clarified)
        catalog.append_elicitation(
            base, question_text, list(QUESTION_OPTIONS), answer, resulting_edit=current,
        )
        LOGGER.info(
            "calibration edit landed: version %s clarifies criterion %s band %d "
            "(question %s)",
            current, criterion_id, band_ordinal, question_id,
        )
    return None if current is base else current


# --- the headless driver: one run, structured outcome (CT-CALIB-10, CT-CALIB-01) --------------------
#
# run_for_assignment is the module's headless entry point: given an assignment's
# situation it returns what happened and why — which rubric grades the class, whether
# anything was skipped and on what grounds, what was asked, what landed. Never a bare
# status (seam 4), and never on the critical path of grade delivery (CT-CALIB-01):
# every branch either grades against R₀ as given or lands an edit whose going-live is
# the gates' decision, not this module's.

#: The R₀ default the assignment factory pins — the same value the contract suite pins,
#: so "graded against R₀" is checked against a value the caller chose.
_DEFAULT_R0_VERSION = "pkg-v1-r0"


@dataclass(frozen=True)
class Assignment:
    """One assignment's calibration situation: whether the rubric was published to
    students in advance (`FR-CALIB-12` — the case where calibration must default to
    R₀ and say why), whether the teacher skipped calibration (`FR-CALIB-13`'s lower-
    confidence path), which version is R₀ for this assignment, and which criteria the
    discovery round flagged as ambiguous (the ones a skip must mark lower-confidence)."""

    rubric_published_in_advance: bool = False
    skip_elicitation: bool = False
    r0_version: str = _DEFAULT_R0_VERSION
    ambiguous_criteria: tuple[str, ...] = ()


def assignment(
    *,
    rubric_published_in_advance: bool = False,
    skip_elicitation: bool = False,
    r0_version: str = _DEFAULT_R0_VERSION,
    ambiguous_criteria: Sequence[str] = (),
) -> Assignment:
    """Build an `Assignment` — the driver's input value, with the R₀ default pinned."""
    return Assignment(
        rubric_published_in_advance=rubric_published_in_advance,
        skip_elicitation=skip_elicitation,
        r0_version=r0_version,
        ambiguous_criteria=tuple(ambiguous_criteria),
    )


@dataclass(frozen=True)
class CalibrationRunOutcome:
    """What one calibration run did, per stage (seam 4) — never a bare status.

    `active_rubric` is the rubric this run's grades use; `revised_version` is the
    version an edit landed on, when one did. The two are different fields on purpose:
    a revision that landed is not a revision that went live — whether it grades the
    next pass is the gates' decision (#139), and an outcome that quietly promoted its
    own revision would be a revision shipped with a warning by another name."""

    r0_version: str
    active_rubric: str
    fairness_note: str
    skipped: bool
    questions_asked: int = 0
    revised_version: str | None = None
    lower_confidence_criteria: tuple[str, ...] = ()
    revision_shipped: bool = False
    notes: tuple[str, ...] = ()

    @property
    def ambiguous_criteria_lower_confidence(self) -> bool:
        """Whether the ambiguous criteria were actually marked lower-confidence —
        the second half of `FR-CALIB-10`'s terminal state ("grade with the rubric
        as given, be more conservative on the ambiguous criteria"), which a run
        that only reported its rubric would otherwise fail silently."""
        return bool(self.lower_confidence_criteria)

    @property
    def shipped_with_warning(self) -> bool:
        """Structurally False (`CT-CALIB-02`): no code path on this surface ships a
        revision carrying a warning. A warned revision is a revision — it goes live,
        scores the class, and carries construct drift into every accumulated
        validation record (RISK-06) — so the clause forbids the path, not just the
        silent version of it. The property is the checkable statement of that refusal,
        in the same shape as `TriageVerdict`'s `fitted`: a caller asserts it, and a
        code path that could set it True cannot be written without the assertion
        failing."""
        return False


def run_for_assignment(
    assignment: Assignment,
    *,
    findings: Sequence[Finding] | None = None,
    answers: Mapping[str, str] | None = None,
    catalog: Any | None = None,
    environ: Mapping[str, str] | None = None,
) -> CalibrationRunOutcome:
    """Run calibration for one assignment and return what it did, per stage.

    The published branch is the clause with teeth (`CT-CALIB-10`/`FR-CALIB-12`): where
    the rubric was published to students in advance, calibration defaults to R₀ and
    SAYS WHY — a silent default is correct behaviour nobody can see. The skip branch
    grades the class with R₀ unchanged, marks the ambiguous criteria lower-confidence
    (`FR-CALIB-13`), and applies nothing — the skip is never on the critical path
    (`CT-CALIB-01`). The full branch elicits, applies the answers through the catalog,
    and reports the revision as landed-but-not-live: the gates own that decision."""
    lower_confidence = tuple(assignment.ambiguous_criteria)
    if assignment.rubric_published_in_advance:
        return CalibrationRunOutcome(
            r0_version=assignment.r0_version,
            active_rubric=assignment.r0_version,
            fairness_note=(
                "the rubric was published to students in advance: revising it now would "
                "change the assignment after the students answered it, so calibration "
                f"defaulted to R₀ ({assignment.r0_version}) and the flagged ambiguities "
                "are recorded for the next cohort's rubric"
            ),
            skipped=True,
            lower_confidence_criteria=lower_confidence,
            revision_shipped=False,
            notes=("rubric published in advance: defaulted to R₀, nothing elicited, "
                   "nothing applied",),
        )
    if assignment.skip_elicitation:
        return CalibrationRunOutcome(
            r0_version=assignment.r0_version,
            active_rubric=assignment.r0_version,
            fairness_note=(
                "calibration was skipped for this run: the class is graded against R₀ "
                f"({assignment.r0_version}) unchanged, no edit exists to apply, and the "
                "ambiguous criteria are marked lower-confidence"
            ),
            skipped=True,
            lower_confidence_criteria=lower_confidence,
            revision_shipped=False,
            notes=("skipped by the assignment: no questions asked, no edit applied "
                   "(CT-CALIB-01: never on the critical path)",),
        )
    if not findings or not answers or catalog is None:
        return CalibrationRunOutcome(
            r0_version=assignment.r0_version,
            active_rubric=assignment.r0_version,
            fairness_note=(
                "nothing to calibrate this run (no findings, no answers, or no catalog "
                "to write through): the class is graded against R₀ "
                f"({assignment.r0_version}) unchanged"
            ),
            skipped=True,
            lower_confidence_criteria=lower_confidence,
            revision_shipped=False,
            notes=("no calibration inputs provided; the run degrades to a skip, never "
                   "to a blocked grade",),
        )
    questions = elicit(findings, environ=environ)
    revised = apply_answers(answers, catalog=catalog)
    if revised is None:
        # Every answer kept the rubric as is: no edit exists, so the run degrades to
        # the skip's outcome (R₀ unchanged) with the questions still on the record.
        return CalibrationRunOutcome(
            r0_version=assignment.r0_version,
            active_rubric=assignment.r0_version,
            fairness_note=(
                "the teacher kept every ambiguous descriptor as is: no edit exists to "
                f"apply, and the class is graded against R₀ ({assignment.r0_version}) "
                "unchanged"
            ),
            skipped=True,
            questions_asked=len(questions),
            revised_version=None,
            lower_confidence_criteria=lower_confidence,
            revision_shipped=False,
            notes=("all answers kept the rubric as is: the conversation is in the "
                   "elicitation history, and no revision landed",),
        )
    return CalibrationRunOutcome(
        r0_version=assignment.r0_version,
        active_rubric=assignment.r0_version,
        fairness_note=(
            "the teacher's answers produced a revision through M-PKG; whether it grades "
            "the next pass is the gates' decision (FR-CALIB-08/-09, #139), so this "
            f"run's grades stay on R₀ ({assignment.r0_version})"
        ),
        skipped=False,
        questions_asked=len(questions),
        revised_version=revised,
        lower_confidence_criteria=lower_confidence,
        revision_shipped=False,
        notes=(
            f"the revision landed as version {revised!r}, one new version per edit, "
            "each recorded in the elicitation history; the gates decide whether it goes "
            "live",
        ),
    )


# --- the two guardrail gates (#139, FR-CALIB-08/-11, §6.5–§6.7) -------------------------------------
#
# Between a proposed revision and a live one sit two gates, and every failure mode ends at
# R₀ (CT-CALIB-02): a revision is the rubric's construct changing shape, and the construct
# is what every accumulated validation record describes (RISK-06) — so the gates are
# evidence gates about construct stability, never quality gates, and no outcome ships a
# revision carrying a warning.

#: The cohort id that names the calibration set itself. The gate refuses it
#: (`NFR-CALIB-02`: the calibration set *"lacks the sample size to mean anything"* — a gate
#: run on twenty papers returns a number, and a number that means nothing is worse than no
#: number, because it is a passed gate somebody will cite).
CALIBRATION_SET = "calibration-set"

#: The threshold §6.5 states as an **example** ("reject if more than 10% of the class
#: shifts by a full rubric level"). It is deliberately *not* the gate's default
#: (`CT-CALIB-13`): the design is explicit that it is "an example value from the HLD, not a
#: validated one" and "must be declared per institution before use" — so the constant
#: exists to be read and documented, and the gate refuses to run until somebody declares
#: their own (an argument, `declare_institutional_threshold`, or the deployment's env
#: channel below).
CALIB_NONINFERIORITY_THRESHOLD: float = 0.10
CALIB_NONINFERIORITY_THRESHOLD_ENV: str = "HARNESS_CALIB_NONINFERIORITY_THRESHOLD"

#: The off-panel checker this deployment names — declared as None because the vocabulary
#: pins the knob and the deployment sets it, as ``provider/build_id[/quantization]``.
#: `back_translate` reads it when the caller passes no explicit checker (the env channel
#: outranks the constant, the way the threshold's channel does); nothing declared is the
#: enumerated unavailable mode — the gate never invents an adversary. The construction
#: transport a run actually uses is bound per build in `_OFF_PANEL_SESSIONS` (the
#: recorded-transport form); a build with no bound session is *unavailable*, never invented.
CALIB_OFF_PANEL_MODEL: str | None = None
CALIB_OFF_PANEL_MODEL_ENV: str = "HARNESS_CALIB_OFF_PANEL_MODEL"


def _off_panel_model_declared(
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """The deployment's declared off-panel checker, read at call time (seam 3).

    The env channel outranks the constant, the way the threshold's channel does; a
    blank value is unset. None means the deployment declared no checker, and the gate
    refuses with the refusal that names the knob rather than inventing a checker."""
    source = os.environ if environ is None else environ
    raw = source.get(CALIB_OFF_PANEL_MODEL_ENV)
    if raw is not None and raw.strip():
        return raw.strip()
    return CALIB_OFF_PANEL_MODEL


def _off_panel_model_ref_from_declared(declared: str) -> OffPanelModelRef:
    """The `OffPanelModelRef` a declared checker string names: ``provider/build_id``
    with an optional ``/quantization``. A string the module cannot read is a
    mis-declared knob, refused with its name — a misconfiguration is a rejected
    config rather than a silent weakening (`NFR-CALIB-04`)."""
    parts = declared.split("/")
    if len(parts) == 2 and all(parts):
        return OffPanelModelRef(provider=parts[0], build_id=parts[1])
    if len(parts) == 3 and all(parts):
        return OffPanelModelRef(provider=parts[0], build_id=parts[1], quantization=parts[2])
    raise OffPanelConfigurationError(
        f"the declared off-panel checker {declared!r} is not one this module can name: "
        f"declare it as provider/build_id[/quantization] (in {CALIB_OFF_PANEL_MODEL_ENV} "
        "or CALIB_OFF_PANEL_MODEL)"
    )

#: The class-size cap (seam 3). Production default is None — **no cap**: the gate scores
#: the full class (`NFR-CALIB-02`), and a set cap refuses an oversized class rather than
#: silently scoring a subset, because a gate over a subset is not the gate the requirement
#: describes.
CALIB_CLASS_SIZE_CAP: int | None = None
CALIB_CLASS_SIZE_CAP_ENV: str = "HARNESS_CALIB_CLASS_SIZE_CAP"


def _noninferiority_threshold_from_env(
    environ: Mapping[str, str] | None = None,
) -> float | None:
    """The env fallback for the threshold (seam 3), or None when unset or mis-set.

    A value outside [0, 1] is treated as unset rather than raising: the mis-set value
    then falls through to the refusal that names the real problem — no threshold
    declared — instead of a ValueError about string parsing."""
    source = os.environ if environ is None else environ
    raw = source.get(CALIB_NONINFERIORITY_THRESHOLD_ENV)
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if 0.0 <= value <= 1.0 else None


def _class_size_cap(environ: Mapping[str, str] | None = None) -> int | None:
    """The class-size cap, read at call time (seam 3). None is the production default:
    the gate scores the full class. A mis-set value falls back rather than raising — a
    mis-set knob must not stop the gate, and the over-cap refusal path carries its own
    name."""
    source = os.environ if environ is None else environ
    raw = source.get(CALIB_CLASS_SIZE_CAP_ENV)
    if raw is None or not raw.strip():
        return CALIB_CLASS_SIZE_CAP
    try:
        value = int(raw)
    except ValueError:
        return CALIB_CLASS_SIZE_CAP
    return value if value >= 1 else CALIB_CLASS_SIZE_CAP


class ThresholdNotDeclared(CalibrationError):
    """The non-inferiority gate was asked to run with no threshold declared for it
    (`FR-CALIB-08`, `CT-CALIB-13`).

    The threshold is an **owned decision**: 0.10 is the HLD's *example*, not a validated
    value, and the design says it "must be declared per institution before use". A gate
    that fell back to a default would let an unowned number decide whether a rubric
    changes — the institution that inherits it never chose it. Declare one (an explicit
    argument, `declare_institutional_threshold`, or the deployment's env) and the gate
    runs; with neither, this is the refusal."""


class InsufficientPopulation(CalibrationError):
    """The gate was asked to run on a population that cannot carry its verdict
    (`NFR-CALIB-02`, `CT-CALIB-07`).

    The gate operates on the **full class** and refuses the calibration set, which lacks
    the sample size to mean anything. A refusal rather than a warning, because a gate run
    on twenty papers returns a number — and a number that means nothing is a passed gate
    somebody will cite."""


class OffPanelConfigurationError(CalibrationError):
    """The off-panel model is **in the scoring panel** (`CT-CALIB-08`, `NFR-CALIB-04`).

    Refused when the *build* matches, not merely the label — two entries naming the same
    served build are the same model, which is the identity `M-CONF`'s
    `compute_panel_build_ref` hashes (and what `RunConfig.__post_init__` refuses at
    configuration time). A shared build would let the panel's own blind spots define the
    adversarial search: the model looking for a response on which R₀ and R₁ differ would
    be the same model that produced the scores, so the responses it cannot imagine are
    exactly the ones it will not construct, and the gate would pass by construction."""


class OffPanelUnavailable(CalibrationError):
    """The off-panel build has no bound construction transport (`CT-CALIB-02`'s
    "off_panel_model_unavailable" mode).

    The gate never invents a construction: the session for the off-panel build is bound
    at wiring time — the same recorded-transport form discovery's bands arrive in
    (`CT-PROV-10`) — and a build with none bound is *unavailable*, which ends at R₀ like
    every other failure mode."""


# --- the module's event clock -----------------------------------------------------------------------
#
# The gates' contract is stated as EVENT ORDER — the threshold's timestamp precedes the first
# result's, authorization follows disclosure — so two events in the same microsecond must not
# compare equal, and a wall clock that steps backwards (NTP, a resumed VM) must not invert them.
# The module keeps a strictly monotonic tick: real wall time while it moves forward, nudged by a
# microsecond when it does not. What the contract asserts is ordering, and this is what makes the
# ordering real rather than a coincidence of the clock.

_LAST_TICK: float = 0.0


def _next_timestamp() -> datetime:
    """The next strictly-monotonic module event timestamp (timezone-aware wall time)."""
    global _LAST_TICK
    tick = time.time()
    if tick <= _LAST_TICK:
        tick = _LAST_TICK + 0.000001
    _LAST_TICK = tick
    return datetime.fromtimestamp(tick, tz=timezone.utc)


# --- the gates' registries and value types (the recorded-transport form, CT-PROV-10) ----------------


def _build_key(provider: str, build_id: str, quantization: str | None) -> str:
    """The served-build identity a gate registry keys on: the exact encoding `M-CONF`'s
    `compute_panel_build_ref` hashes (provider, build id, quantization-or-empty, unit-
    separator). This module does not import `aeh.conf` for it — the gates accept
    duck-typed refs and never touch model endpoints (`TC-PROV-05`) — so the encoding is
    mirrored here and `aeh.conf` stays the canonical owner of the formula."""
    return f"{provider}\x1f{build_id}\x1f{quantization or ''}"


@dataclass(frozen=True)
class OffPanelModelRef:
    """A pinned identity for the off-panel checker (§3.1's ModelRef shape, carried
    locally so the gates accept any provider/build/quantization triple without
    importing `M-CONF`).

    Identity is the **served build** — provider, build id, quantization — not the
    label, which is what makes the shared-build refusal (`CT-CALIB-08`,
    `NFR-CALIB-04`) key on the thing that actually runs."""

    provider: str
    build_id: str
    quantization: str | None = None

    @property
    def build_key(self) -> str:
        return _build_key(self.provider, self.build_id, self.quantization)


@dataclass(frozen=True)
class _ConstructionAttempt:
    """One off-panel construction attempt: the angle probed and what it produced.

    ``response`` is the constructed student response, or None when the angle failed to
    construct one — a failed attempt is a result, not an error (§6.6: the model tries
    several angles; the pass case's note holds that absence of evidence is not evidence
    of preservation)."""

    angle: str
    response: str | None
    divergence_note: str | None = None


@dataclass(frozen=True)
class _BackTranslationSession:
    """The construction session bound to one off-panel build — the recorded-transport
    form (`CT-PROV-10`): the attempts the off-panel model made when asked to construct a
    student response on which R₀ and R₁ would assign different scores.

    Wiring binds the session for the off-panel build the same way discovery's bands are
    injected, so the gate needs no network and no real upstream, and the provider stays
    the only egress point (`CT-PROV-15`)."""

    attempts: tuple[_ConstructionAttempt, ...]

    @property
    def constructed(self) -> _ConstructionAttempt | None:
        """The first attempt that constructed a response, or None."""
        for attempt in self.attempts:
            if attempt.response is not None:
                return attempt
        return None


@dataclass(frozen=True)
class _ClassRoster:
    """One class's dual-scored bands, pre-scored under R₀ and R₁ — the recorded-transport
    form the non-inferiority gate consumes (`CT-PROV-10`).

    ``scores`` is per paper, then per criterion: the ``(r0_band, r1_band)`` pair the panel
    assigned under each rubric. A paper *shifts* when any criterion's band differs — a
    full-band move in either direction, direction-neutral by interpretation (see the
    module docstring): a student whose band moved a level has been regraded in a
    teacher-recognizable sense whether the move was up or down."""

    cohort_id: str
    class_size: int
    criteria: tuple[str, ...]
    scores: tuple[tuple[tuple[int, int], ...], ...]
    is_calibration_set: bool = False

    @property
    def shifted_papers(self) -> int:
        """Papers whose band moved a full level on any criterion."""
        return sum(
            1 for paper in self.scores if any(r0_band != r1_band for r0_band, r1_band in paper)
        )


#: The panel's served builds — what `model_ref_in_panel` registers and `back_translate`
#: checks off-panel membership against.
_PANEL_BUILDS: set[str] = set()

#: Each off-panel build's bound construction session, by build key.
_OFF_PANEL_SESSIONS: dict[str, _BackTranslationSession] = {}

#: Each registered cohort's roster, by cohort id.
_CLASS_ROSTERS: dict[str, _ClassRoster] = {}

#: The standing institutional threshold declaration, and the moment it was fixed. One-shot:
#: the gate run that uses it consumes it (see the module docstring's interpretation).
_INSTITUTIONAL_THRESHOLD: float | None = None
_INSTITUTIONAL_THRESHOLD_DECLARED_AT: datetime | None = None


def declare_institutional_threshold(value: float) -> datetime:
    """Declare the institution's non-inferiority threshold and return when it was fixed
    (`FR-CALIB-08`, `CT-CALIB-13`).

    The declaration is the owned decision the gate consumes: it must exist **before**
    the comparison, which the returned timestamp is the record of. The declaration is
    one-shot — the next gate run that uses it consumes it, so a fresh comparison needs a
    fresh declaration (the strictest honest reading of "declared before the comparison";
    see the module docstring). The value is a fraction of a class, so anything outside
    [0, 1] is refused here, at the declaration."""
    global _INSTITUTIONAL_THRESHOLD, _INSTITUTIONAL_THRESHOLD_DECLARED_AT
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise CalibrationError(
            f"the non-inferiority threshold is a fraction of the class, got {value!r}: "
            "declare a value in [0, 1] — 0.10 is the HLD's example, not a validated one "
            "(CT-CALIB-13)"
        )
    declared_at = _next_timestamp()
    _INSTITUTIONAL_THRESHOLD = value
    _INSTITUTIONAL_THRESHOLD_DECLARED_AT = declared_at
    return declared_at


def _clear_institutional_threshold() -> None:
    """Clear any standing threshold declaration. The declaration is one-shot, so this is
    hygiene for the knob sweep: an observation must read the value it injected, not a
    leftover declaration that outranks the env."""
    global _INSTITUTIONAL_THRESHOLD, _INSTITUTIONAL_THRESHOLD_DECLARED_AT
    _INSTITUTIONAL_THRESHOLD = None
    _INSTITUTIONAL_THRESHOLD_DECLARED_AT = None


@dataclass(frozen=True)
class GateResult:
    """One gate's outcome, with what the gate did next to it (seam 4) — never a bare
    pass/fail.

    ``threshold_used`` is the value the comparison applied and ``threshold_source`` is
    where it came from — "argument" when the caller passed one, "configuration" when it
    came from a standing one-shot declaration, "environment" when it fell back to the
    deployment's env channel. The distinction matters: a declaration is an owned
    decision, a machine default is not, and one reader of the result can tell them
    apart. The timestamps are the
    event-order oracle: ``threshold_declared_at`` is when the threshold was fixed (the
    declaration's moment for a standing declaration; for an argument or an env fallback,
    the call at which the gate fixed it), and it precedes ``first_result_at`` — the first
    comparison's timestamp — on every path, so a threshold chosen to fit the outcome
    shows up as one.

    ``revert_to`` is the revert record (`CT-CALIB-02`): the rubric the run ends on when
    this gate refuses — R₀ — or None when the gate passed. ``advisory_only`` is
    structurally False: no outcome on this surface attaches a note to a revision that
    ships, so the forbidden "warned revision" shape is assertable rather than merely
    avoided."""

    gate: str
    outcome: str
    r0: str
    r1: str
    cohort_id: str | None = None
    threshold_used: float | None = None
    threshold_source: str | None = None
    threshold_declared_at: datetime | None = None
    first_result_at: datetime | None = None
    shifted_papers: int | None = None
    class_size: int | None = None
    shifted_fraction: float | None = None
    divergent_response_found: bool | None = None
    constructed_response: str | None = None
    advisory_only: bool = False
    revert_to: str | None = None
    attempts: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def non_inferiority(
    r0: str,
    r1: str,
    cohort_id: str,
    threshold: float | None,
    *,
    environ: Mapping[str, str] | None = None,
) -> GateResult:
    """The dual-scoring non-inferiority gate (`FR-CALIB-08`, `CT-CALIB-07`/`-13`).

    Compares the full class's dual scores — the R₀ and R₁ bands the registered roster
    carries, the recorded-transport form — and rejects the revision when **more than**
    ``threshold`` of the class shifted by a full band. "More than" is strict: a class
    shifted by exactly the threshold passes, which is the row an implementation using
    ``>=`` gets wrong (`FR-CALIB-08` says "more than").

    The threshold is resolved, never defaulted (`CT-CALIB-13`): an explicit argument
    wins (source "argument"); then a standing institutional declaration — consumed by
    this run (source "configuration"); then the deployment's
    ``HARNESS_CALIB_NONINFERIORITY_THRESHOLD``; with none of the three, the gate refuses
    with `ThresholdNotDeclared`. ``CALIB_NONINFERIORITY_THRESHOLD`` — the design's 0.10 —
    is never applied by the gate: it is the HLD's example, not a validated value.

    The gate refuses the calibration set itself and any roster flagged as it
    (`InsufficientPopulation`, `NFR-CALIB-02`), and refuses a class over the
    deployment's class-size cap rather than silently scoring a subset. Passing is
    **non-inferiority and nothing more** (`CT-CALIB-16`): the gate cannot see whether
    the revision was better, and says nothing about it.
    """
    # The one-shot declaration is consumed here, so the globals are assigned in this scope.
    global _INSTITUTIONAL_THRESHOLD, _INSTITUTIONAL_THRESHOLD_DECLARED_AT

    if cohort_id == CALIBRATION_SET:
        raise InsufficientPopulation(
            f"cohort {CALIBRATION_SET!r} is the calibration set, which lacks the sample "
            "size to mean anything (NFR-CALIB-02): the gate refuses it rather than "
            "returning a number somebody will cite (CT-CALIB-07)"
        )
    roster = _CLASS_ROSTERS.get(cohort_id)
    if roster is None:
        raise CalibrationError(
            f"unknown cohort {cohort_id!r}: the gate scores a registered class — the "
            "recorded-transport form the caller registers (CT-PROV-10)"
        )
    if roster.is_calibration_set:
        raise InsufficientPopulation(
            f"cohort {cohort_id!r} is flagged as the calibration set, which lacks the "
            "sample size to mean anything (NFR-CALIB-02): the gate refuses it"
        )
    cap = _class_size_cap(environ)
    if cap is not None and roster.class_size > cap:
        raise CalibrationError(
            f"cohort {cohort_id!r} carries {roster.class_size} submissions and the "
            f"deployment's {CALIB_CLASS_SIZE_CAP_ENV} is {cap}: the gate scores the FULL "
            "class (NFR-CALIB-02) or refuses, never a subset"
        )

    if threshold is not None:
        threshold_used = float(threshold)
        if not 0.0 <= threshold_used <= 1.0:
            raise CalibrationError(
                f"the threshold is a fraction of the class, got {threshold_used!r}: "
                "pass a value in [0, 1] or None to use the declared one"
            )
        threshold_source = "argument"
        threshold_declared_at = _next_timestamp()
    elif _INSTITUTIONAL_THRESHOLD is not None:
        threshold_used = _INSTITUTIONAL_THRESHOLD
        threshold_source = "configuration"
        threshold_declared_at = _INSTITUTIONAL_THRESHOLD_DECLARED_AT
        _INSTITUTIONAL_THRESHOLD = None  # one-shot: consumed by the run it was declared for
        _INSTITUTIONAL_THRESHOLD_DECLARED_AT = None
    else:
        env_threshold = _noninferiority_threshold_from_env(environ)
        if env_threshold is None:
            raise ThresholdNotDeclared(
                "no threshold was declared for this comparison (CT-CALIB-13): pass one, "
                f"call declare_institutional_threshold first, or set "
                f"{CALIB_NONINFERIORITY_THRESHOLD_ENV}. {CALIB_NONINFERIORITY_THRESHOLD} is "
                "the HLD's example, not a validated value, and the gate does not default it"
            )
        threshold_used = env_threshold
        threshold_source = "environment"
        threshold_declared_at = _next_timestamp()

    shifted = roster.shifted_papers
    shifted_fraction = shifted / roster.class_size
    first_result_at = _next_timestamp()
    outcome = "reject" if shifted_fraction > threshold_used else "pass"
    notes = (
        f"{shifted} of {roster.class_size} submissions shifted a full band "
        f"({shifted_fraction:.2f}) against a threshold of {threshold_used} "
        f"({threshold_source}): "
        + (
            "the revision is rejected and the class is graded against R₀ (FR-CALIB-08)"
            if outcome == "reject"
            else "the shift is within the threshold: non-inferior, and no evidence the "
            "revision improved the rubric (CT-CALIB-16 is a non-promise)"
        ),
    )
    return GateResult(
        gate="non_inferiority",
        outcome=outcome,
        r0=r0,
        r1=r1,
        cohort_id=cohort_id,
        threshold_used=threshold_used,
        threshold_source=threshold_source,
        threshold_declared_at=threshold_declared_at,
        first_result_at=first_result_at,
        shifted_papers=shifted,
        class_size=roster.class_size,
        shifted_fraction=shifted_fraction,
        advisory_only=False,
        revert_to=r0 if outcome == "reject" else None,
        notes=notes,
    )


def back_translate(r0: str, r1: str, off_panel: OffPanelModelRef | None = None) -> GateResult:
    """The adversarial back-translation gate (`FR-CALIB-09`, `CT-CALIB-08`, §6.6).

    A model **not in the scoring panel** is asked to construct a student response on
    which R₀ and R₁ would assign different scores. A successful construction is evidence
    the construct changed, and the outcome is a **rejection** — not an advisory note
    attached to a revision that ships anyway, which would be `CT-CALIB-02`'s warned
    revision renamed. When every attempt fails to construct a divergence the gate passes,
    with the note that absence of evidence is not evidence of preservation: several
    angles were probed and none found the seam, which §6.6 reads as evidence of
    preservation only in the weak sense.

    With no explicit checker the gate reads the deployment's declared one —
    `CALIB_OFF_PANEL_MODEL`, or its env channel `HARNESS_CALIB_OFF_PANEL_MODEL`, at call
    time. Nothing declared is the enumerated unavailable mode: the gate never invents an
    adversary.

    The off-panel build is refused when it shares a served build with the panel
    (`OffPanelConfigurationError`) — at the gate as well as at configuration time,
    because a registry the caller filled by hand deserves the same teeth
    (`NFR-CALIB-04`). A build with no bound construction transport is unavailable
    (`OffPanelUnavailable`), the enumerated failure mode that ends at R₀ like every
    other.
    """
    if not r0 or not r1:
        raise CalibrationError("back_translate needs both rubric versions to ask about")
    if off_panel is None:
        declared = _off_panel_model_declared()
        if declared is None:
            raise OffPanelUnavailable(
                "no off-panel checker is declared: set CALIB_OFF_PANEL_MODEL (or "
                f"{CALIB_OFF_PANEL_MODEL_ENV}) — the gate never invents an adversary "
                "(CT-CALIB-02's off_panel_model_unavailable mode)"
            )
        off_panel = _off_panel_model_ref_from_declared(declared)
    if off_panel.build_key in _PANEL_BUILDS:
        raise OffPanelConfigurationError(
            f"the off-panel model {off_panel.provider}/{off_panel.build_id} is in the "
            "scoring panel: a shared build would let the panel's own blind spots define "
            "the adversarial search, so the gate would pass by construction "
            "(CT-CALIB-08, NFR-CALIB-04)"
        )
    session = _OFF_PANEL_SESSIONS.get(off_panel.build_key)
    if session is None:
        raise OffPanelUnavailable(
            f"no construction transport is bound for the off-panel build "
            f"{off_panel.provider}/{off_panel.build_id}: the gate never invents one "
            "(CT-CALIB-02's off_panel_model_unavailable mode)"
        )
    attempts = tuple(
        f"{attempt.angle}: "
        + ("constructed a divergent response" if attempt.response is not None else "no construction")
        for attempt in session.attempts
    )
    constructed = session.constructed
    if constructed is None:
        return GateResult(
            gate="back_translation",
            outcome="pass",
            r0=r0,
            r1=r1,
            divergent_response_found=False,
            advisory_only=False,
            attempts=attempts,
            notes=(
                "no attempt constructed a response on which R0 and R1 would differ; the "
                "gate passes on the attempts' failure, which is evidence of preservation "
                "only in §6.6's weak sense — absence of evidence is not evidence the "
                "construct did not change",
            ),
        )
    divergence_note = constructed.divergence_note or (
        "the attempt did not name the divergence"
    )
    return GateResult(
        gate="back_translation",
        outcome="reject",
        r0=r0,
        r1=r1,
        divergent_response_found=True,
        constructed_response=constructed.response,
        advisory_only=False,
        revert_to=r0,
        attempts=attempts,
        notes=(
            f"an off-panel model constructed a response on which R0 and R1 would assign "
            f"different scores ({divergence_note}): a successful construction "
            "is evidence the construct changed (FR-CALIB-09), so the revision is rejected "
            "rather than shipping with a note (CT-CALIB-02, CT-CALIB-08)",
        ),
    )


# --- the version pin (FR-CALIB-11, §6.7, CT-CALIB-09) ------------------------------------------------


@dataclass(frozen=True)
class PinnedRevision:
    """The version pin a revision carries once approved (`FR-CALIB-11`, `CT-CALIB-09`):
    the package version, the approver, and the moment of the approval.

    The approver is the field that matters — a revision pinned with a version and a time
    but no approver is a rubric change nobody owns. The durable record rides the
    caller's `M-PKG` publish (this module has no store authority of its own,
    `CT-CALIB-06`); consumers keep R₀-scored and R₁-scored results out of one
    unannotated rollup, and the pin is what they annotate with."""

    package_version: str
    approved_by: str
    approved_at: datetime


def pin_revision(r1: str, *, approved_by: str) -> PinnedRevision:
    """Pin the approved revision as R₁: version, approver, timestamp (`CT-CALIB-09`).

    The approver is required at the boundary — a pin with a version and a time but no
    approver is a rubric change nobody owns. The pin value is returned for the caller to
    record durably through `M-PKG` (see `PinnedRevision`); nothing is written here,
    because this module holds no store authority of its own (`CT-CALIB-06`)."""
    if not r1 or not r1.strip():
        raise CalibrationError("pin_revision needs the revision's package version")
    if not approved_by or not approved_by.strip():
        raise CalibrationError(
            "a pinned revision names its approver: a pin with a version and a timestamp "
            "but no approver is a rubric change nobody owns (FR-CALIB-11, CT-CALIB-09)"
        )
    return PinnedRevision(
        package_version=r1,
        approved_by=approved_by,
        approved_at=_next_timestamp(),
    )


# --- the dual-scoring budget (NFR-CALIB-03, CT-CALIB-12) ---------------------------------------------
#
# Dual scoring costs "one additional full-class scoring pass and shall be budgeted as such".
# A cost discovered afterwards was never budgeted — it was incurred — so the pass is planned,
# disclosed, authorized, and only then run: the ordering is the contract.


@dataclass
class DualScoringPlan:
    """The disclosed cost of one dual-scoring pass (`NFR-CALIB-03`, `CT-CALIB-12`).

    ``disclosed_at`` is set at plan time, ``authorized_at`` only by `authorize`, and
    ``executed_at`` only by `run_dual_scoring` — the observed order is the contract, and
    the plan's event fields are the record of it. ``estimated_calls`` is exactly one
    full-class pass: every submission, under R₁, on every criterion. ``scores`` is what
    the pass bought — one row per submission, one band per criterion, as the provider
    returned them — so what was paid for is inspectable next to what it cost. The gate
    does not read this raw pass: the caller joins it with R₀'s accumulated bands and
    registers the roster the gate consumes."""

    cohort_id: str
    r0: str
    r1: str
    provider: Any
    class_size: int
    criteria_count: int
    estimated_calls: int
    disclosed_at: datetime
    notes: tuple[str, ...] = ()
    authorized_at: datetime | None = None
    executed_at: datetime | None = None
    scores: tuple[tuple[Any, ...], ...] = ()


#: The declared example class a plan falls back to for a cohort the module has no roster
#: for — §6.5's example class, on a single-criterion rubric (the shape the calibration
#: fixture publishes). Disclosed in the plan's notes, never silent: an estimated cost
#: built on an unstated assumption is a budget that lies. Production registers the cohort
#: first and plans against its true shape.
PLAN_DEFAULT_CLASS_SIZE: int = 100
PLAN_DEFAULT_CRITERIA_COUNT: int = 1


def plan_dual_scoring(cohort_id: str, r0: str, r1: str, provider: Any) -> DualScoringPlan:
    """Disclose what one additional full-class dual-scoring pass will cost, **before**
    the operator authorizes it (`NFR-CALIB-03`, `CT-CALIB-12`).

    Plans against the registered roster's shape; for an unregistered cohort, against the
    declared example class, with the assumption in the plan's notes (see the module
    docstring). The plan makes **no** provider calls — the cost is estimated from the
    class's shape, and nothing is spent before `authorize` records the operator's
    approval."""
    roster = _CLASS_ROSTERS.get(cohort_id)
    if roster is None:
        class_size = PLAN_DEFAULT_CLASS_SIZE
        criteria_count = PLAN_DEFAULT_CRITERIA_COUNT
        notes = (
            f"cohort {cohort_id!r} is not registered with the module: planned against the "
            f"declared example class ({PLAN_DEFAULT_CLASS_SIZE} submissions on "
            f"{PLAN_DEFAULT_CRITERIA_COUNT} criterion), so the estimate is a floor — "
            "register the cohort to budget its true shape",
        )
    else:
        class_size = roster.class_size
        criteria_count = len(roster.criteria)
        notes = (
            f"planned against the registered roster for {cohort_id!r}: {class_size} "
            f"submissions on {criteria_count} criteria",
        )
    return DualScoringPlan(
        cohort_id=cohort_id,
        r0=r0,
        r1=r1,
        provider=provider,
        class_size=class_size,
        criteria_count=criteria_count,
        estimated_calls=class_size * criteria_count,
        disclosed_at=_next_timestamp(),
        notes=notes,
    )


def authorize(plan: DualScoringPlan) -> datetime:
    """Record the operator's authorization of the disclosed cost (`CT-CALIB-12`).

    The recorded timestamp is strictly after the disclosure's, so the observed order —
    disclose, then authorize, then run — is what distinguishes a budgeted cost from a
    reported one."""
    if plan.authorized_at is not None:
        raise CalibrationError(
            "this plan is already authorized: a budgeted cost is authorized once"
        )
    plan.authorized_at = _next_timestamp()
    return plan.authorized_at


def run_dual_scoring(plan: DualScoringPlan) -> DualScoringPlan:
    """Run the authorized pass: exactly the disclosed number of calls, through the
    injected provider (`NFR-CALIB-03`; seam 2 — the provider is the only egress point).

    One call per (submission, criterion) pair across the full class — the pass whose
    cost was disclosed and authorized — and the provider's bands land on the plan's
    ``scores`` (seam 4: what was paid for sits next to what it cost). An unauthorized
    plan is refused (a cost nobody approved was never budgeted), a re-run is refused
    (a budgeted cost is incurred once, and a second pass would double the invoice the
    operator approved), and an over-cap class is refused (the deployment's cap names
    itself)."""
    if plan.authorized_at is None:
        raise CalibrationError(
            "the pass was never authorized: run_dual_scoring runs only after authorize "
            "records the operator's approval (NFR-CALIB-03, CT-CALIB-12)"
        )
    if plan.executed_at is not None:
        raise CalibrationError(
            "this plan has already run: a budgeted cost is incurred once, and a second "
            "pass would double the invoice the operator approved"
        )
    cap = _class_size_cap()
    if cap is not None and plan.class_size > cap:
        raise CalibrationError(
            f"the plan covers {plan.class_size} submissions and the deployment's "
            f"{CALIB_CLASS_SIZE_CAP_ENV} is {cap}: the pass covers the full class or "
            "refuses, never a subset"
        )
    plan.scores = tuple(
        tuple(plan.provider.score(paper, criterion) for criterion in range(plan.criteria_count))
        for paper in range(plan.class_size)
    )
    plan.executed_at = _next_timestamp()
    return plan


# --- the knobs, and their externally visible effects (CT-CALIB-13, seam 3) --------------------------
#
# `KNOBS` is the module's full knob surface: the three the design declares plus the class-size
# cap, which is env-only. The declared *values* live on the constants above; the gate's refusal
# to default the threshold is what makes 0.10 an example rather than a default.

KNOBS: dict[str, Any] = {
    "CALIB_MAX_QUESTIONS": CALIB_MAX_QUESTIONS,
    "CALIB_NONINFERIORITY_THRESHOLD": CALIB_NONINFERIORITY_THRESHOLD,
    "CALIB_OFF_PANEL_MODEL": CALIB_OFF_PANEL_MODEL,
    "CALIB_CLASS_SIZE_CAP": CALIB_CLASS_SIZE_CAP,
}


def contrasting_values_for(knob: str) -> tuple[Any, Any]:
    """Two values a run can tell apart for ``knob`` (`CT-CALIB-13`'s sweep moves the
    behaviour between them). Chosen per knob for where they land on the behaviour, not
    for contrast's own sake."""
    if knob == "CALIB_MAX_QUESTIONS":
        return (1, 3)
    if knob == "CALIB_NONINFERIORITY_THRESHOLD":
        # A fixed probe cohort shifts 0.20 of the class, between the two values: the
        # applied threshold — not the roster — decides the outcome.
        return (0.05, 0.50)
    if knob == "CALIB_OFF_PANEL_MODEL":
        return (_off_panel_model_ref(constructs=True), _off_panel_model_ref(constructs=False))
    if knob == "CALIB_CLASS_SIZE_CAP":
        return (None, 5)
    raise CalibrationError(
        f"unknown knob {knob!r}; the knobs the module reads are {sorted(KNOBS)}"
    )


#: Cached probe cohorts the knob observations run against, keyed by (fraction, class size).
_PROBE_COHORTS: dict[tuple[float, int], str] = {}


def _probe_cohort_id(fraction: float, class_size: int) -> str:
    key = (float(fraction), class_size)
    if key not in _PROBE_COHORTS:
        _PROBE_COHORTS[key] = cohort_with_band_shift(fraction=fraction, class_size=class_size)
    return _PROBE_COHORTS[key]


def observable_behaviour_with(knob: str, value: Any) -> Any:
    """What a caller outside the module can observe when ``knob`` is set to ``value``
    (`CT-CALIB-13`).

    The knob is **moved and the difference observed**, not reported on: the question
    count elicitation asks, the gate's outcome and applied threshold, the
    back-translation verdict, the gate's refusal of an over-cap class. Values are
    injected through the call-time ``environ`` seam, or for the off-panel knob through
    the checker argument itself (a model reference does not ride an env string) — never
    ``os.environ``, so an
    observation cannot leak into a neighbouring test; the threshold observation clears
    any standing declaration first, because a declaration outranks the env and a
    leftover would make the injected value unread."""
    if knob == "CALIB_MAX_QUESTIONS":
        questions = elicit(
            findings_fixture(count=20), environ={CALIB_MAX_QUESTIONS_ENV: str(value)}
        )
        return ("questions_asked", len(questions))
    if knob == "CALIB_NONINFERIORITY_THRESHOLD":
        _clear_institutional_threshold()
        result = non_inferiority(
            r0="pkg-v1",
            r1="pkg-v2",
            cohort_id=_probe_cohort_id(0.20, 100),
            threshold=None,
            environ={CALIB_NONINFERIORITY_THRESHOLD_ENV: str(value)},
        )
        return (result.outcome, result.threshold_used)
    if knob == "CALIB_OFF_PANEL_MODEL":
        result = back_translate(r0="pkg-v1", r1="pkg-v2", off_panel=value)
        return (result.outcome, result.divergent_response_found)
    if knob == "CALIB_CLASS_SIZE_CAP":
        environ = {} if value is None else {CALIB_CLASS_SIZE_CAP_ENV: str(value)}
        try:
            result = non_inferiority(
                r0="pkg-v1",
                r1="pkg-v2",
                cohort_id=_probe_cohort_id(0.05, 10),
                threshold=0.10,
                environ=environ,
            )
        except CalibrationError:
            return ("refused",)
        return ("ran", result.outcome)
    raise CalibrationError(
        f"unknown knob {knob!r}; the knobs the module reads are {sorted(KNOBS)}"
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


def findings_fixture(
    *,
    count: int | None = None,
    affected_counts: Sequence[int] | None = None,
) -> tuple[Finding, ...]:
    """Hand-built findings with known affected counts — the fixture the ranking and cap
    assertions need (`CT-CALIB-05`): discovery-order output also looks plausible, so the
    counts are supplied, distinct, and deliberately out of order.

    Criterion ids are zero-padded (`CRIT-001`, ...) so they never collide with the ids a
    real test package carries (`CRIT-1`) — an elicitation session from one fixture must
    not be mistaken for a criterion of the other."""
    if affected_counts is not None:
        counts = [int(value) for value in affected_counts]
    else:
        total = count if count is not None else 3
        counts = [((index * 7) % 23) + 1 for index in range(total)]
    return tuple(
        Finding(
            criterion_id=f"CRIT-{index + 1:03d}",
            category=EDIT_ELIGIBLE_CATEGORY,
            submissions_affected=submissions,
            examples=(
                f"student response A for criterion {f'CRIT-{index + 1:03d}'}",
                f"student response B for criterion {f'CRIT-{index + 1:03d}'}",
            ),
        )
        for index, submissions in enumerate(counts)
    )


def tier_p_path_for_test() -> Path:
    """The Tier P file a test store will use: `<tmp>/packages/pkg-calib-test.pkg.sqlite`.

    The shape is the store's own layout (`data_dir/packages/<package_id>.pkg.sqlite`),
    so `open_store` on the returned path's grandparent opens exactly this file — which
    is what lets the write audit name the file and observe every `sqlite3.connect` on
    it (`CT-CALIB-06`)."""
    data_dir = Path(tempfile.mkdtemp(prefix="aeh-calib-tierp-"))
    return data_dir / "packages" / f"{_FIXTURE_PACKAGE_ID}.pkg.sqlite"


def _build_published_package(data_dir: Path, package_id: str) -> str:
    """Build a real Tier P package: one published version, one criterion, two bands.

    The build happens OUTSIDE any audit window and the store is closed before the
    caller proceeds: a warm handle emits no `sqlite3.connect` events, so the write
    audit can only observe the edit if the edit's reader reopens the file fresh."""
    # The full migration chain must be imported before the first open (CLAUDE.md):
    import aeh.agg  # noqa: F401
    import aeh.det  # noqa: F401
    import aeh.extract  # noqa: F401
    import aeh.grade  # noqa: F401
    import aeh.ingest  # noqa: F401
    import aeh.integ  # noqa: F401
    import aeh.judge  # noqa: F401
    import aeh.orch  # noqa: F401
    import aeh.review  # noqa: F401
    import aeh.synth  # noqa: F401

    from aeh.store import open_store

    store = open_store(data_dir)
    try:
        handle = store.package(package_id)
        with handle.transaction() as tx:
            tx.execute(
                "INSERT INTO package (package_id, created_at) "
                "VALUES (:package_id, :created_at)",
                package_id=package_id, created_at="2026-01-01T00:00:00",
            )
        catalog = PackageCatalog(handle, package_id=package_id)
        version = catalog.create_version(None)
        catalog.add_criterion(version, _FIXTURE_CRITERION_ID, max_points=4.0, band_count=2)
        catalog.add_band(version, _FIXTURE_CRITERION_ID, 0, "needs work", 0.0,
                         descriptor="the response does not yet meet the criterion")
        catalog.add_band(version, _FIXTURE_CRITERION_ID, 1, "meets it", 4.0,
                         descriptor="the response meets the criterion")
        catalog.publish(version, approved_by="teacher")
        return version
    finally:
        store.close()


class _AuditedStoreWrite:
    """The claim the write-audit oracle checks against: every `sqlite3.connect` on the
    fixture's Tier P file is `M-STORE`'s (the layer that owns the connection), initiated
    by `M-CALIB` (the module whose `apply_answers` started the chain).

    A plain class with a duck-typed `__eq__` — it matches the audit's `WriteAttempt`
    records field-wise without importing the test-support module, and the comparison
    works because `WriteAttempt.__eq__` declines non-`WriteAttempt` operands so Python
    tries the reflected operation. The claim carries `attributed_to="M-STORE"`, so a
    write `M-CALIB` performed directly (attributed `M-CALIB`) fails the match — that is
    the oracle's teeth."""

    def __init__(self, *, api: str, target: Any, attributed_to: str,
                 initiated_by: str) -> None:
        self.api = api
        self.target = target
        self.attributed_to = attributed_to
        self.initiated_by = initiated_by

    def __eq__(self, other: object) -> bool:
        if not hasattr(other, "api"):
            return NotImplemented
        return (
            other.api == self.api
            and str(other.target) == str(self.target)
            and other.attributed_to == self.attributed_to
            and other.initiated_by == self.initiated_by
        )


class _FixtureCatalog:
    """A `PackageCatalog` facade over a real Tier P store that reopens lazily.

    The store is built (`_build_published_package`) and closed BEFORE the facade is
    handed to a test; the first call forwarded reopens it. Two readings of why:

    * the audit reading — `CT-CALIB-06`'s oracle is the write-audit log, and a warm
      handle emits no `sqlite3.connect` events; the lazy reopen is what puts a connect
      on the audit log inside the window, and `.audited_writes` is the claim every
      Tier P event on the file must match;
    * the honesty reading — the facade forwards, records which mutating catalog methods
      were called (`.writes`), and implements nothing: no lock check, no second write
      path, nothing a real catalog call could diverge from."""

    def __init__(self, data_dir: Path, package_id: str, tier_p_path: Path) -> None:
        self._data_dir = data_dir
        self._package_id = package_id
        self._tier_p_path = tier_p_path
        self._inner: PackageCatalog | None = None
        self._store: Any = None
        #: Names of the mutating catalog methods forwarded through this facade, in
        #: call order — `catalog.writes` asserts the edit reached the catalog at all.
        self.writes: list[str] = []

    def _catalog(self) -> PackageCatalog:
        if self._inner is None:
            from aeh.store import open_store

            store = open_store(self._data_dir)
            handle = store.package(self._package_id)
            self._inner = PackageCatalog(handle, package_id=self._package_id)
            self._store = store
        return self._inner

    @property
    def audited_writes(self) -> tuple[_AuditedStoreWrite, ...]:
        """The writes this facade claims on the Tier P file: the store reopens fresh
        (its `sqlite3.connect` events land on the audit log), and it writes only
        through the catalog. Anything else touching the file inside an audit window is
        a direct write (`CT-CALIB-06`'s forbidden path)."""
        return (
            _AuditedStoreWrite(
                api="sqlite3.connect",
                target=self._tier_p_path,
                attributed_to="M-STORE",
                initiated_by="M-CALIB",
            ),
        )

    def latest_version(self) -> str | None:
        return self._catalog().latest_version()

    def criteria(self, version: str) -> tuple:
        return self._catalog().criteria(version)

    def bands(self, criterion_id: str) -> tuple:
        """A read, not a write: never recorded on `.writes` — the record is of what
        the edit path WROTE, and composing against the current descriptor only reads
        it (the catalog's own `bands`, the current-version read it contracts)."""
        return self._catalog().bands(criterion_id)

    def create_version(self, parent: str | None) -> str:
        self.writes.append("create_version")
        return self._catalog().create_version(parent)

    def update_band_field(self, version: str, criterion_id: str, ordinal: int,
                          field: str, value: Any) -> None:
        self.writes.append("update_band_field")
        return self._catalog().update_band_field(
            version, criterion_id, ordinal, field, value,
        )

    def update_criterion_field(self, version: str, criterion_id: str, field: str,
                               value: Any) -> None:
        self.writes.append("update_criterion_field")
        return self._catalog().update_criterion_field(version, criterion_id, field, value)

    def add_criterion(self, version: str, criterion_id: str) -> None:
        self.writes.append("add_criterion")
        return self._catalog().add_criterion(version, criterion_id)

    def update_criterion_dependency(self, version: str) -> None:
        self.writes.append("update_criterion_dependency")
        return self._catalog().update_criterion_dependency(version)

    def append_elicitation(self, version: str, question: str,
                           options_offered: Sequence[str], answer_given: str,
                           resulting_edit: str = "") -> str:
        self.writes.append("append_elicitation")
        return self._catalog().append_elicitation(
            version, question, options_offered, answer_given,
            resulting_edit=resulting_edit,
        )


def catalog_for_test(tier_p_path: Path | None = None) -> _FixtureCatalog:
    """A `_FixtureCatalog` over a real published package, its store closed and its
    file ready to reopen on first use (see `_FixtureCatalog` for why)."""
    if tier_p_path is None:
        tier_p_path = tier_p_path_for_test()
    package_id = tier_p_path.name.removesuffix(".pkg.sqlite")
    _build_published_package(tier_p_path.parent.parent, package_id)
    return _FixtureCatalog(tier_p_path.parent.parent, package_id, tier_p_path)


@dataclass(frozen=True)
class _ElicitationHistoryRow:
    """One read-back row: the question asked, the options offered, the answer, the
    edit it produced — the reconstruction `CT-CALIB-11` asserts the history alone can
    answer."""

    question: str
    options: tuple[str, ...]
    answer: str
    edit: str


#: The one UPDATE per history field, each a declared literal with keyword parameters
#: (`FR-STORE-08`): the table is append-only, so every one is a refusal in waiting —
#: the statement exists only so the ATTEMPT is real, and the trigger pair migration 005
#: installs is what aborts it.
_HISTORY_UPDATE_STATEMENTS: dict[str, str] = {
    "question": "UPDATE elicitation_history SET question = :value "
                "WHERE elicitation_id = :row_id",
    "options": "UPDATE elicitation_history SET options_offered = :value "
               "WHERE elicitation_id = :row_id",
    "answer": "UPDATE elicitation_history SET answer_given = :value "
              "WHERE elicitation_id = :row_id",
    "edit": "UPDATE elicitation_history SET resulting_edit = :value "
            "WHERE elicitation_id = :row_id",
}


class _ElicitationHistoryFixture:
    """A real Tier P store's elicitation history, wrapped for the append-only sweep.

    The append routes through `PackageCatalog.append_elicitation` — the one write door
    the table has (`FR-PKG-20`). The attempted update and delete are deliberately RAW
    SQL, because the case's point is that the refusal lives in the data layer
    (`NFR-PKG-01`): migration 005's unconditional trigger pair aborts them for every
    writer, catalog or not, and the store's `IntegrityError` is surfaced here as
    `AppendOnlyViolation`."""

    class AppendOnlyViolation(Exception):
        """An UPDATE or DELETE reached the store and the store aborted it."""

    def __init__(self) -> None:
        # The full migration chain must be imported before the first open (CLAUDE.md):
        import aeh.agg  # noqa: F401
        import aeh.det  # noqa: F401
        import aeh.extract  # noqa: F401
        import aeh.grade  # noqa: F401
        import aeh.ingest  # noqa: F401
        import aeh.integ  # noqa: F401
        import aeh.judge  # noqa: F401
        import aeh.orch  # noqa: F401
        import aeh.review  # noqa: F401
        import aeh.synth  # noqa: F401

        from aeh.store import open_store

        self._data_dir = Path(tempfile.mkdtemp(prefix="aeh-calib-hist-"))
        self._package_id = "pkg-calib-hist"
        self._store = open_store(self._data_dir)
        handle = self._store.package(self._package_id)
        with handle.transaction() as tx:
            tx.execute(
                "INSERT INTO package (package_id, created_at) "
                "VALUES (:package_id, :created_at)",
                package_id=self._package_id, created_at="2026-01-01T00:00:00",
            )
        catalog = PackageCatalog(handle, package_id=self._package_id)
        self._version = catalog.create_version(None)
        self._handle = handle
        self._catalog = catalog

    def append(self, *, question: str, options: Sequence[str], answer: str,
               edit: str = "") -> str:
        """Append one row through the catalog's door; returns its row id."""
        return self._catalog.append_elicitation(
            self._version, question, options, answer, resulting_edit=edit,
        )

    def update(self, row_id: str, **changes: Any) -> None:
        """Attempt a row update — the store's trigger pair must abort it."""
        if not changes:
            raise ValueError("update needs at least one field to attempt.")
        for name, value in changes.items():
            if name not in _HISTORY_UPDATE_STATEMENTS:
                raise ValueError(
                    f"unknown elicitation-history field {name!r}; the fields the table "
                    f"carries are {sorted(_HISTORY_UPDATE_STATEMENTS)}."
                )
            if name == "options":
                value = json.dumps(list(value))
            try:
                with self._handle.transaction() as tx:
                    tx.execute(_HISTORY_UPDATE_STATEMENTS[name], row_id=row_id, value=value)
            except sqlite3.IntegrityError as error:
                raise self.AppendOnlyViolation(
                    f"the store refused the update: {error} (FR-PKG-20)"
                ) from error

    def delete(self, row_id: str) -> None:
        """Attempt a row delete — the store's trigger pair must abort it."""
        try:
            with self._handle.transaction() as tx:
                tx.execute(
                    "DELETE FROM elicitation_history WHERE elicitation_id = :row_id",
                    row_id=row_id,
                )
        except sqlite3.IntegrityError as error:
            raise self.AppendOnlyViolation(
                f"the store refused the delete: {error} (FR-PKG-20)"
            ) from error

    def all(self) -> tuple[_ElicitationHistoryRow, ...]:
        """Every row, in append order, reconstructed from the history alone."""
        rows = self._handle.query(
            "SELECT question, options_offered, answer_given, resulting_edit "
            "FROM elicitation_history ORDER BY rowid"
        )
        return tuple(
            _ElicitationHistoryRow(
                question=row["question"],
                options=tuple(json.loads(row["options_offered"])),
                answer=row["answer_given"],
                edit=row["resulting_edit"],
            )
            for row in rows
        )


def elicitation_history_for_test() -> _ElicitationHistoryFixture:
    """A real Tier P store holding an `elicitation_history` table, for the append-only
    sweep (`CT-CALIB-11`): the refusal is the store's, at rung 2, not a double's."""
    return _ElicitationHistoryFixture()


# --- the guardrail gates' test seams (contract suite, §6.11.17) -------------------------------------
#
# The same pattern the #137/#138 seams above established: part of the module's surface,
# exported in `__all__`, so the contract cases drive exactly the surface a real caller would
# and no test-side double stands in for the module. The rosters and construction sessions are
# the recorded-transport form (`CT-PROV-10`) — production binds them at wiring time; these
# seams bind them in-process.


#: Monotonic counter minting unique registered cohort ids.
_COHORT_COUNTER = 0


def cohort_with_band_shift(*, fraction: float, class_size: int = 100) -> str:
    """Register a class roster in which ``fraction`` of the papers moved a full band
    under R₁, and return its cohort id — the recorded-transport form the
    non-inferiority gate consumes (`CT-PROV-10`).

    Single criterion, two bands: a shifted paper moves from band 1 under R₀ to band 0
    under R₁ (the conservative direction), every other paper keeps its band. The shift
    count is rounded half-up — the reading a class expresses — so a 100-student class
    carries every fraction a realistic sweep needs exactly (the boundary cases,
    0.10 against a 0.10 threshold, round to exactly ten papers)."""
    global _COHORT_COUNTER
    fraction = float(fraction)
    if not 0.0 <= fraction <= 1.0:
        raise CalibrationError(
            f"the shifted fraction is a fraction of the class, got {fraction!r}"
        )
    if isinstance(class_size, bool) or not isinstance(class_size, int) or class_size < 1:
        raise CalibrationError(f"class_size must be a positive integer, got {class_size!r}")
    shifted_count = int(class_size * fraction + 0.5)  # round-half-up, the class's reading
    scores = tuple(
        ((1, 0) if index < shifted_count else (1, 1),) for index in range(class_size)
    )
    _COHORT_COUNTER += 1
    cohort_id = f"cohort-band-shift-{_COHORT_COUNTER:04d}"
    _CLASS_ROSTERS[cohort_id] = _ClassRoster(
        cohort_id=cohort_id,
        class_size=class_size,
        criteria=(_FIXTURE_CRITERION_ID,),
        scores=scores,
        is_calibration_set=False,
    )
    return cohort_id


#: Counter minting unique off-panel build ids, so two registered refs never share a key.
_OFF_PANEL_COUNTER = 0


def _off_panel_model_ref(*, constructs: bool | None = True) -> OffPanelModelRef:
    """Register an off-panel build and return its ref.

    ``constructs=True`` binds a session whose attempts construct a divergent response
    (the CT-CALIB-08 construction); ``False`` binds one that probes several angles and
    constructs nothing (the pass case whose note holds §6.6's honest reading); ``None``
    binds nothing — the unavailable transport (`OffPanelUnavailable`'s path)."""
    global _OFF_PANEL_COUNTER
    _OFF_PANEL_COUNTER += 1
    ref = OffPanelModelRef(
        provider="fixture",
        build_id=f"off-panel-constructor-{_OFF_PANEL_COUNTER:03d}@sha256:"
        + ("beef" if constructs else "cafe"),
    )
    if constructs is not None:
        if constructs:
            session = _BackTranslationSession(
                attempts=(
                    _ConstructionAttempt(
                        angle="probing the top band's boundary", response=None
                    ),
                    _ConstructionAttempt(
                        angle="probing the bottom band's boundary", response=None
                    ),
                    _ConstructionAttempt(
                        angle="a response the clarified descriptor reads differently",
                        response=(
                            "The student restates the criterion accurately but stops "
                            "short of the worked example the clarified descriptor asks "
                            "for: R0 bands the response 1 ('meets it') and R1 — which "
                            "now requires the example — bands it 0 ('needs work'). One "
                            "response, two different scores: the divergence a changed "
                            "construct predicts."
                        ),
                        divergence_note="R0 bands 1, R1 bands 0 under the clarified descriptor",
                    ),
                )
            )
        else:
            session = _BackTranslationSession(
                attempts=(
                    _ConstructionAttempt(
                        angle="probing the top band's boundary", response=None
                    ),
                    _ConstructionAttempt(
                        angle="probing the bottom band's boundary", response=None
                    ),
                    _ConstructionAttempt(
                        angle="probing a mid-band response the clarifications touch",
                        response=None,
                    ),
                )
            )
        _OFF_PANEL_SESSIONS[ref.build_key] = session
    return ref


def model_ref_off_panel() -> OffPanelModelRef:
    """An off-panel build with a bound construction session whose attempts construct a
    response on which R₀ and R₁ would differ — the construction `CT-CALIB-08` treats as
    evidence the construct changed."""
    return _off_panel_model_ref(constructs=True)


def model_ref_in_panel() -> OffPanelModelRef:
    """A model ref registered as **in the scoring panel** (`CT-CALIB-08`): handing it to
    `back_translate` as the off-panel checker is the shared-build configuration
    `NFR-CALIB-04` refuses."""
    global _OFF_PANEL_COUNTER
    _OFF_PANEL_COUNTER += 1
    ref = OffPanelModelRef(
        provider="fixture",
        build_id=f"panel-shared-build-{_OFF_PANEL_COUNTER:03d}@sha256:aaaa",
    )
    _PANEL_BUILDS.add(ref.build_key)
    return ref


@dataclass(frozen=True)
class WorseButLowShiftRevision:
    """The `CT-CALIB-16` fixture: a revision that is genuinely worse yet shifts few
    students.

    ``is_genuinely_worse`` is the fixture's **declaration**, not a measurement — the gate
    cannot see worse-ness, and that is the non-promise: a pass means only that the class
    did not shift beyond the threshold and that an off-panel model constructed no
    divergence. Asserting the pass is what keeps the gate from being read as a quality
    check (§7.3's residual risk)."""

    r0: str
    r1: str
    cohort_id: str
    shifted_fraction: float
    is_genuinely_worse: bool
    note: str


def worse_but_low_shift_revision() -> WorseButLowShiftRevision:
    """A genuinely worse revision that shifts under the threshold, registered against a
    real roster (`CT-CALIB-16`).

    The revision narrows the top band's descriptor — a documented loss the fixture
    declares — while the roster it is registered against moves under a tenth of the
    class. The gate passes it: rejecting it would be the superiority claim the design
    explicitly does not make."""
    fraction = 0.03
    cohort_id = cohort_with_band_shift(fraction=fraction, class_size=100)
    return WorseButLowShiftRevision(
        r0="pkg-v1",
        r1="pkg-v2",
        cohort_id=cohort_id,
        shifted_fraction=fraction,
        is_genuinely_worse=True,
        note=(
            "the revision narrows the top band's descriptor, a documented loss the gate "
            "cannot see; the class shift stays under the declared threshold, which is "
            "the only thing a pass means (CT-CALIB-16)"
        ),
    )


class _CountingProvider:
    """The injected provider `CT-CALIB-12` counts calls on: the seam production binds to
    the panel's scoring worker and a test binds to a counter.

    ``score(paper, criterion)`` is the dual-scoring call shape — one call per
    (submission, criterion) pair — and ``calls`` is the observed count the contract
    asserts against, not a figure the provider authors."""

    def __init__(self) -> None:
        self.calls = 0

    def score(self, paper: int, criterion: int) -> str:
        self.calls += 1
        return f"band-{(paper + criterion) % 2}"


def counting_provider_for_test() -> _CountingProvider:
    """The injected provider `CT-CALIB-12`'s call-count assertion drives: every call is
    counted, so the disclosed estimate and the incurred cost are compared against what
    actually happened."""
    return _CountingProvider()


@dataclass(frozen=True)
class CalibrationMetric:
    """One metric the module emits (seam 4, `CT-CALIB-14`): its name, its label
    dimensions, and whether it is a distribution.

    Dimensionality is the point: findings carry a ``triage_category`` label because the
    three categories mean different remedies; the class shift is a distribution because
    a mean hides whether two students moved a band or forty moved a little."""

    name: str
    labels: tuple[str, ...] = ()
    is_distribution: bool = False
    description: str = ""


def metrics_for_test() -> dict[str, CalibrationMetric]:
    """The metric surface the module's structured records feed (`CT-CALIB-14`).

    The families, names and dimensionality are what the harness scrapes from the
    module's structured records — `DiscoveryReport` (findings by triage category),
    `CalibrationRunOutcome` (questions asked versus answered — the gap is the signal),
    `GateResult` (per-gate outcomes, and the class shift as a distribution). The seam
    pins the surface the contract asserts; the samples flow through the records
    themselves."""
    return {
        "findings": CalibrationMetric(
            "calib_findings_total",
            labels=("triage_category",),
            description="discovered ambiguities, by triage category — a single total "
            "cannot say which kind, and the three kinds need different responses "
            "(CT-CALIB-14)",
        ),
        "questions_asked": CalibrationMetric(
            "calib_questions_asked_total",
            description="elicitation questions asked (CT-CALIB-14: asked versus answered)",
        ),
        "questions_answered": CalibrationMetric(
            "calib_questions_answered_total",
            description="elicitation questions the teacher answered; the gap is the signal",
        ),
        "gate_outcome": CalibrationMetric(
            "calib_gate_outcome_total",
            labels=("gate", "outcome"),
            description="outcomes of the two guardrail gates, per gate (CT-CALIB-14)",
        ),
        "class_shift": CalibrationMetric(
            "calib_class_shift_fractions",
            is_distribution=True,
            description="the full class's shift fractions under dual scoring, as a "
            "distribution — a mean hides whether two students moved a band or forty "
            "moved a little (CT-CALIB-14)",
        ),
    }


@dataclass(frozen=True)
class CalibrationAlert:
    """One alert the module raises (seam 4): its scope, its wording, and the finding
    count that fired it."""

    scope: str
    message: str
    finding_count: int


def alerts_for_test(*, finding_count: int = 0) -> tuple[CalibrationAlert, ...]:
    """The alert surface for a discovery that surfaced ``finding_count`` ambiguities
    (`CT-CALIB-14`).

    More than a handful — the same call-time threshold discovery itself alerts under
    (`_ambiguity_alert_after`) — alerts **once, on the aggregate**: the rubric needs a
    conversation, not twenty questions to answer. The per-finding form buries the signal
    in the workload it describes, which is the shape the clause forbids."""
    if finding_count <= _ambiguity_alert_after():
        return ()
    return (
        CalibrationAlert(
            scope="aggregate",
            message=AMBIGUITY_ALERT_TEXT,
            finding_count=finding_count,
        ),
    )


def simulate_failure(failure_mode: str, *, r0: str = _DEFAULT_R0_VERSION) -> CalibrationRunOutcome:
    """Drive one of `CT-CALIB-02`'s eight failure modes through the module's real paths
    and return the terminal outcome every one of them resolves to (`FR-CALIB-10`).

    The modes and the real path each drives: ``teacher_declines`` — the run's
    no-inputs branch (questions were elicited, the teacher answered nothing);
    ``teacher_abandons_midflow`` — answers arrived with no catalog to apply them
    through; ``gate_fails`` — the gate refuses a population that cannot carry its
    verdict (the calibration set); ``dual_scoring_rejects`` — the comparison rejects
    the revision (a class shifting well past any threshold); ``back_translation_diverges``
    — the off-panel model constructs a divergent response;
    ``triage_unavailable`` — an uncategorized disagreement reaches the triage boundary;
    ``off_panel_model_unavailable`` — the off-panel build has no bound transport;
    ``module_crashes`` — the gate is handed a corrupted roster and the module raises.

    The seam exists because the terminal state is a property of how callers resolve
    these failures, and the contract pins it (`FR-CALIB-10`): R₀ unchanged, the
    ambiguous criteria lower-confidence, no revision shipped, nothing shipped with a
    warning. Errors are caught on purpose — a crash is one of the enumerated modes, and
    the claim under test is that it too ends at R₀."""
    lower_confidence = tuple(f.criterion_id for f in findings_fixture(count=1))

    def _terminal(note: str, *details: str) -> CalibrationRunOutcome:
        return CalibrationRunOutcome(
            r0_version=r0,
            active_rubric=r0,
            fairness_note=note,
            skipped=True,
            revised_version=None,
            lower_confidence_criteria=lower_confidence,
            revision_shipped=False,
            notes=details,
        )

    if failure_mode == "teacher_declines":
        return run_for_assignment(
            assignment(
                r0_version=r0,
                ambiguous_criteria=lower_confidence,
            ),
            findings=findings_fixture(),
            answers=None,
        )
    if failure_mode == "teacher_abandons_midflow":
        return run_for_assignment(
            assignment(
                r0_version=r0,
                ambiguous_criteria=lower_confidence,
            ),
            findings=findings_fixture(),
            answers={"q1": "broaden"},
            catalog=None,
        )
    if failure_mode == "gate_fails":
        try:
            non_inferiority(
                r0=r0, r1="pkg-v2", cohort_id=CALIBRATION_SET, threshold=0.10
            )
        except InsufficientPopulation as error:
            return _terminal(
                _refusal_note(failure_mode, r0, "the gate refused the calibration set"),
                str(error),
            )
        raise CalibrationError(f"the gate_fails path did not refuse: {failure_mode}")
    if failure_mode == "dual_scoring_rejects":
        cohort_id = cohort_with_band_shift(fraction=0.40, class_size=100)
        result = non_inferiority(r0=r0, r1="pkg-v2", cohort_id=cohort_id, threshold=0.10)
        if result.outcome != "reject":
            raise CalibrationError(
                f"the dual_scoring_rejects path did not reject: {result.outcome!r}"
            )
        return _terminal(
            _refusal_note(failure_mode, r0, "dual scoring shifted more of the class than "
                                          "the declared threshold allows"),
            *result.notes,
        )
    if failure_mode == "back_translation_diverges":
        result = back_translate(r0=r0, r1="pkg-v2", off_panel=model_ref_off_panel())
        if result.outcome != "reject":
            raise CalibrationError(
                f"the back_translation_diverges path did not reject: {result.outcome!r}"
            )
        return _terminal(
            _refusal_note(failure_mode, r0,
                          "an off-panel model constructed a response on which R0 and R1 "
                          "differ — evidence the construct changed (FR-CALIB-09)"),
            *result.notes,
        )
    if failure_mode == "triage_unavailable":
        try:
            triage(Disagreement(criterion_id=_FIXTURE_CRITERION_ID))
        except TriageCategoryRequired as error:
            return _terminal(
                _refusal_note(failure_mode, r0,
                              "a disagreement without its required triage category cannot "
                              "reach the editable path"),
                str(error),
            )
        raise CalibrationError(f"the triage_unavailable path did not refuse: {failure_mode}")
    if failure_mode == "off_panel_model_unavailable":
        try:
            back_translate(r0=r0, r1="pkg-v2", off_panel=_off_panel_model_ref(constructs=None))
        except OffPanelUnavailable as error:
            return _terminal(
                _refusal_note(failure_mode, r0,
                              "the off-panel build has no bound construction transport, so "
                              "the gate cannot run and the revision does not ship"),
                str(error),
            )
        raise CalibrationError(f"the off_panel_model_unavailable path did not refuse: {failure_mode}")
    if failure_mode == "module_crashes":
        cohort_id = cohort_with_band_shift(fraction=0.05, class_size=10)
        _CLASS_ROSTERS[cohort_id] = _ClassRoster(
            cohort_id=cohort_id,
            class_size=10,
            criteria=(_FIXTURE_CRITERION_ID,),
            scores=((("corrupted",),),),
            is_calibration_set=False,
        )
        try:
            non_inferiority(r0=r0, r1="pkg-v2", cohort_id=cohort_id, threshold=0.10)
        except Exception as error:  # noqa: BLE001 — the mode IS the crash; it ends at R0 too
            return _terminal(
                _refusal_note(failure_mode, r0,
                              "the module raised on a corrupted roster, and a crash ends "
                              "at R0 like every other failure mode"),
                f"{type(error).__name__}: {error}",
            )
        raise CalibrationError(f"the module_crashes path did not crash: {failure_mode}")
    raise CalibrationError(
        f"unknown failure mode {failure_mode!r}: CT-CALIB-02 enumerates eight"
    )


def _refusal_note(failure_mode: str, r0: str, reason: str) -> str:
    """The terminal-state fairness note every failure mode resolves to (`FR-CALIB-10`)."""
    return (
        f"{failure_mode}: {reason}, so the run ended at R0 ({r0}) — the class is graded "
        "with the rubric as given and the ambiguous criteria are marked lower-confidence "
        "(CT-CALIB-02, FR-CALIB-10)"
    )
