"""`TS-48` (issue #129) — screen S12 over a real run: the answer-key correction control and
the rubric-findings block.

Test plan §5.19, `TC-CONSOLE-30` and `TC-CONSOLE-31`, Integration / rung 3.

Neither case has a clause-suite sibling that reaches a store: S12's correction and findings
halves only exist on the real-store path (`_correct_answer_key`, `_render_rubric_findings`
both return early without a `data_dir`). So the world here is the whole chain —
`PackageCatalog` → `Orchestrator` (enumerated) → `DeterministicEvaluator` →
`GradingService` — and every oracle is read from the ledger those modules wrote, never from
the console's `detail` string, which is a claim the console makes about itself.

**Written ahead of implementation.** The issue says `yes`; stale — `M-CONSOLE` landed
(#127 built S12), so both cases are expected to pass.
"""

from __future__ import annotations

import html as html_lib
import json
import re

import pytest

from aeh.console import build_console
from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.support.console_world import rows, seed_scored_run

pytestmark = [pytest.mark.integration]

#: Submission i's option per multiple-choice criterion (C-01, C-02, C-03). C-02's stored key is
#: B; the correction below re-keys it to D, so the expected re-derivation is a pure lookup:
#: sub-01 (B) 1 → 0, sub-02 (D) 0 → 1, sub-03 (B) 1 → 0. Sub-03's C-03 is an ambiguous mark.
_CHOICES = (("A", "B", "C"), ("A", "D", "C"), ("B", "B", None))
_CORRECTED_KEY = "D"


def _ledger_units(cohort, run_id):
    return rows(
        cohort,
        "SELECT work_id, stage, criterion_id, judge_id, status, attempts, origin FROM work_unit "
        "WHERE run_id = :run_id ORDER BY work_id",
        run_id=run_id,
    )


