"""Unit tests for the custom UCS engine (deterministic synthetic graphs only)."""

import itertools
import random

import networkx as nx
import pytest

from app.algorithms.baselines import astar_search, greedy_best_first
from app.algorithms.graph import GraphValidationError, WeightedGraph
from app.algorithms.ucs import (
    NegativeCostError,
    SearchLimits,
    SearchStatus,
    ucs_one_to_many,
    uniform_cost_search,
)


def g(*edges):
    return WeightedGraph.from_edges(edges)


def test_direct_edge_cheaper_than_indirect():
    graph = g(("A", "C", 3), ("A", "B", 2), ("B", "C", 2))
    r = uniform_cost_search(graph, "A", "C")
    assert r.found and r.node_path == ["A", "C"] and r.total_cost == 3


def test_indirect_route_cheaper_than_direct():
    graph = g(("A", "C", 10), ("A", "B", 2), ("B", "C", 3))
    r = uniform_cost_search(graph, "A", "C")
    assert r.node_path == ["A", "B", "C"] and r.total_cost == 5


def test_multiple_paths_different_cumulative_costs():
    graph = g(("S", "A", 1), ("S", "B", 4), ("A", "B", 2), ("A", "C", 5), ("B", "C", 1), ("C", "G", 3), ("B", "G", 7))
    r = uniform_cost_search(graph, "S", "G")
    assert r.node_path == ["S", "A", "B", "C", "G"]
    assert r.total_cost == 7


def test_zero_cost_edges():
    graph = g(("A", "B", 0), ("B", "C", 0), ("A", "C", 1))
    r = uniform_cost_search(graph, "A", "C")
    assert r.total_cost == 0 and r.node_path == ["A", "B", "C"]


def test_equal_cost_routes_return_valid_optimum():
    graph = g(("A", "B", 1), ("B", "D", 1), ("A", "C", 1), ("C", "D", 1))
    r = uniform_cost_search(graph, "A", "D")
    assert r.total_cost == 2
    assert r.node_path in (["A", "B", "D"], ["A", "C", "D"])
    # Deterministic tie-breaking: same input -> same output.
    assert uniform_cost_search(graph, "A", "D").node_path == r.node_path


def test_disconnected_returns_no_route():
    graph = g(("A", "B", 1), ("C", "D", 1))
    r = uniform_cost_search(graph, "A", "D")
    assert r.status is SearchStatus.NO_ROUTE and not r.found
    assert r.node_path == [] and "No route" in r.message


def test_directed_edges_respected():
    graph = g(("A", "B", 1))
    assert uniform_cost_search(graph, "B", "A").status is SearchStatus.NO_ROUTE


def test_blocked_edges_are_excluded():
    graph = WeightedGraph()
    graph.add_edge("ac", "A", "C", cost=1)
    graph.add_edge("ab", "A", "B", cost=2)
    graph.add_edge("bc", "B", "C", cost=2)
    r = uniform_cost_search(graph, "A", "C", blocked_edges={"ac"})
    assert r.edge_path == ["ab", "bc"] and r.total_cost == 4
    assert r.stats.blocked_edges_skipped == 1
    r2 = uniform_cost_search(graph, "A", "C", blocked_edges={"ac", "bc"})
    assert r2.status is SearchStatus.NO_ROUTE


def test_restricted_edges_via_cost_fn_none():
    graph = WeightedGraph()
    graph.add_edge("low_bridge", "A", "C", cost=1, maxheight_m=3.0)
    graph.add_edge("ab", "A", "B", cost=2)
    graph.add_edge("bc", "B", "C", cost=2)

    def truck(edge):
        if edge.get("maxheight_m") is not None and edge.get("maxheight_m") < 4.0:
            return None
        return edge.get("cost")

    r = uniform_cost_search(graph, "A", "C", truck)
    assert r.edge_path == ["ab", "bc"] and r.stats.restricted_edges_skipped == 1


def test_negative_cost_rejected_at_construction():
    with pytest.raises(GraphValidationError):
        g(("A", "B", -1))


def test_negative_cost_rejected_at_search_time():
    graph = g(("A", "B", 1), ("B", "C", 1))
    with pytest.raises(NegativeCostError):
        uniform_cost_search(graph, "A", "C", lambda e: -1.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "3", True])
def test_invalid_costs_rejected(bad):
    with pytest.raises(GraphValidationError):
        g(("A", "B", bad))


def test_unknown_nodes_rejected():
    graph = g(("A", "B", 1))
    with pytest.raises(GraphValidationError):
        uniform_cost_search(graph, "A", "Z")
    with pytest.raises(GraphValidationError):
        uniform_cost_search(graph, "Z", "A")


def test_improved_path_updates_parent():
    # C is first reached via the expensive direct edge (cost 10), then improved via B.
    graph = WeightedGraph()
    graph.add_edge("ac", "A", "C", cost=10)
    graph.add_edge("ab", "A", "B", cost=1)
    graph.add_edge("bc", "B", "C", cost=1)
    graph.add_edge("cd", "C", "D", cost=1)
    r = uniform_cost_search(graph, "A", "D", trace_limit=100)
    assert r.edge_path == ["ab", "bc", "cd"] and r.total_cost == 3
    improves_c = [e for e in r.trace if e.kind == "improve" and e.node == "C"]
    assert [e.parent for e in improves_c] == ["A", "B"]


