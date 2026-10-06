"""`TC-JUDGE-45` — a composite criterion is never a score unit (`FR-JUDGE-38`, ADR-39; #625, TS-146).

Operator-requirements test plan §5.5: *"F-RUBRIC-METHODS run through enumeration: the
composite's work units vs its aspects'. Only the three aspect criteria are enumerated as score
units; the composite appears in no `work_unit` row. A store hand-corrupted to carry a composite
unit is refused at the enumeration seam with the same finality as a malformed unit."*
Oracle: exact + negative. RISK-111 (critical): a composite reaching a judge returns garbage that
aggregates like a real verdict.

Two arms:

1. **Exact enumeration** — the run's whole `work_unit` set, `(stage, criterion_id, judge_id)`
   per submission, against a hand-computed expectation: the MCQ line one deterministic unit;
   `C-bands`, `C-general` and the three aspects one extract unit each plus one score unit per
   panel seat (holistic → base depth three, panel of three); `C-comp` in no row of any stage.
   The random arm is disabled (`HARNESS_ORCH_RANDOM_ARM_RATE=0`) so the expectation is exact.
2. **The hand-corrupted ledger** — the violation constructed deliberately rather than hoped
   absent: a score unit for `C-comp` raw-inserted beside the aspects' (cloned from an aspect's
   score row, its `work_id` from the shipped `compute_work_id`). A valid reply is RECORDED for
   it, so a guardless worker would happily judge it. The unit is driven through the real
   lease → assemble → dispatch → fail cycle `TC-JUDGE-18` pins for a malformed unit, and must
   reach that case's finality: `quarantined`, `last_error` retained (naming the composite), no
   verdict row — plus the assertion a malformed reply does not have: **zero transport calls**
   for the composite. Before the lease loop the run is enumerated again, so a guard in the
   enumeration path itself gets its chance. Which layer refuses (enumeration, lease, assemble
   or dispatch) is not pinned; the design names "the enumeration seam" but no function.

**Written ahead of #626** (and of #622, whose `score_method` / `component_of` the builder
writes): today the builder raises `TypeError` on `score_method=`. Arm 1 is the
`WRITTEN_AHEAD_BLOCKERS` key for #626 — with only #622 landed it still fails, because
`enumerate_units` walks every criterion and emits composite units.

Isolation: rung 2 — real store, real published package, real orchestrator and workers;
`RecordedFixtureProvider` at the model boundary; no network.
"""

from __future__ import annotations

import pytest

from aeh.orch import (EXTRACTOR_VERSION, STAGE_DETERMINISTIC, STAGE_EXTRACT, STAGE_SCORE,
                      compute_work_id)
from aeh.store import open_store
from tests.support.composition_world import (
    ASPECTS,
    COMPOSITE,
    JUDGED,
    MCQ,
    rubric_methods,
    seed_rubric_run,
    work_units,
)
from tests.support.conf_builders import edge_panel
from tests.support.extract_vocabulary import sampling_params, verdict_completion
from tests.support.judge_run import verdict_rows, warm_judged_modules, work_unit_row

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

SUBMISSIONS = ("s-45-a", "s-45-b")
PANEL = 3
WORKER = "w-judge-tj45"


@pytest.fixture
def world(tmp_data_dir, monkeypatch):
    monkeypatch.setenv("HARNESS_ORCH_RANDOM_ARM_RATE", "0")
    warm_judged_modules()
    store = open_store(tmp_data_dir / "data")
    try:
        yield seed_rubric_run(store, rubric_methods(), SUBMISSIONS, panel=PANEL)
    finally:
        store.close()


def _expected_units(judges: list[str]) -> list[tuple[str, str, str | None, str | None]]:
    expected = []
    for submission_id in SUBMISSIONS:
        expected.append((submission_id, STAGE_DETERMINISTIC, MCQ, None))
        for criterion_id in JUDGED:
            expected.append((submission_id, STAGE_EXTRACT, criterion_id, None))
            for judge in judges:
                expected.append((submission_id, STAGE_SCORE, criterion_id, judge))
    return sorted(expected, key=repr)


