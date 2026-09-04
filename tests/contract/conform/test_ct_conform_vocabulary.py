"""The green half of TS-75: does the fixture still match the design, and do the rules still fire?

**None of this is coverage of a `CT-CONFORM` clause, and it must not be counted as any.** Eleven
of the fourteen cases are behaviourally red behind `writtenahead`, waiting on #133 and #134. What
runs here is the scaffolding those cases stand on:

* the **transcription** — the five divergence dimensions, the corpus bounds, the adversarial
  vocabulary, the consent classes — checked against the design text they were copied from, so a
  reworded clause goes red at the fixture rather than silently renaming a field in eleven tests;
* the **rules** — the tier-wiring check, the hole detector and the consent-reimplementation scan —
  checked against deliberately broken documents, because a rule that has stopped firing is
  indistinguishable from a rule that is passing.

The second half is the one worth being stubborn about. TS-57 shipped a source scan whose positive
control asserted only that a planted row was *flagged*; stubbing one predicate disabled four of
its six rules and every row stayed green. So every control here asserts the problem list **by
name**, and every rule has a good document alongside the broken one — otherwise `return
EVERYTHING` and `return NOTHING` would each pass half the controls.
"""

from __future__ import annotations

import pytest

from tests.support import broken_conform_docs as broken
from tests.support.conform_vocabulary import (
    AGREEMENT_DIMENSION,
    CLASSIFICATION_BLOCKING,
    CLASSIFICATION_INFORMATIONAL,
    CLASSIFICATION_UNAVAILABLE,
    CONFORMANCE_BUDGET_SECONDS,
    CONSENT_CLASSES_ALLOWED,
    CONSENT_CLASSES_REFUSED,
    CORPUS_MAX,
    CORPUS_MIN,
    DIMENSION_CLAUSE_PHRASES,
    DIVERGENCE_DIMENSIONS,
    EXPECTED_CLASSIFICATION,
    GATE_DIMENSIONS,
    INFORMATIONAL_DIMENSIONS,
    INJECTION_PAYLOAD_KINDS,
    LEGIBILITY_SPAN,
    LIVE_GATE_DIMENSION,
    MALICIOUS_PDF_KINDS,
    OBSERVABILITY_FIELDS,
    PROTOCOL_MEMBERS,
    REQUIRED_MEDIA_KINDS,
    RESOLVED_BUILDS_FIELD,
    UNAVAILABLE_GATE_DIMENSION,
    combined_figure_names,
    consent_reimplementation_sites,
    divergence_hole_problems,
    equivalence_claims,
    module_sources,
    simulated_implementation_module,
    tier_wiring_problems,
)
from tests.support.doc_tables import DocRowMissing, find_row, markdown_rows, read_repo_text
from tests.support.guards import recording_write_audit

pytestmark = pytest.mark.contract

DESIGN = "docs/design/detailed-design.md"
PLAN = "docs/design/test-plan.md"


def _clause_row(repo_root, clause_id: str) -> str:
    """The design's contract-table row for `clause_id`, as one lower-cased string."""
    rows = markdown_rows(read_repo_text(repo_root, DESIGN))
    matches = [row for row in rows if row and row[0] == clause_id]
    if len(matches) != 1:
        raise DocRowMissing(
            f"expected exactly one contract row whose first cell is {clause_id!r}; found "
            f"{len(matches)}. The transcription below is keyed to that row."
        )
    return " ".join(matches[0]).lower()


# --- the transcription --------------------------------------------------------------------------


