"""The six integrity signals and how each is computed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .settings import _verification_disabled
from .verification import _FAULT, _span_items


# --- the per-verify derivations (each read's fault lands on the adverse value) ---------------------


def _verification_outcome(
    raw: "bytes | None",
    span_items: "list[tuple[int, int, bytes]] | None",
    citation: bool,
) -> "tuple[bool, bool]":
    """`(spans_verified, evidence_present)` for this verify's span read.

    The disabled switch, a faulted span read, or an unreadable document all
    report `(False, False)` — nothing was verified, so no evidence can be
    claimed present (fail-closed, CT-INTEG-03). An EMPTY span set is the one
    measured absence: `evidence_present` is False, and `spans_verified` is
    vacuously True only when the criterion demands no citation (nothing was
    claimed, so nothing failed to match). With spans in hand, the verdict is
    the shared invariant over every span and evidence is present the moment
    ONE span passed."""
    if _verification_disabled():
        return (False, False)
    if raw is None or span_items is None:
        return (False, False)
    if not span_items:
        return (not citation, False)
    verdicts = [
        0 <= start <= end <= len(raw) and raw[start:end] == text_bytes
        for start, end, text_bytes in span_items
    ]
    return (all(verdicts), any(verdicts))


def _region_signals(
    region_items: "tuple[tuple[Any, int, int, Any, Any], ...] | None",
    span_items: "list[tuple[int, int, bytes]] | None",
    floor: float,
) -> "tuple[bool, bool, Any]":
    """`(ocr_overlap_risk, described_evidence, crop_ref)` for this verify.

    A faulted region read — or a span read that left the cited extents
    unknown — flags both routing-candidate values and carries no crop: an
    unknown overlap cannot be certified clear and an unknown placement cannot
    be certified outside a described graphic (CT-INTEG-03's fail-closed
    reading). With both reads healthy: an at-risk transcription is a region
    whose recorded confidence sits AT OR BELOW the floor and whose extent
    overlaps a cited span (half-open, so merely touching extents do not
    overlap); described evidence is a cited span lying WHOLLY inside one
    described-graphic region — geometric, regardless of whether the span
    verified."""
    if region_items is None or span_items is None:
        return (True, True, None)
    ocr_risk = False
    described = False
    crop_ref: Any = None
    for kind, r_start, r_end, conf, crop in region_items:
        if (
            conf is not None
            and conf <= floor
            and any(
                r_start < s_end and s_start < r_end
                for s_start, s_end, _ in span_items
            )
        ):
            ocr_risk = True
        if kind == "described_graphic" and not described:
            if any(
                r_start <= s_start and s_end <= r_end
                for s_start, s_end, _ in span_items
            ):
                described = True
                crop_ref = crop
    return (ocr_risk, described, crop_ref)


def _disagreement_verdict(
    second: Any,
    span_items: "list[tuple[int, int, bytes]] | None",
) -> "bool | None":
    """The extractor-disagreement tri-state for this verify.

    `None` only when no second family was configured — distinguishable from
    False by identity, never by truthiness. A faulted read or a malformed
    second payload reports True (measured-and-adverse: the second extraction
    ran, so "not measured" would be a lie); a healthy read reports whether the
    two families produced different span sets, fingerprinted by
    (start, end, text bytes) so the comparison is over the bytes themselves."""
    if second is _FAULT:
        return True
    if second is None:
        return None
    second_items = _span_items(second)
    if span_items is None or second_items is None:
        return True
    first_prints = {(start, end, text) for start, end, text in span_items}
    second_prints = {(start, end, text) for start, end, text in second_items}
    return first_prints != second_prints


def _computed_insufficient(panel_flags: "tuple[bool, ...] | None") -> bool:
    """The panel's COMPUTED insufficiency — the routing input, never the
    reported flag: any member reporting the evidence insufficient. A faulted
    panel read is insufficient (fail-closed)."""
    if panel_flags is None:
        return True
    return any(not flag for flag in panel_flags)


def _failure_rate(
    raw: "bytes | None",
    span_items: "list[tuple[int, int, bytes]] | None",
    verified: bool,
) -> float:
    """The cell's span-verification failure rate (1.0 or 0.0).

    A rate that moves only when the extractor hallucinated: 1.0 when spans
    were READ — the document resolved and at least one span arrived — and
    verification still failed. An empty cell had no verification to fail, and
    a read fault is a data problem, not a hallucination; neither moves it."""
    if raw is not None and span_items and not verified:
        return 1.0
    return 0.0


# --- the returned signal surface (CT-INTEG-02: six fields, by set equality) ------------------------


@dataclass(frozen=True)
class IntegritySignals:
    """The six signals, and nothing else (FR-INTEG-01; CT-INTEG-04's output half).

    `extractor_disagreement` is tri-state: `None` when no second extraction ran,
    `True`/`False` when one ran and disagreed/agreed — a consumer collapsing
    `None` into `False` reads "not measured" as "measured, and fine"."""

    spans_verified: bool
    evidence_present: bool
    sufficiency_flag: bool
    ocr_overlap_risk: bool
    described_evidence: bool
    extractor_disagreement: "bool | None"
