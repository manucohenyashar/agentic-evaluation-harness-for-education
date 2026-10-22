"""`TC-STORE-30` (issue #820): purging a class removes its AI-call journal, and nothing else.

Console clarity test plan §3.3, story T7. FR-CONSOLE-77, CT-STORE-10; RC-06. **Regression
entry:** nothing of a purged class may survive, and the journal holds its students' answers and
what the models said of them.

| Arm | What is asserted |
|---|---|
| refused | a purge the store refuses (Tier D not promoted: `PurgePreconditionError`) leaves the whole journal in place, byte for byte |
| purged | after the purge: `logs/ai-calls/<cohort_id>/` does not exist and `PurgeReport.ai_call_journal_deleted` is True; another class's folder, `_packages/` and `_help/` are byte-identical to before |

**Isolation.** Rung 3: a real store over real SQLite files; the journal seeded through the real
`JsonlCallJournal` (records carrying the class's id, two UTC dates for the purged class). The
class and the Tier D promotion are seeded the way `test_purge.py` (TC-STORE-11) seeds them.

**Markers.** `integration` (the fast tier excludes it). Not written ahead: #807 is merged.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from aeh.prov import CallRecord, JsonlCallJournal, journal_root
from tests.integration.store.test_purge import _promote, _seed_cohort
from tests.support.store_api import open_store

pytestmark = pytest.mark.integration

PURGED = "c-journal"
OTHER = "c-other"
PACKAGE = "ENG7-READ-01"


def _record(n: int, *, at: str, kind: str = "ai_judge", cohort_id: str | None = None,
            package_id: str | None = None) -> CallRecord:
    return CallRecord(
        call_id=f"call-{n}", attempt=1, at=at, kind=kind, cohort_id=cohort_id,
        run_id="r1" if cohort_id else None, work_id=None, submission_id=None,
        criterion_id=None, package_id=package_id, model="fixture/m@1", resolved_build=None,
        request=[["submission_transcript", "a student's answer"]], response="band 2",
        outcome="ok", error=None, tokens_in=3, tokens_out=2, latency_ms=4, cost=None)


def _seed_journal(data_dir: Path) -> None:
    sink = JsonlCallJournal(data_dir)
    sink(_record(1, at="2026-10-20T09:00:00.000+00:00", cohort_id=PURGED))
    sink(_record(2, at="2026-10-21T09:00:00.000+00:00", cohort_id=PURGED))
    sink(_record(3, at="2026-10-21T09:00:00.000+00:00", cohort_id=OTHER))
    sink(_record(4, at="2026-10-21T09:00:00.000+00:00", kind="package_drafting",
                 package_id=PACKAGE))
    sink(_record(5, at="2026-10-21T09:00:00.000+00:00", kind="help_question"))


def _snapshot(folder: Path) -> dict[str, str]:
    """Every file under `folder`, by relative path, with its sha256."""
    return {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob("*")) if path.is_file()}


def test_tc_store_30_purge_removes_the_class_journal_and_nothing_else(tmp_data_dir):
    store = open_store(tmp_data_dir)
    _seed_cohort(store, PURGED)
    _seed_cohort(store, OTHER)
    _seed_journal(tmp_data_dir)
    root = journal_root(tmp_data_dir)
    purged_folder = root / PURGED
    survivors = {name: root / name for name in (OTHER, "_packages", "_help")}

    before = _snapshot(root)
    assert sorted(_snapshot(purged_folder)) == ["2026-10-20.jsonl", "2026-10-21.jsonl"], (
        f"precondition: the seeded class journal is {sorted(_snapshot(purged_folder))}")
    assert all(_snapshot(folder) for folder in survivors.values()), (
        f"precondition: a survivor folder is empty: {before}")

    # --- refused: Tier D not promoted, so the store refuses and nothing is half-deleted -------
    with pytest.raises(Exception) as refused:
        store.purge_cohort(PURGED)
    assert type(refused.value).__name__ == "PurgePreconditionError", repr(refused.value)
    assert _snapshot(root) == before, (
        "TC-STORE-30: a refused purge changed the AI-call journal; nothing may be deleted "
        "before the store commits the purge")

    # --- purged ------------------------------------------------------------------------------
    _promote(store, PURGED)
    report = store.purge_cohort(PURGED)
    assert report.cohort_id == PURGED
    assert not purged_folder.exists(), (
        f"TC-STORE-30: {purged_folder} survives the purge: the class's students' answers and "
        f"the models' verdicts on them are still on disk ({_snapshot(purged_folder)})")
    assert report.ai_call_journal_deleted is True, (
        "the purge removed the folder but its report says it did not")
    expected = {path: digest for path, digest in before.items()
                if not Path(path).parts[0] == PURGED}
    assert _snapshot(root) == expected, (
        "TC-STORE-30: the purge touched another class's journal, `_packages/` or `_help/`")
    with sqlite3.connect(store.cohort_path(OTHER)) as raw:
        assert raw.execute("SELECT COUNT(*) FROM cohort").fetchone()[0] == 1
