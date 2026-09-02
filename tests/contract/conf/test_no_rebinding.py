"""`CT-CONF-14` — no operation changes an existing run's backend, panel, or ceilings.

Test plan §6.11.1, block form; `REG-CT-CONF-14` in the permanent baseline set of §6.9. The plan
names this file by path.

**Non-promise and a safety property at once**, which is why it gets three steps rather than an
assertion. A non-promise needs a *consumer sweep* — the thing nobody promised is only safe if no
consumer has quietly come to need it (RISK-36). A safety property needs its *adversarial
construction* — a plausible refactor someone would actually propose, asserted to turn this case
red while every `FR-CONF-*` case in §5 stays green. If it does not, the case is testing something
adjacent to the clause and must be tightened (§6.11).

The construction here is the one the plan names: `RunConfig.with_backend(profile)` returning a
copy, wired to `M-CONSOLE`'s retry control. It is exactly the change someone proposes to fix
"the run failed on the local model, let me retry it on the cloud" — and it is RISK-22 arriving
as a convenience: half a cohort graded by one panel, half by another, one `run_id`, and nothing
in the record saying so.

**Attempted and deliberately not asserted**: `object.__setattr__(config, ...)` and
`config.__dict__.update(...)` both succeed. No Python object can defend against them, frozen
dataclass or not, so an assertion here would be a claim about the language rather than about
`M-CONF`. They are recorded so the next reader knows the sweep did not overlook them.
"""

from __future__ import annotations

import copy
import dataclasses
import inspect

import pytest

from tests.support.conf_builders import (
    EDGE_JUDGE_4,
    EDGE_PANEL_3,
    SYNTHETIC_COHORT,
    edge_cfg,
    hosted_cfg,
)
from tests.support.impl import CONF_MODULE, CONSOLE_MODULE, require

pytestmark = pytest.mark.contract


#: What no operation may accept on an object that already exists. `CT-CONF-14`'s own list, plus
#: `profile`, which is what a `with_backend(profile)` helper would call its argument.
#:
#: This is the **nominal** net, and on its own it is a naming convention rather than a test:
#: review showed `with_backend(self, backend)` — one word renamed — sailing through the entire
#: repository green. It is kept because it catches a helper that exists and is never called, which
#: is what the plan asks for, and it is paired with the behavioural probe below, which catches one
#: whatever its arguments happen to be called.
REBINDING_ARGUMENTS = frozenset(
    {"backend_profile", "panel", "cost_ceiling", "retention_setting", "profile"}
)

#: The two entry points, exempt from the module-level sweep. Exempt **by construction, not by
#: preference**: neither takes a `RunConfig`, so neither operates on an object that already
#: exists. Building a new config from a mapping is the sanctioned way to get a different backend —
#: a different run (`FR-CONF-04`, R1).
ENTRY_POINTS = frozenset({"resolve_run_config", "rehydrate_run_config"})

#: How the *nominal* net decides a module-level function operates on a config that already exists.
#:
#: The prerequisite matters: without it the net flags `compute_panel_build_ref(panel)`, which takes
#: a panel and no config and is the sanctioned way to compute a *new* run's key. Annotation alone
#: is not enough either — `conf.py` has `from __future__ import annotations`, so an unannotated
#: parameter is `Parameter.empty` and `RunConfig | None` is a string matching neither the class nor
#: `"RunConfig"` exactly. So: a substring match on whatever the annotation stringifies to, **or** a
#: config-shaped parameter name.
#:
#: A helper whose config parameter is named something else entirely falls through this net — and is
#: caught by the behavioural one, which passes a real config in and does not care what it is called.
CONFIG_PARAMETER_NAMES = frozenset({"config", "run_config", "persisted", "existing", "run"})


def _takes_a_config(signature) -> bool:
    for parameter in signature.parameters.values():
        annotation = parameter.annotation
        if annotation is not inspect.Parameter.empty and "RunConfig" in str(annotation):
            return True
        if parameter.name in CONFIG_PARAMETER_NAMES:
            return True
    return False


