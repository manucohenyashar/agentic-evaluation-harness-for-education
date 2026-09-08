"""`CT-INGEST-19` — observability (`TC-INGEST-C19`).

Case of test plan §6.11.5; issue #49 (TS-62). Green by design — the columns
the signals are computed from are shipped (#36..#41).

The clause: the module emits `ocr_failure_rate`, unresolved-mark rate
(**separately** — the two have different remedies, and a merged metric sends
the operator to the wrong fix), pages-with-text-layer, mean and max
`text_layer_divergence`, per-gate pass/fail counts, quarantine count by gate,
description second-pass disagreement rate; per-region confidence is recorded
in a form supporting the §6.9 surface-proxy analysis (NFR-INGEST-07).

**Disclosed finding (G4, in `_doubles`, probe-backed):** the AGGREGATE signals
are not emitted anywhere — there is no metrics emission in the module;
`TC-INGEST-44` (TS-19, issue #48) is the open implementation story. What this
case holds at full strength is the producer half the aggregates are computed
from, with the clause's own emphasis asserted at the data level:

- the SEPARATION property: an OCR problem, an unresolved mark and an
  unresolved token are recorded in DISJOINT places — `content_state='blank'`
  on the region (remedy: re-scan/OCR), `selection_state='ambiguous'` with a
  NULL selection (remedy: operator reading), and the token in its OWN
  `unresolved_token` table (remedy: one cluster resolution) — no signal is
  folded into another's column, so the two rates and their different remedies
  stay computable separately;
- pages-with-text-layer and `text_layer_divergence` recorded on the document
  row (mean/max across runs are aggregate arithmetic over them);
- per-gate pass/fail counts and quarantine-by-gate derivable from the five
  gate columns and the findings' gate attribution — distributions asserted
  per column, never one merged total;
- per-region `ocr_conf` non-null on every stored region, untagged heads
  included (CT-INGEST-04's clause, #221).

`description_secondary` is always NULL — the second-pass disagreement signal
is Phase 2 (#39 landed the column; the pass is not implemented). The emission
and aggregation halves are M-STATS/M-INTEG's (stories #115..#118 and #73..#74)
— deferred with disclosure.
"""
from __future__ import annotations

from collections import Counter

import pytest

from tests.contract.ingest._doubles import (
    COHORT,
    Contract,
    RefusingSanitizer,
    answer_text,
    selection_mark,
    student_answer,
)

pytestmark = pytest.mark.contract


