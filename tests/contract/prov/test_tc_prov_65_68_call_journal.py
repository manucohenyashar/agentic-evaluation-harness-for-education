"""The AI-call journal clause suite — every provider, one `CallRecord` per attempt.

Cases: `TC-PROV-65` (FR-PROV-44, CT-PROV-11, CT-PROV-32, P0), `TC-PROV-66` (FR-PROV-44, P1),
`TC-PROV-67` (FR-PROV-46, CT-PROV-31, RC-05, P0) and `TC-PROV-68` (FR-PROV-45, P1).
Issue #813 (story T2), written from `docs/design/console_clarity_test_plan.md` §3.3 against
`docs/design/console_clarity_design_delta.md` §3.8, ADR-51 and ADR-52. Implementing story: #807.

**The interface this suite assumes** (the design's names; #807 matches them):

- `aeh.prov.install_call_journal(sink)` — the one process-wide journal slot, read at emit
  time; `install_call_journal(None)` empties it. A sink is called once per record as
  `sink(record)`. (`_ListSink` below also answers `emit`, `append` and `write`, so a sink
  protocol spelled with one of those methods is served too.)
- `aeh.prov.call_context(kind=…, cohort_id=…, run_id=…, work_id=…, submission_id=…,
  criterion_id=…, package_id=…)` — a context manager over a `contextvars.ContextVar`.
- A record is a `CallRecord` (a dataclass, or anything with `to_dict()`/`as_dict()`, or a
  mapping) carrying at least FR-PROV-44's fields, the seven context fields at top level
  (`None` when unset).

**Isolation.** Rung 0/1 (§2.2): the three live providers run over their `Transport` seam with
canned HTTP replies (the `tests/contract/prov` pattern), the Jev SDK route through its real
TypeSafe client over a programmed transport (the `test_ts124_sdk_provider.py` pattern), the
fixture provider over a `tmp_path` recording. The list sink is the test's instrument, which
§2.2 allows in M-PROV unit cases only.

**Not implemented here, and why.** §2.2 says TC-PROV-65 *"asserts the file sink and the list
sink receive identical records"*. The design names no constructor for the file sink (FR-CONSOLE-77
gives its paths, not its name), so that parity arm is left to #807's own file-sink cases
(TC-CONSOLE-93/94, TC-STORE-30) rather than guessed at here. TC-PROV-67's byte scan runs over
each record serialized as one JSON line, which is what the file sink writes.

Markers. `contract`, and `writtenahead` until #807 lands `call_context` and
`install_call_journal` (entry `"#807 AI-call journal …"` in `WRITTEN_AHEAD_BLOCKERS`). Remove the
marker, never the test.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import random
import re
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from aeh.conf import ModelRef
from aeh.prov import (
    HttpResponse,
    JevOpenRouterProvider,
    LocalServerProvider,
    MalformedResponseError,
    OpenJevLocalProvider,
    OpenRouterProvider,
    PromptPayload,
    RecordedFixtureProvider,
    RetryPolicy,
    SamplingParams,
)
from tests.support import jev_corpora
from tests.support.clock import FrozenClock
from tests.support.impl import require
from tests.support.prov_contract import CountingClock, completion, flat_ok, model_ref, params, payload

pytestmark = [pytest.mark.contract]

ISSUE = "#807"

#: FR-PROV-44's field set, with FR-PROV-45's context fields at top level.
CONTEXT_FIELDS = ("cohort_id", "run_id", "work_id", "submission_id", "criterion_id", "package_id")
RECORD_FIELDS = frozenset({
    "call_id", "attempt", "at", "kind", *CONTEXT_FIELDS, "model", "resolved_build", "request",
    "response", "outcome", "error", "tokens_in", "tokens_out", "latency_ms", "cost",
})
OUTCOMES = frozenset({"ok", "retried", "malformed", "rejected", "failed"})

#: The five implementations of FR-PROV-44 / CT-PROV-32. `fixture` is exercised through both
#: of its doors (`complete` and `decide`), so it appears twice.
INFERENCE = ("openrouter", "local", "fixture")
DECISION = ("jev_openrouter", "openjev_local", "fixture")
DOORS = tuple(("complete", i) for i in INFERENCE) + tuple(("decide", i) for i in DECISION)
DOOR_IDS = tuple(f"{door}-{impl}" for door, impl in DOORS)

KEY = "sk-or-TESTKEY-0123456789"
JEV_REF = ModelRef(role="decision", provider="openrouter-jev",
                   build_id="openrouter/typesafe/jev-1.13@2026-09-01", quantization=None)
OJ_REF = ModelRef(role="decision", provider="openjev",
                  build_id="/models/openjev-FP8/model.safetensors@sha256:" + "ab" * 32,
                  quantization="fp8")
_WIRE = {b["id"]: b["body"] for b in jev_corpora.wire_bodies()}


# --- the instrument --------------------------------------------------------------------------------


class _ListSink:
    """The test's in-memory sink. Every spelling of "take this record" appends to `records`."""

    def __init__(self) -> None:
        self.records: list = []
        self._lock = threading.Lock()

    def __call__(self, record) -> None:  # noqa: ANN001
        with self._lock:
            self.records.append(record)

    emit = append = write = __call__


