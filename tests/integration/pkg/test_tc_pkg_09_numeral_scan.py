"""The package-side half of the numeral prohibition (`M-PKG`).

Case `TC-PKG-09` (`FR-PKG-03`, `FR-JUDGE-03`, P0, artifact assertion), test plan §5.4.
Issue #32 (TS-11).

RISK-04: a numeral reaches a judge — through a band descriptor, an exemplar, or a
`max_points` field — and judges anchor on it, compressing band assignment toward the
middle. `TC-JUDGE-08` is the prompt-side half (it needs `M-JUDGE`, which does not exist
yet); this file is the package-side half, which is checkable today: **no stored band
descriptor or exemplar payload reachable by `M-JUDGE` carries a numeral denoting a
score, `points`, `max_points` or a scale.**

Isolation — the plan's row says rung 0; the case's subject is **stored rows and blob
payloads**, which no pure surface can hold, so it runs one rung up against a real Tier P
file and the real blob directory — the same substitution every catalog behaviour test in
this directory makes. Disclosed here rather than silently taken.

The scan's discrimination boundary (the same discipline `TC-JUDGE-08`'s block form
demands — "a scan that also flags the legitimate numeral is a failing test"):

- **Rubric surfaces** (band labels and descriptors): a *standalone* numeral is refused
  wholesale. `RISK-04` names the band descriptor itself as the anchor risk — whatever a
  rubric descriptor's numeral counts, a judge reads it as a score. Digits attached to an
  identifier token (`b0`, `Q-4`) are not standalone and survive; a label that *is* a
  numeral (`"3"`) is the block form's named catch.
- **Exemplar payloads** (student work): only a numeral in mark vocabulary (`2 points`,
  `out of 4`, `10%`) is refused. Bare content numerals — a student calculating
  `"12 kg"` — are ordinary evidence and must survive, or the scan is untargeted and
  will be disabled the first time it fires on real content.
"""

from __future__ import annotations

import re

import pytest

from aeh.pkg import PackageCatalog, PackageDraft
from aeh.store import open_store
from tests.support.store_api import statement

pytestmark = pytest.mark.integration

ISSUE = "#32"

#: A *standalone* numeral — not a digit inside an identifier token (`b0`, `Q-4`, `v2`).
#: The lookarounds exclude letters AND the hyphen, so both the `b` of `b0` and the `-4`
#: of `Q-4` keep their digits out of the scan; a numeral between separators (`(3 out`,
#: `10%`) still matches.
_NUMERAL = re.compile(r"(?<![A-Za-z0-9-])\d+(?:[.,]\d+)?(?![A-Za-z0-9-])")

#: The mark vocabulary a content numeral is refused beside. `TC-JUDGE-08`'s pattern:
#: "a numeral adjacent to a mark word, 'out of', a percentage".
_MARK_CONTEXT = re.compile(
    r"points?\b|marks?\b|score\b|scale\b|maximum\b|max\b|out\s+of|%|/",
    re.IGNORECASE,
)

#: How much surrounding text counts as "adjacent" for the mark-context test.
_WINDOW = 24


def _offending_numeral(text: str, *, rubric: bool) -> str | None:
    """The first numeral in `text` the prohibition refuses, or `None`.

    On a rubric surface every standalone numeral is score-denoting; in exemplar content
    only a numeral beside mark vocabulary is."""
    for match in _NUMERAL.finditer(text):
        if rubric:
            return match.group()
        window = text[max(0, match.start() - _WINDOW): match.end() + _WINDOW]
        if _MARK_CONTEXT.search(window):
            return match.group()
    return None


def _published_package_with_legitimate_content_numerals(tmp_data_dir):
    """The block form's fixture discipline: a published package whose criteria carry
    `max_points`, whose bands carry points, and whose exemplar text legitimately
    contains numerals — so the scan must discriminate rather than ban all digits."""
    store = open_store(tmp_data_dir)
    handle = store.package("pkg-09")
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO package (package_id, created_at) "
            "VALUES ('pkg-09', '2026-01-01')", issue=ISSUE))
    catalog = PackageCatalog(handle, package_id="pkg-09", blobs=store.blobs())
    v = catalog.create_version(None, PackageDraft(title="numeral-scan fixture"))
    catalog.add_criterion(v, "CRIT-MCQ", question_id="Q-1", kind="mcq",
                          max_points=4.0, band_count=2)
    catalog.add_band(v, "CRIT-MCQ", 0, "b0", 0.0, "emerging — partial evidence")
    catalog.add_band(v, "CRIT-MCQ", 1, "b1", 4.0, "secure — consistent evidence")
    catalog.add_criterion(v, "CRIT-OPEN", question_id="Q-2", kind="open",
                          max_points=3.0, band_count=4)
    for ordinal, descriptor in enumerate(
            ("emerging: names a force", "developing: links force to motion",
             "secure: quantifies the relation", "exemplary: reasons about limits")):
        catalog.add_band(v, "CRIT-OPEN", ordinal, f"b{ordinal}", float(ordinal),
                         descriptor)
    # The legitimate content numeral: ordinary student work, digits and all.
    blob_hash = store.blobs().put(
        b"The sample masses 12 kg and the ramp is 3.5 m long; "
        b"the trolley covers the distance in 4 s.")
    catalog.add_exemplar(v, "ex-content", "CRIT-MCQ", "b0", blob_hash=blob_hash)
    catalog.add_exemplar(v, "ex-text-only", "CRIT-OPEN", "b1")  # no payload to scan
    catalog.publish(v, "approver")
    return store, handle, catalog, v


