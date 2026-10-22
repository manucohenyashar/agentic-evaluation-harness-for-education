"""`TC-CONSOLE-95`, `TC-CONSOLE-102` and `TC-CONSOLE-103` (issue #824): the AI-call read
`GET /api/v1/ai-calls` and the `aeh logs ai-calls` CLI over a real journal.

Console clarity test plan §3.8, story T8. Implementation: #816 (the read and the CLI) over #807's
journal (`aeh.prov`: `call_context`, `JsonlCallJournal`).

| Case | What is asserted |
|---|---|
| CONSOLE-95 (FR-CONSOLE-78, CT-PROV-32) | newest first, 50 per page (page 2 holds the rest); `student=<name>`, `question_id=Q2`, `kind=jev_decision` and `outcome=ok` each return exactly the records they name and **exclude** the rest (exact counts fixed by the world, so a filter that returns everything fails); every item carries FR-CONSOLE-78's teacher label for its kind, the student's listed name, the question, and `request`/`response` equal to the journal's; a fixture-provider record and a canned live-provider record are read alike |
| CONSOLE-102 (FR-UI-35, CT-CONSOLE-09 amended) | the same read over the `real` seed cohort returns its Jev records, named; with no `kind` the read answers `jev_decision,ai_judge` only; `/api/v1/logs` (Run steps) for that run carries no per-student figure and names no student |
| CONSOLE-103 (FR-CONSOLE-79) | `python -m aeh logs ai-calls --data-dir D --run R --student "Tomas Reader" --question Q2`: one summary line per call, newest first; `--full` adds each request and response verbatim; `--json` lines parse to the journal's own records; an unknown student prints "No AI calls match." and exits 0; a missing data folder exits 2 with a plain message and creates nothing |

**The world (rung 3).** A real store; the shipped ENG7 package built through `aeh package
build`'s path (`clarity_world.build_eng7_package`; C1a and C1b grade Q1, C2 grades Q2, C3 Q3); a
`synthetic` class with "Tomas Reader" and "Dana Levi" and a run created by the real
`Orchestrator`; and the clarity seed's `real` cohort (`seed_jev_final`, students E7-001 and
E7-002) administering the same version. The journal is written by the real `JsonlCallJournal`
from real provider calls, each inside the `call_context` the pipeline sets for that kind:
`RecordedFixtureProvider` for every call but two cells, and — the shape-parity arm — Tomas's Q2
cell through the live `JevOpenRouterProvider` and `OpenRouterProvider` over a canned transport
(the `tests/contract/prov` pattern), the judge call's first attempt a 503 so one record is not
`ok`. The journal's clock (`aeh.prov.journal.datetime.now`) is ticked one second per record so
"newest first" has one right answer; the read is served by a real console on a loopback port.

**Disclosed divergence.** The plan says *"after TC-PROV-69's run"*. That run's corpus
(F-JEV-DECISIONS) has no named roster and no `Q2` question, so neither the name filter nor the
plan's `question_id=Q2` could be asserted over it; the records here come from the same provider
code paths and the same journal sink, labelled the way the pipeline labels them.

**Not here.** FR-UI-35's *SPA* half (the AI-calls tab opening on the grading filter) is #823's,
covered by TC-UI-34; this file asserts the read's own default, which is what the tab asks for.

**Markers.** `integration` (the fast tier excludes it). Not written ahead: #816 and #807 are
merged.
"""

from __future__ import annotations

import itertools
import json
import os
import random
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

# The full migration chain before the first store open (CLAUDE.md).
import aeh.agg  # noqa: F401
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.conf import ModelRef
from aeh.console import serve_console
from aeh.prov import (
    HttpResponse,
    JevOpenRouterProvider,
    JsonlCallJournal,
    OpenRouterProvider,
    PromptPayload,
    RecordedFixtureProvider,
    call_context,
    journal_installed,
)
from aeh.prov import journal as journal_module
from aeh.prov.journal import iter_call_records
from aeh.store import open_store
from tests.support import jev_corpora
from tests.support.clarity_world import build_eng7_package, seed_jev_final
from tests.support.clock import FrozenClock
from tests.support.console_redesign_world import _close_console_store, _request
from tests.support.console_security_vocabulary import per_student_progress_figures
from tests.support.prov_contract import CountingClock, completion, flat_ok, model_ref, params

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]

