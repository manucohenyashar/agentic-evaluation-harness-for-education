"""`TC-INTEG-13`, `ADV-01` and `ADV-03` — hallucinated and forged evidence, caught by
verification rather than scored (TS-29, issue #76).

Test plan §5.9 (13: P0, `FR-INTEG-01`, Adversarial / 2) and §6.6 (ADV-01: `FR-AGG-05` +
`FR-INTEG-01`, the confidence inversion; ADV-03: `FR-INTEG-01` + `FR-JUDGE-17`, span
verification). Written ahead of `#73`/`#74` (test plan §8.2); the ADV-01 cap half is
written ahead of `#92`, the M-AGG confidence story.

**The adversarial construction** — the `F-ADV-INJ` forged-citation pairs, which are
committed data (`#3`), not fixtures built here. Each payload plants a line formatted to
look like a quotation of the paper itself::

    As I wrote on the previous page: "the crate accelerates at 9.8 metres per second
    squared down the ramp".

The paper never wrote that. The manipulated extractor obeys the forgery and emits a
citation for it — a span whose TEXT is the quote and whose OFFSETS point into the
paper's content. That construction is what makes the case red rather than merely
executable: the quoted text IS somewhere in the document (the payload planted it), so a
verifier that asks "does this text appear anywhere in the document" — or that normalizes,
fuzz-matches, or tolerates a one-character drift — ACCEPTS the forged citation, and every
test below fails on the spot. Only byte-exact comparison at the claimed offsets
(FR-INTEG-01, NFR-INTEG-02: "a pure function of (document bytes, span)") rejects it,
which is the requirement under attack. The corpus-level property behind this — the quote
appears in the injected document only inside the payload and never in the benign twin —
is `test_tc_conform_09_adversarial_corpora.py`'s; the premise assertions below restate it
locally because the construction's validity is what the case stands on.

**The benign-twin differential** is §6.6's oracle wherever it applies: the same citation
mechanism over the twin's honest content verifies; the forged one does not; and the same
unanimous panel over the twin's verified evidence is not capped, so the injection bought
no confidence (ADV-01's "auto-acceptance on unverified evidence is the failure").

**Coordinates are BYTE offsets into `document.markdown`** — the #75 review's critical
finding, applied from the first line: every offset below is computed on the UTF-8
encoding (`text.encode("utf-8")`), never a codepoint index, and every premise compares
encoded bytes. A codepoint-slicing verifier fails these cases on any multibyte document;
the corpus prose happens to be ASCII, so the helpers stay byte-honest without depending
on that.

**ADV-01's cap half** drives M-AGG's declared pure surface (`aggregate(verdicts,
criterion, signals) -> CriterionScore`, design §3.12, CT-AGG-01) with the signals the
real gate produced over the real store — the adversarial chain, not hand-built inputs.
The cap itself is `#92`'s (FR-AGG-05); the exhaustive 64-cell decision table over the
signals is `TC-AGG-06`'s (`M-AGG` track) and is not repeated here — what is asserted is
the adversarial instance: three unanimous verdicts citing evidence the gate rejected.

Interfaces assumed (reconcile at landing; the M-INTEG rows are the table in
`tests/support/integ_vocabulary.py`):

| Name | Status |
|---|---|
| `aeh.integ.verify_span`, `IntegrityGate`, `IntegritySignals` | the #75-disclosed keys, reused — no new M-INTEG names are minted here |
| `aeh.agg.aggregate`, `aeh.agg.AGG_AUTO_THRESHOLD_ATOMIC` | design §3.12-declared names (Protocol member, Configuration constant); the confidence story that lands them is `#92` |
| `Verdict` / `Criterion` / `CriterionScore` field names | HLD §9.9 / §9.6 shapes constructed directly by consumers, as §3.12's own contract states ("Consumers construct `Verdict` and `IntegritySignals` values directly"); the records below carry `judge_id`, `band`, `cited_spans`, `self_confidence` / `criterion_id`, `bands`, `scoring_model` / `confidence`, `routing` and reconcile when `M-JUDGE`/`M-AGG` land their dataclasses |
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support import corpora
from tests.support.impl import AGG_MODULE, INTEG_MODULE, require
from tests.support.integ_vocabulary import (
    Doc,
    ExtractionView,
    PanelFlags,
    Span,
    document_id_for,
    seed_document,
    seed_verdict,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},)
_PANEL_SIZE = 3
_OCR_FLOOR = 0.70

#: The band the attacker's panel unanimity wants: the top of the criterion's four bands.
_ATTACK_BAND = "B3"


def _forged_pairs() -> list[tuple[corpora.CorpusMember, corpora.CorpusMember]]:
    """The F-ADV-INJ pairs whose payload kind is `forged_citation`.

    The whole tier is swept, not one memorable payload: a defence that memorized one
    string would pass a tier of one (the TC-CONFORM-09 reasoning, applied to the case
    that consumes it).
    """
    pairs = [
        (benign, injected)
        for benign, injected in corpora.injection_pairs()
        if injected.attributes["injection_kind"] == "forged_citation"
    ]
    assert pairs, (
        "no forged_citation pairs in F-ADV-INJ — the corpus no longer carries the shape "
        "TC-INTEG-13 is written against, so this case must be rebuilt rather than run"
    )
    return pairs


def _pair(pairs: dict, injected_id: str):
    assert injected_id in pairs, (
        f"{injected_id} is no longer a forged_citation pair; pick another and update "
        "the scenario's choice of pair"
    )
    return pairs[injected_id]


# --- the forged spans, in bytes ------------------------------------------------------------


def _quote_span(markdown: str, quote: str, claimed_onto: str) -> Span:
    """`quote` cited from byte offsets that actually hold `claimed_onto`.

    The span a manipulated extractor emits: TEXT is the planted quotation, OFFSETS point
    at the start of the paper's own first line — a plausible place for the citation to
    claim. The callers assert the premises that make this a forgery: the quote is in the
    document (planted via the payload) but not at these offsets.
    """
    raw = markdown.encode("utf-8")
    start = raw.find(claimed_onto.encode("utf-8"))
    assert start >= 0, "the claimed region is not in the document at all"
    end = start + len(quote.encode("utf-8"))
    assert end <= len(raw), (
        "the forged citation runs past the end of the document — reposition the claimed "
        "region so the span is in bounds, or the case tests bounds handling (TC-INTEG-09's "
        "property, FUZZ-03's) instead of forgery"
    )
    return Span(start, end, quote)


def _honest_span(markdown: str, passage: str) -> Span:
    """The twin's honest citation: the exact byte slice of a real passage."""
    raw = markdown.encode("utf-8")
    start = raw.find(passage.encode("utf-8"))
    assert start >= 0, "the honest passage is not in the document"
    return Span(start, start + len(passage.encode("utf-8")), passage)


