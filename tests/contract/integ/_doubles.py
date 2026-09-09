"""Shared doubles for the `CT-INTEG` clause suite (TS-66, issue #77).

The #75/#76 files already reconciled the M-INTEG seam in
`tests/support/integ_vocabulary.py` — `verify_span`, `IntegrityGate`,
`IntegritySignals`, `ExtractionView` and the seeding helpers — and every file
here reuses those rather than minting new seams. This module holds only what
the clause cases need that no earlier file did:

- `RefusingSurface` and `block_module_surfaces`: the "all three blocked"
  enforcement CT-INTEG-01 names — every public callable on a module is
  replaced with a raiser, so a violation raises rather than passing slowly.
- `ConsumerVerdict` / `Criterion`: consumer-constructed records for the rung-3
  `M-AGG` differential cases (the shapes §3.12's own contract says consumers
  construct directly; the `#76` precedent's `_Verdict`/`_Criterion`, shared).
- `byte_span`: the one honest span builder — BYTE offsets into
  `document.markdown` (the #75 review's critical finding, applied from the
  first line), because a codepoint index is silently wrong on every multibyte
  document.
- `make_gate` / `seeded_document`: the rung-2 scenario, over a real store per
  §4.2 (SQLite and the blob store are never doubled).

Nothing here doubles M-INTEG's behaviour: the gate itself is always
`require`d from `aeh.integ` inside the test body, so a missing implementation
fails as a stated `NotImplementedYet` naming its issue, never as a fake pass.
"""

from __future__ import annotations

from typing import Any, Iterable

from aeh.store import open_store as open_store

from tests.support.impl import INTEG_MODULE, require
from tests.support.integ_vocabulary import (
    Doc,
    Span,
    document_id_for,
    seed_document,
)

#: The cohort id the contract scenarios seed into; distinct from the #75
#: integration suites' ids so a query can never cross suites by accident.
CONTRACT_COHORT = "c-2026-integ-contract"

#: CT-INTEG-13's floor (design §3.9 Configuration: Assumption 0.70) as the
#: scenarios' injected value — a literal in the test, never read from
#: production code (Q-04), reconciled with #75's `FLOOR` constant.
OCR_FLOOR = 0.70


class RefusingSurface:
    """A blocked surface: touching it in any way raises, loudly.

    CT-INTEG-01: "`verify_span` ... makes no model call, no network call, and
    no store read beyond the document bytes handed to it" — enforced with all
    three blocked "so a violation raises rather than passing slowly". Instances
    of this class are what the blocked surfaces are replaced with.
    """

    def __init__(self, what: str) -> None:
        self._what = what

    def _refuse(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError(
            f"TC-INTEG-C01: the call reached a blocked {self._what} surface — "
            "verify_span must be zero-cost: no model call, no network call, no "
            "store read beyond the bytes handed in (CT-INTEG-01)"
        )

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._refuse(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._refuse


def block_module_surfaces(monkeypatch: Any, module: Any, skip: Iterable[str] = ()) -> None:
    """Replace every public callable on `module` with a `RefusingSurface`.

    Used for the blocked-surface limb: after this, any attempt by the code
    under test to reach the module's API raises instead of passing slowly.
    `skip` names attributes that must survive (rare; the raiser itself needs
    nothing from the module).
    """
    for name in dir(module):
        if name.startswith("_") or name in skip:
            continue
        if callable(getattr(module, name, None)):
            monkeypatch.setattr(module, name, RefusingSurface(f"{module.__name__}.{name}"),
                                raising=False)


def byte_span(markdown: str, needle: str, *, occurrence: int = 0) -> Span:
    """The span of `needle`'s `occurrence`-th appearance, in BYTE offsets.

    The only span builder the contract suite uses: `start` and `end` are
    computed on the UTF-8 encoding, never a codepoint index, and the text is
    the exact slice — so a codepoint-slicing implementation fails every case
    that touches a multibyte document, which is the point.
    """
    raw = markdown.encode("utf-8")
    hits: list[int] = []
    at = raw.find(needle.encode("utf-8"))
    while at != -1:
        hits.append(at)
        at = raw.find(needle.encode("utf-8"), at + 1)
    start = hits[occurrence]
    end = start + len(needle.encode("utf-8"))
    return Span(start, end, markdown.encode("utf-8")[start:end].decode("utf-8"))


class ConsumerVerdict:
    """A consumer-constructed verdict record (HLD §9.9's shape; `#76` precedent).

    `aggregate(verdicts, criterion, signals)` is §3.12's declared pure surface;
    the records below carry the field names the `#76` file reconciled —
    `judge_id`, `band`, `cited_spans`, `self_confidence`, `evidence_sufficient`
    — and reconcile when M-JUDGE/M-AGG land their dataclasses.
    """

    def __init__(self, judge_id: str, band: str, cited_spans: tuple[Span, ...] = (),
                 self_confidence: float = 0.95, evidence_sufficient: bool = True) -> None:
        self.judge_id = judge_id
        self.band = band
        self.cited_spans = cited_spans
        self.self_confidence = self_confidence
        self.evidence_sufficient = evidence_sufficient


class Criterion:
    """The criterion record `aggregate` reads (HLD §9.9's criterion block)."""

    def __init__(self, criterion_id: str, bands: tuple[str, ...] = ("B0", "B1", "B2", "B3"),
                 scoring_model: str = "atomic") -> None:
        self.criterion_id = criterion_id
        self.bands = bands
        self.scoring_model = scoring_model


def unanimous_panel(band: str = "B2", size: int = 3) -> tuple[ConsumerVerdict, ...]:
    """A fully agreeing, fully confident panel — the input every consumer cap
    case attacks with."""
    return tuple(ConsumerVerdict(f"judge-{i}", band) for i in range(size))


def seeded_document(store: Any, submission_id: str, markdown: str) -> Doc:
    """Seed one canonical document into `store`'s contract cohort and return its `Doc`."""
    seed_document(store.cohort(CONTRACT_COHORT), document_id_for(submission_id),
                  submission_id, markdown, CONTRACT_COHORT)
    return Doc(markdown=markdown)


def make_gate(tmp_data_dir, view: Any, *, ocr_conf_floor: float = OCR_FLOOR,
              cohort: str = CONTRACT_COHORT):
    """A real gate over a real store (§4.2), the extraction side injected.

    Returns `(gate, store)`; the caller owns `store` and closes it. The gate is
    required from `aeh.integ` here — inside the test's call stack, so a missing
    implementation is a stated failure, not a collection error.
    """
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#74")
    store = open_store(tmp_data_dir)
    handle = store.cohort(cohort)
    return IntegrityGate(handle, store.blobs(), view, ocr_conf_floor=ocr_conf_floor), store
