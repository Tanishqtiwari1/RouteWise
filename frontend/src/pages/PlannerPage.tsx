import { useEffect, useMemo, useRef, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Calculator, ChevronDown, MapPin, Pause, Play, Route as RouteIcon, Search, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, Notice, Skeleton } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/input";
import { KV } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RouteMap, type MapMarker, type MapRoute } from "@/components/map/RouteMap";
import { Assumptions, CostBreakdown, PlanActions, RouteHeadline, StopsList, Warnings } from "@/features/RouteDetails";
import { useAction, useHealth, useNetworks, useOrders, useSettings, useVehicles, useWarehouses } from "@/hooks/queries";
import { api, ApiError, errorMessage } from "@/services/api";
import { DEMO_MODE, showcasePlan } from "@/services/demo";
import type { GeocodeCandidate, Objective, RoutePlan } from "@/types/api";
import { cn, duration, km, money, num, OBJECTIVE_LABELS } from "@/utils/format";

const schema = z
  .object({
    mode: z.enum(["single", "multi"]),
    warehouse_id: z.coerce.number({ invalid_type_error: "Select a warehouse" }).int().positive("Select a warehouse"),
    vehicle_id: z.coerce.number({ invalid_type_error: "Select a vehicle" }).int().positive("Select a vehicle"),
    objective: z.enum(["money", "time", "distance", "balanced"]),
    dest_type: z.enum(["order", "point"]),
    delivery_order_id: z.preprocess((x) => (x === "" || x === undefined || x === null ? undefined : Number(x)), z.number().int().positive().optional()),
    dest_lat: z.number().optional(),
    dest_lon: z.number().optional(),
    dest_label: z.string().optional(),
    order_ids: z.array(z.number()),
    algorithm: z.enum(["ucs", "astar"]),
    return_to_depot: z.boolean(),
    allow_reload: z.boolean(),
    respect_time_windows: z.boolean(),
    include_fuel: z.boolean(),
    include_driver: z.boolean(),
    include_operating: z.boolean(),
    include_tolls: z.boolean(),
    value_of_time_per_hour: z.string().regex(/^\d*(\.\d+)?$/, "Enter a non-negative number").optional(),
    include_alternatives: z.boolean(),
    include_benchmarks: z.boolean(),
    trace: z.boolean(),
  })
  .superRefine((v, ctx) => {
    if (v.mode === "single") {
      if (v.dest_type === "order" && !v.delivery_order_id) ctx.addIssue({ code: "custom", path: ["delivery_order_id"], message: "Select a delivery order" });
      if (v.dest_type === "point" && (v.dest_lat === undefined || v.dest_lon === undefined))
        ctx.addIssue({ code: "custom", path: ["dest_label"], message: "Search an address or click the map" });
    } else if (v.order_ids.length === 0) {
      ctx.addIssue({ code: "custom", path: ["order_ids"], message: "Select at least one order" });
    }
  });

type FormValues = z.infer<typeof schema>;

const ALT_COLORS: Record<Objective, string> = { money: "#f45b1d", time: "#2563eb", distance: "#7c3aed", balanced: "#0d9488" };

