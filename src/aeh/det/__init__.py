"""M-DET: scores multiple-choice criteria by exact lookup against the answer key (design §3.11).

A deterministic criterion is scored without any model: the student's recorded selection is
compared with the key under the criterion's partial-credit policy. Anything that cannot be
read cleanly (a blank, an ambiguous mark, several marks on a single-select question) is left
unresolved and routed to a person rather than guessed. M-DET also keeps per-question item
statistics and re-derives scores when a key is corrected.

Files:
    constants.py        band names, states, reasons, evaluation modes and the alert-rate knob
    errors.py           the errors this package raises
    kernel.py           `evaluate`: one selection against one key, the pure scoring rule
    schema.py           migrations and the SQL statements
    records.py          the report and row types returned to callers
    ledger.py           small shared reads of the run ledger and the package
    selection_reads.py  reading each question's recorded selection from the ingested document
    rederive.py         re-deriving scores after an answer-key correction
    item_stats.py       per-question item statistics
    evaluator.py        `DeterministicEvaluator`: scores a criterion or a whole cohort
"""

from __future__ import annotations

from .constants import (
    BAND_CORRECT,
    BAND_INCORRECT,
    BAND_UNRESOLVED,
    CONTENT_STATES,
    DECIDED_BY_SYSTEM,
    DEFAULT_UNRESOLVED_ALERT_RATE,
    DETERMINISTIC_EXCLUSION,
    EVALUATION_MODE_DETERMINISTIC,
    EVALUATION_MODE_JUDGED,
    EVALUATION_MODES,
    PARTIAL_CREDIT_POLICIES,
    POLICY_ALL_OR_NOTHING,
    POLICY_PER_OPTION,
    REASON_ABSENT_REGION,
    REASON_AMBIGUOUS_MARK,
    REASON_BLANK,
    REASON_KEY_MATCH,
    REASON_KEY_MISS,
    REASON_MULTIPLE_MARKS,
    REASON_NO_SELECTION_READ,
    REASON_SELECTION_OUTSIDE_OPTION_SET,
    REASON_SINGLE_SELECT_MULTIPLE,
    ROUTING_AUTO,
    ROUTING_TRIAGE,
    SELECTION_STATES,
    STATE_FINAL,
    STATE_UNRESOLVED_SELECTION,
    unresolved_alert_rate,
    UNRESOLVED_ALERT_RATE_ENV,
)
from .errors import (
    DeterministicError,
    MalformedAnswerKey,
    MalformedSelectionRead,
    NotDeterministicCriterion,
    UndeclaredPartialCreditPolicy,
    UnknownCohort,
    UnknownCriterion,
    UnknownPartialCreditPolicy,
    UnknownRun,
)
from .kernel import DetOutcome, evaluate
from .schema import DET_STATEMENTS
from .records import (
    CriterionScore,
    CriterionSummary,
    DeterministicReport,
    ItemOptionCount,
    ItemStatsEntry,
    ItemStatsReport,
    RederiveChange,
    RederiveReport,
    SelectionRead,
)
from .ledger import _newest_run
from .selection_reads import SelectionReadingMixin
from .rederive import KeyCorrectionMixin
from .item_stats import ItemStatisticsMixin
from .evaluator import DeterministicEvaluator
