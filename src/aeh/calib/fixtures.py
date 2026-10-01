"""Test seams over real files: a published package, its catalog, and elicitation history."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aeh.pkg import PackageCatalog

from .constants import EDIT_ELIGIBLE_CATEGORY, _FIXTURE_CRITERION_ID, _FIXTURE_PACKAGE_ID
from .elicitation import Finding


def findings_fixture(
    *,
    count: int | None = None,
    affected_counts: Sequence[int] | None = None,
) -> tuple[Finding, ...]:
    """Test seam: hand-built findings with known affected counts, for the ranking and cap tests
    (CT-CALIB-05). The counts are distinct and deliberately out of order, because output in
    discovery order also looks plausible.

    Criterion ids are zero-padded (`CRIT-001`, ...) so they never collide with the ids a
    real test package carries (`CRIT-1`) — an elicitation session from one fixture must
    not be mistaken for a criterion of the other."""
    if affected_counts is not None:
        counts = [int(value) for value in affected_counts]
    else:
        total = count if count is not None else 3
        counts = [((index * 7) % 23) + 1 for index in range(total)]
    return tuple(
        Finding(
            criterion_id=f"CRIT-{index + 1:03d}",
            category=EDIT_ELIGIBLE_CATEGORY,
            submissions_affected=submissions,
            examples=(
                f"student response A for criterion {f'CRIT-{index + 1:03d}'}",
                f"student response B for criterion {f'CRIT-{index + 1:03d}'}",
            ),
        )
        for index, submissions in enumerate(counts)
    )


def tier_p_path_for_test() -> Path:
    """Test seam: the Tier P file a test store uses, `<tmp>/packages/pkg-calib-test.pkg.sqlite`.

    The shape is the store's own layout (`data_dir/packages/<package_id>.pkg.sqlite`),
    so `open_store` on the returned path's grandparent opens exactly this file — which
    is what lets the write audit name the file and observe every `sqlite3.connect` on
    it (`CT-CALIB-06`)."""
    data_dir = Path(tempfile.mkdtemp(prefix="aeh-calib-tierp-"))
    return data_dir / "packages" / f"{_FIXTURE_PACKAGE_ID}.pkg.sqlite"


def _build_published_package(data_dir: Path, package_id: str) -> str:
    """Build a real Tier P package: one published version, one criterion, two bands.

    The build happens OUTSIDE any audit window and the store is closed before the
    caller proceeds: a warm handle emits no `sqlite3.connect` events, so the write
    audit can only observe the edit if the edit's reader reopens the file fresh."""
    # The full migration chain must be imported before the first open (CLAUDE.md):
    import aeh.agg  # noqa: F401
    import aeh.det  # noqa: F401
    import aeh.extract  # noqa: F401
    import aeh.grade  # noqa: F401
    import aeh.ingest  # noqa: F401
    import aeh.integ  # noqa: F401
    import aeh.judge  # noqa: F401
    import aeh.orch  # noqa: F401
    import aeh.review  # noqa: F401
    import aeh.synth  # noqa: F401

    from aeh.store import open_store

    store = open_store(data_dir)
    try:
        handle = store.package(package_id)
        with handle.transaction() as tx:
            tx.execute(
                "INSERT INTO package (package_id, created_at) "
                "VALUES (:package_id, :created_at)",
                package_id=package_id, created_at="2026-01-01T00:00:00",
            )
        catalog = PackageCatalog(handle, package_id=package_id)
        version = catalog.create_version(None)
        catalog.add_criterion(version, _FIXTURE_CRITERION_ID, max_points=4.0, band_count=2)
        catalog.add_band(version, _FIXTURE_CRITERION_ID, 0, "needs work", 0.0,
                         descriptor="the response does not yet meet the criterion")
        catalog.add_band(version, _FIXTURE_CRITERION_ID, 1, "meets it", 4.0,
                         descriptor="the response meets the criterion")
        catalog.publish(version, approved_by="teacher")
        return version
    finally:
        store.close()


class _AuditedStoreWrite:
    """What the write-audit test checks against: every database connection opened on the fixture's
    Tier P file belongs to M-STORE (which owns the connection) and was started by M-CALIB (whose
    `apply_answers` began the chain).

    A plain class with a duck-typed `__eq__` — it matches the audit's `WriteAttempt`
    records field-wise without importing the test-support module, and the comparison
    works because `WriteAttempt.__eq__` declines non-`WriteAttempt` operands so Python
    tries the reflected operation. The claim carries `attributed_to="M-STORE"`, so a
    write `M-CALIB` performed directly (attributed `M-CALIB`) fails the match — that is
    the oracle's teeth."""

    def __init__(self, *, api: str, target: Any, attributed_to: str,
                 initiated_by: str) -> None:
        self.api = api
        self.target = target
        self.attributed_to = attributed_to
        self.initiated_by = initiated_by

    def __eq__(self, other: object) -> bool:
        if not hasattr(other, "api"):
            return NotImplemented
        return (
            other.api == self.api
            and str(other.target) == str(self.target)
            and other.attributed_to == self.attributed_to
            and other.initiated_by == self.initiated_by
        )


