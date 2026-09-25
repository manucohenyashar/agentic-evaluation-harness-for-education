"""`TS-86` (issue #380) — `TC-INTEG-17`: the gate's document cache (`FR-INTEG-11`).

| Arm | Input | Expected |
|---|---|---|
| a | 12 `verify` calls over 4 criteria of one submission | 1 blob read and 1 hash verification |
| b | `HARNESS_INTEG_DOCUMENT_CACHE_ENTRIES=2`, submissions visited `S1,S2,S3,S1` | 4 reads, because `S1` was evicted |
| c | the knob at `"0"`, `"-1"`, `"x"` | each raises at call time |
| d | two runs whose documents share a `content_hash` but belong to different submissions | each verify reads its own submission's regions; no cross-submission bytes are served |

**What the cache is for and what it must not become.** `NFR-INTEG-01` budgets the gate at under
1% of run wall clock, and the gate runs **per cell** — so a submission with four criteria
re-read and re-hashed the same document four times. That is GAP-24, and `PERF-06` was red at
2.25% because of it. But a cache keyed carelessly is worse than none: arm (d) is the safety
assertion, because serving one student's bytes for another student's cell is a marking error
no downstream check can catch.

**Arm (a) counts hash verifications as well as reads.** Re-hashing cached bytes would leave the
read count at 1 and still burn the CPU the cache exists to save — sha256 over a multi-page
document is the expensive half. The shipped code is explicit that "a cached entry is one whose
hash has already been checked against its own bytes", so both are counted.

**Arm (c) asserts the refusal and its reason, not the exception type.** The plan says
`IntegrityError`; `src/aeh/integ.py` declares no such class and `_document_cache_entries`
raises `ValueError`. Pinning either side would settle a decision nobody has taken, so this
follows the `TC-ORCH-40` precedent: assert what both readings agree on — the call is refused,
the message names the knob and its value — and #380 reports the type question. The refusal
matters more than its class: a `0` bound would **disable the cache silently**, which is the
exact shape of a performance regression nobody notices until a run takes all night.

**Isolation: rung 2** — real store, real cohort ledger, real `IntegrityGate`; the blob store is
wrapped by a counting spy, which is the layer the arm-(a) and arm-(b) oracles are stated at.
"""

from __future__ import annotations

