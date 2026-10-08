"""The run's frozen panel and decision-engine records, and the run-start audit record."""

from __future__ import annotations

import json
import uuid
from typing import Any, Sequence

from .constants import MODEL_PIN_ROLES, MODEL_PINS_KEY, _JSON_SEPARATORS
from .errors import WorkLedgerError
from .statements import ORCH_STATEMENTS
from .settings import JUDGE_DECISION_TEMPLATE_V, _now
from .alerts import _mapping_get


def decision_engine_record(decision_engine: Any) -> dict[str, Any]:
    """The frozen decision engine as `panel_config` and `provider_config` store it (FR-ORCH-36/40):
    provider, build, the four gate values (in canonical form) and the render version."""
    from aeh.conf import _canonical_decimal

    return {
        "provider": decision_engine.model.provider,
        "build": decision_engine.model.build_id,
        "threshold": _canonical_decimal(decision_engine.confidence_threshold),
        "cite_threshold": _canonical_decimal(decision_engine.cite_threshold),
        "max_citation_questions": decision_engine.max_citation_questions,
        "token_bytes_ratio": decision_engine.token_bytes_ratio,
        "template": JUDGE_DECISION_TEMPLATE_V,
    }


def _pin_records(model_pins: "Mapping[str, Any] | None") -> dict[str, Any]:
    """The `model_pins` field a pinned run freezes into `provider_config` (FR-PIPE-19), or
    nothing — the key is absent entirely when no pin was given, so a pre-feature row
    round-trips byte-identically (`NFR-CONF-04`, the `decision_engine` pattern above).

    Each role's entry carries the ref's three identity fields (provider, build,
    quantization), so a caller can rebuild the exact `ModelRef` the run froze. A role
    outside `MODEL_PIN_ROLES` is refused before any write: a pin for a seat the pipeline
    does not drive would record an identity nothing honours.
    """
    if not model_pins:
        return {}
    unknown = sorted(str(role) for role in model_pins if role not in MODEL_PIN_ROLES)
    if unknown:
        raise WorkLedgerError(
            f"model_pins must key {MODEL_PIN_ROLES}, got {unknown}. A pin for a role no "
            "CLI flag or stage drives is not a pin this ledger can honour."
        )
    return {
        MODEL_PINS_KEY: {
            role: {
                "provider": ref.provider,
                "build_id": ref.build_id,
                "quantization": ref.quantization,
            }
            for role, ref in model_pins.items()
        },
    }


def panel_config_json(panel: Sequence[Any], *, decision_engine: Any = None) -> str:
    """The canonical `panel_config` string a run stores and hashes.

    `panel_config` is one of `FR-ORCH-01`'s nine inputs, so its serialization is part of
    the work-ID scheme and lives in exactly one place. The panel is serialized as a JSON
    array of the judges' build ids **in panel order** — order is semantic (it is the
    dispatch order and the escalation ladder's first arm), so sorting would merge distinct
    panels the way `CT-CONF-C07` forbids for `panel_build_ref`. `separators` and
    `sort_keys` are pinned so two code paths cannot serialize the same panel differently
    and silently fork the work-ID space.

    A judge here is identified by its **resolved build id** (`FR-CONF-03`: a build
    identity, never a friendly name) — the same string the unit's `judge_id` hash input
    carries, so a panel change and a judge change are both visible to the hash.
    """
    record: dict[str, Any] = {"arms": [ref.build_id for ref in panel]}
    if decision_engine is not None:
        # FR-ORCH-36: the engine joins the work identity only when present, so turning it on,
        # changing its build or any gate value mints new work ids, while an engine-off
        # `panel_config` stays byte-identical to its pre-delta form (CT-ORCH-30).
        record["decision_engine"] = decision_engine_record(decision_engine)
    return json.dumps(record, separators=_JSON_SEPARATORS, sort_keys=True)


def default_package_id_for(package_version_id: str) -> str:
    """The Tier P key a package version id is stored under, following the catalog's naming rule.

    `PackageCatalog.create_version` mints ``f"{package_id}@{uuid4().hex[:12]}"``, so the
    package id is everything before the **last** ``@``. Injectable on the orchestrator
    (`package_id_for`) so a deployment that names versions differently overrides this
    rather than bending the orchestrator to a guess — and so a test can pin the whole
    resolution without a real Tier P file.
    """
    package_id, _, _ = package_version_id.rpartition("@")
    if not package_id:
        raise WorkLedgerError(
            f"package version id {package_version_id!r} carries no '@<suffix>' portion, "
            "so it does not match the catalog's minted '<package_id>@<suffix>' form and "
            "its Tier P database cannot be resolved. Pass package_id_for explicitly if "
            "this deployment names versions differently."
        )
    return package_id


# --- the audit record (TC-CONF-17's producer) ---------------------------------------------------


