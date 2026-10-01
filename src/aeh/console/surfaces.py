"""Module-level renderers: package catalog, preflight, calibration, conformance, agreement."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from .vocabulary import (
    CALIBRATION_ARRIVES_IN,
    _GATE_COLUMNS,
    _GATE_FAIL_VALUES,
    _GATE_NOT_REACHED,
    _GATE_PASS_VALUES,
    NO_NEW_VALIDATION_EVIDENCE,
    NO_VALIDATION_FOR_POPULATION,
)
from .queries import _SELECT_COHORT_BREAKER, _SELECT_GATE_ROWS, _SELECT_VALIDATION
from .errors import ProvenanceRefused
from .html import _page, _row_get, _section
from .records import (
    CalibrationRender,
    ExportOutcome,
    GradeRecord,
    PreflightView,
    RenderedPage,
    TouchpointRender,
)


# --- module-level renderers ---------------------------------------------------------------------------


def render_package_catalog(
    store: Any = None,
    *,
    package_version: str | None = None,
    population: str | None = None,
    queries: list[str] | None = None,
) -> str:
    """Screen S1's package card. A package carries validation figures from wherever it has been
    used, and those figures do not transfer to a different population (FR-CONSOLE-26, R23). So for
    a population the package was never used with, the card shows the exact absence sentence and no
    figure, and never uses the word that would name another population's figure."""
    log = queries if queries is not None else []
    rows: list[dict[str, Any]] = []
    package_id = str(package_version or "pkg-unaddressed").rpartition("@")[0] or "pkg-unaddressed"
    if store is not None:
        try:
            handle = None
            data_dir = getattr(store, "data_dir", None)
            if data_dir is None or Path(
                data_dir, "packages", f"{package_id}.pkg.sqlite"
            ).exists():
                # The never-create rule this module's own read path states: a store
                # accessor would mint the package file as a side effect of a render,
                # so a package that was never built renders as the empties it has.
                handle = store.package(package_id)
            if handle is not None:
                log.append(_SELECT_VALIDATION)
                rows = [
                    dict(row)
                    for row in handle.query(
                        _SELECT_VALIDATION,
                        package_version_id=package_version or "",
                        population=population or "",
                    )
                ]
        except Exception:  # noqa: BLE001 — a read view renders empties
            rows = []
    lines = ['<section data-role="package-card">']
    lines.append(f"<h2>Package {escape(str(package_version or 'pkg-unaddressed'))}</h2>")
    if population:
        lines.append(f"<p>Population: {escape(population)}</p>")
    if rows:
        for row in rows:
            lines.append(f"<p>Validation record: {escape(json.dumps(row, sort_keys=True))}</p>")
    else:
        lines.append(f"<p>{escape(NO_VALIDATION_FOR_POPULATION)}.</p>")
        lines.append(
            "<p>Validation figures belong to the population they were measured on. This card "
            "shows none rather than showing one from somewhere else.</p>"
        )
    lines.append("</section>")
    return "".join(lines)


def render_preflight(
    cohort_id: str = "c-unaddressed",
    *,
    drift: dict[str, Any] | None = None,
    store: Any = None,
    gates: dict[str, str] | None = None,
    queries: list[str] | None = None,
) -> PreflightView:
    """Screen S6, built from the given evidence. It shows the checks per gate (`v0` integrity, `v1`
    pages, `v2` structure, `v3` identity, `v4` match). Only the cohort breaker (FR-INGEST-28)
    blocks the run; outstanding quarantine items deliberately do not, because quarantine is the
    operator's separate work (§7.7) and must never hold up a run the class is waiting for.

    The gate rows and the breaker finding are read the way `M-INGEST` reads them —
    through the named cohort's Tier C handle, the same seam `Ingestor.cohort_breaker`
    documents as S6's read path."""
    log = queries if queries is not None else []
    resolved_gates = dict(gates or {gate: _GATE_NOT_REACHED for gate in _GATE_COLUMNS})
    breaker: dict | None = None
    quarantined = 0
    if store is not None and gates is None:
        rows, breaker = _cohort_gate_rows(store, cohort_id, log)
        if rows or breaker is not None:
            resolved_gates = _ladder_from_rows(rows)
            quarantined = sum(1 for row in rows if _row_get(row, "quarantined", 0))
    return PreflightView(
        cohort_id=cohort_id,
        gates=resolved_gates,
        start_run_available=breaker is None,
        drift_shown=drift is not None,
        breaker=dict(breaker) if breaker is not None else None,
        quarantined=quarantined,
    )


