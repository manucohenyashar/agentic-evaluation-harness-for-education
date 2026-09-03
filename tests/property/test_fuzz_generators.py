"""The generators `FUZZ-06` and `FUZZ-07` depend on, asserted before anything depends on them.

TS-56 (issue #149). Both fuzz cases are written ahead of **every** module they touch, so
`require()` raises before the test body runs and the strategies are never exercised. That leaves
the generators as the untested half of a written-ahead property test — and §6.7 states each
generator in its own **Generator / corpus** column, which makes it a specification, not a detail.

A degenerate strategy is the failure mode: only acyclic graphs, only tuples that differ
everywhere, only short byte strings. The property still holds, over a corpus that never contained
a counterexample, and the case passes **vacuously** the moment someone removes the marker. Nothing
would say so.

So these run **now**, green, against no implementation at all. They are the same role the positive
control plays in `SEC-15`: proof that the machine can speak before anyone relies on its silence.

The one property expression that needs calibrating rather than sampling — `topological_order`
satisfying every edge — is checked against a reference model and a deliberately reversed variant,
because asserting it backwards passes on a reversed implementation and fails on a correct one.
"""

from __future__ import annotations

import collections
import random

import pytest
from hypothesis import given, settings

from tests.support.fuzz_strategies import (
    MAX_GRAPH_NODES,
    WORK_ID_FIELDS,
    acyclic_graphs,
    cyclic_graphs,
    reversed_topological_order,
    sample_blob_payload,
    sample_criterion_graph,
    sample_work_id_pair,
    sample_write_interleaving,
    satisfies_every_edge,
    topological_order,
)

pytestmark = pytest.mark.property

#: Enough draws to characterize a corpus without paying the fuzz budget twice. The cases these
#: support run at 500 (§6.7); these only have to show the generator reaches its stated shapes.
CORPUS_DRAWS = 120


#: §4.6's constant, so a corpus failure is reproducible by hand.
CORPUS_SEED = 20260101


_RNG_HOLDER: list[random.Random] = []


def _rng() -> random.Random:
    """One `Random` per corpus. Re-seeding per draw would return the same value every time."""
    if not _RNG_HOLDER:
        _RNG_HOLDER.append(random.Random(CORPUS_SEED))
    return _RNG_HOLDER[0]


def _draws():
    """A fresh, seeded corpus per call."""
    _RNG_HOLDER.clear()
    _RNG_HOLDER.append(random.Random(CORPUS_SEED))
    return range(CORPUS_DRAWS)


# **Why the corpus assertions use a seeded sampler and not `@given`.**
#
# The obvious shape — `@given(st.lists(criterion_graphs(), min_size=120, max_size=120))` — does the
# opposite of what it looks like. Hypothesis *shrinks* toward minimal values, so the single drawn
# list is the simplest one the strategy admits: 120 one-node graphs, 120 identical tuples, 120
# empty byte strings. That is exactly the degenerate corpus these assertions exist to reject,
# handed over by the tool meant to prevent it. Measured on the first draft: all five corpus
# assertions failed, in 125 seconds.
#
# §6.7's seed policy for both cases is **"Fixed seed set"**, so a seeded sampler is what the plan
# asks for rather than a workaround. The hypothesis strategies stay — the fuzz cases need shrinking
# to report a readable counterexample — and share their construction with the samplers.


# --- FUZZ-06's graph generator -----------------------------------------------------------------


