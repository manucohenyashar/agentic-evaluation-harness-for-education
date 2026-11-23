"""The live validity check (FR-CONFORM-20; statistical-validity delta §3.5 and §8).

`tools/live_validity_check.py --profile smoke|panel` is the command; this module is the headless
driver behind it (`run_validity_check`, returning a `ValidityCheckResult` with a per-stage trace),
so nothing here needs a terminal.

For each sample test (ENG7-READ-01 and PS9-FORCES-01, `docs/live-tests/sample-materials`) the
check builds the package, creates a `synthetic` class, reads in the test paper and the answer
sheets with the operator commands, then serves a console over the data folder and drives it over
HTTP the way the teacher's browser does: `start run`, wait on the monitor, open the blind sample,
draft every seat from the sample author's intended band, `finish`, read the validity result and
the package record, and purge the class. Before the purge it reads what the §8 table measures:
cells scored per sheet, the verification-refusal rate, the cited share, the confidence
distribution, the labels, and `routing_policy_validity`'s verdict.

Three rules shape it:

- **Synthetic work only (R31).** The classes it creates are `synthetic`. Pointed at a class that
  already exists, it reads the class's consent and refuses anything but `synthetic` on a remote
  profile before anything is built, read or sent (`ValidityCheckRefused`); a `synthetic` class
  that already exists is refused too, because the check grades only classes it built itself.
- **The "teacher" is the sample author.** The blind bands are `INTENDED_BANDS`, the bands the
  sample sheets were written to earn. The output says so (`INTENDED_BANDS_DISCLAIMER`); the
  agreement it reports is with the author's intent, not with a teacher.
- **The provider is the pipeline's.** The check never builds a provider: the operator commands
  and the console resolve it through the pipeline's own seam, so `HARNESS_FIXTURE_DIR` (the
  recorded provider) is the offline override and the configured profile is the live path. No
  retention flag or probe is added here.
"""

from __future__ import annotations

import contextlib
import dataclasses
import http.client
import importlib.util
import io
import json
import os
import sqlite3
import sys
import time
import tomllib
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import urlencode

from aeh.store import Statement

from .errors import ConformanceError

__all__ = [
    "INTENDED_BANDS",
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
#: The HTTP timeout for one console request (seconds).
HTTP_TIMEOUT_ENV = "HARNESS_LIVE_CHECK_HTTP_TIMEOUT_S"
HTTP_TIMEOUT_DEFAULT_S = 120.0

INTENDED_BANDS_DISCLAIMER = (
    'The "teacher" bands in this check are the sample author\'s intended bands: the band each '
    "synthetic answer was written to earn. They are not a teacher's marks, so the agreement "
    "in this check is agreement with the author's intent, not evidence of accuracy with teachers."
)

#: The sample author's intended band per (sheet, judged rubric line), read off the sheets in
#: `build_sample_materials.py` against the package specs' band descriptors. Each sheet's points
#: (these bands plus its multiple-choice keys) sum to its `reference_points`; `_check_intended`
#: asserts that at start, so a sample edited without this table fails loudly. Sheets that intake
#: parks (S9-005 wrong test, S9-006 no name) have no entry: a seat for them is left undrafted.
INTENDED_BANDS: Mapping[str, Mapping[str, str]] = {
    "E7-001": {"C1a": "present", "C1b": "present", "C2": "full", "C3": "evidenced"},
    "E7-002": {"C1a": "present", "C1b": "present", "C2": "adequate", "C3": "change"},
    "E7-003": {"C1a": "absent", "C1b": "absent", "C2": "limited", "C3": "retell"},
    "E7-004": {"C1a": "present", "C1b": "absent", "C2": "none", "C3": "none"},
    "S9-001": {"C4": "full", "C6": "full"},
    "S9-002": {"C4": "adequate", "C6": "adequate"},
    "S9-003": {"C4": "limited", "C6": "limited"},
    "S9-004": {"C4": "none", "C6": "full"},
}


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
    "SELECT submission_id, criterion_id, points, confidence, routing, state "
    "FROM criterion_score WHERE run_id = :run_id ORDER BY submission_id, criterion_id")
