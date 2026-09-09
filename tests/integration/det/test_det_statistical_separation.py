"""The `M-DET` statistical-separation cases against the real store: the adversarial
construction of a statistics query that includes deterministic labels (`TC-DET-13`), the
no-zero-from-failure attack (`ADV-06`), and the sweep of every reachable path into an
agreement figure (`ADV-09`). Test plan §5.11 (`TC-DET-13`) and §6.6 (`ADV-06`, `ADV-09`);
issue #89. This is the `M-DET` half of `RISK-07` — κ inflated by a deterministic result is
validity the system does not have.

**Oracle: prohibition assertion.** The pass criterion is that no reachable path admits
deterministic (or operational) labels into an agreement figure, and the figure's n equals
the blind judged count — a hand-computed number, never the code's own output.

**Isolation: rung 2** — real store, real Tier P package, real cohort ledger, real Tier D
statistics; the run row is `M-ORCH`'s own writer (`seed_det_world`, the `TS-33`
vocabulary). No provider is reachable: `network_guard` closes each case.

**Disclosures** (carrying `TS-33`'s disclosed-bypass discipline, issue #88):
- Label rows are seeded directly in the column shape the `label` table ships — there is
  no `M-REVIEW` labeler writer yet. `det` owns the mode COLUMN, not the row (`CT-DET-06`),
  so a direct write is the only way to stand up both populations; the CHECK constraint
  backstops the vocabulary.
- The κ / α / grader-quality consumers land with `M-STATS` (`TS-42`). The figure surface
  this case pins is what `NFR-DET-03` requires to exist first: the ONE filter definition
  (`DETERMINISTIC_EXCLUSION`), the canonical agreement-figure query it composes into, the
  statement registry every consumer must take, and `det`'s own returned figures. When
  `M-STATS` lands, `TC-STATS-25` attacks its functions from the operational side.
- `ADV-06` traces to `FR-INTEG-03` as well as `FR-DET-03`. The empty-evidence-on-a-
  citation-criterion half of that prohibition belongs to `M-INTEG` (not shipped); this
  case pins the `M-DET` half — the §7.8 kernel's refusal to let a scanning failure become
  a wrong answer — over the three failure shapes the plan names.
"""

from __future__ import annotations

import re

import pytest

from aeh.det import DETERMINISTIC_EXCLUSION, DET_STATEMENTS, DeterministicEvaluator
from aeh.store import STATEMENTS
from tests.support.det_vocabulary import (
    open_det_store,
    seed_det_world,
    seed_selection_answers,
)
from tests.support.sql_scan import scan_module

pytestmark = pytest.mark.integration

ISSUE = "#89"

#: A single-select criterion keyed to B over the default option set A–D.
_CRITERIA = [{"criterion_id": "M1", "question_id": "Q1", "key": ("B",)}]

#: Reads of the label table, and the subset that can feed an agreement figure: a
#: figure is computed over the rows' BAND values, so a label read that does not expose
#: `band` is not a statistics path — `count_promoted_labels` (`FR-STORE-07`'s purge
#: bookkeeping) is the one such statement today, and the sweep pins it to that shape.
_LABEL_READ = re.compile(r"\bFROM\s+label\b|\bJOIN\s+label\b")

#: Non-statistics label reads: purge bookkeeping counts, by name.
_PURGE_COUNT_PREFIX = "count_promoted_"


def _attacker_module() -> str:
    """A source module building the admitting query the plan's attacker builds.

    `TC-DET-13`'s construction: a blind-only query whose mode clause is **computed** —
    here the one filter's predicate rebuilt into its own inverse, so the deterministic
    labels walk straight through. `SEC-15`'s scanner must refuse the shape at the source
    boundary: the statement is assembled by an operator from a non-literal, so the
    construction has no path into a module.
    """
    return (
        "from aeh.det import DETERMINISTIC_EXCLUSION\n"
        "\n"
        "\n"
        "def inflated(store):\n"
        "    mode_clause = DETERMINISTIC_EXCLUSION.replace('<>', '=')\n"
        "    attack = (\"SELECT label_id FROM label WHERE label_type = 'blind' \"\n"
        "              \"AND \" + mode_clause)\n"
        "    return store.durable().query(attack)\n"
    )


