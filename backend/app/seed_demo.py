"""Optional, explicitly labelled DEMONSTRATION data.

Creates a demo warehouse, vehicles, customers and orders in central New Delhi,
all prefixed "[DEMO]". It does not create road data: pass --import-network to
download the real OpenStreetMap road network for the demo area via Overpass.

    python -m app.seed_demo [--import-network]
"""

import argparse
from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Customer, DeliveryAddress, DeliveryOrder, RoadNetwork, Vehicle, Warehouse
from app.services.road_network import run_ingestion

DEMO_BBOX = (28.595, 77.195, 28.645, 77.245)  # Connaught Place – India Gate – Khan Market

# Coordinates of well-known public landmarks (from OpenStreetMap).
STOPS = [
    ("[DEMO] Khan Market Grocers", "Khan Market, New Delhi", 28.6003, 77.2270, 180),
    ("[DEMO] Mandi House Books", "Mandi House, New Delhi", 28.6258, 77.2341, 90),
    ("[DEMO] Gole Market Pharmacy", "Gole Market, New Delhi", 28.6370, 77.2050, 60),
    ("[DEMO] Janpath Textiles", "Janpath, New Delhi", 28.6235, 77.2185, 240),
    ("[DEMO] Lodhi Colony Cafe", "Lodhi Colony, New Delhi", 28.5920, 77.2200, 120),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-network", action="store_true", help="Download the demo area's OSM road network")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        if db.scalar(select(Warehouse).where(Warehouse.name == "[DEMO] Connaught Place Hub")):
            print("Demo data already present.")
        else:
            wh = Warehouse(name="[DEMO] Connaught Place Hub", address="Connaught Place, New Delhi", lat=28.6315, lon=77.2167,
                           geocode_status="manual", geocode_label="Demo coordinates")
            db.add(wh)
            db.add_all([
                Vehicle(name="[DEMO] Diesel van", category="van", fuel_type="diesel", efficiency_km_per_unit=Decimal("14"),
                        max_payload_kg=750, gross_weight_t=1.8, operating_cost_per_km=Decimal("2.5"),
                        fixed_cost_per_trip=Decimal("50"), emissions_kg_per_unit=Decimal("2.68")),
                Vehicle(name="[DEMO] Electric three-wheeler", category="two_wheeler", fuel_type="electric",
                        efficiency_km_per_unit=Decimal("12"), max_payload_kg=300, max_speed_kph=45,
                        operating_cost_per_km=Decimal("0.8")),
            ])
            db.flush()
            for i, (name, addr, lat, lon, kg) in enumerate(STOPS, start=1):
                c = Customer(name=name)
                a = DeliveryAddress(customer=c, address_text=addr, lat=lat, lon=lon, geocode_status="manual",
                                    geocode_label="Demo coordinates")
                db.add_all([c, a])
                db.flush()
                db.add(DeliveryOrder(reference=f"DEMO-{1000 + i}", customer_id=c.id, address_id=a.id, warehouse_id=wh.id,
                                     weight_kg=kg, notes="Demonstration order"))
            db.commit()
            print("Demo warehouse, vehicles, customers and orders created.")
        if args.import_network:
            net = db.scalar(select(RoadNetwork).where(RoadNetwork.name == "[DEMO] Central New Delhi"))
            if net is None:
                s, w, n, e = DEMO_BBOX
                net = RoadNetwork(name="[DEMO] Central New Delhi", south=s, west=w, north=n, east=e)
                db.add(net)
                db.commit()
            print("Downloading OpenStreetMap roads via Overpass (may take a minute)…")
            run_ingestion(net.id)
            db.refresh(net)
            print(f"Network status: {net.status} {net.status_detail or net.error or ''}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
