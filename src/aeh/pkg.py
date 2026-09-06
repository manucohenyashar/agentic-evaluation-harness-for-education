"""`M-PKG` — Assessment Package Catalog (design §3.4).

Owns Tier P: package identity and version lineage, the §6.2 schema lock, criteria and
bands, the dependency graph, exemplars, the grade policy, and validation records. This
file lands **#26** — version lineage and published-version immutability
(`FR-PKG-01`, `-02`, `-04`, `NFR-PKG-01`); later stories (#27-#31) add the schema lock's
enumerable list, the dependency graph, validation scoping, and export/import.

It owns **no student text**: Tier P never contains student work (design §3.3's tier
table), and nothing here reads or writes any other tier.

Immutability is enforced twice (`NFR-PKG-01`: "a database constraint or a data-layer
guard"):

1. **Data-layer guard** — every mutating `PackageCatalog` method calls `_refuse_mutation`,
   which raises `PublishedVersionImmutableError` before a statement is attempted.
2. **Database triggers** — migration `pkg_version_lineage` installs `BEFORE UPDATE`
   triggers on `package_version` and every table referencing it, so a write that routes
   around the catalog (a raw handle, another process) fails at the database. The trigger
   is the backstop that makes "no caller, including `M-CALIB`, can route around it" a
   property of the *data*, not of who remembers to call the guard.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Sequence

from aeh.store import (
    Migration,
    STATEMENTS,
    Statement,
    Tier,
    TIER_MIGRATIONS,
    current_schema_version,
)

__all__ = [
    "BandSetError",
    "CyclicDependencyError",
    "PackageCatalog",
    "PackageDraft",
    "PackageError",
    "PackageVersionId",
    "PublishedVersionImmutableError",
    "SCHEMA_LOCK_FIELDS",
    "SchemaLockViolation",
]

#: A package version's id: an opaque string the catalog mints.
PackageVersionId = str


class PackageError(Exception):
    """Base for every `M-PKG` failure. Siblings, never a chain — the exact-type oracle
    convention every module's error taxonomy follows."""


class BandSetError(PackageError):
    """A band set violates the structural rules the scoring pipeline assumes
    (`FR-PKG-06`): a `band_count` that is odd or outside 2..6, ordinals that are not
    contiguous from 0, or `points` that are not non-decreasing in ordinal.

    The monotone mapping is what `M-AGG` and `M-GRADE` assume; the even count is the
    design rule that removes the safe middle band a hesitant judge retreats to
    (design §5.10, R40). Not retryable by mutation — the band set is rewritten as a
    whole."""


class CyclicDependencyError(PackageError):
    """A `criterion_dependency` write would make the dependency graph cyclic
    (`FR-PKG-05`).

    The extraction sweep's two-pass order rests on the graph being a DAG; a cycle would
    strand the cycle's criteria in the second pass forever. Not retryable — the edge is
    the mistake."""


class SchemaLockViolation(PackageError):
    """An edit the HLD §6.2 lock forbids was attempted (`FR-PKG-03`).

    The message names the offending field, because `M-CALIB` routes every rubric edit
    through this module (`FR-CALIB-07`) and an operator fixing a refused edit needs the
    field, not a generic refusal. The forbidden-field list is `SCHEMA_LOCK_FIELDS` — one
    place in the source, enumerable at runtime (`NFR-PKG-03`); a second copy of the list
    is how a locked field quietly becomes editable.

    Not retryable by mutation: the sanctioned vehicle for every clarification is a new
    version (`FR-PKG-04`).
    """


class PublishedVersionImmutableError(PackageError):
    """An update was attempted on a published (`locked = 1`) `package_version`, or on any
    row referencing one (`FR-PKG-01`).

    A published version is the anchor a grade issued years ago resolves to; mutating it —
    or any criterion, band or exemplar beneath it — silently rewrites history. Not
    retryable: the fix is a **revision** (`create_version` with the published version as
    parent), never a mutation."""


