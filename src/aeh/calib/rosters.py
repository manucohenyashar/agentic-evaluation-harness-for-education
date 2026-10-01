"""Class rosters: each paper's band under R0 and R1, registered or rebuilt from the store."""

from __future__ import annotations

from typing import TYPE_CHECKING

import os
import sqlite3
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aeh.store import Statement

from .errors import CalibrationError

if TYPE_CHECKING:
    from .dual_scoring import DualScoringPlan


#: The class-size cap (seam 3). Production default is None — **no cap**: the gate scores
#: the full class (`NFR-CALIB-02`), and a set cap refuses an oversized class rather than
#: silently scoring a subset, because a gate over a subset is not the gate the requirement
#: describes.
CALIB_CLASS_SIZE_CAP: int | None = None


CALIB_CLASS_SIZE_CAP_ENV: str = "HARNESS_CALIB_CLASS_SIZE_CAP"


def _class_size_cap(environ: Mapping[str, str] | None = None) -> int | None:
    """The class-size cap, read from its knob at call time. None, the production default, means the
    gate scores the whole class. A bad value falls back instead of raising, so a mis-set knob
    cannot stop the gate."""
    source = os.environ if environ is None else environ
    raw = source.get(CALIB_CLASS_SIZE_CAP_ENV)
    if raw is None or not raw.strip():
        return CALIB_CLASS_SIZE_CAP
    try:
        value = int(raw)
    except ValueError:
        return CALIB_CLASS_SIZE_CAP
    return value if value >= 1 else CALIB_CLASS_SIZE_CAP


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
    """The next event timestamp, strictly increasing, in timezone-aware wall time."""
    global _LAST_TICK
    tick = time.time()
    if tick <= _LAST_TICK:
        tick = _LAST_TICK + 0.000001
    _LAST_TICK = tick
    return datetime.fromtimestamp(tick, tz=timezone.utc)


@dataclass(frozen=True)
class _ClassRoster:
    """One class's bands under R0 and under R1, as the non-inferiority gate reads them
    (CT-PROV-10).

    ``scores`` is per paper, then per criterion: the ``(r0_band, r1_band)`` pair the panel
    assigned under each rubric. A paper *shifts* when any criterion's band differs — a
    full-band move in either direction, direction-neutral by interpretation (see the
    code notes (`docs/code-notes/calib.md`)): a student whose band moved a level has been regraded in a
    teacher-recognizable sense whether the move was up or down."""

    cohort_id: str
    class_size: int
    criteria: tuple[str, ...]
    scores: tuple[tuple[tuple[int, int], ...], ...]
    is_calibration_set: bool = False
    #: Which comparison this roster's bands are of (#375). `_CLASS_ROSTERS` is keyed by cohort
    #: alone and `calib_roster`'s rows by `(cohort_id, r0, r1)`, so without these the cached
    #: roster of ONE comparison would answer the gate's question about ANOTHER — the same
    #: question getting opposite verdicts depending on what happened to be cached.
    #:
    #: `None` on both means "registered by a rung-0 test seam, which declares no comparison":
    #: those seams stay (`FR-CALIB-15`), and a roster that names no comparison answers any.
    r0: str | None = None
    r1: str | None = None

    def answers(self, r0: str, r1: str) -> bool:
        """Whether this roster belongs to the given comparison."""
        return (self.r0 is None and self.r1 is None) or (self.r0, self.r1) == (r0, r1)

    @property
    def shifted_papers(self) -> int:
        """The papers whose band moved a full level on any criterion."""
        return sum(
            1 for paper in self.scores if any(r0_band != r1_band for r0_band, r1_band in paper)
        )


#: Each registered cohort's roster, by cohort id.
_CLASS_ROSTERS: dict[str, _ClassRoster] = {}


# --- the persisted dual-scored roster (FR-CALIB-15, CT-CALIB-17, #375) ----------------------
#
# `_CLASS_ROSTERS` is a module-level dict, so a roster registered into it alone survives
# exactly as long as the process does. The operator who runs the gate on Monday and again on
# Tuesday is a NEW process, and a gate whose class evaporated between the two answers
# "unknown cohort" — `CT-CALIB-17`'s "breaks if". The table below is where a registered
# roster actually lives; the dict is a cache of it, populated on first use.

