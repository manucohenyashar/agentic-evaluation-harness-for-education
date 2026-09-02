"""`CT-CONF-01`, `CT-CONF-02`, `CT-CONF-03` — the surface, the shape and the refs.

Test plan §6.11.1, issue #9 (TS-58). These are **clause** cases, and the discriminator §6.11
applies to every row is one question: *would this go red if the clause broke while every `FR-*`
case in §5 stayed green?* A case that only restates the clause is a title, not a test.

That is why each of these enumerates rather than asserts a point. `TC-CONF-01`'s §5 companion
resolves a config and checks the result; this one asks whether the *entry points* are still
synchronous and still touch nothing — a change that keeps every result correct. `TC-CONF-C02`
compares the field set against the design, not against the code, because `RUN_CONFIG_FIELDS` is
literally `tuple(f.name for f in fields(RunConfig))` and asserting against it passes for any
field set at all.

**Written ahead of implementation: the issue says `yes`, and it is stale.** It was filed before
#4, #5 and #6 landed `aeh.conf` on this branch. Thirteen of the fourteen cases in TS-58 are
expected **green**; a red one is an `M-CONF` defect to investigate, not the expected state. Only
`TC-CONF-C14` step 3 is genuinely blocked (rung 3, `M-ORCH` and `M-CONSOLE` real).
"""

from __future__ import annotations

import inspect

import pytest

from tests.support.conf_builders import (
    EDGE_OFF_PANEL,
    EDGE_PANEL_3,
    EDGE_TRANSCRIBER,
    HOSTED_PANEL_3,
    HOSTED_TRANSCRIBER,
    SYNTHETIC_COHORT,
    edge_cfg,
    edge_panel,
    hosted_cfg,
)
from tests.support.guards import open_audit
from tests.support.impl import CONF_MODULE, require

pytestmark = pytest.mark.contract


# `CT-CONF-02`: "RunConfig carries exactly the fields listed in Interfaces." Transcribed by hand
# from design §3.1's Interfaces block — **not** read from `aeh.conf`. The module exports
# `RUN_CONFIG_FIELDS = tuple(f.name for f in fields(RunConfig))`, so asserting against that would
# be the code agreeing with itself: it passes for any field set, including one with a
# `with_backend`-friendly `parent_run_id` bolted on. The literal below is the design's list, and
# the diff between it and the dataclass is the whole assertion.
DESIGN_RUN_CONFIG_FIELDS = (
    "backend_profile",
    "hardware_profile",
    "panel",
    "transcriber",
    "off_panel_checker",
    "prompt_template_v",
    "concurrency_ceiling",
    "prefix_token_ceiling",
    "cost_ceiling",
    "cost_currency",
    "retention_setting",
    "panel_build_ref",
)


# --- TC-CONF-C01 — surface -------------------------------------------------------------------


