"""The green half of TS-72: the transcription checks, the rule controls, and the findings.

Nothing in this file tests `M-REVIEW`. `M-REVIEW` does not exist — it is four stories away and
every case in the other files in this directory is correctly red behind `writtenahead`. What runs
here is the *fixture's* correctness:

* **Transcription.** Every literal in `tests/support/review_vocabulary.py` is asserted against
  design §3.15 itself, so when the design moves the suite goes red at the transcription rather
  than quietly encoding a contract nobody agreed to. This is drift detection, not coverage.
* **Rule controls, in both directions.** Every detector the red cases apply is exercised against
  copy a correct implementation produces *and* copy its clause forbids. The first direction is
  what stops a rule going vacuous; the second is what stops it condemning compliant source, which
  is the failure that gets a rule switched off.
* **Six findings, asserted rather than described.** Each is a claim about the plan or the design,
  so each is a test that fails the day it is fixed — which is when somebody should be told.

Counting any of this as clause coverage would be a mistake, and §8.2 says as much: a green
written-ahead suite means the test is not asserting what it claims.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.support import broken_review_fixtures as broken
from tests.support import review_vocabulary as vocab
from tests.support.doc_tables import DocRowMissing, markdown_rows, read_repo_text

pytestmark = pytest.mark.contract

DESIGN = "docs/design/detailed-design.md"
TEST_PLAN = "docs/design/test-plan.md"

#: Module-scoped so the documents are read once for the whole file. Not the session's `repo_root`
#: fixture, which is function-scoped: pytest refuses that combination and the failure arrives as a
#: collection-time error rather than as a legible test failure.
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def design() -> str:
    return read_repo_text(REPO_ROOT, DESIGN)


@pytest.fixture(scope="module")
def plan() -> str:
    return read_repo_text(REPO_ROOT, TEST_PLAN)


@pytest.fixture(scope="module")
def section(design: str) -> str:
    """§3.15 alone, so a name that appears in a neighbouring module cannot satisfy a check here.

    `M-REVIEW` is named in eleven other modules' `Requires` blocks and in the traceability
    tables; a search over the whole document would find `provisional_unreviewed` in §3.12 and
    call the transcription verified.
    """
    start = design.index("### 3.15 Module: Review Queue")
    end = design.index("### 3.16 Module:", start)
    return design[start:end]


@pytest.fixture(scope="module")
def interfaces(section: str) -> str:
    """The Python block inside §3.15 — the part that is a declaration rather than prose."""
    opened = section.index("```python")
    closed = section.index("```", opened + len("```python"))
    return section[opened:closed]


@pytest.fixture(scope="module")
def design_rows(design: str) -> list[list[str]]:
    return markdown_rows(design)


def _row(rows: list[list[str]], identifier: str) -> list[str]:
    """The one table row whose **first cell** is `identifier`.

    `doc_tables.find_row` matches a needle anywhere in the row, and every `FR-REVIEW-*` and
    `CT-REVIEW-*` id appears again in the traceability tables and in neighbouring modules'
    `Requires` blocks — so a substring locator finds several rows and raises. It still raises
    rather than returning `None`: a locator that returns `None` turns a renamed row into a
    vacuous pass, which is the failure mode of every assertion built on top of it.
    """
    matches = [row for row in rows if row and row[0].strip(" `*") == identifier]
    if len(matches) != 1:
        raise DocRowMissing(
            f"{len(matches)} rows have {identifier!r} in the id column; expected exactly one"
        )
    return matches[0]


def _normalize(text: str) -> str:
    """Lowercase, with hyphens, underscores and backticks flattened to spaces.

    The design writes `evidence spans` and this suite holds it as `evidence_spans`; both are the
    same name and neither spelling is more correct. Word *order* is not flattened, so a
    transcription that reordered a field set still fails.
    """
    return re.sub(r"[\s`_\-–—]+", " ", text.lower()).strip()


def _tokens_present(name: str, text: str) -> bool:
    """Whether every word of `name` appears in `text`.

    Used where the design writes a requirement in prose — *"blind sample completion rate"* against
    this suite's `blind_completion_rate`. A subset check on words is the honest comparison: it
    survives the connectives the design uses and still fails if a feature is missing or renamed.
    """
    haystack = _normalize(text)
    return all(word in haystack for word in _normalize(name).split())


# ==================================================================================================
# Transcription — every literal, against §3.15
# ==================================================================================================


def test_the_service_members_are_the_ones_the_interfaces_block_declares(interfaces):
    """Set equality against the `def` names in §3.15's `ReviewService` Protocol.

    Equality rather than containment in both directions: a member this suite does not know about
    is a surface no clause case sweeps, and `CT-REVIEW-12`'s "no interface accepts a numeric
    score" is a claim about *every* entry point.
    """
    declared = set(re.findall(r"def (\w+)\(", interfaces))

    assert declared == set(vocab.SERVICE_MEMBERS), (
        f"§3.15 declares {sorted(declared)}; this suite is written against "
        f"{sorted(vocab.SERVICE_MEMBERS)}"
    )


def test_the_review_queue_fields_are_the_ones_the_dataclass_declares(interfaces):
    """`ReviewQueue`'s five fields, read off the dataclass rather than the prose around it."""
    block = interfaces[interfaces.index("class ReviewQueue:") :]
    declared = re.findall(r"^\s{4}(\w+)\s*:", block, flags=re.MULTILINE)

    assert tuple(declared) == vocab.REVIEW_QUEUE_FIELDS, (
        f"§3.15's ReviewQueue declares {declared}; this suite holds {list(vocab.REVIEW_QUEUE_FIELDS)}"
    )
    assert set(vocab.RESIDUAL_TRIPLE) <= set(declared), (
        f"CT-REVIEW-04's triple {vocab.RESIDUAL_TRIPLE} is not a subset of the declared fields"
    )


def test_the_action_domain_matches_the_literal_in_the_interfaces_block(interfaces):
    """`act`'s `Literal["accept","edit","override","skip"]`, exactly."""
    literal = re.search(r'Literal\[([^\]]+)\]', interfaces).group(1)
    declared = tuple(re.findall(r'"(\w+)"', literal))

    assert declared == vocab.ACTIONS, (
        f"§3.15 declares actions {declared}; this suite holds {vocab.ACTIONS}"
    )
    assert "skip" not in vocab.LABEL_TYPES, (
        "`skip` is an action and not a label type — an item skipped stays residual, which is "
        "CT-REVIEW-06's subject rather than CT-REVIEW-07's"
    )


