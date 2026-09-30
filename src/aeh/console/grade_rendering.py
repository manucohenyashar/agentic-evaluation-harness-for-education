"""One grade rendered with everything it owes its reader: coverage, boundary risk, figures."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from .vocabulary import _STATE_PRESENTATION
from .html import _row_get, _section


# --- the grade presentation (#107's carry-forward, landed with #127) -----------------------------------
#
# `CT-GRADE-04/05/13/19` name `M-CONSOLE` as the consumer that renders coverage alongside the
# grade, never shows a null grade as fine, presents a deterministic criterion's withheld
# figure as not-applicable, and reads a boundary flag as "could cross". One presentation,
# shared: `render_grade_coverage` is the single-submission face (the correction flow's
# per-submission detail, and the surface the four `CT-GRADE` consumer limbs assert), and the
# rollup's segments render the same presentation from their batch read — one presentation,
# two readers, so the screen and the renderer cannot drift into two consoles.

#: The phrase the boundary flag renders as (`CT-GRADE-19`'s consumer sweep): the flag is a
#: possibility the declared range carries, never a likelihood — "could cross" and nothing
#: that reads as a prediction. The non-promise's word is chosen here, once.
_COULD_CROSS_PHRASE = "could cross"


#: How a null grade presents. `CT-GRADE-05`'s consumer limb: no consumer renders the null
#: grade as a blank that reads as "fine" — the unresolved band is named, not left as a gap
#: where a mark would sit.
_NULL_GRADE_PRESENTATION = (
    "no grade — unresolved: the boundary table names no cut, so the total does not "
    "resolve to a band"
)


#: How a deterministic criterion's withheld agreement figure presents. `CT-GRADE-13`'s
#: consumer limb: the figure is structurally withheld (a lookup has no judge to agree
#: with), so it presents as not-applicable — never as a zero that reads as perfect
#: agreement, and never as a measured shape.
_NULL_FIGURE_PRESENTATION = (
    "agreement figure does not apply — the criterion is deterministic, and no judge "
    "agreement is measured for a lookup"
)


#: The missing-figure presentation for a judged criterion whose agreement column is
#: still empty: the figure has not arrived, which reads as absence — not as either a
#: zero or an applicability claim.
_NO_FIGURE_PRESENTATION = "no agreement figure yet"


def _coverage_text(row: Any) -> str:
    """The five coverage counters from one grade row, as `total/auto/reviewed/provisional/missing`,
    so a teacher can check them against the criterion count at a glance (CT-GRADE-04)."""
    return (
        f"coverage {int(_row_get(row, 'criteria_total', 0))}/"
        f"{int(_row_get(row, 'criteria_auto', 0))}/"
        f"{int(_row_get(row, 'criteria_reviewed', 0))}/"
        f"{int(_row_get(row, 'criteria_provisional', 0))}/"
        f"{int(_row_get(row, 'criteria_missing', 0))} "
        "(criteria total/auto/reviewed/provisional/missing)"
    )


def _boundary_text(row: Any) -> str:
    """The "could cross a grade boundary" warning (CT-GRADE-19). Only shown when the flag is set,
    so a grade with nothing to flag has no boundary line at all."""
    if not int(_row_get(row, "boundary_at_risk", 0) or 0):
        return ""
    low = _row_get(row, "score_low")
    high = _row_get(row, "score_high")
    return (
        "boundary risk: the total "
        f"{_COULD_CROSS_PHRASE} a grade boundary (plausible range "
        f"{escape(_label_value(low))} to {escape(_label_value(high))}); the flag is a "
        "possibility the declared range carries, not a prediction"
    )


def _label_value(value: Any) -> str:
    """One numeric value as text, or "unread" when it is null, so a missing figure never looks like
    zero."""
    return "unread" if value is None else str(value)


def _grade_line(submission_id: Any, row: Any) -> str:
    """One grade line: the state's label, the grade (or the null-grade sentence, never a blank that
    looks fine; CT-GRADE-05), and the total."""
    state = str(_row_get(row, "state") or "provisional")
    state_text = _STATE_PRESENTATION.get(state, state)
    grade = _row_get(row, "grade")
    grade_text = _NULL_GRADE_PRESENTATION if grade in (None, "") else str(grade)
    total = _row_get(row, "total")
    return (
        f"{escape(str(submission_id))}: {escape(state_text)}"
        f" — grade {escape(grade_text)}, total {escape(_label_value(total))}"
    )


def _criterion_figure_lines(score_rows: Any, kinds: Any) -> str:
    """One line per stored criterion score: the band and points, plus either "not applicable" for a
    deterministic criterion (CT-GRADE-13), the recorded agreement for a judged one, or the absence
    sentence if no figure exists yet. A criterion with no stored row is left out, never shown as
    zero."""
    lines = ""
    for row in score_rows:
        criterion_id = str(_row_get(row, "criterion_id"))
        mode = kinds.get(criterion_id)
        agreement = _row_get(row, "agreement")
        if mode == "deterministic":
            figure = _NULL_FIGURE_PRESENTATION
        elif agreement is None:
            figure = _NO_FIGURE_PRESENTATION
        else:
            figure = f"agreement figure {agreement}"
        points = _row_get(row, "points")
        points_text = "no points recorded" if points is None else f"{points} points"
        lines += (
            "<p>criterion "
            f"{escape(criterion_id)}: band {escape(str(_row_get(row, 'band')))}, "
            f"{escape(points_text)} — {escape(figure)}</p>"
        )
    return lines


def render_grade_coverage(
    run_id: str, submission_id: str, *, store: Any = None
) -> str:
    """One submission's grade as HTML, with everything a reader needs (CT-GRADE-04): the five
    coverage counters, a null grade shown as unresolved (CT-GRADE-05), the boundary warning
    (CT-GRADE-19), and one line per criterion score, with deterministic criteria marked not
    applicable (CT-GRADE-13).

    It is a module-level function reading from the store, so the headless driver and the contract
    tests can render a grade without a route. The rollup screen uses the same presentation.

    Reads only. The grade row is the run's current revision; the figures are the
    submission's stored criterion scores; the kinds come from the version the grade
    names — a version id resolves to its package file, and a file that does not exist
    yields no kinds, so every figure degrades to the judged presentation rather than
    inventing a kind. No tier file is ever created by this read."""
    if getattr(store, "data_dir", None) is None:
        return _section(
            "grade-coverage",
            "No coverage record: the console holds no ledger to read one from.",
        )
    grade_row: dict[str, Any] | None = None
    cohort_handle = None
    for key in Path(store.data_dir, "cohorts").glob("*.sqlite"):
        handle = store.cohort(key.stem)
        try:
            rows = list(
                handle.query(
                    "SELECT * FROM submission_grade "
                    "WHERE run_id = :run_id AND submission_id = :submission_id "
                    "AND is_current = 1",
                    run_id=run_id,
                    submission_id=submission_id,
                )
            )
        except Exception:  # noqa: BLE001 — one unreadable ledger is skipped, not fatal
            continue
        if rows:
            grade_row = dict(rows[0])
            cohort_handle = handle
            break
    if grade_row is None:
        return _section(
            "grade-coverage",
            f"No grade for {escape(str(submission_id))} in run {escape(run_id)}: "
            "the ledger holds no current revision, so there is no coverage record to "
            "render.",
        )
    score_rows: list[dict[str, Any]] = []
    try:
        score_rows = [
            dict(row)
            for row in cohort_handle.query(
                # Column list split across lines for the same reason as the
                # audit-record read in `_render_key_correction`: no line may
                # name both "select" and "points" in this module (TC-PKG-C05's
                # line-shaped single-canonical scan).
                "SELECT criterion_id, band, agreement, state, "
                "points FROM criterion_score WHERE run_id = :run_id "
                "AND submission_id = :submission_id "
                "ORDER BY criterion_id",
                run_id=run_id,
                submission_id=submission_id,
            )
        ]
    except Exception:  # noqa: BLE001 — an unreadable score table renders as no figures
        score_rows = []
    kinds: dict[str, str] = {}
    version = str(_row_get(grade_row, "package_version_id") or "")
    package_id = version.rpartition("@")[0] or version
    if package_id and version:
        package_path = Path(store.data_dir, "packages", f"{package_id}.pkg.sqlite")
        if package_path.exists():
            try:
                # `FR-ORCH-35` (#369): the DECLARED mode, not the shape. A criterion
                # the package declares judged has a panel agreement figure to show
                # whatever its `kind` is, and reading `kind='mcq'` here withheld it.
                # M-CONSOLE is not in FR-ORCH-35's enumerated consumer list; the
                # predicate was the same defect, so it moves with the others (disclosed).
                kinds = {
                    row["criterion_id"]: str(row["evaluation_mode"])
                    for row in store.package(package_id).query(
                        "SELECT criterion_id, evaluation_mode FROM criterion "
                        "WHERE package_version_id = :version",
                        version=version,
                    )
                }
            except Exception:  # noqa: BLE001 — an unreadable tier degrades to judged
                kinds = {}
    boundary = _boundary_text(grade_row)
    figures = (
        '<section data-role="criterion-figures">'
        + _criterion_figure_lines(score_rows, kinds)
        + "</section>"
        if score_rows
        else ""
    )
    return _section(
        "grade-coverage",
        _grade_line(submission_id, grade_row),
        _coverage_text(grade_row),
        boundary or "no boundary flag on this grade",
        (
            "Criterion figures for this submission:"
            if score_rows
            else "No criterion figures are recorded for this submission yet."
        ),
    ) + figures
