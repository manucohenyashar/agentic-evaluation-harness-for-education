"""The console's doors: record uploads, and start or resume runs on worker threads."""

from __future__ import annotations

from typing import Any, Mapping

from aeh.orch import Orchestrator

from .driver import run_to_completion
from .runtime import _escalation_judge_refs, _open_store, _provider_for
from .decision_engine import _decision_provider_for_run


# --- completion hooks -----------------------------------------------------------------------


def record_upload(store: Any, cohort_id: str, filename: str, blob_ref: str) -> None:
    """Record one uploaded scan part through M-INGEST, for the console (FR-CONSOLE-27). The
    console's declared dependencies include M-PIPE but not M-INGEST, so it goes through here
    (TC-CONSOLE-36). No SQL here."""
    from aeh.ingest import record_upload_part

    record_upload_part(store, cohort_id, filename, blob_ref)


def uploaded_parts(store: Any, cohort_id: str) -> tuple[str, ...]:
    """The cohort's uploaded parts in assembled order, read through M-INGEST (FR-CONSOLE-27)."""
    from aeh.ingest import upload_parts_in_order

    return upload_parts_in_order(store, cohort_id)


class RunAlreadyStartedError(ValueError):
    """`start_run_in_background` was asked to start a run that is no longer `pending`. A repeated
    "start run" (a double-click, a second tab) is refused, because the first request's worker
    already owns the run (FR-CONSOLE-02)."""


def _reapply_frozen_pins(handle: Any, drive_keywords: dict[str, Any]) -> None:
    """Re-apply a run's recorded model pins as drive keywords (FR-PIPE-19).

    A run that froze `model_pins` keeps the identities it froze when it is driven again —
    the same posture `aeh run`'s continuation path re-applies (`cli._applied_pins`). The
    drive keywords win when the caller supplied a ref explicitly (a replay against a
    recorded corpus is that caller's business), and a run with no recorded pins is
    untouched — a console-started run takes the declared defaults (CT-PIPE-14).
    """
    from aeh.conf import ModelRef

    for role, provider, build_id, quantization in handle.model_pins:
        drive_keywords.setdefault(
            role, ModelRef(role=role, provider=provider, build_id=build_id,
                           quantization=quantization))


