"""Document intake: one normalization step from a teacher's file to `NormalizedDocument`
(FR-AUTHOR-24…28, ADR-46).

Every supported format — `.docx`, `.txt`, `.pdf` — is normalized here, in one step, into the
single in-memory representation `draft()` consumes (`CT-AUTHOR-21`). The step is pure and
deterministic (`CT-AUTHOR-22`): the same bytes produce the same `NormalizedDocument` on every
call, with no I/O beyond reading the source file and **no provider call of any kind** —
refusals (`CT-AUTHOR-23`) and warnings alike are decided by magic bytes and cheap local
checks. `.pdf` rides the same step while its externally visible behaviour stays FR-AUTHOR-01's
(`FR-AUTHOR-27`): `AuthoringService.draft` keeps extracting PDFs through `extraction.py` —
text layer, then the transcriber — and this module wraps the extracted pages into the
representation with a per-page lossless guard, so the quoted document text the reasoning
prompts carry (and therefore the recording keys) stay byte-identical.

What the step could not carry is said, per location, in `IntakeWarning`s — the honest account
the report's Documents section renders (`FR-AUTHOR-12`) and the console shows at upload.
Warnings quote at most a short anchor of surrounding text, never a wholesale passage
(`CT-AUTHOR-26`).

The intake surface (consumed by the console reads/actions tier and by the intake tests):

- `normalize_document(path, *, max_bytes=None) -> NormalizedDocument` — normalize one file,
  refusing per FR-AUTHOR-28's matrix.
- `normalize_documents(paths, *, max_bytes=None) -> tuple[NormalizedDocument, ...]` — the
  plural form, in input order.
- `check_document(path, *, max_bytes=None) -> None` — the refusal envelope alone (magic
  bytes, size, encoding of the name): the cheap pre-check the console runs at upload.
- `document_text(document) -> str` — the normalized blocks as one text, the projection the
  reasoning prompts quote.
- `normalized_from_authoring(document) -> NormalizedDocument` — wrap an extracted PDF
  (`extraction.AuthoringDocument`) into the representation.
- `log_intake(document) -> None` — the stage-level observability line the console's upload
  path can log the same way the draft flow does (seam 4).
"""

from __future__ import annotations

import codecs
import hashlib
import html as _html
import io
import logging
import re
import zipfile
from collections.abc import Sequence
from html.parser import HTMLParser
from pathlib import Path

from .errors import AuthoringInputError, DocumentRefusedError
from .extraction import AuthoringDocument
from .settings import resolve_doc_max_bytes
from .types import Block, IntakeStats, IntakeWarning, NormalizedDocument

LOGGER = logging.getLogger("aeh.author")

# -- FR-AUTHOR-28's refusal matrix, verbatim -------------------------------------------------
# Each sentence is the teacher-facing refusal for its row; `DocumentRefusedError.sentence`
# carries it exactly, and the error's text appends the file's name so a multi-file refusal
# says which file it was.

LEGACY_DOC_SENTENCE = (
    "This file was saved in an older Word format. Open it in Word and save it as .docx, "
    "then upload again."
)
MISMATCH_SENTENCE = (
    "This file isn't what its name says. Rename it to match what it actually is "
    "(.txt, .docx, or .pdf) and upload again."
)
PASSWORD_SENTENCE = (
    "This document is password-protected. Remove the password and upload it again."
)
NO_TEXT_SENTENCE = "We couldn't find any text in this file."
UNSUPPORTED_SENTENCE = (
    "We can read .docx, .txt and .pdf files. Save this as one of those and upload it again."
)

#: Outside the matrix: the file exists but could not be read (permissions, a lock held by
#: another program). The matrix's closest row ("no text") would claim we read the file and
#: found nothing, which is false — so this refusal says what actually happened instead.
UNREADABLE_SENTENCE = (
    "We couldn't read this file. Close it if it's open in another program, then upload "
    "it again."
)

#: The images-only-PDF arm of the empty row — a note, not a refusal: the FR-AUTHOR-01
#: transcriber path reads such pages at draft time.
SCANNED_PDF_SENTENCE = (
    "It looks like scanned pages only — we'll try to read them with the page reader."
)

_OLE_MAGIC = b"\xd0\xcf\x11\xe0"
_ZIP_MAGIC = b"PK\x03\x04"
_PDF_MAGIC = b"%PDF"
#: `.doc` is in the map so a legacy file reaches the OLE check (its matrix row) instead of
#: the unsupported-extension refusal; normalization itself never runs for one.
_SUFFIX_FORMATS = {".docx": "docx", ".doc": "doc", ".txt": "txt", ".pdf": "pdf"}

#: The warning bound of CT-AUTHOR-26: a warning quotes at most a short anchor of document
#: text — never a wholesale passage — and stays within this many characters overall.
WARNING_MAX_CHARS = 200
_ANCHOR_CHARS = 60


def _clip(text: str, limit: int) -> str:
    """`text` shortened to `limit` characters, honestly marked when shortened."""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _anchor(text: str) -> str:
    """A quoted anchor for a warning's location clause: `near '…'`, or '' when there is
    no surrounding text to name."""
    clipped = _clip(text, _ANCHOR_CHARS)
    return f" near '{clipped}'" if clipped else ""


def _bounded(message: str) -> str:
    """The final warning message, within `WARNING_MAX_CHARS` (`CT-AUTHOR-26`)."""
    if len(message) <= WARNING_MAX_CHARS:
        return message
    return message[: WARNING_MAX_CHARS - 1].rstrip() + "…"


# -- the envelope: refusals decided before any content is read (FR-AUTHOR-28) -----------------


def check_document(path: Path, *, max_bytes: int | None = None) -> None:
    """The refusal envelope alone: extension, size, emptiness, magic bytes. `None` when the
    file may proceed to normalization; `DocumentRefusedError` otherwise. No content is
    parsed and no provider is involved — the checks are magic bytes and the byte count
    (FR-AUTHOR-28's decision rule, `CT-AUTHOR-23`)."""
    _preflight(Path(path), resolve_doc_max_bytes(max_bytes))


