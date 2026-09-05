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

# The adversarial corpora and the F-HAND declaration are TS-02's (§8.1's third blocking item),
# so a missing one names #3 rather than #2 — a reader chasing an absent fixture should land on
# the story that builds it.
ADVERSARIAL_ISSUE = "#3"

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
        """The member split at its page markers, in printed order.

        A member carrying **no** marker is a one-page document, and comes back as one page
        rather than as none. `F-GRAPHIC` is exactly that — one page per element kind, nothing
        to split on — and returning `()` for it would leave `TC-REG-01`'s `F-GRAPHIC` half
        assembling an empty page list, failing for a reason that has nothing to do with
        `FR-INGEST-04` or `-06`.
        """
        text = self.text()
        parts = _PAGE_MARKER.split(text)
        if len(parts) == 1:
            return (text.strip("\n"),)
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


# --- the adversarial corpora (TS-02, issue #3) ----------------------------------------------


def injection_pairs() -> list[tuple[CorpusMember, CorpusMember]]:
    """`F-ADV-INJ` as (benign, injected) pairs, in manifest order.

    Paired here rather than in each case, because `CT-CONFORM-09`'s whole point is that the
    differential has a baseline: *"an unpaired injection test proves nothing about whether the
    injection mattered."* A helper that returned a flat list would let a case iterate the
    injections and forget the twins, which is the shape the clause forbids.

    Raises rather than skipping a member whose `twin_id` names nothing: a pair with a missing
    half is a corpus defect, and returning the injections that happen to have twins would hide
    it behind a smaller-than-expected count nobody checks.
    """
    corpus = load("F-ADV-INJ")
    by_id = {member.id: member for member in corpus.members}
    pairs: list[tuple[CorpusMember, CorpusMember]] = []
    for member in corpus.members:
        if member.attributes.get("injection_kind") is None:
            continue
        twin_id = member.attributes["twin_id"]
        if twin_id not in by_id:
            raise AssertionError(
                f"{member.id} names twin {twin_id!r}, which is not in F-ADV-INJ. "
                f"CT-CONFORM-09's differential has no baseline without it."
            )
        pairs.append((by_id[twin_id], member))
    return pairs


def benign_page_of(injected: CorpusMember) -> str:
    """Reconstruct the injected member's first page as its benign twin's, from the manifest.

    Truncates at the recorded `payload_line` rather than searching for the payload text. Searching
    would pass against a pair whose payload was the empty string — that is, against two identical
    documents wearing a `twin_id` — which is exactly the degenerate corpus the differential must
    not silently accept.
    """
    line = injected.attributes["payload_line"]
    return "\n".join(injected.pages()[0].split("\n")[:line])


def adv_pdf_manifest() -> Mapping[str, Any]:
    """`F-ADV-PDF`'s manifest. There are no committed bytes next to it — §4.7 forbids them."""
    path = require_path(
        CORPUS_ROOT / "F-ADV-PDF" / "manifest.json",
        "the F-ADV-PDF manifest",
        issue=ADVERSARIAL_ISSUE,
    )
    return json.loads(path.read_text(encoding="utf-8"))


def materialize_adv_pdfs(dest: Path, ids: Sequence[str] | None = None) -> dict[str, Path]:
    """Generate the malicious PDFs into `dest` and verify each against its declared digest.

    §4.7: *"`F-ADV-PDF` is generated, not committed as binaries."* So the bytes come from the
    committed generator, and the manifest's digest is what makes that generator's output the same
    thing every time — §4.8's *"generated and reproducible from committed scripts"*.

    The verification is not ceremony. Without it, a generator edited in a way that changed its
    output would hand every downstream security case a *different* fixture from the one the
    manifest describes, and `SEC-05..09` would go on passing against constructs nobody declared.
    """
    from harness.corpora.adv_pdf import build_construct
    from harness.corpora.manifest import content_hash

    dest.mkdir(parents=True, exist_ok=True)
    wanted = set(ids) if ids is not None else None
    written: dict[str, Path] = {}
    for entry in adv_pdf_manifest()["submissions"]:
        if wanted is not None and entry["id"] not in wanted:
            continue
        data = build_construct(entry["id"])
        digest = content_hash(data)
        if digest != entry["content_hash"]:
            raise AssertionError(
                f"{entry['id']} ({entry['construct']}) generated {digest}, but "
                f"fixtures/F-ADV-PDF/manifest.json declares {entry['content_hash']}. The "
                f"generator was edited without rebuilding: run "
                f"`python -m harness.corpora.build`."
            )
        path = dest / Path(entry["path"]).name
        path.write_bytes(data)
        written[entry["id"]] = path

    if wanted is not None and wanted - set(written):
        raise AssertionError(
            f"F-ADV-PDF declares no construct(s) {sorted(wanted - set(written))}"
        )
    return written


def hand_registry() -> Mapping[str, Any]:
    """`F-HAND`'s committed declaration. It contains no student work — see `harness.corpora.hand`."""
    path = require_path(
        CORPUS_ROOT / "F-HAND" / "registry.json",
        "the F-HAND registry",
        issue=ADVERSARIAL_ISSUE,
    )
    return json.loads(path.read_text(encoding="utf-8"))


def stats_cases() -> list[Mapping[str, Any]]:
    corpus = load("F-STATS")
    return [json.loads(member.text()) for member in corpus.members]
