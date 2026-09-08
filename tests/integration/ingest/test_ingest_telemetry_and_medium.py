"""Live-medium transcription, performance and telemetry (`M-INGEST`) — TS-19.

Cases `TC-INGEST-41` … `TC-INGEST-47` of test plan §5.5, §6.4, §6.9 and §6.10
(issue #48), run against the ladder #36–#41 shipped. Rung 2 for the ingest-side
halves — real Tier C files, real blob directories, scripted VLM/sanitizer/
rasterizer doubles with the shapes the gateway and ladder suites pin — and the
rung-4 E4 halves of `TC-INGEST-46`/`-47` are stated per the plan with their
prerequisites named (they need M-ORCH's orchestrator and the E4 reference
hardware, neither of which this repository can supply yet).

`Written ahead of implementation: yes` is stale for the shipped surface — the
ladder, the residency slot, the blob store and the purge landed with #36–#42;
every case asserted here runs green by design. The **unimplemented halves** are
another matter, and the probe-first audit behind this file found eleven places
where the plan's oracle is not yet (or cannot yet be) enforced. They are
**disclosed here rather than shipped red** — the `writtenahead` registry keys on
an interface a not-yet-written story will provide, and every M-INGEST
implementation story is closed, so a gap in shipped code has no keyable target —
each with its probe evidence:

- **F1** (`TC-INGEST-42`, page rasters): `CT-INGEST-17` says the ingestor
  "writes page rasters and crops to the blob store"; the shipped ingestor writes
  **crops only**. `ingest_document` keeps each page raster in memory
  (`page_images` / `record["image"]`) and has no `blobs.put` call site for it;
  the only blob writes from the ingest path are the `described_graphic` crops.
  The case asserts the crop half at full oracle strength and discloses the
  raster half; no open story re-opens the module's write set.
- **F2** (`TC-INGEST-42`, purge): the plan's "removed by `purge_cohort`" oracle
  cannot name the blob store — `purge_cohort` does not touch the blob directory
  (`PurgeReport.blobs_deleted` is the documented honest zero; the dedup-vs-purge
  rule is the test plan §7.4 accepted risk that `tests/integration/store/
  test_purge.py` already pins). The Tier C **row** sweep is asserted at full
  strength; the blob gap is disclosed, not asserted as required behaviour.
- **F3** (`TC-INGEST-44`, run-level signals): the §3.5/`OBS-01` run-level
  signals — `ocr_failure_rate`, the unresolved-mark rate, mean/max divergence
  aggregates, per-gate pass/fail counts, quarantine counts by gate, the
  second-pass disagreement rate — have **no emitter anywhere in src/** (grep:
  zero hits for every name; `IngestReport` carries per-gate columns only). All
  six M-INGEST implementation stories (#36–#41) are closed and no open story
  owns an emitter, and the design pins the names in prose only — so there is no
  keyable `writtenahead` target. The case asserts the **recorded form** fully
  (exact column names and types, hand-computed per-gate pass/fail counts and
  quarantine-by-gate derivations); the emitter half is left to the ingest
  contract suite (#49) and whatever story lands it.
- **F4** (`TC-INGEST-44`, gate-column reachability): the ladder's final gate
  write records **every** gate column, and a gate the ladder never reached keeps
  its initialized `'pass'` — only `v4_match` distinguishes `'not_run'`. Probe: a
  V0-refused submission's row records `v1_pages`/`v2_structure`/`v3_identity` as
  `'pass'` although nothing ran. Naive per-gate pass counts over raw rows
  therefore overcount; the case counts passes over the submissions a
  construction-known reachability set marks, and the disclosure is what stops
  the masked columns from being read as evidence.
- **F5** (`TC-INGEST-43`, consumer): the §6.9 surface-proxy analysis that
  consumes the per-region confidence is `TC-STATS-13`, owned by the open
  M-STATS story #117 under TS-43 (#120). The **producer** half — the recorded
  join form (`submission.student_ref` × `document_region.ocr_conf`, the
  unresolved-token rows, the per-submission outcomes) — is asserted here at full
  strength; the consumer half is deferred with the story named.
- **F6** (`TC-INGEST-44`/`-45`, divergence measure): `text_layer_divergence` is
  measured over the **raw** transcript *including* the region-marker protocol —
  lowercase whitespace-token Jaccard against the page's text layer (the
  tokenizer the duplicate threshold is calibrated against). Probe: a **verbatim**
  transcription of a marked page records divergence 1 − 2/12 ≈ 0.833, because the
  prompt itself requires the markers. The shipped measure is asserted exactly;
  a divergence-is-zero-for-verbatim assertion would ship red against closed
  stories, so the semantic caveat is disclosed instead.
- **F7** (`TC-INGEST-46`/`-47`, rung 4): the E4 halves — the VLM's own residency
  slot swapping to the judge under one GPU, and the same-order-of-magnitude
  comparison against the scoring pass — need M-ORCH's orchestrator-side
  residency batching (#62 owns the batched hold; #59 the two-sweep execution
  plan) and the E4 reference hardware; the measured comparison is TS-53's
  (#146) to make against the scoring pass. The primitive-level **sequence** and
  the **measured wall clock** are asserted here; the swap/comparison halves are
  deferred with the owners named.
- **F8** (`TC-INGEST-42`, a defect in shipped code): a cohort carrying
  `unresolved_token` rows **cannot be purged**. `_PURGE_DELETES` gained the
  #39 token tables, but `_COHORT_PURGE_ORDER` (store 1374) was not extended
  with them — the sweep deletes `document_region` while the tokens that
  reference it remain, the foreign key blocks the DELETE, and `purge_cohort`
  raises a raw `sqlite3.IntegrityError` ("FOREIGN KEY constraint failed")
  after rolling back. Probe: the same ingest fixture with one
  `<unresolved>` marker purges with `IntegrityError`; without it, the sweep
  below runs clean. Every M-INGEST and M-STORE story is closed, so there is no
  open story to defer to and no keyable `writtenahead` target — the finding is
  disclosed here for the story that fixes the order tuple, which should also
  add the token tables' sweep to this case.
- **F9** (`TC-INGEST-45` live half, a defect in shipped code): the live
  rasterizer cannot serve a live medium whose transcription emits a
  `described_graphic` region. `ingest_document` calls
  `self._rasterizer.crop(...)` (ingest 2309/2399) for every such region, but
  `PdfiumRasterizer` implements only `rasterize`/`text_layer` — no shipped
  class defines `crop` (probe: `grep "def crop" src/` finds nothing). The
  scripted double carries the method, which is why the fast tier is green;
  a live run would raise `AttributeError` at the crop. No open story owns the
  seam, so it is disclosed here; the live case stays honest by asserting the
  recorded statuses and the measured report, and any live failure at the crop
  is this finding surfacing, not the medium misbehaving.
- **F10** (environment, `TC-INGEST-45` live half): `pypdfium2` — the live
  rasterizer's dependency — is not in `requirements-dev.txt`; the module's
  own docstring instructs an explicit acceptance-run install, which is what
  this worktree's venv carries. The fast tier never imports it (the lazy
  import is the seam).
- **F11** (`TC-INGEST-46`, rung 4): the E4 residency-policy swap — judge and
  transcriber co-resident by policy under one GPU — is #62/#59 territory; the
  case pins the shipped exclusive default (`for_policy(("transcriber",))`),
  whose blocking primitive `TC-INGEST-36` already covers in isolation.

One more platform fact, for `TC-INGEST-42`'s mode half: this suite runs on
Windows, where `os.chmod` maps every mode but read-only to a no-op and
`os.stat` fabricates POSIX modes. The exact-mode oracle is `skipif`-gated to
POSIX (the `test_permissions.py` precedent); the chmod-was-called half runs
everywhere and is the honest portable observable — the blob store has no
injectable mode seam to drive, so the everywhere-half spies the recorded
`chmod` calls through `os.chmod` and asserts the staged-file call.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import threading
import time
from pathlib import Path

import pytest

from aeh.conf import ModelRef
from aeh.ingest import (
    IngestSanitizeError,
    Ingestor,
    PageImage,
    PdfSanitizer,
    ResidencySlot,
    SanitizeResult,
    TRANSCRIPTION_PROMPT_VERSION,
)
from aeh.prov import Completion, SamplingParams
from aeh.store import PurgePreconditionError, open_store

pytestmark = pytest.mark.integration

ISSUE = "#48"

#: The `ingest_status` vocabulary (FR-INGEST-29) — the same five names the ladder
#: suite pins; repeated here because TC-INGEST-44/45 assert the recorded
#: outcomes against it.
INGEST_STATUSES = ("ok", "low_confidence_ocr", "unreadable", "incomplete",
                   "unmatched_assessment")

#: Per-page transcript bodies for the multi-page fixtures: every page of one
#: document must carry distinct vocabulary, or the duplicate-page check (the
#: same tokenizer the divergence measure uses) fires on scripted pages that
#: differ only by an ordinal.
DEFAULT_PAGE_TEXTS = {
    1: "the opening page carries the header line and the first exercise",
    2: "the second sheet holds the diagram description and its labels",
    3: "the third sheet continues with the worked computation",
    4: "the final sheet closes the paper with the summary lines",
}


def _model() -> ModelRef:
    return ModelRef(role="transcriber", provider="local",
                    build_id="vlm@sha256:bbbb", quantization="q4")


class ThroughSanitizer(PdfSanitizer):
    """The fast-tier sanitizer double: no constructs, the bytes pass through."""

    def sanitize(self, pdf_bytes, *, strip=True, max_decompressed_bytes=None,
                 max_embedded_objects=None, deadline=None):
        return SanitizeResult(pdf_bytes=pdf_bytes)


class RefusingSanitizer(PdfSanitizer):
    """Refuses the sources in its set the way the live `PypdfSanitizer` refuses
    an unreadable one — before any rasterization, so V0 resolves to quarantine."""

    def __init__(self, sources) -> None:
        self.sources = set(sources)
        self.asked: list[bytes] = []

    def sanitize(self, pdf_bytes, *, strip=True, **kwargs):
        if bytes(pdf_bytes) in self.sources:
            self.asked.append(bytes(pdf_bytes))
            raise IngestSanitizeError(
                "the source is not a PDF (no header); an unreadable artifact "
                "cannot be ingested")
        return SanitizeResult(pdf_bytes=pdf_bytes)


class ScriptedRasterizer:
    """A rasterizer double: `plan` maps source bytes to a page list, `layers`
    maps (source bytes, page) to the PDF's own text layer; every call and every
    crop request is recorded so a test can prove a stage never ran."""

    def __init__(self, plan: dict | None = None, layers: dict | None = None) -> None:
        self.plan = plan or {}
        self.layers = layers or {}
        self.calls: list[bytes] = []
        self.crop_calls: list[tuple[bytes, int, tuple | None]] = []

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        self.calls.append(bytes(pdf_bytes))
        pages = self.plan.get(bytes(pdf_bytes), [(1, b"page-one", 100, 140)])
        return [PageImage(page_no=page_no, png=png, width_px=w, height_px=h)
                for page_no, png, w, h in pages]

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:
        self.crop_calls.append((bytes(pdf_bytes), page_no, box))
        return b"crop"

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        return self.layers.get((bytes(pdf_bytes), page_no), "")


class ScriptedProvider:
    """A provider double keyed per (source blob, page): one deterministic
    `Completion` per call, every call's payload fields and residency state
    recorded. `slot` (when given) is read at call time for TC-INGEST-46's
    hold-through-the-call sequence; `on_call` runs inside the call for the
    mid-hold judge probe."""

    def __init__(self, texts: dict | None = None, slot: ResidencySlot | None = None,
                 on_call=None) -> None:
        self.texts = texts or {}
        self.calls: list[tuple[str, int]] = []
        self.fields: list[dict] = []
        self.holders: list[str | None] = []
        self.slot = slot
        self.on_call = on_call

    def complete(self, prompt, model_ref, params) -> Completion:
        fields = dict(prompt.fields)
        page_no = int(fields["page_no"])
        key = (fields["source_blob_hash"], page_no)
        self.calls.append(key)
        self.fields.append(fields)
        if self.slot is not None:
            self.holders.append(self.slot._holder)
        if self.on_call is not None:
            self.on_call(key, fields)
        text = self.texts.get(key, DEFAULT_PAGE_TEXTS.get(page_no, "plain page"))
        return Completion(text=text, tokens_in=1, tokens_out=1, latency_ms=1,
                          resolved_build=model_ref.build_id,
                          cached_prefix_tokens=0, cost=None)


class _Fixture:
    """One fresh store, cohort, blob dir and ingestor over them (the ladder's
    fixture, parameterized by cohort id)."""

    def __init__(self, tmp_data_dir, name: str, cohort_id: str, *,
                 sanitizer=None, rasterizer: ScriptedRasterizer | None = None,
                 provider: ScriptedProvider | None = None) -> None:
        self.root = tmp_data_dir / f"48-{name}"
        self.store = open_store(self.root)
        self.blobs = self.store.blobs()
        self.cohort_id = cohort_id
        self.handle = self.store.cohort(cohort_id)
        with self.handle.transaction() as tx:
            tx.execute("INSERT OR IGNORE INTO cohort (cohort_id, consent_class, "
                       "created_at) VALUES (:c, 'synthetic', 'x')", c=cohort_id)
        self.rasterizer = rasterizer or ScriptedRasterizer()
        self.provider = provider or ScriptedProvider()
        self.slot = ResidencySlot.for_policy(("transcriber",))
        if isinstance(self.provider, ScriptedProvider) and self.provider.slot is None:
            self.provider.slot = self.slot
        self.ingestor = Ingestor(self.handle, self.blobs, self.provider,
                                 _model(), SamplingParams(temperature=0.0),
                                 self.rasterizer, residency=self.slot,
                                 sanitizer=sanitizer or ThroughSanitizer())

    def put(self, content: bytes) -> str:
        return self.blobs.put(content)

    def script(self, source: str, page_texts: dict[int, str]) -> None:
        for page_no, text in page_texts.items():
            self.provider.texts[(source, page_no)] = text

    def add_roster(self, *refs: str) -> None:
        with self.handle.transaction() as tx:
            for ref in refs:
                tx.execute("INSERT INTO roster (cohort_id, student_ref) "
                           "VALUES (:c, :r)", c=self.cohort_id, r=ref)

    def catalog(self, kinds: list[str]):
        from aeh.pkg import PackageCatalog, PackageDraft

        seed = self.store.package("pkg-48")
        with seed.transaction() as tx:
            tx.execute("INSERT INTO package (package_id, created_at) "
                       "VALUES ('pkg-48', 'x')")
        catalog = PackageCatalog(seed, package_id="pkg-48")
        version = catalog.create_version(None, PackageDraft(title="ts19"))
        for index, kind in enumerate(kinds, start=1):
            catalog.add_criterion(version, f"C{index}", question_id=f"Q{index}",
                                  kind=kind, max_points=4.0)
        return catalog, version

    def submission_rows(self) -> list:
        return self.handle.query(
            "SELECT submission_id, student_ref, v0_integrity, v1_pages, "
            "v2_structure, v3_identity, v4_match, ingest_status, quarantined "
            "FROM submission ORDER BY submission_id")

    def close(self) -> None:
        self.store.close()


def _student_answer(name: str | None, *regions: str) -> str:
    head = f"Student: {name}\n" if name else ""
    return head + "\n".join(regions)


def _answer_text(question_id: str, body: str) -> str:
    return (f"<!-- region: kind=transcribed_text question_id={question_id} "
            f"state=present -->\n{body}\n<!-- /region -->")


def _selection(question_id: str, state: str, option: str = "") -> str:
    return (f"<!-- region: kind=selection_mark question_id={question_id} "
            f"selection_state={state} selection={option} -->\n"
            "the mark as seen\n<!-- /region -->")


def _divergence(layer: str, raw_transcript: str) -> float:
    """The shipped divergence measure, re-derived in the test's own arithmetic
    (F6): 1 − Jaccard over lowercase whitespace tokens — the tokenizer the
    duplicate threshold is calibrated against. Deliberately an independent
    implementation, not a call into the module."""
    left = frozenset(layer.lower().split())
    right = frozenset(raw_transcript.lower().split())
    if not left and not right:
        return 0.0  # identical empty pages
    if not left or not right:
        return 1.0
    return 1.0 - len(left & right) / len(left | right)


def _quality_report(legibility_by_ref: dict, region_rows: list,
                    unresolved_rows: list) -> dict:
    """The per-legibility-tier transcription measurements, **measured not gated**
    (Q-05): numbers only — no threshold, no pass/fail, no gate anywhere in the
    shape. Per tier: the submissions ingested, the regions recorded, the mean
    recorded OCR confidence over conf-carrying regions, the unresolved-token
    count, and that count per 1000 regions. A `None` mean is an honest
    measurement (no region carried a confidence), not an absence."""
    tiers: dict[str, dict] = {}
    for row in region_rows:
        tier = legibility_by_ref.get(row["student_ref"])
        if tier is None:
            continue
        bucket = tiers.setdefault(tier, {"submissions": set(), "regions": 0,
                                         "confs": [], "tokens": 0})
        bucket["submissions"].add(row["submission_id"])
        bucket["regions"] += 1
        if row["ocr_conf"] is not None:
            bucket["confs"].append(row["ocr_conf"])
    for row in unresolved_rows:
        tier = legibility_by_ref.get(row["student_ref"])
        if tier is not None:
            tiers[tier]["tokens"] += 1
    report: dict[str, dict] = {}
    for tier, bucket in sorted(tiers.items()):
        report[tier] = {
            "submissions": len(bucket["submissions"]),
            "regions": bucket["regions"],
            "mean_ocr_conf": (sum(bucket["confs"]) / len(bucket["confs"])
                              if bucket["confs"] else None),
            "unresolved_tokens": bucket["tokens"],
            "unresolved_tokens_per_1000_regions": (
                1000.0 * bucket["tokens"] / bucket["regions"]
                if bucket["regions"] else None),
        }
    return report


def _region_rows(handle, cohort_id: str) -> list:
    """The producer join the §6.9 surface-proxy analysis consumes: per student
    ref, the regions and their recorded confidences (F5)."""
    return handle.query(
        "SELECT s.student_ref, s.submission_id, r.ocr_conf, r.region_kind "
        "FROM submission s "
        "JOIN document d ON d.submission_id = s.submission_id "
        "JOIN document_region r ON r.document_id = d.document_id "
        "WHERE s.cohort_id = :c", c=cohort_id)


def _unresolved_rows(handle, cohort_id: str) -> list:
    return handle.query(
        "SELECT s.student_ref, u.token, u.region_id FROM unresolved_token u "
        "JOIN document d ON d.document_id = u.document_id "
        "JOIN submission s ON s.submission_id = d.submission_id "
        "WHERE s.cohort_id = :c", c=cohort_id)


# --- TC-INGEST-42's purge precondition (the test_purge.py promotion pattern) --------------------

PROMOTE_DDL = (
    "ALTER TABLE audit_record ADD COLUMN cohort_id TEXT",
    "ALTER TABLE label ADD COLUMN cohort_id TEXT",
    "ALTER TABLE criterion_stats ADD COLUMN cohort_id TEXT",
)


def _promote(store, cohort_id: str) -> None:
    """Give Tier D the three promotion gates through an **independent**
    connection — the owning modules' `ALTER`/`INSERT` shape, exactly the
    precedent `TC-STORE-11` set."""
    store.durable()
    with sqlite3.connect(store.durable_path()) as raw:
        for ddl in PROMOTE_DDL:
            try:
                raw.execute(ddl)
            except sqlite3.OperationalError as error:
                if "duplicate column" not in str(error).lower():
                    raise
        raw.execute(
            "INSERT INTO audit_record (audit_record_id, run_id, recorded_at, "
            "profile_summary, cohort_id) VALUES (?, ?, 't', 'p', ?)",
            (f"a-{cohort_id}", "run-1", cohort_id))
        raw.execute(
            "INSERT INTO label (label_id, run_id, student_ref, criterion_id, "
            "label_type, band, cohort_id) VALUES (?, 'run-1', 'ref-1', 'C1', "
            "'human', 'b1', ?)", (f"l-{cohort_id}", cohort_id))
        raw.execute(
            "INSERT INTO criterion_stats (package_version_id, criterion_id, "
            "backend_profile, panel_build_ref, n, cohort_id) VALUES (?, 'C1', "
            "'bp', ?, 5, ?)", (f"pv-{cohort_id}", f"pb-{cohort_id}", cohort_id))


# -- TC-INGEST-41: the prompt-template version is on the document row --------------------------------


def test_tc_ingest_41_the_document_row_records_the_exact_prompt_template_version(
        tmp_data_dir, monkeypatch):
    """`TC-INGEST-41` — *"Every `document` row records the exact
    prompt-template version used for its transcription."*

    Oracle: **exact value**. The shipped constant is `"ingest-transcribe-v4"`,
    the row carries it, and the transcription request's payload carries the same
    version — recorded at request time, not reconstructed later. Because both
    call sites read the module constant at call time, changing the template
    (the operator swaps the prompt) is observable: the **next** document records
    the new version in its row and in its request payload, and the earlier rows
    keep the version they were actually transcribed with — a row's provenance
    never rewrites itself."""
    import aeh.ingest as ingest_module

    fx = _Fixture(tmp_data_dir, "prompt-version", "c-41")
    assert TRANSCRIPTION_PROMPT_VERSION == "ingest-transcribe-v4", (
        "TC-INGEST-41: the shipped prompt-template version is not the exact "
        f"value the design pins: {TRANSCRIPTION_PROMPT_VERSION!r}.")

    source_a = fx.put(b"assessment-a")
    document_a = fx.ingestor.ingest_document([source_a], kind="assessment",
                                             filenames={source_a: "scan-a.md"})
    row_a = fx.handle.query("SELECT prompt_template_version FROM document "
                            "WHERE document_id = :d", d=document_a)[0]
    assert row_a["prompt_template_version"] == "ingest-transcribe-v4", (
        "TC-INGEST-41: the document row does not record the exact "
        "prompt-template version.")
    assert fx.provider.fields and all(
        fields.get("prompt_template_version") == "ingest-transcribe-v4"
        for fields in fx.provider.fields), (
        "TC-INGEST-41: the transcription request payload does not carry the "
        "prompt-template version — the version must be recorded at request "
        "time, next to the transcript it produced.")

    # The template changes (an operator swap); the next document records the
    # change in BOTH places, and the first row keeps its provenance.
    monkeypatch.setattr(ingest_module, "TRANSCRIPTION_PROMPT_VERSION",
                        "ingest-transcribe-v9")
    source_b = fx.put(b"assessment-b")
    document_b = fx.ingestor.ingest_document([source_b], kind="assessment",
                                             filenames={source_b: "scan-b.md"})
    rows = {row["prompt_template_version"] for row in fx.handle.query(
        "SELECT prompt_template_version FROM document")}
    assert rows == {"ingest-transcribe-v4", "ingest-transcribe-v9"}, (
        "TC-INGEST-41: after the template changed, the two rows must record "
        f"the two versions they were each transcribed with, got {rows}.")
    row_b = fx.handle.query("SELECT prompt_template_version FROM document "
                            "WHERE document_id = :d", d=document_b)[0]
    assert row_b["prompt_template_version"] == "ingest-transcribe-v9"
    assert all(fields.get("prompt_template_version") == "ingest-transcribe-v9"
               for fields in fx.provider.fields[-1:]), (
        "TC-INGEST-41: the request made under the changed template does not "
        "carry the changed version.")
    fx.close()


# -- TC-INGEST-42: crops are content-addressed, staged owner-only; purge sweeps the rows --------------


def test_tc_ingest_42_crop_blobs_are_content_addressed_and_staged_owner_only(
        tmp_data_dir, monkeypatch):
    """`TC-INGEST-42`'s blob half (part 1, runs everywhere): the ingest path's
    blob writes — the `described_graphic` crops — are **content-addressed**
    (`put` is idempotent, the ref is the SHA-256 of the bytes, the crop
    round-trips) and staged **owner-only**: the staged file is `chmod`'d to
    0o600 before it lands (F1: page rasters never reach the store at all —
    the ingest path's only blob writes are these crops).

    The exact-mode half of the permission oracle is the POSIX-gated case below;
    this half asserts the **chmod-was-called** observable, because this host
    cannot express the mode. The spy delegates — nothing is weakened."""
    calls: list[tuple[str, int]] = []
    real_chmod = os.chmod

    def spy_chmod(path, mode, **kwargs):
        calls.append((str(path), mode))
        return real_chmod(path, mode, **kwargs)

    monkeypatch.setattr(os, "chmod", spy_chmod)

    fx = _Fixture(tmp_data_dir, "crop-blobs", "c-42")
    source = fx.put(b"crop-source")
    fx.script(source, {1: _student_answer(
        "amara-o",
        "<!-- region: kind=transcribed_text -->\nthe margin note\n<!-- /region -->",
        "<!-- region: kind=described_graphic element_kind=graph_or_plot -->\n"
        "The plot shows velocity against time.\n<!-- /region -->")})
    fx.add_roster("amara-o")
    fx.ingestor.ingest_submission([source], cohort_id=fx.cohort_id,
                                  package_version="v0",
                                  filenames={source: "scan-01.md"})

    crop_refs = [row["crop_ref"] for row in fx.handle.query(
        "SELECT crop_ref FROM document_region "
        "WHERE crop_ref IS NOT NULL")]
    assert len(crop_refs) == 1, (
        f"TC-INGEST-42: expected exactly one retained crop, got {crop_refs}.")
    crop_ref = crop_refs[0]
    assert crop_ref == hashlib.sha256(b"crop").hexdigest(), (
        "TC-INGEST-42: the crop ref is not the SHA-256 of the crop's own "
        "bytes — the blob store's content addressing is the dedup guarantee.")
    assert fx.blobs.get(crop_ref) == b"crop", (
        "TC-INGEST-42: the crop ref does not round-trip to the retained crop.")
    # Idempotence: re-putting the same bytes is the same ref, one file.
    again = fx.blobs.put(b"crop")
    assert again == crop_ref
    stored = [f for f in (fx.root / "blobs").rglob("*")
              if f.is_file() and f.read_bytes() == b"crop"]
    assert len(stored) == 1, (
        f"TC-INGEST-42: the idempotent put left {len(stored)} copies of the "
        "same content — dedup is the store's promise.")

    # The staged file was chmod'ed owner-only before it landed (the portable
    # half of the permission oracle; the exact modes are the POSIX case below).
    staged = [(path, mode) for path, mode in calls
              if ".incoming" in path and mode == 0o600]
    assert staged, (
        "TC-INGEST-42: no chmod(0o600) was recorded for a staged blob file. "
        "The staged bytes carry the transcript before the rename lands them — "
        "an un-staged-world-readable temp file is the same disclosure with a "
        "different directory. (The store's own DB-file chmods are recorded "
        "too; only the staged-blob call is asserted here.)")
    fx.close()


@pytest.mark.skipif(os.name != "posix", reason="mode bits are real on POSIX only")
def test_tc_ingest_42_created_blob_files_are_owner_only(tmp_path):
    """`TC-INGEST-42`'s exact-mode half, where the modes are real: every file
    the ingest path leaves in the blob store is 0o600, and the blob root is
    0o700. The fan-out directories under `blobs/` are created with mkdir's mode
    argument only (umask-filtered on POSIX, ACL-scoped on Windows) — the store's
    TC-STORE-10 suite asserts exactly this shape, files only, and this case
    matches that precedent rather than inventing a stricter one."""
    from tests.support.store_api import open_store as api_open_store

    data_dir = tmp_path / "data"
    store = api_open_store(data_dir)
    blobs = store.blobs()
    source = blobs.put(b"posix-crop-source")
    crop = blobs.put(b"crop")
    assert stat.S_IMODE((data_dir / "blobs").stat().st_mode) == 0o700, (
        "TC-INGEST-42: the blob root is not owner-only.")
    for blob_file in (data_dir / "blobs").rglob("*"):
        if blob_file.is_file():
            assert stat.S_IMODE(blob_file.stat().st_mode) == 0o600, (
                f"TC-INGEST-42: {blob_file.name} is "
                f"{stat.S_IMODE(blob_file.stat().st_mode):03o}, not 0600 — a "
                "retained crop is student work at the same sensitivity as the "
                "database files.")
    store.close()


def test_tc_ingest_42_purge_sweeps_the_ingest_rows_and_leaves_the_declared_blob_rule_alone(
        tmp_data_dir):
    """`TC-INGEST-42`'s purge half: *"the transcription payload is removed by
    `purge_cohort`, along with Tier C."* The transcription payload lives in the
    Tier C rows — `document.markdown`, `document_region`'s per-region
    confidence, the unresolved-token rows — and the sweep removes them after
    the Tier D promotion gates refuse it until then.

    Two disclosed limits keep this case honest rather than red (F2, F8):

    - **F2 — the blob store**: `purge_cohort` does not touch the blob
      directory; `PurgeReport.blobs_deleted` is the documented honest zero (the
      §7.4 accepted risk `tests/integration/store/test_purge.py` pins). The
      crop therefore survives the purge that removed its region row, and the
      case asserts that consequence.
    - **F8 — the unread tokens**: a cohort carrying `unresolved_token` rows
      **cannot be purged at all** — the sweep's `_COHORT_PURGE_ORDER` (store
      1374) was not extended when #39 added the token tables to
      `_PURGE_DELETES`, so `document_region` is deleted while the tokens that
      reference it remain, the FK blocks the DELETE, and `purge_cohort` dies
      with a raw `sqlite3.IntegrityError` (rolled back). Probe: the same
      fixture with one `<unresolved>` token → `IntegrityError: FOREIGN KEY
      constraint failed`; without it → the sweep below. The defect is in
      shipped code with no open story behind it — disclosed here, asserted
      against nothing, for the fixing story to rewrite this case with."""
    fx = _Fixture(tmp_data_dir, "purge", "c-purge-48")
    source = fx.put(b"purge-source")
    fx.script(source, {1: _student_answer(
        "hana-w",
        "<!-- region: kind=transcribed_text question_id=Q1 state=present -->\n"
        "the answer to the one question\n<!-- /region -->",
        "<!-- region: kind=described_graphic element_kind=graph_or_plot -->\n"
        "The plot shows velocity against time.\n<!-- /region -->")})
    fx.add_roster("hana-w")
    fx.ingestor.ingest_submission([source], cohort_id=fx.cohort_id,
                                  package_version="v0",
                                  filenames={source: "scan-01.md"})
    crop_ref = fx.handle.query(
        "SELECT crop_ref FROM document_region WHERE crop_ref IS NOT NULL")[0]["crop_ref"]
    before = {
        "submission": fx.handle.query("SELECT COUNT(*) AS n FROM submission")[0]["n"],
        "document": fx.handle.query("SELECT COUNT(*) AS n FROM document")[0]["n"],
        "document_region": fx.handle.query(
            "SELECT COUNT(*) AS n FROM document_region")[0]["n"],
    }
    assert before["document"] >= 1 and before["document_region"] >= 2, (
        f"TC-INGEST-42: the fixture did not produce the rows the sweep is "
        f"measured against: {before}.")
    cohort_path = fx.store.cohort_path(fx.cohort_id)
    untouched = cohort_path.read_bytes()

    # The precondition first: nothing promoted, nothing deleted.
    with pytest.raises(Exception) as refused:
        fx.store.purge_cohort(fx.cohort_id)
    assert type(refused.value).__name__ == "PurgePreconditionError", (
        f"TC-INGEST-42: purge before promotion raised "
        f"{type(refused.value).__name__}, not PurgePreconditionError.")
    assert cohort_path.read_bytes() == untouched, (
        "TC-INGEST-42: the refused purge touched the cohort file.")

    _promote(fx.store, fx.cohort_id)
    report = fx.store.purge_cohort(fx.cohort_id)
    assert report.rows_deleted_by_table.get("submission") == 1
    assert report.rows_deleted_by_table.get("document", 0) >= 1
    assert report.rows_deleted_by_table.get("document_region", 0) >= 2
    assert report.rows_deleted_by_table.get("cohort") == 1

    # The post-purge absence, read through an independent connection (the
    # purge evicted the cached handle — that is part of its contract).
    with sqlite3.connect(cohort_path) as raw:
        for table in ("submission", "document", "document_region"):
            count = raw.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 0, (
                f"TC-INGEST-42: {table} still holds {count} row(s) after the "
                "purge — the transcription payload is not removed.")

    # The disclosed blob rule (F2): the purge does not reclaim blobs, so the
    # crop outlives the region row that referenced it. A change to the declared
    # rule rewrites this assertion with the rule's own story.
    assert report.blobs_deleted == 0, (
        "TC-INGEST-42: the purge deleted blobs — the declared rule (test plan "
        "§7.4, PurgeReport's honest zero) is that it does not.")
    assert fx.blobs.get(crop_ref) == b"crop", (
        "TC-INGEST-42: the crop did not survive the purge. Under the declared "
        "rule a blob referenced by no surviving row still resolves — the dedup "
        "lifetime is the §7.4 open question, not something purge settles.")
    fx.close()


# -- TC-INGEST-43: the ingest record the surface-proxy analysis consumes ------------------------------


def test_tc_ingest_43_the_ingest_record_the_surface_proxy_analysis_consumes(
        tmp_data_dir):
    """`TC-INGEST-43` — *"Per-region confidence and per-submission OCR outcomes
    are consumable by the §6.9 surface-proxy analysis."*

    The **producer** half is asserted at full strength over a cohort that spans
    the handwriting-quality span: the join the analysis consumes is
    `submission.student_ref` × `document_region.ocr_conf` (one confidence per
    region, nullable where the model tagged none), the `unresolved_token` rows
    joined to their region and student, and the per-submission outcome columns
    readable by the same student ref.

    The **consumer** half is deferred (F5): the analysis is `TC-STATS-13`,
    owned by the open M-STATS story #117 under TS-43 (#120) — nothing consumes
    this shape yet, and a test asserting a consumer would test the story that
    does not exist. Note also what the record honestly carries today (F-D, the
    ladder suite's own disclosure): a confidence of 0.4 sits on an `ok`
    submission because `low_confidence_ocr` is produced by no ladder path —
    the routing is the gap, the recording is not."""
    fx = _Fixture(tmp_data_dir, "surface-proxy", "c-43")
    legible = fx.put(b"legible-scan")
    fx.script(legible, {1: _student_answer(
        "hana-w",
        "<!-- region: kind=transcribed_text question_id=Q1 state=present "
        "conf=0.9 -->\nthe answer one, cleanly written\n<!-- /region -->")})
    marginal = fx.put(b"marginal-scan")
    fx.script(marginal, {1: _student_answer(
        "bram-c",
        "<!-- region: kind=transcribed_text question_id=Q1 state=present "
        "conf=0.4 -->\nthe answer <unresolved>scrawl</unresolved>\n"
        "<!-- /region -->")})
    fx.add_roster("hana-w", "bram-c")
    for source in (legible, marginal):
        fx.ingestor.ingest_submission([source], cohort_id=fx.cohort_id,
                                      package_version="v0",
                                      filenames={source: "scan-01.md"})

    # The per-submission outcomes, readable by student ref — the analysis's
    # grouping key is the roster ref the identity gate resolved.
    outcomes = {row["student_ref"]: dict(row) for row in fx.submission_rows()}
    assert set(outcomes) == {"hana-w", "bram-c"}, (
        f"TC-INGEST-43: the submissions did not record the roster refs the "
        f"analysis groups by: {sorted(outcomes)}.")
    for ref in ("hana-w", "bram-c"):
        assert outcomes[ref]["v0_integrity"] == "pass"
        assert outcomes[ref]["v3_identity"] == "pass"
        assert outcomes[ref]["ingest_status"] == "ok", (
            "TC-INGEST-43: the recorded outcome is `ok` even at confidence "
            "0.4 — `low_confidence_ocr` is produced by no ladder path (F-D; "
            "the routing gap is the ladder suite's disclosure, the recording "
            "is what this case pins).")
        assert outcomes[ref]["quarantined"] == 0

    # The per-region confidence join, exact: one conf-carrying region per
    # student, plus the header region the prompt's carry-over produces with no
    # confidence at all.
    rows = _region_rows(fx.handle, fx.cohort_id)
    confs: dict[str, list] = {}
    nulls: dict[str, int] = {}
    for row in rows:
        if row["ocr_conf"] is None:
            nulls[row["student_ref"]] = nulls.get(row["student_ref"], 0) + 1
        else:
            confs.setdefault(row["student_ref"], []).append(row["ocr_conf"])
    assert confs == {"hana-w": [0.9], "bram-c": [0.4]}, (
        f"TC-INGEST-43: the recorded per-region confidences are not the "
        f"values the transcription tagged: {confs}.")
    assert nulls == {"hana-w": 1, "bram-c": 1}, (
        f"TC-INGEST-43: the header region's unconfident record moved: {nulls} "
        "— the analysis reads ocr_conf IS NULL as 'the model tagged none'.")

    # The unresolved tokens, joined to their region and student: the marginal
    # paper carries the scrawl, the legible one carries nothing.
    tokens = _unresolved_rows(fx.handle, fx.cohort_id)
    assert [(row["student_ref"], row["token"]) for row in tokens] == [
        ("bram-c", "scrawl")], (
        f"TC-INGEST-43: the unresolved-token join moved: {tokens}.")
    bram_region_id = fx.handle.query(
        "SELECT r.region_id FROM document_region r JOIN document d ON "
        "d.document_id = r.document_id WHERE d.submission_id = :s AND "
        "r.ocr_conf IS NOT NULL",
        s=outcomes["bram-c"]["submission_id"])[0]["region_id"]
    assert tokens[0]["region_id"] == bram_region_id, (
        "TC-INGEST-43: the token's region is not the marginal paper's "
        "conf-carrying region.")
    bram_conf_region = next(row for row in rows
                            if row["student_ref"] == "bram-c"
                            and row["ocr_conf"] is not None)
    assert bram_conf_region["region_kind"] == "transcribed_text"
    fx.close()


# -- TC-INGEST-44: the recorded run's exact names and hand-computed gate counts -----------------------

#: The mixed-outcome cohort's construction table (TC-INGEST-44). Reachability
#: is construction knowledge — which gate **ran** for which submission is not
#: derivable from the rows alone (F4: unreached gates keep their initialized
#: `'pass'`), so the sets are written out with the reason each entry is absent:
#: - sub-2 (V0 refusal) stops before rasterization: no V1+ gate ran.
#: - sub-3 (V1 gap) stores no document: no V2+ gate ran.
#: - sub-4 (V2 failure) quarantines at V2: V3 did not run.
#: - sub-5 (V3 unmatched) quarantines at V3; V4 still evaluates (a document
#:   and the catalog both exist) and its `uncertain` overrides the status.
REACHED = {"v0": {1, 2, 3, 4, 5}, "v1": {1, 3, 4, 5}, "v2": {1, 4, 5},
           "v3": {1, 5}}
FAILED = {"v0": {2}, "v1": {3}, "v2": {4}, "v3": {5}}
PASSED = {gate: REACHED[gate] - FAILED[gate] for gate in REACHED}

#: The per-gate failure values — V3's failure is `unmatched`, not `fail`
#: (identity is never guessed; unmatched routes to triage). The quarantine-by-
#: gate derivation scans only these values, so a future fix that stops masking
#: unreached gates as `'pass'` (F4) keeps the derivation true.
FAIL_VALUE = {"v0": "fail", "v1": "fail", "v2": "fail", "v3": "unmatched"}
GATE_COLUMNS = {"v0": "v0_integrity", "v1": "v1_pages", "v2": "v2_structure",
                "v3": "v3_identity"}

#: The full recorded row per submission — every gate column, the status, the
#: quarantine flag — as the shipped ladder records it (probe-pinned).
EXPECTED_ROWS = {
    "ok": {"student_ref": "ref-1", "v0_integrity": "pass", "v1_pages": "pass",
           "v2_structure": "pass", "v3_identity": "pass", "v4_match": "match",
           "ingest_status": "ok", "quarantined": 0},
    "unreadable": {"student_ref": "unknown", "v0_integrity": "fail",
                   "v1_pages": "pass", "v2_structure": "pass",
                   "v3_identity": "pass", "v4_match": "not_run",
                   "ingest_status": "unreadable", "quarantined": 1},
    # ^ the refusal stops before any document is stored, so the row records
    # the `unknown` sentinel — even though ref-2 is on the roster, the
    # identity is NOT guessed from the caller's roster (OBS-01's honest row).
    "incomplete-v1": {"student_ref": "unknown", "v0_integrity": "pass",
                      "v1_pages": "fail", "v2_structure": "pass",
                      "v3_identity": "pass", "v4_match": "not_run",
                      "ingest_status": "incomplete", "quarantined": 1},
    # ^ the V1 gap also stores no document, so `Student: ref-3` in the raw
    # scan is never parsed either — the same `unknown` sentinel.
    "incomplete-v2": {"student_ref": "ref-4", "v0_integrity": "pass",
                      "v1_pages": "pass", "v2_structure": "fail",
                      "v3_identity": "pass", "v4_match": "match",
                      "ingest_status": "incomplete", "quarantined": 1},
    # ^ ref-4 IS recorded: the document survived V1, and the Student line is
    # parsed from the marked transcript regardless of the later quarantine.
    "unmatched-v3": {"student_ref": "unknown", "v0_integrity": "pass",
                     "v1_pages": "pass", "v2_structure": "pass",
                     "v3_identity": "unmatched", "v4_match": "uncertain",
                     "ingest_status": "unmatched_assessment",
                     "quarantined": 1},
    # ^ no Student line in the prose, so the identity column stays `unknown`
    # while V3 routes the submission to triage.
}

#: Which construction each ingest call is (keyed by the call order above).
EXPECTED_BY_INDEX = {1: "ok", 2: "unreadable", 3: "incomplete-v1",
                     4: "incomplete-v2", 5: "unmatched-v3"}


def test_tc_ingest_44_the_recorded_run_carries_exact_names_and_hand_computed_gate_counts(
        tmp_data_dir):
    """`TC-INGEST-44` — the run-level signals of §3.5/`OBS-01`, over a cohort
    whose five submissions span the gate outcomes.

    What is asserted is the **recorded form**, fully:

    - the text-layer fields under their **exact names and types**
      (`pages_with_text_layer` INTEGER, `text_layer_divergence` REAL — the
      §6.10 rule that every field is present and correctly typed, and that the
      divergence is a per-document maximum, not a mean);
    - every submission's complete per-gate row (the mixed outcomes live in
      their own columns — no boolean collapse, `CT-INGEST-08`);
    - the per-gate **pass/fail counts** and the quarantine counts **by gate**,
      hand-computed against the reachability table above.

    What is disclosed, not asserted (F3): the named run-level signals
    themselves — `ocr_failure_rate`, the unresolved-mark rate, the mean/max
    divergence aggregates, the second-pass disagreement rate — have no emitter
    anywhere in src/ and no open story owns one; the derivations here are what
    a consumer can compute from the recorded rows today."""
    fx = _Fixture(tmp_data_dir, "run-signals", "c-44")
    catalog, version = fx.catalog(["open"])
    fx.add_roster("ref-1", "ref-2", "ref-3", "ref-4", "ref-5")

    # The ok paper: two pages, both with a text layer — page 1 diverges (the
    # layer lacks the header tokens and the marker protocol the raw transcript
    # carries, F6), page 2 is verbatim, so the recorded divergence is the
    # page-1 maximum and the count is 2.
    layer_one = "student ref-1 the worked answer for the one question"
    page_one = _student_answer(
        "ref-1", _answer_text("Q1", "the worked answer for the one question"))
    ok_source = fx.put(b"ok-source")
    fx.rasterizer.plan[b"ok-source"] = [(1, b"a", 100, 140),
                                        (2, b"b", 100, 140)]
    fx.rasterizer.layers[(b"ok-source", 1)] = layer_one
    fx.rasterizer.layers[(b"ok-source", 2)] = DEFAULT_PAGE_TEXTS[2]
    fx.script(ok_source, {1: page_one, 2: DEFAULT_PAGE_TEXTS[2]})

    # The V0 refusal, the V1 gap, the V2 failure and the V3 unmatched.
    refusing = RefusingSanitizer({b"refused-src"})
    refuse_ingestor = Ingestor(fx.handle, fx.blobs, fx.provider, _model(),
                               SamplingParams(temperature=0.0), fx.rasterizer,
                               residency=fx.slot, sanitizer=refusing)
    v1_source = fx.put(b"v1-gap-src")
    v2_source = fx.put(b"v2-fail-src")
    v3_source = fx.put(b"v3-unmatched-src")
    fx.script(v1_source, {1: "Student: ref-3\nPage 1 of 2, the ink is fresh"})
    fx.script(v2_source, {1: _student_answer("ref-4", _selection("Q1", "resolved", "A"))})
    fx.script(v3_source, {1: "plain prose with no identity line at all"})

    reports = {}
    reports[1] = fx.ingestor.ingest_submission(
        [ok_source], cohort_id=fx.cohort_id, package_version=version,
        package_catalog=catalog, filenames={ok_source: "scan-01.md"})
    refused_source = fx.put(b"refused-src")
    reports[2] = refuse_ingestor.ingest_submission(
        [refused_source], cohort_id=fx.cohort_id, package_version=version,
        package_catalog=catalog, filenames={refused_source: "scan-02.md"})
    reports[3] = fx.ingestor.ingest_submission(
        [v1_source], cohort_id=fx.cohort_id, package_version=version,
        package_catalog=catalog, filenames={v1_source: "scan-03.md"})
    reports[4] = fx.ingestor.ingest_submission(
        [v2_source], cohort_id=fx.cohort_id, package_version=version,
        package_catalog=catalog, filenames={v2_source: "scan-04.md"})
    reports[5] = fx.ingestor.ingest_submission(
        [v3_source], cohort_id=fx.cohort_id, package_version=version,
        package_catalog=catalog, filenames={v3_source: "scan-05.md"})

    # Every recorded row, pinned in full (the masked `'pass'` columns are the
    # F4 disclosure, not an oversight). Keyed by submission_id: `student_ref`
    # is NOT unique here — three of the five record the `unknown` sentinel.
    rows = {row["submission_id"]: dict(row) for row in fx.submission_rows()}
    for index, name in EXPECTED_BY_INDEX.items():
        row = rows[reports[index].submission_id]
        for column, value in EXPECTED_ROWS[name].items():
            assert row[column] == value, (
                f"TC-INGEST-44 ({name}): the recorded {column} is "
                f"{row[column]!r}, expected {value!r}.")
    statuses = {row["ingest_status"] for row in fx.submission_rows()}
    assert statuses <= set(INGEST_STATUSES), (
        f"TC-INGEST-44: the run recorded a status outside the vocabulary: "
        f"{statuses - set(INGEST_STATUSES)}.")
    assert "low_confidence_ocr" not in statuses, (
        "TC-INGEST-44: `low_confidence_ocr` appeared — no ladder path "
        "produces it (F-D); if that changed, this assertion and the ladder "
        "suite's disclosure change with it.")

    # The hand-computed derivations, from the recorded rows restricted to the
    # reachability table (F4: raw-row pass counts overcount).
    def _gate_value(row, gate):
        return row[GATE_COLUMNS[gate]]

    fail_counts = {gate: sum(1 for row in fx.submission_rows()
                             if _gate_value(row, gate) == FAIL_VALUE[gate])
                   for gate in ("v0", "v1", "v2", "v3")}
    assert fail_counts == {gate: len(FAILED[gate]) for gate in FAILED}, (
        f"TC-INGEST-44: the per-gate fail counts moved: {fail_counts}.")
    pass_counts = {
        gate: sum(1 for row in fx.submission_rows()
                  if row["submission_id"] in {
                      reports[i].submission_id for i in PASSED[gate]}
                  and _gate_value(row, gate) == "pass")
        for gate in ("v0", "v1", "v2", "v3")}
    assert pass_counts == {gate: len(PASSED[gate]) for gate in PASSED}, (
        f"TC-INGEST-44: the per-gate pass counts moved: {pass_counts}.")
    quarantine_by_gate: dict[str, int] = {}
    for row in fx.submission_rows():
        if not row["quarantined"]:
            continue
        failed_gates = [gate for gate in ("v0", "v1", "v2", "v3")
                        if _gate_value(row, gate) == FAIL_VALUE[gate]]
        assert len(failed_gates) == 1, (
            f"TC-INGEST-44: a quarantined row names {failed_gates} — the "
            "quarantining gate must be exactly one.")
        quarantine_by_gate[failed_gates[0]] = (
            quarantine_by_gate.get(failed_gates[0], 0) + 1)
    assert quarantine_by_gate == {"v0": 1, "v1": 1, "v2": 1, "v3": 1}, (
        f"TC-INGEST-44: the quarantine counts by gate moved: "
        f"{quarantine_by_gate}.")
    quarantined_indices = {
        index for index, report in reports.items()
        if rows[report.submission_id]["quarantined"]}
    assert quarantined_indices == {2, 3, 4, 5}

    # The text-layer fields: exact names, exact types, exact values.
    document_columns = {row["name"]: row["type"] for row in fx.handle.query(
        "PRAGMA table_info(document)")}
    assert document_columns.get("pages_with_text_layer") == "INTEGER", (
        "TC-INGEST-44: `pages_with_text_layer` is missing or mistyped (OBS-01: "
        "every field present and correctly typed).")
    assert document_columns.get("text_layer_divergence") == "REAL", (
        "TC-INGEST-44: `text_layer_divergence` is missing or mistyped.")
    submission_columns = {row["name"]: row["type"] for row in fx.handle.query(
        "PRAGMA table_info(submission)")}
    for column in list(GATE_COLUMNS.values()) + ["v4_match", "ingest_status"]:
        assert submission_columns.get(column) == "TEXT", (
            f"TC-INGEST-44: the submission's {column} is "
            f"{submission_columns.get(column)!r}, not TEXT.")
    assert submission_columns.get("quarantined") == "INTEGER"
    ok_document = fx.handle.query(
        "SELECT pages_with_text_layer, text_layer_divergence FROM document "
        "WHERE submission_id = :s", s=reports[1].submission_id)[0]
    assert ok_document["pages_with_text_layer"] == 2
    expected_divergence = _divergence(layer_one, page_one)
    assert ok_document["text_layer_divergence"] == pytest.approx(
        expected_divergence, abs=1e-12), (
        f"TC-INGEST-44: the recorded divergence "
        f"{ok_document['text_layer_divergence']} is not the per-document "
        f"maximum the measure gives ({expected_divergence}) — F6's measure is "
        "over the raw transcript, markers included.")
    fx.close()


# -- TC-INGEST-45: the nightly live-medium transcription, quality measured not gated -----------------


def test_tc_ingest_45_the_quality_report_measures_and_reports_without_gating(
        tmp_data_dir):
    """`TC-INGEST-45` — *"Nightly live-medium transcription over F-HAND
    produces per-submission quality measures"*, fast half.

    The **measured-not-gated oracle** (Q-05) runs here at full strength over a
    deterministic two-tier cohort: per legibility tier, the report is the five
    measurements and *nothing else* — no threshold, no pass/fail, no gate key.
    The exact-key-set assertion is the no-gate assertion: a future boolean
    (`"quality_ok"`) or a threshold (`"mean_ocr_conf_floor"`) appearing in the
    shape fails here, and the §6.9 analysis decides what the numbers mean.

    The **live-medium half** is the `live`-marked sibling below: the same
    oracle against the real F-HAND directory and the local inference server,
    env-gated like every real-medium case (the TC-CONFORM-03 precedent)."""
    fx = _Fixture(tmp_data_dir, "quality-report", "c-45")
    fx.add_roster("hana-w", "bram-c")
    legible = fx.put(b"legible-scan")
    fx.script(legible, {1: _student_answer(
        "hana-w",
        "<!-- region: kind=transcribed_text question_id=Q1 state=present "
        "conf=0.9 -->\nthe answer one, cleanly written\n<!-- /region -->")})
    marginal = fx.put(b"marginal-scan")
    fx.script(marginal, {1: _student_answer(
        "bram-c",
        "<!-- region: kind=transcribed_text question_id=Q1 state=present "
        "conf=0.4 -->\nthe answer <unresolved>scrawl</unresolved>\n"
        "<!-- /region -->")})
    for source in (legible, marginal):
        fx.ingestor.ingest_submission([source], cohort_id=fx.cohort_id,
                                      package_version="v0",
                                      filenames={source: "scan-01.md"})

    # The legibility tiers are the F-HAND manifest's own field (the corpus
    # owner labels each member; the analysis groups by it).
    legibility_by_ref = {"hana-w": "legible", "bram-c": "marginal"}
    report = _quality_report(
        legibility_by_ref, _region_rows(fx.handle, fx.cohort_id),
        _unresolved_rows(fx.handle, fx.cohort_id))
    assert report == {
        "legible": {"submissions": 1, "regions": 2, "mean_ocr_conf": 0.9,
                    "unresolved_tokens": 0,
                    "unresolved_tokens_per_1000_regions": 0.0},
        "marginal": {"submissions": 1, "regions": 2, "mean_ocr_conf": 0.4,
                     "unresolved_tokens": 1,
                     "unresolved_tokens_per_1000_regions": 500.0}}, (
        "TC-INGEST-45: the per-tier measurements moved.")
    # The no-gate assertion: the shape is measurements, all the way down.
    assert set(report) == {"legible", "marginal"}
    for numbers in report.values():
        assert set(numbers) == {"submissions", "regions", "mean_ocr_conf",
                                "unresolved_tokens",
                                "unresolved_tokens_per_1000_regions"}, (
            f"TC-INGEST-45: the report grew a key outside the measured shape: "
            f"{sorted(numbers)} — a gate would live there (Q-05).")
        assert not any(isinstance(value, bool) for value in numbers.values()), (
            "TC-INGEST-45: a boolean verdict appeared in the quality report — "
            "measured, not gated.")
    fx.close()


def _live_transcriber_ref() -> ModelRef:
    """The live model ref, exactly the TC-PROV-19 shape: the local server's
    model, `build_id`/`quantization` overridable for an acceptance run."""
    return ModelRef(role="transcriber", provider="ollama",
                    build_id=os.environ.get("HARNESS_LIVE_BUILD_ID",
                                            "local-model"),
                    quantization=os.environ.get("HARNESS_LIVE_QUANTIZATION",
                                                "q4"))


@pytest.mark.live
@pytest.mark.slow
def test_tc_ingest_45_live_the_f_hand_medium_transcribes_end_to_end_with_quality_measured(
        tmp_data_dir):
    """`TC-INGEST-45` — the live half: the real F-HAND PDFs through the real
    sanitizer, the real rasterizer and the local inference server, nightly
    (E2/E3). Skips naming the prerequisite when either half of the medium is
    absent — the TC-CONFORM-03 rule that a skip naming what is missing is the
    honest report. Composition is **asserted** (`composition_problems` empty —
    the one gate Q-05 keeps); quality is **measured, not gated**: the report is
    printed and embedded in the final assertion, and the per-submission status
    must be inside the recorded vocabulary, nothing stronger. The numbers are
    for the §6.9 analysis to judge.

    Disclosed (F10): `pypdfium2` is the live rasterizer's dependency and is
    not in `requirements-dev.txt` — the acceptance-run box installs it
    explicitly, exactly as `PdfiumRasterizer`'s own docstring instructs.
    Disclosed (F9): a live transcription that emits a `described_graphic`
    region fails at the crop seam (`PdfiumRasterizer` implements no `crop`),
    which is the disclosure surfacing live, not the medium misbehaving."""
    from harness.corpora import hand

    corpus_dir = os.environ.get(hand.CORPUS_DIR_ENV)
    if not corpus_dir:
        pytest.skip(
            f"{hand.CORPUS_DIR_ENV} is unset. F-HAND is consented real student "
            f"work under Tier C handling and is never committed (§4.4); the "
            f"nightly live-medium transcription (TC-INGEST-45's live half) "
            f"cannot run until it is arranged.")
    base_url = os.environ.get("LOCAL_INFERENCE_BASE_URL")
    if not base_url:
        pytest.skip(
            "LOCAL_INFERENCE_BASE_URL is unset. The live half transcribes "
            "through the local inference server (the TC-PROV-19 prerequisite); "
            "the fast half above carries the measured-not-gated oracle.")

    from aeh.ingest import PdfiumRasterizer, PypdfSanitizer
    from aeh.prov import LocalServerProvider

    root = Path(corpus_dir)
    manifest_path = root / "manifest.json"
    assert manifest_path.is_file(), (
        f"{hand.CORPUS_DIR_ENV} points at {root}, which has no manifest.json "
        "(the corpus declares its own composition).")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems = hand.composition_problems(manifest)
    assert not problems, (
        f"TC-INGEST-45 live: the F-HAND corpus at {root} is not the nightly "
        f"medium ({problems}) — composition is the one asserted half (Q-05).")

    fx = _Fixture(tmp_data_dir, "live-medium", "c-45-live")
    live_provider = LocalServerProvider(base_url=base_url, transport=None)
    ingestor = Ingestor(fx.handle, fx.blobs, live_provider,
                        _live_transcriber_ref(), SamplingParams(temperature=0.0),
                        PdfiumRasterizer(), residency=fx.slot,
                        sanitizer=PypdfSanitizer())
    members = manifest["submissions"]
    members_by_blob = []
    for member in members:
        pdf_path = root / f"{member['id']}.pdf"
        assert pdf_path.is_file(), (
            f"TC-INGEST-45 live: the manifest member {member['id']!r} has no "
            f"scan at {pdf_path}.")
        members_by_blob.append((member, fx.blobs.put(pdf_path.read_bytes())))
    fx.add_roster(*(member["student_ref"] for member, _ in members_by_blob))
    reports = []
    for member, blob in members_by_blob:
        reports.append(ingestor.ingest_submission(
            [blob], cohort_id=fx.cohort_id, package_version="v0",
            filenames={blob: f"{member['id']}.pdf"}))
    rows = {row["student_ref"]: dict(row) for row in fx.submission_rows()}
    assert set(rows) == set(refs), (
        f"TC-INGEST-45 live: the medium did not produce a submission row per "
        f"member: {sorted(rows)} vs {sorted(refs)}.")
    for ref, row in rows.items():
        assert row["ingest_status"] in INGEST_STATUSES, (
            f"TC-INGEST-45 live: {ref} recorded {row['ingest_status']!r}, "
            f"outside the vocabulary {INGEST_STATUSES}.")
    report = _quality_report(
        {member["student_ref"]: member.get("legibility") for member in members},
        _region_rows(fx.handle, fx.cohort_id),
        _unresolved_rows(fx.handle, fx.cohort_id))
    measured = json.dumps(report, indent=2, sort_keys=True)
    print(f"\nTC-INGEST-45 live quality report (measured, not gated):\n{measured}")
    assert report, (
        "TC-INGEST-45 live: the quality report is empty — no legible tier "
        "over the corpus? Manifest legibilities: "
        f"{[m.get('legibility') for m in members]}.\n{measured}")
    fx.close()


# -- TC-INGEST-46: the transcriber's residency slot across a cohort run ------------------------------


def test_tc_ingest_46_the_residency_slot_unloads_at_every_document_boundary_of_a_cohort_run(
        tmp_data_dir):
    """`TC-INGEST-45`/`TC-INGEST-46` — rung 4: the VLM's own residency slot.

    The discipline asserted is the pipeline-level one, over a real
    three-document run:

    - **held through the document** — every model call of every document runs
      with the transcriber holding the slot (`provider.holders`, recorded at
      call time), and a judge probe spawned *inside* a page call cannot barge
      in before the document ends;
    - **unloaded at every document boundary** — a judge probe spawned inside
      document N acquires the slot between document N and N+1: it could only
      get through if the transcriber unloaded at that boundary;
    - **empty at stage end** — after the last document, no role holds.

    The judge probe is a plain `acquire`/`release` pair on the slot itself;
    `TC-INGEST-36` already covers the slot's blocking mechanics in isolation,
    so this case pins what the *run* does with the slot, not the primitive.
    Disclosed (F11): the E4 residency-policy swap (the judge and the
    transcriber co-resident by policy) is story territory (#62/#59) — this
    case pins the exclusive default the shipped pipeline actually runs."""
    fx = _Fixture(tmp_data_dir, "residency-boundaries", "c-46")
    sources = []
    for index in (1, 2, 3):
        ref = f"s-{index}"
        source = fx.put(f"src-{index}".encode())
        fx.rasterizer.plan[f"src-{index}".encode()] = [
            (1, b"a", 100, 140), (2, b"b", 100, 140)]
        fx.script(source, {
            1: _student_answer(ref, _answer_text("Q1", f"the answer of {ref}")),
            2: DEFAULT_PAGE_TEXTS[2]})
        sources.append(source)
    fx.add_roster("s-1", "s-2", "s-3")

    judge_threads: list[threading.Thread] = []
    for document_index, source in enumerate(sources, start=1):
        judge_through = threading.Event()

        def judge_try():
            fx.slot.acquire("judge")
            judge_through.set()
            fx.slot.release("judge")

        def on_call(key, fields):
            del key, fields
            position = len(fx.provider.holders)  # the current call included
            if position % 2 == 1:
                # The first page call of a document: the judge probe starts
                # while the transcriber is mid-call.
                probe = threading.Thread(target=judge_try, name="judge-probe")
                judge_threads.append(probe)
                probe.start()
            else:
                # The second page call, still inside the same document: the
                # judge must still be waiting — no unload mid-document.
                assert not judge_through.is_set(), (
                    f"TC-INGEST-46: the judge acquired the slot between the "
                    f"pages of document {document_index} — the transcriber "
                    "does not hold the slot through its document.")
            assert fx.slot._holder == "transcriber", (
                f"TC-INGEST-46: mid-call holder is {fx.slot._holder!r} "
                f"(document {document_index}, call {position}).")

        fx.provider.on_call = on_call
        fx.ingestor.ingest_submission(
            [source], cohort_id=fx.cohort_id, package_version="v0",
            filenames={source: f"scan-{document_index:02d}.md"})

        # The boundary: the judge — spawned inside this document's calls —
        # gets through exactly here, because the transcriber unloaded. (The
        # judge is the only contender while this wait runs: the next document
        # is not started until after it.)
        assert judge_through.wait(5.0), (
            f"TC-INGEST-46: the judge probe never acquired the slot at the "
            f"boundary of document {document_index} — the transcriber did "
            "not unload.")
        judge_threads[-1].join(5.0)
        assert not judge_threads[-1].is_alive(), (
            f"TC-INGEST-46: the judge probe for document {document_index} "
            "did not release the slot.")
        assert fx.slot._holder is None, (
            f"TC-INGEST-46: after document {document_index}'s boundary the "
            f"slot is held by {fx.slot._holder!r}.")

    assert fx.provider.holders == ["transcriber"] * 6, (
        f"TC-INGEST-46: the recorded mid-call holders moved: "
        f"{fx.provider.holders}.")
    assert fx.slot._holder is None, (
        "TC-INGEST-46: the stage finished with the slot still held.")
    statuses = [row["ingest_status"] for row in fx.submission_rows()]
    assert statuses == ["ok"] * 3, (
        f"TC-INGEST-46: the run itself did not complete cleanly: {statuses}.")
    fx.close()


# -- TC-INGEST-47: the cohort-shape wall clock, measured ---------------------------------------------


def test_tc_ingest_47_ingestion_wall_clock_over_the_full_cohort_shape_is_measured(
        tmp_data_dir):
    """`TC-INGEST-47` — *"Cohort-scale ingestion (350 submissions × ~4 pages)
    stays within measured wall-clock bounds (PERF-02)"*, rung 4.

    The **shape** is asserted exactly: 350 rostered submissions, four pages
    each, all through the scripted transcriber — 1400 model calls, 350
    submission rows, 350 documents, 1400 regions, every status `ok`. The
    **wall clock** is measured with `time.perf_counter` around the whole loop
    and reported — printed, and embedded in the final assertion message — but
    **not gated**: no threshold here, because the calibrated budget belongs to
    PERF-02's acceptance run, not to an integration suite whose absolute
    timing is machine-dependent (the env-knob rule; deferring the gate to
    #62/#146, TS-53's performance story). What this case pins is that the
    cohort shape *runs* end to end and that the number a run produces is the
    number the report carries."""
    fx = _Fixture(tmp_data_dir, "wall-clock", "c-47")
    refs = [f"s-{index:04d}" for index in range(350)]
    fx.add_roster(*refs)
    sources = []
    for ref in refs:
        source = fx.put(f"src-{ref}".encode())
        fx.rasterizer.plan[f"src-{ref}".encode()] = [
            (page_no, bytes([page_no]), 100, 140) for page_no in (1, 2, 3, 4)]
        fx.script(source, {
            1: f"Student: {ref}\nthe written first page of the paper of {ref}",
            2: DEFAULT_PAGE_TEXTS[2], 3: DEFAULT_PAGE_TEXTS[3],
            4: DEFAULT_PAGE_TEXTS[4]})
        sources.append(source)

    started = time.perf_counter()
    for source in sources:
        fx.ingestor.ingest_submission([source], cohort_id=fx.cohort_id,
                                      package_version="v0",
                                      filenames={source: "scan.md"})
    elapsed = time.perf_counter() - started
    per_call_ms = 1000.0 * elapsed / 1400
    measured = (f"wall clock {elapsed:.3f}s over 350 submissions x 4 pages "
                f"(1400 transcriber calls), {per_call_ms:.3f} ms per call")
    print(f"\nTC-INGEST-47 measured: {measured}")

    assert len(fx.provider.calls) == 1400, (
        f"TC-INGEST-47: the run made {len(fx.provider.calls)} model calls, "
        "not the 1400 the shape demands.")
    rows = fx.submission_rows()
    assert len(rows) == 350, (
        f"TC-INGEST-47: {len(rows)} submission rows recorded, not 350.")
    assert {row["ingest_status"] for row in rows} == {"ok"}, (
        f"TC-INGEST-47: the cohort did not ingest cleanly: "
        f"{ {row['ingest_status'] for row in rows} }.")
    assert fx.handle.query(
        "SELECT COUNT(*) AS n FROM document")[0]["n"] == 350
    assert fx.handle.query(
        "SELECT COUNT(*) AS n FROM document_region")[0]["n"] == 1400
    assert elapsed > 0.0, f"TC-INGEST-47 measured: {measured}"
    fx.close()
