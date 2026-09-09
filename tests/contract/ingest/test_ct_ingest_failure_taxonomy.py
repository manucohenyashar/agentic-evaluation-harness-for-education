"""`CT-INGEST-14` — the failure taxonomy (`TC-INGEST-C14`).

Case of test plan §6.11.5; issue #49 (TS-62). Green by design — the named
failures are shipped; the taxonomy's summary is what this file holds.

The clause: a page failing transcription three times quarantines **its
submission, not the run** (NFR-INGEST-02); a `reference` artifact whose
text-layer divergence exceeds threshold **halts** rather than warns
(FR-INGEST-03); where assembly order cannot be determined the module
**quarantines and asks** rather than guessing (FR-INGEST-31); and — the
summary — **no failure mode returns partial content as if complete**.

**Disclosed finding (G3 in `_doubles`, probe-backed, shipped code):** there is
no transcription retry loop — the only re-request loop is the
evaluative-description one (`EVALUATIVE_RETRIES_ENV`, C06's clause). A provider
FAULT on transcription escapes `ingest_submission` raw (only
`IngestGapError` / `IngestDuplicateError` / `IngestError` are caught there),
leaving the submission row with NULL gate columns, NULL `ingest_status` and
`quarantined = 0` — a zombie row the operator surface cannot triage.

**RESOLVED by #220:** the transcription path now carries the three-strike
loop (`HARNESS_INGEST_TRANSCRIPTION_ATTEMPTS`, read at call time) and
`ingest_submission` catches `IngestTranscriptionError` into an honest
quarantine — the row's gate columns are marked (V0 pass, V1 fail, V2/V3
`not_reached`), the exception never escapes raw, and the strike log is in the
report's stage detail. The fault case below asserts the containment shape;
`TC-INGEST-40`'s own suite (#235, exact strike value plus the cohort-
completion oracle) is the test story that depends on #220. The summary sweep
now has no excluded escape route from the transcription path.

Consumer halves deferred with disclosure: the run-level "not the run" is
M-ORCH's (#59..#66); the operator's triage of these findings is M-CONSOLE's
(#123..#130).
"""

from __future__ import annotations

import json

import pytest

from aeh.ingest import IngestError, IngestOrderError, TRANSCRIPTION_ATTEMPTS_ENV
from aeh.prov import Completion
from tests.contract.ingest._doubles import (
    COHORT,
    Contract,
    RefusingSanitizer,
    ScriptedProvider,
    answer_text,
    selection_mark,
    student_answer,
)
from tests.support.store_api import statement

pytestmark = pytest.mark.contract


class FailingProvider(ScriptedProvider):
    """The faulted model: every call dies. The transcription strike loop
    absorbs it per page (#220) until the limit is exhausted, then the
    submission quarantines — the fault exercises every strike."""

    def complete(self, prompt, model_ref, params) -> Completion:
        raise RuntimeError("injected: the model died mid-transcription")


# -- the named failures -------------------------------------------------------------------------------