def _preflight(path: Path, max_bytes: int) -> tuple[bytes, str]:
    """Read the file and decide its envelope. Returns `(data, source_format)`; raises the
    matrix's refusals. The suffix chooses the expected format, the magic bytes confirm it —
    a mismatch is refused whichever way it lies (a `.docx` that is really text, a renamed
    `.pdf`)."""
    suffix = path.suffix.lower()
    source_format = _SUFFIX_FORMATS.get(suffix)
    if source_format is None:
        raise DocumentRefusedError(
            UNSUPPORTED_SENTENCE, path.name,
            detail=f"unsupported extension {suffix!r}; expected one of .docx, .txt, .pdf")
    try:
        data = path.read_bytes()
    except OSError as error:
        raise DocumentRefusedError(
            UNREADABLE_SENTENCE, path.name,
            detail=f"the file could not be read: {type(error).__name__}: {error}") from error
    if not data:
        raise DocumentRefusedError(
            NO_TEXT_SENTENCE, path.name, detail="the file is empty (0 bytes)")
    if len(data) > max_bytes:
        raise DocumentRefusedError(
            _oversize_sentence(max_bytes), path.name,
            detail=f"the file is {len(data)} bytes; the limit is {max_bytes}")
    if data.startswith(_OLE_MAGIC):
        # Both a legacy `.doc` and Word's password-protected `.docx` are OLE compound
        # files; the encrypted ones carry an EncryptedPackage stream, so the stream's name
        # in the directory is what separates the two rows of the matrix. Only the full
        # stream name counts: the bare word "Encrypted" appears in ordinary document text
        # (stored UTF-16LE in a `.doc`), and a legacy document holding that word is not a
        # password-protected one. A password-protected legacy `.doc` — an encrypted
        # WordDocument stream, no EncryptedPackage — lands on the legacy row: it IS a
        # legacy `.doc`, and that row's next step is what unblocks it. The check runs
        # for every suffix: a legacy `.doc` renamed `.txt` is still a legacy `.doc`.
        encrypted_package = (b"E\x00n\x00c\x00r\x00y\x00p\x00t\x00e\x00d\x00"
                             b"P\x00a\x00c\x00k\x00a\x00g\x00e\x00")
        if encrypted_package in data or b"EncryptedPackage" in data:
            raise DocumentRefusedError(
                PASSWORD_SENTENCE, path.name,
                detail="an OLE compound file carrying an encrypted package")
        raise DocumentRefusedError(
            LEGACY_DOC_SENTENCE, path.name,
            detail="OLE compound-file magic D0CF11E0 (the legacy .doc container)")
    if source_format == "doc":
        # Not OLE, so it is not a legacy Word document at all — whatever it is, it is not
        # what its name says.
        raise DocumentRefusedError(
            MISMATCH_SENTENCE, path.name,
            detail=f"the bytes start with {data[:4].hex()}; a .doc is an OLE compound file")
    if source_format == "docx" and not data.startswith(_ZIP_MAGIC):
        raise DocumentRefusedError(
            MISMATCH_SENTENCE, path.name,
            detail=f"the bytes start with {data[:4].hex()}; a .docx is a zip archive")
    if source_format == "pdf" and not data.startswith(_PDF_MAGIC):
        raise DocumentRefusedError(
            MISMATCH_SENTENCE, path.name,
            detail=f"the bytes start with {data[:4].hex()}; a .pdf starts with %PDF")
    if source_format == "txt" and (data.startswith(_ZIP_MAGIC)
                                   or data.startswith(_PDF_MAGIC)):
        raise DocumentRefusedError(
            MISMATCH_SENTENCE, path.name,
            detail=f"the bytes start with {data[:4].hex()}; a .txt is plain text")
    return data, source_format


def _human_bytes(size: int) -> str:
    """A byte count in the units the refusal speaks: whole MB, else whole KB, else bytes."""
    if size % (1024 * 1024) == 0:
        return f"{size // (1024 * 1024)} MB"
    if size % 1024 == 0:
        return f"{size // 1024} KB"
    return f"{size} bytes"


def _oversize_sentence(max_bytes: int) -> str:
    """The oversize refusal with the *actual* limit named — the design's sentence at the
    default 10 MB, the same sentence in the knob's units when an operator lowered it."""
    return (f"This file is larger than {_human_bytes(max_bytes)}. Split it or remove "
            "pictures to get it under the limit.")


# -- the entry points ------------------------------------------------------------------------


def normalize_document(path: Path, *, max_bytes: int | None = None) -> NormalizedDocument:
    """One teacher file in, one `NormalizedDocument` out (`FR-AUTHOR-24`).

    Pure and deterministic (`CT-AUTHOR-22`): the same bytes produce the same document on
    every call, and the only I/O is reading the file. A file the matrix refuses raises
    `DocumentRefusedError` — before anything is parsed, and with no provider anywhere in
    the step (`CT-AUTHOR-23`). A `.docx` or `.txt` that normalizes to no text at all is
    refused too ("empty / no extractable text"); a `.pdf` whose pages have no text layer
    is *not* refused — it comes back with the scanned-pages note, because the draft's
    transcriber path (`FR-AUTHOR-01`) is exactly what reads such pages.
    """
    path = Path(path)
    limit = resolve_doc_max_bytes(max_bytes)
    data, source_format = _preflight(path, limit)
    if source_format == "docx":
        return _normalize_docx(path.name, data)
    if source_format == "txt":
        return _normalize_txt(path.name, data)
    assert source_format == "pdf"  # preflight refuses every other suffix
    return _normalize_pdf(path.name, data)


def log_intake(document: NormalizedDocument) -> None:
    """The intake trace (`FR-AUTHOR-19`'s discipline, applied to the new stage): one line
    per document saying what intake produced, and one per warning saying what was not
    carried. `draft()` calls it as its intake stage's observability; a console caller can
    log the same way after its own `normalize_document` calls."""
    LOGGER.info("intake: %s: %d block(s), %d warning(s)", document.source_name,
                document.stats.block_count, len(document.warnings))
    for warning in document.warnings:
        LOGGER.warning("intake: %s: %s", document.source_name, warning.message)


def normalize_documents(paths: Sequence[Path], *,
                        max_bytes: int | None = None) -> tuple[NormalizedDocument, ...]:
    """Every file in input order (`FR-AUTHOR-24`'s "any mix of sources"). The first refusal
    raises; nothing is normalized after it."""
    return tuple(normalize_document(path, max_bytes=max_bytes) for path in paths)


def document_text(document: NormalizedDocument) -> str:
    """The document's normalized content as one text: the blocks in order, image
    placeholders aside. This is the projection the reasoning prompts quote (`CT-AUTHOR-21`:
    drafting depends on the blocks and warnings, never on `source_format`) — and the
    fingerprint material FR-AUTHOR-23 matches review answers over."""
    return "\n\n".join(block.text for block in document.blocks
                       if block.kind != "image_ref" and block.text.strip())


