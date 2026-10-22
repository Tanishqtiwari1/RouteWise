"""OpenStreetMap road-network ingestion, storage and in-memory graph cache.

Workflow
--------
1. Download drivable ways for a bounding box from an Overpass API endpoint
   (or accept an uploaded Overpass JSON export as an alternative import path).
2. Build a *simplified* directed graph: graph nodes are way endpoints and
   intersections; each edge keeps its full geometry and is measured along it
   with the haversine formula. One-way rules follow OSM tags.
3. Mark the largest strongly-connected component; snapping only targets nodes in
   it so that a route never starts on an isolated fragment.
4. Persist the graph as gzip JSON under ``DATA_DIR/networks`` (kept separate
   from the delivery database); metadata lives in ``road_networks``.

Road closures and segment overrides are stored in the database and applied at
query time (closures as blocked edges, overrides merged into edge data).
"""

from __future__ import annotations

import gzip
import json
import logging
import math
import re
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithms.baselines import haversine_m
from app.algorithms.graph import WeightedGraph
from app.core.config import get_settings
from app.core.errors import NotFound, ServiceUnavailable, Unprocessable
from app.database.session import SessionLocal
from app.models import RoadClosure, RoadNetwork, RoadNetworkGraph, SegmentOverride, utcnow

from .settings_service import DEFAULT_HIGHWAY_SPEEDS, get_settings_row

log = logging.getLogger(__name__)

DRIVABLE = ("motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|"
            "tertiary|tertiary_link|unclassified|residential|living_street|service|road")

FORMAT_VERSION = 1


def overpass_query(south: float, west: float, north: float, east: float, timeout_s: int) -> str:
    bbox = f"{south},{west},{north},{east}"
    return (
        f"[out:json][timeout:{timeout_s}];"
        f'way["highway"~"^({DRIVABLE})$"]["area"!="yes"]["access"!~"^(private|no)$"]'
        f'["motor_vehicle"!~"^(no|private)$"]["motorcar"!~"^(no|private)$"]'
        f'["service"!~"^(parking_aisle|driveway|private|emergency_access)$"]({bbox});'
        "(._;>;);out body qt;"
    )


def bbox_area_km2(south: float, west: float, north: float, east: float) -> float:
    h = haversine_m(south, west, north, west) / 1000
    mid = (south + north) / 2
    w = haversine_m(mid, west, mid, east) / 1000
    return h * w


def validate_bbox(south: float, west: float, north: float, east: float) -> float:
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise Unprocessable("Bounding box must satisfy south < north and west < east within valid coordinates.")
    area = bbox_area_km2(south, west, north, east)
    limit = get_settings().max_network_area_km2
    if area > limit:
        raise Unprocessable(f"Requested area is {area:.0f} km², above the configured limit of {limit:.0f} km². "
                            "Select a smaller area or raise ROUTEWISE_MAX_NETWORK_AREA_KM2.", code="area_too_large")
    return area


# ------------------------------------------------------------------ tag parsing

_NUM = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z' \"]*)\s*$")


def parse_speed_kph(v: str | None) -> float | None:
    if not v:
        return None
    m = _NUM.match(v.split(";")[0])
    if not m:
        return None  # e.g. "IN:urban", "signals", "none"
    val = float(m.group(1))
    unit = m.group(2).strip().lower()
    if unit == "mph":
        val *= 1.609344
    elif unit not in ("", "km/h", "kmh", "kph"):
        return None
    return val if 0 < val <= 200 else None


def parse_weight_t(v: str | None) -> float | None:
    if not v:
        return None
    m = _NUM.match(v)
    if not m:
        return None
    val, unit = float(m.group(1)), m.group(2).strip().lower()
    if unit in ("", "t"):
        return val
    if unit == "kg":
        return val / 1000
    if unit in ("lbs", "lb"):
        return val * 0.000453592
    return None


def parse_length_m(v: str | None) -> float | None:
    if not v:
        return None
    m = _NUM.match(v)
    if m and m.group(2).strip().lower() in ("", "m"):
        return float(m.group(1))
    ft = re.match(r"^\s*(\d+)'\s*(?:(\d+)\")?\s*$", v)
    if ft:
        return int(ft.group(1)) * 0.3048 + int(ft.group(2) or 0) * 0.0254
    return None


