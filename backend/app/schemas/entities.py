from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


Lat = Field(ge=-90, le=90)
Lon = Field(ge=-180, le=180)


class Location(BaseModel):
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def both_or_neither(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError("Provide both lat and lon, or neither")
        return self


# ------------------------------------------------------------- warehouses

class WarehouseIn(Location):
    name: str = Field(min_length=1, max_length=120)
    address: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    active: bool = True
    geocode: bool = Field(default=True, description="Geocode the address when no coordinates are given")


class WarehouseOut(ORM):
    id: int
    name: str
    address: str | None
    lat: float | None
    lon: float | None
    geocode_status: str
    geocode_label: str | None
    notes: str | None
    active: bool
    created_at: datetime
    updated_at: datetime


# -------------------------------------------------------------- customers

class AddressIn(Location):
    label: str | None = Field(default=None, max_length=80)
    address_text: str = Field(min_length=3, max_length=500)


class AddressOut(ORM):
    id: int
    customer_id: int
    label: str | None
    address_text: str
    lat: float | None
    lon: float | None
    geocode_status: str
    geocode_label: str | None
    geocode_candidates: list[dict[str, Any]] | None
    geocoded_at: datetime | None


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    notes: str | None = None


class CustomerOut(ORM):
    id: int
    name: str
    email: str | None
    phone: str | None
    notes: str | None
    addresses: list[AddressOut] = []
    created_at: datetime


class ResolveAddressIn(BaseModel):
    candidate_index: int | None = Field(default=None, ge=0)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


# -------------------------------------------------------------- vehicles

VehicleCategory = Literal["two_wheeler", "car", "van", "light_truck", "heavy_truck"]
FuelType = Literal["petrol", "diesel", "cng", "electric"]


class VehicleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: VehicleCategory
    fuel_type: FuelType
    efficiency_km_per_unit: Decimal = Field(gt=0, le=1000)
    energy_price_override: Decimal | None = Field(default=None, ge=0)
    max_payload_kg: float = Field(gt=0, le=60000)
    gross_weight_t: float | None = Field(default=None, gt=0, le=60)
    height_m: float | None = Field(default=None, gt=0, le=6)
    width_m: float | None = Field(default=None, gt=0, le=4)
    max_speed_kph: float | None = Field(default=None, gt=0, le=200)
    operating_cost_per_km: Decimal = Field(default=Decimal("0"), ge=0)
    fixed_cost_per_trip: Decimal = Field(default=Decimal("0"), ge=0)
    emissions_kg_per_unit: Decimal | None = Field(default=None, ge=0)
    active: bool = True


class VehicleOut(ORM, VehicleIn):
    id: int
    created_at: datetime


# ---------------------------------------------------------------- orders

Priority = Literal["low", "normal", "high", "urgent"]
OrderStatus = Literal["pending", "planned", "dispatched", "delivered", "failed", "cancelled"]


class OrderIn(BaseModel):
    reference: str = Field(min_length=1, max_length=60)
    customer_id: int
    address_id: int
    warehouse_id: int | None = None
    weight_kg: float = Field(gt=0, le=60000)
    quantity: int = Field(default=1, ge=1, le=100000)
    length_cm: float | None = Field(default=None, gt=0)
    width_cm: float | None = Field(default=None, gt=0)
    height_cm: float | None = Field(default=None, gt=0)
    priority: Priority = "normal"
    status: OrderStatus = "pending"
    window_start: datetime | None = None
    window_end: datetime | None = None
    service_time_min: float = Field(default=5, ge=0, le=600)
    notes: str | None = None

    @model_validator(mode="after")
    def window_order(self):
        if self.window_start and self.window_end and self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        return self


class OrderOut(ORM):
    id: int
    reference: str
    customer_id: int
    address_id: int
    warehouse_id: int | None
    weight_kg: float
    quantity: int
    length_cm: float | None
    width_cm: float | None
    height_cm: float | None
    priority: str
    status: str
    window_start: datetime | None
    window_end: datetime | None
    service_time_min: float
    notes: str | None
    delivered_at: datetime | None
    created_at: datetime
    customer_name: str | None = None
    address_text: str | None = None
    geocode_status: str | None = None
    lat: float | None = None
    lon: float | None = None
    warehouse_name: str | None = None


class BulkStatusIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=1000)
    status: OrderStatus
