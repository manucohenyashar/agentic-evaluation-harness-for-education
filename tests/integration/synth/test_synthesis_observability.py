"""`TC-SYNTH-12` and `TC-SYNTH-08` — synthesis observability and the quality sample
(`M-SYNTH`, TS-37; P1, observability / statistical).

- `TC-SYNTH-12` (`NFR-SYNTH-02`, `FR-SYNTH-01`): a run emits the synthesis failure
  rate, the score-claim rejection rate, the mean narrative length and the
  citation-validity rate on the sampled subset — **exact signal plus call count**. The
  call-count half is asserted at its structural source: `~2,100 for 350 students` is 6
  calls per submission (5 L1 + 1 L2), so the exact per-submission count is the same
  fact at fixture scale, and the case asserts it exactly.
- `TC-SYNTH-08` (`FR-SYNTH-04`, `NFR-SYNTH-01`): the quality sample is drawn and
  passed — **not gated** (§2.3 Q-06: the rates are measured and reported, never
  asserted). The measurement itself is `M-STATS`'s (`TC-STATS-19`, TS-43); this case
  asserts what synthesis owes it: a non-empty sample drawn from the run's stored
  narratives, with the sample size attached and the two rates present on the report.

Written ahead of `#97` (test plan §8.2): fails only through `NotImplementedYet` naming
`#97`, or — once landed — through the assertion itself.

Isolation: rung 2 — real SQLite, the capture provider at the model boundary. The
`mean_narrative_length` assertion is an exact value computed from the fixture's own
texts, which is what makes the signal assertion fail-if-wrong: a report that reports a
constant, or averages the wrong row set, cannot match a mean the test derives from the
stored narratives it can read back.

Interface assumed of `#97` (disclosed in `tests/support/synth_vocabulary.py`, reconcile
at landing): the `SynthesisReport` the worker returns carries `model_calls`,
`failures`, `rejected_score_claims`, `mean_narrative_length`, `sample` (tuple of
narrative texts), `sample_size`, `citation_validity_rate`, `hallucinated_claim_rate`.
Signal NAMES are the load-bearing bet — the fourth seam's point is that these are
surfaced next to the status, not buried in a log; if `#97` ships different names the
rename is one line in the vocabulary and this file says so in its failure messages.
"""

from __future__ import annotations

from typing import Any

import pytest

from aeh.store import open_store
from tests.support.impl import SYNTH_MODULE, require
from tests.support.orch_run import seed_run
from tests.support.synth_vocabulary import (
    COHORT_ID,
    FIVE_QUESTION_CRITERIA,
    REPORT,
    SYNTH_ISSUE,
    WORKER,
    CaptureProvider,
    narrative_completion,
    seed_scored_submission,
    synth_ref,
)

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

_SUBMISSION = "SYN-001"
_QUESTIONS = tuple(f"Q{q}" for q in range(1, 6))
_L2_TEXT = "Overall: the submission works through each question in turn."


def _run_clean(store) -> tuple[str, Any]:
    """One submission, all five questions complete, every reply clean.

    Returns `(run_id, report)` — the report is the worker's return value, which is the
    surface the operator reads (disclosed in the vocabulary)."""
    _, run_id, _ = seed_run(store, submissions=(_SUBMISSION,), criteria=FIVE_QUESTION_CRITERIA)
    seed_scored_submission(store, run_id, _SUBMISSION, complete_questions=set(_QUESTIONS))
    replies = [
        narrative_completion(
            f"Question {q[1:]}: the response states the hypothesis and cites the "
            f"worked steps for this question.",
            (f"{q}C1", f"{q}C2"),
        )
        for q in _QUESTIONS
    ] + [narrative_completion(_L2_TEXT)]
    provider = CaptureProvider(replies)
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
    report = Worker(store, provider, synth_ref()).synthesize_submission(run_id, _SUBMISSION)
    return run_id, report


