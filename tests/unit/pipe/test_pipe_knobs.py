"""`TS-83` (issue #377) — `TC-PIPE-14`: `M-PIPE`'s two knobs, validated and read at call time
(`FR-PIPE-01` config arm, gap-fix test plan §5 / §6).

| Case | Input | Expected |
|---|---|---|
| `TC-PIPE-14` | `HARNESS_PIPE_MAX_PASSES` ∈ {`"0"`, `"-1"`, `"x"`, unset, `"2"`}; `HARNESS_PIPE_PASS_SLEEP_MS` ∈ {`"-5"`, `"0"`} | Unset → unbounded. `"2"` → at most 2 passes. `"0"`, `"-1"`, `"x"` and `"-5"` raise before any row is written, and `main` exits 1 (type per Q-14). The knob is read at call time: changing the environment between two calls changes the pass bound |

**Rung 1, and why this case is the one that stays there.** Seam 3 says an environment-sensitive
constant gets a knob whose production value is the default. Nothing about *resolving* a knob
needs a store, a provider or a run — so the resolution arms here construct nothing. The one arm
that does touch a filesystem is the "before any row is written" half, which is an assertion
about **absence**: after `main` refuses, the data directory holds no store files. That needs a
directory, not a world.

**Q-14, honoured rather than worked around.** The plan records that `M-PIPE` declares no module
error type, so `TC-PIPE-14` "asserts only that the error is raised before any row is written and
that `main` exits 1; the type is not asserted". These cases therefore catch `Exception` for the
refusal arms and pin the *exit code* and the *absence of rows*, never a class name. When #364
declares an error type, tightening this to that type is a deliberate edit, not a silent one.

**Read at call time, which is the half a constant gets wrong.** A knob captured at import time
is indistinguishable from a correct one until the second call in the same process — so the last
case changes the environment *between* two resolutions and asserts the answer moved. A module
that read its knob once passes every other assertion in this file.

**Written ahead of implementation: yes** — `aeh.pipeline` does not exist; #364 builds it. Every
body probes it first with `require(...)`, so each case fails in milliseconds with a message
naming #364 rather than erroring at collection. `WRITTEN_AHEAD_BLOCKERS` keys the entry to
**#364**, the implementing issue, not to #377 which writes the tests.

**Scope.** `TC-PIPE-08`'s full CLI contract (exit 0/1/3, stdout JSON, the `HARNESS_PROFILE`
resolution) is `TS-84` (#378) and is deliberately not asserted here; this file touches `main`
only for the one clause `TC-PIPE-14` names.
"""

from __future__ import annotations

import pytest

from tests.support.impl import PIPE_MODULE, require

ISSUE = "#364"

MAX_PASSES_ENV = "HARNESS_PIPE_MAX_PASSES"
PASS_SLEEP_ENV = "HARNESS_PIPE_PASS_SLEEP_MS"

#: The values the plan names as refusals, per knob.
REFUSED_MAX_PASSES = ("0", "-1", "x")
REFUSED_PASS_SLEEP = ("-5",)

#: The reader each knob is resolved through. `M-PIPE` does not exist, so these names are an
#: interface assumption this case makes for #364 to reconcile deliberately: the keyword-`environ`
#: shape every other module in this repo already uses for an env-gated knob
#: (`calib._max_questions`, `store._int_env`), so a knob is testable without mutating the process.
READERS = {MAX_PASSES_ENV: "max_passes", PASS_SLEEP_ENV: "pass_sleep_ms"}


def _resolver(name: str):
    """The module's reader for one knob, probed by name so a missing `M-PIPE` fails legibly."""
    return require(PIPE_MODULE, READERS[name], issue=ISSUE)


# --- TC-PIPE-14 — resolution ---------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_pipe_14_an_unset_max_passes_is_unbounded():
    """Unset → unbounded. `None` is the only honest spelling: a sentinel integer would make
    "unbounded" a number somebody later compares against."""
    resolve = _resolver(MAX_PASSES_ENV)
    assert resolve(environ={}) is None, (
        f"{MAX_PASSES_ENV} unset must resolve to None (unbounded); a numeric default would cap "
        "a production run at a figure nobody declared"
    )


