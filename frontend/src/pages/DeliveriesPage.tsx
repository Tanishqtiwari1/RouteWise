import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useSearchParams } from "react-router-dom";
import { Download, FileUp, MapPinned, Pencil, Plus, RefreshCw, Trash2, Users, Warehouse as WarehouseIcon, Package } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState, ErrorState, Notice, TableSkeleton } from "@/components/ui/feedback";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { PageHeader, Pagination } from "@/components/ui/misc";
import { SortTH, Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { StatusBadge } from "@/components/StatusBadge";
import { useAction, useCustomers, useOrders, useWarehouses } from "@/hooks/queries";
import { api, downloadUrl } from "@/services/api";
import type { Address, Customer, ImportSummary, Order, Warehouse } from "@/types/api";
import { dateTime, fromLocalInput, toLocalInput } from "@/utils/format";

export default function DeliveriesPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "orders";
  return (
    <>
      <PageHeader title="Delivery Management" description="Orders, customers, delivery addresses and warehouses. Locations are never assumed: each address carries its geocoding status." />
      <Tabs value={tab} onValueChange={(t) => setParams({ tab: t })}>
        <TabsList>
          <TabsTrigger value="orders"><Package /> Orders</TabsTrigger>
          <TabsTrigger value="customers"><Users /> Customers & addresses</TabsTrigger>
          <TabsTrigger value="warehouses"><WarehouseIcon /> Warehouses</TabsTrigger>
        </TabsList>
        <TabsContent value="orders" className="mt-4"><OrdersTab /></TabsContent>
        <TabsContent value="customers" className="mt-4"><CustomersTab /></TabsContent>
        <TabsContent value="warehouses" className="mt-4"><WarehousesTab /></TabsContent>
      </Tabs>
    </>
  );
}

/* ------------------------------------------------------------------ orders */

const orderSchema = z.object({
  reference: z.string().trim().min(1, "Required").max(60),
  customer_id: z.coerce.number().int().positive("Select a customer"),
  address_id: z.coerce.number().int().positive("Select an address"),
  warehouse_id: z.string().optional(),
  weight_kg: z.coerce.number().positive("Must be > 0").max(60000),
  quantity: z.coerce.number().int().min(1),
  length_cm: z.string().optional(),
  width_cm: z.string().optional(),
  height_cm: z.string().optional(),
  priority: z.enum(["low", "normal", "high", "urgent"]),
  status: z.enum(["pending", "planned", "dispatched", "delivered", "failed", "cancelled"]),
  window_start: z.string().optional(),
  window_end: z.string().optional(),
  service_time_min: z.coerce.number().min(0).max(600),
  notes: z.string().optional(),
}).refine((v) => !v.window_start || !v.window_end || v.window_end > v.window_start, { path: ["window_end"], message: "Must be after start" });
type OrderForm = z.infer<typeof orderSchema>;

const optNum = (s?: string) => (s && s.trim() !== "" ? Number(s) : null);

