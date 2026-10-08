"""How the console app reads the stores: tier handles, catalogs, and cross-cohort reads."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from aeh.pkg import PackageCatalog
from aeh.review import review_service_over

from .errors import ConsoleReadError, _is_schema_fault
from .html import _row_get


class StoreReadsMixin:
    """Reads the stores: tier handles, package catalogs, the review service and cohort files."""

    # -- the read path ---------------------------------------------------------------------------------

    def _tier(self, name: str) -> Any:
        """The handle for one store tier. Opening a real tier creates its file if it is missing,
        and showing a screen must never create a file, so a real store is only asked for tiers that
        already exist on disk. The audit test double has no files, so its handles are always
        returned."""
        if self._store is None:
            return None
        data_dir = getattr(self._store, "data_dir", None)
        if data_dir is not None:
            wanted = {
                "package": Path(data_dir, "packages", "pkg-mconsole.pkg.sqlite"),
                "durable": Path(data_dir, "durable.sqlite"),
                "cohort": Path(data_dir, "cohorts", "c-mconsole.sqlite"),
            }.get(name)
            if wanted is not None and not wanted.exists():
                return None
        if name == "package":
            return self._store.package("pkg-mconsole")
        if name == "durable":
            return self._store.durable()
        return self._store.cohort("c-mconsole")

    def _package_handle_for(self, package_version: str) -> Any:
        """The package-tier handle for the package a version id names (`<package>@<rev>` lives in
        `<package>.pkg.sqlite`). Returns None when that file does not exist on a real store, rather
        than creating it as a side effect of reading. The audit double has no files, so it returns
        its fixed handle."""
        if self._store is None:
            return None
        data_dir = getattr(self._store, "data_dir", None)
        if data_dir is None:
            return self._tier("package")
        package_id = (
            str(package_version or "pkg-unaddressed").rpartition("@")[0] or "pkg-unaddressed"
        )
        if not Path(data_dir, "packages", f"{package_id}.pkg.sqlite").exists():
            return None
        return self._store.package(package_id)

    def _gate_catalog(self, package_version: str) -> Any:
        """The `PackageCatalog` for the package `package_version` names, if its file exists (same
        no-create rule as `_package_handle_for`)."""
        handle = self._package_handle_for(package_version)
        package_id = str(package_version or "").rpartition("@")[0]
        if handle is None or not package_id or getattr(self._store, "data_dir", None) is None:
            return None
        from aeh.pkg import PackageCatalog

        return PackageCatalog(handle, package_id=package_id)

    def _read(self, query: str, log: list[str], **params: Any) -> list[Any]:
        """Run one read-only query on the durable tier and record it in the page's query log.
        Screens only ever read (§11.7)."""
        handle = self._tier("durable")
        if handle is None:
            return []
        log.append(query)
        try:
            return list(handle.query(query, **params))
        except Exception:  # noqa: BLE001 — a read view reports empties, never crashes a page
            return []

    def _read_package(self, query: str, log: list[str], **params: Any) -> list[Any]:
        """Run one read-only query on the package tier."""
        handle = self._tier("package")
        if handle is None:
            return []
        log.append(query)
        try:
            return list(handle.query(query, **params))
        except Exception:  # noqa: BLE001
            return []

    def _cohort_keys(self) -> tuple[str, ...]:
        """The keys of the store's cohort files, sorted: one file per cohort under
        `<data_dir>/cohorts/`, the same files M-GRADE, M-DET and M-ORCH read. A store with no files
        (the audit double) has none."""
        data_dir = getattr(self._store, "data_dir", None)
        if data_dir is None:
            return ()
        return tuple(path.stem for path in Path(data_dir, "cohorts").glob("*.sqlite"))

    def _review_service(self, run_id: str) -> Any:
        """M-REVIEW's service for this run, or None when there is no store.

        The console holds no review state of its own (`CT-CONSOLE-01`): S9's figures are
        `build_queue`'s, and this is the one place the screen reaches for them. A store with
        no `data_dir` is the write-audit double, which has no run to build over.

        Built over the console's OWN store and the cohort files that already exist, not
        through `open_review(data_dir, run_id=...)`. That constructor opens a second store
        and asks it for a cohort keyed by the run id, which CREATES `<run_id>.sqlite` — so
        merely rendering S9 left a file behind and a console open during a run no longer
        left the run identical (`FR-CONSOLE-01`, `TC-CONSOLE-01`'s differential). Reading a
        screen must not write a ledger."""
        keys = self._cohort_keys()
        if not keys:
            return None
        try:
            catalog = self._run_catalog(run_id)
        except Exception:  # noqa: BLE001 — an unreadable package keeps the default scale, as before
            catalog = None
        try:
            return review_service_over(
                self._store, cohort_ids=list(keys), run_id=run_id, catalog=catalog,
            )
        except Exception:  # noqa: BLE001 — a run the service cannot open renders as the double
            return None

    def _run_catalog(self, run_id: str) -> Any:
        """The run's package catalog, set to the run's version, or None (#598).

        Without it M-REVIEW maps bands on its default scale and refuses every band name the
        run's package declares, so the console could neither accept a review item nor record
        a blind label for such a package (FR-CONSOLE-34, CT-PKG-01). Never-create: a package
        whose file is not on disk yields None, and the service falls back as before."""
        data_dir = getattr(self._store, "data_dir", None)
        if data_dir is None or not run_id:
            return None
        rows = self._read_cohort_files(
            "SELECT package_id, package_version_id FROM run WHERE run_id = :run_id",
            [], run_id=str(run_id))
        if not rows:
            return None
        package_id = _row_get(rows[-1], "package_id")
        version = _row_get(rows[-1], "package_version_id")
        if not package_id or not Path(data_dir, "packages", f"{package_id}.pkg.sqlite").exists():
            return None
        from aeh.pkg import PackageCatalog

        catalog = PackageCatalog(self._store.package(str(package_id)), package_id=str(package_id))
        if version:
            catalog.criteria(str(version))  # primes the version the band reads resolve against
        return catalog

    def _read_cohort_files(self, query: str, log: list[str], **params: Any) -> list[Any]:
        """Run a query across every cohort file, the way M-GRADE and M-DET read them. A store with
        no files falls back to the durable handle, so the query is still logged on the double."""
        keys = self._cohort_keys()
        if not keys:
            return self._read(query, log, **params)
        rows: list[Any] = []
        for key in keys:
            handle = self._store.cohort(key)
            log.append(query)
            try:
                rows.extend(list(handle.query(query, **params)))
            except sqlite3.OperationalError as error:
                # `FR-CONSOLE-37` splits the two: a missing table or column is the QUERY's
                # fault and would give the same wrong answer on every other ledger, so it is
                # raised and rendered as a refusal. A locked or unopenable ledger is that
                # ledger's bad luck — the pipeline is probably writing it — and stays
                # skippable, counted. Both arrive as `OperationalError`, so the message is
                # what separates them.
                if _is_schema_fault(error):
                    raise ConsoleReadError(query, f"cohort {key}", error) from error
                self._skipped_ledgers += 1
                continue
            except Exception:  # noqa: BLE001 — one unreadable ledger renders as empty, counted
                self._skipped_ledgers += 1
                continue
        return rows

    # -- #398: every Phase-1 action reaches the module that owns its effect -------------------

    def _run_row(self, run_id: str) -> dict[str, Any] | None:
        """The run's row (cohort, package, version, status) from whichever cohort file holds it."""
        cohort_key = self._cohort_for_run(run_id)
        if cohort_key is None:
            return None
        rows = list(self._store.cohort(cohort_key).query(
            "SELECT run_id, cohort_id, package_id, package_version_id, status, pause_reason "
            "FROM run "
            "WHERE run_id = :run_id", run_id=run_id))
        return dict(rows[0]) if rows else None

    def _catalog(self, package_id: str) -> PackageCatalog:
        return PackageCatalog(self._store.package(package_id), package_id=package_id)

    def _package_of(self, package_version: str) -> str:
        data_dir = getattr(self._store, "data_dir", None)
        if not package_version or data_dir is None:
            return ""
        for path in sorted(Path(data_dir, "packages").glob("*.pkg.sqlite")):
            package_id = path.name.removesuffix(".pkg.sqlite")
            try:
                rows = list(self._store.package(package_id).query(
                    "SELECT package_version_id FROM package_version "
                    "WHERE package_version_id = :v", v=package_version))
            except Exception:  # noqa: BLE001
                continue
            if rows:
                return package_id
        return ""

    def _known_package(self, package_id: str) -> bool:
        """Whether Tier P holds this package. Opening an unknown id would create a file, so an id
        that came from a form is checked first."""
        data_dir = getattr(self._store, "data_dir", None)
        return bool(package_id) and data_dir is not None and Path(
            data_dir, "packages", f"{package_id}.pkg.sqlite").exists()

    def _cohort_for_run(self, run_id: str) -> str | None:
        """The cohort file that holds a run's row, found the same way M-GRADE and M-DET find it."""
        for key in self._cohort_keys():
            handle = self._store.cohort(key)
            try:
                rows = list(
                    handle.query(
                        "SELECT cohort_id FROM run WHERE run_id = :run_id", run_id=run_id
                    )
                )
            except Exception:  # noqa: BLE001
                continue
            if rows:
                return key
        return None