def test_fuzz_06_the_graph_corpus_contains_cyclic_and_acyclic_graphs():
    """§6.7: *"criterion graphs up to 30 nodes, **cyclic and acyclic**"*.

    The invariant `FUZZ-06` asserts is *"cycles always rejected"*. A corpus of DAGs satisfies it
    without ever presenting a cycle, so the case would pass against an implementation that never
    rejects anything. Both kinds must appear, and neither may be a rounding error.
    """
    corpus = [sample_criterion_graph(_rng()) for _ in _draws()]
    cyclic = sum(1 for graph in corpus if graph.is_cyclic)
    acyclic = len(corpus) - cyclic

    assert cyclic >= 10, (
        f"only {cyclic}/{len(corpus)} generated graphs are cyclic. FUZZ-06's 'cycles always "
        "rejected' invariant never fires against a corpus of DAGs."
    )
    assert acyclic >= 10, (
        f"only {acyclic}/{len(corpus)} generated graphs are acyclic. 'topological_order always "
        "satisfies every edge' is unreachable when every graph is rejected first."
    )


def test_fuzz_06_the_graph_corpus_reaches_the_stated_node_ceiling():
    """*"up to 30 nodes"* — the corpus must actually get there, and must carry real edges.

    A generator that mostly emits one- and two-node graphs satisfies "cyclic and acyclic" and
    still never exercises an ordering: `topological_order` on two nodes is not a test of anything.
    """
    corpus = [sample_criterion_graph(_rng()) for _ in _draws()]
    sizes = [len(graph.nodes) for graph in corpus]
    edge_counts = [len(graph.edges) for graph in corpus]

    assert max(sizes) >= MAX_GRAPH_NODES - 5, (
        f"the largest generated graph has {max(sizes)} nodes; §6.7 says up to {MAX_GRAPH_NODES}"
    )
    assert max(edge_counts) >= 10, (
        f"the densest generated graph has {max(edge_counts)} edges — an ordering over a graph "
        "with almost no edges is satisfied by any permutation"
    )
    assert sum(1 for size in sizes if size >= 10) >= 10, (
        "fewer than 10 graphs reach 10 nodes; the corpus is dominated by trivial cases"
    )


# --- the reference model, and the direction of the invariant -----------------------------------


@given(acyclic_graphs())
@settings(max_examples=CORPUS_DRAWS, deadline=None)
def test_fuzz_06_the_reference_model_satisfies_every_edge(graph):
    """Kahn's algorithm satisfies `satisfies_every_edge`. The **positive** control.

    `FUZZ-06`'s invariant is asserted through `satisfies_every_edge`, so that helper is the thing
    an implementation will be judged by. If it is wrong, every judgement is wrong — and it is
    checked here against a model whose correctness is independent of anything in `src/`.
    """
    order = topological_order(graph)

    assert order is not None, "an acyclic graph has an order"
    assert satisfies_every_edge(order, graph)


@given(acyclic_graphs())
@settings(max_examples=CORPUS_DRAWS, deadline=None)
def test_fuzz_06_a_reversed_ordering_fails_the_invariant(graph):
    """The **negative** control, and the reason this file exists.

    `(before, after)` means `before` is extracted first. Someone reading it as "after depends on
    before, so emit after first" writes `reversed_topological_order` — a legal ordering of the
    reversed graph that satisfies no edge of the real one. An invariant expressed backwards
    (`position[before] > position[after]`) accepts it and rejects the correct implementation, and
    nothing else in TS-56 would notice, because both are total orders over the same nodes.

    Graphs with no edges are excluded: every ordering satisfies an empty edge set, so they cannot
    discriminate and their presence would make this assertion false for the wrong reason.
    """
    if not graph.edges:
        return

    reversed_order = reversed_topological_order(graph)

    assert reversed_order is not None
    assert not satisfies_every_edge(reversed_order, graph), (
        "the reversed ordering satisfied the invariant, so the invariant is direction-blind and "
        "would accept an implementation that emits dependents before their dependencies"
    )


@given(cyclic_graphs())
@settings(max_examples=CORPUS_DRAWS, deadline=None)
def test_fuzz_06_the_cyclic_generator_really_produces_cycles(graph):
    """Every graph from `cyclic_graphs()` is cyclic — asserted, not assumed.

    The generator adds a back-edge to a DAG. If that construction were wrong the corpus would be
    all DAGs while claiming otherwise, and the "cycles always rejected" half of `FUZZ-06` would
    test nothing while looking thorough.
    """
    assert topological_order(graph) is None, (
        f"cyclic_graphs() produced an acyclic graph: {graph.nodes} {graph.edges}"
    )


