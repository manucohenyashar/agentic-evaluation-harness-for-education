"""`CT-INGEST-15` / `CT-INGEST-16` — V4 halts, proposes, never applies;
the cohort breaker (`TC-INGEST-C15`, `TC-INGEST-C16`).

Cases of test plan §6.11.5; issue #49 (TS-62). Green by design — #41 landed
the V4 match, the proposal table and the breaker.

C15's clause: the module **never reassigns** a submission to a different
assessment — a V4 mismatch may propose ranked candidates, recorded as a
PROPOSAL, applied only by a human (FR-INGEST-26); and BOTH `uncertain` and
`mismatch` halt scoring for the submission (sweeping both — covering only
`mismatch` is the plausible gap).

C16's clause: the V4 cohort circuit breaker halts ingestion, withholds run
start, and surfaces **one cohort-level finding** rather than N per-submission
triage items (FR-INGEST-28).

What is assertable on shipped code, probed:

- The mismatch record is the `assessment_match_proposal` row: candidates
  ranked, and the resolution columns (`resolution`, `resolved_at`) left NULL —
  the schema distinction the plan's oracle names. The module's whole write
  surface contains no statement that resolves a proposal: the only write into
  the table is the INSERT, whose column list omits the human's columns, so no
  ladder path can apply a candidate — the "no code path" half, held
  statically over paths never exercised.
- Both non-match outcomes quarantine the row with
  `ingest_status = unmatched_assessment` and the gate column carrying the
  specific outcome; nothing is scored behind either.
- The breaker trips INSIDE the gate-write transaction of the flagged unit and
  is ONE row per cohort (`cohort_id` primary key, INSERT OR IGNORE); every
  later `ingest_submission` for the cohort raises `IngestCohortBreakerTripped`
  at ENTRY — before any write — and a perfectly clean submission is refused
  too: the refusal is cohort-level, not per-student.

Consumer halves deferred with disclosure: "run start is withheld" is the
orchestrator/console preflight (M-ORCH #59..#66, M-CONSOLE #123..#130,
FR-CONSOLE-28); the producer half held here is the read path
(`Ingestor.cohort_breaker`) returning the row a preflight consumes, and the
entry refusal that makes every later unit halt. Resolving the proposal is
M-CONSOLE's write; nothing in M-INGEST can do it.
"""
from __future__ import annotations

import json
import re

import pytest

from aeh.ingest import (
    V4_BREAKER_MIN_ENV,
    V4_BREAKER_RATE_ENV,
    IngestCohortBreakerTripped,
)
from tests.contract.ingest._doubles import (
    COHORT,
    Contract,
    statement_texts,
)
from tests.support.store_api import statement

pytestmark = pytest.mark.contract

#: The assessment artifact's one page — the store's single semantic lineage the
#: V4 signals compare against.
ASSESSMENT_TEXT = "the photosynthesis answer key text"


def _region(question_id: str, body: str) -> str:
    return ("<!-- region: kind=transcribed_text "
            f"question_id={question_id} conf=0.9 -->\n{body}\n<!-- /region -->")


def _assessment(fx: Contract) -> str:
    """The assessment artifact: one lineage head, question-tagged, carrying an
    `Assessment:` identifier a candidate ranking can read."""
    src = fx.put(b"c15 assessment artifact")
    fx.script(src, {1: "Assessment: key-paper\n" + _region("Q1", ASSESSMENT_TEXT)})
    fx.ingestor.ingest_document([src], kind="assessment",
                                filenames={src: "key.pdf"})
    return fx.documents("kind = 'assessment'")[0]["document_id"]


def _submission(fx: Contract, name: str, printed: str, *regions: str):
    src = fx.put(name)
    fx.script(src, {1: "Student: gus\n" + f"Assessment: {printed}\n"
                    + "\n".join(regions)})
    return src


def _criterion_scores(fx: Contract) -> list:
    return fx.table("criterion_score")


# -- C15: the proposal, and both halting outcomes -------------------------------------


