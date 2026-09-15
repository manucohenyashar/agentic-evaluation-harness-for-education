"""`TS-87` (issue #381) — the scoring worker's half: `verdicts_for` (`TC-JUDGE-25`), taxonomy
errors are not strikes (`TC-JUDGE-26`), the verdict row persists `evidence_assessment` and
`latency_ms` (`TC-JUDGE-27`), and contract violations are counted per (criterion, judge)
(`TC-JUDGE-28`).

Gap-fix test plan §5:

- `TC-JUDGE-25` (`FR-JUDGE-18`, P0): run RA with 3 verdicts for `(S1,C1)` inserted in `work_id`
  order `w3, w1, w2`; run RB with 3 verdicts for the same pair → `verdicts_for(h, RA, S1, C1)`
  returns exactly RA's 3, ordered `w1, w2, w3`, each carrying band, `band_ordinal`,
  `cited_spans`, `evidence_sufficient`, `uncited` and `judge_id`. Feeding the tuple to `aggregate`
  succeeds with no adaptation. A nonexistent cell → empty tuple. Oracle: exact tuple.
- `TC-JUDGE-26` (`FR-JUDGE-19`, P0): `ScoringWorker.dispatch`, per error class, as in
  `TC-EXTRACT-16`, with `verdict` in place of `evidence`. The FR-JUDGE-10 re-request is **not**
  triggered by a taxonomy error. Oracle: exact state.
- `TC-JUDGE-27` (`FR-JUDGE-20`, P1): `persist` of a verdict with
  `evidence_assessment="partial: two of three steps"` and a 320 ms call → the stored row carries
  both values exactly; `evidence_assessment` NULL is stored as NULL, not `""`.
- `TC-JUDGE-28` (`FR-JUDGE-21`, P1): J2 returns 3 contract-violating responses on C1 (they
  strike); J1 returns 1 → `run_metrics` rows `judge_contract_violations` with dimensions
  `(C1,J2) = 3` and `(C1,J1) = 1`; a successful response writes none.

**Arms and blockers.** `TC-JUDGE-26`'s contrasts are green today and stay in `TEST_CMD`; its
taxonomy arms are `writtenahead` on #353. `TC-JUDGE-25`, `-27` and `-28` are `writtenahead` on
#361 (`verdicts_for`, the two verdict columns, the violation rows).

**How `TC-EXTRACT-16` maps onto `dispatch`.** The scoring worker keeps its strikes in memory and
raises `JudgmentError` when the budget is spent (it writes nothing and never calls `fail()`), so
"attempts" here is the result's own `attempts` count: a generic failure then a success returns
`attempts == 2` (one strike consumed), three generic failures raise `JudgmentError` — never the
provider's class — and a taxonomy error propagates as itself after exactly one call with the
ledger's `attempts` untouched.

**`TC-JUDGE-28`'s dimensions, read name-agnostically.** `run_metrics` today carries
`submission_id`/`criterion_id` dimensions and no judge column; how #361 records the judge is its
call. The case asserts a `judge_contract_violations` row for the run whose values include `C1`
and the judge's id, with the exact count — not a column name. That still assumes both ids are
stored as whole column values (as `criterion_id` is today); a single JSON "dimensions" column
would need this lookup to decode it.

**Isolation: rung 2** — TS-31's judged world (`tests/support/judge_run.py`) through the real
extraction leg; the judge boundary is the F-TAXONOMY stub or a per-judge script.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

from aeh.orch import STAGE_SCORE, Orchestrator
from aeh.prov import ProviderError
from aeh.store import lease_clock, open_store
from tests.support.clock import FrozenClock
from tests.support.agg_vocabulary import band, criterion, favourable_signals
from tests.support.conf_builders import edge_panel
from tests.support.extract_vocabulary import verdict_completion
from tests.support.impl import AGG_MODULE, JUDGE_MODULE, require
from tests.support.judge_run import (
    CONTROL_BAND,
    CONTROL_CONFIDENCE,
    DECLARED_NAMES,
    byte_span,
    canonical_document,
    default_pages,
    judge_world,
    permuted_reply,
    resolved,
    warm_judged_modules,
)
from tests.support.orch_run import ORCH_COHORT_ID
from tests.support.taxonomy import (
    TAXONOMY_THREE,
    UNPARSEABLE,
    PerJudgeScript,
    TaxonomyProvider,
    server_error,
)

pytestmark = pytest.mark.integration

OTHER_BAND = next(name for name in DECLARED_NAMES if name != CONTROL_BAND)


def _leased_world(tmp_data_dir, make_fixture_provider, *, submissions=("S1",), panel=1,
                  clock=None):
    """The judged world with extraction done and every score unit leased, nothing dispatched.
    `clock` becomes the store's lease clock before anything else can create one."""
    warm_judged_modules()
    store = open_store(tmp_data_dir)
    if clock is not None:
        lease_clock(store, clock)
    world = judge_world(
        store, make_fixture_provider(), submissions=submissions, panel=panel, judge_leg=False
    )
    units = list(world["orchestrator"].lease("w-judge-ts87", STAGE_SCORE, 64))
    assert units, "precondition: the extraction leg released no score units"
    return store, world, units


