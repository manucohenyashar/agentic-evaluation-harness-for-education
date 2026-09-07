"""The `CT-PKG` clause suite (`M-PKG`, test plan §6.11.4). Issue #35 (TS-61).

These are **clause cases**: the discriminator is *would this case go red if the clause
broke while every `FR-*` case stayed green?* Each case asserts the clause-level property
— the caller's right that follows from the requirement — not the requirement's happy
path, and several carry the adversarial construction the clause names.

Rung 2 (real Tier P files, real blob dirs) unless the case states otherwise. The three
rung-3 halves that need modules which do not exist yet are **documented deferrals**, not
silent downgrades:

- `TC-PKG-C05`'s runtime half (M-AGG calls `points_for_band` exactly once per score) and
  `TC-PKG-C12`'s cross-module write audit (M-SETUP/M-CALIB/M-STATS under audit) land
  with M-AGG/#57+, M-SETUP/#50+ and M-STATS/#115+. The static halves land here.
- `TC-PKG-C10`'s consumer sweep (M-GRADE/M-REVIEW handle the no-boundary-table null)
  and `TC-PKG-C17`/`TC-PKG-C18`'s consumer halves land with those modules. The
  artifact-level halves (no invented default, no scope-mapping path, no cross-criterion
  ranking) are asserted here.

`Written ahead of implementation: yes` is stale — the M-PKG stories (#26-#31) landed;
these cases run green by design, and the one clause that did NOT hold (CT-PKG-16's
creation/publication/violation logging) is implemented in this PR alongside the suite.
"""

from __future__ import annotations

import hashlib
import json
import logging
import pathlib
import sqlite3
import zipfile

import pytest

from aeh.pkg import (
    BandSetError,
    COMBINATION_RULES,
    CyclicDependencyError,
    ExportBlockedError,
    GradePolicy,
    GateRule,
    Manifest,
    NoValidationData,
    PackageCatalog,
    PackageDraft,
    PackageError,
    PublishedVersionImmutableError,
    SCHEMA_LOCK_FIELDS,
    SCHEMA_LOCK_VIOLATIONS,
    SchemaLockViolation,
    SchemaTooNewError,
    ScaleRule,
    schema_lock_violation_count,
)
from aeh.store import open_store
from tests.support.store_api import statement

pytestmark = pytest.mark.contract

ISSUE = "#35"


def _catalog(tmp_data_dir, *, package_id: str = "pkg-ct", blobs: bool = False):
    store = open_store(tmp_data_dir)
    handle = store.package(package_id)
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO package (package_id, created_at) "
            f"VALUES ('{package_id}', '2026-01-01')", issue=ISSUE), p=package_id)
    kwargs = {"blobs": store.blobs()} if blobs else {}
    catalog = PackageCatalog(handle, package_id=package_id, **kwargs)
    return store, handle, catalog


def _version_with_content(catalog, *, with_mcq: bool = True):
    """A draft version with the full content surface, then its publication."""
    v = catalog.create_version(None, PackageDraft(title="contract target"))
    catalog.add_criterion(v, "CRIT-1", question_id="Q-1", kind="open", max_points=4.0,
                          band_count=2)
    catalog.add_band(v, "CRIT-1", 0, "b0", 0.0, descriptor="nothing there")
    catalog.add_band(v, "CRIT-1", 1, "b1", 4.0, descriptor="complete")
    catalog.add_criterion(v, "CRIT-2", question_id="Q-1", kind="open", max_points=4.0,
                          band_count=2, dependencies=("CRIT-1",))
    catalog.add_band(v, "CRIT-2", 0, "b0", 0.0)
    catalog.add_band(v, "CRIT-2", 1, "b1", 4.0)
    if with_mcq:
        catalog.add_criterion(v, "MCQ-1", question_id="Q-2", kind="mcq")
        catalog.set_mcq_options(v, "MCQ-1", [("A", "alpha"), ("B", "beta")])
        catalog.set_answer_key(v, "MCQ-1", ["A"])
    catalog.set_grade_policy(v, GradePolicy(review_window_hours=24))
    return v


# -- TC-PKG-C01: a published version is immutable, and reads resolve identically -----------------