# --- FUZZ-06's work-ID generator ---------------------------------------------------------------


def test_fuzz_06_every_work_id_field_varies_somewhere_in_the_corpus():
    """All nine `CT-ORCH-01` inputs must be the sole difference in at least one pair.

    *"distinct input tuples always yield distinct `work_id`s"* is satisfied trivially by tuples
    that differ in eight fields — it tests sha256, not the input set. The pair that discriminates
    differs in **one**, and `CT-ORCH-01` calls the input set contract: an implementation that
    quietly stops hashing `extractor_version` is only caught by a pair where `extractor_version`
    is the only thing that moved.
    """
    corpus = [sample_work_id_pair(_rng()) for _ in _draws()]
    varied = collections.Counter(field for _, _, field in corpus)

    missing = [field for field in WORK_ID_FIELDS if varied[field] == 0]
    assert not missing, (
        f"these work_id inputs are never the sole difference in the corpus: {missing}. An "
        "implementation that dropped one from the hash would pass FUZZ-06 unnoticed."
    )


def test_fuzz_06_each_generated_pair_differs_in_exactly_one_field():
    """The generator's own contract, so the case above means what it says."""
    rng = _rng()
    for _ in _draws():
        base, other, field = sample_work_id_pair(rng)

    differing = [key for key in WORK_ID_FIELDS if base[key] != other[key]]

    assert differing == [field], (
        f"the pair claims to differ in {field!r} alone but differs in {differing}"
    )
    assert set(base) == set(WORK_ID_FIELDS), "a tuple is missing a CT-ORCH-01 input"


# --- FUZZ-07's generators ----------------------------------------------------------------------


def test_fuzz_07_the_blob_corpus_reaches_its_boundaries():
    """§6.7: *"Generated byte strings"* — including the ones that break a naive store.

    Three boundaries, each a real implementation bug: the **empty** blob (a store that skips
    falsy content silently returns nothing for a hash it claims to hold), a blob containing a
    **null byte** (a store that round-trips through `str` truncates there), and a **large** blob
    (a store that reads with a fixed buffer returns a prefix, and `get(put(b)) == b` is the only
    assertion that would notice).
    """
    corpus = [sample_blob_payload(_rng()) for _ in _draws()]

    assert any(len(payload) == 0 for payload in corpus), "no empty blob in the corpus"
    assert any(b"\x00" in payload for payload in corpus), "no null byte in any blob"
    assert max(len(payload) for payload in corpus) >= 512, (
        "every generated blob is tiny; a fixed-buffer read would round-trip perfectly"
    )


def test_fuzz_07_the_interleaving_corpus_contains_both_orders():
    """§6.7: *"generated interleavings of result and status writes"*.

    The interleaving that matters is **status before result** — it is the one that leaves a ledger
    claiming a unit is done with nothing stored against it, which is what `FR-STORE-04`'s single
    transaction exists to prevent. A corpus that only ever writes result-then-status describes the
    happy path and would pass against an implementation with no transaction at all.
    """
    corpus = [sample_write_interleaving(_rng()) for _ in _draws()]
    status_first = 0
    result_first = 0
    for interleaving in corpus:
        seen: dict[int, str] = {}
        for unit, kind in interleaving:
            if unit not in seen:
                seen[unit] = kind
        if "status" in seen.values():
            status_first += 1
        if "result" in seen.values():
            result_first += 1

    assert status_first >= 10, (
        f"only {status_first}/{len(corpus)} interleavings write a status before its result — the "
        "ordering FR-STORE-04's single transaction exists to make unobservable"
    )
    assert result_first >= 10, f"only {result_first}/{len(corpus)} write a result first"
