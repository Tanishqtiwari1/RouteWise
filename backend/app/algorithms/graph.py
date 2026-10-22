"""Minimal directed, weighted multigraph used by the search algorithms.

The graph is deliberately independent of the database, the map provider and
the web framework: nodes are any hashable identifiers and edges carry an
arbitrary metadata mapping. Costs are *not* stored on the graph; callers pass a
cost function so the same graph can be searched under different objectives.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

NodeId = Hashable
EdgeId = Hashable


class GraphValidationError(ValueError):
    """Raised when graph input is structurally invalid."""


@dataclass(frozen=True, slots=True)
class Edge:
    id: EdgeId
    source: NodeId
    target: NodeId
    data: Mapping[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


class WeightedGraph:
    """Directed multigraph with O(1) adjacency lookup.

    Undirected roads are represented as two directed edges.
    """

    def __init__(self) -> None:
        self._adj: dict[NodeId, list[Edge]] = {}
        self._edges: dict[EdgeId, Edge] = {}
        self._node_data: dict[NodeId, dict[str, Any]] = {}

    # -- construction -----------------------------------------------------
    def add_node(self, node: NodeId, **data: Any) -> None:
        if node is None:
            raise GraphValidationError("Node identifier must not be None")
        self._adj.setdefault(node, [])
        self._node_data.setdefault(node, {}).update(data)

    def add_edge(self, edge_id: EdgeId, source: NodeId, target: NodeId, **data: Any) -> Edge:
        if edge_id in self._edges:
            raise GraphValidationError(f"Duplicate edge id: {edge_id!r}")
        if "cost" in data:
            _validate_cost(data["cost"], edge_id)
        self.add_node(source)
        self.add_node(target)
        edge = Edge(edge_id, source, target, data)
        self._adj[source].append(edge)
        self._edges[edge_id] = edge
        return edge

    @classmethod
    def from_edges(cls, edges: Iterable[tuple[NodeId, NodeId, float]]) -> WeightedGraph:
        """Build a graph from ``(source, target, cost)`` triples (ids auto-assigned)."""
        g = cls()
        for i, (u, v, c) in enumerate(edges):
            g.add_edge(i, u, v, cost=c)
        return g

    # -- queries ----------------------------------------------------------
    def has_node(self, node: NodeId) -> bool:
        return node in self._adj

    def neighbors(self, node: NodeId) -> list[Edge]:
        return self._adj.get(node, [])

    def edge(self, edge_id: EdgeId) -> Edge:
        return self._edges[edge_id]

    def has_edge(self, edge_id: EdgeId) -> bool:
        return edge_id in self._edges

    def node_data(self, node: NodeId) -> dict[str, Any]:
        return self._node_data.get(node, {})

    def nodes(self) -> Iterator[NodeId]:
        return iter(self._adj)

    def edges(self) -> Iterator[Edge]:
        return iter(self._edges.values())

    @property
    def node_count(self) -> int:
        return len(self._adj)

    @property
    def edge_count(self) -> int:
        return len(self._edges)


def _validate_cost(cost: Any, edge_id: EdgeId) -> None:
    if not isinstance(cost, (int, float)) or isinstance(cost, bool):
        raise GraphValidationError(f"Edge {edge_id!r} cost must be numeric, got {cost!r}")
    if math.isnan(cost) or math.isinf(cost):
        raise GraphValidationError(f"Edge {edge_id!r} cost must be finite, got {cost!r}")
    if cost < 0:
        raise GraphValidationError(f"Edge {edge_id!r} has negative cost {cost!r}; UCS requires non-negative costs")
