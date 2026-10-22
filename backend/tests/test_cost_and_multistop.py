from decimal import Decimal

import pytest

from app.algorithms.cost_model import (
    CostConfig,
    Objective,
    VehicleRestrictions,
    make_cost_fn,
    route_breakdown,
)
from app.algorithms.graph import WeightedGraph
from app.algorithms.multi_stop import Leg, MultiStopLimits, StopSpec, nearest_neighbour_order, plan_multi_stop
from app.algorithms.ucs import uniform_cost_search


def cfg(**kw):
    base = dict(energy_price_per_unit=Decimal("100"), efficiency_km_per_unit=Decimal("10"),
                driver_cost_per_hour=Decimal("200"), operating_cost_per_km=Decimal("2"))
    base.update(kw)
    return CostConfig(**base)


def road_graph():
    g = WeightedGraph()
    # Direct toll expressway (fast, tolled) vs. free arterial (longer, slower).
    g.add_edge("toll", "W", "C", length_m=10_000, speed_kph=80, toll="yes", toll_cost=Decimal("150"))
    g.add_edge("a1", "W", "M", length_m=6_000, speed_kph=40, toll="no")
    g.add_edge("a2", "M", "C", length_m=6_000, speed_kph=40, toll="no")
    return g


def test_segment_formula_matches_documentation():
    g = road_graph()
    rb = route_breakdown([g.edge("a1")], cfg())
    # 6 km: fuel 6/10*100 = 60; driver 0.15h*200 = 30; operating 6*2 = 12
    assert rb.fuel == Decimal("60") and rb.driver == Decimal("30.0") and rb.operating == Decimal("12")
    assert rb.total == Decimal("102")


def test_fuel_efficiency_changes_cost():
    g = road_graph()
    e = [g.edge("a1")]
    efficient = route_breakdown(e, cfg(efficiency_km_per_unit=Decimal("20"))).fuel
    thirsty = route_breakdown(e, cfg(efficiency_km_per_unit=Decimal("5"))).fuel
    assert efficient == Decimal("30") and thirsty == Decimal("120")


def test_toll_included_and_affects_route_choice():
    g = road_graph()
    money = make_cost_fn(Objective.MONEY, cfg())
    r = uniform_cost_search(g, "W", "C", money)
    # toll route: fuel 100 + driver 25 + op 20 + toll 150 = 295; arterial: 2*102 = 204
    assert r.edge_path == ["a1", "a2"]
    rb_toll = route_breakdown([g.edge("toll")], cfg())
    assert rb_toll.toll == Decimal("150") and rb_toll.total == Decimal("295.0")
    # Fastest route takes the toll road.
    t = uniform_cost_search(g, "W", "C", make_cost_fn(Objective.TIME, cfg()))
    assert t.edge_path == ["toll"]


def test_toll_excluded_when_disabled():
    rb = route_breakdown([road_graph().edge("toll")], cfg(include_tolls=False))
    assert rb.toll == 0


def test_missing_toll_amount_is_reported_not_assumed_free():
    g = WeightedGraph()
    g.add_edge("t", "A", "B", length_m=5000, speed_kph=60, toll="yes")
    g.add_edge("u", "B", "C", length_m=1000, speed_kph=60)  # no toll tag
    rb = route_breakdown([g.edge("t"), g.edge("u")], cfg())
    assert rb.toll == 0
    assert rb.toll_km["unavailable"] == Decimal("5")
    assert rb.toll_km["unconfirmed"] == Decimal("1")
    w = " ".join(rb.warnings())
    assert "NOT included" in w and "not confirmed toll-free" in w
    est = route_breakdown([g.edge("t")], cfg(toll_rate_per_km_estimate=Decimal("2.5")))
    assert est.toll == Decimal("12.5") and "estimate" in " ".join(est.warnings())


def test_disabled_components_are_zero():
    rb = route_breakdown([road_graph().edge("a1")], cfg(include_driver=False, include_operating=False))
    assert rb.driver == 0 and rb.operating == 0 and rb.fuel == 60


def test_vehicle_restrictions():
    g = WeightedGraph()
    g.add_edge("bridge", "A", "B", length_m=100, speed_kph=30, maxweight_t=3.5)
    g.add_edge("ring", "A", "B", length_m=900, speed_kph=30)
    heavy = make_cost_fn(Objective.DISTANCE, cfg(), VehicleRestrictions(gross_weight_t=12))
    light = make_cost_fn(Objective.DISTANCE, cfg(), VehicleRestrictions(gross_weight_t=2))
    assert uniform_cost_search(g, "A", "B", heavy).edge_path == ["ring"]
    assert uniform_cost_search(g, "A", "B", light).edge_path == ["bridge"]


def test_invalid_config_rejected():
    with pytest.raises(ValueError):
        cfg(efficiency_km_per_unit=Decimal("0"))
    with pytest.raises(ValueError):
        cfg(driver_cost_per_hour=Decimal("-1"))


