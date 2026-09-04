"""Controls for every rule in `review_vocabulary`, in **both** directions.

A detector is only worth having if it is known to fire on the copy its clause forbids *and* to
stay silent on the copy a correct implementation produces. The second direction is the one that
gets skipped, and it is the one that matters more day to day: a rule that condemns compliant
source is a rule the first person to hit it switches off, and after that it protects nothing.

So every constant here is labelled `CORRECT_*` or names the violation it carries, and
`tests/contract/review/test_ct_review_vocabulary.py` runs each rule against both. These
fixtures are green today. They are drift detection, not coverage of `M-REVIEW`, which does not
exist.

The source fixtures are deliberately *plausible* rather than minimal — a two-line function that
trips a rule proves the rule fires on something nobody would write. Each one is the shape of the
implementation §3.15 describes.

The dataclasses at the bottom are the populations the red cases construct against. They are
built to be **non-degenerate**: a ranking case run over items that all score identically asserts
nothing about ranking, and a group case run over a population with one signature asserts nothing
about grouping. Each builder states the degeneracy it avoids.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- CT-REVIEW-12: edits are band selections ------------------------------------------------
#
# The rule flags a numeric score as a **parameter**. `new_points` as a return value or an
# attribute is correct — FR-REVIEW-10 derives it from `new_band` — so the correct source below
# computes and returns it, and must not trip.

CORRECT_BAND_EDIT_SOURCE = '''
"""M-REVIEW. Score edits are band selections (FR-REVIEW-10)."""


def act(item, action, new_band=None, review_seconds=0):
    """The only edit path. `new_band` is a band id; there is nowhere to put a number."""
    if action == "edit" and new_band is None:
        raise ValueError("an edit names a band")
    new_points = points_for_band(item.package_version_id, item.criterion_id, new_band)
    return record_label(item, action, new_band=new_band, new_points=new_points,
                        review_seconds=review_seconds)


def points_for_band(package_version_id, criterion_id, band):
    """CT-PKG-05's pinned mapping, applied in exactly one place."""
    return catalog.points_for_band(package_version_id, criterion_id, band)
'''

NUMERIC_SCORE_PARAMETER_SOURCE = '''
def act(item, action, new_band=None, new_points=None, review_seconds=0):
    """A teacher who "just wants to give it 7 out of 10" — the plausible way this arrives."""
    if new_points is not None:
        return record_label(item, action, new_points=new_points)
    return record_label(item, action, new_band=new_band)
'''

NUMERIC_SCORE_KEYWORD_ONLY_SOURCE = '''
def act(item, action, new_band=None, *, review_seconds=0, score=None):
    """Keyword-only and after a star, which is where a line scan stops looking."""
    return record_label(item, action, new_band=new_band, score=score)
