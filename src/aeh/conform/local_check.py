"""The local smoke on the developer box (FR-CONFORM-21, NFR-PROV-12; statistical-validity delta
§3.7.6).

`tools/live_local_check.py` is the command; this module is the headless driver behind it
(`run_local_check`, returning a `LocalCheckResult` with a per-stage trace), so nothing here needs
a terminal.

It grades the sample English test's four answer sheets (ENG7-READ-01,
`docs/live-tests/sample-materials`) on `edge-local` against a local OpenAI-compatible model server
(`LOCAL_INFERENCE_BASE_URL`), with the decision engine off, and reports:

- that the server accepted every `served_as` name (one probe per name, before the run, with no
  student text in it);
- how many of the four sheets the local vision model read;
- the §8 pipeline rows: cells scored per sheet, the verification-refusal rate, the cited share;
- the band agreement with a recorded panel run's bands, when one is given, as consistency
  between graders and never as accuracy (`GRADER_CONSISTENCY_NOTE`, FR-CONFORM-19);
- the wall clock, and the peak memory of this process where the platform lets it be read;
- `SMOKE_DISCLAIMER`: a smoke of the wire path and the pipeline, not the hardware gate.

With `record=True` every completion the local server returns is written, unchanged, as a
recording under `fixtures/F-LOCAL/recordings/` (the recording-honesty rule: captured from real
calls, keyed by the request's SHA-256, never hand-written), with `capture.json` and the
configuration it ran under beside them, so the air-gapped journey (FR-PIPE-22) can replay the
same requests. A run that fails part-way still leaves what it recorded; the stage trace says
which stage failed.

Three rules shape it:

- **Composed here, not through the console.** The run is the pipeline's own composition
  (`ingest_files`, `Orchestrator.create_run` / `start`, `run_to_completion`) with the provider
  passed in, because a recording must see every reply and the console resolves its own
  provider. The console's run start and reading job on `edge-local` are exercised by the
  recorded twin instead (`HARNESS_FIXTURE_DIR` on `edge-local`, `aeh.pipeline.runtime`).
- **The provider is M-PROV's.** It is built by `aeh.prov.provider_for` from the transcriber's
  model reference; the HTTP transport is a parameter (the command passes nothing and gets the
  real one; a unit test passes a stub), so this module holds no HTTP client (CT-PROV-15).
- **Refused before anything is sent** (`LocalCheckRefused`): a bound `HARNESS_FIXTURE_DIR` (that
  would replay recordings, not smoke the server), no server address, a profile other than
  `edge-local`, a model block with a placeholder left in it or without `served_as`, a recording
  folder that already holds recordings, or a class that already exists in the data folder.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import shutil
import sys
import threading
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeh.store import Statement

from .agreement import CHANCE_CORRECTED_KEYS, GRADER_CONSISTENCY_NOTE, chance_corrected_agreement
from .errors import ConformanceError
from .validity_check import (
    _CONFIG_DIR,
    _REPO_ROOT,
    _SAMPLES,
    _UNSCORED_STATES,
    ClassFigures,
    _cli,
    _env_held,
    _import_full_chain,
    _read_only_cohort,
    _read_run_figures,
)

__all__ = [
    "DEFAULT_CONFIG",
    "F_LOCAL_DIR",
    "LocalCheckRefused",
    "LocalCheckResult",
    "SMOKE_DISCLAIMER",
    "format_report",
    "main",
    "run_local_check",
]

#: The shipped configuration the smoke runs under: `edge-local`, one judge, the decision engine
#: off, no escalation. The operator fills in the two model blocks for their own server.
DEFAULT_CONFIG = _CONFIG_DIR / "live-test.edge-local.toml"

#: Where `record=True` writes: `recordings/` (one file per request key), `capture.json` (what
#: the capture ran and measured) and `edge-local.toml` (the configuration it ran under).
F_LOCAL_DIR = _REPO_ROOT / "fixtures" / "F-LOCAL"

_ENG7_SPEC = _CONFIG_DIR / "eng7-read-01.package.toml"
_ENG7_ROSTER = _CONFIG_DIR / "eng7-roster.txt"
_ENG7_PAPER = _SAMPLES / "pdf" / "ENG7-READ-01" / "01-test-paper.pdf"
_ENG7_SHEETS = _SAMPLES / "pdf" / "ENG7-READ-01" / "answer-sheets"

_PROFILE = "edge-local"
_FIXTURE_DIR_ENV = "HARNESS_FIXTURE_DIR"
_DECISION_ENGINE_ENV = "HARNESS_DECISION_ENGINE"

#: The probe each `served_as` name gets before the run: no student text, one short reply. Its
#: token cap is env-gated (seam 3) for a server that refuses a very small `max_tokens`.
PROBE_TEXT = "Reply with the single word: ready."
PROBE_MAX_TOKENS_ENV = "HARNESS_LOCAL_CHECK_PROBE_MAX_TOKENS"
PROBE_MAX_TOKENS_DEFAULT = 8

SMOKE_DISCLAIMER = (
    "This is a smoke of the wire path and the pipeline on the developer box: it shows that a "
    "local model server answers the system's requests under the names it serves and that the "
    "four sample sheets can be read and graded end to end. It is not the hardware acceptance "
    "gate (HLD section 8.5, issue #157), which needs the target hardware and is unchanged by "
    "this result. Small local models are not expected to grade well; the figures describe this "
    "box and these models only."
)


class LocalCheckRefused(ConformanceError):
    """The smoke will not run: something it checks before anything is sent is wrong."""


# --- the result (seams 1 and 4: a structured result with a per-stage trace) ----------------------


@dataclasses.dataclass
class LocalCheckResult:
    """The whole smoke: every report field, and every stage with its status, in order."""

    config_path: str
    data_dir: str
    base_url: str
    probes: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    sheets: dict[str, Any] = dataclasses.field(default_factory=dict)
    figures: ClassFigures | None = None
    agreement: dict[str, Any] = dataclasses.field(default_factory=dict)
    wall_clock_s: float | None = None
    peak_memory_bytes: int | None = None
    memory_note: str = ""
    recorded: dict[str, Any] | None = None
    stages: list[dict[str, str]] = dataclasses.field(default_factory=list)
    consistency_note: str = GRADER_CONSISTENCY_NOTE
    disclaimer: str = SMOKE_DISCLAIMER

    @property
    def ok(self) -> bool:
        """Every stage ran, or was skipped for a stated reason (the agreement, with no panel
        bands given). A failed stage makes the smoke fail."""
        return bool(self.stages) and all(
            stage["status"] in ("ok", "skipped") for stage in self.stages)

    def stage(self, name: str, status: str, detail: str = "") -> None:
        self.stages.append({"stage": name, "status": status, "detail": detail})


# --- the recording tee ----------------------------------------------------------------------------


def _recording_provider(live: Any, recorder: Any) -> Any:
    """The live provider, priced per unit as every pipeline provider is
    (`aeh.pipeline.runtime._UnitPricedProvider`), with every completion it returns written as a
    recording. Subclassing the pricing wrapper keeps `_inner` the live provider, so the pipeline
    still sees a live backend (`_is_live`: real seats for escalation, no derived names)."""
    from aeh.pipeline.runtime import _UnitPricedProvider

    class _RecordingProvider(_UnitPricedProvider):
        def __init__(self) -> None:
            super().__init__(live)
            self.recorded = 0
            self._lock = threading.Lock()

        def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
            completion = self._inner.complete(prompt, model_ref, params)
            if recorder is not None:
                recorder.record(prompt, model_ref, params, completion)
                with self._lock:
                    self.recorded += 1
            return completion

    return _RecordingProvider()


# --- the refusals, before anything is sent ---------------------------------------------------------


def _model_refs(run_config: Any) -> list[Any]:
    """Every model the run dispatches to on this profile: the transcriber (which also stands in
    for the extractor and the synthesizer) and the panel."""
    refs = [run_config.transcriber] if getattr(run_config, "transcriber", None) else []
    return refs + list(run_config.panel)


def _refuse_placeholders(config_path: Path, refs: Sequence[Any]) -> None:
    """A block still carrying the template's `<...>` placeholders, or an all-zero weights hash,
    would put an identity on the recordings that names no real weights file."""
    for ref in refs:
        for field in ("build_id", "quantization", "served_as"):
            value = str(getattr(ref, field, "") or "")
            if "<" in value or ">" in value or value.endswith("sha256:" + "0" * 64):
                raise LocalCheckRefused(
                    f"the {ref.role} block in {config_path.name} still has a placeholder in "
                    f"{field} ({value!r}). Put the weights file's path and real sha256 in "
                    "build_id and the name your server serves the model under in served_as, "
                    "then run again. Nothing was sent.")


def _resolve(config_path: Path, cohort_id: str) -> tuple[dict[str, Any], Any]:
    """The effective configuration (the environment wins, FR-CONF-14) with the decision engine
    held off, resolved for a synthetic class. M-CONF refuses a local block without `served_as`
    here (FR-CONF-40), naming the block and the fix."""
    from aeh.conf import CohortRef, effective_config, resolve_run_config
    from aeh.pipeline.runtime import _load_config_file

    config = effective_config(_load_config_file(str(config_path)))
    config[_DECISION_ENGINE_ENV] = "off"
    profile = str(config.get("HARNESS_PROFILE") or "")
    if profile != _PROFILE:
        raise LocalCheckRefused(
            f"the configuration selects profile {profile or 'none'!r}; the local smoke runs on "
            f"{_PROFILE!r} only (check HARNESS_PROFILE in the terminal, which wins over the "
            "file). Nothing was sent.")
    # The placeholders first: M-CONF would refuse them too, but as a malformed build id, which
    # does not tell the operator they are the template's to fill in.
    declared = [config.get("transcriber"), *(config.get("panel") or ())]
    _refuse_placeholders(config_path, [ref for ref in declared if hasattr(ref, "build_id")])
    try:
        # The class the smoke creates is synthetic sample work; M-CONF's gate decides on it.
        cohort = CohortRef(cohort_id, consent_class="synthetic")
        run_config = resolve_run_config(dict(config), cohort)
    except Exception as error:  # noqa: BLE001 - re-raised as the refusal it is
        raise LocalCheckRefused(f"{error} Nothing was sent.") from error
    if getattr(run_config, "decision_engine", None) is not None:
        raise LocalCheckRefused("the decision engine could not be turned off for the smoke.")
    return config, run_config


def _refuse_before_sending(base_url: str | None, record_dir: Path | None, data_dir: Path,
                           cohort_id: str) -> None:
    if os.environ.get(_FIXTURE_DIR_ENV, "").strip():
        raise LocalCheckRefused(
            f"{_FIXTURE_DIR_ENV} is set, so the run would replay recordings instead of asking "
            "the local server. Unset it for the smoke. Nothing was sent.")
    if not base_url:
        from aeh.prov import LOCAL_INFERENCE_BASE_URL_ENV

        raise LocalCheckRefused(
            f"no local server address: set {LOCAL_INFERENCE_BASE_URL_ENV} (for example "
            "http://127.0.0.1:8080/v1) or pass --base-url. Nothing was sent.")
    if record_dir is not None and record_dir.exists() and any(record_dir.iterdir()):
        raise LocalCheckRefused(
            f"{record_dir} already holds a capture; a second capture would mix two runs' "
            "replies in one folder. Move it aside (or delete it) and run again. Nothing was "
            "sent.")
    if (data_dir / "cohorts" / f"{cohort_id}.sqlite").exists():
        raise LocalCheckRefused(
            f"class {cohort_id!r} already exists in {data_dir}; the smoke grades only the class "
            "it builds itself. Use a fresh data folder. Nothing was sent.")


# --- the stages -------------------------------------------------------------------------------------


def _probe_tokens() -> int:
    try:
        value = int(os.environ.get(PROBE_MAX_TOKENS_ENV, "") or PROBE_MAX_TOKENS_DEFAULT)
    except ValueError:
        return PROBE_MAX_TOKENS_DEFAULT
    return value if value > 0 else PROBE_MAX_TOKENS_DEFAULT


def _probe(provider: Any, refs: Sequence[Any]) -> list[dict[str, Any]]:
    """One completion per distinct `served_as`, before the run, with no student text. Accepted
    means the server answered it; a refusal names what the server said."""
    from aeh.prov import PromptPayload, SamplingParams

    payload = PromptPayload((("probe", PROBE_TEXT),))
    params = SamplingParams(temperature=0.0, max_tokens=_probe_tokens())
    probes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        name = str(ref.served_as)
        if name in seen:
            continue
        seen.add(name)
        started = time.monotonic()
        try:
            completion = provider.complete(payload, ref, params)
        except Exception as error:  # noqa: BLE001 - the refusal is the probe's answer
            probes.append({"role": ref.role, "served_as": name, "accepted": False,
                           "detail": f"{type(error).__name__}: {error}"})
            continue
        probes.append({"role": ref.role, "served_as": name, "accepted": True,
                       "seconds": round(time.monotonic() - started, 3),
                       "detail": f"answered {len(completion.text or '')} character(s)"})
    return probes


def _read_sheets(store: Any, run_config: Any, cohort_id: str, version: str,
                 provider: Any) -> dict[str, Any]:
    from aeh.pipeline.intake import answer_sheet_files, ingest_files

    files = answer_sheet_files([_ENG7_SHEETS])
    result = ingest_files(store, run_config, cohort_id, version, assessment=str(_ENG7_PAPER),
                          sheets=files, provider=provider)
    per_sheet = {sheet.file: {"status": sheet.status, "detail": sheet.detail}
                 for sheet in result.sheets}
    read = sum(1 for sheet in result.sheets if sheet.status == "ok")
    return {"read": read, "total": len(files), "reader": str(run_config.transcriber.served_as),
            "per_sheet": per_sheet}


def _grade(store: Any, config: Mapping[str, Any], run_config: Any, cohort_id: str,
           version: str, provider: Any) -> tuple[str, str]:
    """`aeh run`'s composition (`pipeline.cli._run_command`) for a new run, with this provider."""
    from aeh.conf import resolve_orch_knobs
    from aeh.orch import Orchestrator
    from aeh.pipeline import run_to_completion
    from aeh.pipeline.decision_engine import _decision_provider_for_run
    from aeh.pipeline.runtime import _escalation_judge_refs

    cohort = Orchestrator(store).cohort_ref(cohort_id)
    decision_provider = _decision_provider_for_run(run_config, provider, None)
    judge_refs = _escalation_judge_refs(config, run_config, cohort, provider)
    orchestrator = Orchestrator(store, provider=provider, decision_provider=decision_provider)
    run_id = orchestrator.create_run(
        cohort_id, version, run_config, orch_knobs=resolve_orch_knobs(config),
        escalation_refs=tuple((judge_refs or {}).values()))
    if orchestrator.run_handle(run_id).status == "pending":
        orchestrator.start(run_id)
    result = run_to_completion(store, run_id, provider=provider, run_config=run_config,
                               decision_provider=decision_provider, judge_refs=judge_refs,
                               retention_checked=True)
    return run_id, str(result.status)


