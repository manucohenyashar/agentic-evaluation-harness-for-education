"""The vocabulary `M-STATS`'s clause suite is written against, transcribed from the design.

TS-73 (issue #121) implements twenty-one `CT-STATS` clause cases against a module that does not
exist: `M-STATS` is four stories away (#115 → #116/#117/#118) and every one of those is itself
blocked. A suite that sits red across a phase drifts, and what drifts first is its vocabulary —
the admissibility predicate, the field set of the figure, the three `NoValidationData` reasons,
the six MVVP steps.

So the vocabulary lives here as **literals transcribed from design §3.16**, and
`tests/contract/stats/test_ct_stats_vocabulary.py` asserts every one of them against the design
document itself. Those assertions are green today and they are worth being precise about: they
test that *this fixture still matches the design*, not that `M-STATS` does anything. Nobody
should count them as coverage of a clause. What they buy is drift detection — when §3.16 moves,
the suite goes red at the transcription rather than quietly encoding a contract nobody agreed to.

Design §3.16 **does** carry a Python Interfaces block, so unlike §3.19 most of what the cases
drive is transcribed rather than invented. The additions the clauses force but the block does not
declare are listed below, in one place, so an invented name is visibly invented:

    build_stats(labels=..., **kw) -> ValidationStats     the in-memory rung-0/1 constructor  (#115)
    open_stats(data_dir=..., cohort_id=...)              the rung-2 constructor              (#115)
    .admissible_labels()                                 the single filter (NFR-STATS-04)    (#115)
    STATS_SUBGROUP_ANALYSIS_ENABLED                      §3.16's knob, as a module constant  (#117)
    STATS_MIN_N_FOR_HEADLINE                             the other declared knob             (#118)
    latest_mvvp(...)                                     CT-STATS-08's current result        (#116)
    .aggregate(across=...)                               FR-STATS-13, and -04's refusal      (#118)
    .criterion_override_history(...)                     CT-STATS-09 — see the note below    (#118)
    .narrative_quality(...)                              FR-STATS-12                         (#118)
    .operational_signal(...)                             FR-STATS-14's weighted signal       (#118)
    .observability_counters() / .alerts()                CT-STATS-19                    (#118/#117)
    .analytical_export(...)                              NFR-STATS-03's read-only export     (#118)
    AgreementFigure.degenerate_band_shape                CT-STATS-21's disclosure            (#115)
    CompressionReport .gold/.panel (.band_entropy,
        .interior_rate), .panel_narrower,
        .stated_limitation                               CT-STATS-10 — "part of the return
                                                         value, not a footnote"              (#117)
    MVVPReport .steps[n] (.requirement, .outcome,
        .measured_at, .paired_results), .result_id,
        .measured_configuration, .contributing_results   CT-STATS-07/-08                     (#116)
    RoutingPolicyReport .verdict, .label_population      CT-STATS-11                         (#117)
    DriftReport .criteria_covered                        CT-STATS-12                         (#117)
    ValidationUpdate .<counter>, .message                CT-STATS-06, CT-STATS-05            (#118)

Consumer-side names, in the same spirit — each keyed on the story that delivers it:

    aeh.console  render_agreement_block (#123 scoped / #125 absence), render_preflight (#126)
    aeh.pkg      validation_for (#29), export_package (#31)
    aeh.agg      rank_criteria_for_escalation (#93), describe_agreement (#91)
    aeh.review   record_label (#110), rank_queue_items (#108)
    aeh.orch     run_pipeline_for_test (#61)

**`CT-STATS-09` is the one clause with no requirement behind it.** Every other clause in the table
cites an `FR-STATS-*`; `-09` (criterion override history, and its no-data-versus-zero discipline)
cites none, and no `FR-STATS-*` row mentions override history. So no story owns it — #115–#118
between them implement every FR and none of them implements this. The case is written anyway,
keyed on #118 because that is the story that owns label-derived record surfaces, and
`test_ct_stats_vocabulary.py` asserts the gap so it is reported rather than absorbed.

Every constant below carries the clause or requirement it came from, so the transcription is
checkable by reading rather than by trusting.
"""

from __future__ import annotations

import ast
import re
from typing import Iterable

# --- CT-STATS-01 / FR-STATS-01: which labels may enter a validity claim -------------------

