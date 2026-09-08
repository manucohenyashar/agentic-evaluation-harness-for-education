"""`CT-INGEST-11` — admissibility is exactly the two statuses (`TC-INGEST-C11`).

Case of test plan §6.11.5; issue #49 (TS-62). Green by design — #40 landed the
gate columns and the quarantine flag.

The clause: a submission is admissible to scoring **iff** `ingest_status` is
`ok` or `low_confidence_ocr`; `M-ORCH` may treat that as the complete admission
rule (FR-ORCH-22); no other state is ever scorable; and re-ingestion after
operator action produces a new document that rejoins the same run.

**Disclosed finding (probe-backed, shipped code) — CLOSED by #221:**
`low_confidence_ocr` used to be a DECLARED member of the vocabulary with NO
producing path (the token occurred nowhere else in the module). The ladder now
mints it — a clean-ladder submission with a stored region whose `ocr_conf`
sits strictly below the `HARNESS_INGEST_OCR_CONF_FLOOR` floor (0.70 default)
flags `low_confidence_ocr`, `quarantined = 0`, and the state sweep below
drives ALL FIVE statuses, the biconditional (admissible iff
`quarantined = 0`) holding on each.

Consumer half deferred with disclosure: "`M-ORCH` applies no additional filter
of its own" is the orchestrator's assertion, and M-ORCH does not exist yet
(stories #59..#66). The producer half held here is what the rule needs: a
CLOSED five-value status vocabulary whose admitted subset is exactly the two —
a second, drifting rule would have to introduce a sixth value or re-read the
gate columns, and the CHECK makes the first impossible without a schema change.
"""
from __future__ import annotations

import sqlite3

import pytest

from aeh.ingest import PageReplacement
from tests.contract.ingest._doubles import (
    COHORT,
    INGEST_STATUSES,
    Contract,
    RefusingSanitizer,
    answer_text,
    student_answer,
)
from tests.support.store_api import statement

pytestmark = pytest.mark.contract

#: The clause's admitted set — the complete admission rule, as data.
ADMISSIBLE = frozenset({"ok", "low_confidence_ocr"})


def _clean_fixture(fx: Contract, label: str):
    """One clean ingest: the `ok` route."""
    fx.add_roster("gus")
    source = fx.put(f"c11 {label} pdf".encode())
    fx.script(source, {1: student_answer("gus", answer_text("Q1", "answer"))})
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "a.pdf"})
    assert report.ingest_status == "ok", (
        f"TC-INGEST-C11: the clean route did not complete: "
        f"{report.ingest_status} / {report.gates}."
    )
    return report


def _low_confidence_fixture(fx: Contract, label: str):
    """One clean-but-low-confidence ingest: the `low_confidence_ocr` route
    (#221). The reading sits below the floor, so the ladder flags the status —
    without quarantining: CT-INGEST-11 admits it exactly like `ok`."""
    fx.add_roster("gus")
    source = fx.put(f"c11 {label} pdf".encode())
    fx.script(source, {1: student_answer("gus", answer_text(
        "Q1", "the barely legible answer", conf="0.05"))})
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "a.pdf"})
    assert report.ingest_status == "low_confidence_ocr", (
        f"TC-INGEST-C11: the low-confidence route did not flag: "
        f"{report.ingest_status} / {report.gates}."
    )
    return report


