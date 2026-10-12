"""Writing one student's feedback document as a PDF, and safe file names for it.

The emitter below is shared with the console's readable package export
(`FR-CONSOLE-59`, #762): `text_pdf_bytes` turns lines of teacher text into the same
deterministic PDF the per-student document uses, so both exports answer the same
writer and the byte-stability argument is made once.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence


#: The most text lines one page carries before the emitter starts a continuation page.
#: Letter page, 12 pt type, 16 pt leading from y=720: 45 lines put the last baseline 16
#: points above the page's foot. A constant in code, not an environment read — the
#: console's read passes its own env-gated value (seam 3) as an argument, so this module
#: stays a pure function of its inputs.
PDF_PAGE_LINES = 45


def _safe_filename_part(raw: str) -> str:
    """A run id or student reference made safe for a file name: any character outside the allowed
    set becomes an underscore."""
    return "".join(
        character if character.isalnum() or character in "-_." else "_"
        for character in raw
    )


def _escape(text: str) -> str:
    """A line's text as a PDF string literal: backslash and parentheses escaped."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _page_stream(lines: Sequence[str]) -> bytes:
    """One page's content stream: the lines set from the top-left margin, 16 pt leading.

    cp1252 with replacement: the documents are ASCII by construction (refs and
    figures); a line that carries wider text degrades to '?' rather than crashing an
    export."""
    parts = ["BT", "/F1 12 Tf", "72 720 Td"]
    for index, line in enumerate(lines):
        if index:
            parts.append("0 -16 Td")
        parts.append(f"({_escape(line)}) Tj")
    parts.append("ET")
    return "\n".join(parts).encode("cp1252", errors="replace")


def _assemble(page_streams: Sequence[bytes]) -> bytes:
    """The PDF wire form over one or more page streams, by hand on purpose (no PDF library).

    A PDF library (or a text-report dependency) would buy nothing these documents
    need and would add a reviewed supply-chain surface for it; the documents are text
    pages, and the emitter that writes them is ~40 lines with **no** volatile field
    anywhere — no creation date, no producer string, no file id — so the same lines
    produce byte-identical bytes on every machine, which is what makes the exports
    regression baselines at all (`TC-REG-03`'s normalization has nothing to strip
    because nothing volatile is ever emitted). Letter-size pages, Helvetica, one line
    of text per line below.

    Object numbering: 1 the catalog, 2 the page tree, 3 the first page, 4 the one
    shared font (every page's `/F1 4 0 R`), and from the second page on each page
    object at the next even number with its content stream right behind it at the odd
    one — page `i` (`i` from 1) is object `2i + 4` carrying `/Contents 2i+5 0 R`. With
    one page the layout is exactly the five objects the regression baselines pin."""
    streams = list(page_streams)
    if not streams:  # an empty line list is one empty page, not no document
        streams = [_page_stream(())]
    kids = [3] + [2 * i + 4 for i in range(1, len(streams))]
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [{}] /Count {} >>".format(
            " ".join(f"{number} 0 R" for number in kids), len(streams)
        ).encode("ascii"),
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for index, stream in enumerate(streams):
        if index:
            objects.append(
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                "/Resources << /Font << /F1 4 0 R >> >> /Contents {} 0 R >>".format(
                    2 * index + 5
                ).encode("ascii")
            )
        objects.append(
            b"<< /Length " + str(len(stream)).encode("ascii")
            + b" >>\nstream\n" + stream + b"\nendstream"
        )
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 65535 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)


def text_pdf_bytes(lines: Sequence[str], *, page_lines: int | None = None) -> bytes:
    """Lines of plain text as deterministic PDF bytes, one page per `page_lines` lines.

    The shared emitter: the per-student document (`_student_pdf_bytes`) and the console's
    readable package export (`FR-CONSOLE-59`) both come from here, so neither can drift
    from the other's determinism. With up to `PDF_PAGE_LINES` lines the output is the
    single-page form the regression baselines pin byte for byte; more lines start a
    continuation page, laid out identically."""
    limit = PDF_PAGE_LINES if page_lines is None else page_lines
    if limit < 1:
        raise ValueError(f"page_lines {limit!r} is not a positive number of lines")
    lines = list(lines)
    pages = [lines[i:i + limit] for i in range(0, len(lines), limit)] or [[]]
    return _assemble(_page_stream(page) for page in pages)


def _student_pdf_bytes(
    *,
    run_id: str,
    revision: int,
    student_ref: str,
    total: float | None,
    grade: str | None,
    state: str,
    coverage: tuple[int, int, int, int, int],
    missing: Sequence[str],
) -> bytes:
    """One student's feedback document as PDF bytes, through `text_pdf_bytes`."""
    criteria_total, auto, reviewed, provisional, missing_count = coverage
    lines = [
        f"Grade report - {run_id} (revision {revision})",
        f"Student: {student_ref}",
        "Mark: "
        + ("(no figure recorded)" if total is None else f"{float(total):.2f}"),
        "Grade: " + (grade if grade else "(none recorded)"),
        f"State: {state}",
        "Criteria: "
        + f"{criteria_total} total, {auto} auto, {reviewed} reviewed, "
        + f"{provisional} provisional, {missing_count} missing",
    ]
    if missing:
        lines.append("Missing criteria: " + ", ".join(missing))
    return text_pdf_bytes(lines)


def _write_student_pdf(path: Path, **fields: Any) -> None:
    """Write one student's PDF (from `_student_pdf_bytes`) to `path`."""
    path.write_bytes(_student_pdf_bytes(**fields))
