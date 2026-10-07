"""The live OpenRouter acceptance (`FR-CONFORM-17/18`; design delta §3.3, TS-142 #617/#618).

One run of the full pipeline on an OpenRouter profile — real ingest vision model, real judge
panel, real synthesis model, real Jev decision engine through the TypeSafe SDK path — that
accounts every model call per leg and refuses to report success when a leg did not really run.

The entry point is `run_live_acceptance(run_config, *, cohort, data_dir)`; it returns a
`LiveAcceptanceReport`. The acceptance is *driven* by the nightly's `live`-marked cases
(TC-CONFORM-17/18/C17 and the re-specified TC-CONFORM-04 arm); nothing in the fast tier
reaches this module, because the whole point of the tier is that the model boundary is real.

Three invariants shape the code:

- **A green run with no real calls is a failure, not a pass** (`CT-CONFORM-17`). Every leg's
  figures must be positive; a leg with zero calls fails the report.
- **No recorded fixture substitutes** (`FR-CONFORM-17`). A bound `HARNESS_FIXTURE_DIR` is a
  refusal at run start, before anything resolves or dispatches.
- **The extremes are invalid, not findings** (`FR-CONFORM-18`, RISK-116): a gate that never
  accepted (silent LLM-only grading) or never fell back (accepts everything) makes the run
  invalid, and the invalidity names the extreme and the gate values that produced it.

Per-leg accounting rides a counting wrapper around the providers (the attribution is the
`ModelRef.role` of each call — the pipeline's own role inventory), and the figures land in
`run_metrics` through `Orchestrator.record_run_metrics`, keeping M-ORCH the table's sole
writer (`CT-STORE-03`).
"""

from __future__ import annotations

import json
import os
import statistics
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from .errors import LiveAcceptanceRefused
from .reports import LiveAcceptanceReport

__all__ = ["run_live_acceptance"]

#: The repo root, so the acceptance finds the committed sample materials without a cwd.
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: The committed acceptance corpus: one PS9 forces package, one roster, one test paper and six
#: answer sheets (`docs/live-tests/sample-materials/`). Overridable for a test day that ships
#: its own set (seam 3); the layout underneath is the documents'.
MATERIALS_ROOT_ENV = "HARNESS_LIVE_ACCEPTANCE_MATERIALS"

#: The random-arm sample widens panels past the panel with no spare live seat — the one hazard
#: the drive silences, by holding the knob at 0 for the drive's own duration (seam 3: an env
#: knob held with restore, the way the suite's refusal-world knobs are).
RANDOM_ARM_RATE_ENV = "HARNESS_ORCH_RANDOM_ARM_RATE"


# --- the leg inventory (CT-CONFORM-17) ----------------------------------------------------------

LEG_VISION = "vision"
LEG_JUDGE = "judge"
LEG_SYNTHESIS = "synthesis"
LEG_DECISION = "decision"
LIVE_LEGS: tuple[str, ...] = (LEG_VISION, LEG_JUDGE, LEG_SYNTHESIS, LEG_DECISION)

LIVE_CALLS = "live_calls"
LIVE_TOKENS_IN = "live_tokens_in"
LIVE_TOKENS_OUT = "live_tokens_out"
LIVE_COST = "live_cost"
LIVE_LEG_KEYS: tuple[str, ...] = (LIVE_CALLS, LIVE_TOKENS_IN, LIVE_TOKENS_OUT, LIVE_COST)
LEG_MODEL_REFS = "model_refs"

#: The completion roles each leg owns. The pipeline's own role inventory: the ingest reads pages
#: through the transcriber ref and features through the derived extractor ref (both the vision
#: leg); the panel and the off-panel check are the judge leg; synthesis is its own. A role not
#: named here is a pipeline change this module did not see — the tally refuses it rather than
#: mis-billing the call into a leg that did not make it (a mis-attributed call is exactly the
#: zero-call leg the report exists to catch).
_ROLE_LEGS: Mapping[str, str] = {
    "transcriber": LEG_VISION,
    "extractor": LEG_VISION,
    "judge": LEG_JUDGE,
    "off_panel": LEG_JUDGE,
    "synthesizer": LEG_SYNTHESIS,
}


