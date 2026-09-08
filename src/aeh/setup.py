"""M-SETUP — Stage A: the question inventory proposal, the rubric read-back, the
decomposability classification, the dependency proposals, the two blocking gates, and
publication (#50, #51, #52; design §3.6, FR-SETUP-01/-02/-04/-05/-06/-07/-08/-09/-10/-14/-16,
NFR-SETUP-01/-02/-04).

Stage A runs ONCE per package version (`CT-SETUP-16`): the assessment document the
teacher ingested through `M-INGEST` is read (never re-ingested — `CT-SETUP-11`: setup
reads documents through `M-INGEST`'s store, not around it), a model proposes the
question inventory through `M-PROV`'s seam (`FR-PROV-13` names this module a prompt
builder; `HLD §7.8` Phase 1 is the proposal logic), the teacher confirms or corrects
it, and the confirmed question rows are written through `M-PKG` (`FR-PKG-03`) — where
the §6.2 lock engages at the confirmation (`FR-SETUP-02`), deliberately earlier than
publication. The confirmation IS the teacher's assertion about content; a lock that
engaged only at publish would leave a window where the instrument could drift after
the teacher signed it. After the gate, `read_back_rubric` (#51) reads the stored rubric
into criteria and even band sets whose descriptors state what a response DOES — a
descriptor carrying a magnitude phrase (`SETUP_MAGNITUDE_PHRASES`) or a bare numeral is
rejected and re-requested, never stored (`FR-SETUP-05`).

**The two blocking steps** (`CT-SETUP-01`, §4.2.1, `FR-CONSOLE-06`): exactly two setup
operations block — confirming the question inventory (S3) and setting the answer keys
(S4). `publish()` enforces both gates and is refused until they hold; publication is
the moment `M-PKG`'s version lock flips, which is the §6.2 lock taking effect
(`FR-SETUP-02`). Everything else in the design's setup sequence is skippable with a
recorded default, and the steps this story does not stage yet are enumerated by
`steps()` as present-and-unavailable, naming the story that stages them — the console
tells the teacher the truth about what remains (`NFR-SETUP-04`, `FR-CONSOLE-25`):

- rubric read-back: HERE since #51 — non-blocking (`FR-SETUP-04`: the met/not-met
  default a criterion without a band set takes is the recorded default, so the step can
  be deferred; the derived set is recorded as `derived_default`, not passed off as an
  explicit choice),
- decomposability and dependencies: HERE since #52 — the §5.3 decision table is the
  module's (`classify_decomposability` asks the model for the five ANSWERS, never a
  verdict; fail one question and the classification follows it, and an unclear answer
  defaults `holistic`, never `atomic` — NFR-SETUP-02, RISK-27). The confirmations the
  borderline criteria surface are capped at `SETUP_MAX_CONFIRMATIONS` by THIS module
  (`CT-SETUP-13`, headlessly — no console required), dependencies default to zero and
  are written only on explicit teacher approval (`FR-SETUP-10`), and every verdict —
  teacher-confirmed or taken as the module's default — is recorded through `M-PKG`
  (`R62`: M-CALIB and M-STATS can tell the two apart),
- grade policy, grade boundaries and the prefix budget: #53 — which also stages S4's
  full `FR-SETUP-03` validation semantics. Here `set_answer_keys` is the thin,
  blocking write-through to `PackageCatalog.set_answer_key`, and publish's second gate
  reads the same structural fact it will enforce: every deterministic criterion keyed.

**State is the database, never memory** (`CT-SETUP-03`): a process that dies after the
proposal resumes by constructing a fresh `SetupService` over the same Tier P file and
calling `propose_inventory` again — the stored proposal comes back unchanged, and
`steps()` reports what remains. Nothing here holds in-memory state across calls.

The four seams, from the first commit:

1. **Headless driver** — `SetupService` runs the whole stage from code: structured
   results (`InventoryProposal`, `SetupProgress` with a per-step list), no console
   required (`CT-CONSOLE-01`).
2. **Deterministic transport** — every model call goes through the `InferenceProvider`
   seam (`CT-PROV-01`); tests script a double, production passes a real provider, and
   no other egress exists (`CT-PROV-15`).
3. **Env-gated knobs** — `HARNESS_SETUP_PROPOSAL_ATTEMPTS` and
   `HARNESS_SETUP_READBACK_ATTEMPTS` (the degraded-path attempt budgets, read at CALL
   time per this codebase's knob doctrine).
4. **Stage-level observability** — `LOGGER` ("aeh.setup") logs every proposal attempt,
   confirmation, gate refusal and publication; the proposal row carries its attempt
   count and status, so a degraded proposal is visible in the database, not just the
   log.

Coverage note: the `TC-SETUP-*` cases (test plan §5.6) land with issue #54, the
co-evolution test story paired with this one.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from aeh.ingest import DocumentId
from aeh.pkg import (
    PackageCatalog,
    PackageDraft,
    PackageVersionId,
    QUESTION_TYPES,
)
from aeh.prov import InferenceProvider, ModelRef, PromptPayload, SamplingParams

__all__ = [
    "CLASSIFICATIONS",
    "CLASSIFY_ATTEMPTS_DEFAULT",
    "CLASSIFY_ATTEMPTS_ENV",
    "CONFIRMATIONS_DEFAULT",
    "CONFIRMATIONS_ENV",
    "CriterionDraft",
    "DecomposabilityVerdict",
    "DependencyProposal",
    "FIVE_QUESTIONS",
    "InventoryProposal",
    "PROPOSAL_ATTEMPTS_DEFAULT",
    "PROPOSAL_ATTEMPTS_ENV",
    "ProposedBand",
    "ProposedOption",
    "ProposedQuestion",
    "QuestionCorrection",
    "READBACK_ATTEMPTS_DEFAULT",
    "READBACK_ATTEMPTS_ENV",
    "RubricReadback",
    "SCORING_MODELS",
    "SETUP_CLASSIFY_TEMPLATE_V",
    "SETUP_DEFAULT_BAND_COUNT",
    "SETUP_DEPENDENCIES_TEMPLATE_V",
    "SETUP_EVIDENCE_TYPE_DEFAULT",
    "SETUP_MAGNITUDE_PHRASES",
    "SETUP_MAX_CONFIRMATIONS",
    "SETUP_PROMPT_TEMPLATE_V",
    "SETUP_READBACK_TEMPLATE_V",
    "SetupError",
    "SetupOrderError",
    "SetupProgress",
    "SetupService",
    "SetupStep",
]

#: Module observability: every proposal attempt, confirmation, gate refusal and
#: publication is logged with its identifiers (the four seams' stage-level trace).
LOGGER = logging.getLogger("aeh.setup")

#: The version-pinned inventory prompt (`CT-SETUP-14`, `TC-SETUP-22`): changing the
#: wording changes what the model was asked, so the text carries a version and the
#: proposal row records which one produced it. A prompt change is a NEW version string
#: and a new proposal — never an in-place edit of this constant's meaning.
SETUP_PROMPT_TEMPLATE_V = "setup-inventory-v1"

#: The degraded-path attempt budget (`CT-SETUP-12`): a model proposal that fails to
#: parse or validate is re-requested up to this many times, then the proposal is
#: recorded as `needs_manual_entry` — degraded but complete: the teacher enters the
#: questions as corrections and confirms. Env-gated so a slow test box can shrink it.
PROPOSAL_ATTEMPTS_ENV = "HARNESS_SETUP_PROPOSAL_ATTEMPTS"
PROPOSAL_ATTEMPTS_DEFAULT = 3


def _configured_proposal_attempts() -> int:
    """The attempt budget, read at call time — never at import (`M-PKG`'s knob
    doctrine: a test or deployment sets it per operation, not per process load)."""
    raw = os.environ.get(PROPOSAL_ATTEMPTS_ENV)
    if not raw:
        return PROPOSAL_ATTEMPTS_DEFAULT
    try:
        value = int(raw)
    except ValueError as error:
        raise SetupError(
            f"{PROPOSAL_ATTEMPTS_ENV}={raw!r} is not an integer."
        ) from error
    if value < 1:
        raise SetupError(
            f"{PROPOSAL_ATTEMPTS_ENV}={value} is below 1: at least one proposal "
            "attempt is required."
        )
    return value


#: The version-pinned read-back prompt (`NFR-SETUP-03`, `CT-SETUP-14`'s rule carried to
#: the read back): changing the wording changes what the model was asked, which changes
#: every criterion the read back produces from then on — so the text carries a version
#: and the read-back row records which one produced it. A prompt change is a NEW version
#: string, never an in-place edit of this constant's meaning.
SETUP_READBACK_TEMPLATE_V = "setup-readback-v1"

#: The decomposability-classification prompt's pinned version (`#52`, NFR-SETUP-03's
#: rule at the classifier): a change to it changes every classification made afterwards,
#: so it is recorded with the verdicts it produced (`CT-SETUP-14`'s rule, applied to
#: this prompt too).
SETUP_CLASSIFY_TEMPLATE_V = "setup-classify-v1"

#: The dependency-proposal prompt's pinned version (`#52`): the same record-where-used
#: rule — the proposals' plain-language renderings are traceable to the prompt that
#: elicited them.
SETUP_DEPENDENCIES_TEMPLATE_V = "setup-dependencies-v1"

#: The default band-set size (`FR-SETUP-04`): a criterion whose construct carries no
#: partial credit gets two bands — met / not met — derived from the criterion's own
#: text. Configuration §3.6: `SETUP_DEFAULT_BAND_COUNT` (2).
SETUP_DEFAULT_BAND_COUNT = 2

#: The magnitude-phrase bar (`FR-SETUP-05`, Configuration §3.6: `SETUP_MAGNITUDE_PHRASES`):
#: a generated band descriptor matching any of these (case-insensitive substring) is
#: REJECTED and RE-GENERATED — the setup-time twin of FR-JUDGE-03 (no numeral in the
#: scoring prompt) and FR-SYNTH-03 (no score claim in narrative): the system keeps
#: magnitude language away from the model at every stage. The bar's other arm, a BARE
#: NUMERAL, is a pattern rather than a phrase and lives in `_NUMERAL_IN_DESCRIPTOR`
#: below; `M-JUDGE` never has to filter a descriptor (`CT-SETUP-06`).
SETUP_MAGNITUDE_PHRASES: tuple[str, ...] = (
    "good", "excellent", "weak", "adequate", "out of",
)

#: The bare-numeral arm of the magnitude bar (`FR-SETUP-05`): any digit in a descriptor
#: is a points scale leaking back into the language the judge sees.
_NUMERAL_IN_DESCRIPTOR = re.compile(r"\d")

#: The evidence-type default (`FR-SETUP-09`): what kind of textual evidence satisfies a
#: criterion the read back produces. The design pins no closed vocabulary — M-EXTRACT's
#: interface example names `textual_span`, the common case of evidence located in the
#: response's own text — so the read back attaches this when the model proposes none,
#: and stores whatever non-empty declaration it does propose.
SETUP_EVIDENCE_TYPE_DEFAULT = "textual_span"

#: The read-back's scoring-model vocabulary. The criterion DDL leaves scoring_model open
#: (its writers are trusted), but the design names exactly two models — `atomic` and
#: `holistic` (FR-SETUP-13, FR-AGG-06) — so the read back proposes within those and a
#: third name in a model reply is a schema-validation failure, re-requested.
SCORING_MODELS: tuple[str, ...] = ("atomic", "holistic")

# -- #52: the decomposability classification (FR-SETUP-06/-07/-08, §5.3) ------------------

#: The five HLD §5.3 questions, in the order the HLD names them. The classifier asks
#: the model for an ANSWER to each — never for a verdict — and this module's decision
#: table turns the answers into the classification (FR-SETUP-06: the table is the
#: module's, so a scripted verdict cannot pass through the model seam).
FIVE_QUESTIONS: tuple[str, ...] = (
    "completeness", "non_interference", "independence", "additivity", "gates",
)

#: The classification vocabulary (`CT-SETUP-04`): `atomic` (judged in isolation),
#: `atomic_with_gate` (judged in isolation once its gate holds), `holistic` (judged as
#: a whole). The criterion's stored `scoring_model` IS the classification (`FR-SETUP-08`
#: — panel depth and the auto-acceptance ceiling are functions of stored data, so
#: M-ORCH and M-AGG read a number, never a run-time branch).
CLASSIFICATIONS: tuple[str, ...] = ("atomic", "atomic_with_gate", "holistic")

#: The teacher-time cap (`FR-SETUP-07`, NFR-SETUP-01, Configuration §3.6):
#: `SETUP_MAX_CONFIRMATIONS` (6, Assumption (6), R9's budget) — at most this many
#: decomposability confirmations are REQUESTED per package, plus the two blocking
#: screens, and the cap is enforced by THIS module (`CT-SETUP-13`: headlessly, not by
#: the console). Env-gated so a slower pilot box can widen it without a code change;
#: read at import — the tests and the console read the module attribute, so the env
#: must be set before the process starts.
CONFIRMATIONS_ENV = "HARNESS_SETUP_MAX_CONFIRMATIONS"
CONFIRMATIONS_DEFAULT = 6


def _configured_max_confirmations() -> int:
    """The confirmation cap: the design's 6 unless the env widens or narrows it."""
    raw = os.environ.get(CONFIRMATIONS_ENV)
    if not raw:
        return CONFIRMATIONS_DEFAULT
    try:
        value = int(raw)
    except ValueError as error:
        raise SetupError(
            f"{CONFIRMATIONS_ENV}={raw!r} is not an integer."
        ) from error
    if value < 1:
        raise SetupError(
            f"{CONFIRMATIONS_ENV}={value} is below 1: a cap below one confirmation "
            "cannot surface even the first borderline criterion."
        )
    return value


SETUP_MAX_CONFIRMATIONS: int = _configured_max_confirmations()

#: The classify attempt budget (`CT-SETUP-12`'s rule at the classifier): a reply that
#: fails to parse or validate is re-requested up to this many times, then the verdict
#: degrades to the recorded default (`holistic`, surfaced) — degraded but complete.
#: Env-gated, read at CALL time (the knob doctrine).
CLASSIFY_ATTEMPTS_ENV = "HARNESS_SETUP_CLASSIFY_ATTEMPTS"
CLASSIFY_ATTEMPTS_DEFAULT = 3


def _configured_classify_attempts() -> int:
    """The classify attempt budget, read at call time — never at import."""
    raw = os.environ.get(CLASSIFY_ATTEMPTS_ENV)
    if not raw:
        return CLASSIFY_ATTEMPTS_DEFAULT
    try:
        value = int(raw)
    except ValueError as error:
        raise SetupError(
            f"{CLASSIFY_ATTEMPTS_ENV}={raw!r} is not an integer."
        ) from error
    if value < 1:
        raise SetupError(
            f"{CLASSIFY_ATTEMPTS_ENV}={value} is below 1: at least one classify "
            "attempt is required."
        )
    return value