def _attempts(store, work_id) -> int:
    return int(store.cohort(ORCH_COHORT_ID).query(
        "SELECT attempts FROM work_unit WHERE work_id = :w", w=work_id)[0]["attempts"])


def _verdict_rows(store) -> list[Any]:
    return store.cohort(ORCH_COHORT_ID).query("SELECT * FROM verdict")


def _success(world, submission_id, build_id="judge-build-ts87", **kwargs):
    return verdict_completion(
        CONTROL_BAND, CONTROL_CONFIDENCE, build_id=build_id,
        cited_spans=world["spans"][submission_id], **kwargs,
    )


# --- TC-JUDGE-26 — taxonomy errors are not strikes ----------------------------------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize("error_class", TAXONOMY_THREE, ids=lambda cls: cls.__name__)
def test_tc_judge_26_a_taxonomy_error_propagates_without_a_strike_or_re_request(
    tmp_data_dir, make_fixture_provider, monkeypatch, error_class
):
    """`TC-JUDGE-26`, taxonomy arm — same class out of `dispatch` after exactly one call (no
    strike, no FR-JUDGE-10 re-request), no verdict row, ledger attempts 0, no `fail()`."""
    ScoringWorker = require(JUDGE_MODULE, "ScoringWorker", issue="#353")
    store, world, units = _leased_world(tmp_data_dir, make_fixture_provider)
    try:
        fail_calls: list[str] = []
        monkeypatch.setattr(
            Orchestrator, "fail",
            lambda self, work_id, *a, **k: fail_calls.append(work_id),
        )
        unit = units[0]
        ref = world["judges"].get(unit.judge) or edge_panel(1)[0]
        provider = TaxonomyProvider(
            [error_class] * 3, attempts_probe=lambda: _attempts(store, unit.work_id)
        )
        worker = ScoringWorker(store, provider, ref)
        request = worker.assemble(unit)

        with pytest.raises(ProviderError) as raised:
            worker.dispatch(request, ref)

        assert type(raised.value) is error_class, (
            f"dispatch raised {type(raised.value).__name__}, not {error_class.__name__} "
            f"(CT-JUDGE-19)"
        )
        assert len(provider.calls) == 1, (
            f"dispatch called the provider {len(provider.calls)} times after a "
            f"{error_class.__name__}: a taxonomy error is neither a strike nor a re-request"
        )
        # `dispatch` never touches the ledger today, so these two hold vacuously now; they are
        # kept to pin that the fix does not move a strike into the ledger instead.
        assert fail_calls == []
        assert _attempts(store, unit.work_id) == 0
        assert _verdict_rows(store) == [], "a taxonomy error wrote a verdict row"
    finally:
        store.close()


