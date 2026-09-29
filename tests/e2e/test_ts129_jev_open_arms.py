"""TS-129 (#540): the three Jev journey arms #470 left unwritten (closeout test plan T4).

| Case | Arm added |
|---|---|
| TC-E2E-05 | Over F-JEV-SYNTH (engine on, base panel of one): every escalated cell's stored `agreement` equals ordinal α hand-computed from its verdicts on the declared scale, and its `confidence` equals the design formula applied by hand to the row's own flags; the accepted decision verdicts' gate confidences are the ones the engine returned; the review queue's flagged total is the number of routed cells |
| ADV-15 | The blind sample over an engine-on run can draw a decision-seat cell, and what the blind flow holds or renders carries no decision band and no decision confidence |
| SEC-19 | A unit carrying the student's roster name ("Zelda Quartermaine"), whose script also carries that name, is assembled into a request with the name replaced by the `student_ref`; no log record carries it |

**SEC-19 is red: two defects, owned by no issue yet (they need issues from /plan-to-issues).**
(1) Even when the unit carries the student's roster name, `judge.assemble` replaces it in the
transcript only: the extracted EVIDENCE SPANS the request carries keep it, so the name reaches the
scoring and decide requests. (2) In the shipped system M-ORCH enumerates every unit with `student_name = None` ("the ledger holds neither")
and no tier stores a roster display name, so the boundary never receives a name to replace: a name a
student writes on the script reaches the decide requests and the judge prompts (measured: 6 of 6 and
48 of 54 on F-DEV-PIPE with a signed answer). That missing roster-name plumbing is the second defect. The arm
feeds the boundary the roster name the design says it receives, so a design-conformant fix of both
turns it green; it does not ask for free-text redaction of names the roster does not hold, which
`judge.py` §3.2 rejects.
"""

from __future__ import annotations

import logging
from itertools import combinations
from pathlib import Path

import pytest

from harness.corpora import dev_pipe
from tests.support import pipe_world

pytestmark = [pytest.mark.e2e, pytest.mark.integration]

#: The design's confidence caps (detailed design, M-AGG "The confidence computation").
_CAPS = (("spans_verified", False, 0.25), ("evidence_present", False, 0.25),
         ("sufficiency_flag", True, 0.25), ("ocr_overlap_risk", True, 0.30),
         ("described_evidence", True, 0.50), ("extractor_disagreement", True, 0.40))


def _hand_alpha(ordinals: list[int], k: int) -> float:
    """The module's documented convention, computed independently: 1 - D_o / D_e."""
    pairs = list(combinations(ordinals, 2))
    d_o = sum(abs(a - b) for a, b in pairs) / len(pairs) / (k - 1)
    scale = list(combinations(range(k), 2))
    d_e = sum(abs(a - b) for a, b in scale) / len(scale) / (k - 1)
    return 1 - d_o / d_e


def _hand_confidence(base: float, row: dict, holistic: bool, uncited: bool) -> float:
    value = base * (0.85 if holistic else 1.0) * (0.80 if uncited else 1.0)
    for column, adverse, cap in _CAPS:
        flag = row.get(column)
        # A recorded NULL is "not measured", and M-AGG fails closed on it (the signal reads
        # adverse): the design's caps are the inversion, and an unmeasured check cannot lift one.
        if flag is None or bool(flag) is adverse:
            value = min(value, cap)
    return value