def _cohort_gate_rows(
    store: Any, cohort_id: str, log: list[str] | None = None
) -> tuple[list[dict[str, Any]], dict | None]:
    """The cohort's gate rows and breaker finding, read through the cohort tier handle, or empty
    results if the database cannot be read. Opening a real cohort creates its file if missing, and
    a screen must never create one, so a real store is only read when the file exists."""
    data_dir = getattr(store, "data_dir", None)
    if data_dir is not None and not Path(data_dir, "cohorts", f"{cohort_id}.sqlite").exists():
        return [], None
    try:
        handle = store.cohort(cohort_id)
        if log is not None:
            log.append(_SELECT_GATE_ROWS)
            log.append(_SELECT_COHORT_BREAKER)
        rows = [dict(row) for row in handle.query(_SELECT_GATE_ROWS, cohort_id=cohort_id)]
        breaker_rows = [
            dict(row) for row in handle.query(_SELECT_COHORT_BREAKER, cohort_id=cohort_id)
        ]
    except Exception:  # noqa: BLE001
        return [], None
    return rows, (dict(breaker_rows[0]) if breaker_rows else None)


def _ladder_from_rows(rows: list[dict[str, Any]]) -> dict[str, str]:
    ladder: dict[str, str] = {}
    for gate, column in _GATE_COLUMNS.items():
        values = [
            str(_row_get(row, column)) for row in rows if _row_get(row, column) is not None
        ]
        if not values:
            ladder[gate] = _GATE_NOT_REACHED
        elif any(value in _GATE_FAIL_VALUES[gate] for value in values):
            ladder[gate] = "fail"
        elif all(value in _GATE_PASS_VALUES[gate] for value in values):
            ladder[gate] = "pass"
        else:
            ladder[gate] = "fail"
    return ladder


def render_calibration_surface(*, phase_available: int) -> CalibrationRender:
    """A Phase 4 feature shown as present but unavailable, with its version (FR-CONSOLE-25). If it
    were simply missing, a teacher would conclude the feature does not exist rather than that it is
    coming."""
    del phase_available  # the phase is not this console's: the card names the version instead
    return CalibrationRender(
        present=True,
        available=False,
        available_in_version=CALIBRATION_ARRIVES_IN,
    )


def render_discovery(*, package_version: str = "pkg-v1") -> str:
    """The screen listing what the models were unsure about, stored with the package version. It is
    not a measure of how often the models were right, so it shows no percentage and makes no claim
    of accuracy (CT-CALIB-03)."""
    return (
        f"Package version {package_version}: the ambiguity-elicitation questions are recorded "
        "with the version, together with the answers the teacher gave. "
        "The record shows where the models hesitated, and nothing more. "
        "This is a record of the questions, not a measurement of the models. "
        "The figures that exist for a package belong to M-STATS, not to this card."
    )


def render_gate_result(*, outcome: str = "pass") -> str:
    """A calibration gate's result, shown as what passing means: the new version is not worse, and
    nothing more (CT-CALIB-16). Passing is not evidence that the rubric improved, and the screen
    does not present it that way."""
    return (
        f"Gate outcome: {outcome}. "
        "The recorded decision is non-inferiority: the calibrated prompts did not shift the "
        "error rate relative to the reference administration. "
        "A pass says the gate did not trip, and nothing beyond that."
    )


def render_conformance_surface(report: Any) -> str:
    """The backend-conformance screen used in release decisions. It shows missing results when a
    gate could not run, and never claims two backends are equivalent; the console is where such a
    claim would do harm (TC-CONFORM-C14)."""
    lines = ["Conformance record"]
    fixture_set_version = getattr(report, "fixture_set_version", None)
    if fixture_set_version:
        lines.append(f"Fixture set version: {fixture_set_version}")
    for record in getattr(report, "validation_records", ()) or ():
        profile = getattr(record, "backend_profile", "?")
        panel = getattr(record, "panel_build_ref", "?")
        classification = getattr(record, "classification", "?")
        lines.append(f"Backend {profile}, panel {panel}: {classification}.")
        # FR-CONFORM-12: an engine build whose injection-robustness flag is false is marked,
        # informationally; nothing is gated on it (the weakness is accepted, Q-J14). Read off
        # the record's figure, so the console gains no dependency edge (TC-CONSOLE-36).
        figure = getattr(record, "figure", None) or {}
        if figure.get("decision_engine_injection_robust") is False:
            lines.append(
                f"Decision engine build {panel}: not recommended (injection flip rate "
                f"{figure.get('decision_injection_flip_rate')} against the LLM's "
                f"{figure.get('llm_injection_flip_rate')}; informational)")
        for dimension in getattr(record, "unavailable_dimensions", ()) or ():
            lines.append(f"Dimension {dimension} unavailable for {profile}.")
    overall = getattr(report, "classification", None)
    if overall:
        lines.append(f"Overall classification: {overall}.")
    for dimension in getattr(report, "unavailable_dimensions", ()) or ():
        lines.append(f"Dimension {dimension} unavailable: the surface shows the hole.")
    for dimension in getattr(report, "blocking_dimensions", ()) or ():
        lines.append(f"Dimension {dimension} is blocking.")
    for key, value in (getattr(report, "findings", None) or {}).items():
        lines.append(f"Finding {key}: {value}.")
    lines.append(
        "Where a dimension is unavailable, this surface records the hole; it does not claim "
        "the backends are interchangeable."
    )
    return ". ".join(lines) + "."


