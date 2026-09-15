"""`TS-88` (issue #382) — `TC-AGG-21` and `TC-AGG-24`: `write_score` stores every field of the
`CriterionScore` it is given, and the stored row alone reconstructs the confidence under all six
integrity signals.

`TC-AGG-21` (`FR-AGG-15`, P0; RISK-41/42 Critical), rung 2. Preconditions: verdicts with bands
`(2,3,3)` on a 4-band criterion; `aggregate` yields `s`. Steps: `write_score(tx, "RA", "S1", s,
signals)` inside `with handle.transaction() as tx`, then read the row back. Oracle: field-by-field
equality with `s` and `signals`. Expected: keyed `(RA,S1,C1)`, `band = modal_band = s.modal_band`,
`band_spread = 1`, and `points`, `judge_count = 3`, `agreement`, `confidence`, `confidence_base`,
`routing`, `state` equal to `s`; all six integrity flags stored; `caps_fired` the JSON list (`[]`
when none, never NULL). Variants: `extractor_disagreement=None` → NULL (distinguishable from 0);
`described_evidence=False` → 0; outside a transaction → raises, nothing written; a second identical
call → one row; a second call with a changed band → one row, updated.

`TC-AGG-24` (`FR-AGG-13` amended, P1), rung 2: `write_score` with `described_evidence=True`,
`extractor_disagreement=True` and each of the four base flags toggled one at a time → all six
columns stored, and `recompute_confidence(row) == s.confidence` from the stored row alone, which
closes `TC-AGG-C15`'s residual.

**Why the panel `(2,3,3)`.** Its confidence base is 0.6 (hand-checked against `aggregate`), so the
`described_evidence` cap (0.5) and the `extractor_disagreement` cap (0.4) both *bind*. Under a
base below 0.4 neither would, and a re-derivation that ignores the two new columns would still read
equal — the residual this case exists to close would pass vacuously.

**Interface assumed** (design delta §3.5), for #360 to reconcile deliberately:

| Name | Assumption |
|---|---|
| `aeh.agg.write_score(tx, run_id, submission_id, score, signals)` | as FR-AGG-15 declares; `signals` an `aeh.integ.IntegritySignals` |
| `caps_fired` | a JSON list of the cap names that bound: `[]` for favourable signals; when the extractor-disagreement cap binds, an entry naming it (`extractor_disagreement`, or a suffixed form like TC-AGG-23's `uncited_cap`) |
| `recompute_confidence(row, criterion)` | the shipped re-derivation (`agg.py`), called on the stored row — the plan's `recompute_from_row(row)` |
| "outside a transaction" | `write_score` handed the handle rather than a transaction raises; inside a transaction that rolls back, no row survives |

**Blocker note.** The key is `write_score`; TC-AGG-24 additionally needs `recompute_confidence`
to read the two new columns (FR-AGG-13 amended), which is #360's scope too — if `write_score` lands
first, un-marking reveals the residual rather than hiding it.

The run is a real `run` row (`seed_run`), so the key names an existing run; its id stands in for the
plan's literal `RA`.

**Written ahead of implementation: yes** — keyed on `aeh.agg:write_score` (#360, which depends on
#359's rebuilt table).
"""

from __future__ import annotations

import json

import pytest

import aeh.agg  # noqa: F401 — the full migration chain
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

from aeh.agg import AGG_CAP_TABLE, aggregate, recompute_confidence
from aeh.integ import IntegritySignals
from aeh.store import open_store
from tests.support.agg_vocabulary import band, criterion, panel
from tests.support.impl import AGG_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

ISSUE = "#360"

CRITERION = criterion(
    [band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0), band("B3", 3, 6.0)],
    criterion_id="C1",
)
PANEL = panel(("B2", 2), ("B3", 3), ("B3", 3))
FAVOURABLE = dict(spans_verified=True, evidence_present=True, sufficiency_flag=False,
                  ocr_overlap_risk=False, described_evidence=False, extractor_disagreement=False)


def _signals(**overrides) -> IntegritySignals:
    return IntegritySignals(**{**FAVOURABLE, **overrides})


