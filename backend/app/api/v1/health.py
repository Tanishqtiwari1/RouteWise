from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import RoadNetwork

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    net = db.scalar(select(RoadNetwork).where(RoadNetwork.is_active.is_(True)))
    return {
        "status": "ok",
        "database": "ok",
        "active_network": None if net is None else {"id": net.id, "name": net.name, "status": net.status},
    }
