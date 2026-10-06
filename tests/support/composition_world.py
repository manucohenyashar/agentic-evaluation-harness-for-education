"""The TS-146 world (#625): `F-RUBRIC-METHODS` run, scored from hand-set verdicts, and graded.

`TC-GRADE-27`, `TC-GRADE-C22` and `TC-JUDGE-45` all stand on one shape: the
`F-RUBRIC-METHODS` package (`tests/support/rubric_methods.py`, TS-144's builder — reused, not
re-invented) published into a real store, a real cohort with seeded documents, and a real run
created by `Orchestrator.create_run` and enumerated by `enumerate_units`. From there:

* the **judge cases** read the enumerated `work_unit` rows, or hand-corrupt the ledger;
* the **grade cases** score each (submission, criterion) cell from a **hand-set verdict panel**
  (`StoredVerdict` values — the exact type `aeh.judge.verdicts_for` hands `aggregate` in
  production), aggregate it with the REAL `aeh.agg.aggregate` over a criterion value built by
  the REAL `aeh.pipeline.hooks._criterion_value`, store it with the REAL `aeh.agg.write_score`,
  and grade the run with the REAL `GradingService.compute_all`. No model is called anywhere.

**Why the private `_criterion_value`.** It is how `M-PIPE` builds the criterion value
`aggregate` and `should_escalate` read, and it forwards *every* package column wholesale
(`CT-AGG-09`'s reason). Once Package migration 15 lands, `score_method` and `component_of`
ride that value into aggregation — which is exactly the leak `CT-GRADE-22` forbids ("the method
is never an input to confidence, routing or escalation"). Rebuilding the namespace here would
hide the leak the cases exist to catch, so the production builder is used, disclosed once.

**The one surface assumed of #626** (the design names none — `operator_requirements_design_delta.md`
§3.6, `FR-GRADE-22`'s "per-criterion views shall present composite criteria as one line (sum
awarded / sum max)"). It lives in `composite_line` below and nowhere else, so if #626 lands a
different shape this is the one place to change:

| Name | Assumed shape |
|---|---|
| `GradingService.criterion_lines(run_id, submission_id)` | the per-criterion view of one submission's current grade: a sequence of lines, one per **presented** criterion, each carrying `criterion_id`, `awarded` (float or None) and `max_points` (float); a composite's line also carries `aspects` (its aspect criterion ids). Aspects stay separately readable (their own score rows), so whether they also appear as lines is not asserted. |

Everything else these cases assert is already observable on shipped surfaces: the
`submission_grade` row (`total`, `criteria_missing`, `missing_criteria`, `state`), the
`review_queue` rescan rows, the `criterion_score` rows, and the `work_unit` ledger.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

# CLAUDE.md: every migration-chain contributor is imported before the first store open.
import aeh.agg  # noqa: F401
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

from tests.support.judge_run import byte_span, canonical_document, default_pages, resolved
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_document
from tests.support.rubric_methods import (
    ASPECT_POINTS,
    ASPECTS,
    BANDS,
    COMPOSITE,
    GENERAL,
    MCQ,
    PackageShape,
    build,
    catalog_for,
    rubric_methods,
    with_criterion,
    without_criteria,
)

#: The story whose landing turns every TS-146 case green (`Written ahead: yes`).
ISSUE = "#626"

COHORT = ORCH_COHORT_ID

#: The judged (panel-scored) criteria of `F-RUBRIC-METHODS`: everything but the MCQ line and
#: the composite. A composite is never a score unit (`FR-JUDGE-38`).
JUDGED = (BANDS, GENERAL, *ASPECTS)


# --- the package variants -------------------------------------------------------------------


def general_as_bands(shape: PackageShape | None = None) -> PackageShape:
    """`F-RUBRIC-METHODS` with `C-general` declared `bands` instead (no derivation): the
    `bands` twin `CT-GRADE-22` says a `general` criterion must grade exactly like. Same band
    set, same points, same dependencies — only the method differs."""
    shape = shape or rubric_methods()
    return with_criterion(shape, GENERAL, score_method="bands", derive=False, confirm=False)


def aspects_standalone(shape: PackageShape | None = None) -> PackageShape:
    """`F-RUBRIC-METHODS` with the composite dissolved: its three aspects become standalone
    2-band `bands` criteria on the same question, with the same bands. The control the
    composite cells are compared to (TC-GRADE-27(d))."""
    shape = shape or rubric_methods()
    for aspect in ASPECTS:
        shape = with_criterion(shape, aspect, component_of=None, score_method="bands")
    return without_criteria(shape, COMPOSITE)


# --- the run --------------------------------------------------------------------------------


def seed_rubric_run(store: Any, shape: PackageShape, submissions: Sequence[str], *,
                    panel: int = 3) -> SimpleNamespace:
    """Publish `shape`, seed the cohort and its documents, create the run and enumerate its
    units through the real `enumerate_units`. No unit is leased and nothing is judged."""
    from aeh.orch import Orchestrator

    catalog, version = build(store, shape)
    seed_cohort(store, list(submissions))
    documents: dict[str, str] = {}
    spans: dict[str, list[dict[str, Any]]] = {}
    for submission_id in submissions:
        pages = default_pages(submission_id)
        markdown = canonical_document("\n".join(pages))
        documents[submission_id] = markdown
        seed_document(store, submission_id, markdown)
        spans[submission_id] = [byte_span(markdown, needle) for needle in pages]
    orchestrator = Orchestrator(store)
    run_id = orchestrator.create_run(COHORT, version, resolved(panel))
    enumeration = orchestrator.enumerate_units(run_id)
    return SimpleNamespace(
        enumeration=enumeration,
        store=store, shape=shape, catalog=catalog, version=version,
        package_id=shape.package_id, orchestrator=orchestrator, run_id=run_id,
        cohort=store.cohort(COHORT), submissions=tuple(submissions),
        documents=documents, spans=spans,
    )


def work_units(world: SimpleNamespace) -> list[dict[str, Any]]:
    """Every `work_unit` row of the run, as dicts."""
    return [dict(row) for row in world.cohort.query(
        "SELECT * FROM work_unit WHERE run_id = :r ORDER BY work_id", r=world.run_id)]


# --- hand-set verdicts → real aggregation → real ledger ---------------------------------------


class _CitationView:
    """The one method `_criterion_value` reads off the integrity gate's view: whether the
    criterion requires citation. Every judged `F-RUBRIC-METHODS` line declares an evidence type,
    so it does — the same answer for every method, which is the point."""

    def criterion_requires_citation(self, criterion_id: str) -> bool:
        return True


def criterion_value(world: SimpleNamespace, criterion_id: str) -> Any:
    """The criterion value `aggregate` / `should_escalate` read, built by `M-PIPE`'s own
    builder over the real catalog (every package column forwarded)."""
    from aeh.pipeline.hooks import _criterion_value

    catalog = catalog_for(world.store, world.package_id)
    return _criterion_value(catalog, _CitationView(), world.version, criterion_id)


def favourable_signals() -> SimpleNamespace:
    from tests.support.agg_vocabulary import favourable_signals as favourable

    return favourable()


def adverse_signals() -> SimpleNamespace:
    """One adverse integrity signal (spans unverified) — a cap binds, so routing moves."""
    signals = favourable_signals()
    signals.spans_verified = False
    return signals


def hand_set_panel(criterion: Any, ordinals: Sequence[int], *, cited: bool = True,
                   tag: str = "") -> tuple[Any, ...]:
    """A verdict panel as `aeh.judge.verdicts_for` returns one: `StoredVerdict` values naming
    the criterion's declared bands by ordinal, one per judge."""
    from aeh.judge.results import StoredVerdict

    names = {int(_field(b, "ordinal")): str(_field(b, "band")) for b in criterion.bands}
    return tuple(
        StoredVerdict(
            work_id=f"hand-{tag}-{criterion.criterion_id}-{seat}",
            judge_id=f"judge-{seat}",
            band=names[ordinal],
            band_ordinal=int(ordinal),
            cited_spans=({"start": 0, "end": 4, "text": "hand"},) if cited else (),
            evidence_sufficient=True,
            uncited=not cited,
        )
        for seat, ordinal in enumerate(ordinals)
    )


