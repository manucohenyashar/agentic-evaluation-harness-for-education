"""Validity T14 (issue #911): TC-CONFORM-20 (FR-CONFORM-20) — the live validity check tool, offline.
Statistical-validity test plan §3.13.

| Arm | What is asserted |
|---|---|
| smoke, offline | `tools/live_validity_check.py`'s `main(["--profile", "smoke", ...])`, driven in-process with the command's own loopback client: exit 0, every stage of the trace `[ok]`, and for each sample class every FR-CONFORM-20 section printed — cells scored per sheet (ENG7's four students by name), the verification-refusal rate, the cited share, the confidence distribution, the labels, the administration record, the routing verdict and the purge outcome (dispatched, no paper left) — then the "intended bands" disclaimer |
| a `real` class | the ENG7 class already exists as `real` work: exit 2, "Refused" and the R31 reason on stderr, nothing built (no package file) and nothing sent (the transport saw no request) |

**Departure, disclosed: the stand-in transport, not `HARNESS_FIXTURE_DIR`.** The plan runs the
tool "with a fixture-provider override". No ENG7/PS9 grading recordings exist (TC-E2E-21's are
not captured), and the recording-honesty rule forbids writing them by hand. So the real
`OpenRouterProvider` is pointed at `eng7_sample`'s `FakeOpenRouter` stand-in transport (the
TC-CONF-41 / T9 precedent): pages are answered from the sample transcripts of the very PDFs the
tool reads, the judges answer the lowest band at low confidence, and every reply is built from
its request — none is a live recording and none claims to be. No request leaves the machine (the
console is on 127.0.0.1; the network guard is lifted only for that loopback window). The Jev leg
goes through the TypeSafe SDK path the stand-in does not cover, so `HARNESS_DECISION_ENGINE=off`
(the terminal-wins override the shipped config documents).

**Written ahead: no** (#890 merged).
"""

from __future__ import annotations

import contextlib
import io
import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]
SAMPLES = REPO / "docs" / "live-tests" / "sample-materials"
PDF = SAMPLES / "pdf"
DEV_CI = REPO / "docs" / "live-tests" / "config" / "live-test.dev-ci.toml"

SECTIONS = ("Cells scored per sheet:", "Verification-refusal rate:", "Cited share:",
            "Confidence distribution:", "Labels:", "Administration record:",
            "Routing verdict:", "Purge outcome:")
DISCLAIMER = ('The "teacher" bands in this check are the sample author\'s intended bands: the '
              "band each synthetic answer was written to earn. They are not a teacher's marks, "
              "so the agreement in this check is agreement with the author's intent, not "
              "evidence of accuracy with teachers.")


def _stand_in(monkeypatch, scratch: Path):
    """The real OpenRouter provider bound to the stand-in transport, told every model the smoke
    profile names and the page text of every sample PDF the tool reads."""
    import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ  # noqa: F401,E401
    import aeh.judge, aeh.orch, aeh.pkg, aeh.review, aeh.synth  # noqa: F401,E401
    from aeh.store import open_store
    from tests.support.eng7_sample import forget_sample_modules, install_fake_openrouter
    from tests.support.live_test_config import openrouter_slug

    fake = install_fake_openrouter(monkeypatch)
    section = tomllib.loads(DEV_CI.read_text(encoding="utf-8"))["profiles"]["dev-ci"]
    for ref in list(section["panel"]) + list(section.get("escalation_judge", ())) + [
            section["transcriber"]]:
        fake.models.add(openrouter_slug(ref["build_id"]))

    monkeypatch.syspath_prepend(str(SAMPLES))
    try:
        import build_sample_materials as sm
        import verify_sample_materials as v

        hashes = open_store(scratch)  # content addresses only, never the tool's store
        try:
            blobs = hashes.blobs()
            for test_id, sheets in ((sm.ENGLISH_ID, sm.ENGLISH_SHEETS),
                                    (sm.PHYSICS_ID, sm.PHYSICS_SHEETS)):
                paper = (PDF / test_id / "01-test-paper.pdf").read_bytes()
                fake.pages[(blobs.put(paper), 1)] = v.assessment_transcript(test_id)
                for sheet in sheets:
                    data = (PDF / test_id / "answer-sheets" / f"{sheet['stem']}.pdf").read_bytes()
                    fake.pages[(blobs.put(data), 1)] = v.sheet_transcript(sheet)
        finally:
            hashes.close()
        english = [sheet for sheet in sm.ENGLISH_SHEETS]
    finally:
        forget_sample_modules()
    return fake, english


