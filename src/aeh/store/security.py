"""Owner-only permissions on store files, and refusing world-writable locations."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable

from .settings import OWNER_ONLY_DIR, OWNER_ONLY_FILE
from .errors import ConfigurationProblem, InsecureLocationError


# --- location and permission hardening (FR-STORE-09, CT-STORE-16) -----------------------------


def _harden_files(path: Path) -> None:
    """`OWNER_ONLY_FILE` on a database file and its `-wal`/`-shm` siblings.

    Called on the writable open path once the file certainly exists (`_open_tier`) and after
    purge's `VACUUM` (which rewrites the file and re-creates the siblings). POSIX-honoured;
    on Windows `os.chmod` maps everything but the read-only attribute, so this is a no-op
    there by the platform's own semantics — stated plainly rather than papered over: on
    Windows the owner-only guarantee comes from the directory ACLs the operator's profile
    creates, not from these bits.
    """
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if candidate.exists():
            os.chmod(candidate, OWNER_ONLY_FILE)


def _harden_dir(path: Path) -> None:
    """`OWNER_ONLY_DIR` on a directory this module just created or manages.

    Applied after `mkdir` because `mkdir`'s mode argument is filtered through the process
    umask — see `OWNER_ONLY_DIR`. Windows: no-op, as `_harden_files` documents.
    """
    os.chmod(path, OWNER_ONLY_DIR)


def _insecure_location_reason(
    path: Path, *, os_name: str | None = None, stat_fn: Callable[[Path], os.stat_result] | None = None
) -> str | None:
    """Why `path` is an insecure location for student data, or `None` if it is not.

    The rule `FR-STORE-09` states and `CT-STORE-16` makes contract: refuse a data directory
    that **resolves inside a world-writable temporary path**. Mechanically:

    - **Resolve first.** `os.path.realpath` follows the whole symlink chain, so a data
      directory that is a symlink pointing into `/tmp` is judged by where it *lands* — the
      bypass a naive prefix check on the configured path misses, and the exact case
      `TC-STORE-C16` names.
    - **Walk the ancestors.** The first directory from the resolved path up to the root whose
      POSIX mode is world-writable (`mode & 0o002`) is the reason — `/tmp` at `1777` is the
      canonical hit, and any world-writable ancestor is the same disclosure: files created
      beneath it are reachable by every other account on the host. A directory that is only
      group-writable is **not** refused; `TC-STORE-10`'s expected result names world-writable
      and temp, and a check that refused group-write would red the correct case.
    - **POSIX only.** On Windows the check returns `None` by design, not by omission: `os.stat`
      fabricates `0o777` for every directory there, so a bit test would refuse *every* data
      directory, and `%TEMP%` is ACL-scoped to the user, so the requirement's precondition —
      a world-writable temporary path — is unconstructible. Known residual limits, stated
      rather than hidden: an UNC share is writable across machines by nature, and a FAT/exFAT
      volume has no ACLs at all; neither is detectable through `os.stat` and neither is
      refused here. `NFR-STORE-05`'s platform-encryption placement is the compensating
      deployment control.

    `os_name` and `stat_fn` are injectable so both branches are exercisable from one host —
    this repository's suite runs on Windows only, and a refusal path nothing can run is a
    refusal path nobody can trust. `TC-STORE-10` drives them directly.
    """
    platform = os.name if os_name is None else os_name
    stat = os.stat if stat_fn is None else stat_fn
    if platform != "posix":
        return None
    resolved = Path(os.path.realpath(path))
    for candidate in (resolved, *resolved.parents):
        try:
            mode = stat(candidate).st_mode
        except OSError:
            # An ancestor that cannot be stat'ed is not evidence of a world-writable one —
            # and the data directory itself may legitimately not exist yet (`open_store`
            # creates it after this check, which is what keeps the refusal create-nothing).
            continue
        if mode & 0o002:
            return f"{candidate} is world-writable (mode {mode & 0o777:03o})"
    return None


def _refuse_insecure_location(data_dir: Path) -> None:
    """Raise `InsecureLocationError` for a world-writable location, before anything is created."""
    reason = _insecure_location_reason(data_dir)
    if reason is not None:
        raise InsecureLocationError(
            f"{data_dir} is not a safe data directory: {reason}. FR-STORE-09 refuses to put "
            "student work where every other account on the host can reach it — Tier C is the "
            "largest PII surface in the system, and a world-writable location is the one "
            "place the permission control cannot follow it. Nothing was created. Choose a "
            "directory outside the world-writable tree (e.g. under the operator's home)."
        )


#: What an identifier may look like when it becomes a filename component or a key. Anything
#: else — path separators, `..`, a leading dash, an absolute path — is refused at the
#: operations where the value reaches the filesystem: `purge_cohort` deletes whatever file
#: `cohort_path(cohort_id)` resolves to, so an unvalidated id is a traversal away from
#: irreversibly purging the wrong cohort's file. Review verified the traversal both ways
#: (`../cohorts/other` and an absolute path resetting the join). Keyed lookups pass the id
#: to SQLite as a bound parameter and never reach a filename, so they need no rule.
_SAFE_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


def _validated_component(kind: str, value: str) -> str:
    """Refuse an identifier that cannot safely become a filename (`FR-STORE-09`'s posture).

    `TC-STORE-22` fixes the principle for the blob store's accessors — input validation at
    the operation that could leave the data directory — and purge is the operation where
    the blast radius is irreversible.
    """
    if not isinstance(value, str) or not _SAFE_ID.match(value):
        raise ConfigurationProblem(
            f"{kind} {value!r} is not a safe identifier. It becomes a filename component, "
            f"so path separators, '..' and non-identifier characters are refused: a "
            f"destructive operation must not resolve outside the data directory."
        )
    return value
