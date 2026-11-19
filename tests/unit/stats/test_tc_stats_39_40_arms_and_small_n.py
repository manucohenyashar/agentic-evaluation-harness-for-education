"""`TC-STATS-39` and `TC-STATS-40` (issue #897, Validity T4) — the routing arms and the small-n
reasons.

Test plan (statistical validity, r2) §3.8. Traces to FR-STATS-30, FR-STATS-31, CT-STATS-27
(pair M-STATS → CT-REVIEW-26). Both implementations are merged (#874, PR #926), so these cases
run unmarked.

**TC-STATS-39 is a pair case, so the seed goes through the label table.** CT-REVIEW-26 is the
shape M-REVIEW writes: `routing` at draw time (FR-REVIEW-29) and `origin` from the cell's work
units (FR-REVIEW-25). M-STATS has to read that shape back. So the validity seed is written as
rows into a real durable store's `label` table, and `open_stats(data_dir, cohort_id=...)` reads
them through its declared statement. That is rung 1 for the statistic and rung 2 for the read.
An in-memory fixture would pin the arm mapping, but not that the stored columns reach it.

**The seed.** This is the plan's §2.4 validity seed, cut to what the arms read. Two judged
criteria: an atomic two-band line (`C-AT`) and a holistic four-band line (`C-HO`). There is
also a deterministic line, which is never evidence (R53). Routings are spread across `queued`,
`reviewed`, `provisional`, `auto` and `triage`, and origins across `base`, `escalation` and
`random_arm`. Every count below is worked by hand:

| routing | labels | errors (system band != teacher band) | origin = random_arm |
|---|---|---|---|
| queued | 4 | 2 | 1 (an error) |
| reviewed | 2 | 1 | - |
| provisional | 2 | 1 | - |
| auto | 8 | 0 | 1 (clean) |
| triage | 4 | 4 | 1 (an error) |
| deterministic (any routing) | 2 | 2 | 1 (inadmissible) |

- Escalated arm = {queued, reviewed, provisional}: n = 8, errors = 4, rate = 0.5.
- Auto arm = {auto}: n = 8, errors = 0, rate = 0.0.
- The gap is 0.5, which is at least the 0.05 tolerance, so the verdict is `discriminating`.
- `triage` joins neither arm. If it leaked into the escalated arm, that arm would read 8/12. If
  it leaked into the auto arm, that arm would read 4/12.
- Random-arm estimate: the admissible labels with `origin = 'random_arm'`, whatever their
  routing. That is n = 3, errors = 2. The deterministic random-arm label is inadmissible and
  stays out.

**The mutation (CT-STATS-27).** Restore `ROUTING_POLICY_ARM_SOURCES` to the old
`reviewed`/`auto` mapping, patched where `routing_policy_validity` reads it
(`aeh.stats.comparisons`). The arm sizes no longer match. On the draw-time population, where a
blind label never carries `reviewed` because it is written before any review, the verdict
collapses to `no_data` (SV-17). Both turn the cases red.
"""

from __future__ import annotations

import sqlite3

import pytest

from tests.support import broken_stats_fixtures as broken

pytestmark = pytest.mark.contract

COHORT = "coh-validity-seed"
BACKEND = "edge-local"


# --- the validity seed, as label rows --------------------------------------------------------


def _row(label_id: str, *, routing: str, error: bool, origin: str = "base",
         criterion_id: str = "C-AT", evaluation_mode: str = "judged") -> dict:
    """One stored blind label. The teacher's band is `correct`. The system's band equals it on a
    clean label and differs on an error, so `error` is the label's contribution to its arm's
    error count by construction."""
    return {
        "label_id": label_id,
        "run_id": "run-validity-seed",
        "student_ref": f"P-{label_id}",
        "criterion_id": criterion_id,
        "label_type": "blind",
        "band": "correct",
        "teacher_band": "correct",
        "system_band": "incorrect" if error else "correct",
        "evaluation_mode": evaluation_mode,
        "saw_system_output": 0,
        "routing": routing,
        "origin": origin,
        "cohort_id": COHORT,
        "backend_profile": BACKEND,
    }


