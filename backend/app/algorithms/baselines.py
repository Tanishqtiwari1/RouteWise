"""Comparison algorithms. These are NOT used for the primary route.

* :func:`astar_search` — A* with a caller-supplied heuristic. Used only for
  benchmarking against UCS; with an admissible and consistent heuristic it
  returns the same optimal cost as UCS while usually expanding fewer nodes.
* :func:`greedy_best_first` — expands the node with the smallest heuristic
  value only. Fast but not optimal; included as a naive baseline.
* :func:`haversine_m` — great-circle distance used to build heuristics.
"""

from __future__ import annotations

import heapq
import itertools
import math
import time
from collections.abc import Callable, Collection

from .graph import EdgeId, GraphValidationError, NodeId, WeightedGraph
from .ucs import CostFn, NegativeCostError, SearchStats, SearchStatus, UCSResult

Heuristic = Callable[[NodeId], float]

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def straight_line_heuristic(graph: WeightedGraph, goal: NodeId, cost_per_metre: float) -> Heuristic:
    """h(n) = straight-line metres to goal × a lower bound on cost per metre.

    Admissible when every edge costs at least ``cost_per_metre`` × its length and
    edge lengths are never shorter than the great-circle distance between their
    endpoints (true for lengths measured along OSM geometry).
    """
    g = graph.node_data(goal)
    glat, glon = g["lat"], g["lon"]

    def h(n: NodeId) -> float:
        d = graph.node_data(n)
        return haversine_m(d["lat"], d["lon"], glat, glon) * cost_per_metre

    return h


def _reconstruct(parent: dict, goal: NodeId) -> tuple[list[NodeId], list[EdgeId]]:
    nodes: list[NodeId] = []
    edges: list[EdgeId] = []
    cur = goal
    while cur is not None:
        nodes.append(cur)
        p = parent[cur]
        if p is None:
            break
        edges.append(p[1])
        cur = p[0]
    nodes.reverse()
    edges.reverse()
    return nodes, edges


def astar_search(
    graph: WeightedGraph,
    start: NodeId,
    goal: NodeId,
    cost_fn: CostFn,
    heuristic: Heuristic,
    *,
    blocked_edges: Collection[EdgeId] | None = None,
    max_expansions: int | None = None,
) -> UCSResult:
    for n in (start, goal):
        if not graph.has_node(n):
            raise GraphValidationError(f"Node {n!r} is not in the graph")
    blocked = blocked_edges or frozenset()
    stats = SearchStats()
    t0 = time.perf_counter()
    counter = itertools.count()
    best = {start: 0.0}
    parent: dict[NodeId, tuple[NodeId, EdgeId] | None] = {start: None}
    closed: set[NodeId] = set()
    heap = [(heuristic(start), next(counter), 0.0, start)]
    stats.heap_pushes = 1
    status = SearchStatus.NO_ROUTE
    while heap:
        _, _, g, node = heapq.heappop(heap)
        stats.heap_pops += 1
        if node in closed or g > best.get(node, math.inf):
            stats.stale_skipped += 1
            continue
        closed.add(node)
        stats.expanded_nodes += 1
        if node == goal:
            status = SearchStatus.FOUND
            break
        if max_expansions is not None and stats.expanded_nodes >= max_expansions:
            status = SearchStatus.LIMIT_EXCEEDED
            break
        for edge in graph.neighbors(node):
            if edge.id in blocked:
                stats.blocked_edges_skipped += 1
                continue
            w = cost_fn(edge)
            if w is None:
                stats.restricted_edges_skipped += 1
                continue
            if w < 0:
                raise NegativeCostError(f"Edge {edge.id!r} produced negative cost {w!r}")
            v = edge.target
            if v in closed:
                continue
            stats.relaxations += 1
            ng = g + w
            if ng < best.get(v, math.inf):
                best[v] = ng
                parent[v] = (node, edge.id)
                stats.improvements += 1
                heapq.heappush(heap, (ng + heuristic(v), next(counter), ng, v))
                stats.heap_pushes += 1
        stats.max_frontier_size = max(stats.max_frontier_size, len(heap))
    stats.duration_ms = (time.perf_counter() - t0) * 1000
    res = UCSResult(status=status, start=start, goal=goal, stats=stats)
    if status is SearchStatus.FOUND:
        res.node_path, res.edge_path = _reconstruct(parent, goal)
        res.total_cost = best[goal]
    return res


def greedy_best_first(
    graph: WeightedGraph,
    start: NodeId,
    goal: NodeId,
    cost_fn: CostFn,
    heuristic: Heuristic,
    *,
    blocked_edges: Collection[EdgeId] | None = None,
    max_expansions: int | None = None,
) -> UCSResult:
    """Always expands the node that *looks* closest to the goal. Not optimal."""
    blocked = blocked_edges or frozenset()
    stats = SearchStats()
    t0 = time.perf_counter()
    counter = itertools.count()
    parent: dict[NodeId, tuple[NodeId, EdgeId] | None] = {start: None}
    gcost = {start: 0.0}
    visited: set[NodeId] = set()
    heap = [(heuristic(start), next(counter), start)]
    stats.heap_pushes = 1
    status = SearchStatus.NO_ROUTE
    while heap:
        _, _, node = heapq.heappop(heap)
        stats.heap_pops += 1
        if node in visited:
            stats.stale_skipped += 1
            continue
        visited.add(node)
        stats.expanded_nodes += 1
        if node == goal:
            status = SearchStatus.FOUND
            break
        if max_expansions is not None and stats.expanded_nodes >= max_expansions:
            status = SearchStatus.LIMIT_EXCEEDED
            break
        for edge in graph.neighbors(node):
            if edge.id in blocked:
                continue
            w = cost_fn(edge)
            if w is None or edge.target in visited or edge.target in parent:
                continue
            stats.relaxations += 1
            parent[edge.target] = (node, edge.id)
            gcost[edge.target] = gcost[node] + w
            heapq.heappush(heap, (heuristic(edge.target), next(counter), edge.target))
            stats.heap_pushes += 1
    stats.duration_ms = (time.perf_counter() - t0) * 1000
    res = UCSResult(status=status, start=start, goal=goal, stats=stats)
    if status is SearchStatus.FOUND:
        res.node_path, res.edge_path = _reconstruct(parent, goal)
        res.total_cost = gcost[goal]
    return res