CLASS = "ai-calls-class"
TOMAS = "Tomas Reader"
DANA = "Dana Levi"
NAMES = {TOMAS: "ref-tomas", DANA: "ref-dana"}
SUBMISSIONS = {TOMAS: "sub-tomas", DANA: "sub-dana"}
#: ENG7's judged lines and the question each grades (C1 = C1a + C1b is Q1's checklist).
QUESTION_OF = {"C1a": "Q1", "C1b": "Q1", "C2": "Q2", "C3": "Q3"}
#: FR-CONSOLE-78's teacher labels, transcribed from the design (not imported from the module).
LABELS = {
    "jev_decision": "Jev decision", "ai_judge": "AI judge", "page_reading": "Page reading",
    "package_drafting": "Package drafting", "answer_extraction": "Answer finding",
    "feedback_writing": "Feedback writing", "help_question": "Help question",
}
PAGES_PER_PAPER = 10
#: The run's per-cell kinds, in the order the pipeline calls them.
CELL_KINDS = ("answer_extraction", "jev_decision", "ai_judge", "feedback_writing")
#: The live-provider cell (the CT-PROV-32 arm).
LIVE_CELL = (TOMAS, "C2")

KEY = "sk-or-TESTKEY-0123456789"
JEV_REF = ModelRef(role="decision", provider="openrouter-jev",
                   build_id="openrouter/typesafe/jev-1.13@2026-09-01", quantization=None)
OJ_REF = ModelRef(role="decision", provider="openjev",
                  build_id="/models/openjev-FP8/model.safetensors@sha256:" + "ab" * 32,
                  quantization="fp8")
_WIRE = {b["id"]: b["body"] for b in jev_corpora.wire_bodies()}
BASE_AT = datetime(2026, 10, 21, 8, 0, 0, tzinfo=timezone.utc)


@dataclass
class AiCallWorld:
    data_dir: Path
    run_id: str
    real_run_id: str
    real_submissions: dict[str, str]
    #: Every journal record, in the order it was emitted (= ascending `at`).
    records: list[dict[str, Any]]
    #: The (provider family, kind, submission, criterion) of every emitted record, in order.
    emitted: list[tuple[str, str, str | None, str | None]]


class _Transport:
    """Programmed replies per send, the last repeating."""

    def __init__(self, *responses: HttpResponse) -> None:
        self.responses = list(responses)
        self.sent = 0

    def send(self, request: Any) -> HttpResponse:
        self.sent += 1
        return self.responses[min(self.sent - 1, len(self.responses) - 1)]


