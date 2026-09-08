"""Shared doubles and fixtures for the `M-INGEST` contract suite (issue #49).

The suite behind `TC-INGEST-C01..C20` (test plan §6.11.5). The doubles carry the
same shapes the integration and security suites pin — `ScriptedRasterizer`,
`ScriptedProvider`, a pass-through sanitizer — because the clause cases hold at the
same seams; what is different is what each case *asserts*: the §4.7 clause text, at
contract strength, rather than the FR behaviour.

Written from an implementation audit that probed the shipped module (`aeh.ingest`,
issues #36..#42 all closed; `Written ahead of implementation: yes` in the issue
body is stale — the suite runs green by design). The audit found five places where
a clause's guarantee is not yet enforced on shipped code; a bug in shipped code has
no `writtenahead` target to key on, so they are **disclosed in the case that names
them rather than shipped red**:

- **G1** (`low_confidence_ocr`, `CT-INGEST-08`/`C10`): the status is in the
  declared vocabulary and the column's CHECK admits it, but no path in the ladder
  ever assigns it — the per-region `conf=` tag is stored (C04 probes it) and the
  aggregate that would lower confidence into a status is not computed. Probe:
  regions tagged `conf=0.05` ingest `ok`.
- **G2** (`ocr_conf` non-null, `CT-INGEST-04`): the parser validates
  `region_kind` and `content_state` against their domains but reads `conf=`
  permissively — a region tagged without `conf=` stores NULL and no gate notices.
  The hole is WIDER than a missing tag on a tagged region: every region without
  a `conf=` attribute stores NULL — which is every OUTSIDE-MARKER fragment, e.g.
  the `Student:` head every submission transcript carries, so the common shape
  of a real transcript already includes NULL-conf rows. The clause's non-null
  guarantee holds only for well-formed TAGGED regions; the probe is in
  `test_ct_ingest_region_domains.py`'s docstring.
- **G3** (transcription 3-strikes, `CT-INGEST-14`): there is no transcription
  retry loop — the only re-request loop is the evaluative-description one
  (`EVALUATIVE_RETRIES_ENV`). A provider fault on transcription escapes
  `ingest_submission` raw (only `IngestGapError` / `IngestDuplicateError` /
  `IngestError` are caught), leaving the submission row with NULL gate columns and
  `quarantined=0`. `NFR-INGEST-02` ("fail the unit, never the run") and
  `TC-INGEST-40` (P0) promise containment. The case asserts the half that holds
  today (no row reaches `ok`; no document is written) and discloses the rest.
- **G4** (aggregate observability signals, `CT-INGEST-19`): `ocr_failure_rate`,
  the unresolved-mark rate and per-gate counts are not emitted anywhere —
  `TC-INGEST-44` (TS-19, issue #48) is open. The case pins the *producer
  artifacts* the aggregates would be computed from, at the columns the schema
  already carries.
- **G5** (span identity, `CT-INGEST-03`): `work_unit` carries no `document_id`
  column, so a span's work-ID-mismatch detection is `M-EXTRACT`/`M-INTEG`'s to
  hold; the producer half pins the durability the offsets point into.
"""

from __future__ import annotations

import re

from aeh.conf import ModelRef
from aeh.ingest import (
    INGEST_STATEMENTS,
    IngestSanitizeError,
    Ingestor,
    PageImage,
    PdfSanitizer,
    ResidencySlot,
    SanitizeResult,
)
from aeh.prov import Completion, SamplingParams
from aeh.store import open_store
from tests.support.store_api import statement

ISSUE = "#49"

#: The cohort handle name the fixtures open. One cohort file IS one cohort.
COHORT = "c-ingest-ct"

#: The `ingest_status` vocabulary (FR-INGEST-29 / the submission CHECK).
INGEST_STATUSES = ("ok", "low_confidence_ocr", "unreadable", "incomplete",
                   "unmatched_assessment")

#: The tables `M-INGEST`'s declared statements write — the whole write surface
#: CT-INGEST-17 holds at the module level.
INGEST_OWNED_TABLES = frozenset({
    "document", "document_region", "submission", "unresolved_token",
    "token_cluster", "assessment_match_proposal", "v4_cohort_breaker",
})

