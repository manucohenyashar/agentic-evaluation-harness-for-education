"""`TC-SYNTH-C12` — the four quality signals, under their exact names (§6.11.13).

`CT-SYNTH-12`'s observability clause: synthesis emits the **synthesis failure
rate**, the **score-claim rejection rate**, the **mean narrative length**, and the
**citation-validity rate on the sampled subset** — under those exact names. The
clause states the reason and the case preserves it: narrative quality is the output
teachers and students value most and the one **most likely to go unmeasured**
(`NFR-SYNTH-01`), so the names are contract — a rename or a drop is the unmeasured
state arriving quietly.

Two oracles:

- **Name emission** — the report's field set carries the four exact names, and on a
  real drive each is a measured value (never `None` where the sample is non-empty).
  The mean is pinned by arithmetic: it equals the mean word count over the STORED
  narratives, so a mean computed over a subset (or over the displayed subset, which
  excludes flagged rows — #98's disclosed composition) drifts red.
- **Sampling runs** — the quality sample is drawn on every administration, not a
  configurable that defaults off: the default rate (0.25) samples 2 of 6 stored
  narratives, and the env knob at 0 still draws the floor of one. The floor is the
  shipped semantics and it is the clause's point — `NFR-SYNTH-01` says the rates are
  "measured on a sample every administration", so a configuration that turns the
  sample off would break the measurement, not tune it. Disclosed here because it is
  a one-way ratchet: the knob can shrink the sample, never zero it.

Relationship to shipped cases: `tests/integration/synth/
test_synthesis_observability.py` (`TC-SYNTH-12`) holds the counters (calls,
narratives, failures) and the sample's existence on one drive; this case pins the
four RATE names as an exact-name contract and the sampling floor.

Isolation: rung 2 — real SQLite, `CaptureProvider` at the model boundary.
"""

from __future__ import annotations

import dataclasses

import pytest

from aeh.store import open_store
from tests.support.impl import SYNTH_MODULE, require
from tests.support.orch_run import seed_run
from tests.support.synth_vocabulary import (
    COHORT_ID,
    FIVE_QUESTION_CRITERIA,
    SYNTH_ISSUE,
    WORKER,
    CaptureProvider,
    narrative_completion,
    seed_scored_submission,
    synth_ref,
)

pytestmark = [pytest.mark.contract]

_QUESTIONS = tuple(f"Q{q}" for q in range(1, 6))
_RATE_ENV = "HARNESS_SYNTH_SAMPLE_RATE"

#: The four signals `CT-SYNTH-12` names, under the exact names the report owes.
SIGNAL_NAMES = (
    "synthesis_failure_rate",
    "score_claim_rejection_rate",
    "mean_narrative_length",
    "citation_validity_rate",
)


def _clean(question: str) -> str:
    return (
        f"Question {question[1:]}: the response states the hypothesis and cites "
        "the worked steps for this question."
    )


def _replies() -> list:
    replies = [
        narrative_completion(_clean(q), (f"{q}C1", f"{q}C2")) for q in _QUESTIONS
    ]
    replies.append(narrative_completion("Overall: the submission works through each question in turn."))
    return replies


def _seeded_store(tmp_data_dir, submissions=("SYN-001",)):
    """One run over all named submissions (`seed_run` seeds its cohort once per
    store, so the second submission rides the same run), each scored — the runs map
    gives the drive a per-submission handle."""
    store = open_store(tmp_data_dir)
    _, run_id, _ = seed_run(
        store, submissions=submissions, criteria=FIVE_QUESTION_CRITERIA
    )
    for submission_id in submissions:
        seed_scored_submission(
            store, run_id, submission_id, complete_questions=set(_QUESTIONS)
        )
    runs = {submission_id: run_id for submission_id in submissions}
    return store, runs


def _stored_texts(store, run_id: str, submission_id: str) -> set[str]:
    rows = store.cohort(COHORT_ID).query(
        "SELECT text FROM narrative WHERE run_id = :r AND submission_id = :s",
        r=run_id, s=submission_id,
    )
    return {row["text"] for row in rows}


