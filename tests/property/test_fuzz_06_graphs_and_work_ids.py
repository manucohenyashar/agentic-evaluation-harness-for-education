"""`FUZZ-06` — dependency graphs and work-ID derivation. Test plan §6.7, TS-56 (issue #149).

| Target | Invariant |
|---|---|
| `FR-PKG-05` | Cycles always rejected; `topological_order` always satisfies every edge |
| `FR-ORCH-01` | Distinct input tuples always yield distinct `work_id`s |

**Split into two tests, keyed on two blockers.** The row is one case, but its halves target
different modules and become runnable at different moments: the graph half needs `M-PKG` (#28) and
the work-ID half needs `M-ORCH` (#57). #57 depends on #11, #4 *and* #28, so keying the whole case
on the later blocker would park the graph half behind a story it does not need — red for one story
longer than necessary, which is the same "which single blocker, resolved, makes this runnable"
question that moved `TC-CONF-17` to #57 and `TC-CONF-C14` step 3 to #122.

**Both halves are genuinely written ahead**, and here the issue's flag is accurate — unlike TS-04,
TS-58 and TS-57, where it had gone stale. Neither `aeh.pkg` nor `aeh.orch` exists.

**The generators are tested separately and run green today** (`test_fuzz_generators.py`). That is
not decoration: `require()` raises before these bodies run, so the strategies are the untested half
of a written-ahead property test, and a degenerate corpus makes the invariant hold vacuously the
day someone removes the marker. `satisfies_every_edge` is calibrated there against a reference
implementation *and* a deliberately reversed one, because the ordering property is easy to express
backwards and a backwards expression accepts exactly the implementation it should reject.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings

from tests.support.fuzz_strategies import (
    WORK_ID_FIELDS,
    acyclic_graphs,
    criterion_graphs,
    satisfies_every_edge,
    work_id_input_pairs,
)
from tests.support.impl import ORCH_MODULE, PKG_MODULE, require

pytestmark = pytest.mark.property

#: §6.7's **Examples per run** column for `FUZZ-06` and `FUZZ-07`: *"500 in CI"*.
#:
#: Overrides the loaded profile rather than relying on it — `tests/conftest.py` registers `ci` at
#: `max_examples=200` per §4.7's command table, so the two documents disagree and the row that is
#: specific to these cases wins. Reported in the PR so one of them gets corrected.
#:
#: `deadline=None` because the default profile carries hypothesis's 200 ms per-example deadline,
#: and a real `topological_order` over a 30-node graph plus a database round trip has no reason to
#: fit in it. `derandomize` comes from the profile and is §6.7's *"Fixed seed set"* policy.
FUZZ_EXAMPLES = 500


# --- FR-PKG-05: the dependency graph ------------------------------------------------------------


@pytest.mark.writtenahead
@settings(max_examples=FUZZ_EXAMPLES, deadline=None)
@given(criterion_graphs())
def test_fuzz_06_a_cyclic_dependency_write_is_always_rejected(graph):
    """*"Cycles always rejected"* — over generated graphs, not chosen ones.

    `FR-PKG-05` rejects a write that *would make* the graph cyclic, raising
    `CyclicDependencyError`, and `CT-PKG-06` sharpens it: the rejection happens **at write time,
    never at read time**. That distinction is the case: a catalog that accepted the write and
    raised later when `topological_order` was called would satisfy "cycles are detected" while
    leaving a published package whose extraction sweep cannot run.

    So the assertion is on the write, and an acyclic graph in the same corpus must be *accepted* —
    a catalog that rejected everything would otherwise pass.
    """
    catalog_module = require(PKG_MODULE, issue="#28")
    CyclicDependencyError = require(PKG_MODULE, "CyclicDependencyError", issue="#28")

    catalog = catalog_module.in_memory_catalog()
    version = catalog.create_version(None, catalog_module.PackageDraft(criteria=graph.nodes))

    if graph.is_cyclic:
        with pytest.raises(CyclicDependencyError):
            catalog.set_dependencies(version, graph.edges)
    else:
        catalog.set_dependencies(version, graph.edges)
        assert catalog.topological_order(version), "an accepted graph must be orderable"


@pytest.mark.writtenahead
@settings(max_examples=FUZZ_EXAMPLES, deadline=None)
@given(acyclic_graphs())
def test_fuzz_06_topological_order_always_satisfies_every_edge(graph):
    """*"`topological_order` always satisfies every edge"*.

    Asserted through `satisfies_every_edge`, which is calibrated in `test_fuzz_generators.py`
    against Kahn's algorithm and against a reversed variant — so this case rejects an ordering that
    emits dependents before their dependencies, rather than accepting it because the comparison was
    written the wrong way round.

    Two further clauses from `CT-PKG-06` ride along and neither is redundant: the order covers
    **every** judged criterion (an implementation returning only the constrained ones satisfies
    every edge and loses the rest), and it is **stable for a given version** (`M-ORCH`'s extraction
    sweep enumerates from it, and `NFR-ORCH-05` requires enumeration to be byte-identical across
    runs — an unstable order changes every `work_id` downstream).
    """
    catalog_module = require(PKG_MODULE, issue="#28")

    catalog = catalog_module.in_memory_catalog()
    version = catalog.create_version(None, catalog_module.PackageDraft(criteria=graph.nodes))
    catalog.set_dependencies(version, graph.edges)

    order = catalog.topological_order(version)

    assert set(order) == set(graph.nodes), (
        "topological_order dropped or invented criteria; CT-PKG-06 returns every judged criterion"
    )
    assert satisfies_every_edge(order, graph), (
        f"the order {list(order)} violates an edge of {graph.edges}"
    )
    assert list(catalog.topological_order(version)) == list(order), (
        "the order is not stable for a version, so enumeration cannot be deterministic "
        "(CT-PKG-06, NFR-ORCH-05)"
    )


# --- FR-ORCH-01: work-ID derivation --------------------------------------------------------------


@pytest.mark.writtenahead
@settings(max_examples=FUZZ_EXAMPLES, deadline=None)
@given(work_id_input_pairs())
def test_fuzz_06_distinct_input_tuples_always_yield_distinct_work_ids(pair):
    """*"distinct input tuples always yield distinct `work_id`s"*.

    The generated pairs differ in **exactly one** of `CT-ORCH-01`'s nine inputs, and the corpus is
    asserted elsewhere to vary each of the nine somewhere. That is what makes this more than a test
    of sha256: an implementation that quietly stopped hashing `extractor_version` produces equal
    ids for a pair differing only there, and `CT-ORCH-01` calls the input set contract precisely
    because changing it invalidates every stored result.

    R14 is the risk underneath: stale results must be *structurally* unreusable rather than
    manually cleaned up. A dropped input silently makes yesterday's verdict look like today's.
    """
    base, other, field = pair

    orch = require(ORCH_MODULE, issue="#57")
    compute = require(ORCH_MODULE, "compute_work_id", issue="#57")

    assert compute(**base) != compute(**other), (
        f"two tuples differing only in {field!r} produced the same work_id, so that input is not "
        "reaching the hash (FR-ORCH-01, CT-ORCH-01, R14)"
    )
    assert compute(**base) == compute(**base), "work_id is not a function of its inputs"
    assert set(base) == set(WORK_ID_FIELDS)
    assert orch is not None
