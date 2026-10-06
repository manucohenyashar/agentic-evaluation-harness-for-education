"""`F-NAMES` — the name-normalization / adversarial roster corpus (TS-143, issue #619).

Operator-requirements test plan §4 rule 4 and §8.2: synthetic, Tier C rules, hand-computed
expectations; the matcher is never trained on it. Q-O5 fixes the scope: Latin-script Phase 1 —
case folds, whitespace, diacritics (precomposed and decomposed), surname/given-name order, one
transliteration pair (`ß` ↔ `ss`, which is what full case-folding does and `str.lower()` does
not), and the collision pair: two distinct students whose names normalize identically.

Ten roster rows. Every row carries a declared `student_ref` (`S-0401` .. `S-0410`), so the cohort
"declared IDs" in FR-INGEST-39's sense and TC-INGEST-57 (b)'s secondary signal is available.

**The world.** `NamesWorld` is the rung-2 ingest world the ladder suite uses (real SQLite store,
real blob directory, scripted rasterizer and transcription provider — `tests/integration/ingest/
test_ingest_validation_ladder.py`'s `_Fixture`), with two additions: the roster rows carry
`full_name` (Cohort migration 33, `ingest_roster_names`, #620), and the provider double records
`repr()` of every prompt it is sent, so a sweep can read the assembled V3 request.

**Written ahead of #620.** Until the migration lands, `roster` has no `full_name` column; the world
probes for it and raises `NotImplementedYet` naming #620, so every case fails for that reason and
never on a distant `no such column`.

**Interface choices this corpus makes** (the design names none; disclosed in the PR):

* the paper's written name is the existing `Student: <name>` line the transcription prompt asks
  the model to copy (FR-INGEST-24's head, `markup.py`);
* a student ID written on the paper is a separate `Student ID: <id>` line (TC-INGEST-57 (b));
* the triage payload is the existing V3 finding, `... (candidates: [<refs>])` — the format
  TC-INGEST-27 already pins; a candidate is a `student_ref`.
"""

from __future__ import annotations

import ast
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aeh.conf import ModelRef
from aeh.ingest import Ingestor, PageImage, PdfSanitizer, ResidencySlot, SanitizeResult
from aeh.prov import Completion, SamplingParams
from aeh.store import open_store
from tests.support.impl import NotImplementedYet

ISSUE = "#620"
COHORT = "c-fnames"


@dataclass(frozen=True)
class Row:
    """One roster row: the stored name (NFC unless stated), its declared ref, and the
    hand-computed normalized key (case-folded, diacritics folded, tokens sorted)."""

    full_name: str
    student_ref: str
    hand_key: str


#: The ten rows. `hand_key` is written by hand, not computed — it is the oracle the corpus
#: self-check compares against, and what makes the collision pair a *stated* collision.
ROWS: tuple[Row, ...] = (
    Row("Amara Okafor", "S-0401", "amara okafor"),
    Row("Benito Ruiz", "S-0402", "benito ruiz"),
    Row("Chloé Lefèvre", "S-0403", "chloe lefevre"),
    Row("Jose Nunez", "S-0404", "jose nunez"),
    Row("Inès Haddad", "S-0405", "haddad ines"),
    Row("Dmitri Volkov", "S-0406", "dmitri volkov"),
    Row("Greta Strauß", "S-0407", "greta strauss"),
    Row("Zelda Quartermaine", "S-0408", "quartermaine zelda"),
    Row("Ana Silva", "S-0409", "ana silva"),     # the collision pair:
    Row("Ána Silva", "S-0410", "ana silva"),     # two students, one normalized name
)

REFS = tuple(row.student_ref for row in ROWS)
BY_REF = {row.student_ref: row for row in ROWS}
COLLISION_REFS = ("S-0409", "S-0410")


@dataclass(frozen=True)
class Arm:
    """One TC-INGEST-56 arm: what the paper's `Student:` line says, and whose paper it is."""

    arm_id: str
    written: str
    intended_ref: str


