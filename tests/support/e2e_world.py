"""The assembled-system world the three TC-E2E journeys share (issue #144).

TS-51's three journeys run the ASSEMBLED system - every module real, no doubles at
module boundaries (`§4.2`'s rung 4). The model boundary is the only double anywhere,
and it is the shipped `RecordedFixtureProvider` in its regeneration-then-replay shape
(the journey-1 and smoke-suite precedent): a first sight of a request is answered by
the journey's own computation and **recorded through the shipped
`record()`/request-key machinery**; every later identical request replays from the
recording. `RecordedFixtureProvider` stays the only egress (`CT-PROV-10`).

The world synthesizes the reference package (`harness.corpora.reference_package`) and
the `F-SYNTH` cohort (`harness.corpora.synth`) into REAL ingested documents - one
4-page PDF per submission through the real gateway (real sanitizer, real rasterizer,
one transcription call per page), the region-marker protocol, and the package's
catalog built through the real `M-PKG` writer - then drives the overnight run through
the real orchestrator, deterministic evaluator, extraction workers, integrity gate,
aggregation walk and synthesis worker. Nothing here doubles a module.

**Disclosed shapes** (each read from the shipped modules, not invented):

- **MCQ band names.** The world's catalog declares the deterministic two-band scale
  (`incorrect` / `correct`, the smoke suite's catalog precedent), not the corpus's
  `met` / `not_met` setup default - `M-DET` looks the band up in the run's catalog
  (`det._points` refuses an undeclared band), so the world declares the names det
  scores with.
- **One selection mark on Q5.** Each submission carries ONE resolved `selection_mark`
  region on Q5 (the C-13 item's choice); `M-DET` reads that one mark for all three
  mcq criteria (C-14/C-15 read the same selection). Several marks would parse as
  `multiple_marks` - unresolved - and the mcq answer text stays OUTSIDE the markers
  because V2 fails prose tagged a declared mcq question.
- **V4 semantic floor 0.0.** `HARNESS_INGEST_V4_SEMANTIC_FLOOR` is shipped at 0.10;
  this world pins it to 0.0 so the fully-absent submission (SYN-001, ability 0.0,
  every criterion `absent`) clears the semantic signal at zero word-level Jaccard
  (`aggregate >= floor` holds at 0.0 >= 0.0). A floor above 0 would quarantine it as
  `uncertain`, breaking the 9-quarantine oracle and risking the cohort breaker. The
  identifier and structural signals still do real work, and the v4_signals record
  the honest score and floor.
- **Quarantine indices.** Nine mid-range indices (10..250) drop the `Student:` line,
  so V3 identity fails (`unmatched` -> `incomplete`) while V4 still matches; the
  corpus extremes (SYN-001 fully absent, SYN-350 fully secure) stay graded.
- **Random arms off.** `HARNESS_ORCH_RANDOM_ARM_RATE="0"` - the seeded draw is the
  escalation ladder's own mechanism, and the journeys pin deterministic panels.
- **Escalation budget 1.0, breaker rate 1.0 for the happy walk.**
  `HARNESS_ORCH_ESCALATION_BUDGET="1.0"` (the c09 contract precedent) so the widened
  units dispatch in the same drive, and `HARNESS_ORCH_CRITERION_BREAKER_RATE="1.0"`
  so the interior-band escalation share (roughly three quarters of the cells here is
  the honest rate, far above half) cannot trip the criterion breaker mid-journey -
  the first-window share the breaker reads would trip at the shipped 0.50. The
  breaker's own trip behavior is the breaker variant's subject and M-ORCH's contract
  suite.
- **The second extraction family runs.** Every open criterion is on the injected
  high-risk register, so the worker extracts twice on a different family and the
  payload carries both span sets. The gate's `extractor_disagreement` reads
  `False` (measured agreement) rather than `None` (not measured, fail-closed) -
  the honest assembled-system shape, and it keeps the escalation ladder driven by
  the interior-band limb alone.
- **Pre-judge panel reads are the neutral constant.** The gate's read model derives
  the panel's sufficiency flags from the stored verdict rows once they exist; before
  they exist the view reports the neutral all-sufficient constant, because a panel
  read before its judges answered is reported either way only by guessing.
- **Region extents are read-model reconciliations.** `document_region` carries no
  byte-extent columns (the TS-28 disclosure stands); the view computes each region's
  extent by locating the region's stored content in the document's canonical
  Markdown - the same reconciliation the shipped `ExtractionView` vocabulary names.
- **`f"doc-{submission_id}"` request spelling.** The gate asks for regions by the
  `doc-<submission_id>` spelling (its own id form), while ingest mints
  `doc-<uuid12>` ids; the view resolves the request against the document table's
  submission foreign key - the one line that changes when the extents land.
"""

from __future__ import annotations

# The eleven-module import chain FIRST (CLAUDE.md): every contributor's migrations
# must be registered before the first store open in any process.
import aeh.agg  # noqa: F401
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401

import hashlib
import json
import os
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from aeh.agg import aggregate, should_escalate
from aeh.conf import CohortRef, ModelRef, resolve_run_config
from aeh.det import DeterministicEvaluator
from aeh.extract import ExtractionWorker, assemble_request, prompt_fields
from aeh.grade import open_grade
from aeh.ingest import Ingestor, PdfiumRasterizer, PypdfSanitizer, ResidencySlot
from aeh.integ import IntegrityGate
from aeh.judge import ScoringWorker
from aeh.judge import prompt_fields as judge_prompt_fields
from aeh.orch import (
    CRITERION_BREAKER_MIN_N_ENV,
    CRITERION_BREAKER_RATE_ENV,
    DECISION_HALTED_BY_BREAKER,
    ESCALATION_BUDGET_ENV,
    LEASE_SECONDS_ENV,
    STAGE_DETERMINISTIC,
    STAGE_EXTRACT,
    STAGE_SCORE,
    SWEEP1_ADMITTED_INGEST_STATUSES,
    Orchestrator,
)
from aeh.pkg import GradePolicy, PackageCatalog
from aeh.prov import (
    Completion,
    FixtureMissingError,
    ProviderUnavailableError,
    RecordedFixtureProvider,
    SamplingParams,
)
from aeh.store import open_store
from aeh.synth import LEVEL_L1, LEVEL_L2, SynthesisWorker
from harness.corpora import reference_package as corpus
from harness.corpora import synth as corpus_synth
from harness.corpora.pdf_writer import typed_document
from tests.support.agg_vocabulary import (
    agg_config,
    criterion as agg_criterion,
    criterion_history,
    expected_distribution,
    signals as agg_signals,
)
from tests.support.conf_builders import edge_cfg, edge_panel
from tests.support.extract_vocabulary import (
    sampling_params,
    span_completion,
    verdict_completion,
)