#: The admissibility predicate, verbatim: *"labels with `label_type = 'blind'` **and**
#: `evaluation_mode = 'judged'`"*. Both conditions, which is why this is a mapping and not a
#: single string — `TC-STATS-C01` drops each one independently, since dropping either admits a
#: different contaminated population.
ADMISSIBLE_LABEL_PREDICATE: dict[str, str] = {
    "label_type": "blind",
    "evaluation_mode": "judged",
}

#: RISK-07's two named contamination routes, plus the two that violate one half of the predicate
#: alone. Each is a label the store can hold and the filter must exclude; the value is the field
#: that makes it inadmissible, so a test can say *which* condition did the excluding.
#:
#: `saw_system_output` is `M-REVIEW`'s column (`CT-REVIEW-08`) and is listed because a label may
#: carry `label_type = 'blind'` and still have been produced by a teacher who reached the system's
#: output — blind is a claim about reachability, not a naming convention.
INADMISSIBLE_LABEL_CLASSES: dict[str, dict[str, object]] = {
    "operational": {"label_type": "operational", "evaluation_mode": "judged"},
    "saw_system_output": {"label_type": "blind", "evaluation_mode": "judged",
                          "saw_system_output": True},
    "deterministic_mcq": {"label_type": "blind", "evaluation_mode": "deterministic"},
    "whole_grade_sample": {"label_type": "whole_grade", "evaluation_mode": "judged"},
}

#: `CT-DET-06` owns the column the deterministic exclusion reads, and `CT-REVIEW-08` owns
#: `saw_system_output`. Named here so the pairing in `TC-STATS-C01` step 4 is checkable.
FILTER_SOURCE_CLAUSES: tuple[str, ...] = ("CT-REVIEW-08", "CT-DET-06")


# --- CT-STATS-02 / NFR-STATS-02: the figure carries its own scope --------------------------

#: `AgreementFigure`'s fields, transcribed from §3.16's Interfaces block in declaration order.
AGREEMENT_FIGURE_FIELDS: tuple[str, ...] = (
    "kappa",
    "qwk",
    "ordinal_alpha",
    "n",
    "scoring_model",
    "population_scope_id",
    "backend_profile",
    "panel_build_ref",
)

#: The five the clause names as inseparable from the statistic: *"carries `n`, `scoring_model`,
#: `population_scope_id`, `backend_profile`, and `panel_build_ref` **in the same value**"*. No
#: figure is representable without them, which is what `TC-STATS-C02` asserts by construction
#: refusal rather than by inspecting a constructed value.
REQUIRED_FIGURE_FIELDS: tuple[str, ...] = (
    "n", "scoring_model", "population_scope_id", "backend_profile", "panel_build_ref",
)

#: The chance-corrected statistics `FR-STATS-02` names: *"Cohen's κ, QWK, or ordinal
#: Krippendorff's α"*. The Greek spellings are included because a console renders them — the
#: `M-CONSOLE` suite learned that the hard way, where a rule that did not know `κ` condemned the
#: HLD's own S12 mock-up.
CHANCE_CORRECTED_STATISTICS: frozenset[str] = frozenset(
    {"kappa", "κ", "cohen", "qwk", "quadratic weighted kappa",
     "ordinal_alpha", "alpha", "α", "krippendorff"}
)

#: The figure's four scope dimensions (`CT-STATS-04`: *"keyed by population scope, backend
#: profile, panel build ref, and scoring model"*).
SCOPE_KEY_DIMENSIONS: tuple[str, ...] = (
    "population_scope_id", "backend_profile", "panel_build_ref", "scoring_model",
)


# --- CT-STATS-03 / FR-STATS-04: absence is a type -----------------------------------------

#: `NoValidationData.reason`'s `Literal`, transcribed from the Interfaces block.
NO_VALIDATION_DATA_REASONS: tuple[str, ...] = (
    "no_blind_labels", "no_data_for_population", "no_data_for_backend",
)


# --- CT-STATS-04 / FR-STATS-03, FR-STATS-17: what may never be merged ----------------------

