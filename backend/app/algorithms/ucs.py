"""Uniform Cost Search (UCS) over a :class:`WeightedGraph`.

UCS expands states in non-decreasing order of cumulative path cost g(n) using a
binary heap (``heapq``). With non-negative edge costs the first time a node is
popped with its best-known cost, that cost is optimal, so the goal test is
performed on *pop*, never on push.

The heap may contain several entries for the same node (we use lazy deletion
instead of decrease-key). An entry is *stale* when its cost is greater than the
best cost recorded for the node or when the node was already settled; stale
entries are skipped.

Complexity (V nodes, E edges): O((V + E) log V) time with lazy deletion
(at most E heap entries), O(V + E) memory.
"""

from __future__ import annotations

import heapq
import itertools
import math
import time
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .graph import Edge, EdgeId, GraphValidationError, NodeId, WeightedGraph

CostFn = Callable[[Edge], float | None]
"""Returns the non-negative objective cost of traversing an edge, or ``None``
when the edge is not traversable for this search (e.g. vehicle restriction)."""


class SearchStatus(StrEnum):
    FOUND = "found"
    NO_ROUTE = "no_route"
    LIMIT_EXCEEDED = "limit_exceeded"
    CANCELLED = "cancelled"


class NegativeCostError(GraphValidationError):
    pass


@dataclass(slots=True)
class SearchStats:
    expanded_nodes: int = 0
    relaxations: int = 0
    improvements: int = 0
    heap_pushes: int = 0
    heap_pops: int = 0
    stale_skipped: int = 0
    blocked_edges_skipped: int = 0
    restricted_edges_skipped: int = 0
    max_frontier_size: int = 0
    duration_ms: float = 0.0

    @property
    def queue_operations(self) -> int:
        return self.heap_pushes + self.heap_pops

    def as_dict(self) -> dict[str, Any]:
        return {
            "expanded_nodes": self.expanded_nodes,
            "relaxations": self.relaxations,
            "improvements": self.improvements,
            "heap_pushes": self.heap_pushes,
            "heap_pops": self.heap_pops,
            "queue_operations": self.queue_operations,
            "stale_skipped": self.stale_skipped,
            "blocked_edges_skipped": self.blocked_edges_skipped,
            "restricted_edges_skipped": self.restricted_edges_skipped,
            "max_frontier_size": self.max_frontier_size,
            "duration_ms": round(self.duration_ms, 3),
        }


@dataclass(slots=True)
class ReconstructionStep:
    node: NodeId
    via_edge: EdgeId | None
    edge_cost: float
    cumulative_cost: float


@dataclass(slots=True)
class TraceEvent:
    """One step of the search, recorded only when tracing is enabled."""

    kind: str  # push | pop | stale | relax | improve | goal
    node: NodeId
    cost: float
    parent: NodeId | None = None
    edge: EdgeId | None = None


@dataclass(slots=True)
class UCSResult:
    status: SearchStatus
    start: NodeId
    goal: NodeId
    node_path: list[NodeId] = field(default_factory=list)
    edge_path: list[EdgeId] = field(default_factory=list)
    total_cost: float = math.inf
    steps: list[ReconstructionStep] = field(default_factory=list)
    stats: SearchStats = field(default_factory=SearchStats)
    warnings: list[str] = field(default_factory=list)
    message: str = ""
    trace: list[TraceEvent] = field(default_factory=list)
    trace_truncated: bool = False

    @property
    def found(self) -> bool:
        return self.status is SearchStatus.FOUND


@dataclass(slots=True)
class SearchLimits:
    max_expansions: int | None = None
    time_limit_s: float | None = None
    cancel: Callable[[], bool] | None = None
    """Polled every ``cancel_check_interval`` expansions; return True to abort."""
    cancel_check_interval: int = 256


def default_cost(edge: Edge) -> float | None:
    return edge.get("cost")


