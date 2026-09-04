"""The green half of TS-73: the transcription checks and the rule controls.

Nothing in this file tests `M-STATS`. `M-STATS` does not exist — it is four stories away and every
case in the other files in this directory is correctly red behind `writtenahead`. What runs here
is the *fixture's* correctness:

* **Transcription.** Every literal in `tests/support/stats_vocabulary.py` is asserted against
  design §3.16 itself, so when the design moves the suite goes red at the transcription rather
  than quietly encoding a contract nobody agreed to. This is drift detection, not coverage.
* **Rule controls, in both directions.** Every detector the red cases apply is exercised against
  copy a correct implementation produces *and* copy its clause forbids. The first direction is
  what stops a rule going vacuous; the second is what stops it condemning compliant source, which
  is the failure that gets a rule switched off.
* **Three findings, asserted rather than described.** `CT-STATS-09` has no requirement behind it;
  `CT-STATS-20`'s literal "no threshold is declared here" collides with §3.16's own Configuration
  block; `CT-STATS-02`'s percent-agreement half has no surface to assert against. Each is a claim
  about the design, so each is a test that fails the day the design is fixed — which is when
  somebody should be told.

Counting any of this as clause coverage would be a mistake, and §8.2 says as much: a green
written-ahead suite means the test is not asserting what it claims.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.support.doc_tables import DocRowMissing, markdown_rows, read_repo_text
from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab

pytestmark = pytest.mark.contract

DESIGN = "docs/design/detailed-design.md"


#: Module-scoped so the design document is read once for the whole file. It does not take the
#: session's `repo_root` fixture, which is function-scoped: pytest refuses that combination, and
#: the failure would arrive as a collection-time error rather than as a legible test failure.
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def design() -> str:
    return read_repo_text(REPO_ROOT, DESIGN)


@pytest.fixture(scope="module")
def design_rows(design: str) -> list[list[str]]:
    return markdown_rows(design)


def _row(rows: list[list[str]], identifier: str) -> list[str]:
    """The one table row whose **first cell** is `identifier`.

    `doc_tables.find_row` matches a needle anywhere in the row, and every `FR-STATS-*` and
    `CT-STATS-*` id in this design appears again in the traceability tables and in neighbouring
    modules' `Requires` blocks -- so a substring locator finds three rows and raises. Matching the
    id column is what makes the lookup unique, and it still raises rather than returning `None`:
    a locator that returns `None` turns a renamed row into a vacuous pass, which is the failure
    mode of every assertion built on top of it.
    """
    matches = [row for row in rows if row and row[0].strip(" `*") == identifier]
    if len(matches) != 1:
        raise DocRowMissing(
            f"{len(matches)} rows have {identifier!r} in the id column; expected exactly one"
        )
    return matches[0]


def _normalize(text: str) -> str:
    """Lowercase, with hyphens, underscores and backticks flattened to spaces.

    The design writes `hallucinated-claim rate` and this suite holds it as
    `hallucinated_claim_rate`; both are the same name and neither spelling is more correct. What
    is *not* flattened is word order, so a transcription that reordered a field set still fails.
    """
    return re.sub(r"[\s`_\-–]+", " ", text.lower()).strip()


def _tokens_present(name: str, text: str) -> bool:
    """Whether every word of `name` appears in `text`.

    Used where the design writes a requirement in prose — *"response length in tokens"* against
    this suite's `response_length_tokens`. A subset check on words is the honest comparison: it
    survives the connective the design uses and still fails if a feature is missing or renamed.
    """
    haystack = _normalize(text)
    return all(word in haystack for word in _normalize(name).split())


def _interfaces_block(design: str) -> str:
    """§3.16's Python Interfaces block, from `class ValidationStats` to the end of the fence."""
    start = design.index("class ValidationStats(Protocol):")
    end = design.index("```", start)
    return design[start:end]


# ==================================================================================================
# Transcription — every literal against the design
# ==================================================================================================


