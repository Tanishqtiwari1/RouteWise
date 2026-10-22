from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import analytics

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
def summary(date_from: date | None = None, date_to: date | None = None, vehicle_id: int | None = None,
            warehouse_id: int | None = None, status: list[str] | None = Query(None), db: Session = Depends(get_db)):
    return analytics.summary(db, {"date_from": date_from, "date_to": date_to, "vehicle_id": vehicle_id,
                                  "warehouse_id": warehouse_id, "statuses": status})
