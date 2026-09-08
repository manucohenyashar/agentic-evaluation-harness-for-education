"""`CT-INGEST-10` — quarantines route to the operator, never to review
(`TC-INGEST-C10`).

Case of test plan §6.11.5; issue #49 (TS-62). Green by design — #40 landed the
routing.

The clause: quarantined items route to the **operator surface only**. No
quarantine item is reachable from the teacher review queue, ever (FR-INGEST-30,
R64). Setup-artifact failures are the one exception and surface on the uploading
teacher's screen instead (FR-INGEST-32) — a `reference`/`rubric`/`assessment`
artifact has no submission row to quarantine, so its failure escapes to the
caller as a refusal.

What is assertable on shipped code:

- **The routing artifact**: every failing route leaves exactly one submission
  row, `quarantined = 1`, an `ingest_status` from the five-value vocabulary,
  and a finding naming the gate that failed — the attribution an operator
  triage view is built from (per-gate columns, CT-INGEST-08, are its columns).
- **The setup exception**: setup kinds produce NO submission row whether they
  succeed or refuse — their failures are raised, not routed.
- **The negative routing**: after the full sweep, `review_queue` is empty —
  the teacher queue never received a quarantine item. The consumer halves are
  deferred with disclosure: M-REVIEW's admission rule (that the queue admits
  nothing gated) is `TC-REVIEW-C05`'s clause, already written ahead in
  `tests/contract/review/`; M-CONSOLE's quarantine view is story #123..#130.
  What a consumer cannot see, this producer cannot write — the empty-queue
  sweep is the producer half of that guarantee, at full strength here.
"""

from __future__ import annotations

import pytest

from aeh.ingest import IngestError
from tests.contract.ingest._doubles import (
    COHORT,
    INGEST_STATUSES,
    Contract,
    RefusingSanitizer,
    answer_text,
    selection_mark,
    student_answer,
)
from tests.support.store_api import statement

pytestmark = pytest.mark.contract


def _quarantine_routes(tmp_data_dir) -> list[tuple[str, Contract, object]]:
    """Every gate's failing route, as (label, fixture, report). The same
    builders C09 sweeps; here each report is read for its routing fields."""
    routes: list[tuple[str, Contract, object]] = []

    v0 = Contract(tmp_data_dir, "c10-v0", sanitizer=RefusingSanitizer("junk"))
    routes.append(("v0", v0, v0.ingestor.ingest_submission(
        [v0.put(b"c10 v0 pdf")], cohort_id=COHORT, package_version="v0",
        filenames={})))

    v1 = Contract(tmp_data_dir, "c10-v1")
    first, second = v1.put(b"c10 v1 p1"), v1.put(b"c10 v1 p2")
    v1.script(first, {1: "Page 1 of 4\nbody one"})
    v1.script(second, {1: "Page 2 of 4\nbody two"})
    routes.append(("v1", v1, v1.ingestor.ingest_submission(
        [first, second], cohort_id=COHORT, package_version="v0")))

    v2 = Contract(tmp_data_dir, "c10-v2")
    catalog, version = v2.catalog(["open"])
    source = v2.put(b"c10 v2 pdf")
    v2.script(source, {1: student_answer(
        None, selection_mark("Q1", state="resolved", option="A"))})
    routes.append(("v2", v2, v2.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version=version,
        filenames={source: "a.pdf"}, package_catalog=catalog)))

    v3 = Contract(tmp_data_dir, "c10-v3")
    source = v3.put(b"c10 v3 pdf")
    v3.script(source, {1: student_answer("ghost", answer_text("Q1", "answer"))})
    routes.append(("v3", v3, v3.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "a.pdf"})))

    v4 = Contract(tmp_data_dir, "c10-v4")
    v4.add_roster("gus")
    catalog, version = v4.catalog(["open"])
    source = v4.put(b"c10 v4 pdf")
    v4.script(source, {1: "Student: gus\nAssessment: pkg-other\n"
                          + answer_text("Q1", "answer")})
    routes.append(("v4", v4, v4.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version=version,
        filenames={source: "a.pdf"}, package_catalog=catalog)))
    return routes