def test_the_admissibility_predicate_matches_fr_stats_01(design_rows):
    """`FR-STATS-01` — both halves of the predicate, and the fact that it is a conjunction."""
    row = " ".join(_row(design_rows, "FR-STATS-01"))
    normalized = _normalize(row)

    for field, value in vocab.ADMISSIBLE_LABEL_PREDICATE.items():
        assert f"{_normalize(field)} = '{value}'" in normalized, (
            f"FR-STATS-01 no longer states {field} = {value!r}; the transcription in "
            "stats_vocabulary has drifted from the requirement"
        )

    assert "and" in normalized.split("label type = 'blind'")[1][:20], (
        "FR-STATS-01's two conditions are no longer joined by 'and'. The conjunction is the "
        "clause: dropping either condition admits a different contaminated population."
    )


def test_the_agreement_figure_field_set_matches_the_interfaces_block(design):
    """`CT-STATS-02` / §3.16 — field set **equality**, in declaration order.

    Equality rather than containment: a field added to `AgreementFigure` without reaching this
    fixture is exactly the drift this file exists to catch, and a containment check would let it
    through for as long as the suite stays red.
    """
    block = design[design.index("class AgreementFigure:"):]
    block = block[: block.index("class NoValidationData")]
    declared = tuple(
        match.group(1)
        for match in re.finditer(r"^\s{4}(\w+)\s*:", block, flags=re.MULTILINE)
    )

    assert declared == vocab.AGREEMENT_FIGURE_FIELDS, (
        f"§3.16 declares AgreementFigure as {declared}, the fixture holds "
        f"{vocab.AGREEMENT_FIGURE_FIELDS}"
    )


def test_the_five_required_fields_are_the_ones_ct_stats_02_names(design_rows):
    """`CT-STATS-02` — *"carries `n`, `scoring_model`, `population_scope_id`, `backend_profile`,
    and `panel_build_ref` **in the same value** as the statistic"*.

    The three statistics are deliberately **not** in the required set: `qwk` and `ordinal_alpha`
    are `| None` in the design's own dataclass, so a construction-refusal sweep that demanded them
    would fail a compliant figure carrying κ alone.
    """
    row = _normalize(" ".join(_row(design_rows, "CT-STATS-02")))

    for field in vocab.REQUIRED_FIGURE_FIELDS:
        assert _normalize(field) in row, f"CT-STATS-02 no longer names {field}"

    assert set(vocab.REQUIRED_FIGURE_FIELDS) < set(vocab.AGREEMENT_FIGURE_FIELDS)
    assert not set(vocab.REQUIRED_FIGURE_FIELDS) & {"kappa", "qwk", "ordinal_alpha"}, (
        "a statistic is in the required-field set, so the construction-refusal sweep would "
        "demand qwk or ordinal_alpha — both of which §3.16 declares nullable"
    )


def test_the_no_validation_data_reasons_match_the_literal(design):
    """`CT-STATS-03` / §3.16 — the three reasons, as the `Literal` declares them."""
    block = _interfaces_block(design)
    declared = tuple(re.findall(r'"(no_[a-z_]+)"', block))

    assert declared == vocab.NO_VALIDATION_DATA_REASONS, (
        f"§3.16's Literal declares {declared}, the fixture holds "
        f"{vocab.NO_VALIDATION_DATA_REASONS}"
    )


def test_the_six_mvvp_steps_match_fr_stats_05(design_rows):
    """`FR-STATS-05` — the step→requirement mapping, parsed from the requirement itself.

    The design names the six as *"FR-STATS-02 (step 1), FR-STATS-15 (step 2) …"*, so the mapping
    is read rather than retyped. A step reassigned to a different requirement — the plausible
    change, since steps 2–5 are one contiguous block — turns this red.
    """
    row = " ".join(_row(design_rows, "FR-STATS-05"))
    declared = {
        int(step): f"FR-STATS-{fr}"
        for fr, step in re.findall(r"FR-STATS-(\d+) \(step (\d)\)", row)
    }

    assert declared == vocab.MVVP_STEPS, (
        f"FR-STATS-05 maps {declared}, the fixture holds {vocab.MVVP_STEPS}"
    )
    assert len(vocab.MVVP_STEPS) == 6, "the MVVP is six steps (CT-STATS-07)"


