"""`TC-CONFORM-02` — the corpus is synthetic or consented, and an unconsented cohort is refused.

Case: test plan §5.18, `FR-CONFORM-02`, `NFR-CONFORM-03`. Oracle: **exact refusal plus manifest
assertion**.

    | The suite pointed at a cohort whose `consent_class` is `real` | Refuses to run; the corpus
    | itself contains only synthetic or consented work, asserted over the fixture manifest |

Two halves, and they are enforced in two different places — which is what `CT-CONFORM-10` says in
so many words: *"the corpus contains only synthetic or consented work, and the suite refuses to
run against a cohort not so flagged... the `M-CONF` consent gate is what enforces the boundary."*

* **The manifest half** is asserted here over every committed corpus. This is the assertion the
  case's oracle names, and it is about `fixtures/`, which is TS-02's deliverable.
* **The refusal** is asserted here against `M-CONF`, which is the module that owns it and which is
  real today. Refusing an unconsented cohort is not something `M-CONFORM` implements — a second
  copy of the rule is what `CT-CONFORM-10` forbids, because two consent checks drift and the one
  that drifts open is the one nobody is watching (RISK-10).

**Not duplicated here:** the suite-level sweep — `build_conformance_suite().run(...)` against four
unflagged consent classes — is TS-75's `TC-CONFORM-C10`
(`tests/contract/conform/test_ct_conform_corpus.py`), already written and correctly red on #133.
Writing it a second time under a different case id would double the maintenance and halve the
signal. The overlap is reported on the PR rather than worked around quietly.

`consented` is deliberately **not** an acceptable value for a *committed* corpus. `NFR-CONFORM-03`
permits the fixture corpus to hold consented work, and §4.4's PII rules make `F-HAND` the only
consented corpus and forbid committing it — so a committed file declaring `consented` is either
mislabelled synthetic data or real student work in the repository. Both are findings.
"""

from __future__ import annotations

import json

import pytest

from tests.support import corpora
from tests.support.adversarial import (
    COMMITTABLE_CONSENT_CLASSES,
    COMMITTED_CONSENT_DECLARING_CORPORA,
    COMMITTED_MEDIA_DECLARING_CORPORA,
    COMMITTED_SCAN_CORPORA,
    COMMITTED_SUBMISSION_CORPORA,
)
from tests.support.conf_builders import hosted_cfg

CASE = "TC-CONFORM-02"


@pytest.mark.parametrize("corpus_name", COMMITTED_CONSENT_DECLARING_CORPORA)
def test_tc_conform_02_every_committed_fixture_declares_a_permitted_consent_class(corpus_name):
    """The manifest assertion, per corpus and per member.

    Parametrized rather than looped, so a regression names **which** corpus stopped being
    synthetic instead of reporting one failure for the first offender in an arbitrary order.
    """
    corpus = corpora.load(corpus_name)

    assert corpus.manifest.get("consent_class") in COMMITTABLE_CONSENT_CLASSES, (
        f"{corpus_name}'s manifest declares consent_class "
        f"{corpus.manifest.get('consent_class')!r}; a committed corpus may only be "
        f"{sorted(COMMITTABLE_CONSENT_CLASSES)}"
    )

    offenders = {
        m.id: m.attributes.get("consent_class")
        for m in corpus.members
        if m.attributes.get("consent_class") not in COMMITTABLE_CONSENT_CLASSES
    }
    assert not offenders, (
        f"{corpus_name} members declare a consent class a committed corpus may not carry: "
        f"{offenders}. NFR-CONFORM-03 permits transmitting the corpus to a remote provider "
        f"*because* of this restriction (R31)."
    )

    # The corpus- and member-level declarations must also agree. A manifest header saying
    # `synthetic` over members that say nothing at all would pass a header-only check and hand
    # every downstream consent decision a corpus whose provenance is per-member unknown.
    assert all(m.attributes.get("consent_class") for m in corpus.members), (
        f"{corpus_name} has members with no consent_class of their own"
    )


def test_tc_conform_02_the_documents_themselves_declare_their_consent_class():
    """Asserted in the *bytes*, not only in the manifest.

    A manifest is metadata a build script writes; the document is what a provider would actually
    be sent. If the two could disagree, a corpus could be relabelled synthetic without a single
    submission changing — which is the relabelling `FR-CONF-08`'s audit record exists to make
    impossible on the other side of the boundary.
    """
    for corpus_name in COMMITTED_MEDIA_DECLARING_CORPORA:
        corpus = corpora.load(corpus_name)
        for member in corpus.members:
            declared = member.attributes["consent_class"]
            assert f"consent_class: {declared}" in member.text(), (
                f"{corpus_name}/{member.id}: the manifest says {declared!r} and the document "
                f"does not say so itself"
            )


