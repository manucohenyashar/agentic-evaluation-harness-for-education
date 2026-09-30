"""What setup produces: proposals, criterion drafts, verdicts, and the progress report."""

from __future__ import annotations

from dataclasses import dataclass

from aeh.ingest import DocumentId
from aeh.pkg import PackageVersionId

from .settings import SETUP_EVIDENCE_TYPE_DEFAULT


@dataclass(frozen=True)
class ProposedOption:
    """One option of a proposed `mcq` or `mixed` question, exactly as proposed.

    No correctness field — ADR-1's rule travels with the option set: correctness is
    the answer key, a separate blocking step (`FR-PKG-17`, S4)."""

    option_id: str
    ordinal: int
    label: str


@dataclass(frozen=True)
class ProposedQuestion:
    """One question exactly as the model proposed it (FR-SETUP-01): the prompt text word for word,
    a `question_type` from `aeh.pkg.QUESTION_TYPES`, and the options for an `mcq` or `mixed`
    question. The teacher confirms or corrects this, never a paraphrase."""

    question_id: str
    ordinal: int
    prompt_text: str
    question_type: str
    max_points: float
    options: tuple[ProposedOption, ...]


@dataclass(frozen=True)
class QuestionCorrection:
    """One correction the teacher makes when confirming the inventory.

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
    """A version's stored proposal, rebuilt from its row.

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
    """One band of a read-back criterion, in stored order: ordinals from 0 and points never
    decreasing (FR-PKG-06), so a judge's fallback band is the lowest, never a safe middle. The
    model ranks bands best first; `read_back_rubric` reorders them."""

    band: str
    ordinal: int
    points: float
    descriptor: str


@dataclass(frozen=True)
class CriterionDraft:
    """One criterion as the read-back proposes it. The decomposability step classifies it, and the
    teacher's confirmation makes it part of the package.

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
    #: `FR-SETUP-17` / `FR-PKG-22`: how this criterion is EVALUATED — `deterministic`
    #: for FR-SETUP-13's criteria, `judged` for everything else. Distinct from `kind`,
    #: which says what shape the criterion is: a package may declare a multiple-choice
    #: criterion whose options a panel weighs, and the two fields are what let it.
    evaluation_mode: str = "judged"
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
    """A version's stored read-back, rebuilt from its row.

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


@dataclass(frozen=True)
class DecomposabilityVerdict:
    """One criterion's decomposability outcome (design §3.6).

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
    """One proposed dependency between criteria (FR-SETUP-10). Only a proposal: every criterion
    starts with none, and an edge exists only once the teacher approves it (CT-SETUP-08).

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
class PrefixBudgetReport:
    """What `check_prefix_budget` found (FR-SETUP-11): for each (question, criterion) pair, the
    token count and the ceiling it was compared with, what was dropped to fix an overage, and what
    is still over.

    `over_budget` is the POST-remediation fact: true when some pair's assembled prefix
    still exceeds the ceiling AFTER the drop policy ran (the drops stop at the
    calibration floor, so a prefix that cannot shrink further without stripping a
    band's last exemplar reports its residual honestly). Which exemplars were dropped
    is ON the report (`dropped_exemplars`, in drop order) — a silent drop would leave
    the teacher unable to audit what left the prefix. `per_pair` carries one entry per
    (question, criterion) pair; the report never re-reads storage."""

    package_version_id: str | None
    ceiling_tokens: int
    over_budget: bool
    dropped_exemplars: tuple[str, ...]
    per_pair: tuple[dict, ...] = ()
    residual_tokens: int = 0
    note: str = ""

    def __str__(self) -> str:
        if not self.over_budget and not self.dropped_exemplars:
            return (f"prefix budget OK: every assembled prefix fits the "
                    f"{self.ceiling_tokens}-token ceiling.")
        head = (f"prefix budget: {len(self.dropped_exemplars)} exemplar(s) dropped "
                f"to fit the {self.ceiling_tokens}-token ceiling")
        if self.over_budget:
            head += (f"; {self.residual_tokens} token(s) still over — the "
                     "calibration floor holds each band's last exemplar")
        return head + "."


@dataclass(frozen=True)
class SetupStep:
    """One setup step as the console shows it (NFR-SETUP-04, FR-CONSOLE-25).

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
    """The setup state of one package version, for the console and headless callers: the steps, the
    number that remain (available and not done), and whether both publish gates would pass now."""

    package_version_id: PackageVersionId | None
    steps: tuple[SetupStep, ...]
    remaining_steps: int
    ready_to_publish: bool

    def headline(self) -> str:
        """The console's one-line summary (NFR-SETUP-04): `setup incomplete — N steps remain`, the
        ready line, or, with no draft version, the finished or not-started line. Zero remaining
        reads as ready, because a count of steps nobody can act on would mislead."""
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