def test_the_four_rerun_triggers_match_fr_stats_19(design_rows):
    """`FR-STATS-19` — *"whenever any panel member, model build, quantization, or prompt template
    version changes"*. Four, and the sweep in `TC-STATS-C08` is one row per trigger."""
    row = " ".join(_row(design_rows, "FR-STATS-19"))

    for trigger in vocab.MVVP_RERUN_TRIGGERS:
        assert _tokens_present(trigger, row), f"FR-STATS-19 no longer names {trigger}"

    assert len(vocab.MVVP_RERUN_TRIGGERS) == 4


def test_the_pairing_threshold_matches_fr_stats_18(design_rows):
    """`FR-STATS-18` — 0.95, and *exceeds* rather than *reaches*.

    The comparison is transcribed too: a judge measured at exactly 0.95 is below the trigger, and
    an implementation using `>=` would pair a figure the requirement does not ask to be paired.
    """
    row = " ".join(_row(design_rows, "FR-STATS-18"))

    assert str(vocab.SELF_AGREEMENT_PAIRING_THRESHOLD) in row
    assert "exceeds" in row.lower(), (
        "FR-STATS-18 no longer says 'exceeds', so the strictness of the comparison has changed"
    )


def test_the_two_knobs_and_their_defaults_match_the_configuration_block(design):
    """§3.16 Configuration — `STATS_SUBGROUP_ANALYSIS_ENABLED` (false) and
    `STATS_MIN_N_FOR_HEADLINE` (30)."""
    block = design[design.index("`STATS_SUBGROUP_ANALYSIS_ENABLED`"):][:400]

    assert f"`{vocab.SUBGROUP_ANALYSIS_KNOB}` (default false)" in block
    assert vocab.SUBGROUP_ANALYSIS_DEFAULT is False
    assert f"`{vocab.MIN_N_FOR_HEADLINE_KNOB}` (Assumption: {vocab.MIN_N_FOR_HEADLINE_DEFAULT}" in block
    assert vocab.TOO_FEW_QUALIFIER in block, (
        "the qualifier below STATS_MIN_N_FOR_HEADLINE has been reworded; the fixture's copy is "
        "what TC-STATS-C20 asserts a small-sample figure renders with"
    )


def test_the_drift_sample_range_matches_fr_stats_09(design_rows):
    """`FR-STATS-09` — *"a 20–30 submission sample"*, judged criteria only, advisory."""
    row = " ".join(_row(design_rows, "FR-STATS-09"))
    low, high = vocab.DRIFT_SAMPLE_RANGE

    assert f"{low}–{high} submission sample" in row, (
        f"FR-STATS-09 no longer states a {low}–{high} submission sample"
    )
    assert "judged" in row and "advisory" in row


def test_the_promote_counters_match_fr_stats_10(design_rows):
    """`FR-STATS-10` — three counters, incremented **separately**, and the field closed to
    operational counts."""
    row = " ".join(_row(design_rows, "FR-STATS-10"))

    for counter in vocab.PROMOTE_COUNTERS:
        assert f"`{counter}`" in row, f"FR-STATS-10 no longer names {counter}"
    assert "separately" in row
    assert f"`{vocab.AGREEMENT_FIELD_CLOSED_TO_OPERATIONAL}`" in row


def test_the_compression_check_statistics_and_limitation_match_fr_stats_06(design_rows):
    """`FR-STATS-06` — the two statistics, and the limitation the report must carry."""
    row = " ".join(_row(design_rows, "FR-STATS-06"))

    for statistic in vocab.COMPRESSION_STATISTICS:
        assert f"`{statistic}`" in row
    assert vocab.CO_COMPRESSION_LIMITATION in row, (
        "FR-STATS-06's stated blind spot has been reworded. TC-STATS-C10 asserts the report "
        "carries this sentence in its return value, so the wording is part of the fixture."
    )


def test_the_narrative_metrics_match_fr_stats_12(design_rows):
    row = " ".join(_row(design_rows, "FR-STATS-12"))
    for metric in vocab.NARRATIVE_QUALITY_METRICS:
        assert _tokens_present(metric, row), f"FR-STATS-12 no longer names {metric}"


