from datetime import date, datetime, time
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.algorithms.cost_model import money
from app.api.deps import PageParams, apply_sort, paginate
from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.security import rate_limited
from app.database import get_db
from app.models import ActualDeliveryRecord, DeliveryOrder, RerouteEvent, RoutePlan, utcnow
from app.schemas.routing import ActualIn, MultiStopRequest, PlanStatusIn, RouteRequest, RouteResult
from app.services import csv_io, routing

router = APIRouter(prefix="/routes", tags=["routes"])

TRANSITIONS = {"estimated": {"saved"}, "saved": {"dispatched", "estimated"}, "dispatched": {"completed"},
               "completed": set(), "superseded": set()}


@router.post("/calculate", response_model=RouteResult, dependencies=[Depends(rate_limited("route"))])
def calculate(body: RouteRequest, db: Session = Depends(get_db)):
    """Least-cost route with Uniform Cost Search; persisted as an *estimated* plan."""
    return routing.calculate_route(db, body.model_dump(mode="json"))


@router.post("/multi-stop", response_model=RouteResult, dependencies=[Depends(rate_limited("route"))])
def multi_stop(body: MultiStopRequest, db: Session = Depends(get_db)):
    """Exact multi-delivery plan honouring capacity and (optionally) time windows."""
    return routing.plan_deliveries(db, body.model_dump(mode="json"))


