"""`TC-ORCH-C25`…`C28` and `TC-ORCH-C08` — the refusal, escalation-key, alert-name and
taxonomy-pause clauses (§6.11.7, `CT-ORCH-25/26/27/28`).

| Case | Clause | The violation it catches |
|---|---|---|
| `C25` | a bad grade policy refuses before the run exists | the check moving after the run insert |
| `C26` | the escalation key names its run | the key dropping `run_id`, so RB's escalation is swallowed as RA's duplicate |
| `C27` | the alert vocabulary is closed at five | an alert renamed, or a sixth added without a contract bump |
| `C28` | a provider outage pauses rather than propagates | the exception escaping `progress()`, or the unit left `leased` until its lease expires |
| `C08` | re-specified: the three-element key is the key | — |

**Each of these has an `FR`-level sibling** (`TC-ORCH-44`, `-47`, `-43`), and the clause cases
differ from them deliberately. The FR case asks "does the requirement hold"; the clause case
asks "does it hold *for the reason the contract names*, in a way a plausible refactor cannot
quietly remove". So C25 counts rows in **every** tier rather than one, C26 asserts the two runs'
escalations coexist rather than that one of them exists, C27 asserts set **equality** rather
than membership, and C28 asserts `attempts` is unchanged rather than that the run paused.

**C27's discriminator is renaming.** An alert set asserted by membership survives
`orch_cost_near_ceiling` becoming `orch_cost_warning`: the new name is present, the old one is
simply never checked. Every dashboard keyed on the old name goes quiet, and nothing fails.
Equality is what makes a rename a decision.

**Isolation: rung 1 for C27, rung 2 for the rest.**
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.orch import (
    ALERT_CACHE_COLLAPSE,
    ALERT_COST_NEAR_CEILING,
    ALERT_CRITERION_BREAKER,
    ALERT_ESCALATION_RATE,
    ALERT_RUN_PAUSED,
    RUN_ALERT_NAMES,
    Orchestrator,
    StageOutcome,
    WorkLedgerError,
)
from aeh.pkg import (
    GateRule,
    GradePolicy,
    PackageCatalog,
    PackageError,
    PackageIntegrityError,
)
from aeh.prov import BuildChangedError, ProviderUnavailableError
from aeh.store import Statement, open_store
from tests.support.orch_run import (
    ORCH_COHORT_ID,
    orch_cfg,
    seed_cohort,
    seed_documents,
    seed_package,
    seed_run,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]

SUBMISSION = "S1"
CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)

#: `TC-ORCH-44` arm (e)'s four undeclared ids.
MISSING_IDS = ("C7", "C8", "C9", "C10")

_ESCALATIONS = Statement(
    "SELECT run_id, COUNT(*) AS n FROM work_unit WHERE origin = 'escalation' "
    "AND submission_id = :s AND criterion_id = :c GROUP BY run_id ORDER BY run_id"
)
_UNITS = Statement(
    "SELECT status, attempts FROM work_unit WHERE run_id = :r AND stage = 'extract'"
)
_RUN = Statement("SELECT status FROM run WHERE run_id = :r")


class _StubProvider:
    def estimate_cost(self, unit: Any) -> None:  # noqa: ARG002 — the seam's shape
        return None

    def complete(self, payload: Any, model_ref: Any = None, params: Any = None) -> Any:
        raise AssertionError("this suite's executors answer without a model call")


# --- TC-ORCH-C25 -------------------------------------------------------------------------------


def _row_counts(data_dir) -> dict[str, int]:
    """Every row of every table in every tier file — the snapshot C25 compares.

    Whole-store rather than the `run` table alone: the clause is that the refusal happens
    before ANYTHING is written, and a check that moved after the run insert would also have
    written whatever the insert cascades into.
    """
    counts: dict[str, int] = {}
    for path in sorted(data_dir.rglob("*.sqlite")):
        connection = sqlite3.connect(str(path))
        try:
            tables = [
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            ]
            for table in tables:
                key = f"{path.name}:{table}"
                counts[key] = connection.execute(
                    f'SELECT COUNT(*) FROM "{table}"'  # noqa: S608 — name from sqlite_master
                ).fetchone()[0]
        finally:
            connection.close()
    return counts


def test_tc_orch_c25_a_bad_policy_refuses_with_the_right_type_and_writes_nothing_anywhere(
    tmp_data_dir,
):
    """`PackageIntegrityError`, `isinstance PackageError`, all four ids, zero rows in EVERY tier.

    `TC-ORCH-44` asserts the run-table count. The clause is stronger: the check runs before the
    run row exists, so **nothing anywhere** may change. A check that moved after the insert
    would leave a run row and whatever that cascades into, and the refusal would then be a
    rollback nobody verified.
    """
    store = open_store(tmp_data_dir)
    try:
        seed_cohort(store, (SUBMISSION,))
        version = seed_package(
            store,
            (
                {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
                {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
            ),
        )
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        catalog.set_grade_policy(
            version,
            GradePolicy(
                combination="weighted_sum",
                weights=(("C7", 1.0), ("C8", 1.0), ("C9", 1.0)),
                gate=GateRule(criterion_id="C10", minimum=0.5),
            ),
        )
        orchestrator = Orchestrator(store)
    finally:
        store.close()

    before = _row_counts(tmp_data_dir)

    with pytest.raises(PackageIntegrityError) as caught:
        store = open_store(tmp_data_dir)
        try:
            Orchestrator(store).create_run(ORCH_COHORT_ID, version, orch_cfg())
        finally:
            store.close()

    assert isinstance(caught.value, PackageError), (
        "the refusal is outside the package error family, so a caller catching PackageError "
        "meets it as an orchestrator fault instead of a package that needs fixing"
    )
    assert getattr(caught.value, "retryable", None) is False
    message = str(caught.value)
    for name in MISSING_IDS:
        assert f"'{name}'" in message, (
            f"the refusal does not name {name!r}: {message!r}. An operator fixing the package "
            "needs every offending id — one per attempt turns one edit into four"
        )

    after = _row_counts(tmp_data_dir)
    changed = sorted(
        key for key in set(before) | set(after) if before.get(key) != after.get(key)
    )
    assert changed == [], (
        f"the refused create_run changed {changed}. FR-ORCH-31's check runs BEFORE the run "
        "row exists, so a refusal leaves the store byte-for-byte as it was (CT-ORCH-25)"
    )
    assert orchestrator is not None


# --- TC-ORCH-C26 and TC-ORCH-C08 ---------------------------------------------------------------


@pytest.fixture
def two_runs(tmp_data_dir):
    """RA and RB, both open over one cohort, each holding the pair's score panel."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_a, version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        orchestrator.enumerate_units(run_a)
        run_b = orchestrator.create_run(ORCH_COHORT_ID, version, orch_cfg())
        orchestrator.enumerate_units(run_b)
        yield store, orchestrator, run_a, run_b
    finally:
        store.close()