#: `FR-CONSOLE-38` (GAP-17): what a figure below `aeh.stats.STATS_MIN_N_FOR_HEADLINE` is
#: qualified with. A headline number over a sample too small to support it is the §2.1 error
#: in its most quotable form — the figure goes in a slide deck and the qualifier does not —
#: so the sentence travels WITH the number rather than in a footnote.
TOO_FEW_QUALIFIER = "too few to draw conclusions from"


def render_agreement_block(
    *,
    figure: Any = None,
    no_new_evidence: bool = False,
    previous_administration: Any = None,
    population: str = "",
    package_version: str = "",
) -> str:
    """The agreement block, shown honestly (FR-CONSOLE-24 invariant 20; FR-CONSOLE-10 invariant 5).

    An administration that collected no blind labels renders the absence sentence —
    *never* a zero, which is a real point on the scale and reads as measured-and-bad,
    and *never* a blank, which is the §2.1 error that reads as fine. The previous
    administration's figure is rendered **nowhere in this position** (`RISK-08`): the
    caller may pass it for the separate, labelled prior-record display, and this block
    leaves it there. An administration with figures renders the figure chance-corrected,
    sample-size-adjacent, population- and backend-scoped, and split atomic from
    holistic (`FR-CONSOLE-10`) — and an evidence absence (`NoValidationData`) renders
    as the absence it declares, whatever numeric type carries it.

    `package_version` rides the figure's provenance when one renders (`FR-CONSOLE-09`
    makes provenance a rendering obligation wherever a figure shows; the absence
    sentence stays free of it, because a version beside the absence sentence reads as
    the version the missing evidence belongs to). A figure carrying
    `degenerate_band_shape` (or `band_count = 2`) renders the number **and** the
    degeneracy disclosure — the number is returned, and what it means on a binary band
    scale is stated beside it (`CT-STATS-21`, RISK-30)."""
    scope = f" for population {population}" if population else ""
    reason = getattr(figure, "reason", None)
    if no_new_evidence or figure is None or reason is not None:
        named = f": {str(reason).replace('_', ' ')}" if reason else ""
        return (
            f"Blind labels for this administration{scope}: {NO_NEW_VALIDATION_EVIDENCE}"
            f"{named}. The package's prior record, if any, is shown separately and "
            "labelled with the cohort, population and backend it came from."
        )
    if isinstance(figure, dict):
        kappa = figure.get("kappa")
        alpha = figure.get("ordinal_alpha")
        n = figure.get("n")
        degenerate = figure.get("degenerate_band_shape")
        band_count = figure.get("band_count")
    else:
        kappa = getattr(figure, "kappa", None)
        alpha = getattr(figure, "ordinal_alpha", None)
        n = getattr(figure, "n", None)
        degenerate = getattr(figure, "degenerate_band_shape", None)
        band_count = getattr(figure, "band_count", None)
    # CT-STATS-03/04, FR-CONSOLE-10 (#521): the scope the figure itself carries, read the
    # same way from a mapping or an object. A figure that DECLARES its scope fields and
    # fills none of them (no population, no backend, no panel build) is scopeless: its
    # number is not shown, because a number without a scope cannot be read as anyone's
    # agreement. A partly scoped figure claims only the scope it names. A figure shape
    # that declares no scope field at all (the storeless standing figure) keeps the
    # standing wording.
    scope_fields = ("population_scope_id", "backend_profile", "panel_build_ref")

    def _declares(name: str) -> bool:
        return name in figure if isinstance(figure, dict) else hasattr(figure, name)

    def _scope_field(name: str) -> Any:
        return figure.get(name) if isinstance(figure, dict) else getattr(figure, name, None)

    declared = any(_declares(name) for name in scope_fields)
    figure_population = _scope_field("population_scope_id")
    figure_backend = _scope_field("backend_profile")
    figure_panel = _scope_field("panel_build_ref")
    if figure_population:
        scope = f" for population {figure_population}"
    if declared and (kappa is not None or alpha is not None) and not (
            figure_population or figure_backend or figure_panel):
        return (
            f"Blind labels for this administration{scope}: this agreement figure names no "
            "population, backend or panel build, so it is not shown. An agreement figure "
            "is only readable against the population and backend it was measured on."
        )
    if not declared or (figure_population and figure_backend):
        scoped = "scoped to this population and backend"
    elif figure_population:
        scoped = "scoped to this population; the backend it was measured on is not recorded"
    elif figure_backend:
        scoped = "scoped to this backend; the population it was measured on is not recorded"
    else:
        scoped = "not scoped to a population or backend (panel build only)"
    if kappa is None and alpha is None:
        return (
            f"Blind labels for this administration{scope}: {NO_NEW_VALIDATION_EVIDENCE}. "
            "The package's prior record, if any, is shown separately and labelled with "
            "the cohort, population and backend it came from."
        )
    named = f"kappa {kappa}" if kappa is not None else f"ordinal alpha {alpha}"
    size = f"n = {n}" if n is not None else "sample size as the figure reports it"
    provenance = (
        f" (package version {package_version})" if package_version else ""
    )
    # FR-CONSOLE-38 (GAP-17, HLD §7.9): a figure computed over too small a sample renders
    # WITH the qualifier. The number is still shown — it is the figure the labels support —
    # but a reader who takes 0.41 over eleven papers as the system's agreement is drawing a
    # conclusion the sample cannot carry. The threshold is `aeh.stats`' and is read HERE, at
    # call time (seam 3), so a deployment that lowers it changes the rendering without a
    # code change and without this module keeping a second copy of the number.
    from aeh.stats import STATS_MIN_N_FOR_HEADLINE

    too_few = ""
    if n is not None and int(n) < int(STATS_MIN_N_FOR_HEADLINE):
        too_few = f" This sample is {TOO_FEW_QUALIFIER}."
    degeneracy = ""
    if degenerate or band_count == 2:
        degeneracy = (
            " The band shape is degenerate: a two-band scale makes the statistic "
            "degenerate, so read it beside its band count and beside the bands the "
            "rubric declares."
        )
    return (
        f"Agreement{scope}: {named}, {size}, chance-corrected and "
        f"{scoped}{provenance}; atomic and holistic criteria are "
        f"reported separately and never merged.{too_few}{degeneracy}"
    )