def test_the_review_item_fields_all_appear_in_the_paragraph_that_names_them(section):
    """`ReviewItem` is prose, not a dataclass, so this transcription is the only field list.

    Which is itself the finding asserted further down: every other wire shape in §3.15 is
    declared, and this one is a sentence.
    """
    paragraph = section[section.index("`ReviewItem` is the wire shape") :]
    paragraph = paragraph[: paragraph.index("\n\n**Upstream")]

    missing = [f for f in vocab.REVIEW_ITEM_FIELDS if not _tokens_present(f, paragraph)]
    assert missing == [], (
        f"§3.15's ReviewItem paragraph does not name {missing}"
    )
    for field in vocab.TEACHER_ONLY_ITEM_FIELDS:
        assert field in _normalize(paragraph).replace(" ", "_") or _tokens_present(field, paragraph), (
            f"{field} is not named in the paragraph that restricts it to the teacher"
        )


def test_the_label_fields_are_the_ones_fr_review_09_names(design_rows):
    """Every field in `LABEL_FIELDS` is named by `FR-REVIEW-09`, and none is invented."""
    requirement = _row(design_rows, "FR-REVIEW-09")[1]

    missing = [f for f in vocab.LABEL_FIELDS if not _tokens_present(f, requirement)]
    assert missing == [], f"FR-REVIEW-09 does not name {missing}"

    domain = re.search(r"`label_type` in `\{([^}]+)\}`", requirement)
    assert domain is not None, (
        f"FR-REVIEW-09 no longer states a label_type domain: {requirement!r}"
    )
    declared = tuple(part.strip() for part in domain.group(1).split(","))
    assert declared == vocab.LABEL_TYPES, (
        f"FR-REVIEW-09's label_type domain is {declared}; this suite holds {vocab.LABEL_TYPES}"
    )


def test_the_attribution_fields_come_from_nfr_review_03_not_fr_review_09(design_rows):
    """The two sets are kept apart because they come from different requirements.

    Folding `actor` and `timestamp` into `LABEL_FIELDS` would make the count finding below
    untestable, and would also let a label satisfying `FR-REVIEW-09` fail for an `NFR-REVIEW-03`
    reason with no way to tell which.
    """
    nfr = _row(design_rows, "NFR-REVIEW-03")[2]

    for field in vocab.LABEL_ATTRIBUTION_FIELDS:
        assert _tokens_present(field, nfr), f"NFR-REVIEW-03 does not name {field!r}"
    for field in vocab.LABEL_ATTRIBUTION_FIELDS:
        assert field not in vocab.LABEL_FIELDS, (
            f"{field!r} is in both sets, so the two requirements can no longer fail separately"
        )


def test_the_four_configuration_knobs_carry_their_declared_values(section):
    """§3.15's Configuration line, all four with their Assumption values."""
    line = section[section.index("**Configuration.**") :]
    line = line[: line.index("\n\n")]

    for knob, value in vocab.CONFIG_DEFAULTS.items():
        assert knob in line, f"§3.15's Configuration line does not declare {knob}"
        declared = re.search(rf"{knob}`?\s*\((?:Assumption:\s*)?(\d+)\)", line)
        assert declared is not None, f"{knob} carries no declared value in §3.15"
        assert int(declared.group(1)) == value, (
            f"{knob} is declared as {declared.group(1)} in §3.15; this suite holds {value}"
        )


def test_every_observability_counter_is_named_in_the_observability_paragraph(section):
    """§3.15's Observability line names each counter; the pair is asserted separately below."""
    paragraph = section[section.index("**Observability.**") :]
    paragraph = paragraph[: paragraph.index("\n\n")]

    missing = [c for c in vocab.OBSERVABILITY_COUNTERS if not _tokens_present(c, paragraph)]
    assert missing == [], f"§3.15's Observability line does not name {missing}"

    assert "versus" in paragraph, (
        "the Observability line no longer states `review_items_shown` **versus** "
        "`review_items_flagged`, and the word is what makes them a pair rather than two counters"
    )
    for name in vocab.HONESTY_CHECK_PAIR:
        assert name in vocab.OBSERVABILITY_COUNTERS, (
            f"{name!r} is in the honesty pair but not in the counter list"
        )


def test_the_alert_is_about_consecutive_administrations(section):
    """The alert semantics, which is the half a counter list does not carry."""
    paragraph = section[section.index("**Alert:**") :]
    paragraph = paragraph[: paragraph.index("\n\n")]

    assert "consecutive" in paragraph.lower(), (
        "§3.15's Alert no longer says *consecutive* administrations, so CT-REVIEW-18's "
        "cross-administration retention assertion has nothing behind it"
    )
    assert "pattern" in paragraph.lower(), (
        "the Alert no longer requires the signal be surfaced as a pattern rather than absorbed"
    )
    assert vocab.ALERT_MIN_CONSECUTIVE_ADMINISTRATIONS >= 2, (
        "a 'consecutive administrations' pattern needs at least two administrations to exist"
    )


def test_the_two_sample_ranges_come_from_their_requirements(design_rows):
    """15–25 blind submissions and 10–15 whole grades, read off `FR-REVIEW-12` and `-14`."""
    blind = _row(design_rows, "FR-REVIEW-12")[1]
    whole = _row(design_rows, "FR-REVIEW-14")[1]

    assert f"{vocab.BLIND_SAMPLE_RANGE[0]}–{vocab.BLIND_SAMPLE_RANGE[1]}" in blind, (
        f"FR-REVIEW-12 does not state the range {vocab.BLIND_SAMPLE_RANGE}"
    )
    assert "judged criteria only" in blind.lower(), (
        "FR-REVIEW-12 no longer restricts the blind sample to judged criteria"
    )
    assert f"{vocab.WHOLE_GRADE_SAMPLE_RANGE[0]}–{vocab.WHOLE_GRADE_SAMPLE_RANGE[1]}" in whole, (
        f"FR-REVIEW-14 does not state the range {vocab.WHOLE_GRADE_SAMPLE_RANGE}"
    )
    assert _tokens_present(vocab.WHOLE_GRADE_POPULATION, whole), (
        f"FR-REVIEW-14 no longer restricts the whole-grade sample to the "
        f"{vocab.WHOLE_GRADE_POPULATION} population, which CT-REVIEW-11 calls the point"
    )


