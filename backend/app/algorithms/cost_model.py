"""Monetary and objective cost model for road segments.

Kept separate from the search engine: UCS only ever sees a ``cost_fn(edge)``
returning a non-negative float. This module builds those functions and computes
the decimal-exact cost breakdown of a finished route.

Per-segment formulas (only components enabled in :class:`CostConfig` apply)::

    distance_km   = length_m / 1000
    duration_h    = distance_km / effective_speed_kph
    fuel_cost     = distance_km / efficiency_km_per_unit * energy_price_per_unit
    driver_cost   = duration_h * driver_cost_per_hour
    operating     = distance_km * operating_cost_per_km
    toll_cost     = configured segment toll                 (toll=yes, amount configured)
                  | distance_km * toll_rate_per_km_estimate (toll=yes, estimate enabled)
                  | unavailable -> excluded and reported    (toll=yes, nothing configured)
                  | 0                                       (toll=no, or tag absent: reported as unconfirmed)
    extra_cost    = configured per-segment surcharge (admin overrides)
    money         = fuel + driver + operating + toll + extra

Objectives::

    money     -> money (currency units)
    time      -> duration_h * 3600 (seconds)
    distance  -> length_m (metres)
    balanced  -> money + value_of_time_per_hour * duration_h   (generalised cost, currency units)

The balanced objective is a weighted *generalised* cost, not the cheapest
monetary route. A per-trip fixed cost is added once to the route total and does
not influence route choice.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

from .graph import Edge
from .ucs import CostFn

MONEY_Q = Decimal("0.01")
ZERO = Decimal("0")


def D(value: Any) -> Decimal:
    """Convert to Decimal without binary-float artefacts."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    return Decimal(str(value))


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_Q, rounding=ROUND_HALF_UP)


class Objective(StrEnum):
    MONEY = "money"
    TIME = "time"
    DISTANCE = "distance"
    BALANCED = "balanced"


OBJECTIVE_UNITS = {
    Objective.MONEY: "currency",
    Objective.TIME: "seconds",
    Objective.DISTANCE: "metres",
    Objective.BALANCED: "currency (generalised)",
}


