"""Manifests: what a corpus contains, and the hash that says it is still that.

`NFR-CONFORM-01` requires the fixture set to be *"content-addressed and version-pinned, so a
conformance result names exactly which fixtures produced it"*. That requirement is written
about `F-FROZEN`, but a manifest per corpus costs nothing and makes every other corpus
citable the same way, so all of them carry one.

The shape is fixed by `tests/artifact/test_heldout_disjoint.py` (TS-00), which recomputes each
declared hash from the bytes rather than trusting it. Every manifest here therefore has the
same skeleton::

    {
      "corpus": "F-SYNTH",
      "version": "1",
      "seed": 20260101,
      "generator": "harness.corpora.synth",
      "description": "...",
      "submissions": [ {"id": ..., "path": ..., "content_hash": "sha256:..."} , ... ]
    }

`submissions` is the key that test reads, so it is the key every corpus of *documents* uses,
whatever the corpus calls its members in prose. Corpora that are not documents (`F-STATS`
holds label sets) use the same key for the same reason: one reader, one shape.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

# The repo root, from `harness/corpora/manifest.py`.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CORPUS_ROOT = REPO_ROOT / "fixtures"

HASH_PREFIX = "sha256:"


def content_hash(data: bytes) -> str:
    """The declared form of a content hash: `sha256:` plus the hex digest.

    Prefixed rather than bare, because `NFR-CONFORM-01`'s content addressing has to survive an
    algorithm change: an unprefixed digest in a six-month-old conformance record is a value
    nobody can verify once the algorithm moves.
    """
    return HASH_PREFIX + hashlib.sha256(data).hexdigest()


def write_bytes(path: Path, data: bytes) -> str:
    """Write one corpus member and return its declared content hash.

    Bytes rather than text, and every caller encodes with `"\\n"` line endings explicitly.
    Content addressing is over bytes: a platform-dependent newline would give the same corpus
    two different hashes on two different machines, and every disjointness, reproducibility
    and provenance claim built on those hashes would be a claim about the checkout rather than
    about the corpus.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return content_hash(data)


def as_document(text: str) -> bytes:
    """A corpus document as bytes: UTF-8, LF, one trailing newline."""
    body = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return (body + "\n").encode("utf-8")


@dataclass(frozen=True)
class ManifestEntry:
    id: str
    path: str
    content_hash: str
    extra: Mapping[str, Any] | None = None

    def as_json(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "id": self.id,
            "path": self.path,
            "content_hash": self.content_hash,
        }
        if self.extra:
            entry.update(self.extra)
        return entry


def set_content_hash(entries: Iterable[ManifestEntry]) -> str:
    """One digest over the whole corpus: the ordered `(id, content_hash)` pairs.

    `NFR-CONFORM-01` addresses the **set**, not its members: *"the fixture set shall be
    content-addressed and version-pinned, so a conformance result names exactly which fixtures
    produced it."* Per-member hashes cannot do that job — a result citing thirty-six of them is
    citing a list nobody will compare, and a result citing the version *label* is citing a string
    that stays the same when somebody edits a fixture.

    Over `(id, content_hash)` rather than over the bytes, so the digest changes when a member is
    renamed, reordered, added or removed as well as when its content changes. A digest over
    concatenated bytes alone would be identical for two corpora that differ only in which
    submission is called what — and a conformance result is keyed by submission id.
    """
    joined = "\n".join(f"{e.id}\t{e.content_hash}" for e in entries)
    return content_hash(joined.encode("utf-8"))


def fixture_set_id(corpus: str, version: str, digest: str) -> str:
    """The citable identity of a corpus: `F-FROZEN@1+sha256:...`.

    One string, so a conformance result can carry the whole answer to *"which fixtures produced
    this?"* in a single field. The version is in it because `FR-CONFORM-01` requires the set to be
    versioned; the digest is in it because a version alone is a promise rather than a check.
    """
    return f"{corpus}@{version}+{digest}"


@dataclass(frozen=True)
class Manifest:
    corpus: str
    version: str
    seed: int | None
    generator: str
    description: str
    entries: tuple[ManifestEntry, ...]
    extra: Mapping[str, Any] | None = None

    @property
    def set_hash(self) -> str:
        return set_content_hash(self.entries)

    def as_json(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "corpus": self.corpus,
            "version": self.version,
            "seed": self.seed,
            "generator": self.generator,
            "description": self.description,
            # `NFR-CONFORM-01`'s content addressing, at the level the requirement states it.
            "set_content_hash": self.set_hash,
            "fixture_set_id": fixture_set_id(self.corpus, self.version, self.set_hash),
        }
        if self.extra:
            doc.update(self.extra)
        # `submissions` last, so a human opening the file reads the provenance before the
        # 350-entry list rather than after it.
        doc["submissions"] = [e.as_json() for e in self.entries]
        return doc


def serialize_manifest(manifest: Manifest) -> bytes:
    """The manifest's committed bytes.

    `sort_keys=False` deliberately — the key order above is the reading order and is stable
    because it is written out by hand. `ensure_ascii=False` so a corpus carrying non-ASCII
    student text stays legible in a diff rather than becoming escape sequences.
    """
    text = json.dumps(manifest.as_json(), indent=2, ensure_ascii=False, sort_keys=False)
    return (text + "\n").encode("utf-8")


def write_manifest(root: Path, manifest: Manifest) -> Path:
    path = root / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(serialize_manifest(manifest))
    return path


def read_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def entries_from(root: Path, members: Iterable[tuple[str, str, bytes, Mapping[str, Any] | None]]
                 ) -> tuple[ManifestEntry, ...]:
    """Write each member and collect its manifest entry, in the order given.

    Order is the generator's, never the filesystem's — `FR-INGEST-06` forbids directory
    iteration order as an assembly source, and a manifest built by walking a directory would
    reintroduce exactly that dependency one layer up.
    """
    out: list[ManifestEntry] = []
    for member_id, rel_path, data, extra in members:
        digest = write_bytes(root / rel_path, data)
        out.append(ManifestEntry(id=member_id, path=rel_path, content_hash=digest, extra=extra))
    return tuple(out)
