"""The engine-off baseline for TC-REG-08 / TC-REG-09 (Jev test plan §4.3, TS-104, #457).

**The baseline must come from the old code.** A baseline produced by the new code with the
engine off proves nothing about "unchanged". So this module is written against only what
existed at `fb12d1e`, the last commit before any Jev delta code:
`tests.support.pipe_world.replay_world` / `drive_composed`, `aeh.prov.request_key`,
`aeh.orch.panel_config_json` / `Orchestrator.create_run`, `aeh.conf.compute_panel_build_ref` and
`RunConfig.profile_summary()` / `to_persisted_dict()`. Two callers use it:

- **Capture**, run inside a `git worktree` checked out at `fb12d1e`, with that tree first on
  `sys.path` and this file loaded by path. It writes `baselines/jev_engine_off.json`:

      git worktree add ../aeh-fb12d1e fb12d1e
      cd ../aeh-fb12d1e && PYTHONPATH=".;src" <repo>/.venv/Scripts/python \\
          <repo>/tests/regression/jev_engine_off_capture.py --out <repo>/tests/regression/baselines/jev_engine_off.json

- **The assertions** (`test_jev_engine_off_regression.py`), at HEAD with
  `HARNESS_DECISION_ENGINE=off`.

**Re-blessed at #516 (2026-09-28), consciously.** Extraction requests now carry the criterion
the run pinned (they carried an empty one before, design 1.9 §5.1 R4), so the 12 extraction
fixture keys moved. Every other value, the verdict rows included, is byte-identical to the
`fb12d1e` capture: the new file is the old one with those 12 keys replaced, checked by diff.

**Re-blessed at #616 (2026-10-06), consciously.** FR-CONF-30 records the resolved Q&A model on
every run's `to_persisted_dict()["provider_config"]` as `qa_model` (here `panel[0]`, the default
on both configs). Only the two `serialization.<name>.persisted` strings changed, each gaining that
one key; the run rows M-ORCH writes, the work ids, `panel_build_ref`, the profile summaries and
every table row are byte-identical, checked by diff. The Q&A model is not grader identity.

Every value in the snapshot is deterministic across drives (three captures at `fb12d1e` were
byte-identical). Two things are projected. Measured latency is dropped. A wall-clock stamp
(`*_at`) is reduced to whether it is set, because set-versus-null is behaviour and the instant
is not. Rows are sorted in Python on their projected content, so no column is trusted to order
them.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

#: The only configuration key the snapshot adds to the corpus's own. At `fb12d1e` the resolver
#: ignores this unknown top-level key (checked there); at HEAD it selects the engine-off path.
ENGINE_OFF = {"HARNESS_DECISION_ENGINE": "off"}

#: Measured, so different on every drive by construction.
_VOLATILE = frozenset({"latency_ms"})

#: The tables §4.3 names.
_TABLES = ("evidence", "verdict", "criterion_score", "submission_grade")


def _project(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if key in _VOLATILE:
            continue
        if key.endswith("_at"):
            out[f"{key}_is_set"] = value is not None
        else:
            out[key] = value
    return out


def _rows(handle: Any, table: str) -> list[dict[str, Any]]:
    columns = [r[1] for r in handle.query(f"PRAGMA table_info({table})")]
    rows = [_project(dict(zip(columns, tuple(r))))
            for r in handle.query(f"SELECT {', '.join(columns)} FROM {table}")]
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, default=str))


class _ConfirmingProvider:
    """Confirms zero retention for every ref, so the `cloud-hosted` run row can be written."""

    def verify_retention(self, refs: Any) -> Any:
        from aeh.prov import RetentionReport

        return RetentionReport(confirmed=tuple(refs), unconfirmed=())


def _run_row(world: Any, name: str, resolved: Any) -> dict[str, Any]:
    """The run row `create_run` writes for `resolved`, in the corpus's own store."""
    from aeh.orch import Orchestrator

    run_id = f"reg09-{name}"
    Orchestrator(world.store, provider=_ConfirmingProvider()).create_run(
        world.cohort_id, world.version, resolved, run_id=run_id)
    row = world.handle.query(
        "SELECT panel_config, provider_config, backend_profile FROM run WHERE run_id = :r",
        r=run_id)[0]
    return dict(zip(("panel_config", "provider_config", "backend_profile"), tuple(row)))


