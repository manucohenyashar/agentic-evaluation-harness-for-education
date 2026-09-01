"""`panel_build_ref` — the key every `package_validation` row is filed under.

Case: `TC-CONF-05` (`FR-CONF-05`, P0), test plan §5.1. Rung 0.
Oracle: **exact value against a committed reference hash.**

Why a committed literal rather than `assert pbr(p) == pbr(p)`: `CT-CONF-07` promises "equal
panels produce equal refs **across processes and machines**". A self-comparison holds for any
function, including one seeded with `id()` or `hash()` — which in CPython varies per process
under `PYTHONHASHSEED`. The literals below were computed in a different process, on a different
working directory, at authoring time. A ref that is stable only within one run fails here.

`FR-CONF-05` belongs to issue #5, which owns the *documented* canonical ordering. The formula is
already fixed by issue #4 — `RunConfig` cannot carry the field otherwise (`CT-CONF-C02` pins the
field set at twelve) — so this case is green now, and these literals are what #5 must not
silently change: every stored `package_validation` primary key depends on them.
"""

from __future__ import annotations

import pytest

from aeh.conf import ModelRef, compute_panel_build_ref, resolve_run_config
from tests.support.conf_builders import SYNTHETIC_COHORT, edge_cfg

# A three-judge panel. Odd by contract (`CT-CONF-02`: 1, 3 or 5) and three rather than one
# because ordering cannot be tested with a single member.
J1 = ModelRef("judge", "ollama", "/models/llama-3.3-70b.gguf@sha256:aaaa", "q4")
J2 = ModelRef("judge", "ollama", "/models/qwen-2.5-72b.gguf@sha256:bbbb", "q4")
J3 = ModelRef("judge", "ollama", "/models/mistral-large.gguf@sha256:cccc", "q4")

# The same panel differing in exactly one respect, one respect at a time.
J2_OTHER_QUANTIZATION = ModelRef("judge", "ollama", "/models/qwen-2.5-72b.gguf@sha256:bbbb", "q8")
J2_OTHER_PROVIDER = ModelRef("judge", "vllm-mlx", "/models/qwen-2.5-72b.gguf@sha256:bbbb", "q4")

#: Committed references. Computed out-of-process; see the module docstring.
REFERENCE_PANEL_BUILD_REF = "pbr:ae9f75ccf5402f5d80003788883ffb46"
REFERENCE_SOLO_PANEL_BUILD_REF = "pbr:4f86e8328a1e659372f81994fef84fcf"


def test_tc_conf_05_the_reference_panel_hashes_to_its_committed_value():
    """The exact-value oracle. If this line has to be edited, every `package_validation` row
    already on disk is keyed under a ref the code no longer produces — which is why
    `FR-CONF-05`'s Compatibility note calls a change to this hash **breaking**."""
    assert compute_panel_build_ref((J1, J2, J3)) == REFERENCE_PANEL_BUILD_REF


def test_tc_conf_05_the_ref_computed_during_resolution_is_the_same_value():
    """The field on `RunConfig` carries the same hash the free function produces — a resolver
    computing it a second, subtly different way is a silent key split."""
    config = resolve_run_config(edge_cfg(panel=(J1, J2, J3)), SYNTHETIC_COHORT)

    assert config.panel_build_ref == REFERENCE_PANEL_BUILD_REF
    assert compute_panel_build_ref(config.panel) == config.panel_build_ref


def test_tc_conf_05_a_single_member_panel_hashes_to_its_committed_value():
    """A second committed reference at the other end of `CT-CONF-02`'s size range, so the
    literal above is not the only input the encoding is pinned on."""
    assert compute_panel_build_ref((J1,)) == REFERENCE_SOLO_PANEL_BUILD_REF


@pytest.mark.parametrize(
    "panel,why",
    [
        pytest.param((J3, J2, J1), "reversed", id="different_order"),
        pytest.param((J2, J1, J3), "first two swapped", id="different_order_adjacent_swap"),
        pytest.param((J1, J2_OTHER_QUANTIZATION, J3), "q8 not q4", id="different_quantization"),
        pytest.param((J1, J2_OTHER_PROVIDER, J3), "vllm-mlx not ollama", id="different_provider"),
    ],
)
def test_tc_conf_05_the_ref_differs_for_every_change_of_build_quantization_or_order(panel, why):
    """TC-CONF-05 — "differs for every build, quantization or provider change", plus order.

    Order is the one the plan singles out: `CT-CONF-C07` names sorting as the change most likely
    to be introduced as an optimization, and it would silently merge two distinct panels under
    one key. Both an adjacent swap and a full reversal are here, because a canonicalization that
    sorts would collapse both while a buggy hash that only mixed in the first element would
    survive the reversal alone.
    """
    assert compute_panel_build_ref(panel) != REFERENCE_PANEL_BUILD_REF, why


def test_tc_conf_05_the_ref_is_stable_across_repeated_computation_within_a_process():
    """Weaker than the committed literals above and kept for a different reason: it fails on a
    ref that mixes in a per-call source such as a timestamp or a fresh `uuid4`, which the
    literals would also catch but only after someone regenerated them."""
    assert compute_panel_build_ref((J1, J2, J3)) == compute_panel_build_ref((J1, J2, J3))


def test_tc_conf_05_two_panels_with_the_same_members_in_a_different_order_do_not_collide():
    """The assertion stated as `CT-CONF-07` states it — pairwise inequality across all six
    orderings of the three-judge panel, rather than each against the reference. A hash that
    canonicalized by sorting passes every "differs from the reference" check that compares only
    against one baseline if the baseline happens to be the sorted order."""
    from itertools import permutations

    refs = {compute_panel_build_ref(order) for order in permutations((J1, J2, J3))}

    assert len(refs) == 6, "orderings collided: two distinct panels would share one key"
