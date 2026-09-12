"""`TC-STATS-22` — the export's import graph: no engine, no egress.

Test plan §5.16 (`TC-STATS-22`), issue #120 (TS-43). Traces to
`NFR-STATS-03`. The plan's row: *"Months of accumulated labels. Statistics
computable in seconds; the optional Parquet/DuckDB export is read-only and
never touches the scoring pipeline, asserted by an import-graph check."*
Metric threshold plus import assertion, P2.

Two legs, split by what each is a claim about:

- **the seconds budget and the export's runtime read-only-ness** are
  `TC-STATS-C17`'s (`test_ct_stats_limits_and_nonpromises.py`): the timing
  over ~4,800 accumulated labels, and the export run *during* a live scoring
  run with the write audit, the lock waits and the wall-clock differential
  all asserted. Cross-referenced, not repeated.
- **the import-graph check** is this file's leg — the structural half of
  "read-only, never touches": `aeh.stats` imports **no export engine** and
  **no egress-capable root**. The shipped export is the stdlib JSON writer
  (`analytical_export`: one document under ``exports/``, no connection, no
  lock); a Parquet/DuckDB engine arriving as an unexamined dependency, or a
  provider SDK / HTTP client arriving in a module that sits beside a live
  scoring run, are the two pulls-in this graph must name on the day one
  happens. The walker is `tests.support.import_graph`'s (`TC-PROV-05`'s),
  which parses rather than greps — an aliased or dynamic import is the same
  edge.

The module's imports of the pipeline modules (``aeh.ingest``, ``aeh.judge``,
...) are the migration-chain completion `open_stats` performs and are
**import-only** — schema registration, no calls; the dynamic proof that the
export writes nothing into a running pipeline is C17's, and the two checks
deliberately cover different halves of the same clause.

Isolation: rung 0 — a static scan of the shipped module's source; no store,
no provider (`network_guard` is autouse and the case asserts it).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.import_graph import FORBIDDEN_ROOTS, scan_module
from tests.support.impl import STATS_MODULE, require

pytestmark = pytest.mark.integration

#: The export engines the clause names ("the optional Parquet/DuckDB
#: export") plus the tabular engines one would reach for instead — none may
#: be a dependency of a read-only stdlib export without a deliberate,
#: reviewed pull-in. Matched on module boundaries by the walker, so
#: `pandas_util` would not read as `pandas` and a hit names the edge.
EXPORT_ENGINE_ROOTS: tuple[str, ...] = (
    "duckdb", "pyarrow", "pandas", "polars",
)


def _stats_source() -> tuple[str, str]:
    """The shipped module's source and its repo-relative path."""
    from aeh import stats as stats_module

    require(STATS_MODULE, "analytical_export", issue="#118")  # the member exists
    source_path = Path(stats_module.__file__)
    return source_path.read_text(encoding="utf-8"), source_path.name


def test_tc_stats_22_the_export_module_imports_no_egress_capable_root(
    network_guard,
):
    """No provider SDK, no HTTP client, no egress at all.

    The module runs beside a live scoring run (`TC-STATS-C17`'s concurrent
    shape) and computes figures over store rows. An egress-capable import
    here would be a reporting tool that phones out — and `CT-PROV-15`'s
    sole-egress audit would then read two modules, not one."""
    source, name = _stats_source()
    violations = scan_module("aeh.stats", source, f"src/aeh/{name}")

    assert violations == [], (
        f"{[str(v) for v in violations]}; aeh.stats imports an "
        "egress-capable root — a reporting module that sits beside a live "
        "scoring run and holds no network seam of its own (NFR-STATS-03, "
        "TC-PROV-05's graph)"
    )
    network_guard.assert_no_network()


def test_tc_stats_22_the_optional_parquet_export_is_not_a_pulled_in_engine(
    network_guard,
):
    """No Parquet/DuckDB engine on the module's import graph.

    The optional export shipped as the stdlib JSON writer; the plan's
    Parquet/DuckDB form is the *optional* future it must not become by
    accident. An engine pulled in silently changes the export's dependency
    footprint and its failure modes — a query engine is a writer, and a
    read-only tool that grew one has stopped being read-only in any sense
    the graph can still vouch for. The check names the edge if the day
    comes: the pull-in must be a deliberate, reviewed change that updates
    this case with its reason."""
    source, name = _stats_source()
    violations = scan_module(
        "aeh.stats",
        source,
        f"src/aeh/{name}",
        forbidden=FORBIDDEN_ROOTS | frozenset(EXPORT_ENGINE_ROOTS),
    )

    assert violations == [], (
        f"{[str(v) for v in violations]}; the analytical export is the "
        "stdlib JSON writer over the instance's own figures — an export "
        "engine import (Parquet/DuckDB and kin) is the optional form "
        "arriving as an unreviewed dependency (NFR-STATS-03)"
    )
    network_guard.assert_no_network()