"""`TC-CONSOLE-79` — a test's backup file is imported from the console.

*Inline regression.* Design delta §3.2.3 names the `.aehpkg` backup as a test's one import path,
and the console's "export/import package" control carried only the export half: a teacher who
downloaded a test's backup from the results screen had no way to bring it into another console.
The import goes through M-PKG's own all-or-nothing `import_file` (FR-PKG-10/13); the console adds
only the transport (the file's bytes in the action's body, never a URL, `CT-CONSOLE-34`).

Arms: (a) a published package's backup imports into an EMPTY data folder — no package yet, so
nothing may be opened just to find the packages directory — and the imported version is the one
exported; (b) importing it again is refused (a package is never overwritten); (c) bytes that are
not an archive, or an archive whose content was altered, are refused and write no package file.
"""

from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path

from aeh.console import build_console
from aeh.pipeline.packages import build_package, read_package_spec
from aeh.pkg import PackageCatalog
from aeh.store import open_store

REPO = Path(__file__).resolve().parents[3]
SAMPLE_SPEC = REPO / "docs" / "live-tests" / "config" / "eng7-read-01.package.toml"


def _backup(tmp_path: Path) -> tuple[bytes, str, str]:
    """The sample English package, published in one store and exported to a backup file."""
    source = open_store(tmp_path / "source")
    try:
        built = build_package(source, read_package_spec(SAMPLE_SPEC))
        dest = tmp_path / "backup.aehpkg"
        PackageCatalog(source.package(built.package_id), package_id=built.package_id,
                       blobs=source.blobs()).export(built.package_version, dest)
        return dest.read_bytes(), built.package_id, built.package_version
    finally:
        source.close()


def _import(store, data: bytes):
    return build_console(store=store).perform(
        "export/import package", content_base64=base64.b64encode(data).decode("ascii"),
        name="backup.aehpkg")


def test_tc_console_79_a_backup_imports_into_an_empty_folder_and_never_overwrites(tmp_path):
    data, package_id, version = _backup(tmp_path)
    target = open_store(tmp_path / "target")
    try:
        packages = Path(target.data_dir, "packages")
        assert not list(packages.glob("*.pkg.sqlite"))
        outcome = _import(target, data)
        assert outcome.dispatched, outcome.detail
        assert version in outcome.detail
        # Exactly the imported package landed: no helper file was opened to find the folder.
        assert [p.name for p in packages.glob("*.pkg.sqlite")] == [f"{package_id}.pkg.sqlite"]
        catalog = PackageCatalog(target.package(package_id), package_id=package_id)
        assert catalog.criteria(version), "the imported version holds no criteria"

        again = _import(target, data)
        assert not again.dispatched
        assert "already exists" in again.detail, again.detail
    finally:
        target.close()


def test_tc_console_79_a_damaged_backup_is_refused_and_writes_nothing(tmp_path):
    data, _package_id, _version = _backup(tmp_path)
    # The same archive with its database's bytes altered: the content hash no longer holds.
    altered = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as original, \
            zipfile.ZipFile(altered, "w") as copy:
        for item in original.infolist():
            body = original.read(item.filename)
            if item.filename == "package.pkg.sqlite":
                body = body[:-1] + bytes([body[-1] ^ 0xFF])
            copy.writestr(item, body)
    target = open_store(tmp_path / "target")
    try:
        for bad in (b"not a zip archive at all", altered.getvalue()):
            outcome = _import(target, bad)
            assert not outcome.dispatched, outcome.detail
            assert "not imported" in outcome.detail, outcome.detail
        assert not list(Path(target.data_dir, "packages").glob("*.pkg.sqlite"))
    finally:
        target.close()
