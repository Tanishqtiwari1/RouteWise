import { useState } from "react";
import { BarChart3 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/input";
import { PageHeader, Stat } from "@/components/ui/misc";
import { ComponentsChart, CostPerDeliveryChart, CostTrendChart, DistanceCostChart, VehicleChart } from "@/features/charts";
import { useAnalytics, useVehicles, useWarehouses } from "@/hooks/queries";
import { money, num } from "@/utils/format";

export default function AnalyticsPage() {
  const [f, setF] = useState({ date_from: "", date_to: "", vehicle_id: "", warehouse_id: "", status: "" });
  const vehicles = useVehicles();
  const warehouses = useWarehouses();
  const q = useAnalytics({
    date_from: f.date_from || undefined, date_to: f.date_to || undefined, vehicle_id: f.vehicle_id || undefined,
    warehouse_id: f.warehouse_id || undefined, status: f.status ? [f.status] : undefined,
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const d = q.data;
  const c = d?.currency ?? "INR";

  return (
    <>
      <PageHeader title="Analytics" description="Computed from persisted route plans and recorded delivery outcomes." />
      <Card className="mb-4">
        <CardContent className="grid grid-cols-2 gap-3 pt-4 md:grid-cols-5">
          <Field label="From" htmlFor="af"><Input id="af" type="date" value={f.date_from} onChange={set("date_from")} /></Field>
          <Field label="To" htmlFor="at"><Input id="at" type="date" value={f.date_to} onChange={set("date_to")} /></Field>
          <Field label="Vehicle" htmlFor="av">
            <Select id="av" value={f.vehicle_id} onChange={set("vehicle_id")}>
              <option value="">All vehicles</option>
              {vehicles.data?.items.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </Select>
          </Field>
          <Field label="Warehouse" htmlFor="aw">
            <Select id="aw" value={f.warehouse_id} onChange={set("warehouse_id")}>
              <option value="">All warehouses</option>
              {warehouses.data?.items.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          </Field>
          <Field label="Plan status" htmlFor="as">
            <Select id="as" value={f.status} onChange={set("status")}>
              <option value="">Committed (saved/dispatched/completed)</option>
              <option value="saved">Saved</option>
              <option value="dispatched">Dispatched</option>
              <option value="completed">Completed</option>
            </Select>
          </Field>
        </CardContent>
      </Card>

      {q.isLoading ? <Skeleton className="h-96" /> : q.isError ? <Card><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card> : !d || d.totals.committed_plans === 0 ? (
        <Card><EmptyState icon={BarChart3} title="No data for these filters" description="Save route plans in the planner (and record actual outcomes for dispatched plans) to populate analytics." /></Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Estimated expenditure" value={money(d.totals.estimated_cost, c, 0)} sub={`${num(d.totals.committed_plans)} plans · ${num(d.totals.distance_km, 1)} km`} />
            <Stat label="Actual recorded expenditure" value={money(d.totals.actual_recorded_cost, c, 0)}
              sub={d.totals.plans_with_actuals ? `${d.totals.plans_with_actuals} plans; their estimate was ${money(d.totals.estimated_cost_of_plans_with_actuals, c, 0)}` : "No actuals recorded"} />
            <Stat label="Estimated savings" value={money(d.totals.estimated_savings, c, 0)} sub={d.totals.savings_pct !== null ? `${d.totals.savings_pct}% of ${money(d.totals.baseline_cost, c, 0)} baseline` : "No comparable baseline"} />
            <Stat label="Delivery success" value={d.completion.success_rate !== null ? `${Math.round(d.completion.success_rate * 100)}%` : "—"}
              sub={d.completion.recorded ? `${d.completion.deliveries_completed} completed · ${d.completion.deliveries_failed} failed` : "Needs recorded outcomes"} />
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <ChartCard title="Delivery expenditure over time" desc="Estimated vs. recorded actual"><CostTrendChart data={d.trend} currency={c} /></ChartCard>
            <ChartCard title="Cost distribution" desc="Fuel, driver, operating, toll and fixed components (estimated)"><ComponentsChart data={d.components} currency={c} /></ChartCard>
            <ChartCard title="Cost per delivery" desc="Daily average of estimated plan cost per planned delivery"><CostPerDeliveryChart data={d.trend} currency={c} /></ChartCard>
            <ChartCard title="Route distance vs. cost" desc="Each point is a committed plan"><DistanceCostChart data={d.distance_vs_cost} currency={c} /></ChartCard>
            <ChartCard title="Vehicle utilisation" desc="Distance driven and payload utilisation (multi-stop plans only)"><VehicleChart data={d.vehicles} /></ChartCard>
            <Card>
              <CardHeader><div><CardTitle>Definitions</CardTitle><CardDescription>How these numbers are computed</CardDescription></div></CardHeader>
              <CardContent>
                <dl className="space-y-2 text-xs">
                  {Object.entries(d.definitions).map(([k, v]) => <div key={k}><dt className="font-medium capitalize">{k.replace(/_/g, " ")}</dt><dd className="text-muted-foreground">{v}</dd></div>)}
                </dl>
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </>
  );
}

function ChartCard({ title, desc, children }: { title: string; desc: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader><div><CardTitle>{title}</CardTitle><CardDescription>{desc}</CardDescription></div></CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}
