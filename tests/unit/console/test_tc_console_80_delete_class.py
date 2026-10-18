"""`TC-CONSOLE-80` — a class made by mistake can be deleted; a class with work cannot.

*Inline regression.* The classes screen's "Delete this class" posts `purge cohort`, and
M-STORE's purge runs only after a cohort's evidence is promoted to Tier D (FR-STORE-07,
CT-STORE-10). A class that never held a paper or a run has nothing to promote, so the purge
refused it forever and the mistaken class stayed listed; and a purged class's emptied file was
still listed under its old name. Arms: (a) a list-only class is removed — its file is gone and
the class read no longer lists it; (b) a class holding a paper is refused with the purge's
reason, and keeps its file and its paper.
"""

from __future__ import annotations

from pathlib import Path

from aeh.console import build_console
from aeh.console.screen_reads import class_roster_read
from aeh.store import open_store


def _classes(console) -> list[str]:
    return [entry["cohort_id"] for entry in class_roster_read(None, console, {})["cohorts"]]


def test_tc_console_80_a_list_only_class_is_removed_and_no_longer_listed(tmp_path):
    store = open_store(tmp_path / "data")
    try:
        console = build_console(store=store)
        made = console.perform("create class", class_id="7b-mistake", consent_class="synthetic",
                               paste="Ada Lovelace\nAlan Turing")
        assert made.dispatched, made.detail
        assert "7b-mistake" in _classes(console)

        gone = console.perform("purge cohort", cohort_id="7b-mistake")
        assert gone.dispatched, gone.detail
        assert not Path(store.cohort_path("7b-mistake")).exists()
        assert "7b-mistake" not in _classes(console)
    finally:
        store.close()


def test_tc_console_80_a_class_holding_a_paper_is_refused_and_untouched(tmp_path):
    store = open_store(tmp_path / "data")
    try:
        console = build_console(store=store)
        assert console.perform("create class", class_id="7b-real", consent_class="synthetic",
                               paste="Ada Lovelace").dispatched
        handle = store.cohort("7b-real")
        with handle.transaction() as tx:
            tx.execute("INSERT INTO submission (submission_id, cohort_id, student_ref) "
                       "VALUES ('sub-1', '7b-real', 'unknown')")
        refused = console.perform("purge cohort", cohort_id="7b-real")
        assert not refused.dispatched
        assert "saved for validation" in refused.detail, refused.detail
        assert Path(store.cohort_path("7b-real")).exists()
        assert "7b-real" in _classes(console)
        assert store.cohort("7b-real").query("SELECT COUNT(*) AS n FROM submission")[0]["n"] == 1
    finally:
        store.close()