#: The score-bearing tables the module must never touch (CT-INGEST-09/17): the
#: store's schema declares them in the COHORT database (the only handle an
#: ingestor holds), and M-INGEST's routing never names them. The `band` table is
#: a PACKAGE-schema definition table (band definitions per criterion, grading
#: policy territory) — it is not in a cohort's schema at all; the static
#: statement-text sweep still checks its name.
SCORE_TABLES = frozenset({
    "criterion_score", "submission_grade", "verdict",
    "review_queue", "narrative", "evidence", "work_unit",
})


def model_ref(build: str = "vlm@sha256:cccc") -> ModelRef:
    """A transcriber `ModelRef`; `build` varies where a case varies the build."""
    return ModelRef(role="transcriber", provider="local", build_id=build,
                    quantization="q4")


# -- the scripted seams --------------------------------------------------------------------------------


class ThroughSanitizer(PdfSanitizer):
    """The fast-tier sanitizer double: no constructs, the bytes pass through."""

    def sanitize(self, pdf_bytes, *, strip=True, max_decompressed_bytes=None,
                 max_embedded_objects=None, deadline=None):
        return SanitizeResult(pdf_bytes=pdf_bytes)


class RefusingSanitizer(PdfSanitizer):
    """Refuses every source the way the live sanitizer refuses an unreadable one —
    before any rasterization, so the V0 stage must resolve to quarantine."""

    def __init__(self, message: str) -> None:
        self.message = message
        self.asked: list[bytes] = []

    def sanitize(self, pdf_bytes, *, strip=True, **kwargs):
        self.asked.append(bytes(pdf_bytes))
        raise IngestSanitizeError(self.message)


class ScriptedRasterizer:
    """A rasterizer double: `plan` maps source bytes to a page list; every call —
    rasterize, crop, text_layer — is recorded in order, so a case can prove a
    stage never ran and prove the order two stages ran in."""

    def __init__(self, plan: dict | None = None,
                 default_pages: list | None = None) -> None:
        self.plan = plan or {}
        self.default_pages = ([(1, b"page-one", 100, 140)]
                              if default_pages is None else default_pages)
        self.events: list[tuple[str, ...]] = []

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        self.events.append(("rasterize", bytes(pdf_bytes)))
        pages = self.plan.get(bytes(pdf_bytes), self.default_pages)
        return [PageImage(page_no=page_no, png=png, width_px=w, height_px=h)
                for page_no, png, w, h in pages]

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:
        self.events.append(("crop", bytes(pdf_bytes), page_no))
        return b"crop-of-page"

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        self.events.append(("text_layer", bytes(pdf_bytes), page_no))
        return self.layer.get((bytes(pdf_bytes), page_no), "") \
            if hasattr(self, "layer") else ""


class ScriptedProvider:
    """A provider double keyed per (source blob, page) — one deterministic
    `Completion` per call, every call recorded in order."""

    def __init__(self, texts: dict | None = None) -> None:
        self.texts = texts or {}
        self.calls: list[tuple[str, int]] = []

    def complete(self, prompt, model_ref, params) -> Completion:
        fields = dict(prompt.fields)
        # The escalation payload (V4's model-assisted band) carries no page
        # identity — the key degrades to ("", 0) and the default reply stands.
        key = (fields.get("source_blob_hash", ""),
               int(fields.get("page_no") or 0))
        self.calls.append(key)
        return Completion(text=self.texts.get(key, "plain page"),
                          tokens_in=1, tokens_out=1, latency_ms=1,
                          resolved_build=model_ref.build_id,
                          cached_prefix_tokens=0, cost=None)


class SequencedProvider(ScriptedProvider):
    """A provider double whose answers ADVANCE per call: `sequences` maps
    (source blob, page) to a list of texts handed out in call order (the last
    one repeats). This is how a re-request loop is scripted — first answer
    rejected, second accepted — without a second fixture."""

    def __init__(self, sequences: dict | None = None) -> None:
        super().__init__()
        self.sequences = sequences or {}

    def complete(self, prompt, model_ref, params) -> Completion:
        fields = dict(prompt.fields)
        key = (fields.get("source_blob_hash", ""),
               int(fields.get("page_no") or 0))
        self.calls.append(key)
        queue = self.sequences.get(key)
        if not queue:
            text = "plain page"
        elif len(queue) == 1:
            text = queue[0]
        else:
            text = queue.pop(0)
        return Completion(text=text, tokens_in=1, tokens_out=1, latency_ms=1,
                          resolved_build=model_ref.build_id,
                          cached_prefix_tokens=0, cost=None)


