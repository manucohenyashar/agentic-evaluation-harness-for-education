"""`TC-SYNTH-C13` — the pattern check's boundary, and the honest presentation (§6.11.13).

`CT-SYNTH-13` is a **non-promise, and a declared known weakness** — the case asserts
the BOUNDARY of `CT-SYNTH-03`, not a capability. Two halves:

- **The pass boundary (rung 0, green).** Paraphrased quality claims that carry no
  numeral — "this is among the strongest answers", "a model response" — PASS the
  pattern check. That is the promised behaviour, and asserting it is what stops
  `FR-SYNTH-04`'s guarantee being read as stronger than it is: the check is a
  pattern screen, and paraphrase is its declared, recorded blind spot (§7.3 and
  §7.4 residual risk, with the automated verification still `TBD`). The half is
  pinned WITH a discriminator — a verbatim claim the same check catches — so the
  passes are boundary passes, not the silence of a check that never runs.
- **The consumer language (rung 3, written ahead).** No consumer relies on the
  absence of implied quality claims: `M-CONSOLE` and `M-STATS` must not present
  narrative as **verified score-free**, only as **pattern-checked**. The sweep is
  affirmative-claim-shaped (the TS-74 lesson: a naive net fails the disclaimer the
  clause itself requires, so sentences carrying a negation are dropped before
  matching), and the console must still name the check as a pattern check — the
  honest presentation is required, not merely the absence of the overclaim.

Relationship to shipped cases: `tests/unit/synth/test_score_claim_patterns.py`
(`TC-SYNTH-04`) pins the default list's classes; `tests/security/synth/
test_adv_11_score_claim_paraphrase.py` (ADV-11) owns the attack axis — the
paraphrases an adversary would use. This case owns the BOUNDARY as a contract
statement: the exact fixture sentences that pass, and the presentation language
consumers owe.

Isolation: rung 0 for the boundary (pure string predicates, no store); rung 3 for
the consumer sweep, written ahead of both consumers and registered in
`WRITTEN_AHEAD_BLOCKERS` under `"#100 language consumers (C13)"`.
"""

from __future__ import annotations

import re

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as stats_vocab
from tests.support.impl import CONSOLE_MODULE, STATS_MODULE, SYNTH_MODULE, require
from tests.support.orch_run import seed_run
from tests.support.synth_vocabulary import (
    FIVE_QUESTION_CRITERIA,
    SYNTH_ISSUE,
    WORKER,
    CaptureProvider,
    narrative_completion,
    seed_scored_submission,
    synth_ref,
)

pytestmark = [pytest.mark.contract]

#: The clause's own paraphrase fixtures — quality claims with no numeral, which the
#: pattern check PASSES. `among the strongest` deliberately avoids the holistic
#: class's `one of the` phrasing, and the sentence stops short of
#: `strongest answers in the class` (the second holistic pattern's shape).
_PARAPHRASE_1 = "This is among the strongest answers."
_PARAPHRASE_2 = "Overall, a model response to this task."

#: The discriminator — the verbatim class the patterns name, which the SAME check
#: catches. Without it the two passes above would also describe a check that never
#: runs.
_VERBATIM_CLAIM = "This is one of the strongest answers in the class."

#: Affirmative sentences that present narrative as VERIFIED score-free — the
#: presentation `CT-SYNTH-13` forbids. Multi-word terms, matched as substrings of a
#: sentence, after negated sentences are dropped: a consumer that prints the honest
#: disclaimer ("pattern-checked, not verified score-free") must survive the sweep,
#: or the net gets switched off by the first person it fails (the TS-74 lesson).
_VERIFIED_SCORE_FREE_CLAIMS = (
    "verified score-free",
    "verified free of score claims",
    "verified to contain no score claims",
    "confirmed score-free",
    "guaranteed free of score claims",
    "quality verified",
    "verified quality",
    "narratives are verified",
)

#: Fragments that make a sentence a denial rather than the claim. Generous on
#: purpose — a false negative weakens one sweep; a false positive fails the honest
#: copy the clause requires.
_NEGATIONS = (
    "not ", "no ", "never", "cannot", "can not", "does not", "must not",
    "without", "unable", "isn't", "aren't", "don't", "doesn't", "unverified",
    "pattern-check", "pattern check",
)

#: The honest presentation: the clause says "only as pattern-checked", and these are
#: the spellings of that phrase a rendered page may carry.
_PATTERN_CHECK_DISCLOSURE = ("pattern-check", "pattern check")


def _affirmative_verified_claims(text: str) -> list[str]:
    """The sentences in `text` that affirmatively present narrative as verified
    score-free. Sentences are split on terminators; any carrying a negation (or the
    honest pattern-check phrase) is dropped before the terms are matched."""
    sentences = [part.strip() for part in re.split(r"[.!?\n]+", text) if part.strip()]
    return [
        sentence
        for sentence in sentences
        if not any(marker in sentence.lower() for marker in _NEGATIONS)
        and any(term in sentence.lower() for term in _VERIFIED_SCORE_FREE_CLAIMS)
    ]


def test_tc_synth_c13_paraphrased_claims_pass_the_check():
    """`TC-SYNTH-C13` (P0, rung 0) — the boundary, asserted as the promise's edge:
    the clause's paraphrase fixtures pass `has_score_claim`, and the verbatim claim
    the patterns name does not. A change that starts catching the paraphrases is a
    CONTRACT CHANGE (`FR-SYNTH-04`'s guarantee is a pattern screen, and the recorded
    blind spot is the design's declared residual risk), not a silent tightening."""
    has_score_claim = require(SYNTH_MODULE, "has_score_claim", issue=SYNTH_ISSUE)

    for text in (_PARAPHRASE_1, _PARAPHRASE_2):
        assert not has_score_claim(text), (
            f"has_score_claim({text!r}) is True — the check caught a paraphrased "
            "quality claim with no numeral. CT-SYNTH-13 declares this the check's "
            "BOUNDARY: the guarantee is a pattern screen, and swallowing the "
            "paraphrase class silently widens the prohibition past the design's "
            "recorded residual risk (§7.3, §7.4)"
        )

    assert has_score_claim(_VERBATIM_CLAIM), (
        "control failed: has_score_claim missed the verbatim claim the patterns "
        "name — the two passes above would then describe a check that never runs, "
        "not a boundary (TC-SYNTH-04 pins the classes; ADV-11 the attack axis)"
    )