class _Search:
    """Single-source UCS core shared by the one-to-one and one-to-many APIs."""

    def __init__(
        self,
        graph: WeightedGraph,
        start: NodeId,
        cost_fn: CostFn,
        blocked_edges: Collection[EdgeId] | None,
        limits: SearchLimits | None,
        trace_limit: int,
    ) -> None:
        if not graph.has_node(start):
            raise GraphValidationError(f"Start node {start!r} is not in the graph")
        self.graph = graph
        self.start = start
        self.cost_fn = cost_fn
        self.blocked = blocked_edges or frozenset()
        self.limits = limits or SearchLimits()
        self.trace_limit = trace_limit
        self.trace: list[TraceEvent] = []
        self.trace_truncated = False
        self.stats = SearchStats()
        self.best: dict[NodeId, float] = {start: 0.0}
        self.parent: dict[NodeId, tuple[NodeId, Edge, float] | None] = {start: None}
        self.settled: set[NodeId] = set()
        self._abort: SearchStatus | None = None

    def _record(self, kind: str, node: NodeId, cost: float, parent: NodeId | None = None, edge: EdgeId | None = None) -> None:
        if not self.trace_limit:
            return
        if len(self.trace) >= self.trace_limit:
            self.trace_truncated = True
            return
        self.trace.append(TraceEvent(kind, node, cost, parent, edge))

    def run(self, goals: Collection[NodeId]) -> SearchStatus:
        """Expand until every goal is settled, the frontier empties or a limit hits."""
        t0 = time.perf_counter()
        deadline = t0 + self.limits.time_limit_s if self.limits.time_limit_s else None
        remaining = set(goals)
        counter = itertools.count()  # FIFO tie-breaker keeps results deterministic
        heap: list[tuple[float, int, NodeId]] = [(0.0, next(counter), self.start)]
        self.stats.heap_pushes = 1
        self._record("push", self.start, 0.0)
        status = SearchStatus.NO_ROUTE

        try:
            while heap:
                cost, _, node = heapq.heappop(heap)
                self.stats.heap_pops += 1

                # Lazy deletion: skip entries superseded by a cheaper path.
                if node in self.settled or cost > self.best.get(node, math.inf):
                    self.stats.stale_skipped += 1
                    self._record("stale", node, cost)
                    continue

                self.settled.add(node)
                self.stats.expanded_nodes += 1
                p = self.parent[node]
                self._record("pop", node, cost, p[0] if p else None, p[1].id if p else None)

                # Goal test on pop: cost is now provably minimal.
                if node in remaining:
                    remaining.discard(node)
                    self._record("goal", node, cost)
                    if not remaining:
                        status = SearchStatus.FOUND
                        break

                if self._limit_hit(deadline):
                    break

                for edge in self.graph.neighbors(node):
                    if edge.id in self.blocked:
                        self.stats.blocked_edges_skipped += 1
                        continue
                    w = self.cost_fn(edge)
                    if w is None:
                        self.stats.restricted_edges_skipped += 1
                        continue
                    if not isinstance(w, (int, float)) or math.isnan(w) or math.isinf(w):
                        raise GraphValidationError(f"Edge {edge.id!r} produced invalid cost {w!r}")
                    if w < 0:
                        raise NegativeCostError(f"Edge {edge.id!r} produced negative cost {w!r}; UCS requires non-negative costs")
                    v = edge.target
                    if v in self.settled:
                        continue
                    self.stats.relaxations += 1
                    new_cost = cost + w
                    self._record("relax", v, new_cost, node, edge.id)
                    if new_cost < self.best.get(v, math.inf):
                        self.best[v] = new_cost
                        self.parent[v] = (node, edge, w)
                        self.stats.improvements += 1
                        heapq.heappush(heap, (new_cost, next(counter), v))
                        self.stats.heap_pushes += 1
                        self._record("improve", v, new_cost, node, edge.id)
                if len(heap) > self.stats.max_frontier_size:
                    self.stats.max_frontier_size = len(heap)
            else:
                status = SearchStatus.NO_ROUTE
            if status is not SearchStatus.FOUND and self._abort is not None:
                status = self._abort
        finally:
            self.stats.duration_ms = (time.perf_counter() - t0) * 1000
        return status

    def _limit_hit(self, deadline: float | None) -> bool:
        lim = self.limits
        if lim.max_expansions is not None and self.stats.expanded_nodes >= lim.max_expansions:
            self._abort = SearchStatus.LIMIT_EXCEEDED
            return True
        if self.stats.expanded_nodes % max(1, lim.cancel_check_interval) == 0:
            if deadline is not None and time.perf_counter() > deadline:
                self._abort = SearchStatus.LIMIT_EXCEEDED
                return True
            if lim.cancel is not None and lim.cancel():
                self._abort = SearchStatus.CANCELLED
                return True
        return False

    def reconstruct(self, goal: NodeId) -> tuple[list[NodeId], list[EdgeId], list[ReconstructionStep]]:
        nodes: list[NodeId] = []
        edges: list[EdgeId] = []
        rev: list[tuple[NodeId, Edge | None, float]] = []
        cur: NodeId | None = goal
        guard = 0
        while cur is not None:
            entry = self.parent[cur]
            rev.append((cur, entry[1] if entry else None, entry[2] if entry else 0.0))
            cur = entry[0] if entry else None
            guard += 1
            if guard > len(self.parent) + 1:  # pragma: no cover - defensive
                raise RuntimeError("Cycle detected while reconstructing route")
        rev.reverse()
        steps: list[ReconstructionStep] = []
        acc = 0.0
        for node, edge, w in rev:
            acc += w
            nodes.append(node)
            if edge is not None:
                edges.append(edge.id)
            steps.append(ReconstructionStep(node, edge.id if edge else None, w, acc))
        return nodes, edges, steps


