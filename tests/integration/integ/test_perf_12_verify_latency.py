"""`TS-86` (issue #380) — `PERF-12`: the gate's per-call latency (`CT-INTEG-18`,
`NFR-INTEG-01`).

| Case | Workload | Oracle |
|---|---|---|
| `PERF-12` | 1,000 `verify` calls on 4-page submissions with 20 spans each, warm cache | median `verify` time ≤ 2 ms |

**Why a median and not a mean.** One stall — a page fault, the OS scheduling something else —
moves a mean and tells you nothing about the gate. The median is what a run of 23,000 cells
actually pays per cell, which is the figure `NFR-INTEG-01`'s 1% budget is built out of.

**Warm cache is the stated precondition, and it is the honest one.** `FR-INTEG-11` caches the
document per `(run, content_hash)`, and a production run's second cell onward is warm — the
gate runs per cell and a submission has many. Measuring cold would measure the blob store.
The first call is therefore excluded explicitly rather than absorbed.

**Gated on the CI runner only; elsewhere informational (Q-19).** The plan says so, and the
reason is that a threshold in milliseconds is a statement about a machine. `HARNESS_PERF_GATE`
is the switch: unset (a developer box, this repo's normal case) the measurement still runs and
still reports, and only the **shape** assertions bind — that the median is finite and that a
warm call is faster than a cold one. Set, the 2 ms threshold binds. Recording the machine is
part of the contract, so the measurement is printed either way.

**This is a real workload, not a micro-benchmark.** Four pages of Markdown and twenty spans
per cell, verified against the document's actual bytes — `verify_span` compares in bytes, so
a fixture with one short span would measure the function-call overhead and nothing else.

Marked `slow`, so it is outside the fast tier by design (§4.7); `integration` because it
stands on a real store.
"""

from __future__ import annotations

import os
import statistics
import time
from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.integ import IntegrityGate
from aeh.store import open_store
from tests.support.integ_vocabulary import (
    ExtractionView,
    PanelFlags,
    Span,
    document_id_for,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration, pytest.mark.slow]

#: The plan's threshold. Not widened — `HARNESS_PERF_GATE` decides whether it binds, never
#: what it is.
MEDIAN_BUDGET_MS = 2.0

#: The plan's call count. `HARNESS_PERF12_CALLS` lowers it for a slower box (seam rule 3); it
#: changes the sample size, never the threshold.
CALLS_ENV = "HARNESS_PERF12_CALLS"
CALLS_DEFAULT = 1000

#: Set on the CI runner, where the threshold is a statement about a known machine (Q-19).
PERF_GATE_ENV = "HARNESS_PERF_GATE"

#: "4-page submissions": four pages of prose, each paragraph carrying a distinct sentence the
#: spans quote, so twenty spans land at twenty different offsets across the whole document.
_PARAGRAPH = (
    "The thesis of section {n} is stated plainly, and the argument that follows rests on it "
    "throughout. Evidence is cited in the customary form, and the counter-argument is "
    "acknowledged before it is answered. The conclusion of section {n} restates the claim "
    "in the terms the introduction set out, without overreaching beyond what was shown. "
)
PAGES = 4
PARAGRAPHS_PER_PAGE = 5
SPAN_COUNT = 20

SUBMISSION = "SUB-101"
CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)


def _document_text() -> str:
    return "\n\n".join(
        _PARAGRAPH.format(n=index)
        for index in range(PAGES * PARAGRAPHS_PER_PAGE)
    )


def _spans(text: str) -> list[Span]:
    """Twenty spans at twenty distinct offsets, each quoting real document bytes.

    Real quotations rather than invented text: a span that does not appear in the document
    short-circuits verification, so a fixture of hallucinated spans would measure the failure
    path and report it as the gate's cost.
    """
    needle = "thesis of section"
    spans: list[Span] = []
    cursor = 0
    while len(spans) < SPAN_COUNT:
        start = text.find(needle, cursor)
        if start < 0:
            cursor = 0
            start = text.find(needle, cursor)
            if start < 0:
                break
        end = start + len(needle)
        spans.append(Span(start, end, text[start:end]))
        cursor = end
    return spans