def test_tc_conf_c01_both_entry_points_are_synchronous_and_touch_nothing(network_guard):
    """`CT-CONF-01` — both entry points are synchronous, make no network call, and read no file
    the caller did not name.

    **The violation this catches**: the day someone makes resolution `async` to fetch a remote
    profile table. Every `FR-*` case still passes — the resolved `RunConfig` is correct, the
    fields are right, the hash matches — because a `FR-*` case awaits the result or never
    notices the coroutine. `M-ORCH` and `M-CONFORM` call these from synchronous code and would
    break at every call site.

    Three assertions, and the third is the one that is easy to leave out. A function that is not
    itself a coroutine function can still **return** a coroutine (a plain `def` whose body is
    `return _resolve_async(...)`), which passes `iscoroutinefunction` and fails every caller. So
    the returned value is checked too.

    The read audit is `open_audit`, not `write_audit`: this clause is about *reads*, and
    `write_audit` leaves reads untouched by design. Zero named files means the expected set is
    empty — the caller passed a mapping and a cohort reference, and named no path at all.
    """
    conf = require(CONF_MODULE, issue="#4")
    resolve_run_config = conf.resolve_run_config
    rehydrate_run_config = conf.rehydrate_run_config

    # The plan's oracle names `asyncio.iscoroutinefunction`; `inspect.iscoroutinefunction` is
    # the same predicate under the name that survives — the `asyncio` alias is deprecated and
    # goes away in 3.16, and a DeprecationWarning inside a P1 clause case is a future collection
    # error.
    assert not inspect.iscoroutinefunction(resolve_run_config)
    assert not inspect.iscoroutinefunction(rehydrate_run_config)

    cfg = edge_cfg()

    # Everything imported and built before the audit opens, so the log holds only what the two
    # entry points did.
    with open_audit() as reads:
        resolved = resolve_run_config(cfg, SYNTHETIC_COHORT)
        run_row = {
            "backend_profile": resolved.backend_profile,
            **resolved.to_persisted_dict(),
        }
        rehydrated = rehydrate_run_config(run_row)

    assert not inspect.isawaitable(resolved), (
        "resolve_run_config returned an awaitable. It is not a coroutine function, which is the "
        "check that passes — but every synchronous caller still breaks (CT-CONF-01)."
    )
    assert not inspect.isawaitable(rehydrated)
    assert rehydrated == resolved

    # The caller named no file, so the permitted set is empty.
    assert reads == [], (
        "CT-CONF-01: these entry points read files the caller did not name — "
        + ", ".join(f"{r.api}({r.target!r})" for r in reads)
    )
    network_guard.assert_no_network()


# --- TC-CONF-C02 — data ----------------------------------------------------------------------


def test_tc_conf_c02_the_field_set_equals_the_designs_interfaces_list_exactly():
    """`CT-CONF-02` — `RunConfig` carries **exactly** the fields listed in Interfaces.

    Set equality, not a subset. A subset assertion passes for a `RunConfig` that grew a
    thirteenth field, and design §3.1's Compatibility note calls any change to this field set
    **breaking** — it is what `M-ORCH` serializes into three columns and what `M-STATS` and
    `M-PKG` scope on.

    Order is asserted too, though the clause does not require it: `to_persisted_dict` writes
    positionally into named keys, and a reader comparing this list to the design's block should
    be able to read them side by side.
    """
    conf = require(CONF_MODULE, issue="#4")
    from dataclasses import fields

    actual = tuple(f.name for f in fields(conf.RunConfig))

    assert set(actual) == set(DESIGN_RUN_CONFIG_FIELDS), (
        "RunConfig's field set differs from design §3.1's Interfaces block.\n"
        f"  only in the code:   {sorted(set(actual) - set(DESIGN_RUN_CONFIG_FIELDS))}\n"
        f"  only in the design: {sorted(set(DESIGN_RUN_CONFIG_FIELDS) - set(actual))}"
    )
    assert actual == DESIGN_RUN_CONFIG_FIELDS


@pytest.mark.parametrize(
    "profile, hardware, cost, retention",
    [
        # (backend_profile, hardware_profile non-null?, cost fields non-null?, retention non-null?)
        ("edge-local", True, False, False),
        ("cloud-hosted", False, True, True),
        ("dev-ci", False, True, False),
    ],
)
def test_tc_conf_c02_every_nullability_rule_holds_in_both_directions(
    profile, hardware, cost, retention
):
    """`CT-CONF-02`'s three iff-conditions, swept over all three backends, both directions.

    **Both directions is the case.** Asserting only "`hardware_profile` is non-null on
    `edge-local`" lets a stray `hardware_profile='unified-large'` ride along on a `cloud-hosted`
    config — which is exactly the value `M-ORCH` would then serialize into `provider_config` and
    `M-CONSOLE` would render, describing hardware that never touched the run.

    `retention_setting` is deliberately **not** an iff: the clause says "non-null for
    `cloud-hosted`" and says nothing about `dev-ci`, so the row above asserts non-null on
    `cloud-hosted` and null on `dev-ci` per `FR-CONF-12`, which scopes the requirement to
    `cloud-hosted` alone.
    """
    conf = require(CONF_MODULE, issue="#4")

    cfg = (
        edge_cfg()
        if profile == "edge-local"
        else hosted_cfg(
            profile,
            **({} if profile == "cloud-hosted" else {"retention_setting": None}),
        )
    )
    if profile == "dev-ci":
        cfg.pop("retention_setting", None)

    config = conf.resolve_run_config(cfg, SYNTHETIC_COHORT)

    assert config.backend_profile == profile
    assert (config.hardware_profile is not None) is hardware
    assert (config.cost_ceiling is not None) is cost
    assert (config.cost_currency is not None) is cost
    assert (config.retention_setting is not None) is retention


