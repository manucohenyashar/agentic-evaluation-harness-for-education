"""`TC-CONF-C23` (issue #705) — the clause suite for the `panel_for_profile` surface.

`CT-CONF-23` (contract v2.3, package-authoring design delta §3.2) reads:

> The panel-resolution surface reads configuration **at call time** and is **pure in `cfg`** —
> the named profile's `[[panel]]` refs in declared order, then `[[escalation_judge]]` refs,
> de-duplicated by build identity, each resolved per `CT-CONF-03`; it writes **no store rows**;
> an **empty panel raises** `ConfigurationError`.

The clause suite runs the three assertable rows of that clause — the plan's `§6.12 rows 1–3`
pointer has no such table in either design document (#705's notes record the erratum), so the
rows are the ones test plan §6.2 words: **row 1** call-time read / purity / the *named*
profile's refs; **row 2** the non-empty ordered de-duplicated chain over every legal profile
with per-backend resolved forms; **row 3** the empty-panel refusal. Plus the refusal the
existing resolver already enforces, which must hold on this surface too: the **floating-tag**
case of `CT-CONF-03`, at the panel seat and the escalation seat.

The discriminator every row answers: *would this go red if the clause broke while every
`FR-*` case in §5 stayed green?* A resolution that memoizes, that reads the environment
instead of the argument, or that deduplicates by object identity keeps every §5 chain correct
and breaks exactly one row here.

**Written ahead of implementation: yes** (#705). `panel_for_profile` is #687's story; every
body opens with `require(...)`, so the file runs red with `NotImplementedYet` naming #687
until that story lands. The bets disclosed on #705: `[[escalation_judge]]` arrives in the
parsed mapping as `ModelRef` entries (the parsed form, not M-PIPE's raw tables), and the
`backend_profile` argument names the profile over `HARNESS_PROFILE`.
"""

from __future__ import annotations

import copy
import importlib

import pytest

from tests.support.conf_builders import (
    EDGE_ESCALATION_A,
    EDGE_ESCALATION_DUPLICATE,
    EDGE_JUDGE_3,
    EDGE_PANEL_3,
    HOSTED_ESCALATION_A,
    HOSTED_ESCALATION_DUPLICATE,
    HOSTED_JUDGE,
    HOSTED_JUDGE_2,
    HOSTED_JUDGE_3,
    HOSTED_PANEL_3,
    edge_cfg,
    hosted_cfg,
)
from tests.support.impl import CONF_MODULE, require
from tests.support.profile_switching import (
    FIXTURE_JUDGE,
    PROFILE_NAMES,
    clear_profile_environment,
    f_profiles,
)

pytestmark = [pytest.mark.contract]


def _surface() -> tuple:
    """`panel_for_profile` via `require` (the written-ahead gate) and the conf module beside it.

    The symbol comes from `require` so a missing `panel_for_profile` fails as
    `NotImplementedYet` naming #687 **before anything else in the body runs**; the module
    import beside it supplies the error classes the rows raise and match on.
    """
    panel_for_profile = require(CONF_MODULE, "panel_for_profile", issue="#687")
    conf = importlib.import_module(CONF_MODULE)
    return panel_for_profile, conf


# --- CT-CONF-23 row 1 — call-time read, purity in cfg, the named profile ----------------------


def test_tc_conf_c23_row1_reads_the_configuration_at_call_time_and_leaves_it_untouched():
    """Row 1 — the surface is pure in `cfg` and reads it at call time, not once.

    **Breaks if** the resolution memoizes the first cfg it sees or mutates the mapping it was
    given. Both halves are asserted in one body because they are the same clause read in two
    directions: a cfg the call mutated fails the equality against the pre-call copy; a cfg the
    call *cached* fails the second call, which must see the panel the caller swapped in.
    """
    panel_for_profile, _conf = _surface()
    cfg = hosted_cfg(
        **{
            "panel": (HOSTED_JUDGE,),
            "escalation_judge": (HOSTED_ESCALATION_A,),
        }
    )
    pristine = copy.deepcopy(cfg)

    first = panel_for_profile(cfg, "cloud-hosted")
    assert first == (HOSTED_JUDGE, HOSTED_ESCALATION_A)
    assert cfg == pristine, (
        "panel_for_profile mutated the configuration it was given — the surface is pure in "
        f"cfg (CT-CONF-23 row 1): keys now {sorted(cfg)}"
    )

    cfg["panel"] = (HOSTED_JUDGE_2,)
    second = panel_for_profile(cfg, "cloud-hosted")
    assert second == (HOSTED_JUDGE_2, HOSTED_ESCALATION_A), (
        "the second call returned the first call's chain — the surface must read the "
        "configuration at call time, not memoize it (CT-CONF-23 row 1)"
    )


