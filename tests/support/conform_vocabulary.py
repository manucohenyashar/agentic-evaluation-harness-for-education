"""The vocabulary `M-CONFORM`'s clause suite is written against, transcribed from the design.

TS-75 (issue #136) implements fourteen `CT-CONFORM` clause cases against a module whose two
implementing stories (#133, #134) have not started. The same drift problem TS-74 named applies
here and is worse in one respect: `M-CONFORM`'s consumer is **a process** — CI and release gating
— not another module. Nothing misbehaves when this contract erodes; a release simply ships on
evidence that was never gathered (test plan §6.11.18).

So the vocabulary lives here as **literals transcribed from the design**, and
`tests/contract/conform/test_ct_conform_vocabulary.py` asserts them. Those assertions are green
today and they are worth being precise about: they test that *this fixture still matches the
design*, not that `M-CONFORM` does anything. Nobody should count them as coverage of a clause.

Two of the module's surfaces are already real, which is why part of this suite is genuinely green
rather than merely transcribed:

* **Test plan §4.7's suite table is the repo's CI configuration.** `CT-CONFORM-08` says the two
  tiers are contract, and §4.7 is where the wiring is written down — one row per suite, with its
  command and its trigger. `TC-CONFORM-C08`'s configuration half is assertable against it today.
* **§7.4 and design §4.6 item 2 carry `CT-CONFORM-14`'s hole.** The case's own instruction is that
  it *"should be deleted the day the statistic is declared"*, so the assertion is a three-way
  drift detector across the clause, the open-question item and the §7.4 row.

Every constant below carries the clause or requirement it came from, so the transcription is
checkable by reading rather than by trusting.
"""

from __future__ import annotations

import re
from typing import Any

# --- the module's two surfaces ---------------------------------------------------------------
#
# Settled here rather than per-test, because the two are genuinely different things and a suite
# that blurs them cannot key its blockers.
#
#   `aeh.conform`     the module: `ConformanceSuite`, the fixture set, `DivergenceReport`, the
#                     gate classification. Design §3.18's Interfaces block.
#   `harness.conform` the **entry point**, which test plan §4.7 declares by name:
#                     `python -m harness.conform --fixture-set <v> --backends <a,b>`.
#
# Neither #133 nor #134 names a path, so both names are this suite's choice — flagged in the PR.
# A case drives whichever surface its Oracle names: `TC-CONFORM-C03` (stage execution per
# backend), `-C08` (fast-tier completion) and `-C11` (measured duration) run the entry point;
# `-C04`, `-C06`, `-C13` assert over the module's own data types.
HARNESS_CONFORM_MODULE = "harness.conform"

#: `CT-CONFORM-01` / `FR-CONFORM-01`: *"30–50 submissions spanning the score range"*. Both bounds
#: are inclusive in the requirement's wording and are asserted as such.
CORPUS_MIN = 30
CORPUS_MAX = 50

#: `CT-CONFORM-04` / `FR-CONFORM-04`, the five dimensions verbatim: *"per-criterion score
#: distributions, chance-corrected agreement with the fixture labels, confidence and escalation
#: rate, evidence-integrity failure rate, and self-agreement over repeated runs."*
#:
#: Field names rather than prose, since the case's oracle is **set equality** over
#: `DivergenceReport`'s surface. The mapping from clause phrase to field name is this suite's,
#: and `test_ct_conform_vocabulary.py` asserts each phrase still appears in the clause text so a
#: reworded dimension goes red here rather than silently renaming a field.
SCORE_DISTRIBUTION_DIMENSION = "per_criterion_score_distribution"
AGREEMENT_DIMENSION = "chance_corrected_agreement"
CONFIDENCE_DIMENSION = "confidence_and_escalation_rate"
EVIDENCE_INTEGRITY_DIMENSION = "evidence_integrity_failure_rate"
SELF_AGREEMENT_DIMENSION = "self_agreement_over_repeated_runs"

DIVERGENCE_DIMENSIONS: frozenset[str] = frozenset(
    {
        SCORE_DISTRIBUTION_DIMENSION,
        AGREEMENT_DIMENSION,
        CONFIDENCE_DIMENSION,
        EVIDENCE_INTEGRITY_DIMENSION,
        SELF_AGREEMENT_DIMENSION,
    }
)

