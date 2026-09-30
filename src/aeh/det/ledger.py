"""Small reads of the run ledger and the package that the evaluator's parts share."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import DeterministicError


def _declared_mode(criterion: Any) -> str:
    """The evaluation mode a criterion row declares (FR-PKG-22, FR-ORCH-35).

    A row read through this module's own statements always carries the column; the shape
    fallback covers only the in-memory doubles that predate it. `kind` is not a test any
    consumer may make — the equivalence it stood for was retired when the column shipped.
    """
    try:
        declared = criterion["evaluation_mode"]
    except (KeyError, IndexError, TypeError):
        declared = getattr(criterion, "evaluation_mode", None)
    if declared:
        return str(declared)
    try:
        kind = criterion["kind"]
    except (KeyError, IndexError, TypeError):
        kind = getattr(criterion, "kind", None)
    return "deterministic" if kind == "mcq" else "judged"


def _now() -> str:
    """The current time in UTC, ISO-8601: the one clock read the audit trail writes, in the same
    format M-INGEST and M-ORCH use."""
    return datetime.now(timezone.utc).isoformat()


def _newest_run(runs: list[Any]) -> Any:
    """The cohort's newest run (latest `started_at`, then `run_id`). A re-derivation attributes its
    audit rows to this run, whose grades the correction replaces."""
    return max(runs, key=lambda row: (row["started_at"] or "", row["run_id"]))


def _cohort_keys_on_filesystem(store: Any) -> tuple[str, ...]:
    """The cohort ids found on disk, one `cohorts/<cohort_id>.sqlite` file per administration
    (design §3.3). A store with a different layout passes its own function."""
    data_dir = getattr(store, "data_dir", None)
    if data_dir is None:
        raise DeterministicError(
            "finding a run by id walks the store's cohort ledger files, which "
            "needs the store's data directory; this store exposes no `data_dir`. "
            "Inject a cohort_keys_for function."
        )
    return tuple(path.stem for path in Path(data_dir, "cohorts").glob("*.sqlite"))
