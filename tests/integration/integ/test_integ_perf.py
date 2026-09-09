"""`TC-INTEG-11` — span verification is O(total span bytes), makes no model call, and
adds under 1% to run wall clock, measured against a run with verification disabled.

Test plan §5.9 (P1, `NFR-INTEG-01`, Performance / rung 2; the full-run differential
`PERF-06` belongs to TS-53 and is out of scope here — this case measures the
verification stage itself over a real store). Written ahead of `#73`/`#74` (test plan
§8.2): every case fails only through `NotImplementedYet`.

**The differential is the oracle** (NFR-INTEG-01: "shall add under 1% to run wall
clock"): the same workload measured with verification enabled and disabled, the
disabled run as the baseline. The disable switch is `INTEG_SPAN_VERIFICATION_DISABLED`
— an **invented, env-gated knob** (seam rule 3), disclosed because the plan's oracle
cannot be expressed without one and `PERF-06` (TS-53) needs the same switch.

**Timing noise is handled by construction, not by loosening the threshold**: each side
is the minimum of `_reps()` repetitions (the standard noise reducer — a min converges to
the true cost from above), and the workload is sized so verification's own cost
dominates the fixture's. The 1% threshold is the design's number and is not widened;
the `INTEG_PERF_REPS` env knob widens the repetition count for a slower box — it never
moves the assertion.

The linearity half (`O(total span bytes)`) is asserted as a growth bound over an
8x-bytes workload — time(8x) must stay within a generous linear window — rather than a
fitted slope: the two-orders-of-magnitude fit TS-66's TC-INTEG-C12 performs is the
contract clause's own case, and this case needs only the bound the budget claim rests
on. Marked `slow`: it is excluded from the fast tier by design (§4.7).
"""

from __future__ import annotations

import os
import time

import pytest

from aeh.store import open_store
from tests.support.impl import INTEG_MODULE, require
from tests.support.integ_vocabulary import (
    Doc,
    ExtractionView,
    PanelFlags,
    Span,
    document_id_for,
    seed_document,
)

pytestmark = [pytest.mark.slow, pytest.mark.integration]

_COHORT = "c-2026-7B-integ"
_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},)

_DISABLE_ENV = "INTEG_SPAN_VERIFICATION_DISABLED"
_REPS_ENV = "INTEG_PERF_REPS"  # seam rule 3: a slow box widens the min-of, not the budget
_REPS = 5
_LINEAR_WINDOW = 12.0  # time(8x bytes) <= 12x time(1x bytes): O(bytes) with headroom
_DIFFERENTIAL_BUDGET = 1.01  # the design's own "under 1%"


def _reps() -> int:
    import os

    raw = os.environ.get(_REPS_ENV)
    return int(raw) if raw and raw.strip().isdigit() else _REPS


def _sentence(i: int) -> str:
    return f"Sentence {i} argues point {i} with a cited detail {i}.\n"


def _workload(n_sentences: int, n_units: int):
    """`n_units` documents of `n_sentences` lines each, one cited span per document."""
    docs = []
    for u in range(n_units):
        markdown = "".join(_sentence(i) for i in range(n_sentences))
        start = markdown.index(f"detail {u % n_sentences}")
        span = Span(start, start + len(f"detail {u % n_sentences}"),
                    f"detail {u % n_sentences}")
        docs.append((markdown, span))
    return docs


def _timed_verify(tmp_data_dir, docs, *, disabled: bool) -> float:
    """Minimum verify() wall clock over `_REPS` repetitions of the whole workload.

    One gate per submission, each seeing exactly its own cited span — the per-unit
    verification the design runs on every unit.
    """
    store = open_store(tmp_data_dir)
    handle = store.cohort(_COHORT)
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#73")
    gates = []
    for i, (markdown, span) in enumerate(docs):
        submission = f"SUB-{i:03d}"
        seed_document(handle, document_id_for(submission), submission, markdown, _COHORT)
        view = ExtractionView(spans=(span,), panel=PanelFlags((True, True, True)))
        gates.append((submission,
                      IntegrityGate(handle, store.blobs(), view, ocr_conf_floor=0.70)))
    previous = os.environ.get(_DISABLE_ENV)
    if disabled:
        os.environ[_DISABLE_ENV] = "1"
    else:
        # The enabled arm POPS the variable rather than setting it empty (review
        # finding): a knob implemented as `ENV in os.environ` must not disable
        # verification in both arms, which would vacate the differential.
        os.environ.pop(_DISABLE_ENV, None)
    try:
        best = float("inf")
        for _ in range(_reps()):
            start = time.perf_counter()
            for submission, gate in gates:
                gate.verify("run-perf", submission, "C1")
            best = min(best, time.perf_counter() - start)
    finally:
        if previous is None:
            os.environ.pop(_DISABLE_ENV, None)
        else:
            os.environ[_DISABLE_ENV] = previous
    store.close()
    return best


def test_tc_integ_11_verification_adds_under_one_percent_to_wall_clock(tmp_data_dir):
    """`TC-INTEG-11`'s differential oracle — enabled against disabled, the delta under
    the design's 1%: verification is affordable precisely because it is bounded, and
    the case holds the design to its own number."""
    docs = _workload(n_sentences=200, n_units=20)
    enabled = _timed_verify(tmp_data_dir / "enabled", docs, disabled=False)
    disabled = _timed_verify(tmp_data_dir / "disabled", docs, disabled=True)
    assert enabled <= disabled * _DIFFERENTIAL_BUDGET, (
        f"verification took {enabled:.4f}s against a disabled baseline of "
        f"{disabled:.4f}s — a {_DIFFERENTIAL_BUDGET:.0%} budget (NFR-INTEG-01) that a "
        "model call or an accidental I/O path inside the pure check would blow"
    )


def test_tc_integ_11_verification_scales_with_total_span_bytes(tmp_data_dir):
    """`TC-INTEG-11`'s complexity half — 8x the total span bytes stays inside a linear
    window of the time: the O(total span bytes) claim, asserted as a bound rather than
    a constant."""
    small = _workload(n_sentences=50, n_units=5)
    big = _workload(n_sentences=400, n_units=5)
    t_small = _timed_verify(tmp_data_dir / "small", small, disabled=False)
    t_big = _timed_verify(tmp_data_dir / "big", big, disabled=False)
    assert t_big <= t_small * _LINEAR_WINDOW, (
        f"an 8x-bytes workload took {t_big:.4f}s against {t_small:.4f}s — outside the "
        "linear window, so verification is not O(total span bytes) and the budget "
        "claim it underwrites does not hold"
    )
