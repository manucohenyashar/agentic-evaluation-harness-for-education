"""Controls for every rule in `stats_vocabulary`, in **both** directions.

A detector is only worth having if it is known to fire on the copy its clause forbids *and* to
stay silent on the copy a correct implementation produces. The second direction is the one that
gets skipped, and it is the one that matters more day to day: a rule that condemns compliant
source is a rule the first person to hit it switches off, and after that it protects nothing.

So every constant here is labelled `CORRECT_*` or names the violation it carries, and
`tests/contract/stats/test_ct_stats_vocabulary.py` runs each rule against both. These fixtures are
green today. They are drift detection, not coverage of `M-STATS`, which does not exist.

The source fixtures are deliberately *plausible* rather than minimal — a two-line function that
trips a rule proves the rule fires on something nobody would write. Each one is the shape of the
implementation §3.16 describes.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- NFR-STATS-04: the filter exists once ----------------------------------------------------
#
# `CORRECT_STATS_SOURCE` defines the predicate in exactly one place and calls it from three, which
# is what a compliant `aeh/stats.py` looks like. An earlier draft of the rule counted *mentions*
# of `'blind'` and reported four sites for this source.

CORRECT_STATS_SOURCE = '''
"""M-STATS. Labels admissible to a validity claim are blind and judged (NFR-STATS-04)."""


def admissible_labels(labels):
    """The single filter. CT-STATS-01: it exists once here and every caller reuses it."""
    return [
        label
        for label in labels
        if label.label_type == "blind"
        and label.evaluation_mode == "judged"
        and not label.saw_system_output
    ]


def agreement(labels, scope, backend_profile, panel_build_ref, scoring_model):
    admissible = admissible_labels(labels)
    if not admissible:
        return NoValidationData(reason="no_blind_labels")
    return AgreementFigure(
        kappa=cohen_kappa(admissible),
        qwk=None,
        ordinal_alpha=None,
        n=len(admissible),
        scoring_model=scoring_model,
        population_scope_id=scope,
        backend_profile=backend_profile,
        panel_build_ref=panel_build_ref,
    )


def compression_check(labels, panel_bands):
    gold = admissible_labels(labels)
    return CompressionReport(gold=gold, panel=panel_bands)


def routing_policy_validity(labels):
    both_arms = admissible_labels(labels)
    return RoutingPolicyReport(population=both_arms)
'''

#: The violation `NFR-STATS-04` names: a second caller that inlined the predicate rather than
#: reusing the filter. Nothing about it is visible at a call site, both copies are correct today,
#: and the next change to the definition of "admissible" reaches only one of them.
FILTER_INLINED_TWICE_SOURCE = '''
def admissible_labels(labels):
    return [l for l in labels if l.label_type == "blind" and l.evaluation_mode == "judged"]


def agreement(labels, scope):
    return AgreementFigure(kappa=cohen_kappa(admissible_labels(labels)), n=len(labels))


def agreement_for_dashboard(labels, scope):
    # Inlined "for speed" -- and now there are two definitions of admissible.
    rows = [l for l in labels if l.label_type == "blind" and l.evaluation_mode == "judged"]
    return AgreementFigure(kappa=cohen_kappa(rows), n=len(rows))
'''

#: A function that reads `label_type` **without** deciding admissibility: `blind_count` is
#: `CT-STATS-06`'s counter and it legitimately mentions `"blind"`. The rule must report **zero**
#: definition sites here, which is what makes it a rule about the predicate rather than about the
#: word: a scan matching either half of the conjunction condemns this, and the reflex fix for that
#: is to stop scanning.
COLUMN_READ_WITHOUT_THE_PREDICATE_SOURCE = '''
def blind_count(labels):
    return sum(1 for l in labels if l.label_type == "blind")


def judged_criteria(criteria):
    return [c for c in criteria if c.evaluation_mode == "judged"]
'''

#: No filter at all. The rule must report a cardinality of **zero** and the case must fail on it —
#: an oracle written as "at most one" passes this source, which computes agreement over everything.
NO_FILTER_SOURCE = '''
def agreement(labels, scope):
    return AgreementFigure(kappa=cohen_kappa(labels), n=len(labels))
'''

#: A module-level predicate. Compliant: `NFR-STATS-04` asks for one definition, not for a function.
FILTER_AS_MODULE_CONSTANT_SOURCE = '''
ADMISSIBLE = ("blind", "judged")


def agreement(labels, scope):
    rows = [l for l in labels if (l.label_type, l.evaluation_mode) == ADMISSIBLE]
    return AgreementFigure(kappa=cohen_kappa(rows), n=len(rows))
'''


# --- CT-STATS-01: agreement over another population -------------------------------------------

#: A compliant public surface. Every name here is one design §3.16 or the clause table declares,
#: and several of them deliberately carry one half of the rule's conjunction: `operational_count`
#: names a population, `agreement` and `agreement_kappa` name the statistic. None is a violation.
CORRECT_SURFACE_NAMES: tuple[str, ...] = (
    "agreement",
    "agreement_kappa",
    "admissible_labels",
    "operational_count",
    "blind_count",
    "compression_check",
    "surface_proxies",
    "routing_policy_validity",
    "drift_check",
    "run_mvvp",
    "promote",
    "criterion_override_history",
    "narrative_quality",
    "observability_counters",
)

#: `CT-STATS-01`'s named adversarial construction, plus the two variants of it that a reviewer
#: would wave through. Every one is correct in isolation and honestly labelled, which is the
#: clause's own point: *"none will be added"* exists because the second function **is** the
#: failure, not because the second function would be wrong.
SURFACE_NAMES_ADMITTING_OTHER_POPULATIONS: tuple[str, ...] = (
    "compute_agreement_all_labels",
    "operational_agreement",
    "kappa_including_operational",
    "raw_labels_agreement",
)

#: An agreement function that reads the label table directly. The name rule cannot see this one —
#: it is called `criterion_agreement`, which is exactly what it computes — so the structural rule
#: is what has to catch it.
AGREEMENT_BYPASSING_THE_FILTER_SOURCE = '''
def admissible_labels(labels):
    return [l for l in labels if l.label_type == "blind" and l.evaluation_mode == "judged"]


def criterion_agreement(store, criterion_id):
    rows = store.query("SELECT band, teacher_band FROM label WHERE criterion_id = :c", c=criterion_id)
    return AgreementFigure(kappa=cohen_kappa(rows), n=len(rows))
'''

#: The compliant version of the same shape: the filter is applied by the caller and the signature
#: says so. A rule that insisted on seeing the call would fail this, and it is a reasonable design.
AGREEMENT_TAKING_FILTERED_LABELS_SOURCE = '''
def criterion_agreement(admissible_rows, criterion_id):
    """Takes labels already through `admissible_labels`; the parameter name is the contract."""
    return AgreementFigure(kappa=cohen_kappa(admissible_rows), n=len(admissible_rows))
'''


# --- CT-STATS-04, CT-STATS-14: what may never be merged -----------------------------------------

#: Names offering a combination the contract keeps apart. `combined_quality_score` is
#: `CT-STATS-14`'s exact failure — κ and narrative quality in one number — and the others are
#: `CT-STATS-04`'s.
MERGING_SURFACE_NAMES: tuple[str, ...] = (
    "combined_quality_score",
    "overall_agreement",
    "merged_atomic_and_holistic",
    "aggregate_all_populations",
    "total_backend_agreement",
)


# --- CT-STATS-20: the headline -------------------------------------------------------------------

#: A compliant agreement block, in the shape HLD §11.5's S12 mock-up uses: every figure scoped,
#: every figure chance-corrected, the small sample carrying its qualifier. The Greek κ is here
#: deliberately — a rule that does not know it condemns the design's own mock-up.
CORRECT_AGREEMENT_BLOCK = """
Agreement — Year 9 Extended Response, population: y9-2026-spring, backend: edge-local-q4
  atomic criteria      κ = 0.71   n = 142   panel build 9f2a1c   model: atomic
  holistic criteria    κ = 0.48   n = 118   panel build 9f2a1c   model: holistic
  criterion C-04       κ = 0.35   n = 15    too few to draw conclusions from
  criterion C-11, population y9-2026-spring, backend edge-local-q4:  κ = 0.66
