"""The control actions: the enumerated write surface and how each action writes its rows."""

from __future__ import annotations

import contextlib
import json
import uuid
from typing import Any, Callable, Iterator

from .settings import headless_batch_size
from .routes import REPLAY_ROUTES
from .vocabulary import CONSOLE_WRITE_FIELDS, CONTROL_SURFACE_ACTIONS, REVIEW_BANDS
from .queries import _INSERT_RUN_CONTROL, _SELECT_GRADES
from .errors import _RefreshRequired
from .html import _now, _row_get
from .records import ControlOutcome, GradeRecord, _HeldAction
from .write_rows import _rows_for


class ControlActionsMixin:
    """The fifteen control actions and the rows each one writes."""

    def finalize_batch(self, run_id: str = "r-unaddressed", *, actor: str = "operator") -> dict[str, GradeRecord]:
        """Finalize the batch and write the audit line §11.8 requires. The actor is whatever name
        the form supplied, and the console labels it as such, not as a logged-in identity (there
        are no accounts).

        A configured review window delays finalization (`FR-CONSOLE-22`): the batch
        settles with `finalized_at` still unset and every grade marked provisional — the
        window delays the timestamp and never withholds a grade, and the grades export
        normally throughout it (RISK-11).

        With a store attached the settled grades are the store's; with none, the headless
        driver settles a deterministic batch (`headless_batch_size()` submissions) through
        the same revision ledger an amendment writes — a grade the driver settles is
        readable back by submission id, which is what makes the amendment path runnable
        end to end without a store."""
        outcome = self.perform("finalize batch", run_id=run_id, actor=actor)
        on_store = getattr(self._store, "data_dir", None) is not None
        # RISK-47: on a store, a batch M-GRADE refused (or a held action) did not settle, so the
        # audit line and every grade say so. Only the storeless double has no door to refuse.
        settled = outcome.dispatched or not on_store
        if settled:
            self._audit.append(
                f"finalized_by {actor} (actor as supplied by the form, not an authenticated "
                "identity; the console keeps no accounts)"
            )
        else:
            self._audit.append(f"finalize batch not settled for {actor}: {outcome.detail}")
        grades: dict[str, GradeRecord] = {}
        window_open = (
            self._review_window_hours(run_id) not in (None, 0) if on_store
            else self._review_windows.get(run_id) is not None
        )
        if on_store:
            # `#398` (`FR-CONSOLE-34`): the suppressed second `finalize_batch` that stood here
            # is gone. `perform("finalize batch", …)` above already calls M-GRADE's door and
            # already reports a refusal rather than swallowing it, so this call finalized the
            # same run a SECOND time per screen render — which is what made a double-clicked
            # post change `run_metrics` when `FR-CONSOLE-02` says a replay writes nothing.
            #
            # `contextlib.suppress(Exception)` was the worse half: a refusal from the owning
            # module became a screen that rendered as though the batch had settled. The
            # console reports what the door did, and the door is called once: a refused batch
            # returns its grades provisional and writes no `finalized_by` audit line.
            for row in self._read_cohort_files(_SELECT_GRADES, [], run_id=run_id):
                sid = str(_row_get(row, "submission_id"))
                record = GradeRecord(
                    finalized_at=None,
                    revision=_row_get(row, "revision"),
                    bands=(),
                    provisional=window_open or not settled,
                )
                grades[sid] = record
            return grades
        finalized_at = None if window_open else _now()
        for index in range(headless_batch_size()):
            sid = f"s-{index + 1:04d}"
            record = GradeRecord(
                finalized_at=finalized_at,
                revision=1,
                bands=(REVIEW_BANDS[index % len(REVIEW_BANDS)],),
                provisional=window_open,
            )
            grades[sid] = record
            self._grade_ledger.setdefault(sid, []).append(record)
        return grades

    # -- the control surface -----------------------------------------------------------------------------

    def write_surface(self) -> tuple[str, ...]:
        """The names of the fifteen control actions, checked at runtime (FR-CONSOLE-32). Tests
        compare this set exactly, so any undeclared write path shows up."""
        return CONTROL_SURFACE_ACTIONS

    def write_fields(self, action: str) -> tuple[str, ...]:
        """The store fields `action` may write (the Effect column of §11.8)."""
        if action not in CONSOLE_WRITE_FIELDS:
            raise KeyError(f"{action!r} is not one of the fifteen declared control actions")
        return CONSOLE_WRITE_FIELDS[action]

    def control_actions(self) -> dict[str, Callable[..., ControlOutcome]]:
        """The same fifteen actions as callables, each bound to `perform`."""
        return {action: self._bind(action) for action in CONTROL_SURFACE_ACTIONS}

    def _bind(self, action: str) -> Callable[..., ControlOutcome]:
        def _call(**params: Any) -> ControlOutcome:
            return self.perform(action, **params)

        return _call

    @contextlib.contextmanager
    def hold_after(self, stage: str, *, action: str) -> Iterator[_HeldAction]:
        """Pause the named action after `stage`, so tests can simulate a stale screen without
        racing (§3.19). While paused, `perform` writes nothing; `release()` returns the "refused,
        please refresh" outcome. Leaving the `with` block removes the pause."""
        held = _HeldAction(self, action)
        self._held.add(action)
        try:
            yield held
        finally:
            self._held.discard(action)

    def perform(self, action: str, *, replay: str | None = None, **params: Any) -> ControlOutcome:
        """Carry out one control action as stored rows, following §11.8 end to end:

        - a replay through any route writes nothing and reports the already-settled rows
          (`FR-CONSOLE-02`: no additional row, not merely no exception);
        - a held action suspends and writes nothing;
        - otherwise each declared effect is one row carrying only that action's declared
          fields — on the suite's write-audit double as payload dicts, on a real store as
          the row the schema actually admits for it: `pause/resume` as a `run_control`
          row addressed to the run's cohort ledger, which the orchestrator applies on its
          next read (`CT-ORCH-13` — the control queue admits pause and resume rows only,
          orch migration 12's CHECK), the landed domain effects through the module that
          owns them, and quarantine resolution as the S8 close. An action with neither a
          row the schema admits nor a landed owner reports `dispatched=False` with the
          deferral named — never a silent success, never an inert row written for a
          module that never reads it.
        """
        if action not in CONSOLE_WRITE_FIELDS:
            raise KeyError(f"{action!r} is not one of the fifteen declared control actions")
        if replay is not None:
            if replay not in REPLAY_ROUTES:
                raise ValueError(f"unknown replay route {replay!r}")
            settled = self._applied.get(action, ())
            return ControlOutcome(
                rows_written=settled,
                refused=False,
                dispatched=False,
                detail=f"replayed via {replay}: the action was already settled, no additional row",
            )
        if action in self._held:
            return ControlOutcome(
                rows_written=(),
                refused=False,
                dispatched=False,
                detail="held after the read stage; the write stage is suspended",
            )
        rows = _rows_for(action, params)
        try:
            written, detail, dispatched = self._write_rows(action, rows, params)
        except _RefreshRequired as stale:
            return ControlOutcome(rows_written=(), refused=True, refresh_required=True,
                                  dispatched=False, detail=str(stale))
        self._applied[action] = written
        return ControlOutcome(rows_written=written, refused=False, dispatched=dispatched,
                              detail=detail)

    def _write_rows(
        self, action: str, rows: list[tuple[str, dict[str, Any]]], params: dict[str, Any]
    ) -> tuple[tuple[Any, ...], str, bool]:
        """Write one action's rows to the store. Returns the rows written, the message owed to the
        operator, and whether anything was actually dispatched. On the audit double the payload is
        stored with the row. On a real store each write goes to the tier that owns its table, in
        that tier's own transaction, never nested inside another tier's transaction (CT-STORE-03).
        """
        if getattr(self._store, "data_dir", None) is not None:
            return self._write_rows_real(action, rows, params)
        handle = self._tier("durable")
        if handle is None:
            return (), "no store is attached; nothing was written", False
        written: list[Any] = []
        with handle.transaction() as tx:
            if getattr(tx, "execute", None) is None:
                # The write-audit double: the payload arrives with the row, which is what
                # makes the declared-field contract checkable per write.
                for table, fields in rows:
                    payload = {"table": table, **fields}
                    tx.enqueue_write(payload)
                    written.append(payload)
                return tuple(written), "row payload recorded on the write-audit double", True
        return (), "the store's write seam is not the audit double; nothing was written", False

    def _write_rows_real(
        self, action: str, rows: list[tuple[str, dict[str, Any]]], params: dict[str, Any]
    ) -> tuple[tuple[Any, ...], str, bool]:
        """The real-store path: each action writes the row its schema allows, in one tier and one
        transaction, and reports only what actually happened."""
        if action == "pause/resume":
            run_id = str(params.get("run_id") or "")
            if not run_id:
                return (), "pause/resume names no run; nothing was written", False
            cohort_key = self._cohort_for_run(run_id)
            if cohort_key is None:
                return (
                    (),
                    f"no cohort ledger holds run {run_id!r}; nothing was written",
                    False,
                )
            state = str(params.get("state") or params.get("status") or "paused")
            control_action = "resume" if state in ("running", "resumed") else "pause"
            control_id = f"ctl-{uuid.uuid4().hex[:12]}"
            with self._store.cohort(cohort_key).transaction() as cohort_tx:
                cohort_tx.execute(
                    _INSERT_RUN_CONTROL,
                    control_id=control_id,
                    run_id=run_id,
                    action=control_action,
                    reason=json.dumps({"table": rows[0][0], **rows[0][1]}, sort_keys=True),
                    requested_at=_now(),
                )
            return (
                (control_id,),
                f"queued as run_control row {control_id} on the run's cohort ledger; "
                "the orchestrator applies it on its next read (CT-ORCH-13)",
                True,
            )
        detail, dispatched = self._apply_domain_effects(action, params)
        return (), detail, dispatched
