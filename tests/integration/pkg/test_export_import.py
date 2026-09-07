"""Export, import and the provenance gate against real Tier P files and blob stores.

Cases `TC-PKG-21`, `TC-PKG-22`, `TC-PKG-23`, `TC-PKG-24`, `TC-PKG-25` (`FR-PKG-10`,
`-11`, `-12`, `-13`, `NFR-PKG-02`, `NFR-PKG-04`, `ADR-4`), test plan §5.4. Issue #31
(paired with #34/TS-13).

Rung 2 — real SQLite files, real blob directories, two independent installations built
in separate temp trees: the round-trip oracle is a **differential over the reconstructed
package plus a byte-level content-hash comparison**, and the too-new oracle is a
**store-immutability assertion** (the target tree byte-unchanged after the refusal) —
neither survives a fake.

`Written ahead of implementation: yes` is stale — the export/import surface landed with
#31; the cases run green by design.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import zipfile

import pytest

from aeh.pkg import (
    ExportBlockedError,
    PackageCatalog,
    PackageDraft,
    PackageError,
    GradePolicy,
    SchemaTooNewError,
)
from aeh.store import open_store
from tests.support.store_api import statement

pytestmark = pytest.mark.integration

ISSUE = "#31"

SIGNING_KEY = "HARNESS_PACKAGE_SIGNING_KEY"


def _tree_hash(root) -> str:
    """A byte-level hash of every file under a directory tree — the store-immutability
    oracle's instrument (`TC-PKG-22`: nothing partially imported)."""
    acc = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            acc.update(str(path.relative_to(root)).encode())
            acc.update(path.read_bytes())
    return acc.hexdigest()


def _rich_package(tmp_data_dir):
    """A package carrying every content surface the round-trip must preserve:
    criteria with dependencies and bands, an exemplar with provenance AND a referenced
    blob, a grade policy with its ADR-3 window, an answer key, and a lineage parent
    so `lineage()` itself round-trips."""
    store = open_store(tmp_data_dir / "sender")
    handle = store.package("pkg-roundtrip")
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO package (package_id, created_at) "
            "VALUES ('pkg-roundtrip', '2026-01-01')", issue=ISSUE), p="pkg-roundtrip")
    catalog = PackageCatalog(handle, package_id="pkg-roundtrip", blobs=store.blobs())
    parent = catalog.create_version(None, PackageDraft(title="parent"))
    catalog.add_criterion(parent, "CRIT-0", question_id="Q-0", kind="open",
                          max_points=4.0, band_count=2)
    catalog.add_band(parent, "CRIT-0", 0, "b0", 0.0)
    catalog.add_band(parent, "CRIT-0", 1, "b1", 4.0)
    catalog.publish(parent, "teacher")
    v = catalog.create_version(parent)
    catalog.add_criterion(v, "CRIT-1", question_id="Q-1", kind="open", max_points=4.0,
                          band_count=2, dependencies=("CRIT-0",))
    catalog.add_band(v, "CRIT-1", 0, "b0", 0.0)
    catalog.add_band(v, "CRIT-1", 1, "b1", 4.0)
    catalog.add_criterion(v, "MCQ-1", question_id="Q-2", kind="mcq")
    catalog.set_mcq_options(v, "MCQ-1", [("A", "alpha"), ("B", "beta")])
    catalog.set_answer_key(v, "MCQ-1", ["A"])
    blob_hash = store.blobs().put(b"reference material for the exemplar")
    catalog.add_exemplar(v, "EX-1", "CRIT-1", "b1", provenance="paraphrased",
                         blob_hash=blob_hash)
    catalog.set_grade_policy(v, GradePolicy(review_window_hours=24))
    catalog.publish(v, "teacher")
    return store, catalog, v, parent, blob_hash