def test_stale_entries_do_not_corrupt_results():
    # Node C gets pushed with cost 10, then 2; the stale cost-10 entry must be skipped.
    graph = g(("A", "C", 10), ("A", "B", 1), ("B", "C", 1), ("C", "D", 1), ("D", "E", 20))
    r = uniform_cost_search(graph, "A", "E")
    assert r.total_cost == 23
    assert r.stats.stale_skipped >= 1
    assert r.node_path == ["A", "B", "C", "D", "E"]


def test_source_equals_destination():
    graph = g(("A", "B", 1))
    r = uniform_cost_search(graph, "A", "A")
    assert r.found and r.total_cost == 0 and r.node_path == ["A"] and r.edge_path == []
    assert r.warnings


def test_reconstruction_sequence_and_total():
    graph = WeightedGraph()
    graph.add_edge("e1", 1, 2, cost=1.5)
    graph.add_edge("e2", 2, 3, cost=2.25)
    graph.add_edge("e3", 3, 4, cost=0.25)
    graph.add_edge("e4", 1, 4, cost=5)
    r = uniform_cost_search(graph, 1, 4)
    assert r.node_path == [1, 2, 3, 4]
    assert r.edge_path == ["e1", "e2", "e3"]
    assert r.total_cost == pytest.approx(4.0)
    assert [s.cumulative_cost for s in r.steps] == pytest.approx([0, 1.5, 3.75, 4.0])
    assert sum(graph.edge(e).get("cost") for e in r.edge_path) == pytest.approx(r.total_cost)


def test_parallel_edges_choose_cheapest():
    graph = WeightedGraph()
    graph.add_edge("slow", "A", "B", cost=5)
    graph.add_edge("fast", "A", "B", cost=2)
    assert uniform_cost_search(graph, "A", "B").edge_path == ["fast"]


def test_expansion_limit():
    graph = g(*[(i, i + 1, 1) for i in range(100)])
    r = uniform_cost_search(graph, 0, 100, limits=SearchLimits(max_expansions=10))
    assert r.status is SearchStatus.LIMIT_EXCEEDED and not r.found


def test_cancellation():
    graph = g(*[(i, i + 1, 1) for i in range(5000)])
    r = uniform_cost_search(graph, 0, 5000, limits=SearchLimits(cancel=lambda: True, cancel_check_interval=1))
    assert r.status is SearchStatus.CANCELLED


def test_stats_are_reported():
    graph = g(("A", "B", 1), ("B", "C", 1), ("A", "C", 3))
    r = uniform_cost_search(graph, "A", "C")
    s = r.stats.as_dict()
    assert s["expanded_nodes"] >= 2 and s["relaxations"] >= 2
    assert s["queue_operations"] == s["heap_pushes"] + s["heap_pops"]


def test_one_to_many():
    graph = g(("A", "B", 1), ("B", "C", 1), ("A", "C", 5), ("X", "Y", 1))
    r = ucs_one_to_many(graph, "A", ["B", "C", "Y"])
    assert r.costs == {"B": 1, "C": 2}
    assert r.unreachable == ["Y"]
    assert r.paths["C"][0] == ["A", "B", "C"]


def _random_graph(seed, n=60, m=300):
    rng = random.Random(seed)
    graph = WeightedGraph()
    nxg = nx.MultiDiGraph()
    for i in range(n):
        lat, lon = 28.6 + rng.random() * 0.1, 77.2 + rng.random() * 0.1
        graph.add_node(i, lat=lat, lon=lon)
        nxg.add_node(i)
    for k in range(m):
        u, v = rng.randrange(n), rng.randrange(n)
        c = rng.choice([0, 0.5, 1, 2, 3, 7, 11.5])
        graph.add_edge(k, u, v, cost=c)
        nxg.add_edge(u, v, weight=c)
    return graph, nxg


@pytest.mark.parametrize("seed", range(15))
def test_matches_networkx_dijkstra_on_random_graphs(seed):
    graph, nxg = _random_graph(seed)
    for s, t in itertools.islice(itertools.permutations(range(10), 2), 30):
        r = uniform_cost_search(graph, s, t)
        try:
            expected = nx.dijkstra_path_length(nxg, s, t, weight="weight")
        except nx.NetworkXNoPath:
            assert r.status is SearchStatus.NO_ROUTE
            continue
        assert r.total_cost == pytest.approx(expected)
        assert sum(graph.edge(e).get("cost") for e in r.edge_path) == pytest.approx(expected)


@pytest.mark.parametrize("seed", range(5))
def test_astar_zero_heuristic_matches_ucs_and_greedy_never_beats_it(seed):
    graph, _ = _random_graph(seed)
    for s, t in [(0, 5), (3, 9), (7, 2)]:
        u = uniform_cost_search(graph, s, t)
        a = astar_search(graph, s, t, lambda e: e.get("cost"), lambda n: 0.0)
        gr = greedy_best_first(graph, s, t, lambda e: e.get("cost"), lambda n: 0.0)
        assert u.status == a.status == gr.status
        if u.found:
            assert a.total_cost == pytest.approx(u.total_cost)
            assert gr.total_cost >= u.total_cost - 1e-9
