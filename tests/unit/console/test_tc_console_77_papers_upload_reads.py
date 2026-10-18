"""`TC-CONSOLE-77` — the papers upload reads the papers (live-test blocker B4).

*Inline regression.* The console's papers upload (design delta §3.2.3: "the existing PDF scan
staging path, multi-file, with the paper check naming rejections in plain language and parking
what fails") staged a scan's chunks and recorded its name, and nothing ever read it: the SPA's
file inputs were inert and reading the papers took `aeh ingest` in a terminal. An upload that
asks to be read (`read=1`) must now reach the same intake door `aeh ingest` opens — the same
page reader, the same five checks, the same parking — on a worker the console owns, with its
progress on the jobs read.

The world is `TC-PIPE-30`'s: the sample physics package built from its spec, a class made through
the console's own `import roster file` control, and the pages sent through the real
`OpenRouterProvider.enforcing_zero_retention()` to a stand-in OpenRouter that answers each page
with the sample script's transcript. Only the transport is a stand-in; the console, its HTTP
routes, the upload, the jobs registry and the intake are the shipped ones.

Arms: (a) the test paper and the six sheets uploaded over `POST /api/v1/uploads?read=1`, one
file per request, each answered at once with a job id — one `paper_intake` job reads them all,
and each sheet's status equals `EXPECTED_STATUS` (three read, three parked); the papers read
then reports the test paper in and every sheet with its parked flag; uploading the same sheet
again is skipped, not read twice. (b) an upload that names an unknown class, no test version,
or a `real` class under the remote profile is refused before a byte is staged, and nothing is
read; a sheet uploaded before any test paper fails its file with the teacher's next step.
"""

from __future__ import annotations

import http.client
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from aeh.conf import effective_config
from aeh.pipeline import background, cli
from aeh.pipeline.runtime import _open_store
from aeh.prov import OpenRouterProvider
from tests.support.guards import loopback_census
from tests.unit.pipe.test_ingest_command import (
    DEV_CI_CONFIG,
    SAMPLE_SPEC,
    SAMPLES,
    _FakeOpenRouter,
)


def _request(port: int, method: str, path: str, body: bytes = b"",
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


def _upload(port: int, data: bytes, **query: str) -> tuple[int, Any]:
    from urllib.parse import urlencode

    return _request(port, "POST", f"/api/v1/uploads?{urlencode({'read': '1', **query})}",
                    data, "application/pdf")


def _wait(port: int, job_id: str, timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        status, record = _request(port, "GET", f"/api/v1/jobs/{job_id}")
        assert status == 200, record
        if record["state"] not in ("queued", "running"):
            return record
        assert time.monotonic() < deadline, f"job {job_id} never settled: {record!r}"
        time.sleep(0.1)


@pytest.fixture
def console(tmp_data_dir, monkeypatch, capsys, network_guard):
    """A console served over the sample physics world, with the stand-in OpenRouter behind
    the intake's provider seam (`aeh.pipeline.background._provider_for`)."""
    pytest.importorskip("pypdfium2")
    monkeypatch.syspath_prepend(str(SAMPLES))
    import build_sample_materials as sm
    import verify_sample_materials as v

    for key in ("HARNESS_FIXTURE_DIR", "HARNESS_PROFILE"):
        monkeypatch.delenv(key, raising=False)
    files = sm.build_all()
    fake = _FakeOpenRouter()
    assert cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                     "--spec", str(SAMPLE_SPEC)]) == 0
    version = json.loads(capsys.readouterr().out)["package_version"]
    store = _open_store(str(tmp_data_dir))
    blobs = store.blobs()
    paper = files[f"{sm.PHYSICS_ID}/01-test-paper.pdf"]
    fake.pages[(blobs.put(paper), 1)] = v.assessment_transcript(sm.PHYSICS_ID)
    sheets = {}
    for sheet in sm.PHYSICS_SHEETS:
        data = files[f"{sm.PHYSICS_ID}/answer-sheets/{sheet['stem']}.pdf"]
        fake.pages[(blobs.put(data), 1)] = v.sheet_transcript(sheet)
        sheets[sheet["stem"]] = data
    provider = OpenRouterProvider.enforcing_zero_retention(
        api_key="sk-or-test", base_url="https://openrouter.test/api/v1", transport=fake)
    monkeypatch.setattr(background, "_provider_for", lambda run_config: provider)

    from aeh.console import serve_console

    config = effective_config(cli._load_config_file(str(DEV_CI_CONFIG)))
    server = serve_console(store, cfg=config, config_path=str(DEV_CI_CONFIG))
    # The console is a real loopback server; every other host stays blocked, and the census
    # proves the page reader's traffic never left the process (the stand-in is in-process).
    census = loopback_census(network_guard)
    attempts = census.__enter__()
    try:
        yield {"port": server.port, "version": version, "paper": paper, "sheets": sheets,
               "fake": fake, "expected": dict(v.EXPECTED_STATUS),
               "roster": "\n".join(s["student"] or "S9-006" for s in sm.PHYSICS_SHEETS)}
    finally:
        census.__exit__(None, None, None)
        server.terminate()
        # The class's tier was first opened on a console request thread (the import roster
        # file control), so its own connection belongs to that thread: close tolerating it,
        # the console journeys' shape (`console_journeys._close`).
        try:
            store.close()
        except sqlite3.ProgrammingError:
            pass
        for name in ("build_sample_materials", "verify_sample_materials"):
            sys.modules.pop(name, None)
    assert not fake.request_problems, sorted(set(fake.request_problems))
    assert all(a.address[0] in ("127.0.0.1", "::1", "localhost") for a in attempts), attempts


