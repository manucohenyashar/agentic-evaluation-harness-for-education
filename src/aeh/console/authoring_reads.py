"""The authoring reads (FR-CONSOLE-50, #755): the intake preview and the draft-structure
read — the one place the redesign lands the new `M-CONSOLE` → `M-AUTHOR` edge (`ADR-45`:
the console drives the authoring library directly, never the CLI).

**The preview** is a POST read: the request's body carries the uploaded documents
themselves, because teacher document content can never travel in a URL or a query string
(`CT-CONSOLE-34`) — and the preview *writes nothing*: each document's bytes go to a
temporary file only for `aeh.author` to open, and nothing is staged into the
blob store, the store, or a log line. The staging endpoint the draft job later reads from
belongs to `draft package from documents` (#760); until it lands, the preview is what the
SPA shows the teacher before any drafting begins, so it drives the library exactly as
the drafting job does, minus the model calls: the extractor for PDFs (text layer only,
the transcription knob off, and a `call` seam that refuses to be used — `FR-AUTHOR-03`
would route any model call through `M-PROV`, and a preview makes none), and the same
intake entry (`intake.normalize_document`) for `.docx` and `.txt` (`FR-CONSOLE-50` /
R5a: the upload invites all three, so the preview reads all three). A file the intake
matrix refuses comes back refused with the matrix's own teacher sentence (`FR-AUTHOR-28`),
never a console paraphrase of it.

**The draft read** answers the current draft as structure — items, grading points, score
levels, and the missing pieces with their locations — never as TOML text (`ADR-45`: the
draft files are the state; the teacher never meets the format).

Payload contracts here are what the SPA builds against and what #754's intake tier must
keep when its `NormalizedDocument` becomes the source: the block, stat and warning shapes
below are the delta's NormalizedDocument summary fields, so the source swap changes no
payload.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from aeh.author.errors import DocumentRefusedError
from aeh.author.extraction import (
    AuthoringDocument,
    AuthoringInputError,
    extract_documents,
)
from aeh.author.intake import NormalizedDocument, normalize_document
from aeh.author import gap_question, missing_points
from aeh.author.report import draft_filename
from aeh.author.validation import PLACEHOLDER_PREFIX, validate_draft

from .package_summary import answered_items, package_summary
from .settings import author_doc_max_bytes


#: The directories a draft may live in, under the data directory: the authoring workspace
#: and, beside the packages it belongs to. Confined globs — an arbitrary path never
#: reaches this module (`CT-CONSOLE-34`'s discipline for teacher content).
_DRAFT_DIRS: tuple[str, ...] = ("authoring", "packages")


_PLACEHOLDER_COMMENT = re.compile(r"#\s*PLACEHOLDER\((.*?)\)\s*:\s*(.*)")


def _no_model_call(*_args: Any, **_kwargs: Any) -> Any:
    """The preview's call seam: never invoked while the transcription knob is off, and a
    loud refusal if the extractor ever tries (a preview performs no inference)."""
    raise AssertionError("the authoring preview read performs no model call.")


# --- the draft-structure read ------------------------------------------------------------------------


def _draft_roots(data_dir: Any) -> list[Path]:
    return [Path(data_dir, name) for name in _DRAFT_DIRS]


def find_draft_for(data_dir: Any, package_id: str) -> Path | None:
    """The draft file a package id names, if one exists in a confined draft directory.
    The id can arrive from a request's query string, so it is treated as attacker-shaped
    (`bundle_file`'s discipline): anything carrying a separator, a drive prefix or a null
    byte names no draft — a draft file lives at `<package_id>.package.draft.toml` inside
    the draft directories, and no id that cannot be a file name can reach one."""
    if not package_id or data_dir is None:
        return None
    identifier = str(package_id)
    if ("/" in identifier or "\\" in identifier or ":" in identifier
            or "\x00" in identifier or identifier.strip(".") == ""):
        return None
    name = draft_filename(identifier)
    for root in _draft_roots(data_dir):
        candidate = Path(root, name)
        if candidate.is_file():
            return candidate
    return None


def find_any_draft(data_dir: Any) -> Path | None:
    """The first draft file under the confined draft directories, in name order — the
    draft the SPA's authoring pages open when no package is named yet."""
    if data_dir is None:
        return None
    for root in _draft_roots(data_dir):
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.package.draft.toml")):
            return path
    return None


def _load_draft(path: Path) -> dict[str, Any] | None:
    """The draft's parsed spec, or `None` when it cannot be read as TOML (a half-written
    draft answers as no draft rather than crashing the page)."""
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None


def _walk_placeholders(value: Any, where: str) -> list[tuple[str, str]]:
    """Every sentinel in the spec, as `(item id, location)` pairs — the location a dotted
    path a teacher can follow through the structure read."""
    found: list[tuple[str, str]] = []
    if isinstance(value, str):
        if value.startswith(PLACEHOLDER_PREFIX):
            item_id = value[len(PLACEHOLDER_PREFIX):].split(">>", 1)[0].strip()
            found.append((item_id, where))
    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(_walk_placeholders(item, f"{where}.{key}" if where else str(key)))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_walk_placeholders(item, f"{where}[{index}]"))
    return found


