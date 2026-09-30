"""A judged unit's result, the stored verdict, and the read that returns a cell's verdicts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .schema import JUDGE_STATEMENTS


@dataclass(frozen=True)
class ScoringResult:
    """One judged unit — §9.9's result. `resolved_build` is the RESOLVED identity of
    the model that actually answered (`FR-PROV-04`; the verdict row's `judge_id`
    stays the arm's, while `resolved_build` is who actually answered). `uncited` is
    `FR-JUDGE-12`'s marking: a reply with no cited spans is a legitimate verdict that
    must be MARKED as uncited, never silently treated as cited. `notes` is the
    stage-level observability channel: `None` on a clean first attempt, otherwise the
    line saying what happened — the strike budget ran out, or which attempt landed.
    `prefix_bytes`/`total_bytes` are the payload's invariant-prefix and total sizes —
    `CT-JUDGE-13`'s shared-prefix observable (the throughput assumption a prompt
    change could silently break), in bytes: the tokenizer is the provider's, the byte
    split is the transport-neutral form of the same invariant.
    """

    work_id: str
    judge_id: str
    band: str
    band_ordinal: int
    self_confidence: float
    cited_spans: tuple[Any, ...]
    uncited: bool
    evidence_assessment: str
    evidence_sufficient: bool
    resolved_build: str | None
    attempts: int
    notes: str | None = None
    prefix_bytes: int | None = None
    total_bytes: int | None = None
    #: `FR-JUDGE-10`'s integrity flag(s), named tokens rather than one boolean (the
    #: `IngestReport.gates` shape): `ASSESSMENT_AMENDED` rides exactly on a verdict whose
    #: dispatch re-requested the assessment with an amended prompt before accepting.
    #: Empty on a clean first-acceptance dispatch. Observability, not routing — no
    #: consumer branches a verdict away for carrying one (`FR-JUDGE-13`'s rule is about
    #: `self_confidence`, and the same "one weighted input" posture governs here).
    integrity_flags: tuple[str, ...] = ()
    #: #361 (`FR-JUDGE-20`): the successful call's wall time, the provider's own
    #: `Completion.latency_ms` — persisted on the verdict row. `None` only for a result
    #: built without a call.
    latency_ms: int | None = None
    #: Jev design delta FR-JUDGE-28/35: which engine produced this verdict — `"llm"` (the
    #: panel judge, today's path) or `"decision"` (the decision engine on the decision seat)
    #: — and the build that answered. `prescreen_outcome` names the decision-seat pre-screen
    #: that preceded an LLM verdict (`None` when no pre-screen applied).
    scoring_engine: str = "llm"
    engine_build: str | None = None
    prescreen_outcome: str | None = None


@dataclass(frozen=True)
class StoredVerdict:
    """One persisted verdict as `aggregate` consumes it (`FR-JUDGE-18`): the band and its
    ordinal, the cited-span inventory (a tuple of span documents, empty when uncited), the
    sufficiency answer, the uncited mark and the judge. `agg._verdict_ordinal` reads
    `band_ordinal` and `agg._verdict_cited` reads `uncited`, so the tuple feeds `aggregate`
    with no adaptation."""

    work_id: str
    judge_id: str
    band: str
    band_ordinal: int
    cited_spans: tuple[Any, ...]
    evidence_sufficient: bool
    uncited: bool
    #: FR-JUDGE-35 / CT-JUDGE-24: `llm` or `decision`; a pre-delta row's NULL reads `llm`.
    scoring_engine: str = "llm"

    @property
    def ordinal(self) -> int:
        """The band ordinal under the name `aggregate` reads (`agg._verdict_ordinal`)."""
        return self.band_ordinal


def verdicts_for(
    handle: Any, run_id: str, submission_id: str, criterion_id: str
) -> tuple[StoredVerdict, ...]:
    """The cell's verdicts for ONE run, in `work_id` order (`FR-JUDGE-18`, `CT-JUDGE-20`).

    Reads through `handle` (the cohort tier handle) with the run filter, so a second run's
    verdicts for the same (submission, criterion) never appear. A cell with no verdicts is
    the empty tuple, never an error."""
    rows = handle.query(
        JUDGE_STATEMENTS["select_cell_verdicts"],
        run_id=run_id, submission_id=submission_id, criterion_id=criterion_id,
    )
    return tuple(
        StoredVerdict(
            work_id=row["work_id"],
            judge_id=row["judge_id"],
            band=row["band"],
            band_ordinal=int(row["band_ordinal"]),
            cited_spans=tuple(json.loads(row["cited_spans"])) if row["cited_spans"] else (),
            evidence_sufficient=bool(row["evidence_sufficient"]),
            uncited=bool(row["uncited"]),
            scoring_engine=row["scoring_engine"] or "llm",
        )
        for row in rows
    )
