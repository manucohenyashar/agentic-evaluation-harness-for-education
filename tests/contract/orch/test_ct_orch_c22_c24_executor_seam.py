"""`TC-ORCH-C22`, `TC-ORCH-C23` and `TC-ORCH-C24` — the executor seam's three clauses
(§6.11.7, `CT-ORCH-22/23/24`).

The clause-suite discriminator throughout: *would this go red if the clause broke while every
`FR-ORCH-*` case stayed green?* Each case below is built against the specific construction the
plan names, not against the requirement's happy path — `TC-ORCH-38/39/40` already cover that.

| Case | Clause | The violation it catches |
|---|---|---|
| `C22` | a unit reaches `done` only through the worker's transaction | the pool callback marking units done from the returned `StageOutcome` |
| `C23` | every governed call accrues, including one the worker then strikes | accrual moved to after `persist`, so struck calls vanish from cost |
| `C24` | `cell_phase` is written only by `mark_cell_phase` | M-PIPE or M-INTEG writing the phase directly |

**C22 is the one a green FR suite hides.** `TC-ORCH-38` asserts the executor is *called*; it
says nothing about who closes the unit. An orchestrator that read `StageOutcome(completed=True)`
and marked the row `done` itself would satisfy every dispatch case in the suite and would close
units whose worker raised after the model call — RISK-41's "the ledger says done" with no
evidence row behind it, which is invisible by construction because a `done` row is a legal row.

**C23's third call is the case.** Two successes and a strike: an implementation that accrued
inside `persist` gets the first two right and loses the third, so the run's bill under-reports
by exactly the calls that went wrong. That is the direction that flatters the run, and it is
the direction nobody notices.

**C24 is a census, because the row is only meaningful if one writer owns it.** `cell_phase` is
what makes `M-PIPE`'s hooks resume-safe; a second writer that recorded a phase beside work
that rolled back would make a restart skip the work.

**Isolation: rung 2**, plus a rung-0 static census for C24.
"""

from __future__ import annotations

import ast
import pathlib
import re
from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.orch import ORCH_STATEMENTS, Orchestrator, StageOutcome
from aeh.store import Statement, open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_documents, seed_run

pytestmark = [pytest.mark.contract, pytest.mark.integration]

SUBMISSION = "S01"
CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)

_UNITS = Statement(
    "SELECT work_id, stage, status, attempts FROM work_unit WHERE run_id = :run_id "
    "ORDER BY work_id"
)
_PHASES = Statement("SELECT COUNT(*) AS n FROM cell_phase WHERE run_id = :run_id")
_METRIC = Statement(
    "SELECT value FROM run_metrics WHERE run_id = :run_id AND metric = :metric"
)


class _StubProvider:
    def estimate_cost(self, unit: Any) -> None:  # noqa: ARG002 — the seam's shape
        return None

    def complete(self, payload: Any, model_ref: Any = None, params: Any = None) -> Any:
        raise AssertionError("this suite's executors answer without a model call")


def _world(tmp_data_dir, **kwargs: Any):
    store = open_store(tmp_data_dir)
    seeder, run_id, _version = seed_run(
        store, submissions=(SUBMISSION,), criteria=CRITERIA,
    )
    seed_documents(store, (SUBMISSION,))
    seeder.enumerate_units(run_id)
    probe = Orchestrator(store, **kwargs)
    probe.start(run_id)
    return store, probe, run_id


def _units(store: Any, run_id: str) -> list[dict[str, Any]]:
    return [dict(row) for row in store.cohort(ORCH_COHORT_ID).query(_UNITS, run_id=run_id)]


# --- TC-ORCH-C22 -------------------------------------------------------------------------------