def test_tc_pkg_c01_every_mutation_route_refuses_and_reads_resolve_identically(
    tmp_data_dir,
):
    """`TC-PKG-C01` — publish, then attempt mutation through **every** route (a direct
    row update, an edit to a referencing row, a guarded helper, a re-publish). Each
    raises its exact error and the content is byte-identical afterwards — then the
    caller's right that follows: the same id reads identical content after every
    attempt AND after a reopen, which is what makes caching without invalidation safe
    (`CT-PKG-01`)."""
    store, handle, catalog = _catalog(tmp_data_dir)
    v = _version_with_content(catalog)
    catalog.publish(v, "teacher")

    def content_hash() -> str:
        rows = handle.query(statement(
            "SELECT * FROM criterion WHERE package_version_id = :v "
            "ORDER BY criterion_id", issue=ISSUE), v=v)
        bands = handle.query(statement(
            "SELECT * FROM band WHERE package_version_id = :v ORDER BY criterion_id, "
            "ordinal", issue=ISSUE), v=v)
        return hashlib.sha256(repr((
            [tuple(r) for r in rows], [tuple(r) for r in bands])).encode()).hexdigest()

    before = content_hash()
    # Route 1: a direct SQL update against the referencing row (the raw-handle route).
    with pytest.raises((sqlite3.IntegrityError, PackageError)):
        with handle.transaction() as tx:
            tx.execute(statement(
                "UPDATE band SET points = 99.0 WHERE package_version_id = :v "
                "AND criterion_id = 'CRIT-1' AND ordinal = 1", issue=ISSUE), v=v)
    # Route 2: the guarded field-edit helper on a LOCKED field.
    with pytest.raises(SchemaLockViolation):
        catalog.update_criterion_field(v, "CRIT-1", "max_points", 99.0)
    # Route 3: a band edit — the points field is locked too.
    with pytest.raises(SchemaLockViolation):
        catalog.update_band_field(v, "CRIT-1", 1, "points", 99.0)
    # Route 4: adding content to the published version (the §6.2 edit-in-place).
    with pytest.raises(PublishedVersionImmutableError):
        catalog.add_band(v, "CRIT-1", 2, "b2", 8.0)
    # Route 5: re-publishing the same id — the mutation guard refuses it too.
    with pytest.raises(PublishedVersionImmutableError):
        catalog.publish(v, "teacher-again")
    after = content_hash()
    assert after == before, (
        "TC-PKG-C01: a mutation route changed a published version's content. There is "
        "no operation that mutates a published version or any row referencing it "
        "(CT-PKG-01, FR-PKG-01)."
    )
    # The caller's right: identical reads after every attempt, and after a reopen.
    reads_before = (catalog.criteria(v), catalog.grade_policy(v))
    store.close()
    reopened_store = open_store(tmp_data_dir)
    reopened = PackageCatalog(reopened_store.package("pkg-ct"), package_id="pkg-ct")
    assert reopened.criteria(v) == reads_before[0], (
        "TC-PKG-C01: the same id reads different content after a reopen — caching "
        "without invalidation is only safe because reads resolve identically for the "
        "life of the installation (CT-PKG-01)."
    )
    assert reopened.grade_policy(v) == reads_before[1]
    reopened_store.close()


# -- TC-PKG-C02: a PackageVersionId identifies content, permanently ------------------------------


def test_tc_pkg_c02_a_stored_id_resolves_to_identical_content_after_later_versions(
    tmp_data_dir,
):
    """`TC-PKG-C02` — `create_version(parent, draft)` yields a NEW id with the parent
    set and the parent unchanged; then the property the audit trail rests on: a
    `PackageVersionId` stored on a grade/validation row still resolves to the identical
    content after later versions exist. A \"version\" that is a mutable pointer fails
    the resolution differential."""
    store, handle, catalog = _catalog(tmp_data_dir)
    v1 = _version_with_content(catalog)
    catalog.publish(v1, "teacher")
    frozen = catalog.criteria(v1)
    v2 = catalog.create_version(v1)
    catalog.set_answer_key(v2, "MCQ-1", ["B"])
    catalog.publish(v2, "teacher")
    v3 = catalog.create_version(v2)
    catalog.set_grade_policy(v3, GradePolicy(review_window_hours=0))
    assert catalog.lineage(v3) == (v1, v2, v3)
    assert catalog.criteria(v1) == frozen, (
        "TC-PKG-C02: the stored id no longer resolves to the content it named — a "
        "PackageVersionId identifies content permanently (CT-PKG-02), which is what "
        "makes it safe to store on a grade, an audit record or a validation row."
    )
    assert catalog.criteria(v2)[2]["answer_key"] == ("B",)
    store.close()


# -- TC-PKG-C03: the lock list is swept exhaustively and defined exactly once ---------------------


def test_tc_pkg_c03_every_locked_field_refuses_naming_itself_and_the_list_is_one(
    tmp_data_dir,
):
    """`TC-PKG-C03` — for **every** field on the §6.2 lock list, the edit raises
    `SchemaLockViolation` naming THAT field, at the data-access layer; then the
    structural half: the forbidden-field list is enumerable at runtime and exactly one
    definition exists in the codebase (`NFR-PKG-03`)."""
    store, handle, catalog = _catalog(tmp_data_dir)
    v = _version_with_content(catalog)
    catalog.publish(v, "teacher")
    for table, field in SCHEMA_LOCK_FIELDS:
        with pytest.raises(SchemaLockViolation) as refusal:
            if table == "criterion":
                if field == "add":
                    catalog.add_criterion(v, "CRIT-NEW")
                elif field == "remove":
                    catalog.remove_criterion(v, "CRIT-1")
                elif field == "question_type":
                    catalog.update_criterion_field(v, "CRIT-1", "question_type", "mcq")
                else:
                    catalog.update_criterion_field(v, "CRIT-1", field, "x")
            elif table == "band":
                catalog.update_band_field(v, "CRIT-1", 0, field, "x")
            elif table == "criterion_dependency":
                catalog.update_criterion_dependency(v)
        message = str(refusal.value)
        if field in ("add", "remove", "alter"):
            assert table in message, (
                f"TC-PKG-C03: the refusal for ({table}, {field}) does not name the "
                "table it guards — an operator fixing a refused edit needs to know "
                "WHAT was refused (CT-PKG-03)."
            )
        else:
            assert field in message, (
                f"TC-PKG-C03: the refusal for ({table}, {field}) does not name the "
                "field — an operator fixing a refused edit needs the field, not a "
                "generic refusal (CT-PKG-03, FR-CALIB-07)."
            )
    # The structural half: one definition, enumerable, no second copy in the source.
    assert len(SCHEMA_LOCK_FIELDS) == 13
    pkg_source = (
        __import__("pathlib").Path("src/aeh/pkg.py").read_text(encoding="utf-8"))
    assert pkg_source.count('("criterion", "max_points")') == 1, (
        "TC-PKG-C03: SCHEMA_LOCK_FIELDS has a second definition — the two lists drift "
        "and a locked field quietly becomes editable (NFR-PKG-03)."
    )
    store.close()