#: HLD §7.9's teacher-touchpoint inventory, transcribed in the document's order, with
#: the surface each row lives on. Eleven of the twelve are Phase 1; the one the MVP does
#: not implement (`MVP_ABSENT_TOUCHPOINT`'s row — Stage B ambiguity elicitation is Phase
#: 4, HLD §11.2) renders present-and-unavailable naming the version, a labelled
#: placeholder rather than a gap (`FR-CONSOLE-25`, R72).
TEACHER_TOUCHPOINT_ROUTES: dict[str, str] = {
    "Confirm the question inventory": "/setup/inventory",
    "Supply multiple-choice answer keys": "/setup/answer-keys",
    "Approve how the rubric was understood": "/setup/inventory",
    "Confirm decomposability classifications": "/setup/inventory",
    "Declare the grade policy and boundaries": "/setup/optional",
    "Answer ambiguity-elicitation questions": CALIBRATION_ARRIVES_IN,
    "Mark 10 to 15 calibration papers": "/setup/optional",
    "Work the review queue": "/runs/{id}/review",
    "Blind sample": "/runs/{id}/blind",
    "Whole-grade sample": "/runs/{id}/sample",
    "Finalize the batch": "/runs/{id}/rollup",
    "Drift check on package reuse": "/packages",
}


MVP_ABSENT_TOUCHPOINT = "Answer ambiguity-elicitation questions"


def touchpoint_surface(app: Any = None) -> dict[str, TouchpointRender]:
    """Every touchpoint in the teacher's workflow, listed against all twelve rows of §7.9
    (CT-CONSOLE-17). Each is either implemented or shown as present but unavailable with the
    version it arrives in. A touchpoint can only be missing here if it was dropped from the list,
    which the vocabulary test checks."""
    rendered: dict[str, TouchpointRender] = {}
    for name, surface in TEACHER_TOUCHPOINT_ROUTES.items():
        if name == MVP_ABSENT_TOUCHPOINT:
            rendered[name] = TouchpointRender(
                implemented=False,
                present=True,
                available=False,
                available_in_version=CALIBRATION_ARRIVES_IN,
            )
        else:
            rendered[name] = TouchpointRender(implemented=True, present=True, available=True)
    return rendered


