"""Every `FR-PKG-03` / `FR-PKG-06` constraint is realized, not remembered (`M-PKG`).

Case `TC-PKG-27` (`NFR-PKG-01`, P0, artifact assertion / rung 2), test plan §5.4.
Issue #32 (TS-11).

`NFR-PKG-01`: *"Every constraint in FR-PKG-03 and FR-PKG-06 shall be enforced by a
database constraint or a data-layer guard, not by a caller convention, so violation is a
failed write rather than a code review finding."* The case enumerates each named
constraint with its realization and matches the **live Tier P schema** — the DDL read
back from `sqlite_master` of a real store, the trigger set actually installed, and one
typed probe per data-layer guard to prove it is wired into the write path. A constraint
whose realization is renamed away, dropped from a migration, or left as a docstring
fails here.

The full behavioral sweeps live where the plan puts them: the locked-field sweep in
`test_schema_lock.py` (`TC-PKG-03`, including `NFR-PKG-03`'s single-source enumeration),
the band-set cells in `test_structure_and_graph.py` (`TC-PKG-07`/`TC-PKG-08`). This file
asserts the *realization inventory* those sweeps presuppose.
"""

from __future__ import annotations

import pytest

from aeh.pkg import BandSetError, PackageCatalog, PackageDraft, SchemaLockViolation
from aeh.store import open_store
from tests.support.store_api import statement

pytestmark = pytest.mark.integration

ISSUE = "#32"


def _live_schema(handle) -> dict[str, str]:
    """The live Tier P schema: every table, index and trigger with its SQL, read back
    from the database a real store opened and migrated."""
    rows = handle.query(statement(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE sql IS NOT NULL", issue=ISSUE))
    return {row["name"]: row["sql"] for row in rows}


def _seed_catalog(tmp_data_dir):
    store = open_store(tmp_data_dir)
    handle = store.package("pkg-27b")
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO package (package_id, created_at) "
            "VALUES ('pkg-27b', '2026-01-01')", issue=ISSUE))
    catalog = PackageCatalog(handle, package_id="pkg-27b")
    return store, handle, catalog


# --- the inventory ---------------------------------------------------------------------------------
#
# FR-PKG-03: the schema lock — the data-layer guard (one check every mutation funnels
# through, dispatching on the single-source field list) backstopped by BEFORE triggers on
# every guarded table, so a write that routes around the catalog fails at the database.
#
# FR-PKG-06: the band rules — the cross-row rules (contiguity, monotone points, the
# declared even count) cannot be a SQLite CHECK (they span rows), so their realization
# is the catalog guard probed below; the per-cell halves that CAN be a CHECK are, and
# the DDL must still carry them.

_EXPECTED_TRIGGERS: tuple[str, ...] = (
    # FR-PKG-03's database half — migration 002's immutability backstops:
    "package_version_immutable",
    "criterion_immutable", "criterion_insert_locked",
    "band_immutable", "band_insert_locked",
    "criterion_dependency_immutable", "criterion_dependency_insert_locked",
    "exemplar_immutable", "exemplar_insert_locked",
    "grade_policy_immutable", "grade_policy_insert_locked",
    "validation_record_immutable", "validation_record_insert_locked",
    # migration 005 extended the same rule to the tables it introduced:
    "mcq_option_immutable", "mcq_option_insert_locked", "mcq_option_delete_refused",
    "grade_boundary_immutable", "grade_boundary_insert_locked",
    "grade_boundary_delete_refused", "grade_policy_delete_refused",
    # FR-PKG-20's append-only trail (unconditional — appends are always allowed):
    "elicitation_history_append_only_update",
    "elicitation_history_append_only_delete",
)

_EXPECTED_DDL_FRAGMENTS: tuple[str, ...] = (
    # FR-PKG-06's per-cell halves, as the 001 DDL carries them:
    "CHECK (ordinal >= 0)",        # a band ordinal is never negative
    "CHECK (points >= 0)",         # a band is never worth negative points
    # FR-PKG-05's self-edge half (the catalog refuses it with the graph error; the
    # CHECK backstops raw writes):
    "CHECK (criterion_id <> depends_on)",
    # NFR-PKG-01's own shape: a published version's locked flag cannot drift:
    "CHECK (locked IN (0, 1))",
)


