"""Route planning service: connects the pure algorithms to data and persistence."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithms.baselines import astar_search, greedy_best_first, straight_line_heuristic
from app.algorithms.cost_model import (
    OBJECTIVE_UNITS,
    CostConfig,
    Objective,
    RouteBreakdown,
    VehicleRestrictions,
    make_cost_fn,
    money,
    objective_formula,
    objective_value,
    route_breakdown,
    segment_cost,
)
from app.algorithms.multi_stop import DEPOT, Leg, MultiStopLimits, StopSpec, nearest_neighbour_order, plan_multi_stop
from app.algorithms.ucs import SearchLimits, SearchStatus, UCSResult, ucs_one_to_many, uniform_cost_search
from app.core.config import get_settings
from app.core.errors import NotFound, Unprocessable
from app.models import (
    DeliveryAddress,
    DeliveryOrder,
    RerouteEvent,
    RoadNetwork,
    RouteEdge,
    RoutePlan,
    RouteStop,
    Vehicle,
    Warehouse,
    utcnow,
)

from .road_network import LoadedNetwork, active_blocked_edges, freshness, get_network, load_network
from .settings_service import build_cost_config, get_settings_row, parse_objective, vehicle_restrictions, vehicle_snapshot

log = logging.getLogger(__name__)


@dataclass
class Point:
    lat: float
    lon: float
    label: str
    warehouse_id: int | None = None
    order_id: int | None = None


@dataclass
class Context:
    net: RoadNetwork
    loaded: LoadedNetwork
    vehicle: Vehicle
    cfg: CostConfig
    restrictions: VehicleRestrictions
    blocked: set[str]
    assumptions: list[str]


# ----------------------------------------------------------------- helpers

def _vehicle(db: Session, vehicle_id: int | None) -> Vehicle:
    if vehicle_id is None:
        ws = get_settings_row(db)
        vehicle_id = ws.default_vehicle_id
    if vehicle_id is None:
        raise Unprocessable("Select a vehicle (no default vehicle is configured).", code="vehicle_required")
    v = db.get(Vehicle, vehicle_id)
    if v is None:
        raise NotFound(f"Vehicle {vehicle_id} not found")
    if not v.active:
        raise Unprocessable(f"Vehicle '{v.name}' is inactive.")
    return v


def _context(db: Session, vehicle_id: int | None, network_id: int | None, prefs: dict[str, Any] | None) -> Context:
    vehicle = _vehicle(db, vehicle_id)
    net = get_network(db, network_id)
    loaded = load_network(db, net)
    ws = get_settings_row(db)
    cfg, assumptions = build_cost_config(ws, vehicle, prefs)
    return Context(net, loaded, vehicle, cfg, vehicle_restrictions(vehicle), active_blocked_edges(db, net.id), assumptions)


def warehouse_point(db: Session, warehouse_id: int) -> Point:
    w = db.get(Warehouse, warehouse_id)
    if w is None:
        raise NotFound(f"Warehouse {warehouse_id} not found")
    if w.lat is None or w.lon is None:
        raise Unprocessable(f"Warehouse '{w.name}' has no confirmed location (geocode status: {w.geocode_status}).",
                            code="location_unresolved")
    return Point(w.lat, w.lon, w.name, warehouse_id=w.id)


def address_point(addr: DeliveryAddress, label: str | None = None) -> Point:
    if addr.lat is None or addr.lon is None or addr.geocode_status not in ("matched", "manual"):
        raise Unprocessable(
            f"Address '{addr.address_text}' is not resolved (geocode status: {addr.geocode_status}). "
            "Confirm it in Delivery Management first.", code="location_unresolved")
    return Point(addr.lat, addr.lon, label or addr.address_text)


def order_point(db: Session, order_id: int) -> tuple[DeliveryOrder, Point]:
    o = db.get(DeliveryOrder, order_id)
    if o is None:
        raise NotFound(f"Delivery order {order_id} not found")
    p = address_point(o.address, f"{o.reference} · {o.customer.name}")
    p.order_id = o.id
    return o, p


def _search(ctx: Context, start: int, goal: int, objective: Objective, trace_limit: int = 0) -> UCSResult:
    s = get_settings()
    res = uniform_cost_search(
        ctx.loaded.graph, start, goal, make_cost_fn(objective, ctx.cfg, ctx.restrictions),
        blocked_edges=ctx.blocked,
        limits=SearchLimits(max_expansions=s.ucs_max_expansions, time_limit_s=s.ucs_time_limit_s),
        trace_limit=trace_limit,
    )
    return res


def _raise_for(res: UCSResult, ctx: Context) -> None:
    if res.status is SearchStatus.NO_ROUTE:
        detail = ("No drivable path connects these points with the current road closures"
                  f" ({len(ctx.blocked)} closed segments) and vehicle restrictions for '{ctx.vehicle.name}'.")
        raise Unprocessable(detail, code="no_route", details={"search_stats": res.stats.as_dict()})
    if res.status is SearchStatus.LIMIT_EXCEEDED:
        raise Unprocessable("Route search exceeded its execution budget.", code="search_limit",
                            details={"search_stats": res.stats.as_dict()})
    if res.status is SearchStatus.CANCELLED:
        raise Unprocessable("Route search was cancelled.", code="search_cancelled")


def _edges(ctx: Context, edge_ids: list[str]):
    return [ctx.loaded.graph.edge(e) for e in edge_ids]


def _geometry(ctx: Context, edge_ids: list[str], start_node: int) -> list[list[float]]:
    if not edge_ids:
        lat, lon = ctx.loaded.coords(start_node)
        return [[lat, lon]]
    out: list[list[float]] = []
    for e in _edges(ctx, edge_ids):
        g = e.get("geometry")
        out.extend(g if not out else g[1:])
    return out


def _named_segments(ctx: Context, edge_ids: list[str]) -> list[dict[str, Any]]:
    segs: list[dict[str, Any]] = []
    for e in _edges(ctx, edge_ids):
        name = e.get("name") or f"Unnamed {e.get('highway', 'road')}"
        sc = segment_cost(e, ctx.cfg)
        if segs and segs[-1]["name"] == name:
            s = segs[-1]
            s["distance_m"] += e.get("length_m")
            s["duration_s"] += float(sc.duration_h) * 3600
            s["cost"] += sc.total
            s["edge_count"] += 1
        else:
            segs.append({"name": name, "highway": e.get("highway"), "distance_m": e.get("length_m"),
                         "duration_s": float(sc.duration_h) * 3600, "cost": sc.total, "edge_count": 1,
                         "toll": e.get("toll")})
    for s in segs:
        s["distance_m"] = round(s["distance_m"], 1)
        s["duration_s"] = round(s["duration_s"], 1)
        s["cost"] = str(money(s["cost"]))
    return segs


def _summary(ctx: Context, res: UCSResult, objective: Objective, start_node: int) -> dict[str, Any]:
    rb = route_breakdown(_edges(ctx, res.edge_path), ctx.cfg)
    return {
        "objective": objective.value,
        "objective_value": round(objective_value(rb, objective, ctx.cfg), 4),
        "objective_units": OBJECTIVE_UNITS[objective],
        "distance_m": round(float(rb.distance_km) * 1000, 1),
        "duration_s": round(float(rb.duration_h) * 3600, 1),
        "total_cost": str(money(rb.total)),
        "breakdown": rb.as_dict(),
        "geometry": _geometry(ctx, res.edge_path, start_node),
        "edge_ids": res.edge_path,
        "_rb": rb,
    }


def _heuristic_cost_per_metre(ctx: Context, objective: Objective) -> tuple[float, str]:
    max_speed = ctx.loaded.max_speed_kph * float(ctx.cfg.speed_factor)
    if ctx.cfg.max_vehicle_speed_kph:
        max_speed = min(max_speed, float(ctx.cfg.max_vehicle_speed_kph))
    if objective is Objective.DISTANCE:
        return 1.0, "h(n) = great-circle metres to goal"
    if objective is Objective.TIME:
        return 3.6 / max_speed, f"h(n) = great-circle distance / fastest modelled speed ({max_speed:.0f} km/h)"
    per_km = 0.0
    if ctx.cfg.include_fuel:
        per_km += float(ctx.cfg.energy_price_per_unit / ctx.cfg.efficiency_km_per_unit)
    if ctx.cfg.include_operating:
        per_km += float(ctx.cfg.operating_cost_per_km)
    if ctx.cfg.include_driver:
        per_km += float(ctx.cfg.driver_cost_per_hour) / max_speed
    if objective is Objective.BALANCED:
        per_km += float(ctx.cfg.value_of_time_per_hour) / max_speed
    return per_km / 1000.0, (f"h(n) = great-circle km to goal × {per_km:.3f} {ctx.cfg.currency}/km "
                             "(lowest possible per-km cost: tolls/surcharges assumed 0, fastest modelled speed)")


def run_benchmarks(ctx: Context, start: int, goal: int, objective: Objective, ucs: UCSResult) -> list[dict[str, Any]]:
    cost_fn = make_cost_fn(objective, ctx.cfg, ctx.restrictions)
    per_m, h_desc = _heuristic_cost_per_metre(ctx, objective)
    out = []

    def row(name: str, label: str, res: UCSResult, optimal: str, heuristic: str | None):
        entry = {"algorithm": name, "label": label, "status": res.status.value, "optimality": optimal,
                 "heuristic": heuristic, **res.stats.as_dict()}
        if res.found:
            rb = route_breakdown(_edges(ctx, res.edge_path), ctx.cfg)
            entry.update({"objective_value": round(res.total_cost, 4), "distance_m": round(float(rb.distance_km) * 1000, 1),
                          "duration_s": round(float(rb.duration_h) * 3600, 1), "total_cost": str(money(rb.total)),
                          "matches_ucs_cost": abs(res.total_cost - ucs.total_cost) <= 1e-6 * max(1.0, ucs.total_cost)})
        out.append(entry)

    row("ucs", "Uniform Cost Search (primary)", ucs, "optimal for the objective", None)
    limit = get_settings().ucs_max_expansions
    a = astar_search(ctx.loaded.graph, start, goal, cost_fn, straight_line_heuristic(ctx.loaded.graph, goal, per_m),
                     blocked_edges=ctx.blocked, max_expansions=limit)
    row("astar", "A* (comparison only)", a, "optimal (admissible heuristic)", h_desc)
    gr = greedy_best_first(ctx.loaded.graph, start, goal, cost_fn, straight_line_heuristic(ctx.loaded.graph, goal, 1.0),
                           blocked_edges=ctx.blocked, max_expansions=limit)
    row("greedy", "Greedy best-first (baseline)", gr, "not optimal", "h(n) = great-circle metres to goal")
    return out


def _trace_payload(ctx: Context, res: UCSResult) -> dict[str, Any]:
    events = []
    for ev in res.trace:
        if ev.kind not in ("pop", "goal", "stale"):
            continue
        lat, lon = ctx.loaded.coords(ev.node)
        events.append({"k": ev.kind, "n": ev.node, "c": round(ev.cost, 3), "lat": lat, "lon": lon})
    return {"events": events, "truncated": res.trace_truncated, "recorded": len(res.trace)}


def _access(ctx: Context, p: Point, node: int, dist: float) -> dict[str, Any]:
    lat, lon = ctx.loaded.coords(node)
    return {"from": [p.lat, p.lon], "to": [lat, lon], "distance_m": round(dist, 1), "node": node}


# ------------------------------------------------------------ single route

def calculate_route(db: Session, req: dict[str, Any]) -> dict[str, Any]:
    objective = parse_objective(req.get("objective") or get_settings_row(db).default_objective)
    ctx = _context(db, req.get("vehicle_id"), req.get("network_id"), req.get("preferences"))

    if req.get("warehouse_id"):
        origin = warehouse_point(db, req["warehouse_id"])
    elif req.get("origin"):
        o = req["origin"]
        origin = Point(o["lat"], o["lon"], o.get("label") or f"{o['lat']:.5f}, {o['lon']:.5f}")
    else:
        raise Unprocessable("Provide a warehouse or an origin point.", code="origin_required")

    order = None
    if req.get("delivery_order_id"):
        order, dest = order_point(db, req["delivery_order_id"])
        if order.weight_kg > ctx.vehicle.max_payload_kg:
            raise Unprocessable(f"Order {order.reference} weighs {order.weight_kg:g} kg, above {ctx.vehicle.name}'s "
                                f"payload capacity of {ctx.vehicle.max_payload_kg:g} kg.", code="capacity_exceeded")
    elif req.get("address_id"):
        addr = db.get(DeliveryAddress, req["address_id"])
        if addr is None:
            raise NotFound("Address not found")
        dest = address_point(addr)
    elif req.get("destination"):
        d = req["destination"]
        dest = Point(d["lat"], d["lon"], d.get("label") or f"{d['lat']:.5f}, {d['lon']:.5f}")
    else:
        raise Unprocessable("Provide a destination, an address or a delivery order.", code="destination_required")

    s_node, s_dist = ctx.loaded.snap(origin.lat, origin.lon)
    g_node, g_dist = ctx.loaded.snap(dest.lat, dest.lon)

    trace_limit = min(int(req.get("trace_limit") or 5000), 20000) if req.get("trace") else 0
    res = _search(ctx, s_node, g_node, objective, trace_limit)
    _raise_for(res, ctx)
    main = _summary(ctx, res, objective, s_node)
    rb: RouteBreakdown = main.pop("_rb")

    warnings = list(res.warnings) + rb.warnings()
    fresh = freshness(db, ctx.net)
    if fresh["stale"]:
        warnings.append(f"Road network data is older than {fresh['stale_after_days']} days; consider refreshing it.")
    for label, dist in (("origin", s_dist), ("destination", g_dist)):
        if dist > 200:
            warnings.append(f"The {label} is {dist:.0f} m from the nearest routable road; that access distance is not costed.")
    assumptions = ctx.assumptions + [
        f"Origin and destination snapped to the nearest road-network node ({s_dist:.0f} m and {g_dist:.0f} m away).",
        f"{len(ctx.blocked)} road segments closed at calculation time.",
        "Route alternatives are optimal for their own objective; they are not ranked k-shortest paths.",
    ]

    alternatives: list[dict[str, Any]] = []
    seen = {tuple(res.edge_path): objective.value}
    baseline = None
    if req.get("include_alternatives", True):
        for alt_obj in Objective:
            if alt_obj is objective:
                continue
            ar = _search(ctx, s_node, g_node, alt_obj)
            if not ar.found:
                continue
            summ = _summary(ctx, ar, alt_obj, s_node)
            summ.pop("_rb")
            key = tuple(ar.edge_path)
            summ["same_route_as"] = seen.get(key)
            seen.setdefault(key, alt_obj.value)
            summ["formula"] = objective_formula(alt_obj, ctx.cfg)
            alternatives.append(summ)
            if alt_obj is Objective.DISTANCE:
                baseline = {"method": "shortest_distance", "total_cost": summ["total_cost"], "distance_m": summ["distance_m"],
                            "duration_s": summ["duration_s"]}
    if baseline is None:
        dr = res if objective is Objective.DISTANCE else _search(ctx, s_node, g_node, Objective.DISTANCE)
        if dr.found:
            bs = _summary(ctx, dr, Objective.DISTANCE, s_node)
            baseline = {"method": "shortest_distance", "total_cost": bs["total_cost"], "distance_m": bs["distance_m"],
                        "duration_s": bs["duration_s"]}
    savings = Decimal(baseline["total_cost"]) - money(rb.total) if baseline else None

    benchmarks = run_benchmarks(ctx, s_node, g_node, objective, res) if req.get("include_benchmarks") else None

    plan = RoutePlan(
        name=req.get("name") or f"{origin.label} → {dest.label}"[:160],
        kind="single", status="estimated", warehouse_id=origin.warehouse_id, vehicle_id=ctx.vehicle.id,
        network_id=ctx.net.id, network_revision=ctx.net.revision, algorithm="ucs", objective=objective.value,
        objective_value=main["objective_value"], objective_formula=objective_formula(objective, ctx.cfg),
        origin={"label": origin.label, "lat": origin.lat, "lon": origin.lon, "node": s_node, "snap_m": round(s_dist, 1)},
        destination={"label": dest.label, "lat": dest.lat, "lon": dest.lon, "node": g_node, "snap_m": round(g_dist, 1)},
        request=_jsonable(req), cost_config=ctx.cfg.as_dict(), vehicle_snapshot=vehicle_snapshot(ctx.vehicle),
        distance_m=main["distance_m"], duration_s=main["duration_s"], total_cost=money(rb.total), currency=ctx.cfg.currency,
        breakdown=main["breakdown"], emissions_kg=float(rb.emissions_kg) if rb.emissions_kg is not None else None,
        baseline=baseline, estimated_savings=savings, geometry=main["geometry"], node_path=res.node_path,
        search_stats=res.stats.as_dict(), assumptions=assumptions, warnings=warnings,
    )
    plan.stops = [
        RouteStop(sequence=0, kind="origin", label=origin.label, lat=origin.lat, lon=origin.lon, node_id=str(s_node)),
        RouteStop(sequence=1, kind="destination", label=dest.label, lat=dest.lat, lon=dest.lon, node_id=str(g_node),
                  delivery_order_id=order.id if order else None, arrival_s=main["duration_s"],
                  leg_distance_m=main["distance_m"], leg_cost=money(rb.total - rb.fixed), allocated_cost=money(rb.total),
                  load_kg=order.weight_kg if order else None),
    ]
    plan.edges = _edge_snapshot(ctx, res.edge_path)
    db.add(plan)
    db.commit()
    db.refresh(plan)

    out = plan_to_dict(plan, include_edges=False)
    out.update({
        "objective_units": main["objective_units"],
        "named_segments": _named_segments(ctx, res.edge_path),
        "access": [_access(ctx, origin, s_node, s_dist), _access(ctx, dest, g_node, g_dist)],
        "alternatives": alternatives,
        "benchmarks": benchmarks,
        "freshness": fresh,
        "cost_per_delivery": str(money(rb.total)),
        "reconstruction": [{"node": st.node, "via_edge": st.via_edge, "edge_cost": round(st.edge_cost, 4),
                            "cumulative_cost": round(st.cumulative_cost, 4)} for st in res.steps[:2000]],
    })
    if trace_limit:
        out["trace"] = _trace_payload(ctx, res)
    return out


def _edge_snapshot(ctx: Context, edge_ids: list[str], start_seq: int = 0) -> list[RouteEdge]:
    rows = []
    for i, e in enumerate(_edges(ctx, edge_ids)):
        sc = segment_cost(e, ctx.cfg)
        rows.append(RouteEdge(sequence=start_seq + i, edge_id=e.id, way_id=e.get("way_id"), name=e.get("name"),
                              highway=e.get("highway"), length_m=e.get("length_m"),
                              duration_s=round(float(sc.duration_h) * 3600, 2),
                              cost=sc.total.quantize(Decimal("0.0001")), toll_status=sc.toll_status))
    return rows


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    return v


# --------------------------------------------------------------- multi-stop

def plan_deliveries(db: Session, req: dict[str, Any]) -> dict[str, Any]:
    objective = parse_objective(req.get("objective") or "money")
    algorithm = req.get("algorithm") or "ucs"
    if algorithm not in ("ucs", "astar"):
        raise Unprocessable("algorithm must be 'ucs' or 'astar'")
    ctx = _context(db, req.get("vehicle_id"), req.get("network_id"), req.get("preferences"))
    depot = warehouse_point(db, req["warehouse_id"])
    order_ids: list[int] = list(dict.fromkeys(req.get("delivery_order_ids") or []))
    if not order_ids:
        raise Unprocessable("Select at least one delivery order.", code="orders_required")
    s = get_settings()
    if len(order_ids) > s.multi_stop_max_stops:
        raise Unprocessable(f"{len(order_ids)} stops exceeds the supported exact-search limit of "
                            f"{s.multi_stop_max_stops}. Split the deliveries into batches.", code="too_many_stops")
    orders: list[DeliveryOrder] = []
    points: list[Point] = [depot]
    for oid in order_ids:
        o, p = order_point(db, oid)
        if o.status in ("delivered", "cancelled"):
            raise Unprocessable(f"Order {o.reference} is {o.status} and cannot be planned.")
        orders.append(o)
        points.append(p)

    departure = req.get("departure_time") or utcnow()
    if isinstance(departure, str):
        departure = datetime.fromisoformat(departure)
    if departure.tzinfo is None:
        departure = departure.replace(tzinfo=utcnow().tzinfo)
    use_windows = req.get("respect_time_windows", True)
    stops: list[StopSpec] = []
    for o in orders:
        ws_, we_ = None, None
        if use_windows:
            if o.window_start:
                ws_ = (_aware(o.window_start) - departure).total_seconds()
            if o.window_end:
                we_ = (_aware(o.window_end) - departure).total_seconds()
        stops.append(StopSpec(key=o.id, load_kg=o.weight_kg, service_time_s=(o.service_time_min or 0) * 60,
                              window_start_s=ws_, window_end_s=we_))

    snapped = [ctx.loaded.snap(p.lat, p.lon) for p in points]
    nodes = [n for n, _ in snapped]
    cost_fn = make_cost_fn(objective, ctx.cfg, ctx.restrictions)
    n = len(points)
    legs: list[list[Leg | None]] = [[None] * n for _ in range(n)]
    paths: dict[tuple[int, int], list[str]] = {}
    matrix_stats = {"ucs_runs": 0, "expanded_nodes": 0, "duration_ms": 0.0}
    for i in range(n):
        r = ucs_one_to_many(ctx.loaded.graph, nodes[i], set(nodes), cost_fn, blocked_edges=ctx.blocked,
                            limits=SearchLimits(max_expansions=s.ucs_max_expansions, time_limit_s=s.ucs_time_limit_s))
        matrix_stats["ucs_runs"] += 1
        matrix_stats["expanded_nodes"] += r.stats.expanded_nodes
        matrix_stats["duration_ms"] += r.stats.duration_ms
        for j in range(n):
            if i == j or nodes[j] not in r.costs:
                continue
            eids = r.paths[nodes[j]][1]
            rb = route_breakdown(_edges(ctx, eids), ctx.cfg, include_fixed=False)
            legs[i][j] = Leg(cost=r.costs[nodes[j]], duration_s=float(rb.duration_h) * 3600, distance_m=float(rb.distance_km) * 1000)
            paths[(i, j)] = eids
        legs[i][i] = Leg(0.0, 0.0, 0.0)
        paths[(i, i)] = []
    matrix_stats["duration_ms"] = round(matrix_stats["duration_ms"], 2)

    if objective is Objective.TIME:
        wait_cost = 1.0
    elif objective in (Objective.MONEY, Objective.BALANCED) and ctx.cfg.include_driver:
        wait_cost = float(ctx.cfg.driver_cost_per_hour) / 3600
    else:
        wait_cost = 0.0
    if objective is Objective.BALANCED:
        wait_cost += float(ctx.cfg.value_of_time_per_hour) / 3600

    result = plan_multi_stop(
        legs, stops, ctx.vehicle.max_payload_kg, return_to_depot=req.get("return_to_depot", True),
        allow_reload=req.get("allow_reload", False), algorithm=algorithm, waiting_cost_per_s=wait_cost,
        limits=MultiStopLimits(max_stops=s.multi_stop_max_stops, max_expanded_states=s.multi_stop_max_states),
    )
    if not result.feasible:
        raise Unprocessable(result.message, code=f"plan_{result.status}", details={"search_stats": result.stats})

    # Assemble the full route and allocate costs per delivery.
    seq = result.sequence
    all_edges: list[str] = []
    leg_rows: list[dict[str, Any]] = []
    for a, b in zip(seq, seq[1:], strict=False):
        eids = paths[(a.index, b.index)]
        rb = route_breakdown(_edges(ctx, eids), ctx.cfg, include_fixed=False)
        leg_rows.append({"from": a.index, "to": b.index, "edges": eids, "money": rb.total, "rb": rb, "step": b})
        all_edges.extend(eids)
    total_rb = route_breakdown(_edges(ctx, all_edges), ctx.cfg, include_fixed=False)
    total_rb.fixed = ctx.cfg.fixed_cost_per_trip * result.trips
    waiting_s = sum(st.wait_s for st in seq)
    if ctx.cfg.include_driver and waiting_s:
        total_rb.driver += Decimal(str(waiting_s)) / 3600 * ctx.cfg.driver_cost_per_hour
    total_rb.round_components()

    allocation: dict[int, Decimal] = {k: Decimal("0") for k in range(1, n)}
    trip_members: list[int] = []
    for leg in leg_rows:
        to = leg["to"]
        extra_wait = Decimal("0")
        if ctx.cfg.include_driver and leg["step"].wait_s:
            extra_wait = Decimal(str(leg["step"].wait_s)) / 3600 * ctx.cfg.driver_cost_per_hour
        if to != DEPOT:
            allocation[to] += leg["money"] + extra_wait
            trip_members.append(to)
        else:
            members = trip_members or list(allocation)
            share = (leg["money"] + ctx.cfg.fixed_cost_per_trip) / len(members)
            for m in members:
                allocation[m] += share
            trip_members = []
    if trip_members:  # last trip without return: fixed cost still applies
        share = ctx.cfg.fixed_cost_per_trip / len(trip_members)
        for m in trip_members:
            allocation[m] += share
    rounded = {k: money(v) for k, v in allocation.items()}
    diff = money(total_rb.total) - sum(rounded.values())
    if rounded and diff:
        last = list(rounded)[-1]
        rounded[last] += diff

    total_load_kg = sum(o.weight_kg for o in orders)
    greedy = nearest_neighbour_order(legs, n - 1, req.get("return_to_depot", True))
    greedy_info = None
    if greedy is not None:
        g_order, g_cost = greedy
        g_edges: list[str] = []
        prev = DEPOT
        for k in g_order + ([DEPOT] if req.get("return_to_depot", True) else []):
            g_edges.extend(paths.get((prev, k), []))
            prev = k
        g_rb = route_breakdown(_edges(ctx, g_edges), ctx.cfg)
        comparable = total_load_kg <= ctx.vehicle.max_payload_kg and not any(
            st.window_start_s is not None or st.window_end_s is not None for st in stops)
        greedy_info = {"method": "nearest_neighbour", "order": [orders[k - 1].reference for k in g_order],
                       "objective_value": round(g_cost, 4), "total_cost": str(money(g_rb.total)),
                       "distance_m": round(float(g_rb.distance_km) * 1000, 1), "comparable": comparable,
                       "note": "Greedy nearest-neighbour ordering in a single trip." + (
                           "" if comparable else " Not a valid baseline here: it ignores the capacity and/or "
                           "time-window constraints this plan must satisfy, so no savings are claimed.")}

    warnings = list(result.warnings) + total_rb.warnings()
    fresh = freshness(db, ctx.net)
    if fresh["stale"]:
        warnings.append(f"Road network data is older than {fresh['stale_after_days']} days.")
    assumptions = ctx.assumptions + [
        f"Exact {algorithm.upper()} search over (location, visited set, remaining capacity) states using a "
        f"{n}×{n} leg matrix computed by {n} one-to-many UCS runs.",
        "Each stop is allocated the cost of the leg that reaches it; legs back to the warehouse and fixed trip costs "
        "are split evenly among that trip's stops.",
        f"Service time per stop from the order (default 5 min). Departure {departure.isoformat()}.",
    ]
    if algorithm == "ucs":
        assumptions.append("UCS on this problem is exponential in the number of stops (O(n²·2ⁿ) states).")
    else:
        assumptions.append("A* heuristic: max over unvisited stops of (leg to stop + return leg) — admissible lower bound.")

    total_load = sum(o.weight_kg for o in orders)
    plan = RoutePlan(
        name=req.get("name") or f"{depot.label}: {len(orders)} deliveries",
        kind="multi", status="estimated", warehouse_id=depot.warehouse_id, vehicle_id=ctx.vehicle.id,
        network_id=ctx.net.id, network_revision=ctx.net.revision, algorithm=f"multi_stop_{algorithm}",
        objective=objective.value, objective_value=round(result.total_cost, 4),
        objective_formula=objective_formula(objective, ctx.cfg) + "; summed over legs plus waiting cost",
        origin={"label": depot.label, "lat": depot.lat, "lon": depot.lon, "node": nodes[0], "snap_m": round(snapped[0][1], 1)},
        destination=None, return_to_depot=req.get("return_to_depot", True), request=_jsonable(req),
        cost_config=ctx.cfg.as_dict(), vehicle_snapshot=vehicle_snapshot(ctx.vehicle),
        distance_m=round(float(total_rb.distance_km) * 1000, 1), duration_s=round(result.total_duration_s, 1),
        total_cost=money(total_rb.total), currency=ctx.cfg.currency,
        breakdown={**total_rb.as_dict(), "waiting_s": round(waiting_s, 1), "trips": result.trips,
                   "total_load_kg": total_load, "capacity_kg": ctx.vehicle.max_payload_kg,
                   "utilization": round(min(1.0, total_load / (ctx.vehicle.max_payload_kg * result.trips)), 4)},
        emissions_kg=float(total_rb.emissions_kg) if total_rb.emissions_kg is not None else None,
        baseline=greedy_info,
        estimated_savings=(Decimal(greedy_info["total_cost"]) - money(total_rb.total))
        if greedy_info and greedy_info["comparable"] else None,
        geometry=_geometry(ctx, all_edges, nodes[0]), node_path=[nodes[st.index] for st in seq],
        search_stats={"matrix": matrix_stats, "plan": result.stats}, assumptions=assumptions, warnings=warnings,
    )
    stop_rows = [RouteStop(sequence=0, kind="origin", label=depot.label, lat=depot.lat, lon=depot.lon, node_id=str(nodes[0]),
                           load_kg=ctx.vehicle.max_payload_kg)]
    for i, leg in enumerate(leg_rows, start=1):
        st = leg["step"]
        p = points[st.index]
        if st.index == DEPOT:
            kind = "return" if i == len(leg_rows) else "reload"
        else:
            kind = "delivery"
        stop_rows.append(RouteStop(
            sequence=i, kind=kind, label=p.label, lat=p.lat, lon=p.lon, node_id=str(nodes[st.index]),
            delivery_order_id=p.order_id, arrival_s=round(st.arrival_s, 1), wait_s=round(st.wait_s, 1),
            leg_distance_m=round(float(leg["rb"].distance_km) * 1000, 1), leg_cost=money(leg["money"]),
            allocated_cost=rounded.get(st.index) if kind == "delivery" else None, load_kg=st.capacity_left_kg))
    plan.stops = stop_rows
    plan.edges = _edge_snapshot(ctx, all_edges)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    out = plan_to_dict(plan, include_edges=False)
    out.update({"freshness": fresh, "named_segments": _named_segments(ctx, all_edges),
                "cost_per_delivery": str(money(total_rb.total / len(orders))),
                "legs": [{"from": points[leg["from"]].label, "to": points[leg["to"]].label,
                          "distance_m": round(float(leg["rb"].distance_km) * 1000, 1),
                          "duration_s": round(float(leg["rb"].duration_h) * 3600, 1),
                          "cost": str(money(leg["money"])),
                          "geometry": _geometry(ctx, leg["edges"], nodes[leg["from"]])} for leg in leg_rows]})
    return out


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)


# --------------------------------------------------------------- serialise

def plan_to_dict(plan: RoutePlan, *, include_edges: bool = True) -> dict[str, Any]:
    d = {
        "id": plan.id, "plan_id": plan.id, "name": plan.name, "kind": plan.kind, "status": plan.status,
        "warehouse_id": plan.warehouse_id, "vehicle_id": plan.vehicle_id, "network_id": plan.network_id,
        "network_revision": plan.network_revision, "parent_plan_id": plan.parent_plan_id,
        "algorithm": plan.algorithm, "objective": plan.objective, "objective_value": plan.objective_value,
        "objective_formula": plan.objective_formula, "origin": plan.origin, "destination": plan.destination,
        "return_to_depot": plan.return_to_depot, "distance_m": plan.distance_m, "duration_s": plan.duration_s,
        "total_cost": str(plan.total_cost), "currency": plan.currency, "breakdown": plan.breakdown,
        "emissions_kg": plan.emissions_kg, "baseline": plan.baseline,
        "estimated_savings": None if plan.estimated_savings is None else str(plan.estimated_savings),
        "geometry": plan.geometry, "node_count": len(plan.node_path or []), "search_stats": plan.search_stats,
        "assumptions": plan.assumptions, "warnings": plan.warnings, "cost_config": plan.cost_config,
        "vehicle": plan.vehicle_snapshot, "request": plan.request,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "saved_at": plan.saved_at.isoformat() if plan.saved_at else None,
        "dispatched_at": plan.dispatched_at.isoformat() if plan.dispatched_at else None,
        "completed_at": plan.completed_at.isoformat() if plan.completed_at else None,
        "cost_is_estimate": True,
        "stops": [{"sequence": s.sequence, "kind": s.kind, "label": s.label, "lat": s.lat, "lon": s.lon,
                   "node_id": s.node_id, "delivery_order_id": s.delivery_order_id, "arrival_s": s.arrival_s,
                   "wait_s": s.wait_s, "leg_distance_m": s.leg_distance_m, "leg_cost": str(s.leg_cost),
                   "allocated_cost": None if s.allocated_cost is None else str(s.allocated_cost),
                   "capacity_left_kg" if plan.kind == "multi" else "load_kg": s.load_kg} for s in plan.stops],
        "actual": None,
    }
    if plan.actual is not None:
        a = plan.actual
        d["actual"] = {"distance_km": a.distance_km, "duration_min": a.duration_min,
                       "fuel_cost": _s(a.fuel_cost), "toll_cost": _s(a.toll_cost), "other_cost": _s(a.other_cost),
                       "total_cost": str(a.total_cost), "deliveries_completed": a.deliveries_completed,
                       "deliveries_failed": a.deliveries_failed, "completed_at": a.completed_at.isoformat(),
                       "notes": a.notes}
    if include_edges:
        d["edges"] = [{"sequence": e.sequence, "edge_id": e.edge_id, "way_id": e.way_id, "name": e.name,
                       "highway": e.highway, "length_m": e.length_m, "duration_s": e.duration_s,
                       "cost": str(e.cost), "toll_status": e.toll_status} for e in plan.edges]
    return d


def _s(v):
    return None if v is None else str(money(Decimal(v)))


# ------------------------------------------------------------------ reroute

ACTIVE_STATUSES = ("saved", "dispatched")


def affected_plans(db: Session, network_id: int, edge_ids: list[str]) -> list[RoutePlan]:
    ids = db.scalars(
        select(RouteEdge.plan_id).join(RoutePlan).where(
            RoutePlan.network_id == network_id, RoutePlan.status.in_(ACTIVE_STATUSES), RouteEdge.edge_id.in_(edge_ids)
        ).distinct()
    ).all()
    return [db.get(RoutePlan, i) for i in ids]


def reroute_plan(db: Session, plan: RoutePlan, closure_id: int | None = None) -> RerouteEvent:
    """Recalculate a plan on the current network state and record the comparison."""
    blocked = active_blocked_edges(db, plan.network_id) if plan.network_id else set()
    hit = [e.edge_id for e in plan.edges if e.edge_id in blocked]
    req = dict(plan.request or {})
    req.pop("trace", None)
    req["include_benchmarks"] = False
    req["include_alternatives"] = False
    req["name"] = f"{plan.name} (rerouted)"[:160]
    ev = RerouteEvent(original_plan_id=plan.id, closure_id=closure_id, affected_edge_ids=hit)
    try:
        new = calculate_route(db, req) if plan.kind == "single" else plan_deliveries(db, req)
    except Unprocessable as exc:
        ev.outcome = "no_alternative"
        ev.message = exc.message
        db.add(ev)
        db.commit()
        return ev
    new_plan = db.get(RoutePlan, new["plan_id"])
    new_plan.parent_plan_id = plan.id
    new_plan.status = plan.status
    new_plan.saved_at = plan.saved_at
    new_plan.dispatched_at = plan.dispatched_at
    plan.status = "superseded"
    ev.new_plan_id = new_plan.id
    ev.outcome = "rerouted"
    ev.delta_distance_m = round(new_plan.distance_m - plan.distance_m, 1)
    ev.delta_duration_s = round(new_plan.duration_s - plan.duration_s, 1)
    ev.delta_cost = money(Decimal(new_plan.total_cost) - Decimal(plan.total_cost))
    ev.message = (f"Rerouted around {len(hit)} closed segment(s): "
                  f"{ev.delta_distance_m:+.0f} m, {ev.delta_duration_s / 60:+.1f} min, {ev.delta_cost:+} {plan.currency}.")
    db.add(ev)
    db.commit()
    return ev


def reroute_event_dict(ev: RerouteEvent) -> dict[str, Any]:
    return {"id": ev.id, "original_plan_id": ev.original_plan_id, "new_plan_id": ev.new_plan_id,
            "closure_id": ev.closure_id, "outcome": ev.outcome, "affected_edge_ids": ev.affected_edge_ids,
            "delta_distance_m": ev.delta_distance_m, "delta_duration_s": ev.delta_duration_s,
            "delta_cost": _s(ev.delta_cost), "message": ev.message,
            "created_at": ev.created_at.isoformat() if ev.created_at else None}
