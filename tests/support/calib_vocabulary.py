"""The vocabulary `M-CALIB`'s clause suite is written against, transcribed from the design.

TS-74 (issue #142) implements sixteen `CT-CALIB` clause cases, and every one of them is written
ahead of a module three stories away — `M-CALIB` is Phase 3/4 and its first implementing story
(#137) is itself blocked on four others. A suite that sits red for two phases drifts, and the
thing that drifts first is its vocabulary: the triage categories, the knob values, the list of
fields the schema lock forbids.

So the vocabulary lives here as **literals transcribed from the design**, and
`tests/contract/calib/test_ct_calib_vocabulary.py` asserts them. Those assertions are green today
and they are worth being precise about: they test that *this fixture still matches the design*,
not that `M-CALIB` does anything. Nobody should count them as coverage of a clause. What they buy
is that when the contract moves — and §4.7 marks `CT-CALIB` **provisional**, so it will — the
suite goes red at the vocabulary rather than quietly encoding a rubric nobody agreed to.

Every constant below carries the clause or requirement it came from, so the transcription is
checkable by reading rather than by trusting.
"""

from __future__ import annotations

#: `CT-CALIB-04` / `FR-CALIB-02`: *"Every disagreement shall carry an explicit triage category —
#: `rubric_ambiguity`, `model_failure`, or `teacher_inconsistency` — as a required output field."*
TRIAGE_CATEGORIES: frozenset[str] = frozenset(
    {"rubric_ambiguity", "model_failure", "teacher_inconsistency"}
)

#: The one category eligible to produce a proposed edit (`CT-CALIB-04`). The other two are the
#: point of the clause: `teacher_inconsistency` is *"never fitted to"* (`FR-CALIB-03`), because
#: fitting the rubric to one teacher's noise encodes it into the instrument permanently, and
#: `model_failure` produces a pipeline finding and no rubric edit at all (`FR-CALIB-04`).
EDITABLE_CATEGORY = "rubric_ambiguity"

#: `CT-CALIB-13`'s three knobs, with the values the design declares.
#:
#: **`CALIB_NONINFERIORITY_THRESHOLD` is not a default.** The clause is explicit that 0.10 is *"an
#: example value from the HLD, not a validated one"* and *"must be declared per institution before
#: use"* — so the number below is the design's example, and the *behaviour* the suite asserts is
#: that the gate **refuses to run** when no institutional value has been declared. Those are two
#: different claims and they live in two different tests, because a single test asserting both
#: would be asserting that 0.10 is simultaneously the default and not one.
DECLARED_KNOBS: dict[str, object] = {
    "CALIB_MAX_QUESTIONS": 6,
    "CALIB_NONINFERIORITY_THRESHOLD": 0.10,
    "CALIB_OFF_PANEL_MODEL": None,  # no declared default: NFR-CALIB-04 configures it separately
}

#: `NFR-CALIB-01` / `CT-CALIB-12`: *"at most six questions answerable from two student examples
#: shown side by side"*. Both numbers are asserted — the cap, and the two examples per question.
MAX_QUESTIONS = 6
EXAMPLES_PER_QUESTION = 2

#: The HLD §6.2 lock, verbatim from `FR-PKG-03`: *"changing a criterion's `max_points`, adding or
#: removing a criterion, changing `question_type`, changing `scoring_model`, changing
#: `construct_tag`, changing any `criterion_band` row (label, ordinal, descriptor, or points), and
#: adding, removing or altering a `criterion_dependency` row."*
#:
#: `CT-CALIB-06` sweeps this list **from `M-CALIB`'s side**, and the clause's value is that
#: `M-CALIB` needs no check of its own — every edit goes through `M-PKG`, so `FR-PKG-03`'s lock
#: applies to calibration output for free. A second check implemented here is the thing that would
#: drift (RISK-06), so the case asserts the refusal comes from the catalog.
LOCKED_FIELDS: tuple[str, ...] = (
    "max_points",
    "criterion_count",
    "question_type",
    "scoring_model",
    "construct_tag",
    "criterion_band",
    "criterion_dependency",
)

#: `CT-CALIB-15`: *"triage, dual-scoring non-inferiority and back-translation are Phase 3;
#: elicitation is Phase 4; the §6.2 lock they depend on is Phase 1 and belongs to `M-PKG`."*
#: Phasing is part of the contract, so it is asserted rather than assumed.
DECLARED_PHASES: dict[str, int] = {
    "triage": 3,
    "non_inferiority": 3,
    "back_translate": 3,
    "elicit": 4,
    "schema_lock": 1,  # M-PKG's, and the dependency direction C15 asserts
}

#: The `Calibration` protocol's members, from design §3.17's Interfaces block. Transcribed so
#: `TC-CALIB-C15` can assert the phase of each against `DECLARED_PHASES` rather than against
#: whatever the module happens to expose.
PROTOCOL_MEMBERS: tuple[str, ...] = (
    "discover",
    "triage",
    "elicit",
    "apply_answers",
    "non_inferiority",
    "back_translate",
)

#: Language a consumer must never use about discovery output (`CT-CALIB-03`) or about a passed
#: gate (`CT-CALIB-16`).
#:
#: Two distinct misreadings, and the clauses name both. Discovery is *"ambiguity discovery, never a
#: measurement of accuracy"* — the calibration set is far too small for an accuracy claim, and
#: `M-STATS` owns the ones that exist. A passed gate is *"not evidence that a revision improved the
#: rubric"* — only that the class did not shift beyond the declared threshold and an off-panel
#: model could not construct a divergent case.
ACCURACY_LANGUAGE: tuple[str, ...] = (
    "accuracy", "accurate", "correct rate", "correctness", "percent correct",
    "% correct", "right", "precision", "recall", "f1", "agreement rate",
)
SUPERIORITY_LANGUAGE: tuple[str, ...] = (
    "improved", "improvement", "better", "superior", "superiority",
    "more accurate", "higher quality", "upgrade",
)