#: The §6.2 schema lock, in exactly one place (`NFR-PKG-03`): every `(table, field)` edit
#: a published version refuses, enumerable at runtime so a test can assert the list
#: matches HLD §6.2 field for field. `question_type` is the HLD's name for the physical
#: `kind` column — the HLD name is what the list carries, because the enumeration test
#: reads it against the HLD text.
SCHEMA_LOCK_FIELDS: tuple[tuple[str, str], ...] = (
    ("criterion", "max_points"),
    ("criterion", "add"),
    ("criterion", "remove"),
    ("criterion", "question_type"),
    ("criterion", "scoring_model"),
    ("criterion", "construct_tag"),
    ("band", "label"),
    ("band", "ordinal"),
    ("band", "descriptor"),
    ("band", "points"),
    ("criterion_dependency", "add"),
    ("criterion_dependency", "remove"),
    ("criterion_dependency", "alter"),
)


# --- the Tier P migration this module contributes (design §3.3's decision table) ---------------
#
# `M-STORE` owns the migration *mechanism*; the owning module contributes the migrations.
# #26's migration adds the lineage columns the schema's minimal 001 set did not carry and
# installs the immutability triggers — the database half of `NFR-PKG-01`.

_PKG_SCHEMA_LOCK_COLUMNS = Migration(
    version=3,
    name="pkg_schema_lock_columns",
    statements=(
        Statement("ALTER TABLE criterion ADD COLUMN max_points REAL"),
        Statement("ALTER TABLE criterion ADD COLUMN band_count INTEGER"),
        Statement("ALTER TABLE criterion ADD COLUMN scoring_model TEXT"),
        Statement("ALTER TABLE criterion ADD COLUMN construct_tag TEXT"),
        Statement("ALTER TABLE band ADD COLUMN descriptor TEXT"),
    ),
)

_PKG_VERSION_LINEAGE = Migration(
    version=2,
    name="pkg_version_lineage",
    statements=(
        Statement(
            "ALTER TABLE package_version ADD COLUMN parent_version_id "
            "REFERENCES package_version(package_version_id)"
        ),
        Statement("ALTER TABLE package_version ADD COLUMN published_by TEXT"),
        Statement("ALTER TABLE package_version ADD COLUMN published_at TEXT"),
        # The immutability backstops: UPDATE triggers on every guarded table, plus
        # INSERT triggers on the child tables (adding a row to a published version's
        # content is the §6.2 edit-in-place FR-PKG-04 refuses). Both fire only when the
        # referenced version is locked, so a revision's copies into its own unlocked
        # version pass.
        Statement(
            "CREATE TRIGGER package_version_immutable BEFORE UPDATE ON package_version "
            "WHEN OLD.locked = 1 "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: create a "
            "revision instead'); END"
        ),
        Statement(
            "CREATE TRIGGER criterion_immutable BEFORE UPDATE ON criterion "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: criterion "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER band_immutable BEFORE UPDATE ON band "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: band references "
            "a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER criterion_dependency_immutable BEFORE UPDATE ON "
            "criterion_dependency "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: dependency "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER exemplar_immutable BEFORE UPDATE ON exemplar "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: exemplar "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER grade_policy_immutable BEFORE UPDATE ON grade_policy "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: grade policy "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER validation_record_immutable BEFORE UPDATE ON "
            "validation_record "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: validation "
            "record references a published version'); END"
        ),
        # INSERT triggers on the child tables: ADDING a sub-criterion (or band, exemplar,
        # policy, dependency) to a published version is the §6.2 edit-in-place
        # FR-PKG-04 refuses — the new rows would silently change what the published
        # version contains. They fire only when the referenced version is locked, so a
        # revision's copies into its own unlocked version pass.
        Statement(
            "CREATE TRIGGER criterion_insert_locked BEFORE INSERT ON criterion "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: criterion added "
            "to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER band_insert_locked BEFORE INSERT ON band "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: band added to a "
            "published version'); END"
        ),
        Statement(
            "CREATE TRIGGER criterion_dependency_insert_locked BEFORE INSERT ON "
            "criterion_dependency "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: dependency "
            "added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER exemplar_insert_locked BEFORE INSERT ON exemplar "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: exemplar added "
            "to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER grade_policy_insert_locked BEFORE INSERT ON grade_policy "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: grade policy "
            "added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER validation_record_insert_locked BEFORE INSERT ON "
            "validation_record "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: validation "
            "record added to a published version'); END"
        ),
    ),
)