#: `criterion.scoring_model`'s values. `atomic` and `atomic_with_gate` are reported together and
#: `holistic` separately — the clause's *"reported **separately** and no function merges them"*.
SCORING_MODELS: tuple[str, ...] = ("atomic", "atomic_with_gate", "holistic")
SEPARATELY_REPORTED_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"atomic", "atomic_with_gate"}),
    frozenset({"holistic"}),
)

#: The three dimensions no aggregate may span (`CT-STATS-04`, `FR-STATS-17`, HLD `R51`). Swept
#: one at a time in `TC-STATS-C04`, because a merge refusal that covers two of three is the
#: realistic bug and a single combined assertion would report it as a pass.
NON_AGGREGABLE_DIMENSIONS: tuple[str, ...] = ("population", "backend", "assignment_type")


# --- CT-STATS-05 / FR-STATS-11: the administration that collected nothing -------------------

#: The first-class value's message, verbatim in `FR-STATS-11`, `FR-CONSOLE-24` and `CT-STATS-05`.
NO_NEW_VALIDATION_EVIDENCE = "no new validation evidence for this administration"

#: `FR-CONSOLE-26`'s sibling message, for a package never administered to the current population.
#: A different absence with a different cause, and the console must not substitute one for the
#: other — both are in the vocabulary so `TC-STATS-C05` can assert it rendered *this* one.
NO_VALIDATION_DATA_FOR_POPULATION = "no validation data for this population"


# --- CT-STATS-06 / FR-STATS-10, FR-STATS-14: the validation record --------------------------

#: The three counters `promote` increments **separately**. Merging any two lets operational volume
#: inflate apparent validation depth, which is why the case asserts three individually rather than
#: asserting the record "was updated".
PROMOTE_COUNTERS: tuple[str, ...] = ("cohorts_used", "operational_count", "blind_count")

#: The field an operational count may never reach (`FR-STATS-10`, HLD `R18`/`R20`).
AGREEMENT_FIELD_CLOSED_TO_OPERATIONAL = "agreement_kappa"

#: `FR-STATS-14`'s weighting, *for operational signals only*: *"an override is informative, an
#: acceptance is weak, a blind score is authoritative"*. Ordered strongest-last so a test can
#: assert the ordering rather than three magnitudes it would have to invent.
OPERATIONAL_EVIDENCE_ORDER: tuple[str, ...] = ("acceptance", "override", "blind")


# --- CT-STATS-07, -08 / FR-STATS-05, -15..-19: the MVVP -------------------------------------

#: The six MVVP steps and the requirement each is, transcribed from `FR-STATS-05`: *"FR-STATS-02
#: (step 1), FR-STATS-15 (step 2), FR-STATS-16 (step 3), FR-STATS-17 (step 4), FR-STATS-18
#: (step 5) and FR-STATS-06 (step 6)"*. The names are this suite's; the mapping is the design's.
MVVP_STEPS: dict[int, str] = {
    1: "FR-STATS-02",
    2: "FR-STATS-15",
    3: "FR-STATS-16",
    4: "FR-STATS-17",
    5: "FR-STATS-18",
    6: "FR-STATS-06",
}

#: The four dimensions that force a **full** re-run (`FR-STATS-19`, `CT-STATS-08`, HLD `R30`).
#: Swept one at a time: a partial trigger set is the realistic bug.
MVVP_RERUN_TRIGGERS: tuple[str, ...] = (
    "panel_member", "model_build", "quantization", "prompt_template_version",
)

#: `FR-STATS-18`'s threshold: *"Where a judge's measured self-agreement (FR-STATS-16) exceeds
#: 0.95, the module shall require the position-bias result from FR-STATS-15 to be present"*.
#: Strictly exceeds — a judge measured at exactly 0.95 is below the trigger.
SELF_AGREEMENT_PAIRING_THRESHOLD = 0.95


# --- CT-STATS-10 / FR-STATS-06: the compression check ---------------------------------------

#: The two statistics the check compares (`band_entropy`, `interior_rate`), named in both the FR
#: and the clause.
COMPRESSION_STATISTICS: tuple[str, ...] = ("band_entropy", "interior_rate")

#: The limitation the clause requires **in the return value**: *"it cannot detect panel and
#: teacher compressing together"*. Held as the phrase a report must carry, so
#: `TC-STATS-C10` asserts on content rather than on the presence of a field named `caveat`.
CO_COMPRESSION_LIMITATION = "cannot detect panel and teacher compressing together"