#: One arm per normalization. Every `written` differs from every stored `full_name` byte for
#: byte (the unnormalized comparison matches none — TC-INGEST-56's load-bearing half).
ARMS: tuple[Arm, ...] = (
    Arm("case", "AMARA OKAFOR", "S-0401"),
    Arm("whitespace", "Benito \t   Ruiz", "S-0402"),
    Arm("diacritics-dropped", "Chloe Lefevre", "S-0403"),
    Arm("diacritics-added", "José Núñez", "S-0404"),
    Arm("decomposed", unicodedata.normalize("NFD", "Inès Haddad"), "S-0405"),
    Arm("surname-first", "Volkov Dmitri", "S-0406"),
    Arm("transliteration", "Greta Strauss", "S-0407"),
    Arm("combined", "QUARTERMAINE   zelda", "S-0408"),
)

#: TC-INGEST-57's four decision-table cells.
COLLISION_WRITTEN = "ana  SILVA"          # (a)/(b): normalizes to both collision rows
UNMATCHED_WRITTEN = "Wilhelmina Fairbanks"  # (c): no row
PREFIX_WRITTEN = "Zelda"                  # (d): a prefix of row 8, not a match


def hand_fold(text: str) -> str:
    """The corpus self-check's own fold — used only to verify `hand_key`, never as the oracle
    for the system (the oracle is the hand-written key and the intended ref)."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(sorted(stripped.split()))


def name_variants() -> set[str]:
    """Every spelling of every roster name and every written arm, in NFC and NFD — what a
    boundary sweep must never find outside Tier C rows and the triage payload."""
    spellings = {row.full_name for row in ROWS}
    spellings |= {arm.written for arm in ARMS}
    spellings |= {COLLISION_WRITTEN, UNMATCHED_WRITTEN}
    out: set[str] = set()
    for spelling in spellings:
        collapsed = " ".join(spelling.split())
        for form in ("NFC", "NFD"):
            out.add(unicodedata.normalize(form, collapsed))
    return out


def find_names(text: str, names: set[str] | None = None) -> list[str]:
    """The name spellings `text` carries, compared case-insensitively over NFC-normalized,
    whitespace-collapsed text. The bare prefix `Zelda` is deliberately not in the set: a lone
    given name is not identifying, and including it would flag unrelated text."""
    hay = " ".join(unicodedata.normalize("NFC", text).casefold().split())
    hits = []
    for name in sorted(names if names is not None else name_variants()):
        needle = " ".join(unicodedata.normalize("NFC", name).casefold().split())
        if needle and needle in hay:
            hits.append(name)
    return hits


def scan_bytes_for_names(path: Path) -> list[str]:
    """Names present in a file's raw bytes, as UTF-8 in either normalization form."""
    blob = path.read_bytes()
    hits = []
    for name in sorted(name_variants()):
        for form in ("NFC", "NFD"):
            needle = unicodedata.normalize(form, name).encode("utf-8")
            if needle in blob:
                hits.append(name)
                break
    return hits


def non_cohort_files(root: Path) -> list[Path]:
    """Every database file of the data folder that is NOT a cohort (Tier C/R) file: the Tier D
    file and its WAL/journal siblings, and every package (Tier P) file."""
    cohorts = root / "cohorts"
    return sorted(p for p in root.rglob("*")
                  if p.is_file() and ".sqlite" in p.name and cohorts not in p.parents)


_CANDIDATES = re.compile(r"candidates:\s*(\[[^\]]*\])")


def triage_candidates(report: Any) -> list[str] | None:
    """The V3 finding's candidate list, parsed; None when the report carries no V3 finding with
    a candidate list."""
    for finding in report.detail.get("findings", ()):
        if finding.get("gate") != "v3":
            continue
        match = _CANDIDATES.search(str(finding.get("finding", "")))
        if match:
            return [str(item) for item in ast.literal_eval(match.group(1))]
    return None


def v3_findings(report: Any) -> str:
    return "\n".join(str(f.get("finding")) for f in report.detail.get("findings", ())
                     if f.get("gate") == "v3")


# -- the doubles (the ladder suite's shapes) -------------------------------------------------


class ThroughSanitizer(PdfSanitizer):
    def sanitize(self, pdf_bytes, *, strip=True, max_decompressed_bytes=None,
                 max_embedded_objects=None, deadline=None):
        return SanitizeResult(pdf_bytes=pdf_bytes)


