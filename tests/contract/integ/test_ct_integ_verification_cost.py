"""`CT-INTEG-12` — span verification is **O(total span bytes)** with **no model
call** and adds **under 1%** to run wall clock, and it runs on **every** unit
(`TC-INTEG-C12`).

Case of test plan §6.11.9 (perf); TS-66 (issue #77). Written ahead of `#74`
(the gate) — the pure-function half lands with `#73`, which the gate consumes.

The clause's own warning is what makes this a contract case and not a
benchmark: the check runs on every unit and is only affordable because of that
bound, so a change making it model-assisted or set-scanning would change the
run's cost structure — the case holds the bound itself, in three limbs:

1. **The complexity fit** — verification time measured across a workload
   spanning two orders of magnitude of total span bytes (128x, seven
   doublings), the fitted growth exponent asserted LINEAR in log-log space
   rather than a single constant ratio: the quadratic regression a
   model-assisted or rescanning implementation produces fails; the exponent
   window and its purpose are disclosed below.
2. **The budget** — the same workload with verification enabled and disabled
   (`INTEG_SPAN_VERIFICATION_DISABLED`, the #75-declared knob): the delta under
   the design's own 1%, the min-of-reps noise reducer the #75 perf suite
   established (`INTEG_PERF_REPS` widens the reps, never the budget).
3. **Exact coverage** — the per-unit verdicts over a workload where every unit
   carries a UNIQUE invalid span: a verifier that samples, caches by position,
   or verifies unit 0 and extrapolates fails on a later unit's different
   answer. Total, not sampled, asserted per unit.

**Disclosures register** (nothing new is minted beyond the #75 table):

| Name | Status |
|---|---|
| exponent window | the fit asserts 0.5 <= alpha <= 1.5 over the log-log regression: the LOAD-BEARING side is the upper bound (alpha near 2 is the quadratic the clause forbids); the lower bound guards the fixture's own vacuity (bytes with no effect on time means the measurement broke). Both are disclosed as this case's reading of "fitted growth is linear" |
| noise handling | min-of `_reps()` per size (the #75 convention: a min converges to the true cost from above); `slow`-marked so the full non-live tier owns it, exactly as the conform/console perf contracts do |
| disable switch | `INTEG_SPAN_VERIFICATION_DISABLED`, the #75-declared knob — the enabled arm POPS the variable (the #75 review finding: a membership-test knob must not see it set empty) |
| coverage observable | per-unit `spans_verified` verdicts, the only coverage surface the declared signals expose; `INTEG_RATE_METRICS` (CT-INTEG-14) aggregates them per criterion and is that case's artifact |
"""

from __future__ import annotations

import math
import os
import time

import aeh.prov
import pytest

