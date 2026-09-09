"""`TC-AGG-18` — `aggregate`, `should_escalate` and `ordinal_alpha` are pure, under guards.

Test plan §5.12 (row form: Artifact assertion / rung 0), issue #95 (TS-36). Traces to
`NFR-AGG-01`; the assertion form of CT-AGG-01 ("no store access, no model call, no
clock, no configuration read beyond the values passed in"). **Landed at #93** (the
last of the three symbols — `aggregate` and `ordinal_alpha` are #91's,
`should_escalate` #93's).

`TC-ORCH-32` (#64) pins `should_escalate`'s purity from the orchestrator side; this
file is the module-side assertion over all three members, and the corollary
TC-ORCH-32 declared as a landing assumption is asserted here for every member: the
same inputs evaluated again return an equal result — for `should_escalate` this
holds structurally, the landed decision type being a frozen dataclass compared by
value.

**The guards, and their one declared blind spot:**

- the TS-00 socket guard (autouse) — a model call fails mid-connect;
- a refusing store spy handed to every store-shaped parameter (TC-ORCH-32's oracle);
- the clock, `datetime`, `random` and `os` **surfaces are poisoned**: the stdlib
  attributes (`time.time`, `time.monotonic`, `time.perf_counter`, `time.process_time`,
  `time.thread_time`, `random.random`, `random.choices`, `random.sample`, `os.getenv`)
  raise, naming the I/O the contract forbids, and the `datetime.datetime` /
  `datetime.date` class attributes are replaced with the same poison — the methods
  themselves sit on immutable C types and cannot be patched, so the class is what
  gets poisoned (any `datetime.*` use fails on the attribute access). `os.environ`
  is deliberately left alone — the harness process reads it mid-run — so the os limb
  is `os.getenv`. The module under test's own bindings of those modules are replaced
  too, so a module-qualified access fails as well;
- **blind spot, recorded rather than papered over**: a `from time import time`
  binding captures the function object at import and is invisible to both poisons.
  The AST-level alternative (banning the import shape) is `TC-PROV-05`'s walker's
  job and is not duplicated here; the determinism assertion below is the behavioural
  backstop — a clock-read would make repeated evaluation diverge.

Isolation: rung 0 — the guards ARE the case.
"""

from __future__ import annotations

import inspect

import pytest

from tests.support.agg_vocabulary import (
    band,
    criterion,
    panel,
    signals,
    agg_config,
    escalation_score,
    criterion_history,
    expected_distribution,
)
from tests.support.impl import AGG_MODULE, require

_FOUR_BAND = criterion([band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0),
                        band("B3", 3, 6.0)])
_UNANIMOUS_TOP = panel(("B3", 3), ("B3", 3), ("B3", 3))
_SPLIT = panel(("B0", 0), ("B1", 1), ("B1", 1), ("B1", 1), ("B2", 2))

#: The result fields whose equality the determinism corollary asserts — the observable
#: surface, so a decision type with identity equality (TC-ORCH-32's declared landing
#: assumption) still admits the check.
_SCORE_FIELDS = ("confidence", "routing", "state", "band", "ordinal", "points",
                 "judge_count", "agreement", "band_spread", "modal_band")


class _RefusingStoreSpy:
    """A store spy that fails on any access — TC-ORCH-32's purity oracle."""

    def __getattr__(self, name: str):
        raise AssertionError(
            f"the policy function touched the store during evaluation ({name!r}) — "
            "CT-AGG-01: no store access"
        )


class _Poison:
    """Attribute access raises, naming the I/O the purity contract forbids."""

    def __init__(self, what: str):
        self._what = what

    def __getattr__(self, name: str):
        raise AssertionError(
            f"the policy function reached {self._what}.{name} — CT-AGG-01: no clock "
            "and no configuration read beyond the values passed in"
        )


