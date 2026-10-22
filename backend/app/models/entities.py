"""ORM entities.

Intentional denormalisation: route plans store a *snapshot* of the cost
configuration, vehicle parameters, geometry and per-edge costs used at
calculation time, so historical reports never change when the road network,
vehicle or settings are later edited.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.database.session import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


Money = Numeric(14, 2)


class UTCDateTime(TypeDecorator):
    """Stores UTC; always returns timezone-aware datetimes (SQLite drops tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC) if value is not None else None

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class WorkspaceSettings(TimestampMixin, Base):
    """Single-row table of editable business assumptions."""

    __tablename__ = "workspace_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_name: Mapped[str] = mapped_column(String(120), default="My Workspace")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    # {"petrol": {"price": "94.77", "unit": "litre"}, ...}
    energy_prices: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    energy_prices_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    energy_prices_source: Mapped[str | None] = mapped_column(String(255))
    driver_cost_per_hour: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    include_fuel: Mapped[bool] = mapped_column(Boolean, default=True)
    include_driver: Mapped[bool] = mapped_column(Boolean, default=True)
    include_operating: Mapped[bool] = mapped_column(Boolean, default=True)
    include_tolls: Mapped[bool] = mapped_column(Boolean, default=True)
    toll_rate_per_km_estimate: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    value_of_time_per_hour: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    speed_factor: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("1"))
    highway_speeds_kph: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    default_vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"))
    default_objective: Mapped[str] = mapped_column(String(20), default="money")
    savings_baseline: Mapped[str] = mapped_column(String(30), default="shortest_distance")
    tile_url: Mapped[str] = mapped_column(String(255), default="https://tile.openstreetmap.org/{z}/{x}/{y}.png")
    tile_attribution: Mapped[str] = mapped_column(String(255), default="&copy; OpenStreetMap contributors")
    geocoder_url: Mapped[str] = mapped_column(String(255), default="https://nominatim.openstreetmap.org")
    overpass_url: Mapped[str] = mapped_column(String(255), default="https://overpass-api.de/api/interpreter")
    network_stale_after_days: Mapped[int] = mapped_column(Integer, default=30)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Warehouse(TimestampMixin, Base):
    __tablename__ = "warehouses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    address: Mapped[str | None] = mapped_column(String(500))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    geocode_status: Mapped[str] = mapped_column(String(20), default="pending")
    geocode_label: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)
    addresses: Mapped[list[DeliveryAddress]] = relationship(back_populates="customer", cascade="all, delete-orphan")


class DeliveryAddress(TimestampMixin, Base):
    __tablename__ = "delivery_addresses"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    label: Mapped[str | None] = mapped_column(String(80))
    address_text: Mapped[str] = mapped_column(String(500))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    # pending | matched | ambiguous | failed | manual
    geocode_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    geocode_label: Mapped[str | None] = mapped_column(String(500))
    geocode_candidates: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    geocoded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    customer: Mapped[Customer] = relationship(back_populates="addresses")


class Vehicle(TimestampMixin, Base):
    __tablename__ = "vehicles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    category: Mapped[str] = mapped_column(String(30))  # two_wheeler | car | van | light_truck | heavy_truck
    fuel_type: Mapped[str] = mapped_column(String(20))  # petrol | diesel | cng | electric
    efficiency_km_per_unit: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    energy_price_override: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    max_payload_kg: Mapped[float] = mapped_column(Float)
    gross_weight_t: Mapped[float | None] = mapped_column(Float)
    height_m: Mapped[float | None] = mapped_column(Float)
    width_m: Mapped[float | None] = mapped_column(Float)
    max_speed_kph: Mapped[float | None] = mapped_column(Float)
    operating_cost_per_km: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("0"))
    fixed_cost_per_trip: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    emissions_kg_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class DeliveryOrder(TimestampMixin, Base):
    __tablename__ = "delivery_orders"
    __table_args__ = (Index("ix_orders_status_priority", "status", "priority"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(60), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), index=True)
    address_id: Mapped[int] = mapped_column(ForeignKey("delivery_addresses.id", ondelete="RESTRICT"))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id", ondelete="SET NULL"), index=True)
    weight_kg: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    length_cm: Mapped[float | None] = mapped_column(Float)
    width_cm: Mapped[float | None] = mapped_column(Float)
    height_cm: Mapped[float | None] = mapped_column(Float)
    priority: Mapped[str] = mapped_column(String(10), default="normal")  # low | normal | high | urgent
    status: Mapped[str] = mapped_column(String(15), default="pending")  # pending|planned|dispatched|delivered|failed|cancelled
    window_start: Mapped[datetime | None] = mapped_column(UTCDateTime)
    window_end: Mapped[datetime | None] = mapped_column(UTCDateTime)
    service_time_min: Mapped[float] = mapped_column(Float, default=5.0)
    notes: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    customer: Mapped[Customer] = relationship()
    address: Mapped[DeliveryAddress] = relationship()
    warehouse: Mapped[Warehouse | None] = relationship()


