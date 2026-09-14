"""`TS-81` (issue #154): `Requires` pairwise integration into **`M-REVIEW`**, **`M-GRADE`** and
**`M-CALIB`**. Each test checks one consumer's assumption against the real provider, over a real
store (rung 3).

| Case | Consumer → provider | Assumption checked here |
|---|---|---|
| TC-REQ-53 | `M-GRADE` → `M-REVIEW` | a review action reduces `criteria_provisional` through `criterion_score`, and M-REVIEW writes no grade |
| TC-REQ-55 | `M-REVIEW` → `M-GRADE` | M-GRADE's conservative boundary flag reaches the ranking, so the at-risk item outranks the safe one |
| TC-REQ-59 | `M-STATS` → `M-REVIEW` | labels collected through the real flows carry the columns, and admissibility works from them end to end |
| TC-REQ-60 | `M-STATS` → `M-GRADE` | distributions arrive separated, with nulls (not zeros) on deterministic entropy, and nothing coerces them |
| TC-REQ-77 | `M-CONSOLE` → `M-REVIEW` | the console's blind flow has no query path to system output |
| TC-REQ-78 | `M-CONSOLE` → `M-GRADE` | finalization, provisional export and amendment all complete with the console unimportable |
| TC-REQ-89 | `M-CONSOLE` → `M-CALIB` | every console surface renders with M-CALIB absent or broken, offers no "approve rubric change" control, and names the version calibration arrives in |

`criterion_score` rows are written with `tests/support/grade_vocabulary.write_criterion_scores`,
the disclosed M-AGG stand-in (no `src` module persists M-AGG's score: the TC-REQ-26 finding on #341).

Markers: `contract` and `integration` (§4.7).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.orch  # noqa: E401,F401
import aeh.pkg, aeh.review, aeh.synth  # noqa: E401,F401
from aeh.review import open_review
from aeh.store import open_store
from tests.contract.grade._drive import current_grades, graded_run, set_boundaries
from tests.support.grade_vocabulary import write_criterion_scores
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO = Path(__file__).resolve().parents[3]
OPEN = {"kind": "open", "scoring_model": "atomic"}


def _rows(path: Path, sql: str) -> list[dict]:
    with sqlite3.connect(path) as raw:
        raw.row_factory = sqlite3.Row
        return [dict(r) for r in raw.execute(sql)]


def _cohort_file(data_dir: Path) -> Path:
    return data_dir / "cohorts" / f"{ORCH_COHORT_ID}.sqlite"


def _child_env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO / "src"), str(REPO)])}


def test_tc_req_53_a_review_action_reduces_provisional_through_criterion_score_and_writes_no_grade(
        tmp_data_dir, monkeypatch):
    """`TC-REQ-53` (`M-GRADE` → `M-REVIEW`, CT-REVIEW-06): over a graded run with two provisional
    criterion scores, the teacher edits one through the store-backed review service.

    - **No grade write from review.** Every M-GRADE entry point is made to fail while the action
      runs, and the `submission_grade` rows are identical before and after it.
    - **Through the score row.** M-GRADE's next pass counts the edited criterion as no longer
      provisional: `criteria_provisional` falls from 1 to 0 for S1 and stays 1 for S2 (the
      negative control)."""
    from aeh.grade import GradingService, open_grade

    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = seed_run(store, submissions=("S1", "S2"), criteria=({"criterion_id": "C1", **OPEN},))
        write_criterion_scores(store.cohort(ORCH_COHORT_ID),
                               [("S1", "C1", "B2", 25.0, "provisional"), ("S2", "C1", "B3", 50.0, "provisional")])
        open_grade(store).compute_all(run_id)
    finally:
        store.close()
    grades_before = _rows(_cohort_file(tmp_data_dir), "SELECT * FROM submission_grade ORDER BY submission_id")
    assert [g["criteria_provisional"] for g in grades_before] == [1, 1], f"fixture: {grades_before}"

    service = open_review(tmp_data_dir, run_id=ORCH_COHORT_ID)
    queue = service.build_queue(run_id=ORCH_COHORT_ID, budget_minutes=30)
    target = next(item for item in queue.shown if getattr(item, "score_id", "") == "S1:C1")
    grade_calls: list[str] = []
    for name in ("compute_all", "compute_one", "finalize_batch", "amend"):
        monkeypatch.setattr(GradingService, name, lambda *a, _n=name, **k: grade_calls.append(_n))
    service.act(target, action="edit", new_band="B4", review_seconds=10)
    service.end_session(ORCH_COHORT_ID)
    service.close()
    monkeypatch.undo()
    assert not grade_calls, f"M-REVIEW called M-GRADE's {grade_calls}"
    assert _rows(_cohort_file(tmp_data_dir), "SELECT * FROM submission_grade ORDER BY submission_id") == grades_before, (
        "the review action changed submission_grade: a grade write originated in M-REVIEW")

    scores = {r["submission_id"]: r for r in _rows(_cohort_file(tmp_data_dir), "SELECT * FROM criterion_score")}
    store = open_store(tmp_data_dir)
    try:
        open_grade(store).compute_all(run_id)
        after = {g["submission_id"]: g for g in current_grades(store.cohort(ORCH_COHORT_ID), run_id)}
    finally:
        store.close()
    assert after["S2"]["criteria_provisional"] == 1, "control: the untouched submission changed"
    assert after["S1"]["criteria_provisional"] == 0, (
        f"after the teacher's edit, M-GRADE still counts S1's criterion as provisional "
        f"(criteria_provisional={after['S1']['criteria_provisional']}, criteria_reviewed="
        f"{after['S1']['criteria_reviewed']}); the stored score row reads state="
        f"{scores['S1']['state']!r}, band={scores['S1']['band']!r}. [When written: ReviewService.act "
        f"records a 'criterion_score' entry in its write audit and persists the label, but never "
        f"updates the criterion_score row, so the reduction the audit claims never reaches M-GRADE.]")


def test_tc_req_55_grade_boundary_risk_reaches_the_review_ranking(tmp_data_dir):
    """`TC-REQ-55` (`M-REVIEW` → `M-GRADE`, CT-GRADE-05/19): two submissions each carry one
    provisional criterion with the same declared span [0, 1] and equal weight; only their auto
    totals differ. M-GRADE flags S-NEAR (range 6.5–7.5 spans the 7.0 floor) and not S-FAR
    (1.0–2.0). The flag is conservative, so ranking may over-include but must not under-include:
    the store-backed queue shows the at-risk item and ranks it strictly above the safe one."""
    from aeh.pkg import PackageCatalog

    store = open_store(tmp_data_dir)
    try:
        world = graded_run(store, submissions=("S-NEAR", "S-FAR"),
                           criteria=({"criterion_id": "C1", **OPEN}, {"criterion_id": "C2", **OPEN}),
                           rows=(("S-NEAR", "C1", "B2", 6.5, "auto"), ("S-NEAR", "C2", "SP0", 0.2, "provisional"),
                                 ("S-FAR", "C1", "B2", 1.0, "auto"), ("S-FAR", "C2", "SP1", 0.2, "provisional")),
                           compute=False)
        set_boundaries(store, world.version, (("B", 7.0), ("A", 9.5)))
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        for ordinal, points in enumerate((0.0, 1.0)):
            catalog.add_band(world.version, "C2", ordinal, f"SP{ordinal}", points)
        world.service.compute_all(world.run_id)
        grades = {g["submission_id"]: g for g in current_grades(world.cohort, world.run_id)}
    finally:
        store.close()
    assert (grades["S-NEAR"]["boundary_at_risk"], grades["S-FAR"]["boundary_at_risk"]) == (1, 0), (
        f"fixture: M-GRADE must flag S-NEAR only: {grades}")
    assert grades["S-NEAR"]["score_low"] <= grades["S-NEAR"]["total"] <= grades["S-NEAR"]["score_high"]

    service = open_review(tmp_data_dir, run_id=ORCH_COHORT_ID)
    try:
        queue = service.build_queue(run_id=ORCH_COHORT_ID, budget_minutes=30)
    finally:
        service.close()
    values = {item.score_id: item.expected_value for item in queue.shown if hasattr(item, "score_id")}
    assert "S-NEAR:C2" in values, f"the at-risk item was left out of the queue: {values}"
    assert values["S-NEAR:C2"] > values.get("S-FAR:C2", float("-inf")), (
        f"the queue ranks the grade M-GRADE flagged at risk no higher than the safe one: {values}. "
        f"[When written: impact is criterion_weight x boundary proximity (review.py ~1050). The "
        f"store-backed row reads both criterion_weight and grade_boundary_delta from the criterion_score "
        f"mapping, which carries neither column, so weight reads as 0 and every stored item's expected "
        f"value is 0.0. No src code maps submission_grade's boundary_at_risk/score_low/score_high, or the "
        f"package's criterion weight, into the row; wiring only the delta leaves this red.]")


def test_tc_req_59_labels_from_the_real_flows_carry_the_columns_admissibility_reads(tmp_data_dir):
    """`TC-REQ-59` (`M-STATS` → `M-REVIEW`, CT-REVIEW-07/08/09/11/13): one store-backed review
    session over six provisional judged scores takes a group action (three members), accepts one
    item, then draws and submits the blind sample over what remains.

    - Every stored label carries `label_type`, `saw_system_output` and `evaluation_mode`.
    - The group action wrote one label per member.
    - Queue actions carry `saw_system_output = 1`; blind labels carry 0.
    - M-STATS, opened over the same directory, admits exactly the blind labels.
    - Both bands are on every label, so the admitted population supports an agreement figure."""
    from aeh.stats import AgreementFigure, open_stats

    store = open_store(tmp_data_dir)
    try:
        subs = tuple(f"S{i:02d}" for i in range(6))
        seed_run(store, submissions=subs, criteria=({"criterion_id": "C1", **OPEN},))
        write_criterion_scores(store.cohort(ORCH_COHORT_ID),
                               [(s, "C1", "B2", 25.0, "provisional") for s in subs[:3]]
                               + [(s, "C1", b, 0.0, "provisional") for s, b in zip(subs[3:], ("B1", "B3", "B5"))])
    finally:
        store.close()
    service = open_review(tmp_data_dir, run_id=ORCH_COHORT_ID, seed=7)
    try:
        queue = service.build_queue(run_id=ORCH_COHORT_ID, budget_minutes=60)
        (group,) = [entry for entry in queue.shown if not hasattr(entry, "score_id")]
        group_ids = service.act_on_group(group, band="B4")
        service.act(next(e for e in queue.shown if hasattr(e, "score_id")), action="accept")
        session = service.blind_sample(run_id=ORCH_COHORT_ID, n=15)
        blind_ids = service.submit_blind(session.session_id, {item: "B3" for item in session.items})
    finally:
        service.close()

    labels = _rows(tmp_data_dir / "durable.sqlite", "SELECT * FROM label")
    assert len(group_ids) == len(group.members) == 3, "a group action is not one label per member"
    assert len(blind_ids) >= 2, f"fixture: the blind draw needs two refs, got {blind_ids}"
    assert len(labels) == len(group_ids) + 1 + len(blind_ids), f"stored labels: {labels}"
    for row in labels:
        assert row["label_type"] and row["evaluation_mode"] == "judged", row
        assert row["saw_system_output"] == (0 if row["label_type"] == "blind" else 1), row
    admitted = open_stats(data_dir=tmp_data_dir).admissible_labels()
    assert sorted(label.label_id for label in admitted) == sorted(blind_ids), (
        "M-STATS' admissible set is not exactly the blind labels")

    one_sided = [r["label_id"] for r in labels if r["system_band"] is None or r["teacher_band"] is None]
    figure = open_stats(data_dir=tmp_data_dir).agreement(criterion_id="C1")
    problems = []
    if one_sided:
        problems.append(f"labels {one_sided} were stored without both bands")
    if not isinstance(figure, AgreementFigure):
        problems.append(f"the admitted blind population yields {figure!r}, not an agreement figure")
    assert not problems, (
        f"{'; '.join(problems)}. Labels {one_sided} were stored without both bands, so the admitted blind population "
        f"yields {figure!r} instead of an agreement figure (CT-REVIEW-07: every label carries both "
        f"system_band and teacher_band). [When written: submit_blind writes system_band = NULL on "
        f"every blind label and nothing joins the score's band in after submission, so M-STATS' "
        f"pairing drops every admissible label and the real flows can never produce a figure.]")


def _blind(i, system, teacher):
    return SimpleNamespace(label_id=f"L{i}", criterion_id="C1", label_type="blind", saw_system_output=0,
                           evaluation_mode="judged", system_band=system, teacher_band=teacher, band=teacher)


def test_tc_req_60_distributions_arrive_separated_with_nulls_that_nothing_coerces(tmp_data_dir):
    """`TC-REQ-60` (`M-STATS` → `M-GRADE`, CT-GRADE-12/13): over a graded run with one judged
    criterion (every score in one band, a genuine entropy of 0.0) and one deterministic criterion,
    M-GRADE's separated rollup puts each in its own block. The deterministic entropy and interior
    rate arrive as `None` and the judged entropy as `0.0`; serialized, the two stay `null` and
    `0.0`. M-STATS' own shape figures keep the same distinction.

    Disclosed gap: `aeh.stats` has no read of M-GRADE's distributions today, so the "M-STATS never
    coerces" half is checked on the shape figure it does compute (`compression_check`)."""
    from aeh.grade import separated_rollup
    from aeh.stats import ValidationStats

    store = open_store(tmp_data_dir)
    try:
        world = graded_run(store, submissions=("S-A", "S-B"),
                           criteria=({"criterion_id": "C-J", **OPEN},
                                     {"criterion_id": "C-D", "kind": "mcq", "scoring_model": "atomic"}),
                           rows=(("S-A", "C-J", "B1", 6.0, "auto"), ("S-B", "C-J", "B1", 6.0, "auto"),
                                 ("S-A", "C-D", "correct", 4.0, "auto"), ("S-B", "C-D", "incorrect", 1.0, "auto")))
        rollup = separated_rollup(world.run_id, store)
    finally:
        store.close()
    judged = {f.criterion_id: f for f in rollup.judged.criteria}
    deterministic = {f.criterion_id: f for f in rollup.deterministic.criteria}
    assert set(judged) == {"C-J"} and set(deterministic) == {"C-D"}, "the rollup did not separate the kinds"
    assert deterministic["C-D"].entropy is None and deterministic["C-D"].interior_rate is None, (
        f"the deterministic criterion's figures arrived coerced: {deterministic['C-D']}")
    assert judged["C-J"].entropy == 0.0 and judged["C-J"].entropy is not None, judged["C-J"]
    wire = json.loads(json.dumps({"j": judged["C-J"].entropy, "d": deterministic["C-D"].entropy}))
    assert wire == {"j": 0.0, "d": None}, f"serialization coerced the figures: {wire}"

    measured = ValidationStats([_blind(i, 2, 2) for i in range(4)]).compression_check()
    empty = ValidationStats([]).compression_check()
    assert measured.gold.band_entropy == 0.0 and empty.gold.band_entropy is None, (
        f"M-STATS coerced a null or a zero: measured={measured.gold.band_entropy!r}, "
        f"empty={empty.gold.band_entropy!r}")


