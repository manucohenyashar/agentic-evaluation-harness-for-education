"""`TS-78` (issue #151) — `Requires` pairwise integration into **`M-CONF`**: every consumer's
assumption about the frozen run configuration, checked against the real `aeh.conf`.

Test plan §6.13: each row names a consumer, a provider and the clauses the consumer relies on. §6.11
asserts that `M-CONF` *keeps* its promises; these cases assert that each consumer's **actual usage**
matches the promise it cites. Grouped one suite per provider module (§4.10), at rung 2 or above
against the real provider, never a double.

| Case | Consumer | Assumption checked here |
|---|---|---|
| TC-REQ-01 | `M-PROV` | no configuration or environment read after construction |
| TC-REQ-07 | `M-INGEST` | no unresolved transcriber ref reaches the transcription path |
| TC-REQ-11 | `M-SETUP` | `prefix_token_ceiling` is frozen and read with no runtime lookup, before publication |
| TC-REQ-13 | `M-ORCH` | the run row the orchestrator persists rehydrates, and refuses a perturbed configuration |
| TC-REQ-63 | `M-STATS` | `panel_build_ref` is the same key on two processes |
| TC-REQ-74 | `M-CONFORM` | backend-varied configs are constructible and their build refs stable and comparable |
| TC-REQ-82 | `M-CONSOLE` | the displayed profile is the run's, and a sentinel credential never renders |

Markers: `contract` and `integration`, per §4.7's command for this tier
(`pytest -q -m "contract and integration"`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import aeh.conf as conf
from aeh.conf import (
    BackendMismatchError,
    ModelRef,
    UnresolvedModelRefError,
    compute_panel_build_ref,
    rehydrate_run_config,
    resolve_run_config,
)
from aeh.prov import (
    LocalServerProvider,
    OpenRouterProvider,
    PromptPayload,
    RecordedFixtureProvider,
    SamplingParams,
)
from tests.support.conf_builders import (
    EDGE_JUDGE,
    EDGE_TRANSCRIBER,
    SENTINEL_CREDENTIAL,
    SYNTHETIC_COHORT,
    edge_cfg,
    edge_panel,
    hosted_cfg,
    seed_credentials,
)
from tests.support.prov_contract import ScriptedTransport, completion, flat_ok

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[3]
_CONF_READS = ("resolve_run_config", "rehydrate_run_config", "environment_snapshot",
               "hardware_policy_for")


class _RecordingEnviron(dict):
    """`os.environ` stand-in that records every key read."""

    def __init__(self, source):
        super().__init__(source)
        self.reads: list[str] = []

    def get(self, key, default=None):
        self.reads.append(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.reads.append(key)
        return super().__getitem__(key)

    def __contains__(self, key):
        self.reads.append(key)
        return super().__contains__(key)


def _forbid_config_reads(monkeypatch) -> tuple[_RecordingEnviron, list[str]]:
    calls: list[str] = []
    for name in _CONF_READS:
        original = getattr(conf, name)

        def spy(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(conf, name, spy)
    environ = _RecordingEnviron(os.environ)
    monkeypatch.setattr(os, "environ", environ)
    return environ, calls


def test_tc_req_01_the_provider_reads_no_configuration_after_construction(tmp_path, monkeypatch):
    """`TC-REQ-01` (`M-PROV` → `M-CONF`, CT-CONF-02/03/04): each provider is constructed from a
    resolved config's `ModelRef`. From then on, a completion performs no configuration resolution
    and reads no environment variable."""
    config = resolve_run_config(edge_cfg(), SYNTHETIC_COHORT)
    ref = config.panel[0]
    assert ref.is_resolved(), "fixture: the resolved config must hand the provider a resolved ref"
    prompt = PromptPayload(fields=(("system", "score"), ("submission", "answer")))
    params = SamplingParams(temperature=0.0)

    fixture = RecordedFixtureProvider(fixture_dir=tmp_path)
    fixture.record(prompt, ref, params, completion())
    transport = ScriptedTransport(default=flat_ok(build=ref.build_id))
    live = (
        LocalServerProvider(base_url="http://local/v1", transport=transport),
        OpenRouterProvider(base_url="http://or/v1", api_key="not-a-credential",
                           transport=transport, retention_answers=lambda build: "yes"),
    )

    # Positive control: the recorder sees a read when one happens (construction reads the env).
    environ, _calls = _forbid_config_reads(monkeypatch)
    try:
        LocalServerProvider(transport=transport)
    finally:
        monkeypatch.undo()
    assert environ.reads, "control: the environment recorder saw no read during construction"

    problems = []
    for provider in (fixture, *live):
        environ, calls = _forbid_config_reads(monkeypatch)
        try:
            provider.complete(prompt, ref, params)
        finally:
            monkeypatch.undo()
        name = type(provider).__name__
        if calls:
            problems.append(f"{name}.complete re-resolved configuration mid-run: {calls}")
        if environ.reads:
            problems.append(f"{name}.complete read the environment after construction: "
                            f"{sorted(set(environ.reads))}")
    assert not problems, "\n".join(problems)


def test_tc_req_07_no_unresolved_transcriber_ref_reaches_the_transcription_path(tmp_data_dir):
    """`TC-REQ-07` (`M-INGEST` → `M-CONF`, CT-CONF-02/03): a floating transcriber tag is refused at
    resolution, so a transcriber ref reaches ingestion only resolved. A real `Ingestor` built from
    the resolved config transcribes with exactly that ref."""
    floating = ModelRef(role="transcriber", provider="ollama", build_id="whisper-large-v3:latest",
                        quantization="q4")
    with pytest.raises(UnresolvedModelRefError):
        resolve_run_config(edge_cfg(transcriber=floating), SYNTHETIC_COHORT)

    config = resolve_run_config(edge_cfg(), SYNTHETIC_COHORT)
    assert config.transcriber.is_resolved()

    from aeh.ingest import Ingestor, ResidencySlot
    from aeh.store import open_store
    from tests.support.setup_harness import (
        ASSESSMENT_MD,
        ScriptedIngestProvider,
        ScriptedRasterizer,
        ScriptedSanitizer,
    )

    seen: list[ModelRef] = []

    class _Recording(ScriptedIngestProvider):
        def complete(self, prompt, model_ref, params):
            seen.append(model_ref)
            return super().complete(prompt, model_ref, params)

    store = open_store(tmp_data_dir)
    try:
        ingestor = Ingestor(store.cohort("c-req-07"), store.blobs(), _Recording(ASSESSMENT_MD),
                            config.transcriber, SamplingParams(temperature=0.0),
                            ScriptedRasterizer(), residency=ResidencySlot.for_policy(("transcriber",)),
                            sanitizer=ScriptedSanitizer())
        source = store.blobs().put(b"assessment bytes")
        ingestor.ingest_document([source], kind="assessment", filenames={source: "a.pdf"})
    finally:
        store.close()
    assert seen, "fixture: ingestion made no transcription call"
    unresolved = [ref for ref in seen if not ref.is_resolved() or ref != config.transcriber]
    assert not unresolved, f"the transcription path received {unresolved}, not the resolved ref"


def test_tc_req_11_the_prefix_ceiling_is_frozen_and_read_without_a_runtime_lookup(monkeypatch):
    """`TC-REQ-11` (`M-SETUP` → `M-CONF`, CT-CONF-02): the resolved config carries the per-profile
    `prefix_token_ceiling` before any package exists. `M-SETUP`'s budget check reads that field and
    nothing else: no resolution, no environment. The value follows the profile (2000 on
    `unified-large`, 1500 on `unified-small`), and the field cannot be changed."""
    from aeh.setup import _prefix_ceiling

    large = resolve_run_config(edge_cfg(HARNESS_HARDWARE_PROFILE="unified-large"), SYNTHETIC_COHORT)
    small = resolve_run_config(edge_cfg(HARNESS_HARDWARE_PROFILE="unified-small"), SYNTHETIC_COHORT)
    with pytest.raises((TypeError, AttributeError)):
        large.prefix_token_ceiling = 99  # CT-CONF-04: frozen for the run's life

    environ, calls = _forbid_config_reads(monkeypatch)
    try:
        read = (_prefix_ceiling(large), _prefix_ceiling(small))
    finally:
        monkeypatch.undo()
    assert read == (large.prefix_token_ceiling, small.prefix_token_ceiling)
    assert read[0] != read[1], f"fixture: the two profiles must set different ceilings, got {read}"
    assert not calls and not environ.reads, (
        f"the budget check read configuration at runtime: {calls} {sorted(set(environ.reads))}")


def test_tc_req_13_the_persisted_run_rehydrates_and_refuses_a_perturbed_configuration(tmp_data_dir):
    """`TC-REQ-13` (`M-ORCH` → `M-CONF`, CT-CONF-02/04/06/14): the run row `M-ORCH` writes at
    `create_run` is what `rehydrate_run_config` reads on resume. It must reconstruct the config
    the run started with, and refuse a current configuration naming a different backend with
    `BackendMismatchError`, so a resumed run cannot silently change grader."""
    from aeh.store import open_store
    from tests.support.orch_run import ORCH_COHORT_ID, orch_cfg, seed_run

    started = orch_cfg("edge-local")
    store = open_store(tmp_data_dir)
    try:
        _orch, run_id, _version = seed_run(
            store, submissions=("S001",),
            criteria=({"criterion_id": "C01", "kind": "open", "scoring_model": "holistic"},),
            cfg=started)
        row = dict(store.cohort(ORCH_COHORT_ID).query(
            "SELECT * FROM run WHERE run_id = :r", r=run_id)[0])
    finally:
        store.close()
    for section in ("panel_config", "provider_config"):
        if isinstance(row.get(section), str):
            row[section] = json.loads(row[section])

    problems = []
    try:
        rehydrated = rehydrate_run_config(row)
    except Exception as error:  # the finding is the refusal itself
        problems.append(
            f"rehydrate_run_config cannot read the run row M-ORCH persisted: "
            f"{type(error).__name__}: {error}. [When written: M-ORCH writes panel_config as "
            f"{{'arms': [build ids]}} and provider_config without the refs' provider, "
            f"quantization or the transcriber, while CT-CONF-06 rehydrates from "
            f"RunConfig.to_persisted_dict()'s sections.]")
    else:
        if rehydrated != started:
            problems.append(f"the rehydrated config differs from the one the run started with: "
                            f"{rehydrated} != {started}")
        try:
            rehydrate_run_config(row, hosted_cfg("cloud-hosted"))
            problems.append("a resume against a cloud-hosted configuration did not raise")
        except BackendMismatchError:
            pass
    # The row's own form: a resume with a perturbed environment must refuse.
    from aeh.orch import Orchestrator

    store = open_store(tmp_data_dir)
    try:
        import os as _os

        perturbed = {"HARNESS_PROFILE": "cloud-hosted", "HARNESS_COST_CEILING": "12.50",
                     "HARNESS_COST_CURRENCY": "USD"}
        saved = {k: _os.environ.get(k) for k in perturbed}
        _os.environ.update(perturbed)
        try:
            Orchestrator(store).resume(run_id)
            problems.append("Orchestrator.resume ran against a cloud-hosted environment without "
                            "refusing: nothing on the resume path compares the frozen run with "
                            "current configuration (CT-CONF-06 is never called by M-ORCH)")
        except BackendMismatchError:
            pass
        finally:
            for k, v in saved.items():
                if v is None:
                    _os.environ.pop(k, None)
                else:
                    _os.environ[k] = v
    finally:
        store.close()
    assert not problems, "\n".join(problems)


_PBR_CHILD = """
import json, sys
from aeh.conf import ModelRef, compute_panel_build_ref
panel = [ModelRef(**raw) for raw in json.loads(sys.argv[1])]
print(compute_panel_build_ref(panel))
"""


def test_tc_req_63_panel_build_ref_is_the_same_key_on_two_processes():
    """`TC-REQ-63` (`M-STATS` → `M-CONF`, CT-CONF-07): the scope key `M-STATS` stores is the same
    string when computed in another process with a different hash seed, so a validation record
    means the same thing on two machines. A reordered panel is a different key."""
    panel = edge_panel(3)
    local = compute_panel_build_ref(panel)
    raw = json.dumps([{"role": r.role, "provider": r.provider, "build_id": r.build_id,
                       "quantization": r.quantization} for r in panel])
    remote = []
    for seed in ("0", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed,
                   PYTHONPATH=os.pathsep.join([str(REPO_ROOT / "src"), str(REPO_ROOT)]))
        out = subprocess.run([sys.executable, "-c", _PBR_CHILD, raw], capture_output=True,
                             text=True, env=env, timeout=60, check=True)
        remote.append(out.stdout.strip())
    assert remote == [local, local], f"panel_build_ref differs across processes: {local} {remote}"
    assert compute_panel_build_ref(tuple(reversed(panel))) != local


def test_tc_req_74_backend_varied_configs_are_constructible_and_their_refs_comparable():
    """`TC-REQ-74` (`M-CONFORM` → `M-CONF`, CT-CONF-05/07): the conformance method needs two
    `RunConfig`s over the same cohort and template that differ in backend. Both resolve. Each
    `panel_build_ref` is stable on re-resolution and compares with plain equality, and the two
    are distinct. Identical panel refs cannot be shared across backends: CT-CONF-03 requires
    weights builds on `edge-local` and provider-pinned builds on hosted profiles. So "differing
    only in backend" means the backend and the builds that backend serves."""
    edge_a = resolve_run_config(edge_cfg(), SYNTHETIC_COHORT)
    edge_b = resolve_run_config(edge_cfg(), SYNTHETIC_COHORT)
    hosted = resolve_run_config(hosted_cfg("dev-ci"), SYNTHETIC_COHORT)
    assert edge_a.backend_profile != hosted.backend_profile
    assert edge_a.prompt_template_v == hosted.prompt_template_v
    assert isinstance(edge_a.panel_build_ref, str) and isinstance(hosted.panel_build_ref, str)
    assert edge_a.panel_build_ref == edge_b.panel_build_ref
    assert edge_a.panel_build_ref != hosted.panel_build_ref
    assert edge_a.panel_build_ref == compute_panel_build_ref(edge_a.panel)
    with pytest.raises(UnresolvedModelRefError):
        resolve_run_config(hosted_cfg("dev-ci", panel=(EDGE_JUDGE,), transcriber=EDGE_TRANSCRIBER),
                           SYNTHETIC_COHORT)


