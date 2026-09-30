"""Assembling a scoring request from one work unit, with student names pseudonymized."""

from __future__ import annotations

import hashlib
import json
import os
import random
from typing import Any

from aeh.extract import document_bytes
from aeh.ingest import INGEST_STATEMENTS
from aeh.orch import STAGE_EXTRACT, _cohort_keys_on_filesystem
from aeh.pkg import PackageCatalog
from aeh.prov import PromptPayload

from .schema import JUDGE_STATEMENTS
from .settings import _EXEMPLAR_SEED_DEFAULT, EXEMPLAR_SEED_ENV
from .request import (
    BandView,
    CriterionView,
    DependencyEvidence,
    ExemplarView,
    QuestionView,
    ScoringRequest,
    SubmissionView,
)
from .prompt import prompt_fields


# --- the fresh context: assembly from one unit (FR-JUDGE-02/05) ----------------------------------


def _field_of(unit: Any, key: str) -> Any:
    """Read one identity field off a work unit or an arm row — attribute access for a
    `WorkUnit`, key access for a mapping (the contract door's `sqlite3.Row` arms).
    Missing is `None`, not an error: the arms are rows stripped to identity."""
    if hasattr(unit, key):
        value = getattr(unit, key)
        if not callable(value):
            return value
    try:
        return unit[key]
    except (KeyError, IndexError, TypeError):
        return None


def _current_document(store: Any, submission_id: str) -> Any:
    """The submission's CURRENT document row — `aeh.extract`'s own resolver, mirrored:
    the head of `select_document_head`'s ordering over the cohort files discovered with
    the orchestrator's own function (`FR-ORCH-02`, consumed not re-spelled)."""
    for key in _cohort_keys_on_filesystem(store):
        rows = store.cohort(key).query(
            INGEST_STATEMENTS["select_document_head"], submission_id=submission_id
        )
        if rows:
            return rows[-1]
    raise ValueError(
        f"submission {submission_id!r} has no document row in any cohort ledger — "
        f"the scorer cannot resolve the words for a submission that was never ingested"
    )


def _canonical_document_bytes(store: Any, submission_id: str) -> "bytes | None":
    """The submission's canonical document BYTES, resolved through the store's own
    doors — the head document row (`_current_document`) and its canonical text by
    `aeh.extract.document_bytes`' rule (the `markdown` column the gateway wrote,
    the blob fallback, the hash checked against the bytes read).

    Returns `None` on EVERY unresolvable shape — no store bound, no document row, a
    pairing that satisfies neither source, a read that raises — because the citation gate's
    reading of `None` is fail-closed (`FR-INTEG-01`): an unverifiable citation is
    indistinguishable from a forged one and both are refused. This resolves the
    CANONICAL document, never `request.submission_text` (§3.2's assembly pseudonymizes
    the transported copy; the extracted spans' offsets are the canonical document's —
    verifying against the transported copy could shift every offset and refuse a
    legal citation)."""
    if store is None:
        return None
    try:
        head = _current_document(store, submission_id)
        return document_bytes(store, head)
    except Exception:
        return None


def _find_cohort(store: Any, work_id: str) -> Any:
    """The cohort handle that holds `work_id`, by walking the cohort files — the
    no-side-index discovery the extract driver uses (`FR-ORCH-02`)."""
    for key in _cohort_keys_on_filesystem(store):
        cohort = store.cohort(key)
        rows = cohort.query(
            JUDGE_STATEMENTS["select_work_unit"], work_id=work_id
        )
        if rows:
            return cohort
    raise ValueError(
        f"work unit {work_id[:12]} does not exist in any cohort ledger — scoring a "
        f"unit the ledger does not hold would write a verdict with no work-unit row "
        f"beneath it"
    )


def _pseudonymize(text: str, name: Any, ref: Any) -> str:
    """§3.2's pseudonymization at assembly: every occurrence of the roster name in
    submission-derived text becomes the pseudonymous ref. A unit with no name — every
    leased one — is already clean and passes through unchanged."""
    if name and ref and isinstance(name, str) and name in text:
        return text.replace(name, str(ref))
    return text


