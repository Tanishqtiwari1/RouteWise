import json
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.security import rate_limited, require_admin
from app.database import get_db
from app.models import RoadClosure, RoadClosureEvent, RoadNetwork, SegmentOverride, utcnow
from app.schemas.routing import ClosureIn, NetworkIn, OverrideIn
from app.services import road_network as rn
from app.services.routing import affected_plans, reroute_event_dict, reroute_plan

router = APIRouter(prefix="/networks", tags=["road networks"])


def net_dict(n: RoadNetwork, db: Session | None = None) -> dict:
    d = {k: getattr(n, k) for k in ("id", "name", "south", "west", "north", "east", "source", "source_url", "status",
                                    "status_detail", "error", "node_count", "edge_count", "osm_timestamp", "revision",
                                    "is_active", "attribution")}
    d["imported_at"] = n.imported_at.isoformat() if n.imported_at else None
    d["created_at"] = n.created_at.isoformat() if n.created_at else None
    d["area_km2"] = round(rn.bbox_area_km2(n.south, n.west, n.north, n.east), 2)
    if db is not None and n.status == "ready":
        d["freshness"] = rn.freshness(db, n)
    return d


def _net(db: Session, nid: int) -> RoadNetwork:
    n = db.get(RoadNetwork, nid)
    if not n:
        raise NotFound("Road network not found")
    return n


def _bump(db: Session, net: RoadNetwork, reload_graph: bool) -> None:
    net.revision += 1
    db.commit()
    if reload_graph:
        rn.invalidate_cache(net.id)
    else:
        cached = rn._cache.get(net.id)
        if cached is not None:
            cached.revision = net.revision


@router.get("")
def list_networks(db: Session = Depends(get_db)):
    return [net_dict(n, db) for n in db.scalars(select(RoadNetwork).order_by(RoadNetwork.created_at.desc()))]


@router.post("", status_code=202, dependencies=[Depends(require_admin), Depends(rate_limited("network"))])
def create_network(body: NetworkIn, background: BackgroundTasks, db: Session = Depends(get_db)):
    area = rn.validate_bbox(body.south, body.west, body.north, body.east)
    net = RoadNetwork(name=body.name, south=body.south, west=body.west, north=body.north, east=body.east,
                      status="pending", status_detail=f"Queued ({area:.1f} km²)")
    db.add(net)
    db.commit()
    background.add_task(rn.run_ingestion, net.id)
    return net_dict(net)


@router.post("/upload", status_code=201, dependencies=[Depends(require_admin)])
async def upload_network(name: str = Form(..., min_length=1, max_length=120), file: UploadFile = File(...),
                         db: Session = Depends(get_db)):
    """Alternative import: an Overpass API JSON export (e.g. from overpass-turbo) for when the API is unavailable."""
    raw = await file.read()
    if len(raw) > 200_000_000:
        raise Unprocessable("File too large (max 200 MB).")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise Unprocessable("File is not valid JSON. Export from Overpass with [out:json].") from exc
    nodes = [e for e in data.get("elements", []) if e.get("type") == "node" and "lat" in e]
    if not nodes:
        raise Unprocessable("No OSM nodes found in file.", code="empty_network")
    lats = [e["lat"] for e in nodes]
    lons = [e["lon"] for e in nodes]
    bbox = (min(lats), min(lons), max(lats), max(lons))
    rn.validate_bbox(*bbox)
    net = RoadNetwork(name=name, south=bbox[0], west=bbox[1], north=bbox[2], east=bbox[3],
                      source="openstreetmap-file-upload", source_url=file.filename, status="building")
    db.add(net)
    db.commit()
    try:
        doc = rn.build_graph_document(data, source=f"upload:{file.filename}", bbox=bbox)
    except Unprocessable as exc:
        net.status, net.error = "failed", exc.message
        db.commit()
        raise
    rn.finalize_network(db, net, doc)
    return net_dict(net, db)


@router.get("/{nid}")
def get_network(nid: int, db: Session = Depends(get_db)):
    return net_dict(_net(db, nid), db)


