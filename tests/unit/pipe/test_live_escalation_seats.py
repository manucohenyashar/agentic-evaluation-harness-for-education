"""A live run never sends a judge seat's name as a model (TC-PIPE-33, live-test finding).

Past the panel, an escalation adds judges on derived names, `escalation-arm-<k>`, and the executor
made each one the first judge with that name as its model: on OpenRouter the first disagreement
sent `model: "escalation-arm-2"`, which OpenRouter does not serve. These cases drive the whole
operator path (`aeh package build`, `aeh cohort create`, `aeh ingest`, `aeh run`) over the sample
physics test, with the real `_provider_for` and `OpenRouterProvider`; only the transport is a
stand-in, and it answers 400 to any model it was not told about, as OpenRouter does.
"""

from __future__ import annotations

import io
import json
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from aeh.pipeline import cli
from aeh.prov import HttpResponse, OpenRouterProvider
from aeh.prov.live import _fields_from_wire
from aeh.store import open_store

REPO = Path(__file__).resolve().parents[3]
SAMPLE_SPEC = REPO / "docs" / "live-tests" / "config" / "ps9-forces-01.package.toml"
DEV_CI_CONFIG = REPO / "docs" / "live-tests" / "config" / "live-test.dev-ci.toml"
SAMPLES = REPO / "docs" / "live-tests" / "sample-materials"

TRANSCRIBER = "qwen/qwen3-vl-8b-instruct"
PANEL_JUDGE = "qwen/qwen3-30b-a3b"
EXTRA_JUDGES = ("vendor-a/judge-one", "vendor-b/judge-two", "vendor-c/judge-three")


