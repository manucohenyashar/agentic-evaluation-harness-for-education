"""The criterion dependency graph: the order it implies, and refusing a cycle."""

from __future__ import annotations

from .vocabulary import PackageVersionId
from .errors import CyclicDependencyError
from .statements import PKG_STATEMENTS


class DependencyGraphMixin:
    """Reads the dependency graph and refuses edges that would make it cyclic."""

    def topological_order(self, v: PackageVersionId) -> tuple[str, ...]:
        """A valid topological order over the version's dependency graph — dependencies
        before dependents, which is `M-ORCH`'s extraction sweep order (`FR-PKG-05`)."""
        return self._toposort(self._version_graph(v))

    def dependency_graph(self, v: PackageVersionId) -> dict[str, tuple[str, ...]]:
        """The version's dependency topology, criterion -> its direct dependencies
        (`FR-PKG-05`) — the read side of `set_dependencies`, over the same graph
        `topological_order` sorts. `M-ORCH` consumes the topology rather than
        re-deriving it: the extraction sweep's order is `topological_order`'s, and the
        scoring gate (`FR-ORCH-06`) needs the edges themselves. Every criterion of the
        version appears as a key, dependencies sorted — deterministic where nothing
        depends on the order."""
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
        """Kahn's algorithm: a DAG consumes every node; whatever remains is the cycle
        (`FR-PKG-05`)."""
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
        """Kahn's algorithm, deterministic: ready nodes emit in sorted order so the
        extraction sweep's order is reproducible."""
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
