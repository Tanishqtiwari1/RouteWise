import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Pencil, Plus, Trash2, Truck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useAction, useSettings, useVehicles } from "@/hooks/queries";
import { api } from "@/services/api";
import type { Vehicle } from "@/types/api";
import { money, num } from "@/utils/format";

const dec = z.string().trim().regex(/^\d+(\.\d+)?$/, "Enter a non-negative number");
const optDec = z.string().trim().regex(/^(\d+(\.\d+)?)?$/, "Enter a non-negative number").optional();

const schema = z.object({
  name: z.string().trim().min(1, "Required").max(120),
  category: z.enum(["two_wheeler", "car", "van", "light_truck", "heavy_truck"]),
  fuel_type: z.enum(["petrol", "diesel", "cng", "electric"]),
  efficiency_km_per_unit: dec.refine((v) => Number(v) > 0, "Must be greater than 0"),
  energy_price_override: optDec,
  max_payload_kg: dec.refine((v) => Number(v) > 0, "Must be greater than 0"),
  gross_weight_t: optDec,
  height_m: optDec,
  width_m: optDec,
  max_speed_kph: optDec,
  operating_cost_per_km: dec,
  fixed_cost_per_trip: dec,
  emissions_kg_per_unit: optDec,
  active: z.boolean(),
});
type Form = z.infer<typeof schema>;

const CATEGORY_LABEL: Record<string, string> = {
  two_wheeler: "Two-wheeler", car: "Car", van: "Van", light_truck: "Light truck", heavy_truck: "Heavy truck",
};
const UNIT: Record<string, string> = { petrol: "litre", diesel: "litre", cng: "kg", electric: "kWh" };
const opt = (s?: string) => (s && s !== "" ? s : null);

