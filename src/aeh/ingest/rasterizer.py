"""Turning a PDF page (or a crop of it) into an image: the seam and its pypdfium2 version."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .errors import IngestError


# --- the rasterizer seam -------------------------------------------------------------------------


@dataclass(frozen=True)
class PageImage:
    """One rendered page: PNG bytes, its 1-based page number in the source file, and its size in
    pixels."""

    page_no: int
    png: bytes
    width_px: int
    height_px: int


class Rasterizer:
    """Turns PDF pages into images: the one place a PDF is decoded.

    `FR-INGEST-01` makes this module the sole gateway — the seam exists so the rasterizer
    is a dependency like the model boundary, with a deterministic double for tests and a
    real implementation for the acceptance run."""

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> Sequence[PageImage]:
        """Render every page of `pdf_bytes` at `dpi`. Page numbers start at 1."""
        raise NotImplementedError

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:
        """A box `(x, y, w, h)`, in the pixel space of `dpi`, cut from page `page_no` (1-based) as
        PNG bytes (FR-INGEST-13). A box outside the page is refused, never clamped."""
        raise NotImplementedError

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        """The page's embedded text, or "" when it has none (FR-INGEST-03).

        Extracted IN ADDITION to transcription, never instead: the layer is what the
        divergence check compares against the transcript. Default "" — a rasterizer
        that cannot read text layers reports none, and the divergence columns then
        honestly say zero pages carried one."""
        return ""


class PdfiumRasterizer(Rasterizer):
    """The live rasterizer, using `pypdfium2`. The library is imported only when first used, so the
    fast test tier does not need it."""

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> Sequence[PageImage]:
        try:
            import pypdfium2 as pdfium  # noqa: PLC0415 -- the lazy import IS the seam
        except ImportError as error:  # pragma: no cover - acceptance-run only
            raise IngestError(
                "the live rasterizer needs the pypdfium2 package; the fast tier uses "
                "a scripted Rasterizer double instead. It is a standard dependency: "
                "reinstall the system with `pip install .`."
            ) from error
        pdf = pdfium.PdfDocument(pdf_bytes)
        try:
            scale = dpi / 72.0
            pages = []
            for index in range(len(pdf)):
                page = pdf[index]
                bitmap = page.render(scale=scale)
                pil_image = bitmap.to_pil()
                import io

                buffer = io.BytesIO()
                pil_image.save(buffer, format="PNG")
                pages.append(PageImage(
                    page_no=index + 1, png=buffer.getvalue(),
                    width_px=pil_image.width, height_px=pil_image.height,
                ))
            return pages
        finally:
            pdf.close()

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        try:
            import pypdfium2 as pdfium  # noqa: PLC0415 -- the lazy import IS the seam
        except ImportError as error:  # pragma: no cover - acceptance-run only
            raise IngestError(
                "the live rasterizer needs the pypdfium2 package; the fast tier uses "
                "a scripted Rasterizer double instead."
            ) from error
        pdf = pdfium.PdfDocument(pdf_bytes)
        try:
            text_page = pdf[page_no - 1].get_textpage()
            return text_page.get_text_range()
        finally:
            pdf.close()

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:
        """An image crop of a page as PNG bytes (FR-INGEST-13): the box `(x, y, w, h)` in the pixel
        space of the page rendered at `dpi`. `page_no` is 1-based.

        A box that reaches outside the page — and a negative, degenerate or
        malformed one — is REFUSED, never clamped: a clamped crop would resolve
        a `described_graphic`'s `crop_ref` to an image other than the one its
        description described, exactly the mismatch `FR-INGEST-13`'s "resolving"
        forbids. The design is silent on the out-of-bounds case; this refusal
        (recorded on the issue) is the interpretation."""
        try:
            import pypdfium2 as pdfium  # noqa: PLC0415 -- the lazy import IS the seam
        except ImportError as error:  # pragma: no cover - acceptance-run only
            raise IngestError(
                "the live rasterizer needs the pypdfium2 package; the fast tier uses "
                "a scripted Rasterizer double instead. It is a standard dependency: "
                "reinstall the system with `pip install .`."
            ) from error
        x, y, width, height = _validated_crop_box(box)
        if page_no < 1:
            raise IngestError(
                f"crop page_no {page_no} is not 1-based; the source page "
                "numbers start at 1.")
        pdf = pdfium.PdfDocument(pdf_bytes)
        try:
            if page_no > len(pdf):
                raise IngestError(
                    f"crop page_no {page_no} is out of bounds: the source has "
                    f"{len(pdf)} page(s); the crop is refused, not clamped.")
            page = pdf[page_no - 1]
            bitmap = page.render(scale=dpi / 72.0)
            pil_image = bitmap.to_pil()
        finally:
            pdf.close()
        if x + width > pil_image.width or y + height > pil_image.height:
            raise IngestError(
                f"crop box {box!r} is out of bounds for page {page_no} at "
                f"{dpi} DPI ({pil_image.width}x{pil_image.height}px raster): "
                "the crop is refused, not clamped — a clamped crop would not "
                "be the image the description described (FR-INGEST-13).")
        import io

        buffer = io.BytesIO()
        pil_image.crop((x, y, x + width, y + height)).save(buffer, format="PNG")
        return buffer.getvalue()


def _validated_crop_box(box) -> tuple[int, int, int, int]:
    """Check a crop box before rendering: exactly four integers, a non-negative origin, and
    positive width and height. Anything else raises `IngestError` rather than being clamped or
    guessed."""
    if not isinstance(box, (tuple, list)) or len(box) != 4:
        raise IngestError(
            f"crop box {box!r} is not an (x, y, w, h) four-tuple; the crop is "
            "refused.")
    if not all(isinstance(value, int) and not isinstance(value, bool)
               for value in box):
        raise IngestError(
            f"crop box {box!r} is not four integers; the crop is refused.")
    x, y, width, height = box
    if x < 0 or y < 0:
        raise IngestError(
            f"crop box {box!r} has a negative origin; the crop is refused, "
            "not clamped.")
    if width <= 0 or height <= 0:
        raise IngestError(
            f"crop box {box!r} is degenerate (width and height must be "
            "positive); the crop is refused.")
    return x, y, width, height
