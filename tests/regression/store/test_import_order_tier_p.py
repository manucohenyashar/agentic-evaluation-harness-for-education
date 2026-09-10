"""`TC-STORE-25` — the Tier-P-before-`aeh.pkg` import-order requirement (`FR-STORE-02`, #234).

**The footgun.** The chains in `TIER_MIGRATIONS` are *concatenated at import time* by the
modules that own the schema they add — `aeh.pkg` and `aeh.det` for Tier P, `aeh.ingest`,
`aeh.det`, `aeh.orch`, `aeh.extract`, `aeh.judge`, `aeh.synth`, `aeh.agg` and `aeh.grade`
for Cohort, `aeh.det` and `aeh.integ` for Tier D — so the
chain an
open sees is only as long as the list of contributing modules the process has imported so
far. A process that opens a Tier P file before those imports builds the file at the base
schema (version 1), and the columns the missing migrations would have added surface **later,
far from the open**, as `sqlite3.OperationalError: no such column: parent_version_id` —
#46's probe, disclosed in PR #208, found suite-wide by #94 (whose seeds chose between the two
worlds).

**The guard** (#234): `COMPLETE_SCHEMA_VERSIONS` pins the version each tier must reach once
every contributing module is imported, and `_open_tier` refuses an open whose in-process chain
falls short of the pin — **at the open site, naming the cause** — instead of letting the file
build short and fail at a distance.

**Reconciliation with #269.** Import order had two failure modes. The *ordering* one — an
early import appending a late migration first, so a tier's chain arrived out of version order
and TC-STORE-04/06 flaked with #94's seeds — #269 fixed at the root: `_VersionOrderedRegistry`
sorts each tier's chain at write time, and the pin test below asserts that guarantee. The
*completeness* one survives #269, because a module that was never imported contributes no
migrations at all and sorting cannot add what was never registered — on bare main (PR #269
landed) a fresh interpreter importing only `aeh.store` still opens a Tier P file at the base
schema and #46's probe still fails at a distance. The refusal below pins that world. (The
same gate has now caught two rotations the original draft of this file could not have seen:
#269's `aeh.extract` appends Cohort migration 11 — the pin moved 10→11 — and #61's
`orch_run_lifecycle` appends Cohort migration 12 — the pin moved 11→12, with `aeh.orch` now
owning Cohort's last migration and `aeh.extract` the tail before it. Each time
`COMPLETE_SCHEMA_VERSIONS[Cohort]` failed this file the moment the suites ran on the merged
tree, which is the pin-rot gate working as documented. #78's `judge_verdict_columns` is
the third and fourth rotations — numbered 13 when it first landed, renumbered 12→13→14
as #61's lifecycle and then #97's `synth_narrative_key` took the numbers first at the
merges (`aeh.judge` owned Cohort's last migration; `aeh.synth` joined the import lists
below in the same change). #92's `agg_confidence_columns` is the fifth — Cohort 15→16,
`aeh.agg` joining the lists and owning the tail — and #80's
`judge_verdict_response_columns` the sixth — Cohort 16→17, the tail returning to
`aeh.judge`. #101's `grade_submission_grade_key` is the seventh — Cohort 17→18,
`aeh.grade` joining the lists and owning the tail again.)

**Why fresh interpreters.** Inside this suite the conftest imports every contributing module
up front, so an in-process case could never see the truncated world — the very reason the
footgun hides from the suite and bites only consumers. Each subprocess below starts a real
interpreter, importing exactly what the world it demonstrates imports (`PYTHONPATH` points at
this checkout's `src`).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_SRC = Path(__file__).resolve().parents[3] / "src"

#: Exits 0 naming the refusal; 3 means the open *succeeded* — the unguarded world, where the
#: file silently builds at the base schema and the failure is deferred to a distant query.
_TRUNCATED_WORLD_CHILD = """
import sys

from aeh.store import open_store

store = open_store(sys.argv[1])
try:
    store.package("imp-order")
except Exception as error:
    print(f"REFUSED: {type(error).__module__}.{type(error).__name__}")
    print(str(error))
    sys.exit(0 if "IncompleteMigrationChainError" in type(error).__name__ else 4)
print("OPENED")
sys.exit(3)
"""

#: The convention's world: every contributing module imported before the first open. The probe
#: that #46 ran — a raw SELECT of the column the distant failure named — must now succeed.
_FULL_CHAIN_CHILD = """
import sqlite3
import sys

import aeh.agg  # noqa: F401
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.synth  # noqa: F401

from aeh.store import open_store

store = open_store(sys.argv[1])
store.package("imp-order")
version = store.opened[-1].schema_version_after
store.close()