def test_the_five_dimension_names_transcribe_the_ct_conform_04_clause(repo_root):
    """Every field name in the fixture traces to a phrase that is still in the clause.

    The direction matters. This asserts **fixture → design**: each of the five names the suite
    will assert set-equality against carries a clause phrase, and that phrase is still there. The
    reverse direction — building the expected set by reading the design — is the tautology TS-58
    hit with `DESIGN_RUN_CONFIG_FIELDS`, where a test that derived its expectation from the thing
    under test could not fail.
    """
    row = _clause_row(repo_root, "CT-CONFORM-04")

    assert set(DIMENSION_CLAUSE_PHRASES) == DIVERGENCE_DIMENSIONS, (
        "every dimension must carry the clause phrase it was transcribed from, or the "
        "transcription is unverifiable by reading"
    )

    missing = {
        name: phrase
        for name, phrase in DIMENSION_CLAUSE_PHRASES.items()
        if phrase not in row
    }
    assert not missing, (
        f"CT-CONFORM-04 no longer contains the phrases these field names were transcribed from: "
        f"{missing}. The clause moved; the fixture has not."
    )

    assert len(DIVERGENCE_DIMENSIONS) == 5, (
        "CT-CONFORM-04 declares five dimensions and the case's oracle is set equality; a fixture "
        "of four or six makes that oracle assert the wrong thing"
    )

    # **Every word of the field name must be justified by its phrase.** Presence alone is too weak
    # a check, and mutation testing showed it: shortening `chance-corrected agreement with the
    # fixture labels` to `agreement with the fixture labels` left this test green, because the
    # shorter phrase is still in the clause. `chance-corrected` is the load-bearing half — plain
    # agreement is the statistic the design deliberately does not use — so a phrase that had
    # quietly dropped it would leave the field name claiming something its source no longer says.
    for name, phrase in DIMENSION_CLAUSE_PHRASES.items():
        normalized = phrase.replace("-", " ").lower()
        unjustified = [token for token in name.split("_") if token not in normalized]
        assert not unjustified, (
            f"{name!r} carries {unjustified} that its transcribed phrase {phrase!r} does not "
            f"say. Either the field name overclaims or the phrase has been weakened."
        )


def test_the_gate_partition_is_exhaustive_over_the_five_dimensions():
    """`CT-CONFORM-05` splits the five into two gates and three findings — with nothing left over.

    A classification that covered four dimensions and dropped one would pass every per-dimension
    assertion in the suite while leaving one dimension unclassified, which is `CT-CONFORM-04`'s
    failure mode wearing `CT-CONFORM-05`'s name. So the partition is asserted as a partition:
    the union is exactly the five, and the two parts are disjoint.
    """
    assert GATE_DIMENSIONS | INFORMATIONAL_DIMENSIONS == DIVERGENCE_DIMENSIONS
    assert not (GATE_DIMENSIONS & INFORMATIONAL_DIMENSIONS)
    assert len(GATE_DIMENSIONS) == 2, "the clause declares exactly two gates"
    assert len(INFORMATIONAL_DIMENSIONS) == 3

    assert UNAVAILABLE_GATE_DIMENSION != LIVE_GATE_DIMENSION, (
        "the two gates must be different dimensions — one is computable and one is not, and "
        "collapsing them is how CT-CONFORM-14's hole stops being visible"
    )
    assert set(EXPECTED_CLASSIFICATION) == DIVERGENCE_DIMENSIONS, (
        "every dimension needs a declared expected classification, or a case parametrized over "
        "this mapping silently skips the dimension nobody added"
    )

    # **The partition and the expected classifications must agree.** The union and disjointness
    # assertions above cannot fail on their own — `INFORMATIONAL_DIMENSIONS` is *defined* as the
    # complement — so this is the row that does the work. Without it, flipping one dimension in
    # `EXPECTED_CLASSIFICATION` would leave `TC-CONFORM-C05`'s two red tests contradicting each
    # other, with nothing naming the cause.
    derived = {
        dimension: (CLASSIFICATION_INFORMATIONAL if dimension in INFORMATIONAL_DIMENSIONS else None)
        for dimension in DIVERGENCE_DIMENSIONS
    }
    derived[UNAVAILABLE_GATE_DIMENSION] = CLASSIFICATION_UNAVAILABLE
    derived[LIVE_GATE_DIMENSION] = CLASSIFICATION_BLOCKING
    assert EXPECTED_CLASSIFICATION == derived, (
        f"the gate partition and the expected classifications disagree: partition implies "
        f"{derived}, the fixture declares {EXPECTED_CLASSIFICATION}"
    )


