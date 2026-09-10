"""`CT-INTEG-13` — `INTEG_OCR_CONF_FLOOR` (Assumption: 0.70) and
`INTEG_DESCRIBED_EVIDENCE_ROUTES` (default true) change **externally-visible
routing volume**; the floor is **per-transcriber and unvalidated**, and a
consumer must not treat the current value as calibrated (`TC-INTEG-C13`).

Case of test plan §6.11.9 (config); TS-66 (issue #77). Written ahead of `#74`.

A knob that changes nothing observable is either dead or mis-wired, so each
knob is moved through its environment variable and the ROUTING VOLUME —
review-queue rows, the gate's externally visible routing surface — must move
with it. The floor's honesty half is carried three ways: the value is read
from configuration (moving the env moves the behavior — a hard-coded floor
fails the differential), the no-env default is bracketed around the declared
0.70 (a region at 0.75 is clean, a region at 0.65 is at risk, under the
default), and the case itself never asserts that 0.70 is CORRECT — the clause
records the value as per-transcriber and unvalidated, and this file's
disclosures repeat that no consumer may treat it as calibrated.

**Disclosures register** (nothing new is minted beyond the #75 table):

| Name | Status |
|---|---|
| knob transport | environment variables (seam rule 3), read by the gate's DEFAULT path — the scenario constructs the gate WITHOUT the `ocr_conf_floor` parameter so the configuration path is what the differential exercises; a `#74` that only honors the constructor parameter fails the differential and forces the reconcile |
| routing volume | the count of `review_queue` rows for the run — the gate's externally visible routing surface. The clause says the FLOOR's movement shows up in routing volume; if `#74` expresses the OCR-risk consequence only through `M-AGG`'s cap, this case reds and the landing reconciles — the clause's sentence is what the case holds |
| floor default bracket | the no-env default is pinned by bracket (0.65 flagged, 0.75 clean) rather than exact equality: the Assumption's value is 0.70, and the bracket pins it without asserting a calibration the clause explicitly disclaims |
| per-transcriber | the floor's per-transcriber dimension is `#74`'s configuration plumbing (this suite's fixtures carry a single transcriber); the case pins the configuration-read and the default, and discloses the dimension |
| unvalidated | deliberately untested: no assertion here says 0.70 is the RIGHT floor — §7.4 records that no consumer may treat the current value as calibrated, and this file repeats it |
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.contract.integ._doubles import byte_span
from tests.support.impl import INTEG_MODULE, require
from tests.support.integ_vocabulary import (
    CitedRegion,
    ExtractionView,
    PanelFlags,
    document_id_for,
    seed_document,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.contract

_FLOOR_ENV = "INTEG_OCR_CONF_FLOOR"
_DESCRIBED_ENV = "INTEG_DESCRIBED_EVIDENCE_ROUTES"
_MARKDOWN = "The student argues the thesis directly in the opening paragraph.\n"
_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},)


# --- the oracle and its teeth ---------------------------------------------------------------


def _assert_knob_moves_routing_volume(volume_before, volume_after) -> None:
    """The config oracle: moving the knob moved the externally-visible routing
    volume — the same number before and after is a dead or mis-wired knob."""
    assert volume_before != volume_after, (
        f"routing volume stayed at {volume_before} after moving the knob — a knob "
        "that changes nothing observable is either dead or mis-wired (CT-INTEG-13)"
    )


def test_tc_integ_c13_the_knob_oracle_has_teeth():
    """`TC-INTEG-C13`'s executable construction — the dead-knob mutant (env
    moved, volume unchanged) goes red. Runs green now: it asserts the oracle's
    teeth, not the implementation."""
    _assert_knob_moves_routing_volume(0, 2)      # a wired knob
    with pytest.raises(AssertionError, match="dead or mis-wired"):
        _assert_knob_moves_routing_volume(2, 2)  # the dead knob


# --- the harness -----------------------------------------------------------------------------


def _region(conf: float) -> CitedRegion:
    span = byte_span(_MARKDOWN, "thesis")
    return CitedRegion(region_id="r-c13", region_kind="transcribed_text",
                       start=span.start, end=span.end, ocr_conf=conf,
                       crop_ref=None, content_state="present")


def _described_region() -> CitedRegion:
    span = byte_span(_MARKDOWN, "thesis")
    return CitedRegion(region_id="r-c13-described", region_kind="described_graphic",
                       start=span.start, end=span.end, ocr_conf=None,
                       crop_ref=None, content_state="present")


def _volume(tmp_data_dir, regions, monkeypatch, env: dict[str, str] | None) -> int:
    """One gate built on the DEFAULT configuration path (no injected floor),
    under `env`, over the given regions — returns the run's review-queue rows."""
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    for key in (_FLOOR_ENV, _DESCRIBED_ENV):
        if not (env or {}).get(key):
            monkeypatch.delenv(key, raising=False)
    store = open_store(tmp_data_dir)
    orch, run_id, _version = seed_run(store, submissions=("SUB-C13",),
                                      criteria=_CRITERIA)
    handle = store.cohort(ORCH_COHORT_ID)
    seed_document(handle, document_id_for("SUB-C13"), "SUB-C13", _MARKDOWN,
                  ORCH_COHORT_ID)
    orch.enumerate_units(run_id)
    view = ExtractionView(spans=(byte_span(_MARKDOWN, "thesis"),),
                          regions=regions, panel=PanelFlags((True, True, True)))
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#74")
    gate = IntegrityGate(handle, store.blobs(), view)  # the DEFAULT config path
    gate.verify(run_id, "SUB-C13", "C1")
    # The gate was built on the ORCH cohort's handle — that is the SQLite file
    # its review_queue writes land in; reading another cohort's file reads a
    # different database and always counts zero.
    rows = store.cohort(ORCH_COHORT_ID).query(
        "SELECT COUNT(*) AS n FROM review_queue WHERE submission_id = :s",
        s="SUB-C13",
    )
    store.close()
    return rows[0]["n"]


