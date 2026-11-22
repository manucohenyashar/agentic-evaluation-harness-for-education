"""The ENG7 marked-examples world behind a live console, for Validity T9 (issue #902):
TC-SETUP-28, TC-CALIB-21…23/26, TC-CONSOLE-111/112/115.

**The class.** The four-paper ENG7 class (`tests/support/eng7_sample.py`) is built, enrolled and
read in with the operator commands, under the shipped **panel** config
(`docs/live-tests/config/live-test.panel.toml`: three panel judges and three escalation
judges, profile `dev-ci`). The panel is what makes a score `final`: under the one-judge dev-ci
config every cell is `provisional_unreviewed`, and the examples' triage then files every
difference as `model_failure` (no question could ever be asked).

**The stand-in transport** is `eng7_sample`'s `FakeOpenRouter` (the real `OpenRouterProvider`
sends to it), told about every model the panel config names, with two controlled conditions:

* the **extractor** offers one span per criterion — the student's answer line in the
  criterion's question region, located by its byte offsets in the document the request carries
  (the same document the integrity gate verifies against), so `evidence_present` is 1;
* the **judge** answers the band `judge_rule(paper, criterion, bands, bands_text)` names, else
  the lowest band (the fake's default). `paper` is the ENG7 sheet stem the request's answer
  text belongs to (`E7-001-strong` …), so a case can make the system disagree with the teacher
  on exactly the cells it names. `bands_text` is the judge prompt's band block, which is how a
  case makes the clarified rubric (R1, whose descriptor carries the teacher's clarification)
  answer differently from R0.

No reply here is a recording of a live model: replies are built from the request.

**The console.** A real `serve_console()` on a loopback port (rung 3) over the data folder.
The marked examples are the same four ENG7 sheets, uploaded with `examples upload` (their PDF
bytes, so the transcriber stand-in answers their pages from the sample transcripts), marked with
`examples mark` and graded with `examples grade`; the two long steps run as jobs on the
console's worker threads, which `wait_job` joins.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import tomllib
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from tests.support.eng7_sample import (
    CONFIG_DIR,
    ENG7_COHORT,
    forget_sample_modules,
    ingest_eng7,
)
from tests.support.label_identity_world import ServedRun
from tests.support.live_test_config import openrouter_slug

#: The shipped panel config: three judges, so a score can be `final`.
PANEL_CONFIG = CONFIG_DIR / "live-test.panel.toml"

#: The four ENG7 sheets, in roster order.
SHEETS: tuple[str, ...] = ("E7-001-strong", "E7-002-middle", "E7-003-weak",
                           "E7-004-mostly-blank")

#: Each sheet's Q1 answer, which identifies the paper inside any request carrying its
#: document (`build_sample_materials.ENGLISH_SHEETS`). Checked longest first, so "Tomas."
#: (E7-004) is never matched inside another sheet's words.
_Q1_ANSWERS: dict[str, str] = {
    "E7-001-strong": "The main character is Tomas, the lighthouse keeper.",
    "E7-002-middle": "Tomas lights the lamp every evening.",
    "E7-003-weak": "A man in a lighthouse.",
    "E7-004-mostly-blank": "? Tomas.",
}

#: The judged criteria of ENG7 (C1 is an `evidence_sum` composite, never judged itself), with
#: their bands worst first, from `eng7-read-01.package.toml`.
CRITERIA: dict[str, tuple[str, ...]] = {
    "C1a": ("absent", "present"),
    "C1b": ("absent", "present"),
    "C2": ("none", "limited", "adequate", "full"),
    "C3": ("none", "retell", "change", "evidenced"),
}

#: How long a console worker (a run, an examples job, the R1 check) may take on a slow box, in
#: seconds. Env-gated (seam 3).
JOIN_TIMEOUT_ENV = "AEH_TEST_ENG7_RUN_TIMEOUT_S"

JudgeRule = Callable[[str, str, tuple[str, ...], str], "str | None"]


def _join_timeout() -> float:
    return float(os.environ.get(JOIN_TIMEOUT_ENV, "300"))


def paper_of(text: str) -> str | None:
    """The ENG7 sheet whose answers `text` carries, or None."""
    for stem, answer in sorted(_Q1_ANSWERS.items(), key=lambda kv: -len(kv[1])):
        if answer in text:
            return stem
    return None


def _document_of(submission_field: str) -> str:
    """The document text inside the request's untrusted-content block."""
    text = submission_field
    start = "<untrusted_student_content>\n"
    if text.startswith(start):
        text = text[len(start):]
    end = "\n</untrusted_student_content>"
    if text.endswith(end):
        text = text[: -len(end)]
    return text