function VehicleDialog({ open, onOpenChange, vehicle }: { open: boolean; onOpenChange: (o: boolean) => void; vehicle: Vehicle | null }) {
  const form = useForm<Form>({ resolver: zodResolver(schema) });
  const { register, handleSubmit, reset, watch, formState: { errors: e } } = form;
  useEffect(() => {
    if (!open) return;
    const s = (v: unknown) => (v === null || v === undefined ? "" : String(v));
    reset(vehicle ? {
      name: vehicle.name, category: vehicle.category, fuel_type: vehicle.fuel_type, efficiency_km_per_unit: s(vehicle.efficiency_km_per_unit),
      energy_price_override: s(vehicle.energy_price_override), max_payload_kg: s(vehicle.max_payload_kg), gross_weight_t: s(vehicle.gross_weight_t),
      height_m: s(vehicle.height_m), width_m: s(vehicle.width_m), max_speed_kph: s(vehicle.max_speed_kph),
      operating_cost_per_km: s(vehicle.operating_cost_per_km), fixed_cost_per_trip: s(vehicle.fixed_cost_per_trip),
      emissions_kg_per_unit: s(vehicle.emissions_kg_per_unit), active: vehicle.active,
    } : { name: "", category: "van", fuel_type: "diesel", efficiency_km_per_unit: "", max_payload_kg: "", operating_cost_per_km: "0", fixed_cost_per_trip: "0", active: true });
  }, [open, vehicle, reset]);
  const unit = UNIT[watch("fuel_type") ?? "diesel"];
  const save = useAction((f: Form) => {
    const n = (v?: string) => (v ? Number(v) : null);
    const body = {
      ...f, energy_price_override: opt(f.energy_price_override), emissions_kg_per_unit: opt(f.emissions_kg_per_unit),
      max_payload_kg: Number(f.max_payload_kg), gross_weight_t: n(f.gross_weight_t), height_m: n(f.height_m), width_m: n(f.width_m), max_speed_kph: n(f.max_speed_kph),
    };
    return vehicle ? api.put(`/vehicles/${vehicle.id}`, body) : api.post("/vehicles", body);
  }, { invalidate: ["vehicles"], success: "Vehicle saved", onSuccess: () => onOpenChange(false) });

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={vehicle ? `Edit ${vehicle.name}` : "Add vehicle"} className="max-w-2xl"
      description="Operating costs are calculated from these values. Restrictions (weight, height, width) exclude roads whose OSM limits are lower."
      footer={<><Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={handleSubmit((f) => save.mutate(f))} loading={save.isPending}>Save</Button></>}>
      <form className="grid grid-cols-2 gap-3 sm:grid-cols-3" onSubmit={(ev) => ev.preventDefault()} noValidate>
        <Field label="Name / identifier" htmlFor="v-n" error={e.name?.message} className="col-span-2 sm:col-span-1"><Input id="v-n" {...register("name")} /></Field>
        <Field label="Category" htmlFor="v-c"><Select id="v-c" {...register("category")}>{Object.entries(CATEGORY_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></Field>
        <Field label="Fuel / energy" htmlFor="v-f"><Select id="v-f" {...register("fuel_type")}>{["petrol", "diesel", "cng", "electric"].map((f) => <option key={f} value={f}>{f}</option>)}</Select></Field>
        <Field label={`Efficiency (km/${unit})`} htmlFor="v-e" error={e.efficiency_km_per_unit?.message}><Input id="v-e" inputMode="decimal" {...register("efficiency_km_per_unit")} /></Field>
        <Field label={`Price override (per ${unit})`} htmlFor="v-p" error={e.energy_price_override?.message} hint="Blank = workspace price"><Input id="v-p" inputMode="decimal" {...register("energy_price_override")} /></Field>
        <Field label="Max payload (kg)" htmlFor="v-pl" error={e.max_payload_kg?.message}><Input id="v-pl" inputMode="decimal" {...register("max_payload_kg")} /></Field>
        <Field label="Operating cost (/km)" htmlFor="v-o" error={e.operating_cost_per_km?.message} hint="Maintenance, tyres, depreciation"><Input id="v-o" inputMode="decimal" {...register("operating_cost_per_km")} /></Field>
        <Field label="Fixed cost per trip" htmlFor="v-fx" error={e.fixed_cost_per_trip?.message}><Input id="v-fx" inputMode="decimal" {...register("fixed_cost_per_trip")} /></Field>
        <Field label={`CO₂ (kg/${unit})`} htmlFor="v-co" error={e.emissions_kg_per_unit?.message} hint="Optional; blank = not estimated"><Input id="v-co" inputMode="decimal" {...register("emissions_kg_per_unit")} /></Field>
        <Field label="Gross weight (t)" htmlFor="v-gw" error={e.gross_weight_t?.message}><Input id="v-gw" inputMode="decimal" {...register("gross_weight_t")} /></Field>
        <Field label="Height (m)" htmlFor="v-h" error={e.height_m?.message}><Input id="v-h" inputMode="decimal" {...register("height_m")} /></Field>
        <Field label="Width (m)" htmlFor="v-w" error={e.width_m?.message}><Input id="v-w" inputMode="decimal" {...register("width_m")} /></Field>
        <Field label="Max speed (km/h)" htmlFor="v-s" error={e.max_speed_kph?.message}><Input id="v-s" inputMode="decimal" {...register("max_speed_kph")} /></Field>
        <div className="col-span-2 flex items-end pb-2 sm:col-span-1"><Checkbox label="Active" {...register("active")} /></div>
      </form>
    </Dialog>
  );
}

export default function FleetPage() {
  const vehicles = useVehicles();
  const settings = useSettings();
  const [dlg, setDlg] = useState<{ open: boolean; v: Vehicle | null }>({ open: false, v: null });
  const del = useAction((id: number) => api.del(`/vehicles/${id}`), { invalidate: ["vehicles"], success: "Vehicle deleted" });
  const items = vehicles.data?.items ?? [];
  const cur = settings.data?.currency ?? "INR";
  const perKm = (v: Vehicle) => {
    const price = v.energy_price_override ?? settings.data?.energy_prices?.[v.fuel_type]?.price;
    if (!price) return null;
    return Number(price) / Number(v.efficiency_km_per_unit) + Number(v.operating_cost_per_km);
  };
  return (
    <>
      <PageHeader title="Fleet" description="Vehicles, energy use, capacity and road restrictions used by the cost model."
        actions={<Button onClick={() => setDlg({ open: true, v: null })}><Plus /> Add vehicle</Button>} />
      <Card>
        {vehicles.isLoading ? <TableSkeleton /> : vehicles.isError ? <ErrorState error={vehicles.error} onRetry={() => vehicles.refetch()} /> : items.length === 0 ? (
          <EmptyState icon={Truck} title="No vehicles yet" description="Add a vehicle to calculate fuel and operating costs." action={<Button size="sm" onClick={() => setDlg({ open: true, v: null })}><Plus /> Add vehicle</Button>} />
        ) : (
          <Table>
            <THead><TR><TH>Vehicle</TH><TH>Energy</TH><TH className="text-right">Payload</TH><TH className="text-right">Distance cost*</TH><TH className="text-right">Fixed / trip</TH><TH>Restrictions</TH><TH /></TR></THead>
            <TBody>
              {items.map((v) => {
                const pk = perKm(v);
                return (
                  <TR key={v.id}>
                    <TD><p className="font-medium">{v.name}</p><p className="text-xs text-muted-foreground">{CATEGORY_LABEL[v.category]}{!v.active && <Badge tone="muted" className="ml-1">inactive</Badge>}{settings.data?.default_vehicle_id === v.id && <Badge tone="info" className="ml-1">default</Badge>}</p></TD>
                    <TD className="text-xs capitalize">{v.fuel_type} · {v.efficiency_km_per_unit} km/{UNIT[v.fuel_type]}</TD>
                    <TD className="text-right tabular">{num(v.max_payload_kg)} kg</TD>
                    <TD className="text-right tabular">{pk === null ? <span className="text-warning">price missing</span> : `${money(pk, cur)}/km`}</TD>
                    <TD className="text-right tabular">{money(v.fixed_cost_per_trip, cur)}</TD>
                    <TD className="text-xs text-muted-foreground">{[v.gross_weight_t && `${v.gross_weight_t} t`, v.height_m && `${v.height_m} m high`, v.width_m && `${v.width_m} m wide`].filter(Boolean).join(" · ") || "—"}</TD>
                    <TD className="whitespace-nowrap text-right">
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setDlg({ open: true, v })} aria-label={`Edit ${v.name}`}><Pencil /></Button>
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => confirm(`Delete ${v.name}?`) && del.mutate(v.id)} aria-label={`Delete ${v.name}`}><Trash2 /></Button>
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        )}
        {items.length > 0 && <p className="border-t px-3 py-2 text-[11px] text-muted-foreground">* Fuel/energy + operating cost per km, excluding driver time, tolls and fixed costs.</p>}
      </Card>
      <VehicleDialog open={dlg.open} onOpenChange={(o) => setDlg({ ...dlg, open: o })} vehicle={dlg.v} />
    </>
  );
}