def test_tc_orch_c22_the_pool_callback_closes_units_from_the_returned_outcome(tmp_data_dir):
    """**A reported violation of `CT-ORCH-22`, pinned so the fix is visible.**

    The plan's construction verbatim: `execute` returns a completed `StageOutcome` and never
    touches a worker, so nothing wrote evidence and nothing marked the row. The clause says the
    unit must not be `done` — "the orchestrator does not mark it; only the worker's transaction
    or `complete()` after `evaluate` does. **Breaks if** the pool callback marks units done
    from the returned `StageOutcome`."

    It does. `_run_model_batch` reaches `self.complete(unit.work_id)` for any
    `StageOutcome(completed=True)` (`orch.py`, the batch loop), so a unit the executor merely
    *claimed* is closed. Measured here: one `done` extract unit with no evidence row behind it.

    **Why this is not benign in practice, and why it is not urgent either.** With the shipped
    `ProductionStageExecutor` the worker marks the unit `done` inside its own transaction
    first, and `complete()` early-returns on an already-`done` unit — so the callback is a
    no-op on the real path. The exposure is a *defective or hostile executor*: exactly the
    thing the seam admits as an extension point, and exactly RISK-41's shape (the ledger says
    done, the cell has no evidence, and nothing reports it because `done` is a legal row).

    So this asserts what ships and **fails the day the clause is honoured**, at which point
    this case is replaced by the clause's own assertion (`closed == []`). Asserting the clause
    now would put a permanently red P0 in the suite; asserting nothing would leave a P0 safety
    clause with no case at all. #388 reports it for `/plan-to-issues`.
    """
    class _LyingExecutor:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, unit: Any, governed: Any) -> StageOutcome:  # noqa: ARG002
            self.calls += 1
            return StageOutcome(completed=True, detail="claimed without working")

    executor = _LyingExecutor()
    store, probe, run_id = _world(
        tmp_data_dir, executor=executor, provider=_StubProvider()
    )
    try:
        probe.progress(run_id)

        assert executor.calls > 0, "no unit reached the executor, so the case proves nothing"
        closed = [unit for unit in _units(store, run_id) if unit["status"] == "done"]
        assert closed != [], (
            "no unit was closed by the lying executor — `CT-ORCH-22` is now honoured. Replace "
            "this case with the clause's own assertion (`closed == []`) and delete the "
            "divergence note in its docstring (#388 reported the gap)"
        )
        assert [unit["stage"] for unit in closed] == ["extract"], (
            f"the closed units are {[(u['stage'], u['work_id'][:8]) for u in closed]}; the "
            "pass claims only the extract unit"
        )

        # And the evidence the clause is about is genuinely absent: the row says done and
        # there is nothing behind it. This is the half that makes the gap a SAFETY finding
        # rather than a bookkeeping one.
        evidence = store.cohort(ORCH_COHORT_ID).query(
            Statement(
                "SELECT COUNT(*) AS n FROM evidence WHERE work_id = :w"
            ),
            w=closed[0]["work_id"],
        )[0]["n"]
        assert int(evidence) == 0, (
            "the claimed unit has evidence rows, so the executor did more than claim — the "
            "fixture no longer isolates the clause"
        )
    finally:
        store.close()


def test_tc_orch_c22_a_real_worker_does_close_its_unit(tmp_data_dir):
    """The positive control: when a worker really runs, the unit does reach `done`.

    Without it, C22 passes against an orchestrator that never closes anything — a run that can
    never complete, which is a different defect with the same assertion.
    """
    from aeh.pipeline import ProductionStageExecutor
    from tests.support.extract_vocabulary import span_completion
    from tests.support.orch_run import PLAIN_TRANSCRIPT, orch_cfg

    class _AnsweringProvider:
        def estimate_cost(self, unit: Any) -> None:  # noqa: ARG002
            return None

        def complete(self, payload: Any, model_ref: Any = None, params: Any = None) -> Any:
            build = getattr(model_ref, "build_id", None) or "fixture-build"
            return span_completion(
                [{"start": 0, "end": 5, "text": PLAIN_TRANSCRIPT[:5]}], build_id=build
            )

    config = orch_cfg()
    store = open_store(tmp_data_dir)
    try:
        seeder, run_id, _version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA, cfg=config,
        )
        seed_documents(store, (SUBMISSION,))
        seeder.enumerate_units(run_id)
        provider = _AnsweringProvider()
        executor = ProductionStageExecutor(store, provider, config)
        probe = Orchestrator(store, executor=executor, provider=provider)
        executor.orchestrator = probe
        probe.start(run_id)
        probe.progress(run_id)

        done = [unit for unit in _units(store, run_id) if unit["status"] == "done"]
        assert done, (
            "no unit reached `done` even with a real worker behind the seam; C22's refusal "
            "above would then hold for a run that can never complete"
        )
    finally:
        store.close()


# --- TC-ORCH-C23 -------------------------------------------------------------------------------


