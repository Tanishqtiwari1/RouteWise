"""Built-in demonstration data (sample warehouses, fleet, customers, orders and plans).

Used when ROUTEWISE_DEMO_SEED=true: on start-up, a server with an empty database
loads the bundled Central New Delhi road network (a real OpenStreetMap import
stored in app/demo/) and then creates this sample data through the normal API
endpoints, so every plan is calculated by the real UCS engine. Records are
marked "Sample data for demonstration". Also used by scripts/seed_presentation.py.
"""

import gzip
import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

NOTE = "Sample data for demonstration"
BUNDLED_NETWORK = Path(__file__).parent / "demo" / "central_new_delhi.json.gz"
log_ = logging.getLogger(__name__)


def seed_sample_data(call, health, log=print) -> None:
    """Create the sample data. ``call(method, path, **kw)`` performs an API request and returns JSON."""
    if call("GET", "/warehouses")["total"]:
        log("Warehouses already exist; skipping sample data.")
        return
    # --- warehouses
    WAREHOUSES = {
        "cp": ("Connaught Place Hub", "Connaught Place, New Delhi 110001", 28.6315, 77.2167),
        "lodhi": ("Lodhi Road Depot", "Lodhi Road, New Delhi 110003", 28.5985, 77.2290),
    }
    wh = {k: call("POST", "/warehouses", json={"name": n, "address": a, "lat": la, "lon": lo, "notes": NOTE})
          for k, (n, a, la, lo) in WAREHOUSES.items()}

    # --- fleet (manufacturer-typical figures; edit on the Fleet page)
    VEHICLES = {
        "ace": {"name": "Tata Ace Gold · DL1L 4521", "category": "van", "fuel_type": "diesel", "efficiency_km_per_unit": "14",
                "max_payload_kg": 750, "gross_weight_t": 1.8, "height_m": 1.9, "operating_cost_per_km": "2.5",
                "fixed_cost_per_trip": "50", "emissions_kg_per_unit": "2.68"},
        "ev": {"name": "Electric cargo 3-wheeler · DL1E 0912", "category": "van", "fuel_type": "electric",
               "efficiency_km_per_unit": "12", "max_payload_kg": 550, "gross_weight_t": 1.0, "max_speed_kph": 50,
               "operating_cost_per_km": "0.8", "fixed_cost_per_trip": "30", "emissions_kg_per_unit": "0.71"},
        "truck": {"name": "Eicher Pro 2049 · DL1M 7733", "category": "light_truck", "fuel_type": "diesel",
                  "efficiency_km_per_unit": "9", "max_payload_kg": 2500, "gross_weight_t": 4.9, "height_m": 2.9,
                  "operating_cost_per_km": "4.5", "fixed_cost_per_trip": "120", "emissions_kg_per_unit": "2.68"},
        "bike": {"name": "Courier scooter · DL3S 2280", "category": "two_wheeler", "fuel_type": "petrol",
                 "efficiency_km_per_unit": "45", "max_payload_kg": 25, "max_speed_kph": 60,
                 "operating_cost_per_km": "0.6", "fixed_cost_per_trip": "0", "emissions_kg_per_unit": "2.31"},
    }
    veh = {k: call("POST", "/vehicles", json=v) for k, v in VEHICLES.items()}
    call("PUT", "/settings", json={"workspace_name": "RouteWise Delhi Operations", "default_vehicle_id": veh["ace"]["id"]})

    # --- customers, addresses, orders
    now = datetime.now(UTC)
    CUSTOMERS = [
        # name, address, lat, lon, kg, priority, warehouse, window
        ("Khan Market Grocers", "Khan Market, New Delhi", 28.6003, 77.2270, 180, "high", "lodhi", False),
        ("Mandi House Books", "Mandi House, New Delhi", 28.6258, 77.2341, 90, "normal", "cp", False),
        ("Gole Market Pharmacy", "Gole Market, New Delhi", 28.6370, 77.2050, 60, "urgent", "cp", True),
        ("Janpath Textiles", "Janpath, New Delhi", 28.6235, 77.2185, 240, "normal", "cp", False),
        ("Bengali Market Sweets", "Bengali Market, New Delhi", 28.6290, 77.2330, 120, "normal", "cp", False),
        ("Pandara Road Kitchens", "Pandara Road, New Delhi", 28.6050, 77.2340, 150, "high", "lodhi", True),
        ("Supreme Court Canteen", "Tilak Marg, New Delhi", 28.6223, 77.2400, 80, "normal", "lodhi", False),
        ("Rajiv Chowk Electronics", "Rajiv Chowk, New Delhi", 28.6328, 77.2197, 18, "high", "cp", False),
        ("Shahjahan Road Offices", "Shahjahan Road, New Delhi", 28.6090, 77.2240, 110, "low", "lodhi", False),
        ("KG Marg Clinic", "Kasturba Gandhi Marg, New Delhi", 28.6265, 77.2240, 35, "urgent", "cp", False),
        ("Ashoka Road Stationers", "Ashoka Road, New Delhi", 28.6200, 77.2120, 70, "normal", "cp", False),
        ("Barakhamba Corporate", "Barakhamba Road, New Delhi", 28.6300, 77.2270, 200, "normal", "cp", False),
    ]
    orders = {}
    for i, (name, addr, lat, lon, kg, prio, w, window) in enumerate(CUSTOMERS, start=1):
        cust = call("POST", "/customers", json={"name": name, "phone": f"+91 98100 {10000 + i * 137:05d}", "notes": NOTE})
        a = call("POST", f"/customers/{cust['id']}/addresses", params={"geocode": False},
                 json={"address_text": addr, "lat": lat, "lon": lon})
        body = {"reference": f"ORD-{2400 + i}", "customer_id": cust["id"], "address_id": a["id"], "warehouse_id": wh[w]["id"],
                "weight_kg": kg, "quantity": max(1, kg // 30), "priority": prio, "notes": NOTE}
        if window:
            body |= {"window_start": now.isoformat(), "window_end": (now + timedelta(days=3)).isoformat()}
        orders[name] = call("POST", "/orders", json=body)
    log(f"Created {len(wh)} warehouses, {len(veh)} vehicles, {len(orders)} customers/orders")


    def oid(name):
        return orders[name]["id"]


    def single(w, order, v, objective="money", bench=True):
        return call("POST", "/routes/calculate", json={"warehouse_id": wh[w]["id"], "delivery_order_id": oid(order),
                                                        "vehicle_id": veh[v]["id"], "objective": objective,
                                                        "include_benchmarks": bench})


    def multi(w, names, v, algorithm="astar", reload=False):
        return call("POST", "/routes/multi-stop", json={"warehouse_id": wh[w]["id"], "delivery_order_ids": [oid(n) for n in names],
                                                         "vehicle_id": veh[v]["id"], "algorithm": algorithm,
                                                         "allow_reload": reload, "return_to_depot": True})


    def status(p, s):
        return call("PATCH", f"/routes/{p['plan_id']}/status", json={"status": s})


    def complete(p, fuel, toll="0", other="0", done=1, failed=0, km=None):
        status(p, "saved")
        status(p, "dispatched")
        call("POST", f"/routes/{p['plan_id']}/actual", json={"fuel_cost": fuel, "toll_cost": toll, "other_cost": other,
                                                             "deliveries_completed": done, "deliveries_failed": failed,
                                                             "distance_km": km, "notes": "Sample recorded outcome"})


    # Completed runs with recorded actuals
    p = multi("cp", ["Mandi House Books", "Bengali Market Sweets", "Barakhamba Corporate", "KG Marg Clinic"], "ace")
    complete(p, fuel=str(round(float(p["breakdown"]["fuel"]) * 1.08, 2)), other="40", done=4,
             km=round(p["distance_m"] / 1000 * 1.05, 2))
    p = single("cp", "Rajiv Chowk Electronics", "bike")
    complete(p, fuel=str(round(float(p["breakdown"]["fuel"]) * 0.95 + 0.5, 2)), km=round(p["distance_m"] / 1000, 2))

    # Dispatched (on the road)
    p = multi("lodhi", ["Khan Market Grocers", "Shahjahan Road Offices", "Supreme Court Canteen"], "ev")
    status(p, "saved")
    status(p, "dispatched")

    # Saved plans
    status(single("cp", "Janpath Textiles", "ace"), "saved")
    status(single("cp", "Ashoka Road Stationers", "ace", objective="time"), "saved")
    reroute_target = single("cp", "Gole Market Pharmacy", "truck", objective="distance")
    status(reroute_target, "saved")

    # A road closure on a saved route -> automatic, recorded reroute
    plan = call("GET", f"/routes/{reroute_target['plan_id']}")
    edge = plan["edges"][len(plan["edges"]) // 2]["edge_id"]
    net_id = health["active_network"]["id"]
    res = call("POST", f"/networks/{net_id}/closures", json={"edge_ids": [edge], "reason": "Metro construction (sample)",
                                                             "both_directions": True})
    log("Closure:", res["closure"]["road_name"], "->", [r["message"] for r in res["reroutes"]])

    # Unsaved comparison estimate (shows alternatives/benchmarks in History)
    single("lodhi", "Pandara Road Kitchens", "ev", objective="balanced")
    log("Done. Remaining pending orders are available for a live multi-stop demo.")

    # Fresh pending orders for a live multi-stop demo
    for i, (n, kg, prio) in enumerate([("Janpath Textiles", 160, "high"), ("Mandi House Books", 75, "normal"),
                                       ("Gole Market Pharmacy", 40, "urgent"), ("Barakhamba Corporate", 210, "normal"),
                                       ("Ashoka Road Stationers", 95, "low")], start=1):
        o = orders[n]
        call("POST", "/orders", json={"reference": f"ORD-25{i:02d}", "customer_id": o["customer_id"], "address_id": o["address_id"],
                                      "warehouse_id": wh["cp"]["id"], "weight_kg": kg, "quantity": max(1, kg // 30),
                                      "priority": prio, "notes": NOTE})
    log("Added pending orders for the live demo.")


def load_bundled_network() -> int | None:
    """Create the Central New Delhi network from the bundled graph if no network exists."""
    from app.database import SessionLocal
    from app.models import RoadNetwork
    from app.services.road_network import finalize_network

    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(RoadNetwork)):
            return None
        doc = json.loads(gzip.decompress(BUNDLED_NETWORK.read_bytes()))
        s, w, n, e = doc["bbox"]
        net = RoadNetwork(name="Central New Delhi", south=s, west=w, north=n, east=e,
                          source="openstreetmap-bundled", source_url="Bundled OSM import (Overpass API)", status="building")
        db.add(net)
        db.commit()
        finalize_network(db, net, doc)
        return net.id


def ensure_demo_data() -> None:
    """Idempotent: loads the bundled network and sample data into an empty database."""
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import app

    try:
        nid = load_bundled_network()
        if nid:
            log_.info("Loaded bundled road network %s", nid)
        token = get_settings().admin_token
        client = TestClient(app, headers={"X-Admin-Token": token} if token else {})

        def call(method, path, **kw):
            r = client.request(method, "/api/v1" + path, **kw)
            if r.status_code >= 400:
                raise RuntimeError(f"{method} {path} failed: {r.status_code} {r.text[:300]}")
            return r.json() if r.content else None

        health = call("GET", "/health")
        if health.get("active_network"):
            seed_sample_data(call, health, log=lambda *a: log_.info(" ".join(map(str, a))))
    except Exception:  # never take the API down because of demo data
        log_.exception("Demo data seeding failed")


def start_in_background() -> None:
    threading.Thread(target=ensure_demo_data, name="demo-seed", daemon=True).start()
