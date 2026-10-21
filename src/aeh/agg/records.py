"""`CriterionScore`: one aggregated criterion score."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


# --- the score -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CriterionScore:
    """One aggregated criterion score: the value M-GRADE's `apply_policy` reads (design §3.14).

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
    #: FR-AGG-20: why a cell is not settled, one code from `NOT_FINAL_REASONS`. `None` on a
    #: settled cell (`final` and not `queued`). Not a column: a stored row's code is
    #: re-derived from its own columns by `stored_not_final_reason` (no migration), except
    #: `more_graders_unavailable`, which `write_score` records in `state_reason`.
    not_final_reason: str | None = None


# --- FR-AGG-20: the not-final reason codes ---------------------------------------------------------

#: A single LLM verdict (including Jev below its gate, whose seat an LLM judge answered).
ONE_GRADER_UNSURE = "one_grader_unsure"
#: A panel whose spread or agreement left the confidence below the threshold.
GRADERS_DISAGREE = "graders_disagree"
#: The evidence-required cap fired.
EVIDENCE_NOT_FOUND = "evidence_not_found"
#: The citation-verification cap fired.
QUOTE_NOT_VERIFIED = "quote_not_verified"
#: Escalation was wanted and could not be seated.
MORE_GRADERS_UNAVAILABLE = "more_graders_unavailable"
#: The criterion's breaker tripped (`ungradeable_by_panel`).
GRADERS_REFUSED = "graders_refused"

#: FR-AGG-20's closed set.
NOT_FINAL_REASONS: tuple[str, ...] = (
    ONE_GRADER_UNSURE,
    GRADERS_DISAGREE,
    EVIDENCE_NOT_FOUND,
    QUOTE_NOT_VERIFIED,
    MORE_GRADERS_UNAVAILABLE,
    GRADERS_REFUSED,
)

#: Stored state reasons that predate FR-AGG-20 and the code each one reads as. An even panel
#: left after a quarantine whose replacement arm was refused (FR-PIPE-18) is a cell more
#: graders could not be found for.
_LEGACY_STATE_REASONS = {"even_panel_after_quarantine": MORE_GRADERS_UNAVAILABLE}


def is_settled(state: Any, routing: Any) -> bool:
    """Whether a cell is settled: `final` and not waiting in the teacher's queue."""
    return state == "final" and routing != "queued"


def not_final_reason_for(
    state: Any, routing: Any, *, judge_count: Any, caps_fired: Any, state_reason: Any = None,
) -> str | None:
    """FR-AGG-20's code for why a cell is not settled; `None` for a settled one.

    The cause's precedence: a recorded reason (`more_graders_unavailable`, or FR-PIPE-18's
    even panel); the breaker; then the evidence and citation caps, which name what is missing
    more precisely than the panel's shape does; then one grader, or a panel that disagreed."""
    if is_settled(state, routing):
        return None
    if state_reason in NOT_FINAL_REASONS:
        return state_reason
    if state_reason in _LEGACY_STATE_REASONS:
        return _LEGACY_STATE_REASONS[state_reason]
    if state == "ungradeable_by_panel":
        return GRADERS_REFUSED
    caps = tuple(caps_fired or ())
    if "evidence_present" in caps:
        return EVIDENCE_NOT_FOUND
    if "spans_verified" in caps:
        return QUOTE_NOT_VERIFIED
    if judge_count is not None and int(judge_count) == 1:
        return ONE_GRADER_UNSURE
    if judge_count is not None and int(judge_count) == 0:
        # A deterministic row (FR-AGG-10) has no panel to name; its state is its own story.
        return None
    return GRADERS_DISAGREE


def stored_not_final_reason(row: Any) -> str | None:
    """The FR-AGG-20 reason code of a stored `criterion_score` row (a mapping, a `sqlite3.Row`
    or a `CriterionScore`), re-derived from the row's own `state`, `routing`, `judge_count`,
    `caps_fired` and `state_reason`. `None` for a settled cell."""
    def read(name: str) -> Any:
        if isinstance(row, dict):
            return row.get(name)
        try:
            return row[name]
        except (KeyError, IndexError, TypeError):
            return getattr(row, name, None)

    caps = read("caps_fired")
    if isinstance(caps, str):
        try:
            caps = json.loads(caps)
        except ValueError:
            caps = ()
    return not_final_reason_for(
        read("state"), read("routing"), judge_count=read("judge_count"),
        caps_fired=caps, state_reason=read("state_reason"))
