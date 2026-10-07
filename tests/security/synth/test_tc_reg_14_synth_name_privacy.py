"""TC-REG-14 (#668): no rostered student name reaches M-SYNTH's narrative model request.

**Was red: a rostered name inside an evidence span's text or a document body reached the
synthesizer (NFR-PROV-08 — the R21 shape #593 fixed in M-JUDGE and M-EXTRACT, found by
#593's reviewer as a follow-up).** `SynthesisWorker._evidence` redacted the `Student:` head
only (`redact_identity_head`, #620): a name the student wrote in the body — a signature, a
turn of phrase — or that M-EXTRACT copied into a span payload travelled in the L1 request's
`evidence` field on every profile.

The case follows SEC-19's acceptance form: the model request payload captured at the
transport seam is what is asserted, not the report. The run is the `edge-local` profile
(`seed_run`'s default), and `M-SYNTH` takes no profile branch — this one assembly is the
assembly every profile gets, so the edge-local assertion is the all-profiles assertion
(#593's defense-in-depth rule).

The fix routes through the ONE boundary helper, `aeh.ingest.identity.pseudonymize_name` —
no second, divergent redaction in `M-SYNTH`. It does not ask for free-text redaction of
names the roster does not hold, which `judge.py` §3.2 rejects (the SEC-19 stance).
"""

from __future__ import annotations

import json

import pytest

from aeh.store import open_store
from tests.support.impl import SYNTH_MODULE, require
from tests.support.orch_run import seed_run
from tests.support.roster import strings_in
from tests.support.synth_vocabulary import (
    COHORT_ID,
    CaptureProvider,
    FIVE_QUESTION_CRITERIA,
    WORKER,
    narrative_completion,
    seed_scored_submission,
    synth_ref,
)

pytestmark = [pytest.mark.integration]

_SUBMISSION = "SYN-001"
#: The roster sentinel's name, the same one SEC-19 and TC-REG-11 use.
NAME = "Zelda Quartermaine"
#: The ref the fixture's submission row carries (`seed_cohort`'s shape).
REF = "ref-SYN-001"

#: The stored script: the `Student:` head carries the REF (the post-#620 shape papers
#: write), and the NAME sits in the BODY — the head redaction cannot reach it.
MARKDOWN = (
    f"Student: {REF}\n"
    f"\n"
    f"## Question 1\n"
    f"The response states the hypothesis clearly. Signed, {NAME}.\n"
    f"\n"
    f"## Question 2\n"
    f"The derivation is complete and cites the table."
)

#: A span payload of the shape `_payload_span_texts` decodes, carrying the name in the
#: span text M-EXTRACT sliced out of the same script.
SPAN_TEXT = f"The response states the hypothesis clearly. Signed, {NAME}."
SPAN_PAYLOAD = json.dumps(
    {"spans": [{"start": 0, "end": len(SPAN_TEXT), "text": SPAN_TEXT}]}
).encode("utf-8")


def _seed_named_world(store):
    """The world the defect feeds on: a named roster row, a script whose body carries the
    name, one evidence unit whose span payload carries it too. Returns `(run_id, handle)`."""
    _, run_id, _ = seed_run(store, submissions=(_SUBMISSION,), criteria=FIVE_QUESTION_CRITERIA)
    handle = store.cohort(COHORT_ID)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO roster (cohort_id, student_ref, full_name) "
            "VALUES (:c, :r, :n)",
            c=COHORT_ID, r=REF, n=NAME,
        )
    seed_scored_submission(
        store, run_id, _SUBMISSION,
        complete_questions={"Q1"}, markdown=MARKDOWN,
    )
    # Q1C1's evidence row decodes a span payload; Q1C2's stays payload-less and falls
    # back to the document markdown — both delivery paths feed one L1 request.
    with handle.transaction() as tx:
        tx.execute(
            "UPDATE evidence SET payload = :p WHERE evidence_id = :e",
            p=SPAN_PAYLOAD, e="ev-wu-SYN-001-Q1C1-score",
        )
    return run_id, handle


def test_tc_reg_14_the_narrative_request_carries_the_ref_not_the_name(tmp_data_dir):
    """The L1 request payload — evidence spans and document markdown — carries the
    `student_ref` wherever the rostered name was, asserted over the captured prompt."""
    Worker = require(SYNTH_MODULE, WORKER, issue="#97")

    store = open_store(tmp_data_dir)
    try:
        run_id, handle = _seed_named_world(store)

        # Fixture sanity: the name really is in the stored script and in the span
        # payload — the request is the only place the redaction may remove it from.
        stored = [str(r[0]) for r in handle.query("SELECT markdown FROM document")]
        assert any(NAME in text for text in stored), "fixture: the name never reached the script"
        payload = handle.query(
            "SELECT payload FROM evidence WHERE evidence_id = 'ev-wu-SYN-001-Q1C1-score'"
        )[0][0]
        assert NAME in bytes(payload).decode("utf-8"), "fixture: the span payload holds no name"

        provider = CaptureProvider([
            narrative_completion("Question 1: the response states the hypothesis and cites the signed work."),
        ])
        Worker(store, provider, synth_ref()).synthesize_question(run_id, _SUBMISSION, "Q1")
    finally:
        store.close()

    assert provider.calls == 1, f"fixture: {provider.calls} model calls, expected one L1 call"
    # SEC-19's acceptance form: an assertion over the assembled payload, shape-agnostic.
    text = "\n".join("\n".join(strings_in(prompt)) for prompt in provider.prompts)
    assert NAME not in text, (
        "the rostered student's name reached M-SYNTH's narrative model request "
        "(NFR-PROV-08) — the evidence field carried it from the span text or the "
        "document body, which only `Student:`-head redaction ran over"
    )
    assert REF in text, "the request does not carry the student_ref in the name's place"