def test_the_surface_features_match_fr_stats_07(design_rows):
    row = " ".join(_row(design_rows, "FR-STATS-07"))
    for feature in vocab.SURFACE_FEATURES:
        assert _tokens_present(feature, row), f"FR-STATS-07 no longer names {feature}"


def test_the_protocol_members_match_the_interfaces_block_and_each_has_an_owning_story(design):
    """§3.16's `ValidationStats` — member set equality, plus a blocker for each.

    The second half is what keeps the red sweeps honest. `require()` reports whichever blocker
    resolves **first**, so a sweep over the surface keyed entirely on #115 would report six rows
    as runnable the moment the filter lands, against five functions that do not exist yet. Every
    member therefore has its own story in `MEMBER_ISSUE`, and this asserts the mapping is total.
    """
    block = _interfaces_block(design)
    declared = tuple(re.findall(r"def (\w+)\(self,", block))

    assert declared == vocab.PROTOCOL_MEMBERS, (
        f"§3.16 declares {declared}, the fixture holds {vocab.PROTOCOL_MEMBERS}"
    )
    assert set(vocab.MEMBER_ISSUE) == set(vocab.PROTOCOL_MEMBERS), (
        "a protocol member has no owning story in MEMBER_ISSUE, so a sweep row over it would be "
        "keyed on whatever blocker happened to resolve first"
    )
    assert set(vocab.MEMBER_ISSUE.values()) <= {"#115", "#116", "#117", "#118"}


def test_the_two_contract_alerts_match_the_observability_paragraph(design):
    """`CT-STATS-19` — both alerts, asserted against §3.16's Observability paragraph."""
    start = design.index("**Observability.** Label counts by type and origin")
    paragraph = _normalize(design[start:][:700])

    assert "blind sample skipped for consecutive administrations" in paragraph
    assert "surface proxy flag" in paragraph
    assert len(vocab.CONTRACT_ALERTS) == 2

    for alert, keywords in zip(
        vocab.CONTRACT_ALERTS, (("blind", "skipped", "consecutive"), ("surface", "proxy", "flag"))
    ):
        assert all(word in _normalize(alert) for word in keywords), (
            f"the alert name {alert!r} no longer says what §3.16's paragraph describes"
        )


def test_the_observability_counters_match_the_observability_paragraph(design):
    start = design.index("**Observability.** Label counts by type and origin")
    paragraph = design[start:][:700]
    for counter in vocab.OBSERVABILITY_COUNTERS:
        assert _tokens_present(counter, paragraph), f"§3.16 no longer emits {counter}"


def test_the_write_scope_matches_ct_stats_15(design_rows):
    """`CT-STATS-15` — what is written, through whom, and what is forbidden."""
    row = " ".join(_row(design_rows, "CT-STATS-15"))

    assert "`package_validation` (through `M-PKG`)" in row, (
        "CT-STATS-15's indirection has been reworded. The 'through M-PKG' is the clause — "
        "TC-STATS-C15 asserts the write appears under the catalog's frames, not that no write "
        "happened."
    )
    assert "Reads labels, grades, and metrics" in row
    for forbidden in ("score", "grade", "narrative", "package content"):
        assert f"no {forbidden}" in row.lower()


# ==================================================================================================
# Three findings about the design, asserted rather than described
# ==================================================================================================


def test_ct_stats_09_cites_no_requirement_and_no_story_can_own_it(design, design_rows):
    """**Finding.** `CT-STATS-09` is the one clause in the table with nothing behind it.

    Every other `CT-STATS` clause cites at least one `FR-STATS-*`; `-09` — criterion override
    history, and its explicit no-data value — cites none, and no `FR-STATS-*` row mentions
    override history at all. So #115–#118 between them implement every requirement in §3.16 and
    none of them implements this clause: `TC-STATS-C09` is a P0 case against behaviour no story
    delivers.

    Asserted here rather than reported in prose so that it is re-checked on every run and so that
    fixing the design — adding the requirement, or the story — is what turns it red.
    """
    clause_09 = " ".join(_row(design_rows, "CT-STATS-09"))
    assert "FR-STATS-" not in clause_09, (
        "CT-STATS-09 now cites a requirement — the finding is fixed and this test should be "
        "deleted along with the note in stats_vocabulary's docstring"
    )

    section = design[design.index("### 3.16 Module"):]
    section = section[: section.index("### 3.17 Module")]
    requirements = [
        " ".join(row) for row in markdown_rows(section) if row and row[0].startswith("FR-STATS-")
    ]
    assert requirements, "no FR-STATS rows found — the section parse has drifted"
    assert not [row for row in requirements if "override history" in _normalize(row)], (
        "an FR-STATS requirement now covers criterion override history; CT-STATS-09 has an owner"
    )


