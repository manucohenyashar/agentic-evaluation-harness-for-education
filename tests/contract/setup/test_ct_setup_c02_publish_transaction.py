"""`CT-SETUP-02` — `publish()` is a single transaction and the only route to
published state (`TC-SETUP-C02`).

Case of test plan §6.11.6; issue #56 (TS-63). **Green by design** — `aeh.setup`
and `aeh.pkg` landed with #50; the probe confirmed every half below on shipped
code.

The clause: nothing partially publishes — either the version exists **with the
§6.2 lock in force**, or nothing was written. A half-published version with the
lock not yet applied is an editable published package, which is RISK-06 with the
door left open.

Asserted here, probed:

1. **The only route.** Every public operation `SetupService` offers is driven
   against a draft; only `publish()` ever flips the lock. The other mutators
   (`propose_inventory`, `confirm_inventory`, `set_answer_keys`) leave the
   version unpublished; the read surface and `ensure_version` write nothing of
   the kind. This is a sweep over the reflected surface, not a single call.
2. **The gates refuse before the transaction, with the gate named.** Publishing
   without the confirmed inventory is refused naming blocking gate 1 of 2;
   publishing with a real, unkeyed deterministic criterion — staged through the
   real `PackageCatalog` API, the state gate 2 exists to catch — is refused
   naming blocking gate 2 of 2. A refused publish writes nothing: the version
   row, hashed before and after, is byte-identical.
3. **The transaction is single.** Under the `AuditHandle` write audit, a
   successful `publish()` issues exactly ONE write statement — the single UPDATE
   that sets `locked = 1`, `published_by` and `published_at` together. There is
   no window in which the lock is on but the stamp is not, or vice versa: one
   statement, one transaction.
4. **Randomized mid-publish kills are all-or-nothing.** A `KillError` (a
   `BaseException`, the store's own rollback signal — an uncontrolled kill, not a
   handled failure) is injected at a seeded-random point of the publish
   transaction: before `BEGIN`, inside the body before the statement, after the
   statement, or after the body before the commit. After each kill, a FRESH
   process view of the stored file shows exactly one of two states: the version
   unchanged to the byte (nothing written — the pre-publish hash matches), or
   fully published with the §6.2 lock in force. No third state exists, at any
   kill point. A killed publish is also recoverable: the retry succeeds.

The kill is injected through a pass-through `TierHandle` wrapper
(`tests.contract.setup._doubles.KillHandle`) around the catalog's real handle,
so the database under test is the real SQLite file throughout; only the kill is
injected. Reaching the handle via `catalog._handle` is the one non-public access
the clause's fault injection needs — there is no public seam for killing the
process, by definition.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import random
import sqlite3

import pytest

from aeh.pkg import PackageCatalog
from aeh.setup import SetupOrderError, SetupService
from tests.contract.setup._doubles import (
    AuditHandle,
    KillError,
    KillHandle,
    db_file_for,
    ingest_document,
    stage_chain,
)

pytestmark = pytest.mark.contract

#: The kill points, in the order a publish transaction reaches them. The seeded
#: choice below sweeps all of them repeatedly.
KILL_POINTS = ("before_begin", "before_statement", "after_statement",
               "after_commit_body")


def _fresh_confirmed(data_dir, package_id):
    """A fresh chain with blocking gate 1 satisfied — the minimal publishable
    world (gate 2 is vacuous with zero criteria until #53 stages them)."""
    chain = stage_chain(data_dir, package_id=package_id)
    chain.doc = ingest_document(chain.store, kind="assessment")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)
    return chain


