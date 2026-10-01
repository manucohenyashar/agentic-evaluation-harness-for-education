"""The criterion dependency graph: the order it implies, and refusing a cycle."""

from __future__ import annotations

from .vocabulary import PackageVersionId
from .errors import CyclicDependencyError
from .statements import PKG_STATEMENTS


class DependencyGraphMixin:
    """Reads the dependency graph and refuses edges that would make it cyclic."""

    def topological_order(self, v: PackageVersionId) -> tuple[str, ...]:
        """The criteria in dependency order, dependencies first: the order M-ORCH extracts in
        (FR-PKG-05)."""
        return self._toposort(self._version_graph(v))

    def dependency_graph(self, v: PackageVersionId) -> dict[str, tuple[str, ...]]:
        """The version's dependency graph: each criterion mapped to its direct dependencies, sorted
        (FR-PKG-05). Every criterion appears as a key. M-ORCH uses the edges for its scoring gate
        (FR-ORCH-06) and `topological_order` for extraction order."""
        graph = self._version_graph(v)
        return {
            criterion_id: tuple(sorted(deps))
            for criterion_id, deps in graph.items()
        }

    def _version_graph(self, v: PackageVersionId) -> dict[str, set[str]]:
        graph: dict[str, set[str]] = {
            row["criterion_id"]: set()
            for row in self._handle.query(PKG_STATEMENTS["select_criteria"], v=v)
        }
        for row in self._handle.query(PKG_STATEMENTS["select_dependencies"], v=v):
            graph.setdefault(row["criterion_id"], set()).add(row["depends_on"])
            graph.setdefault(row["depends_on"], set())
        return graph

    def _assert_acyclic(self, graph: dict[str, set[str]]) -> None:
        """Check the graph has no cycle, using Kahn's algorithm: an acyclic graph uses up every
        node, and whatever is left over is the cycle (FR-PKG-05)."""
        remaining = {node: set(edges) for node, edges in graph.items()}
        consumed: set[str] = set()
        while remaining:
            ready = [node for node, edges in remaining.items() if edges <= consumed]
            if not ready:
                cycle = sorted(next(iter(remaining.values())) | set(remaining))
                raise CyclicDependencyError(
                    f"the dependency graph is cyclic among {cycle}. The extraction "
                    "sweep's two-pass order (FR-PKG-05) rests on the graph being a DAG."
                )
            for node in ready:
                consumed.add(node)
                del remaining[node]

    def _toposort(self, graph: dict[str, set[str]]) -> tuple[str, ...]:
        """Kahn's algorithm with ready nodes taken in sorted order, so the extraction order is
        reproducible."""
        remaining = {node: set(edges) for node, edges in graph.items()}
        consumed: set[str] = set()
        order: list[str] = []
        while remaining:
            ready = sorted(node for node, edges in remaining.items()
                           if edges <= consumed)
            if not ready:
                raise CyclicDependencyError(
                    f"the dependency graph is cyclic among {sorted(remaining)}."
                )
            for node in ready:
                order.append(node)
                consumed.add(node)
                del remaining[node]
        return tuple(order)