def _prepare_run(
    store: Any,
    *,
    cohort_id: str,
    package_version_id: str,
    config: Mapping[str, Any],
    run_id: str | None,
    provider: Any,
    allow_running: bool,
    drive_keywords: dict[str, Any],
) -> tuple[str, Any, Any]:
    """Resolve the configuration exactly as `aeh run` does, then create the run, or reuse a
    `pending` run for the same cohort and package version (or the one `run_id` names). A run
    that already left `pending` raises `RunAlreadyStartedError` and nothing is written. Fills
    `drive_keywords` with what `run_to_completion` needs and returns `(run_id, run_config,
    provider)`. Shared by the worker-thread start and the in-process drive."""
    from aeh.conf import resolve_orch_knobs, resolve_run_config

    run_config = resolve_run_config(dict(config), Orchestrator(store).cohort_ref(cohort_id))
    # Built before the run exists and bound to every orchestrator that touches it, exactly as
    # `aeh run` does: `create_run`'s retention gate asks it.
    bound = provider if provider is not None else _provider_for(run_config)
    # The decision provider too, so the retention gate asks it about the decision model rather
    # than falling back to the completion provider (see `cli._run_command`).
    if "decision_provider" not in drive_keywords:
        drive_keywords["decision_provider"] = _decision_provider_for_run(run_config, bound, None)
    # The escalation seats' real models, checked before the run exists (see `cli._run_command`).
    if "judge_refs" not in drive_keywords:
        drive_keywords["judge_refs"] = _escalation_judge_refs(
            config, run_config, Orchestrator(store).cohort_ref(cohort_id), bound)
    orchestrator = Orchestrator(store, provider=bound,
                                decision_provider=drive_keywords["decision_provider"])
    if run_id is None:
        existing = [
            handle for handle in orchestrator.runs()
            if handle.cohort_id == cohort_id and handle.package_version_id == package_version_id
        ]
        pending = [handle for handle in existing if handle.status == "pending"]
        if pending:
            run_id = max(pending, key=lambda h: (h.started_at or "", h.run_id)).run_id
        elif existing:
            latest = max(existing, key=lambda h: (h.started_at or "", h.run_id))
            raise RunAlreadyStartedError(
                f"run {latest.run_id} for cohort {cohort_id!r} and package version "
                f"{package_version_id!r} is already {latest.status}; nothing was started"
            )
        else:
            # FR-CONF-36 / CT-CONF-25: the same resolved budget and random-arm rate `aeh run`
            # records, so a run started here grades by the config file's values.
            # FR-PROV-48: the escalation seats' models are probed for retention with the
            # panel, before the run exists; the worker then does not probe the decision model
            # a second time.
            run_id = orchestrator.create_run(
                cohort_id, package_version_id, run_config,
                orch_knobs=resolve_orch_knobs(config),
                escalation_refs=tuple((drive_keywords["judge_refs"] or {}).values()))
            drive_keywords["retention_checked"] = True
    else:
        status = orchestrator.run_handle(run_id).status
        if status != "pending" and not (allow_running and status == "running"):
            raise RunAlreadyStartedError(
                f"run {run_id} is already {status}; nothing was started")
    # The run this call drives may be one an earlier process pinned (`FR-PIPE-19`): a
    # CLI-created pinned run the console picks up, or one resumed after a restart. Driving
    # it without its frozen identities would extract with the declared default instead of
    # the build the run froze. A fresh create_run records no pins, so the re-apply is a
    # no-op there.
    _reapply_frozen_pins(orchestrator.run_handle(run_id), drive_keywords)
    return run_id, run_config, bound


def start_run_in_background(
    store: Any,
    *,
    cohort_id: str,
    package_version_id: str,
    config: Mapping[str, Any],
    run_id: str | None = None,
    thread_name: str = "aeh-run",
    provider: Any = None,
    allow_running: bool = False,
    **drive_keywords: Any,
) -> tuple[str, Any]:
    """Start a run on a worker thread: the console's "start run" action (FR-CONSOLE-34,
    NFR-CONSOLE-08).

    Synchronously, on the caller's store: resolve the run configuration exactly as
    `aeh run` does, then create the run, or reuse a `pending` run for the same cohort and
    package version (or the one `run_id` names). A run that already left `pending`
    raises `RunAlreadyStartedError` and nothing is written.

    Then return at once, with the run driven on a **server-owned worker thread** that
    opens its own store at the same data directory (SQLite connections belong to their
    thread): `start` if still pending, then `run_to_completion`. A failure inside the
    worker is recorded on the run as its pause reason (`Orchestrator.record_pause_reason`),
    never swallowed. Closing the browser does not stop the worker, and killing the server
    leaves the run resumable by `recover` (`NFR-CONSOLE-03`).

    `provider` and `drive_keywords` pass through to `run_to_completion` (a replay against
    a recorded corpus supplies its refs this way); by default the provider is the one the
    resolved profile names, as `aeh run` builds it.

    Returns `(run_id, thread)`. The thread is a daemon: a server that exits does not wait
    on it, and `recover` is what continues an interrupted run."""
    import threading

    run_id, run_config, bound = _prepare_run(
        store, cohort_id=cohort_id, package_version_id=package_version_id, config=config,
        run_id=run_id, provider=provider, allow_running=allow_running,
        drive_keywords=drive_keywords)
    data_dir = getattr(store, "data_dir", None)
    if data_dir is None:
        raise ValueError("start_run_in_background needs a store with a data_dir")
    started = run_id

    def _drive() -> None:
        worker_store = _open_store(data_dir)
        try:
            worker = Orchestrator(worker_store, provider=bound,
                                  decision_provider=drive_keywords["decision_provider"])
            try:
                if worker.run_handle(started).status == "pending":
                    worker.start(started)
                run_to_completion(
                    worker_store, started,
                    provider=bound,
                    run_config=run_config, **drive_keywords)
            except Exception as error:  # noqa: BLE001 - recorded on the run, not swallowed
                # Pause naming the cause; a run `pause` will not move (still pending, say)
                # gets the cause recorded on its row instead, so the operator reads why.
                try:
                    worker.pause(started, cause=error)
                except Exception:  # noqa: BLE001
                    try:
                        worker.record_pause_reason(started, error)
                    except Exception:  # noqa: BLE001 - a run that cannot record stays for recover
                        pass
        finally:
            worker_store.close()

    thread = threading.Thread(target=_drive, name=f"{thread_name}-{started}", daemon=True)
    thread.start()
    return started, thread


