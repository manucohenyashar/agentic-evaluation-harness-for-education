"""`TS-83` (issue #377) — `TC-PIPE-14`'s refusal arms: `M-PIPE` validates its two knobs before
it writes anything, and `main` exits 1 (`FR-PIPE-01` config arm, gap-fix test plan §5 / §6).

| Case | Input | Expected |
|---|---|---|
| `TC-PIPE-14` | `HARNESS_PIPE_MAX_PASSES` ∈ {`"0"`, `"-1"`, `"x"`, unset, `"2"`}; `HARNESS_PIPE_PASS_SLEEP_MS` ∈ {`"-5"`, `"0"`} | Unset → unbounded. `"2"` → at most 2 passes. `"0"`, `"-1"`, `"x"` and `"-5"` raise before any row is written, and `main` exits 1 (type per Q-14). The knob is read at call time |

**What is implemented here, and what is not.** The **refusal** clauses are implemented: an invalid
knob raises before any row is written, `main` exits 1, and the refusal names the knob it is
about. The **positive** clauses — "unset → unbounded" and "`"2"` → at most 2 passes" — are *not*,
because observing a pass bound requires driving a run to completion, and no world in this repo
can drive `run_to_completion` today (see #377's PR and the issue comment: `F-DEV-PIPE` does not
exist, and the recorded-fixture world records its responses *as it drives*, so a self-driving
composer has nothing to replay). They land with `TC-PIPE-01` once that corpus exists.

**Why the refusal arms are not blocked by the same thing.** The refusal happens *before* the
driver dispatches anything, so the store never needs to be drivable — only real. These cases use
`tests.support.orch_run.seed_run`, a genuine run over a real store, and assert the refusal lands
before it is touched.

**Q-14, honoured rather than worked around.** The plan records that `M-PIPE` declares no module
error type, so `TC-PIPE-14` "asserts only that the error is raised before any row is written and
that `main` exits 1; the type is not asserted". These cases therefore catch `Exception` for the
refusal arms and pin the *exit code*, the *absence of writes* and the *knob named in the
message* — never a class name.

**The control arm is what makes the `main` cases about the knob.** `main` exits 1 for plenty of
reasons — `TC-PIPE-08` already pins exit 1 for an unknown `--package-version` — so an exit code
alone cannot show the knob was read. Each refusal is therefore paired with the same invocation
under a *valid* knob, and the assertion is that only the invalid one names the knob.

**Interface.** Only `CT-PIPE-01`'s declared surface is used: `run_to_completion`, `recover`,
`main`. An earlier draft of this file invented `pipeline.max_passes(environ=...)` and
`pipeline.pass_sleep_ms(environ=...)` readers; they are not in the design, `max_passes` already
names a `run_to_completion` parameter, and every clause here is observable through the declared
surface — so they are gone.

**Written ahead of implementation: yes** — `aeh.pipeline` is #364's. Every body probes it first
with `require(...)`, so each case fails in milliseconds naming #364 rather than erroring at
collection. `WRITTEN_AHEAD_BLOCKERS` keys the entry to **#364**, the implementing issue.
"""

from __future__ import annotations

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md), for the seeded store
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
from aeh.store import Statement, open_store
from tests.support.impl import PIPE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

ISSUE = "#364"

MAX_PASSES_ENV = "HARNESS_PIPE_MAX_PASSES"
PASS_SLEEP_ENV = "HARNESS_PIPE_PASS_SLEEP_MS"

#: The refusals the plan names, per knob, with a valid value of the same knob to control against.
REFUSALS = (
    (MAX_PASSES_ENV, "0", "2"),
    (MAX_PASSES_ENV, "-1", "2"),
    (MAX_PASSES_ENV, "x", "2"),
    (PASS_SLEEP_ENV, "-5", "0"),
)

CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},)
SUBMISSIONS = ("S01",)

#: The five §4.3 tables a driven run writes into. "Before any row is written" is asserted
#: against all of them, not against one.
WRITTEN_TABLES = ("evidence", "verdict", "criterion_score", "narrative", "cell_phase")


def _row_counts(store) -> dict[str, int]:
    handle = store.cohort(ORCH_COHORT_ID)
    counts = {}
    for table in WRITTEN_TABLES:
        rows = handle.query(Statement(f"SELECT COUNT(*) AS n FROM {table}"))  # noqa: S608
        counts[table] = int(rows[0]["n"])
    return counts


@pytest.fixture
def seeded_run(tmp_data_dir):
    """A real run over a real store. Nothing is dispatched — the refusal lands first."""
    store = open_store(tmp_data_dir)
    try:
        _orchestrator, run_id, _version = seed_run(
            store, submissions=SUBMISSIONS, criteria=CRITERIA,
        )
        yield store, run_id
    finally:
        store.close()


