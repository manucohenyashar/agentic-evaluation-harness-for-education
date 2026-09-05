"""`TC-CONFORM-09`, the corpus half — the adversarial tier is a tier that can prove something.

Case: test plan §5.18, `FR-CONFORM-09`, `NFR-SYS-13`, R73/R74. Oracle: **differential against
benign twins plus exact call count** — and the differential is in
`tests/integration/conform/test_tc_conform_09_adversarial_tier.py`, correctly red on #134.

This file asserts what has to be true of `F-ADV-INJ` and `F-ADV-PDF` *before* that differential
means anything. `CT-CONFORM-09` states why the split exists:

    *"The paired design is what makes the assertion meaningful — an unpaired injection test proves
    nothing about whether the injection mattered."*

An unpaired tier does not weaken the differential; it makes it **meaningless while leaving it
green**. The same holds for the two properties nobody would think to check: that the twins really
are identical but for the payload, and that a "forged" citation quotes text that is genuinely
absent from the document. A forged citation that happened to quote real text would verify
correctly, and `TC-INTEG-13`'s *"every forged citation fails verification"* would pass against a
system that verifies nothing.

Green, because the corpora are TS-02's deliverable. See
`tests/artifact/test_tc_conform_01_frozen_fixture_set.py` on why the case's rung 2 is neither
achievable nor meaningful for a composition assertion over committed bytes.
"""

from __future__ import annotations

from tests.support import corpora
from tests.support.adversarial import MIN_TWIN_PAIRS
from tests.support.conform_vocabulary import INJECTION_PAYLOAD_KINDS, MALICIOUS_PDF_KINDS
from tests.support.impl import require_path

from harness.corpora import adv_inj, adv_pdf

CASE = "TC-CONFORM-09"


# --- F-ADV-INJ: the twin pairs ----------------------------------------------------------------


def test_tc_conform_09_the_injection_tier_holds_at_least_twenty_pairs_across_all_five_kinds():
    """§4.4's floor and its five payload kinds, with the requirement's three asserted as a subset.

    Subset, not equality. `FR-CONFORM-09` enumerates three kinds and §4.4 adds role claims and
    encoded/translated variants, which `ADV-02` confirms by name. An equality against the
    requirement's list would forbid the corpus from carrying the two extra shapes; an equality
    against the corpus would let somebody drop `forged_citation` from the requirement and stay
    green. Both directions are checked, each against the list it belongs to.
    """
    pairs = corpora.injection_pairs()
    assert len(pairs) >= MIN_TWIN_PAIRS, (
        f"F-ADV-INJ holds {len(pairs)} twin pairs; §4.4 requires at least {MIN_TWIN_PAIRS}"
    )

    kinds = {injected.attributes["injection_kind"] for _, injected in pairs}
    assert kinds == set(adv_inj.PAYLOAD_KINDS), (
        f"the tier covers {sorted(kinds)}; §4.4 names {sorted(adv_inj.PAYLOAD_KINDS)}. A missing "
        f"shape is an attack nobody measured."
    )
    assert INJECTION_PAYLOAD_KINDS <= kinds, (
        f"FR-CONFORM-09 names {sorted(INJECTION_PAYLOAD_KINDS)} and the corpus is missing "
        f"{sorted(INJECTION_PAYLOAD_KINDS - kinds)}"
    )

    # More than one pair per kind: a defence that memorized one payload string would pass a tier
    # of one, and ADV-02's residual risk is precisely the nudge that survives paraphrase.
    for kind in adv_inj.PAYLOAD_KINDS:
        count = sum(1 for _, i in pairs if i.attributes["injection_kind"] == kind)
        assert count >= 2, f"only {count} pair(s) carry a {kind} payload"


