# RouteWise API

Versioned REST API under `/api/v1`. Interactive documentation (Swagger UI) is served at `/docs`; the OpenAPI schema at `/api/v1/openapi.json`.

## Conventions

- **Errors** are always `{"error": {"code": "...", "message": "...", "details": ...}}` with a meaningful status:
  `404 not_found`, `409 conflict`, `422 validation_error | no_route | outside_coverage | capacity_exceeded | plan_infeasible | missing_energy_price | ...`, `429 rate_limited`, `502 upstream_error`, `503 service_unavailable`.
- **Pagination**: list endpoints accept `page` (1-based) and `page_size` (≤ 200) and return `{items, total, page, page_size}`.
- **Sorting**: `sort=field` or `sort=-field` (descending) from a per-endpoint allow-list.
- **Money** is returned as decimal strings (e.g. `"101.00"`) in the workspace currency.
- **Admin actions** (network import/refresh/delete, closures, overrides, settings) require `X-Admin-Token` when `ROUTEWISE_ADMIN_TOKEN` is set.
- **Rate limits** (per client IP, per minute, `ROUTEWISE_RATE_LIMIT_PER_MINUTE`) apply to route calculation, geocoding and network import.
- The server never trusts client-supplied totals, capacities or route results: costs are always recomputed server-side.

## Key requests

`POST /routes/calculate`
```json
{
  "warehouse_id": 1,                       // or "origin": {"lat":..,"lon":..}
  "delivery_order_id": 7,                  // or "address_id" or "destination": {"lat":..,"lon":..,"label":..}
  "vehicle_id": 1,
  "objective": "money",                    // money | time | distance | balanced
  "preferences": {"include_tolls": true, "value_of_time_per_hour": "300"},
  "include_alternatives": true,
  "include_benchmarks": false,             // A* + greedy on the same network/costs
  "trace": false, "trace_limit": 5000      // UCS expansion order for visualisation
}
```
Response (abridged): `plan_id, status ("estimated"), distance_m, duration_s, total_cost, currency, breakdown{fuel, driver, operating, toll, extra, fixed, total, toll_km, ...}, geometry, named_segments, stops, alternatives[], baseline, estimated_savings, benchmarks[], search_stats{expanded_nodes, relaxations, queue_operations, stale_skipped, ...}, reconstruction[], assumptions[], warnings[], freshness{...}, cost_is_estimate: true`.

`POST /routes/multi-stop`
```json
{"warehouse_id": 1, "delivery_order_ids": [1,2,3], "vehicle_id": 1, "objective": "money",
 "algorithm": "ucs", "return_to_depot": true, "allow_reload": false, "respect_time_windows": true,
 "departure_time": "2026-10-23T09:00:00+05:30"}
```

`POST /networks/{id}/closures` — `{"edge_ids": [...]}` or `{"lat":..,"lon":..}` (nearest road), `both_directions`, `reason`, `starts_at`, `ends_at`, `auto_reroute`. Returns the closure, affected plan ids and reroute results (deltas in distance, duration and cost, or `no_alternative`).

`POST /routes/{id}/actual` — records the *actual* outcome of a dispatched plan; only these values are reported as actual expenditure.

## Endpoints

### Health

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/health` | Health |

### Settings

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/settings` | Get Settings |
| PUT | `/api/v1/settings` | Update Settings |

