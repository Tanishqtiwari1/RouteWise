"""Test configuration: isolated SQLite database and data directory per session.

The fixture road network below is a small *synthetic* grid in Overpass JSON
format. It is used only by tests (never shipped as operating data) and goes
through the same import code path as real OpenStreetMap data.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="routewise-test-"))
os.environ["ROUTEWISE_DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["ROUTEWISE_DATA_DIR"] = str(_TMP / "data")
os.environ["ROUTEWISE_RATE_LIMIT_PER_MINUTE"] = "10000"
os.environ.pop("ROUTEWISE_ADMIN_TOKEN", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]

# 5 x 5 grid, ~220 m spacing. Node id = 1000 + 10*row + col.
LAT0, LON0, STEP = 28.600, 77.200, 0.002


def node_id(r: int, c: int) -> int:
    return 1000 + 10 * r + c


def fixture_osm() -> dict:
    elements = []
    for r in range(5):
        for c in range(5):
            elements.append({"type": "node", "id": node_id(r, c), "lat": LAT0 + r * STEP, "lon": LON0 + c * STEP})
    way = 1
    for r in range(5):  # east-west streets
        tags = {"highway": "residential", "name": f"Row {r} Street"}
        if r == 2:
            tags = {"highway": "primary", "name": "Toll Expressway", "toll": "yes", "maxspeed": "60"}
        elements.append({"type": "way", "id": way, "nodes": [node_id(r, c) for c in range(5)], "tags": tags})
        way += 1
    for c in range(5):  # north-south streets
        tags = {"highway": "residential", "name": f"Col {c} Avenue"}
        if c == 4:
            tags["maxweight"] = "3.5"
        if c == 1:
            tags["oneway"] = "yes"
        elements.append({"type": "way", "id": way, "nodes": [node_id(r, c) for r in range(5)], "tags": tags})
        way += 1
    # Isolated stub not connected to the grid (should never be snapped to).
    elements += [{"type": "node", "id": 9001, "lat": 28.650, "lon": 77.250},
                 {"type": "node", "id": 9002, "lat": 28.651, "lon": 77.250},
                 {"type": "way", "id": 99, "nodes": [9001, 9002], "tags": {"highway": "service"}}]
    return {"version": 0.6, "osm3s": {"timestamp_osm_base": "2026-01-01T00:00:00Z"}, "elements": elements}


def run_migrations() -> None:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", os.environ["ROUTEWISE_DATABASE_URL"])
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def client():
    run_migrations()
    from app.main import app

    with TestClient(app) as c:
        yield c
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(scope="session")
def seeded(client):
    """Network + vehicles + warehouse + customers/addresses/orders with manual coordinates."""
    r = client.post("/api/v1/networks/upload", data={"name": "Fixture grid"},
                    files={"file": ("grid.json", json.dumps(fixture_osm()), "application/json")})
    assert r.status_code == 201, r.text
    net = r.json()
    van = client.post("/api/v1/vehicles", json={
        "name": "Test Van", "category": "van", "fuel_type": "diesel", "efficiency_km_per_unit": "10",
        "max_payload_kg": 500, "gross_weight_t": 2.5, "operating_cost_per_km": "2", "fixed_cost_per_trip": "0"}).json()
    truck = client.post("/api/v1/vehicles", json={
        "name": "Test Truck", "category": "heavy_truck", "fuel_type": "diesel", "efficiency_km_per_unit": "4",
        "max_payload_kg": 5000, "gross_weight_t": 12, "operating_cost_per_km": "6"}).json()
    wh = client.post("/api/v1/warehouses", json={"name": "Grid Depot", "lat": LAT0, "lon": LON0}).json()
    cust = client.post("/api/v1/customers", json={"name": "Grid Customer"}).json()
    addrs, orders = [], []
    for i, (r_, c_) in enumerate([(4, 4), (4, 0), (0, 4), (2, 2)]):
        a = client.post(f"/api/v1/customers/{cust['id']}/addresses",
                        json={"address_text": f"Corner {r_},{c_}", "lat": LAT0 + r_ * STEP, "lon": LON0 + c_ * STEP}).json()
        addrs.append(a)
        o = client.post("/api/v1/orders", json={"reference": f"T-{i}", "customer_id": cust["id"], "address_id": a["id"],
                                                 "warehouse_id": wh["id"], "weight_kg": 150}).json()
        orders.append(o)
    return {"network": net, "van": van, "truck": truck, "warehouse": wh, "customer": cust, "addresses": addrs, "orders": orders}
