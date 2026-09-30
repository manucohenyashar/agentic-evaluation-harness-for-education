"""`PackageCatalog`: Tier P's data-access layer over the store's package handle."""

from __future__ import annotations

import json
from typing import Any

from .vocabulary import LOGGER, PackageVersionId
from .errors import PackageError, PublishedVersionImmutableError, SchemaLockViolation
from .lock import _LOCKED_FIELD_HLD_NAMES, SCHEMA_LOCK_FIELDS, SCHEMA_LOCK_VIOLATIONS
from .statements import PKG_STATEMENTS
from .graph import DependencyGraphMixin
from .criteria import CriterionEditsMixin
from .policy_and_keys import PolicyAndKeysMixin
from .validation_reads import ValidationReadsMixin
from .versions import VersionsMixin
from .exchange import ExchangeMixin
from .setup_records import SetupRecordsMixin
from .setup_checks import SetupChecksMixin


class PackageCatalog(DependencyGraphMixin, CriterionEditsMixin, PolicyAndKeysMixin, ValidationReadsMixin, VersionsMixin, ExchangeMixin, SetupRecordsMixin, SetupChecksMixin):
    """Reads and writes one package's Tier P database, through M-STORE's `package(id)` handle.

    Every mutating method funnels through `_refuse_mutation` — the data-layer guard —
    and the database triggers installed by migration 002 backstop the same rule for
    writes that bypass the catalog. The catalog holds one Tier P database (one package
    file), so `catalog = PackageCatalog(store.package(package_id), package_id=package_id)`.
    """

    def __init__(self, handle, *, package_id: str, blobs: Any | None = None) -> None:
        self._handle = handle
        self._package_id = package_id
        # The content-addressed blob store (`store.blobs()`), needed only to carry
        # exemplar-referenced blobs in an export (CT-STORE-07). Optional: a catalog
        # built without one exports text-only packages and refuses a blob-referencing
        # one with a clear error rather than a silent omission.
        self._blobs = blobs
        # The per-run cache (NFR-PKG-05): loaded once against a version, invalidated on
        # publish and on any edit. ~23,000 unit reads per run must not re-query SQLite.
        self._cache: dict | None = None
        self._cache_version: str | None = None

    @property
    def package_id(self) -> str:
        """The package's id. M-INGEST's V4 check compares a paper's printed `Assessment:` line with
        this (FR-INGEST-25); the schema stores no human-readable title yet."""
        return self._package_id

    def _guard(self, tx, v: PackageVersionId, field: str) -> None:
        """The lock check every change goes through.

        A published version refuses EVERY in-place edit; a locked-field edit is named
        specifically (`SchemaLockViolation`), everything else as
        `PublishedVersionImmutableError` — the two errors' distinct meanings, in one
        place. Drafts (locked = 0) edit freely: the copy-on-revision flow exists to give
        clarifications a vehicle, not to forbid authoring."""
        row = tx.execute(PKG_STATEMENTS["select_version"], v=v)[0]
        if not row["locked"]:
            return
        if field in {f"{table}.{name}" for table, name in SCHEMA_LOCK_FIELDS}:
            SCHEMA_LOCK_VIOLATIONS.increment()
            # The HLD's own name for the field, where the guard string and the HLD
            # vocabulary differ (`_LOCKED_FIELD_HLD_NAMES`): the refusal names the field
            # the way the design states it as well as the way the SQL layer spells it.
            hld_name = _LOCKED_FIELD_HLD_NAMES.get(field)
            LOGGER.warning(
                "schema lock violation: the %r edit on package version %r is refused "
                "(FR-PKG-03) — a rising rate means a caller is attempting something "
                "the design forbids", field, v,
            )
            raise SchemaLockViolation(
                f"the {field!r} edit on package version {v!r} is refused by the §6.2 "
                f"schema lock (FR-PKG-03): changing what is measured invalidates every "
                f"accumulated validation record."
                + (f" The HLD names the locked field {hld_name!r}." if hld_name else "")
                + f" The sanctioned vehicle is a new version (create_version(parent={v!r}))."
            )
        raise PublishedVersionImmutableError(
            f"package version {v!r} is published (locked = 1) and immutable (FR-PKG-01)."
        )

    def criteria(self, v: PackageVersionId, question_id: str | None = None) -> tuple:
        """The version's criteria, from the per-run cache; this is read for every one of about
        23,000 units (NFR-PKG-05)."""
        cached = self._cache_get(v)
        if question_id is None:
            return cached["criteria"]
        return tuple(c for c in cached["criteria"] if c["question_id"] == question_id)

    def bands(self, criterion_id: str) -> tuple:
        """The criterion's bands in ordinal order, from the per-run cache."""
        cached = self._cache_current()
        return cached["bands"].get(criterion_id, ())

    def _cache_get(self, v: PackageVersionId) -> dict:
        if self._cache_version != v or self._cache is None:
            self._cache = self._load_version(v)
            self._cache_version = v
        return self._cache

    def _cache_current(self) -> dict:
        """The cache, loaded for the file's latest version when no version has been read yet;
        `bands(criterion_id)` takes no version argument, so bands come from the current version."""
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
        """Clear the cache after a publish or any edit, so it never becomes a second source of
        truth (design §3.4)."""
        self._cache = None
        self._cache_version = None

    def _load_version(self, v: PackageVersionId) -> dict:
        criteria = []
        for r in self._handle.query(PKG_STATEMENTS["select_criteria"], v=v):
            row = dict(r)
            try:
                row["answer_key"] = (
                    tuple(json.loads(row["answer_key"])) if row["answer_key"] else ()
                )
            except (TypeError, ValueError) as error:
                # A malformed key must not poison the per-run cache loader with a raw
                # JSONDecodeError — CT-PKG-11: caller errors are this module's own.
                raise PackageError(
                    f"version {v!r} holds a malformed answer key for criterion "
                    f"{row['criterion_id']!r}: {error}"
                ) from error
            criteria.append(row)
        bands_by_criterion: dict[str, tuple] = {}
        for row in self._handle.query(PKG_STATEMENTS["select_bands"], v=v):
            bands_by_criterion.setdefault(row["criterion_id"], []).append(dict(row))
        bands = {c: tuple(rows) for c, rows in bands_by_criterion.items()}
        return {"criteria": tuple(criteria), "bands": bands}

    def _refuse_unknown_version(self, v: PackageVersionId) -> None:
        rows = self._handle.query(PKG_STATEMENTS["select_version"], v=v)
        if not rows:
            raise PackageError(
                f"package version {v!r} does not exist in this Tier P database."
            )

    def is_locked(self, v: PackageVersionId) -> bool:
        """Whether version `v` is published."""
        return bool(self._handle.query(
            PKG_STATEMENTS["select_version"], v=v)[0]["locked"])

    def lineage(self, v: PackageVersionId) -> tuple[PackageVersionId, ...]:
        """The version's ancestry, oldest first: the chain a grade is traced through."""
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
        """Raise before any statement touches a published version's rows (NFR-PKG-01)."""
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