# --- CT-STATS-11 / FR-STATS-08: routing-policy validity -------------------------------------

#: The two populations compared, and the verdict vocabulary. The clause fixes the interpretation:
#: *"reports **similar rates in both as failing** rather than as uninformative"* — so `failing` is
#: a value the report must be able to carry, and `uninformative` is the one it must not use there.
ROUTING_POLICY_ARMS: tuple[str, ...] = ("escalated_and_reviewed", "auto_accepted")
ROUTING_POLICY_FAILING_VERDICT = "failing"
ROUTING_POLICY_FORBIDDEN_VERDICT_ON_SIMILAR_RATES = "uninformative"


# --- CT-STATS-12 / FR-STATS-09: the drift check ----------------------------------------------

#: *"a 20–30 submission sample"*, inclusive at both ends, and judged criteria only.
DRIFT_SAMPLE_RANGE: tuple[int, int] = (20, 30)


# --- CT-STATS-14 / FR-STATS-12: narrative quality --------------------------------------------

#: The three narrative-quality metrics, reported **separately** from criterion-score agreement.
NARRATIVE_QUALITY_METRICS: tuple[str, ...] = (
    "citation_validity_rate", "hallucinated_claim_rate", "teacher_rating",
)


# --- CT-STATS-15: the write scope --------------------------------------------------------------

#: What this module may write. `package_validation` only **through `M-PKG`** — the indirection is
#: the clause, not an implementation detail, so `TC-STATS-C15` asserts the write appears under
#: `M-PKG`'s frames rather than asserting no write happened at all.
PERMITTED_WRITE_TARGETS: tuple[str, ...] = ("package_validation", "tier_d_statistics")

#: What it may never write, on any path (`CT-STATS-15`). Table names as they appear in the design's
#: schema, since the static half scans for the write and not for a docstring.
FORBIDDEN_WRITE_TABLES: tuple[str, ...] = (
    "criterion_score", "grade", "narrative", "verdict", "criterion", "criterion_band",
    "package", "package_version", "exemplar", "grade_policy", "grade_boundary",
)


# --- CT-STATS-18 / NFR-STATS-05: the security boundary ------------------------------------------

#: The knob and its declared default, from §3.16's Configuration block. `False` is the contract:
#: *"subgroup analysis is gated on local lawfulness and is **off by default**"*.
SUBGROUP_ANALYSIS_KNOB = "STATS_SUBGROUP_ANALYSIS_ENABLED"
SUBGROUP_ANALYSIS_DEFAULT = False

#: The other declared knob. It is **not** a quality threshold — see `MIN_N_IS_NOT_A_VERDICT_THRESHOLD`
#: below and the finding in `test_ct_stats_vocabulary.py`.
MIN_N_FOR_HEADLINE_KNOB = "STATS_MIN_N_FOR_HEADLINE"
MIN_N_FOR_HEADLINE_DEFAULT = 30

#: `FR-STATS-07`'s surface features, the ones that *ought to be irrelevant* to a score.
SURFACE_FEATURES: tuple[str, ...] = (
    "response_length_tokens", "vocabulary_complexity", "ocr_quality_score",
    "handwriting_legibility_band", "formatting_regularity", "subgroup",
)


# --- CT-STATS-19: observability ----------------------------------------------------------------

#: The emitted names, from §3.16's Observability paragraph.
OBSERVABILITY_COUNTERS: tuple[str, ...] = (
    "label_count_by_type", "label_count_by_origin", "blind_coverage_per_administration",
    "statistics_recomputation_duration",
)

#: The two alerts the clause declares contract. Both must exist **and fire** — an alert that is
#: defined and never reachable is the same as no alert, and the second one is the only detector
#: for a criterion with an excellent κ and no validity.
CONTRACT_ALERTS: tuple[str, ...] = (
    "blind_sample_skipped_consecutive_administrations",
    "surface_proxy_flag_on_criterion",
)


# --- CT-STATS-20: the non-promise, and the threshold that is not one -----------------------------

