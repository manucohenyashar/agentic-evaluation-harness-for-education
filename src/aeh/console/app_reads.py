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
        """The tier handle a render reads through. A real store's accessors *create* the
        tier file when it is missing, and a render must never create one — so a real store
        is consulted only for tiers that exist on disk; the audit double has no
        filesystem, and its handles are virtual."""
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
        """The package-tier handle for the package a version id names — `<package>@<rev>`
        names its file `<package>.pkg.sqlite`. The same never-create rule `_tier` states:
        on a real store a package whose file does not exist yields None rather than
        minting one as a side effect of a read; on a store with no filesystem view (the
        audit double) the pinned handle answers, because there is nothing to create."""
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
        """The `PackageCatalog` of the package `package_version` names, when its file exists
        on this console's store (the same never-create rule as `_package_handle_for`)."""
        handle = self._package_handle_for(package_version)
        package_id = str(package_version or "").rpartition("@")[0]
        if handle is None or not package_id or getattr(self._store, "data_dir", None) is None:
            return None
        from aeh.pkg import PackageCatalog

        return PackageCatalog(handle, package_id=package_id)

    def _read(self, query: str, log: list[str], **params: Any) -> list[Any]:
        """One read-only query against the durable tier, recorded on the page's query
        log. Reads are the whole of what a render does (§11.7: every view is a query)."""
        handle = self._tier("durable")
        if handle is None:
            return []
        log.append(query)
        try:
            return list(handle.query(query, **params))
        except Exception:  # noqa: BLE001 — a read view reports empties, never crashes a page
            return []

    def _read_package(self, query: str, log: list[str], **params: Any) -> list[Any]:
        """One read-only query against the package tier."""
        handle = self._tier("package")
        if handle is None:
            return []
        log.append(query)
        try:
            return list(handle.query(query, **params))
        except Exception:  # noqa: BLE001
            return []

    def _cohort_keys(self) -> tuple[str, ...]:
        """The store's cohort tier keys, in sorted order — the same discovery surface the
        grade, deterministic and orchestrator modules walk: the ledger's own files, one
        per cohort under `<data_dir>/cohorts/`. A store with no filesystem view (the
        audit double) exposes none."""
        data_dir = getattr(self._store, "data_dir", None)
        if data_dir is None:
            return ()
        return tuple(path.stem for path in Path(data_dir, "cohorts").glob("*.sqlite"))

    def _review_service(self, run_id: str) -> Any:
        """`M-REVIEW`'s service over this console's run, or `None` on the storeless double.

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
        """The run's own package catalog, primed at the run's version, or None (#598).

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
        """Read across the cohort tier's files — the layout `M-GRADE` and `M-DET` walk.
        A store with no filesystem view falls back to the durable handle, so the page's
        read path stays observable on the double too."""
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
        """The run row (cohort, package, version, status) from whichever cohort file holds it."""
        cohort_key = self._cohort_for_run(run_id)
        if cohort_key is None:
            return None
        rows = list(self._store.cohort(cohort_key).query(
            "SELECT run_id, cohort_id, package_id, package_version_id, status FROM run "
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
        """Whether Tier P holds this package. Opening an unknown id would CREATE a file
        (the never-create rule `_tier` states), so a form-supplied id is checked first."""
        data_dir = getattr(self._store, "data_dir", None)
        return bool(package_id) and data_dir is not None and Path(
            data_dir, "packages", f"{package_id}.pkg.sqlite").exists()

    def _cohort_for_run(self, run_id: str) -> str | None:
        """Locate the cohort file a run row lives in, the way `M-GRADE` and `M-DET` do."""
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
