from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import PageParams, apply_sort, paginate
from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.security import rate_limited
from app.database import get_db
from app.models import Customer, DeliveryAddress, DeliveryOrder, utcnow
from app.schemas.entities import AddressIn, AddressOut, CustomerIn, CustomerOut, Page, ResolveAddressIn
from app.services import geocoding

router = APIRouter(tags=["customers"])


@router.get("/customers", response_model=Page[CustomerOut])
def list_customers(q: str | None = None, sort: str | None = None, params: PageParams = Depends(),
                   db: Session = Depends(get_db)):
    stmt = select(Customer).options(selectinload(Customer.addresses))
    if q:
        stmt = stmt.where(or_(Customer.name.ilike(f"%{q}%"), Customer.email.ilike(f"%{q}%"), Customer.phone.ilike(f"%{q}%")))
    stmt = apply_sort(stmt, sort, {"name": Customer.name, "created_at": Customer.created_at}, Customer.name)
    items, total = paginate(db, stmt, params)
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(body: CustomerIn, db: Session = Depends(get_db)):
    c = Customer(**body.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _customer(db: Session, cid: int) -> Customer:
    c = db.get(Customer, cid)
    if not c:
        raise NotFound("Customer not found")
    return c


@router.get("/customers/{cid}", response_model=CustomerOut)
def get_customer(cid: int, db: Session = Depends(get_db)):
    return _customer(db, cid)


@router.put("/customers/{cid}", response_model=CustomerOut)
def update_customer(cid: int, body: CustomerIn, db: Session = Depends(get_db)):
    c = _customer(db, cid)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    db.commit()
    return c


@router.delete("/customers/{cid}", status_code=204)
def delete_customer(cid: int, db: Session = Depends(get_db)):
    c = _customer(db, cid)
    if db.scalar(select(DeliveryOrder.id).where(DeliveryOrder.customer_id == cid).limit(1)):
        raise Conflict("Customer has delivery orders; delete or reassign them first.")
    db.delete(c)
    db.commit()


@router.post("/customers/{cid}/addresses", response_model=AddressOut, status_code=201,
             dependencies=[Depends(rate_limited("geocode"))])
def add_address(cid: int, body: AddressIn, geocode: bool = True, db: Session = Depends(get_db)):
    c = _customer(db, cid)
    a = DeliveryAddress(customer=c, label=body.label, address_text=body.address_text)
    db.add(a)
    if body.lat is not None:
        a.lat, a.lon, a.geocode_status, a.geocode_label = body.lat, body.lon, "manual", "Coordinates entered manually"
        db.commit()
    else:
        db.commit()
        if geocode:
            geocoding.geocode_address(db, a)
    db.refresh(a)
    return a


def _address(db: Session, aid: int) -> DeliveryAddress:
    a = db.get(DeliveryAddress, aid)
    if not a:
        raise NotFound("Address not found")
    return a


@router.put("/addresses/{aid}", response_model=AddressOut)
def update_address(aid: int, body: AddressIn, geocode: bool = True, db: Session = Depends(get_db)):
    a = _address(db, aid)
    changed = a.address_text != body.address_text
    a.label, a.address_text = body.label, body.address_text
    if body.lat is not None:
        a.lat, a.lon, a.geocode_status, a.geocode_label = body.lat, body.lon, "manual", "Coordinates entered manually"
        db.commit()
    elif changed:
        a.lat = a.lon = None
        a.geocode_status = "pending"
        db.commit()
        if geocode:
            geocoding.geocode_address(db, a)
    else:
        db.commit()
    return a


@router.delete("/addresses/{aid}", status_code=204)
def delete_address(aid: int, db: Session = Depends(get_db)):
    a = _address(db, aid)
    if db.scalar(select(DeliveryOrder.id).where(DeliveryOrder.address_id == aid).limit(1)):
        raise Conflict("Address is used by delivery orders.")
    db.delete(a)
    db.commit()


@router.post("/addresses/{aid}/geocode", response_model=AddressOut, dependencies=[Depends(rate_limited("geocode"))])
def geocode_address(aid: int, db: Session = Depends(get_db)):
    return geocoding.geocode_address(db, _address(db, aid))


@router.post("/addresses/{aid}/resolve", response_model=AddressOut)
def resolve_address(aid: int, body: ResolveAddressIn, db: Session = Depends(get_db)):
    """Confirm an ambiguous match by choosing a candidate or entering coordinates."""
    a = _address(db, aid)
    if body.candidate_index is not None:
        cands = a.geocode_candidates or []
        if body.candidate_index >= len(cands):
            raise Unprocessable("Candidate index out of range")
        c = cands[body.candidate_index]
        a.lat, a.lon, a.geocode_label, a.geocode_status = c["lat"], c["lon"], c["label"], "matched"
    elif body.lat is not None and body.lon is not None:
        a.lat, a.lon, a.geocode_status, a.geocode_label = body.lat, body.lon, "manual", "Coordinates confirmed manually"
    else:
        raise Unprocessable("Provide candidate_index or lat/lon")
    a.geocoded_at = utcnow()
    db.commit()
    return a


@router.get("/addresses", response_model=Page[AddressOut])
def list_addresses(geocode_status: str | None = None, params: PageParams = Depends(), db: Session = Depends(get_db)):
    stmt = select(DeliveryAddress).order_by(DeliveryAddress.id)
    if geocode_status:
        stmt = stmt.where(DeliveryAddress.geocode_status == geocode_status)
    items, total = paginate(db, stmt, params)
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)
