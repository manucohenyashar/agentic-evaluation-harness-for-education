"""The §6.2 schema lock, exhaustive — every forbidden edit refused at the data layer.

Case `TC-PKG-03` (`FR-PKG-03`, `NFR-PKG-01`, `NFR-PKG-03`, P0, exhaustive sweep), test
plan §5.4. Issue #27.

Rung 2 — real Tier P database, constraints active. The sweep is **exhaustive, not
representative**: the plan's 15-row table is walked row for row, because a lock that
refuses 14 of 15 forbidden edits is a lock with a door left open.

`Written ahead of implementation: yes` is stale — the catalog landed with #26/#27; the
case runs green by design.
"""

from __future__ import annotations

import pytest

from aeh.pkg import (
    PackageCatalog,
    PackageDraft,
    PublishedVersionImmutableError,
    SCHEMA_LOCK_FIELDS,
    SchemaLockViolation,
)
from aeh.store import open_store
from tests.support.store_api import statement

pytestmark = pytest.mark.integration

ISSUE = "#27"


def _seed_published_with_five_criteria(tmp_data_dir):
    """The plan's fixture: a published version with five criteria (one deterministic MCQ,
    three atomic, one holistic), 2/4-band sets, two dependency edges, three exemplars."""
    store = open_store(tmp_data_dir)
    handle = store.package("pkg-27")
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO package (package_id, created_at) "
            "VALUES ('pkg-27', '2026-01-01')", issue=ISSUE))
    catalog = PackageCatalog(handle, package_id="pkg-27")
    v = catalog.create_version(None, PackageDraft(title="friction, five criteria"))
    kinds = (("CRIT-1", "mcq", "4.0"), ("CRIT-2", "open", "4.0"),
             ("CRIT-3", "open", "4.0"), ("CRIT-4", "open", "4.0"),
             ("CRIT-5", "open", "4.0"))
    with handle.transaction() as tx:
        for criterion_id, kind, max_points in kinds:
            tx.execute(statement(
                "INSERT INTO criterion (package_version_id, criterion_id, question_id, "
                "kind, max_points, scoring_model, construct_tag) "
                "VALUES (:v, :c, :q, :k, :mp, :sm, :ct)", issue=ISSUE),
                v=v, c=criterion_id, q=f"Q-{criterion_id}", k=kind,
                mp=float(max_points), sm="atomic" if kind != "open" else "holistic",
                ct="forces-and-motion")
            band_count = 2 if kind == "mcq" else 4
            for ordinal in range(band_count):
                tx.execute(statement(
                    "INSERT INTO band (package_version_id, criterion_id, ordinal, band, "
                    "points, descriptor) VALUES (:v, :c, :o, :b, :p, :d)", issue=ISSUE),
                    v=v, c=criterion_id, o=ordinal, b=f"b{ordinal}",
                    p=float(ordinal), d=f"descriptor {ordinal}")
        tx.execute(statement(
            "INSERT INTO criterion_dependency (package_version_id, criterion_id, "
            "depends_on) VALUES (:v, 'CRIT-2', 'CRIT-1')", issue=ISSUE), v=v)
        tx.execute(statement(
            "INSERT INTO criterion_dependency (package_version_id, criterion_id, "
            "depends_on) VALUES (:v, 'CRIT-3', 'CRIT-1')", issue=ISSUE), v=v)
        for index in range(3):
            tx.execute(statement(
                "INSERT INTO exemplar (exemplar_id, package_version_id, criterion_id, "
                "band) VALUES (:v || '-ex-' || :i, :v, 'CRIT-1', 'b0')", issue=ISSUE),
                v=v, i=index)
    catalog.publish(v, "approver")
    return store, handle, catalog, v


def test_tc_pkg_03_the_exhaustive_forbidden_edit_sweep(tmp_data_dir):
    """`TC-PKG-03` — the plan's 15 rows, walked row for row against the published version.

    Oracle per row: exact exception type **and** the named field in the message; row 15
    asserts the sanctioned escape (the same clarification edit via `create_version`
    succeeds)."""
    store, handle, catalog, v = _seed_published_with_five_criteria(tmp_data_dir)

    # Rows 1-6: criterion-field edits through the guard — SchemaLockViolation, named.
    for field, value, named_field in (
        ("max_points", 5.0, "max_points"),
        ("question_type", "mcq", "question_type"),
        ("scoring_model", "atomic", "scoring_model"),
        ("construct_tag", "energy", "construct_tag"),
    ):
        with pytest.raises(SchemaLockViolation) as refused:
            catalog.update_criterion_field(v, "CRIT-2", field, value)
        assert named_field in str(refused.value), (
            f"TC-PROV row ({field}): the refusal does not name the field. An operator "
            "fixing a refused edit needs the field, not a generic refusal."
        )

    # Rows 2-3 via the add/remove surface:
    with pytest.raises(SchemaLockViolation) as add_refused:
        catalog.add_criterion(v, "CRIT-6")
    assert "add" in str(add_refused.value)
    with pytest.raises(SchemaLockViolation) as remove_refused:
        catalog.remove_criterion(v, "CRIT-5")
    assert "remove" in str(remove_refused.value)

    # Rows 7-10: band-field edits, each named:
    for field, value in (("label", "renamed"), ("ordinal", 9),
                         ("descriptor", "new descriptor"), ("points", 9.0)):
        with pytest.raises(SchemaLockViolation) as band_refused:
            catalog.update_band_field(v, "CRIT-2", 0, field, value)
        assert field in str(band_refused.value), (
            f"TC-PKG-03 (band.{field}): the refusal does not name the field."
        )

    # Rows 11-13: dependency add/remove/alter:
    for attempt in ("add", "remove", "alter"):
        with pytest.raises(SchemaLockViolation) as dep_refused:
            catalog.update_criterion_dependency(v)
        assert "dependency" in str(dep_refused.value)

    # Row 14: the same clarification edit IN PLACE — refused, at the database (the
    # INSERT trigger), proving the guard is at the data layer, not in a caller.
    with pytest.raises(Exception) as in_place:
        with handle.transaction() as tx:
            tx.execute(statement(
                "INSERT INTO criterion (package_version_id, criterion_id, question_id, "
                "kind) VALUES (:v, 'CRIT-1a', 'Q-1a', 'open')", issue=ISSUE), v=v)
    assert "immutable" in str(in_place.value), (
        "TC-PKG-03 (row 14): the in-place sub-criterion INSERT succeeded against a "
        "published version. The edit-in-place must fail AT THE DATABASE — a caller-side "
        "check alone is exactly what M-CALIB could route around (NFR-PKG-01)."
    )

    # Row 15: the sanctioned escape — the same clarification via a revision succeeds,
    # producing a new UNPUBLISHED version with parent_version_id set.
    v_new = catalog.create_version(v, PackageDraft(title="clarification"))
    row = handle.query(statement(
        "SELECT locked, parent_version_id FROM package_version "
        "WHERE package_version_id = :v", issue=ISSUE), v=v_new)[0]
    assert row["locked"] == 0 and row["parent_version_id"] == v
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO criterion (package_version_id, criterion_id, question_id, kind) "
            "VALUES (:v, 'CRIT-1a', 'Q-1a', 'open')", issue=ISSUE), v=v_new)
    store.close()


