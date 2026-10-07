"""`ConformanceSuite`: runs the fixture set through each backend and compares them."""

from __future__ import annotations

import dataclasses
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from harness.corpora import reference_package
from harness.corpora.pdf_writer import typed_document

from .constants import (
    _DECLARED_REFUSAL_MAX_DECOMPRESSED_BYTES,
    DIVERGENCE_DIMENSIONS,
    GATE_DIMENSIONS,
    _GATE_ORDER,
    INFORMATIONAL_DIMENSIONS,
    INGEST_COHORT,
    PIPELINE_STAGES,
    REQUESTED_BUILDS_FIELD,
    RESOLVED_BUILDS_FIELD,
    UNAVAILABLE_GATE_DIMENSION,
)
from .errors import ConformanceError, ConsentRefused
from .bands import _SUBSTITUTION_MARKER
from .fixtures import FixtureSet, FixtureSubmission, _materialize_bytes
from .reports import BackendResult, ConformanceReport, ValidationRecord
from .divergence import (
    _ACTIVE_INDUCED_DIMENSIONS,
    _derive_units,
    _dimension_divergence,
    _divergence_tolerance,
    _figures_for,
    _LADDER_OUTCOMES,
    _load_set_memo,
    _QUARANTINE_OUTCOMES,
    _source_bands,
)
from .backends import (
    _live_backend_profiles,
    _live_provider_for,
    _panel_build_ref,
    _promote_validation,
    recorded_provider_for_fixture_set,
    _requested_builds,
    _resolved_builds,
    _transcription_dispatch,
    _write_report_artifact,
)


@dataclasses.dataclass(frozen=True)
class IngestOutcome:
    """What ingesting one fixture did: the per-gate trace next to the status.

    `quarantined_at` names the FIRST gate that failed, in the ladder's order, as the gate's
    report key upper-cased (`V0`): the malicious-PDF clause (`FR-CONFORM-09`) is about the first
    gate, and a submission that failed V0 and was never scored is a different fact from one that
    failed V3. `None` means no gate failed.
    """

    submission_id: str
    ingest_status: str
    gates: Mapping[str, str]
    quarantined_at: str | None
    detail: Mapping[str, Any]


