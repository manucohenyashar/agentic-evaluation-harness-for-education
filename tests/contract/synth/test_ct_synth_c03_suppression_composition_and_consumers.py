"""`TC-SYNTH-C03` — the score-claim ladder's three states, and the L2 pin (§6.11.13).

`CT-SYNTH-03`'s handling path as three exact states — output matching
`SYNTH_SCORE_CLAIM_PATTERNS` is **rejected and re-requested once**, then **stored
with a flag**, then **suppressed from display** — plus the carry-forward this suite
owns: the composition pin. #98's L2 composition excludes a flagged L1 row
(`not row["score_claim_flag"]` in the L2 assembly) and no shipped TC executes that
line's effect; this file pins it: a twice-claiming question's prose must be absent
from the L2 prompt's syntheses while its clean siblings are present.

The state assertions, disclosed against the shipped siblings:

- `tests/integration/synth/test_score_claim_suppression.py` (`TC-SYNTH-05/06`)
  holds the 7-call shape, the zero-matches scan over stored text, and one flagged
  row. This case asserts the *differentials* it does not: the flagged row is stored
  **not discarded** (discarding would erase the rejection count `CT-SYNTH-12`
  alerts on), the flag partitions stored-vs-displayable exactly, and — the pin —
  the L2 composition honours the flag.
- `tests/security/synth/test_adv_11_score_claim_paraphrase.py` (ADV-11) owns the
  attack/paraphrase axis; this case owns the handling ladder's stored state.

The consumer obligation (`M-CONSOLE` and `M-GRADE` honour the flag, rung 3) is
written ahead of its consumers — both modules are unlanded — and registered in
`WRITTEN_AHEAD_BLOCKERS` under `"#100 suppression consumers (C03)"`.

Isolation: rung 2 — real SQLite, `CaptureProvider` at the model boundary (the
permitted model-boundary double; its canned replies are the only model behaviour in
the case).
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support.impl import (
    CONSOLE_MODULE,
    GRADE_MODULE,
    SYNTH_MODULE,
    require,
)
from tests.support.orch_run import seed_run
from tests.support.synth_vocabulary import (
    COHORT_ID,
    FIVE_QUESTION_CRITERIA,
    SCORE_CLAIM_FLAG,
    SYNTH_ISSUE,
    WORKER,
    CaptureProvider,
    narrative_completion,
    seed_scored_submission,
    synth_ref,
)

pytestmark = [pytest.mark.contract]

_SUBMISSION = "SYN-001"
_QUESTIONS = tuple(f"Q{q}" for q in range(1, 6))

#: Q3 claims on BOTH attempts — the re-request claimed too, which is the terminal
#: state the ladder exists for: stored with the flag set, suppressed, never deleted.
#: Every other question is clean on its first attempt.
_CLAIM_FIRST = (
    "Question 3: the working is careful and the method is sound; this is one of "
    "the strongest answers in the class."
)
_CLAIM_AGAIN = (
    "Question 3: the derivation is complete and clearly set out; it stands as one "
    "of the finest answers in the class."
)


def _clean(question: str) -> str:
    return (
        f"Question {question[1:]}: the response states the hypothesis and cites "
        "the worked steps for this question."
    )


def _replies() -> list:
    """The canned feed in ladder order: Q1, Q2, Q3 (claim, re-claim), Q4, Q5, L2."""
    replies = []
    for question in _QUESTIONS:
        if question == "Q3":
            replies.append(narrative_completion(_CLAIM_FIRST, ("Q3C1", "Q3C2")))
            replies.append(narrative_completion(_CLAIM_AGAIN, ("Q3C1", "Q3C2")))
        else:
            replies.append(narrative_completion(_clean(question), (f"{question}C1", f"{question}C2")))
    replies.append(narrative_completion("Overall: the submission works through each question in turn."))
    return replies


def _seeded_store(tmp_data_dir):
    store = open_store(tmp_data_dir)
    _, run_id, _ = seed_run(store, submissions=(_SUBMISSION,), criteria=FIVE_QUESTION_CRITERIA)
    seed_scored_submission(store, run_id, _SUBMISSION, complete_questions=set(_QUESTIONS))
    return store, run_id


def test_tc_synth_c03_claim_stored_flagged_suppressed_from_composition(tmp_data_dir):
    """`TC-SYNTH-C03` (P0) — the twice-claiming question is re-requested once, stored
    with `score_claim_flag` set (never discarded, never duplicated), kept out of the
    displayable set, and — the unpinned carry-forward — kept out of the L2
    composition's syntheses."""
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
    store, run_id = _seeded_store(tmp_data_dir)
    try:
        provider = CaptureProvider(_replies())
        report = Worker(store, provider, synth_ref()).synthesize_submission(
            run_id, _SUBMISSION
        )

        # The ladder ran as designed: two parsed outputs carried claims (both
        # rejected), the second was terminal-flagged rather than retried forever.
        assert report.model_calls == 7, (
            f"{report.model_calls} model calls — 5 L1 narratives plus one re-request "
            "for the claiming question plus one L2 composition is 7; a different "
            "count means the ladder retried twice or gave up early"
        )
        assert report.rejected_score_claims == 2, (
            f"{report.rejected_score_claims} rejections — both claim-bearing outputs "
            "must count, or the rate CT-SYNTH-12 alerts on under-reports the check's "
            "work"
        )

        # `store.cohort(...).query()` yields `sqlite3.Row` (no `.get`) — convert.
        rows = {
            row["question_id"]: dict(row)
            for row in store.cohort(COHORT_ID).query(
                "SELECT * FROM narrative WHERE run_id = :r AND submission_id = :s "
                "AND level = 'l1_question'",
                r=run_id, s=_SUBMISSION,
            )
        }
        assert len(rows) == 5, (
            f"{len(rows)} stored L1 rows — the flagged narrative is STORED, not "
            "discarded: discarding would erase the rejection the report owes the "
            "operator (CT-SYNTH-12's count reads stored+rejected, not shown-only)"
        )
        flagged = rows["Q3"]
        assert flagged["score_claim_flag"] == 1, (
            "the twice-claiming narrative was stored with the suppression flag "
            f"{flagged['score_claim_flag']!r} — stored-and-flagged is the ladder's "
            "terminal state; unstored loses the record, unflagged would display it"
        )
        assert flagged["text"] == _CLAIM_AGAIN, (
            "the flagged row must hold the SECOND claim (the re-request also "
            "claimed) — the first attempt's text never stores"
        )
        clean_flags = {
            question: row["score_claim_flag"]
            for question, row in rows.items() if question != "Q3"
        }
        assert set(clean_flags.values()) == {0}, (
            f"clean narratives carry flags {clean_flags} — the flag marks claims, "
            "not narrative identity; a blanket flag would suppress everything"
        )

        # The display set is the flag's negative partition, exactly: five displayable
        # rows, the claim not among them.
        displayable = [row["text"] for row in rows.values() if not row["score_claim_flag"]]
        assert len(displayable) == 4 and not any(
            _CLAIM_FIRST in text or _CLAIM_AGAIN in text for text in displayable
        ), (
            "the displayable set is not exactly the flag-clean rows — a consumer "
            "that shows what the check caught publishes the second, competing grade "
            "(RISK-19)"
        )

        # THE PIN (#98's L2-composition exclusion, previously unpinned by any TC):
        # the L2 prompt's syntheses carry the clean L1 texts and NOT the flagged
        # one — the caught claim must not reach the student through the level that
        # re-states the per-question prose.
        l2_prompt = provider.prompts[-1]
        l2_fields = dict(l2_prompt.fields)
        assert l2_prompt is not None and "syntheses" in l2_fields, (
            f"the last captured prompt is {l2_fields.get('level')!r}-level — the "
            "L2 composition never ran, so the composition exclusion is unverified"
        )
        syntheses = l2_fields["syntheses"]
        assert _clean("Q1") in syntheses and _clean("Q2") in syntheses, (
            "the L2 composition lost a clean L1 narrative — the exclusion must be "
            "scoped to the flagged row only, not a broader skip"
        )
        assert _CLAIM_FIRST not in syntheses and _CLAIM_AGAIN not in syntheses, (
            "the flagged narrative's text is IN the L2 syntheses — the composition "
            "filter (`not row['score_claim_flag']`, #98) did not hold, so the "
            "student's whole-test narrative re-frames the claim the check caught"
        )
        l2_row = store.cohort(COHORT_ID).query(
            "SELECT * FROM narrative WHERE run_id = :r AND submission_id = :s "
            "AND level = 'l2_test'",
            r=run_id, s=_SUBMISSION,
        )
        assert len(l2_row) == 1 and l2_row[0]["question_id"] == "__test__", (
            "the L2 row must still store (one, sentinel-keyed) even though one L1 "
            "input was suppressed — suppression is not a synthesis failure"
        )
    finally:
        store.close()