ISSUE = "#144"

#: The package identity the corpus declares (and the V4 identifier signal reads).
PKG_ID = corpus.PACKAGE_ID

E2E_COHORT_ID = "coh-e2e-overnight"
E2E_RUN_ID = "run-e2e-overnight"

TRANSCRIBER_BUILD = "vlm@sha256:e2e02-transcribe"
EXTRACT_BUILD = "vlm@sha256:e2e02-extract"
#: The second family - a DIFFERENT build on the same role (`FR-EXTRACT-07` refuses
#: the same provider/build pair).
EXTRACT_SECOND_BUILD = "vlm@sha256:e2e02-extract-b"
SYNTH_BUILD = "vlm@sha256:e2e02-synth"

#: The nine quarantines: mid-range, spread, away from the pinned extremes - SYN-001
#: (fully absent) and SYN-350 (fully secure) both stay graded.
QUARANTINE_INDICES = (10, 40, 70, 100, 130, 160, 190, 220, 250)

STAMP = "2026-01-01T00:00:00+00:00"

#: The grade boundaries the world declares - inclusive scaled floors, single table.
GRADE_BOUNDARIES = (("A", 33.0), ("B", 24.0), ("C", 15.0), ("D", 0.0))

#: The MCQ band names det scores with (disclosed at the module docstring).
MCQ_BANDS = (("incorrect", 0, 0.0), ("correct", 1, 1.0))

#: The env knobs the world pins at construction. DPI is the journey-1 value; the
#: floor and the random-arm rate carry their disclosure in the module docstring.
WORLD_ENV = {
    "HARNESS_INGEST_DPI": "72",
    "HARNESS_INGEST_V4_SEMANTIC_FLOOR": "0.0",
    "HARNESS_ORCH_RANDOM_ARM_RATE": "0",
}


def _transliterate(text: str) -> str:
    """ASCII-safe form of a page text for the typed renderer's ASCII content streams."""
    return text.encode("ascii", "replace").decode("ascii")


def _pdf_of(pages: list[str]) -> bytes:
    """A REAL PDF carrying `pages` in order - the shipped typed-document renderer, the
    same bytes a teacher's printed-to-PDF booklet enters the gateway by. The journey-1
    precedent: the canonical transcript is the staged reply, not the PDF's bytes, so
    ASCII transliteration loses nothing the pipeline reads."""
    return typed_document([_transliterate(page) for page in pages])


def _region_header(kind: str, question_id: str, conf: float,
                   selection: str | None = None) -> str:
    """One region-marker header; the parser reads the pairs in any order. A resolved
    selection mark carries BOTH attributes the honest-mark rule reads
    (`FR-INGEST-17`: `selection_state=resolved` naming the option in `selection` - a
    resolved state naming no option is stored ambiguous, never resolved with NULL)."""
    header = (
        f"<!-- region: kind={kind} question_id={question_id} "
        f"conf={conf} state=present"
    )
    if selection is not None:
        header += f" selection_state=resolved selection={selection}"
    return header + " -->"


def _wrap_region(kind: str, question_id: str, conf: float, body: str,
                 selection: str | None = None) -> str:
    """A body wrapped in its marker pair - the marker protocol's stored form."""
    return (
        f"{_region_header(kind, question_id, conf, selection)}\n"
        f"{body}\n"
        f"<!-- /region -->"
    )


def _ordinal_of(submission: corpus_synth.SyntheticSubmission, criterion_id: str) -> int:
    """The ordinal the submission's corpus band sits at."""
    for band in corpus.BY_ID[criterion_id].bands:
        if band.band == submission.bands[criterion_id]:
            return band.ordinal
    raise KeyError(
        f"{submission.bands[criterion_id]!r} is not a band of {criterion_id}"
    )


def _q5_choice(item_lines: list[str], criterion_id: str = "C-13") -> str:
    """The choice the corpus's page-4 item lines carry for `criterion_id` - the ONE
    letter the world's selection mark records (disclosed: one mark for all three mcq
    criteria)."""
    prefix = f"{criterion_id}: "
    for line in item_lines:
        if line.startswith(prefix):
            choice = line[len(prefix):].strip()
            assert choice in corpus.MCQ_OPTIONS, (
                f"fixture bug: {line!r} carries no declared option")
            return choice
    raise AssertionError(
        f"fixture bug: the corpus page 4 carries no {criterion_id} item line")


def _marked_pages(submission: corpus_synth.SyntheticSubmission,
                  *, with_student: bool) -> list[str]:
    """The submission's four page transcripts, region-marked per the marker protocol.

    Pages 1-3: the question's rendered criteria wrapped in one `transcribed_text`
    region tagged the question id. Page 4: the Q4 region, then the Q5 block - ONE
    resolved `selection_mark` region (the C-13 item's choice, non-empty body so the
    parser keeps it) with the three item lines OUTSIDE any marker, because V2 fails
    prose tagged a declared mcq question and the item lines are page furniture every
    consumer skips (`element_kind="text"`). Page 1 carries the identity lines outside
    markers: the V3 `Student:` line (dropped for the quarantine indices) and the V4
    `Assessment:` line.
    """
    pages: list[str] = []
    for page_no, raw in enumerate(submission.pages, start=1):
        lines = raw.split("\n")
        assert lines[0].startswith(f"Page {page_no} of 4"), (
            "fixture bug: the corpus page header moved")
        out: list[str] = [lines[0], ""]
        if page_no == 1:
            if with_student:
                out.append(f"Student: {submission.student_ref}")
            out.append(f"Assessment: {PKG_ID}")
        current: str | None = None
        block: list[str] = []

        def _flush() -> None:
            """Emit the section just closed: Q5's item lines become ONE resolved
            selection mark plus the item lines outside any marker; every other
            question's rendered lines become one transcribed_text region."""
            nonlocal current, block
            if current == "Q5" and block:
                choice = _q5_choice(block)
                out.append("")
                out.append(_wrap_region(
                    "selection_mark", "Q5", 0.95, choice, selection=choice))
                out.append("")
                out.extend(block)
            elif current is not None and block:
                out.append("")
                out.append(_wrap_region(
                    "transcribed_text", current, 0.90, "\n".join(block)))
            current = None
            block = []

        for line in lines[1:]:
            if line.startswith("## "):
                _flush()
                current = line[3:].strip()
                out.append("")
                out.append(f"## {current}")
            elif line.strip() and current is not None:
                block.append(line)
        _flush()
        pages.append("\n".join(out).strip("\n"))
    return pages


