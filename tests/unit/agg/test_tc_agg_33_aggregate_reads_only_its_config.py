"""`TC-AGG-33`, the unit arm (issue #896, FR-AGG-21, CT-AGG-14, CT-AGG-01) — `aggregate` reads
the aggregation constants only from its `config` argument.

Statistical-validity test plan §3.5 (story T3): "with the env var changed **during** a direct
`aggregate(...)` call, the result is unchanged (it reads only its `config` argument)". The
pause/resume arm of the same case is
`tests/integration/agg/test_tc_agg_33_frozen_across_pause_and_resume.py`.

**How "during" is made literal.** The verdict panel is a list that, the first time `aggregate`
iterates it (its engine count, before any constant is read), rewrites all four `HARNESS_AGG_*`
variables to salt values that would each move this cell. The environment is salted before the
call as well. A reading of any knob from the environment at any point of the call moves the
figure off the `config` value. (CT-AGG-C01's purity differential salts the environment between
calls; this arm changes it inside one.)

**Isolation: rung 0.** **Written ahead of implementation: no** — #865 (PR #928).

Markers. None (fast tier).
"""

from __future__ import annotations

import os

import pytest

from aeh.agg import aggregate
from aeh.conf import AGG_KEYS, AggKnobs
from tests.support.agg_vocabulary import band, criterion, signals, verdict

HOLISTIC = criterion([band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0),
                      band("B3", 3, 6.0)], scoring_model="holistic")
#: A run's frozen knobs: holistic multiplier 0.85, so a unanimous cited panel reads 0.85 and
#: queues under the 0.90 bar; 0.95 (the default) or any salt below would move it.
FROZEN = AggKnobs(auto_threshold_atomic=0.80, auto_threshold_holistic=0.90,
                  uncited_multiplier=0.80, holistic_multiplier=0.85)
#: Before the call: each would move the figure or the routing if read.
SALT_BEFORE = dict(zip(AGG_KEYS, ("0.30", "0.40", "0.50", "0.60")))
#: Written by the panel while `aggregate` runs: the holistic multiplier back to the default,
#: the holistic bar down so 0.85 would auto-accept.
SALT_DURING = dict(zip(AGG_KEYS, ("0.10", "0.20", "0.70", "0.95")))


class _PanelThatChangesTheEnvironment(list):
    """A verdict panel whose first iteration rewrites the four `HARNESS_AGG_*` variables."""

    def __init__(self, verdicts, environ_writer):
        super().__init__(verdicts)
        self._write = environ_writer
        self.flipped = False

    def __iter__(self):
        if not self.flipped:
            self.flipped = True
            self._write()
        return super().__iter__()


def test_tc_agg_33_unit_arm_the_environment_changed_during_the_call_moves_nothing(monkeypatch):
    for key in AGG_KEYS:
        monkeypatch.delenv(key, raising=False)
    plain = [verdict("B3", 3) for _ in range(3)]
    baseline = aggregate(list(plain), HOLISTIC, signals(), config=FROZEN)
    assert (baseline.confidence, baseline.routing) == (pytest.approx(0.85), "queued"), (
        f"fixture check — the frozen 0.85 decides this cell: {baseline}")

    for key, value in SALT_BEFORE.items():
        monkeypatch.setenv(key, value)

    def flip() -> None:
        for key, value in SALT_DURING.items():
            monkeypatch.setenv(key, value)

    panel = _PanelThatChangesTheEnvironment(plain, flip)
    during = aggregate(panel, HOLISTIC, signals(), config=FROZEN)

    assert panel.flipped, "fixture: the environment was never changed inside the call"
    assert os.environ[AGG_KEYS[3]] == SALT_DURING[AGG_KEYS[3]]
    assert (during.confidence, during.confidence_base, during.routing, during.state) == (
        baseline.confidence, baseline.confidence_base, baseline.routing, baseline.state), (
        "aggregate's result moved with the environment — it must read only its config "
        f"(FR-AGG-21, CT-AGG-01): before {baseline}, during {during}")