class _FakeOpenRouter:
    """OpenRouter for the sample test: pages answered from the sample transcripts, judges that
    disagree (each model picks a different band, with low confidence, so cells escalate), and a
    400 for any model not in `models`."""

    def __init__(self, models) -> None:
        self.models = set(models)
        self.pages: dict[tuple[str, int], str] = {}
        self.sent: list[str] = []
        self.refused: list[str] = []

    def send(self, request):  # noqa: ANN001
        body = json.loads(request.body)
        model = body["model"]
        if model not in self.models:
            self.refused.append(model)
            return HttpResponse(400, {}, json.dumps(
                {"error": {"message": f"{model} is not a valid model ID"}}).encode("utf-8"))
        self.sent.append(model)
        fields = dict(_fields_from_wire(body))
        if "page_no" in fields:
            text = self.pages[(fields["source_blob_hash"], int(fields["page_no"]))]
        elif fields.get("instruction", "").startswith("Decide whether"):
            text = "uncertain"
        elif fields.get("level") in ("l1_question", "l2_test"):
            criteria = [c.strip() for c in fields.get("criteria", "").split(",") if c.strip()]
            text = json.dumps({
                "narrative": "The answer names some of what the question asks for.",
                "citations": criteria if fields["level"] == "l1_question" else []})
        elif "dependency_evidence" in fields:
            text = json.dumps({"spans": []})
        elif "evidence_rules" in fields:
            bands = re.findall(r"^- ([^:\n]+)", fields.get("bands", ""), re.M) or ["none"]
            pick = sorted(self.models).index(model) % len(bands)
            text = json.dumps({  # the pinned field order (FR-JUDGE-09)
                "cited_spans": [],
                "evidence_assessment": "No evidence span was extracted for this criterion.",
                "evidence_sufficient": False, "band": bands[pick], "self_confidence": 0.1})
        else:
            raise AssertionError(f"an unexpected request: {sorted(fields)}")
        return HttpResponse(200, {}, json.dumps({
            "model": model,
            "choices": [{"finish_reason": "stop", "message": {"content": text}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.00001},
        }).encode("utf-8"))


def _config(tmp_path, extra_judges=()):
    """The shipped dev-ci config, plus `escalation_judge` tables for `extra_judges`."""
    text = DEV_CI_CONFIG.read_text(encoding="utf-8")
    for slug in extra_judges:
        text += ("\n[[profiles.dev-ci.escalation_judge]]\nrole = \"judge\"\n"
                 "provider = \"openrouter\"\n"
                 f"build_id = \"openrouter/{slug}@2026-06-01\"\n")
    path = tmp_path / "live.toml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def physics(tmp_data_dir, tmp_path, monkeypatch):
    """The sample physics test read into a class with `aeh ingest`; returns a function that runs
    `aeh run` under a config and gives (exit code, the printed result or None, stderr)."""
    pytest.importorskip("pypdfium2")
    monkeypatch.syspath_prepend(str(SAMPLES))
    import build_sample_materials as sm
    import verify_sample_materials as v

    for key in ("HARNESS_FIXTURE_DIR", "HARNESS_PROFILE", "HARNESS_ORCH_RANDOM_ARM_RATE"):
        monkeypatch.delenv(key, raising=False)
    # Every judge escalation may run: the default budget is a rate, and six papers are few.
    monkeypatch.setenv("HARNESS_ORCH_ESCALATION_BUDGET", "1.0")
    fake = _FakeOpenRouter({TRANSCRIBER, PANEL_JUDGE})
    real = OpenRouterProvider.enforcing_zero_retention.__func__
    monkeypatch.setattr(OpenRouterProvider, "enforcing_zero_retention", classmethod(
        lambda cls, **seams: real(cls, api_key="sk-or-test",
                                  base_url="https://openrouter.test/api/v1", transport=fake)))

    files = sm.build_all()
    paper = tmp_path / "01-test-paper.pdf"
    paper.write_bytes(files[f"{sm.PHYSICS_ID}/01-test-paper.pdf"])
    sheets = tmp_path / "answer-sheets"
    sheets.mkdir()
    store = open_store(tmp_data_dir)
    try:
        blobs = store.blobs()
        fake.pages[(blobs.put(paper.read_bytes()), 1)] = v.assessment_transcript(sm.PHYSICS_ID)
        for sheet in sm.PHYSICS_SHEETS:
            data = files[f"{sm.PHYSICS_ID}/answer-sheets/{sheet['stem']}.pdf"]
            (sheets / f"{sheet['stem']}.pdf").write_bytes(data)
            fake.pages[(blobs.put(data), 1)] = v.sheet_transcript(sheet)
    finally:
        store.close()
    roster = tmp_path / "roster.txt"
    roster.write_text("\n".join(s["student"] or "S9-006" for s in sm.PHYSICS_SHEETS),
                      encoding="utf-8")
    data = str(tmp_data_dir)
    with redirect_stdout(io.StringIO()) as out:
        assert cli.main(["package", "build", "--data-dir", data, "--spec", str(SAMPLE_SPEC)]) == 0
    version = json.loads(out.getvalue())["package_version"]
    with redirect_stdout(io.StringIO()):
        assert cli.main(["cohort", "create", "--data-dir", data, "--cohort", "class-ps9",
                         "--consent", "synthetic", "--roster", str(roster)]) == 0
        assert cli.main(["ingest", "--data-dir", data, "--cohort", "class-ps9",
                         "--package-version", version, "--config", str(DEV_CI_CONFIG),
                         "--assessment", str(paper), str(sheets)]) == 0

    def run(config, capsys):
        capsys.readouterr()
        code = cli.main(["run", "--data-dir", data, "--cohort", "class-ps9",
                         "--package-version", version, "--config", str(config)])
        printed, err = capsys.readouterr()
        start = printed.find("{\n")
        return code, (json.loads(printed[start:]) if start >= 0 else None), err

    yield fake, run
    for name in ("build_sample_materials", "verify_sample_materials"):
        sys.modules.pop(name, None)


def _states(data_dir):
    """Every judged criterion score's (judge_count, state, routing); multiple-choice scores
    have no judges."""
    store = open_store(data_dir)
    try:
        return [tuple(row) for row in store.cohort("class-ps9").query(
            "SELECT judge_count, state, routing FROM criterion_score WHERE judge_count > 0")]
    finally:
        store.close()


def _runs(data_dir):
    store = open_store(data_dir)
    try:
        from aeh.orch import Orchestrator

        return Orchestrator(store).runs()
    finally:
        store.close()


def test_tc_pipe_33_one_judge_and_no_extra_judges_completes_without_widening(
        tmp_data_dir, tmp_path, physics, capsys, monkeypatch):
    fake, run = physics
    monkeypatch.setenv("HARNESS_ORCH_RANDOM_ARM_RATE", "0")
    code, result, err = run(_config(tmp_path), capsys)
    assert fake.refused == [], f"a seat's name went out as a model: {fake.refused}"
    assert code == 0 and result["status"] == "complete", (result, err)
    lines = [line for stage in result["stages"] for line in stage["detail"]]
    assert any("no real judge for seats 2-3" in line for line in lines), lines
    assert set(fake.sent) == {TRANSCRIBER, PANEL_JUDGE}
    # Never settled, never reported as a breaker refusal: provisional, to the teacher.
    states = _states(tmp_data_dir)
    assert states and all(jc == 1 for jc, _state, _route in states), states
    assert {state for _jc, state, _route in states} == {"provisional_unreviewed"}, states


def test_tc_pipe_33_escalation_judges_take_the_seats_past_the_panel(
        tmp_data_dir, tmp_path, physics, capsys):
    fake, run = physics
    fake.models.update(EXTRA_JUDGES)
    code, result, err = run(_config(tmp_path, EXTRA_JUDGES), capsys)
    assert fake.refused == [], f"a seat's name went out as a model: {fake.refused}"
    assert code == 0 and result["status"] == "complete", (result, err)
    # The disagreeing panel escalated onto the configured judges, in order.
    assert {EXTRA_JUDGES[0], EXTRA_JUDGES[1]} <= set(fake.sent), set(fake.sent)
    # Review finding: a widened cell that still wants more judges is the no-op an already
    # escalated pair is, not a seat shortage, so it is not downgraded.
    states = _states(tmp_data_dir)
    assert any(jc == 3 for jc, _state, _route in states), states
    assert all(state != "ungradeable_by_panel" for _jc, state, _route in states), states
    lines = [line for stage in result["stages"] for line in stage["detail"]]
    # The first widening always has its seats; only a random-arm cell (three judges from the
    # start) can want seats 4-5, past the four this run has, and then it says so.
    short = [line for line in lines if "no real judge" in line]
    assert all("seats 4-5" in line for line in short), short


def test_tc_pipe_33_the_random_arm_without_its_seats_is_refused_before_the_run(
        tmp_data_dir, tmp_path, physics, capsys):
    fake, run = physics
    sent = len(fake.sent)
    code, _result, err = run(_config(tmp_path, EXTRA_JUDGES[:1]), capsys)
    assert code == 1
    assert "HARNESS_ORCH_RANDOM_ARM_RATE" in err and "Add 1" in err and "escalation_judge" in err
    assert not _runs(tmp_data_dir) and len(fake.sent) == sent


@pytest.mark.parametrize("extra, words", [
    ((PANEL_JUDGE,), "already has a seat"),
    ((EXTRA_JUDGES[0], EXTRA_JUDGES[0]), "already has a seat"),
])
def test_tc_pipe_33_a_model_holds_one_seat(tmp_data_dir, tmp_path, physics, capsys, extra, words):
    _fake, run = physics
    code, _result, err = run(_config(tmp_path, extra), capsys)
    assert code == 1 and words in err
    assert not _runs(tmp_data_dir)


def test_tc_pipe_33_a_floating_escalation_judge_is_refused(tmp_data_dir, tmp_path, physics, capsys):
    _fake, run = physics
    path = _config(tmp_path, ("vendor-a/judge-one",))
    path.write_text(path.read_text(encoding="utf-8").replace(
        "openrouter/vendor-a/judge-one@2026-06-01", "openrouter/vendor-a/judge-one@latest"),
        encoding="utf-8")
    code, _result, err = run(path, capsys)
    assert code == 1 and "escalation_judge[0]" in err
    assert not _runs(tmp_data_dir)
