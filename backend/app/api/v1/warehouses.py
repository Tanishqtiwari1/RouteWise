from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import PageParams, apply_sort, paginate
from app.core.errors import Conflict, NotFound
from app.database import get_db
from app.models import Warehouse, utcnow
from app.schemas.entities import Page, WarehouseIn, WarehouseOut
from app.services import geocoding

router = APIRouter(prefix="/warehouses", tags=["warehouses"])


def _apply(w: Warehouse, body: WarehouseIn, db: Session) -> None:
    w.name, w.address, w.notes, w.active = body.name, body.address, body.notes, body.active
    if body.lat is not None:
        w.lat, w.lon, w.geocode_status, w.geocode_label = body.lat, body.lon, "manual", "Coordinates entered manually"
    elif body.address and body.geocode:
        try:
            out = geocoding.search(db, body.address)
        except Exception as exc:  # recorded, not hidden
            w.lat = w.lon = None
            w.geocode_status, w.geocode_label = "failed", getattr(exc, "message", str(exc))
            return
        w.geocode_status = out.status
        if out.status == "matched":
            w.lat, w.lon, w.geocode_label = out.best["lat"], out.best["lon"], out.best["label"]
        else:
            w.lat = w.lon = None
            w.geocode_label = out.message
    elif w.lat is None:
        w.geocode_status = "pending"


@router.get("", response_model=Page[WarehouseOut])
def list_warehouses(q: str | None = None, active: bool | None = None, sort: str | None = None,
                    params: PageParams = Depends(), db: Session = Depends(get_db)):
    stmt = select(Warehouse)
    if q:
        stmt = stmt.where(or_(Warehouse.name.ilike(f"%{q}%"), Warehouse.address.ilike(f"%{q}%")))
    if active is not None:
        stmt = stmt.where(Warehouse.active.is_(active))
    stmt = apply_sort(stmt, sort, {"name": Warehouse.name, "created_at": Warehouse.created_at}, Warehouse.name)
    items, total = paginate(db, stmt, params)
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.post("", response_model=WarehouseOut, status_code=201)
def create_warehouse(body: WarehouseIn, db: Session = Depends(get_db)):
    w = Warehouse()
    _apply(w, body, db)
    db.add(w)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(f"A warehouse named '{body.name}' already exists.") from exc
    return w


@router.get("/{wid}", response_model=WarehouseOut)
def get_warehouse(wid: int, db: Session = Depends(get_db)):
    w = db.get(Warehouse, wid)
    if not w:
        raise NotFound("Warehouse not found")
    return w


@router.put("/{wid}", response_model=WarehouseOut)
def update_warehouse(wid: int, body: WarehouseIn, db: Session = Depends(get_db)):
    w = get_warehouse(wid, db)
    address_changed = body.address != w.address
    if body.lat is None and not address_changed:
        body.geocode = False
    _apply(w, body, db)
    w.updated_at = utcnow()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(f"A warehouse named '{body.name}' already exists.") from exc
    return w


@router.delete("/{wid}", status_code=204)
def delete_warehouse(wid: int, db: Session = Depends(get_db)):
    w = get_warehouse(wid, db)
    db.delete(w)
    db.commit()


@router.get("/{wid}/geocode-candidates")
def warehouse_candidates(wid: int, q: str | None = Query(None), db: Session = Depends(get_db)):
    w = get_warehouse(wid, db)
    out = geocoding.search(db, q or w.address or w.name)
    return {"status": out.status, "message": out.message, "candidates": out.candidates}
