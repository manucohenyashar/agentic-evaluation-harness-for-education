"""`TC-CONSOLE-72` (issue #771, CT-CONSOLE-34, RS-10) — documents never leak: a
sentinel-carrying upload is traceable to exactly the places a document may live.

| Leg | Expected |
|---|---|
| the console's own intake (the `draft package from documents` action, over HTTP, a text PDF whose text carries the sentinel) | the action stages the document itself — the sentinel's bytes land at their content address under `blobs/`, put there by the console, not by the test; the job then runs on the recorded transport's refusal and writes the placeholder draft |
| the draft artifacts the intake's job wrote | they exist (the fallback wrote the draft and its report) and carry **no** document text — stricter than the oracle's allowance |
| the preview upload (over HTTP) | the read parses the same sentinel PDF and answers with the sentinel in the parsed blocks — the teacher's own content, echoed to the teacher who uploaded it; it writes nothing |
| the recorded draft job, end to end | the pipeline runs over its corpus documents and finishes clean |
| the scan | the sentinel appears **nowhere else**: not in any store file's bytes (every `*.sqlite` scanned), not in any captured log line at any level, not in any request URL |

**Disclosed divergence, behaviour unchanged — flagged for follow-up in the PR:** the
sentinel cannot ride the *corpus* draft leg — the recorded provider replays prompts keyed
to the corpus documents, so a sentinel-modified corpus would miss its recording and prove
nothing. The sentinel therefore travels the channels a document genuinely enters by — the
draft action's staging intake and the preview upload — and its own draft job then runs on
the recorded transport's refusal of its unknown prompts: the workflow's fallback writes
the draft with placeholders and **no model output**, which is the shipped
failure-tolerance behaviour, not the behaviour under test. Those artifacts are then
asserted under the *stricter* shipped property: they quote no document text at all, so
the sentinel's only resting place is its staged blob.

**Isolation: rung 3 (E1)** — real store, real console over real HTTP, the recorded
provider for the draft leg (see the support module's reconcile for the recorded chain).
"""

from __future__ import annotations

import base64
import json
import logging

import pytest

import aeh.agg  # noqa: F401 — the full migration chain before the first store open (CLAUDE.md)
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
from aeh.grade.pdf import text_pdf_bytes
from tests.support.console_redesign_world import (
    _action,
    _request,
    run_draft_job,
    served_authoring,
    wait_for_job,
)
from tests.support.spa import store_digest

pytestmark = pytest.mark.integration

SENTINEL = "SENTINEL-9f3a1c-do-not-leak"


def _sentinel_pdf() -> bytes:
    """One text PDF whose visible text carries the sentinel — the document a teacher
    uploads, saved straight from a document so its text layer reads."""
    return text_pdf_bytes([
        "Assessment: Leakage Probe",
        "",
        f"This page carries the marker {SENTINEL} in its text.",
        "",
        "<!-- region: kind=transcribed_text question_id=Q1 -->",
        "Explain what the marker above marks.",
        "<!-- /region -->",
    ])


def test_tc_console_72_the_upload_travels_only_by_the_channels_a_document_may_use(
        served_authoring, caplog):
    """The sentinel enters by the console's own document intake, is echoed by the
    preview, and is found in no store byte, no log line and no request URL anywhere
    else."""
    server, port, store, data_dir = served_authoring
    pdf = _sentinel_pdf()
    encoded = base64.b64encode(pdf).decode("ascii")
    requested: list[str] = []

    def track(port_: int, method: str, path: str, body=None):
        requested.append(path)
        return _request(port_, method, path, body)

    # Open the log capture to every level: the leak scan is only honest if a DEBUG-level
    # log line carrying document text would actually be captured.
    caplog.set_level(logging.DEBUG)

    before = store_digest(data_dir)

    # The console's own intake: the `draft package from documents` action stages the
    # document in the blob store *itself*, before the job's worker starts.
    started = _action(port, "draft package from documents", {
        "documents": [{"name": "leak-probe.pdf", "content_base64": encoded}],
    })
    assert started["dispatched"] is True, started["detail"]
    staged_job = started["job_id"]
    staged = [path for path in data_dir.glob("blobs/**/*") if path.is_file()]
    assert staged, "the console's document intake staged nothing"
    assert any(SENTINEL.encode("utf-8") in path.read_bytes() for path in staged), (
        "the console's own staging write does not carry the uploaded document's "
        "bytes; the intake lost the content it was given")

    # The staged job then runs on the recorded transport's refusal of its unknown
    # prompts: the workflow's fallback writes the draft with placeholders and no model
    # output ("Models used: none"). That is the shipped failure-tolerance behaviour —
    # what matters is the intake above, and where the sentinel's text is allowed to sit.
    record = wait_for_job(port, staged_job)
    assert record["state"] == "succeeded", (
        f"the sentinel draft job ended {record['state']}")
    draft_files = [path for path in (data_dir / "authoring").rglob("*")
                   if path.is_file()]
    assert draft_files, "the fallback wrote no draft artifacts"
    # The shipped writer never quotes a document's text in the draft or its report —
    # stricter than the oracle's allowance ("blob staging and the draft artefacts"):
    # the sentinel sits ONLY at its staged blob. If a change starts embedding document
    # text in the artifacts, this fails and the leak surface grew.
    assert all(SENTINEL not in path.read_text(errors="ignore")
               for path in draft_files), (
        "a draft artifact quotes the uploaded document's text; the leak surface grew "
        "beyond the blob staging area")

    # The preview upload: the same sentinel PDF, parsed and echoed back, writing nothing.
    status, _headers, raw = track(port, "POST", "/api/v1/authoring/preview", {
        "documents": [{"name": "leak-probe.pdf", "content_base64": encoded}],
    })
    assert status == 200, raw[:200]
    preview = json.loads(raw)
    document = preview["documents"][0]
    assert document["accepted"] is True, document
    assert any(SENTINEL in block["text"] for block in document["blocks"]), (
        "the preview's parsed blocks do not carry the uploaded text; the teacher "
        "cannot check what the console read")

    # The recorded draft leg: the pipeline runs end to end over its corpus documents.
    _answer, draft_record = run_draft_job(port, "AF-02")
    assert draft_record["state"] == "succeeded", (
        f"the draft job ended {draft_record['state']}")

    # The scan: every file the store holds that is neither the blob staging area nor
    # the draft artifacts, byte-for-byte.
    allowed = (data_dir / "blobs", data_dir / "authoring")
    leaks: list[str] = []
    for path in data_dir.rglob("*"):
        if not path.is_file() or any(
                path.is_relative_to(tree) for tree in allowed):
            continue
        try:
            blob = path.read_bytes()
        except OSError:
            continue
        if SENTINEL.encode("utf-8") in blob:
            leaks.append(str(path.relative_to(data_dir)))
    assert leaks == [], (
        f"the sentinel leaked into {leaks}; a document's text lives only in the "
        "blob staging area and the draft artifacts (CT-CONSOLE-34)")

    assert SENTINEL not in caplog.text, (
        "the console's log lines carry the uploaded document's text")
    assert all(SENTINEL not in path for path in requested), (
        "a request URL carries the uploaded document's text")
    server.terminate()
