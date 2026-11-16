"""`TC-CONF-48` — `served_as` on a local model block (FR-CONF-40, CT-CONF-27, CT-CONF-07; RSV-30).

Statistical-validity test plan r2 §3.22, story T21 (issue #905); implemented by S28 (#871).
Rung 0: config files parsed from TOML text, `resolve_run_config`, the frozen run config's JSON.

ADR-61: `served_as` is an **address**, `build_id` is the **identity**. So the oracle has two
halves that pull in opposite directions, and a test of only one of them would pass an
implementation that gets the other wrong:

* the address must be *carried*: required on an `edge-local` local block (refused, naming the
  block, with the fix), written into the frozen run config and rehydrated on resume;
* the address must *not* be identity: two configs differing only in `served_as` hash to the same
  `panel_build_ref` (CT-CONF-07 unchanged), and a resume under a renamed served model is the same
  grader.

`ModelRef.served_as` is `compare=False`, so `ModelRef` equality cannot see a dropped address.
Every carriage assertion here reads `.served_as` explicitly for that reason.
"""

from __future__ import annotations

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aeh.conf import (
    ConfigurationError,
    ModelRef,
    parse_config_document,
    rehydrate_run_config,
    resolve_run_config,
)
from aeh.conf.panel import compute_panel_build_ref
from aeh.orch.run_records import _persisted_run_config
from tests.support.conf_builders import SYNTHETIC_COHORT, default_retention_setting, edge_cfg

pytestmark = pytest.mark.contract

_HASH = "0" * 64
_JUDGE_A = f"/models/qwen3-30b-a3b-q4.gguf@sha256:{_HASH}"
_JUDGE_B = f"/models/mistral-small-24b-q4.gguf@sha256:{'1' * 64}"
_JUDGE_C = f"/models/gemma-3-27b-q4.gguf@sha256:{'5' * 64}"
_READER = f"/models/qwen3-vl-8b-instruct-q4.gguf@sha256:{'2' * 64}"


def _block(header: str, role: str, provider: str, build_id: str, quantization: str | None,
           served_as: str | None) -> str:
    lines = [header, f'role = "{role}"', f'provider = "{provider}"', f'build_id = "{build_id}"']
    if quantization is not None:
        lines.append(f'quantization = "{quantization}"')
    if served_as is not None:
        lines.append(f'served_as = "{served_as}"')
    return "\n".join(lines)


def _edge_file(*, judge_a: str | None = "qwen3:30b-a3b-q4_K_M",
               judge_b: str | None = "mistral-small:24b-q4_K_M",
               judge_c: str | None = "gemma3:27b-it-q4_K_M",
               reader: str | None = "qwen3-vl:8b-instruct-q4_K_M",
               judge_b_provider: str = "ollama") -> str:
    """An `edge-local` config file: three local judges and a local page reader."""
    return "\n\n".join([
        'HARNESS_PROFILE = "edge-local"\n'
        'HARNESS_HARDWARE_PROFILE = "unified-large"\n'
        'HARNESS_DECISION_ENGINE = "off"\n'
        'prompt_template_v = "conf-v1.0.0"',
        _block("[transcriber]", "transcriber", "local", _READER, "q4", reader),
        _block("[[panel]]", "judge", "local", _JUDGE_A, "q4", judge_a),
        _block("[[panel]]", "judge", judge_b_provider, _JUDGE_B, "q4", judge_b),
        _block("[[panel]]", "judge", "vllm-mlx", _JUDGE_C, "q8", judge_c),
    ]) + "\n"


def _resolve(text: str):
    return resolve_run_config(parse_config_document(text, "toml"), SYNTHETIC_COHORT)


# --- the parse table ------------------------------------------------------------------------


def test_tc_conf_48_a_local_block_with_served_as_is_accepted_and_carries_it():
    config = _resolve(_edge_file())
    assert [ref.served_as for ref in config.panel] == [
        "qwen3:30b-a3b-q4_K_M", "mistral-small:24b-q4_K_M", "gemma3:27b-it-q4_K_M"]
    assert config.transcriber.served_as == "qwen3-vl:8b-instruct-q4_K_M"
    # The identity is untouched by the address (ADR-61).
    assert [ref.build_id for ref in config.panel] == [_JUDGE_A, _JUDGE_B, _JUDGE_C]


@pytest.mark.parametrize("missing, block", [
    ({"judge_a": None}, "panel[0]"),
    ({"judge_b": None}, "panel[1]"),
    ({"judge_b": None, "judge_b_provider": "vllm-mlx"}, "panel[1]"),
    ({"judge_c": None}, "panel[2]"),
    ({"reader": None}, "transcriber"),
], ids=["panel0-local", "panel1-ollama", "panel1-vllm-mlx", "panel2-vllm-mlx", "transcriber"])
def test_tc_conf_48_a_local_block_without_served_as_is_refused_naming_it_and_the_fix(
        missing, block):
    with pytest.raises(ConfigurationError) as caught:
        _resolve(_edge_file(**missing))
    text = str(caught.value)
    assert text.startswith(f"{block} names a local model but not the name the server serves "
                           "it under"), text
    assert 'add served_as = "' in text, f"TC-CONF-48: the fix sentence is missing: {text}"
    # The build id is not echoed (NFR-CONF-02): the refusal names the block, not the weights.
    assert ".gguf" not in text and "sha256" not in text, text