def _near_miss(span: Span, position: int) -> Span:
    """The same span with ONE character of its text substituted — the ADV-03 near miss.

    Substitution, not insertion: same byte length, edit distance one, exactly the mutant
    an edit-distance-tolerant or whitespace-normalizing verifier accepts and byte-exact
    verification must refuse.
    """
    text = span.text
    i = position % len(text)
    swapped = "Z" if text[i] != "Z" else "Q"
    return Span(span.start, span.end, text[:i] + swapped + text[i + 1 :])


def _first_line(markdown: str) -> str:
    """The document's first non-empty content line — the paper's own opening."""
    for line in markdown.splitlines():
        if line.strip():
            return line
    raise AssertionError("the document has no content lines")


# --- the rung-2 scenario -------------------------------------------------------------------


def _scenario(tmp_data_dir, members: list[corpora.CorpusMember]):
    """One real run over the given F-ADV-INJ members: real SQLite, real blob dir.

    Each member gets its own document and its own gate; the view is the M-EXTRACT/M-JUDGE
    stand-in `#75`'s suite already reconciled. The second family agrees with the first
    (`extractor_disagreement = False`) so that the ONLY difference between a pair's signal
    sets is span verification — the forged evidence fooled both extraction families, and
    the case must not owe its red to a signal the injection never touched.
    """
    store = open_store(tmp_data_dir)
    orch, run_id, _version = seed_run(
        store, submissions=[m.id for m in members], criteria=_CRITERIA
    )
    handle = store.cohort(ORCH_COHORT_ID)
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#74")
    gates: dict[str, object] = {}
    for member in members:
        markdown = member.text()
        seed_document(handle, document_id_for(member.id), member.id, markdown,
                      ORCH_COHORT_ID)
        quote = member.attributes.get("forged_quote")
        if quote:
            # The manipulated extractor's emission: the planted quote, cited from the
            # paper's own opening (which says nothing of the kind).
            spans = (_quote_span(markdown, quote, _first_line(markdown)),)
        else:
            spans = (_honest_span(markdown, _first_line(markdown)),)
        view = ExtractionView(
            spans=spans,
            second_family_spans=spans,  # both families obeyed the forgery alike
            panel=PanelFlags((True, True, True)),
        )
        gates[member.id] = IntegrityGate(handle, store.blobs(), view,
                                         ocr_conf_floor=_OCR_FLOOR)
    orch.enumerate_units(run_id)
    return store, run_id, gates