def test_tc_judge_45_only_the_aspects_are_enumerated_and_the_composite_is_in_no_unit(world):
    """Exact: the run's units are the hand-computed set — the composite in none of them."""
    rows = work_units(world)
    judges = [ref.build_id for ref in edge_panel(PANEL)]
    actual = sorted(((r["submission_id"], r["stage"], r["criterion_id"], r["judge_id"])
                     for r in rows), key=repr)

    composite_rows = [r for r in rows if r["criterion_id"] == COMPOSITE]
    assert composite_rows == [], (
        f"composite {COMPOSITE} was enumerated as {len(composite_rows)} work unit(s) "
        f"(stages {sorted({r['stage'] for r in composite_rows})}) — FR-JUDGE-38: a composite is "
        "never a unit, only its aspects are")
    assert actual == _expected_units(judges), (
        "the enumerated unit set is not the hand-computed one:\n"
        f"  missing: {sorted(set(_expected_units(judges)) - set(actual), key=repr)}\n"
        f"  extra:   {sorted(set(actual) - set(_expected_units(judges)), key=repr)}")
    score_criteria = {r["criterion_id"] for r in rows if r["stage"] == STAGE_SCORE}
    assert score_criteria >= set(ASPECTS), "precondition: every aspect is a score unit"


# --- the hand-corrupted ledger ----------------------------------------------------------------


def _corrupt_with_composite_unit(world) -> tuple[str, str]:
    """Raw-insert a `C-comp` score unit, cloned from aspect 1's first-seat score unit of the
    first submission. Returns (work_id, judge build)."""
    cohort = world.cohort
    template = dict(cohort.query(
        "SELECT * FROM work_unit WHERE run_id = :r AND stage = :s AND criterion_id = :c "
        "AND submission_id = :sub ORDER BY work_id LIMIT 1",
        r=world.run_id, s=STAGE_SCORE, c=ASPECTS[0], sub=SUBMISSIONS[0])[0])
    run = dict(cohort.query("SELECT * FROM run WHERE run_id = :r", r=world.run_id)[0])
    work_id = compute_work_id(
        run_id=world.run_id, stage=STAGE_SCORE, submission_id=SUBMISSIONS[0],
        criterion_id=COMPOSITE, judge_id=template["judge_id"],
        package_version_id=world.version, panel_config=str(run["panel_config"]),
        prompt_template_version=str(run["prompt_template_v"]),
        extractor_version=EXTRACTOR_VERSION,
    )
    template.update(work_id=work_id, criterion_id=COMPOSITE, status="pending", attempts=0)
    for volatile in ("lease_owner", "lease_expires_at", "last_error"):
        if volatile in template:
            template[volatile] = None
    columns = sorted(template)
    with cohort.transaction() as tx:
        # The corruption's shape is fixed whatever enumeration did: exactly ONE composite unit,
        # a score unit with no extract sibling (so nothing holds it back from the lease).
        # Before #626 enumeration itself wrote composite units — arm 1's failure — and they
        # are cleared here so this arm tests the refusal, not the gate's extract ordering.
        tx.execute("DELETE FROM work_unit WHERE run_id = :r AND criterion_id = :c",
                   r=world.run_id, c=COMPOSITE)
        tx.execute(
            f"INSERT INTO work_unit ({', '.join(columns)}) "
            f"VALUES ({', '.join(':' + c for c in columns)})",
            **template)
    assert work_unit_row(world.store, work_id)["criterion_id"] == COMPOSITE, (
        "precondition: the corrupted unit is in the ledger")
    return work_id, template["judge_id"]