_SELECT_RUN_LLM_VERDICTS = Statement(
    "SELECT v.uncited FROM verdict v JOIN work_unit w ON w.work_id = v.work_id "
    "WHERE w.run_id = :run_id AND v.scoring_engine = 'llm'")
_SELECT_RUN_REFUSED_REPLIES = Statement(
    "SELECT COALESCE(SUM(value), 0) AS refused FROM run_metrics "
    "WHERE run_id = :run_id AND metric = 'judge_contract_violations'")
_SELECT_RUN_LABELS = Statement(
    "SELECT label_type, origin, routing FROM label WHERE run_id = :run_id")


# --- the refusals, before anything is built or sent ---------------------------------------------


def _existing_consent(data_dir: Path, cohort_id: str) -> str | None:
    """The recorded consent class of a class already in `data_dir`, or None when it has none.
    Read from the ledger file directly, so the refusal opens no store and writes nothing."""
    path = data_dir / "cohorts" / f"{cohort_id}.sqlite"
    if not path.exists():
        return None
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT consent_class FROM cohort WHERE cohort_id = ?", (cohort_id,)).fetchone()
    except sqlite3.Error:
        return "unknown"
    finally:
        connection.close()
    return str(row[0]) if row else "unknown"


def _profile_name(config_path: Path) -> str:
    document = tomllib.loads(config_path.read_text(encoding="utf-8"))
    """The backend profile the run will use: the terminal's `HARNESS_PROFILE` over the file's
    (the order the shipped configs document)."""
    return str(os.environ.get("HARNESS_PROFILE") or document.get("HARNESS_PROFILE") or "")


def _refuse_unsafe_classes(data_dir: Path, tests: Sequence[SampleTest], config_path: Path) -> None:
    """R31: on a remote profile only `synthetic` work. A class that already exists is refused
    whatever its consent, real first and loudest; the check grades only classes it built."""
    from aeh.conf import REMOTE_PROFILES

    profile = _profile_name(config_path)
    # Fail closed: a profile the check cannot name is treated as remote.
    remote = not profile or profile in REMOTE_PROFILES
    for test in tests:
        consent = _existing_consent(data_dir, test.cohort_id)
        if consent is None:
            continue
        if consent != "synthetic" and remote:
            raise ValidityCheckRefused(
                f"class {test.cohort_id!r} is recorded as {consent!r} work, and this check sends "
                "only synthetic sample work to a remote profile (R31). Nothing was built, "
                "read in or sent.")
        raise ValidityCheckRefused(
            f"class {test.cohort_id!r} already exists in {data_dir}; the check grades only the "
            "classes it builds itself. Use a fresh data folder or another class name.")


def _load_sample_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "_aeh_validity_check_samples", _SAMPLES / "build_sample_materials.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _check_intended(tests: Sequence[SampleTest]) -> None:
    """Every sheet with intended bands earns its `reference_points` under them: the judged
    lines' band points from the package spec, plus one key lookup per multiple-choice line."""
    samples = _load_sample_module()
    sheets = {sheet["student"]: sheet
              for sheet in samples.PHYSICS_SHEETS + samples.ENGLISH_SHEETS if sheet["student"]}
    for test in tests:
        spec = tomllib.loads(test.spec.read_text(encoding="utf-8"))
        points = {question["id"]: question.get("points", 0) for question in spec["question"]}
        band_points = {c["id"]: {b["name"]: b["points"] for b in c["bands"]}
                       for c in spec["criterion"] if "bands" in c}
        keys = {c["question"]: c["key"] for c in spec["criterion"] if "key" in c}
        prefix = test.name[:2].upper()
        for student, intended in INTENDED_BANDS.items():
            if not student.startswith(prefix):
                continue
            sheet = sheets[student]
            earned = sum(band_points[criterion][band] for criterion, band in intended.items())
            earned += sum(points[question] for question, key in keys.items()
                          if sheet["mcq"].get(question) == [key])
            expected = sheet["reference_points"]
            if expected is not None and earned != expected:
                raise ValidityCheckRefused(
                    f"the intended bands for {student} earn {earned} points but the sample sheet "
                    f"is written to earn {expected}; correct INTENDED_BANDS before running.")


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


# --- the console, over HTTP ------------------------------------------------------------------------


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return value if value > 0 else default


