import { AlertTriangle, CheckCircle2, Clock, Download, Copy, Printer, Save, Send } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/feedback";
import { KV } from "@/components/ui/misc";
import { StatusBadge } from "@/components/StatusBadge";
import { useAction } from "@/hooks/queries";
import { api, downloadUrl } from "@/services/api";
import type { Breakdown, RoutePlan } from "@/types/api";
import { cn, dateTime, duration, km, money, num, OBJECTIVE_LABELS } from "@/utils/format";

const COMPONENTS: { key: keyof Breakdown; label: string; color: string }[] = [
  { key: "fuel", label: "Fuel / energy", color: "bg-[#f45b1d]" },
  { key: "driver", label: "Driver", color: "bg-[#14161b] dark:bg-stone-200" },
  { key: "operating", label: "Operating", color: "bg-[#2563eb]" },
  { key: "toll", label: "Tolls", color: "bg-[#eab308]" },
  { key: "extra", label: "Surcharges", color: "bg-[#db2777]" },
  { key: "fixed", label: "Fixed per trip", color: "bg-stone-400" },
];

export function CostBreakdown({ breakdown, currency }: { breakdown: Breakdown; currency: string }) {
  const total = Number(breakdown.total) || 0;
  const parts = COMPONENTS.map((c) => ({ ...c, value: Number(breakdown[c.key] ?? 0) }));
  const enabled = breakdown.components_enabled ?? {};
  return (
    <div>
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted" aria-hidden>
        {total > 0 && parts.map((p) => p.value > 0 && <div key={p.key} className={p.color} style={{ width: `${(p.value / total) * 100}%` }} />)}
      </div>
      <dl className="mt-3 divide-y text-sm">
        {parts.map((p) => {
          const disabled = (p.key === "fuel" && enabled.fuel === false) || (p.key === "driver" && enabled.driver === false) ||
            (p.key === "operating" && enabled.operating === false) || (p.key === "toll" && enabled.tolls === false);
          if (p.value === 0 && !["fuel", "toll"].includes(p.key) && !disabled) return null;
          return (
            <div key={p.key} className="flex items-center justify-between py-1.5">
              <dt className="flex items-center gap-2 text-muted-foreground">
                <span className={cn("h-2 w-2 rounded-full", p.color)} />
                {p.label}
                {disabled && <Badge tone="muted">excluded</Badge>}
              </dt>
              <dd className="font-medium tabular">{money(p.value, currency)}</dd>
            </div>
          );
        })}
        <div className="flex items-center justify-between py-2 font-semibold">
          <dt>Total (estimate)</dt>
          <dd className="tabular">{money(breakdown.total, currency)}</dd>
        </div>
      </dl>
    </div>
  );
}

export function RouteHeadline({ plan }: { plan: RoutePlan }) {
  const deliveries = plan.kind === "multi" ? plan.stops.filter((s) => s.kind === "delivery").length : 1;
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
      <Metric label="Estimated cost" value={money(plan.total_cost, plan.currency)} strong />
      <Metric label="Distance" value={km(plan.distance_m)} />
      <Metric label={plan.kind === "multi" ? "Total time incl. stops" : "Duration (modelled)"} value={duration(plan.duration_s)} />
      <Metric label="Cost per delivery" value={money(Number(plan.total_cost) / deliveries, plan.currency)} />
      {plan.emissions_kg !== null && <Metric label="Est. CO₂" value={`${num(plan.emissions_kg, 2)} kg`} />}
      {plan.breakdown.trips !== undefined && <Metric label="Trips" value={String(plan.breakdown.trips)} />}
      {plan.breakdown.utilization !== undefined && <Metric label="Load utilisation" value={`${Math.round(plan.breakdown.utilization * 100)}%`} />}
      {plan.estimated_savings !== null && (
        <Metric label="Est. savings vs baseline" value={money(plan.estimated_savings, plan.currency)} hint={plan.baseline?.method === "shortest_distance" ? "vs. shortest-distance route" : "vs. nearest-neighbour order"} />
      )}
    </div>
  );
}

