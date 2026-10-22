"""API integration tests over the fixture network (no external services)."""

from decimal import Decimal

from sqlalchemy import create_engine, inspect

from .conftest import LAT0, LON0, STEP

API = "/api/v1"


def route(client, seeded, dest=(4, 4), vehicle="van", **kw):
    body = {"warehouse_id": seeded["warehouse"]["id"], "vehicle_id": seeded[vehicle]["id"],
            "destination": {"lat": LAT0 + dest[0] * STEP, "lon": LON0 + dest[1] * STEP}, **kw}
    return client.post(f"{API}/routes/calculate", json=body)


def components_sum(b):
    return sum(Decimal(b[k]) for k in ("fuel", "driver", "operating", "toll", "extra", "fixed"))


def test_migrations_created_all_tables(client):
    import os
    eng = create_engine(os.environ["ROUTEWISE_DATABASE_URL"])
    tables = set(inspect(eng).get_table_names())
    assert {"route_plans", "route_edges", "road_closures", "delivery_orders", "vehicles", "alembic_version"} <= tables


def test_health(client):
    assert client.get(f"{API}/health").json()["status"] == "ok"


def test_network_import(seeded):
    net = seeded["network"]
    assert net["status"] == "ready" and net["is_active"]
    assert net["node_count"] == 27  # 25 grid nodes + isolated stub
    assert "main connected component" in net["status_detail"]


def test_route_breakdown_is_consistent(client, seeded):
    r = route(client, seeded)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "estimated" and d["cost_is_estimate"]
    assert components_sum(d["breakdown"]) == Decimal(d["total_cost"])
    # Route geometry starts at the depot and ends at the destination node.
    assert d["geometry"][0] == [LAT0, LON0]
    assert d["geometry"][-1] == [LAT0 + 4 * STEP, LON0 + 4 * STEP]
    assert d["search_stats"]["expanded_nodes"] > 0
    assert d["alternatives"] and all(a["objective"] != "money" for a in d["alternatives"])
    assert any("static" in a.lower() for a in d["assumptions"])


def test_fuel_efficiency_affects_cost(client, seeded):
    van = route(client, seeded, dest=(0, 4), preferences={"include_driver": False, "include_operating": False}).json()
    truck = route(client, seeded, dest=(0, 4), vehicle="truck",
                  preferences={"include_driver": False, "include_operating": False}).json()
    assert van["distance_m"] == truck["distance_m"]
    # Truck: 4 km/l vs van 10 km/l -> 2.5x fuel cost on the same path.
    ratio = Decimal(truck["breakdown"]["fuel"]) / Decimal(van["breakdown"]["fuel"])
    assert abs(ratio - Decimal("2.5")) < Decimal("0.01")  # values are rounded to paise


def test_missing_toll_amount_reported_and_configured_toll_included(client, seeded):
    d = route(client, seeded, dest=(2, 4), objective="time").json()
    assert any("NOT included" in w for w in d["warnings"])  # Toll Expressway has no amount yet
    net_id = seeded["network"]["id"]
    seg = client.get(f"{API}/networks/{net_id}/segments/nearest",
                     params={"lat": LAT0 + 2 * STEP, "lon": LON0 + 3.5 * STEP}).json()[0]
    assert seg["toll"] == "yes"
    r = client.put(f"{API}/networks/{net_id}/overrides/{seg['id']}", json={"toll_cost": "40"})
    assert r.status_code == 200
    d2 = route(client, seeded, dest=(2, 4), objective="time").json()
    if seg["id"] in {e for e in client.get(f"{API}/routes/{d2['plan_id']}").json()["edges"] and
                     [x["edge_id"] for x in client.get(f"{API}/routes/{d2['plan_id']}").json()["edges"]]}:
        assert Decimal(d2["breakdown"]["toll"]) >= Decimal("40")
    # Money-optimal route avoids paying the toll when a free path of similar length exists.
    m = route(client, seeded, dest=(2, 4), objective="money").json()
    assert Decimal(m["total_cost"]) <= Decimal(d2["total_cost"])
    client.put(f"{API}/networks/{net_id}/overrides/{seg['id']}", json={})


def test_vehicle_weight_restriction(client, seeded):
    van = route(client, seeded, dest=(4, 4), objective="distance").json()
    truck = route(client, seeded, dest=(4, 4), vehicle="truck", objective="distance").json()
    van_edges = [e["edge_id"] for e in client.get(f"{API}/routes/{van['plan_id']}").json()["edges"]]
    truck_route = client.get(f"{API}/routes/{truck['plan_id']}").json()
    assert all(e["name"] != "Col 4 Avenue" for e in truck_route["edges"])  # maxweight 3.5 t
    assert van_edges  # van may use it


