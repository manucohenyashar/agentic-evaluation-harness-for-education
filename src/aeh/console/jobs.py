"""The console-initiated work registry (`ADR-47`, FR-CONSOLE-52): console memory, not pipeline state.

A job is one piece of work the console itself started — today a grading run (whose record
mirrors the run row; the run is the pipeline's own state and this only *reads* it), and from
#760 the authoring jobs whose state is this registry alone. The registry holds no pipeline
state and writes no store row (`ADR-47`: jobs are console memory): a console restart drops
the finished-job history, which is the specified behaviour — the work's real state is
wherever the work itself lives (the run row, the draft files), never in this dict.

Every job record carries exactly the field set `CT-CONSOLE-37` pins, so the SPA renders one
shape whatever the job's kind. The key naming follows the module discipline of the read
surface: no payload here names a value `band`, `confidence` or `scoring_engine` (ADV-15).
"""

from __future__ import annotations

import threading
from typing import Any


#: The closed state set `CT-CONSOLE-37` pins. Adding a value is additive (`CT-CONSOLE-38`):
#: the SPA maps an unknown one to its neutral "needs attention" label rather than erroring.
JOB_STATES: tuple[str, ...] = ("queued", "running", "succeeded", "failed", "cancelled")


def job_record(
    *,
    job_id: str,
    kind: str,
    state: str,
    done: int | None = None,
    total: int | None = None,
    current: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    cost_usd: float | None = None,
    error_detail: str | None = None,
    error_next_action: str | None = None,
) -> dict[str, Any]:
    """One job record in `CT-CONSOLE-37`'s shape, exactly: the identity fields, the progress
    triple, the two stamps, the cost where it is known (`None` is "not known yet", never a
    fabricated zero — `CT-PROV-03`'s rule for cost figures), and the error pair. A job with
    no error answers `error.detail` of `None`; the SPA renders no error block from it."""
    return {
        "job_id": str(job_id),
        "kind": str(kind),
        "state": str(state),
        "progress": {"done": done, "total": total, "current": current},
        "started_at": started_at,
        "finished_at": finished_at,
        "cost_usd": cost_usd,
        "error": {"detail": error_detail, "next_action": error_next_action},
    }


class JobsRegistry:
    """The console's in-memory registry of the jobs it started (`ADR-47`).

    Thread-safe: the server answers every request on its own thread, and the thread that
    registers a job is never the one that polls it. Reads answer copies, so a caller holding
    a record cannot mutate the registry's view of the world."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def register(
        self, *, job_id: str, kind: str, total: int | None = None, current: str | None = None,
        started_at: str | None = None,
    ) -> dict[str, Any]:
        """Declare a new job, `queued`. A re-register of a live id is refused — two pieces of
        work answering to one id would let a poller read the wrong one's progress."""
        with self._lock:
            if job_id in self._jobs:
                raise ValueError(f"a job named {job_id!r} is already registered.")
            record = job_record(
                job_id=job_id, kind=kind, state="queued", total=total, current=current,
                started_at=started_at,
            )
            self._jobs[job_id] = record
            return dict(record)

    def update(
        self, job_id: str, *, state: str | None = None, done: int | None = None,
        total: int | None = None, current: str | None = None, cost_usd: float | None = None,
    ) -> dict[str, Any] | None:
        """Move a live job forward. Only the fields the caller names change; an unknown id
        answers `None` (the job is gone — a console restart dropped it — and the caller
        re-registers rather than resurrecting a stale row)."""
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return None
            if state is not None:
                record["state"] = str(state)
            progress = record["progress"]
            if done is not None:
                progress["done"] = int(done)
            if total is not None:
                progress["total"] = int(total)
            if current is not None:
                progress["current"] = str(current)
            if cost_usd is not None:
                record["cost_usd"] = float(cost_usd)
            return dict(record)

    def finish(
        self, job_id: str, *, state: str, finished_at: str | None = None,
        cost_usd: float | None = None, error_detail: str | None = None,
        error_next_action: str | None = None,
    ) -> dict[str, Any] | None:
        """Settle a job into one of the terminal states. A terminal job keeps its record —
        the finished history is what the jobs page shows — until the console process ends."""
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return None
            record["state"] = str(state)
            record["finished_at"] = finished_at
            if cost_usd is not None:
                record["cost_usd"] = float(cost_usd)
            record["error"] = {
                "detail": error_detail, "next_action": error_next_action,
            }
            return dict(record)

    def get(self, job_id: str) -> dict[str, Any] | None:
        """One job's record, or `None` when the registry holds none under that id."""
        with self._lock:
            record = self._jobs.get(job_id)
            return dict(record) if record is not None else None

    def all(self) -> list[dict[str, Any]]:
        """Every registered job's record, oldest first (registration order is the order the
        console started the work in)."""
        with self._lock:
            return [dict(record) for record in self._jobs.values()]


#: The run states the run row's CHECK domain admits, mapped onto the job states (`ADR-47`:
#: a run job mirrors the run row). `paused` reads as `running` — the job is the work, and a
#: paused run is work mid-flight, not finished work; the run's own status is what the SPA
#: renders beside it. A state outside the map means the ledger grew a new one, which the
#: additive rule (`CT-CONSOLE-38`) expects the SPA to treat as needs-attention — the mirror
#: answers it as `queued`, the least-wrong neutral state, rather than inventing one.
RUN_STATE_TO_JOB_STATE: dict[str, str] = {
    "pending": "queued",
    "running": "running",
    "paused": "running",
    "complete": "succeeded",
    "failed": "failed",
}
