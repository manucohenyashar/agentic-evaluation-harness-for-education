"""`F-CONFORM` — the version-pinned fixture set the conformance suite measures with (#133).

`FR-CONFORM-01` requires 30-50 submissions spanning the score range including mid-range partial
credit; `FR-CONFORM-02/03/09` require consent declarations, real media, and an adversarial tier
with benign twins; `NFR-CONFORM-01` requires the set to be content-addressed and version-pinned.
This module is the **composition**: it selects members from the corpora TS-02 built and pins
the selection as one manifest, so the set a conformance result cites is data — reviewable,
reproducible, and stable across rebuilds — rather than a hardcoded list inside `aeh.conform`.

Manifest-only, like `F-ADV-PDF`
-------------------------------
The members' bytes live in their source corpora (`F-FROZEN`, `F-ADV-INJ`, `F-SCAN`, `F-ADV-PDF`)
and are hashed there; composing copies here would be a second copy of the bytes and a second
place to drift. Each entry therefore carries `source_corpus` + `source_path` and the source
member's `content_hash`, and the loader (`aeh.conform.load_fixture_set`) verifies every
file-backed entry against those bytes before the set is used — staleness is a refusal, not a
warning, because a conformance result measured against a corpus that changed between runs is
not a result.

Why these fifty
---------------
* **All 36 of `F-FROZEN`** — the held-out set already spans the score range including
  mid-range partial credit (`FR-CONFORM-01`, 1.0 to 38.0 of 39.0), and composing it in full
  rather than re-deriving a span means the conformance set and the frozen set can never
  disagree about what "spanning" means.
* **The three required injection kinds, both halves** — `band_forcing` (INJ-01),
  `forged_citation` (INJ-05) and `contract_breaking` (INJ-09) are the payload kinds
  `FR-CONFORM-09` names; each pair's benign twin rides along because an unpaired injection
  proves nothing about whether the injection mattered. The first pair per kind is selected, in
  pair order — the corpus holds the *differential*, not every payload TS-02 generated.
* **One construct per required PDF threat kind** — `embedded_javascript` (ADV-PDF-01),
  `launch_action` (ADV-PDF-04), `embedded_file` (ADV-PDF-05), `decompression_bomb`
  (ADV-PDF-09). These carry `reference_score 0.0` on purpose and say so:
  `reference_score_basis: quarantine_at_v0` records that a construct that must quarantine at
  V0 is never scored, so its floor label is a fact about the pipeline, not a pretence of
  partial credit.
* **All four of `F-SCAN`** — the real-medium tier (`FR-CONFORM-03`): scanned handwriting
  spanning legible to marginal, plus the mixed-format paper.

Version and pin
---------------
The manifest is `version: "1"` like every corpus (`CORPUS_VERSION`), and `load_fixture_set`
accepts the pin label `v1` for the same thing. A future composition is version `"2"` with a
new selection; the digest below is what makes this one the *same* set every time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from harness.corpora import adv_pdf, hand, reference_package
from harness.corpora.manifest import Manifest, ManifestEntry

CORPUS_NAME = "F-CONFORM"

#: The pin label the conformance suite's callers use (`load_fixture_set("v1")`), mapped to the
#: manifest version the corpora build writes. Stated here so the mapping is one fact in one
#: place rather than a convention every reader re-derives.
VERSION_LABEL = "v1"

#: The injection payload kinds `FR-CONFORM-09` requires the adversarial tier to cover, in the
#: order the clause names them. Selection takes the FIRST pair per kind from `F-ADV-INJ`.
REQUIRED_INJECTION_KINDS = ("band_forcing", "forged_citation", "contract_breaking")

#: One construct per malicious-PDF threat kind `FR-CONFORM-09` (R74) requires, chosen from
#: `F-ADV-PDF`'s §4.4 order: the first construct manifesting each required `threat_kind`.
REQUIRED_PDF_CONSTRUCTS = ("ADV-PDF-01", "ADV-PDF-04", "ADV-PDF-05", "ADV-PDF-09")

#: Every entry's ceiling is the package's, so a reference score is always a fraction of the
#: same whole and CT-CONFORM-01's span is a comparison over one scale.
MAX_SCORE = reference_package.MAX_POINTS


def _submission_extra(row: Mapping, *, media_kind: str | None, legibility: str | None,
                      source_corpus: str, source_path: str) -> dict[str, object]:
    """The fields a conformance fixture carries, copied from its source row.

    Field-for-field the surface `aeh.conform.FixtureSubmission` reads: the known reference
    score and its scale, the media and legibility class, the injection pairing, the PDF
    threat, and the consent declaration. Absent adversarial roles are `null` rather than
    missing keys, so a loader can select on any of them without `.get()` guesses.
    """
    return {
        "submission_id": row["id"],
        "source_corpus": source_corpus,
        "source_path": source_path,
        "consent_class": row["consent_class"],
        "reference_score": row["reference_points"],
        "max_score": MAX_SCORE,
        "media_kind": media_kind,
        "legibility": legibility,
        "injection_kind": row.get("injection_kind"),
        "twin_id": row.get("twin_id"),
        "pdf_threat_kind": None,
    }


def _frozen_entries(fixtures_root: Path) -> tuple[ManifestEntry, ...]:
    rows = _manifest(fixtures_root, "F-FROZEN")["submissions"]
    return tuple(
        ManifestEntry(
            id=row["id"],
            path=f"F-FROZEN/{row['path']}",
            content_hash=row["content_hash"],
            extra=_submission_extra(
                row, media_kind=hand.SYNTHETIC_MEDIA_KIND, legibility=None,
                source_corpus="F-FROZEN", source_path=row["path"],
            ),
        )
        for row in rows
    )


def _injection_entries(fixtures_root: Path) -> tuple[ManifestEntry, ...]:
    """Both halves of the first twin pair per required injection kind, in pair order.

    The twin rides along in the same selection step rather than being looked up later, so a
    selection whose benign half went missing is a build-time failure instead of a suite that
    compares an injection to nothing.
    """
    rows = _manifest(fixtures_root, "F-ADV-INJ")["submissions"]
    by_id = {row["id"]: row for row in rows}
    out: list[ManifestEntry] = []
    for kind in REQUIRED_INJECTION_KINDS:
        injected = next(
            row for row in rows
            if row.get("injection_kind") == kind and row["variant"] == "injected"
        )
        twin = by_id[injected["twin_id"]]
        for row in (injected, twin):
            out.append(ManifestEntry(
                id=row["id"],
                path=f"F-ADV-INJ/{row['path']}",
                content_hash=row["content_hash"],
                extra=_submission_extra(
                    row, media_kind=hand.SYNTHETIC_MEDIA_KIND, legibility=None,
                    source_corpus="F-ADV-INJ", source_path=row["path"],
                ),
            ))
    return tuple(out)


def _pdf_entries() -> tuple[ManifestEntry, ...]:
    """One construct per required threat kind. Manifest-only: the bytes are generated.

    The floor reference score is deliberate and declared: a construct that must quarantine at
    V0 reaches no model call, so there is no scored work to label — `reference_score_basis`
    records that this is a fact about the pipeline, not a claimed 0/39 performance.
    """
    rows = {row["id"]: row for row in adv_pdf.manifest_entries()}
    out: list[ManifestEntry] = []
    for construct_id in REQUIRED_PDF_CONSTRUCTS:
        row = rows[construct_id]
        extra = {
            "submission_id": row["id"],
            "source_corpus": "F-ADV-PDF",
            "source_path": row["path"],
            "consent_class": row["consent_class"],
            # Floor on purpose, and labelled: quarantined at V0, never scored.
            "reference_score": 0.0,
            "reference_score_basis": "quarantine_at_v0",
            "max_score": MAX_SCORE,
            "media_kind": None,
            "legibility": None,
            "injection_kind": None,
            "twin_id": None,
            "pdf_threat_kind": row["threat_kind"],
        }
        out.append(ManifestEntry(
            id=row["id"],
            path=f"F-ADV-PDF/{row['path']}",
            content_hash=row["content_hash"],
            extra=extra,
        ))
    return tuple(out)


def _scan_entries(fixtures_root: Path) -> tuple[ManifestEntry, ...]:
    rows = _manifest(fixtures_root, "F-SCAN")["submissions"]
    return tuple(
        ManifestEntry(
            id=row["id"],
            path=f"F-SCAN/{row['path']}",
            content_hash=row["content_hash"],
            extra=_submission_extra(
                row, media_kind=row["media_kind"], legibility=row["legibility"],
                source_corpus="F-SCAN", source_path=row["path"],
            ),
        )
        for row in rows
    )


def _manifest(fixtures_root: Path, corpus: str) -> Mapping:
    path = fixtures_root / corpus / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def conform_entries(fixtures_root: Path) -> tuple[ManifestEntry, ...]:
    """The ordered selection: frozen set, injection pairs, PDF constructs, scans.

    Order is the composition's, stated in the module docstring — a conformance result names
    its fixtures by id, and the digest is order-sensitive (`set_content_hash`), so the order
    is part of the set's identity and is written down rather than emergent.
    """
    return (
        *_frozen_entries(fixtures_root),
        *_injection_entries(fixtures_root),
        *_pdf_entries(),
        *_scan_entries(fixtures_root),
    )


def conform_manifest(fixtures_root: Path) -> Manifest:
    """The `F-CONFORM` manifest as the builder writes it."""
    entries = conform_entries(fixtures_root)
    counts: dict[str, int] = {}
    for entry in entries:
        source = entry.extra["source_corpus"]
        counts[source] = counts.get(source, 0) + 1
    return Manifest(
        corpus=CORPUS_NAME,
        version=pinned_version(),
        seed=None,
        generator="harness.corpora.conform_set:conform_entries",
        description=(
            "The version-pinned fixture set the conformance suite measures with (FR-CONFORM-01, "
            "-02, -03, -09; NFR-CONFORM-01, #133): a composition of the committed corpora, "
            "spanning the score range with mid-range partial credit, carrying scanned "
            "handwriting and a mixed-format paper, and pairing every injection payload with a "
            "benign twin. Manifest-only: the bytes live in the source corpora and every entry "
            "verifies against them at load."
        ),
        entries=entries,
        extra={
            "package_id": reference_package.PACKAGE_ID,
            "package_version": reference_package.PACKAGE_VERSION,
            "consent_class": "synthetic",
            "version_label": VERSION_LABEL,
            "committed_bytes": False,
            "committed_bytes_reason": (
                "F-CONFORM is a selection, not a source: its members' bytes are committed and "
                "hashed by the corpora they come from, and copying them here would make every "
                "rebuild a second place to drift. aeh.conform.load_fixture_set verifies each "
                "file-backed entry against its source bytes at load."
            ),
            "composition_counts": counts,
            "max_points": MAX_SCORE,
            "injection_kinds": list(REQUIRED_INJECTION_KINDS),
            "pdf_threat_kinds": sorted({
                entry.extra["pdf_threat_kind"] for entry in entries
                if entry.extra["pdf_threat_kind"] is not None
            }),
        },
    )


def pinned_version() -> str:
    """The corpus version this composition is pinned to — the corpora build's `CORPUS_VERSION`.

    Imported at call time rather than at module load: `build.py` imports this module, so a
    top-level import in the other direction would be a cycle, and the pin is a build-time fact
    the composition reads rather than one it declares.
    """
    from harness.corpora.build import CORPUS_VERSION

    return CORPUS_VERSION