class ConformanceSuite:
    """The conformance suite (design §3.18): run the fixture set on every backend, compare the
    results, and access the fixtures.

    Built by `build_conformance_suite(provider=...)`. `provider` is the deterministic transport
    the transcription stage dispatches through (`CT-PROV-10`): the suite never opens a socket
    itself, and the fast tier passes a recorded or counting provider. `ingest_one` runs the real
    ingest pipeline over one fixture — the surface the malicious-PDF clause drives — and needs
    a provider for the same reason the pipeline does.
    """

    def __init__(self, provider: Any | None = None) -> None:
        self._provider = provider

    # -- CT-CONFORM-10: the consent boundary ------------------------------------------------------

    def _enforce_consent(self, backend_config: Mapping[str, Any], cohort: Any) -> None:
        """Leave the consent decision entirely to M-CONF (CT-CONFORM-10).

        `aeh.conf.consent_override_for` is the one implementation of the rule — this module
        calls it and reports the refusal under its own exception name. A second copy of the
        check here would drift from the first, and the one that drifts open is the one nobody
        is watching (RISK-10); the structural scan over this module asserts none of this file
        decides on a consent class.
        """
        from aeh.conf import ConsentGateError, consent_override_for

        try:
            consent_override_for(backend_config, cohort)
        except ConsentGateError as error:
            raise ConsentRefused(str(error)) from error

    def run(
        self,
        version: str,
        backend_configs: Sequence[Mapping[str, Any]],
        *,
        cohort: Any,
        tier: str | None = None,
    ) -> Any:
        """Run the same fixture set through the full pipeline on every backend.

        The consent gate is the surface and it is live: every backend config is checked against
        the cohort through `M-CONF` before anything else happens, and a cohort not so flagged is
        refused before a single fixture is read — sending unconsented work anywhere is the
        failure the gate exists to make impossible.

        What the run does, in the order the clauses ask for it (`CT-CONFORM-03`..`-07`,
        `-10`..`-14`): the identical set (`CT-CONFORM-01`'s one input hash) passes through the
        seven pipeline stages per backend — the ingest and transcription stages driven through
        the real ladder per fixture (`FR-CONFORM-04`'s no-stubs clause), the judgment stages on
        the declared references the recorded transport replays; the
        five §7.4 dimensions are measured per backend and compared — per dimension, never a
        headline (`CT-CONFORM-04`); the two named gates partition the dimensions — the live
        evidence-integrity gate blocks on crossing (`FR-CONFORM-07`), the score-distribution
        gate is always `unavailable` because no statistic is declared for it (`CT-CONFORM-14`),
        and the three informational dimensions are findings; every backend's figure set is
        recorded backend-scoped through `M-PKG` and promoted — never merged (`CT-CONFORM-06`);
        the report carries resolved next to requested builds and the per-dimension divergence
        (`CT-CONFORM-13`), and the run's own report artifact is the only write of its kind.
        """
        configs = list(backend_configs)
        if not configs:
            raise ConformanceError(
                "a conformance run needs at least one backend config; nothing was given"
            )
        if len(configs) > 2:
            raise ConformanceError(
                f"the differential compares TWO backends ({len(configs)} given): every "
                "backend between the outer pair would produce records and figures that never "
                "enter the divergence. Run the pairs you need as separate runs."
            )
        for backend_config in configs:
            self._enforce_consent(backend_config, cohort)

        fixture_set = _load_set_memo(version)
        bands_by_id = _source_bands()
        results: dict[str, BackendResult] = {}
        for backend_config in configs:
            profile = str(backend_config["HARNESS_PROFILE"])
            if profile in results:
                raise ConformanceError(
                    f"two backend configs declare the profile {profile!r}; a run compares "
                    "distinct backends, and a second config under the same profile would "
                    "overwrite the first's measurement"
                )
            results[profile] = _run_backend(self, fixture_set, backend_config, bands_by_id,
                                            cohort=cohort)

        divergence = _dimension_divergence(
            list(results.values()), frozenset(_ACTIVE_INDUCED_DIMENSIONS)
        )

        # The partition (`CT-CONFORM-05`/`-14`): exhaustive by construction, and the
        # score-distribution gate never passes — no statistic is declared for it, so no run may
        # report it green.
        tolerance = _divergence_tolerance()
        unavailable = (UNAVAILABLE_GATE_DIMENSION,)
        blocking = tuple(
            dimension
            for dimension in GATE_DIMENSIONS
            if dimension not in unavailable and divergence.dimensions[dimension] > tolerance
        )
        findings = {
            dimension: divergence.dimensions[dimension]
            for dimension in INFORMATIONAL_DIMENSIONS
            if divergence.dimensions[dimension] > tolerance
        }
        passing = tuple(
            dimension
            for dimension in DIVERGENCE_DIMENSIONS
            if dimension not in unavailable
            and dimension not in blocking
            and dimension not in findings
        )

        # Backend-scoped records (`CT-CONFORM-06`): one per backend, keyed on the catalog's
        # seven fields with the administration naming the backend profile the figures speak
        # for. The write goes into the package validation registry (`FR-CONFORM-05` — the
        # figures land where `aeh.pkg.validation_for` reads them back, not only on the report
        # object), and the durable half is the promotion through `M-PKG` (`CT-CONFORM-12`).
        from aeh import pkg as pkg_module

        records: list[ValidationRecord] = []
        for backend_config in configs:
            profile = str(backend_config["HARNESS_PROFILE"])
            result = results[profile]
            record = ValidationRecord(
                package_version=fixture_set.package_version or version,
                criterion="package",
                population_scope=getattr(cohort, "cohort_id", ""),
                backend_profile=profile,
                panel_build_ref=_panel_build_ref(backend_config),
                scoring_model=str(backend_config.get("prompt_template_v") or ""),
                administration=(
                    f"{getattr(cohort, 'cohort_id', '')}@{profile}:{fixture_set.version}"
                ),
                figure=dict(result.figures),
            )
            records.append(record)
            pkg_module.record_validation(
                package_version=record.package_version,
                population_scope=record.population_scope,
                criterion=record.criterion,
                backend_profile=record.backend_profile,
                panel_build_ref=record.panel_build_ref,
                scoring_model=record.scoring_model,
                administration=record.administration,
                figure=dict(record.figure),
            )
            _promote_validation(record)

        observability = {
            "per_dimension_divergence": dict(divergence.dimensions),
            "fixture_set_version": fixture_set.version,
            RESOLVED_BUILDS_FIELD: {
                str(config["HARNESS_PROFILE"]): _resolved_builds(config) for config in configs
            },
            REQUESTED_BUILDS_FIELD: {
                str(config["HARNESS_PROFILE"]): _requested_builds(config) for config in configs
            },
            "fixture_set_id": fixture_set.fixture_set_id,
        }

        first = next(iter(results.values()))
        report = ConformanceReport(
            per_backend=results,
            divergence=divergence,
            observability=observability,
            validation_records=tuple(records),
            input_set_hash=fixture_set.content_hash,
            package_version=fixture_set.package_version or version,
            build_changed_error_raised=False,
            blocked=bool(blocking),
            blocking_dimensions=blocking,
            findings=findings,
            unavailable_dimensions=unavailable,
            passing_dimensions=passing,
            completed=True,
            fixtures_scored=len(first.outcomes),
            tier=tier,
            consent_class=str(getattr(cohort, "consent_class", "") or ""),
        )
        # The run's own observability write — the one M-CONFORM-attributed write kind
        # `CT-CONFORM-12` permits (`_is_own_report_artifact` names the target shape).
        _write_report_artifact(report, fixture_set)
        return report

    def compare(self, a: Any, b: Any) -> Any:
        """Compare two backends dimension by dimension (design §3.18, CT-CONFORM-04).

        Takes two backends' results and returns the per-dimension divergence — five named
        dimensions, no headline. Induced dimensions active at the call drive their values, so
        the gate's blocking behaviour is drivable on the recorded transport (`CT-CONFORM-05`).
        """
        return _dimension_divergence([a, b], frozenset(_ACTIVE_INDUCED_DIMENSIONS))

    # -- the ingest seam ---------------------------------------------------------------------------

    def ingest_one(
        self,
        submission: FixtureSubmission,
        *,
        provider: Any | None = None,
        transcriber: Any | None = None,
    ) -> IngestOutcome:
        """Ingest one fixture through the real pipeline on a temporary store.

        The fixture's bytes are materialized (committed files for the file-backed corpora; the
        generator's output, digest-verified, for the malicious PDFs) and run through the landed
        M-INGEST gateway — real sanitizer, real rasterizer, the transcription stage dispatched
        through a provider. Nothing is stubbed in between, because `CT-CONFORM-03`'s clause
        *"no stubs for ingestion"* names exactly the seam this method is: a malicious PDF must
        quarantine at V0 having reached no model call, and that outcome is only meaningful if
        the gates it passed are the real ones.

        `provider`/`transcriber` override the dispatch for one call (a live-tier drive
        dispatches through the backend's own transport and transcriber ref); the default is
        the suite's injected provider and the fixture transcriber.

        The declared refusal world's knobs (the strip knob and the decompressed-bytes ceiling —
        see `docs/code-notes/conform.md`) are held for the ingest: the adversarial tier's contract
        is *quarantine*, and SEC-05's fork is the declared choice between stripping and
        refusing. The caller's values are restored afterwards.

        The package catalog is not wired (`ingest_submission`'s `package_catalog=None`): the
        ingest surface runs the integrity ladder's ingest-side gates; the conformance
        comparison's full pipelines are `run`'s, with #134.
        """
        dispatch_provider = provider if provider is not None else self._provider
        if dispatch_provider is None:
            raise ConformanceError(
                "ingest_one runs the real transcription stage, which dispatches through a "
                "provider (the deterministic transport): build the suite with "
                "build_conformance_suite(provider=...) before calling it"
            )
        source_bytes = _materialize_bytes(submission)
        if submission.source_corpus in {"F-FROZEN", "F-ADV-INJ"}:
            # The text fixtures are Markdown; the pipeline reads PDFs. They enter the way a
            # typed paper does when it is printed to PDF — one typed page per printed page,
            # rendered from the verified source text.
            text = source_bytes.decode("utf-8")
            source_bytes = typed_document(_markdown_pages(text))

        # The eleven-module migration chain (CLAUDE.md): the store's tiers are built by the
        # modules that own their migrations, and an open on a truncated chain refuses at the
        # open rather than failing at a distance. `aeh.grade` owns Cohort's last migration,
        # which is the one a short list misses.
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

        from aeh.conf import ModelRef
        from aeh.ingest import Ingestor, PdfiumRasterizer, PypdfSanitizer, ResidencySlot
        from aeh.prov import SamplingParams
        from aeh.store import open_store

        with tempfile.TemporaryDirectory(prefix="conform-ingest-") as raw_dir:
            store = open_store(Path(raw_dir))
            try:
                handle = store.cohort(INGEST_COHORT)
                # The ingest surface writes into the cohort it was handed; on an ephemeral store the row does
                # not exist yet, so create it the way the security suite's fixture surface does
                # (`tests/security/ingest/test_active_content.py`) — with the submission's
                # *declared* class rather than a literal, so the module spells no consent
                # vocabulary itself (`CT-CONFORM-10`: the gate is M-CONF's, not this module's).
                with handle.transaction() as tx:
                    tx.execute(
                        "INSERT OR IGNORE INTO cohort (cohort_id, consent_class, created_at) "
                        "VALUES (:c, :cc, 'x')",
                        c=INGEST_COHORT,
                        cc=submission.consent_class,
                    )
                blobs = store.blobs()
                blob_hash = blobs.put(source_bytes)
                ingestor = Ingestor(
                    handle,
                    blobs,
                    dispatch_provider,
                    (
                        transcriber
                        if transcriber is not None
                        else ModelRef(
                            role="transcriber", provider="local",
                            build_id="conform@fixture-transcriber", quantization="q4",
                        )
                    ),
                    SamplingParams(temperature=0.0),
                    PdfiumRasterizer(),
                    residency=ResidencySlot.for_policy(("transcriber",)),
                    sanitizer=PypdfSanitizer(),
                )
                report = _ingest_with_refusal_world(
                    ingestor, [blob_hash], f"{submission.submission_id}.pdf"
                )
            finally:
                store.close()

        return IngestOutcome(
            submission_id=submission.submission_id,
            ingest_status=report.ingest_status,
            gates=dict(report.gates),
            quarantined_at=_first_refused_gate(report.gates),
            detail=dict(report.detail),
        )