#: The content rows a revision copies from its parent, with explicit column lists —
#: one declared statement per table, parents before children so every copied row's FK is
#: satisfied at insert time. `exemplar` re-mints its id: two revisions of one package
#: share one Tier P file, so a verbatim exemplar_id would collide on the primary key.
_REVISION_COPIES: tuple[str, ...] = (
    "INSERT INTO criterion (package_version_id, criterion_id, question_id, kind) "
    "SELECT :new, criterion_id, question_id, kind FROM criterion "
    "WHERE package_version_id = :old",
    "INSERT INTO band (package_version_id, criterion_id, ordinal, band, points) "
    "SELECT :new, criterion_id, ordinal, band, points FROM band "
    "WHERE package_version_id = :old",
    "INSERT INTO criterion_dependency (package_version_id, criterion_id, depends_on) "
    "SELECT :new, criterion_id, depends_on FROM criterion_dependency "
    "WHERE package_version_id = :old",
    "INSERT INTO exemplar (exemplar_id, package_version_id, criterion_id, band) "
    "SELECT hex(randomblob(8)), :new, criterion_id, band FROM exemplar "
    "WHERE package_version_id = :old",
    "INSERT INTO grade_policy (package_version_id, policy) "
    "SELECT :new, policy FROM grade_policy WHERE package_version_id = :old",
)

#: Every table the immutability triggers guard.


# --- the owning-module contribution to the store's migration registry ---------------------------
#
# Appended at import: after this module is imported, Tier P's current schema version is 2
# and every store opened afterwards applies the lineage migration. The migration's
# statements are registered in the store's STATEMENTS registry too — the store's rule is
# that every statement it can issue is registered, and the registry is built when store.py
# is imported, so the contribution extends it here.