# The `calib_roster` table itself is declared in `aeh.store` (Tier D migration 11), not
# here: `TC-REQ-89` renders the console with `sys.modules["aeh.calib"] = None`, so a
# module the system must run WITHOUT cannot own a mandatory link in a tier's chain. See
# that migration's own block for the full reasoning.


#: Every statement this module runs against a store, declared here rather than assembled at a
#: call site (`SEC-15`, `FR-STORE-08`): keyword parameters, no interpolation, and the execute
#: sites registered in `KNOWN_EXECUTE_SITES`.
CALIB_STATEMENTS: dict[str, Statement] = {
    # R₀ is named by the package version its run scored, so the run is resolved from the
    # cohort's own ledger. Every run of that version comes back — the registration refuses an
    # ambiguous answer rather than picking one (see `_resolve_r0_run`).
    "select_runs_for_version": Statement(
        "SELECT run_id FROM run WHERE cohort_id = :cohort_id "
        "AND package_version_id = :package_version_id ORDER BY run_id"
    ),
    # Since #359 `criterion_score` is keyed by run, so this read is scoped to R₀'s run and a
    # second run over the same papers cannot leak its bands into the roster.
    "select_run_criterion_scores": Statement(
        "SELECT submission_id, criterion_id, band FROM criterion_score "
        "WHERE run_id = :run_id ORDER BY submission_id, criterion_id"
    ),
    # Re-registering one comparison replaces it rather than accumulating a second copy
    # alongside the first: the roster is the current answer to "what did this comparison
    # score", not an append-only log of attempts at it.
    "delete_roster": Statement(
        "DELETE FROM calib_roster WHERE cohort_id = :cohort_id AND r0 = :r0 AND r1 = :r1"
    ),
    "insert_roster_cell": Statement(
        "INSERT INTO calib_roster (cohort_id, r0, r1, paper_id, criterion_id, "
        "r0_band, r1_band, recorded_at) "
        "VALUES (:cohort_id, :r0, :r1, :paper_id, :criterion_id, "
        ":r0_band, :r1_band, :recorded_at)"
    ),
    "select_calib_roster": Statement(
        "SELECT paper_id, criterion_id, r0_band, r1_band FROM calib_roster "
        "WHERE cohort_id = :cohort_id AND r0 = :r0 AND r1 = :r1 "
        "ORDER BY paper_id, criterion_id"
    ),
}


#: Each executed dual-scoring pass, by `(cohort_id, r1)` — the two values
#: `register_dual_scored_roster` is given to name it by. Written by `run_dual_scoring`.
_EXECUTED_PASSES: dict[tuple[str, str], DualScoringPlan] = {}


#: Where each registered comparison's roster was persisted, by `(cohort_id, r0, r1)`.
#:
#: The gate takes no store — `non_inferiority(r0, r1, cohort_id, threshold)` is its declared
#: signature and `FR-CALIB-15` says it "reads through" the table rather than changing shape —
#: so the lazy load needs a data directory from somewhere. In a process that registered the
#: roster, that is this map; in a genuinely new process it is `HARNESS_DATA_DIR`, the one
#: channel `NFR-STORE-03` says a deployment configures. Nothing else is guessed at.
_ROSTER_SOURCES: dict[tuple[str, str, str], Path] = {}


def _resolve_r0_run(store: Any, cohort_id: str, r0_version: str) -> str:
    """The run whose stored scores are R0's, found in the cohort's ledger by version.

    Refuses zero and refuses more than one. Two runs of one package version leave the
    registration no key to tell them apart, and picking either would put bands in the roster
    that R₀ may not have assigned — the failure the leak arm of `TC-CALIB-20` exists to catch,
    arriving silently instead of as a refusal."""
    rows = store.cohort(cohort_id).query(
        CALIB_STATEMENTS["select_runs_for_version"],
        cohort_id=cohort_id, package_version_id=str(r0_version),
    )
    run_ids = [str(row["run_id"]) for row in rows]
    if not run_ids:
        raise CalibrationError(
            f"cohort {cohort_id!r} has no run of package version {r0_version!r}: the roster's "
            "R₀ half is built from the bands that run actually scored (FR-CALIB-15), so there "
            "is nothing to build it from"
        )
    if len(run_ids) > 1:
        raise CalibrationError(
            f"cohort {cohort_id!r} has {len(run_ids)} runs of package version {r0_version!r} "
            f"({', '.join(run_ids)}): the registration cannot tell which one is R₀, and "
            "picking one would put bands in the roster that R₀ may never have assigned"
        )
    return run_ids[0]