def test_tc_ingest_c15_a_mismatch_records_a_proposal_and_never_applies_one(
        tmp_data_dir):
    """`TC-INGEST-C15` (mismatch half) — the three-signal mismatch quarantines
    with a proposal row: ranked candidates, `v4_match = 'mismatch'`, and the
    resolution columns NULL. Nothing was applied: the assessment artifact is
    untouched, the submission grew no re-parented document, and nothing was
    scored. Statically, the module's write surface has NO path that resolves a
    proposal — the only statement touching the table is the INSERT, which
    omits the human's columns — and the same walk over a mutant registry copy
    (an `UPDATE ... SET resolution`) flags exactly the mutant."""
    fx = Contract(tmp_data_dir, "c15-proposal")
    fx.add_roster("gus")
    catalog, version = fx.catalog(["open"])
    assessment_id = _assessment(fx)
    before = fx.documents("document_id = :d", d=assessment_id)[0]
    src = _submission(fx, b"c15 mismatch pdf", "wrong-paper",
                      _region("Q2", "utterly different vocabulary here"))
    report = fx.ingestor.ingest_submission(
        [src], cohort_id=COHORT, package_version=version,
        filenames={src: "a.pdf"}, package_catalog=catalog)
    assert report.ingest_status == "unmatched_assessment" \
        and report.gates["v4"] == "mismatch", (
        f"TC-INGEST-C15: the three-signal mismatch did not halt: "
        f"{report.ingest_status} / {report.gates}."
    )
    rows = fx.submission_rows()
    assert rows[0]["quarantined"] == 1 and rows[0]["v4_match"] == "mismatch", (
        f"TC-INGEST-C15: the stored row: {dict(rows[0])}."
    )
    # The proposal record: one row, ranked candidates, the human's columns NULL.
    props = fx.table("assessment_match_proposal")
    assert len(props) == 1, (
        f"TC-INGEST-C15: {len(props)} proposal row(s) for one mismatch."
    )
    prop = props[0]
    assert prop["submission_id"] == report.submission_id \
        and prop["v4_match"] == "mismatch", (
        f"TC-INGEST-C15: the proposal row: {dict(prop)}."
    )
    assert prop["resolution"] is None and prop["resolved_at"] is None, (
        f"TC-INGEST-C15: the ladder wrote the human's columns: {dict(prop)}."
    )
    candidates = json.loads(prop["candidates"])
    assert candidates, "TC-INGEST-C15: the proposal names no candidates."
    scores = [candidate["score"] for candidate in candidates]
    assert scores == sorted(scores, reverse=True), (
        f"TC-INGEST-C15: the candidates are not ranked: {candidates}."
    )
    assert all(candidate["components"] for candidate in candidates), (
        "TC-INGEST-C15: a candidate carries no components — the ranking is "
        "unattributable."
    )
    assert candidates[0]["assessment_document_id"] == assessment_id, (
        f"TC-INGEST-C15: the top candidate is not the store's assessment: "
        f"{candidates[0]}."
    )
    # Nothing applied: the assessment artifact is untouched, the submission
    # grew no re-parented document, and nothing was scored.
    assert fx.documents("document_id = :d", d=assessment_id)[0]["markdown"] \
        == before["markdown"], (
        "TC-INGEST-C15: the assessment artifact changed — the proposal was "
        "applied, not recorded."
    )
    assert [doc for doc in fx.documents() if doc["parent_doc_id"]] == [], (
        "TC-INGEST-C15: the mismatch minted a re-parented document — a "
        "candidate was applied without a human."
    )
    assert _criterion_scores(fx) == [], (
        "TC-INGEST-C15: the mismatched submission was scored."
    )
    # Statically: the write surface cannot resolve a proposal. Vacuity guard
    # first — the walk must SEE the one real write.
    texts = statement_texts()
    assert texts, "TC-INGEST-C15: the statement registry is empty."
    writers = [name for name, sql in texts.items() if re.search(
        r"(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE|DELETE\s+FROM)\s+"
        r"assessment_match_proposal\b", sql, re.IGNORECASE)]
    assert writers == ["insert_match_proposal"], (
        f"TC-INGEST-C15: statements writing the proposal table: {writers}."
    )
    insert = texts["insert_match_proposal"]
    assert not re.search(r"\b(resolution|resolved_at)\b", insert, re.IGNORECASE), (
        f"TC-INGEST-C15: the ladder's INSERT names the human's columns: "
        f"{insert} — a code path touches what only a human may."
    )
    # The mutant demo: the same walk flags an injected apply-path exactly.
    mutant = dict(texts)
    mutant["mutant-c15-apply"] = (
        "UPDATE assessment_match_proposal SET resolution = 'confirmed', "
        "resolved_at = :now WHERE proposal_id = :p")
    flagged = [name for name, sql in mutant.items() if re.search(
        r"UPDATE\s+assessment_match_proposal\b", sql, re.IGNORECASE)]
    assert flagged == ["mutant-c15-apply"], (
        f"TC-INGEST-C15: the mutant walk flagged {flagged} — expected exactly "
        "the injected apply-path."
    )
    fx.close()