def _assessment_page() -> str:
    """The assessment artifact's single-page transcript: the declared-identifier line
    and one `transcribed_text` region per question carrying the question's prompt -
    the one assessment lineage the V4 semantic signal compares against."""
    lines: list[str] = [f"Assessment: {PKG_ID}",
                        "Reference paper for the physics of motion assessment", ""]
    for question in corpus.QUESTIONS:
        lines.append("")
        lines.append(_wrap_region(
            "transcribed_text", question.question_id, 0.95, question.prompt))
        lines.append("")
    return "\n".join(lines).strip("\n")


class JourneyProvider:
    """The model boundary for the overnight journeys: the shipped
    `RecordedFixtureProvider` owns the fixture store and every replay; the wrapper
    answers a *first* sight of an unknown request from the journey's own computation
    and records it through the shipped `record()`. The drive pre-records the extract
    and score replies under their exact request keys before each unit, so the
    wrapper's own fallback carries only the two request shapes the SYSTEM assembles
    internally: page transcription (staged per source blob and page) and synthesis
    (computed from the request's own fields, numeral-free so the score-claim ladder
    stays clean). The injected unavailable window raises `ProviderUnavailableError`
    before the inner call - terminal for the run, never retried (`CT-PROV-08`).
    `estimate_cost` is the run's cost seam (`FR-ORCH-15`): a bare Decimal is the
    figure the run's estimate sums per unit.
    """

    def __init__(self, fixture_dir: Any) -> None:
        self._inner = RecordedFixtureProvider(fixture_dir=fixture_dir)
        self._transcripts: dict[tuple[str, int], str] = {}
        self._unavailable = False
        self.scripted_calls = 0
        self.replayed_calls = 0

    def stage_transcript(self, blob_hash: str, pages: dict[int, str]) -> None:
        """Stage the transcription the VLM returns for one uploaded PDF's pages."""
        for page_no, text in pages.items():
            self._transcripts[(blob_hash, int(page_no))] = text

    def set_unavailable(self, flag: bool = True) -> None:
        """Open or close the injected unavailability window."""
        self._unavailable = bool(flag)

    def unavailable(self) -> bool:
        """Whether the injected unavailability window is open."""
        return self._unavailable

    def record(self, prompt: Any, model_ref: Any, params: Any,
               completion: Completion) -> str:
        """Record one completion through the shipped provider - the same machinery
        the replay path reads; a fixture-carrying cost is refused by the shipped
        guard."""
        return self._inner.record(prompt, model_ref, params, completion)

    def estimate_cost(self, unit: Any) -> Decimal:
        """The cost seam's flat per-unit figure; the run's estimate sums it."""
        return Decimal("0.001")

    def _completion(self, text: str, model_ref: Any) -> Completion:
        return Completion(
            text=text, tokens_in=10, tokens_out=5, latency_ms=1,
            resolved_build=model_ref.build_id, cached_prefix_tokens=0, cost=None,
        )

    def _synth_reply(self, fields: dict[str, str]) -> str:
        """The synthesis reply, computed from the request's own fields: the L1 reply
        cites the request's own criteria; both levels' narratives are numeral-free
        prose (the score-claim ladder rejects a claiming narrative), and the question
        id stays out of the prose for the same reason - a numeral-free narrative is
        the honest reply shape the ladder keeps unflagged."""
        if fields.get("level") == LEVEL_L1:
            criteria = [c.strip() for c in fields.get("criteria", "").split(",")
                        if c.strip()]
            narrative = (
                "The response addresses the criteria the panel read, citing the "
                "work's own words as evidence; where the work stops short, the "
                "narrative says so in the same terms the criteria name."
            )
            return json.dumps({"narrative": narrative, "citations": criteria})
        narrative = (
            "The submission's questions are narrated above; the whole reads as one "
            "response whose strengths and gaps the question narratives already state."
        )
        return json.dumps({"narrative": narrative, "citations": []})

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Completion:
        if self._unavailable:
            raise ProviderUnavailableError(
                "the journey's provider is unavailable (injected window)")
        try:
            completion = self._inner.complete(prompt, model_ref, params)
            self.replayed_calls += 1
            return completion
        except FixtureMissingError:
            pass
        fields = dict(prompt.fields)
        if "page_no" in fields:
            key = (fields.get("source_blob_hash"), int(fields["page_no"]))
            if key not in self._transcripts:
                raise AssertionError(
                    f"the journey staged no transcript for page {key[1]} of blob "
                    f"{str(key[0])[:16]} - an upload the journey did not stage"
                )
            text = self._transcripts[key]
        elif fields.get("instruction", "").startswith("Decide whether"):
            # The V4 escalation's contained model call - never expected on this
            # world's happy path (the deterministic signals settle every submission),
            # and a one-word reply keeps the contained path honest if it ever fires.
            text = "match"
        elif fields.get("level") in (LEVEL_L1, LEVEL_L2):
            text = self._synth_reply(fields)
        else:
            raise AssertionError(
                f"the journey has no reply for an unexpected request: fields "
                f"{sorted(fields)[:6]} - extract and score replies are pre-recorded "
                "by the drive under exact request keys"
            )
        completion = self._completion(text, model_ref)
        self._inner.record(prompt, model_ref, params, completion)
        self.scripted_calls += 1
        return completion