def test_tc_conf_c23_row1_resolves_the_named_profile_not_the_environment(monkeypatch):
    """Row 1 — *the named profile's* `[[panel]]` refs: the `backend_profile` argument wins, and
    a conflicting `HARNESS_PROFILE` in the environment is never consulted.

    **Breaks if** the surface composes through `effective_config` — which lifts the
    environment — instead of `select_profile_config`: the environment's `cloud-hosted` would
    win and the chain would come back as `HOSTED_JUDGE`, not `dev-ci`'s one judge.
    """
    panel_for_profile, _conf = _surface()
    clear_profile_environment(monkeypatch)
    monkeypatch.setenv("HARNESS_PROFILE", "cloud-hosted")

    chain = panel_for_profile(f_profiles(None), "dev-ci")

    assert chain == (FIXTURE_JUDGE,), (
        f"the chain is {chain!r}; the argument names dev-ci and the environment's "
        f"cloud-hosted must not be consulted (CT-CONF-23 row 1)"
    )


# --- CT-CONF-23 row 2 — non-empty, ordered, de-duplicated, resolved ---------------------------


#: (panel, escalations, the surviving escalation seat, required build form) per backend.
_ROW2 = {
    "edge-local": (EDGE_PANEL_3, (EDGE_ESCALATION_A, EDGE_ESCALATION_DUPLICATE), "edge-weights"),
    "cloud-hosted": (
        HOSTED_PANEL_3,
        (HOSTED_ESCALATION_A, HOSTED_ESCALATION_DUPLICATE),
        "provider-pinned",
    ),
    "dev-ci": (HOSTED_PANEL_3, (HOSTED_ESCALATION_A, HOSTED_ESCALATION_DUPLICATE), "provider-pinned"),
}


@pytest.mark.parametrize("profile", PROFILE_NAMES)
def test_tc_conf_c23_row2_the_chain_is_ordered_deduplicated_and_resolved_in_its_backends_form(
    profile, network_guard
):
    """Row 2 — over every legal profile: panel in declared order, then the escalations,
    de-duplicated by build identity, each member resolved in the form its backend requires.

    The duplicate in every row is a **re-constructed** ref equal by build identity to a panel
    member (`*_ESCALATION_DUPLICATE`), so a dedup keyed on object identity keeps a fifth seat
    and the exact-chain assertion fails. The per-backend half is `CT-CONF-03` on this surface:
    a provider-pinned slug is a resolved identity and still wrong on `edge-local`, where only a
    weights path plus quantization plus hash names what ran.
    """
    panel_for_profile, conf = _surface()
    panel, escalations, expected_form = _ROW2[profile]
    cfg_builder = edge_cfg if profile == "edge-local" else hosted_cfg
    if profile == "edge-local":
        # The fixture must re-present a panel member's build identity as a distinct object:
        # aliased, the sweep would stop discriminating object-identity dedup (see the unit
        # file's inline guard for the same discipline).
        assert EDGE_ESCALATION_DUPLICATE == EDGE_JUDGE_3 and (
            EDGE_ESCALATION_DUPLICATE is not EDGE_JUDGE_3
        ), "the duplicate fixture must equal EDGE_JUDGE_3 by build identity, as a distinct object"
        surviving, expected_chain = EDGE_ESCALATION_A, (*panel, EDGE_ESCALATION_A)
    else:
        assert HOSTED_ESCALATION_DUPLICATE == HOSTED_JUDGE_3 and (
            HOSTED_ESCALATION_DUPLICATE is not HOSTED_JUDGE_3
        ), "the duplicate fixture must equal HOSTED_JUDGE_3 by build identity, as a distinct object"
        surviving, expected_chain = HOSTED_ESCALATION_A, (*panel, HOSTED_ESCALATION_A)
    cfg = cfg_builder(**{"panel": panel, "escalation_judge": escalations})

    chain = panel_for_profile(cfg, profile)

    assert chain == expected_chain, (
        f"{profile}: the chain is {chain!r}; the design's is the panel in declared order "
        f"{panel!r} then the escalations that name a new build, de-duplicated by build "
        f"identity — {expected_chain!r} (CT-CONF-23 row 2)"
    )
    assert chain[: len(panel)] == panel, f"{profile}: the panel is not the chain's head"
    assert chain[len(panel):] == (surviving,), f"{profile}: an escalation seat survived the dedup"

    for ref in chain:
        assert ref.is_resolved(), f"{profile}: {ref.role} ref is not resolved: {ref.build_id!r}"
        assert ref.build_form() == expected_form, (
            f"{profile}: a {ref.build_form()} build on {profile!r}, which requires "
            f"{expected_form} (CT-CONF-03 on this surface)"
        )
    network_guard.assert_no_network()