def drive_run(
    store: Any,
    *,
    cohort_id: str,
    package_version_id: str,
    config: Mapping[str, Any],
    provider: Any = None,
    **drive_keywords: Any,
) -> Any:
    """Create (or reuse a `pending`) run for the cohort and package version and drive it to the
    end on THIS thread and store, returning `run_to_completion`'s `RunResult` — the run's stage
    set, its stored status and its counts (FR-PIPE-01).

    The same preparation as `start_run_in_background` — the configuration resolved as `aeh run`
    resolves it, so the consent gate, the retention check and the run cost ceiling all apply —
    for a caller that wants the result rather than a worker: M-CALIB grading a test's marked
    examples (FR-CALIB-17, CT-PIPE-01). A run that already left `pending` raises
    `RunAlreadyStartedError` and nothing is written."""
    run_id, run_config, bound = _prepare_run(
        store, cohort_id=cohort_id, package_version_id=package_version_id, config=config,
        run_id=None, provider=provider, allow_running=False, drive_keywords=drive_keywords)
    orchestrator = Orchestrator(store, provider=bound,
                                decision_provider=drive_keywords["decision_provider"])
    if orchestrator.run_handle(run_id).status == "pending":
        orchestrator.start(run_id)
    return run_to_completion(store, run_id, provider=bound, run_config=run_config,
                             **drive_keywords)


def assign_identity_parked_paper(store: Any, cohort_id: str, submission_id: str,
                                 student_ref: str, *, actor: str,
                                 note: str | None = None) -> str:
    """Give a paper parked only at the identity check to a roster entry and release it to
    grading, through M-INGEST (`assign_identity_parked_paper`). No SQL here."""
    from aeh.ingest import assign_identity_parked_paper as _assign

    return _assign(store.cohort(cohort_id), submission_id, student_ref, actor=actor, note=note)


def resume_runs_in_background(
    store: Any, *, config: Mapping[str, Any], provider: Any = None, **drive_keywords: Any,
) -> list[tuple[str, Any]]:
    """After a restart, drive every `running` run again, each on its own worker thread
    (NFR-CONSOLE-08). Call it after `recover`: `recover` reclaims the dead process's leases, and
    this is what then finishes the runs.

    A run whose frozen backend profile differs from this process's is skipped. `recover`
    has already recorded why it stays where it is (`FR-CONF-15`). Returns the
    `(run_id, thread)` pairs it started."""
    from aeh.conf import resolve_run_config

    orchestrator = Orchestrator(store)
    started: list[tuple[str, Any]] = []
    for handle in orchestrator.runs(statuses=("running",)):
        try:
            resolved = resolve_run_config(dict(config), orchestrator.cohort_ref(handle.cohort_id))
        except Exception:  # noqa: BLE001 - an unresolvable profile leaves the run for recover
            continue
        if handle.backend_profile and resolved.backend_profile != handle.backend_profile:
            continue
        try:
            started.append(start_run_in_background(
                store, cohort_id=handle.cohort_id, package_version_id=handle.package_version_id,
                config=config, run_id=handle.run_id, provider=provider, allow_running=True,
                **drive_keywords))
        except Exception as error:  # noqa: BLE001 - recorded on the run; the console still starts
            # Building a run's providers now happens here, before its worker exists (a
            # malformed retry knob raises in `RetryPolicy.from_environment`). That failure
            # belongs to the run, as it did when it was raised inside the worker, and must not
            # stop the console from serving every other run.
            try:
                orchestrator.record_pause_reason(handle.run_id, error)
            except Exception:  # noqa: BLE001 - a run that cannot record stays for recover
                pass
    return started