def test_tc_console_30_an_answer_key_correction_rederives_by_lookup_and_enqueues_no_judgment(
    tmp_data_dir,
):
    """`TC-CONSOLE-30` / `FR-CONSOLE-30` — S12's correction control, end to end.

    The run is **enumerated**, so the ledger already holds the judged criteria's extract and
    score units — without them "enqueues no panel judgment" would be a count of zero over a
    ledger that could never have held one. Exact-value oracles, all from the store:

    1. a new key version: the package gains exactly one version, parented on the run's, whose
       C-02 key is D — and the parent's key is still B (the old version is not edited);
    2. deterministic scores re-derived by lookup: C-02's band per submission is exactly what
       the corrected key predicts, and C-01/C-03 are untouched;
    3. the grade policy re-ran: each submission gains a current revision 2 whose total is the
       re-derived sum (2.0, 3.0, 0.0), revision 1 retained and superseded;
    4. **enqueue count zero**: the run's `work_unit` rows are identical before and after — no
       new unit, no status moved, no escalation origin — and the run now points at the
       corrected version.
    """
    store = open_store(tmp_data_dir)
    try:
        world = seed_scored_run(store, choices=_CHOICES, with_open_criteria=True,
                                enumerate_units=True)
        cohort = store.cohort(world.cohort_id)
        package = store.package(world.package_id)
        units_before = _ledger_units(cohort, world.run_id)
        judged_units = [u for u in units_before if u["stage"] in ("extract", "score")]
        assert judged_units, (
            "fixture: the enumerated ledger holds no judged unit, so the zero-enqueue oracle "
            "below would count over a ledger that could never have held one"
        )
        scores_before = {
            (r["submission_id"], r["criterion_id"]): r["band"]
            for r in rows(cohort, "SELECT submission_id, criterion_id, band FROM criterion_score")
        }
        assert [scores_before[(s, "C-02")] for s in world.submissions] == [
            "correct", "incorrect", "correct"
        ], f"fixture: C-02 under key B, got {scores_before!r}"

        outcome = build_console(store=store).perform(
            "correct an answer key after a run", run_id=world.run_id, criterion_id="C-02",
            answer_key=_CORRECTED_KEY,
        )
        assert outcome.dispatched, f"the correction did not dispatch: {outcome.detail}"

        # 1. a new key version, the parent left exact
        versions = rows(package, "SELECT package_version_id, parent_version_id FROM "
                                 "package_version ORDER BY revision")
        assert len(versions) == 2, f"expected exactly one new version, got {versions!r}"
        child = versions[1]
        assert child["parent_version_id"] == world.package_version_id, (
            f"the corrected version's parent is {child['parent_version_id']!r}, expected the "
            f"run's version {world.package_version_id!r}"
        )
        catalog = PackageCatalog(package, package_id=world.package_id)
        keys = {
            version: {c["criterion_id"]: c["answer_key"] for c in catalog.criteria(version)}
            for version in (world.package_version_id, child["package_version_id"])
        }
        assert keys[child["package_version_id"]]["C-02"] == (_CORRECTED_KEY,), (
            f"the new version's C-02 key is {keys[child['package_version_id']]['C-02']!r}"
        )
        assert keys[world.package_version_id]["C-02"] == ("B",), (
            "the correction edited the parent version's key — FR-PKG-18: a key correction is a "
            "new version, and every grade produced under the parent still resolves to B"
        )

        # 2. re-derived by lookup, and only the corrected criterion
        scores_after = {
            (r["submission_id"], r["criterion_id"]): r["band"]
            for r in rows(cohort, "SELECT submission_id, criterion_id, band FROM criterion_score")
        }
        assert [scores_after[(s, "C-02")] for s in world.submissions] == [
            "incorrect", "correct", "incorrect"
        ], (
            f"C-02 after re-keying to D reads {[scores_after[(s, 'C-02')] for s in world.submissions]}"
            f"; a lookup against D gives incorrect/correct/incorrect for choices B/D/B"
        )
        untouched = {k: v for k, v in scores_before.items() if k[1] != "C-02"}
        assert {k: scores_after[k] for k in untouched} == untouched, (
            "a criterion other than C-02 changed score — the correction re-derives only the "
            "affected criterion"
        )

        # 3. the grade policy re-ran over the corrected scores
        grades = rows(
            cohort,
            "SELECT submission_id, revision, is_current, total FROM submission_grade "
            "WHERE run_id = :run_id ORDER BY submission_id, revision",
            run_id=world.run_id,
        )
        current = {g["submission_id"]: g for g in grades if g["is_current"]}
        assert [(current[s]["revision"], current[s]["total"]) for s in world.submissions] == [
            (2, 2.0), (2, 3.0), (2, 0.0)
        ], f"the current grades after the correction are {grades!r}"
        assert sum(1 for g in grades if g["revision"] == 1 and not g["is_current"]) == 3, (
            "revision 1 was not retained as a superseded revision for every submission"
        )
        audit = rows(
            store.durable(),
            "SELECT submission_id, answer_key_ref FROM audit_record WHERE run_id = :run_id "
            "AND criterion_id = 'C-02' AND evaluation_mode = 'deterministic'",
            run_id=world.run_id,
        )
        assert {a["submission_id"] for a in audit
                if child["package_version_id"] in str(a["answer_key_ref"])} == set(
            world.submissions
        ), f"the re-derivation's audit records do not name the corrected version: {audit!r}"

        # 4. zero panel judgments enqueued
        units_after = _ledger_units(cohort, world.run_id)
        assert units_after == units_before, (
            f"the correction changed the run's work ledger: {len(units_before)} unit(s) before, "
            f"{len(units_after)} after. FR-CONSOLE-30: a key correction enqueues no panel "
            f"judgment — it re-answers a fixed answer."
        )
        run = rows(cohort, "SELECT package_version_id FROM run WHERE run_id = :r", r=world.run_id)
        assert run[0]["package_version_id"] == child["package_version_id"], (
            "the run was not re-pointed at the corrected version, so its grades no longer "
            "resolve to the key that produced them"
        )
    finally:
        store.close()