#: Language that turns a scoped statistic into a system-wide accuracy claim. `CT-STATS-20` states
#: the violation condition unusually precisely — *"a consumer that renders a single headline
#: number has violated this contract even if every figure in it is correct"* — so the detector
#: looks for the framing, not for a number.
SYSTEM_WIDE_CLAIM_PHRASES: tuple[str, ...] = (
    "system accuracy", "overall accuracy", "system-wide accuracy", "accuracy of the system",
    "overall agreement", "system agreement", "headline accuracy", "overall score",
    "how accurate", "validated system", "system is validated",
)

#: The verdict vocabulary `CT-STATS-20` forbids on a quality figure. A declared threshold would
#: turn a scoped statistic into a pass/fail claim about the system (`NFR-SYS-08`: *"No single
#: threshold is declared here"*).
FORBIDDEN_VERDICT_FIELDS: tuple[str, ...] = (
    "validated", "passes", "passed", "meets_threshold", "is_accurate", "quality_gate",
    "acceptable", "sufficient_quality", "accuracy_threshold", "kappa_threshold",
    "minimum_agreement",
)

#: `STATS_MIN_N_FOR_HEADLINE` is a **display qualifier boundary**, not a quality verdict: below it
#: *"the figure renders with an explicit 'too few to draw conclusions from' qualifier"* (§3.16
#: Configuration, and HLD §11.5's S12 mock does exactly that at n=15). It says nothing about
#: whether a figure is good. Named here because the literal reading of `CT-STATS-20` — *"no
#: threshold is declared here"* — would condemn it, and a case written that way goes red against a
#: compliant module. See `test_the_literal_no_threshold_reading_collides_with_the_design`.
MIN_N_IS_NOT_A_VERDICT_THRESHOLD = True

#: The qualifier the design requires below `STATS_MIN_N_FOR_HEADLINE`.
TOO_FEW_QUALIFIER = "too few to draw conclusions from"


# --- CT-STATS-21: the degeneracy ------------------------------------------------------------------

#: The band count at which ordinal α and κ degenerate (§4.6 item 1: two-band is the **default**
#: band shape, which is what makes this a live problem rather than an edge case).
DEGENERATE_BAND_COUNT = 2

#: Language that would present binary-criterion agreement as equivalent to multi-band agreement.
#: The clause forbids the equivalence, not the number: the module *returns* the figure, and that
#: is the promised behaviour.
EQUIVALENCE_PHRASES: tuple[str, ...] = (
    "same as", "equivalent to", "comparable to", "directly comparable",
    "as reliable as", "on the same scale",
)

#: What a compliant disclosure looks like — the degeneracy named, not merely a footnote elsewhere.
DEGENERACY_DISCLOSURE_TERMS: tuple[str, ...] = (
    "two-band", "two band", "binary", "degenerate", "degeneracy",
)


# --- the module's declared surface --------------------------------------------------------------

#: `ValidationStats`' members, from §3.16's Interfaces block, in declaration order.
PROTOCOL_MEMBERS: tuple[str, ...] = (
    "agreement", "compression_check", "surface_proxies", "routing_policy_validity",
    "drift_check", "run_mvvp", "promote",
)

#: Which story delivers each member, so a parametrized sweep over the surface can key each row on
#: the blocker that makes *that row* runnable. `require()` reports whichever blocker resolves
#: first, and a sweep keyed entirely on #115 would report six rows as runnable the moment the
#: filter lands, five of them against functions that do not exist yet.
MEMBER_ISSUE: dict[str, str] = {
    "agreement": "#115",
    "run_mvvp": "#116",
    "compression_check": "#117",
    "surface_proxies": "#117",
    "routing_policy_validity": "#117",
    "drift_check": "#117",
    "promote": "#118",
}

#: The arguments each member takes, transcribed from §3.16's Interfaces block signatures. Values
#: are this suite's; the parameter **names** are the design's, and `test_ct_stats_vocabulary.py`
#: asserts them against the block so a renamed parameter fails here rather than deep inside a
#: sweep.
EMPTY_DATA_CALL: dict[str, dict[str, object]] = {
    "agreement": {
        "package_version": "pkg-v1",
        "criterion_id": "C-01",
        "scope": "y9-2026-spring",
        "backend_profile": "edge-local-q4",
        "panel_build_ref": "9f2a1c",
        "scoring_model": "atomic",
    },
    "compression_check": {"cohort_id": "coh-1", "criterion_id": "C-01"},
    "surface_proxies": {"cohort_id": "coh-1", "criterion_id": "C-01"},
    "routing_policy_validity": {"cohort_id": "coh-1"},
    "drift_check": {"package_version": "pkg-v1", "sample": ()},
    "run_mvvp": {"assignment_type": "extended_response"},
    "promote": {"cohort_id": "coh-1"},
}

