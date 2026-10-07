"""Template narratives for a multiple-choice-only paper (FR-PIPE-17, #523).

The decision of 2026-10-07 (the issue's option (a)): a submission whose criteria are
all deterministic gets its narrative **built from the multiple-choice results alone,
with no model call**. The writer path still offers the submission — that much shipped
with #565 — and M-SYNTH answers the offer deterministically instead of declining it
for want of a judged answer, so every enumerated submission is narrated.

Nothing here reads the store or the provider: the worker assembles the scored results
(the stored deterministic rows and the package's own band-to-credit mapping) and this
module turns them into sentences. A template, not a model, is what keeps the narrative
deterministic and free of a score claim by construction.
"""

from __future__ import annotations

from dataclasses import dataclass

from aeh.det.constants import BAND_CORRECT, BAND_UNRESOLVED


@dataclass(frozen=True)
class McItemResult:
    """One deterministic criterion's scored result, as the template reads it.

    `points` is the stored score; `full_points` is the same criterion's full-credit
    figure, priced through M-PKG's single canonical mapping (CT-PKG-05), so the
    sentence can say "of how many" without a second reader of the rubric.
    """

    criterion_id: str
    band: str
    points: float
    full_points: float


def _counts(items: tuple[McItemResult, ...]) -> tuple[int, int, float, float]:
    """`(correct, unresolved, earned, available)` over the question's items."""
    correct = sum(1 for item in items if item.band == BAND_CORRECT)
    unresolved = sum(1 for item in items if item.band == BAND_UNRESOLVED)
    earned = sum(item.points for item in items)
    available = sum(item.full_points for item in items)
    return correct, unresolved, earned, available


def mc_question_narrative(question_id: str, items: tuple[McItemResult, ...]) -> str:
    """One question's template sentence: its multiple-choice results, nothing else."""
    correct, unresolved, earned, available = _counts(items)
    text = (
        f"Multiple-choice result for {question_id}: "
        f"{correct} of {len(items)} items correct"
    )
    if unresolved:
        text += f", {unresolved} unresolved"
    return text + f"; {earned:g} of {available:g} points."


def mc_submission_narrative(items: tuple[McItemResult, ...]) -> str:
    """The whole-paper template sentence an MC-only submission gets at L2: the same
    results summarized across every narrated question, still from no source but the
    scores."""
    correct, unresolved, earned, available = _counts(items)
    text = f"Multiple-choice summary: {correct} of {len(items)} items correct"
    if unresolved:
        text += f", {unresolved} unresolved"
    return text + f"; {earned:g} of {available:g} points."