class RecordingResidency:
    """A residency slot that records its acquire/release events while delegating
    the exclusivity to a real `ResidencySlot` — the event list is the oracle for
    "unload before the judge loads" (CT-INGEST-18): the event list must never
    carry a second `acquire` between an unmatched `acquire` and its `release`."""

    def __init__(self, exclusive: bool = True) -> None:
        self._slot = ResidencySlot(exclusive=exclusive)
        self.events: list[tuple[str, str]] = []

    def acquire(self, role: str = "transcriber") -> None:
        self.events.append(("acquire", role))
        self._slot.acquire(role)

    def release(self, role: str = "transcriber") -> None:
        self.events.append(("release", role))
        self._slot.release(role)

    def holds(self, role: str = "transcriber") -> bool:
        """Whether the underlying slot currently holds `role` — probed from
        another thread by the blocking half of CT-INGEST-18."""
        return self._slot._holder == role  # noqa: SLF001 -- test-side probe


# -- the contract fixture --------------------------------------------------------------------------------


class Contract:
    """One fresh store, cohort, blob dir and ingestor over them — the rung-2
    world (real SQLite, real blob directory, real package catalog) with the
    model, sanitizer and rasterizer seams scripted."""

    def __init__(self, tmp_data_dir, name: str, *, sanitizer=None,
                 rasterizer: ScriptedRasterizer | None = None,
                 provider: ScriptedProvider | None = None,
                 residency: bool = True, build: str = "vlm@sha256:cccc",
                 ) -> None:
        self.root = tmp_data_dir / f"49-{name}"
        self.store = open_store(self.root)
        self.blobs = self.store.blobs()
        self.handle = self.store.cohort(COHORT)
        with self.handle.transaction() as tx:
            tx.execute(statement(
                "INSERT OR IGNORE INTO cohort (cohort_id, consent_class, "
                "created_at) VALUES ('c-ingest-ct', 'synthetic', 'x')",
                issue=ISSUE))
        self.rasterizer = rasterizer or ScriptedRasterizer()
        self.provider = provider or ScriptedProvider()
        self.model = model_ref(build)
        self.residency = RecordingResidency() if residency else None
        self.ingestor = Ingestor(
            self.handle, self.blobs, self.provider, self.model,
            SamplingParams(temperature=0.0), self.rasterizer,
            residency=self.residency,
            sanitizer=sanitizer or ThroughSanitizer())

    # -- inputs --------------------------------------------------------------------------------

    def put(self, content: bytes) -> str:
        return self.blobs.put(content)

    def script(self, source: str, page_texts: dict[int, str]) -> None:
        for page_no, text in page_texts.items():
            self.provider.texts[(source, page_no)] = text

    def add_roster(self, *refs: str) -> None:
        with self.handle.transaction() as tx:
            for ref in refs:
                tx.execute(statement(
                    "INSERT INTO roster (cohort_id, student_ref) "
                    "VALUES ('c-ingest-ct', :r)", issue=ISSUE), r=ref)

    def catalog(self, kinds: list[str], *, options: dict | None = None):
        """A package catalog whose version is bound to `self` by identity: the
        declared question ids are `Q1..Qn` in the given `kinds`. `options` maps
        question id -> option ids, declared as mcq options where given."""
        from aeh.pkg import PackageCatalog, PackageDraft

        seed = self.store.package("pkg-49")
        with seed.transaction() as tx:
            tx.execute(statement(
                "INSERT INTO package (package_id, created_at) "
                "VALUES ('pkg-49', 'x')", issue=ISSUE))
        catalog = PackageCatalog(seed, package_id="pkg-49")
        version = catalog.create_version(None, PackageDraft(title="ct-49"))
        for index, kind in enumerate(kinds, start=1):
            criterion_id = f"C{index}"
            question_id = f"Q{index}"
            catalog.add_criterion(version, criterion_id,
                                  question_id=question_id, kind=kind,
                                  max_points=4.0)
            if (options or {}).get(question_id):
                catalog.set_mcq_options(
                    version, criterion_id,
                    [(option, option) for option in options[question_id]])
        return catalog, version

    # -- reads (declared statements; the contract suite never passes raw SQL) ----

    def submission_rows(self) -> list:
        return self.handle.query(statement(
            "SELECT submission_id, cohort_id, student_ref, v0_integrity, "
            "v1_pages, v2_structure, v3_identity, v4_match, v4_signals, "
            "ingest_status, quarantined FROM submission", issue=ISSUE))

    def documents(self, where: str = "", **params) -> list:
        tail = f" WHERE {where}" if where else ""
        return self.handle.query(statement(
            "SELECT document_id, submission_id, content_hash, markdown, "
            "transcriber_ref, prompt_template_version, kind, parent_doc_id, "
            "source_blobs, pages_with_text_layer, text_layer_divergence, "
            "created_at FROM document" + tail, issue=ISSUE), **params)

    def regions(self, document_id: str | None = None) -> list:
        if document_id is None:
            return self.handle.query(statement(
                "SELECT * FROM document_region", issue=ISSUE))
        return self.handle.query(statement(
            "SELECT * FROM document_region WHERE document_id = :d",
            issue=ISSUE), d=document_id)

    def table(self, name: str, columns: str = "*"):
        return self.handle.query(statement(
            f"SELECT {columns} FROM {name}", issue=ISSUE))

    def close(self) -> None:
        self.store.close()