def test_the_blind_flow_reads_two_tables_and_cannot_join_to_the_score_row(section):
    """§3.15's Data flow paragraph — the sentence `CT-REVIEW-09`'s primary assertion rests on."""
    paragraph = section[section.index("**Data flow.**") :]
    paragraph = paragraph[: paragraph.index("\n\n")]

    for table in vocab.BLIND_READABLE_TABLES:
        assert f"`{table}`" in paragraph, (
            f"§3.15's Data flow paragraph no longer says the blind session reads {table!r}"
        )
    # The forbidden table appears in this paragraph too — in the clause that forbids it — so a
    # membership loop over the readable set passes even when the readable set contains it.
    # Mutation added `criterion_score` to BLIND_READABLE_TABLES and nothing caught it.
    assert vocab.BLIND_FORBIDDEN_TABLE not in vocab.BLIND_READABLE_TABLES, (
        f"{vocab.BLIND_FORBIDDEN_TABLE!r} is in the readable set, so CT-REVIEW-09's primary "
        "assertion — set equality against what the session may read — now permits the one join "
        "the clause exists to forbid"
    )
    assert len(vocab.BLIND_READABLE_TABLES) == 2, (
        f"the blind session reads {len(vocab.BLIND_READABLE_TABLES)} tables; §3.15 says two"
    )
    assert f"cannot join to `{vocab.BLIND_FORBIDDEN_TABLE}`" in paragraph, (
        f"§3.15 no longer states that the blind session cannot join to "
        f"{vocab.BLIND_FORBIDDEN_TABLE!r}, which is the structural form of FR-REVIEW-11"
    )


def test_the_five_blind_absences_come_from_fr_review_11(design_rows):
    """`FR-REVIEW-11`'s five, and its *unreachable rather than hidden* wording."""
    requirement = _row(design_rows, "FR-REVIEW-11")[1]

    missing = [f for f in vocab.BLIND_FORBIDDEN_FIELDS if not _tokens_present(f, requirement)]
    assert missing == [], f"FR-REVIEW-11 does not name {missing}"
    # The count as well as the membership. A subset check is half a comparison: dropping a field
    # from this suite's tuple shortens the loop and passes, which mutation confirmed for
    # `routing_reason`. FR-REVIEW-11 lists five and CT-REVIEW-09 step 2 sweeps five.
    assert len(vocab.BLIND_FORBIDDEN_FIELDS) == 5, (
        f"this suite sweeps {len(vocab.BLIND_FORBIDDEN_FIELDS)} absences; FR-REVIEW-11 names five"
    )
    assert "unreachable" in requirement.lower(), (
        "FR-REVIEW-11 no longer requires unreachability. Hiding is a property of a template and "
        "survives exactly as long as nobody edits the template."
    )


def test_the_four_error_probability_signals_come_from_fr_review_03(design_rows):
    """`FR-REVIEW-03`'s four inputs, and its explicit prohibition on self-reported confidence."""
    requirement = _row(design_rows, "FR-REVIEW-03")[1]

    missing = [s for s in vocab.ERROR_PROBABILITY_SIGNALS if not _tokens_present(s, requirement)]
    assert missing == [], f"FR-REVIEW-03 does not name {missing}"
    assert len(vocab.ERROR_PROBABILITY_SIGNALS) == 4, (
        f"this suite varies {len(vocab.ERROR_PROBABILITY_SIGNALS)} signals; FR-REVIEW-03 combines "
        "four — panel spread, adverse integrity signals, transcription overlap and the "
        "criterion's historical override rate. A dropped one is a signal the ranking may ignore "
        "with nothing to notice."
    )

    for signal, phrase in vocab.IMPACT_SIGNALS.items():
        assert phrase in requirement.lower(), (
            f"FR-REVIEW-03's impact term no longer says {phrase!r}, which is the prose this "
            f"suite's {signal!r} was invented for — an invented name whose source has moved is "
            "an invented name nobody can check"
        )
    assert "not self-reported confidence alone" in requirement.lower(), (
        "FR-REVIEW-03 no longer prohibits ranking on self-reported confidence alone, which is "
        "the sweep CT-REVIEW-03's second half performs"
    )


def test_the_residual_state_and_its_two_prohibitions_come_from_fr_review_08(design_rows):
    requirement = _row(design_rows, "FR-REVIEW-08")[1]

    assert f"`{vocab.RESIDUAL_STATE}`" in requirement, (
        f"FR-REVIEW-08 no longer marks residual items {vocab.RESIDUAL_STATE!r}"
    )
    assert "persist across review sessions" in requirement.lower(), (
        "FR-REVIEW-08 no longer requires the residual to persist across sittings, which the test "
        "plan calls the plausible bug"
    )
    assert "never" in requirement.lower() and "backfilled" in requirement.lower(), (
        "FR-REVIEW-08 no longer prohibits silent finalization or backfilling"
    )


def test_the_never_rendered_populations_come_from_fr_review_06_and_07(design_rows):
    """Three from `FR-REVIEW-07` and the fourth from `FR-REVIEW-06`, kept as one tuple."""
    seven = _row(design_rows, "FR-REVIEW-07")[1]
    six = _row(design_rows, "FR-REVIEW-06")[1]

    for population in ("quarantine", "blind_sample", "random_arm"):
        assert _tokens_present(population, seven), f"FR-REVIEW-07 does not name {population!r}"
    assert _tokens_present("deterministic criterion", six), (
        "FR-REVIEW-06 no longer excludes deterministic criteria from the queue"
    )
    assert "no review item" in seven.lower(), (
        "FR-REVIEW-07 no longer says the random arm produces no review item, which is "
        "CT-REVIEW-05's exact-zero assertion"
    )


def test_the_group_signature_components_are_the_band_plus_the_four_integrity_inputs(
    design_rows, section
):
    """`CT-REVIEW-20`'s *"band-plus-integrity-signature"*, resolved against `CT-AGG-10`.

    §3.15 names the rule and not its components, so the four integrity inputs are transcribed
    from §3.12's `CT-AGG-10` row — the design's own list of what sits on a score row. A
    cross-section transcription is asserted against both halves so it cannot drift on either.
    """
    integrity = _row(design_rows, "CT-AGG-10")[2]
    open_question = section[section.index("**Open questions") :]

    assert "band-plus-integrity-signature" in open_question, (
        "§3.15's open question no longer states the Phase 1 grouping rule, so CT-REVIEW-20's "
        "non-promise has nothing to name"
    )
    assert vocab.GROUP_SIGNATURE_COMPONENTS[0] == "proposed_band", (
        "the signature no longer starts with the band, which is the 'band-plus' half"
    )
    missing = [
        c for c in vocab.GROUP_SIGNATURE_COMPONENTS[1:] if not _tokens_present(c, integrity)
    ]
    assert missing == [], (
        f"CT-AGG-10 does not name {missing} among the integrity inputs recorded on the score row"
    )


