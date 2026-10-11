"""`TC-CONF-39` — `panel_for_profile` (FR-CONF-33, package-authoring design delta §3.2; #705).

The §5.3 row pins the surface M-AUTHOR consumes, before M-AUTHOR exists to consume it:

- the chain is the named profile's `[[panel]]` refs in **declared order**, then the
  `[[escalation_judge]]` refs, **de-duplicated by build identity**;
- `dev-ci` resolves to its one judge — the width an authoring flow sees on the cheapest
  backend;
- an **empty panel raises** `ConfigurationError` naming the profile, with escalations present
  or not (Q-O7: escalations alone are never a chain);
- the resolution **writes no store rows** even with a real store open during it — proven by a
  row-count snapshot diff over the whole data directory, not a mock;
- **purity** — two calls over the same cfg return equal chains.

**Written ahead of implementation: yes.** `panel_for_profile` is #687's story, so every body
opens with `require(...)`: red with `NotImplementedYet` naming #687 is the expected
state, and when #687 landed, the marker (never the test) and the `WRITTEN_AHEAD_BLOCKERS`
entry came off.

**Disclosed bets**, each reconcilable without touching what the cases assert:

1. `cfg` is the parsed mapping the rest of M-CONF's surface already takes — top-level keys for
   a single-profile mapping (`edge_cfg`/`hosted_cfg`) and a `profiles` table for a multi-profile
   file (`f_profiles`), with `[[escalation_judge]]` entries already converted to `ModelRef`s
   exactly as `[[panel]]` is (issue #705's notes; the raw-table form is M-PIPE's own key, a
   different surface).
2. The `backend_profile` argument names the profile and wins over `HARNESS_PROFILE`; both cfg
   shapes are exercised so a resolution that only understands one of them fails here visibly
   rather than silently.
"""

from __future__ import annotations

import importlib

import pytest

from aeh.store import open_store
from tests.support.conf_builders import (
    HOSTED_ESCALATION_A,
    HOSTED_ESCALATION_DUPLICATE,
    HOSTED_JUDGE,
    HOSTED_JUDGE_2,
    HOSTED_JUDGE_3,
    HOSTED_PANEL_3,
    hosted_cfg,
)
from tests.support.help_vocabulary import open_every_tier, snapshot_diff, store_snapshot
from tests.support.impl import CONF_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_package
from tests.support.profile_switching import FIXTURE_JUDGE, f_profiles


_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},)

#: The §5.3 row's 3-panel + 2-escalation configuration, with the duplicate: two escalations,
#: the second of which re-presents `HOSTED_JUDGE_3`'s build identity. The expected chain keeps
#: the panel whole and de-duplicates the escalation seat that names the same build.
HOSTED_CFG = hosted_cfg(
    **{
        "panel": HOSTED_PANEL_3,
        "escalation_judge": (HOSTED_ESCALATION_A, HOSTED_ESCALATION_DUPLICATE),
    }
)
HOSTED_EXPECTED_CHAIN = (HOSTED_JUDGE, HOSTED_JUDGE_2, HOSTED_JUDGE_3, HOSTED_ESCALATION_A)


# --- the chain -------------------------------------------------------------------------------


def test_tc_conf_39_dev_ci_resolves_to_exactly_its_single_judge():
    """`TC-CONF-39` — `dev-ci`'s chain is its one judge, and nothing else.

    `f_profiles(None)` carries no top-level `HARNESS_PROFILE`, so the chain can only come from
    the named profile's section — a resolver that fell back to the environment (or to another
    section) fails here before the width assertion is even reached.
    """
    panel_for_profile = require(CONF_MODULE, "panel_for_profile", issue="#687")

    chain = panel_for_profile(f_profiles(None), "dev-ci")

    assert chain == (FIXTURE_JUDGE,), (
        f"dev-ci's chain is {chain!r}; the §5.3 row expects exactly the profile's one judge "
        f"(FIXTURE_JUDGE), in declared order, with no escalation seat"
    )