# --- the floor: moving it moves routing volume; the default is the Assumption ----------------


def test_tc_integ_c13_moving_the_ocr_floor_moves_routing_volume(tmp_data_dir,
                                                                monkeypatch):
    """`TC-INTEG-C13` — the floor differential: a region at confidence 0.75
    under the default floor (0.70) leaves the criterion clean; the SAME region
    with `INTEG_OCR_CONF_FLOOR=0.80` is at risk and the criterion routes. The
    env — not a hard-coded constant — decided the outcome."""
    regions = (_region(0.75),)
    before = _volume(tmp_data_dir / "default", regions, monkeypatch, None)
    after = _volume(tmp_data_dir / "raised", regions, monkeypatch,
                    {_FLOOR_ENV: "0.80"})
    _assert_knob_moves_routing_volume(before, after)


def test_tc_integ_c13_the_floor_is_read_from_configuration_not_hard_coded(
        tmp_data_dir, monkeypatch):
    """`TC-INTEG-C13` — the honesty half: with NO env set, the default floor
    brackets the declared Assumption — a 0.65 region is at risk, a 0.75 region
    is clean — and setting the env to 0.50 releases the 0.65 region too. The
    value is configuration, not a constant: the same fixtures answer
    differently under a moved knob, and the no-env default sits where §3.9
    declares it."""
    low = (_region(0.65),)
    clean = (_region(0.75),)
    low_volume = _volume(tmp_data_dir / "low-default", low, monkeypatch, None)
    clean_volume = _volume(tmp_data_dir / "clean-default", clean, monkeypatch, None)
    assert low_volume > clean_volume, (
        "under the no-env default, a 0.65-confidence cited region did not route "
        "while a 0.75 one did — the default floor is not the declared 0.70 bracket"
    )
    released = _volume(tmp_data_dir / "released", low, monkeypatch,
                       {_FLOOR_ENV: "0.50"})
    assert released < low_volume, (
        "moving INTEG_OCR_CONF_FLOOR to 0.50 left the 0.65 region's routing in place "
        "— the floor is hard-coded, not read from configuration"
    )


# --- the described-evidence switch ------------------------------------------------------------


def test_tc_integ_c13_turning_described_evidence_routing_off_moves_volume(
        tmp_data_dir, monkeypatch):
    """`TC-INTEG-C13` — the switch differential: evidence wholly within a
    described region routes by default (`INTEG_DESCRIBED_EVIDENCE_ROUTES`
    default true); with the env set false, the same otherwise-perfect evidence
    no longer routes. The switch is wired to something observable."""
    regions = (_described_region(),)
    before = _volume(tmp_data_dir / "routes-on", regions, monkeypatch, None)
    after = _volume(tmp_data_dir / "routes-off", regions, monkeypatch,
                    {_DESCRIBED_ENV: "false"})
    _assert_knob_moves_routing_volume(before, after)
    assert before >= 1, (
        "described evidence did not route even with the switch at its default — the "
        "baseline the differential needs is missing (CT-INTEG-10's routing half)"
    )
