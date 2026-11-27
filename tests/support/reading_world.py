"""The console's reading job over the sample physics class, with a probing page reader.

Shared by `TC-CONSOLE-123` (the reading estimate, ceiling, pause and resume) and `TC-PROV-71`'s
reading-job half (retention verified for the transcriber before the first page leaves), issue
#905 (statistical-validity test plan r2 §3.23). It is `TC-CONSOLE-77`'s world: the sample
physics package built from its spec, a class made through the console's own `import roster file`
control, and the pages sent through a real `OpenRouterProvider` to a stand-in OpenRouter in the
process. Only the transport is a stand-in.

What this world adds to `TC-CONSOLE-77`'s:

* **A priced reader.** Every page request answers with `usage.cost = cost_per_request`, so a
  ceiling of 0.01 is reached by the first file (0.00001, the base stand-in's figure, never
  reaches it).
* **A gate.** `hold()` makes the first page request wait until `release()`, so every file a case
  uploads is queued into the one job before the first file finishes — without it, "pauses after
  the first file" would race the later uploads.
* **A probe census.** `ProbingOpenRouter.verify_retention` records the builds each call asks
  about, in one event log with every request the transport saw, so an ordering assertion
  ("before the first page") reads one sequence.
* **A known per-page estimate.** `estimate_cost` answers `calls x PER_PAGE_ESTIMATE` whatever
  the token budgets, so a confirmation's figure is checkable as pages x the per-page estimate
  without this file guessing the budgets the implementation picks.
"""

from __future__ import annotations

import http.client
import json
import sqlite3
import sys
import threading
import time
from decimal import Decimal
from typing import Any

from aeh.prov import CostEstimate, HttpResponse, OpenRouterProvider
from aeh.prov.live import _fields_from_wire

#: The per-call estimate the probing reader's `estimate_cost` answers.
PER_PAGE_ESTIMATE = Decimal("0.0042")


