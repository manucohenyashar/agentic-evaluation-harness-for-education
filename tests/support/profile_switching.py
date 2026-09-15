"""Fixture F-PROFILES for `TS-103` (issue #397): one config file serving all three backend
profiles, selected by `HARNESS_PROFILE` (gap-fix test plan §5.9, design delta §3.15).

Two forms of the same fixture, because the cases stand at two isolation rungs:

* `f_profiles()` — the **parsed** mapping, with its model tables already `ModelRef`s. Rung 0
  (`TC-CONF-20`/`-21`) calls `select_profile_config`/`effective_config` on a mapping; how a file
  becomes one is the entry point's business, not these functions'.
* `f_profiles_toml()` — the file as an operator writes it, for the rung-3 cases that drive
  `python -m aeh ... --config FILE`.

**One disclosed deviation from the plan's fixture text.** §5.9 gives the `cloud-hosted` section
`retention_setting="zero"`; `aeh.conf.RETENTION_SETTINGS` is `('provider-default',
'zero-retention')`, so the fixture as written could never satisfy row 2's "resolves" whatever the
implementation did. The fixture uses the vocabulary's zero-retention value
(`default_retention_setting()`, the suite's one reading of it).
"""

from __future__ import annotations

import uuid
from typing import Any

from aeh.conf import HARNESS_KEYS, CohortRef, ModelRef, resolve_run_config
from aeh.orch import ORCH_LEASE_SECONDS, ORCH_STATEMENTS, Orchestrator
from tests.support.conf_builders import (
    EDGE_JUDGE,
    EDGE_TRANSCRIBER,
    HOSTED_JUDGE,
    HOSTED_TRANSCRIBER,
    default_retention_setting,
    hosted_cfg,
)
from tests.support.orch_run import (
    ORCH_COHORT_ID,
    RetentionConfirmingProvider,
    orch_cfg,
    seed_cohort,
    seed_package,
)

PROFILE_NAMES: tuple[str, ...] = ("edge-local", "cloud-hosted", "dev-ci")

SHARED_TEMPLATE = "p7"

FIXTURE_JUDGE = ModelRef(
    role="judge", provider="fixture", build_id="fixture/judge@2026-01-01", quantization=None
)
FIXTURE_TRANSCRIBER = ModelRef(
    role="transcriber",
    provider="fixture",
    build_id="fixture/transcriber@2026-01-01",
    quantization=None,
)


def f_profiles(top_level_profile: str | None = "edge-local", **shared: Any) -> dict[str, Any]:
    """F-PROFILES, parsed. `top_level_profile=None` omits the file's own `HARNESS_PROFILE`
    (the matrix's "absent"); `**shared` adds further shared top-level keys."""
    cfg: dict[str, Any] = {
        "prompt_template_v": SHARED_TEMPLATE,
        "profiles": {
            "edge-local": {
                "HARNESS_HARDWARE_PROFILE": "unified-small",
                "panel": (EDGE_JUDGE,),
                "transcriber": EDGE_TRANSCRIBER,
            },
            "cloud-hosted": {
                "HARNESS_COST_CEILING": 50,
                "HARNESS_COST_CURRENCY": "EUR",
                "retention_setting": default_retention_setting(),
                "panel": (HOSTED_JUDGE,),
                "transcriber": HOSTED_TRANSCRIBER,
            },
            "dev-ci": {
                "HARNESS_COST_CEILING": 5,
                "HARNESS_COST_CURRENCY": "USD",
                "panel": (FIXTURE_JUDGE,),
                "transcriber": FIXTURE_TRANSCRIBER,
            },
        },
    }
    if top_level_profile is not None:
        cfg["HARNESS_PROFILE"] = top_level_profile
    cfg.update(shared)
    return cfg


def _toml_ref(table: str, ref: ModelRef) -> str:
    lines = [table, f'role = "{ref.role}"', f'provider = "{ref.provider}"',
             f'build_id = "{ref.build_id}"']
    if ref.quantization is not None:
        lines.append(f'quantization = "{ref.quantization}"')
    return "\n".join(lines)


def f_profiles_toml(top_level_profile: str | None = "edge-local") -> str:
    """F-PROFILES as the TOML file an operator writes (model refs spelled as tables)."""
    head = [f'prompt_template_v = "{SHARED_TEMPLATE}"']
    if top_level_profile is not None:
        head.append(f'HARNESS_PROFILE = "{top_level_profile}"')
    parts = [
        "\n".join(head),
        '[profiles.edge-local]\nHARNESS_HARDWARE_PROFILE = "unified-small"',
        _toml_ref("[profiles.edge-local.transcriber]", EDGE_TRANSCRIBER),
        _toml_ref("[[profiles.edge-local.panel]]", EDGE_JUDGE),
        "[profiles.cloud-hosted]\nHARNESS_COST_CEILING = 50\nHARNESS_COST_CURRENCY = \"EUR\"\n"
        f'retention_setting = "{default_retention_setting()}"',
        _toml_ref("[profiles.cloud-hosted.transcriber]", HOSTED_TRANSCRIBER),
        _toml_ref("[[profiles.cloud-hosted.panel]]", HOSTED_JUDGE),
        '[profiles.dev-ci]\nHARNESS_COST_CEILING = 5\nHARNESS_COST_CURRENCY = "USD"',
        _toml_ref("[profiles.dev-ci.transcriber]", FIXTURE_TRANSCRIBER),
        _toml_ref("[[profiles.dev-ci.panel]]", FIXTURE_JUDGE),
    ]
    return "\n\n".join(parts) + "\n"