# -- transcript builders -------------------------------------------------------------------------------


def student_answer(name: str | None, *regions: str) -> str:
    """A page transcript: the carried-over identity head, then region markers."""
    head = f"Student: {name}\n" if name else ""
    return head + "\n".join(regions)


def answer_text(question_id: str, body: str, *, conf: str = "0.97",
                state: str = "present") -> str:
    """A `transcribed_text` region tag, the common case."""
    parts = [f"kind=transcribed_text question_id={question_id}"]
    if conf:
        parts.append(f"conf={conf}")
    if state != "present":
        parts.append(f"state={state}")
    return ("<!-- region: " + " ".join(parts) + " -->\n" + body
            + "\n<!-- /region -->")


def selection_mark(question_id: str, state: str = "resolved",
                   option: str | None = "A", conf: str = "0.93") -> str:
    """A `selection_mark` region tag. `option=None` omits the option attribute —
    the malformed-mark shape the C05 probe reads."""
    parts = [f"kind=selection_mark question_id={question_id}",
             f"selection_state={state}", f"conf={conf}"]
    if option is not None:
        parts.append(f"selection={option}")
    return ("<!-- region: " + " ".join(parts) + " -->\nthe mark as seen\n"
            "<!-- /region -->")


def graphic_mark(question_id: str, description: str, element: str =
                 "graph_or_plot", crop: str | None = "0,0,10,10",
                 conf: str = "0.95") -> str:
    """A `described_graphic` region tag: description in the body, optional crop
    box — the crop is what `_retain_crops` retains into the blob store. The
    prompt's confidence tag rides on every region."""
    parts = [f"kind=described_graphic element_kind={element}",
             f"question_id={question_id}", f"conf={conf}"]
    if crop:
        parts.append(f"crop={crop}")
    return ("<!-- region: " + " ".join(parts) + " -->\n" + description
            + "\n<!-- /region -->")


# -- static readers over the declared registry ----------------------------------------------------------


def statement_texts() -> dict[str, str]:
    """Every declared statement's SQL, keyed by its registry name."""
    return {name: (item.sql if hasattr(item, "sql") else str(item))
            for name, item in INGEST_STATEMENTS.items()}


def written_tables() -> set[str]:
    """Every table `aeh.ingest`'s declared statements write — the module's whole
    write surface, read from the declared-literal registry rather than from a
    database at runtime, so a new write cannot pass unnoticed."""
    pattern = re.compile(r"(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE|"
                         r"DELETE\s+FROM)\s+([a-z0-9_]+)", re.IGNORECASE)
    tables: set[str] = set()
    for sql in statement_texts().values():
        tables.update(match.group(1).lower() for match in pattern.finditer(sql))
    return tables
