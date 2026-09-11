"""`TC-CONFORM-06`, the testable half — the integrity gate blocks; ordinary divergences are findings.

Case: test plan §5.18, `FR-CONFORM-06`, §7.4 (Q-02). Oracle: **exact verdict for the testable
half** — the other half (the score-distribution gate) is recorded as a gap in the plan, and that
recording is asserted green in `tests/artifact/test_tc_conform_06_score_distribution_gap.py`.

    | TC-CONFORM-06 | Integration / 3 | A divergence in score distribution; and a divergence in
    | evidence-integrity failure rate | The integrity-rate divergence is treated as a §7.4 **gate
    | failure**, not a metrics note; ordinary divergences are reported as findings. The
    | score-distribution gate's threshold is **not computable as written** — see §2.3 Q-02 and
    | §7.4; this case asserts the integrity half and records the other as a gap |

**Landed at #134** (unmarked there): the run and the divergence machinery it drives are
`ConformanceSuite.run`'s. Rung 3, and not `live`: both verdicts are driven by *induced*
divergences on a real run, which needs the run machinery, not a live model —
`induced_divergence` is the suite's own test seam.

**How this differs from TS-75's `CT-CONFORM-05`.** Those cases assert the classification trio
per dimension through `classify_divergence` at the contract rung. This file asserts the *verdict*
a real run reaches and what the verdict carries: a blocked run names its gate (so a reader sees
a §7.4 gate failure, not a metrics note), a blocked dimension is never simultaneously filed as a
finding (a verdict that is both is a verdict nobody can act on), and an ordinary divergence's
finding carries its measured value — a finding that only names the dimension is a metrics note
nobody can judge. The overlap is reported on the PR.
"""

from __future__ import annotations

import pytest

from tests.support.conf_builders import EDGE_PANEL_3, HOSTED_PANEL_3, edge_cfg, hosted_cfg
from tests.support.conform_vocabulary import (
    AGREEMENT_DIMENSION,
    DIVERGENCE_DIMENSIONS,
    LIVE_GATE_DIMENSION,
)
from tests.support.impl import CONFORM_MODULE, require

pytestmark = [pytest.mark.integration]

ISSUE = "#134"
CASE = "TC-CONFORM-06"


def _two_backends():
    return [edge_cfg(panel=EDGE_PANEL_3), hosted_cfg(panel=HOSTED_PANEL_3)]


def _synthetic_cohort():
    from aeh.conf import CohortRef

    return CohortRef(cohort_id="c-conform-fixtures", consent_class="synthetic")


def test_tc_conform_06_an_integrity_rate_divergence_is_a_gate_failure_not_a_metrics_note():
    """The computable gate, driven — the run blocks, names the gate, and does not also note it.

    §7.4's own words: *"the evidence-integrity-rate half **is** computable and is gated"*. The
    verdict has to be exact, and the exact verdict has three parts:

    * **blocked** — the run stops, rather than completing with a note attached;
    * **named** — the blocked outcome names the gate that crossed, so the reader sees a §7.4
      gate failure rather than a generic failure;
    * **not also a finding** — a dimension filed both as a gate failure and as a findings entry
      is the verdict reading as whatever the reader prefers, which is how a gate failure becomes
      a metrics note in practice.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue=ISSUE)
    induce = require(CONFORM_MODULE, "induced_divergence", issue=ISSUE)

    with induce(LIVE_GATE_DIMENSION):
        outcome = build_suite().run("v1", _two_backends(), cohort=_synthetic_cohort())

    assert outcome.blocked, (
        f"a divergence on {LIVE_GATE_DIMENSION} did not block the run. §7.4 records this half as "
        f"the one that **is** computable and **is** gated; treating it as a metrics note is "
        f"exactly the treatment the case forbids."
    )
    assert LIVE_GATE_DIMENSION in outcome.blocking_dimensions, (
        f"the run blocked without naming {LIVE_GATE_DIMENSION} as the gate that crossed. A "
        f"§7.4 gate failure is attributed to its gate, not to a run that merely failed."
    )
    assert LIVE_GATE_DIMENSION not in outcome.findings, (
        f"{LIVE_GATE_DIMENSION} is filed as both a gate failure and a finding. The clause's "
        f"contrast is between a gate failure and a metrics note; a dimension that is both is a "
        f"verdict nobody can act on."
    )


def test_tc_conform_06_an_ordinary_divergence_is_a_finding_that_carries_its_measured_value():
    """*"Ordinary divergences are reported as findings"* — and the finding carries its number.

    Reported **as a finding**, not silently and not as a failure: `FR-CONFORM-06`'s default is
    that divergence is for human judgement, and a human cannot judge a name. So the finding is
    asserted to carry the measured divergence value itself — the same figure the divergence
    report carries for that dimension. A findings entry that drops the value would still pass a
    membership check while being exactly the metrics note the clause's contrast implies is not
    enough.

    `AGREEMENT_DIMENSION` stands for the ordinary dimensions here (the other two are asserted
    per-dimension in TS-75's parametrized `CT-CONFORM-05` case): chance-corrected agreement is
    the one dimension where blocking would contradict a promise the design explicitly does not
    make — verdicts are not reproducible, so `M-STATS` measures self-agreement rather than
    assuming it (`CT-JUDGE-17`).
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue=ISSUE)
    induce = require(CONFORM_MODULE, "induced_divergence", issue=ISSUE)

    assert AGREEMENT_DIMENSION in (DIVERGENCE_DIMENSIONS - {LIVE_GATE_DIMENSION}), (
        "the dimension driven as 'ordinary' is not a declared divergence dimension; the case's "
        "ordinary-findings half has lost its subject"
    )
    with induce(AGREEMENT_DIMENSION):
        outcome = build_suite().run("v1", _two_backends(), cohort=_synthetic_cohort())

    assert not outcome.blocked, (
        f"a divergence on {AGREEMENT_DIMENSION} blocked the run. Only two dimensions are gates "
        f"and this is not one; blocking here would stop a release on a metrics note."
    )
    assert AGREEMENT_DIMENSION in outcome.findings, (
        f"{AGREEMENT_DIMENSION} diverged and was neither a gate failure nor a finding — silent, "
        f"which is the one outcome the clause does not offer."
    )
    measured = outcome.divergence.dimensions[AGREEMENT_DIMENSION]
    assert outcome.findings[AGREEMENT_DIMENSION] == measured, (
        f"the finding for {AGREEMENT_DIMENSION} carries {outcome.findings[AGREEMENT_DIMENSION]!r} "
        f"while the divergence report measured {measured!r}. A finding whose value is not the "
        f"measured divergence is a note nobody can judge — and 'for human judgement' was the "
        f"whole reason the clause left this half ungated."
    )