def normalized_from_authoring(document: AuthoringDocument) -> NormalizedDocument:
    """Wrap an extracted PDF (`extraction.AuthoringDocument`) into the representation
    (`FR-AUTHOR-27`): the text the workflow already extracted, page by page, becomes
    blocks — headings inferred by the same heuristics the `.txt` path uses, under a
    per-page lossless guard.

    The guard is what keeps the PDF path's externally visible behaviour unchanged: if the
    page's inferred blocks would not project back to the page's exact text, the page comes
    through as a single paragraph carrying that text verbatim. The quoted document text —
    and with it the recording keys — stays byte-identical to the pre-intake path.
    """
    data = document.path.read_bytes()
    blocks: list[tuple[str, str, int | None]] = []
    warnings: list[IntakeWarning] = []
    for page in document.pages:
        if not page.text:
            continue
        page_blocks, page_warnings = _blocks_from_lines(
            page.text, tables=False, lists=False, warn_structure=False, guard=page.text)
        blocks.extend(page_blocks)
        warnings.extend(page_warnings)
    if not any(text for _, text, _ in blocks):
        warnings.append(IntakeWarning(
            code="image_not_carried", message=_bounded(SCANNED_PDF_SENTENCE), detail="no page yielded a text layer"))
    return _assemble(document.name, "pdf", data, blocks, warnings)


def _assemble(name: str, source_format: str, data: bytes,
              blocks: list[tuple[str, str, int | None]],
              warnings: list[IntakeWarning]) -> NormalizedDocument:
    """The representation's constructor side: ordinals, counts and the content fingerprint."""
    normalized_blocks = tuple(
        Block(kind=kind, text=text, ordinal=ordinal, level=level)
        for ordinal, (kind, text, level) in enumerate(blocks)
    )
    table_count = sum(1 for block in normalized_blocks if block.kind == "table")
    image_count = sum(1 for block in normalized_blocks if block.kind == "image_ref")
    word_count = sum(len(block.text.split()) for block in normalized_blocks
                     if block.kind != "image_ref")
    return NormalizedDocument(
        source_name=name,
        source_format=source_format,
        source_sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        blocks=normalized_blocks,
        warnings=tuple(warnings),
        stats=IntakeStats(word_count=word_count, block_count=len(normalized_blocks),
                          table_count=table_count, image_count=image_count),
    )


# -- the .docx path (FR-AUTHOR-25) ------------------------------------------------------------


def _normalize_docx(name: str, data: bytes) -> NormalizedDocument:
    """`.docx` through `mammoth` to semantic HTML, the HTML to blocks with the stdlib
    parser, and the package's own XML scanned for everything mammoth drops silently
    (text boxes, tracked deletions) or drops without a location (equations)."""
    xml_parts = _ooxml_parts(name, data)
    mammoth_data, broken_images = _strip_unreadable_images(data)
    try:
        import mammoth
    except ImportError as error:  # pragma: no cover - mammoth is a project dependency
        raise AuthoringInputError(
            f"mammoth is not available; .docx documents cannot be read ({error})."
        ) from error
    try:
        converted = mammoth.convert_to_html(io.BytesIO(mammoth_data))
    except Exception as error:  # noqa: BLE001 - any conversion failure refuses the file
        lowered = str(error).lower()
        if "encrypt" in lowered and "password" in lowered:
            # An encrypted entry zipfile only admits at read time (the flag alone can
            # hide): the password row of the matrix, straight from the zip layer.
            raise DocumentRefusedError(
                PASSWORD_SENTENCE, name, detail=str(error)) from error
        raise DocumentRefusedError(
            NO_TEXT_SENTENCE, name,
            detail=f"mammoth could not convert the document: "
                   f"{type(error).__name__}: {error}") from error
    parser = _DocxHTMLParser()
    parser.feed(converted.value)
    parser.close()
    blocks = parser.blocks
    warnings = _docx_warnings(name, parser, _scan_ooxml(xml_parts), converted.messages,
                              broken_images=broken_images)
    if not any(text for kind, text, _ in blocks if kind != "image_ref"):
        raise DocumentRefusedError(
            NO_TEXT_SENTENCE, name,
            detail="the document normalizes to no text (no paragraphs, no tables)")
    return _assemble(name, "docx", data, blocks, warnings)


def _ooxml_parts(name: str, data: bytes) -> list[tuple[str, str]]:
    """The document's OOXML parts as decoded text: the body plus any headers and footers,
    where pictures and text also hide. The zip layer is also where a password-protected
    document fails (`FR-AUTHOR-25`)."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise DocumentRefusedError(
            NO_TEXT_SENTENCE, name,
            detail=f"not a readable .docx archive: {error}") from error
    with archive:
        wanted = re.compile(r"^word/(?:document|header\d+|footer\d+)\.xml$")
        parts: list[tuple[str, str]] = []
        if "word/document.xml" not in archive.namelist():
            raise DocumentRefusedError(
                MISMATCH_SENTENCE, name,
                detail="a zip archive without word/document.xml — not a Word document")
        if any(info.flag_bits & 0x1 for info in archive.infolist()):
            raise DocumentRefusedError(
                PASSWORD_SENTENCE, name, detail="the zip entries are encrypted")
        for info in archive.infolist():
            if not wanted.match(info.filename):
                continue
            try:
                raw = archive.read(info)
            except RuntimeError as error:
                if "encrypt" in str(error).lower():
                    raise DocumentRefusedError(
                        PASSWORD_SENTENCE, name, detail=str(error)) from error
                raise DocumentRefusedError(
                    NO_TEXT_SENTENCE, name,
                    detail=f"{info.filename} could not be read: {error}") from error
            parts.append((info.filename, raw.decode("utf-8", errors="replace")))
    return parts


#: A picture's OOXML containers, outermost first: `w:object` may hold a `w:pict`, so the
#: backreference keeps a single match per container and the inner one goes with it.
_UNREADABLE_CONTAINER = re.compile(
    r"<w:(object|drawing|pict)(?:\s[^>]*)?>.*?</w:\1>", re.S)


def _strip_unreadable_images(data: bytes) -> tuple[bytes, int]:
    """`document.xml` with its unreadable pictures removed, and how many went.

    mammoth resolves a picture's relationship eagerly, and a relationship the document's
    parts do not declare raises a bare `KeyError` out of the conversion — refusing a
    document that has perfectly good text under the wrong matrix row ("no text"). Word
    itself tolerates such files (it shows a placeholder), so intake mirrors that: the
    unreadable picture is removed before conversion and accounted as an
    `image_not_carried` warning instead. Everything but `document.xml` is copied through
    byte for byte; the sanitized bytes feed mammoth only — the `NormalizedDocument` still
    fingerprints the file the teacher gave us. A hyperlink pointing at a missing
    relationship loses only its `r:id` (the text stays, unlinked): mammoth raises there
    too, and the link target is not worth a refusal.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:  # not reachable after _ooxml_parts; stay inert regardless
        return data, 0
    with archive:
        document_xml = archive.read("word/document.xml").decode("utf-8", "replace")
        try:
            rels = archive.read("word/_rels/document.xml.rels").decode("utf-8", "replace")
        except KeyError:
            rels = ""
        declared = set(re.findall(r'Id="(rId\d+)"', rels))
        referenced = set(re.findall(r'\br:(?:embed|link|id)="(rId\d+)"', document_xml))
        missing = referenced - declared
        if not missing:
            return data, 0
        removed = 0

        def drop_unreadable(match: re.Match[str]) -> str:
            nonlocal removed
            span = match.group(0)
            if any(relationship_id in span for relationship_id in missing):
                removed += 1
                return ""
            return span

        document_xml = _UNREADABLE_CONTAINER.sub(drop_unreadable, document_xml)

        def drop_dead_link(match: re.Match[str]) -> str:
            return "" if match.group(1) in missing else match.group(0)

        document_xml = re.sub(r'\s+r:id="(rId\d+)"', drop_dead_link, document_xml)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as fresh:
            for info in archive.infolist():
                payload = (document_xml.encode("utf-8")
                           if info.filename == "word/document.xml"
                           else archive.read(info.filename))
                entry = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                fresh.writestr(entry, payload, compress_type=info.compress_type)
        return buffer.getvalue(), removed


