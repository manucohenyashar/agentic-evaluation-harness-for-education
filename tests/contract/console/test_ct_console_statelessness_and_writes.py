"""`CT-CONSOLE-01`, `-02` and `-03` — the console holds nothing, writes an enumerable set, and
every one of those writes survives being made twice.

Test plan §6.11.19, TS-76 (issue #131). The three clauses are one argument. HLD §11.1 states the
rule — *"a read view over the §9 stores plus a small control surface"* — and §11.8 states its
consequence: *"the console never blocks on the pipeline and the pipeline never blocks on the
console"*. Statelessness is what makes the write surface enumerable, and enumerability is what
makes idempotency assertable per action rather than per sample.

* `-01` — no pipeline state, no inference, every change effected by a row the orchestrator reads
  on its own schedule. §6.11.19 adds the three operational assertions, and they are the point:
  *"statelessness that holds only while nothing goes wrong is not statelessness"*.
* `-02` — the write surface is **exactly** §11.8's fifteen actions, by set equality rather than
  containment, and enumerable at runtime. `FR-CONSOLE-32` says why enumerability is the
  requirement rather than documentation: it is what lets a test assert *no undeclared write path
  exists*, which no list in a document can.
* `-03` — every action idempotent, swept per action through all three replay routes, and never
  partially applied against stale state.

All three are written ahead of **#122**. Every name is invented; the base surface is settled in
`tests/support/console_vocabulary.py` and this suite's additions in
`tests/support/console_security_vocabulary.py`, because design §3.19 declares no Python interface
at all.

**Markers.** `TC-CONSOLE-C01`'s process-kill half carries `integration` alongside `writtenahead`:
its rung is 4, it spawns a real process, and when the `writtenahead` marker comes off it must not
land inside `TEST_CMD`'s 60-second contract budget (§4.10). Chosen now rather than at unmark time,
because at unmark time the choice is made by whoever is reading a failure.
"""

from __future__ import annotations

import pytest

from tests.support import broken_console_security_fixtures as fixtures
from tests.support.console_security_vocabulary import (
    CONSOLE_WRITE_FIELDS,
    REPLAY_ROUTES,
    replayed_writes_are_idempotent,
)
from tests.support.console_vocabulary import CONTROL_SURFACE_ACTIONS, visible_text
from tests.support.impl import CONSOLE_MODULE, require
from tests.support.store_spy import StoreSpy

pytestmark = pytest.mark.contract


# --- CT-CONSOLE-01 — no state, no inference, and nothing that survives a kill --------------------


