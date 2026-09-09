"""`TC-SYNTH-04` — the score-claim check discriminates (`M-SYNTH`, TS-37, P0, unit,
rung 0, negative).

FR-SYNTH-03's configured pattern classes: a numeral adjacent to a mark word, "out of", a
percentage, and a holistic quality phrase. The first four narratives below match those
classes and are **rejected** (the re-request behaviour itself is TC-SYNTH-06's
integration case — this unit case is the pattern scan); the fifth, a clean
criterion-anchored narrative, passes. The final two passing cases are the
**discrimination** requirement the plan states outright: a narrative whose only numeral
is legitimate content ("she calculated 12 kg") must pass, or the check is a numeral
ban, not a score-claim ban — and a check that cannot discriminate silences every
science answer in the cohort.

Written ahead of `#98` (test plan §8.2): fails only through `NotImplementedYet` naming
`#98`, or — once the check lands — through the assertion itself.

Interface assumed of `#98` (reconcile at landing, one line in
`tests/support/synth_vocabulary.py`): `aeh.synth.has_score_claim(text) -> bool`, a pure
module-level predicate — True means a claim matched — in the `verify_span` precedent for
a rung-0 entry point. The specific rejected strings are the plan's own two examples
("one of the strongest answers in the class" is ADV-11's named attack; "she calculated
12 kg" is the plan's own discrimination case) plus one obvious instance per remaining
pattern class; tightening the pattern list to catch more paraphrases is #98's
configuration freedom, and this file only asserts the classes FR-SYNTH-03 names.
"""

from __future__ import annotations

import pytest

from tests.support.impl import SYNTH_MODULE, require
from tests.support.synth_vocabulary import SCORE_CLAIM_CHECK, SCORE_CLAIM_ISSUE

pytestmark = pytest.mark.writtenahead

#: One narrative per pattern class FR-SYNTH-03 names, each with the claim a grader
#: would actually read as a second, competing grade.
REJECTED_NARRATIVES = {
    "numeral adjacent to a mark word": (
        "The response demonstrates consistent method; the answer earned 17 marks "
        "overall and the reasoning is easy to follow."
    ),
    "out of": (
        "A well-organised answer; the final solution is 17 out of 20 and the working "
        "is shown throughout."
    ),
    "percentage": (
        "The derivation is correct and complete; this response sits in the top 90% "
        "of the class for structure."
    ),
    "holistic quality phrase": (
        "The hypothesis is stated clearly and the table is cited; this is one of the "
        "strongest answers in the class."
    ),
}

#: Narratives that must PASS: the clean criterion-anchored form the module is supposed
#: to produce, and the plan's own discrimination case — legitimate content numerals.
PASSING_NARRATIVES = {
    "clean criterion-anchored narrative": (
        "The response states the freezing-point hypothesis in the introduction and "
        "cites the lab table; the derivation shows each substitution step, and the "
        "conclusion names the systematic error the data supports."
    ),
    "legitimate content numeral (the plan's discrimination case)": (
        "In the calculation section she calculated 12 kg for the reaction product, "
        "repeated the measurement 3 times, and cites the 2019 reference for the "
        "calibration constant."
    ),
}


def test_tc_synth_04_score_claim_patterns_are_rejected():
    """`TC-SYNTH-04` (P0, negative half) — every pattern class FR-SYNTH-03 names is
    rejected by the check, including ADV-11's named attack verbatim."""
    has_score_claim = require(SYNTH_MODULE, SCORE_CLAIM_CHECK, issue=SCORE_CLAIM_ISSUE)
    for pattern_class, narrative in REJECTED_NARRATIVES.items():
        assert has_score_claim(narrative) is True, (
            f"the {pattern_class} narrative was NOT flagged: {narrative!r} — FR-SYNTH-03 "
            "names this class as rejected-and-re-requested; a check that lets it through "
            "ships the student a second, competing grade (RISK-19)"
        )


def test_tc_synth_04_clean_and_content_numerals_pass():
    """`TC-SYNTH-04` (P0, discrimination half) — a clean criterion-anchored narrative
    passes, and a legitimate content numeral ("she calculated 12 kg") passes: the check
    must discriminate, not ban numerals."""
    has_score_claim = require(SYNTH_MODULE, SCORE_CLAIM_CHECK, issue=SCORE_CLAIM_ISSUE)
    for case, narrative in PASSING_NARRATIVES.items():
        assert has_score_claim(narrative) is False, (
            f"the {case} was flagged as a score claim: {narrative!r} — the check must "
            "discriminate score claims from content; a numeral ban silences every "
            "science answer in the cohort and is not the check FR-SYNTH-03 configured"
        )


def test_tc_synth_04_check_is_pure_and_total():
    """`TC-SYNTH-04` (supporting, rung 0) — the predicate is total over the input space
    a narrative actually occupies: empty text, the empty narrative a failed re-request
    can leave, and a claim split across the sentence boundary all return a bool without
    raising, so the re-request ladder can never crash on what the check sees."""
    has_score_claim = require(SYNTH_MODULE, SCORE_CLAIM_CHECK, issue=SCORE_CLAIM_ISSUE)
    for text in ("", " ", "\n", "score", "17", "out of", "the mark scheme says 17"):
        result = has_score_claim(text)
        assert isinstance(result, bool), (
            f"has_score_claim({text!r}) returned {type(result).__name__}, not bool — "
            "the re-request ladder branches on this predicate, so a non-bool is a "
            "crash waiting on whatever the model replies next"
        )
