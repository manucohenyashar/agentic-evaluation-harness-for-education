"""The adversarial corpora still contain what test plan §4.4 says they contain.

Not `TC-*`-traced. This is drift detection over the transcription in
`tests/support/adversarial.py` and `harness/corpora/adv_*.py`, in the same spirit as
`tests/regression/test_baseline_registry.py` — and like that file, **it is green and it is not
coverage**. It checks that a transcription still matches the document it came from; it asserts
nothing about any module.

It exists because §4.4's corpus rows are the *specification* of what TS-02 built, and the
generators encode them as Python lists. A row reworded in the plan and not here leaves fourteen
constructs and five payload kinds that nobody asked for any more, still passing their own
composition checks. The failure this catches is a corpus that has quietly stopped being the corpus
the plan describes.
"""

from __future__ import annotations

import pytest

from harness.corpora import adv_inj, adv_pdf, hand
from tests.support.adversarial import (
    ADV_INJ_PHRASES,
    ADV_PDF_PHRASES,
    CORPUS_ROW_MARKERS,
    FROZEN_MAX,
    FROZEN_MIN,
    MIN_TWIN_PAIRS,
    TEST_PLAN,
    missing_phrases,
)
from tests.support.conform_vocabulary import CORPUS_MAX, CORPUS_MIN
from tests.support.doc_tables import DocRowMissing, markdown_rows, read_repo_text


def _corpus_row(repo_root, corpus: str) -> str:
    """§4.4's row for one corpus, located on its leading cell.

    Keyed on the first cell rather than searched across the row, and raising on both zero matches
    and more than one: §4.4's corpus names also appear in prose throughout the plan, and a locator
    that silently picked one of several matches would assert against whichever sorted first.
    """
    marker = CORPUS_ROW_MARKERS[corpus]
    rows = markdown_rows(read_repo_text(repo_root, TEST_PLAN))
    matches = [row for row in rows if row and row[0].startswith(marker)]
    if len(matches) != 1:
        raise DocRowMissing(
            f"{len(matches)} rows in {TEST_PLAN} lead with {marker!r}; §4.4's corpus table must "
            f"have exactly one. Either the table moved (update this locator) or the corpus was "
            f"dropped from the plan (that is the finding)."
        )
    return " | ".join(matches[0])


def test_every_f_adv_pdf_construct_is_still_named_in_section_4_4(repo_root):
    row = _corpus_row(repo_root, "F-ADV-PDF")
    absent = missing_phrases(row, ADV_PDF_PHRASES.values())
    assert not absent, (
        f"§4.4's F-ADV-PDF row no longer names {absent}. The generator still emits a construct "
        f"for each; either the plan dropped it (delete the construct) or the wording changed "
        f"(update ADV_PDF_PHRASES)."
    )
    emitted = {c.construct for c in adv_pdf.CONSTRUCTS}
    assert emitted == set(ADV_PDF_PHRASES), (
        f"the generator emits {sorted(emitted)}; the transcription covers "
        f"{sorted(ADV_PDF_PHRASES)}. A construct with no §4.4 phrase is one nobody can trace."
    )
    assert tuple(adv_pdf.SECTION_4_4_CONSTRUCTS) == tuple(
        c.construct for c in adv_pdf.CONSTRUCTS
    ), "the declared §4.4 order and the order CONSTRUCTS is written in disagree"


def test_every_f_adv_inj_payload_kind_is_still_named_in_section_4_4(repo_root):
    row = _corpus_row(repo_root, "F-ADV-INJ")
    absent = missing_phrases(row, ADV_INJ_PHRASES.values())
    assert not absent, f"§4.4's F-ADV-INJ row no longer names {absent}"
    assert set(adv_inj.PAYLOAD_KINDS) == set(ADV_INJ_PHRASES)
    assert str(MIN_TWIN_PAIRS) in row, (
        f"§4.4 no longer says {MIN_TWIN_PAIRS} pairs; the corpus is sized against a number the "
        f"plan has changed"
    )


def test_the_f_hand_tier_c_rules_are_still_the_ones_section_4_4_states(repo_root):
    """The rules that keep real student work out of the repository, checked against their source.

    A relaxed rule here would not fail anything on its own — which is the point. Every other
    assertion about `F-HAND` in this suite reads `harness.corpora.hand`, so a rule quietly dropped
    from that tuple would take the checks with it and leave the suite green.
    """
    row = _corpus_row(repo_root, "F-HAND").lower()
    for rule in hand.TIER_C_RULES:
        # Compared on the distinctive opening rather than the whole phrase: §4.4 writes the last
        # rule with a backticked requirement id (`FR-CONF-08`) that the registry stores as plain
        # text, and a whole-phrase check would fail on the backticks alone.
        distinctive = rule.split("(")[0].strip().lower()[:40]
        assert distinctive in row, (
            f"§4.4's F-HAND row no longer states {rule!r}. This is the rule set that keeps "
            f"consented real student work out of the repository; a relaxation here is a policy "
            f"change, not a rewording."
        )
    assert "scanned handwriting" in row, (
        f"§4.4's F-HAND row no longer describes the corpus as scanned handwriting, so "
        f"harness.corpora.hand.{hand.REAL_MEDIA_KIND!r} names a medium the plan has stopped "
        f"asking for"
    )


def test_the_frozen_set_bounds_agree_with_the_conformance_clause_suites(repo_root):
    """One number, two suites. TS-02 and TS-75 must not disagree about what 30-50 means.

    Duplicated constants are fine as long as they cannot drift apart; this is the assertion that
    makes them cannot. Also checked against the plan itself, so both copies moving together in the
    wrong direction is still caught.
    """
    assert (FROZEN_MIN, FROZEN_MAX) == (CORPUS_MIN, CORPUS_MAX), (
        f"tests.support.adversarial says {FROZEN_MIN}-{FROZEN_MAX} and "
        f"tests.support.conform_vocabulary says {CORPUS_MIN}-{CORPUS_MAX}"
    )
    row = _corpus_row(repo_root, "F-FROZEN")
    assert f"{FROZEN_MIN}–{FROZEN_MAX}" in row or f"{FROZEN_MIN}-{FROZEN_MAX}" in row, (
        f"§4.4's F-FROZEN row no longer says {FROZEN_MIN}-{FROZEN_MAX}: {row!r}"
    )


@pytest.mark.parametrize("kind", adv_inj.PAYLOAD_KINDS)
def test_each_payload_kind_has_a_distinct_wording_for_every_pair_it_generates(kind):
    """Four payloads per kind, and no two the same.

    Not drift detection — a generator check that belongs here because it is about the corpus
    rather than about a requirement. A `_payloads_for` that returned the same string for every
    index would leave `ADV-02`'s paraphrase-resistance claim resting on one string, and the
    composition assertions upstream count pairs rather than distinct payloads, so nothing else
    would notice.
    """
    wordings = [
        adv_inj._payloads_for(kind, index).lines for index in range(adv_inj.PAIRS_PER_KIND)
    ]
    assert len(set(wordings)) == len(wordings), (
        f"{kind} repeats a payload wording across its {adv_inj.PAIRS_PER_KIND} pairs; a defence "
        f"that memorized one string would pass the whole kind"
    )
