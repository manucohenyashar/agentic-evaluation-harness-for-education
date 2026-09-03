"""The vocabulary TS-74 is written against, checked against the design documents.

Issue #142. **These test the fixture, not `M-CALIB`.** Every one of the sixteen clause cases in
this suite is written ahead of a module three stories away — `M-CALIB`'s first story (#137) is
itself blocked on four others, and the module is Phase 3/4. A suite that sits red for two phases
drifts, and what drifts first is its vocabulary.

So these assert that `tests/support/calib_vocabulary.py` still says what the design says. They are
green today and they are **not coverage of any clause** — nobody should count them as such. What
they buy is that when `CT-CALIB` moves, the suite goes red at the transcription rather than
quietly encoding a contract nobody agreed to. §4.7 marks this contract **provisional**, so it will
move.

Read against the design files directly rather than against `M-CALIB`, because there is no
`M-CALIB` to read against — that is the whole situation this file exists for.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.support.calib_vocabulary import (
    ACCURACY_LANGUAGE,
    DECLARED_KNOBS,
    DECLARED_PHASES,
    SUPERIORITY_LANGUAGE,
    affirmative_sentences,
    EDITABLE_CATEGORY,
    EXAMPLES_PER_QUESTION,
    LOCKED_FIELDS,
    MAX_QUESTIONS,
    PROTOCOL_MEMBERS,
    TRIAGE_CATEGORIES,
)

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
DESIGN = (REPO_ROOT / "docs" / "design" / "detailed-design.md").read_text(encoding="utf-8")


def test_the_triage_categories_are_the_three_the_design_names():
    """`CT-CALIB-04` / `FR-CALIB-02` name exactly three, and the set is closed.

    Closed matters: an uncategorized disagreement would default into the editable path, which is
    what `TC-CALIB-C04` asserts is refused. A fourth category added to the design without being
    added here would make that sweep incomplete and nothing would say so.
    """
    clause = next(line for line in DESIGN.splitlines() if line.startswith("| CT-CALIB-04 "))

    # Parsed **generically**, not by alternating over the fixture's own three names. The first
    # draft did the latter, which made `named` a subset of `TRIAGE_CATEGORIES` by construction —
    # so a fourth category added to the design was invisible, which is the exact case this
    # docstring claims to catch. Review added `extraction_defect` and watched six green tests.
    #
    # The clause states its categories as a set, so that is what is read.
    membership = re.search(r"∈ \{([^}]*)\}", clause)
    assert membership, "CT-CALIB-04 no longer states its triage categories as a set"
    named = set(re.findall(r"`([a-z_]+)`", membership.group(1)))

    assert named == TRIAGE_CATEGORIES, (
        f"the design's CT-CALIB-04 names {sorted(named)}; the fixture carries "
        f"{sorted(TRIAGE_CATEGORIES)}"
    )
    assert EDITABLE_CATEGORY in TRIAGE_CATEGORIES
    assert "only `rubric_ambiguity`" in clause, (
        "CT-CALIB-04 no longer says only rubric_ambiguity is eligible to produce an edit — the "
        "eligibility half of TC-CALIB-C04 is written against that wording"
    )


def test_the_declared_knob_values_match_the_clause():
    """`CT-CALIB-13`'s three knobs and the values the design declares.

    `CALIB_NONINFERIORITY_THRESHOLD` is asserted here as the design's **example**, not as a live
    default — the clause says it is *"an example value from the HLD, not a validated one"* and
    *"must be declared per institution before use"*. The behaviour that follows (the gate refuses
    to run when nothing is declared) is `TC-CALIB-C13`'s, and lives in its own test so the two
    claims stay apart.
    """
    clause = next(line for line in DESIGN.splitlines() if line.startswith("| CT-CALIB-13 "))

    for knob in DECLARED_KNOBS:
        assert f"`{knob}`" in clause, f"the design's CT-CALIB-13 no longer names {knob}"

    assert "`CALIB_MAX_QUESTIONS` (6)" in clause
    assert "0.10" in clause
    assert DECLARED_KNOBS["CALIB_MAX_QUESTIONS"] == 6
    assert DECLARED_KNOBS["CALIB_NONINFERIORITY_THRESHOLD"] == 0.10
    assert "not a validated one" in clause and "declared per institution" in clause, (
        "CT-CALIB-13 no longer says the threshold is unvalidated and must be declared per "
        "institution — TC-CALIB-C13's refusal assertion rests on that wording"
    )


def test_the_teacher_time_budget_matches_nfr_calib_01():
    """`NFR-CALIB-01`: *"at most six questions answerable from two student examples shown side by
    side"*. Both numbers, because `TC-CALIB-C12` asserts an interaction count **and** a
    per-question payload."""
    requirement = next(line for line in DESIGN.splitlines() if line.startswith("| NFR-CALIB-01 "))

    assert "six questions" in requirement
    assert "two student examples" in requirement
    assert MAX_QUESTIONS == 6
    assert EXAMPLES_PER_QUESTION == 2
    assert DECLARED_KNOBS["CALIB_MAX_QUESTIONS"] == MAX_QUESTIONS, (
        "the knob and the NFR disagree about the cap"
    )


def test_the_locked_field_list_matches_fr_pkg_03():
    """The §6.2 lock, which `TC-CALIB-C06` sweeps from `M-CALIB`'s side.

    Transcribed from `FR-PKG-03`, which enumerates it, rather than from `FR-CALIB-07`, which
    summarizes it. `NFR-PKG-03` requires the list to exist *"in exactly one place in the source and
    be enumerable at runtime, so a test can assert the list matches HLD §6.2"* — when `M-PKG`
    lands, `TC-CALIB-C06` should read it from there and this fixture becomes the cross-check.
    """
    requirement = next(line for line in DESIGN.splitlines() if line.startswith("| FR-PKG-03 "))

    # An explicit phrase-to-field mapping, not a substring sweep over `LOCKED_FIELDS`. Six of the
    # seven are named verbatim in `FR-PKG-03`; the seventh is the *prose* "adding or removing a
    # criterion", for which `criterion_count` is this fixture's label rather than the design's
    # word. A naive forward check flagged it, correctly — the fixture's names and the design's
    # phrasing are not the same vocabulary, and pretending otherwise is how a transcription check
    # starts lying.
    LOCK_PHRASES: tuple[tuple[str, str], ...] = (
        ("max_points", "max_points"),
        ("adding or removing a criterion", "criterion_count"),
        ("question_type", "question_type"),
        ("scoring_model", "scoring_model"),
        ("construct_tag", "construct_tag"),
        ("criterion_band", "criterion_band"),
        ("criterion_dependency", "criterion_dependency"),
    )

    for phrase, field in LOCK_PHRASES:
        assert phrase in requirement, f"FR-PKG-03 no longer forbids {phrase!r}"
        assert field in LOCKED_FIELDS, f"the fixture does not cover FR-PKG-03's {phrase!r}"

    # And nothing extra: a fixture entry with no clause behind it would widen `TC-CALIB-C06`'s
    # sweep into fields the lock never claimed, which fails against a correct `M-PKG`.
    assert set(LOCKED_FIELDS) == {field for _, field in LOCK_PHRASES}, (
        f"the fixture's lock list carries entries FR-PKG-03 does not: "
        f"{sorted(set(LOCKED_FIELDS) - {f for _, f in LOCK_PHRASES})}"
    )

    # The direction the mapping alone cannot see: a field `FR-PKG-03` forbids that neither the
    # mapping nor the fixture mentions. `LOCK_PHRASES` is hand-written, so checking the fixture
    # against it is closed over the author's own list — review added an eighth locked field to the
    # design and watched six green tests. Every backticked identifier in the requirement is read
    # instead, and each must be accounted for by the mapping.
    design_fields = set(re.findall(r"`([a-z][a-z_]+)`", requirement))
    unaccounted = sorted(
        field for field in design_fields
        if field not in LOCKED_FIELDS
        and not any(field in phrase for phrase, _ in LOCK_PHRASES)
    )
    assert not unaccounted, (
        f"FR-PKG-03 names fields the fixture's lock list does not cover: {unaccounted}. "
        "TC-CALIB-C06 sweeps LOCKED_FIELDS, so an uncovered field is one M-CALIB could write "
        "without this suite noticing."
    )


def test_the_protocol_members_match_the_interfaces_block():
    """Design §3.17's `Calibration` protocol, transcribed.

    `TC-CALIB-C15` asserts a **phase** per member, so the member list has to be the design's rather
    than whatever the module eventually exposes — a member added to `M-CALIB` without a declared
    phase is exactly what that case exists to catch.
    """
    block = DESIGN[DESIGN.index("class Calibration(Protocol):"):]
    block = block[: block.index("```")]

    declared = tuple(re.findall(r"def (\w+)\(", block))

    assert declared == PROTOCOL_MEMBERS, (
        f"design §3.17 declares {declared}; the fixture carries {PROTOCOL_MEMBERS}"
    )


def test_the_contract_is_still_marked_provisional():
    """The premise this whole suite is written under, asserted rather than assumed.

    §4.7 marks `CT-CALIB` **provisional** and §6.11.17 puts its blast radius at *"near-zero,
    deliberately"*. That is why sixteen red cases against it are worth having — the issue's Goal is
    *"a contract change shows up as a red case rather than as drift"* — and it is also why they
    will churn. The day the contract firms up, this assertion fails and somebody re-reads the
    suite, which is the intended outcome rather than an inconvenience.
    """
    plan = (REPO_ROOT / "docs" / "design" / "test-plan.md").read_text(encoding="utf-8")

    heading = next(
        line for line in plan.splitlines() if line.startswith("#### 6.11.17 ")
    )

    assert "provisional" in heading.lower(), (
        "§6.11.17 no longer marks CT-CALIB provisional. These sixteen cases were written against "
        "a contract the design said was still moving; re-read them against the settled one."
    )


def test_the_editable_category_is_rubric_ambiguity_exactly():
    """`EDITABLE_CATEGORY` is pinned to a value, not merely to membership.

    The first draft asserted only `EDITABLE_CATEGORY in TRIAGE_CATEGORIES`, which holds for all
    three. Drifted to `"model_failure"`, `TC-CALIB-C04`'s eligibility sweep would demand that
    `model_failure` produce edits and `rubric_ambiguity` not — the exact inversion of the clause,
    with a green vocabulary suite sitting above it. Review found it by mutation: one character,
    six passing tests.
    """
    assert EDITABLE_CATEGORY == "rubric_ambiguity"
    clause = next(line for line in DESIGN.splitlines() if line.startswith("| CT-CALIB-04 "))
    assert f"only `{EDITABLE_CATEGORY}`" in clause


def test_every_protocol_member_has_a_declared_phase():
    """`CT-CALIB-15` asserts a phase per member, so every member must have one.

    This ran inside the written-ahead `TC-CALIB-C15` test, where it could not execute — and it was
    **broken**: `apply_answers` had no entry, so the case would have failed *after* `M-CALIB`
    landed, masked until then by `require()`. An `or member == "discover"` escape hatch showed the
    same thing had already happened once and been patched rather than fixed.

    It touches no implementation, so it belongs here, green, where a gap is visible today.
    """
    missing = [member for member in PROTOCOL_MEMBERS if member not in DECLARED_PHASES]

    assert not missing, (
        f"these Calibration protocol members have no declared phase: {missing}. CT-CALIB-15 says "
        "phasing is part of the contract, which is not true of a member without one."
    )
    assert set(DECLARED_PHASES.values()) <= {1, 3, 4}, "an undeclared phase number appeared"
    assert DECLARED_PHASES["elicit"] == 4 and DECLARED_PHASES["apply_answers"] == 4, (
        "CT-CALIB-15 puts elicitation in Phase 4"
    )
    assert DECLARED_PHASES["schema_lock"] == 1, (
        "the §6.2 lock is Phase 1 and belongs to M-PKG — the dependency direction C15 asserts"
    )


def test_the_declared_phases_match_the_clause():
    """The phases, read from `CT-CALIB-15` rather than trusted."""
    clause = next(line for line in DESIGN.splitlines() if line.startswith("| CT-CALIB-15 "))

    assert "Phase 3" in clause and "Phase 4" in clause and "Phase 1" in clause
    for member in ("Triage", "non-inferiority", "back-translation"):
        assert member in clause, f"CT-CALIB-15 no longer names {member} among the Phase 3 work"
    assert "elicitation is Phase 4" in clause


def test_the_language_lists_are_populated_and_negation_scoped():
    """The two consumer-language lists, and the scan that uses them.

    Gutting either list is a mutation the rest of this file cannot see — the lists are only read
    by written-ahead tests — so it is asserted here. And the negation scoping is asserted in both
    directions, because it is the difference between forbidding a claim and forbidding the
    disclaimer the clause requires.
    """
    assert len(ACCURACY_LANGUAGE) >= 8, "the accuracy vocabulary has been emptied"
    assert len(SUPERIORITY_LANGUAGE) >= 6, "the superiority vocabulary has been emptied"

    correct = "Gate: PASS (non-inferiority). This is not evidence the revision improved the rubric."
    overclaiming = "Gate: PASS. The revision improved the rubric."

    assert not [t for t in SUPERIORITY_LANGUAGE
                if any(t in s.lower() for s in affirmative_sentences(correct))], (
        "the scan rejects a console stating CT-CALIB-16's own disclaimer"
    )
    assert [t for t in SUPERIORITY_LANGUAGE
            if any(t in s.lower() for s in affirmative_sentences(overclaiming))], (
        "the scan accepts a console claiming the revision improved the rubric"
    )
