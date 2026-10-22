import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState, Notice, Skeleton } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/misc";
import { useAction, useSettings, useVehicles } from "@/hooks/queries";
import { api } from "@/services/api";
import type { Settings } from "@/types/api";
import { dateTime, OBJECTIVE_LABELS } from "@/utils/format";

const nonneg = z.string().trim().regex(/^\d+(\.\d+)?$/, "Enter a non-negative number");
const FUELS = ["petrol", "diesel", "cng", "electric"] as const;

const schema = z.object({
  workspace_name: z.string().trim().min(1).max(120),
  currency: z.string().trim().length(3, "3-letter ISO code").transform((s) => s.toUpperCase()),
  petrol: nonneg, diesel: nonneg, cng: nonneg, electric: nonneg,
  energy_prices_source: z.string().max(255).optional(),
  driver_cost_per_hour: nonneg,
  include_fuel: z.boolean(), include_driver: z.boolean(), include_operating: z.boolean(), include_tolls: z.boolean(),
  toll_rate_per_km_estimate: z.string().trim().regex(/^(\d+(\.\d+)?)?$/, "Number or blank"),
  value_of_time_per_hour: nonneg,
  speed_factor: z.string().trim().regex(/^\d+(\.\d+)?$/).refine((v) => Number(v) > 0 && Number(v) <= 2, "Between 0 and 2"),
  speeds: z.record(z.string(), z.string().regex(/^\d+(\.\d+)?$/, "km/h")),
  default_vehicle_id: z.string(),
  default_objective: z.enum(["money", "time", "distance", "balanced"]),
  tile_url: z.string().regex(/^https:\/\/.*\{z\}.*\{x\}.*\{y\}/, "Must be https and contain {z}/{x}/{y}"),
  tile_attribution: z.string().min(1, "Attribution is required by tile providers"),
  geocoder_url: z.string().url(),
  overpass_url: z.string().url(),
  network_stale_after_days: z.coerce.number().int().min(1).max(3650),
});
type Form = z.infer<typeof schema>;

function toForm(s: Settings): Form {
  return {
    workspace_name: s.workspace_name, currency: s.currency,
    petrol: s.energy_prices.petrol?.price ?? "", diesel: s.energy_prices.diesel?.price ?? "", cng: s.energy_prices.cng?.price ?? "", electric: s.energy_prices.electric?.price ?? "",
    energy_prices_source: s.energy_prices_source ?? "", driver_cost_per_hour: s.driver_cost_per_hour,
    include_fuel: s.include_fuel, include_driver: s.include_driver, include_operating: s.include_operating, include_tolls: s.include_tolls,
    toll_rate_per_km_estimate: s.toll_rate_per_km_estimate ?? "", value_of_time_per_hour: s.value_of_time_per_hour, speed_factor: s.speed_factor,
    speeds: Object.fromEntries(Object.entries(s.highway_speeds_kph).map(([k, v]) => [k, String(v)])),
    default_vehicle_id: s.default_vehicle_id ? String(s.default_vehicle_id) : "", default_objective: s.default_objective,
    tile_url: s.tile_url, tile_attribution: s.tile_attribution, geocoder_url: s.geocoder_url, overpass_url: s.overpass_url,
    network_stale_after_days: s.network_stale_after_days,
  };
}

