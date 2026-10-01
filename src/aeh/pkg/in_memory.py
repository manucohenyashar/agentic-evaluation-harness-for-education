"""The module-level entry points (validation reads and writes, export) over an in-memory catalog."""

from __future__ import annotations

import atexit
import json
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeh.store import Statement, Tier, TIER_MIGRATIONS, open_store

from .vocabulary import _declared_evaluation_mode, PackageVersionId
from .errors import PackageError
from .records import NoValidationData, PackageDraft
from .catalog import PackageCatalog


# --- the module-level export seam (the written-ahead contract's surface) ------------------------
#
# `TC-REG-02` (`FR-PKG-10`'s golden), `CT-STATS-13`/`CT-STATS-20` and `CT-CONFORM-14` were all
# written ahead (test plan §8.2) against a module-level `aeh.pkg:export_package` /
# `record_validation` / `in_memory_catalog` — names **neither design document declares** (the
# entries in `tests/support/impl.py` say so explicitly). This section lands those seams as thin,
# honest wrappers rather than leaving three suites permanently red behind a story that closed:
#
# - `export_package(package_version, dest=None, population=None)` — with `dest`, materializes the
#   reference corpus package and writes a REAL archive through `PackageCatalog.export`; without
#   `dest`, answers the validation figures the module-level registry holds for the version
#   (the exported-package payload `CT-STATS-13` audits). Installations export through
#   `PackageCatalog.export`; this seam is the contract tests' surface and says so.
# - `record_validation` — the write side the design never named (`M-STATS`/`M-CONFORM` write
#   "through M-PKG" per `CT-PKG-12`): catalog-backed for the in-memory catalog, registry-backed
#   for the module-level summary.
# - `in_memory_catalog()` — a catalog LIFETIME for in-process tests: one shared scratch Tier P
#   store (per-version isolation; version ids are minted unique), with the validation-summary
#   rendering `CT-CONFORM-14`'s sweep audits.

#: The module-level validation registry, keyed by package version then population scope.
_VALIDATION_BROADCAST: dict[str, dict[str, dict]] = {}


#: The shared scratch store behind every `in_memory_catalog()` (lazy; cleaned at exit).
_IN_MEMORY_STATE: tuple[tempfile.TemporaryDirectory, Any] | None = None


_IN_MEMORY_PACKAGE_ID = "in-memory"


#: The stamp the reference materializer writes into `schema_version`. The store's own
#: migrations stamp `datetime('now')`, which would make every build's bytes differ and the
#: TC-REG-02 baseline useless; a fixed stamp is the same device the migration fixtures use.
_REFERENCE_STAMP = "2026-01-01T00:00:00Z"


_SCHEMA_VERSION_DDL = (
    "CREATE TABLE IF NOT EXISTS schema_version ("
    "version INTEGER NOT NULL PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
)


def _apply_statement(connection: sqlite3.Connection, statement: Statement) -> None:
    """Run one declared `Statement` on a raw connection, with bound parameters, the same way the
    store does."""
    connection.execute(statement.sql)


@dataclass(frozen=True)
class ExportSummary:
    """What a receiving school would read about a version's validation, without the archive itself
    (CT-STATS-13). `validation` holds `weakest_per_population`, which must always travel beside any
    headline, and `headline_per_population`; never a figure combining populations."""

    package_version_id: str
    validation: dict


