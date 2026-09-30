"""The recorded replay of each backend, and the per-dimension divergence between two of them."""

from __future__ import annotations

from typing import TYPE_CHECKING

import os
from typing import Any, Mapping, Sequence

from harness.corpora.manifest import read_manifest

from .constants import (
    AGREEMENT_DIMENSION,
    CONFIDENCE_DIMENSION,
    DIVERGENCE_DIMENSIONS,
    EVIDENCE_INTEGRITY_DIMENSION,
    EXPECTED_CLASSIFICATION,
    SCORE_DISTRIBUTION_DIMENSION,
    SELF_AGREEMENT_DIMENSION,
    SELF_AGREEMENT_FIELD,
    SELF_AGREEMENT_REPEATS_FIELD,
)
from .errors import ConformanceError
from .bands import _band_scale, _shift_bands_one_step, _SUBSTITUTION_MARKER
from .fixtures import _fixture_root, FixtureSet, FixtureSubmission, load_fixture_set
from .reports import BackendResult, DivergenceReport, UnitOutcome

if TYPE_CHECKING:
    from .suite import IngestOutcome


#: Env-gated knobs (seam 3): the divergence values below a tolerance count as agreement, the
#: confidence figure's escalation threshold, and the value an induced divergence carries.
DIVERGENCE_TOLERANCE_ENV = "HARNESS_CONFORM_DIVERGENCE_TOLERANCE"


ESCALATION_THRESHOLD_ENV = "HARNESS_CONFORM_ESCALATION_THRESHOLD"


INDUCED_DIVERGENCE_ENV = "HARNESS_CONFORM_INDUCED_DIVERGENCE"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _divergence_tolerance() -> float:
    return _env_float(DIVERGENCE_TOLERANCE_ENV, 0.0)


def _escalation_threshold() -> float:
    return _env_float(ESCALATION_THRESHOLD_ENV, 0.8)


def _induced_divergence_value() -> float:
    return _env_float(INDUCED_DIVERGENCE_ENV, 0.5)


_ACTIVE_INDUCED_DIMENSIONS: set[str] = set()


_QUARANTINE_OUTCOMES: dict[str, IngestOutcome] = {}


_LADDER_OUTCOMES: dict[tuple[str, str], IngestOutcome] = {}


_SOURCE_BANDS_CACHE: dict[str, dict[str, dict[str, str]]] = {}


_SET_CACHE: dict[tuple[str, str], FixtureSet] = {}


def induced_divergence(dimension: str) -> Any:
    """Within the block, force a divergence on one dimension for the runs taken; used to test the
    classification.

    The induced value stands in for a measured divergence the recorded transport cannot
    produce on its own — a clean replay of declared references agrees by construction, so the
    gate's *blocking* behaviour (`CT-CONFORM-05`) is driven through this seam rather than
    asserted over a static report. The dimension must be one of the five declared ones; the
    magnitude is env-tunable (`HARNESS_CONFORM_INDUCED_DIVERGENCE`, default 0.5).
    """
    if dimension not in DIVERGENCE_DIMENSIONS:
        raise ConformanceError(
            f"{dimension!r} is not one of the five declared divergence dimensions"
        )

    class _Induced:
        def __enter__(self) -> None:
            _ACTIVE_INDUCED_DIMENSIONS.add(dimension)

        def __exit__(self, *exc: Any) -> None:
            _ACTIVE_INDUCED_DIMENSIONS.discard(dimension)

    return _Induced()


def classify_divergence(dimension: str, divergence: Any) -> str:
    """How a divergence on this dimension is classified, from the design's table (§7.4).

    Static on purpose: the classification is the dimension's *computability as a gate*, not a
    function of the measured value. The score-distribution gate is `unavailable` whether or not
    a value was induced — that is `CT-CONFORM-14`'s hole, and reporting it `pass` because a
    value existed would be exactly the strength a release decision reads a gate on. Whether the
    integrity gate *fired* is the run's `blocked`, not this classification.
    """
    return EXPECTED_CLASSIFICATION[dimension]


def silent_build_substitution(backend_config: Mapping[str, Any]) -> Any:
    """Replace the backend configuration with one whose build was silently substituted; used to
    test detection.

    The substitution keeps the reported build identical and changes only what the model does —
    the shape of a provider swapping a quantization behind an unchanged name (RISK-22), the
    configuration `BuildChangedError` cannot see (`CT-CONFORM-07`). The run under the swapped
    config shifts one criterion's declared band one step up its scale and resolves a
    substituted serving identity, so both detection paths (`detect_build_substitution` and the
    resolved-vs-requested observability) have the failure to find.
    """
    swapped = dict(backend_config)
    swapped[_SUBSTITUTION_MARKER] = True

    class _Substituted:
        def __enter__(self) -> Mapping[str, Any]:
            return swapped

        def __exit__(self, *exc: Any) -> None:
            swapped.pop(_SUBSTITUTION_MARKER, None)

    return _Substituted()


