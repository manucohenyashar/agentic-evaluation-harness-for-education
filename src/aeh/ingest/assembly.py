"""Assembling page transcripts, in printed order, into the one canonical Markdown document."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Sequence

from .descriptions import _FIDUCIAL_PATTERN, _PAGE_NUMBER_PATTERN
from .errors import IngestError, IngestGapError, IngestOrderError


# --- the ingestor ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class AssembledDocument:
    """The assembled canonical document: the Markdown, its content hash, the transcriber build when
    known, and its provenance: for each page, the source's content hash, the page's index in that
    source and its position in the document (FR-INGEST-07), plus which source decided the order
    (FR-INGEST-06)."""

    canonical_markdown: str
    content_hash: str
    transcriber_ref: str | None
    order_source: str
    pages: tuple[dict, ...]

    @property
    def source_blobs(self) -> str:
        """The provenance as the document row stores it (FR-INGEST-06): which source decided the
        order and, per page, the source, its page index and its position in the document."""
        return json.dumps(
            {"order_source": self.order_source, "pages": list(self.pages)},
            sort_keys=True,
        )


def _parse_page_number(text: str) -> tuple[int, int] | None:
    """A page's `(number, declared total)` from a "Page N of M" header. The total is what makes a
    gap visible: pages 1, 2, 4, 5, 6 of a declared 7 are missing 3 and 7, which counting the pages
    found could never show."""
    match = _PAGE_NUMBER_PATTERN.search(text)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _parse_fiducial(text: str) -> str | None:
    match = _FIDUCIAL_PATTERN.search(text)
    return match.group(1) if match else None


def _natural_key(name: str) -> list:
    """Sort key for file names the way a person means them: numbers compare as numbers, so page-10
    comes after page-9, not between page-1 and page-2."""
    return [int(part) if part.isdigit() else part
            for part in re.split(r"(\d+)", name)]


def assemble_canonical_markdown(
    pages: Sequence[Any], *, transcriber_ref: str | None = None,
    order_hint: Sequence[Any] | None = None, filenames: dict[Any, str] | None = None,
) -> AssembledDocument:
    """Assemble transcribed page files into the one canonical Markdown document (FR-INGEST-04),
    ordering the pages by the declared preference ladder (FR-INGEST-06) and recording each page's
    provenance (FR-INGEST-07).

    `pages` are page transcripts — file paths or any object `str()`/`read_text` can
    read. The preference ladder, in strict order: an operator-stated order
    (`order_hint`, a sequence naming every page) > a printed page number parsed from
    the page ("Page N of M") > a fiducial marker > filename ordering (natural sort,
    when `filenames` maps each page to its name). Nothing here reads directory order;
    with no tier available the call refuses (`IngestOrderError`, `FR-INGEST-31`) —
    the module never guesses.

    This is the pure seam the regression baseline (`TC-REG-01`) pins — the
    ladder's reference semantics. `Ingestor.ingest_document` implements the same
    ladder over the blob store (a blob is one file of many pages, the seam's
    page IS the file); the two move together, ambiguity refusal included
    (#227)."""
    texts: list[str] = []
    for page in pages:
        if hasattr(page, "read_text"):
            texts.append(page.read_text(encoding="utf-8"))
        else:
            texts.append(str(page))
    if not texts:
        raise IngestError("assembly needs at least one page.")

    identities = [getattr(page, "name", None) or str(page) for page in pages]
    order_source: str | None = None
    ordered_indices: list[int] | None = None
    if order_hint is not None:
        hint_names = [str(item) for item in order_hint]
        if sorted(hint_names) != sorted(identities):
            raise IngestError(
                "the operator-stated order does not name every page exactly once."
            )
        # Index by FIRST UNUSED occurrence, so two pages sharing a basename (the
        # same file name materialized in different directories) cannot collapse.
        by_identity: dict[str, list[int]] = {}
        for index, identity in enumerate(identities):
            by_identity.setdefault(identity, []).append(index)
        ordered_indices = []
        taken: set[int] = set()
        for name in hint_names:
            index = next(i for i in by_identity[name] if i not in taken)
            taken.add(index)
            ordered_indices.append(index)
        order_source = "operator"
    if order_source is None:
        numbers = [_parse_page_number(text) for text in texts]
        if all(number is not None for number in numbers):
            declared_totals = {total for _, total in numbers}
            if len(declared_totals) != 1:
                raise IngestGapError(
                    f"the pages disagree about the document's page count "
                    f"({sorted(declared_totals)}): a torn or mixed stack "
                    "(FR-INGEST-09)."
                )
            total = declared_totals.pop()
            found = [number for number, _ in numbers]
            missing = sorted(set(range(1, total + 1)) - set(found))
            if missing:
                raise IngestGapError(
                    f"the printed page sequence is missing positions {missing} "
                    f"(found {sorted(found)} of {total}): rescan the missing pages "
                    "or state the order explicitly (FR-INGEST-09)."
                )
            repeats = sorted({number for number in found
                              if found.count(number) > 1})
            if repeats:
                raise IngestGapError(
                    f"the printed page sequence repeats positions {repeats} "
                    "(FR-INGEST-09)."
                )
            ordered_indices = sorted(range(len(found)), key=lambda i: found[i])
            order_source = "page_number"
    if order_source is None:
        markers = [_parse_fiducial(text) for text in texts]
        if all(marker is not None for marker in markers):
            repeats = sorted({marker for marker in markers
                              if markers.count(marker) > 1})
            if repeats:
                raise IngestGapError(
                    f"the fiducial markers repeat positions {repeats} — a misprint "
                    "or a duplicated sheet (FR-INGEST-09)."
                )
            ordered_indices = sorted(range(len(markers)),
                                     key=lambda i: _natural_key(markers[i]))
            order_source = "marker"
    if order_source is None:
        # The filename tier: an explicit mapping when the caller has real names, else
        # the page's own name (a materialized page FILE is named by its position —
        # page-01.md sorts naturally). This is tier four, not a guess: the design
        # permits filename ordering, and a path's name is a filename.
        names = ([filenames.get(identity) for identity in identities]
                 if filenames is not None else list(identities))
        if all(names):
            # The ambiguity line (FR-INGEST-31, #227), the same one the gateway's
            # ladder enforces: the tier resolves iff its natural keys form a
            # strict total order over the pages; a key collision (identical
            # names, or digit-variant spellings like page-1 vs page-01) refuses —
            # never a silent stable sort over the caller's order.
            keys = [tuple(_natural_key(name)) for name in names]
            colliding = sorted({
                names[index] for index, key in enumerate(keys)
                if keys.count(key) > 1
            })
            if colliding:
                raise IngestOrderError(
                    f"ambiguous filenames cannot be ordered: "
                    f"{', '.join(repr(name) for name in colliding)} resolve to "
                    "the same position, so the filename tier cannot order them. "
                    "The module never guesses (FR-INGEST-31) — state the order "
                    "and re-ingest."
                )
            ordered_indices = sorted(range(len(names)),
                                     key=lambda i: _natural_key(names[i]))
            order_source = "filename"
    if order_source is None:
        raise IngestOrderError(
            "assembly order cannot be determined: no operator-stated order, no "
            "printed page numbers, no fiducial markers, and no unambiguous filenames. "
            "The module never guesses (FR-INGEST-31) — state the order and re-ingest."
        )
    ordered_texts = [texts[index] for index in ordered_indices]

    canonical = "\n\n<!-- page break -->\n\n".join(ordered_texts)
    provenance = [
        {
            "source": identities[index],
            "page_no": index + 1,
            "position": position + 1,
        }
        for position, index in enumerate(ordered_indices)
    ]
    return AssembledDocument(
        canonical_markdown=canonical,
        content_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        transcriber_ref=transcriber_ref,
        order_source=order_source,
        pages=tuple(provenance),
    )