class _LegTally:
    """One leg's accounting: calls, tokens and cost, with the refs that served (Q-O1)."""

    def __init__(self) -> None:
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost = Decimal("0")
        self.refs: set[str] = set()

    def add(self, tokens_in: int, tokens_out: int, cost: Any, build: Any) -> None:
        self.calls += 1
        self.tokens_in += int(tokens_in or 0)
        self.tokens_out += int(tokens_out or 0)
        if cost is not None:
            self.cost += Decimal(str(cost))
        if build:
            self.refs.add(str(build))

    def figures(self) -> dict[str, Any]:
        return {
            LIVE_CALLS: self.calls,
            LIVE_TOKENS_IN: self.tokens_in,
            LIVE_TOKENS_OUT: self.tokens_out,
            LIVE_COST: self.cost,
            LEG_MODEL_REFS: tuple(sorted(self.refs)),
        }


# --- the counting providers (FR-CONFORM-17's per-leg accounting) ---------------------------------


class _CountingCompletionProvider:
    """A completion provider that tallies every call into the leg its `ModelRef.role` names.

    Everything but `complete` is the wrapped provider's own — the retention gate, the cost
    ceiling's pricing and the build watch must see the real transport, not a wrapper's idea of
    it (`_UnitPricedProvider`'s pattern).
    """

    def __init__(self, inner: Any, tallies: Mapping[str, _LegTally]) -> None:
        self._inner = inner
        self._tallies = tallies

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        leg = _ROLE_LEGS.get(str(getattr(model_ref, "role", "") or ""))
        if leg is None:
            raise LiveAcceptanceRefused(
                f"a completion carried role {model_ref.role!r}, which maps to no live leg "
                f"({', '.join(LIVE_LEGS)}); per-leg accounting would silently lose the call."
            )
        completion = self._inner.complete(prompt, model_ref, params)
        self._tallies[leg].add(
            completion.tokens_in, completion.tokens_out, completion.cost,
            completion.resolved_build)
        return completion

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _CountingDecisionProvider:
    """A decision provider that tallies every `decide` into the decision leg.

    The decision leg's calls do not pass the completion provider at all — `decide` is its own
    interface (FR-PROV-16) — so this is the decision leg's only accounting point.
    """

    def __init__(self, inner: Any, tallies: Mapping[str, _LegTally]) -> None:
        self._inner = inner
        self._tallies = tallies

    def decide(self, request: Any, model_ref: Any) -> Any:
        decision = self._inner.decide(request, model_ref)
        self._tallies[LEG_DECISION].add(
            decision.tokens_in, decision.tokens_out, decision.cost,
            decision.resolved_build)
        return decision

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


# --- the run-start refusal gates (FR-CONFORM-17's preconditions) ----------------------------------

_OPENROUTER_PROFILES = frozenset({"dev-ci", "cloud-hosted"})
_KEY_ENV = "OPENROUTER_API_KEY"
_FIXTURE_DIR_ENV = "HARNESS_FIXTURE_DIR"


def _import_full_chain() -> None:
    """CLAUDE.md: before the first store open in a process, import all eleven contributors."""
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


def _refusal_gates(run_config: Any) -> None:
    """Refuse before anything resolves a socket, naming the precondition that failed.

    An acceptance that cannot run is a refusal, never a green report with empty legs. The
    checks are the four the live tier stands on: the credential is present, no recorded
    fixture is bound (the binding is what would replay the legs), the profile dispatches to
    OpenRouter, and the decision engine actually resolved — a resolved-off engine is the
    configuration TC-CONFORM-17's re-specification retires.
    """
    if not os.environ.get(_KEY_ENV, "").strip():
        raise LiveAcceptanceRefused(
            f"{_KEY_ENV} is unset: the live acceptance makes real calls on every leg "
            f"(FR-CONFORM-17), so it refuses rather than run an acceptance with no transport."
        )
    if os.environ.get(_FIXTURE_DIR_ENV, "").strip():
        raise LiveAcceptanceRefused(
            f"{_FIXTURE_DIR_ENV} is set, so the run would replay recordings. The live "
            f"acceptance binds no recorded fixture on any leg (FR-CONFORM-17)."
        )
    profile = str(getattr(run_config, "backend_profile", "") or "")
    if profile not in _OPENROUTER_PROFILES:
        raise LiveAcceptanceRefused(
            f"the live acceptance runs on an OpenRouter profile ({sorted(_OPENROUTER_PROFILES)}); "
            f"the resolved profile is {profile!r}."
        )
    if getattr(run_config, "decision_engine", None) is None:
        raise LiveAcceptanceRefused(
            f"profile {profile!r} resolved the decision engine off. The acceptance must "
            f"exercise the Jev leg (FR-CONFORM-17): FR-CONF-29's default on the OpenRouter "
            f"profiles is jev, and a pinned off is the configuration the acceptance exists to "
            f"retire (design delta §3.3)."
        )


