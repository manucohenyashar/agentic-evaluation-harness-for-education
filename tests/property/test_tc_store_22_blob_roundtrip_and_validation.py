"""Blobs round-trip for every payload, and the accessors reject every malformed hash.

Case `TC-STORE-22` (`FR-STORE-06`, P1, property) and the accessor half of `SEC-09`
(§6.5), test plan §5.3 and §6.5. Issue #15 (TS-09).

Rung 2 — the real blob directory, because `get(put(b)) == b` over multi-megabyte payloads is
a claim about bytes on a disk, and the negative half's oracle is "rejected **before touching
the filesystem**", which is only checkable against a real one.

`Written ahead of implementation: yes` is stale — the blob store landed with #12; the case
runs green by design.

`FUZZ-07`'s blob property (landed, in-gate) is the *positive* half against generated
payloads; this case adds what the plan says `TC-STORE-22` names and `FUZZ-07` left open: the
**input-validation** half — generated non-hex arguments passed directly to `get()` and
`path()`, the only way such a value can reach them since `put()` computes the hash itself.
`SEC-09`'s insecure-location probe is `TC-STORE-10`'s ground (`tests/integration/store/
test_permissions.py`), and is referenced rather than duplicated.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aeh.store import InvalidContentHashError
from tests.support.store_api import open_store

pytestmark = pytest.mark.property

ISSUE = "#15"

VALID_HASH = "ab" * 32  # well-formed, and absent — the shape a wrong-directory get() hits

#: The payloads the plan names: empty, one byte, and multi-megabyte, plus ordinary text and
#: high bytes. `FUZZ-07`'s strategy covers arbitrary byte strings; the boundary sizes here
#: are the ones its generator under-samples.
blob_payloads = st.one_of(
    st.just(b""),
    st.just(b"\x00"),
    st.binary(max_size=256),
    st.binary(min_size=1, max_size=64),
    st.just(b"x" * (2 * 1024 * 1024)),  # multi-megabyte, per the plan
    st.just(bytes(range(256)) * 3),
)

#: The attack spellings `SEC-09` names: traversal, absolute path, wrong length, mixed case,
#: unicode — every shape that is not exactly 64 lowercase hex characters.
invalid_hashes = st.sampled_from([
    "../" + "a" * 61,                      # traversal-shaped, 64 chars
    "/etc/passwd" + "a" * 53,              # absolute path, 64 chars
    "a" * 63,                              # one short
    "a" * 65,                              # one long
    "A" * 64,                              # mixed case — two spellings of one blob
    "g" * 64,                              # out of hex alphabet
    "ab" * 31 + "😀",                       # unicode inside the length
    "",                                    # empty
    "ab" * 32 + "\n",                      # trailing newline tricks a naive match
    " " + "a" * 64,                        # leading whitespace
    "../../etc/passwd",                    # pure traversal
    "a" * 64 + "/../../etc/passwd",        # the suffix the plan calls out by name
]) | st.text(min_size=1, max_size=80).filter(
    lambda s: not (len(s) == 64 and all(c in "0123456789abcdef" for c in s))
)


@settings(max_examples=50, deadline=None)
@given(payload=blob_payloads)
def test_tc_store_22_get_of_put_is_the_bytes_itself(tmp_data_dir, payload):
    """`TC-STORE-22` — *"`get(put(b))` equals `b` for all b."*

    The round-trip invariant, over the boundary sizes the plan names. The path half is
    asserted beside it: the resolved path stays inside the data directory, which is
    `FR-STORE-09`'s containment promise applied to the blob layout."""
    store = open_store(tmp_data_dir)
    blobs = store.blobs()
    content_hash = blobs.put(payload)
    assert blobs.get(content_hash) == payload, (
        "TC-STORE-22: get(put(b)) != b. A blob that does not round-trip is a page raster the "
        "grader cannot re-read — silent corruption of the evidence the verdicts cite."
    )
    resolved = blobs.path(content_hash)
    assert resolved.resolve().is_relative_to(Path(tmp_data_dir).resolve()), (
        "TC-STORE-22: the blob resolved outside the data directory. FR-STORE-09's "
        "containment is not optional for the blob layout."
    )
    # Idempotency, pinned here because the boundary payloads are what a dedup bug eats.
    assert blobs.put(payload) == content_hash
    store.close()


@settings(max_examples=50, deadline=None)
@given(bad=invalid_hashes)
def test_sec_09_the_accessors_reject_a_malformed_hash_before_touching_the_filesystem(
    tmp_data_dir, bad
):
    """`TC-STORE-22`'s negative half, named for `SEC-09` — *"The accessor rejects any
    non-hex hash before touching the filesystem, so resolution can never leave the data
    directory."*

    The oracle is the **before**: the rejection must happen with the blob directory byte-for-
    byte unchanged, because a validator that touches the filesystem first has already lost
    the traversal race it exists to win."""
    store = open_store(tmp_data_dir)
    blobs = store.blobs()
    pinned = blobs.put(b"canary")  # something real, so a hit is distinguishable from a miss
    before = sorted((tmp_data_dir / "blobs").rglob("*"))
    with pytest.raises(InvalidContentHashError):
        blobs.get(bad)
    with pytest.raises(InvalidContentHashError):
        blobs.path(bad)
    assert sorted((tmp_data_dir / "blobs").rglob("*")) == before, (
        f"SEC-09: get/path({bad!r}) touched the filesystem before rejecting. The validation "
        "must run first — a traversal that resolves before it is rejected has already done "
        "its work."
    )
    # The canary still resolves: the rejection is of the argument, not the store.
    assert blobs.get(pinned) == b"canary"
    store.close()
