"""TC-AGG-31 (#814), the pipeline limb: `more_graders_unavailable` is reachable.

Traces: FR-AGG-20 (the closed `not_final_reason` set), CT-AGG-24.
Source: docs/design/console_clarity_test_plan.md §3.2. The other five codes are reached at rung 0 in
`tests/contract/agg/test_tc_agg_27_28_31_jev_final_clause.py`. This one is not `aggregate`'s to set:
"escalation wanted, no seat" is known only to the aggregate hook (`pipeline/hooks.py`, the
`DECISION_NO_REAL_SEAT` branch), so it is reached here at rung 3. The world is TC-PIPE-33's: the
sample physics test through `aeh run`, one judge, no escalation judges, random arm 0, so every
disagreeing cell wants seats 2-3 and has none.

**What "stored" means here.** The delta adds no store migration, so there is no column to read. The
case captures every score the hook hands to `write_score` (the store write seam) and asserts on
the last one written for each cell. A `not_final_reason` column or a results read added later
would be the stronger oracle.

**Interface assumed** (written ahead of #806): `CriterionScore.not_final_reason`. Also a precedence:
a single-LLM-verdict cell whose escalation was wanted but had no seat carries
`more_graders_unavailable`, not `one_grader_unsure`. That is the more specific cause, and the one
the teacher can act on (add graders). Without it, the code is reachable only on a random-arm
three-judge cell, which this suite cannot seed deterministically.

**Markers.** `writtenahead` on #806.
"""

from __future__ import annotations

import dataclasses
import re

import pytest

from tests.support.impl import NotImplementedYet
from tests.unit.pipe.test_live_escalation_seats import _config, physics  # noqa: F401 -- the fixture

pytestmark = pytest.mark.writtenahead

LINE = re.compile(r"^(?P<sub>[^/\s]+)/(?P<crit>\S+): .* -> escalation wanted, no real judge for seats 2-3")


def test_tc_agg_31_more_graders_unavailable_is_stored_for_a_seatless_cell(
        tmp_data_dir, tmp_path, physics, capsys, monkeypatch):  # noqa: F811
    from aeh.agg import CriterionScore
    from aeh.pipeline import hooks

    if "not_final_reason" not in {f.name for f in dataclasses.fields(CriterionScore)}:
        raise NotImplementedYet(
            "CriterionScore has no `not_final_reason` yet (blocked on #806): FR-AGG-20's closed "
            "reason set, written ahead of its implementation (test plan §8.2).")
    written: dict[tuple[str, str], object] = {}
    real = hooks.write_score

    def recording(tx, run_id, submission_id, score, signals):  # noqa: ANN001
        written[(submission_id, score.criterion_id)] = score
        return real(tx, run_id, submission_id, score, signals)

    monkeypatch.setattr(hooks, "write_score", recording)
    monkeypatch.setenv("HARNESS_ORCH_RANDOM_ARM_RATE", "0")
    fake, run = physics
    code, result, err = run(_config(tmp_path), capsys)
    assert code == 0 and result["status"] == "complete", (result, err)
    lines = [line for stage in result["stages"] for line in stage["detail"]]
    seatless = [(m["sub"], m["crit"]) for m in map(LINE.match, lines) if m]
    assert seatless, f"precondition: at least one cell wanted seats it did not have: {lines}"
    for key in seatless:
        score = written[key]
        assert score.state == "provisional_unreviewed", (key, score.state)
        assert score.not_final_reason == "more_graders_unavailable", (key, score.not_final_reason)