def _completion_provider_for(run_config: Any) -> Any:
    """The completion transport the profile names — the one seam an offline driver patches."""
    from aeh.pipeline.runtime import _provider_for

    return _provider_for(run_config)


def _decision_provider_for(run_config: Any, provider: Any) -> Any:
    from aeh.pipeline.decision_engine import _decision_provider_for_run

    return _decision_provider_for_run(run_config, provider, None)


def _counting_providers(run_config: Any) -> tuple[Any, Any, dict[str, _LegTally]]:
    """The live transports wrapped in the tallies, in one place so an offline driver can stub it.

    The completion provider is the profile's own (`_provider_for`, which enforces zero
    retention on OpenRouter and prices a work unit for the ceiling); the decision provider is
    the factory's for the frozen engine (`FR-PROV-26`'s only construction path) — the TypeSafe
    SDK path for `openrouter-jev`.
    """
    tallies = {leg: _LegTally() for leg in LIVE_LEGS}
    provider = _completion_provider_for(run_config)
    decision = _decision_provider_for(run_config, provider)
    return (
        _CountingCompletionProvider(provider, tallies),
        _CountingDecisionProvider(decision, tallies),
        tallies,
    )


# --- the acceptance corpus -----------------------------------------------------------------------


def _materials_paths() -> tuple[Path, Path, Path, Path]:
    """The committed acceptance corpus: package spec, roster, test paper, answer sheets.

    The layout is the live-test documents' (`docs/live-tests/`); the root is a knob so a test
    day ships its own corpus without touching this module. Refused with the corpus missing —
    a missing file is a refusal, never an empty run.
    """
    root = Path(os.environ.get(MATERIALS_ROOT_ENV, "") or (_REPO_ROOT / "docs" / "live-tests"))
    if not root.is_absolute():
        root = _REPO_ROOT / root
    pdf_root = root / "sample-materials" / "pdf" / "PS9-FORCES-01"
    spec = root / "config" / "ps9-forces-01.package.toml"
    roster = root / "config" / "ps9-roster.txt"
    assessment = pdf_root / "01-test-paper.pdf"
    sheets = pdf_root / "answer-sheets"
    missing = [str(p) for p in (spec, roster, assessment, sheets) if not p.exists()]
    if missing:
        raise LiveAcceptanceRefused(
            f"the acceptance corpus is missing {missing} (set {MATERIALS_ROOT_ENV} to the "
            f"materials root holding config/, sample-materials/pdf)."
        )
    return spec, roster, assessment, sheets


def _drive_live_pipeline(
    store: Any,
    run_config: Any,
    cohort: Any,
    *,
    provider: Any,
    decision_provider: Any,
) -> str:
    """The one full-pipeline drive: cohort, package, intake, then run to completion.

    Composed the way `aeh run` composes it (`pipeline.cli._run_command`): the providers are
    built before the run exists (the retention gate asks them inside `create_run`), the run is
    created against the built package version, started, and driven to completion with the same
    providers bound. The random-arm sample is held at 0 for the drive: it widens panels past
    the panel with no spare live seat, which would send a derived name to a real server.
    Returns the run id. The store is the caller's — opened by it, closed by it — so the
    caller's own reads after the drive see the same handle, and no second connection is held
    against the same file.
    """
    from aeh.orch import Orchestrator
    from aeh.orch.cohorts import create_cohort
    from aeh.pipeline.driver import run_to_completion
    from aeh.pipeline.intake import answer_sheet_files, ingest_files
    from aeh.pipeline.packages import (
        build_package,
        packages_folder,
        plan_package,
        read_package_spec,
    )
    from aeh.pipeline.rosters import read_roster_file

    spec_path, roster_path, assessment, sheets_dir = _materials_paths()
    entries = read_roster_file(roster_path)
    spec = read_package_spec(spec_path)
    plan_package(spec, packages_folder(store))

    create_cohort(store, cohort.cohort_id, cohort.consent_class, entries)
    built = build_package(store, spec)

    intake = ingest_files(
        store, run_config, cohort.cohort_id, built.package_version,
        assessment=assessment, sheets=answer_sheet_files((sheets_dir,)), provider=provider)
    if not intake.read:
        raise LiveAcceptanceRefused(
            "the acceptance corpus read no answer sheet; the legs cannot be accounted over a "
            "cohort with nothing scored."
        )

    previous_rate = os.environ.get(RANDOM_ARM_RATE_ENV)
    os.environ[RANDOM_ARM_RATE_ENV] = "0"
    try:
        orchestrator = Orchestrator(store, provider=provider, decision_provider=decision_provider)
        run_id = orchestrator.create_run(cohort.cohort_id, built.package_version, run_config)
        orchestrator.start(run_id)
        result = run_to_completion(
            store, run_id, provider=provider, run_config=run_config,
            decision_provider=decision_provider)
    finally:
        if previous_rate is None:
            os.environ.pop(RANDOM_ARM_RATE_ENV, None)
        else:
            os.environ[RANDOM_ARM_RATE_ENV] = previous_rate

    if str(result.status) != "complete":
        raise LiveAcceptanceRefused(
            f"the live run ended {result.status!r}, not complete — the acceptance cannot "
            f"account legs over a run that never finished (a paused run is legs that did not "
            f"run, not findings to report)."
        )
    return run_id


