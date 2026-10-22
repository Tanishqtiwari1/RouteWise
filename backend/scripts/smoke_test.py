"""Post-deployment smoke test against a running API over HTTP.

    python scripts/smoke_test.py https://api.example.com/api/v1

Read-only: checks health, settings, OpenAPI and (if a network is active) a
route calculation between the first warehouse and the first resolved order.
"""

import sys

import httpx

base = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8010/api/v1").rstrip("/")
c = httpx.Client(timeout=60)


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")
    if not ok:
        sys.exit(1)


h = c.get(f"{base}/health").json()
check("health", h.get("status") == "ok", str(h.get("active_network")))
check("settings", c.get(f"{base}/settings").status_code == 200)
check("openapi", c.get(f"{base}/openapi.json").status_code == 200)
whs = c.get(f"{base}/warehouses").json()["items"]
orders = [o for o in c.get(f"{base}/orders", params={"page_size": 50}).json()["items"] if o["geocode_status"] in ("matched", "manual")]
vehicles = c.get(f"{base}/vehicles").json()["items"]
if h.get("active_network") and whs and orders and vehicles:
    r = c.post(f"{base}/routes/calculate", json={"warehouse_id": whs[0]["id"], "delivery_order_id": orders[0]["id"],
                                                 "vehicle_id": vehicles[0]["id"], "include_alternatives": False})
    body = r.json()
    check("route", r.status_code == 200, f"{body.get('distance_m')} m, {body.get('total_cost')} {body.get('currency')}"
          if r.status_code == 200 else str(body))
    # Note: this creates an 'estimated' plan record (deletable from Route History).
else:
    print("[SKIP] route calculation (needs an active network, a warehouse, a resolved order and a vehicle)")