def test_tc_req_77_the_console_blind_flow_has_no_query_path_to_system_output(tmp_data_dir, monkeypatch):
    """`TC-REQ-77` (`M-CONSOLE` → `M-REVIEW`, CT-REVIEW-01/04/09/12): the store holds provisional
    scores in bands B4 and B2.

    - Every SQL statement run while the console renders its blind screen (S11) is captured through
      a `sqlite3.connect` spy, and none reaches `criterion_score`, a verdict or a narrative.
    - The rendered page carries no system band.
    - The console's declared blind-flow plan names no system-output table.
    - M-REVIEW's blind session reads `submission` and `criterion` only and holds no band.

    Positive control: the same spy, around M-REVIEW's queue build over the same store, does capture
    a `criterion_score` read. The blind session is drawn before the console renders, so the screen
    is rendered with a live draw.

    Disclosed: the console's S11 renders fixed text today and lists none of the drawn refs, so the
    SQL and band checks on it hold because it reads nothing. The load-bearing checks are the
    declared flow plan and M-REVIEW's session boundary. CT-REVIEW-01/04 (the queue is
    minute-budgeted and states its residual) are not asserted here: the console's S9 header reads
    "Flagged for review: 0" over a store with two provisional scores, so it does not render
    M-REVIEW's figures at all. That is recorded as a finding in the PR."""
    from aeh.console import SCREENS, blind_flow, build_console

    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = seed_run(store, submissions=("S01", "S02"), criteria=({"criterion_id": "C1", **OPEN},))
        write_criterion_scores(store.cohort(ORCH_COHORT_ID),
                               [("S01", "C1", "B4", 75.0, "provisional"), ("S02", "C1", "B2", 25.0, "provisional")])
    finally:
        store.close()

    seen: list[str] = []
    real_connect = sqlite3.connect

    def spying_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connection.set_trace_callback(seen.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", spying_connect)
    forbidden = ("criterion_score", "verdict", "narrative", "submission_grade", "review_queue")

    control = open_review(tmp_data_dir, run_id=ORCH_COHORT_ID)
    control.build_queue(run_id=ORCH_COHORT_ID, budget_minutes=30)
    control.close()
    assert any("criterion_score" in s.lower() for s in seen), "control: the spy captured no score read"

    review = open_review(tmp_data_dir, run_id=ORCH_COHORT_ID, seed=3)
    session = review.blind_sample(run_id=ORCH_COHORT_ID, n=15)
    seen.clear()
    store = open_store(tmp_data_dir)
    try:
        pages = [build_console(store=store).render(SCREENS["S11"], id=ident).html
                 for ident in (run_id, ORCH_COHORT_ID)]
    finally:
        store.close()
    reached = sorted({token for s in seen for token in forbidden if token in s.lower()})
    assert not reached, f"rendering the blind screen ran statements reaching {reached}"
    for page in pages:
        assert not re.search(r"\bB[245]\b", page), "the blind screen carries a system band"
    plan = blind_flow(run_id=run_id, submission_ref="S01")
    assert plan.queries and not any(t in str(q).lower() for q in plan.queries for t in forbidden), plan.queries
    review.close()
    assert session.items, "fixture: the blind draw is empty"
    assert session.readable_tables() == frozenset({"submission", "criterion"})
    assert not re.search(r"\bB[245]\b", json.dumps(session.available_data(), default=str))


_FINALIZE_WITHOUT_CONSOLE = textwrap.dedent("""
    import json, sys
    sys.modules["aeh.console"] = None  # the console is killed: any import of it raises
    import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.orch
    import aeh.pkg, aeh.review, aeh.synth
    from pathlib import Path
    from aeh.store import open_store
    from tests.contract.grade._drive import complete_run, current_grades, graded_run, grade_revision, set_boundaries
    data_dir = Path(sys.argv[1])
    store = open_store(data_dir)
    try:
        crit = ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},)
        world = graded_run(store, submissions=("S-DONE", "S-PROV"), criteria=crit,
                           rows=(("S-DONE", "C1", "B2", 7.0, "auto"), ("S-PROV", "C1", "B3", 5.0, "provisional")),
                           compute=False)
        set_boundaries(store, world.version, (("B", 5.0), ("A", 8.0)))
        world.service.compute_all(world.run_id)
        export = world.service.export(world.run_id, 1, "csv")
        complete_run(world.cohort, world.run_id)
        world.service.compute_all(world.run_id)
        states = {g["submission_id"]: [g["state"], g["finalized_at"] is not None]
                  for g in current_grades(world.cohort, world.run_id)}
        world.service.amend(world.run_id, "S-DONE", {"C1": 8.0}, actor="teacher", reason="re-read")
        revisions = [grade_revision(world.cohort, world.run_id, "S-DONE", n) is not None for n in (1, 2)]
    finally:
        store.close()
    # CONTROL-HOOK
    print(json.dumps({"states": states, "export": Path(export).read_text(encoding="utf-8"),
                      "revisions": revisions,
                      "console_loaded": sys.modules.get("aeh.console") is not None}))
""")


def test_tc_req_78_grades_finalize_export_and_amend_with_the_console_killed(tmp_path, monkeypatch):
    """`TC-REQ-78` (`M-CONSOLE` → `M-GRADE`, CT-GRADE-04/06/09/10): in a child process where
    `aeh.console` cannot be imported, a graded run is exported while one grade is still
    provisional, then completed and re-graded, then amended.

    - The CSV carries the provisional row.
    - On completion, the fully-auto grade finalizes with no teacher and no console.
    - The amendment lands as revision 2 beside revision 1.
    - The console never loads.

    Negative control: the same child script, with an `import aeh.console` added, fails, which
    proves the import block is live."""
    monkeypatch.setenv("HARNESS_GRADE_EXPORT_DIR", str(tmp_path / "exports"))

    def run(script: str, data_dir: Path):
        data_dir.mkdir()
        return subprocess.run([sys.executable, "-c", script, str(data_dir)], cwd=REPO, env=_child_env(),
                              capture_output=True, text=True, timeout=300)

    killed = run(_FINALIZE_WITHOUT_CONSOLE.replace("# CONTROL-HOOK", "import aeh.console"), tmp_path / "control")
    assert killed.returncode != 0 and "aeh.console" in killed.stderr, (
        f"control: importing the killed console did not fail: {killed.stderr[-600:]}")

    result = run(_FINALIZE_WITHOUT_CONSOLE, tmp_path / "data")
    assert result.returncode == 0, f"grading failed with the console killed:\n{result.stderr[-2000:]}"
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["console_loaded"] is False
    assert "S-PROV" in out["export"] and "provisional" in out["export"], out["export"]
    assert out["states"]["S-DONE"] == ["final", True], f"no finalization without the console: {out['states']}"
    assert out["revisions"] == [True, True], f"the amendment did not write a revision: {out['revisions']}"


_RENDER_WITHOUT_CALIB = textwrap.dedent("""
    import json, sys
    data_dir, mode = sys.argv[1], sys.argv[2]
    if mode in ("absent", "control"):
        sys.modules["aeh.calib"] = None
    else:
        import aeh.calib
        def _broken(*a, **k):
            raise RuntimeError("M-CALIB disabled")
        for name in list(vars(aeh.calib)):
            value = getattr(aeh.calib, name)
            if not name.startswith("_") and callable(value) and getattr(value, "__module__", "") == "aeh.calib":
                setattr(aeh.calib, name, _broken)
    import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.orch
    import aeh.pkg, aeh.review, aeh.synth
    if mode == "control":
        import aeh.calib  # proves the block is live: this must raise
    from pathlib import Path
    from aeh.store import open_store
    from tests.support.orch_run import seed_run
    store = open_store(Path(data_dir))
    try:
        _, run_id, version = seed_run(store, submissions=("S01",),
                                      criteria=({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},))
        from aeh.console import CALIBRATION_ARRIVES_IN, SCREENS, build_console, touchpoint_surface
        console = build_console(store=store)
        pages = {name: console.render(route, id=run_id, ref="S01", version=version).html
                 for name, route in SCREENS.items()}
        touch = {k: [v.present, v.available, v.available_in_version] for k, v in touchpoint_surface().items()}
    finally:
        store.close()
    print(json.dumps({"pages": pages, "arrives": CALIBRATION_ARRIVES_IN, "touch": touch}))
""")


@pytest.mark.parametrize("mode", ["absent", "disabled"])
def test_tc_req_89_the_console_works_without_calibration_and_offers_no_rubric_change_approval(tmp_path, mode):
    """`TC-REQ-89` (`M-CONSOLE` → `M-CALIB`, CT-CALIB-01/05/15, CT-CONSOLE-17): in a child process
    where `aeh.calib` is either unimportable (`absent`) or imported with every public callable
    replaced by one that raises (`disabled`), all fourteen console screens render over a seeded
    store.

    - No page offers an approve control for a rubric or prompt change, edit or revision. The
      M-SETUP read-back approval ("Approve how the rubric was understood") is a different
      affordance and is allowed.
    - The elicitation touchpoint is present, unavailable, and names the version it arrives in,
      and S5 renders that version.
    - M-CALIB's own elicitation value has no edit field to approve.

    Negative control: the child script with `import aeh.calib` added under the block fails.

    Disclosed: no module in `src/aeh` imports `aeh.calib` today, so both modes hold by
    construction; the test keeps it that way. `aeh.calib` declares no phase constant, so the version named is the console's own
    `CALIBRATION_ARRIVES_IN`, not one read from M-CALIB."""
    import dataclasses

    from aeh.calib import ElicitationQuestion

    def child(run_mode):
        target = tmp_path / run_mode
        target.mkdir()
        return subprocess.run([sys.executable, "-c", _RENDER_WITHOUT_CALIB, str(target), run_mode], cwd=REPO,
                              env=_child_env(), capture_output=True, text=True, timeout=300)

    if mode == "absent":
        control = child("control")
        assert control.returncode != 0 and "aeh.calib" in control.stderr, (
            f"control: importing the blocked M-CALIB did not fail: {control.stderr[-600:]}")
    result = child(mode)
    assert result.returncode == 0, f"the console failed with M-CALIB {mode}:\n{result.stderr[-2000:]}"
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert len(out["pages"]) == 14 and all("<h1>" in html for html in out["pages"].values())
    verb = r"(approve|accept|apply|confirm)"
    change = r"(rubric|prompt)s?\b[^<]{0,30}\b(change|edit|revision)s?|suggested (rubric|prompt)"
    near = re.compile(rf"\b{verb}\b[^<]{{0,80}}\b({change})|\b({change})[^<]{{0,80}}\b{verb}\b", re.I)
    control_html = ["<button>Approve this rubric change</button>", "<p>Accept this prompt revision</p>",
                    "<a>Apply suggested rubric edit</a>", "<p>Rubric change proposed: approve?</p>"]
    assert all(near.search(html) for html in control_html), "control: the pattern misses a known offender"
    assert not near.search("<h2>Approve how the rubric was understood</h2>"), "control: M-SETUP's read-back matched"
    controls = re.compile(r"<(button|input|form)\b[^>]*>[^<]*", re.I)
    offenders = {name: m.group(0) for name, html in out["pages"].items() if (m := near.search(html))}
    offenders.update({f"{name} control": c.group(0) for name, html in out["pages"].items()
                      for c in controls.finditer(html) if re.search(verb, c.group(0), re.I)})
    assert not offenders, f"a console surface offers a rubric-change approval: {offenders}"
    elicitation = [v for k, v in out["touch"].items() if "elicitation" in k.lower()]
    assert elicitation == [[True, False, out["arrives"]]], f"elicitation touchpoint: {out['touch']}"
    assert re.search(r"version \d", out["arrives"]), out["arrives"]
    assert "version 2" in out["arrives"] and "version 2" in out["pages"]["S5"] and "Phase 4" in out["pages"]["S5"], (
        f"S5 does not name the version calibration arrives in ({out['arrives']!r})")
    fields = {f.name for f in dataclasses.fields(ElicitationQuestion)}
    assert not {"proposed_edit", "edit", "diff", "patch"} & fields, fields