@pytest.mark.parametrize(
    "profile, violation",
    [
        ("cloud-hosted", {"hardware_profile": "unified-large"}),
        ("dev-ci", {"hardware_profile": "unified-small"}),
        ("edge-local", {"cost_ceiling": "1"}),
        ("edge-local", {"cost_currency": "USD"}),
        ("edge-local", {"retention_setting": "zero-retention"}),
    ],
)
def test_tc_conf_c02_the_type_itself_refuses_a_violating_combination(profile, violation):
    """The other direction of the iff, asserted on the **type** rather than on the resolver.

    An invariant that lives only in the function that happens to build the value is not an
    invariant: `dataclasses.replace` does not route through `__replace__`, so a caller could
    take a resolved `edge-local` config and construct a `cloud-hosted` one still carrying
    `hardware_profile` — a value `resolve_run_config` can never return but every consumer would
    accept, because design §3.1 tells consumers to construct `RunConfig` literals rather than
    doubles.

    So the assertion is over the constructor. Each row is a field set that satisfies every rule
    except one.
    """
    conf = require(CONF_MODULE, issue="#4")
    from decimal import Decimal

    panel = EDGE_PANEL_3 if profile == "edge-local" else HOSTED_PANEL_3
    base = dict(
        backend_profile=profile,
        hardware_profile="unified-large" if profile == "edge-local" else None,
        panel=panel,
        transcriber=EDGE_TRANSCRIBER if profile == "edge-local" else HOSTED_TRANSCRIBER,
        off_panel_checker=None,
        prompt_template_v="conf-v1.0.0",
        concurrency_ceiling=4,
        prefix_token_ceiling=2000,
        cost_ceiling=None if profile == "edge-local" else Decimal("10"),
        cost_currency=None if profile == "edge-local" else "USD",
        retention_setting="zero-retention" if profile == "cloud-hosted" else None,
        panel_build_ref=conf.compute_panel_build_ref(panel),
    )
    if "cost_ceiling" in violation:
        violation = {"cost_ceiling": Decimal(violation["cost_ceiling"])}
    base.update(violation)

    with pytest.raises(conf.ConfigurationError):
        conf.RunConfig(**base)


@pytest.mark.parametrize("size", [1, 3, 5])
def test_tc_conf_c02_a_panel_of_one_three_or_five_resolves(size):
    """`CT-CONF-02`: "`panel` has length 1, 3, or 5". The positive half, over every legal size.

    Five is the one worth spelling out. `PANEL_SIZES` is a frozenset and the §5 cases exercise
    it, but a panel of five is also the widest input `compute_panel_build_ref` ever sees, and the
    judges are distinct so a dedup-before-hash implementation cannot hide behind repetition.
    """
    conf = require(CONF_MODULE, issue="#4")

    config = conf.resolve_run_config(
        edge_cfg(**{"panel": edge_panel(size)}), SYNTHETIC_COHORT
    )

    assert len(config.panel) == size
    assert len(set(config.panel)) == size, "the panel deduplicated distinct judges"


@pytest.mark.parametrize("size", [0, 2, 4])
def test_tc_conf_c02_a_panel_that_is_empty_or_even_raises(size):
    """"never even, never 0" — each of `0`, `2` and `4` asserted to raise, per the plan's row.

    Built from the same `edge_panel()` helper as the legal sizes, so a failure cannot be blamed
    on a differently-shaped literal.
    """
    conf = require(CONF_MODULE, issue="#4")

    with pytest.raises(conf.ConfigurationError):
        conf.resolve_run_config(edge_cfg(**{"panel": edge_panel(size)}), SYNTHETIC_COHORT)


