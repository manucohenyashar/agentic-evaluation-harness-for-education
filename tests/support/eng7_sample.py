"""The sample ENG7 class (four answer sheets) read in through the operator path, graded by a
stand-in OpenRouter transport (issue #818: TC-CONF-41, TC-REG-21).

The live teacher test's small class is `ENG7-READ-01` from `docs/live-tests/sample-materials`:
four papers, one judge (the shipped dev-ci config). `ingest_eng7` builds the package with
`aeh package build`, the class with `aeh cohort create`, and reads the paper and the four sheets
with `aeh ingest` — the commands a teacher runs. Only the transport is a stand-in: the real
`OpenRouterProvider` sends to `FakeOpenRouter`, which answers pages from the sample transcripts
and judges with one band at low confidence (so cells want more judges), and answers 400 to any
model it was not told about, as OpenRouter does. The same shape as TC-PIPE-33's physics world
(`tests/unit/pipe/test_live_escalation_seats.py`).

The Jev decision engine's leg goes through the TypeSafe SDK path, which this transport does not
stand in for, so callers pin `HARNESS_DECISION_ENGINE=off` in the environment (the terminal wins
over the file, as the shipped config itself instructs for a one-off run).
"""

from __future__ import annotations

import io
import json
import re
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aeh.prov import HttpResponse, OpenRouterProvider
from aeh.prov.live import _fields_from_wire
from aeh.store import open_store
from tests.support.live_test_config import configured_models

REPO = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO / "docs" / "live-tests" / "config"
DEV_CI_CONFIG = CONFIG_DIR / "live-test.dev-ci.toml"
ENG7_SPEC = CONFIG_DIR / "eng7-read-01.package.toml"
ENG7_ROSTER = CONFIG_DIR / "eng7-roster.txt"
SAMPLES = REPO / "docs" / "live-tests" / "sample-materials"
ENG7_COHORT = "class-eng7"

TRANSCRIBER, PANEL_JUDGE = configured_models(DEV_CI_CONFIG)


@dataclass
class FakeOpenRouter:
    """OpenRouter for the sample test: pages from the sample transcripts, low-confidence judges,
    and a 400 for any model not in `models`."""

    models: set[str]
    pages: dict[tuple[str, int], str] = field(default_factory=dict)
    sent: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)

    def send(self, request: Any) -> HttpResponse:
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
            text = json.dumps({  # the pinned field order (FR-JUDGE-09)
                "cited_spans": [],
                "evidence_assessment": "No evidence span was extracted for this criterion.",
                "evidence_sufficient": False, "band": bands[0], "self_confidence": 0.1})
        else:
            raise AssertionError(f"an unexpected request: {sorted(fields)}")
        return HttpResponse(200, {}, json.dumps({
            "model": model,
            "choices": [{"finish_reason": "stop", "message": {"content": text}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.00001},
        }).encode("utf-8"))


@dataclass(frozen=True)
class Eng7World:
    fake: FakeOpenRouter
    data_dir: str
    package_version: str
    cohort_id: str = ENG7_COHORT


def install_fake_openrouter(monkeypatch: Any) -> FakeOpenRouter:
    """Route the real `OpenRouterProvider` to a `FakeOpenRouter` serving the shipped models."""
    fake = FakeOpenRouter({TRANSCRIBER, PANEL_JUDGE})
    real = OpenRouterProvider.enforcing_zero_retention.__func__
    monkeypatch.setattr(OpenRouterProvider, "enforcing_zero_retention", classmethod(
        lambda cls, **seams: real(cls, api_key="sk-or-test",
                                  base_url="https://openrouter.test/api/v1", transport=fake)))
    return fake


def ingest_eng7(data_dir: Path, work_dir: Path, monkeypatch: Any, config: Path) -> Eng7World:
    """Build, enrol and ingest the four-paper ENG7 class with the operator commands, under
    `config`. Leaves the environment's orchestration knobs exactly as the caller set them."""
    from aeh.pipeline import cli

    monkeypatch.syspath_prepend(str(SAMPLES))
    import build_sample_materials as sm
    import verify_sample_materials as v

    fake = install_fake_openrouter(monkeypatch)
    files = sm.build_all()
    paper = work_dir / "01-test-paper.pdf"
    paper.write_bytes(files[f"{sm.ENGLISH_ID}/01-test-paper.pdf"])
    sheets = work_dir / "answer-sheets"
    sheets.mkdir()
    store = open_store(data_dir)
    try:
        blobs = store.blobs()
        fake.pages[(blobs.put(paper.read_bytes()), 1)] = v.assessment_transcript(sm.ENGLISH_ID)
        for sheet in sm.ENGLISH_SHEETS:
            data = files[f"{sm.ENGLISH_ID}/answer-sheets/{sheet['stem']}.pdf"]
            (sheets / f"{sheet['stem']}.pdf").write_bytes(data)
            fake.pages[(blobs.put(data), 1)] = v.sheet_transcript(sheet)
    finally:
        store.close()
    data = str(data_dir)
    with redirect_stdout(io.StringIO()) as out:
        assert cli.main(["package", "build", "--data-dir", data, "--spec", str(ENG7_SPEC)]) == 0
    version = json.loads(out.getvalue())["package_version"]
    with redirect_stdout(io.StringIO()):
        assert cli.main(["cohort", "create", "--data-dir", data, "--cohort", ENG7_COHORT,
                         "--consent", "synthetic", "--roster", str(ENG7_ROSTER)]) == 0
        assert cli.main(["ingest", "--data-dir", data, "--cohort", ENG7_COHORT,
                         "--package-version", version, "--config", str(config),
                         "--assessment", str(paper), str(sheets)]) == 0
    return Eng7World(fake=fake, data_dir=data, package_version=version)


def forget_sample_modules() -> None:
    """Drop the sample-materials scripts from `sys.modules` (they are imported off a path)."""
    for name in ("build_sample_materials", "verify_sample_materials"):
        sys.modules.pop(name, None)


def run_rows(data_dir: str | Path, cohort_id: str = ENG7_COHORT) -> list[dict[str, Any]]:
    """Every run row of the cohort: id, status, pause reason and the recorded provider_config."""
    store = open_store(data_dir)
    try:
        return [dict(row) for row in store.cohort(cohort_id).query(
            "SELECT run_id, status, pause_reason, provider_config FROM run")]
    finally:
        store.close()