def _make_class(port: int, roster: str, class_id: str = "ps9-class",
                consent: str = "synthetic") -> None:
    status, answer = _request(port, "POST", "/api/v1/actions/import-roster-file", json.dumps({
        "class_id": class_id, "consent_class": consent, "content": roster,
        "name": "roster.txt"}).encode("utf-8"))
    assert status == 200 and answer["dispatched"] is True, answer


def test_tc_console_77_a_uploaded_papers_are_read_through_the_intake(console) -> None:
    port, version = console["port"], console["version"]
    _make_class(port, console["roster"])

    status, answer = _upload(port, console["paper"], cohort_id="ps9-class",
                             package_version=version, kind="assessment",
                             filename="01-test-paper.pdf")
    assert status == 200 and answer["dispatched"] is True, answer
    jobs = {answer["job_id"]}
    for stem, data in console["sheets"].items():
        status, answer = _upload(port, data, cohort_id="ps9-class", package_version=version,
                                 kind="sheet", filename=f"{stem}.pdf")
        assert status == 200 and answer["dispatched"] is True, answer
        jobs.add(answer["job_id"])
    for job_id in sorted(jobs):
        record = _wait(port, job_id)
        assert record["kind"] == "paper_intake"
        assert record["state"] == "succeeded", record

    status, papers = _request(port, "GET", "/api/v1/papers?cohort_id=ps9-class")
    assert status == 200, papers
    assert papers["test_paper_read"] is True
    sheets = papers["sheets"]
    assert len(sheets) == len(console["sheets"]), sheets
    want_parked = sorted(s for s, st in console["expected"].items()
                         if s.startswith("S9") and st != "ok")
    assert sum(1 for s in sheets if s["parked"]) == len(want_parked), sheets
    statuses = sorted(s["status"] for s in sheets)
    assert statuses == sorted(st for s, st in console["expected"].items() if s.startswith("S9"))
    read_refs = {s["student_ref"] for s in papers["students"] if s["submission_id"]}
    assert read_refs, papers

    # The same sheet again is skipped by the intake, never read into a second submission.
    requests_before = len(console["fake"].requests)
    stem, data = next(iter(console["sheets"].items()))
    status, answer = _upload(port, data, cohort_id="ps9-class", package_version=version,
                             kind="sheet", filename=f"{stem}.pdf")
    assert status == 200, answer
    again = _wait(port, answer["job_id"])
    assert again["state"] == "succeeded", again
    assert "1 already read" in str(again["progress"]["current"]), again
    assert len(console["fake"].requests) == requests_before
    status, papers = _request(port, "GET", "/api/v1/papers?cohort_id=ps9-class")
    assert len(papers["sheets"]) == len(console["sheets"])


def test_tc_console_77_b_refusals_stage_nothing_and_read_nothing(console) -> None:
    port, version = console["port"], console["version"]
    _make_class(port, console["roster"])
    _make_class(port, console["roster"], class_id="real-class", consent="real")
    paper = console["paper"]

    refusals = [
        ({"cohort_id": "no-such-class", "package_version": version, "kind": "assessment",
          "filename": "p.pdf"}, "no class"),
        ({"cohort_id": "ps9-class", "package_version": "", "kind": "assessment",
          "filename": "p.pdf"}, "published test"),
        ({"cohort_id": "ps9-class", "package_version": version, "kind": "other",
          "filename": "p.pdf"}, "test paper or an answer sheet"),
        ({"cohort_id": "real-class", "package_version": version, "kind": "assessment",
          "filename": "p.pdf"}, "cannot be read under this console's settings"),
    ]
    for query, words in refusals:
        status, answer = _upload(port, paper, **query)
        assert status == 400, (query, answer)
        assert answer["dispatched"] is False and words in answer["detail"], (query, answer)
    # A scan-sized refused upload still gets its reason: the body is drained, not cut off
    # (a reset connection would leave the teacher with no refusal to read).
    big = paper + b"\0" * (8 * 1024 * 1024)
    status, answer = _upload(port, big, cohort_id="no-such-class", package_version=version,
                             kind="sheet", filename="big.pdf")
    assert status == 400 and "no class" in answer["detail"], answer

    status, jobs = _request(port, "GET", "/api/v1/jobs")
    assert not [j for j in jobs["jobs"] if j["kind"] == "paper_intake"], jobs
    assert console["fake"].requests == []
    # Nothing was recorded as uploaded for the classes the refusals named.
    for class_id in ("ps9-class", "real-class"):
        status, papers = _request(port, "GET", f"/api/v1/papers?cohort_id={class_id}")
        assert status == 200 and papers["parts"] == [], papers

    # A sheet before any test paper: the file fails with the next step, nothing is sent.
    stem, data = next(iter(console["sheets"].items()))
    status, answer = _upload(port, data, cohort_id="ps9-class", package_version=version,
                             kind="sheet", filename=f"{stem}.pdf")
    assert status == 200, answer
    record = _wait(port, answer["job_id"])
    assert record["state"] == "failed", record
    assert "upload the test paper first" in str(record["error"]["detail"]), record
    assert console["fake"].requests == []