# --- reading uploaded papers (live-test blocker B4) -----------------------------------------


def cohort_has_test_paper(store: Any, cohort_id: str) -> bool:
    """Whether the cohort already holds its test paper — the right-test check's reference —
    read through M-INGEST for the console, whose declared dependencies stop at M-PIPE
    (TC-CONSOLE-36). No SQL here."""
    from aeh.ingest import has_assessment_document

    return has_assessment_document(store.cohort(cohort_id))


def resolve_intake_config(store: Any, config: Mapping[str, Any], cohort_id: str) -> Any:
    """The resolved configuration a cohort's papers are read under, exactly as `aeh ingest`
    resolves it: the consent gate (`FR-CONF-08`) runs here, before a page is read, so a cohort
    whose work may not leave the machine is refused on a remote profile with nothing sent."""
    from aeh.conf import resolve_run_config

    return resolve_run_config(dict(config), Orchestrator(store).cohort_ref(cohort_id))


def read_uploaded_paper(
    store: Any,
    config: Mapping[str, Any],
    cohort_id: str,
    package_version: str,
    *,
    kind: str,
    filename: str,
    data: bytes,
    provider: Any = None,
) -> Any:
    """Read one uploaded PDF into a cohort: the console's papers upload (B4), through the same
    `ingest_files` door `aeh ingest` opens — the same page reader, the same five intake checks,
    the same skip of a scan already read, the same parking of a paper a check refuses.

    `kind` is `assessment` (the test paper, read once per cohort) or `sheet` (one student's
    answer sheet). The bytes are written to a private temporary folder under their own file
    name for the read and removed afterwards; the blob store keeps the scan, as it does for
    the command line. Returns `ingest_files`' `IntakeResult`."""
    import tempfile
    from pathlib import Path

    from .intake import ingest_files

    if kind not in ("assessment", "sheet"):
        raise ValueError(f"an uploaded paper is the test paper or an answer sheet, not {kind!r}")
    run_config = resolve_intake_config(store, config, cohort_id)
    if kind == "sheet" and not cohort_has_test_paper(store, cohort_id):
        # `ingest_files`' own refusal names a command-line flag; the console's reader is a
        # teacher, so the same gap is named in the screen's terms.
        raise ValueError("this class has no test paper yet: upload the test paper first, "
                         "then the answer sheets (each one is checked against it).")
    with tempfile.TemporaryDirectory(prefix="aeh-papers-") as folder:
        path = Path(folder, Path(filename).name or "paper.pdf")
        path.write_bytes(data)
        return ingest_files(
            store, run_config, cohort_id, package_version,
            assessment=path if kind == "assessment" else None,
            sheets=() if kind == "assessment" else (path,),
            provider=provider if provider is not None else _provider_for(run_config))


# --- the reading job priced, capped and retention-checked (FR-CONSOLE-97, FR-PROV-48) ---------


#: What the Papers confirmation says on a profile whose page reader runs on this computer.
NO_COST_LOCAL = "no cost: local models"


def _model_name(ref: Any) -> str:
    """A model's name for a teacher: the build without its date pin."""
    return str(getattr(ref, "build_id", "") or "").split("@", 1)[0]