@pytest.mark.parametrize("seam", ("executor", "transport"))
def test_tc_orch_c23_a_struck_call_still_accrues_to_the_run(tmp_data_dir, seam):
    """Three governed calls — success, success, strike — and all three are on the bill.

    Run against both seams, as the plan requires: they share `_accrue_completion` by design,
    and the case is what keeps that single definition honest.

    The third call is the case. An implementation that accrued inside `persist` counts the two
    successes and loses the strike, so the run's cost under-reports by exactly the calls that
    went wrong — the direction that flatters the run.
    """
    from aeh.prov import Completion

    def _answer(index: int) -> Completion:
        return Completion(
            text="{}", tokens_in=10, tokens_out=1, latency_ms=1,
            resolved_build=f"build-{index}", cached_prefix_tokens=0, cost=None,
        )

    calls: list[int] = []

    class _CountingProvider:
        def estimate_cost(self, unit: Any) -> None:  # noqa: ARG002
            return None

        def complete(self, payload: Any, model_ref: Any = None, params: Any = None) -> Any:
            calls.append(len(calls))
            return _answer(len(calls))

    class _ThriceThenStrike:
        """Makes three governed calls for the unit and then reports it unfinished.

        The worker's own strike: `completed=False` means "I spent these calls and the unit is
        not done", which is precisely the state whose spending must still be counted.
        """

        def execute(self, unit: Any, governed: Any) -> StageOutcome:  # noqa: ARG002
            for _ in range(3):
                governed.complete("payload", None, None)
            return StageOutcome(completed=False, detail="struck after three calls")

    class _TransportThrice:
        def __init__(self, provider: Any) -> None:
            self._provider = provider

        def call(self, request: Any) -> Any:  # noqa: ARG002
            return self._provider.complete("payload", None, None)

    provider = _CountingProvider()
    if seam == "executor":
        kwargs = {"executor": _ThriceThenStrike(), "provider": provider}
    else:
        kwargs = {"transport": _TransportThrice(provider), "provider": provider}

    store, probe, run_id = _world(tmp_data_dir, **kwargs)
    try:
        probe.progress(run_id)

        tokens_out = store.durable().query(
            _METRIC, run_id=run_id, metric="tokens_out"
        )
        assert tokens_out, "the run flushed no tokens_out metric"
        counted = float(tokens_out[0]["value"])
        assert counted == float(len(calls)), (
            f"the provider answered {len(calls)} call(s) and the run counted {counted} "
            "token(s) out at one per call. Accrual happens around the call, not after the "
            "worker persists — a struck unit's calls are still money the run spent "
            "(CT-ORCH-23, CT-PROV-11)"
        )
    finally:
        store.close()


# --- TC-ORCH-C24 -------------------------------------------------------------------------------


def test_tc_orch_c24_marking_a_phase_twice_leaves_one_row(tmp_data_dir):
    """The behavioural half: two marks, one row.

    `TC-ORCH-40` covers this at the FR level; it is repeated here because the census below is
    only worth having if the single writer is itself idempotent — a census over a writer that
    appended would guarantee one *module* writing duplicates.
    """
    store, probe, run_id = _world(tmp_data_dir)
    try:
        handle = store.cohort(ORCH_COHORT_ID)
        with handle.transaction() as tx:
            probe.mark_cell_phase(tx, run_id, SUBMISSION, CRITERION, "integrity_pre", 2)
            probe.mark_cell_phase(tx, run_id, SUBMISSION, CRITERION, "integrity_pre", 2)

        count = int(handle.query(_PHASES, run_id=run_id)[0]["n"])
        assert count == 1, f"marking one phase twice produced {count} rows"
    finally:
        store.close()


#: Every module that could reach `cell_phase`. `orch.py` owns it; the others are the ones the
#: plan names as the plausible second writers.
_PHASE_WRITER_CANDIDATES = ("orch.py", "pipeline.py", "integ.py", "agg.py", "review.py")

_PHASE_WRITE = re.compile(
    r"(INSERT|UPDATE|REPLACE)[^;]*?\bcell_phase\b", re.IGNORECASE | re.DOTALL
)


