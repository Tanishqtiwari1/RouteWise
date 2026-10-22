from datetime import date, datetime, time

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.api.deps import PageParams, apply_sort, paginate
from app.core.errors import Conflict, NotFound, Unprocessable
from app.database import get_db
from app.models import Customer, DeliveryAddress, DeliveryOrder, RouteStop, Warehouse, utcnow
from app.schemas.entities import BulkStatusIn, OrderIn, OrderOut, Page
from app.services import csv_io

router = APIRouter(prefix="/orders", tags=["delivery orders"])


def to_out(o: DeliveryOrder) -> OrderOut:
    out = OrderOut.model_validate(o)
    out.customer_name = o.customer.name if o.customer else None
    if o.address:
        out.address_text, out.geocode_status, out.lat, out.lon = o.address.address_text, o.address.geocode_status, o.address.lat, o.address.lon
    out.warehouse_name = o.warehouse.name if o.warehouse else None
    return out


def _validate_refs(db: Session, body: OrderIn) -> None:
    if not db.get(Customer, body.customer_id):
        raise Unprocessable("Customer does not exist")
    addr = db.get(DeliveryAddress, body.address_id)
    if not addr or addr.customer_id != body.customer_id:
        raise Unprocessable("Address does not exist or belongs to another customer")
    if body.warehouse_id and not db.get(Warehouse, body.warehouse_id):
        raise Unprocessable("Warehouse does not exist")


@router.get("", response_model=Page[OrderOut])
def list_orders(
    q: str | None = None, status: list[str] | None = Query(None), priority: str | None = None,
    warehouse_id: int | None = None, customer_id: int | None = None, geocode_status: str | None = None,
    date_from: date | None = None, date_to: date | None = None, sort: str | None = None,
    params: PageParams = Depends(), db: Session = Depends(get_db),
):
    stmt = (select(DeliveryOrder).join(DeliveryOrder.customer).join(DeliveryOrder.address)
            .options(joinedload(DeliveryOrder.customer), joinedload(DeliveryOrder.address), joinedload(DeliveryOrder.warehouse)))
    if q:
        stmt = stmt.where(or_(DeliveryOrder.reference.ilike(f"%{q}%"), Customer.name.ilike(f"%{q}%"),
                              DeliveryAddress.address_text.ilike(f"%{q}%")))
    if status:
        stmt = stmt.where(DeliveryOrder.status.in_(status))
    if priority:
        stmt = stmt.where(DeliveryOrder.priority == priority)
    if warehouse_id:
        stmt = stmt.where(DeliveryOrder.warehouse_id == warehouse_id)
    if customer_id:
        stmt = stmt.where(DeliveryOrder.customer_id == customer_id)
    if geocode_status:
        stmt = stmt.where(DeliveryAddress.geocode_status == geocode_status)
    if date_from:
        stmt = stmt.where(DeliveryOrder.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        stmt = stmt.where(DeliveryOrder.created_at <= datetime.combine(date_to, time.max))
    stmt = apply_sort(stmt, sort, {"reference": DeliveryOrder.reference, "created_at": DeliveryOrder.created_at,
                                   "weight_kg": DeliveryOrder.weight_kg, "priority": DeliveryOrder.priority,
                                   "status": DeliveryOrder.status, "customer": Customer.name,
                                   "window_start": DeliveryOrder.window_start}, DeliveryOrder.created_at.desc())
    items, total = paginate(db, stmt, params)
    return Page(items=[to_out(o) for o in items], total=total, page=params.page, page_size=params.page_size)


@router.post("", response_model=OrderOut, status_code=201)
def create_order(body: OrderIn, db: Session = Depends(get_db)):
    _validate_refs(db, body)
    o = DeliveryOrder(**body.model_dump())
    db.add(o)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(f"Order reference '{body.reference}' already exists.") from exc
    db.refresh(o)
    return to_out(o)


def _order(db: Session, oid: int) -> DeliveryOrder:
    o = db.get(DeliveryOrder, oid)
    if not o:
        raise NotFound("Order not found")
    return o


@router.get("/export.csv", response_class=PlainTextResponse)
def export_orders(db: Session = Depends(get_db)):
    return PlainTextResponse(csv_io.export_orders(db), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=orders.csv"})


@router.get("/import/template.csv", response_class=PlainTextResponse)
def import_template():
    return PlainTextResponse(",".join(csv_io.ORDER_COLUMNS) + "\n", media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=orders_template.csv"})


@router.post("/import")
async def import_orders(file: UploadFile = File(...), dry_run: bool = False, db: Session = Depends(get_db)):
    if file.content_type not in ("text/csv", "application/vnd.ms-excel", "text/plain", "application/octet-stream"):
        raise Unprocessable(f"Unsupported content type {file.content_type}; upload a .csv file.")
    if file.filename and not file.filename.lower().endswith(".csv"):
        raise Unprocessable("File must have a .csv extension.")
    raw = await file.read()
    return csv_io.import_orders(db, raw, dry_run=dry_run)


@router.post("/bulk-status")
def bulk_status(body: BulkStatusIn, db: Session = Depends(get_db)):
    orders = list(db.scalars(select(DeliveryOrder).where(DeliveryOrder.id.in_(body.ids))))
    for o in orders:
        o.status = body.status
        if body.status == "delivered":
            o.delivered_at = utcnow()
    db.commit()
    return {"updated": len(orders)}


@router.get("/{oid}", response_model=OrderOut)
def get_order(oid: int, db: Session = Depends(get_db)):
    return to_out(_order(db, oid))


@router.put("/{oid}", response_model=OrderOut)
def update_order(oid: int, body: OrderIn, db: Session = Depends(get_db)):
    o = _order(db, oid)
    _validate_refs(db, body)
    for k, v in body.model_dump().items():
        setattr(o, k, v)
    if body.status == "delivered" and not o.delivered_at:
        o.delivered_at = utcnow()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(f"Order reference '{body.reference}' already exists.") from exc
    return to_out(o)


@router.delete("/{oid}", status_code=204)
def delete_order(oid: int, db: Session = Depends(get_db)):
    o = _order(db, oid)
    if db.scalar(select(RouteStop.id).where(RouteStop.delivery_order_id == oid).limit(1)) and o.status != "pending":
        raise Conflict("Order is part of a route plan; cancel it instead of deleting.")
    db.delete(o)
    db.commit()