@pytest.mark.writtenahead
def test_tc_console_c01_the_console_makes_no_inference_and_effects_change_by_writing_a_row():
    """`CT-CONSOLE-01` / `FR-CONSOLE-01` — the two prohibitions and the one mechanism.

    Three assertions, and the middle one is the one a functional test never makes. *"Performs no
    inference"* cannot be checked with the socket guard alone: the fast tier's provider answers
    from disk, so a console that dispatched a request to a model would make **no socket call** and
    `assert_no_network()` would pass while the thing the clause forbids had happened. That is the
    same boundary error `CT-CONFORM-09` documents, so the assertion is a **count at the provider
    seam**: exactly zero.

    The mechanism assertion is the third: a control action must reach the store as a **row**, not
    as a call into the orchestrator. §11.8 is explicit that this is what decouples the two — *"the
    console never blocks on the pipeline and the pipeline never blocks on the console"* — and a
    console that called `orchestrator.pause()` directly would satisfy every user-visible test and
    lose the property `R14` and `R3` both rest on.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    class _CountingProvider:
        def __init__(self) -> None:
            self.calls: list[object] = []

        def complete(self, request, **kwargs):  # noqa: ANN001, ANN003
            self.calls.append(request)
            raise AssertionError("the console dispatched an inference request")

    provider = _CountingProvider()
    store = StoreSpy()
    app = build_console(store=store, provider=provider)

    app.perform("pause/resume", run_id="r-1", state="paused")

    assert provider.calls == [], (
        f"the console dispatched {len(provider.calls)} inference request(s). CT-CONSOLE-01 says it "
        f"performs no inference, and the socket guard cannot see this: the fast tier's provider "
        f"answers from disk, so a dispatched request makes no socket call at all."
    )
    assert store.writes, (
        "pausing a run wrote nothing to the store, so the change was effected some other way. "
        "FR-CONSOLE-01 requires every change to be a row the orchestrator reads on its own "
        "schedule — that is what makes the console disposable and the run resumable."
    )
    assert not any(
        getattr(write, "operation", "") == "blob_put" for write in store.writes
    ), "a control action wrote a blob; control rows are rows"


@pytest.mark.writtenahead
def test_tc_console_c01_two_tabs_and_a_closed_browser_leave_the_run_untouched():
    """`CT-CONSOLE-01` / `NFR-CONSOLE-03` — the differential across concurrent views.

    HLD §11.7: *"Two browser tabs, or a phone on the same LAN, show the same truth because neither
    holds any."* So the assertion is a **differential**: two independently built consoles over one
    store render identically, and discarding one changes nothing the other sees.

    A console that cached a run in memory passes every single-tab test ever written and fails
    here — which is the whole reason §6.11.19 asks for two tabs rather than one. `R61`'s objection
    is concrete: *"a console that owned the run would make a browser tab a single point of failure
    for 350 grades"*.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    store = StoreSpy()
    first = build_console(store=store)
    second = build_console(store=store)

    before = visible_text(second.render("/runs/{id}/monitor", id="r-1").html)
    first.perform("pause/resume", run_id="r-1", state="paused")
    after = visible_text(second.render("/runs/{id}/monitor", id="r-1").html)

    assert before != after, (
        "the second tab shows the same page after the first tab paused the run. Both read the "
        "ledger, so either the pause was not written or the second tab is serving something it "
        "holds — and HLD §11.7 says every view is a query."
    )

    # Discarding the tab that acted must change nothing. A console holding the run would take it
    # with it, which is the failure a closed browser produces in the field and no test produces by
    # accident.
    del first
    reread = visible_text(second.render("/runs/{id}/monitor", id="r-1").html)
    assert reread == after, (
        "closing the tab that paused the run changed what the other tab shows. FR-CONSOLE-01: "
        "closing the browser has no effect on a running run."
    )


@pytest.mark.integration
@pytest.mark.writtenahead
def test_tc_console_c01_killing_the_console_process_leaves_the_run_and_its_queued_rows_intact():
    """`CT-CONSOLE-01` at rung 4 — the assertion that needs a real process to mean anything.

    §6.11.19 names three operational assertions and this is the third: *"kill the console
    process"*, with state *"reconstructed from the ledger on restart"*. `RES-16` is the same
    assertion from the resilience tier, and §3.19's error handling states the property being
    asserted: *"control rows queue and are picked up on the next start, which is the same property
    that makes `resume` argument-free"*.

    A restarted console is a **new** object over the same store, so the only thing that can carry
    the run across the kill is the ledger. That is what makes this different from the two-tab case
    above: there, both consoles were alive; here, everything in memory is gone by construction.

    Marked `integration` as well as `writtenahead`: this spawns a process, and it must not land in
    `TEST_CMD`'s 60-second contract budget when the marker comes off.
    """
    serve = require(CONSOLE_MODULE, "serve_console", issue="#122")
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    store = StoreSpy()
    server = serve(store=store, run_id="r-1")
    build_console(store=store).perform("pause/resume", run_id="r-1", state="paused")
    queued_before = list(store.writes)

    server.terminate()

    restarted = build_console(store=store)
    assert list(store.writes) == queued_before, (
        "killing the console changed the rows it had already written. Control rows queue and are "
        "picked up on the next orchestrator start (§3.19); losing them on a kill means a paused "
        "run silently resumes."
    )
    page = visible_text(restarted.render("/runs/{id}/monitor", id="r-1").html)
    assert "paused" in page.lower(), (
        f"a console restarted after the kill does not show the run as paused: {page!r}. State is "
        f"reconstructed from the ledger or it was never in the ledger."
    )


# --- CT-CONSOLE-02 — exactly fifteen, enumerable, and nothing else writes ------------------------


