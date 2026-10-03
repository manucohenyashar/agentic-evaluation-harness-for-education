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
        assert criteria["C4"]["max_points"] == 3.0 and criteria["C4"]["scoring_model"] == "holistic"
        bands = [(b["ordinal"], b["band"], b["points"]) for b in catalog.bands("C4")]
        assert bands == [(0, "none", 0.0), (1, "limited", 1.0), (2, "adequate", 2.0),
                         (3, "full", 3.0)], bands
        assert catalog.bands("C4")[3]["descriptor"].startswith("Names the weight")
        assert [catalog.answer_key(c) for c in ("C1", "C2", "C3")] == [("C",), ("B",), ("C",)]
        labels = {o["option_id"]: o["label"] for o in catalog.question_options(version, "Q2")}
        assert labels["B"] == "newton"
        assert [catalog.boundary_for(version, score) for score in (10, 8, 7.9, 6, 2, 0)] == [
            "A", "A", "B", "B", "D", "F"]
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


def _with_criterion(index, **fields):
    spec = _spec()
    spec["criterion"] = [dict(c) for c in spec["criterion"]]
    spec["criterion"][index].update(fields)
    for key, value in list(fields.items()):
        if value is None:
            del spec["criterion"][index][key]
    return spec


def _without_points(spec):
    spec["criterion"] = [dict(c) for c in spec["criterion"]]
    spec["criterion"][3]["bands"] = [{k: v for k, v in b.items() if k != "points"}
                                     for b in spec["criterion"][3]["bands"]]
    return spec


@pytest.mark.parametrize("make, words", [
    # Review findings: each of these used to build and publish a package that could not be fixed.
    (lambda: _with_criterion(4, key="Z"), "not among question 'Q5a'"),
    (lambda: _with_criterion(4, key=None, bands=[{"name": "wrong", "points": 0},
                                                 {"name": "right", "points": 1}]),
     "is multiple choice"),
    (lambda: _with_criterion(3, key="A"), "both a 'key' and 'bands'"),
    (lambda: {**_spec(), "criterion": [c for c in _spec()["criterion"] if c["id"] != "C6"]},
     "have no rubric line"),
    (lambda: _without_points(_spec()), "'points' is required"),
    (lambda: _with_criterion(5, depends_on="C4"), "list of criterion ids"),
    (lambda: _with_criterion(5, depends_on=["CX"]), "names no other criterion"),
    (lambda: _with_criterion(5, scoring="holstic"), "is not one of"),
    (lambda: _spec(review_window_hours=1.5), "whole number of hours"),
    (lambda: _with_criterion(0, key=2), "'key' is an option id"),
    (lambda: _with_criterion(3, bands="x"), "list of tables"),
    (lambda: _spec(criterion=["C1"]), "must be a table"),
    (lambda: _spec(grades={"A": "eight"}), "must be a number"),
])
def test_tc_pipe_28_a_spec_a_published_package_could_not_correct_is_refused(
        tmp_data_dir, make, words):
    store = open_store(tmp_data_dir)
    try:
        with pytest.raises(PackageSpecError, match=words):
            build_package(store, make())
    finally:
        store.close()
    packages = Path(tmp_data_dir) / "packages"
    assert not packages.exists() or list(packages.iterdir()) == []


def test_tc_pipe_28_a_zero_hour_review_window_is_kept(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        built = build_package(store, _spec(review_window_hours=0))
        assert _catalog(store, built).grade_policy(built.package_version).review_window_hours == 0
    finally:
        store.close()


def test_tc_pipe_28_a_refused_spec_leaves_no_data_folder(tmp_path, capsys):
    bad = tmp_path / "bad.toml"
    bad.write_text(SAMPLE_SPEC.read_text(encoding="utf-8").replace(
        'package = "PS9-FORCES-01"', 'package = "../evil"'), encoding="utf-8")
    data_dir = tmp_path / "never-made"
    assert cli.main(["package", "build", "--data-dir", str(data_dir), "--spec", str(bad)]) == 1
    assert not data_dir.exists()
    capsys.readouterr()


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
