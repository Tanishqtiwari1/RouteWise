"""Workspace settings and construction of cost configurations.

All business assumptions are persisted in ``workspace_settings`` and editable
from the Settings page. The initial values below are *starting points* that are
disclosed in every route's assumptions until a user updates them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.algorithms.cost_model import CostConfig, Objective, VehicleRestrictions
from app.core.errors import Unprocessable
from app.models import Vehicle, WorkspaceSettings

# Modelled free-flow speeds by OSM highway class (km/h) used when a road has no
# usable maxspeed tag. A posted maxspeed caps the modelled speed but never raises it.
DEFAULT_HIGHWAY_SPEEDS: dict[str, float] = {
    "motorway": 80, "motorway_link": 50, "trunk": 60, "trunk_link": 40,
    "primary": 45, "primary_link": 35, "secondary": 40, "secondary_link": 30,
    "tertiary": 35, "tertiary_link": 25, "unclassified": 30, "residential": 25,
    "living_street": 10, "service": 15, "road": 25,
}

# Starting fuel/energy prices (INR). Users must review these; routes disclose
# whether they are still the unmodified initial values.
INITIAL_ENERGY_PRICES: dict[str, dict[str, str]] = {
    "petrol": {"price": "94.77", "unit": "litre"},
    "diesel": {"price": "87.67", "unit": "litre"},
    "cng": {"price": "76.09", "unit": "kg"},
    "electric": {"price": "8.00", "unit": "kWh"},
}
INITIAL_PRICE_SOURCE = "Initial values shipped with RouteWise (approximate Delhi retail, 2025). Review in Settings."

ENERGY_UNITS = {"petrol": "litre", "diesel": "litre", "cng": "kg", "electric": "kWh"}

HEAVY_CATEGORIES = {"light_truck", "heavy_truck"}


def get_settings_row(db: Session) -> WorkspaceSettings:
    row = db.get(WorkspaceSettings, 1)
    if row is None:
        row = WorkspaceSettings(
            id=1,
            energy_prices=INITIAL_ENERGY_PRICES,
            energy_prices_source=INITIAL_PRICE_SOURCE,
            driver_cost_per_hour=Decimal("150"),
            value_of_time_per_hour=Decimal("300"),
            speed_factor=Decimal("1"),
            highway_speeds_kph=DEFAULT_HIGHWAY_SPEEDS,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def energy_price_for(settings: WorkspaceSettings, vehicle: Vehicle) -> tuple[Decimal, str, str]:
    """Returns (price, unit, source description)."""
    unit = ENERGY_UNITS.get(vehicle.fuel_type, "unit")
    if vehicle.energy_price_override is not None:
        return Decimal(vehicle.energy_price_override), unit, f"vehicle-specific price for {vehicle.name}"
    entry = (settings.energy_prices or {}).get(vehicle.fuel_type)
    if not entry or entry.get("price") in (None, ""):
        raise Unprocessable(
            f"No {vehicle.fuel_type} price is configured. Set it in Settings or on the vehicle.",
            code="missing_energy_price")
    return Decimal(str(entry["price"])), entry.get("unit", unit), settings.energy_prices_source or "workspace settings"


def build_cost_config(settings: WorkspaceSettings, vehicle: Vehicle, overrides: dict[str, Any] | None = None) -> tuple[CostConfig, list[str]]:
    """Cost configuration for a vehicle plus human-readable assumptions."""
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    price, unit, source = energy_price_for(settings, vehicle)
    cfg = CostConfig(
        currency=settings.currency,
        energy_price_per_unit=price,
        energy_unit=unit,
        efficiency_km_per_unit=Decimal(vehicle.efficiency_km_per_unit),
        driver_cost_per_hour=Decimal(str(overrides.get("driver_cost_per_hour", settings.driver_cost_per_hour))),
        operating_cost_per_km=Decimal(vehicle.operating_cost_per_km or 0),
        fixed_cost_per_trip=Decimal(vehicle.fixed_cost_per_trip or 0),
        include_fuel=overrides.get("include_fuel", settings.include_fuel),
        include_driver=overrides.get("include_driver", settings.include_driver),
        include_operating=overrides.get("include_operating", settings.include_operating),
        include_tolls=overrides.get("include_tolls", settings.include_tolls),
        toll_rate_per_km_estimate=(Decimal(str(settings.toll_rate_per_km_estimate))
                                   if settings.toll_rate_per_km_estimate is not None else None),
        value_of_time_per_hour=Decimal(str(overrides.get("value_of_time_per_hour", settings.value_of_time_per_hour))),
        emissions_kg_per_unit=Decimal(vehicle.emissions_kg_per_unit) if vehicle.emissions_kg_per_unit is not None else None,
        speed_factor=Decimal(str(settings.speed_factor)),
        max_vehicle_speed_kph=Decimal(str(vehicle.max_speed_kph)) if vehicle.max_speed_kph else None,
    )
    cur = settings.currency
    a = [
        f"Energy price: {price} {cur}/{unit} ({source}).",
        f"Vehicle efficiency: {vehicle.efficiency_km_per_unit} km/{unit}; operating cost {vehicle.operating_cost_per_km} {cur}/km.",
    ]
    if cfg.include_driver:
        a.append(f"Driver cost: {cfg.driver_cost_per_hour} {cur}/hour of modelled driving time.")
    if cfg.fixed_cost_per_trip:
        a.append(f"Fixed cost per trip: {cfg.fixed_cost_per_trip} {cur} (does not affect route choice).")
    if cfg.toll_rate_per_km_estimate is not None:
        a.append(f"Tolled roads without a configured amount use an estimated {cfg.toll_rate_per_km_estimate} {cur}/km.")
    a.append("Durations are static estimates from road class and posted limits"
             f" (speed factor {cfg.speed_factor}); no live traffic data is used.")
    disabled = [k for k, on in (("fuel", cfg.include_fuel), ("driver", cfg.include_driver),
                                ("operating", cfg.include_operating), ("tolls", cfg.include_tolls)) if not on]
    if disabled:
        a.append("Excluded cost components: " + ", ".join(disabled) + ".")
    return cfg, a


def vehicle_restrictions(vehicle: Vehicle) -> VehicleRestrictions:
    return VehicleRestrictions(
        gross_weight_t=vehicle.gross_weight_t,
        height_m=vehicle.height_m,
        width_m=vehicle.width_m,
        is_heavy_goods=vehicle.category in HEAVY_CATEGORIES,
    )


def vehicle_snapshot(vehicle: Vehicle) -> dict[str, Any]:
    return {
        "id": vehicle.id, "name": vehicle.name, "category": vehicle.category, "fuel_type": vehicle.fuel_type,
        "efficiency_km_per_unit": str(vehicle.efficiency_km_per_unit), "max_payload_kg": vehicle.max_payload_kg,
        "operating_cost_per_km": str(vehicle.operating_cost_per_km), "fixed_cost_per_trip": str(vehicle.fixed_cost_per_trip),
        "gross_weight_t": vehicle.gross_weight_t, "height_m": vehicle.height_m, "width_m": vehicle.width_m,
        "emissions_kg_per_unit": None if vehicle.emissions_kg_per_unit is None else str(vehicle.emissions_kg_per_unit),
    }


def parse_objective(value: str) -> Objective:
    try:
        return Objective(value)
    except ValueError as exc:
        raise Unprocessable(f"Unknown objective {value!r}; use one of {[o.value for o in Objective]}") from exc
