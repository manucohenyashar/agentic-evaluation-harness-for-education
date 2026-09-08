"""`CT-SETUP-12` — the degraded-but-complete path and the error taxonomy
(`TC-SETUP-C12`).

Case of test plan §6.11.6; issue #56 (TS-63). **Green by design** for every half
asserted here — the attempt loop, the manual-entry completion, the error
taxonomy and the ingestion routing all landed with #50 (and M-INGEST), and the
probe confirmed each on shipped code.

The clause: a model proposal failing schema validation is re-requested **up to
three times** (exact attempt count), then surfaced to the teacher as a
manual-entry path — the outcome is **degraded but complete, never blocked**. A
rubric artifact failing ingestion surfaces on the **upload screen, not operator
quarantine**. A `SchemaLockViolation` from `M-PKG` propagates **unchanged**
rather than being wrapped or swallowed.

Asserted here, probed:

1. **The exact attempt count.** A permanently-failing transport is driven
   through `propose_inventory`; the stored proposal records `attempts == 3` —
   the budget consumed exactly, not "some retries happened" — with status
   `needs_manual_entry` and the last error recorded in the payload (the
   degradation is visible in the DATABASE, not just the log). The knob
   (`HARNESS_SETUP_PROPOSAL_ATTEMPTS`, read at call time) shrinks the budget to
   1 and the count follows — the same property at a different setting.
2. **Degraded but complete, never blocked.** The manual-entry path is driven
   end to end on the degraded proposal: the teacher's `add` corrections enter
   the questions, the confirmation lands, and the version PUBLISHES. A
   permanent model failure costs a degradation, never a deadlock.
3. **`SchemaLockViolation` propagates unchanged.** The real M-PKG refusal type
   is raised at the real boundary (a `FaultCatalog` wrapping the real catalog —
   every member delegates; the one named call carries M-PKG's own error class)
   and exits `SetupService.set_answer_keys` as `SchemaLockViolation` itself:
   `type(exc) is SchemaLockViolation`, NOT a SetupError subclass, and the write
   did not happen. The module's taxonomy docstring promises this
   ("Storage-layer errors are deliberately NOT wrapped"); the assertion is the
   exception's IDENTITY, not merely "an exception was raised".
4. **Rubric ingestion failure routes to the caller, not quarantine.** A rubric
   artifact whose sanitizer fails is driven through the real `Ingestor`: the
   error surfaces to the CALLER (the upload screen's error surface —
   FR-INGEST-32), and NO quarantined submission row is written — the operator
   quarantine route does not fire for setup artifacts.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from aeh.ingest import (
    IngestSanitizeError,
    Ingestor,
    PdfSanitizer,
    ResidencySlot,
)
from aeh.pkg import SchemaLockViolation
from aeh.prov import SamplingParams
from aeh.setup import SetupError, SetupService
from tests.contract.setup._doubles import (
    FaultCatalog,
    db_file_for,
    ingest_document,
    stage_chain,
)
from tests.support.setup_harness import (
    TRANSCRIBER_BUILD,
    ScriptedRasterizer,
    ScriptedIngestProvider,
)

pytestmark = pytest.mark.contract

from aeh.conf import ModelRef

SETUP_MODEL_REF = ModelRef(role="extractor", provider="local",
                           build_id="vlm@sha256:bbbb", quantization="q4")


def _service_with_replies(chain, replies):
    """A service over the chain whose setup transport always fails to produce a
    valid proposal."""
    chain.provider.replies = list(replies)
    return chain.service


def test_tc_setup_c12_attempt_budget_is_exactly_three(tmp_data_dir, monkeypatch):
    """A permanent failure consumes the budget EXACTLY: `attempts == 3`, the
    degraded status, and the last error stored in the payload — and the knob
    moves the count, read at call time."""
    monkeypatch.delenv("HARNESS_SETUP_PROPOSAL_ATTEMPTS", raising=False)
    chain = stage_chain(tmp_data_dir / "budget", package_id="pkg-c12")
    chain.doc = ingest_document(chain.store, kind="assessment")
    service = _service_with_replies(chain, ["nope", "{\"questions\": []}", "garbage{"])

    proposal = service.propose_inventory(chain.doc)
    assert proposal.status == "needs_manual_entry"
    assert proposal.attempts == 3, (
        f"the degraded proposal recorded {proposal.attempts} attempts — the "
        "budget is exactly three (CT-SETUP-12)"
    )
    assert proposal.questions == ()

    # The degradation is visible in the DATABASE, not just the log: the stored
    # payload carries the status and the last attempt's error.
    conn = sqlite3.connect(f"file:{db_file_for(tmp_data_dir / 'budget', 'pkg-c12')}?mode=ro",
                           uri=True)
    try:
        payload = json.loads(conn.execute(
            "SELECT payload FROM setup_proposal").fetchone()[0])
    finally:
        conn.close()
    assert payload["status"] == "needs_manual_entry"
    assert payload["reason"], "the stored degradation lost its reason"

    # The knob moves the budget, read at CALL time (a fresh service over the
    # same directory would resume the stored proposal, so a new package).
    monkeypatch.setenv("HARNESS_SETUP_PROPOSAL_ATTEMPTS", "1")
    chain2 = stage_chain(tmp_data_dir / "budget2", package_id="pkg-c12-knob")
    chain2.doc = ingest_document(chain2.store, kind="assessment")
    service2 = _service_with_replies(chain2, ["nope"])
    proposal2 = service2.propose_inventory(chain2.doc)
    assert proposal2.status == "needs_manual_entry"
    assert proposal2.attempts == 1, (
        "the env knob did not move the attempt budget at call time (CT-SETUP-12)"
    )


def test_tc_setup_c12_degraded_is_complete_never_blocked(tmp_data_dir):
    """The permanent-failure path still finishes: manual entry via `add`
    corrections, confirmation, publication — degraded but complete."""
    chain = stage_chain(tmp_data_dir / "degraded", package_id="pkg-c12d")
    chain.doc = ingest_document(chain.store, kind="assessment")
    service = _service_with_replies(chain, ["nope", "also nope", "still nope"])
    proposal = service.propose_inventory(chain.doc)
    assert proposal.status == "needs_manual_entry"

    # The teacher enters the questions as corrections — the manual-entry
    # vehicle the degraded status names — and the stage completes.
    from aeh.setup import ProposedOption, QuestionCorrection
    corrections = [
        QuestionCorrection(question_id="Q1", action="add", question_type="open",
                           prompt_text="Define impulse in one sentence.",
                           ordinal=0, max_points=4.0),
        QuestionCorrection(question_id="Q4", action="add", question_type="mcq",
                           prompt_text="Circle one: (A) 9.8 (B) 1.6",
                           ordinal=1, max_points=2.0,
                           options=(ProposedOption("A", 0, "9.8"),
                                    ProposedOption("B", 1, "1.6"))),
    ]
    service.confirm_inventory(proposal.proposal_id, corrections)
    # #53: the correction's mcq question stages CRIT-Q4 — the teacher keys it
    # (gate 2) before the degraded path can complete. The refusal half first: a
    # key naming an option the question never offered raises, and writes
    # NOTHING — a blocking gate that half-applies would leave the draft
    # indistinguishable from a partially saved one (found by the #53 reviewer;
    # the validate-every-key-then-write order is the fix).
    with pytest.raises(SetupError):
        service.set_answer_keys({"CRIT-Q4": ["Z"]})
    assert chain.catalog.answer_key("CRIT-Q4") == (), (
        "the refused keying call still wrote the valid keys it passed on the "
        "way to the bad one — set_answer_keys must validate every key BEFORE "
        "writing any (the refusal leaves the stored keys exactly as they were)"
    )
    service.set_answer_keys({"CRIT-Q4": ["A"]})
    version = service.publish("teacher-1")
    assert chain.catalog.is_locked(version), (
        "the degraded path could not complete — manual entry did not reach the "
        "published state (CT-SETUP-12: degraded but complete, never blocked)"
    )
    # The manual entries are in the confirmed inventory.
    questions = chain.catalog.questions(version)
    assert {q["question_id"] for q in questions} >= {"Q1", "Q4"}


def test_tc_setup_c12_schema_lock_violation_propagates_unchanged(tmp_data_dir):
    """M-PKG's refusal type exits setup with its IDENTITY intact: exactly
    `SchemaLockViolation`, not a SetupError, not swallowed — and the write did
    not happen."""
    chain = stage_chain(tmp_data_dir / "taxonomy", package_id="pkg-c12t")
    chain.doc = ingest_document(chain.store, kind="assessment")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)
    version = chain.service.ensure_version()
    chain.catalog.add_criterion(version, "MCQ-1", question_id="Q4", kind="mcq")

    real_catalog = chain.catalog
    fault = FaultCatalog(
        real_catalog, "set_answer_key",
        SchemaLockViolation(
            "the 'criterion.answer_key' edit on package version "
            f"{version!r} is refused by the §6.2 schema lock (FR-PKG-03)"
        ),
    )
    service = SetupService(fault, chain.ingestor, chain.provider, SETUP_MODEL_REF)
    with pytest.raises(SchemaLockViolation) as excinfo:
        service.set_answer_keys({"MCQ-1": ["A"]})
    assert type(excinfo.value) is SchemaLockViolation, (
        "the storage refusal was re-raised under a setup type — the caller "
        "branching on the data-layer type broke (CT-SETUP-12)"
    )
    assert not isinstance(excinfo.value, SetupError), (
        "SchemaLockViolation must not sit inside the SetupError hierarchy — "
        "the taxonomies are siblings, never a chain (CT-SETUP-12)"
    )
    assert fault.fault_calls == 1
    # Not swallowed: nothing was written — the criterion is still unkeyed.
    rows = [row for row in real_catalog.criteria(version)
            if row["criterion_id"] == "MCQ-1"]
    assert rows and not rows[0].get("answer_key")


def test_tc_setup_c12_rubric_ingestion_failure_surfaces_not_quarantines(
        tmp_data_dir):
    """A rubric artifact that fails ingestion surfaces to the CALLER (the
    upload screen's error surface) and writes NO quarantined row — the operator
    quarantine route does not fire for setup artifacts (FR-INGEST-32)."""
    class FailingSanitizer(PdfSanitizer):
        def sanitize(self, pdf_bytes, *, strip=True, max_decompressed_bytes=None,
                     max_embedded_objects=None, deadline=None):
            raise IngestSanitizeError("the rubric artifact failed sanitization")

    data_dir = tmp_data_dir / "routing"
    chain = stage_chain(data_dir, package_id="pkg-c12r")
    source = chain.store.blobs().put(b"rubric bytes")
    ingestor = Ingestor(
        chain.store.cohort("c-rubric-fail"), chain.store.blobs(),
        ScriptedIngestProvider("unused — the sanitizer fails first"),
        ModelRef(role="transcriber", provider="local", build_id=TRANSCRIBER_BUILD,
                 quantization="q4"),
        SamplingParams(temperature=0.0), ScriptedRasterizer(),
        residency=ResidencySlot.for_policy(("transcriber",)),
        sanitizer=FailingSanitizer(),
    )

    with pytest.raises(IngestSanitizeError):
        # The call the upload screen makes: the error lands in the CALLER's
        # hands — surfacing here IS the upload-screen routing.
        ingestor.ingest_document([source], kind="rubric",
                                 filenames={source: "rubric.pdf"})

    # Nothing reached the operator quarantine: no submission row exists for the
    # cohort the rubric was offered to.
    count = chain.store.cohort("c-rubric-fail").query(
        "SELECT COUNT(*) AS n FROM submission")[0]["n"]
    assert count == 0, (
        "a failed rubric artifact was quarantined as a submission — the "
        "operator route fired where the upload-screen route belongs "
        "(CT-SETUP-12, FR-INGEST-32)"
    )
