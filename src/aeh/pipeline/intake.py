"""Reading scanned papers into a cohort: `aeh ingest` (live-test blocker B4).

Before this, nothing shipped turned a scan into a read, checked paper: the console's upload is
stored and never read, and the only callers of `Ingestor.ingest_submission` were test worlds and
the conformance suite. This is the operator's path: the test paper and a folder of answer sheets
(one PDF per student) are read with the page-reading model the run configuration names, through
the five intake checks (V0-V4), and every paper that fails one waits in quarantine.

The model is the one the resolved profile names, built by the same `_provider_for` a run uses,
so under `dev-ci` the pages go to OpenRouter with zero data retention enforced on every request,
and the consent gate (`FR-CONF-08`) has already decided, in `resolve_run_config`, whether this
cohort's work may leave the machine at all. These calls are not counted against a run's cost
ceiling: no run exists yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence


@dataclass(frozen=True)
class SheetOutcome:
    """One answer sheet's intake: its file, the submission it became, and what the checks said."""

    file: str
    status: str
    submission_id: str | None = None
    gates: dict[str, str] = field(default_factory=dict)
    detail: str = ""


@dataclass(frozen=True)
class IntakeResult:
    """What `aeh ingest` did, sheet by sheet (seam 4: what each step did, beside the status)."""

    cohort_id: str
    package_version: str
    assessment: str
    sheets: tuple[SheetOutcome, ...]
    read: int
    quarantined: int
    skipped: int
    # Submissions an earlier, cut-off read left behind, parked in quarantine before this read.
    interrupted: tuple[str, ...] = ()

    @property
    def nothing_readable(self) -> bool:
        """Every sheet read this time stopped before its student was looked for. One unreadable
        scan is a scan; all of them is the page reader (a key, credit, or model problem)."""
        attempted = [o for o in self.sheets if o.submission_id]
        return bool(attempted) and all(o.gates.get("v3") == "not_reached" for o in attempted)


def answer_sheet_files(paths: Sequence[str | Path]) -> tuple[Path, ...]:
    """The PDFs to read: each path is a PDF, or a folder whose `*.pdf` files are taken in name
    order. Anything else is refused before a page is read."""
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            found = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
            if not found:
                raise ValueError(f"{path} holds no .pdf files.")
            files.extend(found)
        elif path.is_file() and path.suffix.lower() == ".pdf":
            files.append(path)
        else:
            raise ValueError(f"{path} is not a PDF file or a folder of them.")
    if len({p.resolve() for p in files}) != len(files):
        raise ValueError("the same answer sheet is named twice.")
    return tuple(files)


def ingest_files(store: Any, run_config: Any, cohort_id: str, package_version: str, *,
                 assessment: str | Path | None, sheets: Sequence[Path],
                 provider: Any = None,
                 on_sheet: Callable[[SheetOutcome], None] | None = None) -> IntakeResult:
    """Read the test paper (unless the cohort already holds it) and every answer sheet.

    One PDF is one student's paper. A sheet whose scan was already read into this cohort is
    skipped, not read again: `ingest_submission` mints a submission per call, and two for one
    paper would grade the student twice. A sheet the checks refuse is quarantined and the next
    is read (fail the unit, never the run); the cohort breaker (too many wrong-test papers)
    stops the command, because it halts the cohort. `on_sheet` is told of each sheet as it is
    done, so a long read shows its progress.
    """
    from aeh.conf import hardware_policy_for
    from aeh.ingest import (
        IngestCohortBreakerTripped,
        IngestError,
        Ingestor,
        PdfiumRasterizer,
        PypdfSanitizer,
        ResidencySlot,
        has_assessment_document,
        park_interrupted_submissions,
        submitted_sources,
    )
    from aeh.orch import default_package_id_for
    from aeh.pkg import PackageCatalog
    from aeh.prov import SamplingParams

    from .runtime import _provider_for

    package_id = default_package_id_for(package_version)
    catalog = PackageCatalog(store.package(package_id), package_id=package_id,
                             blobs=store.blobs())
    if not catalog.criteria(package_version):
        raise ValueError(f"package version {package_version!r} holds no criteria; build it with "
                         f"'aeh package build' first.")
    policy = hardware_policy_for(run_config)
    residency = ResidencySlot.for_policy(
        tuple(policy.residency_policy) if policy is not None else ("transcriber",))
    handle = store.cohort(cohort_id)
    blobs = store.blobs()
    ingestor = Ingestor(handle, blobs, provider if provider is not None else _provider_for(run_config),
                        run_config.transcriber, SamplingParams(temperature=0.0),
                        PdfiumRasterizer(), sanitizer=PypdfSanitizer(), residency=residency,
                        package_catalog=catalog, package_version=package_version)

    if has_assessment_document(handle):
        # Review finding: a different test paper given now is not read; say so.
        assessment_note = ("already read" if assessment is None else
                           f"already read; {Path(assessment).name} was not read again")
    elif assessment is None:
        raise ValueError("this cohort holds no test paper yet: pass --assessment <test-paper.pdf> "
                         "(the right-test check compares each paper with it).")
    else:
        paper = blobs.put(Path(assessment).read_bytes())
        ingestor.ingest_document([paper], kind="assessment", order_hint=[paper],
                                 package_version=package_version,
                                 filenames={paper: Path(assessment).name})
        assessment_note = f"read from {Path(assessment).name}"

    interrupted = park_interrupted_submissions(handle)
    done = submitted_sources(handle)
    outcomes: list[SheetOutcome] = []

    def record(outcome: SheetOutcome) -> None:
        outcomes.append(outcome)
        if on_sheet is not None:
            on_sheet(outcome)

    for index, path in enumerate(sheets):
        blob = blobs.put(path.read_bytes())
        if blob in done:
            record(SheetOutcome(file=path.name, status="skipped",
                                detail="already read into this cohort"))
            continue
        try:
            report = ingestor.ingest_submission(
                [blob], cohort_id, package_version, order_hint=[blob],
                filenames={blob: path.name}, package_catalog=catalog)
        except IngestCohortBreakerTripped as error:
            record(SheetOutcome(file=path.name, status="stopped", detail=str(error)))
            for rest in sheets[index + 1:]:
                record(SheetOutcome(file=rest.name, status="not_read",
                                    detail="the cohort was stopped before this sheet"))
            break
        except IngestError as error:
            record(SheetOutcome(file=path.name, status="error",
                                detail=f"{type(error).__name__}: {error}"))
            continue
        done = done | {blob}
        findings = "; ".join(
            str(f.get("finding")) for f in (report.detail or {}).get("findings", ())
            if isinstance(f, dict) and f.get("finding"))
        record(SheetOutcome(file=path.name, status=report.ingest_status,
                            submission_id=report.submission_id, gates=dict(report.gates),
                            detail=findings))
    read = sum(1 for o in outcomes if o.submission_id)
    return IntakeResult(
        cohort_id=cohort_id, package_version=package_version, assessment=assessment_note,
        sheets=tuple(outcomes), read=read,
        quarantined=sum(1 for o in outcomes if o.submission_id and o.status != "ok"),
        skipped=sum(1 for o in outcomes if o.status == "skipped"), interrupted=interrupted)