class _CallsByUnit:
    """The model boundary, counting every `complete` per work unit being dispatched."""

    def __init__(self, inner):
        self._inner = inner
        self.current: str | None = None
        self.calls: dict[str, int] = {}

    def complete(self, payload, model_ref, params):
        self.calls[self.current] = self.calls.get(self.current, 0) + 1
        return self._inner.complete(payload, model_ref, params)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_tc_judge_45_a_hand_corrupted_composite_unit_is_refused_like_a_malformed_unit(
    world, make_fixture_provider
):
    """The corrupted composite unit reaches TC-JUDGE-18's finality — quarantined, its refusal
    retained and naming the composite, no verdict — with no transport call ever made for it,
    and the rest of the run untouched."""
    from aeh.judge import ScoringWorker, prompt_fields

    work_id, judge_build = _corrupt_with_composite_unit(world)
    judges = {ref.build_id: ref for ref in edge_panel(PANEL)}
    provider = make_fixture_provider()
    counting = _CallsByUnit(provider)
    orchestrator = world.orchestrator
    # FR-JUDGE-38 places the guard "in the work-enumeration path": give that path its chance.
    # A second enumeration over the corrupted ledger is what a resume or a re-ingest does;
    # a guard there may quarantine the unit before any lease sees it (the precondition below
    # accepts that). Whatever it does, it must not raise past the run.
    orchestrator.enumerate_units(world.run_id)
    added = [(r["stage"], r["judge_id"]) for r in work_units(world)
             if r["criterion_id"] == COMPOSITE and r["work_id"] != work_id]
    assert added == [], (
        f"re-enumerating the corrupted ledger emitted {len(added)} more composite unit(s) "
        f"{sorted(added, key=repr)} — FR-JUDGE-38: enumeration never creates a composite unit")

    # No extraction has run, so every aspect / bands / general score unit is held behind its
    # extract sibling (FR-ORCH-06); the corrupted unit has none, so the score stage can only
    # ever hand out the composite. Drive the fail cycle until it is terminal.
    reached = False
    for _cycle in range(8):
        if work_unit_row(world.store, work_id)["status"] in ("quarantined", "done"):
            break
        batch = list(orchestrator.lease(WORKER, STAGE_SCORE, 64))
        if not batch:
            break
        for unit in batch:
            assert unit.work_id == work_id, (
                f"precondition: only the composite unit is claimable before extraction, but "
                f"{unit.criterion_id} was leased")
            reached = True
            ref = judges[unit.judge]
            counting.current = unit.work_id
            worker = ScoringWorker(world.store, counting, ref)
            try:
                request = worker.assemble(unit)
                # A valid-looking reply, recorded under the exact key: a guardless dispatch
                # would accept it and write a verdict the aggregator treats as real.
                provider.record(prompt_fields(request), ref, sampling_params(),
                                verdict_completion("present", 0.9, build_id="build-tj45"))
                result = worker.dispatch(request, ref)
                worker.persist(unit, result)
                orchestrator.complete(unit.work_id)
            except Exception as error:  # the refusal — the case asserts what it led to
                orchestrator.fail(unit.work_id, error)

    row = dict(work_unit_row(world.store, work_id))
    assert reached or row["status"] == "quarantined", (
        f"precondition: the corrupted unit was neither leased nor refused — it sits "
        f"{row['status']!r}, and the arm would pass vacuously")
    assert row["status"] == "quarantined", (
        f"a composite score unit must end quarantined — a malformed unit's finality "
        f"(TC-JUDGE-18) — not {row['status']!r}: {row!r}")
    assert row["last_error"] and COMPOSITE in str(row["last_error"]), (
        f"the quarantine retains a refusal naming the composite {COMPOSITE}: "
        f"{row['last_error']!r}")
    assert verdict_rows(world.store, work_id) == [], (
        "no verdict row may exist for a composite (NFR-JUDGE-05: no fallback verdict)")
    assert counting.calls.get(work_id, 0) == 0, (
        f"the composite reached a judge {counting.calls[work_id]} time(s) — RISK-111: a "
        "composite must be refused before any transport call, not struck after one")

    # The refusal is the composite's alone: every other unit is still pending, untouched.
    others = [r for r in work_units(world) if r["work_id"] != work_id]
    assert others and all(r["status"] == "pending" and not r["attempts"] for r in others), (
        "refusing the composite touched other units: "
        f"{sorted({(r['criterion_id'], r['status']) for r in others if r['status'] != 'pending'})}")
