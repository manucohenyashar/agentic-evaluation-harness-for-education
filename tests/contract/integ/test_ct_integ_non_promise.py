"""`CT-INTEG-15` — **not promised:** the integrity signals do not certify that
evidence is *right*, only that it is present, verifiable against source bytes,
and not drawn from material the system has flagged as uncertain;
`spans_verified = true` means the quoted text exists in the document, nothing
more (`TC-INTEG-C15`).

Case of test plan §6.11.9; TS-66 (issue #77). Written ahead of `#74` (the
gate) and `#92` (the consumer).

The clause is the boundary between "checked" and "correct", and the case holds
it in the adversarial direction — evidence that is verified, present, not
at-risk, and **irrelevant**:

1. **The premise, through the real gate** — the document contains the quoted
   text, so verification passes, and the signal set is *relevance-blind*:
   every integrity field reads the same for the relevant sentence and the
   irrelevant one. Nothing in the six signals promised to see relevance, and
   `spans_verified` MUST read True on the irrelevant fixture — that is the
   field's declared meaning, not a licence to be clever.
2. **The consumer half (`M-AGG`, rung 3)** — the same perfect signal set over
   the same irrelevant evidence, fed to `aggregate` twice with panels that
   differ only in agreement: the split panel must NOT auto-accept (perfect
   signals cannot supply the agreement the confidence rides on — the signal
   set is not a correctness claim), and the unanimous panel must (the designed
   path, so the discriminator is not vacuous). Auto-accept follows the panel,
   never the signals.

**Disclosures register** (nothing new is minted beyond the #75 table):

| Name | Status |
|---|---|
| relevance-blindness form | asserted as a differential (irrelevant ≡ relevant on every integrity field) with `spans_verified` additionally pinned True — the clause's own sentence is about that field; a `#74` that reads False on present text breaks the field's declared meaning rather than exceeding the promise |
| the split panel | three judges on B0/B2/B3 — all distinct, maximal ordinal spread, the weakest agreement a panel can carry. The design's confidence base for a 3-judge panel is the panel's ordinal agreement, so the split panel's confidence is below the atomic threshold for ANY design-faithful implementation; a perfect-signal bonus or substitution is the mutant this limb kills |
| the clean set | constructed all-measured signals (C03's complete shape), so the consumer limbs are orthogonal to C02's not-measured handling and C11's conservative-default timing — the gate-real premise stays in limb 1 |
| `M-CONSOLE` half | DEFERRED — see the trailing block at the end of this file |

**The `M-CONSOLE` presentation half — deferred to the console suite.** The
clause's second consumer must "present the signals with their actual meaning
rather than as a validity badge". That assertion needs the console's
presentation surface, which is `#122`'s (`aeh.console:build_console`) and the
console contract suite's vocabulary — asserting it from here would invent the
console's screen shape wholesale, the exact double-ownership CLAUDE.md's
pipeline table forbids. The `M-AGG` limbs below hold the load-bearing half
(the consumer the confidence math runs through, and RISK-01's boundary); when
the console stories land, the presentation case belongs in
`tests/contract/console/` against the built screens, reading this file's
fixture (verified-but-irrelevant evidence and its clean signal set) as the
scenario.
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.contract.integ._doubles import Criterion, ConsumerVerdict, byte_span
from tests.support.impl import AGG_MODULE, INTEG_MODULE, require
from tests.support.integ_vocabulary import (
    ExtractionView,
    PanelFlags,
    document_id_for,
    seed_document,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.contract

_SUBMISSION = "SUB-C15"
_CRITERION_ID = "C1"
_MARKDOWN = (
    "The thesis is defended with two studies.\n"
    "The weather was rainy during the experiment.\n"
)
_RELEVANT = "defended with two studies"
_IRRELEVANT = "The weather was rainy during the experiment"


# --- the oracles and their teeth -------------------------------------------------------------


def _assert_signals_are_relevance_blind(irrelevant, relevant) -> None:
    """The non-promise oracle, premise half: the integrity set is the same for
    relevant and irrelevant evidence — and `spans_verified` is True on the
    irrelevant fixture, because the quoted text EXISTS. That is the field's
    whole promise, and nothing more may ride on it."""
    assert relevant.spans_verified is True, (
        "the relevant fixture's exact slice did not verify — the fixture itself is "
        "broken and the differential below would be vacuous"
    )
    for name in ("spans_verified", "evidence_present", "ocr_overlap_risk",
                 "described_evidence"):
        got = getattr(irrelevant, name)
        assert got == getattr(relevant, name), (
            f"{name} reads {got!r} on irrelevant evidence against "
            f"{getattr(relevant, name)!r} on relevant evidence — the signal set "
            "claims to see relevance, which CT-INTEG-15 explicitly does not promise "
            "and must not pretend to"
        )
    assert irrelevant.extractor_disagreement is not True, (
        "irrelevant evidence was flagged as extractor disagreement — a relevance "
        "judgment smuggled into a signal whose declared meaning is citation agreement"
    )


def _assert_clean_signals_supply_no_confidence(split, unanimous, threshold) -> None:
    """The non-promise oracle, consumer half: the same perfect signal set, the
    same irrelevant evidence — only the panel's agreement differs. Auto-accept
    follows the panel, never the signals."""
    split_conf = getattr(split, "confidence", split)
    assert split_conf < threshold, (
        f"a split panel with PERFECT integrity signals reads confidence {split_conf} "
        f"— at or above the auto-accept threshold {threshold}. The signal set was read "
        "as a correctness claim: verification says the quoted text exists, not that "
        "it is the right text, and it cannot supply the agreement confidence rides on "
        "(CT-INTEG-15)"
    )
    routing = getattr(split, "routing", None)
    assert routing != "auto", (
        f"the split panel routed {routing!r} on perfect signals — the signal set was "
        "treated as a correctness claim all the way to routing"
    )
    unan_conf = getattr(unanimous, "confidence", unanimous)
    assert unan_conf >= threshold, (
        f"the unanimous control reads confidence {unan_conf} — the designed path "
        "(agreement drives confidence to auto-accept) is broken, and the split-panel "
        "discriminator above passes vacuously"
    )
    assert getattr(unanimous, "routing", None) == "auto", (
        "the unanimous control did not route auto — the designed path is broken and "
        "the discriminator is vacuous"
    )


def test_tc_integ_c15_the_non_promise_oracles_have_teeth():
    """`TC-INTEG-C15`'s executable constructions — the relevance-smelling gate
    (irrelevant evidence flagged), the signals-as-correctness consumer (a
    perfect signal set lifting a split panel to auto), and the broken-designed-
    path consumer all go red. Runs green now: it asserts the oracles' teeth,
    not the implementation."""
    from types import SimpleNamespace

    relevant = SimpleNamespace(spans_verified=True, evidence_present=True,
                               ocr_overlap_risk=False, described_evidence=False,
                               extractor_disagreement=False)
    _assert_signals_are_relevance_blind(SimpleNamespace(**relevant.__dict__),
                                        relevant)                     # faithful
    smeller = SimpleNamespace(spans_verified=False, evidence_present=True,
                              ocr_overlap_risk=False, described_evidence=False,
                              extractor_disagreement=False)
    with pytest.raises(AssertionError, match="does not promise"):
        _assert_signals_are_relevance_blind(smeller, relevant)        # the smeller
    with pytest.raises(AssertionError, match="extractor disagreement"):
        smuggler = SimpleNamespace(**relevant.__dict__)
        smuggler.extractor_disagreement = True
        _assert_signals_are_relevance_blind(smuggler, relevant)       # the smuggler

    faithful_split = SimpleNamespace(confidence=0.4, routing="queued")
    faithful_unanimous = SimpleNamespace(confidence=1.0, routing="auto")
    _assert_clean_signals_supply_no_confidence(
        faithful_split, faithful_unanimous, 0.80)                     # faithful
    with pytest.raises(AssertionError, match="correctness claim"):
        _assert_clean_signals_supply_no_confidence(
            SimpleNamespace(confidence=0.9, routing="auto"),
            faithful_unanimous, 0.80)                                 # the bonus mutant
    with pytest.raises(AssertionError, match="passes vacuously"):
        _assert_clean_signals_supply_no_confidence(
            faithful_split,
            SimpleNamespace(confidence=0.5, routing="queued"), 0.80)  # the broken path


# --- the fixture and its gate-real premise ----------------------------------------------------


def _view(cited_sentence: str) -> ExtractionView:
    span = byte_span(_MARKDOWN, cited_sentence)
    return ExtractionView(spans=(span,), panel=PanelFlags((True, True, True)))


def test_tc_integ_c15_the_signal_set_is_relevance_blind(tmp_data_dir):
    """`TC-INTEG-C15` — the premise, through the real gate: the document
    contains both sentences, the extraction cites the irrelevant one, and every
    integrity field reads exactly as it does for the relevant citation.
    Verification promised the quoted text exists — it did — and nothing in the
    set promised it was the right text."""
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#74")
    store = open_store(tmp_data_dir)
    try:
        orch, run_id, _version = seed_run(
            store, submissions=(_SUBMISSION,),
            criteria=({"criterion_id": _CRITERION_ID, "kind": "open",
                       "scoring_model": "holistic"},))
        handle = store.cohort(ORCH_COHORT_ID)
        seed_document(handle, document_id_for(_SUBMISSION), _SUBMISSION, _MARKDOWN,
                      ORCH_COHORT_ID)
        orch.enumerate_units(run_id)
        relevant = IntegrityGate(handle, store.blobs(), _view(_RELEVANT),
                                 ocr_conf_floor=0.70).verify(
                                     run_id, _SUBMISSION, _CRITERION_ID)
        irrelevant = IntegrityGate(handle, store.blobs(), _view(_IRRELEVANT),
                                   ocr_conf_floor=0.70).verify(
                                       run_id, _SUBMISSION, _CRITERION_ID)
        _assert_signals_are_relevance_blind(irrelevant, relevant)
    finally:
        store.close()


# --- the consumer half: M-AGG rung 3 ----------------------------------------------------------


def _cites(span) -> tuple:
    return (span,)


def _panel(bands, span) -> tuple[ConsumerVerdict, ...]:
    return tuple(ConsumerVerdict(f"judge-{i}", band, cited_spans=_cites(span))
                 for i, band in enumerate(bands))


def test_tc_integ_c15_perfect_signals_cannot_supply_missing_agreement():
    """`TC-INTEG-C15` — the consumer half: the all-clean signal set over
    verified-but-irrelevant evidence, fed to `aggregate` with two panels that
    differ ONLY in agreement. The split panel stays below the atomic threshold
    and never routes auto — perfect signals are the absence of adverse flags,
    not an endorsement — and the unanimous panel reaches auto on the same
    signals. The signal set contributed nothing in either direction; the panel
    decided."""
    IntegritySignals = require(INTEG_MODULE, "IntegritySignals", issue="#74")
    aggregate, auto_threshold = require(
        AGG_MODULE, "aggregate", "AGG_AUTO_THRESHOLD_ATOMIC", issue="#92")
    clean = IntegritySignals(
        spans_verified=True, evidence_present=True, sufficiency_flag=False,
        ocr_overlap_risk=False, described_evidence=False, extractor_disagreement=False,
    )
    span = byte_span(_MARKDOWN, _IRRELEVANT)  # verified-but-irrelevant, cited anyway
    criterion = Criterion(_CRITERION_ID)      # atomic: the 0.80 threshold governs
    split = aggregate(_panel(("B0", "B2", "B3"), span), criterion, clean)
    unanimous = aggregate(_panel(("B0", "B0", "B0"), span), criterion, clean)
    _assert_clean_signals_supply_no_confidence(split, unanimous, auto_threshold)


# --- the deferred M-CONSOLE half --------------------------------------------------------------
# Deferred to the console suite: see the module docstring's `M-CONSOLE` half
# row. The presentation assertion ("the signals with their actual meaning
# rather than as a validity badge") needs `aeh.console:build_console` (#122)
# and the console vocabulary; this file's fixture — verified-but-irrelevant
# evidence and its clean signal set — is the scenario that case should run.