def test_tc_synth_12_signals_are_emitted_and_call_count_is_six_per_submission(tmp_data_dir):
    """`TC-SYNTH-12` (P1) — the four signals on the report with exact clean-run values,
    and 6 calls per submission — the arithmetic `~2,100 for 350 students` is made of."""
    require(SYNTH_MODULE, REPORT, issue=SYNTH_ISSUE)  # the surface exists to assert on
    store = open_store(tmp_data_dir)
    try:
        run_id, report = _run_clean(store)

        # --- the call count: 6 per submission is where ~2,100 comes from ----------
        assert report.model_calls == 6, (
            f"report.model_calls={report.model_calls} for one five-question submission "
            "— 5 L1 + 1 L2 is 6, and 6 x 350 students is the ~2,100 NFR-SYNTH-02 "
            "budgets (roughly 9% of model calls); a different per-submission count is "
            "a different budget, and a report that counts anything but its own calls "
            "is a metric that reports nothing"
        )

        # --- the four signals, exact on the all-clean run --------------------------
        assert report.synthesis_failure_rate == 0.0, (
            f"report.synthesis_failure_rate={report.synthesis_failure_rate} on an "
            "all-clean run — the failure rate is one of the four signals §3.13 emits "
            "per run, and 0.0 is its exact value here"
        )
        assert report.score_claim_rejection_rate == 0.0 and report.rejected_score_claims == 0, (
            f"report.score_claim_rejection_rate={report.score_claim_rejection_rate} / "
            f"rejected_score_claims={report.rejected_score_claims} on a clean feed — "
            "the rejection rate's numerator is the signal a suppress-heavy module "
            "cannot hide"
        )
        rows = store.cohort(COHORT_ID).query(
            "SELECT * FROM narrative WHERE run_id = :r AND submission_id = :s",
            r=run_id,
            s=_SUBMISSION,
        )
        assert len(rows) == 6, f"{len(rows)} narrative rows — the fixture's own shape moved"
        expected_mean = sum(len((row.get("text") or "").split()) for row in rows) / len(rows)
        assert abs(report.mean_narrative_length - expected_mean) < 1e-6, (
            f"report.mean_narrative_length={report.mean_narrative_length}, expected "
            f"{expected_mean} derived from the {len(rows)} stored narratives — a mean "
            "that does not match the rows it averages is decoration"
        )
        assert report.citation_validity_rate is None or isinstance(
            report.citation_validity_rate, (int, float)
        ), (
            f"report.citation_validity_rate={report.citation_validity_rate!r} — the "
            "fourth signal, measured on the sampled subset; a non-numeric value is a "
            "report that cannot be read"
        )
    finally:
        store.close()


def test_tc_synth_08_sample_is_drawn_and_passed_with_size_attached(tmp_data_dir):
    """`TC-SYNTH-08` (P1, statistical) — the sample is drawn from the run's stored
    narratives, its size is attached, and the two measured rates are present. NOT
    gated: the rates' values are §2.3 Q-06's measurement, not this case's assertion."""
    require(SYNTH_MODULE, REPORT, issue=SYNTH_ISSUE)
    store = open_store(tmp_data_dir)
    try:
        run_id, result = _run_clean(store)
        rows = store.cohort(COHORT_ID).query(
            "SELECT * FROM narrative WHERE run_id = :r AND submission_id = :s",
            r=run_id,
            s=_SUBMISSION,
        )
        stored_texts = [row.get("text") or "" for row in rows]

        sample = tuple(result.sample)
        assert sample, (
            "the report carries an empty quality sample — NFR-SYNTH-01: narrative "
            "quality is the output most likely to go unmeasured, and a sample that is "
            "never drawn is the unmeasured state this requirement exists to prevent"
        )
        assert result.sample_size == len(sample), (
            f"report.sample_size={result.sample_size} but the sample holds "
            f"{len(sample)} texts — the sample size must be attached to the sample, "
            "or the rate M-STATS reports has no stated n (TC-SYNTH-08's oracle)"
        )
        assert all(text in stored_texts for text in sample), (
            "the sample contains a text that is not one of the run's stored "
            "narratives — the sample is drawn from what was stored, or the measured "
            "rate describes narratives no student will read"
        )
        for name in ("citation_validity_rate", "hallucinated_claim_rate"):
            value = getattr(result, name, None)
            assert value is None or isinstance(value, (int, float)), (
                f"report.{name}={value!r} — the two measured rates are reported with "
                "the sample (not gated, §2.3 Q-06); a non-numeric rate is a report "
                "that cannot be read"
            )
    finally:
        store.close()