def test_the_corpus_bounds_transcribe_fr_conform_01(repo_root):
    """30–50, and the numbers are still the design's."""
    design = read_repo_text(repo_root, DESIGN).lower()
    assert "30–50 submissions spanning the score range" in design, (
        "FR-CONFORM-01's corpus bound was reworded; CORPUS_MIN/CORPUS_MAX are transcribed from it"
    )
    assert (CORPUS_MIN, CORPUS_MAX) == (30, 50)
    assert CORPUS_MIN < CORPUS_MAX


def test_the_media_and_legibility_vocabulary_transcribes_fr_conform_03(repo_root):
    """`CT-CONFORM-02`'s corpus properties, including the half that is easy to lose.

    *"Real scanned handwriting spanning legible to marginal"* is two claims — that handwriting is
    present, and that it **spans**. A corpus of clean, legible scans satisfies the first and is
    exactly the corpus the clause warns about, so `LEGIBILITY_SPAN` carries both ends.
    """
    row = _clause_row(repo_root, "CT-CONFORM-02")
    assert "real scanned handwriting spanning legible to marginal" in row
    assert "mixed-format paper" in row
    assert LEGIBILITY_SPAN == ("legible", "marginal")
    assert REQUIRED_MEDIA_KINDS == {"scanned_handwriting", "mixed_format"}


def test_the_adversarial_vocabulary_transcribes_fr_conform_09(repo_root):
    """The three injection shapes and the four malicious-PDF shapes, still named in the design."""
    design = read_repo_text(repo_root, DESIGN).lower()
    for phrase in ("band-forcing directives", "forged citations", "contract-breaking instructions"):
        assert phrase in design, f"FR-CONFORM-09 no longer names {phrase!r}"
    for phrase in ("embedded javascript", "launch/open actions", "embedded files", "decompression bombs"):
        assert phrase in design, f"FR-CONFORM-09 no longer names {phrase!r}"

    assert len(INJECTION_PAYLOAD_KINDS) == 3
    assert len(MALICIOUS_PDF_KINDS) == 4


def test_the_observability_fields_transcribe_the_design_observability_line(repo_root):
    """`CT-CONFORM-13`, and the word it turns on.

    The clause says **resolved** builds, and §6.11.18 spells out why: a report naming only the
    requested builds *"would be consistent with a silent substitution"* — the failure
    `CT-CONFORM-07` exists to catch. So the fixture's field is `resolved_builds`, and the
    assertion is that the design still says *resolved*.
    """
    row = _clause_row(repo_root, "CT-CONFORM-13")
    assert "resolved builds" in row
    assert "both" in row, "the clause requires both backends' builds, not one"
    assert RESOLVED_BUILDS_FIELD == "resolved_builds"
    assert OBSERVABILITY_FIELDS == {
        "per_dimension_divergence",
        "fixture_set_version",
        "resolved_builds",
    }


def test_the_protocol_members_are_exactly_the_two_the_interfaces_block_declares(repo_root):
    """Design §3.18 declares `run` and `compare` and nothing else.

    Recorded here because it is the reason almost every name this suite calls is **invented**. A
    fourteen-clause contract resting on a two-member Protocol means the tests must name the
    surfaces they drive before anyone has written them — which is stated in the PR rather than
    hidden, and is also why no blocker in this suite is keyed on a Protocol member.
    """
    design = read_repo_text(repo_root, DESIGN)
    block = design[design.index("class ConformanceSuite(Protocol):") :][:400]
    declared = tuple(
        line.split("def ", 1)[1].split("(", 1)[0]
        for line in block.splitlines()
        if line.strip().startswith("def ")
    )
    assert declared == PROTOCOL_MEMBERS, (
        f"design §3.18's Interfaces block now declares {declared}; the suite was written against "
        f"{PROTOCOL_MEMBERS}. A member added here is a name the tests should be using."
    )


