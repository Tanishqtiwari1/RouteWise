"""CSV import (delivery orders) and CSV exports."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Unprocessable
from app.models import Customer, DeliveryAddress, DeliveryOrder, RoutePlan, Warehouse

ORDER_COLUMNS = ["reference", "customer_name", "customer_email", "customer_phone", "address", "lat", "lon",
                 "weight_kg", "quantity", "priority", "warehouse", "window_start", "window_end",
                 "service_time_min", "notes"]
REQUIRED = {"reference", "customer_name", "address", "weight_kg"}
PRIORITIES = {"low", "normal", "high", "urgent"}


def _decode(raw: bytes) -> str:
    s = get_settings()
    if len(raw) > s.max_csv_bytes:
        raise Unprocessable(f"File is larger than {s.max_csv_bytes // 1000} KB.", code="file_too_large")
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise Unprocessable("File must be UTF-8 encoded CSV.", code="bad_encoding")


def _float(v: str, field: str, errors: list, row: int, *, minimum: float | None = None, maximum: float | None = None):
    try:
        f = float(v)
    except ValueError:
        errors.append({"row": row, "field": field, "message": f"'{v}' is not a number"})
        return None
    if minimum is not None and f < minimum or maximum is not None and f > maximum:
        errors.append({"row": row, "field": field, "message": f"{f} is out of range"})
        return None
    return f


def _dt(v: str, field: str, errors: list, row: int):
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        errors.append({"row": row, "field": field, "message": f"'{v}' is not an ISO-8601 date-time (e.g. 2026-05-01T14:00)"})
        return None


def import_orders(db: Session, raw: bytes, *, dry_run: bool = False) -> dict[str, Any]:
    text = _decode(raw)
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise Unprocessable("CSV has no header row.", code="no_header")
    headers = [h.strip().lower() for h in reader.fieldnames]
    missing = REQUIRED - set(headers)
    if missing:
        raise Unprocessable(f"Missing required columns: {', '.join(sorted(missing))}.", code="missing_columns",
                            details={"expected": ORDER_COLUMNS})
    unknown = [h for h in headers if h not in ORDER_COLUMNS]
    reader.fieldnames = headers

    warehouses = {w.name.lower(): w for w in db.scalars(select(Warehouse))}
    existing_refs = set(db.scalars(select(DeliveryOrder.reference)))
    seen_refs: set[str] = set()
    errors: list[dict[str, Any]] = []
    valid: list[dict[str, Any]] = []
    total = 0
    for i, rec in enumerate(reader, start=2):  # row 1 is the header
        total += 1
        if total > get_settings().max_csv_rows:
            raise Unprocessable(f"CSV has more than {get_settings().max_csv_rows} rows.", code="too_many_rows")
        r = {k: (v or "").strip() for k, v in rec.items() if k}
        row_errors: list[dict[str, Any]] = []
        for f in REQUIRED:
            if not r.get(f):
                row_errors.append({"row": i, "field": f, "message": "is required"})
        ref = r.get("reference", "")
        if ref and (ref in existing_refs or ref in seen_refs):
            row_errors.append({"row": i, "field": "reference", "message": f"duplicate reference '{ref}'"})
        weight = _float(r["weight_kg"], "weight_kg", row_errors, i, minimum=0.001) if r.get("weight_kg") else None
        qty = 1
        if r.get("quantity"):
            q = _float(r["quantity"], "quantity", row_errors, i, minimum=1)
            qty = int(q) if q is not None else 1
        lat = lon = None
        if r.get("lat") or r.get("lon"):
            if not (r.get("lat") and r.get("lon")):
                row_errors.append({"row": i, "field": "lat/lon", "message": "provide both lat and lon, or neither"})
            else:
                lat = _float(r["lat"], "lat", row_errors, i, minimum=-90, maximum=90)
                lon = _float(r["lon"], "lon", row_errors, i, minimum=-180, maximum=180)
        prio = (r.get("priority") or "normal").lower()
        if prio not in PRIORITIES:
            row_errors.append({"row": i, "field": "priority", "message": f"must be one of {sorted(PRIORITIES)}"})
        wh = None
        if r.get("warehouse"):
            wh = warehouses.get(r["warehouse"].lower())
            if wh is None:
                row_errors.append({"row": i, "field": "warehouse", "message": f"unknown warehouse '{r['warehouse']}'"})
        ws_ = _dt(r["window_start"], "window_start", row_errors, i) if r.get("window_start") else None
        we_ = _dt(r["window_end"], "window_end", row_errors, i) if r.get("window_end") else None
        if ws_ and we_ and we_ <= ws_:
            row_errors.append({"row": i, "field": "window_end", "message": "must be after window_start"})
        svc = _float(r["service_time_min"], "service_time_min", row_errors, i, minimum=0, maximum=600) if r.get("service_time_min") else 5.0
        if row_errors:
            errors.extend(row_errors)
            continue
        seen_refs.add(ref)
        valid.append({"ref": ref, "r": r, "weight": weight, "qty": qty, "lat": lat, "lon": lon, "prio": prio,
                      "wh": wh, "ws": ws_, "we": we_, "svc": svc})

    summary = {"total_rows": total, "valid_rows": len(valid), "invalid_rows": len({e["row"] for e in errors}),
               "errors": errors[:500], "unknown_columns": unknown, "dry_run": dry_run,
               "created_orders": 0, "created_customers": 0, "created_addresses": 0, "pending_geocode": 0}
    if dry_run:
        return summary

    customers: dict[tuple[str, str], Customer] = {
        (c.name.lower(), (c.email or "").lower()): c for c in db.scalars(select(Customer))
    }
    for v in valid:
        r = v["r"]
        key = (r["customer_name"].lower(), r.get("customer_email", "").lower())
        cust = customers.get(key)
        if cust is None:
            cust = Customer(name=r["customer_name"], email=r.get("customer_email") or None, phone=r.get("customer_phone") or None)
            db.add(cust)
            db.flush()
            customers[key] = cust
            summary["created_customers"] += 1
        addr = next((a for a in cust.addresses if a.address_text.lower() == r["address"].lower()), None)
        if addr is None:
            addr = DeliveryAddress(customer=cust, address_text=r["address"])
            if v["lat"] is not None:
                addr.lat, addr.lon, addr.geocode_status = v["lat"], v["lon"], "manual"
                addr.geocode_label = "Coordinates supplied in CSV import"
            else:
                summary["pending_geocode"] += 1
            db.add(addr)
            db.flush()
            summary["created_addresses"] += 1
        db.add(DeliveryOrder(reference=v["ref"], customer_id=cust.id, address_id=addr.id,
                             warehouse_id=v["wh"].id if v["wh"] else None, weight_kg=v["weight"], quantity=v["qty"],
                             priority=v["prio"], window_start=v["ws"], window_end=v["we"], service_time_min=v["svc"],
                             notes=r.get("notes") or None))
        summary["created_orders"] += 1
    db.commit()
    return summary


def _csv(rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerows(rows)
    return buf.getvalue()


def export_orders(db: Session) -> str:
    rows: list[list[Any]] = [ORDER_COLUMNS + ["status", "geocode_status"]]
    for o in db.scalars(select(DeliveryOrder).order_by(DeliveryOrder.id)):
        a = o.address
        rows.append([o.reference, o.customer.name, o.customer.email or "", o.customer.phone or "", a.address_text,
                     a.lat if a.lat is not None else "", a.lon if a.lon is not None else "", o.weight_kg, o.quantity,
                     o.priority, o.warehouse.name if o.warehouse else "",
                     o.window_start.isoformat() if o.window_start else "", o.window_end.isoformat() if o.window_end else "",
                     o.service_time_min, o.notes or "", o.status, a.geocode_status])
    return _csv(rows)


def export_plans(plans: list[RoutePlan]) -> str:
    rows: list[list[Any]] = [["id", "name", "kind", "status", "created_at", "objective", "algorithm", "vehicle",
                              "distance_km", "duration_min", "estimated_total_cost", "currency", "fuel", "driver",
                              "operating", "toll", "fixed", "baseline_cost", "estimated_savings", "actual_total_cost",
                              "network_id", "network_revision"]]
    for p in plans:
        b = p.breakdown
        rows.append([p.id, p.name, p.kind, p.status, p.created_at.isoformat(), p.objective, p.algorithm,
                     (p.vehicle_snapshot or {}).get("name", ""), round(p.distance_m / 1000, 3), round(p.duration_s / 60, 1),
                     p.total_cost, p.currency, b.get("fuel"), b.get("driver"), b.get("operating"), b.get("toll"),
                     b.get("fixed"), (p.baseline or {}).get("total_cost", ""),
                     p.estimated_savings if p.estimated_savings is not None else "",
                     p.actual.total_cost if p.actual else "", p.network_id, p.network_revision])
    return _csv(rows)


def export_plan_report(p: RoutePlan) -> str:
    rows: list[list[Any]] = [["RouteWise route report (ESTIMATE — not actual driven costs)"],
                             ["Plan", p.id, p.name], ["Status", p.status], ["Created", p.created_at.isoformat()],
                             ["Objective", p.objective, p.objective_formula], ["Algorithm", p.algorithm],
                             ["Vehicle", (p.vehicle_snapshot or {}).get("name", "")],
                             ["Network", p.network_id, f"revision {p.network_revision}"],
                             ["Distance (km)", round(p.distance_m / 1000, 3)], ["Duration (min)", round(p.duration_s / 60, 1)],
                             [], ["Cost component", f"Amount ({p.currency})"]]
    for k in ("fuel", "driver", "operating", "toll", "extra", "fixed", "total"):
        rows.append([k, p.breakdown.get(k)])
    rows += [[], ["Stops"], ["sequence", "kind", "label", "lat", "lon", "arrival_min", "leg_km", "leg_cost", "allocated_cost"]]
    for s in p.stops:
        rows.append([s.sequence, s.kind, s.label, s.lat, s.lon, round(s.arrival_s / 60, 1), round(s.leg_distance_m / 1000, 3),
                     s.leg_cost, s.allocated_cost if s.allocated_cost is not None else ""])
    rows += [[], ["Assumptions"]] + [[a] for a in p.assumptions] + [[], ["Warnings"]] + [[w] for w in p.warnings]
    rows += [[], ["Road segments"], ["sequence", "edge_id", "name", "highway", "length_m", "duration_s", "cost", "toll_status"]]
    for e in p.edges:
        rows.append([e.sequence, e.edge_id, e.name or "", e.highway or "", e.length_m, e.duration_s, e.cost, e.toll_status])
    rows += [[], ["Map data © OpenStreetMap contributors, ODbL"]]
    return _csv(rows)