export default function PlannerPage() {
  const [params] = useSearchParams();
  const settings = useSettings();
  const health = useHealth();
  const networks = useNetworks();
  const activeNet = networks.data?.find((n) => n.is_active);
  const warehouses = useWarehouses({ active: true });
  const vehicles = useVehicles({ active: true });
  const openOrders = useOrders({ status: ["pending", "planned"], page_size: 200, sort: "-created_at" });
  const [result, setResult] = useState<RoutePlan | null>(null);
  const [highlight, setHighlight] = useState<Objective | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [showPrefs, setShowPrefs] = useState(false);
  const [query, setQuery] = useState("");
  const [candidates, setCandidates] = useState<GeocodeCandidate[] | null>(null);
  const [geoMsg, setGeoMsg] = useState<string | null>(null);
  const [traceStep, setTraceStep] = useState(0);
  const [playing, setPlaying] = useState(false);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      mode: params.get("mode") === "multi" ? "multi" : "single", objective: "money", dest_type: "point", order_ids: [],
      algorithm: "ucs", return_to_depot: true, allow_reload: false, respect_time_windows: true,
      include_fuel: true, include_driver: true, include_operating: true, include_tolls: true,
      include_alternatives: true, include_benchmarks: true, trace: false,
    },
  });
  const { register, handleSubmit, watch, setValue, control, formState: { errors } } = form;
  const v = watch();

  // Apply workspace defaults once loaded.
  useEffect(() => {
    if (!settings.data) return;
    setValue("objective", settings.data.default_objective);
    setValue("include_fuel", settings.data.include_fuel);
    setValue("include_driver", settings.data.include_driver);
    setValue("include_operating", settings.data.include_operating);
    setValue("include_tolls", settings.data.include_tolls);
    setValue("value_of_time_per_hour", settings.data.value_of_time_per_hour);
    if (settings.data.default_vehicle_id) setValue("vehicle_id", settings.data.default_vehicle_id);
  }, [settings.data, setValue]);

  // Re-apply selections once option lists have loaded (native selects show the first option otherwise).
  useEffect(() => {
    const list = vehicles.data?.items;
    if (!list?.length) return;
    const current = Number(form.getValues("vehicle_id"));
    const pick = list.find((x) => x.id === current) ?? list.find((x) => x.id === settings.data?.default_vehicle_id) ?? list[0];
    setValue("vehicle_id", pick.id);
  }, [vehicles.data, settings.data, setValue, form]);
  useEffect(() => {
    const list = warehouses.data?.items.filter((w) => w.lat !== null);
    if (!list?.length) return;
    const current = Number(form.getValues("warehouse_id"));
    setValue("warehouse_id", (list.find((w) => w.id === current) ?? list[0]).id);
  }, [warehouses.data, setValue, form]);

  const calc = useAction(
    (body: { path: string; payload: Record<string, unknown> }) => api.post<RoutePlan>(body.path, body.payload),
    { invalidate: ["routes", "analytics"], silentError: true, onSuccess: (r) => { setResult(r); setError(null); setHighlight(null); setTraceStep(0); setPlaying(false); } },
  );

  const onSubmit = (f: FormValues) => {
    const preferences = {
      include_fuel: f.include_fuel, include_driver: f.include_driver, include_operating: f.include_operating,
      include_tolls: f.include_tolls, value_of_time_per_hour: f.value_of_time_per_hour || null,
    };
    setError(null);
    if (f.mode === "single") {
      calc.mutate({
        path: "/routes/calculate",
        payload: {
          warehouse_id: f.warehouse_id, vehicle_id: f.vehicle_id, objective: f.objective, preferences,
          include_alternatives: f.include_alternatives, include_benchmarks: f.include_benchmarks, trace: f.trace,
          ...(f.dest_type === "order"
            ? { delivery_order_id: f.delivery_order_id }
            : { destination: { lat: f.dest_lat, lon: f.dest_lon, label: f.dest_label } }),
        },
      }, { onError: (e) => setError(e) });
    } else {
      calc.mutate({
        path: "/routes/multi-stop",
        payload: {
          warehouse_id: f.warehouse_id, vehicle_id: f.vehicle_id, objective: f.objective, preferences,
          delivery_order_ids: f.order_ids, algorithm: f.algorithm, return_to_depot: f.return_to_depot,
          allow_reload: f.allow_reload, respect_time_windows: f.respect_time_windows,
        },
      }, { onError: (e) => setError(e) });
    }
  };

  const geocode = useAction((q: string) => api.get<{ status: string; message: string; candidates: GeocodeCandidate[] }>("/geocode/search", { q }), {
    onSuccess: (r) => { setCandidates(r.candidates); setGeoMsg(r.status === "ambiguous" ? "Several places match — pick the right one." : r.status === "failed" ? r.message : null); },
  });

  const pickPoint = (lat: number, lon: number, label: string) => {
    setValue("dest_type", "point");
    setValue("dest_lat", lat);
    setValue("dest_lon", lon);
    setValue("dest_label", label, { shouldValidate: true });
    setCandidates(null);
  };

  // Read-only demo: show a real, pre-computed showcase result for the current mode.
  useEffect(() => {
    if (!DEMO_MODE) return;
    let cancelled = false;
    showcasePlan(v.mode).then((p) => { if (!cancelled && p) { setResult(p); setTraceStep(0); setPlaying(false); } });
    return () => { cancelled = true; };
  }, [v.mode]);

  // UCS search animation
  const traceEvents = result?.trace?.events ?? [];
  const timer = useRef<number | null>(null);
  useEffect(() => {
    if (!playing) return;
    const stepSize = Math.max(1, Math.ceil(traceEvents.length / 240));
    timer.current = window.setInterval(() => {
      setTraceStep((s) => {
        if (s >= traceEvents.length) { setPlaying(false); return s; }
        return Math.min(traceEvents.length, s + stepSize);
      });
    }, 25);
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [playing, traceEvents.length]);

  const wh = warehouses.data?.items.find((w) => w.id === Number(v.warehouse_id));
  const selectedVehicle = vehicles.data?.items.find((x) => x.id === Number(v.vehicle_id));
  const orderList = openOrders.data?.items ?? [];
  const selectedLoad = orderList.filter((o) => v.order_ids.includes(o.id)).reduce((s, o) => s + o.weight_kg, 0);

  const mapRoutes = useMemo<MapRoute[]>(() => {
    if (!result) return [];
    const r: MapRoute[] = [];
    (result.alternatives ?? []).filter((a) => !a.same_route_as).forEach((a) => {
      r.push({ id: `alt-${a.objective}`, geometry: a.geometry, color: ALT_COLORS[a.objective], weight: highlight === a.objective ? 6 : 4,
        opacity: highlight === null || highlight === a.objective ? 0.65 : 0.2, dashed: highlight !== a.objective, label: OBJECTIVE_LABELS[a.objective],
        onClick: () => setHighlight(a.objective) });
    });
    r.push({ id: "main", geometry: result.geometry, color: ALT_COLORS[result.objective], weight: 6,
      opacity: highlight && highlight !== result.objective ? 0.35 : 0.95, label: `Selected: ${OBJECTIVE_LABELS[result.objective]}` });
    (result.access ?? []).forEach((a, i) => r.push({ id: `acc-${i}`, geometry: [a.from, a.to], color: "#64748b", weight: 2, dashed: true, label: `Access ${km(a.distance_m)} (not costed)` }));
    return r;
  }, [result, highlight]);

  const mapMarkers = useMemo<MapMarker[]>(() => {
    const m: MapMarker[] = [];
    if (result) {
      result.stops.forEach((s) => {
        if (s.kind === "reload" || s.kind === "return") return;
        m.push({ id: `s${s.sequence}`, lat: s.lat, lon: s.lon, label: s.label,
          kind: s.kind === "origin" ? "warehouse" : s.kind === "delivery" ? "delivery" : "destination",
          index: result.kind === "multi" && s.kind === "delivery" ? s.sequence : undefined });
      });
      return m;
    }
    if (wh?.lat != null && wh.lon != null) m.push({ id: "wh", lat: wh.lat, lon: wh.lon, label: wh.name, kind: "warehouse" });
    if (v.mode === "single" && v.dest_type === "point" && v.dest_lat !== undefined && v.dest_lon !== undefined)
      m.push({ id: "dest", lat: v.dest_lat, lon: v.dest_lon, label: v.dest_label ?? "Destination", kind: "destination" });
    if (v.mode === "single" && v.dest_type === "order") {
      const o = orderList.find((x) => x.id === Number(v.delivery_order_id));
      if (o?.lat != null && o.lon != null) m.push({ id: "o", lat: o.lat, lon: o.lon, label: o.reference, kind: "destination" });
    }
    if (v.mode === "multi") orderList.filter((o) => v.order_ids.includes(o.id) && o.lat != null).forEach((o) => m.push({ id: `o${o.id}`, lat: o.lat!, lon: o.lon!, label: o.reference, kind: "delivery" }));
    return m;
  }, [result, wh, v.mode, v.dest_type, v.dest_lat, v.dest_lon, v.dest_label, v.delivery_order_id, v.order_ids, orderList]);

  const noNetwork = health.data && !health.data.active_network;
  const fitKey = result ? `r${result.id}` : `${wh?.id}-${v.dest_lat}-${v.order_ids.length}-${activeNet?.id}`;

  return (
    <div className="relative flex flex-col lg:block lg:h-[calc(100vh-4rem)]">
      {/* Left panel */}
      <div className="order-2 w-full bg-card lg:absolute lg:bottom-4 lg:left-4 lg:top-4 lg:z-[450] lg:w-[420px] lg:overflow-y-auto lg:rounded-2xl lg:border lg:shadow-float">
        <form onSubmit={handleSubmit(onSubmit, (errs) => { const first = Object.values(errs)[0]; toast.error(first?.message ? String(first.message) : "Check the highlighted fields"); })} className="space-y-4 border-b p-4" noValidate>
          <div className="flex items-center justify-between">
            <div><p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">Uniform Cost Search</p><h1 className="text-xl font-semibold">Plan a route</h1></div>
            <Controller control={control} name="mode" render={({ field }) => (
              <Tabs value={field.value} onValueChange={(m) => { field.onChange(m); setResult(null); setError(null); }}>
                <TabsList>
                  <TabsTrigger value="single">Single</TabsTrigger>
                  <TabsTrigger value="multi">Multi-stop</TabsTrigger>
                </TabsList>
              </Tabs>
            )} />
          </div>

          {DEMO_MODE && (
            <Notice tone="warning">Read-only demo: below is a real result computed by RouteWise's UCS engine on the Delhi road network. Live calculation needs the full app.</Notice>
          )}
          {noNetwork && (
            <Notice tone="warning">No active road network. <Link to="/network" className="font-medium underline">Import one</Link> to calculate routes.</Notice>
          )}

          <Field label="Warehouse (origin)" htmlFor="wh" error={errors.warehouse_id?.message}>
            {warehouses.isLoading ? <Skeleton className="h-9" /> : (
              <Select id="wh" {...register("warehouse_id")} aria-invalid={!!errors.warehouse_id} defaultValue="">
                <option value="" disabled>Select warehouse…</option>
                {warehouses.data?.items.map((w) => (
                  <option key={w.id} value={w.id} disabled={w.lat === null}>{w.name}{w.lat === null ? ` (location ${w.geocode_status})` : ""}</option>
                ))}
              </Select>
            )}
            {warehouses.data?.items.length === 0 && <p className="text-xs text-muted-foreground">No warehouses yet — <Link className="underline" to="/deliveries?tab=warehouses">add one</Link>.</p>}
          </Field>

          {v.mode === "single" ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Destination</span>
                <div className="flex gap-1 text-xs">
                  <button type="button" className={cn("rounded px-2 py-0.5", v.dest_type === "point" ? "bg-accent text-accent-foreground" : "text-muted-foreground")} onClick={() => setValue("dest_type", "point")}>Address / map</button>
                  <button type="button" className={cn("rounded px-2 py-0.5", v.dest_type === "order" ? "bg-accent text-accent-foreground" : "text-muted-foreground")} onClick={() => setValue("dest_type", "order")}>Delivery order</button>
                </div>
              </div>
              {v.dest_type === "point" ? (
                <>
                  <div className="flex gap-2">
                    <Input placeholder="Search address…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search address"
                      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); if (query.trim().length >= 3) geocode.mutate(query); } }} />
                    <Button type="button" variant="outline" size="icon" onClick={() => geocode.mutate(query)} disabled={query.trim().length < 3} loading={geocode.isPending} aria-label="Search">
                      {!geocode.isPending && <Search />}
                    </Button>
                  </div>
                  {geoMsg && <p className="text-xs text-warning">{geoMsg}</p>}
                  {candidates && candidates.length > 0 && (
                    <ul className="max-h-44 divide-y overflow-y-auto rounded-md border text-xs">
                      {candidates.map((c, i) => (
                        <li key={i}><button type="button" className="w-full px-2.5 py-2 text-left hover:bg-muted" onClick={() => pickPoint(c.lat, c.lon, c.label.split(",").slice(0, 3).join(","))}>{c.label}</button></li>
                      ))}
                    </ul>
                  )}
                  {v.dest_lat !== undefined ? (
                    <div className="flex items-center justify-between rounded-md bg-muted px-2.5 py-1.5 text-xs">
                      <span className="flex min-w-0 items-center gap-1.5"><MapPin className="h-3.5 w-3.5 shrink-0 text-red-600" /><span className="truncate">{v.dest_label}</span></span>
                      <button type="button" aria-label="Clear destination" onClick={() => { setValue("dest_lat", undefined); setValue("dest_lon", undefined); setValue("dest_label", undefined); }}><X className="h-3.5 w-3.5" /></button>
                    </div>
                  ) : <p className="text-xs text-muted-foreground">…or click the map to drop a destination.</p>}
                  {errors.dest_label && <p className="text-xs text-destructive">{errors.dest_label.message}</p>}
                </>
              ) : (
                <Field label="Order" htmlFor="order" error={errors.delivery_order_id?.message}>
                  <Select id="order" {...register("delivery_order_id")} defaultValue="">
                    <option value="" disabled>Select order…</option>
                    {orderList.map((o) => (
                      <option key={o.id} value={o.id} disabled={!(o.geocode_status === "matched" || o.geocode_status === "manual")}>
                        {o.reference} · {o.customer_name} · {o.weight_kg} kg{o.geocode_status !== "matched" && o.geocode_status !== "manual" ? ` (address ${o.geocode_status})` : ""}
                      </option>
                    ))}
                  </Select>
                </Field>
              )}
            </div>
          ) : (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Delivery orders</span>
                <span className={cn("text-xs tabular", selectedVehicle && selectedLoad > selectedVehicle.max_payload_kg ? "text-warning" : "text-muted-foreground")}>
                  {v.order_ids.length} selected · {num(selectedLoad, 1)} kg{selectedVehicle ? ` / ${num(selectedVehicle.max_payload_kg)} kg` : ""}
                </span>
              </div>
              {openOrders.isLoading ? <Skeleton className="h-32" /> : orderList.length === 0 ? (
                <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">No pending orders. <Link className="underline" to="/deliveries">Create or import orders</Link>.</p>
              ) : (
                <Controller control={control} name="order_ids" render={({ field }) => (
                  <ul className="max-h-52 divide-y overflow-y-auto rounded-md border">
                    {orderList.map((o) => {
                      const ok = o.geocode_status === "matched" || o.geocode_status === "manual";
                      const checked = field.value.includes(o.id);
                      return (
                        <li key={o.id}>
                          <label className={cn("flex items-center gap-2 px-2.5 py-1.5 text-xs", ok ? "cursor-pointer hover:bg-muted" : "opacity-50")}>
                            <input type="checkbox" disabled={!ok} checked={checked} className="accent-[hsl(var(--primary))]"
                              onChange={() => field.onChange(checked ? field.value.filter((x) => x !== o.id) : [...field.value, o.id])} />
                            <span className="font-medium">{o.reference}</span>
                            <span className="truncate text-muted-foreground">{o.customer_name}</span>
                            <span className="ml-auto shrink-0 tabular text-muted-foreground">{o.weight_kg} kg</span>
                            {o.window_end && <Badge tone="info">window</Badge>}
                          </label>
                        </li>
                      );
                    })}
                  </ul>
                )} />
              )}
              {errors.order_ids && <p className="text-xs text-destructive">{errors.order_ids.message}</p>}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <Field label="Vehicle" htmlFor="veh" error={errors.vehicle_id?.message}>
              <Select id="veh" {...register("vehicle_id")} defaultValue="">
                <option value="" disabled>Select…</option>
                {vehicles.data?.items.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
              </Select>
            </Field>
            <Field label="Optimise for" htmlFor="obj">
              <Select id="obj" {...register("objective")}>
                {(["money", "time", "distance", "balanced"] as const).map((o) => <option key={o} value={o}>{OBJECTIVE_LABELS[o]}</option>)}
              </Select>
            </Field>
          </div>
          {vehicles.data?.items.length === 0 && <p className="text-xs text-muted-foreground">No vehicles — <Link className="underline" to="/fleet">add one in Fleet</Link>.</p>}
          {v.objective === "balanced" && (
            <Notice>Balanced minimises <b>monetary cost + value of time × hours</b>. It is a trade-off score, not the cheapest monetary route.</Notice>
          )}

          {v.mode === "multi" && (
            <div className="grid grid-cols-2 gap-x-3 gap-y-2">
              <Field label="Search algorithm" htmlFor="alg">
                <Select id="alg" {...register("algorithm")}>
                  <option value="ucs">UCS (exact)</option>
                  <option value="astar">A* (exact, admissible bound)</option>
                </Select>
              </Field>
              <div className="space-y-1.5 pt-5">
                <Checkbox label="Return to warehouse" {...register("return_to_depot")} />
                <Checkbox label="Allow reload trips" {...register("allow_reload")} />
                <Checkbox label="Respect time windows" {...register("respect_time_windows")} />
              </div>
            </div>
          )}

          <div className="rounded-md border">
            <button type="button" className="flex w-full items-center justify-between px-3 py-2 text-xs font-medium" onClick={() => setShowPrefs((s) => !s)} aria-expanded={showPrefs}>
              Cost preferences & output
              <ChevronDown className={cn("h-4 w-4 transition-transform", showPrefs && "rotate-180")} />
            </button>
            {showPrefs && (
              <div className="grid grid-cols-2 gap-2 border-t px-3 py-3">
                <Checkbox label="Fuel / energy" {...register("include_fuel")} />
                <Checkbox label="Driver time" {...register("include_driver")} />
                <Checkbox label="Operating cost" {...register("include_operating")} />
                <Checkbox label="Tolls" {...register("include_tolls")} />
                <Field label={`Value of time (${settings.data?.currency ?? "INR"}/h)`} htmlFor="vot" className="col-span-2" error={errors.value_of_time_per_hour?.message}>
                  <Input id="vot" inputMode="decimal" {...register("value_of_time_per_hour")} />
                </Field>
                {v.mode === "single" && (
                  <>
                    <Checkbox label="Alternatives" {...register("include_alternatives")} />
                    <Checkbox label="A* / greedy benchmark" {...register("include_benchmarks")} />
                    <Checkbox label="Record UCS trace" className="col-span-2" {...register("trace")} />
                  </>
                )}
              </div>
            )}
          </div>

          <Button type="submit" size="lg" className="w-full" loading={calc.isPending} disabled={!!noNetwork || DEMO_MODE} title={DEMO_MODE ? "Not available in the read-only demo" : undefined}>
            {!calc.isPending && <Calculator />} {calc.isPending ? "Searching road network…" : DEMO_MODE ? "Calculate route (full app only)" : "Calculate route"}
          </Button>
        </form>

        <div className="p-4">
          {calc.isPending ? (
            <div className="space-y-3" role="status" aria-label="Calculating"><Skeleton className="h-16" /><Skeleton className="h-40" /></div>
          ) : error ? (
            <ErrorPanel error={error} />
          ) : result ? (
            <ResultPanel plan={result} onChange={setResult} highlight={highlight} setHighlight={setHighlight}
              traceStep={traceStep} setTraceStep={setTraceStep} playing={playing} setPlaying={setPlaying} />
          ) : (
            <EmptyState icon={RouteIcon} title="No route yet" description="Choose a warehouse, destination and vehicle, then calculate. RouteWise searches the road graph with Uniform Cost Search." />
          )}
        </div>
      </div>

      {/* Map */}
      <div className="relative order-1 h-[45vh] lg:absolute lg:inset-0 lg:h-auto">
        <RouteMap
          className="h-full w-full"
          routes={mapRoutes}
          markers={mapMarkers}
          trace={traceStep ? traceEvents.slice(0, traceStep) : []}
          fitKey={fitKey}
          fallbackBounds={activeNet ? [activeNet.south, activeNet.west, activeNet.north, activeNet.east] : null}
          onClick={v.mode === "single" && !result && !DEMO_MODE ? (lat, lon) => pickPoint(lat, lon, `${lat.toFixed(5)}, ${lon.toFixed(5)}`) : undefined}
        />
        {result && (
          <div className="pointer-events-none absolute bottom-6 right-3 z-[400] rounded-xl border bg-card/95 px-3 py-2 text-[11px] shadow-float">
            <p className="font-medium">Legend</p>
            {[result.objective, ...(result.alternatives ?? []).filter((a) => !a.same_route_as).map((a) => a.objective)].map((o) => (
              <p key={o} className="flex items-center gap-1.5"><span className="h-0.5 w-4" style={{ background: ALT_COLORS[o] }} />{OBJECTIVE_LABELS[o]}{o === result.objective && " (selected)"}</p>
            ))}
            {traceStep > 0 && <p className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-[#14161b] dark:bg-white" />UCS expanded node</p>}
          </div>
        )}
      </div>
    </div>
  );
}

function ErrorPanel({ error }: { error: unknown }) {
  const code = error instanceof ApiError ? error.code : "";
  const hint: Record<string, string> = {
    no_route: "Try removing a road closure, choosing a different vehicle (weight/height limits), or another destination.",
    outside_coverage: "Import a road network that covers this location on the Road Network page.",
    capacity_exceeded: "Choose a vehicle with more payload or split the order.",
    plan_infeasible: "Enable reload trips, pick a larger vehicle, relax time windows or remove stops.",
    missing_energy_price: "Set the fuel/energy price in Settings or on the vehicle.",
    no_network: "Import and activate a road network first.",
    location_unresolved: "Resolve the address location in Deliveries.",
  };
  return (
    <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm">
      <p className="font-medium text-destructive">Route could not be calculated</p>
      <p className="mt-1 text-xs">{errorMessage(error)}</p>
      {hint[code] && <p className="mt-2 text-xs text-muted-foreground">{hint[code]}</p>}
    </div>
  );
}

function ResultPanel({ plan, onChange, highlight, setHighlight, traceStep, setTraceStep, playing, setPlaying }: {
  plan: RoutePlan; onChange: (p: RoutePlan) => void; highlight: Objective | null; setHighlight: (o: Objective | null) => void;
  traceStep: number; setTraceStep: (n: number) => void; playing: boolean; setPlaying: (b: boolean) => void;
}) {
  const stats = plan.kind === "single" ? (plan.search_stats as Record<string, number>) : ((plan.search_stats as { plan: Record<string, number> }).plan ?? {});
  const matrix = plan.kind === "multi" ? (plan.search_stats as { matrix: Record<string, number> }).matrix : null;
  const events = plan.trace?.events ?? [];
  return (
    <div className="space-y-4">
      <PlanActions plan={plan} onChanged={onChange} />
      <RouteHeadline plan={plan} />
      <Warnings plan={plan} />
      <Tabs defaultValue="cost">
        <TabsList className="w-full justify-start overflow-x-auto">
          <TabsTrigger value="cost">Cost</TabsTrigger>
          <TabsTrigger value="route">{plan.kind === "multi" ? "Stops" : "Directions"}</TabsTrigger>
          <TabsTrigger value="compare">Compare</TabsTrigger>
          <TabsTrigger value="algo">Search</TabsTrigger>
          <TabsTrigger value="assume">Assumptions</TabsTrigger>
        </TabsList>
        <TabsContent value="cost" className="pt-3">
          <CostBreakdown breakdown={plan.breakdown} currency={plan.currency} />
          {Object.keys(plan.breakdown.toll_km ?? {}).length > 0 && (
            <div className="mt-3 text-xs text-muted-foreground">
              Toll data coverage: {Object.entries(plan.breakdown.toll_km).map(([k, val]) => `${k.replace("_", " ")} ${val} km`).join(" · ")}
            </div>
          )}
        </TabsContent>
        <TabsContent value="route" className="pt-3">
          {plan.kind === "multi" ? <StopsList plan={plan} /> : (
            <>
              <p className="mb-2 text-xs text-muted-foreground">{plan.node_count} road-network nodes · {plan.named_segments?.length ?? 0} named segments</p>
              <ol className="divide-y rounded-md border text-sm">
                {(plan.named_segments ?? []).map((s, i) => (
                  <li key={i} className="flex items-center justify-between gap-2 px-3 py-1.5">
                    <span className="min-w-0 truncate"><span className="mr-2 text-xs text-muted-foreground tabular">{i + 1}.</span>{s.name}{s.toll === "yes" && <Badge tone="warning" className="ml-1">toll</Badge>}</span>
                    <span className="shrink-0 text-xs text-muted-foreground tabular">{km(s.distance_m)} · {duration(s.duration_s)} · {money(s.cost, plan.currency)}</span>
                  </li>
                ))}
              </ol>
            </>
          )}
        </TabsContent>
        <TabsContent value="compare" className="pt-3">
          {plan.kind === "single" ? (
            <>
              <p className="mb-2 text-xs text-muted-foreground">Each alternative is the optimal route for a different objective on the same network and cost settings. They are not ranked second-best routes.</p>
              <Table>
                <THead><TR><TH>Objective</TH><TH className="text-right">Distance</TH><TH className="text-right">Time</TH><TH className="text-right">Cost</TH></TR></THead>
                <TBody>
                  {[{ objective: plan.objective, distance_m: plan.distance_m, duration_s: plan.duration_s, total_cost: plan.total_cost, same_route_as: null as string | null }, ...(plan.alternatives ?? [])].map((a) => (
                    <TR key={a.objective} className={cn("cursor-pointer", highlight === a.objective && "bg-accent")} onClick={() => setHighlight(highlight === a.objective ? null : a.objective)}>
                      <TD className="text-xs">
                        <span className="mr-1.5 inline-block h-2 w-2 rounded-full" style={{ background: ALT_COLORS[a.objective] }} />
                        {OBJECTIVE_LABELS[a.objective]}{a.objective === plan.objective && <Badge tone="info" className="ml-1">selected</Badge>}
                        {a.same_route_as && <span className="block text-[10px] text-muted-foreground">same route as {a.same_route_as}</span>}
                      </TD>
                      <TD className="text-right text-xs tabular">{km(a.distance_m)}</TD>
                      <TD className="text-right text-xs tabular">{duration(a.duration_s)}</TD>
                      <TD className="text-right text-xs tabular">{money(a.total_cost, plan.currency)}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </>
          ) : plan.baseline ? (
            <div className="space-y-2 text-sm">
              <KV k="Exact plan" v={money(plan.total_cost, plan.currency)} />
              <KV k="Nearest-neighbour baseline" v={money(plan.baseline.total_cost, plan.currency)} />
              {plan.baseline.order && <p className="text-xs text-muted-foreground">Baseline order: {plan.baseline.order.join(" → ")}</p>}
              <Notice tone={plan.baseline.comparable ? "info" : "warning"}>{plan.baseline.note}</Notice>
            </div>
          ) : <p className="text-xs text-muted-foreground">No baseline available.</p>}
        </TabsContent>
        <TabsContent value="algo" className="space-y-3 pt-3">
          <div className="grid grid-cols-2 gap-x-4 text-sm">
            {plan.kind === "single" ? (
              <>
                <KV k="Expanded nodes" v={num(stats.expanded_nodes)} />
                <KV k="Relaxations" v={num(stats.relaxations)} />
                <KV k="Queue operations" v={num(stats.queue_operations)} />
                <KV k="Stale entries skipped" v={num(stats.stale_skipped)} />
                <KV k="Closed edges skipped" v={num(stats.blocked_edges_skipped)} />
                <KV k="Restricted edges" v={num(stats.restricted_edges_skipped)} />
                <KV k="Peak frontier" v={num(stats.max_frontier_size)} />
                <KV k="Search time" v={`${num(stats.duration_ms, 1)} ms`} />
              </>
            ) : (
              <>
                <KV k="Leg-matrix UCS runs" v={num(matrix?.ucs_runs)} />
                <KV k="Matrix nodes expanded" v={num(matrix?.expanded_nodes)} />
                <KV k="Plan states expanded" v={num(stats.expanded_states)} />
                <KV k="States generated" v={num(stats.generated_states)} />
                <KV k="States pruned" v={num(stats.pruned_states)} />
                <KV k="Peak frontier" v={num(stats.peak_frontier)} />
                <KV k="Plan search time" v={`${num(stats.duration_ms, 1)} ms`} />
                <KV k="State-space bound" v={num(stats.state_space_upper_bound)} />
              </>
            )}
          </div>
          {plan.benchmarks && (
            <div>
              <p className="mb-1 text-xs font-medium">Benchmark on the same network and cost settings</p>
              <Table>
                <THead><TR><TH>Algorithm</TH><TH className="text-right">Expanded</TH><TH className="text-right">ms</TH><TH className="text-right">Cost</TH></TR></THead>
                <TBody>
                  {plan.benchmarks.map((b) => (
                    <TR key={b.algorithm}>
                      <TD className="text-xs">{b.label}<span className="block text-[10px] text-muted-foreground">{b.optimality}{b.algorithm === "astar" && b.matches_ucs_cost !== undefined && (b.matches_ucs_cost ? " · matches UCS" : " · differs from UCS")}</span></TD>
                      <TD className="text-right text-xs tabular">{num(b.expanded_nodes)}</TD>
                      <TD className="text-right text-xs tabular">{num(b.duration_ms, 1)}</TD>
                      <TD className="text-right text-xs tabular">{money(b.total_cost, plan.currency)}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
              {plan.benchmarks.find((b) => b.heuristic && b.algorithm === "astar") && (
                <p className="mt-1 text-[10px] text-muted-foreground">A* heuristic: {plan.benchmarks.find((b) => b.algorithm === "astar")?.heuristic}</p>
              )}
            </div>
          )}
          {events.length > 0 ? (
            <div className="rounded-md border p-3">
              <p className="text-xs font-medium">UCS expansion order</p>
              <p className="mb-2 text-[11px] text-muted-foreground">Nodes popped from the priority queue in non-decreasing cumulative cost. {plan.trace?.truncated && "Trace truncated at the recording limit."}</p>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" type="button" onClick={() => { if (traceStep >= events.length) setTraceStep(0); setPlaying(!playing); }}>
                  {playing ? <Pause /> : <Play />}{playing ? "Pause" : traceStep ? "Resume" : "Animate"}
                </Button>
                <input type="range" min={0} max={events.length} value={traceStep} onChange={(e) => { setPlaying(false); setTraceStep(Number(e.target.value)); }} className="flex-1 accent-[hsl(var(--primary))]" aria-label="Search step" />
              </div>
              <p className="mt-1 text-[11px] tabular text-muted-foreground">
                Step {num(traceStep)} / {num(events.length)}{traceStep > 0 && ` · g(n) = ${events[Math.min(traceStep, events.length) - 1].c.toFixed(2)}`}
              </p>
            </div>
          ) : plan.kind === "single" && <p className="text-xs text-muted-foreground">Enable “Record UCS trace” under Cost preferences to visualise the search.</p>}
        </TabsContent>
        <TabsContent value="assume" className="pt-3"><Assumptions plan={plan} /></TabsContent>
      </Tabs>
    </div>
  );
}