def _persisted_run_config(cfg: Any) -> str | None:
    """The run's frozen `RunConfig` serialized by `to_persisted_dict()` (CT-CONF-06), or None for a
    test double without one."""
    persisted = getattr(cfg, "to_persisted_dict", None)
    if not callable(persisted):
        return None
    return json.dumps(persisted(), sort_keys=True, default=str, separators=_JSON_SEPARATORS)


def _refuse_profile_switch(row: Any) -> None:
    """Refuse to resume a run under a different `HARNESS_PROFILE` than the one it froze, raising
    `BackendMismatchError` naming both (FR-CONF-15, FR-ORCH-16, #527). With no profile set, the run
    resumes on its own frozen backend."""
    from aeh.conf import BackendMismatchError, effective_config

    current = effective_config({}).get("HARNESS_PROFILE")
    frozen = _mapping_get(row, "backend_profile")
    if current and frozen and str(current) != str(frozen):
        raise BackendMismatchError(
            f"run {row['run_id']} froze backend_profile {frozen!r} and the current "
            f"configuration names {current!r}: a resumed run keeps its own backend, so it is "
            "not resumed under another (FR-CONF-15, FR-ORCH-16)")


def _panel_build_ref_of(row: Any) -> str:
    """The run's frozen `panel_build_ref`, from its saved provider config."""
    try:
        config = json.loads(_mapping_get(row, "provider_config") or "{}")
    except (TypeError, ValueError):
        return ""
    return str(config.get("panel_build_ref") or "") if isinstance(config, dict) else ""


def _model_pin_records_of(
    row: Any,
) -> tuple[tuple[str, str, str, "str | None"], ...]:
    """The run's recorded model pins (`FR-PIPE-19`), from its saved provider config.

    One tuple per pinned role, in role order — `(role, provider, build_id, quantization)`
    — so a caller can compare a fresh flag against what the run froze, or rebuild the
    `ModelRef` a run keeps, without touching the JSON itself (`CT-PIPE-05`: M-PIPE
    executes no SQL, and the persisted-config schema is M-ORCH's to read). `()` for a row
    with no `model_pins` key: pre-feature rows carry none, and the absence is the honest
    answer — an unpinned run has no pin to keep or compare against.
    """
    try:
        config = json.loads(_mapping_get(row, "provider_config") or "{}")
    except (TypeError, ValueError):
        return ()
    if not isinstance(config, dict):
        return ()
    raw = config.get(MODEL_PINS_KEY)
    if not isinstance(raw, dict):
        return ()
    records: list[tuple[str, str, str, "str | None"]] = []
    for role in MODEL_PIN_ROLES:
        entry = raw.get(role)
        if not isinstance(entry, dict):
            continue
        records.append((
            role,
            str(entry.get("provider") or ""),
            str(entry.get("build_id") or ""),
            entry.get("quantization"),
        ))
    return tuple(records)


def record_run_start(
    store: Any, config: Any, *, run_id: str | None = None, summary: Any = None,
    recorded_at: str | None = None,
) -> str:
    """Write the run-start audit record: what configuration graded this run.

    **Invented here** — the name appears in no Interfaces block (checked: zero occurrences
    in either design document), which is exactly why it is this module's to define: the
    store keeps the row, the orchestrator owns what it means.

    The stored summary is `config.profile_summary().to_canonical_json()` — the **same
    serializer** `log_run_start` puts on the log line, which is what makes TC-CONF-17's
    differential ("the stored profile_summary is byte-identical to the one logged at run
    start") a property of the code rather than a hope. Reaching for `json.dumps(asdict(...))`
    here is the defect that case exists to catch.

    `run_id` is minted when the caller has none (an audit row's id needs uniqueness, not
    determinism); `create_run` passes the run's own id so the record names the run it
    belongs to. Returns the run id written.

    `summary` is the `ProfileSummary` `log_run_start` returned, when the caller logged the
    run start (`Orchestrator.create_run` does): storing that object rather than computing a
    second one makes the stored record literally the logged one. Omitted, the summary is
    computed here, as the repair path in `create_run`'s docstring needs.

    `recorded_at` is the orchestrator's wall time (FR-ORCH-44) when `create_run` calls this;
    omitted, the process wall clock stamps the row.
    """
    if summary is None:
        summary = config.profile_summary()
    resolved_run_id = run_id if run_id is not None else f"run-{uuid.uuid4().hex}"
    durable = store.durable()
    with durable.transaction() as tx:
        tx.execute(
            ORCH_STATEMENTS["insert_audit_record"],
            audit_record_id=uuid.uuid4().hex,
            run_id=resolved_run_id,
            recorded_at=recorded_at if recorded_at is not None else _now(),
            profile_summary=summary.to_canonical_json(),
        )
    return resolved_run_id
