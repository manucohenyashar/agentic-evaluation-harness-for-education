"""The smoke suite (TS-50, issue #143) — the store comes up whole and lands safely.

`TC-SMOKE-03` (`FR-STORE-01`, `FR-STORE-02`) — all four tiers open, migrate to current, and
report `journal_mode = wal`; fails if any tier fails to open or migrate. `TC-SMOKE-04`
(`FR-STORE-09`) — the data directory exists with owner-only permissions and is not inside a
temp path; fails on a wrong mode or an insecure location.

Two platform facts shape `TC-SMOKE-04`, both stated in the store's own decision table and
the reason `TC-STORE-10` (issue #15) drives the same seams: this suite runs on Windows only,
where `os.stat` fabricates `0o777` for every directory and `%TEMP%` is ACL-scoped per user,
so "owner-only" and "inside a world-writable temp path" are unconstructible **as real host
states**. The real half of the case is what Windows can express — the data directory exists,
the real check passes it, and the refusal creates nothing; the exact-mode half runs through
`_insecure_location_reason`'s injectable `os_name`/`stat_fn` seams, POSIX semantics
exercised from this host.

`Written ahead of implementation: yes` is stale — the store landed with #10-#13; the cases
run green by design.
"""

from __future__ import annotations

import os
import stat as stat_module
from pathlib import Path

import pytest

import aeh.store as store_module
from aeh.store import (
    COMPLETE_SCHEMA_VERSIONS,
    InsecureLocationError,
    Tier,
    _insecure_location_reason,
    open_store,
)
from tests.support.store_vocabulary import journal_mode

ISSUE = "#143"


def _posix_stat(mode: int):
    """A `stat` stand-in reporting `mode` for every path — the synthetic ancestor."""

    def _stat(path):
        return os.stat_result((mode, 0, 0, 0, 0, 0, 0, 0, 0, 0))

    return _stat


def test_tc_smoke_03_all_four_tiers_open_migrate_and_report_wal(tmp_data_dir):
    """`TC-SMOKE-03` — all four tiers open, migrate to current, and report `journal_mode=wal`.

    Oracle: **exact per-tier values**. Four logical tiers (P, C, R, D) live in three physical
    files — C and R share one file by design (`Tier`'s docstring: they are created and purged
    together, and one file keeps `purge_cohort` a VACUUM on one database) — so the oracle is
    one `TierOpened` record per physical file, each carrying `schema_version_after` equal to
    the tier's `COMPLETE_SCHEMA_VERSIONS` pin, every migration in its chain applied from a
    fresh file, `journal_mode == "wal"` and foreign keys on **on the open handle**, and — the
    persistence half — `wal` on an **independent read-only connection** per file, because a
    per-connection pragma that was not persisted would satisfy the first check and lose
    durability across processes.

    A truncated migration chain (`IncompleteMigrationChainError` at the open, #234), a tier
    that opens below its pin, or a journal mode that regressed to `delete` each red here.
    """
    store = open_store(tmp_data_dir)
    try:
        store.package("pkg-smoke")  # Tier P: packages/pkg-smoke.pkg.sqlite
        store.cohort("c-smoke")     # Tiers C (+ R, same file): cohorts/c-smoke.sqlite
        store.durable()             # Tier D: durable.sqlite

        opened = {record.tier: record for record in store.opened}
        assert set(opened) == {Tier.PACKAGE, Tier.COHORT, Tier.DURABLE}, (
            f"TC-SMOKE-03: the tiers that opened are {sorted(opened)}. All four logical "
            "tiers (three physical files) must come up — FR-STORE-01 counts four."
        )
        for tier, record in opened.items():
            pin = COMPLETE_SCHEMA_VERSIONS[tier]
            assert record.schema_version_after == pin, (
                f"TC-SMOKE-03: {tier.value} opened at schema version "
                f"{record.schema_version_after}, not the current pin {pin}. A tier that "
                "did not migrate to current is a distant-failure trap, not a working store."
            )
            assert record.migrations_applied == tuple(range(1, pin + 1)), (
                f"TC-SMOKE-03: {tier.value} applied {record.migrations_applied} on a fresh "
                f"file; the full chain is 1..{pin}."
            )
            assert record.journal_mode == "wal"
            assert record.foreign_keys is True

        for path in (
            store.package_path("pkg-smoke"),
            store.cohort_path("c-smoke"),
            store.durable_path(),
        ):
            assert journal_mode(path) == "wal", (
                f"TC-SMOKE-03: {path.name} does not report journal_mode=wal on an "
                "independent connection. WAL must be persisted in the file, not only set "
                "on the opening handle — a store that restarts into rollback-journal mode "
                "has lost FR-STORE-02's crash behavior."
            )
    finally:
        store.close()


