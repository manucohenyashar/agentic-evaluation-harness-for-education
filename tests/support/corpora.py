"""Reading the corpora from a test, and materializing pages when a case needs real files.

The corpora themselves are built by `harness.corpora` and committed under `fixtures/`. This
module is the read side: one place that knows the layout, so a case that wants the frozen set
asks for the frozen set rather than composing a path.

`materialize_pages` exists because of what §4.4's corpora are *for*. A submission is committed
as one Markdown file with page markers — see `harness.corpora.synth` for why — but the
ingestion cases need several page blobs to assemble, and `FR-INGEST-06` is specifically about
which of three sources decides that order. Splitting into `page-01.md` … `page-04.md` in a
temp directory gives a case both permitted sources (filename ordering, and the printed
`Page N of 4 - <submission id>` line) and neither is the directory iteration order the
requirement forbids.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.support.impl import require_path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CORPUS_ROOT = REPO_ROOT / "fixtures"

# The issue that owns the corpora, for the message a missing one produces.
CORPORA_ISSUE = "#2"

_PAGE_MARKER = re.compile(r"^<!-- page: (\d+) of (\d+) -->$", re.MULTILINE)


@dataclass(frozen=True)
class CorpusMember:
    id: str
    path: Path
    content_hash: str
    attributes: Mapping[str, Any]

    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def pages(self) -> tuple[str, ...]:
        """The submission split at its page markers, in printed order."""
        parts = _PAGE_MARKER.split(self.text())
        # split() yields [preamble, no, of, body, no, of, body, ...]
        bodies = parts[3::3]
        return tuple(body.strip("\n") for body in bodies)


@dataclass(frozen=True)
class Corpus:
    name: str
    root: Path
    manifest: Mapping[str, Any]
    members: tuple[CorpusMember, ...]

    def by_id(self, member_id: str) -> CorpusMember:
        for member in self.members:
            if member.id == member_id:
                return member
        raise KeyError(f"{member_id!r} is not in {self.name}")


def load(name: str) -> Corpus:
    """Load one corpus, or fail naming the issue that builds it.

    `require_path` rather than a bare open: a corpus that has not been generated is a
    written-ahead condition like any other, and a `FileNotFoundError` deep in a helper is the
    kind of failure a later reader "fixes" by deleting the assertion.
    """
    root = CORPUS_ROOT / name
    manifest_path = require_path(
        root / "manifest.json", f"{name} manifest", issue=CORPORA_ISSUE
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    members = tuple(
        CorpusMember(
            id=entry["id"],
            path=root / entry["path"],
            content_hash=entry["content_hash"],
            attributes={
                k: v for k, v in entry.items() if k not in ("id", "path", "content_hash")
            },
        )
        for entry in manifest["submissions"]
    )
    return Corpus(name=name, root=root, manifest=manifest, members=members)


def reference_package() -> Mapping[str, Any]:
    path = require_path(
        CORPUS_ROOT / "package" / "reference-package.json",
        "the reference package",
        issue=CORPORA_ISSUE,
    )
    return json.loads(path.read_text(encoding="utf-8"))


def materialize_pages(member: CorpusMember, dest: Path) -> tuple[Path, ...]:
    """Write one submission out as separate page files and return them in printed order.

    The returned order is the printed order, never `dest.iterdir()`. A helper that handed back
    directory order would put the thing `FR-INGEST-06` forbids inside the fixture the
    requirement is tested with.
    """
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for index, page in enumerate(member.pages(), start=1):
        path = dest / f"page-{index:02d}.md"
        path.write_bytes((page.rstrip("\n") + "\n").encode("utf-8"))
        written.append(path)
    return tuple(written)


def graphic_pages() -> Sequence[CorpusMember]:
    return load("F-GRAPHIC").members


def stats_cases() -> list[Mapping[str, Any]]:
    corpus = load("F-STATS")
    return [json.loads(member.text()) for member in corpus.members]