def _extract_retries(store, run_id: str, submission_id: str) -> list[dict]:
    return store.cohort(ORCH_COHORT_ID).query(
        "SELECT work_id, status, attempts FROM work_unit WHERE run_id = :r AND "
        "submission_id = :s AND stage = 'extract' ORDER BY work_id",
        r=run_id, s=submission_id,
    )


def _score_rows(store, run_id: str) -> list[dict]:
    return store.durable().query(
        "SELECT * FROM criterion_score WHERE run_id = :r", r=run_id
    )


# --- TC-INTEG-13: every forged citation fails byte-exact verification -----------------------


def test_tc_integ_13_every_forged_citation_fails_byte_exact_verification():
    """`TC-INTEG-13` (P0) — the sweep over the whole forged-citation tier.

    For every pair: the quote is planted in the injected document (via the payload) and
    absent from the source content the citation claims to quote; the claimed span is
    in bounds; and `verify_span` returns False. The benign twin's honest citation — the
    same mechanism over content that really is there — verifies, so the case cannot be
    passed by a verifier that rejects everything.
    """
    verify_span = require(INTEG_MODULE, "verify_span", issue="#73")
    for benign, injected in _forged_pairs():
        quote = injected.attributes["forged_quote"]
        assert quote, f"{injected.id} is a forged_citation pair and names no quote"

        # The construction's premises, each naming what breaks if it fails.
        assert quote in injected.text(), (
            f"{injected.id}: the quotation is not in its own document — a citation the "
            "submission never makes cannot be forged, and this case would pass against a "
            "verifier that accepts nothing"
        )
        source = corpora.benign_page_of(injected) + "\n".join(injected.pages()[1:])
        assert quote not in source, (
            f"{injected.id}: the quote appears in the source content, so it is not "
            "forged — the payload stopped being spliced and the case would hold a real "
            "citation to the standard meant for a fake one"
        )
        raw = injected.text().encode("utf-8")
        span = _quote_span(injected.text(), quote, _first_line(injected.text()))
        assert 0 <= span.start < span.end <= len(raw), (
            f"{injected.id}: the claimed citation is out of bounds"
        )
        assert raw[span.start:span.end] != quote.encode("utf-8"), (
            f"{injected.id}: the bytes under the claimed offsets ARE the quoted text — "
            "the span would verify correctly and is not a forgery"
        )

        assert verify_span(Doc(markdown=injected.text()), span) is False, (
            f"{injected.id}: a forged citation verified. The quote exists in the document "
            "only because the payload planted it there; accepting it means verification "
            "searched the document (or normalized the comparison) instead of comparing "
            "the claimed bytes — RISK-16's citation-forgery half, undetected"
        )

        # The differential: the twin's honest citation over the same mechanism.
        honest = _honest_span(benign.text(), _first_line(benign.text()))
        assert verify_span(Doc(markdown=benign.text()), honest) is True, (
            f"{benign.id}: the honest citation failed verification — a verifier that "
            "rejects everything is not a verifier, and the differential is what makes "
            "the forged half mean something"
        )