_SELECT_RUN_BANDS = Statement(
    "SELECT r.full_name, c.criterion_id, c.band, c.state FROM criterion_score c "
    "JOIN submission s ON s.submission_id = c.submission_id "
    "LEFT JOIN roster r ON r.student_ref = s.student_ref "
    "WHERE c.run_id = :run_id ORDER BY r.full_name, c.criterion_id")


def _band_orders(spec: Path) -> dict[str, list[str]]:
    """Each banded line's band names, worst to best, from the package spec (the ordinal order)."""
    document = tomllib.loads(spec.read_text(encoding="utf-8"))
    return {str(criterion["id"]): [str(band["name"]) for band in criterion["bands"]]
            for criterion in document.get("criterion", []) if criterion.get("bands")}


def _run_bands(store: Any, cohort_id: str, run_id: str) -> dict[str, dict[str, str]]:
    bands: dict[str, dict[str, str]] = {}
    for row in store.cohort(cohort_id).query(_SELECT_RUN_BANDS, run_id=run_id):
        if str(row["state"]) in _UNSCORED_STATES:
            continue
        bands.setdefault(str(row["full_name"] or ""), {})[str(row["criterion_id"])] = str(
            row["band"])
    return bands


def band_agreement(local: Mapping[str, Mapping[str, str]],
                   panel: Mapping[str, Mapping[str, str]],
                   orders: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """The local run's bands against the panel run's, per banded line: exact and adjacent
    agreement, Cohen's kappa and ordinal alpha (`chance_corrected_agreement`), over the cells
    both runs banded. A panel key matches the local student whose name contains it (the sample
    sheets' IDs). Unmeasured figures are None, never 0."""
    per_criterion: dict[str, Any] = {}
    pooled: list[tuple[int, int]] = []
    for criterion, order in sorted(orders.items()):
        pairs: list[tuple[int, int]] = []
        for key, panel_bands in sorted(panel.items()):
            name = next((n for n in local if key and key in n), None)
            mine, theirs = (local.get(name or "", {}).get(criterion),
                            panel_bands.get(criterion))
            if mine in order and theirs in order:
                pairs.append((order.index(mine), order.index(theirs)))
        figures = chance_corrected_agreement(pairs, len(order))
        per_criterion[criterion] = {
            "pairs": figures["pairs"],
            "exact": figures["decision_band_exact_agreement"],
            "adjacent": figures["decision_band_adjacent_agreement"],
            "kappa": figures[CHANCE_CORRECTED_KEYS[0]],
            "ordinal_alpha": figures[CHANCE_CORRECTED_KEYS[1]],
        }
        pooled.extend(pairs)
    n = len(pooled)
    return {
        "per_criterion": per_criterion,
        "cells": n,
        "exact": (sum(1 for a, b in pooled if a == b) / n) if n else None,
        "adjacent": (sum(1 for a, b in pooled if abs(a - b) <= 1) / n) if n else None,
    }


def _peak_memory() -> tuple[int | None, str]:
    """This process's peak memory in bytes, where the platform lets it be read; the local
    server's memory is its own process's and is not read here."""
    note = "peak memory of this process; the model server's own memory is not included"
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class _Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]

            counters = _Counters()
            counters.cb = ctypes.sizeof(_Counters)
            kernel32 = ctypes.windll.kernel32
            # The pseudo-handle is a pointer-sized -1; left as a C int it would be truncated.
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            read = kernel32.K32GetProcessMemoryInfo
            read.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD]
            read.restype = wintypes.BOOL
            if read(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return int(counters.PeakWorkingSetSize), note
            return None, "peak memory could not be read on this machine"
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports kilobytes, macOS bytes.
        return int(peak if sys.platform == "darwin" else peak * 1024), note
    except Exception:  # noqa: BLE001 - "where readable": an unreadable figure is None
        return None, "peak memory could not be read on this machine"


def _write_capture(record_dir: Path, config_path: Path, result: LocalCheckResult,
                   version: str, run_id: str, recorded: int) -> None:
    """What the capture ran and measured, beside its recordings: the configuration file it ran
    under (model identities are part of every request key, so a replay must use the same), the
    package version, the class, the probes and the timings. Written whole by this tool."""
    record_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config_path, record_dir / "edge-local.toml")
    document = {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": "tools/live_local_check.py",
        "profile": _PROFILE,
        "decision_engine": "off",
        "package_spec": str(_ENG7_SPEC.relative_to(_REPO_ROOT)).replace("\\", "/"),
        "package_version": version,
        "roster": str(_ENG7_ROSTER.relative_to(_REPO_ROOT)).replace("\\", "/"),
        "sheets": str(_ENG7_SHEETS.relative_to(_REPO_ROOT)).replace("\\", "/"),
        "run_id": run_id,
        "run_status": result.figures.run_status if result.figures else "",
        "probes": result.probes,
        "sheets_read": {key: result.sheets.get(key) for key in ("read", "total", "reader")},
        "recordings": recorded,
        # Every HARNESS_* setting in force: some shape a request (a token cap, a prompt
        # option), and a replay without the same value misses those keys. No secret is a
        # HARNESS_* setting (the API key and the server address have their own names).
        "environment": {key: value for key, value in sorted(os.environ.items())
                        if key.startswith("HARNESS_")},
        "wall_clock_s": result.wall_clock_s,
        "stages": result.stages,
    }
    (record_dir / "capture.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


# --- the driver -------------------------------------------------------------------------------------


def run_local_check(
    *, data_dir: Path | str, config_path: Path | str | None = None,
    base_url: str | None = None, transport: Any = None, record: bool = False,
    record_dir: Path | str | None = None,
    panel_bands: Mapping[str, Mapping[str, str]] | None = None,
    cohort_id: str = "class-eng7-local",
) -> LocalCheckResult:
    """Probe, build, read, grade and measure ENG7 on `edge-local` against a local server
    (FR-CONFORM-21).

    `base_url` defaults to `LOCAL_INFERENCE_BASE_URL`. `transport` is M-PROV's HTTP seam (None:
    the real one). `record=True` writes every reply to `record_dir` (default
    `fixtures/F-LOCAL/`). `panel_bands` maps a sheet's ID to its band per line from a recorded
    panel run; without it the agreement stage is skipped and says so.

    Raises `LocalCheckRefused` before anything is sent (see the module docstring). Any later
    failure is recorded in the stage trace; `result.ok` is False unless every stage ran.
    """
    from aeh.prov import LOCAL_INFERENCE_BASE_URL_ENV, RecordedFixtureProvider, provider_for

    started = time.monotonic()
    config_path = Path(config_path) if config_path else DEFAULT_CONFIG
    data_dir = Path(data_dir)
    base_url = (base_url or os.environ.get(LOCAL_INFERENCE_BASE_URL_ENV, "")).strip() or None
    target = (Path(record_dir) if record_dir else F_LOCAL_DIR) if record else None

    _import_full_chain()  # before the first store open (CLAUDE.md)
    _refuse_before_sending(base_url, target, data_dir, cohort_id)
    with _env_held(**{_DECISION_ENGINE_ENV: "off"}):
        config, run_config = _resolve(config_path, cohort_id)
        refs = _model_refs(run_config)
        result = LocalCheckResult(config_path=str(config_path), data_dir=str(data_dir),
                                  base_url=str(base_url))
        result.stage("decision engine", "ok", "held off for the smoke")

        live = provider_for(run_config.transcriber, base_url=base_url,
                            hardware_profile=getattr(run_config, "hardware_profile", None),
                            transport=transport)
        result.probes = _probe(live, refs)
        refused = [probe for probe in result.probes if not probe["accepted"]]
        result.stage("probe served names", "failed" if refused else "ok",
                     "; ".join(f"{p['served_as']}: {p['detail']}" for p in refused)
                     or f"{len(result.probes)} name(s) accepted")
        if not refused:
            recorder = RecordedFixtureProvider(fixture_dir=target / "recordings") if target else None
            provider = _recording_provider(live, recorder)
            version, run_id = _run_stages(result, data_dir, config, run_config, cohort_id,
                                          provider, panel_bands)
        else:
            provider, version, run_id = None, "", ""

    result.wall_clock_s = round(time.monotonic() - started, 1)
    result.peak_memory_bytes, result.memory_note = _peak_memory()
    if target is not None:
        replies = int(getattr(provider, "recorded", 0) or 0)
        # A request asked twice (a retried unit) is one recording: the file is its key.
        recorded = len(list((target / "recordings").glob("*.json"))) if replies else 0
        result.recorded = {"dir": str(target), "recordings": recorded, "replies": replies}
        if refused:
            result.stage("recordings", "skipped", "nothing was run, so nothing was recorded")
        else:
            _write_capture(target, config_path, result, version, run_id, recorded)
            result.stage("recordings", "ok" if recorded else "failed",
                         f"{recorded} recording(s) from {replies} reply(ies) written to "
                         f"{target / 'recordings'}")
    return result


def _run_stages(result: LocalCheckResult, data_dir: Path, config: Mapping[str, Any],
                run_config: Any, cohort_id: str, provider: Any,
                panel_bands: Mapping[str, Mapping[str, str]] | None) -> tuple[str, str]:
    """Build, read, grade, measure; each stage traced. Returns (package version, run id)."""
    from aeh.store import open_store

    data_dir.mkdir(parents=True, exist_ok=True)
    data = str(data_dir)
    try:
        built = _cli(["package", "build", "--data-dir", data, "--spec", str(_ENG7_SPEC)])
        version = json.loads(built)["package_version"]
        _cli(["cohort", "create", "--data-dir", data, "--cohort", cohort_id,
              "--consent", "synthetic", "--roster", str(_ENG7_ROSTER)])
    except Exception as error:  # noqa: BLE001 - recorded in the trace
        result.stage("build test and class", "failed", f"{type(error).__name__}: {error}")
        return "", ""
    result.stage("build test and class", "ok", version)

    figures = ClassFigures(test="ENG7-READ-01", cohort_id=cohort_id, package_version=version)
    result.figures = figures
    store = open_store(data_dir)
    try:
        try:
            result.sheets = _read_sheets(store, run_config, cohort_id, version, provider)
        except Exception as error:  # noqa: BLE001 - recorded in the trace
            result.stage("read sheets", "failed", f"{type(error).__name__}: {error}")
            return version, ""
        read, total = result.sheets["read"], result.sheets["total"]
        result.stage("read sheets", "ok" if read == total and total else "failed",
                     f"{read} of {total} sheets read by {result.sheets['reader']}")

        try:
            figures.run_id, figures.run_status = _grade(
                store, config, run_config, cohort_id, version, provider)
        except Exception as error:  # noqa: BLE001 - recorded in the trace
            result.stage("run", "failed", f"{type(error).__name__}: {error}")
            return version, figures.run_id
        result.stage("run", "ok" if figures.run_status == "complete" else "failed",
                     f"{figures.run_id} {figures.run_status}")

        try:
            _read_run_figures(store, figures)
            graded = sum(1 for cell in figures.cells_per_sheet.values() if cell["scored"])
            # A complete run can still have quarantined a student after the read: the smoke
            # grades all four or says how many it did not.
            result.stage("pipeline figures", "ok" if graded == total else "failed",
                         f"{graded} of {total} students graded")
        except Exception as error:  # noqa: BLE001 - recorded in the trace
            result.stage("pipeline figures", "failed", f"{type(error).__name__}: {error}")

        if panel_bands is None:
            result.agreement = {"measured": False,
                                "detail": "no recorded panel run's bands were given"}
            result.stage("band agreement", "skipped", result.agreement["detail"])
        else:
            try:
                result.agreement = {"measured": True, **band_agreement(
                    _run_bands(store, cohort_id, figures.run_id), panel_bands,
                    _band_orders(_ENG7_SPEC))}
                result.stage("band agreement", "ok", f"{result.agreement['cells']} cell(s)")
            except Exception as error:  # noqa: BLE001 - recorded in the trace
                result.stage("band agreement", "failed", f"{type(error).__name__}: {error}")
    finally:
        with contextlib.suppress(Exception):
            store.close()
    return version, figures.run_id


# --- the printout -------------------------------------------------------------------------------


def _pct(value: Any) -> str:
    return "n/a" if value is None else f"{100 * float(value):.1f} %"


def _num(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.3f}"


def format_report(result: LocalCheckResult) -> str:
    """The printed report: each FR-CONFORM-21 field under its own heading, then the stage trace,
    then the consistency sentence and the smoke disclaimer."""
    lines = [f"Local smoke - profile {_PROFILE}, server {result.base_url}, "
             f"data folder {result.data_dir}", ""]
    lines.append("Served names (one probe each, before the run):")
    for probe in result.probes:
        lines.append(f"  {probe['role']} {probe['served_as']}: "
                     f"{'accepted' if probe['accepted'] else 'REFUSED'} - {probe['detail']}")
    sheets = result.sheets
    lines.append(f"Pages read by the local vision model: {sheets.get('read', 0)} of "
                 f"{sheets.get('total', 0)} sheets ({sheets.get('reader', '-')})")
    for name, outcome in sorted((sheets.get("per_sheet") or {}).items()):
        lines.append(f"  {name}: {outcome['status']}"
                     + (f" - {outcome['detail']}" if outcome.get("detail") else ""))
    figures = result.figures
    if figures is not None:
        lines.append(f"Run: {figures.run_id or '-'} {figures.run_status or 'not run'}")
        lines.append("Cells scored per sheet:")
        for sheet, cell in figures.cells_per_sheet.items():
            lines.append(f"  {sheet}: {cell['scored']} of {cell['lines']} lines scored")
        refusal, cited = figures.refusal, figures.cited
        lines.append(f"Refusal rate: {refusal.get('refused', 0)} of {refusal.get('replies', 0)} "
                     f"judge replies refused ({_pct(refusal.get('rate'))})")
        lines.append(f"Cited share: {cited.get('cited', 0)} of {cited.get('verdicts', 0)} "
                     f"surviving verdicts cited ({_pct(cited.get('share'))})")
    agreement = result.agreement
    lines.append("Band agreement with the recorded panel run (consistency between graders, not "
                 "accuracy):")
    if not agreement.get("measured"):
        lines.append(f"  not measured: {agreement.get('detail', 'the run did not reach it')}")
    else:
        lines.append(f"  all lines: {agreement['cells']} cell(s), exact "
                     f"{_pct(agreement['exact'])}, adjacent {_pct(agreement['adjacent'])}")
        for criterion, cell in agreement["per_criterion"].items():
            lines.append(f"  {criterion}: {cell['pairs']} pair(s), exact {_pct(cell['exact'])}, "
                         f"adjacent {_pct(cell['adjacent'])}, kappa {_num(cell['kappa'])}, "
                         f"ordinal alpha {_num(cell['ordinal_alpha'])}")
    lines.append(f"Wall clock: {result.wall_clock_s if result.wall_clock_s is not None else 'n/a'} s")
    memory = result.peak_memory_bytes
    lines.append("Peak memory: " + (f"{memory / 2**20:.0f} MiB ({result.memory_note})"
                                    if memory is not None else result.memory_note or "n/a"))
    if result.recorded is not None:
        lines.append(f"Recordings: {result.recorded['recordings']} (from "
                     f"{result.recorded.get('replies', 0)} replies) written to "
                     f"{result.recorded['dir']}")
    lines.append("")
    lines.append("Stages:")
    for stage in result.stages:
        lines.append(f"  [{stage['status']}] {stage['stage']}"
                     + (f" - {stage['detail']}" if stage["detail"] else ""))
    lines.append("")
    lines.append(f"Note: {result.consistency_note}.")
    lines.append(result.disclaimer)
    return "\n".join(lines)


def _load_panel_bands(path: str | None) -> Mapping[str, Mapping[str, str]] | None:
    if not path:
        return None
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LocalCheckRefused(f"the panel bands file {path} could not be read: {error}. "
                                "Nothing was sent.") from error
    if not isinstance(document, dict) or not all(
            isinstance(v, dict) for v in document.values()):
        raise LocalCheckRefused(
            f"{path} must be a JSON object of sheet ID -> {{line: band}}, for example "
            '{"E7-001": {"C2": "full"}}.')
    return {str(k): {str(c): str(b) for c, b in v.items()} for k, v in document.items()}


def main(argv: Sequence[str] | None = None, *, transport: Any = None) -> int:
    """`live_local_check.py [--config FILE] [--base-url URL] [--data-dir DIR] [--record]
    [--record-dir DIR] [--panel-bands FILE]`. Exit 0 when every stage ran, 1 when one failed,
    2 when refused before anything was sent."""
    import argparse
    import tempfile

    parser = argparse.ArgumentParser(
        prog="live_local_check.py",
        description="Grade the sample English test's four sheets on edge-local against a local "
                    "model server and print the smoke's figures (FR-CONFORM-21). A smoke of "
                    "the wire path, not the hardware gate.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="the edge-local configuration (default: %(default)s)")
    parser.add_argument("--base-url", default=None,
                        help="the local server's OpenAI-compatible base URL "
                             "(default: LOCAL_INFERENCE_BASE_URL)")
    parser.add_argument("--data-dir", default=None,
                        help="the data folder (default: a fresh temporary folder)")
    parser.add_argument("--record", action="store_true",
                        help="write every reply as a recording (default folder: fixtures/F-LOCAL)")
    parser.add_argument("--record-dir", default=None)
    parser.add_argument("--panel-bands", default=None,
                        help="JSON: sheet ID -> {line: band} from a recorded panel run")
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir) if args.data_dir else Path(
        tempfile.mkdtemp(prefix="aeh-local-check-"))
    try:
        panel_bands = _load_panel_bands(args.panel_bands)
        result = run_local_check(
            data_dir=data_dir, config_path=args.config, base_url=args.base_url,
            transport=transport, record=args.record, record_dir=args.record_dir,
            panel_bands=panel_bands)
    except LocalCheckRefused as refusal:
        print(f"Refused: {refusal}", file=sys.stderr)
        print(SMOKE_DISCLAIMER, file=sys.stderr)
        return 2
    print(format_report(result))
    return 0 if result.ok else 1