@router.post("/{nid}/refresh", status_code=202, dependencies=[Depends(require_admin), Depends(rate_limited("network"))])
def refresh_network(nid: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    net = _net(db, nid)
    if net.status in ("downloading", "building"):
        raise Conflict("An import is already running for this network.")
    if net.source == "openstreetmap-file-upload":
        raise Unprocessable("Uploaded networks cannot be refreshed from Overpass; upload a new export instead.")
    net.status, net.status_detail, net.error = "pending", "Refresh queued", None
    db.commit()
    background.add_task(rn.run_ingestion, net.id)
    return net_dict(net)


@router.post("/{nid}/activate", dependencies=[Depends(require_admin)])
def activate_network(nid: int, db: Session = Depends(get_db)):
    net = _net(db, nid)
    if net.status != "ready":
        raise Unprocessable("Only ready networks can be activated.")
    db.execute(update(RoadNetwork).values(is_active=False))
    net.is_active = True
    db.commit()
    return net_dict(net, db)


@router.delete("/{nid}", status_code=204, dependencies=[Depends(require_admin)])
def delete_network(nid: int, db: Session = Depends(get_db)):
    net = _net(db, nid)
    if net.status in ("downloading", "building"):
        raise Conflict("Cannot delete a network while it is importing.")
    db.delete(net)
    db.commit()
    rn.invalidate_cache(nid)


@router.get("/{nid}/segments")
def segments(nid: int, south: float, west: float, north: float, east: float,
             limit: int = Query(4000, ge=1, le=15000), db: Session = Depends(get_db)):
    """Road segments intersecting a bounding box (for map display); one entry per two-way road."""
    net = _net(db, nid)
    loaded = rn.load_network(db, net)
    blocked = rn.active_blocked_edges(db, nid)
    out, seen = [], set()
    for e in loaded.graph.edges():
        if e.id in seen:
            continue
        geom = e.get("geometry")
        if not any(south <= p[0] <= north and west <= p[1] <= east for p in geom):
            continue
        if e.get("twin"):
            seen.add(e.get("twin"))
        out.append({"id": e.id, "twin": e.get("twin"), "name": e.get("name"), "highway": e.get("highway"),
                    "toll": e.get("toll"), "speed_kph": e.get("speed_kph"), "length_m": e.get("length_m"),
                    "closed": e.id in blocked, "geometry": geom})
        if len(out) >= limit:
            break
    return {"segments": out, "truncated": len(out) >= limit}


@router.get("/{nid}/segments/nearest")
def nearest_segment(nid: int, lat: float, lon: float, db: Session = Depends(get_db)):
    loaded = rn.load_network(db, _net(db, nid))
    hits = rn.nearest_edges(loaded, lat, lon, limit=3)
    if not hits:
        raise NotFound("No road segment within 150 m of that point.")
    overrides = {o.edge_id: o for o in db.scalars(select(SegmentOverride).where(SegmentOverride.network_id == nid))}
    res = []
    for d, e in hits:
        o = overrides.get(e.id)
        res.append({"id": e.id, "twin": e.get("twin"), "distance_m": round(d, 1), "name": e.get("name"),
                    "highway": e.get("highway"), "toll": e.get("toll"), "speed_kph": e.get("speed_kph"),
                    "speed_source": e.get("speed_source"), "length_m": e.get("length_m"), "way_id": e.get("way_id"),
                    "maxweight_t": e.get("maxweight_t"), "maxheight_m": e.get("maxheight_m"),
                    "override": None if o is None else {"toll_cost": o.toll_cost and str(o.toll_cost),
                                                        "extra_cost": o.extra_cost and str(o.extra_cost),
                                                        "speed_kph": o.speed_kph, "note": o.note},
                    "geometry": e.get("geometry")})
    return res


# ----------------------------------------------------------------- closures

def closure_dict(c: RoadClosure) -> dict:
    return {"id": c.id, "network_id": c.network_id, "edge_ids": c.edge_ids, "road_name": c.road_name,
            "reason": c.reason, "active": c.active, "geometry": c.geometry,
            "starts_at": c.starts_at.isoformat() if c.starts_at else None,
            "ends_at": c.ends_at.isoformat() if c.ends_at else None,
            "reopened_at": c.reopened_at.isoformat() if c.reopened_at else None,
            "created_at": c.created_at.isoformat()}


@router.get("/{nid}/closures")
def list_closures(nid: int, active: bool | None = None, db: Session = Depends(get_db)):
    stmt = select(RoadClosure).where(RoadClosure.network_id == nid).order_by(RoadClosure.created_at.desc())
    if active is not None:
        stmt = stmt.where(RoadClosure.active.is_(active))
    return [closure_dict(c) for c in db.scalars(stmt)]


@router.post("/{nid}/closures", status_code=201, dependencies=[Depends(require_admin)])
def create_closure(nid: int, body: ClosureIn, db: Session = Depends(get_db)):
    net = _net(db, nid)
    loaded = rn.load_network(db, net)
    if body.edge_ids:
        missing = [e for e in body.edge_ids if not loaded.graph.has_edge(e)]
        if missing:
            raise Unprocessable(f"Unknown edge ids: {missing[:5]}")
        edges = [loaded.graph.edge(e) for e in body.edge_ids]
    else:
        hits = rn.nearest_edges(loaded, body.lat, body.lon, limit=1)
        if not hits:
            raise Unprocessable("No road segment within 150 m of that point.")
        edges = [hits[0][1]]
    ids = {e.id for e in edges}
    if body.both_directions:
        ids |= {e.get("twin") for e in edges if e.get("twin")}
    c = RoadClosure(network_id=nid, edge_ids=sorted(ids), road_name=edges[0].get("name") or edges[0].get("highway"),
                    reason=body.reason, starts_at=body.starts_at, ends_at=body.ends_at,
                    geometry=edges[0].get("geometry"))
    db.add(c)
    db.flush()
    _bump(db, net, reload_graph=False)
    plans = affected_plans(db, nid, list(ids))
    db.add(RoadClosureEvent(closure_id=c.id, event="closed", network_revision=net.revision,
                            affected_plan_ids=[p.id for p in plans]))
    db.commit()
    events = []
    now = utcnow()
    in_effect = (not body.starts_at or _aware(body.starts_at) <= now) and (not body.ends_at or _aware(body.ends_at) > now)
    if body.auto_reroute and in_effect:
        events = [reroute_event_dict(reroute_plan(db, p, closure_id=c.id)) for p in plans]
    return {"closure": closure_dict(c), "affected_plan_ids": [p.id for p in plans], "reroutes": events,
            "network_revision": net.revision}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)