def test_tc_ingest_c11_admissibility_is_exactly_ok_and_low_confidence_ocr(
        tmp_data_dir):
    """`TC-INGEST-C11` (state sweep) — across the WHOLE declared vocabulary the
    biconditional holds: a row is admissible (`ingest_status` in the two) IFF
    it carries `quarantined = 0`. Each of the five statuses is driven by its
    own producing route (V0 unreadable, V1 incomplete, V4
    unmatched_assessment, the confidence floor's `low_confidence_ocr` — the
    fifth, admissible and unquarantined); the three non-admissible states are
    never scorable, and the producer's own flag agrees with the status on
    every row — no state sits in the admitted set while flagged quarantined,
    or outside it while clean."""
    routes: list[tuple[str, Contract, object]] = []

    ok = Contract(tmp_data_dir, "c11-ok")
    routes.append(("ok", ok, _clean_fixture(ok, "ok")))

    unreadable = Contract(tmp_data_dir, "c11-v0",
                          sanitizer=RefusingSanitizer("junk"))
    routes.append(("unreadable", unreadable, unreadable.ingestor.ingest_submission(
        [unreadable.put(b"c11 v0 pdf")], cohort_id=COHORT, package_version="v0",
        filenames={})))

    v1 = Contract(tmp_data_dir, "c11-v1")
    first, second = v1.put(b"c11 v1 p1"), v1.put(b"c11 v1 p2")
    v1.script(first, {1: "Page 1 of 4\nbody one"})
    v1.script(second, {1: "Page 2 of 4\nbody two"})
    routes.append(("incomplete", v1, v1.ingestor.ingest_submission(
        [first, second], cohort_id=COHORT, package_version="v0")))

    v4 = Contract(tmp_data_dir, "c11-v4")
    v4.add_roster("gus")
    catalog, version = v4.catalog(["open"])
    source = v4.put(b"c11 v4 pdf")
    v4.script(source, {1: "Student: gus\nAssessment: pkg-other\n"
                          + answer_text("Q1", "answer")})
    routes.append(("unmatched_assessment", v4, v4.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version=version,
        filenames={source: "a.pdf"}, package_catalog=catalog)))

    low = Contract(tmp_data_dir, "c11-lco")
    routes.append(("low_confidence_ocr", low,
                   _low_confidence_fixture(low, "lco")))

    produced = set()
    for label, fx, report in routes:
        rows = fx.submission_rows()
        assert len(rows) == 1, (
            f"TC-INGEST-C11 ({label}): expected exactly one submission row."
        )
        status, quarantined = rows[0]["ingest_status"], rows[0]["quarantined"]
        assert status == report.ingest_status, (
            f"TC-INGEST-C11 ({label}): the row status {status!r} disagrees "
            f"with the report {report.ingest_status!r}."
        )
        admissible = status in ADMISSIBLE
        assert admissible == (quarantined == 0), (
            f"TC-INGEST-C11 ({label}): status {status!r} with quarantined="
            f"{quarantined} breaks the biconditional — the admission rule and "
            "the producer's flag disagree."
        )
        assert status in INGEST_STATUSES, (
            f"TC-INGEST-C11 ({label}): status {status!r} outside the vocabulary."
        )
        produced.add(status)
        fx.close()
    # The sweep is complete over the WHOLE vocabulary: every one of the five
    # statuses is driven by its own producing route (G1, closed by #221 — a
    # reading below the confidence floor flags `low_confidence_ocr` without
    # quarantining).
    assert produced == set(INGEST_STATUSES), (
        f"TC-INGEST-C11: the sweep produced {sorted(produced)} — the producible "
        "set no longer covers the declared vocabulary exactly."
    )


def test_tc_ingest_c11_the_status_vocabulary_is_closed_over_the_rule(
        tmp_data_dir):
    """`TC-INGEST-C11` (complete-rule half, producer side) — the rule is
    COMPLETE because the vocabulary is closed: the schema CHECK rejects a sixth
    value outright, so "status ∈ {ok, low_confidence_ocr}" can never be
    silently incomplete, and the admitted set is a proper subset with the three
    non-admissible values as its exact complement. A drifting second rule has
    no third way to encode admissibility without a schema change. The
    consumer half (`M-ORCH` applies no filter of its own) is deferred with
    disclosure — stories #59..#66."""
    fx = Contract(tmp_data_dir, "c11-closed")
    # The complement arithmetic, as data: five values, two admitted, three not.
    assert set(INGEST_STATUSES) == ADMISSIBLE | (set(INGEST_STATUSES) - ADMISSIBLE), (
        "TC-INGEST-C11: the declared status set does not partition into the "
        "admitted pair and its complement."
    )
    assert ADMISSIBLE < set(INGEST_STATUSES), (
        "TC-INGEST-C11: the admitted set is not a proper subset of the "
        "vocabulary — the rule would be vacuous."
    )
    assert set(INGEST_STATUSES) - ADMISSIBLE == {
        "unreadable", "incomplete", "unmatched_assessment"}, (
        "TC-INGEST-C11: the non-admissible set drifted from the declared three."
    )
    # The closure: no sixth status can exist. The CHECK rejects the insert —
    # which is why the two-value rule is complete rather than merely current.
    with fx.handle.transaction() as tx:
        with pytest.raises(sqlite3.IntegrityError, match="(?i)check"):
            tx.execute(statement(
                "INSERT INTO submission (submission_id, cohort_id, student_ref, "
                "ingest_status, quarantined) VALUES (:s, :c, 'gus', "
                "'looks_fine_enough', 0)", issue="TS-62"),
                s="c11-sixth", c=COHORT)
    fx.close()


