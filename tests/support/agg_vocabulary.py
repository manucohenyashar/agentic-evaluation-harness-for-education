"""The M-AGG test vocabulary: stand-in value objects and the favourable-signal fixture.

TS-35 (#94) is written **ahead** of #91, so the value objects these cases pass to the
aggregation surface do not exist yet. Collecting them here follows the `store_api.py`
and `orch_run.py` precedents: state the assumption where a reader will find it, keep
`require()` inside the test body, and make a rename one edit.

**Assumed of #91, declared so it is reconciled deliberately rather than discovered**
(the `test_escalation_policy.py` precedent — stand-ins carrying the design's field
names, reconciled at the story's landing):

| Name | Status |
|---|---|
| `aeh.agg:aggregate(verdicts, criterion, signals) -> score` | **module-level shape of design §3.12's `Aggregator.aggregate` Protocol member.** The design declares the Protocol; it does not say how a consumer obtains an instance, and CT-AGG-01 makes the computation pure — so the tests call a module-level pure function. If #91 ships only Protocol methods, the adapter in each file's helper changes in one place. |
| `aeh.agg:ordinal_alpha(verdicts) -> float or None` | design §3.12 Protocol member, same module-level reading. |
| `aeh.agg:EvenPanelError` | **invented**: FR-AGG-03 and CT-AGG-12 name the refusal ("an even panel is a failed write, not a rounded verdict") but no exception name. The invented name is the "exact exception" oracle's pin and reconciles at #91's landing. |
| score `.band` `.points` `.modal_band` `.band_spread` `.judge_count` `.agreement` | the shipped `criterion_score` columns (det migration v9) plus FR-AGG-01's recorded modal band and spread. `modal_band`/`band_spread` are assumed to live on the score: §9.9's `AggregationResult` is the console wire shape and carries the same figures, so a split landing reconciles here first. |
| score `.agreement_degenerate` | **invented**: TC-AGG-19 requires "the degeneracy marker that M-STATS needs" (CT-AGG-17) and the design pins the marker's existence, not its name. |
| verdict `.band` `.ordinal` | the design's Requires table: "every verdict names a declared band with an ordinal" and "carries no points". |
| criterion `.criterion_id` `.scoring_model` `.bands` `.band_count` | CT-PKG-04: bands ordered by ordinal ascending, `band_count` even and in 2..6, points non-decreasing in ordinal. |
| signals | the six M-INTEG fields enumerated by TC-AGG-06: `spans_verified`, `evidence_present`, `sufficiency_flag`, `ocr_overlap_risk`, `described_evidence`, `extractor_disagreement`. `None` means "not measured" and is adverse (fail-closed), so the favourable fixture uses explicit `True`/`False` rather than absence. |
"""

from __future__ import annotations

from types import SimpleNamespace

#: The one story whose landing unmarks every M-AGG case in this suite (test plan §8.2).
AGG_BLOCKER = "#91"


def band(name: str, ordinal: int, points: float) -> SimpleNamespace:
    """One declared band, in the shape M-PKG's `bands()` returns (CT-PKG-04)."""
    return SimpleNamespace(band=name, ordinal=ordinal, points=points)


def criterion(bands, scoring_model: str = "atomic", criterion_id: str = "C-AGG",
              evidence_required: bool = True) -> SimpleNamespace:
    """A criterion carrying its ordered band set — the value `aggregate` maps through.

    TS-36 (#95) adds `evidence_required`: the `evidence_present` cap binds only on a
    citation-requiring criterion (§3.12's cap table: "not evidence_present and evidence
    is required"). Default True — the citation-requiring reading the TS-35 callers
    already sit under.
    """
    bands = tuple(bands)
    return SimpleNamespace(
        criterion_id=criterion_id,
        scoring_model=scoring_model,
        bands=bands,
        band_count=len(bands),
        evidence_required=evidence_required,
    )


def score(criterion_id: str, band_name: str, ordinal: int, points: float, *,
          judge_count: int = 3, agreement: float = 1.0) -> SimpleNamespace:
    """One aggregated criterion score — the value design §3.14's
    `apply_policy(scores: Sequence[CriterionScore], policy)` consumes: the shipped
    `criterion_score` columns (det migration v9) plus the criterion it belongs to.
    `modal_band`/`band_spread` mirror the aggregate score row (FR-AGG-01); the band
    name/ordinal pair is inert to the policy, which reads points by criterion."""
    return SimpleNamespace(
        criterion_id=criterion_id,
        band=band_name,
        ordinal=ordinal,
        points=points,
        modal_band=band_name,
        band_spread=0.0,
        judge_count=judge_count,
        agreement=agreement,
    )


