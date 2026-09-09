"""`CT-DET-05` — the declared partial-credit policy (`TC-DET-C05`).

Case of test plan §6.11.11; issue #90 (TS-68). Green by design — `M-DET`
shipped via #246/#249.

The clause: multi-select applies the criterion's **declared** partial-credit
policy (`all_or_nothing` or `per_option`) and never infers one; where the
package declares nothing, that is a setup-time failure, not a runtime default.

The clause discriminator: the FR-level cases test cells 7-11 of the §7.8 table
one at a time; this case sweeps both declared policies against a
hand-computed grid of selections (exact, subset, superset, disjoint,
over-selected) with the EXACT credit per cell, corroborates the sweep through
the store path where the policy is read from the PACKAGE's declared column,
and then asserts the decisive negative at full strength: with no declared
policy the evaluation RAISES — the exact exception, for every selection state
including a blank answer (a criterion whose scoring rule does not exist is
refused as a criterion, not scored around), and nothing is written — no
inferred default ever grades a row.
"""

from __future__ import annotations

import pytest

from aeh.det import (
    POLICY_ALL_OR_NOTHING,
    POLICY_PER_OPTION,
    DeterministicEvaluator,
    UndeclaredPartialCreditPolicy,
    evaluate,
)
from tests.support.det_vocabulary import (
    open_det_store,
    seed_det_world,
    seed_selection_answers,
)

pytestmark = pytest.mark.contract

from tests.contract.det._doubles import ISSUE  # noqa: F401 — register citation

KEY = ("B", "D")
OPTIONS = ("A", "B", "C", "D", "E")

#: The hand-computed grid. Under `per_option` each selected option the key
#: does not contain cancels one earned credit, floored at zero:
#: credit = max(0, |sel ∩ key| − |sel \\ key|) / |key|. Under
#: `all_or_nothing` only the exact set earns anything.
GRID: tuple[tuple[tuple[str, ...], float, float], ...] = (
    # (selection, all_or_nothing credit, per_option credit)
    (("B", "D"), 1.0, 1.0),      # exact match
    (("B",), 0.0, 0.5),          # subset: 1 earned, nothing cancelled
    (("D",), 0.0, 0.5),          # the other half
    (("B", "D", "E"), 0.0, 0.5),  # superset: 2 earned, 1 cancelled
    (("B", "E"), 0.0, 0.0),      # 1 earned, 1 cancelled
    (("A",), 0.0, 0.0),          # disjoint, floored at zero
    (("A", "C"), 0.0, 0.0),      # disjoint, two wide
    (("B", "D", "A", "C"), 0.0, 0.0),  # 2 earned, 2 cancelled
)


def test_tc_det_c05_declared_policies_swept_against_hand_computed_scores():
    """`TC-DET-C05` (rung 0, swept) — every grid cell's credit is the declared
    policy's exact value under both policies, and the band is `correct` only
    on the exact match — the declared two-band scale is never exceeded even
    where the credit is fractional."""
    for selection, aon_credit, po_credit in GRID:
        aon = evaluate(
            content_state="present", selection_state="resolved",
            selection=selection, key=KEY, multi_select=True,
            partial_credit=POLICY_ALL_OR_NOTHING, option_set=OPTIONS,
        )
        po = evaluate(
            content_state="present", selection_state="resolved",
            selection=selection, key=KEY, multi_select=True,
            partial_credit=POLICY_PER_OPTION, option_set=OPTIONS,
        )
        exact = set(selection) == set(KEY)
        assert aon.credit == aon_credit, (
            f"TC-DET-C05: all_or_nothing on {selection} gave "
            f"{aon.credit}, expected {aon_credit}."
        )
        assert (aon.band == "correct") is exact, (
            f"TC-DET-C05: all_or_nothing band {aon.band!r} for {selection} — "
            "the band must be correct on the exact match only."
        )
        assert po.credit == po_credit, (
            f"TC-DET-C05: per_option on {selection} gave {po.credit}, "
            f"expected {po_credit} (max(0, |∩| − |\\\\|) / |key|)."
        )
        assert (po.band == "correct") is exact, (
            f"TC-DET-C05: per_option band {po.band!r} for {selection} — a "
            "fractional credit must not borrow the correct band."
        )


