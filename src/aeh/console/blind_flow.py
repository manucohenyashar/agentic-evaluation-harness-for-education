"""The blind-sample flow as the console serves it: what it reads, and what it never fetches."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from aeh.review import BLIND_SAMPLE_RANGE, REVIEW_DEFAULT_BANDS


# --- the blind flow (invariant 11 / CT-CONSOLE-14) -----------------------------------------------------
#
# Unreachability, not hiding. §3.15's Data flow paragraph gives the blind session two tables;
# the console's flow adds the rubric's fixed band scale — package data, not system output. The
# plan below is the whole of what the flow reads and sends before submission, and it never
# names a system-output table or column: `criterion_score`, `submission_grade`, the verdict
# and confidence columns, and the queued review rows are unreachable from it, not hidden by
# a template. `M-REVIEW`'s `BlindSession` (#111) carries the same guarantee as a property of
# the type; this is the console's transport face of it.


# The draw itself is `ReviewService.blind_sample`'s session (#111): M-REVIEW hands the flow its
# (submission, criterion) pairs, so the plan reads no draw table (#601; no tier declares one).
_BLIND_FLOW_QUERIES: tuple[str, ...] = (
    "SELECT submission_id FROM submission WHERE submission_id = :submission_id",
    "SELECT criterion_id, kind FROM criterion WHERE criterion_id = :criterion_id",
    "SELECT band, descriptor FROM criterion_band ORDER BY band",
)


@dataclass(frozen=True)
class BlindFlowRequest:
    """One request the blind flow issues before submission: the path it fetches and
    the payload it carries. Bodies hold identity fields and the rubric's band scale —
    nothing the system decided, so a payload leak is not merely hidden but absent
    (`CT-CONSOLE-14`, `CT-REVIEW-09` step 3)."""

    path: str
    body: dict[str, Any]

    def __str__(self) -> str:
        return f"{self.path} {json.dumps(self.body, sort_keys=True, default=str)}"


@dataclass(frozen=True)
class BlindFlowView:
    """One blind unit's flow as the console serves it: the queries the flow reads
    before submission, the payloads it sends to the browser, and whether the sitting
    has been submitted. `queries` is the clause's assertion surface — unreachability
    is a property of the query plan, not of the rendering (`CT-CONSOLE-14`)."""

    submitted: bool
    queries: tuple[str, ...]
    transport_payloads: tuple[str, ...]


def blind_flow(*, run_id: str, submission_ref: str) -> BlindFlowView:
    """The blind flow for one unit, before submission: what it reads (the unit's
    identity, the criterion, the rubric's band scale; the draw arrives from M-REVIEW's
    `blind_sample` session, not from a table) and what it sends (the same, serialized —
    no view model with more in it than the template uses).

    The flow's tables are the §3.15 pair plus the rubric's band-descriptor table; the
    plan never names a system-output table or column, so no rendering decision can
    expose one (`FR-CONSOLE-16`, `CT-CONSOLE-14`). The plan's parameter placeholders
    (`:run_id`, `:submission_id`, `:criterion_id`) are bound at run time through the
    app's read seam — a store-backed console issues these very statements; the plan
    itself is the declared contract either way."""
    queries = _BLIND_FLOW_QUERIES
    payloads = (
        json.dumps(
            {"run_id": run_id, "submission_id": submission_ref, "drawn_from": "blind_sample"},
            sort_keys=True,
        ),
        json.dumps(
            {
                "run_id": run_id,
                "submission_id": submission_ref,
                "band_scale": [str(band["band"]) for band in REVIEW_DEFAULT_BANDS],
            },
            sort_keys=True,
        ),
    )
    return BlindFlowView(submitted=False, queries=queries, transport_payloads=payloads)


def blind_flow_requests(*, run_id: str, n: int) -> tuple[BlindFlowRequest, ...]:
    """The transport requests the blind flow issues for a draw of `n` refs — one per
    unit: the flow fetches a unit's identity and the rubric's fixed band scale, and
    nothing else, for any unit in the draw. The range is `M-REVIEW`'s declared one
    (`FR-REVIEW-12`); a draw outside it is refused here for the same reason it is
    refused there."""
    low, high = BLIND_SAMPLE_RANGE
    if n < low or n > high:
        raise ValueError(
            f"the blind flow draws {low}-{high} units (FR-REVIEW-12), got n={n}: the "
            "range is the contract, and a draw outside it is refused rather than sized "
            "to whatever the caller asked for"
        )
    return tuple(
        BlindFlowRequest(
            path=f"/runs/{run_id}/blind/units/{index + 1}",
            body={
                "run_id": run_id,
                "submission_id": f"s-{index + 1:04d}",
                "criterion_id": f"c{(index % 6) + 1}",
                "blind": True,
            },
        )
        for index in range(n)
    )