def clear_profile_environment(monkeypatch: Any) -> None:
    """Remove every key `effective_config` lifts, so the developer's own shell cannot select a
    profile a case did not ask for."""
    for key in (*HARNESS_KEYS, "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(key, raising=False)


def spy_conf(monkeypatch: Any, name: str, *modules: Any) -> list[tuple[tuple, dict, Any]]:
    """Wrap `aeh.conf.<name>` — and the name in any consumer module that imported it by value —
    recording `(args, kwargs, result)` per call, so a case can see both what a resolution was
    given and what it composed or resolved."""
    import aeh.conf

    real = getattr(aeh.conf, name)
    calls: list[tuple[tuple, dict, Any]] = []

    def spy(*args: Any, **kwargs: Any) -> Any:
        result = real(*args, **kwargs)
        calls.append((args, kwargs, result))
        return result

    monkeypatch.setattr(aeh.conf, name, spy)
    for module in modules:
        if hasattr(module, name):
            monkeypatch.setattr(module, name, spy)
    return calls


RA_PACKAGE = "pkg-profile-ra"
RB_PACKAGE = "pkg-profile-rb"
_SUBMISSIONS = ("SYN-001", "SYN-002")
_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},)


def seed_switched_runs(store: Any, clock: Any) -> dict[str, Any]:
    """`TC-CONF-22`'s world, over one real store:

    * **RA** — created under `edge-local`, started, paused, and carrying an **unapplied resume
      request** (a control row written while the orchestrator was down). That is a paused run a
      profile-blind `recover` *would* resume — `resume()`'s no-argument form applies queued
      control rows but never lifts a bare operator pause — so a case asserting RA stays paused
      fails against a `recover` that ignores `FR-CONF-15`, rather than passing vacuously;
    * **RB** — created under `cloud-hosted`, with one lease claimed and then expired on `clock`.

    Returns the two run ids, RA's persisted row as it stood after the pause, and RB's leased
    work ids. The caller switches the environment and calls `recover`.
    """
    seed_cohort(store, _SUBMISSIONS)
    ra_version = seed_package(store, _CRITERIA, package_id=RA_PACKAGE)
    rb_version = seed_package(store, _CRITERIA, package_id=RB_PACKAGE)

    edge = Orchestrator(store, clock=clock)
    ra = edge.create_run(ORCH_COHORT_ID, ra_version, orch_cfg("edge-local"))
    edge.start(ra)
    edge.pause(ra, "operator pause before the profile switch")
    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        tx.execute(
            ORCH_STATEMENTS["insert_run_control"],
            control_id=f"control-{uuid.uuid4().hex}",
            run_id=ra,
            action="resume",
            reason=None,
            requested_at=clock.now().isoformat(),
        )

    hosted = Orchestrator(store, clock=clock, provider=RetentionConfirmingProvider())
    rb_config = resolve_run_config(
        hosted_cfg(), CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic")
    )
    rb = hosted.create_run(ORCH_COHORT_ID, rb_version, rb_config)
    hosted.start(rb)
    leased = hosted.lease("worker-dead", "extract", 1)
    clock.advance(ORCH_LEASE_SECONDS + 1)

    handle = store.cohort(ORCH_COHORT_ID)
    ra_row = dict(handle.query("SELECT * FROM run WHERE run_id = :r", r=ra)[0])
    return {
        "ra": ra,
        "rb": rb,
        "ra_row": ra_row,
        "rb_leased": tuple(unit.work_id for unit in leased),
        "cohort_id": ORCH_COHORT_ID,
    }


def run_row(store: Any, cohort_id: str, run_id: str) -> dict[str, Any]:
    return dict(store.cohort(cohort_id).query("SELECT * FROM run WHERE run_id = :r", r=run_id)[0])


def leased_units(store: Any, cohort_id: str, run_id: str) -> list[Any]:
    return store.cohort(cohort_id).query(
        "SELECT work_id FROM work_unit WHERE run_id = :r AND status = 'leased'", r=run_id
    )


__all__ = [
    "RA_PACKAGE",
    "RB_PACKAGE",
    "leased_units",
    "run_row",
    "seed_switched_runs",
    "spy_conf",
    "FIXTURE_JUDGE",
    "FIXTURE_TRANSCRIBER",
    "PROFILE_NAMES",
    "SHARED_TEMPLATE",
    "clear_profile_environment",
    "f_profiles",
    "f_profiles_toml",
]
