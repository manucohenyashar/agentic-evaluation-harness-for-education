"""`TC-STATS-25` / `ADV-09` — the operational-side attack on the admissible-label filter.

Test plan §6.6 (`ADV-09`) and §5.16 (`TC-STATS-25`), issue #119 (TS-42). This is
the `M-STATS` half of `RISK-07` — the `M-DET` half lives at
`tests/integration/det/test_det_statistical_separation.py` and its closing
disclosure names this case as its counterpart: *"When `M-STATS` lands,
`TC-STATS-25` attacks its functions from the operational side."*

**Oracle: prohibition assertion.** The pass criterion is that no path admits
operational labels into an agreement figure, and the figure's n equals the blind
judged count — 20 here, over the plan's own matrix (`TC-STATS-01`'s table, hand
computations shared with that case: κ = 173/273, QWK = 123/148, α = 17/20). The
40 operational labels **disagree** (band 1, teacher band 4), so a filter that
admits any of them moves po, pe *and* n — both the exact κ and the exact n are
live discriminators (`TC-STATS-C06`'s review lesson: agreeing contamination can
pass by luck of the arithmetic).

Three legs, each a distinct attack surface:

1. **the argument matrix** — every query construction a caller can hand
   `agreement()` (unscoped, mistyped criterion, wrong-family scoring model,
   empty model string) over a store holding the full contaminated population;
2. **the direct write** — rows of every inadmissible class inserted into the
   `label` table with raw SQL, bypassing `record_label` entirely, in the column
   shape `upsert_label` ships (`M-REVIEW` owns the mode column, not the row —
   the det leg's disclosed-bypass discipline, issue #88). The store cannot
   prevent the write; the filter must still refuse it;
3. **the statement registry** — every registered statement that touches the
   `label` table reads it wholesale and predicates on nothing but the cohort:
   the admissibility conjunction lives exactly once, in the module's own filter
   (`NFR-STATS-04`), and a SQL-side re-spelling would be a second definition
   that can drift. The det side asserts the inverse shape by design — its
   exclusion is SQL, because the mode column is `aeh.det`'s.

**Isolation: rung 2** — real store, real label rows, real Tier D statistics; no
provider is reachable (`network_guard` is autouse and each case asserts it).
"""

from __future__ import annotations

import sqlite3
from fractions import Fraction
from pathlib import Path

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab
from tests.support.impl import REVIEW_MODULE, STATS_MODULE, require

pytestmark = pytest.mark.integration

#: The plan's 20 blind judged labels, as a contingency table over
#: (system band, teacher band) — the hand reference's cells, shared with
#: `TC-STATS-01`'s artifact case.
T1_TABLE: dict[tuple[int, int], int] = {
    (1, 1): 6, (1, 2): 2, (2, 2): 5, (2, 3): 2, (3, 3): 4, (3, 4): 1,
}
T1_N = 20
T1_KAPPA = Fraction(173, 273)
T1_QWK = Fraction(123, 148)
T1_ALPHA = Fraction(17, 20)

DET_CRITERION = "C-DET"
OPERATIONAL_TYPES = ("accept", "edit", "override")
CALL = dict(vocab.EMPTY_DATA_CALL["agreement"])

#: The attack rows, one per inadmissible class (`vocab`'s declared table): the
#: field values that make each one inadmissible, written as a disagreeing pair
#: so admitting it moves the exact κ. `label_type` and `evaluation_mode` name
#: the class; `saw_system_output` is 1 exactly for the class that says so.
_ATTACK_ROWS: list[tuple[str, dict[str, object]]] = [
    ("attack-op", {"label_type": "operational", "evaluation_mode": "judged",
                   "saw_system_output": 1}),
    ("attack-saw", {"label_type": "blind", "evaluation_mode": "judged",
                    "saw_system_output": 1}),
    ("attack-det", {"label_type": "blind", "evaluation_mode": "deterministic",
                    "saw_system_output": 0}),
    ("attack-grade", {"label_type": "whole_grade", "evaluation_mode": "judged",
                      "saw_system_output": 0}),
]

#: The deliberate query constructions, leg 1: every spelling of "give me a
#: wider figure" the signature admits. Each is asserted, below, to return
#: either the same figure (n = 20, κ = 173/273) or an absence value — never a
#: wider population.
_ATTACK_CALLS: list[tuple[str, dict[str, object]]] = [
    ("unscoped, no criterion, no model, no scope",
     {"criterion_id": None, "scoring_model": None, "scope": None,
      "backend_profile": None, "panel_build_ref": None}),
    ("unscoped criterion with a model named",
     {"criterion_id": None, "scoring_model": "atomic"}),
    ("keyed criterion, model defaulted to the declared one",
     {"criterion_id": "C-01", "scoring_model": None}),
    ("keyed criterion, model named",
     {"criterion_id": "C-01", "scoring_model": "atomic"}),
    ("keyed criterion, WRONG-family model named",
     {"criterion_id": "C-01", "scoring_model": "holistic"}),
    ("keyed criterion, empty model string",
     {"criterion_id": "C-01", "scoring_model": ""}),
    ("mistyped criterion — hoping case hides the narrow",
     {"criterion_id": "c-01", "scoring_model": "atomic"}),
    ("absent criterion — hoping absence hides the narrow",
     {"criterion_id": "C-404", "scoring_model": "atomic"}),
    ("unscoped with an unscoped scope",
     {"criterion_id": "C-01", "scoring_model": "atomic", "scope": None}),
]


