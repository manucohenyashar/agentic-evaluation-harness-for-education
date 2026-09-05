"""The vocabulary TS-02's four cases are written against, and where each term came from.

`TC-CONFORM-01`, `-02`, `-03` and `-09` are about **corpora**: what the frozen set contains, what
the adversarial tier contains, and what neither of them may contain. Every list below is
transcribed from test plan §4.4's corpus table or from the requirement it cites, and
`tests/regression/test_adversarial_vocabulary.py` asserts each transcription still matches the
document. Those assertions are green and they are **not coverage** — they check that this fixture
still matches the plan, not that any module does anything.

Two relations are asserted as **subsets**, never as equalities, and the direction matters:

* `conform_vocabulary.INJECTION_PAYLOAD_KINDS` holds the three kinds `FR-CONFORM-09` enumerates.
  §4.4 names five, and `ADV-02` confirms the extra two (*"including paraphrased, encoded and
  translated variants"*). The corpus carries five; the requirement's three must be among them.
* `conform_vocabulary.MALICIOUS_PDF_KINDS` holds four threat kinds. §4.4 names fourteen
  constructs. The corpus carries fourteen; the requirement's four must be among them.

Asserting equality in either direction would be wrong in a way that costs something. Equality
against the requirement's list would forbid the corpus from covering `SubmitForm` — a construct
§4.4 names and `SEC-05..09` needs. Equality against the corpus would let somebody delete
`decompression_bomb` from the requirement's list and stay green.
"""

from __future__ import annotations

from typing import Iterable

TEST_PLAN = "docs/design/test-plan.md"

# --- §4.4's corpus rows, located by their leading cell -----------------------------------------
#
# The corpus name as §4.4 writes it, which is what a row locator matches on. Kept as data so the
# drift test can loop rather than repeat itself once per corpus.
CORPUS_ROW_MARKERS: dict[str, str] = {
    "F-ADV-PDF": "**F-ADV-PDF**",
    "F-ADV-INJ": "**F-ADV-INJ**",
    "F-HAND": "**F-HAND**",
    "F-FROZEN": "**F-FROZEN**",
}

#: Phrases that must still appear in §4.4's `F-ADV-PDF` row. Every one of the fourteen constructs
#: is named there in prose; these are the spellings the row uses, mapped to the `construct` value
#: `harness.corpora.adv_pdf` emits. A construct whose §4.4 phrase disappeared would mean the plan
#: no longer asks for it — a finding, not a rename.
ADV_PDF_PHRASES: dict[str, str] = {
    "embedded_javascript": "embedded JavaScript",
    "open_action": "`OpenAction`",
    "additional_actions": "`AA`",
    "launch_action": "`Launch`",
    "embedded_file": "embedded file",
    "uri_action": "`URI`",
    "goto_remote": "`GoToR`",
    "submit_form": "`SubmitForm`",
    "decompression_bomb": "decompression bomb",
    "page_count_bomb": "100k-page file",
    "giant_image": "60000×60000-pixel image",
    "encrypted": "encrypted file",
    "zero_page": "zero-page file",
    "truncated": "truncated file",
}

#: The same for §4.4's `F-ADV-INJ` row and its five payload kinds.
ADV_INJ_PHRASES: dict[str, str] = {
    "band_forcing": "band-forcing directive",
    "forged_citation": "forged citation",
    "contract_breaking": "contract-breaking instruction",
    "role_claim": "role claim",
    "encoded_translated": "encoded/translated variant",
}

#: §4.4's own floor for the injection tier: *">= 20 pairs"*, written there as `≥ 20 pairs`.
MIN_TWIN_PAIRS = 20

#: `FR-CONFORM-01`'s bounds, restated here so TS-02's cases and TS-75's read one number. Identical
#: to `conform_vocabulary.CORPUS_MIN`/`CORPUS_MAX` by construction — `test_adversarial_vocabulary`
#: asserts the two agree, so the duplication cannot become a disagreement.
FROZEN_MIN = 30
FROZEN_MAX = 50

#: `FR-CONFORM-01`: *"spanning the score range and including mid-range partial-credit cases"*. The
#: fractions below are this suite's reading of "the score range" and "mid-range" — the requirement
#: names neither a threshold nor a fraction — and they match the reading TS-75's
#: `test_tc_conform_c01_...` already committed to, so the two suites cannot disagree about what
#: passes. Stated as constants so a later reader can argue with the numbers rather than inherit
#: them from an expression buried in an assertion.
SPAN_LOW_FRACTION = 0.2
SPAN_HIGH_FRACTION = 0.8
MID_RANGE_LOW = 1 / 3
MID_RANGE_HIGH = 2 / 3

#: The consent classes §4.4 permits a *committed* corpus to carry. `consented` is deliberately
#: absent: `NFR-CONFORM-03` allows the fixture corpus to hold consented work, but §4.4's PII rules
#: make `F-HAND` the only consented corpus and forbid committing it. So anything in `fixtures/`
#: declaring `consented` is either mislabelled synthetic data or real student work in the repo,
#: and both are findings.
COMMITTABLE_CONSENT_CLASSES: frozenset[str] = frozenset({"synthetic"})

#: The corpora committed to this repository that hold submission-shaped documents. Listed rather
#: than discovered by globbing `fixtures/*`: a corpus that stopped being emitted would make a glob
#: silently sweep less, and every assertion built on it would go green by covering nothing.
COMMITTED_SUBMISSION_CORPORA: tuple[str, ...] = (
    "F-SYNTH",
    "F-FROZEN",
    "F-DEV",
    "F-ADV-INJ",
)

#: The committed corpora that hold *pages* rather than submissions: no `student_ref`, no reference
#: bands, and so outside the submission sweeps above. `F-GRAPHIC` is the one, and it is the corpus
#: most likely to be relabelled a real medium later — it stands in for page images. It carries the
#: same `consent_class` and `media_kind` declarations for exactly that reason.
COMMITTED_PAGE_CORPORA: tuple[str, ...] = ("F-GRAPHIC",)

#: Every committed corpus whose members declare a medium and a consent class. Two lists joined
#: rather than one flat list, because the two groups are swept for different things — a page has no
#: `student_ref` to check — and a single list would have to be filtered at each use, which is how a
#: corpus quietly falls out of one sweep while looking covered by the other.
COMMITTED_MEDIA_DECLARING_CORPORA: tuple[str, ...] = (
    *COMMITTED_SUBMISSION_CORPORA,
    *COMMITTED_PAGE_CORPORA,
)

def missing_phrases(row_text: str, phrases: Iterable[str]) -> list[str]:
    """The phrases absent from a §4.4 row.

    Returned as a list rather than asserted here, so the caller's failure message can name the
    corpus. A rule that returns its findings by name is also a rule that can be run against a
    deliberately broken copy of the document and shown to fire — the TS-57 lesson.
    """
    return [phrase for phrase in phrases if phrase not in row_text]
