"""The manuals library (FR-HELP-01, Q-O2): the packaged operator-facing manuals, their
manifest, and the heading-chunked reading of them with a table of contents and stable anchors.

The manuals are the repository's operator-facing documents, packaged with the install under
``MANUALS_DIR`` as package data: the teacher guide, the deployment tutorial, the console's
operating tutorial, and the live-test day plan. The manifest is **declared** here — ids and
titles are stable identifiers that citations and anchors resolve against, so they live in
code rather than being inferred from whatever happens to be in the directory — and each
entry's file must exist in the manuals directory or ``manuals_manifest`` refuses.

Chunking is by heading at every level: each Markdown heading starts one section that runs to
the next heading of any level, and its text is the source lines verbatim. Anchors are derived
from the heading text (lowercase, non-alphanumeric runs collapsed to one hyphen) with a
"-2", "-3"… disambiguator when a manual repeats a heading — computed in document order, so
they are identical in every process regardless of hash seed (`TC-HELP-01` compares two console
starts and two fresh interpreters). Heading-looking lines inside a code fence are content,
not headings — the same fence rule the test support's phrase seeder applies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: The package-data directory the operator-facing manuals ship in (Q-O2). Resolved from this
#: file rather than the working directory, so an installed wheel serves the same manuals a
#: checkout does (the `SPA_BUNDLE_DIR` precedent).
MANUALS_DIR: Path = Path(__file__).resolve().parent.parent / "help_assets" / "manuals"


@dataclass(frozen=True)
class ManualRecord:
    """One manifest entry: the manual's stable id, its title, and its file path relative to
    the manuals directory."""

    manual_id: str
    title: str
    path: str


#: The packaged manifest, in page order. The titles are what Q-O2's corpus census matches on:
#: "teacher guide", "deployment tutorial", "live-test documents" and "console help" — one
#: manual per kind, so widening the corpus later is a visible change here.
MANIFEST: tuple[ManualRecord, ...] = (
    ManualRecord(
        manual_id="teacher-guide",
        title="Teacher guide: how grading works",
        path="teacher-guide.md",
    ),
    ManualRecord(
        manual_id="console-operating-tutorial",
        title="Console operating tutorial",
        path="console-operating-tutorial.md",
    ),
    ManualRecord(
        manual_id="deployment-tutorial",
        title="Deployment tutorial",
        path="deployment-tutorial.md",
    ),
    ManualRecord(
        manual_id="live-test-day-plan",
        title="Live-test day plan",
        path="live-test-day-plan.md",
    ),
)


@dataclass(frozen=True)
class TocEntry:
    """One table-of-contents line: the section's anchor and heading."""

    anchor: str
    heading: str


@dataclass(frozen=True)
class Section:
    """One heading-chunked section: its anchor, its heading, and its source text."""

    anchor: str
    heading: str
    text: str


@dataclass(frozen=True)
class Manual:
    """One manual as the manuals page renders it."""

    manual_id: str
    title: str
    toc: tuple[TocEntry, ...]
    sections: tuple[Section, ...]


_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
#: Anchor slug: lowercase, every non-alphanumeric run to one hyphen. Anchors are URL
#: fragments; the SPA's page is plain HTML rendering of these ids.
_SLUG_DISALLOWED = re.compile(r"[^0-9a-z]+")


def manuals_manifest(manuals_dir: Path | None = None) -> tuple[ManualRecord, ...]:
    """The packaged manifest, refused if a declared manual's file is not packaged.

    ``manuals_dir`` is the deterministic seam (`CLAUDE.md` seam 2): the assistant and the
    console reads can be pointed at a copy of the manuals — which is how `SEC-25`'s nested
    arm nests an injected passage in a manual without touching package data. The manifest is
    the declared set regardless of the directory; only the files' presence is checked there.
    """
    root = Path(manuals_dir) if manuals_dir is not None else MANUALS_DIR
    missing = [record.path for record in MANIFEST if not (root / record.path).is_file()]
    if missing:
        raise FileNotFoundError(
            f"the packaged manuals manifest names files missing from {root}: {missing}. "
            "The manifest is declared in aeh.help.manuals; the manuals directory is package "
            "data."
        )
    return MANIFEST


def _slugify(heading: str, taken: set[str]) -> str:
    """A stable anchor for one heading, unique within its manual.

    Deterministic: the slug is derived from the heading text alone, and a repeat takes the
    next free numeric suffix in document order — never a hash, so two interpreters agree
    (`TC-HELP-01`'s PYTHONHASHSEED arms)."""
    base = _SLUG_DISALLOWED.sub("-", heading.lower()).strip("-") or "section"
    slug = base
    counter = 2
    while slug in taken:
        slug = f"{base}-{counter}"
        counter += 1
    taken.add(slug)
    return slug


def _chunk(markdown: str) -> tuple[Section, ...]:
    """Split one manual's source into sections, one per heading at every level.

    A fenced block's lines are content even when one looks like a heading (the deployment
    tutorial's config snippets carry `#` comment lines); the fence toggles exactly like the
    test support's phrase seeder, so what it seeds from is what chunking holds."""
    sections: list[Section] = []
    taken: set[str] = set()
    heading = ""
    anchor = ""
    lines: list[str] = []
    in_code = False
    for line in markdown.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
        else:
            match = None if in_code else _HEADING.match(line)
            if match is not None:
                if heading:
                    sections.append(Section(anchor, heading, "\n".join(lines).strip("\n")))
                heading = match.group(2)
                anchor = _slugify(heading, taken)
                lines = []
                continue
        lines.append(line)
    if heading:
        sections.append(Section(anchor, heading, "\n".join(lines).strip("\n")))
    return tuple(sections)


def load_manuals(manuals_dir: Path | None = None) -> tuple[Manual, ...]:
    """The packaged manuals as the manuals page renders them: each with its table of contents
    (every section, in page order) and its heading-chunked sections."""
    root = Path(manuals_dir) if manuals_dir is not None else MANUALS_DIR
    manuals = []
    for record in manuals_manifest(root):
        raw = (root / record.path).read_text(encoding="utf-8")
        sections = _chunk(raw)
        manuals.append(Manual(
            manual_id=record.manual_id,
            title=record.title,
            toc=tuple(TocEntry(anchor=s.anchor, heading=s.heading) for s in sections),
            sections=sections,
        ))
    return tuple(manuals)