#: Set by `_attempt` whenever a probe returns anything at all. Read by the liveness guard at the
#: end of `assert_no_rebinding_surface`.
#:
#: `_attempt` swallows every exception, which is correct — a refusal is the outcome this case
#: wants — but it means a sweep in which *every* call happens to raise looks identical to a sweep
#: in which nothing rebinds. That is not hypothetical: the mutation harness once reported a graft
#: as MISSED because a botched rename made its body raise `AttributeError`, and `_attempt` ate it.
#: A broken probe reads exactly like a clean module. So the machinery asserts it is live.
_PROBE_RETURNED: list[object] = []


def _attempt(call, *args, **kwargs):
    """Invoke and return the result, or `None` if it refused. Refusing is the correct outcome."""
    try:
        result = call(*args, **kwargs)
    except Exception:  # noqa: BLE001 - any refusal passes; only a returned config is a finding
        return None
    _PROBE_RETURNED.append(result)
    return result


def _is_a_rebinding(result, original, conf) -> bool:
    """Did this call hand back a config that is *this run* wearing a different grader?"""
    return isinstance(result, conf.RunConfig) and (
        result.backend_profile != original.backend_profile or result.panel != original.panel
    )


def assert_no_rebinding_surface(conf) -> None:
    """Step 1, factored out so the adversarial construction can assert it goes red.

    *"Enumerate every public member of `RunConfig` and of the module, by reflection. Assert none
    of them accepts a `backend_profile`, `panel`, `cost_ceiling` or `retention_setting` argument
    on an object that already exists — the assertion is over the surface, not over a call, so a
    method that exists but is never called still fails."*

    Two populations, because a rebinding helper can live in either — members of `RunConfig` (the
    `with_backend()` shape) and module-level callables taking a config (the
    `rebind(config, backend_profile)` shape, which the first population misses entirely).

    And **two nets over each**, because either alone is defeated by a rename:

    * the **nominal** net reads parameter names, `**kwargs` and return annotations. It is what
      satisfies the plan's "over the surface, not over a call" — a helper that exists and is never
      called fails here — and it is the only net that can see a helper whose body is not yet
      written.
    * the **behavioural** net *invokes* every plausible member with every backend profile and with
      a different panel, and fails if anything hands back a `RunConfig` whose backend or panel
      differs from the one it was given. That is what the clause actually says, and it does not
      care what the argument is named.

    The behavioural net was added after review. The nominal net alone passed
    `with_backend(self, backend)` — the plan's own adversarial construction with one word renamed
    — while every case in the repository stayed green, and the plan is explicit about what that
    means: *"if it does not, the case is testing something adjacent to the clause and must be
    tightened."*

    Two further holes review found in the module population, both closed here: it filtered on
    `parameter.annotation in (RunConfig, "RunConfig")`, but `conf.py` has
    `from __future__ import annotations` — an unannotated parameter is `Parameter.empty` and
    `RunConfig | None` stringifies to neither, so the filter skipped the whole population before
    looking at a single argument. And it enumerated `conf.__all__` rather than `dir(conf)`, so a
    helper the author simply did not export was invisible — which is precisely the one nobody is
    watching.

    **Invoking arbitrary public members is safe here and nowhere else**: `CT-CONF-09` is that this
    module writes nothing at all, and a member that grew a side effect would be caught by
    `TC-CONF-C09`. Not *first* — pytest runs shuffled (§4.6), so there is no ordering to lean on;
    the two cases are independent and both must hold.
    """
    offenders: list[str] = []
    _PROBE_RETURNED.clear()

    edge = conf.resolve_run_config(edge_cfg(**{"panel": EDGE_PANEL_3}), SYNTHETIC_COHORT)
    hosted = conf.resolve_run_config(hosted_cfg(), SYNTHETIC_COHORT)
    # Probed from both directions, so a helper that only ever moves *to* the cloud and one that
    # only ever moves *to* the edge are both caught.
    baselines = (edge, hosted)
    probes = ("edge-local", "cloud-hosted", "dev-ci", (EDGE_JUDGE_4,), EDGE_PANEL_3)

    # -- population 1: members of RunConfig
    for name in dir(conf.RunConfig):
        if name.startswith("_"):
            continue
        member = getattr(conf.RunConfig, name)
        if not callable(member):
            continue
        try:
            signature = inspect.signature(member)
        except (TypeError, ValueError):  # pragma: no cover - builtins without a signature
            continue

        for parameter in signature.parameters.values():
            if parameter.name == "self":
                continue
            if parameter.name in REBINDING_ARGUMENTS:
                offenders.append(
                    f"RunConfig.{name}() accepts {parameter.name!r} on an existing config"
                )
            if parameter.kind is inspect.Parameter.VAR_KEYWORD:
                offenders.append(
                    f"RunConfig.{name}() takes **{parameter.name}, so it accepts any of "
                    f"{sorted(REBINDING_ARGUMENTS)} without naming them"
                )
        if signature.return_annotation in (conf.RunConfig, "RunConfig"):
            offenders.append(f"RunConfig.{name}() returns a RunConfig")

        for baseline in baselines:
            bound = getattr(baseline, name)
            calls = [((), {})]
            calls += [((probe,), {}) for probe in probes]
            calls += [((), {key: probe}) for key in sorted(REBINDING_ARGUMENTS) for probe in probes]
            for args, kwargs in calls:
                if _is_a_rebinding(_attempt(bound, *args, **kwargs), baseline, conf):
                    offenders.append(
                        f"RunConfig.{name}() returned a config on a different backend or panel"
                    )
                    break

    # -- population 2: module-level callables that operate on a config
    for name in dir(conf):
        if name.startswith("_") or name in ENTRY_POINTS:
            continue
        member = getattr(conf, name)
        if not inspect.isfunction(member):
            continue
        signature = inspect.signature(member)

        if _takes_a_config(signature):
            for parameter in signature.parameters.values():
                if parameter.name in REBINDING_ARGUMENTS:
                    offenders.append(
                        f"{name}() takes a config and a {parameter.name!r} argument, which is a "
                        f"rebinding by another name"
                    )
                if parameter.kind is inspect.Parameter.VAR_KEYWORD:
                    offenders.append(f"{name}() takes a config and **{parameter.name}")

        for baseline in baselines:
            calls = [((baseline,), {})]
            calls += [((baseline, probe), {}) for probe in probes]
            calls += [
                ((baseline,), {key: probe})
                for key in sorted(REBINDING_ARGUMENTS)
                for probe in probes
            ]
            for args, kwargs in calls:
                if _is_a_rebinding(_attempt(member, *args, **kwargs), baseline, conf):
                    offenders.append(
                        f"{name}() returned a config on a different backend or panel when given "
                        f"one"
                    )
                    break

    # The behavioural net is only worth anything if it actually reached the code. Every probe
    # raising looks exactly like nothing rebinding, so assert the machinery is live before
    # reporting a clean sweep. `log_run_start(config)` returns a `ProfileSummary` and
    # `to_persisted_dict()` a dict, so this is non-vacuous today without asserting on either
    # by name.
    assert _PROBE_RETURNED, (
        "the behavioural sweep made hundreds of calls and every one of them raised, so it "
        "asserted nothing. Something upstream of the probes is broken — a fixture, a builder, or "
        "the module itself — and a clean result here would be a false negative on a P0 clause."
    )

    assert not offenders, (
        "CT-CONF-14: the module offers a way to change an existing run's backend, panel or "
        "ceilings. A consumer needing a different backend creates a different run "
        "(FR-CONF-04, R1, RISK-22):\n  " + "\n  ".join(sorted(set(offenders)))
    )


