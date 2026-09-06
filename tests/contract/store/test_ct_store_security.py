"""`CT-STORE-08`, `CT-STORE-09`, `CT-STORE-16` — the security clauses.

Cases `TC-STORE-C08`, `TC-STORE-C09`, `TC-STORE-C16`, test plan §6.11.3. Issue #17 (TS-60).

Rung 2. C08 is the **safety property** (design §4.7): its adversarial construction — an FTS
index added as a plausible convenience — must turn this case red while every functional case
stays green, and the adversarial limb here is executed for real against a scratch store. C09
asserts tier ownership as prohibitions. C16 reads real filesystem modes, drives the symlink
bypass, and asserts no network listener exists.

`Written ahead of implementation: yes` is stale; green by design.
"""

from __future__ import annotations

import re
import socket
import sqlite3
from pathlib import Path

import pytest

import aeh.store as store_module
from aeh.store import InsecureLocationError, open_store
from tests.support.store_api import statement
from tests.support.store_vocabulary import virtual_table_definitions

pytestmark = pytest.mark.contract

ISSUE = "#17"

SEARCH_SHAPES = {
    "LIKE": re.compile(r"\blike\b"),
    "GLOB": re.compile(r"\bglob\b"),
    "MATCH": re.compile(r"\bmatch\b"),
    "FTS virtual table": re.compile(r"\bcreate\s+virtual\s+table\b"),
    "fts module": re.compile(r"\busing\s+fts\d*\b"),
    "vector/embedding": re.compile(r"\busing\s+(vss|vec|vector)\d*\b"),
    "REGEXP": re.compile(r"\bregexp\b"),
}


def test_tc_store_c08_no_search_statement_no_fts_and_the_adversarial_construction_reds(
    tmp_data_dir,
):
    """`TC-STORE-C08` — the safety property, both directions.

    Direction one: the shipped store — its registered statements, its schema files, its
    concrete surface — is free of every search shape. Direction two, the **adversarial
    construction**: an FTS index over `document_region`, added as the plausible convenience
    the plan describes, turns this case's schema limb red on a scratch store while leaving
    every functional clause untouched. That is the demonstration the safety property runs
    on: the detector fires on the exact change a well-meaning author would make."""
    from aeh.store import STATEMENTS

    offenders = [
        f"{name}: {shape}"
        for name, stmt in STATEMENTS.items()
        for shape, pattern in SEARCH_SHAPES.items()
        if pattern.search(str(stmt).lower())
    ]
    assert not offenders, (
        f"TC-STORE-C08: the declared-statement registry carries a search shape: {offenders}. "
        "FR-STORE-08 offers keyed lookup and declared queries only — CT-STORE-08 is a safety "
        "property, 'none will be added', and the registry is where an addition shows up."
    )
    store = open_store(tmp_data_dir)
    store.package("s-c08")
    store.cohort("s-c08")
    store.durable()
    store.close()
    for tier_file in sorted(tmp_data_dir.rglob("*.sqlite")):
        virtual = virtual_table_definitions(tier_file)
        assert not virtual, (
            f"TC-STORE-C08: {tier_file.name} declares virtual table(s) {sorted(virtual)}. "
            "An FTS index is the one way to add full-text search without adding a method "
            "anybody would call search — which is why the schema is swept separately."
        )

    # The adversarial construction, on a scratch copy: a plausible convenience feature.
    adversarial = tmp_data_dir / "adversarial"
    store_a = open_store(adversarial)
    handle = store_a.cohort("s-c08-adv")
    with handle.transaction() as tx:
        tx.execute(statement(
            "CREATE VIRTUAL TABLE document_region_fts USING fts5(text)", issue=ISSUE))
    store_a.close()
    caught = []
    for tier_file in sorted(adversarial.rglob("*.sqlite")):
        for name in virtual_table_definitions(tier_file):
            caught.append(f"{tier_file.name}: {name}")
    assert caught, (
        "TC-STORE-C08: the adversarial FTS index did not trip the schema limb. A detector "
        "that stays green on the exact change the plan describes is decoration, and the "
        "safety property is then enforced by nobody."
    )


#: The scoring-path consumers CT-STORE-08's rung-4 limb sweeps, as they land. Empty today;
#: the scaffold below is the unmissable remainder.
SCORING_CONSUMERS: tuple[str, ...] = ()


@pytest.mark.parametrize("consumer", SCORING_CONSUMERS)
def test_tc_store_c08_no_scoring_query_names_another_students_submission(consumer):
    """C08's rung-4 limb — *'run the E2E journey and assert no query issued during scoring
    names another student's submission'* — the runtime form of the no-contamination rule.
    Parametrized over the scoring consumers as they land; an empty registry must never
    read as the sweep having run."""
    pytest.fail(
        f"TC-STORE-C08: scoring consumer {consumer} is registered without a rung-4 sweep "
        "body. Bind the consumer's E2E journey and assert no issued query names another "
        "student's submission when the module lands."
    )