def _label_read_paths():
    """The registered label-reading statements, split by what they can feed.

    A figure path is a label read that exposes the rows' band values — the thing an
    agreement, κ, α or grader-quality statistic consumes. A label read that exposes no
    band cannot compute a figure over labels; those are pinned to purge bookkeeping
    (`_PURGE_COUNT_PREFIX`) so a future statistics consumer cannot hide behind an
    unclassified shape.
    """
    figure_paths: dict[str, str] = {}
    non_figures: dict[str, str] = {}
    for name, stmt in STATEMENTS.items():
        sql = str(stmt)
        if _LABEL_READ.search(sql):
            (figure_paths if "band" in sql else non_figures)[name] = sql
    return figure_paths, non_figures


def _assert_no_admitting_figure_path(figure_paths, non_figures):
    """Every figure path carries BOTH halves of the admissibility conjunction; every
    non-figure label read is disclosed purge bookkeeping."""
    assert "select_agreement_labels" in figure_paths, (
        "the canonical agreement statement vanished from the registry — the sweep "
        "below would pass vacuously"
    )
    for name, sql in figure_paths.items():
        assert "label_type = 'blind'" in sql and DETERMINISTIC_EXCLUSION in sql, (
            f"registered statement {name!r} reads label bands without the full "
            "admissibility conjunction — a query path into an agreement figure that "
            "admits deterministic or operational labels (RISK-07)"
        )
    for name in non_figures:
        assert name.startswith(_PURGE_COUNT_PREFIX), (
            f"registered statement {name!r} reads the label table, exposes no band, "
            "and is not purge bookkeeping — classify it here: a statistics consumer "
            "must take a figure path (which carries the conjunction), and a "
            "non-statistics read must be named as one"
        )


def _seed_label_matrix(store, run_id: str) -> None:
    """Both label populations over criterion `M1`, hand-labelled below — the rows a
    naive `M-REVIEW`-style labeler would have produced (direct writes, disclosed in the
    module docstring).

    | label | label_type    | evaluation_mode | counted in the blind judged n? |
    |-------|---------------|-----------------|--------------------------------|
    | L1    | blind         | judged          | yes                            |
    | L2    | blind         | (column default)| yes                            |
    | L3    | blind         | judged          | yes                            |
    | L4    | blind         | deterministic   | NO — the attack target         |
    | L5    | blind         | deterministic   | NO — the attack target         |
    | L6    | operational   | judged          | NO — not blind                 |
    | L7    | operational   | deterministic   | NO — neither half              |
    Blind judged count = **3**; blind rows = 5; all rows = 7.
    """
    durable = store.durable()
    rows = [
        ("L1", "blind", "judged"),
        ("L2", "blind", None),  # the default the column ships with
        ("L3", "blind", "judged"),
        ("L4", "blind", "deterministic"),
        ("L5", "blind", "deterministic"),
        ("L6", "operational", "judged"),
        ("L7", "operational", "deterministic"),
    ]
    with durable.transaction() as tx:
        for label_id, label_type, evaluation_mode in rows:
            if evaluation_mode is None:
                tx.execute(
                    "INSERT INTO label (label_id, run_id, student_ref, criterion_id, "
                    "label_type, band) VALUES (:l, :r, NULL, 'M1', :t, 'correct')",
                    l=label_id,
                    r=run_id,
                    t=label_type,
                )
            else:
                tx.execute(
                    "INSERT INTO label (label_id, run_id, student_ref, criterion_id, "
                    "label_type, band, evaluation_mode) VALUES (:l, :r, NULL, 'M1', "
                    ":t, 'correct', :m)",
                    l=label_id,
                    r=run_id,
                    t=label_type,
                    m=evaluation_mode,
                )


# --- TC-DET-13 ------------------------------------------------------------------------------


