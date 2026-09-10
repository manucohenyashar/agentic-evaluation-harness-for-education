"""`TC-JUDGE-16` — an uncited verdict is a MARKED verdict, not a discarded one
(`FR-JUDGE-12`, `CT-JUDGE-06`; issue #83 (TS-31)).

A judge reply with an EMPTY span inventory is not a refusal: the citation gate passes
it vacuously (there is nothing to verify), the dispatch accepts it with `uncited`
marked, and `persist` writes the row — `uncited = 1`, `cited_spans` NULL, and the band,
ordinal and confidence the row always carries. The row is not discarded, and the mark
travels: M-AGG reads it and applies the uncited multiplier (§3.12's `× 0.80`), so an
uncited verdict reaches the aggregate as a DOWNGRADED score, never as silence.

Three legs:

- the **dispatch** leg, at the real boundary: an uncited reply through a REAL store
  produces a `ScoringResult` with `uncited=True` and an empty span inventory, beside a
  cited control whose result is marked cited;
- the **persist** leg: the verdict rows as M-AGG consumes them — the uncited row's
  `cited_spans` is SQL NULL (not an empty JSON array), `uncited` is 1, and nothing the
  row owes (band, ordinal, self_confidence) is dropped;
- the **M-AGG bridge**: the same verdict aggregated cited vs uncited differs by
  EXACTLY the uncited multiplier — the consumption contract at the judge boundary
  (#92's suite owns the multiplier's unit behaviour; this pins the handoff).

Isolation: rung 2 — real store, real package, real extraction leg, judge replies
through `RecordedFixtureProvider`. No model, no network.
"""

from __future__ import annotations

import json

import pytest

from aeh.store import open_store
from tests.support.agg_vocabulary import (
    agg_config,
    band as agg_band,
    criterion as agg_criterion,
    favourable_signals,
    verdict as agg_verdict,
)
from tests.support.conf_builders import EDGE_JUDGE
from tests.support.extract_vocabulary import JUDGE_ISSUE
from tests.support.impl import AGG_MODULE, JUDGE_MODULE, require
from tests.support.judge_run import (
    CONTROL_BAND,
    CONTROL_CONFIDENCE,
    byte_span,
    canonical_document,
    default_pages,
    judge_world,
    reply_text,
    verdict_rows,
    warm_judged_modules,
)

pytestmark = [pytest.mark.integration]

#: The two-submission batch: the first is judged on a cited control reply, the second
#: on the same verdict with an EMPTY span inventory — the uncited mark's own case.
CITED_SUBMISSION = "s-16-cited"
UNCITED_SUBMISSION = "s-16-uncited"

#: The one judge of the world's panel — replies are addressed by its build id.
JUDGE_BUILD = EDGE_JUDGE.build_id


def _reply_for(submission_id: str, _judge_build: str):
    """The controlled condition: the cited submission answers with the control reply
    citing its document's own byte offsets; the uncited submission answers the SAME
    band at the SAME confidence with an empty inventory."""
    pages = default_pages(submission_id)
    document = canonical_document("\n".join(pages))
    spans = [byte_span(document, page) for page in pages]
    return reply_text(
        CONTROL_BAND,
        CONTROL_CONFIDENCE,
        build_id=JUDGE_BUILD,
        cited_spans=None if submission_id == UNCITED_SUBMISSION else spans,
    )


def _world(tmp_data_dir, make_fixture_provider):
    warm_judged_modules()
    store = open_store(tmp_data_dir / "data")
    provider = make_fixture_provider()
    world = judge_world(
        store,
        provider,
        submissions=(CITED_SUBMISSION, UNCITED_SUBMISSION),
        panel=1,
        reply_for=_reply_for,
    )
    return store, world


# --- the dispatch leg -------------------------------------------------------------------------------