def test_tc_req_82_the_console_renders_the_runs_profile_and_never_a_credential(
    tmp_data_dir, monkeypatch
):
    """`TC-REQ-82` (`M-CONSOLE` → `M-CONF`, CT-CONF-09/10, CT-CONSOLE-10): a run is started from a
    hosted configuration, with a sentinel credential in the environment and in `cfg`. Every
    console screen over that store must render no trace of the sentinel. The grade-bearing views'
    provenance must show the run's own backend profile, since that display is what CT-CONSOLE-10
    relies on `profile_summary()` to make safe."""
    from aeh.console import build_console
    from aeh.store import open_store
    from tests.support.orch_run import seed_run

    sentinel = seed_credentials(monkeypatch)
    cfg = hosted_cfg("cloud-hosted", OPENROUTER_API_KEY=sentinel, api_key=sentinel)
    config = resolve_run_config(cfg, SYNTHETIC_COHORT.__class__(
        cohort_id="c-2026-7B-orch", consent_class="synthetic"))
    assert sentinel not in config.profile_summary().to_canonical_json()

    store = open_store(tmp_data_dir)
    try:
        _orch, run_id, version = seed_run(
            store, submissions=("S001",),
            criteria=({"criterion_id": "C01", "kind": "open", "scoring_model": "holistic"},),
            cfg=config)
        app = build_console(store=store)
        pages = {screen: app.render(route, id=run_id, ref="S001", version=version).html
                 for screen, route in app.screens().items()}
    finally:
        store.close()

    problems = [f"{screen} renders the credential" for screen, html in pages.items()
                if SENTINEL_CREDENTIAL in html]
    provenance = [screen for screen, html in pages.items() if "backend profile" in html]
    if not provenance:
        problems.append("no screen renders a backend profile, so the credential check is vacuous")
    wrong = [screen for screen in provenance if "cloud-hosted" not in pages[screen]]
    if wrong:
        problems.append(
            f"{wrong} render a backend profile that is not this run's (cloud-hosted). "
            f"[When written: console.py renders a fixed GRADE_PROVENANCE footer, "
            f"'edge-local-q4', instead of the run's profile_summary().]")
    assert not problems, "\n".join(problems)