# --- step 1 — the surface sweep ---------------------------------------------------------------


def test_tc_conf_c14_step_1_no_public_member_accepts_a_rebinding_argument():
    """Step 1. See `assert_no_rebinding_surface` for what is swept and why.

    The assertion is over the surface rather than over a call, deliberately: a rebinding helper
    that exists and is never called still fails this case. That is the difference between a
    safety property and a bug report — the property is that the door is not there, not that
    nobody walked through it today.
    """
    conf = require(CONF_MODULE, issue="#4")

    assert_no_rebinding_surface(conf)


# --- step 2 — the back doors ------------------------------------------------------------------


def test_tc_conf_c14_step_2_every_back_door_refuses_a_backend_or_panel_change():
    """Step 2 — attribute assignment, `dataclasses.replace`, `__setstate__`, `copy` with an
    override, and rehydration from a hand-edited `run` row.

    **Exact exception type per back door**, and the types genuinely differ. A single
    `pytest.raises((TypeError, ConfigurationError))` across the table would pass if a door started
    raising the other one, and the two mean different things to a caller:

    * `setattr` / `delattr` → **`TypeError`**, because `FR-CONF-02` names it. A frozen dataclass
      raises `FrozenInstanceError`, an `AttributeError`, which a consumer's defensive
      `except TypeError` would not catch.
    * `copy.replace` → **`TypeError`**, from the module's own `__replace__`, which exists to say
      "no operation returns a copy".
    * `dataclasses.replace` → **`ConfigurationError`**, and by a different mechanism: it does not
      route through `__replace__` on any Python version, so it reaches `RunConfig.__post_init__`,
      which refuses the resulting shape. That the invariant lives on the *type* and not only in
      the resolver is what closes this door.
    * a hand-edited `run` row → one of **three** types depending on how deep the edit goes, and
      the table in the body says which and why. A row cannot be rebound because the backend, the
      build form and the panel hash constrain each other; an edit has to satisfy all three, and
      each guard refuses with its own type.

    **`__setstate__` is asserted absent, not asserted to raise.** A frozen dataclass has none, and
    that is the finding: were one added it would set `__dict__` directly, bypassing `__setattr__`
    entirely, and every assertion above would still pass.

    **What `dataclasses.replace` does *not* refuse, and why that is correct.** Changing only a
    ceiling — `cost_ceiling`, `retention_setting`, `concurrency_ceiling` — succeeds and returns a
    new object. It cannot be made to raise: design §3.1 tells consumers to *"test against a literal
    `RunConfig` value rather than a double — the type is frozen and cheap to construct"*, and a
    `replace` that changes only a ceiling is indistinguishable from that blessed construction. So
    the assertion for those fields is the pair that is actually true and actually load-bearing:
    the original is unchanged, and step 1 has already established that no operation can make an
    existing run adopt the copy. See the PR body — the plan's "exact exception per back door"
    over-reaches here, and that is a finding about the plan, recorded rather than papered over.
    """
    conf = require(CONF_MODULE, issue="#4")
    from decimal import Decimal

    config = conf.resolve_run_config(edge_cfg(**{"panel": EDGE_PANEL_3}), SYNTHETIC_COHORT)
    hosted = conf.resolve_run_config(hosted_cfg(), SYNTHETIC_COHORT)

    # -- attribute assignment
    with pytest.raises(TypeError):
        config.backend_profile = "cloud-hosted"
    with pytest.raises(TypeError):
        config.panel = (EDGE_JUDGE_4,)
    with pytest.raises(TypeError):
        del config.backend_profile

    # -- copy with an override
    with pytest.raises(TypeError):
        copy.replace(config, backend_profile="cloud-hosted")

    # -- dataclasses.replace, on the two fields the clause protects absolutely
    with pytest.raises(conf.ConfigurationError):
        dataclasses.replace(config, backend_profile="cloud-hosted")
    with pytest.raises(conf.ConfigurationError):
        dataclasses.replace(config, panel=(EDGE_JUDGE_4,))

    # -- __setstate__: absent, so no state injection path exists
    assert not hasattr(config, "__setstate__"), (
        "RunConfig grew a __setstate__, which writes __dict__ directly and bypasses the frozen "
        "__setattr__ every other assertion in this case relies on (CT-CONF-14)."
    )

    # -- a ceiling replace produces a new value and leaves the run's own config untouched
    before = hosted.cost_ceiling
    rebound = dataclasses.replace(hosted, cost_ceiling=Decimal("9999"))
    assert hosted.cost_ceiling == before, "dataclasses.replace mutated the original config"
    assert rebound is not hosted

    # -- rehydration from a hand-edited `run` row, at three depths of edit
    #
    # A row is the run's identity on disk, so editing it is the one back door that does not go
    # through the type at all. Three edits, each refused by a *different* guard, and the exact
    # type per edit is the assertion:
    #
    #   1. flip `backend_profile` alone -> the row now violates CT-CONF-02's iff (a
    #      `hardware_profile` on a non-edge backend), so `RunConfig.__post_init__` refuses it as
    #      a malformed row: ConfigurationError.
    #   2. flip it *and* square away `provider_config`, so the row is internally consistent ->
    #      the panel's builds still carry the old backend's form, and a weights path cannot
    #      identify what a hosted provider served: UnresolvedModelRefError.
    #   3. leave the backend alone and swap a judge, leaving `panel_build_ref` as it was -> the
    #      ref is recomputed from the persisted builds and disagrees: BackendMismatchError.
    #
    # Together they are why a row cannot be rebound: the backend, the build form and the panel
    # hash are three mutually constraining facts, and an edit has to satisfy all three.
    row = dict(config.to_persisted_dict())

    with pytest.raises(conf.ConfigurationError):
        conf.rehydrate_run_config(dict(row, backend_profile="dev-ci"))

    consistent = dict(
        row,
        backend_profile="dev-ci",
        provider_config=dict(
            row["provider_config"],
            hardware_profile=None,
            cost_ceiling="5.00",
            cost_currency="USD",
        ),
    )
    with pytest.raises(conf.UnresolvedModelRefError):
        conf.rehydrate_run_config(consistent)

    swapped_panel = dict(row["panel_config"])
    swapped_panel["panel"] = [dict(ref) for ref in swapped_panel["panel"]]
    swapped_panel["panel"][1]["provider"] = EDGE_JUDGE_4.provider
    swapped_panel["panel"][1]["build_id"] = EDGE_JUDGE_4.build_id
    with pytest.raises(conf.BackendMismatchError):
        conf.rehydrate_run_config(dict(row, panel_config=swapped_panel))