def test_the_literal_no_threshold_reading_collides_with_the_design(design, design_rows):
    """**Finding.** `CT-STATS-20`'s *"no threshold is declared here"* cannot be read literally.

    §3.16's Configuration block declares `STATS_MIN_N_FOR_HEADLINE` (Assumption: 30), and HLD
    §11.5's S12 mock-up depends on it — below that n, the figure renders with an explicit *"too
    few to draw conclusions from"* qualifier. A case asserting that `M-STATS` declares no
    threshold constant would go red against a **compliant** module.

    What `NFR-SYS-08` actually says is narrower and is the assertable form: *"No single threshold
    is declared here, because … a system-wide accuracy claim would be the §2.1 error."* The
    forbidden thing is a **quality verdict** — `validated`, `passes`, `meets_threshold` on a
    figure — not a display-qualifier boundary, which says nothing about whether a figure is good.

    So `TC-STATS-C20` asserts the scoped form and this test asserts the reasoning: both halves of
    the collision, so that if either moves the suite says so. Delete it the day the clause is
    reworded.
    """
    configuration = design[design.index("**Configuration.** `STATS_SUBGROUP_ANALYSIS_ENABLED`"):][:400]
    assert vocab.MIN_N_FOR_HEADLINE_KNOB in configuration, (
        "§3.16 no longer declares a threshold constant, so CT-STATS-20's literal reading is "
        "satisfiable after all and this finding is stale"
    )

    clause = " ".join(_row(design_rows, "CT-STATS-20"))
    assert "no threshold is declared here" in clause

    nfr = " ".join(_row(design_rows, "NFR-SYS-08"))
    assert "No single threshold is declared here" in nfr
    assert "system-wide accuracy claim" in nfr, (
        "NFR-SYS-08 no longer scopes its prohibition to a system-wide accuracy claim, which is "
        "the authority TC-STATS-C20 reads the clause under"
    )
    assert vocab.MIN_N_IS_NOT_A_VERDICT_THRESHOLD is True


def test_ct_stats_02s_percent_agreement_half_has_no_surface_to_assert_against(design):
    """**Finding.** *"No raw percent-agreement is emitted without its chance-corrected counterpart
    attached"* is, today, a conditional over an empty set.

    `AgreementFigure` declares three statistics and every one of them is chance-corrected; there
    is no percent-agreement field for the clause to govern, so a test written to that half passes
    for any implementation, forever, including one that adds a percent figure elsewhere.

    The assertable half of `CT-STATS-02` — the construction refusal and the field-set equality —
    is implemented in `TC-STATS-C02`. This one is asserted as an absence, so the day a story adds
    a percent field (#115 owns `AgreementFigure`; nothing schedules one), this goes red and the
    conditional becomes worth writing.
    """
    block = design[design.index("class AgreementFigure:"):]
    block = block[: block.index("class NoValidationData")]

    assert not re.search(r"percent|pct|raw_agreement|observed_agreement", block), (
        "AgreementFigure now declares a raw-agreement field, so CT-STATS-02's second half has a "
        "surface: TC-STATS-C02 should grow the assertion that it never travels alone"
    )
    assert set(vocab.AGREEMENT_FIGURE_FIELDS) & {"kappa", "qwk", "ordinal_alpha"}, (
        "no chance-corrected statistic is left in the figure"
    )


# ==================================================================================================
# Rule controls — both directions, one pair per detector
# ==================================================================================================