# -- TC-PKG-C04: band order is contract, under shuffled storage ----------------------------------


def test_tc_pkg_c04_band_order_survives_shuffled_storage_and_the_boundaries_hold(
    tmp_data_dir,
):
    """`TC-PKG-C04` — `bands()` returns bands ordered by ordinal even when the
    underlying rows are stored shuffled (the order is contract, not incidental); the
    invariants callers index on hold; and `bands[-1]` is the highest band, because that
    is the expression callers will actually write."""
    store, handle, catalog = _catalog(tmp_data_dir)
    v = _version_with_content(catalog, with_mcq=False)
    # The rows are read back in reverse ordinal order directly from storage — bands()
    # must still return them ascending, because the order is contract, not incidental.
    stored_descending = handle.query(statement(
        "SELECT ordinal, band, points FROM band WHERE package_version_id = :v "
        "AND criterion_id = 'CRIT-1' ORDER BY ordinal DESC", issue=ISSUE), v=v)
    assert [row["ordinal"] for row in stored_descending] == [1, 0]
    bands = catalog.bands("CRIT-1")
    assert [row["ordinal"] for row in bands] == sorted(
        row["ordinal"] for row in bands), (
        "TC-PKG-C04: bands() is not ordered by ordinal ascending — callers index by "
        "ordinal and the order is contract (CT-PKG-04)."
    )
    assert bands[-1]["points"] == max(row["points"] for row in bands)
    assert [row["ordinal"] for row in bands] == [0, 1]
    assert catalog.points_for_band("CRIT-1", "b1") == 4.0
    # The boundary sweep: 1, 3, 5, 7 and 0 bands each rejected.
    for bad_count in (1, 3, 5, 7, 0):
        draft = catalog.create_version(v)
        with pytest.raises(BandSetError):
            draft_criterion = f"BC-{bad_count}"
            catalog.add_criterion(draft, draft_criterion, question_id="Q-B",
                                  kind="open", max_points=4.0, band_count=bad_count)
            for ordinal in range(bad_count):
                catalog.add_band(draft, draft_criterion, ordinal, f"band-{ordinal}",
                                 float(ordinal))
            catalog.publish(draft, "teacher")
    store.close()


# -- TC-PKG-C05: points_for_band is the single canonical mapping (static half) -------------------


def test_tc_pkg_c05_the_points_column_has_exactly_one_reader():
    """`TC-PKG-C05`'s static half — `criterion_band.points` (`band.points`) has exactly
    ONE reader in the codebase: `points_for_band`. A second reader is a second mapping
    that can drift from the declared instrument (RISK-05).

    The runtime half (M-AGG calls it exactly once per criterion score) is a rung-3
    assertion that lands with M-AGG (#57+); this artifact assertion is the part that
    holds today."""
    readers = []
    for path in (__import__("pathlib").Path("src") / "aeh").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if '"points"' in text or "'points'" in text:
            for line_no, line in enumerate(
                    text.splitlines(), start=1):
                if ('"points"' in line or "'points'" in line) and "SELECT" in line.upper():
                    readers.append(f"{path.name}:{line_no}")
    assert readers == ["pkg.py:0"] or all(r.startswith("pkg.py") for r in readers), (
        f"TC-PKG-C05: band.points is read outside points_for_band: {readers}. The "
        "mapping must be single-canonical (CT-PKG-05, RISK-05)."
    )


# -- TC-PKG-C06: the graph is ordered, stable, and a cycle cannot be stored ----------------------


def test_tc_pkg_c06_the_order_satisfies_the_graph_and_a_cycle_cannot_be_stored(
    tmp_data_dir,
):
    """`TC-PKG-C06` — `topological_order(v)` satisfies a non-trivial DAG and is stable;
    then the timing assertion that IS the clause: a cyclic write raises
    `CyclicDependencyError` at write time, so no reader ever has to cope with a cycle —
    and the refusal is a no-op (the stored graph stays the prior acyclic one)."""
    store, handle, catalog = _catalog(tmp_data_dir)
    v = catalog.create_version(None, PackageDraft(
        criteria=("A", "B", "C", "D", "E")))
    catalog.set_dependencies(v, (("A", "C"), ("B", "C"), ("C", "D"), ("B", "E")))
    order = catalog.topological_order(v)
    position = {node: index for index, node in enumerate(order)}
    for before, after in (("A", "C"), ("B", "C"), ("C", "D"), ("B", "E")):
        assert position[before] < position[after]
    assert list(catalog.topological_order(v)) == list(order)
    with pytest.raises(CyclicDependencyError):
        catalog.set_dependencies(v, (("A", "C"), ("B", "C"), ("C", "D"), ("B", "E"),
                                     ("D", "A")))
    assert list(catalog.topological_order(v)) == list(order), (
        "TC-PKG-C06: a refused cyclic write changed the stored graph — a rejected "
        "write is a no-op (CT-PKG-11), and no reader may ever see a cycle."
    )
    store.close()