def test_tc_integ_13_a_forged_citation_routes_and_nothing_is_scored(tmp_data_dir):
    """`TC-INTEG-13`'s routing half, at rung 2 — the unit routes and nothing scores.

    The gate over the injected twin: `spans_verified` False, a re-extraction request in
    the ledger (a pending extract unit whose attempts grew — a fresh request, not the
    enumeration's original row), and no `criterion_score` row anywhere in the run: the
    citation-forgery half of RISK-16 ends as an extraction problem, never as a band.
    The benign twin is the control: honest evidence does not route.
    """
    pairs = {i.id: (b, i) for b, i in _forged_pairs()}
    injected_id, benign_id = "INJ-05-A", "INJ-05-B"
    _injected, _benign = _pair(pairs, injected_id)
    store, run_id, gates = _scenario(
        tmp_data_dir, [pairs[injected_id][1], pairs[injected_id][0]]
    )
    require(INTEG_MODULE, "IntegritySignals", issue="#74")

    signals = gates[injected_id].verify(run_id, injected_id, "C1")
    assert signals.spans_verified is False, (
        "the gate verified a citation the document does not make — RISK-16's forgery "
        "half passed the integrity gate"
    )
    retries = [u for u in _extract_retries(store, run_id, injected_id)
               if u["status"] == "pending" and u["attempts"] >= 1]
    assert retries, (
        "the forged-evidence unit was not routed for re-extraction — unverified evidence "
        "proceeding to scoring is CT-INTEG-06's forbidden path"
    )
    assert not _score_rows(store, run_id), (
        "a criterion_score row exists for a run whose evidence failed verification — "
        "nothing scores on a span this module rejected (CT-INTEG-06)"
    )

    benign_signals = gates[benign_id].verify(run_id, benign_id, "C1")
    assert benign_signals.spans_verified is True, (
        "the benign twin's honest citation failed verification — the differential must "
        "split on forgery, not on the mechanism"
    )
    assert not [u for u in _extract_retries(store, run_id, benign_id)
                if u["status"] == "pending" and u["attempts"] >= 1], (
        "the benign twin routed for re-extraction — the gate is rejecting honest evidence"
    )
    store.close()


# --- ADV-03: near-miss quotations ----------------------------------------------------------