def test_tc_ingest_c14_a_transcription_fault_scores_nothing_and_stores_nothing(
        tmp_data_dir, monkeypatch):
    """`TC-INGEST-C14` (transcription fault) — a model fault mid-transcription
    is CONTAINED (#220, `NFR-INGEST-02`): the call returns a quarantine
    report, the exception never escapes raw, and the row is an honestly-marked
    quarantine — V0 passed (the file was fine), V1 failed (the page could not
    be read), V2/V3 `not_reached`; never a NULL-gates `quarantined=0` zombie.
    The fault cannot manufacture a complete-looking artifact (NO document, NO
    regions, nothing scored), the strike log is observable in the report's
    stage detail, and the call is retryable — the same blobs re-ingest cleanly
    after."""
    # The exact-3 assertion below pins the SHIPPED default; a box that sets
    # the knob (its documented purpose) must not skew it.
    monkeypatch.delenv(TRANSCRIPTION_ATTEMPTS_ENV, raising=False)
    fx = Contract(tmp_data_dir, "c14-fault", provider=FailingProvider())
    fx.add_roster("gus")
    source = fx.put(b"c14 fault pdf")
    fx.script(source, {1: student_answer("gus", answer_text("Q1", "answer"))})
    report = fx.ingestor.ingest_submission([source], cohort_id=COHORT,
                                           package_version="v0",
                                           filenames={source: "a.pdf"})
    assert report.ingest_status == "unreadable" and report.gates["v1"] == "fail", (
        f"TC-INGEST-C14: the faulted transcription did not quarantine: "
        f"{report.ingest_status} / {report.gates}."
    )
    assert (report.gates["v0"] == "pass"
            and report.gates["v2"] == "not_reached"
            and report.gates["v3"] == "not_reached"), (
        f"TC-INGEST-C14: the quarantine's gate columns are not honest: "
        f"{report.gates}."
    )
    strikes = report.detail["transcription_attempts"]
    assert len(strikes) == 3 and [s["attempt"] for s in strikes] == [1, 2, 3], (
        f"TC-INGEST-C14: the strike log is not the three-strike limit: "
        f"{strikes}."
    )
    row = fx.submission_rows()[0]
    assert (row["quarantined"] == 1 and row["ingest_status"] == "unreadable"
            and row["v0_integrity"] == "pass" and row["v1_pages"] == "fail"
            and row["v2_structure"] == "not_reached"
            and row["v3_identity"] == "not_reached"), (
        f"TC-INGEST-C14: the faulted submission's row is not an honestly-"
        f"marked quarantine: {dict(row)}."
    )
    assert fx.documents() == [] and fx.regions() == [], (
        "TC-INGEST-C14: a faulted transcription left an artifact behind — "
        "partial content stored."
    )
    fx.close()
    # Retryability: the same blobs through a healthy provider ingest cleanly.
    retry = Contract(tmp_data_dir, "c14-fault-retry")
    retry.add_roster("gus")
    same = retry.put(b"c14 fault pdf")
    retry.script(same, {1: student_answer("gus", answer_text("Q1", "answer"))})
    report = retry.ingestor.ingest_submission(
        [same], cohort_id=COHORT, package_version="v0",
        filenames={same: "a.pdf"})
    assert report.ingest_status == "ok", (
        f"TC-INGEST-C14: the retry after the fault did not complete: "
        f"{report.ingest_status}."
    )
    retry.close()


def test_tc_ingest_c14_a_reference_divergence_halts_rather_than_warns(
        tmp_data_dir, monkeypatch):
    """`TC-INGEST-C14` (reference halt) — a reference artifact whose text layer
    disagrees with its transcript past the threshold HALTS: `IngestError`
    raised, nothing stored — a corrupted answer key is never ingested with a
    warning. The halt is not sticky: the same artifact with a layer that
    agrees re-ingests cleanly; and the threshold is the declared knob's — at
    `0.0` even a mild divergence halts, while the agreeing layer still
    ingests."""
    from aeh.ingest import DIVERGENCE_HALT_ENV

    fx = Contract(tmp_data_dir, "c14-halt")
    transcript = "the reference answer text"
    layer_bytes = b"c14 ref pdf"
    source = fx.put(layer_bytes)
    fx.script(source, {1: transcript})
    fx.rasterizer.layer = {(layer_bytes, 1): "wholly unrelated layer words"}
    with pytest.raises(IngestError, match="divergence"):
        fx.ingestor.ingest_document([source], kind="reference",
                                    filenames={source: "a.pdf"})
    assert fx.documents() == [] and fx.regions() == [], (
        "TC-INGEST-C14: the halted reference left an artifact behind — the "
        "corrupted key was ingested with a warning, not refused."
    )
    # Retryability: a layer that agrees ingests the same blob cleanly.
    fx.rasterizer.layer = {(layer_bytes, 1): transcript}
    document_id = fx.ingestor.ingest_document([source], kind="reference",
                                              filenames={source: "a.pdf"})
    assert fx.documents("document_id = :d", d=document_id), (
        "TC-INGEST-C14: the corrected reference did not re-ingest."
    )
    fx.close()

    # The knob: the threshold is configured, not hard-coded — at 0.0 a mild
    # divergence halts too, and the agreeing layer still ingests.
    monkeypatch.setenv(DIVERGENCE_HALT_ENV, "0.0")
    strict = Contract(tmp_data_dir, "c14-halt-strict")
    mild_layer = b"c14 mild ref"
    mild = strict.put(mild_layer)
    mild_transcript = "the reference answer text, with a footnote"
    strict.script(mild, {1: mild_transcript})
    strict.rasterizer.layer = {(mild_layer, 1): "the reference answer text"}
    with pytest.raises(IngestError, match="divergence"):
        strict.ingestor.ingest_document([mild], kind="reference",
                                        filenames={mild: "a.pdf"})
    strict.rasterizer.layer = {(mild_layer, 1): mild_transcript}
    strict.ingestor.ingest_document([mild], kind="reference",
                                    filenames={mild: "b.pdf"})
    assert strict.documents("kind = 'reference'"), (
        "TC-INGEST-C14: the agreeing reference did not ingest under the strict "
        "knob."
    )
    strict.close()


