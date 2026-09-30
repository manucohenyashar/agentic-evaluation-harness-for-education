"""Detecting a silent build substitution, and the alerts a conformance report fires."""

from __future__ import annotations

from typing import Any, Mapping

from .constants import (
    ALERT_BUILD_SUBSTITUTION_DETECTED,
    ALERT_DIVERGENCE_GATE_CROSSED,
    REQUESTED_BUILDS_FIELD,
    RESOLVED_BUILDS_FIELD,
    SCORE_DISTRIBUTION_DIMENSION,
)
from .errors import ConformanceError
from .reports import BuildSubstitutionFinding, ConformanceAlert
from .divergence import _divergence_tolerance


def _score_distributions_of(report: Any) -> Mapping[str, Mapping[str, Mapping[str, float]]]:
    """The per-backend score distributions a report carries, whatever its shape."""
    per_backend = getattr(report, "per_backend", None)
    if per_backend is not None:
        return {
            str(profile): dict(result.figures[SCORE_DISTRIBUTION_DIMENSION])
            for profile, result in per_backend.items()
        }
    distribution = getattr(report, "per_criterion_distribution", None)
    if distribution is not None:
        return {str(getattr(report, "backend", "recorded-fixture")): dict(distribution)}
    raise ConformanceError(
        "detect_build_substitution reads per-backend score distributions; the report carries "
        "neither per_backend results nor a per_criterion_distribution"
    )


def _distributions_differ(
    first: Mapping[str, Mapping[str, float]],
    second: Mapping[str, Mapping[str, float]],
    tolerance: float,
) -> bool:
    for criterion in set(first) | set(second):
        bands = set(first.get(criterion, {})) | set(second.get(criterion, {}))
        for band in bands:
            difference = abs(
                first.get(criterion, {}).get(band, 0.0)
                - second.get(criterion, {}).get(band, 0.0)
            )
            if difference > tolerance:
                return True
    return False


def detect_build_substitution(
    baseline: Any | None = None,
    rerun: Any | None = None,
    package_version: str | None = None,
    *,
    tolerance: float | None = None,
) -> BuildSubstitutionFinding | None:
    """Detect a provider-side build substitution between two runs of the same frozen set.

    Both report shapes the suites drive are accepted: a `ConformanceReport` (per-backend
    figures) and a `DistributionReport` (`TC-REG-05`'s single-backend re-run). The comparison
    is over the score distributions of the backends the two runs share, at the divergence
    tolerance (`HARNESS_CONFORM_DIVERGENCE_TOLERANCE`, default 0.0 — an exact comparison, which
    is what "strict" means on a deterministic transport). `None` means the re-run scored
    identically: no finding, no suspicion. A shift with the package unchanged is the finding —
    attributed to the provider (`CT-CONFORM-07`), never to the package.
    """
    if rerun is None:
        raise ConformanceError(
            "detect_build_substitution compares two reports; a rerun is required"
        )
    if baseline is None:
        raise ConformanceError(
            "detect_build_substitution compares two reports; a baseline is missing"
        )
    resolved_tolerance = _divergence_tolerance() if tolerance is None else tolerance
    baseline_distributions = _score_distributions_of(baseline)
    rerun_distributions = _score_distributions_of(rerun)
    common = sorted(set(baseline_distributions) & set(rerun_distributions))
    if not common:
        raise ConformanceError(
            "the two reports share no backend profile, so no per-backend comparison is "
            f"possible: {sorted(baseline_distributions)} vs {sorted(rerun_distributions)}"
        )
    substituted = any(
        _distributions_differ(baseline_distributions[p], rerun_distributions[p], resolved_tolerance)
        for p in common
    )
    if not substituted:
        return None
    baseline_version = (
        package_version if package_version is not None else getattr(baseline, "package_version", None)
    )
    rerun_version = getattr(rerun, "package_version", None)
    package_changed = bool(
        substituted
        and baseline_version is not None
        and rerun_version is not None
        and baseline_version != rerun_version
    )
    return BuildSubstitutionFinding(
        attribution="provider_side_build_substitution",
        package_changed=package_changed,
        substitution_detected=True,
    )


def evaluate_conformance_alerts(report: Any) -> list[ConformanceAlert]:
    """The alerts a report fires, each keyed on its own condition (`CT-CONFORM-13`).

    `divergence_gate_crossed` fires exactly when the live gate blocked the run;
    `build_substitution_detected` exactly when some profile's resolved builds differ from what
    was requested. A clean run fires nothing, and the set is closed — a new alert is additive
    by amendment to the declared kinds, not by a third kind inventing itself.
    """
    alerts: list[ConformanceAlert] = []
    if getattr(report, "blocked", False):
        alerts.append(ConformanceAlert(kind=ALERT_DIVERGENCE_GATE_CROSSED))
    observability = getattr(report, "observability", None) or {}
    resolved = observability.get(RESOLVED_BUILDS_FIELD)
    requested = observability.get(REQUESTED_BUILDS_FIELD)
    if resolved and requested:
        if any(resolved[profile] != requested.get(profile) for profile in resolved):
            alerts.append(ConformanceAlert(kind=ALERT_BUILD_SUBSTITUTION_DETECTED))
    return alerts