def _ingest_with_refusal_world(ingestor: Any, blob_hashes: Sequence[str], filename: str) -> Any:
    """Run the ingest with the refusal scenario's knobs set, restoring them afterwards.

    The adversarial tier's declared reading (SEC-05's other half): an active construct
    **quarantines** and reaches no model call, rather than being stripped and processed. Two
    knobs make that world, and both are M-INGEST's, read from the environment at sanitize
    time — the strip knob (`STRIP_ACTIVE_CONTENT_ENV`) and the decompressed-bytes ceiling
    (`MAX_DECOMPRESSED_BYTES_ENV`). The strip knob alone does not refuse the decompression
    bomb: it carries no active content, so at M-INGEST's 512 MiB production default it
    passes V0, is rasterized, and is transcribed — three model calls, quarantine at V1, the
    exact failure the first-pass review caught (see `docs/code-notes/conform.md`). The ceiling rides
    alongside at the value the declaration supports, and both are restored to whatever the
    caller had, so a run never leaks the refusal world into a pipeline that did not ask
    for it.
    """
    from aeh.ingest import MAX_DECOMPRESSED_BYTES_ENV, STRIP_ACTIVE_CONTENT_ENV

    declared_world = {
        STRIP_ACTIVE_CONTENT_ENV: "false",
        MAX_DECOMPRESSED_BYTES_ENV: str(_DECLARED_REFUSAL_MAX_DECOMPRESSED_BYTES),
    }
    previous = {name: os.environ.get(name) for name in declared_world}
    for name, value in declared_world.items():
        os.environ[name] = value
    try:
        return ingestor.ingest_submission(
            list(blob_hashes),
            cohort_id=INGEST_COHORT,
            package_version=reference_package.PACKAGE_VERSION,
            filenames={blob_hashes[0]: filename},
        )
    finally:
        for name, caller_value in previous.items():
            if caller_value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = caller_value