def test_tc_conform_09_every_injection_has_a_benign_twin_and_no_twin_is_itself_an_injection():
    """The pairing, and the half of it that a naive check misses.

    A pair of two injections satisfies "every injection has a twin" and compares an attack to an
    attack, which produces a clean equality and measures nothing.
    """
    corpus = corpora.load("F-ADV-INJ")
    by_id = {m.id: m for m in corpus.members}

    injections = [m for m in corpus.members if m.attributes["injection_kind"] is not None]
    assert injections, "F-ADV-INJ has no adversarial members at all (FR-CONFORM-09, R73)"

    for member in injections:
        twin = by_id.get(member.attributes["twin_id"])
        assert twin is not None, f"{member.id}'s twin is not in the corpus"
        assert twin.attributes["injection_kind"] is None, (
            f"{member.id}'s twin {twin.id} is itself an injection; the pair compares an attack "
            f"to an attack"
        )
        assert twin.attributes["twin_id"] == member.id, (
            f"{twin.id} does not point back at {member.id}; the pairing is not symmetric, so a "
            f"case iterating from the benign side would silently cover a different set"
        )
        assert twin.attributes["pair_id"] == member.attributes["pair_id"]


def test_tc_conform_09_each_pair_is_identical_but_for_the_payload():
    """§4.4's phrase, reconstructed rather than inspected.

    *"One benign twin identical in content but for the payload."* This is the property the whole
    differential rests on, and it is the one that erodes quietly: two documents written to be
    similar drift into two documents that are merely alike, and the differential then measures
    the drift instead of the payload.

    So the benign page is rebuilt from the injected one by truncating at the recorded
    `payload_line`, and compared byte for byte. Truncating rather than searching for the payload
    text: a search-and-remove check would pass against a pair whose payload was the empty string
    — two identical documents wearing a `twin_id` — which is the degenerate corpus this assertion
    must not accept.

    **And the tail is asserted too**, which is the half review found missing. Truncation alone
    reads the *document*; the non-empty check reads the *manifest*; and nothing made the two meet.
    A generator that stopped splicing the payload — or spliced innocuous prose of the same line
    count while the manifest went on declaring a band-forcing directive — produced twenty pairs of
    identical documents, passed every assertion in this file, passed `--check` after a rebuild,
    and would then have made the integration differential green by comparing each submission to
    itself. Measured, not theorised. The two halves are one assertion now: the lines after
    `payload_line` must be exactly the payload the manifest declares.
    """
    pairs = corpora.injection_pairs()
    assert pairs, "F-ADV-INJ yielded no pairs, so every assertion below would hold vacuously"

    for benign, injected in pairs:
        benign_pages = benign.pages()
        injected_pages = injected.pages()
        assert len(benign_pages) == len(injected_pages), (
            f"{injected.id} has {len(injected_pages)} pages and its twin has "
            f"{len(benign_pages)}"
        )

        assert corpora.benign_page_of(injected) == benign_pages[0], (
            f"{injected.id} is not its twin {benign.id} plus a payload. Removing the payload "
            f"block at line {injected.attributes['payload_line']} does not reproduce the benign "
            f"page, so a band difference between the two would not be attributable to the "
            f"injection (CT-CONFORM-09)."
        )
        assert injected_pages[1:] == benign_pages[1:], (
            f"{injected.id} differs from {benign.id} on a page that carries no payload"
        )

        # The other direction: what the injected document carries past `payload_line` is exactly
        # what the manifest says it carries. Positional, so it cannot be satisfied by a payload
        # that appears somewhere else in the document, and by equality rather than containment,
        # so extra lines are caught as well as missing ones.
        declared = injected.attributes["payload_lines"]
        assert declared and any(line.strip() for line in declared), (
            f"{injected.id} declares an empty payload, so the pair is two identical documents "
            f"wearing a twin_id"
        )
        tail = injected_pages[0].split("\n")[injected.attributes["payload_line"]:]
        assert tail == ["", *declared], (
            f"{injected.id} declares payload {declared} and its document carries {tail!r} at "
            f"line {injected.attributes['payload_line']}. The manifest and the bytes disagree "
            f"about what the attack is, so the differential downstream would be comparing a "
            f"submission to a near-copy of itself and reporting injection resistance."
        )

        # Same reference score on both halves. A differential between two submissions that were
        # supposed to score differently measures the corpus rather than the payload.
        assert injected.attributes["reference_bands"] == benign.attributes["reference_bands"], (
            f"{injected.id} and {benign.id} carry different reference bands"
        )
        assert injected.attributes["reference_points"] == benign.attributes["reference_points"]