def test_tc_conf_39_three_panel_and_two_escalations_yield_the_ordered_deduplicated_chain(
    network_guard,
):
    """`TC-CONF-39` — panel in declared order, then the surviving escalations, de-duplicated by
    build identity, not by object identity.

    The duplicate is `HOSTED_ESCALATION_DUPLICATE`, a re-constructed ref equal by build
    identity to panel member `HOSTED_JUDGE_3` (the fixture asserts the equality, so a fixture
    edit cannot silently turn this into a no-duplicate case). A dedup keyed on `is` keeps both
    mistral seats and produces a five-chain where the design's is four.

    "Escalations after panel" is asserted positionally: the panel occupies the first three
    seats in declared order and every escalation seat comes after all of them — a resolver that
    appended escalations interleaved or first fails the exact-chain equality below.
    """
    panel_for_profile = require(CONF_MODULE, "panel_for_profile", issue="#687")

    assert HOSTED_ESCALATION_DUPLICATE == HOSTED_JUDGE_3 and (
        HOSTED_ESCALATION_DUPLICATE is not HOSTED_JUDGE_3
    ), "the fixture must re-present a panel member's build identity as a distinct object"

    chain = panel_for_profile(HOSTED_CFG, "cloud-hosted")

    assert chain == HOSTED_EXPECTED_CHAIN, (
        f"the chain is {chain!r}; the design's is the panel in declared order "
        f"{HOSTED_PANEL_3!r} followed by the escalations that name a build the panel does "
        f"not ({HOSTED_ESCALATION_A!r}) — {HOSTED_EXPECTED_CHAIN!r}"
    )
    assert chain[: len(HOSTED_PANEL_3)] == HOSTED_PANEL_3, "the panel is not the chain's head"
    network_guard.assert_no_network()


# --- the empty panel -------------------------------------------------------------------------


def test_tc_conf_39_an_empty_panel_raises_naming_the_profile_even_with_escalations(network_guard):
    """`TC-CONF-39` / Q-O7 — an empty `[[panel]]` with escalations present raises
    `ConfigurationError` naming the profile, **before any provider call** (the clause #687's
    acceptance criteria pin).

    Falling through to the escalations is the attractive failure: the config otherwise
    resolves, every ref in it is legal, and M-AUTHOR would author packages judged by models no
    panel ever ratified. The guard asserts the escalation fixture itself is resolved, so a
    resolution error about an unresolved ref could never be mistaken for the empty-panel
    refusal this case pins.
    """
    panel_for_profile = require(CONF_MODULE, "panel_for_profile", issue="#687")
    conf = importlib.import_module(CONF_MODULE)
    escalations = (HOSTED_ESCALATION_A,)
    assert HOSTED_ESCALATION_A.is_resolved(), (
        "the escalation fixture must be resolved, or the case would confound the empty-panel "
        "refusal with a CT-CONF-03 resolution error"
    )

    with pytest.raises(conf.ConfigurationError, match="cloud-hosted") as refusal:
        panel_for_profile(hosted_cfg(**{"panel": (), "escalation_judge": escalations}), "cloud-hosted")

    assert "cloud-hosted" in str(refusal.value), (
        f"the refusal must name the profile so the operator sees which section is empty: "
        f"{refusal.value!r}"
    )
    network_guard.assert_no_network()


def test_tc_conf_39_an_empty_panel_with_no_escalations_raises_the_same_way(network_guard):
    """`TC-CONF-39` — the plain empty panel raises the same `ConfigurationError`; the clause
    does not depend on escalations existing to be violated."""
    panel_for_profile = require(CONF_MODULE, "panel_for_profile", issue="#687")
    conf = importlib.import_module(CONF_MODULE)

    with pytest.raises(conf.ConfigurationError, match="cloud-hosted"):
        panel_for_profile(hosted_cfg(**{"panel": (), "escalation_judge": ()}), "cloud-hosted")
    network_guard.assert_no_network()


# --- store silence ---------------------------------------------------------------------------


