"""`TC-CONSOLE-67` (issue #771, FR-CONSOLE-59, CT-CONSOLE-31) — the readable package
export: the questions and the grading guide as a teacher's PDF.

| Arm | Expected |
|---|---|
| (a) the same package version exported twice | byte-identical bytes — the PDF is a pure function of the package's rows — and the read writes nothing durable (`CT-CONSOLE-30`) |
| (b) the extracted text | the questions in teacher form (the prompts, the answers to choose from), the band descriptors, and the grade policy's plain-language sentence |
| (c) the extracted text, scanned | no TOML syntax anywhere — no `[table]` header, no `key = value` assignment line, no placeholder sentinel (`CT-CONSOLE-31`) |

The package version comes from the recorded authoring journey (`AF-02` drafted, its
`approved_by` answered, approved and published through the console's own actions), so the
exported document is the one a teacher would actually fetch.

**Isolation: rung 3 (E1)** — real store, real console over real HTTP, the recorded
provider (see the support module's reconcile for the recorded chain).
"""

from __future__ import annotations

import re
import tomllib

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
from aeh.pkg import PackageCatalog
from tests.support.console_redesign_world import (
    _action,
    _get_json,
    _request,
    draft_path_in,
    draft_read,
    run_draft_job,
    served_authoring,
)
from tests.support.spa import store_digest

pytestmark = pytest.mark.integration

READABLE_PATH = "/api/v1/packages/readable"
APPROVER_ANSWER = "Prof. Dana Whitfield"


def _approved_version(served_authoring):
    """The recorded AF-02 journey through the console: draft it, answer its approver
    placeholder, approve it. `(port, store, data_dir, package_id, version_id)`."""
    _server, port, store, data_dir = served_authoring
    _answer, record = run_draft_job(port, "AF-02")
    assert record["state"] == "succeeded", f"the draft job ended {record['state']}"
    document = draft_read(port)["draft"]
    package_id = document["package_id"]
    answer = _action(port, "answer authoring review", {
        "package_id": package_id, "item_id": "approved_by", "value": APPROVER_ANSWER,
    })
    assert answer["refused"] is False, answer["detail"]
    approval = _action(port, "approve draft package", {"package_id": package_id})
    assert approval["refused"] is False, approval["detail"]
    # The approve outcome names the version in teacher words (FR-CONSOLE-73, #808); the
    # version id is read from the package page's context row instead.
    context = _get_json(port, "/api/v1/context")
    version = next(row["published_version_id"] for row in context["packages"]
                   if row["package_id"] == package_id)
    return port, store, data_dir, package_id, version


def _extract(port: int, version: str) -> str:
    """The readable export's text, extracted with pypdf from the served PDF."""
    _status, _headers, body = _request(
        port, "GET", f"{READABLE_PATH}?package_version={version}&format=pdf")
    from pypdf import PdfReader
    import io
    return "\n".join(page.extract_text() or ""
                     for page in PdfReader(io.BytesIO(body)).pages)


def test_tc_console_67a_the_same_version_exports_byte_identical_and_writes_nothing(
        served_authoring):
    """Two exports of one version: the same bytes, and the store digest unmoved — the
    export reads the package, it never writes one."""
    port, store, data_dir, _package_id, version = _approved_version(served_authoring)
    before = store_digest(data_dir)

    first_status, first_headers, first = _request(
        port, "GET", f"{READABLE_PATH}?package_version={version}&format=pdf")
    second_status, _headers, second = _request(
        port, "GET", f"{READABLE_PATH}?package_version={version}&format=pdf")

    assert first_status == 200 and second_status == 200
    assert first_headers.get("Content-Type") == "application/pdf"
    assert first == second, (
        "the two exports differ; the PDF must be a pure function of the package's "
        "rows — no timestamp, no store path")
    assert store_digest(data_dir) == before, (
        "the readable export wrote to the store; a fetched read changes no stored "
        "byte (CT-CONSOLE-30)")


def test_tc_console_67b_the_extracted_text_carries_the_questions_and_the_grading_guide(
        served_authoring):
    """The extracted text names every question's prompt, the bands and their
    descriptors, and the grade policy's plain-language sentence — teacher form."""
    port, store, data_dir, _package_id, version = _approved_version(served_authoring)
    draft_spec = tomllib.loads(
        draft_path_in(data_dir, "geo8-climate-01").read_text(encoding="utf-8"))
    prompts = [str(question["text"]) for question in draft_spec["question"]]
    descriptors = [str(band["descriptor"])
                   for criterion in draft_spec["criterion"]
                   for band in criterion["bands"]]
    assert prompts and descriptors, "the draft fixture lost its content"
    plain_language = PackageCatalog(
        store.package("geo8-climate-01"), package_id="geo8-climate-01",
    ).grade_policy(version).plain_language

    text = _extract(port, version)

    for prompt in prompts:
        assert prompt in text, (
            f"the extracted text does not carry the question's prompt {prompt!r}")
    for descriptor in descriptors:
        assert descriptor in text, (
            f"the extracted text does not carry the band descriptor {descriptor!r}")
    plain_sentences = [line.strip() for line in plain_language.splitlines() if line.strip()]
    assert plain_sentences, "the grade policy carries no plain-language sentence"
    for sentence in plain_sentences:
        assert sentence in text, (
            f"the extracted text does not carry the grade policy's sentence "
            f"{sentence!r}")
    assert "The questions" in text and "What each question is marked on" in text, (
        "the document's teacher headings are missing from the extraction")


def test_tc_console_67c_the_extracted_text_carries_no_configuration_syntax(
        served_authoring):
    """No TOML in the teacher's document: no table header, no key assignment, no
    placeholder sentinel — the extraction oracle reads prose (CT-CONSOLE-31)."""
    port, _store, _data_dir, _package_id, version = _approved_version(served_authoring)
    text = _extract(port, version)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    assert lines, "the export extracted no text at all"
    headers = [line for line in lines if re.match(r"\A\[\[?", line)]
    assert headers == [], (
        f"the document renders TOML table header(s) {headers[:3]}; a teacher's "
        "document carries prose, not configuration (CT-CONSOLE-31)")
    assignments = [line for line in lines if re.match(r"\A[A-Za-z_][\w ]*=", line)]
    assert assignments == [], (
        f"the document renders key-assignment line(s) {assignments[:3]}; no "
        "configuration syntax is emitted anywhere (CT-CONSOLE-31)")
    assert "<<" not in text, (
        "the document carries a placeholder sentinel; a published package's export "
        "has none left to show")