def _world(tmp_data_dir):
    store = open_store(tmp_data_dir)
    _orch, run_id, _version = seed_run(
        store, submissions=("S1",),
        criteria=({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},),
    )
    return store, run_id


def _rows(store, run_id):
    return [dict(r) for r in store.cohort(ORCH_COHORT_ID).query(
        "SELECT * FROM criterion_score WHERE run_id = :r AND submission_id = 'S1' "
        "AND criterion_id = 'C1'", r=run_id)]


def _write(store, write_score, run_id, score, signals):
    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        write_score(tx, run_id, "S1", score, signals)


_FLAGS = ("spans_verified", "evidence_present", "sufficiency_flag", "ocr_overlap_risk",
          "described_evidence", "extractor_disagreement")


def _stored_flag(value):
    return None if value is None else int(bool(value))


# --- TC-AGG-21 -----------------------------------------------------------------------------


def test_tc_agg_21_write_score_stores_every_field_of_the_score_and_signals(tmp_data_dir):
    """`TC-AGG-21` — field-by-field equality, `caps_fired` `[]`, one row per key."""
    write_score = require(AGG_MODULE, "write_score", issue=ISSUE)
    store, run_id = _world(tmp_data_dir)
    try:
        signals = _signals()
        s = aggregate(PANEL, CRITERION, signals)
        assert (s.band, s.modal_band, s.band_spread, s.judge_count) == ("B3", "B3", 1, 3), (
            "precondition: (2,3,3) aggregates to band B3, spread 1, three judges"
        )
        _write(store, write_score, run_id, s, signals)

        (row,) = _rows(store, run_id)
        assert (row["run_id"], row["submission_id"], row["criterion_id"]) == (run_id, "S1", "C1")
        assert row["band"] == row["modal_band"] == s.modal_band
        assert row["band_spread"] == 1
        for field in ("points", "judge_count", "agreement", "confidence", "confidence_base",
                      "routing", "state"):
            assert row[field] == getattr(s, field), (
                f"stored {field}={row[field]!r}, the score carried {getattr(s, field)!r}"
            )
        for flag in _FLAGS:
            assert row[flag] == _stored_flag(getattr(signals, flag)), f"flag {flag} not stored"
        assert row["caps_fired"] is not None, "caps_fired is NULL; it must be a JSON list"
        assert json.loads(row["caps_fired"]) == [], "favourable signals fired a cap"

        # Idempotent on the key.
        _write(store, write_score, run_id, s, signals)
        assert len(_rows(store, run_id)) == 1, "a repeated write_score duplicated the row"

        # A changed band updates the one row.
        lower = aggregate(panel(("B2", 2), ("B2", 2), ("B3", 3)), CRITERION, signals)
        _write(store, write_score, run_id, lower, signals)
        rows = _rows(store, run_id)
        assert len(rows) == 1 and rows[0]["band"] == "B2", f"the re-write did not update: {rows}"
    finally:
        store.close()


def test_tc_agg_21_variant_null_extractor_disagreement_stays_distinct_from_false(tmp_data_dir):
    """`extractor_disagreement=None` → NULL; `described_evidence=False` → 0."""
    write_score = require(AGG_MODULE, "write_score", issue=ISSUE)
    store, run_id = _world(tmp_data_dir)
    try:
        signals = _signals(extractor_disagreement=None, described_evidence=False)
        s = aggregate(PANEL, CRITERION, signals)
        _write(store, write_score, run_id, s, signals)
        (row,) = _rows(store, run_id)
        assert row["extractor_disagreement"] is None, (
            f"'not measured' was stored as {row['extractor_disagreement']!r}, not NULL"
        )
        assert row["described_evidence"] == 0
    finally:
        store.close()