def _ticking_datetime() -> type:
    """`datetime` whose `now()` moves one second per call: one distinct `at` per record."""
    ticks = itertools.count()

    class _Ticking(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # noqa: ANN401
            return BASE_AT + timedelta(seconds=next(ticks))

    return _Ticking


def _prompt(*parts: str) -> PromptPayload:
    return PromptPayload(fields=(("system", f"The {parts[0]} instruction."),
                                 ("submission", " / ".join(parts))))


def _seed_class(store: Any, package: tuple[str, str]) -> str:
    """The synthetic class: two named students, one paper each, one run (the real orchestrator)."""
    from aeh.conf import CohortRef, resolve_run_config
    from aeh.orch import Orchestrator
    from aeh.orch.cohorts import RosterEntry, create_cohort
    from tests.support.conf_builders import edge_cfg

    create_cohort(store, CLASS, "synthetic",
                  [RosterEntry(full_name=name, student_ref=ref) for name, ref in NAMES.items()],
                  created_at=BASE_AT.isoformat())
    with store.cohort(CLASS).transaction() as tx:
        for name, submission_id in SUBMISSIONS.items():
            tx.execute("INSERT INTO submission (submission_id, cohort_id, student_ref) "
                       "VALUES (:s, :c, :r)", s=submission_id, c=CLASS, r=NAMES[name])
    resolved = resolve_run_config(edge_cfg(), CohortRef(cohort_id=CLASS, consent_class="synthetic"))
    return Orchestrator(store, clock=lambda: BASE_AT.isoformat()).create_run(
        CLASS, package[1], resolved, run_id=f"run-{CLASS}")


def _journal_calls(fixture_dir: Path, run_id: str, real_run_id: str,
                   real_submissions: dict[str, str]) -> list[tuple[str, str, str | None, str | None]]:
    """Every AI call of the world, each inside the context the pipeline sets for its kind."""
    fixture = RecordedFixtureProvider(fixture_dir=fixture_dir)
    decision = jev_corpora.wire_request()
    fixture.record_decision(decision, OJ_REF, dict(_WIRE["edge-well-formed-reported"]))
    emitted: list[tuple[str, str, str | None, str | None]] = []

    def complete(kind: str, *parts: str) -> None:
        prompt = _prompt(kind, *parts)
        fixture.record(prompt, model_ref(), params(),
                       completion(text=json.dumps({"kind": kind, "for": list(parts)})))
        fixture.complete(prompt, model_ref(), params())

    for name, submission_id in SUBMISSIONS.items():  # intake: page reading, no run yet
        for page in range(1, PAGES_PER_PAPER + 1):
            with call_context(kind="page_reading", cohort_id=CLASS, submission_id=submission_id):
                complete("page_reading", submission_id, f"page {page}")
            emitted.append(("fixture", "page_reading", submission_id, None))
    for name, submission_id in SUBMISSIONS.items():
        for criterion_id in QUESTION_OF:
            for kind in CELL_KINDS:
                labels = dict(kind=kind, cohort_id=CLASS, run_id=run_id,
                              work_id=f"w-{submission_id}-{criterion_id}-{kind}",
                              submission_id=submission_id, criterion_id=criterion_id)
                live = (name, criterion_id) == LIVE_CELL
                with call_context(**labels):
                    if kind == "jev_decision" and live:
                        transport = _Transport(HttpResponse(200, {}, json.dumps(
                            {**_WIRE["cloud-well-formed-reported"],
                             "model": "typesafe/jev-1.13"}).encode("utf-8")))
                        JevOpenRouterProvider(api_key=KEY, transport=transport,
                                              clock=FrozenClock()).decide(decision, JEV_REF)
                        emitted.append(("live", kind, submission_id, criterion_id))
                    elif kind == "jev_decision":
                        fixture.decide(decision, OJ_REF)
                        emitted.append(("fixture", kind, submission_id, criterion_id))
                    elif kind == "ai_judge" and live:
                        transport = _Transport(HttpResponse(503, {}, b'{"error": "busy"}'),
                                               flat_ok(text='{"band": "adequate"}'))
                        OpenRouterProvider(
                            base_url="http://or/v1", api_key=KEY, transport=transport,
                            clock=CountingClock(), rng=random.Random(20261022),
                            retention_answers=lambda build: "yes",
                        ).complete(_prompt(kind, submission_id, criterion_id), model_ref(), params())
                        emitted.append(("live", kind, submission_id, criterion_id))  # the 503
                        emitted.append(("live", kind, submission_id, criterion_id))  # the retry
                    else:
                        complete(kind, submission_id, criterion_id)
                        emitted.append(("fixture", kind, submission_id, criterion_id))
    # The real class: its Jev decisions, and one feedback call each (outside the default filter).
    for name, submission_id in real_submissions.items():
        for criterion_id in QUESTION_OF:
            with call_context(kind="jev_decision", cohort_id="eng7-clarity-real",
                              run_id=real_run_id, work_id=f"w-{submission_id}-{criterion_id}",
                              submission_id=submission_id, criterion_id=criterion_id):
                fixture.decide(decision, OJ_REF)
            emitted.append(("fixture", "jev_decision", submission_id, criterion_id))
        with call_context(kind="feedback_writing", cohort_id="eng7-clarity-real",
                          run_id=real_run_id, submission_id=submission_id):
            complete("feedback_writing", submission_id)
        emitted.append(("fixture", "feedback_writing", submission_id, None))
    return emitted


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> AiCallWorld:
    scratch = tmp_path_factory.mktemp("ai-calls")
    data_dir = scratch / "data"
    for tier in ("packages", "cohorts"):
        (data_dir / tier).mkdir(parents=True)
    store = open_store(data_dir)
    try:
        package = build_eng7_package(store)
        run_id = _seed_class(store, package)
        real = seed_jev_final(store, consent_class="real", package=package)
    finally:
        store.close()
    with pytest.MonkeyPatch.context() as mp, journal_installed(JsonlCallJournal(data_dir)):
        mp.setattr(journal_module, "datetime", _ticking_datetime())
        emitted = _journal_calls(scratch / "fixtures", run_id, real.run_id, real.submissions)
    records = sorted(iter_call_records(data_dir), key=lambda r: r["at"])
    # Preconditions: one record per emitted call attempt, in emission order, ticks distinct.
    assert [(r["kind"], r["submission_id"], r["criterion_id"]) for r in records] == [
        (kind, sub, crit) for _family, kind, sub, crit in emitted], "the journal is not the calls"
    assert len({r["at"] for r in records}) == len(records)
    return AiCallWorld(data_dir=data_dir, run_id=run_id, real_run_id=real.run_id,
                       real_submissions=real.submissions, records=records, emitted=emitted)


@pytest.fixture
def port(world: AiCallWorld, network_guard, monkeypatch) -> Any:
    """A real console over the world's data folder on a loopback port, default knobs."""
    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT",
                 "HARNESS_CONSOLE_AI_CALLS_PAGE"):
        monkeypatch.delenv(name, raising=False)
    store = open_store(world.data_dir)
    network_guard.uninstall()
    try:
        server = serve_console(store=store)
        try:
            yield server.socket.getsockname()[1]
        finally:
            server.terminate()
    finally:
        network_guard.install()
        _close_console_store(store)