function OrderDialog({ open, onOpenChange, order }: { open: boolean; onOpenChange: (o: boolean) => void; order: Order | null }) {
  const customers = useCustomers({ page_size: 200 });
  const warehouses = useWarehouses();
  const form = useForm<OrderForm>({ resolver: zodResolver(orderSchema) });
  const { register, handleSubmit, watch, reset, formState: { errors } } = form;
  useEffect(() => {
    if (!open) return;
    reset(order ? {
      reference: order.reference, customer_id: order.customer_id, address_id: order.address_id, warehouse_id: order.warehouse_id ? String(order.warehouse_id) : "",
      weight_kg: order.weight_kg, quantity: order.quantity, length_cm: order.length_cm?.toString() ?? "", width_cm: order.width_cm?.toString() ?? "",
      height_cm: order.height_cm?.toString() ?? "", priority: order.priority, status: order.status, window_start: toLocalInput(order.window_start),
      window_end: toLocalInput(order.window_end), service_time_min: order.service_time_min, notes: order.notes ?? "",
    } : { reference: "", priority: "normal", status: "pending", quantity: 1, service_time_min: 5, warehouse_id: "" } as Partial<OrderForm>);
  }, [open, order, reset]);
  const custId = Number(watch("customer_id"));
  const addresses = customers.data?.items.find((c) => c.id === custId)?.addresses ?? [];
  const save = useAction((f: OrderForm) => {
    const body = {
      ...f, warehouse_id: f.warehouse_id ? Number(f.warehouse_id) : null, length_cm: optNum(f.length_cm), width_cm: optNum(f.width_cm),
      height_cm: optNum(f.height_cm), window_start: fromLocalInput(f.window_start ?? ""), window_end: fromLocalInput(f.window_end ?? ""), notes: f.notes || null,
    };
    return order ? api.put(`/orders/${order.id}`, body) : api.post("/orders", body);
  }, { invalidate: ["orders"], success: order ? "Order updated" : "Order created", onSuccess: () => onOpenChange(false) });

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={order ? `Edit ${order.reference}` : "New delivery order"} className="max-w-2xl"
      footer={<><Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={handleSubmit((f) => save.mutate(f))} loading={save.isPending}>Save</Button></>}>
      <form className="grid grid-cols-2 gap-3" onSubmit={(e) => e.preventDefault()} noValidate>
        <Field label="Reference" htmlFor="o-ref" error={errors.reference?.message}><Input id="o-ref" {...register("reference")} /></Field>
        <Field label="Priority" htmlFor="o-pri"><Select id="o-pri" {...register("priority")}>{["low", "normal", "high", "urgent"].map((p) => <option key={p}>{p}</option>)}</Select></Field>
        <Field label="Customer" htmlFor="o-cust" error={errors.customer_id?.message}>
          <Select id="o-cust" {...register("customer_id")} defaultValue=""><option value="" disabled>Select…</option>{customers.data?.items.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
        </Field>
        <Field label="Delivery address" htmlFor="o-addr" error={errors.address_id?.message} hint={custId && !addresses.length ? "Add an address in Customers first" : undefined}>
          <Select id="o-addr" {...register("address_id")} defaultValue=""><option value="" disabled>Select…</option>{addresses.map((a) => <option key={a.id} value={a.id}>{a.label ? `${a.label}: ` : ""}{a.address_text} ({a.geocode_status})</option>)}</Select>
        </Field>
        <Field label="Warehouse" htmlFor="o-wh"><Select id="o-wh" {...register("warehouse_id")}><option value="">—</option>{warehouses.data?.items.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</Select></Field>
        <Field label="Status" htmlFor="o-st"><Select id="o-st" {...register("status")}>{["pending", "planned", "dispatched", "delivered", "failed", "cancelled"].map((s) => <option key={s}>{s}</option>)}</Select></Field>
        <Field label="Weight (kg)" htmlFor="o-w" error={errors.weight_kg?.message}><Input id="o-w" inputMode="decimal" {...register("weight_kg")} /></Field>
        <Field label="Quantity" htmlFor="o-q" error={errors.quantity?.message}><Input id="o-q" inputMode="numeric" {...register("quantity")} /></Field>
        <div className="col-span-2 grid grid-cols-3 gap-3">
          <Field label="Length (cm)" htmlFor="o-l"><Input id="o-l" inputMode="decimal" {...register("length_cm")} /></Field>
          <Field label="Width (cm)" htmlFor="o-wd"><Input id="o-wd" inputMode="decimal" {...register("width_cm")} /></Field>
          <Field label="Height (cm)" htmlFor="o-h"><Input id="o-h" inputMode="decimal" {...register("height_cm")} /></Field>
        </div>
        <Field label="Window start" htmlFor="o-ws"><Input id="o-ws" type="datetime-local" {...register("window_start")} /></Field>
        <Field label="Window end" htmlFor="o-we" error={errors.window_end?.message}><Input id="o-we" type="datetime-local" {...register("window_end")} /></Field>
        <Field label="Service time (min)" htmlFor="o-svc" error={errors.service_time_min?.message}><Input id="o-svc" inputMode="decimal" {...register("service_time_min")} /></Field>
        <Field label="Notes" htmlFor="o-n" className="col-span-2"><Textarea id="o-n" {...register("notes")} /></Field>
      </form>
    </Dialog>
  );
}

function ImportDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  const run = useAction((dry: boolean) => {
    const fd = new FormData();
    fd.append("file", file!);
    return api.upload<ImportSummary>("/orders/import", fd, { dry_run: dry });
  }, { invalidate: ["orders", "customers"], onSuccess: setSummary });
  useEffect(() => { if (!open) { setFile(null); setSummary(null); } }, [open]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Import orders from CSV" className="max-w-2xl"
      description="Rows are validated first. Coordinates are optional; addresses without them are marked pending and geocoded later."
      footer={<>
        <Button variant="outline" asChild><a href={downloadUrl("/orders/import/template.csv")} download><Download /> Template</a></Button>
        <Button variant="outline" disabled={!file} loading={run.isPending && run.variables} onClick={() => run.mutate(true)}>Validate</Button>
        <Button disabled={!file || (summary?.dry_run === false)} loading={run.isPending && !run.variables} onClick={() => run.mutate(false)}>Import valid rows</Button>
      </>}>
      <Input type="file" accept=".csv,text/csv" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setSummary(null); }} aria-label="CSV file" className="py-1.5" />
      <p className="mt-2 text-xs text-muted-foreground">Required columns: reference, customer_name, address, weight_kg. Optional: customer_email, customer_phone, lat, lon, quantity, priority, warehouse, window_start, window_end, service_time_min, notes.</p>
      {summary && (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-4 gap-2 text-center text-xs">
            {[["Rows", summary.total_rows], ["Valid", summary.valid_rows], ["Invalid", summary.invalid_rows], [summary.dry_run ? "Would create" : "Created", summary.dry_run ? summary.valid_rows : summary.created_orders]].map(([k, v]) => (
              <div key={k as string} className="rounded-md border p-2"><p className="text-muted-foreground">{k}</p><p className="text-base font-semibold tabular">{v}</p></div>
            ))}
          </div>
          {!summary.dry_run && <Notice>Created {summary.created_customers} customers and {summary.created_addresses} addresses; {summary.pending_geocode} addresses await geocoding.</Notice>}
          {summary.unknown_columns.length > 0 && <Notice tone="warning">Ignored unknown columns: {summary.unknown_columns.join(", ")}</Notice>}
          {summary.errors.length > 0 && (
            <div className="max-h-56 overflow-y-auto rounded-md border">
              <Table><THead><TR><TH>Row</TH><TH>Field</TH><TH>Problem</TH></TR></THead>
                <TBody>{summary.errors.map((e, i) => <TR key={i}><TD className="tabular">{e.row}</TD><TD className="font-mono text-xs">{e.field}</TD><TD className="text-xs">{e.message}</TD></TR>)}</TBody>
              </Table>
            </div>
          )}
        </div>
      )}
    </Dialog>
  );
}