def test_tc_judge_16_a_an_empty_span_inventory_is_a_marked_verdict_not_a_refusal(
    tmp_data_dir, make_fixture_provider
):
    """The uncited reply dispatches (the citation gate has nothing to refuse), and the
    result carries the mark: `uncited=True` with an empty span inventory — beside the
    cited control's `uncited=False`, proving the mark is about THIS reply's inventory,
    not a constant."""
    _store, world = _world(tmp_data_dir, make_fixture_provider)
    assert not world["failures"], (
        f"an uncited reply must not refuse: {world['failures']!r}"
    )
    uncited_result = world["results"][(UNCITED_SUBMISSION, JUDGE_BUILD)]
    cited_result = world["results"][(CITED_SUBMISSION, JUDGE_BUILD)]
    assert uncited_result.uncited is True
    assert uncited_result.cited_spans == ()
    assert uncited_result.band == CONTROL_BAND
    assert cited_result.uncited is False
    assert len(cited_result.cited_spans) == 2, (
        f"the cited control cites its document's spans: {cited_result.cited_spans!r}"
    )


# --- the persisted rows M-AGG consumes ------------------------------------------------------------


def test_tc_judge_16_b_the_uncited_verdict_persists_with_a_null_span_inventory(
    tmp_data_dir, make_fixture_provider
):
    """The uncited verdict's row EXISTS — the mark is not a discard: `uncited` is 1,
    `cited_spans` is SQL NULL (not an empty JSON array), and the band, its declared
    ordinal and the self-confidence are all present, exactly the row shape M-AGG
    reads. The cited control's row is the contrast: `uncited` 0, spans persisted."""
    store, world = _world(tmp_data_dir, make_fixture_provider)
    for key in ((CITED_SUBMISSION, JUDGE_BUILD), (UNCITED_SUBMISSION, JUDGE_BUILD)):
        unit = world["score_units"][key]
        rows = verdict_rows(store, unit.work_id)
        assert len(rows) == 1, (
            f"the {key[0]} verdict persisted exactly one row, got {len(rows)}"
        )
        row = rows[0]
        assert row["band"] == CONTROL_BAND
        assert row["band_ordinal"] is not None and row["self_confidence"] is not None
        if key[0] == UNCITED_SUBMISSION:
            assert row["uncited"] == 1, (
                f"the uncited verdict's mark is 1 on the row: {dict(row)!r}"
            )
            assert row["cited_spans"] is None, (
                f"an uncited verdict persists a NULL span inventory, not an empty "
                f"one: {dict(row)!r}"
            )
        else:
            assert row["uncited"] == 0
            persisted = row["cited_spans"]
            decoded = json.loads(
                persisted.decode("utf-8")
                if isinstance(persisted, (bytes, bytearray))
                else persisted
            )
            assert len(decoded) == 2, (
                f"the cited row persists its span inventory: {decoded!r}"
            )


def test_tc_judge_16_c_m_agg_consumes_the_mark_as_the_exact_uncited_multiplier(
    tmp_data_dir, make_fixture_provider
):
    """The bridge to the consumer: the SAME verdict, aggregated cited and uncited,
    differs by EXACTLY the uncited multiplier — the mark downgrades the score to
    ×`AGG_UNCITED_MULTIPLIER`, it does not discard the verdict and it does not gate
    the score away. (The multiplier's own unit behaviour is #92's suite; this pins
    the consumption contract at the judge boundary.)"""
    aggregate = require(AGG_MODULE, "aggregate", issue="#91")
    multiplier = require(AGG_MODULE, "AGG_UNCITED_MULTIPLIER", issue="#91")
    criterion = agg_criterion(
        (agg_band("emerging", 0, 0.0), agg_band("secure", 1, 10.0)),
        scoring_model="holistic",
        criterion_id="C1",
    )
    cited = aggregate(
        [agg_verdict(CONTROL_BAND, 1, cited=True, self_confidence=CONTROL_CONFIDENCE)],
        criterion,
        favourable_signals(),
        config=agg_config(),
    )
    uncited = aggregate(
        [agg_verdict(CONTROL_BAND, 1, cited=False, self_confidence=CONTROL_CONFIDENCE)],
        criterion,
        favourable_signals(),
        config=agg_config(),
    )
    ratio = uncited.confidence_base / cited.confidence_base
    assert ratio == pytest.approx(multiplier), (
        f"the uncited mark moved the confidence by {ratio}, expected exactly the "
        f"uncited multiplier {multiplier} (FR-JUDGE-12: marked, downgraded, never "
        f"discarded)"
    )
    assert uncited.band == cited.band, (
        "the mark downgrades the confidence, it does not rewrite the band: "
        f"{uncited.band!r} vs {cited.band!r}"
    )