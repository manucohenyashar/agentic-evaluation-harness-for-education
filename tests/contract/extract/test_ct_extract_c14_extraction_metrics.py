"""`CT-EXTRACT-14` — the four extraction metrics, and the per-criterion reading that
is contract (`TC-EXTRACT-C14`).

Case of test plan §6.11.8; issue #72 (TS-65). Written ahead of #68 (`M-EXTRACT`);
registered in `WRITTEN_AHEAD_BLOCKERS` under `"#68 extraction contract metrics
(TS-65)"` — the full `TS65_EXTRACT_SYMBOLS` conjunction (`ExtractionWorker` ...
and `extraction_metrics`), separate from the suite's `TS-26`-shaped entry so the
registry names no symbol these tests do not use.

The clause: the module emits spans-per-unit distribution, empty-result rate per
criterion, second-family disagreement rate, and extraction latency — and the stated
*reading* on the second is CONTRACT: a rising empty-result rate **on one criterion**
means that criterion's `evidence_type` is probably wrong. The aggregate cannot
support that reading, so emitting it only aggregated is the violation.

Halves:
1. **Names, rung 2** — the run's metrics resolve under the four names, the run had
   two units so the spans-per-unit distribution is non-empty, and the
   second-family disagreement rate is the honest ABSENT (`None` — no second family
   ran; a simulated zero would lie, the `RunAggregates` precedent's own rule).
2. **The per-criterion reading, rung 2** — one run, two judged criteria, one
   extracted with spans and one with an EMPTY span list: `empty_result_rate`
   subscripted per criterion returns 0.0 for the spanned criterion and 1.0 for the
   empty one, over exactly the criteria that ran. The rate DISTINGUISHES the
   criterion with the data problem from the one without — which is the clause's
   stated reading, and the thing an aggregate cannot do.

Discriminator: an emitter that folds the rate into one aggregate number turns half 2
red (nothing per criterion to subscript) while half 1 stays green; a simulated zero
for the un-run second family turns half 1 red; missing or renamed metrics turn both
red — while every `FR-EXTRACT-*` case, which never reads metrics, stays green.

**Disclosed stand-ins** (suite register, `_doubles.py`): D5 — the channel is the
`aeh.ingest` `run_aggregates` precedent: ONE module-level emitter over the store,
`extraction_metrics(handle, run_id)`, returning the named signals as attributes;
`empty_result_rate` a per-criterion mapping (criterion id -> rate); the names are
the plan's words in snake case (`EXTRACT_METRIC_NAMES`, the vocabulary's). D1 (the
empty criterion's reply is the recorded empty-span list). **Isolation: rung 2** —
real store, real ledger, two real extract units in one run.
"""

from __future__ import annotations

from typing import Any

import pytest

from aeh.orch import STAGE_EXTRACT, Orchestrator
from tests.support.conf_builders import edge_panel
from tests.support.extract_vocabulary import (
    EXTRACT_METRIC_NAMES,
    METRICS_ACCESSOR,
    WORKER,
    extractor_ref,
    sampling_params,
    span_completion,
)
from tests.support.impl import EXTRACT_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID
from tests.contract.extract._doubles import (
    build_markdown,
    make_world,
    require_extract_surface,
    resolved_config,
)

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]

_MARKDOWN = build_markdown("The equilibrium is stable for small perturbations.\n")
_SPANS = [
    {
        "start": 41,
        "end": 89,
        "text": "The equilibrium is stable for small perturbations.",
        "region_kind": "transcribed_text",
    }
]
_CRITERIA = [
    {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "holistic"},
]


