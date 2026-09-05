"""The exported package archive does not change shape without a version bump.

Case: `TC-REG-02` (test plan §6.9), `FR-PKG-10`, golden file.

    baseline  The exported package archive for the reference package
    reviewer  The package owner
    grounds   Accepted only with a schema-version bump or a declared export-format change

`FR-PKG-10` promises *"one self-contained file containing the Tier P database and any
referenced blobs, importable on another installation with no network"*, and `CT-PKG-14` adds
that import is all-or-nothing and refuses a schema version above the binary's. An archive is
therefore a **compatibility surface**: a member that quietly stops being written breaks import
on an installation that was exporting fine last month, and nothing else in the suite would
notice.

The golden is a canonical listing rather than the archive bytes — member paths, their
digests, and the declared schema version. Archive containers embed timestamps and compression
parameters, so the raw bytes differ between two exports of identical content, and a baseline
that fails on every run gets deleted within a week. The listing is stable and is what the
requirement is actually about.

**Written ahead of implementation** (§8.2). `export_package` is #31's. Remove the marker —
never the test — when #31 closes, and record the baseline in that PR.
"""

from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from tests.support import corpora
from tests.support.baselines import assert_matches_golden
from tests.support.impl import PKG_MODULE, require

pytestmark = pytest.mark.writtenahead

ISSUE = "#31"
CASE = "TC-REG-02"
GOLDEN = "TC-REG-02/PKG-REF.archive.json"


def _canonical_listing(archive_path) -> bytes:
    """Members, digests and declared schema version — sorted, so order is not the assertion."""
    with zipfile.ZipFile(archive_path) as archive:
        members = sorted(archive.namelist())
        listing = [
            {"name": name, "sha256": hashlib.sha256(archive.read(name)).hexdigest()}
            for name in members
        ]
        manifest = json.loads(archive.read("manifest.json")) if "manifest.json" in members else {}
    payload = {
        "schema_version": manifest.get("schema_version"),
        "package_id": manifest.get("package_id"),
        "member_count": len(listing),
        "members": listing,
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def test_tc_reg_02_the_exported_package_archive_matches_its_baseline(tmp_path):
    """TC-REG-02 — the reference package's archive.

    Oracle: golden file over the archive's canonical listing and per-member digests.
    """
    export_package = require(PKG_MODULE, "export_package", issue=ISSUE)

    package = corpora.reference_package()
    destination = tmp_path / "PKG-REF.aehpkg"
    export_package(package_version=package["package_version"], dest=destination)

    assert destination.exists(), (
        "FR-PKG-10: export produces *one self-contained file*. Nothing was written."
    )
    assert_matches_golden(CASE, GOLDEN, _canonical_listing(destination))