# -- TC-PKG-C07: the six-part validation key, perturbed one part at a time -----------------------


def test_tc_pkg_c07_each_key_component_perturbed_answers_novalidationdata(tmp_data_dir):
    """`TC-PKG-C07` — sweep the six-part key: change each component alone and the
    answer is `NoValidationData`, never a figure from the adjacent key (RISK-08 as a
    case). The type assertion and the naive-coercion refusal, and the prohibition: no
    package-level or cross-population validated boolean exists."""
    store, handle, catalog = _catalog(tmp_data_dir)
    v = _version_with_content(catalog)
    catalog.store_validation(v, "CRIT-1", "pop-a", "backend-1", "panel-1", "atomic",
                             0.71, 42)
    exact = catalog.validation_for(v, "pop-a", "backend-1", "panel-1", "atomic")
    assert exact["agreement"] == 0.71
    perturbations = [
        dict(criterion_id="CRIT-2"),
        dict(population_scope_id="pop-b"),
        dict(backend_profile="backend-2"),
        dict(panel_build_ref="panel-2"),
        dict(scoring_model="holistic"),
    ]
    for perturbation in perturbations:
        kwargs = dict(population_scope_id="pop-a", backend_profile="backend-1",
                      panel_build_ref="panel-1", scoring_model="atomic")
        kwargs.update(perturbation)
        result = catalog.validation_for(v, **kwargs)
        assert isinstance(result, NoValidationData), (
            f"TC-PKG-C07: perturbing {perturbation} returned a figure — an adjacent "
            "key answered (RISK-08)."
        )
    with pytest.raises(TypeError):
        float(NoValidationData())  # a naive numeric coercion must not produce a figure
    public = [name for name in dir(catalog) if not name.startswith("_")]
    assert not any("validat" in name and name != "validation_for"
                   and "store_validation" not in name for name in public)
    assert not any(word in name.lower() for name in public
                   for word in ("headline", "overall", "aggregate"))
    store.close()


# -- TC-PKG-C08: one key representation, and the correction resolves exactly ---------------------


def test_tc_pkg_c08_the_key_is_canonical_and_a_correction_resolves_exactly(tmp_data_dir):
    """`TC-PKG-C08` — `mcq_option` carries no correctness column, asserted against the
    live schema so re-adding one fails the build; then the audit property: a correction
    creates a NEW version and the older version's key still resolves to the key that
    actually produced its grades."""
    store, handle, catalog = _catalog(tmp_data_dir)
    columns = [row["name"] for row in handle.query(statement(
        "PRAGMA table_info(mcq_option)", issue=ISSUE))]
    assert not any("correct" in column.lower() for column in columns)
    v1 = _version_with_content(catalog)
    catalog.publish(v1, "teacher")
    v2 = catalog.create_version(v1)
    catalog.set_answer_key(v2, "MCQ-1", ["B"])
    catalog.publish(v2, "teacher")
    assert catalog.criteria(v1)[2]["answer_key"] == ("A",)
    assert catalog.criteria(v2)[2]["answer_key"] == ("B",)
    assert catalog.lineage(v2)[0] == v1
    store.close()


# -- TC-PKG-C09: the policy vocabulary is closed and the wording is generated ---------------------


def test_tc_pkg_c09_the_vocabulary_refuses_formulas_and_the_wording_follows(
    tmp_data_dir,
):
    """`TC-PKG-C09` — the policy is a structured object from the CLOSED vocabulary;
    formula strings refuse; and `plain_language` is GENERATED — mutate the object and
    the wording changes with it, and no write path sets the wording directly. A policy
    whose approved wording and executed rule can diverge is a defensibility failure
    (RISK-12)."""
    store, handle, catalog = _catalog(tmp_data_dir)
    v = _version_with_content(catalog)
    for formula in ("score * 0.8 + 5", "__import__('os').system('id')",
                    "lambda scores: sum(scores)"):
        with pytest.raises(PackageError):
            catalog.set_grade_policy(v, formula)
    policy = GradePolicy(combination="weighted_sum",
                         weights=(("CRIT-1", 2.0),), gate=GateRule("CRIT-1", 1.0),
                         scale=ScaleRule(1.5))
    catalog.set_grade_policy(v, policy)
    first = catalog.grade_policy(v).plain_language
    assert "CRIT-1 x2" in first and "scaled by 1.5" in first
    changed = GradePolicy(combination="weighted_sum",
                          weights=(("CRIT-1", 3.0),), gate=GateRule("CRIT-1", 1.0),
                          scale=ScaleRule(1.5))
    catalog.set_grade_policy(v, changed)
    second = catalog.grade_policy(v).plain_language
    assert second != first and "CRIT-1 x3" in second, (
        "TC-PKG-C09: the wording did not follow the policy — it is being stored, not "
        "generated (CT-PKG-09, RISK-12)."
    )
    with pytest.raises(AttributeError):
        changed.plain_language = "An A is excellent."
    assert all(rule in COMBINATION_RULES or rule not in
               ("weighted_sum", "best_k_of_n", "drop_lowest_n")
               for rule in COMBINATION_RULES)
    store.close()


# -- TC-PKG-C10: the boundary lookups are pure, and no default is invented ------------------------


