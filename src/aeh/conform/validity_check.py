"""The live validity check (FR-CONFORM-20; statistical-validity delta §3.5 and §8).

`tools/live_validity_check.py --profile smoke|panel` is the command; this module is the headless
driver behind it (`run_validity_check`, returning a `ValidityCheckResult` with a per-stage trace),
so nothing here needs a terminal.

For each sample test (ENG7-READ-01 and PS9-FORCES-01, `docs/live-tests/sample-materials`) the
check builds the package, creates a `synthetic` class, reads in the test paper and the answer
sheets with the operator commands, then serves a console over the data folder and drives its API
the way the teacher's browser does: `start run`, wait on the monitor, open the blind sample,
draft every seat from the sample author's intended band, `finish`, read the validity result and
the package record, and purge the class. Before the purge it reads what the §8 table measures:
cells scored per sheet, the verification-refusal rate, the cited share, the confidence
distribution, the labels, and `routing_policy_validity`'s verdict.

Three rules shape it:

- **Synthetic work only (R31).** The classes it creates are `synthetic`. Pointed at a class that
  already exists, it reads the class's consent and refuses anything but `synthetic` on a remote
  profile before anything is built, read or sent (`ValidityCheckRefused`); a `synthetic` class
  that already exists is refused too, because the check grades only classes it built itself.
- **The "teacher" is the sample author.** The blind bands are the sample author's intended bands
  (`docs/live-tests/sample-materials/intended_bands.py`), the bands the sheets were written to
  earn. The output says so (`INTENDED_BANDS_DISCLAIMER`); the
  agreement it reports is with the author's intent, not with a teacher.
- **The provider is the pipeline's.** The check never builds a provider: the operator commands
  and the console resolve it through the pipeline's own seam, so `HARNESS_FIXTURE_DIR` (the
  recorded provider) is the offline override and the configured profile is the live path. No
  retention flag or probe is added here.

The console is spoken to through a `ConsoleRequest` the caller passes in (the command's loopback
HTTP client, `tools/live_validity_check.py`), so this module holds no HTTP client of its own:
M-PROV stays the only module with an egress-capable import (CT-PROV-15).
"""

from __future__ import annotations

import contextlib
import dataclasses
import importlib.util
import io
import json
import os
import sys
import time
import tomllib
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence
from urllib.parse import urlencode

from aeh.store import Statement

from .errors import ConformanceError

__all__ = [
    "ConsoleRequest",
    "INTENDED_BANDS_DISCLAIMER",
    "PROFILES",
    "ValidityCheckRefused",
    "ValidityCheckResult",
    "format_report",
    "main",
    "run_validity_check",
]

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LIVE_TESTS = _REPO_ROOT / "docs" / "live-tests"
_CONFIG_DIR = _LIVE_TESTS / "config"
_SAMPLES = _LIVE_TESTS / "sample-materials"

#: The two named profiles and the shipped configuration each one runs under (FR-CONFORM-20).
PROFILES: Mapping[str, Path] = {
    "smoke": _CONFIG_DIR / "live-test.dev-ci.toml",
    "panel": _CONFIG_DIR / "live-test.panel.toml",
}

#: How long one class's run may take before the check gives up on it (seconds), and how often the
#: monitor is polled. Env-gated (seam 3): a live panel run is slow, a recorded one fast.
RUN_TIMEOUT_ENV = "HARNESS_LIVE_CHECK_RUN_TIMEOUT_S"
RUN_TIMEOUT_DEFAULT_S = 3600.0
POLL_INTERVAL_ENV = "HARNESS_LIVE_CHECK_POLL_S"
POLL_INTERVAL_DEFAULT_S = 2.0
#: One request to the console's API: `(port, method, path, json_body_or_None) -> (status,
#: decoded JSON or text)`. The command passes a loopback HTTP client.
ConsoleRequest = Callable[[int, str, str, "Mapping[str, Any] | None"], "tuple[int, Any]"]