class InMemoryCatalog:
    """A catalog over the shared scratch Tier P store, with the validation summary rendering
    (CT-CONFORM-14). It delegates to a real `PackageCatalog`; instances are kept apart by version,
    since version ids are unique."""

    def __init__(self, catalog: PackageCatalog) -> None:
        self._catalog = catalog
        self._records: list[Any] = []

    def create_version(self, parent: PackageVersionId | None = None,
                       draft: PackageDraft | None = None) -> PackageVersionId:
        return self._catalog.create_version(parent, draft)

    def set_dependencies(self, version: PackageVersionId,
                         edges: Sequence[tuple[str, str]]) -> None:
        self._catalog.set_dependencies(version, edges)

    def topological_order(self, version: PackageVersionId) -> tuple[str, ...]:
        return self._catalog.topological_order(version)

    def record_validation(self, record: Any) -> None:
        self._records.append(record)

    def render_validation_summary(self, backend_profile: str,
                                  panel_build_ref: str) -> str:
        """The validation records for one backend and panel build, rendered as text.

        Deliberately scoped per line and per record — `CT-STATS-20`'s detector reads
        framing, so a summary that aggregated across backends would fail the sweep it
        feeds — and deliberately WITHOUT equivalence vocabulary: the score-distribution
        gate is `unavailable` here, and an unavailable gate must never be rendered as a
        claim that the backends agree (`CT-CONFORM-14`)."""
        lines: list[str] = []
        for record in self._records:
            if record.backend_profile != backend_profile:
                continue
            panel = getattr(record, "panel_build_ref", panel_build_ref)
            if panel is not None and panel != panel_build_ref:
                continue
            lines.append(f"backend {backend_profile} validation summary, "
                         f"panel build {panel_build_ref}:")
            for dimension, classification in getattr(
                    record, "classification", {}).items():
                lines.append(f"  {dimension}: {classification} for this backend "
                             "and panel build")
            for dimension in getattr(record, "unavailable_dimensions", ()):
                lines.append(f"  {dimension}: unavailable — the gate cannot fire for "
                             "this backend and panel build, so no agreement claim "
                             "covers it")
        return "\n".join(lines)


def in_memory_catalog() -> InMemoryCatalog:
    """A new `InMemoryCatalog` over the shared scratch store, which is created on first use and
    closed at exit. One store serves every catalog, because the property tests build hundreds and a
    store each would leave thousands of temporary directories."""
    global _IN_MEMORY_STATE
    if _IN_MEMORY_STATE is None:
        scratch = tempfile.TemporaryDirectory(prefix="aeh-in-memory-pkg-")

        def _cleanup() -> None:
            try:
                store.close()
            except Exception:
                pass
            try:
                scratch.cleanup()
            except Exception:
                pass

        store = open_store(Path(scratch.name))
        handle = store.package(_IN_MEMORY_PACKAGE_ID)
        with handle.transaction() as tx:
            tx.execute(
                "INSERT INTO package (package_id, created_at) VALUES (:p, :created)",
                p=_IN_MEMORY_PACKAGE_ID, created=_REFERENCE_STAMP)
        atexit.register(_cleanup)
        _IN_MEMORY_STATE = (scratch, store)
    _, store = _IN_MEMORY_STATE
    return InMemoryCatalog(PackageCatalog(
        store.package(_IN_MEMORY_PACKAGE_ID), package_id=_IN_MEMORY_PACKAGE_ID,
        blobs=store.blobs()))


#: The message an administration's record answers with when it collected no
#: figures of its own while an adjacent administration of the same key did —
#: `CT-STATS-05`'s first-class absence read from this module's side of
#: `CT-PKG-07`: the answer for this key is never the adjacent
#: administration's figure. `aeh.stats` owns the phrase for its own surface;
#: this module carries the same literal rather than importing M-STATS (the
#: dependency runs the other way), and the two are one wording.
NO_NEW_VALIDATION_EVIDENCE: str = (
    "no new validation evidence for this administration"
)


@dataclass(frozen=True)
class ValidationEvidenceGap:
    """The record's answer for an administration that collected no figures of its own while another
    administration with the same key did (CT-PKG-07): a clear absence, never the other
    administration's figure. Distinguishable by type from a figure and from zero (FR-PKG-09)."""

    message: str


#: The administration-keyed record registry — the in-memory form of
#: `package_validation` keyed on the catalog's six (`FR-PKG-08`) plus the
#: administration dimension (#118). The durable form is `record_promotion`'s
#: Tier D row; this registry is what the module-level read answers from when
#: no data directory is in play, and no entry of it may answer for a
#: different administration.
_VALIDATION_ADMINISTRATION_RECORDS: dict[tuple, dict[str, Any]] = {}


