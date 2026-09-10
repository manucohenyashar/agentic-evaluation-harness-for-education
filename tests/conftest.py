"""Shared fixtures and guards for the whole suite (TS-00, issue #1).

What is injected here is what test-plan §4.6 says must be injected: the clock, randomness and
the filesystem root. What is guarded here is the network. Everything else — SQLite, the blob
store — is real, per §4.2's one rule: *"Doubles are permitted only at the model boundary and
only for failure injection elsewhere."*
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

from tests.support.clock import EPOCH, FrozenClock
from tests.support.guards import SocketGuard
from tests.support.impl import (
    FIXTURE_PROVIDER_CLASS,
    PROVIDER_MODULE,
    require,
)
from tests.support.store_spy import StoreSpy

# TC-STORE-25: the tier migration chains are concatenated at import time, so every test runs
# with the full chain registered *before* any test module is collected — the convention the
# store enforces at the open site (`IncompleteMigrationChainError`, #234). #269's
# `_VersionOrderedRegistry` already makes each chain's *order* independent of import order;
# these imports are about *completeness* — without them a module importing only `aeh.store`
# would open files on a truncated chain, and the open site would refuse. Eleven modules
# contribute: `aeh.grade` owns Cohort's last migration (19, #103's
# `grade_superseded_at_and_append_only`; #101's `grade_submission_grade_key` was 18),
# `aeh.judge` the one before it (17, #80's
# `judge_verdict_response_columns`), `aeh.agg` the one before THAT (16, #92's
# `agg_confidence_columns`), `aeh.grade` also owns Durable's last (7, #103's
# `grade_audit_record_append_only`; #110's `review_label_store_columns` was 6),
# `aeh.integ` the one before THAT (5, #73's
# `integ_rate_dimensions`), `aeh.synth` the one before THAT (13, #97's
# `synth_narrative_key`), `aeh.orch` the one
# before THAT (12, #61's `orch_run_lifecycle`), `aeh.extract` the one
# before THAT (11), and `aeh.extract` pulls `aeh.ingest` and `aeh.orch`
# in transitively — every contributor is listed explicitly all the same.
import aeh.agg  # noqa: E402
import aeh.det  # noqa: E402
import aeh.extract  # noqa: E402
import aeh.grade  # noqa: E402
import aeh.ingest  # noqa: E402
import aeh.integ  # noqa: E402
import aeh.judge  # noqa: E402
import aeh.orch  # noqa: E402
import aeh.pkg  # noqa: E402
import aeh.review  # noqa: E402
import aeh.synth  # noqa: E402

# §4.6: seeded per concern, never the module-global. One constant so a reader can reproduce
# any shuffle-order failure by hand.
DEFAULT_SEED = 20260101

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- hypothesis profiles ------------------------------------------------------------------
# §4.7's command table names two by name: `pytest -q -m property --hypothesis-profile=ci` on
# every push (< 3 min) and `--hypothesis-profile=nightly` for the fuzz campaign (30 min).
#
# All three are `derandomize=True` except `nightly`. §4.6 pins reproducibility and already runs
# the unit suite shuffled, so a property case that fails only on some seeds is, by §4.6's flake
# policy, a P1 defect rather than an interesting result — and a derandomized profile is what
# makes "it failed for me but not for you" impossible to say. `nightly` is the one tier whose
# job *is* to find new inputs, so it draws fresh entropy.
#
# `function_scoped_fixture` is suppressed because `network_guard` is autouse: hypothesis would
# otherwise warn on every property test that the guard is not re-created per example. It does
# not need to be — the guard is stateless between examples and asserts across all of them.
_COMMON = {"suppress_health_check": [HealthCheck.function_scoped_fixture]}

settings.register_profile("default", max_examples=50, derandomize=True, **_COMMON)
settings.register_profile("ci", max_examples=200, derandomize=True, deadline=None, **_COMMON)
settings.register_profile("nightly", max_examples=2000, derandomize=False, deadline=None, **_COMMON)
settings.load_profile("default")


# --- the socket guard ---------------------------------------------------------------------
@pytest.fixture(autouse=True)
def network_guard(request: pytest.FixtureRequest):
    """Block and record outbound connections for every test that is not `live`.

    Autouse, because a guard you have to remember to ask for is a guard that is missing from
    the test that needed it most. `live`-marked tests stand it down: those are the nightly
    E2/E3 cases whose entire purpose is a real model call.

    Tests that assert "no model call is made" take this fixture explicitly and call
    `network_guard.assert_no_network()` — see `TC-PROV-13`.
    """
    if request.node.get_closest_marker("live"):
        yield None
        return

    guard = SocketGuard()
    guard.install()
    try:
        yield guard
    finally:
        guard.uninstall()


# --- the injected seams -------------------------------------------------------------------
@pytest.fixture(autouse=True)
def random_arm_deterministic(monkeypatch: pytest.MonkeyPatch):
    """Pin the escalation random arm's draw rate to 0 for every test (#60, `FR-ORCH-11`).

    The arm's draw is already deterministic — a hash over `(run_id, submission_id,
    criterion_id)` — but the run IDs most suites exercise are `uuid4`-minted per test, so
    at the default rate (0.07) roughly one judged pair in fourteen draws the widened
    panel and any test asserting an exact ledger shape ("5 submissions x 3 base units")
    flakes by construction. §4.6 puts randomness injection here at the suite root, and
    this is randomness: the default-rate arm stays OFF under test unless a test asks for
    it. A test exercising the arm itself overrides the pin — `monkeypatch.setenv
    ("HARNESS_ORCH_RANDOM_ARM_RATE", "0.07")` in the test body wins, because both this
    fixture and the test's write the same `monkeypatch` instance (the test's write lands
    second). Knob read at call time, so the pin holds without reimporting `aeh.orch`.
    """
    monkeypatch.setenv("HARNESS_ORCH_RANDOM_ARM_RATE", "0")


@pytest.fixture
def frozen_clock() -> FrozenClock:
    """A clock that moves only when the test moves it (§4.6: no `sleep`)."""
    return FrozenClock(start=EPOCH)


@pytest.fixture
def seeded_random() -> random.Random:
    """A per-test seeded `Random` instance. Never `random.seed()` — a module-global seed
    leaks between tests and makes shuffled runs (§4.6) non-reproducible."""
    return random.Random(DEFAULT_SEED)


@pytest.fixture
def store_spy() -> StoreSpy:
    """A write-audit hook for the 'writes nothing' clause cases. Not a store — real SQLite
    in `tmp_data_dir` is what store-touching cases use (§4.2, §4.10)."""
    return StoreSpy()


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """`HARNESS_DATA_DIR` for a single test.

    Per-test. Safe against `FR-STORE-09`'s check on the platform this suite runs on:
    Windows `%TEMP%` is ACL-scoped to the user, so no world-writable ancestor exists for
    the store's POSIX-mode check to find. On POSIX the same fixture would sit inside
    world-writable `/tmp` and every store case would red — which is the check working, not
    the fixture breaking; `TC-STORE-10`'s insecure-location probes drive the check's
    injectable `os_name`/`stat_fn` seams instead of relying on host paths.
    """
    data_dir = tmp_path / "data"
    (data_dir / "packages").mkdir(parents=True)
    (data_dir / "cohorts").mkdir(parents=True)
    (data_dir / "blobs").mkdir(parents=True)
    return data_dir


# --- the fast tier's model boundary --------------------------------------------------------
@pytest.fixture
def make_fixture_provider(tmp_path: Path):
    """The fast tier's `InferenceProvider`, as a factory.

    §4.2: `RecordedFixtureProvider` is a *shipped implementation*, not a test fake — it
    returns a stored response keyed by a hash of the fully-assembled request and raises
    `FixtureMissingError` rather than reaching the network. That is what makes the fast tier
    honest, so this binds the real class and fails loudly until it exists.

    A **factory** rather than the provider itself, deliberately: a fixture that raises
    produces a pytest *error* during setup, and an error asserts nothing about the
    requirement — the test never ran. Resolving inside the test body makes a missing
    implementation a legible *failure* on the test's own traceback instead
    (`/write-tests` step 3).
    """

    def _make(fixture_dir: Path | None = None):
        provider_cls = require(PROVIDER_MODULE, FIXTURE_PROVIDER_CLASS, issue="#18")
        target = fixture_dir or (tmp_path / "fixtures")
        target.mkdir(parents=True, exist_ok=True)
        return provider_cls(fixture_dir=target)

    return _make


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT
