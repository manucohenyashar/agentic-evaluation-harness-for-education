"""Discovering where the teacher and the system disagree, and triaging each disagreement."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from aeh.det import EVALUATION_MODE_DETERMINISTIC

from .constants import (
    _ambiguity_alert_after,
    AMBIGUITY_ALERT_TEXT,
    DEFAULT_PIPELINE_STAGE,
    EDIT_ELIGIBLE_CATEGORY,
    EXAMPLES_PER_SIDE_BY_SIDE,
    KIND_AMBIGUITY_DISCOVERY,
    LOGGER,
    MODEL_FAILURE,
    PIPELINE_STAGES,
    TEACHER_INCONSISTENCY,
    TRIAGE_CATEGORIES,
)
from .errors import EditNotEligible, SideBySideRequired, TriageCategoryRequired


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