def _first_refused_gate(gates: Mapping[str, str]) -> str | None:
    """The first gate in the ladder whose value M-INGEST counts as a refusal (`V0` for a malicious
    PDF), or None when every gate passed. The failing values come from M-INGEST
    (`GATE_FAIL_VALUES`), not from a copy here."""
    from aeh.ingest import GATE_FAIL_VALUES

    for gate in _GATE_ORDER:
        if gates.get(gate) in GATE_FAIL_VALUES.get(gate, ()):
            return gate.upper()
    return None


def _markdown_pages(text: str) -> list[str]:
    """The printed pages of a Markdown fixture, split on the corpora's page markers.

    The marker line itself is dropped — the typed rendering re-prints each page's own header
    line ("Page N of M - id"), which is the assembly source the ingest ladder reads.
    """
    pages = [
        segment.strip("\n")
        for segment in re.split(r"^<!-- page: \d+ of \d+ -->\n?", text, flags=re.MULTILINE)
        if segment.strip("\n")
    ]
    return pages if pages else [text]


def build_conformance_suite(provider: Any | None = None) -> ConformanceSuite:
    """Build a conformance suite that runs from code, with the deterministic transport injected
    (CT-PROV-10).

    `provider=None` is legal and useful for the refusal half of the surface — the consent gate
    is checked before any provider could be touched, so `run` refuses unconsented work without
    one. A consented recorded run drives the ingest ladder through the suite's own provider,
    defaulting to the corpus's recorded provider when the suite was built without one;
    `ingest_one` called DIRECTLY still needs the provider and says so. A live-tier run
    (`HARNESS_CONFORM_LIVE_BACKENDS`) dispatches through the backends' own transports
    regardless of what the suite was built with.
    """
    return ConformanceSuite(provider=provider)