#: The clause phrase each dimension came from, so the transcription above is checkable against the
#: design text without a human reading both. Lower-cased fragments, matched as substrings of the
#: `CT-CONFORM-04` row.
DIMENSION_CLAUSE_PHRASES: dict[str, str] = {
    SCORE_DISTRIBUTION_DIMENSION: "per-criterion score distributions",
    AGREEMENT_DIMENSION: "chance-corrected agreement with the fixture labels",
    CONFIDENCE_DIMENSION: "confidence and escalation rate",
    EVIDENCE_INTEGRITY_DIMENSION: "evidence-integrity failure rate",
    SELF_AGREEMENT_DIMENSION: "self-agreement over repeated runs",
}

# --- CT-CONFORM-05's partition ------------------------------------------------------------------
#
# *"Divergence is a **finding, not a failure**, except where it crosses a declared gate: a
# materially different score distribution blocks sharing a validation record across backends, and
# an evidence-integrity failure-rate divergence is a §7.4 gate failure, not a metrics note."*
#
# Three parts, and the partition must be **exhaustive over the five** rather than enumerated: a
# classification that covers four dimensions and drops one is `CT-CONFORM-04`'s failure mode
# wearing `CT-CONFORM-05`'s name. `test_ct_conform_vocabulary.py` asserts the union is exactly
# `DIVERGENCE_DIMENSIONS` and that the three parts are pairwise disjoint.

#: The gate that `CT-CONFORM-14` says is **not computable as written** — no declared statistic,
#: no threshold (design §4.6 item 2, `TBD`).
UNAVAILABLE_GATE_DIMENSION = SCORE_DISTRIBUTION_DIMENSION

#: The gate that *is* computable and *is* live. §7.4's own words: *"the evidence-integrity-rate
#: half **is** computable and is gated"*.
LIVE_GATE_DIMENSION = EVIDENCE_INTEGRITY_DIMENSION

GATE_DIMENSIONS: frozenset[str] = frozenset({UNAVAILABLE_GATE_DIMENSION, LIVE_GATE_DIMENSION})

#: Everything else is a **finding**. Informational is the default and the gates are the exception,
#: which is the direction the clause states — an implementation that gated a third dimension would
#: block a release on a metrics note.
INFORMATIONAL_DIMENSIONS: frozenset[str] = DIVERGENCE_DIMENSIONS - GATE_DIMENSIONS

#: The three classification outcomes a `DivergenceReport` may carry per dimension.
CLASSIFICATION_BLOCKING = "blocking"
CLASSIFICATION_INFORMATIONAL = "informational"
CLASSIFICATION_UNAVAILABLE = "unavailable"

#: The classification each of the five must carry, given `CT-CONFORM-05` **read together with**
#: `CT-CONFORM-14`. Without `-14` the score-distribution row would read `blocking`; with it, the
#: gate cannot fire and the honest value is `unavailable`. A report that marked it `blocking`
#: while having no statistic would be claiming a gate it cannot compute, and one that marked it
#: `informational` would have silently demoted a declared gate — both are the failure `-14` names.
EXPECTED_CLASSIFICATION: dict[str, str] = {
    SCORE_DISTRIBUTION_DIMENSION: CLASSIFICATION_UNAVAILABLE,
    EVIDENCE_INTEGRITY_DIMENSION: CLASSIFICATION_BLOCKING,
    AGREEMENT_DIMENSION: CLASSIFICATION_INFORMATIONAL,
    CONFIDENCE_DIMENSION: CLASSIFICATION_INFORMATIONAL,
    SELF_AGREEMENT_DIMENSION: CLASSIFICATION_INFORMATIONAL,
}

# --- CT-CONFORM-04's prohibition ----------------------------------------------------------------
#
# *"Each is reported separately; there is no single conformance score."*
#
# **The forbidden vocabulary overlaps the required vocabulary by construction.** One of the five
# required dimensions is a *score* distribution, so a substring net on `score` fails a correct
# report — the same shape as TS-74's sweep that rejected the disclaimer its own clause required.
#
# Two lists rather than one, because the two halves need different strictness:
#
#   `FORBIDDEN_COMBINED_FIGURE_NAMES`  matched as a **whole name**. `score` alone is a headline;
#                                      `reference_scores` and `scores_by_criterion` are not, and a
#                                      report that carries per-fixture reference scores is doing
#                                      exactly what CT-CONFORM-01 requires of it.
#   `HEADLINE_TOKENS`                  matched as an identifier **token**, so `overall_status` and
#                                      `conformance_verdict` are caught wherever they appear.
#                                      Deliberately tiny: every token here condemns a whole family
#                                      of names, and a net that fails correct code is a net
#                                      somebody switches off (the TS-57 lesson, from the other
#                                      side).
FORBIDDEN_COMBINED_FIGURE_NAMES: frozenset[str] = frozenset(
    {
        "conformance_score",
        "overall_score",
        "overall",
        "score",
        "total_score",
        "combined_score",
        "summary_score",
        "passed",
        "pass_fail",
        "ok",
        "verdict",
        "grade",
        "equivalent",
        "equivalence",
        "backends_equivalent",
    }
)