class _FixtureCatalog:
    """A `PackageCatalog` wrapper over a real Tier P store that reopens the store only when needed.

    The store is built (`_build_published_package`) and closed BEFORE the facade is
    handed to a test; the first call forwarded reopens it. Two readings of why:

    * the audit reading — `CT-CALIB-06`'s oracle is the write-audit log, and a warm
      handle emits no `sqlite3.connect` events; the lazy reopen is what puts a connect
      on the audit log inside the window, and `.audited_writes` is the claim every
      Tier P event on the file must match;
    * the honesty reading — the facade forwards, records which mutating catalog methods
      were called (`.writes`), and implements nothing: no lock check, no second write
      path, nothing a real catalog call could diverge from."""

    def __init__(self, data_dir: Path, package_id: str, tier_p_path: Path) -> None:
        self._data_dir = data_dir
        self._package_id = package_id
        self._tier_p_path = tier_p_path
        self._inner: PackageCatalog | None = None
        self._store: Any = None
        #: Names of the mutating catalog methods forwarded through this facade, in
        #: call order — `catalog.writes` asserts the edit reached the catalog at all.
        self.writes: list[str] = []

    def _catalog(self) -> PackageCatalog:
        if self._inner is None:
            from aeh.store import open_store

            store = open_store(self._data_dir)
            handle = store.package(self._package_id)
            self._inner = PackageCatalog(handle, package_id=self._package_id)
            self._store = store
        return self._inner

    @property
    def audited_writes(self) -> tuple[_AuditedStoreWrite, ...]:
        """The writes this wrapper expects on the Tier P file: the store reopens (so its
        connections are logged) and writes only through the catalog. Anything else touching the
        file during an audit is a direct write (CT-CALIB-06)."""
        return (
            _AuditedStoreWrite(
                api="sqlite3.connect",
                target=self._tier_p_path,
                attributed_to="M-STORE",
                initiated_by="M-CALIB",
            ),
        )

    def latest_version(self) -> str | None:
        return self._catalog().latest_version()

    def criteria(self, version: str) -> tuple:
        return self._catalog().criteria(version)

    def bands(self, criterion_id: str) -> tuple:
        """Read the current bands. This is a read, so it is not recorded in `.writes`."""
        return self._catalog().bands(criterion_id)

    def create_version(self, parent: str | None) -> str:
        self.writes.append("create_version")
        return self._catalog().create_version(parent)

    def update_band_field(self, version: str, criterion_id: str, ordinal: int,
                          field: str, value: Any) -> None:
        self.writes.append("update_band_field")
        return self._catalog().update_band_field(
            version, criterion_id, ordinal, field, value,
        )

    def update_criterion_field(self, version: str, criterion_id: str, field: str,
                               value: Any) -> None:
        self.writes.append("update_criterion_field")
        return self._catalog().update_criterion_field(version, criterion_id, field, value)

    def add_criterion(self, version: str, criterion_id: str) -> None:
        self.writes.append("add_criterion")
        return self._catalog().add_criterion(version, criterion_id)

    def update_criterion_dependency(self, version: str) -> None:
        self.writes.append("update_criterion_dependency")
        return self._catalog().update_criterion_dependency(version)

    def append_elicitation(self, version: str, question: str,
                           options_offered: Sequence[str], answer_given: str,
                           resulting_edit: str = "") -> str:
        self.writes.append("append_elicitation")
        return self._catalog().append_elicitation(
            version, question, options_offered, answer_given,
            resulting_edit=resulting_edit,
        )


def catalog_for_test(tier_p_path: Path | None = None) -> _FixtureCatalog:
    """Test seam: a `_FixtureCatalog` over a real published package, with its store closed and
    ready to reopen on first use."""
    if tier_p_path is None:
        tier_p_path = tier_p_path_for_test()
    package_id = tier_p_path.name.removesuffix(".pkg.sqlite")
    _build_published_package(tier_p_path.parent.parent, package_id)
    return _FixtureCatalog(tier_p_path.parent.parent, package_id, tier_p_path)


@dataclass(frozen=True)
class _ElicitationHistoryRow:
    """One history row read back: the question asked, the options offered, the answer, and the edit
    it produced (CT-CALIB-11)."""

    question: str
    options: tuple[str, ...]
    answer: str
    edit: str