# --- the adversarial construction --------------------------------------------------------------


def test_tc_conf_c14_the_adversarial_construction_turns_this_case_red_and_nothing_else():
    """The construction the plan names, asserted **two-sided**.

    *"Implement `RunConfig.with_backend(profile)` returning a copy, and wire `M-CONSOLE`'s retry
    control to it. Assert that this construction turns TC-CONF-C14 red while every `FR-CONF-*`
    case in §5 stays green. If it does not, the case is testing something adjacent to the clause
    and must be tightened."*

    Both halves matter and they fail in opposite directions. If the construction leaves this case
    green, the case is decorative. If it also turns the §5 cases red, the case is not isolating
    the clause — it is catching something the functional suite already catches, and the safety
    property is unproven.

    Run **in process**: the helper is grafted onto the class, `assert_no_rebinding_surface` is
    asserted to raise, and then the behaviours §5's cases assert on — resolution, the round trip,
    `profile_summary()`, the panel hash — are exercised under the same mutation and must all still
    hold. The full two-sided run (`pytest tests/contract/conf/test_no_rebinding.py` red,
    `pytest tests/unit/conf/` green, against a mutated `src/aeh/conf.py`) is a scratchpad harness
    reported in the PR; this is the part that belongs in the suite, because it re-runs on every
    change rather than once.

    `monkeypatch` is not used: the helper is removed in a `finally`, so a failure between the two
    halves cannot leave a mutated `RunConfig` for a shuffled neighbour to import.
    """
    conf = require(CONF_MODULE, issue="#4")

    def with_backend(self, profile):
        """The plausible refactor: "retry this run on the cloud"."""
        return conf.resolve_run_config(
            hosted_cfg(profile) if profile != "edge-local" else edge_cfg(), SYNTHETIC_COHORT
        )

    conf.RunConfig.with_backend = with_backend
    try:
        with pytest.raises(AssertionError) as caught:
            assert_no_rebinding_surface(conf)
        assert "with_backend" in str(caught.value), (
            "the construction turned the case red for the wrong reason: "
            f"{caught.value}"
        )

        # And every §5 behaviour still holds under the mutation — the other half of the claim.
        config = conf.resolve_run_config(edge_cfg(**{"panel": EDGE_PANEL_3}), SYNTHETIC_COHORT)
        assert config.backend_profile == "edge-local"
        assert conf.rehydrate_run_config(dict(config.to_persisted_dict())) == config
        assert config.profile_summary().panel_build_ref == config.panel_build_ref
        assert conf.compute_panel_build_ref(EDGE_PANEL_3) == config.panel_build_ref
        with pytest.raises(conf.ConfigurationError):
            conf.resolve_run_config({}, SYNTHETIC_COHORT)
    finally:
        del conf.RunConfig.with_backend

    # The graft is gone, so the real case passes again.
    assert_no_rebinding_surface(conf)


