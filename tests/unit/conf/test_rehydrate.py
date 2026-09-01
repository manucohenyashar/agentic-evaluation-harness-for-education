"""Resume — a run rebinds to its persisted backend, or refuses.

Case: `TC-CONF-04` (`FR-CONF-04`, `NFR-CONF-04`, **P0**, RISK-22 **High**), test plan §5.1.
Rung 0 — a `RunRow` value, no store.

RISK-22 is a resumed run silently changing the grader: an overnight run killed at 2am and
restarted at 3am against a different panel means half the cohort scored by one set of judges and
half by another, with nothing in the record saying so. The grades all look fine. That is why
every check here refuses rather than reconciles.
"""

from __future__ import annotations

import copy
import inspect
import json

import pytest

from aeh.conf import (
    BackendMismatchError,
    ConfigurationError,
    ModelRef,
    RunConfig,
    rehydrate_run_config,
    resolve_run_config,
)
from tests.support.conf_builders import (
    EDGE_PANEL_3,
    EDGE_TRANSCRIBER,
    SYNTHETIC_COHORT,
    edge_cfg,
    hosted_cfg,
)


@pytest.fixture
def started():
    """The persisted run `TC-CONF-04`'s preconditions describe: `edge-local`, a weights build
    with a `sha256:` hash, and the `panel_build_ref` it hashes to.

    Three judges rather than one, deliberately: a one-member panel cannot tell a check that
    compares the whole panel from one that compares `panel[0]`, and the variant this case cares
    most about is a *silent panel change*.
    """
    return resolve_run_config(edge_cfg(panel=EDGE_PANEL_3), SYNTHETIC_COHORT)


@pytest.fixture
def run_row(started):
    return started.to_persisted_dict()


def _current(**overrides):
    """Current configuration matching `started`, with one thing changed.

    `overrides` is applied after the three-judge default, so a case can replace `panel` itself.
    """
    return edge_cfg(**{"panel": EDGE_PANEL_3, **overrides})


# --- step 1: identical configuration round-trips byte-identically -----------------------------


def test_tc_conf_04_step_1_identical_configuration_rehydrates_byte_identically(started, run_row):
    """TC-CONF-04 step 1 — oracle: *exact value; `to_persisted_dict()` byte-identical to the
    stored blob* (`NFR-CONF-04`).

    "Byte-identical" is asserted over the **JSON encoding**, not over dict equality: the row
    reaches disk as text, and two dicts can compare equal while serializing differently — a
    `Decimal` normalized, a tuple that became a list, a key reordered. Dict equality would pass
    all three; the round trip on disk would not.
    """
    restored = rehydrate_run_config(run_row, _current())

    assert restored == started
    assert json.dumps(restored.to_persisted_dict(), sort_keys=True) == json.dumps(
        run_row, sort_keys=True
    )


@pytest.mark.parametrize(
    "ceiling",
    ["12.50", "0.10", "1E+2", "0.1234567890123456789", "12345678901234567890.01"],
)
def test_tc_conf_04_step_1_a_cost_ceiling_survives_the_round_trip_exactly(ceiling):
    """The same oracle where it actually bites: a **hosted** run, whose row carries a `Decimal`.

    The `edge-local` fixture above has no cost ceiling, so it cannot see a lossy serialization
    at all. And the obvious hosted value cannot either: `12.50` through a `float` comes back as
    `12.5`, which compares **equal** as a `Decimal` and re-serializes identically — a lossy
    implementation is self-consistent at that precision and passes.

    The last two values are the ones that discriminate. Verified: `float` loses them
    irrecoverably, so a `str(Decimal)` → `Decimal(str)` round trip and a `float` one give
    different answers here and nowhere else. `NFR-CONF-04` asks for byte-identical, and a ceiling
    is money.
    """
    from decimal import Decimal

    config = resolve_run_config(
        hosted_cfg("cloud-hosted", HARNESS_COST_CEILING=ceiling), SYNTHETIC_COHORT
    )
    row = config.to_persisted_dict()

    restored = rehydrate_run_config(row)

    assert restored.cost_ceiling == Decimal(ceiling)
    assert str(restored.cost_ceiling) == str(config.cost_ceiling)
    assert json.dumps(restored.to_persisted_dict(), sort_keys=True) == json.dumps(
        row, sort_keys=True
    )