@pytest.mark.writtenahead
def test_tc_pipe_14_max_passes_two_resolves_to_two():
    resolve = _resolver(MAX_PASSES_ENV)
    assert resolve(environ={MAX_PASSES_ENV: "2"}) == 2


@pytest.mark.writtenahead
@pytest.mark.parametrize("value", REFUSED_MAX_PASSES)
def test_tc_pipe_14_an_invalid_max_passes_is_refused(value):
    """`"0"`, `"-1"` and `"x"`. Zero is refused with the negatives deliberately: a run that may
    make no passes at all is a run that cannot finish, which is a configuration nobody means."""
    resolve = _resolver(MAX_PASSES_ENV)
    # Q-14: the plan does not declare M-PIPE's error type, so the type is not asserted.
    with pytest.raises(Exception) as caught:
        resolve(environ={MAX_PASSES_ENV: value})
    assert MAX_PASSES_ENV in str(caught.value), (
        f"the refusal does not name {MAX_PASSES_ENV}: an operator reading this message has to "
        f"guess which knob they set wrong. Got: {caught.value!r}"
    )


@pytest.mark.writtenahead
def test_tc_pipe_14_a_zero_pass_sleep_is_valid_and_a_negative_one_is_refused():
    """`"0"` is a legitimate value — no sleep between passes — and `"-5"` is not. The pair is
    one case because the boundary is the whole point: an implementation validating `> 0` refuses
    the valid value, and one validating nothing accepts the invalid one."""
    resolve = _resolver(PASS_SLEEP_ENV)
    assert resolve(environ={PASS_SLEEP_ENV: "0"}) == 0
    for value in REFUSED_PASS_SLEEP:
        with pytest.raises(Exception) as caught:
            resolve(environ={PASS_SLEEP_ENV: value})
        assert PASS_SLEEP_ENV in str(caught.value), (
            f"the refusal does not name {PASS_SLEEP_ENV}. Got: {caught.value!r}"
        )


@pytest.mark.writtenahead
def test_tc_pipe_14_the_knobs_are_read_at_call_time():
    """Two resolutions in one process, with the environment changed between them, give two
    answers (seam 3). A module that captured its knob at import time passes every assertion
    above and fails this one — which is the defect the clause exists for."""
    resolve = _resolver(MAX_PASSES_ENV)
    first = resolve(environ={MAX_PASSES_ENV: "2"})
    second = resolve(environ={MAX_PASSES_ENV: "5"})
    assert (first, second) == (2, 5), (
        f"the pass bound did not move when the environment did: {first} then {second}. The knob "
        "is read at call time, not captured at import (CLAUDE.md seam 3)"
    )


# --- TC-PIPE-14 — the refusal happens before anything is written ---------------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize(
    ("name", "value"),
    [(MAX_PASSES_ENV, value) for value in REFUSED_MAX_PASSES]
    + [(PASS_SLEEP_ENV, value) for value in REFUSED_PASS_SLEEP],
)
def test_tc_pipe_14_main_exits_1_and_writes_no_row_on_an_invalid_knob(
    name, value, tmp_data_dir, monkeypatch
):
    """`main` exits 1, and the refusal lands **before any row is written**.

    The second half is the one worth asserting: an implementation that validates its knobs after
    creating the run row leaves a run nobody can finish, and it exits 1 all the same — so the
    exit code alone cannot tell the two apart. The oracle is the absence of the store files a
    run would have created.
    """
    main = require(PIPE_MODULE, "main", issue=ISSUE)
    monkeypatch.setenv(name, value)

    with pytest.raises(SystemExit) as caught:
        main([
            "run",
            "--data-dir", str(tmp_data_dir),
            "--cohort", "coh-knob",
            "--package-version", "pv-knob",
        ])
    assert caught.value.code == 1, (
        f"main exited {caught.value.code!r} for {name}={value!r}; the plan pins exit 1 for a "
        "refused configuration (Q-14)"
    )
    written = sorted(path.name for path in tmp_data_dir.rglob("*.sqlite") if path.is_file())
    assert written == [], (
        f"main refused {name}={value!r} but left store files behind: {written}. The knob is "
        "validated before any row is written, or a rejected configuration leaves a half-built "
        "run somebody has to clean up"
    )