function OrdersTab() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [geo, setGeo] = useState("");
  const [sort, setSort] = useState("-created_at");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<number[]>([]);
  const [edit, setEdit] = useState<Order | null>(null);
  const [dialog, setDialog] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const orders = useOrders({ q, status: status ? [status] : undefined, priority, geocode_status: geo, sort, page, page_size: 20 });
  const del = useAction((id: number) => api.del(`/orders/${id}`), { invalidate: ["orders"], success: "Order deleted" });
  const bulk = useAction((s: string) => api.post<{ updated: number }>("/orders/bulk-status", { ids: selected, status: s }), {
    invalidate: ["orders"], success: (r) => `${r.updated} orders updated`, onSuccess: () => setSelected([]),
  });
  const geocodePending = useAction(() => api.post<{ started: boolean; total: number }>("/geocode/pending"), {
    success: (r) => (r.started ? `Geocoding ${r.total} pending addresses in the background (~1/s)` : "No pending addresses"),
  });
  const items = orders.data?.items ?? [];
  return (
    <Card>
      <div className="flex flex-wrap items-end gap-2 border-b p-3">
        <Input placeholder="Search reference, customer, address…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} className="w-64" aria-label="Search orders" />
        <Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className="w-36" aria-label="Status filter">
          <option value="">All statuses</option>{["pending", "planned", "dispatched", "delivered", "failed", "cancelled"].map((s) => <option key={s}>{s}</option>)}
        </Select>
        <Select value={priority} onChange={(e) => { setPriority(e.target.value); setPage(1); }} className="w-32" aria-label="Priority filter">
          <option value="">Any priority</option>{["low", "normal", "high", "urgent"].map((s) => <option key={s}>{s}</option>)}
        </Select>
        <Select value={geo} onChange={(e) => { setGeo(e.target.value); setPage(1); }} className="w-40" aria-label="Geocode filter">
          <option value="">Any location status</option>{["matched", "manual", "pending", "ambiguous", "failed"].map((s) => <option key={s}>{s}</option>)}
        </Select>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => geocodePending.mutate(undefined)} loading={geocodePending.isPending}><MapPinned /> Geocode pending</Button>
          <Button variant="outline" size="sm" onClick={() => setImportOpen(true)}><FileUp /> Import CSV</Button>
          <Button variant="outline" size="sm" asChild><a href={downloadUrl("/orders/export.csv")} download><Download /> Export</a></Button>
          <Button size="sm" onClick={() => { setEdit(null); setDialog(true); }}><Plus /> New order</Button>
        </div>
      </div>
      {selected.length > 0 && (
        <div className="flex items-center gap-2 border-b bg-accent/50 px-3 py-2 text-xs">
          {selected.length} selected · set status:
          {["pending", "delivered", "failed", "cancelled"].map((s) => <Button key={s} size="sm" variant="outline" onClick={() => bulk.mutate(s)}>{s}</Button>)}
          <Button size="sm" variant="ghost" onClick={() => setSelected([])}>Clear</Button>
        </div>
      )}
      {orders.isLoading ? <TableSkeleton /> : orders.isError ? <ErrorState error={orders.error} onRetry={() => orders.refetch()} /> : items.length === 0 ? (
        <EmptyState title="No delivery orders" description="Create an order or import a CSV file." action={<Button size="sm" onClick={() => setImportOpen(true)}><FileUp /> Import CSV</Button>} />
      ) : (
        <>
          <Table>
            <THead>
              <TR>
                <TH className="w-8"><input type="checkbox" aria-label="Select all" checked={selected.length === items.length} onChange={(e) => setSelected(e.target.checked ? items.map((o) => o.id) : [])} /></TH>
                <SortTH field="reference" sort={sort} onSort={setSort}>Reference</SortTH>
                <SortTH field="customer" sort={sort} onSort={setSort}>Customer</SortTH>
                <TH>Address</TH>
                <SortTH field="weight_kg" sort={sort} onSort={setSort} className="text-right">Weight</SortTH>
                <SortTH field="priority" sort={sort} onSort={setSort}>Priority</SortTH>
                <SortTH field="status" sort={sort} onSort={setSort}>Status</SortTH>
                <SortTH field="window_start" sort={sort} onSort={setSort}>Window</SortTH>
                <TH />
              </TR>
            </THead>
            <TBody>
              {items.map((o) => (
                <TR key={o.id}>
                  <TD><input type="checkbox" aria-label={`Select ${o.reference}`} checked={selected.includes(o.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, o.id] : selected.filter((x) => x !== o.id))} /></TD>
                  <TD className="font-medium">{o.reference}</TD>
                  <TD>{o.customer_name}</TD>
                  <TD className="max-w-[240px]"><span className="block truncate text-xs">{o.address_text}</span><StatusBadge status={o.geocode_status} /></TD>
                  <TD className="text-right tabular">{o.weight_kg} kg</TD>
                  <TD><Badge tone={o.priority === "urgent" ? "danger" : o.priority === "high" ? "warning" : "muted"}>{o.priority}</Badge></TD>
                  <TD><StatusBadge status={o.status} /></TD>
                  <TD className="text-xs text-muted-foreground">{o.window_start || o.window_end ? `${dateTime(o.window_start)} – ${dateTime(o.window_end)}` : "—"}</TD>
                  <TD className="whitespace-nowrap text-right">
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => { setEdit(o); setDialog(true); }} aria-label={`Edit ${o.reference}`}><Pencil /></Button>
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => confirm(`Delete order ${o.reference}?`) && del.mutate(o.id)} aria-label={`Delete ${o.reference}`}><Trash2 /></Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
          <Pagination page={page} pageSize={20} total={orders.data?.total ?? 0} onPage={setPage} />
        </>
      )}
      <OrderDialog open={dialog} onOpenChange={setDialog} order={edit} />
      <ImportDialog open={importOpen} onOpenChange={setImportOpen} />
    </Card>
  );
}