def test_the_consent_vocabulary_agrees_with_the_module_that_enforces_it():
    """`CT-CONFORM-10`'s allowed classes are read from `M-CONF`, not copied beside it.

    `aeh.conf` exists, so `CONSENTED_CLASSES` can be asserted against directly. That is the point
    of the clause: the enforcement lives in one place, so the vocabulary should too. The fixture's
    copy is asserted **equal** to the module's rather than used in its place, and the refused list
    is asserted disjoint — a class in both lists would make the sweep in `TC-CONFORM-C10` assert
    that the same input is both accepted and refused.
    """
    from aeh.conf import CONSENTED_CLASSES

    assert CONSENT_CLASSES_ALLOWED == set(CONSENTED_CLASSES), (
        "M-CONF's consent classes and this suite's copy have drifted. CT-CONFORM-10 says M-CONF "
        "is what enforces the boundary, so M-CONF is what defines it."
    )
    named = {c for c in CONSENT_CLASSES_REFUSED if isinstance(c, str) and c}
    assert not (named & CONSENT_CLASSES_ALLOWED)
    assert "real" in named, "ADR-5's third class must be in the refused sweep"
    assert None in CONSENT_CLASSES_REFUSED, (
        "a cohort whose consent was never recorded is 'not so flagged' and must be swept too — "
        "an absent flag is the common case, not the exotic one"
    )


def test_the_budget_transcribes_nfr_conform_02_and_the_plan_row(repo_root):
    """One hour per backend, from the requirement and from §4.7's row.

    `NFR-CONFORM-02` says *"well under an hour"*, which is prose. §4.7 turns it into `< 60 min per
    backend`, which is a number. The suite asserts the number and reports the *"well"* as
    unquantified rather than inventing a factor for it — a made-up 0.5 here would become the
    requirement the first time someone hit it.
    """
    assert CONFORMANCE_BUDGET_SECONDS == 3600
    row = find_row(markdown_rows(read_repo_text(repo_root, PLAN)), "harness.conform")
    assert "< 60 min per backend" in " ".join(row)


# --- the rules, against deliberately broken documents ---------------------------------------------


def test_the_combined_figure_net_exempts_the_five_required_dimensions():
    """`CT-CONFORM-04`'s prohibition, and the collision it is built on.

    One of the five *required* dimensions is a **score** distribution and the prohibition is on a
    single conformance **score**. The two vocabularies overlap by construction, so a substring net
    on `score` fails a correct report — the same shape as TS-74's sweep that rejected the very
    disclaimer its clause required, twice over.

    Both directions are asserted, because either alone is satisfied by a broken net: the five must
    pass, and the headline names must be caught.
    """
    assert combined_figure_names(sorted(DIVERGENCE_DIMENSIONS)) == [], (
        "the net condemns a required dimension, so it would fail every correct DivergenceReport"
    )

    # A plausible whole `ConformanceReport` surface, not a handful of scope keys. Proving the five
    # dimensions are exempt and five headline names are caught says nothing about the twenty other
    # names a real report carries — and those are what the sweep will actually run over. Each name
    # below is one the clauses in this suite either require or make likely: `reference_scores` is
    # CT-CONFORM-01's, `resolved_builds` is CT-CONFORM-13's, `scoring_model` is a CT-STATS-04 scope
    # key, `compare` and `run` are the Protocol.
    plausible = [
        "run",
        "compare",
        "per_backend",
        "divergence",
        "dimensions",
        "fixture_set_version",
        "fixture_ids",
        "content_hash",
        "resolved_builds",
        "requested_builds",
        "reference_scores",
        "scores_by_criterion",
        "scoring_model",
        "backend_profile",
        "panel_build_ref",
        "validation_records",
        "findings",
        "blocking_dimensions",
        "unavailable_dimensions",
        "passing_dimensions",
        "grade_policy",
        "pass_rate",
        "duration_seconds",
    ]
    assert combined_figure_names(plausible) == [], (
        "the net condemns names a correct ConformanceReport plausibly carries, so TC-CONFORM-C04 "
        "would go red against a compliant implementation and be switched off by whoever hit it"
    )

    for headline in ("conformance_score", "overall_score", "overall", "passed", "verdict"):
        assert combined_figure_names([headline]) == [headline], (
            f"{headline!r} is exactly the headline figure CT-CONFORM-04 forbids and the net "
            f"missed it"
        )

    # The token path, which is what catches a headline nobody thought to list. Review measured the
    # first version of this net — exact names plus four tokens — letting eight plausible headline
    # figures through, so `score` joined the token list and these rows are the record of it.
    for compound in (
        "overall_status",
        "conformance_verdict",
        "backend_equivalence",
        "is_equivalent",
        "final_score",
        "aggregate_score",
        "headline_score",
        "divergence_score",
        "conformance_index",
        "summary",
        "is_pass",
        "result",
    ):
        assert combined_figure_names([compound]) == [compound], (
            f"{compound!r} reads as a combined figure or an equivalence claim and the net missed "
            f"it — an exact-name list alone cannot catch a name nobody enumerated"
        )

    # The one name carrying the `score` token that a **correct** report is required to have:
    # CT-CONFORM-07 reports build substitution as "a score shift". Exempted by name, so adding the
    # token did not buy four catches at the price of one false positive.
    assert combined_figure_names(["score_shift", "score_shifts"]) == []


