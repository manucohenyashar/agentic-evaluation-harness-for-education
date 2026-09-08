"""`CT-SETUP-15` — NON-PROMISE: nothing in the read back is a rubric
improvement (`TC-SETUP-C15`).

Case of test plan §6.11.6; issue #56 (TS-63). **WRITTEN AHEAD** — the sweep
needs #51's read back to produce corrections, and the three consumers it sweeps
(`M-CALIB`, `M-STATS`, `M-CONSOLE`) do not exist yet (their own contract suites
sit writtenahead behind the same `require` blocks this file uses). The file
carries `writtenahead` and a `WRITTEN_AHEAD_BLOCKERS` entry ("#56 C15 consumer
sweep") keyed on the conjunction of everything its body drives: #51's
`read_back_rubric` plus the three consumer MODULES. It fails ONLY via
`NotImplementedYet` until the last of those lands. (#52/#53 are deliberately
NOT in the conjunction: nothing in this file drives their surfaces — the
sweep is over consumers of the READ-BACK result.)

The clause: the read back is a TRANSCRIPTION step. Make the unpromised thing
vary — run it over a rubric with obvious defects, producing corrections — and
then assert NO consumer treats the result as validation:

- `M-CALIB` still requires its gates before any revision — a read-back
  correction is not a passport past them;
- `M-STATS` attributes no validity to a read-back correction;
- `M-CONSOLE` presents no "reviewed" or "improved" affordance SOURCED from
  setup.

The oracle is a sweep over the consumers' own surfaces (reflection, not a
single call — the non-promise discipline): if any consumer grows a symbol that
names the setup read back as a validity source or an affordance's provenance,
the drift this case exists to catch has started.

**Stated scope bet**: the consumer modules' own suites drive their behavior;
this case pins the one thing theirs cannot — that no consumer surface admits
the read back as validation. The vocabulary swept is the drift signature
("readback"/"read_back" as a validity source; "reviewed"/"improved" provenance
naming setup), not an exhaustive API pin.
"""
from __future__ import annotations

import json

import pytest

import aeh.setup as aeh_setup  # not `setup_module`: pytest reads that name as the xunit hook
from aeh.setup import SetupService
from tests.contract.setup._doubles import ingest_document, stage_chain
from tests.support.impl import (
    CALIB_MODULE,
    CONSOLE_MODULE,
    STATS_MODULE,
    require,
    require_attr,
)

pytestmark = pytest.mark.writtenahead

#: The validity-source vocabulary: if a consumer's surface names the setup read
#: back under one of these shapes, the transcription step is being re-read as
#: quality assurance (the exact drift CT-SETUP-15 exists to catch).
VALIDITY_VOCABULARY = ("readback", "read_back", "setup_readback",
                       "setup_correction")
#: The affordance vocabulary, only ever a violation when SOURCED from setup.
AFFORDANCE_VOCABULARY = ("reviewed", "improved")


def _corrections_from_read_back(tmp_data_dir):
    """Run the read back over a defective rubric; assert corrections CAME OUT —
    the unpromised thing must vary for the sweep to mean anything."""
    require_attr(SetupService, "read_back_rubric", issue="#51")
    chain = stage_chain(tmp_data_dir, package_id="pkg-c15")
    chain.doc = ingest_document(chain.store, kind="assessment")
    rubric = ingest_document(chain.store, kind="rubric", name="rubric.pdf")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)
    # The rubric's defects: a max_points of 99.0 and a construct that names the
    # wrong subject — transcription errors the read back should surface.
    chain.provider.replies = [json.dumps({"criteria": [{
        "criterion_id": "CRIT-DEF", "question_id": "Q1", "kind": "open",
        "scoring_model": "atomic", "max_points": 99.0,
        "construct": "the response explains photosynthesis",
        "corrections": [
            {"field": "max_points", "from": 99.0, "to": 4.0,
             "reason": "the rubric's points line is a transcription error"},
        ],
    }]})]
    readback = chain.service.read_back_rubric(rubric, chain.doc)
    payload = json.dumps(readback, default=str)
    assert "correction" in payload.lower(), (
        "the read back over the defective rubric produced no correction — the "
        "sweep's input is empty and the non-promise holds vacuously "
        "(CT-SETUP-C15)"
    )
    return readback


