"""Issue #637 (TS-150) — `TC-HELP-05` / NFR-HELP-01 (P2): answer latency and retrieval time.

The reference question set (`help_vocabulary.REFERENCE_SET`, twenty manuals questions) is asked
on a cloud QA model (an OpenRouter build) and on edge-local's (the first local judge,
FR-CONF-30). Each answer's latency is the assistant's own measured wall time **plus** the recorded
double's latency envelope for that profile — the replayed `latency_ms` stands in for the model, so
the measurement is "what the assistant adds, on top of what the backend took". p95 must sit within
10 s (cloud) / 30 s (edge); retrieval — measured as the time from `ask()` entry to the provider
call, which is retrieval plus prompt assembly, an upper bound — stays under 200 ms for every
question. Assumption (NFR-HELP-01): measured on the reference hardware, not derived.

Not implemented here: the plan's **live nightly arm** (the same set against the real resolved
model). It needs the live provider wiring #636 builds and belongs to the `live` tier.

**Written ahead of #636**; `integration` + `slow` because twenty asks per profile is a
measurement, not a check.
"""

from __future__ import annotations

import time

import pytest

from tests.support import help_vocabulary as hv

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.mark.writtenahead
@pytest.mark.parametrize("profile", ["cloud", "edge"])
def test_tc_help_05_p95_answer_latency_and_retrieval_within_budget(tmp_path, profile):
    from tests.support.conf_builders import EDGE_JUDGE, HOSTED_JUDGE

    model_ref = HOSTED_JUDGE if profile == "cloud" else EDGE_JUDGE
    data_dir = tmp_path / "data"
    rig = hv.build_rig(data_dir, tmp_path / "rec", model_ref=model_ref)
    rig.assistant.ask(hv.REFERENCE_SET[0].question)  # warm-up, not measured
    totals, retrievals, problems = [], [], []
    for transcript in hv.REFERENCE_SET:
        calls_before = len(rig.double.calls)
        started = time.perf_counter()
        rig.assistant.ask(transcript.question)
        wall_ms = (time.perf_counter() - started) * 1000
        new = rig.double.calls[calls_before:]
        if len(new) > 1:
            problems.append(f"{transcript.question!r}: {len(new)} model calls for one answer")
        envelope = sum(c.completion.latency_ms for c in new)
        totals.append(wall_ms + envelope)
        retrievals.append(((new[0].entered_at - started) * 1000) if new else wall_ms)
    rig.store.close()
    p95 = hv.percentile_95(totals)
    if p95 > hv.P95_BUDGET_MS[profile]:
        problems.append(f"{profile}: p95 answer latency {p95:.0f} ms > {hv.P95_BUDGET_MS[profile]} ms")
    slow = [f"{q.question!r}: {r:.1f} ms" for q, r in zip(hv.REFERENCE_SET, retrievals)
            if r >= hv.RETRIEVAL_BUDGET_MS]
    if slow:
        problems.append(f"retrieval >= {hv.RETRIEVAL_BUDGET_MS} ms: {slow}")
    assert not problems, "\n".join(problems)