def test_the_equivalence_sweep_permits_the_disclaimer_the_clause_requires():
    """`CT-CONFORM-14`'s sweep must not fail the copy `CT-CONFORM-14` demands.

    The clause obliges a consumer to say the gate *cannot fire*. Every phrasing of that sentence
    contains the words a naive claim-detector forbids. TS-74 shipped exactly this bug — a scan
    that rejected `"not evidence the revision improved the rubric"` because it contained
    `improved` — and a scanner that fails correct copy is a scanner somebody switches off.
    """
    honest = (
        "Backend equivalence cannot be reported: the score-distribution gate is unavailable "
        "because no statistic is declared. These figures are not evidence that the backends "
        "are equivalent."
    )
    assert equivalence_claims(honest) == [], (
        "the sweep rejects the disclaimer the clause requires a consumer to print"
    )

    dishonest = "Conformance passed. The backends are equivalent and the record may be shared."
    assert len(equivalence_claims(dishonest)) == 2, (
        "the sweep must catch an affirmative equivalence claim in both of its sentences"
    )


def test_the_tier_wiring_rules_fire_on_a_table_wired_the_wrong_way(repo_root):
    """`TC-CONFORM-C08` and `-C11` rest on this rule, so the rule gets its own control.

    Asserted **by name**, not by count and not by "something was flagged". TS-57's positive
    control asserted containment and stayed green with four of six rules disabled; the fix there
    and here is to name every problem the broken document must produce.
    """
    assert tier_wiring_problems(broken.GOOD_PLAN_TIER_TABLE, broken.GOOD_TEST_SH) == [], (
        "the rule flags a correctly wired table, so it would fail on the real one for the wrong "
        "reason"
    )

    assert set(tier_wiring_problems(broken.BROKEN_PLAN_TIER_TABLE, broken.BROKEN_TEST_SH)) == {
        "conformance_wired_per_commit",
        "conformance_trigger_names_no_change_condition",
        "conformance_trigger_cites_no_requirement",
        "conformance_budget_missing",
        "fast_tier_admits_live",
        "test_sh_admits_live",
        "test_sh_runs_the_conformance_suite",
    }

    # **The near-miss that the first version of this rule walked straight through.** `scripts/test.sh`
    # quotes §4.7's marker string in a comment as well as assigning it, so a whole-file check stayed
    # green when the live exclusion was deleted from the string that is actually executed. The rule
    # now reads the `DEFAULT_MARKERS` assignment; this row is what proves it.
    assert tier_wiring_problems(
        broken.GOOD_PLAN_TIER_TABLE, broken.TEST_SH_WITH_LIVE_ONLY_IN_A_COMMENT
    ) == ["test_sh_admits_live"]

    # A missing row is its own finding: every rule downstream of the locator is vacuous without it.
    assert tier_wiring_problems(
        broken.PLAN_TABLE_WITHOUT_CONFORMANCE, broken.GOOD_TEST_SH
    ) == ["conformance_row_missing"]
    assert tier_wiring_problems(
        broken.PLAN_TABLE_WITHOUT_FAST_TIER, broken.GOOD_TEST_SH
    ) == ["fast_tier_row_missing"]

    # Two matching rows is an ambiguity the locator refuses rather than resolving silently.
    with pytest.raises(DocRowMissing, match="must name exactly one"):
        find_row(
            markdown_rows(broken.PLAN_TABLE_WITH_DUPLICATE_CONFORMANCE), "harness.conform"
        )


