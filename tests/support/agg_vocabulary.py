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


def criterion(bands, scoring_model: str = "atomic", criterion_id: str = "C-AGG") -> SimpleNamespace:
    """A criterion carrying its ordered band set — the value `aggregate` maps through."""
    bands = tuple(bands)
    return SimpleNamespace(
        criterion_id=criterion_id,
        scoring_model=scoring_model,
        bands=bands,
        band_count=len(bands),
    )


def verdict(band_name: str, ordinal: int) -> SimpleNamespace:
    """One judge's verdict: a declared band name with its ordinal, no points (CT-JUDGE)."""
    return SimpleNamespace(band=band_name, ordinal=ordinal)


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