def _run_two_criteria(world: Any, *, empty_second: bool) -> str:
    """One run, two extract units; C1 extracted with spans, C2 with the reply the
    caller chose (spans, or the empty selection)."""
    AssembleRequest = require(EXTRACT_MODULE, "assemble_request", issue="#68")
    PromptFields = require(EXTRACT_MODULE, "prompt_fields", issue="#68")
    Worker = require(EXTRACT_MODULE, WORKER, issue="#68")
    model_ref = extractor_ref()
    orchestrator = Orchestrator(world.store)
    run_id = orchestrator.create_run(
        ORCH_COHORT_ID, world.version, resolved_config(edge_panel(1))
    )
    units = orchestrator.lease("w-extract", STAGE_EXTRACT, 2)
    by_criterion = {u.criterion_id: u for u in units}
    assert set(by_criterion) == {"C1", "C2"}, (
        "TC-EXTRACT-C14: precondition — the run did not enumerate both judged criteria"
    )
    for criterion_id, spans in (
        ("C1", _SPANS),
        ("C2", [] if empty_second else _SPANS),
    ):
        world.provider.record(
            PromptFields(AssembleRequest(by_criterion[criterion_id])),
            model_ref, sampling_params(),
            span_completion(spans, build_id="ct-c14-build"),
        )
        Worker(world.store, world.provider, model_ref).process(
            by_criterion[criterion_id]
        )
    return run_id


def _metrics(world: Any, run_id: str) -> Any:
    """The run's emitted metrics — the ONE module-level emitter, D5's channel."""
    handle = world.store.cohort(ORCH_COHORT_ID)
    return require(EXTRACT_MODULE, METRICS_ACCESSOR, issue="#68")(handle, run_id)


def test_tc_extract_c14_the_four_metrics_are_emitted_under_their_names(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C14` half 1 — the metrics resolve under the plan's names; the
    spans-per-unit distribution is non-empty for a run that extracted; the
    second-family disagreement rate is the honest ABSENT when no second family
    ran."""
    require(EXTRACT_MODULE, issue="#68")
    require_extract_surface()
    require(EXTRACT_MODULE, METRICS_ACCESSOR, issue="#68")
    world = make_world(tmp_data_dir, make_fixture_provider, markdown=_MARKDOWN,
                       criteria=_CRITERIA)
    try:
        run_id = _run_two_criteria(world, empty_second=True)
        metrics = _metrics(world, run_id)
        missing = [n for n in EXTRACT_METRIC_NAMES if not hasattr(metrics, n)]
        assert missing == [], (
            f"TC-EXTRACT-C14: the metrics emitter does not carry {missing} — the "
            f"clause names these four, and the names are the contract"
        )
        assert metrics.spans_per_unit, (
            "TC-EXTRACT-C14: the spans-per-unit distribution is empty for a run "
            "that extracted two units — the signal is not produced"
        )
        assert metrics.second_family_disagreement_rate is None, (
            f"TC-EXTRACT-C14: second_family_disagreement_rate is "
            f"{metrics.second_family_disagreement_rate!r} but no second-family "
            f"extraction ran — None is the honest absent; a zero would lie"
        )
        assert metrics.extraction_latency is not None, (
            "TC-EXTRACT-C14: extraction_latency was not emitted for a run that "
            "extracted twice"
        )
    finally:
        world.close()


def test_tc_extract_c14_the_empty_result_rate_is_readable_per_criterion(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C14` half 2 — the clause's stated reading, contract: one criterion
    extracted spans, the other an empty list, and the per-criterion rate
    DISTINGUISHES them (0.0 vs 1.0) over exactly the criteria that ran. An aggregate
    cannot support the reading."""
    require(EXTRACT_MODULE, issue="#68")
    require_extract_surface()
    require(EXTRACT_MODULE, METRICS_ACCESSOR, issue="#68")
    world = make_world(tmp_data_dir, make_fixture_provider, markdown=_MARKDOWN,
                       criteria=_CRITERIA)
    try:
        run_id = _run_two_criteria(world, empty_second=True)
        rate = _metrics(world, run_id).empty_result_rate
        assert set(rate) == {"C1", "C2"}, (
            f"TC-EXTRACT-C14: empty_result_rate is keyed {set(rate)!r} — it must be "
            f"per criterion, over exactly the criteria that ran"
        )
        assert rate["C1"] == 0.0, (
            f"TC-EXTRACT-C14: C1 extracted spans yet its empty-result rate is "
            f"{rate['C1']!r}"
        )
        assert rate["C2"] == 1.0, (
            f"TC-EXTRACT-C14: C2's extraction was empty yet its rate is "
            f"{rate['C2']!r} — a rising empty-result rate ON ONE CRITERION is the "
            f"clause's stated signal that this criterion's evidence_type is "
            f"probably wrong, and the aggregate cannot say that"
        )
    finally:
        world.close()