@pytest.mark.parametrize(
    "failure", [server_error, lambda: UNPARSEABLE], ids=["ProviderError-500", "unparseable-json"]
)
def test_tc_judge_26_contrast_a_generic_failure_is_still_a_strike(
    tmp_data_dir, make_fixture_provider, failure
):
    """`TC-JUDGE-26`, contrast arm (green today, stays green) — one failure then a success
    consumes one strike (`attempts == 2`) without propagating; three failures raise
    `JudgmentError`, never the provider's class, and write no verdict row."""
    ScoringWorker, JudgmentError = require(
        JUDGE_MODULE, "ScoringWorker", "JudgmentError", issue="#353"
    )
    store, world, units = _leased_world(tmp_data_dir, make_fixture_provider)
    try:
        unit = units[0]
        ref = world["judges"].get(unit.judge) or edge_panel(1)[0]

        once = ScoringWorker(
            store, TaxonomyProvider([failure(), _success(world, unit.submission_id)]), ref
        )
        result = once.dispatch(once.assemble(unit), ref)
        assert result.attempts == 2, f"one failure then success: attempts={result.attempts}"

        thrice = TaxonomyProvider([failure(), failure(), failure()])
        worker = ScoringWorker(store, thrice, ref)
        with pytest.raises(JudgmentError):
            worker.dispatch(worker.assemble(unit), ref)
        assert len(thrice.calls) == 3
        assert _verdict_rows(store) == []
    finally:
        store.close()


# --- TC-JUDGE-27 — evidence_assessment and latency_ms persist exactly ---------------------------


