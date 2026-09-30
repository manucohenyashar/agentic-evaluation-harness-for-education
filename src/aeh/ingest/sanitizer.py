"""Neutralizing and bounding a source PDF before it is rasterized: the seam and its pypdf version."""

from __future__ import annotations

import io
import time
import zlib
from dataclasses import dataclass
from typing import Any

from .errors import IngestError, IngestSanitizeError


# --- the sanitizer seam (#42: FR-INGEST-33 / FR-INGEST-34) ----------------------------------------


#: The active and external-reference action types (`FR-INGEST-33`'s list), keyed by
#: the PDF action's `/S` value, valued by the construct class a finding names. A
#: dictionary whose `/S` is any of these IS the construct — wherever it hides (an
#: annotation's `/A`, the catalog's `/OpenAction`, a name-tree destination, an
#: incremental update's new objects, inside an object stream): the graph walk from
#: the trailer reaches all of them, which is the structural answer to the
#: TC-INGEST-33 variants.
_ACTION_CONSTRUCTS: dict[str, str] = {
    "/JavaScript": "javascript",
    "/Launch": "launch",
    "/URI": "uri",
    "/GoToR": "goto_r",
    "/GoToE": "embedded_file",
    "/SubmitForm": "submit_form",
}


@dataclass(frozen=True)
class SanitizeResult:
    """What the sanitizer found and did for one source PDF.

    `pdf_bytes` is the copy rasterization is allowed to read — the original when
    nothing needed removing, the rewritten document otherwise. `neutralized` names
    the construct classes found and removed; `unremovable` names those detected and
    NOT removed, which the gateway refuses on. `bounds_crossed` names the ceilings
    the artifact crossed mid-walk (`FR-INGEST-34`), after which the walk stopped —
    `decompressed_bytes` is the total measured up to the stop, so a bomb is refused
    without ever being fully decompressed. The structural observations
    (`page_count`, `page_sizes_pt`, `max_declared_image_px`) are what the gateway
    checks the page, pixel and object ceilings against BEFORE rendering."""

    pdf_bytes: bytes
    neutralized: tuple[str, ...] = ()
    unremovable: tuple[str, ...] = ()
    bounds_crossed: tuple[str, ...] = ()
    decompressed_bytes: int = 0
    page_count: int | None = None
    page_sizes_pt: tuple[tuple[float, float], ...] = ()
    max_declared_image_px: int = 0


class PdfSanitizer:
    """Inspects and rewrites a source PDF before it is rasterized: removes active content and
    enforces size limits.

    `FR-INGEST-33` makes sanitization a precondition of rasterization — the seam
    exists so that, like the rasterizer and the model boundary, it is a dependency
    with a deterministic double for tests and a real implementation for the
    acceptance run. A gateway cannot even be constructed without naming one."""

    def sanitize(
        self, pdf_bytes: bytes, *, strip: bool,
        max_decompressed_bytes: int | None,
        max_embedded_objects: int | None, deadline: float | None,
    ) -> SanitizeResult:
        """Inspect `pdf_bytes`, remove active content when `strip=True`, and report what was found
        within the given limits. It may raise anything; the gateway turns every failure into a
        refusal (NFR-INGEST-08)."""
        raise NotImplementedError


class _WalkAborted(Exception):
    """A limit was crossed during the object walk (FR-INGEST-34). The walk stops at once, with
    nothing more visited or decompressed, and what was seen so far goes to the caller as evidence
    for the refusal."""


def _chunked_flate_size(raw: bytes, budget: int) -> int:
    """The decompressed size of a Flate stream, measured in bounded chunks.

    Returns the running total — which may exceed `budget`, but only after the
    measurement STOPPED absorbing (the caller compares and refuses): a bomb is
    sized at most 64KiB past the line it crossed, never fully decompressed (the
    requirement's own acceptance form). Multi-member streams (concatenated zlib
    data) keep being measured until the input is exhausted or the budget is
    crossed."""
    total = 0

    def absorb(member: "zlib._Decompress", feed: bytes) -> bool:
        """Decompress one 64KiB slice, draining what max_length held back.
        False once the budget is crossed."""
        nonlocal total
        piece = member.decompress(feed, 65536)
        total += len(piece)
        if total > budget:
            return False
        while member.unconsumed_tail:
            piece = member.decompress(member.unconsumed_tail, 65536)
            total += len(piece)
            if total > budget:
                return False
        return True

    member = zlib.decompressobj()
    offset = 0
    while True:
        chunk = raw[offset:offset + 65536]
        offset += len(chunk)
        if not absorb(member, chunk):
            return total  # crossed: the count so far, then stop
        if offset < len(raw):
            continue
        if not member.unused_data:
            break  # the input is exhausted and it was one member
        raw = member.unused_data  # a concatenated second member follows
        member = zlib.decompressobj()
        offset = 0
    return total