#: The OOXML tokens the scan walks: where text lives (`w:t`), where dropped content lives
#: (`w:del`/`w:delText`, `m:oMath`, `w:drawing`/`w:pict`, `w:txbxContent`), and where a
#: shape's modern and fallback forms live (`mc:AlternateContent` — mammoth reads only the
#: `mc:Fallback` branch, so a block with one is carried, not dropped).
_OOXML_TOKEN = re.compile(
    r"<w:delText(?:\s[^>]*)?>(.*?)</w:delText>"
    r"|</w:del>"
    r"|<w:del(?:\s[^>]*)?>"
    r"|<m:oMath(?:\s[^>]*)?>"
    r"|<w:drawing(?:\s[^>]*)?>"
    r"|<w:pict(?:\s[^>]*)?>"
    r"|<w:txbxContent(?:\s[^>]*)?>"
    r"|<mc:AlternateContent(?:\s[^>]*)?>"
    r"|</mc:AlternateContent>"
    r"|<w:t(?:\s[^>]*)?>(.*?)</w:t>",
    re.S,
)


def _scan_ooxml(parts: list[tuple[str, str]]) -> dict[str, list[tuple[str, str, str]]]:
    """The parts' dropped-content inventory: `(kind, anchor, part)` triples, where the
    anchor is the last run of body text seen before the element — the "near '…'" of the
    warning.

    Grounded in mammoth 1.13's own source: `mc:AlternateContent` is read through its
    `mc:Fallback` children only (so a text box's text and a fallback picture ARE carried,
    silently), `w:del` is silently ignored, `m:oMath` has no handler (a warning without a
    location), and an image is always carried once its relationship resolves. So the scan
    skips the contents of an AlternateContent block that carries a Fallback — mammoth
    carries those — and classifies a `w:drawing`/`w:pict` that holds a `w:txbxContent` as
    a text box rather than a picture (the box's text is carried; the box itself is not),
    except inside a block with no Fallback, where mammoth reads nothing and the box's
    text is a genuine drop (`textboxes_dropped`).
    Equations and tracked deletions are counted everywhere: mammoth never carries either.
    """
    found: dict[str, list[tuple[str, str, str]]] = {
        "images": [], "equations": [], "deleted": [], "textboxes": [],
        "textboxes_dropped": [],
    }
    for part_name, xml in parts:
        last_text = ""
        del_depth = 0
        del_anchor = ""
        del_texts: list[str] = []
        # An open AlternateContent block whose Fallback exists: its contents are mammoth's
        # source, not a loss. A stack, because the blocks nest.
        carried_blocks: list[bool] = []
        # The AlternateContent blocks (by stack depth) that already gave up a text box.
        counted_boxes: set[int] = set()
        # The span of the drawing/pict container last classified: its own inner
        # `w:txbxContent` token must not count a second time.
        box_until = -1
        for match in _OOXML_TOKEN.finditer(xml):
            token = match.group(0)
            if token.startswith("<w:delText"):
                if del_depth:
                    del_texts.append(_html.unescape(match.group(1) or ""))
            elif token.startswith("<w:t") and match.group(2):
                last_text = _clip(_html.unescape(match.group(2)), _ANCHOR_CHARS)
            elif token.startswith("<w:del"):
                if del_depth == 0:
                    del_anchor = last_text
                del_depth += 1
            elif token == "</w:del>":
                if del_depth:
                    del_depth -= 1
                    if del_depth == 0 and del_texts:
                        joined = " ".join(part for part in
                                          (text.strip() for text in del_texts) if part)
                        found["deleted"].append((_clip(joined, _ANCHOR_CHARS),
                                                 del_anchor, part_name))
                        del_texts = []
            elif token.startswith("<m:oMath"):
                found["equations"].append((_clip("an equation", _ANCHOR_CHARS),
                                           last_text, part_name))
            elif token.startswith("<mc:AlternateContent"):
                fallback = xml.find("<mc:Fallback", match.end())
                closes = xml.find("</mc:AlternateContent>", match.end())
                carried_blocks.append(fallback != -1 and (closes == -1
                                                          or fallback < closes))
            elif token == "</mc:AlternateContent>":
                if carried_blocks:
                    carried_blocks.pop()
            elif token.startswith("<w:drawing") or token.startswith("<w:pict"):
                carried_here = bool(carried_blocks and carried_blocks[-1])
                tag = token[1:].split(">", 1)[0].split(" ", 1)[0]
                end = xml.find(f"</{tag}>", match.end())
                box_until = end if end != -1 else len(xml)
                body = xml[match.start(): box_until]
                if "w:txbxContent" in body:
                    # A shape without a Fallback branch is read by mammoth as nothing at
                    # all: its text is genuinely dropped, unlike a Fallback-borne box's.
                    # Either way the box is counted — its text (or its absence) is the
                    # account; the box itself never survives.
                    if carried_blocks and not carried_blocks[-1]:
                        found["textboxes_dropped"].append(
                            (last_text, last_text, part_name))
                    elif not carried_here:
                        found["textboxes"].append((last_text, last_text, part_name))
                    else:
                        # One AlternateContent block, one box: Word writes the box's
                        # content in both the Choice and the Fallback, and mammoth reads
                        # only the Fallback's copy — count the block's box once.
                        block_id = len(carried_blocks) - 1
                        if block_id not in counted_boxes:
                            counted_boxes.add(block_id)
                            found["textboxes"].append((last_text, last_text, part_name))
                elif not carried_here:
                    # An image inside a Fallback-bearing block arrives through that
                    # Fallback, so it is carried; anywhere else it is mammoth's own read.
                    found["images"].append((last_text, last_text, part_name))
            elif token.startswith("<w:txbxContent"):
                if 0 <= box_until and match.start() < box_until:
                    continue  # inside a container the drawing/pict branch accounted for
                found["textboxes"].append((last_text, last_text, part_name))
    return found