def _source_bands() -> dict[str, dict[str, str]]:
    """The declared reference band for each criterion, collected from the source corpora.

    `F-CONFORM` is a selection: its rows cite source corpora, and the bands live there. The
    join is by member id (the frozen set's `submission_id` is the source row's `id`), over the
    three corpora that declare bands, keyed by the fixture root so an override of
    `HARNESS_FIXTURE_ROOT` re-reads rather than serving a cached join.
    """
    key = str(_fixture_root())
    cached = _SOURCE_BANDS_CACHE.get(key)
    if cached is not None:
        return cached
    bands: dict[str, dict[str, str]] = {}
    for corpus in ("F-FROZEN", "F-ADV-INJ", "F-SCAN"):
        manifest = read_manifest(_fixture_root() / corpus / "manifest.json")
        for row in manifest["submissions"]:
            declared = row.get("reference_bands")
            if declared:
                bands[row["id"]] = dict(declared)
    _SOURCE_BANDS_CACHE[key] = bands
    return bands


def _load_set_memo(pin: str) -> FixtureSet:
    """The loaded fixture set, cached per (fixture root, pin) so the digest checks run once per
    process. The root is part of the key, so changing `HARNESS_FIXTURE_ROOT` mid-process loads the
    new root's set."""
    key = (str(_fixture_root()), pin)
    cached = _SET_CACHE.get(key)
    if cached is None:
        cached = load_fixture_set(pin)
        _SET_CACHE[key] = cached
    return cached


def _derive_units(
    submissions: Sequence[FixtureSubmission],
    bands_by_id: Mapping[str, Mapping[str, str]],
    *,
    substituted: bool = False,
) -> dict[str, tuple[dict[str, str], UnitOutcome]]:
    """Replay the recordings: every fixture with a declared reference, with its bands and judgment.

    The replay IS the derivation — the corpus declares what a correct judgment found, and the
    recorded transport replays it through the grading semantics (per-criterion bands, the unit
    band as their mode, the confidence as the share of criteria at the top of their scale). A
    substituted backend's `C-01` shifts one step first, which is the whole difference the
    detection path exists to catch.
    """
    units: dict[str, tuple[dict[str, str], UnitOutcome]] = {}
    for submission in submissions:
        declared = bands_by_id.get(submission.submission_id)
        if not declared:
            continue
        bands = _shift_bands_one_step(declared) if substituted else dict(declared)
        counts: dict[str, int] = {}
        for band in bands.values():
            counts[band] = counts.get(band, 0) + 1

        def _rank(band: str) -> tuple[int, int]:
            return (-counts[band], _band_scale(band).index(band))

        unit_band = min(counts, key=_rank)
        top = sum(
            1 for band in bands.values() if _band_scale(band).index(band) == len(_band_scale(band)) - 1
        )
        confidence = top / len(bands) if bands else 0.0
        units[submission.submission_id] = (
            bands,
            UnitOutcome(
                band=unit_band,
                citation_verification_outcome="verified",
                confidence=confidence,
            ),
        )
    return units


def _figures_for(
    units: Mapping[str, tuple[dict[str, str], UnitOutcome]],
    repeats: Mapping[str, tuple[dict[str, str], UnitOutcome]],
) -> dict[str, Any]:
    """One backend's figures for each dimension; every divergence value is computed from these.

    The self-agreement figure is computed from the two derivation passes: the agreement rate is
    the share of fixtures whose two judgments agree, and `n` — the figure's stated sample size
    (`TC-CONFORM-12`) — is the number of fixtures whose judgments were compared.
    """
    distribution: dict[str, dict[str, float]] = {}
    carrying: dict[str, int] = {}
    confidences: list[float] = []
    agreed = 0
    for submission_id, (bands, unit) in units.items():
        for criterion, band in bands.items():
            slot = distribution.setdefault(criterion, {})
            slot[band] = slot.get(band, 0.0) + 1.0
            carrying[criterion] = carrying.get(criterion, 0) + 1
        confidences.append(unit.confidence)
        repeat_unit = repeats.get(submission_id)
        if repeat_unit is not None and repeat_unit[1].band == unit.band:
            agreed += 1
    shares = {
        criterion: {band: count / carrying[criterion] for band, count in counts.items()}
        for criterion, counts in distribution.items()
    }
    escalation_threshold = _escalation_threshold()
    escalated = sum(1 for c in confidences if c >= escalation_threshold)
    agreement_rate = agreed / len(units) if units else 0.0
    self_agreement = {
        SELF_AGREEMENT_REPEATS_FIELD: len(units),
        "agreement_rate": agreement_rate,
    }
    return {
        SCORE_DISTRIBUTION_DIMENSION: shares,
        AGREEMENT_DIMENSION: {"kappa": 1.0, "n": len(units)},
        CONFIDENCE_DIMENSION: {
            "mean_confidence": sum(confidences) / len(confidences) if confidences else 0.0,
            "escalation_rate": escalated / len(confidences) if confidences else 0.0,
            "n": len(confidences),
        },
        EVIDENCE_INTEGRITY_DIMENSION: {"failure_rate": 0.0, "n": len(units)},
        SELF_AGREEMENT_DIMENSION: self_agreement,
        # The alias `TC-CONFORM-12` reads: the figure travels under its own field name as well
        # as its dimension's, so the n cannot travel apart from the figure it qualifies.
        SELF_AGREEMENT_FIELD: self_agreement,
    }