Weakest criterion in this population: C-04 (evidence use)
"""

#: The violation, and it is subtle enough to ship: every figure below it is scoped and correct.
#: `CT-STATS-20` says the consumer *"has violated this contract even if every figure in it is
#: correct"*, which is why the rule reads the framing rather than the numbers.
HEADLINE_RENDERINGS: tuple[str, ...] = (
    "Overall accuracy: 87%\nBreakdown by population follows.",
    "System agreement κ = 0.74 across all criteria",
    "This package is validated — overall agreement 0.81",
    "How accurate is the system? 89%",
    "Quality score\n  0.83\nDetail by criterion below",
)

#: The hard case for the headline rule, and the one the other fixtures do not reach: a headline
#: that **is** scoped, in the sense that every scope word appears on its line, and is still a
#: system-wide claim. The mutation campaign found the phrase list unexercised without it — every
#: other headline fixture was already caught by the missing-scope branch, so disabling the framing
#: check changed nothing.
SCOPED_HEADLINE_RENDERINGS: tuple[str, ...] = (
    "Overall accuracy across every population, backend and panel build: 87% (n = 4,210)",
    "System-wide accuracy for this cohort's criterion set: 0.883 (n = 512, panel 9f2a1c)",
)

#: Renderings that carry a number with no scope beside it. Same clause, quieter route: a figure on
#: a line by itself is a headline whatever the page around it says.
UNSCOPED_FIGURE_RENDERINGS: tuple[str, ...] = (
    "Agreement\n  0.79\n",
    "Validation: 92%",
)


# --- CT-STATS-21: the degeneracy -----------------------------------------------------------------

#: Compliant: the number is shown — that is the promised behaviour — and the degeneracy is
#: disclosed beside it rather than in a footnote somewhere else.
CORRECT_DEGENERACY_DISCLOSURE = """
Criterion C-07 (two-band), population y9-2026-spring, backend edge-local-q4
  α = 1.00   n = 96   panel build 9f2a1c
  Two-band criteria are degenerate for α and κ: this figure carries less information than a
  multi-band figure at the same value, and the resolution is an open design question.