#: mammoth's style notices are noise, not loss: an undefined style still carries the text
#: through with the style's ID, so there is nothing to warn about.
_STYLE_NOTICE = re.compile(r"Paragraph style with ID .* was referenced but not defined")

#: mammoth carries an image it cannot name a browser-safe type for — the picture is in the
#: draft as a data URI, but the browser may render nothing where it stood. An advisory, not
#: a drop (`mammoth/docx/body_xml.py`: the warning is emitted on the carried-image path).
_IMAGE_ADVISORY = "unlikely to display"


def _docx_warnings(name: str, parser: "_DocxHTMLParser",
                   scan: dict[str, list[tuple[str, str, str]]],
                   messages, broken_images: int = 0) -> list[IntakeWarning]:
    """The `.docx` warning list: the scan's inventory first (each with its location), then
    whatever mammoth's own messages name beyond that.

    mammoth's image messages split by what actually happened: "unlikely to display" rode
    the carried-image path (the picture is in the draft; only its renderability is in
    question), while the rest name a picture mammoth did not carry. The body images the
    scan counted but mammoth never yielded are reconciled in aggregate — the dropped ones
    cannot be identified by position once a drop precedes a carry — after subtracting the
    drops mammoth's own messages already account for.

    A picture mammoth DID carry is not a silent success either (`§5.1`, FR-AUTHOR-25): what
    reaches the draft is an `image_ref` placeholder, the image data itself is not carried,
    so each carried picture is warned as `image_not_carried` as well — per picture, located
    by block position (the nearest heading above it), when the scan's body entries pair
    one-to-one with the parser's placeholders; by count when a drop or a broken picture
    makes the pairing ambiguous.
    """
    # mammoth's messages, classified before anything is appended, so the scan's
    # reconciliation can subtract the drops the messages already name.
    drop_notes: list[str] = []
    advisory_notes: list[str] = []
    other_notes: list[tuple[bool, str]] = []  # (is an equation notice, text)
    for message in messages:
        text = message.message
        if _STYLE_NOTICE.match(text):
            continue
        if "oMath" in text:
            other_notes.append((True, text))
        elif "mage" in text:
            if _IMAGE_ADVISORY in text:
                advisory_notes.append(text)
            else:
                drop_notes.append(text)
        else:
            other_notes.append((False, text))

    warnings: list[IntakeWarning] = []
    body_images = [entry for entry in scan["images"] if entry[2] == "word/document.xml"]
    uncarried = (len(body_images) - parser.image_count - len(drop_notes)
                 - broken_images)
    if uncarried > 0:
        warnings.append(IntakeWarning(
            code="image_not_carried",
            message=_bounded(f"{uncarried} of the {len(body_images)} pictures in this "
                             "document were not carried into the draft — add them by "
                             "hand if they matter."),
            detail=f"{uncarried} of {len(body_images)} drawing/picture element(s) in the "
                   "document body have no carried counterpart"))
    if parser.image_count:
        # mammoth carries every resolvable picture as a data-URI `<img>`; the parser turns
        # each into an `image_ref` placeholder and drops the data. A placeholder is not the
        # figure — FR-AUTHOR-25's shape is "a warning plus a placeholder", so the carried
        # pictures are named too, per location when the scan's entries pair one-to-one
        # with the parser's placeholders (no drop shifted the positions), and by count when
        # they do not.
        placeholders = parser.image_count
        if not broken_images and not drop_notes and placeholders == len(body_images):
            # The clean pairing is in document order on both sides: the scan walked the
            # body XML and the parser read mammoth's HTML, so the i-th scanned picture is
            # the i-th `image_ref` block — the location comes from block position, never
            # from text matching (the same sentence can stand under two sections).
            image_positions = [position for position, (kind, _, _)
                               in enumerate(parser.blocks) if kind == "image_ref"]
            for entry, position in zip(body_images, image_positions):
                location = _heading_above(parser, position) or entry[0]
                warnings.append(IntakeWarning(
                    code="image_not_carried",
                    message=_bounded(
                        f"This picture{_anchor(location)} was carried only as a "
                        "placeholder — the image itself is not in the draft; add it by "
                        "hand if it matters."),
                    detail=_clip(f"a picture carried as an image_ref placeholder (the "
                                 f"image data is not in the draft), near '{location}'",
                                 WARNING_MAX_CHARS)))
        else:
            if placeholders == 1:
                message = ("1 picture in this document was carried only as a placeholder "
                           "— the image itself is not in the draft; add it by hand if it "
                           "matters.")
            else:
                message = (f"{placeholders} pictures in this document were carried only "
                           "as placeholders — the images themselves are not in the "
                           "draft; add them by hand if they matter.")
            warnings.append(IntakeWarning(
                code="image_not_carried", message=_bounded(message),
                detail=f"{placeholders} image_ref placeholder block(s); the image data "
                       "is not in the draft"))
    if broken_images == 1:
        warnings.append(IntakeWarning(
            code="image_not_carried",
            message=_bounded("One picture in this document could not be read and was "
                             "not carried into the draft — add it by hand if it "
                             "matters."),
            detail="1 picture references a relationship the document's parts do not "
                   "declare"))
    elif broken_images:
        warnings.append(IntakeWarning(
            code="image_not_carried",
            message=_bounded(f"{broken_images} pictures in this document could not be "
                             "read and were not carried into the draft — add them by "
                             "hand if they matter."),
            detail=f"{broken_images} pictures reference relationships the document's "
                   "parts do not declare"))
    for entry in scan["images"]:
        if entry[2] != "word/document.xml":
            warnings.append(IntakeWarning(
                code="image_not_carried",
                message=_bounded(f"This picture{_part_where(entry[2])} was not carried "
                                 "into the draft — add it by hand if it matters."),
                detail=f"a drawing/picture element in {entry[2]} (outside the document body)"))
    if scan["equations"]:
        first_anchor = _anchor(_nearest_heading(parser, scan["equations"][0][1]))
        warnings.append(IntakeWarning(
            code="equation_not_carried",
            message=_bounded(f"Equations were not carried over — write them out in words "
                             f"in their place{first_anchor}."),
            detail=f"{len(scan['equations'])} OMML equation element(s) "
                   f"({', '.join(sorted({part for _, _, part in scan['equations']}))})"))
    for deleted, anchor, part in scan["deleted"]:
        warnings.append(IntakeWarning(
            code="formatting_dropped",
            message=_bounded("This document has tracked changes: text deleted"
                             f"{_anchor(anchor) or ' somewhere'} was not carried."),
            detail=f"deleted text near '{deleted}' in {part}"))
    for anchor, _, part in scan["textboxes"]:
        # mammoth flattens a text box's text into the body without a message; what is
        # lost is the box — its placement and border.
        warnings.append(IntakeWarning(
            code="formatting_dropped",
            message=_bounded(
                f"This document has a text box{_anchor(anchor)}: its text was carried "
                "into the draft, but the box's placement was not — check it in the "
                "original file."),
            detail=f"a text box (w:txbxContent) in {part}"))
    for anchor, _, part in scan["textboxes_dropped"]:
        # A shape with no Fallback branch: mammoth reads nothing from it, text included.
        warnings.append(IntakeWarning(
            code="formatting_dropped",
            message=_bounded(f"This text box{_anchor(anchor)} was not carried — move its "
                             "text into the document body if it matters."),
            detail=f"a text box without a fallback form in {part}"))
    saw_equation_warning = any(warning.code == "equation_not_carried"
                               for warning in warnings)
    for text in advisory_notes:
        warnings.append(IntakeWarning(
            code="formatting_dropped",
            message=_bounded("This picture may not display in the draft — check it in "
                             "the original file."),
            detail=_clip(text, WARNING_MAX_CHARS)))
    for text in drop_notes:
        # A mammoth drop notice the scan did not locate (it counted nothing) still means
        # a picture was not carried.
        warnings.append(IntakeWarning(
            code="image_not_carried",
            message=_bounded("This picture was not carried into the draft — add it by "
                             "hand if it matters."),
            detail=_clip(text, WARNING_MAX_CHARS)))
    for is_equation, text in other_notes:
        if is_equation:
            # The scan owns equations — unless it found none, in which case mammoth's own
            # notice is the only account and it stands (without a location).
            if saw_equation_warning:
                continue
            warnings.append(IntakeWarning(
                code="equation_not_carried",
                message=_bounded("Equations were not carried into the draft — describe "
                                 "them in words where they belong."),
                detail=_clip(text, WARNING_MAX_CHARS)))
            saw_equation_warning = True
            continue
        warnings.append(IntakeWarning(
            code="formatting_dropped",
            message=_bounded("Some formatting in this document was not carried over."),
            detail=_clip(text, WARNING_MAX_CHARS)))
    return warnings