def _read(port: int, **query: Any) -> dict[str, Any]:
    path = "/api/v1/ai-calls?" + urllib.parse.urlencode(query)
    status, _headers, raw = _request(port, "GET", path)
    assert status == 200, f"GET {path} answered {status}: {raw[:400]!r}"
    return json.loads(raw)


def _newest_first(records: list[dict[str, Any]]) -> list[tuple[str, int]]:
    return [(r["call_id"], r["attempt"]) for r in sorted(records, key=lambda r: r["at"],
                                                          reverse=True)]


def _ids(items: list[dict[str, Any]]) -> list[tuple[str, int]]:
    return [(item["call_id"], item["attempt"]) for item in items]


def _name_of(world: AiCallWorld) -> dict[str, str]:
    names = {sub: name for name, sub in SUBMISSIONS.items()}
    names.update({sub: name for name, sub in world.real_submissions.items()})
    return names


def _check_items(world: AiCallWorld, items: list[dict[str, Any]]) -> None:
    """Every item: the teacher label, the listed name, the question, request/response in full."""
    raw = {(r["call_id"], r["attempt"]): r for r in world.records}
    names = _name_of(world)
    problems = []
    for item in items:
        record = raw[(item["call_id"], item["attempt"])]
        expected = {
            "kind": record["kind"],
            "kind_label": LABELS[record["kind"]],
            "student_name": names.get(record["submission_id"]),
            "question": QUESTION_OF.get(record["criterion_id"]),
            "request": record["request"],
            "response": record["response"],
            "outcome": record["outcome"],
            "model": record["model"],
            "at": record["at"],
        }
        got = {key: item.get(key) for key in expected}
        if got != expected:
            problems.append(f"{item['call_id']}#{item['attempt']}: "
                            f"{ {k: (got[k], expected[k]) for k in expected if got[k] != expected[k]} }")
    assert not problems, "\n".join(problems[:10])


# --- TC-CONSOLE-95 ------------------------------------------------------------------------------


def test_tc_console_95_newest_first_fifty_per_page(world, port):
    """`TC-CONSOLE-95`: the class's 53 records, newest first, 50 on page 1 and 3 on page 2."""
    class_records = [r for r in world.records if r["cohort_id"] == CLASS]
    assert len(class_records) == 2 * PAGES_PER_PAPER + 2 * 4 * 4 + 1  # +1: the retried attempt
    expected = _newest_first(class_records)
    first = _read(port, cohort_id=CLASS, kind="all")
    second = _read(port, cohort_id=CLASS, kind="all", page=2)
    assert (first["page_size"], first["total"], first["more"]) == (50, 53, True), first["filters"]
    assert (second["total"], second["more"]) == (53, False)
    assert _ids(first["items"]) == expected[:50]
    assert _ids(second["items"]) == expected[50:]
    _check_items(world, first["items"] + second["items"])


