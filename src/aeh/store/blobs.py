"""The content-addressed blob store: blobs keyed by the SHA-256 of their content."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

from .settings import OWNER_ONLY_DIR, OWNER_ONLY_FILE
from .errors import InvalidContentHashError
from .disk_full import _halt_if_disk_full


#: What a `content_hash` must look like: exactly 64 lowercase hex characters, anchored.
#:
#: Anchored, and lowercase-only. `re.match` without `$` would accept
#: `"a"*64 + "/../../etc/passwd"`, and `hexdigest()` returns lowercase -- so accepting uppercase
#: would mean two spellings of one blob, which is a second copy of the file the whole module
#: exists to store once. `TC-STORE-22` generates mixed case as a rejection input for exactly that
#: reason.
BLOB_HASH_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")


#: Where an in-progress blob is written before it is renamed into place. **Outside `blobs/`**, and
#: that is not tidiness: `TC-STORE-09` counts every file under the blob root and asserts that
#: storing one blob created exactly one file, so a temp file that lived there -- or was left there
#: by a crash -- would fail a correct store.
INCOMING_DIR = ".incoming"


class ContentAddressedBlobStore:
    """Blobs keyed by the SHA-256 of their content (`FR-STORE-06`, `CT-STORE-07`).

    **Content-addressed means idempotent for free.** `put` computes the digest, and the digest
    *is* the location, so storing the same bytes twice writes to the same path and the second
    write is skipped rather than deduplicated afterwards by a comparison. There is no index to
    fall out of step with the directory, which is also why `stats()` walks.

    **Two-level fan-out**, `blobs/<aa>/<bb>/<hash>`. A 350-student run's page rasters and crops
    run to tens of thousands of files (`NFR-STORE-06`), and tens of thousands of entries in one
    directory is where `readdir` and most filesystem tools start to degrade. The path is derived
    from the hash alone, so it is reproducible from the content and nothing needs to record it.

    **Written to a temp file and renamed.** A crash partway through a 3 MB page raster would
    otherwise leave a truncated file *at its own content address* -- the one state this design
    cannot detect, since the address no longer describes the bytes. `os.replace` is atomic within
    a filesystem, and the temp lives under the data directory rather than the system temp so it
    is on that same filesystem (and outside a world-writable path, `FR-STORE-09`).
    """

    __slots__ = ("_incoming", "_root")

    def __init__(self, root: Path, incoming: Path) -> None:
        self._root = root
        self._incoming = incoming

    # -- the three members §3.3 declares --------------------------------------------------------

    def put(self, data: bytes) -> str:
        """Store `data`, returning its SHA-256 hex digest. Idempotent (`CT-STORE-07`)."""
        if isinstance(data, (bytearray, memoryview)):
            data = bytes(data)
        if not isinstance(data, bytes):
            raise InvalidContentHashError(
                f"put() takes bytes, got {type(data).__name__}. A blob is the source PDF, the "
                "page raster or the crop; encoding is the caller's decision, not this module's."
            )
        content_hash = hashlib.sha256(data).hexdigest()
        target = self._path_for(content_hash)
        if target.exists():
            # FR-STORE-06's "deduplicate identical content on write". Not an optimisation: this
            # is what makes `put` idempotent, and rewriting would also mean a window in which an
            # existing, valid blob is replaced by a partial one.
            return content_hash
        target.parent.mkdir(parents=True, exist_ok=True, mode=OWNER_ONLY_DIR)
        self._incoming.mkdir(parents=True, exist_ok=True, mode=OWNER_ONLY_DIR)
        staged = self._incoming / f"{content_hash}.{secrets.token_hex(8)}"
        try:
            try:
                staged.write_bytes(data)
            except BaseException as error:
                # The blob door is a write door like any other (`FR-STORE-10` names no
                # exemption, and a page raster is student data on the same disk the run is
                # about to lose): out-of-space here classifies and halts like the queue,
                # transaction and purge doors, rather than surfacing a retryable-looking
                # OSError from a process that kept going.
                _halt_if_disk_full(error)
                raise
            try:
                staged.chmod(OWNER_ONLY_FILE)
            except OSError:
                pass  # Windows ignores the mode; #13 owns the full FR-STORE-09 rule
            try:
                os.replace(staged, target)
            except OSError:
                # Two threads storing the same bytes both passed the `exists()` check above and
                # both staged a copy; on Windows the loser's `os.replace` hits an open or newly
                # created target and raises `PermissionError` (measured: 2 of 16 racing puts, and
                # again with a reader holding the target open, since CPython's `open()` does not
                # pass FILE_SHARE_DELETE). POSIX would not raise at all.
                #
                # Losing the race is not a failure here, and content addressing is why: whatever
                # is at the target has the same SHA-256, so it has the same bytes. `put` is
                # documented as idempotent without qualification, so it must not raise for the
                # one case where idempotency is doing its job.
                if not target.exists():
                    _halt_if_disk_full(error)
                    raise
        finally:
            # A failed write must not leave the staging file behind: `TC-STORE-09` counts every
            # file under the data directory's blob root, and an operator counting disk usage
            # would be reading a number that includes rubbish.
            if staged.exists():
                staged.unlink()
        return content_hash

    def get(self, content_hash: str) -> bytes:
        """The bytes `put` stored under `content_hash`."""
        path = self.path(content_hash)
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            raise KeyError(
                f"no blob stored under {content_hash}. `put` returns the hash it stored; a hash "
                "that is well-formed but absent means the blob belongs to a different data "
                "directory, or to a cohort that has been purged."
            ) from error

    def path(self, content_hash: str) -> Path:
        """Where the blob with this hash lives on disk. The hash is checked before the filesystem
        is touched.

        `SEC-09` attacks this with a crafted hash, and the order of the two lines below is the
        defence: the pattern is checked first, so `../`, an absolute path and a wrong length are
        all rejected without the operating system ever being asked to resolve them. The
        containment assertion after it is belt and braces against a future change to the layout
        -- 64 hex characters cannot escape `_root`, and the day the fan-out changes is the day
        that stops being obvious.
        """
        self._validate(content_hash)
        resolved = self._path_for(content_hash)
        root = self._root.resolve()
        if not resolved.resolve().is_relative_to(root):
            raise InvalidContentHashError(
                f"{content_hash} resolves outside the blob directory ({resolved}). This cannot "
                "happen for 64 hex characters and is asserted anyway: FR-STORE-09 requires "
                "resolution to stay inside the data directory, and SEC-09 attacks exactly here."
            )
        return resolved

    def delete(self, content_hash: str) -> bool:
        """Remove the blob stored under this hash; True when a file was removed.

        Purge's reclamation door. The caller owns the sharing decision — the store is
        content-addressed with no refcount table, so "does anyone else still reference
        this hash" is a question about the databases that carry hashes, not about this
        directory, and `purge_cohort` answers it before calling here. What this method
        owns is the same door discipline as `path` and `get`: the hash is validated before
        the filesystem is touched and containment is asserted. The unlink targets a file
        under `blobs/`, which is by construction complete — a write stages in `incoming/`
        and renames into place — so there is no partial-write window to protect, and the
        two-level fan-out directories are left in place: `stats()` counts files, and a
        fan-out leaf is not one.
        """
        target = self.path(content_hash)  # validates, then asserts containment
        try:
            target.unlink()
        except FileNotFoundError:
            return False
        return True

    # -- accounting -------------------------------------------------------------------------------

    def reap_staged(self, older_than_s: float) -> int:
        """Delete staging files left behind by a crash between writing a blob and moving it into
        place.

        Bounded by age rather than unconditional: a data directory can legitimately have a second
        process staging a blob right now, and deleting its file mid-write would turn one crash
        into two. `older_than_s` is a knob for that reason.

        `stats()` walks `blobs/` and never saw these, but `store_metrics`'s `data_dir_bytes`
        counts every file under the data directory — and that is the number `NFR-STORE-06`'s
        500 MB is measured against, so an orphan inflates the one figure the Assumption is
        revisited from.
        """
        if not self._incoming.is_dir():
            return 0
        cutoff = time.time() - older_than_s
        reaped = 0
        for entry in self._incoming.iterdir():
            try:
                if entry.is_file() and entry.stat().st_mtime < cutoff:
                    entry.unlink()
                    reaped += 1
            except OSError:
                pass  # in use by another process, or already gone: both mean leave it alone
        return reaped

    def stats(self) -> dict[str, Any]:
        """File count and bytes on disk, found by walking the directory.

        A walk rather than a counter this module maintains. `TC-STORE-09` cross-checks this
        against its own walk and says why: *"a stats accessor that disagrees with the filesystem
        is reporting on something other than the filesystem"*. A maintained counter has to be
        right across every restart, every purge and every crash; a walk cannot drift because
        there is nothing to drift from.
        """
        file_count = 0
        bytes_on_disk = 0
        for entry in self._root.rglob("*"):
            if entry.is_file():
                file_count += 1
                bytes_on_disk += entry.stat().st_size
        return {
            "file_count": file_count,
            "bytes_on_disk": bytes_on_disk,
            "root": self._root,
        }

    # -- internals ----------------------------------------------------------------------------------

    @staticmethod
    def _validate(content_hash: Any) -> None:
        if not isinstance(content_hash, str) or not BLOB_HASH_PATTERN.match(content_hash):
            raise InvalidContentHashError(
                f"{content_hash!r} is not a content hash. `put` returns 64 lowercase hex "
                "characters (SHA-256, CT-STORE-07); anything else was not produced by this "
                "store and is refused before the filesystem is touched (TC-STORE-22, SEC-09)."
            )

    def _path_for(self, content_hash: str) -> Path:
        return self._root / content_hash[:2] / content_hash[2:4] / content_hash


# --- observability -------------------------------------------------------------------------------


def blob_store_stats(blobs: ContentAddressedBlobStore) -> dict[str, Any]:
    """`file_count` and `bytes_on_disk` for a blob directory, by walking it.

    A function rather than a `BlobStore` member for the reason `store_metrics` is one:
    `CT-STORE-07` fixes that protocol at `put` / `get` / `path`, and `TC-STORE-C07` asserts the
    surface. Accounting is not one of the three.
    """
    return blobs.stats()
