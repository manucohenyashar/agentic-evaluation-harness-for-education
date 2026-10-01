"""`run_pipeline_for_test`: runs the whole pipeline end to end from code, with no console."""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from aeh.conf import CohortRef, ModelRef, resolve_run_config
from aeh.grade import GradingService
from aeh.orch import Orchestrator
from aeh.pkg import PackageCatalog
from aeh.store import open_store, store_metrics
from aeh.det import DeterministicEvaluator

from .html import _row_get
from .records import PipelineOutcome


# --- the headless pipeline driver --------------------------------------------------------------------------

_R0_VERSION = "pkg-v1-r0"


_PACKAGE_ID = "pkg-v1"


_DRIVER_STAMP = "2026-01-01T00:00:00+00:00"


_DRIVER_COHORT = "c-2026-console-driver"


_DRIVER_RUN_ID = "run-console-driver"


_DRIVER_CRITERIA: tuple[tuple[str, str, str], ...] = (
    ("C-01", "Q1", "A"),
    ("C-02", "Q2", "B"),
    ("C-03", "Q3", "C"),
)


_DRIVER_OPTIONS = ("A", "B", "C", "D")


def run_pipeline_for_test(
    *,
    calibration: str | None = None,
    data_dir: Path | None = None,
    run_id: str | None = None,
    submissions: int = 3,
    cohort_id: str | None = None,
    alongside: Callable[[], Any] | None = None,
) -> PipelineOutcome:
    """Run the whole pipeline from code, without serving the console, and return a structured
    result with a trace of each stage (CT-CONSOLE-01).

    More detail: `docs/code-notes/console.md`, section `driver.py: run_pipeline_for_test`.
    """
    del calibration  # a disabled or absent M-CALIB is the same pipeline: the driver never imports it
    modules: tuple[str, ...] = (
        "aeh.store",
        "aeh.conf",
        "aeh.pkg",
        "aeh.orch",
        "aeh.det",
        "aeh.grade",
    )
    created_dir = False
    if data_dir is None:
        data_dir = Path(tempfile.mkdtemp(prefix="aeh-console-pipeline-"))
        created_dir = True
    for sub in ("packages", "cohorts", "blobs"):
        Path(data_dir, sub).mkdir(parents=True, exist_ok=True)
    store = open_store(data_dir)
    grades: tuple[Any, ...] = ()
    lower: tuple[str, ...] = ()
    finalized = False
    stages: list[str] = []
    driver_cohort = cohort_id if cohort_id is not None else _DRIVER_COHORT
    driver_run_id = (
        run_id
        if run_id is not None
        else (
            f"{_DRIVER_RUN_ID}-{driver_cohort}"
            if cohort_id is not None
            else _DRIVER_RUN_ID
        )
    )
    alongside_error: list[BaseException] = []

    def _run_alongside() -> None:
        try:
            alongside()  # type: ignore[operator] -- guarded by `is not None` below
        except BaseException as error:  # noqa: BLE001 -- re-raised on the caller's thread
            alongside_error.append(error)

    alongside_thread: threading.Thread | None = None
    try:
        clock = lambda: _DRIVER_STAMP  # noqa: E731 — the driver's pinned clock
        # -- the pinned rubric version (disclosed) ------------------------------------------------------
        # Idempotent, not INSERT OR IGNORE: a second run on the same data directory
        # (CT-STATS-C17's differential) re-seeds nothing — the version row's presence is
        # the seed, and re-adding criteria to it would be a second write to the same
        # locked-by-position rows rather than a declaration.
        seeded = store.package(_PACKAGE_ID).query(
            "SELECT 1 FROM package_version WHERE package_version_id = :v", v=_R0_VERSION
        )
        if not seeded:
            with store.package(_PACKAGE_ID).transaction() as tx:
                tx.execute(
                    "INSERT INTO package (package_id, created_at) VALUES (:p, :t)",
                    p=_PACKAGE_ID,
                    t=_DRIVER_STAMP,
                )
                tx.execute(
                    "INSERT INTO package_version (package_version_id, package_id, revision, locked) "
                    "VALUES (:v, :p, 1, 0)",
                    v=_R0_VERSION,
                    p=_PACKAGE_ID,
                )
            catalog = PackageCatalog(store.package(_PACKAGE_ID), package_id=_PACKAGE_ID)
            for cid, question_id, key in _DRIVER_CRITERIA:
                catalog.add_criterion(
                    _R0_VERSION, cid, question_id=question_id, kind="mcq",
                    band_count=2,
                )
                catalog.add_band(_R0_VERSION, cid, 0, "incorrect", 0.0)
                catalog.add_band(_R0_VERSION, cid, 1, "correct", 1.0)
                catalog.set_mcq_options(
                    _R0_VERSION, cid, [(option, f"Option {option}") for option in _DRIVER_OPTIONS]
                )
                catalog.set_answer_key(_R0_VERSION, cid, key)
            stages.append("package seeded")
        else:
            stages.append("package seed present")
        # -- the cohort, its submissions, and their selection reads -----------------------------------
        with store.cohort(driver_cohort).transaction() as tx:
            tx.execute(
                "INSERT INTO cohort (cohort_id, consent_class, created_at) "
                "VALUES (:c, 'synthetic', :t)",
                c=driver_cohort,
                t=_DRIVER_STAMP,
            )
            for index in range(submissions):
                submission_id = f"sub-driver-{index + 1:02d}"
                tx.execute(
                    "INSERT INTO submission (submission_id, cohort_id, student_ref) "
                    "VALUES (:s, :c, :r)",
                    s=submission_id,
                    c=driver_cohort,
                    r=f"ref-driver-{index + 1:02d}",
                )
                document_id = f"doc-driver-{index + 1:02d}"
                tx.execute(
                    "INSERT INTO document (document_id, submission_id, content_hash, created_at) "
                    "VALUES (:d, :s, :h, :t)",
                    d=document_id,
                    s=submission_id,
                    h=f"hash-{submission_id}",
                    t=_DRIVER_STAMP,
                )
                for position, (cid, question_id, key) in enumerate(_DRIVER_CRITERIA):
                    # The last submission's second criterion is left ambiguous: the one
                    # region the deterministic pass parks for triage, which is what makes
                    # the lower-confidence marker honest rather than asserted.
                    ambiguous = index == submissions - 1 and position == 1
                    tx.execute(
                        "INSERT INTO document_region (region_id, document_id, page_no, "
                        "element_kind, region_kind, retraction, content_state, selection_state, "
                        "selection, position) "
                        "VALUES (:r, :d, 1, :q, 'selection_mark', :retraction, 'present', :ss, "
                        ":sel, :pos)",
                        r=f"reg-{document_id}-{question_id}-1",
                        d=document_id,
                        q=question_id,
                        retraction=None,
                        ss="ambiguous" if ambiguous else "resolved",
                        sel=None if ambiguous else key,
                        pos=position + 1,
                    )
        stages.append("cohort seeded")
        # -- the run, the deterministic pass, the policy pass, the finalization ------------------------
        resolved = resolve_run_config(
            _driver_cfg(), CohortRef(cohort_id=driver_cohort, consent_class="synthetic")
        )
        orchestrator = Orchestrator(
            store, package_id_for=lambda version: _PACKAGE_ID, clock=clock
        )
        created_run_id = orchestrator.create_run(
            driver_cohort, _R0_VERSION, resolved, run_id=driver_run_id
        )
        # The id create_run returns is the one the pass runs under: a caller-pinned
        # id resolves to itself, a derived one is what the run table carries.
        stages.append("run created")
        if alongside is not None:
            # Concurrent, not sequential: the seam's claim is about an export running
            # *during* scoring. `daemon=True` is belt-and-braces — the join below is the
            # real lifecycle — so an export that hangs cannot outlive a killed run.
            alongside_thread = threading.Thread(
                target=_run_alongside, name="aeh-console-alongside", daemon=True
            )
            alongside_thread.start()
        DeterministicEvaluator(store).evaluate_cohort(created_run_id)
        stages.append("deterministic pass complete")
        GradingService(store, clock=clock).compute_all(created_run_id)
        stages.append("grades computed")
        record = GradingService(store, clock=clock).finalize_batch(created_run_id, "console-driver")
        finalized = bool(getattr(record, "finalized", True))
        stages.append("batch finalized")
        cohort_handle = store.cohort(driver_cohort)
        grades = tuple(
            (
                _row_get(row, "submission_id"),
                _row_get(row, "criterion_id"),
                _row_get(row, "band"),
                _row_get(row, "points"),
                _row_get(row, "state"),
            )
            for row in cohort_handle.query(
                "SELECT submission_id, criterion_id, band, state, "
                "points FROM criterion_score WHERE run_id = :run_id "
                "ORDER BY submission_id, criterion_id",
                run_id=created_run_id,
            )
        )
        lower = tuple(
            sorted(
                {
                    str(_row_get(row, "criterion_id"))
                    for row in cohort_handle.query(
                        "SELECT DISTINCT criterion_id FROM criterion_score "
                        "WHERE run_id = :run_id AND state = 'unresolved_selection'",
                        run_id=created_run_id,
                    )
                }
            )
        )
        stages.append("read back")
        # The lock-wait figure is read while every handle the run opened is still open:
        # after `close()` the handles are gone and the figure would be an invention.
        lock_waits = int(store_metrics(store).get("lock_waits", 0))
        stages.append("metrics read")
    finally:
        if alongside_thread is not None:
            alongside_thread.join()
        store.close()
        if created_dir:
            shutil.rmtree(data_dir, ignore_errors=True)
        if alongside_error and sys.exc_info()[1] is None:
            # A concurrent export that failed must fail the run, not pass as a clean
            # one — but it must never mask the pipeline's own failure: if the body
            # raised, *its* exception is the news and wins.
            raise alongside_error[0]
    return PipelineOutcome(
        modules_imported=modules,
        grades=grades,
        grades_delivered=bool(grades),
        finalized=finalized,
        rubric_version=_R0_VERSION,
        lower_confidence_criteria=lower,
        stages=tuple(stages),
        lock_waits=lock_waits,
    )


def _driver_cfg() -> dict[str, Any]:
    """The driver's local configuration, in the same shape `edge_cfg` builds: one judge on the
    panel, a local transcriber and a fixed prompt-template version. The model references name the
    fixture provider, because the driver never calls a model: its run is fully deterministic, and
    naming a real service would suggest network traffic that does not happen."""
    return {
        "HARNESS_PROFILE": "edge-local",
        "HARNESS_HARDWARE_PROFILE": "unified-large",
        # FR-CONF-18: required with no default. The driver is deterministic end to end and
        # never dispatches a judgment, so there is no decision engine to run.
        "HARNESS_DECISION_ENGINE": "off",
        "panel": (
            ModelRef(
                role="judge",
                provider="fixture",
                build_id="/models/llama-3.3-70b.gguf@sha256:aaaa",
                quantization="q4",
            ),
        ),
        "transcriber": ModelRef(
            role="transcriber",
            provider="fixture",
            build_id="/models/whisper-large-v3.gguf@sha256:bbbb",
            quantization="q4",
        ),
        "prompt_template_v": "conf-v1.0.0",
    }
