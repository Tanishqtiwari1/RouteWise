from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import Unprocessable
from app.core.security import require_admin
from app.database import get_db
from app.models import Vehicle, utcnow
from app.schemas.routing import SettingsIn
from app.services.road_network import invalidate_cache
from app.services.settings_service import DEFAULT_HIGHWAY_SPEEDS, ENERGY_UNITS, get_settings_row

router = APIRouter(prefix="/settings", tags=["settings"])


def settings_dict(s) -> dict:
    return {
        "workspace_name": s.workspace_name, "currency": s.currency, "energy_prices": s.energy_prices,
        "energy_units": ENERGY_UNITS,
        "energy_prices_updated_at": s.energy_prices_updated_at.isoformat() if s.energy_prices_updated_at else None,
        "energy_prices_source": s.energy_prices_source, "driver_cost_per_hour": str(s.driver_cost_per_hour),
        "include_fuel": s.include_fuel, "include_driver": s.include_driver, "include_operating": s.include_operating,
        "include_tolls": s.include_tolls,
        "toll_rate_per_km_estimate": None if s.toll_rate_per_km_estimate is None else str(s.toll_rate_per_km_estimate),
        "value_of_time_per_hour": str(s.value_of_time_per_hour), "speed_factor": str(s.speed_factor),
        "highway_speeds_kph": {**DEFAULT_HIGHWAY_SPEEDS, **(s.highway_speeds_kph or {})},
        "default_vehicle_id": s.default_vehicle_id, "default_objective": s.default_objective,
        "savings_baseline": s.savings_baseline, "tile_url": s.tile_url, "tile_attribution": s.tile_attribution,
        "geocoder_url": s.geocoder_url, "overpass_url": s.overpass_url,
        "network_stale_after_days": s.network_stale_after_days, "revision": s.revision,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    return settings_dict(get_settings_row(db))


@router.put("", dependencies=[Depends(require_admin)])
def update_settings(body: SettingsIn, db: Session = Depends(get_db)):
    s = get_settings_row(db)
    data = body.model_dump(exclude_unset=True)
    if "default_vehicle_id" in data and data["default_vehicle_id"] is not None and not db.get(Vehicle, data["default_vehicle_id"]):
        raise Unprocessable("Default vehicle does not exist")
    if "energy_prices" in data and data["energy_prices"] is not None:
        prices = dict(s.energy_prices or {})
        for fuel, price in data.pop("energy_prices").items():
            prices[fuel] = {"price": str(price), "unit": ENERGY_UNITS[fuel]}
        s.energy_prices = prices
        s.energy_prices_updated_at = utcnow()
        if "energy_prices_source" not in data:
            s.energy_prices_source = "Updated by a user in Settings"
    if data.pop("clear_toll_rate_estimate", False):
        s.toll_rate_per_km_estimate = None
    if "highway_speeds_kph" in data and data["highway_speeds_kph"] is not None:
        s.highway_speeds_kph = {**(s.highway_speeds_kph or {}), **data.pop("highway_speeds_kph")}
    for k, v in data.items():
        if v is not None or k in ("default_vehicle_id",):
            setattr(s, k, v)
    s.revision += 1
    db.commit()
    invalidate_cache()
    return settings_dict(s)