@router.post("/{nid}/closures/{cid}/reopen", dependencies=[Depends(require_admin)])
def reopen_closure(nid: int, cid: int, db: Session = Depends(get_db)):
    net = _net(db, nid)
    c = db.get(RoadClosure, cid)
    if not c or c.network_id != nid:
        raise NotFound("Closure not found")
    if not c.active:
        raise Conflict("Closure is already reopened.")
    c.active = False
    c.reopened_at = utcnow()
    _bump(db, net, reload_graph=False)
    db.add(RoadClosureEvent(closure_id=c.id, event="reopened", network_revision=net.revision, affected_plan_ids=[]))
    db.commit()
    return {"closure": closure_dict(c), "network_revision": net.revision,
            "note": "Plans rerouted because of this closure keep their current route; use 'Recalculate' to re-optimise."}


@router.get("/{nid}/closures/events")
def closure_events(nid: int, db: Session = Depends(get_db)):
    rows = db.execute(select(RoadClosureEvent, RoadClosure).join(RoadClosure)
                      .where(RoadClosure.network_id == nid).order_by(RoadClosureEvent.created_at.desc()).limit(200)).all()
    return [{"id": ev.id, "closure_id": ev.closure_id, "event": ev.event, "road_name": c.road_name,
             "network_revision": ev.network_revision, "affected_plan_ids": ev.affected_plan_ids,
             "created_at": ev.created_at.isoformat()} for ev, c in rows]


# ---------------------------------------------------------------- overrides

@router.get("/{nid}/overrides")
def list_overrides(nid: int, db: Session = Depends(get_db)):
    return [{"id": o.id, "edge_id": o.edge_id, "toll_cost": o.toll_cost and str(o.toll_cost),
             "extra_cost": o.extra_cost and str(o.extra_cost), "speed_kph": o.speed_kph, "note": o.note}
            for o in db.scalars(select(SegmentOverride).where(SegmentOverride.network_id == nid))]


@router.put("/{nid}/overrides/{edge_id}", dependencies=[Depends(require_admin)])
def set_override(nid: int, edge_id: str, body: OverrideIn, db: Session = Depends(get_db)):
    net = _net(db, nid)
    loaded = rn.load_network(db, net)
    if not loaded.graph.has_edge(edge_id):
        raise NotFound("Edge not found")
    ids = [edge_id]
    twin = loaded.graph.edge(edge_id).get("twin")
    if body.both_directions and twin:
        ids.append(twin)
    for eid in ids:
        o = db.scalar(select(SegmentOverride).where(SegmentOverride.network_id == nid, SegmentOverride.edge_id == eid))
        empty = body.toll_cost is None and body.extra_cost is None and body.speed_kph is None
        if empty:
            if o:
                db.delete(o)
            continue
        if o is None:
            o = SegmentOverride(network_id=nid, edge_id=eid)
            db.add(o)
        o.toll_cost, o.extra_cost, o.speed_kph, o.note = body.toll_cost, body.extra_cost, body.speed_kph, body.note
    db.flush()
    _bump(db, net, reload_graph=True)
    return {"edge_ids": ids, "network_revision": net.revision}