@pytest.mark.writtenahead
def test_tc_judge_27_persist_writes_evidence_assessment_and_latency_exactly(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-27` — `"partial: two of three steps"` and 320 ms stored exactly; a `None`
    assessment is stored as NULL, not `""`."""
    ScoringWorker = require(JUDGE_MODULE, "ScoringWorker", issue="#361")
    clock = FrozenClock()
    store, world, units = _leased_world(
        tmp_data_dir, make_fixture_provider, submissions=("S1", "S2"), clock=clock
    )
    try:
        by_submission = {unit.submission_id: unit for unit in units}
        ref = edge_panel(1)[0]

        unit = by_submission["S1"]
        reply = dataclasses.replace(
            _success(world, "S1", evidence_assessment="partial: two of three steps"),
            latency_ms=320,
        )

        def timed_reply(payload, model_ref, params):
            # Two witnesses, as in TC-EXTRACT-18: the store's lease clock advances 320 ms
            # inside the call, and the provider reports latency_ms=320.
            clock.advance(0.32)
            return reply

        worker = ScoringWorker(store, TaxonomyProvider([timed_reply]), ref)
        result = worker.dispatch(worker.assemble(unit), ref)
        worker.persist(unit, result)

        other = by_submission["S2"]
        worker2 = ScoringWorker(store, TaxonomyProvider([_success(world, "S2")]), ref)
        null_result = dataclasses.replace(
            worker2.dispatch(worker2.assemble(other), ref), evidence_assessment=None
        )
        worker2.persist(other, null_result)

        rows = {row["work_id"]: row for row in _verdict_rows(store)}
        assert "evidence_assessment" in rows[unit.work_id].keys(), (
            "the verdict row has no evidence_assessment column (FR-JUDGE-20)"
        )
        assert "latency_ms" in rows[unit.work_id].keys(), (
            "the verdict row has no latency_ms column (FR-JUDGE-20)"
        )
        assert rows[unit.work_id]["evidence_assessment"] == "partial: two of three steps"
        # 319 only for float truncation of the clock witness (see TC-EXTRACT-18).
        assert rows[unit.work_id]["latency_ms"] in (319, 320), (
            f"verdict.latency_ms = {rows[unit.work_id]['latency_ms']!r}, the call took 320 ms"
        )
        assert rows[other.work_id]["evidence_assessment"] is None, (
            f"a None assessment was stored as {rows[other.work_id]['evidence_assessment']!r}"
        )
    finally:
        store.close()


# --- TC-JUDGE-28 — contract violations counted per (criterion, judge) --------------------------


@pytest.mark.writtenahead
def test_tc_judge_28_contract_violations_are_recorded_per_criterion_and_judge(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-28` — J2: three violations (budget spent); J1: one violation then a legal reply;
    J3: a legal reply only. Rows: `(C1,J2) = 3`, `(C1,J1) = 1`, none for J3."""
    ScoringWorker, JudgmentError = require(
        JUDGE_MODULE, "ScoringWorker", "JudgmentError", issue="#361"
    )
    store, world, units = _leased_world(tmp_data_dir, make_fixture_provider, panel=3)
    try:
        j1, j2, j3 = (ref.build_id for ref in edge_panel(3))
        refs = {ref.build_id: ref for ref in edge_panel(3)}

        def violation():
            return permuted_reply(CONTROL_BAND, CONTROL_CONFIDENCE, build_id="judge-build-ts87")

        script = PerJudgeScript({
            j2: [violation(), violation(), violation()],
            j1: [violation(), _success(world, "S1")],
            j3: [_success(world, "S1")],
        })
        for unit in units:
            worker = ScoringWorker(store, script, refs[unit.judge])
            request = worker.assemble(unit)
            try:
                worker.persist(unit, worker.dispatch(request, refs[unit.judge]))
            except JudgmentError:
                pass

        run_id = world["run_id"]
        rows = store.durable().query(
            "SELECT * FROM run_metrics "
            "WHERE run_id = :r AND metric = 'judge_contract_violations'",
            r=run_id,
        )

        def value_for(judge: str) -> list[float]:
            return [row["value"] for row in rows
                    if "C1" in tuple(row) and judge in tuple(row)]

        assert value_for(j2) == [3], (
            f"(C1, J2) violations: {value_for(j2)} in {[tuple(r) for r in rows]}"
        )
        assert value_for(j1) == [1], f"(C1, J1) violations: {value_for(j1)}"
        assert value_for(j3) == [], "a judge with only legal replies wrote a violation row"
    finally:
        store.close()


# --- TC-JUDGE-25 — verdicts_for: one run, one cell, work_id order -------------------------------


@pytest.mark.writtenahead
def test_tc_judge_25_verdicts_for_returns_the_named_runs_cell_in_work_id_order(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-25` — RA's three verdicts, stored out of order (`w3, w1, w2`), come back in
    `work_id` order with the six fields; RB's three for the same cell never leak; the tuple feeds
    `aggregate` unchanged; an unknown cell is `()`."""
    warm_judged_modules()
    store = open_store(tmp_data_dir)
    try:
        # The three judges differ on every field `verdicts_for` must carry, so a dropped or
        # hard-coded field reads wrong on at least one row: J1 cites both spans and is
        # sufficient; J2 is uncited and insufficient; J3 cites one span and is sufficient.
        pages = default_pages("S1")
        document = canonical_document("\n".join(pages))
        both = [byte_span(document, pages[0]), byte_span(document, pages[1])]
        j1, j2, j3 = (ref.build_id for ref in edge_panel(3))
        replies = {
            j1: dict(band=CONTROL_BAND, cited_spans=both, evidence_sufficient=True),
            j2: dict(band=OTHER_BAND, cited_spans=None, evidence_sufficient=False),
            j3: dict(band=CONTROL_BAND, cited_spans=both[:1], evidence_sufficient=True),
        }
        world = judge_world(
            store, make_fixture_provider(), submissions=("S1",), panel=3,
            reply_for=lambda submission, judge: verdict_completion(
                replies[judge]["band"], CONTROL_CONFIDENCE, build_id="judge-build-ts87",
                cited_spans=replies[judge]["cited_spans"],
                evidence_sufficient=replies[judge]["evidence_sufficient"],
            ),
        )
        assert not world["failures"], world["failures"]
        run_a = world["run_id"]
        handle = store.cohort(ORCH_COHORT_ID)
        ra_rows = sorted((dict(r) for r in handle.query(
            "SELECT v.* FROM verdict v JOIN work_unit u ON u.work_id = v.work_id "
            "WHERE u.run_id = :r", r=run_a)), key=lambda r: r["work_id"])
        assert len(ra_rows) == 3, "precondition: RA holds three verdicts for (S1, C1)"
        distinct = {(r["uncited"], r["evidence_sufficient"], r["cited_spans"]) for r in ra_rows}
        assert len(distinct) == 3, (
            "precondition: the three RA verdicts must differ on uncited/sufficient/cited_spans"
        )

        # A second run over the same cell: copy RA's score units under new work ids.
        run_b = world["orchestrator"].create_run(
            ORCH_COHORT_ID, world["version"], resolved(3)
        )
        with handle.transaction() as tx:
            ra_ids = [row["work_id"] for row in ra_rows]
            w1, w2, w3 = ra_ids
            reordered = [ra_rows[2], ra_rows[0], ra_rows[1]]  # w3, w1, w2
            tx.execute("DELETE FROM verdict WHERE work_id IN (:a, :b, :c)", a=w1, b=w2, c=w3)
            for row in reordered:
                columns = ", ".join(row)
                tx.execute(f"INSERT INTO verdict ({columns}) VALUES "
                           f"({', '.join(':' + c for c in row)})", **row)
            for row in ra_rows:
                unit = dict(handle.query("SELECT * FROM work_unit WHERE work_id = :w",
                                         w=row["work_id"])[0])
                rb_work = "rb-" + row["work_id"]
                unit.update(work_id=rb_work, run_id=run_b)
                tx.execute(f"INSERT INTO work_unit ({', '.join(unit)}) VALUES "
                           f"({', '.join(':' + c for c in unit)})", **unit)
                rb_verdict = dict(row, verdict_id=rb_work, work_id=rb_work, band=OTHER_BAND)
                tx.execute(f"INSERT INTO verdict ({', '.join(rb_verdict)}) VALUES "
                           f"({', '.join(':' + c for c in rb_verdict)})", **rb_verdict)

        verdicts_for = require(JUDGE_MODULE, "verdicts_for", issue="#361")
        result = verdicts_for(handle, run_a, "S1", "C1")

        assert isinstance(result, tuple), f"verdicts_for returned {type(result).__name__}"
        assert len(result) == 3, f"expected RA's 3 verdicts, got {len(result)} (RB leaked?)"
        assert [v.judge_id for v in result] == [row["judge_id"] for row in ra_rows], (
            "verdicts are not in work_id order (w1, w2, w3) — storage order was w3, w1, w2"
        )
        for stored, row in zip(result, ra_rows):
            assert stored.band == row["band"], "a verdict's band is not RA's (RB leaked)"
            assert stored.band_ordinal == row["band_ordinal"]
            assert stored.evidence_sufficient == bool(row["evidence_sufficient"])
            assert stored.uncited == bool(row["uncited"])
            expected_spans = json.loads(row["cited_spans"]) if row["cited_spans"] else []
            got_spans = list(stored.cited_spans or ())
            assert len(got_spans) == len(expected_spans), (
                f"judge {row['judge_id']}: {len(got_spans)} cited spans, stored "
                f"{len(expected_spans)}"
            )
            for got, want in zip(got_spans, expected_spans):
                view = got if isinstance(got, dict) else vars(got)
                assert (view.get("start"), view.get("end")) == (want["start"], want["end"])

        aggregate = require(AGG_MODULE, "aggregate", issue="#361")
        ordinals = {row["band"]: row["band_ordinal"] for row in ra_rows}
        declared = criterion(
            [band(name, ordinals.get(name, index), float(index))
             for index, name in enumerate(DECLARED_NAMES)],
            criterion_id="C1",
        )
        aggregate(result, declared, favourable_signals())  # no adaptation

        assert verdicts_for(handle, run_a, "S1", "C-missing") == ()
    finally:
        store.close()