def test_balanced_objective_is_money_plus_time_value():
    g = road_graph()
    c = cfg(value_of_time_per_hour=Decimal("2000"))
    fn = make_cost_fn(Objective.BALANCED, c)
    # toll: 295 + 2000*0.125 = 545 ; arterial: 204 + 2000*0.3 = 804 -> toll wins
    assert uniform_cost_search(g, "W", "C", fn).edge_path == ["toll"]


# ---------------------------------------------------------------- multi-stop

def matrix(costs):
    return [[None if c is None else Leg(cost=c, duration_s=c * 60) for c in row] for row in costs]


SQUARE = matrix([
    # depot, s1, s2, s3
    [0, 1, 5, 4],
    [1, 0, 1, 5],
    [5, 1, 0, 1],
    [4, 5, 1, 0],
])


def stops(*loads, **kw):
    return [StopSpec(key=f"s{i+1}", load_kg=w, **kw) for i, w in enumerate(loads)]


@pytest.mark.parametrize("algo", ["ucs", "astar"])
def test_multi_stop_optimal_order(algo):
    r = plan_multi_stop(SQUARE, stops(1, 1, 1), capacity_kg=10, algorithm=algo)
    assert r.feasible
    assert [s.index for s in r.sequence] == [0, 1, 2, 3, 0]
    assert r.total_cost == 7


def test_astar_expands_no_more_than_ucs():
    u = plan_multi_stop(SQUARE, stops(1, 1, 1), 10, algorithm="ucs")
    a = plan_multi_stop(SQUARE, stops(1, 1, 1), 10, algorithm="astar")
    assert a.total_cost == u.total_cost
    assert a.stats["expanded_states"] <= u.stats["expanded_states"]


def test_capacity_violation_rejected():
    r = plan_multi_stop(SQUARE, stops(4, 4, 4), capacity_kg=10)
    assert not r.feasible and r.status == "infeasible" and "exceeds vehicle capacity" in r.message
    r2 = plan_multi_stop(SQUARE, stops(11, 1, 1), capacity_kg=10, allow_reload=True)
    assert not r2.feasible and "individually exceed" in r2.message


def test_capacity_with_reload_trips():
    r = plan_multi_stop(SQUARE, stops(6, 6, 1), capacity_kg=10, allow_reload=True)
    assert r.feasible and r.trips == 2
    assert all(step.capacity_left_kg >= 0 for step in r.sequence)
    loads = {"s1": 6, "s2": 6, "s3": 1}
    carried = 0
    for step in r.sequence[1:]:
        if step.index == 0:
            carried = 0
        else:
            carried += loads[step.stop_key]
            assert carried <= 10


def test_time_windows_change_order():
    # Unconstrained optimum is 0-1-2-3-0 (cost 5), reaching s3 after 3 minutes.
    m = matrix([[0, 1, 2, 2], [3, 0, 1, 5], [5, 1, 0, 1], [2, 5, 1, 0]])
    free = plan_multi_stop(m, stops(1, 1, 1), 10)
    assert [s.index for s in free.sequence] == [0, 1, 2, 3, 0] and free.total_cost == 5
    # s3 must be reached within 2 minutes, so it has to be served first: best is 0-3-2-1-0 (cost 7).
    sp = [StopSpec("s1", 1), StopSpec("s2", 1), StopSpec("s3", 1, window_end_s=120)]
    r = plan_multi_stop(m, sp, 10)
    assert r.feasible and [s.index for s in r.sequence] == [0, 3, 2, 1, 0]
    assert r.total_cost == 7


def test_infeasible_time_windows():
    sp = [StopSpec("s1", 1, window_end_s=10), StopSpec("s2", 1), StopSpec("s3", 1)]
    r = plan_multi_stop(SQUARE, sp, 10)
    assert not r.feasible and r.status == "infeasible"


def test_unreachable_stop():
    m = matrix([[0, 1, None], [1, 0, None], [None, None, 0]])
    r = plan_multi_stop(m, stops(1, 1), 10)
    assert not r.feasible and "unreachable" in r.message


def test_stop_limit_and_budget():
    r = plan_multi_stop(SQUARE, stops(1, 1, 1), 10, limits=MultiStopLimits(max_stops=2))
    assert r.status == "limit_exceeded"
    r2 = plan_multi_stop(SQUARE, stops(1, 1, 1), 10, limits=MultiStopLimits(max_expanded_states=2))
    assert r2.status == "limit_exceeded" and "budget" in r2.message


def test_greedy_baseline_not_better_than_exact():
    nn = nearest_neighbour_order(SQUARE, 3, True)
    r = plan_multi_stop(SQUARE, stops(1, 1, 1), 10)
    assert nn is not None and nn[1] >= r.total_cost


def test_reported_total_equals_sum_of_reported_components():
    g = WeightedGraph()
    g.add_edge("x", "A", "B", length_m=1463.7, speed_kph=27, toll="no")
    d = route_breakdown([g.edge("x")], cfg(fixed_cost_per_trip=Decimal("50"))).as_dict()
    parts = sum(Decimal(d[k]) for k in ("fuel", "driver", "operating", "toll", "extra", "fixed"))
    assert parts == Decimal(d["total"])