def test_tc_agg_21_variant_a_binding_cap_is_named_in_caps_fired(tmp_data_dir):
    """`caps_fired` names the cap that bound: `extractor_disagreement` caps 0.6 to 0.4."""
    write_score = require(AGG_MODULE, "write_score", issue=ISSUE)
    store, run_id = _world(tmp_data_dir)
    try:
        signals = _signals(extractor_disagreement=True)
        s = aggregate(PANEL, CRITERION, signals)
        assert s.confidence == AGG_CAP_TABLE["extractor_disagreement"], "precondition: cap binds"
        _write(store, write_score, run_id, s, signals)
        (row,) = _rows(store, run_id)
        fired = json.loads(row["caps_fired"])
        # The cap's exact spelling is #360's to fix (AGG_CAP_TABLE's key, or a `_cap` suffix as
        # TC-AGG-23's `uncited_cap`); the entry must name the extractor-disagreement cap.
        assert isinstance(fired, list) and any("extractor_disagreement" in str(n) for n in fired), (
            f"caps_fired={fired!r} does not name the binding extractor_disagreement cap"
        )
    finally:
        store.close()


def test_tc_agg_21_variant_outside_a_transaction_raises_and_writes_nothing(tmp_data_dir):
    """"Outside a transaction → raises, nothing written", read through #360's own acceptance
    criterion and CT-AGG-19: handed something that is not a transaction (the handle itself),
    `write_score` raises and writes nothing; and a `write_score` inside a transaction that then
    raises leaves the transaction to roll back whole — no row.

    (A committed `Tx` object is not used as "outside": the store's `Tx` keeps no live/closed
    state, so a correct caller's-transaction writer could not refuse it — a store gap, not
    `write_score`'s.)"""
    write_score = require(AGG_MODULE, "write_score", issue=ISSUE)
    store, run_id = _world(tmp_data_dir)
    try:
        signals = _signals()
        s = aggregate(PANEL, CRITERION, signals)
        handle = store.cohort(ORCH_COHORT_ID)
        with pytest.raises(Exception):
            write_score(handle, run_id, "S1", s, signals)
        assert _rows(store, run_id) == [], "write_score handed a handle, not a tx, wrote a row"

        class _Abort(Exception):
            pass

        with pytest.raises(_Abort):
            with handle.transaction() as tx:
                write_score(tx, run_id, "S1", s, signals)
                raise _Abort()
        assert _rows(store, run_id) == [], (
            "write_score wrote outside the caller's transaction: its row survived the rollback"
        )
    finally:
        store.close()


# --- TC-AGG-24 -----------------------------------------------------------------------------


_TC_AGG_24_SIGNALS = [
    ("described_evidence", dict(described_evidence=True)),
    ("extractor_disagreement", dict(extractor_disagreement=True)),
    ("both-new", dict(described_evidence=True, extractor_disagreement=True)),
    ("both-new+spans_verified", dict(described_evidence=True, extractor_disagreement=True,
                                     spans_verified=False)),
    ("both-new+evidence_present", dict(described_evidence=True, extractor_disagreement=True,
                                       evidence_present=False)),
    ("both-new+sufficiency_flag", dict(described_evidence=True, extractor_disagreement=True,
                                       sufficiency_flag=True)),
    ("both-new+ocr_overlap_risk", dict(described_evidence=True, extractor_disagreement=True,
                                       ocr_overlap_risk=True)),
]


@pytest.mark.parametrize("overrides", [o for _, o in _TC_AGG_24_SIGNALS],
                         ids=[name for name, _ in _TC_AGG_24_SIGNALS])
def test_tc_agg_24_the_stored_row_alone_reconstructs_confidence_under_all_six_signals(
    tmp_data_dir, overrides
):
    """`TC-AGG-24` — six columns stored; `recompute_confidence(row) == s.confidence`."""
    write_score = require(AGG_MODULE, "write_score", issue=ISSUE)
    store, run_id = _world(tmp_data_dir)
    try:
        signals = _signals(**overrides)
        s = aggregate(PANEL, CRITERION, signals)
        _write(store, write_score, run_id, s, signals)
        (row,) = _rows(store, run_id)
        for flag in _FLAGS:
            assert row[flag] == _stored_flag(getattr(signals, flag)), f"flag {flag} not stored"
        assert recompute_confidence(row, CRITERION) == s.confidence, (
            f"the stored row re-derives {recompute_confidence(row, CRITERION)!r}, the score was "
            f"{s.confidence!r} — a cap keyed on a signal the row does not carry (TC-AGG-C15)"
        )
    finally:
        store.close()