def _field(row: Any, name: str) -> Any:
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return getattr(row, name)


def score_cell(world: SimpleNamespace, submission_id: str, criterion_id: str,
               ordinals: Sequence[int], *, signals: Any = None, cited: bool = True) -> Any:
    """Aggregate one cell from a hand-set panel and store it through `write_score`."""
    from aeh.agg import aggregate, write_score

    signals = signals if signals is not None else favourable_signals()
    criterion = criterion_value(world, criterion_id)
    panel = hand_set_panel(criterion, ordinals, cited=cited, tag=submission_id)
    score = aggregate(panel, criterion, signals)
    with world.cohort.transaction() as tx:
        write_score(tx, world.run_id, submission_id, score, signals)
    return score


def score_mcq(world: SimpleNamespace, submission_id: str, correct: bool) -> Any:
    """The MCQ line's deterministic row, passed through `aggregate`'s FR-AGG-10 entry the way
    a judged-without-a-panel row arrives — so every line of the package has its score row."""
    from aeh.agg import aggregate, write_score

    criterion = criterion_value(world, MCQ)
    band = "correct" if correct else "incorrect"
    row = SimpleNamespace(criterion_id=MCQ, band=band, points=1.0 if correct else 0.0,
                          routing="auto", state="final")
    signals = favourable_signals()
    score = aggregate((), criterion, signals, deterministic_score=row)
    with world.cohort.transaction() as tx:
        write_score(tx, world.run_id, submission_id, score, signals)
    return score


