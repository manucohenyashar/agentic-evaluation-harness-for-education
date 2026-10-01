"""The provenance gate, and exporting and importing a package archive."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from aeh.store import Tier, current_schema_version

from .vocabulary import LOGGER, PackageVersionId
from .errors import ExportBlockedError, PackageError, SchemaTooNewError
from .export_format import (
    EXPORT_FORMAT_TAG,
    EXPORT_FORMAT_VERSION,
    _PEEK_PACKAGES,
    _PEEK_SCHEMA_VERSION,
    _PEEK_TABLES,
    _PEEK_VERSIONS,
    _SAFE_PACKAGE_ID,
    _signature_of,
    SIGNING_KEY_ENV,
    _SNAPSHOT_CLEAR_GATE_OUTCOMES,
    _SNAPSHOT_JOURNAL_MODE,
    _SNAPSHOT_VACUUM,
    _zip_entry,
)
from .records import ExportReport, ImportReport, ProvenanceEntry, ProvenanceReport
from .statements import PKG_STATEMENTS


class ExchangeMixin:
    """The provenance gate, export to a signed archive, and import from one."""

    def record_export_gate_outcome(
        self, v: PackageVersionId, outcome: str, *, actor: str | None = None,
        recorded_at: str | None = None,
    ) -> None:
        """Record the provenance gate's outcome for version `v` (FR-CONSOLE-23). Append-only; the
        latest row is the current outcome."""
        if not isinstance(outcome, str) or not outcome.strip():
            raise ValueError("an export gate outcome is a non-empty sentence")
        stamp = recorded_at or datetime.now(timezone.utc).isoformat()
        with self._handle.transaction() as tx:
            tx.execute(PKG_STATEMENTS["insert_export_gate_outcome"], v=v, outcome=outcome,
                       actor=actor, recorded_at=stamp)

    def export_gate_outcome(self, v: PackageVersionId) -> str | None:
        """The latest provenance-gate outcome for `v`, or None when the gate has never run for it
        (FR-CONSOLE-23)."""
        rows = self._handle.query(PKG_STATEMENTS["select_export_gate_outcome"], v=v)
        return str(rows[0]["outcome"]) if rows else None

    # -- export, import and the provenance gate (#31) -----------------------------------------

    def export_provenance_report(self, v: PackageVersionId) -> ProvenanceReport:
        """The export gate's state and every worked example still marked `real_verbatim`: the list
        the console's approval screen works from (FR-PKG-12, FR-CONSOLE-23). It covers the whole
        Tier P file, because that is what an export ships."""
        self._refuse_unknown_version(v)
        entries = tuple(
            ProvenanceEntry(
                exemplar_id=row["exemplar_id"],
                package_version_id=row["package_version_id"],
                criterion_id=row["criterion_id"],
                band=row["band"],
            ) for row in self._handle.query(
                PKG_STATEMENTS["select_real_verbatim_exemplars"])
        )
        flag = bool(self._handle.query(PKG_STATEMENTS["select_package_flag"],
                                       p=self._package_id)[0]["flag"])
        return ProvenanceReport(
            package_id=self._package_id,
            package_version_id=v,
            contains_real_student_text=flag,
            real_verbatim=entries,
        )

    def export(self, v: PackageVersionId, dest: Path) -> ExportReport:
        """Export the package as one self-contained archive: the Tier P database plus every blob
        its worked examples use (FR-PKG-10, CT-STORE-07), importable with no network and no shared
        filesystem (NFR-PKG-02).

        The gate first (`FR-PKG-11`): a 1 in the DERIVED
        `package.contains_real_student_text` column refuses with `ExportBlockedError`
        carrying the provenance report, because a caller may treat any exported package
        as free of verbatim student text (`CT-PKG-13`). The database is snapshotted
        through SQLite's backup API (a consistent copy even beside a live WAL), hashed,
        and — when `HARNESS_PACKAGE_SIGNING_KEY` is set — signed with HMAC-SHA256 over
        the hash (`NFR-PKG-04`)."""
        self._refuse_unknown_version(v)
        flag = bool(self._handle.query(PKG_STATEMENTS["select_package_flag"],
                                       p=self._package_id)[0]["flag"])
        if flag:
            report = self.export_provenance_report(v)
            raise ExportBlockedError(
                f"package {self._package_id!r} carries real student text "
                f"(`contains_real_student_text = 1`): export is refused until every "
                f"real_verbatim exemplar is paraphrased-and-approved or dropped "
                f"(FR-PKG-11). The report on this error lists them.",
                report,
            )
        blob_hashes = tuple(row["blob_hash"] for row in self._handle.query(
            PKG_STATEMENTS["select_exemplar_blob_hashes"]))
        blob_data: dict[str, bytes] = {}
        if blob_hashes:
            if self._blobs is None:
                raise PackageError(
                    "this catalog holds no blob store, so the exemplar-referenced "
                    "blobs cannot travel. Construct it with blobs=store.blobs() "
                    "(CT-STORE-07: the export must be self-contained)."
                )
            for blob_hash in blob_hashes:
                try:
                    blob_data[blob_hash] = self._blobs.get(blob_hash)
                except (KeyError, ValueError) as error:
                    raise PackageError(
                        f"exemplar references blob {blob_hash}, which the blob store "
                        f"does not hold: {error}. The export would not be "
                        "self-contained (FR-PKG-10); declare the exemplar's material "
                        "or drop the reference."
                    ) from error
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        db_path = self._handle._open_report.path  # noqa: SLF001 -- the module's own substrate
        with tempfile.TemporaryDirectory() as snapshot_dir:
            snapshot = Path(snapshot_dir) / "package.pkg.sqlite"
            source = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
            try:
                copy = sqlite3.connect(snapshot)
                try:
                    source.backup(copy)
                    copy.execute(_SNAPSHOT_CLEAR_GATE_OUTCOMES)
                    copy.commit()
                    copy.execute(_SNAPSHOT_VACUUM)
                    copy.execute(_SNAPSHOT_JOURNAL_MODE)
                    copy.commit()
                finally:
                    copy.close()
            finally:
                source.close()
            db_bytes = snapshot.read_bytes()
        content_hash = hashlib.sha256(db_bytes).hexdigest()
        key = os.environ.get(SIGNING_KEY_ENV)
        signed = key is not None
        provenance = tuple(row["provenance"] for row in self._handle.query(
            PKG_STATEMENTS["select_exemplar_provenance"], v=v))
        manifest = {
            "format": EXPORT_FORMAT_TAG,
            "format_version": EXPORT_FORMAT_VERSION,
            "package_id": self._package_id,
            "package_version_id": v,
            "schema_version": self._handle._open_report.schema_version_after,
            "content_hash": content_hash,
            "signature": _signature_of(content_hash, key) if signed else None,
            "blobs": list(blob_hashes),
            # FR-PKG-12: the exemplar provenance ACTUALLY exported travels in the
            # archive, so validated-with-real and exported-with-synthetic are
            # distinguishable on the receiving side, not only in the sender's log.
            "exemplar_provenance": list(provenance),
        }
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
            _zip_entry(archive, "manifest.json",
                       json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8"))
            _zip_entry(archive, "package.pkg.sqlite", db_bytes)
            for blob_hash in sorted(blob_data):
                _zip_entry(archive, f"blobs/{blob_hash}", blob_data[blob_hash])
        LOGGER.info(
            "exported package %s version %s provenance=%s dest=%s",
            self._package_id, v, list(provenance), dest,
        )
        return ExportReport(
            package_id=self._package_id,
            package_version_id=v,
            dest=str(dest),
            schema_version=manifest["schema_version"],
            content_hash=content_hash,
            signed=signed,
            blobs_included=blob_hashes,
            exemplar_provenance=provenance,
            bytes_written=dest.stat().st_size,
        )

    def import_file(self, src: Path) -> ImportReport:
        """Import one export archive, all or nothing (FR-PKG-10, FR-PKG-13, NFR-PKG-02,
        NFR-PKG-04).

        Every check runs against bytes in memory BEFORE anything is written: format
        tag, content hash (the archive is intact), schema version (a package newer than
        this binary refuses with `SchemaTooNewError` NAMING the required upgrade —
        a partial import of a newer package is worse than a refused one), signature
        (REPORTED — verified | unsigned | mismatched | unverifiable — never a silent
        accept and never a refusal; NFR-PKG-04), target collision, and the archived
        database's own integrity (it is a Tier P file, it carries the manifest's
        version and package, its schema version matches the manifest's claim).

        The signature (if any) is HMAC-SHA256 over the content hash under
        `HARNESS_PACKAGE_SIGNING_KEY`. The report returns the imported version id —
        the Protocol's `PackageVersionId` answer, carried on the report because
        NFR-PKG-04's report is mandatory and a bare id cannot hold it.

        The returned report describes the import; the imported file migrates to this
        binary's schema version on its first `store.package()` open, exactly as any
        older tier file does."""
        src = Path(src)
        try:
            archive_bytes = zipfile.ZipFile(src)
        except zipfile.BadZipFile as error:
            raise PackageError(
                f"{src} is not a readable zip archive: {error}. Nothing was imported."
            ) from error
        with archive_bytes as archive:
            try:
                manifest = json.loads(archive.read("manifest.json"))
            except KeyError as error:
                raise PackageError(
                    f"{src} carries no manifest.json; nothing was imported."
                ) from error
            if not isinstance(manifest, dict):
                raise PackageError(
                    f"the manifest in {src} is not a JSON object; nothing was imported."
                )
            for field in ("package_id", "package_version_id", "schema_version",
                          "content_hash"):
                if field not in manifest:
                    raise PackageError(
                        f"the manifest in {src} declares no {field!r}; nothing was "
                        "imported."
                    )
            if manifest.get("format") != EXPORT_FORMAT_TAG:
                raise PackageError(
                    f"{src} is not an AEH package export (format "
                    f"{manifest.get('format')!r})."
                )
            if manifest.get("format_version") != EXPORT_FORMAT_VERSION:
                raise PackageError(
                    f"the export format version {manifest.get('format_version')!r} is "
                    f"not {EXPORT_FORMAT_VERSION}; refusing an unknown format rather "
                    "than guessing at its contents."
                )
            db_bytes = archive.read("package.pkg.sqlite")
            content_hash = hashlib.sha256(db_bytes).hexdigest()
            if content_hash != manifest.get("content_hash"):
                raise PackageError(
                    f"the package in {src} does not match its content hash — the "
                    "archive is corrupt or was altered in transit; nothing was "
                    "imported."
                )
            current = current_schema_version(Tier.PACKAGE)
            file_schema = int(manifest["schema_version"])
            if file_schema > current:
                raise SchemaTooNewError(
                    f"the package in {src} was written by schema version "
                    f"{file_schema}; this binary provides {current}. Upgrade the "
                    f"binary to schema version {file_schema} or later — nothing was "
                    "imported (FR-PKG-13)."
                )
            signature = manifest.get("signature")
            key = os.environ.get(SIGNING_KEY_ENV)
            if signature is None:
                signature_status = "unsigned"
            elif key is None:
                signature_status = "unverifiable"
            elif not isinstance(signature, str):
                signature_status = "mismatched"
            else:
                expected = _signature_of(manifest["content_hash"], key)
                signature_status = ("verified" if hmac.compare_digest(signature, expected)
                                    else "mismatched")
            package_id = manifest["package_id"]
            if (not isinstance(package_id, str)
                    or not _SAFE_PACKAGE_ID.fullmatch(package_id)):
                raise PackageError(
                    f"the archive declares package id {package_id!r}, which is not a "
                    "safe package name; refusing it rather than writing outside the "
                    "packages directory."
                )
            target = self._handle._open_report.path.parent / f"{package_id}.pkg.sqlite"
            if target.exists():
                raise PackageError(
                    f"package {package_id!r} already exists in this installation; "
                    "importing would overwrite it — nothing was imported."
                )
            blob_data: dict[str, bytes] = {}
            for name in archive.namelist():
                if not name.startswith("blobs/"):
                    continue
                blob_hash = name.split("/", 1)[1]
                data = archive.read(name)
                if hashlib.sha256(data).hexdigest() != blob_hash:
                    raise PackageError(
                        f"blob {blob_hash} does not match its content hash; the "
                        "archive is corrupt — nothing was imported."
                    )
                blob_data[blob_hash] = data
            # Integrity peek on an IN-MEMORY copy: the archive's database must be a
            # Tier P file carrying the manifest's package and version, at the manifest's
            # schema version. Nothing has touched the target filesystem yet.
            peek = sqlite3.connect(":memory:")
            try:
                peek.deserialize(db_bytes)
                tables = {row[0] for row in peek.execute(_PEEK_TABLES)}
                if not {"package", "package_version", "schema_version"} <= tables:
                    raise PackageError(
                        f"the database in {src} is not a Tier P package file; nothing "
                        "was imported."
                    )
                in_file_schema = peek.execute(_PEEK_SCHEMA_VERSION).fetchone()[0]
                if in_file_schema != file_schema:
                    raise PackageError(
                        f"the archived database is at schema version "
                        f"{in_file_schema}, but its manifest claims {file_schema}; "
                        "nothing was imported."
                    )
                if package_id not in {
                    row[0] for row in peek.execute(_PEEK_PACKAGES)
                }:
                    raise PackageError(
                        f"the archived database does not carry package "
                        f"{package_id!r}; nothing was imported."
                    )
                if manifest["package_version_id"] not in {
                    row[0] for row in peek.execute(_PEEK_VERSIONS)
                }:
                    raise PackageError(
                        f"the manifest's version does not exist in the archived "
                        "database; nothing was imported."
                    )
            finally:
                peek.close()
            if blob_data and self._blobs is None:
                raise PackageError(
                    f"the archive carries {len(blob_data)} blob(s) its exemplars "
                    "reference, but this catalog holds no blob store. Importing would "
                    "silently drop them — a partial import (CT-PKG-14). Construct the "
                    "catalog with blobs=store.blobs()."
                )
            staging = target.parent / f".import-{uuid.uuid4().hex}.tmp"
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                staging.write_bytes(db_bytes)
                for blob_hash, data in blob_data.items():
                    self._blobs.put(data)
                os.replace(staging, target)
            finally:
                if staging.exists():
                    staging.unlink()
            # The flag is NOT re-derived here: it travels with the rows it derives
            # from, under the content hash this import just verified — re-writing it
            # would break the byte-level round-trip the archive guarantees, and any
            # tampering with either half already failed the hash check. The catalog's
            # own write path re-derives it on every exemplar write (ADR-4, TC-PKG-24);
            # files older than the column migrate on first open.
        report = ImportReport(
            package_version_id=manifest["package_version_id"],
            package_id=package_id,
            schema_version=file_schema,
            signature_status=signature_status,
            blobs_imported=len(blob_data),
            src=str(src),
        )
        LOGGER.info(
            "imported package %s version %s provenance=%s signature=%s src=%s",
            package_id, report.package_version_id, manifest.get("exemplar_provenance"),
            signature_status, src,
        )
        return report