def test_tc_ingest_c11_reingestion_after_operator_action_rejoins_the_run(
        tmp_data_dir):
    """`TC-INGEST-C11` (re-ingestion half) — operator action re-enters the
    pipeline without mutating history: (a) a quarantined unit, completed and
    re-ingested, becomes a NEW submission row (`quarantined = 0`, same cohort —
    the producer-visible run linkage) while the old row stays exactly as it
    was; (b) a correction of an admitted document through `revise_document`
    mints a NEW document id with `parent_doc_id` set and the SAME
    `submission_id`, the original row untouched, and the replaced page's new
    text on the new row — never the old one."""
    # (a) The quarantined unit, completed by the operator, re-ingested.
    fx = Contract(tmp_data_dir, "c11-reingest")
    fx.add_roster("gus")
    one, two = fx.put(b"c11 p1"), fx.put(b"c11 p2")
    fx.script(one, {1: "Student: gus\nPage 1 of 4\nbody one"})
    fx.script(two, {1: "Student: gus\nPage 2 of 4\nbody two"})
    gap = fx.ingestor.ingest_submission([one, two], cohort_id=COHORT,
                                        package_version="v0")
    assert gap.ingest_status == "incomplete", (
        f"TC-INGEST-C11: the gapped ingest did not quarantine: "
        f"{gap.ingest_status}."
    )
    old_rows = fx.submission_rows()
    assert len(old_rows) == 1 and old_rows[0]["quarantined"] == 1, (
        f"TC-INGEST-C11: the gapped ingest's row: {dict(old_rows[0])}."
    )
    three, four = fx.put(b"c11 p3"), fx.put(b"c11 p4")
    fx.script(three, {1: "Student: gus\nPage 3 of 4\nbody three"})
    fx.script(four, {1: "Student: gus\nPage 4 of 4\nbody four"})
    done = fx.ingestor.ingest_submission([one, two, three, four],
                                         cohort_id=COHORT,
                                         package_version="v0")
    assert done.ingest_status == "ok", (
        f"TC-INGEST-C11: the completed re-ingest did not go ok: "
        f"{done.ingest_status} / {done.gates}."
    )
    assert done.submission_id != gap.submission_id, (
        "TC-INGEST-C11: the re-ingest reused the quarantined unit's id — the "
        "operator action must produce a NEW row, never rewrite the old one."
    )
    rows = {row["submission_id"]: row for row in fx.submission_rows()}
    assert set(rows) == {gap.submission_id, done.submission_id}, (
        f"TC-INGEST-C11: unexpected submission rows: {sorted(rows)}."
    )
    assert rows[gap.submission_id]["quarantined"] == 1 \
        and rows[gap.submission_id]["ingest_status"] == "incomplete", (
        f"TC-INGEST-C11: the quarantined row was mutated by the re-ingest: "
        f"{dict(rows[gap.submission_id])}."
    )
    assert rows[done.submission_id]["quarantined"] == 0, (
        f"TC-INGEST-C11: the completed re-ingest did not rejoin as admissible: "
        f"{dict(rows[done.submission_id])}."
    )
    assert rows[done.submission_id]["cohort_id"] == \
        rows[gap.submission_id]["cohort_id"], (
        "TC-INGEST-C11: the re-ingested unit left the cohort — the producer "
        "cannot show it rejoined the same run."
    )
    fx.close()

    # (b) The correction: revise_document mints a NEW document under the SAME
    # submission, original untouched.
    fx = Contract(tmp_data_dir, "c11-revise")
    report = _clean_fixture(fx, "revise")
    before = fx.documents("document_id = :d", d=report.document_id)[0]
    replacement = fx.put(b"c11 rev rescan")
    fx.script(replacement, {1: student_answer("gus",
                                              answer_text("Q1", "rescanned"))})
    new_id = fx.ingestor.revise_document(
        report.document_id, [PageReplacement(blob_hash=replacement, page_no=1)])
    after = fx.documents("document_id = :d", d=new_id)[0]
    assert new_id != report.document_id, (
        "TC-INGEST-C11: revise_document returned the same id — a correction "
        "must never mutate the row it was given."
    )
    assert after["parent_doc_id"] == report.document_id, (
        f"TC-INGEST-C11: the revision's parent is {after['parent_doc_id']!r}, "
        f"not the corrected document."
    )
    assert after["submission_id"] == before["submission_id"], (
        "TC-INGEST-C11: the revision left its submission — the corrected "
        "document does not rejoin the same run."
    )
    assert before["markdown"] == fx.documents(
        "document_id = :d", d=report.document_id)[0]["markdown"], (
        "TC-INGEST-C11: the original document's markdown changed under the "
        "revision — the row is not immutable."
    )
    assert "rescanned" in after["markdown"], (
        f"TC-INGEST-C11: the replacement page's text is not on the revision: "
        f"{after['markdown'][:120]}."
    )
    replaced = [row for row in fx.regions(new_id)
                if row["source_hash"] == replacement]
    assert replaced, (
        "TC-INGEST-C11: no region on the revision cites the replacement blob — "
        "the provenance claims a page the rescan did not produce."
    )
    fx.close()
