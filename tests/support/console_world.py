"""The rung-3 world `TS-48` (issue #129) drives the console against: a real store, a real
package lineage, a real cohort ledger, a real run and the real deterministic and grading
passes over it — the neighbouring modules the console reads and writes through.

Why a world of its own. The `CT-CONSOLE` clause suites (`tests/contract/console/`) run on
`StoreSpy`, the write-audit double, and the console deliberately behaves differently there:
it fabricates a *standing shape* (one review item, one quarantine item) when no real store is
attached, records control rows as payload dicts, and settles a headless batch of grades in
memory. Every one of those is disclosed in `aeh/console.py`, and every one is exactly what a
rung-3 case exists to see past — so these cases hand the console a store whose `data_dir` is
real, which switches all of them off.

**The disclosed stand-ins.** `M-INGEST` and `M-SETUP` are not under test here. The cohort,
submission, document and `document_region` rows are written directly, in the column shape
`M-INGEST`'s shipped writers produce — the same seeding `aeh.console.run_pipeline_for_test`
(the console's own headless driver) and `tests/support/orch_run.py` disclose. Everything
downstream of those rows is the shipped module: `PackageCatalog` writes the package,
`Orchestrator` creates (and, where asked, enumerates) the run, `DeterministicEvaluator`
scores the multiple-choice criteria, `GradingService` computes and finalizes the grades.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

# The full migration chain before the first store open (CLAUDE.md, #234): an open on a
# truncated chain refuses with IncompleteMigrationChainError.
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
from aeh.conf import CohortRef, ModelRef, resolve_run_config
from aeh.det import DeterministicEvaluator
from aeh.grade import GradingService
from aeh.ingest import Ingestor, PageImage, PdfSanitizer, ResidencySlot, SanitizeResult
from aeh.orch import Orchestrator
from aeh.pkg import PackageCatalog, PackageDraft
from aeh.prov import Completion, SamplingParams
from tests.support.conf_builders import edge_cfg

STAMP = "2026-01-01T00:00:00+00:00"
OPTIONS = ("A", "B", "C", "D")

#: Three multiple-choice criteria, each with its stored key: `(criterion_id, question_id, key)`.
MCQ_CRITERIA: tuple[tuple[str, str, str], ...] = (
    ("C-01", "Q1", "A"),
    ("C-02", "Q2", "B"),
    ("C-03", "Q3", "C"),
)

#: The judged criteria a world may carry beside the multiple-choice ones — the kind whose
#: scores are panel outputs, and whose ledger units are what an answer-key correction must
#: never enqueue more of.
OPEN_CRITERIA: tuple[tuple[str, str], ...] = (("C-10", "Q10"), ("C-11", "Q11"))


@dataclass(frozen=True)
class ScoredRun:
    """What a seeded world hands back: the ids a case addresses, and nothing it computed."""

    cohort_id: str
    run_id: str
    package_id: str
    package_version_id: str
    submissions: tuple[str, ...]


def _clock() -> str:
    return STAMP


def seed_scored_run(
    store: Any,
    *,
    cohort_id: str = "c-ts48",
    run_id: str = "r-ts48",
    package_id: str = "pkg-ts48",
    submissions: int = 3,
    choices: Sequence[Sequence[str | None]] | None = None,
    with_open_criteria: bool = False,
    enumerate_units: bool = False,
    finalize: bool = False,
    reuse_version: str | None = None,
) -> ScoredRun:
    """Seed and score one run end to end through the shipped modules.

    `choices[i][j]` is submission *i*'s selected option for `MCQ_CRITERIA[j]`; `None` stores
    an ambiguous mark (the region the deterministic pass parks, so the grade is honestly
    incomplete). Default: every submission selects every stored key. `reuse_version` names a
    version of `package_id` an earlier call already seeded — a second administration of the
    same package version to a new cohort.
    """
    ids = tuple(f"sub-{cohort_id}-{index + 1:02d}" for index in range(submissions))
    if choices is None:
        choices = [[key for _, _, key in MCQ_CRITERIA] for _ in ids]

    handle = store.package(package_id)
    if reuse_version is not None:
        # A second administration of a package that already exists: same version, no seeding.
        version = reuse_version
    else:
        with handle.transaction() as tx:
            tx.execute(
                "INSERT INTO package (package_id, created_at) VALUES (:p, :t)",
                p=package_id,
                t=STAMP,
            )
    catalog = PackageCatalog(handle, package_id=package_id)
    if reuse_version is None:
        version = catalog.create_version(None)
    for criterion_id, question_id, key in (MCQ_CRITERIA if reuse_version is None else ()):
        catalog.add_criterion(version, criterion_id, question_id=question_id, kind="mcq",
                              band_count=2)
        catalog.add_band(version, criterion_id, 0, "incorrect", 0.0)
        catalog.add_band(version, criterion_id, 1, "correct", 1.0)
        catalog.set_mcq_options(
            version, criterion_id, [(option, f"Option {option}") for option in OPTIONS]
        )
        catalog.set_answer_key(version, criterion_id, key)
    if with_open_criteria and reuse_version is None:
        for criterion_id, question_id in OPEN_CRITERIA:
            catalog.add_criterion(version, criterion_id, question_id=question_id,
                                  kind="open", scoring_model="holistic")

    cohort = store.cohort(cohort_id)
    with cohort.transaction() as tx:
        tx.execute(
            "INSERT INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES (:c, 'synthetic', :t)",
            c=cohort_id,
            t=STAMP,
        )
        for index, submission_id in enumerate(ids):
            tx.execute(
                "INSERT INTO submission (submission_id, cohort_id, student_ref) "
                "VALUES (:s, :c, :r)",
                s=submission_id,
                c=cohort_id,
                r=f"ref-{submission_id}",
            )
            document_id = f"doc-{submission_id}"
            tx.execute(
                "INSERT INTO document (document_id, submission_id, content_hash, created_at) "
                "VALUES (:d, :s, :h, :t)",
                d=document_id,
                s=submission_id,
                h=f"hash-{submission_id}",
                t=STAMP,
            )
            for position, ((_, question_id, _), chosen) in enumerate(
                zip(MCQ_CRITERIA, choices[index], strict=True)
            ):
                tx.execute(
                    "INSERT INTO document_region (region_id, document_id, page_no, "
                    "element_kind, region_kind, content_state, selection_state, selection, "
                    "position) VALUES (:r, :d, 1, :q, 'selection_mark', 'present', :ss, "
                    ":sel, :pos)",
                    r=f"reg-{document_id}-{question_id}",
                    d=document_id,
                    q=question_id,
                    ss="ambiguous" if chosen is None else "resolved",
                    sel=chosen,
                    pos=position + 1,
                )

    resolved = resolve_run_config(
        edge_cfg(), CohortRef(cohort_id=cohort_id, consent_class="synthetic")
    )
    orchestrator = Orchestrator(store, clock=_clock)
    run_id = orchestrator.create_run(cohort_id, version, resolved, run_id=run_id)
    if enumerate_units:
        orchestrator.enumerate_units(run_id)
    DeterministicEvaluator(store).evaluate_cohort(run_id)
    GradingService(store, clock=_clock).compute_all(run_id)
    if finalize:
        GradingService(store, clock=_clock).finalize_batch(run_id, "ts48-fixture")
    return ScoredRun(
        cohort_id=cohort_id,
        run_id=run_id,
        package_id=package_id,
        package_version_id=version,
        submissions=ids,
    )


# --- the ingest world: S6 preflight and S8 quarantine over really-ingested submissions ------------
#
# The operator screens read what `M-INGEST` wrote — the per-gate ladder columns, the V4 cohort
# breaker row, the park flag, the region crops — so those cases ingest for real. The VLM is a
# scripted double, the sanitizer passes bytes through and the rasterizer returns fixed pages:
# the doubles `tests/integration/ingest/test_ingest_v4_match.py` (`TC-INGEST-28`) uses, for the
# same reason — the ladder, the breaker and the storage are the shipped code, and only the model
# boundary and the PDF engine are stood in for.

ASSESSMENT_QUESTIONS = {
    "Q1": "explain the water cycle from evaporation to rainfall",
    "Q2": "describe how forces balance on a stationary bridge",
}
MATCH_ANSWERS = {
    "Q1": "the water cycle moves water by evaporation then rainfall",
    "Q2": "the forces on a stationary bridge balance to zero",
}
MISMATCH_ANSWERS = {"Q1": "medieval kingdoms traded silk plus spices"}


class _ThroughSanitizer(PdfSanitizer):
    def sanitize(self, pdf_bytes, *, strip=True, **kwargs):  # noqa: ANN001, ANN003
        return SanitizeResult(pdf_bytes=pdf_bytes)


class _ScriptedRasterizer:
    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        return [PageImage(page_no=1, png=b"page", width_px=1000, height_px=1400)]

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:  # noqa: ANN001
        # Distinct bytes per box and source, so two crops never share one content hash.
        return b"crop:" + ",".join(str(part) for part in box).encode() + b":" + pdf_bytes[:32]

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        return ""


class _ScriptedVlm:
    """Transcription calls carry `page_no`; the V4 escalation payload does not."""

    def __init__(self) -> None:
        self.texts: dict[tuple[str, int], str] = {}

    def complete(self, prompt, model_ref, params) -> Completion:  # noqa: ANN001
        fields = dict(prompt.fields)
        if "page_no" in fields:
            text = self.texts.get((fields["source_blob_hash"], int(fields["page_no"])), "")
        else:
            text = "uncertain"
        return Completion(text=text, tokens_in=1, tokens_out=1, latency_ms=1,
                          resolved_build=model_ref.build_id, cached_prefix_tokens=0, cost=None)


class IngestWorld:
    """One cohort and one two-question package in a shared store, and a real `Ingestor` over
    them. `submit` ingests a scripted paper and returns the shipped `IngestReport`."""

    def __init__(self, store: Any, cohort_id: str, package_id: str) -> None:
        self.store = store
        self.cohort_id = cohort_id
        self.package_id = package_id
        self.handle = store.cohort(cohort_id)
        self.blobs = store.blobs()
        with self.handle.transaction() as tx:
            tx.execute("INSERT OR IGNORE INTO cohort (cohort_id, consent_class, created_at) "
                       "VALUES (:c, 'synthetic', :t)", c=cohort_id, t=STAMP)
            tx.execute("INSERT INTO roster (cohort_id, student_ref) VALUES (:c, 'amara-o')",
                       c=cohort_id)
        package = store.package(package_id)
        with package.transaction() as tx:
            tx.execute("INSERT INTO package (package_id, created_at) VALUES (:p, :t)",
                       p=package_id, t=STAMP)
        self.catalog = PackageCatalog(package, package_id=package_id)
        self.version = self.catalog.create_version(None, PackageDraft(title=package_id))
        for criterion_id, question_id in (("C1", "Q1"), ("C2", "Q2")):
            self.catalog.add_criterion(self.version, criterion_id, question_id=question_id,
                                       kind="open", max_points=4.0)
        self.vlm = _ScriptedVlm()
        self.ingestor = Ingestor(
            self.handle, self.blobs, self.vlm,
            ModelRef(role="transcriber", provider="local", build_id="vlm@sha256:cccc",
                     quantization="q4"),
            SamplingParams(temperature=0.0), _ScriptedRasterizer(),
            residency=ResidencySlot.for_policy(("transcriber",)),
            sanitizer=_ThroughSanitizer(),
        )
        source = self.blobs.put(f"assessment-{package_id}".encode())
        self.vlm.texts[(source, 1)] = "Assessment: Assessment Alpha\n" + "\n".join(
            f"<!-- region: kind=transcribed_text question_id={q} -->\n{text}\n<!-- /region -->"
            for q, text in ASSESSMENT_QUESTIONS.items()
        )
        self.ingestor.ingest_document([source], kind="assessment",
                                      filenames={source: "assessment.md"})

    def submit(self, tag: str, *, printed: str | None, answers: dict[str, str],
               extra_regions: str = "") -> Any:
        head = f"Assessment: {printed}\n" if printed else ""
        regions = "\n".join(
            f"<!-- region: kind=transcribed_text question_id={q} state=present -->\n{body}\n"
            "<!-- /region -->"
            for q, body in answers.items()
        )
        source = self.blobs.put(f"{self.cohort_id}-{tag}".encode())
        self.vlm.texts[(source, 1)] = f"{head}Student: amara-o\n{regions}{extra_regions}"
        return self.ingestor.ingest_submission(
            [source], cohort_id=self.cohort_id, package_version=self.version,
            package_catalog=self.catalog, filenames={source: f"{tag}.md"},
        )

    def submit_match(self, tag: str) -> Any:
        return self.submit(tag, printed=self.package_id, answers=MATCH_ANSWERS)

    def submit_mismatch(self, tag: str) -> Any:
        return self.submit(tag, printed="History Final", answers=MISMATCH_ANSWERS)


def rows(handle: Any, sql: str, **params: Any) -> list[dict[str, Any]]:
    """A direct read of the store — the oracle side, never the console's report."""
    return [dict(row) for row in handle.query(sql, **params)]


def count(handle: Any, table: str) -> int:
    """`SELECT COUNT(*)` over one table: the row-count invariants' unit of measure."""
    return int(handle.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"])


__all__ = [
    "MCQ_CRITERIA",
    "OPEN_CRITERIA",
    "OPTIONS",
    "STAMP",
    "ScoredRun",
    "count",
    "rows",
    "seed_scored_run",
]
