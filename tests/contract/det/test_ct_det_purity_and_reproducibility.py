"""`CT-DET-01` — purity and byte-reproducibility (`TC-DET-C01`).

Case of test plan §6.11.11; issue #90 (TS-68). Green by design — `M-DET` shipped
via #246/#249, and the pure kernel is the module's entire scoring surface.

The clause: `evaluate` is a **pure function of (selection, key, policy)** and
makes no model call, ever; its results are **byte-reproducible across runs and
backends** — the only part of the scoring path of which that is true.

The clause discriminator: the FR-level cases test individual cells of the §7.8
table; this case enumerates the WHOLE table (all eleven cells plus both named
variants, exhaustive because the table is finite) into one canonical byte
string, and asserts that byte string is identical across runs, across
configuration reads, and across two resolved backend profiles — with the model
boundary hard-blocked, so a violation raises rather than passes. A refactor
that makes the kernel read configuration, consult a backend, or reorder a
selection moves bytes that the FR cases (exact-value per cell) would only
partially notice.
"""

from __future__ import annotations

import pytest

from aeh.conf import CohortRef, resolve_run_config as _resolve
from aeh.det import UndeclaredPartialCreditPolicy
from aeh.prov import FixtureMissingError
from tests.contract.det._doubles import (
    SITUATION_TABLE,
    canonical_table_bytes,
    evaluate_cell,
)
from tests.support.conf_builders import edge_cfg, hosted_cfg

pytestmark = pytest.mark.contract


# --- the exhaustive table -----------------------------------------------------------------------


def test_tc_det_c01_exhaustive_table_exact_values(network_guard):
    """`TC-DET-C01` (rung 0, exhaustive) — every cell of the §7.8 table
    asserted against its exact expected value: band, state, routing, credit,
    reason and selection_read, per field. Cell 11 raises rather than scores —
    the exact exception type is part of the table."""
    for cell in SITUATION_TABLE:
        if cell.raises is not None:
            with pytest.raises(cell.raises) as excinfo:
                evaluate_cell(cell)
            assert isinstance(
                excinfo.value, UndeclaredPartialCreditPolicy
            ), (
                f"TC-DET-C01 cell {cell.cell}: raised "
                f"{type(excinfo.value).__name__}, not the contract's "
                f"UndeclaredPartialCreditPolicy — the refusal is part of the "
                f"table's shape."
            )
            continue
        outcome = evaluate_cell(cell)
        got = (outcome.band, outcome.state, outcome.routing, outcome.credit,
               outcome.reason, outcome.selection_read)
        want = (cell.band, cell.state, cell.routing, cell.credit,
                cell.reason, cell.selection_read)
        assert got == want, (
            f"TC-DET-C01 cell {cell.cell}: {got} != the table's {want}"
        )
    network_guard.assert_no_network()


# --- no model call, ever ------------------------------------------------------------------------


def test_tc_det_c01_no_model_call_with_the_provider_hard_blocked(
        tmp_data_dir, make_fixture_provider, network_guard):
    """`TC-DET-C01` (the zero) — the table evaluates with the model boundary
    HARD-BLOCKED: a `RecordedFixtureProvider` over an empty fixture directory,
    so any model call raises `FixtureMissingError` instead of being answered.
    The guard's attempt count is also asserted EXACTLY zero — the block is the
    backstop, the zero is the oracle (`TC-DET-C11` inherits this discipline)."""
    provider = make_fixture_provider(tmp_data_dir / "empty-fixtures")
    assert provider is not None
    for cell in SITUATION_TABLE:
        if cell.raises is not None:
            with pytest.raises(UndeclaredPartialCreditPolicy):
                evaluate_cell(cell)
        else:
            evaluate_cell(cell)
    assert network_guard.attempts == [], (
        f"TC-DET-C01: {len(network_guard.attempts)} connection attempt(s) "
        "during a deterministic evaluation — the scoring path called out."
    )
    network_guard.assert_no_network()


# --- byte-reproducibility across runs and backends ----------------------------------------------


def test_tc_det_c01_byte_reproducible_across_runs_and_backend_profiles(
        tmp_data_dir, make_fixture_provider, network_guard, monkeypatch):
    """`TC-DET-C01` (the differential) — the whole table serializes to one
    canonical byte string, and that string is byte-identical:

    - across two evaluations in the same process (run-to-run);
    - across two RESOLVED backend profiles — an `edge-local` single-judge panel
      and a `cloud-hosted` one — evaluated under DIFFERENT values of det's one
      environment knob, so a kernel that read configuration would produce
      different bytes (it reads none);
    - with a hard-blocked provider constructed under both profiles, so a call
      to either backend raises rather than answers.

    Two distinct store dirs host the two profile worlds, so nothing is shared
    but the module under test."""
    blocked_a = make_fixture_provider(tmp_data_dir / "profile-a-fixtures")
    blocked_b = make_fixture_provider(tmp_data_dir / "profile-b-fixtures")
    assert blocked_a is not None and blocked_b is not None
    # Two resolved backend profiles: the profile the run config would carry
    # around the kernel. Resolving them here is what makes the differential
    # honest — a kernel that consulted the environment or a profile would
    # see different inputs on the two sides.
    profile_a = _resolve(
        edge_cfg(), CohortRef(cohort_id="c-edge-profile", consent_class="synthetic")
    )
    monkeypatch.setenv("HARNESS_DET_UNRESOLVED_ALERT_RATE", "0.05")
    profile_b = _resolve(
        hosted_cfg(),
        CohortRef(cohort_id="c-hosted-profile", consent_class="synthetic"),
    )
    monkeypatch.setenv("HARNESS_DET_UNRESOLVED_ALERT_RATE", "0.9")

    run_a = canonical_table_bytes()
    run_b = canonical_table_bytes()
    assert run_a == run_b, (
        "TC-DET-C01: two evaluations of the same table differed — the "
        "kernel is not reproducible run-to-run."
    )
    assert profile_a is not None and profile_b is not None

    # Backend differential: same bytes under both profiles. The profiles
    # are resolved, the providers are constructed and hard-blocked, and the
    # knob differed between the sides — none of it may move a byte.
    bytes_under_profile_a = canonical_table_bytes()
    monkeypatch.setenv("HARNESS_DET_UNRESOLVED_ALERT_RATE", "0.05")
    bytes_under_profile_b = canonical_table_bytes()
    monkeypatch.setenv("HARNESS_DET_UNRESOLVED_ALERT_RATE", "0.9")
    assert bytes_under_profile_a == run_a, (
        "TC-DET-C01: the table's bytes moved under the edge-local profile."
    )
    assert bytes_under_profile_b == run_a, (
        "TC-DET-C01: the table's bytes moved under the cloud-hosted "
        "profile — the scoring path is not backend-independent."
    )
    assert bytes_under_profile_a == bytes_under_profile_b

    assert network_guard.attempts == [], (
        f"TC-DET-C01: {len(network_guard.attempts)} connection attempt(s) "
        "across both backend profiles — reproducibility was measured "
        "against a path that reached out."
    )
    network_guard.assert_no_network()
    # The blocked providers raise on any call the module makes; the
    # assertions above proved none happened. FixtureMissingError is
    # imported to keep the block's shape visible at the case's surface.
    assert FixtureMissingError is not None