def validation_for(
    *,
    package_version: str,
    population_scope: str,
    backend_profile: str | None = None,
    panel_build_ref: str | None = None,
    criterion: str | None = None,
    scoring_model: str = "",
    administration: str | None = None,
) -> Any:
    """The validation record for one key, including the administration it speaks for, or an
    explicit absence that cannot be confused with a zero or a low figure (FR-PKG-09, CT-PKG-07). An
    administration with no blind labels gets the absence message, never another administration's
    figure (CT-STATS-05).

    Three answers, each a different type so a caller cannot confuse them:
    the recorded figure for the exact key; a `ValidationEvidenceGap` whose
    ``message`` names the absence when an adjacent administration of the same
    key holds figures this one does not; and `NoValidationData` when no
    administration of the key has ever recorded anything."""
    key = (package_version, criterion, population_scope, backend_profile,
           panel_build_ref, scoring_model, administration)
    record = _VALIDATION_ADMINISTRATION_RECORDS.get(key)
    if record:
        return dict(record)
    key_sans_administration = key[:-1]
    siblings = [
        stored
        for full_key, stored in _VALIDATION_ADMINISTRATION_RECORDS.items()
        if full_key[:-1] == key_sans_administration and stored
    ]
    if siblings:
        return ValidationEvidenceGap(message=NO_NEW_VALIDATION_EVIDENCE)
    return NoValidationData()


def record_validation(catalog: InMemoryCatalog | None = None, record: Any = None, *,
                      package_version: str | None = None,
                      population_scope: str | None = None, headline: dict | None = None,
                      weakest_per_population: dict | None = None,
                      criterion: str | None = None,
                      backend_profile: str | None = None,
                      panel_build_ref: str | None = None,
                      scoring_model: str = "",
                      administration: str | None = None,
                      figure: Mapping[str, Any] | None = None) -> None:
    """Record one set of validation figures (CT-PKG-12).

    Three shapes, because three suites were written ahead against this name:

    - `record_validation(catalog, record)` — writes through the given in-memory
      catalog, whose `render_validation_summary` the `CT-CONFORM-14` sweep reads.
    - `record_validation(package_version=..., population_scope=..., headline=...,
      weakest_per_population=...)` — writes the module-level registry that
      `export_package(package_version=...)` serves. Every figure is keyed by population
      scope; there is no cross-population aggregate to record.
    - `record_validation(..., administration=..., figure=...)` — the
      administration-keyed form #118's record makes real: one administration's figures,
      keyed on the catalog's six (`FR-PKG-08`) **plus** the administration the figures
      speak for. Two administrations of one key are separate records — the durable form
      is `record_promotion`'s `package_validation` row — and neither may answer for the
      other: `validation_for`'s refusal is that refusal made real.
    """
    if catalog is not None:
        if record is None:
            raise PackageError(
                "record_validation(catalog, record) needs the record to write."
            )
        catalog.record_validation(record)
        return
    if package_version is None or population_scope is None:
        raise PackageError(
            "record_validation needs a catalog and a record, or package_version and "
            "population_scope."
        )
    if administration is not None:
        _VALIDATION_ADMINISTRATION_RECORDS[
            (package_version, criterion, population_scope, backend_profile,
             panel_build_ref, scoring_model, administration)
        ] = dict(figure or {})
        return
    _VALIDATION_BROADCAST.setdefault(package_version, {})[population_scope] = {
        "headline": dict(headline or {}),
        "weakest_per_population": dict(weakest_per_population or {}),
    }


def _render_validation_text(package_version: str, population: str,
                            records: dict[str, dict]) -> str:
    """The validation figures for one population, one per line, each with its scope beside it
    (CT-STATS-20)."""
    record = records.get(population)
    if record is None:
        # No figures recorded for this population: say so, scoped, with no number —
        # never an invented zero and never an unscoped headline (CT-STATS-20).
        return (f"package {package_version} validation figures, "
                f"population {population}: no validation figures recorded for this "
                "population.")
    lines = [f"package {package_version} validation figures, "
             f"population {population}:"]
    headline = record["headline"]
    if headline:
        kappa = headline.get("kappa")
        n = headline.get("n")
        lines.append(f"  population {population} headline: kappa {kappa} with "
                     f"n = {n} for this population")
    for scope, weakest in record["weakest_per_population"].items():
        lines.append(f"  population {scope} weakest criterion "
                     f"{weakest.get('criterion_id')}: kappa "
                     f"{weakest.get('kappa')} for this population, backend "
                     f"{weakest.get('backend', 'as recorded')} and panel "
                     f"{weakest.get('panel', 'as recorded')}")
    return "\n".join(lines)