PKG_STATEMENTS: dict[str, Statement] = {
    f"pkg_version_lineage_{index:02d}": statement
    for index, statement in enumerate(_PKG_VERSION_LINEAGE.statements)
}
PKG_STATEMENTS.update({
    "select_version": Statement(
        "SELECT package_version_id, package_id, revision, locked, parent_version_id "
        "FROM package_version WHERE package_version_id = :v"
    ),
    "insert_first_version": Statement(
        "INSERT INTO package_version (package_version_id, package_id, revision, locked) "
        "VALUES (:v, :p, 1, 0)"
    ),
    "insert_revision": Statement(
        "INSERT INTO package_version (package_version_id, package_id, revision, locked, "
        "parent_version_id) VALUES (:v, :p, :rev, 0, :parent)"
    ),
    "publish": Statement(
        "UPDATE package_version SET locked = 1, published_by = :by, "
        "published_at = datetime('now') WHERE package_version_id = :v"
    ),
    "count_package": Statement(
        "SELECT COUNT(*) AS n FROM package WHERE package_id = :p"
    ),
    "pkg_revision_copy_criterion": Statement(
        "INSERT INTO criterion (package_version_id, criterion_id, question_id, kind) "
        "SELECT :new, criterion_id, question_id, kind FROM criterion "
        "WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_band": Statement(
        "INSERT INTO band (package_version_id, criterion_id, ordinal, band, points) "
        "SELECT :new, criterion_id, ordinal, band, points FROM band "
        "WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_dependency": Statement(
        "INSERT INTO criterion_dependency (package_version_id, criterion_id, depends_on) "
        "SELECT :new, criterion_id, depends_on FROM criterion_dependency "
        "WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_exemplar": Statement(
        "INSERT INTO exemplar (exemplar_id, package_version_id, criterion_id, band) "
        "SELECT hex(randomblob(8)), :new, criterion_id, band FROM exemplar "
        "WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_grade_policy": Statement(
        "INSERT INTO grade_policy (package_version_id, policy) "
        "SELECT :new, policy FROM grade_policy WHERE package_version_id = :old"
    ),
    "insert_criterion": Statement(
        "INSERT INTO criterion (package_version_id, criterion_id, question_id, kind, "
        "max_points, scoring_model, construct_tag, band_count) VALUES (:v, "
        ":criterion_id, :question_id, :kind, :max_points, :scoring_model, "
        ":construct_tag, :band_count)"
    ),
    "insert_dependency": Statement(
        "INSERT INTO criterion_dependency (package_version_id, criterion_id, "
        "depends_on) VALUES (:v, :criterion_id, :depends_on)"
    ),
    "insert_band": Statement(
        "INSERT INTO band (package_version_id, criterion_id, ordinal, band, points, "
        "descriptor) VALUES (:v, :criterion_id, :ordinal, :band, :points, :descriptor)"
    ),
    "insert_exemplar": Statement(
        "INSERT INTO exemplar (exemplar_id, package_version_id, criterion_id, band) "
        "VALUES (:exemplar_id, :v, :criterion_id, :band)"
    ),
    "select_criteria": Statement(
        "SELECT criterion_id, question_id, kind, max_points, scoring_model, "
        "construct_tag, band_count FROM criterion WHERE package_version_id = :v "
        "ORDER BY criterion_id"
    ),
    "select_bands": Statement(
        "SELECT criterion_id, ordinal, band, points, descriptor FROM band "
        "WHERE package_version_id = :v ORDER BY criterion_id, ordinal"
    ),
    "select_bands_by_criterion": Statement(
        "SELECT criterion_id, ordinal, band, points, descriptor FROM band "
        "WHERE criterion_id = :criterion_id ORDER BY ordinal"
    ),
    "select_dependencies": Statement(
        "SELECT criterion_id, depends_on FROM criterion_dependency "
        "WHERE package_version_id = :v"
    ),
    "select_latest_version": Statement(
        "SELECT package_version_id FROM package_version ORDER BY revision DESC LIMIT 1"
    ),
    # Per-field UPDATE statements: the SET column cannot be a bound parameter, so each
    # lockable field carries its own literal — the registry stays the one place a
    # statement exists, and the guard selects by field name.
    "update_criterion_max_points": Statement(
        "UPDATE criterion SET max_points = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "update_criterion_question_type": Statement(
        "UPDATE criterion SET kind = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "update_criterion_scoring_model": Statement(
        "UPDATE criterion SET scoring_model = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "update_criterion_construct_tag": Statement(
        "UPDATE criterion SET construct_tag = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "update_band_label": Statement(
        "UPDATE band SET label = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id AND ordinal = :ordinal"
    ),
    "update_band_ordinal": Statement(
        "UPDATE band SET ordinal = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id AND ordinal = :ordinal"
    ),
    "update_band_descriptor": Statement(
        "UPDATE band SET descriptor = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id AND ordinal = :ordinal"
    ),
    "update_band_points": Statement(
        "UPDATE band SET points = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id AND ordinal = :ordinal"
    ),
})
STATEMENTS.update(PKG_STATEMENTS)
TIER_MIGRATIONS[Tier.PACKAGE] = (
    TIER_MIGRATIONS[Tier.PACKAGE]
    + (_PKG_VERSION_LINEAGE,)
    + (_PKG_SCHEMA_LOCK_COLUMNS,)
)

#: The revision copy order: parents before children, so every copied row's FK is
#: satisfied at insert time. Each key names a statement in `PKG_STATEMENTS`.
_REVISION_COPY_KEYS: tuple[str, ...] = (
    "pkg_revision_copy_criterion",
    "pkg_revision_copy_band",
    "pkg_revision_copy_dependency",
    "pkg_revision_copy_exemplar",
    "pkg_revision_copy_grade_policy",
)


# --- the catalog --------------------------------------------------------------------------------


@dataclass(frozen=True)
class PackageDraft:
    """A new package version's content, as `M-SETUP`/`M-CALIB` hand it over.

    #26's scope is identity and lineage, so the draft carries the version's identity
    fields; #28 adds criteria and bands to this shape (the dataclass grows fields, which
    is additive per §3.2's compatibility rule)."""

    title: str = ""


class PackageCatalog:
    """Tier P's data-access layer, over `M-STORE`'s `package(id)` handle.

    Every mutating method funnels through `_refuse_mutation` — the data-layer guard —
    and the database triggers installed by migration 002 backstop the same rule for
    writes that bypass the catalog. The catalog holds one Tier P database (one package
    file), so `catalog = PackageCatalog(store.package(package_id), package_id=package_id)`.
    """

    def __init__(self, handle, *, package_id: str) -> None:
        self._handle = handle
        self._package_id = package_id
        # The per-run cache (NFR-PKG-05): loaded once against a version, invalidated on
        # publish and on any edit. ~23,000 unit reads per run must not re-query SQLite.
        self._cache: dict | None = None
        self._cache_version: str | None = None

    def _guard(self, tx, v: PackageVersionId, field: str) -> None:
        """The one lock check every mutation funnels through.

        A published version refuses EVERY in-place edit; a locked-field edit is named
        specifically (`SchemaLockViolation`), everything else as
        `PublishedVersionImmutableError` — the two errors' distinct meanings, in one
        place. Drafts (locked = 0) edit freely: the copy-on-revision flow exists to give
        clarifications a vehicle, not to forbid authoring."""
        row = tx.execute(PKG_STATEMENTS["select_version"], v=v)[0]
        if not row["locked"]:
            return
        if field in {f"{table}.{name}" for table, name in SCHEMA_LOCK_FIELDS}:
            raise SchemaLockViolation(
                f"the {field!r} edit on package version {v!r} is refused by the §6.2 "
                f"schema lock (FR-PKG-03): changing what is measured invalidates every "
                f"accumulated validation record. The sanctioned vehicle is a new version "
                f"(create_version(parent={v!r}))."
            )
        raise PublishedVersionImmutableError(
            f"package version {v!r} is published (locked = 1) and immutable (FR-PKG-01)."
        )

    def add_criterion(self, v: PackageVersionId, criterion_id: str) -> None:
        """Add a criterion in place — refused on published versions (`TC-PKG-03` case 2);
        the sanctioned vehicle is a revision (`FR-PKG-04`)."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion.add")

    def remove_criterion(self, v: PackageVersionId, criterion_id: str) -> None:
        """Remove a criterion in place — refused on published versions (case 3)."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion.remove")

    def update_criterion_dependency(self, v: PackageVersionId) -> None:
        """Add/remove/alter a dependency row in place — refused on published versions
        (cases 11-13). The row-level shape is #28's; the lock fires here first."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion_dependency.alter")

    # -- structure, graph and the per-run cache (#28) ------------------------------------------

    def add_criterion(
        self, v: PackageVersionId, criterion_id: str, *, question_id: str = "",
        kind: str = "open", max_points: float = 0.0, scoring_model: str = "atomic",
        construct_tag: str = "", dependencies: Sequence[str] = (),
        band_count: int | None = None,
    ) -> None:
        """Add a criterion with its dependency edges, refusing a cycle (`FR-PKG-05`) —
        the guard's add-refusal applies to published versions; drafts add freely. The
        content arguments default so a published version's refusal fires before any
        content is needed (TC-PKG-03 row 2 passes only the id).

        `band_count` is the DECLARED band-set size (`FR-PKG-06`): odd or outside 2..6
        fails at the declare — a set that can never satisfy the even-count rule should
        not exist even as a draft. `add_band` refuses past the declared count."""
        if band_count is not None and (band_count < 2 or band_count > 6
                                       or band_count % 2 != 0):
            raise BandSetError(
                f"a band_count of {band_count} is odd or outside 2..6 (FR-PKG-06). The "
                "even count removes the safe middle band a hesitant judge retreats to "
                "(design §5.10, R40) — declared at the criterion, not discovered after "
                "the bands are written."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion.add")
            tx.execute(PKG_STATEMENTS["insert_criterion"],
                       v=v, criterion_id=criterion_id, question_id=question_id,
                       kind=kind, max_points=max_points, scoring_model=scoring_model,
                       construct_tag=construct_tag, band_count=band_count)
            for depends_on in dependencies:
                tx.execute(PKG_STATEMENTS["insert_dependency"],
                           v=v, criterion_id=criterion_id, depends_on=depends_on)
        self._cache_get(v)
        self._assert_acyclic(self._version_graph(v))
        self._invalidate()

    def add_band(
        self, v: PackageVersionId, criterion_id: str, ordinal: int,
        band: str, points: float, descriptor: str = "",
    ) -> None:
        """Add one band, enforcing the structural rules on the whole set afterwards
        (`FR-PKG-06`)."""
        declared = self._band_count(v, criterion_id)
        with self._handle.transaction() as tx:
            self._guard(tx, v, "band.add-unpublished")
            if declared is not None and ordinal >= declared:
                raise BandSetError(
                    f"band ordinal {ordinal} exceeds the criterion's declared "
                    f"band_count of {declared} (FR-PKG-06)."
                )
            tx.execute(PKG_STATEMENTS["insert_band"],
                       v=v, criterion_id=criterion_id, ordinal=ordinal,
                       band=band, points=points, descriptor=descriptor)
        rows = self._read_bands(criterion_id)
        self._validate_band_order(rows)
        if declared is not None and len(rows) == declared:
            self._validate_band_count(len(rows))
        self._invalidate()

    def add_exemplar(
        self, v: PackageVersionId, exemplar_id: str, criterion_id: str, band: str,
    ) -> None:
        """Add an exemplar, refusing a band that does not name a band declared for the
        criterion (`FR-PKG-07`)."""
        declared = {row["band"] for row in self._read_bands(criterion_id)}
        if band not in declared:
            raise BandSetError(
                f"exemplar names band {band!r}, which criterion {criterion_id!r} does "
                f"not declare (declared: {sorted(declared)}). An exemplar anchored to an "
                "undeclared band would train judges toward a level the scoring pipeline "
                "cannot produce."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, "exemplar.add-unpublished")
            tx.execute(PKG_STATEMENTS["insert_exemplar"],
                       v=v, exemplar_id=exemplar_id, criterion_id=criterion_id,
                       band=band)
        self._invalidate()

    def topological_order(self, v: PackageVersionId) -> tuple[str, ...]:
        """A valid topological order over the version's dependency graph — dependencies
        before dependents, which is `M-ORCH`'s extraction sweep order (`FR-PKG-05`)."""
        return self._toposort(self._version_graph(v))

    def criteria(self, v: PackageVersionId, question_id: str | None = None) -> tuple:
        """The version's criteria, from the per-run cache (`NFR-PKG-05`: read on every
        one of ~23,000 units)."""
        cached = self._cache_get(v)
        if question_id is None:
            return cached["criteria"]
        return tuple(c for c in cached["criteria"] if c["question_id"] == question_id)

    def bands(self, criterion_id: str) -> tuple:
        """The criterion's bands, ordered by ordinal, from the per-run cache."""
        cached = self._cache_current()
        return cached["bands"].get(criterion_id, ())

    def points_for_band(self, criterion_id: str, band: str) -> float:
        """The band→points mapping, monotone in ordinal (`FR-PKG-06`'s guarantee)."""
        for row in self.bands(criterion_id):
            if row["band"] == band:
                return float(row["points"])
        raise PackageError(f"criterion {criterion_id!r} declares no band {band!r}.")

    def _cache_get(self, v: PackageVersionId) -> dict:
        if self._cache_version != v or self._cache is None:
            self._cache = self._load_version(v)
            self._cache_version = v
        return self._cache

    def _cache_current(self) -> dict:
        """The cache, loaded against the file's latest version when no version has been
        read yet — `bands(criterion_id)` carries no version argument by contract
        (`CT-PROV`'s sibling shape: bands belong to the file's current version)."""
        if self._cache is None:
            rows = self._handle.query(PKG_STATEMENTS["select_latest_version"])
            if not rows:
                raise PackageError(
                    "this Tier P database holds no package_version — the cache has "
                    "nothing to load."
                )
            self._cache_get(rows[0]["package_version_id"])
        return self._cache

    def _invalidate(self) -> None:
        """Invalidation on publish and on any edit: the cache must not become a second
        source of truth (design §3.4, #28's own acceptance criterion)."""
        self._cache = None
        self._cache_version = None

    def _load_version(self, v: PackageVersionId) -> dict:
        criteria = [dict(r) for r in self._handle.query(
            PKG_STATEMENTS["select_criteria"], v=v)]
        bands_by_criterion: dict[str, tuple] = {}
        for row in self._handle.query(PKG_STATEMENTS["select_bands"], v=v):
            bands_by_criterion.setdefault(row["criterion_id"], []).append(dict(row))
        bands = {c: tuple(rows) for c, rows in bands_by_criterion.items()}
        return {"criteria": tuple(criteria), "bands": bands}

    def _read_bands(self, criterion_id: str) -> list:
        """Bands read straight from the database — the validators and the exemplar guard
        run against the truth, not against the cache."""
        return self._handle.query(PKG_STATEMENTS["select_bands_by_criterion"],
                                  criterion_id=criterion_id)

    def _version_graph(self, v: PackageVersionId) -> dict[str, set[str]]:
        graph: dict[str, set[str]] = {
            row["criterion_id"]: set()
            for row in self._handle.query(PKG_STATEMENTS["select_criteria"], v=v)
        }
        for row in self._handle.query(PKG_STATEMENTS["select_dependencies"], v=v):
            graph.setdefault(row["criterion_id"], set()).add(row["depends_on"])
            graph.setdefault(row["depends_on"], set())
        return graph

    def _assert_acyclic(self, graph: dict[str, set[str]]) -> None:
        """Kahn's algorithm: a DAG consumes every node; whatever remains is the cycle
        (`FR-PKG-05`)."""
        remaining = {node: set(edges) for node, edges in graph.items()}
        consumed: set[str] = set()
        while remaining:
            ready = [node for node, edges in remaining.items() if edges <= consumed]
            if not ready:
                cycle = sorted(next(iter(remaining.values())) | set(remaining))
                raise CyclicDependencyError(
                    f"the dependency graph is cyclic among {cycle}. The extraction "
                    "sweep's two-pass order (FR-PKG-05) rests on the graph being a DAG."
                )
            for node in ready:
                consumed.add(node)
                del remaining[node]

    def _toposort(self, graph: dict[str, set[str]]) -> tuple[str, ...]:
        """Kahn's algorithm, deterministic: ready nodes emit in sorted order so the
        extraction sweep's order is reproducible."""
        remaining = {node: set(edges) for node, edges in graph.items()}
        consumed: set[str] = set()
        order: list[str] = []
        while remaining:
            ready = sorted(node for node, edges in remaining.items()
                           if edges <= consumed)
            if not ready:
                raise CyclicDependencyError(
                    f"the dependency graph is cyclic among {sorted(remaining)}."
                )
            for node in ready:
                order.append(node)
                consumed.add(node)
                del remaining[node]
        return tuple(order)

    def _band_count(self, v: PackageVersionId, criterion_id: str) -> int | None:
        for row in self._handle.query(PKG_STATEMENTS["select_criteria"], v=v):
            if row["criterion_id"] == criterion_id:
                return row["band_count"]
        return None

    def _validate_band_order(self, rows) -> None:
        """`FR-PKG-06`'s order half: ordinals contiguous from 0, points non-decreasing
        in ordinal — the monotone mapping M-AGG and M-GRADE assume."""
        ordinals = sorted(row["ordinal"] for row in rows)
        points = [float(row["points"]) for row in sorted(rows, key=lambda r: r["ordinal"])]
        if ordinals != list(range(len(ordinals))):
            raise BandSetError(
                f"the band ordinals {ordinals} are not contiguous from 0 (FR-PKG-06). "
                "Gaps would leave an unreachable band in the middle of the mapping."
            )
        if any(later < earlier for earlier, later in zip(points, points[1:])):
            raise BandSetError(
                f"the band points {points} are not non-decreasing in ordinal (FR-PKG-06). "
                "M-AGG and M-GRADE assume the monotone band-to-points mapping."
            )

    def _validate_band_count(self, count: int) -> None:
        """`FR-PKG-06`'s count half: even, within 2..6 — the even count removes the safe
        middle band a hesitant judge retreats to (design §5.10, R40)."""
        if count < 2 or count > 6 or count % 2 != 0:
            raise BandSetError(
                f"a band set of {count} bands is outside 2..6 or odd (FR-PKG-06). The "
                "even count removes the safe middle band a hesitant judge retreats to."
            )

    def update_criterion_field(
        self, v: PackageVersionId, criterion_id: str, field: str, value: Any
    ) -> None:
        """Set one criterion column — the guarded mutation surface `M-CALIB` writes
        through (`FR-CALIB-07`). Refuses locked fields on published versions with
        `SchemaLockViolation` naming the field; permits everything on drafts."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, f"criterion.{field}")
            tx.execute(
                PKG_STATEMENTS[f"update_criterion_{field}"],
                v=v, criterion_id=criterion_id, value=value,
            )
        self._invalidate()

    def update_band_field(
        self, v: PackageVersionId, criterion_id: str, ordinal: int,
        field: str, value: Any,
    ) -> None:
        """Set one band column, under the same guard (`TC-PKG-03` cases 7-10)."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, f"band.{field}")
            tx.execute(
                PKG_STATEMENTS[f"update_band_{field}"],
                v=v, criterion_id=criterion_id, ordinal=ordinal, value=value,
            )
        self._invalidate()

    # -- the lineage surface -----------------------------------------------------------------

    def create_version(
        self, parent: PackageVersionId | None, draft: PackageDraft | None = None
    ) -> PackageVersionId:
        """Mint a version: a brand-new package's first version (`parent=None`) or a
        revision of an existing one (`FR-PKG-02`).

        A revision **copies** the parent's content rows into the new version — the copy is
        how a §6.2 clarification edit happens (`FR-PKG-04`): the edit lands in the new,
        unlocked version, and the parent is untouched. The new version is born unlocked."""
        version_id = f"{self._package_id}@{uuid.uuid4().hex[:12]}"
        with self._handle.transaction() as tx:
            if parent is None:
                self._refuse_no_such_package(tx)
                tx.execute(PKG_STATEMENTS["insert_first_version"],
                           v=version_id, p=self._package_id)
            else:
                # NOTE: the parent may be published — a revision of a published version
                # is exactly FR-PKG-02's flow. create_version only READS the parent
                # (the copy) and INSERTs new rows, so no guard fires here; the triggers
                # backstop the parent's rows against UPDATE, not the lineage copy.
                revision = self._next_revision(tx, parent)
                parent_row = tx.execute(PKG_STATEMENTS["select_version"], v=parent)[0]
                tx.execute(PKG_STATEMENTS["insert_revision"],
                           v=version_id, p=self._package_id, rev=revision,
                           parent=parent)
                for key in _REVISION_COPY_KEYS:
                    tx.execute(PKG_STATEMENTS[key], new=version_id, old=parent)
        _ = draft  # #28 extends the draft with criteria; the identity write needs none
        return version_id

    def publish(self, v: PackageVersionId, approved_by: str) -> None:
        """Set `locked = 1` — the one permitted update to a version row, and the moment
        its immutability begins (`FR-PKG-01`)."""
        self._refuse_mutation(v)
        with self._handle.transaction() as tx:
            tx.execute(PKG_STATEMENTS["publish"], by=approved_by, v=v)
        # FR-PKG-06's count half, at the publish boundary: every declared band_count is
        # fully populated and even/2..6. The per-add checks covered order and ceiling.
        # The validation reads the DATABASE directly — the cache was just invalidated.
        for row in self._handle.query(PKG_STATEMENTS["select_criteria"], v=v):
            criterion = dict(row)
            declared = self._band_count(v, criterion["criterion_id"])
            if declared is not None:
                self._validate_band_count(len(self.bands(criterion["criterion_id"])))
        self._invalidate()

    def is_locked(self, v: PackageVersionId) -> bool:
        """Whether `v` is published. Read surface for the tests and the console."""
        return bool(self._handle.query(_SELECT_VERSION, v=v)[0]["locked"])

    def lineage(self, v: PackageVersionId) -> tuple[PackageVersionId, ...]:
        """The version's ancestry, oldest first — the chain a grade resolves through."""
        chain: list[PackageVersionId] = []
        current: str | None = v
        seen: set[str] = set()
        while current is not None and current not in seen:
            seen.add(current)
            chain.append(current)
            row = self._handle.query(PKG_STATEMENTS["select_version"], v=current)[0]
            current = row["parent_version_id"] if row["parent_version_id"] else None
        return tuple(reversed(chain))

    # -- the guards ---------------------------------------------------------------------------

    def _refuse_mutation(self, v: PackageVersionId) -> None:
        """The data-layer guard (`NFR-PKG-01`): raise before any statement touches a
        published version's rows."""
        row = self._handle.query(PKG_STATEMENTS["select_version"], v=v)
        if not row:
            return  # an unknown version is the caller's next statement's problem
        if row[0]["locked"]:
            raise PublishedVersionImmutableError(
                f"package version {v!r} is published (locked = 1) and immutable "
                f"(FR-PKG-01). A revision is a NEW version with parent_version_id "
                f"(FR-PKG-02) — mint it via create_version(parent={v!r})."
            )

    def _refuse_no_such_package(self, tx) -> None:
        rows = tx.execute(PKG_STATEMENTS["count_package"], p=self._package_id)
        if not rows[0]["n"]:
            raise PackageError(
                f"package {self._package_id!r} does not exist in this Tier P database. "
                "A version is minted into an existing package; the package row arrives "
                "with M-SETUP's initial version."
            )

    def _next_revision(self, tx, parent: PackageVersionId) -> int:
        row = tx.execute(PKG_STATEMENTS["select_version"], v=parent)[0]
        return int(row["revision"]) + 1
