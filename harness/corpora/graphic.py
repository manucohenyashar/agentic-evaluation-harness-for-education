"""`F-GRAPHIC` — one page per element kind, plus the page `FR-INGEST-11` demands by name.

§4.4: *"One page per element kind named in `FR-INGEST-10`: free-body diagram, geometry
construction, graph/plot, table, label/annotation, spatial relation. Plus one page whose
**correct** description is easily confusable with a verdict."*

Each page here is a **page source**: a committed text description of what is drawn on the
scanned page, plus the geometry needed to render it. Test cases that need pixels rasterize it
on demand (`tests.support.corpora.materialize_pages`); nothing binary is committed, which is
the same rule §4.7 states for `F-ADV-PDF` — *"generated, not committed as binaries"*.

`required_fields` is the corpus's contribution, and it is the whole reason this corpus is
structured data rather than seven pictures. `FR-INGEST-10` states its own acceptance form —
*"a fixture page per element kind whose description is asserted to contain each named
field"* — so the named fields have to live somewhere a test can enumerate them. Transcribing
them here means `TC-INGEST-11` reads one list rather than restating the requirement in an
assertion, and `tests/regression/` can check the list still matches the design.

**The confusable page.** `FR-INGEST-11` requires the acceptance fixture set to include *"a page
whose correct description is easily confusable with a verdict"* — the point being that a
blanket ban on evaluative vocabulary is not the same as a check that discriminates. So this
page carries both renderings: the description that is correct and purely descriptive, and the
one that has slipped into judgement. `TC-INGEST-14`'s oracle is the differential between
them: the first is accepted, the second rejected. A module that rejects both passes a
one-sided check and fails this one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class GraphicPage:
    page_id: str
    element_kind: str
    question_id: str
    page_source: str
    required_fields: tuple[str, ...]
    extra: Mapping[str, object] = field(default_factory=dict)


# The evaluative-term list `FR-INGEST-11` names verbatim. Transcribed here because the
# confusable page's two renderings have to be built against the same list the module rejects
# on, and a second copy of it in a test file is how the two drift apart.
EVALUATIVE_TERMS: tuple[str, ...] = (
    "correct",
    "valid",
    "appropriate",
    "properly",
    "as expected",
    "should be",
)

PAGES: tuple[GraphicPage, ...] = (
    GraphicPage(
        page_id="GR-01-free-body-diagram",
        element_kind="free_body_diagram",
        question_id="Q1",
        page_source=(
            "A crate is drawn as a square resting on a line inclined 25 degrees above the "
            "horizontal.\n"
            "Three arrows leave the centre of the square:\n"
            "  - an arrow labelled W pointing vertically downward\n"
            "  - an arrow labelled N pointing away from the ramp surface, perpendicular to it\n"
            "  - an arrow labelled f pointing up the slope, parallel to the ramp surface\n"
            "The incline angle is marked at the base with the label 25 deg."
        ),
        # FR-INGEST-10: "per arrow, its label, origin point, and direction expressed as an
        # angle or as a relation to a named surface or axis".
        required_fields=("arrow_label", "arrow_origin", "arrow_direction"),
    ),
    GraphicPage(
        page_id="GR-02-geometry-construction",
        element_kind="geometry_construction",
        question_id="Q2",
        page_source=(
            "Segment AB is drawn horizontally. Two compass arcs of equal radius are struck, one "
            "centred on A and one centred on B, crossing above the segment at P and below it "
            "at Q.\n"
            "Line PQ is drawn through both crossings and meets AB at M.\n"
            "A right-angle square is marked at M. Tick marks show AM congruent to MB."
        ),
        # FR-INGEST-10: "named points, and each marked congruence, parallel or perpendicular
        # relation".
        required_fields=("named_points", "marked_relations"),
    ),
    GraphicPage(
        page_id="GR-03-graph-or-plot",
        element_kind="graph_or_plot",
        question_id="Q3",
        page_source=(
            "A line graph. The horizontal axis is labelled 'time / s' and runs 0 to 8 in steps "
            "of 1. The vertical axis is labelled 'velocity / m s^-1' and runs -4 to 8 in steps "
            "of 2.\n"
            "The plotted curve starts at the origin, rises to a maximum of 8 at t = 4, falls "
            "back through the horizontal axis at t = 6, and ends at -4 at t = 8."
        ),
        # FR-INGEST-10: "axis labels, units, and each intercept and turning point".
        required_fields=("axis_labels", "units", "intercepts", "turning_points"),
    ),
    GraphicPage(
        page_id="GR-04-table",
        element_kind="table",
        question_id="Q4",
        page_source=(
            "A hand-ruled results table with three columns and four rows.\n"
            "Header row: Trial | Ramp angle / deg | Time to base / s\n"
            "Row 1: 1 | 15 | 2.4\n"
            "Row 2: 2 | 25 | 3.1\n"
            "Row 3: 3 | 35 | 1.4"
        ),
        # FR-INGEST-10: "emitted as a Markdown table rather than as prose".
        required_fields=("markdown_table",),
    ),
    GraphicPage(
        page_id="GR-05-label-or-annotation",
        element_kind="label_or_annotation",
        question_id="Q1",
        page_source=(
            "A sketch of the ramp with a handwritten note in the right margin reading 'friction "
            "acts here'.\n"
            "A leader line runs from the note to the contact point between the crate and the "
            "ramp surface.\n"
            "A second note, 'measured from the base', sits directly beneath the angle marking "
            "with no leader line."
        ),
        # FR-INGEST-10: "the object it attaches to and the attachment means (leader line,
        # adjacency, arrow, bracket)".
        required_fields=("attachment_object", "attachment_means"),
    ),
    GraphicPage(
        page_id="GR-06-spatial-relation",
        element_kind="spatial_relation",
        question_id="Q2",
        page_source=(
            "Three circles are drawn in a row. The smallest is inside the largest; the middle "
            "one overlaps the largest on its right edge and touches the smallest at a single "
            "point.\n"
            "No labels or captions appear anywhere on the page."
        ),
        # FR-INGEST-10: "stated explicitly rather than implied by layout".
        required_fields=("explicit_relation_statement",),
    ),
    GraphicPage(
        page_id="GR-07-confusable-with-a-verdict",
        element_kind="free_body_diagram",
        question_id="Q1",
        page_source=(
            "A free-body diagram in which the normal-force arrow is drawn perpendicular to the "
            "*horizontal ground* rather than to the ramp surface, while the weight and friction "
            "arrows are drawn conventionally.\n"
            "The student has written 'N' beside the vertical arrow and circled it."
        ),
        required_fields=("arrow_label", "arrow_origin", "arrow_direction"),
        extra={
            "confusable_with_verdict": True,
            "requirement": "FR-INGEST-11",
            # The differential TC-INGEST-14 asserts on. The first says where the arrow points;
            # the second says the student got it wrong — which is a verdict, and is exactly the
            # judgement that must not be made at the transcription stage. They describe the same
            # page, which is what makes a module that rejects both visibly wrong rather than
            # merely cautious.
            "acceptable_description": (
                "An arrow labelled N leaves the centre of the crate and points vertically "
                "upward, perpendicular to the horizontal ground rather than to the ramp "
                "surface. The label N is circled."
            ),
            "evaluative_description": (
                "An arrow labelled N leaves the centre of the crate but is not drawn properly: "
                "it should be perpendicular to the ramp surface, so the normal force is not "
                "correct here."
            ),
        },
    ),
)

# `FR-INGEST-10` names six kinds; the seventh page is a second free-body diagram and does not
# add a kind. Kept as a constant so the corpus and the requirement can be compared directly.
ELEMENT_KINDS: tuple[str, ...] = (
    "free_body_diagram",
    "geometry_construction",
    "graph_or_plot",
    "table",
    "label_or_annotation",
    "spatial_relation",
)