def reading_estimate(store: Any, config: Mapping[str, Any], cohort_id: str,
                     pages: int) -> dict[str, Any]:
    """The Papers confirmation's figure (FR-CONSOLE-97): reading `pages` pages costs pages x the
    transcriber's per-page `estimate_cost` (FR-PROV-09). Sends nothing.

    Answers `{"estimate": <decimal string or None>, "currency", "text"}`. On `edge-local` the
    page reader runs on this computer, so there is no figure and the text says so; a remote
    reader that declares no price answers no figure and says that instead. The configuration is
    resolved as the read itself resolves it, so a class whose papers may not leave the machine
    is refused here too (`FR-CONF-08`)."""
    from aeh.prov import CallPlan

    from .settings import (
        READ_TOKENS_IN_PER_PAGE_DEFAULT, READ_TOKENS_IN_PER_PAGE_ENV,
        READ_TOKENS_OUT_PER_PAGE_DEFAULT, READ_TOKENS_OUT_PER_PAGE_ENV, _int_knob,
    )

    if pages < 0:
        raise ValueError("the number of pages is a whole number of zero or more.")
    run_config = resolve_intake_config(store, config, cohort_id)
    currency = getattr(run_config, "cost_currency", None) or "USD"
    if run_config.backend_profile == "edge-local":
        return {"estimate": None, "currency": None, "pages": pages, "text": NO_COST_LOCAL}
    plan = CallPlan(
        pages,
        _int_knob(READ_TOKENS_IN_PER_PAGE_ENV, READ_TOKENS_IN_PER_PAGE_DEFAULT, minimum=0),
        _int_knob(READ_TOKENS_OUT_PER_PAGE_ENV, READ_TOKENS_OUT_PER_PAGE_DEFAULT, minimum=0),
    )
    # Looked up on this module at call time: the reading job builds its reader the same way.
    cost = getattr(_reader_for(run_config).estimate_cost(plan), "cost", None)
    if cost is None:
        return {"estimate": None, "currency": currency, "pages": pages,
                "text": "the page reader declares no price, so the cost of reading these "
                        "papers cannot be estimated."}
    return {"estimate": str(cost), "currency": currency, "pages": pages,
            "text": f"Reading {pages} page(s) is estimated to cost about {cost} {currency} "
                    f"(the page reader's price per page x {pages})."}


def _reader_for(run_config: Any) -> Any:
    """The page reader a run configuration names: this module's `_provider_for`, looked up at
    call time, so the estimate and the reading job always build the same reader."""
    return _provider_for(run_config)