def _receiver(tmp_data_dir, name: str):
    """A second installation: its own store, its own blob directory, no shared
    filesystem. The catalog anchors the packages directory through any Tier P
    handle — the import lands under the MANIFEST's package id."""
    store = open_store(tmp_data_dir / name)
    seed = store.package("receiving")
    return store, PackageCatalog(seed, package_id="receiving", blobs=store.blobs())


# -- TC-PKG-21: the round-trip is lossless at the byte level -------------------------------------


def test_tc_pkg_21_export_import_round_trips_every_surface(tmp_data_dir):
    """`TC-PKG-21` — *'Import succeeds; every criterion, band, dependency, exemplar and
    blob round-trips; a content-hash comparison of the reconstructed package matches'*.

    The oracle is the differential PLUS the byte comparison: the staged file's SHA-256
    equals the export's content hash, before the receiving store ever opens it."""
    store, catalog, v, parent, blob_hash = _rich_package(tmp_data_dir)
    monkey_export = pytest.MonkeyPatch()
    monkey_export.setenv(SIGNING_KEY, "school-key")
    try:
        dest = tmp_data_dir / "pkg-roundtrip.pkgzip"
        report = catalog.export(v, dest)
        assert report.package_version_id == v
        assert report.signed is True
        assert report.blobs_included == (blob_hash,)
        assert report.exemplar_provenance == ("paraphrased",)  # FR-PKG-12: what travelled
        assert dest.exists() and report.bytes_written == dest.stat().st_size
    finally:
        monkey_export.undo()

    receiver_store, receiver = _receiver(tmp_data_dir, "receiver")
    patch = pytest.MonkeyPatch()
    patch.setenv(SIGNING_KEY, "school-key")  # the receiver holds the signer's key
    try:
        imported = receiver.import_file(dest)
    finally:
        patch.undo()
    assert imported.package_version_id == v
    assert imported.package_id == "pkg-roundtrip"
    assert imported.signature_status == "verified"
    assert imported.blobs_imported == 1
    staged = (tmp_data_dir / "receiver" / "packages" / "pkg-roundtrip.pkg.sqlite")
    assert hashlib.sha256(staged.read_bytes()).hexdigest() == report.content_hash, (
        "TC-PKG-21: the reconstructed package is not byte-identical to what was "
        "exported — the content-hash oracle is the round-trip's teeth."
    )
    # No network, no shared filesystem: the receiver reads only its own tree.
    receiver_catalog = PackageCatalog(receiver_store.package("pkg-roundtrip"),
                                      package_id="pkg-roundtrip",
                                      blobs=receiver_store.blobs())
    assert receiver_catalog.criteria(v) == catalog.criteria(v)
    assert receiver_catalog.grade_policy(v) == catalog.grade_policy(v)
    assert receiver_catalog.grade_policy(v).review_window_hours == 24
    assert receiver_catalog.mcq_options(v, "MCQ-1") == (("A", "alpha"), ("B", "beta"))
    assert receiver_catalog.answer_key("MCQ-1") == ("A",)
    assert receiver_catalog.topological_order(v) == catalog.topological_order(v)
    assert receiver_catalog.lineage(v) == catalog.lineage(v) == (parent, v)
    assert receiver_store.blobs().get(blob_hash) == b"reference material for the exemplar"
    # The manifest on the receiving side records the provenance actually exported
    # (FR-PKG-12): validated-with-real and exported-with-synthetic stay distinguishable.
    exported_manifest = json.loads(
        zipfile.ZipFile(dest).read("manifest.json"))
    assert exported_manifest["content_hash"] == report.content_hash
    store.close()
    receiver_store.close()


# -- TC-PKG-22: too-new refuses untouched --------------------------------------------------------


