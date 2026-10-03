"""Creating a cohort with its consent class and roster (TC-INGEST-56..57, live-test blocker B3).

Before this, no command created a cohort or wrote a roster row, yet the consent class decides
whether a cohort's work may leave the machine (FR-CONF-08) and the roster is what intake's identity
gate matches each paper against (FR-INGEST-24).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aeh.conf import ConsentGateError, resolve_run_config
from aeh.ingest import (
    CohortSetupError,
    INGEST_STATEMENTS,
    add_to_roster,
    cohort_summary,
    create_cohort,
    read_roster_file,
)
from aeh.orch import Orchestrator
from aeh.pipeline import cli
from aeh.store import open_store
from tests.support.conf_builders import HOSTED_PANEL_3, hosted_cfg


def _roster(store, cohort_id):
    return sorted(row["student_ref"] for row in store.cohort(cohort_id).query(
        INGEST_STATEMENTS["select_roster"], cohort_id=cohort_id))


# --- TC-INGEST-56: the library ----------------------------------------------------------------


def test_tc_ingest_56_a_cohort_is_created_with_its_consent_class_and_roster(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        summary = create_cohort(store, "class-9a", "synthetic", ["S9-001", "S9-002"],
                                created_at="2026-10-03T00:00:00+00:00")
        assert (summary.consent_class, summary.roster_size) == ("synthetic", 2)
        assert _roster(store, "class-9a") == ["S9-001", "S9-002"]
        # The consent gate reads what was stored, not CohortRef's fail-closed default.
        assert Orchestrator(store).cohort_ref("class-9a").consent_class == "synthetic"
        assert cohort_summary(store, "class-9a") == summary
    finally:
        store.close()


@pytest.mark.parametrize("cohort_id, consent, refs, words", [
    ("class-9a", "maybe", ["S1"], "is not one of"),
    ("../evil", "synthetic", ["S1"], "is not allowed"),
    ("a/b", "synthetic", ["S1"], "is not allowed"),
    ("class.", "synthetic", ["S1"], "is not allowed"),
    ("class-9a", "synthetic", [], "roster is empty"),
    ("class-9a", "synthetic", ["S1", "S 2"], "contain spaces"),
    ("class-9a", "synthetic", ["S1", "S2", "S1"], "more than once: S1"),
])
def test_tc_ingest_56_a_refused_cohort_writes_nothing(tmp_data_dir, cohort_id, consent, refs,
                                                     words):
    store = open_store(tmp_data_dir)
    try:
        with pytest.raises(CohortSetupError) as caught:
            create_cohort(store, cohort_id, consent, refs)
        assert words in str(caught.value) and "Nothing was written" in str(caught.value)
    finally:
        store.close()
    cohorts = Path(tmp_data_dir) / "cohorts"
    assert not cohorts.exists() or list(cohorts.iterdir()) == [], list(cohorts.iterdir())
    # `cohorts/../evil.sqlite` would land in the data directory itself.
    assert not (Path(tmp_data_dir) / "evil.sqlite").exists()


def test_tc_ingest_56_an_existing_cohort_is_never_overwritten(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        create_cohort(store, "class-9a", "synthetic", ["S1"])
        with pytest.raises(CohortSetupError, match="already exists"):
            create_cohort(store, "class-9a", "real", ["S2"])
        assert cohort_summary(store, "class-9a").consent_class == "synthetic"
        assert _roster(store, "class-9a") == ["S1"]
    finally:
        store.close()


def test_tc_ingest_56_students_are_added_and_a_repeat_is_refused_whole(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        create_cohort(store, "class-9a", "consented", ["S1"])
        with pytest.raises(CohortSetupError, match="already on the roster: S1"):
            add_to_roster(store, "class-9a", ["S2", "S1"])
        assert _roster(store, "class-9a") == ["S1"]
        assert add_to_roster(store, "class-9a", ["S2", "S3"]).roster_size == 3
        assert cohort_summary(store, "class-9a").consent_class == "consented"
        with pytest.raises(CohortSetupError, match="create it first"):
            add_to_roster(store, "no-such", ["S1"])
    finally:
        store.close()


def test_tc_ingest_56_asking_about_a_missing_cohort_creates_no_file(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        assert cohort_summary(store, "nope") is None
    finally:
        store.close()
    assert not (Path(tmp_data_dir) / "cohorts" / "nope.sqlite").exists()


def test_tc_ingest_56_the_consent_gate_acts_on_the_stored_class(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        create_cohort(store, "class-real", "real", ["S1"])
        create_cohort(store, "class-syn", "synthetic", ["S1"])
        orchestrator = Orchestrator(store)
        cfg = hosted_cfg("dev-ci", panel=HOSTED_PANEL_3)
        with pytest.raises(ConsentGateError):
            resolve_run_config(cfg, orchestrator.cohort_ref("class-real"))
        assert resolve_run_config(cfg, orchestrator.cohort_ref("class-syn")).backend_profile == "dev-ci"
    finally:
        store.close()


@pytest.mark.parametrize("text, expected", [
    ("S1\nS2\n", ("S1", "S2")),
    ("﻿student_ref,name\nS1,Ann\n\n# skip me\nS2,Bo\n", ("S1", "S2")),
    ("name,student_ref\nAnn, S1 \nBo,S2\n", ("S1", "S2")),
    ("# header comment\nS1,extra\n  S2  \n", ("S1", "S2")),
    ("", ()),
])
def test_tc_ingest_56_roster_files(tmp_path, text, expected):
    path = tmp_path / "roster.csv"
    path.write_text(text, encoding="utf-8")
    assert read_roster_file(path) == expected


# --- TC-INGEST-57: the command ----------------------------------------------------------------


def test_tc_ingest_57_aeh_cohort_create_show_and_add(tmp_data_dir, tmp_path, capsys):
    roster = tmp_path / "roster.csv"
    roster.write_text("﻿student_ref\nS9-001\nS9-002\n", encoding="utf-8")
    more = tmp_path / "more.txt"
    more.write_text("S9-003\n", encoding="utf-8")
    base = ["--data-dir", str(tmp_data_dir), "--cohort", "class-9a"]

    assert cli.main(["cohort", "create", *base, "--consent", "synthetic",
                     "--roster", str(roster)]) == 0
    created = json.loads(capsys.readouterr().out)
    assert (created["consent_class"], created["roster_size"]) == ("synthetic", 2)

    assert cli.main(["cohort", "add-students", *base, "--roster", str(more)]) == 0
    assert json.loads(capsys.readouterr().out)["roster_size"] == 3

    assert cli.main(["cohort", "show", *base]) == 0
    assert json.loads(capsys.readouterr().out)["roster_size"] == 3

    assert cli.main(["cohort", "create", *base, "--consent", "real",
                     "--roster", str(roster)]) == 1
    assert "already exists" in capsys.readouterr().err


def test_tc_ingest_57_a_real_cohort_is_flagged_and_the_consent_has_no_default(
        tmp_data_dir, tmp_path, capsys):
    roster = tmp_path / "roster.txt"
    roster.write_text("S1\n", encoding="utf-8")
    base = ["cohort", "create", "--data-dir", str(tmp_data_dir), "--cohort", "c-real",
            "--roster", str(roster)]
    with pytest.raises(SystemExit):
        cli.main(base)  # argparse: --consent is required
    capsys.readouterr()
    assert cli.main([*base, "--consent", "real"]) == 0
    assert "HARNESS_ALLOW_REMOTE_REAL_WORK" in capsys.readouterr().err
