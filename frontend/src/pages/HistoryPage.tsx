import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ClipboardCheck, Download, GitCompare, History, RefreshCw, Trash2, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, Sheet } from "@/components/ui/dialog";
import { EmptyState, ErrorState, Notice, Skeleton, TableSkeleton } from "@/components/ui/feedback";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { KV, PageHeader, Pagination } from "@/components/ui/misc";
import { SortTH, Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { StatusBadge } from "@/components/StatusBadge";
import { RouteMap } from "@/components/map/RouteMap";
import { Assumptions, CostBreakdown, PlanActions, RouteHeadline, StopsList, Warnings } from "@/features/RouteDetails";
import { useAction, useRoute, useRoutes, useVehicles } from "@/hooks/queries";
import { api, downloadUrl } from "@/services/api";
import type { RoutePlan } from "@/types/api";
import { dateTime, duration, km, money, OBJECTIVE_LABELS } from "@/utils/format";

export default function HistoryPage() {
  const [params, setParams] = useSearchParams();
  const openId = params.get("plan") ? Number(params.get("plan")) : null;
  const [f, setF] = useState({ q: "", status: "", kind: "", vehicle_id: "", date_from: "", date_to: "" });
  const [sort, setSort] = useState("-created_at");
  const [page, setPage] = useState(1);
  const [compare, setCompare] = useState<number[]>([]);
  const [compareOpen, setCompareOpen] = useState(false);
  const vehicles = useVehicles();
  const routes = useRoutes({ ...f, status: f.status ? [f.status] : undefined, sort, page, page_size: 20 });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { setF({ ...f, [k]: e.target.value }); setPage(1); };
  const items = routes.data?.items ?? [];

  return (
    <>
      <PageHeader title="Route History" description="Every calculation is stored with its cost settings, network revision and route snapshot. Estimated costs are labelled separately from recorded actuals."
        actions={<>
          {compare.length >= 2 && <Button variant="outline" onClick={() => setCompareOpen(true)}><GitCompare /> Compare {compare.length}</Button>}
          <Button variant="outline" asChild><a href={downloadUrl("/routes/export.csv", { status: f.status ? [f.status] : undefined })} download><Download /> Export CSV</a></Button>
        </>} />
      <Card>
        <div className="flex flex-wrap items-end gap-2 border-b p-3">
          <Input placeholder="Search name…" value={f.q} onChange={set("q")} className="w-52" aria-label="Search plans" />
          <Select value={f.status} onChange={set("status")} className="w-36" aria-label="Status">
            <option value="">All statuses</option>{["estimated", "saved", "dispatched", "completed", "superseded"].map((s) => <option key={s}>{s}</option>)}
          </Select>
          <Select value={f.kind} onChange={set("kind")} className="w-32" aria-label="Type"><option value="">All types</option><option value="single">Single</option><option value="multi">Multi-stop</option></Select>
          <Select value={f.vehicle_id} onChange={set("vehicle_id")} className="w-40" aria-label="Vehicle">
            <option value="">All vehicles</option>{vehicles.data?.items.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
          </Select>
          <Input type="date" value={f.date_from} onChange={set("date_from")} className="w-36" aria-label="From date" />
          <Input type="date" value={f.date_to} onChange={set("date_to")} className="w-36" aria-label="To date" />
        </div>
        {routes.isLoading ? <TableSkeleton /> : routes.isError ? <ErrorState error={routes.error} onRetry={() => routes.refetch()} /> : items.length === 0 ? (
          <EmptyState icon={History} title="No route plans" description="Routes appear here after you calculate them in the planner." />
        ) : (
          <>
            <Table>
              <THead>
                <TR>
                  <TH className="w-8"><span className="sr-only">Compare</span></TH>
                  <SortTH field="name" sort={sort} onSort={setSort}>Plan</SortTH>
                  <TH>Status</TH><TH>Objective</TH><TH>Vehicle</TH>
                  <SortTH field="distance_m" sort={sort} onSort={setSort} className="text-right">Distance</SortTH>
                  <SortTH field="total_cost" sort={sort} onSort={setSort} className="text-right">Est. cost</SortTH>
                  <TH className="text-right">Actual</TH>
                  <SortTH field="created_at" sort={sort} onSort={setSort}>Calculated</SortTH>
                </TR>
              </THead>
              <TBody>
                {items.map((p) => (
                  <TR key={p.id} className="cursor-pointer" onClick={() => setParams({ plan: String(p.id) })}>
                    <TD onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" aria-label={`Compare plan ${p.id}`} checked={compare.includes(p.id)} disabled={!compare.includes(p.id) && compare.length >= 5}
                        onChange={(e) => setCompare(e.target.checked ? [...compare, p.id] : compare.filter((x) => x !== p.id))} />
                    </TD>
                    <TD className="max-w-[260px]"><p className="truncate font-medium">{p.name}</p><p className="text-[11px] capitalize text-muted-foreground">#{p.id} · {p.kind}{p.parent_plan_id && ` · from #${p.parent_plan_id}`}</p></TD>
                    <TD><StatusBadge status={p.status} /></TD>
                    <TD className="text-xs">{OBJECTIVE_LABELS[p.objective]}</TD>
                    <TD className="text-xs">{p.vehicle?.name ?? "—"}</TD>
                    <TD className="text-right tabular">{km(p.distance_m)}</TD>
                    <TD className="text-right tabular">{money(p.total_cost, p.currency)}</TD>
                    <TD className="text-right tabular">{p.actual ? money(p.actual.total_cost, p.currency) : <span className="text-muted-foreground">—</span>}</TD>
                    <TD className="whitespace-nowrap text-xs text-muted-foreground">{dateTime(p.created_at)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            <Pagination page={page} pageSize={20} total={routes.data?.total ?? 0} onPage={setPage} />
          </>
        )}
      </Card>
      <Sheet open={openId !== null} onOpenChange={(o) => !o && setParams({})} side="right" title="Route plan details">
        {openId !== null && <PlanDrawer id={openId} onClose={() => setParams({})} onOpen={(id) => setParams({ plan: String(id) })} />}
      </Sheet>
      <CompareDialog ids={compare} open={compareOpen} onOpenChange={setCompareOpen} />
    </>
  );
}

function PlanDrawer({ id, onClose, onOpen }: { id: number; onClose: () => void; onOpen: (id: number) => void }) {
  const q = useRoute(id);
  const [actualOpen, setActualOpen] = useState(false);
  const reroute = useAction(() => api.post<{ outcome: string; new_plan_id: number | null; message: string }>(`/routes/${id}/reroute`), {
    invalidate: ["routes", "route"], success: (r) => r.message, onSuccess: (r) => r.new_plan_id && onOpen(r.new_plan_id),
  });
  const del = useAction(() => api.del(`/routes/${id}`), { invalidate: ["routes", "analytics"], success: "Plan deleted", onSuccess: onClose });
  if (q.isLoading) return <div className="space-y-3 p-5"><Skeleton className="h-8" /><Skeleton className="h-60" /><Skeleton className="h-40" /></div>;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const p = q.data!;
  return (
    <div className="space-y-4 p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0"><h2 className="truncate text-base font-semibold">{p.name}</h2>
          <p className="text-xs text-muted-foreground">#{p.id} · {p.kind === "multi" ? "Multi-stop" : "Single route"} · {p.algorithm.toUpperCase()} · calculated {dateTime(p.created_at)}</p></div>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close"><X /></Button>
      </div>
      <PlanActions plan={p} onChanged={() => q.refetch()} />
      <div className="flex flex-wrap gap-2">
        {p.status === "dispatched" && <Button size="sm" onClick={() => setActualOpen(true)}><ClipboardCheck /> Record actual outcome</Button>}
        {["saved", "dispatched"].includes(p.status) && <Button size="sm" variant="outline" onClick={() => reroute.mutate(undefined)} loading={reroute.isPending}><RefreshCw /> Recalculate on current network</Button>}
        {["estimated", "superseded"].includes(p.status) && <Button size="sm" variant="ghost" onClick={() => confirm("Delete this plan?") && del.mutate(undefined)}><Trash2 /> Delete</Button>}
      </div>
      <RouteMap className="h-64 overflow-hidden rounded-xl border" routes={[{ id: "r", geometry: p.geometry, color: "#f45b1d" }]} fitKey={`h${p.id}`}
        markers={p.stops.filter((s) => s.kind !== "reload" && s.kind !== "return").map((s) => ({ id: `s${s.sequence}`, lat: s.lat, lon: s.lon, label: s.label,
          kind: s.kind === "origin" ? "warehouse" : s.kind === "delivery" ? "delivery" : "destination", index: p.kind === "multi" && s.kind === "delivery" ? s.sequence : undefined }))} />
      <RouteHeadline plan={p} />
      <Warnings plan={p} />
      {p.actual ? (
        <div className="rounded-md border p-3">
          <p className="mb-1 flex items-center gap-2 text-sm font-medium">Recorded actual <Badge tone="success">actual</Badge></p>
          <KV k="Total" v={money(p.actual.total_cost, p.currency)} />
          <KV k="vs. estimate" v={money(Number(p.actual.total_cost) - Number(p.total_cost), p.currency)} />
          {p.actual.distance_km !== null && <KV k="Distance driven" v={`${p.actual.distance_km} km`} />}
          {p.actual.duration_min !== null && <KV k="Duration" v={`${p.actual.duration_min} min`} />}
          <KV k="Deliveries" v={`${p.actual.deliveries_completed} completed · ${p.actual.deliveries_failed} failed`} />
          {p.actual.notes && <p className="mt-1 text-xs text-muted-foreground">{p.actual.notes}</p>}
        </div>
      ) : p.status !== "completed" && <Notice>Costs shown are estimates. No actual delivery outcome has been recorded for this plan.</Notice>}
      {(p.reroutes ?? []).length > 0 && (
        <div className="rounded-md border p-3 text-xs">
          <p className="mb-1 text-sm font-medium">Rerouting events</p>
          {p.reroutes!.map((e) => (
            <p key={e.id} className="py-0.5">{dateTime(e.created_at)} · {e.original_plan_id === p.id ? (e.new_plan_id ? <>replaced by <button className="underline" onClick={() => onOpen(e.new_plan_id!)}>#{e.new_plan_id}</button></> : "no alternative") : <>replaced <button className="underline" onClick={() => onOpen(e.original_plan_id)}>#{e.original_plan_id}</button></>} — {e.message}</p>
          ))}
        </div>
      )}
      <div><p className="mb-2 text-sm font-medium">Cost breakdown</p><CostBreakdown breakdown={p.breakdown} currency={p.currency} /></div>
      <div><p className="mb-2 text-sm font-medium">Stops</p><StopsList plan={p} /></div>
      <div className="text-xs text-muted-foreground">Network #{p.network_id} revision {p.network_revision} · {p.edges?.length ?? 0} road segments in snapshot</div>
      <Assumptions plan={p} />
      <ActualDialog plan={p} open={actualOpen} onOpenChange={setActualOpen} />
    </div>
  );
}

const money2 = z.string().trim().regex(/^(\d+(\.\d{1,2})?)?$/, "Amount with up to 2 decimals");
const actualSchema = z.object({
  fuel_cost: money2, toll_cost: money2, other_cost: money2, total_cost: money2,
  distance_km: z.string().regex(/^(\d+(\.\d+)?)?$/, "Number"), duration_min: z.string().regex(/^(\d+(\.\d+)?)?$/, "Number"),
  deliveries_completed: z.coerce.number().int().min(0), deliveries_failed: z.coerce.number().int().min(0), notes: z.string().optional(),
}).refine((v) => v.total_cost || v.fuel_cost || v.toll_cost || v.other_cost, { path: ["total_cost"], message: "Enter the total or at least one component" });

function ActualDialog({ plan, open, onOpenChange }: { plan: RoutePlan; open: boolean; onOpenChange: (o: boolean) => void }) {
  const deliveries = plan.kind === "multi" ? plan.stops.filter((s) => s.kind === "delivery").length : 1;
  const form = useForm<z.infer<typeof actualSchema>>({ resolver: zodResolver(actualSchema), values: {
    fuel_cost: "", toll_cost: "", other_cost: "", total_cost: "", distance_km: "", duration_min: "", deliveries_completed: deliveries, deliveries_failed: 0, notes: "" } });
  const e = form.formState.errors;
  const save = useAction((f: z.infer<typeof actualSchema>) => api.post(`/routes/${plan.id}/actual`, {
    fuel_cost: f.fuel_cost || null, toll_cost: f.toll_cost || null, other_cost: f.other_cost || null, total_cost: f.total_cost || null,
    distance_km: f.distance_km ? Number(f.distance_km) : null, duration_min: f.duration_min ? Number(f.duration_min) : null,
    deliveries_completed: f.deliveries_completed, deliveries_failed: f.deliveries_failed, notes: f.notes || null,
  }), { invalidate: ["routes", "route", "analytics", "orders"], success: "Actual outcome recorded", onSuccess: () => onOpenChange(false) });
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Record actual delivery outcome" description="Only these recorded values are reported as actual expenditure. If total is blank it is the sum of the components."
      footer={<Button onClick={form.handleSubmit((f) => save.mutate(f))} loading={save.isPending}>Save & complete plan</Button>}>
      <div className="grid grid-cols-2 gap-3">
        <Field label={`Fuel cost (${plan.currency})`} htmlFor="a-f" error={e.fuel_cost?.message}><Input id="a-f" inputMode="decimal" {...form.register("fuel_cost")} /></Field>
        <Field label="Toll cost" htmlFor="a-t" error={e.toll_cost?.message}><Input id="a-t" inputMode="decimal" {...form.register("toll_cost")} /></Field>
        <Field label="Other cost" htmlFor="a-o" error={e.other_cost?.message}><Input id="a-o" inputMode="decimal" {...form.register("other_cost")} /></Field>
        <Field label="Total cost" htmlFor="a-tot" error={e.total_cost?.message}><Input id="a-tot" inputMode="decimal" {...form.register("total_cost")} /></Field>
        <Field label="Distance driven (km)" htmlFor="a-d" error={e.distance_km?.message}><Input id="a-d" inputMode="decimal" {...form.register("distance_km")} /></Field>
        <Field label="Duration (min)" htmlFor="a-du" error={e.duration_min?.message}><Input id="a-du" inputMode="decimal" {...form.register("duration_min")} /></Field>
        <Field label="Deliveries completed" htmlFor="a-c"><Input id="a-c" inputMode="numeric" {...form.register("deliveries_completed")} /></Field>
        <Field label="Deliveries failed" htmlFor="a-fl"><Input id="a-fl" inputMode="numeric" {...form.register("deliveries_failed")} /></Field>
        <Field label="Notes" htmlFor="a-n" className="col-span-2"><Textarea id="a-n" {...form.register("notes")} /></Field>
      </div>
    </Dialog>
  );
}

function CompareDialog({ ids, open, onOpenChange }: { ids: number[]; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [data, setData] = useState<{ plans: RoutePlan[]; notes: string[] } | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    if (!open) return;
    setData(null);
    setErr(null);
    api.get<{ plans: RoutePlan[]; notes: string[] }>("/routes/compare", { ids }).then(setData).catch(setErr);
  }, [open, ids]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Compare route plans" className="max-w-4xl">
      {err ? <ErrorState error={err} /> : !data ? <Skeleton className="h-40" /> : (
        <>
          {data.notes.map((n) => <Notice key={n} tone="warning" className="mb-2">{n}</Notice>)}
          <Table>
            <THead><TR><TH>Metric</TH>{data.plans.map((p) => <TH key={p.id} className="text-right">#{p.id}</TH>)}</TR></THead>
            <TBody>
              {([
                ["Name", (p: RoutePlan) => p.name],
                ["Status", (p: RoutePlan) => <StatusBadge status={p.status} />],
                ["Objective", (p: RoutePlan) => OBJECTIVE_LABELS[p.objective]],
                ["Vehicle", (p: RoutePlan) => p.vehicle?.name],
                ["Distance", (p: RoutePlan) => km(p.distance_m)],
                ["Duration", (p: RoutePlan) => duration(p.duration_s)],
                ["Fuel", (p: RoutePlan) => money(p.breakdown.fuel, p.currency)],
                ["Driver", (p: RoutePlan) => money(p.breakdown.driver, p.currency)],
                ["Operating", (p: RoutePlan) => money(p.breakdown.operating, p.currency)],
                ["Toll", (p: RoutePlan) => money(p.breakdown.toll, p.currency)],
                ["Fixed", (p: RoutePlan) => money(p.breakdown.fixed, p.currency)],
                ["Estimated total", (p: RoutePlan) => <b>{money(p.total_cost, p.currency)}</b>],
                ["Actual total", (p: RoutePlan) => (p.actual ? money(p.actual.total_cost, p.currency) : "—")],
                ["Network revision", (p: RoutePlan) => `#${p.network_id} r${p.network_revision}`],
                ["Calculated", (p: RoutePlan) => dateTime(p.created_at)],
              ] as [string, (p: RoutePlan) => React.ReactNode][]).map(([label, fn]) => (
                <TR key={label}><TD className="text-xs text-muted-foreground">{label}</TD>{data.plans.map((p) => <TD key={p.id} className="text-right text-xs tabular">{fn(p)}</TD>)}</TR>
              ))}
            </TBody>
          </Table>
        </>
      )}
    </Dialog>
  );
}
