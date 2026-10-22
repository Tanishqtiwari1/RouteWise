"""Multi-stop delivery planning with capacity and optional time windows.

This is a separate problem from single-path routing: solving the cheapest path
between two points with UCS does NOT solve the vehicle routing problem.

Approach
--------
1. A leg matrix ``leg[i][j]`` (objective cost, duration, path) between the depot
   and every stop is computed by the caller, normally with one
   :func:`ucs_one_to_many` run per location.
2. An exact search runs over *plan states*::

       (location, visited_mask, remaining_capacity_kg)   + elapsed time label

   Transitions: drive to an unvisited stop whose load fits (wait if early,
   reject if late), or — when reloading is allowed — return to the depot to
   reset capacity. The goal is "all stops visited" (and back at the depot when
   ``return_to_depot``).
3. ``algorithm="ucs"`` orders the frontier by g only. ``algorithm="astar"`` adds
   the admissible lower bound
   ``h = max over unvisited s of (leg[cur][s] + (leg[s][depot] if returning))``,
   which never over-estimates because every remaining tour must reach ``s``
   (and then the depot) and leg costs are shortest-path costs.

With time windows the state also carries elapsed time; labels at the same key
are pruned only when Pareto-dominated in (cost, time), which keeps the search
exact. The state space grows as O(n · 2^n · C), so stop counts and expanded
states are capped; exceeding a cap returns a clear explanation, not a guess.
"""

from __future__ import annotations

import heapq
import itertools
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

DEPOT = 0  # index of the depot in the leg matrix


@dataclass(frozen=True)
class Leg:
    cost: float  # objective cost
    duration_s: float
    distance_m: float = 0.0


@dataclass(frozen=True)
class StopSpec:
    key: Any  # caller's identifier (e.g. delivery order id)
    load_kg: float
    service_time_s: float = 0.0
    window_start_s: float | None = None  # relative to departure
    window_end_s: float | None = None


@dataclass
class MultiStopLimits:
    max_stops: int = 10
    max_expanded_states: int = 250_000
    time_limit_s: float = 20.0


@dataclass
class VisitStep:
    index: int  # matrix index (0 = depot)
    stop_key: Any | None
    arrival_s: float
    wait_s: float
    departure_s: float
    capacity_left_kg: float
    leg_cost: float