def _poison_the_world(monkeypatch: pytest.MonkeyPatch, agg_module) -> None:
    """Poison every clock, entropy and configuration surface the policy could reach —
    the stdlib attributes and the module under test's own bindings alike."""
    def boom(name):
        def _boom(*_a, **_k):
            raise AssertionError(
                f"the policy function reached {name} — CT-AGG-01: no clock and no "
                "configuration read beyond the values passed in"
            )
        return _boom

    for target in (
        "time.time", "time.monotonic", "time.perf_counter", "time.process_time",
        "time.thread_time", "random.random", "random.choices", "random.sample",
        "os.getenv",
    ):
        monkeypatch.setattr(target, boom(target), raising=False)
    # The datetime surfaces: `datetime.datetime.now`/`.utcnow` and
    # `datetime.date.today` are attributes of IMMUTABLE C types — patching the
    # methods themselves raises `TypeError: cannot set ... of immutable type`
    # (the declared blind spot's sibling, found the first time this fixture
    # ran). The rebindable surface is the module's own class attribute, so the
    # poison replaces the class: any use of `datetime.datetime.<anything>` or
    # `datetime.date.<anything>` under it fails on the attribute access.
    monkeypatch.setattr("datetime.datetime", _Poison("datetime.datetime"), raising=False)
    monkeypatch.setattr("datetime.date", _Poison("datetime.date"), raising=False)
    # `os.environ` itself is NOT replaced: the harness process reads it mid-run
    # (pytest's terminal writer asks shutil.get_terminal_size, which reads
    # os.environ['COLUMNS']), so a wholesale replacement poisons pytest, not the
    # module. The os limb is `os.getenv` — the read path a pure module would
    # take — plus the module-binding poison below.

    for name in ("time", "datetime", "random", "os"):
        if hasattr(agg_module, name):
            monkeypatch.setattr(agg_module, name, _Poison(name))


def _spy_kwargs(function) -> dict:
    """A refusing spy for every store-shaped parameter the signature declares —
    name-agnostic over the usual seams (TC-ORCH-32's construction)."""
    spy_names = {"store", "store_handle", "session", "conn", "connection"}
    return {
        name: _RefusingStoreSpy()
        for name in inspect.signature(function).parameters
        if name.lower() in spy_names
    }


def test_tc_agg_18_aggregate_is_pure_under_guards(monkeypatch):
    """`TC-AGG-18` (`NFR-AGG-01`, artifact assertion / rung 0, purity assertion, P0)
    — `aggregate` evaluated under the full guard set returns the same score twice:
    no store access, no model call, no clock, no configuration read."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")
    _poison_the_world(monkeypatch, require(AGG_MODULE))
    spy_kwargs = _spy_kwargs(aggregate)

    first = aggregate(_UNANIMOUS_TOP, _FOUR_BAND, signals(), config=agg_config(),
                      **spy_kwargs)
    second = aggregate(_UNANIMOUS_TOP, _FOUR_BAND, signals(), config=agg_config(),
                       **spy_kwargs)

    for field in _SCORE_FIELDS:
        assert getattr(first, field) == getattr(second, field), (
            f"aggregate returned {field}={getattr(first, field)!r} then "
            f"{getattr(second, field)!r} for identical inputs — a policy that is not "
            "deterministic is not a pure function (CT-AGG-01, NFR-AGG-01)"
        )


def test_tc_agg_18_should_escalate_is_pure_under_guards(monkeypatch):
    """`TC-AGG-18` (`NFR-AGG-01`, artifact assertion / rung 0, purity assertion, P0)
    — `should_escalate` evaluated under the full guard set returns an equal decision
    twice; any store-shaped parameter receives the refusing spy."""
    should_escalate = require(AGG_MODULE, "should_escalate", issue="#93")
    _poison_the_world(monkeypatch, require(AGG_MODULE))
    spy_kwargs = _spy_kwargs(should_escalate)

    inputs = dict(
        score=escalation_score(ordinal=2, band_count=4),
        criterion=_FOUR_BAND,
        history=criterion_history(),
        baseline=expected_distribution(),
    )
    first = should_escalate(**inputs, **spy_kwargs)
    second = should_escalate(**inputs, **spy_kwargs)

    assert first == second, (
        f"should_escalate returned {first!r} then {second!r} for identical inputs — "
        "a policy that is not deterministic is not a pure function (CT-AGG-01, "
        "NFR-AGG-01; the same corollary TC-ORCH-32 asserts)"
    )


def test_tc_agg_18_ordinal_alpha_is_pure_under_guards(monkeypatch):
    """`TC-AGG-18` (`NFR-AGG-01`, artifact assertion / rung 0, purity assertion, P0)
    — `ordinal_alpha` evaluated under the full guard set returns the same figure
    twice: agreement is a pure function of the verdicts (FR-AGG-04)."""
    ordinal_alpha = require(AGG_MODULE, "ordinal_alpha", issue="#93")
    _poison_the_world(monkeypatch, require(AGG_MODULE))

    first = ordinal_alpha(_SPLIT)
    second = ordinal_alpha(_SPLIT)

    assert first == second, (
        f"ordinal_alpha returned {first!r} then {second!r} for identical verdicts — "
        "agreement is a pure function of the verdicts (FR-AGG-04, CT-AGG-01)"
    )
