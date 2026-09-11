"""M-CALIB — Rubric Calibration (§3.17): discovery and triage (#137), then the
capped elicitation, the lock write-path and the history (#138).

Two stories have landed. The first (#137) is the half the design builds as a
guardrail before the feature it guards (`§3.17`'s phasing note): discovery of
where a rubric is ambiguous, and the triage that categorizes every disagreement
before anything is revised. The second (#138) is the half a teacher actually
meets: the elicitation that turns edit-eligible findings into at most
`CALIB_MAX_QUESTIONS` questions — ranked by how many submissions the ambiguity
affects — each carrying options and two examples, never a pre-authored edit;
the application of the teacher's answers as rubric clarifications written
**through `M-PKG`'s §6.2 lock**; the history that records every question,
option set, answer and resulting edit; and the skip path, which grades the
class against R₀ unchanged and is never on the critical path. The two
guardrail gates — non-inferiority and back-translation — are #139 and are
still deliberately absent: `ThresholdNotDeclared` in particular does not
exist yet, because the written-ahead registry keys that story on that name
and a story that lands its neighbour's key breaks the gate.

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
`apply_answers`/`run_for_assignment` return structured values, no console on
any path. Deterministic transport: the scoring side of discovery arrives
through injected channels — `model_bands` (the recorded-transport form,
pre-scored under R₀) or the `scorer` callable (the injected scoring seam a
test binds to `RecordedFixtureProvider`-backed code and production binds to
the panel) — so a calibration run needs no network and no real upstream
(`CT-PROV-10`), and the provider stays the only egress point (`CT-PROV-15`).
Env-gated knobs, both read at call time: the aggregate
more-than-a-handful-of-ambiguities alert threshold
(`HARNESS_CALIB_AMBIGUITY_ALERT_AFTER`) and the elicitation cap
(`HARNESS_CALIB_MAX_QUESTIONS`, `FR-CALIB-05` — the cap is the knob, because
teacher time is environment-shaped too). Observability: the report and the
run outcome carry what each stage did — papers scored, criteria excluded as
deterministic, unscored papers, per-stage notes, the aggregate alert, and
the run's fairness note and revision trace — never a bare status.

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
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aeh.det import EVALUATION_MODE_DETERMINISTIC
from aeh.pkg import PackageCatalog, SchemaLockViolation

__all__: tuple[str, ...] = (
    "CALIB_AMBIGUITY_ALERT_AFTER",
    "CALIB_AMBIGUITY_ALERT_AFTER_ENV",
    "CALIB_MAX_QUESTIONS",
    "CALIB_MAX_QUESTIONS_ENV",
    "CalibrationError",
    "CalibrationRunOutcome",
    "Assignment",
    "DEFAULT_PIPELINE_STAGE",
    "Disagreement",
    "DiscoveryReport",
    "EditNotEligible",
    "ElicitationQuestion",
    "EXAMPLES_PER_SIDE_BY_SIDE",
    "Finding",
    "KIND_AMBIGUITY_DISCOVERY",
    "LockedFieldEdit",
    "MODEL_FAILURE",
    "PIPELINE_STAGES",
    "PhaseDependencyError",
    "QUESTION_OPTIONS",
    "RUBRIC_AMBIGUITY",
    "SchemaLockViolation",
    "SideBySideRequired",
    "TEACHER_INCONSISTENCY",
    "TriageCategoryRequired",
    "TriageVerdict",
    "TRIAGE_CATEGORIES",
    "apply_answers",
    "assignment",
    "catalog_for_test",
    "discover",
    "edit_touching",
    "elicitation_history_for_test",
    "field_names_of",
    "findings_fixture",
    "package_version_predating_schema_lock",
    "run_for_assignment",
    "tier_p_path_for_test",
    "triage",
    "elicit",
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
