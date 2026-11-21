"""The run's state machine: create, start, pause, resume and complete."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Mapping

from .constants import _JSON_SEPARATORS
from .errors import RunNotFoundError, RunStateError, WorkLedgerError
from .statements import ORCH_STATEMENTS
from .run_records import (
    decision_engine_record,
    panel_config_json,
    _persisted_run_config,
    _pin_records,
    record_run_start,
    _refuse_profile_switch,
)
from .package_checks import validate_grade_policy
from .settings import REMOTE_PROFILES


class RunLifecycleMixin:
    """Creates runs and moves them through their allowed states."""

    # -- run creation ---------------------------------------------------------------------------

    def create_run(
        self,
        cohort_id: str,
        package_version: str,
        cfg: Any,
        *,
        run_id: str | None = None,
        model_pins: "Mapping[str, Any] | None" = None,
        orch_knobs: Any = None,
        escalation_refs: "tuple[Any, ...]" = (),
    ) -> str:
        """Create the run row and its audit record, and return the run id.

        More detail: `docs/code-notes/orch.md`, section `run_lifecycle.py: RunLifecycleMixin.create_run`.

        `model_pins` (`FR-PIPE-19`) freezes the run's extractor and synthesizer identities
        beside the other provider fields — a mapping of `MODEL_PIN_ROLES` role to
        `ModelRef`. The recorded pin is what `compute_work_id`'s `extractor_version` input
        reads (`_unit` reads it from the run row, so a resumed run keeps its pin) and what
        a later `aeh run` / `aeh recover` validates a fresh flag against. Absent or empty,
        nothing is recorded and the row is byte-identical to its pre-feature shape
        (`NFR-CONF-04`).

        `orch_knobs` (`FR-CONF-36`, `CT-CONF-25`) is M-CONF's `OrchKnobs` — the escalation budget
        and random-arm rate resolved environment > config file > default. Its values are
        recorded in `provider_config`, and the run's budget and random-arm reads use them
        whenever the environment does not set the knob. Absent, nothing is recorded and the
        row is byte-identical to its pre-feature shape.

        `escalation_refs` (FR-PROV-48) are the real models the run's escalation seats past the
        panel dispatch to; the retention gate probes them with the panel, before the run row
        exists. When a probe ran, its cost is recorded in `provider_config` as
        `retention_probe_cost` beside `retention_verified`.
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
        # A remote run starts only once zero-retention routing is confirmed for every build it
        # dispatches to (`FR-PROV-14`, `FR-PROV-48`, `NFR-SYS-03`, `SEC-03`): verified here,
        # before the run row exists, so a refusal leaves nothing behind.
        retention, probe_cost = self._verify_retention_at_start(cfg, tuple(escalation_refs))
        provider_fields: dict[str, Any] = {}
        if retention is not None and probe_cost is not None:
            # "Recorded per run": the confirmed build ids, in the run's frozen snapshot, and
            # what the probe cost (FR-PROV-48).
            provider_fields["retention_verified"] = sorted(
                ref.build_id for ref in retention.confirmed
            )
            provider_fields["retention_probe_cost"] = str(probe_cost)
        if retention is not None and retention.exempt:
            # Owner decision 2026-11-20: the Jev decision model was not confirmed, it was
            # exempt — recorded apart from `retention_verified` so it never reads as kept.
            provider_fields["retention_exempt"] = sorted(
                ref.build_id for ref in retention.exempt
            )
        provider_fields.update(_pin_records(model_pins))
        if orch_knobs is not None:
            provider_fields.update(orch_knobs.to_record())
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
                   else {"decision_engine": decision_engine_record(decision_engine),
                         # FR-AGG-20: the frozen Jev-final rule, read back by `run_handle`
                         # so a resumed run aggregates by the rule it started with.
                         "jev_final_on_accept": bool(
                             getattr(cfg, "jev_final_on_accept", True))}),
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

    def _verify_retention_at_start(
        self, cfg: Any, escalation_refs: "tuple[Any, ...]" = (),
    ) -> "tuple[Any, Any]":
        """Check zero retention for every build the run will dispatch to, at run start, and
        refuse if any cannot be confirmed (FR-PROV-14, widened by FR-PROV-48).

        Answers `(report, probe_cost)`. `(None, None)` for a profile that sends nothing off the
        machine, and when no probe ran (below). On a remote profile (`cloud-hosted`, `dev-ci`)
        every distinct build is probed once, before the run row exists: the panel and the
        escalation judges through the provider seam, the decision model through its own
        provider. A seam without `verify_retention`, or a report that leaves any build
        unconfirmed, raises `RetentionPolicyError` naming the model — the gate is never skipped
        on live traffic, because a skipped check reads as a kept privacy promise.

        One exemption: a Jev decision model (`aeh.prov.retention_exempt`, owner decision
        2026-11-20) is not probed and is returned in the report's `exempt`, never `confirmed`;
        `probe_cost` is then None when nothing else was probed.

        Two declared skips. `HARNESS_RETENTION_PRECHECK=0` skips the probe for a provider that
        is the recorded tier (M-PROV decides which, `retention_precheck_skipped`). And a
        `dev-ci` orchestrator bound to no `InferenceProvider` — no seam, or only a pricing
        seam with no `verify_retention`, as a headless or test caller binds — has nothing to
        ask; every shipped provider has it. `cloud-hosted` still refuses that.
        """
        profile = cfg.backend_profile
        if profile not in REMOTE_PROFILES:
            return None, None
        from aeh.prov import (
            RetentionPolicyError, RetentionReport, retention_exempt, retention_precheck_skipped,
            retention_probe_cost,
        )

        verify = getattr(self._provider, "verify_retention", None)
        if verify is None and profile != "cloud-hosted":
            return None, None
        if verify is None:
            raise RetentionPolicyError(
                f"a {profile} run cannot start: the orchestrator was given no provider "
                "able to verify zero-retention routing (FR-PROV-14), so retention for the "
                f"{len(cfg.panel)} panel members is unconfirmed and nothing was created."
            )
        # Once per distinct build: a build named twice is asked about once.
        judges: dict[str, Any] = {}
        for ref in (*cfg.panel, *escalation_refs):
            judges.setdefault(ref.build_id, ref)
        confirmed: list[Any] = []
        cost = None
        if not retention_precheck_skipped(self._provider):
            asked = tuple(judges.values())
            report = verify(asked)
            confirmed_ids = {ref.build_id for ref in getattr(report, "confirmed", ())}
            unconfirmed = [ref for ref in asked if ref.build_id not in confirmed_ids]
            unconfirmed += list(getattr(report, "unconfirmed", ()) or ())
            if unconfirmed:
                names = "; ".join(f"{ref.provider}:{ref.build_id}" for ref in unconfirmed)
                raise RetentionPolicyError(
                    f"zero-retention routing unconfirmed for the run's models: {names}. A "
                    f"{profile} run does not start until every member is confirmed."
                )
            confirmed.extend(getattr(report, "confirmed", ()))
            cost = retention_probe_cost(self._provider, asked)
        engine = getattr(cfg, "decision_engine", None)
        exempt: tuple[Any, ...] = ()
        if (engine is not None and engine.model.build_id not in judges
                and retention_exempt(engine.model)):
            # Jev decision models are exempt from the zero-retention requirement (owner
            # decision 2026-11-20; `retention_exempt`): not probed, no probe cost, and recorded
            # as exempt beside the confirmed builds — never among them.
            exempt = (engine.model,)
        elif engine is not None and engine.model.build_id not in judges:
            # FR-ORCH-40 / FR-PROV-28: the decision model sends student work off the machine
            # too, so it passes the same fail-closed gate before anything is created. Its own
            # provider answers when one is bound; otherwise the provider seam speaks for it.
            engine_provider = (self._decision_provider
                               if getattr(self._decision_provider, "verify_retention", None)
                               else self._provider)
            if not retention_precheck_skipped(engine_provider):
                engine_report = engine_provider.verify_retention((engine.model,))
                engine_confirmed = {
                    ref.build_id for ref in getattr(engine_report, "confirmed", ())}
                if (engine.model.build_id not in engine_confirmed
                        or getattr(engine_report, "unconfirmed", ())):
                    raise RetentionPolicyError(
                        f"zero-retention routing unconfirmed for the decision model "
                        f"{engine.model.provider}:{engine.model.build_id}. A {profile} run "
                        f"does not start until it is confirmed (FR-PROV-28), and nothing was "
                        f"created."
                    )
                confirmed.append(engine.model)
                cost = (cost or 0) + retention_probe_cost(engine_provider, (engine.model,))
        if cost is None and not exempt:
            return None, None
        # `cost` stays None when no probe ran and only an exemption is to be recorded.
        return RetentionReport(confirmed=tuple(confirmed), unconfirmed=(), exempt=exempt), cost

    # -- resume (FR-ORCH-02) --------------------------------------------------------------------

    # -- the run lifecycle: start, pause, resume (FR-ORCH-15/16/17/25, CT-ORCH-12/13) -----------

    def start(self, run_id: str) -> str:
        """Start a `pending` run: `pending` becomes `running` (FR-ORCH-25).

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
        """Pause a run: write a control row, which the next control-read pass applies.

        More detail: `docs/code-notes/orch.md`, section `run_lifecycle.py: RunLifecycleMixin.pause`.
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
        """Resume work. It takes no arguments on purpose: it finds every open run by itself.

        More detail: `docs/code-notes/orch.md`, section `run_lifecycle.py: RunLifecycleMixin.resume`.
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
        """Read and apply a run's unapplied control rows, oldest first.

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
        """Mark one control row as applied. `applied_at` shows the operator the request was carried
        out, not just recorded."""
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
        """Change a run's state, only along an edge FR-ORCH-25 allows.

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
        """Mark a `running` run `complete` once its last open unit is finished.

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
        """The reason a pause writes on the run row; a pause always says why.

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
        """Whether an unapplied resume request is waiting for this run.

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
        """Record why an already-paused run stays paused, without changing its state.

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