def test_tc_conf_04_step_1_rehydration_reads_the_row_not_current_configuration(started, run_row):
    """`FR-CONF-04`: a resumed run "resolves to the `backend_profile` and `provider_config`
    persisted on its `run` row".

    Called with no current configuration at all, it must still reconstruct — which is the claim
    that reconstruction comes from the row. An implementation that quietly re-resolved from
    `cfg` would need one and fail here.
    """
    assert rehydrate_run_config(run_row) == started


@pytest.mark.parametrize(
    "cfg_factory,label",
    [
        (lambda: hosted_cfg("cloud-hosted"), "cloud-hosted"),
        (lambda: hosted_cfg("dev-ci"), "dev-ci"),
    ],
)
def test_tc_conf_04_step_2_a_different_backend_in_current_configuration_refuses(
    run_row, cfg_factory, label
):
    """TC-CONF-04 step 2 — oracle: exact exception type.

    Both remote profiles, not just the one the plan names: the claim is that a resumed run never
    switches backend, and `dev-ci` is the profile people assume is exempt because it looks
    internal.
    """
    with pytest.raises(BackendMismatchError) as caught:
        rehydrate_run_config(run_row, cfg_factory())
    assert type(caught.value) is BackendMismatchError, label


def test_tc_conf_04_step_2_a_backend_change_alone_is_what_refuses(run_row):
    """The same step with **only** the backend differing — same panel, same transcriber, same
    template.

    Every other "different backend" input also carries a different panel, so the panel check
    would catch them even if the backend check were deleted. This input isolates it: remove the
    backend comparison and this is the case that goes green when it should not.
    """
    with pytest.raises(BackendMismatchError):
        rehydrate_run_config(run_row, _current(HARNESS_PROFILE="cloud-hosted"))


# --- step 3: a different resolved build refuses -----------------------------------------------

_OTHER_JUDGE = ModelRef("judge", "ollama", "/models/other-70b.gguf@sha256:9999", "q4")
_SAME_BUILD_OTHER_PROVIDER = ModelRef(
    "transcriber", "attacker-proxy", EDGE_TRANSCRIBER.build_id, EDGE_TRANSCRIBER.quantization
)


@pytest.mark.parametrize(
    "overrides,what",
    [
        ({"panel": (_OTHER_JUDGE,) + EDGE_PANEL_3[1:]}, "a judge build swapped"),
        ({"panel": EDGE_PANEL_3[::-1]}, "the same judges in a different order"),
        (
            {
                "panel": (ModelRef("judge", "ollama", EDGE_PANEL_3[0].build_id, "q8"),)
                + EDGE_PANEL_3[1:]
            },
            "one judge's quantization changed",
        ),
        ({"transcriber": ModelRef("transcriber", "ollama", "/m/other.gguf@sha256:7777", "q4")},
         "a different transcriber build"),
        ({"transcriber": _SAME_BUILD_OTHER_PROVIDER},
         "the same transcriber build_id served by a different provider"),
        ({"prompt_template_v": "conf-v9.9.9"}, "a different prompt template"),
        ({"HARNESS_HARDWARE_PROFILE": "unified-small"}, "a different hardware profile"),
    ],
)
def test_tc_conf_04_step_3_any_change_to_the_grader_refuses(run_row, overrides, what):
    """TC-CONF-04 step 3 — "the same profile but a different resolved build id", widened to
    every change that makes this a different grader.

    Oracle: exact exception type.

    The rows past the first two are the ones a narrow implementation misses. *The same
    `build_id` served by a different provider* is the sharp one: the panel is compared through
    `panel_build_ref`, which mixes in provider and quantization, so comparing the transcriber by
    `build_id` alone leaves one model whose provider can change underneath a resumed run — and
    the transcriber is what turns a scanned page into the text every judge then scores.

    `prompt_template_v` and `hardware_profile` are here because a changed template is a changed
    grader by any reading of RISK-22, and the hardware profile sets the prefix ceiling, which
    decides what fits in the cached prefix.
    """
    with pytest.raises(BackendMismatchError) as caught:
        rehydrate_run_config(run_row, _current(**overrides))
    assert type(caught.value) is BackendMismatchError, what


