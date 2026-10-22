import { Link } from "react-router-dom";
import { ArrowRight, BarChart3, MapPin, Route as RouteIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/feedback";
import { PageHeader, Stat } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { StatusBadge } from "@/components/StatusBadge";
import { CostTrendChart } from "@/features/charts";
import { useAnalytics } from "@/hooks/queries";
import { date, km, money, num } from "@/utils/format";

export default function DashboardPage() {
  const q = useAnalytics();
  const actions = (
    <Button asChild><Link to="/planner"><RouteIcon /> Plan a route</Link></Button>
  );
  if (q.isLoading) {
    return (
      <>
        <Skeleton className="mb-6 h-56 rounded-2xl" />
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)}</div>
        <Skeleton className="mt-4 h-72" />
      </>
    );
  }
  if (q.isError) return <><PageHeader title="Overview" /><Card><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card></>;
  const d = q.data!;
  const t = d.totals;
  const c = d.currency;
  return (
    <>
      <section className="mb-6 overflow-hidden rounded-2xl bg-[hsl(var(--ink))] text-background">
        <div className="grid gap-6 p-6 sm:p-8 lg:grid-cols-[1.4fr_1fr] lg:items-end">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">Overview</p>
            <h1 className="mt-2 text-3xl font-semibold leading-tight sm:text-4xl">Every delivery, on the cheapest road.</h1>
            <p className="mt-3 max-w-lg text-sm text-background/70">Figures come from saved, dispatched and completed plans. Costs are model estimates unless marked actual.</p>
            <div className="mt-5 flex flex-wrap gap-2">
              <Button asChild size="lg"><Link to="/planner"><RouteIcon /> Plan a route</Link></Button>
              <Button asChild size="lg" variant="ghost" className="text-background hover:bg-background/10"><Link to="/planner?mode=multi">Multi-stop run</Link></Button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div><p className="text-[11px] font-semibold uppercase tracking-wider text-background/60">Estimated spend</p><p className="mt-1 font-num text-3xl font-semibold">{money(t.estimated_cost, c, 0)}</p><p className="text-xs text-background/60">Actual recorded {money(t.actual_recorded_cost, c, 0)}</p></div>
            <div><p className="text-[11px] font-semibold uppercase tracking-wider text-background/60">Estimated savings</p><p className="mt-1 font-num text-3xl font-semibold text-primary">{money(t.estimated_savings, c, 0)}</p><p className="text-xs text-background/60">{t.savings_pct !== null ? `${t.savings_pct}% vs baseline` : "No comparable baseline yet"}</p></div>
          </div>
        </div>
      </section>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Planned deliveries" value={num(t.planned_deliveries)} sub={`${num(t.committed_plans)} committed plans`} />
        <Stat label="Routes calculated" value={num(t.calculations)} sub="incl. unsaved estimates" />
        <Stat label="Avg. cost / delivery" value={money(t.avg_estimated_cost_per_delivery, c)} sub="estimate" />
        <Stat label="Distance planned" value={`${num(t.distance_km, 1)} km`} sub={t.emissions_kg !== null ? `${num(t.emissions_kg, 1)} kg CO₂ est.` : "emissions not configured"} />
      </div>

      {t.committed_plans === 0 ? (
        <Card className="mt-4">
          <EmptyState icon={BarChart3} title="No committed route plans yet"
            description="Calculate a route in the planner and save it. Metrics here are computed only from saved plans and recorded deliveries."
            action={actions} />
        </Card>
      ) : (
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader><div><CardTitle>Cost trend</CardTitle><CardDescription>Daily estimated plan cost vs. recorded actual cost</CardDescription></div></CardHeader>
            <CardContent><CostTrendChart data={d.trend} currency={c} /></CardContent>
          </Card>
          <Card>
            <CardHeader><div><CardTitle>Frequent delivery locations</CardTitle><CardDescription>By planned deliveries</CardDescription></div></CardHeader>
            <CardContent>
              {d.top_locations.length === 0 ? <p className="text-xs text-muted-foreground">No delivery locations yet.</p> : (
                <ul className="space-y-2">
                  {d.top_locations.map((l) => (
                    <li key={`${l.lat},${l.lon}`} className="flex items-center gap-2 text-sm">
                      <MapPin className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1 truncate">{l.label}</span>
                      <span className="text-xs tabular text-muted-foreground">{l.count}×</span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
          <Card className="lg:col-span-3">
            <CardHeader>
              <div><CardTitle>Recent route plans</CardTitle></div>
              <Button variant="ghost" size="sm" asChild><Link to="/history">View all <ArrowRight /></Link></Button>
            </CardHeader>
            <Table>
              <THead><TR><TH>Plan</TH><TH>Type</TH><TH>Status</TH><TH className="text-right">Distance</TH><TH className="text-right">Est. cost</TH><TH>Created</TH></TR></THead>
              <TBody>
                {d.recent.map((p) => (
                  <TR key={p.id}>
                    <TD className="max-w-[260px] truncate"><Link to={`/history?plan=${p.id}`} className="hover:underline">{p.name}</Link></TD>
                    <TD className="text-xs capitalize">{p.kind}</TD>
                    <TD><StatusBadge status={p.status} /></TD>
                    <TD className="text-right tabular">{km(p.distance_m)}</TD>
                    <TD className="text-right tabular">{money(p.total_cost, c)}</TD>
                    <TD className="text-xs text-muted-foreground">{date(p.created_at)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </Card>
        </div>
      )}
    </>
  );
}