def _pseudonymized_spans(spans: tuple, name: Any, ref: Any) -> tuple:
    """The same replacement over evidence spans (#593, NFR-PROV-08): a span is a verbatim
    slice of the submission, so a roster name the student wrote travels in its `text` as
    surely as in the transcript. Only `text` changes: the offsets keep indexing the stored
    document, and the citation gate verifies a cited span of this form against it through
    `_verifies_as_pseudonymized`. A span that carries no name is forwarded as the same
    object."""
    out = []
    for span in spans:
        text = span.get("text") if isinstance(span, dict) else None
        if isinstance(text, str):
            clean = _pseudonymize(text, name, ref)
            if clean is not text:
                span = {**span, "text": clean}
        out.append(span)
    return tuple(out)


def _ordered_exemplars(
    exemplars: tuple[ExemplarView, ...], *, question_id: str, criterion_id: str
) -> tuple[ExemplarView, ...]:
    """`FR-JUDGE-08`'s exemplar presentation order: a seeded permutation keyed on
    (question, criterion) and the `HARNESS_JUDGE_EXEMPLAR_SEED` salt.

    Fixed WITHIN a (judge, question, criterion) batch — every submission in the batch
    renders the same exemplar bytes, which is what keeps the invariant prefix one
    value across the batch (`FR-JUDGE-06`) — and differing ACROSS batches, so no
    position bias survives from one criterion's rubric to the next. The salt is read
    at call time (the third seam) and the catalog's exemplar-id order is the
    permutation's base, so an unset salt is still deterministic and a fixture
    recording reproduces exactly."""
    if len(exemplars) < 2:
        return exemplars
    salt = os.environ.get(EXEMPLAR_SEED_ENV) or _EXEMPLAR_SEED_DEFAULT
    digest = hashlib.sha256(
        f"{salt}|{question_id}|{criterion_id}".encode("utf-8")
    ).digest()
    ordered = list(exemplars)
    random.Random(digest).shuffle(ordered)
    return tuple(ordered)


def _rubric_of(
    store: Any, run_row: Any, criterion_id: str
) -> tuple[CriterionView, QuestionView]:
    """The criterion's rubric as the request carries it, through the shipped
    `PackageCatalog` (built with the store's blob store attached, so exemplar material
    resolves): the wording (the criterion's question prompt text — the package's
    criterion rows carry identity, not prose), the declared band set as names,
    ordinals and descriptors, and the criterion's exemplars in `FR-JUDGE-08`'s
    presentation order. A band's points column never leaves the package tier."""
    package_id = run_row["package_id"]
    version = run_row["package_version_id"]
    catalog = PackageCatalog(
        store.package(package_id), package_id=package_id, blobs=store.blobs()
    )
    question_id = ""
    for row in catalog.criteria(version):
        if row.get("criterion_id") == criterion_id:
            question_id = str(row.get("question_id") or "")
            break
    bands = tuple(
        BandView(
            band=str(row["band"]),
            ordinal=int(row["ordinal"]),
            descriptor=str(row.get("descriptor") or ""),
        )
        for row in catalog.bands(criterion_id)
    )
    exemplars = _ordered_exemplars(
        tuple(
            ExemplarView(
                exemplar_id=str(row.get("exemplar_id") or ""),
                band=str(row.get("band") or ""),
                text=catalog.blob_text(row.get("blob_hash")),
            )
            for row in catalog.exemplars(version)
            if str(row.get("criterion_id") or "") == criterion_id
        ),
        question_id=question_id,
        criterion_id=criterion_id,
    )
    prompt_text = ""
    reference_solution = ""
    if question_id:
        for row in catalog.questions(version):
            if str(row.get("question_id") or "") == question_id:
                prompt_text = str(row.get("prompt_text") or "")
                reference_solution = str(row.get("reference_solution") or "")
                break
    return CriterionView(
        criterion_id=criterion_id,
        text=prompt_text,
        bands=bands,
        exemplars=exemplars,
    ), QuestionView(
        prompt_text=prompt_text,
        reference_solution=reference_solution,
    )


