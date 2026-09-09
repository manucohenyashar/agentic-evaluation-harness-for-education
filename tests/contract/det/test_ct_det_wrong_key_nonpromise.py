"""`CT-DET-14` — the non-promise: no claim that a key is right (`TC-DET-C14`).

Case of test plan §6.11.11; issue #90 (TS-68). Green by design — `M-DET`
shipped via #246/#249.

The clause: **not promised** — this module makes no claim that a key is right.
It compares against the key it was given; a wrong key produces **confidently
wrong scores** until corrected, which is why `CT-DET-07` exists and why key
corrections are versioned.

The clause discriminator: a promise-shaped test would assert the module
detects or flags a wrong key; this case asserts the opposite, exactly —
- **the promised behaviour**: a wrong key evaluates without error, to
  `incorrect` at 0.0 with `state='final'` — and the wrong-key rows are
  shape-identical to right-key rows: same columns, same state, same routing,
  same decided_by. Nothing marks them, because the module has no basis to
  mark them;
- **the non-promise, structurally**: no emitted name anywhere — report field,
  summary field or audit_record column — carries validation vocabulary. The
  module does not even name the concept;
- **reproducibility is not correctness**: two evaluations of the same
  wrong-key world write byte-identical rows — determinism holds — and they
  are identical AND wrong, which is the whole point;
- **the compensating machinery**: the versioned correction (`FR-PKG-18`) —
  a new package version carrying the right key — re-derives the four grades
  to correct while the old grades' audit records still resolve to the old
  key (`CT-DET-07`'s property, spot-checked here; C07 owns the deep case).

**Disclosed construction**: `M-GRADE` and `M-CONSOLE` (the consumers this
clause's blast radius names) have not landed, so the consumer-facing claim is
asserted at the data level — the score rows and audit records a grader will
read carry no validation marker to inherit.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from aeh.det import (
    CriterionSummary,
    DeterministicEvaluator,
    DeterministicReport,
)
from aeh.pkg import PackageCatalog
from tests.support.det_vocabulary import (
    open_det_store,
    seed_det_world,
    seed_selection_answers,
)

pytestmark = pytest.mark.contract

from tests.contract.det._doubles import ISSUE  # noqa: F401 — register citation

#: The vocabulary a validation claim would be spelled with. Any emitted name
#: carrying one of these stems is a promise the clause does not make.
VALIDATION_STEMS = ("valid", "verif", "confirm", "trust", "attest", "checked")

_SUBMISSIONS = ("S1", "S2", "S3", "S4")


def _seed_wrong_key_world(store):
    """Four submissions answer B on both questions; `M1`'s published key is
    C — wrong — while `M2`'s is B, the control. Returns `(run_id, v1,
    cohort_id)`."""
    run_id, version, cohort_id = seed_det_world(
        store,
        submissions=_SUBMISSIONS,
        criteria=[
            {"criterion_id": "M1", "question_id": "Q1", "key": ("C",)},
            {"criterion_id": "M2", "question_id": "Q2", "key": ("B",)},
        ],
    )
    seed_selection_answers(
        store, cohort_id,
        [{"submission_id": s, "selection": "B"} for s in _SUBMISSIONS],
    )
    # M2's regions too (the batch helper writes Q1 only).
    from tests.support.det_vocabulary import seed_answer_region

    for s in _SUBMISSIONS:
        seed_answer_region(store, cohort_id, f"doc-{s}", "Q2", selection="B")
    return run_id, version, cohort_id


def _score_rows(store, cohort_id):
    return [dict(r) for r in store.cohort(cohort_id).query(
        "SELECT * FROM criterion_score ORDER BY criterion_id, submission_id"
    )]


def test_tc_det_c14_a_wrong_key_scores_confidently_wrong(tmp_data_dir):
    """`TC-DET-C14` (the promised behaviour + the non-promise) — every B
    answer against the C key grades `incorrect` at 0.0, `state='final'`, with
    no exception and no alert; the wrong-key rows differ from the control's
    right-key rows in NOTHING but the band and points the key produced; and
    no emitted name — report field, summary field or audit_record column —
    carries validation vocabulary. The module does not flag the wrong key,
    and it does not even name the concept of trying."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, _v1, cohort_id = _seed_wrong_key_world(store)
        report = DeterministicEvaluator(store).evaluate_cohort(run_id)

        # Confidently wrong: full pass, no error, all four graded incorrect.
        assert report.evaluations == 8 and report.correct == 4, (
            "TC-DET-C14: the pass did not run to completion over both "
            "criteria."
        )
        rows = _score_rows(store, cohort_id)
        wrong = [r for r in rows if r["criterion_id"] == "M1"]
        right = [r for r in rows if r["criterion_id"] == "M2"]
        assert len(wrong) == 4 and len(right) == 4
        for row in wrong:
            assert row["band"] == "incorrect" and row["points"] == 0.0, (
                f"TC-DET-C14: a wrong-key row read {row['band']!r}/"
                f"{row['points']!r} — the module second-guessed the key it "
                "was given."
            )
            assert row["state"] == "final" and row["routing"] == "auto", (
                f"TC-DET-C14: the wrong-key row is {row['state']!r}/"
                f"{row['routing']!r} — a hedge the module has no basis for."
            )
        # Shape-identical to right-key rows: same columns, same state,
        # same routing — nothing marks the wrongness.
        assert set(wrong[0].keys()) == set(right[0].keys())
        assert {r["state"] for r in wrong} == {r["state"] for r in right}
        assert {r["routing"] for r in wrong} == {r["routing"] for r in right}
        # No alert either: the module's only alarm is a scanning alarm.
        assert report.alerts == ()

        # The non-promise, structural: no emitted name carries validation
        # vocabulary.
        audit_row = store.durable().query(
            "SELECT * FROM audit_record LIMIT 1"
        )[0]
        emitted = (
            {f.name for f in dataclasses.fields(DeterministicReport)}
            | {f.name for f in dataclasses.fields(CriterionSummary)}
            | set(audit_row.keys())
        )
        offenders = {
            name for name in emitted
            if any(stem in name.lower() for stem in VALIDATION_STEMS)
        }
        assert not offenders, (
            f"TC-DET-C14: the emission carries validation vocabulary: "
            f"{sorted(offenders)} — a claim of key correctness grew."
        )
    finally:
        store.close()


def test_tc_det_c14_reproducible_is_not_correct_but_correctable(tmp_data_dir):
    """`TC-DET-C14` (the differential + the compensation) — two evaluations
    of the same wrong-key world write byte-identical M1 rows: determinism
    holds, and it holds over WRONG values — reproducibility is not a claim
    that the key is right. The compensating machinery is the versioned
    correction: a new package version carries the right key (`FR-PKG-18` —
    the old version's key is untouched), the re-derivation flips all four
    grades to correct, and the audit trail keeps both versions — each old
    grade still resolving to the old key bytes it was graded by."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, v1, cohort_id = _seed_wrong_key_world(store)
        evaluator = DeterministicEvaluator(store)
        evaluator.evaluate_cohort(run_id)

        def m1_bytes() -> bytes:
            rows = store.cohort(cohort_id).query(
                "SELECT submission_id, band, points, state, routing FROM "
                "criterion_score WHERE criterion_id = 'M1' ORDER BY "
                "submission_id"
            )
            return json.dumps(
                [list(r) for r in rows], sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")

        first_bytes = m1_bytes()
        report = evaluator.evaluate_cohort(run_id)
        second_bytes = m1_bytes()
        assert second_bytes == first_bytes, (
            "TC-DET-C14: the two evaluations differ — determinism broke."
        )
        # Identical AND wrong: every row in both passes says incorrect.
        assert first_bytes.count(b'"incorrect"') == 4, (
            "TC-DET-C14: the byte-golden rows are not all incorrect — the "
            "wrong key did not produce confidently wrong scores."
        )
        assert report.incorrect >= 4

        # The compensation: a VERSIONED correction (FR-PKG-18) — a new
        # version carrying the right key, the old version untouched.
        catalog = PackageCatalog(store.package("pkg-det"), package_id="pkg-det")
        v2 = catalog.create_version(parent=v1)
        catalog.set_answer_key(v2, "M1", ("B",))
        old_key = store.package("pkg-det").query(
            "SELECT answer_key FROM criterion WHERE package_version_id = :v "
            "AND criterion_id = 'M1'",
            v=v1,
        )[0]["answer_key"]
        assert json.loads(old_key) == ["C"], (
            "TC-DET-C14: the old version's key moved — a correction must "
            "leave the version it corrects intact."
        )

        changed = evaluator.rederive_for_key_change(cohort_id, "M1", v2)
        assert changed.scores_changed == 4 and changed.panel_units_enqueued == 0
        rows = _score_rows(store, cohort_id)
        assert all(
            r["band"] == "correct" and r["points"] == 1.0
            for r in rows if r["criterion_id"] == "M1"
        ), "TC-DET-C14: the correction did not land on every wrong row."

        # The audit trail keeps both versions, each grade answerable to the
        # key that produced it (CT-DET-07, spot-checked).
        audits = store.durable().query(
            "SELECT package_version_id, answer_key_ref FROM audit_record "
            "WHERE criterion_id = 'M1' ORDER BY package_version_id"
        )
        assert {a["package_version_id"] for a in audits} == {v1, v2}
        for a in audits:
            ref_version, ref_key = a["answer_key_ref"].split(":", 1)
            assert ref_version == a["package_version_id"]
            expected = '["C"]' if a["package_version_id"] == v1 else '["B"]'
            assert ref_key == expected, (
                f"TC-DET-C14: {a['answer_key_ref']!r} does not resolve to the "
                "key that produced the grade."
            )
    finally:
        store.close()
