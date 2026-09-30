"""The score-claim check: a narrative must not state a score of its own (FR-SYNTH-03)."""

from __future__ import annotations

import re
from functools import lru_cache


# --- the score-claim prohibition (FR-SYNTH-03, CT-SYNTH-03/11/13) ----------------------------------

#: The configured score-claim patterns — **the one enumerable place** (`CT-SYNTH-11`):
#: the four classes FR-SYNTH-03 names, as case-insensitive regex strings. Changing this
#: list changes what gets suppressed, which makes it externally visible and reviewable
#: as the contract change it is; there is deliberately no env knob for it (it is the
#: prohibition's content, not an environment-sensitive constant) and deliberately no
#: second copy anywhere else in the tree.
#:
#: Precision is the point, disclosed: `CT-SYNTH-13` declares the check pattern-based
#: and weaker than the goal — a paraphrased quality claim ("this is among the
#: strongest answers") carries no numeral and no listed phrase, and is EXPECTED to
#: pass. Each class is written to catch the claim a grader would read as a second,
#: competing grade while passing the legitimate numerals a science answer is full of
#: ("she calculated 12 kg", "the 2019 reference"): a numeral must sit adjacent to a
#: mark word, "out of" must sit between numerals, a percentage must carry the sign or
#: the word, and the holistic class names the graded-object phrasings, so "the
#: strongest evidence for the hypothesis" is content while "one of the strongest
#: answers in the class" is a verdict. The negative fixtures the design names are
#: pinned by `TC-SYNTH-04`/`TC-SYNTH-C13`.
SYNTH_SCORE_CLAIM_PATTERNS: tuple[str, ...] = (
    # (1) A numeral adjacent to a mark, score or grade word — "earned 17 marks",
    #     "17 points", "a mark of 17", "a score of 17", "total score: 17", "a grade
    #     of 7". The numeral-then-word form catches the adjacency; the word-then-
    #     numeral form covers the nouns the prohibition is NAMED for — "a score of
    #     17" is exactly the second, competing grade RISK-19 describes, so the word
    #     "score" cannot be absent from its own net (the reviewer's #98 finding).
    #     Known costs, accepted on purpose and disclosed: "she plotted 3 points on
    #     the graph" matches the numeral-first form, and the content reading of
    #     "a score of 3 on the Mohs scale" / "a z-score of 1.5" matches the
    #     word-first form; a false positive at temperature 0.0 re-requests into the
    #     same phrasing and ends suppressed, not corrected — the reviewer-visible
    #     trade is that the claim forms reach the net, and the content forms that
    #     collide with them are rarer in feedback prose than the claims are.
    #     "Mark scheme" alone never matches (no numeral), and "score"/"grade" with
    #     no separator numeral ("the score was high") do not match either.
    r"\b\d+(?:\.\d+)?\s*(?:marks?|points)\b",
    r"\b(?:marks?|scores?|grades?)\s*(?:of|for|=|:)\s*\d+(?:\.\d+)?\b",
    # (2) "Out of" between numerals — "17 out of 20". Both sides numeric: a bare
    #     "out of the three trials" is content, not a mark. Deliberately out of the
    #     net, for the reviewer's #98 record: the fraction form "17/20" (it collides
    #     with the "3/4" of a maths answer) and "17 out of a possible 20" (the
    #     numeral must sit directly before "out of", or "2 out of the three trials
    #     succeeded" — content — matches) are NOT caught; a reviewer tightening the
    #     net starts here.
    r"\b\d+(?:\.\d+)?\s+out\s+of\s+\d+(?:\.\d+)?\b",
    # (3) A percentage — "top 90%", "90 percent", "90 per cent".
    r"\b\d+(?:\.\d+)?\s*(?:%|percent(?:age)?\b|\bper\s+cent\b)",
    # (4) A holistic quality phrase — an overall-quality verdict on the work.
    #     "one of the strongest answers in the class" is ADV-11's named attack;
    #     "among the strongest" and "a model response" are CT-SYNTH-C13's declared
    #     pass-throughs, and the graded-object nouns keep science prose
    #     ("the strongest evidence for the hypothesis") out of the net. The
    #     "one of the most ..." branch carries the same graded-object constraint
    #     (the reviewer's #98 finding): "one of the most impressive submissions" is
    #     a verdict and matches, while "one of the most common misconceptions" —
    #     ordinary feedback prose a temperature-0.0 re-request could not rephrase —
    #     passes.
    r"\bone of the (?:strongest|best|finest|weakest|poorest|"
    r"most\s+(?:\w+\s+)?(?:answers?|submissions?|responses?|scripts?|"
    r"pieces\s+of\s+work|attempts?|essays?))\b",
    r"\b(?:strongest|best|finest|weakest)\s+"
    r"(?:answers?|submissions?|responses?|scripts?|pieces\s+of\s+work)\s+"
    r"in\s+the\s+(?:class|cohort)\b",
    r"\btop of the (?:class|cohort)\b",
    r"\b(?:an?\s+)?(?:excellent|outstanding|superb|exceptional)\s+"
    r"(?:answers?|submissions?|responses?|pieces?\s+of\s+work|standard)\b",
)


@lru_cache(maxsize=8)
def _compiled_score_claim_patterns(
    patterns: tuple[str, ...],
) -> tuple["re.Pattern[str]", ...]:
    """The pattern list compiled, cached by VALUE — a changed list (CT-SYNTH-11's
    externally visible change) recompiles, the same list never does."""
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)


def has_score_claim(text: str) -> bool:
    """The score-claim predicate (`FR-SYNTH-03`): True when the text matches any
    configured pattern — a numeral-bearing score claim or an overall-quality verdict.

    Pure and total (`TC-SYNTH-04`): a `bool` for every input, never a raise — the
    re-request ladder branches on this predicate, so a crash here would be a crash on
    whatever the model replies next. Case-insensitive over `SYNTH_SCORE_CLAIM_PATTERNS`
    as compiled at the call; an empty pattern list rejects nothing."""
    return any(
        pattern.search(text) is not None
        for pattern in _compiled_score_claim_patterns(tuple(SYNTH_SCORE_CLAIM_PATTERNS))
    )
