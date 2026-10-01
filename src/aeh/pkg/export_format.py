"""The export archive format: entries with fixed metadata, the signature, snapshot statements."""

from __future__ import annotations

import hashlib
import hmac
import zipfile


#: The export archive format tag and version. Import refuses an unknown NEWER format
#: (the same forward-only rule the schema itself follows) and accepts older ones.
EXPORT_FORMAT_VERSION = 1


EXPORT_FORMAT_TAG = "aeh-package-export"


#: The signing key's environment knob (design §3.4's Configuration). Read at CALL time,
#: never at import — a test or a deployment sets it per operation, not per process
#: load. Optional by design (NFR-PKG-04): a school with no PKI still exports.
SIGNING_KEY_ENV = "HARNESS_PACKAGE_SIGNING_KEY"


#: A safe package id for import: the manifest's package_id becomes a FILENAME in the
#: receiving installation's packages directory, so an attacker-controlled archive must
#: not carry `..`, separators, or anything else that escapes it.
_SAFE_PACKAGE_ID = __import__("re").compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


#: The manifest/peek SQL the import runs against a RAW sqlite3 connection (an in-memory
#: copy of the archived database, before a single byte touches the target filesystem).
#: These never touch the store's handles, so they live outside PKG_STATEMENTS.
_PEEK_TABLES = "SELECT name FROM sqlite_master WHERE type = 'table'"


_PEEK_VERSIONS = "SELECT package_version_id FROM package_version"


_PEEK_SCHEMA_VERSION = "SELECT MAX(version) AS v FROM schema_version"


_PEEK_PACKAGES = "SELECT package_id FROM package"


#: The exported database travels in DELETE journal mode: a single-file artifact with no
#: -wal/-shm sidecars (they do not travel in the archive, and a WAL header cannot even be
#: inspected through an in-memory copy). The pragma checkpoints and rewrites the header.
_SNAPSHOT_JOURNAL_MODE = "PRAGMA journal_mode=DELETE"


#: #528: the export gate's outcomes are this installation's record of its own gate runs, not
#: part of the package; the exported copy carries none (an importer would otherwise read a
#: stale refusal), and is compacted so two exports of one package stay byte-identical.
_SNAPSHOT_CLEAR_GATE_OUTCOMES = "DELETE FROM export_gate_outcome"


_SNAPSHOT_VACUUM = "VACUUM"


def _zip_entry(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    """Write one archive entry with a fixed timestamp and owner-only permissions, so identical
    content gives an identical member listing (TC-REG-02) and the file is not world-readable. The
    manifest has no timestamp for the same reason."""
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, data)


def _signature_of(content_hash: str, key: str) -> str:
    """HMAC-SHA256 over the content hash (NFR-PKG-04): the hash fixes the database bytes, and the
    key identifies who produced them."""
    return hmac.new(key.encode("utf-8"), content_hash.encode("ascii"),
                    hashlib.sha256).hexdigest()