def _placeholder_notes(raw_text: str, item_id: str) -> tuple[str, str]:
    """The reason and the supply named in the `# PLACEHOLDER(...)` comment above a
    sentinel's line, as the renderer wrote them; empty strings when the comment is gone
    (a hand-edited draft), which the structure still shows honestly."""
    marker = f"<<PLACEHOLDER: {item_id}>>"
    lines = raw_text.splitlines()
    for index, line in enumerate(lines):
        if marker not in line:
            continue
        for above in reversed(lines[max(0, index - 4):index]):
            match = _PLACEHOLDER_COMMENT.search(above)
            if match:
                return match.group(1).strip(), match.group(2).strip()
    return "", ""


def owner_qid(spec: dict[str, Any], where: str) -> str | None:
    """The question a sentinel at `where` (`question[1].model_answer`, `criterion[2].key`)
    stands in, or `None` for a package-level field."""
    match = re.match(r"(question|criterion)\[(\d+)\]", where)
    if match is None:
        return None
    blocks = spec.get(match.group(1))
    index = int(match.group(2))
    if not isinstance(blocks, list) or index >= len(blocks) \
            or not isinstance(blocks[index], dict):
        return None
    block = blocks[index]
    qid = block.get("id") if match.group(1) == "question" else block.get("question")
    return str(qid) if qid is not None else None


def draft_placeholders(path: Path | None) -> int | None:
    """How many missing pieces stand in a draft file, or `None` when there is no readable
    draft there — the context read's stage-3 signal."""
    if path is None:
        return None
    spec = _load_draft(path)
    if spec is None:
        return None
    return len(_walk_placeholders(spec, ""))


def _project_question(question: dict[str, Any]) -> dict[str, Any]:
    """One draft item, as the editor renders it: its id, type, points, text, options and
    model answer — the spec's own words, which are already teacher vocabulary. The labels
    ride an additive map beside the letters (`options` stays the list the read has always
    answered, so no existing consumer's shape changes): the editor shows what an option
    says and can only add or remove one — retitling an option is not an operation the
    structured edit surface carries."""
    raw_options = question.get("options")
    projected: dict[str, Any] = {
        "id": str(question.get("id") or ""),
        "type": str(question.get("type") or ""),
        "points": question.get("points"),
        "text": str(question.get("text") or ""),
        # The letters only, and only when the options are really a table: a placeholder
        # sentinel standing as the whole options table is the draft's own "no options
        # yet" marker, and listing its characters would dress it up as three options.
        "options": sorted(raw_options) if isinstance(raw_options, dict) else [],
        "model_answer": question.get("model_answer"),
    }
    if isinstance(raw_options, dict):
        projected["option_labels"] = {
            str(letter): str(label) for letter, label in raw_options.items()
        }
    return projected