def test_tc_ingest_c19_the_separate_observables_are_recorded_in_disjoint_places(
        tmp_data_dir):
    """`TC-INGEST-C19` (the separation property) — one page carrying an OCR
    problem (a blank region), an unresolved mark (ambiguous selection) and an
    unresolved token ingests available-but-flagged (`low_confidence_ocr`,
    #221: the fixture's marginal readings at 0.50/0.40 sit below the
    confidence floor; the submission is NOT quarantined — the flag and the
    signals coexist), and the three signals are recorded in disjoint places:
    blank on `content_state`, the unresolved mark on `selection_state` with NO
    selection, the token ONLY in its own table keyed to its region — no signal
    folded into another's column. The document row carries the text-layer
    observables, per-region `ocr_conf` is non-null on EVERY stored row — the
    untagged `Student:` head included (CT-INGEST-04's clause, #221) — and
    `description_secondary` is Phase 2's NULL."""
    fx = Contract(tmp_data_dir, "c19-observe")
    fx.add_roster("gus")
    content = b"c19 observ pdf"
    source = fx.put(content)
    fx.script(source, {1: "Student: gus\n"
        "<!-- region: kind=transcribed_text question_id=Q1 conf=0.97 -->\n"
        "the present answer <unresolved>projekt</unresolved>\n"
        "<!-- /region -->\n"
        "<!-- region: kind=transcribed_text question_id=Q2 conf=0.50 "
        "state=blank -->\n\n<!-- /region -->\n"
        "<!-- region: kind=selection_mark question_id=Q3 "
        "selection_state=ambiguous conf=0.40 -->\n"
        "the mark as seen\n<!-- /region -->"})
    # A text layer that disagrees with the transcript: the divergence and the
    # pages-with-text-layer counts are recorded on the document, not halted
    # (the halt is reference-only — C14's clause).
    fx.rasterizer.layer = {(content, 1): "a wholly unrelated text layer"}
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "a.pdf"})
    assert report.ingest_status == "low_confidence_ocr", (
        f"TC-INGEST-C19: the marginal readings did not flag the submission: "
        f"{report.ingest_status} / {report.gates}."
    )
    assert fx.submission_rows()[0]["quarantined"] == 0, (
        "TC-INGEST-C19: the flagged submission quarantined — "
        "low_confidence_ocr is available to scoring (CT-INGEST-11), and the "
        "flag must not blur into a quarantine signal."
    )
    document = fx.documents()[0]
    assert document["pages_with_text_layer"] == 1, (
        f"TC-INGEST-C19: pages_with_text_layer is "
        f"{document['pages_with_text_layer']} — the signal was not recorded."
    )
    assert document["text_layer_divergence"] == 1.0, (
        f"TC-INGEST-C19: text_layer_divergence is "
        f"{document['text_layer_divergence']} — the measure was not recorded."
    )
    regions = {row["element_kind"]: row
               for row in fx.regions(document["document_id"])}
    assert {"Q1", "Q2", "Q3"} <= set(regions), (
        f"TC-INGEST-C19: the tagged regions did not store: {sorted(regions)}."
    )
    q1, q2, q3 = regions["Q1"], regions["Q2"], regions["Q3"]
    # Per-region confidence, the §6.9 surface-proxy input, on EVERY stored row
    # — the untagged head included (its confidence is the page's minimum tagged
    # reading, 0.40, the conservative direction).
    for label, region in sorted(regions.items()):
        assert region["ocr_conf"] is not None and 0 < region["ocr_conf"] <= 1, (
            f"TC-INGEST-C19: {label}'s ocr_conf is {region['ocr_conf']} — "
            "the per-region confidence was not recorded."
        )
    assert regions["text"]["ocr_conf"] == pytest.approx(0.40), (
        f"TC-INGEST-C19: the head region's ocr_conf is "
        f"{regions['text']['ocr_conf']!r}, not the page's minimum tagged "
        "reading — the untagged fragment's derived confidence moved."
    )
    # Signal 1 — the OCR problem: blank is a content_state, nothing else.
    assert q2["content_state"] == "blank" and not (q2["content"] or "").strip(), (
        f"TC-INGEST-C19: the blank page is not recorded as blank: "
        f"{dict(q2)}."
    )
    # Signal 2 — the unresolved mark: ambiguous on selection_state, NO
    # selection (CT-INGEST-05's biconditional), its own remedy.
    assert q3["selection_state"] == "ambiguous" and q3["selection"] is None, (
        f"TC-INGEST-C19: the unresolved mark is not recorded as ambiguous: "
        f"{dict(q3)}."
    )
    # Signal 3 — the unresolved token: ONLY in its own table, keyed to its own
    # region — never on a region column, never merged with the other two.
    tokens = fx.table("unresolved_token")
    assert [(row["token"], row["region_id"]) for row in tokens] \
        == [("projekt", q1["region_id"])], (
        f"TC-INGEST-C19: the unresolved tokens are {tokens} — not exactly the "
        "one token keyed to its region."
    )
    token_regions = {row["region_id"] for row in tokens}
    assert q2["region_id"] not in token_regions \
        and q3["region_id"] not in token_regions, (
        "TC-INGEST-C19: the blank or the ambiguous mark leaked into the token "
        "table — the signals are merged and the remedies blur."
    )
    assert q1["content_state"] == "present" and q1["selection_state"] is None, (
        f"TC-INGEST-C19: the token demoted its own region: {dict(q1)}."
    )
    # Phase 2's second pass: the column exists and is honestly NULL.
    assert all(row["description_secondary"] is None for row in regions.values()), (
        "TC-INGEST-C19: a description_secondary value appeared — the second "
        "pass is not implemented and must not be simulated."
    )
    fx.close()


