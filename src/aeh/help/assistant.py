"""The grounded, answers-only QA assistant (FR-HELP-02/03, FR-HELP-05): one operation,
``ask(question) -> {answer, citations}``, and nothing else.

Answers-only is enforced by construction rather than by parsing the reply: retrieval selects
the passages (or none), the model is called exactly once on those passages, the reply passes
through as inert prose — nothing is ever parsed or acted on from it (`FR-HELP-05`) — and the
citations are exactly the passages that were sent, so "grounded on what is cited" holds by
construction (`CT-HELP-02`). A question that shares no informative word with the manuals is
never sent to the model at all: it gets the explicit not-found answer and a `not-found` log
row, with zero tokens (`FR-HELP-02` — a model-memory answer cannot leak through a call that
never happened).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, NamedTuple

from aeh.help.log import OUTCOME_GROUNDED, OUTCOME_NOT_FOUND, record_exchange
from aeh.help.manuals import load_manuals
from aeh.help.prompts import build_prompt
from aeh.help.retrieval import Passage, build_index, retrieve
from aeh.prov import SamplingParams

#: The not-found answer (FR-HELP-02): explicit, pointing at the manuals page — and at the
#: Results screen for the "what did this student get?" kind of question, which the assistant
#: cannot answer at all (`FR-HELP-03`).
NOT_FOUND_ANSWER = (
    "The manuals do not cover that, so I have no grounded answer for it. Search or read the "
    "manuals page for what the system does; if your question is about a student's grade, open "
    "the Results screen in the console — the assistant cannot see grades or student data."
)


class Citation(NamedTuple):
    """One cited passage: the manual and the anchor that resolves to its section."""

    manual_id: str
    anchor: str


class Answer(NamedTuple):
    """One ask's result: the prose answer and the passages it was grounded on."""

    answer: str
    citations: tuple[Citation, ...]


def _model_ref_text(model_ref: Any) -> str:
    """The log's model identity: ``provider:build_id`` — the resolved QA model the exchange
    named (`FR-CONF-30`), build id included."""
    return f"{getattr(model_ref, 'provider')}:{getattr(model_ref, 'build_id')}"


class HelpAssistant:
    """The manuals Q&A assistant. Its only public operation is :meth:`ask`; ``index`` is the
    retrieval index it answers from, exposed so the corpus stays inspectable (FR-HELP-03)."""

    def __init__(self, *, store: Any, provider: Any, model_ref: Any,
                 manuals_dir=None) -> None:
        self._store = store
        self._provider = provider
        self._model_ref = model_ref
        # The deterministic seam (`CLAUDE.md` seam 2): the manuals directory can be pointed at
        # a copy so a test can nest an injected passage without touching package data.
        self.index = build_index(load_manuals(manuals_dir))
        self._sampling = SamplingParams(temperature=0.0)

    def ask(self, question: str) -> Answer:
        """Answer one question, grounded on the manuals, and log the exchange."""
        started = time.perf_counter()
        passages = retrieve(self.index, question)
        if passages:
            prompt = build_prompt(passages, question)
            completion = self._provider.complete(prompt, self._model_ref, self._sampling)
            answer = completion.text
            citations = tuple(Citation(passage.manual_id, passage.anchor) for passage in passages)
            tokens_in, tokens_out = completion.tokens_in, completion.tokens_out
            outcome = OUTCOME_GROUNDED
        else:
            answer = NOT_FOUND_ANSWER
            citations = ()
            tokens_in, tokens_out = 0, 0
            outcome = OUTCOME_NOT_FOUND
        latency_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        record_exchange(
            self._store,
            question=question,
            cited_anchors=[citation.anchor for citation in citations],
            model_ref=_model_ref_text(self._model_ref),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            outcome=outcome,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        return Answer(answer, citations)