def test_tc_det_13_the_constructed_statistics_query_cannot_admit_deterministic_labels(
    tmp_data_dir, tmp_path, network_guard
):
    """`TC-DET-13` (`FR-DET-09`) — a statistics query **deliberately constructed** to
    include deterministic labels: the filter refuses, and there is no query path that
    admits them into an agreement figure (`ADV-09`'s oracle, hand-computed n = 3).

    The attacker's three constructions and what each meets:
    1. the canonical registry statement — carries both halves of the admissibility
       conjunction, admits 3;
    2. a consumer composition built from the ONE constant — same refusal, 3;
    3. the minimal admitting edit — strip the predicate out of the canonical SQL. The
       string executes at the raw ledger, but it is not a statistics path: it carries no
       filter (so it is not in the registry and cannot be registered without failing the
       registry sweep), and `SEC-15`'s scanner refuses the assembly at the source
       boundary. Its n (5) is detectably wrong against the blind judged count (3).
    """
    store = open_det_store(tmp_data_dir)
    try:
        run_id, _version, cohort_id = seed_det_world(
            store, submissions=("S01", "S02", "S03"), criteria=_CRITERIA
        )
        seed_selection_answers(
            store,
            cohort_id,
            [
                {"submission_id": "S01", "selection": "B"},
                {"submission_id": "S02", "selection": "C"},
                {"submission_id": "S03", "content_state": "blank"},
            ],
        )
        # Real deterministic results exist before the labels do: the pass writes
        # criterion_score rows, and the labeler's deterministic-mode rows sit over them.
        DeterministicEvaluator(store).evaluate_cohort(run_id)
        _seed_label_matrix(store, run_id)

        canonical = DET_STATEMENTS["select_agreement_labels"]

        # 1. The registry's own agreement query refuses: only the blind judged rows.
        admitted = [row["label_id"] for row in store.durable().query(canonical)]
        assert admitted == ["L1", "L2", "L3"], (
            f"the agreement query admitted {admitted} — a deterministic or operational "
            "label reached an agreement figure (RISK-07's mechanism)"
        )

        # 2. The sanctioned consumer construction — composed from the imported constant,
        #    spelled differently from the registry statement — refuses identically.
        composed = (
            "SELECT label_id FROM label WHERE " + DETERMINISTIC_EXCLUSION +
            " AND label_type = 'blind' ORDER BY label_id"
        )
        assert [
            row["label_id"] for row in store.durable().query(composed)
        ] == admitted, (
            "a composition built from DETERMINISTIC_EXCLUSION admitted a different "
            "population than the canonical statement — the ONE filter disagrees with "
            "its own composition (NFR-DET-03)"
        )

        # 3. The deliberate inclusion: the canonical SQL with the predicate stripped.
        stripped = str(canonical).replace(DETERMINISTIC_EXCLUSION, "1 = 1")
        assert DETERMINISTIC_EXCLUSION not in stripped
        inflated = [row["label_id"] for row in store.durable().query(stripped)]
        assert inflated == ["L1", "L2", "L3", "L4", "L5"], (
            "the stripped construction did not admit the deterministic labels — the "
            "attack legs below would be vacuous"
        )
        # ...and its figure is detectably wrong: n = 5 against the blind judged count 3.
        assert len(inflated) != len(admitted)

        # The stripped query is not a statistics path:
        # (a) the registry holds no band-reading statement without both halves of the
        #     conjunction — an admitting statement cannot be registered;
        figure_paths, non_figures = _label_read_paths()
        _assert_no_admitting_figure_path(figure_paths, non_figures)
        # (b) the assembly has no path into a source module: SEC-15's scanner refuses it.
        source = _attacker_module()
        path = tmp_path / "attacker_stats_module.py"
        path.write_text(source, encoding="utf-8")
        violations = scan_module("attacker_stats", path, tmp_path)
        assert violations, (
            "the constructed admitting query scanned clean — assembled SQL found a path "
            "into a source module, and the construction is no longer refused at the "
            "boundary (SEC-15)"
        )

        network_guard.assert_no_network()
    finally:
        store.close()


# --- ADV-06 ---------------------------------------------------------------------------------