def _validity_seed() -> list[dict]:
    rows: list[dict] = []
    # queued: 4 labels, 2 errors, one error from the random arm.
    rows += [_row("q1", routing="queued", error=True, origin="random_arm"),
             _row("q2", routing="queued", error=True, origin="escalation", criterion_id="C-HO"),
             _row("q3", routing="queued", error=False),
             _row("q4", routing="queued", error=False, origin="escalation", criterion_id="C-HO")]
    # reviewed: 2 labels, 1 error.
    rows += [_row("r1", routing="reviewed", error=True, origin="escalation"),
             _row("r2", routing="reviewed", error=False, criterion_id="C-HO")]
    # provisional: 2 labels, 1 error.
    rows += [_row("p1", routing="provisional", error=True, criterion_id="C-HO"),
             _row("p2", routing="provisional", error=False)]
    # auto: 8 labels, no error, one from the random arm.
    rows += [_row(f"a{i}", routing="auto", error=False,
                  origin="random_arm" if i == 1 else "base",
                  criterion_id="C-HO" if i % 2 else "C-AT") for i in range(1, 9)]
    # triage: 4 labels, every one an error, one from the random arm. Neither arm's.
    rows += [_row(f"t{i}", routing="triage", error=True,
                  origin="random_arm" if i == 1 else "base") for i in range(1, 5)]
    # The deterministic line: never evidence, whatever its routing or origin (R53).
    rows += [_row("d1", routing="auto", error=True, origin="random_arm",
                  criterion_id="C-DET", evaluation_mode="deterministic"),
             _row("d2", routing="queued", error=True, criterion_id="C-DET",
                  evaluation_mode="deterministic")]
    return rows


def _draw_time_seed() -> list[dict]:
    """The population a live administration actually holds. A blind label records the cell's
    routing at draw time, before any review, so no label carries `reviewed`. The escalated
    cells are `queued` and `provisional`: 4 labels, 2 errors. The auto cells are 4 labels with
    no error."""
    return [
        _row("dq1", routing="queued", error=True),
        _row("dq2", routing="queued", error=False),
        _row("dp1", routing="provisional", error=True),
        _row("dp2", routing="provisional", error=False),
        *(_row(f"da{i}", routing="auto", error=False) for i in range(1, 5)),
    ]


def _seed_store(data_dir, rows: list[dict]) -> None:
    """Write the rows into a migrated durable store's `label` table."""
    from aeh.store import open_store

    import aeh.agg  # noqa: F401  the full migration chain before the first open (CLAUDE.md)
    import aeh.det  # noqa: F401
    import aeh.extract  # noqa: F401
    import aeh.grade  # noqa: F401
    import aeh.ingest  # noqa: F401
    import aeh.integ  # noqa: F401
    import aeh.judge  # noqa: F401
    import aeh.orch  # noqa: F401
    import aeh.pkg  # noqa: F401
    import aeh.review  # noqa: F401
    import aeh.synth  # noqa: F401

    store = open_store(data_dir)
    try:
        store.durable()
    finally:
        store.close()
    columns = list(rows[0])
    with sqlite3.connect(data_dir / "durable.sqlite") as connection:
        connection.executemany(
            f"INSERT INTO label ({', '.join(columns)}) "
            f"VALUES ({', '.join(':' + c for c in columns)})",
            rows,
        )


def _report(data_dir, rows: list[dict]):
    from aeh.stats import open_stats

    _seed_store(data_dir, rows)
    return open_stats(data_dir, cohort_id=COHORT).routing_policy_validity(cohort_id=COHORT)


_OLD_ARM_SOURCES = {
    "escalated_and_reviewed": ("escalated_and_reviewed", "reviewed"),
    "auto_accepted": ("auto_accepted", "auto"),
}


# --- TC-STATS-39 -----------------------------------------------------------------------------