def _quarantined_pdf_outcome(submission: FixtureSubmission) -> IngestOutcome:
    """The real ingest ladder's verdict on one malicious PDF, cached per content digest.

    `run` drives `ingest_one` — the real sanitizer, rasterizer and gate ladder — for every
    fixture whose manifest declares a pdf threat. The outcome is provider-independent (the
    construct refuses at V0 with zero model calls), so one run per digest per process is the
    measurement; repeating it per backend would re-run the ladder to learn the same fact.
    """
    cached = _QUARANTINE_OUTCOMES.get(submission.content_hash)
    if cached is not None:
        return cached
    suite = ConformanceSuite(provider=recorded_provider_for_fixture_set("v1"))
    outcome = suite.ingest_one(submission)
    _QUARANTINE_OUTCOMES[submission.content_hash] = outcome
    return outcome


def _ladder_outcome(
    drive_suite: "ConformanceSuite",
    submission: FixtureSubmission,
    profile: str,
    *,
    transcriber: Any = None,
    memoize: bool,
) -> IngestOutcome:
    """The real ingest ladder's outcome for one text fixture on one backend, computed once.

    `ingest_one` IS the ingest stage's real machinery — sanitizer, rasterizer and the
    transcription dispatch through the drive suite's provider (`FR-CONFORM-04`'s no-stubs
    clause; the design prices full ingestion as affordable at 30-50 fixtures). The live
    drive passes the backend's own transcriber ref; the recorded drive uses the fixture
    transcriber. The recorded transport's ladder is deterministic — same bytes, same
    declared answers — so one drive per (content digest, backend) per process is the
    measurement, memoized the way the quarantine path is — and only for the default
    recorded drive. A live dispatch is the real transport and drives every time, because a
    memoized live outcome would be a recorded transcript wearing a live claim; a
    suite-injected provider drives every time too, because its dispatches are the caller's
    measurement, never the shared default's.
    """
    if not memoize:
        return drive_suite.ingest_one(submission, transcriber=transcriber)
    key = (submission.content_hash, profile)
    cached = _LADDER_OUTCOMES.get(key)
    if cached is None:
        cached = drive_suite.ingest_one(submission)
        _LADDER_OUTCOMES[key] = cached
    return cached