@router.get("")
def history(
    q: str | None = None, status: list[str] | None = Query(None), kind: str | None = None,
    vehicle_id: int | None = None, warehouse_id: int | None = None,
    date_from: date | None = None, date_to: date | None = None, sort: str | None = None,
    params: PageParams = Depends(), db: Session = Depends(get_db),
):
    stmt = select(RoutePlan).options(selectinload(RoutePlan.stops), selectinload(RoutePlan.actual))
    if q:
        stmt = stmt.where(or_(RoutePlan.name.ilike(f"%{q}%")))
    if status:
        stmt = stmt.where(RoutePlan.status.in_(status))
    if kind:
        stmt = stmt.where(RoutePlan.kind == kind)
    if vehicle_id:
        stmt = stmt.where(RoutePlan.vehicle_id == vehicle_id)
    if warehouse_id:
        stmt = stmt.where(RoutePlan.warehouse_id == warehouse_id)
    if date_from:
        stmt = stmt.where(RoutePlan.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        stmt = stmt.where(RoutePlan.created_at <= datetime.combine(date_to, time.max))
    stmt = apply_sort(stmt, sort, {"created_at": RoutePlan.created_at, "total_cost": RoutePlan.total_cost,
                                   "distance_m": RoutePlan.distance_m, "name": RoutePlan.name},
                      RoutePlan.created_at.desc())
    items, total = paginate(db, stmt, params)
    slim = []
    for p in items:
        d = routing.plan_to_dict(p, include_edges=False)
        d.pop("geometry")
        d.pop("request")
        slim.append(d)
    return {"items": slim, "total": total, "page": params.page, "page_size": params.page_size}


@router.get("/export.csv", response_class=PlainTextResponse)
def export_history(status: list[str] | None = Query(None), db: Session = Depends(get_db)):
    stmt = select(RoutePlan).order_by(RoutePlan.created_at.desc())
    if status:
        stmt = stmt.where(RoutePlan.status.in_(status))
    return PlainTextResponse(csv_io.export_plans(list(db.scalars(stmt))), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=route_history.csv"})


@router.get("/compare")
def compare(ids: list[int] = Query(..., min_length=2, max_length=5), db: Session = Depends(get_db)):
    plans = [_plan(db, i) for i in ids]
    rows = []
    for p in plans:
        d = routing.plan_to_dict(p, include_edges=False)
        d.pop("request")
        rows.append(d)
    notes = []
    if len({(p.network_id, p.network_revision) for p in plans}) > 1:
        notes.append("Plans were calculated on different road-network revisions.")
    if len({str(sorted(p.cost_config.items())) for p in plans}) > 1:
        notes.append("Plans used different cost configurations; compare totals with care.")
    return {"plans": rows, "notes": notes}


def _plan(db: Session, pid: int) -> RoutePlan:
    p = db.get(RoutePlan, pid)
    if not p:
        raise NotFound("Route plan not found")
    return p


@router.get("/{pid}")
def get_plan(pid: int, db: Session = Depends(get_db)):
    p = _plan(db, pid)
    d = routing.plan_to_dict(p)
    d["reroutes"] = [routing.reroute_event_dict(e) for e in db.scalars(
        select(RerouteEvent).where(or_(RerouteEvent.original_plan_id == pid, RerouteEvent.new_plan_id == pid)))]
    return d


@router.patch("/{pid}/status")
def set_status(pid: int, body: PlanStatusIn, db: Session = Depends(get_db)):
    p = _plan(db, pid)
    if body.status != p.status and body.status not in TRANSITIONS.get(p.status, set()):
        raise Conflict(f"Cannot change status from {p.status} to {body.status}.")
    if body.status == "completed":
        raise Unprocessable("Record the actual delivery outcome to complete a plan.", code="actual_required")
    now = utcnow()
    p.status = body.status
    if body.name:
        p.name = body.name
    order_ids = [s.delivery_order_id for s in p.stops if s.delivery_order_id]
    orders = list(db.scalars(select(DeliveryOrder).where(DeliveryOrder.id.in_(order_ids)))) if order_ids else []
    if body.status == "saved":
        p.saved_at = p.saved_at or now
        for o in orders:
            if o.status == "pending":
                o.status = "planned"
    elif body.status == "dispatched":
        p.dispatched_at = now
        for o in orders:
            if o.status in ("pending", "planned"):
                o.status = "dispatched"
    elif body.status == "estimated":
        p.saved_at = None
        for o in orders:
            if o.status == "planned":
                o.status = "pending"
    db.commit()
    return routing.plan_to_dict(p, include_edges=False)


@router.post("/{pid}/actual")
def record_actual(pid: int, body: ActualIn, db: Session = Depends(get_db)):
    """Record what actually happened. Only these values are reported as actual costs."""
    p = _plan(db, pid)
    if p.status not in ("dispatched", "completed"):
        raise Conflict("Only dispatched plans can have actual delivery records.")
    total = body.total_cost
    if total is None:
        total = sum((v for v in (body.fuel_cost, body.toll_cost, body.other_cost) if v is not None), Decimal("0"))
    rec = p.actual or ActualDeliveryRecord(plan_id=p.id)
    for k, v in body.model_dump(exclude={"total_cost", "completed_at"}).items():
        setattr(rec, k, v)
    rec.total_cost = money(total)
    rec.completed_at = body.completed_at or utcnow()
    db.add(rec)
    p.status = "completed"
    p.completed_at = rec.completed_at
    if body.deliveries_failed == 0:
        order_ids = [s.delivery_order_id for s in p.stops if s.delivery_order_id]
        for o in db.scalars(select(DeliveryOrder).where(DeliveryOrder.id.in_(order_ids))):
            o.status, o.delivered_at = "delivered", rec.completed_at
    db.commit()
    db.refresh(p)
    return routing.plan_to_dict(p, include_edges=False)


@router.post("/{pid}/duplicate", dependencies=[Depends(rate_limited("route"))])
def duplicate(pid: int, db: Session = Depends(get_db)):
    """Re-run the same request on current data, producing a new estimated plan."""
    p = _plan(db, pid)
    req = dict(p.request)
    req["name"] = f"{p.name} (copy)"[:160]
    out = routing.calculate_route(db, req) if p.kind == "single" else routing.plan_deliveries(db, req)
    return out


@router.post("/{pid}/reroute", dependencies=[Depends(rate_limited("route"))])
def reroute(pid: int, db: Session = Depends(get_db)):
    p = _plan(db, pid)
    if p.status not in routing.ACTIVE_STATUSES:
        raise Conflict("Only saved or dispatched plans can be rerouted.")
    return routing.reroute_event_dict(routing.reroute_plan(db, p))


@router.get("/{pid}/export.csv", response_class=PlainTextResponse)
def export_plan(pid: int, db: Session = Depends(get_db)):
    p = _plan(db, pid)
    return PlainTextResponse(csv_io.export_plan_report(p), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=route_{p.id}.csv"})


@router.delete("/{pid}", status_code=204)
def delete_plan(pid: int, db: Session = Depends(get_db)):
    p = _plan(db, pid)
    if p.status not in ("estimated", "superseded"):
        raise Conflict("Only unsaved or superseded plans can be deleted; history of committed plans is retained.")
    db.delete(p)
    db.commit()