def test_the_filter_cardinality_rule_finds_exactly_one_site_in_compliant_source():
    """The direction that gets skipped: compliant source must **pass**.

    `CORRECT_STATS_SOURCE` defines the predicate once and reuses it from three functions — which
    is what `NFR-STATS-04` asks for. An earlier draft of this rule counted mentions of `'blind'`
    and reported four sites here, failing correct source; that rule would have been switched off
    within a release.
    """
    sites = vocab.admissibility_definition_sites(broken.CORRECT_STATS_SOURCE)
    assert sites == ["admissible_labels"], (
        f"the rule found {sites} in source that defines the predicate exactly once"
    )


def test_the_filter_cardinality_rule_accepts_a_module_level_predicate():
    """A filter expressed as a module constant is one definition, and compliant.

    A rule that only saw functions would report zero sites here — and an oracle written as
    "exactly one" would then fail a reasonable implementation for having the wrong shape rather
    than the wrong count.
    """
    assert vocab.admissibility_definition_sites(
        broken.FILTER_AS_MODULE_CONSTANT_SOURCE
    ) == ["<module>"]


def test_the_filter_cardinality_rule_catches_a_second_inlined_definition():
    sites = vocab.admissibility_definition_sites(broken.FILTER_INLINED_TWICE_SOURCE)
    assert len(sites) == 2, f"the second inlined predicate was not seen: {sites}"
    assert "agreement_for_dashboard" in sites


def test_the_filter_cardinality_rule_reports_zero_when_there_is_no_filter():
    """The oracle is **exactly one**, not *at most one*.

    `NO_FILTER_SOURCE` computes agreement over every label it is handed. A case asserting `<= 1`
    would pass it, which is the violation `CT-STATS-01` exists to make impossible.
    """
    assert vocab.admissibility_definition_sites(broken.NO_FILTER_SOURCE) == []


def test_the_surface_rule_passes_a_compliant_public_surface():
    """Every name design §3.16 declares, plus four that carry one half of the conjunction.

    `operational_count` names a population; `agreement` and `agreement_kappa` name the statistic.
    None is a violation, and a rule reading either term alone would condemn all three.
    """
    assert vocab.surface_admitting_other_populations(broken.CORRECT_SURFACE_NAMES) == []


def test_the_surface_rule_catches_the_clauses_named_adversarial_construction():
    flagged = vocab.surface_admitting_other_populations(
        broken.SURFACE_NAMES_ADMITTING_OTHER_POPULATIONS
    )
    assert set(flagged) == set(broken.SURFACE_NAMES_ADMITTING_OTHER_POPULATIONS), (
        f"the rule missed {set(broken.SURFACE_NAMES_ADMITTING_OTHER_POPULATIONS) - set(flagged)}; "
        "`compute_agreement_all_labels` is the construction CT-STATS-01 names by hand"
    )


def test_the_bypass_rule_passes_source_that_routes_through_the_filter():
    assert vocab.agreement_functions_bypassing_the_filter(
        broken.CORRECT_STATS_SOURCE, filter_names={"admissible_labels"}
    ) == []


def test_the_bypass_rule_passes_a_function_that_takes_already_filtered_labels():
    """Pushing the filter to the caller and saying so in the signature is compliant.

    A rule insisting on seeing the call would fail this, and the reflex fix is to call the filter
    twice — which is `NFR-STATS-04`'s violation arriving by way of its own detector.
    """
    assert vocab.agreement_functions_bypassing_the_filter(
        broken.AGREEMENT_TAKING_FILTERED_LABELS_SOURCE, filter_names={"admissible_labels"}
    ) == []


def test_the_bypass_rule_catches_an_innocuously_named_function_reading_labels_directly():
    """The violation the name rule cannot see: `criterion_agreement` is exactly what it computes."""
    flagged = vocab.agreement_functions_bypassing_the_filter(
        broken.AGREEMENT_BYPASSING_THE_FILTER_SOURCE, filter_names={"admissible_labels"}
    )
    assert flagged == ["criterion_agreement"]
    assert vocab.surface_admitting_other_populations(["criterion_agreement"]) == [], (
        "the name rule now flags this too, so the structural rule is no longer the only thing "
        "standing between a direct label read and a validity claim — check the name rule has not "
        "widened into something that would condemn `agreement` itself"
    )