def test_tc_stats_39_arms_are_formed_from_the_routings_labels_carry(tmp_data_dir):
    """TC-STATS-39 on the validity seed: escalated = {queued, reviewed, provisional} (n = 8,
    rate 0.5); auto = {auto} (n = 8, rate 0.0); triage in neither; the verdict is
    `discriminating`; the random-arm estimate counts only `origin = 'random_arm'` (n = 3, 2
    errors). Every figure is worked in the module docstring."""
    from aeh.stats import (
        ROUTING_POLICY_ARMS,
        ROUTING_POLICY_DISCRIMINATING_VERDICT,
        ROUTING_POLICY_NO_DATA_VERDICT,
    )

    report = _report(tmp_data_dir, _validity_seed())
    escalated, auto = (report.label_population[arm] for arm in ROUTING_POLICY_ARMS)

    # Every admissible label was read back. 20 are blind and judged; the 2 deterministic ones
    # are not evidence. A filter that dropped base, escalation or random_arm labels would
    # shrink this.
    assert report.n == 20, (
        f"M-STATS read {report.n} admissible labels from the stored seed, not 20. The pair "
        "with CT-REVIEW-26 is that every origin M-REVIEW writes is readable evidence")

    assert (escalated.n, escalated.paired, escalated.errors) == (8, 8, 4), (
        f"the escalated arm holds n={escalated.n}, errors={escalated.errors}, not the "
        "8 labels / 4 errors routed queued, reviewed or provisional (FR-STATS-30). 2 labels "
        "means the arm reads `reviewed` alone, the old mapping (SV-17); 12 means triage joined it")
    assert escalated.error_rate == pytest.approx(0.5)
    assert (auto.n, auto.paired, auto.errors) == (8, 8, 0), (
        f"the auto arm holds n={auto.n}, errors={auto.errors}, not the 8 clean `auto` labels. "
        "12 means triage joined it, and errors > 0 means the deterministic line did")
    assert auto.error_rate == pytest.approx(0.0)

    assert report.verdict != ROUTING_POLICY_NO_DATA_VERDICT, (
        "both arms are admissible and paired, so the verdict must be discriminating or failing, "
        "never no_data (FR-STATS-30's measurable)")
    assert report.verdict == ROUTING_POLICY_DISCRIMINATING_VERDICT, (
        f"a 0.5-versus-0.0 gap read as {report.verdict!r}")

    random_arm = report.random_arm
    assert random_arm is not None, "the report carries no random-arm estimate (HLD §7.1)"
    assert (random_arm.n, random_arm.paired, random_arm.errors) == (3, 3, 2), (
        f"the random-arm estimate holds n={random_arm.n}, errors={random_arm.errors}. It counts "
        "the admissible labels with origin = 'random_arm' and only those (q1, a1, t1), whatever "
        "their routing. The deterministic random-arm label is not evidence")
    assert random_arm.error_rate == pytest.approx(2 / 3)


def test_tc_stats_39_a_draw_time_population_is_never_no_data(tmp_data_dir):
    """TC-STATS-39, the SV-17 shape: live blind labels carry draw-time routings, so no label
    is `reviewed`. With both arms admissible the verdict is a verdict. The escalated arm is
    2/4 = 0.5 and the auto arm 0/4 = 0.0, so `discriminating`. The old mapping read this
    population as an empty escalated arm, which is `no_data` forever."""
    from aeh.stats import (
        ROUTING_POLICY_ARMS,
        ROUTING_POLICY_DISCRIMINATING_VERDICT,
        ROUTING_POLICY_FAILING_VERDICT,
    )

    report = _report(tmp_data_dir, _draw_time_seed())
    escalated, auto = (report.label_population[arm] for arm in ROUTING_POLICY_ARMS)
    assert report.verdict in (ROUTING_POLICY_DISCRIMINATING_VERDICT,
                              ROUTING_POLICY_FAILING_VERDICT), (
        f"a draw-time population with both arms admissible read {report.verdict!r}. "
        "`queued` and `provisional` are the escalated arm (FR-STATS-30); reading `reviewed` "
        "alone leaves that arm empty by construction (SV-17)")
    assert (escalated.n, escalated.errors, auto.n, auto.errors) == (4, 2, 4, 0)
    assert report.verdict == ROUTING_POLICY_DISCRIMINATING_VERDICT


def test_tc_stats_39_mutation_the_old_arm_sources_are_caught(tmp_data_dir, monkeypatch):
    """CT-STATS-27's mutation, run in-suite. The old `reviewed`/`auto` sources are patched where
    `routing_policy_validity` reads them, and the draw-time population then reads `no_data`.
    That is the red the case above exists to give. If this ever passes vacuously, because the
    patch no longer reaches the function, the case above has lost its teeth."""
    import aeh.stats.comparisons as comparisons
    from aeh.stats import ROUTING_POLICY_NO_DATA_VERDICT

    monkeypatch.setattr(comparisons, "ROUTING_POLICY_ARM_SOURCES", _OLD_ARM_SOURCES)
    report = _report(tmp_data_dir, _draw_time_seed())
    assert report.verdict == ROUTING_POLICY_NO_DATA_VERDICT, (
        "under the old arm sources the draw-time population should read no_data (SV-17). "
        f"It read {report.verdict!r}, so the mutation no longer reaches the arm mapping")