@pytest.mark.parametrize("corpus_name", COMMITTED_SCAN_CORPORA)
def test_tc_conform_02_the_scans_declare_their_consent_class_in_the_pdf_bytes(corpus_name):
    """The bytes-level half of the consent assertion, for the corpus whose members are PDFs.

    `test_tc_conform_02_the_documents_themselves_declare_their_consent_class` asserts the
    declaration through `member.text()` — strict UTF-8, and rightly so for Markdown corpora. The
    scans (#133) are PDFs, so their declaration is asserted where a provider would find it: in
    the raw bytes (the form header is uncompressed text operators, so the line survives any
    parser) and in the text a PDF library extracts. The handwritten pages carry no text layer at
    all — the student's work is pixels — so the declaration rides on the printed form header and
    the manifest, and nothing claims the handwriting itself said anything.
    """
    import pypdf

    corpus = corpora.load(corpus_name)
    assert corpus.manifest["consent_class"] in COMMITTABLE_CONSENT_CLASSES
    assert corpus.manifest["rendering"] == "synthetic_scan", (
        f"{corpus_name}'s members declare the real-medium vocabulary; the manifest must say the "
        f"rendering is synthetic or the medium claim is a mislabel (FR-CONFORM-03, R37)"
    )
    for member in corpus.members:
        declared = member.attributes["consent_class"]
        line = f"consent_class: {declared}".encode("ascii")
        raw = member.path.read_bytes()
        assert line in raw, (
            f"{corpus_name}/{member.id}: the manifest says {declared!r} and the PDF's raw bytes "
            f"do not carry the declaration"
        )
        document = pypdf.PdfReader(member.path.open("rb"))
        extracted = "\n".join(page.extract_text() or "" for page in document.pages)
        assert f"consent_class: {declared}" in extracted, (
            f"{corpus_name}/{member.id}: the declaration is in the bytes but not in the text a "
            f"parser reads, so it would not survive a re-render"
        )


def test_tc_conform_02_no_committed_fixture_carries_a_name_shaped_field():
    """§4.4's PII rule, stated as a check: *"`student_ref` is present and no name-shaped field
    exists"* (`FR-STORE-12`).

    The `F-ADV-INJ` payloads are the interesting case: an injection is free text, and an author
    reaching for realism could put a name in one. The sweep covers them like everything else.
    """
    forbidden = ("student_name", "full_name", "first_name", "last_name", "surname", "pupil_name")
    for corpus_name in COMMITTED_SUBMISSION_CORPORA:
        corpus = corpora.load(corpus_name)
        for member in corpus.members:
            assert member.attributes.get("student_ref"), f"{member.id} carries no student_ref"
            text = member.text().lower()
            hits = [field for field in forbidden if field in text]
            assert not hits, f"{corpus_name}/{member.id} carries name-shaped field(s) {hits}"


@pytest.mark.parametrize("corpus_name", COMMITTED_SCAN_CORPORA)
def test_tc_conform_02_the_scan_submissions_carry_a_student_ref_and_no_name_shaped_field(corpus_name):
    """§4.4's PII rule over the scans, where `member.text()` cannot go.

    Same rule as the text sweep above, different reading surface: the student's work is pixels,
    so the checkable text is the printed form header, extracted the way a PDF library would.
    `student_ref` is asserted from the manifest attribute — the field the ingest identity gate
    would read — rather than from the pixels, which carry no text layer to read it from.
    """
    import pypdf

    forbidden = ("student_name", "full_name", "first_name", "last_name", "surname", "pupil_name")
    corpus = corpora.load(corpus_name)
    for member in corpus.members:
        assert member.attributes.get("student_ref"), f"{member.id} carries no student_ref"
        document = pypdf.PdfReader(member.path.open("rb"))
        extracted = "\n".join(page.extract_text() or "" for page in document.pages).lower()
        hits = [field for field in forbidden if field in extracted]
        assert not hits, (
            f"{corpus_name}/{member.id} carries name-shaped field(s) {hits} in its printable "
            f"text (FR-STORE-12, §4.4)"
        )


def test_tc_conform_02_a_run_against_an_unconsented_cohort_is_refused_by_the_consent_gate():
    """The exact refusal, at the module that owns it (`CT-CONFORM-10`, `FR-CONF-08`).

    Green today: `M-CONF` is real. The paired positive assertion matters as much as the refusal —
    without it this test would pass against a `resolve_run_config` that raised for every cohort,
    which refuses the unconsented one for a reason that has nothing to do with consent.
    """
    from aeh.conf import CohortRef, ConsentGateError, resolve_run_config

    with pytest.raises(ConsentGateError):
        resolve_run_config(
            hosted_cfg(), CohortRef(cohort_id="c-2026-real", consent_class="real")
        )

    synthetic = CohortRef(cohort_id="c-conform-fixtures", consent_class="synthetic")
    assert resolve_run_config(hosted_cfg(), synthetic) is not None, (
        "a synthetic cohort was refused too, so the refusal above is not the consent gate"
    )


def test_tc_conform_02_the_f_hand_registry_is_a_declaration_and_carries_no_student_work():
    """The one consented corpus, and the check that it is still only a declaration.

    `NFR-CONFORM-03` allows consented work in the fixture corpus; §4.4's Tier C rules forbid
    committing it. Both hold only if the committed `F-HAND` artifact stays a description of a
    corpus rather than becoming one.
    """
    registry = corpora.hand_registry()
    assert registry["committed"] is False
    assert registry["consent_class"] == "consented"

    raw = json.dumps(registry)
    assert "student_ref" not in raw and "submissions" not in raw, (
        "the F-HAND registry has acquired submission-shaped content. It is a declaration; "
        "§4.4 makes it the only corpus containing real student work and forbids committing it."
    )

    hand_dir = corpora.CORPUS_ROOT / "F-HAND"
    stray = sorted(p.name for p in hand_dir.iterdir() if p.name != "registry.json")
    assert not stray, (
        f"fixtures/F-HAND/ contains {stray}. Nothing but the registry may ever be committed "
        f"there — §4.4: 'never committed, never exported'."
    )