export default function SettingsPage() {
  const settings = useSettings();
  const vehicles = useVehicles();
  const form = useForm<Form>({ resolver: zodResolver(schema) });
  const { register, handleSubmit, reset, formState: { errors: e, isDirty } } = form;
  useEffect(() => { if (settings.data) reset(toForm(settings.data)); }, [settings.data, reset]);
  const pricesChanged = (f: Form) => settings.data && FUELS.some((k) => f[k] !== (settings.data!.energy_prices[k]?.price ?? ""));
  const save = useAction((f: Form) => api.put<Settings>("/settings", {
    workspace_name: f.workspace_name, currency: f.currency,
    ...(pricesChanged(f) ? { energy_prices: Object.fromEntries(FUELS.map((k) => [k, f[k]])), energy_prices_source: f.energy_prices_source || "Updated by a user in Settings" } : {}),
    driver_cost_per_hour: f.driver_cost_per_hour, include_fuel: f.include_fuel, include_driver: f.include_driver,
    include_operating: f.include_operating, include_tolls: f.include_tolls,
    ...(f.toll_rate_per_km_estimate ? { toll_rate_per_km_estimate: f.toll_rate_per_km_estimate } : { clear_toll_rate_estimate: true }),
    value_of_time_per_hour: f.value_of_time_per_hour, speed_factor: f.speed_factor,
    highway_speeds_kph: Object.fromEntries(Object.entries(f.speeds).map(([k, v]) => [k, Number(v)])),
    default_vehicle_id: f.default_vehicle_id ? Number(f.default_vehicle_id) : null, default_objective: f.default_objective,
    tile_url: f.tile_url, tile_attribution: f.tile_attribution, geocoder_url: f.geocoder_url, overpass_url: f.overpass_url,
    network_stale_after_days: f.network_stale_after_days,
  }), { invalidate: ["settings", "networks"], success: "Settings saved — new calculations use these values" });

  if (settings.isLoading) return <><PageHeader title="Settings" /><Skeleton className="h-96" /></>;
  if (settings.isError) return <><PageHeader title="Settings" /><Card><ErrorState error={settings.error} onRetry={() => settings.refetch()} /></Card></>;
  const s = settings.data!;
  const cur = s.currency;

  return (
    <form onSubmit={handleSubmit((f) => save.mutate(f))} noValidate>
      <PageHeader title="Settings" description="Cost assumptions and data providers. Changes apply to new calculations; saved plans keep the settings snapshot they were calculated with."
        actions={<Button type="submit" loading={save.isPending} disabled={!isDirty}><Save /> Save changes</Button>} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><div><CardTitle>Workspace</CardTitle></div></CardHeader>
          <CardContent className="grid grid-cols-2 gap-3">
            <Field label="Workspace name" htmlFor="s-ws" error={e.workspace_name?.message}><Input id="s-ws" {...register("workspace_name")} /></Field>
            <Field label="Currency" htmlFor="s-cur" error={e.currency?.message}><Input id="s-cur" maxLength={3} {...register("currency")} /></Field>
            <Field label="Default vehicle" htmlFor="s-dv"><Select id="s-dv" {...register("default_vehicle_id")}><option value="">None</option>{vehicles.data?.items.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</Select></Field>
            <Field label="Default objective" htmlFor="s-do"><Select id="s-do" {...register("default_objective")}>{Object.entries(OBJECTIVE_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></Field>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><div><CardTitle>Fuel & energy prices</CardTitle><CardDescription>Last updated: {s.energy_prices_updated_at ? dateTime(s.energy_prices_updated_at) : "never (initial values)"}</CardDescription></div></CardHeader>
          <CardContent className="space-y-3">
            {!s.energy_prices_updated_at && <Notice tone="warning">{s.energy_prices_source}</Notice>}
            <div className="grid grid-cols-2 gap-3">
              {FUELS.map((k) => (
                <Field key={k} label={`${k[0].toUpperCase() + k.slice(1)} (${cur}/${s.energy_units[k]})`} htmlFor={`s-${k}`} error={e[k]?.message}><Input id={`s-${k}`} inputMode="decimal" {...register(k)} /></Field>
              ))}
            </div>
            <Field label="Price source / note" htmlFor="s-src"><Input id="s-src" placeholder="e.g. IOCL Delhi retail, 1 May" {...register("energy_prices_source")} /></Field>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><div><CardTitle>Cost components</CardTitle><CardDescription>Which components enter route costs by default (overridable per calculation)</CardDescription></div></CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <Checkbox label="Fuel / energy" {...register("include_fuel")} />
              <Checkbox label="Driver time" {...register("include_driver")} />
              <Checkbox label="Vehicle operating cost" {...register("include_operating")} />
              <Checkbox label="Tolls" {...register("include_tolls")} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label={`Driver cost (${cur}/hour)`} htmlFor="s-drv" error={e.driver_cost_per_hour?.message}><Input id="s-drv" inputMode="decimal" {...register("driver_cost_per_hour")} /></Field>
              <Field label={`Toll estimate (${cur}/km)`} htmlFor="s-toll" error={e.toll_rate_per_km_estimate?.message} hint="Applied only to roads tagged toll=yes without a configured amount. Blank = report as unavailable.">
                <Input id="s-toll" inputMode="decimal" {...register("toll_rate_per_km_estimate")} />
              </Field>
              <Field label={`Value of time (${cur}/hour)`} htmlFor="s-vot" error={e.value_of_time_per_hour?.message} hint="Used only by the Balanced objective"><Input id="s-vot" inputMode="decimal" {...register("value_of_time_per_hour")} /></Field>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><div><CardTitle>Travel-time model</CardTitle><CardDescription>Static speeds by road class (no live traffic). A posted maxspeed only lowers these.</CardDescription></div></CardHeader>
          <CardContent className="space-y-3">
            <Field label="Speed factor" htmlFor="s-sf" error={e.speed_factor?.message} hint="Multiplies all speeds, e.g. 0.8 for congested conditions"><Input id="s-sf" inputMode="decimal" className="w-32" {...register("speed_factor")} /></Field>
            <div className="grid grid-cols-3 gap-2">
              {Object.keys(s.highway_speeds_kph).map((k) => (
                <Field key={k} label={k.replace(/_/g, " ")} htmlFor={`sp-${k}`} error={e.speeds?.[k]?.message}><Input id={`sp-${k}`} inputMode="decimal" {...register(`speeds.${k}` as const)} /></Field>
              ))}
            </div>
          </CardContent>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader><div><CardTitle>Map & data providers</CardTitle><CardDescription>Respect each provider's usage policy. Public OSM services are for light use; configure your own instances for production volume.</CardDescription></div></CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            <Field label="Map tile URL" htmlFor="s-tile" error={e.tile_url?.message}><Input id="s-tile" {...register("tile_url")} /></Field>
            <Field label="Tile attribution" htmlFor="s-attr" error={e.tile_attribution?.message}><Input id="s-attr" {...register("tile_attribution")} /></Field>
            <Field label="Geocoder (Nominatim-compatible)" htmlFor="s-geo" error={e.geocoder_url?.message}><Input id="s-geo" {...register("geocoder_url")} /></Field>
            <Field label="Overpass API endpoint" htmlFor="s-ovp" error={e.overpass_url?.message}><Input id="s-ovp" {...register("overpass_url")} /></Field>
            <Field label="Flag road data as stale after (days)" htmlFor="s-stale" error={e.network_stale_after_days?.message}><Input id="s-stale" inputMode="numeric" className="w-32" {...register("network_stale_after_days")} /></Field>
          </CardContent>
        </Card>
      </div>
    </form>
  );
}
