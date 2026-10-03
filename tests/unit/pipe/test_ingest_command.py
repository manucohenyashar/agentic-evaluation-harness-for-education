"""Reading scanned papers with `aeh ingest` (TC-PIPE-30..31, live-test blocker B4).

Before this, nothing shipped read a scan into a checked paper. These cases drive the real command
over the sample physics test: the package from its spec, a class from `aeh cohort create`, and
the pages sent through the real `OpenRouterProvider` and its wire format to a fake OpenRouter that
answers each page with the sample script's transcript for it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from aeh.pipeline import cli
from aeh.prov import HttpResponse, OpenRouterProvider
from aeh.prov.live import IMAGE_FIELD, _fields_from_wire
from aeh.store import open_store

REPO = Path(__file__).resolve().parents[3]
SAMPLE_SPEC = REPO / "docs" / "live-tests" / "config" / "ps9-forces-01.package.toml"
DEV_CI_CONFIG = REPO / "docs" / "live-tests" / "config" / "live-test.dev-ci.toml"
SAMPLES = REPO / "docs" / "live-tests" / "sample-materials"


class _FakeOpenRouter:
    """Answers each page-reading request with the transcript staged for that scan and page."""

    def __init__(self) -> None:
        self.pages: dict[tuple[str, int], str] = {}
        self.requests: list = []
        self.interrupt_at: int | None = None  # raise KeyboardInterrupt on this request number
        self.status = 200

    def send(self, request):  # noqa: ANN001
        self.requests.append(request)
        if self.interrupt_at is not None and len(self.requests) == self.interrupt_at:
            raise KeyboardInterrupt
        if self.status != 200:
            return HttpResponse(self.status, {}, b'{"error": {"message": "User not found."}}')
        body = json.loads(request.body)
        fields = dict((name, value) for name, value in _fields_from_wire(body))
        if fields.get("instruction", "").startswith("Decide whether"):
            text = "uncertain"  # the right-test check's optional second opinion
        else:
            text = self.pages[(fields["source_blob_hash"], int(fields["page_no"]))]
        return HttpResponse(200, {}, json.dumps({
            "model": "qwen/qwen3-vl-8b-instruct",
            "choices": [{"finish_reason": "stop", "message": {"content": text}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.00001},
        }).encode("utf-8"))


@pytest.fixture
def physics(tmp_data_dir, tmp_path, monkeypatch, capsys):
    """The sample physics test set up as an operator would: package built, class created, the
    test paper and answer sheets written to disk, and a fake OpenRouter staged with every page."""
    pytest.importorskip("pypdfium2")
    monkeypatch.syspath_prepend(str(SAMPLES))
    import build_sample_materials as sm
    import verify_sample_materials as v

    for key in ("HARNESS_FIXTURE_DIR", "HARNESS_PROFILE"):
        monkeypatch.delenv(key, raising=False)
    files = sm.build_all()
    paper = tmp_path / "01-test-paper.pdf"
    paper.write_bytes(files[f"{sm.PHYSICS_ID}/01-test-paper.pdf"])
    sheets_dir = tmp_path / "answer-sheets"
    sheets_dir.mkdir()
    fake = _FakeOpenRouter()
    store = open_store(tmp_data_dir)
    try:
        blobs = store.blobs()
        fake.pages[(blobs.put(paper.read_bytes()), 1)] = v.assessment_transcript(sm.PHYSICS_ID)
        for sheet in sm.PHYSICS_SHEETS:
            data = files[f"{sm.PHYSICS_ID}/answer-sheets/{sheet['stem']}.pdf"]
            (sheets_dir / f"{sheet['stem']}.pdf").write_bytes(data)
            fake.pages[(blobs.put(data), 1)] = v.sheet_transcript(sheet)
    finally:
        store.close()
    roster = tmp_path / "roster.txt"
    roster.write_text("\n".join(s["student"] or "S9-006" for s in sm.PHYSICS_SHEETS),
                      encoding="utf-8")
    assert cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                     "--spec", str(SAMPLE_SPEC)]) == 0
    built = json.loads(capsys.readouterr().out)
    provider = OpenRouterProvider.enforcing_zero_retention(
        api_key="sk-or-test", base_url="https://openrouter.test/api/v1", transport=fake)
    monkeypatch.setattr(cli, "_provider_for", lambda run_config: provider)
    yield {"version": built["package_version"], "paper": paper, "sheets": sheets_dir,
           "roster": roster, "fake": fake, "expected": dict(v.EXPECTED_STATUS)}
    for name in ("build_sample_materials", "verify_sample_materials"):
        sys.modules.pop(name, None)


def _ingest(data_dir, physics, capsys, cohort="class-ps9", with_paper=True):
    """Run `aeh ingest`; returns (exit code, the JSON it printed or None, its stderr)."""
    capsys.readouterr()
    args = ["ingest", "--data-dir", str(data_dir), "--cohort", cohort,
            "--package-version", physics["version"], "--config", str(DEV_CI_CONFIG)]
    if with_paper:
        args += ["--assessment", str(physics["paper"])]
    code = cli.main([*args, str(physics["sheets"])])
    out, err = capsys.readouterr()
    return code, (json.loads(out) if out.strip() else None), err


# --- TC-PIPE-30 -------------------------------------------------------------------------------


def test_tc_pipe_30_aeh_ingest_reads_every_sheet_through_the_real_checks(tmp_data_dir, physics,
                                                                         capsys):
    assert cli.main(["cohort", "create", "--data-dir", str(tmp_data_dir), "--cohort", "class-ps9",
                     "--consent", "synthetic", "--roster", str(physics["roster"])]) == 0
    code, result, _err = _ingest(tmp_data_dir, physics, capsys)
    assert code == 0
    statuses = {Path(s["file"]).stem: s["status"] for s in result["sheets"]}
    assert statuses == {stem: physics["expected"][stem] for stem in statuses}, statuses
    assert (result["read"], result["quarantined"], result["skipped"]) == (6, 3, 0)
    assert result["assessment"] == "read from 01-test-paper.pdf"
    # Every page went over the real wire format: an image part, zero-retention routing.
    pages = [json.loads(r.body) for r in physics["fake"].requests
             if any(m.get("name") == IMAGE_FIELD for m in json.loads(r.body)["messages"])]
    assert len(pages) == 7  # the test paper and six answer sheets, one page each
    for body in pages:
        image = next(m for m in body["messages"] if m["name"] == IMAGE_FIELD)
        assert image["content"][0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert body["provider"] == {"zdr": True, "data_collection": "deny"}
        assert body["model"] == "qwen/qwen3-vl-8b-instruct"


def test_tc_pipe_30_a_rerun_reads_nothing_twice(tmp_data_dir, physics, capsys):
    assert cli.main(["cohort", "create", "--data-dir", str(tmp_data_dir), "--cohort", "class-ps9",
                     "--consent", "synthetic", "--roster", str(physics["roster"])]) == 0
    assert _ingest(tmp_data_dir, physics, capsys)[0] == 0
    sent = len(physics["fake"].requests)
    code, again, _err = _ingest(tmp_data_dir, physics, capsys, with_paper=False)
    assert code == 0
    assert again["assessment"] == "already read"
    read_before = {s["file"] for s in again["sheets"] if s["status"] == "skipped"}
    # Every sheet that became a document is skipped; only the unreadable-at-V0 kind could be
    # read again, and the sample has none.
    assert read_before == {p.name for p in physics["sheets"].iterdir()}, again
    assert len(physics["fake"].requests) == sent, "a re-run sent pages again"
    store = open_store(tmp_data_dir)
    try:
        count = store.cohort("class-ps9").query("SELECT COUNT(*) AS n FROM submission")[0]["n"]
    finally:
        store.close()
    assert count == 6


# --- TC-PIPE-31 -------------------------------------------------------------------------------


def test_tc_pipe_31_a_real_class_is_refused_before_any_page_is_sent(tmp_data_dir, physics, capsys):
    assert cli.main(["cohort", "create", "--data-dir", str(tmp_data_dir), "--cohort", "class-real",
                     "--consent", "real", "--roster", str(physics["roster"])]) == 0
    code, _out, err = _ingest(tmp_data_dir, physics, capsys, cohort="class-real")
    assert code == 1 and "ConsentGateError" in err
    assert physics["fake"].requests == []


def test_tc_pipe_31_without_a_test_paper_the_command_says_so(tmp_data_dir, physics, capsys):
    assert cli.main(["cohort", "create", "--data-dir", str(tmp_data_dir), "--cohort", "class-ps9",
                     "--consent", "synthetic", "--roster", str(physics["roster"])]) == 0
    code, _out, err = _ingest(tmp_data_dir, physics, capsys, with_paper=False)
    assert code == 1 and "pass --assessment" in err
    assert physics["fake"].requests == []


# --- TC-PIPE-32: a cut-off read and a reader that cannot read (review findings) ----------------


def _submissions(data_dir):
    store = open_store(data_dir)
    try:
        return [dict(r) for r in store.cohort("class-ps9").query(
            "SELECT submission_id, ingest_status, quarantined FROM submission")]
    finally:
        store.close()


def test_tc_pipe_32_a_read_cut_off_by_ctrl_c_is_parked_and_never_graded(tmp_data_dir, physics,
                                                                       capsys):
    assert cli.main(["cohort", "create", "--data-dir", str(tmp_data_dir), "--cohort", "class-ps9",
                     "--consent", "synthetic", "--roster", str(physics["roster"])]) == 0
    physics["fake"].interrupt_at = 3  # the test paper, the first sheet, then Ctrl-C
    with pytest.raises(KeyboardInterrupt):
        _ingest(tmp_data_dir, physics, capsys)
    left = [r for r in _submissions(tmp_data_dir) if r["ingest_status"] is None]
    assert len(left) == 1, "the cut-off read left no half-made submission to test against"
    physics["fake"].interrupt_at = None
    code, result, err = _ingest(tmp_data_dir, physics, capsys, with_paper=False)
    assert code == 0, err
    assert result["interrupted"] == [left[0]["submission_id"]]
    assert "cut-off read" in err
    rows = {r["submission_id"]: r for r in _submissions(tmp_data_dir)}
    assert (rows[left[0]["submission_id"]]["ingest_status"],
            rows[left[0]["submission_id"]]["quarantined"]) == ("incomplete", 1)
    # Nothing a run would admit is left without a status, and each student's paper counts once.
    assert all(r["ingest_status"] is not None for r in rows.values())
    graded = [r for r in rows.values() if not r["quarantined"]]
    stems = {p.stem for p in physics["sheets"].iterdir()}
    assert len(graded) == sum(1 for stem in stems if physics["expected"][stem] == "ok")


def test_tc_pipe_32_a_reader_that_reads_nothing_exits_1_and_says_why(tmp_data_dir, physics, capsys):
    assert cli.main(["cohort", "create", "--data-dir", str(tmp_data_dir), "--cohort", "class-ps9",
                     "--consent", "synthetic", "--roster", str(physics["roster"])]) == 0
    assert _ingest(tmp_data_dir, physics, capsys)[0] == 0
    # The key is revoked; new sheets arrive in the same folder.
    physics["fake"].status = 401
    extra = physics["sheets"] / "late.pdf"
    extra.write_bytes(next(physics["sheets"].glob("S9-001*.pdf")).read_bytes() + b"\n%late")
    code, result, err = _ingest(tmp_data_dir, physics, capsys, with_paper=False)
    assert code == 1
    assert "no answer sheet could be read" in err and "API key" in err
    late = next(s for s in result["sheets"] if s["file"] == "late.pdf")
    assert late["status"] == "unreadable" and late["detail"], late
    assert "late.pdf: unreadable" in err
