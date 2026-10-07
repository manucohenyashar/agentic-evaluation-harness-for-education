"""Building an extraction request from one work unit, and reading the canonical document."""

from __future__ import annotations

import hashlib
from typing import Any, Sequence

from aeh.ingest import INGEST_STATEMENTS
from aeh.ingest.identity import redact_identity_head
from aeh.orch import _cohort_keys_on_filesystem
from aeh.pkg import PackageCatalog

from .schema import EXTRACT_STATEMENTS
from .settings import DEFAULT_EVIDENCE_TYPE
from .records import Criterion, _dependency_entry, ExtractionRequest, _question_of, SubmissionRef


#: Per-store memo of the pinned criteria (#516, CT-PKG-15: a package version is loaded once
#: per run, not once per unit). Keyed by the store object's identity, and holding the store
#: itself so the id is never reused while the entry lives. A published version is immutable,
#: so a cached entry never goes stale.
_PINNED_CRITERIA: dict[int, tuple[Any, dict[tuple[str, str, str], Any]]] = {}


def _pinned_criterion(store: Any, package_id: str, version: str, criterion_id: str
                      ) -> tuple[str, str, dict[str, str] | None] | None:
    held = _PINNED_CRITERIA.get(id(store))
    if held is None or held[0] is not store:
        if len(_PINNED_CRITERIA) >= 8:
            _PINNED_CRITERIA.clear()
        held = (store, {})
        _PINNED_CRITERIA[id(store)] = held
    memo = held[1]
    key = (package_id, version, criterion_id)
    if key not in memo:
        prefix = (package_id, version)
        if not any(k[:2] == prefix for k in memo):
            catalog = PackageCatalog(store.package(package_id), package_id=package_id)
            questions = {str(row.get("question_id") or ""): row
                         for row in catalog.questions(version)}
            for row in catalog.criteria(version):
                memo[(package_id, version, str(row.get("criterion_id")))] = (
                    _criterion_parts(catalog, row, questions))
        memo.setdefault(key, None)
    return memo[key]


def _criterion_parts(catalog: Any, criterion: Any, questions: dict[str, Any]
                     ) -> tuple[str, str, dict[str, str] | None]:
    parts: list[str] = []
    if criterion.get("construct_tag"):
        parts.append(f"construct: {criterion['construct_tag']}")
    bands = [f"{row['band']}: {row.get('descriptor') or ''}".rstrip(": ").rstrip()
             for row in catalog.bands(str(criterion.get("criterion_id")))]
    if bands:
        parts.append("bands: " + "; ".join(bands))
    evidence_type = str(criterion.get("evidence_type") or DEFAULT_EVIDENCE_TYPE)
    question = None
    row = questions.get(str(criterion.get("question_id") or ""))
    if row is not None and (row.get("prompt_text") or row.get("reference_solution")):
        question = {"prompt_text": str(row.get("prompt_text") or ""),
                    "reference_solution": str(row.get("reference_solution") or "")}
    return "\n".join(parts), evidence_type, question


def _criterion_of_run(store: Any, work_id: str, criterion_id: str
                      ) -> tuple[str, str, dict[str, str] | None]:
    """The criterion as the unit's run pinned it, in the form the extractor needs (CT-PKG-01,
    CT-PKG-06): its wording (what it measures and each band's descriptor, in ordinal order), its
    `evidence_type`, and its question's prompt and reference solution when the version declares
    one.

    It is read through `PackageCatalog` from the run's own package version, so a later draft cannot
    change a running unit's request. A unit whose run is not in the store keeps the empty criterion
    (the storeless path)."""
    version_row = None
    for key in _cohort_keys_on_filesystem(store):
        rows = store.cohort(key).query(
            EXTRACT_STATEMENTS["select_unit_run_version"], work_id=work_id)
        if rows:
            version_row = rows[0]
            break
    if version_row is None:
        return "", "", None
    pinned = _pinned_criterion(store, str(version_row["package_id"]),
                               str(version_row["package_version_id"]), criterion_id)
    return pinned if pinned is not None else ("", "", None)


def _current_document(store: Any, submission_id: str) -> Any:
    """The submission's current document row, read from the ledger files.

    Current = the head of `select_document_head`'s ordering (`created_at`,
    `document_id`) — the same ordering `M-INGEST` defines, so a superseding
    re-transcription is the row extraction reads (`TC-EXTRACT-12`). Discovery walks
    the cohort files with the orchestrator's own function — one definition of "where
    are the ledgers", consumed rather than re-spelled.
    """
    for key in _cohort_keys_on_filesystem(store):
        rows = store.cohort(key).query(
            INGEST_STATEMENTS["select_document_head"], submission_id=submission_id
        )
        if rows:
            return rows[-1]
    raise ValueError(
        f"submission {submission_id!r} has no document row in any cohort ledger — "
        f"extraction cannot resolve a transcript for a submission that was never "
        f"ingested"
    )