@pytest.mark.parametrize(("query", "keep", "count"), [
    ({"student": TOMAS},
     lambda r: r["submission_id"] == SUBMISSIONS[TOMAS], 4 * 4 + 1),
    ({"question_id": "Q2"},
     lambda r: r["criterion_id"] == "C2", 2 * 4 + 1),
    ({"kind": "jev_decision"},
     lambda r: r["kind"] == "jev_decision", 2 * 4),
    ({"outcome": "ok"},
     lambda r: r["outcome"] == "ok", 2 * 4 * 4),
], ids=["student", "question_id", "kind", "outcome"])
def test_tc_console_95_each_filter_narrows_to_exactly_its_records(world, port, query, keep, count):
    """`TC-CONSOLE-95`: each filter over the run returns exactly the records it names, newest
    first, and excludes the rest — the run holds 33 records, so returning everything fails."""
    run_records = [r for r in world.records if r["run_id"] == world.run_id]
    assert len(run_records) == 33
    expected = [r for r in run_records if keep(r)]
    assert len(expected) == count, "the world no longer has the shape the counts assume"
    answer = _read(port, run_id=world.run_id, **({"kind": "all"} | query))
    assert answer["total"] == count, (query, answer["total"], answer["projected"])
    assert _ids(answer["items"]) == _newest_first(expected)
    _check_items(world, answer["items"])
    if "student" in query:
        assert {item["student_name"] for item in answer["items"]} == {TOMAS}


def test_tc_console_95_run_and_default_kind_narrow(world, port):
    """`TC-CONSOLE-95`: `run_id` drops the class's intake calls, and with no `kind` only the
    grading calls (`jev_decision`, `ai_judge`) are answered."""
    answer = _read(port, run_id=world.run_id)
    run_records = [r for r in world.records if r["run_id"] == world.run_id]
    expected = [r for r in run_records if r["kind"] in ("jev_decision", "ai_judge")]
    assert len(expected) == 8 + 8 + 1
    assert answer["total"] == len(expected)
    assert _ids(answer["items"]) == _newest_first(expected)


def test_tc_console_95_a_fixture_record_and_a_live_record_read_alike(world, port):
    """`TC-CONSOLE-95` / CT-PROV-32: a fixture-provider record and a canned live-provider record
    of the same kind come back with the same fields, both named, both with request and
    response in full."""
    answer = _read(port, run_id=world.run_id, question_id="Q2", kind="jev_decision")
    by_student = {item["student_name"]: item for item in answer["items"]}
    assert set(by_student) == {TOMAS, DANA}
    live, fixture = by_student[TOMAS], by_student[DANA]
    families = {(sub, crit, kind): family for family, kind, sub, crit in world.emitted}
    assert families[(SUBMISSIONS[TOMAS], "C2", "jev_decision")] == "live"
    assert families[(SUBMISSIONS[DANA], "C2", "jev_decision")] == "fixture"
    assert live["model"] != fixture["model"], "precondition: two different providers"
    raw = {(r["call_id"], r["attempt"]): r for r in world.records}
    assert set(raw[(live["call_id"], live["attempt"])]) == set(
        raw[(fixture["call_id"], fixture["attempt"])]), "the journal records differ in shape"
    assert set(live) == set(fixture)
    for item in (live, fixture):
        assert item["kind_label"] == "Jev decision" and item["question"] == "Q2"
        assert item["request"] and item["response"], item
    _check_items(world, [live, fixture])
    judge = _read(port, run_id=world.run_id, question_id="Q2", kind="ai_judge",
                  student=TOMAS)["items"]
    assert [item["outcome"] for item in judge] == ["ok", "retried"], judge


# --- TC-CONSOLE-102 -----------------------------------------------------------------------------


def test_tc_console_102_a_real_class_s_jev_records_are_read_by_name(world, port):
    """`TC-CONSOLE-102` (FR-UI-35, CT-CONSOLE-09 amended): the `real` cohort's Jev records come
    back, named, with no consent filter; with no `kind` the read is `jev_decision,ai_judge`."""
    real = [r for r in world.records if r["run_id"] == world.real_run_id]
    jev = [r for r in real if r["kind"] == "jev_decision"]
    assert len(real) == 10 and len(jev) == 8
    answer = _read(port, run_id=world.real_run_id)
    assert answer["filters"]["kind"] == ["jev_decision", "ai_judge"]
    assert answer["total"] == 8
    assert _ids(answer["items"]) == _newest_first(jev)
    assert {item["student_name"] for item in answer["items"]} == set(world.real_submissions)
    _check_items(world, answer["items"])
    assert _read(port, run_id=world.real_run_id, kind="all")["total"] == 10


