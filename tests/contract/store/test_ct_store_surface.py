"""`CT-STORE-01` and `CT-STORE-07` — the closed surface, and content-addressed blobs.

Cases `TC-STORE-C01` (P0) and `TC-STORE-C07` (P1), test plan §6.11.3. Issue #17 (TS-60).

Rung 2 — the concrete classes, not the Protocols: `SEC-15` sweeps the protocols and cannot
see a concrete member added off-protocol, which is exactly the door this case shuts.

`Written ahead of implementation: yes` is stale — the store is landed and reviewed; the cases
run green by design.
"""

from __future__ import annotations

import pytest

from aeh.store import Statement, open_store
from tests.support.store_api import statement

pytestmark = pytest.mark.contract

ISSUE = "#17"

#: `CT-STORE-01`, verbatim: the contract surface.
STORE_MEMBERS = {"package", "cohort", "durable", "blobs", "purge_cohort"}
HANDLE_MEMBERS = {"query", "enqueue_write", "transaction"}

#: The documented non-contract members the concrete `SqliteStore` carries: lifecycle
#: (`close`), the layout accessors the tests and operators read (`data_dir`, the three path
#: helpers), open-time observability (`opened`, `limits`), and #12's lease-clock API. They
#: are PINNED — set equality over the whole public surface — so a *new* member still fails
#: the case; only this exact set is sanctioned, and a future story that privatizes any of
#: them edits this constant in the same PR.
STORE_INFRASTRUCTURE_MEMBERS = {
    "close", "data_dir", "limits", "opened", "package_path", "cohort_path",
    "durable_path", "attach_lease_clock", "lease_clock_instance",
}


def _public_members(instance) -> set[str]:
    """Public names as the object actually carries them — the concrete class, not the
    Protocol. Properties count as members: a `search_results` property is as much a surface
    as a method (the callable-only filter is exactly what TS-60's review of the TC-STORE-15
    draft called out)."""
    return {name for name in dir(instance) if not name.startswith("_")}


def test_tc_store_c01_the_store_surface_is_exactly_five_members(tmp_data_dir):
    """`TC-STORE-C01` — *"`Store` yields exactly three handle kinds plus `blobs()` and
    `purge_cohort(id)`, by set equality."* Set equality, not presence: a member that appears
    without a contract row is the bypass door, and presence checks are how it slips through."""
    store = open_store(tmp_data_dir)
    sanctioned = STORE_MEMBERS | STORE_INFRASTRUCTURE_MEMBERS
    extra = _public_members(store) - sanctioned
    missing = STORE_MEMBERS - _public_members(store)
    assert not extra and not missing, (
        f"TC-STORE-C01: Store's public surface drifted — extra: {sorted(extra)}, missing: "
        f"{sorted(missing)}. The five contract members are set-equal by enumeration; the "
        "pinned infrastructure set above is the only other thing the concrete class may "
        "carry, and a NEW member is a door no clause audited. ('Harmless-looking' is the "
        "review verdict that let `close()` onto the handle in #10 — caught by TC-STORE-15, "
        "renamed in #12.)"
    )
    # Each handle kind comes back, and the handle surface is closed too.
    for handle in (store.package("pkg-c01"), store.cohort("coh-c01"), store.durable()):
        extra = _public_members(handle) - HANDLE_MEMBERS
        missing = HANDLE_MEMBERS - _public_members(handle)
        assert not extra and not missing, (
            f"TC-STORE-C01: TierHandle's surface drifted — extra: {sorted(extra)}, missing: "
            f"{sorted(missing)}. `query`, `enqueue_write`, `transaction` — and nothing else: "
            "an added `execute` or `raw_connection` is the escape hatch through which every "
            "other clause in this contract gets bypassed."
        )
    store.close()


def test_tc_store_c07_blobs_are_content_addressed_idempotent_and_live_for_the_tier(
    tmp_data_dir,
):
    """`TC-STORE-C07` — *"`put(data) -> content_hash` is content-addressed on SHA-256 and
    idempotent ... `get` and `path` resolve any hash `put` returned, for the lifetime of the
    owning tier."*

    Oracle: **exact value against a known SHA-256**, and a file count — dedup is asserted by
    counting the files on disk, not by trusting `put` to say it deduplicated."""
    import hashlib

    store = open_store(tmp_data_dir)
    blobs = store.blobs()
    payload = b"CT-STORE-C07 canonical payload"
    expected = hashlib.sha256(payload).hexdigest()

    first = blobs.put(payload)
    assert first == expected, (
        f"TC-STORE-C07: put() returned {first}; the clause pins content-addressing to "
        "SHA-256, and an exact known-vector mismatch means the hash is not the digest of "
        "the bytes — keyed lookup by content is then untrustworthy everywhere."
    )
    assert blobs.put(payload) == first
    files = [p for p in (tmp_data_dir / "blobs").rglob("*") if p.is_file()]
    assert len(files) == 1, (
        f"TC-STORE-C07: {len(files)} files on disk after two identical puts. Idempotency is "
        "asserted by the filesystem, not by the return value — one stored copy is the clause."
    )
    assert blobs.get(first) == payload

    # The lifetime half: reopen the store (new handles, same directory) and resolve again —
    # `get` AND `path`, both of which the clause names.
    store.close()
    reopened = open_store(tmp_data_dir)
    assert reopened.blobs().get(first) == payload, (
        "TC-STORE-C07: a hash put() returned did not resolve after a reopen. The lifetime is "
        "the owning tier's, not the handle's — M-INGEST reads rasters back across sessions."
    )
    resolved = reopened.blobs().path(first)
    assert resolved.is_relative_to(tmp_data_dir.resolve()) and resolved.exists(), (
        f"TC-STORE-C07: path({first}) after reopen is {resolved} — outside the data "
        "directory or absent. The clause names path() beside get()."
    )
    reopened.close()