#: The read-back attempt budget (`CT-SETUP-12`'s rule at the read back): a model reply
#: that fails to parse, to validate, or to clear the magnitude bar is re-requested up to
#: this many times, then the read back is recorded as `needs_manual_entry` — degraded
#: but complete. Env-gated, read at CALL time (the knob doctrine: per operation, not
#: per process load).
READBACK_ATTEMPTS_ENV = "HARNESS_SETUP_READBACK_ATTEMPTS"
READBACK_ATTEMPTS_DEFAULT = 3


def _configured_readback_attempts() -> int:
    """The read-back attempt budget, read at call time — never at import."""
    raw = os.environ.get(READBACK_ATTEMPTS_ENV)
    if not raw:
        return READBACK_ATTEMPTS_DEFAULT
    try:
        value = int(raw)
    except ValueError as error:
        raise SetupError(
            f"{READBACK_ATTEMPTS_ENV}={raw!r} is not an integer."
        ) from error
    if value < 1:
        raise SetupError(
            f"{READBACK_ATTEMPTS_ENV}={value} is below 1: at least one read-back "
            "attempt is required."
        )
    return value


class SetupError(Exception):
    """Base for every `M-SETUP` failure — the taxonomy is siblings, never a chain.

    Storage-layer errors (`M-PKG`'s) are deliberately NOT wrapped: they propagate
    unchanged (`CT-SETUP-12`), because a caller branching on a data-layer refusal
    needs the data-layer type, and re-raising it under a setup name would break that
    branch."""

    retryable = False


class SetupOrderError(SetupError):
    """A setup operation ran out of order, or a blocking gate was not yet satisfied
    (`§4.2.1`'s sequence): confirming before proposing, proposing after confirming,
    publishing before both blocking gates hold. The refusal names the gate and the
    step that unblocks it — the console renders this verbatim."""

    retryable = False


@dataclass(frozen=True)
class ProposedOption:
    """One option of a proposed `mcq`/`mixed` question, exactly as proposed.

    No correctness field — ADR-1's rule travels with the option set: correctness is
    the answer key, a separate blocking step (`FR-PKG-17`, S4)."""

    option_id: str
    ordinal: int
    label: str


@dataclass(frozen=True)
class ProposedQuestion:
    """One proposed question, exactly as the model proposed it (`FR-SETUP-01`): the
    prompt text verbatim, a `question_type` from `aeh.pkg.QUESTION_TYPES`, and the
    option set for any `mcq`/`mixed` question. The teacher confirms or corrects
    THIS — never a paraphrase."""

    question_id: str
    ordinal: int
    prompt_text: str
    question_type: str
    max_points: float
    options: tuple[ProposedOption, ...]


@dataclass(frozen=True)
class QuestionCorrection:
    """One teacher correction, applied at confirmation time.

    Actions: `set` patches fields of a proposed question; `remove` drops it;
    `add` contributes a question the model missed (and is the manual-entry vehicle
    that completes the degraded path, `CT-SETUP-12`: an `add` correction must carry
    `question_type` and `prompt_text`). Corrections apply BEFORE the write — after
    confirmation the inventory is locked (`FR-SETUP-02`) and this module offers no
    edit at all."""

    question_id: str
    action: str = "set"
    question_type: str | None = None
    prompt_text: str | None = None
    ordinal: int | None = None
    max_points: float | None = None
    options: tuple[ProposedOption, ...] | None = None


@dataclass(frozen=True)
class InventoryProposal:
    """The proposal a version holds, as rebuilt from its stored row.

    `status` is the payload's own word for how it got here: `proposed` (awaiting the
    teacher) or `needs_manual_entry` (the degraded path: the model's replies never
    parsed, the questions are empty, the teacher enters them as `add` corrections —
    degraded but complete, `CT-SETUP-12`). It never becomes "confirmed" — confirmation
    is not a payload word but the row's `confirmed_at` column, and this object's
    `confirmed` flag is the signal for it (the payload is frozen at confirm time; the
    column is what the §6.2 lock keys on). `attempts` is how many model calls
    the stored proposal cost, `model_ref` the build that actually answered
    (`FR-PROV-04`), `template_version` the pinned prompt that asked (`TC-SETUP-22`)."""

    proposal_id: str
    assessment_doc_id: DocumentId
    package_version_id: PackageVersionId
    template_version: str
    model_ref: str
    attempts: int
    questions: tuple[ProposedQuestion, ...]
    status: str
    confirmed_at: str | None = None

    @property
    def confirmed(self) -> bool:
        return self.confirmed_at is not None

    def entry(self, question_id: str) -> ProposedQuestion | None:
        for question in self.questions:
            if question.question_id == question_id:
                return question
        return None


@dataclass(frozen=True)
class ProposedBand:
    """One band of a read-back criterion, in the STORED order — ordinals contiguous
    from 0, points non-decreasing (`FR-PKG-06`'s order half), so the band a judge can
    retreat to is the LOW one, never a safe middle. The model ranks bands best-first;
    `read_back_rubric` fixes the ordering on read-back, which is the order §3.6's
    Requires table assigns to this module."""

    band: str
    ordinal: int
    points: float
    descriptor: str


@dataclass(frozen=True)
class CriterionDraft:
    """One criterion as the read back proposes it — the draft #52's decomposability
    classification consumes and the teacher's confirmation makes the package's content.

    `construct` is the criterion's own behavioural text as read from the rubric;
    `band_count` is EVEN in 2..6 (`FR-SETUP-04`); `bands` are `ProposedBand`s in stored
    order; `justification` records why the band set exceeds the two-band default
    (partial credit genuinely part of the construct) and is empty exactly when
    `band_count == SETUP_DEFAULT_BAND_COUNT`; `evidence_type` declares what kind of
    textual evidence satisfies the criterion (`FR-SETUP-09` — M-INTEG routes on it,
    FR-INTEG-03)."""

    criterion_id: str
    question_id: str
    kind: str
    scoring_model: str
    max_points: float
    construct: str
    band_count: int
    bands: tuple[ProposedBand, ...]
    justification: str = ""
    evidence_type: str = SETUP_EVIDENCE_TYPE_DEFAULT
    #: `proposed` when the model proposed the band set, `derived_default` when the
    #: module derived the two-band met / not-met set (`FR-SETUP-14`: a default taken
    #: is recorded, not indistinguishable from an explicit choice).
    bands_source: str = "proposed"
    #: `#52` (`FR-SETUP-06`): which §5.3 question decided the scoring model the read
    #: back wrote, when the reply carried the answers for the table to decide — the
    #: name of the deciding question, or "" when nothing did (all answers pass; the
    #: unclear default applied). The audit field beside `scoring_model`, not a
    #: separate scoring input.
    decomposition_basis: str = ""
    #: `#52` (`FR-SETUP-07`): the table's verdict for this criterion was BORDERLINE —
    #: an unclear answer or a warning sign — so it belongs to the confirmation
    #:`surface and counts against `SETUP_MAX_CONFIRMATIONS`. Set at parse time
    #: (it is the reply's property, not stored state); the service applies the cap.
    needs_confirmation: bool = False


@dataclass(frozen=True)
class RubricReadback:
    """The read back a version holds, as rebuilt from its stored row.

    `status` is the payload's own word: `proposed` (criteria and bands written to the
    draft, awaiting #52's classification and the teacher's confirmation) or
    `needs_manual_entry` (the degraded path: every reply failed to parse, to validate,
    or to clear the magnitude bar within the attempt budget — degraded but complete,
    `CT-SETUP-12`, with the last error in `reason`). `attempts` is how many model calls
    the stored read back cost, `model_ref` the build that answered (`FR-PROV-04`),
    `template_version` the pinned prompt that asked (`NFR-SETUP-03`)."""

    rubric_doc_id: DocumentId
    assessment_doc_id: DocumentId
    package_version_id: PackageVersionId
    template_version: str
    model_ref: str
    attempts: int
    criteria: tuple[CriterionDraft, ...]
    status: str
    reason: str = ""

    def entry(self, criterion_id: str) -> CriterionDraft | None:
        for criterion in self.criteria:
            if criterion.criterion_id == criterion_id:
                return criterion
        return None


# -- #52: the decomposability decision table and its verdict (FR-SETUP-06/-07/-08) --------


def _classify_answers(
    answers: Mapping[str, Any],
) -> tuple[str, str | None]:
    """The five-question decision table — THE module's, not the model's (`FR-SETUP-06`).

    The model answers the §5.3 questions; this table turns answers into a
    classification. Scanned in the HLD's order, the first `no` decides: `gates`
    failing names `atomic_with_gate` (the criterion is judged in isolation once its
    gate holds), any other question failing names `holistic` (the construct does not
    survive being cut apart). With no `no` anywhere, an `unclear` answer — or an
    answer the vocabulary does not name, which IS unclear — applies NFR-SETUP-02's
    asymmetric default: `holistic`, never `atomic` (RISK-27: a default of `atomic`
    would hand the criterion panel depth 1 and a higher auto-acceptance ceiling than
    it deserves, and nothing downstream would notice). All answers pass and none is
    unclear: `atomic` — the one classification the table grants, never the default.

    Returns `(classification, deciding_question)`; the deciding question is None
    exactly when nothing decided (the all-pass cell and the default cell)."""
    for question in FIVE_QUESTIONS:
        if str(answers.get(question, "")).strip().lower() == "no":
            if question == "gates":
                return "atomic_with_gate", question
            return "holistic", question
    for question in FIVE_QUESTIONS:
        if str(answers.get(question, "")).strip().lower() != "yes":
            return "holistic", None
    return "atomic", None


@dataclass(frozen=True)
class DecomposabilityVerdict:
    """One criterion's decomposability outcome (`§3.6`'s Interface, `#52`).

    `classification` is one of `atomic` / `atomic_with_gate` / `holistic`;
    `deciding_question` names WHICH §5.3 question decided it — the audit field
    `decomposition_basis` records (`FR-SETUP-06`), None exactly when nothing decided.
    `reasoning` is the module's own statement of why, carrying the model's answer set;
    `needs_teacher_confirmation` is the surfacing half of `FR-SETUP-07` — true for the
    borderline criteria (an unclear answer anywhere) and the warning-sign criteria, as
    the confirmation cap allows, because the teacher's time is the budget
    (`NFR-SETUP-01`)."""

    classification: str
    deciding_question: str | None
    reasoning: str
    needs_teacher_confirmation: bool


@dataclass(frozen=True)
class DependencyProposal:
    """One proposed criterion dependency (`FR-SETUP-10`, `#52`) — a PROPOSAL, never a
    write: every criterion defaults to zero dependencies, and an edge exists only once
    the teacher explicitly approves it (`CT-SETUP-08`).

    `str()` renders the plain language `FR-SETUP-10` demands — both criteria named,
    the proposal's own reason carried, no payload syntax: a teacher reads a sentence,
    not a dict."""

    criterion_id: str
    depends_on: str
    reason: str

    def __str__(self) -> str:
        return (
            f"When grading {self.criterion_id}, the grader will also see the work you "
            f"credited under {self.depends_on}, because {self.reason.rstrip('.')}."
        )


@dataclass(frozen=True)
class SetupStep:
    """One setup step as the console renders it (`NFR-SETUP-04`, `FR-CONSOLE-25`).

    A step that is not `available` yet is present-and-unavailable: the list names it
    and its staging story, so the teacher sees the whole sequence without being
    offered an operation that does not exist. `publish` is not a step — it is the
    gate point the blocking steps hold shut."""

    step_id: str
    name: str
    blocking: bool
    available: bool
    done: bool
    note: str = ""


@dataclass(frozen=True)
class SetupProgress:
    """The setup state of one package version, structured for the console and the
    headless driver: the enumerated steps, the honest remaining count (steps that are
    available and not done), and whether `publish`'s two gates would pass right now."""

    package_version_id: PackageVersionId | None
    steps: tuple[SetupStep, ...]
    remaining_steps: int
    ready_to_publish: bool

    def headline(self) -> str:
        """The console's one-line state (`NFR-SETUP-04`): `setup incomplete — N steps
        remain`, the ready line, or — with no draft version — the finished/not-started
        line. A zero that is NOT a lie reads `ready`, because a count of remaining
        steps that no one can act on is the console lying."""
        if self.ready_to_publish:
            return f"setup complete for {self.package_version_id!r} — ready to publish"
        if self.package_version_id is None and self.remaining_steps == 0:
            return ("setup has finished for this package (its version is published); "
                    "a new instrument is a new package or a revision (FR-PKG-02)")
        if self.package_version_id is None:
            return ("setup has not started — no draft version exists yet; "
                    f"{self.remaining_steps} step(s) remain (the question inventory)")
        return (
            f"setup incomplete — {self.remaining_steps} step(s) remain for "
            f"{self.package_version_id!r}"
        )


_INVENTORY_INSTRUCTION = (
    "You are reading one assessment document and proposing the question inventory a "
    "grading package will be built from (HLD §7.8, Phase 1 — propose once, from the "
    "document alone). For every question the document asks:\n"
    "- question_type is 'mcq' when the question enumerates options or answer markers "
    "(lettered options, checkboxes, a 'circle one' instruction); 'open' when it names "
    "a ruled response area with nothing to mark; 'mixed' when one question carries "
    "both a marked part and a written part.\n"
    "- For every mcq or mixed question include the full option set exactly as "
    "printed, one entry per option, with the option's printed id and label.\n"
    "- Copy prompt_text verbatim from the document; set ordinal to the question's "
    "printed number and max_points to its printed marks (0 when the document shows "
    "none).\n"
    "- Propose only what the document contains: no invented questions, no merged or "
    "split questions, and no answer key — the teacher declares keys in a separate "
    "blocking step.\n"
    "Reply with ONLY a JSON object, no prose, of this shape — note an open question "
    "carries an EMPTY options list, and only mcq/mixed carry entries in it:\n"
    '{"questions": [{"question_id": "Q1", "ordinal": 1, "prompt_text": "...", '
    '"question_type": "open", "max_points": 4, "options": []}, '
    '{"question_id": "Q2", "ordinal": 2, "prompt_text": "...", '
    '"question_type": "mcq", "max_points": 2, "options": [{"option_id": "A", '
    '"ordinal": 0, "label": "..."}]}]}'
)

