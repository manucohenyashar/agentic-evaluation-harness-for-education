"""The reference assessment package every synthetic corpus is written against.

§4.4 fixes its shape: *"350 generated submissions against a 5-question, 15-criterion package:
12 open criteria, 3 MCQ."* Everything else here is chosen to satisfy the package constraints
the design states, so that a fixture corpus cannot be the reason a `M-PKG` case fails:

- `FR-SETUP-04` / `CT-PKG-04`: every criterion's band set has an **even** `band_count` in
  2..6, ordinals contiguous from 0, `points` non-decreasing in ordinal, and the bands are
  listed ordered by ordinal ascending.
- `FR-PKG-06` via `CT-PKG-04`: a caller may index by ordinal and rely on `bands[-1]` being the
  highest band. The literals below are written in that order, not sorted afterwards.
- ADR-1: there is no `is_correct` flag on an option; the key lives on `criterion.answer_key`.

The subject matter is not incidental either. The six element kinds `FR-INGEST-10` names — free
body diagram, geometry construction, graph or plot, table, label or annotation, spatial
relation — have to appear in a page corpus (`F-GRAPHIC`) that is *about* something, and a
mechanics-and-geometry worksheet is the smallest assignment in which all six occur without
being contrived.

**Four-band open criteria, two-band MCQ.** §4.4 requires `F-FROZEN` to include *"mid-range
partial-credit cases"*, and a two-band criterion has no mid-range. Four is the smallest even
count that gives two interior bands, which is also what makes `TC-STATS-*`'s interior-rate
figure non-degenerate on this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

PACKAGE_ID = "PKG-REF"
PACKAGE_VERSION = "1"

# The four-band scale for open criteria, ordered by ordinal ascending (CT-PKG-04).
OPEN_BANDS: tuple[tuple[str, int, float, str], ...] = (
    ("absent", 0, 0.0, "No work addressing this criterion appears."),
    ("emerging", 1, 1.0, "The work names the idea but does not carry it through."),
    ("developing", 2, 2.0, "The work carries the idea through with a stated gap."),
    ("secure", 3, 3.0, "The work carries the idea through completely and states its grounds."),
)

# The two-band scale for MCQ criteria (FR-SETUP-04's default: met / not met).
MCQ_BANDS: tuple[tuple[str, int, float, str], ...] = (
    ("not_met", 0, 0.0, "The selected option is not the keyed option."),
    ("met", 1, 1.0, "The selected option is the keyed option."),
)


@dataclass(frozen=True)
class Band:
    band: str
    ordinal: int
    points: float
    descriptor: str


@dataclass(frozen=True)
class Criterion:
    criterion_id: str
    question_id: str
    kind: str  # "open" | "mcq"
    text: str
    bands: tuple[Band, ...]
    answer_key: tuple[str, ...] = ()


@dataclass(frozen=True)
class Question:
    question_id: str
    prompt: str
    element_kind: str | None  # the FR-INGEST-10 kind this question's page carries, if any


def _bands(spec: Sequence[tuple[str, int, float, str]]) -> tuple[Band, ...]:
    return tuple(Band(band=b, ordinal=o, points=p, descriptor=d) for b, o, p, d in spec)


QUESTIONS: tuple[Question, ...] = (
    Question(
        "Q1",
        "A crate rests on a ramp inclined at 25 degrees. Draw and label the forces acting on "
        "the crate, then explain why it does not slide.",
        "free_body_diagram",
    ),
    Question(
        "Q2",
        "Construct the perpendicular bisector of segment AB and justify each step.",
        "geometry_construction",
    ),
    Question(
        "Q3",
        "The plot shows the velocity of a trolley over eight seconds. Describe the motion and "
        "find the displacement over the first four seconds.",
        "graph_or_plot",
    ),
    Question(
        "Q4",
        "Complete the results table for the three trials and state what the pattern shows.",
        "table",
    ),
    Question(
        "Q5",
        "Select the best answer for each of the three items below.",
        None,
    ),
)

# 12 open criteria across Q1..Q4, 3 MCQ criteria on Q5 (§4.4).
_OPEN_SPECS: tuple[tuple[str, str, str], ...] = (
    ("C-01", "Q1", "Identifies every force acting on the crate and no force that is absent."),
    ("C-02", "Q1", "Labels each force with its direction relative to the ramp surface."),
    ("C-03", "Q1", "Explains equilibrium in terms of the component along the ramp."),
    ("C-04", "Q2", "Produces a construction that yields a bisector rather than an estimate."),
    ("C-05", "Q2", "Names the points used and the relation each construction step establishes."),
    ("C-06", "Q2", "Justifies why the construction gives a perpendicular."),
    ("C-07", "Q3", "Reads the axes with their units before describing the motion."),
    ("C-08", "Q3", "Describes each phase of the motion, including the turning point."),
    ("C-09", "Q3", "Computes the displacement from the area under the curve."),
    ("C-10", "Q4", "Records all three trials with consistent precision."),
    ("C-11", "Q4", "States the relationship the table shows rather than restating the numbers."),
    ("C-12", "Q4", "Notes the trial that departs from the pattern and says what to do about it."),
)

_MCQ_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("C-13", "Q5", "Item 5a: the direction of the net force on the crate.", "B"),
    ("C-14", "Q5", "Item 5b: the unit of the gradient of the velocity-time plot.", "C"),
    ("C-15", "Q5", "Item 5c: the effect of doubling the ramp angle on the normal force.", "A"),
)

CRITERIA: tuple[Criterion, ...] = tuple(
    Criterion(cid, qid, "open", text, _bands(OPEN_BANDS)) for cid, qid, text in _OPEN_SPECS
) + tuple(
    Criterion(cid, qid, "mcq", text, _bands(MCQ_BANDS), answer_key=(key,))
    for cid, qid, text, key in _MCQ_SPECS
)

CRITERION_IDS: tuple[str, ...] = tuple(c.criterion_id for c in CRITERIA)
OPEN_CRITERION_IDS: tuple[str, ...] = tuple(c.criterion_id for c in CRITERIA if c.kind == "open")
MCQ_CRITERION_IDS: tuple[str, ...] = tuple(c.criterion_id for c in CRITERIA if c.kind == "mcq")

MCQ_OPTIONS: tuple[str, ...] = ("A", "B", "C", "D")

# 12 open criteria at 3 points + 3 MCQ criteria at 1 point.
MAX_POINTS: float = sum(c.bands[-1].points for c in CRITERIA)

BY_ID: Mapping[str, Criterion] = {c.criterion_id: c for c in CRITERIA}


def points_for(criterion_id: str, band: str) -> float:
    """The band→points mapping for the reference package.

    Present so a fixture's declared reference points and its declared reference bands cannot
    disagree — the corpus computes one from the other rather than carrying both by hand.
    """
    for b in BY_ID[criterion_id].bands:
        if b.band == band:
            return b.points
    raise KeyError(f"{band!r} is not a band of {criterion_id} (CT-JUDGE-04: never mapped or rounded)")


def as_json() -> dict[str, object]:
    """The package as committed data, for the corpora that cite it."""
    return {
        "package_id": PACKAGE_ID,
        "package_version": PACKAGE_VERSION,
        "max_points": MAX_POINTS,
        "questions": [
            {"question_id": q.question_id, "prompt": q.prompt, "element_kind": q.element_kind}
            for q in QUESTIONS
        ],
        "criteria": [
            {
                "criterion_id": c.criterion_id,
                "question_id": c.question_id,
                "kind": c.kind,
                "text": c.text,
                "answer_key": list(c.answer_key),
                "bands": [
                    {
                        "band": b.band,
                        "ordinal": b.ordinal,
                        "points": b.points,
                        "descriptor": b.descriptor,
                    }
                    for b in c.bands
                ],
            }
            for c in CRITERIA
        ],
    }