def test_the_hole_rules_fire_on_each_document_that_closes_it():
    """`TC-CONFORM-C14` is supposed to be **deleted** the day the statistic is declared.

    A case that only asserted "the report marks the gate unavailable" would never notice that day:
    it would keep passing against a module that had been fixed, and the case would outlive its
    subject. So the detector spans three passages, and each one closing produces its own named
    problem — which is what makes the failure message actionable rather than merely red.
    """
    assert divergence_hole_problems(broken.GOOD_DESIGN_HOLE, broken.GOOD_PLAN_HOLE) == []

    assert "clause_no_longer_declares_the_gate_uncomputable" in divergence_hole_problems(
        broken.DESIGN_CLAUSE_NO_LONGER_UNCOMPUTABLE, broken.GOOD_PLAN_HOLE
    )
    assert "design_open_question_resolved_or_reworded" in divergence_hole_problems(
        broken.DESIGN_HOLE_CLOSED, broken.GOOD_PLAN_HOLE
    )
    assert divergence_hole_problems(broken.GOOD_DESIGN_HOLE, broken.PLAN_GAP_ROW_CLOSED) == [
        "plan_gap_row_no_longer_accepted_risk"
    ]
    assert divergence_hole_problems(
        broken.GOOD_DESIGN_HOLE, broken.PLAN_RELEASE_GATE_EXCLUSION_DROPPED
    ) == ["plan_release_gate_no_longer_excludes_the_divergence_gate"]


def test_the_consent_reimplementation_scan_has_a_positive_and_a_negative_control():
    """`TC-CONFORM-C10`'s structural half cannot run until #133, so its rule is exercised here.

    Without this the scan would sit unrun for two phases and land on a real module having never
    been shown to work — and the first person to see it flag nothing would reasonably conclude the
    module was clean.

    The negative control mentions `consent_class` four times and imports `CONSENTED_CLASSES` by
    name, because that is what a correct delegating implementation looks like: a scan keyed on the
    *word* rather than on the *decision* condemns it and is useless.
    """
    assert consent_reimplementation_sites(broken.DELEGATING_CONFORM_SOURCE) == [], (
        "a module that reads consent_class and delegates the decision to M-CONF is exactly what "
        "CT-CONFORM-10 requires; flagging it makes the scan unusable"
    )

    sites = consent_reimplementation_sites(broken.REIMPLEMENTING_CONFORM_SOURCE)
    assert len(sites) == 3, (
        f"the three shapes an implementer reaches for — ==, in (...), and the reversed comparison "
        f"— must all be caught; caught {sites}"
    )
    assert {literal for _, literal in sites} == {"real", "consented", "synthetic"}

    # **The controls that are not fitted to the rule.** Review measured five realistic
    # re-implementations against the first version of this scan and all five walked through it,
    # including `not in CONSENTED_CLASSES` — the shape a careful implementer writes, because
    # importing M-CONF's own constant looks like delegation. Each is asserted by name so a
    # regression says which shape stopped being caught.
    missed = [
        label
        for label, source in broken.EVASIVE_REIMPLEMENTATIONS.items()
        if not consent_reimplementation_sites(source)
    ]
    assert not missed, (
        f"these re-implementations of the consent gate are invisible to the scan: {missed}. Each "
        f"is a second consent check inside M-CONFORM, which is what CT-CONFORM-10 forbids."
    )


