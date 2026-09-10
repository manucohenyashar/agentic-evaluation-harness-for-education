"""`F-SCAN` — synthetic rendered scans: the real-medium tier issue #133 commits.

`FR-CONFORM-03` requires the conformance corpus to carry *real scanned handwriting spanning
legible to marginal* and *a mixed-format paper*, and #133's technical note says the corpora are
built once, from committed generation scripts, extending what TS-02 shipped rather than
duplicating it. This module is that generator for the media classes no committed corpus has:
every member is a parseable PDF whose answer content exists only as ink pixels — the medium a
transcriber must actually be run against, with no text layer to shortcut through.

What "synthetic" and "real medium" mean here, stated once so neither word does quiet work
------------------------------------------------------------------------------------------
The **medium** claim is honest: each member's student work exists as a bilevel image raster in
an image XObject, the same medium a photocopied exam has, and the handwritten pages carry no
text layer to shortcut through. The *handwriting* is declared synthetic — the manifest's
`rendering` field says so outright: the strokes are drawn from a committed glyph table by a
seeded renderer. Nothing here is a scan of a real person's writing, and no member pretends
otherwise; that is `F-HAND`'s job, and `F-HAND` is the only consented real corpus in the tree
(`harness.corpora.hand`).

Why every page also carries *typed* header lines
------------------------------------------------
Each page has a printed form header — submission id, `student_ref`, `consent_class: synthetic`,
the printed `Page N of 4` line — drawn as PDF text operators in an uncompressed content stream.
Two reasons pull the same way. First, §4.4's consent declaration must be assertable from the
committed bytes the way it is for every text corpus; a pixel-only page could carry no
assertable declaration without putting OCR inside the sweep. Second, it is what a scanned
answer booklet actually looks like: a pre-printed header, handwritten answers below. The
student work stays pixels-only — the header is form furniture — so `CT-CONFORM-02`'s traversal
claim survives: transcribing these pages still means reading the raster.

Determinism and size
--------------------
The renderer is stdlib-only and byte-deterministic: strokes come from a fixed glyph table, all
jitter draws come from one seeded `random.Random` (§4.6), the pixel buffer is packed by hand,
and the PDF writer emits streams with no filter — the committed digests are a function of this
module and of nothing else, so no compression library's version can move a hash. At 1 bit per
pixel a page's payload is ~43 KB, so the corpus stays fixture-sized. Reference bands and points
come from the same `synth.generate` the other submission corpora use: one generator for what
the work says, one renderer for what the scan looks like.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Mapping, Sequence

from harness.corpora import hand
from harness.corpora import synth
from harness.corpora.pdf_writer import PdfObject, build_pdf, image_object, stream_object
from harness.corpora.reference_package import points_for

SCAN_SEED = 20260104

#: One body image, in pixels. The MediaBox page is 612×792 pt; the region this image paints is
#: 540 wide (36 pt margins) and 640 tall, below the printed form header. At 1 bit per pixel the
#: payload is 68 bytes × 640 rows ≈ 43 KB — three orders of magnitude under `FR-INGEST-34`'s
#: ceilings, and small enough that `python -m harness.corpora.build` finishes in seconds.
BODY_WIDTH = 540
BODY_HEIGHT = 640

#: Pixel geometry. One grid unit is 2.2 px, so a glyph is ~9 px wide and ~13 px tall — small
#: but readable, which is the point: SC-01 must be genuinely legible and the marginal pair
#: genuinely strained, not merely declared so.
SCALE = 2.2
#: Glyph advance: glyph box (4 units) plus inter-character gap (2 units).
ADVANCE = 6 * SCALE
#: One text line, glyph box plus leading.
LINE_HEIGHT = 9 * SCALE
#: The longest line the body fits, derived so wrapping is a function of the geometry — one
#: column shaved off the exact fit, because jitter and squeeze push the last glyph past a
#: margin that was already tight.
CHARS_PER_LINE = int(BODY_WIDTH / ADVANCE) - 1


# --- the glyph table -------------------------------------------------------------------------

#: Hand-authored stroke glyphs on a 4-wide, 6-tall grid (x grows right, y grows up from the
#: baseline). Each glyph is a tuple of polyline strokes; the renderer fattens them into ink
#: pixels. Written out rather than generated, so the "handwriting" is a committed, reviewable
#: artifact rather than a parameter nobody can argue with.
_GLYPHS: Mapping[str, tuple[tuple[tuple[float, float], ...], ...]] = {
    "A": (((0, 0), (2, 6)), ((2, 6), (4, 0)), ((0.6, 2), (3.4, 2))),
    "B": (((0, 0), (0, 6)), ((0, 6), (2.6, 5.4), (3, 4.4), (0, 3.2)),
          ((0, 3.2), (2.4, 2.6), (2.6, 1.2), (0, 0))),
    "C": (((3.8, 5.2), (2.8, 6), (1.2, 6), (0.2, 4.8), (0, 3), (0.2, 1.2), (1.2, 0),
           (2.8, 0), (3.8, 0.8)),),
    "D": (((0, 0), (0, 6)), ((0, 6), (2.6, 5.4), (3.4, 4), (3.4, 2), (2.4, 0.4), (0, 0))),
    "E": (((0, 0), (0, 6)), ((0, 6), (3.8, 6)), ((0, 3), (3, 3)), ((0, 0), (3.8, 0))),
    "F": (((0, 0), (0, 6)), ((0, 6), (3.8, 6)), ((0, 3), (2.8, 3))),
    "G": (((3.8, 5.2), (2.8, 6), (1.2, 6), (0.2, 4.8), (0, 3), (0.2, 1.2), (1.2, 0),
           (2.8, 0), (3.8, 0.8), (3.8, 2.4), (2.2, 2.4)),),
    "H": (((0, 0), (0, 6)), ((4, 0), (4, 6)), ((0, 3), (4, 3))),
    "I": (((0, 6), (2, 6)), ((1, 6), (1, 0)), ((0, 0), (2, 0))),
    "J": (((3, 6), (3, 1.2)), ((3, 1.2), (2.2, 0), (1, 0)), ((1, 0), (0, 1.2))),
    "K": (((0, 0), (0, 6)), ((3.8, 6), (0, 2.8)), ((1.4, 2.8), (3.8, 0))),
    "L": (((0, 6), (0, 0)), ((0, 0), (3.8, 0))),
    "M": (((0, 0), (0, 6)), ((0, 6), (2, 2.4)), ((2, 2.4), (4, 6)), ((4, 6), (4, 0))),
    "N": (((0, 0), (0, 6)), ((0, 6), (4, 0)), ((4, 0), (4, 6))),
    "O": (((2, 6), (3.4, 5.4), (4, 3.8), (3.8, 1.8), (2.6, 0.4), (1, 0.2), (0.2, 1.6),
           (0, 3.2), (0.6, 4.8), (2, 6)),),
    "P": (((0, 0), (0, 6)), ((0, 6), (2.8, 5.4), (3.2, 4.4), (2.4, 3.2), (0, 3.2))),
    "Q": (((2, 6), (3.4, 5.4), (4, 3.8), (3.8, 1.8), (2.6, 0.4), (1, 0.2), (0.2, 1.6),
           (0, 3.2), (0.6, 4.8), (2, 6)), ((2.4, 1.6), (3.8, 0))),
    "R": (((0, 0), (0, 6)), ((0, 6), (2.8, 5.4), (3.2, 4.2), (2.4, 3.2), (0, 3)),
          ((1.2, 3), (3.8, 0))),
    "S": (((3.6, 5.4), (2.4, 6), (1.2, 6), (0.2, 4.8), (0.8, 3.6), (2.6, 2.8),
           (3.4, 1.8), (2.8, 0.4), (1.2, 0), (0.2, 0.8)),),
    "T": (((0, 6), (4, 6)), ((2, 6), (2, 0))),
    "U": (((0, 6), (0, 1.4)), ((0, 1.4), (1.2, 0.2), (2.6, 0.4), (4, 1.8)),
          ((4, 1.8), (4, 6))),
    "V": (((0, 6), (2, 0), (4, 6)),),
    "W": (((0, 6), (1, 0)), ((1, 0), (2, 3.4)), ((2, 3.4), (3, 0)), ((3, 0), (4, 6))),
    "X": (((0, 0), (4, 6)), ((0, 6), (4, 0))),
    "Y": (((0, 6), (2, 3)), ((4, 6), (2, 3)), ((2, 3), (2, 0))),
    "Z": (((0, 6), (4, 6)), ((4, 6), (0, 0)), ((0, 0), (4, 0))),
    "0": (((2, 6), (3.4, 5.4), (4, 3.8), (3.8, 1.8), (2.6, 0.4), (1, 0.2), (0.2, 1.6),
           (0, 3.2), (0.6, 4.8), (2, 6)),),
    "1": (((0.4, 5), (1.6, 6)), ((1.6, 6), (1.6, 0)), ((0.4, 0), (2.8, 0))),
    "2": (((0.4, 4.6), (1.2, 6), (2.8, 6), (3.6, 4.8)),
          ((3.6, 4.8), (3.2, 2.8), (1.6, 1.2), (0, 0)), ((0, 0), (4, 0))),
    "3": (((0.4, 5), (1.2, 6), (2.8, 6), (3.4, 4.6)),
          ((3.4, 4.6), (3, 3.2), (1.8, 2.8)),
          ((1.8, 2.8), (3, 2.4), (3.4, 1.2), (2.8, 0), (1.2, 0), (0.4, 1))),
    "4": (((3, 0), (3, 6)), ((3, 6), (0, 2.4)), ((0, 2.4), (4, 2.4))),
    "5": (((3.6, 6), (0.6, 6)), ((0.6, 6), (0.4, 3.6), (2, 3.4), (3.4, 2.4), (3.4, 1),
          (2.4, 0.2), (1, 0.2), (0.2, 1.2))),
    "6": (((3.6, 6), (1.2, 4.2), (0.4, 2.6), (0.6, 1), (1.8, 0), (3, 0.6), (3.4, 1.8),
           (2.8, 2.8), (1.2, 3), (0.4, 2.6))),
    "7": (((0, 6), (4, 6)), ((4, 6), (1.2, 0))),
    "8": (((1, 6), (2.6, 6), (3.2, 4.8), (2.4, 3.6), (1, 3.6), (0.8, 4.8), (1, 6)),
          ((1, 3.4), (2.8, 3.4), (3.6, 2), (2.8, 0.4), (1.2, 0.2), (0.6, 1.8), (1, 3.4))),
    "9": (((0.4, 3), (0.6, 3.4), (1.6, 3), (2.8, 3.2), (3.4, 4.4), (3, 5.6), (1.6, 6),
           (0.6, 5.2)), ((3.4, 4.4), (3.4, 1.2), (2.6, 0))),
    ".": (((1.8, 0.4), (2.1, 0.1)),),
    ",": (((2.1, 1.4), (1.5, 0)),),
    "-": (((0.4, 3), (2.4, 3)),),
    ":": (((1.8, 4), (2.1, 3.7)), ((1.8, 1.2), (2.1, 0.9)),),
    "(": (((2.6, 6), (1.2, 3), (2.6, 0)),),
    ")": (((1.2, 6), (2.6, 3), (1.2, 0)),),
    "?": (((0.4, 4.8), (1, 6), (2.6, 6), (3.4, 4.8), (2.2, 3), (1.9, 2)),
          ((1.9, 0.6), (2.2, 0.3))),
}

#: Per-legibility rendering. `legible` is a steady hand: glyphs land where they are put.
#: `marginal` is the strained half of the span — wandering baselines, drifting glyph positions
#: and strokes that drop out — which is where two transcribers actually differ (`CT-CONFORM-02`:
#: a corpus of clean scans measures only the easy half).
_LEGIBILITY_SETTINGS: Mapping[str, Mapping[str, float]] = {
    "legible": {"glyph_jitter": 0.8, "point_jitter": 0.4, "dropout": 0.0, "drift": 1.0,
                "squeeze": 0.02},
    "marginal": {"glyph_jitter": 2.6, "point_jitter": 1.8, "dropout": 0.14, "drift": 4.0,
                 "squeeze": 0.12},
}


@dataclass(frozen=True)
class ScanSubmission:
    """One scanned-paper member: known reference bands, and the PDF the scan renders to."""

    submission_id: str
    student_ref: str
    bands: Mapping[str, str]
    media_kind: str
    legibility: str
    pdf: bytes

    @property
    def reference_points(self) -> float:
        return sum(points_for(cid, band) for cid, band in self.bands.items())


def _wrap(text: str, width: int) -> list[str]:
    """Wrap one paragraph to `width` columns, breaking on spaces.

    Handwriting does not break mid-word: a run that would overflow starts a new line, the way
    a real margin forces it.
    """
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if len(candidate) > width and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return lines


def _plot(canvas: bytearray, x: int, y: int) -> None:
    """One ink pixel plus its right and lower neighbour — the fat, photocopied stroke."""
    for px, py in ((x, y), (x + 1, y), (x, y + 1)):
        if 0 <= px < BODY_WIDTH and 0 <= py < BODY_HEIGHT:
            canvas[py * BODY_WIDTH + px] = 0


def _line(canvas: bytearray, a: tuple[float, float], b: tuple[float, float]) -> None:
    """Bresenham between two points, plotting the run."""
    x0, y0 = int(round(a[0])), int(round(a[1]))
    x1, y1 = int(round(b[0])), int(round(b[1]))
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    error = dx + dy
    while True:
        _plot(canvas, x0, y0)
        if x0 == x1 and y0 == y1:
            return
        doubled = 2 * error
        if doubled >= dy:
            error += dy
            x0 += sx
        if doubled <= dx:
            error += dx
            y0 += sy


def render_hand_page(text: str, *, legibility: str, rng: random.Random) -> bytes:
    """Render `text` as handwriting into the packed 1-bit body image for one page.

    The canvas is a raster: row 0 is the top scanline — which is how PDF image streams order
    their samples, whatever the page coordinate space does — so line 0 sits at the small-y
    end and every glyph's grid-y grows *upward from the baseline*, i.e. toward smaller rows.
    Every jitter draw comes from `rng` in a fixed order, which is what makes the committed
    bytes reproducible: same seed, same scan.
    """
    settings = _LEGIBILITY_SETTINGS[legibility]
    canvas = bytearray(b"\x01" * (BODY_WIDTH * BODY_HEIGHT))
    for line_no, line in enumerate(_wrap(text.upper(), int(CHARS_PER_LINE))):
        baseline = 24 + line_no * LINE_HEIGHT + rng.uniform(
            -settings["drift"], settings["drift"])
        if baseline > BODY_HEIGHT - SCALE * 9:
            break  # the body region is full; a scan cuts off what the page could not hold
        x = 0.0
        for ch in line:
            glyph = _GLYPHS.get(ch)
            offset_x = x + rng.uniform(-settings["glyph_jitter"], settings["glyph_jitter"])
            offset_y = baseline + rng.uniform(-settings["glyph_jitter"], settings["glyph_jitter"])
            advance = ADVANCE * (1 + rng.uniform(-settings["squeeze"], settings["squeeze"]))
            if glyph is None:
                x += advance
                continue
            for stroke in glyph:
                if settings["dropout"] and rng.random() < settings["dropout"]:
                    continue  # the pen lifted; the stroke is gone
                previous: tuple[float, float] | None = None
                for gx, gy in stroke:
                    point = (
                        offset_x + gx * SCALE
                        + rng.uniform(-settings["point_jitter"], settings["point_jitter"]),
                        offset_y - gy * SCALE
                        + rng.uniform(-settings["point_jitter"], settings["point_jitter"]),
                    )
                    if previous is None:
                        _plot(canvas, int(round(point[0])), int(round(point[1])))
                    else:
                        _line(canvas, previous, point)
                    previous = point
            x += advance
    return _pack(canvas)


def _pack(canvas: bytearray) -> bytes:
    """Pack the canvas into PDF image rows: 8 pixels per byte, MSB first, paper-padded.

    Rows are padded to a byte boundary with 1s (paper), so the padding is indistinguishable
    from the right margin — which is what a scan's margin is.
    """
    row_bytes = (BODY_WIDTH + 7) // 8
    out = bytearray()
    for y in range(BODY_HEIGHT):
        row = canvas[y * BODY_WIDTH:(y + 1) * BODY_WIDTH]
        # Start every byte as paper (1) and clear the ink pixels — so the tail padding of a
        # partial final byte is paper, the same margin the scan never wrote over.
        bits = bytearray(b"\xff" * row_bytes)
        for index, pixel in enumerate(row):
            if pixel == 0:
                bits[index // 8] &= ~(0x80 >> (index % 8)) & 0xFF
        out += bits
    return bytes(out)


# --- assembling the member PDFs ---------------------------------------------------------------


def _content_stream(page_no: int, submission_id: str, student_ref: str,
                    typed_lines: Sequence[str] | None) -> bytes:
    """One page's content stream: the printed form header, then either typed text or an image.

    Uncompressed, so the consent declaration is assertable from the committed bytes (`§4.4`,
    and the same reason every text corpus's document carries the declaration as text).
    """
    header = (
        b"BT /F1 11 Tf 36 750 Td (" + submission_id.encode("ascii") + b") Tj ET\n"
        b"BT /F1 8 Tf 36 736 Td (student_ref: " + student_ref.encode("ascii")
        + b"   consent_class: synthetic) Tj ET\n"
        b"BT /F1 8 Tf 36 722 Td (Page " + str(page_no).encode("ascii")
        + b" of 4 - " + submission_id.encode("ascii") + b") Tj ET\n"
    )
    if typed_lines is None:
        # The handwritten body: one image XObject painted over the body region. This is the
        # line that makes the medium real — the work is read from pixels or not at all.
        return header + b"q 540 0 0 640 36 40 cm /Im0 Do Q\n"
    body = bytearray(header)
    y = 690
    for line in typed_lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        body += b"BT /F1 10 Tf 36 " + str(y).encode("ascii") + b" Td ("
        body += escaped.encode("ascii") + b") Tj ET\n"
        y -= 14
    return bytes(body)


def _submission_pdf(submission_id: str, student_ref: str, page_specs: Sequence[dict]) -> bytes:
    """Assemble one member: a 4-page PDF whose pages are typed lines and/or scan images.

    Each spec is `{"typed": [lines...]}` for a typed page or `{"image": packed_bytes}` for a
    handwritten one. Object numbering is sequential and explicit: catalog 1, page tree 2, font
    3, then per page its content stream, the page itself, and — when the page is an image —
    the image XObject.
    """
    number = 3
    page_bodies: list[PdfObject] = []
    kids: list[bytes] = []
    for index, spec in enumerate(page_specs, start=1):
        number += 1
        content_number = number
        if "image" in spec:
            content = _content_stream(index, submission_id, student_ref, typed_lines=None)
        else:
            content = _content_stream(index, submission_id, student_ref,
                                      typed_lines=spec["typed"])
        page_bodies.append(stream_object(content_number, b"<< >>", content))
        number += 1
        page_number = number
        resources = b"<< /Font << /F1 3 0 R >> >>"
        if "image" in spec:
            number += 1
            image_number = number
            page_bodies.append(image_object(image_number, BODY_WIDTH, BODY_HEIGHT,
                                            spec["image"]))
            resources = (b"<< /Font << /F1 3 0 R >> /XObject << /Im0 "
                         + str(image_number).encode("ascii") + b" 0 R >> >>")
        kids.append(str(page_number).encode("ascii") + b" 0 R")
        page_bodies.append(PdfObject(
            page_number,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents "
            + str(content_number).encode("ascii") + b" 0 R /Resources " + resources + b" >>",
        ))
    objects = [
        PdfObject(1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        PdfObject(2, b"<< /Type /Pages /Kids [" + b" ".join(kids) + b"] /Count "
                  + str(len(page_specs)).encode("ascii") + b" >>"),
        PdfObject(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
        *page_bodies,
    ]
    return build_pdf(objects)


def _page_body(page_text: str) -> str:
    """The page body to render, with the printed-page line and Markdown markers removed.

    The synth page's first line (`Page N of 4 - <sid>`) is drawn as the printed header
    instead, and `##` headings are Markdown structure a scanned paper would not carry: the
    question id stays, the decoration goes.
    """
    lines = [line for line in page_text.split("\n") if line.strip()]
    if lines and lines[0].lower().startswith("page "):
        lines = lines[1:]
    return "\n".join(line.removeprefix("## ") for line in lines)


def scan_set() -> tuple[ScanSubmission, ...]:
    """`F-SCAN` — four scanned papers: legible handwriting, two marginal, one mixed format.

    SC-01 (legible), SC-02 and SC-03 (marginal) are wholly handwritten scans; SC-04 is the
    mixed-format paper — one typed page, three handwritten ones — so the corpus exercises both
    a typed text layer and pixels-only pages in one submission. Abilities are assigned rather
    than drawn (`§4.6`, and the same reasoning `synth.frozen_set` states): a four-member corpus
    cannot span the range by luck, and #133's set needs the media classes at known scores.
    """
    rng = random.Random(SCAN_SEED)
    out: list[ScanSubmission] = []
    for index, (sid, media_kind, legibility, ability) in enumerate(
            (("SC-01", hand.REAL_MEDIA_KIND, "legible", 0.9),
             ("SC-02", hand.REAL_MEDIA_KIND, "marginal", 0.55),
             ("SC-03", hand.REAL_MEDIA_KIND, "marginal", 0.15),
             ("SC-04", hand.MIXED_FORMAT_MEDIA_KIND, "legible", 0.75)), start=1):
        work = synth.generate(sid, f"H-{index:04d}", ability, rng)
        page_specs: list[dict] = []
        for page_no, page in enumerate(work.pages, start=1):
            body = _page_body(page)
            if sid == "SC-04" and page_no == 1:
                page_specs.append({"typed": _wrap(body, 85)})
            else:
                page_specs.append({"image": render_hand_page(body, legibility=legibility,
                                                             rng=rng)})
        out.append(ScanSubmission(
            submission_id=sid,
            student_ref=f"H-{index:04d}",
            bands=dict(work.bands),
            media_kind=media_kind,
            legibility=legibility,
            pdf=_submission_pdf(sid, f"H-{index:04d}", page_specs),
        ))
    return tuple(out)