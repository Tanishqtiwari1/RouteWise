"""Export a read-only snapshot of a running RouteWise API for the static demo site.

    python scripts/export_demo_snapshot.py [API_BASE] [OUTPUT]

Everything in the snapshot is real API output: lists, plan details, analytics,
and two showcase calculations (single route with UCS trace + benchmarks, and a
multi-stop plan). The showcase calculations are created as unsaved estimates
and deleted again after export, so the source database is left unchanged.
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

API = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8010/api/v1").rstrip("/")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).resolve().parents[2] / "frontend/public/demo-snapshot.json")
c = httpx.Client(base_url=API, timeout=120)


def get(path, **params):
    r = c.get(path, params=params)
    r.raise_for_status()
    return r.json()


health = get("/health")
net_id = health["active_network"]["id"] if health.get("active_network") else None
routes = get("/routes", page_size=200)
snap: dict = {
    "exported_at": datetime.now(UTC).isoformat(),
    "get": {
        "/health": health,
        "/settings": get("/settings"),
        "/networks": get("/networks"),
        "/analytics/summary": get("/analytics/summary"),
        "/warehouses": get("/warehouses", page_size=200),
        "/vehicles": get("/vehicles", page_size=200),
        "/customers": get("/customers", page_size=200),
        "/orders": get("/orders", page_size=200),
        "/routes": routes,
    },
}
if net_id:
    snap["get"][f"/networks/{net_id}/closures"] = get(f"/networks/{net_id}/closures")
    snap["get"][f"/networks/{net_id}"] = get(f"/networks/{net_id}")
for p in routes["items"]:
    snap["get"][f"/routes/{p['id']}"] = get(f"/routes/{p['id']}")

# Showcase calculations (real UCS runs), deleted from the source DB afterwards.
whs = snap["get"]["/warehouses"]["items"]
vehicle_id = snap["get"]["/settings"]["default_vehicle_id"] or snap["get"]["/vehicles"]["items"][0]["id"]
orders = [o for o in snap["get"]["/orders"]["items"] if o["geocode_status"] in ("matched", "manual")]
pending = [o for o in orders if o["status"] == "pending"]
showcase = {}
if whs and orders:
    hub = next((w for w in whs if "Connaught" in w["name"]), whs[0])
    far = max(orders, key=lambda o: abs(o["lat"] - hub["lat"]) + abs(o["lon"] - hub["lon"]))
    r = c.post("/routes/calculate", json={"warehouse_id": hub["id"], "delivery_order_id": far["id"], "vehicle_id": vehicle_id,
                                         "objective": "money", "include_benchmarks": True, "include_alternatives": True,
                                         "trace": True, "trace_limit": 8000})
    r.raise_for_status()
    showcase["single"] = r.json()
    c.delete(f"/routes/{showcase['single']['plan_id']}")
    if len(pending) >= 2:
        r = c.post("/routes/multi-stop", json={"warehouse_id": hub["id"], "delivery_order_ids": [o["id"] for o in pending[:6]],
                                              "vehicle_id": vehicle_id, "algorithm": "astar", "allow_reload": True})
        r.raise_for_status()
        showcase["multi"] = r.json()
        c.delete(f"/routes/{showcase['multi']['plan_id']}")
snap["showcase"] = showcase

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(snap, separators=(",", ":")))
print(f"Wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB): {len(snap['get'])} GET responses, showcase={list(showcase)}")