class PricedOpenRouter:
    """A stand-in OpenRouter for page reading: answers each page with its staged transcript and
    `cost_per_request`, logs every request into `events`, and can hold the first page."""

    def __init__(self, transcriber: str, events: list, cost_per_request: str = "0.02") -> None:
        self.transcriber = transcriber
        self.pages: dict[tuple[str, int], str] = {}
        self.requests: list = []
        self.page_hashes: list[str] = []
        self.events = events
        self.cost = cost_per_request
        self._gate: threading.Event | None = None

    def hold(self) -> None:
        self._gate = threading.Event()

    def release(self) -> None:
        if self._gate is not None:
            self._gate.set()

    def send(self, request):  # noqa: ANN001
        self.events.append(("send", request.method, request.url))
        self.requests.append(request)
        if self._gate is not None and request.method == "POST":
            self._gate.wait(timeout=60)
        if request.method != "POST":
            return HttpResponse(200, {}, b'{"data": []}')
        body = json.loads(request.body)
        fields = dict((name, value) for name, value in _fields_from_wire(body))
        if fields.get("instruction", "").startswith("Decide whether"):
            text = "uncertain"
        else:
            source = fields["source_blob_hash"]
            self.page_hashes.append(source)
            text = self.pages[(source, int(fields["page_no"]))]
        return HttpResponse(200, {}, json.dumps({
            "model": self.transcriber,
            "choices": [{"finish_reason": "stop", "message": {"content": text}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": float(self.cost)},
        }).encode("utf-8"))


class ProbingOpenRouter(OpenRouterProvider):
    """The real provider, with `verify_retention` recorded into the shared event log and the
    per-call estimate fixed at `PER_PAGE_ESTIMATE`."""

    def __init__(self, *, events: list, unconfirmed: frozenset[str] = frozenset(),
                 **kwargs: Any) -> None:
        self.events = events
        self.probed: list[str] = []
        self._unconfirmed = unconfirmed
        super().__init__(retention_answers=self._answer, **kwargs)

    def _answer(self, build_id: str) -> str:
        return "retention: standard" if build_id in self._unconfirmed else "zero-retention"

    def verify_retention(self, model_refs):  # noqa: ANN001
        builds = [ref.build_id for ref in model_refs]
        self.probed.extend(builds)
        self.events.append(("probe", tuple(builds)))
        return super().verify_retention(model_refs)

    def estimate_cost(self, plan):  # noqa: ANN001
        return CostEstimate(calls=plan.calls, tokens_in=plan.calls * plan.tokens_in_per_call,
                            tokens_out=plan.calls * plan.tokens_out_per_call,
                            cost=PER_PAGE_ESTIMATE * plan.calls)


def request(port: int, method: str, path: str, body: bytes = b"",
            content_type: str = "application/json") -> tuple[int, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        connection.request(method, path, body=body,
                           headers={"Content-Type": content_type,
                                    "Content-Length": str(len(body))})
        response = connection.getresponse()
        raw = response.read()
    finally:
        connection.close()
    try:
        return response.status, json.loads(raw.decode("utf-8"))
    except ValueError:
        return response.status, raw


def upload(port: int, data: bytes, **query: str) -> tuple[int, Any]:
    from urllib.parse import urlencode

    return request(port, "POST", f"/api/v1/uploads?{urlencode({'read': '1', **query})}",
                   data, "application/pdf")


def is_paused(record: dict[str, Any]) -> bool:
    return record.get("state") == "paused" or record.get("paused") is True


def wait_settled(port: int, job_id: str, timeout: float = 60.0) -> dict[str, Any]:
    """The job once it is finished or paused, or the last record seen at the deadline."""
    deadline = time.monotonic() + timeout
    while True:
        status, record = request(port, "GET", f"/api/v1/jobs/{job_id}")
        assert status == 200, record
        if is_paused(record) or record["state"] not in ("queued", "running"):
            return record
        if time.monotonic() >= deadline:
            return record
        time.sleep(0.1)


def make_class(port: int, roster: str, class_id: str = "ps9-class") -> None:
    status, answer = request(port, "POST", "/api/v1/actions/import-roster-file", json.dumps({
        "class_id": class_id, "consent_class": "synthetic", "content": roster,
        "name": "roster.txt"}).encode("utf-8"))
    assert status == 200 and answer["dispatched"] is True, answer


def reading_world(tmp_data_dir, monkeypatch, capsys, network_guard, *,
                  unconfirmed: frozenset[str] = frozenset()):
    """A generator for a pytest fixture: yields the world dict, tears the console down."""
    import pytest

    from aeh.conf import effective_config
    from aeh.pipeline import background, cli
    from aeh.pipeline.runtime import _open_store
    from tests.support.guards import loopback_census
    from tests.support.live_test_config import configured_builds
    from tests.unit.pipe.test_ingest_command import (
        DEV_CI_CONFIG, SAMPLE_SPEC, SAMPLES, TRANSCRIBER)

    pytest.importorskip("pypdfium2")
    monkeypatch.syspath_prepend(str(SAMPLES))
    import build_sample_materials as sm
    import verify_sample_materials as v

    for key in ("HARNESS_FIXTURE_DIR", "HARNESS_PROFILE", "HARNESS_READ_COST_CEILING",
                "HARNESS_RETENTION_PRECHECK"):
        monkeypatch.delenv(key, raising=False)
    files = sm.build_all()
    events: list = []
    fake = PricedOpenRouter(TRANSCRIBER, events)
    assert cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                     "--spec", str(SAMPLE_SPEC)]) == 0
    version = json.loads(capsys.readouterr().out)["package_version"]
    store = _open_store(str(tmp_data_dir))
    blobs = store.blobs()
    paper = files[f"{sm.PHYSICS_ID}/01-test-paper.pdf"]
    paper_hash = blobs.put(paper)
    fake.pages[(paper_hash, 1)] = v.assessment_transcript(sm.PHYSICS_ID)
    sheets: dict[str, bytes] = {}
    sheet_hashes: dict[str, str] = {}
    for sheet in sm.PHYSICS_SHEETS:
        data = files[f"{sm.PHYSICS_ID}/answer-sheets/{sheet['stem']}.pdf"]
        sheet_hashes[sheet["stem"]] = blobs.put(data)
        fake.pages[(sheet_hashes[sheet["stem"]], 1)] = v.sheet_transcript(sheet)
        sheets[sheet["stem"]] = data
    provider = ProbingOpenRouter(events=events, unconfirmed=unconfirmed,
                                 api_key="sk-or-test", base_url="https://openrouter.test/api/v1",
                                 transport=fake)
    monkeypatch.setattr(background, "_provider_for", lambda run_config: provider)

    from aeh.console import serve_console

    config = effective_config(cli._load_config_file(str(DEV_CI_CONFIG)))
    server = serve_console(store, cfg=config, config_path=str(DEV_CI_CONFIG))
    census = loopback_census(network_guard)
    census.__enter__()
    try:
        yield {"port": server.port, "version": version, "paper": paper,
               "paper_hash": paper_hash, "sheets": sheets, "sheet_hashes": sheet_hashes,
               "fake": fake, "provider": provider, "events": events,
               "transcriber": TRANSCRIBER, "store": store,
               "transcriber_build": configured_builds(DEV_CI_CONFIG)[0],
               "roster": "full_name,student_ref\n" + "\n".join(
                   f"{s['name']},{s['student']}" for s in sm.PHYSICS_SHEETS)}
    finally:
        fake.release()
        census.__exit__(None, None, None)
        server.terminate()
        try:
            store.close()
        except sqlite3.ProgrammingError:
            pass
        for name in ("build_sample_materials", "verify_sample_materials"):
            sys.modules.pop(name, None)