def test_tc_pkg_09_no_stored_rubric_or_payload_carries_a_score_numeral(tmp_data_dir):
    """`TC-PKG-09` — the artifact assertion over the **stored rows**: every band label
    and descriptor of the published package, and every exemplar payload its rows
    reference, is scanned; the scan must come back clean while the legitimate content
    numerals are demonstrably present in what it scanned.

    Both halves matter: a clean scan over a payload with no digits proves nothing, and
    a scan that flagged the digits would be the untargeted check the block form
    rejects."""
    store, handle, catalog, v = _published_package_with_legitimate_content_numerals(
        tmp_data_dir)

    band_rows = handle.query(statement(
        "SELECT criterion_id, ordinal, band, descriptor FROM band "
        "WHERE package_version_id = :v ORDER BY criterion_id, ordinal", issue=ISSUE),
        v=v)
    assert band_rows, "the fixture published no bands; the scan would be vacuous."
    for row in band_rows:
        for surface, text in (("label", row["band"]),
                              ("descriptor", row["descriptor"] or "")):
            assert _offending_numeral(text, rubric=True) is None, (
                f"TC-PKG-09: the {surface} {text!r} of criterion "
                f"{row['criterion_id']!r} carries a standalone numeral. RISK-04: a "
                "judge anchors on it and band assignment compresses toward the middle."
            )

    exemplar_rows = handle.query(statement(
        "SELECT exemplar_id, blob_hash FROM exemplar "
        "WHERE package_version_id = :v AND blob_hash IS NOT NULL", issue=ISSUE), v=v)
    scanned_payloads = []
    for row in exemplar_rows:
        payload = store.blobs().get(row["blob_hash"]).decode("utf-8")
        scanned_payloads.append(payload)
        assert _offending_numeral(payload, rubric=False) is None, (
            f"TC-PKG-09: exemplar {row['exemplar_id']!r} carries a numeral beside "
            "mark vocabulary — the anchor risk the package-side half of the "
            "prohibition exists for."
        )
    # The discrimination proof: the scanned payload really does contain bare numerals
    # ("12 kg", "3.5 m", "4 s") — the scan is clean because it refuses only
    # mark-adjacent numerals, not because it saw none.
    assert scanned_payloads and re.search(r"\d", scanned_payloads[0]), (
        "TC-PKG-09: the fixture's exemplar carries no numeral, so the clean scan "
        "proves nothing — the discrimination the case demands is untested."
    )
    store.close()


def test_tc_pkg_09_the_scan_catches_every_planted_violation(tmp_data_dir):
    """The adversarial cells, planted and caught — a scan that cannot flag the
    violation it exists for is decoration. Each cell is one the block form or its
    variants name: a numeric band label (`"3"`), a descriptor quoting a mark scheme
    (`"3 out of 4"`), a percentage, and an exemplar payload worth points."""
    store, handle, catalog, v = _published_package_with_legitimate_content_numerals(
        tmp_data_dir)
    planted = catalog.create_version(v, PackageDraft(title="adversarial cells"))
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO criterion (package_version_id, criterion_id, question_id, "
            "kind, max_points, scoring_model) VALUES (:v, 'ADV', 'Q-A', 'open', 4.0, "
            "'atomic')", issue=ISSUE), v=planted)
        for label, descriptor in (
            ("3", "a label that is itself a numeral"),
            ("b0", "secure work (3 out of 4)"),
            ("b1", "top 10% of responses"),
        ):
            tx.execute(statement(
                "INSERT INTO band (package_version_id, criterion_id, ordinal, band, "
                "points, descriptor) VALUES (:v, 'ADV', :o, :b, :p, :d)", issue=ISSUE),
                v=planted, o=int(label) if label.isdigit() else {"b0": 0, "b1": 1}[label],
                b=label, p=0.0, d=descriptor)
        points_blob = store.blobs().put(b"this response is worth 2 points")
        tx.execute(statement(
            "INSERT INTO exemplar (exemplar_id, package_version_id, criterion_id, "
            "band, blob_hash) VALUES ('ex-adv', :v, 'ADV', 'b0', :h)", issue=ISSUE),
            v=planted, h=points_blob)

    band_rows = handle.query(statement(
        "SELECT band, descriptor FROM band WHERE package_version_id = :v "
        "AND criterion_id = 'ADV' ORDER BY ordinal", issue=ISSUE), v=planted)
    caught = [
        _offending_numeral(row["band"], rubric=True)
        or _offending_numeral(row["descriptor"] or "", rubric=True)
        for row in band_rows
    ]
    assert all(cell is not None for cell in caught), (
        f"TC-PKG-09: the scan missed a planted rubric violation ({caught}) — a "
        "descriptor quoting a mark scheme or a numeric band label reached a judge "
        "unflagged."
    )
    payload = store.blobs().get(handle.query(statement(
        "SELECT blob_hash FROM exemplar WHERE exemplar_id = 'ex-adv'",
        issue=ISSUE))[0]["blob_hash"]).decode("utf-8")
    assert _offending_numeral(payload, rubric=False) == "2", (
        "TC-PKG-09: the scan missed an exemplar payload carrying its points value — "
        "the exact anchor RISK-04 describes."
    )
    store.close()
