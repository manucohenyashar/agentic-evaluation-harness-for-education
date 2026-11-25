"""Validity T18 (issue #903): the built review queue, served (TC-CONSOLE-117), and the group
action and skip (TC-CONSOLE-118). Rung 3, over HTTP.

| Case | What is asserted |
|---|---|
| TC-CONSOLE-117 (FR-CONSOLE-91, CT-CONSOLE-58) | `GET /api/v1/review-queue?budget_minutes=30`: the five header numbers equal `build_queue(run_id, 30, record=False)`'s on the same store; `entries` are `built.shown` in the service's order (the group first, then items with `rank_score` non-increasing, an order that is NOT the submission order); the group's size, three samples and shared band; per item: full name (not the ref), question and line labels, `proposed_band` (the stored band), `panel` (each grader's verdict band, under a grader name), `why_flagged` (exactly the service's reasons, in the four teacher phrases, no float), the stored feedback sentence, quotes, `est_seconds`, the package's levels, `revision` (the stored panel depth); no `confidence` key anywhere; budgets 0, 481 and a word refused 400 naming 1…480, 1 and 480 served; two GETs write no `shown_at` (and a `record=True` build does — the control); two random-arm cells and the open draw's seats are in no entry and out of `flagged_total`; deterministic lines never reach the queue (on the validity store, which has MCQ lines) |
| TC-CONSOLE-118 (FR-CONSOLE-92; CT-REVIEW-13/15) | `review group action` at the proposed band writes one `accept` label per member and says *n answers marked*; at another band with one member escalated between read and action (`judge_count` 1 → 3, the stored version), that member is refused by full name and every other member gets one `edit` label; `review action` with `decision = 'skip'` writes no label, the cell stays `provisional_unreviewed` and is in the next build and the next read |

**World.** ENG7 graded by the console's own `start run` (`tests/support/eng7_console.py`), shaped
by `tests/support/console_r2_world.shape_queue`: one group (the four C1a cells) and twelve single
items with distinct rank scores. Every number compared is read from M-REVIEW or the store.

**Departures from the plan's seed** (disclosed in the PR): ENG7 has four papers, so the group
has 4 members, not 6, and the reply's *n* is the group's size; ENG7 has no deterministic line, so
the deterministic-absence arm runs on the validity store's MCQ lines.

**Mutations (run by hand, recorded in the PR):** `built_queue_document` sorting `entries` by
submission id -> 117's order arm red.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

import pytest

from tests.support.console_r2_world import (
    GROUP_CRITERION,
    eng7_levels,
    served_validity,
    shape_queue,
)
from tests.support.eng7_console import Eng7Console, eng7_console

pytestmark = pytest.mark.integration

#: FR-REVIEW-03's four inputs in the teacher's words (FR-CONSOLE-91), spelled here, keyed by
#: M-REVIEW's reason codes.
FOUR_PHRASES = {
    "panel_disagreement": "panel disagreement",
    "near_grade_boundary": "near a grade boundary",
    "reading_uncertain": "reading uncertain",
    "often_changed": "this line is often changed",
}
HEADER = ("budget_minutes", "reserved_for_blind_minutes", "flagged_total", "shown_total",
          "residual_provisional")


def _keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


def _built_key(entry: Any) -> tuple:
    members = getattr(entry, "members", None)
    if members is not None:
        return ("group", str(entry.criterion_id),
                tuple(sorted(str(m.submission_id) for m in members)))
    return ("item", str(entry.criterion_id), str(entry.submission_id))


def _served_key(entry: dict) -> tuple:
    if entry["kind"] == "group":
        return ("group", entry["criterion_id"],
                tuple(sorted(m["submission_id"] for m in entry["members"])))
    return ("item", entry["criterion_id"], entry["submission_id"])


def _cells_in(entries: list[dict]) -> set[tuple[str, str]]:
    cells = set()
    for entry in entries:
        if entry["kind"] == "group":
            cells |= {(m["submission_id"], entry["criterion_id"]) for m in entry["members"]}
            cells |= {(s["submission_id"], s["criterion_id"]) for s in entry["sample"]}
        else:
            cells.add((entry["submission_id"], entry["criterion_id"]))
    return cells


def _queue(served: Any, budget: int = 30) -> dict:
    status, document = served.get("/api/v1/review-queue", run_id=served.run_id,
                                  budget_minutes=budget)
    assert status == 200, document
    return document


def _questions(served: Eng7Console) -> dict[str, str]:
    status, screen = served.get("/api/v1/results/screen", run_id=served.run_id)
    assert status == 200, screen
    return {line["criterion_id"]: line["question_id"]
            for student in screen["students"] for line in student["criteria"]}


def _shown_at_count(served: Any) -> int:
    return served.rows("SELECT COUNT(*) AS n FROM review_queue WHERE shown_at IS NOT NULL")[0]["n"]


def _check_item(served: Eng7Console, service: Any, entry: dict, built_item: Any,
                questions: dict[str, str], refs: dict[str, str], names: dict[str, str],
                cells: dict[tuple[str, str], dict]) -> list[str]:
    problems: list[str] = []
    sub, crit = entry["submission_id"], entry["criterion_id"]
    where = f"{sub}/{crit}"
    stored = cells[(sub, crit)]
    if entry.get("full_name") != names[sub] or entry.get("full_name") == refs[sub]:
        problems.append(f"{where}: full_name {entry.get('full_name')!r}, roster {names[sub]!r}")
    if entry.get("question_label") != questions[crit] or entry.get("criterion_label") != crit:
        problems.append(f"{where}: labels {entry.get('question_label')!r}/"
                        f"{entry.get('criterion_label')!r}")
    if entry.get("proposed_band") != stored["band"]:
        problems.append(f"{where}: proposed_band {entry.get('proposed_band')!r}, "
                        f"stored {stored['band']!r}")
    verdicts = served.rows(
        "SELECT v.band, v.judge_id FROM verdict v JOIN work_unit w ON w.work_id = v.work_id "
        "WHERE w.run_id = ? AND w.submission_id = ? AND w.criterion_id = ? ORDER BY v.work_id",
        served.run_id, sub, crit)
    panel = entry.get("panel") or []
    if [p.get("band") for p in panel] != [v["band"] for v in verdicts] or not panel:
        problems.append(f"{where}: panel {panel}, verdicts {[v['band'] for v in verdicts]}")
    judge_ids = {v["judge_id"] for v in verdicts}
    if any(p.get("grader") in judge_ids or not p.get("grader") for p in panel):
        problems.append(f"{where}: a grader is named by its model id: {panel}")
    why = entry.get("why_flagged")
    expected_why = [FOUR_PHRASES[code] for code in service.flag_reasons(built_item)]
    if not why or why != expected_why or not set(why) <= set(FOUR_PHRASES.values()) \
            or any(not isinstance(word, str) for word in why):
        problems.append(f"{where}: why_flagged {why!r}, the service's {expected_why!r}")
    narrative = served.rows(
        "SELECT text FROM narrative WHERE run_id = ? AND submission_id = ? AND "
        "question_id = ? AND level = 'l1_question'", served.run_id, sub, questions[crit])
    if not narrative or entry.get("narrative") != narrative[0]["text"] or not entry["narrative"]:
        problems.append(f"{where}: narrative {entry.get('narrative')!r}")
    if not isinstance(entry.get("quotes"), list) or \
            any(not isinstance(q, str) for q in entry["quotes"]):
        problems.append(f"{where}: quotes {entry.get('quotes')!r}")
    if entry.get("est_seconds") != pytest.approx(float(built_item.est_seconds)):
        problems.append(f"{where}: est_seconds {entry.get('est_seconds')!r}, "
                        f"service {built_item.est_seconds!r}")
    if entry.get("levels") != eng7_levels()[crit]:
        problems.append(f"{where}: levels {entry.get('levels')!r}")
    if entry.get("revision") != int(stored["judge_count"] or 1):
        problems.append(f"{where}: revision {entry.get('revision')!r}, "
                        f"stored judge_count {stored['judge_count']!r}")
    if entry.get("rank_score") != pytest.approx(float(built_item.expected_value)):
        problems.append(f"{where}: rank_score {entry.get('rank_score')!r}")
    return problems


def test_tc_console_117_the_built_queue_is_served_as_the_service_builds_it(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-117 (see the module docstring)."""
    with eng7_console(tmp_path / "w", tmp_path / "work", monkeypatch, network_guard) as served:
        shape_queue(served)
        service = served.service()
        refs = served.roster_refs()
        names = served.names()
        questions = _questions(served)
        shown_before = _shown_at_count(served)

        document = _queue(served)
        built = service.build_queue(served.run_id, 30, record=False)

        # Header equality.
        for key in HEADER:
            assert document[key] == getattr(built, key), (
                f"{key}: served {document[key]!r}, the service built {getattr(built, key)!r}")

        # Order: the service's own, groups first, rank non-increasing, not the paper order.
        entries = document["entries"]
        assert [_served_key(e) for e in entries] == [_built_key(e) for e in built.shown], (
            "the read does not serve the service's entries in the service's order")
        assert entries and entries[0]["kind"] == "group", entries[:1]
        groups = [e for e in entries if e["kind"] == "group"]
        items = [e for e in entries if e["kind"] == "item"]
        assert len(groups) == 1 and entries.index(groups[0]) == 0, "fixture: one group, first"
        scores = [e["rank_score"] for e in items]
        assert scores == sorted(scores, reverse=True), f"items not in rank order: {scores}"
        by_paper = sorted(items, key=lambda e: (e["submission_id"], e["criterion_id"]))
        assert [_served_key(e) for e in items] != [_served_key(e) for e in by_paper], (
            "fixture: the rank order equals the submission order, so the order arm is vacuous")

        # The group.
        group = groups[0]
        cells = served.judged_cells()
        group_cells = sorted(sub for (sub, crit) in cells if crit == GROUP_CRITERION)
        assert group["criterion_id"] == GROUP_CRITERION
        assert group["size"] == len(group["members"]) == len(group_cells) == len(
            built.shown[0].members), group
        assert sorted(m["submission_id"] for m in group["members"]) == group_cells
        assert len(group["sample"]) == 3, f"three sample members, not {len(group['sample'])}"
        assert {s["submission_id"] for s in group["sample"]} <= set(group_cells)
        shared = {cells[(sub, GROUP_CRITERION)]["band"] for sub in group_cells}
        assert len(shared) == 1 and group["proposed_band"] == shared.pop() and all(
            s["proposed_band"] == group["proposed_band"] for s in group["sample"]), group
        assert isinstance(group.get("pattern"), str) and str(group["size"]) in group["pattern"]
        assert all(m["full_name"] == names[m["submission_id"]] for m in group["members"])
        assert all(m["revision"] == int(cells[(m["submission_id"], GROUP_CRITERION)]
                                        ["judge_count"] or 1) for m in group["members"])

        # Per item (and each of the group's samples).
        built_items = {(str(e.submission_id), str(e.criterion_id)): e for e in built.shown
                       if getattr(e, "members", None) is None}
        for member in built.shown[0].members:
            built_items[(str(member.submission_id), str(member.criterion_id))] = member
        problems: list[str] = []
        for entry in items + group["sample"]:
            problems += _check_item(served, service, entry,
                                    built_items[(entry["submission_id"], entry["criterion_id"])],
                                    questions, refs, names, cells)
        assert not problems, "per-item fields:\n  " + "\n  ".join(problems)
        assert "confidence" not in set(_keys(document)), "a confidence figure is served"
        assert any("reading uncertain" in e["why_flagged"] for e in items) and any(
            "reading uncertain" not in e["why_flagged"] for e in items), (
            "fixture: why_flagged does not vary, so the reasons arm proves little")

        # Budget bounds.
        for bad in (0, 481, "thirty"):
            status, body = served.get("/api/v1/review-queue", run_id=served.run_id,
                                      budget_minutes=bad)
            text = json.dumps(body, ensure_ascii=False)
            assert status == 400 and re.search(r"\b1\b\D{1,12}\b480\b", text), (bad, status, body)
        for good in (1, 480):
            assert _queue(served, good)["budget_minutes"] == good

        # A read is a read.
        _queue(served)
        _queue(served)
        assert _shown_at_count(served) == shown_before, "a GET of the queue wrote shown_at"

        # Random-arm cells are held out.
        single_c2 = sorted(e["submission_id"] for e in items if e["criterion_id"] == "C2")[:2]
        for sub in single_c2:
            served.execute("UPDATE work_unit SET origin = 'random_arm' WHERE run_id = ? AND "
                           "submission_id = ? AND criterion_id = 'C2' AND stage = 'score'",
                           served.run_id, sub)
        random_arm = {(sub, "C2") for sub in single_c2}
        document = _queue(served)
        built = service.build_queue(served.run_id, 30, record=False)
        assert document["flagged_total"] == built.flagged_total == len(cells) - 2, (
            document["flagged_total"], built.flagged_total)
        assert not _cells_in(document["entries"]) & random_arm, "a random-arm cell is served"

        # The open draw's seats are held out.
        served.open_draw()
        drawn = served.drawn_cells()
        assert drawn, "fixture: nothing drawn"
        document = _queue(served)
        built = service.build_queue(served.run_id, 30, record=False)
        for key in HEADER:
            assert document[key] == getattr(built, key), (key, document[key])
        held = _cells_in(document["entries"]) & (drawn | random_arm)
        assert not held, f"drawn or random-arm cells in the queue: {sorted(held)}"
        assert document["flagged_total"] == len(cells) - len(drawn | random_arm), (
            document["flagged_total"], len(drawn | random_arm))

        # The control for the read-is-a-read arm: a recording build does write shown_at.
        service.build_queue(served.run_id, 30, record=True)
        assert _shown_at_count(served) > shown_before or not document["entries"], (
            "fixture: a recording build wrote no shown_at either, so the read arm proves nothing")