def _pattern_checked_world(tmp_data_dir):
    """The `TC-SYNTH-C03` world — one flagged question, four clean — so the consumer
    sweep runs against narratives the check has actually screened, flagged row
    included in storage."""
    from aeh.store import open_store

    _CLAIM_FIRST = (
        "Question 3: the working is careful and the method is sound; this is one of "
        "the strongest answers in the class."
    )
    _CLEAN = (
        "Question {n}: the response states the hypothesis and cites the worked "
        "steps for this question."
    )
    questions = tuple(f"Q{q}" for q in range(1, 6))
    store = open_store(tmp_data_dir)
    _, run_id, _ = seed_run(store, submissions=("SYN-001",), criteria=FIVE_QUESTION_CRITERIA)
    seed_scored_submission(store, run_id, "SYN-001", complete_questions=set(questions))
    replies = []
    for question in questions:
        if question == "Q3":
            replies.append(narrative_completion(_CLAIM_FIRST, ("Q3C1", "Q3C2")))
            replies.append(narrative_completion(_CLAIM_FIRST, ("Q3C1", "Q3C2")))
        else:
            replies.append(
                narrative_completion(
                    _CLEAN.format(n=question[1:]), (f"{question}C1", f"{question}C2")
                )
            )
    replies.append(narrative_completion("Overall: the submission works through each question in turn."))
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
    Worker(store, CaptureProvider(replies), synth_ref()).synthesize_submission(
        run_id, "SYN-001"
    )
    return store, run_id


def test_tc_synth_c13_consumers_present_narrative_as_pattern_checked_not_verified(
    tmp_data_dir,
):
    """`TC-SYNTH-C13` (P0, rung 3) — the consumer language assertion: `M-CONSOLE`'s
    student page and `M-STATS`'s narrative-quality surface must not present
    narrative as VERIFIED score-free, only as pattern-checked. A consumer that
    upgrades a pattern screen into a verification claim turns the design's declared
    blind spot into a promise nobody made (§7.3/§7.4 record the residual risk;
    `FR-SYNTH-04`'s automated verification is still `TBD`).

    Written ahead of both consumers (test plan §8.2); registered in
    `WRITTEN_AHEAD_BLOCKERS` under `"#100 language consumers (C13)"` (symbols
    `aeh.console:build_console`, `aeh.stats:promote` — the #118-only symbol, per the
    shipped `"#118 stats"` entry's keying, since the narrative-quality member lands
    with that story). The console surface is disclosed in
    `tests/support/console_vocabulary.py` (`/students/{ref}`, `RenderedPage.html`);
    the stats surface in `tests/support/stats_vocabulary.py` (`build_stats`,
    `.narrative_quality`).
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    require(STATS_MODULE, "narrative_quality", issue="#118")  # the member this sweep drives

    store, run_id = _pattern_checked_world(tmp_data_dir)
    try:
        provider = CaptureProvider([])  # dry: the console must not re-call the model
        app = build_console(cohort_size=1, provider=provider)
        page = app.render("/students/SYN-001")

        claims = _affirmative_verified_claims(page.html)
        assert not claims, (
            f"the student page affirms verified-score-free narrative at {claims[:2]} "
            "— M-CONSOLE must present narrative as PATTERN-CHECKED, only that "
            "(CT-SYNTH-13): the screen has a declared paraphrase blind spot, and "
            "presenting its pass as verification claims more than the design "
            "promises"
        )
        page_lower = page.html.lower()
        assert any(term in page_lower for term in _PATTERN_CHECK_DISCLOSURE), (
            "the student page never names the check as a pattern check — 'only as "
            "pattern-checked' is the honest presentation CT-SYNTH-13 requires, and "
            "its absence leaves the narrative's status unreadable to the teacher "
            "who must judge how much to trust it"
        )

        # M-STATS's narrative-quality surface: figures, never verification verdicts.
        # The metric names are CT-STATS-14's declared three; the sweep borrows that
        # suite's forbidden-verdict vocabulary and adds the verification claims this
        # clause names.
        stats = build_stats(labels=broken.agreeing_population())
        report = stats.narrative_quality(cohort_id="coh-1")
        names = [name for name in dir(report) if not name.startswith("_")]
        assert names, (
            "the narrative-quality report exposes no public names, so the sweep "
            "would pass vacuously"
        )
        forbidden = set(stats_vocab.FORBIDDEN_VERDICT_FIELDS) | {
            "verified", "score_free", "score-free", "claim_free", "claim-free",
            "quality_verified", "verified_score_free",
        }
        offenders = [
            name for name in names
            if name.lower() in forbidden
            or any(token in re.split(r"[^a-z0-9]+", name.lower()) for token in
                   ("verified", "score_free", "claim_free", "quality_verified"))
        ]
        assert not offenders, (
            f"the narrative-quality report carries {offenders} — a verification "
            "verdict on the narrative surface presents the pattern screen as "
            "verified score-free (CT-SYNTH-13); the rates are measured, never gated "
            "(§2.3 Q-06), and the presentation must say the same"
        )
    finally:
        store.close()
