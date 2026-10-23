"""Populate a running RouteWise API with sample data for a demonstration.

    python scripts/seed_presentation.py [http://localhost:8010/api/v1]

Creates warehouses, vehicles, customers and orders at real Central Delhi
locations (inside the "Central New Delhi" road network), then plans routes
through the normal API (UCS on the real OSM graph) and moves some through the
saved -> dispatched -> completed lifecycle. Records marked "Sample data".
"""

import os
import sys
import time

import httpx

API = (sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "http://localhost:8010/api/v1").rstrip("/")
# Deployed APIs require the admin token for settings, network import and closures.
_token = os.environ.get("ROUTEWISE_ADMIN_TOKEN")
c = httpx.Client(base_url=API, timeout=180, headers={"X-Admin-Token": _token} if _token else {})
NOTE = "Sample data for demonstration"


def call(method, path, **kw):
    r = c.request(method, path, **kw)
    if r.status_code >= 400:
        raise SystemExit(f"{method} {path} failed: {r.status_code} {r.text[:300]}")
    return r.json() if r.content else None


health = call("GET", "/health")
if not health.get("active_network") and "--import-network" in sys.argv:
    # Same area as the local demo: Connaught Place – India Gate – Khan Market.
    net = call("POST", "/networks", json={"name": "Central New Delhi", "south": 28.595, "west": 77.195,
                                          "north": 28.645, "east": 77.245})
    print("Importing OpenStreetMap roads on the server…")
    for _ in range(90):
        time.sleep(5)
        net = call("GET", f"/networks/{net['id']}")
        if net["status"] in ("ready", "failed"):
            break
    if net["status"] != "ready":
        raise SystemExit(f"Network import did not finish: {net['status']} {net.get('error') or ''}")
    print("Network ready:", net["status_detail"])
    health = call("GET", "/health")
if not health.get("active_network"):
    raise SystemExit("No active road network. Import one on the Roads page first (or pass --import-network).")

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from app.demo_seed import seed_sample_data  # noqa: E402

seed_sample_data(call, health)