def document_bytes(store: Any, head: Any) -> bytes:
    """The bytes of the submission's canonical document; span offsets are byte positions into these
    (FR-EXTRACT-01).

    The head row's `markdown` column is the canonical artifact — `FR-INGEST-04`
    inserts the `document` row carrying the Markdown its `content_hash` was hashed
    over, and the blob store's declared inventory (`FR-STORE-06`) is source PDFs,
    page rasters and image crops, not document text. The content-addressed blob
    named by `content_hash` remains the fallback — the seeded world's form
    (`tests/support/orch_run.py`'s `seed_document` puts the bytes and stores only
    the hash) — so a row whose column is empty still resolves. The hash must equal
    the bytes actually read either way (`CT-INGEST-02`'s
    immutability from the consumer's side; `M-INTEG`'s `_document_bytes`
    established the rule), and a row that satisfies neither source raises
    `ValueError` — an unaddressable transcript, never a silent empty one.
    """
    stored_hash = head["content_hash"] if hasattr(head, "__getitem__") else None
    raw: "bytes | None" = None
    markdown = head["markdown"] if hasattr(head, "__getitem__") else None
    if isinstance(markdown, str) and markdown:
        raw = markdown.encode("utf-8")
    elif isinstance(stored_hash, str) and stored_hash and store is not None:
        try:
            data = store.blobs().get(stored_hash)
        except KeyError as error:
            raise ValueError(
                f"document {head['document_id']} resolves neither a markdown "
                f"column nor a blob for its content_hash — the transcript cannot "
                f"be addressed"
            ) from error
        if isinstance(data, (bytes, bytearray)):
            raw = bytes(data)
    if not isinstance(raw, bytes):
        raise ValueError(
            f"document {head['document_id']} carries no markdown and no readable "
            f"blob — the transcript cannot be addressed"
        )
    if not isinstance(stored_hash, str) or (
            hashlib.sha256(raw).hexdigest() != stored_hash):
        raise ValueError(
            f"document {head['document_id']}'s content_hash does not match the "
            f"bytes read — a superseded or stale pairing, never a stale acceptance "
            f"(CT-INGEST-02)"
        )
    return raw


def assemble_request(
    unit: Any,
    *,
    dependency_evidence: Sequence[Any] | None = None,
    question: Any = None,
    store: Any = None,
) -> ExtractionRequest:
    """Build the `ExtractionRequest` for one work unit (design §3.8).

    Pure with respect to the model: no provider call, no prompt render. The inputs
    beyond the unit are the two the §3.8 shape needs that a shipped `WorkUnit` has no
    source for — the caller-resolved parent spans (`dependency_evidence`, checked
    against the spans-only schema) and the assignment's `question`. The transcript is
    resolved HERE (the assembler's act at dispatch): the unit's `submission_text`
    when set, else the submission's current document through the `store` keyword.

    Raises `TypeError` for a non-unit argument and `ValueError` for a request that
    cannot be addressed (missing ids, an unresolvable transcript) or a dependency
    entry outside the spans-only schema.
    """
    work_id = getattr(unit, "work_id", None)
    submission_id = getattr(unit, "submission_id", None)
    criterion_id = getattr(unit, "criterion_id", None)
    if work_id is None or submission_id is None or criterion_id is None:
        raise TypeError(
            f"assemble_request needs a work unit carrying work_id, submission_id "
            f"and criterion_id; got {type(unit).__name__} "
            f"(work_id={work_id!r}, submission_id={submission_id!r}, "
            f"criterion_id={criterion_id!r})"
        )
    transcript = getattr(unit, "submission_text", None)
    if transcript is None:
        if store is None:
            raise ValueError(
                f"unit {work_id[:12]} carries no submission_text and no store was "
                f"passed to resolve it: the lease resolves identities, the "
                f"assembler the words. Pass `store=` (the transcript resolves from "
                f"the submission's current document) or a resolved unit."
            )
        head = _current_document(store, submission_id)
        transcript = document_bytes(store, head).decode("utf-8")
    text, evidence_type, pinned_question = ("", "", None)
    if store is not None:
        text, evidence_type, pinned_question = _criterion_of_run(
            store, work_id, str(criterion_id))
    # The caller's `question=` wins; otherwise the question the pinned version declares, so
    # the request never tells the extractor both that there is a question and that there
    # is not (#516 review).
    return ExtractionRequest(
        work_id=work_id,
        criterion=Criterion(criterion_id=criterion_id, text=text, evidence_type=evidence_type),
        question=_question_of(question if question is not None else pinned_question),
        dependency_evidence=tuple(
            _dependency_entry(entry)
            for entry in (dependency_evidence or ())
        ),
        # The paper's `Student:` head carries the child's written name; the request
        # carries the resolved ref in its place (NFR-PROV-04, CT-INGEST-23, #620). Spans
        # are parsed against the stored document, never this copy.
        submission=SubmissionRef(
            submission_id=submission_id,
            transcript=redact_identity_head(transcript, getattr(unit, "student_ref", None)),
        ),
    )