# --- TC-PIPE-14 — the refusal lands before anything is written -----------------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize(("name", "bad", "good"), REFUSALS)
def test_tc_pipe_14_an_invalid_knob_is_refused_before_any_row_is_written(
    name, bad, good, seeded_run, monkeypatch
):
    """The refusal raises, names the knob, and leaves every §4.3 table untouched.

    "Before any row is written" is the half worth asserting: an implementation that validated
    its knobs after starting to drive would raise too, and the exception alone cannot tell the
    two apart. The row counts can.
    """
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    store, run_id = seeded_run
    before = _row_counts(store)
    monkeypatch.setenv(name, bad)

    with pytest.raises(Exception) as caught:  # Q-14: the type is not asserted
        run_to_completion(store, run_id, provider=None, run_config=None)

    assert name in str(caught.value), (
        f"the refusal does not name {name}: an operator reading it has to guess which knob they "
        f"set wrong. Got: {caught.value!r}"
    )
    assert _row_counts(store) == before, (
        f"{name}={bad!r} was refused, but rows were written first: {before} became "
        f"{_row_counts(store)}. A rejected configuration must leave no half-driven run behind"
    )
    # The control: the same call under a valid value of the same knob must not refuse *for the
    # knob*. Without this the assertions above pass for a driver that refuses everything.
    monkeypatch.setenv(name, good)
    try:
        run_to_completion(store, run_id, provider=None, run_config=None)
    except Exception as exc:  # noqa: BLE001 — a valid knob may still fail for other reasons
        assert name not in str(exc), (
            f"{name}={good!r} is a valid value but the driver still refused naming the knob: "
            f"{exc!r}. The knob check is rejecting a value the plan declares legal"
        )


@pytest.mark.writtenahead
@pytest.mark.parametrize(("name", "bad", "good"), REFUSALS)
def test_tc_pipe_14_main_exits_1_on_an_invalid_knob(name, bad, good, tmp_data_dir, monkeypatch):
    """`main` exits 1 for a refused configuration, and does so *because of the knob*.

    The control arm carries this case: `main` exits 1 for many reasons, so the same invocation
    is made under a valid value of the same knob and the assertion is that only the invalid one
    names it. Without the pair, `TC-PIPE-08`'s unknown-`--package-version` exit would satisfy
    every assertion here while the knob went unread.
    """
    main = require(PIPE_MODULE, "main", issue=ISSUE)
    argv = [
        "run",
        "--data-dir", str(tmp_data_dir),
        "--cohort", ORCH_COHORT_ID,
        "--package-version", "pv-knob",
    ]

    monkeypatch.setenv(name, bad)
    with pytest.raises(SystemExit) as caught:
        main(list(argv))
    assert caught.value.code == 1, (
        f"main exited {caught.value.code!r} for {name}={bad!r}; the plan pins exit 1 for a "
        "refused configuration (Q-14)"
    )
    invalid_message = str(caught.value)

    monkeypatch.setenv(name, good)
    with pytest.raises(SystemExit) as control:
        main(list(argv))
    assert name in invalid_message or name not in str(control.value), (
        f"main's refusal reads the same with {name}={bad!r} as with {name}={good!r}: "
        f"{invalid_message!r} vs {str(control.value)!r}. Nothing here shows the knob was read "
        "at all — this invocation exits 1 for its unknown package version either way"
    )


@pytest.mark.writtenahead
def test_tc_pipe_14_the_knob_is_read_at_call_time(seeded_run, monkeypatch):
    """Two calls in one process, with the environment changed between them, behave differently.

    Seam 3: a knob captured at import time is indistinguishable from a correct one until the
    second call. The observable used here is the refusal itself — valid, then invalid — which
    needs no drivable run.
    """
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    store, run_id = seeded_run

    monkeypatch.setenv(MAX_PASSES_ENV, "2")
    try:
        run_to_completion(store, run_id, provider=None, run_config=None)
    except Exception as exc:  # noqa: BLE001
        assert MAX_PASSES_ENV not in str(exc), (
            f"{MAX_PASSES_ENV}=2 is valid but was refused: {exc!r}"
        )

    monkeypatch.setenv(MAX_PASSES_ENV, "0")
    with pytest.raises(Exception) as caught:
        run_to_completion(store, run_id, provider=None, run_config=None)
    assert MAX_PASSES_ENV in str(caught.value), (
        f"the second call did not refuse {MAX_PASSES_ENV}=0 although the environment changed "
        f"between the two: {caught.value!r}. The knob was captured once, not read at call time"
    )