def test_tc_ingest_c15_both_uncertain_and_mismatch_halt_scoring(
        tmp_data_dir):
    """`TC-INGEST-C15` (the sweep) — BOTH non-match outcomes halt scoring for
    the submission: `uncertain` (one dissenting signal) and `mismatch` (all
    three) each leave the row quarantined with
    `ingest_status = unmatched_assessment`, the gate column naming the specific
    outcome, the finding attributed to v4, and no score anywhere. The
    `uncertain` outcome records NO proposal — proposing is the mismatch's
    specific record — and its escalation verdict is recorded in the signals,
    never applied."""
    routes = []
    # mismatch: identifier, structural AND semantic all disagree.
    mismatch = Contract(tmp_data_dir, "c15-halt-mismatch")
    mismatch.add_roster("gus")
    catalog, version = mismatch.catalog(["open"])
    _assessment(mismatch)
    src = _submission(mismatch, b"c15 halt mismatch", "wrong-paper",
                      _region("Q2", "utterly different vocabulary here"))
    routes.append(("mismatch", mismatch, mismatch.ingestor.ingest_submission(
        [src], cohort_id=COHORT, package_version=version,
        filenames={src: "a.pdf"}, package_catalog=catalog)))
    # uncertain: exactly ONE dissenting signal (the printed identifier).
    uncertain = Contract(tmp_data_dir, "c15-halt-uncertain")
    uncertain.add_roster("gus")
    catalog, version = uncertain.catalog(["open"])
    _assessment(uncertain)
    src = _submission(uncertain, b"c15 halt uncertain", "other-name",
                      _region("Q1", "the photosynthesis answer words"))
    routes.append(("uncertain", uncertain, uncertain.ingestor.ingest_submission(
        [src], cohort_id=COHORT, package_version=version,
        filenames={src: "a.pdf"}, package_catalog=catalog)))

    for outcome, fx, report in routes:
        assert report.ingest_status == "unmatched_assessment" \
            and report.gates["v4"] == outcome, (
            f"TC-INGEST-C15 ({outcome}): did not halt with its own verdict: "
            f"{report.ingest_status} / {report.gates}."
        )
        rows = fx.submission_rows()
        assert rows[0]["quarantined"] == 1 and rows[0]["v4_match"] == outcome, (
            f"TC-INGEST-C15 ({outcome}): the stored row: {dict(rows[0])}."
        )
        assert any(finding.get("gate") == "v4"
                   for finding in report.detail["findings"]), (
            f"TC-INGEST-C15 ({outcome}): the halt is not attributed to v4: "
            f"{report.detail['findings']}."
        )
        assert _criterion_scores(fx) == [], (
            f"TC-INGEST-C15 ({outcome}): the halted submission was scored."
        )
        proposals = fx.table("assessment_match_proposal")
        assert (len(proposals) == 1) == (outcome == "mismatch"), (
            f"TC-INGEST-C15 ({outcome}): {len(proposals)} proposal row(s) — "
            "proposing is the mismatch's record alone."
        )
        fx.close()


# -- C16: the cohort breaker -----------------------------------------------------------