class OnePageRasterizer:
    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        return [PageImage(page_no=1, png=b"page-one", width_px=1000, height_px=1400)]

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:
        return b"crop"

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        return ""


class RecordingProvider:
    """A transcription double keyed per (source blob, page); records `repr()` of every prompt
    it is sent — the assembled request, as the model boundary receives it."""

    def __init__(self) -> None:
        self.texts: dict[tuple[str, int], str] = {}
        self.requests: list[str] = []

    def complete(self, prompt, model_ref, params) -> Completion:
        self.requests.append(repr(prompt))
        fields = dict(prompt.fields)
        key = (fields.get("source_blob_hash", ""), int(fields.get("page_no") or 0))
        return Completion(text=self.texts.get(key, "plain page"), tokens_in=1, tokens_out=1,
                          latency_ms=1, resolved_build=model_ref.build_id,
                          cached_prefix_tokens=0, cost=None)


def _model() -> ModelRef:
    return ModelRef(role="transcriber", provider="local", build_id="vlm@sha256:f00d",
                    quantization="q4")


def transcript(written: str | None, student_id: str | None = None) -> str:
    """One page: the identity head the model copies, then one answer region."""
    head = f"Student: {written}\n" if written is not None else ""
    if student_id is not None:
        head += f"Student ID: {student_id}\n"
    return head + ("<!-- region: kind=transcribed_text question_id=Q1 conf=0.97 -->\n"
                   "the worked answer\n<!-- /region -->")


def roster_has_names_column(handle: Any) -> bool:
    return any(row["name"] == "full_name"
               for row in handle.query("PRAGMA table_info(roster)"))


def require_names_column(handle: Any) -> None:
    if not roster_has_names_column(handle):
        raise NotImplementedYet(
            f"the roster has no full_name column — Cohort migration 33 "
            f"('ingest_roster_names') has not landed (blocked on {ISSUE}). This case is written "
            f"ahead of its implementation (operator-requirements test plan §8.2, TS-143).")


@dataclass
class NamesWorld:
    """One fresh store, one cohort holding `rows`, and an ingestor over it."""

    root: Path
    rows: tuple[Row, ...] = ROWS
    store: Any = field(init=False)
    handle: Any = field(init=False)
    provider: RecordingProvider = field(init=False)
    ingestor: Any = field(init=False)

    def __post_init__(self) -> None:
        self.store = open_store(self.root)
        try:
            self.store.durable()  # Tier D exists, so its file is there to sweep
            self.handle = self.store.cohort(COHORT)
            require_names_column(self.handle)
            with self.handle.transaction() as tx:
                tx.execute("INSERT INTO cohort (cohort_id, consent_class, created_at) "
                           "VALUES ('c-fnames', 'synthetic', '2026-10-05T00:00:00+00:00')")
                for row in self.rows:
                    tx.execute("INSERT INTO roster (cohort_id, student_ref, full_name) "
                               "VALUES ('c-fnames', :r, :n)", r=row.student_ref, n=row.full_name)
        except BaseException:
            self.store.close()
            raise
        self.provider = RecordingProvider()
        self.ingestor = Ingestor(self.handle, self.store.blobs(), self.provider, _model(),
                                 SamplingParams(temperature=0.0), OnePageRasterizer(),
                                 residency=ResidencySlot.for_policy(("transcriber",)),
                                 sanitizer=ThroughSanitizer())

    def ingest(self, tag: str, written: str | None, student_id: str | None = None) -> Any:
        """Ingest one one-page sheet whose transcription carries `written` (and `student_id`)."""
        source = self.store.blobs().put(f"fnames-sheet-{tag}".encode())
        self.provider.texts[(source, 1)] = transcript(written, student_id)
        return self.ingestor.ingest_submission([source], cohort_id=COHORT,
                                               package_version="v0",
                                               filenames={source: f"scan-{tag}.pdf"})

    def submission(self, submission_id: str) -> Any:
        rows = self.handle.query(
            "SELECT submission_id, student_ref, v3_identity, ingest_status, quarantined "
            "FROM submission WHERE submission_id = :s", s=submission_id)
        assert len(rows) == 1, f"fixture: expected one submission row for {submission_id}"
        return rows[0]

    def close(self) -> None:
        self.store.close()