class _Console:
    """A console on a loopback port, spoken to as the browser speaks to it."""

    def __init__(self, server: Any) -> None:
        self.server = server
        self.port = int(server.socket.getsockname()[1])

    def request(self, method: str, path: str, body: Mapping[str, Any] | None = None
                ) -> tuple[int, Any]:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.port, timeout=_env_float(HTTP_TIMEOUT_ENV, HTTP_TIMEOUT_DEFAULT_S))
        try:
            headers = {"Content-Type": "application/json"} if payload is not None else {}
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            raw = response.read()
        finally:
            connection.close()
        try:
            return response.status, json.loads(raw) if raw else None
        except ValueError:
            return response.status, raw.decode("utf-8", errors="replace")

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
def _serve(store: Any, config_path: Path) -> Iterator[_Console]:
    from aeh.conf import parse_config_document
    from aeh.console import serve_console

    cfg = parse_config_document(config_path.read_text(encoding="utf-8"), "toml")
    with _env_held(CONSOLE_PORT="0", CONSOLE_BIND=None):
        with redirect_stdout(io.StringIO()):
            server = serve_console(store=store, cfg=cfg, config_path=str(config_path))
    try:
        yield _Console(server)
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
        cell["scored"] += row["points"] is not None
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


def _play_blind(console: _Console, figures: ClassFigures) -> None:
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
        student = next((ref for ref in INTENDED_BANDS if ref in name), None)
        band = INTENDED_BANDS.get(student or "", {}).get(str(seat.get("criterion_id")))
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


def _papers_left(data_dir: Path, cohort_id: str) -> int | None:
    """Submission rows left in the class's ledger (0 when the file is gone), or None unread."""
    path = data_dir / "cohorts" / f"{cohort_id}.sqlite"
    if not path.exists():
        return 0
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM submission").fetchone()[0])
    except sqlite3.Error:
        return None
    finally:
        connection.close()


# --- the driver ----------------------------------------------------------------------------------


def _import_full_chain() -> None:
    """All eleven migration owners, before the first store open (CLAUDE.md)."""
    import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ  # noqa: F401,E401
    import aeh.judge, aeh.orch, aeh.pkg, aeh.review, aeh.synth  # noqa: F401,E401


def run_validity_check(
    profile: str, *, data_dir: Path | str,
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
    _refuse_unsafe_classes(data_dir, tests, config_path)
    _check_intended(tests)
    data_dir.mkdir(parents=True, exist_ok=True)
    _import_full_chain()
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
        with _serve(console_store, config_path) as console:
            for test in tests:
                if test.name not in versions:
                    continue
                result.classes.append(
                    _one_class(console, data_dir, test, versions[test.name], result))
    finally:
        with contextlib.suppress(Exception):
            console_store.close()
    return result


def _one_class(console: _Console, data_dir: Path, test: SampleTest, version: str,
               result: ValidityCheckResult) -> ClassFigures:
    """One class through the console, every read taken before the purge. The reader store is
    closed before the purge, so no connection of this thread holds the class's ledger open."""
    from aeh.store import open_store

    store = open_store(data_dir)
    try:
        return _class_steps(console, store, data_dir, test, version, result)
    finally:
        with contextlib.suppress(Exception):
            store.close()


def _class_steps(console: _Console, store: Any, data_dir: Path, test: SampleTest, version: str,
                 result: ValidityCheckResult) -> ClassFigures:
    figures = ClassFigures(test=test.name, cohort_id=test.cohort_id, package_version=version)
    steps = (
        ("run", lambda: _run_step(console, store, test, version, figures)),
        ("pipeline figures", lambda: _read_run_figures(store, figures)),
        ("blind sample", lambda: _play_blind(console, figures)),
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


def main(argv: Sequence[str] | None = None) -> int:
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
                                    eng7_cohort=args.eng7_cohort, ps9_cohort=args.ps9_cohort)
    except ValidityCheckRefused as refusal:
        print(f"Refused: {refusal}", file=sys.stderr)
        print(INTENDED_BANDS_DISCLAIMER, file=sys.stderr)
        return 2
    print(format_report(result))
    return 0 if result.ok else 1
