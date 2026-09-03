"""The generators `FUZZ-06` and `FUZZ-07` depend on, asserted before anything depends on them.

TS-56 (issue #149). §6.7 states each case's generator in its own **Generator / corpus** column,
which makes it a specification rather than a detail — and the fuzz cases themselves are red until
four modules land, so these assertions are the only thing standing between them and a degenerate
corpus.

The failure mode: only acyclic graphs, only one-node graphs, only tuples differing everywhere,
only short byte strings. The invariant still holds, over a corpus that never contained a
counterexample, and the case passes **vacuously** the moment someone removes the marker.

**These assert over the strategies, not over a copy of them.** An earlier draft asserted over a
parallel set of seeded samplers, on the premise that `require()` raises before the draw so the
strategies were unreachable. That premise was false — `require()` runs inside the test body, after
hypothesis has drawn — and review measured the cost: six degeneracies applied to the *strategies*
all survived nine green tests here, because the samplers were the only thing being checked. The
samplers are gone.

**How a whole corpus is collected.** `@given` hands over one example at a time and cannot express
"both kinds appear across the run". Drawing `st.lists(strategy, min_size=N, max_size=N)` looks
like the answer and is not: with `max_examples=1` hypothesis generates from the simplest buffer,
so the list comes back as N one-node graphs and N empty byte strings — precisely the degenerate
corpus being tested for. So each case runs its own `@given` function to completion and asserts on
what accumulated, which draws from the real strategy under the real profile.
"""

from __future__ import annotations

import collections

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.support.fuzz_strategies import (
    MAX_GRAPH_NODES,
    WORK_ID_FIELDS,
    acyclic_graphs,
    blob_payloads,
    criterion_graphs,
    cyclic_graphs,
    duplicating_topological_order,
    reversed_topological_order,
    satisfies_every_edge,
    topological_order,
    work_id_input_pairs,
    write_interleavings,
)

pytestmark = pytest.mark.property

#: Enough draws to characterize a corpus. The cases these support run at 500 (§6.7); these only
#: have to show the generator reaches its stated shapes.
CORPUS_DRAWS = 200


def collect(strategy, draws: int = CORPUS_DRAWS) -> list:
    """Run `strategy` to completion under hypothesis and return everything it produced.

    The inner `@given` function is invoked directly, which is how a corpus is obtained from the
    *real* strategy rather than from a re-implementation of it. `database=None` keeps the example
    database out of it: a corpus assertion must describe what the strategy generates, not what a
    previous failure happened to leave cached.
    """
    corpus: list = []

    @settings(max_examples=draws, deadline=None, database=None)
    @given(strategy)
    def _collect(value):
        corpus.append(value)

    _collect()
    return corpus


# --- FUZZ-06's graph generator -----------------------------------------------------------------