def _evidence_spans(cohort: Any, run_id: str, submission_id: str, criterion_id: str) -> tuple:
    """The criterion's extracted spans for one (run, submission, criterion) — the rows
    the judgeless extraction wrote, keyed with no judge dimension (FR-EXTRACT-02), so
    every judge on the panel reads byte-identical evidence (CT-EXTRACT-03). Spans come
    back verbatim from the payload's own JSON: the request re-checks the span schema
    and forwards them unchanged."""
    rows = cohort.query(
        JUDGE_STATEMENTS["select_judge_run_evidence"],
        run_id=run_id,
        submission_id=submission_id,
        criterion_id=criterion_id,
        stage=STAGE_EXTRACT,
    )
    spans: list[Any] = []
    for row in rows:
        if row["payload"] is None:
            continue
        payload = json.loads(bytes(row["payload"]).decode("utf-8"))
        spans.extend(payload.get("spans", ()))
    return tuple(spans)


def assemble(unit: Any, *, store: Any = None) -> ScoringRequest:
    """Assemble §3.10's `ScoringRequest` from ONE work unit — exactly one criterion,
    exactly one submission, and a context built fresh from nothing else (`FR-JUDGE-02`,
    `FR-JUDGE-05`).

    This is BOTH the design's pure method and the contract door (the module docstring's
    first disclosed interpretation): a shipped `WorkUnit` in, a `ScoringRequest` out —
    no provider call, no store write, no clock read. The `store=` keyword is the
    `M-EXTRACT` disclosure verbatim: the lease resolves identities, the assembler the
    words and the rubric. With NO store the door still assembles — the pure door builds
    the request from what the unit carries, and the contract cases' arm rows (stripped
    to identity: `work_id`, `judge_id`, at most `submission_id`) assemble with the
    rubric views empty, which is exactly what makes the panel's payloads
    byte-identical: the ids are the only per-arm bytes, and the render carries
    none of them. An arm with no submission text assembles an EMPTY one — the honest
    rendering of "nothing was handed over", and the distinguishability CT-EXTRACT-08
    asserts is the ids'.

    Two disclosed readings, both test-pinned: the pseudonymous ref travels inside the
    pseudonymized submission text (§3.2's mechanism, and what the TC-JUDGE-20 scan
    verifies) rather than on the view's own slot at the pure door — the slot fills at
    the store door, where the lease's identity is resolved; and a unit that still
    carries `student_name` has it replaced with the ref before the request exists — in
    the transcript and in every evidence span's text, the dependency parents' included
    (#593).
    """
    work_id = _field_of(unit, "work_id")
    if not isinstance(work_id, str) or not work_id:
        raise TypeError(
            f"assemble needs a work unit carrying work_id (a work unit or an arm row "
            f"with an identity); got {type(unit).__name__}"
        )
    submission_id = _field_of(unit, "submission_id") or ""
    criterion_id = _field_of(unit, "criterion_id") or ""
    student_ref = _field_of(unit, "student_ref") or ""
    student_name = _field_of(unit, "student_name")
    transcript = _field_of(unit, "submission_text")
    run_id = _field_of(unit, "run_id")

    criterion: CriterionView = CriterionView(criterion_id=str(criterion_id), text="")
    question = QuestionView(prompt_text="", reference_solution="")
    evidence: tuple = ()
    dependency_evidence: tuple = ()
    # The view's ref slot starts empty — the pure door's arm rows must carry no
    # identity bytes beyond the ids (TC-JUDGE-05's leaf scan runs over exactly this
    # shape). It fills below, on the store door only.
    view_ref = ""

    if store is not None:
        # The lease resolved the identity (the claim select carries `student_ref`,
        # orch.py's work-unit claim) — the store door is where the view's slot fills.
        view_ref = str(student_ref)
        cohort = _find_cohort(store, work_id)
        if transcript is None:
            head = _current_document(store, submission_id)
            transcript = document_bytes(store, head).decode("utf-8")
        if run_id is None:
            run_id = cohort.query(
                JUDGE_STATEMENTS["select_work_unit"], work_id=work_id
            )[0]["run_id"]
        run_rows = cohort.query(JUDGE_STATEMENTS["select_judge_run"], run_id=run_id)
        if run_rows:
            criterion, question = _rubric_of(store, run_rows[0], str(criterion_id))
            evidence = _evidence_spans(cohort, str(run_id), str(submission_id), str(criterion_id))
            # One evidence query per dependency parent: the spans are read once and
            # carried, or the parent is dropped when extraction wrote none for it (a
            # parent with no evidence contributes nothing — no entry, never a guess).
            parent_spans = (
                (str(parent), _evidence_spans(
                    cohort, str(run_id), str(submission_id), str(parent)))
                for parent in _dependency_parents(store, run_rows[0], str(criterion_id))
            )
            dependency_evidence = tuple(
                DependencyEvidence(criterion_id=cid, spans=spans)
                for cid, spans in parent_spans
                if spans
            )
    if not isinstance(transcript, str):
        # The pure door's arm rows carry no words: an empty submission is what the
        # identity-only row honestly renders (the contract door's disclosed reading).
        transcript = ""

    transcript = _pseudonymize(transcript, student_name, student_ref)
    evidence = _pseudonymized_spans(evidence, student_name, student_ref)
    dependency_evidence = tuple(
        DependencyEvidence(
            criterion_id=entry.criterion_id,
            spans=_pseudonymized_spans(entry.spans, student_name, student_ref),
        )
        for entry in dependency_evidence
    )
    return ScoringRequest(
        work_id=work_id,
        criterion=criterion,
        question=question,
        evidence=evidence,
        dependency_evidence=dependency_evidence,
        submission=SubmissionView(
            submission_id=str(submission_id), student_ref=view_ref
        ),
        submission_text=transcript,
    )