#: The members that report a **figure**, and therefore the ones whose no-data outcome is
#: `NoValidationData`.
#:
#: `promote` is deliberately not among them. Its no-data outcome is `CT-STATS-05`'s *"no new
#: validation evidence for this administration"* — a first-class value of a different kind, and
#: one that also carries the non-advancement guarantee — so sweeping it here would assert a return
#: type the contract does not promise and would contradict `TC-STATS-C05` two files away. It is
#: still swept in `TC-STATS-C16`, which asserts the weaker and universal claim: no entry point
#: raises because there is too little data.
FIGURE_MEMBERS: tuple[str, ...] = tuple(m for m in PROTOCOL_MEMBERS if m != "promote")


# ==================================================================================================
# Rules
#
# Each rule below is a detector the cases apply to a source file, a rendering, or a name set. Every
# one has a control in **both directions** in `test_ct_stats_vocabulary.py`: copy a correct
# implementation produces, and copy the clause forbids. A rule that fails correct copy is a rule
# the first person to hit it switches off.
# ==================================================================================================


def _function_nodes(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every function in `tree`, nested ones included.

    Takes a parsed tree rather than source text on purpose. An earlier draft took the text and
    called `ast.parse` per query — so `id()` comparisons between "nodes inside a function" and
    "nodes in the module" were comparing two *different* trees, every identity check was false,
    and the module-level scan counted every literal in the file. It reported a second definition
    site in compliant source, which is the exact failure mode these rules exist to avoid.
    """
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _string_constants(node: ast.AST) -> set[str]:
    """String literals inside `node`, excluding its docstring.

    Docstrings are excluded deliberately: a module that *documents* the predicate in prose — which
    a compliant one does, since `NFR-STATS-04` is about a single definition and not about silence
    — would otherwise be counted as defining it a second time.
    """
    doc_ids = set()
    for child in ast.walk(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = getattr(child, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    doc_ids.add(id(body[0].value))
    return {
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant)
        and isinstance(child.value, str)
        and id(child) not in doc_ids
    }


def admissibility_definition_sites(source: str) -> list[str]:
    """Function names in `source` that **define** the admissibility predicate.

    `NFR-STATS-04`: *"The 'labels admissible to a validity claim' filter shall exist once in the
    source and be reused, so R20 and R53 cannot be violated by a new caller."* `CT-STATS-01` makes
    the single-source property the thing under test, so the oracle is a **cardinality of one**.

    Counting *definitions*, not mentions. A compliant module defines the predicate once and calls
    it from four places; a scan that counted every occurrence of `'blind'` would report five and
    fail correct source — and the reflex fix for that is to stop scanning, which is worse than
    never having scanned. A site is a function whose body carries **both** halves of the predicate
    as literals: the clause is the conjunction, and a function that mentions only `'blind'` is
    reading a column, not deciding admissibility.

    Module-level definitions count too, under the name `<module>`: a compliant implementation may
    express the filter as a module constant (a `Statement`, a frozen predicate) rather than a
    function, and a scan that saw only functions would report a cardinality of zero and pass an
    implementation with no filter at all.
    """
    tree = ast.parse(source)
    values = set(ADMISSIBLE_LABEL_PREDICATE.values())
    sites: list[str] = []

    for node in _function_nodes(tree):
        if values <= _string_constants(node):
            sites.append(node.name)

    # Module level: everything that is not inside a function.
    function_spans = {
        id(child)
        for node in _function_nodes(tree)
        for child in ast.walk(node)
    }
    module_strings = {
        child.value
        for child in ast.walk(tree)
        if isinstance(child, ast.Constant)
        and isinstance(child.value, str)
        and id(child) not in function_spans
    }
    if values <= module_strings:
        sites.append("<module>")

    return sites


#: Names that mean a callable computes an agreement statistic. Used by the two rules below.
_AGREEMENT_TERMS: tuple[str, ...] = (
    "agreement", "kappa", "qwk", "alpha", "krippendorff", "concordance",
)

#: The population qualifiers that make an agreement function a second filter. `CT-STATS-01`'s
#: adversarial construction is `compute_agreement_all_labels()` — "clearly labelled as an
#: operational figure" — and its label is exactly what the name rule reads.
_OTHER_POPULATION_TERMS: tuple[str, ...] = (
    "all_labels", "all_label", "any_label", "every_label", "unfiltered", "raw_labels",
    "operational", "unblind", "non_blind", "including_operational", "regardless_of_type",
)


def surface_admitting_other_populations(names: Iterable[str]) -> list[str]:
    """Public names that compute agreement over a population other than the admissible one.

    `CT-STATS-01`: *"There is no function in this module that computes agreement over any other
    label population, and none will be added."* The clause's own justification for the second half
    is that the added function is correct in isolation and honestly labelled — so the name is the
    evidence, and the rule reads it.

    Both terms required. `operational_count` is `CT-STATS-06`'s counter and names a population
    without computing agreement over it; `agreement` alone is the module's whole subject. Only the
    conjunction is a violation, which is also why this rule needs no rescue list — the narrower
    the conjunction, the less there is to rescue.
    """
    flagged = []
    for name in names:
        if name.startswith("_"):
            continue
        lowered = name.lower()
        if any(term in lowered for term in _AGREEMENT_TERMS) and any(
            term in lowered for term in _OTHER_POPULATION_TERMS
        ):
            flagged.append(name)
    return flagged


def agreement_functions_bypassing_the_filter(
    source: str, filter_names: Iterable[str]
) -> list[str]:
    """Functions that produce an agreement figure without routing through the single filter.

    The structural half of `CT-STATS-01` step 2, and the half a name rule cannot reach: a function
    named innocuously that reads the label table directly is the same violation as
    `compute_agreement_all_labels`, minus the honest label.

    A function *produces* a figure if it constructs `AgreementFigure` or calls a statistic helper.
    It *routes through the filter* if it calls one of `filter_names`, or takes a parameter whose
    name says its argument is already filtered — a compliant module that pushes the filter to its
    caller and states so in the signature is not violating the clause, and a rule that insisted on
    the call would fail it.
    """
    filter_names = set(filter_names)
    flagged: list[str] = []

    for node in _function_nodes(ast.parse(source)):
        called = {
            child.func.id if isinstance(child.func, ast.Name) else
            child.func.attr if isinstance(child.func, ast.Attribute) else ""
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
        }
        produces = "AgreementFigure" in called or any(
            any(term in name.lower() for term in ("kappa", "qwk", "krippendorff"))
            for name in called
        )
        if not produces:
            continue
        if called & filter_names:
            continue
        params = [arg.arg for arg in node.args.args + node.args.kwonlyargs]
        if any("admissible" in p or "blind" in p for p in params):
            continue
        flagged.append(node.name)

    return flagged


def merging_surface(names: Iterable[str]) -> list[str]:
    """Public names that offer a figure spanning something the contract keeps apart.

    Two prohibitions read by one rule, because they are the same shape: `CT-STATS-04` forbids a
    function merging `atomic`/`atomic_with_gate` with `holistic` or aggregating across population,
    backend or assignment type; `CT-STATS-14` forbids a function combining narrative quality with
    criterion-score agreement. In every case the violation is a **name offering the combination**,
    which is what a consumer would reach for.
    """
    combining = ("combined", "merged", "blended", "overall", "unified", "aggregate_all", "total")
    kept_apart = (
        "atomic", "holistic", "narrative", "population", "backend", "assignment_type",
        "quality", "agreement",
    )
    flagged = []
    for name in names:
        if name.startswith("_"):
            continue
        lowered = name.lower()
        if any(term in lowered for term in combining) and any(
            term in lowered for term in kept_apart
        ):
            flagged.append(name)
    return flagged


#: A number that could be a figure: a percentage, or a decimal between 0 and 1.
_NUMBER = re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%|\b[01]\.\d{2,}\b")

#: Tokens that make a nearby number scoped. `CT-STATS-02` puts the scope in the value; a rendering
#: satisfies `CT-STATS-20` when the scope travels with the number on screen too.
_SCOPE_TOKENS: tuple[str, ...] = (
    "population", "cohort", "backend", "panel", "build", "model", "criterion",
    "n =", "n=", "n &", "sample", "scope",
)


def unscoped_headline_figures(rendering: str) -> list[str]:
    """Statements in `rendering` that present a figure as a claim about the system.

    `CT-STATS-20`'s violation condition: *"a consumer that renders a single headline number has
    violated this contract even if every figure in it is correct."* Two ways to violate it and the
    rule reads both — a system-wide framing (`"overall accuracy: 87%"`), or a number with no scope
    anywhere near it.

    Scanned per line rather than per document. A dashboard that renders one scoped figure per row
    is compliant; concatenating the whole page and asking whether the word "population" appears
    somewhere in it would pass a headline sitting above forty scoped rows, which is precisely the
    screen the clause describes.
    """
    problems: list[str] = []
    for raw in rendering.splitlines():
        line = raw.strip()
        if not line:
            continue
        lowered = line.lower()
        for phrase in SYSTEM_WIDE_CLAIM_PHRASES:
            if phrase in lowered:
                problems.append(f"{line!r} frames a figure as {phrase!r}")
                break
        else:
            if _NUMBER.search(line) and not any(token in lowered for token in _SCOPE_TOKENS):
                problems.append(f"{line!r} carries a figure with no scope beside it")
    return problems


def presents_binary_agreement_as_equivalent(rendering: str) -> list[str]:
    """Places where a two-band figure is offered as equivalent to a multi-band one.

    `CT-STATS-21`: the module *returns* the number — that is the promised behaviour — and the
    consumers *"must not present binary-criterion agreement as equivalent to multi-band
    agreement"*. So the rule reads the equivalence, not the figure, and a rendering that shows the
    number beside a disclosure is compliant.
    """
    problems: list[str] = []
    for raw in rendering.splitlines():
        line = raw.strip()
        lowered = line.lower()
        if not any(term in lowered for term in DEGENERACY_DISCLOSURE_TERMS):
            continue
        for phrase in EQUIVALENCE_PHRASES:
            if phrase in lowered:
                problems.append(f"{line!r} presents a two-band figure as {phrase!r} multi-band")
                break
    return problems


def numeric_coercions(value: object) -> list[str]:
    """Which numeric coercions `value` permits.

    `CT-STATS-03` step 2: `float()`, arithmetic, comparison against a threshold and
    format-as-percentage must **each** raise. The adversarial construction is a `float` subclass
    valued `0.0` — every call site keeps working and a package with no evidence advertises 0.00 —
    so this returns the list of coercions that *succeeded*, and a compliant `NoValidationData`
    yields an empty list.
    """
    permitted: list[str] = []
    probes = (
        ("float", lambda v: float(v)),  # noqa: PLW0108 - the lambda is the probe
        ("arithmetic", lambda v: v + 1),
        ("comparison", lambda v: v > 0.5),
        ("format_percent", lambda v: format(v, ".2%")),
        ("multiplication", lambda v: v * 100),
    )
    for name, probe in probes:
        try:
            probe(value)
        except Exception:  # noqa: BLE001 - any raise is the required outcome
            continue
        permitted.append(name)
    return permitted


def forbidden_write_statements(source: str) -> list[str]:
    """String literals in `source` that write a table `CT-STATS-15` closes to this module.

    The static half: *"Writes no score, no grade, no narrative, no package content, asserted
    statically so it covers unexercised paths."* A behavioural write audit sees only the paths a
    test drove; this sees the ones it did not.

    Reads are permitted and explicitly so — the clause grants *"reads labels, grades, and
    metrics"* — so the rule matches only the write verbs. A `SELECT ... FROM grade` is compliant
    and a rule that flagged it would flag the module's whole reason for existing.
    """
    write_verbs = ("insert into", "update ", "delete from", "replace into", "upsert into")
    problems: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        lowered = " ".join(node.value.lower().split())
        for verb in write_verbs:
            if verb not in lowered:
                continue
            after = lowered.split(verb, 1)[1].strip()
            target = after.split()[0].strip("(`\"'[]") if after else ""
            if target in FORBIDDEN_WRITE_TABLES:
                problems.append(f"{verb.strip()} {target}")
    return problems
