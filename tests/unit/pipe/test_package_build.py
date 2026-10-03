"""Building a package from a spec (TC-PIPE-27..29, live-test blocker B5).

Before this, a package could only be built by library calls. `aeh package build` builds the
version a TOML spec describes through `M-PKG`'s API, with its question inventory (a judge's
criterion text and question come from it), and publishes it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from aeh.pipeline import cli
from aeh.pipeline.packages import PackageSpecError, build_package, read_package_spec
from aeh.pkg import PackageCatalog
from aeh.store import open_store

REPO = Path(__file__).resolve().parents[3]
SAMPLE_SPEC = REPO / "docs" / "live-tests" / "config" / "ps9-forces-01.package.toml"
SAMPLES = REPO / "docs" / "live-tests" / "sample-materials"


def _spec(**changes):
    spec = read_package_spec(SAMPLE_SPEC)
    spec.update(changes)
    return spec


def _catalog(store, built):
    return PackageCatalog(store.package(built.package_id), package_id=built.package_id,
                          blobs=store.blobs())


# --- TC-PIPE-27: the sample spec builds a complete, published package --------------------------


def test_tc_pipe_27_the_sample_spec_builds_and_publishes(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        built = build_package(store, _spec())
        catalog = _catalog(store, built)
        version = built.package_version
        assert version.startswith("PS9-FORCES-01@")
        assert (built.questions, built.criteria, built.answer_keys) == (6, 6, 4)
        questions = {q["question_id"]: q for q in catalog.questions(version)}
        assert list(questions) == ["Q1", "Q2", "Q3", "Q4", "Q5a", "Q5b"]
        assert questions["Q4"]["prompt_text"].startswith("A book rests on a table")
        assert questions["Q4"]["reference_solution"].startswith("Two forces act on the book")
        assert [o["option_id"] for o in catalog.question_options(version, "Q1")] == list("ABCD")
        criteria = {row["criterion_id"]: row for row in catalog.criteria(version)}
        assert criteria["C4"]["kind"] == "open" and criteria["C4"]["evidence_type"]
        assert criteria["C1"]["kind"] == "mcq"
        assert catalog.answer_key("C5") == ("B",)
        assert built.grades == ("A", "B", "C", "D", "F")
        # Published: the version refuses any further change.
        with pytest.raises(Exception):
            catalog.add_criterion(version, "C9", question_id="Q1")
    finally:
        store.close()


def test_tc_pipe_27_aeh_package_build_prints_the_version(tmp_data_dir, capsys):
    args = ["package", "build", "--data-dir", str(tmp_data_dir), "--spec", str(SAMPLE_SPEC)]
    assert cli.main(args) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["package_version"].startswith("PS9-FORCES-01@")
    assert cli.main(args) == 1
    assert "already exists" in capsys.readouterr().err


# --- TC-PIPE-28: refusals write nothing, and a corrected spec builds under the same id ---------


@pytest.mark.parametrize("changes, words", [
    ({"package": "../evil"}, "is not allowed"),
    ({"package": "NUL"}, "is not allowed"),
    ({"approved_by": ""}, "'approved_by' is required"),
    ({"question": []}, "no [[question]]"),
    ({"criterion": [{"id": "C1", "question": "Q9", "key": "A"}]}, "does not list"),
    ({"criterion": [{"id": "C1", "question": "Q4", "key": "A"}]}, "has no options"),
    ({"criterion": [{"id": "C1", "question": "Q4"}]}, "either a 'key'"),
])
def test_tc_pipe_28_a_spec_that_cannot_be_translated_creates_nothing(tmp_data_dir, changes,
                                                                    words):
    store = open_store(tmp_data_dir)
    try:
        with pytest.raises(PackageSpecError, match=words.replace("[", r"\[").replace("]", r"\]")):
            build_package(store, _spec(**changes))
    finally:
        store.close()
    packages = Path(tmp_data_dir) / "packages"
    assert not packages.exists() or list(packages.iterdir()) == []


def test_tc_pipe_28_the_same_name_ignoring_case_is_one_package(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        build_package(store, _spec())
        with pytest.raises(PackageSpecError, match="ignoring case"):
            build_package(store, _spec(package="ps9-forces-01"))
    finally:
        store.close()


def test_tc_pipe_28_a_rule_m_pkg_refuses_leaves_no_half_package(tmp_data_dir):
    """Three bands is odd: M-PKG refuses it (FR-PKG-06) after the package file exists. The file
    is removed, and the corrected spec then builds under the same id."""
    spec = _spec()
    spec["criterion"] = [dict(c) for c in spec["criterion"]]
    spec["criterion"][3]["bands"] = spec["criterion"][3]["bands"][:3]
    store = open_store(tmp_data_dir)
    with pytest.raises(Exception, match="odd"):
        build_package(store, spec)
    assert not any((Path(tmp_data_dir) / "packages").glob("*.sqlite*"))
    store = open_store(tmp_data_dir)
    try:
        assert build_package(store, _spec()).criteria == 6
    finally:
        store.close()


# --- TC-PIPE-29: the built package and a created cohort carry the sample sheets through intake ---


def test_tc_pipe_29_the_sample_sheets_meet_the_real_intake_gates(tmp_data_dir, monkeypatch):
    """`aeh package build` + `aeh cohort create`, then the ten-sheet sample's physics half through
    the real `Ingestor` (V0-V4), the page reader stood in by the sample script's scripted
    transcripts. Every sheet lands where the live-test guide says, and a dev-ci run is created
    over the package."""
    pytest.importorskip("pypdfium2")
    monkeypatch.syspath_prepend(str(SAMPLES))
    import build_sample_materials as sm
    import verify_sample_materials as v

    from aeh.conf import resolve_run_config
    from aeh.ingest import Ingestor, PdfiumRasterizer, PypdfSanitizer, ResidencySlot
    from aeh.orch import Orchestrator
    from aeh.orch.cohorts import create_cohort
    from aeh.prov import SamplingParams
    from tests.support.conf_builders import HOSTED_PANEL_3, hosted_cfg

    store = open_store(tmp_data_dir)
    try:
        built = build_package(store, _spec())
        catalog = _catalog(store, built)
        sheets = sm.PHYSICS_SHEETS
        create_cohort(store, "class-ps9", "synthetic",
                      [sheet["student"] or "S9-006" for sheet in sheets])
        files = sm.build_all()
        reader, blobs = v.ScriptedReader(), store.blobs()
        ingestor = Ingestor(store.cohort("class-ps9"), blobs, reader, v.TRANSCRIBER,
                            SamplingParams(temperature=0.0), PdfiumRasterizer(),
                            residency=ResidencySlot.for_policy(("transcriber",)),
                            sanitizer=PypdfSanitizer())
        paper = blobs.put(files[f"{sm.PHYSICS_ID}/01-test-paper.pdf"])
        reader.stage(paper, [v.assessment_transcript(sm.PHYSICS_ID)])
        ingestor.ingest_document([paper], kind="assessment", order_hint=[paper])
        outcomes = {}
        for sheet in sheets:
            blob = blobs.put(files[f"{sm.PHYSICS_ID}/answer-sheets/{sheet['stem']}.pdf"])
            reader.stage(blob, [v.sheet_transcript(sheet)])
            report = ingestor.ingest_submission(
                [blob], "class-ps9", built.package_version, order_hint=[blob],
                filenames={blob: sheet["stem"] + ".pdf"}, package_catalog=catalog)
            outcomes[sheet["stem"]] = report.ingest_status
        assert outcomes == {stem: v.EXPECTED_STATUS[stem] for stem in outcomes}, outcomes
        orchestrator = Orchestrator(store)
        cfg = resolve_run_config(hosted_cfg("dev-ci", panel=HOSTED_PANEL_3),
                                 orchestrator.cohort_ref("class-ps9"))
        run_id = orchestrator.create_run("class-ps9", built.package_version, cfg)
        assert orchestrator.enumerate_units(run_id).units_enumerated > 0
    finally:
        store.close()
        for name in ("build_sample_materials", "verify_sample_materials"):
            sys.modules.pop(name, None)