/* --------------------------------------------------------------- customers */

const custSchema = z.object({ name: z.string().trim().min(1, "Required"), email: z.string().email("Invalid email").or(z.literal("")).optional(), phone: z.string().optional(), notes: z.string().optional() });
const addrSchema = z.object({
  label: z.string().optional(), address_text: z.string().trim().min(3, "At least 3 characters"),
  lat: z.string().optional(), lon: z.string().optional(),
}).refine((v) => !!v.lat === !!v.lon, { path: ["lon"], message: "Provide both coordinates or neither" })
  .refine((v) => !v.lat || (Math.abs(Number(v.lat)) <= 90 && Math.abs(Number(v.lon)) <= 180), { path: ["lat"], message: "Invalid coordinates" });

function CustomerDialog({ open, onOpenChange, customer }: { open: boolean; onOpenChange: (o: boolean) => void; customer: Customer | null }) {
  const form = useForm<z.infer<typeof custSchema>>({ resolver: zodResolver(custSchema) });
  useEffect(() => { if (open) form.reset({ name: customer?.name ?? "", email: customer?.email ?? "", phone: customer?.phone ?? "", notes: customer?.notes ?? "" }); }, [open, customer, form]);
  const save = useAction((f: z.infer<typeof custSchema>) => {
    const body = { ...f, email: f.email || null, phone: f.phone || null, notes: f.notes || null };
    return customer ? api.put(`/customers/${customer.id}`, body) : api.post("/customers", body);
  }, { invalidate: ["customers"], success: "Customer saved", onSuccess: () => onOpenChange(false) });
  const e = form.formState.errors;
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={customer ? "Edit customer" : "New customer"}
      footer={<Button onClick={form.handleSubmit((f) => save.mutate(f))} loading={save.isPending}>Save</Button>}>
      <div className="space-y-3">
        <Field label="Name" htmlFor="c-n" error={e.name?.message}><Input id="c-n" {...form.register("name")} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Email" htmlFor="c-e" error={e.email?.message}><Input id="c-e" type="email" {...form.register("email")} /></Field>
          <Field label="Phone" htmlFor="c-p"><Input id="c-p" {...form.register("phone")} /></Field>
        </div>
        <Field label="Notes" htmlFor="c-no"><Textarea id="c-no" {...form.register("notes")} /></Field>
      </div>
    </Dialog>
  );
}