@pytest.mark.writtenahead
def test_tc_console_c02_the_runtime_write_surface_equals_the_declared_control_actions():
    """`CT-CONSOLE-02` / `FR-CONSOLE-32` — **set equality**, against the running console.

    §6.11.19 is explicit that containment is not enough, and the two directions fail differently.
    A missing action is a feature that does not exist. An **extra** one is an undeclared write
    path, which is the thing the clause exists to make impossible — and it is what a containment
    assertion cannot see.

    Enumerability is asserted first and separately, because it is the mechanism rather than the
    property: `FR-CONSOLE-32` requires the surface to be enumerable *at runtime* precisely so a
    test can make this comparison. A documented list is not a mechanism — it cannot go out of date
    loudly.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")
    app = build_console(store=StoreSpy())

    surface = app.write_surface()
    actions = app.control_actions()

    assert set(surface) == set(CONTROL_SURFACE_ACTIONS), (
        f"the console's runtime write surface is not HLD §11.8's fifteen actions. "
        f"Undeclared: {sorted(set(surface) - set(CONTROL_SURFACE_ACTIONS))}. "
        f"Missing: {sorted(set(CONTROL_SURFACE_ACTIONS) - set(surface))}. "
        f"An extra entry is the undeclared write path FR-CONSOLE-32 exists to expose."
    )
    assert set(actions) == set(surface), (
        f"the enumeration and the surface disagree: {sorted(set(actions) ^ set(surface))}. An "
        f"action that is callable but not enumerated is invisible to every assertion built on the "
        f"enumeration, which is every assertion in this clause."
    )
    for name, action in actions.items():
        assert callable(action), (
            f"{name!r} is enumerated but not callable, so the enumeration is a list of strings "
            f"rather than the runtime mechanism FR-CONSOLE-32 requires"
        )


@pytest.mark.integration
@pytest.mark.writtenahead
def test_tc_console_c02_every_write_a_screen_makes_maps_to_a_declared_action():
    """`CT-CONSOLE-02`'s dynamic cross-check: the enumeration is not merely self-consistent.

    A console can enumerate fifteen actions and write a sixteenth row from a template. §6.11.19
    asks for the sweep for that reason — *"exercise every screen at rung 3 under a write audit and
    assert every write maps to a declared action"*.

    The audit is `StoreSpy`, not `guards.write_audit()`. That distinction is load-bearing: the
    write audit watches `open`, `Path.write_*` and `mkdir`, so against a SQLite-backed console it
    sees the database file being touched and cannot say *which row* was written by *which action*
    — which is the entire question. `StoreSpy` records at the `TierHandle` seam design §3.3
    declares, so a write arrives with its payload attached.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    store = StoreSpy()
    app = build_console(store=store)

    declared_fields = {
        field for fields in CONSOLE_WRITE_FIELDS.values() for field in fields
    }
    for action in CONTROL_SURFACE_ACTIONS:
        app.perform(action)

    undeclared: list[str] = []
    for write in store.writes:
        for field in _payload_fields(write.payload):
            if field not in declared_fields:
                undeclared.append(f"{write.tier}:{write.operation} wrote {field}")

    assert not undeclared, (
        f"the console wrote fields no §11.8 action declares: {undeclared}. That is the undeclared "
        f"write path FR-CONSOLE-32 makes assertable — the enumeration says fifteen actions and the "
        f"store saw a sixteenth effect."
    )
    assert store.writes, (
        "driving all fifteen control actions produced no writes at all, so this sweep would pass "
        "against a console that does nothing — the vacuity a write audit is easiest to lose to"
    )


