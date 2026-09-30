"""Small reads of the run ledger and the package that the evaluator's parts share."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import DeterministicError


def _declared_mode(criterion: Any) -> str:
    """One criterion row's declared evaluation mode (`FR-PKG-22`, `FR-ORCH-35`).

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
    """The one wall-clock read the audit trail writes, UTC ISO-8601 — the same
    form `ingest._now` and `orch._now` use, so every recorded_at in the store
    reads the same way."""
    return datetime.now(timezone.utc).isoformat()


def _newest_run(runs: list[Any]) -> Any:
    """The cohort's newest run — latest non-null `started_at`, then `run_id` —
    the run a re-derivation attributes its audit rows to: the one whose grades
    the correction supersedes."""
    return max(runs, key=lambda row: (row["started_at"] or "", row["run_id"]))


def _cohort_keys_on_filesystem(store: Any) -> tuple[str, ...]:
    """The default cohort-key discovery, same layout the orchestrator walks:
    one `cohorts/<cohort_id>.sqlite` file per administration (§3.3). A store
    that lays the tier out differently injects its own key function."""
    data_dir = getattr(store, "data_dir", None)
    if data_dir is None:
        raise DeterministicError(
            "finding a run by id walks the store's cohort ledger files, which "
            "needs the store's data directory; this store exposes no `data_dir`. "
            "Inject a cohort_keys_for function."
        )
    return tuple(path.stem for path in Path(data_dir, "cohorts").glob("*.sqlite"))
