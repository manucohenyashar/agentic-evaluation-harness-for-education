"""`TC-JUDGE-C16` — the judge signals are emitted per criterion and per judge, under
their exact names (§6.11.10).

`CT-JUDGE-16` (observe): *"Emits, per criterion and judge: uncited-verdict rate,
`evidence_sufficient = false` rate, band histogram, contract-violation rate, latency,
prefix cache hit rate. Contract violations concentrated on one judge mean that judge's
prompt or build is wrong; that reading is contract because it is what makes the metric
actionable."* (detailed design, verbatim). The plan row makes the DIMENSIONALITY the
contract: *"a metric emitted without the judge dimension fails the case even though it
is emitted."*

Written ahead of its emitter: no per-(criterion, judge) emitter exists yet, and no
Interfaces block declares the six names — so the surface is declared ONCE, in
`tests/support/judge_vocabulary.py` (`JUDGE_SIGNAL_FIELDS`, named for the clause's own
words), and this file resolves it through the `require()` door keyed `#148` (the
observability suite, TS-55 — the Requires tables name `M-STATS` as the emitter's
owner), whose `WRITTEN_AHEAD_BLOCKERS` entry is what tells whoever lands the emitter
to unmark this file. The whole case is `writtenahead` and correctly red; the body
below is the bet the emitter must satisfy when it lands — over a real judged run at
rung 2, not over invented numbers.

The bet, in three limbs over one judged run carrying an atomic AND a holistic
criterion (so both dimensions are populated by construction):

1. the emitted cells' key set is EXACTLY the (criterion, judge) pairs the run's
   ledger judged — a run-level aggregate carries the fields but fails here, because
   the clause's reading is unsupportable from an aggregate;
2. every cell carries all six signals under their exact names, by set equality —
   a renamed signal is a signal nobody alerts on;
3. every declared field carries a value per cell — the declared-but-unmeasured shape
   is the silent failure `CLAUDE.md` names first.

Cross-references, not duplicates: the prefix-share invariant the cache-hit signal
presumes is `TC-JUDGE-C13` (`test_ct_judge_c13_prefix_share.py`); the contract violations
the rate counts are the refusals `M-INTEG`'s verification and the response contract
raise at the judge boundary (`FR-JUDGE-17`, `TC-JUDGE-C14`'s three guarantees); the
per-judge panel identity the dimensionality rests on is `TC-JUDGE-C08`'s byte-identity
drive. The integration-tier census over the same six signals is `TC-JUDGE-24a`
(`tests/integration/judge/test_tc_judge_24_signal_census.py`, #83): it hand-counts
exact rates on one disclosed criterion and defers "the non-degenerate per-criterion
pin" — which is the axis this file holds (atomic AND holistic, key-set equality
against the run's ledger). The consumer that turns the signals into action is the
console monitor (`M-CONSOLE`) — it reads what this case pins the emitter to produce.

Isolation: rung 2 — real store, real workers, the fixture provider at the model
boundary; the socket guard is autouse.
"""

from __future__ import annotations

from typing import Any

import pytest

from aeh.store import open_store
from tests.contract.judge._drive import BANDS, drive_judged_run
from tests.support.impl import STATS_MODULE, require
from tests.support.judge_vocabulary import JUDGE_SIGNAL_FIELDS
from tests.support.orch_run import ORCH_COHORT_ID

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]


def test_tc_judge_c16_the_six_signals_are_emitted_per_criterion_and_per_judge(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C16` (`CT-JUDGE-16`, names + dimensionality, rung 2, P0) — over a
    real judged run mixing an atomic and a holistic criterion, the emitted cells are
    exactly the (criterion, judge) pairs the ledger judged, and every cell carries
    all six declared signals under their exact names."""
    judge_signals = require(STATS_MODULE, "judge_signals", issue="#148")
    store = open_store(tmp_data_dir)
    try:
        # Two criteria of different scoring models: the atomic one panels at base
        # depth 1 (one judge), the holistic one at the full panel depth (three) —
        # both dimensions of the contract populated by the drive itself.
        specs = [
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic",
             "band_count": len(BANDS)},
            {"criterion_id": "C2", "kind": "open", "scoring_model": "holistic",
             "band_count": len(BANDS)},
        ]
        _orchestrator, run_id, _version = drive_judged_run(
            store, make_fixture_provider(), criterion_specs=specs,
        )
        judged_pairs = {
            (row["criterion_id"], row["judge_id"])
            for row in store.cohort(ORCH_COHORT_ID).query(
                "SELECT DISTINCT criterion_id, judge_id FROM work_unit "
                "WHERE run_id = :r AND stage = 'score'",
                r=run_id,
            )
        }
        assert len({judge for _c, judge in judged_pairs}) >= 3, (
            "fixture bug: the drive did not judge through the full panel — the "
            "judge dimension below cannot be distinguished from an aggregate"
        )
        assert len({criterion for criterion, _j in judged_pairs}) == 2, (
            "fixture bug: the drive judged one criterion — the criterion "
            "dimension below cannot be distinguished from a judge aggregate"
        )

        emitted = judge_signals(store, run_id)
        cells = dict(emitted)

        # The dimensionality: the emitted cells are EXACTLY the (criterion, judge)
        # pairs the run judged. A run-level aggregate — one cell of six numbers —
        # is emitted and fails here all the same.
        assert set(cells) == judged_pairs, (
            f"the signals are emitted for {sorted(map(str, cells))} but the run "
            f"judged {sorted(map(str, judged_pairs))} — the dimensionality is the "
            "contract: 'contract violations concentrated on one judge' is "
            "locatable only from a (criterion, judge) keying, and a metric "
            "emitted without the judge dimension fails this case even though it "
            "is emitted (CT-JUDGE-16)"
        )

        # The names: every cell carries all six signals, under their exact names.
        for (criterion_id, judge_id), cell in sorted(cells.items()):
            assert set(cell) == set(JUDGE_SIGNAL_FIELDS), (
                f"{criterion_id}/{judge_id} emits {sorted(cell)}; CT-JUDGE-16 "
                f"declares {sorted(JUDGE_SIGNAL_FIELDS)} — under their exact "
                "names, per criterion and per judge"
            )
            for field in JUDGE_SIGNAL_FIELDS:
                assert cell[field] is not None, (
                    f"{criterion_id}/{judge_id} carries {field} = None — a "
                    "declared signal with no value is the declared-but-unmeasured "
                    "shape that reads as monitoring while measuring nothing "
                    "(CT-JUDGE-16, CLAUDE.md seam 4)"
                )
    finally:
        store.close()