INTENDED_BANDS_DISCLAIMER = (
    'The "teacher" bands in this check are the sample author\'s intended bands: the band each '
    "synthetic answer was written to earn. They are not a teacher's marks, so the agreement "
    "in this check is agreement with the author's intent, not evidence of accuracy with teachers."
)

def _load_path(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def intended_bands() -> Mapping[str, Mapping[str, str]]:
    """The sample author's intended band per (sheet, judged rubric line), from the sample
    materials. Raises `ValidityCheckRefused` when a sheet's intended bands no longer earn its
    reference points (the samples changed without the table)."""
    module = _load_path("_aeh_intended_bands", _SAMPLES / "intended_bands.py")
    problems = module.mismatches()
    if problems:
        raise ValidityCheckRefused(
            "the sample author's intended bands no longer match the samples: "
            + "; ".join(problems) + ". Correct intended_bands.py before running.")
    return module.INTENDED_BANDS


@dataclasses.dataclass(frozen=True)
class SampleTest:
    """One sample test: its package spec, class list, papers and the class the check creates."""

    name: str
    spec: Path
    roster: Path
    paper: Path
    sheets: Path
    cohort_id: str


def _sample_tests(eng7_cohort: str, ps9_cohort: str) -> tuple[SampleTest, ...]:
    pdf = _SAMPLES / "pdf"
    return (
        SampleTest("ENG7-READ-01", _CONFIG_DIR / "eng7-read-01.package.toml",
                   _CONFIG_DIR / "eng7-roster.txt", pdf / "ENG7-READ-01" / "01-test-paper.pdf",
                   pdf / "ENG7-READ-01" / "answer-sheets", eng7_cohort),
        SampleTest("PS9-FORCES-01", _CONFIG_DIR / "ps9-forces-01.package.toml",
                   _CONFIG_DIR / "ps9-roster.txt", pdf / "PS9-FORCES-01" / "01-test-paper.pdf",
                   pdf / "PS9-FORCES-01" / "answer-sheets", ps9_cohort),
    )


class ValidityCheckRefused(ConformanceError):
    """The check will not run: a non-synthetic class on a remote profile, a class it did not
    build, an unknown profile, or a sample table that no longer matches the samples."""


# --- the result (seams 1 and 4: a structured result with a per-stage trace) ----------------------


@dataclasses.dataclass
class ClassFigures:
    """What the check measured for one sample class, before and after its purge."""

    test: str
    cohort_id: str
    package_version: str = ""
    run_id: str = ""
    run_status: str = ""
    cells_per_sheet: dict[str, dict[str, int]] = dataclasses.field(default_factory=dict)
    refusal: dict[str, Any] = dataclasses.field(default_factory=dict)
    cited: dict[str, Any] = dataclasses.field(default_factory=dict)
    confidence: dict[str, Any] = dataclasses.field(default_factory=dict)
    routing_mix: dict[str, int] = dataclasses.field(default_factory=dict)
    blind: dict[str, Any] = dataclasses.field(default_factory=dict)
    labels: dict[str, Any] = dataclasses.field(default_factory=dict)
    validity: Any = None
    record: Any = None
    routing_verdict: dict[str, Any] = dataclasses.field(default_factory=dict)
    purge: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class ValidityCheckResult:
    """The whole check: per class figures, and every stage with its status, in order."""

    profile: str
    data_dir: str
    classes: list[ClassFigures] = dataclasses.field(default_factory=list)
    stages: list[dict[str, str]] = dataclasses.field(default_factory=list)
    disclaimer: str = INTENDED_BANDS_DISCLAIMER

    @property
    def ok(self) -> bool:
        return bool(self.stages) and all(stage["status"] == "ok" for stage in self.stages)

    def stage(self, name: str, test: str, status: str, detail: str = "") -> None:
        self.stages.append({"stage": name, "test": test, "status": status, "detail": detail})


# --- the reads (declared here, as `live_acceptance` declares its own) ----------------------------

_SELECT_SUBMISSIONS = Statement(
    "SELECT s.submission_id, r.full_name FROM submission s "
    "LEFT JOIN roster r ON r.student_ref = s.student_ref ORDER BY s.submission_id")
_SELECT_RUN = Statement(
    "SELECT run_id, status FROM run WHERE cohort_id = :cohort_id ORDER BY started_at")
_SELECT_RUN_SCORES = Statement(
    "SELECT submission_id, criterion_id, confidence, routing, state "
    "FROM criterion_score WHERE run_id = :run_id ORDER BY submission_id, criterion_id")
#: `criterion_score.state` values that mean the line has no score.
_UNSCORED_STATES = frozenset({"ungradeable_by_panel", "unresolved_selection"})
_SELECT_RUN_LLM_VERDICTS = Statement(
    "SELECT v.uncited FROM verdict v JOIN work_unit w ON w.work_id = v.work_id "
    "WHERE w.run_id = :run_id AND v.scoring_engine = 'llm'")
_SELECT_RUN_REFUSED_REPLIES = Statement(
    "SELECT COALESCE(SUM(value), 0) AS refused FROM run_metrics "
    "WHERE run_id = :run_id AND metric = 'judge_contract_violations'")
_SELECT_RUN_LABELS = Statement(
    "SELECT label_type, origin, routing FROM label WHERE run_id = :run_id")


# --- the refusals, before anything is built or sent ---------------------------------------------


_SELECT_CONSENT = Statement(
    "SELECT consent_class FROM cohort WHERE cohort_id = :cohort_id")
_COUNT_PAPERS = Statement("SELECT COUNT(*) AS n FROM submission")


def _read_only_cohort(data_dir: Path, ledger: str, statement: Statement, **params: Any
                      ) -> list[Any] | None:
    """Rows of `statement` from a class's ledger opened read-only, or None when it has none."""
    from aeh.store import open_store

    if not (data_dir / "cohorts" / f"{ledger}.sqlite").exists():
        return None
    store = open_store(data_dir, read_only=True)
    try:
        return list(store.cohort(ledger).query(statement, **params))
    finally:
        store.close()


def _existing_consent(data_dir: Path, cohort_id: str) -> str | None:
    """The recorded consent class of a class already in `data_dir`, or None when it has none.
    Read through a read-only store, so the refusal writes nothing."""
    rows = _read_only_cohort(data_dir, cohort_id, _SELECT_CONSENT, cohort_id=cohort_id)
    if rows is None:
        return None
    return str(rows[0]["consent_class"]) if rows else "unknown"


def _profile_name(config_path: Path) -> str:
    """The backend profile the run will use: the terminal's `HARNESS_PROFILE` over the file's
    (the order the shipped configs document)."""
    document = tomllib.loads(config_path.read_text(encoding="utf-8"))
    return str(os.environ.get("HARNESS_PROFILE") or document.get("HARNESS_PROFILE") or "")


def _refuse_unsafe_classes(data_dir: Path, tests: Sequence[SampleTest], config_path: Path) -> None:
    """R31: on a remote profile only synthetic work. The rule is M-CALIB's
    `refuse_remote_real_work` (stricter than the consent gate: no override lifts it), not a copy
    of it here (CT-CONFORM-10). A class that already exists is refused whatever its consent,
    the R31 refusal first; the check grades only classes it built."""
    from aeh.calib.examples import ExamplesRefused, refuse_remote_real_work

    profile = _profile_name(config_path)
    if not profile:
        raise ValidityCheckRefused(
            f"{config_path.name} names no profile, so the check cannot tell whether the work "
            "would leave the machine. Set HARNESS_PROFILE.")
    for test in tests:
        consent = _existing_consent(data_dir, test.cohort_id)
        if consent is None:
            continue
        try:
            refuse_remote_real_work({"HARNESS_PROFILE": profile}, consent)
        except ExamplesRefused:
            raise ValidityCheckRefused(
                f"class {test.cohort_id!r} is recorded as {consent!r} work, and this check sends "
                "only synthetic sample work to a remote profile (R31). Nothing was built, "
                "read in or sent.") from None
        raise ValidityCheckRefused(
            f"class {test.cohort_id!r} already exists in {data_dir}; the check grades only the "
            "classes it builds itself. Use a fresh data folder or another class name.")


# --- the operator commands ------------------------------------------------------------------------


def _cli(argv: list[str]) -> str:
    from aeh.pipeline import cli

    with redirect_stdout(io.StringIO()) as out:
        code = cli.main(argv)
    if code != 0:
        raise ConformanceError(f"`aeh {' '.join(argv[:2])}` exited {code}: {out.getvalue()[-800:]}")
    return out.getvalue()


def _build_and_ingest(test: SampleTest, data_dir: Path, config_path: Path) -> str:
    data = str(data_dir)
    built = _cli(["package", "build", "--data-dir", data, "--spec", str(test.spec)])
    version = json.loads(built)["package_version"]
    _cli(["cohort", "create", "--data-dir", data, "--cohort", test.cohort_id,
          "--consent", "synthetic", "--roster", str(test.roster)])
    _cli(["ingest", "--data-dir", data, "--cohort", test.cohort_id, "--package-version", version,
          "--config", str(config_path), "--assessment", str(test.paper), str(test.sheets)])
    return version


# --- the console, through its API ------------------------------------------------------------------


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return value if value > 0 else default


class _Console:
    """A console on a loopback port, spoken to as the browser speaks to it, through the
    caller's `ConsoleRequest`."""

    def __init__(self, server: Any, send: ConsoleRequest) -> None:
        self.server = server
        self.port = int(server.socket.getsockname()[1])
        self._send = send

    def request(self, method: str, path: str, body: Mapping[str, Any] | None = None
                ) -> tuple[int, Any]:
        return self._send(self.port, method, path, body)

    def get(self, path: str, **query: Any) -> tuple[int, Any]:
        return self.request("GET", path + ("?" + urlencode(query) if query else ""))

    def action(self, action: str, **params: Any) -> tuple[int, Any]:
        slug = action.lower().replace(" ", "-").replace("/", "-")
        return self.request("POST", f"/api/v1/actions/{slug}", params)


@contextlib.contextmanager
def _env_held(**values: str | None) -> Iterator[None]:
    """Hold environment variables for the console's lifetime, restoring them after."""
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextlib.contextmanager
def _serve(store: Any, config_path: Path, send: ConsoleRequest) -> Iterator[_Console]:
    from aeh.conf import parse_config_document
    from aeh.console import serve_console

    cfg = parse_config_document(config_path.read_text(encoding="utf-8"), "toml")
    with _env_held(CONSOLE_PORT="0", CONSOLE_BIND=None):
        with redirect_stdout(io.StringIO()):
            server = serve_console(store=store, cfg=cfg, config_path=str(config_path))
    try:
        yield _Console(server, send)
    finally:
        server.terminate()


def _start_and_wait(console: _Console, store: Any, test: SampleTest, version: str
                    ) -> tuple[str, str]:
    status, outcome = console.action("start run", cohort_id=test.cohort_id,
                                     package_version=version)
    if status != 200 or not (isinstance(outcome, dict) and outcome.get("dispatched")):
        raise ConformanceError(f"start run was not dispatched: {status} {outcome!r}")
    rows = store.cohort(test.cohort_id).query(_SELECT_RUN, cohort_id=test.cohort_id)
    if not rows:
        raise ConformanceError("start run was dispatched but no run row exists")
    run_id = str(rows[-1]["run_id"])
    deadline = time.monotonic() + _env_float(RUN_TIMEOUT_ENV, RUN_TIMEOUT_DEFAULT_S)
    poll = _env_float(POLL_INTERVAL_ENV, POLL_INTERVAL_DEFAULT_S)
    while True:
        status, monitor = console.get("/api/v1/monitor", run_id=run_id)
        run_status = str((monitor or {}).get("status") or "") if status == 200 else ""
        if run_status in ("complete", "failed", "paused"):
            return run_id, run_status
        if time.monotonic() > deadline:
            return run_id, f"timed out ({run_status or status})"
        time.sleep(poll)


# --- the figures ---------------------------------------------------------------------------------


def _read_run_figures(store: Any, figures: ClassFigures) -> None:
    """The §8 pipeline rows, read from the class's ledger and the durable tier before purge."""
    handle = store.cohort(figures.cohort_id)
    names = {str(row["submission_id"]): str(row["full_name"] or "")
             for row in handle.query(_SELECT_SUBMISSIONS)}
    scores = handle.query(_SELECT_RUN_SCORES, run_id=figures.run_id)
    per_sheet: dict[str, dict[str, int]] = {}
    confidences: Counter[str] = Counter()
    routing: Counter[str] = Counter()
    for row in scores:
        sheet = names.get(str(row["submission_id"])) or f"unmatched {row['submission_id']}"
        cell = per_sheet.setdefault(sheet, {"scored": 0, "lines": 0})
        cell["lines"] += 1
        # A line is scored unless the panel could not grade it or the reader could not resolve
        # the mark (the two states that leave a line without a score).
        cell["scored"] += str(row["state"]) not in _UNSCORED_STATES
        if row["confidence"] is not None:
            confidences[f"{float(row['confidence']):.2f}"] += 1
        routing[str(row["routing"])] += 1
    figures.cells_per_sheet = dict(sorted(per_sheet.items()))
    figures.confidence = {"distinct": len(confidences),
                          "histogram": dict(sorted(confidences.items()))}
    figures.routing_mix = dict(sorted(routing.items()))

    verdicts = handle.query(_SELECT_RUN_LLM_VERDICTS, run_id=figures.run_id)
    landed = len(verdicts)
    cited = sum(1 for row in verdicts if row["uncited"] is not None and not row["uncited"])
    refused_rows = store.durable().query(_SELECT_RUN_REFUSED_REPLIES, run_id=figures.run_id)
    refused = int(float(refused_rows[0]["refused"])) if refused_rows else 0
    replies = landed + refused
    figures.refusal = {"refused": refused, "replies": replies,
                       "rate": (refused / replies) if replies else None}
    figures.cited = {"cited": cited, "verdicts": landed,
                     "share": (cited / landed) if landed else None}


def _play_blind(console: _Console, figures: ClassFigures,
                bands: Mapping[str, Mapping[str, str]]) -> None:
    """Open the draw, draft each seat from the intended band, finish. A seat whose student or
    line has no intended band (a parked sheet, an unknown name) is left undrafted and counted;
    no band is invented for it."""
    status, read = console.get("/api/v1/blind-seats", run_id=figures.run_id)
    if status != 200 or not isinstance(read, dict) or read.get("state") != "open":
        figures.blind = {"state": (read or {}).get("state") if isinstance(read, dict) else status,
                         "seats": 0, "drafted": 0, "undrafted": 0}
        return
    drafted = 0
    undrafted: list[str] = []
    for seat in read.get("seats", []):
        name = str(seat.get("student_name") or "")
        # The intended-band table is keyed by the roster's full name, which is what the seat
        # carries. Exact, not substring: a name that is not in the table is a parked/unknown
        # student and is left undrafted rather than matched to a different one.
        student = name if name in bands else None
        band = bands.get(student or "", {}).get(str(seat.get("criterion_id")))
        offered = {str(b.get("name")) for b in seat.get("bands", [])}
        if band is None or band not in offered:
            undrafted.append(f"{name or '?'} / {seat.get('criterion_id')}")
            continue
        status, outcome = console.action("blind-sample draft", run_id=figures.run_id,
                                         seat_id=seat["seat_id"], band=band)
        if status == 200 and isinstance(outcome, dict) and outcome.get("dispatched"):
            drafted += 1
        else:
            undrafted.append(f"{name} / {seat.get('criterion_id')} (refused: {status})")
    status, finished = console.action("blind-sample finish", run_id=figures.run_id)
    figures.blind = {
        "state": "finished" if status == 200 else f"finish refused ({status})",
        "seats": len(read.get("seats", [])), "drafted": drafted, "undrafted": len(undrafted),
        "undrafted_seats": undrafted,
        "rows_written": finished.get("rows_written") if isinstance(finished, dict) else None,
    }


def _read_labels(store: Any, figures: ClassFigures) -> None:
    rows = store.durable().query(_SELECT_RUN_LABELS, run_id=figures.run_id)
    figures.labels = {
        "total": len(rows),
        "by_type": dict(Counter(str(r["label_type"]) for r in rows)),
        "by_origin": dict(Counter(str(r["origin"]) for r in rows)),
        "by_routing": dict(Counter(str(r["routing"]) for r in rows)),
    }


def _read_routing_verdict(data_dir: Path, figures: ClassFigures) -> None:
    from aeh.stats import open_stats

    report = open_stats(data_dir, cohort_id=figures.cohort_id).routing_policy_validity(
        figures.cohort_id)
    figures.routing_verdict = {
        "verdict": report.verdict,
        "n": report.n,
        "arms": {arm: {"paired": value.paired, "errors": value.errors,
                       "error_rate": value.error_rate}
                 for arm, value in report.label_population.items()},
        "interpretation": report.stated_interpretation,
    }


def _purge(console: _Console, data_dir: Path, figures: ClassFigures) -> None:
    """The console's `purge cohort`. FR-STORE-07 keeps the class's ledger file, emptied and
    still migrated, so success is the dispatch plus no paper left in it (read independently)."""
    status, outcome = console.action("purge cohort", cohort_id=figures.cohort_id)
    detail = outcome.get("detail") if isinstance(outcome, dict) else outcome
    figures.purge = {"status": status, "dispatched": bool(
        isinstance(outcome, dict) and outcome.get("dispatched")),
        "papers_left": _papers_left(data_dir, figures.cohort_id), "detail": detail}


def _papers_left(data_dir: Path, cohort_id: str) -> int:
    """Submission rows left in the class's ledger (0 when the file is gone), read-only."""
    rows = _read_only_cohort(data_dir, cohort_id, _COUNT_PAPERS)
    return 0 if not rows else int(rows[0]["n"])


# --- the driver ----------------------------------------------------------------------------------


def _import_full_chain() -> None:
    """All eleven migration owners, before the first store open (CLAUDE.md)."""
    import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ  # noqa: F401,E401
    import aeh.judge, aeh.orch, aeh.pkg, aeh.review, aeh.synth  # noqa: F401,E401


def run_validity_check(
    profile: str, *, data_dir: Path | str, console_request: ConsoleRequest,
    eng7_cohort: str = "class-eng7-check", ps9_cohort: str = "class-ps9-check",
) -> ValidityCheckResult:
    """Build, ingest, run, blind-mark, measure and purge ENG7 and PS9 on `profile` (FR-CONFORM-20).

    Raises `ValidityCheckRefused` before anything is built, read or sent when the profile is
    unknown, the sample table drifted, or a named class already exists (a non-synthetic one on a
    remote profile is the R31 refusal). Any later failure is recorded in the stage trace and the
    check moves to the next class; `result.ok` is False unless every stage ran.
    """
    if profile not in PROFILES:
        raise ValidityCheckRefused(
            f"unknown profile {profile!r}; the check runs {sorted(PROFILES)}")
    config_path = PROFILES[profile]
    data_dir = Path(data_dir)
    tests = _sample_tests(eng7_cohort, ps9_cohort)
    # Before the refusal: it reads an existing class's consent through the store, and a store
    # open needs the full migration chain (CLAUDE.md).
    _import_full_chain()
    _refuse_unsafe_classes(data_dir, tests, config_path)
    bands = intended_bands()
    data_dir.mkdir(parents=True, exist_ok=True)
    result = ValidityCheckResult(profile=profile, data_dir=str(data_dir))

    versions: dict[str, str] = {}
    for test in tests:
        try:
            versions[test.name] = _build_and_ingest(test, data_dir, config_path)
            result.stage("build+ingest", test.name, "ok", versions[test.name])
        except Exception as error:  # noqa: BLE001 - recorded, and the class is skipped
            result.stage("build+ingest", test.name, "failed", str(error))

    from aeh.store import open_store

    # The console's store is the console's: its handler threads open their own connections,
    # and a connection this thread opened on it would block the purge (a SQLite connection is
    # bound to its thread). The check reads through a store of its own (`_one_class`).
    console_store = open_store(data_dir)
    try:
        with _serve(console_store, config_path, console_request) as console:
            for test in tests:
                if test.name not in versions:
                    continue
                result.classes.append(
                    _one_class(console, data_dir, test, versions[test.name], bands, result))
    finally:
        with contextlib.suppress(Exception):
            console_store.close()
    return result


def _one_class(console: _Console, data_dir: Path, test: SampleTest, version: str,
               bands: Mapping[str, Mapping[str, str]], result: ValidityCheckResult
               ) -> ClassFigures:
    """One class through the console, every read taken before the purge. The reader store is
    closed before the purge, so no connection of this thread holds the class's ledger open."""
    from aeh.store import open_store

    store = open_store(data_dir)
    try:
        return _class_steps(console, store, data_dir, test, version, bands, result)
    finally:
        with contextlib.suppress(Exception):
            store.close()


def _class_steps(console: _Console, store: Any, data_dir: Path, test: SampleTest, version: str,
                 bands: Mapping[str, Mapping[str, str]], result: ValidityCheckResult
                 ) -> ClassFigures:
    figures = ClassFigures(test=test.name, cohort_id=test.cohort_id, package_version=version)
    steps = (
        ("run", lambda: _run_step(console, store, test, version, figures)),
        ("pipeline figures", lambda: _read_run_figures(store, figures)),
        ("blind sample", lambda: _play_blind(console, figures, bands)),
        ("labels", lambda: _read_labels(store, figures)),
        ("administration record", lambda: _read_record(console, figures)),
        ("routing verdict", lambda: _read_routing_verdict(data_dir, figures)),
        ("purge", lambda: (store.close(), _purge(console, data_dir, figures))[1]),
    )
    for name, step in steps:
        try:
            detail = step() or ""
        except Exception as error:  # noqa: BLE001 - recorded in the trace, never swallowed
            result.stage(name, test.name, "failed", f"{type(error).__name__}: {error}")
            if name == "run":
                break
            continue
        status = "ok"
        if name == "run" and figures.run_status != "complete":
            status = "failed"
        if name == "purge" and not (figures.purge.get("dispatched")
                                    and figures.purge.get("papers_left") == 0):
            status = "failed"
        if name == "blind sample" and figures.blind.get("state") != "finished":
            status = "failed"
        result.stage(name, test.name, status, str(detail))
        if name == "run" and status != "ok":
            break
    return figures


def _run_step(console: _Console, store: Any, test: SampleTest, version: str,
              figures: ClassFigures) -> str:
    figures.run_id, figures.run_status = _start_and_wait(console, store, test, version)
    return f"{figures.run_id} {figures.run_status}"


def _read_record(console: _Console, figures: ClassFigures) -> None:
    _status, figures.validity = console.get("/api/v1/results/validity", run_id=figures.run_id)
    _status, figures.record = console.get("/api/v1/packages/record",
                                          package_version_id=figures.package_version)


# --- the printout --------------------------------------------------------------------------------


def _pct(value: Any) -> str:
    return "n/a" if value is None else f"{100 * float(value):.1f} %"


def format_report(result: ValidityCheckResult) -> str:
    """The printed report: per class, each FR-CONFORM-20 section under its own heading, then the
    stage trace, then the intended-bands disclaimer."""
    lines = [f"Live validity check - profile {result.profile}, data folder {result.data_dir}", ""]
    for figures in result.classes:
        lines.append(f"== {figures.test} (class {figures.cohort_id}, run {figures.run_id or '-'}, "
                     f"{figures.run_status or 'not run'})")
        lines.append("Cells scored per sheet:")
        for sheet, cell in figures.cells_per_sheet.items():
            lines.append(f"  {sheet}: {cell['scored']} of {cell['lines']} lines scored")
        refusal = figures.refusal
        lines.append(f"Verification-refusal rate: {refusal.get('refused', 0)} of "
                     f"{refusal.get('replies', 0)} judge replies refused "
                     f"({_pct(refusal.get('rate'))}; every response-contract refusal, a "
                     "citation that fails verification among them)")
        cited = figures.cited
        lines.append(f"Cited share: {cited.get('cited', 0)} of {cited.get('verdicts', 0)} "
                     f"surviving verdicts cited ({_pct(cited.get('share'))})")
        confidence = figures.confidence
        lines.append(f"Confidence distribution: {confidence.get('distinct', 0)} distinct values "
                     f"{json.dumps(confidence.get('histogram', {}))}")
        lines.append(f"Routing of scored cells: {json.dumps(figures.routing_mix)}")
        lines.append(f"Blind sample: {json.dumps(figures.blind)}")
        lines.append(f"Labels: {json.dumps(figures.labels)}")
        lines.append(f"Administration record: validity {json.dumps(figures.validity, default=str)}")
        lines.append(f"  package record {json.dumps(figures.record, default=str)}")
        lines.append(f"Routing verdict: {json.dumps(figures.routing_verdict, default=str)}")
        lines.append(f"Purge outcome: {json.dumps(figures.purge, default=str)}")
        lines.append("")
    lines.append("Stages:")
    for stage in result.stages:
        lines.append(f"  [{stage['status']}] {stage['test']} {stage['stage']}"
                     + (f" - {stage['detail']}" if stage["detail"] else ""))
    lines.append("")
    lines.append(result.disclaimer)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None, *, console_request: ConsoleRequest) -> int:
    """`live_validity_check.py --profile smoke|panel [--data-dir DIR] [--eng7-cohort ID]
    [--ps9-cohort ID]`. Exit 0 when every stage ran, 1 when one failed, 2 when refused."""
    import argparse
    import tempfile

    parser = argparse.ArgumentParser(
        prog="live_validity_check.py",
        description="Run ENG7 and PS9 through a profile and the console's blind flow, and print "
                    "the validity figures (FR-CONFORM-20). Synthetic sample work only.")
    parser.add_argument("--profile", required=True, choices=sorted(PROFILES))
    parser.add_argument("--data-dir", default=None,
                        help="the data folder (default: a fresh temporary folder)")
    parser.add_argument("--eng7-cohort", default="class-eng7-check")
    parser.add_argument("--ps9-cohort", default="class-ps9-check")
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir) if args.data_dir else Path(
        tempfile.mkdtemp(prefix="aeh-validity-check-"))
    try:
        result = run_validity_check(args.profile, data_dir=data_dir,
                                    console_request=console_request,
                                    eng7_cohort=args.eng7_cohort, ps9_cohort=args.ps9_cohort)
    except ValidityCheckRefused as refusal:
        print(f"Refused: {refusal}", file=sys.stderr)
        print(INTENDED_BANDS_DISCLAIMER, file=sys.stderr)
        return 2
    print(format_report(result))
    return 0 if result.ok else 1