def test_tc_det_c05_the_package_declared_policy_is_what_applies(tmp_data_dir):
    """`TC-DET-C05` (the store corroboration) — two criteria keyed alike, one
    declaring `all_or_nothing` and one `per_option`: the cohort pass applies
    EACH criterion's OWN declared column, so the same selection earns
    different stored points under the two policies — read back from the
    written rows, not from the report. The policy is the package's, applied
    by lookup (`_doubles` discloses the direct column write: no pkg setter
    exists yet)."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, version, cohort_id = seed_det_world(
            store,
            submissions=("S01", "S02", "S03"),
            criteria=[
                {"criterion_id": "M-aon", "question_id": "Q1", "key": KEY,
                 "multi_select": True, "partial_credit": "all_or_nothing"},
                {"criterion_id": "M-po", "question_id": "Q2", "key": KEY,
                 "multi_select": True, "partial_credit": "per_option"},
            ],
        )
        seed_selection_answers(
            store, cohort_id,
            [
                {"submission_id": "S01", "selection": "B"},   # half the key
                {"submission_id": "S02", "selection": "B"},   # per-question doc
                {"submission_id": "S03", "selection": "B"},
            ],
        )
        # Each submission needs the selection on BOTH questions; the batch
        # helper writes one question per document, so seed Q2 explicitly.
        from tests.support.det_vocabulary import seed_answer_region

        for i in (1, 2, 3):
            document_id = f"doc-S{i:02d}"
            seed_answer_region(store, cohort_id, document_id, "Q2",
                               selection="B")

        DeterministicEvaluator(store).evaluate_cohort(run_id)

        rows = {
            (row["criterion_id"], row["submission_id"]): dict(row)
            for row in store.cohort(cohort_id).query(
                "SELECT criterion_id, submission_id, band, points FROM "
                "criterion_score WHERE submission_id LIKE 'S0%'"
            )
        }
        # The same half-key answer: incorrect under all_or_nothing (0.0
        # points), partial under per_option (half the correct band's 1.0).
        aon, po = rows[("M-aon", "S01")], rows[("M-po", "S01")]
        assert aon["band"] == "incorrect" and aon["points"] == 0.0, (
            f"TC-DET-C05: all_or_nothing stored {(aon['band'], aon['points'])}"
            " — the declared policy was not applied."
        )
        assert po["band"] == "incorrect" and po["points"] == pytest.approx(0.5), (
            f"TC-DET-C05: per_option stored {(po['band'], po['points'])} — "
            "the fractional credit did not land scaled to the correct band."
        )
        assert version  # the package version the policy columns live in
    finally:
        store.close()


def test_tc_det_c05_undeclared_policy_raises_and_writes_nothing(tmp_data_dir):
    """`TC-DET-C05` (the decisive negative) — a multi-select criterion whose
    package declares NO policy: every evaluation RAISES
    `UndeclaredPartialCreditPolicy` — the setup-time failure the clause names,
    not a runtime default — for every selection state, including a blank
    answer (the refusal is the criterion's: a scoring rule that does not
    exist is fixed at setup, not scored around). Nothing is written: no score
    row exists under an inferred policy."""
    # Kernel: the raise fires on the criterion's shape, whatever the read.
    for content_state, selection_state, selection in (
        ("present", "resolved", ("B",)),
        ("present", "resolved", ("B", "D")),
        ("present", "ambiguous", None),
        ("present", "multiple_marks", None),
        ("blank", None, None),
        ("absent", None, None),
    ):
        with pytest.raises(UndeclaredPartialCreditPolicy) as excinfo:
            evaluate(
                content_state=content_state,
                selection_state=selection_state,
                selection=selection,
                key=KEY,
                multi_select=True,
                partial_credit=None,
                option_set=OPTIONS,
            )
        assert "never infers" in str(excinfo.value) or "forbids inferring" in \
            str(excinfo.value), (
                "TC-DET-C05: the refusal does not name the no-inference rule."
            )

    # Store: the cohort pass refuses the same way, and the refusal is total.
    store = open_det_store(tmp_data_dir)
    try:
        run_id, _version, cohort_id = seed_det_world(
            store,
            submissions=("S01", "S02"),
            criteria=[
                {"criterion_id": "M-open", "question_id": "Q1", "key": KEY,
                 "multi_select": True, "partial_credit": None},
                {"criterion_id": "M-single", "question_id": "Q2",
                 "key": ("B",)},
            ],
        )
        seed_selection_answers(
            store, cohort_id,
            [
                {"submission_id": "S01", "selection": "B"},
                {"submission_id": "S02", "selection": "C"},
            ],
        )
        with pytest.raises(UndeclaredPartialCreditPolicy):
            DeterministicEvaluator(store).evaluate_cohort(run_id)
        rows = store.cohort(cohort_id).query(
            "SELECT criterion_id FROM criterion_score WHERE criterion_id = "
            "'M-open'"
        )
        assert list(rows) == [], (
            f"TC-DET-C05: {len(list(rows))} score rows exist for the "
            "undeclared-policy criterion — a default was applied before the "
            "raise."
        )
    finally:
        store.close()
