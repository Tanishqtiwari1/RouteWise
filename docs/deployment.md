# Deployment

## Environment variables (backend)

| Variable | Default | Notes |
|---|---|---|
| `ROUTEWISE_DATABASE_URL` | SQLite in `backend/data/` | Production: `postgresql+psycopg://user:pass@host:5432/db` |
| `ROUTEWISE_DATA_DIR` | `backend/data` | Cache for road-graph files (the database holds the authoritative copy). |
| `ROUTEWISE_CORS_ORIGINS` | `http://localhost:5173` | Comma-separated; bare hostnames get `https://`. Not needed when the frontend proxies `/api` (nginx setup). |
| `ROUTEWISE_ADMIN_TOKEN` | *(unset)* | Required for network import, closures, overrides, settings. **Mandatory when `ROUTEWISE_ENVIRONMENT=production`** (the API refuses to start without it). |
| `ROUTEWISE_ENVIRONMENT` | `development` | Set `production` in deployments. |
| `ROUTEWISE_HTTP_USER_AGENT` | generic | Identify your deployment + contact (OSM usage policy). |
| `ROUTEWISE_MAX_NETWORK_AREA_KM2` | 200 | Largest importable area. |
| `ROUTEWISE_MAX_SNAP_DISTANCE_M` | 1500 | Points farther from any road are rejected as outside coverage. |
| `ROUTEWISE_UCS_MAX_EXPANSIONS` / `ROUTEWISE_UCS_TIME_LIMIT_S` | 3,000,000 / 20 | Search budget. |
| `ROUTEWISE_MULTI_STOP_MAX_STOPS` / `..._MAX_STATES` | 10 / 300,000 | Exact multi-stop budget. |
| `ROUTEWISE_RATE_LIMIT_PER_MINUTE` | 30 | Per IP, per expensive endpoint group. |
| `ROUTEWISE_MAX_CSV_BYTES` / `..._ROWS` | 2 MB / 5000 | CSV import limits. |

Frontend build-time: `VITE_API_BASE_URL` (default `/api/v1`, i.e. same origin). For a separate API origin, set the full URL and add the site origin to `ROUTEWISE_CORS_ORIGINS`.

Map tiles, geocoder and Overpass endpoints are runtime settings (Settings page). The public OSM tile server, Nominatim and Overpass are for light use; for production traffic use your own instances or a commercial provider and keep attribution.

## Docker Compose (local, PostgreSQL)

```bash
docker compose up --build
```
Web: http://localhost:8080 · API docs: http://localhost:8080/docs · API direct: http://localhost:8010. Migrations run on backend start. Optional demo data:
```bash
docker compose exec backend python -m app.seed_demo --import-network
```

## One-click deploy on Render (recommended)

`render.yaml` defines everything: PostgreSQL, the API (Docker) and the website (static).

1. Push this project to a GitHub (or GitLab) repository.
2. On https://dashboard.render.com choose **New → Blueprint**, select the repository, and apply.
3. Wait for the three resources to deploy. The website URL is shown on the `routewise-web` service (e.g. `https://routewise-web.onrender.com`).
4. Open `routewise-api` → Environment, copy the generated `ROUTEWISE_ADMIN_TOKEN`, then in the website click the key icon and paste it.
5. On the site's **Roads** page, import your delivery area, then add warehouses, vehicles and orders.

Notes: free Render services sleep when idle (first request takes ~1 minute) and free PostgreSQL expires after 30 days, so upgrade both for real use. Road graphs are stored in PostgreSQL, so no persistent disk is required.

## Hosting (other providers)

* **Backend** (Render, Railway, Fly.io, ECS, a VM…): build `backend/Dockerfile`, attach managed PostgreSQL via `ROUTEWISE_DATABASE_URL`, mount a persistent volume at `/data`, set `ROUTEWISE_ADMIN_TOKEN` and `ROUTEWISE_HTTP_USER_AGENT`. Health check: `GET /api/v1/health`. Run one worker (in-process background jobs).
* **Frontend**: either `frontend/Dockerfile` (nginx, proxies `/api` to a host named `backend` — edit `nginx.conf` for your backend address), or any static host (Netlify, Vercel, S3+CloudFront) with `VITE_API_BASE_URL=https://api.example.com/api/v1` at build time, an SPA fallback to `index.html`, and that site's origin in `ROUTEWISE_CORS_ORIGINS`.
* After deploying, run `python scripts/smoke_test.py https://your-host/api/v1` to verify.

## Database

* Migrate: `alembic upgrade head` (runs automatically in the container). New migration: `alembic revision --autogenerate -m "..."`.
* Backups: schedule `pg_dump -Fc routewise > routewise_$(date +%F).dump` (or your provider's automated backups + point-in-time recovery). Road graphs are inside the database, so the database backup covers them.
* Refreshing a network re-downloads OSM data; edge ids are derived from OSM way ids, so most closures/overrides remain valid, but ways that OSM editors split or merged may not match.