def test_adv_06_no_scanning_failure_is_scored_a_wrong_answer(tmp_data_dir, network_guard):
    """`ADV-06` (`FR-INTEG-03`, `FR-DET-03`) — the no-zero-from-failure rule. Attacker's
    goal: make a failure look like a wrong answer. Three shapes the plan names, seeded as
    real regions and run through the real cohort pass (hand-computed over key B,
    options A–D):

    - S01: the region is scanned **unreadable** (`ambiguous`)        -> unresolved
    - S02: the tick sits **exactly between two boxes** (two marks)   -> unresolved
    - S03: the answer is written **outside the region** (option `Z`,
           not in the declared set)                                  -> unresolved
    - S04: control — a genuinely **blank** region                    -> incorrect, 0.0

    Pass = each attack routes as an ingestion problem (state `unresolved_selection`,
    routing `triage`, points NULL — never band `incorrect`, never the lowest band's 0.0),
    nothing is written into the grade surface for it (no audit record), and the failure
    is *visible*: the unresolved-count alert fires, labelled a scanning problem. The
    control is the differential: a legitimate zero exists and is scored, so the module
    distinguishes failure from wrong answer in BOTH directions (`CT-DET-03`).
    """
    store = open_det_store(tmp_data_dir)
    try:
        run_id, _version, cohort_id = seed_det_world(
            store, submissions=("S01", "S02", "S03", "S04"), criteria=_CRITERIA
        )
        seed_selection_answers(
            store,
            cohort_id,
            [
                # The unreadable region: ingest saw a mark it could not resolve.
                {"submission_id": "S01", "selection_state": "ambiguous"},
                # The tick between two boxes: two live selection marks on the question.
                {
                    "submission_id": "S02",
                    "regions": [{"selection": "B"}, {"selection": "C"}],
                },
                # The answer written outside the region: a resolved mark on an option
                # that is not in the declared set.
                {"submission_id": "S03", "selection": "Z"},
                # The control: an empty answer — the legitimate zero.
                {"submission_id": "S04", "content_state": "blank"},
            ],
        )
        evaluator = DeterministicEvaluator(store)
        report = evaluator.evaluate_cohort(run_id)

        durable = store.durable()
        cohort = store.cohort(cohort_id)
        rows = {
            row["submission_id"]: row
            for row in cohort.query(
                "SELECT submission_id, band, points, state, routing FROM criterion_score "
                "WHERE criterion_id = 'M1' ORDER BY submission_id"
            )
        }
        for submission_id in ("S01", "S02", "S03"):
            row = rows[submission_id]
            assert row["band"] == "unresolved", (
                f"{submission_id}: a scanning failure landed in band {row['band']!r} — "
                "a failure was scored as an answer (RISK-03, ADV-06)"
            )
            assert row["band"] != "incorrect"
            assert row["state"] == "unresolved_selection"
            assert row["routing"] == "triage", (
                f"{submission_id}: routing {row['routing']!r} — the ingestion problem "
                "did not route to the operator queue"
            )
            assert row["routing"] != "auto"
            assert row["points"] is None, (
                f"{submission_id}: points {row['points']!r} — the lowest band's 0.0 is "
                "reserved for a legitimate zero; a failed read must carry no points at "
                "all (FR-INTEG-03's prohibition, det half)"
            )

        # Each attack carries the reason naming its ingestion problem, and no selection
        # read to score — from the shipped per-case API (idempotent under re-run).
        reasons = {
            submission_id: evaluator.evaluate(run_id, submission_id, "M1").reason
            for submission_id in ("S01", "S02", "S03")
        }
        assert reasons == {
            "S01": "ambiguous_mark",
            "S02": "multiple_marks",
            "S03": "selection_outside_option_set",
        }, f"the failure reasons do not name the ingestion problems: {reasons}"

        # The differential control: the blank IS a zero — scored, auto-routed, counted
        # as blank and never as unresolved.
        control = rows["S04"]
        assert control["band"] == "incorrect" and control["routing"] == "auto"
        assert control["points"] == 0.0
        assert evaluator.evaluate(run_id, "S04", "M1").reason == "blank_legitimate_zero"

        # Hand-computed figures: n = 4, correct 0, incorrect 1 (the blank zero),
        # blank_count 1, unresolved_count 3 — separate figures (`TC-DET-05`'s rule).
        assert (report.correct, report.incorrect) == (0, 1)
        assert (report.blank, report.unresolved) == (1, 3)
        summary = report.summaries[0]
        assert (summary.blank_count, summary.unresolved_count) == (1, 3), (
            "the summary conflated blank with unresolved — the failure/zero distinction "
            "collapsed at the aggregate level"
        )

        # Nothing entered the grade surface for the failures: only the control's zero
        # wrote an audit record.
        assert report.audit_records_written == 1
        failed_audits = durable.query(
            "SELECT COUNT(*) AS n FROM audit_record WHERE submission_id IN "
            "('S01', 'S02', 'S03')"
        )[0]["n"]
        assert failed_audits == 0, (
            f"{failed_audits} audit records exist for the attacked submissions — a "
            "failure was graded, not routed"
        )

        # The failure is visible: the unresolved rate (3/4) trips the alert, labelled a
        # scanning problem — a rescan queue, never an item-difficulty reading.
        assert len(report.alerts) == 1
        alert = report.alerts[0]
        assert alert["kind"] == "scanning_problem"
        assert alert["reads_as"] == "rescan_queue_never_item_difficulty"
        assert alert["criterion_id"] == "M1"
        assert alert["unresolved_count"] == 3

        network_guard.assert_no_network()
    finally:
        store.close()


