"""`WorkUnit`, where its text came from, and `compute_work_id`, its content address."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


# --- the WorkUnit type (design v1.5 note) ------------------------------------------------------


@dataclass(frozen=True)
class WorkUnit:
    """One unit of work (§3.7).

    The field list is exactly the design note's: `work_id`, `run_id`, `stage`,
    `student_ref`, `student_name`, `submission_id`, `criterion_id`, `submission_text`,
    `judge` (None for a deterministic unit) and `attempt`.

    **`student_name` is on the unit deliberately** (§3.7): the pseudonymization boundary
    is at **assembly** (`M-JUDGE`), not at the ledger. A unit carrying only `student_ref`
    would make `TC-PROV-21`, `SEC-04` and `TC-PROV-C13` unfalsifiable — they would pass
    against an assembler that copies every field it is given. The name travels on the unit
    so those cases can assert the assembled payload drops it.

    **`student_name` and `submission_text` are None on enumerated units.** The ledger row
    carries none of it — Tier C's tables hold `student_ref`, and text lives in the
    documents — so enumeration returns units with these unresolved; the lease surface
    (#58, `FR-ORCH-04`) resolves them from the store before handing a unit to a worker.
    None, not an empty string: None is visible ("not resolved yet"), an empty string is
    the silent-failure shape. Neither field is a `work_id` input, so resolving them later
    cannot fork the work-ID space.
    """

    work_id: str
    run_id: str
    stage: str
    student_ref: str
    student_name: str | None
    submission_id: str
    criterion_id: str | None
    submission_text: str | None
    judge: str | None
    attempt: int = 0


@dataclass(frozen=True)
class UnitProvenance:
    """Where one unit's text came from: unit, then submission, then document (#223).

    Design §3.7's `WorkUnit` field list is closed, so the join is a lookup over the
    submission row rather than a field on the unit. The record carries identifiers only —
    no `student_ref`, `student_name` or text — so reading provenance widens nothing the
    ledger exposes; the pseudonymization boundary stays at assembly (`M-JUDGE`).

    `document_id` is the document the unit's text **came from**. Once the unit has been
    extracted, that is the document its evidence rows name (`read_from_evidence` is True),
    even if the submission was re-transcribed since. Before extraction it is the
    submission's current document, the row extraction will read. `current_document_id` is
    always the head of `M-INGEST`'s ordering; the two differ exactly when a re-transcription
    superseded the text a finished unit read. `document_ids` lists every document of the
    submission, oldest first. `hops` is the join as it was followed, one entry per table
    (with an `evidence:` hop when the evidence decided), so the trace shows the path.
    """

    work_id: str
    run_id: str
    stage: str
    submission_id: str
    document_id: str
    content_hash: str
    current_document_id: str
    read_from_evidence: bool
    document_ids: tuple[str, ...]
    hops: tuple[str, ...]


# --- the work-ID scheme (FR-ORCH-01) -----------------------------------------------------------


#: `FR-ORCH-01`'s nine inputs, in the requirement's own order. `compute_work_id` hashes
#: them in this order, and `TC-REG-06`'s committed reference population declares the same
#: order (`work-id-reference.inputs.json`); the two are kept visually adjacent on purpose.
WORK_ID_INPUTS: tuple[str, ...] = (
    "run_id",
    "stage",
    "submission_id",
    "criterion_id",
    "judge_id",
    "package_version_id",
    "panel_config",
    "prompt_template_version",
    "extractor_version",
)


def _row_evaluation_mode(criterion: Any) -> str:
    """One criterion row's declared evaluation mode (FR-PKG-22, FR-ORCH-35).

    Read from the column, with the shape default only for a row that predates the column
    — a package file migrated to version 11 always carries it, so the fallback covers the
    in-memory catalogue doubles rather than any stored package. `kind = 'mcq'` is NOT a
    test any consumer may make: the equivalence it encoded was retired with the column,
    because a judged multiple-choice criterion is a package the design allows and that
    test makes unrepresentable.
    """
    try:
        declared = criterion["evaluation_mode"]
    except (KeyError, IndexError, TypeError):
        declared = getattr(criterion, "evaluation_mode", None)
    if declared:
        return str(declared)
    try:
        kind = criterion["kind"]
    except (KeyError, IndexError, TypeError):
        kind = getattr(criterion, "kind", None)
    return "deterministic" if kind == "mcq" else "judged"


def _encode_field(value: str | None) -> bytes:
    """The canonical bytes for one `work_id` input.

    **The encoding `M-ORCH` chose where §3.7 is silent** (recorded on the #57 PR, and the
    migration note `TC-REG-06`'s grounds require): each field is encoded as a **type tag
    plus a decimal byte length plus the UTF-8 bytes**, and the nine encodings are
    concatenated in `WORK_ID_INPUTS` order and sha256'd once.

    - A `str` value encodes as ``S<len>:<utf-8 bytes>`` (e.g. ``S7:RUN-0001``).
    - `None` encodes as ``N`` — the deterministic-unit judge (`judge_id=None`), distinct
      from every string by tag, so no judge id can collide with the null judge and no
      separator-guessing is ever needed.

    Length-prefixed concatenation is canonical and unambiguous where a delimiter is not:
    ``("a", "bc")`` and ``("ab", "c")`` encode differently, which a join with any
    separator — including one as exotic as ``\\x1f`` — cannot promise across arbitrary
    field values. The tag is what makes the null-judge sentinel unforgeable rather than a
    string no real judge is likely to be named.

    A change to this encoding changes every `work_id` at once. That is the correct effect
    — it is the encoding, not the data, that moved — but it must be a conscious act with
    the migration note `TC-REG-06`'s grounds demand, never a side effect.
    """
    if value is None:
        return b"N"
    data = value.encode("utf-8")
    return b"S" + str(len(data)).encode("ascii") + b":" + data


def compute_work_id(
    *,
    run_id: str,
    stage: str,
    submission_id: str,
    criterion_id: str | None,
    judge_id: str | None,
    package_version_id: str,
    panel_config: str,
    prompt_template_version: str,
    extractor_version: str,
) -> str:
    """The content hash that identifies one unit of work (FR-ORCH-01).

    ``sha256`` over the nine named inputs, in `WORK_ID_INPUTS` order, under
    `_encode_field`'s canonical encoding; returned as the 64-character lowercase hex
    digest (`work_id` is a TEXT primary key in the ledger).

    Changing **any** input changes the id, which is what makes invalidation automatic
    (NFR-EXTRACT-02/03): a superseded document, a new prompt template version or a
    changed panel produces new units rather than a cleanup job. The arguments are
    keyword-only so a caller cannot transpose `criterion_id` and `judge_id` and silently
    address the wrong unit. `criterion_id` and `judge_id` admit None (a unit need not
    carry either); every other input is a string.

    Pure and total: no clock, no environment, no I/O — `NFR-ORCH-05`'s determinism is a
    property of the function alone, which is why the oracle is byte-identical `work_id`
    sets across two whole enumerations rather than a count.
    """
    values = {
        "run_id": run_id,
        "stage": stage,
        "submission_id": submission_id,
        "criterion_id": criterion_id,
        "judge_id": judge_id,
        "package_version_id": package_version_id,
        "panel_config": panel_config,
        "prompt_template_version": prompt_template_version,
        "extractor_version": extractor_version,
    }
    digest = hashlib.sha256()
    for name in WORK_ID_INPUTS:
        digest.update(_encode_field(values[name]))
    return digest.hexdigest()
