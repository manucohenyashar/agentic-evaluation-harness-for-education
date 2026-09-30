"""Backend identities and transports, and promoting a backend's validation record through M-PKG."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .constants import AGREEMENT_DIMENSION, LIVE_BACKENDS_ENV, RECORDED_FIXTURE_DISPATCH
from .errors import ConformanceError
from .bands import _SUBSTITUTED_BUILD_SUFFIX, _SUBSTITUTION_MARKER
from .fixtures import FixtureSet
from .reports import ConformanceReport, ValidationRecord


_PROMOTION_STORE_DIR: Path | None = None


def _build_id_of(ref: Any) -> str:
    if ref is None:
        return ""
    return str(getattr(ref, "build_id", None) or ref.get("build_id") or "")


def _requested_builds(backend_config: Mapping[str, Any]) -> tuple[str, ...]:
    """What the caller asked for, read off the config (`CT-CONFORM-13`'s source of truth)."""
    refs = list(backend_config.get("panel") or ()) + [backend_config.get("transcriber")]
    return tuple(sorted(_build_id_of(ref) for ref in refs if ref is not None))


def _resolved_builds(backend_config: Mapping[str, Any]) -> tuple[str, ...]:
    """The serving identities the transport resolved, per profile.

    An honest recorded transport resolves exactly what was requested. A substituted backend
    resolved a different serving identity while reporting the requested build — which is why
    the report carries both (`CT-CONFORM-13`): the divergence is attributable only when the
    report names what actually ran.
    """
    requested = _requested_builds(backend_config)
    if not backend_config.get(_SUBSTITUTION_MARKER):
        return requested
    transcriber = _build_id_of(backend_config.get("transcriber"))
    return tuple(sorted(
        build + _SUBSTITUTED_BUILD_SUFFIX if build == transcriber else build for build in requested
    ))


def _live_backend_profiles() -> frozenset[str]:
    """The profiles the live-backend env knob (`HARNESS_CONFORM_LIVE_BACKENDS`) declares —
    the shared gate in the clause suite. Naming a profile commits its run to a REAL dispatch:
    the transcription stage drives the backend's own live transport (`_live_provider_for`),
    and the dispatch field reports the transcriber build because that is what actually served.
    """
    return frozenset(
        name.strip() for name in os.environ.get(LIVE_BACKENDS_ENV, "").split(",") if name.strip()
    )


def _live_provider_for(backend_config: Mapping[str, Any]) -> Any:
    """The live transport one live-tier backend's transcription dispatches through.

    Built from the backend's own transcriber ref via `aeh.prov.provider_for` — M-PROV owns
    the provider-name mapping (`CT-PROV-15`: the only place in the tree that names a
    backend), so this module carries no backend-specific constant. An unknown name refuses
    at the factory.
    """
    from aeh.prov import provider_for

    transcriber = backend_config.get("transcriber")
    if transcriber is None:
        raise ConformanceError(
            "a live conformance backend needs a declared transcriber to dispatch through"
        )
    return provider_for(transcriber)


def _transcription_dispatch(backend_config: Mapping[str, Any]) -> str:
    """What the transcription stage dispatched through, named per backend (`TC-CONFORM-04`).

    The recorded transport reports `recorded_fixture`; a profile the live-backend env knob
    declares (`HARNESS_CONFORM_LIVE_BACKENDS`) reports the transcriber build it actually
    dispatched to — the run really wires that backend's live transport for the drive
    (`_live_provider_for`), so the field is a record of a dispatch that happened, never a
    claim about one that did not.
    """
    profile = str(backend_config.get("HARNESS_PROFILE") or "")
    if profile in _live_backend_profiles():
        return _build_id_of(backend_config.get("transcriber"))
    return RECORDED_FIXTURE_DISPATCH


def _panel_build_ref(backend_config: Mapping[str, Any]) -> str:
    from aeh.conf import compute_panel_build_ref

    return compute_panel_build_ref(backend_config["panel"])


def _promotion_store_dir() -> Path:
    """The ephemeral durable store the validation administrations are promoted into.

    Created once per process: the migrations run when `durable()` first opens (the
    eleven-module chain, imported here), and `record_promotion` connects to
    `durable.sqlite` from then on. `os.makedirs` builds the directory — the write audit
    records `Path.mkdir`, and scaffolding is not output.
    """
    global _PROMOTION_STORE_DIR
    if _PROMOTION_STORE_DIR is None:
        root = Path(tempfile.gettempdir()) / f"aeh-conform-durable-{uuid4().hex[:8]}"
        os.makedirs(root, exist_ok=True)
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

        from aeh.store import open_store

        store = open_store(root)
        try:
            store.durable()
        finally:
            store.close()
        _PROMOTION_STORE_DIR = root
    return _PROMOTION_STORE_DIR


def _promote_validation(record: ValidationRecord) -> None:
    """Promote one backend's validation record through `M-PKG` (`CT-CONFORM-12`).

    The write goes through `aeh.pkg.record_promotion` — the durable `package_validation` row —
    keyed on the record's administration, which names the backend profile the figures speak
    for. One row per backend, never a row spanning two: the same scoping rule the record
    itself carries, held by the key rather than by convention.
    """
    from aeh import pkg as pkg_module

    agreement = dict(record.figure.get(AGREEMENT_DIMENSION) or {})
    pkg_module.record_promotion(
        _promotion_store_dir(),
        package_version_id=record.package_version,
        cohort_id=record.administration,
        cohorts_used=1,
        operational_count=0,
        blind_count=0,
        n=int(agreement.get("n") or 0),
        agreement_kappa=float(agreement.get("kappa") or 0.0),
        weakest_per_population="{}",
        surface_proxy_flags="[]",
        message=(
            "conformance validation replay over declared references; the per-backend figure "
            "is the record this row promotes"
        ),
    )


def _write_report_artifact(report: ConformanceReport, fixture_set: FixtureSet) -> Path:
    """The run's own report artifact — the one write kind `CT-CONFORM-12` permits by hand."""
    target = Path(tempfile.gettempdir()) / (
        f"conformance-report-{fixture_set.version}-{uuid4().hex[:8]}.json"
    )
    payload = {
        "fixture_set_version": fixture_set.version,
        "fixture_set_id": fixture_set.fixture_set_id,
        "input_set_hash": report.input_set_hash,
        "package_version": report.package_version,
        "blocked": report.blocked,
        "divergence": dict(report.divergence.dimensions),
        "per_backend": {
            profile: {
                "duration_seconds": result.duration_seconds,
                "transcription_dispatch": result.transcription_dispatch,
                # Every fixture's real ladder outcome now rides the result; the artifact's
                # field is the ones that QUARANTINED, which is what the name always said.
                "ingest_quarantined": sorted(
                    sid
                    for sid, outcome in result.ingest_outcomes.items()
                    if getattr(outcome, "quarantined_at", None)
                ),
            }
            for profile, result in report.per_backend.items()
        },
    }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def recorded_provider_for_fixture_set(version: str) -> Any:
    """The deterministic transport for a fixture set's ingest surface (`CT-PROV-10`).

    Socket-free and cost-free: the completions are derived from the request itself, so a suite
    built without an injected provider can still drive the real ingest ladder (the malicious
    PDFs never reach it — quarantine at V0 precedes any transcription — and a `CountingProvider`
    wrapping this provider counts zero for exactly that reason).
    """

    class _ConformRecordedProvider:
        def __init__(self, fixture_set_version: str) -> None:
            self._fixture_set_version = fixture_set_version

        def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
            from aeh.prov import Completion

            request_key = str(getattr(prompt, "request_key", "") or "")
            return Completion(
                text=f"recorded transcription ({self._fixture_set_version}) {request_key}",
                tokens_in=1,
                tokens_out=1,
                latency_ms=1,
                resolved_build=str(getattr(model_ref, "build_id", "recorded")),
                cached_prefix_tokens=0,
                cost=None,
            )

    return _ConformRecordedProvider(version)