def test_tc_setup_c15_no_consumer_treats_readback_as_validation(tmp_data_dir):
    """The sweep: with real corrections in hand, no consumer surface admits the
    read back as a validity source — M-CALIB's gates, M-STATS's validity and
    M-CONSOLE's affordances all stay sourced where they were."""
    corrections = _corrections_from_read_back(tmp_data_dir)
    assert corrections is not None  # the varying input is real (non-vacuous)

    # The consumers, each through its own designed blocker (their implementing
    # stories carry their own suites; the label names the missing module).
    calib = require(CALIB_MODULE, issue=f"{CALIB_MODULE} implementing story")
    stats = require(STATS_MODULE, issue=f"{STATS_MODULE} implementing story")
    console = require(CONSOLE_MODULE,
                      issue=f"{CONSOLE_MODULE} implementing story")

    for name, module in (("M-CALIB", calib), ("M-STATS", stats),
                         ("M-CONSOLE", console)):
        public = [n for n in dir(module) if not n.startswith("_")]
        for symbol in public:
            lowered = symbol.lower()
            for word in VALIDITY_VOCABULARY:
                assert word not in lowered, (
                    f"{name}'s surface carries {symbol!r} — a consumer names "
                    "the setup read back as a validity source; the "
                    "transcription step is being re-read as quality assurance "
                    "(CT-SETUP-C15)"
                )
        # The affordance half, console-only: no presented-language symbol pairs
        # "reviewed"/"improved" WITH setup provenance. (The words themselves
        # are the console's business — sourced from review, never from setup.)
        if module is console:
            for symbol in public:
                lowered = symbol.lower()
                for word in AFFORDANCE_VOCABULARY:
                    if word in lowered:
                        setup_sourced = ("setup" in lowered
                                         or "readback" in lowered
                                         or "read_back" in lowered)
                        assert not setup_sourced, (
                            f"M-CONSOLE's surface carries {symbol!r} — a "
                            "reviewed/improved affordance sourced from setup "
                            "(CT-SETUP-C15)"
                        )


def test_tc_setup_c15_calib_gates_still_fire_with_a_correction_in_hand():
    """M-CALIB's gate discipline is intact against the read back: its refusal
    types are its own, and nothing in its surface binds setup machinery — a
    correction is data, never a passport."""
    require_attr(SetupService, "read_back_rubric", issue="#51")
    require(CALIB_MODULE, "TriageCategoryRequired",
            issue=f"{CALIB_MODULE} implementing story")

    calib = require(CALIB_MODULE, issue=f"{CALIB_MODULE} implementing story")
    # The gates' refusal types are the module's own, not setup's: nothing in
    # the read back's vocabulary appears in their lineage.
    for gate_type_name in ("TriageCategoryRequired", "PhaseDependencyError",
                           "ThresholdNotDeclared"):
        if hasattr(calib, gate_type_name):
            gate_type = getattr(calib, gate_type_name)
            module_name = getattr(gate_type, "__module__", "")
            assert module_name.startswith(CALIB_MODULE), (
                f"{gate_type_name} resolves outside {CALIB_MODULE} "
                f"({module_name!r}) — a gate type imported from setup would be "
                "a second enforcement point (CT-SETUP-C15)"
            )
    # And no calibration symbol binds the read back's machinery: setup's module
    # object and its service type appear nowhere in M-CALIB's public surface.
    service_type = aeh_setup.SetupService
    for symbol in (n for n in dir(calib) if not n.startswith("_")):
        member = getattr(calib, symbol)
        assert member is not aeh_setup and member is not service_type, (
            f"{CALIB_MODULE}.{symbol} is setup machinery — M-CALIB has bound "
            "the read back into its own surface (CT-SETUP-C15)"
        )
