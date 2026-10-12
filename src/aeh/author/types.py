"""The §3.1 data structures: the vocabulary every caller of `aeh.author` speaks.

Pinned by the design's Data-structures block and re-exported from the package root — the
tests construct through these names, so they live in exactly one place. The intake tier's
value types (`NormalizedDocument`, `Block`, `IntakeWarning`, `IntakeStats`) are the console
redesign delta's §3.1.1 amendment (ADR-46): the one representation every supported document
format normalizes into, which `AuthoringService.draft` consumes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

#: The reasoning steps, in run order (`StepId` in the design's data-structures block).
StepId = Literal["inventory", "rubric", "grades"]

#: The progress stages the console renders (`FR-AUTHOR-30`'s `AuthoringProgress.stage`):
#: the closed set of phases a draft, from-scratch or review run moves through. The stage
#: names are the console's own vocabulary — never logged for it to scrape (`FR-AUTHOR-30`:
#: the observer is the console's only progress source).
AuthoringStage = Literal["reading documents", "drafting", "reviewing", "writing draft"]

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


@dataclass(frozen=True)
class AuthoringProgress:
    """One step boundary's progress, in stage/item terms the console renders directly
    (`FR-AUTHOR-30`). The service emits it to the observer between steps, never mid-step,
    and checks the cancel at the same boundaries. `done` counts the stage's completed items
    and never decreases within a stage (`CT-AUTHOR-25`); `total` is the stage's item count
    when it is known (`None` while a stage's denominator is still being discovered — the
    drafting stage cannot know its item count until the inventory names the questions);
    `current` names the item just completed; `attempt` is the calls the item spent and
    `attempts` the budget it had (`1`/`1` for the deterministic steps that make no model
    call; a *derived* rubric row — a question whose criterion the answers line already
    determined — reports `attempt=0`, having spent nothing)."""

    stage: AuthoringStage
    done: int
    total: int | None
    current: str
    attempt: int
    attempts: int


#: The observer a console hands the service: one `AuthoringProgress` per step boundary,
#: called between steps, never mid-step (`FR-AUTHOR-30`).
AuthoringObserver = Callable[[AuthoringProgress], None]

#: The cooperative cancel check: called at the same boundaries the observer is; a `True`
#: stops the run at that boundary with `AuthoringCancelled` (`CT-AUTHOR-24`).
AuthoringCancel = Callable[[], bool]


@dataclass(frozen=True)
class CarriedAnswer:
    """One recorded review answer the re-draft carried over, provisional until the teacher
    confirms it at review (FR-AUTHOR-23). `fingerprint` is the recorded content
    fingerprint that matched — the hash over the item's id and the underlying content,
    never over the answer (CT-AUTHOR-20)."""

    item_id: str
    display: str
    fingerprint: str


@dataclass(frozen=True)
class DroppedAnswer:
    """One recorded review answer the re-draft did NOT re-apply, named with the reason it
    was dropped (FR-AUTHOR-23: dropped answers are accounted for, never silent)."""

    item_id: str
    display: str
    reason: str


# -- the intake tier's value types (console redesign delta §3.1.1, ADR-46) -------------------

#: Where a normalized document came from. Every supported format — and only these three —
#: normalizes into the one representation (FR-AUTHOR-24); anything else is refused per
#: FR-AUTHOR-28 before normalization is attempted.
SourceFormat = Literal["docx", "txt", "pdf"]

#: What one block of the representation is. `image_ref` marks where a picture stood — the
#: picture itself is never carried (`FR-AUTHOR-25`: it becomes a warning, never silently
#: dropped content).
BlockKind = Literal["heading", "paragraph", "list_item", "table", "image_ref"]


@dataclass(frozen=True)
class IntakeWarning:
    """One thing intake did not carry, or had to guess, in the teacher's own language
    (FR-AUTHOR-24/25/26). `message` is what the teacher reads — it names the location and
    never quotes more than the surrounding sentence of document text (`CT-AUTHOR-26`);
    `detail` is the operator-facing expansion, equally bounded."""

    code: "IntakeWarningCode"
    message: str
    detail: str = ""


#: What intake can warn about. The set is closed: a new honesty gap is a new code, decided
#: in design — never an ad-hoc string (`CT-AUTHOR-26`'s leak bound is asserted per code).
IntakeWarningCode = Literal[
    "image_not_carried",      # a picture was not carried (FR-AUTHOR-25)
    "equation_not_carried",   # an equation was not carried (FR-AUTHOR-25)
    "structure_guessed",      # inferred heading/table/list structure in an unmarked format
    "formatting_dropped",     # styling or content the converter could not carry (FR-AUTHOR-25)
    "encoding_fallback",      # a `.txt` was not UTF-8; the detected encoding was used
]


@dataclass(frozen=True)
class Block:
    """One block of the representation, in document order. `text` is plain text; a table
    carries one row per line with its cells tab-separated (the same plain-text encoding a
    `.txt` twin of the same content produces, so cross-format equality holds, `TC-AUTHOR-32`).
    `level` is a heading's level 1–6 where the format carries one (`None` otherwise).
    `ordinal` is the block's 0-based position in the document."""

    kind: BlockKind
    text: str
    ordinal: int
    level: int | None = None


@dataclass(frozen=True)
class IntakeStats:
    """What intake counted, next to the status (seam 4): the representation's own shape."""

    word_count: int
    block_count: int
    table_count: int
    image_count: int


@dataclass(frozen=True)
class NormalizedDocument:
    """The one internal document representation (FR-AUTHOR-24, ADR-46): an in-memory value
    type — not a file format, not a store row; the draft files remain the only durable
    authoring artefact (ADR-45). `source_sha256` fingerprints the original bytes; the
    carry-over's content fingerprints are defined over the normalized block text (§3.1.1),
    so a `.txt` re-draft of `.docx` content carries answers wherever the content matches."""

    source_name: str           # the teacher's filename, shown back to them
    source_format: SourceFormat
    source_sha256: str         # content fingerprint of the original bytes
    byte_size: int
    blocks: tuple[Block, ...]  # the document's content, in order
    warnings: tuple[IntakeWarning, ...] = field(default=())
    stats: IntakeStats = field(
        default_factory=lambda: IntakeStats(word_count=0, block_count=0, table_count=0,
                                            image_count=0))