def _escalations(store: Any) -> dict[str, int]:
    return {
        str(row["run_id"]): int(row["n"])
        for row in store.cohort(ORCH_COHORT_ID).query(
            _ESCALATIONS, s=SUBMISSION, c=CRITERION
        )
    }


def test_tc_orch_c26_two_runs_escalations_coexist_as_distinct_units(two_runs):
    """RA's and RB's escalations for the same pair are separate units.

    The clause's own case, and the one `TC-ORCH-47` arm (a) cannot reach: that arm escalates
    one run and checks the other is untouched, which an implementation keyed on
    `(submission, criterion)` alone would also pass — it simply has nothing to collide with
    yet. Escalating **both** is what makes the collision observable: with `run_id` out of the
    work id, RB's units are byte-identical to RA's and `INSERT OR IGNORE` drops them.
    """
    store, orchestrator, run_a, run_b = two_runs

    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        orchestrator.enqueue_escalation(tx, (run_a, SUBMISSION, CRITERION))
    after_a = _escalations(store)

    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        orchestrator.enqueue_escalation(tx, (run_b, SUBMISSION, CRITERION))
    after_both = _escalations(store)

    assert after_a.get(run_b, 0) == 0
    assert after_both.get(run_a, 0) == after_a.get(run_a, 0), (
        f"escalating RB changed RA's units: {after_a} became {after_both}"
    )
    assert after_both.get(run_b, 0) > 0, (
        f"RB's escalation wrote no unit: {after_both}. Its units carry the same "
        "(submission, criterion, judge) as RA's, so a work id without run_id makes them "
        "collide and INSERT OR IGNORE silently drops the second run's widened panel"
    )
    assert after_both[run_a] == after_both[run_b], (
        f"the two runs widened by different amounts: {after_both}. Same pair, same ladder"
    )


def test_tc_orch_c08_the_three_element_key_is_the_key(two_runs):
    """`TC-ORCH-C08` re-specified: the three-element key names its run; the two-element form
    resolves only when exactly one open run holds the pair, and raises otherwise.

    The base case asserted the two-element key, which was the surface before `FR-ORCH-34`. Both
    halves are here because the deprecated form is still supported — the re-specification is
    about which one is *the* key, not about removing the other.
    """
    store, orchestrator, run_a, run_b = two_runs

    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        reports = orchestrator.enqueue_escalation(tx, (run_a, SUBMISSION, CRITERION))
    assert len(reports) == 1
    assert _escalations(store).get(run_b, 0) == 0, (
        "the run-scoped key widened a run it does not name"
    )

    with pytest.raises(WorkLedgerError) as caught:
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            orchestrator.enqueue_escalation(tx, (SUBMISSION, CRITERION))
    message = str(caught.value)
    assert run_a in message and run_b in message, (
        f"the ambiguity refusal names neither run: {message!r}"
    )


# --- TC-ORCH-C27 -------------------------------------------------------------------------------