# --- the per-criterion figures (FR-CONFORM-18) ----------------------------------------------------


def _band_agreement(store: Any, cohort_id: str, run_id: str) -> dict[str, Mapping[str, Any]]:
    """Per criterion, the Jev band against the LLM panel's median band, on the same cells.

    The engine's band per cell is the pre-screen row's `band_probabilities`, stored as a JSON
    list ordered by band ordinal — the argmax index IS the ordinal, and a tied top has no band
    (the same rule `aeh.conform.decision` states for the fixture set). The panel's band per
    cell is the median of the `scoring_engine = 'llm'` verdict ordinals. Agreement is measured
    only where both operands exist — a cell the engine never banded, or the panel never
    scored, has no agreement to report — and a criterion with no comparable cell reports None
    rather than a fabricated number.

    An even panel's median can fall between two ordinals; a distance within one band still
    counts as adjacent, which is what `decision_band_adjacent_agreement` claims.
    """
    from aeh.judge.schema import JUDGE_STATEMENTS

    handle = store.cohort(cohort_id)
    engine_cells: dict[tuple[str, str], int | None] = {}
    for row in handle.query(JUDGE_STATEMENTS["select_run_prescreen_bands"], run_id=run_id):
        probabilities = json.loads(row["band_probabilities"]) if row["band_probabilities"] else ()
        top = max(probabilities) if probabilities else None
        banded = top is not None and probabilities.count(top) == 1
        engine_cells[(str(row["submission_id"]), str(row["criterion_id"]))] = (
            probabilities.index(top) if banded else None)
    llm_ordinals: dict[tuple[str, str], list[int]] = {}
    for row in handle.query(JUDGE_STATEMENTS["select_run_llm_band_ordinals"], run_id=run_id):
        llm_ordinals.setdefault(
            (str(row["submission_id"]), str(row["criterion_id"])), []).append(
            int(row["band_ordinal"]))

    def figures_for(criterion: str) -> Mapping[str, Any]:
        deltas: list[float] = []
        for (submission_id, cell_criterion), medians in llm_ordinals.items():
            if cell_criterion != criterion:
                continue
            engine_ord = engine_cells.get((submission_id, cell_criterion))
            if engine_ord is None:
                continue
            deltas.append(abs(engine_ord - statistics.median(medians)))
        comparable = len(deltas)
        if not comparable:
            return {
                "decision_band_exact_agreement": None,
                "decision_band_adjacent_agreement": None,
                "decision_llm_median_divergence": None,
            }
        exact = sum(1 for d in deltas if d == 0) / comparable
        adjacent = sum(1 for d in deltas if d <= 1) / comparable
        return {
            "decision_band_exact_agreement": exact,
            "decision_band_adjacent_agreement": adjacent,
            "decision_llm_median_divergence": 1.0 - exact,
        }

    criteria = {cell for (_, cell) in engine_cells} | {cell for (_, cell) in llm_ordinals}
    return {criterion: figures_for(criterion) for criterion in sorted(criteria)}


# --- the entry point ------------------------------------------------------------------------------