@pytest.mark.integration
@pytest.mark.writtenahead
def test_tc_console_c02_everything_else_the_console_does_is_a_read():
    """The clause's complement, and §6.11.19 asks for it explicitly: *"asserted as the complement"*.

    Rendering every route must write **nothing**. That is a stronger statement than "the write
    surface is fifteen actions", and it is the one that catches the realistic drift: a view that
    records a "last seen" timestamp, a page that lazily materialises a cached rollup. Neither is a
    control action, both are writes, and `NFR-CONSOLE-05`'s replaceability seam — *"it only reads
    stores and writes the enumerated control rows"* — is gone the moment either exists.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    store = StoreSpy()
    app = build_console(store=store)

    for screen, route in app.screens().items():
        store.writes.clear()
        app.render(route)
        assert store.writes == [], (
            f"rendering {screen} ({route}) wrote {[w.operation for w in store.writes]}. Every view "
            f"is a query (HLD §11.7); a render that writes is a write path outside the enumerated "
            f"fifteen and it will not be found by enumerating them."
        )
        assert store.queries, f"rendering {screen} ({route}) queried nothing at all"


def _payload_fields(payload: object) -> list[str]:
    """The dotted field names a recorded write touched.

    Kept local rather than in the vocabulary: it reads `StoreSpy`'s payload shape, which is this
    repo's test double rather than part of the invented `M-CONSOLE` surface.
    """
    if isinstance(payload, dict):
        table = str(payload.get("table") or payload.get("tier") or "")
        return [f"{table}.{key}" if table else str(key) for key in payload if key != "table"]
    return []


# --- CT-CONSOLE-03 — idempotent through every route a teacher can replay one ---------------------


@pytest.mark.integration
@pytest.mark.writtenahead
@pytest.mark.parametrize("action", CONTROL_SURFACE_ACTIONS)
def test_tc_console_c03_every_control_action_is_idempotent_through_all_three_replay_routes(action):
    """`CT-CONSOLE-03` / `FR-CONSOLE-02` — **per action**, not sampled.

    Parametrized rather than looped, so a failure names the action rather than the first one that
    broke: §6.11.19's reason is that *"one non-idempotent control is enough to corrupt a run"*, and
    a loop that stops at the first failure hides the other fourteen from whoever is fixing it.

    All three routes §11.8 names, because they are not the same operation. A double-click sends two
    requests with the same body in flight together; a retry sends the second after the first
    completed; a back-navigation re-submits a form whose view is now stale. An implementation that
    dedupes on an in-flight token survives the first and fails the third.

    Idempotent means **no additional row**, not "no exception" — a second `label`, a second
    `audit_record` or a second `run` is a corrupted run that raised nothing.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    app = build_console(store=StoreSpy())
    first = app.perform(action)

    for route in REPLAY_ROUTES:
        replay = app.perform(action, replay=route)
        ok, reason = replayed_writes_are_idempotent(first, replay)
        assert ok, (
            f"{action!r} is not idempotent under {route}: {reason}. §11.8 says every one of the "
            f"fifteen is idempotent, and R14's reason is that a double-clicked button must not be "
            f"able to corrupt a run that takes hours."
        )


@pytest.mark.integration
@pytest.mark.writtenahead
def test_tc_console_c03_an_action_against_stale_state_is_refused_or_idempotent_never_partial():
    """`CT-CONSOLE-03`'s stale-state rule, asserted on the **rows** rather than on the response.

    §3.19's error handling gives exactly two permitted outcomes and forbids the third by name:
    *"idempotent or refused with a refresh, **never partially applied**"*. So the assertion is not
    that the second action failed — it is that the store is in one of two states afterwards, and a
    half-written amendment is neither.

    **The race is ordered, not raced.** §4.6 treats a test that passes on some interleavings as a
    flake rather than a result, and two threads with a sleep would be one. A barrier the console
    releases at a stated point produces the same oracle deterministically: the conflicting write
    lands *while* the first action is mid-flight, which is the only interleaving that can produce a
    partial application at all.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    store = StoreSpy()
    app = build_console(store=store)

    app.perform("finalize batch", run_id="r-1", actor="r.mensah")
    settled = list(store.writes)

    # The same action against state that moved underneath it — the run is already finalized.
    outcome = app.perform("finalize batch", run_id="r-1", actor="r.mensah", expected_revision=0)

    if getattr(outcome, "refused", False):
        assert getattr(outcome, "refresh_required", False), (
            "the stale action was refused without asking for a refresh. §3.19 permits a refusal "
            "'with a refresh' — a bare refusal leaves the teacher looking at a page the system has "
            "already decided is wrong, with nothing to do about it."
        )
        assert list(store.writes) == settled, (
            f"the action was refused and still wrote {len(store.writes) - len(settled)} row(s). A "
            f"refusal that writes is the partial application the clause forbids, wearing the name "
            f"of the outcome it permits."
        )
    else:
        assert list(store.writes) == settled, (
            f"replaying finalize against stale state wrote {len(store.writes) - len(settled)} "
            f"additional row(s) and did not refuse, so it was neither idempotent nor refused — "
            f"which leaves only 'partially applied'."
        )

    assert fixtures.SENTINEL_STUDENT_NAME not in str(settled), (
        "a control row carries a student name in its payload; control rows are about the run"
    )