def score_submissions(world: SimpleNamespace,
                      panels: Mapping[str, Mapping[str, Sequence[int]]],
                      mcq: Mapping[str, bool]) -> None:
    """Score every cell `panels` names (submission → criterion → ordinals), plus the MCQ line."""
    for submission_id, cells in panels.items():
        score_mcq(world, submission_id, mcq[submission_id])
        for criterion_id, ordinals in cells.items():
            score_cell(world, submission_id, criterion_id, ordinals)


def grade(world: SimpleNamespace) -> Any:
    from aeh.grade import open_grade

    service = open_grade(world.store)
    world.service = service
    world.report = service.compute_all(world.run_id)
    return world.report


# --- the readbacks ----------------------------------------------------------------------------

#: Columns that legitimately differ between two otherwise identical runs: identities and
#: wall-clock stamps. Everything else a grade path writes must match byte for byte.
_VOLATILE = ("run_id", "package_version_id", "queue_id")


def _stable(row: Any) -> dict[str, Any]:
    out = dict(row)
    for key in list(out):
        if key in _VOLATILE or key.endswith("_at"):
            out.pop(key)
    return out


def score_rows(world: SimpleNamespace) -> list[str]:
    """Every `criterion_score` row the run's grade path wrote, identity- and clock-stripped,
    canonical JSON, sorted."""
    return sorted(json.dumps(_stable(r), sort_keys=True, default=str) for r in world.cohort.query(
        "SELECT * FROM criterion_score WHERE run_id = :r", r=world.run_id))


def grade_rows(world: SimpleNamespace) -> list[str]:
    """Every `submission_grade` row of the run, identity- and clock-stripped, canonical JSON."""
    return sorted(json.dumps(_stable(r), sort_keys=True, default=str) for r in world.cohort.query(
        "SELECT * FROM submission_grade WHERE run_id = :r", r=world.run_id))


def queue_rows(world: SimpleNamespace) -> list[str]:
    """The run's `review_queue` rows (the rescan routing a missing input earns)."""
    return sorted(json.dumps(_stable(r), sort_keys=True, default=str) for r in world.cohort.query(
        "SELECT * FROM review_queue WHERE run_id = :r", r=world.run_id))


def current_grade(world: SimpleNamespace, submission_id: str) -> dict[str, Any]:
    rows = world.cohort.query(
        "SELECT * FROM submission_grade WHERE run_id = :r AND submission_id = :s "
        "AND is_current = 1", r=world.run_id, s=submission_id)
    assert len(rows) == 1, f"expected one current grade for {submission_id}, got {len(rows)}"
    return dict(rows[0])


def rescan_rows_for(world: SimpleNamespace, criterion_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in world.cohort.query(
        "SELECT * FROM review_queue WHERE run_id = :r AND criterion_id = :c",
        r=world.run_id, c=criterion_id)]


def composite_line(world: SimpleNamespace, submission_id: str,
                   criterion_id: str = COMPOSITE) -> Any:
    """The composite's one presented line (FR-GRADE-22) — the assumed #626 surface, see the
    module docstring. Fails as an assertion naming the missing surface, never an
    AttributeError."""
    service = getattr(world, "service", None)
    lines_of = getattr(service, "criterion_lines", None)
    assert callable(lines_of), (
        "GradingService.criterion_lines(run_id, submission_id) is not there: FR-GRADE-22's "
        f"per-criterion view (one line per composite, sum awarded / sum max) is #626's "
        "(the surface is assumed in tests/support/composition_world.py)")
    lines = [line for line in lines_of(world.run_id, submission_id)
             if str(_field(line, "criterion_id")) == criterion_id]
    assert len(lines) == 1, (
        f"the per-criterion view presents composite {criterion_id} as exactly one line "
        f"(FR-GRADE-22), found {len(lines)}")
    return lines[0]


# --- method-blindness: the same panel through two criteria that differ only in method ---------

#: Band patterns over a 2-band set: unanimous both ways, split both ways, single-judge both ways.
TWO_BAND_PATTERNS: tuple[tuple[int, ...], ...] = ((1, 1, 1), (0, 0, 0), (0, 1, 1), (0, 0, 1),
                                                  (1,), (0,))