HEADLINE_TOKENS: frozenset[str] = frozenset({"overall", "verdict", "equivalence", "equivalent"})


def combined_figure_names(surface_names: Any) -> list[str]:
    """The names on a report surface that read as a single combined conformance figure.

    The five declared dimensions are exempt by name, not by pattern: `SCORE_DISTRIBUTION_DIMENSION`
    contains the token `score` and is *required*, so a net that did not exempt it would fail every
    correct implementation.

    Names a correct report legitimately carries — `scoring_model` (a `CT-STATS-04` scope key),
    `reference_scores`, `pass_rate`, `grade_policy` — must survive. They do, because `score`,
    `passed`, `ok` and `grade` are matched only as complete names, never as tokens inside one.
    """
    hits = []
    for name in surface_names:
        if name in DIVERGENCE_DIMENSIONS:
            continue
        lowered = str(name).lower()
        tokens = set(re.split(r"[^a-z0-9]+", lowered)) - {""}
        if lowered in FORBIDDEN_COMBINED_FIGURE_NAMES or (tokens & HEADLINE_TOKENS):
            hits.append(name)
    return hits


# --- CT-CONFORM-02, the corpus medium -----------------------------------------------------------
#
# *"The corpus includes **real scanned handwriting spanning legible to marginal** and a
# mixed-format paper (FR-CONFORM-03, R37). Transcription and mark-reading are exercised on the
# real medium, never assumed — a clean-typed-text corpus would make every downstream result a
# measurement of the wrong thing."*

#: The two ends of the legibility span the clause names. Asserted as a span, not as membership:
#: a corpus carrying only `legible` scans satisfies "includes real scanned handwriting" and is
#: exactly the corpus the clause warns about.
LEGIBILITY_SPAN: tuple[str, str] = ("legible", "marginal")

#: The media kinds `FR-CONFORM-03` requires the corpus to contain.
REQUIRED_MEDIA_KINDS: frozenset[str] = frozenset({"scanned_handwriting", "mixed_format"})

#: The stage a fixture must traverse for transcription and mark-reading to be *exercised* rather
#: than assumed (HLD `R37`). A corpus whose fixtures arrive as text has skipped it.
VLM_STAGE = "transcribe"

#: The stage name a text shortcut would take instead — asserted absent, since "the fixtures went
#: through *a* pipeline" is satisfied by a pipeline that read the text straight off the page.
TEXT_SHORTCUT_STAGE = "text_passthrough"

# --- CT-CONFORM-03, the full pipeline ------------------------------------------------------------
#
# *"The **identical** fixture set runs through the **full** pipeline on each backend, with **no
# stubs for ingestion**."* The stage list is this suite's, drawn from the pipeline the design
# assembles in §4.1; what the clause makes contract is that **ingestion is among them** and that
# every stage ran for every fixture on both backends.
PIPELINE_STAGES: tuple[str, ...] = (
    "ingest",
    "transcribe",
    "extract",
    "judge",
    "integrity",
    "aggregate",
    "grade",
)

#: The stage the clause singles out. A conformance run that stubbed it *"would compare the two
#: backends on the one stage where they differ most"*.
UNSTUBBABLE_STAGE = "ingest"

# --- CT-CONFORM-09, the adversarial tier ---------------------------------------------------------
#
# `FR-CONFORM-09` verbatim: *"band-forcing directives, forged citations, contract-breaking
# instructions"* and *"embedded JavaScript, launch/open actions, embedded files, decompression
# bombs"*.
INJECTION_PAYLOAD_KINDS: frozenset[str] = frozenset(
    {"band_forcing", "forged_citation", "contract_breaking"}
)
MALICIOUS_PDF_KINDS: frozenset[str] = frozenset(
    {"embedded_javascript", "launch_action", "embedded_file", "decompression_bomb"}
)

#: The three properties the clause asserts across a twin pair, and the relation each must satisfy.
#: `same_band` and `same_citation_outcome` are equalities; confidence is an **inequality** — *"no
#: higher confidence than its twin"* — and writing it as an equality would fail a correct
#: implementation that (rightly) became *less* confident on an adversarial submission.
TWIN_PROPERTIES: tuple[str, ...] = ("band", "citation_verification_outcome", "confidence")