@dataclass
class MultiStopResult:
    feasible: bool
    status: str  # found | infeasible | limit_exceeded | invalid
    message: str
    sequence: list[VisitStep] = field(default_factory=list)
    total_cost: float = math.inf
    total_duration_s: float = 0.0
    trips: int = 0
    stats: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def plan_multi_stop(
    legs: Sequence[Sequence[Leg | None]],
    stops: Sequence[StopSpec],
    capacity_kg: float,
    *,
    return_to_depot: bool = True,
    allow_reload: bool = False,
    algorithm: str = "ucs",
    waiting_cost_per_s: float = 0.0,
    limits: MultiStopLimits | None = None,
) -> MultiStopResult:
    """Exact search over delivery orders. ``legs`` is (n+1)×(n+1); index 0 is the depot.

    ``None`` in the leg matrix means unreachable. ``waiting_cost_per_s`` converts
    waiting time at early arrivals into objective units (must be ≥ 0).
    """
    limits = limits or MultiStopLimits()
    n = len(stops)
    if n == 0:
        return MultiStopResult(False, "invalid", "At least one delivery stop is required.")
    if n > limits.max_stops:
        return MultiStopResult(
            False, "limit_exceeded",
            f"{n} stops exceeds the exact-search limit of {limits.max_stops}. The state space grows as "
            f"n·2^n·capacity; split the deliveries into smaller batches or raise the configured limit.")
    if len(legs) != n + 1 or any(len(r) != n + 1 for r in legs):
        return MultiStopResult(False, "invalid", "Leg matrix dimensions do not match the number of stops.")
    if capacity_kg <= 0:
        return MultiStopResult(False, "invalid", "Vehicle capacity must be positive.")
    if waiting_cost_per_s < 0:
        return MultiStopResult(False, "invalid", "Waiting cost must be non-negative.")
    for i in range(n + 1):
        for j in range(n + 1):
            leg = legs[i][j]
            if leg is not None and (leg.cost < 0 or leg.duration_s < 0):
                return MultiStopResult(False, "invalid", "Leg costs and durations must be non-negative.")

    # Feasibility pre-checks with clear explanations.
    over = [s for s in stops if s.load_kg > capacity_kg]
    if over:
        keys = ", ".join(str(s.key) for s in over)
        return MultiStopResult(False, "infeasible",
                               f"Stops {keys} individually exceed the vehicle capacity of {capacity_kg:g} kg.")
    total_load = sum(s.load_kg for s in stops)
    if total_load > capacity_kg and not allow_reload:
        return MultiStopResult(
            False, "infeasible",
            f"Total load {total_load:g} kg exceeds vehicle capacity {capacity_kg:g} kg. Enable reload trips "
            "via the warehouse, choose a larger vehicle, or split the deliveries.")
    for k, s in enumerate(stops, start=1):
        if legs[DEPOT][k] is None:
            return MultiStopResult(False, "infeasible", f"Stop {s.key} is unreachable from the warehouse.")
        if return_to_depot and legs[k][DEPOT] is None:
            return MultiStopResult(False, "infeasible", f"The warehouse is unreachable from stop {s.key}.")
        if s.window_start_s is not None and s.window_end_s is not None and s.window_start_s > s.window_end_s:
            return MultiStopResult(False, "invalid", f"Stop {s.key} has a time window that ends before it starts.")

    use_windows = any(s.window_start_s is not None or s.window_end_s is not None for s in stops)
    full = (1 << n) - 1
    # Capacity is tracked in grams as an integer so state keys are exact.
    cap_units = int(round(capacity_kg * 1000))
    load_units = [int(round(s.load_kg * 1000)) for s in stops]

    def h(loc: int, mask: int) -> float:
        if algorithm != "astar":
            return 0.0
        best = 0.0
        for k in range(1, n + 1):
            if mask & (1 << (k - 1)):
                continue
            to = legs[loc][k]
            if to is None:
                return math.inf
            back = 0.0
            if return_to_depot:
                b = legs[k][DEPOT]
                if b is None:
                    return math.inf
                back = b.cost
            best = max(best, to.cost + back)
        if mask == full and return_to_depot and loc != DEPOT:
            b = legs[loc][DEPOT]
            return math.inf if b is None else b.cost
        return best

    t0 = time.perf_counter()
    counter = itertools.count()
    # State: (loc, mask, cap_left). Label: (g, t).
    labels: dict[tuple[int, int, int], list[tuple[float, float]]] = {}
    parent: dict[int, tuple[int | None, VisitStep, tuple[int, int, int]]] = {}
    start_state = (DEPOT, 0, cap_units)
    root_id = next(counter)
    parent[root_id] = (None, VisitStep(DEPOT, None, 0.0, 0.0, 0.0, capacity_kg, 0.0), start_state)
    heap: list[tuple[float, float, int, float, tuple[int, int, int]]] = [(h(DEPOT, 0), 0.0, root_id, 0.0, start_state)]
    labels[start_state] = [(0.0, 0.0)]
    expanded = generated = pruned = 0
    peak = 1
    goal_id: int | None = None
    goal_g = math.inf
    goal_t = 0.0

    def dominated(key: tuple[int, int, int], g: float, t: float) -> bool:
        for (lg, lt) in labels.get(key, ()):
            if lg <= g and (not use_windows or lt <= t):
                return True
        return False

    def add_label(key: tuple[int, int, int], g: float, t: float) -> None:
        lst = labels.setdefault(key, [])
        if use_windows:
            lst[:] = [(lg, lt) for (lg, lt) in lst if not (g <= lg and t <= lt)]
            lst.append((g, t))
        else:
            lst[:] = [(g, t)]

    status = "infeasible"
    while heap:
        f, g, sid, t, state = heapq.heappop(heap)
        loc, mask, cap = state
        # Stale entry if a better label now dominates it.
        if any((lg < g and (not use_windows or lt <= t)) for (lg, lt) in labels.get(state, ())):
            pruned += 1
            continue
        expanded += 1
        if mask == full and (not return_to_depot or loc == DEPOT):
            goal_id, goal_g, goal_t = sid, g, t
            status = "found"
            break
        if expanded >= limits.max_expanded_states or (expanded % 1024 == 0 and time.perf_counter() - t0 > limits.time_limit_s):
            status = "limit_exceeded"
            break

        successors: list[tuple[int, int, int, float, float, float, float]] = []
        for k in range(1, n + 1):
            bit = 1 << (k - 1)
            if mask & bit or load_units[k - 1] > cap:
                continue
            leg = legs[loc][k]
            if leg is None:
                continue
            s = stops[k - 1]
            arrive = t + leg.duration_s
            wait = 0.0
            if s.window_start_s is not None and arrive < s.window_start_s:
                wait = s.window_start_s - arrive
            if s.window_end_s is not None and arrive + wait > s.window_end_s:
                continue  # would be late
            depart = arrive + wait + s.service_time_s
            ng = g + leg.cost + wait * waiting_cost_per_s
            successors.append((k, mask | bit, cap - load_units[k - 1], ng, arrive, wait, depart))
        reload_trip = allow_reload and mask != full
        final_return = mask == full and return_to_depot
        if loc != DEPOT and (reload_trip or final_return):
            leg = legs[loc][DEPOT]
            if leg is not None:
                arrive = t + leg.duration_s
                new_cap = cap_units if allow_reload else cap
                successors.append((DEPOT, mask, new_cap, g + leg.cost, arrive, 0.0, arrive))

        for (k, nmask, ncap, ng, arrive, wait, depart) in successors:
            key = (k, nmask, ncap)
            generated += 1
            if dominated(key, ng, depart):
                pruned += 1
                continue
            add_label(key, ng, depart)
            hv = h(k, nmask)
            if math.isinf(hv):
                continue
            nid = next(counter)
            leg_cost = ng - g
            parent[nid] = (sid, VisitStep(k, stops[k - 1].key if k else None, arrive, wait, depart,
                                          ncap / 1000.0, leg_cost), key)
            heapq.heappush(heap, (ng + hv, ng, nid, depart, key))
        peak = max(peak, len(heap))

    stats = {
        "algorithm": algorithm,
        "expanded_states": expanded,
        "generated_states": generated,
        "pruned_states": pruned,
        "peak_frontier": peak,
        "distinct_state_keys": len(labels),
        "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
        "state_space_upper_bound": (n + 1) * (1 << n) * (cap_units + 1 if allow_reload else 1),
    }
    if status != "found" or goal_id is None:
        msg = ("Search budget exhausted before a complete plan was proven optimal "
               f"({expanded} states expanded). Reduce the number of stops or raise the limit."
               if status == "limit_exceeded" else
               "No feasible delivery order satisfies the capacity, reachability and time-window constraints.")
        return MultiStopResult(False, status, msg, stats=stats)

    seq: list[VisitStep] = []
    cur: int | None = goal_id
    while cur is not None:
        p, step, _ = parent[cur]
        seq.append(step)
        cur = p
    seq.reverse()
    inner = seq[1:-1] if (return_to_depot and seq[-1].index == DEPOT) else seq[1:]
    trips = 1 + sum(1 for s in inner if s.index == DEPOT)
    res = MultiStopResult(True, "found", "Optimal delivery order found for the given leg costs and constraints.",
                          sequence=seq, total_cost=goal_g, total_duration_s=goal_t, trips=trips, stats=stats)
    if allow_reload and trips > 1:
        res.warnings.append(f"Plan uses {trips} trips with reloads at the warehouse to respect capacity.")
    return res


def nearest_neighbour_order(legs: Sequence[Sequence[Leg | None]], n: int, return_to_depot: bool) -> tuple[list[int], float] | None:
    """Greedy baseline: always drive to the cheapest unvisited stop. Ignores windows/capacity."""
    order: list[int] = []
    cur, total = DEPOT, 0.0
    remaining = set(range(1, n + 1))
    while remaining:
        nxt = min((k for k in remaining if legs[cur][k] is not None), key=lambda k: legs[cur][k].cost, default=None)
        if nxt is None:
            return None
        total += legs[cur][nxt].cost
        order.append(nxt)
        remaining.discard(nxt)
        cur = nxt
    if return_to_depot:
        if legs[cur][DEPOT] is None:
            return None
        total += legs[cur][DEPOT].cost
    return order, total
