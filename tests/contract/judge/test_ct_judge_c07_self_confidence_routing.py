"""`TC-JUDGE-C07` — self-confidence is persisted, never routing (§6.11.10).

`CT-JUDGE-07` (behaviour): *"Assert `self_confidence` is persisted but **never by
itself determines routing**. The discriminating case: hold every observable signal
constant and vary `self_confidence` across its range, asserting routing does **not**
change on that basis alone. Then assert at rung 3 that `M-AGG` weights it as **one
signal among the observable ones**. A consumer treating it as the escalation trigger
violates HLD `R22` — a model's self-report is not an observable."* (plan §6.11.10,
verbatim)

The judge-side half is this file's own:

1. **routing invariance under varied self-confidence** — the SAME world driven
   three times with the reply's self-confidence swept across its full range
   (0.0, 0.5, 1.0), every other observable held constant: the routed work is
   identical in shape (same judged pairs, same judges, same origins — compared
   on the routing tuple, not the `work_id`, which is per-drive by construction:
   `run_id` is a `work_id` input and each drive is its own run), the band
   is unchanged, the row carries the varied confidence verbatim, and no
   escalation unit exists anywhere in the run (`origin='escalation'`): the
   escalation path never fired on the self-report;
2. **the module's own surface carries no escalation trigger** — a call-shaped
   static scan over `aeh.judge`'s text for `should_escalate(` /
   `enqueue_*(...)` call sites, with the scanner's own positive control, since
   the module docstring legitimately MENTIONS `should_escalate` as #93's
   consumer (`FR-JUDGE-13`, R22) and a substring scan would false-positive on
   the mention.

Cross-references, not duplicates — the rung-3 weight limbs are owned elsewhere and
executed there: `tests/contract/agg/test_ct_agg_c08_enqueues_nothing.py` (`TC-AGG-C08`)
carries `CT-AGG-08`'s R22 invariance through the shipped sibling
`tests/unit/agg/test_routing_and_escalation.py` (`TC-AGG-09`:
`test_tc_agg_09_self_confidence_alone_cannot_flip_the_escalation_decision` — the
per-signal sensitivity sweep where self-confidence alone moves nothing), and the
review-side consumer (`TC-REVIEW-C03`, `M-REVIEW`, #108 in flight) reads the same
row. This file holds the judge-side half those consumers stand on: the row IS the
self-report, and the judge module creates no routing from it.

Isolation: rung 2 — real store, real workers, three drives over identical worlds;
the socket guard is autouse and the completions come from the recorded fixture
provider.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from aeh.store import open_store
from tests.contract.judge._drive import drive_judged_run, verdict_rows
from tests.support.orch_run import ORCH_COHORT_ID

pytestmark = [pytest.mark.contract]

#: The story that owns the verdict shape (`M-JUDGE` is complete — #78/#79/#80/#81).
ISSUE = "#78"

#: The full-range sweep the plan's discriminating case asks for: low, middle, high —
#: every other observable (the submission, the criterion, the cited span, the band)
#: held constant across the three drives.
_CONFIDENCE_RANGE: tuple[float, ...] = (0.0, 0.5, 1.0)

#: The call-shaped escalation patterns the judge module must not carry. Call-shaped,
#: not substring: the module docstring legitimately MENTIONS `should_escalate` as
#: #93's consumer (`FR-JUDGE-13`, R22), and a bare-name scan would flag that mention.
_ESCALATION_CALL_SITES = r"should_escalate\s*\(|enqueue_[A-Za-z_]+\s*\("

#: The scanner's in-file positive control: the same patterns planted as a string the
#: scan MUST catch, so a toothless scan cannot pass this file silently.
_POSITIVE_CONTROL = "should_escalate(signals) and enqueue_escalation(run_id, plan)"


def _judged_store(tmp_data_dir: Any, make_fixture_provider: Any,
                  self_confidence: float) -> tuple[Any, str, list[dict[str, Any]]]:
    """One judged drive over the default world with the reply's self-confidence set —
    `(store, run_id, verdict rows)` out, the store left OPEN for the caller's
    assertions (the caller closes it)."""
    store = open_store(tmp_data_dir)
    provider = make_fixture_provider()

    def completion_for(unit: Any, judge_ref: Any) -> Any:
        from tests.support.extract_vocabulary import verdict_completion

        return verdict_completion(
            "secure", self_confidence,
            build_id="build-judge-contract",
            cited_spans=None,
        )

    _orchestrator, run_id, _version = drive_judged_run(
        store, provider, completion_for=completion_for, cited=False,
    )
    return store, run_id, verdict_rows(store, run_id, "SYN-001", "C1")


def test_tc_judge_c07_routing_is_invariant_under_varied_self_confidence(
    tmp_path_factory, make_fixture_provider
):
    """`TC-JUDGE-C07` (`CT-JUDGE-07`, routing invariance under varied
    self-confidence, rung 2, P0) — the same world driven at self-confidence 0.0,
    0.5 and 1.0: the routed work is identical in shape (the same judged pairs, the
    same judges, the same origins), the band never moves, the confidence is
    persisted verbatim, and no escalation unit exists anywhere in any run. (The
    work_ids themselves differ across drives — `run_id` is a `work_id` input and
    each drive is its own run; the routing observable is WHAT was routed.)"""
    roots = [tmp_path_factory.mktemp(f"c07-{index}") for index in
             range(len(_CONFIDENCE_RANGE))]
    routed_by_confidence: dict[float, list[tuple[str, str, str, str]]] = {}
    rows_by_confidence: dict[float, list[dict[str, Any]]] = {}
    for root, confidence in zip(roots, _CONFIDENCE_RANGE):
        store, run_id, rows = _judged_store(root, make_fixture_provider, confidence)
        try:
            rows_by_confidence[confidence] = rows
            assert rows, (
                f"fixture bug: the drive at confidence {confidence} persisted no "
                "verdict row — the sweep below needs the persisted self-report"
            )
            units = store.cohort(ORCH_COHORT_ID).query(
                "SELECT work_id, origin, judge_id, submission_id, criterion_id "
                "FROM work_unit WHERE run_id = :r AND stage = 'score'",
                r=run_id,
            )
            routed_by_confidence[confidence] = sorted(
                (u["submission_id"], u["criterion_id"], u["judge_id"], u["origin"])
                for u in units
            )
            escalations = [u for u in units if u["origin"] == "escalation"]
            assert escalations == [], (
                f"the drive at confidence {confidence} created "
                f"{len(escalations)} escalation unit(s) — self_confidence is "
                "persisted but never by itself determines routing, and a "
                "self-report must not widen the panel (CT-JUDGE-07, HLD R22)"
            )
        finally:
            store.close()

    # The routed work is IDENTICAL across the sweep — same shape, same origins.
    routed = list(routed_by_confidence.values())
    assert routed[0] == routed[1] == routed[2], (
        "the routed work changed as self_confidence moved across its range: "
        f"{routed} — every observable signal is held constant, so a routing "
        "change on that basis alone is the R22 violation (CT-JUDGE-07)"
    )
    # The persistence half: the confidence rides the row verbatim; the band never moves.
    for confidence, rows in rows_by_confidence.items():
        for row in rows:
            assert abs(row["self_confidence"] - confidence) < 1e-9, (
                f"the drive at confidence {confidence} persisted "
                f"{row['self_confidence']} — the self-report is persisted verbatim, "
                "not clamped or rounded (CT-JUDGE-07)"
            )
            assert row["band"] == "secure", (
                f"the drive at confidence {confidence} persisted band "
                f"{row['band']!r} — the verdict's content is independent of the "
                "self-report's size (CT-JUDGE-07)"
            )


def test_tc_judge_c07_the_judge_module_carries_no_escalation_trigger():
    """`TC-JUDGE-C07` (`CT-JUDGE-07`, module-surface assertion, rung 0, P0) — no
    escalation trigger is CALLABLE from `aeh.judge`: the scan is call-shaped
    (`should_escalate(` / `enqueue_*(...)`), so the docstring's legitimate mention
    of #93's consumer does not false-positive, and the scanner's own positive
    control proves it sees the shape it refuses."""
    import aeh.judge as judge_module

    source = Path(judge_module_path(judge_module)).read_text(encoding="utf-8")
    hits = re.findall(_ESCALATION_CALL_SITES, source)
    assert hits == [], (
        f"`aeh.judge` carries escalation call site(s) {hits} — a consumer treating "
        "the self-report as the escalation trigger violates HLD R22: a model's "
        "self-report is not an observable, and routing is #93's consumer alone "
        "(CT-JUDGE-07)"
    )
    # The scanner's teeth: the same scan catches a planted call shape.
    control_hits = re.findall(_ESCALATION_CALL_SITES, _POSITIVE_CONTROL)
    assert control_hits == ["should_escalate(", "enqueue_escalation("], (
        f"the escalation-call scanner returned {control_hits} on its own positive "
        "control — a scan that cannot fire is not a scan (CT-JUDGE-07)"
    )


def judge_module_path(judge_module: Any) -> str:
    return judge_module.__file__