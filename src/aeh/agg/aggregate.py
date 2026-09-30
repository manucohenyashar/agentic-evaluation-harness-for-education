"""`aggregate`: turns a panel of verdicts into one criterion score with a confidence."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from aeh.pkg import PackageError, points_for_band

from .errors import EmptyVerdictsError, EvenPanelError, PanelCorrelationError
from .settings import (
    AGG_AUTO_THRESHOLD_ATOMIC,
    AGG_AUTO_THRESHOLD_HOLISTIC,
    AGG_CAP_TABLE,
    AGG_HOLISTIC_MULTIPLIER,
    AGG_UNCITED_MULTIPLIER,
)
from .rows import _AGG_FAVOURABLE, _row_field, _row_value, _signal_adverse
from .records import CriterionScore
from .agreement import ordinal_alpha, _verdict_ordinal


# --- the aggregation -------------------------------------------------------------------------------


def _band_row(row: Any, field_name: str) -> Any:
    """Read one field of a band, whether the band is a store row (from M-PKG's catalog cache) or a
    band value carried on the criterion (CT-PKG-04)."""
    if isinstance(row, dict):
        return row[field_name]
    return getattr(row, field_name)


def _band_by_ordinal(criterion: Any, ordinal: int) -> Any:
    """The criterion's declared band with this ordinal. Ordinals are unique (CT-PKG-04), so the
    match is exact."""
    for row in criterion.bands:
        if _band_row(row, "ordinal") == ordinal:
            return row
    raise PackageError(
        f"criterion {criterion.criterion_id!r} declares no band at ordinal {ordinal!r}."
    )


def _verdict_cited(verdict: Any) -> bool:
    """Whether a judge's verdict cites its evidence. M-JUDGE marks uncited verdicts, so a verdict
    without the mark counts as cited (design §3.12).

    `cited` is the declared field (the test vocabulary's shape); `cited_spans`
    is the consumer-constructed shape the `#76` file reconciled (an uncited
    verdict carries no spans). Absent both, the verdict is read as cited — the
    mark is the signal, and this module does not invent one.
    """
    cited = getattr(verdict, "cited", None)
    if cited is not None:
        return bool(cited)
    spans = getattr(verdict, "cited_spans", None)
    if spans is not None:
        return bool(spans)
    return True


def _band_position_prior(ordinal: int, band_count: int) -> float:
    """The confidence base for a single judge: a prior that depends only on the band's position,
    higher for the extreme bands (design §3.12).

    The design names the shape and no numbers; this implementation declares them
    (the α-convention precedent, recorded for review): the prior rises linearly
    with how far the named band sits from the scale's centre, from 0.50 at the
    centre to 0.75 at an extreme. A single judge who named an extreme band has
    placed the work at the scale's edge with no panel to contradict them; the
    figure tops out below the atomic auto-accept threshold (0.75 < 0.80), which
    is the property the shape wants: one judge's word alone, however placed, is
    never sufficient to auto-accept. The figure never exceeds 1.0 — the
    single-judge domain bound TC-AGG-10's no-cap cell pins.
    """
    bands = int(band_count)
    if bands <= 1:
        # One declared band: the panel is unanimous on it by construction
        # (unreachable per CT-PKG-04's band_count >= 2, kept for honesty).
        return 1.0
    center = (bands - 1) / 2
    extremity = 2.0 * abs(int(ordinal) - center) / (bands - 1)
    return 0.50 + 0.25 * extremity


def _confidence_base(verdicts: Sequence[Any], criterion: Any) -> float:
    """The starting confidence figure: the panel's ordinal alpha for three or more judges, or the
    band-position prior for a single judge (design §3.12).

    The α term is computed **without** the criterion — §3.12's literal form —
    so the base is a property of the panel's own scale. For a panel whose
    valuations never reach the declared top band, the inferred scale is smaller
    than the declared one and the inferred α is the SMALLER figure
    (α = 1 − 3·D̄/(K+1) grows with K), which is exactly the reading TC-AGG-10's
    no-cap cell pins as its ceiling: the confidence never exceeds the panel's
    own α. The score's `agreement` field stays α on the DECLARED scale (#91's
    convention), so the base is recorded beside it (`confidence_base`) rather
    than conflated with it.
    """
    if len(verdicts) >= 3:
        return ordinal_alpha(verdicts)
    return _band_position_prior(_verdict_ordinal(verdicts[0]), criterion.band_count)


def aggregate(
    verdicts: Sequence[Any],
    criterion: Any,
    signals: Any,
    *,
    config: Any = None,
    fallback: bool = False,
    breaker_tripped: bool = False,
    deterministic_score: Any = None,
) -> CriterionScore:
    """Combine a panel's verdicts into one criterion score (FR-AGG-01..04), with its confidence
    (FR-AGG-05, FR-AGG-13, NFR-AGG-04), its routing and its state (FR-AGG-07, -10, -11, -12).

    More detail: `docs/code-notes/agg.md`, section `aggregate.py: aggregate`.
    """
    # The deterministic pass-through (FR-AGG-10) is its own entry and is checked
    # first: an empty panel is exactly how a row judged without a panel arrives,
    # so this entry must come before the empty-panel refusal it is the marked
    # alternative to. A non-empty panel alongside a row is a contradictory call.
    if deterministic_score is not None:
        if len(verdicts) != 0:
            raise ValueError(
                "aggregate received both a verdict panel and a deterministic score — "
                "FR-AGG-10's entry is for rows judged without a panel; the two are "
                "never combined."
            )
        return _passthrough_score(deterministic_score, criterion)
    if len(verdicts) == 0:
        raise EmptyVerdictsError(
            "aggregate over an empty verdict set is a programming error (CT-AGG-12): "
            "it is never a zero, a lowest band, or a null score."
        )
    # FR-AGG-18: the only place aggregation reads a verdict's engine. Everything below is
    # engine-blind (FR-AGG-19, CT-AGG-23): a decision-engine verdict is a verdict.
    decision_verdicts = sum(
        1 for verdict in verdicts if _row_field(verdict, "scoring_engine") == "decision")
    if decision_verdicts > 1:
        raise PanelCorrelationError(
            f"aggregate refuses a panel carrying {decision_verdicts} decision-engine verdicts "
            f"(FR-AGG-18): two answers from one near-deterministic engine are one opinion "
            f"counted twice, never agreement (CT-JUDGE-21, CT-AGG-22)."
        )
    if len(verdicts) % 2 == 0:
        if fallback and len(verdicts) == 2:
            # The two-verdict discard (FR-AGG-12), composed with the even-panel
            # refusal: the ONE even case with a declared fallback — a panel left
            # at exactly two by an unrecoverable judge failure. The second
            # verdict is discarded, never adjudicated between: two judges whose
            # verdicts disagree is a coin flip a rule would present as a
            # judgement (R48). The base single-judge band is kept and the score
            # is provisional — never a rounded verdict, never a settled panel.
            single = aggregate(
                verdicts[:1],
                criterion,
                signals,
                config=config,
                breaker_tripped=breaker_tripped,
            )
            return replace(
                single,
                notes=single.notes
                + (
                    "second verdict discarded: panel left at two by an unrecoverable "
                    "failure — the base single-judge band is kept, never adjudicated "
                    "between the two (FR-AGG-12)",
                ),
            )
        raise EvenPanelError(
            f"a panel of {len(verdicts)} judges is even — an even panel is a failed "
            "write, not a rounded verdict (FR-AGG-03): escalate 1 → 3, never to 2. "
            "(A panel left at exactly two by an unrecoverable failure is the one "
            "fallback: mark it with fallback=True, FR-AGG-12.)"
        )

    ordinals = sorted(_verdict_ordinal(v) for v in verdicts)
    median_ordinal = ordinals[len(ordinals) // 2]
    median_row = _band_by_ordinal(criterion, median_ordinal)
    band = _band_row(median_row, "band")

    # The single mapping, applied once, after aggregation (`FR-AGG-02`): the
    # median band's points are a lookup through M-PKG's canonical function —
    # a lookup, not a computation — and there is deliberately no other place in
    # this module that reads a band's points.
    points = points_for_band(criterion.bands, band)

    counts: dict[int, int] = {}
    for ordinal in ordinals:
        counts[ordinal] = counts.get(ordinal, 0) + 1
    top = max(counts.values())
    # The declared tie-break: among bands tied for the mode, the one whose ordinal
    # is closest to the median band's; still tied, the lower ordinal. Always a band
    # the panel gave (`TC-AGG-02`'s declared assumption, declared at #91).
    modal_ordinal = min(
        (ordinal for ordinal, count in counts.items() if count == top),
        key=lambda ordinal: (abs(ordinal - median_ordinal), ordinal),
    )
    modal_band = _band_row(_band_by_ordinal(criterion, modal_ordinal), "band")

    band_spread = ordinals[-1] - ordinals[0]

    histogram = tuple(
        (_band_row(_band_by_ordinal(criterion, ordinal), "band"), counts[ordinal])
        for ordinal in sorted(counts)
    )

    # --- the confidence surface (#92) ------------------------------------------------------------
    # Configuration: `config=None` means the module constants; a `config` value
    # supplies any subset of the knobs, each defaulting to its constant. The
    # values are read through getattr with the constant as default, never from
    # the environment (`CT-AGG-01`).
    if config is not None:
        caps = getattr(config, "caps", None)
        atomic_threshold = getattr(config, "auto_threshold_atomic", AGG_AUTO_THRESHOLD_ATOMIC)
        holistic_threshold = getattr(
            config, "auto_threshold_holistic", AGG_AUTO_THRESHOLD_HOLISTIC
        )
        uncited_multiplier = getattr(config, "uncited_multiplier", AGG_UNCITED_MULTIPLIER)
        holistic_multiplier = getattr(config, "holistic_multiplier", AGG_HOLISTIC_MULTIPLIER)
    else:
        caps = None
        atomic_threshold = AGG_AUTO_THRESHOLD_ATOMIC
        holistic_threshold = AGG_AUTO_THRESHOLD_HOLISTIC
        uncited_multiplier = AGG_UNCITED_MULTIPLIER
        holistic_multiplier = AGG_HOLISTIC_MULTIPLIER
    cap_table = dict(AGG_CAP_TABLE) if caps is None else dict(caps)

    scoring_model = getattr(criterion, "scoring_model", "atomic")
    threshold = holistic_threshold if scoring_model == "holistic" else atomic_threshold

    # Step 1 — the base. Step 2 — the multipliers. A `None` base is impossible
    # here: a panel of three or more always pair (unanimity is defined; see
    # `ordinal_alpha`), and a single judge always has a prior.
    base = _confidence_base(verdicts, criterion)
    multiplier = 1.0
    if any(not _verdict_cited(v) for v in verdicts):
        multiplier *= uncited_multiplier
    if scoring_model == "holistic":
        multiplier *= holistic_multiplier
    confidence_base = base * multiplier

    # Step 3 — the caps. A cap is a `min`, never a penalty term (ADR-10): each
    # adverse signal's cap is a hard ceiling on the figure, taken in any order,
    # and unanimity cannot buy any of it back.
    confidence = confidence_base
    caps_fired: list[str] = []
    for signal_name, favourable in _AGG_FAVOURABLE.items():
        if not _signal_adverse(getattr(signals, signal_name, None), favourable):
            continue
        # §3.12's one conditional cap: `evidence_present` binds only where
        # evidence is required. A criterion that does not declare the flag is
        # read as requiring it — fail-closed (the cap can bind, never be
        # skipped by an omission).
        if signal_name == "evidence_present" and not getattr(
            criterion, "evidence_required", True
        ):
            continue
        cap = cap_table.get(signal_name)
        if cap is not None:
            confidence = min(confidence, float(cap))
            if float(cap) < confidence_base:
                caps_fired.append(signal_name)

    # --- #93: routing and state, assigned per cause (FR-AGG-07, FR-AGG-11) -------------------
    # Precedence is the cause's, not the confidence's: the breaker mark and the
    # single-judge construction both force `provisional` regardless of the
    # confidence figure — a capped-high number is still one judge's word or a
    # criterion the panel could not grade (CT-ORCH-16: consumers surface it,
    # never treat it as an ordinary provisional).
    notes: tuple[str, ...] = ()
    if breaker_tripped:
        routing = "provisional"
        state = "ungradeable_by_panel"
        notes += (
            "criterion breaker tripped: ungradeable_by_panel (FR-AGG-11, CT-ORCH-16)",
        )
    elif len(verdicts) == 1:
        # A single-judge band is provisional by construction (§3.12): it awaits
        # its panel — FR-AGG-09's escalation to three is M-ORCH's to enqueue —
        # and one judge's word alone is never sufficient to auto-accept.
        routing = "provisional"
        state = "provisional_unreviewed"
        notes += ("single-judge band: provisional by construction (FR-AGG-07, FR-AGG-11)",)
    else:
        routing = "auto" if confidence >= threshold else "queued"
        state = "final"

    return CriterionScore(
        criterion_id=criterion.criterion_id,
        band=band,
        ordinal=median_ordinal,
        points=points,
        modal_band=modal_band,
        band_spread=band_spread,
        judge_count=len(verdicts),
        agreement=ordinal_alpha(verdicts, criterion),
        agreement_degenerate=int(criterion.band_count) < 3,
        histogram=histogram,
        confidence=confidence,
        confidence_base=confidence_base,
        routing=routing,
        state=state,
        notes=notes,
        spans_verified=getattr(signals, "spans_verified", None),
        evidence_present=getattr(signals, "evidence_present", None),
        sufficiency_flag=getattr(signals, "sufficiency_flag", None),
        ocr_overlap_risk=getattr(signals, "ocr_overlap_risk", None),
        described_evidence=getattr(signals, "described_evidence", None),
        extractor_disagreement=getattr(signals, "extractor_disagreement", None),
        caps_fired=tuple(caps_fired),
    )


def _passthrough_score(row: Any, criterion: Any) -> CriterionScore:
    """Pass a deterministic M-DET row through unchanged as a score (FR-AGG-10).

    The row judged without a panel arrives **already scored** — M-DET mapped the
    band and its mapped value, or left it `NULL` for an unresolved choice — so
    this is an echo, never a re-aggregation: the module invents no band, maps no
    points, and derives no confidence. `routing`/`state` come from the row (an
    unresolved choice arrives routed `triage` — the OPERATOR queue, the same
    boundary `FR-INGEST-30`/`FR-CONSOLE-11` draw); `auto`/`final` are the
    fallbacks when a row omits them, not overrides. The one clause in `notes`
    marks the entry, so a consumer reading the row alone can tell a
    pass-through from a panel score.
    """
    band_name = _row_value(row, "band")
    if band_name is None:
        # A det row always names its band; an absent one is echoed as the empty
        # name rather than invented from the criterion.
        band_name = ""
    ordinal = _row_value(row, "ordinal")
    if ordinal is None and band_name:
        # No ordinal on the row: a lookup through the criterion's declared bands
        # by name — the same single source the panel path maps through.
        for declared in getattr(criterion, "bands", ()) or ():
            if _band_row(declared, "band") == band_name:
                ordinal = _band_row(declared, "ordinal")
                break
    points = _row_value(row, "points")
    judge_count = _row_value(row, "judge_count")
    agreement = _row_value(row, "agreement")
    band_spread = _row_value(row, "band_spread")
    histogram = _row_value(row, "histogram")
    return CriterionScore(
        criterion_id=_row_value(row, "criterion_id") or criterion.criterion_id,
        band=band_name,
        ordinal=int(ordinal) if ordinal is not None else 0,
        points=None if points is None else float(points),
        modal_band=_row_value(row, "modal_band") or band_name or "",
        band_spread=int(band_spread) if band_spread is not None else 0,
        judge_count=int(judge_count) if judge_count is not None else 0,
        agreement=None if agreement is None else float(agreement),
        agreement_degenerate=int(getattr(criterion, "band_count", 0)) < 3,
        histogram=histogram if isinstance(histogram, tuple) else (),
        confidence=_row_value(row, "confidence"),
        confidence_base=_row_value(row, "confidence_base"),
        routing=_row_value(row, "routing") or "auto",
        state=_row_value(row, "state") or "final",
        notes=("deterministic score passed through unchanged (FR-AGG-10)",),
        spans_verified=_row_value(row, "spans_verified"),
        evidence_present=_row_value(row, "evidence_present"),
        sufficiency_flag=_row_value(row, "sufficiency_flag"),
        ocr_overlap_risk=_row_value(row, "ocr_overlap_risk"),
        described_evidence=_row_value(row, "described_evidence"),
        extractor_disagreement=_row_value(row, "extractor_disagreement"),
    )


#: FR-PIPE-18 (#524): the `state_reason` of a cell whose widened panel was left even by a
#: quarantined arm and whose replacement arm was refused.
EVEN_PANEL_AFTER_QUARANTINE = "even_panel_after_quarantine"


def aggregate_even_panel_after_quarantine(
    verdicts: Sequence[Any], criterion: Any, signals: Any, *, config: Any = None,
) -> CriterionScore:
    """The score of a cell that an even-sized panel left ungradeable after a judge was quarantined
    (FR-PIPE-18, CT-PIPE-12, ADR-34).

    Quarantine left the widened panel even and its replacement arm was refused (budget or
    breaker). An even panel is never aggregated as one (FR-AGG-03), so the row states what
    the panel could not do: `ungradeable_by_panel`, routed `provisional` so review admits
    it, with `state_reason = even_panel_after_quarantine`. The band shown to the reviewer is
    the panel's LOWER median — the median of the odd panel left when the highest-ordinal
    verdict is set aside — which is independent of verdict order and never rounds an even
    median up. `judge_count` is that odd panel's size: CT-AGG-03 admits only 0 or an odd count
    (the store's CHECK refuses anything else), and its own rule for a panel left at two is the
    same — discard a verdict rather than adjudicate between two (FR-AGG-09/12). The set-aside
    verdict stays in the ledger. The reviewer's decision is what settles the row."""
    if len(verdicts) < 2 or len(verdicts) % 2:
        raise EvenPanelError(
            f"aggregate_even_panel_after_quarantine is for an even panel of two or more; got "
            f"{len(verdicts)} verdict(s)")
    ordered = sorted(verdicts, key=_verdict_ordinal)
    base = aggregate(ordered[:-1], criterion, signals, config=config)
    return replace(
        base,
        routing="provisional",
        state="ungradeable_by_panel",
        state_reason=EVEN_PANEL_AFTER_QUARANTINE,
        notes=base.notes + (
            "even panel after quarantine, replacement arm refused: ungradeable_by_panel, "
            "routed to review; band shown is the panel's lower median (FR-PIPE-18)",
        ),
    )