@pytest.mark.parametrize(
    "partial,what",
    [
        ({"HARNESS_PROFILE": "edge-local"}, "a cfg naming only the profile"),
        ({**edge_cfg(panel=EDGE_PANEL_3), "panel": [{"build_id": "x"}]}, "a JSON-shaped panel"),
        ({**edge_cfg(panel=EDGE_PANEL_3), "panel": "not-a-panel"}, "a string panel"),
    ],
)
def test_tc_conf_04_step_3_an_incomplete_current_configuration_refuses_rather_than_passing(
    run_row, partial, what
):
    """Absence must not be a pass.

    A comparison that skips whatever the caller did not supply degrades to approving everything
    the moment `cfg` is thin — and this module refuses on absence everywhere else (`CT-CONF-11`,
    "absence raises"). Passing `cfg` at all is a claim to be holding current configuration; a
    caller who cannot make that claim omits the argument and gets no comparison, which is
    honest.
    """
    with pytest.raises(ConfigurationError) as caught:
        rehydrate_run_config(run_row, partial)
    assert type(caught.value) is ConfigurationError, what


# --- step 4: no member rebinds the backend ----------------------------------------------------


def test_tc_conf_04_step_4_no_public_member_mutates_or_replaces_the_backend(started):
    """TC-CONF-04 step 4 — oracle: artifact assertion over the reflected member list.

    Over the *surface*, not over a call: a method that exists but is never called still fails,
    because the next caller is the problem. `CT-CONF-14` names `with_backend()` as the exact
    construction this forbids.

    The full back-door sweep — `dataclasses.replace`, pickle, a hand-edited row — is
    `TC-CONF-C14`'s, on issue #9. What is asserted here is the member list plus the two doors
    this type closes itself.
    """
    # **Instance methods only.** `conf.py` states the exemption in as many words — "the sweep is
    # over operations that rebind *an object that already exists*, so it must exempt
    # constructors — otherwise every frozen value object in the module fails it". A
    # `@classmethod from_persisted(cls, backend_profile, panel, …)` is a constructor and is
    # additive per §3.1; without this filter it fails, which would be the test contradicting the
    # code it guards.
    for name in [n for n in dir(RunConfig) if not n.startswith("_")]:
        attribute = inspect.getattr_static(RunConfig, name, None)
        if isinstance(attribute, (classmethod, staticmethod)) or not callable(attribute):
            continue
        try:
            parameters = list(inspect.signature(attribute).parameters)
        except (TypeError, ValueError):  # pragma: no cover - builtins without a signature
            continue
        if not parameters or parameters[0] != "self":
            continue

        # `CT-CONF-14`'s own words: "backend, panel, or ceilings". `retention_setting` is not on
        # that list, so it is not asserted here — it is `CT-CONF-02`'s, enforced on the type.
        forbidden = set(parameters) & {
            "backend_profile", "panel", "cost_ceiling", "concurrency_ceiling",
            "prefix_token_ceiling",
        }
        assert not forbidden, (
            f"RunConfig.{name} accepts {sorted(forbidden)} on an object that already exists — "
            f"that is a rebinding surface (CT-CONF-14)"
        )

        # The parameter names are only half of it. `CT-CONF-14` names `with_backend()` as the
        # exact forbidden construction, and `def with_backend(self, profile)` carries none of
        # the names above — so the *verb* is checked too. Found by mutation: that method
        # survived the whole suite.
        assert not any(
            name.startswith(prefix)
            for prefix in ("with_", "set_", "rebind", "evolve", "replace_", "copy_with")
        ), (
            f"RunConfig.{name} reads as an operation that returns a rebound copy; CT-CONF-14 "
            f"names `with_backend()` as the construction that makes RISK-22 possible again"
        )

    with pytest.raises(TypeError):
        started.backend_profile = "cloud-hosted"
    with pytest.raises(TypeError):
        copy.replace(started, backend_profile="cloud-hosted")