#: The one UPDATE per history field, each a declared literal with keyword parameters
#: (`FR-STORE-08`): the table is append-only, so every one is a refusal in waiting —
#: the statement exists only so the ATTEMPT is real, and the trigger pair migration 005
#: installs is what aborts it.
_HISTORY_UPDATE_STATEMENTS: dict[str, str] = {
    "question": "UPDATE elicitation_history SET question = :value "
                "WHERE elicitation_id = :row_id",
    "options": "UPDATE elicitation_history SET options_offered = :value "
               "WHERE elicitation_id = :row_id",
    "answer": "UPDATE elicitation_history SET answer_given = :value "
              "WHERE elicitation_id = :row_id",
    "edit": "UPDATE elicitation_history SET resulting_edit = :value "
            "WHERE elicitation_id = :row_id",
}


class _ElicitationHistoryFixture:
    """A real Tier P store's elicitation history, wrapped for the append-only test.

    The append routes through `PackageCatalog.append_elicitation` — the one write door
    the table has (`FR-PKG-20`). The attempted update and delete are deliberately RAW
    SQL, because the case's point is that the refusal lives in the data layer
    (`NFR-PKG-01`): migration 005's unconditional trigger pair aborts them for every
    writer, catalog or not, and the store's `IntegrityError` is surfaced here as
    `AppendOnlyViolation`."""

    class AppendOnlyViolation(Exception):
        """An UPDATE or DELETE reached the store and the store aborted it."""

    def __init__(self) -> None:
        # The full migration chain must be imported before the first open (CLAUDE.md):
        import aeh.agg  # noqa: F401
        import aeh.det  # noqa: F401
        import aeh.extract  # noqa: F401
        import aeh.grade  # noqa: F401
        import aeh.ingest  # noqa: F401
        import aeh.integ  # noqa: F401
        import aeh.judge  # noqa: F401
        import aeh.orch  # noqa: F401
        import aeh.review  # noqa: F401
        import aeh.synth  # noqa: F401

        from aeh.store import open_store

        self._data_dir = Path(tempfile.mkdtemp(prefix="aeh-calib-hist-"))
        self._package_id = "pkg-calib-hist"
        self._store = open_store(self._data_dir)
        handle = self._store.package(self._package_id)
        with handle.transaction() as tx:
            tx.execute(
                "INSERT INTO package (package_id, created_at) "
                "VALUES (:package_id, :created_at)",
                package_id=self._package_id, created_at="2026-01-01T00:00:00",
            )
        catalog = PackageCatalog(handle, package_id=self._package_id)
        self._version = catalog.create_version(None)
        self._handle = handle
        self._catalog = catalog

    def append(self, *, question: str, options: Sequence[str], answer: str,
               edit: str = "") -> str:
        """Append one row through the catalog and return its row id."""
        return self._catalog.append_elicitation(
            self._version, question, options, answer, resulting_edit=edit,
        )

    def update(self, row_id: str, **changes: Any) -> None:
        """Try to update a row; the store's triggers must abort it."""
        if not changes:
            raise ValueError("update needs at least one field to attempt.")
        for name, value in changes.items():
            if name not in _HISTORY_UPDATE_STATEMENTS:
                raise ValueError(
                    f"unknown elicitation-history field {name!r}; the fields the table "
                    f"carries are {sorted(_HISTORY_UPDATE_STATEMENTS)}."
                )
            if name == "options":
                value = json.dumps(list(value))
            try:
                with self._handle.transaction() as tx:
                    tx.execute(_HISTORY_UPDATE_STATEMENTS[name], row_id=row_id, value=value)
            except sqlite3.IntegrityError as error:
                raise self.AppendOnlyViolation(
                    f"the store refused the update: {error} (FR-PKG-20)"
                ) from error

    def delete(self, row_id: str) -> None:
        """Try to delete a row; the store's triggers must abort it."""
        try:
            with self._handle.transaction() as tx:
                tx.execute(
                    "DELETE FROM elicitation_history WHERE elicitation_id = :row_id",
                    row_id=row_id,
                )
        except sqlite3.IntegrityError as error:
            raise self.AppendOnlyViolation(
                f"the store refused the delete: {error} (FR-PKG-20)"
            ) from error

    def all(self) -> tuple[_ElicitationHistoryRow, ...]:
        """Every row in append order, rebuilt from the history alone."""
        rows = self._handle.query(
            "SELECT question, options_offered, answer_given, resulting_edit "
            "FROM elicitation_history ORDER BY rowid"
        )
        return tuple(
            _ElicitationHistoryRow(
                question=row["question"],
                options=tuple(json.loads(row["options_offered"])),
                answer=row["answer_given"],
                edit=row["resulting_edit"],
            )
            for row in rows
        )


def elicitation_history_for_test() -> _ElicitationHistoryFixture:
    """Test seam: a real Tier P store with an `elicitation_history` table, for the append-only test
    (CT-CALIB-11). The store itself does the refusing."""
    return _ElicitationHistoryFixture()