def _environment(monkeypatch) -> None:
    for name in ("HARNESS_PROFILE", "HARNESS_FIXTURE_DIR", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HARNESS_DECISION_ENGINE", "off")
    monkeypatch.setenv("HARNESS_LIVE_CHECK_POLL_S", "0.2")


def _main(argv: list[str]) -> tuple[int, str, str]:
    from tools.live_validity_check import loopback_request
    from aeh.conform.validity_check import main

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv, console_request=loopback_request)
    return code, out.getvalue(), err.getvalue()


def test_tc_conform_20_smoke_profile_prints_every_section_offline(
        tmp_path, monkeypatch, network_guard) -> None:
    _environment(monkeypatch)
    fake, english = _stand_in(monkeypatch, tmp_path / "hashes")
    data_dir = tmp_path / "check"
    network_guard.uninstall()
    try:
        code, out, err = _main(["--profile", "smoke", "--data-dir", str(data_dir)])
    finally:
        network_guard.install()

    assert code == 0, f"exit {code}\n{out[-4000:]}\n{err[-2000:]}"
    assert fake.sent, "the check graded nothing through the transport"
    stages = re.findall(r"^  \[(\w+)\] (\S+) (.+?)(?: - |$)", out, re.M)
    assert stages and all(status == "ok" for status, _, _ in stages), stages
    for test in ("ENG7-READ-01", "PS9-FORCES-01"):
        names = {stage for _, t, stage in stages if t == test}
        assert names == {"build+ingest", "run", "pipeline figures", "blind sample", "labels",
                         "administration record", "routing verdict", "purge"}, (test, names)

    blocks = re.split(r"^== ", out, flags=re.M)[1:]
    assert [block.split(" ", 1)[0] for block in blocks] == ["ENG7-READ-01", "PS9-FORCES-01"]
    for block in blocks:
        positions = [block.find(section) for section in SECTIONS]
        assert all(p >= 0 for p in positions), (block.split("\n", 1)[0], positions)
        assert positions == sorted(positions), "a section is out of the printed order"
        assert ", complete)" in block.split("\n", 1)[0], block.split("\n", 1)[0]
        purge = re.search(r"^Purge outcome: (.*)$", block, re.M).group(1)
        assert '"dispatched": true' in purge and '"papers_left": 0' in purge, purge
    eng7 = blocks[0]
    sheet_lines = re.findall(r"^  (.+): (\d+) of (\d+) lines scored$",
                             eng7.split("Verification-refusal rate:")[0], re.M)
    assert len(sheet_lines) == 4, sheet_lines
    for sheet in english:
        assert any(sheet["name"] in name for name, _, _ in sheet_lines), (
            sheet["name"], sheet_lines)
    assert all(int(lines) > 0 for _, _, lines in sheet_lines), sheet_lines
    assert out.rstrip().endswith(DISCLAIMER), out[-600:]


def test_tc_conform_20_a_real_class_is_refused_before_anything_is_built_or_sent(
        tmp_path, monkeypatch, network_guard) -> None:
    from aeh.pipeline import cli

    _environment(monkeypatch)
    fake, _english = _stand_in(monkeypatch, tmp_path / "hashes")
    data_dir = tmp_path / "check"
    roster = REPO / "docs" / "live-tests" / "config" / "eng7-roster.txt"
    with contextlib.redirect_stdout(io.StringIO()):
        assert cli.main(["cohort", "create", "--data-dir", str(data_dir), "--cohort",
                         "class-eng7-check", "--consent", "real", "--roster", str(roster)]) == 0
    packages_before = sorted(p.name for p in (data_dir / "packages").glob("*")) \
        if (data_dir / "packages").exists() else []

    code, out, err = _main(["--profile", "smoke", "--data-dir", str(data_dir)])

    assert code == 2, (code, out, err)
    assert err.startswith("Refused: "), err
    assert "'real'" in err and "R31" in err and "Nothing was built" in err, err
    assert DISCLAIMER in err
    assert out == "", out
    assert fake.sent == [] and fake.refused == [], "a request was sent for a real class"
    packages_after = sorted(p.name for p in (data_dir / "packages").glob("*")) \
        if (data_dir / "packages").exists() else []
    assert packages_after == packages_before, "a package was built before the refusal"
    assert not (data_dir / "cohorts" / "class-ps9-check.sqlite").exists()