_READBACK_INSTRUCTION = (
    "You are reading one rubric document and proposing the criteria and band sets a "
    "grading package will judge against (HLD §7.8, Phase 1 — read back, never improve: "
    "correcting a rubric is a gated, separate step the teacher owns). Anchor every "
    "criterion to a question the confirmed inventory carries.\n"
    "- kind is 'open' when the criterion judges written work, 'mcq' when it judges a "
    "marked choice; scoring_model is 'atomic' when the criterion stands alone, "
    "'holistic' when it can only be judged as a whole.\n"
    "- band_count must be an EVEN number in 2..6. Omit it and bands entirely when the "
    "criterion is a met / not met judgment — the two-band default is derived for you.\n"
    "- Propose explicit bands ONLY where partial credit is genuinely part of the "
    "construct, and then carry a 'justification' string saying what earns the partial "
    "credit.\n"
    "- Rank bands BEST-FIRST: ordinal 1 is the best band, and points descend to the "
    "worst. The stored ordering is fixed afterwards; your ranking is what is read.\n"
    "- Every band descriptor must state what a response IN THAT BAND DOES — the "
    "observable action, not a quality judgment. NEVER use the words good, excellent, "
    "weak, adequate, or 'out of', and never write a numeral anywhere in a descriptor: "
    "a descriptor containing a number is a points scale leaking into the language the "
    "judge sees, and it will be rejected.\n"
    "- evidence_type names what kind of textual evidence satisfies the criterion "
    "(omit it to take the default).\n"
    "Reply with ONLY a JSON object, no prose, of this shape:\n"
    '{"criteria": [{"criterion_id": "CRIT-1", "question_id": "Q1", "kind": "open", '
    '"scoring_model": "holistic", "max_points": 4, '
    '"construct": "what the criterion asks for, behaviourally", '
    '"evidence_type": "textual_span", '
    '"bands": [{"band": "met", "ordinal": 1, "points": 4, "descriptor": "the response '
    'does ..."}, {"band": "not met", "ordinal": 2, "points": 0, "descriptor": "the '
    'response does not ..."}]}]}'
)

_CLASSIFY_INSTRUCTION = (
    "You are answering the five decomposability questions for ONE grading criterion "
    "(HLD §5.3): they decide whether a judge can score this criterion in isolation on "
    "one response, or only as a whole. Do NOT classify the criterion yourself — answer "
    "the questions; the system applies the decision table.\n"
    "Answer each question 'yes', 'no', or 'unclear':\n"
    "- completeness: is everything the criterion judges present in the response "
    "segment it is scored on, on its own?\n"
    "- non_interference: can the criterion's evidence be gathered without being "
    "distorted by how another criterion's evidence is gathered?\n"
    "- independence: does the judgment not depend on the outcome of another "
    "criterion's judgment?\n"
    "- additivity: can the criterion's score be combined additively with the others "
    "without double counting or interaction effects?\n"
    "- gates: can the criterion be scored with NO precondition (a gate) that has "
    "to hold before it can be scored at all? Answer 'no' when such a gate exists — "
    "every question here is phrased so that 'yes' means the criterion passes it, "
    "and the decision table reads a 'no' on gates as 'this criterion carries a "
    "gate'.\n"
    "- warning_signs: list anything about the criterion that warns against decomposing "
    "it (straddling two constructs, mixed scales, ...); an empty list when none.\n"
    "Use 'unclear' whenever the criterion's text does not settle a question — never "
    "guess.\n"
    "Reply with ONLY a JSON object, no prose, of this shape:\n"
    '{"criterion_id": "CRIT-1", "answers": {"completeness": "yes", '
    '"non_interference": "yes", "independence": "unclear", "additivity": "no", '
    '"gates": "yes"}, "warning_signs": ["straddles two constructs"], '
    '"reasoning": "what the criterion text shows for the answers given"}'
)

_DEPENDENCIES_INSTRUCTION = (
    "You are proposing criterion dependencies for a grading package (FR-SETUP-10). A "
    "dependency makes one criterion's grading SEE the evidence credited under another "
    "criterion — a contamination channel that must earn its place — so propose an edge "
    "ONLY where the subject itself makes error-carried-forward likely (a later "
    "criterion graded on work that presupposes an earlier criterion's construct). "
    "Every criterion you do not name keeps its default of zero dependencies.\n"
    "- criterion_id is the LATER criterion whose grading would see the earlier work; "
    "depends_on is the EARLIER one whose credited work it presupposes.\n"
    "- reason states, in the subject's own terms, what the later criterion's grading "
    "presupposes.\n"
    "Reply with ONLY a JSON object, no prose, of this shape — an empty list when "
    "nothing is likely:\n"
    '{"dependencies": [{"criterion_id": "CRIT-4", "depends_on": "CRIT-2", '
    '"reason": "error carried forward: the derivation is graded on work that '
    'presupposes the definition"}]}'
)


def _now() -> str:
    """The confirmation stamp. UTC ISO — the same shape the store's
    `datetime('now')` stamps carry (which are UTC), so one column sorts cleanly."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _ReplyError(Exception):
    """A model reply that did not parse into a valid proposal. PRIVATE on purpose:
    it is the retried failure (`CT-SETUP-12`), never surfaced — the caller sees the
    re-request, or the degraded proposal with the last error recorded in it."""


def _parse_reply(text: str) -> tuple[ProposedQuestion, ...]:
    """Parse the model's reply into proposed questions, raising `_ReplyError` on
    anything that is not a valid inventory — the failure the attempt loop re-requests.
    The reply is expected to be one JSON object; prose around it is tolerated (models
    add it), JSON-shaped text that is not an inventory is not."""
    stripped = text.strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start < 0 or end <= start:
        raise _ReplyError("the reply contains no JSON object.")
    try:
        parsed = json.loads(stripped[start:end + 1])
    except ValueError as error:
        raise _ReplyError(f"the reply is not valid JSON: {error}") from error
    if not isinstance(parsed, dict) or not isinstance(parsed.get("questions"), list):
        raise _ReplyError("the reply's JSON does not carry a 'questions' list.")
    if not parsed["questions"]:
        raise _ReplyError(
            "the reply proposes zero questions — the document asks something; an "
            "empty inventory is not a proposal."
        )
    questions: list[ProposedQuestion] = []
    seen_ids: set[str] = set()
    seen_ordinals: set[int] = set()
    for index, raw in enumerate(parsed["questions"]):
        if not isinstance(raw, dict):
            raise _ReplyError(f"question #{index} is not an object.")
        question_id = raw.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            raise _ReplyError(f"question #{index}: question_id must be a non-empty string.")
        if question_id in seen_ids:
            raise _ReplyError(f"question #{index}: duplicate question_id {question_id!r}.")
        seen_ids.add(question_id)
        ordinal = raw.get("ordinal")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
            raise _ReplyError(
                f"question {question_id!r}: ordinal must be a non-negative integer, "
                f"got {ordinal!r}."
            )
        if ordinal in seen_ordinals:
            raise _ReplyError(
                f"question {question_id!r}: duplicate ordinal {ordinal} — two "
                "questions cannot share a position."
            )
        seen_ordinals.add(ordinal)
        prompt_text = raw.get("prompt_text")
        if not isinstance(prompt_text, str) or not prompt_text.strip():
            raise _ReplyError(f"question {question_id!r}: prompt_text must be non-empty.")
        question_type = raw.get("question_type")
        if question_type not in QUESTION_TYPES:
            raise _ReplyError(
                f"question {question_id!r}: question_type {question_type!r} is outside "
                f"the vocabulary {QUESTION_TYPES} (FR-SETUP-01)."
            )
        max_points = raw.get("max_points", 0.0)
        if isinstance(max_points, bool) or not isinstance(max_points, (int, float)):
            raise _ReplyError(
                f"question {question_id!r}: max_points must be a number, got "
                f"{max_points!r}."
            )
        raw_options = raw.get("options", [])
        if not isinstance(raw_options, list):
            raise _ReplyError(f"question {question_id!r}: options must be a list.")
        options: list[ProposedOption] = []
        option_ids: set[str] = set()
        option_ordinals: set[int] = set()
        for option_index, raw_option in enumerate(raw_options):
            if not isinstance(raw_option, dict):
                raise _ReplyError(
                    f"question {question_id!r} option #{option_index} is not an object."
                )
            option_id = raw_option.get("option_id")
            label = raw_option.get("label")
            if not isinstance(option_id, str) or not option_id.strip():
                raise _ReplyError(
                    f"question {question_id!r} option #{option_index}: option_id must "
                    "be a non-empty string."
                )
            if option_id in option_ids:
                raise _ReplyError(
                    f"question {question_id!r}: duplicate option_id {option_id!r}."
                )
            if not isinstance(label, str) or not label.strip():
                raise _ReplyError(
                    f"question {question_id!r} option {option_id!r}: label must be "
                    "non-empty."
                )
            option_ordinal = raw_option.get("ordinal", option_index)
            if (not isinstance(option_ordinal, int) or isinstance(option_ordinal, bool)
                    or option_ordinal < 0):
                raise _ReplyError(
                    f"question {question_id!r} option {option_id!r}: ordinal must be "
                    f"a non-negative integer, got {option_ordinal!r}."
                )
            if option_ordinal in option_ordinals:
                raise _ReplyError(
                    f"question {question_id!r}: duplicate option ordinal "
                    f"{option_ordinal} — two options cannot share a position."
                )
            option_ordinals.add(option_ordinal)
            option_ids.add(option_id)
            options.append(ProposedOption(option_id=option_id,
                                          ordinal=option_ordinal, label=label))
        if question_type in ("mcq", "mixed") and not options:
            raise _ReplyError(
                f"question {question_id!r} is {question_type} but proposes no options "
                "— the teacher would have nothing to mark (FR-SETUP-01)."
            )
        if question_type == "open" and options:
            raise _ReplyError(
                f"question {question_id!r} is open but carries {len(options)} "
                "option(s) — a typed mismatch is a proposal bug, not a content choice."
            )
        questions.append(ProposedQuestion(
            question_id=question_id, ordinal=ordinal, prompt_text=prompt_text,
            question_type=question_type, max_points=float(max_points),
            options=tuple(options),
        ))
    return tuple(questions)


def _question_to_dict(question: ProposedQuestion) -> dict:
    """The catalog's record shape for `write_confirmed_inventory` — plain mappings,
    because the data layer does not import this module's types."""
    return {
        "question_id": question.question_id,
        "ordinal": question.ordinal,
        "prompt_text": question.prompt_text,
        "question_type": question.question_type,
        "max_points": question.max_points,
        "options": [
            {"option_id": option.option_id, "ordinal": option.ordinal,
             "label": option.label}
            for option in question.options
        ],
    }


def _assert_confirmed_shape(questions: Sequence[ProposedQuestion]) -> None:
    """Re-validate AFTER corrections (`CT-PKG-12` in setup's own voice): a correction
    set can collide ordinals or duplicate ids that the proposal alone never had. The
    catalog re-validates at the write (`InventoryError`); this pre-check keeps the
    failure in setup's taxonomy with the correction named."""
    if not questions:
        raise SetupError(
            "a confirmed inventory carries at least one question — the corrections "
            "removed every proposed question. Add one (the manual-entry path) or "
            "confirm the proposal unmodified."
        )
    seen_ids: set[str] = set()
    seen_ordinals: set[int] = set()
    for question in questions:
        if question.question_id in seen_ids:
            raise SetupError(
                f"correction produced a duplicate question_id {question.question_id!r}."
            )
        seen_ids.add(question.question_id)
        if question.ordinal in seen_ordinals:
            raise SetupError(
                f"correction produced a duplicate ordinal {question.ordinal} "
                f"(question {question.question_id!r}) — two questions cannot share a "
                "position."
            )
        seen_ordinals.add(question.ordinal)
        if question.question_type not in QUESTION_TYPES:
            raise SetupError(
                f"correction set question {question.question_id!r} to question_type "
                f"{question.question_type!r}, outside the vocabulary {QUESTION_TYPES}."
            )
        if question.question_type in ("mcq", "mixed") and not question.options:
            raise SetupError(
                f"correction left {question.question_type} question "
                f"{question.question_id!r} without options — the teacher would have "
                "nothing to mark."
            )
        if question.question_type == "open" and question.options:
            raise SetupError(
                f"correction left open question {question.question_id!r} with an "
                "option set — a typed mismatch is a correction bug, not a content "
                "choice."
            )


def _proposal_from_row(v: PackageVersionId, row: Mapping[str, Any]) -> InventoryProposal:
    """Rebuild the stored proposal — the resume path's read (`CT-SETUP-03`: state is
    the database). The payload's entries become `ProposedQuestion`s verbatim; a
    malformed stored payload raises `SetupError` naming the corruption rather than
    silently re-proposing over it."""
    try:
        payload = json.loads(row["payload"])
        entries = payload["entries"]
        status = payload["status"]
    except (ValueError, KeyError, TypeError) as error:
        raise SetupError(
            f"the stored proposal for version {v!r} is malformed ({error}) — the "
            "payload is provenance and is not silently replaced; delete the version "
            "and run setup again."
        ) from error
    questions = tuple(
        ProposedQuestion(
            question_id=str(entry["question_id"]),
            ordinal=int(entry["ordinal"]),
            prompt_text=str(entry["prompt_text"]),
            question_type=str(entry["question_type"]),
            max_points=float(entry.get("max_points", 0.0)),
            options=tuple(
                ProposedOption(option_id=str(option["option_id"]),
                               ordinal=int(option["ordinal"]),
                               label=str(option["label"]))
                for option in entry.get("options", ())
            ),
        )
        for entry in entries
    )
    return InventoryProposal(
        proposal_id=str(row["proposal_id"]),
        assessment_doc_id=str(row["assessment_doc_id"]),
        package_version_id=v,
        template_version=str(row["template_version"]),
        model_ref=str(row["model_ref"]),
        attempts=int(row["attempts"]),
        questions=questions,
        status=status,
        confirmed_at=row["confirmed_at"],
    )


# --- the rubric read-back (FR-SETUP-04/-05/-09, #51) --------------------------------------------
#
# The read back turns the rubric artifact into criterion drafts with band sets. Two
# rules carry the design's teeth:
#
#   * the magnitude bar (`FR-SETUP-05`): a band descriptor matching
#     `SETUP_MAGNITUDE_PHRASES` — or containing any digit — is a schema-validation
#     failure of the reply, re-requested within the attempt budget, never stored. The
#     rejection is the point: judges see descriptors, not a points scale in disguise.
#   * the band-order fix (`FR-PKG-06`'s order half): the model ranks bands best-first
#     (ordinal 1 = best, points descending); the STORED order is points-ascending with
#     ordinals contiguous from 0, because the band a judge can retreat to must be the
#     LOW one. §3.6's Requires table assigns that fix to this module: "band ordering is
#     fixed on read-back".
#
# A criterion whose construct carries no partial credit arrives with no bands at all
# (the common real case, §3.6's open question): the module derives the default two-band
# met / not-met set anchored on the criterion's own text.


