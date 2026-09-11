"""`TC-CALIB-11` — the shared build is refused at configuration time, at the type.

Test plan §5.17, `TC-CALIB-11` (NFR-CALIB-04, Unit / rung 0, negative).

The contract suite carries the gate-level refusal (`TC-CALIB-C08`: `back_translate` refuses an
off-panel ref whose `build_key` is registered as a panel build) — and its name says
"at_configuration_time", but the value it drives is the gate's registry, not the configuration
type. What no green test carried before this file is the moment the check can first refuse:
`RunConfig.__post_init__`, the constructor the design tells callers to use directly
("construct `RunConfig` literals rather than doubles", §3.1):

* a configuration whose off-panel checker shares a served build with a panel member is
  **rejected at construction** — `ConfigurationError`, naming `panel[<position>]`, the shared
  build, and the clause (`CT-CALIB-08`, `NFR-CALIB-04`);
* the identity is the **served build** — provider, build id and quantization — not the label:
  the same build under a different role refuses, while the same build id under a *different
  quantization* is a different served artifact and is accepted;
* the position is named — a three-judge panel that shares its second judge's build is refused
  naming `panel[1]`, so the operator finds the clash rather than hunting for it;
* a distinct build constructs cleanly, so the refusal is the shared build and nothing else.

Asserted on the type (the constructor), because an invariant enforced only by the resolver is
forgeable through `dataclasses.replace` and through a hand-written literal — the same reasoning
`TC-CONF-C02` applies to every other field rule.
"""

from __future__ import annotations

import dataclasses

import pytest

from tests.support.conf_builders import (
    EDGE_JUDGE,
    EDGE_JUDGE_2,
    EDGE_JUDGE_3,
    EDGE_OFF_PANEL,
    EDGE_TRANSCRIBER,
    PROMPT_TEMPLATE_V,
    SYNTHETIC_COHORT,
)
from tests.support.impl import CONF_MODULE, require


def _run_config_kwargs(conf, panel, off_panel_checker):
    """A legal `edge-local` `RunConfig` literal, varying only the off-panel checker.

    Mirrors the type-level idiom `TC-CONF-C02` uses: the resolver is not in the loop, so the
    constructor is what is on trial."""
    return dict(
        backend_profile="edge-local",
        hardware_profile="unified-large",
        panel=panel,
        transcriber=EDGE_TRANSCRIBER,
        off_panel_checker=off_panel_checker,
        prompt_template_v=PROMPT_TEMPLATE_V,
        concurrency_ceiling=4,
        prefix_token_ceiling=2000,
        cost_ceiling=None,
        cost_currency=None,
        retention_setting=None,
        panel_build_ref=conf.compute_panel_build_ref(panel),
    )


# --- the refusal, at the type --------------------------------------------------------------------


def test_tc_calib_11_a_shared_build_is_refused_when_the_configuration_is_built():
    """`RunConfig` with the panel's build in the off-panel checker → `ConfigurationError`.

    The exact exception the plan names, at the earliest moment the check can refuse. The message
    names the position (`panel[0]`), the shared build, and the clause — the operator fixes the
    configuration from the message alone.
    """
    conf = require(CONF_MODULE, issue="#140")
    require(
        CONF_MODULE, "RunConfig", "ConfigurationError", "compute_panel_build_ref",
        issue="#140",
    )

    shared = dataclasses.replace(EDGE_JUDGE, role="off_panel")
    panel = (EDGE_JUDGE,)
    with pytest.raises(conf.ConfigurationError) as exc:
        conf.RunConfig(**_run_config_kwargs(conf, panel, shared))

    message = str(exc.value)
    assert "shares its served build with panel[0]" in message, (
        f"the refusal reads {message!r}; a shared-build refusal must name the position the "
        "checker clashes with, not merely that a clash exists"
    )
    assert "CT-CALIB-08" in message and "NFR-CALIB-04" in message, (
        "the refusal does not name its clauses; the message is the record a reviewer reads to "
        "see the check was the off-panel share, not a resolution failure"
    )