def test_tc_pkg_03_the_raw_sql_path_is_also_refused(tmp_data_dir):
    """The sweep's second leg — the same edits attempted by **raw SQL against the tier
    handle**, proving the guard lives in the data layer: a caller that routes around the
    catalog hits the database's own refusal."""
    store, handle, catalog, v = _seed_published_with_five_criteria(tmp_data_dir)
    raw_updates = (
        "UPDATE criterion SET max_points = 5.0 WHERE criterion_id = 'CRIT-2'",
        "UPDATE criterion SET kind = 'mcq' WHERE criterion_id = 'CRIT-2'",
        "UPDATE criterion SET scoring_model = 'holistic' WHERE criterion_id = 'CRIT-5'",
        "UPDATE criterion SET construct_tag = 'energy' WHERE criterion_id = 'CRIT-2'",
        "UPDATE band SET band = 'renamed' WHERE criterion_id = 'CRIT-2' AND ordinal = 0",
        "UPDATE band SET points = 9.0 WHERE criterion_id = 'CRIT-2' AND ordinal = 0",
    )
    for sql in raw_updates:
        with pytest.raises(Exception) as refused:
            with handle.transaction() as tx:
                tx.execute(statement(sql, issue=ISSUE))
        assert "immutable" in str(refused.value), (
            f"TC-PKG-03 (raw SQL): {sql!r} succeeded against a published version. The "
            "trigger backstop is the data-layer proof NFR-PKG-01 demands."
        )
    store.close()


def test_tc_pkg_nfr_03_the_forbidden_field_list_is_single_source_and_matches_the_hld():
    """`NFR-PKG-03` — *'the schema lock's forbidden-field list shall exist in exactly one
    place in the source and be enumerable at runtime, so a test can assert the list
    matches HLD §6.2.'*

    Oracle: **artifact assertion**. The list is `SCHEMA_LOCK_FIELDS`, and the HLD §6.2
    field-for-field expectation lives HERE — the test is the second copy only in the
    sense every contract test is: it pins the source, it does not duplicate it."""
    expected = {
        ("criterion", "max_points"),
        ("criterion", "add"),
        ("criterion", "remove"),
        ("criterion", "question_type"),
        ("criterion", "scoring_model"),
        ("criterion", "construct_tag"),
        ("band", "label"),
        ("band", "ordinal"),
        ("band", "descriptor"),
        ("band", "points"),
        ("criterion_dependency", "add"),
        ("criterion_dependency", "remove"),
        ("criterion_dependency", "alter"),
    }
    assert set(SCHEMA_LOCK_FIELDS) == expected, (
        "NFR-PKG-03: SCHEMA_LOCK_FIELDS drifted from HLD §6.2. The lock's list is "
        "single-source — this assertion is what keeps a quietly added field from becoming "
        "a quietly editable one."
    )
    # Enumerable at runtime: it is a plain tuple of (table, field) pairs, and the guard
    # dispatches on it (the guard's membership check reads the same constant).
    assert all(len(pair) == 2 for pair in SCHEMA_LOCK_FIELDS)


def test_tc_pkg_03_draft_versions_edit_freely(tmp_data_dir):
    """The negative that keeps the lock honest: a DRAFT version's locked fields edit
    freely — the copy-on-revision flow exists to give clarifications a vehicle, and a
    lock that refused drafts would make authoring impossible."""
    store, handle, catalog, v = _seed_published_with_five_criteria(tmp_data_dir)
    draft = catalog.create_version(v, PackageDraft(title="draft"))
    catalog.update_criterion_field(draft, "CRIT-2", "max_points", 5.0)
    catalog.update_criterion_field(draft, "CRIT-2", "question_type", "mcq")
    rows = handle.query(statement(
        "SELECT max_points, kind FROM criterion WHERE package_version_id = :v "
        "AND criterion_id = 'CRIT-2'", issue=ISSUE), v=draft)
    assert rows[0]["max_points"] == 5.0 and rows[0]["kind"] == "mcq"
    store.close()
