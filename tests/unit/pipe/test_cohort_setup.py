"""Creating a cohort with its consent class and roster (TC-ORCH-59..60, live-test blocker B3).

Before this, no command created a cohort or wrote a roster row, yet the consent class decides
whether a cohort's work may leave the machine (FR-CONF-08) and the roster is what intake's identity
gate matches each paper against (FR-INGEST-24).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from aeh.conf import ConsentGateError, resolve_run_config
from aeh.orch import ORCH_STATEMENTS, Orchestrator
from aeh.orch import cohorts as cohorts_module
from aeh.orch.cohorts import (
    CohortSetupError,
    add_to_roster,
    cohort_summary,
    create_cohort,
)
from aeh.pipeline import cli
from aeh.pipeline.rosters import read_roster_file
from aeh.store import open_store
from tests.support.conf_builders import HOSTED_PANEL_3, hosted_cfg


def _roster(store, cohort_id):
    return [row["student_ref"] for row in store.cohort(cohort_id).query(
        ORCH_STATEMENTS["select_roster_refs"], cohort_id=cohort_id)]


def _no_cohort_files(data_dir):
    cohorts = Path(data_dir) / "cohorts"
    return not cohorts.exists() or list(cohorts.iterdir()) == []


# --- TC-ORCH-59: the library ------------------------------------------------------------------


def test_tc_orch_59_a_cohort_is_created_with_its_consent_class_and_roster(tmp_data_dir):
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
    ("Class-9A", "synthetic", ["S1"], "is not allowed"),
    ("nul", "synthetic", ["S1"], "is not allowed"),
    ("com1.x", "synthetic", ["S1"], "is not allowed"),
    ("class-9a", "synthetic", [], "roster is empty"),
    ("class-9a", "synthetic", ["S1", "S 2"], "invisible"),
    ("class-9a", "synthetic", ["S1", "S2​"], "invisible"),
    ("class-9a", "synthetic", ["S1", "S2", "S1"], "more than once: S1"),
])
def test_tc_orch_59_a_refused_cohort_writes_nothing(tmp_data_dir, cohort_id, consent, refs,
                                                   words):
    store = open_store(tmp_data_dir)
    try:
        with pytest.raises(CohortSetupError) as caught:
            create_cohort(store, cohort_id, consent, refs)
        assert words in str(caught.value) and "Nothing was written" in str(caught.value)
    finally:
        store.close()
    assert _no_cohort_files(tmp_data_dir)
    # `cohorts/../evil.sqlite` would land in the data directory itself.
    assert not (Path(tmp_data_dir) / "evil.sqlite").exists()


def test_tc_orch_59_an_existing_cohort_is_never_overwritten(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        create_cohort(store, "class-9a", "synthetic", ["S1"])
        with pytest.raises(CohortSetupError, match="already exists"):
            create_cohort(store, "class-9a", "real", ["S2"])
        assert cohort_summary(store, "class-9a").consent_class == "synthetic"
        assert _roster(store, "class-9a") == ["S1"]
    finally:
        store.close()


def test_tc_orch_59_a_file_holding_another_cohort_is_refused(tmp_data_dir):
    """What a case-insensitive file system does: `class-9b`'s file IS a file holding another
    cohort. Simulated by copying `class-9a`'s database to `class-9b`'s path."""
    import shutil

    store = open_store(tmp_data_dir)
    try:
        create_cohort(store, "class-9a", "synthetic", ["S1"])
        source, target = store.cohort_path("class-9a"), store.cohort_path("class-9b")
    finally:
        store.close()
    shutil.copyfile(source, target)
    store = open_store(tmp_data_dir)
    try:
        with pytest.raises(CohortSetupError, match="refusing to share it"):
            create_cohort(store, "class-9b", "real", ["S2"])
        rows = store.cohort("class-9b").query(ORCH_STATEMENTS["select_cohort_ids"])
        assert [row["cohort_id"] for row in rows] == ["class-9a"]
    finally:
        store.close()


def test_tc_orch_59_the_cohort_and_its_roster_are_one_transaction(tmp_data_dir, monkeypatch):
    """A roster insert that fails after the cohort insert leaves no cohort row."""
    broken = dict(ORCH_STATEMENTS)
    broken["insert_roster_entry"] = ORCH_STATEMENTS["insert_cohort"]  # wrong parameters: fails
    monkeypatch.setattr(cohorts_module, "ORCH_STATEMENTS", broken)
    store = open_store(tmp_data_dir)
    try:
        with pytest.raises(Exception):
            create_cohort(store, "class-9a", "synthetic", ["S1"])
        monkeypatch.setattr(cohorts_module, "ORCH_STATEMENTS", ORCH_STATEMENTS)
        assert cohort_summary(store, "class-9a") is None
    finally:
        store.close()


def test_tc_orch_59_a_simultaneous_create_says_already_exists(tmp_data_dir, monkeypatch):
    """The loser of two creates fails inside the write; the message names the cause."""
    store = open_store(tmp_data_dir)
    try:
        monkeypatch.setattr(cohorts_module, "cohort_summary", lambda store, cohort_id: None)
        create_cohort(store, "class-9a", "synthetic", ["S1"])
        with pytest.raises(CohortSetupError, match="already exists.*same moment"):
            create_cohort(store, "class-9a", "real", ["S1"])
    finally:
        store.close()


def test_tc_orch_59_students_are_added_and_a_repeat_is_refused_whole(tmp_data_dir):
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


def test_tc_orch_59_asking_about_a_missing_cohort_creates_no_file(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        assert cohort_summary(store, "nope") is None
    finally:
        store.close()
    assert not (Path(tmp_data_dir) / "cohorts" / "nope.sqlite").exists()


def test_tc_orch_59_the_consent_gate_acts_on_the_stored_class(tmp_data_dir):
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


# --- TC-ORCH-60: the roster file and the command ----------------------------------------------


@pytest.mark.parametrize("text, expected", [
    ("S1\nS2\n", ("S1", "S2")),
    ("S1\r\nS2\r\n", ("S1", "S2")),
    ("﻿student_ref,name\nS1,Ann\n\nS2,Bo\n", ("S1", "S2")),
    ("name,student_ref\n,S1\nBo,S2\n", ("S1", "S2")),           # a blank name keeps the student
    ('name,student_ref\n"Lee, Ann",S1\n', ("S1",)),
    ("# a comment\n  S1  \n\nS2\n", ("S1", "S2")),
    ("", ()),
])
def test_tc_orch_60_roster_files_read_as_written(tmp_path, text, expected):
    path = tmp_path / "roster.csv"
    path.write_text(text, encoding="utf-8")
    assert read_roster_file(path) == expected


@pytest.mark.parametrize("text, words", [
    ("name,id\nAnn,S1\nBo,S2\n", "no 'student_ref' header"),   # names would become the roster
    ("S1,Ann\n", "no 'student_ref' header"),
    ("id\nS1\nS2\n", "looks like a header"),                    # 'id' would become a student
    ("name,student_ref\nAnn,\n", "line 2 has no student_ref"),  # a student would be dropped
])
def test_tc_orch_60_an_ambiguous_roster_file_is_refused(tmp_path, text, words):
    path = tmp_path / "roster.csv"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(CohortSetupError, match=words):
        read_roster_file(path)


def test_tc_orch_60_aeh_cohort_create_show_and_add(tmp_data_dir, tmp_path, capsys):
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


def test_tc_orch_60_a_bad_id_or_file_is_refused_before_the_data_folder_exists(tmp_path, capsys):
    data_dir = tmp_path / "typo-folder"
    bad = tmp_path / "bad.csv"
    bad.write_text("name,id\nAnn,S1\n", encoding="utf-8")
    assert cli.main(["cohort", "create", "--data-dir", str(data_dir), "--cohort", "Class-9A",
                     "--consent", "synthetic", "--roster", str(bad)]) == 1
    assert cli.main(["cohort", "create", "--data-dir", str(data_dir), "--cohort", "class-9a",
                     "--consent", "synthetic", "--roster", str(bad)]) == 1
    assert not data_dir.exists()
    capsys.readouterr()


def test_tc_orch_60_a_real_cohort_is_flagged_and_the_consent_has_no_default(
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