@pytest.fixture(scope="module")
def jev_synth(tmp_path_factory):
    root = tmp_path_factory.mktemp("ts129") / "w"
    mp = pytest.MonkeyPatch()
    world = pipe_world.jev_synth_replay_world(root, monkeypatch=mp)
    decisions: list[object] = []
    inner = world.provider.decide

    def decide(request, model_ref):
        decision = inner(request, model_ref)
        decisions.append(decision)
        return decision

    def distinct(decision):
        """Every score answer's gate confidence made unique (still above any gate), so the
        stored verdicts can only match if each carries ITS decision's value."""
        import dataclasses

        from aeh.prov import ScoreAnswer

        answers = {}
        for key, answer in decision.answers.items():
            if isinstance(answer, ScoreAnswer):
                assigned.append(round(0.951 + 0.0001 * len(assigned), 4))
                answer = dataclasses.replace(answer, confidence=assigned[-1])
            answers[key] = answer
        return dataclasses.replace(decision, answers=answers)

    assigned: list[float] = []
    world.assigned_confidences = assigned
    world.provider.decide = lambda request, model_ref: distinct(decide(request, model_ref))
    try:
        world.build_run()
        world.start_run()
        result = pipe_world.drive_composed(world)
    finally:
        mp.undo()  # the world's env knobs are needed for the drive only (TC-REG-10)
    yield world, result, decisions, root
    world.store.close()


def test_tc_e2e_05_alpha_and_confidence_are_the_hand_computed_values(jev_synth):
    from aeh.pkg import PackageCatalog

    world, result, _d, _root = jev_synth
    assert result.status == "complete", result.pause_reason
    handle = world.handle
    catalog = PackageCatalog(world.store.package(world.package_id), package_id=world.package_id)
    criteria = {str(r["criterion_id"]): r for r in catalog.criteria(world.version)}
    rows = [dict(r) for r in handle.query(
        "SELECT * FROM criterion_score WHERE run_id = :r AND judge_count >= 3", r=world.run_id)]
    assert rows, "fixture: no escalated cell"
    for row in rows:
        verdicts = handle.query(
            "SELECT v.band_ordinal, v.uncited, v.scoring_engine FROM verdict v JOIN work_unit u ON "
            "u.work_id = v.work_id WHERE u.run_id = :r AND u.submission_id = :s AND u.criterion_id = :c",
            r=world.run_id, s=row["submission_id"], c=row["criterion_id"])
        assert len(verdicts) == row["judge_count"] == 3, (row, [tuple(v) for v in verdicts])
        assert sorted(v["scoring_engine"] for v in verdicts) == ["decision", "llm", "llm"]
        k = len(catalog.bands(row["criterion_id"]))
        alpha = _hand_alpha([int(v["band_ordinal"]) for v in verdicts], k)
        assert row["agreement"] == pytest.approx(alpha), (row["submission_id"], row["agreement"], alpha)
        holistic = str(criteria[row["criterion_id"]]["scoring_model"]) == "holistic"
        uncited = any(bool(v["uncited"]) for v in verdicts)
        expected = _hand_confidence(alpha, row, holistic, uncited)
        assert row["confidence"] == pytest.approx(expected), (row, expected)


def test_tc_e2e_05_the_gate_confidences_are_the_engines(jev_synth):
    world, _result, decisions, _root = jev_synth
    stored = sorted(float(r[0]) for r in world.handle.query(
        "SELECT self_confidence FROM verdict WHERE scoring_engine = 'decision'"))
    assigned = world.assigned_confidences
    assert stored and len(set(assigned)) == len(assigned), "fixture: no distinct confidences assigned"
    assert len(set(stored)) == len(stored), f"two verdicts carry one gate confidence: {stored}"
    assert set(stored) <= set(assigned), (
        f"accepted verdicts carry gate confidences {sorted(set(stored) - set(assigned))} the engine "
        "never returned")


def test_tc_e2e_05_the_review_queue_holds_every_routed_cell(jev_synth):
    from aeh import review

    world, _result, _d, root = jev_synth
    routed = int(world.handle.query(
        "SELECT COUNT(*) FROM criterion_score WHERE run_id = :r AND routing != 'auto'",
        r=world.run_id)[0][0])
    service = review.open_review(root, run_id=world.run_id)
    try:
        queue = service.build_queue(run_id=world.run_id, budget_minutes=600)
    finally:
        service.close()
    assert routed > 0, "fixture: nothing was routed to review"
    assert queue.flagged_total == routed, (queue.flagged_total, routed)