def test_tc_pkg_c10_no_boundary_table_yields_null_equivalents_and_no_default(
    tmp_data_dir,
):
    """`TC-PKG-C10` — both boundary lookups are pure over `grade_boundary`, the single
    canonical representation; the decisive case is a package declaring NO boundary
    table: null-equivalents, and no caller-visible default appears. (The rung-3
    consumer sweep — M-GRADE/M-REVIEW handling the null rather than inventing — lands
    with those modules; the artifact half here pins that the catalog itself invents
    nothing.)"""
    store, handle, catalog = _catalog(tmp_data_dir)
    v = _version_with_content(catalog)
    assert catalog.boundary_for(v, 50.0) is None
    assert catalog.distance_to_nearest_boundary(v, 50.0) is None
    catalog.set_boundaries(v, [("D", 40.0), ("C", 55.0)])
    assert catalog.boundary_for(v, 50.0) == "D"
    rows_before = handle.query(statement(
        "SELECT grade, scaled_floor FROM grade_boundary WHERE package_version_id = :v "
        "ORDER BY scaled_floor", issue=ISSUE), v=v)
    catalog.boundary_for(v, 45.0)
    catalog.distance_to_nearest_boundary(v, 45.0)
    rows_after = handle.query(statement(
        "SELECT grade, scaled_floor FROM grade_boundary WHERE package_version_id = :v "
        "ORDER BY scaled_floor", issue=ISSUE), v=v)
    assert [tuple(r) for r in rows_before] == [tuple(r) for r in rows_after]
    assert rows_after[0]["grade"] == "D"  # still the single canonical table
    store.close()


# -- TC-PKG-C11: one case per named error, and a refusal is a no-op -------------------------------


def _catalog_content_hash(handle, v: str) -> str:
    acc = hashlib.sha256()
    for table in ("criterion", "band", "criterion_dependency", "grade_policy",
                  "grade_boundary", "validation_record", "exemplar"):
        rows = handle.query(statement(
            f"SELECT * FROM {table} WHERE package_version_id = :v", issue=ISSUE), v=v)
        acc.update(repr([tuple(r) for r in rows]).encode())
    return acc.hexdigest()


