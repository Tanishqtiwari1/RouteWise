export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type GeocodeStatus = "pending" | "matched" | "ambiguous" | "failed" | "manual";

export interface GeocodeCandidate {
  lat: number;
  lon: number;
  label: string;
  importance?: number | null;
  type?: string | null;
}

export interface Warehouse {
  id: number;
  name: string;
  address: string | null;
  lat: number | null;
  lon: number | null;
  geocode_status: GeocodeStatus;
  geocode_label: string | null;
  notes: string | null;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Address {
  id: number;
  customer_id: number;
  label: string | null;
  address_text: string;
  lat: number | null;
  lon: number | null;
  geocode_status: GeocodeStatus;
  geocode_label: string | null;
  geocode_candidates: GeocodeCandidate[] | null;
  geocoded_at: string | null;
}

export interface Customer {
  id: number;
  name: string;
  email: string | null;
  phone: string | null;
  notes: string | null;
  addresses: Address[];
  created_at: string;
}

export type VehicleCategory = "two_wheeler" | "car" | "van" | "light_truck" | "heavy_truck";
export type FuelType = "petrol" | "diesel" | "cng" | "electric";

export interface Vehicle {
  id: number;
  name: string;
  category: VehicleCategory;
  fuel_type: FuelType;
  efficiency_km_per_unit: string;
  energy_price_override: string | null;
  max_payload_kg: number;
  gross_weight_t: number | null;
  height_m: number | null;
  width_m: number | null;
  max_speed_kph: number | null;
  operating_cost_per_km: string;
  fixed_cost_per_trip: string;
  emissions_kg_per_unit: string | null;
  active: boolean;
  created_at: string;
}

export type OrderStatus = "pending" | "planned" | "dispatched" | "delivered" | "failed" | "cancelled";
export type Priority = "low" | "normal" | "high" | "urgent";

export interface Order {
  id: number;
  reference: string;
  customer_id: number;
  address_id: number;
  warehouse_id: number | null;
  weight_kg: number;
  quantity: number;
  length_cm: number | null;
  width_cm: number | null;
  height_cm: number | null;
  priority: Priority;
  status: OrderStatus;
  window_start: string | null;
  window_end: string | null;
  service_time_min: number;
  notes: string | null;
  delivered_at: string | null;
  created_at: string;
  customer_name: string | null;
  address_text: string | null;
  geocode_status: GeocodeStatus | null;
  lat: number | null;
  lon: number | null;
  warehouse_name: string | null;
}

export interface Freshness {
  network_id: number;
  network_name: string;
  revision: number;
  imported_at: string | null;
  osm_timestamp: string | null;
  stale: boolean;
  stale_after_days: number;
  attribution: string;
  energy_prices_updated_at: string | null;
  energy_prices_source: string | null;
  traffic: string;
}

export interface RoadNetwork {
  id: number;
  name: string;
  south: number;
  west: number;
  north: number;
  east: number;
  source: string;
  source_url: string | null;
  status: "pending" | "downloading" | "building" | "ready" | "failed";
  status_detail: string | null;
  error: string | null;
  node_count: number;
  edge_count: number;
  osm_timestamp: string | null;
  imported_at: string | null;
  created_at: string | null;
  revision: number;
  is_active: boolean;
  attribution: string;
  area_km2: number;
  freshness?: Freshness;
}

export interface Segment {
  id: string;
  twin: string | null;
  name: string | null;
  highway: string | null;
  toll: "yes" | "no" | "unknown" | null;
  speed_kph: number;
  speed_source?: string;
  length_m: number;
  way_id?: number;
  distance_m?: number;
  maxweight_t?: number | null;
  maxheight_m?: number | null;
  closed?: boolean;
  override?: { toll_cost: string | null; extra_cost: string | null; speed_kph: number | null; note: string | null } | null;
  geometry: [number, number][];
}

export interface Closure {
  id: number;
  network_id: number;
  edge_ids: string[];
  road_name: string | null;
  reason: string | null;
  active: boolean;
  geometry: [number, number][] | null;
  starts_at: string | null;
  ends_at: string | null;
  reopened_at: string | null;
  created_at: string;
}

export interface RerouteEvent {
  id: number;
  original_plan_id: number;
  new_plan_id: number | null;
  closure_id: number | null;
  outcome: "rerouted" | "no_alternative" | "unaffected";
  affected_edge_ids: string[];
  delta_distance_m: number | null;
  delta_duration_s: number | null;
  delta_cost: string | null;
  message: string | null;
  created_at: string | null;
}

export interface Breakdown {
  currency: string;
  distance_km: string;
  duration_h: string;
  fuel: string;
  driver: string;
  operating: string;
  toll: string;
  extra: string;
  fixed: string;
  total: string;
  energy_units: string;
  emissions_kg: string | null;
  toll_km: Record<string, string>;
  components_enabled: Record<string, boolean>;
  trips?: number;
  waiting_s?: number;
  total_load_kg?: number;
  capacity_kg?: number;
  utilization?: number;
}

export interface PlanStop {
  sequence: number;
  kind: "origin" | "delivery" | "reload" | "return" | "destination";
  label: string;
  lat: number;
  lon: number;
  node_id: string;
  delivery_order_id: number | null;
  arrival_s: number;
  wait_s: number;
  leg_distance_m: number;
  leg_cost: string;
  allocated_cost: string | null;
  capacity_left_kg?: number | null;
  load_kg?: number | null;
}

export interface Alternative {
  objective: Objective;
  objective_value: number;
  objective_units: string;
  distance_m: number;
  duration_s: number;
  total_cost: string;
  breakdown: Breakdown;
  geometry: [number, number][];
  same_route_as: string | null;
  formula: string;
}

export interface Benchmark {
  algorithm: "ucs" | "astar" | "greedy";
  label: string;
  status: string;
  optimality: string;
  heuristic: string | null;
  expanded_nodes: number;
  relaxations: number;
  queue_operations: number;
  duration_ms: number;
  objective_value?: number;
  distance_m?: number;
  duration_s?: number;
  total_cost?: string;
  matches_ucs_cost?: boolean;
}

export interface TraceEvent {
  k: "pop" | "goal" | "stale";
  n: number;
  c: number;
  lat: number;
  lon: number;
}

export type Objective = "money" | "time" | "distance" | "balanced";
export type PlanStatus = "estimated" | "saved" | "dispatched" | "completed" | "superseded";

export interface ActualRecord {
  distance_km: number | null;
  duration_min: number | null;
  fuel_cost: string | null;
  toll_cost: string | null;
  other_cost: string | null;
  total_cost: string;
  deliveries_completed: number;
  deliveries_failed: number;
  completed_at: string;
  notes: string | null;
}

export interface RoutePlan {
  id: number;
  plan_id: number;
  name: string | null;
  kind: "single" | "multi";
  status: PlanStatus;
  warehouse_id: number | null;
  vehicle_id: number | null;
  network_id: number | null;
  network_revision: number;
  parent_plan_id: number | null;
  algorithm: string;
  objective: Objective;
  objective_value: number;
  objective_formula: string;
  origin: { label: string; lat: number; lon: number; node: number; snap_m: number };
  destination: { label: string; lat: number; lon: number; node: number; snap_m: number } | null;
  return_to_depot: boolean;
  distance_m: number;
  duration_s: number;
  total_cost: string;
  currency: string;
  breakdown: Breakdown;
  emissions_kg: number | null;
  baseline: { method: string; total_cost: string; distance_m: number; comparable?: boolean; note?: string; order?: string[] } | null;
  estimated_savings: string | null;
  geometry: [number, number][];
  node_count: number;
  search_stats: Record<string, unknown>;
  assumptions: string[];
  warnings: string[];
  cost_config: Record<string, unknown>;
  vehicle: { name: string; fuel_type: string; max_payload_kg: number } | null;
  request: Record<string, unknown>;
  created_at: string;
  saved_at: string | null;
  dispatched_at: string | null;
  completed_at: string | null;
  cost_is_estimate: boolean;
  stops: PlanStop[];
  actual: ActualRecord | null;
  edges?: { sequence: number; edge_id: string; name: string | null; highway: string | null; length_m: number; duration_s: number; cost: string; toll_status: string }[];
  reroutes?: RerouteEvent[];
  // calculation-only fields
  objective_units?: string;
  named_segments?: { name: string; highway: string | null; distance_m: number; duration_s: number; cost: string; edge_count: number; toll: string | null }[];
  access?: { from: [number, number]; to: [number, number]; distance_m: number }[];
  alternatives?: Alternative[];
  benchmarks?: Benchmark[] | null;
  freshness?: Freshness;
  cost_per_delivery?: string;
  trace?: { events: TraceEvent[]; truncated: boolean; recorded: number };
  legs?: { from: string; to: string; distance_m: number; duration_s: number; cost: string; geometry: [number, number][] }[];
}

export interface Settings {
  workspace_name: string;
  currency: string;
  energy_prices: Record<FuelType, { price: string; unit: string }>;
  energy_units: Record<FuelType, string>;
  energy_prices_updated_at: string | null;
  energy_prices_source: string | null;
  driver_cost_per_hour: string;
  include_fuel: boolean;
  include_driver: boolean;
  include_operating: boolean;
  include_tolls: boolean;
  toll_rate_per_km_estimate: string | null;
  value_of_time_per_hour: string;
  speed_factor: string;
  highway_speeds_kph: Record<string, number>;
  default_vehicle_id: number | null;
  default_objective: Objective;
  savings_baseline: string;
  tile_url: string;
  tile_attribution: string;
  geocoder_url: string;
  overpass_url: string;
  network_stale_after_days: number;
  revision: number;
  updated_at: string | null;
}

export interface AnalyticsSummary {
  currency: string;
  definitions: Record<string, string>;
  totals: {
    committed_plans: number;
    calculations: number;
    planned_deliveries: number;
    estimated_cost: string;
    avg_estimated_cost_per_delivery: string | null;
    estimated_savings: string;
    baseline_cost: string;
    savings_pct: number | null;
    actual_recorded_cost: string;
    plans_with_actuals: number;
    estimated_cost_of_plans_with_actuals: string;
    distance_km: number;
    emissions_kg: number | null;
  };
  trend: { date: string; estimated: number; actual: number; plans: number; deliveries: number; cost_per_delivery: number | null }[];
  components: { component: string; amount: number }[];
  distance_vs_cost: { plan_id: number; distance_km: number; cost: number; kind: string; name: string }[];
  top_locations: { label: string; lat: number; lon: number; count: number }[];
  vehicles: { vehicle_id: number | null; vehicle: string; plans: number; distance_km: number; estimated_cost: number; utilization: number | null }[];
  recent: { id: number; name: string; kind: string; status: PlanStatus; total_cost: string; distance_m: number; created_at: string }[];
  orders_by_status: Record<string, number>;
  completion: { recorded: number; deliveries_completed: number; deliveries_failed: number; success_rate: number | null };
}

export interface ImportSummary {
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  errors: { row: number; field: string; message: string }[];
  unknown_columns: string[];
  dry_run: boolean;
  created_orders: number;
  created_customers: number;
  created_addresses: number;
  pending_geocode: number;
}
