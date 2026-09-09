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
| `CoverageSummary.grades_by_state`; `FinalizationRecord.finalized`, `.coverage` | **invented field names** on design-declared return types (§3.14's Interfaces block: `coverage(run_id) -> CoverageSummary`, `finalize_batch(run_id, actor) -> FinalizationRecord`). `grades_by_state` maps the three state literals (`final` / `provisional` / `incomplete`) to counts; the record echoes the coverage it named and reports how many grades it finalized. The **automatic** finalization path (FR-GRADE-10) has no Protocol member of its own — it is probed through the service's own declared pass, a `compute_all` re-invocation once the lapse/completion state has changed; if #101 lands the sweep on another surface the rename is one line. |

**Assumed of the shipped-and-landing schema** (the `run_id`-column precedent in
`test_completion_predicate.py`): #101's chain is `Depends on: #93 -> #92 -> #91`, so when
`open_grade` exists, `criterion_score` carries the aggregation migration's columns. The
rows written by `write_criterion_scores` name the post-#91 column set
`(submission_id, criterion_id, band, points, routing, state)`; today's table is
`(submission_id, criterion_id, band)` and the extension is #91's, disclosed rather than
hidden. The **two-column split is the design's, not a bet**: CT-AGG-06 / FR-AGG-07 pin
`routing` ∈ {`auto`, `queued`, `reviewed`, `provisional`, `triage`} — the coverage class
the grade record counts (`criteria_auto` …, the vocabulary TC-GRADE-07's fixture uses:
"auto-accepted, reviewed, provisional, missing") — and CT-AGG-07 / FR-AGG-11 pin
`criterion_score.state` ∈ {`final`, `provisional_unreviewed`, `ungradeable_by_panel`,
`unresolved_selection`}, the aggregation state, which M-GRADE's Requires row names
together with routing as what "distinguish[es] provisional from missing". What **is**
the stand-in's bet is the pairing: the fixtures only ever seed settled rows, so
`write_criterion_scores` derives `state` from `routing` (`auto`/`reviewed` → `final`,
`provisional` → `provisional_unreviewed`; `queued`/`triage` are M-REVIEW's queue
population and are refused here). #91's writer decides the real pairs; until it lands a
row carrying `provisional` routing and `final` state would be a fixture bug, not a
design. A missing criterion has **no** row, so `missing` is never a row value. The
writer is an **upsert** (`INSERT OR REPLACE`): today's shipped PK is
`(submission_id, criterion_id)` (aeh/store.py migration 5), so a rewritten row — the
key-correction leg's re-point, TC-GRADE-12 — must replace the prior row, and a plain
INSERT would fail at fixture time on exactly the rewrite the case exists to exercise.
`submission_grade`'s full column set (per HLD §9.6, which
is not in this repository) is assumed to carry at least `submission_id`, `revision`,
`run_id` and `is_current` (ADR-9's `(run_id, submission_id, revision)` key and
current-flag are design-declared — §3.14's data-structures note), `state`, `grade`,
`total`, `policy_version`, `answer_key_ref` (the shipped `M-PKG` name for the key a
grade pins — `PackageCatalog.answer_key`'s docstring: the grade "pins by
`answer_key_ref`"), `computed_at`, the five coverage counters, `boundary_at_risk`,
`score_low`, `score_high` and the missing-input names — reconciled at #101's migration.

**Disclosed stand-ins.** Writing `criterion_score` rows directly is the
`test_completion_predicate.py` pattern: the production writer is `M-AGG`'s
(`criterion_score` is M-AGG's alone to write, CT-AGG's Requires row) and no production
module may bypass it; this support file is test scaffolding standing in for that writer,
writing exactly the rows it will write. The same applies to `backdate_grades` (the
review-window cases need a determinizable "computed_at", and a wall-clock seam on the
service is not a design-declared surface), to the run-completion UPDATE in
`test_finalization.py` (the `UPDATE run SET status = 'complete'` pattern
`test_resume_and_rerun.py` already uses — the run row is `M-ORCH`'s alone to write) and
to the run-row re-baseline UPDATE in `test_recompute_on_correction.py`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Sequence

#: The one story whose landing unmarks every M-GRADE case in this suite (test plan §8.2).
GRADE_BLOCKER = "#101"

#: The routing literals a criterion-score row's coverage class is drawn from, per
#: CT-AGG-06 / FR-AGG-07. `queued` and `triage` are M-REVIEW's queue population — rows
#: awaiting the teacher or the operator — and this vocabulary never seeds them: grading
#: reads settled rows. A missing criterion is the row's **absence**, never a routing.
ROUTINGS = ("auto", "reviewed", "provisional")

#: The disclosed routing → aggregation-state pairing the stand-in writes, per the
#: schema paragraph in the module docstring (CT-AGG-07's literal set; #91's writer
#: decides the real pairs).
ROUTING_TO_STATE = {
    "auto": "final",
    "reviewed": "final",
    "provisional": "provisional_unreviewed",
}


def score(
    criterion_id: str,
    points: float,
    *,
    routing: str = "auto",
    band: str = "B1",
    ordinal: int = 1,
) -> SimpleNamespace:
    """One criterion score in the shape `apply_policy` and `coverage_for` consume.

    `points` is the aggregated figure `M-AGG` derives from the band (FR-AGG-02);
    `routing` is the coverage class the row contributes to (CT-AGG-06's column). A
    missing criterion is represented by the row's **absence**, never by a routing —
    that is the no-imputation rule's input side. `state` (CT-AGG-07's aggregation
    column) is derived by the disclosed `ROUTING_TO_STATE` mapping.
    """
    if routing not in ROUTINGS:
        raise ValueError(
            f"routing {routing!r} is not one of {ROUTINGS}; a missing criterion is "
            "represented by the row's absence, not by a routing."
        )
    return SimpleNamespace(
        criterion_id=criterion_id,
        band=band,
        ordinal=ordinal,
        points=points,
        routing=routing,
        state=ROUTING_TO_STATE[routing],
    )


def boundary(grade: str, scaled_floor: float) -> tuple[str, float]:
    """One `grade_boundary` row in the shipped DDL's shape (`grade`, `scaled_floor`)."""
    return (grade, scaled_floor)


def write_criterion_scores(handle: Any, rows: Sequence[tuple]) -> None:
    """Write `(submission_id, criterion_id, band, points, routing)` rows into Tier R.

    The disclosed M-AGG stand-in: see the module docstring. The column set is the
    post-#91 shape the aggregation migration lands, which precedes #101 in #101's own
    dependency chain; the `state` column is derived from `routing` by the disclosed
    mapping, and the write is an upsert — a rewritten row (the key-correction leg's
    re-point) replaces the prior one, which today's `(submission_id, criterion_id)` PK
    requires of any rewrite.
    """
    with handle.transaction() as tx:
        for submission_id, criterion_id, band_name, points, routing in rows:
            if routing not in ROUTING_TO_STATE:
                raise ValueError(
                    f"routing {routing!r} is not one the stand-in seeds "
                    f"({sorted(ROUTING_TO_STATE)}); queued/triage rows are M-REVIEW's "
                    "population, and a missing criterion is the row's absence."
                )
            tx.execute(
                "INSERT OR REPLACE INTO criterion_score "
                "(submission_id, criterion_id, band, points, routing, state) "
                "VALUES (:s, :c, :b, :p, :r, :st)",
                s=submission_id,
                c=criterion_id,
                b=band_name,
                p=points,
                r=routing,
                st=ROUTING_TO_STATE[routing],
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
    "ROUTINGS",
    "ROUTING_TO_STATE",
    "backdate_grades",
    "boundary",
    "grade_rows",
    "score",
    "write_criterion_scores",
]