def _oneway(tags: dict[str, str]) -> int:
    """1 forward only, -1 reverse only, 0 both directions."""
    ow = tags.get("oneway", "").lower()
    if ow in ("yes", "true", "1"):
        return 1
    if ow == "-1" or ow == "reverse":
        return -1
    if ow == "no":
        return 0
    if tags.get("highway") in ("motorway",) or tags.get("junction") in ("roundabout", "circular"):
        return 1
    return 0


def _toll(tags: dict[str, str]) -> str:
    t = tags.get("toll", "").lower()
    if t in ("yes", "true"):
        return "yes"
    if t in ("no", "false"):
        return "no"
    return "unknown"


# ---------------------------------------------------------------- graph build

def build_graph_document(osm: dict[str, Any], *, source: str, bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    """Convert Overpass JSON into the stored, simplified graph document."""
    elements = osm.get("elements")
    if not isinstance(elements, list):
        raise Unprocessable("OSM data has no 'elements' list; expected Overpass API JSON output.")
    coords: dict[int, tuple[float, float]] = {}
    ways: list[dict[str, Any]] = []
    for el in elements:
        t = el.get("type")
        if t == "node" and "lat" in el and "lon" in el:
            coords[int(el["id"])] = (float(el["lat"]), float(el["lon"]))
        elif t == "way" and el.get("nodes") and el.get("tags", {}).get("highway"):
            ways.append(el)
    if not ways:
        raise Unprocessable("The OSM data contains no drivable roads for this area.", code="empty_network")

    usage: dict[int, int] = defaultdict(int)
    for w in ways:
        nds = w["nodes"]
        for n in nds:
            usage[n] += 1
        usage[nds[0]] += 1  # endpoints are always graph nodes
        usage[nds[-1]] += 1

    nodes: dict[int, tuple[float, float]] = {}
    edges: list[list[Any]] = []
    missing_refs = 0
    for w in ways:
        tags = w.get("tags", {})
        nds = [n for n in w["nodes"] if n in coords]
        missing_refs += len(w["nodes"]) - len(nds)
        if len(nds) < 2:
            continue
        direction = _oneway(tags)
        attrs = {
            "way_id": int(w["id"]),
            "name": tags.get("name") or tags.get("ref"),
            "highway": tags.get("highway"),
            "maxspeed_kph": parse_speed_kph(tags.get("maxspeed")),
            "toll": _toll(tags),
            "maxweight_t": parse_weight_t(tags.get("maxweight")),
            "maxheight_m": parse_length_m(tags.get("maxheight")),
            "maxwidth_m": parse_length_m(tags.get("maxwidth")),
            "hgv": tags.get("hgv"),
        }
        attrs = {k: v for k, v in attrs.items() if v is not None}
        piece: list[int] = [nds[0]]
        part = 0
        for n in nds[1:]:
            piece.append(n)
            if usage[n] > 1 or n == nds[-1]:
                if piece[0] == piece[-1] and len(piece) <= 2:
                    piece = [n]
                    continue
                geom = [coords[x] for x in piece]
                length = sum(haversine_m(*geom[i], *geom[i + 1]) for i in range(len(geom) - 1))
                if length > 0:
                    u, v = piece[0], piece[-1]
                    nodes[u], nodes[v] = coords[u], coords[v]
                    fid, rid = f"{w['id']}:{part}:f", f"{w['id']}:{part}:r"
                    g = [[round(a, 7), round(b, 7)] for a, b in geom]
                    if direction >= 0:
                        edges.append([fid, u, v, round(length, 2), g, rid if direction == 0 else None, attrs])
                    if direction <= 0:
                        edges.append([rid, v, u, round(length, 2), g[::-1], fid if direction == 0 else None, attrs])
                    part += 1
                piece = [n]

    # Largest strongly connected component (NetworkX used for inspection only).
    dg = nx.DiGraph()
    dg.add_nodes_from(nodes)
    dg.add_edges_from((e[1], e[2]) for e in edges)
    main = max(nx.strongly_connected_components(dg), key=len) if nodes else set()

    return {
        "format": FORMAT_VERSION,
        "source": source,
        "bbox": list(bbox),
        "osm_timestamp": (osm.get("osm3s") or {}).get("timestamp_osm_base"),
        "copyright": (osm.get("osm3s") or {}).get("copyright", "© OpenStreetMap contributors, ODbL"),
        "nodes": {str(k): [round(v[0], 7), round(v[1], 7), 1 if k in main else 0] for k, v in nodes.items()},
        "edges": edges,
        "stats": {"ways": len(ways), "missing_node_refs": missing_refs, "main_component_nodes": len(main)},
    }


def encode_graph_document(doc: dict[str, Any]) -> bytes:
    return gzip.compress(json.dumps(doc, separators=(",", ":")).encode("utf-8"), compresslevel=6)


def cache_path(network_id: int, revision_tag: str) -> Path:
    return get_settings().networks_dir / f"network_{network_id}_{revision_tag}.json.gz"


def write_graph_cache(path: Path, blob: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    except OSError:  # cache only; the database copy is authoritative
        log.warning("Could not write graph cache %s", path)


# --------------------------------------------------------------- ingestion job

_jobs_lock = threading.Lock()
_running_jobs: set[int] = set()


def download_overpass(overpass_url: str, south: float, west: float, north: float, east: float) -> dict[str, Any]:
    s = get_settings()
    q = overpass_query(south, west, north, east, int(s.overpass_timeout_s))
    try:
        resp = httpx.post(overpass_url, data={"data": q}, timeout=s.overpass_timeout_s + 30,
                          headers={"User-Agent": s.http_user_agent})
    except httpx.HTTPError as exc:
        raise ServiceUnavailable(f"Could not reach the Overpass API ({exc.__class__.__name__}). "
                                 "Retry later, choose another Overpass endpoint in Settings, or upload an "
                                 "Overpass JSON export.", code="overpass_unreachable") from exc
    if resp.status_code in (429, 504):
        raise ServiceUnavailable(f"Overpass API is busy (HTTP {resp.status_code}). Retry in a few minutes or "
                                 "use a smaller area.", code="overpass_busy")
    if resp.status_code >= 400:
        raise ServiceUnavailable(f"Overpass API returned HTTP {resp.status_code}: {resp.text[:200]}", code="overpass_error")
    try:
        data = resp.json()
    except ValueError as exc:
        raise ServiceUnavailable("Overpass API returned non-JSON output (possibly a timeout).", code="overpass_error") from exc
    if data.get("remark") and "runtime error" in data["remark"].lower():
        raise ServiceUnavailable(f"Overpass query failed: {data['remark'][:300]}", code="overpass_error")
    return data


def _set_status(db: Session, net: RoadNetwork, status: str, detail: str | None = None, error: str | None = None) -> None:
    net.status = status
    net.status_detail = detail
    net.error = error
    db.commit()


def finalize_network(db: Session, net: RoadNetwork, doc: dict[str, Any]) -> RoadNetwork:
    blob = encode_graph_document(doc)
    row = db.get(RoadNetworkGraph, net.id)
    if row is None:
        db.add(RoadNetworkGraph(network_id=net.id, data=blob))
    else:
        row.data, row.created_at = blob, utcnow()
    path = cache_path(net.id, utcnow().strftime("%Y%m%d%H%M%S"))
    write_graph_cache(path, blob)
    net.file_path = str(path)
    net.node_count = len(doc["nodes"])
    net.edge_count = len(doc["edges"])
    net.osm_timestamp = doc.get("osm_timestamp")
    net.imported_at = utcnow()
    net.revision = (net.revision or 0) + 1
    net.status = "ready"
    net.error = None
    net.status_detail = (f"{doc['stats']['ways']} ways → {net.node_count} nodes / {net.edge_count} directed edges; "
                         f"{doc['stats']['main_component_nodes']} nodes in the main connected component.")
    if not db.scalar(select(RoadNetwork).where(RoadNetwork.is_active.is_(True), RoadNetwork.id != net.id)):
        net.is_active = True
    db.commit()
    invalidate_cache(net.id)
    return net


def run_ingestion(network_id: int) -> None:
    """Background job: download, build and store a network. Never fabricates data."""
    with _jobs_lock:
        if network_id in _running_jobs:
            return
        _running_jobs.add(network_id)
    db = SessionLocal()
    try:
        net = db.get(RoadNetwork, network_id)
        if net is None:
            return
        ws = get_settings_row(db)
        net.source_url = ws.overpass_url
        _set_status(db, net, "downloading", "Requesting road data from Overpass API…")
        data = download_overpass(ws.overpass_url, net.south, net.west, net.north, net.east)
        _set_status(db, net, "building", f"Building graph from {len(data.get('elements', []))} OSM elements…")
        doc = build_graph_document(data, source=ws.overpass_url, bbox=(net.south, net.west, net.north, net.east))
        finalize_network(db, net, doc)
        log.info("Network %s ready: %s", network_id, net.status_detail)
    except Exception as exc:  # recorded for the UI; no fallback data is generated
        log.exception("Network ingestion %s failed", network_id)
        db.rollback()
        net = db.get(RoadNetwork, network_id)
        if net is not None:
            msg = getattr(exc, "message", None) or f"{exc.__class__.__name__}: {exc}"
            _set_status(db, net, "failed", None, msg)
    finally:
        db.close()
        with _jobs_lock:
            _running_jobs.discard(network_id)


# ------------------------------------------------------------ in-memory cache

class SpatialIndex:
    def __init__(self, cell_deg: float = 0.005) -> None:
        self.cell = cell_deg
        self.buckets: dict[tuple[int, int], list[tuple[int, float, float]]] = defaultdict(list)

    def key(self, lat: float, lon: float) -> tuple[int, int]:
        return (math.floor(lat / self.cell), math.floor(lon / self.cell))

    def add(self, node: int, lat: float, lon: float) -> None:
        self.buckets[self.key(lat, lon)].append((node, lat, lon))

    def nearest(self, lat: float, lon: float, max_m: float) -> tuple[int, float] | None:
        ki, kj = self.key(lat, lon)
        best: tuple[int, float] | None = None
        cell_m = self.cell * 111_000 * max(0.2, math.cos(math.radians(lat)))
        max_ring = int(max_m / cell_m) + 2
        for r in range(max_ring + 1):
            for i in range(ki - r, ki + r + 1):
                for j in range(kj - r, kj + r + 1):
                    if max(abs(i - ki), abs(j - kj)) != r:
                        continue
                    for node, nlat, nlon in self.buckets.get((i, j), ()):
                        d = haversine_m(lat, lon, nlat, nlon)
                        if best is None or d < best[1]:
                            best = (node, d)
            if best is not None and best[1] <= (r - 1) * cell_m:
                break
        if best is None or best[1] > max_m:
            return None
        return best


@dataclass
class LoadedNetwork:
    network_id: int
    revision: int
    settings_revision: int
    graph: WeightedGraph
    index: SpatialIndex
    bbox: tuple[float, float, float, float]
    osm_timestamp: str | None
    max_speed_kph: float

    def coords(self, node: int) -> tuple[float, float]:
        d = self.graph.node_data(node)
        return d["lat"], d["lon"]

    def snap(self, lat: float, lon: float) -> tuple[int, float]:
        max_m = get_settings().max_snap_distance_m
        hit = self.index.nearest(lat, lon, max_m)
        if hit is None:
            raise Unprocessable(
                f"Location ({lat:.5f}, {lon:.5f}) is more than {max_m:.0f} m from any routable road in this network. "
                "It may be outside the imported area; import a network that covers it.", code="outside_coverage")
        return hit


_cache: dict[int, LoadedNetwork] = {}
_cache_lock = threading.Lock()


def invalidate_cache(network_id: int | None = None) -> None:
    with _cache_lock:
        if network_id is None:
            _cache.clear()
        else:
            _cache.pop(network_id, None)


def _effective_speed(attrs: dict[str, Any], speeds: dict[str, float]) -> tuple[float, str]:
    default = float(speeds.get(attrs.get("highway", ""), speeds.get("road", 25)))
    tag = attrs.get("maxspeed_kph")
    if tag:
        return (min(tag, default), "class default capped by posted limit") if tag < default else (default, "road-class default")
    return default, "road-class default"


def load_network(db: Session, net: RoadNetwork) -> LoadedNetwork:
    if net.status != "ready" or not net.file_path:
        raise Unprocessable(f"Road network '{net.name}' is not ready (status: {net.status}).", code="network_not_ready")
    ws = get_settings_row(db)
    with _cache_lock:
        hit = _cache.get(net.id)
        if hit and hit.revision == net.revision and hit.settings_revision == ws.revision:
            return hit
    path = Path(net.file_path)
    if path.exists():
        blob = path.read_bytes()
    else:
        row = db.get(RoadNetworkGraph, net.id)
        if row is None:
            raise ServiceUnavailable(f"Graph data for network '{net.name}' is missing; refresh the network.",
                                     code="network_file_missing")
        blob = row.data
        write_graph_cache(path, blob)
    doc = json.loads(gzip.decompress(blob))
    overrides = {o.edge_id: o for o in db.scalars(select(SegmentOverride).where(SegmentOverride.network_id == net.id))}
    speeds = {**DEFAULT_HIGHWAY_SPEEDS, **(ws.highway_speeds_kph or {})}
    g = WeightedGraph()
    idx = SpatialIndex()
    for nid, (lat, lon, main) in doc["nodes"].items():
        n = int(nid)
        g.add_node(n, lat=lat, lon=lon, main=bool(main))
        if main:
            idx.add(n, lat, lon)
    max_speed = 1.0
    for eid, u, v, length, geom, twin, attrs in doc["edges"]:
        data = dict(attrs)
        data["length_m"] = length
        data["geometry"] = geom
        data["twin"] = twin
        speed, src = _effective_speed(data, speeds)
        o = overrides.get(eid)
        if o is not None:
            if o.speed_kph:
                speed, src = o.speed_kph, "segment override"
            if o.toll_cost is not None:
                data["toll_cost"] = o.toll_cost
            if o.extra_cost is not None:
                data["extra_cost"] = o.extra_cost
        data["speed_kph"] = speed
        data["speed_source"] = src
        max_speed = max(max_speed, speed)
        g.add_edge(eid, u, v, **data)
    loaded = LoadedNetwork(net.id, net.revision, ws.revision, g, idx,
                           tuple(doc["bbox"]), doc.get("osm_timestamp"), max_speed)
    with _cache_lock:
        _cache[net.id] = loaded
    return loaded


def get_network(db: Session, network_id: int | None = None) -> RoadNetwork:
    if network_id is not None:
        net = db.get(RoadNetwork, network_id)
        if net is None:
            raise NotFound(f"Road network {network_id} not found")
        return net
    net = db.scalar(select(RoadNetwork).where(RoadNetwork.is_active.is_(True)))
    if net is None:
        raise Unprocessable("No active road network. Import one on the Road Network page first.", code="no_network")
    return net


def active_blocked_edges(db: Session, network_id: int) -> set[str]:
    now = utcnow()
    blocked: set[str] = set()
    for c in db.scalars(select(RoadClosure).where(RoadClosure.network_id == network_id, RoadClosure.active.is_(True))):
        starts = _aware(c.starts_at)
        ends = _aware(c.ends_at)
        if starts and starts > now:
            continue
        if ends and ends <= now:
            continue
        blocked.update(c.edge_ids)
    return blocked


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)


def freshness(db: Session, net: RoadNetwork) -> dict[str, Any]:
    ws = get_settings_row(db)
    imported = _aware(net.imported_at)
    stale = bool(imported and utcnow() - imported > timedelta(days=ws.network_stale_after_days))
    return {
        "network_id": net.id, "network_name": net.name, "revision": net.revision,
        "imported_at": imported.isoformat() if imported else None,
        "osm_timestamp": net.osm_timestamp, "stale": stale,
        "stale_after_days": ws.network_stale_after_days, "attribution": net.attribution,
        "energy_prices_updated_at": ws.energy_prices_updated_at.isoformat() if ws.energy_prices_updated_at else None,
        "energy_prices_source": ws.energy_prices_source,
        "traffic": "none (static modelled speeds)",
    }


def nearest_edges(loaded: LoadedNetwork, lat: float, lon: float, limit: int = 1, max_m: float = 150) -> list[tuple[float, Any]]:
    """Edges whose geometry passes closest to a point (for picking a road to close)."""
    hit = loaded.index.nearest(lat, lon, max_m * 4)
    candidates: dict[str, tuple[float, Any]] = {}
    if hit is None:
        return []
    # Search edges around nearby nodes (1-hop), measuring point-to-polyline distance.
    seeds = {hit[0]}
    ki, kj = loaded.index.key(lat, lon)
    for i in range(ki - 1, ki + 2):
        for j in range(kj - 1, kj + 2):
            for n, _, _ in loaded.index.buckets.get((i, j), ()):
                seeds.add(n)
    for n in seeds:
        for e in loaded.graph.neighbors(n):
            d = _point_polyline_m(lat, lon, e.get("geometry"))
            if d <= max_m and (e.id not in candidates or d < candidates[e.id][0]):
                candidates[e.id] = (d, e)
    return sorted(candidates.values(), key=lambda x: x[0])[:limit]


def _point_polyline_m(lat: float, lon: float, geom: list[list[float]]) -> float:
    best = math.inf
    k = math.cos(math.radians(lat))
    px, py = lon * k, lat
    for (alat, alon), (blat, blon) in zip(geom, geom[1:], strict=False):
        ax, ay, bx, by = alon * k, alat, blon * k, blat
        dx, dy = bx - ax, by - ay
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        qx, qy = ax + t * dx, ay + t * dy
        best = min(best, haversine_m(lat, lon, qy, qx / k))
    return best