def _score_distribution_distance(
    first: Mapping[str, Mapping[str, float]], second: Mapping[str, Mapping[str, float]]
) -> float:
    """The total variation distance between two backends' per-criterion distributions, for the
    worst criterion.

    TV is half the L1 distance over each criterion's declared bands; the reported value is the
    worst criterion. A distribution is per criterion precisely so a shift on one criterion is
    visible rather than averaged into a pooled figure.
    """
    worst = 0.0
    for criterion in set(first) | set(second):
        bands = set(first.get(criterion, {})) | set(second.get(criterion, {}))
        distance = sum(
            abs(first.get(criterion, {}).get(band, 0.0) - second.get(criterion, {}).get(band, 0.0))
            for band in bands
        ) / 2.0
        worst = max(worst, distance)
    return worst


def _dimension_divergence(
    results: Sequence[BackendResult], induced: frozenset[str]
) -> DivergenceReport:
    """The divergence between two backends on each of the five dimensions.

    With a single backend the comparison is the backend against itself — zero everywhere, the
    honest statement that one measurement compares against nothing. An induced dimension's
    value replaces the measured one for the runs taken inside `induced_divergence`.
    """
    first, second = results[0], results[-1]

    def _figure_of(result: Any, dimension: str) -> Mapping[str, Any]:
        return getattr(result, "figures", {}).get(dimension) or {}

    agreement_first = _figure_of(first, AGREEMENT_DIMENSION)
    agreement_second = _figure_of(second, AGREEMENT_DIMENSION)
    confidence_first = _figure_of(first, CONFIDENCE_DIMENSION)
    confidence_second = _figure_of(second, CONFIDENCE_DIMENSION)
    integrity_first = _figure_of(first, EVIDENCE_INTEGRITY_DIMENSION)
    integrity_second = _figure_of(second, EVIDENCE_INTEGRITY_DIMENSION)
    self_first = _figure_of(first, SELF_AGREEMENT_DIMENSION)
    self_second = _figure_of(second, SELF_AGREEMENT_DIMENSION)
    dimensions = {
        SCORE_DISTRIBUTION_DIMENSION: _score_distribution_distance(
            _figure_of(first, SCORE_DISTRIBUTION_DIMENSION),
            _figure_of(second, SCORE_DISTRIBUTION_DIMENSION),
        ),
        AGREEMENT_DIMENSION: abs(
            float(agreement_first.get("kappa", 0.0)) - float(agreement_second.get("kappa", 0.0))
        ),
        CONFIDENCE_DIMENSION: max(
            abs(float(confidence_first.get("mean_confidence", 0.0)) - float(confidence_second.get("mean_confidence", 0.0))),
            abs(float(confidence_first.get("escalation_rate", 0.0)) - float(confidence_second.get("escalation_rate", 0.0))),
        ),
        EVIDENCE_INTEGRITY_DIMENSION: abs(
            float(integrity_first.get("failure_rate", 0.0))
            - float(integrity_second.get("failure_rate", 0.0))
        ),
        SELF_AGREEMENT_DIMENSION: abs(
            float(self_first.get("agreement_rate", 0.0)) - float(self_second.get("agreement_rate", 0.0))
        ),
    }
    if induced:
        induced_value = _env_float(INDUCED_DIVERGENCE_ENV, 0.5)
        for dimension in induced:
            dimensions[dimension] = induced_value
    return DivergenceReport(dimensions=dimensions)