def _answer_span(document: str, prompt_text: str) -> dict | None:
    """One span over the last non-empty line of the answer region whose body carries
    `prompt_text`, with byte offsets into `document`."""
    for match in re.finditer(r"<!--\s*region:[^>]*question_id=[^>]*-->\n(?P<body>.*?)\n<!--",
                             document, re.DOTALL):
        body = match.group("body")
        if prompt_text[:30] not in body:
            continue
        line = body.strip().splitlines()[-1].strip() if body.strip() else ""
        if not line:
            return None
        at = document.index(line, match.start("body"))
        start = len(document[:at].encode("utf-8"))
        end = start + len(line.encode("utf-8"))
        return {"start": start, "end": end, "text": line}
    return None


def install_examples_transport(fake: Any, rule: Callable[[], "JudgeRule | None"]) -> None:
    """Wrap the stand-in transport: every panel model answers, the extractor offers the answer
    span, and the judge answers what `rule()` names (read at call time, so a case can change it
    between steps)."""
    from aeh.prov.live import _fields_from_wire

    panel = tomllib.loads(PANEL_CONFIG.read_text(encoding="utf-8"))["profiles"]["dev-ci"]
    for judge in list(panel["panel"]) + list(panel.get("escalation_judge", ())):
        fake.models.add(openrouter_slug(judge["build_id"]))
    original = fake.send

    def send(request: Any) -> Any:
        response = original(request)
        fields = dict(_fields_from_wire(json.loads(request.body)))
        if "dependency_evidence" in fields:
            document = _document_of(fields.get("submission", ""))
            prompt = re.search(r"prompt_text: (.*)", fields.get("question", ""))
            span = _answer_span(document, prompt.group(1) if prompt else "")
            text = json.dumps({"spans": [span] if span else []})
        elif "evidence_rules" in fields:
            criterion = re.search(r"criterion_id: (\S+)", fields.get("criterion", ""))
            bands = tuple(re.findall(r"^- ([^:\n]+)", fields.get("bands", ""), re.M))
            current = rule()
            band = None
            if current is not None and criterion is not None:
                band = current(paper_of(fields.get("submission", "")) or "",
                               criterion.group(1), bands, fields.get("bands", ""))
            if band is None:
                return response
            body = json.loads(response.body)
            content = json.loads(body["choices"][0]["message"]["content"])
            content["band"] = band
            content["self_confidence"] = 0.95
            body["choices"][0]["message"]["content"] = json.dumps(content)
            return type(response)(response.status, response.headers,
                                  json.dumps(body).encode("utf-8"))
        else:
            return response
        body = json.loads(response.body)
        body["choices"][0]["message"]["content"] = text
        return type(response)(response.status, response.headers,
                              json.dumps(body).encode("utf-8"))

    fake.send = send


@dataclass
class _Ids:
    cohort_id: str
    run_id: str = ""