def uniform_cost_search(
    graph: WeightedGraph,
    start: NodeId,
    goal: NodeId,
    cost_fn: CostFn = default_cost,
    *,
    blocked_edges: Collection[EdgeId] | None = None,
    limits: SearchLimits | None = None,
    trace_limit: int = 0,
) -> UCSResult:
    """Find the minimum-cost path from ``start`` to ``goal``.

    Raises :class:`GraphValidationError` for unknown nodes or invalid costs and
    :class:`NegativeCostError` when any relaxed edge has a negative cost.
    """
    if not graph.has_node(goal):
        raise GraphValidationError(f"Goal node {goal!r} is not in the graph")
    search = _Search(graph, start, cost_fn, blocked_edges, limits, trace_limit)
    status = search.run({goal})
    result = UCSResult(status=status, start=start, goal=goal, stats=search.stats,
                       trace=search.trace, trace_truncated=search.trace_truncated)
    if status is SearchStatus.FOUND:
        result.node_path, result.edge_path, result.steps = search.reconstruct(goal)
        result.total_cost = search.best[goal]
        if start == goal:
            result.warnings.append("Start and goal are the same node; the route is empty with zero cost.")
        result.message = "Route found"
    elif status is SearchStatus.NO_ROUTE:
        result.message = "No route exists between the start and goal with the current closures and restrictions."
    elif status is SearchStatus.LIMIT_EXCEEDED:
        result.message = "Search stopped after reaching its configured expansion or time limit."
    else:
        result.message = "Search was cancelled."
    return result


@dataclass(slots=True)
class OneToManyResult:
    status: SearchStatus
    costs: dict[NodeId, float]
    paths: dict[NodeId, tuple[list[NodeId], list[EdgeId]]]
    unreachable: list[NodeId]
    stats: SearchStats


def ucs_one_to_many(
    graph: WeightedGraph,
    start: NodeId,
    goals: Iterable[NodeId],
    cost_fn: CostFn = default_cost,
    *,
    blocked_edges: Collection[EdgeId] | None = None,
    limits: SearchLimits | None = None,
) -> OneToManyResult:
    """Single UCS run that settles several goals (used for multi-stop matrices)."""
    goal_set = set(goals)
    for g in goal_set:
        if not graph.has_node(g):
            raise GraphValidationError(f"Goal node {g!r} is not in the graph")
    search = _Search(graph, start, cost_fn, blocked_edges, limits, 0)
    status = search.run(goal_set)
    costs: dict[NodeId, float] = {}
    paths: dict[NodeId, tuple[list[NodeId], list[EdgeId]]] = {}
    unreachable: list[NodeId] = []
    for g in goal_set:
        if g in search.settled:
            costs[g] = search.best[g]
            n, e, _ = search.reconstruct(g)
            paths[g] = (n, e)
        else:
            unreachable.append(g)
    if status is SearchStatus.NO_ROUTE and not unreachable:
        status = SearchStatus.FOUND
    return OneToManyResult(status, costs, paths, unreachable, search.stats)
