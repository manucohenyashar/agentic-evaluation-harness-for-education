"""The results and reports a conformance run produces."""

from __future__ import annotations

from typing import TYPE_CHECKING

import dataclasses
from typing import Any, Mapping

from .errors import MergeRefused

if TYPE_CHECKING:
    from .suite import IngestOutcome


@dataclasses.dataclass(frozen=True)
class UnitOutcome:
    """One fixture's judgment, from the recorded replay.

    `band` is the fixture's unit band (the mode of its declared per-criterion bands),
    `citation_verification_outcome` the replayed citation verdict, and `confidence` the
    derived confidence in [0, 1] — the three paired properties the adversarial differential
    compares (`TWIN_PROPERTIES`).
    """

    band: str
    citation_verification_outcome: str
    confidence: float


@dataclasses.dataclass(frozen=True)
class BackendResult:
    """One backend's run over the fixture set, with the observability fields the contract requires.

    `stages_executed` is per fixture (`CT-CONFORM-03`'s sweep reads it that way); the fixtures
    the real ingest ladder quarantined are absent from it — they were never scored — and are
    recorded in `ingest_outcomes` instead. `figures` carries the per-dimension measurement each
    divergence value stands on, keyed by the five declared dimension names (plus the
    `self_agreement` figure alias `TC-CONFORM-12` reads).
    """

    backend_profile: str
    input_set_hash: str
    stages_executed: Mapping[str, tuple[str, ...]]
    transcription_dispatch: str
    figures: Mapping[str, Any]
    outcomes: Mapping[str, UnitOutcome]
    ingest_outcomes: Mapping[str, "IngestOutcome"]
    duration_seconds: float


@dataclasses.dataclass(frozen=True)
class ValidationRecord:
    """One backend's validation figures, keyed on the catalog's seven-part key (FR-PKG-08).

    The durable form is `aeh.pkg.record_promotion`'s row under the same administration key;
    `write_merged_validation_record` exists so that refusing the merge is an offered refusal.
    """

    package_version: str
    criterion: str
    population_scope: str
    backend_profile: str
    panel_build_ref: str
    scoring_model: str
    administration: str
    figure: Mapping[str, Any]


@dataclasses.dataclass(frozen=True)
class DivergenceReport:
    """The divergence between two backends on each dimension, with no single headline number.

    One field: the five declared dimensions, each with its measured value. A single combined
    figure is exactly what `CT-CONFORM-04` forbids, and the sweep over this surface runs in the
    suite — so the class carries the measurement and nothing that could read as a score.
    """

    dimensions: Mapping[str, float]


@dataclasses.dataclass(frozen=True)
class ConformanceReport:
    """What a conformance run reports: per-backend results, the divergence, the
    blocking/informational split, and the validation records.

    The partition is exhaustive by construction (`blocking_dimensions`, `findings`,
    `unavailable_dimensions`, `passing_dimensions` — every dimension in exactly one bucket);
    `blocked` is the live gate having crossed, not a summary of the dimensions. The
    score-distribution gate is always in `unavailable_dimensions` (`CT-CONFORM-14`): no
    statistic is declared for it, so no run may report it passing.
    """

    per_backend: Mapping[str, BackendResult]
    divergence: DivergenceReport
    observability: Mapping[str, Any]
    validation_records: tuple[ValidationRecord, ...]
    input_set_hash: str
    package_version: str
    build_changed_error_raised: bool
    blocked: bool
    blocking_dimensions: tuple[str, ...]
    findings: Mapping[str, float]
    unavailable_dimensions: tuple[str, ...]
    passing_dimensions: tuple[str, ...]
    completed: bool
    fixtures_scored: int
    tier: str | None
    consent_class: str

    def write_merged_validation_record(self, first: Any, second: Any) -> None:
        """Always refuses: two backends' records never become one (CT-CONFORM-06)."""
        raise MergeRefused(
            "a merged validation record answers for no population: it would span "
            f"{getattr(first, 'backend_profile', '?')!r} and "
            f"{getattr(second, 'backend_profile', '?')!r}, and CT-CONFORM-06 scopes every "
            "record to the backend profile and panel build that produced it. Write each "
            "backend's record through aeh.pkg.record_validation instead."
        )


@dataclasses.dataclass(frozen=True)
class DistributionReport:
    """One corpus's per-criterion score distribution, as the regression run reports it (TC-REG-05).

    The frozen corpus re-run is the regression's subject: a *shift* on an unchanged package is
    build substitution (`FR-CONFORM-08`), not a baseline to update. `package_version` is what
    the set declares; `backend` names the single backend the distribution stands for.
    """

    per_criterion_distribution: Mapping[str, Mapping[str, float]]
    package_version: str
    backend: str


@dataclasses.dataclass(frozen=True)
class BuildSubstitutionFinding:
    """What `detect_build_substitution` returns when the same frozen set scored differently.

    The attribution is the assertion (`CT-CONFORM-07`): a score shift on frozen fixtures with
    an unchanged package is a provider-side build substitution, not a package finding —
    reporting it as the latter sends someone to audit a rubric nobody touched. `package_changed`
    and `package_version_changed` are the same fact under the two names the two suites read.
    """

    attribution: str
    package_changed: bool
    substitution_detected: bool

    @property
    def package_version_changed(self) -> bool:
        return self.package_changed


@dataclasses.dataclass(frozen=True)
class ConformanceAlert:
    """One fired alert, with a `kind` naming its condition (CT-CONFORM-13)."""

    kind: str


@dataclasses.dataclass(frozen=True)
class AdversarialTierReport:
    """What running one adversarial corpus through the tier reports (TC-CONFORM-09).

    `F-ADV-INJ` yields differential `outcomes` for every member; `F-ADV-PDF` yields
    `ingest_outcomes` — the real ladder's verdict per construct, with no model calls reached.
    `consent_class` is the corpus's own declaration carried onto the run.
    """

    fixture_set_id: str
    outcomes: Mapping[str, UnitOutcome]
    ingest_outcomes: Mapping[str, "IngestOutcome"]
    consent_class: str