def test_tc_console_117_deterministic_lines_never_reach_the_queue(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-117's deterministic arm, on the validity store (MCQ lines C-01…C-03 beside
    two judged lines whose cells are queued), in the state M-DET writes (`auto`).

    What keeps them out today is the routing filter: `criterion_score` has no evaluation-mode
    column, so the store path's mode gate (`ranking._admitted`) defaults every row to judged
    and a deterministic row routed `queued` WOULD be admitted. M-DET never writes that routing,
    so it is a latent gap, reported in the PR rather than asserted on a state the system
    does not produce."""
    from tests.support.validity_seed import ATOMIC, HOLISTIC, ValidityStore

    world = ValidityStore(tmp_path / "v")
    try:
        administration = world.administer(
            "c-det", {ATOMIC: ("fail", "pass") * 3, HOLISTIC: ("B1", "B2", "B3") * 2})
        with served_validity(world, administration, monkeypatch, network_guard) as served:
            deterministic = {row["criterion_id"] for row in served.rows(
                "SELECT DISTINCT criterion_id FROM criterion_score WHERE run_id = ? AND "
                "criterion_id NOT IN (?, ?)", served.run_id, ATOMIC, HOLISTIC)}
            assert deterministic, "fixture: no deterministic line"
            document = _queue(served)
            served_criteria = {e["criterion_id"] for e in document["entries"]}
            assert served_criteria and served_criteria <= {ATOMIC, HOLISTIC}, served_criteria
            judged = served.rows("SELECT COUNT(*) AS n FROM criterion_score WHERE run_id = ? "
                                 "AND routing IN ('queued', 'provisional')",
                                 served.run_id)[0]["n"]
            built = served.server.app._review_service(served.run_id).build_queue(
                served.run_id, 30, record=False)
            assert document["flagged_total"] == built.flagged_total == judged, (
                document["flagged_total"], built.flagged_total, judged)
            assert not served_criteria & deterministic
    finally:
        world.close()


def _group_of(served: Eng7Console) -> dict:
    document = _queue(served)
    (group,) = [e for e in document["entries"] if e["kind"] == "group"]
    return group


def _run_labels(served: Eng7Console) -> list[dict]:
    return served.rows("SELECT * FROM label WHERE run_id = ?", served.run_id, tier="durable")


def test_tc_console_118_the_group_action_writes_one_label_per_member(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-118: the group at its proposed band -> one `accept` label per member."""
    with eng7_console(tmp_path / "w", tmp_path / "work", monkeypatch, network_guard) as served:
        shape_queue(served)
        refs = served.roster_refs()
        group = _group_of(served)
        assert not _run_labels(served), "fixture: labels before the action"
        outcome = served.dispatched("review group action", run_id=served.run_id,
                                    group_signature=group["group_signature"],
                                    band=group["proposed_band"])
        labels = _run_labels(served)
        members = {refs[m["submission_id"]] for m in group["members"]}
        assert len(labels) == group["size"], f"{len(labels)} labels for {group['size']} members"
        assert sorted(label["student_ref"] for label in labels) == sorted(members)
        assert all(label["criterion_id"] == group["criterion_id"] for label in labels)
        assert all(label["band"] == group["proposed_band"] for label in labels), labels
        assert {label["label_type"] for label in labels} == {"accept"}, (
            [label["label_type"] for label in labels])
        assert f"{group['size']} answers marked {group['proposed_band']}" in outcome["detail"], (
            outcome)
        remaining = _cells_in(_queue(served)["entries"])
        assert not remaining & {(m["submission_id"], group["criterion_id"])
                                for m in group["members"]}, "marked members still queued"


