"""`CT-INGEST-09` — the gate never scores (`TC-INGEST-C09`).

Case of test plan §6.11.5; issue #49 (TS-62). Green by design — #40 landed the
routing; the clause is what keeps it honest.

The clause: every gate outcome is a **routing decision and never a score**.
There is no path from a gate failure to a band, a zero, or a points value
(FR-INGEST-30, R13), and a consumer that receives a quarantined submission may
rely on nothing having been scored for it.

Three halves, each a different escape route for the clause break:

1. **The behavioural sweep** — drive every gate's failing route (V0 through V4)
   plus the clean route, then read every score-bearing table as a result set:
   EMPTY, not zero. The clause's consumer reliance is exactly an empty result
   set — there is no row whose value could be read as a score.
2. **The scan is not vacuous** — the same sweep's scan detects a hand-inserted
   `criterion_score` row for a QUARANTINED submission (the mutant's write shape:
   a zero banded to a gated unit), which is the executable form of "would go
   red if the clause broke": the row appears, the scan finds it, the reliance
   is broken and checkable.
3. **The statement graph** — no declared `M-INGEST` statement mentions a
   score-bearing table, read or write (the module "has no such write path",
   CT-INGEST-17's negative twin); and the same walker over a graph COPY with a
   mutant `INSERT INTO criterion_score` flags exactly the mutant, so the static
   half demonstrably fails on the clause break rather than passing vacuously.

Discriminator: a mutant that writes a zero (or a band) when a gate quarantines
turns halves 1 and 2 red while every FR case — which asserts the gates dict and
the status on the report — stays green.
"""

from __future__ import annotations

import re

import pytest

from tests.contract.ingest._doubles import (
    COHORT,
    ISSUE,
    SCORE_TABLES,
    Contract,
    RefusingSanitizer,
    answer_text,
    selection_mark,
    statement_texts,
    student_answer,
)
from tests.support.store_api import statement

pytestmark = pytest.mark.contract

#: Every score-bearing NAME the clause forbids, for the static text sweep — the
#: cohort-schema tables plus `band`, the package-schema definition table (not in
#: a cohort handle's database at all, so the behavioural sweep cannot and need
#: not read it; a statement naming it would still be a path toward a score).
SCORE_NAMES = frozenset(SCORE_TABLES) | {"band"}

_SCORE_WORD = re.compile(
    r"\b(" + "|".join(sorted(SCORE_NAMES)) + r")\b", re.IGNORECASE)
_SCORE_WRITE = re.compile(
    r"(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE|DELETE\s+FROM)\s+"
    r"(" + "|".join(sorted(SCORE_NAMES)) + r")\b", re.IGNORECASE)


def _assert_nothing_scored(fx: Contract) -> None:
    """The consumer's reliance, as an empty result set per score-bearing table."""
    for name in sorted(SCORE_TABLES):
        rows = fx.table(name)
        assert rows == [], (
            f"TC-INGEST-C09: gate routing left {len(rows)} row(s) in {name!r} "
            f"({rows[:2]}) — a gate outcome became a score."
        )


# -- the behavioural sweep over every gate's failing route ---------------------------