def _descriptor_offense(text: str) -> str | None:
    """What the magnitude bar finds in one descriptor, or None: a configured phrase
    (case-insensitive substring) or any digit. The message names the match — it is the
    re-request's reason and the log line the operator reads."""

    lowered = text.lower()
    for phrase in SETUP_MAGNITUDE_PHRASES:
        if phrase.lower() in lowered:
            return f"the magnitude phrase {phrase!r}"
    numeral = _NUMERAL_IN_DESCRIPTOR.search(text)
    if numeral:
        return f"a bare numeral ({numeral.group(0)!r})"
    return None


def _derived_default_bands(construct: str, max_points: float) -> tuple[ProposedBand, ...]:
    """The two-band default (`FR-SETUP-04`): met / not met, anchored on the criterion's
    own text — the met band's descriptor IS the construct (the rubric's behavioural
    sentence, not a magnitude word), the not-met band states what falls outside it.
    Derived descriptors pass the same magnitude bar as proposed ones: if the construct
    itself carries a phrase or a numeral, the reply is rejected and re-requested — the
    model is asked for a cleaner statement of the construct."""

    met = construct.strip()
    not_met = f"the response does not do what the criterion describes ({met})"
    return (
        ProposedBand(band="not met", ordinal=0, points=0.0, descriptor=not_met),
        ProposedBand(band="met", ordinal=1, points=max_points, descriptor=met),
    )


def _normalize_bands(raw_bands: Sequence[Mapping], construct: str,
                     max_points: float) -> tuple[ProposedBand, ...]:
    """Fix the band ordering on read-back (`FR-PKG-06`'s order half): sort by points
    ascending — the reply's own order breaking ties, so the model's ranking survives
    a flat band set — and re-base the ordinals to contiguous-from-0. The reply's
    descriptor content has already cleared the magnitude bar before this runs.

    The reply's bands are typed into `ProposedBand` FIRST and ordered through the
    attribute: this module orders and writes band points, it never reads a stored band
    row to map a band to a score — that mapping is `points_for_band`'s alone
    (`TC-PKG-C05`, RISK-05), and the typed shape is what keeps the two apart."""

    typed = tuple(
        ProposedBand(band=str(band["band"]), ordinal=int(band["ordinal"]),
                     points=float(band.get("points", 0.0)),
                     descriptor=str(band["descriptor"]))
        for band in raw_bands
    )
    ordered = sorted(enumerate(typed), key=lambda pair: (pair[1].points, pair[0]))
    return tuple(
        ProposedBand(band=band.band, ordinal=fixed_ordinal, points=band.points,
                     descriptor=band.descriptor)
        for fixed_ordinal, (_reply_ordinal, band) in enumerate(ordered)
    )


def _parse_readback_reply(
    text: str, confirmed_ids: Mapping[str, Mapping],
) -> tuple[CriterionDraft, ...]:
    """Parse the model's read-back reply into criterion drafts, raising `_ReplyError`
    on anything that is not a valid read-back — the failure the attempt loop
    re-requests. Validity here is the whole bar: schema fields, the band rules
    (`FR-PKG-06`'s count half), the justification rule (`FR-SETUP-04`), and the
    magnitude scan (`FR-SETUP-05`) over every proposed AND derived descriptor — the
    stored set must be clean whatever produced it."""

    stripped = text.strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start < 0 or end <= start:
        raise _ReplyError("the reply contains no JSON object.")
    try:
        parsed = json.loads(stripped[start:end + 1])
    except ValueError as error:
        raise _ReplyError(f"the reply is not valid JSON: {error}") from error
    if not isinstance(parsed, dict) or not isinstance(parsed.get("criteria"), list):
        raise _ReplyError("the reply's JSON does not carry a 'criteria' list.")
    if not parsed["criteria"]:
        raise _ReplyError(
            "the reply proposes zero criteria — a rubric read back that reads nothing "
            "is not a read back."
        )
    drafts: list[CriterionDraft] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(parsed["criteria"]):
        if not isinstance(raw, dict):
            raise _ReplyError(f"criterion #{index} is not an object.")
        criterion_id = raw.get("criterion_id")
        if not isinstance(criterion_id, str) or not criterion_id.strip():
            raise _ReplyError(
                f"criterion #{index}: criterion_id must be a non-empty string."
            )
        if criterion_id in seen_ids:
            raise _ReplyError(
                f"criterion #{index}: duplicate criterion_id {criterion_id!r}."
            )
        seen_ids.add(criterion_id)
        question_id = raw.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            raise _ReplyError(
                f"criterion {criterion_id!r}: question_id must be a non-empty string."
            )
        if question_id not in confirmed_ids:
            raise _ReplyError(
                f"criterion {criterion_id!r}: question_id {question_id!r} is not in "
                "the CONFIRMED inventory — criteria anchor to confirmed questions "
                "(FR-SETUP-02), and an invented anchor is a proposal bug."
            )
        kind = raw.get("kind")
        if kind not in ("open", "mcq"):
            raise _ReplyError(
                f"criterion {criterion_id!r}: kind {kind!r} is outside the vocabulary "
                "('open', 'mcq')."
            )
        scoring_model = raw.get("scoring_model")
        decomposition_basis = ""
        needs_confirmation = False
        if scoring_model is None:
            # #52 (`FR-SETUP-06`/`-08`): the reply carried the §5.3 ANSWERS (or none at
            # all) and no scoring model — the classification is the module's table, not
            # the reply's word. An `mcq` criterion is FR-SETUP-13's: never submitted to
            # the §5.3 test, `atomic` outright. Anything else is the table over whatever
            # answers the reply carried — an absent answer set is the unclear case, and
            # the default is `holistic`, never `atomic` (NFR-SETUP-02, RISK-27).
            if kind == "mcq":
                scoring_model = "atomic"
            else:
                raw_answers = raw.get("answers")
                raw_answers = raw_answers if isinstance(raw_answers, dict) else {}
                scoring_model, decided = _classify_answers(raw_answers)
                decomposition_basis = decided or ""
                # The same refusal the classifier applies (`_verdict_from_answers`):
                # a warning sign with every answer passing refuses the atomic grant,
                # and a borderline verdict — unclear answers OR warning signs — is
                # surfaced for the teacher and counted against the cap by the
                # service (`_request_confirmation`). A read-back reply must not be
                # a second classification surface that quietly escapes FR-SETUP-07.
                raw_warnings = raw.get("warning_signs", [])
                warning_signs = ([str(item) for item in raw_warnings
                                  if str(item).strip()]
                                 if isinstance(raw_warnings, list) else [])
                if decided is None and scoring_model == "atomic" and warning_signs:
                    scoring_model = "holistic"
                    decomposition_basis = ""
                needs_confirmation = (
                    decided is None
                    and any(str(raw_answers.get(question, "")).strip().lower()
                            not in ("yes", "no") for question in FIVE_QUESTIONS)
                ) or bool(warning_signs)
        elif scoring_model not in SCORING_MODELS:
            raise _ReplyError(
                f"criterion {criterion_id!r}: scoring_model {scoring_model!r} is "
                f"outside the vocabulary {SCORING_MODELS} (FR-SETUP-13, FR-AGG-06)."
            )
        max_points = raw.get("max_points", 0.0)
        if isinstance(max_points, bool) or not isinstance(max_points, (int, float)):
            raise _ReplyError(
                f"criterion {criterion_id!r}: max_points must be a number, got "
                f"{max_points!r}."
            )
        if max_points < 0:
            raise _ReplyError(
                f"criterion {criterion_id!r}: max_points {max_points} is negative."
            )
        if not math.isfinite(max_points):
            raise _ReplyError(
                f"criterion {criterion_id!r}: max_points {max_points} is not a finite "
                "number — NaN would fail the band write outright and an infinity would "
                "make every band unreachable."
            )
        construct = raw.get("construct")
        if not isinstance(construct, str) or not construct.strip():
            raise _ReplyError(
                f"criterion {criterion_id!r}: construct must be non-empty — the "
                "criterion's own behavioural text is what the default band set "
                "anchors on."
            )
        raw_bands = raw.get("bands", [])
        if not isinstance(raw_bands, list):
            raise _ReplyError(f"criterion {criterion_id!r}: bands must be a list.")
        band_count = raw.get("band_count", len(raw_bands) or SETUP_DEFAULT_BAND_COUNT)
        if (not isinstance(band_count, int) or isinstance(band_count, bool)
                or band_count < 2 or band_count > 6 or band_count % 2 != 0):
            raise _ReplyError(
                f"criterion {criterion_id!r}: band_count {band_count!r} is odd or "
                "outside 2..6 (FR-SETUP-04). The even count removes the safe middle "
                "band a hesitant judge retreats to (design §5.10, R40)."
            )
        justification = raw.get("justification", "")
        if justification is None:
            justification = ""
        if not isinstance(justification, str):
            raise _ReplyError(
                f"criterion {criterion_id!r}: justification must be a string."
            )
        if band_count > SETUP_DEFAULT_BAND_COUNT and not justification.strip():
            raise _ReplyError(
                f"criterion {criterion_id!r}: band_count {band_count} exceeds the "
                "two-band default without a justification (FR-SETUP-04) — partial "
                "credit that is genuinely part of the construct is recorded, not "
                "silent."
            )
        evidence_type = raw.get("evidence_type")
        if evidence_type is None:
            evidence_type = SETUP_EVIDENCE_TYPE_DEFAULT
        if not isinstance(evidence_type, str) or not evidence_type.strip():
            raise _ReplyError(
                f"criterion {criterion_id!r}: evidence_type, when given, must be a "
                "non-empty string (FR-SETUP-09) — a declaration of nothing satisfies "
                "no criterion."
            )
        if raw_bands:
            if len(raw_bands) != band_count:
                raise _ReplyError(
                    f"criterion {criterion_id!r}: {len(raw_bands)} band(s) proposed "
                    f"against a declared band_count of {band_count}."
                )
            for band_index, raw_band in enumerate(raw_bands):
                if not isinstance(raw_band, dict):
                    raise _ReplyError(
                        f"criterion {criterion_id!r} band #{band_index} is not an "
                        "object."
                    )
                label = raw_band.get("band")
                if not isinstance(label, str) or not label.strip():
                    raise _ReplyError(
                        f"criterion {criterion_id!r} band #{band_index}: band label "
                        "must be non-empty."
                    )
                points = raw_band.get("points", 0.0)
                if isinstance(points, bool) or not isinstance(points, (int, float)):
                    raise _ReplyError(
                        f"criterion {criterion_id!r} band {label!r}: points must be "
                        f"a number, got {points!r}."
                    )
                if points < 0:
                    raise _ReplyError(
                        f"criterion {criterion_id!r} band {label!r}: points "
                        f"{points} is negative."
                    )
                if not math.isfinite(points):
                    raise _ReplyError(
                        f"criterion {criterion_id!r} band {label!r}: points {points} "
                        "is not a finite number — the JSON decoder accepts NaN and "
                        "Infinity, and neither is a points value a band can carry."
                    )
                descriptor = raw_band.get("descriptor")
                if not isinstance(descriptor, str) or not descriptor.strip():
                    raise _ReplyError(
                        f"criterion {criterion_id!r} band {label!r}: descriptor must "
                        "state what a response in that band DOES — an empty "
                        "descriptor states nothing."
                    )
                offense = _descriptor_offense(descriptor)
                if offense:
                    raise _ReplyError(
                        f"criterion {criterion_id!r} band {label!r}: its descriptor "
                        f"carries {offense} (FR-SETUP-05) — judges see what a "
                        "response does, never a quality word or a points scale."
                    )
            bands = _normalize_bands(raw_bands, construct, float(max_points))
            bands_source = "proposed"
        else:
            if band_count != SETUP_DEFAULT_BAND_COUNT:
                raise _ReplyError(
                    f"criterion {criterion_id!r}: no bands proposed but band_count "
                    f"{band_count} is not the default — propose the bands or omit "
                    "the count."
                )
            bands = _derived_default_bands(construct, float(max_points))
            bands_source = "derived_default"
            for band in bands:
                offense = _descriptor_offense(band.descriptor)
                if offense:
                    raise _ReplyError(
                        f"criterion {criterion_id!r}: its construct carries {offense}, "
                        "which would leak into the derived band descriptors "
                        "(FR-SETUP-05) — restate the construct behaviourally."
                    )
        drafts.append(CriterionDraft(
            criterion_id=criterion_id, question_id=question_id, kind=kind,
            scoring_model=scoring_model, max_points=float(max_points),
            construct=construct, band_count=band_count, bands=bands,
            justification=justification.strip(), evidence_type=evidence_type.strip(),
            bands_source=bands_source, decomposition_basis=decomposition_basis,
            needs_confirmation=needs_confirmation,
        ))
    return tuple(drafts)


def _draft_criterion_identity(draft: Any) -> dict:
    """The classifier's view of one criterion draft, as a plain mapping.

    The draft arrives either as a `CriterionDraft` (the read back's own drafts) or as
    the plain dict a caller assembled (the payload shape the test suite bets on) — the
    classifier consumes the identity fields either way, and refuses a draft that names
    no criterion (`SetupError`: a classification of nothing is not a classification)."""
    if isinstance(draft, Mapping):
        get = draft.get
    else:
        get = lambda name, default=None: getattr(draft, name, default)  # noqa: E731
    criterion_id = get("criterion_id")
    if not isinstance(criterion_id, str) or not criterion_id.strip():
        raise SetupError(
            "classify_decomposability needs a draft that names its criterion — "
            f"got {draft!r} with no usable 'criterion_id'."
        )
    return {
        "criterion_id": criterion_id,
        "question_id": str(get("question_id", "") or ""),
        "kind": str(get("kind", "") or ""),
        "construct": str(get("construct", "") or ""),
        "max_points": get("max_points", 0.0),
        "band_count": get("band_count", 0),
    }


