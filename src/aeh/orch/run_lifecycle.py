"""The run's state machine: create, start, pause, resume and complete."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from .constants import _JSON_SEPARATORS
from .errors import RunNotFoundError, RunStateError, WorkLedgerError
from .statements import ORCH_STATEMENTS
from .run_records import (
    decision_engine_record,
    panel_config_json,
    _persisted_run_config,
    record_run_start,
    _refuse_profile_switch,
)
from .package_checks import validate_grade_policy


class RunLifecycleMixin:
    """Creates runs and moves them through the declared states."""

    # -- run creation ---------------------------------------------------------------------------

    def create_run(
        self,
        cohort_id: str,
        package_version: str,
        cfg: Any,
        *,
        run_id: str | None = None,
    ) -> str:
        """Create the run row and its audit record; return the run id.

        `run_id` is minted as ``run-<uuid4 hex>`` — two runs of the same (cohort, package
        version, config) are *different runs* and must not share work ids, which is why
        `run_id` is a hash input. Keyword override for a caller (or test) that names its
        own. The row is born `status='pending'`; `FR-ORCH-25`'s status transitions are
        control-row territory (#61) and #57 flips none of them.

        `provider_config` is the run's frozen backend snapshot, serialized canonically —
        the HLD's "provider, per-judge model ref, retention setting in force, concurrency
        cap, cost ceiling", every field the audit may one day ask the run to account for.

        The run start is logged here too: exactly one `run_start` line through
        `aeh.conf.log_run_start`, whose returned summary is the one the audit record stores.

        The audit record is written here, on the durable tier, by `record_run_start` —
        the run's configuration is frozen the moment the row exists, and the audit trail
        should not depend on a later story landing. The two writes are two transactions
        on two tiers (a cross-tier transaction is refused by design, `CT-STORE-06`): the
        run row commits first, so a crash between them leaves a run whose audit record
        is absent — visible in the durable tier, and repairable without touching the
        ledger: read the run's id back from the run table and call
        `record_run_start(store, cfg, run_id=<that id>)` to write the missing record.
        Creating the run "again" would mint a second `run_id` and a second audit
        record, which is not a retry. Never a half-written ledger.
        """
        package_id = self._package_id_for(package_version)
        # FR-ORCH-31: the version's own declarations must hang together before the run row
        # exists — beside the retention check below, and for the same reason: a refusal at
        # run start leaves nothing behind.
        from aeh.pkg import PackageCatalog

        validate_grade_policy(
            PackageCatalog(self._store.package(package_id), package_id=package_id),
            package_version,
        )
        if run_id is None:
            run_id = f"run-{uuid.uuid4().hex}"
        decision_engine = getattr(cfg, "decision_engine", None)
        panel_config = panel_config_json(cfg.panel, decision_engine=decision_engine)
        # A `cloud-hosted` run starts only once zero-retention routing is confirmed for every
        # panel member (`FR-PROV-14`, `NFR-SYS-03`, `SEC-03`): verified here, before the run
        # row exists, so a refusal leaves nothing behind.
        retention = self._verify_retention_at_start(cfg)
        provider_fields: dict[str, Any] = {}
        if retention is not None:
            # "Recorded per run": the confirmed build ids, in the run's frozen snapshot.
            provider_fields["retention_verified"] = sorted(
                ref.build_id for ref in retention.confirmed
            )
        provider_config = json.dumps(
            {
                **provider_fields,
                "backend_profile": cfg.backend_profile,
                "panel_build_ref": cfg.panel_build_ref,
                "panel": [ref.build_id for ref in cfg.panel],
                "transcriber": cfg.transcriber.build_id,
                "prompt_template_v": cfg.prompt_template_v,
                "concurrency_ceiling": cfg.concurrency_ceiling,
                "retention_setting": cfg.retention_setting,
                "cost_ceiling": (
                    str(cfg.cost_ceiling) if cfg.cost_ceiling is not None else None
                ),
                "cost_currency": cfg.cost_currency,
                # FR-ORCH-40: recorded only when the engine is on (byte-identical when off).
                **({} if decision_engine is None
                   else {"decision_engine": decision_engine_record(decision_engine)}),
            },
            separators=_JSON_SEPARATORS,
            sort_keys=True,
        )
        handle = self._store.cohort(cohort_id)
        try:
            with handle.transaction() as tx:
                tx.execute(
                    ORCH_STATEMENTS["insert_run"],
                    run_id=run_id,
                    cohort_id=cohort_id,
                    package_version_id=package_version,
                    package_id=package_id,
                    panel_config=panel_config,
                    backend_profile=cfg.backend_profile,
                    provider_config=provider_config,
                    prompt_template_v=cfg.prompt_template_v,
                    # CT-CONF-06 / FR-CONF-15 (#527): the whole frozen RunConfig, in the
                    # serialization `rehydrate_run_config` reads back. Beside, not instead of,
                    # the three columns M-ORCH itself reads (their forms are pinned by
                    # TC-REG-08/09).
                    run_config=_persisted_run_config(cfg),
                )
        except sqlite3.IntegrityError as error:
            # Named, not raw: the two ways this write is refused are caller mistakes
            # worth naming, in the same posture as `RunNotFoundError` — a nonexistent
            # cohort (the run row's FK refuses the write) or an explicit `run_id`
            # already taken. Either way nothing was created and nothing needs cleanup.
            raise WorkLedgerError(
                f"run {run_id!r} was not created for cohort {cohort_id!r}: {error}. "
                "Either the cohort does not exist (create it with ingest first) or the "
                "run id is already taken by an earlier run."
            ) from error
        # The run start is this moment, and only this caller knows it (`log_run_start`'s own
        # docstring): the one structured line is emitted here, once per run, and the audit
        # record stores the very summary the line carried (`FR-CONF-09`, `CT-CONF-13`,
        # `NFR-SYS-11`, OBS-10). Resolution never logs, so a console that resolved on the
        # request path does not produce a second line.
        from aeh.conf import log_run_start

        summary = log_run_start(cfg)
        record_run_start(self._store, cfg, run_id=run_id, summary=summary,
                         recorded_at=self._wall_now())
        return run_id

    def _verify_retention_at_start(self, cfg: Any) -> Any:
        """`FR-PROV-14` at run start, fail-closed.

        `None` for a profile that sends nothing off the machine. For `cloud-hosted`, the
        provider seam's `RetentionReport`, confirmed for every panel member. A missing seam,
        a seam without `verify_retention`, or a report that leaves any member unconfirmed
        raises `RetentionPolicyError` — the gate is never skipped, because a skipped check
        reads as a kept privacy promise.
        """
        if cfg.backend_profile != "cloud-hosted":
            return None
        from aeh.prov import RetentionPolicyError

        verify = getattr(self._provider, "verify_retention", None)
        if verify is None:
            raise RetentionPolicyError(
                "a cloud-hosted run cannot start: the orchestrator was given no provider "
                "able to verify zero-retention routing (FR-PROV-14), so retention for the "
                f"{len(cfg.panel)} panel members is unconfirmed and nothing was created."
            )
        report = verify(tuple(cfg.panel))
        confirmed = {ref.build_id for ref in getattr(report, "confirmed", ())}
        unconfirmed = [ref for ref in cfg.panel if ref.build_id not in confirmed]
        unconfirmed += list(getattr(report, "unconfirmed", ()) or ())
        if unconfirmed:
            names = "; ".join(f"{ref.provider}:{ref.build_id}" for ref in unconfirmed)
            raise RetentionPolicyError(
                f"zero-retention routing unconfirmed for panel members: {names}. A "
                "cloud-hosted run does not start until every member is confirmed."
            )
        engine = getattr(cfg, "decision_engine", None)
        if engine is None:
            return report
        # FR-ORCH-40 / FR-PROV-28: the decision model sends student work off the machine too,
        # so it passes the same fail-closed gate before anything is created. Its own provider
        # answers when one is bound; otherwise the provider seam must speak for it.
        engine_verify = getattr(self._decision_provider, "verify_retention", None) or verify
        engine_report = engine_verify((engine.model,))
        engine_confirmed = {ref.build_id for ref in getattr(engine_report, "confirmed", ())}
        if engine.model.build_id not in engine_confirmed or getattr(engine_report, "unconfirmed", ()):
            raise RetentionPolicyError(
                f"zero-retention routing unconfirmed for the decision model "
                f"{engine.model.provider}:{engine.model.build_id}. A cloud-hosted run does not "
                f"start until it is confirmed (FR-PROV-28), and nothing was created."
            )
        from aeh.prov import RetentionReport

        return RetentionReport(
            confirmed=tuple(getattr(report, "confirmed", ())) + (engine.model,), unconfirmed=())

    # -- resume (FR-ORCH-02) --------------------------------------------------------------------

    # -- the run lifecycle: start, pause, resume (FR-ORCH-15/16/17/25, CT-ORCH-12/13) -----------

    def start(self, run_id: str) -> str:
        """Dispatch a `pending` run: `pending → running` (`FR-ORCH-25`'s declared edge).

        **The estimate precedes dispatch** (`FR-ORCH-15`): before the status flips, the
        run's estimated cost is obtained from the provider seam — the per-unit figures the
        run will actually be dispatched against, summed — and written to the run row, so
        the operator surface can read the figure before a single unit is leased. A run
        with no seam injected (or nothing enumerated yet) displays no estimate: a
        fabricated zero would read as a measured price (`CT-PROV-03`'s principle).

        **A queued pause is honoured at start** (`CT-ORCH-13`): a control row written
        while the orchestrator was not dispatching (a `pause` requested of a `pending`
        run — request ≠ effect) is applied here instead of starting, so the run pauses
        rather than races past a stop someone already asked for. The start that loses to
        a queued pause is not swallowed: the row reads `paused`, with the requester's
        reason, not `running`.

        From any state but `pending` — including `paused` (an operator resumes, never
        re-starts, a paused run: `FR-ORCH-25` declares `paused → running` as resume's
        edge) — this raises `RunStateError` and the row's state stays exactly where it
        was. Returns the status the run row carries after the call.
        """
        cohort, row = self._find_run(run_id)
        if row["status"] != "pending":
            raise RunStateError(
                f"start({run_id[:12]}) refused: the run is '{row['status']}', not "
                "'pending' — FR-ORCH-25's machine declares pending → running as the "
                "start edge and nothing else; resume() un-pauses a paused run."
            )
        # Control rows first: a queued pause outranks the start that honours it
        # (`CT-ORCH-13` — the request was already made; the effect lands now).
        self._apply_control_rows(cohort, run_id, honour_queued_pause=True)
        row = self._run_row(run_id)
        if row["status"] == "paused":
            return "paused"
        # FR-ORCH-15's displayed estimate, before any dispatch.
        estimate = self._run_cost_estimate(cohort, run_id)
        # FR-ORCH-37: when the decision engine's calls are what push the estimate past the
        # run's frozen ceiling, the start is refused before anything is written — the ceiling
        # budgets Jev plus a full LLM fallback. Only when the engine contributes, so an
        # engine-off run keeps today's behaviour exactly (NFR-SYS-14).
        ceiling = self._run_ceiling(row)
        if estimate is not None and ceiling is not None:
            units = cohort.query(ORCH_STATEMENTS["select_run_units_for_estimate"], run_id=run_id)
            decision_part = self._decision_cost_estimate(cohort, run_id, units)
            if decision_part > 0 and estimate > ceiling:
                from aeh.prov import ConfigurationError

                raise ConfigurationError(
                    f"start({run_id[:12]}) refused: the estimate {estimate} (including "
                    f"{decision_part} for decision-engine pre-screens, assuming every seat "
                    f"also falls back to the LLM) exceeds the run's cost ceiling {ceiling} "
                    f"(FR-ORCH-37). Raise the ceiling or start without the decision engine. "
                    f"Nothing was written."
                )
        if estimate is not None:
            with cohort.transaction() as tx:
                tx.execute(
                    ORCH_STATEMENTS["set_run_estimate"],
                    run_id=run_id,
                    cost_estimate=str(estimate),
                )
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["transition_run_started"],
                run_id=run_id,
                started_at=self._wall_now(),
            )
            won = int(tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"])
        if won:
            self._maybe_complete_run(cohort, run_id)
        return "running"

    def pause(
        self, run_id: str, cause: BaseException | str | None = None
    ) -> str:
        """Pause a run: write the **control row**, then let the control-read pass apply it.

        The two-step is the point, not overhead: the control row is the durable request
        (`CT-ORCH-13` — request ≠ effect, the orchestrator reads control rows on its own
        schedule), and applying through the same pass the claim loop reads means a pause
        lands identically whether it was requested a second ago or written while the
        orchestrator was down. On a `running` run the read pass runs immediately and the
        effect is immediate; on a `pending` run the row stays queued and the effect lands
        at the next `start` — a run that has not begun dispatching is not torn down for a
        stop it can simply honour first. An already-`paused` run records the request as
        satisfied (applied at once): the state the request asks for already holds.
        Terminal states (`complete`, `failed`) refuse with `RunStateError` — a stop is
        not a result.

        `cause` is one of `CT-ORCH-12`'s four pause conditions: a `ProviderUnavailableError`
        (`FR-ORCH-16`), a `BuildChangedError` (`FR-ORCH-17`), the cost ceiling (the claim
        pass pauses on its own — it writes a sensed pause naming spend and remaining, never
        calling this), or `None` for an operator request. The rendered reason lands on the
        run row (`pause_reason`) so the operator surface can say *why* the run stopped,
        never just that it did.

        The pause touches lifecycle columns only — never `provider_config`/`panel_config`
        (`FR-ORCH-16`'s resume-same-backend: the backend the run was frozen with is the
        backend it resumes with, because nothing here can change it). Returns the status
        the run row carries after the call.
        """
        cohort, row = self._find_run(run_id)
        status = row["status"]
        if status in ("complete", "failed"):
            raise RunStateError(
                f"pause({run_id[:12]}) refused: the run is '{status}' — a terminal "
                "run keeps its record; a pause is a stop, not a rewrite of history."
            )
        reason = self._pause_reason_text(cause)
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["insert_run_control"],
                control_id=f"control-{uuid.uuid4().hex}",
                run_id=run_id,
                action="pause",
                reason=reason,
                requested_at=self._wall_now(),
            )
        if status == "paused":
            # The requested state already holds: record the request as applied, change
            # nothing. (An operator double-pausing must not manufacture a state flip.)
            with cohort.transaction() as tx:
                tx.execute(
                    ORCH_STATEMENTS["mark_pauses_applied"],
                    applied_at=self._wall_now(),
                    run_id=run_id,
                )
            return "paused"
        # Apply through the control-read pass — immediate on a running run, queued on a
        # pending one (CT-ORCH-13).
        status_after, _queued = self._apply_control_rows(cohort, run_id)
        return status_after

    def resume(self, run_id: str | None = None) -> None:
        """Resume work with **no arguments** — the requirement, not ergonomics.

        With no argument, the open runs are discovered from the ledger itself: every run
        whose status is `pending`, `running` or `paused`, across every cohort file the
        store holds. No side file, no cursor, no operator input — `resume` requires no
        bookkeeping beyond the ledger (`FR-ORCH-02`), and an argument would be a place
        for an operator to be wrong under time pressure.

        Resuming re-enumerates, and re-enumeration is where "skip every unit with
        `status='done'`" is realized: a done unit's `work_id` is already in the ledger,
        `INSERT OR IGNORE` leaves it untouched, and no result is recomputed or duplicated.
        A completed run resumed — by discovery's omission or by explicit id — enumerates
        to a no-op. Invoked when nothing is wrong, it inserts nothing and changes
        nothing: the safe no-op the acceptance criterion asks for.

        **Control rows are both the input and the effect here** (`CT-ORCH-13`): the
        no-argument form reads each open run's unapplied control rows first — a resume
        written while the orchestrator was down flips its paused run back to `running`
        through the same guarded transition an explicit resume uses. **An explicit
        `run_id` is itself written as a control row** — request ≠ effect applies to
        every resume, no-argument or named: the row is the durable request, the read
        pass the effect. On a paused run the pass effects the `paused → running` edge
        (`FR-ORCH-25`) and supersedes the pauses queued before it; on a pending or
        running one the request is vacuous and is marked applied. Either way the resume
        re-binds to nothing and consults no current configuration — the run's frozen
        `provider_config`/`panel_config` are the backend (`FR-ORCH-16`'s
        resume-same-backend is structural: the lifecycle transitions write status
        columns only, so *no code path exists* by which a resume could substitute a
        backend). An operator's pause stays sticky across a restart:
        the no-argument form applies control rows and enumerates but does not auto-unpause
        a run nobody asked to resume — a stop an operator requested outranks a scheduler's
        restart.

        The dispatch half of resume — leasing the pending units to workers — is #58's
        `lease` landing on this same ledger; the ledger half (nothing done is re-run,
        nothing lost, nothing duplicated) is complete here.
        """
        if run_id is not None:
            cohort, row = self._find_run(run_id)
            _refuse_profile_switch(row)
            if row["status"] not in ("complete", "failed"):
                # The explicit resume is a control row like any other (`CT-ORCH-13` —
                # a resume request is effected by WRITING the row and letting the
                # control-read pass apply it, never as an in-request state change;
                # the row is the durable request, `applied_at` the evidence it was
                # honoured). On a paused run the pass effects the `paused → running`
                # edge; on a pending/running one the request is vacuous and is marked
                # applied; either way it supersedes the pauses queued before it.
                with cohort.transaction() as tx:
                    tx.execute(
                        ORCH_STATEMENTS["insert_run_control"],
                        control_id=f"control-{uuid.uuid4().hex}",
                        run_id=run_id,
                        action="resume",
                        reason=None,
                        requested_at=self._wall_now(),
                    )
                status_after, _ = self._apply_control_rows(cohort, run_id)
                if status_after == "running":
                    # The resumed run's last open unit may have closed while it was
                    # paused (completions keep landing; the probe only fires from
                    # `running`) — a resume that opens a finished run completes it.
                    self._maybe_complete_run(cohort, run_id)
            self.enumerate_units(run_id)
            return
        for open_run in self._open_run_ids():
            cohort, row = self._find_run(open_run)
            self._apply_control_rows(cohort, open_run)
            self.enumerate_units(open_run)

    def _apply_control_rows(
        self, cohort: Any, run_id: str, *, honour_queued_pause: bool = False
    ) -> tuple[str, str | None]:
        """Read and apply a run's unapplied control rows, oldest request first.

        Returns `(status, queued_pause_reason)`: the run row's status after application,
        and the reason of a pause still queued on a `pending` run (queued, not dropped —
        `CT-ORCH-13`'s request ≠ effect; the claim pass uses a non-None reason to stop
        dispatching into a run someone has asked to stop, and `start`'s
        `honour_queued_pause=True` call applies it instead of starting).

        **The arms.** A `pause` on a `running` run transitions it to `paused` carrying the
        requester's reason; on a `pending` run it stays queued (unless
        `honour_queued_pause` — `start`'s call — applies it as `pending → paused`); on an
        already-`paused` run it is marked applied (the requested state holds). A `resume`
        on a `paused` run transitions it to `running` and supersedes every pause still
        queued behind it (the latest control intent wins); elsewhere it is vacuous and is
        marked applied so the ledger does not accumulate forever-unapplied rows. Every
        transition is the guarded `UPDATE ... WHERE status = :from_status` whose
        `changes()` decides the win — a concurrent writer's move absorbs the request,
        exactly the claim guard's discipline.
        """
        fresh = cohort.query(ORCH_STATEMENTS["select_run"], run_id=run_id)
        if not fresh:
            raise RunNotFoundError(
                f"no run row named {run_id!r} exists in this cohort ledger."
            )
        controls = cohort.query(
            ORCH_STATEMENTS["select_unapplied_control"], run_id=run_id
        )
        if not controls:
            return fresh[0]["status"], None
        status = fresh[0]["status"]
        queued_reason: str | None = None
        for control in controls:
            action = control["action"]
            reason = control["reason"]
            control_id = control["control_id"]
            if action == "pause":
                if status == "running":
                    if self._transition_run(
                        cohort,
                        run_id,
                        to_status="paused",
                        pause_reason=reason,
                        completed_at=None,
                        from_status="running",
                    ):
                        status = "paused"
                    self._mark_control_applied(cohort, control_id)
                elif status == "pending" and honour_queued_pause:
                    if self._transition_run(
                        cohort,
                        run_id,
                        to_status="paused",
                        pause_reason=reason,
                        completed_at=None,
                        from_status="pending",
                    ):
                        status = "paused"
                    self._mark_control_applied(cohort, control_id)
                elif status == "pending":
                    queued_reason = reason  # stays unapplied: honoured at start
                else:  # already paused — the request is satisfied
                    self._mark_control_applied(cohort, control_id)
            elif action == "resume":
                if status == "paused":
                    if self._transition_run(
                        cohort,
                        run_id,
                        to_status="running",
                        pause_reason=None,
                        completed_at=None,
                        from_status="paused",
                    ):
                        status = "running"
                # The supersede is bounded by request time: a resume supersedes the
                # pauses queued BEFORE it — a pause requested after the resume is a
                # later intent this resume must not consume, and it is honoured at
                # its own pass (controls apply oldest-request-first).
                with cohort.transaction() as tx:
                    tx.execute(
                        ORCH_STATEMENTS["mark_pauses_applied_before"],
                        applied_at=self._wall_now(),
                        run_id=run_id,
                        requested_at=control["requested_at"],
                    )
                queued_reason = None
                # Applied in every arm: the resume was honoured (paused → running)
                # or is vacuous (the run was never paused) — either way the request
                # is resolved, and marking it so is what keeps the ledger from
                # accumulating forever-unapplied rows.
                self._mark_control_applied(cohort, control_id)
        return status, queued_reason

    def _mark_control_applied(self, cohort: Any, control_id: str) -> None:
        """Mark one control row applied (`applied_at` read-back is the operator's
        evidence the request was honoured, not just recorded)."""
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["mark_control_applied"],
                control_id=control_id,
                applied_at=self._wall_now(),
            )

    def _transition_run(
        self,
        cohort: Any,
        run_id: str,
        *,
        to_status: str,
        pause_reason: str | None,
        completed_at: str | None,
        from_status: str,
    ) -> bool:
        """One guarded run-state transition (`FR-ORCH-25`'s edges, nothing else).

        The `WHERE status = :from_status` guard is the same write-time discipline as the
        claim's: two writers racing to move the same run resolve by the row's state at
        write time, and the loser's `changes()` reads zero. Returns whether this caller
        won.
        """
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["transition_run_status"],
                run_id=run_id,
                to_status=to_status,
                pause_reason=pause_reason,
                completed_at=completed_at,
                from_status=from_status,
            )
            return bool(int(tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"]))

    def _maybe_complete_run(self, cohort: Any, run_id: str) -> None:
        """Flip a `running` run to `complete` when its last open unit closed.

        Deliberately **conservative**: the probe only fires from a `running` run that
        holds at least one `work_unit` row and zero open ones (`pending` or `leased`).
        The unit-existence guard keeps a never-enumerated run `running` — a run started
        but not yet enumerated is not complete, it is unpopulated; quarantined units are
        not open (their record stands), so a run whose remainder is quarantined completes
        with that record intact. The probe runs after every won lifecycle write that
        could close the run (a completion, a quarantine, a resume) and is one indexed
        count in the common case.
        """
        rows = cohort.query(ORCH_STATEMENTS["select_run"], run_id=run_id)
        if not rows or rows[0]["status"] != "running":
            return
        if not cohort.query(
            ORCH_STATEMENTS["select_any_work_unit"], run_id=run_id
        ):
            return
        if cohort.query(
            ORCH_STATEMENTS["select_run_open_units"], run_id=run_id
        )[0]["n"]:
            return
        if self._awaiting_aggregation(cohort, run_id):
            return
        self._transition_run(
            cohort,
            run_id,
            to_status="complete",
            pause_reason=None,
            completed_at=self._wall_now(),
            from_status="running",
        )

    @staticmethod
    def _pause_reason_text(cause: BaseException | str | None) -> str:
        """The reason text a pause writes on the run row — always say *why*.

        An operator request (`None`) says so plainly rather than rendering an empty
        string; an exception renders `Type: message` so the operator surface can name
        the condition (`FR-ORCH-16/17`: pause **and alert** — the alert's content is
        this reason); a bare string is taken as given.
        """
        if cause is None:
            return "operator request"
        if isinstance(cause, BaseException):
            return f"{type(cause).__name__}: {cause}"
        return str(cause)

    def has_queued_resume(self, run_id: str) -> bool:
        """Whether an unapplied **resume** request is waiting on this run.

        The distinction a recovery pass depends on. `resume()`'s no-argument form applies
        queued control rows and deliberately never lifts a bare operator pause — "a stop an
        operator requested outranks a scheduler's restart" — but it also re-enumerates every
        open run it discovers, `pending` ones included, which writes work units for a run
        nobody started. An explicit `resume(run_id)` enumerates only the run named, and
        supersedes the pauses before it.

        So a caller that wants the first rule without the second has to know which paused runs
        carry a request, and that is this. Without it a recovery either restarts stopped work
        or enumerates unstarted work; neither is acceptable and both have a case asserting so.
        """
        cohort, _row = self._find_run(run_id)
        return any(
            str(row["action"]) == "resume"
            for row in cohort.query(
                ORCH_STATEMENTS["select_unapplied_control"], run_id=run_id)
        )

    def record_pause_reason(self, run_id: str, cause: "BaseException | str") -> None:
        """Record WHY an already-paused run is staying paused, with no state change.

        `pause()` is the right call to stop a run and the wrong one to annotate a stopped one:
        on a `paused` run it records the request as satisfied and changes nothing, which is
        deliberate. But a run that recovery refuses to resume — a profile switch, say
        (`FR-CONF-15`) — needs the refusal on the row, because an operator who switched
        profiles and found a run stopped reads `pause_reason` to learn why, and a stale
        operator note answers a different question.

        Touches `pause_reason` and nothing else: not the status, not the frozen
        `provider_config`/`panel_config` (`FR-ORCH-16`'s resume-same-backend). A run that is
        not paused is left alone — this annotates, it never stops anything.
        """
        cohort, _row = self._find_run(run_id)
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["update_pause_reason"],
                run_id=run_id, pause_reason=self._pause_reason_text(cause),
            )
