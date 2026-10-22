"""Address geocoding via a Nominatim-compatible service.

Respects the public Nominatim usage policy: identifying User-Agent, at most
~1 request/second (process-wide throttle), results cached in the database. For
production volumes configure a self-hosted or commercial Nominatim-compatible
endpoint in Settings.

Results are classified, never assumed:
* ``matched``   — one clear best candidate
* ``ambiguous`` — several comparable candidates far apart; user must choose
* ``failed``    — no candidate, or the provider could not be reached
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithms.baselines import haversine_m
from app.core.config import get_settings
from app.core.errors import RateLimited, UpstreamError
from app.models import DeliveryAddress, GeocodeCache, utcnow

from .settings_service import get_settings_row

_lock = threading.Lock()
_last_call = 0.0
CACHE_TTL = timedelta(days=30)


@dataclass
class GeocodeOutcome:
    status: str  # matched | ambiguous | failed
    candidates: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""

    @property
    def best(self) -> dict[str, Any] | None:
        return self.candidates[0] if self.candidates else None


def validate_coordinates(lat: float, lon: float) -> None:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"Invalid coordinates ({lat}, {lon})")


def _throttle() -> None:
    global _last_call
    interval = get_settings().geocoder_min_interval_s
    with _lock:
        wait = _last_call + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _classify(cands: list[dict[str, Any]]) -> GeocodeOutcome:
    if not cands:
        return GeocodeOutcome("failed", [], "No match found for this address.")
    if len(cands) == 1:
        return GeocodeOutcome("matched", cands, "Single match.")
    a, b = cands[0], cands[1]
    gap = (a.get("importance") or 0) - (b.get("importance") or 0)
    far = haversine_m(a["lat"], a["lon"], b["lat"], b["lon"]) > 500
    if far and gap < 0.05:
        return GeocodeOutcome("ambiguous", cands, "Several different places match this address; choose one.")
    return GeocodeOutcome("matched", cands, "Best match selected; alternatives available.")


def search(db: Session, query: str, *, limit: int = 5, viewbox: tuple[float, float, float, float] | None = None) -> GeocodeOutcome:
    """Geocode free text. ``viewbox`` = (west, south, east, north) biases results."""
    q = " ".join(query.split())
    if len(q) < 3:
        return GeocodeOutcome("failed", [], "Address is too short to geocode.")
    ws = get_settings_row(db)
    provider = ws.geocoder_url.rstrip("/")
    cache_key = f"{q.lower()}|{limit}|{viewbox}"
    cached = db.scalar(select(GeocodeCache).where(GeocodeCache.provider == provider, GeocodeCache.query == cache_key)
                       .order_by(GeocodeCache.created_at.desc()))
    if cached is not None:
        created = cached.created_at if cached.created_at.tzinfo else cached.created_at.replace(tzinfo=utcnow().tzinfo)
        if utcnow() - created < CACHE_TTL:
            return _classify(cached.results)

    params: dict[str, Any] = {"q": q, "format": "jsonv2", "limit": limit, "addressdetails": 0}
    if viewbox:
        params["viewbox"] = ",".join(str(v) for v in viewbox)
    s = get_settings()
    _throttle()
    try:
        resp = httpx.get(f"{provider}/search", params=params, timeout=s.http_timeout_s,
                         headers={"User-Agent": s.http_user_agent, "Accept-Language": "en"})
    except httpx.HTTPError as exc:
        raise UpstreamError(f"Geocoding provider unreachable: {exc.__class__.__name__}", code="geocoder_unreachable") from exc
    if resp.status_code == 429:
        raise RateLimited("Geocoding provider rate limit reached; try again shortly.", code="geocoder_rate_limited")
    if resp.status_code >= 400:
        raise UpstreamError(f"Geocoding provider returned HTTP {resp.status_code}", code="geocoder_error")
    try:
        raw = resp.json()
    except ValueError as exc:
        raise UpstreamError("Geocoding provider returned an invalid response", code="geocoder_error") from exc
    cands = [
        {"lat": float(r["lat"]), "lon": float(r["lon"]), "label": r.get("display_name", ""),
         "importance": r.get("importance"), "type": r.get("type"), "category": r.get("category")}
        for r in raw if "lat" in r and "lon" in r
    ]
    db.add(GeocodeCache(provider=provider, query=cache_key, results=cands))
    db.commit()
    return _classify(cands)


def geocode_address(db: Session, address: DeliveryAddress, viewbox=None) -> DeliveryAddress:
    """Geocode and persist the outcome on the address row (status always recorded)."""
    try:
        outcome = search(db, address.address_text, viewbox=viewbox)
    except UpstreamError as exc:
        address.geocode_status = "failed"
        address.geocode_label = exc.message
        address.geocoded_at = utcnow()
        db.commit()
        return address
    address.geocode_candidates = outcome.candidates
    address.geocoded_at = utcnow()
    address.geocode_status = outcome.status
    if outcome.status == "matched":
        address.lat, address.lon = outcome.best["lat"], outcome.best["lon"]
        address.geocode_label = outcome.best["label"]
    else:
        address.lat = address.lon = None
        address.geocode_label = outcome.message
    db.commit()
    return address
