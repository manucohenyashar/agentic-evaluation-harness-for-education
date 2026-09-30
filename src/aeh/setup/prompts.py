"""The instructions sent to the model at each setup step."""

from __future__ import annotations


_INVENTORY_INSTRUCTION = (
    "You are reading one assessment document and proposing the question inventory a "
    "grading package will be built from (HLD §7.8, Phase 1 — propose once, from the "
    "document alone). For every question the document asks:\n"
    "- question_type is 'mcq' when the question enumerates options or answer markers "
    "(lettered options, checkboxes, a 'circle one' instruction); 'open' when it names "
    "a ruled response area with nothing to mark; 'mixed' when one question carries "
    "both a marked part and a written part.\n"
    "- For every mcq or mixed question include the full option set exactly as "
    "printed, one entry per option, with the option's printed id and label.\n"
    "- Copy prompt_text verbatim from the document; set ordinal to the question's "
    "printed number and max_points to its printed marks (0 when the document shows "
    "none).\n"
    "- Propose only what the document contains: no invented questions, no merged or "
    "split questions, and no answer key — the teacher declares keys in a separate "
    "blocking step.\n"
    "Reply with ONLY a JSON object, no prose, of this shape — note an open question "
    "carries an EMPTY options list, and only mcq/mixed carry entries in it:\n"
    '{"questions": [{"question_id": "Q1", "ordinal": 1, "prompt_text": "...", '
    '"question_type": "open", "max_points": 4, "options": []}, '
    '{"question_id": "Q2", "ordinal": 2, "prompt_text": "...", '
    '"question_type": "mcq", "max_points": 2, "options": [{"option_id": "A", '
    '"ordinal": 0, "label": "..."}]}]}'
)


_READBACK_INSTRUCTION = (
    "You are reading one rubric document and proposing the criteria and band sets a "
    "grading package will judge against (HLD §7.8, Phase 1 — read back, never improve: "
    "correcting a rubric is a gated, separate step the teacher owns). Anchor every "
    "criterion to a question the confirmed inventory carries.\n"
    "- kind is 'open' when the criterion judges written work, 'mcq' when it judges a "
    "marked choice; scoring_model is 'atomic' when the criterion stands alone, "
    "'holistic' when it can only be judged as a whole.\n"
    "- band_count must be an EVEN number in 2..6. Omit it and bands entirely when the "
    "criterion is a met / not met judgment — the two-band default is derived for you.\n"
    "- Propose explicit bands ONLY where partial credit is genuinely part of the "
    "construct, and then carry a 'justification' string saying what earns the partial "
    "credit.\n"
    "- Rank bands BEST-FIRST: ordinal 1 is the best band, and points descend to the "
    "worst. The stored ordering is fixed afterwards; your ranking is what is read.\n"
    "- Every band descriptor must state what a response IN THAT BAND DOES — the "
    "observable action, not a quality judgment. NEVER use the words good, excellent, "
    "weak, adequate, or 'out of', and never write a numeral anywhere in a descriptor: "
    "a descriptor containing a number is a points scale leaking into the language the "
    "judge sees, and it will be rejected.\n"
    "- evidence_type names what kind of textual evidence satisfies the criterion "
    "(omit it to take the default).\n"
    "Reply with ONLY a JSON object, no prose, of this shape:\n"
    '{"criteria": [{"criterion_id": "CRIT-1", "question_id": "Q1", "kind": "open", '
    '"scoring_model": "holistic", "max_points": 4, '
    '"construct": "what the criterion asks for, behaviourally", '
    '"evidence_type": "textual_span", '
    '"bands": [{"band": "met", "ordinal": 1, "points": 4, "descriptor": "the response '
    'does ..."}, {"band": "not met", "ordinal": 2, "points": 0, "descriptor": "the '
    'response does not ..."}]}]}'
)


_CLASSIFY_INSTRUCTION = (
    "You are answering the five decomposability questions for ONE grading criterion "
    "(HLD §5.3): they decide whether a judge can score this criterion in isolation on "
    "one response, or only as a whole. Do NOT classify the criterion yourself — answer "
    "the questions; the system applies the decision table.\n"
    "Answer each question 'yes', 'no', or 'unclear':\n"
    "- completeness: is everything the criterion judges present in the response "
    "segment it is scored on, on its own?\n"
    "- non_interference: can the criterion's evidence be gathered without being "
    "distorted by how another criterion's evidence is gathered?\n"
    "- independence: does the judgment not depend on the outcome of another "
    "criterion's judgment?\n"
    "- additivity: can the criterion's score be combined additively with the others "
    "without double counting or interaction effects?\n"
    "- gates: can the criterion be scored with NO precondition (a gate) that has "
    "to hold before it can be scored at all? Answer 'no' when such a gate exists — "
    "every question here is phrased so that 'yes' means the criterion passes it, "
    "and the decision table reads a 'no' on gates as 'this criterion carries a "
    "gate'.\n"
    "- warning_signs: list anything about the criterion that warns against decomposing "
    "it (straddling two constructs, mixed scales, ...); an empty list when none.\n"
    "Use 'unclear' whenever the criterion's text does not settle a question — never "
    "guess.\n"
    "Reply with ONLY a JSON object, no prose, of this shape:\n"
    '{"criterion_id": "CRIT-1", "answers": {"completeness": "yes", '
    '"non_interference": "yes", "independence": "unclear", "additivity": "no", '
    '"gates": "yes"}, "warning_signs": ["straddles two constructs"], '
    '"reasoning": "what the criterion text shows for the answers given"}'
)


_DEPENDENCIES_INSTRUCTION = (
    "You are proposing criterion dependencies for a grading package (FR-SETUP-10). A "
    "dependency makes one criterion's grading SEE the evidence credited under another "
    "criterion — a contamination channel that must earn its place — so propose an edge "
    "ONLY where the subject itself makes error-carried-forward likely (a later "
    "criterion graded on work that presupposes an earlier criterion's construct). "
    "Every criterion you do not name keeps its default of zero dependencies.\n"
    "- criterion_id is the LATER criterion whose grading would see the earlier work; "
    "depends_on is the EARLIER one whose credited work it presupposes.\n"
    "- reason states, in the subject's own terms, what the later criterion's grading "
    "presupposes.\n"
    "Reply with ONLY a JSON object, no prose, of this shape — an empty list when "
    "nothing is likely:\n"
    '{"dependencies": [{"criterion_id": "CRIT-4", "depends_on": "CRIT-2", '
    '"reason": "error carried forward: the derivation is graded on work that '
    'presupposes the definition"}]}'
)