def test_fuzz_06_the_graph_corpus_contains_cyclic_and_acyclic_graphs():
    """§6.7: *"criterion graphs up to 30 nodes, **cyclic and acyclic**"*.

    The invariant `FUZZ-06` asserts is *"cycles always rejected"*. A corpus of DAGs satisfies it
    without ever presenting a cycle, so the case would pass against a catalog that never rejects
    anything. Both kinds must appear, and neither may be a rounding error.
    """
    corpus = collect(criterion_graphs())

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

    A generator that mostly emits one- and two-node graphs satisfies "cyclic and acyclic" and still
    never exercises an ordering: `topological_order` on two nodes is not a test of anything.

    The node assertion is against `MAX_GRAPH_NODES` exactly. An earlier `>= MAX_GRAPH_NODES - 5`
    let a generator capped at 25 pass while the message quoted 30 — a tolerance nobody chose,
    silently widening the claim.
    """
    corpus = collect(criterion_graphs())
    sizes = [len(graph.nodes) for graph in corpus]
    edge_counts = [len(graph.edges) for graph in corpus]

    assert max(sizes) == MAX_GRAPH_NODES, (
        f"the largest generated graph has {max(sizes)} nodes; §6.7 says up to {MAX_GRAPH_NODES}"
    )
    assert max(edge_counts) >= 10, (
        f"the densest generated graph has {max(edge_counts)} edges — an ordering over a graph "
        "with almost no edges is satisfied by any permutation"
    )
    assert sum(1 for size in sizes if size >= 10) >= 10, (
        "fewer than 10 graphs reach 10 nodes; the corpus is dominated by trivial cases"
    )


def test_fuzz_06_the_cyclic_generator_really_produces_cycles():
    """Every graph from `cyclic_graphs()` is cyclic — asserted, not assumed.

    The generator adds a back-edge to a DAG. If that construction were wrong the corpus would be
    all DAGs while claiming otherwise, and the "cycles always rejected" half of `FUZZ-06` would
    test nothing while looking thorough.
    """
    corpus = collect(cyclic_graphs())

    acyclic = [graph for graph in corpus if topological_order(graph) is not None]

    assert not acyclic, f"cyclic_graphs() produced {len(acyclic)} acyclic graphs, e.g. {acyclic[0]}"


# --- the reference model, and the direction of the invariant -----------------------------------


def test_fuzz_06_the_reference_model_satisfies_every_edge():
    """Kahn's algorithm satisfies `satisfies_every_edge`. The **positive** control.

    `FUZZ-06`'s invariant is asserted through `satisfies_every_edge`, so that helper is the thing
    an implementation will be judged by. If it is wrong, every judgement is wrong — and it is
    checked here against a model whose correctness is independent of anything in `src/`.
    """
    corpus = collect(acyclic_graphs())

    for graph in corpus:
        order = topological_order(graph)
        assert order is not None, "an acyclic graph has an order"
        assert satisfies_every_edge(order, graph), f"the model failed its own invariant on {graph}"


def test_fuzz_06_a_reversed_ordering_fails_the_invariant():
    """The first **negative** control, and one of two reasons this file exists.

    `(before, after)` means `before` is extracted first. Someone reading it as "after depends on
    before, so emit after first" writes `reversed_topological_order` — a legal ordering of the
    reversed graph that satisfies no edge of the real one. An invariant expressed backwards
    (`position[before] > position[after]`) accepts it and rejects the correct implementation, and
    nothing else in TS-56 would notice, because both are total orders over the same nodes.

    Edgeless graphs cannot discriminate — every ordering satisfies an empty edge set — so they are
    skipped, and the count of graphs that *did* discriminate is asserted. Without that the control
    goes vacuous the moment the generator stops producing edges, with no signal at all.
    """
    corpus = collect(acyclic_graphs())
    discriminating = 0

    for graph in corpus:
        if not graph.edges:
            continue
        discriminating += 1
        reversed_order = reversed_topological_order(graph)
        assert reversed_order is not None
        assert not satisfies_every_edge(reversed_order, graph), (
            f"the reversed ordering satisfied the invariant on {graph}, so the invariant is "
            "direction-blind and would accept an implementation that emits dependents before "
            "their dependencies"
        )

    assert discriminating >= 20, (
        f"only {discriminating}/{len(corpus)} generated graphs have any edge, so this control is "
        "nearly vacuous — a reversed ordering is indistinguishable on an edgeless graph"
    )


def test_fuzz_06_a_duplicating_ordering_fails_the_invariant():
    """The second **negative** control, added because review got past the first.

    `satisfies_every_edge` builds `position` as a dict comprehension, so a repeated node keeps its
    last index and `set(order) == set(nodes)` still holds — `['a', 'a', 'b', 'b']` was accepted for
    the edge `(a, b)`. That makes "every node, twice, in a correct order" a wrong implementation
    that is direction-correct and set-correct, and `M-ORCH` enumerates one work unit per criterion
    from this order.
    """
    corpus = collect(acyclic_graphs())
    checked = 0

    for graph in corpus:
        duplicated = duplicating_topological_order(graph)
        assert duplicated is not None
        checked += 1
        assert not satisfies_every_edge(duplicated, graph), (
            f"an order emitting every node twice satisfied the invariant on {graph}, so a "
            "duplicating implementation would produce duplicate work units unnoticed"
        )

    assert checked >= 20, "the corpus was too small to exercise the control"


# --- FUZZ-06's work-ID generator ---------------------------------------------------------------


def test_fuzz_06_every_work_id_field_varies_somewhere_in_the_corpus():
    """All nine `CT-ORCH-01` inputs must be the sole difference in at least one pair.

    *"distinct input tuples always yield distinct `work_id`s"* is satisfied trivially by tuples
    that differ in eight fields — it tests sha256, not the input set. The pair that discriminates
    differs in **one**, and `CT-ORCH-01` calls the input set contract: an implementation that
    quietly stops hashing `extractor_version` is only caught by a pair where `extractor_version`
    is the only thing that moved.
    """
    corpus = collect(work_id_input_pairs())
    varied = collections.Counter(field for _, _, field in corpus)

    missing = [field for field in WORK_ID_FIELDS if varied[field] == 0]
    assert not missing, (
        f"these work_id inputs are never the sole difference in the corpus: {missing}. An "
        "implementation that dropped one from the hash would pass FUZZ-06 unnoticed."
    )


def test_fuzz_06_every_generated_pair_differs_in_exactly_one_field():
    """The generator's own contract, checked on **every** pair.

    An earlier draft asserted outside its loop and so checked only the last of 200 draws: a
    generator perturbing a second field 5% of the time — ten bad pairs per corpus — passed. The
    case above then means nothing, because a pair differing in two fields cannot show which one
    reached the hash.
    """
    corpus = collect(work_id_input_pairs())

    for base, other, field in corpus:
        differing = [key for key in WORK_ID_FIELDS if base[key] != other[key]]
        assert differing == [field], (
            f"a pair claims to differ in {field!r} alone but differs in {differing}"
        )
        assert set(base) == set(WORK_ID_FIELDS), "a tuple is missing a CT-ORCH-01 input"


# --- FUZZ-07's generators ----------------------------------------------------------------------


def test_fuzz_07_the_blob_corpus_reaches_its_boundaries():
    """§6.7: *"Generated byte strings"* — including the ones that break a naive store.

    Three boundaries, each a real implementation bug: the **empty** blob (a store that skips falsy
    content silently returns nothing for a hash it claims to hold), a blob containing a **null
    byte** (a store that round-trips through `str` truncates there), and a **large** blob (a store
    that reads with a fixed buffer returns a prefix, and `get(put(b)) == b` is the only assertion
    that would notice).
    """
    corpus = collect(blob_payloads())

    assert any(len(payload) == 0 for payload in corpus), "no empty blob in the corpus"
    assert any(b"\x00" in payload for payload in corpus), "no null byte in any blob"
    assert max(len(payload) for payload in corpus) >= 512, (
        "every generated blob is tiny; a fixed-buffer read would round-trip perfectly"
    )


def test_fuzz_07_the_interleaving_corpus_contains_both_orders_and_an_abort():
    """§6.7: *"generated interleavings of result and status writes"*.

    Three things the corpus must contain, and the third is the one whose absence made `FUZZ-07`
    unfalsifiable. **Status before result** is the ordering that leaves a ledger claiming a unit is
    done with nothing stored against it. **An abort** is the moment `CT-STORE-03` is actually
    about — "both present or both absent after any crash" — and without it every transaction runs
    to completion, both writes always land, and the invariant is trivially true. Review proved
    that: a `transaction()` that is a bare `yield`, with no atomicity whatsoever, passed 500/500.
    """
    corpus = collect(write_interleavings())
    flattened = [entry for interleaving in corpus for entry in interleaving]

    assert any(kind == "status" for _, kind, _ in flattened), "no status-first write in the corpus"
    assert any(kind == "result" for _, kind, _ in flattened), "no result-first write in the corpus"

    aborts = sum(1 for _, _, outcome in flattened if outcome == "abort")
    assert aborts >= 20, (
        f"only {aborts} aborted transactions in the corpus. Without an abort, both writes always "
        "land and FUZZ-07's atomicity invariant holds against a store with no transaction at all."
    )

    with_both = sum(
        1 for interleaving in corpus
        if {kind for _, kind, _ in interleaving} == {"result", "status"}
    )
    assert with_both >= 20, (
        f"only {with_both}/{len(corpus)} interleavings contain both kinds of write; the ordering "
        "half of the case needs them together"
    )


def test_fuzz_07_the_interleaving_corpus_revisits_units():
    """Some unit must appear more than once in an interleaving.

    An interleaving where every entry names a different work unit cannot express a *sequence* of
    operations against one unit, which is where a partially-applied transaction shows up: abort the
    first write for `w-3`, then commit a later one, and a store without atomicity leaves a result
    with no status behind.
    """
    corpus = collect(write_interleavings())

    revisiting = sum(
        1 for interleaving in corpus
        if len({unit for unit, _, _ in interleaving}) < len(interleaving)
    )

    assert revisiting >= 20, (
        f"only {revisiting}/{len(corpus)} interleavings touch the same unit twice"
    )