class LedgerEvidenceView:
    """The gate's read model, standing in for the extractor and the panel - the read
    model the shipped `ExtractionView` vocabulary declares, backed by REAL store rows.
    Four reads, one per signal computation the gate consumes:

    - `spans` decodes the extract evidence payload the workers persisted (the one
      place the extractor's span payload lives, `#68`/`#69`);
    - `regions` resolves the gate's `doc-<submission_id>` spelling through the
      document table's submission foreign key (ingest mints `doc-<uuid12>` ids) and
      computes each region's extent by locating its stored content in the canonical
      Markdown, advancing a search cursor in row order so repeated content addresses
      successive lines;
    - `panel_sufficiency` derives the flags from the stored verdict rows once they
      exist and reports the neutral all-sufficient constant before they do
      (disclosed at the module docstring);
    - `criterion_requires_citation` is True: the world's criteria are citation-
      requiring and its judges cite.

    `second_family_spans` returns `None` per payload only when no second family ran;
    this world's payload carries one, so the read returns its span set.
    """

    def __init__(self, world: "SynthWorld") -> None:
        self._world = world

    def spans(self, submission_id: str, criterion_id: str) -> tuple[SimpleNamespace, ...]:
        rows = self._world.handle.query(
            "SELECT e.payload FROM work_unit w JOIN evidence e ON e.work_id = w.work_id "
            "WHERE w.run_id = :r AND w.submission_id = :s AND w.criterion_id = :c "
            "AND w.stage = 'extract' AND e.payload IS NOT NULL",
            r=self._world.run_id, s=submission_id, c=criterion_id,
        )
        spans: list[SimpleNamespace] = []
        for row in rows:
            record = json.loads(bytes(row["payload"]).decode("utf-8"))
            for span in record.get("spans", ()):
                spans.append(SimpleNamespace(
                    start=int(span["start"]), end=int(span["end"]),
                    text=str(span["text"]),
                ))
        return tuple(spans)

    def second_family_spans(
        self, submission_id: str, criterion_id: str,
    ) -> tuple[SimpleNamespace, ...] | None:
        rows = self._world.handle.query(
            "SELECT e.payload FROM work_unit w JOIN evidence e ON e.work_id = w.work_id "
            "WHERE w.run_id = :r AND w.submission_id = :s AND w.criterion_id = :c "
            "AND w.stage = 'extract' AND e.payload IS NOT NULL",
            r=self._world.run_id, s=submission_id, c=criterion_id,
        )
        if not rows:
            return None
        record = json.loads(bytes(rows[0]["payload"]).decode("utf-8"))
        family = record.get("second_family")
        if not isinstance(family, dict):
            return None
        return tuple(
            SimpleNamespace(
                start=int(span["start"]), end=int(span["end"]), text=str(span["text"]),
            )
            for span in family.get("spans", ())
        )

    def regions(self, document_id: str) -> tuple[SimpleNamespace, ...]:
        # The gate asks by its own `doc-<submission_id>` spelling; the store's
        # document ids are minted, so the request resolves through the submission
        # foreign key (disclosed at the module docstring).
        submission_id = document_id[len("doc-"):] if document_id.startswith("doc-") \
            else document_id
        docs = self._world.handle.query(
            "SELECT document_id, markdown FROM document WHERE submission_id = :s "
            "ORDER BY document_id LIMIT 1",
            s=submission_id,
        )
        if not docs:
            return ()
        rows = self._world.handle.query(
            "SELECT region_kind, ocr_conf, crop_ref, content FROM document_region "
            "WHERE document_id = :d ORDER BY position",
            d=docs[0]["document_id"],
        )
        markdown = docs[0]["markdown"] or ""
        items: list[SimpleNamespace] = []
        cursor = 0
        for row in rows:
            content = row["content"] or ""
            start = markdown.find(content, cursor) if content else cursor
            if start < 0:
                start = cursor  # a region the canonical text no longer carries
            end = start + len(content.encode("utf-8"))
            cursor = max(cursor, start)
            items.append(SimpleNamespace(
                region_kind=row["region_kind"], start=start, end=end,
                ocr_conf=row["ocr_conf"], crop_ref=row["crop_ref"],
            ))
        return tuple(items)

    def panel_sufficiency(self, submission_id: str,
                          criterion_id: str) -> SimpleNamespace:
        flags = self._verdict_flags(submission_id, criterion_id)
        if flags is None:
            flags = (True, True, True)
        return SimpleNamespace(evidence_sufficient=flags)

    def _verdict_flags(self, submission_id: str,
                       criterion_id: str) -> tuple[bool, ...] | None:
        rows = self._world.handle.query(
            "SELECT v.evidence_sufficient FROM verdict v "
            "JOIN work_unit w ON w.work_id = v.work_id "
            "WHERE w.run_id = :r AND w.submission_id = :s AND w.criterion_id = :c "
            "ORDER BY v.work_id",
            r=self._world.run_id, s=submission_id, c=criterion_id,
        )
        if not rows:
            return None
        return tuple(bool(row["evidence_sufficient"]) for row in rows)

    def criterion_requires_citation(self, criterion_id: str) -> bool:
        return True


