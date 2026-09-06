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
    "PackageCatalog",
    "PackageDraft",
    "PackageError",
    "PackageVersionId",
    "PublishedVersionImmutableError",
]

#: A package version's id: an opaque string the catalog mints.
PackageVersionId = str


class PackageError(Exception):
    """Base for every `M-PKG` failure. Siblings, never a chain — the exact-type oracle
    convention every module's error taxonomy follows."""


class PublishedVersionImmutableError(PackageError):
    """An update was attempted on a published (`locked = 1`) `package_version`, or on any
    row referencing one (`FR-PKG-01`).

    A published version is the anchor a grade issued years ago resolves to; mutating it —
    or any criterion, band or exemplar beneath it — silently rewrites history. Not
    retryable: the fix is a **revision** (`create_version` with the published version as
    parent), never a mutation."""


# --- the Tier P migration this module contributes (design §3.3's decision table) ---------------
#
# `M-STORE` owns the migration *mechanism*; the owning module contributes the migrations.
# #26's migration adds the lineage columns the schema's minimal 001 set did not carry and
# installs the immutability triggers — the database half of `NFR-PKG-01`.

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
})
STATEMENTS.update(PKG_STATEMENTS)
TIER_MIGRATIONS[Tier.PACKAGE] = TIER_MIGRATIONS[Tier.PACKAGE] + (_PKG_VERSION_LINEAGE,)

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