def _phase_write_sites(module_name: str, source_text: str | None = None) -> list[str]:
    """Names of the string constants in `module_name` that write `cell_phase`.

    Parsed rather than grepped so the modules' own prose about the table is not reported. The
    value returned is the enclosing assignment target or dict key where one can be read, so a
    failure names the statement rather than a line number that moves.
    """
    if source_text is None:
        path = pathlib.Path(aeh.orch.__file__).parent / module_name
        if not path.exists():
            return []
        source_text = path.read_text(encoding="utf-8")
    tree = ast.parse(source_text)

    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }

    found: list[str] = []
    # Constants already attributed to a named statement, so a dict entry is reported once by
    # its key rather than twice (key + the literal inside it).
    attributed: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            constants = [
                inner for inner in ast.walk(value)
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str)
            ]
            text = "".join(inner.value for inner in constants)
            if _PHASE_WRITE.search(text) and isinstance(key, ast.Constant):
                found.append(str(key.value))
                attributed.update(id(inner) for inner in constants)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings or id(node) in attributed:
            continue
        if _PHASE_WRITE.search(node.value):
            found.append(f"<literal@{node.lineno}>")
    return sorted(set(found))


#: What the census finds TODAY — and `integ.py`'s entry is a **reported violation of
#: `CT-ORCH-24`**, not an exemption anyone granted.
#:
#: The clause says `cell_phase` is written only by `mark_cell_phase`. `M-INTEG` writes it
#: directly (`INTEG_STATEMENTS["write_integrity_post"]`, `integ.py:254`, called from
#: `_record_routed`) and **cannot do otherwise**: its row carries `panel_state`, and
#: `mark_cell_phase(tx, run_id, submission_id, criterion_id, phase, units_consumed)` has no
#: such parameter — `panel_state` does not appear in `orch.py` at all.
#:
#: So the clause and the implementation genuinely disagree, and closing it is a design call
#: (`mark_cell_phase` grows the parameter, or `CT-ORCH-24` is amended to name two writers).
#: Pinning the state means the day it is settled this case goes red and is settled
#: deliberately; asserting zero would put a permanently red P0 in the suite, and asserting
#: nothing would let a THIRD writer land unnoticed — which is the failure the census exists
#: for. #388 reports it.
SANCTIONED_PHASE_WRITERS: dict[str, list[str]] = {
    "orch.py": ["upsert_cell_phase"],
    "integ.py": ["write_integrity_post"],
}


@pytest.mark.parametrize("module_name", _PHASE_WRITER_CANDIDATES)
def test_tc_orch_c24_only_the_sanctioned_statements_write_cell_phase(module_name):
    """Only `ORCH_STATEMENTS["upsert_cell_phase"]` writes `cell_phase`.

    The phase row is what makes `M-PIPE`'s hooks resume-safe: it commits inside the caller's
    transaction, so a phase and the work it stands for land together or not at all. A second
    writer — M-PIPE recording the phase beside its hook, M-INTEG stamping `integrity_post` —
    could record a phase next to work that rolled back, and a restart would then skip the work
    (`NFR-PIPE-01` is about exactly that).
    """
    sites = _phase_write_sites(module_name)

    assert sites == SANCTIONED_PHASE_WRITERS.get(module_name, []), (
        f"{module_name}'s cell_phase writers are {sites}, not "
        f"{SANCTIONED_PHASE_WRITERS.get(module_name, [])}. `M-ORCH` owns the table: a writer "
        "that recorded a phase beside work which then rolled back would make a restart skip "
        f"the work (NFR-PIPE-01). Sanctioned today: {SANCTIONED_PHASE_WRITERS}"
    )


def test_tc_orch_c24_the_declared_statement_is_the_one_the_census_found():
    """The census's control: the statement it names really is a `cell_phase` write.

    Exercised through `_phase_write_sites` itself, over a probe that plainly writes the table,
    so a census that stopped matching fails here rather than reporting "no writers" for every
    module — which is what a broken scan looks like and is indistinguishable from success.
    """
    assert "cell_phase" in str(ORCH_STATEMENTS["upsert_cell_phase"]).lower(), (
        "the declared statement does not mention cell_phase; the census is pointed at the "
        "wrong name"
    )

    probe = (
        'STATEMENTS = {\n'
        '    "sneaky_phase": Statement(\n'
        '        "INSERT INTO cell_phase (run_id, phase) VALUES (:r, :p)"\n'
        '    ),\n'
        '}\n'
    )
    assert _phase_write_sites("probe.py", probe) == ["sneaky_phase"], (
        "the census does not recognise a plain INSERT into cell_phase, so every module case "
        "above is passing over a pattern it cannot see"
    )