def test_tc_synth_c12_the_four_signals_are_emitted_under_their_exact_names(
    tmp_data_dir,
):
    """`TC-SYNTH-C12` (P1) — `SynthesisReport` carries all four signals under the
    exact names the clause uses, and on a real drive each is a measured value: the
    two rates are floats in [0, 1], the mean equals the stored narratives' mean word
    count by arithmetic, and the citation rate is measured on the sampled subset
    (non-`None` exactly because the sample is non-empty)."""
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
    SynthesisReport = require(SYNTH_MODULE, "SynthesisReport", issue=SYNTH_ISSUE)

    store, runs = _seeded_store(tmp_data_dir)
    try:
        report = Worker(store, CaptureProvider(_replies()), synth_ref()).synthesize_submission(
            runs["SYN-001"], "SYN-001"
        )

        field_names = {field.name for field in dataclasses.fields(SynthesisReport)}
        missing = [name for name in SIGNAL_NAMES if name not in field_names]
        assert not missing, (
            f"SynthesisReport lacks {missing} — CT-SYNTH-12 emits the synthesis "
            "failure rate, the score-claim rejection rate, the mean narrative "
            "length and the citation-validity rate under those exact names "
            "(NFR-SYNTH-01): narrative quality is the output teachers and students "
            "value most and the one most likely to go unmeasured, so a renamed or "
            "dropped signal is the unmeasured state arriving quietly"
        )

        for name in SIGNAL_NAMES:
            value = getattr(report, name)
            assert value is not None, (
                f"{name} is None on a completed drive — the signal must be "
                "EMITTED, not merely declared (CT-SYNTH-12)"
            )
        for rate_name in (
            "synthesis_failure_rate", "score_claim_rejection_rate",
            "citation_validity_rate",
        ):
            rate = getattr(report, rate_name)
            assert 0.0 <= rate <= 1.0, (
                f"{rate_name}={rate!r} is outside [0, 1] — the emitted value must "
                "be a rate, not a count wearing a rate's name"
            )

        # The mean, pinned by arithmetic over the STORED narratives (5 L1 + 1 L2):
        # a mean computed over a different set — the displayed subset, the sample,
        # the attempts rather than the stores — drifts from this number.
        stored = _stored_texts(store, runs["SYN-001"], "SYN-001")
        expected_mean = sum(len(text.split()) for text in stored) / len(stored)
        assert report.mean_narrative_length == pytest.approx(expected_mean), (
            f"mean_narrative_length={report.mean_narrative_length!r} but the stored "
            f"narratives' mean word count is {expected_mean!r} — the mean describes "
            "what synthesis PRODUCED (#98's disclosure), not a subset a consumer "
            "sees"
        )

        # The sampled-subset pin: the citation rate is measured ON the sample, which
        # is why it is a float here — the sample is non-empty, and #98's contract is
        # that the citation rates are None exactly when the sample is empty.
        assert report.sample and report.sample_size == len(report.sample), (
            f"sample_size={report.sample_size!r} vs {len(report.sample)} sampled "
            "texts — the size must describe the sample actually drawn"
        )
        assert set(report.sample) <= stored, (
            "the sample holds text synthesis never stored — the quality sample is "
            "drawn from the stored narratives, so an off-table sample is measured "
            "against nothing"
        )
    finally:
        store.close()


def test_tc_synth_c12_the_quality_sample_runs_each_administration(
    tmp_data_dir, monkeypatch
):
    """`TC-SYNTH-C12` (P1) — the sampling actually runs: the default drive draws 2 of
    the 6 stored narratives (rate 0.25, rounded), and the env knob at 0 STILL draws
    the floor of one — sampling cannot be configured off. That floor is disclosed,
    not incidental: NFR-SYNTH-01's "measured on a sample every administration" makes
    a sampleless administration a measurement gap, so the knob tunes the sample's
    size and never its existence."""
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
    default_rate = require(SYNTH_MODULE, "SYNTH_SAMPLE_RATE", issue=SYNTH_ISSUE)

    store, runs = _seeded_store(tmp_data_dir, submissions=("SYN-001", "SYN-002"))
    try:
        # Default administration: 6 stored narratives, rate 0.25 → round(6 * 0.25)
        # = 2 drawn (rounded-half-up: 1.5 + 0.5). A drive that drew 0 would make
        # every downstream rate a None, which is the unmeasured state.
        report = Worker(store, CaptureProvider(_replies()), synth_ref()).synthesize_submission(
            runs["SYN-001"], "SYN-001"
        )
        stored = _stored_texts(store, runs["SYN-001"], "SYN-001")
        assert len(stored) == 6, (
            f"{len(stored)} stored narratives — the sample arithmetic below needs "
            "the full two-level drive"
        )
        assert report.sample_size == 2, (
            f"sample_size={report.sample_size!r} at the default rate "
            f"{default_rate!r} over 6 narratives — the sample must actually run "
            "each administration (CT-SYNTH-12), not exist as a configurable that "
            "defaults off"
        )
        assert len(report.sample) == report.sample_size and set(report.sample) <= stored, (
            "the drawn sample must be real stored narrative texts, sized to "
            "sample_size"
        )

        # The knob at 0: the floor of one holds — the sample shrinks, never vanishes.
        monkeypatch.setenv(_RATE_ENV, "0")
        report_zero = Worker(
            store, CaptureProvider(_replies()), synth_ref()
        ).synthesize_submission(runs["SYN-002"], "SYN-002")
        assert report_zero.sample_size == 1 and report_zero.sample, (
            f"sample_size={report_zero.sample_size!r} with the rate knob at 0 — "
            "the floor of one holds: sampling cannot be configured off "
            "(NFR-SYNTH-01's 'every administration'), only narrowed"
        )
    finally:
        store.close()