def test_tc_conform_09_every_forged_citation_quotes_text_that_is_absent_from_the_document():
    """The property that makes `forged` mean something.

    `TC-INTEG-13` asserts *"every forged citation fails verification"*. If a payload's quotation
    happened to appear in the submission, verification would correctly succeed and that case would
    pass against a system doing no verification at all. So the corpus has to guarantee the
    quotation is not there — asserted against **both** halves of the pair, since the injected
    document contains the payload itself and only the rest of it counts as the source text.

    The *present* direction is asserted first, and it is not ceremony: an absence check alone is
    satisfied by a quotation that appears nowhere at all, which is what a corpus whose payloads
    stopped being spliced looks like. The pair of assertions is what makes "forged" mean *claimed
    in the document, absent from it* rather than merely *absent*.
    """
    forged = [
        (b, i)
        for b, i in corpora.injection_pairs()
        if i.attributes["injection_kind"] == "forged_citation"
    ]
    assert forged, "no forged-citation pairs, so this assertion would pass vacuously"

    for benign, injected in forged:
        quote = injected.attributes["forged_quote"]
        assert quote, f"{injected.id} is a forged_citation pair and names no quote"
        assert quote in injected.text(), (
            f"{injected.id}'s forged quotation does not appear in its own document. A citation "
            f"the submission never makes cannot fail verification, so TC-INTEG-13 would have "
            f"nothing to reject."
        )
        assert quote not in benign.text(), (
            f"{injected.id}'s 'forged' quotation appears verbatim in its benign twin, so it is "
            f"not forged: span verification would correctly succeed and TC-INTEG-13 would pass "
            f"against a system that verifies nothing"
        )
        # And in the injected document it appears only inside the payload block.
        source = corpora.benign_page_of(injected) + "\n".join(injected.pages()[1:])
        assert quote not in source, (
            f"{injected.id}'s quotation appears in its own document outside the payload"
        )


# --- F-ADV-PDF: the malicious and malformed constructs -------------------------------------------


def test_tc_conform_09_the_pdf_tier_covers_every_construct_section_4_4_names():
    """Fourteen constructs, with `FR-CONFORM-09`'s four asserted as a subset of them."""
    manifest = corpora.adv_pdf_manifest()
    constructs = {row["construct"] for row in manifest["submissions"]}

    assert constructs == set(adv_pdf.SECTION_4_4_CONSTRUCTS), (
        f"the tier covers {sorted(constructs)}; §4.4 names "
        f"{sorted(adv_pdf.SECTION_4_4_CONSTRUCTS)}"
    )
    assert len(manifest["submissions"]) == len(adv_pdf.SECTION_4_4_CONSTRUCTS), (
        "two entries share a construct, so one of §4.4's fourteen is covered twice and another "
        "not at all"
    )

    kinds = {row["threat_kind"] for row in manifest["submissions"]}
    assert MALICIOUS_PDF_KINDS <= kinds, (
        f"FR-CONFORM-09 names {sorted(MALICIOUS_PDF_KINDS)} and the corpus is missing "
        f"{sorted(MALICIOUS_PDF_KINDS - kinds)} (R74)"
    )