def test_the_performance_threshold_and_its_load_come_from_nfr_review_01(design_rows):
    requirement = _row(design_rows, "NFR-REVIEW-01")[2]

    assert f"{int(vocab.QUEUE_BUILD_SECONDS)} seconds" in requirement, (
        f"NFR-REVIEW-01 no longer states {vocab.QUEUE_BUILD_SECONDS} seconds"
    )
    assert f"{vocab.PERF_STUDENTS}-student" in requirement, (
        f"NFR-REVIEW-01's load is no longer {vocab.PERF_STUDENTS} students"
    )
    assert f"{vocab.PERF_FLAGGED_ITEMS} flagged" in requirement, (
        f"NFR-REVIEW-01's load is no longer ~{vocab.PERF_FLAGGED_ITEMS} flagged items"
    )


def test_the_est_seconds_non_promise_is_a_phase_two_requirement(design_rows):
    """`FR-REVIEW-16`'s Phase column is what makes `CT-REVIEW-19` a non-promise rather than a bug."""
    row = _row(design_rows, "FR-REVIEW-16")

    assert row[-1].strip() == str(vocab.EST_SECONDS_CALIBRATION_PHASE), (
        f"FR-REVIEW-16 is now Phase {row[-1].strip()}; this suite treats calibration as Phase "
        f"{vocab.EST_SECONDS_CALIBRATION_PHASE}, which is the whole content of CT-REVIEW-19"
    )
    assert len(vocab.CALIBRATION_INPUTS) == 2, (
        "CT-REVIEW-19's Phase 2 path is a comparison, so it needs both sides stored — dropping "
        "one leaves the non-promise with no way out and nothing asserting it"
    )
    for field in vocab.CALIBRATION_INPUTS:
        assert _tokens_present(field, row[1]), (
            f"FR-REVIEW-16 does not name {field!r}, so CT-REVIEW-19's Phase 2 path has nothing "
            "stored to calibrate against"
        )


# ==================================================================================================
# Rule controls — both directions, every rule
# ==================================================================================================


def test_the_numeric_entry_rule_passes_a_band_only_edit_path():
    """Direction one: the correct implementation, which *returns* `new_points` and accepts a band."""
    assert vocab.numeric_entry_parameters(broken.CORRECT_BAND_EDIT_SOURCE) == [], (
        "the rule flags a compliant edit path. FR-REVIEW-10 derives new_points from new_band, so "
        "the name appearing as a local and a keyword argument to `record_label` is correct — a "
        "rule that condemns it is one the first person to hit it switches off."
    )


def test_the_numeric_entry_rule_flags_a_numeric_parameter():
    """Direction two, in the shape it actually arrives: a teacher who wants to type 7 out of 10."""
    flagged = vocab.numeric_entry_parameters(broken.NUMERIC_SCORE_PARAMETER_SOURCE)
    assert "act:new_points" in flagged, (
        f"the rule did not flag a numeric score parameter: {flagged}"
    )


def test_the_numeric_entry_rule_sees_past_a_keyword_only_star():
    """A parameter after `*` is where a line scan stops looking, and where the next one will go."""
    flagged = vocab.numeric_entry_parameters(broken.NUMERIC_SCORE_KEYWORD_ONLY_SOURCE)
    assert "act:score" in flagged, (
        f"the rule missed a keyword-only numeric parameter: {flagged}. Parsing rather than "
        "grepping is the whole reason this rule reads an AST."
    )


def test_the_annotation_rule_passes_the_declared_review_surface():
    assert vocab.annotation_surface_members(broken.CORRECT_REVIEW_SURFACE_NAMES) == [], (
        "the rule flags §3.15's own declared members, so it would condemn every compliant module"
    )


def test_the_annotation_rule_flags_a_surface_named_for_its_screen():
    flagged = vocab.annotation_surface_members(broken.ANNOTATION_SURFACE_NAMES_PRESENT)
    assert flagged == ["add_comment", "annotate_submission", "student_notes"], (
        f"the rule found {flagged}. The surface arrives named for its screen rather than for the "
        "prohibition, which is why this matches substrings."
    )


def test_the_percentage_sizing_rule_passes_the_designs_own_signature():
    """`blind_sample(n=15)` is §3.15's own parameter; a rule flagging a bare `n` fails on day one."""
    assert vocab.percentage_sizing_surface(broken.CORRECT_SIZING_NAMES) == [], (
        "the rule flags the design's own names, including the `n` of blind_sample(n=15)"
    )


def test_the_percentage_sizing_rule_flags_a_proportionally_sized_queue():
    flagged = vocab.percentage_sizing_surface(broken.PERCENTAGE_SIZING_NAMES_PRESENT)
    assert flagged == ["coverage_fraction", "review_percent", "top_n_items"], (
        f"the rule found {flagged}"
    )


def test_the_semantic_clustering_rule_passes_a_rendering_that_names_the_actual_rule():
    assert vocab.semantic_clustering_language(broken.CORRECT_GROUP_RENDERING) == [], (
        "the rule flags a caption that describes exact band-plus-signature grouping, which is "
        "the copy CT-REVIEW-20 asks for"
    )


def test_the_semantic_clustering_rule_does_not_match_similar_inside_dissimilar():
    """The word-boundary half. `"dissimilar"` contains `"similar"`, and a substring rule is wrong.

    This is the control that keeps the rule usable: a caption saying *"responses that are
    dissimilar in wording are still grouped"* is exactly the honest copy the clause wants, and a
    naive rule condemns it.
    """
    assert "dissimilar" in broken.GROUP_RENDERING_WITH_DISSIMILAR, (
        "the control fixture no longer contains the word it exists to trap — without it this "
        "test passes for a rule with no word-boundary handling at all"
    )
    assert vocab.semantic_clustering_language(broken.GROUP_RENDERING_WITH_DISSIMILAR) == [], (
        "the rule matched `similar` inside `dissimilar`, so it condemns the most accurate "
        "description of Phase 1 grouping available"
    )


@pytest.mark.parametrize("rendering", broken.SEMANTIC_GROUP_RENDERINGS)
def test_the_semantic_clustering_rule_flags_a_content_claim(rendering):
    assert vocab.semantic_clustering_language(rendering) != [], (
        f"the rule passed {rendering!r}, which claims the group is alike in content — a claim "
        "exact signature grouping does not support"
    )


def test_the_budget_guarantee_rule_passes_a_rendering_that_calls_the_budget_an_estimate():
    assert vocab.budget_guarantee_language(broken.CORRECT_BUDGET_RENDERING) == [], (
        "the rule flags a caption that states the budget and calls the estimate uncalibrated, "
        "which is the copy CT-REVIEW-19 asks for"
    )