def _part_where(part: str) -> str:
    """The location clause for content found outside the document body."""
    if "header" in part:
        return " in the page header"
    if "footer" in part:
        return " in the page footer"
    return ""


def _heading_above(parser: "_DocxHTMLParser", index: int) -> str:
    """The nearest heading block at or before block `index`, '' when none stands above
    it. This is the location clause's source when the element's block position is known —
    the honest way to name a section, never dependent on text matching."""
    for kind, text, _ in reversed(parser.blocks[:index + 1]):
        if kind == "heading":
            return text
    return ""


def _nearest_heading(parser: "_DocxHTMLParser", anchor: str) -> str:
    """The heading text a warning's location clause names (`§3.1.1`: the message "names the
    location — \\"Figure near 'Question 3'\\"").

    The scan's anchor is the last run of body text seen before the element, so the block it
    opens is where the element stands, and the nearest heading at or before that block is
    the section the element belongs to. The anchor itself stands in when the anchor matches
    no block (an element inside a paragraph whose runs mammoth split differently) or when
    no heading stands above it — a location clause still names something. Callers that know
    the element's block position (the carried placeholders, paired positionally with the
    scan's entries) use `_heading_above` directly: text matching can hit the wrong
    occurrence when the same sentence stands under two sections.
    """
    if not anchor:
        return anchor
    probe = anchor[:-1] if anchor.endswith("…") else anchor
    index = next((position for position, (kind, text, _) in enumerate(parser.blocks)
                  if kind != "image_ref" and text.startswith(probe)), None)
    if index is None:
        return anchor
    return _heading_above(parser, index) or anchor


