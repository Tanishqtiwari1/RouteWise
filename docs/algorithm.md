# Algorithms

## Uniform Cost Search — `backend/app/algorithms/ucs.py`

The primary router. Hand-written over Python's `heapq`; NetworkX is used only in tests (to cross-check against Dijkstra) and to compute connected components during ingestion.

```
best[start] = 0; parent[start] = None
push (0, tie, start)
while heap:
    (g, _, n) = pop()
    if n settled or g > best[n]:  skip (stale entry — lazy deletion)
    settle n
    if n is goal:  return reconstruct(n)          # goal test on POP => g is optimal
    for edge (n -> v):
        if edge closed: skip                      # road closures
        w = cost_fn(edge)
        if w is None: skip                        # vehicle restriction (weight/height/width/hgv)
        if w < 0 or not finite: raise             # UCS requires non-negative costs
        if g + w < best[v]: best[v] = g + w; parent[v] = (n, edge); push (g + w, tie, v)
return NO_ROUTE
```

* **State**: road-graph node id. **Priority**: cumulative objective cost g(n). Ties are broken FIFO by an insertion counter, so results are deterministic.
* **Stale entries**: the heap may hold several entries per node; anything popped with `g > best[n]` or for an already-settled node is skipped and counted (`stale_skipped`).
* **Limits**: `max_expansions`, wall-clock `time_limit_s`, and a `cancel()` callback polled periodically → statuses `limit_exceeded` / `cancelled`.
* **Result**: node path, ordered edge ids, total objective cost, per-step reconstruction (edge cost + cumulative cost), statistics (expanded nodes, relaxations, improvements, heap pushes/pops = queue operations, stale/blocked/restricted skips, peak frontier, duration), warnings and an optional bounded trace of push/pop/relax/improve/goal events.
* **Complexity**: O((V + E) log V) time with lazy deletion (≤ E heap entries), O(V + E) memory.
* `ucs_one_to_many` runs the same core until several goals are settled (used to build multi-stop leg matrices).

Never substituted silently: the route the user sees is always the UCS result. A* and greedy best-first live in `baselines.py` and only run when benchmarks are requested.

## Cost model — `backend/app/algorithms/cost_model.py`

Separate from the search. For each segment (only enabled components apply):

```
distance_km  = length_m / 1000                       (measured along OSM geometry)
duration_h   = distance_km / (speed_kph × speed_factor, capped by vehicle max speed)
fuel         = distance_km / efficiency_km_per_unit × energy_price_per_unit
driver       = duration_h × driver_cost_per_hour
operating    = distance_km × operating_cost_per_km
toll         = configured amount (admin override)            if toll=yes and configured
             = distance_km × toll_rate_per_km_estimate       if toll=yes and estimate enabled (disclosed)
             = excluded and reported as UNAVAILABLE          if toll=yes and nothing configured
             = 0, reported as "unconfirmed"                  if OSM has no toll tag
             = 0, "confirmed free"                           if toll=no
surcharge    = configured per-segment extra cost
money        = fuel + driver + operating + toll + surcharge
```

Objectives give UCS its edge weight: **money** (currency), **time** (seconds), **distance** (metres), **balanced** = money + value_of_time_per_hour × hours (a generalised cost in currency units — explicitly *not* the cheapest monetary route). A fixed cost per trip is added once to the total and does not affect route choice. Route breakdowns use `Decimal`; components are rounded to paise and the reported total is their exact sum.

Speeds are static: road-class defaults (editable in Settings), lowered — never raised — by a posted `maxspeed`. No live traffic is used; every route says so.

## Alternatives and baselines

* **Alternatives** = the UCS-optimal route for each other objective on the same network and cost settings, de-duplicated. They are not k-shortest paths and are never described as "second cheapest".
* **Savings baseline** (single route) = monetary cost of the shortest-distance route under the same settings.
* **Benchmarks** (optional): UCS vs A* vs greedy best-first, same graph/closures/costs. A* uses `h(n) = great-circle distance to goal × lowest possible cost per metre` (fuel + operating per km, driver cost at the fastest modelled speed, tolls/surcharges assumed 0). Edge lengths are measured along geometry (≥ great-circle) so h is admissible and consistent; the response reports whether A*'s cost matched UCS.

## Multi-stop planning — `backend/app/algorithms/multi_stop.py`

Solving point-to-point UCS does not solve vehicle routing; this is a separate module.

1. **Leg matrix**: one `ucs_one_to_many` run per location (depot + n stops) gives shortest objective cost, duration and path for every ordered pair.
2. **Exact plan search** over states `(location, visited_mask, remaining_capacity_kg)` with an elapsed-time label:
   * deliver to an unvisited stop if its load fits; wait if early (waiting priced at the driver rate for money objectives), reject if past the window end;
   * if reloads are allowed, return to the depot to reset capacity (each trip incurs the fixed trip cost);
   * goal: all stops visited (and back at the depot if requested).
   * With time windows, labels at the same state are pruned only when Pareto-dominated in (cost, time), keeping the search exact.
3. `algorithm="ucs"` orders by g. `algorithm="astar"` adds the admissible bound `h = max over unvisited s (leg[cur][s] + leg[s][depot] if returning)`.
4. State space is O(n · 2ⁿ · C); limits (`MULTI_STOP_MAX_STOPS`, `MULTI_STOP_MAX_STATES`, time) return `limit_exceeded` with an explanation rather than a heuristic answer.
5. Infeasibility is explained: individual order heavier than the vehicle, total load above capacity without reloads, unreachable stops, impossible time windows.
6. **Allocation**: each stop gets the cost of the leg reaching it (+ its waiting cost); legs back to the depot and fixed trip costs are split evenly among that trip's stops. Allocations sum exactly to the total.
7. **Baseline**: nearest-neighbour ordering. It is reported as a savings baseline only when it is valid for the same constraints (fits in one trip, no time windows); otherwise no savings are claimed.

## Dynamic rerouting

Closures are stored as events with network revisions. On creating a closure that is in effect, every *saved* or *dispatched* plan whose edge snapshot uses a closed edge is recalculated from its stored request on the current network. The new plan links to the old (`parent_plan_id`), the old becomes `superseded`, and a `RerouteEvent` records deltas (distance, duration, cost) or `no_alternative` with the reason. This is event-driven — there is no live traffic feed.