function Metric({ label, value, strong, hint }: { label: string; value: string; strong?: boolean; hint?: string }) {
  return (
    <div>
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className={cn("font-num", strong ? "text-2xl font-semibold text-primary" : "text-lg font-medium")}>{value}</p>
      {hint && <p className="text-[10px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function Warnings({ plan }: { plan: RoutePlan }) {
  if (!plan.warnings.length) return null;
  return (
    <Notice tone="warning" className="space-y-1">
      {plan.warnings.map((w, i) => (
        <p key={i} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-warning" />{w}</p>
      ))}
    </Notice>
  );
}

export function StopsList({ plan }: { plan: RoutePlan }) {
  return (
    <ol className="space-y-0">
      {plan.stops.map((s) => (
        <li key={s.sequence} className="relative flex gap-3 pb-3 pl-1">
          <div className="flex flex-col items-center">
            <span className={cn("flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold text-white",
              s.kind === "delivery" ? "bg-[#f45b1d]" : s.kind === "destination" ? "bg-red-600" : "bg-[#14161b]")}>
              {s.sequence}
            </span>
            {s.sequence < plan.stops.length - 1 && <span className="mt-1 w-px flex-1 bg-border" />}
          </div>
          <div className="min-w-0 flex-1 text-sm">
            <p className="truncate font-medium">{s.label}</p>
            <p className="text-xs capitalize text-muted-foreground">
              {s.kind}
              {s.sequence > 0 && <> · arrive {duration(s.arrival_s)} · leg {km(s.leg_distance_m)} · {money(s.leg_cost, plan.currency)}</>}
              {s.wait_s > 0 && <> · waits {duration(s.wait_s)}</>}
            </p>
            {s.allocated_cost && plan.kind === "multi" && (
              <p className="text-xs">Allocated cost: <span className="font-medium tabular">{money(s.allocated_cost, plan.currency)}</span></p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

export function Assumptions({ plan }: { plan: RoutePlan }) {
  return (
    <div className="space-y-4 text-sm">
      <div>
        <p className="text-xs font-medium text-muted-foreground">Objective</p>
        <p>{OBJECTIVE_LABELS[plan.objective]}</p>
        <p className="mt-1 rounded bg-muted px-2 py-1 font-mono text-[11px]">{plan.objective_formula}</p>
      </div>
      <div>
        <p className="text-xs font-medium text-muted-foreground">Assumptions</p>
        <ul className="mt-1 list-disc space-y-1 pl-4 text-xs">{plan.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
      </div>
      {plan.freshness && (
        <div>
          <p className="text-xs font-medium text-muted-foreground">Data freshness</p>
          <KV k="Road network" v={`${plan.freshness.network_name} (rev. ${plan.freshness.revision})`} />
          <KV k="Imported" v={dateTime(plan.freshness.imported_at)} />
          <KV k="OSM snapshot" v={dateTime(plan.freshness.osm_timestamp)} />
          <KV k="Energy prices updated" v={plan.freshness.energy_prices_updated_at ? dateTime(plan.freshness.energy_prices_updated_at) : "Initial defaults — review in Settings"} />
          <KV k="Traffic" v={plan.freshness.traffic} />
          {plan.freshness.stale && <Notice tone="warning" className="mt-2">Road data is older than {plan.freshness.stale_after_days} days.</Notice>}
        </div>
      )}
      <p className="text-[11px] text-muted-foreground">All costs are estimates from the configured cost model. {plan.freshness?.attribution ?? "© OpenStreetMap contributors"}.</p>
    </div>
  );
}

export function PlanActions({ plan, onChanged }: { plan: RoutePlan; onChanged?: (p: RoutePlan) => void }) {
  const setStatus = useAction((status: string) => api.patch<RoutePlan>(`/routes/${plan.id}/status`, { status }), {
    invalidate: ["routes", "analytics", "orders"], success: (r) => `Plan ${r.status}`, onSuccess: (r) => onChanged?.({ ...plan, ...r, geometry: plan.geometry }),
  });
  const duplicate = useAction(() => api.post<RoutePlan>(`/routes/${plan.id}/duplicate`), {
    invalidate: ["routes"], success: "Recalculated on current data", onSuccess: (r) => onChanged?.(r),
  });
  return (
    <div className="flex flex-wrap items-center gap-2">
      <StatusBadge status={plan.status} />
      {plan.status === "estimated" && <Button size="sm" onClick={() => setStatus.mutate("saved")} loading={setStatus.isPending}><Save /> Save plan</Button>}
      {plan.status === "saved" && <Button size="sm" onClick={() => setStatus.mutate("dispatched")} loading={setStatus.isPending}><Send /> Mark dispatched</Button>}
      {plan.status === "dispatched" && <Badge tone="warning"><Clock className="h-3 w-3" /> Record actuals in History</Badge>}
      {plan.status === "completed" && <Badge tone="success"><CheckCircle2 className="h-3 w-3" /> Completed</Badge>}
      <Button size="sm" variant="outline" asChild>
        <a href={downloadUrl(`/routes/${plan.id}/export.csv`)} download><Download /> CSV</a>
      </Button>
      <Button size="sm" variant="outline" onClick={() => window.print()}><Printer /> Print</Button>
      <Button size="sm" variant="ghost" onClick={() => duplicate.mutate(undefined)} loading={duplicate.isPending} title="Recalculate the same request on current data">
        <Copy /> Duplicate
      </Button>
    </div>
  );
}