class ReadingSession:
    """One reading job's page reader, between its start (or a Resume) and its end or pause.

    Built on the worker before the first file: it resolves the configuration as the read does,
    builds the reader once and, on a remote profile, verifies zero retention for the
    transcriber before a page leaves (FR-PROV-48) — a reader with no zero-retention host refuses
    the job naming the model, and nothing was sent. `HARNESS_RETENTION_PRECHECK=0` skips that
    probe for the recorded tier only.

    Every file of the job is read through M-PROV's `MeteredProvider` over that reader, which
    adds up each completion's reported cost: `spent` is the job's whole spend (carried across a
    Resume), `spent_here` what this session spent. `ceiling_reached()` compares `spent_here`
    with `HARNESS_READ_COST_CEILING` (default: the run cost ceiling), so each Resume is the
    teacher's approval of up to one more ceiling's worth (FR-CONSOLE-97)."""

    def __init__(self, store: Any, config: Mapping[str, Any], cohort_id: str, *,
                 spent: Any = 0) -> None:
        from aeh.prov import MeteredProvider

        self.run_config = resolve_intake_config(store, config, cohort_id)
        self._reader = _reader_for(self.run_config)
        self._store = store
        self._config = config
        self._cohort_id = cohort_id
        self.probe_cost = self._verify_retention()
        self._meter = MeteredProvider(self._reader, spent=spent)

    @property
    def spent(self) -> Any:
        """The job's whole spend, the part before a Resume included."""
        return self._meter.spent

    @property
    def spent_here(self) -> Any:
        """What this session's reading cost."""
        return self._meter.spent_here

    def _verify_retention(self) -> Any:
        from aeh.orch import REMOTE_PROFILES
        from aeh.prov import RetentionPolicyError, retention_precheck_skipped, retention_probe_cost

        if self.run_config.backend_profile not in REMOTE_PROFILES:
            return None
        if retention_precheck_skipped(self._reader):
            return None
        transcriber = self.run_config.transcriber
        refusal = (f"the page reader {_model_name(transcriber)} could not be confirmed to keep "
                   f"no copy of students' work, so no page was sent. Choose a page reader "
                   f"that is served with zero data retention in the settings, then press "
                   f"Resume or upload the papers again.")
        verify = getattr(self._reader, "verify_retention", None)
        if verify is None:
            raise RetentionPolicyError(refusal)
        try:
            report = verify((transcriber,))
        except RetentionPolicyError as error:
            raise RetentionPolicyError(refusal) from error
        confirmed = {ref.build_id for ref in getattr(report, "confirmed", ())}
        if transcriber.build_id not in confirmed or getattr(report, "unconfirmed", ()):
            raise RetentionPolicyError(refusal)
        return retention_probe_cost(self._reader, (transcriber,))

    # -- the ceiling ---------------------------------------------------------------------------

    def ceiling(self) -> Any:
        """`HARNESS_READ_COST_CEILING`, read now, else the run cost ceiling; `None` is uncapped."""
        from .settings import READ_COST_CEILING_ENV, _decimal_knob

        knob = _decimal_knob(READ_COST_CEILING_ENV)
        return knob if knob is not None else getattr(self.run_config, "cost_ceiling", None)

    def ceiling_reached(self) -> bool:
        ceiling = self.ceiling()
        return ceiling is not None and self.spent_here >= ceiling

    @property
    def currency(self) -> str:
        return getattr(self.run_config, "cost_currency", None) or "USD"

    def read(self, package_version: str, *, kind: str, filename: str, data: bytes) -> Any:
        """Read one uploaded file through this session's metered reader."""
        return read_uploaded_paper(self._store, self._config, self._cohort_id, package_version,
                                   kind=kind, filename=filename, data=data,
                                   provider=self._meter)


# --- the operator's decision on a parked paper (live-test blocker B8) ---------------------------


def record_parked_decision(handle: Any, submission_id: str, **decision: Any) -> str:
    """Record the operator's decision on a parked paper through M-INGEST, for the console —
    whose declared dependencies stop at M-PIPE (TC-CONSOLE-36). No SQL here."""
    from aeh.ingest import record_quarantine_decision

    return record_quarantine_decision(handle, submission_id, **decision)


def check_parked_assignment(handle: Any, submission_id: str, student_ref: str) -> None:
    """Refuse an assignment M-INGEST would refuse, before anything is written."""
    from aeh.ingest import check_assignment

    check_assignment(handle, submission_id, student_ref)


def parked_decisions(handle: Any) -> list[dict[str, Any]]:
    """The cohort's recorded parked-paper decisions, oldest first, read through M-INGEST."""
    from aeh.ingest import quarantine_decisions

    return quarantine_decisions(handle)


def repeated_parked_decision(handle: Any, submission_id: str, **decision: Any) -> bool:
    """Whether this exact decision is already the paper's last recorded one, through M-INGEST."""
    from aeh.ingest import repeated_decision

    return repeated_decision(handle, submission_id, **decision)


# --- the teacher's corrections to whose a paper is (FR-CONSOLE-66) ----------------------------
# Through M-INGEST, for the console, whose declared dependencies stop at M-PIPE
# (TC-CONSOLE-36). No SQL here. A refusal raises M-INGEST's `PaperCorrectionError`, which the
# console reports in the teacher's words; `ValueError` catches it. Removing a paper or the test
# paper is M-STORE's (`discard_ungraded_paper`, `discard_test_paper`).


def move_paper_to_student(handle: Any, submission_id: str, student_ref: str, *, actor: str,
                          note: str | None = None) -> str | None:
    """Give a matched paper to the right student (FR-CONSOLE-66), recorded."""
    from aeh.ingest import reassign_paper

    return reassign_paper(handle, submission_id, student_ref, actor=actor, note=note)