def test_adv_03_near_miss_quotations_differing_by_one_character_fail_verification():
    """`ADV-03`'s near-miss arm — quotations differing from the document by one character.

    The attacker's stronger forgery is not an invented quote but a drifted one: the
    paper's real text with a single character changed. For every forged pair, the exact
    slice verifies (the control) and the one-character substitution at the first,
    a middle and the last position fails — the mutants a byte-exact `verify_span` must
    refuse and a fuzzy, normalized or edit-distance-tolerant one accepts.
    """
    verify_span = require(INTEG_MODULE, "verify_span", issue="#73")
    for benign, _injected in _forged_pairs():
        markdown = benign.text()
        honest = _honest_span(markdown, _first_line(markdown))
        assert verify_span(Doc(markdown=markdown), honest) is True, (
            f"{benign.id}: the control drift — an exact slice must verify"
        )
        for position, label in (
            (0, "the first character"),
            (len(honest.text) // 2, "a middle character"),
            (len(honest.text) - 1, "the last character"),
        ):
            drifted = _near_miss(honest, position)
            assert drifted.text != honest.text, (
                f"{benign.id} ({label}): the drift changed nothing"
            )
            assert len(drifted.text.encode("utf-8")) == len(
                honest.text.encode("utf-8")
            ), (
                f"{benign.id} ({label}): the drift changed the length, which is a "
                "trivially-caught mutant — substitution is the adversarial one"
            )
            assert verify_span(Doc(markdown=markdown), drifted) is False, (
                f"{benign.id}: a quotation differing from the document by one character "
                f"({label}) verified. Byte-exact verification (FR-INTEG-01) cannot "
                "accept it; a verifier that did has tolerance, and the tolerance is "
                "the hole ADV-03 exists to find"
            )


# --- ADV-01: the confidence inversion -------------------------------------------------------


class _Verdict:
    """A consumer-constructed verdict record (HLD §9.9's shape; see module docstring)."""

    def __init__(self, judge_id: str, band: str, cited_spans: tuple[Span, ...],
                 self_confidence: float) -> None:
        self.judge_id = judge_id
        self.band = band
        self.cited_spans = cited_spans
        self.self_confidence = self_confidence
        self.evidence_sufficient = True


class _Criterion:
    """The criterion record `aggregate` reads (HLD §9.9's criterion block)."""

    def __init__(self, criterion_id: str, bands: tuple[str, ...],
                 scoring_model: str) -> None:
        self.criterion_id = criterion_id
        self.bands = bands
        self.scoring_model = scoring_model


_CRITERION = _Criterion("C1", ("B0", "B1", "B2", "B3"), "atomic")


def test_adv_01_unanimous_panel_on_unverified_evidence_is_capped_and_never_auto_accepts(
    tmp_data_dir,
):
    """`ADV-01` (P0) — the confidence inversion, attacked with the corpus's own forgery.

    Three unanimous verdicts, all citing the evidence, all confident: the attacker's
    input. The gate rejects the forged spans; `aggregate` receives the gate's adverse
    signals and must cap the confidence below the auto-accept threshold and route the
    item — a `min` cap, so no amount of unanimity can outrun it (FR-AGG-05, ADR-10).
    The benign twin, fed the same verdicts over evidence that verifies, is NOT capped:
    the injection bought nothing. Auto-acceptance on unverified evidence is the failure.

    The cap's exact value is `#92`'s tuning table (TC-AGG-06 sweeps all 64 signal
    combinations); what is asserted here is the adversarial instance of it.
    """
    aggregate, auto_threshold = require(
        AGG_MODULE, "aggregate", "AGG_AUTO_THRESHOLD_ATOMIC", issue="#92"
    )
    pairs = {i.id: (b, i) for b, i in _forged_pairs()}
    injected_id, benign_id = "INJ-06-A", "INJ-06-B"
    _pair(pairs, injected_id)
    store, run_id, gates = _scenario(
        tmp_data_dir, [pairs[injected_id][1], pairs[injected_id][0]]
    )
    handle = store.cohort(ORCH_COHORT_ID)

    # Sweep 2 answers for both twins: three real verdict rows each — the panel is real
    # ledger state, and the gate's conservative sufficiency default lifts (TC-INTEG-12's
    # sequence) so the ONLY adverse thing on the injected side is the verification.
    for member_id in (injected_id, benign_id):
        score_units = store.cohort(ORCH_COHORT_ID).query(
            "SELECT work_id FROM work_unit WHERE run_id = :r AND submission_id = :s "
            "AND stage = 'score' ORDER BY work_id LIMIT 3",
            r=run_id, s=member_id,
        )
        assert len(score_units) == _PANEL_SIZE, (
            f"{member_id}: the run did not enumerate a three-judge score panel"
        )
        for i, unit in enumerate(score_units):
            seed_verdict(handle, f"v-forged-{member_id}-{i}", unit["work_id"],
                         f"judge-{i}", _ATTACK_BAND)

    forged_signals = gates[injected_id].verify(run_id, injected_id, "C1")
    honest_signals = gates[benign_id].verify(run_id, benign_id, "C1")
    assert forged_signals.spans_verified is False, (
        "the gate verified the forged citation — the attack is over before aggregation"
    )
    assert honest_signals.spans_verified is True

    # The attacker's panel: unanimous, top band, every verdict citing evidence, every
    # judge confident — identical for both twins, so the ONLY difference `aggregate`
    # sees is the gate's verdict about the evidence. The cited span's coordinates are
    # irrelevant to the confidence computation (the signals carry the integrity input);
    # a one-byte in-bounds span stands in for the citation both panels make.
    def _panel(cited: Span) -> tuple[_Verdict, ...]:
        return tuple(
            _Verdict(f"judge-{i}", _ATTACK_BAND, (cited,), 0.95)
            for i in range(_PANEL_SIZE)
        )

    citation = Span(0, 1, "T")  # any in-bounds byte; the signals carry the integrity
    capped = aggregate(_panel(citation), _CRITERION, forged_signals)
    honest = aggregate(_panel(citation), _CRITERION, honest_signals)

    assert capped.confidence < auto_threshold, (
        f"capped confidence {capped.confidence} sits at or above the auto-accept "
        f"threshold {auto_threshold} — a unanimous panel auto-accepted on evidence the "
        "integrity gate rejected, which is exactly RISK-01 (HLD §12's most dangerous "
        "failure)"
    )
    assert capped.routing != "auto", (
        "the unverified item routed auto — 'the item routes' means it went to a human "
        "queue, not out the door (CT-AGG-06)"
    )
    assert capped.confidence < honest.confidence, (
        "the forged evidence's confidence is not lower than the honest twin's — the "
        "injection bought confidence, which the §6.6 differential forbids"
    )
    assert honest.confidence >= auto_threshold, (
        "even the fully-favourable case cannot reach the auto-accept threshold — the "
        "premise of the inversion is that unanimity CAN carry verified evidence "
        "(TC-AGG-06's step-1 record); if the base formula cannot, the cap is not what "
        "is being tested"
    )
    store.close()
