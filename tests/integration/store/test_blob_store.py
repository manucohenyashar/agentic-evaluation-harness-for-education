"""Content-addressed blobs: one hash, one copy, and nothing but the hash in the database.

Case `TC-STORE-09` (`FR-STORE-06`, P1), test plan §5.3. Issue #14 (TS-08); implemented by issue
**#12**.

Rung 2 — a real blob directory on a real filesystem. "Occupy one file on disk" is a claim about
the filesystem, and the only honest oracle for it is counting the files.

**Written ahead of implementation** (test plan §8.2). Registered under `#12 blob_store_stats`.

`TC-STORE-22` (property, §5.3) owns the round-trip and the input-validation half of
`FR-STORE-06`; this case owns deduplication, the exact digest, and the database's ignorance of
blob content. They are deliberately disjoint.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3

import pytest

from tests.support.store_api import blob_store_stats, open_store, statement
from tests.support.store_vocabulary import table_names

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = "#12"

#: The plan says "the same 3 MB PDF". Env-gated (`CLAUDE.md` seam 3): the size is what makes
#: this a realistic page raster rather than a toy, but a constrained box should be able to turn
#: it down without editing the case.
BLOB_MB = int(os.environ.get("HARNESS_TEST_BLOB_MB", "3"))
BLOB_BYTES = BLOB_MB * 1024 * 1024

_BLOB_DDL = "CREATE TABLE document_blob (id INTEGER PRIMARY KEY, content_hash TEXT NOT NULL, rel_path TEXT NOT NULL)"
_BLOB_INSERT = "INSERT INTO document_blob (content_hash, rel_path) VALUES (:content_hash, :rel_path)"


def _pdf_bytes(seed: int, size: int = BLOB_BYTES) -> bytes:
    """A deterministic byte string shaped like a PDF.

    Deterministic rather than random: §4.6 seeds every source of randomness so a failure is
    reproducible by hand, and a content-addressing case whose inputs change per run cannot
    report a stable expected digest.

    The `%PDF-` header and `%%EOF` trailer are real because `FR-STORE-06` names PDFs and a
    store that sniffs content would behave differently on arbitrary bytes than on the thing it
    will actually be handed.
    """
    header = b"%PDF-1.7\n"
    trailer = b"\n%%EOF\n"
    body_size = size - len(header) - len(trailer)
    # A repeating, seed-dependent pattern: incompressible enough to be a fair filesystem test,
    # cheap enough not to dominate the integration tier's budget.
    chunk = bytes((seed * 31 + index * 17) % 251 for index in range(4096))
    body = (chunk * (body_size // len(chunk) + 1))[:body_size]
    return header + body + trailer


def _files_on_disk(blob_root) -> list:
    return sorted(path for path in blob_root.rglob("*") if path.is_file())


def test_tc_store_09_identical_content_is_stored_once_and_the_database_holds_only_the_hash(
    tmp_data_dir,
):
    """`TC-STORE-09` — *"Identical writes return the same SHA-256 and occupy one file on disk;
    different content yields different hashes; only hash and relative path are stored in the
    database."*

    Oracle: **exact value plus on-disk file count**.

    Four claims:

    1. **The exact digest.** `put()` must return `hashlib.sha256(data).hexdigest()`, not merely
       *a* stable identifier. `CT-STORE-07` names SHA-256 specifically, and `M-INGEST` and
       `M-CONSOLE` resolve blobs by a hash they may have computed themselves.
    2. **One copy.** The second `put` of identical bytes must not add a file. Counted by
       walking the directory — the independent oracle — and *then* cross-checked against the
       module's own `blob_store_stats`, so a stats accessor that under-reports is caught by the
       walk rather than believed.
    3. **Different content, different hash, at equal length.** Equal length is the point: a
       length-keyed or mtime-keyed "content addressing" bug collides here and nowhere else.
    4. **The database never holds the bytes.** `FR-STORE-06` says "storing only the hash and
       relative path in the database". Asserted by scanning every value of every column of
       every table for a distinctive slice of the blob — a store that also stashed the content
       in a BLOB column satisfies every hash assertion above while doubling the footprint
       `NFR-STORE-06` bounds and putting student work in the tier that is *not* purged.
    """
    store = open_store(tmp_data_dir, issue=ISSUE)
    blobs = store.blobs()
    blob_root = tmp_data_dir / "blobs"

    original = _pdf_bytes(seed=1)
    expected_digest = hashlib.sha256(original).hexdigest()

    before = _files_on_disk(blob_root)
    first_hash = blobs.put(original)

    assert first_hash == expected_digest, (
        f"TC-STORE-09: put() returned {first_hash!r}, not the SHA-256 of the content "
        f"({expected_digest!r}). CT-STORE-07 names SHA-256, and consumers resolve blobs by a "
        "hash they may have computed themselves."
    )

    after_first = _files_on_disk(blob_root)
    assert len(after_first) == len(before) + 1, (
        f"TC-STORE-09: storing one blob created {len(after_first) - len(before)} files, not 1."
    )

    # (2) the same bytes again — same hash, no new file.
    second_hash = blobs.put(original)
    after_second = _files_on_disk(blob_root)

    assert second_hash == first_hash, (
        "TC-STORE-09: the same content produced two different hashes. CT-STORE-07: `put` is "
        "content-addressed on SHA-256 and idempotent."
    )
    assert after_second == after_first, (
        f"TC-STORE-09: re-storing identical content added a file. Deduplication on write is "
        f"FR-STORE-06's explicit requirement. Before: {len(after_first)} files, after: "
        f"{len(after_second)}: {[p.name for p in after_second]}"
    )

    stats = blob_store_stats(blobs, issue=ISSUE)
    assert stats["file_count"] == len(after_second), (
        f"TC-STORE-09: blob_store_stats reports {stats['file_count']} files, the directory "
        f"holds {len(after_second)}. The walk is the oracle; a stats accessor that disagrees "
        "with the filesystem is reporting on something other than the filesystem."
    )

    # (3) different content of the *same length*.
    other = _pdf_bytes(seed=2)
    assert len(other) == len(original), "the two fixtures must be equal length for this limb"
    assert other != original
    other_hash = blobs.put(other)
    assert other_hash != first_hash, (
        "TC-STORE-09: two different documents of equal length collided. A store keyed on "
        "length, mtime or a truncated digest passes every other assertion in this case."
    )
    assert other_hash == hashlib.sha256(other).hexdigest()
    assert len(_files_on_disk(blob_root)) == len(after_second) + 1, (
        "TC-STORE-09: distinct content did not produce a second file."
    )

    # (4) the database holds the hash and the path — never the bytes.
    handle = store.cohort("COH-BLOB")
    with handle.transaction() as tx:
        tx.execute(statement(_BLOB_DDL, issue=ISSUE))
        tx.execute(
            statement(_BLOB_INSERT, issue=ISSUE),
            content_hash=first_hash,
            rel_path=str(blobs.path(first_hash).relative_to(tmp_data_dir)),
        )

    cohort_path = tmp_data_dir / "cohorts" / "COH-BLOB.sqlite"
    needle = original[len(b"%PDF-1.7\n"): len(b"%PDF-1.7\n") + 512]
    offenders = _columns_containing(cohort_path, needle)
    assert not offenders, (
        "TC-STORE-09: blob content is stored in the database as well as on disk "
        f"({', '.join(offenders)}). FR-STORE-06 stores 'only the hash and relative path in the "
        "database'. Duplicating the bytes doubles the footprint NFR-STORE-06 bounds and puts "
        "verbatim student work somewhere purge does not reach."
    )


def _columns_containing(db_path, needle: bytes) -> list[str]:
    """Every `table.column` whose values contain `needle`, read independently."""
    found: list[str] = []
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        connection.text_factory = bytes
        for table in sorted(table_names(db_path)):
            if table.startswith("sqlite_"):
                continue
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
            for column in columns:
                for (value,) in connection.execute(f'SELECT "{column}" FROM "{table}"'):
                    if isinstance(value, (bytes, bytearray)) and needle in value:
                        found.append(f"{table}.{column}")
                        break
    return found
