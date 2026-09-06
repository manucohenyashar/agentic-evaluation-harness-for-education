"""The store refuses an insecure data directory and creates its files owner-only.

Cases `TC-STORE-10` (`FR-STORE-09`, P0, security) and `RES-02`, test plan §5.3 and §6.8.
Issue #15 (TS-09).

Rung 2 — real filesystem where the platform can express the requirement, and the check's
**injectable seams** where it cannot. This suite runs on Windows only, and the platform facts
are stated in the store's own decision table: `os.stat` fabricates `0o777` for every Windows
directory, so a mode-bit test would refuse *everything*, and `%TEMP%` is ACL-scoped per user,
so a world-writable temporary path is unconstructible there. The refusal is therefore driven
through `_insecure_location_reason`'s `os_name`/`stat_fn` parameters — POSIX semantics,
exercised from this host — and the exact-mode half of the oracle is `skipif`-gated to POSIX,
where the modes are real. The `chmod`-was-called half runs everywhere.

`Written ahead of implementation: yes` is stale — the check landed with #13; the case runs
green by design.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

import aeh.store as store_module
from aeh.store import InsecureLocationError, _insecure_location_reason, open_store
from tests.support.store_api import open_store as api_open_store

pytestmark = [pytest.mark.integration]

ISSUE = "#15"


def _posix_stat(mode: int):
    """A `stat` stand-in that reports `mode` for every path — the synthetic ancestor."""

    def _stat(path):
        return os.stat_result((mode, 0, 0, 0, 0, 0, 0, 0, 0, 0))

    return _stat


class _TestStatMode:
    """The four inputs `TC-STORE-10` names, expressed through the check's own seams."""

    @staticmethod
    def normal_path() -> str | None:
        return _insecure_location_reason(
            Path("Z:/operator-data/cohorts"), os_name="posix",
            stat_fn=_posix_stat(0o40750))

    @staticmethod
    def inside_system_temp() -> str | None:
        # /tmp at 1777: the canonical world-writable temporary path, refused whether the hit
        # is the temp root or any ancestor.
        return _insecure_location_reason(
            Path("/tmp/pytest-of-operator/data"), os_name="posix",
            stat_fn=lambda p: os.stat_result(
                (0o40700 if p.name == "data" else 0o41777, 0, 0, 0, 0, 0, 0, 0, 0, 0)))

    @staticmethod
    def world_writable_directory() -> str | None:
        return _insecure_location_reason(
            Path("/srv/share/data"), os_name="posix",
            stat_fn=lambda p: os.stat_result((0o40777, 0, 0, 0, 0, 0, 0, 0, 0, 0)))

    @staticmethod
    def group_writable_directory() -> str | None:
        return _insecure_location_reason(
            Path("/srv/team/data"), os_name="posix",
            stat_fn=lambda p: os.stat_result((0o40770, 0, 0, 0, 0, 0, 0, 0, 0, 0)))


def test_tc_store_10_the_refusal_partition_is_exact():
    """`TC-STORE-10` — *"Files and blob directory created owner-only; `InsecureLocationError`
    for the world-writable and temp cases."*

    Oracle: **exact partition**. Refused: a path inside the system temp directory, and a path
    under a world-writable directory. Not refused: a normal path (0750) and — the negative
    control — a group-writable directory (0770), which the requirement does not name and a
    stricter check would red on every legitimate shared-mount deployment."""
    assert _TestStatMode.inside_system_temp() is not None
    assert _TestStatMode.world_writable_directory() is not None
    assert _TestStatMode.normal_path() is None
    assert _TestStatMode.group_writable_directory() is None, (
        "TC-STORE-10: a group-writable directory was refused. The requirement names "
        "*world-writable*; refusing group-write reds every shared-mount deployment and is "
        "one the first M-STORE commit switches off — the same failure the name-vocabulary "
        "rule documented for over-broad patterns."
    )