# --- TC-CONF-C03 — data ----------------------------------------------------------------------


@pytest.mark.parametrize("profile", ["edge-local", "cloud-hosted", "dev-ci"])
def test_tc_conf_c03_every_reachable_ref_is_resolved_in_its_backends_form(profile):
    """`CT-CONF-03` — every `ModelRef` reachable from a `RunConfig` satisfies `is_resolved()`,
    *and* is resolved in the form its backend requires.

    An **invariant over the reachable set**, which is what makes this a clause case rather than a
    restatement. "Reachable" is all three positions — every panel member, the transcriber, and
    the off-panel checker — because a resolver that validated `panel[0]` and trusted the rest
    passes any case built on a one-judge panel. The panels here are three-judge and an off-panel
    checker is supplied on every backend that can carry one.

    The per-backend half is the part `is_resolved()` alone cannot express: a provider-pinned slug
    is a perfectly resolved identity and still wrong on `edge-local`, where nothing but a weights
    path plus quantization plus hash names what actually ran. `M-PKG` keys every
    `package_validation` row on `build_id`, so a `build_id` that stops identifying the build
    invalidates the record silently.
    """
    conf = require(CONF_MODULE, issue="#4")

    if profile == "edge-local":
        cfg = edge_cfg(**{"panel": EDGE_PANEL_3, "off_panel_checker": EDGE_OFF_PANEL})
        expected_form = "edge-weights"
    else:
        cfg = hosted_cfg(profile, **{"panel": HOSTED_PANEL_3})
        expected_form = "provider-pinned"

    config = conf.resolve_run_config(cfg, SYNTHETIC_COHORT)

    reachable = [*config.panel, config.transcriber]
    if config.off_panel_checker is not None:
        reachable.append(config.off_panel_checker)
    assert len(reachable) >= 4, "the fixture must reach more than one ref for this to assert"

    for ref in reachable:
        assert ref.is_resolved(), f"{ref.role} ref is not resolved: {ref.build_id!r}"
        assert ref.build_form() == expected_form, (
            f"{ref.role} ref is a {ref.build_form()} build on {profile!r}, which requires "
            f"{expected_form} (CT-CONF-03)"
        )
        if expected_form == "edge-weights":
            # What "resolved" *means* here, spelled out rather than delegated to build_form():
            # a weights path, a quantization, and a hash.
            assert ref.quantization is not None
            assert "@sha256:" in ref.build_id
            assert any(
                ref.build_id.split("@")[0].endswith(suffix)
                for suffix in conf.WEIGHTS_SUFFIXES
            )


@pytest.mark.parametrize("tag", ["latest", "stable", "main"])
@pytest.mark.parametrize("position", ["panel", "transcriber", "off_panel_checker"])
def test_tc_conf_c03_a_ref_carrying_a_floating_tag_fails_at_every_position(tag, position):
    """"A ref carrying a floating tag (`:latest`) must fail" — at every reachable position.

    A floating tag is the failure mode that survives review: it looks pinned, it resolves today,
    and it names a *different* build next week. Nothing downstream can tell, because
    `package_validation` recorded the slug rather than what answered.

    Swept over all three positions because a resolver that checks the panel and takes the
    transcriber on trust is the shape this clause exists to catch — and it is the shape a reader
    of a panel-only test would never suspect.
    """
    conf = require(CONF_MODULE, issue="#4")

    floating = conf.ModelRef(
        role="judge" if position == "panel" else position.replace("_checker", ""),
        provider="openrouter",
        build_id=f"meta-llama/llama-3.3-70b-instruct:{tag}",
        quantization=None,
    )
    assert not floating.is_resolved(), "the fixture is not floating, so the case asserts nothing"

    overrides = (
        {"panel": (floating,)} if position == "panel" else {position: floating}
    )
    with pytest.raises(conf.UnresolvedModelRefError):
        conf.resolve_run_config(hosted_cfg(**overrides), SYNTHETIC_COHORT)
