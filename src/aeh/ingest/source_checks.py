"""The checks on each source file: sanitization, raster limits and the wall-clock deadline."""

from __future__ import annotations

import time
from typing import Sequence

from .settings import (
    _configured_dpi,
    _configured_resolution_floor,
    DEFAULT_MAX_DECOMPRESSED_BYTES,
    DEFAULT_MAX_EMBEDDED_OBJECTS,
    DEFAULT_MAX_FILE_SECONDS,
    DEFAULT_MAX_IMAGE_PIXELS,
    DEFAULT_MAX_PAGES,
    DEFAULT_STRIP_ACTIVE_CONTENT,
    MAX_DECOMPRESSED_BYTES_ENV,
    MAX_EMBEDDED_OBJECTS_ENV,
    MAX_FILE_SECONDS_ENV,
    MAX_IMAGE_PIXELS_ENV,
    MAX_PAGES_ENV,
    RESOLUTION_FLOOR_ENV,
    STRIP_ACTIVE_CONTENT_ENV,
)
from .errors import IngestError, IngestSanitizeError
from .rasterizer import PageImage
from .sanitizer import SanitizeResult


class SourceChecksMixin:
    """Sanitizes each source file and checks the rasters against the limits."""

    # -- the sanitize-and-bound stage (#42: FR-INGEST-33/34) ---------------------------------------

    def _sanitize_source(self, blob_hash: str, pdf_bytes: bytes, *,
                         pages_used: int, deadline: float) -> SanitizeResult:
        """Sanitize one source PDF before anything is rasterized (FR-INGEST-33, FR-INGEST-34):
        remove active content, then check the limits that can be checked before allocating memory:
        the page limit against the page count (including this document's running total) and the
        pixel limit against each page's expected raster size and each embedded image's declared
        size.

        Every failure is a refusal (`NFR-INGEST-08`): a sanitizer exception of any
        kind, unremovable active content, or a crossed bound raises
        `IngestSanitizeError` — quarantine in the submission path, the teacher
        surfacing in the setup-artifact path (`FR-INGEST-32`). The guard is
        fail-closed at EVERY bound-check site, the post-sanitize evaluations
        included: a fault injected there resolves to the declared refusal on
        both paths, never to a foreign exception or to processing (#231,
        closing the note-level disclosure PR #209 recorded against SEC-07).
        The wall-clock ceiling rides in as `deadline` (per source file, checked
        at the decode boundaries); the byte and object ceilings are enforced
        inside the sanitizer's walk, mid-stream."""
        strip = self._configured_bool(STRIP_ACTIVE_CONTENT_ENV,
                                      DEFAULT_STRIP_ACTIVE_CONTENT)
        try:
            result = self._sanitizer.sanitize(
                pdf_bytes, strip=strip,
                max_decompressed_bytes=self._configured_int(
                    MAX_DECOMPRESSED_BYTES_ENV, DEFAULT_MAX_DECOMPRESSED_BYTES),
                max_embedded_objects=self._configured_int(
                    MAX_EMBEDDED_OBJECTS_ENV, DEFAULT_MAX_EMBEDDED_OBJECTS),
                deadline=deadline)
        except IngestError:
            raise  # a declared refusal carries its own reason and type
        except Exception as error:  # noqa: BLE001 -- NFR-INGEST-08's letter:
            # ANY exception inside the sanitizer — declared or not, a fault-
            # injected one included — resolves to refusal, never to processing
            # (review B2: the docstring promised the wrapping; this is it).
            raise IngestSanitizeError(
                f"source blob {blob_hash[:12]} could not be sanitized: "
                f"{error!r}") from error
        try:
            if result.unremovable:
                raise IngestSanitizeError(
                    f"source blob {blob_hash[:12]} carries active content that "
                    f"cannot be removed ({', '.join(result.unremovable)}): "
                    "quarantined, never transcribed (FR-INGEST-33).")
            if result.bounds_crossed:
                raise IngestSanitizeError(
                    f"source blob {blob_hash[:12]} crossed a resource ceiling "
                    f"({', '.join(result.bounds_crossed)}): quarantined rather "
                    "than allocated for (FR-INGEST-34).")
            max_pages = self._configured_int(MAX_PAGES_ENV, DEFAULT_MAX_PAGES)
            if result.page_count is not None \
                    and pages_used + result.page_count > max_pages:
                raise IngestSanitizeError(
                    f"source blob {blob_hash[:12]} would take the document to "
                    f"{pages_used + result.page_count} pages, over the "
                    f"{max_pages}-page ceiling: quarantined rather than "
                    "rasterized (FR-INGEST-34).")
            max_pixels = self._configured_int(MAX_IMAGE_PIXELS_ENV,
                                              DEFAULT_MAX_IMAGE_PIXELS)
            dpi = _configured_dpi()
            oversized = [
                index + 1
                for index, (width_pt, height_pt) in enumerate(result.page_sizes_pt)
                if width_pt * dpi / 72.0 * (height_pt * dpi / 72.0) > max_pixels
            ]
            if oversized or result.max_declared_image_px > max_pixels:
                raise IngestSanitizeError(
                    f"source blob {blob_hash[:12]} carries an image over the "
                    f"{max_pixels}-pixel ceiling (pages {oversized}, largest "
                    f"declared image {result.max_declared_image_px}px): "
                    "quarantined before any render allocates for it "
                    "(FR-INGEST-34).")
        except IngestError:
            raise  # a declared refusal carries its own reason and type
        except Exception as error:  # noqa: BLE001 -- NFR-INGEST-08's letter:
            # ANY fault inside a post-sanitize bound evaluation — a fault-
            # injected one included — fails closed to the declared refusal.
            # The submission path's V0 loop already caught everything; this is
            # the same guard for the setup path, where the refusal raises to
            # the uploading teacher instead of quarantining (#231, closing the
            # note-level disclosure PR #209 recorded against SEC-07).
            raise IngestSanitizeError(
                f"source blob {blob_hash[:12]} failed closed in a post-sanitize "
                f"bound evaluation: {error!r} (NFR-INGEST-08).") from error
        return result

    def _check_rasters(self, blob_hash: str, pages: Sequence[PageImage]) -> None:
        """Check the actual rasters against the pixel limit and the resolution floor, as a second
        check after the size estimates, so a rasterizer that misreported sizes is caught before a
        model call is spent. The floor (`HARNESS_INGEST_RESOLUTION_FLOOR`, FR-INGEST-21)
        quarantines a page whose raster is too small in either dimension. Any fault here ends in
        the declared refusal, never in processing (NFR-INGEST-08)."""
        try:
            max_pixels = self._configured_int(MAX_IMAGE_PIXELS_ENV,
                                              DEFAULT_MAX_IMAGE_PIXELS)
            floor = _configured_resolution_floor()
            for page in pages:
                if page.width_px * page.height_px > max_pixels:
                    raise IngestSanitizeError(
                        f"source blob {blob_hash[:12]} page {page.page_no} rasterized "
                        f"to {page.width_px}x{page.height_px}, over the {max_pixels}-"
                        "pixel ceiling (FR-INGEST-34).")
                if min(page.width_px, page.height_px) < floor:
                    raise IngestSanitizeError(
                        f"source blob {blob_hash[:12]} page {page.page_no} rasterized "
                        f"to {page.width_px}x{page.height_px}px, below the profile's "
                        f"{floor}px resolution floor ({RESOLUTION_FLOOR_ENV}): an "
                        "artifact below the floor cannot carry a legible "
                        "transcription and quarantines as unreadable (FR-INGEST-21).")
        except IngestError:
            raise  # a declared refusal carries its own reason and type
        except Exception as error:  # noqa: BLE001 -- NFR-INGEST-08's letter
            raise IngestSanitizeError(
                f"source blob {blob_hash[:12]} failed closed at the raster "
                f"pixel-bound check: {error!r} (NFR-INGEST-08).") from error

    def _file_deadline(self, blob_hash: str) -> float:
        """The time limit for processing one source file: now plus `MAX_FILE_SECONDS`
        (FR-INGEST-34). A fault while reading the limit ends in the declared refusal
        (NFR-INGEST-08); a malformed limit value raises its own `IngestError`."""
        try:
            return time.monotonic() + self._configured_seconds(
                MAX_FILE_SECONDS_ENV, DEFAULT_MAX_FILE_SECONDS)
        except IngestError:
            raise  # a declared refusal carries its own reason and type
        except Exception as error:  # noqa: BLE001 -- NFR-INGEST-08's letter
            raise IngestSanitizeError(
                f"source blob {blob_hash[:12]} failed closed at the wall-clock "
                f"ceiling read: {error!r} (NFR-INGEST-08).") from error

    def _refuse_past_deadline(self, blob_hash: str, deadline: float,
                              phase: str) -> None:
        """Refuse the file once its time limit has passed (FR-INGEST-34); a fault while checking
        also ends in refusal (NFR-INGEST-08). For a setup document the teacher sees the refusal,
        since there is no operator queue for setup files (FR-INGEST-32)."""
        try:
            exceeded = time.monotonic() >= deadline
        except IngestError:
            raise  # a declared refusal carries its own reason and type
        except Exception as error:  # noqa: BLE001 -- NFR-INGEST-08's letter
            raise IngestSanitizeError(
                f"source blob {blob_hash[:12]} failed closed at the wall-clock "
                f"boundary read: {error!r} (NFR-INGEST-08).") from error
        if exceeded:
            raise IngestSanitizeError(
                f"source blob {blob_hash[:12]} exceeded the wall-clock ceiling "
                f"{phase} (FR-INGEST-34).")