def test_the_merge_rule_passes_a_compliant_surface():
    assert vocab.merging_surface(broken.CORRECT_SURFACE_NAMES) == []


def test_the_merge_rule_catches_every_forbidden_combination():
    flagged = vocab.merging_surface(broken.MERGING_SURFACE_NAMES)
    assert set(flagged) == set(broken.MERGING_SURFACE_NAMES), (
        f"missed {set(broken.MERGING_SURFACE_NAMES) - set(flagged)}"
    )
    assert "combined_quality_score" in flagged, (
        "CT-STATS-14's exact failure — κ and narrative quality in one number — went unflagged"
    )


def test_the_headline_rule_passes_the_hld_s12_agreement_block():
    """A compliant block: every figure scoped, the small sample qualified, κ in Greek.

    The Greek spelling is the control that matters. The `M-CONSOLE` suite shipped a rule that did
    not know `κ` and it condemned HLD §11.5's own mock-up.
    """
    assert vocab.unscoped_headline_figures(broken.CORRECT_AGREEMENT_BLOCK) == []


@pytest.mark.parametrize("rendering", broken.HEADLINE_RENDERINGS)
def test_the_headline_rule_catches_a_system_wide_framing(rendering):
    assert vocab.unscoped_headline_figures(rendering), (
        f"{rendering!r} renders a figure as a claim about the system and was not flagged"
    )


@pytest.mark.parametrize("rendering", broken.UNSCOPED_FIGURE_RENDERINGS)
def test_the_headline_rule_catches_a_number_with_no_scope_beside_it(rendering):
    assert vocab.unscoped_headline_figures(rendering)


def test_the_headline_rule_reads_lines_not_documents():
    """A headline above forty scoped rows is the screen `CT-STATS-20` describes.

    Concatenating the page and asking whether "population" appears anywhere in it would pass this
    — which is why the rule scans per line.
    """
    page = "Overall accuracy: 87%\n" + broken.CORRECT_AGREEMENT_BLOCK
    problems = vocab.unscoped_headline_figures(page)
    assert len(problems) == 1 and "overall accuracy" in problems[0].lower()


def test_the_degeneracy_rule_passes_a_compliant_disclosure():
    assert vocab.presents_binary_agreement_as_equivalent(
        broken.CORRECT_DEGENERACY_DISCLOSURE
    ) == []


@pytest.mark.parametrize("rendering", broken.EQUIVALENCE_RENDERINGS)
def test_the_degeneracy_rule_catches_the_equivalence_claim(rendering):
    assert vocab.presents_binary_agreement_as_equivalent(rendering)


def test_the_coercion_probe_reports_nothing_for_a_compliant_absence_value():
    assert vocab.numeric_coercions(broken.CompliantNoValidationData("no_blind_labels")) == []


def test_the_coercion_probe_catches_the_float_subclass_construction():
    """`CT-STATS-03`'s named adversarial construction, and every coercion it permits.

    All five, not one: the point of the construction is that *every* call site keeps working, so a
    probe that only tried `float()` would understate what shipping it costs.
    """
    permitted = vocab.numeric_coercions(broken.FloatSubclassNoValidationData())
    assert set(permitted) == {"float", "arithmetic", "comparison", "format_percent", "multiplication"}


def test_the_write_rule_passes_source_that_reads_grades_and_writes_only_its_own_rows():
    """The control that matters most here: `CT-STATS-15` **grants** reads of grades and metrics.

    A rule matching table names rather than write verbs would condemn `SELECT … FROM grade`, which
    is the module's whole reason for existing.
    """
    assert vocab.forbidden_write_statements(broken.CORRECT_WRITE_SCOPE_SOURCE) == []


@pytest.mark.parametrize("table, source", sorted(broken.FORBIDDEN_WRITE_SOURCES.items()))
def test_the_write_rule_catches_each_forbidden_write(table, source):
    problems = vocab.forbidden_write_statements(source)
    assert problems and any(table in problem for problem in problems), (
        f"a write to {table} was not flagged: {problems}"
    )