def _blind_judged() -> list[broken.Label]:
    """The 20, cell by cell, on the matrix's judged criterion."""
    labels = []
    for index, ((system, teacher), count) in enumerate(sorted(T1_TABLE.items())):
        for j in range(count):
            labels.append(
                broken.Label(
                    label_id=f"blind-{index}-{j}",
                    criterion_id="C-01",
                    band=system,
                    teacher_band=teacher,
                )
            )
    return labels


def _operational() -> list[broken.Label]:
    """The 40, disagreeing — the contamination the attack tries to walk in."""
    return [
        broken.Label(
            label_id=f"op-{i}",
            label_type=OPERATIONAL_TYPES[i % 3],
            origin=OPERATIONAL_TYPES[i % 3],
            criterion_id="C-01",
            saw_system_output=True,
            band=1,
            teacher_band=4,
        )
        for i in range(40)
    ]


def _deterministic() -> list[broken.Label]:
    """The 15 blind labels on the deterministic criterion — inadmissible by mode."""
    return [
        broken.Label(
            label_id=f"det-{i}",
            criterion_id=DET_CRITERION,
            evaluation_mode="deterministic",
            band=1 + (i % 4),
            teacher_band=1 + (i % 4),
        )
        for i in range(15)
    ]


def _seed_store(tmp_data_dir: Path) -> None:
    """The contaminated store: 20 blind judged + 40 operational + 15 deterministic."""
    record_label = require(REVIEW_MODULE, "record_label", issue="#110")
    for label in _blind_judged() + _operational() + _deterministic():
        record_label(data_dir=tmp_data_dir, label=label)


def _assert_the_blind_figure(figure: object, context: str) -> None:
    """The prohibition's positive half: the figure is the blind population's own."""
    figure_cls = require(STATS_MODULE, "AgreementFigure", issue="#115")
    assert isinstance(figure, figure_cls), (
        f"{context}: the attack produced {figure!r}; the figure for the plan's "
        "matrix is a computed value, and the absence values the attack hits are "
        "asserted at their call sites"
    )
    assert figure.n == T1_N, (
        f"{context}: the figure's population is {figure.n}; the blind judged "
        "count is 20, and no wider figure is representable (FR-STATS-01, RISK-07)"
    )
    assert figure.kappa == pytest.approx(float(T1_KAPPA)), (
        f"{context}: kappa = {figure.kappa!r}; the blind population's own hand "
        f"figure is {float(T1_KAPPA):.6f} (173/273) — an operational label that "
        "got in moves it (RISK-07)"
    )
    assert figure.qwk == pytest.approx(float(T1_QWK)), (
        f"{context}: qwk = {figure.qwk!r}, expected {float(T1_QWK):.6f} (123/148)"
    )
    assert figure.ordinal_alpha == pytest.approx(float(T1_ALPHA)), (
        f"{context}: alpha = {figure.ordinal_alpha!r}, expected "
        f"{float(T1_ALPHA):.6f} (17/20)"
    )


def test_tc_stats_25_no_query_construction_widens_the_population(
    tmp_data_dir, network_guard
):
    """Leg 1 — the argument matrix. Every deliberate construction returns the
    same figure or an honest absence; none admits an operational label."""
    _seed_store(tmp_data_dir)
    open_stats = require(STATS_MODULE, "open_stats", issue="#115")
    no_validation = require(STATS_MODULE, "NoValidationData", issue="#115")
    stats = open_stats(data_dir=tmp_data_dir)

    for description, overrides in _ATTACK_CALLS:
        call = dict(CALL)
        call.update(overrides)
        figure = stats.agreement(**call)
        if isinstance(figure, no_validation):
            # The narrowing constructions must refuse honestly — and the
            # refusal's n is still the measurement of what was there, never a
            # wider population's.
            assert figure.n in (0, T1_N) or figure.reason in (
                "no_data_for_population", "no_data_for_backend"
            ), (
                f"{description}: the absence reports n={figure.n} reason="
                f"{figure.reason!r}"
            )
        else:
            _assert_the_blind_figure(figure, f"attack {description!r}")

    # The keyed figure over the contaminated store, once, with everything it
    # discloses: the 55 inadmissible labels are named beside the figure.
    figure = stats.agreement(**CALL)
    _assert_the_blind_figure(figure, "the keyed call")
    assert figure.excluded_count == 55, (
        f"the keyed figure discloses {figure.excluded_count} exclusions; the "
        "contaminated store holds 40 operational + 15 deterministic labels "
        "beside the 20 blind judged ones (CT-REVIEW-08 step 4)"
    )

    # The absence for the deterministic criterion carries what was measured:
    # nothing admissible, and all 55 inadmissible labels named.
    det_call = dict(CALL)
    det_call["criterion_id"] = DET_CRITERION
    det_figure = stats.agreement(**det_call)
    assert isinstance(det_figure, no_validation), (
        f"agreement over the deterministic criterion returned {det_figure!r}"
    )
    assert det_figure.n == 0 and det_figure.excluded_count == 55, (
        "the deterministic criterion's absence reports what was measured: no "
        "admissible labels, 55 excluded"
    )
    network_guard.assert_no_network()