"""

#: A compliant rendering that uses the equivalence vocabulary about something that is **not** the
#: degenerate figure. `CT-STATS-21` forbids presenting binary agreement as equivalent to
#: multi-band agreement; it says nothing about comparing this year's band 3 to last year's, and a
#: rule that flagged this would be condemning ordinary copy.
EQUIVALENCE_ABOUT_SOMETHING_ELSE = """
Band 3 this year is comparable to band 3 last year, so the boundary has not moved.
Criterion C-04 (four-band), population y9-2026-spring: κ = 0.35, n = 15.
"""

#: The forbidden presentation: the disclosure vocabulary is present, and used to claim the
#: equivalence the clause forbids.
EQUIVALENCE_RENDERINGS: tuple[str, ...] = (
    "Criterion C-07 is binary; its α = 1.00 is equivalent to a multi-band α of 1.00.",
    "Two-band agreement is directly comparable to the multi-band figures above.",
    "This binary criterion is as reliable as the four-band ones (α = 1.00).",
)


# --- CT-STATS-03: absence is not a number ---------------------------------------------------------


class CompliantNoValidationData:
    """What `NoValidationData` must be: a value that refuses every numeric reading of itself.

    Not a stand-in for the implementation — it is the **control** for `numeric_coercions`, which
    would otherwise be a probe nobody had run against a passing input.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"NoValidationData(reason={self.reason!r})"


class FloatSubclassNoValidationData(float):
    """`CT-STATS-03`'s adversarial construction, verbatim: a `float` subclass valued `0.0`.

    *"So existing formatting code doesn't need to change."* Every call site keeps working, every
    template renders, and a package with no validation evidence now advertises an agreement of
    0.00 — which reads as *measured and bad* rather than *never measured*. `CT-PKG-13` then sends
    it to another school.
    """

    def __new__(cls, reason: str = "no_blind_labels"):
        value = super().__new__(cls, 0.0)
        value.reason = reason
        return value


# --- CT-STATS-15: the write scope ------------------------------------------------------------------