#: The same shapes over a 4-band set.
FOUR_BAND_PATTERNS: tuple[tuple[int, ...], ...] = ((3, 3, 3), (2, 2, 2), (1, 2, 3), (0, 0, 3),
                                                   (2,), (0,))


#: Aggregation configs the sweep runs under. Every judged `F-RUBRIC-METHODS` line is holistic,
#: and at the module defaults holistic confidence (at most 1.0 x 0.85) can never reach the 0.90
#: auto threshold — so without the lowered threshold no cell could route `auto`, and a method
#: that forced composite aspects to `queued` would slip past the sweep (#625 review).
AGG_CONFIGS: tuple[tuple[str, Any], ...] = (
    ("default knobs", None),
    ("auto threshold 0.5", SimpleNamespace(auto_threshold_holistic=0.5,
                                           auto_threshold_atomic=0.5)),
)


def escalation_contexts() -> tuple[tuple[str, Any, Any], ...]:
    """(label, history, baseline) pairs `should_escalate` is consulted under: the production
    no-data defaults `M-PIPE` passes, and TC-AGG-26's populated stand-ins."""
    from aeh.pkg import NoValidationData
    from tests.support.agg_vocabulary import criterion_history, expected_distribution

    return (
        ("no-data", NoValidationData(reason="no_blind_labels", n=0), NoValidationData()),
        ("populated", criterion_history(), expected_distribution()),
        ("override-heavy", criterion_history(override_rate=0.4, escalations=3),
         expected_distribution(mean=0.5, std=0.2)),
    )


def method_blind_sweep(world_a: SimpleNamespace, criterion_a: str,
                       world_b: SimpleNamespace, criterion_b: str,
                       patterns: Sequence[Sequence[int]]) -> SimpleNamespace:
    """Every pattern × signal set × aggregation config × citation × escalation context, aggregated and escalated
    through `criterion_a` of `world_a` and `criterion_b` of `world_b` (two criteria with the
    same band set that differ only in their declared method). Returns the mismatches and the
    variety observed — a sweep whose outputs never vary would make "equal" vacuous."""
    from dataclasses import replace
    from itertools import product

    from aeh.agg import aggregate, should_escalate

    a = criterion_value(world_a, criterion_a)
    b = criterion_value(world_b, criterion_b)
    mismatches: list[str] = []
    confidences: set[Any] = set()
    routings: set[str] = set()
    states: set[str] = set()
    escalations: set[bool] = set()
    cases = 0
    for ordinals in patterns:
        for (label, signals), (knobs, config), cited in product(
                (("favourable", favourable_signals()), ("adverse", adverse_signals())),
                AGG_CONFIGS, (True, False)):
            score_a = aggregate(hand_set_panel(a, ordinals, cited=cited), a, signals,
                                config=config)
            score_b = aggregate(hand_set_panel(b, ordinals, cited=cited), b, signals,
                                config=config)
            cases += 1
            where = f"panel {tuple(ordinals)}, {label} signals, {knobs}, cited={cited}"
            if replace(score_b, criterion_id=score_a.criterion_id) != score_a:
                mismatches.append(f"{where}: score {score_a!r} != {score_b!r}")
            confidences.add(score_a.confidence)
            routings.add(score_a.routing)
            states.add(score_a.state)
            for context, history, baseline in escalation_contexts():
                decision_a = should_escalate(score_a, a, history, baseline)
                decision_b = should_escalate(
                    replace(score_b, criterion_id=score_a.criterion_id), b, history,
                    baseline)
                if decision_a != decision_b:
                    mismatches.append(
                        f"{where}, {context}: escalation {decision_a!r} != {decision_b!r}")
                escalations.add(bool(getattr(decision_a, "escalate", False)))
    return SimpleNamespace(mismatches=mismatches, cases=cases, confidences=confidences,
                           routings=routings, states=states, escalations=escalations)


#: The composite's maximum, hand-computed: the sum of its aspects' maxima (FR-PKG-25).
COMPOSITE_MAX = float(sum(ASPECT_POINTS))



__all__ = [
    "ASPECTS", "ASPECT_POINTS", "BANDS", "COHORT", "COMPOSITE", "COMPOSITE_MAX", "GENERAL",
    "FOUR_BAND_PATTERNS", "ISSUE", "JUDGED", "MCQ", "TWO_BAND_PATTERNS", "adverse_signals",
    "aspects_standalone", "composite_line", "escalation_contexts", "method_blind_sweep",
    "criterion_value", "current_grade", "favourable_signals", "general_as_bands", "grade",
    "grade_rows", "hand_set_panel", "queue_rows", "rescan_rows_for",
    "rubric_methods", "score_cell", "score_mcq", "score_rows", "score_submissions",
    "seed_rubric_run", "work_units",
]