def _findings_lines(page_html: str) -> list[str]:
    match = re.search(r'<section data-role="rubric-findings">(.*?)</section>', page_html, re.S)
    assert match, "S12 rendered no rubric-findings section"
    return [html_lib.unescape(line) for line in re.findall(r"<p>(.*?)</p>", match.group(1), re.S)]


def test_tc_console_31_the_rubric_findings_block_reports_breaker_and_budget_criteria(
    tmp_data_dir,
):
    """`TC-CONSOLE-31` / `FR-CONSOLE-31` — S12 with one breaker-tripped criterion and one
    budget-exhausted criterion.

    **Disclosed stand-ins** (the `TC-GRADE-16` precedent, `tests/integration/grade/
    test_rollup_findings.py`): C-10's `ungradeable_by_panel` rows are written directly because
    only M-AGG's breaker may mark them and M-AGG is not under test; C-11's exhausted review-queue
    row stands in for M-REVIEW's residual. The run, the package and the grade ledger around them
    are the shipped modules'.

    Exact value: the block has one line per finding — C-10 naming the breaker and 2 students,
    C-11 naming the exhausted budget and 1 student — and no line for any criterion that scored
    clean (the three multiple-choice criteria). The empty-run control renders the absence
    sentence instead, so the block is shown to discriminate.
    """
    store = open_store(tmp_data_dir)
    try:
        clean = seed_scored_run(store, cohort_id="c-ts48-clean", run_id="r-ts48-clean",
                                package_id="pkg-ts48-clean", with_open_criteria=True)
        clean_lines = _findings_lines(build_console(store=store).render(
            "/runs/{id}/rollup", id=clean.run_id).html)
        assert len(clean_lines) == 1 and "No rubric findings" in clean_lines[0], (
            f"a run with no breaker mark and no exhausted budget renders findings: {clean_lines!r}"
        )

        world = seed_scored_run(store, submissions=4, with_open_criteria=True,
                                choices=[("A", "B", "C")] * 4)
        cohort = store.cohort(world.cohort_id)
        s1, s2, s3, _s4 = world.submissions
        with cohort.transaction() as tx:
            for submission_id in (s1, s2):
                tx.execute(
                    "INSERT OR REPLACE INTO criterion_score "
                    "(run_id, submission_id, criterion_id, band, points, routing, state) "
                    "VALUES (COALESCE((SELECT run_id FROM run ORDER BY COALESCE(started_at, '') DESC, run_id DESC LIMIT 1), 'run-fixture'), :s, 'C-10', 'unscored', NULL, 'provisional', "
                    "'ungradeable_by_panel')",
                    s=submission_id,
                )
            tx.execute(
                "INSERT INTO review_queue (queue_id, submission_id, criterion_id, reason) "
                "VALUES (:q, :s, 'C-11', 'review budget exhausted')",
                q=f"q-{world.run_id}-C-11-{s3}",
                s=s3,
            )

        lines = _findings_lines(build_console(store=store).render(
            "/runs/{id}/rollup", id=world.run_id).html)
        per_criterion = {}
        for line in lines[1:]:  # the first line is the block's heading sentence
            criterion_id = line.split(":", 1)[0]
            assert criterion_id not in per_criterion, f"{criterion_id} listed twice: {lines!r}"
            per_criterion[criterion_id] = line
        assert set(per_criterion) == {"C-10", "C-11"}, (
            f"the findings block lists {sorted(per_criterion)}; expected exactly the "
            f"breaker-tripped C-10 and the budget-exhausted C-11 — {json.dumps(lines)}"
        )
        assert "ungradeable" in per_criterion["C-10"] and per_criterion["C-10"].endswith(
            "2 students"
        ), f"C-10's finding must name the breaker and its 2 students: {per_criterion['C-10']!r}"
        assert "review budget exhausted" in per_criterion["C-11"] and per_criterion[
            "C-11"
        ].endswith("1 student"), (
            f"C-11's finding must name the exhausted budget and its 1 student: "
            f"{per_criterion['C-11']!r}"
        )
    finally:
        store.close()
