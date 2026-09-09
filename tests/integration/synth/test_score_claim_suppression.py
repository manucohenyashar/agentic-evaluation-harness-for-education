"""`TC-SYNTH-05` and `TC-SYNTH-06` — the score-claim prohibition at the store
(`M-SYNTH`, TS-37, P0).

- `TC-SYNTH-05` (`FR-SYNTH-03`, artifact assertion): every stored narrative after a
  full run scans **zero matches** against `SYNTH_SCORE_CLAIM_PATTERNS` — the design
  names an assertion over **stored** narratives as the acceptance form, because a scan
  on the generation path misses a narrative that reached the store by any other route.
  The run below is deliberately not all-clean: the provider emits one claim-bearing
  reply, so the zero-matches scan only passes if the module's check actually rejected
  it. A module that never checks stores the claim and fails here; a module that checks
  but fails to persist the replacement fails here too.
- `TC-SYNTH-06` (`FR-SYNTH-03`, exact value plus display assertion): a narrative that
  fails the check **twice** is re-requested **once**, then stored **with a flag and
  suppressed from display** rather than shown — a prose verdict above a mark is
  functionally a second competing grade (RISK-19), but deleting it loses feedback the
  module owes the student's record. The exact-value half is the stored text and the
  call count; the display half is the flag a consumer reads (CT-SYNTH-03: "a consumer
  may rely on displayed narrative being score-free; it must honour the suppression
  flag" — the console's rendering of that flag is TC-CONSOLE's case, not this one).

Written ahead of `#98` (with `#97`'s module; test plan §8.2): fails only through
`NotImplementedYet` naming the owning issue, or — once landed — through the assertion.

Isolation: TC-SYNTH-06's plan row says rung 1; this file runs it at **rung 2** (real
SQLite, capture provider at the model boundary) — the same harness as its siblings,
which is the stricter form of the same isolation statement. The claim-bearing replies
are `narrative_completion` payloads whose text matches FR-SYNTH-03's own classes (the
same strings TC-SYNTH-04 asserts the predicate on), so the module under test is free
to parse whatever reply format it likes as long as the narrative text comes out.

Interface assumed of `#97`/`#98` (disclosed in `tests/support/synth_vocabulary.py`,
reconcile at landing): `SynthesisWorker(store, provider, model_ref)` with
`.synthesize_submission(...)`; `SYNTH_SCORE_CLAIM_PATTERNS` exported from `aeh.synth`
as an iterable of regex strings; `narrative` rows carry `text` and the suppression flag
column `score_claim_flag` (0/1), read name-agnostically as row dicts.
"""

from __future__ import annotations

import re

import pytest

from aeh.store import open_store
from tests.support.impl import SYNTH_MODULE, require
from tests.support.orch_run import seed_run
from tests.support.synth_vocabulary import (
    COHORT_ID,
    FIVE_QUESTION_CRITERIA,
    PATTERNS,
    SCORE_CLAIM_CHECK,
    SCORE_CLAIM_FLAG,
    SCORE_CLAIM_ISSUE,
    SYNTH_ISSUE,
    WORKER,
    CaptureProvider,
    narrative_completion,
    seed_scored_submission,
    synth_ref,
)

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

_SUBMISSIONS = ("SYN-001", "SYN-002")
_QUESTIONS = tuple(f"Q{q}" for q in range(1, 6))

#: ADV-11's named attack, verbatim — the claim-bearing reply the feeds below emit.
_CLAIM_TEXT = (
    "Question 3: the response states the hypothesis and cites the table; this is one "
    "of the strongest answers in the class."
)
_CLEAN_TEXTS = {
    q: f"Question {q[1:]}: the response states the hypothesis and cites the worked "
       f"steps for this question."
    for q in _QUESTIONS
}


def _seeded_run(store) -> str:
    _, run_id, _ = seed_run(store, submissions=_SUBMISSIONS, criteria=FIVE_QUESTION_CRITERIA)
    for submission_id in _SUBMISSIONS:
        seed_scored_submission(store, run_id, submission_id, complete_questions=set(_QUESTIONS))
    return run_id


def _feed(claim_question: str | None = None, twice_question: str | None = None) -> CaptureProvider:
    """Replies for one submission's two-level run, in the disclosed call order.

    With `claim_question` set, that question's FIRST reply is the claim-bearing text
    and its second reply is clean — the reject-and-re-request the check owes. With
    `twice_question` set, that question gets the claim text on BOTH attempts — the
    reject-once-then-store-flagged terminal path, with no third attempt to hide in.
    """
    replies: "list[object]" = []
    for question in _QUESTIONS:
        if question == claim_question:
            first, second = _CLAIM_TEXT, _CLEAN_TEXTS[question]
        elif question == twice_question:
            first, second = _CLAIM_TEXT, _CLAIM_TEXT
        else:
            first, second = _CLEAN_TEXTS[question], None
        replies.append(narrative_completion(first, (f"{question}C1", f"{question}C2")))
        if second is not None:
            replies.append(narrative_completion(second, (f"{question}C1", f"{question}C2")))
    replies.append(narrative_completion("Overall: the submission works through each question in turn."))
    return CaptureProvider(replies)