def test_tc_ingest_c14_an_undeterminable_order_quarantines_and_asks(
        tmp_data_dir):
    """`TC-INGEST-C14` (order refusal) — pages with no order source anywhere:
    the direct call refuses (`IngestOrderError`, never a guess), the gateway
    quarantines the unit with a finding that ASKS (names the missing order for
    the operator), and stating the order makes the same blobs assemble — the
    refusal was a question, not a dead end."""
    fx = Contract(tmp_data_dir, "c14-order")
    fx.add_roster("gus")
    one = fx.put(b"c14 order one")
    two = fx.put(b"c14 order two")
    fx.script(one, {1: student_answer("gus", answer_text("Q1", "one"))})
    fx.script(two, {1: answer_text("Q2", "two")})
    with pytest.raises(IngestOrderError, match="cannot be determined"):
        fx.ingestor.ingest_document([one, two], kind="submission")
    assert fx.documents() == [], (
        "TC-INGEST-C14: the order refusal stored an assembled document — the "
        "module guessed."
    )
    report = fx.ingestor.ingest_submission([one, two], cohort_id=COHORT,
                                           package_version="v0")
    assert report.ingest_status == "unreadable" and report.gates["v0"] == "fail", (
        f"TC-INGEST-C14: the order refusal did not quarantine through the "
        f"gateway: {report.ingest_status}."
    )
    finding_text = json.dumps(report.detail["findings"])
    assert "order" in finding_text.lower(), (
        f"TC-INGEST-C14: the quarantine finding does not ask about the order: "
        f"{finding_text[:200]} — the operator is left with an unattributable "
        "refusal."
    )
    document_id = fx.ingestor.ingest_document(
        [one, two], kind="submission", order_hint=[one, two])
    assert fx.documents("document_id = :d", d=document_id), (
        "TC-INGEST-C14: stating the order did not unblock the same blobs — "
        "the refusal was not a question."
    )
    fx.close()


# -- the summary: no failure mode returns partial content as if complete --------------


def _sweep_routes(tmp_data_dir) -> list[tuple[str, Contract, object]]:
    """Every failure route the module ships, each on its own fixture: the
    routes whose outcome is CONTAINED (a quarantined row or a raised refusal,
    never an escape)."""
    routes: list[tuple[str, Contract, object]] = []

    v1 = Contract(tmp_data_dir, "c14s-gap")
    first, second = v1.put(b"c14s gap p1"), v1.put(b"c14s gap p2")
    v1.script(first, {1: "Page 1 of 4\nbody one"})
    v1.script(second, {1: "Page 2 of 4\nbody two"})
    routes.append(("gap", v1, v1.ingestor.ingest_submission(
        [first, second], cohort_id=COHORT, package_version="v0")))

    dup = Contract(tmp_data_dir, "c14s-duplicate")
    one, two = dup.put(b"c14s dup one"), dup.put(b"c14s dup two")
    dup.script(one, {1: "the very same body words"})
    dup.script(two, {1: "the very same body words"})
    routes.append(("duplicate", dup, dup.ingestor.ingest_submission(
        [one, two], cohort_id=COHORT, package_version="v0",
        filenames={one: "1-page.pdf", two: "2-page.pdf"})))

    v2 = Contract(tmp_data_dir, "c14s-v2")
    catalog, version = v2.catalog(["open"])
    source = v2.put(b"c14s v2 pdf")
    v2.script(source, {1: student_answer(
        None, selection_mark("Q1", state="resolved", option="A"))})
    routes.append(("v2-structure", v2, v2.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version=version,
        filenames={source: "a.pdf"}, package_catalog=catalog)))

    v3 = Contract(tmp_data_dir, "c14s-v3")
    source = v3.put(b"c14s v3 pdf")
    v3.script(source, {1: student_answer("ghost", answer_text("Q1", "x"))})
    routes.append(("v3-identity", v3, v3.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "a.pdf"})))

    v4 = Contract(tmp_data_dir, "c14s-v4")
    v4.add_roster("gus")
    catalog, version = v4.catalog(["open"])
    source = v4.put(b"c14s v4 pdf")
    v4.script(source, {1: "Student: gus\nAssessment: pkg-other\n"
                          + answer_text("Q1", "answer")})
    routes.append(("v4-unmatched", v4, v4.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version=version,
        filenames={source: "a.pdf"}, package_catalog=catalog)))

    order = Contract(tmp_data_dir, "c14s-order")
    source = order.put(b"c14s order pdf")
    order.script(source, {1: student_answer("gus", answer_text("Q1", "x"))})
    second = order.put(b"c14s order pdf2")
    # Two blobs, no order source anywhere: through the gateway the refusal is
    # CONTAINED (quarantined unreadable) — the raise is the direct call's form.
    routes.append(("order-refusal", order, order.ingestor.ingest_submission(
        [source, second], cohort_id=COHORT, package_version="v0")))

    unterminated = Contract(tmp_data_dir, "c14s-unterminated")
    source = unterminated.put(b"c14s bad pdf")
    unterminated.script(source, {1: "Student: gus\n"
                                    "<!-- region: kind=transcribed_text "
                                    "question_id=Q1 conf=0.9 -->\nnever closed"})
    routes.append(("unterminated-marker", unterminated,
                   unterminated.ingestor.ingest_submission(
                       [source], cohort_id=COHORT, package_version="v0",
                       filenames={source: "a.pdf"})))

    v0 = Contract(tmp_data_dir, "c14s-v0",
                  sanitizer=RefusingSanitizer("junk"))
    routes.append(("v0-unreadable", v0, v0.ingestor.ingest_submission(
        [v0.put(b"c14s v0 pdf")], cohort_id=COHORT, package_version="v0",
        filenames={})))
    return routes


