"""The M-GRADE test vocabulary: stand-in value objects, seeding helpers, and the
assumed interface, named once.

TS-38 (issue #105) is written **ahead** of #101 (`M-GRADE`, Phase 1), whose story owns
`aeh.grade` — the module does not exist yet. Collecting the assumptions here follows the
`agg_vocabulary.py` / `store_api.py` / `review_vocabulary.py` precedents: state the
assumption where a reader will find it, keep `require()` inside the test body, and make a
rename one edit.

**Design-declared names (detailed-design.md §3.14, CT-GRADE-01..19)**

| Name | Status |
|---|---|
| `aeh.grade:apply_policy(scores, policy) -> GradeComputation` | **declared** — §3.14's Interfaces block, CT-GRADE-02's pure applicator. `GradeComputation`'s field set is NOT pinned; `.total` is the one field read here, the same pin FUZZ-05 declared (a float when the grade stands, `None` when the policy's gate refuses). |
| `GradingService.compute_all / compute_one / coverage / finalize_batch / amend / rollup / export` | **declared** — §3.14's Protocol. Reached through the invented constructor below; the concrete class ships with #101. |
| coverage field names `criteria_total`, `criteria_auto`, `criteria_reviewed`, `criteria_provisional`, `criteria_missing` | **declared** — FR-GRADE-04 / CT-GRADE-04, verbatim. |

**Invented names (declared so they are reconciled deliberately at #101's landing)**

| Name | Status |
|---|---|
| `aeh.grade:resolve_grade(scaled_score, boundaries)` | **invented** — FR-GRADE-03's resolution rule as a module-level pure seam (the `verify_span` / `synthesize` precedent: the design declares the behaviour on the service, the rung-0 cases need a pure entry point). `boundaries` is a sequence of `(grade, scaled_floor)` pairs or `None` when the package declares no table; the rule is the shipped `grade_boundary` DDL's own words (aeh/pkg.py migration 5): *floors are INCLUSIVE — the grade with the greatest floor <= the scaled score resolves*. If #101 implements the composition inside the service, the rename here and in `WRITTEN_AHEAD_BLOCKERS` is one line. |
| `aeh.grade:coverage_for(scores, criterion_ids)` | **invented** — FR-GRADE-04's coverage record as a pure seam. `criterion_ids` is the package's full criterion list, so a criterion with **no** row (its extraction quarantined) is counted `criteria_missing` rather than silently absent. Returns the five design-named counters. |
| `aeh.grade:boundary_risk(total, provisional_intervals, boundaries)` | **invented** — FR-GRADE-05's `boundary_at_risk` as a pure seam. `total` is the computed total **including** the provisional criteria's current points; `provisional_intervals` is the **injected interval source** the case requires (test plan §5.14 TC-GRADE-06; the full-band-range assumption is design `TBD` §7.4, CT-GRADE-19): one `(low, high)` offset pair per provisional criterion — where that criterion's eventual points may yet move relative to its current ones, the full declared band range under the conservative assumption. Because each criterion's current points sit inside its own range, `total` always lies inside the achievable span, so `score_low = total + sum(lows)` and `score_high = total + sum(highs)` bracket every achievable outcome; `at_risk` is set when any boundary floor lies inside `[score_low, score_high]` inclusive both ends — landing exactly on a floor resolves to that floor's band (the shipped DDL's floors are INCLUSIVE), which is the case's third scenario, and containment is exactly "the range spans a band edge". Returns `.at_risk`, `.score_low`, `.score_high` (the latter two `None` when not at risk, per CT-GRADE-05). |
| `aeh.grade:open_grade(store)` | **invented** — the rung-2 constructor (the `open_review` precedent). Design §3.14 declares the service Protocol but no constructor; the service resolves the run's package version from the run row and reads policy/boundaries through `M-PKG`. |

**Assumed of the shipped-and-landing schema** (the `run_id`-column precedent in
`test_completion_predicate.py`): #101's chain is `Depends on: #93 -> #92 -> #91`, so when
`open_grade` exists, `criterion_score` carries the aggregation migration's columns. The
rows written by `write_criterion_scores` name the post-#91 column set
`(submission_id, criterion_id, band, points, state)`; today's table is
`(submission_id, criterion_id, band)` and the extension is #91's, disclosed rather than
hidden. The `state` literals `auto` / `reviewed` / `provisional` are pinned from the
coverage field names (`criteria_auto` …), the vocabulary TC-GRADE-07's fixture uses
("auto-accepted, reviewed, provisional, missing"); a missing criterion has **no** row, so
`missing` is never a row state. `submission_grade`'s full column set (per HLD §9.6, which
is not in this repository) is assumed to carry at least `submission_id`, `revision`,
`state`, `grade`, `total`, `policy_version`, `key_version`, `computed_at`, the five
coverage counters, `boundary_at_risk`, `score_low`, `score_high` and the missing-input
names — reconciled at #101's migration.

**Disclosed stand-ins.** Writing `criterion_score` rows directly is the
`test_completion_predicate.py` pattern: the production writer is `M-AGG`'s
(`criterion_score` is M-AGG's alone to write, CT-AGG's Requires row) and no production
module may bypass it; this support file is test scaffolding standing in for that writer,
writing exactly the rows it will write. The same applies to `backdate_grades` (the
review-window cases need a determinizable "computed_at", and a wall-clock seam on the
service is not a design-declared surface) and to the run-row re-baseline UPDATE in
`test_recompute_on_correction.py`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Sequence

#: The one story whose landing unmarks every M-GRADE case in this suite (test plan §8.2).
GRADE_BLOCKER = "#101"

#: The state literals a criterion-score row carries, pinned from the coverage field names.
SCORE_STATES = ("auto", "reviewed", "provisional")


def score(
    criterion_id: str,
    points: float,
    *,
    state: str = "auto",
    band: str = "B1",
    ordinal: int = 1,
) -> SimpleNamespace:
    """One criterion score in the shape `apply_policy` and `coverage_for` consume.

    `points` is the aggregated figure `M-AGG` derives from the band (FR-AGG-02); `state`
    is the coverage class the row contributes to. A missing criterion is represented by
    the row's **absence**, never by a state — that is the no-imputation rule's input side.
    """
    if state not in SCORE_STATES:
        raise ValueError(
            f"state {state!r} is not one of {SCORE_STATES}; a missing criterion is "
            "represented by the row's absence, not by a state."
        )
    return SimpleNamespace(
        criterion_id=criterion_id,
        band=band,
        ordinal=ordinal,
        points=points,
        state=state,
    )


def boundary(grade: str, scaled_floor: float) -> tuple[str, float]:
    """One `grade_boundary` row in the shipped DDL's shape (`grade`, `scaled_floor`)."""
    return (grade, scaled_floor)