def test_tc_smoke_04_data_dir_owner_only_and_not_inside_a_temp_path(tmp_data_dir, monkeypatch):
    """`TC-SMOKE-04` — the data directory exists with owner-only permissions and is not
    inside a temp path.

    Oracle: **the refusal partition, on the real host where it can be expressed**. The real
    half: `open_store` on the suite's own data directory succeeds, the three subdirectories
    exist, and the real check passes this host's ACL-scoped `%TEMP%` (`None` — by design, not
    by omission; see the module docstring). The seam half drives `_insecure_location_reason`
    with POSIX semantics: a data directory inside a world-writable temp path is refused,
    a world-writable directory is refused (wrong mode), an owner-only `0o700` directory is
    accepted, and the refusal fires **before anything is created** — a store that half-builds
    at an unsafe location leaves the trap for the next start.
    """
    # The real location: every store test's data directory must pass the real check, and
    # the layout FR-STORE-01's tiers need must actually exist on disk.
    assert _insecure_location_reason(tmp_data_dir) is None
    store = open_store(tmp_data_dir)
    try:
        store.durable()
    finally:
        store.close()
    for child in ("packages", "cohorts", "blobs"):
        assert (tmp_data_dir / child).is_dir(), (
            f"TC-SMOKE-04: {child} is missing from the data directory. The store creates "
            "the §3.3 layout at open — a layout half-created is an install step NFR-STORE-03 "
            "forbids."
        )

    # Wrong mode and insecure location, through the check's own seams.
    assert _insecure_location_reason(
        Path("/tmp/pytest-of-operator/data"), os_name="posix",
        stat_fn=lambda p: os.stat_result(
            (0o40700 if p.name == "data" else 0o41777, 0, 0, 0, 0, 0, 0, 0, 0, 0)),
    ) is not None, (
        "TC-SMOKE-04: a data directory inside a world-writable temp path was accepted. "
        "FR-STORE-09 refuses to put student work where every other account on the host "
        "can reach it."
    )
    assert _insecure_location_reason(
        Path("/srv/share/data"), os_name="posix", stat_fn=_posix_stat(0o40777)
    ) is not None, (
        "TC-SMOKE-04: a world-writable data directory was accepted. Owner-only is the "
        "requirement; 0777 is the wrong mode and must be refused."
    )
    assert _insecure_location_reason(
        Path("/srv/operator/data"), os_name="posix", stat_fn=_posix_stat(0o40700)
    ) is None, (
        "TC-SMOKE-04: an owner-only (0700) data directory was refused. The check must "
        "refuse the world-writable cases and accept the owner-only one — both halves, or "
        "the requirement is not what is implemented."
    )

    # The refusal runs before the first directory exists — nothing half-built.
    fresh = tmp_data_dir / "never-created"
    monkeypatch.setattr(
        store_module, "_insecure_location_reason",
        lambda path, **kw: "synthetic: /tmp (1777)",
    )
    with pytest.raises(InsecureLocationError) as raised:
        open_store(fresh)
    assert "world-writable" in str(raised.value) or "synthetic" in str(raised.value)
    assert not fresh.exists(), (
        "TC-SMOKE-04: the refused start created the data directory. 'Not inside a temp "
        "path' must hold before the first byte of student data has anywhere to land."
    )