class RoadNetwork(TimestampMixin, Base):
    """Metadata only; the graph itself lives in a versioned file (see services.road_network)."""

    __tablename__ = "road_networks"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    south: Mapped[float] = mapped_column(Float)
    west: Mapped[float] = mapped_column(Float)
    north: Mapped[float] = mapped_column(Float)
    east: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(40), default="openstreetmap-overpass")
    source_url: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|downloading|building|ready|failed
    status_detail: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    node_count: Mapped[int] = mapped_column(Integer, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, default=0)
    osm_timestamp: Mapped[str | None] = mapped_column(String(40))
    imported_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    file_path: Mapped[str | None] = mapped_column(String(500))
    revision: Mapped[int] = mapped_column(Integer, default=1)  # bumps on closures / overrides
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    attribution: Mapped[str] = mapped_column(String(255), default="© OpenStreetMap contributors, ODbL")


class RoadNetworkGraph(Base):
    """Compressed graph document (gzip JSON). The database is the source of truth so
    graphs survive redeploys on hosts without persistent disks; files are a cache."""

    __tablename__ = "road_network_graphs"
    network_id: Mapped[int] = mapped_column(ForeignKey("road_networks.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SegmentOverride(TimestampMixin, Base):
    __tablename__ = "segment_overrides"
    __table_args__ = (UniqueConstraint("network_id", "edge_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    network_id: Mapped[int] = mapped_column(ForeignKey("road_networks.id", ondelete="CASCADE"), index=True)
    edge_id: Mapped[str] = mapped_column(String(80))
    toll_cost: Mapped[Decimal | None] = mapped_column(Money)
    extra_cost: Mapped[Decimal | None] = mapped_column(Money)
    speed_kph: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(String(255))


class RoadClosure(TimestampMixin, Base):
    __tablename__ = "road_closures"
    id: Mapped[int] = mapped_column(primary_key=True)
    network_id: Mapped[int] = mapped_column(ForeignKey("road_networks.id", ondelete="CASCADE"), index=True)
    edge_ids: Mapped[list[str]] = mapped_column(JSON)
    road_name: Mapped[str | None] = mapped_column(String(255))
    reason: Mapped[str | None] = mapped_column(String(255))
    starts_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    reopened_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    geometry: Mapped[list[list[float]] | None] = mapped_column(JSON)


class RoadClosureEvent(Base):
    __tablename__ = "road_closure_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    closure_id: Mapped[int] = mapped_column(ForeignKey("road_closures.id", ondelete="CASCADE"), index=True)
    event: Mapped[str] = mapped_column(String(20))  # closed | reopened
    network_revision: Mapped[int] = mapped_column(Integer)
    affected_plan_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RoutePlan(TimestampMixin, Base):
    __tablename__ = "route_plans"
    __table_args__ = (Index("ix_route_plans_created", "created_at"), Index("ix_route_plans_status", "status"))
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(10))  # single | multi
    # estimated -> saved -> dispatched -> completed ; superseded when rerouted
    status: Mapped[str] = mapped_column(String(15), default="estimated")
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id", ondelete="SET NULL"), index=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"), index=True)
    network_id: Mapped[int | None] = mapped_column(ForeignKey("road_networks.id", ondelete="SET NULL"))
    network_revision: Mapped[int] = mapped_column(Integer)
    parent_plan_id: Mapped[int | None] = mapped_column(ForeignKey("route_plans.id", ondelete="SET NULL"))
    algorithm: Mapped[str] = mapped_column(String(30))
    objective: Mapped[str] = mapped_column(String(20))
    objective_value: Mapped[float] = mapped_column(Float)
    objective_formula: Mapped[str] = mapped_column(Text)
    origin: Mapped[dict[str, Any]] = mapped_column(JSON)  # {label, lat, lon, node}
    destination: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    return_to_depot: Mapped[bool] = mapped_column(Boolean, default=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSON)  # original request (for duplicate / reroute)
    cost_config: Mapped[dict[str, Any]] = mapped_column(JSON)  # snapshot
    vehicle_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    distance_m: Mapped[float] = mapped_column(Float)
    duration_s: Mapped[float] = mapped_column(Float)
    total_cost: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSON)
    emissions_kg: Mapped[float | None] = mapped_column(Float)
    baseline: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # {method, total_cost, distance_m}
    estimated_savings: Mapped[Decimal | None] = mapped_column(Money)
    geometry: Mapped[list[list[float]]] = mapped_column(JSON)  # [[lat, lon], ...]
    node_path: Mapped[list[Any]] = mapped_column(JSON)
    search_stats: Mapped[dict[str, Any]] = mapped_column(JSON)
    assumptions: Mapped[list[str]] = mapped_column(JSON, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    saved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    dispatched_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    stops: Mapped[list[RouteStop]] = relationship(back_populates="plan", cascade="all, delete-orphan", order_by="RouteStop.sequence")
    edges: Mapped[list[RouteEdge]] = relationship(back_populates="plan", cascade="all, delete-orphan", order_by="RouteEdge.sequence")
    actual: Mapped[ActualDeliveryRecord | None] = relationship(back_populates="plan", cascade="all, delete-orphan", uselist=False)


class RouteStop(Base):
    __tablename__ = "route_stops"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("route_plans.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(12))  # origin | delivery | reload | return | destination
    delivery_order_id: Mapped[int | None] = mapped_column(ForeignKey("delivery_orders.id", ondelete="SET NULL"))
    label: Mapped[str] = mapped_column(String(255))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    node_id: Mapped[str] = mapped_column(String(40))
    arrival_s: Mapped[float] = mapped_column(Float, default=0)
    wait_s: Mapped[float] = mapped_column(Float, default=0)
    leg_distance_m: Mapped[float] = mapped_column(Float, default=0)
    leg_cost: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    allocated_cost: Mapped[Decimal | None] = mapped_column(Money)
    load_kg: Mapped[float | None] = mapped_column(Float)
    plan: Mapped[RoutePlan] = relationship(back_populates="stops")


class RouteEdge(Base):
    __tablename__ = "route_edges"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("route_plans.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    edge_id: Mapped[str] = mapped_column(String(80), index=True)
    way_id: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String(255))
    highway: Mapped[str | None] = mapped_column(String(40))
    length_m: Mapped[float] = mapped_column(Float)
    duration_s: Mapped[float] = mapped_column(Float)
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    toll_status: Mapped[str] = mapped_column(String(20))
    plan: Mapped[RoutePlan] = relationship(back_populates="edges")


class ActualDeliveryRecord(TimestampMixin, Base):
    """Recorded (not estimated) outcome of a dispatched plan."""

    __tablename__ = "actual_delivery_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("route_plans.id", ondelete="CASCADE"), unique=True)
    distance_km: Mapped[float | None] = mapped_column(Float)
    duration_min: Mapped[float | None] = mapped_column(Float)
    fuel_cost: Mapped[Decimal | None] = mapped_column(Money)
    toll_cost: Mapped[Decimal | None] = mapped_column(Money)
    other_cost: Mapped[Decimal | None] = mapped_column(Money)
    total_cost: Mapped[Decimal] = mapped_column(Money)
    deliveries_completed: Mapped[int] = mapped_column(Integer, default=0)
    deliveries_failed: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    notes: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[RoutePlan] = relationship(back_populates="actual")


class RerouteEvent(Base):
    __tablename__ = "reroute_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    original_plan_id: Mapped[int] = mapped_column(ForeignKey("route_plans.id", ondelete="CASCADE"), index=True)
    new_plan_id: Mapped[int | None] = mapped_column(ForeignKey("route_plans.id", ondelete="SET NULL"))
    closure_id: Mapped[int | None] = mapped_column(ForeignKey("road_closures.id", ondelete="SET NULL"))
    outcome: Mapped[str] = mapped_column(String(20))  # rerouted | no_alternative | unaffected
    affected_edge_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    delta_distance_m: Mapped[float | None] = mapped_column(Float)
    delta_duration_s: Mapped[float | None] = mapped_column(Float)
    delta_cost: Mapped[Decimal | None] = mapped_column(Money)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class GeocodeCache(Base):
    __tablename__ = "geocode_cache"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(40))
    query: Mapped[str] = mapped_column(String(500), index=True)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
