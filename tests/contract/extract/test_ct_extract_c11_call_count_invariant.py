"""`CT-EXTRACT-11` — one model call per (submission, judged criterion), and cost
does not multiply by panel size (`TC-EXTRACT-C11`).

Case of test plan §6.11.8; issue #72 (TS-65). Written ahead of #68 (`M-EXTRACT`);
registered in `WRITTEN_AHEAD_BLOCKERS` under `"#68 extraction contract suite (TS-65)"`.

The clause: exactly ONE model call per (submission, judged criterion) — ~5,250 calls
at 350 students x 15 judged criteria — on one small model. Cost does **not** multiply
by panel size (NFR-EXTRACT-01); a change that made it do so would multiply the run's
dominant cost, and nothing else in the suite would notice.

Halves:
1. **The exact count, rung 2** — a package carrying one deterministic and two judged
   criteria: the run's extraction makes exactly TWO calls — one per (submission,
   judged criterion), the deterministic criterion contributing ZERO (the cost-side
   reading of `TC-EXTRACT-C07`'s empty-set clause: 5,250 = 350 x 15 *judged*).
2. **The panel-depth invariance, rung 2** — the decisive assertion, the clause's own
   warning: the same two judged criteria are extracted at panel depth 1, 3 and 5, and
   the extraction call count is UNCHANGED — two, at every depth. Extraction is
   per-(submission, criterion), never per-judge; the panel multiplies *scoring* work,
   not *extraction* work.

Discriminator: a change that makes extraction per-judge (a judge dimension in the
extraction loop, a per-judge prompt) turns half 2 red at depth > 1 while depth 1
stays green and every `FR-EXTRACT-*` case — which runs depth 1 or never counts calls
— stays green; counting calls for deterministic criteria turns half 1 red. The
invariance is why the oracle counts across THREE depths rather than asserting one
count: a constant two would also pass a wrong "per-run" reading.

**Disclosed stand-ins** (suite register, `_doubles.py`): D4 — `CountingProvider`
delegates every call to a real `RecordedFixtureProvider` and counts `complete()`
calls, which is exactly this case's instrument; the fixture provider contract is
never doubled away. The reply is recorded per judged criterion's assembled request
(D1). **Isolation: rung 2** — real store, real ledger, real panel enumeration through
the shipped `Orchestrator`; the model boundary the only fake.
"""

from __future__ import annotations

from typing import Any

import pytest

from aeh.orch import STAGE_EXTRACT, Orchestrator
from tests.support.conf_builders import edge_panel
from tests.support.extract_vocabulary import (
    WORKER,
    extractor_ref,
    sampling_params,
    span_completion,
)
from tests.support.impl import EXTRACT_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID
from tests.contract.extract._doubles import (
    CountingProvider,
    build_markdown,
    make_world,
    require_extract_surface,
    resolved_config,
)

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]

_MARKDOWN = build_markdown(
    "The rate is 12 kg per hour.\n"
)
_SPANS = [
    {
        "start": 41,
        "end": 65,
        "text": "The rate is 12 kg per hour.",
        "region_kind": "transcribed_text",
    }
]
_JUDGED = [
    {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "holistic"},
]
# The design's "deterministic criterion" is the shipped catalog's `kind: "mcq"`.
_DETERMINISTIC = {"criterion_id": "C0", "kind": "mcq",
                  "scoring_model": "deterministic"}


def _extract_count(world: Any, panel: tuple) -> int:
    """Create a run at the given panel depth, extract its units with a counting
    provider, and return the call count."""
    AssembleRequest = require(EXTRACT_MODULE, "assemble_request", issue="#68")
    PromptFields = require(EXTRACT_MODULE, "prompt_fields", issue="#68")
    Worker = require(EXTRACT_MODULE, WORKER, issue="#68")
    model_ref = extractor_ref()
    orchestrator = Orchestrator(world.store)
    run_id = orchestrator.create_run(
        ORCH_COHORT_ID, world.version, resolved_config(panel)
    )
    units = orchestrator.lease("w-extract", STAGE_EXTRACT, 10)
    counter = CountingProvider(world.provider)
    for unit in units:
        if unit.criterion_id == "C0":
            continue  # no extract unit exists for an mcq criterion (C07); guard only
        world.provider.record(
            PromptFields(AssembleRequest(unit)), model_ref, sampling_params(),
            span_completion(_SPANS, build_id="ct-c11-build"),
        )
        Worker(world.store, counter, model_ref).process(unit)
    return counter.count


def test_tc_extract_c11_exactly_one_call_per_submission_and_judged_criterion(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C11` half 1 — one deterministic and two judged criteria: exactly
    TWO extraction calls, one per (submission, judged criterion); the deterministic
    criterion contributes zero."""
    require(EXTRACT_MODULE, issue="#68")
    require_extract_surface()
    world = make_world(tmp_data_dir, make_fixture_provider, markdown=_MARKDOWN,
                       criteria=[_DETERMINISTIC] + _JUDGED)
    try:
        count = _extract_count(world, edge_panel(1))
        assert count == 2, (
            f"TC-EXTRACT-C11: the run made {count} extraction calls for one "
            f"submission with two judged criteria — the contract is exactly ONE per "
            f"(submission, judged criterion), the deterministic criterion "
            f"contributing zero (5,250 = 350 x 15 JUDGED)"
        )
    finally:
        world.close()


def test_tc_extract_c11_the_call_count_does_not_multiply_by_panel_size(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C11` half 2 — the decisive assertion: the same two judged criteria
    extracted at panel depth 1, 3 and 5 make the SAME number of calls. Extraction is
    per-(submission, criterion), never per-judge."""
    require(EXTRACT_MODULE, issue="#68")
    require_extract_surface()
    world = make_world(tmp_data_dir, make_fixture_provider, markdown=_MARKDOWN,
                       criteria=_JUDGED)
    try:
        depth_1 = _extract_count(world, edge_panel(1))
        depth_3 = _extract_count(world, edge_panel(3))
        depth_5 = _extract_count(world, edge_panel(5))
        assert depth_1 == depth_3 == depth_5 == 2, (
            f"TC-EXTRACT-C11: extraction made {depth_1}/{depth_3}/{depth_5} calls at "
            f"panel depth 1/3/5 — the count multiplied by panel size, which "
            f"multiplies the run's dominant cost (NFR-EXTRACT-01)"
        )
    finally:
        world.close()