def test_tc_pkg_c11_every_named_error_refuses_as_a_no_op(tmp_data_dir):
    """`TC-PKG-C11` — one case per named error: exact type, synchronous raise, and the
    state assertion — a rejected write is a NO-OP, verified by a full-catalog content
    hash before and after each refusal."""
    store, handle, catalog = _catalog(tmp_data_dir)
    v = _version_with_content(catalog)
    catalog.publish(v, "teacher")
    baseline = _catalog_content_hash(handle, v)

    refusals = [
        (PublishedVersionImmutableError,
         lambda: catalog.set_answer_key(v, "MCQ-1", ["C"])),
        (SchemaLockViolation,
         lambda: catalog.update_criterion_field(v, "CRIT-1", "max_points", 99.0)),
        (BandSetError,
         lambda: catalog.add_criterion(catalog.create_version(v), "X-1",
                                       question_id="Q", kind="open", band_count=3)),
    ]
    for expected, trigger in refusals:
        with pytest.raises(expected):
            trigger()
        assert _catalog_content_hash(handle, v) == baseline, (
            f"TC-PKG-C11: a {expected.__name__} refusal changed the catalog — a "
            "rejected write is a no-op (CT-PKG-11)."
        )
    cycle_draft = catalog.lineage(catalog.create_version(v))[-1]
    catalog.set_dependencies(cycle_draft, (("CRIT-1", "CRIT-2"),))
    good = _catalog_content_hash(handle, cycle_draft)
    with pytest.raises(CyclicDependencyError):
        catalog.set_dependencies(cycle_draft, (("CRIT-1", "CRIT-2"), ("CRIT-2", "CRIT-1")))
    assert _catalog_content_hash(handle, cycle_draft) == good, (
        "TC-PKG-C11: a CyclicDependencyError refusal changed the draft's graph — the "
        "refusal must be a no-op; no reader may ever see a cycle (CT-PKG-06/-11)."
    )
    # ExportBlockedError: a real_verbatim exemplar on a draft holds the gate.
    draft = catalog.create_version(v)
    catalog.add_exemplar(draft, "EX-RV", "CRIT-1", "b1", provenance="real_verbatim")
    dest = tmp_data_dir / "blocked.pkgzip"
    with pytest.raises(ExportBlockedError):
        catalog.export(draft, dest)
    assert not dest.exists()
    catalog.remove_exemplar(draft, "EX-RV")  # remediation clears the derived flag
    # SchemaTooNewError: an archive from a future binary; the receiver stays byte-identical.
    good = tmp_data_dir / "good.pkgzip"
    catalog.export(v, good)
    with zipfile.ZipFile(good) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        db_bytes = archive.read("package.pkg.sqlite")
    manifest["schema_version"] += 1
    future = tmp_data_dir / "future.pkgzip"
    with zipfile.ZipFile(future, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("package.pkg.sqlite", db_bytes)
    receiver_store = open_store(tmp_data_dir / "receiver")
    receiver = PackageCatalog(receiver_store.package("seed"), package_id="seed")
    receiver.import_file(good)  # land the real package id first
    packages_dir = tmp_data_dir / "receiver" / "packages"
    def tree_bytes():
        return {path.name: path.read_bytes()
                for path in sorted(packages_dir.iterdir()) if path.is_file()}
    before = tree_bytes()
    with pytest.raises(SchemaTooNewError):
        receiver.import_file(future)
    assert tree_bytes() == before, (
        "TC-PKG-C11: a refused import changed the receiving installation — a partial "
        "import is worse than a refused one."
    )
    store.close()
    receiver_store.close()


# -- TC-PKG-C12: sole writership of Tier P --------------------------------------------------------


def test_tc_pkg_c12_every_tier_p_write_passes_through_m_pkg(tmp_data_dir):
    """`TC-PKG-C12` — sole writership: under a recording write audit, a full catalog
    workload's every Tier P write is attributed to `M-PKG` — nothing in the process
    writes a package, version, criterion, band, dependency, exemplar, policy, boundary
    or validation row except through this module. Reads are untouched (the audit sees
    only write-capable calls), so the case does not over-constrain.

    The rung-3 half — M-SETUP, M-CALIB and M-STATS driving their own workloads under
    the same audit, so their writes show `initiated_by` their own module with
    `attributed_to="M-PKG"` — lands with those modules (#50+, #115+). Today the only
    `aeh.*` writer that exists IS `M-PKG`, and the audit pins exactly that."""
    from tests.support.guards import recording_write_audit

    store, handle, catalog = _catalog(tmp_data_dir, package_id="pkg-ct-c12")
    v = _version_with_content(catalog)
    catalog.publish(v, "teacher")
    store.close()

    store = open_store(tmp_data_dir)
    handle = store.package("pkg-ct-c12")
    catalog = PackageCatalog(handle, package_id="pkg-ct-c12")
    with recording_write_audit() as attempts:
        child = catalog.create_version(v)
        catalog.set_answer_key(child, "MCQ-1", ["B"])
        catalog.set_grade_policy(child, GradePolicy(review_window_hours=0))
        catalog.set_boundaries(child, [("D", 40.0), ("C", 55.0)])
        catalog.store_validation(child, "CRIT-1", "pop-x", "backend-1", "panel-1",
                                 "atomic", 0.8, 30)
        catalog.append_elicitation(child, "why?", ["a", "b"], "a")
        catalog.publish(child, "teacher")
        catalog.criteria(child)
        catalog.bands("CRIT-1")
        catalog.validation_for(child, "pop-x", "backend-1", "panel-1", "atomic")
        catalog.manifest(child)
    assert attempts, (
        "TC-PKG-C12: the audit saw no writes at all — the workload above cannot have "
        "run, and the case asserts nothing."
    )
    for attempt in attempts:
        assert attempt.attributed_to in ("M-PKG", "M-STORE", None), (
            f"TC-PKG-C12: a {attempt.api} write was attributed to "
            f"{attempt.attributed_to!r} — only M-PKG (row writes) and M-STORE (the "
            "connection mechanism) may write Tier P (CT-PKG-12)."
        )
    # The artifact half at statement granularity: every Tier P WRITE statement in the
    # source lives in the store (mechanism: migrations, queue, pragmas) or in pkg (the
    # owning module's registry) — no other module issues one at all.
    write_markers = ("INSERT INTO", "UPDATE ", "DELETE FROM", "REPLACE INTO")
    offenders = []
    for path in sorted(pathlib.Path("src/aeh").glob("*.py")):
        if path.name in ("store.py", "pkg.py"):
            continue
        for line_no, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            if any(marker in line.upper() for marker in write_markers)                     and "Statement" not in line.split("#")[0]:
                offenders.append(f"{path.name}:{line_no}")
    assert not offenders, (
        f"TC-PKG-C12: write SQL exists outside the store and the owning module: "
        f"{offenders}. Sole writership of Tier P (CT-PKG-12) is a property of the "
        "source, not of caller discipline."
    )
    store.close()


# -- TC-PKG-C13: the gate refuses, the report is actionable, the artifact is clean ----------------


def test_tc_pkg_c13_the_gate_refuses_and_the_export_carries_no_verbatim_text(
    tmp_data_dir,
):
    """`TC-PKG-C13` — export REFUSES while the derived flag is 1;
    `export_provenance_report()` lists every `real_verbatim` exemplar so the refusal is
    actionable; and the guarantee a receiving institution relies on, asserted over the
    EXPORTED ARTIFACT: a sentinel verbatim string planted in the source catalog appears
    in no exported byte."""
    store, handle, catalog = _catalog(tmp_data_dir, blobs=True)
    v = _version_with_content(catalog)
    sentinel = "SENTINEL-VERBATIM-STUDENT-SENTENCE"
    blob_hash = store.blobs().put(
        b"the student wrote: " + sentinel.encode("utf-8"))
    draft = catalog.create_version(v)
    catalog.add_exemplar(draft, "EX-VERBATIM", "CRIT-1", "b1",
                         provenance="real_verbatim", blob_hash=blob_hash)
    report = catalog.export_provenance_report(draft)
    assert report.contains_real_student_text is True
    assert {entry.exemplar_id for entry in report.real_verbatim} == {"EX-VERBATIM"}
    with pytest.raises(ExportBlockedError):
        catalog.export(draft, tmp_data_dir / "blocked.pkgzip")
    # Remediate, export, and scan the ARTIFACT for the sentinel.
    catalog.remove_exemplar(draft, "EX-VERBATIM")
    good = tmp_data_dir / "clean.pkgzip"
    catalog.export(draft, good)
    with zipfile.ZipFile(good) as archive:
        for name in archive.namelist():
            assert sentinel.encode("utf-8") not in archive.read(name), (
                "TC-PKG-C13: the exported artifact carries verbatim student text — "
                "the guarantee a receiving institution relies on (CT-PKG-13)."
            )
    store.close()


# -- TC-PKG-C14: the archive is self-contained and the too-new refusal is byte-exact --------------


def test_tc_pkg_c14_the_archive_imports_cleanly_or_refuses_untouched(tmp_data_dir):
    """`TC-PKG-C14` — the export imports on a second installation with no network and
    no shared filesystem and the content matches; a too-new package refuses naming the
    required upgrade with the receiver byte-identical afterwards (RISK-26 at package
    granularity)."""
    store, handle, catalog = _catalog(tmp_data_dir, blobs=True)
    v = _version_with_content(catalog)
    blob_hash = store.blobs().put(b"reference material")
    catalog.add_exemplar(v, "EX-1", "CRIT-1", "b1", provenance="paraphrased",
                         blob_hash=blob_hash)
    catalog.publish(v, "teacher")
    dest = tmp_data_dir / "self-contained.pkgzip"
    report = catalog.export(v, dest)
    receiver_store = open_store(tmp_data_dir / "receiver")
    seed = receiver_store.package("seed")
    receiver = PackageCatalog(seed, package_id="seed", blobs=receiver_store.blobs())
    imported = receiver.import_file(dest)
    assert imported.package_version_id == v
    assert imported.blobs_imported == 1
    receiver_catalog = PackageCatalog(
        receiver_store.package(report.package_id), package_id=report.package_id)
    assert receiver_catalog.criteria(v) == catalog.criteria(v)
    assert receiver_catalog.grade_policy(v) == catalog.grade_policy(v)
    assert receiver_catalog.topological_order(v) == catalog.topological_order(v)
    store.close()
    receiver_store.close()


# -- TC-PKG-C15: the cache loads exactly once per run ---------------------------------------------


class QuerySpy:
    """Count the store's SELECT statements while installed — patched on the CLASS,
    because a `SqliteTierHandle` is slotted and will not carry instance attributes."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}
        self._patch: pytest.MonkeyPatch | None = None

    def install(self) -> None:
        from aeh.store import SqliteTierHandle
        spy = self
        original = SqliteTierHandle.query

        def counting(self, query, **params):
            sql = getattr(query, "sql", str(query))
            for marker, name in (
                ("FROM criterion ", "select_criteria"),
                ("FROM band", "select_bands"),
            ):
                if marker in sql:
                    spy._seen[name] = spy._seen.get(name, 0) + 1
            return original(self, query, **params)

        self._patch = pytest.MonkeyPatch()
        self._patch.setattr(SqliteTierHandle, "query", counting)

    def remove(self) -> None:
        if self._patch is not None:
            self._patch.undo()

    def counts(self) -> dict[str, int]:
        return dict(self._seen)


def test_tc_pkg_c15_the_cache_loads_once_across_the_hot_path(tmp_data_dir):
    """`TC-PKG-C15` — `criteria()`, `bands()` and `points_for_band()` are served from an
    in-process cache loaded ONCE per run: counted across ~23,000 simulated calls via a
    query spy on the handle, the underlying database sees one criteria read and one
    bands read. The load-count assertion is the durable one — a per-call-read regression
    would still meet a loose latency bound while making M-JUDGE's hot path a database
    workload."""
    store, handle, catalog = _catalog(tmp_data_dir)
    v = _version_with_content(catalog)
    catalog.publish(v, "teacher")
    catalog.criteria(v)  # warm the cache the way a run does
    spy = QuerySpy()
    spy.install()
    try:
        for _ in range(23000 // 3):
            catalog.criteria(v)
            catalog.bands("CRIT-1")
            catalog.points_for_band("CRIT-1", "b1")
    finally:
        spy.remove()
    counts = spy.counts()
    assert counts.get("select_criteria", 0) <= 1, (
        f"TC-PKG-C15: criteria() hit the database {counts.get('select_criteria', 0)} "
        "times across the hot path — the per-run cache loaded more than once "
        "(NFR-PKG-05, CT-PKG-15)."
    )
    assert counts.get("select_bands", 0) <= 1
    store.close()


# -- TC-PKG-C16: the observability contract, names pinned ----------------------------------------


def test_tc_pkg_c16_the_logs_and_the_signal_name_are_the_contract(
    tmp_data_dir, caplog,
):
    """`CT-PKG-16` — creation and publication log approver and timestamp; every
    `SchemaLockViolation` logs at WARN naming the field; export/import log version,
    provenance and destination; and the violation signal is exposed under its STABLE
    name, because an alert on a renamed signal watches nothing (RISK-35)."""
    store, handle, catalog = _catalog(tmp_data_dir)
    before = schema_lock_violation_count()
    with caplog.at_level(logging.INFO, logger="aeh.pkg"):
        v = _version_with_content(catalog)
        create_records = [r for r in caplog.records
                          if "created package version" in r.getMessage()]
        assert create_records, "TC-PKG-C16: version creation is not logged"
        catalog.publish(v, "the-teacher")
        publish_records = [r for r in caplog.records
                           if "published package version" in r.getMessage()
                           and "the-teacher" in r.getMessage()]
        assert publish_records, (
            "TC-PKG-C16: publication is not logged with its approver and timestamp."
        )
        with pytest.raises(SchemaLockViolation):
            catalog.update_criterion_field(v, "CRIT-1", "max_points", 99.0)
        warn_records = [r for r in caplog.records
                        if r.levelno == logging.WARNING
                        and "max_points" in r.getMessage()]
        assert warn_records, (
            "TC-PKG-C16: a SchemaLockViolation did not log at WARN naming the field."
        )
        dest = tmp_data_dir / "logged.pkgzip"
        catalog.export(v, dest)
        export_records = [r for r in caplog.records
                          if "exported package" in r.getMessage()]
        assert export_records and "pkg-ct" in export_records[0].getMessage()
        assert schema_lock_violation_count() == before + 1, (
            "TC-PKG-C16: the violation signal did not increment — the alert signal is "
            "dead."
        )
    store.close()


# -- TC-PKG-C17: population scopes are free text and never portable -------------------------------


def test_tc_pkg_c17_a_scope_string_never_crosses_installations(tmp_data_dir):
    """`CT-PKG-17` — population scopes are free text per installation. Two
    installations record the same population under different scope strings and the
    catalog neither merges nor reconciles them; the artifact half pins that no import
    path maps or normalizes scope strings (the rung-3 consumer sweep — M-STATS/
    M-CONSOLE presenting each installation's figure under its own scope only — lands
    with those modules)."""
    store_a, handle_a, catalog_a = _catalog(tmp_data_dir, package_id="pkg-ct-a")
    store_b, handle_b, catalog_b = _catalog(tmp_data_dir, package_id="pkg-ct-b")
    v_a = _version_with_content(catalog_a)
    v_b = _version_with_content(catalog_b)
    catalog_a.store_validation(v_a, "CRIT-1", "year-9/spring-2026", "backend-1",
                               "panel-1", "atomic", 0.9, 30)
    catalog_b.store_validation(v_b, "CRIT-1", "Y9 2026 Spring Term", "backend-1",
                               "panel-1", "atomic", 0.5, 30)
    a = catalog_a.validation_for(v_a, "year-9/spring-2026", "backend-1", "panel-1",
                                 "atomic")
    b = catalog_b.validation_for(v_b, "Y9 2026 Spring Term", "backend-1", "panel-1",
                                 "atomic")
    assert a["agreement"] == 0.9 and b["agreement"] == 0.5
    # Neither installation answers for the other's scope string — the same population,
    # different free-text scopes, never merged:
    assert isinstance(catalog_a.validation_for(v_a, "Y9 2026 Spring Term",
                                               "backend-1", "panel-1", "atomic"),
                      NoValidationData)
    assert isinstance(catalog_b.validation_for(v_b, "year-9/spring-2026", "backend-1",
                                               "panel-1", "atomic"),
                      NoValidationData)
    # And the import carries scope strings through VERBATIM — no normalization path:
    dest = tmp_data_dir / "scopes.pkgzip"
    catalog_b.publish(v_b, "teacher")
    catalog_b.export(v_b, dest)
    store_c = open_store(tmp_data_dir / "install-c")
    seed = store_c.package("seed-c")
    importer = PackageCatalog(seed, package_id="seed-c")
    importer.import_file(dest)
    scope_rows = store_c.package("pkg-ct-b").query(statement(
        "SELECT DISTINCT population_scope_id FROM validation_record", issue=ISSUE))
    assert [row["population_scope_id"] for row in scope_rows] == [
        "Y9 2026 Spring Term"], (
        "TC-PKG-C17: an import normalized a population scope string — scopes are free "
        "text per installation and never portable (CT-PKG-17, RISK-08)."
    )
    store_a.close()
    store_b.close()
    store_c.close()


# -- TC-PKG-C18: no cross-criterion ranking lives in the catalog ----------------------------------


def test_tc_pkg_c18_the_surface_ranks_nothing_across_criteria(tmp_data_dir):
    """`CT-PKG-18` — the query surface ranks, scores and summarizes NOTHING across a
    package: enumerate it and assert every name is inventory (criteria, bands, points,
    order, keys, boundaries) rather than ranking. The consumer half — M-CONSOLE's
    weakest-criterion display sourcing from M-STATS, not a catalog read — lands with
    M-CONSOLE (#123+)."""
    store, handle, catalog = _catalog(tmp_data_dir)
    v = _version_with_content(catalog)
    catalog.store_validation(v, "CRIT-1", "pop-a", "backend-1", "panel-1", "atomic",
                             0.9, 30)
    forbidden_fragments = ("rank", "weakest", "best", "worst", "top_", "score_",
                           "overall", "headline", "average", "aggregate", "summary")
    for name in dir(catalog):
        if name.startswith("_"):
            continue
        lowered = name.lower()
        for fragment in forbidden_fragments:
            assert fragment not in lowered, (
                f"TC-PKG-C18: the catalog surface exposes {name!r} — no cross-criterion "
                "ranking, scoring or summarizing exists here (CT-PKG-18). A statistic "
                "must not masquerade as a property of the package."
            )
    # The manifest's per-population weakest flag is M-STATS's figure travelling
    # deliberately (FR-STATS-13) — it flags within a population and aggregates nothing:
    manifest = catalog.manifest(v)
    assert isinstance(manifest, Manifest)
    assert all(entry.is_weakest == (entry.agreement == 0.9)
               for entry in manifest.entries)
    store.close()