def test_tc_ingest_c09_no_gate_outcome_leaves_a_score_behind(tmp_data_dir):
    """`TC-INGEST-C09` half 1 — for the clean route and every gate's failing
    route (V0 unreadable, V1 incomplete, V2 structure, V3 identity, V4
    unmatched), the store's score-bearing tables read back EMPTY: no band, no
    zero, no points, no review entry was produced by any gate outcome."""
    # Clean route.
    clean = Contract(tmp_data_dir, "c09-clean")
    clean.add_roster("gus")
    source = clean.put(b"c09 clean pdf")
    clean.script(source, {1: student_answer("gus", answer_text("Q1", "answer"))})
    report = clean.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "a.pdf"})
    assert report.ingest_status == "ok", (
        f"TC-INGEST-C09: the clean route did not complete: "
        f"{report.ingest_status}."
    )
    _assert_nothing_scored(clean)
    clean.close()

    # V0: the sanitizer refuses the source.
    v0 = Contract(tmp_data_dir, "c09-v0", sanitizer=RefusingSanitizer("junk"))
    refused = v0.ingestor.ingest_submission(
        [v0.put(b"c09 v0 pdf")], cohort_id=COHORT, package_version="v0",
        filenames={})
    assert refused.gates["v0"] == "fail" and refused.ingest_status == "unreadable", (
        f"TC-INGEST-C09: the V0 route did not quarantine: {refused.gates}."
    )
    _assert_nothing_scored(v0)
    v0.close()

    # V1: a page-number ladder with a gap (declares 4, carries 2).
    v1 = Contract(tmp_data_dir, "c09-v1")
    first, second = v1.put(b"c09 v1 p1"), v1.put(b"c09 v1 p2")
    v1.script(first, {1: "Page 1 of 4\nbody one"})
    v1.script(second, {1: "Page 2 of 4\nbody two"})
    gapped = v1.ingestor.ingest_submission(
        [first, second], cohort_id=COHORT, package_version="v0")
    assert gapped.gates["v1"] == "fail" and gapped.ingest_status == "incomplete", (
        f"TC-INGEST-C09: the V1 route did not quarantine: {gapped.gates}."
    )
    _assert_nothing_scored(v1)
    v1.close()

    # V2: a selection where the package declares the question open.
    v2 = Contract(tmp_data_dir, "c09-v2")
    catalog, version = v2.catalog(["open"])
    source = v2.put(b"c09 v2 pdf")
    v2.script(source, {1: student_answer(
        None, selection_mark("Q1", state="resolved", option="A"))})
    mismatched = v2.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version=version,
        filenames={source: "a.pdf"}, package_catalog=catalog)
    assert mismatched.gates["v2"] == "fail", (
        f"TC-INGEST-C09: the V2 route did not quarantine: {mismatched.gates}."
    )
    _assert_nothing_scored(v2)
    v2.close()

    # V3: a student the roster does not know.
    v3 = Contract(tmp_data_dir, "c09-v3")
    source = v3.put(b"c09 v3 pdf")
    v3.script(source, {1: student_answer("ghost", answer_text("Q1", "answer"))})
    unknown = v3.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "a.pdf"})
    assert unknown.gates["v3"] == "unmatched" \
        and unknown.ingest_status == "incomplete", (
        f"TC-INGEST-C09: the V3 route did not quarantine: {unknown.gates}."
    )
    _assert_nothing_scored(v3)
    v3.close()

    # V4: an identifier that does not name the bound package.
    v4 = Contract(tmp_data_dir, "c09-v4")
    v4.add_roster("gus")
    catalog, version = v4.catalog(["open"])
    source = v4.put(b"c09 v4 pdf")
    v4.script(source, {1: "Student: gus\nAssessment: pkg-other\n"
                          + answer_text("Q1", "answer")})
    unmatched = v4.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version=version,
        filenames={source: "a.pdf"}, package_catalog=catalog)
    assert unmatched.ingest_status == "unmatched_assessment", (
        f"TC-INGEST-C09: the V4 route did not quarantine: "
        f"{unmatched.ingest_status} / {unmatched.gates}."
    )
    _assert_nothing_scored(v4)
    v4.close()