@dataclass
class Eng7Examples(ServedRun):
    """The ENG7 class and its test behind a live console, with the sheets to upload as
    examples. `judge_rule` is the judge's controlled condition (see the module docstring)."""

    package_version: str = ""
    fake: Any = None
    sheets: dict[str, bytes] = field(default_factory=dict)
    test_paper: bytes = b""
    config: Any = None
    judge_rule: "JudgeRule | None" = None

    # -- the store, read-only ----------------------------------------------------------------

    def store(self) -> Any:
        """The console's own store (read through it; the console owns writes)."""
        return self.server.app._store

    def calib_cohort(self) -> str:
        from aeh.calib.examples import calibration_cohort_id

        return calibration_cohort_id(self.package_version)

    def catalog(self) -> Any:
        from aeh.calib.examples import _catalog

        return _catalog(self.store(), self.package_version)

    def raw_get(self, path: str, **query: Any) -> tuple[int, bytes]:
        """A GET whose body is returned as bytes (the exports, byte-compared)."""
        import http.client
        from urllib.parse import urlencode

        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            connection.request("GET", path + ("?" + urlencode(query) if query else ""))
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def class_runs(self) -> list[dict]:
        """The class cohort's runs, oldest first: id, status, the version graded."""
        return self.rows("SELECT run_id, status, package_version_id FROM run "
                         "ORDER BY started_at, run_id")

    # -- the jobs ------------------------------------------------------------------------------

    def wait_job(self, job_id: str) -> dict:
        """Join an examples job's worker thread and return its state from the job read."""
        thread = self.server.app._examples_threads[job_id]
        thread.join(_join_timeout())
        assert not thread.is_alive(), f"fixture: examples job {job_id} did not finish"
        record = self.server.app._jobs.get(job_id)
        return dict(record) if isinstance(record, dict) else dict(vars(record))

    def wait_runs(self) -> None:
        """Join every run worker and R1 check the console started."""
        for _ in range(3):
            for key, thread in list(self.server.app._run_threads.items()):
                thread.join(_join_timeout())
                assert not thread.is_alive(), f"fixture: console worker {key} did not finish"

    # -- the examples step over HTTP -------------------------------------------------------------

    def upload(self, stems: tuple[str, ...] = SHEETS, *, consent: str | None = "synthetic",
               with_paper: bool = True) -> tuple[dict, dict]:
        """`examples upload` of the named sheets; returns (the action's outcome, the job)."""
        params: dict[str, Any] = {
            "package_version": self.package_version,
            "documents": [{"name": f"{stem}.pdf",
                           "content_base64": base64.b64encode(self.sheets[stem]).decode()}
                          for stem in stems],
        }
        if consent is not None:
            params["consent"] = consent
        if with_paper:
            params["test_paper"] = {"name": "01-test-paper.pdf",
                                    "content_base64": base64.b64encode(self.test_paper).decode()}
        outcome = self.dispatched("examples upload", **params)
        return outcome, self.wait_job(outcome["job_id"])

    def examples_read(self) -> dict:
        status, read = self.get("/api/v1/calibration/examples",
                                package_version=self.package_version)
        assert status == 200, (status, read)
        return read

    def document_of(self) -> dict[str, str]:
        """sheet stem -> the example's document id, from the examples read."""
        return {example["file_name"].removesuffix(".pdf"): example["document_id"]
                for example in self.examples_read()["examples"]}

    def mark(self, bands_by_sheet: dict[str, dict[str, str]]) -> list[dict]:
        """`examples mark` for each named sheet."""
        documents = self.document_of()
        return [self.dispatched("examples mark", package_version=self.package_version,
                                document_id=documents[stem], bands=bands)
                for stem, bands in bands_by_sheet.items()]

    def grade(self) -> tuple[dict, dict]:
        outcome = self.dispatched("examples grade", package_version=self.package_version)
        return outcome, self.wait_job(outcome["job_id"])

    def start_class(self, package_version: str | None = None, **extra: Any) -> dict:
        """The console's `start run` on the ENG7 class, then wait for the run and any R1 check
        beside it."""
        outcome = self.dispatched("start run", cohort_id=self.cohort_id,
                                  package_version=package_version or self.package_version,
                                  **extra)
        self.wait_runs()
        return outcome


#: The three-disagreement setup (TC-CALIB-23's "4 examples with 3 disagreements"): the system
#: marks every line at its lowest band except C2 on E7-004, which it marks `full`; the teacher
#: marks C2 `full` on all four and every other line at its lowest. So the two disagree on C2
#: for E7-001…003 only — three differences, all on one criterion, each with no agreeing
#: example in the same system band, so all three triage as rubric ambiguity (one question).
THREE_DISAGREEMENTS_TEACHER: dict[str, str] = {"C1a": "absent", "C1b": "absent", "C2": "full",
                                                "C3": "none"}


def three_disagreements_rule(paper: str, criterion: str, bands: tuple[str, ...],
                             bands_text: str) -> str | None:
    if criterion == "C2" and paper == "E7-004-mostly-blank":
        return "full"
    return None


#: The clause `apply_answers` appends to a band descriptor for a "broaden" answer — it is how a
#: judge request under R1 is told apart from one under R0 (the band block carries it).
BROADENED_CLAUSE = "broadened to also cover"


def shifting_under_r1(paper: str, criterion: str, bands: tuple[str, ...],
                      bands_text: str) -> str | None:
    """The three-disagreement system, except that under R1 (a band block carrying the
    broadened clause) every C2 line is marked `full`: R1 moves three of the four papers a full
    band, so non-inferiority fails at any threshold below 0.75."""
    if criterion == "C2" and BROADENED_CLAUSE in bands_text:
        return "full"
    return three_disagreements_rule(paper, criterion, bands, bands_text)


class ScriptedOffPanel:
    """The back-translation checker's stand-in: constructs a divergent response (BT fails) or
    answers that none exists (BT passes). Records each call."""

    def __init__(self, constructs: bool) -> None:
        self.constructs = constructs
        self.calls: list[dict] = []

    def complete(self, payload: Any, model_ref: Any, sampling: Any) -> Any:
        from types import SimpleNamespace

        self.calls.append(dict(payload.fields))
        response = "Because." if self.constructs else None
        return SimpleNamespace(text=json.dumps({
            "response": response,
            "divergence_note": "R1's broadened level takes it, R0's does not"
            if self.constructs else None}))