function AddressDialog({ open, onOpenChange, customerId }: { open: boolean; onOpenChange: (o: boolean) => void; customerId: number | null }) {
  const form = useForm<z.infer<typeof addrSchema>>({ resolver: zodResolver(addrSchema) });
  useEffect(() => { if (open) form.reset({ label: "", address_text: "", lat: "", lon: "" }); }, [open, form]);
  const save = useAction((f: z.infer<typeof addrSchema>) => api.post<Address>(`/customers/${customerId}/addresses`, {
    label: f.label || null, address_text: f.address_text, lat: f.lat ? Number(f.lat) : null, lon: f.lon ? Number(f.lon) : null,
  }), { invalidate: ["customers", "orders"], success: (a) => `Address added — location ${a.geocode_status}`, onSuccess: () => onOpenChange(false) });
  const e = form.formState.errors;
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Add delivery address" description="Without coordinates the address is geocoded with OpenStreetMap Nominatim; ambiguous or failed matches are flagged for review."
      footer={<Button onClick={form.handleSubmit((f) => save.mutate(f))} loading={save.isPending}>Add address</Button>}>
      <div className="space-y-3">
        <Field label="Label (optional)" htmlFor="a-l"><Input id="a-l" placeholder="e.g. Back entrance" {...form.register("label")} /></Field>
        <Field label="Address" htmlFor="a-t" error={e.address_text?.message}><Textarea id="a-t" {...form.register("address_text")} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Latitude (optional)" htmlFor="a-lat" error={e.lat?.message}><Input id="a-lat" inputMode="decimal" {...form.register("lat")} /></Field>
          <Field label="Longitude (optional)" htmlFor="a-lon" error={e.lon?.message}><Input id="a-lon" inputMode="decimal" {...form.register("lon")} /></Field>
        </div>
      </div>
    </Dialog>
  );
}

