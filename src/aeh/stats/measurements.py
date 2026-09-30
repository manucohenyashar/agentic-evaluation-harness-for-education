"""Measuring each judge's position bias and self-agreement by re-running it."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .schema import STATS_STATEMENTS


# --- the MVVP measurement drivers (#374, FR-STATS-21) -------------------------------------

#: The replication floor `measure_self_agreement` refuses below (`FR-STATS-21`:
#: "replicate each judgment >= 3 times"). Three is the design's number, not a knob: a
#: self-agreement figure over two runs cannot distinguish a judge that is stable from one
#: that happened to answer twice the same way, and `FR-STATS-16`'s replication step reads
#: this rate as evidence of stability. A caller asking for fewer is asking for a figure
#: that does not mean what its name says, so it is refused rather than computed.
SELF_AGREEMENT_MINIMUM_RUNS = 3


class _ExemplarSalt:
    """`HARNESS_JUDGE_EXEMPLAR_SEED` set to one value for the duration of an assembly.

    The salt is read at CALL time inside `judge._ordered_exemplars`, so permuting the
    exemplar order means setting the environment around `assemble` and putting it back —
    there is no argument to pass. Restores the previous value rather than deleting, so a
    caller that had the knob set for its own reasons still has it afterwards.

    `None` means the shipped default order: the knob is REMOVED, not set to "", because
    `_ordered_exemplars` falls back on `or _EXEMPLAR_SEED_DEFAULT` and an empty string
    would take that same branch by accident rather than by intent.
    """

    def __init__(self, value: str | None) -> None:
        self._value = value
        self._previous: str | None = None
        self._was_set = False

    def __enter__(self) -> "_ExemplarSalt":
        from aeh.judge import EXEMPLAR_SEED_ENV

        self._was_set = EXEMPLAR_SEED_ENV in os.environ
        self._previous = os.environ.get(EXEMPLAR_SEED_ENV)
        if self._value is None:
            os.environ.pop(EXEMPLAR_SEED_ENV, None)
        else:
            os.environ[EXEMPLAR_SEED_ENV] = self._value
        return self

    def __exit__(self, *exc: Any) -> None:
        from aeh.judge import EXEMPLAR_SEED_ENV

        if self._was_set:
            os.environ[EXEMPLAR_SEED_ENV] = str(self._previous)
        else:
            os.environ.pop(EXEMPLAR_SEED_ENV, None)


def _score_units_for(store: Any, fixture_submissions: Sequence[str]) -> list[Any]:
    """The score units of `fixture_submissions`, rebuilt as the lease resolved them.

    The drivers re-score judgments that have already been made, so the units are the
    `done` ones — the statement says so — and `Orchestrator.lease`, which claims PENDING
    work, cannot hand them over. They are read back instead, into the shipped `WorkUnit`:
    same fields, same values the claim select filled, `student_name` and `submission_text`
    left `None` exactly as a lease leaves them (the assembler resolves the words;
    `FR-ORCH-04`'s reconciliation).

    That fidelity is the whole point. `assemble` builds the request from these fields, the
    recorded-fixture key IS the request, and a unit rebuilt with one field different
    assembles a request no recording answers — surfacing as a missing-recording refusal
    far from the field that caused it.

    Cohorts are discovered by walking the tier's files, the no-side-index discovery
    `M-JUDGE` and `M-EXTRACT` use. A submission the store does not hold contributes no
    unit rather than raising: the caller names a fixture SET, and the drivers report a
    rate per judge over the judgments that exist — which is why they divide by what this
    returns per judge, never by `len(fixture_submissions)`.

    One (submission, judge) may yield SEVERAL units — one per criterion, and one more per
    run the fixture set was judged in. That is correct and each is its own judgment; the
    per-judge denominator is what keeps the arithmetic honest across all of them.
    """
    from aeh.orch import WorkUnit

    data_dir = getattr(store, "data_dir", None)
    if data_dir is None:
        raise ValueError(
            "the MVVP measurement drivers discover cohorts from the store's ledger files, "
            f"which needs the store's data directory; {type(store).__name__} exposes no "
            "`data_dir`. Pass the store rather than a tier handle."
        )
    wanted = set(fixture_submissions)
    units: list[Any] = []
    for path in sorted(Path(data_dir, "cohorts").glob("*.sqlite")):
        handle = store.cohort(path.stem)
        for row in handle.query(STATS_STATEMENTS["select_score_units"]):
            if row["submission_id"] not in wanted:
                continue
            units.append(WorkUnit(
                work_id=row["work_id"],
                run_id=row["run_id"],
                stage=row["stage"],
                student_ref=row["student_ref"],
                student_name=None,
                submission_id=row["submission_id"],
                criterion_id=row["criterion_id"],
                submission_text=None,
                judge=row["judge_id"],
                attempt=row["attempt"],
            ))
    return units


def _exemplar_order(request: Any) -> tuple:
    """The exemplar ids of an assembled request, in presentation order.

    This is the thing the salt permutes, so comparing two of these is how the drivers
    tell a real permutation from one that changed nothing.
    """
    criterion = getattr(request, "criterion", None)
    return tuple(
        getattr(view, "exemplar_id", None)
        for view in (getattr(criterion, "exemplars", ()) or ())
    )


def _assemble_under(store: Any, provider: Any, ref: Any, unit: Any, salt: str | None) -> Any:
    """Assemble one unit with `HARNESS_JUDGE_EXEMPLAR_SEED` set to `salt`.

    Assembly is inside the salt and dispatch is outside it on purpose: the exemplar order
    is fixed the moment the request exists, and the recorded reply is keyed on that
    request, so holding the environment across the dispatch would change nothing and
    would widen the window in which an unrelated concurrent assembly saw the wrong order.
    """
    from aeh.judge import ScoringWorker

    with _ExemplarSalt(salt):
        return ScoringWorker(store, provider, ref).assemble(unit)


def _band_of(store: Any, provider: Any, ref: Any, request: Any) -> str:
    """Dispatch one assembled request and return the band answered."""
    from aeh.judge import ScoringWorker

    return ScoringWorker(store, provider, ref).dispatch(request, ref).band


def measure_position_bias(
    store: Any,
    provider: Any,
    panel: Sequence[Any],
    fixture_submissions: Sequence[str],
    *,
    seed: Any,
) -> Mapping[str, float]:
    """`FR-STATS-21`: each judge's band-change rate under a permuted exemplar order.

    Re-scores every fixture judgment twice through the real `ScoringWorker.assemble` /
    `dispatch` path — once in the shipped default order, once with
    `HARNESS_JUDGE_EXEMPLAR_SEED` set to `seed` — and reports, per judge, the fraction of
    its judgments whose band MOVED. A judge whose verdict is a property of the work
    answers the same band either way and rates 0; one whose verdict is a property of
    where the exemplars sat rates above it. That is `FR-STATS-15`'s order/position swap,
    measured.

    **The denominator is each judge's own measured judgments — not the fixture-submission
    count, and not the dispatch count.** All three coincide in the simple world (one run,
    one criterion, every submission judged) and diverge everywhere else, silently:

    * one (submission, judge) yields one judgment PER CRITERION, and one more per run the
      fixture set was judged in. Dividing by `len(fixture_submissions)` counted those
      extra judgments in the numerator while leaving the denominator at six — a fixture
      set judged twice reported double the true rate, and `run_mvvp` then REFUSED the
      result for leaving `[0, 1]`, turning a wrong figure into a crash one call later;
    * a submission the store holds no judgment for inflated the denominator, understating
      every rate (`2/7` where the truth is `2/6`);
    * two dispatches make ONE comparison, so dividing by dispatches would halve
      everything.

    **A judge with no measured judgment is absent from the result, never `0.0`.** Zero is
    a measurement — "this judge did not move" — and a judge the fixture set never reached
    has not been measured at all. `run_mvvp` reports an absent judge as
    `measured=False` with its declared reason, which is the true statement; a fabricated
    `0.0` would have been stamped `measured=True`. This is the same rule the empty-fixture
    guard below applies, held at per-judge granularity.

    **A permutation that moved nothing is excluded from both sides of the fraction.**
    `judge._ordered_exemplars` returns early for a criterion with fewer than two
    exemplars, so the salt cannot reorder what is not there: the permuted request is
    byte-identical to the default, the same recorded reply answers both, and the
    comparison can only ever say "no change". Counting that as evidence of
    order-insensitivity would manufacture a confident `0.0` out of a criterion that was
    never permutable. Units whose order did not move are skipped; a judge left with no
    movable judgment is absent, and a call where nothing at all was permutable raises
    rather than returning a mapping of silent zeroes.

    The return is a plain `Mapping[judge build_id, float]`, which is what
    `run_mvvp(measured_position_bias=...)` validates and reports verbatim. No wrapper
    type: a rate that cannot be compared with `==` to the figure a reader hand-computes
    is a rate nobody can check.

    Judges outside `panel` are ignored rather than measured — `run_mvvp` refuses rates for
    judges its declared panel does not name, so emitting one here would produce a mapping
    the consumer is required to reject.
    """
    refs = {ref.build_id: ref for ref in panel}
    submissions = tuple(fixture_submissions)
    if not submissions:
        raise ValueError(
            "measure_position_bias() needs at least one fixture submission: a rate over an "
            "empty fixture set is 0/0, and reporting 0.0 for it would read as 'this judge "
            "is order-insensitive' when nothing was measured at all."
        )
    changed: dict[str, int] = {}
    measured: dict[str, int] = {}
    units = _score_units_for(store, submissions)
    for unit in units:
        ref = refs.get(unit.judge)
        if ref is None:
            continue
        default_request = _assemble_under(store, provider, ref, unit, None)
        permuted_request = _assemble_under(store, provider, ref, unit, str(seed))
        if _exemplar_order(permuted_request) == _exemplar_order(default_request):
            # The salt moved nothing for this judgment — see the docstring. Not a
            # measurement, so it enters neither the numerator nor the denominator.
            continue
        measured[unit.judge] = measured.get(unit.judge, 0) + 1
        default_band = _band_of(store, provider, ref, default_request)
        permuted_band = _band_of(store, provider, ref, permuted_request)
        if permuted_band != default_band:
            changed[unit.judge] = changed.get(unit.judge, 0) + 1
    if units and not measured:
        raise ValueError(
            f"measure_position_bias(seed={seed!r}) found judgments to re-score but the "
            "exemplar salt reordered none of them, so every rate would be a vacuous 0.0 "
            "reading as 'order-insensitive'. A criterion with fewer than two exemplars "
            "cannot be permuted (judge._ordered_exemplars returns early); measure a "
            "fixture set whose criteria declare at least two."
        )
    return {
        build_id: changed.get(build_id, 0) / count
        for build_id, count in measured.items()
    }


def measure_self_agreement(
    store: Any,
    provider: Any,
    panel: Sequence[Any],
    fixture_submissions: Sequence[str],
    *,
    runs: int = SELF_AGREEMENT_MINIMUM_RUNS,
) -> Mapping[str, float]:
    """`FR-STATS-21`: each judge's self-agreement over `runs` replications per judgment.

    Every fixture judgment is dispatched `runs` times in the default exemplar order, and a
    judgment counts as agreeing only when ALL its replications answered the same band. The
    rate is the fraction of the judge's judgments that agreed — 1.0 for a judge that
    repeated itself exactly, lower for one that did not.

    **Replication is per judgment, not per judge.** `runs` dispatches of one submission
    says nothing about the other five; the floor `FR-STATS-21` states is on each judgment,
    so this issues ``runs`` dispatches for every judgment the judge actually made.

    **The denominator is each judge's own measured judgments**, and a judge with none is
    absent from the result rather than carrying `0.0` — for the reasons set out on
    `measure_position_bias`, which apply here with the sign flipped: a fabricated `0.0`
    self-agreement reads as "measured, and never stable", the harshest possible claim
    about a judge that was never asked anything. The two drivers fabricating opposite
    lies from the same empty input is what makes this a rule rather than a preference.

    `runs` below `SELF_AGREEMENT_MINIMUM_RUNS` raises `ValueError` — a real refusal, not an
    assertion, so it survives ``python -O`` and reads as a rejected argument rather than a
    broken invariant.

    Reported beside, never merged with, the backend's own
    ``deterministic_at_temperature_zero`` claim: `run_mvvp`'s step 3 carries both, because
    a measured rate and a vendor's assertion are different kinds of evidence
    (`CT-PROV-04`).
    """
    if not isinstance(runs, int) or isinstance(runs, bool):
        raise ValueError(
            f"measure_self_agreement(runs={runs!r}) needs a whole number of replications."
        )
    if runs < SELF_AGREEMENT_MINIMUM_RUNS:
        raise ValueError(
            f"measure_self_agreement(runs={runs}) is below the replication floor of "
            f"{SELF_AGREEMENT_MINIMUM_RUNS} (FR-STATS-21). Two replications cannot tell a "
            "judge that is stable from one that answered the same way twice by chance, and "
            "a figure that does not mean what its name says is worse than no figure."
        )
    refs = {ref.build_id: ref for ref in panel}
    submissions = tuple(fixture_submissions)
    if not submissions:
        raise ValueError(
            "measure_self_agreement() needs at least one fixture submission: 1.0 over an "
            "empty fixture set would read as perfect stability, measured on nothing."
        )
    agreed: dict[str, int] = {}
    measured: dict[str, int] = {}
    for unit in _score_units_for(store, submissions):
        ref = refs.get(unit.judge)
        if ref is None:
            continue
        request = _assemble_under(store, provider, ref, unit, None)
        measured[unit.judge] = measured.get(unit.judge, 0) + 1
        bands = {_band_of(store, provider, ref, request) for _ in range(runs)}
        if len(bands) == 1:
            agreed[unit.judge] = agreed.get(unit.judge, 0) + 1
    return {
        build_id: agreed.get(build_id, 0) / count
        for build_id, count in measured.items()
    }