def _json_object(text: str) -> dict:
    """The one JSON object a reply carries, tolerating prose around it (models add
    it) — the shared first half of the reply parsers."""
    stripped = text.strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start < 0 or end <= start:
        raise _ReplyError("the reply contains no JSON object.")
    try:
        parsed = json.loads(stripped[start:end + 1])
    except ValueError as error:
        raise _ReplyError(f"the reply is not valid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise _ReplyError("the reply's JSON is not an object.")
    return parsed


def _parse_classify_reply(text: str, criterion_id: str) -> tuple[dict, list[str], str]:
    """Parse the classifier's reply into (answers, warning_signs, reasoning), raising
    `_ReplyError` on anything that is not a valid §5.3 answer set — the failure the
    attempt loop re-requests. The reply carries ANSWERS, never a classification
    (`FR-SETUP-06`: the table is the module's); a reply naming a different criterion
    than the draft is a schema failure, not an answer to accept."""
    parsed = _json_object(text)
    reply_id = parsed.get("criterion_id")
    if reply_id is not None and str(reply_id) != criterion_id:
        raise _ReplyError(
            f"the reply classifies {str(reply_id)!r} but the draft names "
            f"{criterion_id!r} — one classification per criterion, and this reply "
            "answers a different one."
        )
    raw_answers = parsed.get("answers")
    if not isinstance(raw_answers, dict):
        raise _ReplyError(
            "the reply's JSON does not carry an 'answers' object — the classifier "
            "answers the five §5.3 questions; it does not classify."
        )
    answers = {
        question: str(raw_answers.get(question, "unclear")).strip().lower()
        for question in FIVE_QUESTIONS
    }
    raw_warnings = parsed.get("warning_signs", [])
    if raw_warnings is None:
        raw_warnings = []
    if not isinstance(raw_warnings, list):
        raise _ReplyError(
            f"criterion {criterion_id!r}: warning_signs must be a list of strings."
        )
    warning_signs = [str(item) for item in raw_warnings if str(item).strip()]
    reasoning = parsed.get("reasoning", "")
    if reasoning is None:
        reasoning = ""
    if not isinstance(reasoning, str):
        raise _ReplyError(
            f"criterion {criterion_id!r}: reasoning must be a string."
        )
    return answers, warning_signs, reasoning.strip()


def _parse_dependencies_reply(
    text: str, known_ids: frozenset[str] | set[str],
) -> tuple[tuple[str, str, str], ...]:
    """Parse the dependency proposal's reply into (criterion_id, depends_on, reason)
    triples, raising `_ReplyError` on anything that is not a valid proposal set —
    the failure the attempt loop re-requests. An edge naming a criterion the version
    does not carry, or an edge whose ends are the same criterion, is a schema
    failure: the write path would refuse it, so the proposal path does too."""
    parsed = _json_object(text)
    items = parsed.get("dependencies")
    if items is None:
        items = parsed.get("proposals")
    if not isinstance(items, list):
        raise _ReplyError(
            "the reply's JSON does not carry a 'dependencies' list."
        )
    triples: list[tuple[str, str, str]] = []
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise _ReplyError(f"dependency #{index} is not an object.")
        criterion_id = raw.get("criterion_id")
        depends_on = raw.get("depends_on")
        if not isinstance(criterion_id, str) or not criterion_id.strip():
            raise _ReplyError(f"dependency #{index}: criterion_id must be a string.")
        if not isinstance(depends_on, str) or not depends_on.strip():
            raise _ReplyError(
                f"dependency #{index} ({criterion_id!r}): depends_on must be a string."
            )
        if criterion_id == depends_on:
            raise _ReplyError(
                f"dependency #{index}: {criterion_id!r} cannot depend on itself — a "
                "self-edge is the cycle the write path refuses."
            )
        for end in (criterion_id, depends_on):
            if end not in known_ids:
                raise _ReplyError(
                    f"dependency #{index}: criterion {end!r} is not in this version's "
                    "criteria — a proposal attaches to criteria that exist."
                )
        reason = raw.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise _ReplyError(
                f"dependency {criterion_id!r} -> {depends_on!r}: reason must state, "
                "in words, what the grading presupposes — a dependency without its "
                "why cannot be rendered as plain language (FR-SETUP-10)."
            )
        triples.append((criterion_id, depends_on, reason.strip()))
    return tuple(triples)


def _criterion_to_dict(draft: CriterionDraft) -> dict:
    """The payload shape for one read-back criterion — plain mappings, because the
    data layer does not import this module's types. `bands_source` is
    `proposed` or `derived_default` (`FR-SETUP-14`: a default taken is recorded)."""
    return {
        "criterion_id": draft.criterion_id,
        "question_id": draft.question_id,
        "kind": draft.kind,
        "scoring_model": draft.scoring_model,
        "max_points": draft.max_points,
        "construct": draft.construct,
        "band_count": draft.band_count,
        "evidence_type": draft.evidence_type,
        "justification": draft.justification,
        "bands_source": draft.bands_source,
        "decomposition_basis": draft.decomposition_basis,
        "bands": [
            {"band": band.band, "ordinal": band.ordinal, "points": band.points,
             "descriptor": band.descriptor}
            for band in draft.bands
        ],
    }


def _criterion_record(draft: CriterionDraft) -> dict:
    """The write shape `PackageCatalog.write_readback` validates and stores — the
    payload dict's sibling under M-PKG's names (`construct_tag`, `band_justification`)."""
    return {
        "criterion_id": draft.criterion_id,
        "question_id": draft.question_id,
        "kind": draft.kind,
        "max_points": draft.max_points,
        "scoring_model": draft.scoring_model,
        "construct_tag": draft.construct,
        "band_count": draft.band_count,
        "evidence_type": draft.evidence_type,
        "band_justification": draft.justification or None,
        "bands": [
            {"band": band.band, "ordinal": band.ordinal, "points": band.points,
             "descriptor": band.descriptor}
            for band in draft.bands
        ],
    }


def _stored_readback_status(row: Mapping[str, Any] | None) -> str:
    """The stored read-back row's status — a field of the PAYLOAD, not a column.

    `steps()` reads this to report done / degraded honestly (`NFR-SETUP-04`): the
    row's own columns are provenance (documents, prompt, build, attempts), and the
    status word the module wrote lives inside the payload it mirrors. A row whose
    payload cannot be parsed reads as not-done rather than crashing the console's
    enumeration — the row is provenance, and provenance is not silently replaced."""
    if not row:
        return ""
    try:
        return str(json.loads(row["payload"]).get("status") or "")
    except (KeyError, TypeError, ValueError):
        return ""


def _readback_from_row(v: PackageVersionId, row: Mapping[str, Any]) -> RubricReadback:
    """Rebuild the stored read back — the resume path's read (`CT-SETUP-03`: state is
    the database). A malformed stored payload raises `SetupError` naming the corruption
    rather than silently re-reading the rubric over it."""

    try:
        payload = json.loads(row["payload"])
        status = payload["status"]
        entries = payload.get("criteria", [])
        reason = payload.get("reason", "")
    except (ValueError, KeyError, TypeError) as error:
        raise SetupError(
            f"the stored read-back for version {v!r} is malformed ({error}) — the "
            "payload is provenance and is not silently replaced; delete the version "
            "and run setup again."
        ) from error
    criteria = tuple(
        CriterionDraft(
            criterion_id=str(entry["criterion_id"]),
            question_id=str(entry["question_id"]),
            kind=str(entry["kind"]),
            scoring_model=str(entry["scoring_model"]),
            max_points=float(entry.get("max_points", 0.0)),
            construct=str(entry.get("construct", "")),
            band_count=int(entry["band_count"]),
            bands=tuple(
                ProposedBand(band=str(band["band"]), ordinal=int(band["ordinal"]),
                             points=float(band.get("points", 0.0)),
                             descriptor=str(band["descriptor"]))
                for band in entry.get("bands", ())
            ),
            justification=str(entry.get("justification", "")),
            evidence_type=str(entry.get("evidence_type",
                                        SETUP_EVIDENCE_TYPE_DEFAULT)),
            bands_source=str(entry.get("bands_source", "proposed")),
            decomposition_basis=str(entry.get("decomposition_basis", "")),
        )
        for entry in entries
    )
    return RubricReadback(
        rubric_doc_id=str(row["rubric_doc_id"]),
        assessment_doc_id=str(row["assessment_doc_id"]),
        package_version_id=v,
        template_version=str(row["template_version"]),
        model_ref=str(row["model_ref"]),
        attempts=int(row["attempts"]),
        criteria=criteria,
        status=status,
        reason=str(reason),
    )


class SetupService:
    """M-SETUP's Stage A, end to end, from code (`CT-SETUP-11`'s headless driver).

    `SetupService(catalog, ingestor, provider, model_ref)` — the Tier P catalog the
    package lives in, the `M-INGEST` gateway the assessment is read through, and the
    `M-PROV` seam the proposal call goes through. `params` defaults to
    `SamplingParams(temperature=0.0)`: a proposal is a reading task, not a sampling
    one.

    Design §3.6's protocol, and what this story stages:

    ============================  =============================================
    operation                     status
    ============================  =============================================
    `propose_inventory`           here — one proposal per version (`CT-SETUP-16`)
    `confirm_inventory`           here — BLOCKING gate 1; locks the rows
    `read_back_rubric`            here — #51: criteria and even band sets, magnitude
                                  descriptors rejected and re-requested; one read
                                  back per version (`CT-SETUP-16`)
    `set_answer_keys`             here — BLOCKING gate 2 (thin; #53 stages the
                                  full `FR-SETUP-03` semantics)
    `classify_decomposability`    here — #52: the §5.3 ANSWERS from the model, the
                                  decision table from the module; confirmations
                                  capped at `SETUP_MAX_CONFIRMATIONS` headlessly
    `confirm_classifications`     here — #52: the teacher's confirmation recorded
                                  apart from the module's default (`R62`)
    `propose_dependencies`        here — #52: plain-language proposals, nothing
                                  written; `confirm_dependencies` writes only on
                                  explicit approval
    `publish`                     here — refused until both gates hold
    `ensure_version`, `steps`,    here — the resume and console surfaces
    `current_proposal`
    `set_grade_policy`            #53 (grade boundaries land there too)
    `check_prefix_budget`         #53
    ============================  =============================================
    """

    def __init__(
        self, catalog: PackageCatalog, ingestor: Any, provider: InferenceProvider,
        model_ref: ModelRef, *, params: SamplingParams | None = None,
    ) -> None:
        self._catalog = catalog
        self._ingestor = ingestor
        self._provider = provider
        self._model_ref = model_ref
        self._params = params if params is not None else SamplingParams(temperature=0.0)
        # The confirmation cap's counter (`FR-SETUP-07`, `CT-SETUP-13`): confirmations
        # REQUESTED per draft version, this service's accounting of what the teacher
        # has been asked so far. Keyed by version so one service carrying several
        # drafts never lets one package's spend buy another's confirmations.
        self._confirmations_requested: dict[str | None, int] = {}

    @property
    def package_id(self) -> str:
        """The package this service stages, as the catalog knows it."""
        return self._catalog.package_id

    # -- the version and the resume surface -------------------------------------------------

    def ensure_version(self) -> PackageVersionId:
        """The draft version setup works on, minted on first call: the package row and
        its initial version are exactly what `create_version` refuses to mint itself
        (`FR-SETUP-16`'s first move). Resumption calls this and gets the SAME draft —
        the latest unpublished version — because state is the database (`CT-SETUP-03`)."""
        draft = self._catalog.draft_version()
        if draft is not None:
            return draft
        self._catalog.ensure_package()
        version = self._catalog.create_version(None)
        LOGGER.info("minted initial package version %s for setup", version)
        return version

    def current_proposal(self) -> InventoryProposal | None:
        """The draft version's stored proposal, or None — what a resuming console
        re-renders without calling the model again."""
        v = self._catalog.draft_version()
        if v is None:
            return None
        stored = self._catalog.proposal(v)
        return _proposal_from_row(v, stored) if stored else None

    def steps(self) -> SetupProgress:
        """The enumerated setup steps and what remains (`TC-SETUP-03`'s shape,
        `NFR-SETUP-04`'s honest count).

        With no draft version the package is in one of two states, told apart by
        `has_version`: NOT STARTED (no version at all — the inventory step is
        available, because proposing mints the initial version) or FINISHED (a
        published version, no draft — every step unavailable and the count 0: no step
        can be acted on, and a count that says otherwise is the console lying).

        `answer_keys`' done state is the structural fact `publish` enforces — every
        deterministic criterion keyed — which with zero criteria is vacuously true:
        no deterministic criterion exists until #53 stages their creation from the
        confirmed inventory, so in this story's world a confirmed inventory is
        publishable and the console must say so rather than demand a step whose work
        does not exist yet."""
        v = self._catalog.draft_version()
        if v is None:
            # No draft. Two states, told apart (`has_version`): a package with NO
            # version has not started — the inventory step is available (its first
            # move mints the draft); a package whose versions are all published has
            # FINISHED — no step can be acted on, and the remaining count is 0
            # because a count that says otherwise is the console lying.
            started = self._catalog.has_version()
            later_steps = (
                SetupStep(
                    step_id="rubric_readback",
                    name="Rubric read-back against the stored rubric",
                    blocking=False, available=False, done=False,
                    note="needs a draft version and a confirmed inventory — the read "
                    "back anchors criteria to confirmed questions (FR-SETUP-02)",
                ),
                SetupStep(
                    step_id="decomposability",
                    name="Criterion decomposability and dependencies",
                    blocking=False, available=False, done=False,
                    note="non-blocking — the §5.3 classification runs once the read "
                    "back has staged the criteria; skipped steps record their "
                    "default (FR-SETUP-14)",
                ),
                SetupStep(
                    step_id="grade_policy",
                    name="Grade policy, boundaries and the prefix budget",
                    blocking=False, available=False, done=False,
                    note="staged by #53",
                ),
            )
            return SetupProgress(
                package_version_id=None,
                steps=(
                    SetupStep(
                        step_id="inventory",
                        name="Question inventory: propose, correct, confirm",
                        blocking=True, available=not started, done=False,
                        note="setup has not started — proposing mints the package's "
                        "initial version" if not started else
                        "setup has finished (its version is published); a new "
                        "instrument is a new package or a revision (FR-PKG-02)",
                    ),
                    SetupStep(
                        step_id="answer_keys",
                        name="Answer keys for the deterministic criteria",
                        blocking=True, available=False, done=False,
                        note="needs a draft version and a confirmed inventory",
                    ),
                ) + later_steps,
                remaining_steps=1 if not started else 0,
                ready_to_publish=False,
            )
        stored = self._catalog.proposal(v)
        confirmed = bool(stored and stored["confirmed_at"])
        criteria = self._catalog.criteria(v)
        unkeyed = [
            row["criterion_id"] for row in criteria
            if row.get("scoring_model") == "atomic" and not row.get("answer_key")
        ]
        keys_done = not unkeyed
        keys_note = ""
        if not confirmed:
            keys_note = "unlocks when the question inventory is confirmed (§4.2.1)"
        elif unkeyed:
            keys_note = f"answer keys missing for: {', '.join(unkeyed)}"
        elif not any(row.get("scoring_model") == "atomic" for row in criteria):
            keys_note = "no deterministic criteria yet — #53 stages their creation"
        # The rubric read-back went live with #51: available once gate 1 is met, done
        # when the stored read-back row reads `proposed` (the degraded row is a fact
        # the note carries, not a done). The status lives in the row's PAYLOAD — the
        # row's own columns are provenance only. The getattr guard keeps the
        # enumeration honest over rung-0 doubles that do not model the write surface —
        # a missing member reads as "not done", never as a console crash.
        readback_member = getattr(self._catalog, "readback", None)
        stored_readback = readback_member(v) if readback_member is not None else None
        readback_status = _stored_readback_status(stored_readback)
        readback_note = ""
        if not confirmed:
            readback_note = "unlocks when the question inventory is confirmed (§4.2.1)"
        elif readback_status == "needs_manual_entry":
            readback_note = ("the read back degraded to needs_manual_entry after its "
                             "attempt budget — enter criteria through M-PKG, or a new "
                             "version re-reads the rubric (FR-SETUP-04)")
        # The decomposability step's record (#52): the provenance row the step's own
        # writes leave (confirmations, dependency proposals, approvals), read back
        # through the same getattr guard the other write surfaces use — a catalog
        # without the recording surface reads as "not done", never as a crash.
        step_reader = getattr(self._catalog, "step_record", None)
        decomposability_record = (step_reader(v, "decomposability")
                                  if step_reader is not None else None)
        decomposability_note = ""
        if not confirmed:
            decomposability_note = (
                "unlocks when the question inventory is confirmed (§4.2.1)")
        elif readback_status != "proposed":
            decomposability_note = (
                "unlocks when the rubric read-back has staged the criteria — the "
                "§5.3 table judges criteria that exist (FR-SETUP-06)")
        elif decomposability_record is not None:
            decomposability_note = (
                f"recorded: {decomposability_record['status']} at "
                f"{decomposability_record['recorded_at']} (FR-SETUP-14)")
        else:
            decomposability_note = (
                "surfaced confirmations await the teacher; dependencies stay at "
                "zero until explicitly approved (FR-SETUP-07, FR-SETUP-10)")
        later = (
            SetupStep(
                step_id="rubric_readback",
                name="Rubric read-back against the stored rubric",
                blocking=False, available=confirmed,
                done=readback_status == "proposed",
                note=readback_note,
            ),
            SetupStep(
                step_id="decomposability",
                name="Criterion decomposability and dependencies",
                blocking=False,
                # Available once criteria EXIST for the table to judge — the read
                # back is what stages them. Hand-authored criteria alone do not
                # unlock the step: the §5.3 classification is the read-back
                # population's step (§4.2.1's S5), and an unlocked-but-empty step
                # would be the console offering an operation with no work behind it.
                available=confirmed and readback_status == "proposed",
                done=decomposability_record is not None,
                note=decomposability_note,
            ),
            SetupStep(
                step_id="grade_policy",
                name="Grade policy, boundaries and the prefix budget",
                blocking=False, available=False, done=False,
                note="staged by #53",
            ),
        )
        steps = (
            SetupStep(
                step_id="inventory",
                name="Question inventory: propose, correct, confirm",
                blocking=True, available=True, done=confirmed,
                note="" if confirmed else "the teacher's confirmation is blocking "
                "gate 1 of 2 (FR-SETUP-02)",
            ),
            SetupStep(
                step_id="answer_keys",
                name="Answer keys for the deterministic criteria",
                blocking=True, available=confirmed, done=keys_done,
                note=keys_note,
            ),
        ) + later
        remaining = sum(1 for step in steps if step.available and not step.done)
        ready = confirmed and keys_done
        return SetupProgress(
            package_version_id=v, steps=steps, remaining_steps=remaining,
            ready_to_publish=ready,
        )

    # -- Stage A: propose, confirm (BLOCKING), publish ---------------------------------------

    def propose_inventory(self, assessment_doc: DocumentId) -> InventoryProposal:
        """Propose the question inventory from the assessment document — ONCE per
        version (`CT-SETUP-16`).

        The document is read through `M-INGEST` (`CT-SETUP-11`); one model call goes
        out through the provider seam per attempt (`CT-SETUP-12`'s budget, env-gated).
        A reply that fails to parse or validate is re-requested; after the budget the
        proposal is recorded as `needs_manual_entry` — degraded but complete, the
        teacher enters the questions as `add` corrections and confirms.

        Already-stored proposals come back unchanged (the resume path — no new model
        call); a CONFIRMED inventory refuses to be proposed again (`SetupOrderError`):
        it is locked (`FR-SETUP-02`), and a new instrument is a new version."""
        v = self.ensure_version()
        stored = self._catalog.proposal(v)
        if stored is not None:
            proposal = _proposal_from_row(v, stored)
            if proposal.confirmed:
                raise SetupOrderError(
                    f"the inventory for version {v!r} was already confirmed at "
                    f"{proposal.confirmed_at}; the question rows are locked "
                    "(FR-SETUP-02) and proposing again is out of order (CT-SETUP-16). "
                    "A new instrument is a new version (FR-PKG-02)."
                )
            LOGGER.info("resuming with the stored proposal %s for version %s",
                        proposal.proposal_id, v)
            return proposal

        markdown = self._ingestor.read_document(assessment_doc)
        payload = PromptPayload(fields=(
            ("instruction", _INVENTORY_INSTRUCTION),
            ("assessment_transcript", markdown),
        ))
        proposal_id = uuid.uuid4().hex[:12]
        budget = _configured_proposal_attempts()
        last_error = ""
        for attempt in range(1, budget + 1):
            try:
                completion = self._provider.complete(payload, self._model_ref,
                                                     self._params)
                questions = _parse_reply(completion.text)
            except _ReplyError as error:
                last_error = f"attempt {attempt}: {error}"
                LOGGER.warning("inventory proposal reply failed to parse (%d/%d): %s",
                               attempt, budget, error)
                continue
            except Exception as error:  # contained: the transport's failure is a
                # failed attempt, and the degraded path — not a crash — is the
                # honest end of a budget spent (CT-SETUP-12).
                last_error = f"attempt {attempt}: {type(error).__name__}: {error}"
                LOGGER.warning("inventory proposal attempt %d/%d failed: %s",
                               attempt, budget, error)
                continue
            body = {
                "status": "proposed",
                "entries": [_question_to_dict(question) for question in questions],
            }
            self._catalog.record_proposal(
                v, proposal_id=proposal_id, assessment_doc_id=assessment_doc,
                payload=json.dumps(body, sort_keys=True),
                template_version=SETUP_PROMPT_TEMPLATE_V,
                model_ref=completion.resolved_build, attempts=attempt,
            )
            proposal = InventoryProposal(
                proposal_id=proposal_id, assessment_doc_id=assessment_doc,
                package_version_id=v, template_version=SETUP_PROMPT_TEMPLATE_V,
                model_ref=completion.resolved_build, attempts=attempt,
                questions=questions, status="proposed",
            )
            LOGGER.info(
                "proposed inventory %s for version %s from document %s: %d "
                "question(s) in %d attempt(s), prompt %s",
                proposal_id, v, assessment_doc, len(questions), attempt,
                SETUP_PROMPT_TEMPLATE_V,
            )
            return proposal

        body = {
            "status": "needs_manual_entry",
            "entries": [],
            "reason": last_error,
        }
        self._catalog.record_proposal(
            v, proposal_id=proposal_id, assessment_doc_id=assessment_doc,
            payload=json.dumps(body, sort_keys=True),
            template_version=SETUP_PROMPT_TEMPLATE_V,
            model_ref=self._model_ref.build_id, attempts=budget,
        )
        LOGGER.warning(
            "inventory proposal for version %s degraded to needs_manual_entry after "
            "%d attempt(s): %s — the teacher enters the questions as corrections "
            "(CT-SETUP-12)", v, budget, last_error,
        )
        return InventoryProposal(
            proposal_id=proposal_id, assessment_doc_id=assessment_doc,
            package_version_id=v, template_version=SETUP_PROMPT_TEMPLATE_V,
            model_ref=self._model_ref.build_id, attempts=budget, questions=(),
            status="needs_manual_entry",
        )

    def confirm_inventory(
        self, proposal_id: str, corrections: Sequence[QuestionCorrection] = (),
    ) -> None:
        """The teacher's confirmation — BLOCKING gate 1 (`§4.2.1`). Applies the
        corrections to the stored proposal and writes the confirmed inventory through
        `M-PKG` in one transaction; the §6.2 lock engages at this write
        (`FR-SETUP-02`), which is why confirmation is deliberate and refuses to be
        anonymous: the `proposal_id` must be the version's stored proposal, so the
        teacher confirms what was actually proposed.

        Returns None by design (`§3.6`'s protocol): the confirmation's observable
        result is the locked inventory, read back through `current_proposal` /
        `steps` / the catalog's question surfaces."""
        v = self._require_draft_version()
        stored = self._catalog.proposal(v)
        if stored is None:
            raise SetupOrderError(
                f"no inventory proposal is recorded for version {v!r} — "
                "propose_inventory first; confirmation confirms a proposal, not an "
                "idea."
            )
        if stored["confirmed_at"] is not None:
            raise SetupOrderError(
                f"the inventory for version {v!r} is already confirmed (at "
                f"{stored['confirmed_at']}) — it is locked (FR-SETUP-02) and cannot "
                "be confirmed again."
            )
        if stored["proposal_id"] != proposal_id:
            raise SetupOrderError(
                f"confirmation names proposal {proposal_id!r} but version {v!r} "
                f"holds {stored['proposal_id']!r} — the teacher confirms what was "
                "proposed, and a stale or foreign id is refused."
            )
        proposal = _proposal_from_row(v, stored)
        entries: dict[str, ProposedQuestion] = {
            question.question_id: question for question in proposal.questions
        }
        for correction in corrections:
            if correction.action not in ("add", "set", "remove"):
                raise SetupError(
                    f"correction for {correction.question_id!r} has unknown action "
                    f"{correction.action!r} — 'add', 'set' or 'remove'."
                )
            if correction.action == "add":
                if correction.question_id in entries:
                    raise SetupError(
                        f"add correction names {correction.question_id!r}, which the "
                        "proposal already carries — a 'set' correction edits it."
                    )
                missing = [
                    field for field in ("question_type", "prompt_text")
                    if getattr(correction, field) is None
                ]
                if missing:
                    raise SetupError(
                        f"add correction for {correction.question_id!r} is missing "
                        f"{', '.join(missing)} — the manual-entry path must carry "
                        "them (CT-SETUP-12)."
                    )
                if correction.question_type not in QUESTION_TYPES:
                    raise SetupError(
                        f"add correction for {correction.question_id!r} carries "
                        f"question_type {correction.question_type!r}, outside the "
                        f"vocabulary {QUESTION_TYPES}."
                    )
                options = correction.options or ()
                if correction.question_type in ("mcq", "mixed") and not options:
                    raise SetupError(
                        f"add correction for {correction.question_id!r} is "
                        f"{correction.question_type} without options — the teacher "
                        "would have nothing to mark."
                    )
                if correction.question_type == "open" and options:
                    raise SetupError(
                        f"add correction for {correction.question_id!r} is open but "
                        "carries options — a typed mismatch is a correction bug."
                    )
                ordinal = correction.ordinal
                if ordinal is None:
                    ordinal = max((q.ordinal for q in entries.values()), default=-1) + 1
                entries[correction.question_id] = ProposedQuestion(
                    question_id=correction.question_id, ordinal=ordinal,
                    prompt_text=correction.prompt_text or "",
                    question_type=correction.question_type,
                    max_points=float(correction.max_points or 0.0),
                    options=tuple(options),
                )
            elif correction.action == "set":
                if correction.question_id not in entries:
                    raise SetupError(
                        f"set correction names {correction.question_id!r}, which the "
                        "proposal does not carry — 'add' contributes a new question."
                    )
                base = entries[correction.question_id]
                if (correction.options is not None
                        and correction.question_type is None
                        and base.question_type == "open" and correction.options):
                    raise SetupError(
                        f"set correction adds options to open question "
                        f"{correction.question_id!r} without retyping it — set "
                        "question_type to 'mcq' or 'mixed' in the same correction."
                    )
                entries[correction.question_id] = ProposedQuestion(
                    question_id=base.question_id,
                    ordinal=base.ordinal if correction.ordinal is None
                    else correction.ordinal,
                    prompt_text=base.prompt_text if correction.prompt_text is None
                    else correction.prompt_text,
                    question_type=base.question_type
                    if correction.question_type is None
                    else correction.question_type,
                    max_points=base.max_points if correction.max_points is None
                    else float(correction.max_points),
                    options=base.options if correction.options is None
                    else tuple(correction.options),
                )
            else:  # remove
                if correction.question_id not in entries:
                    raise SetupError(
                        f"remove correction names {correction.question_id!r}, which "
                        "the proposal does not carry."
                    )
                del entries[correction.question_id]
        questions = tuple(entries.values())
        _assert_confirmed_shape(questions)
        self._catalog.write_confirmed_inventory(
            v, proposal_id=proposal_id,
            questions=[_question_to_dict(question) for question in questions],
            confirmed_at=_now(),
        )
        LOGGER.info(
            "inventory confirmed for version %s (%d question(s), %d correction(s)) — "
            "the question rows are locked (FR-SETUP-02)", v, len(questions),
            len(corrections),
        )

    def read_back_rubric(self, rubric_doc: DocumentId,
                         assessment_doc: DocumentId) -> RubricReadback:
        """Read the stored rubric back into criteria and band sets (`§3.6`'s Interface,
        `FR-SETUP-04`/`-05`/`-09`).

        Gate 1 (the confirmed inventory) must be met first — criteria anchor to
        confirmed questions (`SetupOrderError` otherwise). The rubric and assessment are
        read through `M-INGEST` (`CT-SETUP-11`); each attempt is one model call through
        the provider seam within the `HARNESS_SETUP_READBACK_ATTEMPTS` budget. A reply
        that fails to parse, anchors to an unconfirmed question, or carries a band
        descriptor matching `SETUP_MAGNITUDE_PHRASES` (or a bare numeral) is
        re-requested (`FR-SETUP-05`); after the budget the read back degrades to
        `needs_manual_entry` — recorded, so the teacher enters the criteria through
        `M-PKG` and the console says what happened rather than retrying forever.

        The stored row comes back unchanged (the resume path — no new model call,
        `CT-SETUP-03`), and a read back is ONCE per version (`CT-SETUP-16`): the row is
        provenance, written all-or-nothing through `M-PKG` (`CT-PKG-11`)."""
        v = self._require_draft_version()
        stored = self._catalog.readback(v)
        if stored is not None:
            readback = _readback_from_row(v, stored)
            LOGGER.info("resuming with the stored rubric read-back for version %s "
                        "(status %s, %d attempt(s))", v, readback.status,
                        readback.attempts)
            return readback
        proposal = self._catalog.proposal(v)
        if proposal is None or not proposal["confirmed_at"]:
            raise SetupOrderError(
                f"the inventory for version {v!r} is not confirmed yet — the rubric "
                "read-back anchors criteria to confirmed questions, so gate 1 "
                "(§4.2.1) must be met before it runs (FR-SETUP-02)."
            )
        taken = [row["criterion_id"] for row in self._catalog.criteria(v)]
        if taken:
            # Reachable through M-PKG's public add_criterion — the same manual path
            # the degraded note directs a teacher to. The read back writes criteria
            # onto a clean draft (CT-PKG-11: a rejected write is a no-op, so the next
            # attempt re-proposes onto that clean draft); merging its output with
            # hand-added criteria is a decision a model call cannot make, so refuse
            # BEFORE spending the attempt budget rather than letting M-PKG's refusal
            # escape mid-write.
            raise SetupOrderError(
                f"version {v!r} already carries criterion rows ({', '.join(taken[:4])}"
                f"{', …' if len(taken) > 4 else ''}) — the rubric read-back writes "
                "criteria onto a clean draft and would collide with them. A version "
                "is either hand-authored or read back, not both; a fresh read-back is "
                "a new version (FR-PKG-02)."
            )
        rubric_markdown = self._ingestor.read_document(rubric_doc)
        assessment_markdown = self._ingestor.read_document(assessment_doc)
        confirmed_ids = frozenset(
            row["question_id"] for row in self._catalog.questions(v)
        )
        payload = PromptPayload(fields=(
            ("instruction", _READBACK_INSTRUCTION),
            ("rubric_transcript", rubric_markdown),
            ("assessment_transcript", assessment_markdown),
        ))
        budget = _configured_readback_attempts()
        last_error = ""
        for attempt in range(1, budget + 1):
            try:
                completion = self._provider.complete(payload, self._model_ref,
                                                     self._params)
                criteria = _parse_readback_reply(completion.text, confirmed_ids)
            except _ReplyError as error:
                last_error = f"attempt {attempt}: {error}"
                LOGGER.warning("rubric read-back reply failed to parse (%d/%d): %s",
                               attempt, budget, error)
                continue
            except Exception as error:  # contained: the transport's failure is a
                # failed attempt, and the degraded path — not a crash — is the
                # honest end of a budget spent (CT-SETUP-12's pattern).
                last_error = f"attempt {attempt}: {type(error).__name__}: {error}"
                LOGGER.warning("rubric read-back attempt %d/%d failed: %s",
                               attempt, budget, error)
                continue
            body = {
                "status": "proposed",
                "criteria": [_criterion_to_dict(criterion) for criterion in criteria],
            }
            # The read back is a classification surface too (#52): every criterion
            # whose scoring model the §5.3 table (or the reply's declared model)
            # produced gets its `source='default'` row NOW, so the R62 audit table
            # is complete before the teacher speaks, and every borderline verdict —
            # an unclear answer or a warning sign — counts against the confirmation
            # cap through the SAME counter the classifier uses (`_request_confirmation`
            # is the cap's one accounting point).
            recorder = getattr(self._catalog, "record_classification", None)
            borderline: list[str] = []
            for criterion in criteria:
                if recorder is not None:
                    recorder(
                        v, criterion_id=criterion.criterion_id,
                        classification=criterion.scoring_model,
                        decomposition_basis=criterion.decomposition_basis or None,
                        source="default", recorded_at=_now(),
                    )
                if criterion.needs_confirmation and self._request_confirmation(v):
                    borderline.append(criterion.criterion_id)
            if borderline:
                LOGGER.warning(
                    "read back produced %d borderline classification(s) for version "
                    "%s (%s) — surfaced for the teacher within the %d-confirmation "
                    "cap (FR-SETUP-07, NFR-SETUP-01)", len(borderline), v,
                    ", ".join(borderline), SETUP_MAX_CONFIRMATIONS,
                )
            self._catalog.write_readback(
                v, rubric_doc_id=rubric_doc, assessment_doc_id=assessment_doc,
                criteria=[_criterion_record(criterion) for criterion in criteria],
                payload=json.dumps(body, sort_keys=True),
                template_version=SETUP_READBACK_TEMPLATE_V,
                model_ref=completion.resolved_build, attempts=attempt,
                created_at=_now(),
            )
            LOGGER.info(
                "read the rubric back for version %s from documents %s/%s: %d "
                "criterion(s) in %d attempt(s), prompt %s",
                v, rubric_doc, assessment_doc, len(criteria), attempt,
                SETUP_READBACK_TEMPLATE_V,
            )
            return RubricReadback(
                rubric_doc_id=rubric_doc, assessment_doc_id=assessment_doc,
                package_version_id=v, template_version=SETUP_READBACK_TEMPLATE_V,
                model_ref=completion.resolved_build, attempts=attempt,
                criteria=criteria, status="proposed",
            )

        body = {
            "status": "needs_manual_entry",
            "criteria": [],
            "reason": last_error,
        }
        self._catalog.write_readback(
            v, rubric_doc_id=rubric_doc, assessment_doc_id=assessment_doc,
            criteria=[], payload=json.dumps(body, sort_keys=True),
            template_version=SETUP_READBACK_TEMPLATE_V,
            model_ref=self._model_ref.build_id, attempts=budget,
            created_at=_now(),
        )
        LOGGER.warning(
            "rubric read-back for version %s degraded to needs_manual_entry after "
            "%d attempt(s): %s — the teacher enters the criteria through M-PKG "
            "(CT-SETUP-12's pattern)", v, budget, last_error,
        )
        return RubricReadback(
            rubric_doc_id=rubric_doc, assessment_doc_id=assessment_doc,
            package_version_id=v, template_version=SETUP_READBACK_TEMPLATE_V,
            model_ref=self._model_ref.build_id, attempts=budget, criteria=(),
            status="needs_manual_entry", reason=last_error,
        )

    def set_answer_keys(self, keys: Mapping[str, Sequence[str]]) -> None:
        """The teacher's answer keys — BLOCKING gate 2 (`§4.2.1`). A thin write-through
        to `PackageCatalog.set_answer_key` (`FR-PKG-17`'s single canonical
        representation): `#53` stages S4's full `FR-SETUP-03` semantics on top of this
        surface, so the operation exists and blocks NOW and does not change shape
        later. Requires the confirmed inventory first — the keys name criteria the
        inventory's questions become, and §4.2.1's order is S3 then S4."""
        v = self._require_draft_version()
        stored = self._catalog.proposal(v)
        if stored is None or stored["confirmed_at"] is None:
            raise SetupOrderError(
                "answer keys come after the confirmed inventory (S3 blocks S4, "
                "§4.2.1): confirm_inventory first — the keys name criteria the "
                "confirmed questions become."
            )
        if not keys:
            raise SetupError(
                "set_answer_keys with an empty mapping keys nothing — name at least "
                "one criterion and its acceptable option ids."
            )
        for criterion_id, key in keys.items():
            self._catalog.set_answer_key(v, criterion_id, list(key))
        LOGGER.info(
            "set %d answer key(s) for version %s — blocking step S4 (its full "
            "FR-SETUP-03 validation semantics land with #53)", len(keys), v,
        )

    # -- Stage A: decomposability and dependencies (#52, skippable steps) ---------------------

    def classify_decomposability(self, criterion_draft: Any) -> DecomposabilityVerdict:
        """Classify one criterion against the five §5.3 questions (`FR-SETUP-06`,
        `#52`) — the decision table applied where it belongs.

        The model is asked for ANSWERS (one prompt per criterion, `NFR-SETUP-03`'s
        version-pinned template), never for a verdict; `_classify_answers` is the
        module's table, so a scripted or hallucinated classification cannot pass
        through the seam. An unclear answer — or an attempt budget spent — applies
        NFR-SETUP-02's asymmetric default: `holistic`, never `atomic` (RISK-27), and
        the default case SURFACES for the teacher, which is what makes it auditable
        rather than silent.

        The surfacing half of `FR-SETUP-07` lives here too: only borderline criteria
        (an unclear answer anywhere) and warning-sign criteria are surfaced, and the
        number of confirmations REQUESTED per draft version is capped at
        `SETUP_MAX_CONFIRMATIONS` — enforced by this module, headlessly (`CT-SETUP-13`),
        never by the console. A criterion beyond the cap keeps its classification but
        is not requested. Every verdict is recorded through `M-PKG` as the module's
        default (`source='default'`), so a skipped confirmation still leaves the
        teacher-vs-system distinction `M-CALIB` and `M-STATS` read (`R62`)."""
        identity = _draft_criterion_identity(criterion_draft)
        criterion_id = identity["criterion_id"]
        payload = PromptPayload(fields=(
            ("instruction", _CLASSIFY_INSTRUCTION),
            ("criterion", json.dumps(identity, sort_keys=True)),
        ))
        budget = _configured_classify_attempts()
        last_error = ""
        for attempt in range(1, budget + 1):
            try:
                completion = self._provider.complete(payload, self._model_ref,
                                                     self._params)
                answers, warning_signs, reply_reasoning = _parse_classify_reply(
                    completion.text, criterion_id)
            except _ReplyError as error:
                last_error = f"attempt {attempt}: {error}"
                LOGGER.warning("classify reply for %s failed to parse (%d/%d): %s",
                               criterion_id, attempt, budget, error)
                continue
            except Exception as error:  # contained: the transport's failure is a
                # failed attempt, and the degraded default — not a crash — is the
                # honest end of a budget spent (CT-SETUP-12's pattern).
                last_error = f"attempt {attempt}: {type(error).__name__}: {error}"
                LOGGER.warning("classify attempt %d/%d for %s failed: %s",
                               attempt, budget, criterion_id, error)
                continue
            verdict = self._verdict_from_answers(
                criterion_id, answers, warning_signs, reply_reasoning)
            LOGGER.info(
                "classified %s for version %s: %s (decided by %s, confirmation "
                "%s) in %d attempt(s), prompt %s — confirmations requested %d/%d",
                criterion_id, self._catalog.draft_version(), verdict.classification,
                verdict.deciding_question or "nothing",
                "requested" if verdict.needs_teacher_confirmation else "not requested",
                attempt, SETUP_CLASSIFY_TEMPLATE_V,
                self._confirmations_requested.get(self._catalog.draft_version(), 0),
                SETUP_MAX_CONFIRMATIONS,
            )
            return verdict

        # The budget is spent and no reply parsed: degraded but complete (`CT-SETUP-12`)
        # — the default applies, surfaced, and the reason is in the verdict's reasoning
        # so the audit trail says WHY the teacher is being asked. The cap is applied
        # through the same counter as the classified path (`_request_confirmation`):
        # a degraded package must not exceed SETUP_MAX_CONFIRMATIONS any more than a
        # classified one (NFR-SETUP-01); beyond-cap criteria keep the holistic default
        # but are not requested.
        degraded = DecomposabilityVerdict(
            classification="holistic", deciding_question=None,
            reasoning=(
                "the classifier could not read a §5.3 answer set "
                f"({last_error or 'no valid reply within the attempt budget'}); the "
                "default applies: holistic, never atomic (NFR-SETUP-02) — please "
                "enter the answers or confirm the criterion by hand."
            ),
            needs_teacher_confirmation=self._request_confirmation(
                self._catalog.draft_version()),
        )
        self._record_classification(self._catalog.draft_version(), criterion_id,
                                    degraded)
        LOGGER.warning(
            "classify for %s degraded to the holistic default after %d attempt(s): %s",
            criterion_id, budget, last_error,
        )
        return degraded

    def _request_confirmation(self, v: PackageVersionId | None) -> bool:
        """Count one teacher confirmation against the cap, and say whether it was
        REQUESTED — the cap's single accounting point (`FR-SETUP-07`, `NFR-SETUP-01`).
        `SETUP_MAX_CONFIRMATIONS` confirmations are surfaced per draft version; a
        criterion beyond the cap keeps its classification but is not requested. The
        degraded path shares this counter, so a package whose provider fails cannot
        exceed the cap either. Keyed by the draft version when there is one — the
        rung-0 doubles carry none, and the counter still runs (keyed None)."""
        requested = self._confirmations_requested.get(v, 0)
        if requested >= SETUP_MAX_CONFIRMATIONS:
            return False
        self._confirmations_requested[v] = requested + 1
        return True

    def _verdict_from_answers(
        self, criterion_id: str, answers: Mapping[str, str],
        warning_signs: Sequence[str], reply_reasoning: str,
    ) -> DecomposabilityVerdict:
        """The table, the cap and the record, composed into one verdict — the shared
        body of the classified path and the degraded one. The cap counts confirmations
        REQUESTED per draft version (`FR-SETUP-07`): a criterion beyond
        `SETUP_MAX_CONFIRMATIONS` keeps its classification but is not requested."""
        classification, deciding = _classify_answers(answers)
        unclear = any(
            str(answers.get(question, "")).strip().lower() not in ("yes", "no")
            for question in FIVE_QUESTIONS
        )
        # A warning sign with every answer passing still refuses the atomic grant:
        # the table's one automatic `atomic` is for criteria with nothing standing
        # against decomposition — a warning sign is the population FR-SETUP-07
        # surfaces, and it is judged holistic rather than granted depth 1
        # (RISK-27's asymmetry, applied to the warning case too).
        if deciding is None and classification == "atomic" and warning_signs:
            classification = "holistic"
        borderline = unclear or bool(warning_signs)
        needs = self._request_confirmation(
            self._catalog.draft_version()) if borderline else False
        if deciding is not None:
            reasoning = (
                f"the §5.3 table decided on {deciding!r} (its answer was 'no'): the "
                f"criterion classifies {classification!r}."
            )
        elif unclear:
            reasoning = (
                "the §5.3 answers were unclear: the default applies — holistic, "
                "never atomic (NFR-SETUP-02, RISK-27); surfaced for the teacher."
            )
        elif warning_signs:
            reasoning = (
                "the §5.3 answers pass, but the criterion carries warning signs "
                f"({'; '.join(warning_signs)}): judged holistic and surfaced for "
                "the teacher (FR-SETUP-07)."
            )
        else:
            reasoning = (
                "all five §5.3 answers pass and no warning sign stands: the "
                "criterion is judged in isolation (atomic)."
            )
        if reply_reasoning:
            reasoning = f"{reasoning} The criterion's reader said: {reply_reasoning}"
        verdict = DecomposabilityVerdict(
            classification=classification, deciding_question=deciding,
            reasoning=reasoning, needs_teacher_confirmation=needs,
        )
        self._record_classification(self._catalog.draft_version(), criterion_id,
                                    verdict)
        return verdict

    def _record_classification(
        self, v: PackageVersionId | None, criterion_id: str,
        verdict: DecomposabilityVerdict,
    ) -> None:
        """Persist one verdict as the module's default through `M-PKG` (`R62`) — the
        row a later `confirm_classifications` upserts to `source='teacher'`. Skipped
        when there is no draft version or no recording surface (the rung-0 doubles):
        the verdict itself is still returned, since the classification does not
        depend on the record."""
        if v is None:
            return
        record = getattr(self._catalog, "record_classification", None)
        if record is None:
            return
        record(v, criterion_id=criterion_id, classification=verdict.classification,
               decomposition_basis=verdict.deciding_question, source="default",
               recorded_at=_now())

    def _record_decomposability_step(
        self, v: PackageVersionId, *, status: str, update: Mapping,
    ) -> None:
        """Merge `update` into the decomposability step's ONE provenance row
        (`FR-SETUP-14`) — merge, never replace: the step is one teacher step with
        three sub-acts (confirmations, proposals, approvals), and a whole-payload
        upsert would have each erase the others' record — the teacher confirms a
        classification and then approves a proposal, and the approval must still
        find the proposals it approves (`CT-SETUP-03`: state is the database).
        Skipped when the catalog offers no recording surface (the rung-0 doubles)."""
        step = getattr(self._catalog, "record_step", None)
        if step is None:
            return
        prior: dict = {}
        reader = getattr(self._catalog, "step_record", None)
        if reader is not None:
            row = reader(v, "decomposability")
            if row is not None:
                try:
                    loaded = json.loads(row["payload"])
                except (ValueError, TypeError):
                    loaded = None
                if isinstance(loaded, dict):
                    prior = loaded
        payload = {**prior, **dict(update)}
        step(v, step_id="decomposability", status=status,
             payload=json.dumps(payload, sort_keys=True), recorded_at=_now())

    def confirm_classifications(self, answers: Mapping[str, str]) -> None:
        """The teacher's confirmations of the surfaced classifications — the
        skippable step whose skip is itself recorded (`FR-SETUP-14`, `R62`).

        Each entry names a criterion and the classification the teacher confirms; the
        rows already stored as `source='default'` (the module's table, written at
        classify time) are upserted to `source='teacher'` — the recorded distinction
        between a teacher's judgment and the system default that `M-CALIB` and
        `M-STATS` read. A classification outside the vocabulary, or a criterion the
        version does not carry, is refused; skipping the call entirely records
        nothing here and leaves the default rows standing, which is the point."""
        v = self._require_draft_version()
        if not answers:
            LOGGER.info("confirm_classifications confirmed nothing for version %s", v)
            return
        misplaced = sorted(
            criterion_id for criterion_id, classification in answers.items()
            if classification not in CLASSIFICATIONS
        )
        if misplaced:
            raise SetupError(
                f"classification(s) for {', '.join(misplaced)} are outside the "
                f"vocabulary {CLASSIFICATIONS} (FR-SETUP-06) — a confirmed "
                "classification is one the decision table could have produced."
            )
        known = {row["criterion_id"] for row in self._catalog.criteria(v)}
        unknown = sorted(set(answers) - known)
        if unknown:
            raise SetupError(
                f"confirmation names criterion(s) {', '.join(unknown)} that version "
                f"{v!r} does not carry — the teacher confirms criteria that exist."
            )
        reader = getattr(self._catalog, "classification", None)
        record = getattr(self._catalog, "record_classification", None)
        confirmed: dict[str, str] = {}
        for criterion_id, classification in answers.items():
            basis = None
            if reader is not None:
                prior = reader(v, criterion_id)
                if prior is not None:
                    basis = prior.get("decomposition_basis")
            if record is not None:
                record(v, criterion_id=criterion_id, classification=classification,
                       decomposition_basis=basis, source="teacher",
                       recorded_at=_now())
            confirmed[criterion_id] = classification
        self._record_decomposability_step(
            v, status="classifications_confirmed",
            update={"confirmed": confirmed,
                    "teacher_confirmed_count": len(confirmed)})
        LOGGER.info(
            "teacher confirmed %d classification(s) for version %s — recorded as "
            "'teacher' beside the module's 'default' rows (R62)", len(confirmed), v,
        )

    def propose_dependencies(self) -> tuple[DependencyProposal, ...]:
        """Propose the dependencies the subject makes likely (`FR-SETUP-10`, `#52`) —
        and write NOTHING: every criterion defaults to zero dependencies, and a
        proposal is words for the teacher to act on (`CT-SETUP-08`).

        One version-pinned model call proposes the edges; each comes back rendered in
        plain language naming both criteria and the reason — the sentence
        `FR-SETUP-10` gives the standard for. A version with no criteria proposes
        nothing (there is nothing to attach to). The proposals are recorded on the
        step's provenance row — the record `confirm_dependencies` approves against
        (`CT-SETUP-03`: state is the database) — and the step's base case, nothing
        likely, is recorded too rather than left indistinguishable from a skip."""
        v = self._require_draft_version()
        rows = self._catalog.criteria(v)
        known = frozenset(row["criterion_id"] for row in rows)
        if not known:
            LOGGER.info("version %s carries no criteria — no dependency proposal", v)
            return ()
        listing = [
            {"criterion_id": row["criterion_id"], "question_id": row["question_id"],
             "kind": row["kind"], "construct": row.get("construct_tag", "")}
            for row in rows
        ]
        payload = PromptPayload(fields=(
            ("instruction", _DEPENDENCIES_INSTRUCTION),
            ("criteria", json.dumps(listing, sort_keys=True)),
        ))
        budget = _configured_proposal_attempts()
        last_error = ""
        for attempt in range(1, budget + 1):
            try:
                completion = self._provider.complete(payload, self._model_ref,
                                                     self._params)
                triples = _parse_dependencies_reply(completion.text, known)
            except _ReplyError as error:
                last_error = f"attempt {attempt}: {error}"
                LOGGER.warning(
                    "dependency-proposal reply failed to parse (%d/%d): %s",
                    attempt, budget, error)
                continue
            except Exception as error:  # contained: the transport's failure is a
                # failed attempt (CT-SETUP-12's pattern).
                last_error = f"attempt {attempt}: {type(error).__name__}: {error}"
                LOGGER.warning("dependency-proposal attempt %d/%d failed: %s",
                               attempt, budget, error)
                continue
            proposals = tuple(
                DependencyProposal(criterion_id=criterion_id, depends_on=depends_on,
                                   reason=reason)
                for criterion_id, depends_on, reason in triples
            )
            self._record_dependency_proposals(v, proposals)
            LOGGER.info(
                "proposed %d dependency edge(s) for version %s in %d attempt(s), "
                "prompt %s — nothing written; approval is the teacher's act "
                "(FR-SETUP-10)", len(proposals), v, attempt,
                SETUP_DEPENDENCIES_TEMPLATE_V,
            )
            return proposals

        # The budget is spent: degraded but complete (`CT-SETUP-12`) — the default
        # (zero dependencies) stands, and the failure is on the step's record.
        self._record_dependency_proposals(v, (), status="dependencies_needs_review",
                                          reason=last_error)
        LOGGER.warning(
            "dependency proposals for version %s degraded to the zero-dependency "
            "default after %d attempt(s): %s", v, budget, last_error,
        )
        return ()

    def _record_dependency_proposals(
        self, v: PackageVersionId, proposals: Sequence[DependencyProposal],
        *, status: str | None = None, reason: str = "",
    ) -> None:
        """Write the dependency proposals into the step's provenance row — the
        proposals as recorded state (`CT-SETUP-03`), which `confirm_dependencies`
        approves against. The row is MERGED, not replaced (see
        `_record_decomposability_step`): a confirm_classifications call before or
        after this one must not erase the proposals. Skipped when the catalog
        offers no recording surface (the rung-0 doubles)."""
        if status is None:
            status = ("dependencies_proposed" if proposals
                      else "dependencies_none_proposed")
        self._record_decomposability_step(v, status=status, update={
            "proposals": [
                {"criterion_id": item.criterion_id,
                 "depends_on": item.depends_on,
                 "reason": item.reason,
                 "rendered": str(item)}
                for item in proposals
            ],
            "template_version": SETUP_DEPENDENCIES_TEMPLATE_V,
            **({"reason": reason} if reason else {}),
        })

    def confirm_dependencies(
        self,
        approved: Sequence[DependencyProposal | tuple[str, str] | Mapping],
    ) -> None:
        """The teacher's approval — the ONLY write path for a dependency edge
        (`FR-SETUP-10`, `CT-SETUP-08`).

        Each approval names a criterion pair; every pair must be among the proposals
        recorded on the step's row (approval confirms a proposal, not an idea), and
        the whole approved set is written in ONE `M-PKG` call — transactional, and
        cycle-refusing inside that transaction (a `PackageError` propagates
        unchanged, `CT-SETUP-12`). A dependency the teacher declines is simply absent:
        declining needs no call, and the empty graph it leaves is the design's base
        case."""
        v = self._require_draft_version()
        reader = getattr(self._catalog, "step_record", None)
        recorded = reader(v, "decomposability") if reader is not None else None
        proposed: set[tuple[str, str]] = set()
        payload: dict = {}
        if recorded is not None:
            try:
                loaded = json.loads(recorded["payload"])
            except (ValueError, TypeError):
                loaded = None
            if isinstance(loaded, dict):
                payload = loaded
            for item in payload.get("proposals", []):
                if isinstance(item, dict) and "criterion_id" in item \
                        and "depends_on" in item:
                    proposed.add((str(item["criterion_id"]),
                                  str(item["depends_on"])))
        if not proposed:
            raise SetupOrderError(
                f"no dependency proposal is recorded for version {v!r} — call "
                "propose_dependencies first; approval confirms a proposal, not an "
                "idea (FR-SETUP-10)."
            )
        pairs: list[tuple[str, str]] = []
        for item in approved:
            if isinstance(item, DependencyProposal):
                pairs.append((item.criterion_id, item.depends_on))
            elif isinstance(item, Mapping):
                pairs.append((str(item["criterion_id"]), str(item["depends_on"])))
            else:
                criterion_id, depends_on = item
                pairs.append((str(criterion_id), str(depends_on)))
        unproposed = sorted(set(pairs) - proposed)
        if unproposed:
            raise SetupError(
                f"approval names pair(s) {unproposed} that were never proposed for "
                f"version {v!r} — a dependency edge is written on the teacher's "
                "approval OF a proposal (FR-SETUP-10); hand-authored edges are "
                "M-PKG's own path."
            )
        # The edge is (before, after): `after` depends on `before` — the proposal's
        # `depends_on` is the earlier criterion whose credited work the later one
        # would see. Approving in batches ACCUMULATES: the graph write is a replace
        # (M-PKG's set_dependencies), so each approval writes the union of every
        # approval so far — read off this row's own recorded approvals, the
        # state-is-the-database rule — never just this batch, which would silently
        # un-approve an earlier one.
        merged: dict[tuple[str, str], dict] = {}
        for item in payload.get("approved", []):
            if isinstance(item, dict) and "criterion_id" in item \
                    and "depends_on" in item:
                merged[(str(item["criterion_id"]),
                        str(item["depends_on"]))] = item
        for criterion_id, depends_on in pairs:
            merged.setdefault((criterion_id, depends_on), {
                "criterion_id": criterion_id, "depends_on": depends_on})
        approved_pairs = list(merged.values())
        edges = [(item["depends_on"], item["criterion_id"])
                 for item in approved_pairs]
        self._catalog.set_dependencies(v, edges)
        self._record_decomposability_step(
            v, status="dependencies_approved",
            update={"approved": approved_pairs, "edge_count": len(edges)})
        LOGGER.info(
            "teacher approved %d dependency edge(s) for version %s — written in one "
            "M-PKG call (FR-SETUP-10)", len(edges), v,
        )

    def publish(self, approved_by: str) -> PackageVersionId:
        """Publish the version — the point the §6.2 lock takes effect (`FR-SETUP-02`).

        Both blocking gates are checked HERE and refused with the gate named: the
        confirmed inventory (gate 1) and every deterministic criterion keyed (gate 2).
        The publication itself is `M-PKG`'s one-transaction lock flip (`FR-PKG-01`) —
        setup assembles and gates; the Tier P writer writes (`CT-PKG-12`)."""
        v = self._require_draft_version()
        self._refuse_unmet_gates(v)
        self._record_uncompleted_step_default(v)
        self._catalog.publish(v, approved_by)
        LOGGER.info(
            "published package version %s by %r — both blocking gates satisfied; the "
            "§6.2 schema lock now holds (FR-SETUP-02)", v, approved_by,
        )
        return v

    # -- internals ----------------------------------------------------------------------------

    def _record_uncompleted_step_default(self, v: PackageVersionId) -> None:
        """Record the decomposability step's default where the step never recorded
        itself (`FR-SETUP-14`, `#52`): completing setup by skipping the step leaves
        stored provenance naming it, so the default is never indistinguishable from
        an explicit choice (`R62`, `CT-SETUP-01`). A step that DID record — the
        teacher confirmed classifications, or proposals were made — is never
        overwritten. The gate checks have already passed, so this write is on the
        publish path's happy tail, immediately before the lock flip."""
        record = getattr(self._catalog, "record_default_step", None)
        if record is None:
            return
        written = record(
            v, step_id="decomposability", status="default_taken",
            payload=json.dumps({
                "default": (
                    "the decomposability step was skipped: the §5.3 table's "
                    "verdicts stand as recorded (source 'default', holistic on any "
                    "unclear case) and dependencies stay at zero — no approval was "
                    "recorded (FR-SETUP-10)."
                ),
                "confirmations_requested":
                    self._confirmations_requested.get(v, 0),
                "confirmation_cap": SETUP_MAX_CONFIRMATIONS,
            }, sort_keys=True),
            recorded_at=_now(),
        )
        if written:
            LOGGER.info(
                "recorded the decomposability step's default for version %s — the "
                "skip is stored provenance, not silence (FR-SETUP-14)", v,
            )

    def _require_draft_version(self) -> PackageVersionId:
        """The draft the operation works on, or the honest refusal: a package whose
        setup has finished has a published version and no draft, and operating on a
        published version is not setup's business."""
        v = self._catalog.draft_version()
        if v is None:
            raise SetupOrderError(
                f"no unpublished version exists for package {self.package_id!r} — "
                "setup has already finished (its version is published) or the initial "
                "version was never minted: call ensure_version() first."
            )
        return v

    def _refuse_unmet_gates(self, v: PackageVersionId) -> None:
        """The two blocking gates, each refused with its number and its unblocking
        step — the console renders the refusal verbatim (`FR-CONSOLE-06`: exactly two
        screens block)."""
        stored = self._catalog.proposal(v)
        if stored is None or stored["confirmed_at"] is None:
            raise SetupOrderError(
                "publish refused: the question inventory is not confirmed — blocking "
                "gate 1 of 2 (§4.2.1). The teacher's confirmation is the assertion "
                "the §6.2 lock records (FR-SETUP-02): confirm_inventory first."
            )
        unkeyed = [
            row["criterion_id"] for row in self._catalog.criteria(v)
            if row.get("scoring_model") == "atomic" and not row.get("answer_key")
        ]
        if unkeyed:
            raise SetupOrderError(
                "publish refused: answer keys missing for the deterministic criteria "
                f"{', '.join(unkeyed)} — blocking gate 2 of 2 (§4.2.1): "
                "set_answer_keys first."
            )