# --- variants ---------------------------------------------------------------------------------


def test_tc_conf_04_variant_an_edge_local_row_with_no_hardware_profile_raises_configuration_error(
    run_row,
):
    """TC-CONF-04's first variant. `CT-CONF-02` makes `hardware_profile` non-null **iff**
    `edge-local`, so a row missing it is malformed — a `ConfigurationError`, not a mismatch:
    nothing about the *grader* changed, the row is simply not a row."""
    tampered = copy.deepcopy(run_row)
    tampered["provider_config"]["hardware_profile"] = None

    with pytest.raises(ConfigurationError) as caught:
        rehydrate_run_config(tampered)
    assert type(caught.value) is ConfigurationError


def test_tc_conf_04_variant_a_panel_build_ref_disagreeing_with_the_builds_raises_mismatch(run_row):
    """TC-CONF-04's second variant, and the one the plan singles out: *"this is the variant that
    catches a silent panel change."*

    `BackendMismatchError`, **not** `ConfigurationError` — and the distinction is the whole
    point. A stored ref that no longer matches its stored builds means the panel changed
    underneath a run that had already started scoring with it. That is RISK-22, not a malformed
    row, and a consumer branching on the exception type needs to be able to tell them apart.
    """
    tampered = copy.deepcopy(run_row)
    tampered["panel_config"]["panel"][1]["build_id"] = "/models/swapped.gguf@sha256:4444"

    with pytest.raises(BackendMismatchError) as caught:
        rehydrate_run_config(tampered)
    assert type(caught.value) is BackendMismatchError


def test_tc_conf_04_variant_a_tampered_ref_is_caught_even_with_no_current_configuration(run_row):
    """The same variant with `cfg` omitted, because that is how a resume actually runs.

    The check must live in reconstruction, not in the comparison against current configuration —
    otherwise the one code path a 3am unattended resume takes is the one path with no check.
    """
    tampered = copy.deepcopy(run_row)
    tampered["panel_config"]["panel"][2]["quantization"] = "q2"

    with pytest.raises(BackendMismatchError):
        rehydrate_run_config(tampered)


def test_tc_conf_04_no_step_returns_a_config_differing_from_the_persisted_one(started, run_row):
    """*"No step returns a config differing from the persisted one."*

    The expected result stated as a sweep: across every perturbation above, the call either
    raises or returns exactly what was stored. There is no third outcome — no reconciliation, no
    "closest match", no silently-updated field.
    """
    perturbations = [
        None,
        _current(),
        _current(HARNESS_PROFILE="cloud-hosted"),
        _current(prompt_template_v="conf-v9.9.9"),
        _current(panel=EDGE_PANEL_3[::-1]),
        hosted_cfg("cloud-hosted"),
    ]

    for current in perturbations:
        try:
            result = rehydrate_run_config(run_row) if current is None else rehydrate_run_config(
                run_row, current
            )
        except (BackendMismatchError, ConfigurationError):
            continue
        assert result == started, "a resume returned a config that is not the persisted one"


# --- the second producer of a remote binding --------------------------------------------------


@pytest.mark.parametrize("consent", ["real", "undeclared"])
def test_tc_conf_04_a_resume_re_runs_the_consent_gate_when_a_cohort_is_supplied(consent):
    """`FR-CONF-08` says *"refuse to produce a `RunConfig` binding a remote provider"* — and
    `rehydrate_run_config` produces exactly that.

    **This is the second producer, and it had no coverage at all.** The reasoning is `SEC-02`'s
    own: that case sweeps every remote profile because "a fourth remote backend added later is
    caught here and by nothing else". A second *entry point* is the same argument. Found by
    mutation — a `rehydrate_run_config` that silently ignored its `cohort` argument passed the
    entire suite.

    The scenario is not hypothetical: consent withdrawn at 6pm, a run killed at 2am, resumed at
    3am by an unattended sweeper holding the row. Without this the row is authority enough.
    """
    from aeh.conf import CohortRef, ConsentGateError

    hosted = resolve_run_config(hosted_cfg("cloud-hosted"), SYNTHETIC_COHORT)
    row = hosted.to_persisted_dict()
    cohort = CohortRef("c-2026-7B") if consent == "undeclared" else CohortRef("c-2026-7B", consent)

    with pytest.raises(ConsentGateError) as caught:
        rehydrate_run_config(row, cohort=cohort)
    assert type(caught.value) is ConsentGateError


