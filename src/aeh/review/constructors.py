"""Building a review service: over score rows, over an open store, or over a stored run."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

from .settings import (
    _calibration_knobs,
    _resolve_knob,
    REVIEW_BLIND_N,
    REVIEW_BLIND_RESERVE_MINUTES,
    REVIEW_DEFAULT_BUDGET_MINUTES,
    REVIEW_WHOLE_GRADE_N,
)
from .errors import UnknownRunError
from .schema import REVIEW_STATEMENTS
from .service import ReviewService
from .stored_rows import (
    _newest_run_id,
    _row_mapping,
    _run_row_context,
    _ScoreRowContext,
    _store_cohort_ids,
    _StoredScoreRow,
)


# --- the constructors -------------------------------------------------------------------------------


def build_review(
    scores: Any = None,
    *,
    actor: str = "teacher",
    clock: Callable[[], str] | None = None,
    catalog: Any = None,
    config: Any = None,
    review_blind_reserve_minutes: int | None = None,
    review_blind_n: int | None = None,
    review_whole_grade_n: int | None = None,
    review_default_budget_minutes: int | None = None,
    seed: int | None = None,
    administration_id: str | None = None,
    previous_administration: Any = None,
) -> ReviewService:
    """Build a review service over score rows, or, given a store, over the whole store.

    The four §3.15 knobs arrive as keywords (``review_blind_n=20``), as
    ``config=`` attributes named after the constants, or not at all — the
    module constants are the declared defaults (`CT-REVIEW-17`). The store
    form (`build_review(store)`, the c05/c07/c09 consumer limbs' declared
    shape) reads every cohort the store carries and admits the same
    population `open_review` does; the queue is then the service's read path
    (``.queue()``).

    #111's sampling keywords ride both forms: ``seed=`` reproduces both
    samples' draws, ``administration_id=`` names the administration the skip
    report speaks for, and ``previous_administration=`` is held — never read —
    so the skip report's ``current_figure=None`` is an honest None rather than
    an uninformed one (`FR-REVIEW-13`'s no-carry-forward clause)."""
    if scores is not None and hasattr(scores, "cohort"):
        return _service_from_store(
            scores,
            actor=actor,
            clock=clock,
            catalog=catalog,
            config=config,
            review_blind_reserve_minutes=review_blind_reserve_minutes,
            review_blind_n=review_blind_n,
            review_whole_grade_n=review_whole_grade_n,
            review_default_budget_minutes=review_default_budget_minutes,
            seed=seed,
            administration_id=administration_id,
            previous_administration=previous_administration,
        )
    return ReviewService(
        scores or (),
        actor=actor,
        clock=clock,
        catalog=catalog,
        config=config,
        blind_reserve_minutes=_resolve_knob(
            review_blind_reserve_minutes, config, "REVIEW_BLIND_RESERVE_MINUTES",
            REVIEW_BLIND_RESERVE_MINUTES,
        ),
        blind_n=_resolve_knob(
            review_blind_n, config, "REVIEW_BLIND_N", REVIEW_BLIND_N
        ),
        whole_grade_n=_resolve_knob(
            review_whole_grade_n, config, "REVIEW_WHOLE_GRADE_N", REVIEW_WHOLE_GRADE_N
        ),
        default_budget_minutes=_resolve_knob(
            review_default_budget_minutes, config, "REVIEW_DEFAULT_BUDGET_MINUTES",
            REVIEW_DEFAULT_BUDGET_MINUTES,
        ),
        seed=seed,
        administration_id=administration_id,
        previous_administration=previous_administration,
    )


def review_service_over(
    store: Any,
    *,
    cohort_ids: Sequence[str] | None = None,
    run_id: str | None = None,
    actor: str = "teacher",
    clock: Callable[[], str] | None = None,
    catalog: Any = None,
    config: Any = None,
) -> ReviewService:
    """Build a review service over a store that is already open (FR-CONSOLE-35).

    `open_review` is the constructor for a caller holding a path: it opens its own store and
    asks it for a cohort keyed by the run id, which creates that cohort's file. A caller that
    already has a store — the console, whose screens are reads — must not do either, because
    rendering a screen would then leave a ledger behind (`FR-CONSOLE-01`). Same service, same
    admission, no new file."""
    return _service_from_store(
        store,
        cohort_ids=cohort_ids,
        run_id=run_id,
        actor=actor,
        clock=clock,
        catalog=catalog,
        config=config,
    )


def _service_from_store(
    store: Any,
    *,
    cohort_ids: Sequence[str] | None = None,
    run_id: str | None = None,
    actor: str = "teacher",
    clock: Callable[[], str] | None = None,
    catalog: Any = None,
    config: Any = None,
    review_blind_reserve_minutes: int | None = None,
    review_blind_n: int | None = None,
    review_whole_grade_n: int | None = None,
    review_default_budget_minutes: int | None = None,
    seed: int | None = None,
    administration_id: str | None = None,
    previous_administration: Any = None,
) -> ReviewService:
    """Build a store-backed review service, shared by `open_review` (one cohort) and `build_review`
    (every cohort in the store).

    Reads the cohort's stored ``criterion_score`` rows through ``aeh.store`` —
    the deterministic store, no egress — and maps them onto the score-row
    vocabulary with honest defaults for the columns the store does not carry.
    The query takes both of the teacher's routings (`CT-AGG-06`: ``queued``;
    the provisional family whose fallback and breaker rows `CT-AGG-07` binds
    this module to surface); the state column rides through to the item, and
    the admission predicate — the same one the in-memory service runs — does
    the excluding."""
    # The store's tier migration chains are concatenated at import time by the
    # modules that own the schema they add (CLAUDE.md): the cohort handle this
    # opens must not be the first open in a process that skipped the imports.
    # These ten plus *this module* — which owns Durable's last migration, the
    # #110 label-store columns — make the complete chain; importing aeh.review
    # from inside aeh.review is a no-op, so the ten it does not own are here.
    import aeh.agg  # noqa: F401
    import aeh.det  # noqa: F401
    import aeh.extract  # noqa: F401
    import aeh.grade  # noqa: F401
    import aeh.ingest  # noqa: F401
    import aeh.integ  # noqa: F401
    import aeh.judge  # noqa: F401
    import aeh.orch  # noqa: F401
    import aeh.pkg  # noqa: F401
    import aeh.synth  # noqa: F401

    if cohort_ids is None:
        cohort_ids = _store_cohort_ids(store)
    rows: list[Any] = []
    # The routing narrow is a declared literal, not an assembly: SEC-15's
    # walker (`FR-STORE-08`) forbids building SQL at runtime, so this statement
    # matches ``_ADVISORY_ROUTINGS`` by transcription and the admission_query
    # plan reports the same values. Drift between the two is caught by review
    # of the pair, as the plan's docstring says. The mode and origin halves of
    # the admission ride the predicate on the fetched rows.
    # `run_id` given: that run, in whichever cohort holds it — not each cohort's NEWEST run.
    # Without it S9 for an older run showed the newest run's queue, and a store with two
    # cohorts pooled both cohorts' flagged items into one count. `None` keeps the previous
    # behaviour for callers that mean "this cohort, as it now stands".
    owning: list[str] = []
    for cohort_id in cohort_ids:
        scope = run_id if run_id is not None else _newest_run_id(store, cohort_id)
        if scope is None:
            continue
        found = [
            _row_mapping(row)
            for row in store.cohort(cohort_id).query(
                REVIEW_STATEMENTS["select_run_advisory_scores"], run_id=scope
            )
        ]
        if found:
            owning.append(cohort_id)
        rows.extend((mapping, cohort_id, scope) for mapping in found)
    knobs = _calibration_knobs()
    contexts: dict[tuple[str, str], _ScoreRowContext] = {}
    mapped = []
    for mapping, cohort_id, scope in rows:
        key = (cohort_id, scope)
        if key not in contexts:
            contexts[key] = _run_row_context(store, cohort_id, scope, knobs)
        mapped.append(
            _StoredScoreRow(mapping, knobs["default_est_seconds"], contexts[key])
        )
    service = build_review(
        mapped,
        actor=actor,
        clock=clock,
        catalog=catalog,
        config=config,
        review_blind_reserve_minutes=review_blind_reserve_minutes,
        review_blind_n=review_blind_n,
        review_whole_grade_n=review_whole_grade_n,
        review_default_budget_minutes=review_default_budget_minutes,
        seed=seed,
        administration_id=administration_id,
        previous_administration=previous_administration,
    )._with_store(store, cohort_ids=cohort_ids, owning_cohorts=owning)
    # What the run's package DECLARES, which is a wider set than what the queue holds:
    # `FR-REVIEW-19` answers for every criterion the run scores, including the ones that
    # were auto-accepted and so never reached a teacher's queue.
    declared: dict[str, str] = {}
    for context in contexts.values():
        declared.update(context.declared_models())
    service._declared_models = declared
    return service


def open_review(
    data_dir: Path | str,
    *,
    run_id: str,
    actor: str = "teacher",
    clock: Callable[[], str] | None = None,
    catalog: Any = None,
    config: Any = None,
    review_blind_reserve_minutes: int | None = None,
    review_blind_n: int | None = None,
    review_whole_grade_n: int | None = None,
    review_default_budget_minutes: int | None = None,
    seed: int | None = None,
    administration_id: str | None = None,
    previous_administration: Any = None,
) -> ReviewService:
    """Build a review service over one stored run's flagged score rows.

    Reads the cohort's own ``criterion_score`` rows through ``aeh.store`` — the
    deterministic store, no egress — and admits the same population the
    in-memory service does. Actions write the label store (`FR-REVIEW-09`):
    every label is held in memory and persisted to Tier D's ``label`` table
    (this module's Durable 6 migration adds the columns), attributed to the
    ``run_id`` named here.

    FR-REVIEW-24 / CT-REVIEW-24 (#515): ``run_id`` is resolved to its cohort through
    M-ORCH's run registry (``Orchestrator.run_handle``) and the service holds that run's
    rows only, whatever other runs share the cohort. An unknown run raises
    ``UnknownRunError`` naming it, and no cohort file is created (the run id is never
    used as a cohort key).
    """
    from aeh.orch import Orchestrator, RunNotFoundError
    from aeh.store import open_store as _open_store

    # No cohort file at all means no run anywhere: refuse BEFORE opening the store, whose
    # open lays out the data directory's skeleton (CT-REVIEW-24: nothing is created).
    if not any(Path(data_dir, "cohorts").glob("*.sqlite")):
        raise UnknownRunError(
            f"no stored run is named {run_id!r}: this data directory holds no cohort "
            "(FR-REVIEW-24)")
    store = _open_store(Path(data_dir))
    try:
        try:
            handle = Orchestrator(store).run_handle(run_id)
        except RunNotFoundError:
            raise UnknownRunError(
                f"no stored run is named {run_id!r}: open_review takes a run id, and none of "
                "this data directory's cohorts holds it (FR-REVIEW-24)") from None
        return _service_from_store(
            store,
            cohort_ids=[handle.cohort_id],
            run_id=run_id,
            actor=actor,
            clock=clock,
            catalog=catalog,
            config=config,
            review_blind_reserve_minutes=review_blind_reserve_minutes,
            review_blind_n=review_blind_n,
            review_whole_grade_n=review_whole_grade_n,
            review_default_budget_minutes=review_default_budget_minutes,
            seed=seed,
            administration_id=administration_id,
            previous_administration=previous_administration,
        )
    except Exception:
        store.close()
        raise