def _narrative_rows(store, run_id: str) -> "list[dict]":
    return store.cohort(COHORT_ID).query(
        "SELECT * FROM narrative WHERE run_id = :r",
        r=run_id,
    )


def test_tc_synth_05_stored_narratives_scan_zero_matches(tmp_data_dir):
    """`TC-SYNTH-05` (P0) — after a run whose provider emitted a claim, EVERY stored
    narrative scans zero matches against the configured patterns and the predicate."""
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
    has_score_claim = require(SYNTH_MODULE, SCORE_CLAIM_CHECK, issue=SCORE_CLAIM_ISSUE)
    patterns = require(SYNTH_MODULE, PATTERNS, issue=SCORE_CLAIM_ISSUE)
    compiled = [re.compile(pattern) for pattern in patterns]
    assert compiled, (
        "SYNTH_SCORE_CLAIM_PATTERNS is empty — the configured list is the one "
        "enumerable place FR-SYNTH-03's classes live, and an empty list suppresses "
        "nothing"
    )

    store = open_store(tmp_data_dir)
    try:
        run_id = _seeded_run(store)
        # SYN-001's Q3 misbehaves once: the check must reject and re-request, and the
        # stored set must still scan clean.
        for index, submission_id in enumerate(_SUBMISSIONS):
            feed = _feed(claim_question="Q3") if index == 0 else _feed()
            Worker(store, feed, synth_ref()).synthesize_submission(run_id, submission_id)

        rows = _narrative_rows(store, run_id)
        assert rows, "the run stored no narratives — nothing to scan is not a pass"
        for row in rows:
            text = row.get("text") or ""
            assert has_score_claim(text) is False, (
                f"stored narrative for {row.get('question_id')!r} matches the "
                f"score-claim check: {text!r} — FR-SYNTH-03's acceptance form is an "
                "assertion over STORED narratives; a claim in the store is a second, "
                "competing grade that reaches the student (RISK-19)"
            )
            for pattern in compiled:
                assert pattern.search(text) is None, (
                    f"stored narrative for {row.get('question_id')!r} matches the "
                    f"configured pattern {pattern.pattern!r}: {text!r} — the "
                    "configured list, not the predicate alone, is what CT-SYNTH-11 "
                    "makes externally visible"
                )
    finally:
        store.close()


def test_tc_synth_06_twice_failing_claim_is_stored_flagged_and_suppressed(tmp_data_dir):
    """`TC-SYNTH-06` (P0) — a narrative failing the check twice: re-requested once (two
    calls, no third), then stored flagged rather than shown."""
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)

    store = open_store(tmp_data_dir)
    try:
        run_id = _seeded_run(store)
        # SYN-001's Q3 fails the check on BOTH attempts; every other reply is clean.
        feed = _feed(twice_question="Q3")
        Worker(store, feed, synth_ref()).synthesize_submission(run_id, "SYN-001")

        # --- exact value: re-requested ONCE, and the second attempt is what stored --
        assert feed.calls == 7, (
            f"{feed.calls} model calls for a five-question submission with one "
            "twice-failing narrative — five L1 calls with ONE re-request (6), plus the "
            "L2 call (7); a third attempt on Q3 contradicts the re-request-once "
            "ladder, a fifth total call means the claim was never re-requested at all"
        )
        rows = _narrative_rows(store, run_id)
        q3_rows = [row for row in rows if row.get("question_id") == "Q3"]
        assert len(q3_rows) == 1, (
            f"{len(q3_rows)} stored narratives for Q3 — flagged storage is one row, "
            "not one row per attempt"
        )
        stored = q3_rows[0].get("text") or ""
        assert _CLAIM_TEXT in stored, (
            f"Q3's stored narrative is {stored!r} — the twice-failing attempt is the "
            "text that gets STORED WITH A FLAG (CT-SYNTH-03: re-requested once, then "
            "stored with a flag rather than shown); the flag without the text is a "
            "silently rewritten narrative"
        )

        # --- the display assertion: the row carries the suppression flag, and the ---
        # --- flag is discriminating — every other stored row is unflagged ----------
        assert q3_rows[0].get(SCORE_CLAIM_FLAG), (
            f"Q3's stored narrative has {SCORE_CLAIM_FLAG}="
            f"{q3_rows[0].get(SCORE_CLAIM_FLAG)!r} — CT-SYNTH-03 stores the "
            "twice-failing narrative WITH A FLAG and suppresses it from display; "
            "without the flag the claim reaches the student as shown narrative"
        )
        others = [row for row in rows if row.get("question_id") != "Q3"]
        assert others, "the run stored no other narratives — the fixture degenerated"
        assert all(not row.get(SCORE_CLAIM_FLAG) for row in others), (
            "a narrative that passed the check carries the suppression flag too — a "
            "flag that flags everything suppresses everything, and the store stops "
            "distinguishing feedback that may be shown from feedback that may not"
        )
    finally:
        store.close()