def _journal_api():
    return require("aeh.prov", "call_context", "install_call_journal", issue=ISSUE)


@pytest.fixture
def journal():
    """A list sink installed in the process-wide slot for the test, and emptied after it."""
    _, install = _journal_api()
    sink = _ListSink()
    install(sink)
    try:
        yield sink
    finally:
        install(None)


def _as_dict(record) -> dict:  # noqa: ANN001
    if dataclasses.is_dataclass(record) and not isinstance(record, type):
        return {f.name: getattr(record, f.name) for f in dataclasses.fields(record)}
    for name in ("to_dict", "as_dict"):
        method = getattr(record, name, None)
        if callable(method):
            return dict(method())
    if isinstance(record, Mapping):
        return dict(record)
    raise AssertionError(f"a journal record must be a CallRecord dataclass or a mapping; got {type(record).__name__}")


def _records(sink: _ListSink) -> list[dict]:
    return [_as_dict(r) for r in sink.records]


def _line(record: dict) -> bytes:
    """One record as the file sink writes it: one JSON line."""
    return json.dumps(record, default=str, ensure_ascii=False).encode("utf-8")


def _strings(value) -> list[str]:  # noqa: ANN001
    """Every string inside a nested request/response value."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [s for k, v in value.items() for s in (*_strings(k), *_strings(v))]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _strings(v)]
    return []


def _request_fields(request) -> list[tuple[str, str]]:  # noqa: ANN001
    """An inference record's `request` read back as the payload's (name, value) pairs."""
    if isinstance(request, Mapping) and "fields" in request:
        request = request["fields"]
    assert isinstance(request, (list, tuple)), f"request must be the payload fields in order, got {request!r}"
    return [tuple(pair) for pair in request]


# --- the providers ---------------------------------------------------------------------------------


class _Transport:
    """Programmed replies per send, the last repeating; requests kept for the header scan."""

    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.requests: list = []

    def send(self, request):  # noqa: ANN001
        self.requests.append(request)
        return self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]


def _http(status: int, body: dict | bytes, headers: dict | None = None) -> HttpResponse:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    return HttpResponse(status, headers or {}, raw)


def _inference(impl: str, transport, tmp_path, *, policy=None):  # noqa: ANN001
    clock, rng = CountingClock(), random.Random(20261020)
    if impl == "openrouter":
        return OpenRouterProvider(base_url="http://or/v1", api_key=KEY, transport=transport, clock=clock,
                                  rng=rng, policy=policy, retention_answers=lambda build: "yes")
    if impl == "local":
        return LocalServerProvider(base_url="http://local/v1", api_key=KEY, transport=transport,
                                   clock=clock, rng=rng, policy=policy)
    return RecordedFixtureProvider(fixture_dir=tmp_path / "fixtures")


def _jev_body() -> dict:
    return {**_WIRE["cloud-well-formed-reported"], "model": "typesafe/jev-1.13"}


def _edge_body() -> dict:
    return dict(_WIRE["edge-well-formed-reported"])


def _call(door: str, impl: str, tmp_path, prompt: PromptPayload | None = None):  # noqa: ANN001
    """Make exactly one call through one door of one implementation. Returns
    (returned value, transport or None, request object)."""
    if door == "complete":
        prompt = prompt or payload(PromptPayload)
        transport = _Transport(flat_ok())
        provider = _inference(impl, transport, tmp_path)
        if impl == "fixture":
            provider.record(prompt, model_ref(), params(), completion())
            transport = None
        return provider.complete(prompt, model_ref(), params()), transport, prompt
    request = jev_corpora.wire_request()
    if impl == "jev_openrouter":
        transport = _Transport(_http(200, _jev_body()))
        provider = JevOpenRouterProvider(api_key=KEY, transport=transport, clock=FrozenClock())
        return provider.decide(request, JEV_REF), transport, request
    if impl == "openjev_local":
        transport = _Transport(_http(200, _edge_body()))
        provider = OpenJevLocalProvider(transport=transport, clock=FrozenClock())
        return provider.decide(request, OJ_REF), transport, request
    provider = RecordedFixtureProvider(fixture_dir=tmp_path / "fixtures")
    provider.record_decision(request, OJ_REF, _edge_body())
    return provider.decide(request, OJ_REF), None, request


def _ref_for(door: str, impl: str) -> ModelRef:
    if door == "complete":
        return model_ref()
    return JEV_REF if impl == "jev_openrouter" else OJ_REF


# --- TC-PROV-65 ------------------------------------------------------------------------------------


@pytest.mark.parametrize(("door", "impl"), DOORS, ids=DOOR_IDS)
def test_tc_prov_65_one_call_is_exactly_one_fully_typed_record(door, impl, tmp_path, journal) -> None:
    """TC-PROV-65 — one `complete()`/`decide()` with a list sink installed emits exactly one
    record carrying FR-PROV-44's field set, typed, and agreeing with what the call returned."""
    got, _, request = _call(door, impl, tmp_path)
    records = _records(journal)
    assert len(records) == 1, f"TC-PROV-65 ({door}/{impl}): one call, one attempt → exactly 1 record; got {len(records)}"
    record = records[0]

    missing = RECORD_FIELDS - set(record)
    assert not missing, f"TC-PROV-65 ({door}/{impl}): the record lacks FR-PROV-44 fields {sorted(missing)}"

    assert isinstance(record["call_id"], str) and record["call_id"], "call_id must be a non-empty string"
    assert type(record["attempt"]) is int and record["attempt"] == 1, "a first attempt is attempt 1"
    at = datetime.fromisoformat(str(record["at"]).replace("Z", "+00:00"))
    assert at.utcoffset() == timedelta(0), f"`at` must be UTC ISO-8601, got {record['at']!r}"
    assert record["kind"] == "unlabelled", "a call made with no context records kind='unlabelled' (FR-PROV-45)"
    for name in CONTEXT_FIELDS:
        assert record[name] is None, f"no context was set, so {name} must be None, got {record[name]!r}"
    assert record["model"] == _ref_for(door, impl).build_id, "`model` is the requested build"
    assert record["outcome"] == "ok" and record["error"] is None

    # The figures are the call's own, not placeholders.
    assert record["resolved_build"] == got.resolved_build
    for name in ("tokens_in", "tokens_out", "latency_ms"):
        assert type(record[name]) is int and record[name] == getattr(got, name), (
            f"TC-PROV-65 ({door}/{impl}): {name}={record[name]!r}, the call returned {getattr(got, name)!r}")
    if got.cost is None:
        assert record["cost"] is None, "cost is null exactly where the call's cost is null (CT-PROV-03)"
    else:
        assert record["cost"] is not None and Decimal(str(record["cost"])) == got.cost

    if door == "complete":
        assert _request_fields(record["request"]) == list(request.fields), (
            "an inference record's request is the PromptPayload fields, in order")
        assert record["response"] == got.text, "an inference record's response is Completion.text verbatim"
    else:
        request_text = " ".join(_strings(record["request"]))
        response_text = " ".join(_strings(record["response"]))
        for question in request.questions:
            assert question.key in request_text, f"the Jev request must carry question {question.key!r}"
            assert question.key in response_text, f"the Jev response must carry the answer to {question.key!r}"
        assert record["response"], "the Jev response (answer probabilities) must not be empty"
    json.loads(_line(record))  # one JSON line, as the file sink writes it


