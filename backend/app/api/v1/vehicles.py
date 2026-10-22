from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import PageParams, apply_sort, paginate
from app.core.errors import Conflict, NotFound
from app.database import get_db
from app.models import Vehicle
from app.schemas.entities import Page, VehicleIn, VehicleOut

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.get("", response_model=Page[VehicleOut])
def list_vehicles(q: str | None = None, active: bool | None = None, sort: str | None = None,
                  params: PageParams = Depends(), db: Session = Depends(get_db)):
    stmt = select(Vehicle)
    if q:
        stmt = stmt.where(or_(Vehicle.name.ilike(f"%{q}%"), Vehicle.category.ilike(f"%{q}%")))
    if active is not None:
        stmt = stmt.where(Vehicle.active.is_(active))
    stmt = apply_sort(stmt, sort, {"name": Vehicle.name, "max_payload_kg": Vehicle.max_payload_kg,
                                   "created_at": Vehicle.created_at}, Vehicle.name)
    items, total = paginate(db, stmt, params)
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.post("", response_model=VehicleOut, status_code=201)
def create_vehicle(body: VehicleIn, db: Session = Depends(get_db)):
    v = Vehicle(**body.model_dump())
    db.add(v)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(f"A vehicle named '{body.name}' already exists.") from exc
    return v


def _vehicle(db: Session, vid: int) -> Vehicle:
    v = db.get(Vehicle, vid)
    if not v:
        raise NotFound("Vehicle not found")
    return v


@router.get("/{vid}", response_model=VehicleOut)
def get_vehicle(vid: int, db: Session = Depends(get_db)):
    return _vehicle(db, vid)


@router.put("/{vid}", response_model=VehicleOut)
def update_vehicle(vid: int, body: VehicleIn, db: Session = Depends(get_db)):
    v = _vehicle(db, vid)
    for k, val in body.model_dump().items():
        setattr(v, k, val)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(f"A vehicle named '{body.name}' already exists.") from exc
    return v


@router.delete("/{vid}", status_code=204)
def delete_vehicle(vid: int, db: Session = Depends(get_db)):
    db.delete(_vehicle(db, vid))
    db.commit()