def _hosted_file(served_as: str | None) -> str:
    return "\n\n".join([
        'HARNESS_PROFILE = "dev-ci"\n'
        'HARNESS_COST_CEILING = "12.50"\n'
        'HARNESS_COST_CURRENCY = "USD"\n'
        'HARNESS_DECISION_ENGINE = "off"\n'
        f'retention_setting = "{default_retention_setting()}"\n'
        'prompt_template_v = "conf-v1.0.0"',
        _block("[transcriber]", "transcriber", "openrouter",
               "openrouter/qwen/qwen3-vl-8b-instruct@2026-06-01", None, None),
        _block("[[panel]]", "judge", "openrouter",
               "openrouter/qwen/qwen3-30b-a3b@2026-06-01", None, served_as),
    ]) + "\n"


def test_tc_conf_48_an_openrouter_block_with_served_as_is_accepted_and_ignored():
    """Accepted: the hosted start does not refuse it. Ignored: it changes neither the identity
    hash nor what OpenRouter is sent (the plain slug, never the address)."""
    from tests.unit.prov.test_openrouter_wire_shape import (
        PARAMS, _openrouter, _openrouter_ok, _payload, _Transport)

    with_address = _resolve(_hosted_file("some-local-name:7b"))
    without = _resolve(_hosted_file(None))
    assert with_address.panel_build_ref == without.panel_build_ref

    transport = _Transport(_openrouter_ok())
    _openrouter(transport).complete(_payload(), with_address.panel[0], PARAMS)
    (body,) = transport.bodies()
    assert body["model"] == "qwen/qwen3-30b-a3b"
    assert "some-local-name" not in json.dumps(body)


# --- hash equality (CT-CONF-07 unchanged) ---------------------------------------------------


def test_tc_conf_48_configs_differing_only_in_served_as_give_equal_panel_build_ref():
    one = _resolve(_edge_file())
    other = _resolve(_edge_file(judge_a="renamed:latest-tag", judge_b="another-name",
                                  judge_c="third-name"))
    assert one.panel_build_ref == other.panel_build_ref
    # Control: the hash does see identity — a changed build is a different panel.
    changed = _resolve(_edge_file().replace(_JUDGE_B, f"/models/other.gguf@sha256:{'3' * 64}"))
    assert changed.panel_build_ref != one.panel_build_ref


_NAMES = st.one_of(
    st.none(),
    st.text(alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E), min_size=1,
            max_size=24),
)


@pytest.mark.property
@settings(max_examples=60, deadline=None)
@given(first=st.lists(_NAMES, min_size=3, max_size=3),
       second=st.lists(_NAMES, min_size=3, max_size=3))
def test_tc_conf_48_property_served_as_never_enters_panel_build_ref(first, second):
    """For any two panels equal in every identity field and differing arbitrarily in
    `served_as` (including present vs absent), `panel_build_ref` is equal."""
    builds = (_JUDGE_A, _JUDGE_B, f"/models/third.gguf@sha256:{'4' * 64}")

    def panel(names):
        return tuple(ModelRef("judge", "ollama", build, "q4", served_as=name)
                     for build, name in zip(builds, names))

    assert compute_panel_build_ref(panel(first)) == compute_panel_build_ref(panel(second))


# --- the frozen run config and resume -------------------------------------------------------


def test_tc_conf_48_served_as_round_trips_the_frozen_run_config_and_rehydrates_on_resume():
    started = _resolve(_edge_file())
    # The exact text M-ORCH writes into `run.run_config` (migration 31).
    frozen_text = _persisted_run_config(started)
    assert "qwen3:30b-a3b-q4_K_M" in frozen_text

    restored = rehydrate_run_config({"run_config": frozen_text})
    assert [ref.served_as for ref in restored.panel] == [ref.served_as for ref in started.panel]
    assert restored.transcriber.served_as == "qwen3-vl:8b-instruct-q4_K_M"
    assert _persisted_run_config(restored) == frozen_text, "the round trip is not byte-identical"

    # Resume against the current configuration (the same file): rehydrates with the address.
    current = parse_config_document(_edge_file(), "toml")
    resumed = rehydrate_run_config({"run_config": frozen_text}, current, SYNTHETIC_COHORT)
    assert [ref.served_as for ref in resumed.panel] == [
        "qwen3:30b-a3b-q4_K_M", "mistral-small:24b-q4_K_M", "gemma3:27b-it-q4_K_M"]
    assert resumed.transcriber.served_as == "qwen3-vl:8b-instruct-q4_K_M"


def test_tc_conf_48_a_resume_under_a_renamed_served_model_is_the_same_grader():
    """ADR-61: renaming a model in the server is a config edit, not a new grader — the resume
    is not refused as a backend mismatch, and the build identity is the frozen one.

    Which address a resumed run then uses (the frozen one or the edited one) the plan does not
    state, so it is deliberately not pinned here."""
    frozen_text = _persisted_run_config(_resolve(_edge_file()))
    renamed = parse_config_document(
        _edge_file(judge_a="qwen3:30b-renamed", reader="vision-renamed"), "toml")
    resumed = rehydrate_run_config({"run_config": frozen_text}, renamed, SYNTHETIC_COHORT)
    assert [ref.build_id for ref in resumed.panel] == [_JUDGE_A, _JUDGE_B, _JUDGE_C]
    assert resumed.panel[0].served_as is not None


def test_tc_conf_48_a_config_with_no_local_model_freezes_byte_identically_to_before():
    """`served_as` is written only when set, so a run config without it serializes as it
    always did: no `served_as` key anywhere in the frozen text."""
    hosted = _resolve(_hosted_file(None))
    assert "served_as" not in _persisted_run_config(hosted)
    # And an edge config built in code from refs that carry it does write it.
    assert "served_as" in _persisted_run_config(resolve_run_config(edge_cfg(), SYNTHETIC_COHORT))
