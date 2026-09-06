"""`CT-STORE-02` — `enqueue_write` is asynchronous, and callers may not assume otherwise.

Case `TC-STORE-C02` (P0, RISK-31 — "the single most load-bearing clause in this contract and
the easiest to get wrong"), test plan §6.11.3. Issue #17 (TS-60).

Rung 2 against a real file. The plan's automation target is this file's name.

Rung 3 note, recorded rather than silently dropped: steps 3 (the five-consumer sweep) and 4
(the §4.2 in-memory-shortcut enumeration) sweep *consumers* — `M-ORCH`, `M-JUDGE`,
`M-EXTRACT`, `M-INGEST`, `M-SYNTH` — none of which exist yet. The sweep is written to iterate
a registry that is empty today and grows as consumers land; asserting nothing over zero
consumers is honest exactly as long as the registry is what fills. The store-side limbs
(steps 1-2) carry the clause here.
"""

from __future__ import annotations

import time

import pytest

from aeh.store import store_metrics
from tests.support.store_api import open_store, statement

# Step 4 needs the file tree; pathlib is imported at use site inside the self-audit.

pytestmark = pytest.mark.contract

ISSUE = "#17"

#: The consumers `CT-STORE-02` names, swept at rung 3 as they land. Empty today by design —
#: see the file docstring; a case that swept nothing while claiming to sweep five would be
#: the vacuous pass this suite exists to prevent.
CONSUMERS: tuple[str, ...] = ()


ROW_INSERT = "INSERT INTO run_metrics (run_id, metric, value) VALUES (:r, :m, :v)"
ROW_READ = "SELECT value FROM run_metrics WHERE metric = :m"


def test_tc_store_c02_enqueue_write_returns_before_the_row_is_durable(tmp_data_dir):
    """Step 1 — the row is **absent**, on a separate connection that cannot see uncommitted
    state, immediately after `enqueue_write` returns. A case asserting only that the row
    *eventually* appears would pass against a synchronous implementation and is therefore
    not this case."""
    store = open_store(tmp_data_dir)
    handle = store.cohort("c-c02")
    with handle.transaction() as tx:
        tx.execute(statement(
            "CREATE TABLE c02_probe (id INTEGER PRIMARY KEY, payload TEXT)", issue=ISSUE))

    handle.enqueue_write(statement(
        "INSERT INTO c02_probe (payload) VALUES ('async-row')", issue=ISSUE))

    # A separate, raw connection: it sees only committed state, by SQLite's own semantics.
    import sqlite3

    with sqlite3.connect(handle._path) as independent:  # noqa: SLF001 -- the file, not the API
        rows = independent.execute("SELECT COUNT(*) FROM c02_probe").fetchone()[0]
    assert rows == 0, (
        f"TC-STORE-C02: {rows} row(s) visible immediately after enqueue_write returned. The "
        "clause says the call returns BEFORE the row is durable — a store that wrote "
        "synchronously here breaks M-ORCH's throughput model in the direction the clause "
        "calls 'the easiest to get wrong', and nothing else in the suite would notice."
    )
    # Step 2, sanctioned way one: wait for the batch (drain), then the row is there.
    deadline = time.monotonic() + 30
    while int(store_metrics(store)["write_queue_depth"]) > 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert handle.query(statement(
        "SELECT payload FROM c02_probe", issue=ISSUE))[0][0] == "async-row"
    store.close()


def test_tc_store_c02_read_your_own_write_goes_through_transaction(tmp_data_dir):
    """Step 2 — the second sanctioned way to observe your own write: inside the same
    `transaction()`, the row is visible to the body itself. This is the contract's answer to
    step 1, and it is what a caller that must read its own write uses."""
    store = open_store(tmp_data_dir)
    handle = store.cohort("c-c02b")
    with handle.transaction() as tx:
        tx.execute(statement(
            "CREATE TABLE c02b_probe (id INTEGER PRIMARY KEY, payload TEXT)", issue=ISSUE))
        tx.execute(statement(
            "INSERT INTO c02b_probe (payload) VALUES ('in-tx')", issue=ISSUE))
        seen = tx.execute(statement(
            "SELECT payload FROM c02b_probe WHERE payload = 'in-tx'", issue=ISSUE))
        assert len(seen) == 1, (
            "TC-STORE-C02: a transaction body could not read its own write. CT-STORE-02 "
            "sanctions exactly two observation routes — the batch wait and the transaction — "
            "and this one is how every read-modify-write ledger transition works."
        )
    store.close()


def test_tc_store_c02_step_4_no_contract_case_uses_an_in_memory_store():
    """Step 4 — *'assert the §4.2 in-memory shortcut is confined: enumerate cases using an
    in-memory store and assert none exercises a write path (§4.10 forbids an in-memory
    stand-in for this contract).'* Implementable today, over this suite's own tree: no
    contract case may open an in-memory SQLite database at all, because a synchronous
    in-memory stand-in is what hides CT-STORE-02's violation."""
    from pathlib import Path

    contract_dir = Path(__file__).resolve().parent
    needle = ":mem" + "ory:"  # assembled so this audit's own text does not match itself
    offenders: list[str] = []
    for py_file in sorted(contract_dir.glob("*.py")):
        if py_file.name == Path(__file__).name:
            continue  # the audit's own docstring discusses the shortcut; code is what counts
        text = py_file.read_text(encoding="utf-8")
        if needle in text:
            offenders.append(py_file.name)
    assert not offenders, (
        f"TC-STORE-C02: contract file(s) open an in-memory store: {offenders}. §4.10 "
        "forbids an in-memory stand-in for this contract — a synchronous in-memory fake is "
        "the exact shape that hides the asynchrony clause being violated."
    )


@pytest.mark.parametrize("consumer", CONSUMERS)
def test_tc_store_c02_no_consumer_reads_back_its_own_enqueue(consumer, tmp_data_dir):
    """Step 3 — the rung-3 consumer sweep, parametrized over the registry above. Empty today;
    the parametrization is the scaffold so the sweep exists the day the first consumer
    lands."""
    pytest.fail(
        f"TC-STORE-C02: consumer {consumer} is registered but no sweep body is bound to it. "
        "Implement the consumer's read-your-own-write sweep when the consumer lands — an "
        "empty sweep must never silently pass."
    )


def test_tc_store_c02_the_batch_wait_is_the_other_sanctioned_route(tmp_data_dir):
    """Step 2, sanctioned way two, made exact: after the queue drains, an independent
    connection sees the row. The waiting caller's contract is the depth signal reaching
    zero — the same signal `CT-STORE-17` emits."""
    store = open_store(tmp_data_dir)
    handle = store.cohort("c-c02c")
    with handle.transaction() as tx:
        tx.execute(statement("CREATE TABLE c02c_probe (id INTEGER PRIMARY KEY)", issue=ISSUE))
    for index in range(5):
        handle.enqueue_write(statement(
            "INSERT INTO c02c_probe (id) VALUES (:i)", issue=ISSUE), i=index)
    deadline = time.monotonic() + 30
    while int(store_metrics(store)["write_queue_depth"]) > 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    import sqlite3

    with sqlite3.connect(handle._path) as independent:  # noqa: SLF001 -- the file, not the API
        count = independent.execute("SELECT COUNT(*) FROM c02c_probe").fetchone()[0]
    assert count == 5, (
        f"TC-STORE-C02: {count} of 5 rows durable after the queue reported drained. The "
        "depth signal is a caller's batch-wait contract; if it reads zero before the commit "
        "lands, every caller waiting on it has been lied to."
    )
    store.close()