from tests.contract.integ._doubles import block_module_surfaces
from tests.support.impl import INTEG_MODULE, require
from tests.support.integ_vocabulary import (
    ExtractionView,
    PanelFlags,
    Span,
    document_id_for,
    seed_document,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.contract

_COHORT = ORCH_COHORT_ID
_DISABLE_ENV = "INTEG_SPAN_VERIFICATION_DISABLED"
_REPS_ENV = "INTEG_PERF_REPS"
_REPS = 3
_EXPONENT_WINDOW = (0.5, 1.5)
_BUDGET = 1.01  # the design's own "under 1%"
_COVERAGE_UNITS = 12


def _reps() -> int:
    raw = os.environ.get(_REPS_ENV)
    return int(raw) if raw and raw.strip().isdigit() else _REPS


def _sentence(i: int) -> str:
    return f"Sentence {i} argues point {i} with a cited detail {i}.\n"


def _workload(n_sentences: int, n_units: int = 4):
    """`n_units` documents of `n_sentences` lines each, one cited span per unit —
    the total span bytes scale with `n_sentences` (span text grows with the
    sentence), the document text with it too."""
    docs = []
    for u in range(n_units):
        markdown = "".join(_sentence(i) for i in range(n_sentences))
        needle = f"detail {u % n_sentences}"
        start = markdown.encode("utf-8").find(needle.encode("utf-8"))
        docs.append((markdown, (start, start + len(needle), needle)))
    return docs


def _total_span_bytes(docs) -> int:
    return sum(end - start for _, (start, end, _) in docs)


def _timed_verify(tmp_data_dir, docs, *, disabled: bool) -> float:
    """Minimum verify() wall clock over `_reps()` repetitions, with the disable
    knob armed exactly as the #75 review finding requires."""
    store = None
    previous = os.environ.get(_DISABLE_ENV)
    if disabled:
        os.environ[_DISABLE_ENV] = "1"
    else:
        os.environ.pop(_DISABLE_ENV, None)
    try:
        IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#74")
        store = open_store(tmp_data_dir)
        orch, run_id, _version = seed_run(
            store, submissions=tuple(f"SUB-{i:03d}" for i in range(len(docs))),
            criteria=({"criterion_id": "C1", "kind": "open",
                       "scoring_model": "holistic"},))
        handle = store.cohort(_COHORT)
        gates = []
        for i, (markdown, (start, end, text)) in enumerate(docs):
            submission = f"SUB-{i:03d}"
            seed_document(handle, document_id_for(submission), submission,
                          markdown, _COHORT)
            view = ExtractionView(spans=(Span(start, end, text),),
                                  panel=PanelFlags((True, True, True)))
            gates.append((submission,
                          IntegrityGate(handle, store.blobs(), view,
                                        ocr_conf_floor=0.70)))
        best = float("inf")
        for _ in range(_reps()):
            started = time.perf_counter()
            for submission, gate in gates:
                gate.verify(run_id, submission, "C1")
            best = min(best, time.perf_counter() - started)
        return best
    finally:
        if previous is None:
            os.environ.pop(_DISABLE_ENV, None)
        else:
            os.environ[_DISABLE_ENV] = previous
        if store is not None:
            store.close()


def _fitted_exponent(points: list[tuple[float, float]]) -> float:
    """The least-squares exponent of log(time) against log(bytes)."""
    xs = [math.log(b) for b, _ in points]
    ys = [math.log(t) for _, t in points]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var = sum((x - mean_x) ** 2 for x in xs)
    return cov / var


# --- limb 1: the complexity fit, two orders of magnitude -------------------------------------


@pytest.mark.writtenahead
@pytest.mark.slow
def test_tc_integ_c12_verification_is_linear_in_total_span_bytes(tmp_data_dir):
    """`TC-INTEG-C12` — the fit: seven doublings of total span bytes (1x..128x,
    past the two orders of magnitude the clause names), time measured per size,
    the log-log growth exponent asserted linear. The quadratic a rescanning or
    model-assisted implementation produces fails the window."""
    sizes = [25, 50, 100, 200, 400, 800, 1600]
    points = []
    for size in sizes:
        docs = _workload(n_sentences=size)
        elapsed = _timed_verify(tmp_data_dir / f"size-{size}", docs, disabled=False)
        points.append((_total_span_bytes(docs), elapsed))
    alpha = _fitted_exponent(points)
    low, high = _EXPONENT_WINDOW
    assert low <= alpha <= high, (
        f"fitted growth exponent {alpha:.2f} outside the linear window {low}..{high} "
        f"over {sizes[0]}..{sizes[-1]} sentences — verification is not O(total span "
        "bytes), and the every-unit budget claim it underwrites does not hold "
        "(NFR-INTEG-01, CT-INTEG-12)"
    )


@pytest.mark.writtenahead
@pytest.mark.slow
def test_tc_integ_c12_verification_adds_under_one_percent_to_run_wall_clock(
        tmp_data_dir):
    """`TC-INTEG-C12` — the budget: the same workload with verification enabled
    and disabled, the delta under the design's 1%. The disable knob is the
    #75-declared seam; the arm order and the POP are the #75 review's."""
    docs = _workload(n_sentences=200)
    enabled = _timed_verify(tmp_data_dir / "enabled", docs, disabled=False)
    disabled = _timed_verify(tmp_data_dir / "disabled", docs, disabled=True)
    assert enabled <= disabled * _BUDGET, (
        f"verification took {enabled:.4f}s against a disabled baseline of "
        f"{disabled:.4f}s — over the 1% budget (NFR-INTEG-01) the clause says makes "
        "every-unit verification affordable"
    )


@pytest.mark.writtenahead
def test_tc_integ_c12_no_unit_verification_needs_a_model_call(tmp_data_dir,
                                                              monkeypatch):
    """`TC-INTEG-C12` — no model call at scale: the whole multi-unit workload
    verifies with every public callable on `aeh.prov` (the model boundary)
    replaced by a raiser. A single model-assisted verification anywhere in the
    sweep raises rather than passing slowly."""
    block_module_surfaces(monkeypatch, aeh.prov)
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#74")
    store = open_store(tmp_data_dir)
    orch, run_id, _version = seed_run(
        store, submissions=tuple(f"SUB-{i:03d}" for i in range(4)),
        criteria=({"criterion_id": "C1", "kind": "open",
                   "scoring_model": "holistic"},))
    handle = store.cohort(_COHORT)
    for i, (markdown, _) in enumerate(_workload(n_sentences=40, n_units=4)):
        submission = f"SUB-{i:03d}"
        seed_document(handle, document_id_for(submission), submission, markdown,
                      _COHORT)
    for i in range(4):
        gate = IntegrityGate(handle, store.blobs(),
                             ExtractionView(panel=PanelFlags((True, True, True))),
                             ocr_conf_floor=0.70)
        gate.verify(run_id, f"SUB-{i:03d}", "C1")
    store.close()


# --- limb 3: exact coverage, total rather than sampled ---------------------------------------


def _assert_total_coverage(verdicts: list[bool], expected: list[bool]) -> None:
    """The coverage oracle: every unit's verdict matches its own expected value.
    A sampled verifier (unit 0's verdict copied forward) fails on the first
    unit whose truth differs."""
    assert len(verdicts) == len(expected), (
        f"{len(verdicts)} verdicts for {len(expected)} units — a unit was not "
        "verified at all, and CT-INTEG-12's coverage is TOTAL"
    )
    mismatches = [(i, got, want) for i, (got, want)
                  in enumerate(zip(verdicts, expected)) if got is not want]
    assert not mismatches, (
        f"per-unit verdicts {mismatches} diverge from per-unit truth — verification "
        "was sampled, cached or extrapolated, and CT-INTEG-12 runs it on EVERY unit"
    )


def test_tc_integ_c12_the_coverage_oracle_has_teeth():
    """`TC-INTEG-C12`'s executable construction — the sampled verifier (unit
    0's verdict for everyone) and the dropped-unit verifier go red. Runs green
    now: it asserts the oracle's teeth, not the implementation."""
    truth = [True] + [False] * 11
    _assert_total_coverage(list(truth), truth)              # faithful
    with pytest.raises(AssertionError, match="sampled, cached or extrapolated"):
        _assert_total_coverage([True] * 12, truth)          # unit 0 copied forward
    with pytest.raises(AssertionError, match="not verified at all"):
        _assert_total_coverage(truth[:11], truth)           # a unit dropped


@pytest.mark.writtenahead
def test_tc_integ_c12_every_unit_is_verified_total_not_sampled(tmp_data_dir):
    """`TC-INTEG-C12` — the coverage limb over the real gate: 12 units, unit 0
    clean, units 1..11 each carrying a UNIQUE invalid span (distinct text, so a
    cached verdict from another unit cannot match). Every unit's verdict must be
    its own — total coverage, exactly counted."""
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#74")
    store = open_store(tmp_data_dir)
    orch, run_id, _version = seed_run(
        store, submissions=tuple(f"SUB-{i:03d}" for i in range(_COVERAGE_UNITS)),
        criteria=({"criterion_id": "C1", "kind": "open",
                   "scoring_model": "holistic"},))
    handle = store.cohort(_COHORT)
    verdicts: list[bool] = []
    try:
        for i in range(_COVERAGE_UNITS):
            submission = f"SUB-{i:03d}"
            markdown = "".join(_sentence(j) for j in range(30))
            seed_document(handle, document_id_for(submission), submission,
                          markdown, _COHORT)
            if i == 0:
                needle = "detail 0"
                start = markdown.encode("utf-8").find(b"detail 0")
                span_text = needle  # valid: the exact slice
            else:
                needle = f"detail {i}"
                start = markdown.encode("utf-8").find(needle.encode("utf-8"))
                span_text = f"detail {i}x"  # unique hallucination per unit
            view = ExtractionView(
                spans=[Span(start, start + len(needle), span_text)],
                panel=PanelFlags((True, True, True)),
            )
            gate = IntegrityGate(handle, store.blobs(), view, ocr_conf_floor=0.70)
            signals = gate.verify(run_id, submission, "C1")
            verdicts.append(signals.spans_verified)
        expected = [i == 0 for i in range(_COVERAGE_UNITS)]
        _assert_total_coverage(verdicts, expected)
    finally:
        store.close()