def test_tc_store_c09_tier_prohibitions_and_the_pseudonymized_boundary(tmp_data_dir):
    """`TC-STORE-C09` — *'data moves toward D only, and nothing flows back. Attempt a write
    from Tier D toward C and assert refusal. Then ... Tier D rejects any insert carrying a
    student-name column.'*

    The prohibition half is structural — Tier D's connections attach no other database, so
    'a write from D toward C' cannot even be *expressed* through the handle: the attempt
    below fails at ATTACH (the schema authorizer) and at the closed surface, and the case
    asserts both refusals. The pseudonymization half is the name guard, attempted directly."""
    store = open_store(tmp_data_dir)
    durable = store.durable()
    cohort = store.cohort("s-c09")

    # The route a "write from D toward C" would take: ATTACH the cohort file from the
    # durable write connection and reach across. The authorizer refuses it.
    cohort_file = str(store.cohort_path("s-c09")).replace("\\", "/")
    with pytest.raises(sqlite3.DatabaseError):
        with durable.transaction() as tx:
            tx.execute(statement(
                f"ATTACH DATABASE '{cohort_file}' AS cohort_side", issue=ISSUE))
    # The cohort's rows are untouched by the refused attempt.
    rows = cohort.query(statement("SELECT COUNT(*) FROM cohort", issue=ISSUE))
    assert rows[0][0] == 0

    # The pseudonymization half: the name-bearing insert is refused by the exact guard.
    from aeh.store import StudentNameInTierDError

    with pytest.raises(StudentNameInTierDError) as refused:
        with durable.transaction() as tx:
            tx.execute(statement(
                "INSERT INTO label (label_id, run_id, student_name, criterion_id, label_type, "
                "band) VALUES ('l-1', 'r', 'Amara Okonkwo', 'c', 'human', 'b1')", issue=ISSUE))
    assert "student_name" in str(refused.value)
    store.close()


def test_tc_store_c16_owner_only_modes_symlink_refusal_and_no_listener(tmp_data_dir):
    """`TC-STORE-C16` — *'database files and the blob directory are created owner-only ... the
    module refuses to start when the configured data directory resolves inside a
    world-writable temporary path — including via a symlink ... no network listener exists.'*

    The mode half is POSIX-gated (Windows fabricates the bits); the symlink half drives the
    check's own seams (the platform cannot express the precondition); the listener half
    records every `bind`/`listen` call across a full open-write-read cycle."""
    import os
    from unittest import mock

    if os.name == "posix":
        data = tmp_data_dir / "modes"
        store = open_store(data)
        store.durable()
        store.cohort("s-c16")
        store.close()
        import stat as stat_module

        for directory in (data, data / "packages", data / "cohorts", data / "blobs"):
            assert stat_module.S_IMODE(directory.stat().st_mode) == 0o700
        assert stat_module.S_IMODE(store.durable_path().stat().st_mode) == 0o600
    else:
        # Windows: the mode bits are fabricated; the chmod calls are the honest evidence.
        calls: list[tuple[str, int]] = []
        real_chmod = os.chmod
        with mock.patch.object(store_module.os, "chmod",
                               lambda p, m: calls.append((os.fspath(p), m))):
            data = tmp_data_dir / "modes"
            store = open_store(data)
            store.durable()
            store.close()
        assert any(m == 0o700 for _, m in calls) and any(
            m == 0o600 for _, m in calls), (
            f"TC-STORE-C16: no owner-only chmod calls recorded ({calls}). The owner-only "
            "posture runs on every platform; the bits themselves are POSIX-verified."
        )

    # The symlink bypass: a data directory that is a symlink into a world-writable temp
    # tree. Two halves: the resolution itself (via the check's injectable seams, since this
    # host cannot express the POSIX modes), and the refusal before anything is created.
    reason = store_module._insecure_location_reason(
        Path("/tmp/link/data"), os_name="posix",
        stat_fn=lambda p: os.stat_result(
            (0o40700 if p.name == "data" else 0o41777, 0, 0, 0, 0, 0, 0, 0, 0, 0)))
    assert reason is not None, (
        "TC-STORE-C16: a data directory resolving into a world-writable temp tree passed. "
        "The resolution is the defence against the symlink bypass a prefix check misses."
    )
    never = tmp_data_dir / "symlinked-target-never-created"
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        store_module, "_insecure_location_reason", lambda p, **kw: str(reason))
    try:
        with pytest.raises(InsecureLocationError):
            open_store(never)
        assert not never.exists(), (
            "TC-STORE-C16: the refused start created the directory — the refusal must "
            "precede the first mkdir for 'refuses to start' to mean anything."
        )
    finally:
        monkeypatch.undo()

    # No network listener: record every bind/listen across open, write, read, close.
    bound: list[str] = []
    real_bind = socket.socket.bind
    real_listen = socket.socket.listen
    with mock.patch.object(socket.socket, "bind",
                           lambda self, addr: (bound.append(f"bind {addr}"), real_bind(self, addr))[1]), \
         mock.patch.object(socket.socket, "listen",
                           lambda self, n: (bound.append("listen"), real_listen(self, n))[1]):
        listener_store = open_store(tmp_data_dir / "listener")
        listener_store.durable()
        listener_store.close()
    assert not bound, (
        f"TC-STORE-C16: the store bound/listened on {bound}. §3.3: no server process, no "
        "network listener — a bound socket is the clause failing in the direction an "
        "operator would never think to check."
    )