@pytest.mark.parametrize("rendering", broken.BUDGET_GUARANTEE_RENDERINGS)
def test_the_budget_guarantee_rule_flags_a_promise_about_elapsed_time(rendering):
    assert vocab.budget_guarantee_language(rendering) != [], (
        f"the rule passed {rendering!r}, which presents the budget as a guarantee of elapsed time"
    )


def test_the_residual_rule_passes_a_rendering_that_states_all_three_figures():
    queue = broken.QueueFigures()
    assert vocab.unstated_residual(broken.CORRECT_QUEUE_RENDERING, queue) == [], (
        "the rule flags a screen that states all three figures under its own labels — it matches "
        "numbers rather than field names precisely so a rewording is not a violation"
    )


def test_the_residual_rule_flags_a_screen_that_shows_only_what_fits():
    queue = broken.QueueFigures()
    missing = vocab.unstated_residual(broken.RENDERING_OMITTING_THE_RESIDUAL, queue)
    assert set(missing) == {"flagged_total", "residual_provisional"}, (
        f"the rule reported {missing} for a screen that states only what it is showing — which "
        "is precisely the dishonesty CT-REVIEW-04 exists to prevent"
    )


def test_the_residual_rule_flags_a_screen_missing_only_the_flagged_total():
    queue = broken.QueueFigures()
    assert vocab.unstated_residual(broken.RENDERING_OMITTING_THE_FLAGGED_TOTAL, queue) == [
        "flagged_total"
    ], "the rule does not distinguish which of the three is missing"


def test_the_prefetch_rule_passes_a_compliant_blind_session():
    assert vocab.blind_prefetch_attributes(broken.CompliantBlindSession()) == [], (
        "the rule flags a session holding only submissions and criteria"
    )


def test_the_prefetch_rule_flags_the_adversarial_construction():
    """`TC-REVIEW-C09`'s construction, and the reason the probe reads attributes.

    The construction renders nothing, so every assertion made over rendered output passes it. What
    changes is the object.
    """
    found = vocab.blind_prefetch_attributes(broken.PrefetchingBlindSession())
    assert "prefetched_score" in found, (
        f"the rule found {found} on a session carrying a cached score row"
    )


def test_the_fixture_populations_are_not_degenerate():
    """The controls on the fixtures themselves, which are as easy to get wrong as the rules.

    A ranking case run over a population where every row scores identically asserts nothing; a
    grouping case run over a population with one signature asserts nothing. Both are silent
    failures — the test passes and covers nothing — so each builder's non-degeneracy is asserted
    here rather than assumed.
    """
    population = broken.flagged_population(40)

    for signal in vocab.ERROR_PROBABILITY_SIGNALS:
        values = {getattr(row, signal) for row in population}
        assert len(values) > 1, (
            f"every row in flagged_population shares {signal} = {values}, so a per-signal "
            "sensitivity case run over it cannot detect a ranking that ignores the signal"
        )

    # Not a disjunction. An earlier draft wrote `... or len(set(est)) > 1`, whose right-hand side
    # is always true for this fixture — so the guard could not fail, including for a fixture in
    # perfect lockstep. Review caught it. What lockstep means is that one value determines the
    # other, so the test is that neither mapping is a function.
    est = [row.est_seconds for row in population]
    spread = [row.panel_spread for row in population]
    assert len({(e, s) for e, s in zip(est, spread)}) > max(len(set(est)), len(set(spread))), (
        "est_seconds and panel_spread vary in lockstep — one determines the other — so a ranking "
        "reading one is indistinguishable from a ranking reading the other, and CT-REVIEW-03's "
        "per-signal sensitivity case cannot tell them apart"
    )

    # The premise ten cases in this suite rest on: `queue.shown` is typed
    # `Sequence[ReviewItem | ReviewGroup]`, and those cases iterate it for `.score_id` and
    # `.est_seconds`. If this population groups, a *correct* implementation hands them a
    # `ReviewGroup` and they raise. Review measured an earlier draft grouping all 200 rows.
    for size in (12, 20, 40, 200):
        rows = broken.flagged_population(size)
        signatures = [
            (row.criterion_id, *(getattr(row, c) for c in vocab.GROUP_SIGNATURE_COMPONENTS))
            for row in rows
        ]
        assert len(set(signatures)) == len(rows), (
            f"flagged_population({size}) has {len(rows) - len(set(signatures))} rows sharing a "
            "criterion and a grouping signature, so a correct queue presents them as a group and "
            "every case that iterates `shown` for `.score_id` fails against compliant code"
        )

    grouped = broken.identical_signature_population(12)
    assert len({row.submission_id for row in grouped}) == len(grouped), (
        "the group fixture's members share a submission id, so 'one label per member' cannot be "
        "distinguished from one label"
    )
    signatures = {
        tuple(getattr(row, c) for c in vocab.GROUP_SIGNATURE_COMPONENTS) for row in grouped
    }
    assert len(signatures) == 1, (
        f"the group fixture holds {len(signatures)} distinct signatures, so it does not group "
        "under the Phase 1 rule and CT-REVIEW-13's case has nothing to act on"
    )


def test_the_signature_variants_differ_in_exactly_one_component_each():
    """Each variant differs from the base in its own component and in nothing else.

    Without this, `TC-REVIEW-C20`'s per-component sweep is satisfied by a grouping rule that reads
    one component: every variant would differ in that one too, and every parametrization would
    pass for the wrong reason.
    """
    base = broken.identical_signature_population(1)[0]
    variants = broken.signature_variants(base)

    assert set(variants) == set(vocab.GROUP_SIGNATURE_COMPONENTS), (
        f"the variant set covers {sorted(variants)} against §3.15's "
        f"{sorted(vocab.GROUP_SIGNATURE_COMPONENTS)}"
    )
    for component, variant in variants.items():
        differing = [
            c
            for c in vocab.GROUP_SIGNATURE_COMPONENTS
            if getattr(variant, c) != getattr(base, c)
        ]
        assert differing == [component], (
            f"the {component!r} variant differs in {differing}; the sweep needs exactly one "
            "difference per variant or a rule reading a single component passes every case"
        )


def test_the_excluded_population_fixture_covers_every_never_rendered_population():
    excluded = broken.excluded_population()
    assert set(excluded) == set(vocab.NEVER_RENDERED_POPULATIONS), (
        f"the fixture covers {sorted(excluded)} against CT-REVIEW-05's "
        f"{sorted(vocab.NEVER_RENDERED_POPULATIONS)}"
    )
    assert excluded["random_arm"].origin == vocab.RANDOM_ARM_ORIGIN, (
        "the random-arm fixture does not carry the origin CT-ORCH-15 makes it separable by"
    )
    assert excluded["deterministic_criterion"].evaluation_mode == (
        vocab.DETERMINISTIC_EVALUATION_MODE
    ), "the deterministic fixture does not carry the column CT-DET-06 enforces the exclusion from"