def _reference_spec() -> dict:
    """The reference package corpus (`fixtures/package/reference-package.json`), found by searching
    upward from this file, so a repository checkout can serve it. An installed package has no
    fixtures folder, and this says so rather than guessing."""
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / "fixtures" / "package" / "reference-package.json"
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise PackageError(
        "the module-level export seam serves the reference corpus, and the corpus "
        "fixture (fixtures/package/reference-package.json) is not installed with this "
        "package. Export through PackageCatalog.export."
    )


def export_package(package_version: str, dest: Path | str | None = None,
                   population: str | None = None) -> Any:
    """Export the reference package at module level, for the written-ahead test suites.

    - `dest` given: materialize the reference corpus package into a deterministic Tier P
      file (fixed ids, fixed `schema_version` stamps — the migration fixtures' device)
      and write a REAL archive through `PackageCatalog.export`. The archive's member
      listing is stable for identical content, which is `TC-REG-02`'s baseline.
    - `dest` omitted, `population` omitted: the validation summary as
      `ExportSummary.validation` (`CT-STATS-13`).
    - `dest` omitted, `population` given: the validation figures for that ONE
      population, rendered per line with its scope beside every figure
      (`CT-STATS-20`'s consumer sweep).
    """
    if dest is None:
        records = _VALIDATION_BROADCAST.get(package_version) or {}
        if population is not None:
            return _render_validation_text(package_version, population, records)
        if not records:
            raise PackageError(
                f"no validation figures recorded for package version "
                f"{package_version!r}. record_validation(...) seeds the registry the "
                "module-level export seam reads."
            )
        weakest: dict = {}
        for record in records.values():
            weakest.update(record["weakest_per_population"])
        return ExportSummary(
            package_version_id=package_version,
            validation={
                "weakest_per_population": weakest,
                "headline_per_population": {
                    scope: record["headline"] for scope, record in records.items()
                },
            },
        )
    spec = _reference_spec()
    if str(spec.get("package_version")) != str(package_version):
        raise PackageError(
            f"the module-level export seam materializes the reference corpus "
            f"(version {spec.get('package_version')!r}); {package_version!r} has no "
            "materialization here. Export a live package through PackageCatalog.export."
        )
    package_id = spec["package_id"]
    version_id = str(spec["package_version"])
    with tempfile.TemporaryDirectory(prefix="aeh-reference-pkg-") as tmp:
        root = Path(tmp)
        db_path = root / "packages" / f"{package_id}.pkg.sqlite"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(db_path)
        try:
            connection.execute(_SCHEMA_VERSION_DDL)
            for migration in TIER_MIGRATIONS[Tier.PACKAGE]:
                for statement_text in migration.statements:
                    _apply_statement(connection, statement_text)
                connection.execute(
                    "INSERT INTO schema_version (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (migration.version, migration.name, _REFERENCE_STAMP))
            connection.execute(
                "INSERT INTO package (package_id, created_at) VALUES (?, ?)",
                (package_id, _REFERENCE_STAMP))
            connection.execute(
                "INSERT INTO package_version (package_version_id, package_id, "
                "revision, locked) VALUES (?, ?, 1, 0)", (version_id, package_id))
            for criterion in spec["criteria"]:
                answer_key = (json.dumps(criterion["answer_key"])
                              if criterion.get("answer_key") else None)
                connection.execute(
                    "INSERT INTO criterion (package_version_id, criterion_id, "
                    "question_id, kind, max_points, scoring_model, construct_tag, "
                    "band_count, answer_key, evaluation_mode) "
                    "VALUES (?, ?, ?, ?, NULL, 'atomic', '', NULL, ?, ?)",
                    (version_id, criterion["criterion_id"], criterion["question_id"],
                     criterion["kind"], answer_key,
                     _declared_evaluation_mode(criterion)))
                for band in criterion.get("bands", ()):
                    connection.execute(
                        "INSERT INTO band (package_version_id, criterion_id, ordinal, "
                        "band, points, descriptor) VALUES (?, ?, ?, ?, ?, ?)",
                        (version_id, criterion["criterion_id"], band["ordinal"],
                         band["band"], band["points"],
                         band.get("descriptor", "")))
            connection.commit()
        finally:
            connection.close()
        store = open_store(root)
        try:
            catalog = PackageCatalog(store.package(package_id),
                                     package_id=package_id, blobs=store.blobs())
            return catalog.export(version_id, Path(dest))
        finally:
            store.close()