def test_the_consent_scan_reads_every_file_of_a_package_not_just_its_init(tmp_path):
    """`inspect.getsource` on a package returns `__init__.py` and nothing else.

    `M-CONFORM` has a corpus builder, a runner and a comparator, so it plausibly lands as a
    package — and a scan that read only the `__init__` would report clean while the second consent
    check sat in `runner.py`, which is exactly where it would be written. Review found that hole.

    A real package on disk rather than a mock, because the thing being asserted is what
    `__path__` traversal does, and a mock of it would assert the mock.
    """
    import sys

    package = tmp_path / "fake_conform_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("from .runner import run\n", encoding="utf-8")
    (package / "runner.py").write_text(
        "def run(cohort):\n"
        '    if cohort.consent_class == "real":\n'
        "        raise RuntimeError\n",
        encoding="utf-8",
    )

    sys.path.insert(0, str(tmp_path))
    try:
        import importlib

        module = importlib.import_module("fake_conform_pkg")
        source = module_sources(module)
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("fake_conform_pkg", None)
        sys.modules.pop("fake_conform_pkg.runner", None)

    assert "consent_class" in source, "module_sources missed the package's non-__init__ files"
    assert consent_reimplementation_sites(source), (
        "a consent check living in a package submodule is invisible to the scan, so a packaged "
        "M-CONFORM could re-implement the gate and CT-CONFORM-10's structural half would pass"
    )


def test_the_write_audit_attributes_a_write_to_the_module_that_made_it():
    """`TC-CONFORM-C12`'s oracle is *"a write-audit log with per-stack attribution"* — this is it.

    The clause's whole claim is about **whose** write a write is: `M-CONFORM` runs whole pipelines,
    so a great deal is written during its run and none of it is its own. Without attribution the
    audit records every write identically and the case has no oracle at all — which is what review
    found: `WriteAttempt` had no such field, so C12's two tests were unsatisfiable rather than
    merely red, and `getattr(w, "attributed_to", None)` turned the missing field into a silent
    wrong answer.

    Exercised here against simulated modules because no `aeh.*` module involved in a conformance
    run exists yet. A mechanism that arrived at #134 having never been run, reporting `None` for
    everything, would read as "M-CONFORM wrote nothing" — the passing answer, for the wrong reason.
    """
    import pathlib
    import tempfile

    pkg = simulated_implementation_module(
        "aeh.pkg",
        "def record(path):\n    path.write_text('validation record', encoding='utf-8')\n",
    )
    conform = simulated_implementation_module(
        "aeh.conform",
        "def through_pkg(path, pkg):\n    pkg.record(path)\n"
        "def direct(path):\n    path.write_text('report', encoding='utf-8')\n",
    )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        with recording_write_audit() as writes:
            conform.through_pkg(root / "record.json", pkg)
            conform.direct(root / "conformance-report.json")
            (root / "scaffolding.txt").write_text("the test's own", encoding="utf-8")

    by_target = {pathlib.Path(str(w.target)).name: w for w in writes}
    assert set(by_target) >= {"record.json", "conformance-report.json", "scaffolding.txt"}

    # Written **through** M-PKG: performed there, initiated here. This is the distinction the
    # clause turns on — "writes backend-scoped validation records through M-PKG".
    assert by_target["record.json"].attributed_to == "M-PKG"
    assert by_target["record.json"].initiated_by == "M-CONFORM"

    # Written with its own hands: M-CONFORM at both ends.
    assert by_target["conformance-report.json"].attributed_to == "M-CONFORM"
    assert by_target["conformance-report.json"].initiated_by == "M-CONFORM"

    # The test's own scaffolding has no implementation frame, so it is attributed to nothing —
    # which is what keeps a fixture file from reading as a module's write.
    assert by_target["scaffolding.txt"].attributed_to is None
    assert by_target["scaffolding.txt"].initiated_by is None
