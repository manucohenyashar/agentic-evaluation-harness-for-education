"""Rendering a route: the screen dispatcher and the parts every screen shares."""

from __future__ import annotations

import re
from html import escape
from typing import Any

from .settings import CONSOLE_POLL_INTERVAL_MS
from .routes import SCREENS
from .vocabulary import OPTIONAL_SETUP_STEPS
from .errors import ConsoleReadError
from .html import _page
from .setup_prompts import render_setup_step
from .records import PreflightView, RenderedPage
from .surfaces import render_package_catalog, render_preflight


class ScreenRenderingMixin:
    """Renders a route: fills in its parameters and calls the screen."""

    def render(self, route: str, **params: Any) -> RenderedPage:
        """Render one route, filling placeholders from `params`. A missing parameter shows its
        section as empty instead of failing."""
        queries: list[str] = []
        screen, resolved = self._resolve(route, params)
        self._skipped_ledgers = 0
        read_error = ""
        try:
            html = self._render_screen(screen, resolved, queries)
        except ConsoleReadError as refusal:
            # `FR-CONSOLE-37`: the page still renders. What it must not do is render the
            # number it could not read — so the section says it could not be read, and
            # carries no count at all.
            read_error = str(refusal)
            html = _page(
                "This view could not be read",
                '<section data-role="unreadable-view"><p>This view could not be read.</p>'
                f"<p>{escape(read_error)}</p></section>",
            )
        return RenderedPage(
            html=html,
            skipped_ledgers=self._skipped_ledgers,
            read_error=read_error,
            queries=tuple(queries),
            poll_interval_ms=CONSOLE_POLL_INTERVAL_MS if screen == "S7" else None,
        )

    def api_payload(self, route: str, **params: Any) -> dict[str, Any]:
        """The same view as data: the route, its parameters and the queries the render ran. Nothing
        a control row could add is included."""
        page = self.render(route, **params)
        return {
            "route": route,
            "params": dict(params),
            "queries": list(page.queries),
        }

    def _resolve(self, route: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        resolved = dict(params)
        chosen = "S1"
        for screen, template in SCREENS.items():
            if route == template:
                chosen = screen
                break
            pattern = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", template)
            match = re.fullmatch(pattern, route)
            if match:
                chosen = screen
                for key, value in match.groupdict().items():
                    resolved.setdefault(key, value)
                break
        return chosen, resolved

    def _render_screen(self, screen: str, params: dict[str, Any], queries: list[str]) -> str:
        if screen == "S1":
            return _page(
                "Packages",
                render_package_catalog(
                    store=self._store,
                    package_version=params.get("package_version"),
                    population=params.get("population"),
                    queries=queries,
                ),
            )
        if screen == "S2":
            return _page("New package upload", self._render_upload(queries, params))
        if screen == "S3":
            return _page("Confirm the question inventory",
                         self._render_inventory(queries, params))
        if screen == "S4":
            return _page("Supply multiple-choice answer keys", self._render_answer_keys(queries))
        if screen == "S5":
            return _page("Optional setup", self._render_optional(queries))
        if screen == "S6":
            cohort_id = str(params.get("id") or params.get("cohort_id") or "c-unaddressed")
            view = self._cohort_preflight(cohort_id, queries, drift=params.get("drift"))
            return _page(f"Preflight for cohort {cohort_id}", f"<p>{escape(str(view))}</p>")
        if screen == "S7":
            return _page(
                "Run monitor",
                self._render_monitor(str(params.get("id") or params.get("run_id") or "r-unaddressed"), queries),
                poll_interval_ms=CONSOLE_POLL_INTERVAL_MS,
            )
        if screen == "S8":
            return _page("Operator quarantine", self._render_quarantine(queries))
        if screen == "S9":
            return _page(
                "Review queue",
                self._render_review_screen(
                    str(params.get("id") or params.get("run_id") or "r-unaddressed"), queries
                ),
            )
        if screen == "S10":
            return _page("Whole-grade sample", self._render_sample(queries))
        if screen == "S11":
            return _page("Blind sample", self._render_blind(queries))
        if screen == "S12":
            return _page(
                "Class rollup",
                self._render_rollup_screen(
                    str(params.get("id") or params.get("run_id") or "r-unaddressed"), queries
                ),
            )
        if screen == "S14":
            return _page(
                "Export provenance gate",
                self._render_export_gate(queries, params),
            )
        return _page(
            "Student detail",
            self._render_student(str(params.get("ref") or params.get("student_ref") or ""), queries),
        )

    def _render_optional(self, queries: list[str]) -> str:
        # `FR-CONSOLE-35`: the `setup_skip` read that stood here named a table no tier
        # declares, so it could only ever return nothing — and once `_read_cohort_files`
        # stops swallowing `OperationalError` (`FR-CONSOLE-37`) a read like it is a
        # `ConsoleReadError` on a screen that has nothing wrong with it.
        # Invariant 1 (`FR-CONSOLE-06`): each card is a non-blocking prompt with a
        # first-class skip control and the cost of skipping in the same view. The cards
        # render through the module-level step renderer, so the page and the headless
        # step surface cannot drift.
        cards = "".join(render_setup_step(step) for step in OPTIONAL_SETUP_STEPS)
        return (
            '<section data-role="optional-setup"><p>Five optional setup cards; each may be '
            f"skipped, and each skip is its own line in the telemetry.</p>{cards}</section>"
        )

    # -- S6: preflight — the per-gate ladder, the breaker, and what does not withhold ------------------

    def _cohort_preflight(
        self, cohort_id: str, queries: list[str], drift: Any = None
    ) -> PreflightView:
        return render_preflight(
            cohort_id, drift=drift, store=self._store, queries=queries
        )

    # -- S7: the monitor polls the ledger and writes nothing -------------------------------------------

    def _run_status_from_ledger(self) -> str | None:
        """The run's latest status, from the write log the console can see.

        The write log is the ledger: every control row the console has written is in it,
        and the last `run` payload names the status the orchestrator will apply. A fresh
        console over the same store derives the same status — no tab holds any."""
        status = None
        for write in self._writes():
            payload = getattr(write, "payload", None)
            if isinstance(payload, dict) and payload.get("table") == "run" and payload.get("status"):
                status = str(payload["status"])
        return status

    # -- the audit surface ------------------------------------------------------------------------------

    def _render_audit_lines(self) -> str:
        lines = "".join(f"<p>{escape(line)}</p>" for line in self._audit)
        return (
            '<section data-role="audit">'
            + (lines or "<p>No audit records yet.</p>")
            + "</section>"
        )
