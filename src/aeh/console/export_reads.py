"""The export reads (FR-CONSOLE-58, FR-CONSOLE-59, #762): the results workbook and the
readable package export — each returning the file the way the existing results export
does, and each through the door the module that owns the data already offers.

They are reads, not control rows. §3.2.2 lists them among the redesign's new actions,
and their behaviour column says what they are: *synchronous, returns the file like the
existing exports*. The existing exports are file-returning GET reads
(`FR-CONSOLE-44`'s `results export`); bytes cannot ride the control-outcome JSON, and
neither export writes anything the control surface owns — the workbook reads the
grades the run already holds, and the readable export writes its two files into a
temporary directory, so a fetched read changes no stored byte (the read-route write
audit, `CT-CONSOLE-30`)."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

from aeh.grade import GradeError, grade_workbook_bytes
from aeh.grade.pdf import text_pdf_bytes
from aeh.pkg import ExportBlockedError, PackageCatalog, PackageError, points_for_band

from .results_reads import _run_id_of
from .settings import pdf_page_lines

#: The readable export's two formats on one route, the way the results export carries
#: csv and pdf on its one route: `pdf` (the default) is the teacher-readable document,
#: `aehpkg` is the backup the re-import path (`aeh package import`, M-PKG's
#: `import_file`) accepts — the same bytes the `export/import package` control writes
#: into the exports directory, produced here beside the PDF without touching it.
READABLE_FORMATS = ("pdf", "aehpkg")

#: The `.aehpkg` backup's media type: an opaque archive to the browser, imported by name.
AEHPKG_CONTENT_TYPE = "application/octet-stream"


#: The version-id shape the export control validates (`_export_effect`'s guard), checked
#: here for the same reason: a version id is about to become a file name.
_VERSION_SHAPE = re.compile(r"[A-Za-z0-9_.@-]+")


def workbook_export_read(app: Any, query: Any) -> Any:
    """The run's marks as an `.xlsx` workbook (`FR-CONSOLE-58`): the same rows the marks
    CSV carries, through `grade_workbook_bytes` — the school-facing export's own producer
    side. A `FileAnswer`, so the bytes leave the same synchronous path the CSV and PDF
    exports leave. Raises `ValueError` for a missing run id, a revision that is not a
    number, or a run no ledger holds — the caller's mistake, the same refusal the export
    read answers with."""
    run_id = _run_id_of(query, "results workbook")
    raw_revision = str(query.get("revision") or "1")
    try:
        revision = int(raw_revision)
    except ValueError as exc:
        raise ValueError(f"results workbook revision {raw_revision!r} is not a number") from exc
    try:
        export = grade_workbook_bytes(run_id, revision, store=app._store)
    except GradeError as refusal:
        # A missing run or revision is a refusal, not a crash (the export read's shape).
        raise ValueError(str(refusal)) from refusal
    from .api import FileAnswer

    return FileAnswer(export.body, export.content_type)


def readable_package_export_read(app: Any, query: Any) -> Any:
    """The package as a teacher-readable document (`FR-CONSOLE-59`): the questions and
    the grading guide as the shared deterministic PDF emitter renders them, and — on the
    same route, `format=aehpkg` — the `.aehpkg` backup whose re-import path already
    exists. Both artefacts come from M-PKG's own export path: `PackageCatalog.export`
    writes the backup (its provenance gate, `FR-PKG-11`, refuses a package that carries
    real student text — the same teacher-language refusal the control action answers
    with), and the PDF's lines are read from the same catalog, so the document and the
    backup cannot disagree about what the package says.

    Both files are written into a temporary directory and read back, like the results
    export's: the console serves the same bytes a CLI export writes and writes nothing
    durable of its own. The PDF is a pure function of the package's rows — no timestamp,
    no store path — so the same package version exports byte-identical bytes
    (`TC-CONSOLE-67`)."""
    package_version = str(query.get("package_version") or "")
    if not package_version:
        raise ValueError("the readable package export names a package version "
                         "(package_version)")
    if not _VERSION_SHAPE.fullmatch(package_version) or ".." in package_version:
        raise ValueError(f"{package_version!r} is not a package version id")
    package_id = app._package_of(package_version)
    if not app._known_package(package_id):
        # The never-create rule: an unknown version's Tier P file must not be created by
        # the read that looks for it (the start-run effect's rule, on the same tier).
        raise ValueError(f"no stored package version {package_version!r}; nothing was exported")
    fmt = str(query.get("format") or "pdf").strip().lower()
    if fmt not in READABLE_FORMATS:
        raise ValueError(f"readable package export format {fmt!r} is neither 'pdf' "
                         "nor 'aehpkg'")

    catalog = PackageCatalog(app._store.package(package_id), package_id=package_id,
                             blobs=app._store.blobs())
    with tempfile.TemporaryDirectory(prefix="aeh-console-readable-") as tmp:
        backup = Path(tmp, f"{package_version}.aehpkg")
        try:
            catalog.export(package_version, backup)
        except (ExportBlockedError, PackageError) as refusal:
            # M-PKG's gate speaks for itself (the provenance report is teacher language);
            # a read answers a refusal with a 400, never a traceback.
            raise ValueError(str(refusal)) from refusal
        if fmt == "aehpkg":
            body = backup.read_bytes()
            content_type = AEHPKG_CONTENT_TYPE
        else:
            body = text_pdf_bytes(
                _readable_lines(catalog, package_version, package_id),
                page_lines=pdf_page_lines(),
            )
            content_type = "application/pdf"

    from .api import FileAnswer

    return FileAnswer(body, content_type)


def _readable_lines(
    catalog: Any, version: str, package_id: str
) -> list[str]:
    """The package's questions and grading guide as lines of teacher text.

    Everything here is the package's own wording — the confirmed prompts, the option
    labels, the construct each criterion marks, the band descriptors, and the grade
    policy's generated plain-language sentence (`FR-PKG-15`). No stored identifier is
    rendered where a teacher word exists for it, and no configuration syntax is
    emitted anywhere (`CT-CONSOLE-31`): the extraction oracle reads prose, not TOML.
    The order is the stored order (questions by ordinal, criteria by id, bands by
    ordinal), so the same version always renders the same lines."""
    lines = [
        f"Package: {package_id} (version {version})",
        "What this test asks, and how it is graded",
        "",
        "The questions",
        "",
    ]
    questions = catalog.questions(version)
    criteria = catalog.criteria(version)
    # The answer choices, keyed by question id. A confirmed inventory carries its own
    # `question_option` rows; a package whose options live only on the criteria (the
    # authoring path that never confirmed an inventory) still has them, so the
    # criterion's stored options back the question up rather than the document dropping
    # the line a teacher needs to see what the paper offered.
    criterion_options: dict[str, str] = {}
    for criterion in criteria:
        question_id = str(criterion["question_id"] or "")
        if question_id and question_id not in criterion_options:
            options = catalog.mcq_options(version, str(criterion["criterion_id"]))
            if options:
                criterion_options[question_id] = "; ".join(
                    str(option[1] or "") for option in options
                )
    if not questions:
        lines.append("This package version carries no confirmed questions yet.")
        lines.append("")
    for number, question in enumerate(questions, start=1):
        lines.append(f"Question {number}: {question['prompt_text'] or ''}")
        options = catalog.question_options(version, str(question["question_id"]))
        if options:
            choices = "; ".join(str(option["label"] or "") for option in options)
        else:
            choices = criterion_options.get(str(question["question_id"]), "")
        if choices:
            lines.append(f"  The answers to choose from: {choices}")
        lines.append("")

    if criteria:
        lines.append("What each question is marked on")
        lines.append("")
        for criterion in criteria:
            heading = str(criterion["construct_tag"] or "").strip()
            lines.append(f"Marked on: {heading or 'the answer to this question'}")
            justification = str(criterion["band_justification"] or "").strip()
            if justification:
                lines.append(f"  Why the bands sit where they do: {justification}")
            criterion_bands = [dict(band) for band in catalog.bands(str(criterion["criterion_id"]))]
            for band in criterion_bands:
                # Through M-PKG's one band-to-points reader (CT-PKG-05), never the column.
                points = float(points_for_band(criterion_bands, str(band["band"])))
                figure = f"{points:g}"
                descriptor = str(band["descriptor"] or "").strip()
                lines.append(f"  {band['band']} ({figure} points): {descriptor}")
            lines.append("")

    lines.append("How the marks become a grade")
    lines.append("")
    for sentence in str(catalog.grade_policy(version).plain_language).splitlines():
        sentence = sentence.strip()
        if sentence:
            lines.append(sentence)
    lines.append("")
    return lines
