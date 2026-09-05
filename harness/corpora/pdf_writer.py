"""A minimal, byte-deterministic PDF writer.

`F-ADV-PDF` is *"generated, not committed as binaries"* (test plan §4.7), and §4.8 makes it an
entry criterion that it be *"generated and reproducible from committed scripts"*. Reproducible
means byte-identical on every machine and in six months' time, so this writer exists rather
than `pikepdf`:

* **No timestamps, no `/ID`, no producer string.** A real PDF library stamps `/CreationDate`,
  `/ModDate` and a random file `/ID` — three values that change on every run and would make
  the declared digests in `fixtures/F-ADV-PDF/manifest.json` wrong the moment anybody
  regenerated the corpus.
* **No third-party dependency.** A declared digest over `pikepdf` output changes when
  `pikepdf` changes, so a routine dependency bump would fail the reproducibility check with a
  diff nobody could explain. All fourteen §4.4 constructs are *structural* — dictionary keys
  and stream contents — so raw byte emission is both simpler and permanently stable.

The output is a real PDF: header, numbered objects, a cross-reference table with correct byte
offsets, a trailer, and `startxref`. Parsers must actually parse these files, or the fixtures
would prove that ingestion rejects malformed bytes rather than that it neutralizes the
construct each one carries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

PDF_HEADER = b"%PDF-1.7\n"

# A binary comment line directly after the header. Every real producer writes one — it tells
# transfer software the file is binary — and its absence is the kind of incidental difference
# that would make a fixture rejected as "not a PDF" before the construct under test was ever
# reached.
BINARY_COMMENT = b"%\xe2\xe3\xcf\xd3\n"


@dataclass(frozen=True)
class PdfObject:
    """One indirect object: its number, and the bytes between `obj` and `endobj`."""

    number: int
    body: bytes


def stream_object(number: int, dictionary: bytes, data: bytes) -> PdfObject:
    """A stream object whose `/Length` is the real length of `data`.

    `/Length` is written from the data rather than declared separately: a stream whose declared
    length disagrees with its content is a *different* malformed-file construct, and getting it
    by accident in the decompression-bomb fixture would confuse two findings into one.
    """
    head = dictionary.rstrip()
    assert head.startswith(b"<<") and head.endswith(b">>"), "a stream needs a dictionary"
    head = head[:-2].rstrip() + b" /Length " + str(len(data)).encode("ascii") + b" >>"
    return PdfObject(number, head + b"\nstream\n" + data + b"\nendstream")


def build_pdf(objects: Sequence[PdfObject], trailer_extra: bytes = b"",
              root: int = 1) -> bytes:
    """Assemble numbered objects into a PDF with a correct xref table.

    `objects` need not be contiguous or sorted; free slots are emitted as free entries, which
    is what the zero-page and truncated fixtures need in order to stay parseable up to the
    point where they are supposed to fail.
    """
    by_number = {obj.number: obj for obj in objects}
    assert len(by_number) == len(objects), "duplicate object number"
    size = max(by_number) + 1

    out = bytearray(PDF_HEADER + BINARY_COMMENT)
    offsets: dict[int, int] = {}
    for number in sorted(by_number):
        offsets[number] = len(out)
        out += str(number).encode("ascii") + b" 0 obj\n"
        out += by_number[number].body
        out += b"\nendobj\n"

    xref_offset = len(out)
    out += b"xref\n0 " + str(size).encode("ascii") + b"\n"
    # Entry 0 is always the head of the free list, and the format is fixed-width by spec:
    # exactly 20 bytes per entry, `nnnnnnnnnn ggggg n\r\n`. Getting the width wrong produces a
    # file most parsers still open by rebuilding the table — which would silently turn every
    # fixture here into a "damaged file" test rather than the construct it names.
    out += b"0000000000 65535 f \n"
    for number in range(1, size):
        if number in offsets:
            out += b"%010d 00000 n \n" % offsets[number]
        else:
            out += b"0000000000 65535 f \n"

    out += b"trailer\n<< /Size " + str(size).encode("ascii")
    out += b" /Root " + str(root).encode("ascii") + b" 0 R"
    if trailer_extra:
        out += b" " + trailer_extra.strip()
    out += b" >>\nstartxref\n" + str(xref_offset).encode("ascii") + b"\n%%EOF\n"
    return bytes(out)


def simple_page_document(extra_catalog: bytes = b"", extra_page: bytes = b"",
                         extra_objects: Iterable[PdfObject] = (),
                         page_text: str = "Question 1") -> bytes:
    """A one-page document, with room to graft a construct onto the catalog or the page.

    Every active-content fixture is this document plus one dictionary key, which is what makes
    the corpus a *differential*: the only difference between the `/Launch` fixture and a clean
    PDF is the `/Launch` action. A fixture that also differed in page count or content stream
    would let an implementation quarantine it for the wrong reason and still look correct.
    """
    content = (
        b"BT /F1 12 Tf 72 720 Td ("
        + page_text.encode("ascii")
        + b") Tj ET\n"
    )
    objects = [
        PdfObject(1, b"<< /Type /Catalog /Pages 2 0 R" + extra_catalog + b" >>"),
        PdfObject(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        PdfObject(
            3,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
            b" /Resources << /Font << /F1 5 0 R >> >>" + extra_page + b" >>",
        ),
        stream_object(4, b"<< >>", content),
        PdfObject(5, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
        *extra_objects,
    ]
    return build_pdf(objects)