def _r0_bands(store: Any, cohort_id: str, run_id: str) -> dict[tuple[str, str], str]:
    """R0's band for each `(paper, criterion)` cell, from the run's stored score rows."""
    return {
        (str(row["submission_id"]), str(row["criterion_id"])): str(row["band"])
        for row in store.cohort(cohort_id).query(
            CALIB_STATEMENTS["select_run_criterion_scores"], run_id=run_id
        )
    }


def register_dual_scored_roster(
    cohort_id: str, *, r0_version: str, r1_version: str, store: Any
) -> datetime:
    """Build the class roster from the stored R0 scores and the R1 pass, save it, and register it
    for the gate (FR-CALIB-15, CT-CALIB-17).

    ``r0_version`` is the **package version** R₀'s run scored: it names the run whose stored
    ``criterion_score`` rows are R₀'s half, and it is an input to that resolution rather than
    something the table records — the roster's ``r0``/``r1`` columns carry the two *revisions*
    being compared, because those are the only two things `non_inferiority` knows when it
    comes looking for the roster again. ``r1_version`` names the executed
    `run_dual_scoring` pass whose bands are R₁'s half.

    The paper and criterion axes are the sorted submission ids and criterion ids of R₀'s
    scored cells, which is the index space the plan's ``scores`` rows and columns are in — one
    row per submission, one column per criterion, in the roster's own order.

    Returns the moment the roster was recorded. Both halves land in one durable transaction,
    so a roster is never half-written.
    """
    executed = _EXECUTED_PASSES.get((cohort_id, r1_version))
    if executed is None or executed.executed_at is None:
        raise CalibrationError(
            f"no executed dual-scoring pass for cohort {cohort_id!r} under {r1_version!r}: "
            "the roster's R₁ half is the bands run_dual_scoring returned (FR-CALIB-15) — "
            "plan, authorize and run the pass before registering the roster"
        )

    run_id = _resolve_r0_run(store, cohort_id, r0_version)
    bands = _r0_bands(store, cohort_id, run_id)
    if not bands:
        raise CalibrationError(
            f"run {run_id!r} of cohort {cohort_id!r} has no criterion_score rows: R₀ scored "
            "nothing, so there is no roster to build (FR-CALIB-15)"
        )
    papers = sorted({paper for paper, _criterion in bands})
    criteria = sorted({criterion for _paper, criterion in bands})

    if (len(papers), len(criteria)) != (executed.class_size, executed.criteria_count):
        raise CalibrationError(
            f"R₀'s run scored {len(papers)} papers on {len(criteria)} criteria and the "
            f"authorized R₁ pass covered {executed.class_size} × {executed.criteria_count}: "
            "the two halves of a roster describe the same class, and a mismatch would pair "
            "one paper's R₀ band with another's R₁ band"
        )
    missing = [
        (paper, criterion)
        for paper in papers for criterion in criteria if (paper, criterion) not in bands
    ]
    if missing:
        raise CalibrationError(
            f"R₀'s run left {len(missing)} of {len(papers) * len(criteria)} cells unscored "
            f"(e.g. {missing[:3]}): the gate scores the FULL class (NFR-CALIB-02) or refuses"
        )

    scores = tuple(
        tuple(
            (bands[(paper, criterion)], str(executed.scores[paper_index][criterion_index]))
            for criterion_index, criterion in enumerate(criteria)
        )
        for paper_index, paper in enumerate(papers)
    )

    recorded_at = _next_timestamp()
    handle = store.durable()
    with handle.transaction() as tx:
        tx.execute(
            CALIB_STATEMENTS["delete_roster"],
            cohort_id=cohort_id, r0=executed.r0, r1=executed.r1,
        )
        for paper_index, paper in enumerate(papers):
            for criterion_index, criterion in enumerate(criteria):
                r0_band, r1_band = scores[paper_index][criterion_index]
                tx.execute(
                    CALIB_STATEMENTS["insert_roster_cell"],
                    cohort_id=cohort_id,
                    r0=executed.r0,
                    r1=executed.r1,
                    paper_id=paper,
                    criterion_id=criterion,
                    r0_band=r0_band,
                    r1_band=r1_band,
                    recorded_at=recorded_at.isoformat(),
                )

    _CLASS_ROSTERS[cohort_id] = _ClassRoster(
        cohort_id=cohort_id,
        class_size=len(papers),
        criteria=tuple(criteria),
        scores=scores,
        is_calibration_set=False,
        r0=executed.r0,
        r1=executed.r1,
    )
    _ROSTER_SOURCES[(cohort_id, executed.r0, executed.r1)] = Path(store.data_dir)
    return recorded_at