def test_tc_console_102_run_steps_still_carries_no_per_student_figure(world, port):
    """`TC-CONSOLE-102`: `/api/v1/logs` (Run steps) for the real run names no student and
    carries no per-student figure (CT-CONSOLE-09's narrowed scope)."""
    status, _headers, raw = _request(port, "GET", f"/api/v1/logs?run_id={world.real_run_id}")
    assert status == 200, raw[:400]
    payload = json.loads(raw)
    assert per_student_progress_figures(payload) == []
    text = raw.decode("utf-8")
    leaked = [token for name, sub in world.real_submissions.items()
              for token in (name, sub, f"ref-{name.lower()}") if token in text]
    assert not leaked, f"Run steps names students: {leaked}"


# --- TC-CONSOLE-103 -----------------------------------------------------------------------------


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO / "src"), str(REPO)])}
    return subprocess.run([sys.executable, "-m", "aeh", "logs", "ai-calls", *args],
                          capture_output=True, text=True, encoding="utf-8", env=env,
                          timeout=120)


def _verbatim(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False)


def _tomas_q2(world: AiCallWorld) -> list[dict[str, Any]]:
    """Tomas's Q2 calls in the run, newest first: every kind (the CLI's default)."""
    found = [r for r in world.records if r["run_id"] == world.run_id
             and r["submission_id"] == SUBMISSIONS[TOMAS] and r["criterion_id"] == "C2"]
    return sorted(found, key=lambda r: r["at"], reverse=True)


def _base(world: AiCallWorld) -> list[str]:
    return ["--data-dir", str(world.data_dir), "--run", world.run_id,
            "--student", TOMAS, "--question", "Q2"]


def test_tc_console_103_one_summary_line_per_call(world):
    """`TC-CONSOLE-103`: one line per call, newest first, each naming its kind, the student and
    the question."""
    expected = _tomas_q2(world)
    assert len(expected) == 5
    done = _cli(*_base(world))
    assert done.returncode == 0, done.stderr[-1500:]
    lines = done.stdout.splitlines()
    assert len(lines) == len(expected), done.stdout
    for line, record in zip(lines, expected):
        assert line.startswith(record["at"]), (line, record["at"])
        for part in (LABELS[record["kind"]], TOMAS, "Q2", record["outcome"]):
            assert part in line, (part, line)


def test_tc_console_103_full_adds_request_and_response(world):
    """`TC-CONSOLE-103`: `--full` prints each call's request and response verbatim under it."""
    done = _cli(*_base(world), "--full")
    assert done.returncode == 0, done.stderr[-1500:]
    out = done.stdout
    assert out.count("What the AI was asked:") == 5 and out.count("What it answered:") == 5
    lines = set(line.strip() for line in out.splitlines())
    for record in _tomas_q2(world):
        for field in ("request", "response"):
            if record[field] is None:
                continue
            for text in _verbatim(record[field]).splitlines():
                assert text.strip() in lines, (record["kind"], field, text)


def test_tc_console_103_json_lines_are_the_journal_records(world):
    """`TC-CONSOLE-103`: `--json` lines parse to the journal's own records, newest first."""
    done = _cli(*_base(world), "--json")
    assert done.returncode == 0, done.stderr[-1500:]
    parsed = [json.loads(line) for line in done.stdout.splitlines()]
    assert parsed == _tomas_q2(world)


def test_tc_console_103_unknown_student_is_an_empty_answer(world):
    """`TC-CONSOLE-103`: no match prints "No AI calls match." and exits 0."""
    done = _cli("--data-dir", str(world.data_dir), "--run", world.run_id,
                "--student", "Nobody Known")
    assert (done.returncode, done.stdout) == (0, "No AI calls match.\n"), done.stderr


def test_tc_console_103_missing_data_folder_exits_2_plainly(tmp_path):
    """`TC-CONSOLE-103`: a data folder that is not there exits 2 with a plain message and
    creates nothing."""
    missing = tmp_path / "no-such-data"
    done = _cli("--data-dir", str(missing), "--student", TOMAS)
    assert done.returncode == 2, (done.stdout, done.stderr)
    assert done.stdout == ""
    assert "data folder" in done.stderr and "Traceback" not in done.stderr, done.stderr
    assert not missing.exists()
