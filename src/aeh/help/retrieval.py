"""The local retrieval index over the packaged manuals (FR-HELP-03) and its scoring.

The index is built from the manuals and nothing else — its corpus is inspectable, and
`TC-HELP-04` sweeps it to prove the store never feeds it. Scoring is token overlap weighted by
inverse document frequency: a token that appears in every passage weighs zero, and the common
function words are dropped before scoring entirely, so a question sharing only boilerplate with
the manuals stays ungrounded while the rare words a real question carries ("blind sample",
"start a run") rank the passages that answer it. That is what makes the not-found path honest
(FR-HELP-02) rather than a coin flip over "the".

Token sets and IDF weights are computed once at index build and reused per question: retrieval
is measured against a 200 ms budget (`NFR-HELP-01`'s retrieval clause), which re-tokenizing 90
passages per ask would spend for nothing.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable

#: Passages retrieved per question, in score order. Every retrieved passage is cited, so a
#: wider window cites more of what the model actually saw.
MAX_PASSAGES = 8

_NON_ALNUM = re.compile(r"[^0-9a-z]+")

#: Function and question words scored as zero information. Deliberately narrow: content verbs
#: and nouns the operator's question carries ("start", "run", "export") must keep ranking. A
#: word added here stops grounding a question that shares only that word with the manuals.
STOPWORDS = frozenset({
    "a", "all", "also", "am", "an", "and", "any", "are", "as", "at", "be", "because", "been",
    "before", "being", "both", "but", "by", "can", "could", "did", "do", "does", "doing",
    "done", "down", "during", "each", "few", "for", "from", "further", "get", "got", "had",
    "has", "have", "having", "he", "her", "here", "hers", "him", "his", "i", "if", "in",
    "into", "is", "it", "its", "just", "me", "might", "more", "most", "must", "my", "no",
    "nor", "not", "of", "off", "on", "once", "only", "or", "other", "our", "out", "over",
    "own", "same", "shall", "she", "should", "so", "some", "such", "than", "that", "the",
    "how",
    "their", "them", "then", "there", "these", "they", "this", "those", "through", "to",
    "too", "under", "up", "very", "was", "we", "were", "what", "when", "where", "which",
    "while", "who", "whom", "why", "will", "with", "within", "without", "would", "you",
    "your",
})


@dataclass(frozen=True)
class Passage:
    """One indexed passage: the manual section it came from, and its text as the prompt
    carries it (heading included — a heading is often the phrase a question matches)."""

    manual_id: str
    anchor: str
    heading: str
    text: str


@dataclass(frozen=True)
class RetrievalIndex:
    """The retrieval index over the manuals: its passages, in manual then page order, with each
    passage's token set and the corpus's IDF weights precomputed for scoring."""

    passages: tuple[Passage, ...]
    tokens: tuple[frozenset[str], ...]
    idf: dict[str, float]


def tokenize(text: str) -> tuple[str, ...]:
    """Lowercase, every non-alphanumeric run to one space, split — the normalization the
    manuals' Markdown formatting drops out under."""
    return tuple(_NON_ALNUM.sub(" ", text.lower()).split())


def build_index(manuals: Iterable) -> RetrievalIndex:
    """The index over the given manuals: one passage per section (chunked by heading), with the
    section's anchor so every citation resolves (CT-HELP-02)."""
    passages = tuple(
        Passage(
            manual_id=getattr(manual, "manual_id"),
            anchor=section.anchor,
            heading=section.heading,
            text=f"{section.heading}\n{section.text}",
        )
        for manual in manuals
        for section in getattr(manual, "sections")
    )
    document_frequency: dict[str, int] = {}
    token_sets = []
    for passage in passages:
        tokens = frozenset(tokenize(passage.text))
        token_sets.append(tokens)
        for token in tokens:
            document_frequency[token] = document_frequency.get(token, 0) + 1
    total = len(passages)
    idf = {token: math.log(total / df) for token, df in document_frequency.items()}
    return RetrievalIndex(passages=passages, tokens=tuple(token_sets), idf=idf)


def score_passages(index: RetrievalIndex, question: str) -> tuple[tuple[Passage, float], ...]:
    """Every passage scored against the question, best first, deterministically.

    A passage's score is the sum of the IDF weights of the question's non-stopword tokens it
    contains; a token the corpus never carries contributes nothing. Ties break by the passage's
    position in the index (manual then page order), never by set iteration — the answer's
    citations must be reproducible (`CT-HELP-02`)."""
    query_tokens = set(tokenize(question)) - STOPWORDS
    scored = []
    for position, (passage, tokens) in enumerate(zip(index.passages, index.tokens)):
        present = query_tokens & tokens
        score = sum(index.idf[token] for token in present)
        if score > 0.0:
            scored.append((-score, position, passage))
    scored.sort(key=lambda item: (item[0], item[1]))
    return tuple((passage, -negated) for negated, _position, passage in scored)


def retrieve(index: RetrievalIndex, question: str) -> tuple[Passage, ...]:
    """The passages a question is grounded on: the best-scoring ones, or none when the question
    shares no informative word with the corpus (the explicit not-found path, FR-HELP-02 — the
    question's own boilerplate never grounds it)."""
    scored = score_passages(index, question)
    return tuple(passage for passage, _score in scored[:MAX_PASSAGES])
