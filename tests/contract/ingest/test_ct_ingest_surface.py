"""`CT-INGEST-01` — the sole entry point from PDF to text (`TC-INGEST-C01`).

Case `TC-INGEST-C01` (P0), test plan §6.11.5; issue #49 (TS-62). `Written ahead of
implementation: yes` is stale — #36..#42 landed `M-INGEST`; the suite is green by
design.

The clause's audit claim is a **cardinality claim about the whole source tree**:
exactly one module turns a PDF into text. The FR case (`TC-INGEST-01`,
tests/integration/ingest/test_ingest_gateway.py) scans the three shipped modules
with substring markers; the clause case holds the stronger form — a parse (AST)
over every `.py` under the scanned roots, which is the only form that survives
the two evasions a substring top-level scan cannot see:

- a module in a **subpackage** (`aeh/utils/render.py`) never enters
  `Path("src", "aeh").glob("*.py")`;
- a **lazy import** (`import pypdfium2` inside a method — exactly how
  `aeh.ingest`'s own live rasterizer imports, so the double standard would also
  hide a second copy of the same trick) sits inside a function body; the AST
  walk visits it, a module-level import list does not.

Discriminator: a second decoding module anywhere in the tree turns this red while
every FR-* case stays green — the FR sweep's file set and the substring match are
both narrower than the clause's claim. The interface half (no entry point takes a
path; document intake is content-addressed) is asserted by reflection over the
`aeh.*` modules the process imports — all four shipped modules, every one the
suite exercises — and statically at the module's own body: the gateway reads no
filesystem path at all — every PDF byte enters through the blob seam.
Disclosed scope of the reflection: it sees module-level callables only, so a
path-taking CLASS entry point, or a module imported nowhere in the process
(`aeh.setup` today — verified), would not enter this sweep; the clause's real
carrier for those is the AST walk above plus the static no-path body check.

Rung note: the plan names rung 0 for the static halves and rung 3 for the
headless full-system journey (console → orchestrator → ingest). `M-CONSOLE` and
`M-ORCH` do not exist yet (issues #59..#66, #123..#130); the achievable half is
the ingest side, which every behavioural case in this suite drives headlessly —
`Ingestor.ingest_submission` returns a structured `IngestReport` with per-gate
fields and needs no console. The end-to-end journey is deferred with disclosure,
keyed on those stories.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import aeh.ingest as ingest_module
from aeh.ingest import Ingestor
from tests.contract.ingest._doubles import ISSUE

pytestmark = pytest.mark.contract

#: The roots a PDF-or-image decoder would import, boundary-matched (so
#: `pypdfium2_helpers` is not read as `pypdfium2` and `pypdf` does not match
#: inside `pypdfium2`'s segment list). The FR case's marker tuple, widened into
#: module roots for the AST walk.
PDF_IMAGE_ROOTS: frozenset[str] = frozenset({
    "pypdfium2", "pdfminer", "fitz", "pypdf", "pdf2image", "PyPDF2",
    "imageio", "PIL", "pikepdf", "pdfplumber", "pymupdf",
})

#: Method names that read or write BINARY content by path — PDF/image intake or
#: output. The gateway's every byte enters through the blob seam (`blobs.get`),
#: so none of these may appear in the module's body.
BINARY_PATH_CALLS: frozenset[str] = frozenset({
    "open", "read_bytes", "write_bytes",
})

#: The one sanctioned text-file read: `assemble_canonical_markdown` accepts page
#: TRANSCRIPTS as paths ("file paths or any object `str()`/`read_text` can
#: read") — already-decoded text, not PDF intake. A `read_text` outside that
#: pure seam is a second intake the clause forbids.
SANCTIONED_READ_TEXT_FUNCTION = "assemble_canonical_markdown"

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _source_files() -> list[tuple[str, Path]]:
    """Every importable module under `src/`, with its dotted name — the same
    stem rule `tests.support.import_graph` applies (a non-identifier stem names
    no node in the import graph and is reported by that helper's own gate).
    `src/aeh/` IS the `aeh` package (`src` is the path entry), so the relative
    path already spells the dotted name."""
    found: list[tuple[str, Path]] = []
    root = _REPO_ROOT / "src"
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.relative_to(root).parts)
        parts[-1] = parts[-1][: -len(".py")]
        if parts and not parts[-1].isidentifier():
            continue
        found.append((".".join(parts), path))
    return found


def _imports_of(tree: ast.AST) -> list[str]:
    """Every module name an import statement in `tree` names — static and lazy
    alike: `ast.walk` descends into function bodies, which is where
    `aeh.ingest`'s own live imports live."""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def _boundary_hits(dotted: str, roots: frozenset[str]) -> list[str]:
    segments = dotted.split(".")
    return [root for root in roots
            if segments[: len(root.split("."))] == root.split(".")]


def test_tc_ingest_c01_pdf_decoding_imports_live_only_in_m_ingest():
    """`TC-INGEST-C01` step 1 — the import graph over the WHOLE tree: the set of
    modules holding a PDF/image-decoder import is exactly {aeh.ingest}. The lazy
    imports are the point: they are how the shipped module itself imports, so a
    second copy of the same pattern in any other module must be caught by the
    same walk that tolerates the first."""
    holders: dict[str, list[str]] = {}
    for module, path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for dotted in _imports_of(tree):
            hits = _boundary_hits(dotted, PDF_IMAGE_ROOTS)
            if hits:
                holders.setdefault(module, []).extend(hits)
    assert set(holders) == {"aeh.ingest"}, (
        f"TC-INGEST-C01: PDF/image decoding exists outside M-INGEST: {holders}. "
        "The gateway is the sole route from PDF to text (CT-INGEST-01) — a second "
        "decoding module is the clause's named break, not a style matter."
    )
    # The claim is about cardinality, so it must fail the empty case too: the
    # holder set is non-empty because the live rasterizer and sanitizer are in it.
    assert holders["aeh.ingest"], (
        "TC-INGEST-C01: aeh.ingest carries no decoder import — the scan is "
        "vacuous, which is a broken walker, not a passing clause."
    )


def test_tc_ingest_c01_no_entry_point_takes_a_path_and_intake_is_content_addressed():
    """`TC-INGEST-C01` step 2 — the interface half. Reflected: no public callable
    of any `aeh` module names a path-like parameter, and the gateway's document
    intake parameters are `blobs` (content-addressed hashes). Static over the
    module body: `aeh.ingest` reads no path at all — its every byte enters
    through `blobs.get`."""
    import aeh
    import aeh.pkg as pkg_module
    import aeh.store as store_module

    modules = [pkg_module, store_module, ingest_module]
    for name in dir(aeh):
        submodule = getattr(aeh, name)
        if inspect.ismodule(submodule) and submodule.__name__.startswith("aeh."):
            modules.append(submodule)
    forbidden_names = {"path", "pdf", "image", "filepath", "pdf_path",
                       "image_path", "file_path"}
    offenders: list[str] = []
    for module in modules:
        for attr, obj in vars(module).items():
            if attr.startswith("_") or not callable(obj) or inspect.isclass(obj):
                continue
            if getattr(obj, "__module__", "") != module.__name__:
                continue
            try:
                parameters = inspect.signature(obj).parameters
            except (TypeError, ValueError):
                continue
            hits = [parameter for parameter in parameters
                    if parameter.lower() in forbidden_names]
            if hits:
                offenders.append(f"{module.__name__}.{attr}{hits}")
    assert not offenders, (
        f"TC-INGEST-C01: entry points accepting a path/image argument: {offenders}. "
        "Downstream stages receive a document_id and read document.markdown."
    )
    for method in (Ingestor.ingest_document, Ingestor.ingest_submission):
        parameters = inspect.signature(method).parameters
        intake = [name for name in parameters if name.lower() in ("blobs",
                                                                  "sources")]
        assert intake, (
            f"TC-INGEST-C01: {method.__name__} takes no blob-hash intake "
            f"parameter (parameters: {tuple(parameters)}) — the gateway's inputs "
            "are content-addressed blob hashes."
        )
    # A correction names its replacement pages the same way: the replacement is
    # a blob-hash reference, not a path.
    from aeh.ingest import PageReplacement

    assert tuple(PageReplacement.__dataclass_fields__) == ("blob_hash",
                                                           "page_no"), (
        "TC-INGEST-C01: a replacement page is no longer (blob_hash, page_no) — "
        "correction intake has left the content-addressed seam."
    )
    # The module body reads no binary path: no `open()` / `read_bytes()` call —
    # and every `read_text()` sits inside the pure assembly seam (transcript
    # files, already-decoded text), never elsewhere.
    tree = ast.parse(
        (_REPO_ROOT / "src" / "aeh" / "ingest.py").read_text(encoding="utf-8"))
    seam = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) \
                and node.name == SANCTIONED_READ_TEXT_FUNCTION:
            seam = (node.lineno, node.end_lineno)
    assert seam is not None, (
        "TC-INGEST-C01: the pure assembly seam vanished — the walker's "
        "sanctioned-read-text rule is vacuous."
    )
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else None)
        if name in BINARY_PATH_CALLS:
            offenders.append(f"line {node.lineno}: {name}()")
        elif name == "read_text" and not seam[0] <= node.lineno <= seam[1]:
            offenders.append(f"line {node.lineno}: read_text() outside the "
                             "assembly seam")
    assert not offenders, (
        f"TC-INGEST-C01: aeh.ingest touches the filesystem outside the blob "
        f"seam: {offenders}. Every PDF byte enters through `blobs.get`; the one "
        "sanctioned text read is the pure seam's transcript intake."
    )