# ==================================================================================================
# Findings — claims about the plan and the design, asserted so they retire themselves
# ==================================================================================================


def test_finding_the_plan_says_nine_label_fields_and_the_requirement_names_eight(
    design_rows, plan
):
    """**Finding.** `TC-REVIEW-C07` asks for *"all nine named fields"*; `FR-REVIEW-09` names eight.

    Counted from the requirement's own text: `label_type`, `saw_system_output`, `routing`,
    `origin`, `evaluation_mode`, `review_seconds`, `system_band`, `teacher_band`. The suite
    transcribes the design's eight and asserts `NFR-REVIEW-03`'s `actor` and `timestamp`
    separately, because they are a different requirement.

    Nothing is weakened by the discrepancy — a label carrying all ten passes both — but the count
    in the plan is wrong by one and a reader reconciling the two would go looking for a field that
    does not exist. This goes green the day either document is corrected.
    """
    requirement = _row(design_rows, "FR-REVIEW-09")[1]
    named = [f for f in vocab.LABEL_FIELDS if _tokens_present(f, requirement)]

    assert len(named) == len(vocab.LABEL_FIELDS) == 8, (
        f"FR-REVIEW-09 now names {len(named)} of this suite's fields"
    )
    assert "all nine named fields" in plan, (
        "the test plan no longer says 'all nine named fields' for TC-REVIEW-C07, so this finding "
        "has been fixed — drop it, and reconcile LABEL_FIELDS with whatever the plan now says"
    )
    assert vocab.LABEL_FIELD_COUNT_CLAIMED_BY_PLAN != len(vocab.LABEL_FIELDS), (
        "the plan's count and the requirement's now agree; this finding is retired"
    )


def test_finding_a_five_minute_budget_cannot_cover_a_ten_minute_blind_reserve(design_rows):
    """**Finding.** `NFR-REVIEW-05`'s 5 minutes collides with `REVIEW_BLIND_RESERVE_MINUTES` = 10.

    `FR-REVIEW-02` subtracts the blind reservation **before** ranking, so a 5-minute budget has
    nothing left to spend and the queue is empty — while `NFR-REVIEW-05` promises it *"shows fewer
    items and states a larger residual"* at exactly that budget. The design settles neither: it
    does not say the reserve is capped at the budget, nor that a budget below the reserve is
    refused, nor that the sample is skipped.

    `TC-REVIEW-C01`'s degradation case asserts a non-empty queue at 5 minutes and says why, so
    whichever way this is resolved the case fails loudly rather than passing vacuously over an
    empty list.
    """
    reserve = vocab.CONFIG_DEFAULTS["REVIEW_BLIND_RESERVE_MINUTES"]
    assert vocab.DEGRADED_BUDGET_MINUTES < reserve, (
        f"the degraded budget ({vocab.DEGRADED_BUDGET_MINUTES}) now clears the reserve "
        f"({reserve}); the collision is gone and this finding is retired"
    )
    nfr = _row(design_rows, "NFR-REVIEW-05")[2]
    assert f"{vocab.DEGRADED_BUDGET_MINUTES} minutes" in nfr, (
        f"NFR-REVIEW-05 no longer names {vocab.DEGRADED_BUDGET_MINUTES} minutes"
    )
    assert "cap" not in nfr.lower() and "refus" not in nfr.lower(), (
        "NFR-REVIEW-05 now says what happens when the budget is below the reserve; this finding "
        "is resolved and TC-REVIEW-C01's assertion should follow the design's answer"
    )


def test_finding_the_interfaces_block_declares_nothing_that_exposes_a_query(interfaces, section):
    """**Finding.** §3.15 mandates a query-level assertion and declares no query-level surface.

    The Compatibility paragraph is explicit — *"the required negative test is that a blind
    session's query plan **cannot** reach `criterion_score`, which is asserted against the query,
    not the rendering"* — and the Interfaces block returns `BlindSession` with no member that
    exposes what it can read. `CT-REVIEW-05`'s admission reachability has the same gap.

    So `BlindSession.readable_tables()` and `.admission_query()` are invented in
    `review_vocabulary`'s docstring. The alternative was a source scan of `aeh/review/`, which
    asserts *"no code in this module names the table"* — a weaker claim that a module reaching it
    through a store helper or a database view satisfies while violating the clause. The gap is
    named on the PR rather than closed by quietly substituting the weaker assertion.
    """
    compatibility = section[section.index("*Compatibility.*") :]
    assert "asserted against the query, not the rendering" in compatibility, (
        "§3.15 no longer mandates a query-level assertion, so the invented member is no longer "
        "forced and this finding is retired"
    )
    exposing = [
        name
        for name in re.findall(r"def (\w+)\(", interfaces)
        if "quer" in name or "readable" in name or "plan" in name
    ]
    assert exposing == [], (
        f"§3.15 now declares {exposing}, which exposes what a session can read — drop the "
        "invented `readable_tables()` and write CT-REVIEW-09 against the declared member"
    )


def test_finding_the_transport_step_of_ct_review_09_belongs_to_m_console(plan):
    """**Finding.** `TC-REVIEW-C09` step 3 asserts against a surface `M-REVIEW` does not have.

    *"Assert the negative at the transport layer: no request made during the blind flow returns
    system output, even unrendered."* `M-REVIEW` is a service with six methods and no requests;
    the transport is `M-CONSOLE`'s, delivered by #124/#125.

    The step is still implemented — dropping a P0 safety-property step because it lands next door
    would be exactly the silent weakening `/write-tests` step 5 exists to prevent — but it is
    keyed on the console story rather than on `M-REVIEW`, which means `CT-REVIEW-09` is not fully
    asserted until a *different* module lands. That is worth a reader knowing.
    """
    assert "Assert the negative at the transport layer" in plan, (
        "the test plan no longer asks for a transport-layer assertion under TC-REVIEW-C09; this "
        "finding is retired"
    )
    assert "M-CONSOLE" in vocab.__doc__ or "aeh.console" in vocab.__doc__, (
        "the invented-names docstring no longer records that the transport probe is a console "
        "surface, so the finding has lost its anchor"
    )