def _roster_from_store(cohort_id: str, *, r0: str, r1: str) -> _ClassRoster | None:
    """Rebuild this comparison's roster from the `calib_roster` table when it is not in
    `_CLASS_ROSTERS`.

    Returns None — never a partial roster and never an invented one — when there is nowhere
    to look or nothing recorded there, so the gate's "unknown cohort" refusal still reads the
    way it always did for a cohort nobody registered.

    The store is opened read-only and closed again: the gate is a reader, and a second writer
    on a file some caller already has open is a lock nobody asked for."""
    from aeh.store import StoreError, data_dir_from_environment, open_store

    # The deployment's configured channel wins. `_ROSTER_SOURCES` is process-local memory of
    # where a registration in THIS process wrote, and a remembered path silently outranking
    # `HARNESS_DATA_DIR` would make the gate read a directory the deployment never named.
    try:
        data_dir = data_dir_from_environment()
    except StoreError:
        data_dir = _ROSTER_SOURCES.get((cohort_id, r0, r1))
    if data_dir is None:
        return None
    if not (Path(data_dir) / "durable.sqlite").exists():
        return None

    # Read-only, so the gate — a reader — takes no write lock on a file some caller already
    # holds open. The open itself is NOT guarded: `IncompleteMigrationChainError` is a refusal
    # that must reach the caller, not something to swallow into "no roster recorded".
    store = open_store(data_dir, read_only=True)
    try:
        rows = [
            dict(row) for row in store.durable().query(
                CALIB_STATEMENTS["select_calib_roster"], cohort_id=cohort_id, r0=r0, r1=r1
            )
        ]
    except sqlite3.OperationalError:
        # A durable file written before #375 is still at Tier D 10 and has no `calib_roster`
        # — and a read-only open applies no migrations (`store.py:2141`), so nothing creates
        # it here. That is a cohort with no recorded roster, which is what the gate's own
        # `CalibrationError` already says; a raw sqlite error at this line would replace a
        # documented refusal with an implementation detail.
        return None
    finally:
        store.close()
    if not rows:
        return None

    cells = {
        (str(row["paper_id"]), str(row["criterion_id"])):
            (str(row["r0_band"]), str(row["r1_band"]))
        for row in rows
    }
    papers = sorted({paper for paper, _criterion in cells})
    criteria = sorted({criterion for _paper, criterion in cells})
    if len(cells) != len(papers) * len(criteria):
        raise CalibrationError(
            f"the recorded roster for cohort {cohort_id!r} ({r0!r} vs {r1!r}) holds "
            f"{len(cells)} cells for {len(papers)} papers × {len(criteria)} criteria: the "
            "gate scores the full class (NFR-CALIB-02) or refuses, never a ragged subset"
        )
    roster = _ClassRoster(
        cohort_id=cohort_id,
        class_size=len(papers),
        criteria=tuple(criteria),
        scores=tuple(
            tuple(cells[(paper, criterion)] for criterion in criteria) for paper in papers
        ),
        is_calibration_set=False,
        r0=r0,
        r1=r1,
    )
    _CLASS_ROSTERS[cohort_id] = roster
    return roster