# --- step 3 — the consumer sweep, rung 3 -------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_conf_c14_step_3_no_consumer_exposes_a_path_that_rebinds_a_run():
    """Step 3 — the consumer sweep, at **rung 3**, with `M-ORCH` and `M-CONSOLE` real.

    *"Assert neither exposes a path that reaches a rebinding — a console control that 'restarts
    with a different backend' must create a new run with a new id, and the case asserts the id
    changed."*

    **This is the half of `CT-CONF-14` that steps 1 and 2 cannot reach**, and the reason a
    non-promise needs a consumer sweep at all (RISK-36). `M-CONF` can hold its surface perfectly
    while `M-CONSOLE` rebinds a run by rewriting the `run` row directly and never calling this
    module — nothing in `aeh.conf` would notice, and the clause would be broken in a module
    nobody touched.

    Written ahead of `M-CONSOLE` and registered in `WRITTEN_AHEAD_BLOCKERS` under **#122**. Keyed
    on the console rather than on `M-ORCH` (#57, #61) although it needs both: the gate fires when
    *any* registered blocker resolves, so registering both would fire the moment the orchestrator
    lands with the console still months away, and whoever acted on it would unmark a test that
    then fails for a reason nobody expects. #122 depends on #10 and #61, so `M-CONSOLE` lands
    strictly after `M-ORCH` and resolving it means both halves are present.

    It fails with a stated reason rather than a collection error, so the failure names the issue
    that unblocks it (test plan §8.2). Substituting a rung-0 double would be worse than leaving
    it red: the double is precisely what this case exists to check past.
    """
    console = require(CONSOLE_MODULE, issue="#122")

    conf = require(CONF_MODULE, issue="#4")
    original = conf.resolve_run_config(edge_cfg(**{"panel": EDGE_PANEL_3}), SYNTHETIC_COHORT)

    # The console's retry control, driven to a different backend. The run it produces must be a
    # *different* run — a new id — not the same run wearing a new grader.
    started = console.start_run(original)
    retried = console.retry_run(started.run_id, backend_profile="cloud-hosted")

    assert retried.run_id != started.run_id, (
        "CT-CONF-14: the console retried a run onto a different backend under the same run_id. "
        "A consumer needing a different backend creates a different run (FR-CONF-04, RISK-22)."
    )