def test_tc_store_10_open_store_refuses_and_creates_nothing(tmp_data_dir, monkeypatch):
    """The refusal runs **before the first directory is created** — `open_store` on a refused
    location must leave the path absent, not half-built. The synthetic reason stands in for
    the POSIX-mode finding the host platform cannot express."""
    fresh = tmp_data_dir / "never-created"
    monkeypatch.setattr(
        store_module, "_insecure_location_reason", lambda path, **kw: "synthetic: /tmp (1777)")
    with pytest.raises(InsecureLocationError) as raised:
        api_open_store(fresh)
    assert "world-writable" in str(raised.value) or "safe" in str(raised.value)
    assert not fresh.exists(), (
        "TC-STORE-10: the refused start created the data directory. 'Refuses to start' "
        "(CT-STORE-16) means nothing on disk — a half-built directory at a location the "
        "operator must move is a trap the next start quietly reuses."
    )


def test_tc_store_10_the_real_check_passes_the_suite_s_own_tmp_fixture(tmp_data_dir):
    """The control that keeps the refusal honest on this host: the same directory every store
    test uses must pass the real check. If the check ever starts refusing it, every store
    case reds — and the fixture docstring, the store's decision table and this test are the
    three places that agreement is written down."""
    assert _insecure_location_reason(tmp_data_dir) is None
    store = api_open_store(tmp_data_dir)
    store.durable()
    store.close()


@pytest.mark.skipif(os.name != "posix", reason="mode bits are real on POSIX only")
def test_tc_store_10_res_02_created_files_and_directories_are_owner_only(tmp_path):
    """The exact-mode half of the oracle, where modes are real: every directory the store
    creates is 0o700, every database file (and its `-wal`/`-shm` siblings) 0o600, blob files
    included. `RES-02`'s permission-denied variant is the same posture from the other side:
    a location the process cannot write refuses at startup rather than degrading."""
    data_dir = tmp_path / "data"
    store = open_store(data_dir)
    durable = store.durable()
    cohort = store.cohort("c-perm")
    blobs = store.blobs()
    blobs.put(b"raster")
    handle = cohort
    with handle.transaction() as tx:
        tx.execute(statement("CREATE TABLE perm_probe (id INTEGER PRIMARY KEY)", issue=ISSUE))

    for directory in (data_dir, data_dir / "packages", data_dir / "cohorts", data_dir / "blobs"):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700, (
            f"TC-STORE-10: {directory} is {stat.S_IMODE(directory.stat().st_mode):03o}, not "
            "0700. FR-STORE-09's owner-only is explicit chmod after mkdir, because mkdir's "
            "mode argument is filtered through the umask."
        )
    for db_file in (store.durable_path(), store.cohort_path("c-perm")):
        assert stat.S_IMODE(db_file.stat().st_mode) == 0o600, (
            f"TC-STORE-10: {db_file.name} is not 0600. The -wal holds the same student rows "
            "the database does — a world-readable WAL is the same disclosure with a different "
            "extension."
        )
        wal = db_file.with_name(db_file.name + "-wal")
        if wal.exists():
            assert stat.S_IMODE(wal.stat().st_mode) == 0o600
    for blob_file in (data_dir / "blobs").rglob("*"):
        if blob_file.is_file():
            assert stat.S_IMODE(blob_file.stat().st_mode) == 0o600
    durable.close()


def test_res_02_an_unusable_directory_refuses_at_startup(tmp_data_dir, monkeypatch):
    """`RES-02` — *"Permission denied on the data directory at open: refuse to start, no
    partial initialization."* Driven through the same seam as the refusal cases: a location
    that cannot even be stat'ed by this process is refused, and the reason names the
    directory rather than vanishing into an OSError traceback."""
    locked = tmp_data_dir / "locked"
    def denying_stat(path):
        raise PermissionError(13, "Permission denied", str(path))
    reason = _insecure_location_reason(locked, os_name="posix", stat_fn=denying_stat)
    assert reason is None, (
        "RES-02: an unstat-able ancestor is not evidence of a world-writable one — the check "
        "skips it (the data directory itself may not exist yet). The refusal of a genuinely "
        "unwritable location surfaces as the OS's own error at mkdir, which propagates: "
        "refuse-to-start, no partial initialization."
    )
    # The real half, portable: a data-dir path whose parent is a *file* cannot be created,
    # and open_store refuses before any database exists.
    blocker = tmp_data_dir / "blocker"
    blocker.write_text("not a directory")
    with pytest.raises(Exception) as refused:
        api_open_store(blocker / "data")
    assert type(refused.value).__name__ != "InsecureLocationError"
    assert not (blocker / "data" / "durable.sqlite").exists()