def _run_backend(
    self_suite: "ConformanceSuite",
    fixture_set: FixtureSet,
    backend_config: Mapping[str, Any],
    bands_by_id: Mapping[str, Mapping[str, str]],
    *,
    cohort: Any,
) -> BackendResult:
    """One backend's pass over the fixture set: check the fixtures, stage them, replay the
    judgments and prepare the figures for comparison."""
    started = time.perf_counter()
    profile = str(backend_config["HARNESS_PROFILE"])
    substituted = bool(backend_config.get(_SUBSTITUTION_MARKER))
    live = profile in _live_backend_profiles()
    # Computed inside the live branch, initialized here so the recorded tier carries None
    # without the branch having to say so.
    live_legs: Mapping[str, Any] | None = None
    if live:
        # The live tier dispatches the transcription stage through the backend's own
        # transport, with the backend's own transcriber ref — the dispatch field reports
        # the build that actually served.
        drive_suite = ConformanceSuite(provider=_live_provider_for(backend_config))
        transcriber = backend_config.get("transcriber")
        memoize = False
        live_legs = _live_arm_legs(backend_config, cohort)
    else:
        # The recorded transport: the suite's own injected provider drives the ladder (a
        # counting provider passed to the suite sees the dispatches), defaulting to the
        # recorded provider for the corpus when the suite was built without one — the
        # deterministic transport the fast tier's recorded run is (CT-PROV-10). The consent
        # gate has already run by the time a drive happens, so a default here never serves
        # unconsented work. Only the default recorded drive shares the ladder memo: an
        # injected provider is the caller's measurement instrument and must see every
        # dispatch itself.
        drive_suite = ConformanceSuite(
            provider=self_suite._provider or recorded_provider_for_fixture_set(fixture_set.version)
        )
        transcriber = None
        memoize = self_suite._provider is None
    stages_executed: dict[str, tuple[str, ...]] = {}
    ingest_outcomes: dict[str, IngestOutcome] = {}
    for submission in fixture_set.submissions:
        if submission.pdf_threat_kind is not None:
            # The real ladder, driven: quarantine at V0 with no model calls is a fact about
            # the real gates, never about a replay.
            ingest_outcomes[submission.submission_id] = _quarantined_pdf_outcome(submission)
            continue
        ingest_outcomes[submission.submission_id] = _ladder_outcome(
            drive_suite, submission, profile, transcriber=transcriber, memoize=memoize
        )
        stages_executed[submission.submission_id] = PIPELINE_STAGES
    units = _derive_units(fixture_set.submissions, bands_by_id, substituted=substituted)
    repeats = _derive_units(fixture_set.submissions, bands_by_id, substituted=substituted)
    return BackendResult(
        backend_profile=profile,
        input_set_hash=fixture_set.content_hash,
        stages_executed=stages_executed,
        transcription_dispatch=_transcription_dispatch(backend_config),
        figures=_figures_for(units, repeats),
        outcomes={sid: unit for sid, (_, unit) in units.items()},
        ingest_outcomes=ingest_outcomes,
        duration_seconds=time.perf_counter() - started,
        live_legs=live_legs,
    )


def _live_arm_legs(
    backend_config: Mapping[str, Any], cohort: Any,
) -> Mapping[str, Any] | None:
    """The re-specified TC-CONFORM-04 arm's per-leg figures, or None when there is no arm.

    A live backend on an OpenRouter profile whose config resolves the decision engine drives
    the full pipeline once (`aeh.conform.live_acceptance.live_backend_legs`) and carries the
    CT-CONFORM-17 per-leg keys beside its figures (TS-142, #618): the differential includes
    the decision leg, and the report shows it really ran. The engine-off backends — the
    `edge-local` profile, or a config that pins the engine off — carry None: the field's
    presence is not the claim, the legs' contents are.
    """
    from aeh.conf import resolve_run_config
    from aeh.conf import HOSTED_JEV_PROFILES

    from .live_acceptance import live_backend_legs

    profile = str(backend_config["HARNESS_PROFILE"])
    if profile not in HOSTED_JEV_PROFILES:
        return None
    run_config = resolve_run_config(dict(backend_config), cohort)
    if run_config.decision_engine is None:
        return None
    with tempfile.TemporaryDirectory(prefix="conform-live-arm-") as arm_dir:
        return live_backend_legs(run_config, cohort, Path(arm_dir))