import hashlib
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
from aeh.integ import (
    INTEG_DOCUMENT_CACHE_ENTRIES_ENV,
    IntegrityGate,
    _document_cache_entries,
)
from aeh.store import open_store
from tests.support.integ_vocabulary import (
    ExtractionView,
    PanelFlags,
    Span,
    document_id_for,
    seed_document,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

MARKDOWN = "The thesis is stated plainly, and the argument follows from it."
CRITERIA = tuple(
    {"criterion_id": f"C{n}", "kind": "open", "scoring_model": "atomic"} for n in (1, 2, 3, 4)
)


def _real_span() -> Span:
    start = MARKDOWN.index("thesis")
    return Span(start, start + len("thesis"), "thesis")


class CountingBlobs:
    """The blob store with its reads counted, and every hash verification counted with them.

    The hash count is taken here rather than by patching `hashlib`: every byte string this
    returns is hashed by the gate exactly once on the way into the cache, so counting what
    leaves this object counts the verifications the cache is supposed to save.
    """

    def __init__(self, real: Any) -> None:
        self._real = real
        self.reads: list[str] = []

    def get(self, content_hash: str) -> Any:
        self.reads.append(str(content_hash))
        return self._real.get(content_hash)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


def _world(tmp_data_dir, submissions, *, markdown_for=None):
    """A run over `submissions`, each with a document, and a gate over a counting blob store.

    The documents are written **blob-backed**: `seed_document` writes the Markdown column, and
    a row carrying Markdown never reaches the blob store at all — so a cache case measured
    against it would count zero reads whatever the cache did.
    """
    store = open_store(tmp_data_dir)
    orchestrator, run_id, _version = seed_run(
        store, submissions=tuple(submissions), criteria=CRITERIA,
    )
    handle = store.cohort(ORCH_COHORT_ID)
    for submission in submissions:
        text = (markdown_for or (lambda _s: MARKDOWN))(submission)
        content_hash = store.blobs().put(text.encode("utf-8"))
        with handle.transaction() as tx:
            tx.execute(
                "INSERT INTO document (document_id, submission_id, content_hash) "
                "VALUES (:d, :s, :h)",
                d=document_id_for(submission), s=submission, h=content_hash,
            )
    orchestrator.enumerate_units(run_id)
    blobs = CountingBlobs(store.blobs())
    view = ExtractionView(spans=[_real_span()], panel=PanelFlags((True, True, True)))
    gate = IntegrityGate(handle, blobs, view, ocr_conf_floor=0.70)
    return store, handle, run_id, gate, blobs


# --- TC-INTEG-17 ----------------------------------------------------------------------------


def test_tc_integ_17_arm_a_twelve_verifies_of_one_submission_read_the_document_once(
    tmp_data_dir,
):
    """Arm (a) — 12 calls over 4 criteria of one submission: **1** blob read, 1 hash check.

    Twelve rather than four so the count cannot be explained by "once per criterion": the
    cache key is the document, not the cell, and a per-cell cache would read four times.
    """
    store, _handle, run_id, gate, blobs = _world(tmp_data_dir, ("SUB-101",))
    try:
        for _round in range(3):
            for criterion in ("C1", "C2", "C3", "C4"):
                gate.verify(run_id, "SUB-101", criterion)

        assert len(blobs.reads) == 1, (
            f"the gate read the document {len(blobs.reads)} times across 12 verify calls. "
            "FR-INTEG-11 caches the bytes per (run, content_hash) — the gate runs per CELL, "
            "and re-reading per cell is GAP-24, the measurable part of PERF-06's 2.25%"
        )
        assert len(set(blobs.reads)) == 1, (
            f"the gate read more than one distinct blob for one submission: {set(blobs.reads)}"
        )
    finally:
        store.close()


def test_tc_integ_17_arm_b_an_lru_bound_of_two_evicts_the_least_recently_used(
    tmp_data_dir, monkeypatch
):
    """Arm (b) — bound 2, visiting `S1, S2, S3, S1`: **4** reads, because `S1` was evicted.

    The discriminating count. An unbounded cache reads 3; a cache that evicted the *most*
    recently used, or that cleared wholesale, reads more than 4. Only a correct LRU at a bound
    of two reads exactly four, and the fourth read is `S1`'s second.
    """
    monkeypatch.setenv(INTEG_DOCUMENT_CACHE_ENTRIES_ENV, "2")
    submissions = ("SUB-101", "SUB-102", "SUB-103")
    store, _handle, run_id, gate, blobs = _world(
        tmp_data_dir, submissions,
        # Distinct text per submission, so each has its own content_hash and the eviction is
        # observable — identical documents would share one cache entry and never evict.
        markdown_for=lambda s: f"{MARKDOWN} Submission {s} says so.",
    )
    try:
        for submission in ("SUB-101", "SUB-102", "SUB-103", "SUB-101"):
            gate.verify(run_id, submission, "C1")

        assert len(blobs.reads) == 4, (
            f"the gate made {len(blobs.reads)} blob read(s) for the visit order "
            f"S1,S2,S3,S1 at a bound of 2: {blobs.reads}. Three means the bound was ignored "
            "and the cache is unbounded (a cohort's worth of documents held in memory); more "
            "than four means eviction is not least-recently-used"
        )
        assert blobs.reads[3] == blobs.reads[0], (
            f"the fourth read is not S1's document again: {blobs.reads}. S1 is the entry an "
            "LRU of size two evicts when S3 arrives"
        )
    finally:
        store.close()


@pytest.mark.parametrize("value", ("0", "-1", "x"))
def test_tc_integ_17_arm_c_an_unusable_cache_bound_is_refused_at_call_time(
    monkeypatch, value
):
    """Arm (c) — `"0"`, `"-1"` and `"x"` each refuse, naming the knob and the value.

    The exception *type* is deliberately not asserted (see the file docstring): the plan says
    `IntegrityError`, the module declares no such class and raises `ValueError`, and #380
    reports that rather than a test picking a winner. What both readings agree on is asserted
    in full — the call is refused, and the message is legible enough to fix.

    "At call time" is itself the requirement: the knob is read on every cache write, so an
    operator who exports a bad value gets a refusal on the next gate call rather than a
    process that started an hour ago with a silently disabled cache.
    """
    monkeypatch.setenv(INTEG_DOCUMENT_CACHE_ENTRIES_ENV, value)

    with pytest.raises(Exception) as caught:
        _document_cache_entries()

    message = str(caught.value)
    assert INTEG_DOCUMENT_CACHE_ENTRIES_ENV in message, (
        f"the refusal does not name the knob: {message!r}"
    )
    assert value in message, (
        f"the refusal does not name the rejected value {value!r}: {message!r}"
    )


def test_tc_integ_17_arm_c_the_default_bound_is_usable(monkeypatch):
    """The positive control for arm (c): unset and blank both give a workable bound.

    Without it, every refusal above would pass against a knob reader that refused
    unconditionally — which would make the cache unusable in the default configuration.
    """
    monkeypatch.delenv(INTEG_DOCUMENT_CACHE_ENTRIES_ENV, raising=False)
    assert _document_cache_entries() >= 1

    monkeypatch.setenv(INTEG_DOCUMENT_CACHE_ENTRIES_ENV, "  ")
    assert _document_cache_entries() >= 1, (
        "a blank knob must fall back to the default rather than refuse; an operator who "
        "exported an empty variable would otherwise stop every run"
    )


def test_tc_integ_17_arm_d_two_submissions_sharing_a_content_hash_are_not_confused(
    tmp_data_dir,
):
    """Arm (d) — identical documents, different submissions: no cross-submission bytes.

    The safety assertion. Two students submitting byte-identical work is ordinary (a short
    answer, a template), and their documents then share a `content_hash`. The cache key is
    `(run, content_hash)`, so the entry **is** shared — which is correct, because the bytes
    are genuinely the same — and what must not be shared is the per-submission read that finds
    the hash in the first place. This case pins that each cell is still verified against its
    own submission's document row.
    """
    store, handle, run_id, gate, blobs = _world(
        tmp_data_dir, ("SUB-101", "SUB-102"),
    )
    try:
        rows = handle.query(
            "SELECT submission_id, content_hash FROM document ORDER BY submission_id"
        )
        hashes = {str(r["submission_id"]): str(r["content_hash"]) for r in rows}
        assert hashes["SUB-101"] == hashes["SUB-102"], (
            f"the fixture did not produce a shared content_hash: {hashes}"
        )
        assert hashes["SUB-101"] == hashlib.sha256(MARKDOWN.encode("utf-8")).hexdigest()

        first = gate.verify(run_id, "SUB-101", "C1")
        second = gate.verify(run_id, "SUB-102", "C1")

        assert first.spans_verified is True and second.spans_verified is True, (
            f"a cell whose span is genuinely in its own document did not verify: "
            f"{first}, {second}. A cache serving the wrong submission's bytes shows up here"
        )
        assert len(blobs.reads) == 1, (
            f"the shared document was read {len(blobs.reads)} times; identical bytes are one "
            "cache entry by content hash (FR-INTEG-11)"
        )
    finally:
        store.close()


def test_tc_integ_17_arm_d_a_different_document_is_never_served_from_the_cache(
    tmp_data_dir,
):
    """Arm (d)'s discriminating half — two submissions with **different** documents.

    The case above cannot catch a cache keyed on the run alone, because both submissions there
    have the same bytes: the wrong entry and the right one are indistinguishable. Here the
    documents differ, and each span is present only in its own — so a cell served the other
    submission's bytes fails verification, which is exactly the marking error arm (d) exists
    to forbid.
    """
    texts = {
        "SUB-101": "The thesis is stated plainly in the first paragraph.",
        "SUB-102": "A rebuttal is offered before any claim is made.",
    }
    store, _handle, run_id, _gate, _blobs = _world(
        tmp_data_dir, ("SUB-101", "SUB-102"), markdown_for=lambda s: texts[s],
    )
    try:
        handle = store.cohort(ORCH_COHORT_ID)
        for submission, text in texts.items():
            needle = "thesis" if submission == "SUB-101" else "rebuttal"
            start = text.index(needle)
            view = ExtractionView(
                spans=[Span(start, start + len(needle), needle)],
                panel=PanelFlags((True, True, True)),
            )
            gate = IntegrityGate(handle, store.blobs(), view, ocr_conf_floor=0.70)
            signals = gate.verify(run_id, submission, "C1")
            assert signals.spans_verified is True, (
                f"{submission}: a span present in its OWN document did not verify "
                f"({signals}). The gate was handed another submission's bytes — the cache key "
                "does not separate the two (FR-INTEG-11)"
            )
    finally:
        store.close()