def test_invalid_inputs(client, seeded):
    assert client.post(f"{API}/vehicles", json={"name": "Bad", "category": "van", "fuel_type": "diesel",
                                               "efficiency_km_per_unit": "0", "max_payload_kg": 10}).status_code == 422
    r = route(client, seeded, dest=(40, 40))
    assert r.status_code == 422 and r.json()["error"]["code"] == "outside_coverage"
    r = client.post(f"{API}/routes/calculate", json={"vehicle_id": 1})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_capacity_violation_rejected(client, seeded):
    o = seeded["orders"][0]
    heavy = client.post(f"{API}/orders", json={"reference": "HEAVY-1", "customer_id": o["customer_id"],
                                               "address_id": o["address_id"], "weight_kg": 900}).json()
    r = client.post(f"{API}/routes/calculate", json={"warehouse_id": seeded["warehouse"]["id"],
                                                      "delivery_order_id": heavy["id"], "vehicle_id": seeded["van"]["id"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "capacity_exceeded"
    ids = [x["id"] for x in seeded["orders"]]  # 4 x 150 kg = 600 > 500 kg van
    r = client.post(f"{API}/routes/multi-stop", json={"warehouse_id": seeded["warehouse"]["id"],
                                                       "delivery_order_ids": ids, "vehicle_id": seeded["van"]["id"]})
    assert r.status_code == 422 and "exceeds vehicle capacity" in r.json()["error"]["message"]
    client.delete(f"{API}/orders/{heavy['id']}")


def test_multi_stop_plan(client, seeded):
    ids = [x["id"] for x in seeded["orders"]]
    r = client.post(f"{API}/routes/multi-stop", json={"warehouse_id": seeded["warehouse"]["id"], "delivery_order_ids": ids,
                                                       "vehicle_id": seeded["van"]["id"], "allow_reload": True,
                                                       "algorithm": "astar"})
    assert r.status_code == 200, r.text
    d = r.json()
    deliveries = [s for s in d["stops"] if s["kind"] == "delivery"]
    assert sorted(s["delivery_order_id"] for s in deliveries) == sorted(ids)
    assert d["breakdown"]["trips"] == 2
    assert sum(Decimal(s["allocated_cost"]) for s in deliveries) == Decimal(d["total_cost"])
    assert d["stops"][-1]["kind"] == "return"
    big = client.post(f"{API}/routes/multi-stop", json={"warehouse_id": seeded["warehouse"]["id"], "delivery_order_ids": ids,
                                                         "vehicle_id": seeded["truck"]["id"]}).json()
    assert big["breakdown"]["trips"] == 1


def test_closure_triggers_reroute_and_no_alternative(client, seeded):
    net = seeded["network"]["id"]
    d = route(client, seeded, dest=(4, 2), objective="distance").json()
    pid = d["plan_id"]
    assert client.patch(f"{API}/routes/{pid}/status", json={"status": "saved"}).json()["status"] == "saved"
    edges = client.get(f"{API}/routes/{pid}").json()["edges"]
    mid = edges[len(edges) // 2]["edge_id"]
    r = client.post(f"{API}/networks/{net}/closures", json={"edge_ids": [mid], "reason": "test"}).json()
    assert pid in r["affected_plan_ids"]
    ev = r["reroutes"][0]
    assert ev["outcome"] == "rerouted" and ev["delta_distance_m"] >= 0
    new = client.get(f"{API}/routes/{ev['new_plan_id']}").json()
    assert mid not in [e["edge_id"] for e in new["edges"]]
    assert new["parent_plan_id"] == pid and new["network_revision"] > d["network_revision"]
    assert client.get(f"{API}/routes/{pid}").json()["status"] == "superseded"
    client.post(f"{API}/networks/{net}/closures/{r['closure']['id']}/reopen")

    # Close every road into corner (0,4) -> no alternative.
    target = route(client, seeded, dest=(0, 4)).json()
    client.patch(f"{API}/routes/{target['plan_id']}/status", json={"status": "saved"})
    closures = []
    for lat, lon in ((LAT0, LON0 + 3.5 * STEP), (LAT0 + 0.5 * STEP, LON0 + 4 * STEP)):
        res = client.post(f"{API}/networks/{net}/closures", json={"lat": lat, "lon": lon, "auto_reroute": True}).json()
        closures.append(res)
    last = closures[-1]["reroutes"]
    assert last and last[-1]["outcome"] == "no_alternative"
    r = route(client, seeded, dest=(0, 4))
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_route"
    for c in closures:
        client.post(f"{API}/networks/{net}/closures/{c['closure']['id']}/reopen")
    assert route(client, seeded, dest=(0, 4)).status_code == 200


def test_history_persists_after_restart(client, seeded):
    pid = route(client, seeded, dest=(3, 3)).json()["plan_id"]
    from app.database import session as dbs
    from app.services import road_network
    dbs.engine.dispose()
    road_network.invalidate_cache()
    p = client.get(f"{API}/routes/{pid}").json()
    assert p["id"] == pid and p["edges"] and p["cost_config"]["currency"] == "INR"


def test_csv_import_reports_row_errors(client, seeded):
    csv_text = (
        "reference,customer_name,address,lat,lon,weight_kg,priority,warehouse\n"
        "CSV-1,Acme,Corner A,28.601,77.201,10,high,Grid Depot\n"
        "CSV-2,Acme,Corner B,,77.2,10,normal,\n"
        "CSV-3,,Corner C,,,abc,urgent,Nowhere\n"
        "CSV-1,Acme,Dup,,,5,low,\n"
    )
    files = {"file": ("orders.csv", csv_text, "text/csv")}
    dry = client.post(f"{API}/orders/import", files=files, params={"dry_run": True}).json()
    assert dry["valid_rows"] == 1 and dry["created_orders"] == 0
    fields = {(e["row"], e["field"]) for e in dry["errors"]}
    assert (3, "lat/lon") in fields and (4, "customer_name") in fields and (4, "weight_kg") in fields
    assert (4, "warehouse") in fields and (5, "reference") in fields
    real = client.post(f"{API}/orders/import", files=files).json()
    assert real["created_orders"] == 1
    bad = client.post(f"{API}/orders/import", files={"file": ("x.csv", "foo,bar\n1,2\n", "text/csv")})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "missing_columns"


def test_actual_vs_estimated_and_analytics(client, seeded):
    pid = route(client, seeded, dest=(1, 3)).json()["plan_id"]
    assert client.post(f"{API}/routes/{pid}/actual", json={"total_cost": "50"}).status_code == 409
    client.patch(f"{API}/routes/{pid}/status", json={"status": "saved"})
    client.patch(f"{API}/routes/{pid}/status", json={"status": "dispatched"})
    r = client.post(f"{API}/routes/{pid}/actual", json={"fuel_cost": "30", "toll_cost": "0", "deliveries_completed": 1})
    assert r.status_code == 200 and r.json()["status"] == "completed"
    assert r.json()["actual"]["total_cost"] == "30.00"
    s = client.get(f"{API}/analytics/summary").json()
    assert s["totals"]["committed_plans"] >= 1
    assert Decimal(s["totals"]["actual_recorded_cost"]) >= Decimal("30")
    assert s["completion"]["deliveries_completed"] >= 1


def test_settings_change_affects_costs(client, seeded):
    before = route(client, seeded, dest=(3, 1), objective="distance").json()
    client.put(f"{API}/settings", json={"energy_prices": {"diesel": "200"}})
    after = route(client, seeded, dest=(3, 1), objective="distance").json()
    assert Decimal(after["breakdown"]["fuel"]) > Decimal(before["breakdown"]["fuel"])
    assert client.get(f"{API}/settings").json()["energy_prices_updated_at"] is not None


def test_benchmarks_ucs_equals_astar(client, seeded):
    d = route(client, seeded, dest=(4, 3), include_benchmarks=True, trace=True).json()
    b = {x["algorithm"]: x for x in d["benchmarks"]}
    assert b["astar"]["matches_ucs_cost"] is True
    assert b["astar"]["expanded_nodes"] <= b["ucs"]["expanded_nodes"]
    assert d["trace"]["events"] and d["trace"]["events"][0]["k"] == "pop"


def test_route_export_and_duplicate(client, seeded):
    pid = route(client, seeded, dest=(2, 1)).json()["plan_id"]
    csv_text = client.get(f"{API}/routes/{pid}/export.csv").text
    assert "ESTIMATE" in csv_text and "Assumptions" in csv_text
    dup = client.post(f"{API}/routes/{pid}/duplicate").json()
    assert dup["plan_id"] != pid


def test_graph_survives_missing_cache_file(client, seeded):
    """Hosts without persistent disks lose the file cache; the DB copy must be used."""
    from pathlib import Path

    from app.services import road_network
    net = client.get(f"{API}/networks/{seeded['network']['id']}").json()
    from app.database import SessionLocal
    from app.models import RoadNetwork
    with SessionLocal() as db:
        Path(db.get(RoadNetwork, net["id"]).file_path).unlink()
    road_network.invalidate_cache()
    assert route(client, seeded, dest=(1, 1)).status_code == 200


def test_production_requires_admin_token(monkeypatch):
    import pytest

    from app.core.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("ROUTEWISE_ENVIRONMENT", "production")
    monkeypatch.delenv("ROUTEWISE_ADMIN_TOKEN", raising=False)
    try:
        with pytest.raises(RuntimeError, match="ADMIN_TOKEN"):
            get_settings()
        monkeypatch.setenv("ROUTEWISE_ADMIN_TOKEN", "x" * 24)
        monkeypatch.setenv("ROUTEWISE_CORS_ORIGINS", "app.example.com,http://localhost:5173")
        s = get_settings()
        assert s.cors_origins == ["https://app.example.com", "http://localhost:5173"]
    finally:
        get_settings.cache_clear()