# --- CT-CONF-23 row 3 — the empty panel -------------------------------------------------------


@pytest.mark.parametrize("with_escalations", [True, False])
def test_tc_conf_c23_row3_an_empty_panel_raises_naming_the_profile(with_escalations, network_guard):
    """Row 3 — an empty `[[panel]]` raises `ConfigurationError` naming the profile, escalations
    present or not, **before any provider call** (the clause #687's acceptance criteria pin;
    Q-O7: the escalations are never a chain on their own).

    The escalations-present arm is the one worth spelling out: the config otherwise resolves,
    every ref in it is legal, and a fall-through would let M-AUTHOR author packages judged by
    models no panel ever ratified. The fixture guard keeps the arm honest about that.
    """
    panel_for_profile, conf = _surface()
    assert HOSTED_ESCALATION_A.is_resolved(), (
        "the escalation fixture must be resolved, or the case would confound the empty-panel "
        "refusal with a CT-CONF-03 resolution error"
    )
    escalations = (HOSTED_ESCALATION_A,) if with_escalations else ()
    cfg = hosted_cfg(**{"panel": (), "escalation_judge": escalations})

    with pytest.raises(conf.ConfigurationError, match="cloud-hosted") as refusal:
        panel_for_profile(cfg, "cloud-hosted")

    assert "cloud-hosted" in str(refusal.value), (
        f"the refusal must name the profile: {refusal.value!r}"
    )
    network_guard.assert_no_network()


# --- CT-CONF-03 on this surface — the floating-tag refusal ------------------------------------


@pytest.mark.parametrize("tag", ["latest", "stable", "main"])
@pytest.mark.parametrize("position", ["panel", "escalation_judge"])
def test_tc_conf_c23_a_floating_tag_is_refused_at_every_position_of_this_surface(tag, position):
    """`CT-CONF-03` on the new surface — "a ref carrying a floating tag (`:latest`) must fail".

    Each chain member is resolved per `CT-CONF-03` (the clause suite's closing sentence), so a
    floating tag is refused at the panel seat **and** at the escalation seat — a resolver that
    checked the panel and took the escalations on trust is exactly the shape this sweep
    exists to catch. `UnresolvedModelRefError` is asserted as the exact type: it is a
    deliberate **sibling** of `ConfigurationError` (never a chain), so a resolution that
    collapsed the two errors fails here.
    """
    panel_for_profile, conf = _surface()
    floating = conf.ModelRef(
        role="judge",
        provider="openrouter",
        build_id=f"meta-llama/llama-3.3-70b-instruct:{tag}",
        quantization=None,
    )
    assert not floating.is_resolved(), "the fixture is not floating, so the case asserts nothing"

    overrides = (
        {"panel": (floating,)}
        if position == "panel"
        else {"panel": (HOSTED_JUDGE,), "escalation_judge": (floating,)}
    )
    with pytest.raises(conf.UnresolvedModelRefError):
        panel_for_profile(hosted_cfg(**overrides), "cloud-hosted")