def _dependency_parents(store: Any, run_row: Any, criterion_id: str) -> tuple:
    """The criterion's declared parents, from the package's dependency graph — the
    orchestrator's topological order is what guarantees a parent's evidence exists
    (CT-ORCH-05); this reads the graph, never a verdict on it."""
    package_id = run_row["package_id"]
    catalog = PackageCatalog(store.package(package_id), package_id=package_id)
    graph = catalog.dependency_graph(run_row["package_version_id"])
    return tuple(graph.get(criterion_id, ()))


def assemble_prompt(
    submission_id: str, criterion_id: str, *, rerun: bool = False
) -> PromptPayload:
    """The rerun-review assembly door (`CT-REVIEW-14`'s judge half): the prompt a
    re-run of one (submission, criterion) unit would assemble, keyed on ids alone.

    This is the second assembly door the rerun case's contract names — `assemble` is
    the unit-keyed door (the orchestrator's lease drives it); this one is id-keyed, so
    a reviewer-side caller can name the pair without holding the leased unit. It
    renders the SAME fresh-context template (`prompt_fields`) over the pure door's
    shape: the rubric views empty and the submission text empty, because an id carries
    no words — the words join through the store-backed `assemble` when the review
    wiring (#108/#109) resolves the unit's run.

    The `rerun` flag changes NO bytes, and that is the point (`FR-REVIEW-17`, R15): a
    re-run assembles the same fresh context a first judgment got, because the
    whitelist schema has no field a teacher's label could ride and the render carries
    no ids. Nothing a teacher records here is merely filtered out — it is
    unrepresentable.
    """
    if not isinstance(submission_id, str) or not submission_id:
        raise TypeError(
            f"assemble_prompt needs a submission_id (a non-empty string), got "
            f"{submission_id!r}"
        )
    if not isinstance(criterion_id, str) or not criterion_id:
        raise TypeError(
            f"assemble_prompt needs a criterion_id (a non-empty string), got "
            f"{criterion_id!r}"
        )
    request = ScoringRequest(
        # A synthesized identity for the id-keyed door: the render carries no ids, so
        # the work_id's exact value never reaches the prompt — it only satisfies the
        # whitelist's attribution requirement.
        work_id=f"rerun:{submission_id}:{criterion_id}",
        criterion=CriterionView(criterion_id=criterion_id, text=""),
        question=QuestionView(prompt_text="", reference_solution=""),
        evidence=(),
        dependency_evidence=(),
        submission=SubmissionView(
            submission_id=submission_id, student_ref=""
        ),
        submission_text="",
    )
    return prompt_fields(request)