@pytest.mark.writtenahead
def test_tc_synth_c03_consumers_honour_the_suppression_flag(tmp_data_dir):
    """`TC-SYNTH-C03` (P0, rung 3 consumer sweep) — `M-CONSOLE` renders the
    submission without the flagged narrative, and `M-GRADE`'s export carries none of
    it either: a consumer that ignores the flag publishes exactly what the check
    caught.

    Written ahead of both consumers (test plan §8.2); registered in
    `WRITTEN_AHEAD_BLOCKERS` under `"#100 suppression consumers (C03)"` (symbols
    `aeh.console:build_console`, `aeh.grade:open_grade`). The rendered/exported
    shapes are the consumers' to reconcile — disclosed in
    `tests/support/console_vocabulary.py` (`/students/{ref}` route, `RenderedPage`
    `.html`) and `tests/support/grade_vocabulary.py` (`GradingService.export`).
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")
    open_grade = require(GRADE_MODULE, "open_grade", issue="#101")
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)

    store, run_id = _seeded_store(tmp_data_dir)
    try:
        provider = CaptureProvider(_replies())
        Worker(store, provider, synth_ref()).synthesize_submission(run_id, _SUBMISSION)

        app = build_console(cohort_size=1, provider=provider)
        page = app.render("/students/SYN-001")
        assert _CLAIM_AGAIN not in page.html and _CLAIM_FIRST not in page.html, (
            "the console rendered the flagged narrative — M-CONSOLE must honour the "
            "suppression flag: a consumer that shows what the check caught publishes "
            "exactly the second, competing grade the check exists to keep from the "
            "student (CT-SYNTH-03, RISK-19)"
        )
        assert _clean("Q1") in page.html, (
            "the console dropped a clean narrative too — suppression is scoped to "
            "the flagged row, not a blanket skip"
        )

        service = open_grade(store)
        exported = service.export(run_id)
        exported_text = exported if isinstance(exported, str) else str(exported)
        assert _CLAIM_FIRST not in exported_text and _CLAIM_AGAIN not in exported_text, (
            "M-GRADE's export carried the flagged narrative — the suppression flag "
            "is the contract every consumer reads, and the export is the one the "
            "student's permanent record is built from"
        )
    finally:
        store.close()
