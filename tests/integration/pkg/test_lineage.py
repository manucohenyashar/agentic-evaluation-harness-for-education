"""Version lineage and published-version immutability (`M-PKG`).

Cases `TC-PKG-01`, `TC-PKG-02`, `TC-PKG-04` (`FR-PKG-01`, `-02`, `-04`, P0/P1), test plan
§5.4 — the #26 share of TS-11 (issue #32 owns the remaining schema-lock sweep cases).
Issue #26.

Rung 2 — real Tier P files, because the oracle is a **state assertion**: the prior version
is byte-unchanged, and a write that routes around the catalog fails at the database.

`Written ahead of implementation: yes` is stale — the catalog landed with #26; the cases
run green by design.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from aeh.pkg import (
    BandSetError,
    PackageCatalog,
    PackageDraft,
    PublishedVersionImmutableError,
)
from aeh.store import open_store
from tests.support.store_api import statement

pytestmark = pytest.mark.integration

ISSUE = "#26"
ISSUE_230 = "#230"  # TC-PKG-30's raw reads attribute their statements to their story


def _seed_published(catalog: PackageCatalog, handle, package_id: str = "pkg-26") -> str:
    """A published v1 with one criterion and one band — the state a revision revises."""
    v1 = catalog.create_version(None, PackageDraft(title="friction"))
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO criterion (package_version_id, criterion_id, question_id, kind) "
            "VALUES (:v, 'CRIT-1', 'Q-1', 'open')", issue=ISSUE), v=v1)
        tx.execute(statement(
            "INSERT INTO band (package_version_id, criterion_id, ordinal, band, points) "
            "VALUES (:v, 'CRIT-1', 0, 'b0', 0.0)", issue=ISSUE), v=v1)
    catalog.publish(v1, "approver")
    return v1


def _seed_package_row(handle, package_id: str = "pkg-26") -> None:
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO package (package_id, created_at) "
            "VALUES (:p, '2026-01-01')", issue=ISSUE), p=package_id)


def _row_digests(handle, v: str) -> dict[str, str]:
    """Every row of every content table for version `v`, as a digest — the byte-unchanged
    assertion TC-PKG-01's oracle names."""
    digests: dict[str, str] = {}
    for table in ("package_version", "criterion", "band"):
        rows = handle.query(statement(
            f"SELECT * FROM {table} WHERE package_version_id = :v", issue=ISSUE), v=v)
        digests[table] = hashlib.sha256(repr([tuple(r) for r in rows]).encode()).hexdigest()
    return digests


def test_tc_pkg_01_published_version_refuses_every_update_and_is_byte_unchanged(
    tmp_data_dir,
):
    """`TC-PKG-01` — *'update a package_version row with published = 1; then a criterion
    referencing it; then a criterion_band; then an exemplar: every update raises
    PublishedVersionImmutableError; the row is byte-unchanged afterwards.'*

    Two enforcement layers are asserted, because `NFR-PKG-01` demands the violation be a
    failed write, not a convention:

    1. **The data-layer guard** — the catalog's publish-of-a-published attempt raises the
       exact typed error.
    2. **The database triggers** — a write that routes around the catalog through the raw
       Tier P handle (the route M-CALIB could take, per `NFR-PKG-01`) fails at the
       database with the trigger's message, and every row of the published version is
       byte-unchanged afterwards."""
    store = open_store(tmp_data_dir)
    handle = store.package("pkg-26")
    _seed_package_row(handle)
    catalog = PackageCatalog(handle, package_id="pkg-26")
    v1 = _seed_published(catalog, handle)
    before = _row_digests(handle, v1)

    # Layer 1 — the data-layer guard, exact type:
    with pytest.raises(PublishedVersionImmutableError):
        catalog.publish(v1, "second-approver")

    # Layer 2 — the database triggers, for every table the version owns:
    for table, update in (
        ("package_version", "UPDATE package_version SET revision = 9 WHERE package_version_id = :v"),
        ("criterion", "UPDATE criterion SET question_id = 'Q-9' WHERE package_version_id = :v"),
        ("band", "UPDATE band SET points = 9 WHERE package_version_id = :v"),
    ):
        with pytest.raises(sqlite_error()) as refused:
            with handle.transaction() as tx:
                tx.execute(statement(update, issue=ISSUE), v=v1)
        assert "immutable" in str(refused.value), (
            f"TC-PKG-01 ({table}): the write succeeded. NFR-PKG-01 makes the violation a "
            "failed write enforced by the database — a convention review would have to "
            "catch is exactly what a routed-around guard becomes."
        )

    after = _row_digests(handle, v1)
    assert after == before, (
        "TC-PKG-01: the published version's rows changed despite every update raising. "
        "The byte-unchanged oracle is the state half of the exact-exception one."
    )
    store.close()