def test_tc_console_118_a_member_changed_since_the_read_is_refused_by_name(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-118 / CT-REVIEW-15: one member escalated between read and action is refused
    by name; every other member gets one `edit` label at the chosen band."""
    with eng7_console(tmp_path / "w", tmp_path / "work", monkeypatch, network_guard) as served:
        shape_queue(served)
        refs = served.roster_refs()
        names = served.names()
        group = _group_of(served)
        other = next(level for level in group["levels"] if level != group["proposed_band"])
        escalated = sorted(m["submission_id"] for m in group["members"])[-1]
        served.execute("UPDATE criterion_score SET judge_count = 3 WHERE run_id = ? AND "
                       "submission_id = ? AND criterion_id = ?", served.run_id, escalated,
                       group["criterion_id"])
        status, outcome = served.action("review group action", run_id=served.run_id,
                                        group_signature=group["group_signature"], band=other)
        assert status == 200, outcome
        labels = _run_labels(served)
        fresh = {refs[m["submission_id"]] for m in group["members"]} - {refs[escalated]}
        assert sorted(label["student_ref"] for label in labels) == sorted(fresh), (
            [label["student_ref"] for label in labels])
        assert all(label["label_type"] == "edit" and label["band"] == other for label in labels), (
            [(label["label_type"], label["band"]) for label in labels])
        detail = outcome["detail"]
        assert names[escalated] in detail and "changed since" in detail, detail
        assert f"{group['size'] - 1} answers marked {other}" in detail, detail
        refusal = detail[detail.index("recorded on its own"):]
        assert not [names[s] for s in names if s != escalated and names[s] in refusal], detail


def test_tc_console_118_skip_writes_nothing_and_the_answer_stays_queued(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-118 / FR-REVIEW-08: `review action` with `decision = 'skip'`."""
    with eng7_console(tmp_path / "w", tmp_path / "work", monkeypatch, network_guard) as served:
        shape_queue(served)
        item = next(e for e in _queue(served)["entries"] if e["kind"] == "item")
        cell = (item["submission_id"], item["criterion_id"])
        outcome = served.dispatched("review action", run_id=served.run_id,
                                    submission_id=cell[0], criterion_id=cell[1],
                                    decision="skip", revision=item["revision"])
        assert "Skipped" in outcome["detail"], outcome
        assert not _run_labels(served), "a skip wrote a label"
        assert served.judged_cells()[cell]["state"] == "provisional_unreviewed"
        built = served.service().build_queue(served.run_id, 30, record=False)
        assert cell in {(str(e.submission_id), str(e.criterion_id)) for e in built.shown
                        if getattr(e, "members", None) is None}, "the skipped answer left the build"
        assert cell in _cells_in(_queue(served)["entries"]), "the skipped answer left the read"
