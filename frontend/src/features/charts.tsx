import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import type { AnalyticsSummary } from "@/types/api";
import { money } from "@/utils/format";

const AXIS = { fontSize: 11, fill: "hsl(var(--muted-foreground))" };
const GRID = "hsl(var(--border))";
const tooltipStyle = { fontSize: 12, borderRadius: 6, border: "1px solid hsl(var(--border))", background: "hsl(var(--card))", color: "hsl(var(--foreground))" };

export function CostTrendChart({ data, currency, height = 240 }: { data: AnalyticsSummary["trend"]; currency: string; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="date" tick={AXIS} tickLine={false} axisLine={false} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={70} tickFormatter={(v) => money(v, currency, 0)} />
        <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => money(v, currency)} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line type="monotone" dataKey="estimated" name="Estimated" stroke="#f45b1d" strokeWidth={2} dot={false} />
        <Line type="monotone" dataKey="actual" name="Actual (recorded)" stroke="#14161b" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function CostPerDeliveryChart({ data, currency }: { data: AnalyticsSummary["trend"]; currency: string }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="date" tick={AXIS} tickLine={false} axisLine={false} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={64} tickFormatter={(v) => money(v, currency, 0)} />
        <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => money(v, currency)} />
        <Line type="monotone" dataKey="cost_per_delivery" name="Cost / delivery" stroke="#f45b1d" strokeWidth={2} dot={{ r: 2 }} connectNulls />
      </LineChart>
    </ResponsiveContainer>
  );
}

const COMPONENT_COLORS: Record<string, string> = { fuel: "#f45b1d", driver: "#44403c", operating: "#2563eb", toll: "#eab308", extra: "#db2777", fixed: "#a8a29e" };

export function ComponentsChart({ data, currency }: { data: AnalyticsSummary["components"]; currency: string }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
        <CartesianGrid stroke={GRID} horizontal={false} />
        <XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} tickFormatter={(v) => money(v, currency, 0)} />
        <YAxis type="category" dataKey="component" tick={AXIS} tickLine={false} axisLine={false} width={70} />
        <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => money(v, currency)} />
        <Bar dataKey="amount" name="Estimated" radius={[0, 3, 3, 0]}>
          {data.map((d) => <Cell key={d.component} fill={COMPONENT_COLORS[d.component] ?? "#f45b1d"} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function DistanceCostChart({ data, currency }: { data: AnalyticsSummary["distance_vs_cost"]; currency: string }) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <ScatterChart margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
        <CartesianGrid stroke={GRID} />
        <XAxis type="number" dataKey="distance_km" name="Distance" unit=" km" tick={AXIS} tickLine={false} />
        <YAxis type="number" dataKey="cost" name="Cost" tick={AXIS} tickLine={false} width={64} tickFormatter={(v) => money(v, currency, 0)} />
        <ZAxis range={[40, 40]} />
        <Tooltip contentStyle={tooltipStyle} formatter={(v: number, n: string) => (n === "Cost" ? money(v, currency) : `${v} km`)} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Scatter name="Single routes" data={data.filter((d) => d.kind === "single")} fill="#f45b1d" />
        <Scatter name="Multi-stop plans" data={data.filter((d) => d.kind === "multi")} fill="#44403c" />
      </ScatterChart>
    </ResponsiveContainer>
  );
}

export function VehicleChart({ data }: { data: AnalyticsSummary["vehicles"] }) {
  const rows = data.map((v) => ({ ...v, utilization_pct: v.utilization === null ? null : Math.round(v.utilization * 100) }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="vehicle" tick={AXIS} tickLine={false} axisLine={false} />
        <YAxis yAxisId="l" tick={AXIS} tickLine={false} axisLine={false} width={40} />
        <YAxis yAxisId="r" orientation="right" tick={AXIS} tickLine={false} axisLine={false} width={40} unit="%" domain={[0, 100]} />
        <Tooltip contentStyle={tooltipStyle} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar yAxisId="l" dataKey="distance_km" name="Distance (km)" fill="#f45b1d" radius={[3, 3, 0, 0]} />
        <Bar yAxisId="r" dataKey="utilization_pct" name="Load utilisation %" fill="#44403c" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