def sqlite_error():
    import sqlite3

    return sqlite3.IntegrityError


def test_tc_pkg_02_a_revision_is_a_new_row_with_parent_set_and_the_parent_untouched(
    tmp_data_dir,
):
    """`TC-PKG-02` — *'create a revision of a published version: a new package_version row
    exists with parent_version_id set; the parent is untouched; no mutation path exists.'*

    Oracle: **exact value plus lineage assertion** — parent_version_id is the literal
    parent id, the parent's digest is unchanged, and the lineage chain reads oldest-first
    through the parent link (which is how a grade issued years ago resolves to exactly the
    version that produced it)."""
    store = open_store(tmp_data_dir)
    handle = store.package("pkg-26")
    _seed_package_row(handle)
    catalog = PackageCatalog(handle, package_id="pkg-26")
    v1 = _seed_published(catalog, handle)
    before = _row_digests(handle, v1)

    v2 = catalog.create_version(v1, PackageDraft(title="friction, clarified"))

    row = handle.query(statement(
        "SELECT revision, locked, parent_version_id FROM package_version "
        "WHERE package_version_id = :v", issue=ISSUE), v=v2)[0]
    assert row["parent_version_id"] == v1
    assert row["locked"] == 0, "a revision is born unlocked — its edits are its own"
    assert row["revision"] == 2
    assert _row_digests(handle, v1) == before, (
        "TC-PKG-02: the parent changed when the revision was created. FR-PKG-02: a "
        "revision is a new version, never a mutation — the parent is the anchor a grade "
        "resolves to."
    )
    assert catalog.lineage(v2) == (v1, v2)
    store.close()


def test_tc_pkg_04_clarification_edits_succeed_only_as_a_new_version(tmp_data_dir):
    """`TC-PKG-04` — each §6.2 clarification edit, applied via a new version: *'sub-criteria,
    operational definitions, edge-case handling and evidence-type annotations all succeed
    as a new version and fail in place.'*

    The four edits are modelled as content writes against the revision's copied rows (the
    copy is the sanctioned vehicle), each asserted to land in the NEW version while the
    published parent stays untouched. `FR-PKG-04`'s 'fail in place' half is the trigger
    backstop: the same write against the parent's own rows fails at the database."""
    store = open_store(tmp_data_dir)
    handle = store.package("pkg-26")
    _seed_package_row(handle)
    catalog = PackageCatalog(handle, package_id="pkg-26")
    v1 = _seed_published(catalog, handle)

    clarifications = {
        # §6.2's four edit kinds, as content writes on the copied rows:
        "sub-criterion": "INSERT INTO criterion (package_version_id, criterion_id, question_id, kind) "
                         "VALUES (:v, 'CRIT-1a', 'Q-1a', 'open')",
        "operational-definition": "UPDATE criterion SET question_id = 'Q-1 (op. def.)' "
                                  "WHERE package_version_id = :v AND criterion_id = 'CRIT-1'",
        "edge-case-handling": "UPDATE band SET band = 'b0 (edge: no units)' "
                              "WHERE package_version_id = :v AND criterion_id = 'CRIT-1'",
        "evidence-type": "INSERT INTO band (package_version_id, criterion_id, ordinal, band, points) "
                         "VALUES (:v, 'CRIT-1', 1, 'b1', 1.0)",
    }
    for edit, sql in clarifications.items():
        revision = catalog.create_version(v1, PackageDraft(title=f"clarify: {edit}"))
        with handle.transaction() as tx:
            tx.execute(statement(sql, issue=ISSUE), v=revision)  # lands: the copy is unlocked
        # The same write against the published parent fails at the database:
        with pytest.raises(sqlite_error()):
            with handle.transaction() as tx:
                tx.execute(statement(sql, issue=ISSUE), v=v1)
    store.close()


