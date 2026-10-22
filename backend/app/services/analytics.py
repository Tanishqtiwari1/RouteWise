"""Analytics computed from persisted records only.

Definitions
-----------
* *Committed plans*: route plans with status saved, dispatched or completed.
  Scratch calculations (status ``estimated``) and superseded plans are excluded.
* *Estimated cost*: cost model output stored on the plan at calculation time.
* *Actual cost*: values entered in an ActualDeliveryRecord. Never inferred.
* *Estimated savings*: per plan, baseline cost − plan cost, where the baseline is
  the shortest-distance route (single routes) or nearest-neighbour ordering
  (multi-stop) evaluated with the same network and cost configuration.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.algorithms.cost_model import money
from app.models import ActualDeliveryRecord, DeliveryOrder, RoutePlan, Vehicle

COMMITTED = ("saved", "dispatched", "completed")


def _filtered_plans(db: Session, f: dict[str, Any]) -> list[RoutePlan]:
    q = select(RoutePlan).options(selectinload(RoutePlan.stops), selectinload(RoutePlan.actual))
    statuses = f.get("statuses") or COMMITTED
    q = q.where(RoutePlan.status.in_(statuses))
    if f.get("date_from"):
        q = q.where(RoutePlan.created_at >= datetime.combine(f["date_from"], time.min))
    if f.get("date_to"):
        q = q.where(RoutePlan.created_at <= datetime.combine(f["date_to"], time.max))
    if f.get("vehicle_id"):
        q = q.where(RoutePlan.vehicle_id == f["vehicle_id"])
    if f.get("warehouse_id"):
        q = q.where(RoutePlan.warehouse_id == f["warehouse_id"])
    return list(db.scalars(q.order_by(RoutePlan.created_at)))


def _deliveries(p: RoutePlan) -> int:
    if p.kind == "single":
        return 1
    return sum(1 for s in p.stops if s.kind == "delivery")


def summary(db: Session, f: dict[str, Any]) -> dict[str, Any]:
    plans = _filtered_plans(db, f)
    currency = plans[0].currency if plans else "INR"
    total_est = sum((Decimal(p.total_cost) for p in plans), Decimal("0"))
    deliveries = sum(_deliveries(p) for p in plans)
    savings = sum((Decimal(p.estimated_savings) for p in plans if p.estimated_savings is not None), Decimal("0"))
    baseline_total = sum((Decimal(p.baseline["total_cost"]) for p in plans if p.estimated_savings is not None and p.baseline), Decimal("0"))
    actuals = [p.actual for p in plans if p.actual is not None]
    actual_total = sum((Decimal(a.total_cost) for a in actuals), Decimal("0"))
    est_for_actual = sum((Decimal(p.total_cost) for p in plans if p.actual is not None), Decimal("0"))

    by_day: dict[date, dict[str, Any]] = defaultdict(lambda: {"estimated": Decimal("0"), "actual": Decimal("0"), "plans": 0, "deliveries": 0})
    comp = {k: Decimal("0") for k in ("fuel", "driver", "operating", "toll", "extra", "fixed")}
    scatter = []
    locations: Counter[tuple[str, float, float]] = Counter()
    vehicle_use: dict[int | None, dict[str, Any]] = defaultdict(lambda: {"plans": 0, "distance_m": 0.0, "load_kg": 0.0, "capacity_kg": 0.0, "cost": Decimal("0")})
    for p in plans:
        d = p.created_at.date()
        by_day[d]["estimated"] += Decimal(p.total_cost)
        by_day[d]["plans"] += 1
        by_day[d]["deliveries"] += _deliveries(p)
        if p.actual is not None:
            by_day[d]["actual"] += Decimal(p.actual.total_cost)
        for k in comp:
            comp[k] += Decimal(str(p.breakdown.get(k, "0")))
        scatter.append({"plan_id": p.id, "distance_km": round(p.distance_m / 1000, 3), "cost": float(p.total_cost),
                        "kind": p.kind, "name": p.name})
        if p.kind == "single" and p.destination:
            locations[(p.destination["label"], round(p.destination["lat"], 4), round(p.destination["lon"], 4))] += 1
        for s in p.stops:
            if s.kind == "delivery":
                locations[(s.label, round(s.lat, 4), round(s.lon, 4))] += 1
        vu = vehicle_use[p.vehicle_id]
        vu["plans"] += 1
        vu["distance_m"] += p.distance_m
        vu["cost"] += Decimal(p.total_cost)
        if p.kind == "multi":
            vu["load_kg"] += float(p.breakdown.get("total_load_kg", 0))
            vu["capacity_kg"] += float(p.breakdown.get("capacity_kg", 0)) * int(p.breakdown.get("trips", 1))

    vehicles = {v.id: v.name for v in db.scalars(select(Vehicle))}
    order_counts = dict(db.execute(select(DeliveryOrder.status, func.count()).group_by(DeliveryOrder.status)).all())
    completed_actual = sum(a.deliveries_completed for a in actuals)
    failed_actual = sum(a.deliveries_failed for a in actuals)

    return {
        "currency": currency,
        "definitions": {
            "committed_plans": "Plans with status saved, dispatched or completed.",
            "estimated_cost": "Cost-model estimate stored at calculation time.",
            "actual_cost": "Entered from recorded deliveries only.",
            "savings": "Baseline cost minus plan cost; baseline = shortest-distance route (single) or "
                       "nearest-neighbour order (multi-stop), same network and cost settings.",
        },
        "totals": {
            "committed_plans": len(plans),
            "calculations": db.scalar(select(func.count()).select_from(RoutePlan)) or 0,
            "planned_deliveries": deliveries,
            "estimated_cost": str(money(total_est)),
            "avg_estimated_cost_per_delivery": str(money(total_est / deliveries)) if deliveries else None,
            "estimated_savings": str(money(savings)),
            "baseline_cost": str(money(baseline_total)),
            "savings_pct": round(float(savings / baseline_total) * 100, 2) if baseline_total else None,
            "actual_recorded_cost": str(money(actual_total)),
            "plans_with_actuals": len(actuals),
            "estimated_cost_of_plans_with_actuals": str(money(est_for_actual)),
            "distance_km": round(sum(p.distance_m for p in plans) / 1000, 2),
            "emissions_kg": round(sum(p.emissions_kg or 0 for p in plans), 2) if any(p.emissions_kg for p in plans) else None,
        },
        "trend": [{"date": d.isoformat(), "estimated": float(v["estimated"]), "actual": float(v["actual"]),
                   "plans": v["plans"], "deliveries": v["deliveries"],
                   "cost_per_delivery": float(v["estimated"] / v["deliveries"]) if v["deliveries"] else None}
                  for d, v in sorted(by_day.items())],
        "components": [{"component": k, "amount": float(money(v))} for k, v in comp.items() if v],
        "distance_vs_cost": scatter[-500:],
        "top_locations": [{"label": k[0], "lat": k[1], "lon": k[2], "count": c} for k, c in locations.most_common(8)],
        "vehicles": [{"vehicle_id": vid, "vehicle": vehicles.get(vid, "Deleted vehicle"), "plans": v["plans"],
                      "distance_km": round(v["distance_m"] / 1000, 2), "estimated_cost": float(money(v["cost"])),
                      "utilization": round(v["load_kg"] / v["capacity_kg"], 4) if v["capacity_kg"] else None}
                     for vid, v in vehicle_use.items()],
        "recent": [{"id": p.id, "name": p.name, "kind": p.kind, "status": p.status, "total_cost": str(p.total_cost),
                    "distance_m": p.distance_m, "created_at": p.created_at.isoformat()} for p in reversed(plans[-6:])],
        "orders_by_status": order_counts,
        "completion": {
            "recorded": len(actuals),
            "deliveries_completed": completed_actual,
            "deliveries_failed": failed_actual,
            "success_rate": round(completed_actual / (completed_actual + failed_actual), 4) if (completed_actual + failed_actual) else None,
        },
    }


def actual_records(db: Session) -> list[ActualDeliveryRecord]:
    return list(db.scalars(select(ActualDeliveryRecord)))
