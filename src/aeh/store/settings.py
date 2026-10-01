"""The data directory and the store's environment-sensitive numbers, each with its knob."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from .errors import ConfigurationProblem


# --- configuration ---------------------------------------------------------------------------

#: §3.3: *"no configuration beyond a data directory path"* (`NFR-STORE-03`).
DATA_DIR_ENV = "HARNESS_DATA_DIR"


#: How long SQLite waits for a lock before raising `SQLITE_BUSY`, and how many times this module
#: retries after that. Both are environment-sensitive: WAL plus a single writer should make busy
#: impossible (§3.3), but a slow or networked filesystem makes "should" into "usually", and a
#: constant calibrated for a developer SSD becomes a phantom failure everywhere else.
BUSY_TIMEOUT_MS_ENV = "HARNESS_SQLITE_BUSY_TIMEOUT_MS"


BUSY_RETRIES_ENV = "HARNESS_SQLITE_BUSY_RETRIES"


DEFAULT_BUSY_TIMEOUT_MS = 5_000


DEFAULT_BUSY_RETRIES = 4


#: §3.3 Configuration, with §3.3's own values as the defaults. `FR-STORE-04` calls 100/5000 an
#: Assumption and `FR-STORE-05` calls 1,000 one, which is exactly what makes them knobs rather
#: than literals: the mechanism is fixed, the numbers are calibrated per environment
#: (`CLAUDE.md` seam 3, "production value is the default").
COMMIT_BATCH_ENV = "HARNESS_COMMIT_BATCH"


COMMIT_INTERVAL_MS_ENV = "HARNESS_COMMIT_INTERVAL_MS"


WRITE_QUEUE_DEPTH_ENV = "HARNESS_WRITE_QUEUE_DEPTH"


DEFAULT_COMMIT_BATCH = 100


DEFAULT_COMMIT_INTERVAL_MS = 5_000


DEFAULT_WRITE_QUEUE_DEPTH = 1_000


#: The free-disk alert's other input (§3.3 **Alerts**: "free disk below the projected remaining-run
#: requirement"). `M-ORCH` knows what a run will still write; this module cannot, so the figure is
#: supplied rather than guessed. Zero — the default — means "no projection stated", and an alert
#: with no projection behind it must stay quiet rather than invent a threshold.
PROJECTED_RUN_BYTES_ENV = "HARNESS_PROJECTED_RUN_BYTES"


DEFAULT_PROJECTED_RUN_BYTES = 0


#: How long queue depth must stay at or above the backpressure threshold before the *alert*
#: fires. §3.3 says "queue depth **sustained** above the backpressure threshold", and the word is
#: load-bearing: backpressure at the boundary is normal operation and `CT-STORE-06` tells
#: `M-ORCH` to treat it as a throttle signal, not a fault. An alert that fired on the same edge
#: would page an operator for the system working as designed.
QUEUE_DEPTH_SUSTAIN_MS_ENV = "HARNESS_QUEUE_DEPTH_SUSTAIN_MS"


DEFAULT_QUEUE_DEPTH_SUSTAIN_MS = 5_000


#: How long the writer sleeps between checks when it has nothing due. Bounds how late a
#: time-triggered commit can be, so it is environment-sensitive in the same way the interval is.
WRITER_POLL_MS_ENV = "HARNESS_WRITER_POLL_MS"


DEFAULT_WRITER_POLL_MS = 5


#: `NFR-STORE-06`: *"a 350-student run shall occupy under 500 MB including blobs"*, which §3.3
#: records as an Assumption ("the HLD estimates tens of megabytes for rows; page rasters and crops
#: dominate"). A knob rather than a literal, because #12's own technical note asks for "a measured,
#: knob-adjustable expectation rather than a hard-coded literal" — a cohort of 800 or a school that
#: rasterises at 600 dpi is a different number, and re-deriving it must not need a code change.
CAPACITY_BUDGET_BYTES_ENV = "HARNESS_CAPACITY_BUDGET_BYTES"


DEFAULT_CAPACITY_BUDGET_BYTES = 500 * 1024 * 1024


#: How far the restored lease counter is pushed past the last expiry it recorded, so a lease
#: issued in the instant before an uncontrolled kill cannot come back live on a rounding edge.
#: Seconds; environment-sensitive because it trades reclaim latency against that edge.
LEASE_RESTORE_MARGIN_S_ENV = "HARNESS_LEASE_RESTORE_MARGIN_S"


DEFAULT_LEASE_RESTORE_MARGIN_S = 1


#: How old a staging file must be before an opening store reaps it. Generous by default, because
#: the thing it must never do is delete a blob another process is writing this second.
STAGED_BLOB_TTL_S_ENV = "HARNESS_STAGED_BLOB_TTL_S"


DEFAULT_STAGED_BLOB_TTL_S = 3600


#: The two alerts §3.3 names under **Alerts**, spelled once. `CT-STORE-17` makes their semantics
#: contract, so the names are part of the interface rather than log text.
ALERT_FREE_DISK = "free_disk_below_projection"


ALERT_QUEUE_DEPTH = "queue_depth_sustained"


DECLARED_ALERTS: tuple[str, ...] = (ALERT_FREE_DISK, ALERT_QUEUE_DEPTH)


#: Owner-only, on **each directory this module itself creates** — not on their parents, and not
#: at all on Windows, where `mkdir`'s mode argument and `chmod`'s mode bits are ignored for
#: anything but the read-only attribute. `FR-STORE-09`'s other half — refusing a world-writable
#: location with `InsecureLocationError` — is `_refuse_insecure_location`, called by
#: `open_store` before the first directory is created.
#:
#: An explicit `chmod` after `mkdir` is the part that actually holds on POSIX: `mkdir`'s mode
#: argument is subject to the process umask, so `mode=0o700` can silently create `0o750`. A
#: permission that depends on an umask nobody audited is not `CT-STORE-16`'s owner-only, it is
#: owner-only on a good day.
OWNER_ONLY_DIR = 0o700


#: Owner-only for the **files**: the database files this module creates and the `-wal`/`-shm`
#: siblings SQLite keeps beside them. The WAL holds the same student rows the database does, so
#: a world-readable `-wal` is the same disclosure with a different extension — `0o600` on the
#: database alone would lock the front door and leave the side one unlatched.
OWNER_ONLY_FILE = 0o600


#: The exit code `DiskFullError` halts with (`FR-STORE-10`). Not an environment knob — an
#: operator script matching on an exit code is a deployment concern, and no environment-sensitive
#: calibration is involved. 70 is sysexits' `EX_SOFTWARE`, chosen so a disk-full halt is
#: distinguishable in a shell transcript from a generic crash.
DISK_FULL_EXIT_CODE = 70


def _int_env(name: str, default: int, environ: Mapping[str, str] | None = None) -> int:
    source = os.environ if environ is None else environ
    raw = source.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationProblem(f"{name}={raw!r} is not an integer") from exc
    if value < 0:
        raise ConfigurationProblem(f"{name}={value} must not be negative")
    return value


def data_dir_from_environment(environ: Mapping[str, str] | None = None) -> Path:
    """The data directory from `HARNESS_DATA_DIR`, or a refusal naming that variable.

    No default path. A store that silently picked one would put student work somewhere the
    operator did not choose, and Tier C is the largest PII surface in the system (§3.3 security).
    """
    source = os.environ if environ is None else environ
    raw = source.get(DATA_DIR_ENV)
    if raw is None or not raw.strip():
        raise ConfigurationProblem(
            f"{DATA_DIR_ENV} is unset. NFR-STORE-03 requires no configuration beyond a data "
            f"directory path — but it does require that one."
        )
    return Path(raw).expanduser()