function ResolveDialog({ address, onOpenChange }: { address: Address | null; onOpenChange: (o: boolean) => void }) {
  const resolve = useAction((i: number) => api.post(`/addresses/${address!.id}/resolve`, { candidate_index: i }), {
    invalidate: ["customers", "orders"], success: "Location confirmed", onSuccess: () => onOpenChange(false),
  });
  return (
    <Dialog open={!!address} onOpenChange={onOpenChange} title="Confirm location" description={address?.address_text}>
      {!address?.geocode_candidates?.length ? <p className="text-sm text-muted-foreground">No candidates. Edit the address or enter coordinates.</p> : (
        <ul className="divide-y rounded-md border text-sm">
          {address.geocode_candidates.map((c, i) => (
            <li key={i} className="flex items-center justify-between gap-3 px-3 py-2">
              <div className="min-w-0"><p className="truncate">{c.label}</p><p className="text-xs text-muted-foreground tabular">{c.lat.toFixed(5)}, {c.lon.toFixed(5)} · {c.type}</p></div>
              <Button size="sm" variant="outline" onClick={() => resolve.mutate(i)}>Use</Button>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}

function CustomersTab() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const customers = useCustomers({ q, page, page_size: 15 });
  const [custDialog, setCustDialog] = useState<{ open: boolean; c: Customer | null }>({ open: false, c: null });
  const [addrFor, setAddrFor] = useState<number | null>(null);
  const [resolving, setResolving] = useState<Address | null>(null);
  const geocode = useAction((id: number) => api.post<Address>(`/addresses/${id}/geocode`), { invalidate: ["customers", "orders"], success: (a) => `Geocode result: ${a.geocode_status}` });
  const delCust = useAction((id: number) => api.del(`/customers/${id}`), { invalidate: ["customers"], success: "Customer deleted" });
  const delAddr = useAction((id: number) => api.del(`/addresses/${id}`), { invalidate: ["customers"], success: "Address deleted" });
  const items = customers.data?.items ?? [];
  return (
    <Card>
      <div className="flex flex-wrap gap-2 border-b p-3">
        <Input placeholder="Search customers…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} className="w-64" aria-label="Search customers" />
        <Button size="sm" className="ml-auto" onClick={() => setCustDialog({ open: true, c: null })}><Plus /> New customer</Button>
      </div>
      {customers.isLoading ? <TableSkeleton /> : customers.isError ? <ErrorState error={customers.error} onRetry={() => customers.refetch()} /> : items.length === 0 ? (
        <EmptyState icon={Users} title="No customers" description="Add customers manually or import orders from CSV." />
      ) : (
        <ul className="divide-y">
          {items.map((c) => (
            <li key={c.id} className="px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-medium">{c.name}</p>
                <span className="text-xs text-muted-foreground">{[c.email, c.phone].filter(Boolean).join(" · ")}</span>
                <div className="ml-auto flex gap-1">
                  <Button variant="outline" size="sm" onClick={() => setAddrFor(c.id)}><Plus /> Address</Button>
                  <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setCustDialog({ open: true, c })} aria-label="Edit customer"><Pencil /></Button>
                  <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => confirm(`Delete ${c.name}?`) && delCust.mutate(c.id)} aria-label="Delete customer"><Trash2 /></Button>
                </div>
              </div>
              {c.addresses.length === 0 ? <p className="mt-1 text-xs text-muted-foreground">No addresses.</p> : (
                <ul className="mt-2 space-y-1">
                  {c.addresses.map((a) => (
                    <li key={a.id} className="flex flex-wrap items-center gap-2 rounded-md bg-muted/40 px-2.5 py-1.5 text-xs">
                      <StatusBadge status={a.geocode_status} />
                      <span className="min-w-0 flex-1 truncate">{a.label && <b>{a.label}: </b>}{a.address_text}</span>
                      {a.lat !== null && <span className="tabular text-muted-foreground">{a.lat.toFixed(5)}, {a.lon?.toFixed(5)}</span>}
                      {a.geocode_status === "ambiguous" && <Button size="sm" variant="outline" onClick={() => setResolving(a)}>Choose match</Button>}
                      {["failed", "pending"].includes(a.geocode_status) && <Button size="sm" variant="outline" onClick={() => geocode.mutate(a.id)} loading={geocode.isPending && geocode.variables === a.id}><RefreshCw /> Geocode</Button>}
                      {a.geocode_status === "failed" && <span className="text-destructive">{a.geocode_label}</span>}
                      <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => confirm("Delete address?") && delAddr.mutate(a.id)} aria-label="Delete address"><Trash2 /></Button>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
      <Pagination page={page} pageSize={15} total={customers.data?.total ?? 0} onPage={setPage} />
      <CustomerDialog open={custDialog.open} onOpenChange={(o) => setCustDialog({ ...custDialog, open: o })} customer={custDialog.c} />
      <AddressDialog open={addrFor !== null} onOpenChange={(o) => !o && setAddrFor(null)} customerId={addrFor} />
      <ResolveDialog address={resolving} onOpenChange={(o) => !o && setResolving(null)} />
    </Card>
  );
}

/* -------------------------------------------------------------- warehouses */

const whSchema = z.object({
  name: z.string().trim().min(1, "Required"), address: z.string().optional(), lat: z.string().optional(), lon: z.string().optional(), notes: z.string().optional(), active: z.boolean(),
}).refine((v) => !!v.lat === !!v.lon, { path: ["lon"], message: "Provide both coordinates or neither" })
  .refine((v) => !!v.lat || !!v.address, { path: ["address"], message: "Enter an address or coordinates" });

function WarehouseDialog({ open, onOpenChange, wh }: { open: boolean; onOpenChange: (o: boolean) => void; wh: Warehouse | null }) {
  const form = useForm<z.infer<typeof whSchema>>({ resolver: zodResolver(whSchema) });
  useEffect(() => {
    if (open) form.reset({ name: wh?.name ?? "", address: wh?.address ?? "", lat: wh?.geocode_status === "manual" ? String(wh.lat) : "", lon: wh?.geocode_status === "manual" ? String(wh.lon) : "", notes: wh?.notes ?? "", active: wh?.active ?? true });
  }, [open, wh, form]);
  const save = useAction((f: z.infer<typeof whSchema>) => {
    const body = { name: f.name, address: f.address || null, lat: f.lat ? Number(f.lat) : null, lon: f.lon ? Number(f.lon) : null, notes: f.notes || null, active: f.active };
    return wh ? api.put<Warehouse>(`/warehouses/${wh.id}`, body) : api.post<Warehouse>("/warehouses", body);
  }, { invalidate: ["warehouses"], success: (w) => `Warehouse saved — location ${w.geocode_status}`, onSuccess: () => onOpenChange(false) });
  const e = form.formState.errors;
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={wh ? "Edit warehouse" : "New warehouse"} footer={<Button onClick={form.handleSubmit((f) => save.mutate(f))} loading={save.isPending}>Save</Button>}>
      <div className="space-y-3">
        <Field label="Name" htmlFor="w-n" error={e.name?.message}><Input id="w-n" {...form.register("name")} /></Field>
        <Field label="Address" htmlFor="w-a" error={e.address?.message} hint="Geocoded via OpenStreetMap Nominatim when no coordinates are given."><Input id="w-a" {...form.register("address")} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Latitude" htmlFor="w-lat"><Input id="w-lat" inputMode="decimal" {...form.register("lat")} /></Field>
          <Field label="Longitude" htmlFor="w-lon" error={e.lon?.message}><Input id="w-lon" inputMode="decimal" {...form.register("lon")} /></Field>
        </div>
        <Field label="Notes" htmlFor="w-no"><Textarea id="w-no" {...form.register("notes")} /></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" {...form.register("active")} /> Active</label>
      </div>
    </Dialog>
  );
}

function WarehousesTab() {
  const warehouses = useWarehouses();
  const [dlg, setDlg] = useState<{ open: boolean; wh: Warehouse | null }>({ open: false, wh: null });
  const del = useAction((id: number) => api.del(`/warehouses/${id}`), { invalidate: ["warehouses"], success: "Warehouse deleted" });
  const items = warehouses.data?.items ?? [];
  return (
    <Card>
      <div className="flex border-b p-3"><Button size="sm" className="ml-auto" onClick={() => setDlg({ open: true, wh: null })}><Plus /> New warehouse</Button></div>
      {warehouses.isLoading ? <TableSkeleton /> : warehouses.isError ? <ErrorState error={warehouses.error} onRetry={() => warehouses.refetch()} /> : items.length === 0 ? (
        <EmptyState icon={WarehouseIcon} title="No warehouses" description="Add the depots your deliveries start from." />
      ) : (
        <Table>
          <THead><TR><TH>Name</TH><TH>Address</TH><TH>Location</TH><TH>Status</TH><TH /></TR></THead>
          <TBody>
            {items.map((w) => (
              <TR key={w.id}>
                <TD className="font-medium">{w.name}{!w.active && <Badge tone="muted" className="ml-1">inactive</Badge>}</TD>
                <TD className="max-w-[280px] truncate text-xs">{w.address ?? "—"}</TD>
                <TD className="text-xs tabular text-muted-foreground">{w.lat !== null ? `${w.lat.toFixed(5)}, ${w.lon?.toFixed(5)}` : w.geocode_label ?? "—"}</TD>
                <TD><StatusBadge status={w.geocode_status} /></TD>
                <TD className="whitespace-nowrap text-right">
                  <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setDlg({ open: true, wh: w })} aria-label={`Edit ${w.name}`}><Pencil /></Button>
                  <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => confirm(`Delete ${w.name}?`) && del.mutate(w.id)} aria-label={`Delete ${w.name}`}><Trash2 /></Button>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      <WarehouseDialog open={dlg.open} onOpenChange={(o) => setDlg({ ...dlg, open: o })} wh={dlg.wh} />
    </Card>
  );
}