@pytest.mark.parametrize(("door", "impl"), DOORS, ids=DOOR_IDS)
def test_tc_prov_65_no_sink_means_no_record_and_no_file(door, impl, tmp_path, monkeypatch) -> None:
    """TC-PROV-65 / CT-PROV-11 — with the slot empty the provider emits nothing and writes no
    file of its own (cwd and the fixture folder are the only places it could)."""
    _, install = _journal_api()
    sink = _ListSink()
    install(sink)
    install(None)
    monkeypatch.chdir(tmp_path)
    _call(door, impl, tmp_path)
    before_files = {p for p in tmp_path.rglob("*") if p.is_file()}
    _call(door, impl, tmp_path)  # a second call: the recording already exists, nothing new may appear
    after_files = {p for p in tmp_path.rglob("*") if p.is_file()}
    assert sink.records == [], "an emptied slot must reach no sink (CT-PROV-11)"
    assert after_files == before_files, f"the provider wrote files with no sink: {sorted(map(str, after_files - before_files))}"
    assert not (tmp_path / "logs").exists(), "with no sink the provider writes no journal file"
    for path in before_files:
        assert "fixtures" in path.parts, f"only the test's own recording may exist; found {path}"


# --- TC-PROV-66 ------------------------------------------------------------------------------------


