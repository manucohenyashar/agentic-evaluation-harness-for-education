"""Per-criterion figures across rubric revisions, and what the revision gate's outcome means."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .schema import STATS_STATEMENTS
from .records import CriterionFigure
from .comparisons import _require_str_or_none


#: The cohort ids `cohort_with_mixed_revisions` created, each mapping to the
#: store its criterion rows live in — the same fixture registry shape
# `aeh.grade`'s `class_rollup` resolves through, so a fixture cohort a test
#: asked for is the cohort `criterion_figures` reads.
_MIXED_REVISION_COHORTS: dict[str, Any] = {}


def cohort_with_mixed_revisions(store: Any = None) -> str:
    """Test seam: a cohort whose per-criterion record spans two rubric revisions (`pkg-v1` and
    `pkg-v2`, two criteria, one administration), for CT-CALIB-09. The store is registered under the
    returned cohort id so `criterion_figures` finds it, and the rows are written with M-STATS's own
    statement."""
    import tempfile
    import uuid

    from aeh.store import open_store

    if store is None:
        store = open_store(Path(tempfile.mkdtemp(prefix="aeh-stats-mixed-")))
    cohort_id = f"c-stats-mixed-{uuid.uuid4().hex[:10]}"
    handle = store.durable()
    with handle.transaction() as tx:
        for package_version_id, criterion_id, n in (
            ("pkg-v1", "C-01", 12),
            ("pkg-v1", "C-02", 9),
            ("pkg-v2", "C-01", 15),
            ("pkg-v2", "C-02", 7),
        ):
            tx.execute(
                STATS_STATEMENTS["record_criterion_stats"],
                package_version_id=package_version_id,
                criterion_id=criterion_id,
                backend_profile="edge-local-q4",
                panel_build_ref="9f2a1c",
                n=n,
                cohort_id=cohort_id,
            )
    _MIXED_REVISION_COHORTS[cohort_id] = store
    return cohort_id


def criterion_figures(
    cohort_id: str | None = None,
    *,
    data_dir: Path | str | None = None,
) -> tuple[CriterionFigure, ...]:
    """One population's per-criterion figures as the validation record keeps them (FR-STATS-13):
    each criterion, the rubric revision its statistics came from, and the scope.

    The store is resolved from the fixture registry (``cohort_with_mixed_
    revisions`` registers the cohorts it builds), or opened at ``data_dir=``
    where the caller holds one — a cohort neither resolves to is refused, a
    figure sourced from a store the caller did not name being the mislabeled
    claim this module refuses everywhere else."""
    _require_str_or_none("criterion_figures", cohort_id=cohort_id)
    registered = _MIXED_REVISION_COHORTS.get(cohort_id) if cohort_id else None
    if registered is None and data_dir is None:
        raise ValueError(
            f"criterion_figures() has no store for cohort {cohort_id!r}: the "
            "fixture registry does not name it and no data_dir= was given. "
            "Figures from an unnamed store would be claims about nothing."
        )
    statement = STATS_STATEMENTS["select_criterion_stats"]
    if registered is not None:
        rows = registered.durable().query(
            statement, cohort_id=cohort_id
        )
    else:
        from aeh.store import open_store as _open_store

        store = _open_store(data_dir)
        try:
            rows = store.durable().query(statement, cohort_id=cohort_id)
        finally:
            store.close()
    return tuple(
        CriterionFigure(
            criterion_id=str(row["criterion_id"] or ""),
            rubric_version=row["package_version_id"] or None,
            backend_profile=row["backend_profile"] or None,
            panel_build_ref=row["panel_build_ref"] or None,
            n=int(row["n"] or 0),
            cohort_id=row["cohort_id"] or None,
        )
        for row in rows
    )


#: What the revision gate says, per outcome — a description, not a verdict.
#: The pass entry says the two things a reader needs beside a passing gate:
#: what was compared, and what a pass is **not** — the negated sentences are
#: the honest disclosure (`CT-STATS-16`'s discipline, applied to prose: the
#: value never tells the reader the revision is better, because no figure
#: here can).
_REVISION_GATE_DESCRIPTIONS: Mapping[str, str] = {
    "pass": (
        "The revision gate compares one administration's blind labels against "
        "the figure the revised rubric declared, over one criterion, one "
        "population, one backend profile and one panel build. A pass is not "
        "evidence that the revision got better: it is a report that this "
        "administration's blind agreement reached the figure the revision "
        "declared, and nothing else. The gate reports the comparison; whether "
        "the revision is worth keeping is a decision for the consumer, and no "
        "number here makes it for them."
    ),
    "fail": (
        "A fail is a report that this administration's blind agreement did not "
        "reach the figure the revised rubric declared, over the scope the "
        "figure names. It is not a verdict on the system, and it is not "
        "evidence the revision got worse: one administration's comparison "
        "moved the way the declared expectation says, which is the whole of "
        "what this value reports."
    ),
    "no_data": (
        "The gate reports no comparison for this administration: the blind "
        "labels that would support one were not collected, which is the "
        "absence value, not a zero and not a pass carried forward. The "
        "administration's record says so (`CT-STATS-05`'s message), and the "
        "next administration's comparison is the next chance to measure."
    ),
}


def describe_revision_gate(outcome: str) -> str:
    """What the revision gate's outcome means, in plain words a console can show. A pass means a
    comparison was completed, never proof that the revision is better, and the description says so.
    """
    if outcome not in _REVISION_GATE_DESCRIPTIONS:
        raise ValueError(
            f"describe_revision_gate() got outcome={outcome!r}; the gate "
            f"describes {sorted(_REVISION_GATE_DESCRIPTIONS)}."
        )
    return _REVISION_GATE_DESCRIPTIONS[outcome]
