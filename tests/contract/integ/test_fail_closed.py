"""`CT-INTEG-03` — fail-closed, without exception (`TC-INTEG-C03`).

Safety property (design §4.7); block form of test plan §6.11.9; TS-66 (issue
#77). Guards RISK-01, RISK-03; `NFR-INTEG-03`, HLD `R19`. Written ahead of
`#74` (the gate and the signals) and `#92` (the `M-AGG` consumer limb).

The clause: an error computing **any** signal yields the **conservative**
value — unverified, absent, insufficient, at-risk — never the permissive one;
a consumer may rely on the **absence** of a signal being adverse; and no error
path returns a partially-computed set that looks complete. The block form
makes it a **sweep over the cross product of signals and failure modes, not a
sample** — "without exception" is the requirement.

The conservative mapping applied to the signals is the one `#75`'s
fault-injection cases reconciled (see `tests/unit/integ/
test_integrity_signals.py`'s interface table), reused here unchanged: a span
read failing is unverified AND absent; a regions read failing is at-risk AND
described; a panel read failing is insufficient; a second-family read failing
is disagreement `True`, **not** `None` (the second extraction ran, so "not
measured" is contractually wrong); a citation-requirement read failing
resolves to the routing candidate (treated as requiring — the adverse reading
of an unknown), asserted as a routing request, not a signal value.

**Disclosures register**:

| Name | Status |
|---|---|
| `IntegrityGate` / `IntegritySignals` / `ExtractionView` | the #75 keys, reused — `ExtractionView`'s five reads are the injection points, one per signal-computation input |
| `aeh.agg.aggregate`, `aeh.agg.AGG_AUTO_THRESHOLD_ATOMIC` | §3.12-declared; the step-2 consumer limb lands with `#92` |
| citation-requirement read's conservative value | the design's four conservative words do not name a fifth read; `True` (treat as requiring) is the disclosed adverse reading, asserted through the routing it produces rather than a signal value |
| failure-mode vocabulary | exception (three exception types), missing input (`None`), unexpected type (non-iterable), malformed input (a string where the read's tuple belongs) — the block form's modes mapped onto what a view read can actually return |
| `second-family x return-none` | **not a failure cell**, disclosed: `None` is the second-family read's declared "no second extraction ran" value (CT-INTEG-02), so it is not an error — the sweep excludes it and TC-INTEG-06's own case pins the None state it produces |

**The adversarial construction** ("wrap signal computation in try/except
returning the previous run's cached values, to avoid spurious routing when the
store hiccups") is executable twice over: the oracle checker rejects the
caching mutant's stale set on record-shaped data now (green, teeth), and
against the real gate with a faulted second run (writtenahead) — where the
mutant's routing volume DROPS, which looks like an improvement, and the
failure mode is that a broken integrity check reads as clean evidence. That
is RISK-01's enabling condition, and it is why the regression
(`REG-CT-INTEG-03`) is permanent.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from aeh.store import open_store
from tests.contract.integ._doubles import (
    CONTRACT_COHORT,
    Criterion,
    byte_span,
    make_gate,
    unanimous_panel,
)
from tests.support.impl import AGG_MODULE, INTEG_MODULE, require
from tests.support.integ_vocabulary import (
    CitedRegion,
    Doc,
    ExtractionView,
    PanelFlags,
    seed_document,
    document_id_for,
)

pytestmark = pytest.mark.contract

_MARKDOWN = "The mitochondrion is the powerhouse of the cell.\nA figure follows.\n"
_RUN = "run-integ-c03"
_SUBMISSION = "SUB-C03"


# --- the conservative oracle ---------------------------------------------------------------
#
# Per faulted read: the EXACT conservative values its signals must take (the
# block form's oracle is "exact conservative value per (signal x failure mode)
# cell"). Unfaulted reads are asserted to stay computed-honest in step 3.


def _conservative(faulted_read: str) -> dict[str, object]:
    table: dict[str, dict[str, object]] = {
        "spans": {"spans_verified": False, "evidence_present": False},
        "second-family": {"extractor_disagreement": True},
        "regions": {"ocr_overlap_risk": True, "described_evidence": True},
        "panel": {"sufficiency_flag": True},
        # The citation read's adverse reading: treated as requiring. Asserted as a
        # routing request in its cell, not as a signal value (see disclosures).
        "citation": {},
    }
    return table[faulted_read]


class _NotFaulted:
    """Sentinel: this read was not the faulted one."""


class _FaultView(ExtractionView):
    """A view where one named read performs one named failure — the sweep's
    injection point (one fault per run, so a cell's values are attributable)."""

    def __init__(self, read: str, mode: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._read = read
        self._mode = mode

    def _fault(self, read: str):
        if read != self._read:
            return _NotFaulted
        if self._mode == "raise-runtime":
            raise RuntimeError("injected: the read died")
        if self._mode == "raise-timeout":
            raise TimeoutError("injected: the read timed out")
        if self._mode == "raise-value":
            raise ValueError("injected: the read refused its input")
        if self._mode == "return-none":
            return None  # missing input
        if self._mode == "return-wrong-type":
            return 42  # unexpected type
        if self._mode == "return-malformed":
            return "malformed"  # a string where the read's tuple belongs
        raise AssertionError(f"unknown mode {self._mode}")

    def _maybe(self, read: str, fallback, *args):
        result = self._fault(read)
        return result if result is not _NotFaulted else fallback(*args)

    def spans(self, submission_id, criterion_id):
        return self._maybe("spans", super().spans, (submission_id, criterion_id))

    def second_family_spans(self, submission_id, criterion_id):
        return self._maybe("second-family", super().second_family_spans,
                           (submission_id, criterion_id))

    def regions(self, document_id):
        return self._maybe("regions", super().regions, (document_id,))

    def panel_sufficiency(self, submission_id, criterion_id):
        return self._maybe("panel", super().panel_sufficiency,
                           (submission_id, criterion_id))

    def criterion_requires_citation(self, criterion_id):
        return self._maybe("citation", super().criterion_requires_citation, (criterion_id,))


_FAULT_MODES = (
    "raise-runtime", "raise-timeout", "raise-value",
    "return-none", "return-wrong-type", "return-malformed",
)
_SIGNAL_READS = ("spans", "second-family", "regions", "panel")
#: The cross product, minus the one cell that is not a failure (disclosures).
CELLS = [(read, mode) for read in _SIGNAL_READS for mode in _FAULT_MODES
         if (read, mode) != ("second-family", "return-none")]


def _seeded_store(tmp_data_dir) -> None:
    store = open_store(tmp_data_dir)
    seed_document(store.cohort(CONTRACT_COHORT), document_id_for(_SUBMISSION),
                  _SUBMISSION, _MARKDOWN, CONTRACT_COHORT)
    store.close()


def _healthy_view_kwargs() -> dict:
    span = byte_span(_MARKDOWN, "mitochondrion")
    return dict(
        spans=(span,),
        second_family_spans=(span,),
        regions=(CitedRegion("r-ok", "transcribed_text", span.start, span.end,
                             ocr_conf=0.95),),
        panel=PanelFlags((True, True, True)),
    )


# --- step 1: the exhaustive cross product ---------------------------------------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize("read, mode", CELLS, ids=[f"{r}-{m}" for r, m in CELLS])
def test_tc_integ_c03_every_signal_times_every_failure_mode_resolves_conservative(
        tmp_data_dir, read, mode):
    """`TC-INTEG-C03` step 1 — the cross product the block form demands: four
    signal-feeding reads x six failure modes (23 cells), each asserting the
    EXACT conservative value the faulted computation must produce, never the
    permissive one (NFR-INTEG-03). A sample would not honor 'without
    exception'; the citation read's cell is the routing case below."""
    _seeded_store(tmp_data_dir)
    gate, store = make_gate(tmp_data_dir, _FaultView(read, mode, **_healthy_view_kwargs()))
    signals = gate.verify(_RUN, _SUBMISSION, "C1")
    for name, value in _conservative(read).items():
        actual = getattr(signals, name)
        assert actual is value, (
            f"({read} x {mode}): {name} read {actual!r} — the conservative value is "
            f"{value!r} (CT-INTEG-03: an error computing a signal yields unverified, "
            "absent, insufficient or at-risk, never the permissive one)"
        )
    store.close()


@pytest.mark.writtenahead
def test_tc_integ_c03_the_citation_read_failing_resolves_to_the_routing_candidate(
        tmp_data_dir):
    """`TC-INTEG-C03` step 1's fifth read — the citation-requirement read
    failing resolves to the adverse reading (treated as requiring), which for
    empty evidence is observable as a routing request: the unit re-extracts
    instead of scoring on evidence whose citation obligation could not be
    established."""
    _seeded_store(tmp_data_dir)
    view = _FaultView("citation", "raise-runtime",
                      spans=(), panel=PanelFlags((True, True, True)),
                      evidence_type_requires_citation=True)
    gate, store = make_gate(tmp_data_dir, view)
    signals = gate.verify(_RUN, _SUBMISSION, "C1")
    assert signals.evidence_present is False
    routed = store.cohort(CONTRACT_COHORT).query(
        "SELECT work_id, status, attempts FROM work_unit WHERE submission_id = :s "
        "AND criterion_id = :c AND stage = 'extract' AND attempts >= 1 "
        "AND status IN ('pending', 'leased')",
        s=_SUBMISSION, c="C1")
    assert routed, (
        "the citation read failed and empty evidence did not route — an unknown "
        "citation obligation resolved permissive (the disclosed adverse reading is "
        "treat-as-requiring, and its observable is this routing request)"
    )
    store.close()


# --- step 3: no partially-computed set that looks complete -----------------------------------


@pytest.mark.writtenahead
def test_tc_integ_c03_an_all_faults_run_is_fully_conservative(tmp_data_dir):
    """`TC-INTEG-C03` step 3 — every read faulting at once: all six signals
    land on their conservative values simultaneously. A mix — one faulted
    signal conservative, another silently permissive — is the
    'partially-computed set that looks complete' the block form forbids."""

    class _AllFault(_FaultView):
        def _fault(self, read: str):
            self._read = read  # every read is the faulted one
            return super()._fault(read)

    _seeded_store(tmp_data_dir)
    gate, store = make_gate(tmp_data_dir, _AllFault("spans", "raise-runtime"))
    signals = gate.verify(_RUN, _SUBMISSION, "C1")
    assert (signals.spans_verified, signals.evidence_present) == (False, False)
    assert signals.sufficiency_flag is True
    assert (signals.ocr_overlap_risk, signals.described_evidence) == (True, True)
    assert signals.extractor_disagreement is True, (
        "the second-family read faulted, so 'not measured' (None) is contractually "
        "wrong — the second extraction ran and its outcome could not be established; "
        "None would be consumed by M-AGG as agreement (CT-INTEG-02's distinction)"
    )
    store.close()


@pytest.mark.writtenahead
def test_tc_integ_c03_a_single_fault_leaves_the_rest_of_the_set_computed_honest(
        tmp_data_dir):
    """`TC-INTEG-C03` step 3's other half — with only the panel read faulting,
    the successfully computed signals keep their COMPUTED values: the set is
    honest about which half failed. A gate that 'recovered' by defaulting the
    unfaulted signals to conservative would be failing closed twice; a gate
    that let the fault leak permissive defaults anywhere fails here."""
    _seeded_store(tmp_data_dir)
    gate, store = make_gate(tmp_data_dir,
                            _FaultView("panel", "raise-timeout", **_healthy_view_kwargs()))
    signals = gate.verify(_RUN, _SUBMISSION, "C1")
    assert (signals.spans_verified, signals.evidence_present) == (True, True), (
        "the span computation succeeded and its result was overwritten — the set is "
        "no longer honest about which half failed"
    )
    assert (signals.ocr_overlap_risk, signals.described_evidence) == (False, False)
    assert signals.extractor_disagreement is False  # second family agreed: computed
    assert signals.sufficiency_flag is True  # the faulted read: conservative
    store.close()


# --- step 2: the absence of a signal is adverse (rung 3, M-AGG) ------------------------------
#
# The checker is the oracle; the record-shaped arm runs now so the teeth are
# provable before #92 lands.


def _assert_dropped_signal_is_adverse(outcome, auto_threshold: float) -> None:
    """The consumer oracle for a dropped signal: capped below auto-accept, never
    routed out the door — unknown-therefore-fine is the forbidden reading."""
    confidence = getattr(outcome, "confidence", outcome)
    routing = getattr(outcome, "routing", None)
    assert confidence < auto_threshold, (
        f"confidence {confidence} reached the auto-accept threshold with an "
        "integrity signal missing — absence read as fine, the unknown-therefore-fine "
        "reading CT-INTEG-03 forbids"
    )
    if routing is not None:
        assert routing != "auto", (
            "the missing-signal item routed auto — absence must be adverse all the "
            "way to the routing decision"
        )


def test_tc_integ_c03_the_unknown_therefore_fine_mutant_turns_this_oracle_red():
    """`TC-INTEG-C03` step 2's executable construction — a consumer that reads
    a missing signal as neutral scores the dropped-signal case at full
    confidence; the oracle reds on it. Green now: record-shaped, no
    implementation."""
    threshold = 0.85
    _assert_dropped_signal_is_adverse(
        SimpleNamespace(confidence=0.5, routing="review"), threshold)
    with pytest.raises(AssertionError, match="unknown-therefore-fine"):
        _assert_dropped_signal_is_adverse(
            SimpleNamespace(confidence=0.9, routing="auto"), threshold)


@pytest.mark.writtenahead
@pytest.mark.parametrize("dropped", [
    "spans_verified", "evidence_present", "sufficiency_flag",
    "ocr_overlap_risk", "described_evidence", "extractor_disagreement",
])
def test_tc_integ_c03_m_agg_reads_a_dropped_signal_as_adverse(tmp_data_dir, dropped):
    """`TC-INTEG-C03` step 2 — each signal dropped ENTIRELY from the set
    `M-AGG` reads: the verdict is capped below auto-accept and never routed
    auto. A consumer may rely on the absence of a signal being adverse — that
    reliance is only worth what this differential says it is."""
    aggregate, auto_threshold = require(
        AGG_MODULE, "aggregate", "AGG_AUTO_THRESHOLD_ATOMIC", issue="#92")
    full = dict(
        spans_verified=True, evidence_present=True, sufficiency_flag=False,
        ocr_overlap_risk=False, described_evidence=False, extractor_disagreement=False,
    )
    del full[dropped]
    incomplete = SimpleNamespace(**full)  # the signal is absent, not False
    outcome = aggregate(unanimous_panel("B2"), Criterion("C1"), incomplete)
    _assert_dropped_signal_is_adverse(outcome, auto_threshold)


# --- the adversarial construction: cached values on failure ---------------------------------


def _assert_signal_set_is_conservative(signals, faulted_read: str) -> None:
    """The step-1 oracle as a reusable checker: for a run whose named read
    faulted, every signal the read feeds must hold its conservative value."""
    for name, value in _conservative(faulted_read).items():
        actual = getattr(signals, name)
        assert actual is value, (
            f"a faulted {faulted_read} read left {name}={actual!r} — the conservative "
            f"value is {value!r} (CT-INTEG-03)"
        )


class _CachingGate:
    """The adversarial construction: a gate-shaped wrapper whose try/except
    serves the previous run's signals 'to avoid spurious routing when the store
    hiccups'. Run 1 caches a clean set; run 2 faults and is served the stale
    clean set — routing volume drops, which looks like an improvement, and a
    broken integrity check now reads as clean evidence (RISK-01's enabling
    condition)."""

    def __init__(self, gate) -> None:
        self._gate = gate
        self._cache = None

    def verify(self, run_id, submission_id, criterion_id):
        try:
            signals = self._gate.verify(run_id, submission_id, criterion_id)
        except Exception:  # noqa: BLE001 - the mutant's whole point
            return self._cache
        self._cache = signals
        return signals


def test_tc_integ_c03_the_cached_values_mutant_turns_this_oracle_red():
    """`TC-INTEG-C03`'s named construction, executable on record-shaped data:
    run 2's faulted read is served run 1's clean set, the step-1 checker reds
    on it — while the FR-style observation (routing volume dropped, nothing
    crashed) sees an improvement. Green now: the teeth do not need the gate."""
    clean = SimpleNamespace(
        spans_verified=True, evidence_present=True, sufficiency_flag=False,
        ocr_overlap_risk=False, described_evidence=False, extractor_disagreement=False,
    )
    mutant = _CachingGate(None)
    mutant._cache = clean
    stale = mutant.verify("r2", "s", "C1")  # the wrapped gate faults; cache served
    assert stale is clean, "premise: the mutant served the previous run's set"
    with pytest.raises(AssertionError, match="conservative"):
        _assert_signal_set_is_conservative(stale, "regions")


@pytest.mark.writtenahead
def test_tc_integ_c03_the_cached_values_mutant_turns_the_real_gate_red(tmp_data_dir):
    """`TC-INTEG-C03`'s construction against the real gate: run 1 healthy (its
    clean set cached), run 2 over a gate whose regions read faults — the
    mutant serves the stale set, the oracle reds on exactly that set, and the
    honest gate on the same fault returns the conservative one. The FR-style
    cases stay green on the mutant (its healthy run is indistinguishable from
    the honest one); only the faulted read separates them, which is why this
    regression is permanent (REG-CT-INTEG-03)."""
    _seeded_store(tmp_data_dir)

    class _FaultingRegionsGate:
        """The real gate, with the regions read faulting on every call."""

        def verify(self, run_id, submission_id, criterion_id):
            faulted = _FaultView("regions", "raise-runtime", **_healthy_view_kwargs())
            gate, _ = make_gate(tmp_data_dir, faulted)
            return gate.verify(run_id, submission_id, criterion_id)

    # The honest gate on the same fault: conservative, not stale.
    honest = _FaultingRegionsGate().verify(_RUN, _SUBMISSION, "C1")
    _assert_signal_set_is_conservative(honest, "regions")

    # Run 1 through the mutant: healthy, cached.
    healthy_gate, _ = make_gate(tmp_data_dir, ExtractionView(**_healthy_view_kwargs()))
    mutant = _CachingGate(healthy_gate)
    first = mutant.verify(_RUN, _SUBMISSION, "C1")
    assert first.ocr_overlap_risk is False

    # Run 2 through the mutant over the faulting gate: stale set served.
    stale_mutant = _CachingGate(_FaultingRegionsGate())
    stale_mutant._cache = first
    stale = stale_mutant.verify(_RUN + "-2", _SUBMISSION, "C1")
    assert stale is first, "premise: the mutant served run 1's cached set"
    with pytest.raises(AssertionError, match="conservative"):
        _assert_signal_set_is_conservative(stale, "regions")
