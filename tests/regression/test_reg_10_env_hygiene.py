"""`TC-REG-10` (TS-126, #537): test-support worlds leak no `HARNESS_*` variable.

Test plan 1.7 §6.9. The root cause (design 1.9 §5.2): `tests/support/e2e_world.py`'s
`WORLD_ENV` (DPI 72, semantic floor 0.0, random arm 0) and `tests/support/pipe_world.py`'s
corpus escalation budget were written to `os.environ` whenever a world was built without
`monkeypatch`, and never restored. Every later test in the process inherited them, which is
how TC-INGEST-02/25/28/39, ADV-07 and TC-ORCH-36 came to fail by test order, and why the
gate's `test_ct_ingest_v4_halting` cases flaked.

Arm (a) builds each world without `monkeypatch` and asserts the builder's writes are undone
by `restore_world_env`, the call the suite root makes after every test. Arm (b) is the
suite-root guard in `tests/conftest.py` (the `pytest_runtest_setup`/`pytest_runtest_teardown` hooks, which also reset every world write to its test-start value), which runs around every test in
the tree. The case here checks the guard is wired and that it restores a stray write.
"""

from __future__ import annotations

import os

import pytest

from tests.support.env_hygiene import harness_env_snapshot, restore_world_env, set_world_env

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("builder", ["synth_world", "replay_world", "jev_replay_world"])
def test_tc_reg_10_a_a_world_built_without_monkeypatch_leaves_no_knob_behind(builder, tmp_path):
    from tests.support import pipe_world
    from tests.support.e2e_world import SynthWorld

    before = harness_env_snapshot()
    if builder == "synth_world":
        world = SynthWorld(tmp_path / "d", tmp_path / "fx", n_submissions=3)
    elif builder == "replay_world":
        world = pipe_world.replay_world(tmp_path / "d")
    else:
        world = pipe_world.jev_replay_world(tmp_path / "d")
    try:
        during = harness_env_snapshot()
        assert during != before, (
            f"{builder} set no knob at all, so this case cannot tell a restoring builder from a "
            "leaking one — the fixture it guards has changed"
        )
    finally:
        world.store.close()
    restored = restore_world_env()
    after = harness_env_snapshot()
    assert restored, f"{builder} recorded nothing to restore though it set {sorted(set(during) - set(before))}"
    assert after == before, (
        f"{builder} leaked HARNESS_* variables after restore: "
        f"{sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))}"
    )


def test_tc_reg_10_a_a_monkeypatched_world_records_nothing(tmp_path, monkeypatch):
    """With `monkeypatch`, pytest owns the restore and the registry stays empty."""
    set_world_env("HARNESS_INGEST_DPI", "72", monkeypatch)
    assert restore_world_env() == []
    assert os.environ["HARNESS_INGEST_DPI"] == "72"  # monkeypatch undoes it at teardown


def test_tc_reg_10_b_the_suite_root_guard_is_active(request):
    """The guard runs around this very test: the setup hook snapshotted HARNESS_* for it."""
    assert hasattr(request.node, "_harness_env_before"), (
        "tests/conftest.py's pytest_runtest_setup hook took no HARNESS_* snapshot: nothing "
        "reports a leaked variable between tests"
    )
