from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import rate_limited
from app.database import SessionLocal, get_db
from app.models import DeliveryAddress
from app.services import geocoding

router = APIRouter(prefix="/geocode", tags=["geocoding"])

_batch_state = {"running": False, "processed": 0, "total": 0, "last_error": None}


@router.get("/search", dependencies=[Depends(rate_limited("geocode"))])
def search(q: str = Query(min_length=3, max_length=300), limit: int = Query(5, ge=1, le=10),
           db: Session = Depends(get_db)):
    out = geocoding.search(db, q, limit=limit)
    return {"status": out.status, "message": out.message, "candidates": out.candidates,
            "attribution": "Geocoding © OpenStreetMap contributors (Nominatim)"}


def _geocode_pending(ids: list[int]) -> None:
    db = SessionLocal()
    try:
        for aid in ids:
            a = db.get(DeliveryAddress, aid)
            if a is None or a.geocode_status != "pending":
                _batch_state["processed"] += 1
                continue
            try:
                geocoding.geocode_address(db, a)
            except Exception as exc:  # e.g. provider rate limit — stop rather than hammer the service
                _batch_state["last_error"] = getattr(exc, "message", str(exc))
                break
            _batch_state["processed"] += 1
    finally:
        _batch_state["running"] = False
        db.close()


@router.post("/pending", status_code=202)
def geocode_pending(background: BackgroundTasks, max_items: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    """Geocode pending addresses in the background, throttled to the provider's policy (~1/s)."""
    if _batch_state["running"]:
        return {"started": False, **_batch_state}
    ids = list(db.scalars(select(DeliveryAddress.id).where(DeliveryAddress.geocode_status == "pending").limit(max_items)))
    _batch_state.update(running=bool(ids), processed=0, total=len(ids), last_error=None)
    if ids:
        background.add_task(_geocode_pending, ids)
    return {"started": bool(ids), **_batch_state}


@router.get("/pending/status")
def geocode_pending_status():
    return _batch_state