def _calls() -> int:
    raw = os.environ.get(CALLS_ENV)
    if raw is None or not raw.strip():
        return CALLS_DEFAULT
    value = int(raw)
    if value < 2:
        raise ValueError(
            f"{CALLS_ENV}={raw!r} must be at least 2: the first call is the cold one and is "
            "excluded, so a sample of one leaves nothing to take a median of."
        )
    return value


@pytest.fixture
def gate_world(tmp_data_dir):
    """A run whose one submission carries a four-page blob-backed document and 20 spans."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        handle = store.cohort(ORCH_COHORT_ID)
        text = _document_text()
        content_hash = store.blobs().put(text.encode("utf-8"))
        with handle.transaction() as tx:
            tx.execute(
                "INSERT INTO document (document_id, submission_id, content_hash) "
                "VALUES (:d, :s, :h)",
                d=document_id_for(SUBMISSION), s=SUBMISSION, h=content_hash,
            )
        orchestrator.enumerate_units(run_id)
        spans = _spans(text)
        assert len(spans) == SPAN_COUNT, (
            f"the fixture produced {len(spans)} spans, not {SPAN_COUNT}"
        )
        view = ExtractionView(spans=spans, panel=PanelFlags((True, True, True)))
        gate = IntegrityGate(handle, store.blobs(), view, ocr_conf_floor=0.70)
        yield store, run_id, gate, text
    finally:
        store.close()


def _timed_calls(gate: Any, run_id: str, count: int) -> list[float]:
    """`count` `verify` calls, each timed in milliseconds, cold call first."""
    samples: list[float] = []
    for _index in range(count):
        started = time.perf_counter()
        gate.verify(run_id, SUBMISSION, CRITERION)
        samples.append((time.perf_counter() - started) * 1000.0)
    return samples


# --- PERF-12 --------------------------------------------------------------------------------


def test_perf_12_the_warm_median_verify_stays_inside_the_budget(gate_world, capsys):
    """Median warm `verify` ≤ 2 ms, gated on the CI runner and informational elsewhere."""
    _store, run_id, gate, text = gate_world
    count = _calls()

    samples = _timed_calls(gate, run_id, count)
    cold, warm = samples[0], samples[1:]
    median = statistics.median(warm)

    with capsys.disabled():
        print(
            f"\nPERF-12: {len(warm)} warm calls over a {len(text)}-byte document with "
            f"{SPAN_COUNT} spans — median {median:.3f} ms, "
            f"p95 {statistics.quantiles(warm, n=20)[-1]:.3f} ms, cold {cold:.3f} ms "
            f"(budget {MEDIAN_BUDGET_MS} ms; gate "
            f"{'ON' if os.environ.get(PERF_GATE_ENV) else 'OFF — informational, Q-19'})"
        )

    # Shape assertions — these bind everywhere, because they are about the gate and not about
    # the machine. A median that is zero or absurd means the measurement, not the gate, is
    # what this case is reporting.
    assert median > 0.0, "the median warm verify took no measurable time at all"
    assert len(warm) == count - 1

    if not os.environ.get(PERF_GATE_ENV):
        pytest.skip(
            f"median {median:.3f} ms against a {MEDIAN_BUDGET_MS} ms budget — informational "
            f"off the CI runner (Q-19). Set {PERF_GATE_ENV} to bind the threshold."
        )

    assert median <= MEDIAN_BUDGET_MS, (
        f"median warm verify is {median:.3f} ms against CT-INTEG-18's {MEDIAN_BUDGET_MS} ms. "
        "At 23,000 cells that is the difference between the gate costing under 1% of run "
        "wall clock and costing a visible share of it (NFR-INTEG-01)"
    )


def test_perf_12_the_warm_path_is_cheaper_than_the_cold_one(gate_world):
    """The cache is doing something — the warm median beats the cold call.

    Not a performance gate: a threshold-free ordering that binds on every machine. Without it,
    a gate whose cache silently stopped working would go on passing the case above on a fast
    box, and `PERF-06`'s 1% budget would drift back to the 2.25% that prompted this delta.
    """
    _store, run_id, gate, _text = gate_world

    samples = _timed_calls(gate, run_id, min(_calls(), 60))
    cold, warm = samples[0], samples[1:]

    assert statistics.median(warm) < cold, (
        f"the warm median ({statistics.median(warm):.3f} ms) is not below the cold call "
        f"({cold:.3f} ms); the document cache is not saving the read and hash it exists to "
        "save (FR-INTEG-11, GAP-24)"
    )
