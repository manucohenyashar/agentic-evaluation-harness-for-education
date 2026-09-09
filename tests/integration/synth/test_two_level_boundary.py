"""`TC-SYNTH-01` — the two-level information boundary (`M-SYNTH`, TS-37, P0,
integration, rung 2).

FR-SYNTH-01: L1 reads one question's criterion verdicts and evidence for one
submission; L2 reads **only** the L1 syntheses and no raw verdicts. The oracle is the
plan's own: **asserted by inspecting the assembled requests** — the capture provider is
the model-boundary double §4.2 permits, and the captured `PromptPayload`s are the
assembled L1/L2 requests exactly as the worker built them.

What makes this fail-if-wrong rather than run-and-pass:

- **Level classification is content-derived, not order-derived.** Each captured prompt
  is classified by which question's criterion ids it names, so a worker that hands L1
  all five questions at once produces five prompts that each name five questions and
  the one-per-prompt assertion fails; a worker that skips a level produces the wrong
  call count and fails there.
- **The L2 half is a negative assertion over raw material.** The L2 request must carry
  the five L1 syntheses and must NOT carry any judge id, any `EVIDENCE-Q*` span
  marker, or any criterion id — the identifiers raw verdicts and raw evidence cannot
  travel without. A prompt-instruction "boundary" (NFR-SYNTH-03's named failure: the
  text says don't, the type doesn't enforce) shows up here as raw material in the
  captured L2 prompt, and the case goes red.

Isolation: rung 2 — real SQLite in `tmp_data_dir`, real package and cohort rows, the
capture provider standing in at the one boundary doubles are permitted (§4.2). The
verdict/evidence/document state is seeded directly (see
`tests.support.synth_vocabulary.seed_scored_submission`), which states the upstream
modules' artifacts as inputs rather than standing in for three modules.

Interface assumed of `#97` (disclosed in `tests/support/synth_vocabulary.py`,
reconcile at landing): `SynthesisWorker(store, provider, model_ref)` with
`.synthesize_submission(run_id, submission_id) -> SynthesisReport`, and the canned
reply format `narrative_completion` builds. One order assumption remains, disclosed:
within one submission the L1 calls precede the L2 call, so the last captured prompt is
the L2 request — the classification assertion does not depend on it, the L2-targeting
assertion does, and it is one line if #97 orders differently.
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support.impl import SYNTH_MODULE, require
from tests.support.orch_run import seed_run
from tests.support.synth_vocabulary import (
    FIVE_QUESTION_CRITERIA,
    SYNTH_ISSUE,
    WORKER,
    CaptureProvider,
    evidence_marker,
    narrative_completion,
    seed_scored_submission,
    synth_ref,
)

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

_SUBMISSION = "SYN-001"
_QUESTIONS = tuple(f"Q{q}" for q in range(1, 6))


def test_tc_synth_01_l1_reads_one_question_l2_reads_only_l1_syntheses(tmp_data_dir):
    """`TC-SYNTH-01` (P0) — L1 per question from that question's verdicts and evidence;
    L2 from the L1 syntheses alone; raw verdicts and raw evidence never reach L2."""
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)

    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = seed_run(store, submissions=(_SUBMISSION,), criteria=FIVE_QUESTION_CRITERIA)
        seed_scored_submission(store, run_id, _SUBMISSION, complete_questions=set(_QUESTIONS))

        # Five L1 narratives (one per question, each naming its question so the L2
        # prompt's carried syntheses are attributable) plus the one L2 reply.
        l1_texts = [
            f"Question {q[1:]}: the response states the hypothesis and cites the "
            f"worked steps for this question." for q in _QUESTIONS
        ]
        replies = [
            narrative_completion(text, (f"{q}C1", f"{q}C2"))
            for q, text in zip(_QUESTIONS, l1_texts, strict=True)
        ] + [narrative_completion("Overall: the submission works through each question in turn.")]
        provider = CaptureProvider(replies)

        worker = Worker(store, provider, synth_ref())
        worker.synthesize_submission(run_id, _SUBMISSION)

        # --- the two-level shape itself: five L1 calls plus one L2 call ------------
        assert provider.calls == 6, (
            f"{provider.calls} model calls for a five-question submission — the "
            "two-level composition is five L1 calls (one per question) and one L2 "
            "call; a different count is a different shape (NFR-SYNTH-02: ~6 per "
            "submission is where ~2,100 per 350 students comes from)"
        )

        # --- L1: each request reads exactly one question's verdicts and evidence ---
        classified: "dict[str, list[int]]" = {q: [] for q in _QUESTIONS}
        for index, prompt in enumerate(provider.prompts):
            text = "\n".join(f"{name}={value}" for name, value in prompt.fields)
            questions_named = [q for q in _QUESTIONS if f"{q}C1" in text or f"{q}C2" in text]
            assert len(questions_named) <= 1, (
                f"captured request {index} names the criteria of questions "
                f"{questions_named} — an L1 request reads ONE question's criterion "
                "verdicts (FR-SYNTH-01); a request carrying several questions is the "
                "thirty-verdict failure NFR-SYNTH-03 exists to prevent"
            )
            if questions_named:
                classified[questions_named[0]].append(index)
        for question in _QUESTIONS:
            assert classified[question], (
                f"no captured request reads question {question}'s criterion verdicts — "
                "one L1 call per question is the level structure FR-SYNTH-01 states"
            )
            text = "\n".join(
                f"{name}={value}"
                for index in classified[question]
                for name, value in provider.prompts[index].fields
            )
            assert evidence_marker(question) in text, (
                f"the L1 request for {question} does not read that question's evidence "
                "— L1 reads the question's criterion verdicts AND evidence "
                f"({evidence_marker(question)} is the only span marker the seed puts "
                "there for it)"
            )

        # --- L2: only the L1 syntheses; no raw verdicts, no raw evidence -----------
        l1_indices = {i for idxs in classified.values() for i in idxs}
        l2_indices = [i for i in range(len(provider.prompts)) if i not in l1_indices]
        assert len(l2_indices) == 1, (
            f"{len(l2_indices)} non-L1 requests captured — exactly one L2 composition "
            "per submission is the second level of FR-SYNTH-01"
        )
        l2_text = "\n".join(
            f"{name}={value}" for name, value in provider.prompts[l2_indices[0]].fields
        )
        for text in l1_texts:
            assert text in l2_text, (
                f"the L2 request does not carry the L1 synthesis for a question "
                f"({text!r} absent) — L2 reads the L1 syntheses, and one missing means "
                "the per-test narrative is composed from less than the whole"
            )
        leaked = [
            marker for marker in (
                [evidence_marker(q) for q in _QUESTIONS],
                [f"judge-{q.lower()}" for q in _QUESTIONS],
                [f"{q}C{k}" for q in _QUESTIONS for k in (1, 2)],
            ) for marker in marker
        ]
        present = [marker for marker in leaked if marker in l2_text]
        assert not present, (
            f"the L2 request carries raw material ({present}) — judge ids, criterion "
            "ids and evidence markers are the identifiers raw verdicts and raw evidence "
            "cannot travel without; FR-SYNTH-01: L2 reads ONLY the L1 syntheses, and "
            "NFR-SYNTH-03 makes that a type-level fact, not a prompt instruction"
        )
    finally:
        store.close()