def amend_finalized_grade(
    app: Any,
    *,
    submission_ref: str,
    criterion_id: str = "",
    new_band: str = "",
    actor: str = "operator",
) -> GradeRecord:
    """Amend a finalized grade (FR-CONSOLE-21, invariant 17). The delivered grade keeps its
    `finalized_at`, and the correction is stored as a new revision; older revisions stay readable
    through `ConsoleApp.grade_revision`. Finalizing does not end editing (R69)."""
    return app.amend_grade(
        submission_ref=submission_ref,
        criterion_id=criterion_id,
        new_band=new_band,
        actor=actor,
    )


def export_package(
    app: Any,
    *,
    package_version: str,
    contains_real_student_text: int | bool = 0,
    actor: str = "operator",
) -> ExportOutcome:
    """Export a package through the export gate (FR-CONSOLE-23, invariant 19, R71).

    A package flagged `contains_real_student_text` is refused by raising `ProvenanceRefused`, not
    by returning a false value, because a quietly failed export looks like a successful one. The
    outcome is recorded whether the gate passes or refuses. The check happens here, where the
    teacher clicks export, and the call still goes to M-PKG so its own refusal is exercised on the
    real path (CT-PKG-13)."""
    flagged = bool(contains_real_student_text)
    if flagged:
        outcome = (
            f"refused: the package carries real student text, so the export did not "
            "happen and no student text left the building"
        )
        app.record_gate_outcome(package_version, outcome, actor=actor)
        raise ProvenanceRefused(
            f"{package_version}: {outcome} (FR-CONSOLE-23; the export gate is screen S14)"
        )
    outcome = "passed: no real student text in the package; exemplar paraphrases approved at export"
    app.perform(
        "approve exemplar paraphrases at export",
        package_version=package_version,
        contains_real_student_text=contains_real_student_text,
        actor=actor,
    )
    exported = app.perform(
        "export/import package",
        package_version=package_version,
        actor=actor,
    )
    if getattr(app._store, "data_dir", None) is not None and not exported.dispatched:
        # On a real store the export is M-PKG's: a refusal there is the gate's outcome,
        # never "passed" (#398).
        refused = f"refused: {exported.detail}"
        app.record_gate_outcome(package_version, refused, actor=actor)
        raise ProvenanceRefused(f"{package_version}: {refused} (FR-CONSOLE-23)")
    app.record_gate_outcome(package_version, f"provenance gate {outcome}", actor=actor)
    return ExportOutcome(
        package_version=package_version,
        contains_real_student_text=False,
        refused=False,
        detail=f"provenance gate {outcome}; outcome recorded on the validation record",
    )


def render_rollup(app: Any, *, run_id: str) -> RenderedPage:
    """The rollup page: the final grades, the agreement block, and the finalization and audit
    lines."""
    return app.render("/runs/{id}/rollup", id=run_id)


def render_submission_text(app: Any, *, text: str) -> RenderedPage:
    """One submission's text, as shown when correcting an answer key (FR-CONSOLE-30, screen S12),
    so the teacher reads what the student wrote before deciding the key was wrong. Module-level so
    the headless driver can use it without a route.

    The console renders the text and states the limitation beside it — never refuses a
    read of student work for its language. Withholding an Arabic submission from the
    one person who can act on it would be a worse failure than showing it inside a
    limitation the page names; the clause (`NFR-CONSOLE-07`) concedes the MVP is
    English and left-to-right and requires the limitation be *visible*, which the
    shell's statement is (`_LIMITATION_SECTION`, `CT-CONSOLE-24`: the system fails or
    degrades visibly, never silently). The text is escaped, so no non-English or RTL
    byte is corrupted into mojibake on the way to the page — the outcome the
    non-promise case forbids regardless of whether a warning also shows.

    Refusal stays available (`RenderedPage.refused`) for a caller-facing refusal path;
    this render chooses the stated-limitation path, so `refused` is False and the
    degradation is the statement, visible on the page."""
    return RenderedPage(
        html=_page(
            "Submission text",
            _section(
                "submission-text",
                "The submission's text, as the correction flow reads it: what the "
                "student's answer carries, shown before a key is corrected against it.",
                escape(str(text)),
            )
            + _section(
                "correction-flow",
                "Correcting an answer key writes a new key version, re-derives the "
                "affected deterministic scores by lookup, re-runs the grade policy, and "
                "enqueues no panel judgment (FR-CONSOLE-30).",
            ),
        ),
        queries=(),
        refused=False,
    )