class PypdfSanitizer(PdfSanitizer):
    """The live sanitizer, using `pypdf`. The library is imported only when first used, so the fast
    test tier does not need it.

    Three passes, in order: a bounded MEASUREMENT walk of the original (detect the
    constructs, size the streams chunk-wise, count the objects, watch the clock) —
    a bound crossed here stops the walk and refuses the artifact before anything
    is allocated for it; then the STRIP (mutate the reader's object graph, clone it
    out through `PdfWriter`); then a VERIFY re-parse of the rewritten bytes, whose
    finding of any surviving construct reads as `unremovable` rather than as
    success — "neutralized" is an asserted property, never a hope."""

    _CHUNK = 65536

    @staticmethod
    def _module() -> Any:
        """The `pypdf` module, imported on first use."""
        import pypdf  # noqa: PLC0415 -- the lazy import IS the seam
        return pypdf

    def sanitize(
        self, pdf_bytes: bytes, *, strip: bool,
        max_decompressed_bytes: int | None,
        max_embedded_objects: int | None, deadline: float | None,
    ) -> SanitizeResult:
        try:
            import pypdf  # noqa: PLC0415 -- the lazy import IS the seam
        except ImportError as error:  # pragma: no cover - acceptance-run only
            raise IngestError(
                "the live sanitizer needs the pypdf package; the fast tier uses a "
                "scripted PdfSanitizer double instead (the dependency is declared "
                "in requirements-dev.txt)."
            ) from error

        reader = self._open(pypdf, pdf_bytes)
        measured = self._walk(reader, pypdf, measure_streams=True,
                              max_decompressed_bytes=max_decompressed_bytes,
                              max_embedded_objects=max_embedded_objects,
                              deadline=deadline)
        if measured["bounds_crossed"]:
            # A ceiling was crossed mid-walk: the artifact is refused without
            # being fully walked, let alone rewritten (FR-INGEST-34's "quarantine
            # rather than being allocated for"). No strip happens past a crossed
            # bound — stripping would be processing the artifact.
            return SanitizeResult(
                pdf_bytes=pdf_bytes,
                bounds_crossed=measured["bounds_crossed"],
                decompressed_bytes=measured["decompressed_bytes"],
                page_count=measured["page_count"],
                page_sizes_pt=measured["page_sizes_pt"],
                max_declared_image_px=measured["max_declared_image_px"],
            )
        if not measured["constructs"]:
            # Nothing active: the sanitized copy of a clean PDF is itself — no
            # gratuitous re-serialization of a well-formed document.
            return self._result(pdf_bytes, measured)
        if not strip:
            # Declared reading of the knob (module constants above): strip=false
            # means refuse, never process. Any detected construct is then, by
            # definition, one that cannot be removed in this configuration.
            return SanitizeResult(
                pdf_bytes=pdf_bytes, unremovable=tuple(sorted(measured["constructs"])),
                decompressed_bytes=measured["decompressed_bytes"],
                page_count=measured["page_count"],
                page_sizes_pt=measured["page_sizes_pt"],
                max_declared_image_px=measured["max_declared_image_px"],
            )

        self._strip(reader, pypdf)
        sanitized = self._serialize(reader, pypdf)
        verified = self._walk(self._open(pypdf, sanitized), pypdf,
                              measure_streams=False, max_decompressed_bytes=None,
                              max_embedded_objects=None, deadline=None)
        if verified["constructs"]:
            # The rewrite did not take: the construct survives in the sanitized
            # copy, so the honest outcome is "cannot be removed" (FR-INGEST-33),
            # and the gateway quarantines instead of rasterizing.
            return SanitizeResult(
                pdf_bytes=pdf_bytes,
                unremovable=tuple(sorted(verified["constructs"])),
                decompressed_bytes=measured["decompressed_bytes"],
                page_count=measured["page_count"],
                page_sizes_pt=measured["page_sizes_pt"],
                max_declared_image_px=measured["max_declared_image_px"],
            )
        return SanitizeResult(
            pdf_bytes=sanitized,
            neutralized=tuple(sorted(measured["constructs"])),
            decompressed_bytes=measured["decompressed_bytes"],
            page_count=verified["page_count"],
            page_sizes_pt=verified["page_sizes_pt"],
            max_declared_image_px=measured["max_declared_image_px"],
        )

    # -- the passes -------------------------------------------------------------------------------

    def _open(self, pypdf: Any, pdf_bytes: bytes) -> Any:
        if not pdf_bytes.lstrip()[:5] == b"%PDF-":
            raise IngestSanitizeError(
                "the source does not carry a PDF header — it is not a PDF, and "
                "nothing about it can be sanitized.")
        try:
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            if reader.is_encrypted:
                # An encrypted file cannot be inspected, so it cannot be
                # sanitized — F-ADV-PDF's encrypted fixture quarantines here.
                raise IngestSanitizeError(
                    "the source is encrypted; an unreadable artifact cannot be "
                    "sanitized, so it is refused (FR-INGEST-33).")
            return reader
        except IngestSanitizeError:
            raise
        except Exception as error:
            raise IngestSanitizeError(
                f"the source could not be parsed for sanitization: {error}") from error

    def _walk(
        self, reader: Any, pypdf: Any, *, measure_streams: bool,
        max_decompressed_bytes: int | None, max_embedded_objects: int | None,
        deadline: float | None,
    ) -> dict:
        """One bounded walk over every object reachable from the PDF's trailer.

        Detection is structural: any dictionary carrying `/AA`, `/OpenAction`,
        `/JS`, `/XFA`, `/EF`, an action dictionary whose `/S` is one of the
        construct types, or a name tree naming JavaScript or embedded files. The
        same walk measures: unique indirect objects visited (the embedded-object
        ceiling), stream decompression chunk-wise (the byte ceiling), and the
        clock. With `measure_streams=False` (the verify pass) streams are left
        sealed — construct detection never needs to decompress one."""
        constructs: set[str] = set()
        seen: set[tuple[int, int]] = set()
        decompressed = 0
        bounds_crossed: list[str] = []
        max_image_px = 0

        def visit(value: Any) -> None:
            nonlocal decompressed, max_image_px
            if deadline is not None and time.monotonic() >= deadline:
                bounds_crossed.append("wall_clock")
                raise _WalkAborted
            if isinstance(value, pypdf.generic.IndirectObject):
                key = (value.idnum, value.generation)
                if key in seen:
                    return
                if max_embedded_objects is not None \
                        and len(seen) >= max_embedded_objects:
                    bounds_crossed.append("embedded_objects")
                    raise _WalkAborted
                seen.add(key)
                value = value.get_object()
            if isinstance(value, pypdf.generic.StreamObject):
                subtype = str(value.get("/Subtype", ""))
                if subtype == "/Image":
                    # Declared dimensions, read from the dictionary: a
                    # 60000×60000 image is refused from its header before
                    # anything decodes it (the FR's pixel bound, pre-allocation).
                    try:
                        max_image_px = max(max_image_px, int(value["/Width"])
                                           * int(value["/Height"]))
                    except (KeyError, TypeError, ValueError):
                        pass
                    return  # image streams are never decompressed by the walk
                if measure_streams:
                    remaining = (max_decompressed_bytes - decompressed
                                 if max_decompressed_bytes is not None else -1)
                    sized = self._measure_stream(value, remaining)
                    if sized is None:
                        # Unmeasurable without decoding: refused, not measured
                        # (review B3 — the declared filter-family rule).
                        bounds_crossed.append("decompressed_bytes")
                        raise _WalkAborted
                    decompressed += sized  # the partial count, if it crossed
                    if max_decompressed_bytes is not None \
                            and decompressed > max_decompressed_bytes:
                        bounds_crossed.append("decompressed_bytes")
                        raise _WalkAborted
                return
            if isinstance(value, pypdf.generic.DictionaryObject):
                constructs.update(self._detect(value))
            if isinstance(value, (pypdf.generic.DictionaryObject,
                                  pypdf.generic.ArrayObject)):
                children = (value.values() if isinstance(
                    value, pypdf.generic.DictionaryObject) else value)
                for child in list(children):
                    visit(child)

        try:
            visit(reader.trailer)
        except _WalkAborted:
            pass
        pages = self._page_facts(reader)
        return {"constructs": constructs, "seen": len(seen),
                "decompressed_bytes": decompressed,
                "bounds_crossed": tuple(bounds_crossed),
                "max_declared_image_px": max_image_px, **pages}

    def _detect(self, obj: Any) -> set[str]:
        """The kinds of active content one PDF dictionary contains (FR-INGEST-33)."""
        pypdf = self._module()
        found: set[str] = set()
        for key in ("/AA", "/OpenAction", "/JS", "/XFA", "/EF"):
            if key in obj:
                found.add({"AA": "aa", "OpenAction": "open_action",
                           "JS": "javascript", "XFA": "xfa",
                           "EF": "embedded_file"}[key[1:]])
        action = obj.get("/S")
        if action is not None:
            construct = _ACTION_CONSTRUCTS.get(str(action))
            if construct:
                found.add(construct)
        if str(obj.get("/Subtype", "")) == "/FileAttachment":
            found.add("embedded_file")
        names = obj.get("/Names")
        if isinstance(names, pypdf.generic.DictionaryObject):
            for tree, construct in (("/JavaScript", "javascript"),
                                    ("/EmbeddedFiles", "embedded_file")):
                if tree in names:
                    found.add(construct)
        return found

    def _measure_stream(self, stream: Any, budget: int) -> int | None:
        """A stream's decompressed size within `budget` (-1 means no limit), or None when it cannot
        be bounded without decoding it fully.

        Declared rule (review B3): exactly two families are measurable —
        UNFILTERED streams (the encoded bytes ARE the data; a plain `len`, no
        decode) and streams whose ENTIRE filter chain is FlateDecode (measured
        in bounded chunks that stop absorbing at the budget). Every other
        chain — LZW, RunLength, ASCII85, DCT outside an image, any compound
        chain — is UNMEASURABLE and returns None: the walk refuses the artifact
        rather than decoding past its ceiling. These are the standard filters,
        not exotic ones, and the alternative (decode, then count) is precisely
        the allocate-then-check shape the requirement forbids; NFR-INGEST-08
        makes the conservative outcome the default."""
        filter_value = stream.get("/Filter")
        filters = (list(filter_value) if isinstance(filter_value, list)
                   else [filter_value] if filter_value else [])
        if not filters:
            return len(self._encoded_bytes(stream))
        if len(filters) == 1 and str(filters[0]) in ("/FlateDecode", "/Fl"):
            raw = self._encoded_bytes(stream)
            try:
                return _chunked_flate_size(
                    raw, len(raw) if budget < 0 else budget)
            except zlib.error:
                return len(raw)
        return None

    @staticmethod
    def _encoded_bytes(stream: Any) -> bytes:
        """A stream's encoded bytes, without decoding them."""
        return stream.raw_data if hasattr(stream, "raw_data") else stream._data

    def _page_facts(self, reader: Any) -> dict:
        """The page count and each page's size in points, so raster limits can be checked before
        any raster is made (a page's raster size is `pt / 72 * dpi`)."""
        try:
            pages = list(reader.pages)
        except Exception as error:  # noqa: BLE001 -- an unreadable page tree is a refusal
            raise IngestSanitizeError(
                f"the page tree could not be read for the resource bounds: {error}"
            ) from error
        sizes: list[tuple[float, float]] = []
        for page in pages:
            try:
                box = page.mediabox
                sizes.append((float(box.width), float(box.height)))
            except Exception:  # noqa: BLE001 -- a page without a box contributes no size
                sizes.append((0.0, 0.0))
        return {"page_count": len(pages), "page_sizes_pt": tuple(sizes)}

    def _strip(self, reader: Any, pypdf: Any) -> None:
        """Remove the active content found by the walk, in place: the dictionary keys, name-tree
        entries and file-attachment annotations. A later pass checks the removal."""
        visited: set[tuple[int, int]] = set()

        def prune(value: Any) -> None:
            if isinstance(value, pypdf.generic.IndirectObject):
                key = (value.idnum, value.generation)
                if key in visited:
                    return
                visited.add(key)
                value = value.get_object()
            if isinstance(value, pypdf.generic.DictionaryObject):
                for key in ("/AA", "/OpenAction", "/JS", "/XFA", "/EF"):
                    if key in value:
                        del value[pypdf.generic.NameObject(key)]
                action = value.get("/A")
                if isinstance(action, pypdf.generic.IndirectObject):
                    action = action.get_object()
                if isinstance(action, pypdf.generic.DictionaryObject) \
                        and str(action.get("/S", "")) in _ACTION_CONSTRUCTS:
                    del value[pypdf.generic.NameObject("/A")]
                names = value.get("/Names")
                if isinstance(names, pypdf.generic.IndirectObject):
                    names = names.get_object()
                if isinstance(names, pypdf.generic.DictionaryObject):
                    for tree in ("/JavaScript", "/EmbeddedFiles"):
                        if tree in names:
                            del names[pypdf.generic.NameObject(tree)]
                    dests = names.get("/Dests")
                    if isinstance(dests, pypdf.generic.IndirectObject):
                        dests = dests.get_object()
                    if isinstance(dests, pypdf.generic.DictionaryObject):
                        self._prune_dest_tree(dests, pypdf)
            if isinstance(value, (pypdf.generic.DictionaryObject,
                                  pypdf.generic.ArrayObject)):
                children = (list(value.values()) if isinstance(
                    value, pypdf.generic.DictionaryObject) else list(value))
                for child in children:
                    prune(child)

        prune(reader.trailer)
        for page in reader.pages:
            annots = page.get("/Annots")
            if isinstance(annots, pypdf.generic.IndirectObject):
                annots = annots.get_object()
            if not isinstance(annots, pypdf.generic.ArrayObject):
                continue
            kept = pypdf.generic.ArrayObject()
            for entry in annots:
                resolved = (entry.get_object() if isinstance(
                    entry, pypdf.generic.IndirectObject) else entry)
                if isinstance(resolved, pypdf.generic.DictionaryObject) \
                        and str(resolved.get("/Subtype", "")) == "/FileAttachment":
                    continue  # the embedded-file vector leaves with its annotation
                kept.append(entry)
            page[pypdf.generic.NameObject("/Annots")] = kept

    def _prune_dest_tree(self, node: Any, pypdf: Any) -> None:
        """Remove named destinations whose action points outside the document or runs something,
        because a `/Dests` tree can hide `/GoToR` and `/URI` actions just as annotations can."""
        kids = node.get("/Kids")
        if isinstance(kids, pypdf.generic.IndirectObject):
            kids = kids.get_object()
        if isinstance(kids, pypdf.generic.ArrayObject):
            for kid in list(kids):
                resolved = (kid.get_object() if isinstance(
                    kid, pypdf.generic.IndirectObject) else kid)
                if isinstance(resolved, pypdf.generic.DictionaryObject):
                    self._prune_dest_tree(resolved, pypdf)
            return
        flat = node.get("/Names")
        if not isinstance(flat, pypdf.generic.ArrayObject):
            return
        kept = pypdf.generic.ArrayObject()
        entries = list(flat)
        for index in range(0, len(entries) - 1, 2):
            target = entries[index + 1]
            if isinstance(target, pypdf.generic.IndirectObject):
                target = target.get_object()
            if isinstance(target, pypdf.generic.DictionaryObject) \
                    and str(target.get("/S", "")) in _ACTION_CONSTRUCTS:
                continue  # the named destination's action leaves with its entry
            kept.append(entries[index])
            kept.append(entries[index + 1])
        node[pypdf.generic.NameObject("/Names")] = kept

    def _serialize(self, reader: Any, pypdf: Any) -> bytes:
        buffer = io.BytesIO()
        try:
            writer = pypdf.PdfWriter(clone_from=reader)
            writer.write(buffer)
        except Exception as error:
            raise IngestSanitizeError(
                f"the sanitized copy could not be written: {error}") from error
        return buffer.getvalue()

    @staticmethod
    def _result(pdf_bytes: bytes, measured: dict) -> SanitizeResult:
        return SanitizeResult(
            pdf_bytes=pdf_bytes, neutralized=(),
            bounds_crossed=measured["bounds_crossed"],
            decompressed_bytes=measured["decompressed_bytes"],
            page_count=measured["page_count"],
            page_sizes_pt=measured["page_sizes_pt"],
            max_declared_image_px=measured["max_declared_image_px"],
        )
