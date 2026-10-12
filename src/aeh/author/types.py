"""The §3.1 data structures: the vocabulary every caller of `aeh.author` speaks.

Pinned by the design's Data-structures block and re-exported from the package root — the
tests construct through these names, so they live in exactly one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

#: The reasoning steps, in run order (`StepId` in the design's data-structures block).
StepId = Literal["inventory", "rubric", "grades"]

#: An item's outcome status: resolved (the proposal was accepted whole), derived (a
#: deterministic pre-pass filled it from stated content), placeholder (a named gap stands —
#: a sentinel in the draft or an omission the report names), unresolved (the chain could not
#: make a proposal pass the structural checks).
ItemStatus = Literal["resolved", "derived", "placeholder", "unresolved"]


@dataclass(frozen=True)
class StepOutcome:
    """One reasoning item's outcome: which model produced the accepted proposal, how many
    attempts it took, and one failure reason per rejected model, in fallback order."""

    step: StepId
    item_id: str
    status: ItemStatus
    model: str | None          # the build id that produced the accepted proposal
    attempts: int              # calls spent on the winning model, first attempt included
    failures: tuple[str, ...]  # one reason per rejected model, in fallback order


@dataclass(frozen=True)
class DraftResult:
    """What `draft()` produced: the two artifacts' paths and the run's tallies."""

    draft_path: Path
    report_path: Path
    outcomes: tuple[StepOutcome, ...]
    placeholders: int      # the named gaps standing (the sign-off slot is never counted)
    resolved: int          # outcome rows resolved or derived — the steps' own items
    unresolved: int        # outcome rows whose reasoning did not converge
    models_used: tuple[str, ...]  # in first-use order — a subset of the chain


@dataclass(frozen=True)
class ReviewAnswer:
    """The scripted form of one terminal answer (the review walk is issue #696's story)."""

    item_id: str
    value: str


@dataclass(frozen=True)
class ReviewResult:
    """What `review()` reports: whether the draft is ready, and what still stands."""

    ready: bool
    remaining: tuple[str, ...]  # item ids still placeholder/unresolved