def run_live_acceptance(run_config: Any, *, cohort: Any, data_dir: Path) -> LiveAcceptanceReport:
    """One live acceptance: the full pipeline on the profile's real models, accounted per leg.

    The four precondition gates run first (`_refusal_gates`); then the pipeline is driven once
    over the committed acceptance corpus through the counting providers; then the report is
    computed — per-leg figures from the tallies, per-criterion rates from the CT-JUDGE-28
    surface (`aeh.judge.metrics.decision_engine_metrics`), band agreement from the run's own
    pre-screen and verdict rows. A leg with zero calls fails the report (`failed_legs`) and an
    extreme rate marks it invalid (`invalid_extremes`, naming the extreme and the frozen gate
    values). The per-leg figures are recorded into `run_metrics` through M-ORCH's write path,
    so the report and the durable record are the same numbers.
    """
    from aeh.judge.metrics import decision_engine_metrics
    from aeh.orch import Orchestrator
    from aeh.store import open_store

    _refusal_gates(run_config)
    _import_full_chain()
    completion, decision, tallies = _counting_providers(run_config)
    store = open_store(Path(data_dir))
    try:
        run_id = _drive_live_pipeline(
            store, run_config, cohort, provider=completion, decision_provider=decision)

        handle = store.cohort(cohort.cohort_id)
        metrics = decision_engine_metrics(handle, run_id)
        agreement = _band_agreement(store, cohort.cohort_id, run_id)
        threshold = Decimal(str(run_config.decision_engine.confidence_threshold))

        per_criterion: dict[str, dict[str, Any]] = {}
        invalid_extremes: dict[str, dict[str, Any]] = {}
        for criterion, figures in metrics.per_criterion.items():
            entry: dict[str, Any] = {
                "decision_accepted_rate": figures.decision_accepted_rate,
                "decision_fallback_rate": figures.decision_fallback_rate,
                # The key set is the contract (CT-CONFORM-C17): a criterion with no comparable
                # cell carries None rather than a missing key — *unmeasured* and *absent* are
                # different facts, and only the first is a measurement.
                "decision_band_exact_agreement": None,
                "decision_band_adjacent_agreement": None,
                "decision_llm_median_divergence": None,
            }
            entry.update(agreement.get(criterion, {}))
            per_criterion[criterion] = entry
            extremes = []
            if figures.decision_accepted_rate == 0:
                extremes.append("never_accepted")
            if figures.decision_fallback_rate == 0:
                extremes.append("never_fell_back")
            if extremes:
                invalid_extremes[criterion] = {
                    "extreme": tuple(extremes),
                    "gate": {"confidence_threshold": threshold},
                }

        legs = {leg: tallies[leg].figures() for leg in LIVE_LEGS}
        # CT-CONFORM-17: the decision leg carries the two rates beside the accounting keys —
        # the run's overall mix (per-criterion rates live in `per_criterion`).
        legs[LEG_DECISION]["decision_accepted_rate"] = metrics.decision_accepted_rate
        legs[LEG_DECISION]["decision_fallback_rate"] = metrics.decision_fallback_rate
        failed_legs = tuple(
            leg for leg in LIVE_LEGS if float(legs[leg][LIVE_CALLS]) == 0)

        report = LiveAcceptanceReport(
            run_id=run_id,
            legs=legs,
            per_criterion=per_criterion,
            valid=not failed_legs and not invalid_extremes,
            failed_legs=failed_legs,
            invalid_extremes=invalid_extremes,
        )
        _record_run_metrics(store, report)
        return report
    finally:
        store.close()


def _record_run_metrics(store: Any, report: LiveAcceptanceReport) -> None:
    """The per-leg figures, into `run_metrics` through M-ORCH's write path (`CT-STORE-03`).

    The metric name is `<key>.<leg>` (the table has no leg column); the values are floats —
    the cost's Decimal form does not survive a REAL column, and the report object is the
    precise figure. Cost None is written as 0.0: an unmeasured cost on a leg that made no
    calls is the same absence the zero-call count already names.
    """
    from aeh.orch import Orchestrator

    metrics: dict[str, float] = {}
    for leg, figures in report.legs.items():
        for key in LIVE_LEG_KEYS:
            value = figures[key]
            metrics[f"{key}.{leg}"] = float(value) if value is not None else 0.0
    Orchestrator(store).record_run_metrics(report.run_id, metrics)


def live_backend_legs(run_config: Any, cohort: Any, data_dir: Path) -> dict[str, dict[str, Any]]:
    """The re-specified TC-CONFORM-04 arm: the same drive for a conformance-suite backend.

    A live OpenRouter backend whose config resolves the decision engine drives the full
    pipeline once (the same corpus, providers and accounting as `run_live_acceptance`) and its
    `BackendResult` carries the per-leg figures beside the divergence figures. Only the legs
    are returned: the differential's subject is the backend's own pass over the fixture set;
    this drive exists so the report can show the decision leg really ran on the profile's
    default engine.
    """
    from aeh.store import open_store

    _refusal_gates(run_config)
    _import_full_chain()
    completion, decision, tallies = _counting_providers(run_config)
    store = open_store(Path(data_dir))
    try:
        _drive_live_pipeline(
            store, run_config, cohort, provider=completion, decision_provider=decision)
        return {leg: tallies[leg].figures() for leg in LIVE_LEGS}
    finally:
        store.close()