def test_tc_ingest_c14_no_failure_mode_returns_partial_content_as_complete(
        tmp_data_dir):
    """`TC-INGEST-C14` (summary) — across every contained failure route the
    store's state is exactly one of: nothing stored, or a quarantined row
    beside a document whose every recorded page carries a region. No route
    leaves an `ok` status over a short document — and the positive control (a
    clean ingest) shows the completeness check has teeth."""
    for label, fx, report in _sweep_routes(tmp_data_dir):
        rows = fx.submission_rows()
        documents = fx.documents()
        assert documents == [] or all(row["quarantined"] == 1 for row in rows), (
            f"TC-INGEST-C14 ({label}): the store holds a document beside an "
            f"unquarantined submission ({[dict(r) for r in rows]}) — a failure "
            "mode returned content as if complete."
        )
        if report is not None:
            assert report.ingest_status != "ok", (
                f"TC-INGEST-C14 ({label}): the failure route reported ok."
            )
        # Whatever documents exist carry a region for every page their own
        # provenance records — partial builds are detectable, not silent. The
        # page identity is (source hash, page within that source): the region's
        # provenance triple, not the assembled position (C07's distinction).
        for document in documents:
            provenance = json.loads(document["source_blobs"])
            recorded = {(entry["blob_hash"], entry["page_no"])
                        for entry in provenance["pages"]}
            covered = {(row["source_hash"], row["page_no"]) for row in fx.regions(
                document["document_id"])}
            assert covered == recorded, (
                f"TC-INGEST-C14 ({label}): document {document['document_id']} "
                f"records {sorted(recorded)} but its regions cover "
                f"{sorted(covered)} — partial content presented as complete."
            )
        fx.close()

    # The positive control: a clean ingest's document is complete by the same
    # check — the sweep's completeness assertion is not vacuous.
    clean = Contract(tmp_data_dir, "c14s-clean")
    clean.add_roster("gus")
    first, second = clean.put(b"c14s clean one"), clean.put(b"c14s clean two")
    clean.script(first, {1: student_answer("gus", answer_text("Q1", "one"))})
    clean.script(second, {1: answer_text("Q2", "two")})
    document_id = clean.ingestor.ingest_document(
        [first, second], kind="submission", order_hint=[first, second])
    document = clean.documents("document_id = :d", d=document_id)[0]
    provenance = json.loads(document["source_blobs"])
    recorded = {(entry["blob_hash"], entry["page_no"])
                for entry in provenance["pages"]}
    covered = {(row["source_hash"], row["page_no"])
               for row in clean.regions(document_id)}
    assert covered == recorded and len(recorded) == 2, (
        f"TC-INGEST-C14: the clean document is not complete by the sweep's "
        f"own check (recorded {sorted(recorded)}, covered {sorted(covered)})."
    )
    clean.close()
