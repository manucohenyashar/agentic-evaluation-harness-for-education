"""`CriterionScore`: one aggregated criterion score."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# --- the score -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CriterionScore:
    """One aggregated criterion score — the value §3.14's `apply_policy` consumes.

    The shipped `criterion_score` columns (det migration v9: band, points,
    judge_count, agreement, state, routing) plus `FR-AGG-01`'s recorded modal band
    and spread, the degeneracy marker `CT-AGG-17`/`TC-AGG-19` require, the
    aggregation stage's histogram, and #92's confidence surface: the figure, the
    pre-cap base it was computed from, its routing, and the four integrity inputs
    `FR-AGG-13` records so the figure is reconstructible from the stored row
    alone (`NFR-AGG-04`). The defaults exist only for constructions that predate
    a field; `aggregate` always fills every field.
    """

    criterion_id: str
    band: str
    ordinal: int
    #: The mapped value. `None` only on a deterministic pass-through row whose
    #: unresolved selection never mapped one (FR-DET-03) — the panel path always
    #: maps exactly once (FR-AGG-02).
    points: float | None
    modal_band: str
    band_spread: int
    judge_count: int
    agreement: float | None
    agreement_degenerate: bool
    #: The panel's band histogram, in the criterion's own band order — the
    #: aggregation stage's observability (`CT-AGG-15`'s per-criterion band
    #: histogram, surfaced on the result rather than folded into a status).
    histogram: tuple[tuple[str, int], ...] = field(default_factory=tuple)
    #: #92 (`FR-AGG-05`, ADR-10): the confidence figure — the base (the panel's
    #: own α for three or more judges, the band-position prior for one) with the
    #: design's multipliers applied and each adverse integrity signal's hard cap
    #: taken as a `min`. `None` is never produced by `aggregate`; the default
    #: exists for constructions that predate the field.
    confidence: float | None = None
    #: What the caps consumed: the post-multiplier, pre-cap base. Recorded
    #: beside `agreement` because the two are different figures — `agreement`
    #: is α on the criterion's declared scale (#91's convention), the base is
    #: α on the panel's own inferred scale (§3.12's `base = ordinal_alpha(verdicts)`),
    #: and the two diverge exactly when the panel never reached the declared
    #: top band. Recorded on the row (cohort migration v16) so the confidence
    #: is re-derivable from stored data alone.
    confidence_base: float | None = None
    #: The closed routing set (`FR-AGG-07`, `CT-AGG-06`): `auto` — the
    #: confidence met the scoring model's threshold; `queued` — the TEACHER's
    #: review queue, panel disagreement below the threshold; `provisional` — a
    #: single-judge band (or a score under a tripped criterion breaker), never
    #: auto-accepted; `reviewed` — a reviewer has acted, M-REVIEW's to write;
    #: `triage` — the OPERATOR's queue, for unresolved-selection and
    #: ingestion-caused states only. `reviewed` is the one value this module
    #: never assigns: it names a review that has happened.
    routing: str = "queued"
    #: The score's state, naming the cause (`FR-AGG-11`, `CT-AGG-07`):
    #: `final` — a full panel's settled aggregation; `provisional_unreviewed` —
    #: a single-judge band awaiting its panel; `ungradeable_by_panel` — the
    #: criterion's `M-ORCH` circuit breaker tripped (consumers surface it, never
    #: treat it as an ordinary provisional); `unresolved_selection` — M-DET's
    #: unresolved selection, arriving routed `triage`.
    state: str = "final"
    #: #93 (seam 4): what this module did to produce the score, in order — the
    #: cause markers for the two-verdict discard, the single-judge provisional,
    #: the breaker mark and the deterministic pass-through. Clauses carry the
    #: FR id that required them, so a consumer reading the row alone can tell a
    #: discarded second verdict from a never-run one.
    notes: tuple[str, ...] = ()
    #: FR-PIPE-18 (#524): why the row carries its `state` when the cause is not the state
    #: itself, recorded on the row (`criterion_score.state_reason`, cohort migration 30).
    #: Today one value: `even_panel_after_quarantine`. `None` everywhere else.
    state_reason: str | None = None
    #: The four recorded integrity inputs (`FR-AGG-13`), passed through exactly
    #: as received — including `None` ("not measured"), which is adverse
    #: fail-closed wherever the figure is consumed. Recorded so the confidence
    #: is answerable from stored data alone.
    spans_verified: Any = None
    evidence_present: Any = None
    sufficiency_flag: Any = None
    ocr_overlap_risk: Any = None
    #: #360 (`FR-AGG-13` amended): the remaining two signals, passed through as
    #: received so `write_score` stores all six.
    described_evidence: Any = None
    extractor_disagreement: Any = None
    #: #360 (`FR-AGG-15`): the caps that bound, named by their `AGG_CAP_TABLE`
    #: key, in the table's order — an adverse signal whose cap sits below the
    #: pre-cap base, so the cap lowered the figure. Empty when none did.
    caps_fired: tuple[str, ...] = ()