### Warehouses

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/warehouses` | List Warehouses |
| POST | `/api/v1/warehouses` | Create Warehouse |
| GET | `/api/v1/warehouses/{wid}` | Get Warehouse |
| PUT | `/api/v1/warehouses/{wid}` | Update Warehouse |
| DELETE | `/api/v1/warehouses/{wid}` | Delete Warehouse |
| GET | `/api/v1/warehouses/{wid}/geocode-candidates` | Warehouse Candidates |

### Customers

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/customers` | List Customers |
| POST | `/api/v1/customers` | Create Customer |
| GET | `/api/v1/customers/{cid}` | Get Customer |
| PUT | `/api/v1/customers/{cid}` | Update Customer |
| DELETE | `/api/v1/customers/{cid}` | Delete Customer |
| POST | `/api/v1/customers/{cid}/addresses` | Add Address |
| PUT | `/api/v1/addresses/{aid}` | Update Address |
| DELETE | `/api/v1/addresses/{aid}` | Delete Address |
| POST | `/api/v1/addresses/{aid}/geocode` | Geocode Address |
| POST | `/api/v1/addresses/{aid}/resolve` | Resolve Address |
| GET | `/api/v1/addresses` | List Addresses |

### Geocoding

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/geocode/search` | Search |
| POST | `/api/v1/geocode/pending` | Geocode Pending |
| GET | `/api/v1/geocode/pending/status` | Geocode Pending Status |

### Delivery Orders

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/orders` | List Orders |
| POST | `/api/v1/orders` | Create Order |
| GET | `/api/v1/orders/export.csv` | Export Orders |
| GET | `/api/v1/orders/import/template.csv` | Import Template |
| POST | `/api/v1/orders/import` | Import Orders |
| POST | `/api/v1/orders/bulk-status` | Bulk Status |
| GET | `/api/v1/orders/{oid}` | Get Order |
| PUT | `/api/v1/orders/{oid}` | Update Order |
| DELETE | `/api/v1/orders/{oid}` | Delete Order |

### Vehicles

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/vehicles` | List Vehicles |
| POST | `/api/v1/vehicles` | Create Vehicle |
| GET | `/api/v1/vehicles/{vid}` | Get Vehicle |
| PUT | `/api/v1/vehicles/{vid}` | Update Vehicle |
| DELETE | `/api/v1/vehicles/{vid}` | Delete Vehicle |

### Road Networks

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/networks` | List Networks |
| POST | `/api/v1/networks` | Create Network |
| POST | `/api/v1/networks/upload` | Upload Network |
| GET | `/api/v1/networks/{nid}` | Get Network |
| DELETE | `/api/v1/networks/{nid}` | Delete Network |
| POST | `/api/v1/networks/{nid}/refresh` | Refresh Network |
| POST | `/api/v1/networks/{nid}/activate` | Activate Network |
| GET | `/api/v1/networks/{nid}/segments` | Segments |
| GET | `/api/v1/networks/{nid}/segments/nearest` | Nearest Segment |
| GET | `/api/v1/networks/{nid}/closures` | List Closures |
| POST | `/api/v1/networks/{nid}/closures` | Create Closure |
| POST | `/api/v1/networks/{nid}/closures/{cid}/reopen` | Reopen Closure |
| GET | `/api/v1/networks/{nid}/closures/events` | Closure Events |
| GET | `/api/v1/networks/{nid}/overrides` | List Overrides |
| PUT | `/api/v1/networks/{nid}/overrides/{edge_id}` | Set Override |

### Routes

| Method | Path | Summary |
|---|---|---|
| POST | `/api/v1/routes/calculate` | Calculate |
| POST | `/api/v1/routes/multi-stop` | Multi Stop |
| GET | `/api/v1/routes` | History |
| GET | `/api/v1/routes/export.csv` | Export History |
| GET | `/api/v1/routes/compare` | Compare |
| GET | `/api/v1/routes/{pid}` | Get Plan |
| DELETE | `/api/v1/routes/{pid}` | Delete Plan |
| PATCH | `/api/v1/routes/{pid}/status` | Set Status |
| POST | `/api/v1/routes/{pid}/actual` | Record Actual |
| POST | `/api/v1/routes/{pid}/duplicate` | Duplicate |
| POST | `/api/v1/routes/{pid}/reroute` | Reroute |
| GET | `/api/v1/routes/{pid}/export.csv` | Export Plan |

### Analytics

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/analytics/summary` | Summary |