#: Compliant: writes `package_validation` and a Tier D statistics row, **reads** grades and labels.
#: The reads are the control that matters — the clause grants them explicitly, and a rule matching
#: table names rather than write verbs would condemn the module's whole reason for existing.
CORRECT_WRITE_SCOPE_SOURCE = '''
def promote(catalog, store, cohort_id):
    labels = store.query("SELECT * FROM label WHERE cohort_id = :c", c=cohort_id)
    grades = store.query("SELECT band, points FROM grade WHERE cohort_id = :c", c=cohort_id)
    metrics = store.query("SELECT * FROM run_metrics WHERE cohort_id = :c", c=cohort_id)
    catalog.update_validation(cohort_id, blind_count=len(labels))
    store.durable().enqueue_write(
        "INSERT INTO stats_criterion_summary (criterion_id, kappa, n) VALUES (:a, :b, :c)"
    )
    return ValidationUpdate(grades=grades, metrics=metrics)
'''

#: Each of these is a write the clause closes. The middle one is the realistic version: a
#: convenience backfill of the score row with the agreement figure, on a path no test drives —
#: which is why the clause asks for the assertion to be static.
FORBIDDEN_WRITE_SOURCES: dict[str, str] = {
    "grade": 'def f(s):\n    s.execute("UPDATE grade SET band = :b WHERE id = :i")\n',
    "criterion_score": (
        'def backfill(s):\n'
        '    s.execute("UPDATE criterion_score SET agreement = :a WHERE criterion_id = :c")\n'
    ),
    "narrative": 'def g(s):\n    s.execute("INSERT INTO narrative (text) VALUES (:t)")\n',
    "criterion_band": 'def h(s):\n    s.execute("DELETE FROM criterion_band WHERE id = :i")\n',
}


# --- label fixtures for the admissibility sweep -----------------------------------------------------

@dataclass(frozen=True)
class Label:
    """A label row as `M-REVIEW` produces it, with the columns `CT-STATS-01` filters on.

    **Invented, and only as far as it has to be.** `M-STATS` reads labels; §3.16 does not declare
    the row, and `CT-REVIEW-07`/`-08` — which this module's *Requires* table cites — name the
    columns without giving a dataclass. So the fields below are the four the admissibility
    predicate reads plus the two a κ needs, and nothing else: a fixture that invented a richer row
    would be asserting a shape no clause promises.

    Defaults are the **admissible** values, so a contaminated fixture is one keyword away and a
    reader sees exactly which column made it inadmissible.
    """

    label_id: str
    label_type: str = "blind"
    evaluation_mode: str = "judged"
    saw_system_output: bool = False
    criterion_id: str = "C-01"
    band: int = 3
    teacher_band: int = 3
    origin: str = "blind_sample"

    #: `CT-REVIEW-07`'s `routing` column: which side of the routing policy produced the judgment
    #: this label scores. `FR-STATS-08` compares the two arms and names them; `CT-ORCH-15` is why
    #: they stay separable at all, since the random arm carries its own `origin` and is never
    #: suppressed. `None` for a label not produced under the policy.
    routing: str | None = None


#: One admissible label, as the filter's positive control. Without it the exclusion sweep passes
#: for a filter that returns nothing at all — which excludes every contaminated class perfectly
#: and computes agreement over nothing, the vacuous pass this suite has to be able to fail.
ADMISSIBLE_LABEL = Label(label_id="lbl-admissible-1")


#: `CT-STATS-01`'s adversarial construction, assembled the way it would actually arrive: the
#: compliant module, unchanged, **plus** one honest new function for the operator dashboard.
#:
#: Everything that was true of `CORRECT_STATS_SOURCE` is still true here — the filter still exists
#: exactly once, `agreement` still routes through it, every `FR-STATS-*` property still holds.
#: That is the clause's point. The new function is correct in isolation, its label is honest, and
#: within two releases its output is on a screen beside a validity figure with nothing
#: distinguishing them. `CT-STATS-01` says *"and none will be added"* because the second function
#: **is** the failure.
CORRECT_SOURCE_PLUS_ADVERSARIAL_FUNCTION = CORRECT_STATS_SOURCE + '''

def compute_agreement_all_labels(labels, scope, backend_profile, panel_build_ref, scoring_model):
    """Operational figure for the operator dashboard. Clearly labelled; not a validity claim."""
    return AgreementFigure(
        kappa=cohen_kappa(labels),
        qwk=None,
        ordinal_alpha=None,
        n=len(labels),
        scoring_model=scoring_model,
        population_scope_id=scope,
        backend_profile=backend_profile,
        panel_build_ref=panel_build_ref,
    )
'''
