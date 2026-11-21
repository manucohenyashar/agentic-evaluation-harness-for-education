"""The validity seed and the record seed (statistical-validity test plan §2.4), built for
Validity T6 (issue #899): scored runs over a real store whose blind labels come from real
draws, drafts and closes through M-REVIEW, and whose administrations are recorded by M-PIPE's
`promote_administration`.

**What is seeded and what is shipped.** The run, the package and the deterministic pass are
`console_world.seed_scored_run` (the shipped modules). The judged cells' bands are written with
`grade_vocabulary.write_scored_cells` (the disclosed M-AGG stand-in) and then set, by one
UPDATE, to the routing the case asks for, `judge_count = 3` and `state = 'final'`:

- the routing is `queued` or `provisional`, the only routings M-REVIEW draws from
  (`review.ranking._ADVISORY_ROUTINGS`), so `auto`, `reviewed` and `triage` cells cannot carry
  a blind label and the plan's routing spread is narrowed to the drawable two;
- `state = 'final'` because FR-STATS-34's baseline reads the run's FINAL judged scores
  (`select_run_final_bands`), and a seed whose cells were all provisional would leave the
  baseline empty.

Everything after that is the shipped path: `blind_sample`, `draft_blind`, `finish_blind` or
`skip_blind_sample` on M-REVIEW's store-backed service, then `promote_administration`.

The bands of both open criteria are named so their alphabetical order is their declared order
(`fail` < `pass`, `B1` < … < `B4`): the in-memory promote has no package scale and ranks bands
by name, and TC-STATS-42 compares it with the durable path.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.support.console_world import ScoredRun, seed_scored_run
from tests.support.grade_vocabulary import write_scored_cells

#: The atomic two-band line, the holistic four-band line, and a deterministic (MCQ) line.
ATOMIC = "C-10"
HOLISTIC = "C-11"
DETERMINISTIC = "C-01"
ATOMIC_BANDS: tuple[str, ...] = ("fail", "pass")
HOLISTIC_BANDS: tuple[str, ...] = ("B1", "B2", "B3", "B4")
BANDS: dict[str, tuple[str, ...]] = {ATOMIC: ATOMIC_BANDS, HOLISTIC: HOLISTIC_BANDS}
PACKAGE_ID = "pkg-validity"

# --- the validity seed: 12 submissions, both lines drawn whole ------------------------------
#
# Indexed by submission (0..11). Atomic, rows = system band, columns = teacher band:
#   system fail x6 (0-5), pass x6 (6-11); teacher fail on 0-4 and 6-7, pass on 5 and 8-11
#   -> confusion [[5, 1], [2, 4]].
# Holistic: system B1 on 0, B2 on 1-10, B3 on 11; teacher B1 on 0-2, B2 on 3-8, B3 on 9-11
#   -> confusion [[1,0,0,0], [2,6,2,0], [0,0,1,0], [0,0,0,0]].
VALIDITY_SYSTEM: dict[str, tuple[str, ...]] = {
    ATOMIC: ("fail",) * 6 + ("pass",) * 6,
    HOLISTIC: ("B1",) + ("B2",) * 10 + ("B3",),
}
VALIDITY_TEACHER: dict[str, tuple[str, ...]] = {
    ATOMIC: ("fail",) * 5 + ("pass",) + ("fail",) * 2 + ("pass",) * 4,
    HOLISTIC: ("B1",) * 3 + ("B2",) * 6 + ("B3",) * 3,
}
#: Cells seeded `provisional` (the rest `queued`), and cells whose scoring unit carries the
#: `escalation` origin (the rest `base`): the drawable spread of routing and origin.
VALIDITY_PROVISIONAL: frozenset[tuple[int, str]] = frozenset(
    {(i, ATOMIC) for i in range(0, 12, 2)} | {(i, HOLISTIC) for i in range(1, 12, 3)})
VALIDITY_ESCALATED: frozenset[tuple[int, str]] = frozenset(
    {(i, ATOMIC) for i in (1, 4, 9)} | {(i, HOLISTIC) for i in (0, 5, 11)})


@dataclass
class Administration:
    """One class's run of the package version: the seeded ids and the cells' system bands."""

    run: ScoredRun
    system: dict[tuple[str, str], str] = field(default_factory=dict)

    @property
    def run_id(self) -> str:
        return self.run.run_id

    @property
    def cohort_id(self) -> str:
        return self.run.cohort_id

    @property
    def package_version_id(self) -> str:
        return self.run.package_version_id

    def submission(self, index: int) -> str:
        return self.run.submissions[index]


class ValidityStore:
    """A real store holding one package version and any number of its administrations."""

    def __init__(self, root: Path) -> None:
        from aeh.store import open_store

        self.root = Path(root)
        self.store = open_store(self.root)
        self.package_version_id: str | None = None

    # -- seeding ---------------------------------------------------------------------------

    def administer(
        self,
        cohort_id: str,
        system: Mapping[str, Sequence[str]],
        *,
        provisional: frozenset[tuple[int, str]] = frozenset(),
        escalated: frozenset[tuple[int, str]] = frozenset(),
    ) -> Administration:
        """Seed and score one administration: `system[criterion][i]` is submission i's
        system band on that open criterion (a criterion left out has no judged cell)."""
        from aeh.pkg import PackageCatalog

        count = max(len(bands) for bands in system.values())
        run = seed_scored_run(
            self.store, cohort_id=cohort_id, run_id=f"run-{cohort_id}", package_id=PACKAGE_ID,
            submissions=count, with_open_criteria=self.package_version_id is None,
            reuse_version=self.package_version_id,
            open_scoring_models={ATOMIC: "atomic", HOLISTIC: "holistic"})
        if self.package_version_id is None:
            self.package_version_id = run.package_version_id
            catalog = self.catalog()
            for criterion, bands in BANDS.items():
                for ordinal, band in enumerate(bands):
                    catalog.add_band(run.package_version_id, criterion, ordinal, band,
                                     float(ordinal))
        administration = Administration(run=run)
        rows = []
        for criterion, bands in system.items():
            for index, band in enumerate(bands):
                administration.system[(run.submissions[index], criterion)] = band
                rows.append((run.submissions[index], criterion, band, 1.0, "auto"))
        cohort = self.store.cohort(cohort_id)
        write_scored_cells(cohort, rows)
        with cohort.transaction() as tx:
            for (submission_id, criterion), _band in administration.system.items():
                index = run.submissions.index(submission_id)
                tx.execute(
                    "UPDATE criterion_score SET routing = :r, judge_count = 3, state = 'final' "
                    "WHERE run_id = :run AND submission_id = :s AND criterion_id = :c",
                    r="provisional" if (index, criterion) in provisional else "queued",
                    run=run.run_id, s=submission_id, c=criterion)
                if (index, criterion) in escalated:
                    tx.execute(
                        "UPDATE work_unit SET origin = 'escalation' WHERE run_id = :run "
                        "AND submission_id = :s AND criterion_id = :c AND stage = 'score'",
                        run=run.run_id, s=submission_id, c=criterion)
        return administration

    def catalog(self) -> Any:
        from aeh.pkg import PackageCatalog

        return PackageCatalog(self.store.package(PACKAGE_ID), package_id=PACKAGE_ID)

    # -- the blind flow, through M-REVIEW's store-backed service ---------------------------

    def service(self, administration: Administration) -> Any:
        from aeh.review import review_service_over

        return review_service_over(self.store, cohort_ids=[administration.cohort_id],
                                   run_id=administration.run_id, catalog=self.catalog(),
                                   actor="teacher")

    def draw(self, administration: Administration, n: int) -> list[tuple[str, str, str]]:
        """Open the draw; `(seat_id, submission_id, criterion_id)` per seat, in seat order."""
        service = self.service(administration)
        service.blind_sample(administration.run_id, n)
        seats = service.blind_seats(administration.run_id)
        items = service.blind_draw_items(administration.run_id)
        return [(seat["seat_id"], item.submission_id, item.criterion_id)
                for seat, item in zip(seats, items, strict=True)]

    def mark(self, administration: Administration, seats: Sequence[tuple[str, str, str]],
             teacher: Mapping[tuple[str, str], str]) -> int:
        """Draft the teacher's band on every drawn seat `teacher` names; returns the count."""
        service = self.service(administration)
        marked = 0
        for seat_id, submission_id, criterion in seats:
            band = teacher.get((submission_id, criterion))
            if band is not None:
                service.draft_blind(administration.run_id, seat_id, band)
                marked += 1
        return marked

    def finish(self, administration: Administration) -> Any:
        return self.service(administration).finish_blind(administration.run_id)

    def skip(self, administration: Administration) -> Any:
        return self.service(administration).skip_blind_sample(administration.run_id)

    def promote(self, administration: Administration, trigger: str) -> Any:
        from aeh.pipeline import promote_administration

        return promote_administration(self.store, administration.run_id, trigger)

    # -- reads -----------------------------------------------------------------------------

    def durable_rows(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        with sqlite3.connect(self.root / "durable.sqlite") as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def labels(self, administration: Administration) -> list[dict[str, Any]]:
        return self.durable_rows("SELECT * FROM label WHERE run_id = ? ORDER BY label_id",
                                 administration.run_id)

    def package_validation(self, administration: Administration) -> list[dict[str, Any]]:
        return self.durable_rows(
            "SELECT * FROM package_validation WHERE package_version_id = ? AND cohort_id = ?",
            administration.package_version_id, administration.cohort_id)

    def criterion_stats(self, administration: Administration) -> dict[str, dict[str, Any]]:
        rows = self.durable_rows(
            "SELECT * FROM criterion_stats WHERE package_version_id = ? AND cohort_id = ?",
            administration.package_version_id, administration.cohort_id)
        return {str(row["criterion_id"]): row for row in rows}

    def insert_label_like(self, source: Mapping[str, Any], **overrides: Any) -> None:
        """Insert a copy of a stored label row with `overrides` applied: the seeding of a
        label the blind flow cannot produce (a deterministic line's, or a late unclaimed
        one), in the column shape the flow writes."""
        row = {**dict(source), **overrides}
        columns = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with sqlite3.connect(self.root / "durable.sqlite") as connection:
            connection.execute(f"INSERT INTO label ({columns}) VALUES ({marks})",
                               tuple(row.values()))

    def insert_labels_like(self, source: Mapping[str, Any],
                           overrides: Sequence[Mapping[str, Any]]) -> None:
        """`insert_label_like` for many rows in one transaction (the bulk seeding a draw,
        capped at 25 seats, cannot reach)."""
        rows = [{**dict(source), **dict(item)} for item in overrides]
        if not rows:
            return
        columns = list(rows[0])
        sql = (f"INSERT INTO label ({', '.join(columns)}) "
               f"VALUES ({', '.join('?' for _ in columns)})")
        with sqlite3.connect(self.root / "durable.sqlite") as connection:
            connection.executemany(sql, [tuple(row[c] for c in columns) for row in rows])

    def run_handle(self, administration: Administration) -> Any:
        from aeh.orch import Orchestrator

        return Orchestrator(self.store).run_handle(administration.run_id)

    def close(self) -> None:
        self.store.close()


def teacher_bands(administration: Administration,
                  teacher: Mapping[str, Sequence[str]]) -> dict[tuple[str, str], str]:
    """`teacher[criterion][i]` keyed by `(submission_id, criterion)`."""
    return {(administration.submission(index), criterion): band
            for criterion, bands in teacher.items() for index, band in enumerate(bands)}


def validity_seed(root: Path) -> tuple[ValidityStore, Administration]:
    """The validity seed, drawn whole and marked: 24 seats (12 per open line), every seat
    drafted with `VALIDITY_TEACHER`, then Finish. Not yet promoted."""
    world = ValidityStore(root)
    administration = world.administer("c-validity", VALIDITY_SYSTEM,
                                      provisional=VALIDITY_PROVISIONAL,
                                      escalated=VALIDITY_ESCALATED)
    seats = world.draw(administration, 24)
    assert len(seats) == 24, f"fixture: the validity seed drew {len(seats)} seats, not 24"
    marked = world.mark(administration, seats, teacher_bands(administration, VALIDITY_TEACHER))
    assert marked == 24, f"fixture: {marked} of 24 seats drafted"
    report = world.finish(administration)
    assert len(report.label_ids) == 24, f"fixture: Finish wrote {len(report.label_ids)} labels"
    return world, administration


__all__ = [
    "ATOMIC",
    "ATOMIC_BANDS",
    "Administration",
    "BANDS",
    "DETERMINISTIC",
    "HOLISTIC",
    "HOLISTIC_BANDS",
    "VALIDITY_SYSTEM",
    "VALIDITY_TEACHER",
    "ValidityStore",
    "teacher_bands",
    "validity_seed",
]
