"""The teacher's name for a package version (FR-CONSOLE-74).

A version is *"<package> version <n>"*, with ``n = package_version.revision + 1`` counted
from revision 0 — or from revision 1 for a catalog `M-PKG` minted, whose first version is
revision 1 (see `_SELECT_VERSION`). The table has no timestamp of its own. Where a date
helps it is followed by *"(approved <date>)"*, the date read from the version's approval
record (`published_at`, written by `PackageCatalog.publish`) and written the way a
teacher writes it: *"20 Oct 2026"*.

The `<package>@<hash>` form is internal (FR-UI-23): it stays in exports, logs and the API's
id fields, and this module is how the console turns it into words. `version_label_for()`
is the resolver `teacher_text()` takes; `read_version_label()` is the read that refuses an
unknown version — without echoing the id it was given, since an id is not teacher text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from .teacher_text import VERSION_ID_PATTERN

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

#: The version's row, with its package's lowest revision beside it. FR-CONSOLE-74 says
#: ``n = revision + 1`` on the premise that the first version is revision 0 (the column's
#: floor); `M-PKG` in fact mints a package's first version at revision 1
#: (`insert_first_version`), so a literal ``+ 1`` would call the first published test
#: "version 2". Counting from the package's own first revision keeps both readings: a
#: catalog based at 0 reads revisions 0, 1, 5 as versions 1, 2, 6, and M-PKG's first
#: version is "version 1".
_SELECT_VERSION = (
    "SELECT v.revision AS revision, v.published_by AS published_by, "
    "v.published_at AS published_at, "
    "(SELECT MIN(f.revision) FROM package_version AS f "
    " WHERE f.package_id = v.package_id) AS first_revision "
    "FROM package_version AS v WHERE v.package_version_id = :v"
)

#: The refusal for a version this console cannot find. It names no id on purpose.
UNKNOWN_VERSION_DETAIL = (
    "That test version is not in this console's records. Choose the test again from "
    "the list of published tests.")


class UnknownPackageVersion(ValueError):
    """A version id that names no version this console's store holds. A `ValueError`, so
    the API's read path answers it as the caller's 400 with the teacher's sentence."""

    def __init__(self) -> None:
        super().__init__(UNKNOWN_VERSION_DETAIL)


@dataclass(frozen=True)
class PackageVersionLabel:
    """One version, in teacher words: the package name, the version number, and who
    approved it when (both `None` for a version not yet published)."""

    package_id: str
    number: int
    approved_by: str | None = None
    approved_on: str | None = None

    @property
    def version(self) -> str:
        """``"version 1"`` — the label `teacher_text()` puts after the package name."""
        return f"version {self.number}"

    def text(self, *, with_date: bool = False) -> str:
        """``"ENG7-READ-01 version 1"``, or with `with_date` and an approval on record,
        ``"ENG7-READ-01 version 1 (approved 20 Oct 2026)"``."""
        label = f"{self.package_id} {self.version}"
        if with_date and self.approved_on:
            label += f" (approved {self.approved_on})"
        return label


def teacher_date(value: Any) -> str | None:
    """A stored date or timestamp as a teacher writes it — ``"20 Oct 2026"`` — or `None`
    when there is none or it cannot be read. Month names are fixed English, not the
    process locale, so the label is the same on every machine."""
    if isinstance(value, datetime):
        day = value.date()
    elif isinstance(value, date):
        day = value
    elif isinstance(value, str) and value.strip():
        try:
            day = datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
        except ValueError:
            return None
    else:
        return None
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def _package_of(version_id: str) -> str | None:
    match = VERSION_ID_PATTERN.fullmatch(version_id.strip())
    return match.group(1) if match else None


def read_version_label(store: Any, version_id: str) -> PackageVersionLabel:
    """The label of the version `version_id` names, read from its package's catalog.
    Refuses (`UnknownPackageVersion`) a malformed id, a package with no file on disk — the
    read never creates one — and an id the catalog does not hold."""
    package_id = _package_of(str(version_id or ""))
    if package_id is None:
        raise UnknownPackageVersion()
    path_of = getattr(store, "package_path", None)
    if path_of is None or not Path(path_of(package_id)).is_file():
        raise UnknownPackageVersion()
    try:
        rows = store.package(package_id).query(_SELECT_VERSION, v=str(version_id).strip())
    except Exception as error:  # noqa: BLE001 — an unreadable catalog names nothing
        raise UnknownPackageVersion() from error
    if not rows:
        raise UnknownPackageVersion()
    row = rows[0]
    published_by = row["published_by"]
    return PackageVersionLabel(
        package_id=package_id,
        number=int(row["revision"]) - min(int(row["first_revision"]), 1) + 1
        if row["first_revision"] is not None else int(row["revision"]) + 1,
        approved_by=str(published_by) if published_by else None,
        approved_on=teacher_date(row["published_at"]),
    )


def version_label_for(store: Any) -> Callable[[str], str | None]:
    """The resolver `teacher_text()` takes, bound to `store`: a version id in, its
    ``"version <n>"`` label out, or `None` when the store cannot name it. Answers are
    cached for the resolver's life (one response), so a payload that mentions one version
    many times reads its catalog once."""
    cache: dict[str, str | None] = {}

    def resolve(version_id: str) -> str | None:
        if version_id not in cache:
            try:
                cache[version_id] = read_version_label(store, version_id).version
            except UnknownPackageVersion:
                cache[version_id] = None
        return cache[version_id]

    return resolve


__all__ = [
    "PackageVersionLabel",
    "UNKNOWN_VERSION_DETAIL",
    "UnknownPackageVersion",
    "read_version_label",
    "teacher_date",
    "version_label_for",
]