@pytest.mark.parametrize("impl", ("openrouter", "local"))
def test_tc_prov_66_each_retry_is_its_own_record(impl, tmp_path, journal) -> None:
    """TC-PROV-66 — 429, 500, 200: three records, one `call_id`, attempts 1-2-3, outcomes
    retried, retried, ok. A journal that emitted per call (not per attempt) fails here."""
    transport = _Transport(_http(429, b"", {"Retry-After": "0"}), _http(500, b""), flat_ok())
    provider = _inference(impl, transport, tmp_path, policy=RetryPolicy(max_attempts=3))
    got = provider.complete(payload(PromptPayload), model_ref(), params())
    records = _records(journal)
    assert len(transport.requests) == 3
    assert [r["attempt"] for r in records] == [1, 2, 3], f"one record per attempt; got {[r.get('attempt') for r in records]}"
    assert [r["outcome"] for r in records] == ["retried", "retried", "ok"]
    assert len({r["call_id"] for r in records}) == 1, "the attempts of one call share one call_id"
    assert records[2]["error"] is None and records[2]["response"] == got.text
    for r in records[:2]:
        assert r["error"], "a retried attempt says why it was retried"
        assert "Traceback" not in str(r["error"])
    assert all(r["outcome"] in OUTCOMES for r in records)

    # A second call is a new call_id.
    transport.responses, transport.requests = [flat_ok()], []
    provider.complete(payload(PromptPayload), model_ref(), params())
    assert len(journal.records) == 4
    assert _records(journal)[3]["call_id"] != records[0]["call_id"]


@pytest.mark.parametrize("impl", ("openrouter", "local"))
def test_tc_prov_66_a_malformed_final_reply_is_journaled_as_malformed(impl, tmp_path, journal) -> None:
    """TC-PROV-66 — the budget ends on a malformed reply: the last record is `malformed`, its
    `error` names the error class and carries no traceback."""
    transport = _Transport(_http(429, b"", {"Retry-After": "0"}), _http(200, b"<html>not json</html>"))
    provider = _inference(impl, transport, tmp_path, policy=RetryPolicy(max_attempts=2))
    with pytest.raises(MalformedResponseError):
        provider.complete(payload(PromptPayload), model_ref(), params())
    records = _records(journal)
    assert [r["attempt"] for r in records] == [1, 2]
    assert [r["outcome"] for r in records] == ["retried", "malformed"]
    assert len({r["call_id"] for r in records}) == 1
    error = str(records[1]["error"])
    assert "MalformedResponseError" in error, f"error must carry the class name, got {error!r}"
    assert "Traceback" not in error and 'File "' not in error, "error carries no traceback"


# --- TC-PROV-67 ------------------------------------------------------------------------------------

_BASE64_RUN = re.compile(rb"[A-Za-z0-9+/=]{201,}")
_FORBIDDEN = (b"authorization", b"bearer", b"http-referer")
_DESCRIPTOR = re.compile(r"^\[page image: page \d+ of \d+, \d+ KB, sha256 [0-9a-f]{4}")