@contextmanager
def off_panel_checker(monkeypatch: Any, *, constructs: bool) -> Iterator[ScriptedOffPanel]:
    """Declare an off-panel checker (its env channel) and bind the stand-in to it."""
    from aeh.calib.off_panel import (
        CALIB_OFF_PANEL_MODEL_ENV,
        OffPanelModelRef,
        bind_off_panel_provider,
        unbind_off_panel_provider,
    )

    ref = OffPanelModelRef(provider="local", build_id="off-panel-checker")
    checker = ScriptedOffPanel(constructs)
    monkeypatch.setenv(CALIB_OFF_PANEL_MODEL_ENV, f"{ref.provider}/{ref.build_id}")
    bind_off_panel_provider(ref, checker)
    try:
        yield checker
    finally:
        unbind_off_panel_provider(ref)


def examples_checked(world: "Eng7Examples") -> None:
    """Upload the four sheets, mark them with the three-disagreement form, and grade them."""
    world.judge_rule = world.judge_rule or three_disagreements_rule
    _, job = world.upload()
    assert job["state"] == "succeeded", f"fixture: the upload job ended {job}"
    world.mark({stem: dict(THREE_DISAGREEMENTS_TEACHER) for stem in SHEETS})
    _, job = world.grade()
    assert job["state"] == "succeeded", f"fixture: the grading job ended {job}"


def uniform_bands(band_index: int = -1) -> dict[str, str]:
    """A form giving every judged criterion the band at `band_index` (worst first)."""
    return {criterion: bands[band_index] for criterion, bands in CRITERIA.items()}


@contextmanager
def eng7_examples(root: Path, work: Path, monkeypatch: Any, network_guard: Any,
                  judge_rule: "JudgeRule | None" = None,
                  config: Path = PANEL_CONFIG) -> Iterator[Eng7Examples]:
    """Ingest ENG7 into `root` under `config`, and serve a console over it. No run is started."""
    from aeh.conf import parse_config_document
    from aeh.console import serve_console
    from aeh.store import open_store

    for key in ("HARNESS_PROFILE", "HARNESS_FIXTURE_DIR", "CONSOLE_BIND",
                "HARNESS_CALIB_MAX_QUESTIONS", "HARNESS_CALIB_NONINFERIORITY_THRESHOLD",
                "HARNESS_CALIB_OFF_PANEL_MODEL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HARNESS_DECISION_ENGINE", "off")
    monkeypatch.setenv("CONSOLE_PORT", "0")
    root.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    store = None
    server = None
    try:
        world = ingest_eng7(root, work, monkeypatch, config)
        cfg = parse_config_document(config.read_text(encoding="utf-8"), "toml")
        served = Eng7Examples(world=_Ids(cohort_id=ENG7_COHORT), server=None, port=0,
                              root=root, package_version=world.package_version,
                              fake=world.fake, config=cfg, judge_rule=judge_rule)
        install_examples_transport(world.fake, lambda: served.judge_rule)
        served.sheets = {stem: (work / "answer-sheets" / f"{stem}.pdf").read_bytes()
                         for stem in SHEETS}
        served.test_paper = (work / "01-test-paper.pdf").read_bytes()
        store = open_store(root)
        network_guard.uninstall()
        with redirect_stdout(io.StringIO()):
            server = serve_console(store=store, cfg=cfg, config_path=str(config))
        served.server = server
        served.port = server.socket.getsockname()[1]
        yield served
    finally:
        try:
            if server is not None:
                server.terminate()
        finally:
            network_guard.install()
            forget_sample_modules()
            _reset_process_state()
            if store is not None:
                try:
                    store.close()
                except Exception as error:  # noqa: BLE001 — teardown after the assertions
                    if "can only be used in that same thread" not in str(error):
                        raise


def _reset_process_state() -> None:
    """The process-global state M-CALIB keeps between calls, cleared so no case reads another's:
    the elicitation session, the standing threshold, the examples guard, the R1 check guard and
    the class-roster cache."""
    from aeh.calib import elicitation, gates, rosters
    from aeh.calib import first_class
    from aeh.console import examples_actions

    elicitation._ACTIVE_QUESTIONS = []
    gates._clear_institutional_threshold()
    examples_actions._GRADING.clear()
    first_class._FINISHING.clear()
    getattr(rosters, "_CLASS_ROSTERS", {}).clear()


__all__ = ["CRITERIA", "Eng7Examples", "JOIN_TIMEOUT_ENV", "PANEL_CONFIG", "SHEETS",
           "eng7_examples", "install_examples_transport", "paper_of", "uniform_bands"]
