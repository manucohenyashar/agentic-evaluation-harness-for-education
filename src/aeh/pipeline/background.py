"""The console's doors: record uploads, and start or resume runs on worker threads."""

from __future__ import annotations

from typing import Any, Mapping

from aeh.orch import Orchestrator

from .driver import run_to_completion
from .runtime import _open_store, _provider_for


# --- completion hooks -----------------------------------------------------------------------


def record_upload(store: Any, cohort_id: str, filename: str, blob_ref: str) -> None:
    """The console's door to M-INGEST's upload record (FR-CONSOLE-27, #531): the console's
    declared seams include this module, not `aeh.ingest` (TC-CONSOLE-36). No SQL here."""
    from aeh.ingest import record_upload_part

    record_upload_part(store, cohort_id, filename, blob_ref)


def uploaded_parts(store: Any, cohort_id: str) -> tuple[str, ...]:
    """The cohort's uploaded parts in assembled order, from M-INGEST (FR-CONSOLE-27, #531)."""
    from aeh.ingest import upload_parts_in_order

    return upload_parts_in_order(store, cohort_id)


class RunAlreadyStartedError(ValueError):
    """`start_run_in_background` asked to start a run that already left `pending`.
    A repeated "start run" (a double-click, a second tab) is refused rather than
    re-driven: the first request's worker owns the run (`FR-CONSOLE-02`)."""


def start_run_in_background(
    store: Any,
    *,
    cohort_id: str,
    package_version_id: str,
    config: Mapping[str, Any],
    run_id: str | None = None,
    thread_name: str = "aeh-run",
    provider: Any = None,
    allow_running: bool = False,
    **drive_keywords: Any,
) -> tuple[str, Any]:
    """The console's "start run" door (`FR-CONSOLE-34`, `NFR-CONSOLE-08`, #398).

    Synchronously, on the caller's store: resolve the run configuration exactly as
    `aeh run` does, then create the run, or reuse a `pending` run for the same cohort and
    package version (or the one `run_id` names). A run that already left `pending`
    raises `RunAlreadyStartedError` and nothing is written.

    Then return at once, with the run driven on a **server-owned worker thread** that
    opens its own store at the same data directory (SQLite connections belong to their
    thread): `start` if still pending, then `run_to_completion`. A failure inside the
    worker is recorded on the run as its pause reason (`Orchestrator.record_pause_reason`),
    never swallowed. Closing the browser does not stop the worker, and killing the server
    leaves the run resumable by `recover` (`NFR-CONSOLE-03`).

    `provider` and `drive_keywords` pass through to `run_to_completion` (a replay against
    a recorded corpus supplies its refs this way); by default the provider is the one the
    resolved profile names, as `aeh run` builds it.

    Returns `(run_id, thread)`. The thread is a daemon: a server that exits does not wait
    on it, and `recover` is what continues an interrupted run."""
    import threading

    from aeh.conf import resolve_run_config

    orchestrator = Orchestrator(store)
    run_config = resolve_run_config(dict(config), orchestrator.cohort_ref(cohort_id))
    if run_id is None:
        existing = [
            handle for handle in orchestrator.runs()
            if handle.cohort_id == cohort_id and handle.package_version_id == package_version_id
        ]
        pending = [handle for handle in existing if handle.status == "pending"]
        if pending:
            run_id = max(pending, key=lambda h: (h.started_at or "", h.run_id)).run_id
        elif existing:
            latest = max(existing, key=lambda h: (h.started_at or "", h.run_id))
            raise RunAlreadyStartedError(
                f"run {latest.run_id} for cohort {cohort_id!r} and package version "
                f"{package_version_id!r} is already {latest.status}; nothing was started"
            )
        else:
            run_id = orchestrator.create_run(cohort_id, package_version_id, run_config)
    else:
        status = orchestrator.run_handle(run_id).status
        if status != "pending" and not (allow_running and status == "running"):
            raise RunAlreadyStartedError(
                f"run {run_id} is already {status}; nothing was started")
    data_dir = getattr(store, "data_dir", None)
    if data_dir is None:
        raise ValueError("start_run_in_background needs a store with a data_dir")
    started = run_id

    def _drive() -> None:
        worker_store = _open_store(data_dir)
        try:
            worker = Orchestrator(worker_store)
            try:
                if worker.run_handle(started).status == "pending":
                    worker.start(started)
                run_to_completion(
                    worker_store, started,
                    provider=provider if provider is not None else _provider_for(run_config),
                    run_config=run_config, **drive_keywords)
            except Exception as error:  # noqa: BLE001 - recorded on the run, not swallowed
                # Pause naming the cause; a run `pause` will not move (still pending, say)
                # gets the cause recorded on its row instead, so the operator reads why.
                try:
                    worker.pause(started, cause=error)
                except Exception:  # noqa: BLE001
                    try:
                        worker.record_pause_reason(started, error)
                    except Exception:  # noqa: BLE001 - a run that cannot record stays for recover
                        pass
        finally:
            worker_store.close()

    thread = threading.Thread(target=_drive, name=f"{thread_name}-{started}", daemon=True)
    thread.start()
    return started, thread


def resume_runs_in_background(
    store: Any, *, config: Mapping[str, Any], provider: Any = None, **drive_keywords: Any,
) -> list[tuple[str, Any]]:
    """After a restart, drive every `running` run again on its own worker thread
    (`NFR-CONSOLE-08`, #398). Call it after `recover`, which reclaims the dead
    process's leases: `recover` resets state, and this is what makes the run finish.

    A run whose frozen backend profile differs from this process's is skipped. `recover`
    has already recorded why it stays where it is (`FR-CONF-15`). Returns the
    `(run_id, thread)` pairs it started."""
    from aeh.conf import resolve_run_config

    orchestrator = Orchestrator(store)
    started: list[tuple[str, Any]] = []
    for handle in orchestrator.runs(statuses=("running",)):
        try:
            resolved = resolve_run_config(dict(config), orchestrator.cohort_ref(handle.cohort_id))
        except Exception:  # noqa: BLE001 - an unresolvable profile leaves the run for recover
            continue
        if handle.backend_profile and resolved.backend_profile != handle.backend_profile:
            continue
        started.append(start_run_in_background(
            store, cohort_id=handle.cohort_id, package_version_id=handle.package_version_id,
            config=config, run_id=handle.run_id, provider=provider, allow_running=True,
            **drive_keywords))
    return started
