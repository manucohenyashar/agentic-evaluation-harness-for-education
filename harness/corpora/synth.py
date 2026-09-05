"""`F-SYNTH`, `F-FROZEN` and `F-DEV`: generated student work with known reference bands.

One generator, three corpora, because §4.4 requires it: *"A separate `F-DEV` subset of 8
submissions, **drawn from the same generator** but disjoint, is what developers iterate
against."* Two generators would make "the same generator" a claim nobody could check.

What a submission looks like on disk
------------------------------------
One Markdown file per submission, four pages inside it separated by an explicit page marker::

    <!-- page: 1 of 4 -->

Not four files per submission, for two reasons that pull the same way. 350 submissions × 4
pages is 1,400 committed files for a corpus whose interesting content is a few hundred bytes
each; and `tests/artifact/test_heldout_disjoint.py` hashes *one file per manifest entry*, so a
per-page layout would need a second manifest shape for the same kind of thing.

Ingestion cases that need real multi-blob input call
`tests.support.corpora.materialize_pages()`, which splits a submission into
`page-01.md` … `page-04.md` in a temp directory. That gives `FR-INGEST-06` both of its
permitted assembly-order sources to discriminate between — filename ordering, and the printed
`Page N of 4` line inside each page — without either being the directory iteration order the
requirement forbids.

Determinism
-----------
Each corpus draws from its own seeded `random.Random` (§4.6: seeded per concern, never the
module-global). Ability is *assigned* rather than drawn for `F-FROZEN` and `F-DEV`: both are
small, and `FR-CONFORM-01` requires the frozen set to span the score range *including
mid-range partial credit*, which a 36-draw sample from a random ability distribution does not
reliably do. Spreading ability evenly across the range is the only thing here that is
deliberate rather than random, and it is deliberate for a stated reason.

**Pseudonymity.** Every submission carries a `student_ref` and no name-shaped field
(`FR-STORE-12`, §4.4). The corpora are `consent_class = 'synthetic'` throughout; no real
student work is generated, referenced, or paraphrased here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Mapping, Sequence

from harness.corpora.reference_package import (
    BY_ID,
    CRITERIA,
    MCQ_OPTIONS,
    QUESTIONS,
    points_for,
)

SYNTH_SEED = 20260101
FROZEN_SEED = 20260102
DEV_SEED = 20260103

SYNTH_COUNT = 350
FROZEN_COUNT = 36  # FR-CONFORM-01: 30-50
DEV_COUNT = 8  # §4.4, and asserted exactly by TC-CONFORM-10

PAGES_PER_SUBMISSION = 4

# How a band renders as student work. Indexed by band ordinal, so the four-band open scale and
# the two-band MCQ scale both read out of a table rather than a branch.
_OPEN_RENDERING: tuple[str, ...] = (
    "I did not get to this part.",
    "{claim}.",
    "{claim}, because {reason}.",
    "{claim}, because {reason}, and this holds as long as {condition}.",
)

# Per-criterion phrasing. The claim is what the criterion is about; the reason and condition
# are what raise it through the band scale. Written out rather than generated, so a reader can
# see that a `secure` page really does contain more of the construct than an `emerging` one —
# a corpus whose bands differ only in a random word is a corpus no agreement figure means
# anything against.
_PHRASING: Mapping[str, tuple[str, str, str]] = {
    "C-01": (
        "The crate has weight down, the normal force out of the ramp, and friction up the slope",
        "nothing else is touching it",
        "the ramp surface stays in contact",
    ),
    "C-02": (
        "The normal force is perpendicular to the ramp and friction is parallel to it",
        "contact forces split into those two directions",
        "the crate is not tipping",
    ),
    "C-03": (
        "The crate stays put because friction balances the weight component along the ramp",
        "the two along-ramp forces are equal and opposite",
        "the required friction stays under the limiting value",
    ),
    "C-04": (
        "I swung equal arcs from A and from B and joined the two crossings",
        "the crossings are equidistant from both endpoints",
        "the radius is more than half of AB",
    ),
    "C-05": (
        "The arcs meet at P and Q, and PA equals PB and QA equals QB",
        "each arc was drawn with one radius",
        "the compass is not reset between arcs",
    ),
    "C-06": (
        "PQ is perpendicular to AB and cuts it in half",
        "P and Q are both equidistant from A and B",
        "A and B are distinct points",
    ),
    "C-07": (
        "The horizontal axis is time in seconds and the vertical axis is velocity in metres per second",
        "the axis labels carry their units",
        "the scale is linear on both axes",
    ),
    "C-08": (
        "It speeds up for four seconds, turns around at the peak, then slows to rest",
        "the curve rises, reaches a maximum, then falls",
        "the trolley is not pushed again",
    ),
    "C-09": (
        "The displacement over the first four seconds is the area under the curve, sixteen metres",
        "area under a velocity-time graph is displacement",
        "the velocity does not change sign in that interval",
    ),
    "C-10": (
        "All three trials are recorded to one decimal place",
        "the instrument reads to that precision",
        "the same instrument is used throughout",
    ),
    "C-11": (
        "The table shows the time falling as the ramp angle rises",
        "a steeper ramp gives a larger along-ramp force",
        "the surface is unchanged between trials",
    ),
    # No phrase here may collide with `FR-INGEST-11`'s evaluative-term list (`correct`, `valid`,
    # `appropriate`, `properly`, `as expected`, `should be`). The requirement scopes that list to
    # *descriptions of non-text regions*, not to student prose — but a synthetic corpus is the
    # wrong place to test whether every future scanner gets that scoping right, and "needs
    # repeating" says the same thing as "should be repeated".
    "C-12": (
        "Trial two sits off the pattern and needs repeating",
        "its value is far from the other two at the same angle",
        "nothing else about trial two was different",
    ),
}


@dataclass(frozen=True)
class SyntheticSubmission:
    submission_id: str
    student_ref: str
    bands: Mapping[str, str]
    pages: tuple[str, ...]

    @property
    def reference_points(self) -> float:
        return sum(points_for(cid, band) for cid, band in self.bands.items())

    def as_document(self) -> str:
        """The committed form: a header, then the four pages with their markers."""
        header = [
            f"# Submission {self.submission_id}",
            "",
            f"student_ref: {self.student_ref}",
            "consent_class: synthetic",
            "",
        ]
        body: list[str] = []
        for index, page in enumerate(self.pages, start=1):
            body.append(f"<!-- page: {index} of {len(self.pages)} -->")
            body.append(page)
            body.append("")
        return "\n".join(header + body).rstrip("\n")


def render_band(criterion_id: str, ordinal: int) -> str:
    """One open criterion rendered as student prose at one band ordinal.

    Public because `harness.corpora.adv_inj` renders the same way: an injection twin pair whose
    benign half was written in a different voice from `F-SYNTH` would make the adversarial
    differential a comparison of two corpora rather than of one payload.
    """
    claim, reason, condition = _PHRASING[criterion_id]
    return _OPEN_RENDERING[ordinal].format(claim=claim, reason=reason, condition=condition)


def _band_for(ordinal_count: int, ability: float, rng: random.Random) -> int:
    """Which band this student lands in on one criterion.

    Ability sets the centre and the draw moves one band either side of it, so a submission is
    uneven across criteria — a corpus where every criterion of a submission carries the same
    band makes ordinal agreement trivially perfect and hides every bug that only shows up on
    a mixed profile.
    """
    centre = ability * (ordinal_count - 1)
    jitter = rng.choice((-1, 0, 0, 1))
    return max(0, min(ordinal_count - 1, round(centre) + jitter))


def _page_text(question_index: int, criteria_ids: Sequence[str], bands: Mapping[str, str],
               mcq_choices: Mapping[str, str], page_no: int, submission_id: str) -> str:
    # The printed page line carries the submission id as well as the page number, which is what
    # a real answer booklet does and what `FR-INGEST-06` reads as its second-preference assembly
    # source. It also makes a page body unique to its submission, so no two corpora can end up
    # sharing one by coincidence — `F-FROZEN` staying held out is a property of the bytes, not of
    # anyone's discipline.
    question = QUESTIONS[question_index]
    lines = [
        f"Page {page_no} of {PAGES_PER_SUBMISSION} - {submission_id}",
        "",
        f"## {question.question_id}",
        "",
    ]
    for cid in criteria_ids:
        criterion = BY_ID[cid]
        ordinal = next(b.ordinal for b in criterion.bands if b.band == bands[cid])
        lines.append(render_band(cid, ordinal))
    if page_no == PAGES_PER_SUBMISSION:
        lines += ["", f"## {QUESTIONS[4].question_id}", ""]
        for cid, choice in mcq_choices.items():
            lines.append(f"{cid}: {choice}")
    return "\n".join(lines)


def generate(submission_id: str, student_ref: str, ability: float,
             rng: random.Random) -> SyntheticSubmission:
    bands: dict[str, str] = {}
    mcq_choices: dict[str, str] = {}
    for criterion in CRITERIA:
        if criterion.kind == "mcq":
            key = criterion.answer_key[0]
            correct = rng.random() < ability
            choice = key if correct else rng.choice([o for o in MCQ_OPTIONS if o != key])
            mcq_choices[criterion.criterion_id] = choice
            bands[criterion.criterion_id] = "met" if correct else "not_met"
        else:
            ordinal = _band_for(len(criterion.bands), ability, rng)
            bands[criterion.criterion_id] = criterion.bands[ordinal].band

    by_question: dict[str, list[str]] = {}
    for criterion in CRITERIA:
        if criterion.kind == "open":
            by_question.setdefault(criterion.question_id, []).append(criterion.criterion_id)

    pages = tuple(
        _page_text(
            index,
            by_question[QUESTIONS[index].question_id],
            bands,
            mcq_choices,
            index + 1,
            submission_id,
        )
        for index in range(PAGES_PER_SUBMISSION)
    )
    return SyntheticSubmission(
        submission_id=submission_id, student_ref=student_ref, bands=bands, pages=pages
    )


def _spread(count: int) -> list[float]:
    """Abilities spread evenly across `[0, 1]`, endpoints included.

    `FR-CONFORM-01` wants the frozen set to span the score range *and* to include mid-range
    partial credit; an even spread is the smallest construction that guarantees both for any
    count, rather than getting them from a lucky seed.
    """
    if count == 1:
        return [0.5]
    return [i / (count - 1) for i in range(count)]


def synth_cohort() -> tuple[SyntheticSubmission, ...]:
    """`F-SYNTH` — 350 submissions, ability drawn rather than assigned.

    Drawn, because this corpus stands in for a real cohort: the performance cases, the E2E
    journeys and the routing statistics all read it, and an evenly-spread cohort would make
    the routing rate an artifact of the spread. The extremes are pinned at both ends so the
    corpus still contains a fully-absent and a fully-secure submission, which several cases
    need and a 350-draw sample does not guarantee.
    """
    rng = random.Random(SYNTH_SEED)
    out: list[SyntheticSubmission] = []
    for index in range(1, SYNTH_COUNT + 1):
        if index == 1:
            ability = 0.0
        elif index == SYNTH_COUNT:
            ability = 1.0
        else:
            ability = min(1.0, max(0.0, rng.gauss(0.55, 0.22)))
        sid = f"SYN-{index:03d}"
        out.append(generate(sid, f"S-{index:04d}", ability, rng))
    return tuple(out)


def frozen_set() -> tuple[SyntheticSubmission, ...]:
    """`F-FROZEN` — the held-out conformance set (`FR-CONFORM-01`, 30-50)."""
    rng = random.Random(FROZEN_SEED)
    return tuple(
        generate(f"FZ-{index + 1:02d}", f"F-{index + 1:04d}", ability, rng)
        for index, ability in enumerate(_spread(FROZEN_COUNT))
    )


def dev_set() -> tuple[SyntheticSubmission, ...]:
    """`F-DEV` — the 8 submissions development is allowed to look at (§4.4)."""
    rng = random.Random(DEV_SEED)
    return tuple(
        generate(f"DEV-{index + 1}", f"D-{index + 1:04d}", ability, rng)
        for index, ability in enumerate(_spread(DEV_COUNT))
    )
