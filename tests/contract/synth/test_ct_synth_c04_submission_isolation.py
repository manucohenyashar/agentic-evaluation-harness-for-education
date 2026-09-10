"""`TC-SYNTH-C04` — one submission per request, and no sibling's content (§6.11.13).

`CT-SYNTH-04`'s isolation half, the mechanically assertable part the plan calls
"the enforceable part": the request carries **exactly one** `submission_id` and
**no other submission's content is reachable** — asserted by sentinel scan across a
full two-submission run, in the same shape as `TC-JUDGE-C03`. The anchoring half
(each claim corresponds to a criterion and cites that student's own work) is the
part the plan marks `TBD` (`CT-SYNTH-13`, §7.4): this case asserts what is
assertable — the citation-validity measurement the report already carries
(`TC-SYNTH-12`'s signals) — and the docstring says so rather than implying more.

The sentinel scan's shape, disclosed: the shipped `seed_scored_submission` falls
back to the ADDRESSED DOCUMENT's markdown when an evidence row carries no span
payload, and one document holds every question's marker — so a same-submission
sibling question's marker legitimately appears in an L1 prompt, and the boundary
this case asserts is between SUBMISSIONS: each submission's document embeds markers
unique to it (`ONLY-SYN-001-Q2`), and no prompt of one submission's drive may carry
the other's.

Relationship to shipped cases: `tests/artifact/test_synth_score_free_schema.py`
(`TC-SYNTH-07`) pins the exactly-one-submission_id FIELD; `tests/integration/synth/
test_two_level_boundary.py` pins per-question prompt classification on one
submission. This case is the cross-submission differential neither holds.

Isolation: rung 2 — real SQLite, `CaptureProvider` at the model boundary, one
provider per drive so every captured prompt is attributable to its submission.
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

pytestmark = [pytest.mark.contract]

_SUBMISSIONS = ("SYN-001", "SYN-002")
_QUESTIONS = tuple(f"Q{q}" for q in range(1, 6))


def _markdown(submission_id: str) -> str:
    """A document whose per-question evidence markers name THIS submission — the
    sentinel scan's needles."""
    return "\n\n".join(
        f"## Question {q[1:]}\nONLY-{submission_id}-Q{q[1:]}: the student's own "
        f"work for question {q}."
        for q in _QUESTIONS
    )


def _l1_prose(submission_id: str, question: str) -> str:
    return (
        f"Question {question[1:]}: the response states the hypothesis and cites "
        f"the worked steps for {submission_id}."
    )


def _replies(submission_id: str) -> list:
    replies = [
        narrative_completion(
            _l1_prose(submission_id, question), (f"{question}C1", f"{question}C2")
        )
        for question in _QUESTIONS
    ]
    replies.append(narrative_completion(
        f"Overall: the submission works through each question in turn — see "
        f"{submission_id}."
    ))
    return replies


def _drive(store, run_id: str, submission_id: str):
    """One submission's full two-level drive; returns the provider (prompts
    attributable to THIS drive)."""
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
    provider = CaptureProvider(_replies(submission_id))
    report = Worker(store, provider, synth_ref()).synthesize_submission(
        run_id, submission_id
    )
    assert report.failures == 0, (
        f"{report.failures} failures on the isolation drive — the isolation oracle "
        "must read a clean run, or a missing prompt could be a failure wearing "
        "isolation's clothes"
    )
    return provider


def test_tc_synth_c04_no_other_submissions_content_is_reachable(tmp_data_dir):
    """`TC-SYNTH-C04` (P0) — across a full two-submission run, every L1 request
    carries exactly one submission and none of the other submission's evidence; the
    L2 composition draws only on that submission's own syntheses; and every stored
    row belongs to the drive that produced it."""
    store = open_store(tmp_data_dir)
    try:
        # One run over both submissions (`seed_run` seeds its cohort once per store);
        # each submission's document carries markers unique to it, so the sentinel
        # scan's needles cannot collide across the pair.
        _, run_id, _ = seed_run(
            store, submissions=_SUBMISSIONS, criteria=FIVE_QUESTION_CRITERIA
        )
        for submission_id in _SUBMISSIONS:
            seed_scored_submission(
                store, run_id, submission_id,
                complete_questions=set(_QUESTIONS),
                markdown=_markdown(submission_id),
            )

        prompts_by_submission = {
            submission_id: _drive(store, run_id, submission_id).prompts
            for submission_id in _SUBMISSIONS
        }

        for submission_id, prompts in prompts_by_submission.items():
            other = next(s for s in _SUBMISSIONS if s != submission_id)
            for prompt in prompts:
                fields = dict(prompt.fields)
                # Exactly one submission named, and it is THIS drive's.
                submissions_in_prompt = [
                    value for name, value in prompt.fields if name == "submission"
                ]
                assert submissions_in_prompt == [submission_id], (
                    f"a {fields.get('level')!r}-level prompt of {submission_id} "
                    f"carries {submissions_in_prompt!r} — exactly one submission_id "
                    "per request (FR-SYNTH-05); a prompt that names two submissions "
                    "composes across students"
                )
                # The sentinel scan: the other submission's markers are nowhere in
                # the rendered prompt, at either level.
                rendered = "\n".join(f"{n}={v}" for n, v in prompt.fields)
                for marker in (
                    f"ONLY-{other}-Q{n[1:]}" for n in _QUESTIONS
                ):
                    assert marker not in rendered, (
                        f"a {fields.get('level')!r}-level prompt for {submission_id} "
                        f"carries {marker} — another submission's content reached "
                        "the narrative model (FR-SYNTH-05); the first place this "
                        "shows is the evidence the prompt composes from"
                    )
                # And the L2 composition reads only this submission's syntheses.
                if fields.get("level") == "l2_test":
                    syntheses = fields["syntheses"]
                    for question in _QUESTIONS:
                        own = _l1_prose(submission_id, question)
                        foreign = _l1_prose(other, question)
                        assert own in syntheses and foreign not in syntheses, (
                            "the L2 composition mixed submissions: it must draw on "
                            "the stored L1 narratives of ITS submission only"
                        )

        # The stored rows agree with the drives: every narrative row belongs to the
        # submission its drive served, at both levels.
        for submission_id in _SUBMISSIONS:
            rows = store.cohort(COHORT_ID).query(
                "SELECT submission_id, level, question_id FROM narrative "
                "WHERE run_id = :r AND submission_id = :s",
                r=run_id, s=submission_id,
            )
            assert len(rows) == 6, (
                f"{len(rows)} narrative rows for {submission_id} — the "
                "fixture's 5 L1 rows plus one L2 row, all attributable"
            )
            assert {row["submission_id"] for row in rows} == {submission_id}, (
                "a stored narrative names a submission its drive did not serve — "
                "the isolation breach reached the store, not just the prompt"
            )
            assert {
                row["question_id"] for row in rows if row["level"] == "l2_test"
            } == {"__test__"}, (
                "the L2 row is sentinel-keyed, one per submission (CT-SYNTH-06)"
            )
    finally:
        store.close()