# --- TC-STATS-40 -----------------------------------------------------------------------------


def _agreement(labels, **scope):
    from aeh.stats import build_stats

    stats = build_stats(labels=labels, population_scopes=["pop-40"], backend_profiles=[BACKEND])
    return stats.agreement(criterion_id="C-01", **scope)


def test_tc_stats_40_n0_is_no_blind_labels():
    """TC-STATS-40, n = 0 gives `no_blind_labels` with n = 0. The reason is reserved for an
    empty population (FR-STATS-31)."""
    from aeh.stats import NoValidationData

    figure = _agreement([])
    assert isinstance(figure, NoValidationData)
    assert (figure.reason, figure.n) == ("no_blind_labels", 0)


def test_tc_stats_40_n1_is_too_few_labels_with_its_n():
    """TC-STATS-40, n = 1 gives `too_few_labels` with n = 1. One label was drawn, so "no blind
    labels" would tell the reader nothing was (SV-15)."""
    from aeh.stats import NoValidationData

    figure = _agreement([broken.Label(label_id="one", band=2, teacher_band=2,
                                      backend_profile=BACKEND)])
    assert isinstance(figure, NoValidationData), f"one label produced a figure: {figure!r}"
    assert figure.reason == "too_few_labels", (
        f"n = 1 reported {figure.reason!r}. FR-STATS-31 reserves no_blind_labels for n = 0")
    assert figure.n == 1


def test_tc_stats_40_n2_is_a_figure_as_today():
    """TC-STATS-40, n = 2 gives a figure, as before FR-STATS-31. Worked by hand: the pairs
    (1, 1) and (2, 2) give p_o = 1 and p_e = (1*1 + 1*1) / 4 = 0.5, so kappa = (1 - 0.5) /
    (1 - 0.5) = 1.0."""
    from aeh.stats import AgreementFigure

    figure = _agreement([
        broken.Label(label_id="two-a", band=1, teacher_band=1, backend_profile=BACKEND),
        broken.Label(label_id="two-b", band=2, teacher_band=2, backend_profile=BACKEND),
    ])
    assert isinstance(figure, AgreementFigure), (
        f"two paired labels produced an absence ({getattr(figure, 'reason', figure)!r}). The "
        "small-n reason is for n < 2 only")
    assert figure.n == 2
    assert figure.kappa == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize("n, too_few", [(29, True), (30, False)], ids=["n29", "n30"])
def test_tc_stats_40_the_headline_threshold_is_stats_min_n_for_headline(n, too_few):
    """TC-STATS-40, n = 29 is `too_few` for the headline and n = 30 is not
    (`STATS_MIN_N_FOR_HEADLINE` = 30).

    Both are real figures, not absences: `too_few` qualifies a headline and is not a reason
    to withhold the figure. The headline today is `render_agreement_block` (FR-CONSOLE-38),
    which reads M-STATS's constant at call time. So the M-STATS figure at each n is rendered,
    and the qualifier must appear at 29 and only there. TC-CONSOLE-48 pins the renderer over a
    hand-built figure; this case pins the pair, with the figure M-STATS actually computes. The
    `too_few` field on the validity read and the package record (FR-CONSOLE-80, FR-STATS-35,
    #881) is TC-CONSOLE-110's and TC-STATS-44's."""
    from aeh.console import TOO_FEW_QUALIFIER, render_agreement_block
    from aeh.stats import STATS_MIN_N_FOR_HEADLINE, AgreementFigure

    assert STATS_MIN_N_FOR_HEADLINE == 30
    labels = [
        broken.Label(label_id=f"h{i}", band=1 + (i % 4),
                     teacher_band=1 + ((i + 1) % 4) if i % 5 == 0 else 1 + (i % 4),
                     backend_profile=BACKEND)
        for i in range(n)
    ]
    figure = _agreement(labels, scope="pop-40", backend_profile=BACKEND)
    assert isinstance(figure, AgreementFigure), (
        f"n = {n} produced an absence ({getattr(figure, 'reason', figure)!r})")
    assert figure.n == n and figure.kappa is not None
    rendered = render_agreement_block(figure=figure)
    assert f"n = {n}" in rendered, rendered
    assert (TOO_FEW_QUALIFIER in rendered) is too_few, (
        f"n = {n} against STATS_MIN_N_FOR_HEADLINE = 30: the headline "
        f"{'lacks' if too_few else 'carries'} the too-few qualifier: {rendered!r}")
