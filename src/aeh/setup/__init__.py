"""M-SETUP: Stage A, turning a teacher's assessment into a published package (design §3.6).

Setup walks a teacher through a fixed sequence of steps for one package version:

1. A model proposes the question inventory from the assessment document; the teacher
   confirms or corrects it (blocking gate 1).
2. A model reads the rubric back into criteria and band sets.
3. The teacher enters answer keys for multiple-choice questions (blocking gate 2) and the
   grade policy, and the prompt prefixes are checked against the token budget.
4. Each criterion is classified for decomposability against five questions, with a capped
   number of teacher confirmations; likely dependencies between criteria are proposed and
   only become edges when the teacher approves them.
5. The version is published, after which the package is locked.

Every step records its outcome through M-PKG, so a console can resume a half-finished setup.

Files:
    settings.py        prompt versions, attempt budgets, the confirmation cap and other knobs
    errors.py          the errors this package raises
    records.py         proposals, drafts, verdicts and the progress report
    prompts.py         the instructions sent to the model at each step
    inventory.py       the inventory step: propose, correct and confirm the questions
    readback.py        the rubric read-back step
    keys_and_policy.py answer keys, the grade policy, the prefix budget and calibration papers
    decomposability.py classifying criteria and the teacher's confirmations
    dependencies.py    proposing criterion dependencies and the teacher's approval
    progress.py        the step list and what remains
    service.py         `SetupService`, which runs the steps and publishes the version
"""

from __future__ import annotations

from aeh.pkg import default_grade_policy
from aeh.prov import ModelRef

from .settings import (
    CLASSIFICATIONS,
    CLASSIFY_ATTEMPTS_DEFAULT,
    CLASSIFY_ATTEMPTS_ENV,
    CONFIRMATIONS_DEFAULT,
    CONFIRMATIONS_ENV,
    FIVE_QUESTIONS,
    LOGGER,
    _prefix_ceiling,
    PROPOSAL_ATTEMPTS_DEFAULT,
    PROPOSAL_ATTEMPTS_ENV,
    READBACK_ATTEMPTS_DEFAULT,
    READBACK_ATTEMPTS_ENV,
    SCORING_MODELS,
    SETUP_CLASSIFY_TEMPLATE_V,
    SETUP_DEFAULT_BAND_COUNT,
    SETUP_DEPENDENCIES_TEMPLATE_V,
    SETUP_EVIDENCE_TYPE_DEFAULT,
    SETUP_MAGNITUDE_PHRASES,
    SETUP_MAX_CONFIRMATIONS,
    SETUP_MCQ_BAND_NAMES,
    SETUP_PREFIX_TOKEN_CEILING_DEFAULT,
    SETUP_PROMPT_TEMPLATE_V,
    SETUP_READBACK_TEMPLATE_V,
)
from .errors import SetupError, SetupOrderError
from .records import (
    CriterionDraft,
    DecomposabilityVerdict,
    DependencyProposal,
    InventoryProposal,
    PrefixBudgetReport,
    ProposedBand,
    ProposedOption,
    ProposedQuestion,
    QuestionCorrection,
    RubricReadback,
    SetupProgress,
    SetupStep,
)
from .prompts import _INVENTORY_INSTRUCTION
from .inventory import InventoryStepMixin
from .readback import ReadbackStepMixin
from .keys_and_policy import KeysAndPolicyMixin
from .decomposability import DecomposabilityMixin
from .dependencies import DependencyStepMixin
from .progress import ProgressMixin
from .service import setup_service_for_store, SetupService


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
    "PrefixBudgetReport",
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
    "SETUP_MCQ_BAND_NAMES",
    "SETUP_PREFIX_TOKEN_CEILING_DEFAULT",
    "SETUP_PROMPT_TEMPLATE_V",
    "SETUP_READBACK_TEMPLATE_V",
    "SetupError",
    "SetupOrderError",
    "SetupProgress",
    "SetupService",
    "SetupStep",
]
