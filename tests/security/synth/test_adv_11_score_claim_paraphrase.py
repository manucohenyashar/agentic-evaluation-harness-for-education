"""`ADV-11` — the attack on the score-claim prohibition (`M-SYNTH`, TS-37, security).

**Attacker goal:** get a score into the narrative. The input is verdicts engineered to
elicit "one of the strongest answers in the class" (the plan's named attack, fed
verbatim) and similar paraphrases — the rewordings a helpful model produces when a
prompt says "don't state a score" but the summary instinct survives.

**Pass = correct handling or visible failure.** Two tiers of assertion, exactly as the
plan's row states:

- **Hard:** the verbatim pattern-matched claim is rejected — it reaches no stored row
  (the check caught it and the re-request stored the replacement). This is the part
  the configured `SYNTH_SCORE_CLAIM_PATTERNS` owe: the plan's own example must not
  store.
- **Measured, not gated (§2.3 Q-06):** paraphrases will get through. The case computes
  the catch rate the report discloses — rejections over claim-bearing attempts — and
  asserts only that it is a measured, bounded quantity, never that it is 1.0. The
  measured rate is the number §2.3 Q-06 tracks; an assertion of zero paraphrase leaks
  here would be a test the next model upgrade silently breaks, and an assertion of a
  specific catch fraction would be a quality claim about a model the suite does not
  own.

Isolation: rung 2 — real SQLite, the capture provider at the model boundary. The
"verdicts engineered to elicit" half is realized at the only seam a fixture can reach:
the provider's replies ARE what the verdicts elicit, so the feed carries the attack
texts a verdict set of this shape produces, and the module's check is what stands
between them and the store.

Interface assumed of `#97`/`#98` (disclosed in `tests/support/synth_vocabulary.py`,
reconcile at landing): `SynthesisWorker(store, provider, model_ref)` with
`.synthesize_submission(...) -> SynthesisReport`; `narrative` rows carrying `text` and
`question_id`, read name-agnostically as row dicts.
"""

from __future__ import annotations

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

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

_SUBMISSION = "SYN-001"
_QUESTIONS = tuple(f"Q{q}" for q in range(1, 6))

#: The plan's named attack, verbatim — the claim the configured patterns MUST catch.
VERBATIM_CLAIM = (
    "Question 1: the response states the hypothesis; this is one of the strongest "
    "answers in the class."
)

#: Paraphrase attempts — rewordings that carry the same verdict in prose the patterns
#: may or may not reach. The case measures what gets through; it does not gate.
PARAPHRASES = {
    "Q2": "Question 2: the derivation is complete; few submissions in this cohort "
          "matched this standard of reasoning.",
    "Q3": "Question 3: the table is cited throughout; an exemplary submission "
          "overall.",
    "Q4": "Question 4: the conclusion is well argued; this sets the standard the "
          "rest of the cohort should aim at.",
}


def test_adv_11_pattern_matched_claims_rejected_and_the_rate_measured(tmp_data_dir):
    """`ADV-11` — the verbatim attack stores nothing; the paraphrase catch rate is
    measured and reported, not asserted."""
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)

    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = seed_run(store, submissions=(_SUBMISSION,), criteria=FIVE_QUESTION_CRITERIA)
        seed_scored_submission(store, run_id, _SUBMISSION, complete_questions=set(_QUESTIONS))

        # Every attack question claims on its FIRST attempt and yields a clean
        # replacement on its second; Q5 and L2 are clean throughout.
        replies = []
        for question in _QUESTIONS:
            if question == "Q1":
                first, second = VERBATIM_CLAIM, (
                    f"Question 1: the response states the hypothesis and cites the "
                    f"worked steps for this question."
                )
            elif question in PARAPHRASES:
                first, second = PARAPHRASES[question], (
                    f"Question {question[1:]}: the response states the hypothesis and "
                    f"cites the worked steps for this question."
                )
            else:
                first, second = (
                    f"Question {question[1:]}: the response states the hypothesis and "
                    f"cites the worked steps for this question.", None
                )
            replies.append(narrative_completion(first, (f"{question}C1", f"{question}C2")))
            if second is not None:
                replies.append(narrative_completion(second, (f"{question}C1", f"{question}C2")))
        replies.append(narrative_completion("Overall: the submission works through each question in turn."))
        provider = CaptureProvider(replies)

        report = Worker(store, provider, synth_ref()).synthesize_submission(run_id, _SUBMISSION)

        # --- hard half: the pattern-matched claim reaches no stored row ------------
        rows = store.cohort(COHORT_ID).query(
            "SELECT * FROM narrative WHERE run_id = :r", r=run_id
        )
        q1_rows = [row for row in rows if row.get("question_id") == "Q1"]
        assert len(q1_rows) == 1, (
            f"{len(q1_rows)} stored narratives for Q1 — a rejected claim must leave "
            "exactly its replacement, not one row per attempt"
        )
        stored = q1_rows[0].get("text") or ""
        assert VERBATIM_CLAIM not in stored, (
            f"the plan's named attack is IN the stored narrative: {stored!r} — the "
            "verbatim claim 'one of the strongest answers in the class' is exactly "
            "what SYNTH_SCORE_CLAIM_PATTERNS exist to reject; storing it ships the "
            "student a second, competing grade (RISK-19, FR-SYNTH-03)"
        )

        # --- measured half: the catch rate is disclosed, bounded, and NOT gated ----
        attempts = 1 + len(PARAPHRASES)  # claim-bearing replies fed
        caught = report.rejected_score_claims
        assert isinstance(caught, int) and caught >= 1, (
            f"report.rejected_score_claims={caught!r} — the verbatim attack alone must "
            "be counted as rejected; a report that does not count rejections cannot "
            "measure the prohibition's coverage"
        )
        rate = caught / attempts
        assert 0.0 < rate <= 1.0, (
            f"the measured catch rate {rate:.2f} ({caught}/{attempts}) is not a rate — "
            "§2.3 Q-06: paraphrase leakage is MEASURED, and the measurement must be a "
            "bounded proportion of the attempts fed, never asserted to be perfect"
        )
        # The rate itself is deliberately not asserted further: whatever it measures,
        # it is the number the administration reports (§2.3 Q-06), and this file's
        # hard guarantee is the verbatim rejection above.
    finally:
        store.close()
