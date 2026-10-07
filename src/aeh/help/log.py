"""The Q&A log (FR-HELP-04, CT-HELP-04/05): the module's only write surface, one appended row
per exchange, and its read side ``qa_log``.

The row is written in one synchronous transaction on the Tier D handle — the store's only write
door for this module — and carries no cohort, roster, submission or grade column: the question
is the teacher's own words, the anchors name manual headings, and the model ref names the
resolved QA model (`CT-HELP-03`; the request sweep `TC-HELP-04` holds the model requests
themselves to the same rule).
"""

from __future__ import annotations

import json
from typing import Any

from aeh.help.schema import HELP_STATEMENTS

OUTCOME_GROUNDED = "grounded"
OUTCOME_NOT_FOUND = "not-found"

#: The two log outcomes; the schema's CHECK constraint admits exactly these (`FR-HELP-04`).
OUTCOMES = (OUTCOME_GROUNDED, OUTCOME_NOT_FOUND)


def record_exchange(store: Any, *, question: str, cited_anchors: list[str], model_ref: str,
                    tokens_in: int, tokens_out: int, latency_ms: float, outcome: str,
                    recorded_at: str) -> None:
    """Append one exchange to the Q&A log. ``cited_anchors`` is stored as a JSON array of anchor
    strings — written once, read whole (`CT-HELP-05`); ``tokens_in``/``tokens_out`` are 0 when
    no model was called, which is the not-found path."""
    if outcome not in OUTCOMES:
        raise ValueError(
            f"outcome {outcome!r} is not one of {OUTCOMES}; the log's schema admits only "
            "'grounded' and 'not-found' (FR-HELP-04), so an unknown outcome must fail here "
            "rather than die as a raw constraint error at commit."
        )
    with store.durable().transaction() as tx:
        tx.execute(
            HELP_STATEMENTS["insert_qa_exchange"],
            question=question,
            cited_anchors=json.dumps(cited_anchors),
            model_ref=model_ref,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            outcome=outcome,
            recorded_at=recorded_at,
        )


def qa_log(store: Any) -> list[dict[str, Any]]:
    """The Q&A log, oldest first, one mapping per exchange with ``cited_anchors`` parsed back
    to its anchor strings — the read side the accountability story reads."""
    rows = store.durable().query(HELP_STATEMENTS["read_qa_log"])
    return [
        {
            "exchange_id": row["exchange_id"],
            "question": row["question"],
            "cited_anchors": json.loads(row["cited_anchors"]),
            "model_ref": row["model_ref"],
            "tokens_in": row["tokens_in"],
            "tokens_out": row["tokens_out"],
            "latency_ms": row["latency_ms"],
            "outcome": row["outcome"],
            "recorded_at": row["recorded_at"],
        }
        for row in rows
    ]