def test_tc_orch_c27_the_alert_vocabulary_is_exactly_five_names():
    """`RUN_ALERT_NAMES` equals the five declared alerts — set **equality**, not membership.

    The discriminator is renaming. A membership check survives `orch_cost_near_ceiling`
    becoming `orch_cost_warning`: the new name is there, the old one is simply never asked
    about, every dashboard keyed on it goes quiet, and nothing fails. Equality makes a rename
    a decision somebody takes rather than one that happens.
    """
    declared = {
        ALERT_ESCALATION_RATE,
        ALERT_CRITERION_BREAKER,
        ALERT_COST_NEAR_CEILING,
        ALERT_CACHE_COLLAPSE,
        ALERT_RUN_PAUSED,
    }

    assert set(RUN_ALERT_NAMES) == declared, (
        f"the alert vocabulary is {sorted(RUN_ALERT_NAMES)}; the contract names "
        f"{sorted(declared)} (CT-ORCH-27, OBS-12)"
    )
    assert len(RUN_ALERT_NAMES) == 5, (
        f"there are {len(RUN_ALERT_NAMES)} alerts, not five. A sixth is a contract bump, not "
        "an addition"
    )
    assert RUN_ALERT_NAMES == tuple(dict.fromkeys(RUN_ALERT_NAMES)), (
        f"the alert tuple repeats a name: {RUN_ALERT_NAMES}"
    )


def test_tc_orch_c27_a_progress_report_exposes_only_declared_alert_names(tmp_data_dir):
    """OBS-12 through `progress()`: whatever alerts a report carries are drawn from the five.

    The vocabulary check above is about the constant; this is about the surface that uses it.
    An alert assembled by string formatting at the call site would satisfy the constant and
    still put an undeclared name in front of an operator.
    """
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        orchestrator.enumerate_units(run_id)
        orchestrator.start(run_id)
        report = orchestrator.progress(run_id)
    finally:
        store.close()

    alerts = list(getattr(report, "alerts", ()) or ())
    undeclared = [
        alert for alert in alerts
        if not any(str(alert).startswith(name) for name in RUN_ALERT_NAMES)
    ]
    assert undeclared == [], (
        f"progress() reported alerts outside the declared vocabulary: {undeclared}. The five "
        f"names are {sorted(RUN_ALERT_NAMES)}"
    )


# --- TC-ORCH-C28 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error,label",
    (
        (ProviderUnavailableError("the endpoint is gone"), "ProviderUnavailable"),
        (BuildChangedError("answering as a different build"), "BuildChanged"),
    ),
    ids=("provider-unavailable", "build-changed"),
)
def test_tc_orch_c28_a_taxonomy_error_pauses_without_propagating_or_striking(
    tmp_data_dir, error, label
):
    """`progress()` returns, the run pauses, the unit is `pending`, `attempts` is unchanged.

    All four together, because each rules out a different plausible implementation:

    * **returns** — the exception must not escape, or `M-PIPE`'s loop reads a composition
      fault and exits non-zero over a condition worth waiting out;
    * **paused** — the run stops rather than burning the batch against a dead endpoint;
    * **pending** — the unit is not left `leased` until its lease expires, which would idle it
      for `ORCH_LEASE_SECONDS` after the provider came back;
    * **`attempts` unchanged** — §8.3's "plausible tidy-up"
      (`except ProviderError as e: self._strike(unit, e); raise`) keeps the pause and restores
      the strike. Only this assertion catches it, and three strikes quarantine a unit whose
      only problem was the provider's.
    """
    class _RaisingExecutor:
        def execute(self, unit: Any, governed: Any) -> StageOutcome:  # noqa: ARG002
            raise error

    store = open_store(tmp_data_dir)
    try:
        seeder, run_id, _version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        seed_documents(store, (SUBMISSION,))
        seeder.enumerate_units(run_id)
        probe = Orchestrator(
            store, executor=_RaisingExecutor(), provider=_StubProvider()
        )
        probe.start(run_id)

        report = probe.progress(run_id)
        assert report is not None, (
            "progress() returned None; CT-ORCH-28 requires a ProgressReport so the caller can "
            "read that the run paused"
        )

        cohort = store.cohort(ORCH_COHORT_ID)
        assert str(cohort.query(_RUN, r=run_id)[0]["status"]) == "paused", (
            f"the run did not pause on a {label} error"
        )
        units = [dict(row) for row in cohort.query(_UNITS, r=run_id)]
        assert units, "the run enumerated no extract unit"
        for unit in units:
            assert unit["status"] == "pending", (
                f"the unit is {unit['status']!r}; a unit the provider never answered returns "
                "to pending rather than idling under a lease until it expires"
            )
            assert unit["attempts"] == 0, (
                f"the unit was charged {unit['attempts']} attempt(s) for the PROVIDER's "
                "condition. This is the assertion §8.3's tidy-up breaks while the pause "
                "assertion above still passes"
            )
    finally:
        store.close()