def test_finding_review_item_is_prose_where_every_other_wire_shape_is_declared(interfaces, section):
    """**Finding.** `ReviewItem` — the shape the whole queue is made of — is a sentence.

    §3.15 declares `ReviewService` and `ReviewQueue` in Python and describes `ReviewItem` in
    prose: *"carrying `proposed_band`, `band_options` with descriptors, …"*. Ten fields, no types,
    no optionality, and `est_seconds` and `grade_boundary_delta` — which `FR-REVIEW-03`'s ranking
    formula divides by and multiplies with — exist nowhere else in the design.

    `TC-REVIEW-C03` and `-C16` both read them, so this suite transcribes the paragraph. A reader
    checking the transcription has to check a sentence against a tuple, which is the cost.
    """
    assert "class ReviewItem" not in interfaces, (
        "§3.15 now declares ReviewItem, so REVIEW_ITEM_FIELDS should be read off the dataclass "
        "the way REVIEW_QUEUE_FIELDS is; this finding is retired"
    )
    assert "`ReviewItem` is the wire shape" in section, (
        "the paragraph this suite transcribes ReviewItem from has moved or been reworded"
    )
    for field in ("est_seconds", "grade_boundary_delta"):
        assert field in vocab.REVIEW_ITEM_FIELDS, (
            f"{field} is read by CT-REVIEW-03's ranking and is not in the transcription"
        )


def test_finding_three_of_the_four_knobs_have_no_label_count_differential(
    interfaces, design_rows
):
    """**Finding.** `CT-REVIEW-17` says all four knobs change how much validation evidence an
    administration produces. Three of them cannot be measured that way in this module.

    * `REVIEW_WHOLE_GRADE_N` sizes a sample that writes no label: `FR-REVIEW-14` offers the
      whole-grade sample as a display, and `FR-REVIEW-09` writes labels for teacher *actions*.
    * `REVIEW_DEFAULT_BUDGET_MINUTES` is a default for a parameter the Interfaces block declares
      as required — `build_queue(self, run_id, budget_minutes)` — so nothing inside `M-REVIEW`
      reads it; the default belongs to whichever consumer calls the method.
    * `REVIEW_BLIND_RESERVE_MINUTES` sizes the **reservation**, and nothing in §3.15 couples
      reserved minutes to sample size: `blind_sample(n=...)` draws its own `n` whatever the
      reserve is. An earlier draft swept it for a label-count differential and the assertion could
      not have passed for any implementation — which is why this finding says three where the
      first draft said two.

    All four are asserted for their declared values. Only `REVIEW_BLIND_N` has the differential
    the clause's framing asks for, and inventing one for the other three would be worse than
    reporting it. Each assertion below retires its own third.
    """
    assert re.search(r"def build_queue\(self, run_id: RunId, budget_minutes: int\)", interfaces), (
        "build_queue's signature has changed; if budget_minutes now carries a default, "
        "REVIEW_DEFAULT_BUDGET_MINUTES has a differential and a third of this finding is retired"
    )
    whole_grade = _row(design_rows, "FR-REVIEW-14")[1]
    assert "label" not in whole_grade.lower(), (
        "FR-REVIEW-14 now mentions a label, so the whole-grade sample may write one and a third "
        "of this finding is retired"
    )
    reserve = _row(design_rows, "FR-REVIEW-02")[1]
    assert "REVIEW_BLIND_N" not in reserve and not _tokens_present("sample size", reserve), (
        "FR-REVIEW-02 now couples the blind reservation to the sample size, so "
        "REVIEW_BLIND_RESERVE_MINUTES has a label-count differential after all — sweep it in "
        "TC-REVIEW-C17 and retire the last third of this finding"
    )
    assert "def blind_sample(self, run_id: RunId, n: int = 15)" in interfaces, (
        "blind_sample no longer draws a caller-supplied n independent of the reserve, which is "
        "what makes the reservation unmeasurable as validation evidence today"
    )


@pytest.mark.parametrize("phrase", sorted(vocab.SEMANTIC_CLUSTERING_PHRASES))
def test_every_semantic_clustering_phrase_is_detected_on_its_own(phrase):
    """One probe per phrase, so removing any single phrase from the rule fails here.

    The realistic captions above each trip several phrases at once, which meant the rule could
    lose one and stay green — mutation removed `"cluster"` and nothing noticed, because
    `"clustered"` and `"comparable"` were in the same sentence.
    """
    probe = broken.SEMANTIC_PHRASE_PROBES[phrase]
    assert vocab.semantic_clustering_language(probe) == [phrase], (
        f"the rule reported {vocab.semantic_clustering_language(probe)} for {probe!r}; it should "
        f"report exactly [{phrase!r}]"
    )


def test_the_semantic_probe_set_covers_every_declared_phrase():
    """The probes and the rule's phrase list are the same set, so a phrase added later is swept."""
    assert set(broken.SEMANTIC_PHRASE_PROBES) == set(vocab.SEMANTIC_CLUSTERING_PHRASES), (
        f"probes cover {sorted(broken.SEMANTIC_PHRASE_PROBES)} against the rule's "
        f"{sorted(vocab.SEMANTIC_CLUSTERING_PHRASES)}"
    )


def test_the_residual_rule_reports_a_figure_the_queue_never_computed():
    """The `None` branch, which no other fixture reaches.

    A screen omitting the residual and a queue that never computed one are different failures and
    the rule has to report the field for both — inverting the condition passed every test until
    this fixture existed.
    """
    assert vocab.unstated_residual(broken.CORRECT_QUEUE_RENDERING, broken.UNCOMPUTED_QUEUE) == [
        "residual_provisional"
    ], "the rule does not report a residual the queue never computed"


def test_the_prefetch_rule_control_session_declares_no_cache_attribute_at_all():
    """Absence, not `None`.

    `blind_prefetch_attributes` tests `is not None`, which is the right semantic for a *populated*
    cache — and it means a session declaring `prefetched_score = None` passes while being one
    assignment from the adversarial construction. The control asserts the attribute is not
    declared, so the fixture cannot drift into that state unnoticed.
    """
    session = broken.CompliantBlindSession()
    declared = [
        name for name in vocab.BLIND_PREFETCH_ATTRIBUTES if hasattr(session, name)
    ]
    assert declared == [], (
        f"the compliant control session declares {declared}. A slot for the score row is not the "
        "same as no route to it, and CT-REVIEW-09 is a claim about the route."
    )