#: `CT-INGEST-13`/`-18`: a malicious PDF quarantines at the first validation gate.
QUARANTINE_GATE = "V0"

# --- CT-CONFORM-10, consent ------------------------------------------------------------------------
#
# ADR-5's column is `synthetic | consented | real`, and `FR-CONF-08` is the gate. `aeh.conf`
# already declares `CONSENTED_CLASSES`; the tests assert against **that**, not against the copy
# below, so the two cannot drift — the copy exists to make the sweep's *refused* half explicit.
CONSENT_CLASSES_ALLOWED: frozenset[str] = frozenset({"synthetic", "consented"})

#: The classes the suite must **refuse** to run against. `real` is the declared third value;
#: `None` and `""` are "not so flagged" — a cohort whose consent was never recorded. `CohortRef`
#: refuses an unrecognized string at construction, which is itself part of the refusal surface.
CONSENT_CLASSES_REFUSED: tuple[Any, ...] = ("real", None, "", "unknown")

# --- CT-CONFORM-11, the bound -----------------------------------------------------------------------
#
# `NFR-CONFORM-02`: *"well under an hour per backend"*. Test plan §4.7 turns the prose into the
# checkable number — the conformance row's duration budget is `< 60 min per backend`.
#
# **"Well under" has no declared factor.** The bound asserted is the declared one (3600 s); the
# "well" is reported as prose the design never quantified, rather than invented here as, say, 0.5.
CONFORMANCE_BUDGET_SECONDS = 3600

# --- CT-CONFORM-13, observability ---------------------------------------------------------------------
#
# Design §3.18 Observability: *"Per run: per-dimension divergence, fixture set version, both
# backends' resolved builds."*
#
# `resolved_builds` is the one the clause singles out: *"Assert **resolved**, not requested"*. Both
# names are transcribed so the case can assert the report carries the resolved builds and that a
# report naming only the requested ones is caught — which is the shape a silent substitution
# (`CT-CONFORM-07`) would leave behind.
RESOLVED_BUILDS_FIELD = "resolved_builds"
REQUESTED_BUILDS_FIELD = "requested_builds"

OBSERVABILITY_FIELDS: frozenset[str] = frozenset(
    {"per_dimension_divergence", "fixture_set_version", RESOLVED_BUILDS_FIELD}
)

# --- design §3.18's Interfaces block ---------------------------------------------------------------
#
#     class ConformanceSuite(Protocol):
#         def run(self, fixture_set_v: str, backends: Sequence[RunConfig]) -> ConformanceReport: ...
#         def compare(self, a: BackendResult, b: BackendResult) -> DivergenceReport: ...
#
# Two members, and that is the whole declared surface. Everything else these tests call is
# **invented** — see the module docstring of `test_ct_conform_corpus.py`.
PROTOCOL_MEMBERS: tuple[str, ...] = ("run", "compare")

# --- CT-CONFORM-14, the consumer claim sweep ------------------------------------------------------
#
# *"A consumer must not report backend equivalence on the strength of a gate that cannot fire."*
#
# The sweep looks for an **affirmative** equivalence claim. TS-74's lesson applies directly and
# was expensive there: the clause's own disclaimer — the sentence a correct console must print —
# contains the very words the naive net forbids, so a scanner without a negation filter fails the
# copy the clause requires and gets switched off by whoever hits it first.
EQUIVALENCE_CLAIM_TERMS: tuple[str, ...] = (
    "backends are equivalent",
    "backend equivalence",
    "equivalent backends",
    "backends agree",
    "no material difference",
    "materially equivalent",
    "conformance passed",
    "backends conform",
)

#: Fragments that make a sentence a *denial* of the claim rather than the claim. Deliberately
#: generous: a false negative here weakens one sweep, a false positive fails correct copy.
_NEGATIONS: tuple[str, ...] = (
    "not ",
    "no ",
    "never",
    "cannot",
    "can not",
    "unavailable",
    "undeclared",
    "not computable",
    "does not",
    "must not",
    "without",
    "unable",
    "tbd",
)