@dataclass(frozen=True)
class CostConfig:
    currency: str = "INR"
    energy_price_per_unit: Decimal = ZERO
    energy_unit: str = "litre"
    efficiency_km_per_unit: Decimal = Decimal("1")
    driver_cost_per_hour: Decimal = ZERO
    operating_cost_per_km: Decimal = ZERO
    fixed_cost_per_trip: Decimal = ZERO
    include_fuel: bool = True
    include_driver: bool = True
    include_operating: bool = True
    include_tolls: bool = True
    toll_rate_per_km_estimate: Decimal | None = None
    value_of_time_per_hour: Decimal = ZERO
    emissions_kg_per_unit: Decimal | None = None
    speed_factor: Decimal = Decimal("1")
    max_vehicle_speed_kph: Decimal | None = None

    def __post_init__(self) -> None:
        if self.efficiency_km_per_unit <= 0:
            raise ValueError("Vehicle efficiency must be greater than zero")
        if not (Decimal("0") < self.speed_factor <= Decimal("2")):
            raise ValueError("speed_factor must be in (0, 2]")
        for name in ("energy_price_per_unit", "driver_cost_per_hour", "operating_cost_per_km",
                     "fixed_cost_per_trip", "value_of_time_per_hour"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.toll_rate_per_km_estimate is not None and self.toll_rate_per_km_estimate < 0:
            raise ValueError("toll_rate_per_km_estimate must be non-negative")

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in self.__dict__.items():
            out[k] = str(v) if isinstance(v, Decimal) else v
        return out


@dataclass(frozen=True)
class VehicleRestrictions:
    gross_weight_t: float | None = None
    height_m: float | None = None
    width_m: float | None = None
    is_heavy_goods: bool = False


def vehicle_allowed(edge: Edge, vehicle: VehicleRestrictions | None) -> bool:
    if vehicle is None:
        return True
    maxw = edge.get("maxweight_t")
    if maxw is not None and vehicle.gross_weight_t is not None and vehicle.gross_weight_t > maxw:
        return False
    maxh = edge.get("maxheight_m")
    if maxh is not None and vehicle.height_m is not None and vehicle.height_m > maxh:
        return False
    maxwd = edge.get("maxwidth_m")
    if maxwd is not None and vehicle.width_m is not None and vehicle.width_m > maxwd:
        return False
    if vehicle.is_heavy_goods and edge.get("hgv") == "no":
        return False
    return True


def effective_speed_kph(edge: Edge, cfg: CostConfig) -> float:
    base = float(edge.get("speed_kph") or 0)
    if base <= 0:
        raise ValueError(f"Edge {edge.id!r} has no usable speed")
    speed = base * float(cfg.speed_factor)
    if cfg.max_vehicle_speed_kph is not None:
        speed = min(speed, float(cfg.max_vehicle_speed_kph))
    return speed


def edge_duration_h(edge: Edge, cfg: CostConfig) -> float:
    return (float(edge.get("length_m", 0)) / 1000.0) / effective_speed_kph(edge, cfg)


@dataclass
class SegmentCost:
    distance_km: Decimal
    duration_h: Decimal
    fuel: Decimal = ZERO
    driver: Decimal = ZERO
    operating: Decimal = ZERO
    toll: Decimal = ZERO
    extra: Decimal = ZERO
    toll_status: str = "none"  # confirmed_free | configured | estimated | unavailable | unconfirmed

    @property
    def total(self) -> Decimal:
        return self.fuel + self.driver + self.operating + self.toll + self.extra


def segment_cost(edge: Edge, cfg: CostConfig) -> SegmentCost:
    km = D(edge.get("length_m", 0)) / 1000
    hours = D(edge_duration_h(edge, cfg))
    sc = SegmentCost(distance_km=km, duration_h=hours)
    if cfg.include_fuel:
        sc.fuel = km / cfg.efficiency_km_per_unit * cfg.energy_price_per_unit
    if cfg.include_driver:
        sc.driver = hours * cfg.driver_cost_per_hour
    if cfg.include_operating:
        sc.operating = km * cfg.operating_cost_per_km
    sc.extra = D(edge.get("extra_cost"))

    toll_tag = edge.get("toll", "unknown")
    configured = edge.get("toll_cost")
    if toll_tag == "yes":
        if configured is not None:
            sc.toll_status = "configured"
            sc.toll = D(configured) if cfg.include_tolls else ZERO
        elif cfg.toll_rate_per_km_estimate is not None:
            sc.toll_status = "estimated"
            sc.toll = km * cfg.toll_rate_per_km_estimate if cfg.include_tolls else ZERO
        else:
            sc.toll_status = "unavailable"
    elif toll_tag == "no":
        sc.toll_status = "confirmed_free"
    else:
        sc.toll_status = "unconfirmed"
        if configured is not None:  # admin recorded a toll on an untagged road
            sc.toll_status = "configured"
            sc.toll = D(configured) if cfg.include_tolls else ZERO
    return sc


def make_cost_fn(objective: Objective, cfg: CostConfig, vehicle: VehicleRestrictions | None = None) -> CostFn:
    """Return a UCS cost function for the objective; ``None`` marks restricted edges."""

    if objective is Objective.DISTANCE:
        def fn(edge: Edge) -> float | None:
            if not vehicle_allowed(edge, vehicle):
                return None
            return float(edge.get("length_m", 0))
    elif objective is Objective.TIME:
        def fn(edge: Edge) -> float | None:
            if not vehicle_allowed(edge, vehicle):
                return None
            return edge_duration_h(edge, cfg) * 3600.0
    elif objective is Objective.MONEY:
        def fn(edge: Edge) -> float | None:
            if not vehicle_allowed(edge, vehicle):
                return None
            return float(segment_cost(edge, cfg).total)
    elif objective is Objective.BALANCED:
        vot = float(cfg.value_of_time_per_hour)

        def fn(edge: Edge) -> float | None:
            if not vehicle_allowed(edge, vehicle):
                return None
            sc = segment_cost(edge, cfg)
            return float(sc.total) + vot * float(sc.duration_h)
    else:  # pragma: no cover
        raise ValueError(f"Unknown objective {objective}")
    return fn


def objective_formula(objective: Objective, cfg: CostConfig) -> str:
    if objective is Objective.MONEY:
        return "Σ (fuel + driver + operating + toll + surcharge) per segment"
    if objective is Objective.TIME:
        return "Σ segment_length_km / (modelled_speed_kph × speed_factor) — static, no live traffic"
    if objective is Objective.DISTANCE:
        return "Σ segment_length_m"
    return (f"Σ [monetary cost + {cfg.value_of_time_per_hour} {cfg.currency}/h × duration_h] — "
            "a generalised cost that trades money against time; not the cheapest monetary route")


@dataclass
class RouteBreakdown:
    currency: str
    distance_km: Decimal = ZERO
    duration_h: Decimal = ZERO
    fuel: Decimal = ZERO
    driver: Decimal = ZERO
    operating: Decimal = ZERO
    toll: Decimal = ZERO
    extra: Decimal = ZERO
    fixed: Decimal = ZERO
    energy_units: Decimal = ZERO
    emissions_kg: Decimal | None = None
    toll_km: dict[str, Decimal] = field(default_factory=dict)
    components_enabled: dict[str, bool] = field(default_factory=dict)

    @property
    def total(self) -> Decimal:
        return self.fuel + self.driver + self.operating + self.toll + self.extra + self.fixed

    def round_components(self) -> RouteBreakdown:
        """Quantise each component to the currency's minor unit so the reported
        total is exactly the sum of the reported components."""
        for k in ("fuel", "driver", "operating", "toll", "extra", "fixed"):
            setattr(self, k, money(getattr(self, k)))
        return self

    def warnings(self) -> list[str]:
        w: list[str] = []
        unavailable = self.toll_km.get("unavailable", ZERO)
        if unavailable > 0:
            w.append(f"{unavailable:.2f} km is on roads tagged as tolled in OpenStreetMap but no toll amount or "
                     "estimate rate is configured; toll cost for those segments is NOT included.")
        estimated = self.toll_km.get("estimated", ZERO)
        if estimated > 0:
            w.append(f"Toll for {estimated:.2f} km is an estimate from the configured per-km toll rate.")
        unconfirmed = self.toll_km.get("unconfirmed", ZERO)
        if unconfirmed > 0 and self.components_enabled.get("tolls"):
            w.append(f"{unconfirmed:.2f} km has no toll tag in OpenStreetMap; treated as untolled but not confirmed toll-free.")
        return w

    def as_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "distance_km": str(self.distance_km.quantize(Decimal("0.001"))),
            "duration_h": str(self.duration_h.quantize(Decimal("0.0001"))),
            "fuel": str(money(self.fuel)),
            "driver": str(money(self.driver)),
            "operating": str(money(self.operating)),
            "toll": str(money(self.toll)),
            "extra": str(money(self.extra)),
            "fixed": str(money(self.fixed)),
            "total": str(money(self.total)),
            "energy_units": str(self.energy_units.quantize(Decimal("0.001"))),
            "emissions_kg": None if self.emissions_kg is None else str(self.emissions_kg.quantize(Decimal("0.001"))),
            "toll_km": {k: str(v.quantize(Decimal("0.001"))) for k, v in self.toll_km.items()},
            "components_enabled": self.components_enabled,
        }