def _png(page: int) -> bytes:
    """A PNG-signed page image of ~6 KB; its base64 is a run far over 200 characters."""
    noise = random.Random(page).randbytes(6000)
    return b"\x89PNG\r\n\x1a\n" + noise


def _page_payload(page: int) -> PromptPayload:
    """One page of a 3-page paper, shaped like `M-INGEST`'s transcription request."""
    return PromptPayload(fields=(
        ("instruction", "Transcribe this page."),
        ("source_blob_hash", "sha256:" + "cd" * 32),
        ("page_no", str(page)),
        ("image_png_base64", base64.b64encode(_png(page)).decode("ascii")),
        ("image_width_px", "1240"),
        ("image_height_px", "1754"),
    ))


def _scan(records: list[dict], where: str) -> None:
    for record in records:
        line = _line(record)
        assert KEY.encode() not in line, f"TC-PROV-67 ({where}): the API key is in a journal line"
        lowered = line.lower()
        for word in _FORBIDDEN:
            assert word not in lowered, f"TC-PROV-67 ({where}): {word.decode()!r} is in a journal line"
        run = _BASE64_RUN.search(line)
        assert run is None, f"TC-PROV-67 ({where}): a base64 run of {len(run.group())} chars is in a journal line"


@pytest.mark.parametrize("impl", INFERENCE)
def test_tc_prov_67_page_reading_journals_no_key_header_or_image_bytes(impl, tmp_path, journal) -> None:
    """TC-PROV-67 / CT-PROV-31 / SEC-26 journal arm — a 3-page page-reading job over the three
    inference implementations: no key, header or base64 run in any line, and each page image
    is recorded as a `[page image: …]` descriptor."""
    call_context, _ = _journal_api()
    transports = []
    for page in (1, 2, 3):
        prompt = _page_payload(page)
        transport = _Transport(flat_ok(text=f"Page {page}: the student's answer."))
        provider = _inference(impl, transport, tmp_path)
        if impl == "fixture":
            provider.record(prompt, model_ref(), params(), completion(text=f"Page {page}."))
        with call_context(kind="page_reading", cohort_id="c1", submission_id="s1"):
            provider.complete(prompt, model_ref(), params())
        transports.append(transport)
    if impl != "fixture":
        # The scan is not vacuous: the key and the image really were on the wire.
        sent = transports[0].requests[0]
        assert dict(sent.headers).get("Authorization") == f"Bearer {KEY}"
        assert base64.b64encode(_png(1)) in bytes(sent.body)
    records = _records(journal)
    assert len(records) == 3
    _scan(records, impl)
    for page, record in zip((1, 2, 3), records):
        assert record["kind"] == "page_reading"
        image = base64.b64encode(_png(page)).decode("ascii")
        assert image not in " ".join(_strings(record["request"])), "the image bytes are in the record"
        descriptors = [s for s in _strings(record["request"]) if _DESCRIPTOR.match(s)]
        assert len(descriptors) == 1, f"page {page}: expected one `[page image: …]` descriptor in the request"
        digest = descriptors[0].split("sha256 ")[1][:4]
        assert digest in (hashlib.sha256(_png(page)).hexdigest()[:4], hashlib.sha256(image.encode()).hexdigest()[:4]), (
            "the descriptor's sha256 prefix must be the image's own")
        assert f"page {page} of" in descriptors[0], f"page {page}'s descriptor names another page: {descriptors[0]!r}"


@pytest.mark.parametrize("impl", DECISION)
def test_tc_prov_67_decisions_journal_no_key_or_header(impl, tmp_path, journal) -> None:
    """TC-PROV-67 over the decision implementations: the Jev request carries the key in its
    `Authorization` header on the wire, and none of it reaches the journal."""
    _, transport, _ = _call("decide", impl, tmp_path)
    if impl == "jev_openrouter":
        headers = {str(k).lower(): str(v) for k, v in dict(transport.requests[0].headers).items()}
        assert headers.get("authorization") == f"Bearer {KEY}", "the scan must not be vacuous"
    records = _records(journal)
    assert len(records) == 1
    _scan(records, impl)


# --- TC-PROV-68 ------------------------------------------------------------------------------------