def affirmative_sentences(text: str) -> list[str]:
    """Split `text` into sentences and drop the ones carrying a negation.

    The same helper shape as `calib_vocabulary.affirmative_sentences`, with its own negation list
    — this sweep's disclaimers are about computability (*"cannot fire"*, *"not computable"*)
    rather than about accuracy. Duplicated rather than shared on purpose: a shared list tuned for
    one clause suite quietly changes what the other one forbids.
    """
    sentences = [part.strip() for part in re.split(r"[.!?\n]+", text) if part.strip()]
    return [s for s in sentences if not any(n in s.lower() for n in _NEGATIONS)]


def equivalence_claims(text: str) -> list[str]:
    """The sentences in `text` that affirmatively claim the two backends are equivalent."""
    return [
        sentence
        for sentence in affirmative_sentences(text)
        if any(term in sentence.lower() for term in EQUIVALENCE_CLAIM_TERMS)
    ]


# --- a model-call counter -----------------------------------------------------------------------


class CountingProvider:
    """Wraps an `InferenceProvider` and counts the calls that reach it.

    **The socket guard cannot express `CT-CONFORM-09`'s exact zero.** The fast tier's provider is
    `RecordedFixtureProvider`, which answers from disk — so a malicious PDF that was cheerfully
    dispatched to a model makes *no socket call at all*, and `network_guard.assert_no_network()`
    passes while the thing the clause forbids has happened. The guard would be watching the wrong
    boundary, the same way `open_audit` watched `builtins.open` and missed `os.open` in TS-58.

    So the assertion is a count at the provider seam: `calls == 0`, exactly, for every malicious
    PDF. Both guards run — the socket guard because a fast-tier test reaching the network is
    `CT-PROV-10`'s violation (`CT-CONFORM-08` says so explicitly), this counter because it is the
    only one that can see the failure `CT-CONFORM-09` is about.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[Any] = []

    def complete(self, request: Any, **kwargs: Any) -> Any:
        self.calls.append(request)
        return self._inner.complete(request, **kwargs)

    def __getattr__(self, name: str) -> Any:
        # Anything the provider protocol grows later still reaches the real provider, but only
        # `complete` is counted — a passthrough that silently counted nothing would make the
        # exact-zero assertion vacuous the moment the protocol gained a second dispatch method.
        return getattr(self._inner, name)

    @property
    def call_count(self) -> int:
        return len(self.calls)


# --- the two configuration rules --------------------------------------------------------------
#
# Written as functions rather than inline assertions so the **same rule** can be run against a
# deliberately broken copy of the documents. TS-57's lesson: a scan asserted only for containment
# stayed green when four of its six rules were disabled, because containment is satisfied by any
# one rule firing. So each rule returns a **named** problem, the real documents must produce none,
# and the broken fixture must produce every one of them by name.


def tier_wiring_problems(plan_text: str, test_sh_text: str) -> list[str]:
    """`CT-CONFORM-08` and `CT-CONFORM-11`, read against test plan §4.7's suite table.

    The clause makes two things contract — the fast tier needs no live model, and the full suite
    is not run per commit — and §4.7 is where both are wired. Each rule below names the failure it
    catches; a rule that stopped firing would leave the check green while the wiring was gone.
    """
    from tests.support.doc_tables import DocRowMissing, find_row, markdown_rows

    problems: list[str] = []
    rows = markdown_rows(plan_text)

    # Locate by the command, not by the suite's display name: the name is prose and gets reworded,
    # the `python -m harness.conform` invocation is the thing CI would actually run.
    try:
        conformance = find_row(rows, "harness.conform")
    except DocRowMissing:
        return ["conformance_row_missing"]

    trigger = " ".join(conformance).lower()

    # The prohibition, stated by FR-CONFORM-07: not per commit, not per push.
    if "every push" in trigger or "every commit" in trigger or "per commit" in trigger:
        problems.append("conformance_wired_per_commit")

    # The positive half: it must be wired to *something*, and FR-CONFORM-07 names what.
    if "change" not in trigger:
        problems.append("conformance_trigger_names_no_change_condition")
    if "fr-conform-07" not in trigger:
        problems.append("conformance_trigger_cites_no_requirement")

    # `CT-CONFORM-11`'s gate-wiring half: a trigger with no budget is an advisory job.
    if "min per backend" not in trigger:
        problems.append("conformance_budget_missing")

    # `CT-CONFORM-08`'s fast-tier half, asserted in **both** places it is written down: §4.7's row
    # and the script the Stop hook actually runs. A table that said "no live model" while
    # `scripts/test.sh` selected the live tier would be an intention, which is the word the case
    # uses for what it will not accept.
    # Located by the suite's name, not by its marker string: §4.9's assumptions table quotes the
    # same `TEST_CMD` string in a row of its own, so a locator on the markers matches two rows and
    # `find_row` refuses the ambiguity rather than picking one.
    try:
        fast_tier = find_row(rows, "Unit + artifact assertion")
    except DocRowMissing:
        return [*problems, "fast_tier_row_missing"]

    if "not live" not in " ".join(fast_tier):
        problems.append("fast_tier_admits_live")
    if "not live" not in test_sh_text:
        problems.append("test_sh_admits_live")
    if "harness.conform" in test_sh_text:
        problems.append("test_sh_runs_the_conformance_suite")

    return problems


def divergence_hole_problems(design_text: str, plan_text: str) -> list[str]:
    """`CT-CONFORM-14`, read across the three places the hole is recorded.

    §6.11.18 gives this case an unusual instruction: it *"verifies a limitation is visible, and it
    should be deleted the day the statistic is declared"*. A test that only asserted the report
    marks the gate unavailable would not notice that day — it would keep passing against a module
    that had been fixed, and the case would outlive its subject.

    So the assertion is a **three-way drift detector**: the clause (design `CT-CONFORM-14`), the
    open question (design §4.6 item 2) and the plan's own gap register (§7.4). All three currently
    say the same thing. When any stops, this goes red and the failure names the case to delete.
    """
    # Whitespace-normalized: the design wraps §4.6 item 2 mid-sentence, so a phrase that reads as
    # one line in the rendered document spans two in the source. A raw substring check would miss
    # it and report the hole as closed — the direction that deletes a case while its subject is
    # still open.
    problems: list[str] = []
    design_lower = " ".join(design_text.lower().split())
    plan_lower = " ".join(plan_text.lower().split())

    if "ct-conform-14" not in design_lower:
        problems.append("clause_removed")
    elif "not computable as written" not in design_lower:
        problems.append("clause_no_longer_declares_the_gate_uncomputable")

    # Design §4.6 item 2 — "What counts as a 'material' divergence between backends."
    if "fr-conform-06 declares a gate with no" not in design_lower:
        problems.append("design_open_question_resolved_or_reworded")

    # Test plan §7.4's gap register.
    if "accepted risk** until a statistic and threshold are declared" not in plan_lower:
        problems.append("plan_gap_row_no_longer_accepted_risk")

    # Test plan §4.8 — the explicit exclusion from the release gate.
    if "not computable as written" not in plan_lower:
        problems.append("plan_release_gate_no_longer_excludes_the_divergence_gate")

    return problems


# --- CT-CONFORM-10's enforcement-location rule ---------------------------------------------------


def consent_reimplementation_sites(source: str) -> list[tuple[int, str]]:
    """Places in `source` where `M-CONFORM` decides consent for itself.

    `CT-CONFORM-10` draws a boundary rather than stating a behaviour: the corpus is synthetic or
    consented, *"and the `M-CONF` consent gate is what enforces the boundary"*. §6.11.18 asks the
    case to assert *"the enforcement lives in `M-CONF` and is not re-implemented here"*.

    **A behavioural refusal test cannot make that assertion.** Running the suite against a `real`
    cohort and asserting it raises passes identically whether the refusal came from `M-CONF` or
    from a second copy of the rule inside `M-CONFORM` — and a second copy is exactly what the
    clause forbids, because two consent checks drift and the one that drifts open is the one
    nobody notices (RISK-10). So the oracle is structural: an AST scan for this module comparing a
    consent class against a literal of its own.

    What is flagged is a **comparison or membership test against a consent-class literal**.
    Reading `consent_class` is fine and necessary — a suite may log it or key a record by it; what
    it may not do is decide on it. Passing the value to `M-CONF` is likewise fine, which is why the
    scan looks at `Compare` nodes rather than at every mention of the name.
    """
    import ast

    literals = set(CONSENT_CLASSES_ALLOWED) | {"real"}
    sites: list[tuple[int, str]] = []

    def _literal_strings(node: Any) -> set[str]:
        found: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                found.add(child.value)
        return found

    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Compare):
            continue
        # `x == "synthetic"`, `x in ("synthetic", "consented")`, `x not in {...}` — all of them
        # are the module deciding. The left operand is included in the sweep because
        # `"consented" == cohort.consent_class` is the same decision written backwards.
        operands = [node.left, *node.comparators]
        hit = set().union(*(_literal_strings(operand) for operand in operands)) & literals
        if hit:
            sites.append((node.lineno, sorted(hit)[0]))
    return sites