class SynthWorld:
    """The assembled system over the synthesized cohort: real store, real gateway,
    real catalog, real orchestrator, real workers, real gate. The model boundary is
    the only double.

    Construction order is the pipeline's own: environment knobs, catalog build and
    publication, cohort and roster, the ONE assessment artifact, then the
    submissions through the real gateway. The run and its legs are built by the
    journey tests on top.
    """

    def __init__(
        self,
        data_dir: Any,
        fixture_dir: Any,
        *,
        n_submissions: int = corpus_synth.SYNTH_COUNT,
        cohort_id: str = E2E_COHORT_ID,
        run_id: str = E2E_RUN_ID,
        monkeypatch: Any = None,
        quarantine_indices: tuple[int, ...] = QUARANTINE_INDICES,
        panel_size: int = 3,
        review_window_hours: int | None = None,
    ) -> None:
        for name, value in WORLD_ENV.items():
            if monkeypatch is not None:
                monkeypatch.setenv(name, value)
            else:
                os.environ[name] = value
        self.monkeypatch = monkeypatch
        self.data_dir = data_dir
        self.fixture_dir = fixture_dir
        self.cohort_id = cohort_id
        self.run_id = run_id
        self.n_submissions = n_submissions
        self.quarantine_indices = tuple(
            index for index in quarantine_indices if index <= n_submissions
        )
        self.review_window_hours = review_window_hours
        self.store = open_store(data_dir)
        self.provider = JourneyProvider(fixture_dir)
        self.blobs = self.store.blobs()
        self.handle = self.store.cohort(cohort_id)
        self.panel_refs = edge_panel(panel_size)
        self.judge_refs = {ref.build_id: ref for ref in self.panel_refs}
        self.escalation_refs = {
            "escalation-arm-4": self._judge_ref("escalation-arm-4"),
            "escalation-arm-5": self._judge_ref("escalation-arm-5"),
        }
        self.open_ids = tuple(corpus.OPEN_CRITERION_IDS)
        self.mcq_ids = tuple(corpus.MCQ_CRITERION_IDS)
        self.cohort = corpus_synth.synth_cohort()[:n_submissions]
        self.sid_by_index: dict[int, str] = {}
        self.index_by_sid: dict[str, int] = {}
        self.student_ref_by_sid: dict[str, str] = {}
        self.ingest_reports: dict[str, Any] = {}
        self.stored_markdown: dict[str, str] = {}
        self.spans_by_cell: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.signals_by_cell: dict[tuple[str, str], Any] = {}
        self._build()

    # -- construction pieces ---------------------------------------------------------------------

    def _judge_ref(self, build_id: str) -> Any:
        return ModelRef(role="judge", provider="local", build_id=build_id,
                        quantization="q4")

    def _build(self) -> None:
        self._build_catalog()
        self._build_cohort()
        self._ingest_assessment()
        self._ingest_submissions()

    def _build_catalog(self) -> None:
        """The package, through the real M-PKG writer: the corpus's twelve open
        criteria (holistic, four-band) and three mcq criteria (atomic, the
        deterministic two-band scale), options and keys, the inclusive boundary
        table, then publication and the lock. The package row lives on the Tier P
        file - the same write `orch_run.seed_package` makes before its catalog
        opens (`create_version` refuses to mint a package row)."""
        package_handle = self.store.package(PKG_ID)
        with package_handle.transaction() as tx:
            tx.execute(
                "INSERT INTO package (package_id, created_at) VALUES (:p, :c)",
                p=PKG_ID, c=STAMP,
            )
        self.catalog = PackageCatalog(
            package_handle, package_id=PKG_ID, blobs=self.blobs)
        version = self.catalog.create_version(None)
        self.version = version
        for criterion in corpus.CRITERIA:
            if criterion.kind == "open":
                self.catalog.add_criterion(
                    version, criterion.criterion_id,
                    question_id=criterion.question_id, kind="open",
                    max_points=corpus.points_for(
                        criterion.criterion_id, criterion.bands[-1].band),
                    scoring_model="holistic",
                )
                for band in criterion.bands:
                    self.catalog.add_band(
                        version, criterion.criterion_id, band.ordinal,
                        band.band, band.points, band.descriptor,
                    )
            else:
                self.catalog.add_criterion(
                    version, criterion.criterion_id,
                    question_id=criterion.question_id, kind="mcq",
                    max_points=1.0, scoring_model="atomic", band_count=2,
                )
                for ordinal, (name, _band_ordinal, points) in enumerate(MCQ_BANDS):
                    self.catalog.add_band(
                        version, criterion.criterion_id, ordinal, name, points,
                    )
                self.catalog.set_mcq_options(
                    version, criterion.criterion_id,
                    [(o, f"Option {o}") for o in corpus.MCQ_OPTIONS],
                )
                self.catalog.set_answer_key(version, criterion.criterion_id,
                                            criterion.answer_key)
        self.catalog.set_boundaries(version, list(GRADE_BOUNDARIES))
        # The review window is per-package data (`ADR-3`), and a published
        # version is immutable (`FR-PKG-01`) - so a journey that needs a window
        # attaches its policy HERE, before the lock, exactly as the package
        # owner would. Default None stores no row, and `grade_policy()` answers
        # the default (null window: completion settles) - journey 2's shape.
        if self.review_window_hours is not None:
            self.catalog.set_grade_policy(
                version, GradePolicy(review_window_hours=self.review_window_hours))
        self.catalog.publish(version, approved_by="The package owner")

    def _build_cohort(self) -> None:
        """The cohort, its roster (the V3 identity gate reads it), and nothing else -
        submissions arrive through the real gateway, never as direct rows."""
        with self.handle.transaction() as tx:
            tx.execute(
                "INSERT INTO cohort (cohort_id, consent_class, created_at) "
                "VALUES (:c, 'synthetic', :ts)",
                c=self.cohort_id, ts=STAMP,
            )
            for index in range(1, self.n_submissions + 1):
                tx.execute(
                    "INSERT INTO roster (cohort_id, student_ref) VALUES (:c, :s)",
                    c=self.cohort_id, s=f"S-{index:04d}",
                )

    def _ingestor(self) -> Ingestor:
        return Ingestor(
            self.handle, self.blobs, self.provider,
            ModelRef(role="transcriber", provider="local",
                     build_id=TRANSCRIBER_BUILD, quantization="q4"),
            SamplingParams(temperature=0.0), PdfiumRasterizer(),
            residency=ResidencySlot.for_policy(("transcriber",)),
            sanitizer=PypdfSanitizer(),
        )

    def _ingest_assessment(self) -> None:
        """The ONE assessment artifact, ingested before any submission - the single
        lineage head the V4 semantic signal compares against."""
        text = _assessment_page()
        blob = self.blobs.put(_pdf_of([text]))
        self.provider.stage_transcript(blob, {1: text})
        ingestor = self.ingestor
        self.assessment_doc_id = ingestor.ingest_document(
            [blob], kind="assessment", order_hint=[blob],
        )

    def _ingest_submissions(self) -> None:
        """The cohort's submissions through the real gateway, one 4-page PDF each -
        `ingest_submission` mints the store's submission ids, so the world records
        the corpus-index to store-id map (and the student refs, which the report
        does not carry) as it goes. The quarantine indices' pages drop the
        `Student:` line: V3 identity fails, V4 still matches."""
        ingestor = self.ingestor
        for index, submission in enumerate(self.cohort, start=1):
            pages = _marked_pages(
                submission, with_student=(index not in self.quarantine_indices))
            blob = self.blobs.put(_pdf_of(pages))
            self.provider.stage_transcript(
                blob, {page_no: page for page_no, page in enumerate(pages, start=1)})
            report = ingestor.ingest_submission(
                [blob], self.cohort_id, self.version,
                order_hint=[blob], filenames={blob: f"SYN-{index:03d}.pdf"},
                package_catalog=self.catalog,
            )
            sid = report.submission_id
            self.sid_by_index[index] = sid
            self.index_by_sid[sid] = index
            self.student_ref_by_sid[sid] = submission.student_ref
            self.ingest_reports[sid] = report
            head = self.handle.query(
                "SELECT markdown FROM document WHERE submission_id = :s "
                "ORDER BY document_id LIMIT 1", s=sid,
            )
            assert head and head[0]["markdown"], (
                f"fixture bug: submission {index} ingested no canonical markdown")
            self.stored_markdown[sid] = head[0]["markdown"]

    def _stage_spans(self) -> None:
        """The extraction's reply spans, cut from the STORED canonical markdown - the
        bytes the workers assemble over and the gate verifies against are the same
        document the gateway stored. A per-criterion search cursor advances so two
        criteria rendering identical prose (the absent submission's repeated line)
        address successive lines, never one first occurrence."""
        for index in sorted(self.sid_by_index):
            sid = self.sid_by_index[index]
            submission = self.cohort[index - 1]
            markdown = self.stored_markdown[sid]
            cursor = 0
            for cid in self.open_ids:
                needle = corpus_synth.render_band(cid, _ordinal_of(submission, cid))
                start = markdown.find(needle, cursor)
                assert start >= 0, (
                    f"fixture bug: the band line for {cid} of index {index} is not "
                    "in the stored markdown")
                end = start + len(needle)
                cursor = end
                self.spans_by_cell[(sid, cid)] = [
                    {"start": start, "end": end, "text": needle,
                     "region_kind": "transcribed_text"},
                ]

    # -- derived surfaces ------------------------------------------------------------------------

    @property
    def ingestor(self) -> Ingestor:
        return self._ingestor()

    def sid_of(self, index: int) -> str:
        return self.sid_by_index[index]

    def admitted_ids(self) -> list[str]:
        """The store submission ids whose ingest status admits them to the run's
        judged stages (`SWEEP1_ADMITTED_INGEST_STATUSES`), in corpus order."""
        return [
            self.sid_by_index[index] for index in sorted(self.sid_by_index)
            if self.ingest_reports[self.sid_by_index[index]].ingest_status
            in SWEEP1_ADMITTED_INGEST_STATUSES
        ]

    def quarantined_ids(self) -> list[str]:
        return [
            self.sid_by_index[index] for index in sorted(self.sid_by_index)
            if self.ingest_reports[self.sid_by_index[index]].quarantined
        ]

    def refresh_stored_markdown(self) -> None:
        """Re-read the canonical markdown from the store - the resume variants call
        this after a simulated kill, because the world object outlives the store
        handle but the corpus-indexed cache must match the reopened file's rows."""
        for sid in self.stored_markdown:
            head = self.handle.query(
                "SELECT markdown FROM document WHERE submission_id = :s "
                "ORDER BY document_id LIMIT 1", s=sid,
            )
            assert head and head[0]["markdown"], (
                f"fixture bug: submission {sid}'s document vanished")
            self.stored_markdown[sid] = head[0]["markdown"]

    def sweep(self) -> Any:
        """Requeue the units a killed drive left leased: the sweeper reclaims leases
        older than `HARNESS_ORCH_LEASE_SECONDS`, pinned 0 at the call so every
        outstanding lease reads expired - the recovery the resume variants run
        before continuing the drive."""
        _set_env(self.monkeypatch, LEASE_SECONDS_ENV, "0")
        return self.orchestrator.sweep_expired_leases()

    def reattach(self) -> None:
        """Reopen the world after a simulated kill: a fresh store on the same data
        dir, a fresh provider over the SAME fixture dir (the recordings replay), a
        fresh orchestrator bound to the fresh store. Ingest completed before the
        drive, so no transcription call remains to stage; the extract, score and
        synthesis replies replay from the fixture store under their exact keys -
        the resume variant's whole point (a restart invents nothing)."""
        self.store = open_store(self.data_dir)
        self.provider = JourneyProvider(self.fixture_dir)
        self.blobs = self.store.blobs()
        self.handle = self.store.cohort(self.cohort_id)
        self.orchestrator = Orchestrator(self.store, provider=self.provider)
        self.refresh_stored_markdown()

    # -- the run ---------------------------------------------------------------------------------

    def build_run(self) -> str:
        """Create and enumerate the overnight run through the real orchestrator, the
        world's three-judge edge panel resolved as the run's config. Not started -
        the journeys assert on the enumeration and the estimate first."""
        self.orchestrator = Orchestrator(self.store, provider=self.provider)
        resolved = resolve_run_config(
            edge_cfg(panel=self.panel_refs),
            CohortRef(cohort_id=self.cohort_id, consent_class="synthetic"),
        )
        self.resolved = resolved
        self.run_id = self.orchestrator.create_run(
            self.cohort_id, self.version, resolved, run_id=self.run_id)
        self.enumeration = self.orchestrator.enumerate_units(self.run_id)
        self._stage_spans()
        return self.run_id

    def start_run(self) -> None:
        assert self.orchestrator.start(self.run_id) == "running", (
            "the run did not start - the journeys read the running state first")

    def drive_deterministic(self) -> None:
        """The deterministic leg: `M-DET`'s cohort pass over EVERY submission (the
        enumeration admits none - det scores the mcq criteria of quarantines too),
        then the stage's units complete."""
        DeterministicEvaluator(self.store).evaluate_cohort(self.run_id)
        batch = self.orchestrator.lease("w-e2e-det", STAGE_DETERMINISTIC, 512)
        for unit in batch:
            self.orchestrator.complete(unit.work_id)

    def drive_extract(self, *, limit: int | None = None) -> int:
        """The extraction leg: lease in batches, record the reply under the exact
        request key for BOTH families (every open criterion is on the high-risk
        register), then drive the real worker. With `limit`, the drive stops after
        that many units with the rest of the last batch still LEASED - the exact
        state a SIGKILLed worker leaves (the kill variant's injury), which only the
        lease sweeper requeues."""
        ref = ModelRef(role="extractor", provider="local", build_id=EXTRACT_BUILD,
                       quantization="q4")
        second = ModelRef(role="extractor", provider="local",
                          build_id=EXTRACT_SECOND_BUILD, quantization="q4")
        worker = ExtractionWorker(
            self.store, self.provider, ref,
            second_family_model=second, high_risk_criteria=self.open_ids,
        )
        processed = 0
        while True:
            batch = self.orchestrator.lease("w-e2e-extract", STAGE_EXTRACT, 32)
            if not batch:
                break
            for unit in batch:
                if limit is not None and processed >= limit:
                    return processed
                self._drive_extract_unit(unit, worker, ref, second)
                processed += 1
        return processed

    def _drive_extract_unit(self, unit: Any, worker: ExtractionWorker,
                            ref: Any, second: Any) -> None:
        self.ensure_available()
        request = assemble_request(unit, store=self.store)
        spans = self.spans_by_cell[(unit.submission_id, unit.criterion_id)]
        self.provider.record(
            prompt_fields(request), ref, sampling_params(),
            span_completion(spans, build_id=EXTRACT_BUILD),
        )
        self.provider.record(
            prompt_fields(request), second, sampling_params(),
            span_completion(spans, build_id=EXTRACT_SECOND_BUILD),
        )
        worker.process(unit)

    def drive_score(self, *, include_escalations: bool = False,
                    limit: int | None = None) -> int:
        """The scoring leg: lease in batches and drive each unit through the scoring
        worker named by its judge. With `include_escalations`, the extension arms
        (`escalation-arm-4/5`, the ladder's derived identities) drive too - the
        base leg passes them by until the escalation walk enqueues them. With
        `limit`, the drive stops after that many units with the rest of the last
        batch still LEASED - the SIGKILL variant's injury, requeued by the sweep."""
        refs = dict(self.judge_refs)
        if include_escalations:
            refs.update(self.escalation_refs)
        processed = 0
        while True:
            batch = self.orchestrator.lease("w-e2e-judge", STAGE_SCORE, 32)
            if not batch:
                break
            for unit in batch:
                if limit is not None and processed >= limit:
                    return processed
                self._drive_score_unit(unit, refs)
                processed += 1
        return processed

    def _drive_score_unit(self, unit: Any, refs: dict[str, Any]) -> None:
        self.ensure_available()
        ref = refs.get(unit.judge)
        assert ref is not None, (
            f"score unit {unit.work_id[:16]} names judge {unit.judge!r} - not one "
            "of the world's panel or extension arms"
        )
        worker = ScoringWorker(self.store, self.provider, ref)
        request = worker.assemble(unit)
        spans = self.spans_by_cell[(unit.submission_id, unit.criterion_id)]
        band = self._judge_band(unit.submission_id, unit.criterion_id)
        self.provider.record(
            judge_prompt_fields(request), ref, sampling_params(),
            verdict_completion(band, 0.9, build_id=ref.build_id, cited_spans=spans),
        )
        result = worker.dispatch(request, ref)
        assert result.band == band, (
            "the judge's reply was not the verdict the fixture recorded")
        worker.persist(unit, result)

    def _judge_band(self, sid: str, cid: str) -> str:
        return self.cohort[self.index_by_sid[sid] - 1].bands[cid]

    def ensure_available(self) -> None:
        """The unavailability variant's entry: an open window surfaces to the driver
        BEFORE any unit is struck - the operator pauses on the same backend and the
        ledger takes no damage in the window."""
        if self.provider.unavailable():
            raise ProviderUnavailableError(
                "the journey's provider is unavailable (injected window)")

    # -- the integrity gate ----------------------------------------------------------------------

    def integrity_gate(self) -> IntegrityGate:
        return IntegrityGate(
            self.handle, self.blobs, LedgerEvidenceView(self),
        )

    def integrity_pass(self, *, capture: bool = False) -> None:
        """One pass of the integrity gate over every admitted cell: pre-judge the
        pass routes on the extraction's own signals; post-judge (capture) the pass
        re-runs over the judged cells and the captured signals ride into the
        aggregation walk. The gate's own routing writes are the shipped mechanism."""
        gate = self.integrity_gate()
        for sid in self.admitted_ids():
            for cid in self.open_ids:
                signals = gate.verify(self.run_id, sid, cid)
                if capture:
                    self.signals_by_cell[(sid, cid)] = signals

    # -- the aggregation walk --------------------------------------------------------------------

    def aggregate_walk(
        self,
        *,
        monkeypatch: Any = None,
        breaker_rate: str | None = None,
        breaker_min_n: str | None = None,
        agg_config_kwargs: dict | None = None,
    ) -> int:
        """The M-AGG walk over the judged cells: aggregate each cell's stored
        verdicts against the run's declared bands and the captured integrity
        signals, decide the escalation policy, and write the triggering row and the
        widening it triggers in ONE transaction - the caller's (`CT-ORCH-08`).
        Returns the number of escalation units the walk enqueued.

        With `breaker_rate`/`breaker_min_n` the walk hands the criterion breaker
        its knobs at call time (the env seam - the enqueue path reads them there),
        and a cell whose enqueue reports `halted_by_breaker` is re-aggregated with
        `breaker_tripped=True` in the SAME transaction: the mark on the criterion's
        RESULT is M-AGG's artifact to write - the ledger's breaker row and the
        report's decision are what tell it to (`FR-ORCH-13`, `CT-ORCH-16`). The
        marked cells are recorded on `breaker_marked` for the journey's oracle.

        With `agg_config_kwargs` the walk injects the aggregation configuration the
        caller states (Q-04: the tests inject the cap table and thresholds; the
        assertions are stated against the injection, never against the literals) -
        journey 3's auto-accepted population is engineered exactly so, by lowering
        the holistic auto threshold below the unanimous-panel figure the world's
        judges produce. The default (no kwargs) is the design's Assumption numbers,
        which is what journey 2's baseline pins.
        """
        _set_env(monkeypatch, ESCALATION_BUDGET_ENV, "1.0")
        _set_env(monkeypatch, CRITERION_BREAKER_RATE_ENV, breaker_rate or "1.0")
        if breaker_min_n is not None:
            _set_env(monkeypatch, CRITERION_BREAKER_MIN_N_ENV, breaker_min_n)
        config = agg_config(**(agg_config_kwargs or {}))
        self.breaker_marked = []
        catalog = PackageCatalog(self.store.package(PKG_ID), package_id=PKG_ID)
        bands = {cid: catalog.bands(cid) for cid in self.open_ids}
        enqueued = 0
        for sid in self.admitted_ids():
            for cid in self.open_ids:
                rows = self.stored_verdicts(sid, cid)
                crit = agg_criterion(
                    bands[cid], scoring_model="holistic", criterion_id=cid)
                captured = self.signals_by_cell[(sid, cid)]
                sig = agg_signals(
                    spans_verified=captured.spans_verified,
                    evidence_present=captured.evidence_present,
                    sufficiency_flag=captured.sufficiency_flag,
                    ocr_overlap_risk=captured.ocr_overlap_risk,
                    described_evidence=captured.described_evidence,
                    extractor_disagreement=captured.extractor_disagreement,
                )
                score = aggregate(rows, crit, sig, config=config)
                decision = should_escalate(
                    score=score, criterion=crit,
                    history=criterion_history(override_rate=0.0),
                    baseline=expected_distribution(), config=config,
                )
                with self.handle.transaction() as tx:
                    if decision.escalate:
                        reports = self.orchestrator.enqueue_escalation(tx, (sid, cid))
                        enqueued += sum(
                            report.units_inserted for report in reports)
                        if any(report.decision == DECISION_HALTED_BY_BREAKER
                               for report in reports):
                            # The breaker's mark on the RESULT (FR-ORCH-13): the
                            # refused widening leaves the panel's own figure
                            # standing, routed provisional, state
                            # ungradeable_by_panel (FR-AGG-11's precedence).
                            score = aggregate(
                                rows, crit, sig, config=config,
                                breaker_tripped=True,
                            )
                            self.breaker_marked.append((sid, cid))
                    tx.execute(
                        _SCORE_UPSERT,
                        sid=sid, cid=cid, band=score.band, points=score.points,
                        judge_count=score.judge_count, agreement=score.agreement,
                        state=score.state, routing=score.routing,
                        confidence=score.confidence,
                        confidence_base=score.confidence_base,
                        spans_verified=score.spans_verified,
                        evidence_present=score.evidence_present,
                        sufficiency_flag=score.sufficiency_flag,
                        ocr_overlap_risk=score.ocr_overlap_risk,
                    )
        return enqueued

    def stored_verdicts(self, sid: str, cid: str) -> list[SimpleNamespace]:
        """The cell's verdict rows, read back from the real ledger as the
        verdict-shaped values `aggregate` consumes; `cited` True - the world's
        completions all cite (the `_drive.py` precedent's disclosure)."""
        rows = self.handle.query(
            "SELECT v.band, v.band_ordinal, v.self_confidence FROM verdict v "
            "JOIN work_unit w ON w.work_id = v.work_id "
            "WHERE w.run_id = :r AND w.submission_id = :s AND w.criterion_id = :c "
            "ORDER BY v.work_id",
            r=self.run_id, s=sid, c=cid,
        )
        return [
            SimpleNamespace(band=row["band"], ordinal=row["band_ordinal"],
                            self_confidence=row["self_confidence"], cited=True)
            for row in rows
        ]

    # -- synthesis -------------------------------------------------------------------------------

    def drive_synthesis(self) -> None:
        """The synthesis leg: the two-level driver per admitted submission - L1 for
        each complete question, then one L2 composition. The worker absorbs stored
        narratives on re-entry (the resume variants' idempotence)."""
        worker = SynthesisWorker(
            self.store, self.provider,
            ModelRef(role="synthesizer", provider="local", build_id=SYNTH_BUILD,
                     quantization="q4"),
        )
        for sid in self.admitted_ids():
            worker.synthesize_submission(self.run_id, sid)

    # -- the closer and the result set -----------------------------------------------------------

    def finalize(self) -> None:
        """The sanctioned closer and the grade pass: `resume` completes the run once
        its last open unit closed underneath a worker; `compute_all` grades the run."""
        self.orchestrator.resume(self.run_id)
        open_grade(self.store).compute_all(self.run_id)

    def result_set(self) -> dict[str, Any]:
        """The journey's result set, keyed by corpus index with the minted
        identifiers normalized out (the journey-1 manifest precedent): the store
        submission ids are `uuid4`-minted per build, so the baseline freezes the
        CONTENT and the identifier shapes are asserted separately. Timestamps are
        excluded; narrative texts carry digests (the prose is scripted and stable,
        but the baseline's business is what the system PRODUCED, not its wording).
        Quarantine reads off the report's status: admitted is the shipped rule's
        frozenset, so quarantine is its complement - the report records the status
        the gates decided, and the run's admission rule reads the same value."""
        submissions: list[dict[str, Any]] = []
        grade_rows = {
            row["submission_id"]: row for row in self.handle.query(
                "SELECT submission_id, state, grade, total, criteria_total, "
                "criteria_auto, criteria_reviewed, criteria_provisional, "
                "criteria_missing FROM submission_grade WHERE run_id = :r "
                "AND is_current = 1", r=self.run_id,
            )
        }
        for index in sorted(self.sid_by_index):
            sid = self.sid_by_index[index]
            report = self.ingest_reports[sid]
            grade = grade_rows.get(sid)
            scores = [
                [row["criterion_id"], row["band"], round(float(row["points"]), 4),
                 row["judge_count"], row["routing"], row["state"]]
                for row in self.handle.query(
                    "SELECT criterion_id, band, points, judge_count, routing, state "
                    "FROM criterion_score WHERE submission_id = :s "
                    "ORDER BY criterion_id", s=sid,
                )
            ]
            narratives = [
                [row["level"], row["question_id"],
                 hashlib.sha256(row["text"].encode("utf-8")).hexdigest()[:16]]
                for row in self.handle.query(
                    "SELECT level, question_id, text FROM narrative "
                    "WHERE submission_id = :s ORDER BY level, question_id", s=sid,
                )
            ]
            submissions.append({
                "index": index,
                "student_ref": self.student_ref_by_sid[sid],
                "ingest_status": report.ingest_status,
                "quarantined": report.ingest_status
                not in SWEEP1_ADMITTED_INGEST_STATUSES,
                "gates": dict(report.gates),
                "grade": None if grade is None else {
                    "state": grade["state"], "grade": grade["grade"],
                    "total": round(float(grade["total"]), 4),
                    "criteria_total": grade["criteria_total"],
                    "criteria_auto": grade["criteria_auto"],
                    "criteria_reviewed": grade["criteria_reviewed"],
                    "criteria_provisional": grade["criteria_provisional"],
                    "criteria_missing": grade["criteria_missing"],
                },
                "scores": scores,
                "narratives": narratives,
            })
        return {
            "issue": ISSUE,
            "package_id": PKG_ID,
            "version_shape": "PKG-REF@<uuid12hex>",
            "submissions": submissions,
        }


#: The re-aggregation write: `INSERT OR REPLACE` over the pair's primary key, so the
#: escalated cells' rewritten panels collapse onto their first-walk rows instead of
#: colliding (`criterion_score` PK is `(submission_id, criterion_id)`).
_SCORE_UPSERT = (
    "INSERT OR REPLACE INTO criterion_score (submission_id, criterion_id, band, "
    "points, judge_count, agreement, state, routing, confidence, confidence_base, "
    "spans_verified, evidence_present, sufficiency_flag, ocr_overlap_risk) "
    "VALUES (:sid, :cid, :band, :points, :judge_count, :agreement, :state, "
    ":routing, :confidence, :confidence_base, :spans_verified, :evidence_present, "
    ":sufficiency_flag, :ocr_overlap_risk)"
)


def _set_env(monkeypatch: Any, name: str, value: str) -> None:
    """Set one call-time knob through the test's monkeypatch when it is given, else
    the process environment - the env-gated knobs are read at call time (seam 3)."""
    if monkeypatch is not None:
        monkeypatch.setenv(name, value)
    else:
        os.environ[name] = value