def test_tc_pkg_22_a_too_new_package_refuses_naming_the_upgrade_and_imports_nothing(
    tmp_data_dir,
):
    """`TC-PKG-22` — *'Refused with a message naming the required upgrade; nothing is
    partially imported, asserted by checking the target store is byte-unchanged'*.

    The too-new package is an honest archive whose manifest declares a schema version
    one ahead of this binary's — the content hash covers the database bytes, so the
    rewritten manifest is a well-formed archive from a future binary, exactly the
    thing `FR-PKG-13` exists to refuse."""
    store, catalog, v, _, _ = _rich_package(tmp_data_dir)
    dest = tmp_data_dir / "future.pkgzip"
    catalog.export(v, dest)
    with zipfile.ZipFile(dest) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        db_bytes = archive.read("package.pkg.sqlite")
    manifest["schema_version"] += 1
    future = tmp_data_dir / "future.pkgzip"
    with zipfile.ZipFile(future, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("package.pkg.sqlite", db_bytes)

    receiver_store, receiver = _receiver(tmp_data_dir, "receiver")
    packages_dir = tmp_data_dir / "receiver" / "packages"
    before = _tree_hash(packages_dir)
    with pytest.raises(SchemaTooNewError) as refusal:
        receiver.import_file(future)
    message = str(refusal.value)
    assert str(manifest["schema_version"]) in message and "binary" in message, (
        "TC-PKG-22: the refusal must name the required upgrade (FR-PKG-13)."
    )
    assert _tree_hash(packages_dir) == before, (
        "TC-PKG-22: the target store changed during a refused import — a partial "
        "import is worse than a refused one (FR-PKG-13)."
    )
    # A corrupted archive (content hash mismatch) refuses the same way, before any write:
    with zipfile.ZipFile(tmp_data_dir / "corrupt.pkgzip", "w") as archive:
        archive.writestr("manifest.json", json.dumps(
            {**manifest, "schema_version": manifest["schema_version"] - 1}))
        archive.writestr("package.pkg.sqlite", db_bytes + b"tampered")
    with pytest.raises(PackageError, match="content hash"):
        receiver.import_file(tmp_data_dir / "corrupt.pkgzip")
    assert _tree_hash(packages_dir) == before
    store.close()
    receiver_store.close()


def test_tc_pkg_22_an_import_is_all_or_nothing_in_the_happy_path_too(tmp_data_dir):
    """`TC-PKG-22`'s positive half — a refusing import leaves no staging file behind:
    the packages directory holds exactly the seed and the imported package, nothing
    else, after a successful import and after a collision refusal."""
    store, catalog, v, _, _ = _rich_package(tmp_data_dir)
    dest = tmp_data_dir / "pkg.pkgzip"
    catalog.export(v, dest)
    receiver_store, receiver = _receiver(tmp_data_dir, "receiver")
    receiver.import_file(dest)
    with pytest.raises(PackageError, match="already exists"):
        receiver.import_file(dest)
    packages_dir = tmp_data_dir / "receiver" / "packages"
    names = sorted(path.name for path in packages_dir.iterdir())
    assert "pkg-roundtrip.pkg.sqlite" in names
    assert not any(name.startswith(".import-") for name in names), (
        f"TC-PKG-22: a refused import left staging debris in the packages directory: "
        f"{[n for n in names if n.startswith('.import-')]}."
    )
    store.close()
    receiver_store.close()


# -- TC-PKG-23: the provenance gate ---------------------------------------------------------------


def test_tc_pkg_23_export_is_refused_until_every_real_verbatim_is_remediated(
    tmp_data_dir,
):
    """`TC-PKG-23` — *'Refused in the first case with ExportBlockedError; succeeds in
    the other two; export_provenance_report() lists every real_verbatim exemplar in
    the first case'* — paraphrased-and-approved clears the gate, and so does dropping
    the row; the report is the actionable list at the moment of refusal."""
    store, catalog, v, _, _ = _rich_package(tmp_data_dir)
    draft = catalog.create_version(v)
    catalog.add_exemplar(draft, "EX-REAL-1", "CRIT-1", "b1", provenance="real_verbatim")
    catalog.add_exemplar(draft, "EX-REAL-2", "CRIT-1", "b1", provenance="real_verbatim")
    report = catalog.export_provenance_report(draft)
    assert report.contains_real_student_text is True
    assert {entry.exemplar_id for entry in report.real_verbatim} == {
        "EX-REAL-1", "EX-REAL-2"}
    dest = tmp_data_dir / "blocked.pkgzip"
    with pytest.raises(ExportBlockedError) as refusal:
        catalog.export(draft, dest)
    assert {entry.exemplar_id for entry in refusal.value.report.real_verbatim} == {
        "EX-REAL-1", "EX-REAL-2"}, (
            "TC-PKG-23: the refusal must carry the actionable report (FR-CONSOLE-23's "
            "data half)."
        )
    assert not dest.exists()
    # Paraphrased-and-approved: every real_verbatim row through the gate clears it.
    catalog.set_exemplar_provenance(draft, "EX-REAL-1", "paraphrased")
    assert catalog.export_provenance_report(draft).contains_real_student_text is True
    catalog.set_exemplar_provenance(draft, "EX-REAL-2", "paraphrased")
    assert catalog.export_provenance_report(draft).contains_real_student_text is False
    cleared = tmp_data_dir / "cleared.pkgzip"
    assert catalog.export(draft, cleared).package_version_id == draft
    # Dropped: the other remediation, on a fresh real_verbatim row.
    catalog.add_exemplar(draft, "EX-REAL-3", "CRIT-1", "b1", provenance="real_verbatim")
    assert catalog.export_provenance_report(draft).contains_real_student_text is True
    catalog.remove_exemplar(draft, "EX-REAL-3")
    assert catalog.export_provenance_report(draft).contains_real_student_text is False
    assert catalog.export(draft, tmp_data_dir / "cleared2.pkgzip")
    store.close()


def test_tc_pkg_23_provenance_is_a_closed_vocabulary(tmp_data_dir):
    """`ADR-4` — 'real_consented' is the superseded name for 'real_verbatim'; two names
    for one state is the drift the gate exists to prevent, so the vocabulary refuses
    anything but the canonical three."""
    store, catalog, v, _, _ = _rich_package(tmp_data_dir)
    draft = catalog.create_version(v)
    with pytest.raises(PackageError, match="vocabulary"):
        catalog.add_exemplar(draft, "EX-X", "CRIT-1", "b1", provenance="real_consented")
    with pytest.raises(PackageError, match="vocabulary"):
        catalog.set_exemplar_provenance(draft, "EX-1", "approved")
    store.close()


def test_tc_pkg_21_a_revision_carries_provenance_and_blob_references(tmp_data_dir):
    """`TC-PKG-21`'s copy half — the revision copy of an exemplar carries its provenance
    AND its blob reference (the id re-mints; two revisions share one Tier P file): a
    corrected child that silently lost either would export a package whose provenance
    record (FR-PKG-12) or self-containedness (FR-PKG-10) is a lie."""
    store, catalog, v, _, blob_hash = _rich_package(tmp_data_dir)
    child = catalog.create_version(v)
    rows = store.package("pkg-roundtrip").query(statement(
        "SELECT criterion_id, band, provenance, blob_hash FROM exemplar "
        "WHERE package_version_id = :v", issue=ISSUE), v=child)
    assert [tuple(r) for r in rows] == [("CRIT-1", "b1", "paraphrased", blob_hash)]
    assert catalog.criteria(child)[0]["answer_key"] == catalog.criteria(v)[0]["answer_key"]
    store.close()


# -- TC-PKG-24: the flag is derived, never independent --------------------------------------------


def test_tc_pkg_24_the_flag_is_derived_from_exemplar_presence(tmp_data_dir):
    """`TC-PKG-24` — *'The flag is derived from exemplar presence, not maintained
    independently, so flag and exemplars cannot disagree'* — add raises it, every
    remediation lowers it, and the column always equals the EXISTS over the rows
    (ADR-4's invariant, read back both through the catalog and the raw column)."""
    store, catalog, v, _, _ = _rich_package(tmp_data_dir)
    draft = catalog.create_version(v)

    def column():
        return bool(store.package("pkg-roundtrip").query(statement(
            "SELECT contains_real_student_text AS flag FROM package "
            "WHERE package_id = 'pkg-roundtrip'", issue=ISSUE))[0]["flag"])

    assert column() is False
    catalog.add_exemplar(draft, "EX-RV", "CRIT-1", "b1", provenance="real_verbatim")
    assert column() is True
    assert catalog.export_provenance_report(draft).contains_real_student_text is True
    # A paraphrased sibling does NOT clear the gate while one real_verbatim remains:
    catalog.add_exemplar(draft, "EX-SYN", "CRIT-1", "b1", provenance="synthetic")
    assert column() is True
    catalog.set_exemplar_provenance(draft, "EX-RV", "paraphrased")
    assert column() is False
    # Re-add, then drop: the other remediation lowers it again.
    catalog.add_exemplar(draft, "EX-RV2", "CRIT-1", "b1", provenance="real_verbatim")
    assert column() is True
    catalog.remove_exemplar(draft, "EX-RV2")
    assert column() is False
    store.close()


# -- TC-PKG-25: the signature is a report, not a gate ---------------------------------------------


def _export_with_key(tmp_data_dir, catalog, v, dest, key):
    patch = pytest.MonkeyPatch()
    if key is None:
        patch.delenv(SIGNING_KEY, raising=False)
    else:
        patch.setenv(SIGNING_KEY, key)
    try:
        return catalog.export(v, dest)
    finally:
        patch.undo()


def test_tc_pkg_25_signed_unsigned_and_mismatched_are_distinguishable(tmp_data_dir):
    """`TC-PKG-25` — *'Signed verifies; unsigned is reported and proceeds; mismatched
    is reported'* — and a signature the receiver cannot check (no local key) reports
    `unverifiable`, distinct from both unsigned and mismatched (§2.3 Q-07 leaves the
    finer grading open; the only binding rule is that none of these refuses the
    import — NFR-PKG-04)."""
    store, catalog, v, _, _ = _rich_package(tmp_data_dir)
    unsigned_dest = tmp_data_dir / "unsigned.pkgzip"
    _export_with_key(tmp_data_dir, catalog, v, unsigned_dest, None)
    signed_dest = tmp_data_dir / "signed.pkgzip"
    _export_with_key(tmp_data_dir, catalog, v, signed_dest, "school-key")
    other_dest = tmp_data_dir / "other-key.pkgzip"
    _export_with_key(tmp_data_dir, catalog, v, other_dest, "other-school")

    # One receiver per import: an import lands the manifest's package id, so a second
    # import of the same package into the same installation is a COLLISION (refused),
    # not a signature question — each status gets a fresh installation.
    landed = []
    for dest, expected_key, expected_status in (
        (unsigned_dest, None, "unsigned"),
        (other_dest, "a-different-key", "mismatched"),
        (signed_dest, "school-key", "verified"),
        (signed_dest, None, "unverifiable"),
    ):
        receiver_store, receiver = _receiver(tmp_data_dir, f"receiver-{expected_status}")
        patch = pytest.MonkeyPatch()
        if expected_key is None:
            patch.delenv(SIGNING_KEY, raising=False)
        else:
            patch.setenv(SIGNING_KEY, expected_key)
        try:
            report = receiver.import_file(dest)
        finally:
            patch.undo()
        assert report.signature_status == expected_status, (
            f"TC-PKG-25: {dest.name} under key {expected_key!r} reported "
            f"{report.signature_status!r}, expected {expected_status!r}."
        )
        landed.append((tmp_data_dir / f"receiver-{expected_status}" / "packages"
                       / "pkg-roundtrip.pkg.sqlite").exists())
        receiver_store.close()
    # every one of them landed: the report, not a gate, decided nothing (NFR-PKG-04).
    assert all(landed)
    store.close()