def verdict(band_name: str, ordinal: int, *, cited: bool = True,
            self_confidence: float = 0.9) -> SimpleNamespace:
    """One judge's verdict: a declared band name with its ordinal, no points (CT-JUDGE).

    TS-36 (#95) adds the two M-JUDGE fields the confidence and escalation cases vary —
    "uncited verdicts arrive marked" and "`self_confidence` is present but not
    authoritative" (§3.12's Requires table). Both default to the favourable reading, so
    the TS-35 callers are unaffected.
    """
    return SimpleNamespace(
        band=band_name, ordinal=ordinal, cited=cited, self_confidence=self_confidence
    )


def panel(*band_specs) -> list:
    """A panel from `(name, ordinal)` pairs, in judge order."""
    return [verdict(name, ordinal) for name, ordinal in band_specs]


def favourable_signals() -> SimpleNamespace:
    """All six integrity signals favourable — the baseline every adverse case varies from."""
    return SimpleNamespace(
        spans_verified=True,
        evidence_present=True,
        sufficiency_flag=False,
        ocr_overlap_risk=False,
        described_evidence=False,
        extractor_disagreement=False,
    )


# --- TS-36 (#95): the confidence, routing and escalation extension ------------------------
#
# The cases of issue #95 (TC-AGG-06..18) are written ahead of #91 (the aggregate core),
# #92 (the confidence caps and the stored integrity inputs) and #93 (routing, escalation
# policy, score states). The stand-ins below extend this vocabulary the same additive way
# the TS-35 section did; every name a design gap forced is listed in the table so the
# owning story reconciles it deliberately rather than discovering it.
#
# | Name | Status |
# |---|---|
# | `signals(**overrides)` | the six M-INTEG fields, favourable by default, `None` = not measured = adverse (fail-closed). Generalizes `favourable_signals()`, which stays. |
# | `agg_config(**kw)` | the injected cap table + thresholds + uncited multiplier (Q-04: injected as configuration, never test literals). `caps` maps each of the six fields to a hard cap; the defaults are the design's Assumption numbers (§3.12), present as *fixture data*, not as assertions. |
# | `escalation_score(...)` | a `criterion_score` in the shape `should_escalate` reads: the observable signals live on the row (FR-AGG-13's four recorded fields, §7.1's list). Field names follow TC-ORCH-32's stand-ins (`.band` `.confidence` `.judge_count`) — one vocabulary, one reconciliation. |
# | `criterion_history(...)` | `.override_rate` `.escalations` — TC-ORCH-32's stand-in shape (CT-STATS-09: an explicit no-data value rather than a zero is M-STATS's concern, not the stand-in's). |
# | `expected_distribution(...)` | `.mean` `.std` — the package baseline (§3.12's `ExpectedDistribution`). |
# | `EscalationDecision.escalate` / `.target_judge_count` | **invented**: the design returns a decision to M-ORCH but pins no fields. `escalate` is the bool; `target_judge_count` carries FR-AGG-09's 1 → 3 (never 2). |
# | `aggregate(..., fallback=)` | **invented keyword**: TC-AGG-04 (#94) pins that a raw even panel raises `EvenPanelError`; TC-AGG-12 requires that a panel *left at two by an unrecoverable failure* discards the second verdict and records the base single-judge band as provisional. The two compose only if the caller can mark the fallback case — `fallback=True` is that mark, reconciles at #93. |
# | `aggregate(..., breaker_tripped=)` | **invented keyword**: FR-AGG-11 sets `ungradeable_by_panel` for criteria the M-ORCH breaker tripped; the state must be an input, because the tripping is the orchestrator's (shipped `criterion_breaker_tripped`, #60). |
# | `aggregate(..., deterministic_score=)` | **invented keyword**: FR-AGG-10's pass-through. An empty verdict list is a programming error (CT-AGG-12), so the deterministic row cannot arrive through the panel path; this is the marked alternative entry, reconciles at #93. |
# | `aeh.agg:recompute_confidence(row, criterion)` | **invented**: NFR-AGG-04's round trip needs the confidence derivable from the stored row alone; §3.12 names no function. `row` is the stored `criterion_score` mapping; `criterion` is the package's static band definition. Reconciles at #92. |
# | `aeh.agg:AGG_CAP_TABLE` | **invented name** for §3.12's Assumption-numbered cap table (the `AGG_AUTO_THRESHOLD_*` constants are design-declared; the caps are not). Reconciles at #92. |
# | score `.confidence` `.routing` `.state` | the shipped migration v9 columns (det.py) — `confidence` itself lands with #92's migration. |