def route_breakdown(edges: Iterable[Edge], cfg: CostConfig, *, include_fixed: bool = True) -> RouteBreakdown:
    """Decimal-exact cost breakdown of a route (sum of per-segment costs)."""
    rb = RouteBreakdown(
        currency=cfg.currency,
        components_enabled={"fuel": cfg.include_fuel, "driver": cfg.include_driver,
                            "operating": cfg.include_operating, "tolls": cfg.include_tolls},
    )
    for e in edges:
        sc = segment_cost(e, cfg)
        rb.distance_km += sc.distance_km
        rb.duration_h += sc.duration_h
        rb.fuel += sc.fuel
        rb.driver += sc.driver
        rb.operating += sc.operating
        rb.toll += sc.toll
        rb.extra += sc.extra
        rb.toll_km[sc.toll_status] = rb.toll_km.get(sc.toll_status, ZERO) + sc.distance_km
    rb.energy_units = rb.distance_km / cfg.efficiency_km_per_unit
    if cfg.emissions_kg_per_unit is not None:
        rb.emissions_kg = rb.energy_units * cfg.emissions_kg_per_unit
    if include_fixed:
        rb.fixed = cfg.fixed_cost_per_trip
    return rb.round_components()


def objective_value(rb: RouteBreakdown, objective: Objective, cfg: CostConfig) -> float:
    """Objective value of a route from its breakdown (excluding the fixed trip cost)."""
    variable = rb.total - rb.fixed
    if objective is Objective.MONEY:
        return float(variable)
    if objective is Objective.TIME:
        return float(rb.duration_h * 3600)
    if objective is Objective.DISTANCE:
        return float(rb.distance_km * 1000)
    return float(variable + cfg.value_of_time_per_hour * rb.duration_h)