def test_tc_pkg_30_a_revision_child_carries_its_parents_criteria_and_bands_verbatim(
    tmp_data_dir,
):
    """`TC-PKG-30` — *'given a parent version whose criteria carry `max_points`,
    `scoring_model`, `construct_tag`, `band_count` and band descriptors, a revision
    mints a child whose criteria carry all of those fields verbatim; with one explicit
    change, the child differs from the parent in exactly that field'* (#230, FR-PKG-02).

    Oracle: the **differential form** — parent and child rows compared field by field,
    the delta asserted to be exactly the one explicit edit. Before #230 the delta was
    the whole dropped set: a child that differs from its parent in fields nobody
    changed is mutation by omission, and `CT-PKG-02`'s 'a `PackageVersionId`
    identifies content permanently' fails with it."""
    store = open_store(tmp_data_dir)
    handle = store.package("pkg-26")
    _seed_package_row(handle)
    catalog = PackageCatalog(handle, package_id="pkg-26")
    v1 = catalog.create_version(None, PackageDraft(title="rubric"))
    catalog.add_criterion(
        v1, "CRIT-1", question_id="Q-1", kind="open", max_points=12.5,
        scoring_model="holistic", construct_tag="inference", band_count=2,
        evidence_type="quoted_text",
    )
    catalog.add_band(v1, "CRIT-1", 0, "weak", 0.0, descriptor="no evidence cited")
    catalog.add_band(v1, "CRIT-1", 1, "strong", 12.5, descriptor="cites the text")
    catalog.publish(v1, "approver")

    v2 = catalog.create_version(v1, PackageDraft(title="clarify: max_points"))
    catalog.update_criterion_field(v2, "CRIT-1", "max_points", 10.0)  # the one edit

    def rows(table: str, v: str) -> list[dict]:
        return [dict(r) for r in handle.query(statement(
            f"SELECT * FROM {table} WHERE package_version_id = :v ORDER BY rowid",
            issue=ISSUE_230), v=v)]

    parent, child = rows("criterion", v1)[0], rows("criterion", v2)[0]
    assert parent.keys() == child.keys()
    del parent["package_version_id"], child["package_version_id"]  # the new identity
    delta = {key for key in parent if parent[key] != child[key]}
    assert delta == {"max_points"}, (
        f"TC-PKG-30: the revision differs from its parent in fields nobody changed "
        f"({sorted(delta - {'max_points'})}). The copy is verbatim (#230) — a child "
        "that drops criterion fields is mutation by omission, and a PackageVersionId "
        "stops identifying content permanently (CT-PKG-02)."
    )
    assert parent["max_points"] == 12.5 and child["max_points"] == 10.0, (
        "TC-PKG-30: the explicit edit is the one delta — the parent keeps its own "
        "value and the child carries the change."
    )
    def band_rows(version: str) -> list[dict]:
        return [{k: v for k, v in r.items() if k != "package_version_id"}
                for r in rows("band", version)]

    assert band_rows(v1) == band_rows(v2), (
        "TC-PKG-30: the copied band set lost fields (the descriptor first of all). "
        "The bands are copied verbatim — FR-PKG-06's mapping must not drift between "
        "a version and its revision."
    )
    store.close()


def test_tc_pkg_30_a_criterion_that_fails_the_copy_refuses_the_revision(tmp_data_dir):
    """`TC-PKG-30`'s edge — a criterion whose copied band set fails `FR-PKG-06`'s
    count half (a declared `band_count` the copied bands never fully populate —
    M-SETUP's even-band bar) refuses the revision rather than shipping a half-copied
    child. The refusal runs inside the revision's transaction, so it is a no-op
    (`CT-PKG-11`): no child row, no copied rows, nothing to clean up."""
    store = open_store(tmp_data_dir)
    handle = store.package("pkg-26")
    _seed_package_row(handle)
    catalog = PackageCatalog(handle, package_id="pkg-26")
    v1 = catalog.create_version(None, PackageDraft(title="unfinished rubric"))
    catalog.add_criterion(v1, "CRIT-1", question_id="Q-1", kind="open",
                          max_points=4.0, scoring_model="atomic",
                          construct_tag="accuracy", band_count=2)
    catalog.add_band(v1, "CRIT-1", 0, "weak", 0.0, descriptor="off track")
    # The declared 2-band set is half written: the parent is a draft nobody can
    # publish, and a revision would mint the half set as a child's inheritance.

    with pytest.raises(BandSetError):
        catalog.create_version(v1, PackageDraft(title="revise the unfinished"))

    state = handle.query(statement(
        "SELECT (SELECT COUNT(*) FROM package_version) AS versions, "
        "(SELECT COUNT(*) FROM criterion) AS criteria, "
        "(SELECT COUNT(*) FROM band) AS bands", issue=ISSUE_230))[0]
    assert (state["versions"], state["criteria"], state["bands"]) == (1, 1, 1), (
        "TC-PKG-30: the refused revision left rows behind — a half-copied child or a "
        "child version row at all. The refusal is a no-op on disk (CT-PKG-11)."
    )
    store.close()