def test_tc_ingest_c10_every_quarantine_routes_to_the_operator_with_attribution(
        tmp_data_dir):
    """`TC-INGEST-C10` (routing artifact half) — every failing gate route leaves
    exactly one submission row, `quarantined = 1`, a status from the five-value
    vocabulary, and a finding naming the gate that failed: the attribution an
    operator triage view is built from, never a bare status."""
    for label, fx, report in _quarantine_routes(tmp_data_dir):
        rows = fx.submission_rows()
        assert len(rows) == 1, (
            f"TC-INGEST-C10: the {label} route left {len(rows)} submission "
            "rows — a quarantine is one operator-routed unit."
        )
        assert rows[0]["quarantined"] == 1, (
            f"TC-INGEST-C10: the {label} route's stored row is not flagged "
            f"quarantined (row: {dict(rows[0])})."
        )
        assert rows[0]["ingest_status"] in INGEST_STATUSES, (
            f"TC-INGEST-C10: the {label} route's status "
            f"{rows[0]['ingest_status']!r} is outside the declared vocabulary."
        )
        assert report.ingest_status == rows[0]["ingest_status"], (
            f"TC-INGEST-C10: the {label} route's report status "
            f"{report.ingest_status!r} disagrees with the stored row "
            f"{rows[0]['ingest_status']!r}."
        )
        gates_in_findings = {finding["gate"] for finding in report.detail["findings"]
                             if "gate" in finding}
        assert label in gates_in_findings, (
            f"TC-INGEST-C10: the {label} route's findings "
            f"({report.detail['findings']}) do not name the gate that failed — "
            "the operator could not attribute the quarantine."
        )
        fx.close()


def test_tc_ingest_c10_setup_artifacts_never_enter_the_quarantine_table(
        tmp_data_dir):
    """`TC-INGEST-C10` (setup exception half) — setup kinds never produce a
    submission row: a clean `reference` ingests with none, and a corrupted
    reference (text layer diverging past the halt) REFUSES to the caller — the
    uploading teacher's screen — while the quarantine table stays untouched.
    The exception is structural: setup artifacts have no unit to quarantine."""
    fx = Contract(tmp_data_dir, "c10-setup")
    transcript = "the reference answer text"
    # The rasterizer's text_layer seam is keyed by the PDF CONTENT bytes (the
    # module passes the sanitized bytes, not the blob hash).
    good_bytes, bad_bytes = b"c10 reference good", b"c10 reference bad"
    good, bad = fx.put(good_bytes), fx.put(bad_bytes)
    fx.script(good, {1: transcript})
    fx.rasterizer.layer = {(good_bytes, 1): transcript}  # agrees: divergence 0
    fx.ingestor.ingest_document([good], kind="reference",
                                filenames={good: "a.pdf"})
    assert fx.submission_rows() == [], (
        "TC-INGEST-C10: a setup artifact produced a submission row — setup "
        "intake is not a quarantinable unit."
    )
    fx.script(bad, {1: transcript})
    fx.rasterizer.layer = {(bad_bytes, 1): "wholly unrelated layer words here"}
    with pytest.raises(IngestError, match="divergence"):
        fx.ingestor.ingest_document([bad], kind="reference",
                                    filenames={bad: "b.pdf"})
    assert fx.submission_rows() == [], (
        "TC-INGEST-C10: a refused setup artifact entered the quarantine table "
        "— its failure surfaces to the uploading teacher, not the operator "
        "triage view (FR-INGEST-32)."
    )
    for kind in ("rubric", "assessment"):
        artifact = fx.put(f"c10 {kind}".encode())
        fx.script(artifact, {1: student_answer(None, answer_text("Q1", "x"))})
        fx.ingestor.ingest_document([artifact], kind=kind,
                                    filenames={artifact: "a.pdf"})
    assert fx.submission_rows() == [], (
        "TC-INGEST-C10: a setup kind produced a submission row."
    )
    fx.close()


def test_tc_ingest_c10_no_quarantine_reaches_the_review_queue(tmp_data_dir):
    """`TC-INGEST-C10` (negative routing half) — after the full quarantine sweep
    the teacher review queue is empty: no gate outcome ever routed there. The
    consumer halves are deferred with disclosure — M-REVIEW's admission rule is
    `TC-REVIEW-C05` (written ahead in tests/contract/review/), and M-CONSOLE's
    quarantine view is stories #123..#130; the producer half held here is the
    stronger fact under them: the queue received nothing to admit."""
    for label, fx, _report in _quarantine_routes(tmp_data_dir):
        queue = fx.table("review_queue")
        assert queue == [], (
            f"TC-INGEST-C10: the {label} route left {len(queue)} review_queue "
            "row(s) — a quarantine reached the teacher surface."
        )
        fx.close()
    # And statically: the module's write surface has no route into the queue.
    from tests.contract.ingest._doubles import written_tables
    assert "review_queue" not in written_tables(), (
        "TC-INGEST-C10: an M-INGEST statement writes review_queue — the queue "
        "is reachable from the gateway after all."
    )