def write_criterion_scores(handle: Any, rows: Sequence[tuple]) -> None:
    """Write `(submission_id, criterion_id, band, points, state)` rows into Tier R.

    The disclosed M-AGG stand-in: see the module docstring. The column set is the
    post-#91 shape the aggregation migration lands, which precedes #101 in #101's own
    dependency chain.
    """
    with handle.transaction() as tx:
        for submission_id, criterion_id, band_name, points, state in rows:
            tx.execute(
                "INSERT INTO criterion_score "
                "(submission_id, criterion_id, band, points, state) "
                "VALUES (:s, :c, :b, :p, :st)",
                s=submission_id,
                c=criterion_id,
                b=band_name,
                p=points,
                st=state,
            )


def grade_rows(handle: Any) -> list[dict]:
    """Read every `submission_grade` row back as dicts, current revision included."""
    return [
        dict(row)
        for row in handle.query("SELECT * FROM submission_grade ORDER BY submission_id, revision")
    ]


def backdate_grades(handle: Any, computed_at: str) -> None:
    """Set every grade's `computed_at` backwards — the review-window cases' stand-in.

    The window runs from grade issuance (ADR-3's review-window semantics read against
    FR-GRADE-10); a wall-clock seam on the service is not a design-declared surface, so
    the state-based stand-in is a direct write of the timestamp the window is measured
    from, disclosed here once.
    """
    with handle.transaction() as tx:
        tx.execute("UPDATE submission_grade SET computed_at = :t", t=computed_at)


__all__ = [
    "GRADE_BLOCKER",
    "SCORE_STATES",
    "backdate_grades",
    "boundary",
    "grade_rows",
    "score",
    "write_criterion_scores",
]
