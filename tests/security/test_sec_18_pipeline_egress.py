"""SEC-18 (CT-PIPE-06, CT-PROV-15; TS-99 #393): M-PIPE opens no network path of its own.

| Arm | Oracle |
|---|---|
| static | `aeh/pipeline.py` imports none of `http`, `urllib`, `socket`, `litellm`, `requests`, `httpx`, `aiohttp`, `openai`, `anthropic` |
| run | a whole F-DEV-PIPE run through `run_to_completion`, under the suite's socket guard, makes zero outbound attempts |

Disclosed: the plan runs the dynamic arm as TC-SMOKE-12 (`python -m aeh run` in a subprocess). That
case is blocked: the CLI derives its extractor and synthesizer identities from the run config
(`RunConfig` has no field for either, M-PIPE's recorded gap 2), so it cannot replay a corpus
recorded under the corpus's own identities (#378). The composed run here is the same code path
below the argument parsing, under the in-process guard that sees every socket call.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.support import pipe_world
from tests.support.source_tree import module_source

REPO = Path(__file__).resolve().parents[2]
FORBIDDEN = {"http", "urllib", "socket", "litellm", "requests", "httpx", "aiohttp", "openai", "anthropic"}


def test_sec_18_static_the_composition_layer_imports_no_network_client():
    tree = ast.parse(module_source("pipeline", REPO / "src" / "aeh"))
    roots = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    roots |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not roots & FORBIDDEN, sorted(roots & FORBIDDEN)


@pytest.mark.integration
def test_sec_18_run_a_composed_run_makes_no_outbound_attempt(tmp_path, monkeypatch, network_guard):
    monkeypatch.setenv("HARNESS_PROFILE", "edge-local")
    world = pipe_world.replay_world(tmp_path / "w", monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    try:
        assert pipe_world.drive_composed(world).status == "complete"
    finally:
        world.store.close()
    network_guard.assert_no_network()