def _fixture_provider(tmp_path, refs: list[str]) -> tuple[RecordedFixtureProvider, dict[str, PromptPayload]]:
    provider = RecordedFixtureProvider(fixture_dir=tmp_path / "fixtures")
    prompts = {}
    for ref in refs:
        prompt = PromptPayload(fields=(("system", "Score one criterion."), ("student_ref", ref),
                                       ("submission", f"answer of {ref}")))
        provider.record(prompt, model_ref(), params(), completion())
        prompts[ref] = prompt
    return provider, prompts


def _labels(record: dict) -> dict:
    return {name: record[name] for name in ("kind", *CONTEXT_FIELDS)}


def _unlabelled() -> dict:
    return {"kind": "unlabelled", **dict.fromkeys(CONTEXT_FIELDS)}


def test_tc_prov_68_the_context_labels_the_record_and_nesting_restores(tmp_path, journal) -> None:
    """TC-PROV-68 — inside `call_context(...)` the record carries exactly those fields; outside,
    `kind='unlabelled'`; a nested context restores the outer one on exit."""
    call_context, _ = _journal_api()
    provider, prompts = _fixture_provider(tmp_path, ["ref-1"])
    call = lambda: provider.complete(prompts["ref-1"], model_ref(), params())  # noqa: E731

    call()
    with call_context(kind="jev_decision", run_id="r1", work_id="w1", submission_id="s1", criterion_id="C2"):
        call()
        with call_context(kind="ai_judge", run_id="r9", work_id="w9", submission_id="s9", criterion_id="C9"):
            call()
        call()
    call()

    outer = {"kind": "jev_decision", "cohort_id": None, "run_id": "r1", "work_id": "w1",
             "submission_id": "s1", "criterion_id": "C2", "package_id": None}
    inner = {"kind": "ai_judge", "run_id": "r9", "work_id": "w9", "submission_id": "s9", "criterion_id": "C9"}
    records = _records(journal)
    assert len(records) == 5
    assert _labels(records[0]) == _unlabelled(), "a call outside any context is unlabelled"
    assert _labels(records[1]) == outer, "the record carries the context's fields exactly"
    assert {k: records[2][k] for k in inner} == inner, "the inner context labels the inner call"
    assert _labels(records[3]) == outer, "leaving the inner context restores the outer one"
    assert _labels(records[4]) == _unlabelled(), "leaving the outer context leaves nothing behind"


def test_tc_prov_68_each_thread_pool_worker_gets_its_own_ids(tmp_path, journal) -> None:
    """TC-PROV-68 — under a `ThreadPoolExecutor(8)`, each worker sets its own context and every
    record carries that worker's ids. Tasks reused on a pool thread after a labelled task
    record `unlabelled`: a context set by one task must not leak to the next."""
    call_context, _ = _journal_api()
    workers = 8
    provider, prompts = _fixture_provider(tmp_path, [f"ref-{i}" for i in range(workers)])
    gate = threading.Barrier(workers, timeout=10)

    def labelled(i: int) -> None:
        with call_context(kind="ai_judge", run_id=f"r{i}", work_id=f"w{i}", submission_id=f"s{i}",
                          criterion_id=f"C{i}"):
            gate.wait()  # all eight contexts are live at once before anyone calls
            for _ in range(3):
                provider.complete(prompts[f"ref-{i}"], model_ref(), params())

    def unlabelled(i: int) -> None:
        provider.complete(prompts[f"ref-{i}"], model_ref(), params())

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in [pool.submit(labelled, i) for i in range(workers)]:
            future.result()
        for future in [pool.submit(unlabelled, i) for i in range(workers)]:
            future.result()

    records = _records(journal)
    assert len(records) == workers * 3 + workers
    labelled_records = [r for r in records if r["kind"] != "unlabelled"]
    assert len(labelled_records) == workers * 3, "a pool thread's later task inherited an earlier task's context"
    for record in labelled_records:
        ref = dict(_request_fields(record["request"]))["student_ref"]
        i = ref.split("-")[1]
        assert _labels(record) == {"kind": "ai_judge", "cohort_id": None, "run_id": f"r{i}", "work_id": f"w{i}",
                                   "submission_id": f"s{i}", "criterion_id": f"C{i}", "package_id": None}, (
            f"the call for {ref} carries another worker's ids: {_labels(record)}")