def _project_criterion(criterion: dict[str, Any]) -> dict[str, Any]:
    """One grading point, with its score levels as a name list (`ADV-15`: the scale
    travels as names and their descriptors, never under a key the blind-sample arm scans
    for)."""
    bands = criterion.get("bands")
    projected: dict[str, Any] = {
        "id": str(criterion.get("id") or ""),
        "question": str(criterion.get("question") or ""),
        "points": criterion.get("points"),
        "score_method": criterion.get("score_method"),
        "component_of": criterion.get("component_of"),
        "score_levels": [
            {
                "name": str(band.get("name") or ""),
                "points": band.get("points"),
                "descriptor": str(band.get("descriptor") or ""),
            }
            for band in (bands or ())
            if isinstance(band, dict)
        ],
    }
    if criterion.get("key") is not None:
        projected["key"] = criterion.get("key")
    return projected


def authoring_draft_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The current draft as structure (FR-CONSOLE-50): the items, the grading points, the
    grades table, and every missing piece with its location, reason and what to supply —
    with `aeh.author`'s own validation issues beside them. Never the TOML text. A console
    with no draft answers `draft: None`."""
    del console
    data_dir = getattr(app._store, "data_dir", None)
    package_id = str((query or {}).get("package_id") or "").strip()
    path = find_draft_for(data_dir, package_id) if package_id else find_any_draft(data_dir)
    # The upload ceiling rides every answer (`CT-CONSOLE-36`): the SPA enforces the same
    # bound client-side, with the same teacher sentence, so the knob's value in force
    # travels with the read rather than being copied into the bundle.
    doc_max_bytes = author_doc_max_bytes()
    if path is None:
        return {"draft": None, "doc_max_bytes": doc_max_bytes,
                "projected": {"items": 0, "criteria": 0,
                              "placeholders": 0, "issues": 0}}
    spec = _load_draft(path)
    if spec is None:
        return {"draft": None, "doc_max_bytes": doc_max_bytes,
                "projected": {"items": 0, "criteria": 0,
                              "placeholders": 0, "issues": 0}}
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError:
        raw_text = ""
    placeholders = [
        {
            "item_id": item_id,
            "location": where,
            "reason": reason,
            "supply": supply,
            # The teacher's side (FR-AUTHOR-31): the screen shows these, never `reason`.
            **gap_question(item_id, spec, owner_qid(spec, where)).as_fields(),
        }
        for item_id, where in _walk_placeholders(spec, "")
        for reason, supply in [_placeholder_notes(raw_text, item_id)]
    ]
    # A question's missing points stand in no sentinel (a report-only gap), yet the test's
    # total waits on them (FR-AUTHOR-32): they are asked beside the placeholders, in a
    # list of their own so the placeholder count keeps its meaning.
    points_questions = [
        {"item_id": item_id, **gap_question(item_id, spec).as_fields()}
        for item_id in missing_points(spec)
    ]
    issues = validate_draft(spec)
    issue_rows = [
        {"field": issue.field, "message": issue.message} for issue in issues
    ]
    # The draft's tables are `[[question]]` and `[[criterion]]` (singular, the grammar
    # `render_draft` writes and the edit surface reads) — a plural key here reads an
    # empty list and the editor and review outline would render a draft with no entries.
    questions = [item for item in (spec.get("question") or ()) if isinstance(item, dict)]
    criteria = [item for item in (spec.get("criterion") or ()) if isinstance(item, dict)]
    package_id = path.name.removesuffix(".package.draft.toml")
    return {
        "draft": {
            "package_id": package_id,
            "file_name": path.name,
            "package": spec.get("package"),
            "approved_by": spec.get("approved_by"),
            "items": [_project_question(question) for question in questions],
            "criteria": [_project_criterion(criterion) for criterion in criteria],
            "grades": spec.get("grades"),
            "placeholders": placeholders,
            "points_questions": points_questions,
            "issues": issue_rows,
            "missing_pieces": len(placeholders),
            # FR-CONSOLE-72: the package as it would be published, answers merged in.
            "summary": package_summary(spec, answered_items(path, package_id)),
        },
        "doc_max_bytes": doc_max_bytes,
        "projected": {
            "items": len(questions),
            "criteria": len(criteria),
            "placeholders": len(placeholders),
            "issues": len(issues),
        },
    }


# --- the intake preview read (POST) ---------------------------------------------------------------------

#: The formats the preview reads in full (`FR-CONSOLE-50` / R5a): the upload input
#: invites `.docx`, `.txt` and `.pdf`, the library's intake normalizes all three, and
#: the drafting job drafts all three — so the preview reads all three. Anything else
#: routes through intake's envelope too, whose matrix (`FR-AUTHOR-28`) refuses it with
#: the teacher's sentence — a legacy `.doc` gets its save-as-`.docx` row, a renamed
#: file its mismatch row — so the console keeps no suffix refusal of its own.
_SUPPORTED_SUFFIXES = frozenset({".pdf", ".docx", ".txt"})


def _refusal(name: str, detail: str, next_action: str) -> dict[str, Any]:
    """One file the preview could not read, in the teacher's words with the next step
    (`CT-CONSOLE-33`): a refusal carries both, never an exception name or a format code."""
    return {
        "name": name,
        "accepted": False,
        "refusal": {"detail": detail, "next_action": next_action},
    }


def _preview_document(name: str, data: bytes) -> dict[str, Any]:
    """One accepted document's summary — its blocks, its stats, its warnings — or its
    refusal. A `.pdf` is read through `aeh.author`'s extractor, text layer only; a
    `.docx` or `.txt` through the library's own intake entry, the same normalization
    the drafting job runs. Neither path makes a model call."""
    from tempfile import TemporaryDirectory

    if len(data) > author_doc_max_bytes():
        limit_mb = author_doc_max_bytes() / (1024 * 1024)
        return _refusal(
            name,
            f"That file is larger than the {limit_mb:g} MB limit for one document.",
            "Split the document or export fewer pages, then upload it again.",
        )
    with TemporaryDirectory(prefix="aeh-preview-") as tmp:
        staged = Path(tmp, Path(name).name or "document")
        staged.write_bytes(data)
        if staged.suffix.lower() == ".pdf":
            try:
                (document,) = extract_documents(
                    [staged], transcriber=None, call=_no_model_call, transcribe_enabled=False,
                )
            except AuthoringInputError:
                # FR-AUTHOR-13's own refusal: the file is a valid document but every page
                # carries no machine-readable text — the photographed-papers case, whose
                # honest preview is this refusal with the truthful next step. The draft job
                # reads such pages aloud (the transcriber, a model call a read never makes);
                # telling the teacher to re-upload the same file would be advice that fails
                # the same way twice.
                return _refusal(
                    name,
                    "The pages of this file carry no machine-readable text — it is likely "
                    "photographs of the test rather than a saved document.",
                    "You can still upload it: making the draft will read photographed pages "
                    "aloud. Or upload a PDF saved straight from a document, which this "
                    "preview reads in full.",
                )
            except Exception:  # noqa: BLE001 — one unreadable file is that file's refusal
                return _refusal(
                    name,
                    "The pages of this file could not be read.",
                    "Check the file opens on your computer, then upload it again.",
                )
            return _project_document(document)
        # Every other kind goes through the library's intake entry (`FR-CONSOLE-50` /
        # R5a: `.docx` and `.txt` first-class, the same normalization the draft job
        # runs — no extractor, no model). A file the intake matrix refuses raises
        # `DocumentRefusedError` carrying the matrix's own teacher sentence
        # (`FR-AUTHOR-28`), which the console renders as-is.
        try:
            normalized = normalize_document(staged, max_bytes=author_doc_max_bytes())
        except DocumentRefusedError as refused:
            # The matrix sentence carries its own next step when one is needed
            # (FR-AUTHOR-28: `next_step` only "when the sentence does not already carry
            # one"), so the console adds nothing of its own.
            return _refusal(name, refused.sentence, refused.next_step)
        except Exception:  # noqa: BLE001 — one unreadable file is that file's refusal
            return _refusal(
                name,
                "The pages of this file could not be read.",
                "Check the file opens on your computer, then upload it again.",
            )
        return _project_normalized(normalized)


def _project_normalized(document: NormalizedDocument) -> dict[str, Any]:
    """The same summary shape the extractor path projects, for a `.docx` or `.txt`
    intake (`FR-AUTHOR-24`'s representation): the blocks carry their kinds — a table
    is counted and rendered (`TC-AUTHOR-33`), a picture its placeholder — the whole
    file reads as one page, and the warnings are intake's own teacher sentences."""
    blocks = [
        {"kind": block.kind, "ordinal": block.ordinal, "page": 1, "text": block.text}
        for block in document.blocks
    ]
    return {
        "name": document.source_name,
        "accepted": True,
        "pages": 1,
        "blocks": blocks,
        "stats": {
            "page_count": 1,
            "block_count": document.stats.block_count,
            "word_count": document.stats.word_count,
            "table_count": document.stats.table_count,
            "image_count": document.stats.image_count,
        },
        "warnings": [
            {"code": warning.code, "message": warning.message}
            for warning in document.warnings
        ],
    }


def _project_document(document: AuthoringDocument) -> dict[str, Any]:
    """The summary the SPA renders for one document: blocks in page order, the counts the
    editor's preview needs, and the warnings an honest extraction must carry — a page
    with no text layer is named, never silently dropped."""
    blocks: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    words = 0
    for page in document.pages:
        text = page.text.strip()
        if not text:
            warnings.append({
                "code": "page_not_read",
                "message": (
                    f"Page {page.page_no} has no machine-readable text; the page reader "
                    "will be used for it when the draft is made."
                ),
            })
            continue
        blocks.append({
            "kind": "paragraph",
            "ordinal": len(blocks),
            "page": page.page_no,
            "text": text,
        })
        words += len(text.split())
    if document.pages:
        warnings.append({
            "code": "preview_scope",
            "message": "This preview reads the text layer only; tables and pictures are "
                       "not detected yet.",
        })
    return {
        "name": document.name,
        "accepted": True,
        "pages": document.page_count,
        "blocks": blocks,
        "stats": {
            "page_count": document.page_count,
            "block_count": len(blocks),
            "word_count": words,
            "table_count": 0,
            "image_count": 0,
        },
        "warnings": warnings,
    }


def authoring_preview_read(console: Any, app: Any, body: Any) -> dict[str, Any]:
    """What intake made of the uploaded documents, before any drafting (FR-CONSOLE-50):
    one summary or one refusal per file, in the order the request named them. The body is
    the POST read's JSON object: `{"documents": [{"name", "content_base64"}]}`. The read
    writes nothing anywhere — no blob, no store row, no log line carries the bytes."""
    del console, app  # the preview drives the library, not the store
    documents = (body or {}).get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError(
            "the preview read takes the uploaded documents in its body, as "
            '{"documents": [{"name": ..., "content_base64": ...}]}'
        )
    projected: list[dict[str, Any]] = []
    accepted = refused = blocks = 0
    for entry in documents:
        if not isinstance(entry, dict) or not str(entry.get("name") or "").strip():
            projected.append(_refusal(
                "(unnamed file)",
                "One of the uploaded files arrived without a name.",
                "Upload the files again.",
            ))
            refused += 1
            continue
        name = str(entry["name"])
        raw = entry.get("content_base64")
        if not isinstance(raw, str) or not raw.strip():
            projected.append(_refusal(
                name, "That file arrived with no content in it.",
                "Upload the file again."))
            refused += 1
            continue
        import base64

        try:
            data = base64.b64decode(raw, validate=True)
        except (ValueError, TypeError):
            projected.append(_refusal(
                name, "That file's content could not be unpacked.",
                "Upload the file again."))
            refused += 1
            continue
        answer = _preview_document(name, data)
        projected.append(answer)
        if answer["accepted"]:
            accepted += 1
            blocks += len(answer["blocks"])
        else:
            refused += 1
    return {
        "documents": projected,
        "projected": {
            "received": len(documents),
            "accepted": accepted,
            "refused": refused,
            "blocks": blocks,
        },
    }