@pytest.mark.parametrize("consent", ["synthetic", "consented"])
def test_tc_conf_04_a_resume_for_a_still_consented_cohort_reconstructs(consent):
    """The positive half: the gate must not refuse work that is still consented, or a resume
    becomes impossible for the cohorts the remote profile exists to serve."""
    from aeh.conf import CohortRef

    hosted = resolve_run_config(hosted_cfg("cloud-hosted"), SYNTHETIC_COHORT)
    row = hosted.to_persisted_dict()

    assert rehydrate_run_config(row, cohort=CohortRef("c-2026-7B", consent)) == hosted


def test_tc_conf_04_an_edge_local_resume_is_never_gated(started, run_row):
    """Nothing leaves the machine, so there is nothing to consent to — the same asymmetry the
    decision table has. A gate that refused here would make the air-gapped tier unresumable."""
    from aeh.conf import CohortRef

    assert rehydrate_run_config(run_row, cohort=CohortRef("c", "real")) == started


def test_tc_conf_04_omitting_the_cohort_skips_the_gate_deliberately():
    """The absence of a cohort is the caller saying "this is machinery replaying its own row",
    and it must not become an accidental bypass that looks like a check.

    Asserted so the optionality is a documented decision rather than something a reader has to
    infer from a default argument — and so that flipping it to mandatory later is a visible
    change to this test rather than a silent behaviour change.
    """
    hosted = resolve_run_config(hosted_cfg("cloud-hosted"), SYNTHETIC_COHORT)

    assert rehydrate_run_config(hosted.to_persisted_dict()) == hosted


# --- the off-panel checker --------------------------------------------------------------------

_OFF_PANEL = ModelRef("off_panel", "ollama", "/models/qwen-2.5-7b.gguf@sha256:abcd", "q4")
_OTHER_OFF_PANEL = ModelRef("off_panel", "ollama", "/models/phi-4.gguf@sha256:bcde", "q4")


@pytest.mark.parametrize(
    "persisted_has,current,what",
    [
        (True, None, "dropped between start and resume"),
        (False, _OFF_PANEL, "added between start and resume"),
        (True, _OTHER_OFF_PANEL, "swapped for a different build"),
        (
            True,
            ModelRef("off_panel", "vllm-mlx", _OFF_PANEL.build_id, _OFF_PANEL.quantization),
            "same build_id served by a different provider",
        ),
    ],
)
def test_tc_conf_04_step_3_the_off_panel_checker_is_compared_too(persisted_has, current, what):
    """`TC-CONF-04` step 3 reaches the off-panel checker as much as the transcriber: it is a
    reachable `ModelRef` that `_check_resolved` validates, so it is "a resolved build id".

    Found by mutation — the `started` fixture had no off-panel checker, so only the
    `both are None` branch of the comparison ever ran, and deleting the off-panel comparison
    entirely passed the whole suite. `M-INTEG` routes to this model on escalation, so a swap
    changes who adjudicates the contested cases specifically.
    """
    cfg_started = _current(off_panel_checker=_OFF_PANEL) if persisted_has else _current()
    row = resolve_run_config(cfg_started, SYNTHETIC_COHORT).to_persisted_dict()

    cfg_now = _current(off_panel_checker=current) if current is not None else _current()

    with pytest.raises(BackendMismatchError) as caught:
        rehydrate_run_config(row, cfg_now)
    assert type(caught.value) is BackendMismatchError, what


def test_tc_conf_04_an_unchanged_off_panel_checker_round_trips():
    """The positive half, so "refuse every off-panel configuration" cannot satisfy the above."""
    cfg = _current(off_panel_checker=_OFF_PANEL)
    started = resolve_run_config(cfg, SYNTHETIC_COHORT)

    restored = rehydrate_run_config(started.to_persisted_dict(), cfg)

    assert restored == started
    assert restored.off_panel_checker == _OFF_PANEL