'''


# --- CT-REVIEW-14: no per-student annotation surface -----------------------------------------

CORRECT_REVIEW_SURFACE_NAMES: tuple[str, ...] = (
    "build_queue",
    "act",
    "act_on_group",
    "blind_sample",
    "submit_blind",
    "whole_grade_sample",
    "record_label",
    "labels_for",
    "rank_queue_items",
    "observability_counters",
)

#: Each of these is how the surface actually arrives — named for its screen rather than for the
#: prohibition, which is why the rule matches on substrings.
ANNOTATION_SURFACE_NAMES_PRESENT: tuple[str, ...] = (
    "build_queue",
    "act",
    "annotate_submission",
    "student_notes",
    "add_comment",
)


# --- CT-REVIEW-01: the queue is sized by minutes ---------------------------------------------
#
# `blind_sample(n=15)` is §3.15's own signature, so a rule flagging a bare `n` would fail correct
# copy on its first run. `CORRECT_SIZING_NAMES` contains it deliberately.

CORRECT_SIZING_NAMES: tuple[str, ...] = (
    "build_queue",
    "budget_minutes",
    "reserved_for_blind_minutes",
    "blind_sample",
    "n",
    "residual_provisional",
)

PERCENTAGE_SIZING_NAMES_PRESENT: tuple[str, ...] = (
    "build_queue",
    "review_percent",
    "top_n_items",
    "coverage_fraction",
)


# --- CT-REVIEW-20: how a group may be described ----------------------------------------------

#: The correct copy names the actual Phase 1 rule. It contains "identical", which is a synonym a
#: naive rule would have flagged, and it must pass.
CORRECT_GROUP_RENDERING = """
Group of 210 responses — identical proposed band and identical integrity signature.
Applying a band here records one label per response.
"""

#: `"dissimilar"` contains `"similar"`. A substring rule flags this and is wrong; the word-boundary
#: half of `semantic_clustering_language` is what this fixture exists to hold in place.
GROUP_RENDERING_WITH_DISSIMILAR = """
Group of 210 responses — identical band and integrity signature. Responses that are
dissimilar in wording are still grouped when the signature matches.
"""

SEMANTIC_GROUP_RENDERINGS: tuple[str, ...] = (
    "210 similar responses were grouped for review.",
    "These submissions all show the same pattern.",
    "Semantically clustered by response content.",
    "This cluster contains 210 comparable answers.",
)

#: One rendering per phrase in `SEMANTIC_CLUSTERING_PHRASES`, carrying **that phrase and no
#: other**. The tuple above is a set of realistic captions and each trips several phrases at
#: once, so dropping a phrase from the rule leaves every one of them still caught — mutation
#: found exactly that: removing `"cluster"` changed nothing, because `"clustered"` and
#: `"comparable"` covered for it.
SEMANTIC_PHRASE_PROBES: dict[str, str] = {
    "similar": "These 210 responses are similar.",
    "semantically": "Grouped semantically for review.",
    "same pattern": "All 210 show the same pattern.",
    "alike": "The responses in this group are alike.",
    "cluster": "One cluster of 210 responses.",
    "clustered": "The responses were clustered for review.",
    "equivalent": "These 210 answers are equivalent.",
    "comparable": "A group of 210 comparable answers.",
}


# --- CT-REVIEW-19: the budget is an estimate -------------------------------------------------

CORRECT_BUDGET_RENDERING = """
Review budget: 30 minutes, of which 10 are reserved for the blind sample.
Item time is estimated and uncalibrated at this phase; actual time will vary.
"""

BUDGET_GUARANTEE_RENDERINGS: tuple[str, ...] = (
    "This queue will take 20 minutes.",
    "Guaranteed to fit inside your 30-minute window.",
    "You will finish this queue in the time remaining.",
    "Reviewing these takes exactly 20 minutes.",
)


# --- CT-REVIEW-04: all three of the residual triple are rendered -----------------------------


@dataclass(frozen=True)
class QueueFigures:
    """Just enough of `ReviewQueue` for the rendering rule, which reads three fields."""

    flagged_total: int = 812
    shown: tuple[str, ...] = ("item-1", "item-2", "item-3")
    residual_provisional: int | None = 809


CORRECT_QUEUE_RENDERING = """
812 criteria flagged for review. Showing 3 in this sitting.
809 remain provisional and carry forward to your next session.
"""

#: The dishonesty the clause exists to prevent, and it is the *plausible* screen: it states what
#: it is showing and says nothing about what it is not.
RENDERING_OMITTING_THE_RESIDUAL = """
Showing 3 items for review in this sitting.
"""

RENDERING_OMITTING_THE_FLAGGED_TOTAL = """
Showing 3 items. 809 remain provisional.
"""

#: A queue that never computed its residual at all. Distinct from a *screen* that omits it: the
#: rule has to report the field in both cases, and mutation showed the `value is None` branch was
#: never reached — every fixture carried all three figures, so inverting the condition changed
#: nothing.
UNCOMPUTED_QUEUE = QueueFigures(residual_provisional=None)  # type: ignore[arg-type]


# --- CT-REVIEW-09: unreachable, not hidden ---------------------------------------------------


@dataclass
class CompliantBlindSession:
    """A blind session holding only what §3.15's Data flow paragraph permits.

    It carries no prefetch attribute **at all**, not one set to `None`. The control asserts the
    absence rather than the value: `getattr(..., None) is not None` passes a session that declares
    `prefetched_score = None` and fills it on the next request, and mutation found that adding the
    declaration here changed no test.
    """

    session_id: str = "blind-1"
    submissions: tuple[str, ...] = ("sub-1", "sub-2")
    criteria: tuple[str, ...] = ("C-01", "C-02")

    def readable_tables(self) -> frozenset[str]:
        return frozenset({"submission", "criterion"})

    def available_data(self) -> dict[str, object]:
        return {"submissions": self.submissions, "criteria": self.criteria}


@dataclass
class PrefetchingBlindSession:
    """`TC-REVIEW-C09`'s adversarial construction, verbatim.

    The score row is prefetched *"to make submission instant"* and rendered nowhere. Nothing is
    displayed, the flow looks identical, and the guarantee has degraded from **unreachable** to
    **hidden** — one template change away from visible.
    """

    session_id: str = "blind-1"
    submissions: tuple[str, ...] = ("sub-1", "sub-2")
    criteria: tuple[str, ...] = ("C-01", "C-02")
    prefetched_score: dict[str, object] = field(
        default_factory=lambda: {"system_band": "B3", "confidence": 0.91}
    )

    def readable_tables(self) -> frozenset[str]:
        return frozenset({"submission", "criterion", "criterion_score"})

    def available_data(self) -> dict[str, object]:
        return {"submissions": self.submissions, "criteria": self.criteria}


# --- the populations the red cases construct against -----------------------------------------


@dataclass(frozen=True)
class ScoreRow:
    """A `criterion_score` row as `M-REVIEW` reads it (design §3.12's `CT-AGG-10` fields).

    `frozen` so a test that means to vary one signal has to build a new row rather than mutate a
    shared one — the failure mode where a ranking case's "before" and "after" are the same object.
    """

    score_id: str
    criterion_id: str = "C-01"
    submission_id: str = "sub-1"
    routing: str = "queued"
    origin: str = "escalation"
    evaluation_mode: str = "judged"
    state: str = "provisional_unreviewed"
    proposed_band: str = "B3"

    # FR-REVIEW-03's P(error) inputs
    panel_spread: float = 0.2
    adverse_integrity_signals: int = 0
    transcription_overlap: float = 0.0
    historical_override_rate: float = 0.1

    # the impact term
    criterion_weight: float = 0.2
    grade_boundary_delta: float = 5.0

    # the denominator, and the signal that must *not* drive ranking on its own
    est_seconds: int = 60
    self_confidence: float = 0.8

    # CT-AGG-10's integrity inputs, which are also CT-REVIEW-20's signature components
    spans_verified: bool = True
    evidence_present: bool = True
    sufficiency_flag: bool = True
    ocr_overlap_risk: bool = False


@dataclass(frozen=True)
class Label:
    """A `label` row carrying `FR-REVIEW-09`'s eight fields plus `NFR-REVIEW-03`'s attribution."""

    label_id: str
    label_type: str = "blind"
    saw_system_output: int = 0
    routing: str = "queued"
    origin: str = "escalation"
    evaluation_mode: str = "judged"
    review_seconds: int = 45
    system_band: str = "B3"
    teacher_band: str = "B3"
    actor: str = "teacher-1"
    timestamp: str = "2026-01-01T09:00:00Z"


def flagged_population(count: int = 40, *, criteria: int = 4) -> list[ScoreRow]:
    """A queued population with a **spread of expected values**, for the ranking cases.

    Every signal varies across the population, and none of them varies in lockstep with another:
    a fixture where `panel_spread` and `est_seconds` rise together cannot distinguish a ranking
    that reads one from a ranking that reads the other, so a per-signal sensitivity case run over
    it asserts nothing. The offsets below are deliberately coprime with `criteria` for that
    reason.
    """
    rows = []
    for i in range(count):
        rows.append(
            ScoreRow(
                score_id=f"score-{i}",
                criterion_id=f"C-{(i % criteria) + 1:02d}",
                submission_id=f"sub-{i // criteria}",
                proposed_band=f"B{(i % 4) + 1}",
                panel_spread=round(0.05 + (i % 7) * 0.12, 3),
                adverse_integrity_signals=i % 3,
                transcription_overlap=round((i % 5) * 0.15, 3),
                historical_override_rate=round((i % 11) * 0.07, 3),
                criterion_weight=round(0.1 + (i % 4) * 0.2, 3),
                grade_boundary_delta=round(1.0 + (i % 13) * 2.5, 3),
                est_seconds=30 + (i % 9) * 20,
                self_confidence=round(0.5 + (i % 6) * 0.08, 3),
                spans_verified=(i % 4) != 0,
                evidence_present=(i % 6) != 0,
                sufficiency_flag=(i % 5) != 0,
                ocr_overlap_risk=(i % 8) == 0,
            )
        )
    return rows


def oversubscribed_population(count: int = 800) -> list[ScoreRow]:
    """`TC-REVIEW-C02`'s discriminating fixture: far more flagged items than any budget fits.

    This is the construction the clause's ordering exists to survive. Reserve-after-ranking
    produces a full queue and **zero** blind items here, and nothing looks wrong — which is the
    mechanism by which RISK-13 happens without anyone choosing it.
    """
    return flagged_population(count, criteria=8)


def identical_signature_population(count: int = 12) -> list[ScoreRow]:
    """A population that groups: same band, same four integrity signals, different submissions.

    Different `submission_id` throughout, because `CT-REVIEW-13` asserts **one label per member**
    and a fixture whose members are indistinguishable rows cannot show N labels rather than one.
    """
    return [
        ScoreRow(
            score_id=f"grp-{i}",
            submission_id=f"sub-grp-{i}",
            criterion_id="C-01",
            proposed_band="B2",
            spans_verified=True,
            evidence_present=True,
            sufficiency_flag=True,
            ocr_overlap_risk=False,
        )
        for i in range(count)
    ]


def signature_variants(base: ScoreRow) -> dict[str, ScoreRow]:
    """One row per signature component, each differing from `base` in exactly that component.

    `CT-REVIEW-20`'s assertion is that two items differing in **any** component are not grouped,
    so the sweep needs a variant per component rather than one "different" row — otherwise a
    grouping rule that ignores three of the four components passes.
    """
    import dataclasses as _dataclasses

    return {
        "proposed_band": _dataclasses.replace(base, score_id="var-band", proposed_band="B4"),
        "spans_verified": _dataclasses.replace(
            base, score_id="var-spans", spans_verified=not base.spans_verified
        ),
        "evidence_present": _dataclasses.replace(
            base, score_id="var-evidence", evidence_present=not base.evidence_present
        ),
        "sufficiency_flag": _dataclasses.replace(
            base, score_id="var-sufficiency", sufficiency_flag=not base.sufficiency_flag
        ),
        "ocr_overlap_risk": _dataclasses.replace(
            base, score_id="var-ocr", ocr_overlap_risk=not base.ocr_overlap_risk
        ),
    }


def excluded_population() -> dict[str, ScoreRow]:
    """One row per population `CT-REVIEW-05` says is never rendered, keyed by which one it is.

    Keyed rather than listed so a failure names the population that leaked rather than reporting
    "an excluded item appeared".
    """
    return {
        "quarantine": ScoreRow(score_id="quar-1", routing="triage", origin="quarantine"),
        "blind_sample": ScoreRow(score_id="blind-1", routing="queued", origin="blind_sample"),
        "random_arm": ScoreRow(score_id="rand-1", routing="auto", origin="random_arm"),
        "deterministic_criterion": ScoreRow(
            score_id="det-1", routing="auto", evaluation_mode="deterministic"
        ),
    }
