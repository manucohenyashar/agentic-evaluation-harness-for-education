"""The compact rung-3 drive the `M-GRADE` contract cases share (TS-71, issue #107).

The run-shaped world is `tests/support/orch_run.py`'s (built by #63) and the score
vocabulary is `tests/support/grade_vocabulary.py`'s (built by #105); this file adds
the drive shape the delivery cases stand on — seed a run, write the aggregated
`criterion_score` rows the `M-AGG` writer would have written, and compute the run
through the real `GradingService` — compressed to the shapes the nineteen clauses
need:

- `graded_run` — seed, write scores, `compute_all`; one namespace with the cohort
  handle, the service, the run id and the report. Rows are written by the
  vocabulary's disclosed stand-in for `M-AGG`'s writer (`criterion_score` is
  M-AGG's alone to write, `CT-AGG`'s Requires row); the grades are the real
  service's.
- `write_state_row` — the direct insert the breaker-refused shape needs: a row
  whose `state` column is `ungradeable_by_panel` rather than the vocabulary's
  derived pairing. `CT-AGG-07`'s own contract case inserts this way; the
  aggregation state is `M-AGG`'s column and no settled-routing derivation carries
  it, disclosed here once.
- `complete_run` — the disclosed run-row UPDATE (`M-ORCH` is the run row's alone
  to write; the `test_finalization.py` pattern), the state the automatic
  finalization path reads.
- `current_grades` / `grade_row` — the ledger readbacks the cases assert on,
  current-revision-scoped.

Isolation: rung 2-3 — real store, real package, the real grading service; the
socket guard is autouse. The drives write no `submission_grade` row themselves:
every delivered grade a case reads is the service's own write, read back from the
ledger.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterable, Sequence

from aeh.grade import open_grade
from tests.support.grade_vocabulary import write_criterion_scores
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

#: The cohort every seeded run lives in — `orch_run`'s own constant, re-named here
#: so a case reads `drive.COHORT` rather than reaching into the orch support file.
COHORT = ORCH_COHORT_ID


def graded_run(
    store: Any,
    *,
    submissions: Sequence[str],
    criteria: Sequence[dict[str, Any]],
    rows: Iterable[tuple[str, str, str, float | None, str]] = (),
    compute: bool = True,
) -> SimpleNamespace:
    """The whole drive: seeded run, the aggregated score rows written, the real
    grading pass out. `rows` carries `(submission_id, criterion_id, band, points,
    routing)` tuples exactly as `write_criterion_scores` takes them; a submission
    named in `submissions` but absent from `rows` is graded from an empty score
    set — the never-scored shape the missing-input cases sweep. `compute=False`
    skips the pass: the case writes its remaining rows itself (the NULL-points and
    breaker-refused shapes need `_drive.write_state_row`, which the derived
    vocabulary cannot express) and then issues the one grading pass itself."""
    orchestrator, run_id, version = seed_run(
        store, submissions=submissions, criteria=criteria
    )
    cohort = store.cohort(COHORT)
    for submission_id, criterion_id, band, points, routing in rows:
        write_criterion_scores(cohort, [(submission_id, criterion_id, band, points, routing)])
    service = open_grade(store)
    report = service.compute_all(run_id) if compute else None
    return SimpleNamespace(
        orchestrator=orchestrator,
        run_id=run_id,
        version=version,
        cohort=cohort,
        service=service,
        report=report,
    )


def write_state_row(cohort: Any, submission_id: str, criterion_id: str,
                    band: str, points: float | None, routing: str, state: str) -> None:
    """One `criterion_score` row with an explicit aggregation `state` — the
    breaker-refused shape the derived vocabulary cannot write (a row that routes
    `provisional` but whose state says the panel refused), and the quarantined
    shape (a row whose `points` is NULL — the extraction never delivered a figure).
    The `M-AGG` stand-in's escape hatch, disclosed in the module docstring; the
    columns are the shipped det-migration shape, so `points REAL` accepts the NULL
    the CHECKs permit."""
    with cohort.transaction() as tx:
        tx.execute(
            "INSERT OR REPLACE INTO criterion_score "
            "(submission_id, criterion_id, band, points, routing, state) "
            "VALUES (:s, :c, :b, :p, :r, :st)",
            s=submission_id, c=criterion_id, b=band, p=points, r=routing, st=state,
        )


def complete_run(cohort: Any, run_id: str) -> None:
    """Mark the run complete — the state the automatic finalization path reads.

    `M-ORCH` is the run row's single writer; this is the same disclosed stand-in
    `tests/integration/grade/test_finalization.py` uses (`UPDATE run SET status`)."""
    with cohort.transaction() as tx:
        tx.execute("UPDATE run SET status = 'complete' WHERE run_id = :r", r=run_id)


def current_grades(cohort: Any, run_id: str) -> list[dict[str, Any]]:
    """The run's current-revision grade rows, as dicts."""
    return [
        dict(row)
        for row in cohort.query(
            "SELECT * FROM submission_grade "
            "WHERE run_id = :r AND is_current = 1 ORDER BY submission_id",
            r=run_id,
        )
    ]


def grade_revision(cohort: Any, run_id: str, submission_id: str,
                   revision: int) -> dict[str, Any]:
    """One named revision of one submission's grade, as a dict — `None` where no
    such revision exists, so a case can assert a revision's absence too."""
    rows = cohort.query(
        "SELECT * FROM submission_grade "
        "WHERE run_id = :r AND submission_id = :s AND revision = :rev",
        r=run_id, s=submission_id, rev=revision,
    )
    return dict(rows[0]) if rows else None


def criterion_rows(cohort: Any, submission_id: str) -> list[dict[str, Any]]:
    """One submission's stored criterion scores, as dicts — the figures a
    delivered total must decompose into (`TC-GRADE-C07` step 2)."""
    return [
        dict(row)
        for row in cohort.query(
            "SELECT criterion_id, band, points, routing, state FROM criterion_score "
            "WHERE submission_id = :s ORDER BY criterion_id",
            s=submission_id,
        )
    ]


def set_policy(store: Any, version: str, policy: Any) -> None:
    """Install a policy on the seeded package version — the shipped catalog API,
    the way `M-SETUP` writes the policy the grading service then reads."""
    from aeh.pkg import PackageCatalog

    catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
    catalog.set_grade_policy(version, policy)


def set_boundaries(store: Any, version: str,
                   cuts: Sequence[tuple[str, float]]) -> None:
    """Install the grade-boundary table on the seeded version — the shipped
    `PackageCatalog.set_boundaries`, the single canonical representation of the
    resolution rule (`FR-PKG-16`). Cases that need a resolved grade seed this;
    cases that need the no-table null discipline seed nothing."""
    from aeh.pkg import PackageCatalog

    catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
    catalog.set_boundaries(version, cuts)


__all__ = [
    "COHORT",
    "complete_run",
    "criterion_rows",
    "current_grades",
    "grade_revision",
    "graded_run",
    "set_boundaries",
    "set_policy",
    "write_state_row",
]
