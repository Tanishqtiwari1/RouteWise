/**
 * Read-only demo mode (VITE_DEMO_MODE=true), used for the static GitHub Pages build.
 *
 * Every response comes from `demo-snapshot.json`, a snapshot of real API output
 * exported by `backend/scripts/export_demo_snapshot.py`. Lists are filtered,
 * sorted and paginated in the browser; anything that would change data or needs
 * the server (route calculation, geocoding, closures) is rejected with a clear
 * "read-only demo" error.
 */
import type { RoutePlan } from "@/types/api";

export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === "true";
export const REPO_URL = "https://github.com/Tanishqtiwari1/RouteWise";

interface Snapshot {
  exported_at: string;
  get: Record<string, unknown>;
  showcase: { single?: RoutePlan; multi?: RoutePlan };
}

let snapshotPromise: Promise<Snapshot> | null = null;

export function loadSnapshot(): Promise<Snapshot> {
  snapshotPromise ??= fetch(`${import.meta.env.BASE_URL}demo-snapshot.json`).then((r) => {
    if (!r.ok) throw new Error("Demo data could not be loaded.");
    return r.json() as Promise<Snapshot>;
  });
  return snapshotPromise;
}

export class DemoReadOnlyError extends Error {}

export const READ_ONLY_MESSAGE =
  "This is a read-only demo. Calculating routes, editing data and road closures need the full app with its server — see the README to run it.";

type Query = Record<string, unknown>;
type Item = Record<string, unknown>;

function matches(item: Item, key: string, wanted: unknown): boolean {
  const values = Array.isArray(wanted) ? wanted.map(String) : [String(wanted)];
  const actual = key === "geocode_status" && item.geocode_status === undefined ? undefined : item[key];
  return values.includes(String(actual));
}

function searchText(item: Item, q: string): boolean {
  const needle = q.toLowerCase();
  return JSON.stringify(item).toLowerCase().includes(needle);
}

function compare(a: unknown, b: unknown): number {
  const na = Number(a);
  const nb = Number(b);
  if (a !== null && b !== null && a !== "" && b !== "" && !Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
  return String(a ?? "").localeCompare(String(b ?? ""));
}

const SORT_ALIASES: Record<string, string> = { customer: "customer_name" };
const FILTER_KEYS = ["status", "priority", "kind", "vehicle_id", "warehouse_id", "customer_id", "geocode_status", "active"];

function pageOf(data: { items: Item[] }, query: Query) {
  let items = [...data.items];
  if (typeof query.q === "string" && query.q) items = items.filter((i) => searchText(i, query.q as string));
  for (const k of FILTER_KEYS) {
    const v = query[k];
    if (v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length)) continue;
    items = items.filter((i) => matches(i, k, v));
  }
  if (typeof query.sort === "string" && query.sort) {
    const desc = query.sort.startsWith("-");
    const field = SORT_ALIASES[query.sort.replace("-", "")] ?? query.sort.replace("-", "");
    items.sort((a, b) => compare(a[field], b[field]) * (desc ? -1 : 1));
  }
  const page = Number(query.page ?? 1);
  const size = Number(query.page_size ?? 25);
  return { items: items.slice((page - 1) * size, page * size), total: items.length, page, page_size: size };
}

export async function demoRequest<T>(method: string, path: string, query: Query = {}): Promise<T> {
  if (method !== "GET") throw new DemoReadOnlyError(READ_ONLY_MESSAGE);
  const snap = await loadSnapshot();
  const data = snap.get[path];

  if (path.match(/^\/networks\/\d+\/segments$/)) return { segments: [], truncated: false } as T;
  if (path.startsWith("/geocode") || path.match(/^\/networks\/\d+\/segments\/nearest$/)) throw new DemoReadOnlyError(READ_ONLY_MESSAGE);
  if (path === "/routes/compare") {
    const ids = (Array.isArray(query.ids) ? query.ids : [query.ids]).map(String);
    return { plans: ids.map((id) => snap.get[`/routes/${id}`]).filter(Boolean), notes: [] } as T;
  }
  if (path === "/addresses") {
    const customers = (snap.get["/customers"] as { items: { addresses: Item[] }[] }).items;
    return pageOf({ items: customers.flatMap((c) => c.addresses) }, query) as T;
  }
  if (data === undefined) throw new Error(`Not available in the demo snapshot: ${path}`);
  if (data && typeof data === "object" && "items" in (data as object) && "total" in (data as object)) {
    return pageOf(data as { items: Item[] }, query) as T;
  }
  return data as T;
}

export async function showcasePlan(kind: "single" | "multi"): Promise<RoutePlan | null> {
  const snap = await loadSnapshot();
  return snap.showcase[kind] ?? null;
}