# --- ADV-09 ---------------------------------------------------------------------------------


def test_adv_09_no_reachable_path_inflates_an_agreement_figure(
    tmp_data_dir, network_guard
):
    """`ADV-09` (`FR-STATS-01`, `FR-DET-09`) — the admissible-label filter, attacked
    across every reachable path. Attacker's goal: inflate κ. Pass = no path admits
    operational or deterministic labels into an agreement figure, and the figure's n
    equals the **blind judged count** — 3 here, hand-computed in `_seed_label_matrix`.

    Three legs, each a path the attack must fail to walk:
    1. the registry — every statement that reads the `label` table carries both halves
       of the conjunction (there is no registered query path that admits);
    2. the module's own figures — `evaluate_cohort` and `item_stats` computed **with the
       full label population present** still match the hand counts derived from the
       SELECTIONS alone: the figures are computed over selections, never over labels,
       and every score row's agreement stays NULL with judge_count 0;
    3. the canonical agreement-figure query — its n is 3, not the 5 blind rows and not
       the 7 total rows, with the operational rows (`L6`, the saw-the-output label) and
       the deterministic rows (`L4`, `L5`) both refused.
    """
    store = open_det_store(tmp_data_dir)
    try:
        run_id, _version, cohort_id = seed_det_world(
            store, submissions=("S01", "S02", "S03"), criteria=_CRITERIA
        )
        seed_selection_answers(
            store,
            cohort_id,
            [
                {"submission_id": "S01", "selection": "B"},   # correct
                {"submission_id": "S02", "selection": "C"},   # wrong answer
                {"submission_id": "S03", "content_state": "blank"},  # legitimate zero
            ],
        )
        # The label population exists BEFORE the figures are computed: if any figure
        # read labels, the hand counts below would move.
        _seed_label_matrix(store, run_id)

        evaluator = DeterministicEvaluator(store)
        report = evaluator.evaluate_cohort(run_id)

        # Leg 1: the registry sweep — no admitting query path is registered.
        figure_paths, non_figures = _label_read_paths()
        assert figure_paths, (
            "no band-reading label statement is registered — the sweep passed "
            "vacuously and the agreement path may have moved"
        )
        _assert_no_admitting_figure_path(figure_paths, non_figures)

        # Leg 2: the module's figures, computed under the full label population, match
        # the hand counts from the selections alone.
        assert (report.correct, report.incorrect, report.blank, report.unresolved) == (
            1, 2, 1, 0
        ), (
            "the cohort figures moved with the label population — a figure is being "
            "computed over labels"
        )
        score_rows = store.cohort(cohort_id).query(
            "SELECT judge_count, agreement FROM criterion_score WHERE criterion_id = 'M1'"
        )
        assert score_rows and all(
            row["judge_count"] == 0 and row["agreement"] is None for row in score_rows
        ), (
            "a deterministic score row carries a judged figure — agreement over a "
            "population that includes deterministic results (RISK-07)"
        )
        item_stats = evaluator.item_stats(cohort_id)
        entry = {e.criterion_id: e for e in item_stats.items}["M1"]
        assert entry.n == 3, (
            f"mcq_item_summary n = {entry.n} — the item figures were computed over "
            f"the 7 label rows (or the 5 blind ones) instead of the 3 selections"
        )
        assert (entry.blank_count, entry.unresolved_count) == (1, 0)
        chosen = {o.option: o.chosen for o in entry.options}
        assert chosen == {"A": 0, "B": 1, "C": 1, "D": 0}, (
            f"per-option chosen counts {chosen} moved with the label population — the "
            "item statistics are computed over labels, not selections"
        )

        # Leg 3: the canonical figure's n equals the blind judged count — 3, against
        # 5 blind rows and 7 total.
        admitted = [
            row["label_id"] for row in store.durable().query(
                DET_STATEMENTS["select_agreement_labels"]
            )
        ]
        assert len(admitted) == 3, (
            f"the agreement figure's n is {len(admitted)}, not the blind judged count 3 "
            "— operational or deterministic labels entered the population (ADV-09)"
        )
        assert admitted == ["L1", "L2", "L3"]

        network_guard.assert_no_network()
    finally:
        store.close()