def test_tc_pkg_27_every_named_constraint_is_realized_in_the_live_schema(tmp_data_dir):
    """`TC-PKG-27` — *'every constraint named in FR-PKG-03 and FR-PKG-06 is realized as
    a database CHECK or FK, or as a data-layer guard — not as a caller convention.
    Enumerate and match.'*

    Three realization classes, each matched against the live schema:

    1. **The trigger set** (`FR-PKG-03`'s database half): every immutability backstop
       the migrations install is present by name — a trigger renamed away is a locked
       table quietly unlocked.
    2. **The DDL fragments** (the per-cell halves of `FR-PKG-06` and the self-edge of
       `FR-PKG-05`): read back from `sqlite_master`, not from the source — the schema a
       real store opens is the artifact under assertion.
    3. **The data-layer guards** (the cross-row rules no CHECK can express): one typed
       probe each, proving the guard is wired into the write path rather than written
       in a docstring."""
    store, handle, catalog = _seed_catalog(tmp_data_dir)
    live = _live_schema(handle)
    live_triggers = {name for name, sql in live.items()
                     if name in set(_EXPECTED_TRIGGERS)}
    missing = sorted(set(_EXPECTED_TRIGGERS) - live_triggers)
    assert not missing, (
        f"TC-PKG-27: the live Tier P schema is missing immutability trigger(s) "
        f"{missing}. NFR-PKG-01 makes the §6.2 lock a property of the data — a "
        "trigger renamed away is a locked table quietly unlocked for every write "
        "that routes around the catalog."
    )

    ddl_text = "\n".join(sql for name, sql in live.items()
                         if name in {"package_version", "criterion", "band",
                                     "criterion_dependency"})
    for fragment in _EXPECTED_DDL_FRAGMENTS:
        assert fragment in ddl_text, (
            f"TC-PKG-27: the live Tier P DDL no longer carries {fragment!r}. The "
            "per-cell constraint was realized as a database CHECK; losing it from the "
            "schema leaves the rule to a caller convention (NFR-PKG-01)."
        )

    # -- the data-layer guards, probed once each (the full sweeps are TC-PKG-03/-07/-08's):
    v = catalog.create_version(None, PackageDraft(title="realization probes"))

    # FR-PKG-06, declare half: a band_count that is odd and out of range is refused at
    # the declare, before any row exists.
    with pytest.raises(BandSetError):
        catalog.add_criterion(v, "PR-1", question_id="Q", kind="open",
                              max_points=4.0, band_count=3)
    # FR-PKG-06, publish half: a declared count that is not fully populated refuses
    # publication — the rule holds at the boundary where the lock begins.
    catalog.add_criterion(v, "PR-2", question_id="Q", kind="open", max_points=4.0,
                          band_count=4)
    catalog.add_band(v, "PR-2", 0, "b0", 0.0)
    catalog.add_band(v, "PR-2", 1, "b1", 1.0)
    catalog.add_band(v, "PR-2", 2, "b2", 2.0)
    with pytest.raises(BandSetError):
        catalog.publish(v, "approver")  # PR-2 declares 4, carries 3: odd, incomplete
    # The no-op pin: the count half runs BEFORE the lock flips, so the refused publish
    # left the version unlocked. (Before #32 the validation ran after the UPDATE
    # committed, and a refused publish left the version locked with the incomplete set
    # — an immutable invalid instrument.)
    assert not catalog.is_locked(v), (
        "TC-PKG-27: a refused publish locked the version — the count half must run "
        "before the lock transaction, or the refusal is not a no-op and the locked "
        "version carries the invalid band set forever."
    )
    # FR-PKG-06, contiguity and monotonicity: the whole-set guard runs inside the
    # write, refusing the gapped ordinal and the decreasing points value.
    catalog.add_band(v, "PR-2", 3, "b3", 3.0)  # complete the set so later steps run
    catalog.add_criterion(v, "PR-3", question_id="Q", kind="open", max_points=4.0)
    catalog.add_band(v, "PR-3", 0, "b0", 0.0)
    with pytest.raises(BandSetError):
        catalog.add_band(v, "PR-3", 2, "b2", 2.0)  # gap: not contiguous from 0
    catalog.add_band(v, "PR-3", 1, "b1", 2.0)
    with pytest.raises(BandSetError):
        catalog.add_band(v, "PR-3", 2, "b2", 1.0)  # 1.0 < 2.0: not non-decreasing

    # FR-PKG-03: the guard refuses a locked-field edit on a PUBLISHED version with the
    # exact typed error (the exhaustive sweep is TC-PKG-03's; here the realization).
    v_published = catalog.create_version(None, PackageDraft(title="published probe"))
    catalog.add_criterion(v_published, "PR-P", question_id="Q", kind="open",
                          max_points=4.0)
    catalog.publish(v_published, "approver")
    with pytest.raises(SchemaLockViolation):
        catalog.update_criterion_field(v_published, "PR-P", "max_points", 5.0)
    # ...and the trigger half: the same edit by raw SQL fails at the database, which is
    # what makes the lock a property of the data rather than of the catalog's callers.
    with pytest.raises(Exception) as raw_refused:
        with handle.transaction() as tx:
            tx.execute(statement(
                "UPDATE criterion SET max_points = 5.0 WHERE package_version_id = :v "
                "AND criterion_id = 'PR-P'", issue=ISSUE), v=v_published)
    assert "immutable" in str(raw_refused.value), (
        "TC-PKG-27: a raw-SQL edit on a published version succeeded — the guard is a "
        "caller convention, not a data-layer one (NFR-PKG-01)."
    )
    store.close()
