"""M-AGG: combines a panel of judge verdicts into one criterion score (design §3.12).

The score's band is the median of the judges' bands, and points come from the band through the
package's one band-to-points mapping. Each score also carries a confidence figure: the panel's
agreement (Krippendorff's ordinal alpha) or, for a single judge, a prior for the band's
position, reduced by caps for uncited verdicts, holistic criteria and adverse integrity
signals. The confidence is a ranking figure, not a probability. M-AGG also decides whether a
cell should be escalated to more judges, and ranks criteria by how urgently they need review.

Files:
    errors.py         the errors this package raises
    settings.py       confidence thresholds, caps and escalation weights
    rows.py           tolerant reads of stored score rows and their integrity signals
    records.py        `CriterionScore`, the aggregated score
    agreement.py      Krippendorff's ordinal alpha and how an agreement figure is described
    aggregate.py      `aggregate`: a panel of verdicts in, one score out
    recompute.py      recomputing a stored score's confidence from the stored row alone
    schema.py         migrations and the SQL statements
    persistence.py    writing a score and recording a teacher's review
    metrics.py        per-criterion aggregation signals for a run
    escalation.py     `should_escalate` and the escalation ranking of criteria
"""

from __future__ import annotations

from aeh.pkg import points_for_band

from .errors import AggregateError, EmptyVerdictsError, EvenPanelError, PanelCorrelationError
from .settings import (
    AGG_AUTO_THRESHOLD_ATOMIC,
    AGG_AUTO_THRESHOLD_HOLISTIC,
    AGG_CAP_TABLE,
    AGG_ESCALATION_ANOMALY_SIGMA,
    AGG_ESCALATION_NO_DATA_WEIGHT,
    AGG_ESCALATION_OVERRIDE_RATE,
    AGG_ESCALATION_SELF_CONFIDENCE_WEIGHT,
    AGG_ESCALATION_SIGNAL_WEIGHT,
    AGG_ESCALATION_THRESHOLD,
    AGG_HOLISTIC_MULTIPLIER,
    AGG_UNCITED_MULTIPLIER,
)
from .rows import adverse_signal_count
from .records import CriterionScore
from .agreement import describe_agreement, ordinal_alpha
from .aggregate import (
    aggregate,
    aggregate_even_panel_after_quarantine,
    EVEN_PANEL_AFTER_QUARANTINE,
)
from .recompute import recompute_confidence
from .schema import AGG_SIGNAL_STATEMENTS, AGG_STATEMENTS
from .persistence import record_review, write_score
from .metrics import aggregation_signals, AggregationSignals
from .escalation import (
    CriterionEscalationRank,
    EscalationDecision,
    rank_criteria_for_escalation,
    should_escalate,
)


__all__ = [
    "AGG_AUTO_THRESHOLD_ATOMIC",
    "AGG_AUTO_THRESHOLD_HOLISTIC",
    "AGG_CAP_TABLE",
    "AGG_ESCALATION_ANOMALY_SIGMA",
    "AGG_ESCALATION_OVERRIDE_RATE",
    "AGG_ESCALATION_NO_DATA_WEIGHT",
    "AGG_ESCALATION_SELF_CONFIDENCE_WEIGHT",
    "AGG_ESCALATION_SIGNAL_WEIGHT",
    "AGG_ESCALATION_THRESHOLD",
    "AGG_HOLISTIC_MULTIPLIER",
    "AGG_UNCITED_MULTIPLIER",
    "AggregateError",
    "CriterionEscalationRank",
    "CriterionScore",
    "EmptyVerdictsError",
    "EscalationDecision",
    "EVEN_PANEL_AFTER_QUARANTINE",
    "EvenPanelError",
    "aggregate_even_panel_after_quarantine",
    "PanelCorrelationError",
    "aggregate",
    "AGG_STATEMENTS",
    "AggregationSignals",
    "aggregation_signals",
    "describe_agreement",
    "ordinal_alpha",
    "rank_criteria_for_escalation",
    "adverse_signal_count",
    "recompute_confidence",
    "write_score",
    "should_escalate",
]
