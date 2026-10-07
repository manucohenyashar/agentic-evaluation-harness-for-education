"""`ConsoleApp`: the console as a headless object over the stores."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .settings import CONSOLE_BIND
from .routes import (
    AUDIT_ROUTES,
    BLOCKING_SCREENS,
    OPERATOR_ROUTES,
    SCREENS,
    SETUP_STEP_SCREENS,
    TEACHER_ROUTES,
)
from .records import GradeRecord
from .app_reads import StoreReadsMixin
from .screens import ScreenRenderingMixin
from .setup_screens import SetupScreensMixin
from .run_screens import RunScreensMixin
from .results_screens import ResultsScreensMixin
from .queues import QueuesMixin
from .controls import ControlActionsMixin
from .effects import DomainEffectsMixin
from .key_correction import KeyCorrectionMixin
from .views import ReadViewsMixin
from .grade_actions import GradeActionsMixin


class ConsoleApp(StoreReadsMixin, ScreenRenderingMixin, SetupScreensMixin, RunScreensMixin, ResultsScreensMixin, QueuesMixin, ControlActionsMixin, DomainEffectsMixin, KeyCorrectionMixin, ReadViewsMixin, GradeActionsMixin):
    """The console as a plain object: read views over the stores plus the enumerated control actions
    (§11.1, §11.8).

    It holds no pipeline state. Every screen is a query and every change is a stored row, so two
    browser tabs on one store see the same thing, and closing the browser changes nothing."""

    def __init__(
        self,
        *,
        store: Any = None,
        provider: Any = None,
        cohort_size: int | None = None,
        student_name: str | None = None,
        blind_labels_collected: int | None = None,
        bind_address: str | None = None,
    ) -> None:
        self._store = store
        self._provider = provider  # held, never called: the console performs no inference
        self._cohort_size = cohort_size
        self._student_name = student_name
        self._blind_labels = blind_labels_collected
        self.bind_address = bind_address or CONSOLE_BIND
        self._audit: list[str] = []
        #: Per-render count of per-ledger reads skipped (`FR-CONSOLE-37`). Thread-local,
        #: not plain instance state: since #366 one `ConsoleApp` serves every request
        #: thread of a real `ThreadingHTTPServer`, so a shared counter would have two
        #: concurrent renders reporting each other's skips.
        self._render_state = threading.local()
        self._held: set[str] = set()
        self._applied: dict[str, tuple[Any, ...]] = {}
        # §7.9/§11.8 life-cycle state the console itself owns: the review windows set per
        # run, the append-only revision history the headless driver settles and amends
        # through, and the provenance-gate outcomes waiting for their validation record.
        self._review_windows: dict[str, float] = {}
        self._grade_ledger: dict[str, list[GradeRecord]] = {}
        self._gate_outcomes: dict[str, str] = {}
        #: "start run"'s server-owned workers, by run id (NFR-CONSOLE-08). Held so a test
        #: or an operator can join one; the thread itself outlives any request.
        self._run_threads: dict[str, Any] = {}
        #: The run configuration "start run" resolves from, set by the serving layer from
        #: its cfg (`ConsoleServer`); `None` resolves from the environment alone.
        self.run_config: dict[str, Any] | None = None

    # -- lifecycle -----------------------------------------------------------------------------------

    def close(self) -> None:
        """Release what this tab holds. The console owns no pipeline state, so closing it changes
        nothing another tab or a restarted console would read (NFR-CONSOLE-03)."""
        self._audit = list(self._audit)

    # -- the coupling seam (NFR-CONSOLE-05) ------------------------------------------------------------

    def read_surface(self) -> tuple[str, ...]:
        """The store tiers this console reads."""
        return ("package tier", "cohort tier", "durable tier")

    def actual_couplings(self) -> tuple[str, ...]:
        """Everything the running console touches: the store tiers it holds handles to. It calls no
        pipeline module and shares no in-process object, so this equals the read surface."""
        return self.read_surface()

    @property
    def _skipped_ledgers(self) -> int:
        return int(getattr(self._render_state, "skipped", 0))

    @_skipped_ledgers.setter
    def _skipped_ledgers(self, value: int) -> None:
        self._render_state.skipped = int(value)

    # -- the screens ---------------------------------------------------------------------------------

    def screens(self) -> dict[str, str]:
        """The thirteen screens and their routes (HLD §11.5)."""
        return dict(SCREENS)

    def blocking_screens(self) -> tuple[str, ...]:
        """The screens that must be completed before a run can start (§11.5), taken from M-SETUP's
        own list of blocking steps (CT-CONSOLE-07, #532). With a real store holding a package, this
        is one entry per blocking step `SetupService.steps()` reports, in its order. With no store
        or no package, the declared default pair is returned."""
        steps = self._setup_blocking_steps()
        if steps is None:
            return tuple(screen for screen in SCREENS if screen in BLOCKING_SCREENS)
        return tuple(SETUP_STEP_SCREENS.get(step_id, step_id) for step_id in steps)

    def _setup_blocking_steps(self) -> tuple[str, ...] | None:
        data_dir = getattr(self._store, "data_dir", None)
        if data_dir is None:
            return None
        packages = sorted(Path(data_dir, "packages").glob("*.pkg.sqlite"))
        if not packages:
            return None
        from aeh.setup import setup_service_for_store

        package_id = packages[0].name.removesuffix(".pkg.sqlite")
        try:
            progress = setup_service_for_store(self._store, package_id).steps()
        except Exception:  # noqa: BLE001 — no readable setup: the declared pair answers
            return None
        return tuple(step.step_id for step in progress.steps if step.blocking)

    def routes(self) -> dict[str, tuple[str, ...]]:
        """The route tables for each role. There is deliberately no login route, because the
        console has no accounts."""
        return {"teacher": TEACHER_ROUTES, "operator": OPERATOR_ROUTES}

    def audit_routes(self) -> tuple[str, ...]:
        """The routes that show the audit screens (CT-CONSOLE-23)."""
        return AUDIT_ROUTES

    def _writes(self) -> tuple[Any, ...]:
        return tuple(getattr(self._store, "writes", ()) or ())

    @staticmethod
    def _write_table(write: Any) -> str:
        payload = getattr(write, "payload", None)
        if isinstance(payload, dict):
            return str(payload.get("table", ""))
        return ""

    @staticmethod
    def _write_value(write: Any, key: str) -> Any:
        payload = getattr(write, "payload", None)
        if isinstance(payload, dict):
            return payload.get(key)
        return None
