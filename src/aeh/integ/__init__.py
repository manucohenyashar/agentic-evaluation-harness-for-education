"""M-INTEG: the integrity gate between extraction and judging (design §3.9).

For every (submission, criterion) cell the gate checks that each extracted span's text is
really in the canonical document, byte for byte, and computes six signals: whether the spans
verified, whether any evidence is present, OCR-overlap risk, described (non-text) evidence,
extractor disagreement, and insufficiency. From those signals it routes the cell: on to the
judges, back for another extraction attempt, or to human review. It never scores anything.

Files:
    schema.py        migrations, the SQL statements, and the rate metric names
    settings.py      thresholds and switches, each with its environment knob
    verification.py  `verify_span`, `relocate_span` (quote-anchored relocation, region-scoped),
                     `clear_of_region_markup`, `answer_regions`, and the span/region/byte readers
    signals.py       computing the six signals (`IntegritySignals`)
    view.py          `StoreExtractionView`, the store-backed read the gate uses in production
    gate.py          `IntegrityGate`, which verifies a cell and routes it

Detailed design notes (the full original module description): `docs/code-notes/integ.md`.
"""

from __future__ import annotations

from .schema import ALERT_SPAN_VERIFICATION_FAILURES, INTEG_RATE_METRICS, INTEG_STATEMENTS
from .settings import (
    _DISABLED_ENV,
    _document_cache_entries,
    INTEG_DOCUMENT_CACHE_ENTRIES,
    INTEG_DOCUMENT_CACHE_ENTRIES_ENV,
    _verification_disabled,
)
from .verification import (
    Span,
    _region_items,
    _span_items,
    answer_regions,
    clear_of_region_markup,
    relocate_span,
    verify_span,
)
from .signals import IntegritySignals, _region_signals
from .view import StoreExtractionView
from .gate import IntegrityGate


__all__ = [
    "ALERT_SPAN_VERIFICATION_FAILURES",
    "INTEG_RATE_METRICS",
    "INTEG_STATEMENTS",
    "IntegrityGate",
    "IntegritySignals",
    "Span",
    "answer_regions",
    "clear_of_region_markup",
    "relocate_span",
    "verify_span",
]