class _DocxHTMLParser(HTMLParser):
    """mammoth's semantic HTML to blocks, with the stdlib parser (`FR-AUTHOR-25`).

    Headings map to heading blocks at their level, `p` to paragraphs, list items to
    `list_item` blocks at their nesting depth, tables to one table block per table (one
    row per line, cells tab-separated), and images to `image_ref` blocks carrying the alt
    text — the placeholder that says a figure stood here.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str, int | None]] = []
        self.image_count = 0
        self._kind = "paragraph"
        self._level: int | None = None
        self._pieces: list[str] | None = None
        self._row: list[str] = []
        self._rows: list[list[str]] = []
        self._cell: list[str] | None = None
        self._cell_parts: list[str] = []
        self._list_depth = 0

    # -- capture helpers ----------------------------------------------------------------------

    def _start_capture(self, kind: str, level: int | None) -> None:
        self._flush()
        self._kind = kind
        self._level = level
        self._pieces = []

    def _flush(self) -> None:
        pieces, self._pieces = self._pieces, None
        if pieces is None:
            return
        text = _inline_text(pieces)
        kind, level = self._kind, self._level
        self._kind, self._level = "paragraph", None
        if not text:
            return
        if self._cell is not None:
            if self._cell_parts:
                self._cell_parts.append(" ")  # multi-paragraph cells read on one line
            self._cell_parts.append(text.replace("\n", " "))
            return
        self.blocks.append((kind, text, level))

    # -- the parser's hooks ---------------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001 - stdlib signature
        attributes = dict(attrs)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._start_capture("heading", int(tag[1]))
        elif tag == "p":
            self._start_capture("paragraph", None)
        elif tag in ("ul", "ol"):
            self._list_depth += 1
        elif tag == "li":
            self._start_capture("list_item", self._list_depth)
        elif tag == "table":
            self._rows = []
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._flush()
            self._cell = []
            self._cell_parts = []
        elif tag == "img":
            self.image_count += 1
            self.blocks.append(("image_ref", _clip(attributes.get("alt") or "", _ANCHOR_CHARS),
                                None))
        elif tag == "br":
            if self._pieces is not None:
                self._pieces.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:  # noqa: ANN001 - stdlib signature
        if tag == "img":
            self.handle_starttag(tag, attrs)
        elif tag == "br":
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li"):
            self._flush()
        elif tag in ("ul", "ol"):
            self._list_depth = max(0, self._list_depth - 1)
        elif tag in ("td", "th"):
            self._flush()
            self._cell = None
            self._row.append(" ".join(self._cell_parts).strip())
            self._cell_parts = []
        elif tag == "tr":
            if self._row:
                self._rows.append(self._row)
            self._row = []
        elif tag == "table":
            text = "\n".join("\t".join(row) for row in self._rows)
            self._rows = []
            if text.strip():
                self.blocks.append(("table", text, None))

    def handle_data(self, data: str) -> None:
        if self._pieces is not None:
            self._pieces.append(data)


def _inline_text(pieces: list[str]) -> str:
    """Captured HTML text as block text: whitespace collapsed inside each line, empty
    lines dropped, kept lines joined with newlines (a `<br>`'s line break survives)."""
    lines: list[str] = []
    for line in "".join(pieces).split("\n"):
        line = re.sub(r"[ \t\r\f\v]+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


# -- the .txt path (FR-AUTHOR-26) -------------------------------------------------------------


def _normalize_txt(name: str, data: bytes) -> NormalizedDocument:
    """`.txt` through encoding detection, line-ending normalization and best-effort
    structure inference — every inferred heading, table and list warned (`FR-AUTHOR-26`)."""
    text, encoding_warning = _decode_text(name, data)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise DocumentRefusedError(
            NO_TEXT_SENTENCE, name,
            detail=f"the file decodes as {encoding_warning.detail} to no text"
            if encoding_warning else "the file holds no text")
    blocks, warnings = _blocks_from_lines(text, tables=True, lists=True,
                                          warn_structure=True)
    if encoding_warning is not None:
        warnings.insert(0, encoding_warning)
    return _assemble(name, "txt", data, blocks, warnings)


#: The encodings the detection names, in the words a teacher knows. Anything outside the
#: map is shown as charset-normalizer spelled it.
_ENCODING_DISPLAY = {
    "cp1252": "Windows-1252",
    "cp1250": "Windows-1250",
    "cp1251": "Windows-1251",
    "iso8859_1": "ISO-8859-1 (Latin-1)",
    "latin_1": "ISO-8859-1 (Latin-1)",
    "utf_16": "UTF-16",
    "utf_32": "UTF-32",
    "mac_roman": "Mac Roman",
    "koi8_r": "KOI8-R",
    "shift_jis": "Shift JIS",
    "big5": "Big5",
    "gb2312": "GB2312",
    "euc_jp": "EUC-JP",
    "euc_kr": "EUC-KR",
}


def _decode_text(name: str, data: bytes) -> tuple[str, IntakeWarning | None]:
    """The bytes as text, and the `encoding_fallback` warning when the detection is not
    UTF-8 (`FR-AUTHOR-26`).

    The chain is strict UTF-8 first (a BOM is stripped by `utf-8-sig` when present), then
    charset-normalizer with the cp1252/latin-1 family preferred — probed against
    charset-normalizer 3.5: its blind `best()` mis-detects cp1252 text as cp1250 (the
    accented characters come back wrong), so the family is picked from the candidate list
    by name before falling back to the best-ranked candidate, and a NUL-bearing byte
    stream prefers the UTF-16/32 candidates over the single-byte family.
    """
    if data.startswith(codecs.BOM_UTF8):
        return data.decode("utf-8-sig"), None
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        pass
    for bom, encoding in ((codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"),
                          (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16")):
        if data.startswith(bom):
            try:
                return data.decode(encoding), _encoding_warning(name, data, encoding,
                                                                [encoding])
            except UnicodeDecodeError:
                break
    try:
        from charset_normalizer import from_bytes
    except ImportError as error:  # pragma: no cover - charset-normalizer is a dependency
        raise AuthoringInputError(
            f"charset-normalizer is not available; .txt encodings cannot be detected "
            f"({error}).") from error
    candidates = [match.encoding for match in from_bytes(data)]
    family = [name_ for name_ in ("cp1252", "iso8859_1") if name_ in candidates]
    if b"\x00" in data:
        wide = [name_ for name_ in ("utf_16", "utf_32") if name_ in candidates]
        if wide:
            family = wide
    encoding = family[0] if family else (candidates[0] if candidates else "cp1252")
    try:
        text = data.decode(encoding, errors="replace")
    except (LookupError, UnicodeError):
        encoding, text = "cp1252", data.decode("cp1252", errors="replace")
    return text, _encoding_warning(name, data, encoding, candidates)


def _encoding_warning(name: str, data: bytes, encoding: str,
                      candidates: list[str]) -> IntakeWarning:
    """The `encoding_fallback` warning, in the design's sentence, naming the encoding the
    file was read as."""
    # The BOM branch passes the codec spellings ("utf-16"); the map keys follow
    # charset-normalizer's ("utf_16") — normalize before the lookup.
    display = _ENCODING_DISPLAY.get(encoding.replace("-", "_"), encoding)
    if encoding.startswith("utf"):
        message = (f"This file uses a less common Unicode encoding — we read it as "
                   f"{display}; check that special characters look right.")
    else:
        message = (f"This file is not Unicode — we read it as {display}; check that "
                   "special characters look right.")
    return IntakeWarning(
        code="encoding_fallback", message=_bounded(message),
        detail=f"{name}: charset-normalizer candidates {candidates[:5]}; "
               f"{len(data)} bytes decoded as {encoding}")


# -- structure inference, shared by the .txt and .pdf paths ------------------------------------

_HEADING_NUMBERED = re.compile(r"^\s*(?:\d+\s*[.)]\s+\S|Q\s*\d+\b|Question\s+\d+\b)")
_BULLET_PREFIXES = ("- ", "* ", "• ", "– ", "— ")


def _is_all_caps(line: str) -> bool:
    letters = [char for char in line if char.isalpha()]
    return len(letters) >= 2 and line == line.upper() and len(line) <= 80


def _heading_candidate(line: str, followed_by_blank: bool) -> int | None:
    """The heading rules of FR-AUTHOR-26, in priority order, with the level each rule
    implies: ALL-CAPS is a top title, a numbered line marks a question, a short line set
    off by blank lines is a section title."""
    if _is_all_caps(line):
        return 1
    if _HEADING_NUMBERED.match(line):
        return 3
    if (followed_by_blank and 0 < len(line) <= 80
            and not line.endswith((".", "!", "?", ";", ","))):
        return 2
    return None


def _is_bullet(line: str) -> bool:
    return line.startswith(_BULLET_PREFIXES)


def _blocks_from_lines(text: str, *, tables: bool, lists: bool, warn_structure: bool,
                       guard: str | None = None,
                       ) -> tuple[list[tuple[str, str, int | None]], list[IntakeWarning]]:
    """Plain text to blocks, line runs at a time: a run of tab-separated lines is a table,
    a run of bulleted lines is list items, a heading candidate is a heading, everything
    else is a paragraph. `warn_structure` marks every inference with `structure_guessed`
    (the `.txt` path; the PDF path rides the same heuristics silently, FR-AUTHOR-27).

    `guard`, when given, is the text the blocks must project back to exactly
    (`document_text`'s join): when the structured reading would change so much as a
    newline, the whole text comes back as one paragraph instead — structure is never
    worth a changed character of content.
    """
    lines = text.split("\n")
    blocks: list[tuple[str, str, int | None]] = []
    warnings: list[IntakeWarning] = []
    index, count = 0, len(lines)
    while index < count:
        if not lines[index].strip():
            index += 1
            continue
        start = index
        run: list[str] = []
        while index < count and lines[index].strip():
            run.append(lines[index].strip())
            index += 1
        followed_by_blank = index < count  # the loop stopped on a blank line or the end
        stripped = run
        if tables and len(stripped) >= 2 and all("\t" in line for line in stripped):
            blocks.append(("table", "\n".join(stripped), None))
            if warn_structure:
                warnings.append(_structure_warning(
                    "table", start, stripped[0]))
            continue
        if lists and all(_is_bullet(line) for line in stripped):
            for offset, line in enumerate(stripped):
                blocks.append(("list_item", line[2:].strip() if line[:2] in ("- ", "* ")
                               else line.lstrip("•–— ").strip(), None))
            if warn_structure:
                warnings.append(_structure_warning("list", start, stripped[0]))
            continue
        # The heading rules apply per line, not per run (FR-AUTHOR-26): an ALL-CAPS line
        # and a `Question 3`-numbered line are candidates wherever they stand — a quiz's
        # `Question 1` sits on its own line right above its first question, with no blank
        # line to set it off. The "short line set off by a blank line" rule needs the
        # blank after it, so only a run's last line can satisfy it. Consecutive
        # non-candidate lines stay one paragraph, as before.
        paragraph: list[str] = []
        for offset, line in enumerate(stripped):
            level = _heading_candidate(line, followed_by_blank
                                       and offset == len(stripped) - 1)
            if level:
                if paragraph:
                    blocks.append(("paragraph", "\n".join(paragraph), None))
                    paragraph = []
                blocks.append(("heading", line, level))
                if warn_structure:
                    warnings.append(_structure_warning(
                        "heading", start + offset, line))
            else:
                paragraph.append(line)
        if paragraph:
            blocks.append(("paragraph", "\n".join(paragraph), None))
    if (warn_structure and len(blocks) > 1
            and not any(warning.code == "structure_guessed" for warning in warnings)):
        # A heading-less prose file (§5.1's AF-17 row): no heading/table/list rule fired,
        # so the outline itself is the guess — the blocks came from blank-line separation
        # alone, and presenting them as read would hide it. The design's heading sentence
        # is the message; the review walk, not the intake, is where a wrong guess gets
        # fixed (FR-AUTHOR-26).
        warnings.append(IntakeWarning(
            code="structure_guessed",
            message=_bounded("We guessed where the headings are — check the outline on "
                             "the next screen."),
            # "using", not "from": "from" beside "table" below is two SQL keywords in one
            # f-string, and SEC-15's source scanner (tests/support/sql_scan.py) cannot tell
            # teacher-facing prose from an assembled statement — the tree must stay clean.
            detail=f"the outline was guessed using blank lines alone: {len(blocks)} "
                   "blocks, no heading/table/list rule matched"))
    if guard is not None:
        projected = "\n\n".join(item[1] for item in blocks)
        if projected != guard:
            return [("paragraph", guard, None)], []
    return blocks, warnings


def _structure_warning(kind: str, line_index: int, sample: str) -> IntakeWarning:
    """The `structure_guessed` warning: the design's sentence, the operator detail naming
    the rule, the source line and a short sample."""
    noun = {"heading": "headings", "table": "table", "list": "list"}[kind]
    if kind == "heading":
        message = "We guessed where the headings are — check the outline on the next screen."
    else:
        message = (f"We guessed these lines are a {noun} — check it on the next screen.")
    return IntakeWarning(
        code="structure_guessed", message=_bounded(message),
        detail=f"inferred on source line {line_index + 1}: {_clip(sample, 60)}")


# -- the .pdf path in intake itself (FR-AUTHOR-27, the console's upload preview) ---------------


def _normalize_pdf(name: str, data: bytes) -> NormalizedDocument:
    """The PDF's text layer through the same block heuristics, under the same per-page
    guard `normalized_from_authoring` uses. No transcriber here — a page with no text
    layer stands empty, and a document with no text at all comes back with the
    scanned-pages note (`FR-AUTHOR-28`'s images-only arm is the draft's transcriber path,
    not a refusal)."""
    try:
        from pypdf import PdfReader
    except ImportError as error:  # pragma: no cover - pypdf is a project dependency
        raise AuthoringInputError(
            f"pypdf is not available; the text layer cannot be read ({error}).") from error
    try:
        reader = PdfReader(io.BytesIO(data))
        page_texts = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as error:  # noqa: BLE001 - an unreadable PDF is refused, not parsed
        lowered = str(error).lower()
        if "password" in lowered or "decrypt" in lowered:
            raise DocumentRefusedError(
                PASSWORD_SENTENCE, name,
                detail=f"{type(error).__name__}: {error}") from error
        raise DocumentRefusedError(
            NO_TEXT_SENTENCE, name,
            detail=f"the PDF could not be read: {type(error).__name__}: {error}") from error
    blocks: list[tuple[str, str, int | None]] = []
    warnings: list[IntakeWarning] = []
    for page_text in page_texts:
        if not page_text:
            continue
        page_blocks, page_warnings = _blocks_from_lines(
            page_text, tables=False, lists=False, warn_structure=False, guard=page_text)
        blocks.extend(page_blocks)
        warnings.extend(page_warnings)
    if not any(text for _, text, _ in blocks):
        warnings.append(IntakeWarning(
            code="image_not_carried", message=_bounded(SCANNED_PDF_SENTENCE),
            detail="no page yielded a text layer"))
    return _assemble(name, "pdf", data, blocks, warnings)
