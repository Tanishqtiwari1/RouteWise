# RouteWise — Smart Delivery Cost Minimizer

Plans least-cost delivery routes over real OpenStreetMap road networks using a hand-written **Uniform Cost Search**, with transparent, configurable costs (fuel/energy, driver time, vehicle operating cost, tolls, surcharges, fixed trip cost), exact multi-stop planning with capacity and time windows, road closures with event-driven rerouting, and persisted history and analytics.

* **Backend**: Python 3.12+, FastAPI, Pydantic, SQLAlchemy 2, Alembic, PostgreSQL (SQLite for dev/tests), pytest.
* **Frontend**: React 18 + TypeScript, Vite, Tailwind, shadcn-style components (Radix), React Router, TanStack Query, Leaflet + OSM tiles, Recharts, React Hook Form + Zod, Lucide.
* **Data**: OpenStreetMap roads via the Overpass API (or an uploaded Overpass JSON export), Nominatim geocoding. No hard-coded routes or operating data; the optional demo seed is labelled `[DEMO]`.

Docs: [architecture](docs/architecture.md) · [algorithms](docs/algorithm.md) · [API](docs/api.md) · [deployment](docs/deployment.md)

## Quick start (local)

Requirements: Python 3.12+ and Node 20+.

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env            # optional; defaults use SQLite in backend/data
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --port 8010
```

```bash
cd frontend
npm install
npm run dev                      # http://localhost:5173, proxies /api to localhost:8010
```

Then in the app: **Road Network** → pan to your area → *Use map view* → *Import roads* (downloads OSM data, ~1 min for ~25 km²) → add a warehouse (Deliveries) and a vehicle (Fleet) → **Route Planner**.

Optional demo data (central New Delhi, labelled `[DEMO]`, real OSM road download):

```bash
cd backend && .venv/bin/python -m app.seed_demo --import-network
```

With Docker (PostgreSQL + API + nginx web on http://localhost:8080): `docker compose up --build`.

**Public deployment:** push to GitHub, then on Render choose New → Blueprint (uses `render.yaml`). Step-by-step instructions are in [docs/deployment.md](docs/deployment.md).

## Tests and checks

```bash
cd backend && .venv/bin/python -m pytest && .venv/bin/ruff check app tests
cd frontend && npm test && npm run typecheck && npm run build
python backend/scripts/smoke_test.py http://localhost:8010/api/v1   # against a running API
```

## Project layout

```
backend/app/algorithms   graph.py, ucs.py, cost_model.py, multi_stop.py, baselines.py (A*, greedy)
backend/app/services     routing, road_network, geocoding, settings_service, analytics, csv_io
backend/app/api/v1       versioned REST routers      backend/app/models  SQLAlchemy entities
backend/alembic          migrations                  backend/tests       unit + API integration tests
frontend/src             pages, features, components (ui, map), hooks, services, types, utils
docs/                    architecture.md, algorithm.md, api.md, deployment.md
```

## Known limitations

* Travel times are static (road class + posted limits + a speed factor). No live traffic integration exists, and none is claimed.
* Toll amounts are rarely in OSM: tolled roads without a configured amount or estimate rate are excluded from cost and flagged; untagged roads are reported as "unconfirmed", not toll-free.
* Multi-stop planning is exact and therefore exponential; it is capped (default 10 stops / 300k states) and explains when a problem exceeds the budget. Larger fleets need a VRP heuristic/solver (future work).
* Background jobs and rate limiting are in-process (single worker). Single workspace with an optional admin token; no per-user accounts.
* Edge ids come from OSM way ids; after a network refresh, closures/overrides on ways that OSM split or merged may no longer match.
* Public OSM services (tiles, Nominatim, Overpass) are for light use; production deployments should configure their own providers in Settings.

## Future enhancements

Live traffic / historical speed profiles; toll-plaza datasets; heuristic VRP for large batches and multiple vehicles; pickups and deliveries; user accounts and roles; task queue (e.g. RQ/Celery) for ingestion; PDF route reports; contraction hierarchies for very large networks (kept as an optional comparison alongside UCS).
