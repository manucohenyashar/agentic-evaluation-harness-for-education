"""Writing one student's feedback document as a PDF, and safe file names for it."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence


def _safe_filename_part(raw: str) -> str:
    """A run id or student reference made safe for a file name: any character outside the allowed
    set becomes an underscore."""
    return "".join(
        character if character.isalnum() or character in "-_." else "_"
        for character in raw
    )


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
    """One student's feedback document as PDF bytes, built by hand on purpose (no PDF library).

    A PDF library (or a text-report dependency) would buy nothing this document
    needs and would add a reviewed supply-chain surface for it; the document is a
    single text page, and the emitter that writes it is ~30 lines with **no**
    volatile field anywhere — no creation date, no producer string, no file id — so
    the same student's mark at the same revision produces byte-identical bytes on
    every machine, which is what makes the per-student PDF a regression baseline at
    all (`TC-REG-03`'s normalization has nothing to strip because nothing volatile
    is ever emitted). Letter-size page, Helvetica, one line of text per line below:
    the marks, the grade band, the state and the coverage record (`CT-GRADE-04`'s
    render-coverage-alongside obligation reaches the student's own document).
    """
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

    def _escape(text: str) -> str:
        return (
            text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        )

    content_parts = ["BT", "/F1 12 Tf", "72 720 Td"]
    for index, line in enumerate(lines):
        if index:
            content_parts.append("0 -16 Td")
        content_parts.append(f"({_escape(line)}) Tj")
    content_parts.append("ET")
    # cp1252 with replacement: the document is ASCII by construction (refs and
    # figures); a store row that carries wider text degrades to '?' rather than
    # crashing a student's export.
    stream = "\n".join(content_parts).encode("cp1252", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii")
        + b" >>\nstream\n" + stream + b"\nendstream",
    ]
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


def _write_student_pdf(path: Path, **fields: Any) -> None:
    """Write one student's PDF (from `_student_pdf_bytes`) to `path`."""
    path.write_bytes(_student_pdf_bytes(**fields))