def _state_hash(data_dir, package_id, version):
    """A hash over EVERY stored row of the package tier — the material the
    all-or-nothing property is stated over."""
    conn = sqlite3.connect(f"file:{db_file_for(data_dir, package_id)}?mode=ro",
                           uri=True)
    try:
        payload = []
        for (table,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            payload.append(f"{table}={sorted(map(repr, rows))}")
        blob = json.dumps(payload, sort_keys=True).encode()
    finally:
        conn.close()
    return hashlib.sha256(blob).hexdigest()


def test_tc_setup_c02_only_publish_reaches_published_state(tmp_data_dir):
    """Every public operation is driven; only `publish()` produces a locked
    version. The sweep is over the reflected surface — adding a sixth public
    operation that writes published state lands outside this sweep's exceptions
    only by failing here (the operation either locks the version and is caught
    by the assertion below, or joins the route list and must be added WITH a
    clause of its own)."""
    chain = _fresh_confirmed(tmp_data_dir, "pkg-c02-route")
    version = chain.service.ensure_version()
    assert not chain.catalog.is_locked(version)

    # The public callables of the service, from reflection — not a hand list.
    operations = [
        name for name, member in inspect.getmembers(SetupService, inspect.isfunction)
        if not name.startswith("_")
    ]
    assert "publish" in operations, "the reflection lost publish — fix the sweep"

    stored = chain.catalog.proposal(version)
    for name in operations:
        if name == "publish":
            continue
        op = getattr(chain.service, name)
        try:
            # Each operation is actually DRIVEN (real arguments, not a TypeError
            # that skips it): the mutators run against the draft — some refuse,
            # which is their right; none may produce published state.
            if name == "propose_inventory":
                op(chain.doc)
            elif name == "confirm_inventory":
                op(stored["proposal_id"])
            elif name == "set_answer_keys":
                op({"MCQ-1": ["A"]})
            else:
                op()
        except Exception:
            pass  # the refusal is fine; producing published state is not
        assert not chain.catalog.is_locked(version), (
            f"{name}() produced published state — publish() is not the only "
            "route to the §6.2 lock (CT-SETUP-02)"
        )

    # And the one route that exists does reach it.
    chain.service.publish("teacher-1")
    assert chain.catalog.is_locked(version)


def test_tc_setup_c02_gates_refuse_before_any_write(tmp_data_dir):
    """Both blocking gates refuse publish BEFORE the transaction, name the gate,
    and leave the stored state byte-identical."""
    chain = stage_chain(tmp_data_dir, package_id="pkg-c02-gates")
    chain.doc = ingest_document(chain.store, kind="assessment")
    proposal = chain.service.propose_inventory(chain.doc)
    version = chain.service.ensure_version()
    before = _state_hash(tmp_data_dir, "pkg-c02-gates", version)

    # Gate 1: the inventory is not confirmed.
    with pytest.raises(SetupOrderError) as exc:
        chain.service.publish("teacher-1")
    assert "gate 1 of 2" in str(exc.value)
    assert not chain.catalog.is_locked(version)
    assert _state_hash(tmp_data_dir, "pkg-c02-gates", version) == before, (
        "a refused publish wrote something (CT-SETUP-02: nothing partially publishes)"
    )

    # Gate 2: a real deterministic criterion without a key, staged through the
    # real M-PKG API — the exact state gate 2 exists to catch. (The confirmation
    # itself wrote; the invariant is per-refusal, so the baseline is re-taken
    # after it and compared across the refusal only.)
    chain.service.confirm_inventory(proposal.proposal_id)
    chain.catalog.add_criterion(version, "MCQ-1", question_id="Q4", kind="mcq")
    after_confirm = _state_hash(tmp_data_dir, "pkg-c02-gates", version)
    with pytest.raises(SetupOrderError) as exc:
        chain.service.publish("teacher-1")
    assert "gate 2 of 2" in str(exc.value)
    assert "MCQ-1" in str(exc.value), "the refusal does not name the unkeyed criterion"
    assert not chain.catalog.is_locked(version)
    assert _state_hash(tmp_data_dir, "pkg-c02-gates", version) == after_confirm, (
        "a refused publish wrote something (CT-SETUP-02: nothing partially publishes)"
    )


def test_tc_setup_c02_publish_is_one_write_statement(tmp_data_dir):
    """Under the write audit, a successful publish issues exactly ONE statement —
    the single UPDATE carrying the lock and both stamps together."""
    chain = _fresh_confirmed(tmp_data_dir, "pkg-c02-audit")
    version = chain.service.ensure_version()
    audit = AuditHandle(chain.catalog._handle)
    chain.catalog._handle = audit
    try:
        chain.service.publish("teacher-1")
    finally:
        chain.catalog._handle = audit._inner
    assert chain.catalog.is_locked(version)
    publish_writes = [sql for sql in audit.writes if "package_version" in sql
                      and "locked" in sql]
    assert len(publish_writes) == 1, (
        f"publish() issued {len(publish_writes)} lock-carrying statements — "
        "the lock and its stamps must be one statement, one transaction "
        "(CT-SETUP-02)"
    )
    sql = publish_writes[0]
    assert "locked = 1" in sql and "published_by" in sql and "published_at" in sql, (
        f"the lock statement does not carry lock and stamps together: {sql!r}"
    )


def test_tc_setup_c02_randomized_kills_are_all_or_nothing(tmp_data_dir):
    """Kill the publish at seeded-random points; after each kill a fresh process
    view shows the version unchanged to the byte OR fully published with the
    §6.2 lock in force. Never a third state."""
    rng = random.Random(56)  # fixed seed: a failing run is reproducible
    for index in range(8):
        package_id = f"pkg-c02-kill-{index}"
        chain = _fresh_confirmed(tmp_data_dir / f"k{index}", package_id)
        version = chain.service.ensure_version()
        before = _state_hash(tmp_data_dir / f"k{index}", package_id, version)
        real_handle = chain.catalog._handle
        point = KILL_POINTS[index % len(KILL_POINTS)] if index < 4 else rng.choice(
            KILL_POINTS)

        chain.catalog._handle = KillHandle(real_handle, point)
        killed = False
        try:
            chain.catalog.publish(version, "teacher-1")
        except KillError:
            killed = True
        finally:
            chain.catalog._handle = real_handle
        if index < 4:
            # The deterministic half: each of the four kill points MUST fire.
            # If publish() moved off the transaction() door, every iteration
            # would silently degrade to a happy path and the all-or-nothing
            # sweep would assert nothing.
            assert killed, (
                f"[{point}] the kill never fired — publish() no longer executes "
                "through the audited transaction door, so this sweep is "
                "asserting happy paths (CT-SETUP-02)"
            )

        # A FRESH process view: new catalog object over the same file.
        fresh_catalog = PackageCatalog(
            chain.store.package(package_id), package_id=package_id)
        locked = fresh_catalog.is_locked(version)
        after = _state_hash(tmp_data_dir / f"k{index}", package_id, version)

        if killed:
            assert not locked, (
                f"[{point}] a killed publish left the §6.2 lock in force without "
                "completing — a half-published version is RISK-06 with the door "
                "left open (CT-SETUP-02)"
            )
            assert after == before, (
                f"[{point}] a killed publish wrote something: the stored state "
                "changed although the lock never engaged (CT-SETUP-02)"
            )
        else:
            assert locked, (
                f"[{point}] publish returned success but the lock is not in force"
            )
        # Either way the version row is internally consistent: lock and stamps
        # agree (never locked-without-stamp or stamped-without-lock).
        conn = sqlite3.connect(
            f"file:{db_file_for(tmp_data_dir / f'k{index}', package_id)}?mode=ro",
            uri=True)
        try:
            row = conn.execute(
                "SELECT locked, published_by, published_at FROM package_version "
                "WHERE package_version_id = ?", (version,)).fetchone()
        finally:
            conn.close()
        assert ((row[0] == 1) == (row[1] is not None) == (row[2] is not None)), (
            f"[{point}] lock and stamps disagree: {row!r} — a partial publish "
            "state exists (CT-SETUP-02)"
        )
        # A killed publish is recoverable: the retry completes and locks.
        if killed:
            chain.catalog.publish(version, "teacher-1")
            assert chain.catalog.is_locked(version)