def test_tc_ingest_c19_per_gate_counts_and_quarantine_attribution_are_derivable(
        tmp_data_dir):
    """`TC-INGEST-C19` (per-gate counts, quarantine by gate) — across a clean
    route and two failing routes, the gate columns carry INDEPENDENT
    distributions (a merged counter could not show a v1 failure beside
    all-passing v0 columns), and every quarantined row's findings attribute to
    the gate that failed — the quarantine count is BY gate, not in total."""
    routes = []
    clean = Contract(tmp_data_dir, "c19-clean")
    clean.add_roster("gus")
    source = clean.put(b"c19 clean pdf")
    clean.script(source, {1: student_answer("gus", answer_text("Q1", "fine"))})
    routes.append(("clean", clean, clean.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "a.pdf"})))
    gap = Contract(tmp_data_dir, "c19-gap")
    first, second = gap.put(b"c19 gap p1"), gap.put(b"c19 gap p2")
    gap.script(first, {1: "Page 1 of 4\nbody one"})
    gap.script(second, {1: "Page 2 of 4\nbody two"})
    routes.append(("gap", gap, gap.ingestor.ingest_submission(
        [first, second], cohort_id=COHORT, package_version="v0")))
    ghost = Contract(tmp_data_dir, "c19-ghost")
    source = ghost.put(b"c19 ghost pdf")
    ghost.script(source, {1: student_answer("ghost", answer_text("Q1", "x"))})
    routes.append(("ghost", ghost, ghost.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "a.pdf"})))

    rows = [row for _label, fx, _report in routes for row in fx.submission_rows()]
    assert len(rows) == 3, f"TC-INGEST-C19: expected three rows, got {len(rows)}."
    # Per-gate pass/fail counts: each column's own distribution, asserted
    # exactly — independent, never a merged total.
    columns = {"v0_integrity": {"pass": 3},
               "v1_pages": {"pass": 2, "fail": 1},
               "v2_structure": {"pass": 3},
               "v3_identity": {"pass": 2, "unmatched": 1},
               "v4_match": {"not_run": 3}}
    for column, expected in columns.items():
        counts = Counter(row[column] for row in rows)
        assert counts == Counter(expected), (
            f"TC-INGEST-C19: the {column} distribution is {dict(counts)}, "
            f"expected {expected} — the per-gate counts drifted."
        )
    # Quarantine count by gate: exactly the two failing rows quarantined, and
    # each route's findings attribute to ITS gate — v1's quarantine is not
    # recorded against v3's.
    quarantined = [row for row in rows if row["quarantined"] == 1]
    assert len(quarantined) == 2 \
        and {row["ingest_status"] for row in quarantined} == {"incomplete"}, (
        f"TC-INGEST-C19: the quarantined rows: "
        f"{[dict(r) for r in quarantined]}."
    )
    attributed = {label: {finding.get("gate")
                          for finding in report.detail["findings"]}
                  for label, _fx, report in routes}
    assert "v1" in attributed["gap"] and attributed["gap"] - {"v1"} == set(), (
        f"TC-INGEST-C19: the gap route's findings attribute to "
        f"{attributed['gap']} — not exactly its own gate."
    )
    assert "v3" in attributed["ghost"] and attributed["ghost"] - {"v3"} == set(), (
        f"TC-INGEST-C19: the ghost route's findings attribute to "
        f"{attributed['ghost']} — not exactly its own gate."
    )
    assert "v4" not in attributed["clean"] or \
        not any(finding.get("gate") == "v4" and "fail" in str(finding)
                for finding in routes[0][2].detail["findings"]), (
        "TC-INGEST-C19: the clean route carries a quarantine finding."
    )
    for _label, fx, _report in routes:
        fx.close()


def test_tc_ingest_c19_a_v0_refusal_names_v0_not_the_skipped_gates(
        tmp_data_dir):
    """`TC-INGEST-C19` (attribution under skips) — a V0 refusal quarantines
    before V1–V3 run, and the shipped columns keep the skipped gates' `pass`
    init (the C08 nuance): the attribution that survives is the FINDING's gate
    key, which names v0 — the operator's quarantine-by-gate count reads the
    finding, not the columns alone. Asserted so the aggregate cannot silently
    attribute skipped gates."""
    fx = Contract(tmp_data_dir, "c19-v0", sanitizer=RefusingSanitizer("junk"))
    report = fx.ingestor.ingest_submission(
        [fx.put(b"c19 v0 pdf")], cohort_id=COHORT, package_version="v0",
        filenames={})
    assert report.ingest_status == "unreadable", (
        f"TC-INGEST-C19: the V0 refusal did not quarantine: "
        f"{report.ingest_status}."
    )
    gates = {finding.get("gate") for finding in report.detail["findings"]}
    assert gates == {"v0"}, (
        f"TC-INGEST-C19: the refusal's findings attribute to {gates} — the "
        "quarantine must count by the gate that failed."
    )
    row = fx.submission_rows()[0]
    assert row["quarantined"] == 1 and row["ingest_status"] == "unreadable", (
        f"TC-INGEST-C19: the stored row: {dict(row)}."
    )
    fx.close()