def test_the_random_arm_produces_exactly_zero_review_items():
    """`CT-REVIEW-05`: *"produces no review item"* — zero, not "few".

    Asserted on the constant because `TC-REVIEW-C05` compares against it: raising it to 1 turns
    the red case into one that tolerates a leak, and mutation showed nothing caught that.
    """
    assert vocab.RANDOM_ARM_REVIEW_ITEMS == 0, (
        "CT-REVIEW-05 admits no random-arm review item at all. A tolerance of one is a tolerance "
        "for the arm spending teacher minutes, which is what stops it being an independent sample."
    )


# ==================================================================================================
# Controls for the machinery the review findings introduced
# ==================================================================================================


def test_items_shown_counts_members_rather_than_entries():
    """`CT-REVIEW-04`'s arithmetic is about items; `len(shown)` counts entries.

    §3.15 types `shown` as `Sequence[ReviewItem | ReviewGroup]`, so a queue presenting 200 items
    as 16 groups shows 16 entries and covers 200 items. Both shapes are exercised, because a
    helper that only handled groups would break the far commoner all-items case.
    """

    class _Group:
        def __init__(self, n):
            self.members = tuple(range(n))

    class _Item:
        pass

    assert vocab.items_shown(broken.QueueFigures(shown=("a", "b", "c"))) == 3

    mixed = type("Q", (), {"shown": (_Item(), _Group(12), _Item(), _Group(5))})()
    assert vocab.items_shown(mixed) == 1 + 12 + 1 + 5, (
        "a group is counted as one entry rather than as its members, so the residual arithmetic "
        "would demand back the items the group already covered"
    )
    assert vocab.items_shown(type("Q", (), {"shown": ()})()) == 0


def test_label_fields_in_matches_whole_identifiers_only():
    """`origin` is a substring of `original`, and a compliant prompt says "the original submission".

    Both directions: the rule must not fire on the compliant sentence and must fire on a prompt
    that genuinely carries the field.
    """
    assert vocab.label_fields_in("consider the original submission and its evidence") == [], (
        "the rule matched `origin` inside `original`, so it fails a prompt that says nothing "
        "about the label store"
    )
    assert vocab.label_fields_in("origin: escalation") == ["origin"]
    assert set(vocab.label_fields_in("teacher_band=B2 saw_system_output=1")) == {
        "teacher_band",
        "saw_system_output",
    }


def test_reachable_values_finds_a_value_nested_inside_the_structure():
    """`CT-REVIEW-09` step 2 asks whether the system's answer is *reachable*, not whether a key
    is present at the top level.

    The nested cases are the ones that matter: a session returning
    `{"items": [ref_with_a_system_band, ...]}` passes a `in` check on the mapping and hands the
    teacher the answer anyway.
    """
    sentinel = "B7-SYSTEM"

    assert vocab.reachable_values({"a": 1, "b": "safe"}, sentinel) == []
    assert vocab.reachable_values({"system_band": sentinel}, sentinel) == ["system_band"]
    assert vocab.reachable_values({"items": [{"band": sentinel}]}, sentinel) == ["items[0].band"]

    class _Ref:
        def __init__(self):
            self.system_band = sentinel

    assert vocab.reachable_values({"items": [_Ref()]}, sentinel) == ["items[0].system_band"], (
        "a value on an object attribute is not reachable to the walker, so a session handing back "
        "item refs rather than dicts defeats CT-REVIEW-09 step 2"
    )


def test_the_system_output_sentinels_are_distinctive_enough_to_attribute():
    """A probe that looks for `"B3"` in a page cannot say the value came from the score row.

    Every sentinel must be absent from the ordinary fixture, or step 2 reports a leak whenever the
    blind flow renders anything at all.
    """
    ordinary = repr(broken.flagged_population(40))
    for field, sentinel in broken.SYSTEM_OUTPUT_SENTINELS.items():
        assert str(sentinel) not in ordinary, (
            f"the {field!r} sentinel {sentinel!r} appears in the ordinary population, so "
            "CT-REVIEW-09 step 2 would report a leak for a compliant blind flow"
        )
    assert set(broken.SYSTEM_OUTPUT_SENTINELS) == set(vocab.BLIND_FORBIDDEN_FIELDS), (
        "the sentinels and FR-REVIEW-11's five absences have drifted apart, so a field is swept "
        "with no distinctive value to look for"
    )
    carried = broken.system_output_population(5)
    assert all(
        row.proposed_band == broken.SYSTEM_OUTPUT_SENTINELS["system_band"] for row in carried
    ), "the population does not actually carry the system's band, so the probe finds nothing"


def test_the_forbidden_label_fields_do_not_overlap_the_required_ones():
    """`CT-REVIEW-07`'s extra-field direction cannot condemn a field the same clause requires."""
    overlap = sorted(set(vocab.FORBIDDEN_LABEL_FIELDS) & set(vocab.LABEL_FIELDS))
    assert overlap == [], (
        f"{overlap} is both required by FR-REVIEW-09 and forbidden as a denormalization, so the "
        "set-equality assertion cannot be satisfied by any label"
    )
    assert "system_band" not in vocab.FORBIDDEN_LABEL_FIELDS, (
        "the system's band is the required half of the agreement pair, not a contamination — "
        "forbidding it would fail every compliant label"
    )
    assert "confidence" in vocab.FORBIDDEN_LABEL_FIELDS, (
        "a label carrying the system's confidence is one join from an agreement statistic that "
        "weights by the system's own certainty"
    )


def test_module_sources_walks_a_package_rather_than_reading_its_init():
    """`inspect.getsource(package)` returns `__init__.py` alone.

    Exercised against `tests.support` itself, which is a real package in this repo — so the
    control does not depend on `aeh.review` existing.
    """
    import tests.support as pkg

    names = [name for name, _ in vocab.module_sources(pkg)]
    assert "review_vocabulary.py" in names and "broken_review_fixtures.py" in names, (
        f"the walk found {names}; a package scan that sees only __init__.py would miss a "
        "numeric-entry parameter in any file but the first"
    )

    single = vocab.module_sources(vocab)
    assert len(single) == 1 and "SERVICE_MEMBERS" in single[0][1], (
        "a plain module is no longer read at all, so the scan works only for packages"
    )


def test_the_skip_consequence_terms_are_present_in_the_sentence_they_came_from():
    """The terms have to be a weakening of the sentence, not a different claim."""
    for term in vocab.SKIP_CONSEQUENCE_TERMS:
        assert term in vocab.SKIP_CONSEQUENCE, (
            f"{term!r} is required of a skip report but is not in the consequence FR-REVIEW-13 "
            "states, so the test would demand wording the design does not"
        )
    assert not vocab.SKIP_CONSEQUENCE_TERMS[0].startswith("no new"), (
        "the terms have collapsed back into the sentence, which is the string-equality gate this "
        "replaced"
    )
