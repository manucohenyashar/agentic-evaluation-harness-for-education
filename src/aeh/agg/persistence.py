"""Writing an aggregated score, and recording a teacher's review decision on it."""

from __future__ import annotations

import json
from typing import Any

from .rows import _stored_signal
from .records import CriterionScore
from .schema import AGG_STATEMENTS


def record_review(
    tx: Any, run_id: str, submission_id: str, criterion_id: str, band: str,
    points: float | None,
) -> None:
    """Record a teacher's review decision on the stored score row (#517, CT-REVIEW-06): the
    band and points the reviewer settled on, routing `reviewed`, state `final`. M-GRADE's next
    pass counts the criterion as reviewed, no longer provisional. Runs in the caller's
    transaction, like `write_score`, and never opens one; a non-transaction is refused."""
    if not callable(getattr(tx, "execute", None)):
        raise TypeError("record_review needs the caller's open transaction")
    tx.execute(AGG_STATEMENTS["record_review"], run_id=run_id, submission_id=submission_id,
               criterion_id=criterion_id, band=band, points=points)


def write_score(
    tx: Any, run_id: str, submission_id: str, score: CriterionScore, signals: Any
) -> None:
    """Persist one aggregated score in the caller's transaction (`FR-AGG-15`, `CT-AGG-18/19`).

    Upserts the row keyed `(run_id, submission_id, criterion_id)` with every field
    of `score` and all six integrity signals from `signals` (`FR-AGG-13`
    amended): each stored 0/1, `None` stored `NULL` — "not measured" stays
    distinguishable from a measured `False`. `caps_fired` is the JSON list of the
    caps that bound (`[]` when none). Idempotent: an identical second call
    leaves one unchanged row; a changed score updates it.

    `tx` must be a transaction the caller opened (`with handle.transaction() as
    tx`): this function never opens, commits or rolls one back, so a caller's
    rollback removes the row. Anything that is not a transaction — a tier
    handle, which has no `execute` — is refused with `TypeError` before any
    write.
    """
    if not callable(getattr(tx, "execute", None)):
        raise TypeError(
            f"write_score needs the caller's open transaction (CT-AGG-19), got "
            f"{type(tx).__name__}: open one with `with handle.transaction() as tx`."
        )
    tx.execute(
        AGG_STATEMENTS["upsert_criterion_score"],
        run_id=run_id,
        submission_id=submission_id,
        criterion_id=score.criterion_id,
        band=score.band,
        modal_band=score.modal_band,
        band_spread=score.band_spread,
        points=score.points,
        judge_count=score.judge_count,
        agreement=score.agreement,
        confidence=score.confidence,
        confidence_base=score.confidence_base,
        spans_verified=_stored_signal(getattr(signals, "spans_verified", None)),
        evidence_present=_stored_signal(getattr(signals, "evidence_present", None)),
        sufficiency_flag=_stored_signal(getattr(signals, "sufficiency_flag", None)),
        ocr_overlap_risk=_stored_signal(getattr(signals, "ocr_overlap_risk", None)),
        described_evidence=_stored_signal(getattr(signals, "described_evidence", None)),
        extractor_disagreement=_stored_signal(
            getattr(signals, "extractor_disagreement", None)
        ),
        caps_fired=json.dumps(list(score.caps_fired)),
        routing=score.routing,
        state=score.state,
        state_reason=getattr(score, "state_reason", None),
    )
