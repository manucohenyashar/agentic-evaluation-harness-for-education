"""Removing a cohort that never held student work (the console's "Delete this class").

`SqliteStore.purge_cohort` deletes a cohort's Tier C and R content only after its evidence is
promoted to Tier D (FR-STORE-07, CT-STORE-10). A cohort with no submission and no run — a class
made by mistake, its list typed and nothing else — has nothing to promote, so the purge refused
it forever and the file stayed listed. This removes such a cohort outright and refuses any
other, naming the purge as its way out: evidence is never discarded this way.

A module function, not a Store member: the Store's public surface is the five contract members
(`TC-STORE-C01`); this is store-internal housekeeping over a store it is handed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import PurgePreconditionError, ReadOnlyTierError
from .interfaces import Tier
from .purge import _DISCARD_WORK_COUNTS
from .security import _validated_component


def discard_empty_cohort(store: Any, cohort_id: str) -> None:
    """Remove `cohort_id`'s file if it holds no paper and no run; refuse otherwise (nothing is
    removed). The cohort's cached handle is closed first, as `purge_cohort` does: on Windows an
    open connection is a file that cannot be removed."""
    cohort_id = _validated_component("cohort id", cohort_id)
    if getattr(store, "_read_only", False):
        raise ReadOnlyTierError(
            f"discard_empty_cohort was called on a read-only store for cohort {cohort_id!r}.")
    path = Path(store.cohort_path(cohort_id))
    if not path.exists():
        raise PurgePreconditionError(f"no cohort {cohort_id!r} is stored; nothing was removed.")
    handle = store.cohort(cohort_id)
    held = [what for what, statement in _DISCARD_WORK_COUNTS.items()
            if handle.query(statement)[0][0]]
    if held:
        raise PurgePreconditionError(
            f"cohort {cohort_id!r} holds {' and '.join(held)}, so it is purged only after its "
            "evidence is promoted (purge_cohort); nothing was removed.")
    handles = store._handles  # noqa: SLF001 -- the store package's own housekeeping
    cached = handles.get((Tier.COHORT, cohort_id, False))
    if cached is not None:
        cached._close()  # noqa: SLF001 -- flush queued writes; a failure propagates
        handles.pop((Tier.COHORT, cohort_id, False), None)
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


__all__ = ["discard_empty_cohort"]