def _serialization(config: dict[str, Any], cohort: Any, world: Any = None,
                   name: str = "") -> dict[str, Any]:
    from aeh.conf import compute_panel_build_ref, resolve_run_config
    from aeh.orch import panel_config_json

    resolved = resolve_run_config(config, cohort)
    return {
        "run_row": _run_row(world, name, resolved) if world is not None else None,
        "panel_build_ref": compute_panel_build_ref(resolved.panel),
        "profile_summary": resolved.profile_summary().to_canonical_json(),
        "panel_config_json": panel_config_json(resolved.panel),
        "persisted": json.dumps(resolved.to_persisted_dict(), sort_keys=True, default=str),
    }


def serialization_configs() -> dict[str, dict[str, Any]]:
    """TC-REG-09's two fixed configurations: a 3-judge `cloud-hosted` one and an `edge-local`
    one, built from the repo's own builders plus `ENGINE_OFF`."""
    from aeh.conf import ModelRef
    from tests.support.conf_builders import edge_cfg, edge_panel, hosted_cfg

    cloud_panel = tuple(ModelRef(role="judge", provider="openrouter",
                                 build_id=f"openrouter/judge-{i}@2026-01-01", quantization=None)
                        for i in range(3))
    return {
        "cloud-hosted": {**hosted_cfg("cloud-hosted", panel=cloud_panel), **ENGINE_OFF},
        "edge-local": {**edge_cfg(panel=edge_panel(3)), **ENGINE_OFF},
    }


def snapshot(scratch: Path) -> dict[str, Any]:
    """Drive F-DEV-PIPE through `run_to_completion` with nothing recorded on the way and
    return §4.3's artifacts, plus TC-REG-09's serialization values and run rows."""
    import aeh.prov as prov
    from aeh.conf import CohortRef
    from tests.support import pipe_world

    hit: set[str] = set()
    original = prov.RecordedFixtureProvider.complete
    original_decide = getattr(prov.RecordedFixtureProvider, "decide", None)

    def spying(self: Any, prompt: Any, model_ref: Any, params: Any) -> Any:
        hit.add(prov.request_key(prompt, model_ref, params))
        return original(self, prompt, model_ref, params)

    def spying_decide(self: Any, request: Any, model_ref: Any) -> Any:
        # `decide` exists only after the delta. An engine-off run must never reach it, and a
        # key recorded here is a difference from the fb12d1e baseline, which has none.
        hit.add("decide:" + prov.decision_request_key(request, model_ref))
        return original_decide(self, request, model_ref)

    prov.RecordedFixtureProvider.complete = spying
    if original_decide is not None:
        prov.RecordedFixtureProvider.decide = spying_decide
    try:
        world = pipe_world.replay_world(scratch / "data")
        world.build_run()
        world.start_run()
        result = pipe_world.drive_composed(world)
    finally:
        prov.RecordedFixtureProvider.complete = original
        if original_decide is not None:
            prov.RecordedFixtureProvider.decide = original_decide
    try:
        handle = world.handle
        run = dict(zip(("panel_config", "provider_config", "backend_profile"), tuple(handle.query(
            "SELECT panel_config, provider_config, backend_profile FROM run WHERE run_id = :r",
            r=world.run_id)[0])))
        prescreen_table = handle.query(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'decision_prescreen'")
        cohort = CohortRef(cohort_id=world.cohort_id, consent_class="synthetic")
        out = {
            "status": result.status,
            # Detail lines are sorted: units complete concurrently, so their order is not part
            # of the behaviour; the set of lines is.
            "trace": [[s.stage, s.units, s.done, s.quarantined, sorted(s.detail)]
                      for s in result.stages],
            "work_ids": sorted(r[0] for r in handle.query("SELECT work_id FROM work_unit")),
            "run_row": run,
            "profile_summary": world.resolved.profile_summary().to_canonical_json(),
            "fixture_keys": sorted(hit),
            "tables": {table: _rows(handle, table) for table in _TABLES},
            # Absent at fb12d1e; at HEAD an engine-off run writes no pre-screen row.
            "decision_prescreen_rows": (
                handle.query("SELECT count(*) FROM decision_prescreen")[0][0] if prescreen_table else 0),
            "serialization": {name: _serialization(cfg, cohort, world, name)
                              for name, cfg in serialization_configs().items()},
        }
    finally:
        world.store.close()
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        data = snapshot(Path(tmp))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=1, sort_keys=True, default=str) + "\n",
                        encoding="utf-8", newline="\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