def test_tc_stats_25_no_raw_row_bypassing_the_producer_is_admitted(
    tmp_data_dir, network_guard
):
    """Leg 2 — the direct write. Every inadmissible class, inserted into the
    `label` table with raw SQL in the shape `upsert_label` ships (bypassing
    `record_label` entirely), disagreeing so admission would move the exact κ.
    The figure is the blind population's own, and the exclusions name the
    forged rows."""
    _seed_store(tmp_data_dir)

    connection = sqlite3.connect(str(Path(tmp_data_dir) / "durable.sqlite"))
    try:
        for label_id, class_fields in _ATTACK_ROWS:
            connection.execute(
                "INSERT INTO label (label_id, run_id, student_ref, criterion_id, "
                "label_type, band, evaluation_mode, saw_system_output, routing, "
                "origin, system_band, teacher_band, actor, cohort_id) "
                "VALUES (?, '', '', 'C-01', ?, '1', ?, ?, 'queued', 'direct', "
                "'1', '4', '', NULL)",
                (label_id, class_fields["label_type"],
                 class_fields["evaluation_mode"],
                 class_fields["saw_system_output"]),
            )
        connection.commit()
    finally:
        connection.close()

    open_stats = require(STATS_MODULE, "open_stats", issue="#115")
    no_validation = require(STATS_MODULE, "NoValidationData", issue="#115")
    stats = open_stats(data_dir=tmp_data_dir)

    figure = stats.agreement(**CALL)
    _assert_the_blind_figure(figure, "after the direct write")
    assert figure.excluded_count == 59, (
        f"the figure discloses {figure.excluded_count} exclusions after the "
        "write; the forged rows are 4 more inadmissible labels (55 + 4) — they "
        "are named, not silently dropped (CT-REVIEW-08 step 4)"
    )

    det_call = dict(CALL)
    det_call["criterion_id"] = DET_CRITERION
    det_figure = stats.agreement(**det_call)
    assert isinstance(det_figure, no_validation), (
        f"agreement over the deterministic criterion returned {det_figure!r}"
    )
    assert det_figure.excluded_count == 59, (
        "the keyed absence carries the same exclusion count — the forged rows "
        "are disclosed on every path, not only the figure's own"
    )
    network_guard.assert_no_network()


def test_adv_09_the_registered_label_reads_carry_no_admission_predicate():
    """Leg 3 — the registry sweep. Every registered statement that touches the
    `label` table reads it wholesale and predicates on nothing but the cohort:
    the admissibility conjunction lives exactly once, in the module's own
    filter (`NFR-STATS-04`). A SQL-side re-spelling would be a second
    definition that can drift from that one — the drift this sweep refuses.
    (The det side asserts the inverse shape, by design: its exclusion IS SQL,
    because the mode column is `aeh.det`'s — the det leg's `_label_read_paths`.)"""
    statements = require(STATS_MODULE, "STATS_STATEMENTS", issue="#115")
    label_statements = {
        name: str(stmt)
        for name, stmt in statements.items()
        if "FROM label" in str(stmt) or "UPDATE label" in str(stmt)
    }

    # Non-vacuity: the sweep must see the canonical reads, or it passes on an
    # empty registry while the real path moved.
    assert {"select_labels", "select_labels_all",
            "select_unclaimed_labels", "claim_labels"} <= set(label_statements), (
        f"the label-touching statements are {sorted(label_statements)!r}; the "
        "canonical cohort read, the wholesale read, the unclaimed read and the "
        "claim are the surfaces this sweep pins"
    )

    for name, sql in label_statements.items():
        for column in ("label_type", "evaluation_mode", "saw_system_output",
                       "system_band", "teacher_band"):
            assert column not in sql, (
                f"registered statement {name!r} predicates on the admissibility "
                f"column {column!r}: a second, SQL-side spelling of the "
                "admissible-label conjunction that can drift from the module's "
                f"one filter (NFR-STATS-04). Statement: {sql!r}"
            )
        # The row filter is the cohort's, or there is none: the read carries
        # every row's pair columns wholesale (`CT-STATS-C18`'s bound
        # parameter, no student-identifying column named).
        if name == "select_labels":
            assert sql.strip() == "SELECT * FROM label WHERE cohort_id = :cohort_id", (
                f"the canonical cohort read is {sql!r}; it reads wholesale and "
                "predicates on the cohort alone"
            )
        if name == "select_labels_all":
            assert sql.strip() == "SELECT * FROM label", (
                f"the wholesale read is {sql!r}; no predicate at all — the "
                "admissibility decision is never in the SQL"
            )