# --- ADV-15 ---------------------------------------------------------------------------------


def test_adv_15_the_blind_sample_never_shows_a_decision_band_or_confidence(jev_synth):
    from aeh import review

    world, _result, _d, root = jev_synth
    seats = {(r[0], r[1]) for r in world.handle.query(
        "SELECT u.submission_id, u.criterion_id FROM verdict v JOIN work_unit u ON u.work_id = v.work_id "
        "WHERE v.scoring_engine = 'decision'")}
    confidences = {f"{float(r[0]):g}" for r in world.handle.query(
        "SELECT DISTINCT self_confidence FROM verdict WHERE scoring_engine = 'decision'")}
    service = review.open_review(root, run_id=world.run_id)
    try:
        session = service.blind_sample(world.run_id, n=25)  # FR-REVIEW-12's ceiling
        html = service.render_blind_flow(session.session_id)
        data = repr(session.available_data())
    finally:
        service.close()
    drawn = {(i.submission_id, i.criterion_id) for i in session.items}
    assert drawn & seats, "the blind sample could not draw a decision-seat cell"
    for text in (html, data):
        for token in ("scoring_engine", "decision engine", "openrouter-jev", "self_confidence"):
            assert token not in text.lower(), f"the blind flow carries {token!r}"
        for value in confidences:
            assert value not in text and f"{float(value) * 100:g}%" not in text, (
                f"the blind flow carries a decision confidence {value}")
    import re as _re

    keys = set(_re.findall(r"'([a-z_]+)':", data))
    assert not keys & {"band", "system_band", "proposed_band", "decision_band", "self_confidence",
                       "confidence", "scoring_engine"}, f"the blind session holds system output: {keys}"
    assert not _re.search(r"\b(selected|checked)\b", html), "the blind flow pre-selects a band"


# --- SEC-19 ---------------------------------------------------------------------------------

NAME = "Zelda Quartermaine"


def test_sec_19_a_units_roster_name_never_reaches_the_request(tmp_path, monkeypatch, caplog):
    from types import SimpleNamespace

    from aeh import judge

    real_render = dev_pipe.render_band
    monkeypatch.setattr(dev_pipe, "render_band",
                        lambda cid, o: real_render(cid, o) + (f" Signed, {NAME}." if cid == "C1" else ""))
    caplog.set_level(logging.DEBUG)
    root = tmp_path / "w"
    for sub in ("packages", "cohorts", "blobs"):
        (root / sub).mkdir(parents=True)
    (tmp_path / "fx").mkdir()
    world = pipe_world.PipeWorld(root, tmp_path / "fx", record_as_you_go=True, decision_engine=True,
                                 monkeypatch=monkeypatch)
    try:
        world.build_run()
        world.start_run()
        pipe_world.drive_composed(world)
        row = world.handle.query(
            "SELECT w.work_id, w.run_id, w.stage, w.submission_id, w.criterion_id, w.judge_id, "
            "s.student_ref FROM work_unit w JOIN submission s ON s.submission_id = w.submission_id "
            "WHERE w.stage = 'score' AND w.criterion_id = 'C1' LIMIT 1")[0]
        unit = SimpleNamespace(work_id=row["work_id"], run_id=row["run_id"], stage="score",
                               student_ref=row["student_ref"], student_name=NAME,
                               submission_id=row["submission_id"], criterion_id="C1",
                               submission_text=None, judge=row["judge_id"], attempt=0)
        stored = [str(r[0]) for r in world.handle.query("SELECT markdown FROM document")]
        request = judge.assemble(unit, store=world.store)
    finally:
        world.store.close()
    assert any(NAME in m for m in stored), "fixture: the name never reached the stored script"
    text = repr(request)
    assert NAME not in text, "the unit's roster name reached the assembled request (NFR-PROV-08)"
    assert row["student_ref"] in text, "the request does not carry the student_ref in the name's place"
    assert NAME not in caplog.text, "the student's name reached a log record"
