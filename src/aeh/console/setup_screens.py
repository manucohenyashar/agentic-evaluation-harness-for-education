"""The setup screens: the question inventory and the answer keys."""

from __future__ import annotations

import json
import sqlite3
from html import escape
from pathlib import Path
from typing import Any

from .errors import ConsoleReadError, _is_schema_fault
from .html import _row_get, _section


class SetupScreensMixin:
    """The question-inventory and answer-key screens."""

    # -- S3/S4/S5: setup -----------------------------------------------------------------------------

    def _inventory_target(self, params: dict[str, Any], queries: list[str]) -> Any:
        """The package screen S3 confirms (#599): named by `package_id`, or by a run id (the run's
        package and version). Returns `(catalog, package_id, version_or_None)`; `(None, package_id,
        None)` when the package's file does not exist (showing a screen never creates one); or None
        when nothing is named."""
        data_dir = getattr(self._store, "data_dir", None)
        if data_dir is None:
            return None
        package_id = params.get("package_id")
        version = params.get("package_version_id")
        run_id = params.get("run_id") or params.get("id")
        if not package_id and run_id:
            rows = self._read_cohort_files(
                "SELECT package_id, package_version_id FROM run WHERE run_id = :run_id",
                queries, run_id=str(run_id))
            if rows:
                package_id = _row_get(rows[-1], "package_id")
                version = version or _row_get(rows[-1], "package_version_id")
        if not package_id:
            return None
        if not Path(data_dir, "packages", f"{package_id}.pkg.sqlite").exists():
            return None, str(package_id), None
        from aeh.pkg import PackageCatalog

        catalog = PackageCatalog(self._store.package(str(package_id)), package_id=str(package_id))
        return catalog, str(package_id), version

    def _render_inventory(self, queries: list[str], params: dict[str, Any] | None = None) -> str:
        target = self._inventory_target(params or {}, queries)
        if target is None:
            rows = self._read_package(
                "SELECT question_id, prompt_text FROM question ORDER BY question_id", queries
            )
            count = len(rows)
            editable = ""
        elif target[0] is None:
            # Addressed, but not on this store: say so, never the pinned package's count.
            return _section(
                "blocking",
                "This screen blocks run start until the question inventory is confirmed.",
                f"No package {target[1]} exists on this store, so there is no inventory to "
                "confirm.",
            )
        else:
            catalog, package_id, version = target
            from aeh.pkg import QUESTION_TYPES

            queries.append(f"PackageCatalog({package_id}).draft_version/proposal/questions")
            try:
                # The draft being set up; once published, the latest version's inventory.
                version = version or catalog.draft_version() or catalog.latest_version()
                proposal = catalog.proposal(version) if version else None
                confirmed = catalog.questions(version) if version else ()
            except sqlite3.OperationalError as error:
                # CT-CONSOLE-28: never a count over a table that could not be read.
                if _is_schema_fault(error):
                    raise ConsoleReadError(
                        "PackageCatalog inventory read", f"package {package_id}", error
                    ) from error
                return self._inventory_unread()
            except Exception:  # noqa: BLE001 — one unreadable ledger, counted and said
                return self._inventory_unread()
            entries: list[dict] = []
            if proposal and proposal.get("confirmed_at") is None:
                try:
                    entries = list(json.loads(proposal.get("payload") or "{}").get("entries", ()))
                except (TypeError, ValueError):
                    entries = []
            if entries:
                # HLD §11.5: the proposal is shown as rows the teacher can correct before
                # confirming; confirming is the control action, not this render.
                count = len(entries)
                editable = '<section data-role="proposed-inventory"><h2>Proposed questions</h2><ol>' + "".join(
                    f'<li><label>{escape(str(e.get("question_id", "")))} '
                    f'<input name="prompt_text:{escape(str(e.get("question_id", "")))}" '
                    f'value="{escape(str(e.get("prompt_text", "")))}"></label> '
                    f'<select name="question_type:{escape(str(e.get("question_id", "")))}">'
                    + "".join(
                        f'<option{" selected" if t == e.get("question_type") else ""}>{t}</option>'
                        for t in QUESTION_TYPES)
                    + "</select></li>"
                    for e in entries
                ) + "</ol></section>"
            else:
                count = len(confirmed)
                editable = "".join(
                    f"<p>{escape(str(q.get('question_id', '')))}: "
                    f"{escape(str(q.get('prompt_text', '')))}</p>"
                    for q in confirmed)
        return editable + _section(
            "blocking",
            "This screen blocks run start until the question inventory is confirmed.",
            f"Questions read back from the package: {count}.",
            "Confirming the inventory is a control action; nothing here scores anything.",
        )

    def _inventory_unread(self) -> str:
        """Screen S3 when the package could not be read right now (locked or busy): the screen
        shows no count rather than a wrong one, and the skipped read is counted (FR-CONSOLE-37)."""
        self._skipped_ledgers += 1
        return _section(
            "blocking",
            "This screen blocks run start until the question inventory is confirmed.",
            "The question inventory could not be read just now; no count is shown rather "
            "than one that may be wrong.",
        )

    def _render_answer_keys(self, queries: list[str]) -> str:
        rows = self._read_package(
            "SELECT criterion_id, answer_key FROM criterion ORDER BY criterion_id", queries
        )
        count = len(rows)
        return _section(
            "blocking",
            "This screen blocks run start until the multiple-choice answer keys are supplied.",
            f"Answer keys read back from the package: {count}.",
            "The keys are read back to you before the lock; the lock is M-PKG's.",
        )
