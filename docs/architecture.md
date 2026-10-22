# Architecture

```
frontend/ (React + TS + Vite)            backend/ (FastAPI)
  pages ─ features ─ components            api/v1/*  ── schemas (Pydantic)
     │  TanStack Query hooks                  │
     └── services/api.ts ── /api/v1 ──────►   services/
                                               ├─ routing.py      single route, alternatives, benchmarks,
                                               │                  multi-stop assembly, rerouting, persistence
                                               ├─ road_network.py Overpass ingestion, graph build, cache,
                                               │                  snapping, closures, overrides
                                               ├─ geocoding.py    Nominatim client (throttled, cached, classified)
                                               ├─ settings_service.py  cost config from persisted settings
                                               ├─ analytics.py    metrics from persisted records only
                                               └─ csv_io.py       validated import, exports, reports
                                             algorithms/  (pure Python — no DB, web or map imports)
                                               ├─ graph.py  ucs.py  cost_model.py
                                               ├─ multi_stop.py  baselines.py (A*, greedy)
                                             models/ (SQLAlchemy 2) ─ alembic/ migrations
                                             data/networks/*.json.gz   road graphs (outside the DB)
```

**Boundaries**

* `app/algorithms` is framework-independent and fully unit-tested on synthetic graphs. UCS receives a graph and a `cost_fn(edge) → float | None`; it knows nothing about money, maps or the database.
* The road graph is a compressed (gzip JSON) document in its own table, `road_network_graphs`, separate from the delivery tables, so it survives redeploys on hosts without persistent disks. A copy under `DATA_DIR/networks` is only a cache, and graphs are cached in memory per (network revision, settings revision).
* Every route plan stores a snapshot: request, cost configuration, vehicle parameters, geometry, per-edge costs, network id + revision and search statistics. Later edits to settings, vehicles or networks never change historical reports.
* Estimated vs actual: plans are estimates (`cost_is_estimate: true`); actual costs exist only in `actual_delivery_records`, entered by users.

## Data model

| Table | Purpose |
|---|---|
| `workspace_settings` | single row: currency, energy prices (+ source/date), cost component switches, driver cost, toll estimate, value of time, speed model, providers |
| `warehouses` | depots with location and geocode status |
| `customers`, `delivery_addresses` | addresses with `geocode_status` (pending/matched/ambiguous/failed/manual) and candidates |
| `delivery_orders` | weight, dimensions, quantity, priority, status, time window, service time |
| `vehicles` | category, fuel type, efficiency, payload, restrictions, per-km and per-trip costs, emissions factor |
| `road_networks` | bbox, source, status, counts, OSM timestamp, revision, cache file path |
| `road_network_graphs` | compressed graph document per network (source of truth) |
| `segment_overrides` | admin toll amounts, surcharges, speeds per directed edge |
| `road_closures`, `road_closure_events` | closures with optional time window; closed/reopened events with network revision and affected plans |
| `route_plans` | plan snapshot (intentionally denormalised, see above), status lifecycle estimated → saved → dispatched → completed / superseded |
| `route_stops`, `route_edges` | ordered stops with leg and allocated costs; ordered edge snapshot with per-edge cost and toll status |
| `actual_delivery_records` | recorded outcomes (the only source of "actual" figures) |
| `reroute_events` | old/new plan, closure, deltas or no-alternative reason |
| `geocode_cache` | provider responses (30-day TTL) to respect usage policies |

Foreign keys, indexes on common filters (status, created_at, plan ids, edge ids), and UTC timestamps throughout. Schema changes go through Alembic.

## Security & reliability

* Environment configuration (`ROUTEWISE_*`), no secrets in the frontend; optional `X-Admin-Token` for administrative actions (constant-time compare).
* Pydantic validation on every request; ORM-only database access; CSV size/row/encoding/column validation.
* CORS restricted to configured origins (the production nginx setup is same-origin).
* Abuse limits: bbox area cap, snapping distance cap, UCS expansion and time limits, multi-stop stop/state caps, per-IP rate limits on expensive or externally-backed endpoints.
* Providers: identifying User-Agent, geocoder throttle (~1 req/s), caching, explicit handling of 429/5xx/timeouts; no fabricated fallback data.
* Structured errors, logging via the standard library.

## Known design trade-offs

* Background jobs (network ingestion, batch geocoding) run in-process. Run a single API worker, or move them to a task queue for multi-worker deployments. The in-memory rate limiter is per process.
* Single workspace; no user accounts (admin token only).
