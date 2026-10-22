from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ObjectiveName = Literal["money", "time", "distance", "balanced"]


class PointIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    label: str | None = Field(default=None, max_length=255)


class CostPreferences(BaseModel):
    include_fuel: bool | None = None
    include_driver: bool | None = None
    include_operating: bool | None = None
    include_tolls: bool | None = None
    driver_cost_per_hour: Decimal | None = Field(default=None, ge=0, le=100000)
    value_of_time_per_hour: Decimal | None = Field(default=None, ge=0, le=100000)


class RouteRequest(BaseModel):
    warehouse_id: int | None = None
    origin: PointIn | None = None
    delivery_order_id: int | None = None
    address_id: int | None = None
    destination: PointIn | None = None
    vehicle_id: int | None = None
    objective: ObjectiveName | None = None
    network_id: int | None = None
    preferences: CostPreferences = CostPreferences()
    include_alternatives: bool = True
    include_benchmarks: bool = False
    trace: bool = False
    trace_limit: int = Field(default=5000, ge=1, le=20000)
    name: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def endpoints(self):
        if not (self.warehouse_id or self.origin):
            raise ValueError("Provide warehouse_id or origin")
        if not (self.delivery_order_id or self.address_id or self.destination):
            raise ValueError("Provide delivery_order_id, address_id or destination")
        return self


class MultiStopRequest(BaseModel):
    warehouse_id: int
    delivery_order_ids: list[int] = Field(min_length=1, max_length=50)
    vehicle_id: int | None = None
    objective: ObjectiveName = "money"
    algorithm: Literal["ucs", "astar"] = "ucs"
    return_to_depot: bool = True
    allow_reload: bool = False
    respect_time_windows: bool = True
    departure_time: datetime | None = None
    network_id: int | None = None
    preferences: CostPreferences = CostPreferences()
    name: str | None = Field(default=None, max_length=160)


class RouteResult(BaseModel):
    """Route plan as returned by the API. Additional diagnostic fields are included."""

    model_config = ConfigDict(extra="allow")
    plan_id: int
    kind: Literal["single", "multi"]
    status: str
    objective: str
    objective_value: float
    objective_formula: str
    algorithm: str
    distance_m: float
    duration_s: float
    total_cost: str
    currency: str
    breakdown: dict[str, Any]
    geometry: list[list[float]]
    stops: list[dict[str, Any]]
    assumptions: list[str]
    warnings: list[str]
    search_stats: dict[str, Any]
    cost_is_estimate: bool = True


class PlanStatusIn(BaseModel):
    status: Literal["saved", "dispatched", "completed", "estimated"]
    name: str | None = Field(default=None, max_length=160)


class ActualIn(BaseModel):
    distance_km: float | None = Field(default=None, ge=0)
    duration_min: float | None = Field(default=None, ge=0)
    fuel_cost: Decimal | None = Field(default=None, ge=0)
    toll_cost: Decimal | None = Field(default=None, ge=0)
    other_cost: Decimal | None = Field(default=None, ge=0)
    total_cost: Decimal | None = Field(default=None, ge=0)
    deliveries_completed: int = Field(default=0, ge=0)
    deliveries_failed: int = Field(default=0, ge=0)
    completed_at: datetime | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def has_total(self):
        if self.total_cost is None and all(v is None for v in (self.fuel_cost, self.toll_cost, self.other_cost)):
            raise ValueError("Provide total_cost or at least one cost component")
        return self


class NetworkIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    south: float = Field(ge=-90, le=90)
    west: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)


class ClosureIn(BaseModel):
    edge_ids: list[str] | None = Field(default=None, max_length=200)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    both_directions: bool = True
    reason: str | None = Field(default=None, max_length=255)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    auto_reroute: bool = True

    @model_validator(mode="after")
    def target(self):
        if not self.edge_ids and (self.lat is None or self.lon is None):
            raise ValueError("Provide edge_ids or a lat/lon near the road to close")
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class OverrideIn(BaseModel):
    toll_cost: Decimal | None = Field(default=None, ge=0)
    extra_cost: Decimal | None = Field(default=None, ge=0)
    speed_kph: float | None = Field(default=None, gt=0, le=200)
    note: str | None = Field(default=None, max_length=255)
    both_directions: bool = True


class SettingsIn(BaseModel):
    workspace_name: str | None = Field(default=None, max_length=120)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    energy_prices: dict[Literal["petrol", "diesel", "cng", "electric"], Decimal] | None = None
    energy_prices_source: str | None = Field(default=None, max_length=255)
    driver_cost_per_hour: Decimal | None = Field(default=None, ge=0)
    include_fuel: bool | None = None
    include_driver: bool | None = None
    include_operating: bool | None = None
    include_tolls: bool | None = None
    toll_rate_per_km_estimate: Decimal | None = Field(default=None, ge=0)
    clear_toll_rate_estimate: bool = False
    value_of_time_per_hour: Decimal | None = Field(default=None, ge=0)
    speed_factor: Decimal | None = Field(default=None, gt=0, le=2)
    highway_speeds_kph: dict[str, float] | None = None
    default_vehicle_id: int | None = None
    default_objective: ObjectiveName | None = None
    tile_url: str | None = Field(default=None, max_length=255, pattern=r"^https://.*\{z\}.*\{x\}.*\{y\}.*")
    tile_attribution: str | None = Field(default=None, max_length=255)
    geocoder_url: str | None = Field(default=None, max_length=255, pattern=r"^https?://")
    overpass_url: str | None = Field(default=None, max_length=255, pattern=r"^https?://")
    network_stale_after_days: int | None = Field(default=None, ge=1, le=3650)

    @model_validator(mode="after")
    def speeds(self):
        for k, v in (self.highway_speeds_kph or {}).items():
            if not (0 < v <= 150):
                raise ValueError(f"Speed for {k} must be in (0, 150] km/h")
        return self