def test_tc_ingest_c09_the_scan_detects_a_mutant_score_row(tmp_data_dir):
    """`TC-INGEST-C09` half 2 — the empty sweep is not vacuous: hand-insert the
    mutant's write shape (a criterion zero banded to a QUARANTINED submission),
    and the same scan finds it; delete it and the reliance is restored. This is
    the executable discriminator — the clause break is detectable, not merely
    asserted absent."""
    fx = Contract(tmp_data_dir, "c09-mutant")
    source = fx.put(b"c09 mutant pdf")
    fx.script(source, {1: student_answer("ghost", answer_text("Q1", "answer"))})
    quarantined = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "a.pdf"})
    assert quarantined.gates["v3"] == "unmatched" and quarantined.gates["v0"] == "pass", (
        f"TC-INGEST-C09: the V3 route did not quarantine: {quarantined.gates}."
    )
    _assert_nothing_scored(fx)
    # The mutant's shape: a gate failure producing a banded score row.
    with fx.handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO criterion_score (submission_id, criterion_id, band) "
            "VALUES (:s, 'C1', 'zero')", issue=ISSUE),
            s=quarantined.submission_id)
    rows = fx.table("criterion_score")
    assert rows != [], (
        "TC-INGEST-C09: the score scan could not see a hand-inserted "
        "criterion_score row — the sweep would pass even with the clause "
        "broken, which is a broken oracle, not a kept clause."
    )
    assert rows[0]["submission_id"] == quarantined.submission_id, (
        f"TC-INGEST-C09: the detected score row is not the quarantined "
        f"submission's: {rows[0]}."
    )
    with fx.handle.transaction() as tx:
        tx.execute(statement("DELETE FROM criterion_score", issue=ISSUE))
    _assert_nothing_scored(fx)
    fx.close()


# -- the statement graph: no path from a gate to a score ------------------------------


def test_tc_ingest_c09_no_declared_statement_names_a_score_table():
    """`TC-INGEST-C09` half 3 — no `M-INGEST` statement mentions a score-bearing
    table, read OR write (the clause's "no path" is a graph property, stronger
    than "no quarantined run happened to write one"). Vacuity guards: the
    registry is non-empty and provably mentions the tables it does own; and the
    same walker over a mutant-injected COPY of the graph flags exactly the
    mutant."""
    texts = statement_texts()
    assert texts, "TC-INGEST-C09: the statement registry is empty — the walk is vacuous."
    owned = [name for name, sql in texts.items()
             if re.search(r"\bsubmission\b", sql, re.IGNORECASE)]
    assert owned, (
        "TC-INGEST-C09: no declared statement mentions `submission` — the walk "
        "sees no real SQL, so its silence about score tables proves nothing."
    )
    offenders = [name for name, sql in texts.items() if _SCORE_WORD.search(sql)]
    assert not offenders, (
        f"TC-INGEST-C09: M-INGEST statements name score-bearing tables: "
        f"{offenders} — the module has a path toward a score, read or write."
    )
    # The same walk over a mutant copy flags exactly the mutant.
    mutant = dict(texts)
    mutant["mutant-c09-zero"] = (
        "INSERT INTO criterion_score (submission_id, criterion_id, band) "
        "VALUES (:s, 'C1', 'zero')")
    flagged = [name for name, sql in mutant.items() if _SCORE_WORD.search(sql)]
    assert flagged == ["mutant-c09-zero"], (
        f"TC-INGEST-C09: the mutant walk flagged {flagged} — expected exactly "
        "the injected score write, so the walker demonstrably fails on the "
        "clause break."
    )
    # And the stricter write-shape walk agrees on the compliant graph.
    assert not [name for name, sql in texts.items() if _SCORE_WRITE.search(sql)], (
        "TC-INGEST-C09: a declared statement WRITES a score-bearing table."
    )
    # The type half of step 1 (a gate outcome's type must not be convertible to
    # a score type): every gate outcome and every status is a non-numeric word —
    # none is a number a points column could take, so no implicit coercion path
    # exists. The adversarial rule ("unreadable → lowest band") must ADD an
    # explicit mapping, and that mapping's statement is what the walk flags.
    from tests.contract.ingest._doubles import INGEST_STATUSES

    outcomes = set(INGEST_STATUSES) | {
        "pass", "fail", "not_run", "unmatched", "ambiguous",
        "match", "uncertain", "mismatch",
    }
    numeric = [value for value in outcomes
               if re.fullmatch(r"-?\d+(?:\.\d+)?", value)]
    assert not numeric, (
        f"TC-INGEST-C09: gate outcomes {numeric} are numeric — a gate outcome "
        "is directly convertible to a score value, which is the path the "
        "clause forbids."
    )
