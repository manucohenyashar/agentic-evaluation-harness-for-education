"""`RunConfig`, the frozen configuration of one run, and the summaries shown to people."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Literal

from .vocabulary import BACKEND_PROFILES, BackendProfile, HardwareProfileName, PANEL_SIZES
from .errors import BackendMismatchError, ConfigurationError
from .frozen import _typeerror_on_mutation
from .model_ref import ModelRef, _ref_to_dict, _require_model_ref
from .decision_engine import (
    DECISION_PROVIDERS_BY_PROFILE,
    DecisionEngine,
    FIXTURE_DECISION_PROVIDER,
    PROVIDER_MANAGED,
)
from .checks import _check_resolved, _COST_BEARING_PROFILES, _echo, RETENTION_SETTINGS
from .panel import _build_identity, compute_panel_build_ref


@_typeerror_on_mutation
@dataclass(frozen=True)
class CohortRef:
    """The cohort a run grades. `consent_class` records whether its work may leave the building
    (ADR-5).

    The default is `"real"` and that is load-bearing: `TC-CONF-08` calls the undeclared-cohort
    row "the difference between a fail-closed and a fail-open design". The gate that reads it is
    `FR-CONF-08`, in `_check_consent`; the default belongs here because this is where the type lives.
    """

    cohort_id: str
    consent_class: Literal["synthetic", "consented", "real"] = "real"

    def __post_init__(self) -> None:
        """Check field types only, as `ModelRef` does.

        `_check_consent` tests `consent_class in CONSENTED_CLASSES` against a `frozenset`, so an
        unhashable value escaped `resolve_run_config` as a bare `TypeError` — undeclared, which
        `CT-CONF-08`'s closed taxonomy and `TC-CONF-15`'s invariant both forbid. `TC-CONF-15`
        holds the cohort fixed and fuzzes only `cfg`, so the green suite could not see it.
        """
        if not isinstance(self.cohort_id, str) or not self.cohort_id.strip():
            raise ConfigurationError(
                f"CohortRef.cohort_id must be a non-empty string, got "
                f"{type(self.cohort_id).__name__}."
            )
        if self.consent_class not in ("synthetic", "consented", "real"):
            raise ConfigurationError(
                "CohortRef.consent_class must be 'synthetic', 'consented' or 'real' (ADR-5). "
                "An unrecognized value is refused rather than treated as unconsented, so a "
                "typo cannot quietly become a gate decision."
            )


@_typeerror_on_mutation
@dataclass(frozen=True)
class BuildSummary:
    """One model build, in the form the console shows and the audit record keeps.

    A projection of `ModelRef`, not the ref itself: `is_resolved()` and `build_form()` are
    resolution-time questions with no meaning on a stored record, and a summary that carried
    behaviour would invite a consumer to re-derive rather than read.
    """

    role: str
    provider: str
    build_id: str
    quantization: str

    @classmethod
    def of(cls, ref: ModelRef) -> "BuildSummary":
        return cls(
            role=ref.role,
            provider=ref.provider,
            build_id=ref.build_id,
            quantization=ref.quantization or PROVIDER_MANAGED,
        )


@_typeerror_on_mutation
@dataclass(frozen=True)
class ProfileSummary:
    """The run's grader identity (FR-CONF-09): backend profile, panel builds, transcriber build,
    quantization and, for cloud runs, the retention setting. The console shows it next to every
    grade, and the audit record stores it as is.

    More detail: `docs/code-notes/conf.md`, section `run_config.py: ProfileSummary`.
    """

    backend_profile: str
    panel: tuple[BuildSummary, ...]
    transcriber: BuildSummary
    off_panel_checker: BuildSummary | None
    quantization: tuple[str, ...]
    retention_setting: str | None
    panel_build_ref: str
    #: FR-CONF-26: the decision engine and its threshold, **omitted from the canonical JSON when
    #: the engine is off**, so an engine-off record stays byte-identical to its pre-delta form.
    decision_engine: BuildSummary | None = None
    decision_threshold: str | None = None

    def to_canonical_json(self) -> str:
        """The one serialization of this summary, so the same summary always gives the same bytes
        (TC-CONF-17).

        `M-ORCH` stores this record and `log_run_start` logs it. If each formatted the summary
        its own way, "byte-identical to the one logged at run start" would fail on whitespace
        and key order — a difference that is not a defect, reported as one. So there is exactly
        one serializer and both callers use it.

        `sort_keys=True` rather than field order: §3.1's Compatibility note makes a new
        `ProfileSummary` field additive, and ordering by declaration would let an additive change
        reorder every existing record.
        """
        record = asdict(self)
        if record["decision_engine"] is None:
            del record["decision_engine"]
            del record["decision_threshold"]
        return json.dumps(record, sort_keys=True, separators=(",", ":"))


@_typeerror_on_mutation
@dataclass(frozen=True)
class RunConfig:
    """One frozen answer to "which grader is this run?" (design §3.1).

    The field set is **exactly** these thirteen (Jev design delta FR-CONF-17 added
    `decision_engine`, defaulted `None` so a literal written before it still constructs an
    engine-off config). `CT-CONF-C02` asserts set equality rather than a
    subset, so adding a convenience field here breaks the contract suite by design — that is the
    clause working, not a broken test.

    Nullability, both directions (`CT-CONF-02`):

    | field | non-null iff |
    |---|---|
    | `hardware_profile` | `backend_profile == "edge-local"` |
    | `cost_ceiling`, `cost_currency` | `backend_profile in {"cloud-hosted", "dev-ci"}` |
    | `retention_setting` | `backend_profile == "cloud-hosted"`, and one of `RETENTION_SETTINGS` |

    No method returns a copy with a different backend or panel, and none will be added
    (`CT-CONF-14`, a safety property): a consumer needing a different backend creates a
    different run.
    """

    backend_profile: BackendProfile
    hardware_profile: HardwareProfileName | None
    panel: tuple[ModelRef, ...]
    transcriber: ModelRef
    off_panel_checker: ModelRef | None
    prompt_template_v: str
    concurrency_ceiling: int
    prefix_token_ceiling: int
    cost_ceiling: Decimal | None
    cost_currency: str | None
    retention_setting: str | None
    panel_build_ref: str
    decision_engine: DecisionEngine | None = None

    def __post_init__(self) -> None:
        """Enforce CT-CONF-02 and CT-CONF-03 on the type itself, not only in the resolver.

        This is what makes the invariants unforgeable. `dataclasses.replace` does not route
        through `__replace__` (see `_typeerror_on_mutation`), so without this a caller could
        take a resolved `edge-local` config and produce a `cloud-hosted` one still carrying
        `hardware_profile='unified-large'` and no cost ceiling — a value violating both of
        `CT-CONF-02`'s iffs at once, and one `resolve_run_config` can never return. An invariant
        that lives only in the function that happens to build the value is not an invariant.

        All three of `CT-CONF-02`'s nullability rules are enforced here, including
        `retention_setting` — added by #6 once `FR-CONF-12` had code, rather than asserted ahead
        of it.
        """
        if self.backend_profile not in BACKEND_PROFILES:
            raise ConfigurationError(
                f"backend_profile must be one of {BACKEND_PROFILES}, got "
                f"{_echo('HARNESS_PROFILE', self.backend_profile)}."
            )

        # A `tuple` specifically, not any sequence, and that is deliberate: the design declares
        # `panel: tuple[ModelRef, ...]`, and a `list` field would make `CT-CONF-04`'s "consumers
        # may hold one for the life of a run without defensive copying" false — the object would
        # be frozen while its panel stayed mutable. `resolve_run_config` converts for callers;
        # a literal has to pass a tuple.
        if not isinstance(self.panel, tuple) or len(self.panel) not in PANEL_SIZES:
            raise ConfigurationError(
                f"panel must be a tuple of {sorted(PANEL_SIZES)} ModelRefs, got "
                f"{type(self.panel).__name__} of length "
                f"{len(self.panel) if isinstance(self.panel, Sequence) else '?'} (CT-CONF-02)."
            )
        for position, member in enumerate(self.panel):
            _require_model_ref(member, f"panel[{position}]", "judge")
        _require_model_ref(self.transcriber, "transcriber", "transcriber")
        if self.off_panel_checker is not None:
            _require_model_ref(self.off_panel_checker, "off_panel_checker", "off_panel")

        # The two iffs, both directions. Asserting only "required when" would let a stray
        # non-null through on the profile that has no use for it.
        edge = self.backend_profile == "edge-local"
        if edge != (self.hardware_profile is not None):
            raise ConfigurationError(
                f"hardware_profile is non-null iff backend_profile is 'edge-local' "
                f"(CT-CONF-02); got backend_profile={self.backend_profile!r}, "
                f"hardware_profile={self.hardware_profile!r}."
            )
        hosted = self.backend_profile in _COST_BEARING_PROFILES
        for name, value in (("cost_ceiling", self.cost_ceiling), ("cost_currency", self.cost_currency)):
            if hosted != (value is not None):
                raise ConfigurationError(
                    f"{name} is non-null iff backend_profile is cloud-hosted or dev-ci "
                    f"(CT-CONF-02); got backend_profile={self.backend_profile!r} and "
                    f"{name}={'set' if value is not None else 'None'}."
                )

        # `CT-CONF-02`'s third nullability rule, and `FR-CONF-12`. On the type rather than only
        # in the resolver, for the reason `docs/code-notes/conf.md` gives about the other two: an
        # invariant enforced only by the function that builds the value is forgeable — through
        # `dataclasses.replace`, through a hand-written literal, and through `rehydrate_run_config`,
        # which reconstructs from a row rather than from `cfg` and so never reaches the resolver's
        # check. A `cloud-hosted` run resuming with `retention_setting=None` is a run proceeding
        # in the belief that retention is off.
        cloud = self.backend_profile == "cloud-hosted"
        if cloud != (self.retention_setting is not None):
            raise ConfigurationError(
                f"retention_setting is non-null iff backend_profile is 'cloud-hosted' "
                f"(CT-CONF-02, FR-CONF-12); got backend_profile={self.backend_profile!r} and "
                f"retention_setting={'set' if self.retention_setting is not None else 'None'}."
            )
        if cloud and self.retention_setting not in RETENTION_SETTINGS:
            raise ConfigurationError(
                f"retention_setting must be one of {RETENTION_SETTINGS} (FR-CONF-12). The "
                f"supplied value is not echoed here; it is not one of them."
            )

        for name in ("concurrency_ceiling", "prefix_token_ceiling"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ConfigurationError(
                    f"{name} must be an integer of at least 1, got {type(value).__name__}."
                )
        if not isinstance(self.prompt_template_v, str) or not self.prompt_template_v.strip():
            raise ConfigurationError("prompt_template_v must be a non-empty string.")

        # CT-CONF-03: every reachable ref is resolved, in the form this backend requires.
        for position, member in enumerate(self.panel):
            _check_resolved(member, f"panel[{position}]", self.backend_profile)
        _check_resolved(self.transcriber, "transcriber", self.backend_profile)
        if self.off_panel_checker is not None:
            _check_resolved(self.off_panel_checker, "off_panel_checker", self.backend_profile)

        # CT-CALIB-08 / NFR-CALIB-04: the off-panel checker is **not in the scoring panel**, and
        # a shared build is refused at configuration time — the moment the check can refuse,
        # before any calibration run reaches for it. A shared build would let the panel's own
        # blind spots define the adversarial search: the model looking for a response on which
        # R₀ and R₁ differ would be the same model that produced the scores, so the responses it
        # cannot imagine are exactly the ones it will not construct, and the back-translation
        # gate would pass by construction. Identity is the **build**, not the label — keyed on
        # the same encoding `compute_panel_build_ref` hashes, because two entries naming the
        # same served build are the same model however they are labelled.
        if self.off_panel_checker is not None:
            checker_identity = _build_identity(self.off_panel_checker)
            for position, member in enumerate(self.panel):
                if _build_identity(member) == checker_identity:
                    raise ConfigurationError(
                        f"off_panel_checker shares its served build with panel[{position}] "
                        f"({self.off_panel_checker.provider}/{self.off_panel_checker.build_id}"
                        f"{'/' + self.off_panel_checker.quantization if self.off_panel_checker.quantization else ''})"
                        " — the adversarial back-translation checker must not be one of the "
                        "models it checks (CT-CALIB-08, NFR-CALIB-04)."
                    )

        # CT-CONF-07: the ref must be the hash **of this panel**. Without this, a replace that
        # reorders the panel keeps the old ref, and two distinct ordered panels share one key —
        # verbatim the regression `TC-CONF-C07` exists to catch, and `CT-CONF-07` licenses
        # consumers to use the ref as a `package_validation` primary-key component.
        #
        # `rehydrate_run_config` checks the same thing earlier and raises `BackendMismatchError`
        # instead, because `TC-CONF-04`'s variant names that type for a row whose stored ref no
        # longer matches its stored builds -- a changed panel, not a malformed row.
        # FR-CONF-17/19: a decision engine is resolved, of role `decision`, and bound to the
        # provider this backend admits (the fixture double only under the test tier, which the
        # resolver checks; the type admits it so a rehydrated test run reconstructs).
        if self.decision_engine is not None:
            if not isinstance(self.decision_engine, DecisionEngine):
                raise ConfigurationError(
                    f"decision_engine must be a DecisionEngine or None, got "
                    f"{type(self.decision_engine).__name__}.")
            provider = self.decision_engine.model.provider
            allowed = DECISION_PROVIDERS_BY_PROFILE[self.backend_profile]
            if provider != FIXTURE_DECISION_PROVIDER and provider not in allowed:
                raise BackendMismatchError(
                    f"decision provider {provider!r} is not bound to backend_profile "
                    f"{self.backend_profile!r}; it admits {allowed} (FR-CONF-19).")
            _check_resolved(self.decision_engine.model, "decision_engine.model", self.backend_profile)

        expected_ref = compute_panel_build_ref(self.panel, self.decision_engine)
        if self.panel_build_ref != expected_ref:
            raise ConfigurationError(
                f"panel_build_ref does not match this panel: carries "
                f"{self.panel_build_ref!r}, the ordered panel hashes to {expected_ref!r} "
                f"(CT-CONF-07)."
            )

    def profile_summary(self) -> ProfileSummary:
        """The run's grader identity, ready to show or store (FR-CONF-09).

        Every reachable build appears, in panel order. "Every" is the load-bearing word: a
        summary listing the first judge and dropping the other two describes a panel that never
        ran, and `CT-CONSOLE-10` puts this record under a grade a teacher is reading.

        `quantization` collects the **distinct** labels rather than one per build, because the
        console shows it as a single fact about the run ("q4") and the per-build detail is
        already in `panel` and `transcriber`. Deduplicated in first-seen order, not sorted, so a
        mixed panel reads in the order the builds are listed above it.
        """
        builds = [BuildSummary.of(ref) for ref in self.panel]
        builds.append(BuildSummary.of(self.transcriber))
        if self.off_panel_checker is not None:
            builds.append(BuildSummary.of(self.off_panel_checker))

        return ProfileSummary(
            backend_profile=self.backend_profile,
            panel=tuple(BuildSummary.of(ref) for ref in self.panel),
            transcriber=BuildSummary.of(self.transcriber),
            off_panel_checker=(
                None
                if self.off_panel_checker is None
                else BuildSummary.of(self.off_panel_checker)
            ),
            quantization=tuple(dict.fromkeys(build.quantization for build in builds)),
            retention_setting=self.retention_setting,
            panel_build_ref=self.panel_build_ref,
            decision_engine=(None if self.decision_engine is None
                             else BuildSummary.of(self.decision_engine.model)),
            decision_threshold=(None if self.decision_engine is None
                                else str(self.decision_engine.confidence_threshold)),
        )

    def to_persisted_dict(self) -> dict[str, Any]:
        """The configuration without credentials, as M-ORCH writes it to the run row (FR-CONF-11).

        Shaped as design §3.1's three columns — *"`RunConfig` is serialized into
        `run.backend_profile`, `run.panel_config`, and `run.provider_config`. No new tables"* —
        so `M-ORCH` writes each key to its column without reshaping. A flat dict would have
        needed a mapping step, and a mapping step is a second place for the round trip to drift.

        `cost_ceiling` goes out as `str(Decimal)` and comes back through `Decimal(...)`, which is
        exact. `NFR-CONF-04` asks for a **byte-identical** round trip, and a float would lose it
        on the first two-decimal ceiling anybody sets.

        Credential-free **by construction**, not by redaction: no field of this type holds a
        secret, and the module never reads one (see `environment_snapshot`). There is nothing
        here to filter out, which is a stronger guarantee than filtering correctly.
        """
        return {
            "backend_profile": self.backend_profile,
            "panel_config": {
                "panel": [_ref_to_dict(ref) for ref in self.panel],
                "transcriber": _ref_to_dict(self.transcriber),
                "off_panel_checker": (
                    None if self.off_panel_checker is None else _ref_to_dict(self.off_panel_checker)
                ),
                "prompt_template_v": self.prompt_template_v,
                "panel_build_ref": self.panel_build_ref,
            },
            "provider_config": {
                "hardware_profile": self.hardware_profile,
                "concurrency_ceiling": self.concurrency_ceiling,
                "prefix_token_ceiling": self.prefix_token_ceiling,
                "cost_ceiling": None if self.cost_ceiling is None else str(self.cost_ceiling),
                "cost_currency": self.cost_currency,
                "retention_setting": self.retention_setting,
                # FR-CONF-17: present only when the engine is on, so an engine-off row is
                # byte-identical to its pre-delta form (NFR-SYS-14).
                **({} if self.decision_engine is None
                   else {"decision_engine": self.decision_engine.to_dict()}),
            },
        }