def test_tc_conf_39_a_resolution_with_the_store_open_writes_no_store_rows(
    tmp_data_dir, network_guard
):
    """`TC-CONF-39` — no cohort or run rows written (store snapshot).

    A real store, not a mock: seeded so the baseline is non-trivial, every tier opened and
    closed for the first row-count snapshot, then **reopened** — the resolution runs with the
    store open, as it would inside M-AUTHOR — and a second snapshot taken after the store
    drains. `snapshot_diff` compares row counts (and row hashes) of every table of every
    SQLite file under the data directory, so a write to any tier fails the case, not just the
    two tables the clause names. The baseline guards stand before the diff, so a snapshot that
    never saw the `run`/`cohort` tables cannot make `{}` pass vacuously.
    """
    panel_for_profile = require(CONF_MODULE, "panel_for_profile", issue="#687")

    store = open_store(tmp_data_dir)
    try:
        seed_cohort(store, ("SYN-001",))
        seed_package(store, _CRITERIA, package_id="pkg-pfp")
        # Open (and so migrate) every tier before the baseline, so a lazy migration on the
        # first ask cannot be mistaken for — or hidden among — the resolution's writes.
        open_every_tier(store, packages=["pkg-pfp"], cohorts=[ORCH_COHORT_ID])
    finally:
        store.close()
    before = store_snapshot(tmp_data_dir)
    assert [k for k in before if k.endswith("::run")], (
        "the baseline snapshot never saw the cohort tier's run table; a diff of {} would "
        "prove nothing"
    )
    assert [k for k in before if k.endswith("::cohort")], (
        "the baseline snapshot never saw the cohort table; a diff of {} would prove nothing"
    )

    store = open_store(tmp_data_dir)
    try:
        panel_for_profile(HOSTED_CFG, "cloud-hosted")
    finally:
        store.close()
    network_guard.assert_no_network()
    changed = snapshot_diff(before, store_snapshot(tmp_data_dir))

    assert changed == {}, (
        f"the resolution wrote store rows while the store was open — every table must be "
        f"row-identical (CT-CONF-23 row 2): {changed}"
    )


# --- purity ----------------------------------------------------------------------------------


def test_tc_conf_39_two_calls_return_equal_chains():
    """`TC-CONF-39` — purity: two calls over the same cfg return equal chains.

    The §5.3 oracle is equality of the chains themselves, not of a memoized cache hit: an
    implementation that cached only the second call's answer or appended a fresh escalation
    seat per call fails the comparison, and every consumer that assumes `panel_for_profile` is
    a pure projection of `cfg` fails with it.
    """
    panel_for_profile = require(CONF_MODULE, "panel_for_profile", issue="#687")

    first = panel_for_profile(HOSTED_CFG, "cloud-hosted")
    second = panel_for_profile(HOSTED_CFG, "cloud-hosted")

    assert first == second, (
        f"two calls over the same configuration returned different chains — {first!r} then "
        f"{second!r} (FR-CONF-33: the surface is pure in cfg)"
    )


# --- the floating-tag refusal rides on this surface too (CT-CONF-03) -------------------------


@pytest.mark.parametrize("tag", ["latest", "stable", "main"])
def test_tc_conf_39_a_panel_ref_carrying_a_floating_tag_is_refused_here_too(tag):
    """`TC-CONF-39` — each chain member is resolved per CT-CONF-03, so the floating-tag refusal
    the existing resolver enforces holds on this surface's panel seat as well.

    Swept over the tags `tests/contract/conf/test_ct_conf_surface_and_shape.py` sweeps, so the
    refusal cannot decay to a `latest`-only check. `UnresolvedModelRefError` is asserted as the
    exact type: it is a deliberate **sibling** of `ConfigurationError`, so a resolution that
    collapsed both into one error fails here.
    """
    panel_for_profile = require(CONF_MODULE, "panel_for_profile", issue="#687")
    conf = importlib.import_module(CONF_MODULE)
    floating = conf.ModelRef(
        role="judge",
        provider="openrouter",
        build_id=f"meta-llama/llama-3.3-70b-instruct:{tag}",
        quantization=None,
    )
    assert not floating.is_resolved(), "the fixture is not floating, so the case asserts nothing"

    with pytest.raises(conf.UnresolvedModelRefError):
        panel_for_profile(hosted_cfg(**{"panel": (floating,)}), "cloud-hosted")