def test_tc_ingest_c16_the_breaker_halts_the_cohort_with_one_finding(
        tmp_data_dir, monkeypatch):
    """`TC-INGEST-C16` — trip the breaker (the declared knobs, at test scale:
    a 0% rate over a 2-submission minimum) and assert the three things
    together. ONE cohort-level finding: two units flagged, yet exactly one
    `v4_cohort_breaker` row — the schema's `cohort_id` primary key makes the
    count structural, not caller discipline. Ingestion halts: the next call
    for the cohort raises `IngestCohortBreakerTripped` at ENTRY, writing
    nothing — and a perfectly clean submission is refused too, so the refusal
    cannot be misread as a per-student problem. Run start withheld: the read
    path a preflight consumes (`cohort_breaker`) returns the row; the preflight
    itself is M-CONSOLE's (FR-CONSOLE-28, stories #123..#130) — deferred with
    disclosure."""
    monkeypatch.setenv(V4_BREAKER_MIN_ENV, "2")
    monkeypatch.setenv(V4_BREAKER_RATE_ENV, "0.0")
    fx = Contract(tmp_data_dir, "c16-breaker")
    fx.add_roster("gus")
    catalog, version = fx.catalog(["open"])
    _assessment(fx)
    # Two flagged units: the first cannot trip (below the minimum), the second
    # trips inside its own transaction. ONE row, not two findings.
    first = _submission(fx, b"c16 bad one", "wrong-paper",
                        _region("Q2", "utterly different vocabulary here"))
    one = fx.ingestor.ingest_submission(
        [first], cohort_id=COHORT, package_version=version,
        filenames={first: "a.pdf"}, package_catalog=catalog)
    assert one.ingest_status == "unmatched_assessment" \
        and fx.table("v4_cohort_breaker") == [], (
        f"TC-INGEST-C16: the first flagged unit tripped below the minimum: "
        f"{[dict(r) for r in fx.table('v4_cohort_breaker')]}."
    )
    second = _submission(fx, b"c16 bad two", "wrong-paper",
                         _region("Q2", "still nothing alike here"))
    two = fx.ingestor.ingest_submission(
        [second], cohort_id=COHORT, package_version=version,
        filenames={second: "a.pdf"}, package_catalog=catalog)
    assert two.ingest_status == "unmatched_assessment", (
        f"TC-INGEST-C16: the second flagged unit did not complete its own "
        f"quarantine: {two.ingest_status}."
    )
    breakers = fx.table("v4_cohort_breaker")
    assert len(breakers) == 1, (
        f"TC-INGEST-C16: {len(breakers)} breaker row(s) for two flagged units "
        "— the clause demands ONE cohort-level finding, not one per "
        "submission."
    )
    row = breakers[0]
    assert row["cohort_id"] == COHORT and row["flagged"] == 2 \
        and row["ingested"] == 2, (
        f"TC-INGEST-C16: the breaker row: {dict(row)}."
    )
    assert COHORT in row["finding"] and "cohort" in row["finding"].lower(), (
        f"TC-INGEST-C16: the finding does not name the cohort: "
        f"{row['finding'][:120]}."
    )
    # The read path a run-start preflight consumes returns the row.
    assert fx.ingestor.cohort_breaker(COHORT) is not None, (
        "TC-INGEST-C16: the breaker read path sees nothing — a preflight "
        "could not withhold the run."
    )
    # Ingestion halts at ENTRY, writing nothing — for a BAD submission…
    rows_before = len(fx.submission_rows())
    with pytest.raises(IngestCohortBreakerTripped, match="cohort"):
        bad = _submission(fx, b"c16 bad three", "wrong-paper",
                          _region("Q2", "more different words again"))
        fx.ingestor.ingest_submission(
            [bad], cohort_id=COHORT, package_version=version,
            filenames={bad: "a.pdf"}, package_catalog=catalog)
    # …and for a CLEAN one — the refusal is cohort-level, never per-student.
    clean = _submission(fx, b"c16 clean", "pkg-49",
                        _region("Q1", ASSESSMENT_TEXT))
    with pytest.raises(IngestCohortBreakerTripped, match="cohort"):
        fx.ingestor.ingest_submission(
            [clean], cohort_id=COHORT, package_version=version,
            filenames={clean: "a.pdf"}, package_catalog=catalog)
    assert len(fx.submission_rows()) == rows_before, (
        "TC-INGEST-C16: a breaker-refused call wrote a submission row — the "
        "halt is not at entry."
    )
    assert fx.table("v4_cohort_breaker") == breakers, (
        "TC-INGEST-C16: a refused call grew the breaker table."
    )
    fx.close()