def test_tc_calib_11_the_refusal_names_the_clashing_position_not_just_the_first():
    """A three-judge panel sharing its *second* judge's build is refused naming `panel[1]`.

    The sweep runs in panel order, and the refusal carries the position it stopped at. Asserted
    on a non-zero position because a `panel[0]`-only implementation is the shape an off-by-one
    or a break-early loop produces — and the fixture, not the message, decides which judge
    shares.
    """
    conf = require(CONF_MODULE, issue="#140")
    require(
        CONF_MODULE, "RunConfig", "ConfigurationError", "compute_panel_build_ref",
        issue="#140",
    )

    shared = dataclasses.replace(EDGE_JUDGE_2, role="off_panel")
    panel = (EDGE_JUDGE, EDGE_JUDGE_2, EDGE_JUDGE_3)
    with pytest.raises(conf.ConfigurationError) as exc:
        conf.RunConfig(**_run_config_kwargs(conf, panel, shared))

    assert "panel[1]" in str(exc.value), (
        f"the refusal reads {exc.value!s}; the clash is with the panel's second judge, and a "
        "refusal that only ever names panel[0] does not say which judge to replace"
    )


# --- the identity is the served build, not the label ---------------------------------------------


def test_tc_calib_11_the_label_does_not_fool_it_but_a_different_quantization_is_not_a_share():
    """Same build under a different role refuses; same build id under different quantization
    constructs.

    Identity is the exact encoding `compute_panel_build_ref` hashes — provider, build id,
    quantization — because two entries naming the same served build are the same model however
    they are labelled. A different quantization is a different served artifact (different
    weights), so it is a legal checker. The pair is the clause's teeth: keyed on the identity,
    neither a relabel sneaks through nor an honest deployment gets refused.
    """
    conf = require(CONF_MODULE, issue="#140")
    require(
        CONF_MODULE, "RunConfig", "ConfigurationError", "compute_panel_build_ref",
        issue="#140",
    )

    panel = (EDGE_JUDGE,)

    # Same served build, different role label: refused.
    relabelled = dataclasses.replace(EDGE_JUDGE, role="off_panel")
    with pytest.raises(conf.ConfigurationError):
        conf.RunConfig(**_run_config_kwargs(conf, panel, relabelled))

    # Same provider and build id, different quantization: a different served artifact.
    re_quantized = dataclasses.replace(
        EDGE_JUDGE, role="off_panel", quantization="q8"
    )
    config = conf.RunConfig(**_run_config_kwargs(conf, panel, re_quantized))
    assert config.off_panel_checker is not None

    # A genuinely distinct build constructs cleanly — the control row.
    config = conf.RunConfig(**_run_config_kwargs(conf, panel, EDGE_OFF_PANEL))
    assert config.off_panel_checker == EDGE_OFF_PANEL


def test_tc_calib_11_the_resolver_refuses_a_shared_build_the_same_way():
    """The resolver route refuses too — one rule, read through both entry points.

    `resolve_run_config` builds the same `RunConfig` from the caller's mapping, so a shared
    build arriving as configuration input cannot reach a resolved config by choosing the other
    entry point. Asserted once, on the shared-build literal, so the two entries are the same
    check and not a resolver that skips the type's invariant.
    """
    conf = require(CONF_MODULE, issue="#140")
    require(
        CONF_MODULE, "RunConfig", "ConfigurationError", "compute_panel_build_ref",
        issue="#140",
    )

    shared = dataclasses.replace(EDGE_JUDGE, role="off_panel")
    with pytest.raises(conf.ConfigurationError):
        conf.resolve_run_config(
            {
                "HARNESS_PROFILE": "edge-local",
                "HARNESS_HARDWARE_PROFILE": "unified-large",
                "panel": (shared,),
                "transcriber": EDGE_TRANSCRIBER,
                "off_panel_checker": EDGE_OFF_PANEL,
                "prompt_template_v": PROMPT_TEMPLATE_V,
            },
            SYNTHETIC_COHORT,
        )