def test_tc_conform_09_every_pdf_construct_declares_quarantine_at_v0_and_zero_model_calls():
    """`FR-CONFORM-09`'s outcome, declared once per construct rather than negotiated per fixture.

    The count is **exact**, and the manifest says so: *"only one model call"* is the same failure
    as a hundred. A tier whose expected outcome varied by construct would invite an
    implementation to settle with the easy ones.
    """
    manifest = corpora.adv_pdf_manifest()
    assert len(manifest["submissions"]) == len(adv_pdf.SECTION_4_4_CONSTRUCTS), (
        "F-ADV-PDF declares the wrong number of constructs, so the sweep below would run over "
        "the wrong set — or, at zero, over none"
    )
    for row in manifest["submissions"]:
        assert row["expected_outcome"] == adv_pdf.EXPECTED_OUTCOME, row["id"]
        assert row["quarantine_gate"] == adv_pdf.QUARANTINE_GATE, (
            f"{row['id']} expects quarantine at {row['quarantine_gate']!r} rather than "
            f"{adv_pdf.QUARANTINE_GATE}; a threat that gets past the first gate has already "
            f"been parsed (CT-INGEST-13, NFR-INGEST-08)"
        )
        assert row["expected_model_calls"] == 0, row["id"]
        assert row["rationale"].strip(), (
            f"{row['id']} states no rationale, so a reader cannot tell what it is a fixture *of*"
        )


def test_tc_conform_09_the_pdf_constructs_regenerate_to_exactly_their_declared_digests(tmp_path):
    """§4.8's entry criterion: *"generated and reproducible from committed scripts."*

    `materialize_adv_pdfs` verifies each construct against the manifest as it writes it, so the
    call itself is the assertion; what is checked here is that it wrote **all fourteen** and that
    each file is really on disk. Without the count, a helper that silently generated none would
    pass this test by raising nothing.
    """
    written = corpora.materialize_adv_pdfs(tmp_path / "pdfs")

    declared = {row["id"] for row in corpora.adv_pdf_manifest()["submissions"]}
    # Both sides counted before they are compared: `set(written) == declared` holds when both are
    # empty, which is what a helper that silently generated nothing against a manifest that
    # declared nothing would look like.
    assert len(written) == len(adv_pdf.SECTION_4_4_CONSTRUCTS), (
        f"materialized {len(written)} construct(s); §4.4 names "
        f"{len(adv_pdf.SECTION_4_4_CONSTRUCTS)}"
    )
    assert set(written) == declared, (
        f"materialized {sorted(written)}; the manifest declares {sorted(declared)}"
    )
    for construct_id, path in written.items():
        assert path.is_file() and path.stat().st_size > 0, f"{construct_id} wrote nothing"
        assert path.read_bytes().startswith(b"%PDF-"), (
            f"{construct_id} is not a PDF at all. Every construct here must be parseable up to "
            f"the point it is supposed to fail, or the fixture proves that ingestion rejects "
            f"garbage rather than that it neutralizes the construct it names."
        )


def test_tc_conform_09_no_malicious_pdf_is_committed_to_the_repository():
    """§4.7: *"`F-ADV-PDF` is generated, not committed as binaries."*

    Asserted as a property of the tree rather than trusted to the build script, because this is a
    rule about what a teacher's clone contains and the cheapest way to break it is a well-meaning
    `build()` that starts writing the files out.
    """
    root = require_path(
        corpora.CORPUS_ROOT / "F-ADV-PDF", "the F-ADV-PDF directory", issue="#3"
    )
    committed = sorted(p.name for p in root.rglob("*") if p.is_file())
    assert committed == ["manifest.json"], (
        f"fixtures/F-ADV-PDF/ contains {committed}. §4.7 keeps the binaries out of the "
        f"repository; the manifest's digests are what make the corpus reproducible without them."
    )

    manifest = corpora.adv_pdf_manifest()
    assert manifest["committed_bytes"] is False, (
        "the manifest no longer declares that its bytes are uncommitted, so a reader finding no "
        "files would think the corpus was lost rather than generated"
    )
    assert manifest["set_content_hash"] and manifest["fixture_set_id"].startswith("F-ADV-PDF@"), (
        "F-ADV-PDF is not content-addressed. NFR-CONFORM-01 makes the fixture set citable, and a "
        "tier whose bytes are not committed is the one that most needs to be."
    )