rows = sqlite3.connect(sys.argv[2]).execute(
    "SELECT parent_version_id FROM package_version LIMIT 1"
).fetchall()
print(f"VERSION: {version}")
print(f"PROBE-OK: {len(rows) == 0}")
sys.exit(0)
"""


def _run_child(script: str, data_dir: Path, package_path: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(  # noqa: S603 — fixed argv, no shell
        [sys.executable, "-c", script, str(data_dir), str(package_path)],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        check=False,
    )


def test_tc_store_25_opening_tier_p_without_the_pkg_import_refuses_at_the_open(
    tmp_data_dir,
):
    """A fresh interpreter that imports `aeh.store` alone and opens a Tier P file must be
    refused **at the open site**, with the cause named — never allowed to build the file at
    the base schema and fail later as a distant `no such column` (#234's acceptance edge)."""
    result = _run_child(
        _TRUNCATED_WORLD_CHILD, tmp_data_dir, tmp_data_dir / "packages" / "imp-order.pkg.sqlite"
    )
    assert result.returncode == 0, (
        f"TC-STORE-25: the truncated-world open was not refused at the open site "
        f"(exit {result.returncode}, stdout {result.stdout!r}, stderr {result.stderr!r}). "
        "Left unguarded, the file builds at the base schema and the missing columns surface "
        "later as `no such column: parent_version_id` — a phantom bug at a distance from its "
        "cause (#46, PR #208, #94)."
    )
    assert "IncompleteMigrationChainError" in result.stdout
    assert "aeh.pkg" in result.stdout, (
        f"TC-STORE-25: the refusal must name the cause and the fix — the owning import — "
        f"not a bare failure. stdout was {result.stdout!r}."
    )
    package_file = tmp_data_dir / "packages" / "imp-order.pkg.sqlite"
    assert not package_file.exists(), (
        "TC-STORE-25: the refusal fired after the file was created — a file built from the "
        "truncated chain exists on disk, which is the very artifact the guard exists to "
        "prevent."
    )


def test_tc_store_25_opening_tier_p_after_the_full_chain_import_opens_complete(
    tmp_data_dir,
):
    """The convention's world: every contributing module imported before the first open. The
    open succeeds, the file reaches the full schema version, and #46's probe — the exact
    SELECT whose distant failure named this issue — runs clean against the file."""
    package_path = tmp_data_dir / "packages" / "imp-order.pkg.sqlite"
    result = _run_child(_FULL_CHAIN_CHILD, tmp_data_dir, package_path)
    assert result.returncode == 0, (
        f"TC-STORE-25: the convention's world must open and probe clean "
        f"(exit {result.returncode}, stdout {result.stdout!r}, stderr {result.stderr!r})."
    )
    assert "PROBE-OK: True" in result.stdout, (
        f"TC-STORE-25: `parent_version_id` missing after a convention-conformant open "
        f"({result.stdout!r}) — the full chain did not land."
    )


def test_tc_store_25_pin_tracks_the_full_chain():
    """The pin must track the chain: a migration added without bumping
    `COMPLETE_SCHEMA_VERSIONS` would leave the guard refusing opens in the *full* world —
    the pin rots into the same phantom bug it guards against, in mirror image. The same loop
    pins #269's version-order guarantee: whatever order the contributing modules got imported
    in (this test module itself is collected after `aeh.det` has been imported first by the
    conftest block, the ordering #94's seeds used to shuffle), a tier's chain must read in
    ascending version order — `TC-STORE-06`'s no-reverse-step as a property of the registry
    (`_VersionOrderedRegistry`), not of anyone's collection order."""
    import aeh.agg  # noqa: F401
    import aeh.det  # noqa: F401
    import aeh.extract  # noqa: F401
    import aeh.grade  # noqa: F401
    import aeh.ingest  # noqa: F401
    import aeh.integ  # noqa: F401
    import aeh.judge  # noqa: F401
    import aeh.orch  # noqa: F401
    import aeh.pkg  # noqa: F401
    import aeh.synth  # noqa: F401

    from aeh.store import COMPLETE_SCHEMA_VERSIONS, TIER_MIGRATIONS, Tier, current_schema_version

    for tier in Tier:
        versions = [m.version for m in TIER_MIGRATIONS[tier]]
        assert versions == sorted(versions), (
            f"TC-STORE-25: {tier.value}'s migration chain reads {versions} — out of version "
            "order. #269's `_VersionOrderedRegistry` sorts each tier's chain at write time, so "
            "the order a contributor appends in must never be observable; a sorted() in an "
            "appender or a registry change broke the contract."
        )
        assert current_schema_version(tier) == COMPLETE_SCHEMA_VERSIONS[tier], (
            f"TC-STORE-25: {tier.value} implements schema version "
            f"{current_schema_version(tier)} with every contributing module imported, but "
            "COMPLETE_SCHEMA_VERSIONS pins "
            f"{COMPLETE_SCHEMA_VERSIONS[tier]}. A change that adds a migration bumps the pin "
            "in the same change — a stale pin refuses opens in the full-chain world."
        )