#: The six M-INTEG signal fields, in §3.12's enumeration order (the 2^6 sweep of TC-AGG-06).
SIGNAL_FIELDS = (
    "spans_verified",
    "evidence_present",
    "sufficiency_flag",
    "ocr_overlap_risk",
    "described_evidence",
    "extractor_disagreement",
)

#: §3.12's Assumption cap table, as fixture data (Q-04: the tests inject this; the
#: assertions are stated against the injection, never against these literals).
DESIGN_CAPS = {
    "spans_verified": 0.25,
    "evidence_present": 0.25,
    "sufficiency_flag": 0.25,
    "ocr_overlap_risk": 0.30,
    "described_evidence": 0.50,
    "extractor_disagreement": 0.40,
}


def signals(**overrides) -> SimpleNamespace:
    """The six M-INTEG signals, favourable by default, per-field overridden.

    `None` means "not measured" (the design's fail-closed reading: adverse, never
    favourable, never absent).
    """
    values = {
        "spans_verified": True,
        "evidence_present": True,
        "sufficiency_flag": False,
        "ocr_overlap_risk": False,
        "described_evidence": False,
        "extractor_disagreement": False,
    }
    unknown = set(overrides) - set(values)
    assert not unknown, f"not one of the six M-INTEG signals: {sorted(unknown)}"
    values.update(overrides)
    return SimpleNamespace(**values)


def agg_config(*, auto_threshold_atomic: float = 0.80,
               auto_threshold_holistic: float = 0.90,
               uncited_multiplier: float = 0.80,
               caps: dict | None = None) -> SimpleNamespace:
    """The configuration `aggregate` is assumed to accept (Q-04, CT-AGG-01: the policy
    reads no configuration beyond the values passed in). Defaults are the design's
    Assumption numbers — fixture data, not the oracle."""
    return SimpleNamespace(
        auto_threshold_atomic=auto_threshold_atomic,
        auto_threshold_holistic=auto_threshold_holistic,
        uncited_multiplier=uncited_multiplier,
        caps=dict(DESIGN_CAPS if caps is None else caps),
    )


def escalation_score(*, confidence: float = 0.62, ordinal: int = 3, band_count: int = 4,
                     judge_count: int = 3, uncited: bool = False,
                     self_confidence: float = 0.9, criterion_id: str = "C-ESC",
                     **signal_overrides) -> SimpleNamespace:
    """A `criterion_score` in the shape `should_escalate` reads.

    The observable signals live on the row: FR-AGG-13's four recorded integrity fields
    (§7.1's "adverse integrity signals" and "transcription overlap"), the panel figures,
    the interior band position (`ordinal` against `band_count`) and the uncited mark.
    `self_confidence` is present — and TC-AGG-09 exists to prove it is never the sole
    trigger.
    """
    sig = signals(**signal_overrides)
    return SimpleNamespace(
        criterion_id=criterion_id,
        band=f"B{ordinal}",
        ordinal=ordinal,
        band_count=band_count,
        confidence=confidence,
        judge_count=judge_count,
        uncited=uncited,
        self_confidence=self_confidence,
        spans_verified=sig.spans_verified,
        evidence_present=sig.evidence_present,
        sufficiency_flag=sig.sufficiency_flag,
        ocr_overlap_risk=sig.ocr_overlap_risk,
        described_evidence=sig.described_evidence,
        extractor_disagreement=sig.extractor_disagreement,
    )


def criterion_history(*, override_rate: float = 0.0, escalations: int = 0) -> SimpleNamespace:
    """The criterion's override history — TC-ORCH-32's stand-in shape."""
    return SimpleNamespace(override_rate=override_rate, escalations=escalations)


def expected_distribution(*, mean: float = 2.0, std: float = 0.5) -> SimpleNamespace:
    """The package's expected band distribution (§3.12's `ExpectedDistribution`)."""
    return SimpleNamespace(mean=mean, std=std)
