"""`StoreLimits`: the environment-sensitive numbers, resolved once when the store opens."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .settings import (
    BUSY_RETRIES_ENV,
    BUSY_TIMEOUT_MS_ENV,
    CAPACITY_BUDGET_BYTES_ENV,
    COMMIT_BATCH_ENV,
    COMMIT_INTERVAL_MS_ENV,
    DEFAULT_BUSY_RETRIES,
    DEFAULT_BUSY_TIMEOUT_MS,
    DEFAULT_CAPACITY_BUDGET_BYTES,
    DEFAULT_COMMIT_BATCH,
    DEFAULT_COMMIT_INTERVAL_MS,
    DEFAULT_LEASE_RESTORE_MARGIN_S,
    DEFAULT_PROJECTED_RUN_BYTES,
    DEFAULT_QUEUE_DEPTH_SUSTAIN_MS,
    DEFAULT_STAGED_BLOB_TTL_S,
    DEFAULT_WRITE_QUEUE_DEPTH,
    DEFAULT_WRITER_POLL_MS,
    _int_env,
    LEASE_RESTORE_MARGIN_S_ENV,
    PROJECTED_RUN_BYTES_ENV,
    QUEUE_DEPTH_SUSTAIN_MS_ENV,
    STAGED_BLOB_TTL_S_ENV,
    WRITE_QUEUE_DEPTH_ENV,
    WRITER_POLL_MS_ENV,
)
from .errors import ConfigurationProblem


@dataclass(frozen=True)
class StoreLimits:
    """The environment-sensitive numbers, read once when the store opens.

    Resolved at construction, not per call, and that is a decision `TC-STORE-24` depends on:
    seam 3 says "production value is the default; the knob exists so a slower test box can
    adjust without a code change", which describes a value read when the process configures
    itself. A store that re-read `os.environ` on every enqueue would be promising live reload,
    which nothing requires and which makes the configured value unobservable.
    """

    commit_batch: int = DEFAULT_COMMIT_BATCH
    commit_interval_ms: int = DEFAULT_COMMIT_INTERVAL_MS
    write_queue_depth: int = DEFAULT_WRITE_QUEUE_DEPTH
    projected_run_bytes: int = DEFAULT_PROJECTED_RUN_BYTES
    queue_depth_sustain_ms: int = DEFAULT_QUEUE_DEPTH_SUSTAIN_MS
    writer_poll_ms: int = DEFAULT_WRITER_POLL_MS
    capacity_budget_bytes: int = DEFAULT_CAPACITY_BUDGET_BYTES
    lease_restore_margin_s: int = DEFAULT_LEASE_RESTORE_MARGIN_S
    staged_blob_ttl_s: int = DEFAULT_STAGED_BLOB_TTL_S
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS
    retries: int = DEFAULT_BUSY_RETRIES

    def __post_init__(self) -> None:
        """Refuse a knob value that makes no sense, rather than hang on it.

        `_int_env` rejects a negative, which leaves zero -- and zero is not a small value here,
        it is a different program. `commit_batch=0` makes every batch empty, so the writer spins
        forever committing nothing while the queue never shrinks; `write_queue_depth=0` makes
        `enqueue_write` block on its first call, since the depth is reached before anything is
        queued. Both are silent hangs from one mistyped environment variable, and seam 3 exists
        so a slower box can retune these -- retuning is when a typo happens.
        """
        for name, env, value in (
            ("commit_batch", COMMIT_BATCH_ENV, self.commit_batch),
            ("commit_interval_ms", COMMIT_INTERVAL_MS_ENV, self.commit_interval_ms),
            ("write_queue_depth", WRITE_QUEUE_DEPTH_ENV, self.write_queue_depth),
            ("writer_poll_ms", WRITER_POLL_MS_ENV, self.writer_poll_ms),
            ("capacity_budget_bytes", CAPACITY_BUDGET_BYTES_ENV, self.capacity_budget_bytes),
        ):
            if value <= 0:
                raise ConfigurationProblem(
                    f"{env} is {value}; it must be greater than zero. A {name} of zero does not "
                    "mean 'no limit' — it stalls the write queue with nothing to report."
                )

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> StoreLimits:
        return cls(
            commit_batch=_int_env(COMMIT_BATCH_ENV, DEFAULT_COMMIT_BATCH, environ),
            commit_interval_ms=_int_env(
                COMMIT_INTERVAL_MS_ENV, DEFAULT_COMMIT_INTERVAL_MS, environ),
            write_queue_depth=_int_env(
                WRITE_QUEUE_DEPTH_ENV, DEFAULT_WRITE_QUEUE_DEPTH, environ),
            projected_run_bytes=_int_env(
                PROJECTED_RUN_BYTES_ENV, DEFAULT_PROJECTED_RUN_BYTES, environ),
            queue_depth_sustain_ms=_int_env(
                QUEUE_DEPTH_SUSTAIN_MS_ENV, DEFAULT_QUEUE_DEPTH_SUSTAIN_MS, environ),
            writer_poll_ms=_int_env(WRITER_POLL_MS_ENV, DEFAULT_WRITER_POLL_MS, environ),
            capacity_budget_bytes=_int_env(
                CAPACITY_BUDGET_BYTES_ENV, DEFAULT_CAPACITY_BUDGET_BYTES, environ),
            lease_restore_margin_s=_int_env(
                LEASE_RESTORE_MARGIN_S_ENV, DEFAULT_LEASE_RESTORE_MARGIN_S, environ),
            staged_blob_ttl_s=_int_env(
                STAGED_BLOB_TTL_S_ENV, DEFAULT_STAGED_BLOB_TTL_S, environ),
            busy_timeout_ms=_int_env(BUSY_TIMEOUT_MS_ENV, DEFAULT_BUSY_TIMEOUT_MS, environ),
            retries=_int_env(BUSY_RETRIES_ENV, DEFAULT_BUSY_RETRIES, environ),
        )
